"""Source-audit leak sweep and allowlist refusal (Ticket E2 plan, leak file)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from source_audit import compare as C
from source_audit import export as E
from source_audit import snapshot as S

ROOT = Path(__file__).resolve().parents[1]
USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "sentinel-subject-marker-9z"


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
            {
                "id": "2",
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": "2026-10-29T02:00:00Z",
                "action": "merged",
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
                "rows": 2,
                "oldest": "2026-10-29T01:00:00Z",
                "newest": "2026-10-29T02:00:00Z",
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


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT, type TEXT,"
        " time TEXT, source_id TEXT, data TEXT, tier TEXT, collected_at TEXT,"
        " collector_version TEXT)"
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-sentinel-row-marker-9z', ?, 'github',"
        " 'github.pr', '2026-10-29T01:00:00+00:00',"
        " 'sentinel-source-marker-9z',"
        ' \'{"repo": "sentinel-repo-marker-9z", "counts": {"opened": 1}}\','
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
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
        " 'm', 'h', 0, 1, 0, NULL,"
        ' \'{"period.earlier.prs": 0, "period.prior.prs": 1,'
        " \"period.last.prs\": 0, \"github.pr.count\": 1}', '[]', '[]', 0, 0)",
        (SUBJECT,),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT)"
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00',"
        " 'Pull requests rose from 0 in earlier to 9 in prior"
        " sentinel-statement-marker-9z.', '[]', 'code')",
        (SUBJECT,),
    )
    conn.commit()
    return conn


def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "source_audit", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_no_sentinel_reaches_output(tmp_path):
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snapshot()))
    db_path = tmp_path / "store.db"
    _db(db_path).close()
    export = tmp_path / "export.json"
    proc = _run_cli(
        [
            "compare",
            "--snapshot",
            str(snap_path),
            "--store",
            str(db_path),
            "--as-of",
            "2026-10-31T00:05:00+00:00",
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
            "--export",
            str(export),
        ],
        ROOT,
    )
    assert proc.returncode in (1, 3), proc.stderr[-2000:]
    blob = proc.stdout + proc.stderr
    if export.exists():
        blob += export.read_text()
    for marker in (
        "sentinel-subject-marker-9z",
        "sentinel-source-marker-9z",
        "sentinel-repo-marker-9z",
        "sentinel-statement-marker-9z",
        "sentinel-row-marker-9z",
    ):
        assert marker not in blob, marker
    proc = _run_cli(["negative-control"], ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "sentinel" not in (proc.stdout + proc.stderr).lower()


SLOT = "2026-10-31T00:30:00+00:00"
AS_OF = "2026-10-31T00:05:00+00:00"


def _db_t13(
    path, sentinel, stored, statement, refs_value=9, claim_text=None, refs=None
):
    """Build a Ticket 13 store carrying sentinels in every card-shaped field."""
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
    conn.execute(
        "INSERT INTO events VALUES ('e-cal', ?, 'github', 'github.calendar',"
        " '2026-10-29T02:00:00+00:00', 'cal-1', ?,"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT, json.dumps({"label": f"calendar {sentinel}", "counts": {}})),
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-screen', ?, 'github', 'github.screen',"
        " '2026-10-29T03:00:00+00:00', 'screen-1', ?,"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT, json.dumps({"label": f"screen {sentinel}", "counts": {}})),
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-bad', ?, 'github', 'github.pr',"
        " '2026-10-29T04:00:00+00:00', 'bad-1', ?,"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT, "{broken " + sentinel),
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-bad-time', ?, 'github', 'github.pr',"
        f" 'not-a-time {sentinel}', 'bad-2', '{{\"counts\": {{\"opened\": 1}}}}',"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-bad-collected', ?, 'github', 'github.pr',"
        " '2026-10-29T04:30:00+00:00', 'bad-3', '{\"counts\": {\"opened\": 1}}',"
        f" 'public', 'also-bad {sentinel}', 'v')",
        (SUBJECT,),
    )
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, model_id TEXT, prompt_hash TEXT, latency_ms INTEGER,"
        " raw_valid INTEGER, is_noop INTEGER, noop_reason TEXT, snapshot TEXT,"
        " passes TEXT, dropped_codes TEXT, kept_count INTEGER,"
        " dropped_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?,"
        " 'm', 'h', 0, 1, 0, NULL, ?, '[]', '[]', 0, 0)",
        (SUBJECT, AS_OF, stored),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, fact_id TEXT,"
        " subject_id TEXT, window_start TEXT, window_end TEXT, statement TEXT,"
        " evidence TEXT, tier TEXT, origin TEXT)"
    )
    conn.execute(
        "INSERT INTO facts VALUES ('c1', 1, 'f1', ?,"
        " '2026-10-28T00:00:00+00:00', '2026-10-31T00:00:00+00:00', ?,"
        " '[]', 'code', 'code')",
        (SUBJECT, statement),
    )
    conn.execute(
        "CREATE TABLE proposal_results (proposal_key TEXT, cycle_id TEXT,"
        " run INTEGER, profile_id TEXT, subject_id TEXT, slot TEXT, kind TEXT,"
        " briefing_json TEXT, fallback_json TEXT, snapshot TEXT, hour_start"
        " TEXT, hour_end TEXT, reason_codes TEXT, cycle_age_s REAL)"
    )
    briefing = json.dumps(
        {
            "sections": [
                {
                    "type": "overall_state",
                    "claims": [
                        {
                            "id": "c1",
                            "text": claim_text
                            if claim_text is not None
                            else f"claim {sentinel}",
                            "fact_ids": [],
                            "metric_refs": (
                                refs
                                if refs is not None
                                else [
                                    {
                                        "metric_id": "period.prior.prs",
                                        "value": refs_value,
                                    }
                                ]
                            ),
                        }
                    ],
                    "actions": [{"text": f"action {sentinel}"}],
                }
            ]
        }
    )
    conn.execute(
        "INSERT INTO proposal_results VALUES ('k1', 'c1', 1, ?, ?, ?,"
        " 'proposal', ?, NULL, ?, NULL, NULL, '[]', 1.0)",
        (f"p1 {sentinel}", SUBJECT, SLOT, briefing, stored),
    )
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT,"
        " card_id TEXT, detail TEXT, seconds REAL)"
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
    card = {
        "slot": SLOT,
        "since_line": f"since {sentinel}",
        "proposals": [
            {
                "letter": "A",
                "title": f"title {sentinel}",
                "profile": f"p1 {sentinel}",
            }
        ],
        "statements": [statement],
    }
    chart = {
        "pushes": {
            "label": f"chart {sentinel}",
            "earlier": 0,
            "prior": 0,
            "last": 0,
        }
    }
    for letter in ("A", "B"):
        conn.execute(
            "INSERT INTO slot_cards VALUES ('card-1', ?, ?, ?, ?, 'b', ?,"
            " 'c', 'proposal', NULL, NULL)",
            (letter, SLOT, SUBJECT, AS_OF, f"p1 {sentinel}"),
        )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-9', 'A', ?, 'other-subject', ?,"
        " 'b', 'p1', 'c', 'proposal', NULL, NULL)",
        (SLOT, AS_OF),
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES ('card-bad', 'A', ?, ?, ?, 'b', 'p1',"
        " 'c', 'proposal', NULL, NULL)",
        (f"never {sentinel}", SUBJECT, AS_OF),
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES ('card-1', ?, ?)",
        (json.dumps(card), json.dumps(chart)),
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', 'card-1', NULL, 1.5)",
        (SLOT,),
    )
    conn.commit()
    conn.close()


def test_t13_card_sentinels_never_reach_output(tmp_path):
    sentinel = "sentinel-t13-marker-9z"
    stored = (
        '{"period.earlier.prs": 0, "period.prior.prs": 9,'
        ' "period.last.prs": 0, "github.pr.count": 9}'
    )
    statement = "Pull requests rose from 0 in earlier to 9 in prior " + sentinel
    _db_t13(tmp_path / "s.db", sentinel, stored, statement)
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snapshot()))
    export_path = tmp_path / "export.json"
    for argv in (
        [
            "compare",
            "--snapshot",
            str(snap_path),
            "--store",
            str(tmp_path / "s.db"),
            "--as-of",
            AS_OF,
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
            "--export",
            str(export_path),
        ],
        [
            "recount",
            "--snapshot",
            str(snap_path),
            "--as-of",
            AS_OF,
            "--tz",
            "UTC",
            "--metric",
            "prs",
        ],
    ):
        proc = _run_cli(argv, ROOT)
        assert proc.returncode in (0, 1, 2, 3), proc.stderr[-2000:]
        assert sentinel not in proc.stdout, argv
        assert sentinel not in proc.stderr, argv
    assert export_path.exists()
    assert sentinel not in export_path.read_text()


def test_run_in_process_never_reaches_sentinel(tmp_path, monkeypatch, capsys):
    from source_audit import __main__ as M
    from source_audit import fetch as F

    sentinel = "sentinel-t13-marker-9z"
    stored = (
        '{"period.earlier.prs": 0, "period.prior.prs": 9,'
        ' "period.last.prs": 0, "github.pr.count": 9}'
    )
    statement = "Pull requests rose from 0 in earlier to 9 in prior " + sentinel
    _db_t13(tmp_path / "s.db", sentinel, stored, statement)

    def _fake_fetch(user, repo, out):
        snap = dict(_snapshot())
        snap["user"] = user
        snap["repo"] = repo
        Path(out).write_text(json.dumps(snap))
        return snap

    monkeypatch.setattr(F, "run_fetch", _fake_fetch)
    outdir = tmp_path / "out"
    code = M.main(
        [
            "run",
            "--user",
            USER,
            "--repo",
            REPO,
            "--out",
            str(outdir),
            "--store",
            str(tmp_path / "s.db"),
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
        ]
    )
    assert code in (0, 1), code
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    snapshot_text = (outdir / "snapshot.json").read_text()
    export_text = (outdir / "export.json").read_text()
    assert (outdir / "snapshot.json").exists()
    assert (outdir / "export.json").exists()
    assert sentinel not in blob
    assert sentinel not in snapshot_text
    assert sentinel not in export_text


def test_run_end_to_end_writes_files_exits_by_verdict(tmp_path, monkeypatch, capsys):
    import os
    import tempfile

    from source_audit import __main__ as M
    from source_audit import fetch as F

    stored = (
        '{"period.earlier.prs": 0, "period.prior.prs": 1,'
        ' "period.last.prs": 0, "github.pr.count": 1}'
    )
    statement = "Pull requests rose from 0 in earlier to 1 in prior."
    _db_t13(
        tmp_path / "s.db",
        "",
        stored,
        statement,
        claim_text=statement,
        refs=[
            {"metric_id": "period.earlier.prs", "value": 0},
            {"metric_id": "period.prior.prs", "value": 1},
        ],
    )

    def _fake_fetch(user, repo, out):
        snap = dict(_snapshot())
        snap["user"] = user
        snap["repo"] = repo
        Path(out).write_text(json.dumps(snap))
        return snap

    monkeypatch.setattr(F, "run_fetch", _fake_fetch)
    made = []
    real_mkdtemp = tempfile.mkdtemp

    def _spy(*args, **kwargs):
        folder = real_mkdtemp(*args, **kwargs)
        made.append(folder)
        return folder

    monkeypatch.setattr(tempfile, "mkdtemp", _spy)
    outdir = tmp_path / "out"
    code = M.main(
        [
            "run",
            "--user",
            USER,
            "--repo",
            REPO,
            "--out",
            str(outdir),
            "--scratch-copy-of",
            str(tmp_path / "s.db"),
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
            "--card",
            "latest",
        ]
    )
    assert code == 0, code
    captured = capsys.readouterr()
    assert "verdict=PASS" in captured.out
    assert (outdir / "snapshot.json").exists()
    assert (outdir / "export.json").exists()
    assert made, "expected a scratch copy"
    for folder in made:
        assert not os.path.exists(folder)


def test_allowlist_pass_refuses_space_and_unknown_shape(tmp_path):
    export = {"ok": True, "note": "has a space", "metric": "prs"}
    with pytest.raises(E.ExportRefused):
        E.write_export(tmp_path / "e.json", export)
    assert not (tmp_path / "e.json").exists()
    export = {"ok": True, "repo": "not a repo!!", "metric": "prs"}
    with pytest.raises(E.ExportRefused):
        E.write_export(tmp_path / "e.json", export)
    assert not (tmp_path / "e.json").exists()


def test_export_writer_refuses_unknown_keys(tmp_path):
    top = {"metric": "prs", "mystery_key": "X"}
    with pytest.raises(E.ExportRefused) as exc:
        E.write_export(tmp_path / "top.json", top)
    assert exc.value.code == "EXPORT_REFUSED"
    assert not (tmp_path / "top.json").exists()
    nested = {
        "metric": "prs",
        "stages": [
            {
                "metric": "prs",
                "stage": "1",
                "status": "match",
                "mystery_key": "X",
            }
        ],
    }
    with pytest.raises(E.ExportRefused) as exc:
        E.write_export(tmp_path / "nested.json", nested)
    assert exc.value.code == "EXPORT_REFUSED"
    assert not (tmp_path / "nested.json").exists()


def test_planted_bad_export_value_prints_only_refused(tmp_path, monkeypatch, capsys):
    from source_audit import __main__ as M

    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snapshot()))
    conn = _db(tmp_path / "store.db")
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
    res["export"]["stages"][0]["status"] = "a bad value"
    monkeypatch.setattr(C, "run_compare", lambda *a, **k: res)
    code = M.main(
        [
            "compare",
            "--snapshot",
            str(snap_path),
            "--store",
            str(tmp_path / "store.db"),
            "--as-of",
            "2026-10-31T00:05:00+00:00",
            "--metric",
            "prs",
            "--subject-id",
            SUBJECT,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == "EXPORT_REFUSED\n"
    assert captured.err == ""


def test_compare_never_prints_store_path(tmp_path, capsys):
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snapshot()))
    assert S.load_snapshot(snap_path)["user"] == USER
    conn = _db(tmp_path / "store.db")
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
    blob = " ".join(res["lines"]) + json.dumps(res["export"])
    assert "store.db" not in blob
    assert str(tmp_path) not in blob
