"""Source-audit product conformance (Ticket E2 plan, conformance file).

The one file that imports both sides. I keep it as the drift alarm.
"""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from evals.glimmer_cases import SUBJECT_ID, make_event
from framework.cycle import run_cycle
from framework.glimmer import metrics as M
from framework.store import EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.telegram.ledger import CardLedger
from source_audit import compare as C
from source_audit import recount as R

SUBJECT = SUBJECT_ID
USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
MADRID = ZoneInfo("Europe/Madrid")


class _RaisingLLM:
    def complete(self, prompt):
        raise AssertionError("the model must not be called")


def _pr(eid, number, action, time, repo=REPO, collected=None, **kw):
    return make_event(
        eid=eid,
        source="github",
        source_id=str(1000 + number),
        type="github.pr",
        time=time,
        data={"repo": repo, "counts": {action: 1}},
        collected_at=kw.get("collected_at", collected),
    )


def _push(eid, time, head, collected=None, **kw):
    return make_event(
        eid=eid,
        source="github",
        source_id=f"push-{eid}",
        type="github.push",
        time=time,
        data={"repo": REPO, "counts": {"commits": 2}},
        collected_at=kw.get("collected_at", collected),
    )


def _cycle_db(path, as_of, events):
    store = EventStore(db_path=path)
    try:
        store.append_events(events)
        facts = FactStore(db_path=path)
        try:
            result, _ = run_cycle(
                as_of,
                SUBJECT,
                store,
                facts,
                _RaisingLLM(),
                personal_pass=False,
                feed_pass=False,
            )
        finally:
            facts.close()
    finally:
        store.close()
    return result


INSTANTS = [
    datetime(2026, 10, 31, 0, 0, tzinfo=UTC),
    datetime(2026, 10, 31, 0, 5, tzinfo=UTC),
    datetime(2026, 10, 31, 0, 5, tzinfo=ZoneInfo("Asia/Kathmandu")),
    datetime(2026, 10, 31, 0, 5, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    datetime(2026, 10, 25, 2, 30, tzinfo=MADRID, fold=0),
    datetime(2026, 10, 25, 2, 30, tzinfo=MADRID, fold=1),
]

KEYS = (
    "period.earlier.prs",
    "period.prior.prs",
    "period.last.prs",
    "github.pr.count",
    "period.earlier.pushes",
    "period.prior.pushes",
    "period.last.pushes",
    "github.push.count",
)


def _seeded_rows(as_of):
    """Make at least 40 deterministic rows anchored to one window.

    Pull request rows with opened, merged, closed, and reopened actions,
    pushes with and without a push id, rows exactly on each period edge,
    and rows in the open hour. Pushes stay out of last on purpose so the
    withheld last key has something to line up with.
    """
    ws, we = M.window_bounds(as_of)
    collected = ws + timedelta(hours=1)
    feed = []
    store = []
    pr_number = [0]

    def _add_pr(action, created):
        pr_number[0] += 1
        number = pr_number[0]
        opened_id = str(1000 + number)
        feed.append(
            {
                "id": opened_id if action == "opened" else str(3000 + number),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created.isoformat(),
                "action": "opened",
                "pr_number": number,
                "push_id": None,
                "head": None,
                "before": None,
            }
        )
        if action != "opened":
            feed.append(
                {
                    "id": str(3000 + number),
                    "type": "PullRequestEvent",
                    "repo": REPO,
                    "actor": USER,
                    "created_at": created.isoformat(),
                    "action": action,
                    "pr_number": number,
                    "push_id": None,
                    "head": None,
                    "before": None,
                }
            )
            store.append(
                make_event(
                    eid=f"x{action}{number}",
                    source="github",
                    source_id=str(3000 + number),
                    type="github.pr",
                    time=created,
                    data={"repo": REPO, "counts": {action: 1}},
                    collected_at=collected,
                )
            )
        store.append(
            _pr(f"o{number}", number, "opened", created, collected_at=collected)
        )
        return {"number": number, "created_at": created.isoformat(), "author": USER}

    def _add_push(created, with_id=True):
        stamp = int(created.timestamp())
        push_id = 5000 + stamp if with_id else None
        head = "a" * 32 + f"{stamp % 16**8:08x}"
        feed.append(
            {
                "id": str(4000 + stamp),
                "type": "PushEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created.isoformat(),
                "action": None,
                "pr_number": None,
                "push_id": push_id,
                "head": head,
                "before": "0" * 40,
            }
        )
        store.append(_push(f"p{stamp}", created, head, collected_at=collected))

    pulls = []
    mid = [ws + timedelta(hours=12), ws + timedelta(hours=36)]
    for created in mid:
        for _ in range(2):
            pulls.append(_add_pr("opened", created))
            pulls.append(_add_pr("merged", created))
        pulls.append(_add_pr("closed", created))
        pulls.append(_add_pr("reopened", created))
        _add_push(created + timedelta(hours=1))
        _add_push(created + timedelta(hours=2), with_id=False)
    last_mid = ws + timedelta(hours=60)
    for _ in range(2):
        pulls.append(_add_pr("opened", last_mid))
        pulls.append(_add_pr("merged", last_mid))
    pulls.append(_add_pr("closed", last_mid))
    pulls.append(_add_pr("reopened", last_mid))
    for edge in (
        ws,
        ws + timedelta(hours=24),
        ws + timedelta(hours=48),
        we,
        we + timedelta(seconds=1),
    ):
        pulls.append(_add_pr("opened", edge))
        pulls.append(_add_pr("merged", edge))
    open_hour = [we + timedelta(minutes=2), we + timedelta(minutes=3)]
    pulls.append(_add_pr("opened", open_hour[0]))
    pulls.append(_add_pr("merged", open_hour[0]))
    _add_push(open_hour[1])
    assert len(store) >= 40, len(store)
    return feed, pulls, store


def _feed_snapshot(feed, pulls, as_of):
    ws, we = R.window_bounds(as_of)
    times = sorted(e["created_at"] for e in feed)
    return {
        "fetched_at": (we + timedelta(hours=7)).isoformat().replace("+00:00", "Z"),
        "user": USER,
        "repo": REPO,
        "events": feed,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(feed),
                "oldest": (ws - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "newest": times[-1] if times else None,
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": (ws - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "newest": max(p["created_at"] for p in pulls),
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


def test_recount_matches_product_snapshot_and_bounds(tmp_path):
    for pos, moment in enumerate(INSTANTS):
        assert R.floor_hour(moment) == M.floor_hour(moment)
        assert R.window_bounds(moment) == M.window_bounds(moment)
        assert [(n, s, e) for n, s, e in R.period_bounds(moment)] == [
            (n, s, e) for n, s, e in M.period_bounds(moment)
        ]
        feed, pulls, rows = _seeded_rows(moment)
        db = tmp_path / f"c{pos}.db"
        result = _cycle_db(db, moment, rows)
        snap = dict(result.snapshot.values)
        mine = R.recount(_feed_snapshot(feed, pulls, moment), moment, USER, REPO)
        for key in KEYS:
            name = key.split(".")[1]
            is_prs = key.endswith("prs") or key == "github.pr.count"
            if key.startswith("github."):
                mine_value = mine["prs"]["total"] if is_prs else mine["pushes"]["total"]
            else:
                idx = {"earlier": 0, "prior": 1, "last": 2}[name]
                block = mine["prs"] if is_prs else mine["pushes"]
                mine_value = block["periods"][idx]
            prod_value = snap.get(key)
            if prod_value is None:
                assert mine_value == 0, (moment, key, snap)
                assert key == "period.last.pushes", (moment, key, snap)
                assert mine["pushes"]["open"] > 0, (moment, key)
                assert mine["pushes"]["periods"][2] == 0, (moment, key)
            else:
                assert int(prod_value) == mine_value, (
                    moment,
                    key,
                    prod_value,
                    mine_value,
                )


def _table_info(path):
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]: {col[1] for col in conn.execute(f"PRAGMA table_info({row[0]})")}
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def test_columns_match_product_built_store(tmp_path):
    from framework.briefing.schemas import Briefing, Claim, MetricRef, Section
    from framework.proposal.core import AttemptOutcome, ProposalResult
    from framework.telegram.models import Card, Proposal

    db = tmp_path / "c.db"
    store = EventStore(db_path=db)
    moment = datetime(2026, 10, 29, 1, tzinfo=UTC)
    try:
        store.append_events(
            [
                _pr(
                    "e1",
                    1,
                    "opened",
                    moment,
                    collected_at=datetime(2026, 10, 31, tzinfo=UTC),
                )
            ]
        )
    finally:
        store.close()
    facts = FactStore(db_path=db)
    try:
        result, run = run_cycle(
            datetime(2026, 10, 31, 0, 5, tzinfo=UTC),
            SUBJECT,
            EventStore(db_path=db),
            facts,
            _RaisingLLM(),
            personal_pass=False,
            feed_pass=False,
        )
    finally:
        facts.close()
    slot = datetime(2026, 10, 31, 0, 30, tzinfo=UTC)
    briefing = Briefing(
        id="b1",
        profile_id="p1",
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="overall_state",
                claims=[
                    Claim(
                        id="c1",
                        text="t",
                        fact_ids=[],
                        metric_refs=[MetricRef(metric_id="period.prior.prs", value=1)],
                    )
                ],
                actions=[],
            ),
        ],
    )
    props = ProposalStore(db_path=db)
    try:
        props.record(
            ProposalResult(
                kind="proposal",
                profile_id="p1",
                subject_id=SUBJECT,
                cycle_id=result.cycle_id,
                run=run,
                slot=slot,
                hour=None,
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(
                    AttemptOutcome(
                        number=1,
                        model_requested="m",
                        model_reported="m",
                        effort="low",
                        prompt_hash="h",
                        raw_text="{}",
                        parsed_ok=True,
                        blocked=False,
                        codes=(),
                        latency_ms=1,
                        prompt_tokens=None,
                        completion_tokens=None,
                        reasoning_tokens=None,
                        finish_reason=None,
                    ),
                ),
                cycle_age_s=1.0,
                prompt_hash="h",
            ),
            snapshot=dict(result.snapshot.values),
        )
    finally:
        props.close()
    card = Card(
        slot=slot,
        since_line="one line",
        proposals=(
            Proposal(
                letter="A",
                kind="proposal",
                profile="p1",
                title="t",
                start=datetime(2026, 10, 31, 1, tzinfo=UTC),
                end=datetime(2026, 10, 31, 2, tzinfo=UTC),
            ),
        ),
        statements=("Pull requests rose from 0 in earlier to 1 in prior.",),
    )
    ledger = CardLedger(db_path=db)
    ledger.save_card(card, now=datetime(2026, 10, 31, 1, tzinfo=UTC))
    from source_audit import control as CTL
    from source_audit import store as ST

    info = _table_info(db)
    for table, columns in ST.STORE_COLUMNS.items():
        if table in ST.TICKET13:
            continue
        assert table in info, table
        for column in columns:
            assert column in info.get(table, set()), (table, column)
    control_db = tmp_path / "control.db"
    CTL._db(
        str(control_db),
        CTL._stored(0, 8),
        CTL._statement(0, 8),
        CTL._refs(0, 8),
        chart_last=8,
    )
    control_info = _table_info(control_db)
    for table, columns in ST.STORE_COLUMNS.items():
        if table == "telegram_cards":
            continue
        assert table in control_info, table
        for column in columns:
            assert column in control_info.get(table, set()), (table, column)
    try:
        import importlib

        module = importlib.import_module("framework.cycle.slot_ledger")
    except ImportError:
        pytest.skip("slot_ledger not importable until Ticket 13 merges")
    statements = [
        value
        for value in vars(module).values()
        if isinstance(value, str) and "CREATE TABLE" in value
    ]
    assert statements, "slot_ledger module exposes no DDL"
    slot_db = sqlite3.connect(tmp_path / "slot.db")
    try:
        for ddl in statements:
            slot_db.executescript(ddl)
        slot_info = {
            row[0]: {col[1] for col in slot_db.execute(f"PRAGMA table_info({row[0]})")}
            for row in slot_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        slot_db.close()
    for table, columns in ST.STORE_COLUMNS.items():
        if table not in ST.TICKET13:
            continue
        for column in columns:
            assert column in slot_info.get(table, set()), (table, column)


def test_open_hour_withheld_through_product(tmp_path):
    as_of = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)
    push_time = datetime(2026, 10, 31, 0, 2, tzinfo=UTC)
    db = tmp_path / "c.db"
    result = _cycle_db(
        db, as_of, [_push("p1", push_time, "a" * 40, collected_at=as_of)]
    )
    snap = dict(result.snapshot.values)
    assert "period.last.pushes" not in snap
    snap = _audit_snapshot(as_of)
    mine = R.recount(snap, as_of, USER, REPO)
    assert mine["pushes"]["open"] == 1
    assert mine["pushes"]["periods"][2] == 0
    conn = sqlite3.connect(db)
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of=as_of.isoformat(),
            metric="pushes",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    assert res["stages"]["pushes"][1]["status"] == "unavailable"
    assert "STORED_PERIOD_WITHHELD" in res["stages"]["pushes"][1]["codes"]


def test_since_counts_and_line_match_recount_floored():
    from framework.cycle.card_build import since_counts, since_line
    from framework.glimmer.metrics import floor_hour
    from framework.schemas.events import Event as _Event
    from source_audit.parse import parse_since_line as _parse

    def _ev(kind, when, **kw):
        from typing import Any as _Any

        data: _Any = {"type": kind, "repo": REPO}
        if kind == "github.pr":
            data["counts"] = {"opened": 1}
        else:
            data["counts"] = {"commits": 1}
        return _Event(
            id=kw.get("eid", "e1"),
            subject_id=SUBJECT,
            source="github",
            source_id=kw.get("sid", "1"),
            type=kind,  # type: ignore[arg-type]
            time=when,
            data=data,
            tier="public",
            collected_at=kw.get("collected", when),
            collector_version="v",
        )

    first_as_of = datetime(2026, 10, 30, 0, 5, tzinfo=UTC)
    second_as_of = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)
    first_prev = first_as_of - timedelta(hours=24)
    rows = [
        _ev("github.pr", datetime(2026, 10, 29, 0, 0, tzinfo=UTC), eid="a", sid="1"),
        _ev("github.push", datetime(2026, 10, 29, 1, 0, tzinfo=UTC), eid="b", sid="2"),
        _ev("github.pr", datetime(2026, 10, 30, 0, 0, tzinfo=UTC), eid="c", sid="3"),
        _ev(
            "github.pr",
            datetime(2026, 10, 30, 0, 2, tzinfo=UTC),
            eid="d",
            sid="4",
            collected=second_as_of,
        ),
    ]
    rows.extend(
        [
            _ev(
                "github.pr",
                datetime(2026, 10, 30, 0, 3, tzinfo=UTC),
                eid="gap-a1",
                sid="gap-a1",
            ),
            _ev(
                "github.pr",
                datetime(2026, 10, 30, 0, 4, tzinfo=UTC),
                eid="gap-a2",
                sid="gap-a2",
            ),
            _ev(
                "github.pr",
                datetime(2026, 10, 31, 0, 3, tzinfo=UTC),
                eid="gap-b",
                sid="gap-b",
            ),
        ]
    )
    first_counts = since_counts(rows, first_prev, first_as_of)
    first_line = since_line(
        datetime(2026, 10, 29, 1, 30, tzinfo=UTC), first_counts, first=True
    )
    assert _parse(first_line) == int(first_counts["pushes"])
    second_counts = since_counts(rows, first_as_of, second_as_of)
    second_line = since_line(
        datetime(2026, 10, 30, 1, 30, tzinfo=UTC), second_counts, first=False
    )
    assert _parse(second_line) == int(second_counts["pushes"])
    snap = {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": [
            {
                "id": "1",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-29T00:00:00Z",
                "action": "opened",
                "pr_number": 1,
                "push_id": None,
                "head": None,
                "before": None,
            },
            {
                "id": "2",
                "type": "PushEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-29T01:00:00Z",
                "action": None,
                "pr_number": None,
                "push_id": 2,
                "head": "a" * 40,
                "before": "b" * 40,
            },
            {
                "id": "3",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-30T00:00:00Z",
                "action": "opened",
                "pr_number": 3,
                "push_id": None,
                "head": None,
                "before": None,
            },
            {
                "id": "4",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-30T00:02:00Z",
                "action": "opened",
                "pr_number": 4,
                "push_id": None,
                "head": None,
                "before": None,
            },
            {
                "id": "gap-a1",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-30T00:03:00Z",
                "action": "opened",
                "pr_number": 101,
                "push_id": None,
                "head": None,
                "before": None,
            },
            {
                "id": "gap-a2",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-30T00:04:00Z",
                "action": "opened",
                "pr_number": 102,
                "push_id": None,
                "head": None,
                "before": None,
            },
            {
                "id": "gap-b",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-31T00:03:00Z",
                "action": "opened",
                "pr_number": 103,
                "push_id": None,
                "head": None,
                "before": None,
            },
        ],
        "pulls": [
            {"number": 1, "created_at": "2026-10-29T00:00:00Z", "author": USER},
            {"number": 3, "created_at": "2026-10-30T00:00:00Z", "author": USER},
            {"number": 4, "created_at": "2026-10-30T00:02:00Z", "author": USER},
            {
                "number": 101,
                "created_at": "2026-10-30T00:03:00Z",
                "author": USER,
            },
            {
                "number": 102,
                "created_at": "2026-10-30T00:04:00Z",
                "author": USER,
            },
            {
                "number": 103,
                "created_at": "2026-10-31T00:03:00Z",
                "author": USER,
            },
        ],
        "activity": [],
        "coverage": {
            "events": {
                "rows": 7,
                "oldest": "2026-10-29T00:00:00Z",
                "newest": "2026-10-31T00:03:00Z",
                "stop": "last_page",
            },
            "pulls": {
                "rows": 6,
                "oldest": "2026-10-29T00:00:00Z",
                "newest": "2026-10-31T00:03:00Z",
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
    first_start = floor_hour(first_prev)
    first_end = floor_hour(first_as_of)
    second_start = floor_hour(first_as_of)
    second_end = floor_hour(second_as_of)
    assert R.count_between(snap, USER, REPO, first_start, first_end) == int(
        first_counts["pushes"]
    )
    assert R.count_between(snap, USER, REPO, second_start, second_end) == int(
        second_counts["pushes"]
    )
    floored = R.count_between(snap, USER, REPO, second_start, second_end)
    assert floored == 4
    raw = R.count_between(snap, USER, REPO, first_as_of, second_as_of)
    assert raw == 1
    assert raw != floored
    since_info = C._since(
        snap,
        {
            "proven": True,
            "as_of": second_as_of,
            "card": {"since_line": "Since 00:05: 4 pushes + PRs."},
        },
        first_as_of,
    )
    assert since_info == {"stated": 4, "recounted": 4, "codes": []}


def _audit_snapshot(as_of):
    push_created = "2026-10-31T00:02:00Z"
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": [
            {
                "id": "9001",
                "type": "PushEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": push_created,
                "action": None,
                "pr_number": None,
                "push_id": 4242,
                "head": "a" * 40,
                "before": "b" * 40,
            },
        ],
        "pulls": [],
        "activity": [],
        "coverage": {
            "events": {
                "rows": 1,
                "oldest": push_created,
                "newest": push_created,
                "stop": "last_page",
            },
            "pulls": {"rows": 0, "oldest": None, "newest": None, "stop": "last_page"},
            "activity": {
                "rows": 0,
                "oldest": None,
                "newest": None,
                "stop": "last_page",
            },
        },
    }
