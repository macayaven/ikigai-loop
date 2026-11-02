"""Source-audit stages, parser, and control exit path (Ticket E2 plan, stages file)."""

import json
import sqlite3

from source_audit import compare as C
from source_audit import control as CTL
from source_audit import parse as P
from source_audit import store as ST

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
AS_OF = "2026-10-31T00:05:00+00:00"
SLOT = "2026-10-31T00:30:00+00:00"


def _snapshot(prs=((1, "2026-10-29T01:00:00Z"),), extra_events=()):
    events = [
        {
            "id": str(n),
            "type": "PullRequestEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": created,
            "action": "opened",
            "pr_number": n,
            "push_id": None,
            "head": None,
            "before": None,
        }
        for n, created in prs
    ]
    events.extend(extra_events)
    pulls = [{"number": n, "created_at": created, "author": USER} for n, created in prs]
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
                "oldest": times[0] if times else None,
                "newest": times[-1] if times else None,
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": min((p["created_at"] for p in pulls), default=None),
                "newest": max((p["created_at"] for p in pulls), default=None),
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


def _stored(earlier=0, prior=1, last=0, count=1):
    return json.dumps(
        {
            "period.earlier.prs": earlier,
            "period.prior.prs": prior,
            "period.last.prs": last,
            "github.pr.count": count,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
            "period.last.pushes": 0,
        }
    )


def _db(path, stored, facts=(), results=(), cards=None, ledger=()):
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
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?, 'm', 'h', 0, 1, 0, NULL,"
        " ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, stored),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    for i, statement in enumerate(facts):
        conn.execute(
            "INSERT INTO facts VALUES ('c1', 1, ?, ?,"
            " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
            " '[]', 'code')",
            (f"f{i}", SUBJECT, statement),
        )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    for key, kind, briefing in results:
        conn.execute(
            "INSERT INTO proposal_results VALUES (?, 'c1', 1, 'p1', ?, ?, ?,"
            " ?, NULL, ?, NULL, NULL, '[]', 1.0)",
            (key, SUBJECT, SLOT, kind, briefing, stored),
        )
    if cards is not None:
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
        for card_id, card_json, chart_json in cards:
            conn.execute(
                "INSERT INTO slot_cards VALUES (?, 'A', ?, ?, ?, 'b', 'p1',"
                " 'c', 'proposal', NULL, NULL)",
                (card_id, SLOT, SUBJECT, AS_OF),
            )
            conn.execute(
                "INSERT INTO slot_card_payloads VALUES (?, ?, ?)",
                (card_id, card_json, chart_json),
            )
        for slot, step, outcome, card_id in ledger:
            conn.execute(
                "INSERT INTO slot_ledger VALUES (?, ?, ?, ?, NULL)",
                (slot, step, outcome, card_id),
            )
    conn.commit()
    return conn


def _briefing(claims):
    return json.dumps(
        {
            "sections": [
                {"type": "overall_state", "claims": claims},
                {"type": "since_last", "claims": []},
            ]
        }
    )


def _card(statements):
    return json.dumps(
        {
            "slot": SLOT,
            "since_line": "First card, last 24h: nothing recorded.",
            "proposals": [{"letter": "A"}],
            "statements": statements,
        }
    )


def _compare(snap, conn, **kw):
    args = {"as_of": AS_OF, "metric": "prs", "subject": SUBJECT}
    args.update(kw)
    if args.get("card") is not None:
        args.pop("as_of", None)
    try:
        return C.run_compare(snap, conn, **args)
    finally:
        conn.close()


def test_snapshot_diverges(tmp_path):
    snap = _snapshot()
    other = json.loads(_stored())
    other["period.prior.prs"] = 9
    briefing = _briefing([{"id": "c1", "text": "x", "fact_ids": [], "metric_refs": []}])
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    conn.execute("UPDATE proposal_results SET snapshot = ?", (json.dumps(other),))
    conn.commit()
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    assert "SNAPSHOT_DIVERGES" in res["stages"]["prs"][1]["codes"]


def _delta_briefing(delta_text, delta_value):
    return json.dumps(
        {
            "sections": [
                {
                    "type": "overall_state",
                    "claims": [
                        {
                            "id": "c1",
                            "text": "Pull requests rose from 0 in earlier to 1 in prior.",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.earlier.prs", "value": 0},
                                {"metric_id": "period.prior.prs", "value": 1},
                            ],
                        }
                    ],
                },
                {
                    "type": "since_last",
                    "claims": [
                        {
                            "id": "c2",
                            "text": delta_text,
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.prior.prs", "value": delta_value}
                            ],
                        }
                    ],
                },
            ]
        }
    )


def test_since_last_counted_never_compared(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    differing = "Pull requests rose from 0 in prior to 9 in last."
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", _delta_briefing(differing, 9))],
        cards=[("card-1", _card([statement, differing]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["status"] == "match", res["stages"]["prs"][3]
    assert "CARD_DELTA_NOT_AUDITED" in res["delta_codes"]
    assert res["deltas_not_audited"] == 1
    assert res["export"]["deltas_not_audited"] == 1
    equal = "Pull requests fell from 1 in prior to 0 in last."
    conn = _db(
        tmp_path / "s2.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", _delta_briefing(equal, 0))],
        cards=[("card-1", _card([statement, equal]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["status"] == "match", res["stages"]["prs"][3]
    assert res["deltas_not_audited"] == 1


def test_subject_filter_and_sided_cards(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    briefing = _briefing(
        [
            {
                "id": "c1",
                "text": statement,
                "fact_ids": [],
                "metric_refs": [{"metric_id": "period.prior.prs", "value": 1}],
            }
        ]
    )
    conn = sqlite3.connect(tmp_path / "s.db")
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
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?, 'm', 'h', 0, 1, 0, NULL,"
        " ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, _stored()),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
        " '[]', 'code')",
        (SUBJECT, statement),
    )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, 'p1', ?, ?,"
        " 'proposal', ?, NULL, ?, NULL, NULL, '[]', 1.0)",
        (SUBJECT, SLOT, briefing, _stored()),
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
    other_card = _card(["Pull requests rose from 9 in earlier to 9 in prior."])
    for letter in ("A", "B"):
        conn.execute(
            "INSERT INTO slot_cards VALUES ('card-1', ?, ?, ?, ?, 'b', 'p1',"
            " 'c', 'proposal', NULL, NULL)",
            (letter, SLOT, SUBJECT, AS_OF),
        )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-9', 'A', ?, 'other-subject', ?,"
        " 'b', 'p1', 'c', 'proposal', NULL, NULL)",
        (SLOT, AS_OF),
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES ('card-1', ?, 'null')",
        (_card([statement]),),
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES ('card-9', ?, 'null')", (other_card,)
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', 'card-1', NULL)",
        (SLOT,),
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', 'card-9', NULL)",
        (SLOT,),
    )
    conn.commit()
    res = C.run_compare(snap, conn, card="latest", metric="prs", subject=SUBJECT)
    conn.close()
    assert res["stages"]["prs"][3]["status"] == "match", res["stages"]["prs"][3]


def test_feed_topic_statement_stays_out(tmp_path):
    snap = _snapshot()
    statement = "I saw 9 feed items about push notifications in the last 24 hours."
    conn = _db(tmp_path / "s.db", _stored(), facts=[statement])
    res = _compare(snap, conn, metric="all")
    assert res["stages"]["pushes"][2]["status"] == "unavailable"
    assert "FACT_NONE_FOUND" in res["stages"]["pushes"][2]["codes"]


def test_parser_tiers(tmp_path):
    snap = _snapshot()
    conn = _db(
        tmp_path / "t1.db",
        _stored(),
        facts=["Pull requests rose from 0 in earlier to 1 in prior."],
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "match"
    conn = _db(
        tmp_path / "t2.db", _stored(), facts=["One pull request in the last 24 hours."]
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "mismatch"
    conn = _db(
        tmp_path / "t3.db", _stored(), facts=["Pull requests and pushes rose to 5."]
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "unavailable"
    assert "FACT_UNPARSED" in res["stages"]["prs"][2]["codes"]
    conn = _db(
        tmp_path / "t4.db", _stored(), facts=["I made 2.5 pull requests in prior."]
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "unavailable"
    conn = _db(
        tmp_path / "t5.db",
        _stored(),
        facts=["The push-review queue is long with 3 items."],
    )
    res = _compare(snap, conn, metric="all")
    assert res["stages"]["pushes"][2]["status"] == "unavailable"
    conn = _db(tmp_path / "t6.db", _stored(), facts=["Eight pull requests in prior."])
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "mismatch"


def test_fallback_never_match(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    conn = sqlite3.connect(tmp_path / "s.db")
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
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?, 'm', 'h', 0, 1, 0, NULL,"
        " ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, _stored()),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
        " '[]', 'code')",
        (SUBJECT, statement),
    )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, 'p1', ?, ?,"
        " 'fallback', NULL, '{}', ?, NULL, NULL, '[]', 1.0)",
        (SUBJECT, SLOT, _stored()),
    )
    conn.execute(
        "CREATE TABLE telegram_cards (card_id TEXT, card_json TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO telegram_cards VALUES ('card-9', ?, 't')", (_card([statement]),)
    )
    conn.commit()
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["status"] == "unavailable"
    assert "DELIVERY_NOT_PROVEN" in res["stages"]["prs"][3]["codes"]


def test_ticket13_not_delivered_shapes(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    card = _card([statement])
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", _briefing([]))],
        cards=[("card-1", card, "null")],
        ledger=[(SLOT, "send_intent", "ok", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["status"] == "unavailable"
    assert "CARD_NOT_FOUND" in res["stages"]["prs"][3]["codes"]
    conn = _db(
        tmp_path / "s2.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", _briefing([]))],
        cards=[("card-1", card, "null")],
        ledger=[(SLOT, "send", "DELIVERY_UNKNOWN", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["status"] == "unavailable"
    assert "CARD_NOT_FOUND" in res["stages"]["prs"][3]["codes"]


def test_activity_unmatched_changes_no_status(tmp_path):
    snap = _snapshot()
    conn = _db(tmp_path / "s.db", _stored())
    plain = _compare(snap, conn, metric="all")
    snap["activity"] = [
        {
            "id": "50",
            "timestamp": "2026-10-29T03:00:00Z",
            "activity_type": "pr_merge",
            "before": "b" * 40,
            "after": "a" * 40,
            "actor": USER,
        }
    ]
    snap["coverage"]["activity"] = {
        "rows": 1,
        "oldest": "2026-10-29T03:00:00Z",
        "newest": "2026-10-29T03:00:00Z",
        "stop": "last_page",
    }
    conn = _db(tmp_path / "s2.db", _stored())
    with_activity = _compare(snap, conn, metric="all")
    for metric in ("prs", "pushes", "pushes_plus_prs"):
        assert [s["status"] for s in plain["stages"][metric]] == [
            s["status"] for s in with_activity["stages"][metric]
        ]
    for res in (plain, with_activity):
        assert res["stages"]["pushes"][0]["codes"] == ["NO_INDEPENDENT_SOURCE"]


def test_activity_unmatched_uses_head_sha_exact_counts(tmp_path):
    from source_audit import recount as R
    from source_audit import stages as S

    head_a = "a" * 40
    head_b = "b" * 40
    head_c = "c" * 40
    head_d = "d" * 40
    snap = _snapshot(prs=())
    snap["events"] = [
        {
            "id": "11",
            "type": "PushEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": "2026-10-29T01:00:00Z",
            "action": None,
            "pr_number": None,
            "push_id": 11,
            "head": head_a,
            "before": "0" * 40,
        },
        {
            "id": "12",
            "type": "PushEvent",
            "repo": REPO,
            "actor": USER,
            "created_at": "2026-10-29T02:00:00Z",
            "action": None,
            "pr_number": None,
            "push_id": 12,
            "head": head_b,
            "before": "0" * 40,
        },
    ]
    snap["pulls"] = []
    snap["activity"] = [
        {
            "id": "21",
            "timestamp": "2026-10-29T01:30:00Z",
            "activity_type": "pr_merge",
            "before": "0" * 40,
            "after": head_a,
            "actor": USER,
        },
        {
            "id": "22",
            "timestamp": "2026-10-29T02:30:00Z",
            "activity_type": "branch_creation",
            "before": "0" * 40,
            "after": head_b,
            "actor": USER,
        },
        {
            "id": "23",
            "timestamp": "2026-10-29T03:00:00Z",
            "activity_type": "pr_merge",
            "before": "0" * 40,
            "after": head_c,
            "actor": USER,
        },
        {
            "id": "24",
            "timestamp": "2026-10-29T04:00:00Z",
            "activity_type": "branch_creation",
            "before": "0" * 40,
            "after": head_d,
            "actor": USER,
        },
    ]
    snap["coverage"]["events"] = {
        "rows": 2,
        "oldest": "2026-10-29T01:00:00Z",
        "newest": "2026-10-29T02:00:00Z",
        "stop": "last_page",
    }
    snap["coverage"]["activity"] = {
        "rows": 4,
        "oldest": "2026-10-29T01:30:00Z",
        "newest": "2026-10-29T04:00:00Z",
        "stop": "last_page",
    }
    as_of = R.parse_instant(AS_OF)
    count = R.recount(snap, as_of, USER, REPO)
    unmatched = S.activity_unmatched(count, snap)
    assert unmatched == {"pr_merge": 1, "branch_creation": 1}


def test_per_repo_breakdown_and_other_repos(tmp_path):
    snap = _snapshot(
        prs=(
            (1, "2026-10-29T01:00:00Z"),
            (2, "2026-10-29T02:00:00Z"),
        )
    )
    snap["events"].append(
        {
            "id": "9",
            "type": "PullRequestEvent",
            "repo": "synthetic-owner/synthetic-other",
            "actor": USER,
            "created_at": "2026-10-29T03:00:00Z",
            "action": "opened",
            "pr_number": 9,
            "push_id": None,
            "head": None,
            "before": None,
        }
    )
    snap["coverage"]["events"]["rows"] = 3
    conn = _db(tmp_path / "s.db", _stored(prior=3, count=3))
    res = _compare(snap, conn)
    assert res["stages"]["prs"][0]["status"] == "match"
    assert res["other_repos_feed_only"] == 1


def test_stored_fraction_and_float(tmp_path):
    prs = tuple((n, "2026-10-29T01:00:00Z") for n in range(1, 9))
    snap = _snapshot(prs=prs)
    conn = _db(
        tmp_path / "s.db",
        json.dumps(
            {
                "period.earlier.prs": 0,
                "period.prior.prs": 8.5,
                "period.last.prs": 0,
                "github.pr.count": 8,
            }
        ),
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    conn = _db(
        tmp_path / "s2.db",
        json.dumps(
            {
                "period.earlier.prs": 0,
                "period.prior.prs": 8.0,
                "period.last.prs": 0,
                "github.pr.count": 8,
            }
        ),
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][1]["status"] == "match"


def test_chart_match_mismatch_null(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    chart = json.dumps(
        {"pushes": {"label": "pushes + PRs", "earlier": 0, "prior": 1, "last": 0}}
    )
    briefing = _briefing([])
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([statement]), chart)],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT, metric="pushes_plus_prs")
    assert res["stages"]["pushes_plus_prs"][3]["status"] == "match"
    bad_chart = json.dumps(
        {"pushes": {"label": "pushes + PRs", "earlier": 0, "prior": 5, "last": 0}}
    )
    conn = _db(
        tmp_path / "s2.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([statement]), bad_chart)],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT, metric="pushes_plus_prs")
    assert res["stages"]["pushes_plus_prs"][3]["status"] == "mismatch"
    conn = _db(
        tmp_path / "s3.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT, metric="pushes_plus_prs")
    assert res["stages"]["pushes_plus_prs"][3]["status"] == "unavailable"
    assert "CHART_MISSING" in res["stages"]["pushes_plus_prs"][3]["codes"]


def test_noop_row_ignored_in_join(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    briefing = _briefing(
        [
            {
                "id": "c1",
                "text": statement,
                "fact_ids": [],
                "metric_refs": [{"metric_id": "period.prior.prs", "value": 1}],
            }
        ]
    )
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing), ("k2", "noop", "null")],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    conn.execute(
        "UPDATE proposal_results SET cycle_id = 'placeholder-cycle',"
        " snapshot = ? WHERE kind = 'noop'",
        (_stored(prior=9, count=9),),
    )
    conn.commit()
    res = _compare(snap, conn, card=SLOT)
    assert "CARD_CYCLE_AMBIGUOUS" not in res["stages"]["prs"][3]["codes"]
    assert "SNAPSHOT_DIVERGES" not in res["stages"]["prs"][1]["codes"]
    assert res["stages"]["prs"][1]["status"] == "match"
    assert res["stages"]["prs"][3]["status"] == "match"


def test_identifiers_use_snapshot_spelling(tmp_path):
    snap = _snapshot(prs=((1, "2026-10-29T01:00:00Z"), (2, "2026-10-29T02:00:00Z")))
    mixed = "Synthetic-Owner/Synthetic-Repo"
    snap["repo"] = mixed
    for event in snap["events"]:
        event["repo"] = mixed
    snap["pulls"] = [
        {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER},
        {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER},
    ]
    snap["coverage"]["pulls"]["rows"] = 2
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn)
    dups = res["identifiers"]["duplicate"]
    assert dups
    assert all(d["repo"] == mixed for d in dups), dups
    missing = [d for d in res["identifiers"]["disagree"] if str(d.get("item")) == "2"]
    assert missing
    assert all(d["repo"] == mixed for d in missing), missing
    assert all("event" in d for d in missing)


def test_identifiers_appear_once_with_metric_all(tmp_path):
    snap = _snapshot()
    snap["pulls"].append(
        {"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER}
    )
    snap["coverage"]["pulls"]["rows"] = 2
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn, metric="all")
    dups = res["identifiers"]["duplicate"]
    assert len(dups) == len(
        {(d.get("repo"), d.get("item"), d.get("event")) for d in dups}
    )
    assert len(dups) == 1


def test_wrong_stored_number_has_own_code_once(tmp_path):
    snap = _snapshot()
    conn = _db(
        tmp_path / "s.db",
        json.dumps(
            {
                "period.earlier.prs": 0,
                "period.prior.prs": 2,
                "period.last.prs": 0,
                "github.pr.count": 2,
            }
        ),
    )
    res = _compare(snap, conn)
    codes = res["stages"]["prs"][1]["codes"]
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    assert "STORED_NUMBER_WRONG" in codes
    assert "STORED_PERIOD_MISSING" not in codes
    assert codes.count("STORED_NUMBER_WRONG") == 1


def test_missing_earlier_key_stays_missing(tmp_path):
    snap = _snapshot()
    conn = _db(
        tmp_path / "s.db",
        json.dumps(
            {
                "period.prior.prs": 1,
                "period.last.prs": 0,
                "github.pr.count": 1,
            }
        ),
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    assert "STORED_PERIOD_MISSING" in res["stages"]["prs"][1]["codes"]
    assert "STORED_NUMBER_WRONG" not in res["stages"]["prs"][1]["codes"]


def test_non_numeric_sum_is_mismatch_not_crash(tmp_path):
    for bad in ('"eight"', "NaN", "Infinity"):
        stored = (
            '{"period.earlier.prs": 0, "period.prior.prs": ' + bad + ","
            ' "period.last.prs": 0, "github.pr.count": 1,'
            ' "period.earlier.pushes": 0, "period.prior.pushes": 0,'
            ' "period.last.pushes": 0}'
        )
        conn = _db(tmp_path / f"s-{bad}.db", stored)
        res = _compare(_snapshot(), conn, metric="pushes_plus_prs")
        assert res["stages"]["pushes_plus_prs"][1]["status"] == "mismatch"


def test_invalid_cycle_snapshot_is_unavailable(tmp_path):
    for pos, bad in enumerate(('{"unclosed":', "[1, 2]")):
        conn = _db(tmp_path / f"s-{pos}.db", bad)
        res = _compare(_snapshot(), conn)
        assert res["stages"]["prs"][1]["status"] == "unavailable"
        assert "STORE_JSON_INVALID" in res["stages"]["prs"][1]["codes"]


def test_invalid_card_briefing_chart_are_unavailable(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    briefing = _briefing([])
    conn = _db(
        tmp_path / "card.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", "{bad json", "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["codes"] == ["STORE_JSON_INVALID"]
    conn = _db(
        tmp_path / "briefing.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", "{bad json")],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["codes"] == ["STORE_JSON_INVALID"]
    conn = _db(
        tmp_path / "chart.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([statement]), "{bad json")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT, metric="pushes_plus_prs")
    assert res["stages"]["pushes_plus_prs"][3]["codes"] == ["STORE_JSON_INVALID"]


def test_bad_data_row_skipped_and_counted(tmp_path):
    snap = _snapshot()
    db_path = tmp_path / "s.db"
    conn = sqlite3.connect(db_path)
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
    conn.execute(
        "INSERT INTO events VALUES ('e2', ?, 'github', 'github.pr',"
        " '2026-10-29T02:00:00+00:00', '2', '{oops',"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
    )
    conn.commit()
    res = C.run_compare(snap, conn, as_of=AS_OF, metric="prs", subject=SUBJECT)
    conn.close()
    diag = res["diagnostics"]["prs"]
    assert diag["counted"] == 1
    assert diag["rows_unreadable"] == 1


def test_card_without_result_row_falls_back_to_latest_cycle(tmp_path):
    snap = _snapshot()
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    res = _compare(snap, conn, card=SLOT)
    assert res["stages"]["prs"][3]["codes"] == ["CARD_NO_RESULT_ROW"]
    assert res["stages"]["prs"][1]["status"] == "match", res["stages"]["prs"][1]
    assert res["stages"]["prs"][2]["status"] == "match", res["stages"]["prs"][2]


def test_parser_table_over_parse_statement():
    cases = [
        (
            "prs",
            "Pull requests rose from 2 in earlier to 3 in prior.",
            "parsed",
            {0: 2, 1: 3},
            None,
        ),
        (
            "pushes",
            "Pushes fell from 4 in prior to 1 in last.",
            "parsed",
            {1: 4, 2: 1},
            None,
        ),
        ("prs", "One pull request in the last 24 hours.", "parsed", {2: 1}, None),
        ("prs", "One pull request in the last 24h.", "parsed", {2: 1}, None),
        ("prs", "Pull requests and pushes rose to 5.", "unparsed", None, None),
        ("prs", "I made 2.5 pull requests in prior.", "unparsed", None, None),
        ("prs", "I made 12.25 pull requests in prior.", "unparsed", None, None),
        ("pushes", "Pushes were 3.5 and 2 in last.", "unparsed", None, None),
        ("prs", "Pull requests were up 50% in last.", "ignored", None, None),
        ("prs", "8 pull requests on Nov 1 in last.", "parsed", {2: 8}, None),
        ("prs", "pull requests on Nov 1 in last.", "ignored", None, None),
        ("prs", "8 pull requests on 1 November in last.", "parsed", {2: 8}, None),
        ("pushes", "I marked 3 pushes in prior.", "parsed", {1: 3}, None),
        ("pushes", "We decided on 2 pushes in last.", "parsed", {2: 2}, None),
        ("prs", "I made twenty-one pull requests in prior.", "unparsed", None, None),
        ("prs", "I made ~8 pull requests in prior.", "unparsed", None, None),
        ("prs", "Merged PR #25 with no other count.", "ignored", None, None),
        ("pushes", "Merged PR #25 with 8 pushes in prior.", "parsed", {1: 8}, None),
        ("pushes", "No pushes in last.", "parsed", {2: 0}, None),
        ("pushes", "Zero pushes in last.", "parsed", {2: 0}, None),
        ("prs", "One PR in prior.", "parsed", {1: 1}, None),
        ("prs", "One wonders about pull requests.", "ignored", None, None),
        (
            "pushes",
            "The push-review queue is long with 3 items.",
            "ignored",
            None,
            None,
        ),
        (
            "pushes",
            "I saw 9 feed items about push notifications in the last 24 hours.",
            "ignored",
            None,
            None,
        ),
        ("prs", "Eight pull requests in prior.", "parsed", {1: 8}, None),
        ("prs", "8 pull requests in earlier and prior.", "unparsed", None, None),
        (
            "prs",
            "Pull requests rose from 2 in earlier to 3 in last.",
            "unparsed",
            None,
            None,
        ),
    ]
    for metric, text, kind, periods, total in cases:
        result = P.parse_statement(text, metric)
        assert result["kind"] == kind, (text, result)
        if kind == "parsed":
            assert result.get("periods") == periods, (text, result)
            assert result.get("total") == total, (text, result)


def test_export_pins_every_key_and_value(tmp_path):
    from source_audit.limits import LIMITS

    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    briefing = _briefing(
        [
            {
                "id": "c1",
                "text": statement,
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "period.earlier.prs", "value": 0},
                    {"metric_id": "period.prior.prs", "value": 1},
                ],
            }
        ]
    )
    snap = _snapshot()
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing)],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    conn.execute(
        "INSERT INTO events VALUES ('e1', ?, 'github', 'github.pr',"
        " '2026-10-29T01:00:00+00:00', '1', '{\"counts\": {\"opened\": 1}}',"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
    )
    conn.commit()
    res = C.run_compare(
        snap, conn, as_of=AS_OF, metric="prs", subject=SUBJECT, card=SLOT
    )
    conn.close()
    limits = sorted(code for code in LIMITS if code != "LIMIT_FEED_MAY_SETTLE")
    assert res["export"] == {
        "window_start": "2026-10-28T00:00:00Z",
        "window_end": "2026-10-31T00:00:00Z",
        "fetched_at": "2026-10-31T07:00:00Z",
        "feed_settled": True,
        "delivery_proven": True,
        "limits": limits,
        "other_repos_feed_only": 0,
        "deltas_not_audited": 0,
        "card_window": None,
        "per_repo": [{"repo": REPO, "prs": 1, "pushes": 0}],
        "open_hour": [
            {"metric": "prs", "count": 0},
            {"metric": "pushes", "count": 0},
            {"metric": "pushes_plus_prs", "count": 0},
        ],
        "coverage": [
            {
                "source": "events",
                "rows": 1,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T01:00:00Z",
                "stop": "last_page",
            },
            {
                "source": "pulls",
                "rows": 1,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T01:00:00Z",
                "stop": "last_page",
            },
            {
                "source": "activity",
                "rows": 0,
                "oldest": None,
                "newest": None,
                "stop": "last_page",
            },
        ],
        "stages": [
            {
                "metric": "prs",
                "stage": "1",
                "status": "match",
                "earlier": 0,
                "prior": 1,
                "last": 0,
                "total": 1,
                "codes": [],
            },
            {
                "metric": "prs",
                "stage": "2",
                "status": "match",
                "earlier": 0,
                "prior": 1,
                "last": 0,
                "total": 1,
                "codes": [],
            },
            {
                "metric": "prs",
                "stage": "3",
                "status": "match",
                "earlier": 0,
                "prior": 1,
                "last": None,
                "total": None,
                "codes": [],
            },
            {
                "metric": "prs",
                "stage": "4",
                "status": "match",
                "earlier": 0,
                "prior": 1,
                "last": None,
                "total": None,
                "codes": [],
            },
        ],
        "verdicts": [{"metric": "prs", "verdict": "PASS"}],
        "rows": [
            {
                "metric": "prs",
                "rows_counted": 1,
                "rows_late": 0,
                "rows_not_in_snapshot": 0,
                "items_not_stored": 0,
                "rows_unreadable": 0,
                "codes": [],
            }
        ],
        "activity_unmatched": [],
        "identifiers": {"disagree": [], "duplicate": [], "item_not_stored": []},
        "statements": [],
        "since_line": {"stated": 0, "recounted": 0, "codes": []},
    }


def test_statements_list_only_wrong(tmp_path):
    snap = _snapshot()
    good = "Pull requests rose from 0 in earlier to 1 in prior."
    conn = _db(tmp_path / "s.db", _stored(), facts=[good])
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "match"
    assert res["identifiers"]["statements"] == []
    assert res["export"]["statements"] == []
    assert "statements=" not in " ".join(res["lines"])
    wrong = "Pull requests rose from 0 in earlier to 9 in prior."
    conn = _db(tmp_path / "s2.db", _stored(), facts=[good, wrong])
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "mismatch"
    assert res["identifiers"]["statements"] == [
        {"metric": "prs", "stage": "3", "item": "2"}
    ]
    assert res["export"]["statements"] == [{"metric": "prs", "stage": "3", "item": "2"}]


def _t13db(path, cards, cycle_as_of=None):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT, card_id TEXT,"
        " detail TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, letter TEXT, slot TEXT, subject_id TEXT,"
        " as_of TEXT, bucket TEXT, profile_id TEXT, commitment_id TEXT, kind TEXT,"
        " policy_pick TEXT, policy_alternative TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    for i, (slot, as_of, since_line) in enumerate(cards):
        card = json.dumps(
            {
                "slot": slot,
                "since_line": since_line,
                "proposals": [{"letter": "A"}],
                "statements": [],
            }
        )
        conn.execute(
            "INSERT INTO slot_cards VALUES (?, 'A', ?, ?, ?, 'b', 'p1', 'c',"
            " 'proposal', NULL, NULL)",
            (f"card-{i}", slot, SUBJECT, as_of),
        )
        conn.execute(
            "INSERT INTO slot_card_payloads VALUES (?, ?, 'null')", (f"card-{i}", card)
        )
        conn.execute(
            "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', ?, NULL)",
            (slot, f"card-{i}"),
        )
    if cycle_as_of is not None:
        stored = _stored()
        conn.execute(
            "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
            " as_of TEXT, model_id TEXT, prompt_hash TEXT, latency_ms INTEGER,"
            " raw_valid INTEGER, is_noop INTEGER, noop_reason TEXT, snapshot TEXT,"
            " passes TEXT, dropped_codes TEXT, kept_count INTEGER, dropped_count INTEGER)"
        )
        conn.execute(
            "INSERT INTO cycles VALUES ('c1', 1, ?, ?, 'm', 'h', 0, 1, 0,"
            " NULL, ?, '[]', '[]', 0, 0)",
            (SUBJECT, cycle_as_of, stored),
        )
        conn.execute(
            "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT, subject_id TEXT,"
            " window_start TEXT, window_end TEXT, statement TEXT, evidence TEXT,"
            " origin TEXT)"
        )
        conn.execute(
            "INSERT INTO facts VALUES ('c1', 1, 'f1', ?, '2026-10-27T00:00:00+00:00',"
            " '2026-10-30T00:00:00+00:00',"
            " 'Pull requests rose from 0 in earlier to 1 in prior.', '[]', 'code')",
            (SUBJECT,),
        )
        conn.execute(
            "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT, run INTEGER,"
            " profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT, briefing_json TEXT,"
            " fallback_json TEXT, snapshot TEXT, hour_start TEXT, hour_end TEXT,"
            " reason_codes TEXT, cycle_age_s REAL)"
        )
        conn.execute(
            "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, 'p1', ?, ?,"
            " 'proposal', '{\"sections\": []}', NULL, ?, NULL, NULL, '[]', 1.0)",
            (SUBJECT, cards[-1][0], stored),
        )
    conn.commit()
    return conn


def test_since_line_second_card_beside_recount_no_status(tmp_path):
    snap = _snapshot()
    first = (
        "2026-10-29T01:00:00+00:00",
        "2026-10-29T00:00:00+00:00",
        "First card, last 24h: code 1.2h.",
    )
    conn = _t13db(
        tmp_path / "s.db",
        [
            first,
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
                "Since 01:00: 5 pushes + PRs.",
            ),
        ],
        cycle_as_of="2026-10-30T00:00:00+00:00",
    )
    try:
        res = C.run_compare(
            snap,
            conn,
            metric="pushes_plus_prs",
            subject=SUBJECT,
            card="2026-10-30T01:00:00+00:00",
        )
        res_latest = C.run_compare(
            snap, conn, metric="pushes_plus_prs", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res["since_line"] == {
        "stated": 5,
        "recounted": 1,
        "codes": ["SINCE_LINE_WRONG"],
    }
    assert (
        "since_line_stated=5 since_line_recounted=1 codes=SINCE_LINE_WRONG"
        in res["lines"]
    )
    assert res_latest["since_line"] == res["since_line"]
    assert res["stages"]["pushes_plus_prs"][3]["status"] == "mismatch"
    assert "SINCE_LINE_WRONG" in res["stages"]["pushes_plus_prs"][3]["codes"]
    conn = _t13db(
        tmp_path / "s2.db",
        [
            first,
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
                "Since 01:00: 1 push + PR.",
            ),
        ],
        cycle_as_of="2026-10-30T00:00:00+00:00",
    )
    try:
        res2 = C.run_compare(
            snap,
            conn,
            metric="pushes_plus_prs",
            subject=SUBJECT,
            card="2026-10-30T01:00:00+00:00",
        )
    finally:
        conn.close()
    assert res2["since_line"] == {
        "stated": 1,
        "recounted": 1,
        "codes": [],
    }
    assert res2["stages"]["pushes_plus_prs"][3]["status"] != "mismatch" or (
        "SINCE_LINE_WRONG" not in res2["stages"]["pushes_plus_prs"][3]["codes"]
    )


def test_since_line_first_card_and_zero_forms(tmp_path):
    snap = _snapshot()
    conn = _t13db(
        tmp_path / "s.db",
        [
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T02:00:00+00:00",
                "First card, last 24h: code 1.2h.",
            )
        ],
    )
    try:
        res = C.run_compare(
            snap, conn, metric="prs", subject=SUBJECT, card="2026-10-30T01:00:00+00:00"
        )
    finally:
        conn.close()
    assert res["since_line"] == {
        "stated": 0,
        "recounted": 0,
        "codes": [],
    }
    assert P.parse_since_line("First card, last 24h: 1 push + PR.") == 1
    assert P.parse_since_line("First card, last 24h: 12 pushes + PRs.") == 12
    assert P.parse_since_line("Since 13:30: 1 push + PR.") == 1
    assert P.parse_since_line("Since 13:30: 12 pushes + PRs.") == 12
    assert P.parse_since_line("Since 13:30: code 1.2h.") == 0
    assert P.parse_since_line("Since 13:30: nothing new recorded.") == 0
    assert P.parse_since_line("First card, last 24h: code 1.2h.") == 0
    assert P.parse_since_line("First card, last 24h: nothing recorded.") == 0
    assert P.parse_since_line("Since 13:30: nothing recorded.") == 0
    assert P.parse_since_line("1 push + PR") is None
    assert P.parse_since_line("12 pushes + PRs") is None
    assert P.parse_since_line("one line") is None
    assert P.parse_since_line("5 pushes yesterday") is None
    assert P.parse_since_line("Since 13:30:") is None
    assert P.parse_since_line(None) is None
    assert P.parse_since_line(7) is None


def test_since_line_sentinel_states_nothing_and_leaks_nothing(tmp_path):
    sentinel = "plume-sentinel-9z"
    snap = _snapshot()
    conn = _t13db(
        tmp_path / "s.db",
        [
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T02:00:00+00:00",
                f"Since 13:30: {sentinel} recorded.",
            )
        ],
    )
    try:
        res = C.run_compare(
            snap, conn, metric="prs", subject=SUBJECT, card="2026-10-30T01:00:00+00:00"
        )
    finally:
        conn.close()
    assert res["since_line"]["stated"] is None
    blob = " ".join(res["lines"]) + json.dumps(res["export"])
    assert sentinel not in blob


def test_pick_sorts_on_instant_not_text_across_dst(tmp_path):
    import json as _json
    import sqlite3 as _sqlite
    from datetime import datetime as _dt

    early_slot = "2026-10-25T03:00:00+02:00"
    late_slot = "2026-10-25T01:30:00+00:00"
    assert early_slot > late_slot
    assert _dt.fromisoformat(early_slot) < _dt.fromisoformat(late_slot)
    conn = _sqlite.connect(tmp_path / "dst.db")
    conn.execute("CREATE TABLE telegram_cards (card_id TEXT, card_json TEXT)")
    for card_id, slot in (("card-early", early_slot), ("card-late", late_slot)):
        card = _json.dumps({"slot": slot, "proposals": [], "statements": []})
        conn.execute("INSERT INTO telegram_cards VALUES (?, ?)", (card_id, card))
    conn.commit()
    try:
        picked, code, _, _, _ = C._pick(conn, SUBJECT, "latest", None)
    finally:
        conn.close()
    assert code == "CARD_NO_RESULT_ROW"
    assert picked is not None
    assert picked["slot"] == _dt.fromisoformat(late_slot)


def test_since_line_fallback_card_reports_nulls(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    conn.execute("CREATE TABLE telegram_cards (card_id TEXT, card_json TEXT)")
    card = json.dumps(
        {
            "slot": SLOT,
            "since_line": "7 pushes + PRs",
            "proposals": [],
            "statements": [],
        }
    )
    conn.execute("INSERT INTO telegram_cards VALUES ('card-1', ?)", (card,))
    conn.commit()
    try:
        res = C.run_compare(_snapshot(), conn, metric="prs", subject=SUBJECT, card=SLOT)
    finally:
        conn.close()
    assert res["since_line"] == {
        "stated": None,
        "recounted": None,
        "codes": [],
    }


def test_since_line_unreadable_makes_stage_unavailable(tmp_path):
    snap = _snapshot()
    conn = _t13db(
        tmp_path / "s.db",
        [
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T02:00:00+00:00",
                "Since 13:30: plume wording here.",
            )
        ],
    )
    try:
        res = C.run_compare(
            snap,
            conn,
            metric="pushes_plus_prs",
            subject=SUBJECT,
            card="2026-10-30T01:00:00+00:00",
        )
    finally:
        conn.close()
    assert res["since_line"]["codes"] == ["SINCE_LINE_UNREADABLE"]
    assert res["stages"]["pushes_plus_prs"][3]["status"] == "unavailable"
    assert "SINCE_LINE_UNREADABLE" in res["stages"]["pushes_plus_prs"][3]["codes"]


def test_since_line_no_line_leaves_chart_alone(tmp_path):
    snap = _snapshot()
    conn = _t13db(
        tmp_path / "s.db",
        [
            (
                "2026-10-30T01:00:00+00:00",
                "2026-10-30T02:00:00+00:00",
                None,
            )
        ],
    )
    # _t13db writes None as JSON null; patch the card to miss the key
    try:
        res = C.run_compare(
            snap,
            conn,
            metric="pushes_plus_prs",
            subject=SUBJECT,
            card="2026-10-30T01:00:00+00:00",
        )
    finally:
        conn.close()
    assert res["since_line"]["stated"] is None
    assert "SINCE_LINE_WRONG" not in res["stages"]["pushes_plus_prs"][3]["codes"]
    assert "SINCE_LINE_UNREADABLE" not in res["stages"]["pushes_plus_prs"][3]["codes"]


def test_negative_control_exit_path(monkeypatch):
    real = C.run_compare

    def always_pass(*args, **kwargs):
        res = real(*args, **kwargs)
        for stages in res["stages"].values():
            for stage in stages:
                stage["status"] = "match"
                stage["codes"] = []
        for verdict in res["verdicts"]:
            res["verdicts"][verdict] = "PASS"
        return res

    def always_fail(*args, **kwargs):
        res = real(*args, **kwargs)
        for stages in res["stages"].values():
            for stage in stages:
                stage["status"] = "mismatch"
                stage["codes"] = ["X"]
        for verdict in res["verdicts"]:
            res["verdicts"][verdict] = "FAIL"
        return res

    monkeypatch.setattr(C, "run_compare", always_pass)
    assert CTL.run_control() == 1
    monkeypatch.setattr(C, "run_compare", always_fail)
    assert CTL.run_control() == 1


def _push_event(eid, created, push_id=77):
    return {
        "id": str(eid),
        "type": "PushEvent",
        "repo": REPO,
        "actor": USER,
        "created_at": created,
        "action": None,
        "pr_number": None,
        "push_id": push_id,
        "head": "c" * 40,
        "before": "d" * 40,
    }


def test_stage1_pull_without_feed_row_mismatches(tmp_path):
    snap = _snapshot(prs=((1, "2026-10-29T01:00:00Z"), (2, "2026-10-29T02:00:00Z")))
    snap["events"] = [e for e in snap["events"] if e["pr_number"] != 2]
    snap["coverage"]["events"]["rows"] = 1
    snap["coverage"]["events"]["newest"] = "2026-10-29T01:00:00Z"
    conn = _db(tmp_path / "s.db", _stored(prior=2, count=2))
    res = _compare(snap, conn)
    stage = res["stages"]["prs"][0]
    assert stage["status"] == "mismatch"
    assert stage["codes"] == ["SOURCE_SET_DISAGREE"]
    assert (stage["earlier"], stage["prior"], stage["last"], stage["total"]) == (
        0,
        2,
        0,
        2,
    )
    assert res["identifiers"]["disagree"] == [{"repo": REPO, "item": "2"}]


def test_stage1_feed_row_without_pull_mismatches(tmp_path):
    snap = _snapshot(
        prs=((1, "2026-10-29T01:00:00Z"),),
        extra_events=[
            {
                "id": "9",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-29T03:00:00Z",
                "action": "opened",
                "pr_number": 9,
                "push_id": None,
                "head": None,
                "before": None,
            }
        ],
    )
    conn = _db(tmp_path / "s.db", _stored(prior=1, count=1))
    res = _compare(snap, conn)
    stage = res["stages"]["prs"][0]
    assert stage["status"] == "mismatch"
    assert stage["codes"] == ["SOURCE_SET_DISAGREE"]
    assert (stage["earlier"], stage["prior"], stage["last"], stage["total"]) == (
        0,
        1,
        0,
        1,
    )
    assert res["identifiers"]["disagree"] == [{"repo": REPO, "item": "9", "event": "9"}]


def test_stage1_duplicate_push_mismatches_both_sums_counts_once(tmp_path):
    snap = _snapshot(prs=())
    snap["events"] = [
        _push_event(21, "2026-10-29T01:00:00Z"),
        _push_event(22, "2026-10-29T02:00:00Z"),
    ]
    snap["coverage"]["events"] = {
        "rows": 2,
        "oldest": "2026-10-29T01:00:00Z",
        "newest": "2026-10-29T02:00:00Z",
        "stop": "last_page",
    }
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn, metric="all")
    for metric in ("pushes", "pushes_plus_prs"):
        stage = res["stages"][metric][0]
        assert stage["status"] == "mismatch", (metric, stage)
        assert stage["codes"] == ["DUPLICATE_IN_SNAPSHOT"], (metric, stage)
        assert stage["total"] == 1, (metric, stage)
    assert res["stages"]["pushes"][0]["prior"] == 1
    dups = res["identifiers"]["duplicate"]
    assert {d.get("event") for d in dups} == {"21", "22"}
    assert {d.get("item") for d in dups} == {"77"}


def _sum_snapshot():
    return _snapshot(
        prs=((1, "2026-10-29T01:00:00Z"),),
        extra_events=[_push_event(21, "2026-10-29T02:00:00Z")],
    )


def _sum_stored(prs_prior, prs_count, pushes_prior, pushes_count):
    return json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": prs_prior,
            "period.last.prs": 0,
            "github.pr.count": prs_count,
            "period.earlier.pushes": 0,
            "period.prior.pushes": pushes_prior,
            "period.last.pushes": 0,
            "github.push.count": pushes_count,
        }
    )


def test_stage2_sum_takes_worse_parent_status(tmp_path):
    conn = _db(tmp_path / "s.db", _sum_stored(1, 1, 0, 0))
    res = _compare(_sum_snapshot(), conn, metric="all")
    assert res["stages"]["prs"][1]["status"] == "match"
    assert res["stages"]["pushes"][1]["status"] == "mismatch"
    assert "STORED_NUMBER_WRONG" in res["stages"]["pushes"][1]["codes"]
    stage = res["stages"]["pushes_plus_prs"][1]
    assert stage["status"] == "mismatch"
    assert "STORED_NUMBER_WRONG" in stage["codes"]
    assert (stage["earlier"], stage["prior"], stage["last"], stage["total"]) == (
        0,
        1,
        0,
        1,
    )
    conn = _db(tmp_path / "s2.db", _sum_stored(0, 0, 1, 1))
    res = _compare(_sum_snapshot(), conn, metric="all")
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    assert res["stages"]["pushes"][1]["status"] == "match"
    stage = res["stages"]["pushes_plus_prs"][1]
    assert stage["status"] == "mismatch"
    assert "STORED_NUMBER_WRONG" in stage["codes"]
    assert (stage["earlier"], stage["prior"], stage["last"], stage["total"]) == (
        0,
        1,
        0,
        1,
    )


def test_diagnostics_opened_row_not_stored_lists_identifiers(tmp_path):
    snap = _snapshot()
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn)
    diag = res["diagnostics"]["prs"]
    assert diag["items"] == 1
    assert "ITEMS_NOT_STORED" in diag["codes"]
    assert res["identifiers"]["item_not_stored"] == [
        {"repo": REPO, "item": "1", "event": "1"}
    ]


def test_diagnostics_push_not_stored_lists_identifiers(tmp_path):
    snap = _snapshot(prs=())
    snap["events"] = [_push_event(21, "2026-10-29T01:00:00Z")]
    snap["coverage"]["events"] = {
        "rows": 1,
        "oldest": "2026-10-29T01:00:00Z",
        "newest": "2026-10-29T01:00:00Z",
        "stop": "last_page",
    }
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn, metric="pushes")
    diag = res["diagnostics"]["pushes"]
    assert diag["items"] == 1
    assert "ITEMS_NOT_STORED" in diag["codes"]
    assert res["identifiers"]["item_not_stored"] == [{"item": "77", "event": "21"}]


def test_diagnostics_open_hour_push_never_not_stored(tmp_path):
    snap = _snapshot(prs=())
    snap["events"] = [_push_event(21, "2026-10-31T00:02:00Z")]
    snap["coverage"]["events"] = {
        "rows": 1,
        "oldest": "2026-10-31T00:02:00Z",
        "newest": "2026-10-31T00:02:00Z",
        "stop": "last_page",
    }
    conn = _db(tmp_path / "s.db", _stored())
    res = _compare(snap, conn, metric="pushes")
    assert res["diagnostics"]["pushes"]["items"] == 0
    assert res["identifiers"]["item_not_stored"] == []


def test_diagnostics_rows_outside_window_change_nothing(tmp_path):
    snap = _snapshot()
    plain = _db(tmp_path / "plain.db", _stored())
    res_plain = _compare(snap, plain)
    conn = _db(tmp_path / "s.db", _stored())
    for eid, sid, when in (
        ("e-early", "sid-early", "2026-10-27T23:59:00+00:00"),
        ("e-end", "sid-end", "2026-10-31T00:00:00+00:00"),
    ):
        conn.execute(
            "INSERT INTO events VALUES (?, ?, 'github', 'github.pr', ?, ?,"
            " '{\"counts\": {\"opened\": 1}}', 'public',"
            " '2026-10-29T05:00:00+00:00', 'v')",
            (eid, SUBJECT, when, sid),
        )
    conn.commit()
    res = _compare(snap, conn)
    for key in ("counted", "late", "not_in_snapshot", "rows_unreadable"):
        assert res["diagnostics"]["prs"][key] == 0, key
        assert res["diagnostics"]["prs"][key] == res_plain["diagnostics"]["prs"][key], (
            key
        )


def test_stage3_total_statement_matches_and_mismatches(tmp_path):
    prs = tuple((n, "2026-10-29T01:00:00Z") for n in range(1, 9))
    snap = _snapshot(prs=prs)
    conn = _db(
        tmp_path / "s.db",
        _stored(prior=8, count=8),
        facts=["I counted 9 pull requests."],
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "mismatch"
    assert res["stages"]["prs"][2]["codes"] == ["FACT_NUMBER_WRONG"]
    assert res["identifiers"]["statements"] == [
        {"metric": "prs", "stage": "3", "item": "1"}
    ]
    conn = _db(
        tmp_path / "s2.db",
        _stored(prior=8, count=8),
        facts=["I counted 8 pull requests."],
    )
    res = _compare(snap, conn)
    assert res["stages"]["prs"][2]["status"] == "match"


def test_latest_result_rowid_decides_cycle_snapshot_briefing(tmp_path):
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    briefing1 = _briefing(
        [
            {
                "id": "c1",
                "text": statement,
                "fact_ids": [],
                "metric_refs": [{"metric_id": "period.prior.prs", "value": 1}],
            }
        ]
    )
    briefing2 = _briefing(
        [
            {
                "id": "c1",
                "text": statement,
                "fact_ids": [],
                "metric_refs": [{"metric_id": "period.prior.prs", "value": 9}],
            }
        ]
    )
    conn = _db(
        tmp_path / "s.db",
        _stored(),
        facts=[statement],
        results=[("k1", "proposal", briefing1)],
        cards=[("card-1", _card([statement]), "null")],
        ledger=[(SLOT, "send", "delivered", "card-1")],
    )
    stored2 = _stored(prior=9, count=9)
    conn.execute(
        "INSERT INTO cycles VALUES ('c2', 1, ?, ?, 'm', 'h', 0, 1, 0, NULL,"
        " ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, stored2),
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c2', 1, 'f9', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
        " '[]', 'code')",
        (SUBJECT, statement),
    )
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k2', 'c2', 1, 'p1', ?, ?,"
        " 'proposal', ?, NULL, ?, NULL, NULL, '[]', 1.0)",
        (SUBJECT, SLOT, briefing2, stored2),
    )
    conn.commit()
    res = _compare(_snapshot(), conn, card=SLOT)
    assert res["stages"]["prs"][1]["status"] == "mismatch"
    assert res["stages"]["prs"][1]["total"] == 9
    assert res["stages"]["prs"][3]["status"] == "mismatch"
    assert res["identifiers"]["statements"] == [
        {"metric": "prs", "stage": "4", "item": "1"}
    ]


def test_latest_cycle_picks_by_instant_not_text_or_run():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, snapshot TEXT)"
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c-early-run2', 2, ?,"
        " '2026-10-31T02:00:00+02:00', '{}')",
        (SUBJECT,),
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c-late-run1', 1, ?,"
        " '2026-10-31T01:00:00+00:00', '{}')",
        (SUBJECT,),
    )
    conn.commit()
    try:
        picked = ST.latest_cycle(conn, SUBJECT)
    finally:
        conn.close()
    assert picked is not None
    assert picked["cycle_id"] == "c-late-run1"


def test_negative_control_catches_off_by_one_stage3_number(monkeypatch):
    assert CTL.run_control() == 0
    real = C.run_compare

    def bumped(*args, **kwargs):
        res = real(*args, **kwargs)
        for stages in res["stages"].values():
            for stage in stages[2:3]:
                if isinstance(stage.get("last"), int):
                    stage["last"] += 1
        return res

    monkeypatch.setattr(C, "run_compare", bumped)
    assert CTL.run_control() == 1
