"""Ticket 14 Step 5: compile through the guarded client (D9, D10).

Fake compile client throughout, plus one real-client refusal arm that never
reaches a runner. No network, no model.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    OutboundBlocked,
    WonderRequest,
    WonderResponse,
)
from framework.proposal.muse_client import MuseExecClient, RunResult
from framework.voice.compile import CompileOutcome, compile_correction
from framework.voice.prompt import (
    PromptCommitment,
    PromptOffer,
    build_compile_prompt,
)
from framework.voice.schemas import CompiledCorrection, build_correction_schema

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 31, 14, 5, tzinfo=MADRID)

COMMITMENTS = (
    PromptCommitment(id="write-up", title="Finish the write-up", side="builder"),
    PromptCommitment(id="evening-rest", title="Evening rest", side="disconnect"),
)
OFFERS = (
    PromptOffer(
        label="A",
        title="Finish the write-up",
        slot=datetime(2026, 10, 31, 15, 7, tzinfo=MADRID),
    ),
)
STATEMENTS = ("Work continued after hours.",)
CLEAN = {
    "private_terms": (),
    "private_terms_available": True,
    "forbidden_raw_literals": (),
}

SKIP_TODAY = json.dumps(
    {
        "operation": "skip",
        "commitment_id": "write-up",
        "until": "today",
        "question": None,
    }
)


class FakeCompileClient:
    """Count complete() calls; script one reply, or one raise."""

    transport = "fake"
    transport_version: str | None = "fake-0"

    def __init__(
        self,
        text: str = SKIP_TODAY,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[WonderRequest] = []
        self.text = text
        self.error = error

    def complete(self, request: WonderRequest) -> WonderResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return WonderResponse(
            text=self.text,
            model_reported="fake",
            latency_ms=11,
            finish_reason="completed",
            prompt_tokens=5,
            completion_tokens=7,
            reasoning_tokens=None,
            cached_tokens=None,
        )


def _compile(
    client: FakeCompileClient, transcript: str, **kwargs: Any
) -> CompileOutcome:
    args: dict[str, Any] = {
        "client": client,
        "transcript": transcript,
        "commitments": COMMITMENTS,
        "offers": OFFERS,
        "statements": STATEMENTS,
        "now_local": NOW,
        "model": "muse-spark-1.3",
        "effort": "minimal",
    }
    args.update(CLEAN)
    args.update(kwargs)
    return compile_correction(**args)  # type: ignore[arg-type]


def test_blocked_scan_sends_nothing() -> None:
    client = FakeCompileClient()
    outcome = _compile(
        client,
        "Don't drop the write-up, I just can't do it today",
        forbidden_raw_literals=("write-up",),
    )
    assert outcome.kind == "blocked"
    assert outcome.correction is None
    assert "L1_RAW_VALUE" in outcome.codes
    assert client.calls == []


def test_private_terms_unavailable_is_unavailable_not_blocked() -> None:
    client = FakeCompileClient()
    outcome = _compile(
        client,
        "Skip the write-up today",
        private_terms_available=False,
    )
    assert outcome.kind == "unavailable"
    assert outcome.correction is None
    assert outcome.codes == ("L1_PRIVATE_TERMS_UNAVAILABLE",)
    assert client.calls == []


def test_happy_path_compiles_and_passes_tokens() -> None:
    client = FakeCompileClient()
    outcome = _compile(client, "Skip the write-up today")
    assert outcome.kind == "compiled"
    assert outcome.correction == CompiledCorrection(
        operation="skip", commitment_id="write-up", until="today", question=None
    )
    assert outcome.codes == ()
    assert outcome.prompt_tokens == 5
    assert outcome.completion_tokens == 7
    assert outcome.latency_ms == 11


def test_request_uses_frozen_builders() -> None:
    client = FakeCompileClient()
    transcript = "Skip the write-up today"
    outcome = _compile(client, transcript)
    assert outcome.kind == "compiled"
    (request,) = client.calls
    assert request.prompt == build_compile_prompt(
        transcript=transcript,
        commitments=COMMITMENTS,
        offers=OFFERS,
        statements=STATEMENTS,
        now_local=NOW,
    )
    assert request.model == "muse-spark-1.3"
    assert request.effort == "minimal"
    assert request.schema_name == "voice_correction"
    assert request.response_schema == build_correction_schema(
        ["write-up", "evening-rest"]
    )
    assert request.forbidden_raw_literals == ()


def test_transcript_confined_to_the_prompt_data_block() -> None:
    client = FakeCompileClient()
    transcript = "Skip the write-up today please zebra-quux"
    outcome = _compile(client, transcript)
    assert outcome.kind == "compiled"
    (request,) = client.calls
    assert request.prompt.count(transcript) == 1
    block = "<<<TRANSCRIPT_DATA\n" + transcript + "\nTRANSCRIPT_DATA>>>"
    assert block in request.prompt


def test_full_prompt_block_maps_to_blocked() -> None:
    client = FakeCompileClient(error=OutboundBlocked(("L1_RAW_VALUE",)))
    outcome = _compile(client, "Skip the write-up today")
    assert outcome.kind == "blocked"
    assert outcome.correction is None
    assert outcome.codes == ("L1_RAW_VALUE",)
    assert len(client.calls) == 1


def test_transport_failure_maps_to_unavailable_with_code_kept() -> None:
    client = FakeCompileClient(error=MetaUnavailableError("timeout", latency_ms=9))
    outcome = _compile(client, "Skip the write-up today")
    assert outcome.kind == "unavailable"
    assert outcome.correction is None
    assert outcome.codes == ("timeout",)
    assert len(client.calls) == 1


def test_unparseable_reply_maps_to_unparseable() -> None:
    client = FakeCompileClient(text="not json at all")
    outcome = _compile(client, "Skip the write-up today")
    assert outcome.kind == "unparseable"
    assert outcome.correction is None
    assert outcome.codes == ()


def test_contributor_id_refused_with_zero_runner_calls() -> None:
    seen: list[list[str]] = []

    def _fake_runner(argv: Any, **kwargs: Any) -> RunResult:
        seen.append(list(argv))
        raise AssertionError("the runner must never run for a contributor id")

    client = MuseExecClient(
        private_terms_available=True,
        runner=_fake_runner,  # type: ignore[arg-type]
    )
    with pytest.raises(ContributorModelRefused):
        compile_correction(
            client=client,
            transcript="Skip the write-up today",
            commitments=COMMITMENTS,
            offers=OFFERS,
            statements=STATEMENTS,
            now_local=NOW,
            model="muse-contributor-spark-1.3",
            effort="minimal",
            **CLEAN,  # type: ignore[arg-type]
        )
    assert seen == []
