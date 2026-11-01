"""Ticket 8: number-token masking/extraction arms (one test per arm)."""

from decimal import Decimal

import pytest

from framework.briefing.numbers import extract_number_tokens


def _values(text: str) -> tuple[Decimal, ...]:
    return tuple(t.value for t in extract_number_tokens(text))


def test_iso_dates_masked() -> None:
    assert _values("Reviewed on 2026-10-31 at 14:30") == ()


def test_day_first_dates_masked() -> None:
    assert _values("Due 31/10/2026 soon") == ()


def test_month_name_dates_masked() -> None:
    assert _values("Notes from Oct 30 look steady") == ()
    assert _values("Review dated 31 Oct 2026 passed") == ()


def test_bare_year_is_a_token_full_dates_only() -> None:
    assert _values("In 2026 we shipped the trial") == (Decimal(2026),)
    assert _values("Seen 2026 units") == (Decimal(2026),)
    assert _values("Review of 2026 closed") == (Decimal(2026),)
    assert _values("Dated 31 Oct 2026 today") == ()


def test_clock_times_and_ranges_masked() -> None:
    assert _values("from 13:00 to 23:30") == ()
    assert _values("Call at 2:30 pm today") == ()


def test_word_durations_are_extracted() -> None:
    assert _values("Walked 25 min today") == (Decimal(25),)
    assert _values("Averaged 7.5 h") == (Decimal("7.5"),)


def test_identifiers_masked_only_when_cited() -> None:
    known = {"brf_01", "claim-2", "v14"}
    assert (
        tuple(t.value for t in extract_number_tokens("See brf_01 and claim-2", known))
        == ()
    )
    assert tuple(t.value for t in extract_number_tokens("Tier v14 passed", known)) == ()
    assert _values("See brf_01 and claim-2") == (Decimal(1), Decimal(2))
    assert _values("Tier v14 passed") == (Decimal(14),)


def test_dotted_versions_are_tokens() -> None:
    assert _values("Version 1.2.3 ships") == (Decimal("1.2"), Decimal(3))
    assert _values("1.2.3 hours.") == (Decimal("1.2"), Decimal(3))


def test_reference_forms_masked_only_when_cited() -> None:
    assert (
        tuple(
            t.value
            for t in extract_number_tokens("See fact:212 for the log", {"fact:212"})
        )
        == ()
    )
    assert _values("See fact:212 for the log") == (Decimal(212),)


def test_ordinals_masked() -> None:
    assert _values("The 1st draft and 2nd review") == ()


def test_thousands_commas_parsed() -> None:
    assert _values("Counted 1,234 steps") == (Decimal(1234),)


def test_percent_means_whole_value() -> None:
    (token,) = extract_number_tokens("Done at 50% completion")
    assert token.value == Decimal(50)
    assert token.places == 0


def test_spelled_out_two_to_ninety_need_no_unit() -> None:
    assert _values("Seven hours of sleep") == (Decimal(7),)
    assert _values("Slept nine hours.") == (Decimal(9),)
    assert _values("Rest one of the days") == ()
    assert _values("Walked twenty steps today") == (Decimal(20),)
    assert _values("Down fifty percent") == (Decimal(50),)
    assert _values("Seven slept") == (Decimal(7),)
    assert _values("Twenty birds") == (Decimal(20),)
    assert _values("Fifty birds") == (Decimal(50),)
    assert _values("Logged one hour") == (Decimal(1),)
    assert _values("Logged one-hour session") == (Decimal(1),)


def test_spelled_out_one_needs_the_widened_list() -> None:
    for text in (
        "Logged one push",
        "Logged one pushes",
        "Logged one commit",
        "Logged one task",
        "Logged one call",
        "Logged one card",
        "Logged one pr",
        "Logged one event",
        "Logged one block",
        "Logged one item",
        "Logged one times",
        "Logged one day",
        "Logged one-hour session",
        "Logged one-day plan",
    ):
        assert _values(text) == (Decimal(1),), text
    assert _values("Rest one of the days") == ()
    assert _values("Twenty-one pages read") == (Decimal(20),)


def test_spelled_out_scale_words_are_unconditional() -> None:
    assert _values("Zero pushes today") == (Decimal(0),)
    assert _values("A thousand steps walked") == (Decimal(1000),)
    assert _values("Ten thousand steps walked") == (Decimal(10), Decimal(1000))
    assert _values("Eight and a half hours slept") == (Decimal(8),)
    assert _values("A dozen eggs") == (Decimal(12),)
    assert _values("A hundred days") == (Decimal(100),)


def test_spelled_word_boundaries() -> None:
    for text in ("often late", "weight noted", "tonight late", "stone cold"):
        assert _values(text) == (), text
    assert _values("someone called") == ()
    assert _values("none left") == ()
    assert _values("Nineteen birds") == (Decimal(19),)


def test_unmasked_dates_and_times_with_measure_words() -> None:
    assert _values("Logged May 2000 steps in the synthetic trial") == (Decimal(2000),)
    assert _values("Logged May 2000 STEPS in the synthetic trial") == (Decimal(2000),)
    assert _values("Range 12/25/2000 steps done") == (
        Decimal(12),
        Decimal(25),
        Decimal(2000),
    )
    assert _values("Range 12/25/2000 Steps done") == (
        Decimal(12),
        Decimal(25),
        Decimal(2000),
    )
    assert _values("Logged 10:30 steps today") == (Decimal(10), Decimal(30))
    assert _values("Logged 10:30 STEPS today") == (Decimal(10), Decimal(30))
    assert _values("Slept 8:30 h last night") == (Decimal(8), Decimal(30))


def test_singular_count_after_time_keeps_the_mask() -> None:
    assert _values("Join the 14:00 call today") == ()
    assert _values("Join the 18:00 block today") == ()
    assert _values("Join the May 9 call today") == ()
    assert _values("Logged 10:30 calls today") == (Decimal(10), Decimal(30))
    assert _values("Logged May 2000 tasks today") == (Decimal(2000),)


def test_glued_units_are_tokens() -> None:
    assert _values("Walked 45min today") == (Decimal(45),)
    assert _values("Slept 2h last night") == (Decimal(2),)


def test_month_names_match_only_capitalized() -> None:
    assert _values("Planned for May 9") == ()
    assert _values("You may 9 hours rest.") == (Decimal(9),)


def test_time_before_duration_word_is_a_token() -> None:
    assert _values("Slept 8:30 hours.") == (Decimal(8), Decimal(30))
    assert _values("On 2026-10-30 at 13:30") == ()
    assert _values("Call lasted 7 min today") == (Decimal(7),)


def test_hyphen_is_separator_after_digit() -> None:
    assert _values("Range 3-5 passed") == (Decimal(3), Decimal(5))


def test_hyphen_is_minus_after_space() -> None:
    (token,) = extract_number_tokens("Energy is down -5 from last time")
    assert token.value == Decimal(-5)


def test_hyphen_after_letter_is_separator() -> None:
    assert _values("well-known 5 stars") == (Decimal(5),)


def test_token_places_recorded() -> None:
    (token,) = extract_number_tokens("Quality sits at 21.20 this week")
    assert token.value == Decimal("21.20")
    assert token.places == 2


def test_left_to_right_order_and_offsets() -> None:
    tokens = extract_number_tokens("Scored 42 points with 7 faults")
    assert [t.value for t in tokens] == [Decimal(42), Decimal(7)]
    assert tokens[0].start < tokens[1].start


@pytest.mark.parametrize(
    ("word", "value"),
    [
        ("two", 2),
        ("three", 3),
        ("four", 4),
        ("five", 5),
        ("six", 6),
        ("seven", 7),
        ("eight", 8),
        ("nine", 9),
        ("ten", 10),
        ("eleven", 11),
        ("twelve", 12),
        ("thirteen", 13),
        ("fourteen", 14),
        ("fifteen", 15),
        ("sixteen", 16),
        ("seventeen", 17),
        ("eighteen", 18),
        ("nineteen", 19),
        ("twenty", 20),
        ("thirty", 30),
        ("forty", 40),
        ("fifty", 50),
        ("sixty", 60),
        ("seventy", 70),
        ("eighty", 80),
        ("ninety", 90),
        ("zero", 0),
        ("hundred", 100),
        ("thousand", 1000),
        ("million", 1000000),
        ("dozen", 12),
    ],
)
def test_every_spelled_word_is_a_token(word: str, value: int) -> None:
    assert _values(f"{word} of the") == (Decimal(value),), word
    assert _values(f"{word.upper()} of the") == (Decimal(value),), word


def test_one_hyphen_joins_only_listed_words() -> None:
    for text in ("one-hour shift", "one-day plan", "one-minute call"):
        assert _values(text) == (Decimal(1),), text
    for text in (
        "one-off deal",
        "one-on-one chat",
        "one-time offer",
        "one-way street",
        "one-sided view",
        "one-to-one session",
    ):
        assert _values(text) == (), text
    assert _values("A one-on-one call moved") == ()
    assert _values("A one-to-one call moved") == ()
    assert _values("Twenty-one hours logged") == (Decimal(20),)
    assert _values("Twenty-one pages read") == (Decimal(20),)
    assert _values("one hour") == (Decimal(1),)
    assert _values("one-hour") == (Decimal(1),)
    assert _values("one-day") == (Decimal(1),)
    assert _values("one-off") == ()
    assert _values("one-on-one") == ()


def test_every_date_and_time_form_unmasks_before_a_unit() -> None:
    assert _values("Logged 2026-10-31 steps today") == (
        Decimal(2026),
        Decimal(10),
        Decimal(31),
    )
    assert _values("Logged Oct 30 steps today") == (Decimal(30),)
    assert _values("Logged Oct 30 STEPS today") == (Decimal(30),)
    assert _values("Logged 30 Oct steps today") == (Decimal(30),)
    assert _values("Planned for 2026-10-31 call today") == ()
