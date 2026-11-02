"""Source-audit withheld keys and the window guard (Ticket E2 plan, open-hour file)."""

import sqlite3

from source_audit import compare as C

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
AS_OF = "2026-10-31T00:05:00+00:00"


def _snapshot():
    pulls = [
        {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER},
    ]
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
        "pulls": pulls,
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


def _db(path, snapshot_json, facts_window=None):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, type TEXT,"
        " time TEXT, source_id TEXT, data TEXT, tier TEXT, collected_at TEXT,"
        " collector_version TEXT)"
    )
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, model_id TEXT, prompt_hash TEXT, latency_ms INTEGER,"
        " raw_valid INTEGER, is_noop INTEGER, noop_reason TEXT, snapshot TEXT,"
        " passes TEXT, dropped_codes TEXT, kept_count INTEGER,"
        " dropped_count INTEGER)"
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?, 'm', 'h', 0, 1, 0, NULL,"
        " ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, snapshot_json),
    )
    if facts_window is not None:
        conn.execute(
            "INSERT INTO facts VALUES ('c1', 1, 'f1', ?, ?, ?, 'none', '[]', 'code')",
            (SUBJECT, facts_window[0], facts_window[1]),
        )
    conn.commit()
    return conn


def test_open_hour_rows_excluded_from_set_comparison(tmp_path):
    snap = _snapshot()
    snap["events"] = [
        {
            "id": "7",
            "type": "PullRequestEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": "2026-10-31T00:02:00Z",
            "action": "opened",
            "pr_number": 7,
            "push_id": None,
            "head": None,
            "before": None,
        },
    ]
    snap["pulls"] = [
        {"number": 7, "created_at": "2026-10-31T00:02:00Z", "author": USER},
    ]
    snap["coverage"]["events"]["rows"] = 1
    snap["coverage"]["events"]["oldest"] = "2026-10-31T00:02:00Z"
    snap["coverage"]["events"]["newest"] = "2026-10-31T00:02:00Z"
    snap["coverage"]["pulls"]["rows"] = 1
    snap["coverage"]["pulls"]["oldest"] = "2026-10-31T00:02:00Z"
    snap["coverage"]["pulls"]["newest"] = "2026-10-31T00:02:00Z"
    stored = '{"period.earlier.prs": 0, "period.prior.prs": 0, "github.pr.count": 0}'
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    assert res["stages"]["prs"][0]["status"] == "match"
    assert res["stages"]["prs"][0]["total"] == 0
    from source_audit import recount as R

    assert R.recount(snap, R.parse_instant(AS_OF), USER, REPO)["prs"]["open"] == 1


def test_missing_last_key_unavailable_when_source_zero(tmp_path):
    snap = _snapshot()
    stored = '{"period.earlier.prs": 0, "period.prior.prs": 1, "github.pr.count": 1}'
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    stage2 = res["stages"]["prs"][1]
    assert stage2["status"] == "unavailable"
    assert "STORED_PERIOD_WITHHELD" in stage2["codes"]
    assert stage2["last"] is None


def test_missing_last_key_mismatch_when_source_positive(tmp_path):
    snap = _snapshot()
    snap["pulls"].append(
        {"number": 9, "created_at": "2026-10-30T01:00:00Z", "author": USER}
    )
    snap["events"].append(
        {
            "id": "9",
            "type": "PullRequestEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": "2026-10-30T01:00:00Z",
            "action": "opened",
            "pr_number": 9,
            "push_id": None,
            "head": None,
            "before": None,
        }
    )
    snap["coverage"]["events"]["rows"] = 2
    snap["coverage"]["pulls"]["rows"] = 2
    stored = '{"period.earlier.prs": 0, "period.prior.prs": 1, "github.pr.count": 2}'
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    stage2 = res["stages"]["prs"][1]
    assert stage2["status"] == "mismatch"
    assert "STORED_PERIOD_MISSING" in stage2["codes"]


def test_window_guard_stops_stage4_with_wrong_card_numbers(tmp_path):
    import json as _json

    snap = _snapshot()
    stored = (
        '{"period.earlier.prs": 9, "period.prior.prs": 9,'
        ' "period.last.prs": 9, "github.pr.count": 27}'
    )
    conn = _db(
        tmp_path / "s.db",
        stored,
        facts_window=("2026-10-31T00:05:00+00:00", "2026-11-03T00:05:00+00:00"),
    )
    slot = "2026-10-31T00:30:00+00:00"
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
            "slot": slot,
            "since_line": "First card, last 24h: nothing recorded.",
            "proposals": [],
            "statements": ["Pull requests rose from 9 in prior to 9 in last."],
        }
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-1', 'A', ?, ?, ?, 'b', 'p1', 'c',"
        " 'proposal', NULL, NULL)",
        (slot, SUBJECT, AS_OF),
    )
    conn.execute("INSERT INTO slot_card_payloads VALUES ('card-1', ?, 'null')", (card,))
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', 'card-1', NULL)",
        (slot,),
    )
    conn.commit()
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    for stage in res["stages"]["prs"][1:]:
        assert stage["status"] == "unavailable"
        assert "WINDOW_RULE_MISMATCH" in stage["codes"]
    assert res["verdicts"]["prs"] == "INCOMPLETE"


def test_pushes_plus_prs_stage2_merges_parents_no_false_fail(tmp_path):
    import json as _json

    base = _snapshot()
    stored = _json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 1,
            "period.last.prs": 0,
            "github.pr.count": 1,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
            "period.last.pushes": 0,
        }
    )
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(base), conn, as_of=AS_OF, metric="pushes_plus_prs", subject=SUBJECT
        )
    finally:
        conn.close()
    stage2 = res["stages"]["pushes_plus_prs"][1]
    assert stage2["status"] == "match"
    assert stage2["total"] == 1
    assert "STORED_PERIOD_MISSING" not in stage2["codes"]


def test_pushes_plus_prs_stage2_withheld_pushes_no_mismatch(tmp_path):
    import json as _json

    from source_audit import recount as R

    snap = _snapshot()
    snap["events"].append(
        {
            "id": "99",
            "type": "PushEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": "2026-10-31T00:02:00Z",
            "action": None,
            "pr_number": None,
            "push_id": 99,
            "head": "f" * 40,
            "before": "0" * 40,
        }
    )
    snap["coverage"]["events"]["rows"] = 2
    snap["coverage"]["events"]["newest"] = "2026-10-31T00:02:00Z"
    assert R.recount(snap, R.parse_instant(AS_OF), USER, REPO)["pushes"]["open"] == 1
    stored = _json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 1,
            "period.last.prs": 0,
            "github.pr.count": 1,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
        }
    )
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="pushes_plus_prs", subject=SUBJECT
        )
    finally:
        conn.close()
    stage2 = res["stages"]["pushes_plus_prs"][1]
    assert stage2["status"] != "mismatch"


def test_single_metric_missing_total_reads_zero_wrong(tmp_path):
    import json as _json

    snap = _snapshot()
    stored = _json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 1,
            "period.last.prs": 0,
        }
    )
    conn = _db(tmp_path / "s.db", stored)
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    stage2 = res["stages"]["prs"][1]
    assert stage2["status"] == "mismatch"
    assert "STORED_NUMBER_WRONG" in stage2["codes"]
    assert stage2["total"] == 0


def test_guard_failure_reports_null_diagnostics(tmp_path):
    snap = _snapshot()
    stored = (
        '{"period.earlier.prs": 1, "period.prior.prs": 0,'
        ' "period.last.prs": 0, "github.pr.count": 1}'
    )
    conn = _db(
        tmp_path / "s.db",
        stored,
        facts_window=("2026-10-31T00:05:00+00:00", "2026-11-03T00:05:00+00:00"),
    )
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["counted"] is None
    assert diag["late"] is None
    assert res["export"]["rows"][0]["rows_counted"] is None
    assert "rows_counted=-" in " ".join(res["lines"])


def test_pre_floor_cycle_hits_window_guard(tmp_path):
    snap = _snapshot()
    stored = (
        '{"period.earlier.prs": 1, "period.prior.prs": 0,'
        ' "period.last.prs": 0, "github.pr.count": 1}'
    )
    conn = _db(
        tmp_path / "s.db",
        stored,
        facts_window=("2026-10-31T00:05:00+00:00", "2026-11-03T00:05:00+00:00"),
    )
    try:
        res = C.run_compare(
            dict(snap), conn, as_of=AS_OF, metric="prs", subject=SUBJECT
        )
    finally:
        conn.close()
    for stage in res["stages"]["prs"][1:3]:
        assert stage["status"] == "unavailable"
        assert "WINDOW_RULE_MISMATCH" in stage["codes"]
    assert "WINDOW_RULE_MISMATCH" in " ".join(res["lines"])
