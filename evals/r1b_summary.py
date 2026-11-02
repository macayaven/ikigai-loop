"""Ticket 16b: the R1b summary (D10, D19).

Pure and deterministic: ``render_summary`` regenerates ``docs/r1b.md``
from the JSONL rows alone. Counts are the result; the paired test is
descriptive only.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

CATEGORY_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Unbacked number", ("L1B_NUMBER_WITHOUT_METRIC_REF",)),
    (
        "Wrong or unknown evidence",
        (
            "L1B_UNKNOWN_METRIC",
            "L1B_UNKNOWN_FACT",
            "L1B_CLAIM_WITHOUT_EVIDENCE",
            "L1B_METRIC_VALUE_MISMATCH",
            "L1B_DELTA_MISMATCH",
            "L1_ACTION_NOT_COMMITTED",
        ),
    ),
    ("Direction", ("L1B_DIRECTION_MISMATCH",)),
    ("Advice", ("L1_ADVICE",)),
    (
        "Wording or form",
        (
            "L1B_METRIC_LABEL_MISSING",
            "L1B_METRIC_LABEL_UNKNOWN",
            "L1B_PERIOD_WORD_MISSING",
            "L1B_TOO_MANY_METRICS",
            "L1_ACTION_TEXT_MISMATCH",
            "L1B_MISSING_SINCE_LAST",
            "L1B_SINCE_LAST_WITHOUT_PARENT",
            "L1B_PARENT_MISMATCH",
            "L0_ACTION_COUNT",
            "L0_DUPLICATE_ID",
            "L0_DUPLICATE_SECTION",
            "L0_EMPTY_SECTION",
            "L0_MISSING_SECTION",
            "L0_SCHEMA_INVALID",
            "L0_SECTION_COUNT",
            "L0_UNKNOWN_SECTION",
        ),
    ),
    (
        "Leak",
        (
            "L1_SECRET",
            "L1_PII",
            "L1_RAW_VALUE",
            "L1_PRIVATE_TERM",
            "L1_ACTION_TARGETS_REPO",
        ),
    ),
    (
        "Not a draft outcome",
        (
            "L1_PRIVATE_TERMS_UNAVAILABLE",
            "L1_COMMITMENTS_UNAVAILABLE",
            "L1_SLOT_OUTSIDE_ALLOWED_HOURS",
            "L1_ACTION_BEFORE_SLOT",
            "L1_ACTION_IN_BUSY_INTERVAL",
            "L1_ACTION_NOT_FREE",
        ),
    ),
)

GATE_CODES: frozenset[str] = frozenset(
    code for _category, codes in CATEGORY_TABLE for code in codes
)

PROPOSAL_CODES: frozenset[str] = frozenset(
    {
        "PROPOSAL_CLAIM_TOO_LONG",
        "PROPOSAL_CLAIM_NOT_PLAIN",
        "PROPOSAL_SINCE_LAST_DELTA_MISSING",
    }
)

CODE_TO_CATEGORY: dict[str, str] = {
    code: category for category, codes in CATEGORY_TABLE for code in codes
}

NOT_DRAFT_OUTCOME_CODES: frozenset[str] = frozenset(
    code
    for category, codes in CATEGORY_TABLE
    if category == "Not a draft outcome"
    for code in codes
)

GATE_FAILURE_CODES: frozenset[str] = GATE_CODES - NOT_DRAFT_OUTCOME_CODES

PREDICTION = (
    "the plain prompt fails at least 3 times as often as the product prompt, "
    "on every model"
)


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar's exact test, two-sided, stdlib only."""
    n = b + c
    if n == 0:
        return 1.0
    total = sum(math.comb(n, k) for k in range(min(b, c) + 1))
    return min(1.0, 2.0 * total / (2**n))


def _codes_of(row: dict[str, Any]) -> list[str]:
    return [str(pair[0]) for pair in row["codes"]]


def _is_unavailable_first(row: dict[str, Any]) -> bool:
    return "MODEL_UNAVAILABLE" in _codes_of(row)


def _execution_is_complete(exec_rows: list[dict[str, Any]]) -> bool:
    first = [row for row in exec_rows if int(row["attempt"]) == 1]
    return bool(first) and not _is_unavailable_first(first[0])


def group_executions(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str, str, str, int], list[dict[str, Any]]]:
    """Group rows by (gate, model, effort, arm, case, execution)."""
    grouped: dict[tuple[str, str, str, str, str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["gate_commit"]),
            str(row["gate_hash"]),
            str(row["model"]),
            str(row["effort"]),
            str(row["arm"]),
            str(row["case_id"]),
            int(row["execution"]),
        )
        grouped.setdefault(key, []).append(row)
    for key, exec_rows in grouped.items():
        grouped[key] = sorted(exec_rows, key=lambda row: int(row["attempt"]))
    return grouped


def select_counted_first_attempts(
    rows: list[dict[str, Any]], case_order: dict[str, int]
) -> dict[tuple[str, str, str, str, str, str], dict[str, Any]]:
    """Map (gate, model, effort, arm, case) to the counted first row."""
    del case_order
    grouped = group_executions(rows)
    last_complete: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for key, exec_rows in grouped.items():
        short = key[:6]
        if _execution_is_complete(exec_rows) and (
            short not in last_complete
            or key[6] > int(last_complete[short][0]["execution"])
        ):
            last_complete[short] = exec_rows
    counted: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for short, exec_rows in last_complete.items():
        first = next(row for row in exec_rows if int(row["attempt"]) == 1)
        counted[short] = first
    return counted


def _is_gate_failure(row: dict[str, Any]) -> bool:
    return (
        bool(row["parsed_ok"])
        and not bool(row["blocked"])
        and any(code in GATE_FAILURE_CODES for code in _codes_of(row))
    )


def _is_beyond_wording(row: dict[str, Any]) -> bool:
    """A gate failure with at least one code outside "Wording or form"."""
    return _is_gate_failure(row) and any(
        code in GATE_FAILURE_CODES and CODE_TO_CATEGORY.get(code) != "Wording or form"
        for code in _codes_of(row)
    )


def _is_not_draft_outcome(row: dict[str, Any]) -> bool:
    codes = _codes_of(row)
    return (
        bool(row["parsed_ok"])
        and not bool(row["blocked"])
        and bool(codes)
        and all(code in NOT_DRAFT_OUTCOME_CODES for code in codes)
    )


def _is_pass(row: dict[str, Any]) -> bool:
    return bool(row["parsed_ok"]) and not bool(row["blocked"]) and not _codes_of(row)


def _is_proposal_only(row: dict[str, Any]) -> bool:
    codes = _codes_of(row)
    return (
        bool(row["parsed_ok"])
        and not bool(row["blocked"])
        and not any(code in GATE_CODES for code in codes)
        and any(code in PROPOSAL_CODES for code in codes)
    )


def _is_unparseable(row: dict[str, Any]) -> bool:
    return (
        not bool(row["parsed_ok"])
        and not bool(row["blocked"])
        and not _is_unavailable_first(row)
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _format_tokens(values: list[Any]) -> str:
    present = [float(value) for value in values if value is not None]
    if not present:
        return "not reported"
    return _format_number(_median(present))


def _preamble() -> str:
    return (
        "I asked each model to write one short briefing card per case: pick the "
        "commitment that most deserves the shown hour and write a few short claims "
        "about what the data shows. Each case ran twice, once with the product "
        "prompt (built by Ticket 11's `build_prompt` in "
        "framework/proposal/prompt.py) and once with a plain prompt that teaches "
        "none of the gate's rules (pinned verbatim in D6 of "
        "[docs/plans/016b-models-on-the-gate.md](plans/016b-models-on-the-gate.md) "
        "and built by evals/r1b_prompts.py). The Muse route carries the "
        "harness's own "
        "instructions of about 15,900 input tokens, per PREREG Deviation 10. "
        "The local route sends temperature 0 and max_tokens 32768; the Muse "
        "route exposes neither, so no cap is claimed there.\n"
        "\n"
        "The set is synthetic, one pass per case (one first draft plus at most "
        "one retry through the product's own loop). It came from two author "
        "sessions, both on muse-wonder-full-1.0 at high: a first session wrote "
        "a set from a script that drew on pools of stock sentences, and "
        "Claude Code rejected that file before any arm ran because its facts "
        "had nothing "
        "to do with its commitments, so no model under test ever saw it; a "
        "second fresh session, in Contributor mode on made-up data, in a new "
        "empty folder holding only the case-author description, was told to "
        "stay in that folder, to write every case by hand with no generator "
        "and no pooled sentence, and that a pooled set had already been "
        "rejected, and it wrote the 54 cases in this file with reminder "
        "agents off for it. Claude Code read that session's log: every path "
        "it touched was inside that folder, and it wrote no generator. That "
        "session then replaced two fact statements, in r1b-011 and r1b-028, "
        "because the private-term scan Claude Code runs on public files "
        "hit a word in "
        "them, before any arm ran. That session never saw this repository, "
        "the gate's source, the product prompt or any result. "
        "muse-wonder-full-1.0 is also one of the arms under test, with no "
        "memory across sessions. The file's sha256 was recorded right after "
        "that, and every result row carries it.\n"
        "\n"
        "The private-term check is not exercised in this benchmark: the runner "
        "passes an explicitly empty, available list, so L1_PRIVATE_TERM cannot "
        "fire and L1_PRIVATE_TERMS_UNAVAILABLE is suppressed by construction. "
        "A gate pass does not show a sentence is true, and a gate failure does "
        "not show a sentence is false. Injection cases score only what the "
        "gate sees, so a model that obeys a planted instruction in a way the "
        "gate cannot see still passes."
    )


def render_summary(
    rows: list[dict[str, Any]],
    cases: list[Any],
    *,
    arm_order: tuple[str, ...] | list[str] = ("product", "plain"),
) -> str:
    """Render the benchmark doc from the rows alone (deterministic)."""
    lines = ["# R1b — models on the gate", "", _preamble(), ""]
    live = [row for row in rows if not row.get("regated")]
    regated = [row for row in rows if row.get("regated")]
    if not live and not regated:
        lines.append("no rows yet.")
        lines.append("")
        return "\n".join(lines)
    case_ids = [case.id for case in cases]
    order = {case_id: index for index, case_id in enumerate(case_ids)}
    lines.extend(_render_group(live, case_ids, order, arm_order, regated=False))
    if regated:
        lines.extend(_render_group(regated, case_ids, order, arm_order, regated=True))
    lines.append("")
    return "\n".join(lines)


def _matrix_sort_key(model: str, effort: str) -> tuple[int, int, str, str]:
    """Matrix rows first in matrix order; unknown rows after, by name."""
    try:
        from evals.r1b import MATRIX
    except ImportError:  # pragma: no cover - the runner always ships MATRIX
        matrix: tuple[tuple[str, str], ...] = ()
    else:
        matrix = tuple((entry.model, entry.effort) for entry in MATRIX)
    if (model, effort) in matrix:
        return (0, matrix.index((model, effort)), "", "")
    return (1, 0, model, effort)


def _arm_sort_key(arm: str, arm_order: tuple[str, ...] | list[str]) -> tuple[int, str]:
    ordered = list(arm_order)
    if arm in ordered:
        return (ordered.index(arm), "")
    return (len(ordered), arm)


def _second_of(
    grouped: dict[tuple[str, str, str, str, str, str, int], list[dict[str, Any]]],
    first: dict[str, Any],
) -> dict[str, Any] | None:
    same = [
        row
        for key, exec_rows in grouped.items()
        if key[5] == str(first["case_id"]) and key[6] == int(first["execution"])
        for row in exec_rows
        if int(row["attempt"]) == 2
    ]
    return same[0] if same else None


def _last_of(
    grouped: dict[tuple[str, str, str, str, str, str, int], list[dict[str, Any]]],
    first: dict[str, Any],
) -> dict[str, Any]:
    same = [
        row
        for key, exec_rows in grouped.items()
        if key[5] == str(first["case_id"]) and key[6] == int(first["execution"])
        for row in exec_rows
    ]
    ordered = sorted(same, key=lambda row: int(row["attempt"]))
    return ordered[-1] if ordered else first


def _retry_passed(second: dict[str, Any] | None) -> bool:
    if second is None or not second["parsed_ok"]:
        return False
    return not [
        code
        for code in _codes_of(second)
        if code in GATE_CODES or code in PROPOSAL_CODES
    ]


def _arm_stats(
    row_rows: list[dict[str, Any]],
    arm: str,
    case_ids: list[str],
    order: dict[str, int],
) -> dict[str, Any]:
    """Every count the table and the detail section print for one arm."""
    arm_rows = [row for row in row_rows if str(row["arm"]) == arm]
    counted = select_counted_first_attempts(arm_rows, order)
    firsts = list(counted.values())
    grouped = group_executions(arm_rows)
    incomplete: set[str] = set()
    by_case: dict[str, list[list[dict[str, Any]]]] = {}
    for key, exec_rows in grouped.items():
        by_case.setdefault(key[5], []).append(exec_rows)
    for case_id, execs in by_case.items():
        if any(_execution_is_complete(exec_rows) for exec_rows in execs):
            continue
        attempt_ones = [
            row for exec_rows in execs for row in exec_rows if int(row["attempt"]) == 1
        ]
        if any(_is_unavailable_first(row) for row in attempt_ones):
            incomplete.add(case_id)
    counted_cases = sorted(
        {str(row["case_id"]) for row in firsts},
        key=lambda case_id: order.get(case_id, len(order)),
    )
    not_run = [
        case_id
        for case_id in case_ids
        if case_id not in set(counted_cases) and case_id not in incomplete
    ]
    passes = [row for row in firsts if _is_pass(row)]
    failures = [row for row in firsts if _is_gate_failure(row)]
    beyond = sum(1 for row in failures if _is_beyond_wording(row))
    proposal_only = [row for row in firsts if _is_proposal_only(row)]
    not_draft = [row for row in firsts if _is_not_draft_outcome(row)]
    unparseable = [row for row in firsts if _is_unparseable(row)]
    blocked = [row for row in firsts if bool(row["blocked"])]
    unavailable_all = sum(
        1 for row in arm_rows if int(row["attempt"]) == 1 and _is_unavailable_first(row)
    )
    recovered = 0
    stayed = 0
    stayed_proposal_retry = 0
    retry_unavailable = 0
    for row in failures:
        second = _second_of(grouped, row)
        if second is None:
            stayed += 1
        elif _is_unavailable_first(second):
            retry_unavailable += 1
        elif _retry_passed(second):
            recovered += 1
        else:
            stayed += 1
            if bool(second["parsed_ok"]) and not any(
                code in GATE_CODES for code in _codes_of(second)
            ):
                stayed_proposal_retry += 1
    ended_passing = sum(1 for row in firsts if _is_pass(_last_of(grouped, row)))
    unparseable_recovered = sum(
        1 for row in unparseable if _retry_passed(_second_of(grouped, row))
    )
    trap_counted: dict[str, int] = {}
    trap_failed: dict[str, int] = {}
    for row in firsts:
        trap = "clean" if row["trap"] is None else str(row["trap"])
        trap_counted[trap] = trap_counted.get(trap, 0) + 1
    for row in failures:
        trap = "clean" if row["trap"] is None else str(row["trap"])
        trap_failed[trap] = trap_failed.get(trap, 0) + 1
    return {
        "arm_rows": arm_rows,
        "firsts": firsts,
        "counted_cases": counted_cases,
        "not_run": not_run,
        "incomplete": incomplete,
        "passes": passes,
        "failures": failures,
        "beyond": beyond,
        "wording_only": len(failures) - beyond,
        "proposal_only": proposal_only,
        "not_draft": not_draft,
        "unparseable": unparseable,
        "blocked": blocked,
        "unavailable_all": unavailable_all,
        "recovered": recovered,
        "stayed": stayed,
        "stayed_proposal_retry": stayed_proposal_retry,
        "retry_unavailable": retry_unavailable,
        "ended_passing": ended_passing,
        "unparseable_recovered": unparseable_recovered,
        "trap_counted": trap_counted,
        "trap_failed": trap_failed,
    }


def _seconds(values_ms: list[float]) -> str:
    if not values_ms:
        return "not reported"
    return f"{_median(values_ms) / 1000:.1f}"


def _worst_seconds(values_ms: list[float]) -> str:
    if not values_ms:
        return "not reported"
    return f"{max(values_ms) / 1000:.1f}"


def _render_overview_table(
    by_row: dict[tuple[str, str], list[dict[str, Any]]],
    case_ids: list[str],
    order: dict[str, int],
    arm_order: tuple[str, ...] | list[str],
    *,
    regated: bool,
) -> list[str]:
    lines = [
        (
            "| model | effort | arm | counted | pass | fail | fail beyond wording | "
            "proposal-only | recovered | stayed failed | unparseable | "
            "unavailable | blocked | latency median s | latency worst s |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model, effort in sorted(by_row, key=lambda item: _matrix_sort_key(*item)):
        row_rows = by_row[(model, effort)]
        arms = sorted(
            {str(row["arm"]) for row in row_rows},
            key=lambda arm: _arm_sort_key(arm, arm_order),
        )
        for arm in arms:
            stats = _arm_stats(row_rows, arm, case_ids, order)
            latencies = [float(row["latency_ms"]) for row in stats["firsts"]]
            if regated:
                recovered = "n/a"
                stayed = "n/a"
            else:
                recovered = str(stats["recovered"])
                stayed = str(stats["stayed"])
            lines.append(
                f"| {model} | {effort} | {arm} | "
                f"{len(stats['counted_cases'])}/{len(case_ids)} | "
                f"{len(stats['passes'])} | {len(stats['failures'])} | "
                f"{stats['beyond']} | "
                f"{len(stats['proposal_only'])} | {recovered} | {stayed} | "
                f"{len(stats['unparseable'])} | {stats['unavailable_all']} | "
                f"{len(stats['blocked'])} | {_seconds(latencies)} | "
                f"{_worst_seconds(latencies)} |"
            )
    lines.append("")
    return lines


def _render_group(
    rows: list[dict[str, Any]],
    case_ids: list[str],
    order: dict[str, int],
    arm_order: tuple[str, ...] | list[str],
    *,
    regated: bool,
) -> list[str]:
    lines: list[str] = []
    by_gate: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_gate.setdefault((str(row["gate_commit"]), str(row["gate_hash"])), []).append(
            row
        )
    for commit, gate_hash in sorted(by_gate):
        label = "Re-gated rows" if regated else "Live rows"
        lines.append(f"## {label} — gate {gate_hash[:12]} (commit {commit})")
        lines.append("")
        gate_rows = by_gate[(commit, gate_hash)]
        by_row: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in gate_rows:
            by_row.setdefault((str(row["model"]), str(row["effort"])), []).append(row)
        lines.extend(
            _render_overview_table(by_row, case_ids, order, arm_order, regated=regated)
        )
        verdicts: list[str] = []
        for model, effort in sorted(by_row, key=lambda item: _matrix_sort_key(*item)):
            lines.append(f"### {model} ({effort})")
            lines.append("")
            row_rows = by_row[(model, effort)]
            present_arms = sorted(
                {str(row["arm"]) for row in row_rows},
                key=lambda arm: _arm_sort_key(arm, arm_order),
            )
            lines.append(f"cases in the set: {len(case_ids)}")
            lines.append("")
            for arm in present_arms:
                lines.extend(
                    _render_arm(
                        row_rows,
                        arm,
                        case_ids,
                        order,
                        regated=regated,
                    )
                )
            paired_verdict = _render_paired(row_rows, order, lines)
            if paired_verdict is not None:
                verdicts.append(paired_verdict)
            if effort == "none":
                lines.append(
                    "the local client has no effort parameter; `none` names "
                    "that, not a setting."
                )
                lines.append("")
        if verdicts and not regated:
            overall = _overall_verdict(verdicts)
            lines.append(
                f"overall: {overall} (did not hold if any row did not hold, "
                f"held if every row held, otherwise not evaluable)"
            )
            lines.append("")
    return lines


def _render_arm(
    row_rows: list[dict[str, Any]],
    arm: str,
    case_ids: list[str],
    order: dict[str, int],
    *,
    regated: bool,
) -> list[str]:
    lines = [f"#### arm: {arm}", ""]
    stats = _arm_stats(row_rows, arm, case_ids, order)
    firsts = stats["firsts"]
    failures = stats["failures"]
    counted_cases = stats["counted_cases"]
    incomplete = stats["incomplete"]
    not_run = stats["not_run"]
    lines.append(f"cases counted: {len(counted_cases)}")
    lines.append(f"cases attempted but not complete: {len(incomplete)}")
    lines.append(f"cases not run: {len(not_run)}")
    if (
        counted_cases
        and 0 < len(counted_cases) < len(case_ids)
        and counted_cases == case_ids[: len(counted_cases)]
    ):
        lines.append(f"ran only a prefix: the first {len(counted_cases)} cases")
    lines.append(f"first-draft passes: {len(stats['passes'])}")
    lines.append(f"first-draft gate failures: {len(failures)}")
    lines.append(
        f"first-draft gate failures beyond wording or form: {stats['beyond']} "
        f"(wording or form alone: {stats['wording_only']})"
    )
    by_code: dict[str, int] = {}
    for row in failures:
        for code in _codes_of(row):
            if code in GATE_FAILURE_CODES:
                by_code[code] = by_code.get(code, 0) + 1
    lines.append("failures by code (codes counted, one draft may count twice):")
    for code in sorted(by_code):
        lines.append(f"- {code}: {by_code[code]}")
    lines.append("failures by category (drafts counted once per category they touch):")
    for category, _codes in CATEGORY_TABLE:
        if category == "Not a draft outcome":
            continue
        touched = sum(
            1
            for row in failures
            if any(CODE_TO_CATEGORY.get(code) == category for code in _codes_of(row))
        )
        lines.append(f"- {category}: {touched}")
    lines.append(
        "A plain-arm failure is not always a false sentence: the wording split "
        "above shows how much of it is wording or form the gate insists on."
    )
    lines.append("failures by trap class (failures of counted cases in that class):")
    for trap in sorted(stats["trap_counted"]):
        lines.append(
            f"- {trap}: {stats['trap_failed'].get(trap, 0)} of "
            f"{stats['trap_counted'][trap]} counted"
        )
    proposal_codes_seen: dict[str, int] = {}
    for row in firsts:
        for code in _codes_of(row):
            if code in PROPOSAL_CODES:
                proposal_codes_seen[code] = proposal_codes_seen.get(code, 0) + 1
    lines.append("proposal-level codes (apart, never in the numerator):")
    if proposal_codes_seen:
        for code in sorted(proposal_codes_seen):
            lines.append(f"- {code}: {proposal_codes_seen[code]}")
    else:
        lines.append("- none")
    if not regated:
        lines.append(f"recovered by one retry: {stats['recovered']}")
        lines.append(f"stayed failed: {stats['stayed']}")
        lines.append(
            f"of those, retry passed the gate but kept a proposal-level code: "
            f"{stats['stayed_proposal_retry']}"
        )
        lines.append(
            f"first-draft failure whose retry came back unavailable: "
            f"{stats['retry_unavailable']}"
        )
        lines.append(
            f"ended passing within one retry: {stats['ended_passing']} of "
            f"{len(counted_cases)} counted"
        )
        lines.append(
            f"unparseable first drafts recovered by retry: "
            f"{stats['unparseable_recovered']}"
        )
    lines.append(f"proposal-level-only first drafts: {len(stats['proposal_only'])}")
    lines.append(f"not-a-draft-outcome first drafts: {len(stats['not_draft'])}")
    lines.append(f"unparseable first drafts: {len(stats['unparseable'])}")
    lines.append(f"unavailable first attempts: {stats['unavailable_all']}")
    lines.append(f"blocked first attempts: {len(stats['blocked'])}")
    latencies = [float(row["latency_ms"]) for row in firsts]
    if latencies:
        lines.append(
            f"first-attempt latency median ms: {_format_number(_median(latencies))}"
        )
        lines.append(
            f"first-attempt latency worst ms: {_format_number(max(latencies))}"
        )
    lines.append(
        "first-attempt prompt tokens median: "
        + _format_tokens([row["prompt_tokens"] for row in firsts])
    )
    lines.append(
        "first-attempt completion tokens median: "
        + _format_tokens([row["completion_tokens"] for row in firsts])
    )
    lines.append(
        "first-attempt reasoning tokens median: "
        + _format_tokens([row["reasoning_tokens"] for row in firsts])
    )
    lines.append(
        "first-attempt cached tokens median: "
        + _format_tokens([row.get("cached_tokens") for row in firsts])
    )
    lines.append("medians take the middle value, or the mean of the middle two.")
    if firsts and all(row.get("transport") == "local" for row in firsts):
        lines.append("muse versions seen: not applicable")
        lines.append("rules-file values seen: not applicable")
    else:
        versions = sorted({str(row["muse_version"]) for row in firsts})
        rules_files = sorted({str(row["harness_rules_file"]) for row in firsts})
        lines.append(f"muse versions seen: {', '.join(versions)}")
        lines.append(f"rules-file values seen: {', '.join(rules_files)}")
    lines.append("")
    return lines


def _render_paired(
    row_rows: list[dict[str, Any]], order: dict[str, int], lines: list[str]
) -> str | None:
    counted_product = select_counted_first_attempts(
        [row for row in row_rows if str(row["arm"]) == "product"], order
    )
    counted_plain = select_counted_first_attempts(
        [row for row in row_rows if str(row["arm"]) == "plain"], order
    )
    if not counted_product and not counted_plain:
        return None
    model = str(row_rows[0]["model"])
    effort = str(row_rows[0]["effort"])
    paired: list[str] = []
    excluded = 0
    for key, first_product in counted_product.items():
        case_id = key[5]
        first_plain = counted_plain.get(
            (key[0], key[1], model, effort, "plain", case_id)
        )
        if first_plain is None:
            excluded += 1
            continue
        usable_product = bool(first_product["parsed_ok"]) and not bool(
            first_product["blocked"]
        )
        usable_plain = bool(first_plain["parsed_ok"]) and not bool(
            first_plain["blocked"]
        )
        if not (usable_product and usable_plain):
            excluded += 1
            continue
        paired.append(case_id)
    for key, first_plain in counted_plain.items():
        case_id = key[5]
        if not bool(first_plain["parsed_ok"]) or bool(first_plain["blocked"]):
            continue
        match = counted_product.get((key[0], key[1], model, effort, "product", case_id))
        if match is None:
            excluded += 1
    product_failures = sum(
        1
        for case_id in paired
        if _is_gate_failure(
            counted_product[next(key for key in counted_product if key[5] == case_id)]
        )
    )
    plain_failures = sum(
        1
        for case_id in paired
        if _is_gate_failure(
            counted_plain[next(key for key in counted_plain if key[5] == case_id)]
        )
    )
    fails: dict[str, bool] = {}
    for case_id in paired:
        first_product = counted_product[
            next(key for key in counted_product if key[5] == case_id)
        ]
        first_plain = counted_plain[
            next(key for key in counted_plain if key[5] == case_id)
        ]
        fails[case_id + ":product"] = _is_gate_failure(first_product)
        fails[case_id + ":plain"] = _is_gate_failure(first_plain)
    b = sum(
        1
        for case_id in paired
        if fails[case_id + ":plain"] and not fails[case_id + ":product"]
    )
    c = sum(
        1
        for case_id in paired
        if fails[case_id + ":product"] and not fails[case_id + ":plain"]
    )
    p_value = mcnemar_exact(b, c)
    lines.append(
        f"paired: {len(paired)} cases with a parsed, unblocked first draft in "
        "both the product and the plain arm"
    )
    lines.append(
        f"paired product failures: {product_failures}; paired plain failures: "
        f"{plain_failures}"
    )
    lines.append(
        f"paired b (plain fails, product passes): {b}; c (plain passes, "
        f"product fails): {c}; excluded from the pair: {excluded}"
    )
    product_beyond = sum(
        1
        for case_id in paired
        if _is_beyond_wording(
            counted_product[next(key for key in counted_product if key[5] == case_id)]
        )
    )
    plain_beyond = sum(
        1
        for case_id in paired
        if _is_beyond_wording(
            counted_plain[next(key for key in counted_plain if key[5] == case_id)]
        )
    )
    lines.append(
        f"paired beyond wording or form (not registered, no verdict): "
        f"product {product_beyond}, plain {plain_beyond}"
    )
    if b + c == 0:
        lines.append("paired McNemar exact two-sided p: 1.0 (no discordant pairs)")
    elif p_value < 0.0001:
        lines.append("paired McNemar exact two-sided p: p < 0.0001")
    else:
        lines.append(f"paired McNemar exact two-sided p: {p_value:.4f}")
    lines.append(
        "the p-value is descriptive only: the counts are the result, and it "
        "generalises past them not at all."
    )
    lines.append(f"registered prediction: {PREDICTION}")
    if product_failures == 0:
        lines.append(
            f"verdict: {model} ({effort}): not evaluable (product failures 0, "
            f"plain failures {plain_failures}; ratio undefined)"
        )
        verdict = "not evaluable"
    elif plain_failures >= 3 * product_failures:
        lines.append(
            f"verdict: {model} ({effort}): held (product failures "
            f"{product_failures}, plain failures {plain_failures})"
        )
        verdict = "held"
    else:
        lines.append(
            f"verdict: {model} ({effort}): did not hold (product failures "
            f"{product_failures}, plain failures {plain_failures})"
        )
        verdict = "did not hold"
    lines.append("")
    return verdict


def _overall_verdict(verdicts: list[str]) -> str:
    if any(verdict == "did not hold" for verdict in verdicts):
        return "did not hold"
    if all(verdict == "held" for verdict in verdicts):
        return "held"
    return "not evaluable"
