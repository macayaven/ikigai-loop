"""One more attempt for a Wonder call that ends in a timeout (made-up data)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    WonderRequest,
    WonderResponse,
)
from framework.proposal.muse_client import (
    LocalStartFailure,
    MuseExecClient,
    RunResult,
)
from framework.proposal.timeout_retry import TimeoutRetryClient


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real home: the temp root lives under it."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))


SUCCESS_TEXT = '{"word": "blue"}'


def _request() -> WonderRequest:
    return WonderRequest(
        prompt="clean prompt text",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={"type": "object"},
    )


def _response(text: str = SUCCESS_TEXT) -> WonderResponse:
    return WonderResponse(
        text=text,
        model_reported="muse-wonder-1.0",
        latency_ms=9000,
        finish_reason="completed",
        prompt_tokens=10,
        completion_tokens=5,
        reasoning_tokens=None,
        cached_tokens=None,
    )


class _FakeInner:
    """Scripted outcomes; records each request it was given."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.requests: list[WonderRequest] = []
        self.transport = "muse"
        self.transport_version: str | None = "fake version 1.0"
        self.harness_rules_file: bool | None = True

    def complete(self, request: WonderRequest) -> WonderResponse:
        self.requests.append(request)
        outcome = self._script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, WonderResponse)
        return outcome


def _timeout() -> MetaUnavailableError:
    return MetaUnavailableError("timeout", latency_ms=120000)


def _client(
    script: list[Any], left: float | None = 1000.0, minimum: float = 120.0
) -> tuple[TimeoutRetryClient, _FakeInner, list[float | None]]:
    inner = _FakeInner(script)
    seen: list[float | None] = []

    def _seconds_left() -> float | None:
        seen.append(left)
        return left

    return (
        TimeoutRetryClient(inner, seconds_left=_seconds_left, min_seconds_left=minimum),
        inner,
        seen,
    )


def test_timeout_then_response_returns_response() -> None:
    retry, inner, _ = _client([_timeout(), _response()])
    request = _request()
    assert retry.complete(request) == _response()
    assert inner.requests == [request, request]
    assert len(inner.requests) == 2
    assert retry.retries == 1


def test_two_timeouts_raise_the_second_failure() -> None:
    first = _timeout()
    second = _timeout()
    retry, inner, _ = _client([first, second])
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert exc_info.value is second
    assert len(inner.requests) == 2
    assert retry.retries == 1


def test_second_failure_carries_no_context() -> None:
    """Two timeouts: the raised failure holds no `__context__`.

    The second attempt runs after the handler has ended, like the
    Muse client's raises outside its handlers and the local retry's
    next attempt outside its handler.
    """
    retry, _, _ = _client([_timeout(), _timeout()])
    with pytest.raises(MetaUnavailableError) as exc_info:
        retry.complete(_request())
    assert exc_info.value.__context__ is None


def test_seconds_left_just_under_minimum_never_retries() -> None:
    retry, inner, seen = _client([_timeout()], left=119.9, minimum=120.0)
    with pytest.raises(MetaUnavailableError, match="^timeout$"):
        retry.complete(_request())
    assert len(inner.requests) == 1
    assert retry.retries == 0
    assert seen == [119.9]


def test_seconds_left_exactly_at_minimum_retries() -> None:
    retry, inner, _ = _client([_timeout(), _response()], left=120.0, minimum=120.0)
    assert retry.complete(_request()) == _response()
    assert len(inner.requests) == 2
    assert retry.retries == 1


def test_no_seconds_left_never_retries() -> None:
    retry, inner, seen = _client([_timeout()], left=None)
    with pytest.raises(MetaUnavailableError, match="^timeout$"):
        retry.complete(_request())
    assert len(inner.requests) == 1
    assert retry.retries == 0
    assert seen == [None]


@pytest.mark.parametrize(
    "failure",
    [
        MetaUnavailableError("exit 1", latency_ms=5),
        MetaUnavailableError("muse not runnable", latency_ms=5),
        MetaUnavailableError("temp files", latency_ms=5),
        MetaUnavailableError("invalid response", latency_ms=5),
        MetaUnavailableError("muse terminal", latency_ms=5),
        MetaUnavailableError("contributor model", latency_ms=5),
        MetaUnavailableError("slot deadline", latency_ms=0),
        LocalStartFailure("exit 1", latency_ms=150, exit_code=1, stderr_masked=""),
        LocalStartFailure("timeout", latency_ms=150, exit_code=1, stderr_masked=""),
        ContributorModelRefused("contributor models are refused"),
        ValueError("boom"),
    ],
    ids=[
        "exit",
        "not-runnable",
        "temp-files",
        "invalid-response",
        "muse-terminal",
        "contributor-model",
        "slot-deadline",
        "local-start",
        "local-start-timeout",
        "contributor-refused",
        "unrelated",
    ],
)
def test_other_failures_go_up_on_the_first_try(failure: BaseException) -> None:
    retry, inner, seen = _client([_response()])
    inner._script.insert(0, failure)
    with pytest.raises(type(failure)) as exc_info:
        retry.complete(_request())
    assert exc_info.value is failure
    assert len(inner.requests) == 1
    assert retry.retries == 0
    assert seen == []


def test_two_calls_each_timeout_once_count_two() -> None:
    retry, inner, _ = _client(
        [_timeout(), _response(), _timeout(), _response()], left=1000.0
    )
    assert retry.complete(_request()) == _response()
    assert retry.complete(_request()) == _response()
    assert len(inner.requests) == 4
    assert retry.retries == 2


def test_transport_properties_forward() -> None:
    retry, inner, _ = _client([_response()])
    assert retry.transport == "muse"
    assert retry.transport_version == "fake version 1.0"
    assert retry.harness_rules_file is True
    inner.transport_version = None
    inner.harness_rules_file = None
    assert retry.transport_version is None
    assert retry.harness_rules_file is None


def _line(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "stream": {"kind": "session", "id": "s"},
            "record_type": "event",
            "payload": payload,
        }
    )


def test_timed_out_run_through_the_real_client_retries() -> None:
    """The rule keys on the client's ``timeout`` reason; a rename breaks this."""
    from framework.proposal.muse_client import RunResult as _Run

    models = [
        {
            "model": "muse-wonder-1.0",
            "input_tokens": 10,
            "cached_tokens": 0,
            "output_tokens": 5,
            "reasoning_tokens": 2,
        }
    ]
    usage = {"kind": "run_usage", "models": models, "calls": 1, "completed_calls": 1}
    terminal = {"kind": "run_terminal", "terminal": "completed", "text": SUCCESS_TEXT}
    good = (_line(usage) + "\n" + _line(terminal) + "\n").encode()

    calls = 0

    def _fake_runner(
        argv: Any, *, env: Any, timeout_s: float, cwd: str | None
    ) -> RunResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _Run(None, b"", True)
        return _Run(0, good, False)

    inner = MuseExecClient(
        private_terms=(),
        private_terms_available=True,
        muse_bin="/fake/muse",
        runner=_fake_runner,
    )
    retry = TimeoutRetryClient(
        inner, seconds_left=lambda: 1000.0, min_seconds_left=120.0
    )
    assert retry.complete(_request()).text == SUCCESS_TEXT
    assert calls == 2
    assert retry.retries == 1
