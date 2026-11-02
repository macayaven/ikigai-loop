"""Ticket 10b Stage 1: offline red-team runner.

Runs each attack (or true sentence) from an input file against the real
``evaluate_briefing`` gate in one fixed synthetic context, and records one
row per input. Offline, deterministic: no network, no model, no clock, no
env read except the frozen-file git stamp (read from git, never from
``HIDDEN_CRITERIA_DIR``).

Usage::

    python -m evals.redteam docs/redteam/round-1.json [--write-frozen]
    python -m evals.redteam --summary [--markdown]
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.briefing.gate import evaluate_briefing
from framework.briefing.schemas import Commitment
from framework.schemas.core import Fact

REPO_ROOT = Path(__file__).resolve().parents[1]
REDTEAM_DIR = REPO_ROOT / "docs" / "redteam"
GATE_DIR = REPO_ROOT / "framework" / "briefing"

TARGETS = frozenset({"A", "B", "C", "D", "E", "F"})
ROUND_RE = re.compile(r"^round-(\d+)\.json$")

# Pinned fixed runner context (plan section "Fixed runner context").
_METRIC_VALUES: dict[str, float] = {
    "period.earlier.pushes": 3,
    "period.prior.pushes": 1,
    "period.last.pushes": 0,
    "period.prior.screen_hours.Work/Programming": 4.75,
    "period.last.screen_hours.Work/Programming": 1.75,
    "period.last.screen_hours.Media/Video": 4,
    "github.push.count": 4,
    "calendar.busy_hours": 6.5,
}
_FACT_STATEMENTS: dict[str, str] = {
    "f1": "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
    "f2": "Programming screen hours fell from 4.75 in prior to 1.75 in last.",
}
_WINDOW_START = "2026-10-30T00:00:00+01:00"
_WINDOW_END = "2026-10-31T12:00:00+01:00"
_HOST_CLAIM_TEXT = "Pushes fell from 3 in earlier to 1 in prior and to 0 in last."


def _fact_payload(fid: str, statement: str) -> dict[str, Any]:
    return {
        "id": fid,
        "subject_id": "subject-1",
        "window": {"start": _WINDOW_START, "end": _WINDOW_END},
        "statement": statement,
        "evidence": ["synthetic log"],
        "tier": "public",
    }


def build_context(
    extra_facts: list[dict[str, Any]] | None = None,
) -> GateContext:
    """Build the one fixed synthetic ``GateContext``.

    ``extra_facts`` (``[{"id": ..., "statement": ...}]``) are added to a
    copy of the context for a single review row only, using the pinned
    window, subject, evidence and tier.
    """
    facts = {
        fid: Fact.model_validate(_fact_payload(fid, statement))
        for fid, statement in _FACT_STATEMENTS.items()
    }
    for extra in extra_facts or []:
        facts[extra["id"]] = Fact.model_validate(
            _fact_payload(extra["id"], extra["statement"])
        )
    return GateContext(
        facts=facts,
        metrics=MetricSnapshot(values=dict(_METRIC_VALUES)),
        parent_briefing=None,
        parent_metrics=None,
        free_intervals=(
            TimeInterval(
                start=datetime.fromisoformat("2026-10-31T13:00:00+01:00"),
                end=datetime.fromisoformat("2026-10-31T23:30:00+01:00"),
            ),
        ),
        busy_intervals=(
            TimeInterval(
                start=datetime.fromisoformat("2026-10-31T15:00:00+01:00"),
                end=datetime.fromisoformat("2026-10-31T16:00:00+01:00"),
            ),
        ),
        limits=ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start=time(13, 0),
            allowed_end=time(23, 30),
            max_actions=3,
        ),
        check_slot=True,
        private_terms=("Zebrafinch", "Quillon"),
        private_terms_available=True,
        raw_metric_ids=frozenset(),
        forbidden_raw_literals=("Dentist on Tuesday",),
        commitments=(
            Commitment(
                id="c1",
                profile_id="builder",
                title="Ship one small change",
                kind="build",
                dimension="good_at",
                evidence="tap",
            ),
        ),
        commitments_available=True,
    )


def build_host_briefing(
    claim_text: str,
    fact_ids: list[str],
    metric_refs: list[dict[str, Any]],
    claim_id: str = "claim-attack",
) -> dict[str, Any]:
    """Build the host briefing with the input claim in ``working``.

    A fresh deep copy per call: callers mutate nothing shared.
    """
    return {
        "id": "brf-redteam-host",
        "profile_id": "builder",
        "subject_id": "subject-1",
        "slot": "2026-10-31T13:00:00+01:00",
        "parent_briefing_id": None,
        "sections": [
            {
                "type": "overall_state",
                "claims": [
                    {
                        "id": "claim-host",
                        "text": _HOST_CLAIM_TEXT,
                        "fact_ids": [],
                        "metric_refs": [
                            {"metric_id": "period.earlier.pushes", "value": 3},
                            {"metric_id": "period.prior.pushes", "value": 1},
                            {"metric_id": "period.last.pushes", "value": 0},
                        ],
                    }
                ],
                "actions": [],
            },
            {
                "type": "working",
                "claims": [
                    {
                        "id": claim_id,
                        "text": claim_text,
                        "fact_ids": list(fact_ids),
                        "metric_refs": copy.deepcopy(metric_refs),
                    }
                ],
                "actions": [],
            },
            {"type": "not_working", "claims": [], "actions": []},
            {
                "type": "actions",
                "claims": [],
                "actions": [
                    {
                        "id": "act-host",
                        "commitment_id": "c1",
                        "kind": "build",
                        "text": "Ship one small change",
                        "dimension": "good_at",
                        "proposed_start": "2026-10-31T14:00:00+01:00",
                        "proposed_end": "2026-10-31T14:45:00+01:00",
                    }
                ],
            },
        ],
    }


def run_claim(
    claim_text: str,
    fact_ids: list[str],
    metric_refs: list[dict[str, Any]],
    context: GateContext,
) -> dict[str, Any]:
    """Run one claim in a fresh host briefing; a raise never kills a run."""
    briefing = build_host_briefing(claim_text, fact_ids, metric_refs)
    try:
        result = evaluate_briefing(briefing, context)
    except Exception as exc:  # noqa: BLE001 - the type name is the record
        return {"passed": False, "codes": [], "raised": type(exc).__name__}
    return {
        "passed": result.passed,
        "codes": sorted({v.code for v in result.violations}),
        "raised": None,
    }


# ---------------------------------------------------------------------------
# Input loading and validation.
# ---------------------------------------------------------------------------


def _fail(path: Path, index: int, entry_id: str, reason: str) -> ValueError:
    return ValueError(f"{path}: row {index} ({entry_id}): {reason}")


def _check_claim(
    path: Path, index: int, entry_id: str, claim: Any
) -> tuple[str, list[str], list[dict[str, Any]]]:
    if not isinstance(claim, dict):
        raise _fail(path, index, entry_id, "claim must be an object")
    text = claim.get("text")
    if not isinstance(text, str) or not text:
        raise _fail(path, index, entry_id, "claim is missing text")
    fact_ids = claim.get("fact_ids", [])
    metric_refs = claim.get("metric_refs", [])
    if not isinstance(fact_ids, list) or not all(isinstance(f, str) for f in fact_ids):
        raise _fail(path, index, entry_id, "claim fact_ids must be strings")
    if not isinstance(metric_refs, list) or not all(
        isinstance(r, dict) for r in metric_refs
    ):
        raise _fail(path, index, entry_id, "claim metric_refs must be objects")
    return text, list(fact_ids), copy.deepcopy(metric_refs)


def load_input(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Load and validate an input file.

    Returns ``("attacks", entries)`` or ``("sentences", entries)``; each
    entry holds ``id`` plus the validated ``claim`` triple. Raises
    ``ValueError`` naming the file and row index on any malformed input.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot parse input: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: input must be an object")  # noqa: TRY004
    has_attacks = "attacks" in raw
    has_sentences = "sentences" in raw
    if has_attacks == has_sentences:
        raise ValueError(
            f"{path}: input must hold either attacks or sentences, never both"
        )
    kind = "attacks" if has_attacks else "sentences"
    entries = raw[kind]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: {kind} must be a non-empty list")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _fail(path, index, "?", "entry must be an object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise _fail(path, index, "?", "duplicate or empty id")
        if entry_id in seen:
            raise _fail(path, index, entry_id, "duplicate or empty id")
        seen.add(entry_id)
        text, fact_ids, metric_refs = _check_claim(
            path, index, entry_id, entry.get("claim")
        )
        item: dict[str, Any] = {
            "id": entry_id,
            "text": text,
            "fact_ids": fact_ids,
            "metric_refs": metric_refs,
        }
        if kind == "attacks":
            target = entry.get("target")
            predicted = entry.get("predicted_passes")
            if target not in TARGETS:
                raise _fail(path, index, entry_id, "target outside A to F")
            if not isinstance(predicted, bool):
                raise _fail(path, index, entry_id, "predicted_passes must be a boolean")
            item["target"] = target
            item["predicted_passes"] = predicted
        out.append(item)
    return kind, out


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _current_path(input_path: Path) -> Path:
    return input_path.with_name(input_path.stem + ".results.json")


def _frozen_path(input_path: Path) -> Path:
    return input_path.with_name(input_path.stem + ".frozen.json")


def _adjudication_path(input_path: Path) -> Path:
    return input_path.with_name(input_path.stem + ".adjudicated.json")


# ---------------------------------------------------------------------------
# Frozen-file stamps (git only; HIDDEN_CRITERIA_DIR is never read).
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def gate_files_sha256() -> str:
    """SHA-256 over the sorted ``framework/briefing/*.py`` paths+contents.

    For each path in sorted order, hash the UTF-8 path, a NUL byte, the
    file bytes, and a NUL byte.
    """
    digest = hashlib.sha256()
    for path in sorted(GATE_DIR.glob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def frozen_stamps(input_path: Path) -> dict[str, Any]:
    """Collect the D3 stamps for a frozen file."""
    dirty = (
        subprocess.run(
            ["git", "status", "--porcelain", "--", "framework/briefing/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        != ""
    )
    return {
        "gate_commit": _git("rev-parse", "HEAD"),
        "gate_tree": _git("rev-parse", "HEAD^{tree}"),
        "gate_files_sha256": gate_files_sha256(),
        "gate_dirty": dirty,
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Running.
# ---------------------------------------------------------------------------


def load_adjudication(input_path: Path) -> dict[str, Any] | None:
    """Load the sibling adjudication file, if one exists."""
    path = _adjudication_path(input_path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot parse adjudication: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(
        raw.get("found_in_review", []), list
    ):
        raise ValueError(  # noqa: TRY004
            f"{path}: adjudication has no found_in_review list"
        )
    return raw


def _check_extra_metrics(
    source: Path, index: int, entry_id: str, entry: dict[str, Any]
) -> dict[str, float]:
    """Validate a review row's optional ``extra_metrics`` object.

    Returns ``{metric_id: number}``; a value that is not a finite
    number, or an entry that is not an object, raises ``ValueError``
    naming the file and the row, as ``extra_facts`` does.
    """
    extra_metrics: Any = entry.get("extra_metrics", {})
    if not isinstance(extra_metrics, dict):
        raise ValueError(  # noqa: TRY004
            f"{source}: review row {index} ({entry_id}): "
            "extra_metrics must be an object"
        )
    checked: dict[str, float] = {}
    for metric_id, number in extra_metrics.items():
        if not isinstance(metric_id, str) or not metric_id:
            raise ValueError(
                f"{source}: review row {index} ({entry_id}): "
                "extra_metrics keys must be non-empty strings"
            )
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError(
                f"{source}: review row {index} ({entry_id}): "
                f"extra_metrics value for {metric_id!r} must be a finite number"
            )
        checked[metric_id] = number
    return checked


def _check_extra_private_terms(
    source: Path, index: int, entry_id: str, entry: dict[str, Any]
) -> tuple[str, ...]:
    """Validate a review row's optional ``extra_private_terms`` list.

    Returns the extra terms as a tuple; a value that is not a list of
    non-empty strings raises ``ValueError`` naming the file and the row,
    as ``extra_metrics`` does.
    """
    extra_terms: Any = entry.get("extra_private_terms", [])
    if not isinstance(extra_terms, list) or not all(
        isinstance(term, str) and term for term in extra_terms
    ):
        raise ValueError(
            f"{source}: review row {index} ({entry_id}): "
            "extra_private_terms must be a list of non-empty strings"
        )
    return tuple(extra_terms)


def run_review_rows(
    source: Path, adjudication: dict[str, Any], context: GateContext
) -> list[dict[str, Any]]:
    """Run each ``found_in_review`` claim on a copy of the host context.

    ``extra_facts`` are added to a copy of the context for that row alone,
    ``extra_metrics`` values are added to the metric snapshot on a copy
    of the context for that row alone, and ``extra_private_terms`` are
    appended to the private terms on a copy of the context for that row
    alone; the shared context is never mutated.
    """
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(adjudication.get("found_in_review", [])):
        entry_id = entry.get("id", "?") if isinstance(entry, dict) else "?"
        if not isinstance(entry, dict):
            raise ValueError(  # noqa: TRY004
                f"{source}: review row {index}: not an object"
            )
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"{source}: review row {index}: empty id")
        text, fact_ids, metric_refs = _check_claim(
            source, index, entry_id, entry.get("claim")
        )
        extra = entry.get("extra_facts", [])
        if not isinstance(extra, list):
            raise ValueError(  # noqa: TRY004
                f"{source}: review row {index} ({entry_id}): extra_facts must be a list"
            )
        new_facts = dict(context.facts)
        for fact in extra:
            if (
                not isinstance(fact, dict)
                or not isinstance(fact.get("id"), str)
                or not fact["id"]
                or not isinstance(fact.get("statement"), str)
                or not fact["statement"]
            ):
                raise ValueError(
                    f"{source}: review row {index} ({entry_id}): "
                    "extra_facts need an id and a statement"
                )
            new_facts[fact["id"]] = Fact.model_validate(
                _fact_payload(fact["id"], fact["statement"])
            )
        extra_metrics = _check_extra_metrics(source, index, entry_id, entry)
        new_values = dict(context.metrics.values)
        new_values.update(extra_metrics)
        extra_terms = _check_extra_private_terms(source, index, entry_id, entry)
        row_context = context.model_copy(
            update={
                "facts": new_facts,
                "metrics": MetricSnapshot(values=new_values),
                "private_terms": (*context.private_terms, *extra_terms),
            }
        )
        outcome = run_claim(text, fact_ids, metric_refs, row_context)
        rows.append({"id": entry_id, **outcome})
    return rows


def run_file(input_path: Path, write_frozen: bool) -> int:
    """Default run: regenerate the current results file (and frozen once)."""
    try:
        kind, entries = load_input(input_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    frozen = _frozen_path(input_path)
    if write_frozen and frozen.exists():
        print(
            f"error: {frozen} already exists; refusing to overwrite it",
            file=sys.stderr,
        )
        return 1
    try:
        adjudication = load_adjudication(input_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    context = build_context()
    rows: list[dict[str, Any]] = []
    for entry in entries:
        outcome = run_claim(
            entry["text"], entry["fact_ids"], entry["metric_refs"], context
        )
        if kind == "attacks":
            rows.append(
                {
                    "id": entry["id"],
                    "target": entry["target"],
                    "predicted_passes": entry["predicted_passes"],
                    **outcome,
                }
            )
        else:
            rows.append({"id": entry["id"], **outcome})
    current: dict[str, Any] = {"rows": rows}
    if adjudication is not None:
        try:
            current["review_rows"] = run_review_rows(
                _adjudication_path(input_path), adjudication, context
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if write_frozen:
        try:
            stamps = frozen_stamps(input_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        frozen.write_text(_dump({**stamps, "rows": rows}), encoding="utf-8")
    _current_path(input_path).write_text(_dump(current), encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Summary (D17): computed only from frozen, current and adjudication files.
# ---------------------------------------------------------------------------


def discover_inputs(search_dir: Path = REDTEAM_DIR) -> tuple[list[Path], list[Path]]:
    """Find every attack file and true-sentences input, never results."""
    rounds = sorted(
        p for p in search_dir.glob("round-*.json") if ROUND_RE.fullmatch(p.name)
    )
    blinds = sorted(
        p
        for p in search_dir.glob("true-sentences-*.json")
        if not p.name.endswith(".results.json") and not p.name.endswith(".frozen.json")
    )
    return rounds, blinds


def _rows_of(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _blocked(rows: list[dict[str, Any]] | None) -> int | None:
    if rows is None:
        return None
    return sum(1 for row in rows if not row["passed"])


def _raised(rows: list[dict[str, Any]] | None) -> list[str]:
    if rows is None:
        return []
    return [row["id"] for row in rows if row["raised"] is not None]


def summarize_file(input_path: Path) -> dict[str, Any]:
    """Summarize one input file from its frozen/current rows on disk."""
    kind, entries = load_input(input_path)
    frozen_rows = _rows_of(_frozen_path(input_path))
    current_rows = _rows_of(_current_path(input_path))
    by_code: dict[str, int] = {}
    if current_rows is not None:
        for row in current_rows:
            for code in row["codes"]:
                by_code[code] = by_code.get(code, 0) + 1
    newly_ids: list[str] = []
    if frozen_rows is not None and current_rows is not None:
        frozen_by_id = {row["id"]: row for row in frozen_rows}
        for row in current_rows:
            if frozen_by_id[row["id"]]["passed"] and not row["passed"]:
                newly_ids.append(row["id"])
    newly_by_code: dict[str, int] = {}
    if current_rows is not None:
        current_by_id = {row["id"]: row for row in current_rows}
        for nid in newly_ids:
            for code in current_by_id[nid]["codes"]:
                newly_by_code[code] = newly_by_code.get(code, 0) + 1
    return {
        "kind": kind,
        "sentences": len(entries),
        "blocked_on_frozen": _blocked(frozen_rows),
        "blocked_on_current": _blocked(current_rows),
        "blocked_by_code_on_current": by_code,
        "newly_blocked": {"ids": newly_ids, "by_code": newly_by_code},
        "raised_ids": {
            "frozen": _raised(frozen_rows),
            "current": _raised(current_rows),
        },
    }


def summarize_round(input_path: Path, number: str) -> dict[str, Any]:
    """Per-round verdict accounting from the frozen rows + adjudication."""
    _, entries = load_input(input_path)
    attacks = {entry["id"]: entry for entry in entries}
    frozen_rows = _rows_of(_frozen_path(input_path)) or []
    current_rows = _rows_of(_current_path(input_path))
    current_by_id = (
        {row["id"]: row for row in current_rows} if current_rows is not None else None
    )
    # A row that raised counts as through: it needs a verdict like a pass.
    through = [row for row in frozen_rows if row["passed"] or row["raised"] is not None]
    adjudication = load_adjudication(input_path)
    verdicts: dict[str, str] = {}
    if adjudication is not None:
        for verdict in adjudication.get("verdicts", []):
            verdicts[verdict["id"]] = verdict["verdict"]
    by_verdict: dict[str, int] = {}
    for row in through:
        verdict = verdicts.get(row["id"], "unadjudicated")
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
    by_target: dict[str, int] = {}
    for row in through:
        target = attacks[row["id"]]["target"]
        by_target[target] = by_target.get(target, 0) + 1
    matched = sum(
        1
        for row in frozen_rows
        if attacks[row["id"]].get("predicted_passes") == row["passed"]
    )
    through_on_fixed: int | None = None
    fixed = 0
    if current_by_id is not None:
        through_on_fixed = sum(
            1 for row in through if current_by_id[row["id"]]["passed"]
        )
        # A row that raised on the current run is not counted as fixed:
        # a raise is no verdict, not a stop.
        fixed = sum(
            1
            for row in through
            if verdicts.get(row["id"]) == "real_hole"
            and current_by_id[row["id"]]["raised"] is None
            and not current_by_id[row["id"]]["passed"]
        )
    found_total = 0
    found_by_verdict: dict[str, int] = {}
    review_ids: list[str] = []
    review_rows: list[dict[str, Any]] = []
    if adjudication is not None:
        review_verdicts = {
            entry["id"]: entry.get("verdict", "?")
            for entry in adjudication.get("found_in_review", [])
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        for entry in adjudication.get("found_in_review", []):
            found_total += 1
            verdict = entry.get("verdict", "?")
            found_by_verdict[verdict] = found_by_verdict.get(verdict, 0) + 1
        if current_rows is not None:
            current_doc = json.loads(
                _current_path(input_path).read_text(encoding="utf-8")
            )
            for row in current_doc.get("review_rows", []):
                review_ids.append(row["id"])
                review_rows.append(
                    {
                        "id": row["id"],
                        "verdict": review_verdicts.get(row["id"], "unadjudicated"),
                        "passed": row["passed"],
                        "codes": list(row["codes"]),
                        "raised": row["raised"],
                    }
                )
    return {
        "input": input_path.name,
        "through_total": len(through),
        "through_by_verdict": by_verdict,
        "through_by_target": by_target,
        "predicted_actual_agreement": {"matched": matched, "total": len(frozen_rows)},
        "through_on_fixed": through_on_fixed,
        "fixed": fixed,
        "found_in_review": {
            "total": found_total,
            "by_verdict": found_by_verdict,
            "review_ids": review_ids,
            "rows": review_rows,
        },
    }


def build_summary(search_dir: Path = REDTEAM_DIR) -> dict[str, Any]:
    """Build the full summary object over every discovered input."""
    rounds, blinds = discover_inputs(search_dir)
    files: dict[str, Any] = {}
    total_sentences = 0
    total_blocked_frozen = 0
    total_blocked_current = 0
    for path in rounds + blinds:
        files[path.name] = summarize_file(path)
        total_sentences += files[path.name]["sentences"]
        if files[path.name]["blocked_on_frozen"] is not None:
            total_blocked_frozen += files[path.name]["blocked_on_frozen"]
        if files[path.name]["blocked_on_current"] is not None:
            total_blocked_current += files[path.name]["blocked_on_current"]
    return {
        "files": files,
        "total": {
            "sentences": total_sentences,
            "blocked_on_frozen": total_blocked_frozen,
            "blocked_on_current": total_blocked_current,
        },
        "rounds": {
            match.group(1): summarize_round(path, match.group(1))
            for path in rounds
            for match in [ROUND_RE.fullmatch(path.name)]
            if match is not None
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    """Render the summary as Markdown tables (also used verbatim in docs)."""
    lines = ["## Red-team summary", ""]
    lines.append("| file | sentences | frozen blocked | current blocked |")
    lines.append("|---|---|---|---|")
    for name in sorted(summary["files"]):
        entry = summary["files"][name]
        lines.append(
            f"| {name} | {entry['sentences']} | "
            f"{entry['blocked_on_frozen']} | {entry['blocked_on_current']} |"
        )
    lines.append("")
    lines.append(
        f"Total sentences: {summary['total']['sentences']}, "
        f"blocked on frozen: {summary['total']['blocked_on_frozen']}, "
        f"blocked on current: {summary['total']['blocked_on_current']}."
    )
    lines.append("")
    for number in sorted(summary["rounds"]):
        entry = summary["rounds"][number]
        lines.append(f"### Round {number}")
        lines.append("")
        lines.append(
            f"Through on frozen: {entry['through_total']} "
            f"(by verdict: {json.dumps(entry['through_by_verdict'], sort_keys=True)}; "
            f"by target: {json.dumps(entry['through_by_target'], sort_keys=True)})."
        )
        agreement = entry["predicted_actual_agreement"]
        lines.append(
            f"Predicted/actual agreement: {agreement['matched']}/{agreement['total']}."
        )
        lines.append(
            f"Through on fixed gate: {entry['through_on_fixed']}; "
            f"fixed: {entry['fixed']}."
        )
        found = entry["found_in_review"]
        lines.append("")
        lines.append("Found in review (kept apart from attacker totals):")
        lines.append("")
        lines.append("| id | verdict | passed | codes |")
        lines.append("|---|---|---|---|")
        if found["rows"]:
            for row in found["rows"]:
                lines.append(
                    f"| {row['id']} | {row['verdict']} | "
                    f"{row['passed']} | {json.dumps(row['codes'])} |"
                )
        else:
            lines.append("| none yet | - | - | - |")
        lines.append("")
    for name in sorted(summary["files"]):
        entry = summary["files"][name]
        lines.append(
            f"{name} newly blocked: {json.dumps(entry['newly_blocked']['ids'])} "
            f"by code {json.dumps(entry['newly_blocked']['by_code'], sort_keys=True)}; "
            f"raised: {json.dumps(entry['raised_ids'], sort_keys=True)}."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--summary" in args:
        summary = build_summary()
        if "--markdown" in args:
            print(render_markdown(summary), end="")
        else:
            print(_dump(summary), end="")
        return 0
    positional = [a for a in args if not a.startswith("--")]
    flags = {a for a in args if a.startswith("--")}
    if len(positional) != 1 or flags - {"--write-frozen"}:
        print(
            "usage: python -m evals.redteam INPUT [--write-frozen]\n"
            "       python -m evals.redteam --summary [--markdown]",
            file=sys.stderr,
        )
        return 2
    return run_file(Path(positional[0]), "--write-frozen" in flags)


if __name__ == "__main__":
    raise SystemExit(main())
