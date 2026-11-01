"""Ticket 11: Wonder proposal step (pure core plus CLI-edge client)."""

from framework.proposal.assembly import assemble_briefing
from framework.proposal.core import (
    AttemptOutcome,
    ContributorModelRefused,
    MetaUnavailableError,
    ModelParams,
    OutboundBlocked,
    ProposalResult,
    WonderClient,
    WonderRequest,
    WonderResponse,
    propose,
)
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
from framework.proposal.hour import (
    allowed_windows,
    fallback_window_codes,
    future_busy_intervals,
    pick_hour,
)
from framework.proposal.prompt import (
    Delta,
    build_prompt,
    compute_deltas,
    display_value,
    fill_once,
    offered_metrics,
)
from framework.proposal.schemas import (
    ClaimDraft,
    FallbackProposal,
    ProposalDraft,
    UnparseableDraft,
    build_response_schema,
    parse_draft,
)

__all__ = [
    "DEFAULT_EFFORT",
    "DEFAULT_MODEL",
    "AttemptOutcome",
    "ClaimDraft",
    "ContributorModelRefused",
    "Delta",
    "FallbackProposal",
    "MetaUnavailableError",
    "ModelParams",
    "OutboundBlocked",
    "ProposalDraft",
    "ProposalResult",
    "UnparseableDraft",
    "WonderClient",
    "WonderRequest",
    "WonderResponse",
    "allowed_windows",
    "assemble_briefing",
    "build_prompt",
    "build_response_schema",
    "compute_deltas",
    "display_value",
    "fallback_window_codes",
    "fill_once",
    "future_busy_intervals",
    "offered_metrics",
    "parse_draft",
    "pick_hour",
    "propose",
]
