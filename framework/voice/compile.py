"""Ticket 14: compile a transcript into one typed operation.

The transcript is scanned before anything travels: a real hit returns
``blocked`` with zero client calls, while unavailable private terms return
the distinct transient kind ``unavailable`` with the code kept. Otherwise
the frozen prompt and the per-call schema go through the guarded client
the caller hands in — this module never assembles a command line. A full
prompt hit inside the client maps to ``blocked``, a transport failure to
``unavailable``, and a reply that does not parse to ``unparseable``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from framework.briefing.gate import scan_outbound_text
from framework.proposal.core import (
    MetaUnavailableError,
    OutboundBlocked,
    WonderClient,
    WonderRequest,
)
from framework.voice.prompt import (
    PromptCommitment,
    PromptOffer,
    build_compile_prompt,
)
from framework.voice.schemas import (
    CompiledCorrection,
    UnparseableCorrection,
    build_correction_schema,
    parse_compiled,
)

CompileKind = Literal["compiled", "blocked", "unavailable", "unparseable"]

_PRIVATE_TERMS_UNAVAILABLE = "L1_PRIVATE_TERMS_UNAVAILABLE"


@dataclass(frozen=True)
class CompileOutcome:
    """One compile attempt: the closed kind, the parsed reply, step codes."""

    kind: CompileKind
    correction: CompiledCorrection | None
    codes: tuple[str, ...]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0


def compile_correction(
    *,
    client: WonderClient,
    transcript: str,
    commitments: Sequence[PromptCommitment],
    offers: Sequence[PromptOffer],
    statements: Sequence[str],
    now_local: datetime,
    model: str,
    effort: str,
    private_terms: tuple[str, ...],
    private_terms_available: bool,
    forbidden_raw_literals: tuple[str, ...],
) -> CompileOutcome:
    """Scan first, then compile through ``client``; never raises on model output."""
    scan_codes = scan_outbound_text(
        transcript,
        private_terms=private_terms,
        private_terms_available=private_terms_available,
        forbidden_raw_literals=forbidden_raw_literals,
    )
    if scan_codes:
        codes = tuple(scan_codes)
        if _PRIVATE_TERMS_UNAVAILABLE in codes:
            return CompileOutcome(kind="unavailable", correction=None, codes=codes)
        return CompileOutcome(kind="blocked", correction=None, codes=codes)
    prompt = build_compile_prompt(
        transcript=transcript,
        commitments=commitments,
        offers=offers,
        statements=statements,
        now_local=now_local,
    )
    request = WonderRequest(
        prompt=prompt,
        model=model,
        effort=effort,
        response_schema=build_correction_schema(
            [commitment.id for commitment in commitments]
        ),
        schema_name="voice_correction",
        forbidden_raw_literals=tuple(forbidden_raw_literals),
    )
    try:
        response = client.complete(request)
    except OutboundBlocked as exc:
        return CompileOutcome(kind="blocked", correction=None, codes=tuple(exc.codes))
    except MetaUnavailableError as exc:
        return CompileOutcome(kind="unavailable", correction=None, codes=(str(exc),))
    parsed = parse_compiled(response.text)
    if isinstance(parsed, UnparseableCorrection):
        return CompileOutcome(
            kind="unparseable",
            correction=None,
            codes=(),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
        )
    return CompileOutcome(
        kind="compiled",
        correction=parsed,
        codes=(),
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        latency_ms=response.latency_ms,
    )
