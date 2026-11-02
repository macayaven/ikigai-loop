"""Source-audit coverage and feed-settled rules (Ticket E2 plan, coverage file)."""

import sqlite3

from source_audit import compare as C
from source_audit import recount as R

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"


def _event(eid, created):
    return {
        "id": str(eid),
        "type": "PullRequestEvent",
        "repo": REPO,
        "actor": USER,
        "created_at": created,
        "action": "opened",
        "pr_number": int(eid),
        "push_id": None,
        "head": None,
        "before": None,
    }


def _base(fetched_at="2026-10-31T00:10:00Z", estop="last_page", erows=None):
    events = [_event(1, "2026-10-29T01:00:00Z"), _event(2, "2026-10-29T02:00:00Z")]
    pulls = [
        {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER},
        {"number": 2, "created_at": "2026-10-29T02:00:00Z", "author": USER},
    ]
    return {
        "fetched_at": fetched_at,
        "user": USER,
        "repo": REPO,
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(events) if erows is None else erows,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T02:00:00Z",
                "stop": estop,
            },
            "pulls": {
                "rows": 2,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T02:00:00Z",
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


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, type TEXT,"
        " time TEXT, source_id TEXT, data TEXT, tier TEXT, collected_at TEXT,"
        " collector_version TEXT)"
    )
    conn.execute(
        "INSERT INTO events VALUES ('e1', ?, 'github', 'github.pr',"
        " '2026-10-29T01:00:00+00:00', '1', '{\"counts\": {\"opened\": 1}}',"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
    )
    conn.commit()
    return conn


def _full_db(path):
    import json as _json

    conn = _db(path)
    stored = _json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 0,
            "period.last.prs": 0,
            "github.pr.count": 0,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
            "period.last.pushes": 0,
        }
    )
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, model_id TEXT, prompt_hash TEXT, latency_ms INTEGER,"
        " raw_valid INTEGER, is_noop INTEGER, noop_reason TEXT, snapshot TEXT,"
        " passes TEXT, dropped_codes TEXT, kept_count INTEGER,"
        " dropped_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c1', 1, ?, '2026-10-31T00:05:00+00:00',"
        " 'm', 'h', 0, 1, 0, NULL, ?, '[]', '[]', 0, 0)",
        (SUBJECT, stored),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00',"
        " 'Pull requests rose from 0 in earlier to 0 in prior.', '[]', 'code')",
        (SUBJECT,),
    )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    briefing = _json.dumps({"sections": []})
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, 'p1', ?,"
        " '2026-10-31T00:30:00+00:00', 'proposal', ?, NULL, ?, NULL, NULL,"
        " '[]', 1.0)",
        (SUBJECT, briefing, stored),
    )
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT,"
        " card_id TEXT, detail TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, letter TEXT, slot TEXT,"
        " subject_id TEXT, as_of TEXT, bucket TEXT, profile_id TEXT,"
        " commitment_id TEXT, kind TEXT, policy_pick TEXT,"
        " policy_alternative TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    card = _json.dumps(
        {
            "slot": "2026-10-31T00:30:00+00:00",
            "since_line": "First card, last 24h: nothing recorded.",
            "proposals": [],
            "statements": [],
        }
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-1', 'A',"
        " '2026-10-31T00:30:00+00:00', ?, '2026-10-31T00:05:00+00:00', 'b',"
        " 'p1', 'c', 'proposal', NULL, NULL)",
        (SUBJECT,),
    )
    conn.execute("INSERT INTO slot_card_payloads VALUES ('card-1', ?, 'null')", (card,))
    conn.execute(
        "INSERT INTO slot_ledger VALUES ('2026-10-31T00:30:00+00:00', 'send',"
        " 'delivered', 'card-1', NULL)"
    )
    conn.commit()
    return conn


def test_snapshot_before_window_end_unavailable(tmp_path):
    snap = _base(fetched_at="2026-10-30T23:00:00Z")
    conn = _full_db(tmp_path / "s.db")
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
            card="latest",
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "unavailable"
    assert "COVERAGE_GAP" in res["stages"]["prs"][0]["codes"]
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert "COVERAGE_GAP" in stage["codes"]
    assert res["verdicts"]["prs"] != "FAIL"


def test_window_past_30_days_unavailable(tmp_path):
    snap = _base(fetched_at="2026-12-05T00:10:00Z")
    conn = _full_db(tmp_path / "s.db")
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
            card="latest",
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "unavailable"
    assert "COVERAGE_GAP" in res["stages"]["prs"][0]["codes"]
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert "COVERAGE_GAP" in stage["codes"]
    assert res["verdicts"]["prs"] != "FAIL"


def test_feed_at_300_rows_short_of_window_start_unavailable(tmp_path):
    snap = _base(estop="last_page", erows=300)
    conn = _full_db(tmp_path / "s.db")
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
            card="latest",
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "unavailable"
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert "COVERAGE_GAP" in stage["codes"]
    assert res["verdicts"]["prs"] != "FAIL"


def test_truncated_pull_list_unavailable(tmp_path):
    snap = _base()
    snap["coverage"]["pulls"] = {
        "rows": 1000,
        "oldest": "2026-10-30T00:00:00Z",
        "newest": "2026-10-30T01:00:00Z",
        "stop": "page_cap",
    }
    conn = _full_db(tmp_path / "s.db")
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
            card="latest",
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "unavailable"
    assert "COVERAGE_GAP" in res["stages"]["prs"][0]["codes"]
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert "COVERAGE_GAP" in stage["codes"]
    assert res["verdicts"]["prs"] != "FAIL"


def test_feed_refused_but_oldest_covers_window(tmp_path):
    snap = _base(estop="github_pagination_refusal")
    snap["coverage"]["events"]["oldest"] = "2026-10-27T00:00:00Z"
    conn = _db(tmp_path / "s.db")
    try:
        res = C.run_compare(
            snap, conn, as_of="2026-10-31T00:05:00+00:00", metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "match"
    assert "COVERAGE_GAP" not in res["stages"]["prs"][0]["codes"]


def test_pull_list_without_30_day_limit():
    snap = _base(fetched_at="2026-12-10T00:10:00Z")
    out = R.recount(snap, R.parse_instant("2026-10-31T00:05:00+00:00"), USER, REPO)
    assert out["coverage"]["events"]["ok"] is False
    assert out["coverage"]["pulls"]["ok"] is True
    assert out["coverage"]["activity"]["ok"] is True


def test_feed_settled_false_under_6_hours():
    as_of = R.parse_instant("2026-10-31T00:05:00+00:00")
    assert (
        R.recount(_base("2026-10-31T01:00:00Z"), as_of, USER, REPO)["feed_settled"]
        is False
    )
    assert (
        R.recount(_base("2026-10-31T07:00:00Z"), as_of, USER, REPO)["feed_settled"]
        is True
    )
