"""Source-audit CLI exit codes (Ticket E2 plan, CLI file)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
AS_OF = "2026-10-31T00:05:00+00:00"


def _snapshot(prs_prior=1):
    events = [
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
    ]
    pulls = [{"number": 1, "created_at": "2026-10-29T01:00:00Z", "author": USER}]
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": events,
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


STATEMENT = "Pull requests rose from 0 in earlier to 1 in prior."
CARD_JSON = json.dumps(
    {
        "slot": "2026-10-31T00:30:00+00:00",
        "since_line": "First card, last 24h: nothing recorded.",
        "proposals": [
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "p",
                "title": "t",
                "start": "2026-10-31T01:00:00+00:00",
                "end": "2026-10-31T02:00:00+00:00",
            }
        ],
        "statements": [STATEMENT],
    }
)
BRIEFING_JSON = json.dumps(
    {
        "sections": [
            {
                "type": "overall_state",
                "claims": [
                    {
                        "id": "c-overall_state-1",
                        "text": STATEMENT,
                        "fact_ids": [],
                        "metric_refs": [
                            {"metric_id": "period.earlier.prs", "value": 0},
                            {"metric_id": "period.prior.prs", "value": 1},
                        ],
                    }
                ],
            },
            {"type": "since_last", "claims": []},
        ],
    }
)
CHART_JSON = json.dumps(
    {"pushes": {"label": "pushes + PRs", "earlier": 0, "prior": 1, "last": 0}}
)


def _db(path, stored):
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
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
        " '[]', 'code')",
        (SUBJECT, STATEMENT),
    )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, 'p1', ?,"
        " '2026-10-31T00:30:00+00:00', 'proposal', ?, NULL, ?, NULL, NULL,"
        " '[]', 1.0)",
        (SUBJECT, BRIEFING_JSON, stored),
    )
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT,"
        " card_id TEXT, detail TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, letter TEXT, slot TEXT,"
        " subject_id TEXT, as_of TEXT, bucket TEXT, profile_id TEXT,"
        " commitment_id TEXT, kind TEXT, policy_pick TEXT, policy_alternative"
        " TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES ('2026-10-31T00:30:00+00:00', 'send',"
        " 'delivered', 'card-1', NULL)"
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-1', 'A',"
        " '2026-10-31T00:30:00+00:00', ?, '2026-10-31T00:05:00+00:00', 'b',"
        " 'p1', 'c', 'proposal', NULL, NULL)",
        (SUBJECT,),
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES ('card-1', ?, ?)",
        (CARD_JSON, CHART_JSON),
    )
    conn.commit()
    conn.close()


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "source_audit", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _case(tmp_path, stored):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    db = tmp_path / "s.db"
    _db(db, stored)
    return [
        "compare",
        "--snapshot",
        str(snap),
        "--store",
        str(db),
        "--metric",
        "prs",
        "--subject-id",
        SUBJECT,
        "--card",
        "latest",
    ]


def test_pass_maps_to_zero(tmp_path):
    stored = (
        '{"period.earlier.prs": 0, "period.prior.prs": 1,'
        ' "period.last.prs": 0, "github.pr.count": 1}'
    )
    proc = _run(_case(tmp_path, stored))
    assert proc.returncode == 0, proc.stderr[-2000:] + proc.stdout[-2000:]


def test_fail_maps_to_one(tmp_path):
    stored = (
        '{"period.earlier.prs": 0, "period.prior.prs": 5,'
        ' "period.last.prs": 0, "github.pr.count": 5}'
    )
    proc = _run(_case(tmp_path, stored))
    assert proc.returncode == 1, proc.stderr[-2000:]
    assert "mismatch" in proc.stdout


def test_incomplete_maps_to_three(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    db = tmp_path / "s.db"
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
    conn.close()
    proc = _run(
        [
            "compare",
            "--snapshot",
            str(snap),
            "--store",
            str(db),
            "--as-of",
            AS_OF,
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
        ]
    )
    assert proc.returncode == 3, proc.stderr[-2000:]
    assert "unavailable" in proc.stdout


def test_recount_same_counts_different_zones(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    first = _run(
        [
            "recount",
            "--snapshot",
            str(snap),
            "--as-of",
            AS_OF,
            "--tz",
            "Europe/Madrid",
            "--metric",
            "prs",
        ]
    )
    second = _run(
        [
            "recount",
            "--snapshot",
            str(snap),
            "--as-of",
            AS_OF,
            "--tz",
            "Australia/Sydney",
            "--metric",
            "prs",
        ]
    )
    assert first.returncode == 0, first.stderr[-2000:]
    assert second.returncode == 0, second.stderr[-2000:]
    counts = lambda out: sorted(l for l in out.splitlines() if l.startswith("metric="))
    assert counts(first.stdout) == counts(second.stdout)
    local = lambda out: sorted(l for l in out.splitlines() if "window_start_local" in l)
    assert local(first.stdout) != local(second.stdout)
    assert "window_start=" in first.stdout
    assert "pr=synthetic-owner/synthetic-repo#1@" in first.stdout
    assert "period=prior" in first.stdout


def test_unknown_zone_is_bad_tz(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    proc = _run(
        [
            "recount",
            "--snapshot",
            str(snap),
            "--as-of",
            AS_OF,
            "--tz",
            "No/Such_Zone",
            "--metric",
            "prs",
        ]
    )
    assert proc.returncode == 2
    assert proc.stdout.strip() == "USAGE_BAD_TZ"
    proc = _run(
        [
            "compare",
            "--snapshot",
            str(snap),
            "--store",
            str(tmp_path / "s.db"),
            "--tz",
            "No/Such_Zone",
        ]
    )
    assert proc.returncode == 2
    assert proc.stdout.strip() == "USAGE_BAD_TZ"


def test_settle_sentence_only_when_unsettled(tmp_path):
    snap = tmp_path / "snap.json"
    base = _snapshot()
    base["fetched_at"] = "2026-10-31T01:00:00Z"
    snap.write_text(json.dumps(base))
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, type TEXT,"
        " time TEXT, source_id TEXT, data TEXT, tier TEXT, collected_at TEXT,"
        " collector_version TEXT)"
    )
    conn.commit()
    conn.close()
    args = [
        "compare",
        "--snapshot",
        str(snap),
        "--store",
        str(db),
        "--as-of",
        AS_OF,
        "--metric",
        "prs",
        "--subject-id",
        SUBJECT,
    ]
    early = _run(args)
    assert early.returncode == 3, early.stderr[-2000:]
    assert "under 6 hours" in early.stdout
    base["fetched_at"] = "2026-10-31T07:00:00Z"
    snap.write_text(json.dumps(base))
    late = _run(args)
    assert late.returncode == 3, late.stderr[-2000:]
    assert "under 6 hours" not in late.stdout


def test_flag_conflict_before_store_open(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    proc = _run(
        [
            "compare",
            "--snapshot",
            str(snap),
            "--scratch-copy-of",
            str(tmp_path / "missing.db"),
            "--as-of",
            AS_OF,
            "--card",
            "latest",
        ]
    )
    assert proc.returncode == 2
    assert proc.stdout.strip() == "USAGE_AS_OF_WITH_CARD"


def test_run_flag_conflict_makes_no_http_call(tmp_path, monkeypatch):
    from source_audit import __main__ as M
    from source_audit import fetch as F

    calls = []
    monkeypatch.setattr(
        F, "run_fetch", lambda *args, **kwargs: calls.append(args) or {}
    )
    code = M.main(
        [
            "run",
            "--user",
            USER,
            "--repo",
            REPO,
            "--out",
            str(tmp_path / "out"),
            "--store",
            str(tmp_path / "s.db"),
            "--as-of",
            AS_OF,
            "--card",
            "latest",
        ]
    )
    assert code == 2
    assert calls == []


def test_usage_error_maps_to_two(tmp_path):
    proc = _run(
        [
            "compare",
            "--snapshot",
            str(tmp_path / "missing.json"),
            "--store",
            str(tmp_path / "s.db"),
        ]
    )
    assert proc.returncode == 2


def test_ambiguous_subjects_exit_two_without_ids(tmp_path):
    subjects = ("synthetic-subject-aaa", "synthetic-subject-bbb")
    for name, subject in zip(("two.db", "zero.db"), subjects):
        db = tmp_path / name
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT,"
            " type TEXT, time TEXT, source_id TEXT, data TEXT, tier TEXT,"
            " collected_at TEXT, collector_version TEXT)"
        )
        if name == "two.db":
            for subject in subjects:
                conn.execute(
                    "INSERT INTO events VALUES ('e1', ?, 'github',"
                    " 'github.pr', '2026-10-29T01:00:00+00:00', '1',"
                    " '{\"counts\": {\"opened\": 1}}', 'public',"
                    " '2026-10-29T05:00:00+00:00', 'v')",
                    (subject,),
                )
        conn.commit()
        conn.close()
    for name in ("two.db", "zero.db"):
        snap = tmp_path / f"{name}.json"
        snap.write_text(json.dumps(_snapshot()))
        proc = _run(
            [
                "compare",
                "--snapshot",
                str(snap),
                "--store",
                str(tmp_path / name),
                "--as-of",
                AS_OF,
                "--metric",
                "prs",
            ]
        )
        assert proc.returncode == 2, (name, proc.stderr[-2000:])
        assert proc.stdout.strip() == "USAGE_SUBJECT_AMBIGUOUS", (
            name,
            proc.stdout[-500:],
        )
        for subject in subjects:
            assert subject not in proc.stdout, (name, subject)
            assert subject not in proc.stderr, (name, subject)


def test_unexpected_exception_prints_class_only(capsys, tmp_path, monkeypatch):
    from source_audit import __main__ as M
    from source_audit import compare as C

    sentinel = "sentinel-failure-tekst-9z"
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()))
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()

    def boom(*args, **kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(C, "run_compare", boom)
    code = M.main(
        [
            "compare",
            "--snapshot",
            str(snap),
            "--store",
            str(db),
            "--as-of",
            AS_OF,
            "--subject-id",
            SUBJECT,
        ]
    )
    assert code == 2
    out, err = capsys.readouterr()
    assert out.strip() == "ERROR_RuntimeError"
    assert sentinel not in out
    assert sentinel not in err


def test_malformed_snapshot_maps_to_two(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text('{"user": "x"}')
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()
    proc = _run(
        [
            "compare",
            "--snapshot",
            str(snap),
            "--store",
            str(db),
            "--subject-id",
            SUBJECT,
        ]
    )
    assert proc.returncode == 2
    assert "SNAPSHOT_INVALID" in proc.stdout + proc.stderr
