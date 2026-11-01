"""Ticket 9c: R10 live measurement of the label step against the keyword list.

A live measurement, not an Inspect task: no ``@task``, not in
``EVAL_FILES``. Every case title goes to both arms unchanged. The report
never prints a title, a note, or a case id. No model run happens unless
``IKIGAI_R10_LIVE=1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.r10_keywords import keyword_label
from framework.glimmer.facts import LLMUnavailableError
from framework.glimmer.label_step import (
    LABEL_PROMPT_SHA256,
    build_label_client,
    build_label_prompt,
    label_outcome,
)
from framework.glimmer.labels import LABELS
from framework.glimmer.llm import MODEL_TIMEOUT_S

R10_CASES_SHA256 = "9c346ea1ec17665cb5f5254b484e311589f0bcb07ddaef859fecf21722e616cf"
DEFAULT_CASES_PATH = Path("evals/r10_cases.json")
DEFAULT_RESULTS_DIR = Path("evals/r10_results")

_TOP_KEYS = frozenset({"labels", "cases"})
_CASE_KEYS = frozenset({"id", "title", "label", "accepted", "class", "lang", "note"})
_INVALID_COLUMN = "invalid"


@dataclass(frozen=True)
class R10Case:
    id: str
    title: str
    label: str
    accepted: tuple[str, ...]
    class_: str
    lang: str
    note: str


@dataclass(frozen=True)
class R10Cases:
    labels: tuple[str, ...]
    cases: tuple[R10Case, ...]


def load_r10_cases(path: str | Path) -> R10Cases:
    """Validate the pinned shape; faults name the index, never a title."""
    raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw.keys()) != set(_TOP_KEYS):
        raise ValueError("r10 cases: top-level keys must be exactly labels, cases")
    labels = raw["labels"]
    if not isinstance(labels, list) or set(labels) != set(LABELS):
        raise ValueError("r10 cases: labels must equal LABELS as a set")
    cases_raw = raw["cases"]
    if not isinstance(cases_raw, list):
        raise ValueError("r10 cases: cases must be a list")  # noqa: TRY004
    seen: set[str] = set()
    cases: list[R10Case] = []
    for index, item in enumerate(cases_raw):
        if not isinstance(item, dict) or set(item.keys()) != set(_CASE_KEYS):
            raise ValueError(
                f"r10 case {index}: keys must be exactly"
                " id, title, label, accepted, class, lang, note"
            )
        cid = item["id"]
        if not isinstance(cid, str) or not cid:
            raise ValueError(f"r10 case {index}: empty or missing id")
        if cid in seen:
            raise ValueError(f"r10 case {index}: duplicate id")
        seen.add(cid)
        for key in ("title", "label", "class", "lang", "note"):
            if not isinstance(item[key], str):
                raise ValueError(  # noqa: TRY004
                    f"r10 case {index}: {key} must be a string"
                )
        if not item["title"]:
            raise ValueError(f"r10 case {index}: empty title")
        if item["label"] not in LABELS:
            raise ValueError(f"r10 case {index}: label outside LABELS")
        accepted = item["accepted"]
        if not isinstance(accepted, list) or not 1 <= len(accepted) <= 2:
            raise ValueError(f"r10 case {index}: accepted must hold 1 or 2 labels")
        if any(entry not in LABELS for entry in accepted):
            raise ValueError(f"r10 case {index}: accepted member outside LABELS")
        if accepted[0] != item["label"]:
            raise ValueError(f"r10 case {index}: accepted[0] != label")
        cases.append(
            R10Case(
                id=cid,
                title=item["title"],
                label=item["label"],
                accepted=tuple(accepted),
                class_=item["class"],
                lang=item["lang"],
                note=item["note"],
            )
        )
    return R10Cases(labels=tuple(labels), cases=tuple(cases))


def is_correct(predicted: str, valid: bool, accepted: Sequence[str]) -> bool:
    """Correct scoring: the answer is valid and is in ``accepted``."""
    return bool(valid) and predicted in accepted


def is_strict(predicted: str, valid: bool, gold: str) -> bool:
    """Strict scoring: the answer is valid and equals ``label``."""
    return bool(valid) and predicted == gold


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar p over the discordant counts, in integers."""
    n = b + c
    if n == 0:
        return 1.0
    total = sum(math.comb(n, k) for k in range(min(b, c) + 1))
    return min(1.0, 2.0 * total / 2**n)


@dataclass(frozen=True)
class R10Stats:
    n: int
    answered: int
    model_correct: int
    keyword_correct: int
    model_strict: int
    keyword_strict: int
    discordant_b: int
    discordant_c: int
    discordant_b_strict: int
    discordant_c_strict: int
    mcnemar_p: float
    mcnemar_p_strict: float
    committed: int
    committed_correct: int
    committed_strict: int
    care_model_correct: int
    care_keyword_correct: int
    care_model_strict: int
    care_keyword_strict: int
    model_invalid: int


@dataclass(frozen=True)
class R10Decision:
    eligible: bool
    reasons: tuple[str, ...]  # one per decision condition, with PASS or FAIL


def r10_decision(stats: R10Stats) -> R10Decision:
    """The gate rule, written before any result exists."""
    complete = stats.answered == stats.n
    more = (
        stats.model_correct > stats.keyword_correct
        and stats.model_strict > stats.keyword_strict
    )
    discordant = stats.discordant_b + stats.discordant_c
    discordant_strict = stats.discordant_b_strict + stats.discordant_c_strict
    luck = (
        stats.mcnemar_p < 0.05
        and discordant >= 10
        and stats.mcnemar_p_strict < 0.05
        and discordant_strict >= 10
    )
    commits = (
        stats.committed > 0
        and stats.committed_correct / stats.committed >= 0.8
        and stats.committed_strict / stats.committed >= 0.8
    )
    care = (
        stats.care_model_correct >= stats.care_keyword_correct
        and stats.care_model_strict >= stats.care_keyword_strict
    )
    clean = stats.model_invalid * 100 <= 2 * stats.n
    reasons = (
        f"1 complete {stats.answered}/{stats.n}: {'PASS' if complete else 'FAIL'}",
        (
            f"2 more right {stats.model_correct}>{stats.keyword_correct}"
            f" strict {stats.model_strict}>{stats.keyword_strict}:"
            f" {'PASS' if more else 'FAIL'}"
        ),
        (
            f"3 not luck p={stats.mcnemar_p:.4g}/{stats.mcnemar_p_strict:.4g}"
            f" discordant={discordant}/{discordant_strict}:"
            f" {'PASS' if luck else 'FAIL'}"
        ),
        (
            f"4 right when it commits {stats.committed_correct}/{stats.committed}"
            f" strict {stats.committed_strict}/{stats.committed}:"
            f" {'PASS' if commits else 'FAIL'}"
        ),
        (
            f"5 iki-care {stats.care_model_correct}>={stats.care_keyword_correct}"
            f" strict {stats.care_model_strict}>={stats.care_keyword_strict}:"
            f" {'PASS' if care else 'FAIL'}"
        ),
        (
            f"6 clean answers invalid={stats.model_invalid}/{stats.n}:"
            f" {'PASS' if clean else 'FAIL'}"
        ),
    )
    eligible = all([complete, more, luck, commits, care, clean])
    return R10Decision(eligible=eligible, reasons=reasons)


def _keywords_sha() -> str:
    return hashlib.sha256(
        (Path(__file__).parent / "r10_keywords.py").read_bytes()
    ).hexdigest()


def compute_stats(
    cases: R10Cases, records: Mapping[str, Mapping[str, Any]]
) -> R10Stats:
    """Score both arms over the answered cases."""
    answered = 0
    model_correct = keyword_correct = 0
    model_strict = keyword_strict = 0
    b = c = b_strict = c_strict = 0
    committed = committed_correct = committed_strict = 0
    care_model = care_kw = care_model_strict = care_kw_strict = 0
    invalid = 0
    for case in cases.cases:
        record = records.get(case.id)
        if record is None:
            continue
        answered += 1
        predicted = str(record.get("predicted", ""))
        valid = bool(record.get("valid", False))
        keyword = keyword_label(case.title)
        right = is_correct(predicted, valid, case.accepted)
        kw_right = is_correct(keyword, True, case.accepted)
        strict = is_strict(predicted, valid, case.label)
        kw_strict = is_strict(keyword, True, case.label)
        model_correct += int(right)
        keyword_correct += int(kw_right)
        model_strict += int(strict)
        keyword_strict += int(kw_strict)
        b += int(right and not kw_right)
        c += int(kw_right and not right)
        b_strict += int(strict and not kw_strict)
        c_strict += int(kw_strict and not strict)
        invalid += int(not valid)
        if valid and predicted != "iki-unknown":
            committed += 1
            committed_correct += int(right)
            committed_strict += int(strict)
        if case.label == "iki-care":
            care_model += int(right)
            care_kw += int(kw_right)
            care_model_strict += int(strict)
            care_kw_strict += int(kw_strict)
    return R10Stats(
        n=len(cases.cases),
        answered=answered,
        model_correct=model_correct,
        keyword_correct=keyword_correct,
        model_strict=model_strict,
        keyword_strict=keyword_strict,
        discordant_b=b,
        discordant_c=c,
        discordant_b_strict=b_strict,
        discordant_c_strict=c_strict,
        mcnemar_p=mcnemar_p(b, c),
        mcnemar_p_strict=mcnemar_p(b_strict, c_strict),
        committed=committed,
        committed_correct=committed_correct,
        committed_strict=committed_strict,
        care_model_correct=care_model,
        care_keyword_correct=care_kw,
        care_model_strict=care_model_strict,
        care_keyword_strict=care_kw_strict,
        model_invalid=invalid,
    )


def _nearest_p90(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def render_report(
    *,
    role: str,
    model: str,
    cases: R10Cases,
    records: Mapping[str, Mapping[str, Any]],
    cases_sha: str,
    keywords_sha: str,
    response_format: bool,
    frozen: bool,
) -> str:
    """Deterministic report from the results file; no titles, notes, or ids."""
    stats = compute_stats(cases, records)
    lines = [f"role: {role}", f"model: {model}", f"n: {stats.n}"]
    if role == "comparison":
        lines.insert(0, "COMPARISON, not the product")
    lines += [
        f"cases_sha: {cases_sha[:12]}",
        f"prompt_sha: {LABEL_PROMPT_SHA256[:12]}",
        f"keywords_sha: {keywords_sha[:12]}",
        f"response_format: {'yes' if response_format else 'no'}",
        f"frozen cases: {'yes' if frozen else 'no, custom cases, not the frozen set'}",
        (
            f"model correct: {stats.model_correct}/{stats.n}"
            f" strict: {stats.model_strict}/{stats.n}"
        ),
        (
            f"keywords correct: {stats.keyword_correct}/{stats.n}"
            f" strict: {stats.keyword_strict}/{stats.n}"
        ),
    ]
    for arm in ("model", "keywords"):
        lines.append(f"per-label correct ({arm}, correct/strict by gold label):")
        for label in LABELS:
            gold = [case for case in cases.cases if case.label == label]
            if arm == "model":
                correct = sum(
                    1
                    for case in gold
                    if (rec := records.get(case.id)) is not None
                    and is_correct(
                        str(rec.get("predicted", "")),
                        bool(rec.get("valid", False)),
                        case.accepted,
                    )
                )
                strict = sum(
                    1
                    for case in gold
                    if (rec := records.get(case.id)) is not None
                    and is_strict(
                        str(rec.get("predicted", "")),
                        bool(rec.get("valid", False)),
                        case.label,
                    )
                )
            else:
                correct = sum(
                    1 for case in gold if keyword_label(case.title) in case.accepted
                )
                strict = sum(
                    1 for case in gold if keyword_label(case.title) == case.label
                )
            lines.append(
                f"  {label}: correct {correct}/{len(gold)} strict {strict}/{len(gold)}"
            )
    for arm in ("model", "keywords"):
        lines.append(f"confusion {arm} (rows gold, columns predicted):")
        columns = (*LABELS, _INVALID_COLUMN)
        lines.append("  gold\\pred " + " ".join(columns))
        for label in LABELS:
            row = [label]
            counts = {column: 0 for column in columns}
            for case in cases.cases:
                if case.label != label:
                    continue
                if arm == "model":
                    rec = records.get(case.id)
                    if rec is None:
                        continue
                    predicted = str(rec.get("predicted", ""))
                    valid = bool(rec.get("valid", False))
                    column = (
                        predicted if valid and predicted in LABELS else _INVALID_COLUMN
                    )
                else:
                    column = keyword_label(case.title)
                counts[column] += 1
            row += [str(counts[column]) for column in columns]
            lines.append("  " + " ".join(row))
    for field in ("class_", "lang"):
        lines.append(f"by {field.rstrip('_')} (correct scoring, both arms):")
        values = sorted({getattr(case, field) for case in cases.cases})
        for value in values:
            group = [case for case in cases.cases if getattr(case, field) == value]
            model_hits = sum(
                1
                for case in group
                if (rec := records.get(case.id)) is not None
                and is_correct(
                    str(rec.get("predicted", "")),
                    bool(rec.get("valid", False)),
                    case.accepted,
                )
            )
            kw_hits = sum(
                1 for case in group if keyword_label(case.title) in case.accepted
            )
            lines.append(
                f"  {value}: model {model_hits}/{len(group)}"
                f" keywords {kw_hits}/{len(group)}"
            )
    unknown_total = sum(
        1 for case in cases.cases if keyword_label(case.title) == "iki-unknown"
    )
    unknown_non_gold = sum(
        1
        for case in cases.cases
        if keyword_label(case.title) == "iki-unknown" and case.label != "iki-unknown"
    )
    lines.append(
        f"keywords unknown: total {unknown_total}"
        f" among gold not unknown {unknown_non_gold}"
    )
    lines.append(f"model invalid: {stats.model_invalid}")
    seconds = [
        float(records[case.id].get("seconds", 0.0))
        for case in cases.cases
        if case.id in records
    ]
    if seconds:
        lines.append(
            f"seconds per title: mean {_mean(seconds):.2f} median {_median(seconds):.2f}"
            f" p90 {_nearest_p90(seconds):.2f} max {max(seconds):.2f}"
            f" total {sum(seconds):.2f}"
        )
    else:
        lines.append("seconds per title: none recorded")
    tokens = [
        int(records[case.id]["completion_tokens"])
        for case in cases.cases
        if case.id in records and records[case.id].get("completion_tokens") is not None
    ]
    unreported = sum(
        1
        for case in cases.cases
        if case.id in records and records[case.id].get("completion_tokens") is None
    )
    if tokens:
        lines.append(
            f"completion tokens per title: mean {_mean(tokens):.1f}"
            f" median {_median(tokens):.1f} max {max(tokens)}"
            f" total {sum(tokens)} unreported {unreported}"
        )
    else:
        lines.append(
            f"completion tokens per title: none reported unreported {unreported}"
        )
    lines.append(
        f"mcnemar correct: b={stats.discordant_b} c={stats.discordant_c}"
        f" p={stats.mcnemar_p:.4g}"
    )
    lines.append(
        f"mcnemar strict: b={stats.discordant_b_strict} c={stats.discordant_c_strict}"
        f" p={stats.mcnemar_p_strict:.4g}"
    )
    lines.append(
        "mcnemar limits: the smallest p reachable with n discordant pairs is"
        " 2/2**n; the test says nothing about the size of the gap; per-label"
        " counts are small and carry no test; 80 synthetic titles say little"
        " about my real calendar, and no real title is ever scored, so nobody"
        " will know the accuracy on real titles after this is on."
    )
    for reason in r10_decision(stats).reasons:
        lines.append(f"condition {reason}")
    if role != "product":
        lines.append("no decision: comparison role")
    elif not frozen:
        lines.append("no decision: custom cases, not the frozen set")
    elif stats.answered != stats.n:
        lines.append(f"no decision: partial file ({stats.answered}/{stats.n} answered)")
    else:
        decision = r10_decision(stats)
        lines.append(f"decision: {'eligible' if decision.eligible else 'not eligible'}")
    return "\n".join(lines) + "\n"


def _safe_model_name(model: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in model)


def _load_results(
    path: Path, header: Mapping[str, Any], *, truncate: bool
) -> dict[str, dict[str, Any]] | None:
    """Load answered ids; None means exit 2 (bad header or torn earlier line).

    A last line with no trailing newline is torn even when it parses: the
    next append would glue a record to it. Under ``truncate=True`` the torn
    tail is cut with ``os.truncate`` at the byte offset where that line
    starts, then fsynced; the whole file is never rewritten. Under
    ``truncate=False`` (``--report-only``) the torn last line is ignored and
    the file is left byte-identical.
    """
    data = path.read_bytes()
    if not data:
        return None
    ends_newline = data.endswith(b"\n")
    lines = data.split(b"\n")
    if ends_newline:
        lines.pop()
    try:
        stored = json.loads(lines[0].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(stored, dict) or stored != dict(header):
        return None
    if len(lines) == 1 and not ends_newline:
        # Only the header, with no trailing newline: keep it and add the
        # newline under truncate; leave the bytes alone for --report-only.
        if truncate:
            with open(path, "ab") as handle:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
        return {}
    records: dict[str, dict[str, Any]] = {}
    chunks = lines[1:]
    total = len(chunks)
    for position, chunk in enumerate(chunks):
        record: Any = None
        torn_tail = position == total - 1 and not ends_newline
        if not torn_tail:
            try:
                record = json.loads(chunk.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                record = None
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            if position == total - 1:
                if truncate:
                    os.truncate(
                        path, len(data) - len(chunk) - (1 if ends_newline else 0)
                    )
                    with open(path, "rb") as handle:
                        os.fsync(handle.fileno())
                break
            return None
        records.setdefault(record["id"], record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.r10")
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--role", choices=("product", "comparison"), default="product")
    parser.add_argument("--no-response-format", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.report_only and os.environ.get("IKIGAI_R10_LIVE") != "1":
        print("r10: disabled (set IKIGAI_R10_LIVE=1)")
        return 2
    cases_path = Path(args.cases)
    frozen = cases_path.resolve() == DEFAULT_CASES_PATH.resolve()
    if frozen:
        if not cases_path.exists():
            print("r10: default cases file absent", file=sys.stderr)
            return 2
        cases_sha = hashlib.sha256(cases_path.read_bytes()).hexdigest()
        if cases_sha != R10_CASES_SHA256:
            print(f"r10: cases hash mismatch {cases_sha[:12]}", file=sys.stderr)
            return 2
    else:
        try:
            cases_sha = hashlib.sha256(cases_path.read_bytes()).hexdigest()
        except OSError:
            print("r10: cases file unreadable", file=sys.stderr)
            return 2
    try:
        cases = load_r10_cases(cases_path)
    except ValueError as exc:
        print(f"r10: {exc}", file=sys.stderr)
        return 2
    out_path = (
        Path(args.out)
        if args.out
        else DEFAULT_RESULTS_DIR / f"{_safe_model_name(args.model)}.jsonl"
    )
    keywords_sha = _keywords_sha()
    header = {
        "type": "header",
        "model": args.model,
        "role": args.role,
        "cases_sha": cases_sha,
        "prompt_sha": LABEL_PROMPT_SHA256,
        "keywords_sha": keywords_sha,
        "response_format": not args.no_response_format,
    }
    records: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        loaded = _load_results(out_path, header, truncate=not args.report_only)
        if loaded is None:
            print("r10: results header mismatch or torn file", file=sys.stderr)
            return 2
        records = loaded
    if args.report_only:
        print(
            render_report(
                role=args.role,
                model=args.model,
                cases=cases,
                records=records,
                cases_sha=cases_sha,
                keywords_sha=keywords_sha,
                response_format=not args.no_response_format,
                frozen=frozen,
            )
        )
        return 0
    pending = [case for case in cases.cases if case.id not in records]
    client = None
    if pending:
        try:
            client = build_label_client(
                os.environ, model=args.model, timeout_s=MODEL_TIMEOUT_S
            )
        except ValueError:
            print("r10: refused endpoint", file=sys.stderr)
            return 2
        if args.no_response_format:
            client.response_format = None
    if not out_path.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as handle:
            handle.write((json.dumps(header) + "\n").encode("utf-8"))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
    for position, case in enumerate(pending):
        answered = len(cases.cases) - len(pending) + position
        print(f"{answered + 1}/{len(cases.cases)}", file=sys.stderr)
        prompt = build_label_prompt(case.title)
        started = time.monotonic()
        assert client is not None
        try:
            response = client.complete(prompt)
        except LLMUnavailableError as exc:
            print(
                f"r10: model unavailable ({exc}), stopped, rerun resumes",
                file=sys.stderr,
            )
            return 3
        seconds = time.monotonic() - started
        outcome = label_outcome(response)
        line: dict[str, Any] = {
            "id": case.id,
            "predicted": outcome.label,
            "valid": outcome.valid,
            "seconds": seconds,
            "completion_tokens": response.completion_tokens,
            "finish_reason": response.finish_reason,
        }
        if not outcome.valid:
            line["raw_answer"] = response.text
        with open(out_path, "ab") as handle:
            handle.write((json.dumps(line) + "\n").encode("utf-8"))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        records[case.id] = line
    print(
        render_report(
            role=args.role,
            model=args.model,
            cases=cases,
            records=records,
            cases_sha=cases_sha,
            keywords_sha=keywords_sha,
            response_format=not args.no_response_format,
            frozen=frozen,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
