"""Ticket 11: edge client over fake/recording transports, plus source scans."""

from __future__ import annotations

import http.client
import inspect
import json
import logging
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, Self

import pytest

from evals.proposal_cases import (
    AS_OF,
    CASES_BY_NAME,
    CYCLE_ID,
    GOOD_DRAFT,
    LIMITS,
    MODELS,
    PROFILE_ID,
    STALE_AFTER_S,
    SUBJECT_ID,
    Case,
    build_context,
)
from framework.briefing.gate import scan_outbound_text
from framework.proposal.client import (
    MetaClient,
    MetaConfigError,
    load_meta_config,
    refuse_contributor_model,
)
from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    OutboundBlocked,
    WonderRequest,
    propose,
)
from framework.proposal.hour import pick_hour
from framework.proposal.schemas import build_response_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_DIR = REPO_ROOT / "framework" / "proposal"
FAKE_KEY = "synthetic-fake-key-VALUE"


def _envelope(
    content: Any,
    *,
    finish: Any = "stop",
    model: Any = "muse-wonder-1.0",
    prompt_tokens: Any = 11,
    completion_tokens: Any = 13,
    reasoning: Any = None,
) -> bytes:
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0),
    }
    if reasoning is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": finish,
                    "index": 0,
                    "logprobs": None,
                    "message": {
                        "content": content,
                        "refusal": None,
                        "role": "assistant",
                    },
                }
            ],
            "created": 1,
            "id": "chatcmpl-synthetic",
            "model": model,
            "object": "chat.completion",
            "usage": usage,
        }
    ).encode()


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class RecordingTransport:
    """Record requests; the handler decides the outcome."""

    def __init__(self, handler):  # type: ignore[no-untyped-def]
        self.calls: list[urllib.request.Request] = []
        self.timeouts: list[float] = []
        self._handler = handler

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.calls.append(request)
        self.timeouts.append(timeout)
        return self._handler(request)


def _client(
    transport: RecordingTransport,
    *,
    private_terms: tuple[str, ...] = (),
    available: bool = True,
    resend_pause_s: float = 0.0,
) -> MetaClient:
    return MetaClient(
        api_key=FAKE_KEY,
        private_terms=private_terms,
        private_terms_available=available,
        transport=transport,
        resend_pause_s=resend_pause_s,
    )


def _request(prompt: str = "synthetic prompt") -> WonderRequest:
    return WonderRequest(
        prompt=prompt,
        model="muse-wonder-1.0",
        effort="high",
        response_schema=build_response_schema(
            commitment_ids=["cm-builder-parser"],
            fact_ids=[],
            snapshot_metric_ids=[],
            delta_metric_ids=[],
            has_facts=False,
            has_metrics=False,
            has_parent=False,
        ),
    )


def _propose_with_client(case: Case, transport: RecordingTransport) -> Any:
    from datetime import datetime

    from framework.proposal.core import ProposalResult

    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    client = MetaClient(
        api_key=FAKE_KEY,
        private_terms=case.private_terms,
        private_terms_available=case.private_terms_available,
        transport=transport,
    )
    result: ProposalResult = propose(
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
        policy=case.policy,
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    return result


def _canary_case(**overrides: Any) -> Case:
    base = CASES_BY_NAME["P1"].to_dict()
    base.update(overrides)
    return Case.from_dict({**base, "name": "canary", "script": []})


def test_request_body_shape_exact() -> None:
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope("{}")))
    client = _client(transport)
    request = _request("hello")
    response = client.complete(request)
    assert response.text == "{}"
    assert response.finish_reason == "stop"
    assert response.model_reported == "muse-wonder-1.0"
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 13
    assert response.reasoning_tokens is None
    assert response.latency_ms >= 0
    assert len(transport.calls) == 1
    sent = transport.calls[0]
    assert sent.full_url == "https://api.meta.ai/v1/chat/completions"
    assert sent.get_header("Authorization") == f"Bearer {FAKE_KEY}"
    raw_data = sent.data
    assert isinstance(raw_data, bytes)
    body = json.loads(raw_data.decode())
    assert body["model"] == "muse-wonder-1.0"
    assert body["reasoning_effort"] == "high"
    assert body["max_tokens"] == 32768
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "proposal_draft",
            "schema": request.response_schema,
        },
    }
    assert "temperature" not in body
    assert "strict" not in body
    assert transport.timeouts == [300]


def test_client_has_no_model_or_literals_argument() -> None:
    params = inspect.signature(MetaClient.__init__).parameters
    assert "model" not in params
    assert "forbidden_raw_literals" not in params


def test_reported_model_sanitised_and_unreported() -> None:
    transport = RecordingTransport(
        lambda req: _FakeResponse(_envelope("{}", model="a/b/muse-wonder-1.0"))
    )
    assert _client(transport).complete(_request()).model_reported == ("muse-wonder-1.0")
    transport = RecordingTransport(
        lambda req: _FakeResponse(_envelope("{}", model=None))
    )
    assert _client(transport).complete(_request()).model_reported == "unreported"


def test_reasoning_tokens_parsed_when_present() -> None:
    transport = RecordingTransport(
        lambda req: _FakeResponse(_envelope("{}", reasoning=409))
    )
    assert _client(transport).complete(_request()).reasoning_tokens == 409


def test_failure_mapping_to_closed_reasons() -> None:
    def _raises(exc: Exception) -> RecordingTransport:
        def _handler(request: urllib.request.Request) -> Any:
            raise exc

        return RecordingTransport(_handler)

    cases = [
        (_raises(TimeoutError("slow")), "timeout"),
        (_raises(OSError("down")), "transport error"),
        (
            _raises(
                urllib.error.HTTPError(
                    "https://api.meta.ai/v1/chat/completions",
                    429,
                    "Too Many",
                    Message(),
                    None,
                )
            ),
            "status 429",
        ),
        (
            RecordingTransport(lambda req: _FakeResponse(b"not json")),
            "invalid response",
        ),
        (
            RecordingTransport(lambda req: _FakeResponse(json.dumps({}).encode())),
            "invalid response",
        ),
    ]
    for transport, reason in cases:
        with pytest.raises(MetaUnavailableError) as excinfo:
            _client(transport).complete(_request())
        assert str(excinfo.value) == reason, reason


def _drop_script(*outcomes: object) -> RecordingTransport:
    state = {"n": 0}

    def _handler(request: urllib.request.Request) -> Any:
        outcome = outcomes[min(state["n"], len(outcomes) - 1)]
        state["n"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, bytes)
        return _FakeResponse(outcome)

    return RecordingTransport(_handler)


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.meta.ai/v1/chat/completions",
        status,
        "Synthetic",
        Message(),
        None,
    )


@pytest.mark.parametrize(
    "drop",
    [
        http.client.RemoteDisconnected("closed"),
        ConnectionResetError("reset"),
        ConnectionAbortedError("aborted"),
        BrokenPipeError("pipe"),
    ],
)
def test_dropped_connection_resent_once_then_success(
    drop: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    import framework.proposal.client as client_module

    scans: list[str] = []
    real_scan = client_module.scan_outbound_text

    def _counting(text: str, **kwargs: Any) -> tuple[str, ...]:
        scans.append(text)
        return real_scan(text, **kwargs)

    monkeypatch.setattr(client_module, "scan_outbound_text", _counting)
    transport = _drop_script(drop, _envelope("{}"))
    response = _client(transport).complete(_request("hello"))
    assert response.text == "{}"
    assert len(transport.calls) == 2
    assert transport.calls[0].data == transport.calls[1].data
    assert transport.calls[0].get_header("Authorization") == transport.calls[
        1
    ].get_header("Authorization")
    assert scans == ["hello"]


@pytest.mark.parametrize(
    "drop",
    [
        http.client.RemoteDisconnected("closed"),
        ConnectionResetError("reset"),
        ConnectionAbortedError("aborted"),
        BrokenPipeError("pipe"),
    ],
)
def test_dropped_twice_gives_transport_error_after_two_calls(drop: Exception) -> None:
    transport = _drop_script(drop, drop)
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == "transport error"
    assert FAKE_KEY not in str(excinfo.value)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("status", [429, 500])
def test_no_resend_on_http_status(status: int) -> None:
    transport = _drop_script(_http_error(status))
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == f"status {status}"
    assert len(transport.calls) == 1


def test_no_resend_on_timeout() -> None:
    transport = _drop_script(TimeoutError("slow"))
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == "timeout"
    assert len(transport.calls) == 1


def test_url_error_wrapping_drop_resent_once_then_success() -> None:
    transport = _drop_script(
        urllib.error.URLError(ConnectionResetError("reset")), _envelope("{}")
    )
    response = _client(transport).complete(_request("hello"))
    assert response.text == "{}"
    assert len(transport.calls) == 2


def test_url_error_wrapping_drop_twice_gives_transport_error() -> None:
    transport = _drop_script(
        urllib.error.URLError(ConnectionResetError("reset")),
        urllib.error.URLError(ConnectionResetError("reset")),
    )
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == "transport error"
    assert FAKE_KEY not in str(excinfo.value)
    assert len(transport.calls) == 2


def test_url_error_wrapping_timeout_is_timeout_without_resend() -> None:
    transport = _drop_script(urllib.error.URLError(TimeoutError("slow")))
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == "timeout"
    assert FAKE_KEY not in str(excinfo.value)
    assert len(transport.calls) == 1


def test_url_error_wrapping_other_reason_is_transport_error() -> None:
    transport = _drop_script(urllib.error.URLError("no route"))
    with pytest.raises(MetaUnavailableError) as excinfo:
        _client(transport).complete(_request())
    assert str(excinfo.value) == "transport error"
    assert FAKE_KEY not in str(excinfo.value)
    assert len(transport.calls) == 1


def test_null_content_is_unparseable_not_unavailable() -> None:
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope(None)))
    response = _client(transport).complete(_request())
    assert response.text == ""


def test_contributor_refused_before_transport() -> None:
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope("{}")))
    client = _client(transport)
    request = WonderRequest(
        prompt="x",
        model="muse-wonder-1.0-contributor",
        effort="high",
        response_schema={},
    )
    with pytest.raises(ContributorModelRefused):
        client.complete(request)
    assert transport.calls == []
    with pytest.raises(ContributorModelRefused):
        refuse_contributor_model("MUSE-WONDER-1.0-Contributor")


def test_unknown_effort_rejected() -> None:
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope("{}")))
    with pytest.raises(ValueError):
        _client(transport).complete(
            WonderRequest(
                prompt="x",
                model="muse-wonder-1.0",
                effort="ultra",
                response_schema={},
            )
        )
    assert transport.calls == []


def test_no_fake_key_in_any_exception_or_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(request: urllib.request.Request) -> Any:
        raise OSError("synthetic transport failure")

    transports = [
        RecordingTransport(_boom),
        RecordingTransport(lambda req: _FakeResponse(b"broken")),
        RecordingTransport(lambda req: _FakeResponse(_envelope("{}"))),
    ]
    with caplog.at_level(logging.DEBUG):
        for transport in transports:
            try:
                _client(transport).complete(_request())
            except MetaUnavailableError as exc:
                for surface in (
                    str(exc),
                    repr(exc),
                    str(exc.__cause__),
                    str(exc.__context__),
                ):
                    assert FAKE_KEY not in surface, surface
        client = _client(transports[2])
        try:
            client.complete(
                WonderRequest(
                    prompt="x",
                    model="muse-wonder-1.0-contributor",
                    effort="high",
                    response_schema={},
                )
            )
        except ContributorModelRefused as exc:
            assert FAKE_KEY not in str(exc)
        try:
            client.complete(_request())
        except OutboundBlocked:
            pass
    for record in caplog.records:
        assert FAKE_KEY not in record.getMessage()


def test_load_meta_config_names_variable_only() -> None:
    with pytest.raises(MetaConfigError) as excinfo:
        load_meta_config({})
    assert str(excinfo.value) == "META_API_KEY"
    assert load_meta_config({"META_API_KEY": "k"}).api_key == "k"


def _good_transport() -> RecordingTransport:
    return RecordingTransport(lambda req: _FakeResponse(_envelope(GOOD_DRAFT)))


def test_canary_fact_statement_blocks_send() -> None:
    from evals.proposal_cases import BASE_FACTS

    lit = BASE_FACTS[0].model_copy(
        update={"statement": "Synthetic note on quixotic-zebra-742 progress"}
    )
    case = _canary_case(
        facts=[lit.model_dump(mode="json"), BASE_FACTS[1].model_dump(mode="json")],
        forbidden=["quixotic-zebra-742"],
    )
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope(GOOD_DRAFT)))
    result = _propose_with_client(case, transport)
    assert transport.calls == []
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED",)
    assert len(result.attempts) == 1
    assert result.attempts[0].blocked is True
    assert result.attempts[0].codes == (("L1_RAW_VALUE", "prompt"),)
    assert result.attempts[0].latency_ms == 0
    assert result.attempts[0].raw_text == ""


def test_canary_commitment_title_blocks_send() -> None:
    from evals.proposal_cases import BASE_ELIGIBLE

    marked = BASE_ELIGIBLE[0].model_copy(
        update={"title": "Build the quixotic-zebra-742 sketch"}
    )
    case = _canary_case(
        eligible=[marked.model_dump(mode="json")],
        forbidden=["quixotic-zebra-742"],
    )
    transport = _good_transport()
    result = _propose_with_client(case, transport)
    assert transport.calls == []
    assert result.kind == "noop"
    assert result.attempts[0].codes == (("L1_RAW_VALUE", "prompt"),)


def test_canary_policy_block_blocks_send() -> None:
    case = _canary_case(
        policy='{"note": "quixotic-zebra-742"}',
        forbidden=["quixotic-zebra-742"],
    )
    transport = _good_transport()
    result = _propose_with_client(case, transport)
    assert transport.calls == []
    assert result.kind == "noop"
    assert result.attempts[0].codes == (("L1_RAW_VALUE", "prompt"),)


def test_canary_secret_shape_email_and_terms_block_send() -> None:
    from evals.proposal_cases import BASE_FACTS

    cases_and_codes = [
        (
            _canary_case(
                facts=[
                    BASE_FACTS[0]
                    .model_copy(
                        update={
                            "statement": "Synthetic note sk-abcdefghijklmnopqrstuvwx"
                        }
                    )
                    .model_dump(mode="json"),
                    BASE_FACTS[1].model_dump(mode="json"),
                ]
            ),
            "L1_SECRET",
        ),
        (
            _canary_case(
                facts=[
                    BASE_FACTS[0]
                    .model_copy(
                        update={
                            "statement": "Synthetic note to someone@example.com today"
                        }
                    )
                    .model_dump(mode="json"),
                    BASE_FACTS[1].model_dump(mode="json"),
                ]
            ),
            "L1_PII",
        ),
        (
            _canary_case(
                facts=[
                    BASE_FACTS[0]
                    .model_copy(
                        update={"statement": "Synthetic note on harbor-light today"}
                    )
                    .model_dump(mode="json"),
                    BASE_FACTS[1].model_dump(mode="json"),
                ],
                private_terms=["harbor-light"],
            ),
            "L1_PRIVATE_TERM",
        ),
    ]
    for case, code in cases_and_codes:
        transport = _good_transport()
        result = _propose_with_client(case, transport)
        assert transport.calls == [], code
        assert result.kind == "noop", code
        assert result.attempts[0].codes == ((code, "prompt"),), code


def test_canary_terms_unavailable_blocks_send() -> None:
    case = _canary_case(private_terms_available=False)
    transport = _good_transport()
    result = _propose_with_client(case, transport)
    assert transport.calls == []
    assert result.kind == "noop"
    assert result.attempts[0].codes == (("L1_PRIVATE_TERMS_UNAVAILABLE", "prompt"),)


def test_context_literal_blocks_send_with_zero_transport_calls() -> None:
    case = _canary_case(forbidden=["quixotic-zebra-742"])
    context_literals = ("quixotic-zebra-742",)
    assert scan_outbound_text(
        "synthetic quixotic-zebra-742 text",
        private_terms=(),
        private_terms_available=True,
        forbidden_raw_literals=context_literals,
    ) == ("L1_RAW_VALUE",)
    transport = _good_transport()
    client = _client(transport)
    request = WonderRequest(
        prompt="synthetic quixotic-zebra-742 text",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={},
        forbidden_raw_literals=context_literals,
    )
    with pytest.raises(OutboundBlocked):
        client.complete(request)
    assert transport.calls == []
    assert case.forbidden == context_literals


def test_retry_send_is_scanned_with_its_own_literals() -> None:
    transport = RecordingTransport(lambda req: _FakeResponse(_envelope(GOOD_DRAFT)))
    client = _client(transport)
    first = WonderRequest(
        prompt="clean synthetic prompt",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={},
        forbidden_raw_literals=(),
    )
    client.complete(first)
    assert len(transport.calls) == 1
    second = WonderRequest(
        prompt="clean synthetic prompt plus quixotic-zebra-742 feedback",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={},
        forbidden_raw_literals=("quixotic-zebra-742",),
    )
    with pytest.raises(OutboundBlocked) as excinfo:
        client.complete(second)
    assert excinfo.value.codes == ("L1_RAW_VALUE",)
    assert len(transport.calls) == 1


def test_truncated_first_attempt_retries_then_falls_back() -> None:
    from evals.proposal_cases import build_context

    bodies = [_envelope("truncated garbage {{{", finish="length"), _envelope("nope")]
    transport = RecordingTransport(lambda req: _FakeResponse(bodies.pop(0)))
    case = CASES_BY_NAME["P1"]
    context = build_context(case)
    from datetime import datetime

    slot = datetime.fromisoformat(case.slot_iso)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=_client(transport),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert result.kind == "fallback"
    assert result.attempts[0].codes == (("DRAFT_TRUNCATED", "draft"),)
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_UNPARSEABLE",)


def _repo_python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if ".git" not in path.parts and "pre-commit-home" not in path.parts
    ]


def test_meta_host_only_in_client() -> None:
    hits = [
        path
        for path in _repo_python_files(REPO_ROOT / "framework")
        if "api.meta.ai" in path.read_text(encoding="utf-8")
    ]
    assert hits == [PROPOSAL_DIR / "client.py"], hits


def test_network_tokens_only_in_proposal_client() -> None:
    for token in (
        "urlopen",
        "build_opener",
        "http.client",
        "import socket",
        "import requests",
        "import httpx",
        "import urllib",
    ):
        hits = [
            path
            for path in _repo_python_files(PROPOSAL_DIR)
            if token in path.read_text(encoding="utf-8")
        ]
        assert set(hits) <= {PROPOSAL_DIR / "client.py"}, (token, hits)
    assert "build_opener" in (PROPOSAL_DIR / "client.py").read_text(encoding="utf-8")


def test_subprocess_only_in_muse_client() -> None:
    hits = [
        path
        for path in _repo_python_files(PROPOSAL_DIR)
        if "subprocess" in path.read_text(encoding="utf-8")
    ]
    assert hits == [PROPOSAL_DIR / "muse_client.py"], hits


def test_pure_modules_hold_no_side_channels() -> None:
    for name in ("core.py", "prompt.py", "assembly.py", "hour.py", "schemas.py"):
        text = (PROPOSAL_DIR / name).read_text(encoding="utf-8")
        for token in (
            "os.environ",
            "getenv",
            "time.",
            "datetime.now",
            "urllib",
            "muse-",
        ):
            assert token not in text, (name, token)
