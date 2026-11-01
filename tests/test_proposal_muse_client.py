"""Ticket 11: MuseExecClient over a fake runner, never the real binary."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals.proposal_cases import (
    AS_OF,
    BASE_ELIGIBLE,
    BASE_FACTS,
    BASE_SNAPSHOT,
    CYCLE_ID,
    GOOD_DRAFT,
    LIMITS,
    MODELS,
    PROFILE_ID,
    STALE_AFTER_S,
    SUBJECT_ID,
    Case,
    ScriptedWonderClient,
    build_context,
)
from framework.cycle import __main__ as propose_main
from framework.glimmer.facts import FactResult, PassResult
from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    WonderRequest,
    propose,
)
from framework.proposal.hour import pick_hour
from framework.proposal.muse_client import (
    _VERSION_CACHE,
    MAX_MODEL_STEPS,
    MuseExecClient,
    RunResult,
    resolve_muse_bin,
    rules_file_path,
)
from framework.store import EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT_ID_CLI = "subject-1"
AS_OF_ISO = "2026-10-31T14:00:00+01:00"
SLOT_ISO = "2026-10-31T15:07:00+01:00"

ONE_ROW = [
    {
        "model": "muse-wonder-1.0",
        "input_tokens": 25100,
        "cached_tokens": 0,
        "output_tokens": 49,
        "reasoning_tokens": 34,
        "calls": 1,
    }
]
TWO_ROWS = [
    {
        "model": "muse-wonder-1.0",
        "input_tokens": 100,
        "cached_tokens": 5,
        "output_tokens": 10,
        "reasoning_tokens": 3,
    },
    {
        "model": "muse-wonder-1.0",
        "input_tokens": 200,
        "cached_tokens": 7,
        "output_tokens": 20,
        "reasoning_tokens": 9,
    },
]
SUCCESS_TEXT = '{"word": "blue"}'


@pytest.fixture(autouse=True)
def _clean_version_cache():
    _VERSION_CACHE.clear()
    yield
    _VERSION_CACHE.clear()


class FakeRunner:
    """Scripted outcomes; observes the temp files while it 'runs'."""

    def __init__(
        self,
        script: list[Any] | None = None,
        *,
        version_stdout: bytes = b"muse 1.2.3\n",
        version_script: list[Any] | None = None,
    ) -> None:
        self._script = list(script or [])
        self._version_stdout = version_stdout
        self._version_script = list(version_script or [])
        self.calls: list[dict[str, Any]] = []
        self.version_calls = 0

    def __call__(
        self,
        argv: Any,
        *,
        env: Any,
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        record: dict[str, Any] = {
            "argv": [str(item) for item in argv],
            "env": dict(env),
            "timeout_s": timeout_s,
            "cwd": cwd,
        }
        self.calls.append(record)
        if len(record["argv"]) > 1 and record["argv"][1] == "--version":
            self.version_calls += 1
            if self._version_script:
                outcome = self._version_script.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
            return RunResult(0, self._version_stdout, False)
        args = record["argv"]
        workspace = args[args.index("--workspace") + 1]
        prompt_path = args[args.index("--prompt-file") + 1]
        schema_path = args[args.index("--output-schema") + 1]
        record["workspace"] = workspace
        record["root"] = os.path.dirname(workspace)
        record["prompt_file"] = prompt_path
        record["schema_file"] = schema_path
        record["prompt_bytes"] = Path(prompt_path).read_bytes()
        record["schema_bytes"] = Path(schema_path).read_bytes()
        record["prompt_mode"] = stat.S_IMODE(os.stat(prompt_path).st_mode)
        record["schema_mode"] = stat.S_IMODE(os.stat(schema_path).st_mode)
        record["workspace_entries"] = sorted(os.listdir(workspace))
        record["workspace_isdir"] = os.path.isdir(workspace)
        if not self._script:
            raise AssertionError("runner called more times than scripted")
        outcome = self._script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _line(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "stream": {"kind": "session", "id": "s"},
            "record_type": "event",
            "payload": payload,
        }
    )


def _usage_payload(models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "run_usage",
        "models": models,
        "calls": 1,
        "completed_calls": 1,
        "failed_calls": 0,
        "allowance": {"window": {"used_percent": 11}},
    }


def _terminal_payload(text: Any, terminal: str = "completed") -> dict[str, Any]:
    return {
        "kind": "run_terminal",
        "terminal": terminal,
        "text": text,
        "reason": None,
    }


def _stdout(*payloads: dict[str, Any], prefix: tuple[str, ...] = ()) -> bytes:
    lines = list(prefix) + [_line(payload) for payload in payloads]
    return ("\n".join(lines) + "\n").encode()


def _ok_result(text: str, models: list[dict[str, Any]] | None = None) -> RunResult:
    return RunResult(
        0, _stdout(_usage_payload(models or ONE_ROW), _terminal_payload(text)), False
    )


def _request(
    prompt: str = "clean prompt text",
    model: str = "muse-wonder-1.0",
    effort: str = "high",
    schema: dict[str, Any] | None = None,
) -> WonderRequest:
    return WonderRequest(
        prompt=prompt,
        model=model,
        effort=effort,
        response_schema=schema if schema is not None else {"type": "object"},
    )


def _exec_client(fake: FakeRunner, **kwargs: Any) -> MuseExecClient:
    kwargs.setdefault("private_terms_available", True)
    kwargs.setdefault("muse_bin", "/fake/muse")
    return MuseExecClient(runner=fake, **kwargs)


def _roots(fake: FakeRunner) -> list[str]:
    return [call["root"] for call in fake.calls if "root" in call]


def _exec_calls(fake: FakeRunner) -> list[dict[str, Any]]:
    """Model-run calls only; the `--version` probe never runs a prompt."""
    return [
        call
        for call in fake.calls
        if len(call["argv"]) > 1 and call["argv"][1] != "--version"
    ]


def test_resolve_muse_bin_default_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUSE_BIN", raising=False)
    assert resolve_muse_bin() == os.path.expanduser("~/.local/bin/muse")
    assert resolve_muse_bin({}) == os.path.expanduser("~/.local/bin/muse")
    assert resolve_muse_bin({"MUSE_BIN": "/opt/bin/muse"}) == "/opt/bin/muse"
    monkeypatch.setenv("MUSE_BIN", "~/bin/muse")
    assert resolve_muse_bin() == os.path.expanduser("~/bin/muse")


def test_rules_file_path_xdg_and_home() -> None:
    assert (
        rules_file_path({"XDG_CONFIG_HOME": "/tmp/xdg-9f2c"})
        == "/tmp/xdg-9f2c/muse/AGENTS.md"
    )
    assert rules_file_path({"XDG_CONFIG_HOME": ""}) == os.path.expanduser(
        "~/.config/muse/AGENTS.md"
    )


def test_harness_rules_file_absent_then_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    client = _exec_client(FakeRunner([]))
    assert client.harness_rules_file is False
    rules_dir = tmp_path / "muse"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    assert client.harness_rules_file is True


def test_harness_rules_file_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    client = _exec_client(FakeRunner([]))
    assert client.harness_rules_file is False
    rules_dir = tmp_path / ".config" / "muse"
    rules_dir.mkdir(parents=True)
    (rules_dir / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    assert client.harness_rules_file is True


def test_harness_rules_file_never_reads_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rules_dir = tmp_path / "muse"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text("secret contents\n", encoding="utf-8")
    client = _exec_client(FakeRunner([]))

    def _boom_open(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("rules file contents must never be read")

    def _boom_os_open(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("rules file contents must never be read")

    monkeypatch.setattr(builtins, "open", _boom_open)
    monkeypatch.setattr(os, "open", _boom_os_open)
    assert client.harness_rules_file is True


def test_full_model_reaches_argv_unchanged() -> None:
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    _exec_client(fake).complete(_request(model="muse-wonder-full-1.0"))
    record = _exec_calls(fake)[0]
    assert record["argv"][record["argv"].index("--model") + 1] == (
        "muse-wonder-full-1.0"
    )


def test_full_contributor_model_refused_without_runner_calls() -> None:
    fake = FakeRunner([])
    with pytest.raises(ContributorModelRefused):
        _exec_client(fake).complete(_request(model="muse-wonder-full-1.0-contributor"))
    assert fake.calls == []


@pytest.mark.parametrize("flag", ["--model", "--retry-model"])
def test_cli_full_contributor_model_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env_no_key(monkeypatch, tmp_path, db) + [
        flag,
        "muse-wonder-full-1.0-contributor",
    ]
    monkeypatch.setattr(propose_main, "MuseExecClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert "contributor" in captured.err
    assert captured.out == ""


def test_exact_argv_snapshot() -> None:
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    client = _exec_client(fake, muse_bin="/fake/muse")
    schema = {"type": "object", "properties": {"word": {"type": "string"}}}
    client.complete(_request(prompt="P", schema=schema))
    record = fake.calls[0]
    assert len(fake.calls) == 1
    workspace = record["workspace"]
    mapping = {
        "/fake/muse": "<bin>",
        workspace: "<workspace>",
        record["schema_file"]: "<schema>",
        record["prompt_file"]: "<prompt>",
    }
    snapshot = [mapping.get(item, item) for item in record["argv"]]
    assert snapshot == [
        "<bin>",
        "exec",
        "--json",
        "--no-session-log",
        "--preset",
        "empty",
        "--model",
        "muse-wonder-1.0",
        "--reasoning-effort",
        "high",
        "--contributor-mode",
        "off",
        "--approval-mode",
        "never",
        "--trust-workspace",
        "--workspace",
        "<workspace>",
        "--no-foreign-personal-context",
        "--disable-web-tools",
        "--disable-request-user-input",
        "--disable-reminders",
        "--disable-shell",
        "--disable-write",
        "--max-model-steps",
        str(MAX_MODEL_STEPS),
        "--output-schema",
        "<schema>",
        "--prompt-file",
        "<prompt>",
    ]
    assert MAX_MODEL_STEPS == 3
    assert "--yolo" not in record["argv"]


def test_child_env_drops_key_keeps_home_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_API_KEY", "fake-key-xyz")
    monkeypatch.setenv("HOME", "/fake/home")
    monkeypatch.setenv("PATH", "/fake/path")
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    _exec_client(fake).complete(_request())
    env = fake.calls[0]["env"]
    assert "META_API_KEY" not in env
    assert env["HOME"] == "/fake/home"
    assert env["PATH"] == "/fake/path"


def test_temp_files_while_running() -> None:
    prompt = "PROMPT-EXACT-2441"
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"word": {"type": "string"}},
    }
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    _exec_client(fake).complete(_request(prompt=prompt, schema=schema))
    record = fake.calls[0]
    assert record["prompt_bytes"] == prompt.encode()
    assert record["schema_bytes"] == json.dumps(schema).encode()
    assert record["prompt_mode"] == 0o600
    assert record["schema_mode"] == 0o600
    assert record["workspace_entries"] == []
    assert record["cwd"] == record["workspace"]
    assert record["workspace_isdir"] is True
    assert not os.path.exists(record["root"])


@pytest.mark.parametrize(
    "outcome",
    [
        _ok_result(SUCCESS_TEXT),
        RunResult(1, b"", False),
        RunResult(None, b"", True),
        RuntimeError("boom"),
    ],
    ids=["success", "exit-1", "timeout", "raises"],
)
def test_temp_root_gone_on_every_path(outcome: Any) -> None:
    fake = FakeRunner([outcome])
    client = _exec_client(fake)
    try:
        client.complete(_request())
    except (MetaUnavailableError, RuntimeError):
        pass
    assert len(_roots(fake)) == 1
    assert not os.path.exists(_roots(fake)[0])


_FAILED_STDOUT = _stdout(
    {"kind": "run_usage", "models": [], "calls": 1, "failed_calls": 1},
    {
        "kind": "run_terminal",
        "terminal": "failed",
        "text": "",
        "reason": "model does not exist [request_id=abc]",
    },
)


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (RunResult(1, _FAILED_STDOUT, False), "exit 1"),
        (RunResult(3, b"", False), "exit 3"),
        (RunResult(None, b"", True), "timeout"),
        (OSError("no such file"), "muse not runnable"),
        (RunResult(0, b"", False), "invalid response"),
        (RunResult(0, b"hello\nnot json {\n", False), "invalid response"),
        (
            RunResult(0, _stdout(_usage_payload(ONE_ROW)), False),
            "invalid response",
        ),
        (
            RunResult(
                0,
                _stdout(_usage_payload(ONE_ROW), _terminal_payload("", "failed")),
                False,
            ),
            "muse terminal",
        ),
        (
            RunResult(
                0,
                _stdout(
                    _usage_payload(ONE_ROW),
                    {
                        "kind": "run_terminal",
                        "terminal": "completed",
                        "text": 42,
                        "reason": None,
                    },
                ),
                False,
            ),
            "invalid response",
        ),
    ],
    ids=[
        "exit-1",
        "exit-3",
        "timeout",
        "oserror",
        "empty",
        "non-json",
        "no-terminal",
        "failed-terminal",
        "non-string-text",
    ],
)
def test_failures_map_to_closed_reasons(outcome: Any, reason: str) -> None:
    fake = FakeRunner([outcome])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    assert str(exc_info.value) == reason
    assert isinstance(exc_info.value.latency_ms, int)
    assert not os.path.exists(_roots(fake)[0])


def test_failures_hide_output() -> None:
    canary = "CANARY-9f2c"
    fake_key = "fake-key-abc123"
    stdout = f"{canary} {fake_key}\n".encode() + _FAILED_STDOUT
    fake = FakeRunner([RunResult(1, stdout, False)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "exit 1"
    for blob in (str(exc), repr(exc)):
        assert canary not in blob
        assert fake_key not in blob
        assert "model does not exist" not in blob
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_success_sums_two_model_rows() -> None:
    fake = FakeRunner([_ok_result(SUCCESS_TEXT, TWO_ROWS)])
    response = _exec_client(fake).complete(_request())
    assert response.text == SUCCESS_TEXT
    assert response.model_reported == "muse-wonder-1.0"
    assert response.finish_reason == "completed"
    assert response.prompt_tokens == 300
    assert response.cached_tokens == 12
    assert response.completion_tokens == 30
    assert response.reasoning_tokens == 12
    assert isinstance(response.latency_ms, int)


def test_missing_usage_gives_none_tokens() -> None:
    fake = FakeRunner([RunResult(0, _stdout(_terminal_payload(SUCCESS_TEXT)), False)])
    response = _exec_client(fake).complete(_request())
    assert response.text == SUCCESS_TEXT
    assert response.model_reported == "unreported"
    assert response.prompt_tokens is None
    assert response.cached_tokens is None
    assert response.completion_tokens is None
    assert response.reasoning_tokens is None


def test_usage_row_missing_one_field() -> None:
    models = [
        {
            "model": "muse-wonder-1.0",
            "input_tokens": 100,
            "output_tokens": 10,
            "reasoning_tokens": 3,
        }
    ]
    fake = FakeRunner([_ok_result(SUCCESS_TEXT, models)])
    response = _exec_client(fake).complete(_request())
    assert response.prompt_tokens == 100
    assert response.cached_tokens is None
    assert response.completion_tokens == 10
    assert response.reasoning_tokens == 3


def test_bool_token_is_not_an_int() -> None:
    models = [
        {
            "model": "muse-wonder-1.0",
            "input_tokens": True,
            "cached_tokens": False,
            "output_tokens": 5,
            "reasoning_tokens": 0,
        }
    ]
    fake = FakeRunner([_ok_result(SUCCESS_TEXT, models)])
    response = _exec_client(fake).complete(_request())
    assert response.prompt_tokens is None
    assert response.cached_tokens is None
    assert response.completion_tokens == 5
    assert response.reasoning_tokens == 0


def test_version_runs_once_per_bin() -> None:
    fake = FakeRunner([_ok_result(SUCCESS_TEXT), _ok_result(SUCCESS_TEXT)])
    first = _exec_client(fake, muse_bin="bin-one")
    first.complete(_request())
    first.complete(_request())
    assert first.transport_version == "muse 1.2.3"
    second = _exec_client(fake, muse_bin="bin-one")
    assert second.transport_version == "muse 1.2.3"
    assert fake.version_calls == 1


@pytest.mark.parametrize(
    "version_outcome",
    [
        RunResult(1, b"", False),
        RunResult(0, b"", False),
        RunResult(0, "muse \xff\xfe\n".encode("latin-1"), False),
        RunResult(0, (b"x" * 81 + b"\n"), False),
        OSError("no such file"),
    ],
    ids=["exit-1", "empty", "non-ascii", "too-long", "oserror"],
)
def test_bad_version_gives_none(version_outcome: Any) -> None:
    fake = FakeRunner([], version_script=[version_outcome])
    client = _exec_client(fake, muse_bin="bin-bad")
    assert client.transport_version is None


def test_contributor_model_refused_without_runner_calls() -> None:
    fake = FakeRunner([])
    client = _exec_client(fake)
    with pytest.raises(ContributorModelRefused):
        client.complete(_request(model="x-contributor-y"))
    with pytest.raises(ContributorModelRefused):
        client.complete(_request(model="MODEL-CONTRIBUTOR-Z"))
    assert fake.calls == []


def test_unknown_effort_refused_without_runner_calls() -> None:
    fake = FakeRunner([])
    with pytest.raises(ValueError, match="unknown effort"):
        _exec_client(fake).complete(_request(effort="ultra"))
    assert fake.calls == []


def test_dash_model_refused_without_runner_calls() -> None:
    fake = FakeRunner([])
    with pytest.raises(ValueError, match="unknown model"):
        _exec_client(fake).complete(_request(model="--yolo"))
    assert fake.calls == []


def _propose_with(client: MuseExecClient, case: Case, policy: str = "") -> Any:
    context = build_context(case)
    slot = datetime.fromisoformat(case.slot_iso)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    assert hour is not None
    return propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=client,
        models=MODELS,
        policy=policy,
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )


def _draft_stdout(text: str) -> bytes:
    return _stdout(_usage_payload(ONE_ROW), _terminal_payload(text))


def _spy_temp_dirs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    created: list[str] = []
    real = tempfile.TemporaryDirectory

    def _spy(*args: Any, **kwargs: Any) -> Any:
        created.append("tmp")
        return real(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", _spy)
    return created


def test_blocked_fact_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _spy_temp_dirs(monkeypatch)
    marked = BASE_FACTS[0].model_copy(
        update={"statement": "Synthetic session harbor-light finished yesterday"}
    )
    case = Case(
        name="muse-blocked-fact",
        facts=(marked, BASE_FACTS[1]),
        private_terms=("harbor-light",),
    )
    fake = FakeRunner([])
    client = _exec_client(fake, private_terms=("harbor-light",))
    result = _propose_with(client, case)
    assert result.kind == "noop"
    assert "NOOP_OUTBOUND_BLOCKED" in result.reason_codes
    assert len(result.attempts) == 1
    assert result.attempts[0].blocked is True
    assert _exec_calls(fake) == []
    assert created == []


def test_blocked_title_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _spy_temp_dirs(monkeypatch)
    marked = BASE_ELIGIBLE[0].model_copy(update={"title": "Build harbor-light sketch"})
    case = Case(
        name="muse-blocked-title",
        eligible=(marked, BASE_ELIGIBLE[1]),
        private_terms=("harbor-light",),
    )
    fake = FakeRunner([])
    client = _exec_client(fake, private_terms=("harbor-light",))
    result = _propose_with(client, case)
    assert result.kind == "noop"
    assert "NOOP_OUTBOUND_BLOCKED" in result.reason_codes
    assert _exec_calls(fake) == []
    assert created == []


def test_blocked_policy_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _spy_temp_dirs(monkeypatch)
    case = Case(name="muse-blocked-policy", private_terms=("harbor-light",))
    fake = FakeRunner([])
    client = _exec_client(fake, private_terms=("harbor-light",))
    result = _propose_with(client, case, policy="ranking harbor-light note")
    assert result.kind == "noop"
    assert "NOOP_OUTBOUND_BLOCKED" in result.reason_codes
    assert _exec_calls(fake) == []
    assert created == []


def test_propose_valid_draft_is_proposal() -> None:
    fake = FakeRunner([RunResult(0, _draft_stdout(GOOD_DRAFT), False)])
    client = _exec_client(fake, muse_bin="bin-propose")
    result = _propose_with(client, Case(name="muse-ok"))
    assert result.kind == "proposal"
    assert len(result.attempts) == 1
    assert result.briefing is not None
    attempt = result.attempts[0]
    assert attempt.transport == "muse"
    assert attempt.transport_version == "muse 1.2.3"
    assert attempt.cached_tokens == 0


def test_propose_unparseable_then_valid() -> None:
    fake = FakeRunner(
        [
            RunResult(0, _draft_stdout("not json"), False),
            RunResult(0, _draft_stdout(GOOD_DRAFT), False),
        ]
    )
    client = _exec_client(fake, muse_bin="bin-retry")
    result = _propose_with(client, Case(name="muse-retry"))
    assert result.kind == "proposal"
    assert len(result.attempts) == 2
    assert result.attempts[0].parsed_ok is False


def test_propose_invalid_twice_is_fallback() -> None:
    fake = FakeRunner(
        [
            RunResult(0, _draft_stdout("{}"), False),
            RunResult(0, _draft_stdout("{}"), False),
        ]
    )
    client = _exec_client(fake, muse_bin="bin-invalid")
    result = _propose_with(client, Case(name="muse-invalid"))
    assert result.kind == "fallback"
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_UNPARSEABLE",)


def test_propose_exit_1_is_unavailable_fallback() -> None:
    fake = FakeRunner([RunResult(1, _FAILED_STDOUT, False)])
    client = _exec_client(fake, muse_bin="bin-exit")
    result = _propose_with(client, Case(name="muse-exit"))
    assert result.kind == "fallback"
    assert result.attempts[0].codes == (("MODEL_UNAVAILABLE", "exit 1"),)
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_MODEL_UNAVAILABLE",)


def test_propose_empty_text_is_unparseable() -> None:
    fake = FakeRunner(
        [
            RunResult(0, _draft_stdout(""), False),
            RunResult(0, _draft_stdout(""), False),
        ]
    )
    client = _exec_client(fake, muse_bin="bin-empty")
    result = _propose_with(client, Case(name="muse-empty"))
    assert result.kind == "fallback"
    assert result.attempts[0].codes == (("DRAFT_UNPARSEABLE", "draft"),)
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_UNPARSEABLE",)


def test_attempt_rows_hold_transport_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from evals.proposal_cases import CASES_BY_NAME, run_case

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    rules_dir = tmp_path / "xdg" / "muse"
    rules_dir.mkdir(parents=True)
    (rules_dir / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    fake = FakeRunner(
        [RunResult(0, _draft_stdout(GOOD_DRAFT), False)],
        version_stdout=b"muse 9.9.9\n",
    )
    client = _exec_client(fake, muse_bin="bin-stored")
    result = _propose_with(client, Case(name="muse-stored"))
    assert result.kind == "proposal"
    assert client.transport_version == "muse 9.9.9"
    assert result.attempts[0].harness_rules_file is True
    (rules_dir / "AGENTS.md").unlink()
    assert client.harness_rules_file is False
    bare = FakeRunner(
        [RunResult(0, _draft_stdout(GOOD_DRAFT), False)],
        version_stdout=b"muse 9.9.9\n",
    )
    bare_client = _exec_client(bare, muse_bin="bin-stored-bare")
    bare_result = _propose_with(bare_client, Case(name="muse-stored-bare"))
    assert bare_result.attempts[0].harness_rules_file is False
    scripted = run_case(CASES_BY_NAME["P1"])
    assert scripted.attempts[0].harness_rules_file is None
    store = ProposalStore(db_path=tmp_path / "muse.db")
    try:
        store.record(result, snapshot=dict(BASE_SNAPSHOT))
        store.record(bare_result, snapshot=dict(BASE_SNAPSHOT))
        store.record(scripted, snapshot=dict(BASE_SNAPSHOT))
        conn = sqlite3.connect(store.db_path)
        try:
            rows = conn.execute(
                "SELECT cached_tokens, transport, transport_version,"
                " harness_rules_file FROM proposal_attempts ORDER BY rowid"
            ).fetchall()
        finally:
            conn.close()
    finally:
        store.close()
    assert rows == [
        (0, "muse", "muse 9.9.9", 1),
        (0, "muse", "muse 9.9.9", 0),
        (None, "scripted", None, None),
    ]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_default_runner_kills_group_on_timeout(tmp_path: Path) -> None:
    from framework.proposal.muse_client import _default_runner

    script = tmp_path / "hang.sh"
    script.write_text(
        '#!/bin/sh\nsleep 60 &\necho "$$ $!" > pids\nwait\n', encoding="utf-8"
    )
    script.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    start = time.monotonic()
    result = _default_runner([str(script)], env=env, timeout_s=0.5, cwd=str(tmp_path))
    elapsed = time.monotonic() - start
    assert result.timed_out is True
    assert result.returncode is None
    assert elapsed < 10
    pids = (tmp_path / "pids").read_text(encoding="utf-8").split()
    assert len(pids) == 2
    deadline = time.monotonic() + 5
    while True:
        alive = [pid for pid in pids if _pid_alive(int(pid))]
        if not alive:
            break
        assert time.monotonic() < deadline, f"pids still alive: {alive}"
        time.sleep(0.05)


def test_default_runner_ignores_stderr(tmp_path: Path) -> None:
    usage = _line(_usage_payload(ONE_ROW))
    terminal = _line(_terminal_payload(SUCCESS_TEXT))
    script = tmp_path / "ok.sh"
    script.write_text(
        "#!/bin/sh\necho 'CANARY_STDERR_4d2a' >&2\n"
        f"printf '%s\\n' '{usage}' '{terminal}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    client = MuseExecClient(
        private_terms_available=True, muse_bin=str(script), timeout_s=30
    )
    response = client.complete(_request(schema={"type": "object"}))
    assert response.text == SUCCESS_TEXT
    assert response.prompt_tokens == 25100
    assert "CANARY_STDERR_4d2a" not in repr(response)


def _pass(name):  # type: ignore[no-untyped-def]
    return PassResult(
        name=name,
        attempts=0,
        raw_valid=True,
        model_id="",
        latency_ms=0,
        finish_reason=None,
        completion_tokens=None,
        kept=0,
        noop_reason=None,
    )


def _seed_cycle(db: Path) -> None:
    from framework.briefing.context import MetricSnapshot

    as_of = datetime.fromisoformat(AS_OF_ISO)
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    try:
        result = FactResult(
            facts=tuple(BASE_FACTS),
            code_fact_ids=(),
            snapshot=MetricSnapshot(values=dict(BASE_SNAPSHOT)),
            passes=(_pass("personal"), _pass("feed")),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT_ID_CLI,
            as_of=as_of,
            window_start=as_of - timedelta(hours=72),
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
    finally:
        fact_store.close()
        store.close()


def _write_commitments(tmp_path: Path) -> Path:
    path = tmp_path / "commitments.json"
    path.write_text(
        json.dumps([c.model_dump(mode="json") for c in BASE_ELIGIBLE]),
        encoding="utf-8",
    )
    return path


def _write_terms(tmp_path: Path) -> Path:
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "deny-terms.txt").write_text("harbor-light\n", encoding="utf-8")
    return hidden


def _env_no_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Path) -> list[str]:
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(_write_terms(tmp_path)))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(_write_commitments(tmp_path)))
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID_CLI)
    monkeypatch.setenv("MUSE_BIN", sys.executable)
    return ["propose", "--as-of", AS_OF_ISO, "--slot", SLOT_ISO, "--db", str(db)]


def _stub_client(script_texts: list[str]) -> Any:
    from evals.proposal_cases import ScriptEntry

    script = tuple(ScriptEntry(kind="text", text=text) for text in script_texts)

    def _factory(**kwargs: Any) -> Any:
        return ScriptedWonderClient(script)

    return _factory


def test_cli_defaults_to_muse_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env_no_key(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MuseExecClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == [
        (
            "profile=builder kind=proposal attempts=1 codes=- seconds=0.0s "
            "tokens=13 stale=0"
        ),
        (
            "profile=disconnect kind=noop attempts=0 codes=NOOP_NO_ELIGIBLE_COMMITMENT "
            "seconds=0.0s tokens=0 stale=0"
        ),
    ]


def test_cli_api_without_key_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env_no_key(monkeypatch, tmp_path, db) + ["--transport", "api"]
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: META_API_KEY\n", captured.err
    assert captured.out == ""


def test_cli_missing_muse_bin_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env_no_key(monkeypatch, tmp_path, db)
    monkeypatch.setenv("MUSE_BIN", str(tmp_path / "missing-muse"))
    monkeypatch.setattr(propose_main, "MuseExecClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: MUSE_BIN\n", captured.err
    assert captured.out == ""


def test_cli_unknown_transport_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env_no_key(monkeypatch, tmp_path, db) + ["--transport", "warp"]
    with pytest.raises(SystemExit) as exc_info:
        propose_main.main(args)
    assert exc_info.value.code == 2


def test_temp_dir_creation_failure_is_temp_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import framework.proposal.muse_client as muse_module

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no temp dir")

    monkeypatch.setattr(muse_module.tempfile, "TemporaryDirectory", _boom)
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "temp files"
    assert isinstance(exc.latency_ms, int)
    assert exc.__context__ is None
    assert _exec_calls(fake) == []


def test_prompt_write_failure_is_temp_files_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import framework.proposal.muse_client as muse_module

    created: list[str] = []
    real = tempfile.TemporaryDirectory

    def _spy(*args: Any, **kwargs: Any) -> Any:
        instance = real(*args, **kwargs)
        created.append(instance.name)
        return instance

    monkeypatch.setattr(muse_module.tempfile, "TemporaryDirectory", _spy)

    def _boom_write(path: str, data: bytes) -> None:
        raise OSError("cannot write prompt")

    monkeypatch.setattr(muse_module, "_write_exclusive", _boom_write)
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "temp files"
    assert isinstance(exc.latency_ms, int)
    assert exc.__context__ is None
    assert _exec_calls(fake) == []
    assert len(created) == 1
    assert not os.path.exists(created[0])


def test_temp_removal_failure_after_good_response_is_temp_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import framework.proposal.muse_client as muse_module

    class _RemoveFails(tempfile.TemporaryDirectory):
        def cleanup(self) -> None:
            super().cleanup()
            raise OSError("cannot remove temp dir")

    monkeypatch.setattr(muse_module.tempfile, "TemporaryDirectory", _RemoveFails)
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "temp files"
    assert isinstance(exc.latency_ms, int)
    assert exc.__context__ is None


def test_large_prompt_reaches_file_whole() -> None:
    sentence = "Chat was 3 hours in the last period. "
    count = (2 * 1024 * 1024 + len(sentence) - 1) // len(sentence)
    prompt = sentence * count
    fake = FakeRunner([_ok_result(SUCCESS_TEXT)])
    _exec_client(fake).complete(_request(prompt=prompt))
    record = _exec_calls(fake)[0]
    assert record["prompt_bytes"] == prompt.encode()
    assert len(record["prompt_bytes"]) == count * len(sentence)


def _configured_payload(model_id: Any) -> dict[str, Any]:
    return {"kind": "run_model_configured", "model_id": model_id}


def _contributor_row(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input_tokens": 100,
        "cached_tokens": 0,
        "output_tokens": 10,
        "reasoning_tokens": 3,
        "calls": 1,
    }


def test_reported_contributor_usage_model_is_closed() -> None:
    stdout = _stdout(
        _usage_payload([_contributor_row("muse-wonder-1.0-contributor")]),
        _terminal_payload(SUCCESS_TEXT),
    )
    fake = FakeRunner([RunResult(0, stdout, False)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "contributor model"
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_reported_contributor_configured_model_is_closed() -> None:
    stdout = _stdout(
        _configured_payload("muse-spark-1.3-contributor"),
        _usage_payload(ONE_ROW),
        _terminal_payload(SUCCESS_TEXT),
    )
    fake = FakeRunner([RunResult(0, stdout, False)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "contributor model"
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_reported_contributor_second_usage_row_is_closed() -> None:
    stdout = _stdout(
        _usage_payload(
            [
                _contributor_row("muse-wonder-1.0"),
                _contributor_row("MUSE-Wonder-1.0-Contributor"),
            ]
        ),
        _terminal_payload(SUCCESS_TEXT),
    )
    fake = FakeRunner([RunResult(0, stdout, False)])
    with pytest.raises(MetaUnavailableError) as exc_info:
        _exec_client(fake).complete(_request())
    assert str(exc_info.value) == "contributor model"


def test_clean_configured_model_still_returns_response() -> None:
    stdout = _stdout(
        _configured_payload("muse-wonder-1.0"),
        _usage_payload(ONE_ROW),
        _terminal_payload(SUCCESS_TEXT),
    )
    fake = FakeRunner([RunResult(0, stdout, False)])
    response = _exec_client(fake).complete(_request())
    assert response.text == SUCCESS_TEXT


def test_propose_contributor_run_is_unavailable_fallback() -> None:
    stdout = _stdout(
        _usage_payload([_contributor_row("muse-wonder-1.0-contributor")]),
        _terminal_payload(GOOD_DRAFT),
    )
    fake = FakeRunner([RunResult(0, stdout, False)])
    client = _exec_client(fake, muse_bin="bin-contributor")
    result = _propose_with(client, Case(name="muse-contributor"))
    assert result.kind == "fallback"
    assert result.attempts[0].codes == (("MODEL_UNAVAILABLE", "contributor model"),)
    assert result.attempts[0].raw_text == ""
    assert GOOD_DRAFT not in result.attempts[0].raw_text
    assert result.briefing is None
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_MODEL_UNAVAILABLE",)
