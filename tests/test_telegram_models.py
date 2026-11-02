"""Card, proposal, callback, ruling and chart-data validation (synthetic only)."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from telegram_fake import no_sockets  # noqa: F401  (autouse fixture)

from framework.telegram.models import (
    LABEL_WRONG,
    Card,
    ChartData,
    ChartSeries,
    Proposal,
    TallyItem,
    build_callback,
    build_keyboard,
    build_ruled_keyboard,
    first_rulings,
    parse_callback,
    render_card_text,
    utf16_len,
)

MADRID_18 = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
START = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
END = datetime(2026, 11, 2, 17, 25, tzinfo=UTC)
SINCE = "Since 15:30: build time up, family call not logged."


def proposal(
    letter: str = "A",
    kind: str = "proposal",
    profile: str = "Builder",
    title: str = "Write-up draft",
    **extra: object,
) -> Proposal:
    payload: dict[str, object] = {
        "letter": letter,
        "kind": kind,
        "profile": profile,
        "title": title,
        "start": START,
        "end": END,
    }
    payload.update(extra)
    return Proposal.model_validate(payload)


def card(**extra: object) -> Card:
    payload: dict[str, object] = {
        "slot": MADRID_18,
        "since_line": SINCE,
        "proposals": [
            proposal("A", "proposal"),
            proposal("B", "proposal", profile="Disconnect", title="Family call"),
        ],
    }
    payload.update(extra)
    return Card.model_validate(payload)


def test_two_proposals_in_letter_order_ok() -> None:
    assert [p.letter for p in card().proposals] == ["A", "B"]


def test_b_before_a_rejected() -> None:
    with pytest.raises(ValueError):
        card(
            proposals=[
                proposal("B", "proposal"),
                proposal("A", "proposal"),
            ]
        )


def test_single_proposal_either_letter() -> None:
    only_a = card(proposals=[proposal("A", "proposal")])
    assert [p.letter for p in only_a.proposals] == ["A"]
    only_b = card(proposals=[proposal("B", "proposal")])
    assert [p.letter for p in only_b.proposals] == ["B"]


def test_duplicate_letters_rejected() -> None:
    with pytest.raises(ValueError):
        card(proposals=[proposal("A", "proposal"), proposal("A", "proposal")])


def test_no_proposals_rejected() -> None:
    with pytest.raises(ValidationError):
        card(proposals=[])


def test_three_proposals_rejected() -> None:
    with pytest.raises(ValidationError):
        card(
            proposals=[
                proposal("A", "proposal"),
                proposal("B", "proposal"),
                proposal("A", "proposal"),
            ]
        )


def test_kind_is_required() -> None:
    with pytest.raises(ValidationError):
        Proposal.model_validate(
            {
                "letter": "A",
                "profile": "Builder",
                "title": "Write-up draft",
                "start": START,
                "end": END,
            }
        )


def test_reason_code_with_space_rejected() -> None:
    with pytest.raises(ValueError):
        proposal("A", "fallback", reason_codes=["has space"])


def test_reason_codes_on_proposal_rejected() -> None:
    with pytest.raises(ValueError):
        proposal("A", "proposal", reason_codes=["ok.code"])


def test_fallback_may_carry_reason_codes() -> None:
    side = proposal("B", "fallback", reason_codes=["gate.ok", "x:y-z_1"])
    assert side.reason_codes == ("gate.ok", "x:y-z_1")


def test_fallback_only_card_with_since_line_rejected() -> None:
    with pytest.raises(ValueError):
        card(
            since_line=SINCE,
            proposals=[
                proposal("A", "fallback"),
                proposal("B", "fallback"),
            ],
        )


def test_fallback_only_card_with_statement_rejected() -> None:
    with pytest.raises(ValueError):
        card(
            since_line=None,
            statements=["a cited statement"],
            proposals=[
                proposal("A", "fallback"),
                proposal("B", "fallback"),
            ],
        )


def test_proposal_card_without_since_line_rejected() -> None:
    with pytest.raises(ValueError):
        card(since_line=None)


def test_blank_since_line_rejected() -> None:
    with pytest.raises(ValueError):
        card(since_line="   ")


def test_multiline_profile_rejected() -> None:
    with pytest.raises(ValueError):
        proposal("A", "proposal", profile="Build\ner")


def test_blank_title_rejected() -> None:
    with pytest.raises(ValueError):
        proposal("A", "proposal", title="  ")


def test_naive_times_rejected() -> None:
    naive = datetime(2026, 11, 2, 17, 0)
    with pytest.raises(ValidationError):
        card(slot=naive)


def test_end_before_start_rejected() -> None:
    with pytest.raises(ValueError):
        proposal("A", "proposal", start=END, end=START)


def test_caption_limit_is_a_construction_error() -> None:
    with pytest.raises(ValueError):
        card(since_line="x" * 2000)


def test_mixed_card_text_byte_for_byte() -> None:
    text = render_card_text(
        card(
            proposals=[
                proposal("A", "proposal"),
                proposal(
                    "B",
                    "fallback",
                    profile="Disconnect",
                    title="Family call",
                ),
            ]
        )
    )
    assert text.encode() == (
        b"18:00  Since 15:30: build time up, family call not logged.\n"
        b"\n"
        b"A  Builder \xc2\xb7 Write-up draft, 18:00-18:25\n"
        b"B  Disconnect \xc2\xb7 Family call, 18:00-18:25 (no checked facts)"
    )


def test_fallback_only_card_text_byte_for_byte() -> None:
    text = render_card_text(
        card(
            since_line=None,
            proposals=[
                proposal("A", "fallback"),
                proposal(
                    "B",
                    "fallback",
                    profile="Disconnect",
                    title="Family call",
                ),
            ],
        )
    )
    assert text.encode() == (
        b"18:00  No checked facts this time.\n"
        b"\n"
        b"A  Builder \xc2\xb7 Write-up draft, 18:00-18:25 (no checked facts)\n"
        b"B  Disconnect \xc2\xb7 Family call, 18:00-18:25 (no checked facts)"
    )


def test_single_b_proposal_text_byte_for_byte() -> None:
    text = render_card_text(
        card(
            proposals=[
                proposal(
                    "B",
                    "proposal",
                    profile="Disconnect",
                    title="Family call",
                ),
            ]
        )
    )
    assert text.encode() == (
        b"18:00  Since 15:30: build time up, family call not logged.\n"
        b"\n"
        b"B  Disconnect \xc2\xb7 Family call, 18:00-18:25"
    )


def test_single_a_fallback_text_byte_for_byte() -> None:
    text = render_card_text(
        card(since_line=None, proposals=[proposal("A", "fallback")])
    )
    assert text.encode() == (
        b"18:00  No checked facts this time.\n"
        b"\n"
        b"A  Builder \xc2\xb7 Write-up draft, 18:00-18:25 (no checked facts)"
    )


def test_reason_codes_never_print_on_card() -> None:
    text = render_card_text(
        card(
            proposals=[
                proposal("A", "proposal"),
                proposal(
                    "B",
                    "fallback",
                    profile="Disconnect",
                    title="Family call",
                    reason_codes=["gate.ok"],
                ),
            ]
        )
    )
    assert "gate.ok" not in text
    assert text.endswith("(no checked facts)")


def test_madrid_rendering_from_utc_input() -> None:
    text = render_card_text(card(slot=datetime(2026, 11, 2, 17, 0, tzinfo=UTC)))
    assert text.startswith("18:00  ")


def test_madrid_summer_rendering() -> None:
    text = render_card_text(card(slot=datetime(2026, 7, 1, 16, 0, tzinfo=UTC)))
    assert text.startswith("18:00  ")


def test_card_id_stable_across_offsets_and_resend() -> None:
    first = card()
    plus_two = timezone(timedelta(hours=2))
    plus_one = card(slot=datetime(2026, 11, 2, 19, 0, tzinfo=plus_two))
    assert first.card_id == plus_one.card_id
    clone = Card.model_validate(first.model_dump(mode="json"))
    assert clone.card_id == first.card_id
    assert first.card_id.startswith("card-")
    assert len(first.card_id) == 21


def test_card_id_covers_kind_and_reason_codes() -> None:
    plain = card(
        proposals=[
            proposal("A", "proposal"),
            proposal("B", "proposal", profile="Disconnect", title="Family call"),
        ]
    )
    fallback = card(
        proposals=[
            proposal("A", "proposal"),
            proposal(
                "B",
                "fallback",
                profile="Disconnect",
                title="Family call",
                reason_codes=["gate.ok"],
            ),
        ]
    )
    assert plain.card_id != fallback.card_id


def test_callback_round_trip_and_limits() -> None:
    card_id = card().card_id
    for target in ("A", "B", "neither", "wrong", "why"):
        payload = build_callback(card_id, target)
        assert len(payload.encode()) <= 64
        assert parse_callback(payload) == (card_id, target)


def test_callback_parse_strictness() -> None:
    card_id = card().card_id
    assert parse_callback("no-colon-here") is None
    assert parse_callback(f"{card_id}:A:extra") is None
    assert parse_callback(f"{card_id}:C") is None
    assert parse_callback("card-short:A") is None
    assert parse_callback(f"card-{'g' * 16}:A") is None
    assert parse_callback("") is None


def test_callback_and_reason_reject_trailing_newline() -> None:
    card_id = card().card_id
    assert parse_callback("card-0123456789abcdef\n:A") is None
    assert parse_callback(f"{card_id}:A\n") is None
    with pytest.raises(ValueError):
        proposal("B", "fallback", reason_codes=["CODE\n"])


def test_caption_limit_counts_utf16_units() -> None:
    fitting_by_points = "\U0001f600" * 480
    assert len(fitting_by_points) < 1024
    assert utf16_len(fitting_by_points) > 900
    with pytest.raises(ValueError):
        card(since_line=fitting_by_points)
    card(since_line="\U0001f600" * 400)


def test_title_prints_exactly_as_given() -> None:
    for title in ("WRITE-UP draft", "Write-up  draft"):
        text = render_card_text(
            card(proposals=[proposal("A", "proposal", title=title)])
        )
        assert f"Builder \u00b7 {title}," in text


def test_keyboard_two_proposals() -> None:
    keyboard = build_keyboard(card())
    rows: Any = keyboard["inline_keyboard"]
    assert [b["text"] for b in rows[0]] == ["Take A"]
    assert [b["text"] for b in rows[1]] == ["Take B"]
    assert [b["text"] for b in rows[2]] == ["Neither now", "Why?"]
    assert [b["text"] for b in rows[3]] == ["Something's wrong"]


def test_keyboard_one_proposal() -> None:
    keyboard = build_keyboard(card(proposals=[proposal("B", "proposal")]))
    rows: Any = keyboard["inline_keyboard"]
    assert [b["text"] for b in rows[0]] == ["Take B"]
    assert [b["text"] for b in rows[1]] == ["Neither now", "Why?"]
    assert [b["text"] for b in rows[2]] == ["Something's wrong"]


def test_ruled_keyboard_keeps_callback() -> None:
    card_id = card().card_id
    keyboard = build_ruled_keyboard(card_id, "A")
    rows: Any = keyboard["inline_keyboard"]
    assert [b["text"] for b in rows[0]] == ["\u2713 Take A"]
    assert rows[0][0]["callback_data"] == f"{card_id}:A"
    assert [b["text"] for b in rows[1]] == ["Something's wrong"]
    assert [b["text"] for b in rows[2]] == ["Why?"]


def test_wrong_button_has_own_row() -> None:
    two = card()
    one = card(proposals=[proposal("B", "proposal")])
    for candidate in (two, one):
        rows: Any = build_keyboard(candidate)["inline_keyboard"]
        wrong_rows = [row for row in rows if LABEL_WRONG in [b["text"] for b in row]]
        assert len(wrong_rows) == 1
        assert len(wrong_rows[0]) == 1
    for target in ("A", "B", "neither"):
        ruled: Any = build_ruled_keyboard(two.card_id, target)["inline_keyboard"]
        wrong_rows = [row for row in ruled if LABEL_WRONG in [b["text"] for b in row]]
        assert len(wrong_rows) == 1
        assert len(wrong_rows[0]) == 1


def test_utf16_len_counts_astral_as_two() -> None:
    assert utf16_len("abc") == 3
    assert utf16_len("\U0001f600") == 2


def _tap(source_id: str, target: str, when: datetime, eid: str):
    from framework.collectors.common import event_id
    from framework.schemas import Event

    return Event.model_validate(
        {
            "id": event_id("telegram", eid),
            "subject_id": "subject-1",
            "source": "telegram",
            "type": "app.tap",
            "time": when,
            "source_id": source_id,
            "data": {"type": "app.tap", "block_id": "card-x", "target": target},
            "tier": "private",
            "collected_at": when,
            "collector_version": "telegram@0.1.0",
        }
    )


def test_first_rulings_picks_earliest_by_time_then_id() -> None:
    t0 = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    t1 = datetime(2026, 11, 2, 18, 1, tzinfo=UTC)
    events = [
        _tap("card-x:B", "B", t1, "second"),
        _tap("card-x:A", "A", t0, "first"),
        _tap("card-x:why", "why", t1, "third"),
        _tap("card-x:wrong", "wrong", t1, "fourth"),
    ]
    assert first_rulings(events) == {"card-x": "A"}


def test_first_rulings_ignores_other_sources() -> None:
    t0 = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    event = _tap("card-x:A", "A", t0, "first")
    other = event.model_copy(update={"source": "other"})
    assert first_rulings([other]) == {}


def test_first_rulings_tie_break_by_id_in_both_orders() -> None:
    t0 = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    one = _tap("card-x:A", "A", t0, "alpha")
    two = _tap("card-x:B", "B", t0, "beta")
    ranked = sorted([("A", one), ("B", two)], key=lambda pair: pair[1].id)
    assert ranked[0][1].id != ranked[1][1].id
    assert first_rulings([one, two]) == {"card-x": ranked[0][0]}
    assert first_rulings([two, one]) == {"card-x": ranked[0][0]}


def test_chart_series_label_rules() -> None:
    ChartSeries(label="Build minutes", earlier=1.0, prior=2.0, last=3.0)
    with pytest.raises(ValueError):
        ChartSeries(label="x" * 19, earlier=1.0, prior=2.0, last=3.0)
    with pytest.raises(ValueError):
        ChartSeries(label="see http://x.example", earlier=1.0, prior=2.0, last=3.0)
    with pytest.raises(ValueError):
        ChartSeries(label="www.charts.example", earlier=1.0, prior=2.0, last=3.0)
    with pytest.raises(ValueError):
        ChartSeries(label="two\nlines", earlier=1.0, prior=2.0, last=3.0)


def test_chart_series_value_rules() -> None:
    with pytest.raises(ValueError):
        ChartSeries(label="ok", earlier=float("nan"), prior=1.0, last=1.0)
    with pytest.raises(ValueError):
        ChartSeries(label="ok", earlier=-1.0, prior=1.0, last=1.0)
    with pytest.raises(ValueError):
        ChartSeries(label="ok", earlier=2_000_000.0, prior=1.0, last=1.0)


def test_chart_data_shape_rules() -> None:
    series = ChartSeries(label="ok", earlier=1.0, prior=1.0, last=1.0)
    ChartData(
        period_labels=("One", "Two", "Three"),
        screen=(series,),
        pushes=series,
        tally=(TallyItem(label="Items", count=2),),
    )
    with pytest.raises(ValidationError):
        ChartData.model_validate(
            {
                "period_labels": ["One", "Two"],
                "screen": [series],
                "pushes": series,
                "tally": [],
            }
        )
    with pytest.raises(ValidationError):
        ChartData(
            period_labels=("One", "Two", "Three"),
            screen=tuple([series] * 9),
            pushes=series,
            tally=(),
        )
    with pytest.raises(ValidationError):
        ChartData(
            period_labels=("One", "Two", "Three"),
            screen=(),
            pushes=series,
            tally=tuple([TallyItem(label="t", count=0)] * 5),
        )


def test_chart_data_missing_ties_pushes_to_no_data() -> None:
    series = ChartSeries(label="ok", earlier=1.0, prior=1.0, last=1.0)
    minimal = ChartData(
        period_labels=("One", "Two", "Three"),
        screen=(),
        pushes=None,
        tally=(),
        missing=("screen", "pushes + PRs"),
    )
    assert minimal.pushes is None
    with pytest.raises(ValidationError):
        ChartData(
            period_labels=("One", "Two", "Three"),
            screen=(),
            pushes=None,
            tally=(),
        )
    with pytest.raises(ValidationError):
        ChartData(
            period_labels=("One", "Two", "Three"),
            screen=(series,),
            pushes=series,
            tally=(),
            missing=("pushes + PRs",),
        )


def test_chart_data_missing_refuses_unknown_entry() -> None:
    series = ChartSeries(label="ok", earlier=1.0, prior=1.0, last=1.0)
    with pytest.raises(ValidationError):
        ChartData.model_validate(
            {
                "period_labels": ["One", "Two", "Three"],
                "screen": [series],
                "pushes": series,
                "tally": [],
                "missing": ["screen tomorrow"],
            }
        )
