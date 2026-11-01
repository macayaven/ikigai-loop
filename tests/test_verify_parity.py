"""Ticket 17a: anti-drift parity between verify_claims and evaluate_briefing.

Only the pinned expressible subset is claimed equal. Every other case is
named with its one-line reason, and the pinned lists fail the test when a
new case lands in evals/briefing_cases.py until someone classifies it.
"""

from __future__ import annotations

from collections import Counter

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.gate import ADVICE_WORDS, evaluate_briefing
from framework.briefing.labels import metric_label_binding
from framework.verify import verify_claims

# L1B_PERIOD_WORD_MISSING only exists inside this test: the translator puts
# the period word in the labels word list, so the gate code maps here.
PERIOD_ALIAS = {"L1B_PERIOD_WORD_MISSING": "L1B_METRIC_LABEL_MISSING"}

SHARED_CODES = frozenset(
    {
        "L1_SECRET",
        "L1_PII",
        "L1_ADVICE",
        "L1_PRIVATE_TERM",
        "L1B_CLAIM_WITHOUT_EVIDENCE",
        "L1B_UNKNOWN_FACT",
        "L1B_UNKNOWN_METRIC",
        "L1B_METRIC_VALUE_MISMATCH",
        "L1B_NUMBER_WITHOUT_METRIC_REF",
        "L1B_METRIC_LABEL_MISSING",
        "L1B_TOO_MANY_METRICS",
        "L1B_DIRECTION_MISMATCH",
        "L1B_PERIOD_WORD_MISSING",
    }
)

PERIOD_WORDS = ("earlier", "prior", "last")
PERIOD_ORDER = {"earlier": 0, "prior": 1, "last": 2}

EXPRESSIBLE_MUTANTS = (
    "M4-pii-email",
    "M5-secret-token",
    "M6-private-term",
    "M10-unknown-fact",
    "M11-number-without-ref",
    "M12-metric-mismatch",
    "M14-claim-without-evidence",
    "M21-swapped-metric-label",
    "M22-wrong-period-word",
    "M23-reversed-direction",
    "M28-advice-should",
    "M29-advice-must",
    "M30-advice-medication",
    "M31-spelled-number-without-ref",
    "M32-date-number-without-ref",
    "M33-too-many-metrics",
    "M36-direction-single-ref",
    "M37-direction-mixed-changes",
)

EXCLUDED_MUTANTS = (
    ("M1-unknown-section", "unknown section, L0"),
    ("M2-missing-since-last", "parent/since_last"),
    ("M3-action-count", "action count, L0"),
    ("M7-raw-value", "raw ref, L1_RAW_VALUE"),
    ("M8-slot-outside-hours", "slot hours, L1"),
    ("M9-action-in-busy", "action window, L1"),
    ("M13-delta-mismatch", "parent delta"),
    ("M15-action-before-slot", "action window, L1"),
    ("M16-empty-overall-state", "empty section, L0"),
    ("M17-child-without-parent-id", "parent mismatch"),
    ("M18-parent-profile-mismatch", "parent mismatch"),
    ("M19-parent-subject-mismatch", "parent mismatch"),
    ("M20-parent-slot-not-before", "parent mismatch"),
    ("M24-reversed-delta-direction", "parent/since_last delta direction"),
    ("M25-action-not-committed", "action commitment, L1"),
    ("M26-action-cross-profile", "action commitment, L1"),
    ("M27-action-text-mismatch", "action text, L1"),
    ("M34-unknown-metric-family", "generic id has no public counterpart"),
    ("M35-commitments-unavailable", "commitments unavailable, L1"),
    ("M38-uncited-period-word", "reserved period vocabulary is product-only"),
)

EXPRESSIBLE_KNOWN_GOOD = (
    "G1-builder-first",
    "G3-disconnect-first",
    "G5-slot-at-open",
    "G6-evening-boundary-touch",
    "G7-one-action",
    "G8-three-actions",
    "G9-datetime-prose",
    "G10-two-facts-merged-free",
    "G11-plain-english",
    "G12-rounded-absolute-backing",
    "G13-one-period-ref",
    "G14-two-period-refs",
    "G15-three-period-refs",
    "G16-labelled-no-direction",
    "G17-model-wording-screen",
    "G18-model-wording-pushes",
    "G19-model-wording-segment",
)

EXCLUDED_KNOWN_GOOD = (
    ("G2-builder-with-parent", "parent and since_last the public shape cannot say"),
    (
        "G4-disconnect-parent-pct-dec",
        "parent and since_last the public shape cannot say",
    ),
    (
        "G20-negative-delta-absolute",
        "parent and since_last the public shape cannot say",
    ),
)


def _claim_text_names_period_word(text: str) -> set[str]:
    from framework.briefing.gate import collapse_text, contains_token

    collapsed = collapse_text(text)
    return {word for word in PERIOD_WORDS if contains_token(collapsed, word)}


def _is_expressible(case: Case) -> bool:
    briefing = case.briefing
    if briefing.get("parent_briefing_id") is not None:
        return False
    if any(s.get("type") == "since_last" for s in briefing.get("sections", [])):
        return False
    if not case.context.private_terms_available:
        return False
    if not case.context.commitments_available:
        return False
    if any(code not in SHARED_CODES for code in case.expected):
        return False
    for section in briefing.get("sections", []):
        for claim in section.get("claims", []):
            for ref in claim.get("metric_refs", []):
                metric_id = ref["metric_id"]
                if (
                    metric_id.startswith("raw.")
                    or metric_id in case.context.raw_metric_ids
                ):
                    return False
                if metric_label_binding(metric_id) is None:
                    return False
            cited_periods = [
                b.period
                for ref in claim.get("metric_refs", [])
                if (b := metric_label_binding(ref["metric_id"])) is not None
            ]
            if _claim_text_names_period_word(claim["text"]) and not any(
                p is not None for p in cited_periods
            ):
                # Names a reserved period word while citing no period
                # binding at all (the M38 shape): the input shape cannot
                # say that rule.
                return False
    return True


def _translate(case: Case) -> dict[str, object]:
    from framework.briefing.gate import collapse_text, contains_token

    context = case.context
    claims: list[dict[str, object]] = []
    for section in case.briefing.get("sections", []):
        for claim in section.get("claims", []):
            claims.append(
                {
                    "id": claim["id"],
                    "text": claim["text"],
                    "fact_ids": list(claim.get("fact_ids", [])),
                    "metric_refs": [
                        {"metric_id": r["metric_id"], "value": r["value"]}
                        for r in claim.get("metric_refs", [])
                    ],
                }
            )
    facts = {fid: fact.statement for fid, fact in context.facts.items()}
    metrics = dict(context.metrics.values)
    labels: dict[str, list[str]] = {}
    stems: dict[str, str] = {}
    for section in case.briefing.get("sections", []):
        for claim in section.get("claims", []):
            collapsed = collapse_text(claim["text"])
            for ref in claim.get("metric_refs", []):
                binding = metric_label_binding(ref["metric_id"])
                assert binding is not None
                words = sorted(binding.labels)
                label = next(
                    (w for w in words if contains_token(collapsed, w.lower())),
                    words[0],
                )
                entry = [label]
                if binding.period is not None:
                    entry.append(binding.period)
                labels[ref["metric_id"]] = entry
                if binding.period is not None:
                    stem = ref["metric_id"].split(f".{binding.period}.", 1)[1]
                    if stem not in stems:
                        stems[stem] = label
                    for period in PERIOD_WORDS:
                        # Members nobody cited get the cited id's label;
                        # a cited member's own entry above always wins.
                        labels.setdefault(
                            f"period.{period}.{stem}", [stems[stem], period]
                        )
    # The whole family series over all three periods, in the gate's
    # period order. metric_refs order is never read. Series and labels
    # may name ids absent from metrics.
    order = [[f"period.{period}.{stem}" for period in PERIOD_WORDS] for stem in stems]
    payload: dict[str, object] = {
        "claims": claims,
        "facts": facts,
        "metrics": metrics,
        "labels": labels,
        "deny_terms": list(context.private_terms),
        "advice_words": list(ADVICE_WORDS),
    }
    if order:
        payload["order"] = order
    return payload


def test_pinned_lists_match_the_predicate() -> None:
    assert len(MUTANTS) == 38
    assert len(KNOWN_GOOD) == 20
    computed_mutants = sorted(c.name for c in MUTANTS if _is_expressible(c))
    assert computed_mutants == sorted(EXPRESSIBLE_MUTANTS)
    assert len(EXPRESSIBLE_MUTANTS) == 18
    assert sorted(n for n, _ in EXCLUDED_MUTANTS) == sorted(
        c.name for c in MUTANTS if not _is_expressible(c)
    )
    assert len(EXCLUDED_MUTANTS) == 20
    computed_good = sorted(c.name for c in KNOWN_GOOD if _is_expressible(c))
    assert computed_good == sorted(EXPRESSIBLE_KNOWN_GOOD)
    assert len(EXPRESSIBLE_KNOWN_GOOD) == 17
    assert sorted(n for n, _ in EXCLUDED_KNOWN_GOOD) == sorted(
        c.name for c in KNOWN_GOOD if not _is_expressible(c)
    )
    assert len(EXCLUDED_KNOWN_GOOD) == 3


def _gate_codes(case: Case) -> tuple[Counter[str], bool]:
    result = evaluate_briefing(case.briefing, case.context)
    # The gate can emit L1B_METRIC_LABEL_MISSING and
    # L1B_PERIOD_WORD_MISSING on one claim while verify_claims reports
    # one finding per code per claim, so dedupe the gate's aliased codes
    # per location before counting.
    seen: set[tuple[str, str]] = set()
    codes: list[str] = []
    for violation in result.violations:
        key = (PERIOD_ALIAS.get(violation.code, violation.code), violation.location)
        if key not in seen:
            seen.add(key)
            codes.append(key[0])
    return Counter(codes), result.passed


def _public_codes(case: Case) -> tuple[Counter[str], bool]:
    report = verify_claims(_translate(case))
    return Counter(v.code for v in report.violations), report.passed


def _public_codes_reversed(case: Case) -> tuple[Counter[str], bool]:
    payload = _translate(case)
    claims = payload["claims"]
    assert isinstance(claims, list)
    for claim in claims:
        assert isinstance(claim, dict)
        refs = claim.get("metric_refs", [])
        assert isinstance(refs, list)
        refs.reverse()
    report = verify_claims(payload)
    return Counter(v.code for v in report.violations), report.passed


def test_expressible_cases_match_gate_verdict() -> None:
    failures: list[str] = []
    for case in list(MUTANTS) + list(KNOWN_GOOD):
        if case.name not in set(EXPRESSIBLE_MUTANTS) | set(EXPRESSIBLE_KNOWN_GOOD):
            continue
        gate_counter, gate_passed = _gate_codes(case)
        public_counter, public_passed = _public_codes(case)
        if gate_counter != public_counter or gate_passed != public_passed:
            failures.append(
                f"{case.name}: gate={sorted(gate_counter.items())} "
                f"public={sorted(public_counter.items())}"
            )
    assert failures == []


def test_reversed_refs_give_same_verdict() -> None:
    failures: list[str] = []
    for case in list(MUTANTS) + list(KNOWN_GOOD):
        if case.name not in set(EXPRESSIBLE_MUTANTS) | set(EXPRESSIBLE_KNOWN_GOOD):
            continue
        plain_counter, plain_passed = _public_codes(case)
        rev_counter, rev_passed = _public_codes_reversed(case)
        if plain_counter != rev_counter or plain_passed != rev_passed:
            failures.append(
                f"{case.name}: plain={sorted(plain_counter.items())} "
                f"reversed={sorted(rev_counter.items())}"
            )
    assert failures == []


def test_uncited_period_word_rejected_both_paths() -> None:
    from evals.briefing_cases import _section, base_case
    from framework.briefing.context import MetricSnapshot

    case = base_case("builder")
    working = _section(case.briefing, "working")
    working["claims"].append(
        {
            "id": "claim-push-extra",
            "text": "Pushes reached 5 in last and prior",
            "fact_ids": [],
            "metric_refs": [{"metric_id": "period.last.pushes", "value": 5}],
        }
    )
    context = case.context.model_copy(
        update={"metrics": MetricSnapshot(values={"period.last.pushes": 5.0})}
    )
    gate_result = evaluate_briefing(case.briefing, context)
    assert gate_result.passed is False
    assert (
        "sections[working].claims[claim-push-extra]",
        "L1B_PERIOD_WORD_MISSING",
    ) in {(v.location, v.code) for v in gate_result.violations}

    public_report = verify_claims(_translate(case))
    assert public_report.passed is False
    assert (
        "claim-push-extra",
        "L1B_METRIC_LABEL_MISSING",
        "claim names another metric in its series without citing it",
    ) in {(v.claim_id, v.code, v.message) for v in public_report.violations}
