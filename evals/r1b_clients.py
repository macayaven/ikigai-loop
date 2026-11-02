"""Ticket 16b: arm clients (D5, D13, D17).

``SwappingWonderClient`` swaps the prompt and the schema independently at
the client boundary. ``LocalWonderClient`` adapts Ticket 9's endpoint
client. ``ReplayWonderClient`` replays one stored draft for re-gate mode.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from framework.glimmer.facts import LLMUnavailableError
from framework.glimmer.llm import (
    LLMConfig,
    OpenAICompatibleClient,
    sanitise_model_id,
)
from framework.proposal.client import refuse_contributor_model
from framework.proposal.core import (
    MetaUnavailableError,
    WonderClient,
    WonderRequest,
    WonderResponse,
)

RETRY_MARKER = "\n\nPREVIOUS ATTEMPT FAILED\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SwappingWonderClient:
    """Wrap a client, replacing prompt and schema independently per arm."""

    def __init__(
        self,
        wrapped: WonderClient,
        *,
        prompt_override: str | None,
        schema_override: dict[str, Any] | None,
    ) -> None:
        self._wrapped = wrapped
        self._prompt_override = prompt_override
        self._schema_override = schema_override
        self.sent_prompts: list[str] = []
        self.sent_schemas: list[dict[str, Any]] = []
        self.sent_hashes: list[str] = []

    @property
    def transport(self) -> str:
        return self._wrapped.transport

    @property
    def transport_version(self) -> str | None:
        return self._wrapped.transport_version

    @property
    def harness_rules_file(self) -> bool | None:
        return self._wrapped.harness_rules_file

    def _send_prompt(self, outbound: str) -> str:
        if self._prompt_override is None:
            return outbound
        index = outbound.rfind(RETRY_MARKER)
        if index < 0:
            return self._prompt_override
        return self._prompt_override + outbound[index:]

    def complete(self, request: WonderRequest) -> WonderResponse:
        prompt = self._send_prompt(request.prompt)
        schema = (
            self._schema_override
            if self._schema_override is not None
            else request.response_schema
        )
        self.sent_prompts.append(prompt)
        self.sent_schemas.append(schema)
        self.sent_hashes.append(_sha256(prompt))
        return self._wrapped.complete(
            WonderRequest(
                prompt=prompt,
                model=request.model,
                effort=request.effort,
                response_schema=schema,
                schema_name=request.schema_name,
                forbidden_raw_literals=request.forbidden_raw_literals,
            )
        )


class LocalWonderClient:
    """Adapt Ticket 9's endpoint client to the ``WonderClient`` protocol."""

    transport = "local"
    transport_version: str | None = None
    harness_rules_file: bool | None = None

    def __init__(self, llm_config: LLMConfig) -> None:
        self._config = llm_config

    def complete(self, request: WonderRequest) -> WonderResponse:
        refuse_contributor_model(request.model)
        client = OpenAICompatibleClient(
            base_url=self._config.base_url,
            model=self._config.model,
            api_key=self._config.api_key,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.response_schema,
                },
            },
        )
        try:
            response = client.complete(request.prompt)
        except LLMUnavailableError as exc:
            raise MetaUnavailableError(
                str(exc) or "unknown", latency_ms=exc.latency_ms
            ) from None
        return WonderResponse(
            text=response.text,
            model_reported=sanitise_model_id(response.model_id),
            latency_ms=response.latency_ms,
            finish_reason=response.finish_reason,
            prompt_tokens=None,
            completion_tokens=response.completion_tokens,
            reasoning_tokens=None,
        )


class ReplayWonderClient:
    """Return one stored draft once, then report unavailable (re-gate)."""

    transport = "replay"
    transport_version: str | None = None
    harness_rules_file: bool | None = None

    def __init__(self, raw_text: str) -> None:
        self._raw_text = raw_text
        self.calls = 0

    def complete(self, request: WonderRequest) -> WonderResponse:
        self.calls += 1
        if self.calls > 1:
            raise MetaUnavailableError("replay exhausted", latency_ms=0)
        return WonderResponse(
            text=self._raw_text,
            model_reported="replay",
            latency_ms=0,
            finish_reason="stop",
            prompt_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
        )
