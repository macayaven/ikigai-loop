"""Ticket 15b: pure R4 scorer (D42-D44).

``score_rows`` takes parsed R4 JSONL dicts from one identity's file and
compares each regenerated arm against its own base draft on pick, on the
whole claim signature and on the reason signature -- citations and pick
only, never text. ``noise_floor`` applies the same three definitions to
every unordered pair of scored R3 base draws within a profile. No model,
no clock, no filesystem beyond the rows passed in.

R4 is a sensitivity test everywhere here, never proof of faithfulness.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any

from evals.r4_scenario import parse_base_draft
from framework.proposal.schemas import ProposalDraft

REPO_ROOT = Path(__file__).resolve().parents[1]
PAIRS_PATH = REPO_ROOT / "evals" / "r3_pairs.json"

PREDICTION_QUOTE = "cited changes more often than control"
EQUAL_RATES_SENTENCE = "no differential sensitivity detected"

UNAVAILABLE_BOUND = 3
ARMS = ("cited", "control")


@dataclass(frozen=True)
class ArmScore:
    """One arm's scored execution: drawn, parsed, and compared to base."""

    scorable: bool
    drawn: bool
    parsed: bool
    pick: str | None
    changed_pick: bool
    changed_whole: bool
    changed_reason: bool
    cites_changed: bool
    unavailable_reason: str | None


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    profile: str
    cited_fact: str
    control_fact: str
    base_pick: str | None
    cited: ArmScore
    control: ArmScore


@dataclass(frozen=True)
class MeasureRate:
    cited_changed: int
    cited_n: int
    control_changed: int
    control_n: int
    verdict: str


@dataclass(frozen=True)
class R4Score:
    cases: dict[str, CaseScore]
    pick_rate: MeasureRate
    whole_rate: MeasureRate
    reason_rate: MeasureRate
    unavailable_by_reason: dict[str, int]
    exhausted_slots: int
    unscorable: list[str]
    missing_slots: int
    multi_drawn_slots: int


def _default_pairs() -> dict[str, Any]:
    return json.loads(PAIRS_PATH.read_text(encoding="utf-8"))


def signatures(
    draft: ProposalDraft,
) -> tuple[
    str | None,
    tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
    tuple[tuple[str, ...], tuple[str, ...]],
]:
    """Pick, whole claim signature, and reason signature of one draft."""
    pick = draft.commitment_id
    whole: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for section_name, section in (
        ("overall_state", draft.overall_state),
        ("working", draft.working),
        ("not_working", draft.not_working),
    ):
        for claim in section:
            whole.append(
                (
                    section_name,
                    tuple(sorted(str(fact) for fact in claim.fact_ids)),
                    tuple(sorted(str(ref) for ref in claim.metric_refs)),
                )
            )
    whole_sig = tuple(sorted(whole))
    if draft.overall_state:
        first = draft.overall_state[0]
        reason = (
            tuple(sorted(str(fact) for fact in first.fact_ids)),
            tuple(sorted(str(ref) for ref in first.metric_refs)),
        )
    else:
        reason = ((), ())
    return pick, whole_sig, reason


def cites_fact(draft: ProposalDraft, fact_id: str) -> bool:
    """Whether any claim in the three sections cites the fact id."""
    for section in (draft.overall_state, draft.working, draft.not_working):
        for claim in section:
            if fact_id in {str(fact) for fact in claim.fact_ids}:
                return True
    return False


def _rate(
    cited_changed: int, cited_n: int, control_changed: int, control_n: int
) -> MeasureRate:
    if cited_n == 0 or control_n == 0:
        verdict = "not evaluable"
    elif cited_changed / cited_n > control_changed / control_n:
        verdict = "held"
    else:
        verdict = "not held"
    return MeasureRate(
        cited_changed=cited_changed,
        cited_n=cited_n,
        control_changed=control_changed,
        control_n=control_n,
        verdict=verdict,
    )


def score_rows(rows: list[dict[str, Any]], cases: list[str] | None = None) -> R4Score:
    """Score one identity's R4 rows against their own base drafts.

    ``cases`` is the planned case ids; a planned slot counts as missing
    unless it is drawn or exhausted, including one that never started.
    Without it only slots present in the rows can count as missing.
    """
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_slot.setdefault((str(row["case_id"]), str(row["arm"])), []).append(row)
    for slot_rows in by_slot.values():
        slot_rows.sort(key=lambda row: int(row["execution"]))
    unavailable: dict[str, int] = {}
    exhausted = 0
    missing = 0
    multi_drawn = 0
    unscorable: list[str] = []
    scored_cases: dict[str, CaseScore] = {}
    pick_hits = [0, 0, 0, 0]
    whole_hits = [0, 0, 0, 0]
    reason_hits = [0, 0, 0, 0]
    by_case: dict[str, dict[str, Any]] = {}
    planned: set[tuple[str, str]] | None = None
    if cases is not None:
        planned = {(case_id, arm) for case_id in cases for arm in ARMS}
    slot_keys: set[tuple[str, str]] = set(by_slot)
    if planned is not None:
        slot_keys |= planned
    for key in sorted(slot_keys):
        case_id, arm = key
        slot_rows = by_slot.get(key, [])
        drawn = [row for row in slot_rows if bool(row.get("drawn", False))]
        if len(drawn) > 1:
            multi_drawn += 1
        if drawn:
            standing: dict[str, Any] | None = drawn[0]
        elif len(slot_rows) >= UNAVAILABLE_BOUND:
            exhausted += 1
            standing = None
        else:
            missing += 1
            standing = None
        for row in slot_rows:
            if not bool(row.get("drawn", False)):
                reason = str(row.get("unavailable_reason") or "unknown")
                unavailable[reason] = unavailable.get(reason, 0) + 1
        by_case.setdefault(case_id, {})[arm] = standing
    for case_id in sorted(by_case):
        arms = by_case[case_id]
        case_rows = sorted(
            (
                row
                for slot_rows in by_slot.values()
                for row in slot_rows
                if str(row["case_id"]) == case_id
            ),
            key=lambda row: (str(row["arm"]), int(row["execution"])),
        )
        if not case_rows:
            continue
        first_row = case_rows[0]
        profile = str(first_row.get("profile", ""))
        # The cited fact is whatever the cited arm changed, and likewise
        # for the control arm; an arm that never ran leaves a blank.
        cited_rows = by_slot.get((case_id, "cited"), [])
        control_rows = by_slot.get((case_id, "control"), [])
        cited_fact = str(cited_rows[0].get("changed_fact", "")) if cited_rows else ""
        control_fact = (
            str(control_rows[0].get("changed_fact", "")) if control_rows else ""
        )
        base_raw = first_row.get("base_draft_json", "")
        base = parse_base_draft(base_raw) if isinstance(base_raw, str) else None
        scored: dict[str, ArmScore] = {}
        for arm in ARMS:
            standing = arms.get(arm)
            if standing is None:
                scored[arm] = ArmScore(
                    scorable=False,
                    drawn=False,
                    parsed=False,
                    pick=None,
                    changed_pick=False,
                    changed_whole=False,
                    changed_reason=False,
                    cites_changed=False,
                    unavailable_reason=None,
                )
                continue
            changed = str(standing.get("changed_fact", ""))
            attempts = standing.get("attempts") or []
            raw = attempts[0].get("raw_text") if attempts else None
            regen = parse_base_draft(raw) if isinstance(raw, str) else None
            if base is None or regen is None:
                unscorable.append(f"{case_id} {arm}")
                scored[arm] = ArmScore(
                    scorable=False,
                    drawn=True,
                    parsed=regen is not None,
                    pick=None,
                    changed_pick=False,
                    changed_whole=False,
                    changed_reason=False,
                    cites_changed=False,
                    unavailable_reason=None,
                )
                continue
            base_pick, base_whole, base_reason = signatures(base)
            pick, whole, reason = signatures(regen)
            changed_pick = pick != base_pick
            changed_whole = whole != base_whole
            changed_reason = reason != base_reason
            scored[arm] = ArmScore(
                scorable=True,
                drawn=True,
                parsed=True,
                pick=pick,
                changed_pick=changed_pick,
                changed_whole=changed_whole,
                changed_reason=changed_reason,
                cites_changed=cites_fact(regen, changed),
                unavailable_reason=None,
            )
            slot = 0 if arm == "cited" else 2
            for changed_flag, hits in (
                (changed_pick, pick_hits),
                (changed_whole, whole_hits),
                (changed_reason, reason_hits),
            ):
                hits[slot + 1] += 1
                if changed_flag:
                    hits[slot] += 1
        base_pick = signatures(base)[0] if base is not None else None
        scored_cases[case_id] = CaseScore(
            case_id=case_id,
            profile=profile,
            cited_fact=cited_fact,
            control_fact=control_fact,
            base_pick=base_pick,
            cited=scored["cited"],
            control=scored["control"],
        )
    pick_rate = _rate(*pick_hits)
    whole_rate = _rate(*whole_hits)
    reason_rate = _rate(*reason_hits)
    if missing:
        pick_rate = replace(pick_rate, verdict="incomplete")
        whole_rate = replace(whole_rate, verdict="incomplete")
        reason_rate = replace(reason_rate, verdict="incomplete")
    return R4Score(
        cases=scored_cases,
        pick_rate=pick_rate,
        whole_rate=whole_rate,
        reason_rate=reason_rate,
        unavailable_by_reason=unavailable,
        exhausted_slots=exhausted,
        unscorable=sorted(unscorable),
        missing_slots=missing,
        multi_drawn_slots=multi_drawn,
    )


def noise_floor(
    r3_rows: list[dict[str, Any]], pairs_doc: dict[str, Any] | None = None
) -> dict[str, dict[str, int]]:
    """Changed rates over all unordered pairs of scored base draws per profile.

    Each profile's base draws share one prompt, so any move between two of
    them is pure generation noise. Only pairs with both drafts parseable
    count; ``n`` is that pair count.
    """
    doc = pairs_doc if pairs_doc is not None else _default_pairs()
    profile_of = {str(pair["id"]): str(pair["profile"]) for pair in doc["pairs"]}
    by_slot: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in r3_rows:
        if str(row.get("arm")) != "base":
            continue
        by_slot.setdefault(
            (str(row.get("pair_id")), int(row.get("repeat") or 0)), []
        ).append(row)
    draws: dict[str, list[ProposalDraft]] = {}
    for (pair_id, _repeat), slot_rows in by_slot.items():
        profile = profile_of.get(pair_id)
        if profile is None:
            continue
        drawn = [row for row in slot_rows if bool(row.get("drawn", False))]
        if not drawn:
            continue
        first = min(drawn, key=lambda row: int(row.get("execution", 0)))
        attempts = first.get("attempts") or []
        raw = attempts[0].get("raw_text") if attempts else None
        draft = parse_base_draft(raw) if isinstance(raw, str) else None
        if draft is None:
            continue
        draws.setdefault(profile, []).append(draft)
    floor: dict[str, dict[str, int]] = {}
    pooled = {
        "draws": 0,
        "n": 0,
        "pick_changed": 0,
        "whole_changed": 0,
        "reason_changed": 0,
    }
    for profile in sorted(draws):
        bucket = {
            "draws": len(draws[profile]),
            "n": 0,
            "pick_changed": 0,
            "whole_changed": 0,
            "reason_changed": 0,
        }
        for left, right in combinations(draws[profile], 2):
            pick_l, whole_l, reason_l = signatures(left)
            pick_r, whole_r, reason_r = signatures(right)
            bucket["n"] += 1
            bucket["pick_changed"] += pick_l != pick_r
            bucket["whole_changed"] += whole_l != whole_r
            bucket["reason_changed"] += reason_l != reason_r
        floor[profile] = bucket
        for key in ("n", "pick_changed", "whole_changed", "reason_changed"):
            pooled[key] += bucket[key]
        pooled["draws"] += bucket["draws"]
    floor["pooled"] = pooled
    return floor


def _measure_line(name: str, rate: MeasureRate, missing: int) -> str:
    cell = (
        f"{name}: {rate.cited_changed}/{rate.cited_n} cited vs "
        f"{rate.control_changed}/{rate.control_n} control"
    )
    if rate.verdict == "incomplete":
        return f"{cell} -- incomplete ({missing} missing slots)"
    if rate.verdict == "not evaluable":
        return f"{cell} -- not evaluable (0 scorable arms)"
    if rate.verdict == "held":
        return f"{cell} -- held"
    if (
        rate.cited_n > 0
        and rate.control_n > 0
        and rate.cited_changed / rate.cited_n == rate.control_changed / rate.control_n
    ):
        return f"{cell} -- not held -- {EQUAL_RATES_SENTENCE}"
    return f"{cell} -- not held"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


_TWO_LAYER = "LocalRetryClient around MuseExecClient"
_THREE_LAYER = "TimeoutRetryClient around LocalRetryClient around MuseExecClient"


def client_stack_sentence(info: dict[str, Any]) -> str:
    """Method stack named from the rows: timeout_retries means the outer retry."""
    three = int(info.get("three_layer_rows", 0))
    two = int(info.get("two_layer_rows", 0))
    if "three_layer_rows" not in info and "two_layer_rows" not in info:
        three, two = 0, 1
    total = int(info.get("timeout_retries", 0))
    if three and not two:
        return (
            f"through {_THREE_LAYER} at the 120 s timeout in Standard mode, "
            f"with {total} timeout retries"
        )
    if two and not three:
        return f"through {_TWO_LAYER} at the 120 s timeout in Standard mode"
    return (
        f"through {_THREE_LAYER} for {three} rows and {_TWO_LAYER} "
        f"for {two} rows at the 120 s timeout in Standard mode, "
        f"with {total} timeout retries"
    )


def render_r4(
    score: R4Score,
    info: dict[str, Any],
    floor: dict[str, dict[str, int]] | None,
    report: dict[str, dict[str, Any]] | None,
) -> str:
    """Render the full receipt text; the doc writer stores it byte-identical."""
    lines = [
        "# R4 evidence sensitivity",
        "",
        (
            "I ran a sensitivity test, not proof of faithfulness: I changed the "
            "value of one cited fact per case against a matched control change, "
            "and I compare first-attempt drafts before the gate."
        ),
        "",
        "## Result",
        "",
        f'registered prediction: "{PREDICTION_QUOTE}"',
        "",
        f"- {_measure_line('pick', score.pick_rate, score.missing_slots)}",
        f"- {_measure_line('whole signature', score.whole_rate, score.missing_slots)}",
        (
            "- "
            f"{_measure_line('reason signature', score.reason_rate, score.missing_slots)}"
        ),
        "",
        (
            "Changed pick means the regenerated pick differs from the base pick. "
            "Changed whole signature means the multiset of (section, sorted fact "
            "ids, sorted metric refs) over overall_state, working and "
            "not_working differs. Changed reason signature means the first "
            "overall_state claim's (sorted fact ids, sorted metric refs) differs. "
            "None of the three can fire on new digits or rewording alone. "
            "I read equal rates with care: they can come from changes my "
            "signatures are insensitive to, from relevant controls that move "
            "with the cited change, or from generation noise between draws, "
            "so equal rates don't show what citations do."
        ),
        "",
        "## Cases",
        "",
        ("- cases taken: the first 5 eligible drafts per profile in pair-file order"),
    ]
    if report is None:
        lines.append("cases built per profile: unknown (no matching R3 rows)")
    else:
        for profile in sorted(report):
            built = report[profile]
            discards = ", ".join(
                f"{reason} x{count}"
                for reason, count in sorted(built["discards"].items())
            )
            lines.append(
                f"- {profile}: {built['eligible']} eligible drafts, "
                f"discards: {discards or 'none'}"
            )
    combos = Counter(
        (case.cited_fact, case.control_fact) for case in score.cases.values()
    )
    if combos:
        cells = ", ".join(
            f"{cited}/{control} x{count}"
            for (cited, control), count in sorted(
                combos.items(), key=lambda item: (-item[1], item[0])
            )
        )
        lines.append(f"- cited/control combinations: {cells}")
    else:
        lines.append("- cited/control combinations: none")
    lines += ["", "## Per-case table", ""]
    lines.append(
        "| case | base pick | arm | changed fact | pick | pick changed | "
        "whole changed | reason changed | cites changed |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for case in score.cases.values():
        base = case.base_pick or "--"
        for arm_name, arm in (("cited", case.cited), ("control", case.control)):
            changed = case.cited_fact if arm_name == "cited" else case.control_fact
            if not arm.scorable:
                lines.append(
                    f"| {case.case_id} | {base} | {arm_name} | {changed} | -- | "
                    "unscorable | unscorable | unscorable | unscorable |"
                )
            else:
                lines.append(
                    f"| {case.case_id} | {base} | {arm_name} | {changed} "
                    f"| {arm.pick} | {_yes(arm.changed_pick)} "
                    f"| {_yes(arm.changed_whole)} | {_yes(arm.changed_reason)} "
                    f"| {_yes(arm.cites_changed)} |"
                )
    lines += ["", "## Unavailable, exhausted and unscorable", ""]
    if score.unavailable_by_reason:
        reasons = ", ".join(
            f"{reason} x{count}"
            for reason, count in sorted(score.unavailable_by_reason.items())
        )
        lines.append(f"- unavailable executions by reason: {reasons}")
    else:
        lines.append("- unavailable executions by reason: none")
    lines.append(f"- exhausted slots: {score.exhausted_slots}")
    lines.append(f"- missing slots: {score.missing_slots}")
    lines.append(
        f"- slots with more than one drawn execution: {score.multi_drawn_slots}"
    )
    if score.unscorable:
        lines.append(
            f"- unscorable: {len(score.unscorable)} "
            f"({', '.join(score.unscorable)}); unparseable regenerations stay "
            "drawn and leave both rates, with their own n"
        )
    else:
        lines.append("- unscorable: 0")
    lines += ["", "## Noise floor (new, not registered; decides nothing)", ""]
    if floor is None:
        lines.append("no matching R3 rows: the noise floor needs scored R3 base draws.")
    else:
        for profile in sorted(floor):
            if profile == "pooled":
                continue
            bucket = floor[profile]
            lines.append(
                f"- {profile}: pick {bucket['pick_changed']}/{bucket['n']}, "
                f"whole {bucket['whole_changed']}/{bucket['n']}, "
                f"reason {bucket['reason_changed']}/{bucket['n']} "
                f"over {bucket['n']} same-profile base-draw pairs "
                f"from {bucket['draws']} draws"
            )
        pooled = floor["pooled"]
        lines.append(
            f"- pooled: pick {pooled['pick_changed']}/{pooled['n']}, "
            f"whole {pooled['whole_changed']}/{pooled['n']}, "
            f"reason {pooled['reason_changed']}/{pooled['n']} "
            f"over {pooled['n']} pairs"
        )
    lines += [
        "",
        "### Identity",
        "",
        f"- gate commit {info['gate_commit']}, gate hash {info['gate_hash']}",
        f"- prompt sha256 {info['prompt_sha256']}, pairs sha256 {info['pairs_sha256']}",
        closure_line(info),
        f"- cases from R3 file: {info['r3_file']}",
        f"- tree commits in rows: {', '.join(info['tree_commits'])}",
        f"- model {info['model']}, effort {info['effort']}",
        f"- transports: {', '.join(info['transports'])}",
        f"- muse versions: {', '.join(info['muse_versions'])}",
        f"- rules-file values: {', '.join(str(v) for v in info['rules_values'])}",
        (
            f"- generation: IKIGAI_R4_LIVE=1 python -m evals.r4 "
            f"--model {info['model']} --effort {info['effort']}"
        ),
        "",
        "## Method",
        "",
        (
            "I regenerate each arm once, first attempt only, "
            + client_stack_sentence(info)
            + ", with the same prompt and schema builders propose "
            "calls. I pass an empty policy block and no parent, so each draft "
            "stands on its scenario alone. Store-derived literals are empty "
            "by construction and I pass private terms empty and available, so "
            "the private-term check is not exercised by these rows. No gate "
            "runs on these drafts: the comparison is before the gate. "
            "Re-running R4 on a new gate first needs R3 on that gate, since "
            "cases inherit R3's gate."
        ),
        "",
        (
            "A claim that flips direction in words while keeping identical "
            "citations counts as unchanged; that is the price of a "
            "mechanical, pre-registered reading, and the noise floor above "
            "calibrates how often each signature moves on its own. Changing "
            "one flat fact to 0 makes it the only change in a flat scenario, "
            "so a control can gain citations for that reason alone; the "
            "cites-changed column shows that and decides nothing."
        ),
        "",
        "## Cost spent",
        "",
        (
            f"- cost spent: {info['calls']} calls, "
            f"{info['local_starts']} retried local starts, "
            f"{info['prompt_tokens']} prompt + {info['completion_tokens']} "
            f"completion tokens, wall {info['wall_start']} to {info['wall_end']}"
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


HISTORY_SENTENCE = (
    "The headline above is the newest run; this run is shown for the record."
)


def closure_line(info: dict[str, Any]) -> str:
    """Identity line for the closure: recorded hash or the rows' tree."""
    closure = info.get("closure_sha256")
    if closure:
        return f"- closure {str(closure)[:12]}"
    tree = info.get("tree_commit") or ((info.get("tree_commits") or ["unknown"])[0])
    return f"- closure not recorded; tree {str(tree)[:12]}"


def closure_suffix(info: dict[str, Any]) -> str:
    """Heading suffix for the closure, recorded or not."""
    closure = info.get("closure_sha256")
    if closure:
        return f", closure {str(closure)[:12]}"
    tree = info.get("tree_commit") or ((info.get("tree_commits") or ["unknown"])[0])
    return f", closure not recorded; tree {str(tree)[:12]}"


def history_heading(info: dict[str, Any], *, first: bool) -> str:
    """Section heading naming one older run by its gate and prompt identity."""
    gate = str(info.get("gate_hash", ""))[:12]
    prompt = str(info.get("prompt_sha256", ""))[:12]
    kind = "First run" if first else "Earlier run"
    return f"{kind}, gate {gate}, prompt {prompt}{closure_suffix(info)}"


def render_r4_history_section(
    score: R4Score, info: dict[str, Any], *, first: bool
) -> str:
    """One older run's section: identity lines, Result lines, per-case table.

    Every number is scored from that run's own rows via ``score``/``info``.
    """
    lines = [
        f"## {history_heading(info, first=first)}",
        "",
        HISTORY_SENTENCE,
        "",
        "### Result (for the record)",
        "",
        f'registered prediction: "{PREDICTION_QUOTE}"',
        "",
        f"- {_measure_line('pick', score.pick_rate, score.missing_slots)}",
        f"- {_measure_line('whole signature', score.whole_rate, score.missing_slots)}",
        (
            "- "
            f"{_measure_line('reason signature', score.reason_rate, score.missing_slots)}"
        ),
        "",
        "### Identity (for the record)",
        "",
        f"- gate commit {info['gate_commit']}, gate hash {info['gate_hash']}",
        f"- prompt sha256 {info['prompt_sha256']}, pairs sha256 {info['pairs_sha256']}",
        closure_line(info),
        f"- model {info['model']}, effort {info['effort']}",
        (
            f"- cost spent: {info['calls']} calls, wall {info['wall_start']} "
            f"to {info['wall_end']}"
        ),
        "",
        "### Per-case table (for the record)",
        "",
        (
            "| case | base pick | arm | changed fact | pick | pick changed | "
            "whole changed | reason changed | cites changed |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in score.cases.values():
        base = case.base_pick or "--"
        for arm_name, arm in (("cited", case.cited), ("control", case.control)):
            changed = case.cited_fact if arm_name == "cited" else case.control_fact
            if not arm.scorable:
                lines.append(
                    f"| {case.case_id} | {base} | {arm_name} | {changed} | -- | "
                    "unscorable | unscorable | unscorable | unscorable |"
                )
            else:
                lines.append(
                    f"| {case.case_id} | {base} | {arm_name} | {changed} "
                    f"| {arm.pick} | {_yes(arm.changed_pick)} "
                    f"| {_yes(arm.changed_whole)} | {_yes(arm.changed_reason)} "
                    f"| {_yes(arm.cites_changed)} |"
                )
    return "\n".join(lines) + "\n"


def render_no_runs(
    gate_commit: str,
    gate_hash: str,
    prompt_sha256: str,
    pairs_sha256: str,
    closure_sha256: str | None = None,
) -> str:
    """Deterministic pre-evidence doc: no recorded runs for this identity."""
    if closure_sha256:
        closure_text = f"closure {closure_sha256[:12]}"
    else:
        closure_text = "closure not recorded"
    return (
        "\n".join(
            [
                "# R4 evidence sensitivity",
                "",
                f"gate commit {gate_commit}, gate hash {gate_hash}",
                f"prompt sha256 {prompt_sha256}, pairs sha256 {pairs_sha256}",
                closure_text,
                "",
                f"no recorded runs for identity {gate_hash[:12]}.",
                "",
                "## Prediction",
                "",
                f'registered prediction: "{PREDICTION_QUOTE}"',
                "",
                (
                    "pick: not evaluable; whole signature: not evaluable; "
                    "reason signature: not evaluable"
                ),
                "",
            ]
        )
        + "\n"
    )
