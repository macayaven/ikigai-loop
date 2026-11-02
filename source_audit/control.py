"""The four negative-control scenarios on made-up stores and snapshots."""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
import tempfile
from typing import Any

from source_audit import compare as C
from source_audit import store as ST

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
SLOT = "2026-10-31T00:30:00+00:00"


def _prs() -> list[tuple[int, str]]:
    """Return eight pull requests, all in last, none in the other periods."""
    times = ["01:00", "01:10", "01:20", "01:30", "02:00", "02:10", "02:20", "02:30"]
    return [(n + 1, f"2026-10-30T{when}:00Z") for n, when in enumerate(times)]


def _event(n: int, created: str, eid: str, action: str) -> dict[str, Any]:
    """Build one made-up feed row for a pull request."""
    row: dict[str, Any] = {
        "id": eid,
        "type": "PullRequestEvent",
        "repo": REPO,
        "actor": USER,
        "created_at": created,
        "action": action,
        "pr_number": n,
        "push_id": None,
        "head": None,
        "before": None,
    }
    return row


def _cov(rows: int, oldest: Any, newest: Any) -> dict[str, Any]:
    """Build one coverage block for the made-up snapshot."""
    return {"rows": rows, "oldest": oldest, "newest": newest, "stop": "last_page"}


def _snapshot(extra_feed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the made-up snapshot for one window."""
    prs = _prs()
    events: list[dict[str, Any]] = []
    for n, created in prs:
        events.append(_event(n, created, str(n), "opened"))
        events.append(_event(n, created, str(100 + n), "merged"))
    events.extend(extra_feed or [])
    pulls = [{"number": n, "created_at": created, "author": USER} for n, created in prs]
    stamps = [e["created_at"] for e in events]
    snap: dict[str, Any] = {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": _cov(len(events), min(stamps), max(stamps)),
            "pulls": _cov(len(pulls), min(stamps), max(stamps)),
            "activity": _cov(0, None, None),
        },
    }
    return snap


def _stored(prior: int, last: int) -> str:
    """Build a stored snapshot with pushes at zero and earlier empty."""
    stored = {
        "period.earlier.prs": 0,
        "period.prior.prs": prior,
        "period.last.prs": last,
        "github.pr.count": prior + last,
        "period.earlier.pushes": 0,
        "period.prior.pushes": 0,
        "period.last.pushes": 0,
    }
    return json.dumps(stored)


def _statement(prior: int, last: int) -> str:
    """Build the code-form fact statement for prior to last."""
    direction = "rose" if last > prior else "fell"
    return f"Pull requests {direction} from {prior} in prior to {last} in last."


def _put(conn: sqlite3.Connection, sql: str, rows: list[tuple]) -> None:
    """Insert every row with one statement; one builder for all tables."""
    conn.executemany(sql, rows)


def _db(
    path: str,
    stored: str,
    statement: str,
    refs: list[dict[str, Any]],
    extra_rows: list[tuple[str, str, str]] | None = None,
    chart_last: int = 0,
    since_line: str = "First card, last 24h: 8 pushes + PRs.",
) -> None:
    """Build the made-up store with T13 tables and a delivered row."""
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, source_id TEXT,"
        " type TEXT, time TEXT, collected_at TEXT, data TEXT);"
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT, as_of TEXT,"
        " snapshot TEXT);"
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, window_start TEXT, window_end TEXT,"
        " statement TEXT, origin TEXT);"
        "CREATE TABLE proposal_results (profile_id TEXT, cycle_id TEXT, run INTEGER,"
        " kind TEXT, slot TEXT, subject_id TEXT, briefing_json TEXT, snapshot TEXT);"
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT, card_id TEXT);"
        "CREATE TABLE slot_cards (card_id TEXT, slot TEXT, subject_id TEXT, as_of TEXT);"
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT, chart_json TEXT);"
    )
    rows = [
        (eid, SUBJECT, sid, created, json.dumps({"counts": {action: 1}}))
        for n, created in _prs()
        for eid, sid, action in (
            (f"o{n}", str(n), "opened"),
            (f"m{n}", str(100 + n), "merged"),
        )
    ]
    for eid, sid, created in extra_rows or []:
        rows.append((eid, SUBJECT, sid, created, json.dumps({"counts": {"opened": 1}})))
    events_sql = (
        "INSERT INTO events (id, subject_id, source, source_id, type, time,"
        " collected_at, data) VALUES (?, ?, 'github', ?, 'github.pr', ?,"
        " '2026-10-30T05:00:00+00:00', ?)"
    )
    _put(conn, events_sql, rows)
    _put(
        conn,
        "INSERT INTO cycles (cycle_id, run, subject_id, as_of, snapshot)"
        " VALUES ('c1', 1, ?, ?, ?)",
        [(SUBJECT, "2026-10-31T00:05:00+00:00", stored)],
    )
    _put(
        conn,
        "INSERT INTO facts (cycle_id, run, window_start, window_end, statement, origin)"
        " VALUES ('c1', 1, '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?, 'code')",
        [(statement,)],
    )
    claim: dict[str, Any] = {
        "id": "c-overall_state-1",
        "text": statement,
        "fact_ids": [],
        "metric_refs": refs,
    }
    sections = [
        {"type": "overall_state", "claims": [claim]},
        {"type": "since_last", "claims": []},
    ]
    briefing = json.dumps({"sections": sections})
    _put(
        conn,
        "INSERT INTO proposal_results (profile_id, cycle_id, run, kind, slot,"
        " subject_id, briefing_json, snapshot) VALUES ('p1', 'c1', 1, 'proposal', ?, ?, ?, ?)",
        [(SLOT, SUBJECT, briefing, stored)],
    )
    payload: dict[str, Any] = {
        "slot": SLOT,
        "since_line": since_line,
        "proposals": [{"letter": "A"}],
        "statements": [statement],
    }
    card = json.dumps(payload)
    pushes: dict[str, Any] = {
        "label": "pushes + PRs",
        "earlier": 0,
        "prior": 0,
        "last": chart_last,
    }
    chart = json.dumps({"pushes": pushes})
    _put(
        conn,
        "INSERT INTO slot_ledger (slot, step, outcome, card_id)"
        " VALUES (?, 'send', 'delivered', 'card-1')",
        [(SLOT,)],
    )
    _put(
        conn,
        "INSERT INTO slot_cards (card_id, slot, subject_id, as_of) VALUES ('card-1', ?, ?, ?)",
        [(SLOT, SUBJECT, "2026-10-31T00:05:00+00:00")],
    )
    _put(
        conn, "INSERT INTO slot_card_payloads VALUES ('card-1', ?, ?)", [(card, chart)]
    )
    conn.commit()
    conn.close()


def _refs(prior: int, last: int) -> list[dict[str, Any]]:
    """Build claim refs for prior and last."""
    return [
        {"metric_id": "period.prior.prs", "value": prior},
        {"metric_id": "period.last.prs", "value": last},
    ]


def _inputs(prior: int, last: int, extra_feed: Any = None) -> tuple:
    """Build the snapshot, stored text, statement, and refs for one case."""
    return (
        _snapshot(extra_feed),
        _stored(prior, last),
        _statement(prior, last),
        _refs(prior, last),
    )


def _scenario(
    folder: str,
    name: str,
    inputs: tuple,
    extra_rows: Any = None,
    chart_last: int = 0,
    since_line: str = "First card, last 24h: 8 pushes + PRs.",
    metric: str = "prs",
) -> dict[str, Any]:
    """Run one scenario through the real comparison code."""
    snap, stored, statement, refs = inputs
    _db(
        f"{folder}/{name}.db",
        stored,
        statement,
        refs,
        extra_rows,
        chart_last,
        since_line,
    )
    with contextlib.closing(ST.open_ro(f"{folder}/{name}.db")) as conn:
        return C.run_compare(snap, conn, metric=metric, subject=SUBJECT, card="latest")


def _periods(stage: dict[str, Any]) -> str:
    """Render one stage's period numbers with dashes where it has none."""
    return "/".join(
        "-" if v is None else str(v)
        for v in (stage["earlier"], stage["prior"], stage["last"])
    )


def _line(name: str, res: dict[str, Any], expected: str, extra: str = "") -> str:
    """Render one scenario line with numbers, the verdict, and the expected."""
    stages = res["stages"]["prs"]
    diag = res["diagnostics"]["prs"]
    line = (
        f"scenario={name} source={_periods(stages[0])} "
        f"stored={_periods(stages[1])} fact={_periods(stages[2])} "
        f"delivered={_periods(stages[3])} "
        f"rows_counted={diag['counted']} rows_not_in_snapshot={diag['not_in_snapshot']} "
        f"verdict={res['verdicts']['prs']} expected={expected}"
    )
    if extra:
        line += f" {extra}"
    return line


def _expect(res: dict[str, Any], verdict: str, total: int, periods: list[str]) -> bool:
    """Check one scenario's verdict, first total, and rendered periods."""
    stages = res["stages"]["prs"]
    return (
        res["verdicts"]["prs"] == verdict
        and stages[0]["total"] == total
        and [_periods(stage) for stage in stages] == periods
    )


def _since_line(name: str, res: dict[str, Any], expected: str) -> str:
    """Render the since-line scenario with its stated and recounted numbers."""
    since = res.get("since_line", {})
    return (
        f"scenario={name} stated={since.get('stated')} "
        f"recounted={since.get('recounted')} "
        f"verdict={res['verdicts']['pushes_plus_prs']} expected={expected}"
    )


def run_control() -> int:
    """Run the five scenarios; exit 0 only when each comes out as stated."""
    folder = tempfile.mkdtemp(prefix="source-audit-control-")
    try:
        clean = _scenario(folder, "clean", _inputs(0, 8), chart_last=8)
        doubled = _scenario(folder, "doubled", _inputs(0, 16), chart_last=16)
        extra = [("extra1", "extra-sid", "2026-10-30T04:00:00Z")]
        planted_row = _scenario(folder, "planted-row", _inputs(0, 9), extra, 9)
        dup_feed = [_event(3, "2026-10-30T01:20:00Z", "4242", "opened")]
        planted_snap = _scenario(
            folder, "planted-snap", _inputs(0, 8, dup_feed), chart_last=8
        )
        since_res = _scenario(
            folder,
            "since-line",
            _inputs(0, 8),
            chart_last=8,
            since_line="First card, last 24h: 16 pushes + PRs.",
            metric="pushes_plus_prs",
        )
        print(_line("clean", clean, "PASS"))
        print(_line("doubled", doubled, "FAIL"))
        missing = planted_row["diagnostics"]["prs"]["not_in_snapshot"]
        print(
            _line("planted-row", planted_row, "FAIL", f"rows_not_in_snapshot={missing}")
        )
        dups = len(planted_snap["identifiers"]["duplicate"])
        print(_line("planted-snap", planted_snap, "FAIL", f"duplicates={dups}"))
        print(_since_line("since-line", since_res, "FAIL"))
        ok = (
            _expect(clean, "PASS", 8, ["0/0/8", "0/0/8", "-/0/8", "-/0/8"])
            and _expect(doubled, "FAIL", 8, ["0/0/8", "0/0/16", "-/0/16", "-/0/16"])
            and doubled["stages"]["prs"][1]["status"] == "mismatch"
            and "STORED_NUMBER_WRONG" in doubled["stages"]["prs"][1]["codes"]
            and "STORED_PERIOD_MISSING" not in doubled["stages"]["prs"][1]["codes"]
            and doubled["stages"]["prs"][2]["status"] == "mismatch"
            and doubled["stages"]["prs"][3]["status"] == "mismatch"
            and _expect(planted_row, "FAIL", 8, ["0/0/8", "0/0/9", "-/0/9", "-/0/9"])
            and planted_row["stages"]["prs"][1]["status"] == "mismatch"
            and planted_row["diagnostics"]["prs"]["counted"] == 9
            and missing == 1
            and planted_snap["stages"]["prs"][0]["status"] == "mismatch"
            and "DUPLICATE_IN_SNAPSHOT" in planted_snap["stages"]["prs"][0]["codes"]
            and _expect(planted_snap, "FAIL", 8, ["0/0/8", "0/0/8", "-/0/8", "-/0/8"])
            and dups == 2
            and since_res["since_line"]["stated"] == 16
            and since_res["since_line"]["recounted"] == 8
            and since_res["stages"]["pushes_plus_prs"][3]["status"] == "mismatch"
            and "SINCE_LINE_WRONG" in since_res["stages"]["pushes_plus_prs"][3]["codes"]
            and since_res["verdicts"]["pushes_plus_prs"] == "FAIL"
        )
        return 0 if ok else 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)
