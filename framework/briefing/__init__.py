"""Ticket 8: briefing gate package (schema, context, numbers, gate)."""

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    PrivateTerms,
    ProfileLimits,
    TimeInterval,
    load_private_terms,
)
from framework.briefing.gate import GateResult, Violation, evaluate_briefing
from framework.briefing.numbers import NumberToken, extract_number_tokens
from framework.briefing.schemas import (
    Action,
    ActionKind,
    Briefing,
    Claim,
    MetricRef,
    Section,
    SectionType,
)

__all__ = [
    "Action",
    "ActionKind",
    "Briefing",
    "Claim",
    "GateContext",
    "GateResult",
    "MetricRef",
    "MetricSnapshot",
    "NumberToken",
    "PrivateTerms",
    "ProfileLimits",
    "Section",
    "SectionType",
    "TimeInterval",
    "Violation",
    "evaluate_briefing",
    "extract_number_tokens",
    "load_private_terms",
]
