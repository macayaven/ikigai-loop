"""Local start failures retried inside the propose deadline (made-up data)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from framework.proposal.core import MetaUnavailableError, WonderRequest
from framework.proposal.local_retry import (
    FIRST_RETRY_DELAY_S,
    SECOND_RETRY_DELAY_S,
    LocalRetryClient,
    mask_stderr,
)
from framework.proposal.muse_client import (
    LocalStartFailure,
    MuseExecClient,
    RunResult,
    _default_runner,
)

SUCCESS_TEXT = '{"word": "blue"}'
PRIVATE_CANARY = "ZzPrivateTermCanary"
TOKEN_CANARY = "tok_" + "Ab3-" * 8
EMAIL_CANARY = "madeup.fellow@example.invalid"
PLAIN_SENTENCE = "muse died before any model request ran"

STDERR_RAW = (
    f"{PLAIN_SENTENCE}\n{PRIVATE_CANARY} {TOKEN_CANARY} "
    f"{EMAIL_CANARY} {os.path.expanduser('~')}/madeup-notes.txt\n"
).encode()


def _line(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "stream": {"kind": "session", "id": "s"},
            "record_type": "event",
            "payload": payload,
        }
    )


def _terminal(text: Any, terminal: str = "completed") -> dict[str, Any]:
    return {"kind": "run_terminal", "terminal": terminal, "text": text, "reason": None}


def _usage(models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "run_usage",
        "models": models,
        "calls": 1,
        "completed_calls": 1,
        "failed_calls": 0,
        "allowance": {"window": {"used_percent": 11}},
    }


def _ok_stdout(text: str = SUCCESS_TEXT) -> bytes:
    models = [
        {
            "model": "muse-wonder-1.0",
            "input_tokens": 10,
            "cached_tokens": 0,
            "output_tokens": 5,
            "reasoning_tokens": 2,
        }
    ]
    return ("\n".join([_line(_usage(models)), _line(_terminal(text))]) + "\n").encode()


def _request() -> WonderRequest:
    return WonderRequest(
        prompt="clean prompt text",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={"type": "object"},
    )


class FakeRunner:
    """Scripted outcomes; records how often the binary would have run."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls = 0

    def __call__(
        self,
        argv: Any,
        *,
        env: Any,
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        self.calls += 1
        outcome = self._script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, RunResult)
        return outcome


def _client(fake: FakeRunner) -> MuseExecClient:
    return MuseExecClient(
        private_terms=(PRIVATE_CANARY,),
        private_terms_available=True,
        muse_bin="/fake/muse",
        runner=fake,
    )


def _exit(code: int, stderr: bytes = b"") -> RunResult:
    return RunResult(code, b"boom\n", False, stderr)


def _timeout() -> RunResult:
    return RunResult(None, b"", True)


def test_fast_exit_failure_retried_once_then_succeeds() -> None:
    fake = FakeRunner([_exit(1, STDERR_RAW), RunResult(0, _ok_stdout(), False)])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    response = retry.complete(_request())
    assert response.text == SUCCESS_TEXT
    assert sleeps == [FIRST_RETRY_DELAY_S]
    assert FIRST_RETRY_DELAY_S == 5.0
    assert len(retry.failures) == 1
    record = retry.failures[0]
    assert (record.attempt, record.reason) == (1, "exit 1")
    assert record.exit_code == 1
    assert record.latency_ms < 2000
    assert PLAIN_SENTENCE in record.stderr_masked
    for canary in (PRIVATE_CANARY, TOKEN_CANARY, EMAIL_CANARY):
        assert canary not in record.stderr_masked


def test_two_fast_failures_wait_five_then_twenty() -> None:
    fake = FakeRunner(
        [_exit(1, b"first\n"), _exit(3, b"second\n"), RunResult(0, _ok_stdout(), False)]
    )
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    assert retry.complete(_request()).text == SUCCESS_TEXT
    assert sleeps == [FIRST_RETRY_DELAY_S, SECOND_RETRY_DELAY_S]
    assert SECOND_RETRY_DELAY_S == 20.0
    assert [(item.attempt, item.reason) for item in retry.failures] == [
        (1, "exit 1"),
        (2, "exit 3"),
    ]


def test_three_fast_failures_raise_last_with_all_recorded() -> None:
    fake = FakeRunner([_exit(1, b"one\n"), _exit(1, b"two\n"), _exit(3, b"three\n")])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    with pytest.raises(LocalStartFailure) as exc_info:
        retry.complete(_request())
    assert str(exc_info.value) == "exit 3"
    assert exc_info.value.exit_code == 3
    assert sleeps == [FIRST_RETRY_DELAY_S, SECOND_RETRY_DELAY_S]
    assert [(item.attempt, item.reason) for item in retry.failures] == [
        (1, "exit 1"),
        (2, "exit 1"),
        (3, "exit 3"),
    ]
    assert fake.calls == 3


def test_timeout_is_never_retried() -> None:
    fake = FakeRunner([_timeout()])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert type(exc_info.value) is MetaUnavailableError
    assert str(exc_info.value) == "timeout"
    assert sleeps == []
    assert retry.failures == ()


def test_slow_exit_is_never_retried() -> None:
    class _Slow(FakeRunner):
        def __call__(self, argv: Any, **kwargs: Any) -> RunResult:
            self.calls += 1
            time.sleep(2.1)
            return RunResult(1, b"slow\n", False, b"")

    sleeps: list[float] = []
    retry = LocalRetryClient(_client(_Slow([])), sleep=sleeps.append)
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert type(exc_info.value) is MetaUnavailableError
    assert str(exc_info.value) == "exit 1"
    assert sleeps == []
    assert retry.failures == ()


def test_contributor_model_is_never_retried() -> None:
    models = [
        {
            "model": "muse-wonder-1.0-contributor",
            "input_tokens": 10,
            "cached_tokens": 0,
            "output_tokens": 5,
            "reasoning_tokens": 2,
        }
    ]
    stdout = (
        "\n".join([_line(_usage(models)), _line(_terminal(SUCCESS_TEXT))]) + "\n"
    ).encode()
    fake = FakeRunner([RunResult(0, stdout, False)])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert type(exc_info.value) is MetaUnavailableError
    assert str(exc_info.value) == "contributor model"
    assert sleeps == []
    assert retry.failures == ()


def test_muse_terminal_is_never_retried() -> None:
    stdout = (_line(_terminal("", terminal="failed")) + "\n").encode()
    fake = FakeRunner([RunResult(0, stdout, False)])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert type(exc_info.value) is MetaUnavailableError
    assert str(exc_info.value) == "muse terminal"
    assert sleeps == []
    assert retry.failures == ()


def test_invalid_response_without_terminal_is_a_local_start() -> None:
    fake = FakeRunner(
        [RunResult(0, b"not json\n", False), RunResult(0, _ok_stdout(), False)]
    )
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    assert retry.complete(_request()).text == SUCCESS_TEXT
    assert sleeps == [FIRST_RETRY_DELAY_S]
    assert [(item.attempt, item.reason) for item in retry.failures] == [
        (1, "invalid response")
    ]


def test_invalid_response_with_terminal_event_is_plain() -> None:
    stdout = (_line(_terminal(42)) + "\n").encode()
    fake = FakeRunner([RunResult(0, stdout, False)])
    sleeps: list[float] = []
    retry = LocalRetryClient(_client(fake), sleep=sleeps.append)
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert type(exc_info.value) is MetaUnavailableError
    assert str(exc_info.value) == "invalid response"
    assert sleeps == []
    assert retry.failures == ()


def test_plain_meta_unavailable_passes_through_untouched() -> None:
    sentinel = MetaUnavailableError("slot deadline", latency_ms=0)

    class _Inner:
        transport = "muse"
        transport_version: str | None = "fake version 1.0"
        harness_rules_file: bool | None = None
        calls = 0

        def complete(self, request: WonderRequest) -> Any:
            self.calls += 1
            raise sentinel

    inner = _Inner()
    sleeps: list[float] = []
    retry = LocalRetryClient(inner, sleep=sleeps.append)  # type: ignore[arg-type]
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert exc_info.value is sentinel
    assert sleeps == []
    assert retry.failures == ()
    assert retry.transport == "muse"
    assert retry.transport_version == "fake version 1.0"
    assert retry.harness_rules_file is None


@pytest.mark.parametrize(
    ("left", "want_sleeps", "want_calls"),
    [(10.0, [5.0], 2), (3.0, [], 1), (5.0, [5.0], 2)],
    ids=["second-delay-misses", "first-delay-misses", "exact-fit-runs"],
)
def test_retry_stops_when_next_delay_misses_seconds_left(
    left: float, want_sleeps: list[float], want_calls: int
) -> None:
    script: list[Any] = [_exit(1, b"burst\n")] * 3
    fake = FakeRunner(script)
    sleeps: list[float] = []
    retry = LocalRetryClient(
        _client(fake), sleep=sleeps.append, seconds_left=lambda: left
    )
    with pytest.raises(LocalStartFailure):
        retry.complete(_request())
    assert sleeps == want_sleeps
    assert fake.calls == want_calls
    assert len(retry.failures) == want_calls


def test_masking_removes_canaries_and_keeps_a_plain_sentence() -> None:
    path_canary = "/home/someone/secret-path"
    raw = STDERR_RAW + f"crash at {path_canary} end\n".encode()
    masked = mask_stderr(raw, (PRIVATE_CANARY,))
    assert PLAIN_SENTENCE in masked
    for canary in (
        PRIVATE_CANARY,
        PRIVATE_CANARY.lower(),
        TOKEN_CANARY,
        EMAIL_CANARY,
        os.path.expanduser("~") + "/madeup-notes.txt",
        path_canary,
        "secret-path",
    ):
        assert canary not in masked
    assert os.path.expanduser("~") not in masked
    assert len(mask_stderr(b"word " * 2000, ())) == 2000


def test_masking_hides_paths_after_quote_equals_or_bracket() -> None:
    quoted = "/home/someone/secret"
    equals = "/srv/data/x"
    bracket = "/opt/thing"
    raw = (
        f"No such file: '{quoted}' store={equals} ({bracket}) keep a/b and ./c end\n"
    ).encode()
    masked = mask_stderr(raw, ())
    for canary in (quoted, equals, bracket, "someone", "/srv/data", "/opt/thing"):
        assert canary not in masked
    assert "a/b" in masked
    assert "./c" in masked


def test_failure_message_and_repr_hold_no_stderr() -> None:
    fake = FakeRunner([_exit(1, STDERR_RAW)])
    with pytest.raises(LocalStartFailure) as exc_info:
        _client(fake).complete(_request())
    exc = exc_info.value
    assert str(exc) == "exit 1"
    for blob in (str(exc), repr(exc)):
        assert PRIVATE_CANARY not in blob
        assert TOKEN_CANARY not in blob
        assert EMAIL_CANARY not in blob
        assert PLAIN_SENTENCE not in blob
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert isinstance(exc.latency_ms, int)
    assert PLAIN_SENTENCE in exc.stderr_masked
    assert PRIVATE_CANARY not in exc.stderr_masked


def test_default_runner_returns_stderr_only_on_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.sh"
    bad.write_text(
        "#!/bin/sh\necho 'CANARY_ERR_7aa1' >&2\necho out\nexit 3\n",
        encoding="utf-8",
    )
    bad.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    failed = _default_runner([str(bad)], env=env, timeout_s=30, cwd=str(tmp_path))
    assert failed.returncode == 3
    assert failed.timed_out is False
    assert b"CANARY_ERR_7aa1" in failed.stderr
    assert failed.stdout == b"out\n"

    good = tmp_path / "good.sh"
    good.write_text(
        "#!/bin/sh\necho 'CANARY_ERR_7aa1' >&2\necho out\n", encoding="utf-8"
    )
    good.chmod(0o755)
    ok = _default_runner([str(good)], env=env, timeout_s=30, cwd=str(tmp_path))
    assert ok.returncode == 0
    assert ok.stderr == b""
