"""Ticket 10b: review-rule regression rows (own sentences, not round text).

Table driven over :func:`evals.redteam.run_claim`: each row names the exact
codes the gate must emit. Failing rows prove the new rule; passing rows pin
the true sentences the rule must keep quiet on.
"""

from __future__ import annotations

import pytest

from evals.redteam import build_context, run_claim
from framework.briefing import claim_text

PROG_PRIOR = ("period.prior.screen_hours.Work/Programming", 4.75)
PROG_LAST = ("period.last.screen_hours.Work/Programming", 1.75)
PUSH_EARLIER = ("period.earlier.pushes", 3.0)
PUSH_PRIOR = ("period.prior.pushes", 1.0)
PUSH_LAST = ("period.last.pushes", 0.0)
BUSY = ("calendar.busy_hours", 6.5)

# (row id, claim text, metric refs, expected sorted codes)
ROWS: list[tuple[str, str, list[tuple[str, float]], list[str]]] = [
    # Value beside its period: forward swap.
    (
        "V1-forward-swap",
        "Pushes dropped from 1 in earlier to 3 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    # Backward with the period word between.
    (
        "V2-backward-period-word",
        "Pushes in prior stood at 0 and in last stood at 1.",
        [PUSH_PRIOR, PUSH_LAST],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    # Comma shape.
    (
        "V3-comma-shape",
        "In prior, programming reached 1.75, with last at 1.75.",
        [PROG_PRIOR, PROG_LAST],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    # Spelled values are values too, never unknown comparison words.
    (
        "V4-spelled-swap",
        "Pushes sank from zero in earlier to three in last.",
        [PUSH_EARLIER, PUSH_LAST],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    # Positional list stays quiet.
    (
        "V5-positional-list",
        "Pushes were 3 and 1 in earlier and prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        [],
    ),
    # Clause rule catches the adverb between separator and value.
    (
        "V6-clause-still",
        "Programming screen hours fell, last was still 4.75 and prior was still 1.75.",
        [PROG_PRIOR, PROG_LAST],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    # Stated change: the drop is 2, not 1.
    (
        "V7-stated-change",
        "Pushes dropped by 1 from 3 in earlier to 1 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_VALUE_PERIOD_MISMATCH"],
    ),
    (
        "V-true-forward",
        "Programming screen hours fell from 4.75 in prior to 1.75 in last.",
        [PROG_PRIOR, PROG_LAST],
        [],
    ),
    (
        "V-true-change",
        "Pushes fell by 1 from 1 in prior to 0 in last.",
        [PUSH_PRIOR, PUSH_LAST],
        [],
    ),
    (
        "V-true-backward",
        "In the prior period pushes stood at 1.",
        [PUSH_PRIOR],
        [],
    ),
    # Than comparison names the earlier period first.
    (
        "T-false-prior-lower",
        "Programming was lower in the prior period at 4.75 hours than in the last period at 1.75 hours.",
        [PROG_PRIOR, PROG_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "T-true-prior-higher",
        "Programming was higher in the prior period at 4.75 hours than in the last period at 1.75 hours.",
        [PROG_PRIOR, PROG_LAST],
        [],
    ),
    # Bare `one` as a count.
    (
        "O-fail-last-one",
        "Pushes in last hit one.",
        [PUSH_LAST],
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    ("O-pass-prior-one", "Pushes in prior reached one.", [PUSH_PRIOR], []),
    ("O-pass-determiner", "Pushes in last reached the one.", [PUSH_LAST], []),
    # Units.
    (
        "U-fail-magnitude",
        "Programming screen hours in last ran 1.75 km.",
        [PROG_LAST],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "U-fail-duration",
        "Programming screen hours in last ran 1.75 fortnights.",
        [PROG_LAST],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "U-fail-wrong-noun",
        "Pushes in last were 0 tables.",
        [PUSH_LAST],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "U-fail-percent",
        "Programming screen hours in last ran 1.75 percent.",
        [PROG_LAST],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "U-pass-adjective",
        "Programming screen hours in last were 1.75 quiet hours.",
        [PROG_LAST],
        [],
    ),
    (
        "U-pass-plain",
        "Programming screen hours in last were 1.75 hours.",
        [PROG_LAST],
        [],
    ),
    # Joined labels: case boundary counts, lower-case joining does not.
    (
        "J-fail-camel",
        "MediaVideo programming screen time in last was 1.75.",
        [PROG_LAST],
        ["L1B_METRIC_LABEL_MISMATCH"],
    ),
    (
        "J-pass-lower",
        "Mediavideo programming screen hours in last were 1.75.",
        [PROG_LAST],
        [],
    ),
    # Uncited period belongs to the period check, not the value check.
    (
        "P-uncited-period",
        "Programming screen hours fell from 4.75 in earlier to 1.75 in last.",
        [PROG_PRIOR, PROG_LAST],
        ["L1B_PERIOD_WORD_MISSING"],
    ),
    # Glued letter-digit runs (metric claims only).
    (
        "Q1-glued-trailing",
        "Pushes in earlier totalled 3O.",
        [PUSH_EARLIER],
        ["L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q1-glued-leading",
        "Pushes in earlier were x3.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q1-glued-odd-suffix",
        "Pushes in earlier were 3-odd.",
        [PUSH_EARLIER],
        ["L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q1-pass-hours-glued-unit",
        "Programming screen hours in last were 1.75h.",
        [PROG_LAST],
        [],
    ),
    (
        "Q1-pass-ordinal-suffix",
        "Pushes in last hit its 99th push.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Qualifiers around a number.
    (
        "Q2-after",
        "Pushes in earlier totalled 3 or so.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q2-after-label",
        "Pushes in earlier were 3 pushes or so.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q2-before",
        "Pushes in earlier were a minimum of 3.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q2-before-square",
        "Programming hours in last totaled the square of 1.75.",
        [PROG_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q2-pass-two-values",
        "Programming screen hours fell from 4.75 hours in prior to 1.75 hours in last.",
        [PROG_PRIOR, PROG_LAST],
        [],
    ),
    # Quantity words.
    (
        "Q3-hundreds",
        "Pushes in last were hundreds.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-tens",
        "Tens of pushes landed in last.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-a-single",
        "A single push arrived in last.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-once",
        "Pushes in last happened once.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-multiplied",
        "Pushes in last multiplied to 0.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-trebled",
        "Pushes in earlier trebled to 3.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q3-billion",
        "Pushes in last reached 0 billion.",
        [PUSH_LAST],
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    ("Q3-pass-true", "Pushes in prior stood at 1.", [PUSH_PRIOR], []),
    # Lower-case Roman numerals (metric claims only).
    (
        "Q4-lower",
        "Pushes in last were xii.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    ("Q4-pass-i", "Pushes in last were i.", [PUSH_LAST], []),
    # Rank and share (metric claims only).
    (
        "Q5-bulk",
        "The bulk of pushes landed in last.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q5-new-high",
        "Pushes in last hit a new high.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q5-ordinal-was",
        "Pushes were 2nd in last.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Universal words on metric claims.
    (
        "Q6-every",
        "Every push landed in last.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q6-pass-coordination",
        "Both pushes and pulls landed in last.",
        [PUSH_LAST],
        [],
    ),
    (
        "Q6-pass-other-label",
        "All repos note pushes in last stood at 0.",
        [PUSH_LAST],
        [],
    ),
    # Time scope on metric claims.
    (
        "Q7-today",
        "Pushes in last reached 0 today.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q7-week",
        "Pushes in last stood at 0 this week.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # New quantity kinds.
    (
        "Q8-ordinal-word",
        "Pushes in last hit the twelfth push.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-ordinal-hyphen",
        "Pushes in last hit the twenty-first push.",
        [PUSH_LAST],
        ["L1B_NUMBER_WITHOUT_METRIC_REF", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-tally",
        "Pushes in last went push, push, push.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-fraction-shape",
        "Pushes in earlier showed 3_000 with last at 0.",
        [PUSH_EARLIER, PUSH_LAST],
        ["L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-fraction-decimal",
        "Pushes in earlier were 3.000.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-range",
        "Pushes in last varied.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q8-between",
        "Pushes in last sat between 0 and 1.",
        [PUSH_LAST],
        ["L1B_NUMBER_WITHOUT_METRIC_REF", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Negation.
    (
        "Q9-nonzero",
        "Pushes in last were nonzero.",
        [PUSH_LAST],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "Q9-anything",
        "Pushes in last numbered anything but 0.",
        [PUSH_LAST],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "Q9-other",
        "Pushes in last were other than 0.",
        [PUSH_LAST],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "Q9-pass-zero",
        "Pushes in last were no pushes.",
        [PUSH_LAST],
        [],
    ),
    # Direction words with hyphens.
    (
        "Q10-hyphen",
        "Pushes in last sat higher-than-usual at 0.",
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "Q10-uptrend",
        "Pushes in last stayed up-trending at 0.",
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "Q10-above",
        "Pushes in last were above-average at 0.",
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    # Period words.
    (
        "Q11-resort",
        "Pushes stood at 0 in last resort.",
        [PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING"],
    ),
    (
        "Q11-next",
        "Pushes in next-to-last were 0.",
        [PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING"],
    ),
    (
        "Q11-pass-prior",
        "Pushes in next-to-last were 1.",
        [PUSH_PRIOR],
        [],
    ),
    (
        "Q11-pass-earlier",
        "Pushes in third-to-last were 3.",
        [PUSH_EARLIER],
        [],
    ),
    # `held` reads as contained, so a count after it states no direction.
    (
        "H-pass-held-pushes",
        "Pushes held 0 in last.",
        [PUSH_LAST],
        [],
    ),
    (
        "H-pass-held-hours",
        "Programming held 1.75 hours in last.",
        [PROG_LAST],
        [],
    ),
    # `ahead` ranks nothing in a planning phrase, so those pass.
    (
        "A-pass-plan-ahead",
        "Busy hours ran 6.5, leaving this hour clear to plan ahead.",
        [BUSY],
        [],
    ),
    (
        "A-pass-planning-ahead",
        "Busy hours ran 6.5 with planning ahead in mind.",
        [BUSY],
        [],
    ),
    # Naming a second metric without citing it: the cited numeral cannot
    # back the unnamed one.
    (
        "C-fail-uncited-busy",
        "Pushes in last were 0 while busy hours ran 6.5.",
        [PUSH_LAST],
        ["L1B_METRIC_LABEL_MISMATCH", "L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    (
        "C-fail-uncited-prior",
        "Pushes in prior were 1 while busy hours ran 6.5.",
        [PUSH_PRIOR],
        ["L1B_METRIC_LABEL_MISMATCH", "L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    (
        "C-pass-cited-busy",
        "Busy hours ran 6.5 over the window.",
        [BUSY],
        [],
    ),
    # A range across two named periods that holds both ends passes.
    (
        "R-pass-range-earlier-last",
        "Pushes ranged from 3 in earlier to 0 in last.",
        [PUSH_EARLIER, PUSH_LAST],
        [],
    ),
    (
        "R-pass-range-prior-last",
        "Programming ranged from 4.75 in prior to 1.75 in last.",
        [PROG_PRIOR, PROG_LAST],
        [],
    ),
    # A hyphen compound hiding a direction word is not known vocabulary,
    # even when the other part is: `over-` joined to a direction word
    # between two values and their periods still fails the comparison.
    (
        "W-fail-over-fell",
        "Pushes over-fell from 3 in earlier to 1 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_COMPARISON_WORD_UNKNOWN"],
    ),
    (
        "W-fail-over-rose",
        "Pushes over-rose from 3 in earlier to 1 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_COMPARISON_WORD_UNKNOWN"],
    ),
    # A direction compound the direction rule reads stays known.
    (
        "W-pass-down-fell",
        "Pushes down-fell from 3 in earlier to 1 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        [],
    ),
    (
        "W-pass-plain-fell",
        "Pushes fell from 3 in earlier to 1 in prior.",
        [PUSH_EARLIER, PUSH_PRIOR],
        [],
    ),
    # Underscores read as spaces for every quantity kind: vague phrases.
    (
        "U-fail-vague-wrapped",
        "Pushes in earlier stood at 3 with _several_ extras.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "U-fail-vague-joined",
        "Pushes in earlier stood at 3 with a_couple extras.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "U-fail-vague-half-dozen",
        "Pushes in earlier stood at 3 with half_dozen extras.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Underscores read as spaces for every quantity kind: rank words.
    (
        "U-fail-rank-wrapped",
        "Pushes in earlier stood at 3, the _top_ push.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "U-fail-record-joined",
        "Pushes in last hit a_new_high.",
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Qualifier phrases joined with underscores keep firing as before.
    (
        "U-pass-qualifier-joined",
        "Pushes in earlier were a_minimum_of 3.",
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Plain sentences the underscore rule must keep quiet on.
    (
        "U-pass-plain-standing",
        "Pushes in earlier stood at 3.",
        [PUSH_EARLIER],
        [],
    ),
]

# (row id, claim text, fact ids, metric refs, expected sorted codes)
FROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    (
        "Q5-pass-session",
        "Notes from the 3rd session.",
        ["f1"],
        [],
        [],
    ),
    (
        "Q6-fact-each",
        "Each push landed in last.",
        ["f1"],
        [],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Q7-fact-today",
        "Pushes fell today.",
        ["f1"],
        [],
        [],
    ),
    (
        "Q10-fact-mixed",
        "Pushes sank in prior and climbed in last.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "Q10-fact-matched",
        "Pushes in last equaled pushes in earlier.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "Q10-fact-particle",
        "Pushes followed-up in last.",
        ["f1"],
        [],
        [],
    ),
    # README known costs: true sentences the gate rejects, one pin each.
    (
        "K1-stated-change",
        "Pushes fell to 0 in last.",
        ["f1"],
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "K2-spelled-count",
        "Pushes fell to zero in last.",
        ["f1"],
        [],
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    (
        "K3-failed",
        "Pushes failed to appear in last.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "K4-two-numbers",
        "Pushes went from 3 to 0.",
        ["f1"],
        [],
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    (
        "K5-no-time",
        "Pushes in last were none.",
        ["f1"],
        [PUSH_LAST],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "K6-time-words",
        "Pushes now stand at 0.",
        ["f1"],
        [PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING"],
    ),
    (
        "K7-quoted-title",
        '"Late Review": review pushes in last at 0.',
        ["f1"],
        [PUSH_LAST],
        ["L1_ADVICE"],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), FROWS)
def test_fact_review_rows(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


# Ticket 10b red-team follow-ups: empty text, links, spelled-out text,
# private-term shapes, raw-literal spans, imperatives, advice, titles,
# and language lists. Own sentences; the round texts stay out of the file.
T10B_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    ("X01-empty", "...", ["f1"], [], ["L1_UNSAFE_TEXT"]),
    (
        "X02-link-http",
        "The full log sits at http://example.net/z.",
        ["f1"],
        [],
        ["L1_UNSAFE_TEXT"],
    ),
    (
        "X03-link-www",
        "Further notes wait on www.example.net/z.",
        ["f1"],
        [],
        ["L1_UNSAFE_TEXT"],
    ),
    (
        "X04-spelled",
        "Pushes in last stood at 0, marked N O T.",
        [],
        [PUSH_LAST],
        ["L1_UNSAFE_TEXT"],
    ),
    (
        "X05-spelled-two",
        "Pushes in last stood at 0, marked O K.",
        [],
        [PUSH_LAST],
        [],
    ),
    (
        "X06-phonetic",
        "The notes name Alfa Bravo Charlie today.",
        ["f1"],
        [],
        ["L1_UNSAFE_TEXT"],
    ),
    (
        "X07-phonetic-two",
        "The notes name Alfa Bravo today.",
        ["f1"],
        [],
        [],
    ),
    (
        "X08-spelled-term-skip",
        "The notes mention Q U I L L O N today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X09-spelled-term-split",
        "The notes spell Q U I L L O N today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X10-punct-term",
        "The notes name Zebra; finch today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X11-rotation-term",
        "The archive cites Finchzebra today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X12-fold-li-term",
        "The archive cites QuiIIon today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X13-pair-join",
        "The notes name Zebra Finch today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X14-pair-near",
        "The notes name Zebra Vinch today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X15-pair-first-letter-guard",
        "The notes name Xebra Finch today.",
        ["f1"],
        [],
        [],
    ),
    (
        "X16-mask-fire",
        "The archive cites Qu*llon today.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X17-mask-sentence-end",
        "The archive cites Qu*llon.",
        ["f1"],
        [],
        ["L1_PRIVATE_TERM"],
    ),
    (
        "X18-dots-not-mask",
        "Pushes in prior were 1...",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "X19-dashes-not-mask",
        "Pushes in prior were 1 --",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "X20-bag-edit",
        "The notes mention Dentis on Tuesday.",
        ["f1"],
        [],
        ["L1_RAW_VALUE"],
    ),
    (
        "X21-bag-prefix",
        "The notes mention Dent on Tuesday.",
        ["f1"],
        [],
        ["L1_RAW_VALUE"],
    ),
    (
        "X22-bag-near",
        "The calendar cites Dentist in the early morning on Tuesday.",
        ["f1"],
        [],
        ["L1_RAW_VALUE"],
    ),
    (
        "X23-bag-far",
        "The notes mention Dentist after the long morning review ended on Tuesday.",
        ["f1"],
        [],
        [],
    ),
    (
        "X24-opener",
        "Today polish one small widget.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X25-time-to",
        "Time to launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X26-so-mid",
        "Pushes fell in last so launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X27-and-join",
        "Notes were filed in last and launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X28-dash-join",
        "Notes were filed in last - launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X29-bracket-join",
        "Notes were filed in last (launch the parser).",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X30-glued-em",
        "Notes were filed in last—launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X31-question",
        "Could the next free hour fit a short build.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X32-would-help",
        "It would help to launch a small widget.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X33-would-be-good",
        "A calm week would be good for momentum.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X34-next-move",
        "A short walk is the next move.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X35-overdue",
        "Delaying the parser upgrade is overdue.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X36-shall",
        "You shall complete the parser tonight.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X37-commit-to",
        "Commit to the plan.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X38-test-verb",
        "Test the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X39-launch",
        "Launch the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X40-title-vocative",
        "Colleague ship a small change in the free hour.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X41-title-whole",
        "Ship one small change in the free hour.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X42-hour-needs",
        "This hour needs a short rest.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "X43-fits-hour",
        "Pushes stood at 0 in last, and rest fits this hour.",
        [],
        [PUSH_LAST],
        [],
    ),
    (
        "X44-noun-second",
        "Build logs show steady work.",
        ["f1"],
        [],
        [],
    ),
    (
        "X45-lined-up",
        "Push and pull request activity lined up lately, so building fits this hour.",
        ["f1"],
        [],
        [],
    ),
    (
        "X46-time-split",
        "Time split between build notes and rest.",
        ["f1"],
        [],
        [],
    ),
    (
        "X47-merged-fix",
        "The merged fix landed in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "X48-hour-free",
        "The next hour is free.",
        ["f1"],
        [],
        [],
    ),
    (
        "X49-crecen",
        "Pushes in last crecen at 0.",
        [],
        [PUSH_LAST],
        ["L1_CLAIM_LANGUAGE"],
    ),
    (
        "X50-spanish-sin",
        "Una semana sin prisa con calma.",
        ["f1"],
        [],
        ["L1_CLAIM_LANGUAGE"],
    ),
    (
        "X51-dutch-direction",
        "De groei daalt in het vrije uur.",
        ["f1"],
        [],
        ["L1_CLAIM_LANGUAGE"],
    ),
    (
        "X52-dutch-advice",
        "Verzend een update voor het vrije uur.",
        ["f1"],
        [],
        ["L1_CLAIM_LANGUAGE"],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10B_ROWS)
def test_t10b_review_rows(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


# Ticket 10b over-blocks: true sentences in Ticket 11's prompt shapes that
# the gate rejects. Own sentences; the round texts stay out of the file.
T10B_OVERBLOCK_ROWS: list[
    tuple[str, str, list[str], list[tuple[str, float]], list[str]]
] = [
    # `last card` stays off the period list outside since_last.
    (
        "LC-last-card-working",
        "Pushes stood at 0 since the last card.",
        [],
        [PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING"],
    ),
    # The pick named after `this hour goes to` is not the title.
    (
        "TT-goes-to-pick",
        "Programming screen hours stood at 4.75 in prior, so this hour goes to one small change.",
        [],
        [PROG_PRIOR],
        [],
    ),
    (
        "TT-goes-toward-pick",
        "Programming screen hours stood at 4.75 in prior, so this hour goes toward one small change.",
        [],
        [PROG_PRIOR],
        [],
    ),
    (
        "TT-goes-towards-pick",
        "Programming screen hours stood at 4.75 in prior, so this hour goes towards one small change.",
        [],
        [PROG_PRIOR],
        [],
    ),
    # Advice and imperatives still read the whole claim.
    (
        "TT-advice-still-reads",
        "Programming screen hours stood at 4.75 in prior, so this hour goes to one small change, which would help.",
        [],
        [PROG_PRIOR],
        ["L1_ADVICE"],
    ),
    (
        "TT-imperative-still-reads",
        "Programming screen hours stood at 4.75 in prior, so this hour goes to one small change, time to ship.",
        [],
        [PROG_PRIOR],
        ["L1_ADVICE"],
    ),
    # The title anywhere else still fires.
    (
        "TT-title-elsewhere",
        "One small change followed programming screen hours at 4.75 in prior.",
        [],
        [PROG_PRIOR],
        ["L1_ADVICE"],
    ),
    # `tied to` states a connection, never equality: no direction word.
    (
        "TD-tied-to-quiet",
        "Programming screen hours stood at 1.75 in last, tied to screens.",
        [],
        [PROG_LAST],
        [],
    ),
    (
        "TD-tied-to-front-quiet",
        "Tied to screens, programming screen hours stood at 1.75 in last.",
        [],
        [PROG_LAST],
        [],
    ),
    (
        "TD-tied-to-fact-quiet",
        "Pushes in last were tied to screens.",
        ["f1"],
        [],
        [],
    ),
    # Bare `tied` or `tied with` still states equality (N17's shape).
    (
        "TD-tied-with-still-fires",
        "Programming screen hours stood at 1.75 in last, tied with screens.",
        [],
        [PROG_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "TD-tied-bare-fact-still-fires",
        "Pushes in last tied pushes in earlier.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "TD-tied-with-fact-still-fires",
        "Pushes in last tied with pushes in earlier.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    # `ahead` after a time noun ranks nothing.
    (
        "AH-week-ahead",
        "Busy hours ran 6.5, clearing the week ahead for deep work.",
        [],
        [BUSY],
        [],
    ),
    (
        "AH-day-ahead",
        "Busy hours ran 6.5, leaving the day ahead open for calls.",
        [],
        [BUSY],
        [],
    ),
    (
        "AH-month-ahead",
        "Busy hours ran 6.5 with the month ahead in view.",
        [],
        [BUSY],
        [],
    ),
    (
        "AH-hour-ahead",
        "Busy hours ran 6.5, with a quiet hour ahead.",
        [],
        [BUSY],
        [],
    ),
    (
        "AH-time-ahead",
        "Busy hours ran 6.5, with free time ahead.",
        [],
        [BUSY],
        [],
    ),
    # `ahead of` stays a rank word.
    (
        "AH-ahead-of-still-ranks",
        "Pushes landed ahead of prior at 0 in last.",
        [],
        [PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # `steady`/`stable` before a noun are adjectives, not direction.
    (
        "ST-adjective-steady",
        "Programming screen hours stood at 4.75 in prior with steady work.",
        [],
        [PROG_PRIOR],
        [],
    ),
    (
        "ST-adjective-stable",
        "Programming screen hours stood at 4.75 in prior with stable pacing.",
        [],
        [PROG_PRIOR],
        [],
    ),
    (
        "ST-plain-verb-steady",
        "Programming screen hours ran steady at 4.75 in prior.",
        [],
        [PROG_PRIOR],
        [],
    ),
    # After a copula or a cited label they still count as same-direction.
    (
        "ST-was-steady-still",
        "Programming screen hours were steady at 4.75 in prior.",
        [],
        [PROG_PRIOR],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "ST-label-steady-still",
        "Programming steady at 4.75 in prior.",
        [],
        [PROG_PRIOR],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "ST-sat-stable-still",
        "Pushes sat stable at 0 in last.",
        [],
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    # `a single` on a fact-only claim about a non-label.
    (
        "SG-book-passes",
        "I read a single book in the window.",
        ["f1"],
        [],
        [],
    ),
    # Right before a snapshot label it still fires.
    (
        "SG-label-still",
        "A single push settled the debate.",
        ["f1"],
        [],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
]


@pytest.mark.parametrize(
    ("row_id", "text", "fact_ids", "refs", "expected"), T10B_OVERBLOCK_ROWS
)
def test_t10b_overblock_rows(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


# Ticket 10b: the pick after bare `this hour goes` names the pick too, so
# neither the title rule nor the other-metric label check reads it. Own
# sentences; the round texts stay out of the file.
T10B_GOES_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # The pick is a snapshot label of another metric: an adverb of place.
    (
        "GH-bare-goes-home-quiet",
        "Programming screen hours stood at 4.75 in prior, so this hour goes home.",
        [],
        [PROG_PRIOR],
        [],
    ),
    (
        "GH-bare-goes-title-quiet",
        "Programming screen hours stood at 4.75 in prior, so this hour goes one small change.",
        [],
        [PROG_PRIOR],
        [],
    ),
    # With `toward` the label check skips the pick as well.
    (
        "GH-toward-home-quiet",
        "Programming screen hours stood at 4.75 in prior, so this hour goes toward home.",
        [],
        [PROG_PRIOR],
        [],
    ),
    # A label anywhere else still fires, and other rules still read the pick.
    (
        "GH-label-elsewhere-still-fires",
        "Programming screen hours stood at 4.75 in prior over video, so this hour goes home.",
        [],
        [PROG_PRIOR],
        ["L1B_METRIC_LABEL_MISMATCH"],
    ),
    (
        "GH-advice-in-pick-still-reads",
        "Programming screen hours stood at 4.75 in prior, so this hour goes home, which would help.",
        [],
        [PROG_PRIOR],
        ["L1_ADVICE"],
    ),
]


def _context_with_home():  # type: ignore[no-untyped-def]
    return _context_plus({"period.last.screen_hours.Home": 2.0})


def test_t10b_bare_goes_pick() -> None:
    context = _context_with_home()
    for row_id, text, fact_ids, refs, expected in T10B_GOES_ROWS:
        outcome = run_claim(
            text,
            fact_ids,
            [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
            context,
        )
        assert outcome["raised"] is None, row_id
        assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


def _context_with_terms(terms: tuple[str, ...]):  # type: ignore[no-untyped-def]
    return build_context().model_copy(update={"private_terms": terms})


def test_short_private_word_does_not_fire() -> None:
    context = _context_with_terms(("Zebrafinch", "I 7 depot"))
    outcome = run_claim(
        "Pushes in prior came to 1.",
        [],
        [{"metric_id": "period.prior.pushes", "value": 1.0}],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


def test_hyphen_term_parts_do_not_fire() -> None:
    context = _context_with_terms(("quetzal-garden",))
    for text in (
        "A garden stroll fits the notes.",
        "The notes mention Quetzal today.",
    ):
        outcome = run_claim(text, ["f1"], [], context)
        assert outcome["raised"] is None, text
        assert sorted(outcome["codes"]) == [], text


def test_multiword_term_word_and_whole_fire() -> None:
    context = _context_with_terms(("zebra finch",))
    for text in (
        "The notes mention Zebra today.",
        "The notes mention Zebra finch today.",
    ):
        outcome = run_claim(text, ["f1"], [], context)
        assert outcome["raised"] is None, text
        assert sorted(outcome["codes"]) == ["L1_PRIVATE_TERM"], text


def test_curly_apostrophe_term_matches() -> None:
    context = _context_with_terms(("quetzal's garden",))
    outcome = run_claim(
        "The archive cites Quetzal’s garden today.",
        ["f1"],
        [],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1_PRIVATE_TERM"]


@pytest.mark.parametrize(("row_id", "text", "refs", "expected"), ROWS)
def test_review_rows(
    row_id: str, text: str, refs: list[tuple[str, float]], expected: list[str]
) -> None:
    outcome = run_claim(
        text,
        [],
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


def _context_with(metric_id: str, value: float):
    context = build_context()
    values = dict(context.metrics.values)
    values[metric_id] = value
    return context.model_copy(
        update={"metrics": context.metrics.model_copy(update={"values": values})}
    )


def test_clock_followed_by_unit_word_is_a_number() -> None:
    outcome = run_claim(
        "Napped 7:45 hours.",
        ["f1"],
        [],
        build_context(),
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1B_NUMBER_WITHOUT_METRIC_REF"]


def test_range_between_values_has_no_unit_code() -> None:
    context = _context_with("period.last.screen_hours.Work/Programming", 5.0)
    outcome = run_claim(
        "Programming moved 4.75-5 across prior and last.",
        [],
        [
            {"metric_id": "period.prior.screen_hours.Work/Programming", "value": 4.75},
            {"metric_id": "period.last.screen_hours.Work/Programming", "value": 5.0},
        ],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


def test_whole_number_backing_rounds_to_two_places() -> None:
    context = _context_with("github.push.count", 4.9999999)
    outcome = run_claim(
        "GitHub pushes reached 5.",
        [],
        [{"metric_id": "github.push.count", "value": 4.9999999}],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


def test_huge_ref_value_mismatches_snapshot() -> None:
    big = float(2**53)
    context = _context_with("github.push.count", big)
    outcome = run_claim(
        "GitHub pushes have reached 9007199254740992.",
        [],
        [{"metric_id": "github.push.count", "value": big}],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1B_METRIC_VALUE_MISMATCH"]


def test_long_text_reports_only_length() -> None:
    text = "Pushes in last were 0 " + "a" * 1979
    assert len(text) > 2000
    outcome = run_claim(
        text, [], [{"metric_id": "period.last.pushes", "value": 0.0}], build_context()
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1_TEXT_TOO_LONG"]


def test_exactly_2000_chars_has_no_length_code() -> None:
    base = "Pushes in last were 0 in"
    pool = ["calm", "bright", "field", "stone", "river", "maple"]
    text = base + "".join(f" {pool[i % len(pool)]}" for i in range(330))
    tail = " xyzab"
    while len(text) + len(tail) > 2000:
        text = text.rsplit(" ", 1)[0]
    text += "x" * (2000 - len(tail) - len(text)) + tail
    assert len(text) == 2000
    outcome = run_claim(
        text, [], [{"metric_id": "period.last.pushes", "value": 0.0}], build_context()
    )
    assert outcome["raised"] is None
    assert "L1_TEXT_TOO_LONG" not in outcome["codes"]
    assert sorted(outcome["codes"]) == []


def test_direction_lists_live_on_claim_text() -> None:
    from framework.briefing import claim_text, gate

    assert "growth" in claim_text.UP_WORDS
    assert "decline" in claim_text.DOWN_WORDS
    assert tuple(claim_text.PERIOD_WORDS) == ("earlier", "prior", "last")
    assert tuple(claim_text.ADVICE_PHRASES) == ("push harder", "rest more")
    assert gate.UP_WORDS is claim_text.UP_WORDS
    assert gate.DOWN_WORDS is claim_text.DOWN_WORDS
    assert gate.PERIOD_WORDS is claim_text.PERIOD_WORDS
    assert gate.ADVICE_PHRASES is claim_text.ADVICE_PHRASES
    assert not hasattr(claim_text, "set_direction_bases")


def test_cancel_is_comparison_vocabulary() -> None:
    from framework.briefing.claim_text import COMPARISON_VOCABULARY

    assert "cancel" in COMPARISON_VOCABULARY


def _context_plus(extra_values: dict[str, float]):  # type: ignore[no-untyped-def]
    context = build_context()
    values = dict(context.metrics.values)
    values.update(extra_values)
    return context.model_copy(
        update={"metrics": context.metrics.model_copy(update={"values": values})}
    )


def test_cancel_true_sentence_passes() -> None:
    context = _context_plus(
        {
            "period.last.cancelled.iki-deep": 0.0,
            "period.prior.cancelled.iki-deep": 1.0,
        }
    )
    outcome = run_claim(
        "Cancelled deep blocks fell from 1 in the prior period to 0 in the last period.",
        [],
        [
            {"metric_id": "period.prior.cancelled.iki-deep", "value": 1.0},
            {"metric_id": "period.last.cancelled.iki-deep", "value": 0.0},
        ],
        context,
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


def test_cited_label_holding_shorter_label_stays_quiet() -> None:
    context = _context_plus(
        {
            "period.last.screen_hours.Comms/Video Calls": 1.5,
            "period.prior.screen_hours.Comms/Video Calls": 1.0,
        }
    )
    video_calls = [
        {"metric_id": "period.last.screen_hours.Comms/Video Calls", "value": 1.5}
    ]
    video = [{"metric_id": "period.last.screen_hours.Media/Video", "value": 4.0}]
    # The cited label holds `video` as one of its words; naming only the
    # cited label is not naming the other metric.
    outcome = run_claim("Video Calls in last were 1.5 hours.", [], video_calls, context)
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []
    # Naming the shorter label on its own as well still fires.
    outcome = run_claim(
        "Video Calls in last were 1.5 hours of video.", [], video_calls, context
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1B_METRIC_LABEL_MISMATCH"]
    # The shorter label on its own stays quiet; naming the longer one fires.
    outcome = run_claim("Video in last was 4 hours.", [], video, context)
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []
    outcome = run_claim("Video in last was 4 hours of video calls.", [], video, context)
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == ["L1B_METRIC_LABEL_MISMATCH"]


def test_fact_universal_exempt_when_statement_holds_all() -> None:
    context = build_context(
        extra_facts=[
            {"id": "f9", "statement": "All pushes finished in last."},
        ]
    )
    outcome = run_claim("Each push landed in last.", ["f9"], [], context)
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


def test_time_scope_helper_exempts_cited_labels() -> None:
    from framework.briefing.quantities import time_scope_hit

    assert time_scope_hit("pushes in last reached 0 today", set()) == ("today",)
    assert time_scope_hit("pushes in last reached 0 today", {"today"}) == ()
    assert time_scope_hit("pushes in last stood at 0", set()) == ()


# Ticket 10b round-2 follow-ups: digit ordinals on metric claims, the
# missing advice phrase, bracket/dash clause starts, fact-arm label forms
# and `both`. Own sentences; the round texts stay out of the file.
T10C_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # Digit ordinal before a non-count noun fires on a metric claim.
    (
        "Y01-ordinal-milestone",
        "Pushes reached the 2nd milestone in last.",
        [],
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "Y02-ordinal-place",
        "Pushes took 3rd place in last.",
        [],
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Fact-only claims keep the old shape: ordinals before other nouns pass.
    (
        "Y03-ordinal-fact-shift",
        "Pushes took the 2nd shift in last.",
        ["f1"],
        [],
        [],
    ),
    # `is required` fires like `is needed`.
    (
        "Y04-required-mid",
        "An evening review is required for the free hour.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "Y05-required-front",
        "A rest break is required before the next build.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "Y06-review-filed-true",
        "An evening review was filed in last.",
        ["f1"],
        [],
        [],
    ),
    # Noun in brackets followed by a bare verb form: no advice.
    (
        "Y07-bracket-past-quiet",
        "The session (prior) set off early.",
        ["f1"],
        [],
        [],
    ),
    (
        "Y08-dash-verb-quiet",
        "The session ended early - set off again.",
        ["f1"],
        [],
        [],
    ),
    # Imperative in brackets, or after a spaced dash, with an object word.
    (
        "Y09-bracket-object-fires",
        "Notes were filed in last (send one update).",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    (
        "Y10-dash-object-fires",
        "Notes were filed in last - send one update.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    # Fact arm: `push` over a statement saying `pushes` is one label.
    (
        "Y11-fact-label-forms",
        "Push activity fell in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "Y12-fact-label-other",
        "Programming fell in last.",
        ["f1"],
        [],
        ["L1B_METRIC_LABEL_MISMATCH"],
    ),
    # Fact arm: `both` over two cited facts is ordinary and true.
    (
        "Y13-fact-both-quiet",
        "Both pushes finished in last.",
        ["f1"],
        [],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Metric arm: `both` still states a share.
    (
        "Y14-metric-both-fires",
        "Both pushes stood at 3 in earlier and 1 in prior.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10C_ROWS)
def test_t10c_review_rows(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


def test_long_action_text_reports_length() -> None:
    from evals.redteam import build_host_briefing
    from framework.briefing.gate import evaluate_briefing

    briefing = build_host_briefing(
        "Pushes in last were 0.",
        [],
        [{"metric_id": "period.last.pushes", "value": 0.0}],
    )
    briefing["sections"][3]["actions"][0]["text"] = (
        "Ship one small change " + "x" * 2000
    )
    result = evaluate_briefing(briefing, build_context())
    assert not result.passed
    assert [v.code for v in result.violations] == [
        "L1_ACTION_TEXT_MISMATCH",
        "L1_TEXT_TOO_LONG",
    ]


# Ticket 10b dead-list sweep: these foreign word lists had no test reaching
# any entry. One sentence form covers every entry: each fires the
# claim-language rule on a metric claim.
_DEAD_FOREIGN_LISTS = (
    ("SPANISH_ADVICE", claim_text.SPANISH_ADVICE),
    ("FRENCH_DIRECTION", claim_text.FRENCH_DIRECTION),
    ("FRENCH_ADVICE", claim_text.FRENCH_ADVICE),
    ("GERMAN_DIRECTION", claim_text.GERMAN_DIRECTION),
    ("GERMAN_NUMBERS", claim_text.GERMAN_NUMBERS),
    ("GERMAN_ADVICE", claim_text.GERMAN_ADVICE),
    ("ITALIAN_DIRECTION", claim_text.ITALIAN_DIRECTION),
    ("PORTUGUESE_DIRECTION", claim_text.PORTUGUESE_DIRECTION),
    ("PORTUGUESE_ADVICE", claim_text.PORTUGUESE_ADVICE),
)
_DEAD_FOREIGN_ROWS = tuple(
    (list_name, word)
    for list_name, words in _DEAD_FOREIGN_LISTS
    for word in sorted(words)
)


# Ticket 10b red-team round-3 follow-ups: one row per review finding, in
# sentences made up here. Table form is (row id, text, fact ids, refs,
# expected sorted codes); the comparison-crash rows below assert only that
# the gate returns, over every period-word pair against every cited pair.
T10D_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # A stated zero still reads its direction word.
    (
        "R2-no-rose",
        "No pushes rose in last.",
        [],
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "R2-no-climbed",
        "No pushes climbed in last.",
        [],
        [PUSH_LAST],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "R2-true-no-direction",
        "No pushes stood at 0 in last.",
        [],
        [PUSH_LAST],
        [],
    ),
    (
        "R2-nonzero-pins-negation",
        "No pushes rose in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    ),
    # A closed negator rejects a label no cited statement holds.
    (
        "R3-push-over-other",
        "Pushes failed.",
        ["f2"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "R3-programming-over-pushes",
        "Programming never landed.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "R3-true-direction-negator",
        "Pushes never fell.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "R3-true-quiet",
        "Pushes landed in last.",
        ["f1"],
        [],
        [],
    ),
    # A period compound states its period to the value rules.
    (
        "R4-next-spaced",
        "Pushes stood at 0 in next to last.",
        [],
        [PUSH_PRIOR, PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING", "L1B_VALUE_PERIOD_MISMATCH"],
    ),
    (
        "R4-next-hyphen",
        "Pushes stood at 0 in next-to-last.",
        [],
        [PUSH_PRIOR, PUSH_LAST],
        ["L1B_PERIOD_WORD_MISSING", "L1B_VALUE_PERIOD_MISMATCH"],
    ),
    (
        "R4-third-spaced",
        "Pushes stood at 1 in third to last.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_PERIOD_WORD_MISSING", "L1B_VALUE_PERIOD_MISMATCH"],
    ),
    (
        "R4-third-hyphen",
        "Pushes stood at 1 in third-to-last.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_PERIOD_WORD_MISSING", "L1B_VALUE_PERIOD_MISMATCH"],
    ),
    (
        "R4-true-prior",
        "Pushes stood at 1 in next-to-last.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "R4-true-earlier",
        "Pushes stood at 3 in third to last.",
        [],
        [PUSH_EARLIER],
        [],
    ),
    # A percent word is a unit mismatch on every metric.
    (
        "R5-pct-busy",
        "Busy hours hit 6.5 pct in the slot.",
        [],
        [BUSY],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "R5-percent-busy",
        "Busy hours hit 6.5 percent in the slot.",
        [],
        [BUSY],
        ["L1B_UNIT_MISMATCH"],
    ),
    (
        "R5-per-cent-busy",
        "Busy hours hit 6.5 per cent in the slot.",
        [],
        [BUSY],
        ["L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R5-true-sign",
        "Busy hours hit 6.5% in the slot.",
        [],
        [BUSY],
        [],
    ),
    (
        "R5-percent-push",
        "Pushes hit 3 percent in earlier.",
        [],
        [PUSH_EARLIER],
        ["L1B_UNIT_MISMATCH"],
    ),
    # `both` before one label, with no `and`, states a count of two.
    (
        "R6-pushes-no-and",
        "Both pushes ended in last.",
        ["f1"],
        [],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R6-programming-no-and",
        "Both programming blocks ended in last.",
        ["f2"],
        [],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R6-true-coordination",
        "Both pushes and pulls finished in last.",
        ["f1"],
        [],
        [],
    ),
    # A clause starting with a digit ordinal is not an imperative.
    (
        "R7-ordinal-sentence",
        "2nd ship arrived in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "R7-ordinal-clause",
        "Notes were filed in last, 2nd ship arrived late.",
        ["f1"],
        [],
        [],
    ),
    (
        "R7-true-imperative",
        "Ship the spare pushes in last.",
        [],
        [PUSH_LAST],
        ["L1_ADVICE"],
    ),
    (
        "R7-true-mid-ordinal",
        "Ship the 2nd spare pushes in last.",
        [],
        [PUSH_LAST],
        ["L1_ADVICE", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # `last commit` is not the period; four more time-scope phrases.
    (
        "R8-last-commit",
        "Pushes in prior stood at 1, logged in the last commit.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "R8-last-hour",
        "Pushes stood at 1 in prior last hour.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-last-minute",
        "Pushes stood at 1 in prior last minute.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-last-minutes",
        "Pushes stood at 1 in prior last minutes.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-past-hour",
        "Pushes stood at 1 in prior past hour.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # A plus sign fires with or without a space; `up-to` reads as `up to`.
    (
        "R8-plus-space",
        "Pushes rose + 3 in earlier.",
        [],
        [PUSH_EARLIER],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-plus-tight",
        "Pushes rose +3 in earlier.",
        [],
        [PUSH_EARLIER],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-upto-hyphen",
        "Pushes grew up-to 1 in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "R8-upto-spaced",
        "Pushes grew up to 1 in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Lower-case roman stays metric-only; spaced compounds hold no ordinal.
    (
        "R8-roman-fact",
        "Pushes sat iii in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "R8-second-spaced",
        "Pushes stood at 1 in second to last.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "R8-second-hyphen",
        "Pushes stood at 1 in second-to-last.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    # `up-to-date` states no direction side.
    (
        "R8-uptodate-metric",
        "Pushes were up-to-date in prior and last.",
        [],
        [PUSH_PRIOR, PUSH_LAST],
        [],
    ),
    (
        "R8-uptodate-fact",
        "Pushes were up-to-date in last.",
        ["f1"],
        [],
        [],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10D_ROWS)
def test_t10d_review_rows(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


_THAN_PERIODS = ("earlier", "prior", "last")
_THAN_CITED: dict[tuple[str, str], list[tuple[str, float]]] = {
    ("earlier", "prior"): [PUSH_EARLIER, PUSH_PRIOR],
    ("earlier", "last"): [PUSH_EARLIER, PUSH_LAST],
    ("prior", "last"): [PUSH_PRIOR, PUSH_LAST],
}


@pytest.mark.parametrize("first", _THAN_PERIODS)
@pytest.mark.parametrize("second", _THAN_PERIODS)
@pytest.mark.parametrize("cited_key", sorted(_THAN_CITED))
def test_than_naming_uncited_periods_returns(
    first: str, second: str, cited_key: tuple[str, str]
) -> None:
    refs = _THAN_CITED[cited_key]
    outcome = run_claim(
        f"Pushes stood higher in {first} than in {second}.",
        [],
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, (first, second, cited_key)


# Ticket 10b: words hidden in hyphen compounds. Own sentences; the round
# texts stay out of the file. Table form is (row id, text, fact ids,
# refs, expected sorted codes).
T10E_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # Comparison vocabulary reads inside hyphen compounds.
    (
        "E-C1-madeup-verb",
        "Pushes florp-blorped from 3 in earlier to 1 in prior.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_COMPARISON_WORD_UNKNOWN"],
    ),
    (
        "E-C2-madeup-middle",
        "Pushes stood zorp-wobble at 3 in earlier and 1 in prior.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_COMPARISON_WORD_UNKNOWN"],
    ),
    (
        "E-C3-madeup-with",
        "Pushes showed quix-nargle with 3 in earlier and 1 in prior.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        ["L1B_COMPARISON_WORD_UNKNOWN"],
    ),
    (
        "E-C-true-known-hyphen",
        "Pushes were 3 in earlier and 1 in prior time-and-again.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        [],
    ),
    (
        "E-C-true-label-hyphen",
        "Programming moved work-programming from 4.75 in prior to 1.75 in last.",
        [],
        [PROG_PRIOR, PROG_LAST],
        [],
    ),
    (
        "E-C-true-period-hyphen",
        "Pushes fell from 1 in second-to-last to 0 in last.",
        [],
        [PUSH_PRIOR, PUSH_LAST],
        [],
    ),
    # Fact arm reads a compound ending in a direction word.
    (
        "E-D1-rose",
        "Pushes were well-rose in last.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "E-D2-climbed",
        "Pushes were bright-climbed in last.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "E-D3-prog-rose",
        "Programming was stone-rose in last.",
        ["f2"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    (
        "E-D-true-long",
        "Pushes were long-running in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "E-D-true-known",
        "Pushes were well-known in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "E-D-true-hand",
        "Pushes were hand-written in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "E-D-true-followup",
        "Pushes had a follow-up in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "E-D-true-writeup",
        "Pushes had a write-up in last.",
        ["f1"],
        [],
        [],
    ),
    # Negators count as parts of hyphen compounds, on both arms.
    (
        "E-N1-metric-never",
        "Pushes never-fell stood at 1 in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "E-N2-metric-not",
        "Pushes stood not-quite at 1 in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "E-N3-fact-not",
        "Pushes not-fell in last.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "E-N4-fact-hardly",
        "Pushes were hardly-known in last.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    (
        "E-N-true-plain",
        "Pushes stood at 1 in prior.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    (
        "E-N-true-nonzero",
        "Pushes in last were nonzero.",
        [],
        [PUSH_LAST],
        ["L1B_NEGATED_CLAIM"],
    ),
    # Approximators and comparators read a hyphen as a space.
    (
        "E-A1-over",
        "Pushes in prior stood at well-over 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "E-A2-just-over",
        "Pushes in prior stood at just-over 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "E-A3-more-than",
        "Pushes in earlier stood at far-more-than 3.",
        [],
        [PUSH_EARLIER],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "E-A-true-trailing",
        "Pushes in prior stood at 1 and the well-over notes agree.",
        [],
        [PUSH_PRIOR],
        [],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10E_ROWS)
def test_t10e_hyphen_compounds(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


def test_t10e_low_level_same_direction_stays_quiet() -> None:
    context = build_context(
        extra_facts=[
            {"id": "f9", "statement": "Pushes stayed at 1 in prior."},
        ]
    )
    outcome = run_claim("Pushes were low-level in prior.", ["f9"], [], context)
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


# Ticket 10b red-team follow-ups: punctuation around approximator and
# comparator words and numbers, underscores joining rule words, and
# hyphenated phrasal particles. Own sentences; the round texts stay out
# of the file. Table form is (row id, text, fact ids, refs, expected
# sorted codes).
T10F_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # A word in brackets, quotes or emphasis marks still reads before a number.
    (
        "F-P1-bracket-word",
        "Pushes in prior stood at [over] 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P2-quote-word",
        'Pushes in prior stood at "over" 1.',
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P3-emphasis-word",
        "Pushes in prior stood at *over* 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # A comma, colon, semicolon or slash right after the word still reads.
    (
        "F-P4-comma-word",
        "Pushes in prior stood at over, 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P5-colon-word",
        "Pushes in prior stood at over: 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P6-semicolon-word",
        "Pushes in prior stood at over; 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P7-slash-word",
        "Pushes in prior stood at over/1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # A number in brackets still reads after the word.
    (
        "F-P8-bracket-number",
        "Pushes in prior stood at over [1].",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Two- and three-word phrases read through the same punctuation.
    # The comparator words keep their own direction or negation codes;
    # the fix only adds the quantity code beside them.
    (
        "F-P9-paren-phrase",
        "Pushes in prior stood at (more than) 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P10-quoted-phrase-3",
        'Pushes in earlier stood at "no more than" 3.',
        [],
        [PUSH_EARLIER],
        ["L1B_NEGATED_CLAIM", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P11-bracket-phrase-word",
        "Pushes in prior stood at [fewer] than 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_DIRECTION_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"],
    ),
    (
        "F-P12-colon-phrase-3",
        "Pushes in prior stood at as many as: 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # A bracketed value beside its period with no approximator stays quiet.
    (
        "F-P-true-bracket-value",
        "Pushes in prior stood at [1].",
        [],
        [PUSH_PRIOR],
        [],
    ),
    # A masked clock is not the number after the approximator.
    (
        "F-P-true-clock-masked",
        "Pushes in prior stood at 1 at around 15:00.",
        [],
        [PUSH_PRIOR],
        [],
    ),
    # A direction verb before `up to` keeps the approximator quiet.
    (
        "F-P-pin-up-to-guard",
        "Pushes went up to 1 in prior.",
        [],
        [PUSH_PRIOR],
        ["L1B_DIRECTION_MISMATCH"],
    ),
]

T10G_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # An underscore reads as a space: direction words on the fact arm.
    (
        "G-U1-fact-direction",
        "Pushes were well_rose in last.",
        ["f1"],
        [],
        ["L1B_DIRECTION_MISMATCH"],
    ),
    # Negators joined or wrapped with underscores.
    (
        "G-U2-fact-negator",
        "Pushes not_fell in last.",
        ["f1"],
        [],
        ["L1B_NEGATED_CLAIM"],
    ),
    # Quantity words joined with underscores.
    (
        "G-U3-quantity-word",
        "Pushes in last were tens_of.",
        [],
        [PUSH_LAST],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Approximators joined with underscores.
    (
        "G-U4-approximator",
        "Pushes in prior stood at well_over 1.",
        [],
        [PUSH_PRIOR],
        ["L1B_UNVERIFIABLE_QUANTITY"],
    ),
    # Imperatives joined with underscores.
    (
        "G-U5-imperative",
        "Launch_the parser.",
        ["f1"],
        [],
        ["L1_ADVICE"],
    ),
    # Foreign words joined with underscores.
    (
        "G-U6-foreign",
        "Pushes in last cayeron_hard at 0.",
        [],
        [PUSH_LAST],
        ["L1_CLAIM_LANGUAGE"],
    ),
    # A cited metric id holding an underscore stays whole and quiet.
    (
        "G-U-true-metric-id",
        "Busy hours calendar.busy_hours ran 6.5.",
        [],
        [BUSY],
        [],
    ),
]

T10H_ROWS: list[tuple[str, str, list[str], list[tuple[str, float]], list[str]]] = [
    # Each spaced particle also reads hyphenated, past tenses too.
    (
        "H-Y1-lined-up",
        "Pushes lined-up in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "H-Y2-took-up",
        "Pushes took-up in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "H-Y3-showed-up",
        "Pushes showed-up in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "H-Y4-wrote-up",
        "Pushes wrote-up in last.",
        ["f1"],
        [],
        [],
    ),
    (
        "H-Y5-sat-down",
        "Pushes sat-down in last.",
        ["f1"],
        [],
        [],
    ),
    # A hyphenated particle leaves no unknown comparison word behind.
    (
        "H-Y6-metric-took-up",
        "Pushes were 3 in earlier and 1 in prior, took-up still.",
        [],
        [PUSH_EARLIER, PUSH_PRIOR],
        [],
    ),
    # `roll-up` is a hyphen particle too: no direction on the fact arm.
    (
        "H-Y7-roll-up",
        "Pushes roll-up in last.",
        ["f1"],
        [],
        [],
    ),
    # The `held`-before-a-count guard ignores case.
    (
        "H-Y8-held-capital",
        "Held 3 pushes in earlier.",
        [],
        [PUSH_EARLIER],
        [],
    ),
    (
        "H-Y9-held-lower",
        "held 3 pushes in earlier.",
        [],
        [PUSH_EARLIER],
        [],
    ),
]


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10F_ROWS)
def test_t10f_punctuation_around_quantity_words(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10G_ROWS)
def test_t10g_underscore_joined_rule_words(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


@pytest.mark.parametrize(("row_id", "text", "fact_ids", "refs", "expected"), T10H_ROWS)
def test_t10h_hyphenated_particles(
    row_id: str,
    text: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    expected: list[str],
) -> None:
    outcome = run_claim(
        text,
        fact_ids,
        [{"metric_id": metric_id, "value": value} for metric_id, value in refs],
        build_context(),
    )
    assert outcome["raised"] is None, row_id
    assert (row_id, sorted(outcome["codes"])) == (row_id, sorted(expected))


def test_t10g_fact_id_with_underscore_stays_quiet() -> None:
    context = build_context(
        extra_facts=[
            {"id": "f_my_fact", "statement": "Pushes stayed at 1 in prior."},
        ]
    )
    outcome = run_claim(
        "Pushes were low-level in prior (f_my_fact).", ["f_my_fact"], [], context
    )
    assert outcome["raised"] is None
    assert sorted(outcome["codes"]) == []


@pytest.mark.parametrize(("list_name", "word"), _DEAD_FOREIGN_ROWS)
def test_dead_foreign_entries_fire_claim_language(list_name: str, word: str) -> None:
    outcome = run_claim(
        f"Pushes in last {word} at 0.",
        [],
        [{"metric_id": "period.last.pushes", "value": 0.0}],
        build_context(),
    )
    assert outcome["raised"] is None, list_name
    assert (list_name, word, sorted(outcome["codes"])) == (
        list_name,
        word,
        ["L1_CLAIM_LANGUAGE"],
    )
