"""Slice A, AT-A6: the rater page works offline from a file."""

import json
import re

import pytest

from framework.rater.__main__ import main as rater_main
from framework.rater.page import render_page
from tests.test_rater_pack import (
    _briefing,
    _card,
    _claim,
    _deliver,
    _env,
    _record,
    _record_facts,
    _rows,
    slot_at,
)

CSP = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'\">"
)

ITEMS = (
    (
        "item-0001",
        "Pushes were 2 in the last period.",
        ("pushes in the last period: 2",),
    ),
    (
        "item-0002",
        "Paper lists hold tasks and picnic lists hold dates.",
        ("Paper lists hold tasks and picnic lists hold dates.",),
    ),
)


def _page() -> str:
    return render_page("pack-abc123", "deadbeef" * 8, ITEMS)


def test_csp_meta_present() -> None:
    assert CSP in _page()


def test_no_network_or_navigation_surface() -> None:
    page = _page()
    for token in (
        "http://",
        "https://",
        "src=",
        "href=",
        "<form",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
    ):
        assert token not in page, token


def test_pack_page_holds_no_store_secrets(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Build a pack from a made-up store; the page must hold none of its ids."""
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-blind",
        "builder",
        slot,
        {
            "overall_state": [
                _claim(
                    "c-blind-1",
                    "Pushes were 2 in the last period.",
                    ("f-blind-1",),
                    (("period.last.pushes", 2.0),),
                )
            ]
        },
    )
    proposal_key = _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f-blind-1": "Made-up backing line."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    out = tmp_path / "pack"
    code = rater_main(
        [
            "pack",
            "--db",
            str(db),
            "--out-dir",
            str(out),
            "--seed",
            "7",
            "--cut",
            "2026-11-04T18:00:00+01:00",
        ]
    )
    capsys.readouterr()
    assert code == 0
    page = next(out.glob("*.html")).read_text(encoding="utf-8")
    key = json.loads(next(out.glob("*.key.json")).read_text(encoding="utf-8"))
    item = next(iter(key["items"].values()))
    secrets = [
        item["card_id"],
        item["slot"],
        slot.strftime("%H:%M"),
        "builder",
        "Builder",
        item["model"],
        item["effort"],
        proposal_key,
        "c-blind-1",
        "f-blind-1",
        "Draft the weekly notes",
        "Rest with music",
    ]
    for token in secrets:
        assert token and token not in page, token


def test_counter_and_start_count_match_items() -> None:
    page = _page()
    assert "2 sentences" in page
    assert "1 of 2" in page


def test_storage_fallback_and_data_contract() -> None:
    page = _page()
    assert "localStorage" in page
    assert "try" in page
    match = re.search(
        r'<script type="application/json" id="rater-data">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload["pack_id"] == "pack-abc123"
    assert [item["item_id"] for item in payload["items"]] == ["item-0001", "item-0002"]
    assert payload["items"][0]["evidence"] == ["pushes in the last period: 2"]
    assert "in-memory" in page or "memory" in page


def test_buttons_are_ordinary_with_visible_text() -> None:
    page = _page()
    for label in ("Yes", "No", "Can't tell", "Back"):
        assert label in page, label
    assert page.count("<button") >= 4


def test_start_screen_explains_periods() -> None:
    page = _page()
    assert "three back-to-back 24-hour periods" in page
    assert "earlier" in page and "prior" in page and "last" in page
    assert "most recent" in page
    assert "all three together" in page
    assert "the number on the previous card and the number on this card" in page
    assert "covers different hours" in page


def test_start_screen_describes_since_last_values() -> None:
    page = _page()
    assert (
        "A line about a change since the previous card shows the number on the "
        "previous card and the number on this card, then the change." in page
    )
    assert (
        "Each card counts its own three periods, so the same period name on two "
        "cards covers different hours." in page
    )


def test_start_screen_says_what_the_rater_judges() -> None:
    page = _page()
    assert "comes from a card" in page
    assert "whether the sentence follows from that data" in page
    assert "not whether it is a good idea" in page


def test_answer_meanings_are_disjoint() -> None:
    page = _page()
    assert "backs up everything the sentence says about it" in page
    assert "says something different" in page
    assert "cannot decide from what is shown" in page


def test_sentence_stands_out_from_evidence() -> None:
    page = _page()
    assert "font-weight" in page
    assert "Cited data" in page
    assert page.index('class="sentence"') < page.index("Cited data")


def test_answer_buttons_are_full_width_and_equal() -> None:
    page = _page()
    assert "width:100%" in page


def test_preview_note_and_noscript() -> None:
    page = _page()
    assert 'id="preview-note"' in page
    assert "instead of a preview" in page
    assert "<noscript>" in page


def test_reload_progress_and_copy_status() -> None:
    page = _page()
    assert "already answered" in page
    assert "Continue" in page
    assert "chosen" in page
    assert "Back to the sentences" in page
    assert 'id="copy-status"' in page
    assert "Select the text" in page
