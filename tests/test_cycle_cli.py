"""Ticket 9: ``python -m framework.cycle facts`` prints one counts-only line."""

import re
from pathlib import Path
from typing import Any

import pytest

from evals.glimmer_cases import SUBJECT_ID, RecordingLLM, base_case
from framework.cycle import __main__ as cycle_main
from framework.store import EventStore
from framework.store.fact_store import FactStore

AS_OF_ISO = "2026-10-31T13:00:00+01:00"

LINE_RE = re.compile(
    r"^cycle=\S+ run=1 kept=3 dropped=0 noop=- "
    r"personal=2:-:0\.0s:stop feed=1:-:0\.0s:stop codes=-$"
)


def _seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "cli.db"
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(base_case().events)) == len(base_case().events)
    finally:
        store.close()
    return db


def _stub_llm() -> RecordingLLM:
    case = base_case()
    return RecordingLLM(personal=case.personal_texts, feed=case.feed_texts)


def test_facts_line_exact_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    code = cycle_main.main(
        ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert LINE_RE.match(out.strip()), out
    assert out.strip().count("\n") == 0


def test_stdout_carries_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    cycle_main.main(
        ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
    )
    out = capsys.readouterr().out
    for forbidden in (
        "Programming screen hours fell",
        "Push activity continued",
        "model compression methods",
        "Synthetic transformer pruning",
        "synthetic/repo",
        "mock-model",
        "registry/",
    ):
        assert forbidden not in out, forbidden


def test_subject_id_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(["facts", "--as-of", AS_OF_ISO, "--db", str(db)])
    assert code == 0
    assert LINE_RE.match(capsys.readouterr().out.strip())


def test_missing_subject_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    code = cycle_main.main(["facts", "--as-of", AS_OF_ISO, "--db", str(db)])
    assert code == 2
    assert "IKIGAI_SUBJECT_ID" in capsys.readouterr().err


def test_naive_as_of_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    code = cycle_main.main(
        [
            "facts",
            "--as-of",
            "2026-10-31T13:00:00",
            "--subject-id",
            SUBJECT_ID,
            "--db",
            str(db),
        ]
    )
    assert code == 2
    assert capsys.readouterr().out == ""


def test_missing_llm_env_names_variable_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        cycle_main.main(
            ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
        )
    assert "LOCAL_LLM_BASE_URL" in str(excinfo.value)
    assert capsys.readouterr().out == ""


def test_second_run_replays_same_run_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    args = ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
    assert cycle_main.main(args) == 0
    first = capsys.readouterr().out
    assert cycle_main.main(args) == 0
    assert capsys.readouterr().out == first
    store = FactStore(db_path=db)
    try:
        assert len(store.fetch_facts(_cycle_id(first), 1)) == 3
    finally:
        store.close()


def _cycle_id(line: str) -> str:
    return line.split()[0].removeprefix("cycle=").strip()


def _assert_single_error_line(captured: object, name: str) -> None:
    err = captured.err  # type: ignore[attr-defined]
    assert err == f"error: {name}\n", err
    assert "Traceback" not in err
    assert captured.out == ""  # type: ignore[attr-defined]


def test_db_directory_exits_1_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    code = cycle_main.main(
        [
            "facts",
            "--as-of",
            AS_OF_ISO,
            "--subject-id",
            SUBJECT_ID,
            "--db",
            str(tmp_path),
        ]
    )
    assert code == 1
    _assert_single_error_line(capsys.readouterr(), "OperationalError")


def test_db_non_sqlite_file_exits_1_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.db"
    bad.write_text("this is not sqlite")
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    code = cycle_main.main(
        ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(bad)]
    )
    assert code == 1
    _assert_single_error_line(capsys.readouterr(), "DatabaseError")


def test_overflow_as_of_exits_1_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    code = cycle_main.main(
        [
            "facts",
            "--as-of",
            "0001-01-01T00:00:00+00:00",
            "--subject-id",
            SUBJECT_ID,
            "--db",
            str(tmp_path / "cli.db"),
        ]
    )
    assert code == 1
    _assert_single_error_line(capsys.readouterr(), "OverflowError")


def test_stub_bug_exits_1_without_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)

    class _Buggy:
        def complete(self, prompt: str) -> object:
            raise RuntimeError("SENTINEL marker must stay hidden")

    monkeypatch.setattr(cycle_main, "_build_llm", lambda: _Buggy())
    code = cycle_main.main(
        ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err == "error: RuntimeError\n", captured.err
    assert "SENTINEL" not in captured.err
    assert captured.out == ""


def test_statement_text_in_neither_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _seeded_db(tmp_path)
    monkeypatch.setattr(cycle_main, "_build_llm", _stub_llm)
    code = cycle_main.main(
        ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
    )
    assert code == 0
    captured = capsys.readouterr()
    for forbidden in (
        "Programming screen hours fell",
        "Push activity continued",
        "model compression methods",
    ):
        assert forbidden not in captured.out, forbidden
        assert forbidden not in captured.err, forbidden


def test_run_cycle_asks_for_absolute_72h_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from evals.glimmer_cases import RecordingLLM
    from framework.cycle import run_cycle

    seen: dict[str, object] = {}

    class _SpyStore:
        def events_between(
            self,
            subject_id: str,
            start: object,
            end: object,
            types: object = None,
        ) -> list:
            seen["subject_id"] = subject_id
            seen["start"] = start
            seen["end"] = end
            seen["types"] = types
            return []

    as_of = datetime(2026, 10, 26, 12, tzinfo=ZoneInfo("Europe/Madrid"))
    store = FactStore(db_path=tmp_path / "spy.db")
    spy: Any = _SpyStore()
    try:
        result, _ = run_cycle(as_of, SUBJECT_ID, spy, store, RecordingLLM())
    finally:
        store.close()
    from framework.glimmer.facts import ALLOWED_TYPES

    assert result.is_noop is True
    assert seen["subject_id"] == SUBJECT_ID
    assert seen["types"] == ALLOWED_TYPES
    from datetime import UTC

    start = seen["start"]
    end = seen["end"]
    span = end.astimezone(UTC) - start.astimezone(UTC)  # type: ignore[attr-defined, operator]
    assert span == timedelta(hours=72)


def test_missing_llm_env_creates_no_database_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL", "LOCAL_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    db = tmp_path / "never.db"
    with pytest.raises(SystemExit):
        cycle_main.main(
            ["facts", "--as-of", AS_OF_ISO, "--subject-id", SUBJECT_ID, "--db", str(db)]
        )
    assert not db.exists()
