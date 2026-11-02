"""Ticket 13 slice 3: real child processes (made-up data, no port, no network).

Each test sets its own timeout with ``signal.alarm``, so a hang fails
instead of blocking. A lock is never paired with a constant clock and a
retry loop here: every wait is bounded by a real deadline.
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from framework.cycle.orchestrator import production_facts_runner
from framework.cycle.slot_ledger import SlotLedger

MADRID = ZoneInfo("Europe/Madrid")
REPO = Path(__file__).resolve().parents[1]
SUBJECT = "subject-a"

_DRIVER = '''\
"""Driver: run one slot with fakes, but in a real OS process."""

import fcntl
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.environ["IKIGAI_REPO"])

from framework.cycle.orchestrator import (
    FactsChildResult,
    Seams,
    production_facts_runner,
    run_slot,
)
from framework.proposal.core import MetaUnavailableError

MADRID = ZoneInfo("Europe/Madrid")


class Down:
    transport = "muse"
    transport_version = "fake version 1.0"
    harness_rules_file = None

    def complete(self, request):
        raise MetaUnavailableError("synthetic down", latency_ms=5)


class FileClient:
    def __init__(self, path):
        self.path = path

    def send_photo(self, chat_id, photo, caption, markup, timeout_s=60.0):
        with open(self.path, "ab") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(b"sendPhoto\\n")
            fcntl.flock(handle, fcntl.LOCK_UN)
        return {"message_id": 1}


def main() -> int:
    db = Path(os.environ["IKIGAI_DB"])
    slot = datetime.fromisoformat(os.environ["IKIGAI_SLOT"])
    facts_argv = os.environ.get("IKIGAI_FACTS_ARGV")
    if facts_argv:
        argv = json.loads(facts_argv)

        def _facts(**kwargs):
            return production_facts_runner(
                as_of=kwargs["as_of"],
                subject_id=kwargs["subject_id"],
                db_path=kwargs["db_path"],
                deadline=kwargs["deadline"],
                clock=lambda: slot - timedelta(minutes=25),
                argv=argv,
            )

    else:

        def _facts(**kwargs):
            return FactsChildResult("SKIPPED", None, None)

    seams = Seams(
        facts=_facts,
        wonder=lambda terms, deadline: Down(),
        telegram=FileClient(os.environ["IKIGAI_COUNT"]),
        clock=lambda: slot - timedelta(minutes=25),
        sleep=lambda seconds: None,
        home=Path(os.environ["IKIGAI_HOME"]),
        ledger_sleep=lambda seconds: None,
    )
    return run_slot(
        slot=slot,
        subject_id="subject-a",
        db_path=db,
        no_wait=True,
        force_slot=True,
        skip_local_model=not facts_argv,
        seams=seams,
    )


if __name__ == "__main__":
    sys.exit(main())
'''

_HOLDER = (
    "import sqlite3, sys, time\n"
    "db = sys.argv[1]\n"
    "ready = sys.argv[2]\n"
    "hold_s = float(sys.argv[3])\n"
    "conn = sqlite3.connect(db)\n"
    "conn.isolation_level = None\n"
    "conn.execute('BEGIN EXCLUSIVE')\n"
    "open(ready, 'w').write('held')\n"
    "time.sleep(hold_s)\n"
)


def _write_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    terms = tmp_path / "terms"
    terms.mkdir(exist_ok=True)
    (terms / "deny-terms.txt").write_text("zzforbiddenzz\n")
    commitments = tmp_path / "commitments.json"
    commitments.write_text(
        json.dumps(
            [
                {
                    "id": "b-1",
                    "profile_id": "builder",
                    "title": "Morning pages draft",
                    "kind": "build",
                    "dimension": "love",
                    "evidence": "github_push",
                },
                {
                    "id": "d-1",
                    "profile_id": "disconnect",
                    "title": "Short walk outside",
                    "kind": "rest",
                    "dimension": "love",
                    "evidence": "github_push",
                },
            ]
        )
    )
    return commitments


def _pinned_slot() -> datetime:
    return datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)


def test_hanging_facts_child_killed_by_group_at_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hanging facts child dies with its process group at the deadline."""
    signal.alarm(120)
    try:
        script = tmp_path / "hang.py"
        pid_file = tmp_path / "grandchild.pid"
        script.write_text(
            "import subprocess, time\n"
            f"child = subprocess.Popen(['sleep', '60'])\n"
            f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        deadline = datetime.now(MADRID) + timedelta(seconds=2)
        started = time.monotonic()
        result = production_facts_runner(
            as_of=datetime.now(MADRID),
            subject_id=SUBJECT,
            db_path=str(tmp_path / "cycle.db"),
            deadline=deadline,
            argv=[sys.executable, str(script)],
        )
        elapsed = time.monotonic() - started
        assert result.outcome == "FACTS_DEADLINE"
        assert result.cycle_id is None
        assert elapsed < 60
        grandchild = int(pid_file.read_text())
        for _ in range(100):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("process group survived the deadline kill")
    finally:
        signal.alarm(0)


def test_two_real_processes_race_one_slot_exactly_one_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two real processes race one slot; exactly one sendPhoto happens."""
    signal.alarm(180)
    try:
        commitments = _write_env(tmp_path, monkeypatch)
        db = tmp_path / "cycle.db"
        count = tmp_path / "sends.count"
        home = tmp_path / "home"
        home.mkdir()
        driver = tmp_path / "driver.py"
        driver.write_text(_DRIVER)
        slot = _pinned_slot()
        env = dict(os.environ)
        env["IKIGAI_REPO"] = str(REPO)
        env["IKIGAI_DB"] = str(db)
        env["IKIGAI_SLOT"] = slot.isoformat()
        env["IKIGAI_COUNT"] = str(count)
        env["IKIGAI_HOME"] = str(home)
        env["IKIGAI_COMMITMENTS_FILE"] = str(commitments)
        env["HIDDEN_CRITERIA_DIR"] = str(tmp_path / "terms")
        env["TELEGRAM_CHAT_ID"] = "424242"
        env.pop("META_API_KEY", None)
        env.pop("IKIGAI_KILL_FILE", None)
        env.pop("IKIGAI_FACTS_ARGV", None)
        first = subprocess.Popen([sys.executable, str(driver)], env=env)
        second = subprocess.Popen([sys.executable, str(driver)], env=env)
        try:
            first.wait(timeout=150)
        finally:
            pass
        second.wait(timeout=150)
        assert count.exists()
        assert count.read_bytes() == b"sendPhoto\n"
        assert first.returncode in (0, 3)
        assert second.returncode in (0, 3)
    finally:
        signal.alarm(0)


def test_real_facts_child_failure_sends_code_facts_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real facts child that exits nonzero gives MODEL_DOWN and a card."""
    signal.alarm(180)
    try:
        commitments = _write_env(tmp_path, monkeypatch)
        db = tmp_path / "cycle.db"
        count = tmp_path / "sends.count"
        home = tmp_path / "home"
        home.mkdir()
        driver = tmp_path / "driver.py"
        driver.write_text(_DRIVER)
        slot = _pinned_slot()
        env = dict(os.environ)
        env["IKIGAI_REPO"] = str(REPO)
        env["IKIGAI_DB"] = str(db)
        env["IKIGAI_SLOT"] = slot.isoformat()
        env["IKIGAI_COUNT"] = str(count)
        env["IKIGAI_HOME"] = str(home)
        env["IKIGAI_COMMITMENTS_FILE"] = str(commitments)
        env["HIDDEN_CRITERIA_DIR"] = str(tmp_path / "terms")
        env["TELEGRAM_CHAT_ID"] = "424242"
        env.pop("META_API_KEY", None)
        env.pop("IKIGAI_KILL_FILE", None)
        env["IKIGAI_FACTS_ARGV"] = json.dumps(
            [sys.executable, "-c", "import sys; sys.exit(3)"]
        )
        proc = subprocess.run(
            [sys.executable, str(driver)], env=env, timeout=150, check=False
        )
        assert proc.returncode == 0
        assert count.read_bytes() == b"sendPhoto\n"
        rows = SlotLedger(db).rows_for_slot(slot)
        assert "MODEL_DOWN" in [
            row.outcome for row in rows if row.step == "facts_model"
        ]
        assert "delivered" in [row.outcome for row in rows if row.step == "send"]
    finally:
        signal.alarm(0)


def test_delivered_row_lands_after_lock_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock held past 30 s and released before the stale limit still lands."""
    signal.alarm(300)
    try:
        from framework.cycle.orchestrator import FactsChildResult as _Result
        from framework.cycle.orchestrator import Seams as _Seams
        from framework.cycle.orchestrator import run_slot as _run_slot
        from framework.proposal.core import MetaUnavailableError as _Down

        commitments = _write_env(tmp_path, monkeypatch)
        monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(commitments))
        monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(tmp_path / "terms"))
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
        monkeypatch.delenv("META_API_KEY", raising=False)
        monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
        db = tmp_path / "cycle.db"
        slot = _pinned_slot()
        ready = tmp_path / "holder.ready"
        started: list[subprocess.Popen[bytes]] = []

        class _DownClient:
            transport = "muse"
            transport_version = "fake version 1.0"
            harness_rules_file = None

            def complete(self, request):
                raise _Down("synthetic down", latency_ms=5)

        class _TriggerClient:
            def __init__(self) -> None:
                self.calls = 0

            def send_photo(self, chat_id, photo, caption, markup, timeout_s=60.0):
                self.calls += 1
                if not started:
                    started.append(
                        subprocess.Popen(
                            [
                                sys.executable,
                                "-c",
                                _HOLDER,
                                str(db),
                                str(ready),
                                "31",
                            ]
                        )
                    )
                    for _ in range(200):
                        if ready.exists():
                            break
                        time.sleep(0.05)
                    assert ready.exists()
                return {"message_id": 9}

        telegram = _TriggerClient()
        seams = _Seams(
            facts=lambda **kwargs: _Result("SKIPPED", None, None),
            wonder=lambda terms, deadline: _DownClient(),
            telegram=telegram,
            clock=lambda: slot,
            sleep=lambda seconds: None,
            home=tmp_path / "home",
            ledger_sleep=lambda seconds: None,
        )
        began = time.monotonic()
        code = _run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=db,
            no_wait=True,
            force_slot=True,
            skip_local_model=True,
            seams=seams,
        )
        elapsed = time.monotonic() - began
        assert started != []
        started[0].wait(timeout=60)
        assert code == 0
        assert telegram.calls == 1
        assert elapsed >= 29
        rows = SlotLedger(db).rows_for_slot(slot)
        assert "delivered" in [row.outcome for row in rows if row.step == "send"]
    finally:
        signal.alarm(0)
