"""Ticket 13 slice 4: the dress rehearsal on a scratch database.

One command seeds synthetic rows next to a new database file, runs the
same ``run_slot`` a timer would, then polls until a ruling tap lands. The
rehearsal slot is the next 15:30 Madrid at or after now, so it always
covers both goals. Nothing here names anything real.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from framework.cycle.orchestrator import Seams, rebuild_state, run_slot
from framework.cycle.slot_ledger import SlotLedger
from framework.schemas.events import Event
from framework.store.store import EventStore
from framework.telegram.client import TelegramClient, TelegramConflict
from framework.telegram.models import first_rulings
from framework.telegram.service import RULING_WINDOW_START, poll_once

MADRID = ZoneInfo("Europe/Madrid")

TEST_COMMITMENTS = (
    {
        "id": "t-b1",
        "profile_id": "builder",
        "title": "TEST Draft the quiet pages",
        "kind": "build",
        "dimension": "love",
        "evidence": "github_push",
    },
    {
        "id": "t-b2",
        "profile_id": "builder",
        "title": "TEST File the weekly notes",
        "kind": "write",
        "dimension": "love",
        "evidence": "github_push",
    },
    {
        "id": "t-d1",
        "profile_id": "disconnect",
        "title": "TEST Hum the evening tune",
        "kind": "music",
        "dimension": "love",
        "evidence": "github_push",
    },
    {
        "id": "t-d2",
        "profile_id": "disconnect",
        "title": "TEST Sit with a slow pause",
        "kind": "rest",
        "dimension": "love",
        "evidence": "github_push",
    },
)


def next_rehearsal_slot(now: datetime) -> datetime:
    """The next 15:30 Madrid at or after now: always a two-goal slot."""
    mad = now.astimezone(MADRID)
    candidate = datetime(mad.year, mad.month, mad.day, 15, 30, tzinfo=MADRID)
    if now > candidate:
        candidate += timedelta(days=1)
    return candidate


def _seed_event(
    eid: str,
    etype: str,
    moment: datetime,
    data: dict[str, Any],
    subject_id: str,
    *,
    tier: str = "public",
) -> Event:
    payload = dict(data)
    payload["type"] = etype
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": subject_id,
            "source": "synthetic-seed",
            "type": etype,
            "time": moment.isoformat(),
            "source_id": f"{etype}-{eid}",
            "data": payload,
            "tier": tier,
            "collected_at": (moment + timedelta(minutes=5)).isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def _seed(slot: datetime, subject_id: str, store: EventStore) -> None:
    """Synthetic rows through ``append_event`` so the code facts say something."""
    rows = (
        _seed_event(
            "rehearse-push-1",
            "github.push",
            slot - timedelta(hours=4),
            {"repo": "synthetic/quiet", "counts": {"commits": 2}},
            subject_id,
        ),
        _seed_event(
            "rehearse-push-2",
            "github.push",
            slot - timedelta(hours=3),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
            subject_id,
        ),
        _seed_event(
            "rehearse-pr-1",
            "github.pr",
            slot - timedelta(minutes=70),
            {"repo": "synthetic/quiet", "counts": {"opened": 1}},
            subject_id,
        ),
        _seed_event(
            "rehearse-screen-1",
            "screen.hour",
            slot - timedelta(hours=2),
            {"device": "mac", "minutes_by_category": {"code": 90.0}},
            subject_id,
            tier="private",
        ),
    )
    for event in rows:
        store.append_event(event)


def rehearse(
    *,
    db_path: Path | str,
    skip_local_model: bool = False,
    no_wait: bool = True,
    seams: Seams,
) -> int:
    """Seed a scratch database, run one slot, poll until a ruling tap lands.

    Prints counts and codes only; the last line prints ``card=<id>``. Exit
    0 when a ruling tap arrived and replay saw it, 3 on a 409, 5 when no
    tap lands within 10 minutes.
    """
    db = Path(db_path)
    if db.exists():
        print("code=FILE_EXISTS")
        return 2
    print("stop every other poller on this token, then restart them after")
    subject_id = os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print("code=IKIGAI_SUBJECT_ID")
        return 2
    slot = next_rehearsal_slot(seams.clock())
    db.parent.mkdir(parents=True, exist_ok=True)
    commitments_path = db.parent / (db.stem + ".commitments.json")
    commitments_path.write_text(json.dumps(list(TEST_COMMITMENTS), indent=2) + "\n")
    os.environ["IKIGAI_COMMITMENTS_FILE"] = str(commitments_path)
    store = EventStore(db_path=db)
    try:
        _seed(slot, subject_id, store)
    finally:
        store.close()
    code = run_slot(
        slot=slot,
        subject_id=subject_id,
        db_path=db,
        no_wait=no_wait,
        skip_local_model=skip_local_model,
        night_cutoff=False,
        seams=seams,
    )
    if code != 0:
        return code
    ledger = SlotLedger(db)
    card_id = ledger.latest_card_id(slot)
    if card_id is None:
        return code
    tg = seams.telegram if seams.telegram is not None else TelegramClient()
    start = seams.clock()
    while True:
        try:
            poll_once(db_path=db, client=tg, long_poll_s=30, now_fn=seams.clock)
        except TelegramConflict:
            print("code=CONFLICT")
            print(f"card={card_id}")
            return 3
        reader = EventStore(db_path=db)
        try:
            taps = reader.events_between(
                subject_id,
                RULING_WINDOW_START,
                seams.clock() + timedelta(days=1),
                types=["app.tap"],
            )
            cards = SlotLedger(db).all_slot_cards()
        finally:
            reader.close()
        ruling = first_rulings(taps).get(card_id)
        if ruling in ("A", "B", "neither"):
            rebuilt, _ = rebuild_state(taps, cards)
            if rebuilt.rulings_seen >= 1:
                print(f"code=RULING_SEEN ruling={ruling}")
                print(f"card={card_id}")
                return 0
        if seams.clock() - start >= timedelta(minutes=10):
            print("code=NO_TAP")
            print(f"card={card_id}")
            return 5
        seams.sleep(5.0)
