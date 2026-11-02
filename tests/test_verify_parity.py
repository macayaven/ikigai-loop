"""Ticket 17a: anti-drift parity between verify_claims and evaluate_briefing.

Only the pinned expressible subset is claimed equal. Every other case is
named with its one-line reason, and the pinned lists fail the test when a
new case lands in evals/briefing_cases.py until someone classifies it.
"""

from __future__ import annotations

from collections import Counter

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.gate import (
    ADVICE_WORDS,
    CLAIM_ADVICE_PHRASES,
    collapse_text,
    contains_token,
    evaluate_briefing,
    word_list_hit,
)
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
    "M41-growth-synonym",
    "M42-exceeded-synonym",
    "M56-rounded-integer",
    "M63-fullwidth-term",
    "M64-spaced-term",
    "M67-deontic-phrase",
    "M69-rhetorical-question",
    "M71-crash-decimals",
    "M85-R20-hyphen-direction",
    "M88-R23-punctuated-term",
    "M91-R26-suggestion-phrase",
    "M92-R27-commitment-object",
    "M97-R35-hour-is-for",
    "M100-R38-scale-word",
    "M101-R39-curly-term",
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
    ("M39-negated-direction", "negation is claim-path-only"),
    ("M40-negated-zero", "negation is claim-path-only"),
    ("M43-spanish-direction", "claim language is claim-path-only"),
    ("M44-doubled", "multiplier words are claim-path-only"),
    ("M45-half", "fractions are claim-path-only"),
    ("M46-vulgar-fraction", "vulgar fractions are claim-path-only"),
    ("M47-tally-marks", "tally marks are claim-path-only"),
    ("M48-roman-numeral", "roman numerals are claim-path-only"),
    ("M49-french-number", "claim language is claim-path-only"),
    ("M50-digit-ordinal", "ordinals are a stated verify limit"),
    ("M51-clock-duration", "clock durations are claim-path-only"),
    ("M52-invalid-clock", "comparison vocabulary is claim-path-only"),
    ("M53-tenfold", "multiplier words are claim-path-only"),
    ("M54-a-couple", "vague counts are claim-path-only"),
    ("M55-one-oh", "spoken number forms are claim-path-only"),
    ("M57-wrong-unit", "units are a stated verify limit"),
    ("M58-period-compound", "period compounds are claim-path-only"),
    ("M59-conflicting-category", "conflicting categories are claim-path-only"),
    ("M60-rank-ordinal", "rank words are claim-path-only"),
    ("M61-rate-word", "rate words are claim-path-only"),
    ("M62-hidden-char-term", "unsafe text is claim-path-only"),
    ("M65-confusable-term", "claim language is claim-path-only"),
    ("M66-punctuated-literal", "raw literals are claim-path-only"),
    ("M68-bare-imperative", "bare imperatives are claim-path-only"),
    ("M70-french-imperative", "claim language is claim-path-only"),
    ("M72-swapped-periods", "value-period binding is claim-path-only"),
    ("M73-N01-value-beside-wrong-period", "value-period binding is claim-path-only"),
    (
        "M74-R09-spelled-beside-wrong-period",
        "value-period binding is claim-path-only",
    ),
    ("M75-N07-wrong-duration-word", "units are a stated verify limit"),
    ("M76-R11-magnitude-word", "units are a stated verify limit"),
    ("M77-R12-glued-letter", "glued letters are claim-path-only"),
    ("M78-R13-trailing-qualifier", "trailing qualifiers are claim-path-only"),
    ("M79-R14-single", "vague counts are claim-path-only"),
    ("M80-R15-lower-roman", "roman numerals are claim-path-only"),
    ("M81-R16-share-word", "rank words are claim-path-only"),
    ("M82-R17-universal-label", "universal words are claim-path-only"),
    ("M83-R18-negated-one-word", "negation is claim-path-only"),
    ("M84-R19-fact-both-directions", "fact-only period word is product-only"),
    ("M86-R21-period-other-sense", "period words in another sense are claim-path-only"),
    ("M87-R22-spaced-negation", "unsafe text is claim-path-only"),
    ("M89-R24-misspelled-literal", "raw literals are claim-path-only"),
    ("M90-R25-opener-imperative", "bare imperatives are claim-path-only"),
    ("M93-R28-strong-verb", "bare imperatives are claim-path-only"),
    ("M94-R32-exactness-limit", "integers past 2^53 are claim-path-only"),
    ("M95-R33-and-imperative", "bare imperatives are claim-path-only"),
    ("M96-R34-dash-imperative", "bare imperatives are claim-path-only"),
    ("M98-R36-named-not-cited", "uncited metrics are claim-path-only"),
    ("M99-R37-time-word-periodless", "time-scope words are claim-path-only"),
    ("M102-N12-spelled-ordinal", "ordinals are a stated verify limit"),
    ("M103-N14-tally", "tally marks are claim-path-only"),
    ("M104-N08-slash-fraction", "fractions are claim-path-only"),
    ("M105-N15-range-one-period", "range words are claim-path-only"),
    ("M106-N05-wrong-change", "stated changes are claim-path-only"),
    ("M107-R41-periods-wrong-way", "time-order than-comparisons are claim-path-only"),
    ("M108-N04-joined-label", "joined labels are claim-path-only"),
    ("M109-N06-percent-word", "units are a stated verify limit"),
    ("M110-R52-digit-ordinal-noun", "ordinals are a stated verify limit"),
    ("M111-N22-lookalike-I", "term variants are claim-path-only"),
    ("M112-N23-halves-swapped", "term variants are claim-path-only"),
    ("M113-N24-phonetic-term", "unsafe text is claim-path-only"),
    ("M114-N25-stretched-literal", "raw literals are claim-path-only"),
    ("M115-N26-dutch", "claim language is claim-path-only"),
    ("M116-N28-question-no-mark", "questions are claim-path-only"),
    ("M117-R44-link", "unsafe text is claim-path-only"),
    ("M118-R45-no-letters-digits", "unsafe text is claim-path-only"),
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
    "G21-n1-stood",
    "G22-n2-went-down",
    "G23-n3-value-first",
    "G24-n4-busy-over",
    "G25-n5-stated-zero",
    "G27-n7-spent",
    "G30-n10-about",
    "G31-n11-moved",
    "G32-n12-totaled",
    "G33-n13-clock-the",
    "G34-n14-period-list",
    "G35-n15-unit-pairs",
    "G36-n16-roman-free",
    "G37-n17-up-to",
    "G40-n20-backticks",
    "G41-n21-you-spent",
    "G44-n24-github-pushes",
    "G45-n25-cancelled-zero",
    "G47-n27-slashed-category",
    "G49-R04-whole-over-noise",
    "G50-R05-held-count",
    "G51-R06-phrasal-particle",
    "G52-R07-ahead",
    "G53-R31-short-word-value",
    "G54-R42-hyphen-part-alone",
    "G55-R40-later-period-first",
    "G56-R43-cancel-comparison",
    "G57-range-two-periods",
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
    ("G26-n6-absent", "fact-only period word is product-only"),
    ("G28-n8-shipped", "fact-only period word is product-only"),
    ("G29-n9-review-notes", "fact-only period word is product-only"),
    ("G38-n18-use-of", "fact-only period word is product-only"),
    ("G39-n19-focus-dropped", "fact-only period word is product-only"),
    ("G42-n22-godel", "fact-only period word is product-only"),
    ("G43-n23-due", "fact-only period word is product-only"),
    ("G46-n26-glimmer-fact", "fact-only period word is product-only"),
    ("G48-r2-name-with-number", "fact-only period word is product-only"),
)


def _claim_text_names_period_word(text: str) -> set[str]:
    from framework.briefing.gate import collapse_text, contains_token

    collapsed = collapse_text(text)
    return {word for word in PERIOD_WORDS if contains_token(collapsed, word)}


def _term_variant_hit(text: str, term: str) -> bool:
    """Whether ``text`` holds an li-fold or rotation of ``term``, not exact.

    The claim path reads ``l``/``i`` as one letter and halves-swapped
    rotations of spaceless terms (the M111/M112 shapes); the public
    subset leaves those arms out, so such a case is not expressible.
    """
    import re

    from framework.briefing.normalize import normalize_text

    target = "".join(c for c in normalize_text(term).casefold() if c.isalnum())
    if len(target) < 6:
        return False
    folded = target.replace("l", "i")
    for token in re.findall(r"\w+", normalize_text(text).casefold()):
        token = "".join(c for c in token if c.isalnum())
        if len(token) != len(target) or token == target:
            continue
        if token.replace("l", "i") == folded:
            return True
        if any(
            target[index:] + target[:index] == token for index in range(1, len(target))
        ):
            return True
    return False


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
    if "L1_ADVICE" in case.expected:
        public_advice = list(ADVICE_WORDS) + list(CLAIM_ADVICE_PHRASES)
        texts = [
            claim["text"]
            for section in briefing.get("sections", [])
            for claim in section.get("claims", [])
        ]
        if not any(word_list_hit(text, public_advice) for text in texts):
            # The gate's imperative rule fires with no listed advice word
            # (the M68 shape): the public subset leaves that rule out.
            return False
    for section in briefing.get("sections", []):
        for claim in section.get("claims", []):
            collapsed = collapse_text(claim["text"])
            if "to-last" in collapsed or "penultimate" in collapsed:
                # The gate's period-phrase rule reads compounds like
                # second-to-last (the M58 shape): the public subset
                # leaves that rule out.
                return False
            if "at last" in collapsed:
                # A period word in another sense (the M86 shape): the
                # public subset leaves that reading out.
                return False
            if contains_token(collapsed, "than"):
                import re

                tokens = re.findall(r"[a-z0-9_]+", collapsed)
                if (
                    "prior" in tokens
                    and "last" in tokens
                    and tokens.index("prior") < tokens.index("last")
                ):
                    # A than-comparison naming prior first (the M107
                    # shape): the public subset reads it in time order.
                    return False
            if "L1_PRIVATE_TERM" in case.expected and any(
                _term_variant_hit(claim["text"], term)
                for term in case.context.private_terms
            ):
                # An li-fold or rotation of a private term (the
                # M111/M112 shapes): the public subset leaves those
                # arms out.
                return False
            for ref in claim.get("metric_refs", []):
                metric_id = ref["metric_id"]
                if (
                    metric_id.startswith("raw.")
                    or metric_id in case.context.raw_metric_ids
                ):
                    return False
                if metric_label_binding(metric_id) is None:
                    return False
                value = ref["value"]
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and abs(value) >= 2**53
                ):
                    # Integers past 2^53 (the M94 shape): floats cannot
                    # tell them apart, so the public subset leaves that
                    # rule out.
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
        "advice_words": list(ADVICE_WORDS) + list(CLAIM_ADVICE_PHRASES),
    }
    if order:
        payload["order"] = order
    return payload


def test_pinned_lists_match_the_predicate() -> None:
    assert len(MUTANTS) == 38 + 34 + 46 == 118
    assert len(KNOWN_GOOD) == 20 + 28 + 9 == 57
    computed_mutants = sorted(c.name for c in MUTANTS if _is_expressible(c))
    assert computed_mutants == sorted(EXPRESSIBLE_MUTANTS)
    assert len(EXPRESSIBLE_MUTANTS) == 33
    assert sorted(n for n, _ in EXCLUDED_MUTANTS) == sorted(
        c.name for c in MUTANTS if not _is_expressible(c)
    )
    assert len(EXCLUDED_MUTANTS) == 85
    computed_good = sorted(c.name for c in KNOWN_GOOD if _is_expressible(c))
    assert computed_good == sorted(EXPRESSIBLE_KNOWN_GOOD)
    assert len(EXPRESSIBLE_KNOWN_GOOD) == 45
    assert sorted(n for n, _ in EXCLUDED_KNOWN_GOOD) == sorted(
        c.name for c in KNOWN_GOOD if not _is_expressible(c)
    )
    assert len(EXCLUDED_KNOWN_GOOD) == 12


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
