"""Ticket 023: hardened parity between the gate and check_claims.

Translator gives each cited metric its binding label alone in labels,
its period word in periods, its unit from metric_unit_class in units
and order as today, plus period words for uncited series members.
Gate L1B_PERIOD_WORD_MISSING compares one to one with the new D6 arm.
Pinned lists and counts live here, separate from test_verify_parity.py,
which stays byte-unchanged. Made-up data only; no network, no model.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.gate import (
    ADVICE_WORDS,
    CLAIM_ADVICE_PHRASES,
    collapse_text,
    contains_token,
    evaluate_briefing,
    word_list_hit,
)
from framework.briefing.labels import metric_label_binding, metric_unit_class
from framework.verify.__main__ import main
from framework.verify.hardened import check_claims

PERIOD_WORDS = ("earlier", "prior", "last")
PERIOD_ORDER = {period: index for index, period in enumerate(PERIOD_WORDS)}

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
        "L1B_NEGATED_CLAIM",
        "L1B_UNVERIFIABLE_QUANTITY",
        "L1B_UNIT_MISMATCH",
        "L1B_VALUE_PERIOD_MISMATCH",
    }
)

EXPRESSIBLE_MUTANTS = (
    "M10-unknown-fact",
    "M101-R39-curly-term",
    "M102-N12-spelled-ordinal",
    "M103-N14-tally",
    "M104-N08-slash-fraction",
    "M105-N15-range-one-period",
    "M106-N05-wrong-change",
    "M11-number-without-ref",
    "M110-R52-digit-ordinal-noun",
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
    "M39-negated-direction",
    "M4-pii-email",
    "M40-negated-zero",
    "M41-growth-synonym",
    "M42-exceeded-synonym",
    "M44-doubled",
    "M45-half",
    "M46-vulgar-fraction",
    "M48-roman-numeral",
    "M5-secret-token",
    "M50-digit-ordinal",
    "M51-clock-duration",
    "M53-tenfold",
    "M54-a-couple",
    "M55-one-oh",
    "M56-rounded-integer",
    "M57-wrong-unit",
    "M6-private-term",
    "M60-rank-ordinal",
    "M63-fullwidth-term",
    "M64-spaced-term",
    "M67-deontic-phrase",
    "M69-rhetorical-question",
    "M71-crash-decimals",
    "M72-swapped-periods",
    "M73-N01-value-beside-wrong-period",
    "M74-R09-spelled-beside-wrong-period",
    "M78-R13-trailing-qualifier",
    "M79-R14-single",
    "M80-R15-lower-roman",
    "M81-R16-share-word",
    "M82-R17-universal-label",
    "M85-R20-hyphen-direction",
    "M88-R23-punctuated-term",
    "M91-R26-suggestion-phrase",
    "M92-R27-commitment-object",
    "M97-R35-hour-is-for",
)

EXPRESSIBLE_KNOWN_GOOD = (
    "G1-builder-first",
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
    "G3-disconnect-first",
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
    "G5-slot-at-open",
    "G50-R05-held-count",
    "G51-R06-phrasal-particle",
    "G52-R07-ahead",
    "G53-R31-short-word-value",
    "G54-R42-hyphen-part-alone",
    "G55-R40-later-period-first",
    "G56-R43-cancel-comparison",
    "G57-range-two-periods",
    "G6-evening-boundary-touch",
    "G7-one-action",
    "G8-three-actions",
    "G9-datetime-prose",
)

EXCLUDED_MUTANTS = (
    ("M1-unknown-section", "unknown section, L0"),
    (
        "M100-R38-scale-word",
        "magnitude word on a count metric reads as a unit mismatch here",
    ),
    ("M107-R41-periods-wrong-way", "time-order than-comparisons are claim-path-only"),
    ("M108-N04-joined-label", "joined labels are claim-path-only"),
    (
        "M109-N06-percent-word",
        "period word without a declared period is not carried over",
    ),
    ("M111-N22-lookalike-I", "term variants are claim-path-only"),
    ("M112-N23-halves-swapped", "term variants are claim-path-only"),
    ("M113-N24-phonetic-term", "unsafe text is claim-path-only"),
    ("M114-N25-stretched-literal", "raw literals are claim-path-only"),
    ("M115-N26-dutch", "claim language is claim-path-only"),
    ("M116-N28-question-no-mark", "questions are claim-path-only"),
    ("M117-R44-link", "unsafe text is claim-path-only"),
    ("M118-R45-no-letters-digits", "unsafe text is claim-path-only"),
    (
        "M119-since-last-period-phrase",
        "since_last wording: parent and since_last the public shape cannot say",
    ),
    ("M13-delta-mismatch", "parent delta"),
    ("M15-action-before-slot", "action window, L1"),
    ("M16-empty-overall-state", "empty section, L0"),
    ("M17-child-without-parent-id", "parent mismatch"),
    ("M18-parent-profile-mismatch", "parent mismatch"),
    ("M19-parent-subject-mismatch", "parent mismatch"),
    ("M2-missing-since-last", "parent/since_last"),
    ("M20-parent-slot-not-before", "parent mismatch"),
    ("M24-reversed-delta-direction", "parent/since_last delta direction"),
    ("M25-action-not-committed", "action commitment, L1"),
    ("M26-action-cross-profile", "action commitment, L1"),
    ("M27-action-text-mismatch", "action text, L1"),
    ("M3-action-count", "action count, L0"),
    ("M34-unknown-metric-family", "generic id has no public counterpart"),
    ("M35-commitments-unavailable", "commitments unavailable, L1"),
    ("M38-uncited-period-word", "reserved period vocabulary is product-only"),
    ("M43-spanish-direction", "claim language is claim-path-only"),
    ("M47-tally-marks", "tally marks are claim-path-only"),
    ("M49-french-number", "claim language is claim-path-only"),
    ("M52-invalid-clock", "comparison vocabulary is claim-path-only"),
    ("M58-period-compound", "period compounds are claim-path-only"),
    ("M59-conflicting-category", "conflicting categories are claim-path-only"),
    ("M61-rate-word", "rate word still trips the base time arm"),
    ("M62-hidden-char-term", "unsafe text is claim-path-only"),
    ("M65-confusable-term", "claim language is claim-path-only"),
    ("M66-punctuated-literal", "raw literals are claim-path-only"),
    ("M68-bare-imperative", "bare imperatives are claim-path-only"),
    ("M7-raw-value", "raw ref, L1_RAW_VALUE"),
    ("M70-french-imperative", "claim language is claim-path-only"),
    (
        "M75-N07-wrong-duration-word",
        "fortnight is outside the carried-over unit families",
    ),
    ("M76-R11-magnitude-word", "gigawatts is not a unit, magnitude or percent form"),
    ("M77-R12-glued-letter", "glued x is not in the carried-over glued forms"),
    ("M8-slot-outside-hours", "slot hours, L1"),
    ("M83-R18-negated-one-word", "number inside non-zero is not carried over"),
    ("M84-R19-fact-both-directions", "fact-only period word is product-only"),
    ("M86-R21-period-other-sense", "period words in another sense are claim-path-only"),
    ("M87-R22-spaced-negation", "unsafe text is claim-path-only"),
    ("M89-R24-misspelled-literal", "raw literals are claim-path-only"),
    ("M9-action-in-busy", "action window, L1"),
    ("M90-R25-opener-imperative", "bare imperatives are claim-path-only"),
    ("M93-R28-strong-verb", "bare imperatives are claim-path-only"),
    ("M94-R32-exactness-limit", "integers past 2^53 are claim-path-only"),
    ("M95-R33-and-imperative", "bare imperatives are claim-path-only"),
    ("M96-R34-dash-imperative", "bare imperatives are claim-path-only"),
    ("M98-R36-named-not-cited", "uncited metrics are claim-path-only"),
    ("M99-R37-time-word-periodless", "time-scope word still trips the base time arm"),
)

EXCLUDED_KNOWN_GOOD = (
    ("G2-builder-with-parent", "parent and since_last the public shape cannot say"),
    (
        "G20-negative-delta-absolute",
        "parent and since_last the public shape cannot say",
    ),
    ("G26-n6-absent", "fact-only period word is product-only"),
    ("G28-n8-shipped", "fact-only period word is product-only"),
    ("G29-n9-review-notes", "fact-only period word is product-only"),
    ("G38-n18-use-of", "fact-only period word is product-only"),
    ("G39-n19-focus-dropped", "fact-only period word is product-only"),
    (
        "G4-disconnect-parent-pct-dec",
        "parent and since_last the public shape cannot say",
    ),
    ("G42-n22-godel", "fact-only period word is product-only"),
    ("G43-n23-due", "fact-only period word is product-only"),
    ("G46-n26-glimmer-fact", "fact-only period word is product-only"),
    (
        "G48-r2-name-with-number",
        "fact names holding numbers are not blanked in the public shape",
    ),
)


def _term_variant_hit(text: str, term: str) -> bool:
    """Whether ``text`` holds an li-fold or rotation of ``term``, not exact."""
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
            for s in briefing.get("sections", [])
            for claim in s.get("claims", [])
        ]
        if not any(word_list_hit(text, public_advice) for text in texts):
            return False
    for section in briefing.get("sections", []):
        for claim in section.get("claims", []):
            collapsed = collapse_text(claim["text"])
            if "to-last" in collapsed or "penultimate" in collapsed:
                return False
            if "at last" in collapsed:
                return False
            if contains_token(collapsed, "than"):
                tokens = re.findall(r"[a-z0-9_]+", collapsed)
                if (
                    "prior" in tokens
                    and "last" in tokens
                    and tokens.index("prior") < tokens.index("last")
                ):
                    return False
            if "L1_PRIVATE_TERM" in case.expected and any(
                _term_variant_hit(claim["text"], term)
                for term in case.context.private_terms
            ):
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
                    return False
            cited_periods = [
                binding.period
                for ref in claim.get("metric_refs", [])
                if (binding := metric_label_binding(ref["metric_id"])) is not None
            ]
            if {
                word for word in PERIOD_WORDS if contains_token(collapsed, word)
            } and not any(p is not None for p in cited_periods):
                return False
    return True


def _translate(case: Case) -> dict[str, object]:
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
    units: dict[str, str] = {}
    periods: dict[str, str] = {}
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
                labels[ref["metric_id"]] = [label]
                if binding.period is not None:
                    periods[ref["metric_id"]] = binding.period
                unit = metric_unit_class(ref["metric_id"])
                if unit is not None:
                    units[ref["metric_id"]] = unit
                if binding.period is not None:
                    stem = ref["metric_id"].split(f".{binding.period}.", 1)[1]
                    if stem not in stems:
                        stems[stem] = label
                    for period in PERIOD_WORDS:
                        labels.setdefault(f"period.{period}.{stem}", [stems[stem]])
                        periods.setdefault(f"period.{period}.{stem}", period)
    order = [[f"period.{period}.{stem}" for period in PERIOD_WORDS] for stem in stems]
    payload: dict[str, object] = {
        "claims": claims,
        "facts": facts,
        "metrics": metrics,
        "labels": labels,
        "deny_terms": list(context.private_terms),
        "advice_words": list(ADVICE_WORDS) + list(CLAIM_ADVICE_PHRASES),
    }
    if units:
        payload["units"] = units
    if periods:
        payload["periods"] = periods
    if order:
        payload["order"] = order
    return payload


def _gate_codes(case: Case) -> tuple[Counter[str], bool]:
    result = evaluate_briefing(case.briefing, case.context)
    seen: set[tuple[str, str]] = set()
    codes: list[str] = []
    for violation in result.violations:
        key = (violation.code, violation.location)
        if key not in seen:
            seen.add(key)
            codes.append(violation.code)
    return Counter(codes), result.passed


def _public_codes(case: Case) -> tuple[Counter[str], bool]:
    report = check_claims(_translate(case))
    return Counter(v.code for v in report.violations), report.passed


def _expressible() -> list[Case]:
    return [
        case
        for case in list(MUTANTS) + list(KNOWN_GOOD)
        if case.name in set(EXPRESSIBLE_MUTANTS) | set(EXPRESSIBLE_KNOWN_GOOD)
    ]


RETESTED_STILL_EXCLUDED = (
    "M100-R38-scale-word",
    "M61-rate-word",
    "M75-N07-wrong-duration-word",
    "M76-R11-magnitude-word",
    "M77-R12-glued-letter",
    "M83-R18-negated-one-word",
    "M99-R37-time-word-periodless",
)


def test_pinned_lists_match_the_predicate() -> None:
    # 38 base + 34 round-1 redteam (M39-M72) + 46 round-2 (M73-M118)
    # + 1 Ticket 10c since_last mutant (M119).
    assert len(MUTANTS) == 38 + 34 + 46 + 1 == 119
    assert len(KNOWN_GOOD) == 20 + 28 + 9 == 57
    pred_mutants = sorted(c.name for c in MUTANTS if _is_expressible(c))
    assert sorted(EXPRESSIBLE_MUTANTS) == sorted(
        set(pred_mutants) - set(RETESTED_STILL_EXCLUDED)
    )
    assert len(EXPRESSIBLE_MUTANTS) == 59
    assert sorted(pred_mutants) == sorted(
        list(EXPRESSIBLE_MUTANTS) + list(RETESTED_STILL_EXCLUDED)
    )
    assert sorted(n for n, _ in EXCLUDED_MUTANTS) == sorted(
        {c.name for c in MUTANTS} - set(EXPRESSIBLE_MUTANTS)
    )
    assert len(EXCLUDED_MUTANTS) == 60
    computed_good = sorted(c.name for c in KNOWN_GOOD if _is_expressible(c))
    assert computed_good == sorted(EXPRESSIBLE_KNOWN_GOOD)
    assert len(EXPRESSIBLE_KNOWN_GOOD) == 45
    assert sorted(n for n, _ in EXCLUDED_KNOWN_GOOD) == sorted(
        c.name for c in KNOWN_GOOD if not _is_expressible(c)
    )
    assert len(EXCLUDED_KNOWN_GOOD) == 12


def test_expressible_cases_match_gate_verdict() -> None:
    failures: list[str] = []
    for case in _expressible():
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
    for case in _expressible():
        first = _public_codes(case)
        payload = _translate(case)
        claims = payload["claims"]
        assert isinstance(claims, list)
        for claim in claims:
            assert isinstance(claim, dict)
            refs = claim.get("metric_refs", [])
            assert isinstance(refs, list)
            refs.reverse()
        second = (
            Counter(v.code for v in check_claims(payload).violations),
            check_claims(payload).passed,
        )
        if first != second:
            failures.append(
                f"{case.name}: plain={sorted(first[0].items())} rev={sorted(second[0].items())}"
            )
    assert failures == []


def test_cli_agrees_on_expressible(tmp_path: Path) -> None:
    failures: list[str] = []
    for case in _expressible():
        target = tmp_path / f"{case.name}.json"
        target.write_text(json.dumps(_translate(case)), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err  # type: ignore[assignment]
        try:
            code = main([str(target)])
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        _, gate_passed = _gate_codes(case)
        if (code == 0) != gate_passed:
            failures.append(f"{case.name}: cli={code} gate_passed={gate_passed}")
    assert failures == []


def test_bundle_agrees_on_expressible(tmp_path: Path) -> None:
    from framework.verify.page_bundle import build_bundle_text

    bundle = json.loads(build_bundle_text())
    assert "framework/verify/hardened.py" in bundle
    for relpath, source in bundle.items():
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    payloads = {case.name: _translate(case) for case in _expressible()}
    for name, payload in payloads.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    names = sorted(payloads)
    script = "\n".join(
        [
            f"import sys; sys.path.insert(0, {str(tmp_path)!r})",
            "import json",
            "from pathlib import Path",
            "from framework.verify.hardened import check_claims",
            f"names = {names!r}",
            f"root = {str(tmp_path)!r}",
            "out = {}",
            "for name in names:",
            "    report = check_claims((Path(root) / (name + '.json')).read_text())",
            "    out[name] = [sorted([v.code for v in report.violations]), report.passed]",
            "print(json.dumps(out))",
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    failures = []
    for case in _expressible():
        gate_counter, gate_passed = _gate_codes(case)
        codes, passed = got[case.name]
        if Counter(codes) != gate_counter or passed != gate_passed:
            failures.append(
                f"{case.name}: bundle={codes} gate={sorted(gate_counter.items())}"
            )
    assert failures == []
