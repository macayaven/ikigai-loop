"""Ticket 13 slice 2: slot ledger tables, writes and state reading (made-up data)."""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from framework.cycle.slot_ledger import (
    LedgerWriteBlocked,
    SlotCardRow,
    SlotLedger,
)

MADRID = ZoneInfo("Europe/Madrid")


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def ledger_at(tmp_path: Path) -> SlotLedger:
    return SlotLedger(tmp_path / "cycle.db")


def card_row(
    card_id: str,
    letter: str,
    slot: datetime,
    profile: str = "builder",
    kind: str = "proposal",
    pick: str | None = "b-1",
) -> SlotCardRow:
    return SlotCardRow(
        card_id=card_id,
        letter=letter,
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        profile_id=profile,
        commitment_id="b-1" if profile == "builder" else "d-1",
        kind=kind,
        policy_pick=pick,
        policy_alternative=None,
    )


def send_delivered(ledger: SlotLedger, slot: datetime, card_id: str) -> None:
    ledger.append_step(slot, "send_intent", "intent", 0.1, card_id, {"try": "1"})
    ledger.append_step(slot, "send", "delivered", 0.2, card_id, {"message_id": "7"})


def test_detail_builds_sorted_pairs_and_refuses_whitespace(
    tmp_path: Path,
) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("13:30")
    ledger.append_step(slot, "start", "ok", 0.0, None, {"forced": "1", "cycle": "abc"})
    (row,) = ledger.rows_for_slot(slot)
    assert row.detail == "cycle=abc forced=1"
    with pytest.raises(ValueError):
        ledger.append_step(slot, "start", "ok", 0.0, None, {"note": "has space"})
    with pytest.raises(ValueError):
        ledger.append_step(slot, "start", "ok", 0.0, None, {"has space": "1"})


def test_all_five_tables_refuse_update_and_delete(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("13:30")
    ledger.append_step(slot, "start", "ok", 0.0, None, {"as_of": "x"})
    ledger.save_slot_cards((card_row("card-aaa", "A", slot),))
    ledger.save_card_payload("card-aaa", '{"a":1}', '{"b":2}')
    ledger.append_learner_state(slot, '{"rulings_seen":0}')
    ledger.append_local_retry(slot, "builder", 1, "exit 1", 5, 1, "masked")
    raw = sqlite3.connect(tmp_path / "cycle.db")
    try:
        for table in (
            "slot_ledger",
            "slot_cards",
            "slot_card_payloads",
            "learner_states",
            "local_start_retries",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                raw.execute(f"UPDATE {table} SET rowid = rowid")
            with pytest.raises(sqlite3.IntegrityError):
                raw.execute(f"DELETE FROM {table}")
    finally:
        raw.close()


def test_rows_for_slot_are_isolated_and_ordered(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    first, second = slot_at("13:30"), slot_at("15:30")
    ledger.append_step(first, "start", "ok", 0.0, None, None)
    ledger.append_step(second, "start", "ok", 0.0, None, None)
    ledger.append_step(first, "done", "ok", 1.0, "card-aaa", None)
    rows = ledger.rows_for_slot(first)
    assert [row.step for row in rows] == ["start", "done"]
    assert ledger.rows_for_slot(second)[0].step == "start"


def test_latest_start_as_of_wins(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("13:30")
    early = slot_at("13:05")
    late = slot_at("13:06")
    ledger.append_step(slot, "start", "ok", 0.0, None, {"as_of": early.isoformat()})
    ledger.append_step(slot, "start", "ok", 0.0, None, {"as_of": late.isoformat()})
    assert ledger.latest_start_as_of(slot) == late
    assert ledger.latest_start_as_of(slot_at("15:30")) is None


def test_send_state_from_rows(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    assert ledger.send_state(slot_at("13:30")) == "none"
    cases = [
        ("intent_open", [("send_intent", "intent")]),
        ("delivered", [("send_intent", "intent"), ("send", "delivered")]),
        (
            "DELIVERY_UNKNOWN",
            [("send_intent", "intent"), ("send", "DELIVERY_UNKNOWN")],
        ),
        (
            "SEND_NOT_SENT",
            [("send_intent", "intent"), ("send", "SEND_NOT_SENT")],
        ),
        (
            "SEND_REFUSED",
            [("send_intent", "intent"), ("send", "SEND_REFUSED")],
        ),
        (
            "intent_open",
            [
                ("send_intent", "intent"),
                ("send", "SEND_NOT_SENT"),
                ("send_intent", "intent"),
            ],
        ),
    ]
    for day_offset, (wanted, steps) in enumerate(cases):
        slot = slot_at("13:30", day=3 + day_offset)
        for step, outcome in steps:
            ledger.append_step(slot, step, outcome, 0.1, "card-x", None)
        assert ledger.send_state(slot) == wanted


def test_disconnect_count_covers_delivered_and_unknown(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    day = date(2026, 11, 2)
    delivered = slot_at("13:30")
    ledger.save_slot_cards((card_row("card-a", "A", delivered, "builder"),))
    ledger.save_slot_cards((card_row("card-a", "B", delivered, "disconnect"),))
    send_delivered(ledger, delivered, "card-a")
    unknown = slot_at("15:30")
    ledger.save_slot_cards((card_row("card-b", "A", unknown, "builder"),))
    ledger.save_slot_cards((card_row("card-b", "B", unknown, "disconnect"),))
    ledger.append_step(unknown, "send_intent", "intent", 0.1, "card-b", None)
    ledger.append_step(unknown, "send", "DELIVERY_UNKNOWN", 0.1, "card-b", None)
    refused = slot_at("18:00")
    ledger.save_slot_cards((card_row("card-c", "B", refused, "disconnect"),))
    ledger.append_step(refused, "send_intent", "intent", 0.1, "card-c", None)
    ledger.append_step(refused, "send", "SEND_NOT_SENT", 0.1, "card-c", None)
    ledger.save_slot_cards((card_row("card-open", "B", refused, "disconnect"),))
    ledger.append_step(refused, "send_intent", "intent", 0.1, "card-open", None)
    builder_only = slot_at("20:30")
    ledger.save_slot_cards((card_row("card-d", "A", builder_only, "builder"),))
    send_delivered(ledger, builder_only, "card-d")
    forced = slot_at("22:30")
    ledger.save_slot_cards((card_row("card-e", "B", forced, "disconnect"),))
    ledger.append_step(forced, "send_intent", "intent", 0.1, "card-e", None)
    ledger.append_step(forced, "send", "delivered", 0.1, "card-e", {"forced": "1"})
    other_day = slot_at("15:30", day=3)
    ledger.save_slot_cards((card_row("card-f", "B", other_day, "disconnect"),))
    send_delivered(ledger, other_day, "card-f")
    assert ledger.disconnect_count(day) == 4
    assert ledger.disconnect_count(date(2026, 11, 3)) == 1


def test_latest_delivered_card_before_slot(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    first, second = slot_at("13:30"), slot_at("15:30")
    send_delivered(ledger, first, "card-first")
    ledger.append_step(second, "send_intent", "intent", 0.1, "card-lost", None)
    ledger.append_step(second, "send", "DELIVERY_UNKNOWN", 0.1, "card-lost", None)
    assert ledger.latest_delivered_card_id(slot_at("18:00")) == "card-first"
    assert ledger.latest_delivered_card_id(second) == "card-first"
    assert ledger.latest_delivered_card_id(first) is None


def test_latest_proposal_slot_needs_delivered_proposal_kind(
    tmp_path: Path,
) -> None:
    ledger = ledger_at(tmp_path)
    first, second = slot_at("13:30"), slot_at("15:30")
    ledger.save_slot_cards((card_row("card-1", "A", first, "builder", "proposal"),))
    send_delivered(ledger, first, "card-1")
    ledger.save_slot_cards((card_row("card-2", "A", second, "builder", "fallback"),))
    send_delivered(ledger, second, "card-2")
    ledger.save_slot_cards((card_row("card-2", "B", second, "disconnect", "proposal"),))
    assert ledger.latest_proposal_slot("builder", slot_at("18:00")) == first
    assert ledger.latest_proposal_slot("disconnect", slot_at("18:00")) == second
    assert ledger.latest_proposal_slot("builder", first) is None
    assert ledger.latest_proposal_slot("disconnect", first) is None


def test_latest_proposal_slot_reads_the_delivered_card(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    first, second = slot_at("13:30"), slot_at("15:30")
    ledger.save_slot_cards((card_row("card-1", "A", first, "builder", "proposal"),))
    send_delivered(ledger, first, "card-1")
    # A refused proposal card, then a fresh fallback card delivered at the
    # same slot: the delivered card has no proposal side for the profile.
    ledger.save_slot_cards((card_row("card-2", "A", second, "builder", "proposal"),))
    ledger.append_step(second, "send_intent", "intent", 0.1, "card-2", None)
    ledger.append_step(second, "send", "SEND_REFUSED", 0.2, "card-2", None)
    ledger.save_slot_cards((card_row("card-3", "A", second, "builder", "fallback"),))
    send_delivered(ledger, second, "card-3")
    assert ledger.latest_proposal_slot("builder", slot_at("18:00")) == first


def test_slot_cards_save_and_load(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("15:30")
    rows = (
        card_row("card-a", "A", slot, "builder"),
        card_row("card-a", "B", slot, "disconnect"),
    )
    ledger.save_slot_cards(rows)
    assert ledger.slot_cards_for_slot(slot) == rows
    assert ledger.slot_cards_for_card("card-a") == rows
    assert ledger.slot_cards_for_slot(slot_at("18:00")) == ()
    with pytest.raises(sqlite3.IntegrityError):
        ledger.save_slot_cards(rows)


def test_card_payload_save_and_load(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    assert ledger.load_card_payload("card-missing") is None
    ledger.save_card_payload("card-a", '{"id":1}', '{"t":2}')
    assert ledger.load_card_payload("card-a") == ('{"id":1}', '{"t":2}')


def test_learner_state_append_and_read(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("13:30")
    assert ledger.learner_state_for_slot(slot) is None
    ledger.append_learner_state(slot, '{"rulings_seen":0}')
    ledger.append_learner_state(slot, '{"rulings_seen":1}')
    assert ledger.learner_state_for_slot(slot) == '{"rulings_seen":1}'


def test_watchdog_row_and_alert_once_per_day(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    day = date(2026, 11, 2)
    ledger.append_watchdog(slot_at("13:30"), "MODEL_DOWN")
    assert ledger.watchdog_alerted("MODEL_DOWN", day) is True
    assert ledger.watchdog_alerted("MODEL_DOWN", date(2026, 11, 3)) is False
    assert ledger.watchdog_alerted("CHART_FAILED", day) is False
    ledger.append_watchdog(slot_at("15:30"), "MODEL_DOWN")
    assert ledger.watchdog_alerted("MODEL_DOWN", day) is True


def test_save_card_step_writes_sides_payload_and_row_atomically(
    tmp_path: Path,
) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("15:30")
    rows = (
        card_row("card-new", "A", slot, "builder"),
        card_row("card-new", "B", slot, "disconnect"),
    )
    ledger.save_card_step(
        slot, "card-new", {"codes": "-"}, rows, '{"id":1}', '{"t":2}', 0.5
    )
    assert ledger.load_card_payload("card-new") == ('{"id":1}', '{"t":2}')
    assert ledger.slot_cards_for_slot(slot) == rows
    assert ledger.latest_card_id(slot) == "card-new"
    (card_row_found,) = [
        row for row in ledger.rows_for_slot(slot) if row.step == "card"
    ]
    assert card_row_found.outcome == "ok"
    assert card_row_found.card_id == "card-new"
    # A rebuild after a crash cannot collide: the same card id means the
    # same card, so sides and payload are ignored and only a row is added.
    ledger.save_card_step(
        slot, "card-new", {"codes": "-"}, rows, '{"id":1}', '{"t":2}', 0.5
    )
    assert ledger.slot_cards_for_slot(slot) == rows
    assert ledger.latest_card_id(slot) == "card-new"


def test_latest_card_id_reads_the_row_never_sides_alone(
    tmp_path: Path,
) -> None:
    ledger = ledger_at(tmp_path)
    slot = slot_at("15:30")
    assert ledger.latest_card_id(slot) is None
    first = (card_row("card-one", "A", slot, "builder"),)
    ledger.save_card_step(slot, "card-one", None, first, "{}", "{}", 0.1)
    second = (card_row("card-two", "A", slot, "builder"),)
    ledger.save_card_step(slot, "card-two", None, second, "{}", "{}", 0.1)
    assert ledger.latest_card_id(slot) == "card-two"
    assert len(ledger.slot_cards_for_slot(slot)) == 2


def test_all_slot_cards_returns_every_stored_side(tmp_path: Path) -> None:
    ledger = ledger_at(tmp_path)
    assert ledger.all_slot_cards() == ()
    first, second = slot_at("13:30"), slot_at("15:30")
    ledger.save_slot_cards((card_row("card-a", "A", first, "builder"),))
    ledger.save_slot_cards((card_row("card-b", "B", second, "disconnect"),))
    assert ledger.all_slot_cards() == (
        card_row("card-a", "A", first, "builder"),
        card_row("card-b", "B", second, "disconnect"),
    )


def test_sanitise_detail_value_closes_and_cuts() -> None:
    from framework.cycle.slot_ledger import sanitise_detail_value

    assert sanitise_detail_value("muse 2.1.0 (abc def)") == "muse_2.1.0__abc_def_"
    assert sanitise_detail_value("ok-1.2_3") == "ok-1.2_3"
    assert len(sanitise_detail_value("x" * 100)) == 40


def test_open_closes_connection_when_ddl_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3 as sqlite_module

    import framework.cycle.slot_ledger as ledger_module

    closed: list[bool] = []
    real_connect = sqlite_module.connect

    class ExplodingConnection(sqlite_module.Connection):
        def executescript(self, script: str) -> sqlite3.Cursor:
            raise sqlite3.OperationalError("synthetic ddl failure")

        def close(self) -> None:
            closed.append(True)
            super().close()

    def _connect(path: object, *args: object, **kwargs: object) -> object:
        return real_connect(path, *args, factory=ExplodingConnection, **kwargs)  # type: ignore[call-arg]

    monkeypatch.setattr(sqlite_module, "connect", _connect)
    with pytest.raises(sqlite3.OperationalError):
        ledger_module._open(tmp_path / "cycle.db")
    assert closed == [True]


def test_locked_write_past_deadline_raises_without_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import framework.cycle.slot_ledger as ledger_module

    sleeps: list[float] = []
    ticks = iter([0.0, 1000.0])

    def advancing_clock() -> float:
        return next(ticks, 1000.0)

    def always_locked(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger_module, "_open", always_locked)
    ledger = SlotLedger(
        tmp_path / "cycle.db",
        sleep=sleeps.append,
        clock=advancing_clock,
    )
    with pytest.raises(LedgerWriteBlocked):
        ledger.append_step(
            slot_at("13:30"), "start", "ok", 0.0, None, None, timeout_s=30.0
        )
    assert sleeps == []


def test_retry_then_success_uses_injected_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import framework.cycle.slot_ledger as ledger_module

    sleeps: list[float] = []
    real_open: Callable[[Path], sqlite3.Connection] = ledger_module._open
    calls = 0

    def flaky(path: Path) -> sqlite3.Connection:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_open(path)

    monkeypatch.setattr(ledger_module, "_open", flaky)
    ledger = SlotLedger(tmp_path / "cycle.db", sleep=sleeps.append)
    ledger.append_step(slot_at("13:30"), "start", "ok", 0.0, None, None)
    assert calls == 3
    assert sleeps == [0.05, 0.05]
    assert len(ledger.rows_for_slot(slot_at("13:30"))) == 1
