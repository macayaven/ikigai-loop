"""Source-audit scratch-copy safety (Ticket E2 plan, scratch file)."""

import sqlite3

import pytest

from source_audit import store as ST

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
SUBJECT = "synthetic-subject-1"
AS_OF = "2026-10-31T00:05:00+00:00"


def _snapshot():
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": [],
        "pulls": [],
        "activity": [],
        "coverage": {
            "events": {"rows": 0, "oldest": None, "newest": None, "stop": "last_page"},
            "pulls": {"rows": 0, "oldest": None, "newest": None, "stop": "last_page"},
            "activity": {
                "rows": 0,
                "oldest": None,
                "newest": None,
                "stop": "last_page",
            },
        },
    }


def _wal_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
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
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "INSERT INTO events VALUES ('e2', ?, 'github', 'github.pr',"
        " '2026-10-29T02:00:00+00:00', '2', '{\"counts\": {\"opened\": 1}}',"
        " 'public', '2026-10-29T05:00:00+00:00', 'v')",
        (SUBJECT,),
    )
    writer.commit()
    return conn, writer


def _main_bytes(path):
    """Read the main file bytes for the hash comparison."""
    with open(path, "rb") as handle:
        return handle.read()


def test_wal_rows_included_source_bytes_unchanged_folder_gone(tmp_path):
    db = tmp_path / "live.db"
    conn, writer = _wal_db(db)
    before = _main_bytes(db)
    scratch = ST.Scratch(str(db))
    folder = scratch.folder
    try:
        with scratch as copied:
            rows, unreadable = ST.github_rows(
                copied,
                SUBJECT,
                "2026-10-28T00:00:00+00:00",
                "2026-10-31T00:00:00+00:00",
            )
            assert {r["source_id"] for r in rows} == {"1", "2"}
            assert unreadable == []
        assert _main_bytes(db) == before
    finally:
        writer.close()
        conn.close()
    import os

    assert not os.path.exists(folder)


def test_scratch_folder_gone_after_exception(tmp_path):
    db = tmp_path / "live.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()
    scratch = ST.Scratch(str(db))
    folder = scratch.folder
    with pytest.raises(RuntimeError), scratch:
        raise RuntimeError("boom")
    import os

    assert not os.path.exists(folder)


def test_backup_failure_removes_folder(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()

    class _FailingSource:
        def backup(self, target):
            raise RuntimeError("backup boom")

        def close(self):
            pass

    monkeypatch.setattr(ST, "open_ro", lambda path: _FailingSource())
    scratch = ST.Scratch(str(db))
    folder = scratch.folder
    with pytest.raises(RuntimeError, match="backup boom"), scratch:
        pass
    import os

    assert not os.path.exists(folder)


def test_scratch_copy_is_read_only(tmp_path):
    db = tmp_path / "live.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.execute("INSERT INTO events VALUES ('e1')")
    conn.commit()
    conn.close()
    scratch = ST.Scratch(str(db))
    with scratch as copied:
        assert copied.execute("SELECT id FROM events").fetchall() == [("e1",)]
        with pytest.raises(sqlite3.OperationalError):
            copied.execute("INSERT INTO events VALUES ('e2')")


def test_unreadable_file_is_not_missing(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(ST.StoreError) as exc:
        ST.open_ro(str(junk))
    assert exc.value.code == "STORE_UNREADABLE"
    with pytest.raises(ST.StoreError) as exc:
        ST.Scratch(str(junk))
    assert exc.value.code == "STORE_UNREADABLE"


def test_missing_source_fails_closed_creates_nothing(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(ST.StoreError) as exc:
        ST.Scratch(str(missing))
    assert exc.value.code == "STORE_MISSING"
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ST.StoreError) as exc:
        ST.open_ro(str(missing))
    assert exc.value.code == "STORE_MISSING"
    assert list(tmp_path.iterdir()) == []
