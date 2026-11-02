"""Ticket 13 slice 4: the rehearsal on a scratch database (made-up data)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.cycle.orchestrator import FactsChildResult, Seams
from framework.cycle.rehearse import next_rehearsal_slot
from framework.cycle.slot_ledger import SlotLedger
from framework.proposal.core import WonderResponse
from framework.schemas.events import AppTapData
from framework.store.store import EventStore
from framework.telegram.client import TelegramConflict
from framework.telegram.service import RULING_WINDOW_START

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-a"


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    terms = tmp_path / "terms"
    terms.mkdir(exist_ok=True)
    (terms / "deny-terms.txt").write_text("zzforbiddenzz\n")
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(terms))
    monkeypatch.delenv("IKIGAI_COMMITMENTS_FILE", raising=False)
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _DownFacts:
    def __call__(self, **kwargs: Any) -> FactsChildResult:
        return FactsChildResult("MODEL_DOWN", None, None)


class _GatePassWonder:
    """A fake whose draft mirrors the passing shape over the rehearsal seeds."""

    transport = "muse"
    transport_version: str | None = "synthetic 1.0"
    harness_rules_file: bool | None = None

    def complete(self, request: Any) -> WonderResponse:
        schema = request.response_schema
        properties = schema["properties"]
        cids = properties["commitment_id"]["enum"]
        claim_schema = properties["overall_state"]["items"]["properties"]
        fact_ids = claim_schema.get("fact_ids", {}).get("items", {}).get("enum", [])
        metric_ids = (
            claim_schema.get("metric_refs", {}).get("items", {}).get("enum", [])
        )
        assert fact_ids, "the gate needs a fact to cite"
        assert "period.last.pushes" in metric_ids
        second_fact = fact_ids[1] if len(fact_ids) > 1 else fact_ids[0]
        return WonderResponse(
            text=json.dumps(
                {
                    "commitment_id": cids[0],
                    "overall_state": [
                        {
                            "text": "The recorded push activity stands as noted",
                            "fact_ids": [fact_ids[0]],
                            "metric_refs": [],
                        }
                    ],
                    "working": [
                        {
                            "text": "The recorded session stands as noted",
                            "fact_ids": [second_fact],
                            "metric_refs": [],
                        }
                    ],
                    "not_working": [],
                }
            ),
            model_reported="synthetic",
            latency_ms=7,
            finish_reason="stop",
            prompt_tokens=11,
            completion_tokens=13,
            reasoning_tokens=None,
        )


class _TapTelegram:
    """A fake transport that taps A on the sent card at the first poll."""

    def __init__(self) -> None:
        self.card_id: str | None = None
        self.sent = 0
        self.polled = 0

    def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        caption: str,
        markup: dict[str, Any],
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        data = markup["inline_keyboard"][0][0]["callback_data"]
        self.card_id = str(data).split(":")[0]
        self.sent += 1
        return {"message_id": 7}

    def get_updates(self, offset: Any, long_poll_s: int) -> list[dict[str, Any]]:
        self.polled += 1
        assert self.card_id is not None
        return [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "synthetic-query-1",
                    "from": {"id": 424242, "is_bot": False},
                    "message": {
                        "message_id": 7,
                        "chat": {"id": 424242, "type": "private"},
                        "date": 1790985600,
                        "text": "card",
                    },
                    "chat_instance": "synthetic-instance",
                    "data": f"{self.card_id}:A",
                },
            }
        ]

    def call(
        self,
        method: str,
        payload: dict[str, Any],
        timeout_s: float = 10.0,
        attempts: int = 2,
    ) -> bool:
        return True


def test_next_rehearsal_slot_is_next_1530() -> None:
    assert next_rehearsal_slot(datetime(2026, 11, 2, 13, 0, tzinfo=MADRID)) == datetime(
        2026, 11, 2, 15, 30, tzinfo=MADRID
    )
    assert next_rehearsal_slot(
        datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    ) == datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    assert next_rehearsal_slot(
        datetime(2026, 11, 2, 21, 30, tzinfo=MADRID)
    ) == datetime(2026, 11, 3, 15, 30, tzinfo=MADRID)
    assert next_rehearsal_slot(
        datetime(2026, 11, 2, 15, 31, tzinfo=MADRID)
    ) == datetime(2026, 11, 3, 15, 30, tzinfo=MADRID)


def test_rehearse_refuses_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    db = tmp_path / "taken.db"
    db.write_bytes(b"existing")
    clock = _Clock(datetime(2026, 11, 2, 13, 0, tzinfo=MADRID))
    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=_TapTelegram(),
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    assert rehearse(db_path=db, seams=seams) == 2
    assert "code=FILE_EXISTS" in capsys.readouterr().out


def test_rehearse_sends_and_tap_reaches_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    now = datetime(2026, 11, 2, 13, 0, tzinfo=MADRID)
    clock = _Clock(now)
    telegram = _TapTelegram()
    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=telegram,
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 0
    out = capsys.readouterr().out
    lines = out.strip().split("\n")
    assert "poller" in lines[0].lower()
    slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    ledger = SlotLedger(db)
    card_id = ledger.latest_card_id(slot)
    assert card_id is not None
    assert lines[-1] == f"card={card_id}"
    assert telegram.sent == 1
    rows = ledger.slot_cards_for_card(card_id)
    assert {row.profile_id for row in rows} == {"builder", "disconnect"}
    reader = EventStore(db_path=db)
    try:
        taps = reader.events_between(
            SUBJECT,
            RULING_WINDOW_START,
            now + timedelta(days=1),
            types=["app.tap"],
        )
    finally:
        reader.close()
    got: list[tuple[str, str]] = []
    for tap in taps:
        assert isinstance(tap.data, AppTapData)
        got.append((tap.data.block_id, tap.data.target))
    assert got == [(card_id, "A")]
    commitments_path = db.parent / (db.stem + ".commitments.json")
    assert commitments_path.exists()
    payload = json.loads(commitments_path.read_text())
    assert len(payload) == 4
    assert all(str(item["title"]).startswith("TEST") for item in payload)
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for item in payload:
        by_profile.setdefault(item["profile_id"], []).append(item)
    assert len(by_profile["builder"]) == 2
    assert len(by_profile["disconnect"]) == 2
    assert sum(1 for item in by_profile["disconnect"] if item["kind"] == "music") == 1


def test_rehearse_conflict_exits_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    clock = _Clock(datetime(2026, 11, 2, 13, 0, tzinfo=MADRID))

    class _ConflictTelegram(_TapTelegram):
        def get_updates(self, offset: Any, long_poll_s: int) -> list[Any]:
            raise TelegramConflict("synthetic 409")

    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=_ConflictTelegram(),
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 3
    out = capsys.readouterr().out
    assert "code=CONFLICT" in out
    slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    card_id = SlotLedger(db).latest_card_id(slot)
    assert card_id is not None
    assert out.strip().split("\n")[-1] == f"card={card_id}"


def test_rehearse_no_tap_exits_5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    clock = _Clock(datetime(2026, 11, 2, 13, 0, tzinfo=MADRID))

    class _QuietTelegram(_TapTelegram):
        def get_updates(self, offset: Any, long_poll_s: int) -> list[Any]:
            return []

    def _sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)

    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=_QuietTelegram(),
        clock=clock,
        sleep=_sleep,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 5
    out = capsys.readouterr().out
    assert "code=NO_TAP" in out
    slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    card_id = SlotLedger(db).latest_card_id(slot)
    assert card_id is not None
    assert out.strip().split("\n")[-1] == f"card={card_id}"


def test_rehearse_at_2330_still_sends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 23:30 rehearsal is exempt from the night cut-off and still sends."""
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    start = datetime(2026, 11, 2, 23, 30, tzinfo=MADRID)
    clock = _Clock(start)
    telegram = _TapTelegram()
    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=telegram,
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 0
    out = capsys.readouterr().out
    assert "code=RULING_SEEN" in out
    assert telegram.sent == 1
    slot = datetime(2026, 11, 3, 15, 30, tzinfo=MADRID)
    card_id = SlotLedger(db).latest_card_id(slot)
    assert card_id is not None
    assert out.strip().split("\n")[-1] == f"card={card_id}"


def test_rehearse_no_tap_waits_the_full_ten_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The no-tap exit comes after 10 minutes on the fake clock, not before."""
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    start = datetime(2026, 11, 2, 13, 0, tzinfo=MADRID)
    clock = _Clock(start)

    class _QuietTelegram(_TapTelegram):
        def get_updates(self, offset: Any, long_poll_s: int) -> list[Any]:
            self.polled += 1
            return []

    telegram = _QuietTelegram()

    def _sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)

    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=telegram,
        clock=clock,
        sleep=_sleep,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 5
    assert "code=NO_TAP" in capsys.readouterr().out
    assert clock.now - start == timedelta(minutes=10)
    assert telegram.polled == 121


def test_rehearse_seeds_sit_at_set_distances_from_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.rehearse import rehearse

    _env(monkeypatch, tmp_path)
    clock = _Clock(datetime(2026, 11, 2, 13, 0, tzinfo=MADRID))
    telegram = _TapTelegram()
    seams = Seams(
        facts=_DownFacts(),
        wonder=lambda terms, deadline: _GatePassWonder(),  # type: ignore[return-value]
        telegram=telegram,
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    db = tmp_path / "scratch.db"
    assert rehearse(db_path=db, seams=seams) == 0
    capsys.readouterr()
    slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    reader = EventStore(db_path=db)
    try:
        rows = {
            event.id: event
            for event in reader.events_between(
                SUBJECT,
                RULING_WINDOW_START,
                slot + timedelta(days=1),
            )
            if event.id.startswith("rehearse-")
        }
    finally:
        reader.close()
    assert set(rows) == {
        "rehearse-push-1",
        "rehearse-push-2",
        "rehearse-pr-1",
        "rehearse-screen-1",
    }
    assert rows["rehearse-push-1"].time == slot - timedelta(hours=4)
    assert rows["rehearse-push-2"].time == slot - timedelta(hours=3)
    assert rows["rehearse-pr-1"].time == slot - timedelta(minutes=70)
    assert rows["rehearse-screen-1"].time == slot - timedelta(hours=2)
