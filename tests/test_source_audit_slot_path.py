"""Audit reading tables the real slot wrote (Ticket E2, slot-path file)."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from source_audit import compare as C

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
MADRID = ZoneInfo("Europe/Madrid")

SLOT1 = datetime(2026, 10, 31, 15, 30, tzinfo=MADRID)
SLOT2 = datetime(2026, 10, 31, 18, 0, tzinfo=MADRID)


def _prs_times(as_of):
    from framework.glimmer.metrics import floor_hour

    end = floor_hour(as_of)
    base = end - timedelta(hours=12)
    return [base + timedelta(hours=i) for i in range(8)]


def _seed_gap_rows(db_path, times, collected_at, start_n=1):
    from framework.store import EventStore

    store = EventStore(db_path=db_path)
    try:
        from framework.schemas.events import Event as _Event

        events = []
        for offset, when in enumerate(times):
            n = start_n + offset
            events.append(
                _Event.model_validate(
                    {
                        "id": f"slot-gap{n}",
                        "subject_id": SUBJECT,
                        "source": "github",
                        "type": "github.pr",
                        "time": when.isoformat(),
                        "source_id": str(9000 + n),
                        "data": {
                            "type": "github.pr",
                            "repo": REPO,
                            "counts": {"opened": 1},
                        },
                        "tier": "public",
                        "collected_at": collected_at.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                )
            )
        store.append_events(events)
    finally:
        store.close()


def _seed_github(db_path, times, as_of, start_n=1):
    from framework.store import EventStore

    store = EventStore(db_path=db_path)
    try:
        from framework.schemas.events import Event as _Event

        events = []
        for offset, when in enumerate(times):
            n = start_n + offset
            events.append(
                _Event.model_validate(
                    {
                        "id": f"slot-e{n}",
                        "subject_id": SUBJECT,
                        "source": "github",
                        "type": "github.pr",
                        "time": when.isoformat(),
                        "source_id": str(9000 + n),
                        "data": {
                            "type": "github.pr",
                            "repo": REPO,
                            "counts": {"opened": 1},
                        },
                        "tier": "public",
                        "collected_at": as_of.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                )
            )
        store.append_events(events)
    finally:
        store.close()


def _snapshot_for(times, fetched_at, start_n=1):
    events = []
    pulls = []
    for offset, when in enumerate(times):
        n = start_n + offset
        iso = when.astimezone(UTC).isoformat().replace("+00:00", "Z")
        events.append(
            {
                "id": str(9000 + n),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": iso,
                "action": "opened",
                "pr_number": 9000 + n,
                "push_id": None,
                "head": None,
                "before": None,
            }
        )
        pulls.append({"number": 9000 + n, "created_at": iso, "author": USER})
    stamps = [e["created_at"] for e in events]
    return {
        "fetched_at": fetched_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "user": USER,
        "repo": REPO,
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(events),
                "oldest": min(stamps),
                "newest": max(stamps),
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": min(stamps),
                "newest": max(stamps),
                "stop": "last_page",
            },
            "activity": {
                "rows": 0,
                "oldest": None,
                "newest": None,
                "stop": "last_page",
            },
        },
    }


def _env(monkeypatch, tmp_path):
    terms = tmp_path / "terms"
    terms.mkdir(exist_ok=True)
    (terms / "deny-terms.txt").write_text("zzforbiddenzz\n")
    commitments = tmp_path / "commitments.json"
    commitments.write_text(
        json.dumps(
            [
                {
                    "id": "c-builder",
                    "profile_id": "builder",
                    "title": "Build thing",
                    "kind": "build",
                    "dimension": "love",
                    "evidence": "github_push",
                },
                {
                    "id": "c-disconnect",
                    "profile_id": "disconnect",
                    "title": "Walk outside",
                    "kind": "build",
                    "dimension": "love",
                    "evidence": "github_push",
                },
            ]
        )
    )
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(terms))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(commitments))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
    return commitments


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class _Telegram:
    def __init__(self):
        self.calls = []

    def send_photo(
        self,
        chat_id,
        photo,
        caption,
        markup,
        timeout_s=60.0,
        disable_notification=False,
    ):
        self.calls.append({"chat_id": chat_id, "caption": caption})
        return {"message_id": 11}


def _propose_factory(text, prior, last):
    from framework.briefing.schemas import Briefing
    from framework.proposal.core import ProposalResult

    def _make(**kwargs):
        profile = str(kwargs["profile_id"])
        slot = kwargs["slot"]
        briefing = Briefing.model_validate(
            {
                "id": f"brf-{profile}",
                "profile_id": profile,
                "subject_id": kwargs["subject_id"],
                "slot": slot.isoformat(),
                "sections": [
                    {
                        "type": "overall_state",
                        "claims": [
                            {
                                "id": "c1",
                                "text": text,
                                "fact_ids": [],
                                "metric_refs": [
                                    {"metric_id": "period.prior.prs", "value": prior},
                                    {"metric_id": "period.last.prs", "value": last},
                                ],
                            }
                        ],
                    },
                    {
                        "type": "actions",
                        "claims": [],
                        "actions": [
                            {
                                "id": "act-1",
                                "commitment_id": (
                                    "c-builder"
                                    if profile == "builder"
                                    else "c-disconnect"
                                ),
                                "kind": "build",
                                "text": "Do it",
                                "dimension": "love",
                                "proposed_start": slot.isoformat(),
                                "proposed_end": (slot + timedelta(hours=1)).isoformat(),
                            }
                        ],
                    },
                ],
            }
        )
        return ProposalResult(
            kind="proposal",
            profile_id=profile,
            subject_id=kwargs["subject_id"],
            cycle_id=kwargs["cycle_id"],
            run=kwargs["run"],
            slot=slot,
            hour=kwargs["hour"],
            briefing=briefing,
            fallback=None,
            reason_codes=(),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="",
        )

    class _Spy:
        def __init__(self):
            self.calls = 0

        def __call__(self, **kwargs):
            self.calls += 1
            return _make(**kwargs)

    return _Spy()


def _run_slot(slot, db_path, seams):
    from framework.cycle.orchestrator import run_slot

    return run_slot(
        slot=slot,
        subject_id=SUBJECT,
        db_path=db_path,
        no_wait=True,
        seams=seams,
    )


def _harness(monkeypatch, tmp_path, slot, propose_spy, telegram):
    from framework.cycle.orchestrator import FactsChildResult, Seams

    _env(monkeypatch, tmp_path)
    clock = _Clock(slot)

    def _facts(**kwargs):
        return FactsChildResult("MODEL_DOWN", None, None)

    class _Wonder:
        transport = "muse"
        transport_version = "fake"
        harness_rules_file = None

        def complete(self, request):
            raise AssertionError("wonder client must not be called")

    seams = Seams(
        facts=_facts,
        wonder=lambda terms, deadline: _Wonder(),
        telegram=telegram,
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    monkeypatch.setattr("framework.cycle.propose", propose_spy)
    return seams


def test_slot_path_clean_passes_prs_and_sum(tmp_path, monkeypatch, capsys):
    slot = SLOT1
    as_of = slot - timedelta(minutes=25)
    times = _prs_times(as_of)
    assert len(times) == 8
    db = tmp_path / "slot.db"
    _seed_github(db, times, as_of)
    telegram = _Telegram()
    propose_spy = _propose_factory(
        "Pull requests rose from 0 in prior to 8 in last.", 0, 8
    )
    seams = _harness(monkeypatch, tmp_path, slot, propose_spy, telegram)
    code = _run_slot(slot, db, seams)
    capsys.readouterr()
    assert code == 0
    assert telegram.calls, "card was never sent"
    snap = _snapshot_for(times, as_of + timedelta(hours=7))
    conn = sqlite3.connect(db)
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["total"] == 8
    assert res["stages"]["prs"][1]["total"] == 8
    assert res["stages"]["prs"][2]["last"] == 8
    assert res["stages"]["prs"][3]["last"] == 8
    assert res["verdicts"]["prs"] == "PASS"
    assert res["delivery_proven"] is True
    conn = sqlite3.connect(db)
    try:
        res_all = C.run_compare(
            snap, conn, metric="all", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res_all["stages"]["prs"][0]["total"] == 8
    assert res_all["stages"]["pushes_plus_prs"][3]["status"] == "match"
    assert res_all["since_line"]["stated"] == res_all["since_line"]["recounted"]


def test_slot_path_claim_11_fails_stage4_only(tmp_path, monkeypatch, capsys):
    slot = SLOT1
    as_of = slot - timedelta(minutes=25)
    times = _prs_times(as_of)
    db = tmp_path / "slot.db"
    _seed_github(db, times, as_of)
    telegram = _Telegram()
    propose_spy = _propose_factory(
        "Pull requests rose from 0 in prior to 11 in last.", 0, 11
    )
    seams = _harness(monkeypatch, tmp_path, slot, propose_spy, telegram)
    code = _run_slot(slot, db, seams)
    capsys.readouterr()
    assert code == 0
    snap = _snapshot_for(times, as_of + timedelta(hours=7))
    conn = sqlite3.connect(db)
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert [s["status"] for s in res["stages"]["prs"][:3]] == [
        "match",
        "match",
        "match",
    ]
    assert res["stages"]["prs"][3]["status"] == "mismatch"


def test_slot_path_planted_row_reads_9(tmp_path, monkeypatch, capsys):
    from framework.store import EventStore

    slot = SLOT1
    as_of = slot - timedelta(minutes=25)
    times = _prs_times(as_of)
    db = tmp_path / "slot.db"
    _seed_github(db, times, as_of)
    store = EventStore(db_path=db)
    try:
        from framework.schemas.events import Event as _Event

        extra_when = times[0]
        store.append_events(
            [
                _Event.model_validate(
                    {
                        "id": "slot-extra",
                        "subject_id": SUBJECT,
                        "source": "github",
                        "type": "github.pr",
                        "time": extra_when.isoformat(),
                        "source_id": "9999",
                        "data": {
                            "type": "github.pr",
                            "repo": REPO,
                            "counts": {"opened": 1},
                        },
                        "tier": "public",
                        "collected_at": as_of.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                )
            ]
        )
    finally:
        store.close()
    telegram = _Telegram()
    propose_spy = _propose_factory(
        "Pull requests rose from 0 in prior to 9 in last.", 0, 9
    )
    seams = _harness(monkeypatch, tmp_path, slot, propose_spy, telegram)
    code = _run_slot(slot, db, seams)
    capsys.readouterr()
    assert code == 0
    snap = _snapshot_for(times, as_of + timedelta(hours=7))
    conn = sqlite3.connect(db)
    try:
        res = C.run_compare(snap, conn, metric="all", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["total"] == 8
    assert res["stages"]["prs"][1]["total"] == 9
    assert res["stages"]["prs"][2]["last"] == 9
    assert res["stages"]["prs"][3]["last"] == 9
    assert res["diagnostics"]["prs"]["not_in_snapshot"] == 1
    assert res["diagnostics"]["prs"]["counted"] == 9


def test_slot_path_two_slots_since_covers_floored_gap(tmp_path, monkeypatch, capsys):
    from framework.glimmer.metrics import floor_hour

    db = tmp_path / "slot.db"
    telegram = _Telegram()
    propose_spy = _propose_factory(
        "Pull requests rose from 0 in prior to 8 in last.", 0, 8
    )
    as_of1 = SLOT1 - timedelta(minutes=25)
    times1 = _prs_times(as_of1)[:4]
    _seed_github(db, times1, as_of1, start_n=1)
    seams1 = _harness(monkeypatch, tmp_path, SLOT1, propose_spy, telegram)
    code1 = _run_slot(SLOT1, db, seams1)
    capsys.readouterr()
    assert code1 == 0
    as_of2 = SLOT2 - timedelta(minutes=25)
    times2 = _prs_times(as_of2)[4:]
    _seed_github(db, times2, as_of2, start_n=5)
    floor1, floor2 = floor_hour(as_of1), floor_hour(as_of2)
    gap_in = [floor1 + timedelta(minutes=2), floor1 + timedelta(minutes=3)]
    gap_out = [floor2 + timedelta(minutes=2)]
    _seed_gap_rows(db, gap_in + gap_out, as_of2, start_n=9)
    seams2 = _harness(monkeypatch, tmp_path, SLOT2, propose_spy, telegram)
    code2 = _run_slot(SLOT2, db, seams2)
    capsys.readouterr()
    assert code2 == 0
    snap1 = _snapshot_for(times1, as_of2 + timedelta(hours=7), start_n=1)
    snap2 = _snapshot_for(times2, as_of2 + timedelta(hours=7), start_n=5)
    all_times = times1 + times2
    snap = _snapshot_for(all_times, as_of2 + timedelta(hours=7), start_n=1)
    snap["events"] = snap1["events"] + snap2["events"]
    snap["pulls"] = snap1["pulls"] + snap2["pulls"]
    gap_snap = _snapshot_for(gap_in + gap_out, as_of2 + timedelta(hours=7), start_n=9)
    snap["events"] = snap["events"] + gap_snap["events"]
    snap["pulls"] = snap["pulls"] + gap_snap["pulls"]
    stamps = [e["created_at"] for e in snap["events"]]
    snap["coverage"]["events"] = {
        "rows": len(snap["events"]),
        "oldest": min(stamps),
        "newest": max(stamps),
        "stop": "last_page",
    }
    snap["coverage"]["pulls"] = {
        "rows": len(snap["pulls"]),
        "oldest": min(stamps),
        "newest": max(stamps),
        "stop": "last_page",
    }
    conn = sqlite3.connect(db)
    try:
        res = C.run_compare(
            snap, conn, metric="pushes_plus_prs", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res["since_line"]["recounted"] is not None
    start = floor_hour(as_of1)
    end = floor_hour(as_of2)
    assert end > start
    from source_audit import recount as R

    expected = R.count_between(snap, USER, REPO, start, end)
    assert res["since_line"]["recounted"] == expected
    assert expected == 2
    raw = R.count_between(snap, USER, REPO, as_of1, as_of2)
    assert raw == 1
    assert raw != expected
    assert res["since_line"]["stated"] == expected
    assert res["stages"]["pushes_plus_prs"][3]["status"] != "mismatch" or (
        "SINCE_LINE_WRONG" not in res["stages"]["pushes_plus_prs"][3]["codes"]
    )
