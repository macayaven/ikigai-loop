"""Source-audit events-only store (Ticket E2 plan, events-only file)."""

import sqlite3

from source_audit import compare as C

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"


def _snapshot():
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": [
            {
                "id": "1",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-29T01:00:00Z",
                "action": "opened",
                "pr_number": 1,
                "push_id": None,
                "head": None,
                "before": None,
            },
        ],
        "pulls": [
            {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER},
        ],
        "activity": [],
        "coverage": {
            "events": {
                "rows": 1,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T01:00:00Z",
                "stop": "last_page",
            },
            "pulls": {
                "rows": 1,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T01:00:00Z",
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


def _snapshot_for(prs, open_prs=()):
    events = []
    for number, created in prs:
        events.append(
            {
                "id": str(number),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created,
                "action": "opened",
                "pr_number": number,
                "push_id": None,
                "head": None,
                "before": None,
            },
        )
    for number, created in open_prs:
        events.append(
            {
                "id": str(100 + number),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created,
                "action": "opened",
                "pr_number": number,
                "push_id": None,
                "head": None,
                "before": None,
            },
        )
    pulls = [{"number": n, "created_at": c, "author": USER} for n, c in prs]
    pulls += [{"number": n, "created_at": c, "author": USER} for n, c in open_prs]
    times = sorted(e["created_at"] for e in events)
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(events),
                "oldest": times[0],
                "newest": times[-1],
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": min(p["created_at"] for p in pulls),
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


def _store_with_rows(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, type TEXT,"
        " time TEXT, source_id TEXT, data TEXT, tier TEXT, collected_at TEXT,"
        " collector_version TEXT)"
    )
    for eid, created, sid, collected in rows:
        conn.execute(
            "INSERT INTO events VALUES (?, ?, 'github', 'github.pr', ?, ?,"
            " '{\"counts\": {\"opened\": 1}}', 'public', ?, 'v')",
            (eid, SUBJECT, created, sid, collected),
        )
    conn.commit()
    return conn


def test_events_only_store_unavailable_not_crash(tmp_path):
    db = tmp_path / "events.db"
    conn = sqlite3.connect(db)
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
    try:
        res = C.run_compare(
            _snapshot(),
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    assert res["exit"] == 3
    assert res["stages"]["prs"][0]["status"] == "match"
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert stage["earlier"] is None
        assert stage["prior"] is None
        assert stage["last"] is None
        assert stage["total"] is None
    for line in res["lines"]:
        if line.startswith("metric=prs stage=") and "stage=1" not in line:
            assert "earlier=-" in line
            assert "prior=-" in line
            assert "last=-" in line
            assert "total=-" in line


def test_no_window_still_prints_stages_verdicts_and_limits(tmp_path):
    import json as _json

    snap = _snapshot()
    conn = _store_with_rows(
        tmp_path / "store.db",
        [("e1", "2026-10-29T01:00:00+00:00", "1", "2026-10-29T05:00:00+00:00")],
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
    card = _json.dumps({"slot": "2026-10-31T00:30:00+00:00", "statements": []})
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-1', 'A', '2026-10-31T00:30:00+00:00',"
        f" '{SUBJECT}', '2026-10-31T00:05:00+00:00', 'b', 'p1', 'c',"
        " 'proposal', NULL, NULL)"
    )
    conn.execute("INSERT INTO slot_card_payloads VALUES ('card-1', ?, 'null')", (card,))
    conn.execute(
        "INSERT INTO slot_ledger VALUES ('2026-10-31T00:30:00+00:00', 'send',"
        " 'delivered', 'card-1', NULL)"
    )
    conn.commit()
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["export"]["window_start"] is None
    assert len(res["export"]["stages"]) > 0
    assert len(res["export"]["verdicts"]) > 0
    text = "\n".join(res["lines"])
    assert "metric=prs stage=" in text
    assert "metric=prs verdict=" in text
    from source_audit.limits import LIMITS as _LIMITS

    for code in _LIMITS:
        if code == "LIMIT_FEED_MAY_SETTLE":
            continue
        assert _LIMITS[code] in res["lines"]
    assert res["lines"][-1] in _LIMITS.values()


def test_events_only_diagnostics_count_real_rows(tmp_path):
    snap = _snapshot_for([(n, "2026-10-29T01:00:00Z") for n in range(1, 4)])
    rows = [
        (f"e{n}", "2026-10-29T01:00:00+00:00", str(n), "2026-10-29T05:00:00+00:00")
        for n in range(1, 19)
    ]
    conn = _store_with_rows(tmp_path / "store.db", rows)
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["counted"] == 18
    assert diag["late"] == 0
    assert diag["not_in_snapshot"] == 15
    assert diag["items"] == 0
    assert diag["rows_unreadable"] == 0


def test_open_hour_public_item_not_reported_missing(tmp_path):
    snap = _snapshot_for(
        [(1, "2026-10-29T01:00:00Z")], open_prs=[(7, "2026-10-31T00:02:00Z")]
    )
    conn = _store_with_rows(
        tmp_path / "store.db",
        [("e1", "2026-10-29T01:00:00+00:00", "1", "2026-10-29T05:00:00+00:00")],
    )
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["counted"] == 1
    assert diag["items"] == 0
    assert "ITEMS_NOT_STORED" not in diag["codes"]


def test_pull_list_item_without_feed_row_reported(tmp_path):
    snap = _snapshot_for([(1, "2026-10-29T01:00:00Z")])
    snap["pulls"].append(
        {"number": 5, "created_at": "2026-10-29T02:00:00Z", "author": USER}
    )
    snap["coverage"]["pulls"]["rows"] = 2
    conn = _store_with_rows(
        tmp_path / "store.db",
        [("e1", "2026-10-29T01:00:00+00:00", "1", "2026-10-29T05:00:00+00:00")],
    )
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["items"] == 1
    assert "ITEMS_NOT_STORED" in diag["codes"]
    assert {"repo": REPO, "item": "5"} in res["identifiers"]["item_not_stored"]


def test_late_only_item_reported_as_late(tmp_path):
    snap = _snapshot_for([(1, "2026-10-29T01:00:00Z")])
    conn = _store_with_rows(
        tmp_path / "store.db",
        [("e1", "2026-10-29T01:00:00+00:00", "1", "2026-10-31T00:06:00+00:00")],
    )
    try:
        res = C.run_compare(
            snap,
            conn,
            as_of="2026-10-31T00:05:00+00:00",
            metric="prs",
            subject=SUBJECT,
        )
    finally:
        conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["late"] == 1
    assert diag["counted"] == 0
    assert diag["items"] == 0
    assert "ROWS_COLLECTED_LATE" in diag["codes"]
    assert "ITEMS_NOT_STORED" not in diag["codes"]
