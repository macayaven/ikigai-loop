"""Ticket 16b: direct LocalWonderClient tests (D13).

No network, no model call: the endpoint client class is replaced with a
recording fake, so every assertion below exercises ``LocalWonderClient``
itself.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from evals.r1b_clients import LocalWonderClient
from framework.glimmer.facts import LLMResponse, LLMUnavailableError
from framework.glimmer.llm import LLMConfig
from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    WonderRequest,
    WonderResponse,
)


class _EndpointProbe:
    """Stand-in for ``OpenAICompatibleClient``; records builds and prompts."""

    built: ClassVar[list[dict[str, Any]]] = []
    prompts: ClassVar[list[str]] = []
    answer: ClassVar[LLMResponse | None] = None
    failure: ClassVar[LLMUnavailableError | None] = None

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        response_format: Any = None,
        **kwargs: Any,
    ) -> None:
        _ = kwargs
        _EndpointProbe.built.append(
            {
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "response_format": response_format,
            }
        )

    def complete(self, prompt: str) -> LLMResponse:
        _EndpointProbe.prompts.append(prompt)
        if _EndpointProbe.failure is not None:
            raise _EndpointProbe.failure
        assert _EndpointProbe.answer is not None
        return _EndpointProbe.answer


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> type[_EndpointProbe]:
    _EndpointProbe.built = []
    _EndpointProbe.prompts = []
    _EndpointProbe.answer = LLMResponse(
        text="{}",
        model_id="m",
        latency_ms=5,
        finish_reason="stop",
        completion_tokens=9,
    )
    _EndpointProbe.failure = None
    monkeypatch.setattr("evals.r1b_clients.OpenAICompatibleClient", _EndpointProbe)
    return _EndpointProbe


def _config() -> LLMConfig:
    return LLMConfig(
        base_url="http://127.0.0.1:1",
        model="muse-glimmer-30b",
        api_key="synthetic",
    )


def _request() -> WonderRequest:
    return WonderRequest(
        prompt="draft the card",
        model="muse-glimmer-30b",
        effort="none",
        response_schema={"type": "object", "properties": {}},
        schema_name="proposal_draft",
    )


def test_contributor_model_refused_before_any_build(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    client = LocalWonderClient(_config())
    request = _request()
    refused = WonderRequest(
        prompt=request.prompt,
        model="muse-wonder-1.0-contributor",
        effort=request.effort,
        response_schema=request.response_schema,
        schema_name=request.schema_name,
    )
    with pytest.raises(ContributorModelRefused):
        client.complete(refused)
    assert _EndpointProbe.built == []


def test_one_endpoint_client_per_request(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    client = LocalWonderClient(_config())
    client.complete(_request())
    client.complete(_request())
    assert len(_EndpointProbe.built) == 2


def test_response_format_carries_schema_name_and_schema(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    client = LocalWonderClient(_config())
    request = _request()
    client.complete(request)
    assert _EndpointProbe.built[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": request.schema_name,
            "schema": request.response_schema,
        },
    }


def test_prompt_reaches_endpoint_unchanged(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    client = LocalWonderClient(_config())
    request = _request()
    client.complete(request)
    assert _EndpointProbe.prompts == [request.prompt]


def test_unavailable_maps_reason_and_latency(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    endpoint.failure = LLMUnavailableError("timeout", latency_ms=42)
    client = LocalWonderClient(_config())
    with pytest.raises(MetaUnavailableError) as excinfo:
        client.complete(_request())
    assert str(excinfo.value) == "timeout"
    assert excinfo.value.latency_ms == 42


def test_token_counts_pass_through_without_invention(
    endpoint: type[_EndpointProbe],
) -> None:
    _ = endpoint
    client = LocalWonderClient(_config())
    response = client.complete(_request())
    assert isinstance(response, WonderResponse)
    assert response.prompt_tokens is None
    assert response.reasoning_tokens is None
    assert response.completion_tokens == 9
