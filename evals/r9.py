"""Ticket 14 Step 6: R9 held-out runner.

Runs the held-out voice-correction set through the same compile path as
production: prompts and schemas come from the frozen builders in
``framework/voice/prompt.py`` and ``framework/voice/schemas.py``, never a
copy. ``python -m evals.r9 --matcher`` is the offline baseline; model arms
(``--model <id> --effort <e> [--transport muse|local]``) refuse unless
``IKIGAI_R9_LIVE=1`` is set. One pass per case, no retries, one results file
per arm under ``evals/r9_results/``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from evals.r9_matcher import match, match_with_until_words
from framework.briefing.context import load_private_terms
from framework.glimmer.facts import LLMResponse
from framework.glimmer.llm import OpenAICompatibleClient, load_llm_config
from framework.proposal.client import EFFORTS, refuse_contributor_model
from framework.proposal.core import WonderRequest, WonderResponse
from framework.proposal.muse_client import MuseExecClient
from framework.voice.prompt import (
    PromptCommitment,
    PromptOffer,
    build_compile_prompt,
)
from framework.voice.schemas import (
    UnparseableCorrection as _UnparseableCorrection,
)
from framework.voice.schemas import (
    build_correction_schema,
    parse_compiled,
    validate_compiled,
)

CASES_PATH = Path("evals/r9_cases.json")
RESULTS_DIR = Path("evals/r9_results")
REAL_FILE_SHA256 = "3b79eb01bbd914c30933235238c8cfc3ffe3fec880db092c821e75fd8f9c6707"
LIVE_VAR = "IKIGAI_R9_LIVE"
EXPECTED_REAL_CASES = 60

OPERATIONS = (
    "skip",
    "defer",
    "drop",
    "done",
    "keep",
    "fact_correction",
    "none",
)
UNTILS = ("slot", "today", "tomorrow", "this_week", "open")
REPLY_KEYS = ("operation", "commitment_id", "until", "question")
FIELDS = ("commitment_id", "operation", "until")
TRAPS = (
    None,
    "negation",
    "double_negation",
    "other_commitment",
    "fact_vs_commitment",
    "self_correction",
    "scope_word",
    "already_done",
    "underdetermined",
    "off_topic",
    "instruction_in_note",
)
LANGS = ("en", "es", "mixed")

_ALLOWED_PAIRS = frozenset(
    [
        ("skip", "slot"),
        ("skip", "today"),
        ("skip", "tomorrow"),
        ("skip", "this_week"),
        ("skip", "open"),
        ("defer", "today"),
        ("defer", "tomorrow"),
        ("defer", "this_week"),
        ("drop", "open"),
        ("done", "today"),
        ("keep", None),
        ("fact_correction", None),
        ("none", None),
    ]
)


@dataclass(frozen=True)
class R9Commitment:
    id: str
    title: str
    side: str


@dataclass(frozen=True)
class R9Offer:
    label: str
    title: str
    slot: str


@dataclass(frozen=True)
class R9Card:
    shown_at: str
    proposals: tuple[R9Offer, ...]
    cited_statements: tuple[str, ...]


@dataclass(frozen=True)
class R9Case:
    id: int | str
    now: str
    weekday: str
    transcript: str
    trap: str | None
    accepted: tuple[dict[str, Any], ...]
    requires_question: bool
    pinned: tuple[str, ...]
    lang: str
    noise: bool


@dataclass(frozen=True)
class R9File:
    schema: Any
    commitments: tuple[R9Commitment, ...]
    card: R9Card
    cases: tuple[R9Case, ...]


class MuseTransport(Protocol):
    """Structural client for the muse arm; fakes satisfy it in tests."""

    @property
    def transport_version(self) -> str | None: ...

    def complete(self, request: WonderRequest) -> WonderResponse: ...


class LocalTransport(Protocol):
    """Structural client for the local arm; fakes satisfy it in tests."""

    def complete(self, prompt: str) -> LLMResponse: ...


@dataclass(frozen=True)
class ScoredReply:
    passed: bool
    fields: dict[str, bool]
    question_ok: bool
    fence_recovered: bool
    correct_ignoring_pinned_fields: bool
    validation_codes: tuple[str, ...]


def _need(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ValueError(f"r9: {where} is missing {key!r}")
    return mapping[key]


def _need_str(mapping: Mapping[str, Any], key: str, where: str) -> str:
    value = _need(mapping, key, where)
    if not isinstance(value, str):
        raise TypeError(f"r9: {where} field {key!r} must be a string")
    return value


def _need_case_id(mapping: Mapping[str, Any], key: str, where: str) -> int | str:
    value = _need(mapping, key, where)
    if isinstance(value, bool):
        raise TypeError(f"r9: {where} field {key!r} must be an integer or a string")
    if isinstance(value, (int, str)):
        return value
    raise TypeError(f"r9: {where} field {key!r} must be an integer or a string")


def _check_accepted(entry: Any, where: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise TypeError(f"r9: {where} accepted entries must be objects")
    for key in ("commitment_id", "operation", "until"):
        if key not in entry:
            raise ValueError(f"r9: {where} accepted entry misses {key!r}")
    cid = entry["commitment_id"]
    if cid is not None and not isinstance(cid, str):
        raise TypeError(f"r9: {where} commitment_id must be a string or null")
    if entry["operation"] not in OPERATIONS:
        raise ValueError(f"r9: {where} has an unknown operation")
    if entry["until"] is not None and entry["until"] not in UNTILS:
        raise ValueError(f"r9: {where} has an unknown until value")
    if (entry["operation"], entry["until"]) not in _ALLOWED_PAIRS:
        raise ValueError(f"r9: {where} has a disallowed operation/until pair")
    return {
        "commitment_id": cid,
        "operation": entry["operation"],
        "until": entry["until"],
    }


def load_cases(path: str | Path, *, expected_cases: int | None = 60) -> R9File:
    """Load and shape-check the held-out file.

    The case count is checked when ``expected_cases`` is not None; the real
    file runs with the default 60 while a synthetic fixture passes its own
    smaller count (or None to skip the check).
    """
    raw = json.loads(Path(path).read_bytes().decode("utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("r9: cases file must hold a JSON object")
    for key in ("schema", "commitments", "card", "cases"):
        if key not in raw:
            raise ValueError(f"r9: cases file is missing {key!r}")
    commitments: list[R9Commitment] = []
    for row in raw["commitments"]:
        if not isinstance(row, dict):
            raise TypeError("r9: commitments must hold objects")
        commitments.append(
            R9Commitment(
                id=_need_str(row, "id", "commitment"),
                title=_need_str(row, "title", "commitment"),
                side=_need_str(row, "side", "commitment"),
            )
        )
    card_raw = raw["card"]
    if not isinstance(card_raw, dict):
        raise TypeError("r9: card must hold an object")
    offers: list[R9Offer] = []
    proposals = _need(card_raw, "proposals", "card")
    if not isinstance(proposals, list):
        raise TypeError("r9: card proposals must hold a list")
    for row in proposals:
        if not isinstance(row, dict):
            raise TypeError("r9: card proposals must hold objects")
        offers.append(
            R9Offer(
                label=_need_str(row, "label", "card proposal"),
                title=_need_str(row, "title", "card proposal"),
                slot=_need_str(row, "slot", "card proposal"),
            )
        )
    cited = _need(card_raw, "cited_statement", "card")
    if isinstance(cited, str):
        statements = (cited,)
    elif isinstance(cited, list) and all(isinstance(s, str) for s in cited):
        statements = tuple(cited)
    else:
        raise TypeError("r9: card cited_statement must be a string or strings")
    card = R9Card(
        shown_at=_need_str(card_raw, "shown_at", "card"),
        proposals=tuple(offers),
        cited_statements=statements,
    )
    cases_raw = raw["cases"]
    if not isinstance(cases_raw, list):
        raise TypeError("r9: cases must hold a list")
    cases: list[R9Case] = []
    for row in cases_raw:
        if not isinstance(row, dict):
            raise TypeError("r9: cases must hold objects")
        where = f"case {row.get('id', '?')!r}"
        trap = _need(row, "trap", where)
        if trap not in TRAPS:
            raise ValueError(f"r9: {where} has an unknown trap")
        accepted_raw = _need(row, "accepted", where)
        if not isinstance(accepted_raw, list) or not accepted_raw:
            raise ValueError(f"r9: {where} needs a non-empty accepted list")
        accepted = tuple(_check_accepted(e, where) for e in accepted_raw)
        pinned_raw = _need(row, "pinned_by_coordinator_silence", where)
        if not isinstance(pinned_raw, list) or any(
            not isinstance(p, str) for p in pinned_raw
        ):
            raise TypeError(f"r9: {where} pinned fields must be strings")
        lang = _need(row, "lang", where)
        if lang not in LANGS:
            raise ValueError(f"r9: {where} has an unknown lang")
        noise = _need(row, "noise", where)
        if not isinstance(noise, bool):
            raise TypeError(f"r9: {where} noise must be a bool")
        questions = _need(row, "requires_question", where)
        if not isinstance(questions, bool):
            raise TypeError(f"r9: {where} requires_question must be a bool")
        cases.append(
            R9Case(
                id=_need_case_id(row, "id", where),
                now=_need_str(row, "now", where),
                weekday=_need_str(row, "weekday", where),
                transcript=_need_str(row, "transcript", where),
                trap=trap,
                accepted=accepted,
                requires_question=questions,
                pinned=tuple(pinned_raw),
                lang=lang,
                noise=noise,
            )
        )
    if expected_cases is not None and len(cases) != expected_cases:
        raise ValueError(f"r9: expected {expected_cases} cases, found {len(cases)}")
    return R9File(
        schema=raw["schema"],
        commitments=tuple(commitments),
        card=card,
        cases=tuple(cases),
    )


def prompt_for_case(data: R9File, case: R9Case) -> str:
    """Build the prompt through the production builder at the case's now."""
    now = datetime.fromisoformat(case.now)
    commitments = [
        PromptCommitment(id=c.id, title=c.title, side=c.side) for c in data.commitments
    ]
    offers = [
        PromptOffer(label=o.label, title=o.title, slot=now) for o in data.card.proposals
    ]
    return build_compile_prompt(
        transcript=case.transcript,
        commitments=commitments,
        offers=offers,
        statements=list(data.card.cited_statements),
        now_local=now,
    )


def _strip_to_json(text: str) -> str:
    """Unwrap one markdown fence and surrounding prose, if either is there."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        return candidate[start : end + 1]
    return candidate


def fence_recovered(text: str) -> bool:
    """Would stripping a fence or prose have given valid JSON (an object)."""
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        pass
    else:
        return False
    try:
        return isinstance(json.loads(_strip_to_json(text)), dict)
    except (ValueError, RecursionError):
        return False


_MISSING: Any = object()


def _best_entry(
    loaded: dict[str, Any], accepted: Sequence[dict[str, Any]], skip: Collection[str]
) -> dict[str, Any]:
    best = accepted[0]
    best_hits = -1
    for entry in accepted:
        hits = sum(
            1
            for name in FIELDS
            if name not in skip and name in loaded and loaded[name] == entry[name]
        )
        if hits > best_hits:
            best = entry
            best_hits = hits
    return best


def _question_ok(loaded: dict[str, Any], requires_question: bool) -> bool:
    if not requires_question:
        return True
    question = loaded.get("question")
    return isinstance(question, str) and bool(question.strip())


def _values_allowed(loaded: dict[str, Any]) -> bool:
    if loaded.get("operation") not in OPERATIONS:
        return False
    commitment_id = loaded.get("commitment_id", _MISSING)
    if commitment_id is _MISSING:
        return False
    if commitment_id is not None and not isinstance(commitment_id, str):
        return False
    until = loaded.get("until", _MISSING)
    if until is _MISSING:
        return False
    if until is not None and until not in UNTILS:
        return False
    question = loaded.get("question", _MISSING)
    if question is _MISSING:
        return False
    return question is None or isinstance(question, str)


def _validation_codes(
    text: str,
    known_ids: Collection[str],
    private_terms: tuple[str, ...],
    private_terms_available: bool,
) -> tuple[str, ...]:
    parsed = parse_compiled(text)
    if isinstance(parsed, _UnparseableCorrection):
        return ("CORRECTION_SCHEMA_INVALID",)
    return validate_compiled(
        parsed,
        known_ids,
        private_terms=private_terms,
        private_terms_available=private_terms_available,
        forbidden_raw_literals=(),
    )


def score_reply(
    text: str,
    case: R9Case,
    *,
    known_ids: Collection[str],
    private_terms: tuple[str, ...] = (),
    private_terms_available: bool = False,
) -> ScoredReply:
    """Score one reply under D31: strict parse, best-entry fields, question."""
    try:
        loaded: Any = json.loads(text)
    except (ValueError, RecursionError):
        loaded = None
    valid_shape = isinstance(loaded, dict)
    keys_ok = valid_shape and set(loaded.keys()) == set(REPLY_KEYS)
    values_ok = bool(keys_ok) and _values_allowed(loaded)
    abstention = (
        valid_shape
        and "commitment_id" in loaded
        and loaded.get("operation") == "none"
        and loaded.get("commitment_id") is None
    )
    if not valid_shape or (abstention and not case.requires_question):
        fields = {name: False for name in FIELDS}
        passed = False
    else:
        best = _best_entry(loaded, case.accepted, ())
        fields = {
            name: name in loaded and loaded[name] == best[name] for name in FIELDS
        }
        question_ok = _question_ok(loaded, case.requires_question)
        passed = bool(values_ok) and all(fields.values()) and question_ok
    ignoring = _score_ignoring_pinned(loaded, case)
    codes = _validation_codes(text, known_ids, private_terms, private_terms_available)
    return ScoredReply(
        passed=passed,
        fields=fields,
        question_ok=(
            _question_ok(loaded, case.requires_question) if valid_shape else False
        ),
        fence_recovered=fence_recovered(text),
        correct_ignoring_pinned_fields=ignoring,
        validation_codes=codes,
    )


def _score_ignoring_pinned(loaded: Any, case: R9Case) -> bool:
    """The same pass comparison with the pinned fields left out."""
    if not isinstance(loaded, dict):
        return False
    if (
        loaded.get("operation") == "none"
        and loaded.get("commitment_id") is None
        and not case.requires_question
    ):
        return False
    if set(loaded.keys()) != set(REPLY_KEYS):
        return False
    if not _values_allowed(loaded):
        return False
    if not _question_ok(loaded, case.requires_question):
        return False
    pinned = set(case.pinned)
    rest = [name for name in FIELDS if name not in pinned]
    if not rest:
        return True
    best = _best_entry(loaded, case.accepted, pinned)
    return all(name in loaded and loaded[name] == best[name] for name in rest)


def rules_file_present(environ: Mapping[str, str] | None = None) -> bool:
    """Whether a personal rules file is present (true or false only).

    Assumption: the file lives at ``muse/AGENTS.md`` under ``XDG_CONFIG_HOME``
    (else ``~/.config``) or at ``~/.muse/AGENTS.md``; the plan names no path,
    so this is a stated guess the reviewer runs with it absent.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    candidates: list[Path] = []
    xdg = env.get("XDG_CONFIG_HOME", "")
    home = env.get("HOME", "")
    if xdg:
        candidates.append(Path(xdg) / "muse" / "AGENTS.md")
    if home:
        candidates.append(Path(home) / ".config" / "muse" / "AGENTS.md")
        candidates.append(Path(home) / ".muse" / "AGENTS.md")
    return any(p.is_file() for p in candidates)


def _commitment_rows(data: R9File) -> list[dict[str, Any]]:
    return [{"id": c.id, "title": c.title} for c in data.commitments]


def _score_row(
    *,
    case: R9Case,
    text: str,
    latency_s: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model: str,
    effort: str,
    transport: str,
    muse_version: str | None,
    rules_present: bool,
    known_ids: Collection[str],
    private_terms: tuple[str, ...],
    private_terms_available: bool,
    transport_error: str | None,
) -> dict[str, Any]:
    scored = score_reply(
        text,
        case,
        known_ids=known_ids,
        private_terms=private_terms,
        private_terms_available=private_terms_available,
    )
    try:
        loaded: Any = json.loads(text)
    except (ValueError, RecursionError):
        loaded = None
    triple = {
        name: loaded.get(name) if isinstance(loaded, dict) else None for name in FIELDS
    }
    question = loaded.get("question") if isinstance(loaded, dict) else None
    return {
        "case_id": case.id,
        "trap": case.trap,
        "lang": case.lang,
        "noise": case.noise,
        "operation": triple["operation"],
        "commitment_id": triple["commitment_id"],
        "until": triple["until"],
        "question_present": isinstance(question, str) and bool(question.strip()),
        "passed": scored.passed,
        "correct_ignoring_pinned_fields": scored.correct_ignoring_pinned_fields,
        "fence_recovered": scored.fence_recovered,
        "validation_codes": list(scored.validation_codes),
        "fields": dict(scored.fields),
        "latency_s": latency_s,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "model": model,
        "effort": effort,
        "transport": transport,
        "muse_version": muse_version,
        "rules_file_present": rules_present,
        "transport_error": transport_error,
    }


def _summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    per_trap: dict[str, dict[str, int]] = {}
    per_lang: dict[str, dict[str, int]] = {}
    per_noise: dict[str, dict[str, int]] = {}
    per_field = {name: 0 for name in FIELDS}
    latencies: list[float] = []
    total_tokens = 0
    passed = 0
    ignoring = 0
    refused = 0
    transport_errors = 0
    for row in rows:
        trap_key = row["trap"] if isinstance(row["trap"], str) else "none"
        bucket = per_trap.setdefault(trap_key, {"total": 0, "passed": 0})
        bucket["total"] += 1
        lang_bucket = per_lang.setdefault(row["lang"], {"total": 0, "passed": 0})
        lang_bucket["total"] += 1
        noise_key = "true" if row["noise"] else "false"
        noise_bucket = per_noise.setdefault(noise_key, {"total": 0, "passed": 0})
        noise_bucket["total"] += 1
        if row["passed"]:
            passed += 1
            bucket["passed"] += 1
            lang_bucket["passed"] += 1
            noise_bucket["passed"] += 1
        for name in FIELDS:
            if row["fields"][name]:
                per_field[name] += 1
        if row["correct_ignoring_pinned_fields"]:
            ignoring += 1
        if row["passed"] and row["validation_codes"]:
            refused += 1
        if row.get("transport_error") is not None:
            transport_errors += 1
        latencies.append(row["latency_s"])
        for key in ("prompt_tokens", "completion_tokens"):
            if isinstance(row[key], int):
                total_tokens += row[key]
    return {
        "total": len(rows),
        "passed": passed,
        "per_field": per_field,
        "per_trap": per_trap,
        "per_lang": per_lang,
        "per_noise": per_noise,
        "correct_ignoring_pinned_fields": ignoring,
        "passes_refused_by_validation": refused,
        "transport_errors": transport_errors,
        "latency_median_s": statistics.median(latencies) if latencies else 0.0,
        "latency_worst_s": max(latencies) if latencies else 0.0,
        "total_tokens": total_tokens,
    }


def _write_results(
    results_dir: Path,
    *,
    arm: str,
    model: str,
    effort: str,
    transport: str,
    private_terms_available: bool,
    rows: list[dict[str, Any]],
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{arm}.json"
    path.write_text(
        json.dumps(
            {
                "arm": arm,
                "model": model,
                "effort": effort,
                "transport": transport,
                "private_terms_available": private_terms_available,
                "rows": rows,
                "summary": _summarise(rows),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_matcher_arms(
    data: R9File,
    *,
    results_dir: Path,
    private_terms: tuple[str, ...],
    private_terms_available: bool,
    rules_present: bool,
) -> list[Path]:
    known_ids = [c.id for c in data.commitments]
    rows_by_arm: dict[str, list[dict[str, Any]]] = {
        "matcher": [],
        "matcher-until-words": [],
    }
    for case in data.cases:
        commitment_rows = _commitment_rows(data)
        for arm, matched in (
            ("matcher", match(case.transcript, commitment_rows)),
            (
                "matcher-until-words",
                match_with_until_words(case.transcript, commitment_rows),
            ),
        ):
            start = time.monotonic()
            text = json.dumps(matched)
            latency_s = time.monotonic() - start
            rows_by_arm[arm].append(
                _score_row(
                    case=case,
                    text=text,
                    latency_s=latency_s,
                    prompt_tokens=None,
                    completion_tokens=None,
                    model=arm,
                    effort="none",
                    transport="matcher",
                    muse_version=None,
                    rules_present=rules_present,
                    known_ids=known_ids,
                    private_terms=private_terms,
                    private_terms_available=private_terms_available,
                    transport_error=None,
                )
            )
    return [
        _write_results(
            results_dir,
            arm=arm,
            model=arm,
            effort="none",
            transport="matcher",
            private_terms_available=private_terms_available,
            rows=rows,
        )
        for arm, rows in rows_by_arm.items()
    ]


def _run_model_arm(
    data: R9File,
    *,
    transport: str,
    model: str,
    effort: str,
    results_dir: Path,
    private_terms: tuple[str, ...],
    private_terms_available: bool,
    rules_present: bool,
    muse_client: MuseTransport | None = None,
    local_client: LocalTransport | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    known_ids = [c.id for c in data.commitments]
    muse_transport: MuseTransport | None = None
    local_transport: LocalTransport | None = None
    if transport == "muse":
        if muse_client is None:
            muse_transport = MuseExecClient(
                private_terms=private_terms,
                private_terms_available=private_terms_available,
                timeout_s=60,
            )
        else:
            muse_transport = muse_client
        version = muse_transport.transport_version
    else:
        config = load_llm_config(environ)
        if local_client is None:
            local_transport = OpenAICompatibleClient(
                config.base_url, config.model, config.api_key
            )
        else:
            local_transport = local_client
        version = None
    recorded_effort = effort if transport == "muse" else "local"
    rows: list[dict[str, Any]] = []
    ids = [c.id for c in data.commitments]
    for case in data.cases:
        prompt = prompt_for_case(data, case)
        schema = build_correction_schema(ids)
        start = time.monotonic()
        text = ""
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        transport_error: str | None = None
        try:
            if transport == "muse":
                assert muse_transport is not None
                response = muse_transport.complete(
                    WonderRequest(
                        prompt=prompt,
                        model=model,
                        effort=effort,
                        response_schema=schema,
                        schema_name="voice_correction",
                        forbidden_raw_literals=(),
                    )
                )
                text = response.text
                prompt_tokens = response.prompt_tokens
                completion_tokens = response.completion_tokens
            else:
                assert local_transport is not None
                reply = local_transport.complete(prompt)
                text = reply.text
                completion_tokens = reply.completion_tokens
        except Exception as exc:  # noqa: BLE001 - one pass, no retry; a miss is a row
            text = ""
            transport_error = type(exc).__name__
        latency_s = time.monotonic() - start
        rows.append(
            _score_row(
                case=case,
                text=text,
                latency_s=latency_s,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=model,
                effort=recorded_effort,
                transport=transport,
                muse_version=version,
                rules_present=rules_present,
                known_ids=known_ids,
                private_terms=private_terms,
                private_terms_available=private_terms_available,
                transport_error=transport_error,
            )
        )
    arm = f"{transport}-{model}-{recorded_effort}"
    return _write_results(
        results_dir,
        arm=arm,
        model=model,
        effort=recorded_effort,
        transport=transport,
        private_terms_available=private_terms_available,
        rows=rows,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cases_path: str | Path | None = None,
    results_dir: str | Path | None = None,
    muse_client: MuseTransport | None = None,
    local_client: LocalTransport | None = None,
) -> int:
    """Entry point; injectable paths and clients keep tests offline."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="R9 voice-correction runner")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--transport", default="muse", choices=("muse", "local"))
    parser.add_argument("--matcher", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    wants_model = args.model is not None
    if not wants_model and not args.matcher:
        print(
            "r9: refusing: no arm chosen (pass --model or --matcher)",
            file=sys.stderr,
        )
        return 1
    if wants_model and env.get(LIVE_VAR) != "1":
        print(
            f"r9: refusing: {LIVE_VAR}=1 is not set; model arms need it",
            file=sys.stderr,
        )
        return 1
    path = Path(cases_path) if cases_path is not None else CASES_PATH
    try:
        data = load_cases(
            path,
            expected_cases=(
                EXPECTED_REAL_CASES if path.resolve() == CASES_PATH.resolve() else None
            ),
        )
    except FileNotFoundError:
        print(f"r9: refusing: cases file absent: {path}", file=sys.stderr)
        return 1
    except (ValueError, TypeError) as exc:
        print(f"r9: refusing: {exc}", file=sys.stderr)
        return 1
    if wants_model and args.transport == "muse":
        if args.effort is None:
            print(
                "r9: refusing: --effort is required with --transport muse",
                file=sys.stderr,
            )
            return 1
        if args.effort not in EFFORTS:
            print("r9: refusing: unknown effort", file=sys.stderr)
            return 1
        try:
            refuse_contributor_model(args.model or "")
        except Exception:  # noqa: BLE001 - refusal names the rule only
            print("r9: refusing: contributor models are refused", file=sys.stderr)
            return 1
    terms = load_private_terms(env, allow_missing_for_tests=True)
    out = Path(results_dir) if results_dir is not None else RESULTS_DIR
    rules_present = rules_file_present(env)
    written: list[Path] = []
    if wants_model:
        assert args.model is not None
        try:
            written.append(
                _run_model_arm(
                    data,
                    transport=args.transport,
                    model=args.model,
                    effort=args.effort or "local",
                    results_dir=out,
                    private_terms=terms.terms,
                    private_terms_available=terms.available,
                    rules_present=rules_present,
                    muse_client=muse_client,
                    local_client=local_client,
                    environ=env,
                )
            )
        except SystemExit as exc:
            print(f"r9: refusing: {exc}", file=sys.stderr)
            return 1
    if args.matcher:
        written.extend(
            _run_matcher_arms(
                data,
                results_dir=out,
                private_terms=terms.terms,
                private_terms_available=terms.available,
                rules_present=rules_present,
            )
        )
    for done in written:
        print(f"r9: wrote {done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
