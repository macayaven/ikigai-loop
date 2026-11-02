"""Ticket 15b: pure R3 scorer (D30-D32, D35).

``score_rows`` takes parsed JSONL dicts from one identity's file and
applies the registered pass rules to the letter, under both the re-run
reading (latest drawn execution stands) and the literal reading (each
slot's first execution stands). No model, no clock, no filesystem
beyond the rows passed in.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PAIRS_PATH = REPO_ROOT / "evals" / "r3_pairs.json"

WILSON_Z = 1.959964
UNAVAILABLE_BOUND = 3
DIRECTIONAL_THRESHOLD = 0.70
INVARIANCE_THRESHOLD = 8

PREDICTION_QUOTE = (
    "at least 70% of informative directional pairs and at least 8 of 10 invariance"
)


@dataclass(frozen=True)
class ArmResult:
    """One arm's three repeats in run order."""

    picks: tuple[str | None, ...]
    labels: tuple[str, ...]
    real: int
    most: frozenset[str]
    stable: bool


@dataclass(frozen=True)
class PairScore:
    pair_id: str
    kind: str
    profile: str
    expect_pick: str | None
    expect_avoid: str | None
    informative: bool
    uninformative_reason: str | None
    passed: bool
    base: ArmResult
    perturbed: ArmResult
    missing: int


@dataclass(frozen=True)
class Score:
    pairs: dict[str, PairScore]
    directional_total: int
    directional_passes: int
    directional_informative: int
    directional_uninformative: dict[str, str]
    invariance_passes: int
    invariance_total: int
    invariance_no_pick_pairs: int
    missing_slots: int
    unavailable_by_reason: dict[str, int]
    exhausted_slots: int
    multi_drawn_slots: int
    verdict_directional: str
    verdict_invariance: str
    verdict_combined: str
    timeout_attempts: int
    total_attempts: int


@dataclass(frozen=True)
class R3Score:
    rerun: Score
    literal: Score | None
    literal_applies: bool


def wilson(successes: int, trials: int, z: float = WILSON_Z) -> tuple[float, float]:
    """95% score interval for these fixed pairs; it generalizes nowhere."""
    if trials <= 0:
        return (0.0, 0.0)
    p = successes / trials
    denom = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denom
    half = z * sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _default_pairs() -> dict[str, Any]:
    return json.loads(PAIRS_PATH.read_text(encoding="utf-8"))


def _slot_rows(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    by_slot: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["pair_id"]), str(row["arm"]), int(row["repeat"]))
        by_slot.setdefault(key, []).append(row)
    for slot_rows in by_slot.values():
        slot_rows.sort(key=lambda row: int(row["execution"]))
    return by_slot


def _most_picked(picks: list[str | None]) -> frozenset[str]:
    counts = Counter(p for p in picks if p is not None)
    if not counts:
        return frozenset()
    top = max(counts.values())
    return frozenset(p for p, n in counts.items() if n == top)


def _score_selection(
    pairs_doc: dict[str, Any],
    by_slot: dict[tuple[str, str, int], list[dict[str, Any]]],
    *,
    literal: bool,
) -> Score:
    pairs = pairs_doc["pairs"]
    scored: dict[str, PairScore] = {}
    unavailable: Counter[str] = Counter()
    exhausted = 0
    missing = 0
    for row in [row for slot_rows in by_slot.values() for row in slot_rows]:
        if not bool(row.get("drawn", False)):
            unavailable[str(row.get("unavailable_reason") or "unknown")] += 1
    directional_passes = 0
    directional_informative = 0
    directional_uninformative: dict[str, str] = {}
    invariance_passes = 0
    invariance_no_pick = 0
    for pair in pairs:
        pair_id = str(pair["id"])
        kind = str(pair["kind"])
        profile = str(pair["profile"])
        expect_pick = pair.get("expect_pick")
        expect_avoid = pair.get("expect_avoid")
        arms: dict[str, ArmResult] = {}
        pair_missing = 0
        for arm in ("base", "perturbed"):
            picks: list[str | None] = []
            labels: list[str] = []
            for repeat in (1, 2, 3):
                slot_rows = by_slot.get((pair_id, arm, repeat), [])
                if literal:
                    if not slot_rows:
                        picks.append(None)
                        labels.append("—(missing)")
                        pair_missing += 1
                    else:
                        first = slot_rows[0]
                        if bool(first.get("drawn", False)):
                            pick = first.get("pick")
                            picks.append(str(pick) if pick is not None else None)
                            labels.append(
                                str(pick)
                                if pick is not None
                                else f"—({first.get('result_kind') or 'fallback'})"
                            )
                        else:
                            picks.append(None)
                            labels.append("—(unavailable-exhausted)")
                else:
                    drawn = [r for r in slot_rows if bool(r.get("drawn", False))]
                    if drawn:
                        # The first drawn execution stands: resume never
                        # re-runs a drawn slot, so a second drawn execution
                        # is a fault and must not silently replace the first.
                        latest = drawn[0]
                        pick = latest.get("pick")
                        picks.append(str(pick) if pick is not None else None)
                        labels.append(
                            str(pick)
                            if pick is not None
                            else f"—({latest.get('result_kind') or 'fallback'})"
                        )
                    elif len(slot_rows) >= UNAVAILABLE_BOUND:
                        picks.append(None)
                        labels.append("—(unavailable-exhausted)")
                        exhausted += 1
                    else:
                        picks.append(None)
                        labels.append("—(missing)")
                        pair_missing += 1
            real = sum(1 for p in picks if p is not None)
            real_picks = [p for p in picks if p is not None]
            arms[arm] = ArmResult(
                picks=tuple(picks),
                labels=tuple(labels),
                real=real,
                most=_most_picked(picks),
                stable=real >= 2 and len(set(real_picks)) == 1,
            )
        missing += pair_missing
        base, perturbed = arms["base"], arms["perturbed"]
        base_picks = list(base.picks)
        pert_picks = list(perturbed.picks)
        if kind == "directional":
            target = expect_pick if expect_pick is not None else expect_avoid
            assert target is not None
            base_hits = sum(1 for p in base_picks if p == target)
            pert_hits = sum(1 for p in pert_picks if p == target)
            if base.real < 2:
                informative = False
                reason: str | None = "base-fewer-than-2-real-picks"
            elif expect_pick is not None and base_hits == 3:
                informative = False
                reason = "base-picks-expect-3-of-3"
            elif expect_avoid is not None and base_hits == 0:
                informative = False
                reason = "base-never-picks-avoid"
            else:
                informative = True
                reason = None
            if pair_missing or not informative:
                passed = False
            elif expect_pick is not None:
                passed = pert_hits >= 2 and pert_hits > base_hits
            else:
                passed = (
                    perturbed.real >= 2 and pert_hits <= 1 and pert_hits < base_hits
                )
            if informative:
                directional_informative += 1
                if passed:
                    directional_passes += 1
            else:
                assert reason is not None
                directional_uninformative[pair_id] = reason
        else:
            informative = True
            reason = None
            if pair_missing or base.real < 1 or perturbed.real < 1:
                passed = False
            else:
                passed = perturbed.most <= base.most
            if passed:
                invariance_passes += 1
            if base.real == 0 or perturbed.real == 0:
                invariance_no_pick += 1
        scored[pair_id] = PairScore(
            pair_id=pair_id,
            kind=kind,
            profile=profile,
            expect_pick=str(expect_pick) if expect_pick is not None else None,
            expect_avoid=str(expect_avoid) if expect_avoid is not None else None,
            informative=informative,
            uninformative_reason=reason,
            passed=passed,
            base=base,
            perturbed=perturbed,
            missing=pair_missing,
        )
    directional_total = sum(1 for p in pairs if str(p["kind"]) == "directional")
    invariance_total = sum(1 for p in pairs if str(p["kind"]) == "invariance")
    directional_missing = sum(
        s.missing for s in scored.values() if s.kind == "directional"
    )
    invariance_missing = sum(
        s.missing for s in scored.values() if s.kind == "invariance"
    )
    if directional_missing:
        verdict_directional = "incomplete"
    elif directional_informative == 0:
        verdict_directional = "not evaluable"
    elif directional_passes / directional_informative >= DIRECTIONAL_THRESHOLD:
        verdict_directional = "held"
    else:
        verdict_directional = "not held"
    if invariance_missing:
        verdict_invariance = "incomplete"
    elif invariance_passes >= INVARIANCE_THRESHOLD:
        verdict_invariance = "held"
    else:
        verdict_invariance = "not held"
    multi_drawn = sum(
        1
        for slot_rows in by_slot.values()
        if sum(1 for row in slot_rows if bool(row.get("drawn", False))) > 1
    )
    total_attempts = sum(
        len(row.get("attempts", []) or [])
        for slot_rows in by_slot.values()
        for row in slot_rows
    )
    timeout_attempts = sum(
        1
        for slot_rows in by_slot.values()
        for row in slot_rows
        for attempt in (row.get("attempts", []) or [])
        for code in (attempt.get("codes", []) or [])
        if list(code) == ["MODEL_UNAVAILABLE", "timeout"]
    )
    if verdict_directional == "incomplete" or verdict_invariance == "incomplete":
        verdict_combined = "incomplete"
    elif verdict_directional == "not evaluable":
        verdict_combined = "not evaluable"
    elif verdict_directional == "held" and verdict_invariance == "held":
        verdict_combined = "held"
    else:
        verdict_combined = "not held"
    return Score(
        pairs=scored,
        directional_total=directional_total,
        directional_passes=directional_passes,
        directional_informative=directional_informative,
        directional_uninformative=directional_uninformative,
        invariance_passes=invariance_passes,
        invariance_total=invariance_total,
        invariance_no_pick_pairs=invariance_no_pick,
        missing_slots=missing,
        unavailable_by_reason=dict(unavailable),
        exhausted_slots=exhausted,
        multi_drawn_slots=multi_drawn,
        verdict_directional=verdict_directional,
        verdict_invariance=verdict_invariance,
        verdict_combined=verdict_combined,
        timeout_attempts=timeout_attempts,
        total_attempts=total_attempts,
    )


def score_rows(
    rows: list[dict[str, Any]], pairs_doc: dict[str, Any] | None = None
) -> R3Score:
    """Score one identity's rows under both readings."""
    doc = pairs_doc if pairs_doc is not None else _default_pairs()
    by_slot = _slot_rows(rows)
    rerun = _score_selection(doc, by_slot, literal=False)
    applies = any(
        len(slot_rows) > 1 and not bool(slot_rows[0].get("drawn", False))
        for slot_rows in by_slot.values()
    )
    literal = _score_selection(doc, by_slot, literal=True) if applies else None
    return R3Score(rerun=rerun, literal=literal, literal_applies=applies)


def profile_rate(score: Score, profile: str) -> tuple[int, int]:
    """(numerator, denominator) for one profile, per the registered rule."""
    num = 0
    den = 0
    for pair in score.pairs.values():
        if pair.profile != profile:
            continue
        if pair.kind == "directional":
            if pair.informative:
                den += 1
                if pair.passed:
                    num += 1
        else:
            den += 1
            if pair.passed:
                num += 1
    return (num, den)


def stability_summary(score: Score) -> dict[str, Any]:
    """Repeat stability overall and per kind, with the excluded count."""
    stable = 0
    eligible = 0
    by_kind: dict[str, list[int]] = {}
    excluded = 0
    for pair in score.pairs.values():
        for arm in (pair.base, pair.perturbed):
            if arm.real >= 2:
                eligible += 1
                bucket = by_kind.setdefault(pair.kind, [0, 0])
                bucket[1] += 1
                if arm.stable:
                    stable += 1
                    bucket[0] += 1
            else:
                excluded += 1
    return {
        "overall": (stable, eligible),
        "by_kind": {kind: (s, e) for kind, (s, e) in by_kind.items()},
        "excluded": excluded,
    }


def base_spread(score: Score) -> dict[str, dict[str, int]]:
    """Per profile, base draws tabulated by commitment, over real picks only."""
    spread: dict[str, Counter[str]] = {}
    for pair in score.pairs.values():
        bucket = spread.setdefault(pair.profile, Counter())
        for pick in pair.base.picks:
            if pick is not None:
                bucket[str(pick)] += 1
    return {profile: dict(counts) for profile, counts in spread.items()}


def base_no_picks(score: Score) -> dict[str, int]:
    """Per profile, base draws with no pick, shown on their own."""
    counts: dict[str, int] = {}
    for pair in score.pairs.values():
        counts.setdefault(pair.profile, 0)
        counts[pair.profile] += sum(1 for pick in pair.base.picks if pick is None)
    return counts


def _fmt_interval(successes: int, trials: int) -> str:
    low, high = wilson(successes, trials)
    return f"Wilson 95% {low:.2f} to {high:.2f}"


def _verdict_label(pair: PairScore) -> str:
    """pass, fail, or uninformative with its reason — never fail for the latter."""
    if not pair.informative:
        return f"uninformative ({pair.uninformative_reason})"
    return "pass" if pair.passed else "fail"


def _most_cell(picks: frozenset[str]) -> str:
    return ", ".join(sorted(picks)) if picks else "—"


def _uninformative_sentence(pair: PairScore) -> str | None:
    """One plain first-person sentence saying why a pair can't show a move."""
    if pair.informative:
        return None
    reason = pair.uninformative_reason or "unknown reason"
    target = pair.expect_pick if pair.expect_pick is not None else pair.expect_avoid
    if reason == "base-picks-expect-3-of-3" and target is not None:
        return (
            f"I found {pair.pair_id} uninformative: its base arm already "
            f"picked {target} 3 of 3 before the change, so it can't show a move."
        )
    if reason == "base-never-picks-avoid" and target is not None:
        return (
            f"I found {pair.pair_id} uninformative: its base arm never picked "
            f"{target} in its 3 base draws, so avoiding it can't show a move."
        )
    if reason == "base-fewer-than-2-real-picks":
        return (
            f"I found {pair.pair_id} uninformative: its base arm has fewer "
            "than 2 real picks, so it can't show a move."
        )
    return f"I found {pair.pair_id} uninformative ({reason})."


def _contrast_detail(pair: PairScore) -> str:
    """Per-pick counts for a directional pair, read from the pair's target."""
    target = pair.expect_pick if pair.expect_pick is not None else pair.expect_avoid
    base_hits = sum(1 for p in pair.base.picks if p == target)
    pert_hits = sum(1 for p in pair.perturbed.picks if p == target)
    return f"{target} base {base_hits}/3, perturbed {pert_hits}/3"


def _matching_detail(pair: PairScore) -> str:
    """Perturbed picks matching a most-picked commitment of the base arm."""
    matching = sum(1 for p in pair.perturbed.picks if p in pair.base.most)
    return f"perturbed picks matching a base most-picked commitment: {matching}/3"


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


def tenth_departure(info: dict[str, Any], score: Score) -> str:
    """Tenth departure: old gate line only for rows without the retry field."""
    three = int(info.get("three_layer_rows", 0))
    if "three_layer_rows" not in info and "two_layer_rows" not in info:
        three = 0
    if three == 0:
        gate_prefix = str(info.get("gate_hash", ""))[:12]
        if score.timeout_attempts == 0:
            timed = f"none of its {score.total_attempts} calls timed out"
        else:
            timed = (
                f"{score.timeout_attempts} of its {score.total_attempts} "
                "calls timed out"
            )
        return (
            f"- R3's first stored run, on gate {gate_prefix}, predates "
            f"Ticket 13b, so its calls ran without the stalled-call retry, "
            f"and {timed}."
        )
    if score.timeout_attempts == 0:
        timed = f"none of its {score.total_attempts} calls timed out"
    else:
        timed = (
            f"{score.timeout_attempts} of its {score.total_attempts} calls timed out"
        )
    return (
        "- I leave the stalled-call retry without a deadline, like the local "
        f"one, and {timed}."
    )


def render_r3(full: R3Score, info: dict[str, Any]) -> str:
    """Render the full receipt text; the doc writer stores it byte-identical."""
    score = full.rerun
    lines = [
        "# R3 steering",
        "",
        "## Result",
        "",
        f'registered prediction: "{PREDICTION_QUOTE}"',
        "",
        (
            f"directional: {score.verdict_directional}; "
            f"invariance: {score.verdict_invariance}; "
            f"combined: {score.verdict_combined}"
        ),
        "",
    ]
    if score.directional_informative == 0:
        lines.append("- directional: not evaluable (0 informative pairs)")
    else:
        low, high = wilson(score.directional_passes, score.directional_informative)
        lines.append(
            f"- directional: {score.directional_passes}/{score.directional_informative} "
            "passes over informative pairs "
            f"(Wilson 95% {low:.2f} to {high:.2f}; this interval describes "
            "these fixed pairs only and generalizes nowhere); "
            f"informative {score.directional_informative}/{score.directional_total} "
            f"of {score.directional_total} directional pairs"
        )
    if score.directional_uninformative:
        lines.append(
            "- uninformative: "
            + ", ".join(
                f"{pair_id} ({reason})"
                for pair_id, reason in sorted(score.directional_uninformative.items())
            )
        )
    else:
        lines.append("- uninformative: none")
    lines.append(
        f"- invariance: {score.invariance_passes}/{score.invariance_total} passes "
        f"({_fmt_interval(score.invariance_passes, score.invariance_total)}); "
        f"pairs failing on an arm with no picks: {score.invariance_no_pick_pairs}"
    )
    lines += [
        "",
        "### Identity",
        "",
        f"- gate commit {info['gate_commit']}, gate hash {info['gate_hash']}",
        f"- prompt sha256 {info['prompt_sha256']}, pairs sha256 {info['pairs_sha256']}",
        closure_line(info),
        f"- tree commits in rows: {', '.join(info['tree_commits'])}",
        f"- model {info['model']}, effort {info['effort']}",
        f"- transports: {', '.join(info['transports'])}",
        f"- muse versions: {', '.join(info['muse_versions'])}",
        f"- rules-file values: {', '.join(str(v) for v in info['rules_values'])}",
        (
            f"- generation: IKIGAI_R3_LIVE=1 python -m evals.r3 "
            f"--model {info['model']} --effort {info['effort']} --repeats 3"
        ),
        "",
        "## Method",
        "",
        (
            "I call Ticket 11's propose once per pair, arm and repeat "
            + client_stack_sentence(info)
            + ". I pass an empty policy block and no parent, "
            "so each draft stands on its scenario alone. Store-derived literals "
            "are empty by construction and I pass private terms empty and "
            "available, so the private-term check is not exercised by these "
            "synthetic rows. I8 reaches propose directly with its UTC-written "
            "slot, which the product would refuse, so it tests how the model "
            "reads the hour string and nothing else. Fallback and noop count "
            "as no pick and unavailable repeats re-run to a bound of 3 "
            "under my reading of the registered fallback and noop rule, "
            "which is: a repeat whose first attempt got no answer was never "
            "drawn, and the first drawn execution stands; the literal "
            "first-execution reading prints beside the registered one."
        ),
        "",
        "Departures from run_slot, all ten:",
        "",
        "- I pass an empty policy block; the product passes the learner's block.",
        (
            "- I attach no parent briefing or metrics, so there is no since_last; "
            "the product attaches the latest delivered proposal."
        ),
        (
            "- I set as_of and cycle_as_of to the slot with cycle_id "
            "r3-synthetic, so there is no stored cycle and the staleness check "
            "can never fire."
        ),
        (
            "- I pass an empty offered map, so a fallback becomes the lowest "
            "commitment id; fallbacks score as no pick either way, and I record "
            "the fallback id."
        ),
        "- I pass no busy intervals; the synthetic world has no calendar.",
        (
            "- I pass empty private terms marked available and never read the "
            "hidden-criteria path, so the private-term check is simply not "
            "exercised by these rows."
        ),
        (
            "- I leave the local retry without a deadline, so both retries always "
            "fit; a started repeat always finishes."
        ),
        (
            "- I use no deadline wrapper and record nothing in the product "
            "database; the JSONL file is the record."
        ),
        (
            "- I8's UTC slot reaches propose directly although the product would "
            "refuse a slot written in UTC, so it tests the model's reading of "
            "the hour string, not a path the product takes."
        ),
        tenth_departure(info, score),
        "",
        "## Directional pairs",
        "",
    ]
    pick_group = [
        p
        for p in score.pairs.values()
        if p.kind == "directional" and p.informative and p.expect_pick is not None
    ]
    avoid_group = [
        p
        for p in score.pairs.values()
        if p.kind == "directional" and p.informative and p.expect_avoid is not None
    ]
    for label, group in (("pick-pairs", pick_group), ("avoid-pairs", avoid_group)):
        passed = sum(1 for p in group if p.passed)
        if group:
            lines.append(
                f"{label}: {passed}/{len(group)} ({_fmt_interval(passed, len(group))})"
            )
        else:
            lines.append(f"{label}: not evaluable (0 informative)")
    lines += ["", "## Per-profile rates", ""]
    for profile in sorted({p.profile for p in score.pairs.values()}):
        num, den = profile_rate(score, profile)
        if den:
            lines.append(
                f"- {profile}: {num}/{den} "
                f"({_fmt_interval(num, den)}; informative directional passes plus "
                f"invariance passes over informative directional pairs plus all "
                f"invariance pairs)"
            )
        else:
            lines.append(f"- {profile}: not evaluable (0 pairs)")
    lines += ["", "## All six picks per pair", ""]
    lines.append(
        "| pair | base 1-3 | perturbed 1-3 | most-picked base | "
        "most-picked perturbed | verdict |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for pair in score.pairs.values():
        lines.append(
            f"| {pair.pair_id} | {', '.join(pair.base.labels)} "
            f"| {', '.join(pair.perturbed.labels)} "
            f"| {_most_cell(pair.base.most)} | {_most_cell(pair.perturbed.most)} "
            f"| {_verdict_label(pair)} |"
        )
    stability = stability_summary(score)
    stable, eligible = stability["overall"]
    lines += ["", "## Repeat stability", ""]
    by_kind = ", ".join(
        f"{kind} {s}/{e}" for kind, (s, e) in sorted(stability["by_kind"].items())
    )
    lines.append(
        f"repeat stability: {stable}/{eligible} arms stable"
        + (f" ({by_kind})" if by_kind else "")
        + f"; {stability['excluded']} arms with fewer than 2 real picks excluded"
    )
    lines += ["", "## Unavailable and exhausted", ""]
    if score.unavailable_by_reason:
        reasons = ", ".join(
            f"{reason} ×{count}"
            for reason, count in sorted(score.unavailable_by_reason.items())
        )
        lines.append(f"- unavailable executions by reason: {reasons}")
    else:
        lines.append("- unavailable executions by reason: none")
    lines.append(f"- exhausted slots: {score.exhausted_slots}")
    lines.append(
        f"- slots with more than one drawn execution: {score.multi_drawn_slots}"
    )
    lines.append(
        "- My reading of the registered fallback and noop rule: unavailable "
        "repeats re-run to a bound of 3, and the first drawn execution stands."
    )
    if full.literal_applies and full.literal is not None:
        lit = full.literal
        lines += ["", "## Literal reading (first execution stands)", ""]
        lines.append(
            "The reading my registered-rule reading replaced: each slot's first "
            "execution stands, an unavailable first execution counting as no pick."
        )
        lines.append(
            f"directional: {lit.directional_passes}/{lit.directional_informative} "
            f"({lit.verdict_directional}); invariance: "
            f"{lit.invariance_passes}/{lit.invariance_total} ({lit.verdict_invariance}); "
            f"combined: {lit.verdict_combined}"
        )
    lines += ["", "## Missing repeats", ""]
    if score.missing_slots:
        missing_ids = sorted(
            pair_id for pair_id, pair in score.pairs.items() if pair.missing
        )
        lines.append(
            f"missing repeat slots: {score.missing_slots} "
            f"(pairs {', '.join(missing_ids)})"
        )
    else:
        lines.append("missing repeat slots: none")
    lines += ["", "## Base spread (new, not registered; decides nothing)", ""]
    no_picks = base_no_picks(score)
    for profile in sorted(base_spread(score)):
        counts = base_spread(score)[profile]
        total = sum(counts.values())
        top = max(counts.values()) if counts else 0
        cells = (
            ", ".join(f"{pick} {count}" for pick, count in sorted(counts.items()))
            or "—"
        )
        lines.append(
            f"{profile}: {cells} (modal share {top}/{total} of real picks; "
            f"no picks {no_picks.get(profile, 0)})"
        )
    if "D6" in score.pairs and "I1" in score.pairs:
        lines += [
            "",
            (
                "## Registered contrast D6/I1 (same perturbation, both goals; "
                "PREREG defines no out-of-6 score)"
            ),
            "",
            "| pair | base 1-3 | perturbed 1-3 | detail | verdict |",
            "| --- | --- | --- | --- | --- |",
        ]
        d6 = score.pairs["D6"]
        i1 = score.pairs["I1"]
        lines.append(
            f"| D6 | {', '.join(d6.base.labels)} "
            f"| {', '.join(d6.perturbed.labels)} "
            "| d-screens base "
            f"{sum(1 for p in d6.base.picks if p == 'd-screens')}/3, perturbed "
            f"{sum(1 for p in d6.perturbed.picks if p == 'd-screens')}/3 "
            f"| {_verdict_label(d6)} |"
        )
        matching = sum(1 for p in i1.perturbed.picks if p in i1.base.most)
        lines.append(
            f"| I1 | {', '.join(i1.base.labels)} "
            f"| {', '.join(i1.perturbed.labels)} "
            "| perturbed picks matching a base most-picked commitment: "
            f"{matching}/3 | {_verdict_label(i1)} |"
        )
        for contrast_pair in (d6, i1):
            sentence = _uninformative_sentence(contrast_pair)
            if sentence is not None:
                lines += ["", sentence]
    if "D1" in score.pairs and "I2" in score.pairs:
        lines += [
            "",
            "## Also registered: D1 and I2 (shown after I saw the results)",
            "",
            "| pair | base 1-3 | perturbed 1-3 | detail | verdict |",
            "| --- | --- | --- | --- | --- |",
        ]
        d1 = score.pairs["D1"]
        i2 = score.pairs["I2"]
        lines.append(
            f"| D1 | {', '.join(d1.base.labels)} "
            f"| {', '.join(d1.perturbed.labels)} "
            f"| {_contrast_detail(d1)} | {_verdict_label(d1)} |"
        )
        lines.append(
            f"| I2 | {', '.join(i2.base.labels)} "
            f"| {', '.join(i2.perturbed.labels)} "
            f"| {_matching_detail(i2)} | {_verdict_label(i2)} |"
        )
        for contrast_pair in (d1, i2):
            sentence = _uninformative_sentence(contrast_pair)
            if sentence is not None:
                lines += ["", sentence]
    lines += ["", "## Cost spent", ""]
    lines.append(
        f"- cost spent: {info['calls']} calls including retries, "
        f"{info['local_starts']} retried local starts, "
        f"{info['prompt_tokens']} prompt + {info['completion_tokens']} completion "
        f"tokens, wall {info['wall_start']} to {info['wall_end']}"
    )
    lines.append(
        "- Wilson 95% intervals describe these fixed pairs only and do not "
        "generalize past them."
    )
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


def render_r3_history_section(
    full: R3Score, info: dict[str, Any], *, first: bool
) -> str:
    """One older run's section: identity lines, Result lines, six-picks table.

    Every number is scored from that run's own rows via ``full``/``info``.
    """
    score = full.rerun
    lines = [
        f"## {history_heading(info, first=first)}",
        "",
        HISTORY_SENTENCE,
        "",
        "### Result (for the record)",
        "",
        f'registered prediction: "{PREDICTION_QUOTE}"',
        "",
        (
            f"directional: {score.verdict_directional}; "
            f"invariance: {score.verdict_invariance}; "
            f"combined: {score.verdict_combined}"
        ),
        "",
    ]
    if score.directional_informative == 0:
        lines.append("- directional: not evaluable (0 informative pairs)")
    else:
        low, high = wilson(score.directional_passes, score.directional_informative)
        lines.append(
            f"- directional: {score.directional_passes}/{score.directional_informative} "
            "passes over informative pairs "
            f"(Wilson 95% {low:.2f} to {high:.2f}); "
            f"informative {score.directional_informative}/{score.directional_total} "
            f"of {score.directional_total} directional pairs"
        )
    if score.directional_uninformative:
        lines.append(
            "- uninformative: "
            + ", ".join(
                f"{pair_id} ({reason})"
                for pair_id, reason in sorted(score.directional_uninformative.items())
            )
        )
    else:
        lines.append("- uninformative: none")
    lines.append(
        f"- invariance: {score.invariance_passes}/{score.invariance_total} passes "
        f"({_fmt_interval(score.invariance_passes, score.invariance_total)})"
    )
    lines += [
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
        "### All six picks per pair (for the record)",
        "",
        (
            "| pair | base 1-3 | perturbed 1-3 | most-picked base | "
            "most-picked perturbed | verdict |"
        ),
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for pair in score.pairs.values():
        lines.append(
            f"| {pair.pair_id} | {', '.join(pair.base.labels)} "
            f"| {', '.join(pair.perturbed.labels)} "
            f"| {_most_cell(pair.base.most)} | {_most_cell(pair.perturbed.most)} "
            f"| {_verdict_label(pair)} |"
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
                "# R3 steering",
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
                    "directional: not evaluable; invariance: not evaluable; "
                    "combined: not evaluable"
                ),
                "",
            ]
        )
        + "\n"
    )
