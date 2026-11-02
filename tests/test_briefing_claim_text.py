"""Ticket 10b: claim-only rule tests (D8, D9, D12, D13, D14, D21, D22)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evals.briefing_cases import base_case
from framework.briefing.claim_text import SPANISH_DIRECTION
from framework.briefing.context import MetricSnapshot
from framework.briefing.gate import evaluate_briefing


def _codes(result: Any) -> list[str]:
    return [v.code for v in result.violations]


def _fresh(profile: str = "builder") -> tuple[dict[str, Any], Any]:
    case = base_case(profile)
    return copy.deepcopy(case.briefing), case.context


def _section(briefing: dict[str, Any], section_type: str) -> dict[str, Any]:
    return next(s for s in briefing["sections"] if s["type"] == section_type)


def _metric_claim(
    text: str, refs: list[tuple[str, float]]
) -> tuple[dict[str, Any], Any]:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    claim["fact_ids"] = []
    claim["metric_refs"] = [
        {"metric_id": metric_id, "value": value} for metric_id, value in refs
    ]
    values = dict(context.metrics.values)
    for metric_id, value in refs:
        values[metric_id] = value
    return briefing, context.model_copy(
        update={"metrics": MetricSnapshot(values=values)}
    )


def _fact_claim(
    text: str,
    statement: str,
    fact_ids: list[str] | None = None,
    forbidden: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], Any]:
    from framework.schemas.core import Fact

    briefing, context = _fresh()
    fact = Fact.model_validate(
        {
            "id": "fact:local-1",
            "subject_id": "subject-1",
            "window": {
                "start": "2026-10-30T00:00:00+01:00",
                "end": "2026-10-31T12:00:00+01:00",
            },
            "statement": statement,
            "evidence": ["synthetic log"],
            "tier": "public",
        }
    )
    facts = dict(context.facts)
    facts["fact:local-1"] = fact
    context = context.model_copy(update={"facts": facts})
    if forbidden is not None:
        context = context.model_copy(update={"forbidden_raw_literals": forbidden})
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    claim["fact_ids"] = fact_ids if fact_ids is not None else ["fact:local-1"]
    claim["metric_refs"] = []
    return briefing, context


PUSH3 = [
    ("period.earlier.pushes", 3.0),
    ("period.prior.pushes", 1.0),
    ("period.last.pushes", 0.0),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pushes did not fall from 3 in earlier to 0 in last.", ["L1B_NEGATED_CLAIM"]),
        ("Pushes did not rise from 3 in earlier to 0 in last.", ["L1B_NEGATED_CLAIM"]),
        ("Pushes never rose from 3 in earlier to 0 in last.", ["L1B_NEGATED_CLAIM"]),
        ("Pushes didn't fall from 3 in earlier to 0 in last.", ["L1B_NEGATED_CLAIM"]),
        # "case" is outside the comparison vocabulary, so both fire here.
        (
            "It is not the case that pushes fell from 3 in earlier to 0 in last.",
            ["L1B_COMPARISON_WORD_UNKNOWN", "L1B_NEGATED_CLAIM"],
        ),
        # "any" and "way" are outside the vocabulary, so both fire here.
        (
            "Pushes did not, in any way, fall from 3 in earlier to 0 in last.",
            ["L1B_COMPARISON_WORD_UNKNOWN", "L1B_NEGATED_CLAIM"],
        ),
        ("No fall in pushes from 3 in earlier to 0 in last.", ["L1B_NEGATED_CLAIM"]),
        ("Pushes were not 0 in last.", ["L1B_NEGATED_CLAIM"]),
    ],
)
def test_negated_metric_claims_fire(text: str, expected: list[str]) -> None:
    if "were not 0" in text:
        refs = [("period.last.pushes", 0.0)]
    else:
        refs = [
            ("period.earlier.pushes", 3.0),
            ("period.last.pushes", 0.0),
        ]
    briefing, context = _metric_claim(text, refs)
    assert _codes(evaluate_briefing(briefing, context)) == expected, text


def test_negated_over_block_o1_pinned() -> None:
    text = "Pushes did not rise from 3 in earlier to 1 in prior and to 0 in last."
    briefing, context = _metric_claim(text, PUSH3)
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_NEGATED_CLAIM"]
    assert "state the value or direction positively" in next(
        v.message for v in result.violations
    )


def test_stated_zero_passes() -> None:
    briefing, context = _metric_claim(
        "There were no pushes in last.", [("period.last.pushes", 0.0)]
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_stated_zero_wrong_value_fires_number() -> None:
    briefing, context = _metric_claim(
        "There were no pushes in prior.", [("period.prior.pushes", 1.0)]
    )
    assert _codes(evaluate_briefing(briefing, context)) == [
        "L1B_NUMBER_WITHOUT_METRIC_REF"
    ]


def test_unnegated_passes() -> None:
    briefing, context = _metric_claim(
        "Pushes in last were 0.", [("period.last.pushes", 0.0)]
    )
    assert evaluate_briefing(briefing, context).passed is True


FRACTION_CASES = [
    "Pushes dropped by half from 3 in earlier to 0 in last.",
    "Pushes dropped by halves from 3 in earlier to 0 in last.",
    "Pushes in last were one quarter of the pushes in earlier.",
    "Pushes in last were one-third of pushes in earlier.",
    "Pushes in last stood at \u00be of the pushes in earlier.",
]
MULTIPLICATIVE_CASES = [
    "Pushes have doubled from 3 in earlier to 0 in last.",
    "Pushes in last ran tenfold the pushes in earlier.",
    "Pushes tripled from 3 in earlier to 0 in last.",
    "Pushes in last came twice a day.",
]
VAGUE_CASES = [
    "Pushes in last totalled a couple.",
    "Several pushes landed in last.",
    "Pushes in last reached dozens.",
    "Pushes in last reached a handful.",
]
RATE_CASES = [
    "Pushes in last occurred daily.",
    "Pushes in last happened hourly.",
    "Pushes in last came per day.",
]
SPOKEN_CASES = [
    "Pushes in last hit one-oh.",
    "Pushes in last reached oh-three.",
    "Pushes in last reached three point three.",
    "Twenty-one pushes landed in last.",
    "Pushes in last were 3 0.",
    "Pushes in last grew 3x.",
    "Pushes in last grew three times over.",
]
APPROXIMATOR_CASES = [
    "Pushes in last were about 4.",
    "Pushes in last were roughly 4.",
    "Pushes in last were nearly 4.",
    "Pushes in last were almost 4.",
    "Pushes in last were approximately 4.",
    "Pushes in last were circa 4.",
    "Pushes in last were just over 4.",
    "Pushes in last were just under 4.",
    "Pushes in last were up to 4.",
    "Pushes in last were over 4.",
    "Pushes in last were ~4.",
]


@pytest.mark.parametrize("text", FRACTION_CASES)
def test_fractions_fire(text: str) -> None:
    briefing, context = _metric_claim(
        text, [("period.earlier.pushes", 3.0), ("period.last.pushes", 0.0)]
    )
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


@pytest.mark.parametrize("text", MULTIPLICATIVE_CASES)
def test_multiplicatives_fire(text: str) -> None:
    briefing, context = _metric_claim(
        text, [("period.earlier.pushes", 3.0), ("period.last.pushes", 0.0)]
    )
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


@pytest.mark.parametrize("text", VAGUE_CASES)
def test_vague_words_fire(text: str) -> None:
    briefing, context = _metric_claim(text, [("period.last.pushes", 0.0)])
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


@pytest.mark.parametrize("text", RATE_CASES)
def test_rate_words_fire(text: str) -> None:
    briefing, context = _metric_claim(text, [("period.last.pushes", 0.0)])
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


@pytest.mark.parametrize("text", SPOKEN_CASES)
def test_spoken_digits_fire(text: str) -> None:
    briefing, context = _metric_claim(text, [("period.last.pushes", 0.0)])
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


@pytest.mark.parametrize("text", APPROXIMATOR_CASES)
def test_approximators_fire_before_a_number(text: str) -> None:
    briefing, context = _metric_claim(text, [("period.last.pushes", 0.0)])
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(
        evaluate_briefing(briefing, context)
    ), text


def test_approximator_needs_a_number_after_it() -> None:
    briefing, context = _fact_claim(
        "Feed items about On-device inference optimization appeared.",
        "Feed items about On-device inference optimization appeared.",
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_up_to_direction_guard_keeps_passing() -> None:
    briefing, context = _metric_claim(
        "Chat screen hours went up to 3.45 in last from 1.27 in prior.",
        [
            ("period.prior.screen_hours.Chat", 1.27),
            ("period.last.screen_hours.Chat", 3.45),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_half_with_backed_fifty_passes() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Busy list is half done at 50% in the synthetic window"
    claim["fact_ids"] = []
    claim["metric_refs"] = [{"metric_id": "calendar.busy_hours", "value": 50.0}]
    values = dict(context.metrics.values)
    values["calendar.busy_hours"] = 50.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert evaluate_briefing(briefing, context).passed is True


def test_symbols_fire() -> None:
    briefing, context = _metric_claim(
        "Pushes in last reached 3 \u2192 0.", [("period.last.pushes", 0.0)]
    )
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(evaluate_briefing(briefing, context))


def test_backtick_label_passes() -> None:
    briefing, context = _metric_claim(
        "Cancelled `iki-deep` blocks were 1 in prior.",
        [("period.prior.cancelled.iki-deep", 1.0)],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_signed_plus_fires_outside_since_last() -> None:
    briefing, context = _metric_claim(
        "Pushes in last were +3.", [("period.last.pushes", 3.0)]
    )
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(evaluate_briefing(briefing, context))


def test_signed_minus_needs_negative_ref() -> None:
    briefing, context = _metric_claim(
        "Pushes in earlier were -3.", [("period.earlier.pushes", 3.0)]
    )
    assert _codes(evaluate_briefing(briefing, context)) == [
        "L1B_NUMBER_WITHOUT_METRIC_REF"
    ]


def test_week_after_this_is_not_a_day_unit() -> None:
    briefing, context = _metric_claim(
        "Programming quality sits at 21.2 this week",
        [("screen_hours.Work/Programming", 21.1544)],
    )
    codes = _codes(evaluate_briefing(briefing, context))
    assert "L1B_UNVERIFIABLE_QUANTITY" in codes
    assert "L1B_UNIT_MISMATCH" not in codes


def test_roman_pins() -> None:
    for text in (
        "Feed items about ML and CI tooling appeared.",
        "Feed items about MDX and DIV tooling appeared.",
        "Feed items about MIX tooling appeared.",
    ):
        briefing, context = _fact_claim(text, text)
        assert evaluate_briefing(briefing, context).passed is True, text
    briefing, context = _metric_claim(
        "Pushes in last hit IV.", [("period.last.pushes", 0.0)]
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_UNVERIFIABLE_QUANTITY"]


def test_lone_v_fires_only_with_refs() -> None:
    briefing, context = _fact_claim("Version V landed.", "Version V landed.")
    assert evaluate_briefing(briefing, context).passed is True
    briefing, context = _metric_claim(
        "Pushes in last reached V.", [("period.last.pushes", 0.0)]
    )
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(evaluate_briefing(briefing, context))


def test_pronoun_i_never_roman() -> None:
    briefing, context = _fact_claim(
        "I placed push activity in last.", "I placed push activity in last."
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_digit_ordinal_before_count_noun_fires() -> None:
    briefing, context = _metric_claim(
        "Pushes in last logged their 99th push.", [("period.last.pushes", 0.0)]
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_UNVERIFIABLE_QUANTITY"]


def test_ordinals_before_other_nouns_pass() -> None:
    for text in (
        "The 1st draft followed the 2nd review",
        "Notes from the 3rd session",
    ):
        briefing, context = _fact_claim(text, text)
        assert evaluate_briefing(briefing, context).passed is True, text


def test_most_without_refs_is_negation_not_rank() -> None:
    briefing, context = _fact_claim(
        "No pushes at all were recorded in the most recent period.",
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_NEGATED_CLAIM"]


def test_clock_position_rule() -> None:
    briefing, context = _metric_claim(
        "Programming screen hours in last took 14:30.",
        [("period.last.screen_hours.Work/Programming", 1.75)],
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_UNVERIFIABLE_QUANTITY"]
    briefing, context = _fact_claim(
        "The 14:00 call ran long.", "Review notes were written in prior."
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_invalid_clock_tokenises() -> None:
    briefing, context = _metric_claim(
        "Pushes show 3:99 between earlier and last.",
        [("period.earlier.pushes", 3.0), ("period.last.pushes", 0.0)],
    )
    codes = _codes(evaluate_briefing(briefing, context))
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in codes


def test_spanish_direction_list_exact() -> None:
    assert SPANISH_DIRECTION == frozenset(
        {
            "subieron",
            "subió",
            "suben",
            "sube",
            "aumentaron",
            "aumentó",
            "aumentan",
            "aumenta",
            "crecieron",
            "creció",
            "crecen",
            "crece",
            "cayeron",
            "cayó",
            "caen",
            "cae",
            "descendieron",
            "descendió",
            "descienden",
            "desciende",
            "disminuyeron",
            "disminuyó",
            "disminuyen",
            "disminuye",
            "decrecieron",
            "decreció",
            "decrecen",
            "decrece",
            "subir",
            "aumentar",
            "crecer",
            "caer",
            "descender",
            "disminuir",
            "decrecer",
        }
    )


def test_language_arm_c_fires_on_cafe() -> None:
    briefing, context = _fact_claim(
        "Feed items about caf\u00e9 appeared.", "Feed items appeared."
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_CLAIM_LANGUAGE"]


def test_language_verbatim_exemption() -> None:
    text = "Feed items about G\u00f6del machines appeared in last."
    briefing, context = _fact_claim(text, text)
    assert evaluate_briefing(briefing, context).passed is True
    text2 = "Feed items about Arduino Uno appeared."
    briefing, context = _fact_claim(text2, text2)
    assert evaluate_briefing(briefing, context).passed is True


def test_due_removed_from_italian_numbers() -> None:
    briefing, context = _fact_claim(
        "A review was due in last.", "A review was due in last."
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_quatre_fires() -> None:
    briefing, context = _metric_claim(
        "Pushes in last hit quatre.", [("period.last.pushes", 0.0)]
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_CLAIM_LANGUAGE"]


def test_english_lookalikes_pass_language() -> None:
    briefing, context = _metric_claim(
        "Pushes have fallen from 3 in earlier to 0 in last.",
        [("period.earlier.pushes", 3.0), ("period.last.pushes", 0.0)],
    )
    assert evaluate_briefing(briefing, context).passed is True
    briefing, context = _metric_claim(
        "Six pushes landed in last.", [("period.last.pushes", 6.0)]
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_foreign_advice_fires_language() -> None:
    briefing, context = _fact_claim(
        "Exp\u00e9diez pendant la prochaine heure libre un petit changement.",
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_CLAIM_LANGUAGE"]


@pytest.mark.parametrize(
    "verb,text",
    [
        ("Go", "Go for a walk"),
        ("Try", "Try to ship"),
        ("Start", "Start with the parser"),
        ("Focus", "Focus on the parser"),
        ("Ship", "Ship one small tweak during the next free hour."),
    ],
)
def test_strong_imperatives_fire(verb: str, text: str) -> None:
    briefing, context = _fact_claim(
        text, "Pushes fell from 3 in earlier to 1 in prior and to 0 in last."
    )
    assert "L1_ADVICE" in _codes(evaluate_briefing(briefing, context)), text


@pytest.mark.parametrize(
    "text",
    [
        "Walk total is unchanged",
        "Rest with quiet music",
        "Shoulder the synthetic pack",
        "See fact:212 for the synthetic log",
        "Use of the feed fell in last.",
        "Focus dropped in last.",
        "Review comments were read.",
    ],
)
def test_imperative_guards_pass(text: str) -> None:
    if text.startswith("See fact:212"):
        briefing, context = _fact_claim(
            text,
            "Synthetic reference log filed under review",
            fact_ids=["fact:212"],
        )
    else:
        briefing, context = _fact_claim(text, text)
    assert evaluate_briefing(briefing, context).passed is True, text


def test_question_mark_fires_advice() -> None:
    briefing, context = _fact_claim(
        "Why not ship a small tweak during the next free hour?",
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_ADVICE"]


def test_deontic_phrases_fire() -> None:
    briefing, context = _fact_claim(
        "You ought to ship one small tweak during the next free hour.",
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_ADVICE"]


def test_decimal_sentence_split() -> None:
    briefing, context = _metric_claim(
        "You spent 4.75 hours on Programming in prior and 1.75 hours in last.",
        [
            ("period.prior.screen_hours.Work/Programming", 4.75),
            ("period.last.screen_hours.Work/Programming", 1.75),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_ikea_short_term_no_squash_hit() -> None:
    from framework.briefing.gate import text_check_codes

    assert text_check_codes("I like a chair", private_terms=("ikea",)) == ()


def test_squashed_boundary_counter_case() -> None:
    from framework.briefing.gate import text_check_codes

    assert text_check_codes("aquil lon chair", private_terms=("quillon",)) == ()
    assert text_check_codes("Q u i l l o n today", private_terms=("Quillon",)) == (
        "L1_PRIVATE_TERM",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The digit inside the leet spelling is itself an unbacked number.
        (
            "The notes mention Zebraf1nch today.",
            ["L1_PRIVATE_TERM", "L1B_NUMBER_WITHOUT_METRIC_REF"],
        ),
        ("The notes mention Zebraf*nch today.", ["L1_PRIVATE_TERM"]),
        ("The notes mention Zebrafinsh today.", ["L1_PRIVATE_TERM"]),
        ("The notes mention hcnifarbez today.", ["L1_PRIVATE_TERM"]),
    ],
)
def test_claim_only_private_arms_fire(text: str, expected: list[str]) -> None:
    briefing, context = _fact_claim(text, text)
    context = context.model_copy(update={"private_terms": ("Zebrafinch",)})
    assert _codes(evaluate_briefing(briefing, context)) == expected, text


def test_private_arms_do_not_touch_titles() -> None:
    from framework.briefing.gate import text_check_codes

    for text in (
        "Zebraf1nch notes",
        "Zebraf*nch notes",
        "Zebrafinsh notes",
        "hcnifarbez notes",
    ):
        assert text_check_codes(text, private_terms=("Zebrafinch",)) == (), text


def test_raw_bag_fires_claims_only() -> None:
    for text in (
        "The calendar note reads Tuesday dentist.",
        "The dentist visit is Tuesday.",
    ):
        briefing, context = _fact_claim(text, text, forbidden=("Dentist on Tuesday",))
        assert _codes(evaluate_briefing(briefing, context)) == ["L1_RAW_VALUE"], text
    from framework.briefing.gate import text_check_codes

    assert (
        text_check_codes(
            "Tuesday dentist", forbidden_raw_literals=("Dentist on Tuesday",)
        )
        == ()
    )


def test_vocabulary_eligible_passes() -> None:
    briefing, context = _metric_claim(
        "You spent 4.75 hours on Programming in prior and 1.75 hours in last.",
        [
            ("period.prior.screen_hours.Work/Programming", 4.75),
            ("period.last.screen_hours.Work/Programming", 1.75),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_vocabulary_unknown_word_fires() -> None:
    briefing, context = _metric_claim(
        "Pushes in last outshone those in prior.",
        [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
    )
    assert _codes(evaluate_briefing(briefing, context)) == [
        "L1B_COMPARISON_WORD_UNKNOWN"
    ]


def test_vocabulary_feed_labels_pinned() -> None:
    briefing, context = _metric_claim(
        "Feed fell from 3 in prior to 1 in last.",
        [("period.prior.pushes", 3.0), ("period.last.pushes", 1.0)],
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISSING"]


def test_value_period_swapped_pair_fires_once() -> None:
    for text in (
        "Pushes dropped from 1 in last to 0 in prior.",
        "Pushes were 1 in last and 0 in prior.",
    ):
        briefing, context = _metric_claim(
            text, [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)]
        )
        assert _codes(evaluate_briefing(briefing, context)) == [
            "L1B_VALUE_PERIOD_MISMATCH"
        ], text


def test_value_period_backed_pairs_pass() -> None:
    for text, refs in (
        (
            "Pushes in last were 0, down from 1 in prior.",
            [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
        ),
        ("Pushes fell from 3 in earlier to 1 in prior and to 0 in last.", PUSH3),
        (
            "Pushes were 1 and 0 in prior and last.",
            [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
        ),
        (
            "Programming screen hours were 4.75 hours in prior and 1.75 hours in last.",
            [
                ("period.prior.screen_hours.Work/Programming", 4.75),
                ("period.last.screen_hours.Work/Programming", 1.75),
            ],
        ),
    ):
        briefing, context = _metric_claim(text, refs)
        assert evaluate_briefing(briefing, context).passed is True, text


def test_cited_names_are_blanked() -> None:
    from framework.briefing.numbers import extract_number_tokens

    assert extract_number_tokens("Pushes to repo3 were 0 in last.") != ()
    briefing, context = _fact_claim(
        "Pushes to example-user/seven-tower landed in last.",
        "Pushes to example-user/seven-tower landed in last.",
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_two_fold_in_cited_name_does_not_fire() -> None:
    briefing, context = _fact_claim(
        "Pushes to example-user/two-fold happened in last.",
        "Pushes to example-user/two-fold happened in last.",
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_fact_only_direction_checks() -> None:
    briefing, context = _fact_claim(
        "Pushes fell in prior.",
        "Pushes fell from 3 in earlier to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_PERIOD_WORD_MISSING"]
    briefing, context = _fact_claim(
        "Pushes rose in last.",
        "Pushes fell from 3 in earlier to 0 in last.",
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_fact_only_gated_label_arm() -> None:
    from framework.schemas.core import Fact

    briefing, context = _fresh()
    fact = Fact.model_validate(
        {
            "id": "fact:local-2",
            "subject_id": "subject-1",
            "window": {
                "start": "2026-10-30T00:00:00+01:00",
                "end": "2026-10-31T12:00:00+01:00",
            },
            "statement": (
                "Programming screen hours fell from 4.75 in prior to 1.75 in last."
            ),
            "evidence": ["synthetic log"],
            "tier": "public",
        }
    )
    facts = dict(context.facts)
    facts["fact:local-2"] = fact
    values = dict(context.metrics.values)
    values["period.last.screen_hours.Media/Video"] = 4.0
    context = context.model_copy(
        update={"facts": facts, "metrics": MetricSnapshot(values=values)}
    )
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Video fell in last."
    claim["fact_ids"] = ["fact:local-2"]
    claim["metric_refs"] = []
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISMATCH"]


def test_fact_only_directionless_over_directionless_passes() -> None:
    briefing, context = _fact_claim(
        "Code review landed in prior.", "Code review landed in prior."
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_new_code_messages_never_echo_matches() -> None:
    from framework.briefing import gate as gate_module

    messages = gate_module._CLAIM_MESSAGES
    assert set(messages) >= {
        "L1_UNSAFE_TEXT",
        "L1_CLAIM_LANGUAGE",
        "L1B_UNVERIFIABLE_QUANTITY",
        "L1B_NEGATED_CLAIM",
        "L1B_COMPARISON_WORD_UNKNOWN",
        "L1B_UNIT_MISMATCH",
        "L1B_METRIC_LABEL_MISMATCH",
        "L1B_VALUE_PERIOD_MISMATCH",
    }
    for code, message in messages.items():
        assert code not in (
            "L1_PRIVATE_TERM",
            "L1_RAW_VALUE",
            "L1_ADVICE",
        ) or message in (
            "private term",
            "raw source value",
            "state what the data shows, with no question, instruction or suggestion",
        )
        assert "Zebrafinch" not in message
        assert "Dentist" not in message


@pytest.mark.parametrize(
    "text",
    [
        "Prs rose by 3 in the last period.",
        "Prs rose by 3 in last.",
        "Prs rose by 3 during last.",
        "Prs rose by 3 for the last period.",
        "Prs rose by 3 over the last period.",
        "Prs rose by 3 across last.",
        "Prs rose by 3 in a period.",
        "Prs rose by 3 during the period.",
        "Prs rose by 3 over a period.",
        "Prs rose by 3 across the period.",
        "Pushes rose by 1 in the earlier period.",
        "Pushes rose by 1 during earlier.",
        "Pushes rose by 1 over the earlier period.",
        "Prs rose by 3 for prior.",
        "Prs rose by 3 across the prior period.",
    ],
)
def test_since_last_containment_patterns_fire(text: str) -> None:
    from framework.briefing.claim_text import claim_text_codes

    codes = claim_text_codes(
        text,
        section_type="since_last",
        has_metric_refs=True,
        cited_refs=[("period.last.prs", 3.0)],
    )
    assert "L1B_SINCE_LAST_WORDING" in codes, text


@pytest.mark.parametrize(
    "text",
    [
        "Prs rose by 3 since the last card.",
        "Prs rose by 3 since my last card.",
        "Prs rose by 3 since the previous card.",
        "Prior prs rose by 3 since the last card.",
        "Earlier pushes rose by 1 since the last card.",
    ],
)
def test_since_last_plain_wording_passes_claim_codes(text: str) -> None:
    from framework.briefing.claim_text import claim_text_codes

    codes = claim_text_codes(
        text,
        section_type="since_last",
        has_metric_refs=True,
        cited_refs=[("period.last.prs", 3.0)],
    )
    assert "L1B_SINCE_LAST_WORDING" not in codes, text


def test_since_last_wording_ignores_other_sections() -> None:
    from framework.briefing.claim_text import claim_text_codes

    codes = claim_text_codes(
        "Prs rose by 3 in the last period.",
        section_type="working",
        has_metric_refs=True,
        cited_refs=[("period.last.prs", 3.0)],
    )
    assert "L1B_SINCE_LAST_WORDING" not in codes


def test_since_last_wording_needs_metric_refs() -> None:
    from framework.briefing.claim_text import claim_text_codes

    codes = claim_text_codes(
        "Prs rose by 3 in the last period.",
        section_type="since_last",
        has_metric_refs=False,
    )
    assert "L1B_SINCE_LAST_WORDING" not in codes
