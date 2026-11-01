"""Ticket 10: briefing gate package (schema, context, numbers, gate)."""

from framework.briefing.commitments import (
    LoadedCommitments,
    load_commitments,
)
from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    PrivateTerms,
    ProfileLimits,
    TimeInterval,
    load_private_terms,
)
from framework.briefing.gate import (
    ADVICE_PHRASES,
    ADVICE_WORDS,
    DOWN_WORDS,
    PERIOD_WORDS,
    UP_WORDS,
    GateResult,
    Violation,
    action_targets_repo,
    action_window_codes,
    evaluate_briefing,
    scan_outbound_text,
    slot_window_codes,
    text_check_codes,
)
from framework.briefing.labels import MetricBinding, metric_label_binding
from framework.briefing.numbers import NumberToken, extract_number_tokens
from framework.briefing.schemas import (
    Action,
    ActionKind,
    Briefing,
    Claim,
    Commitment,
    EvidenceKind,
    MetricRef,
    Section,
    SectionType,
)

__all__ = [
    "ADVICE_PHRASES",
    "ADVICE_WORDS",
    "DOWN_WORDS",
    "PERIOD_WORDS",
    "UP_WORDS",
    "Action",
    "ActionKind",
    "Briefing",
    "Claim",
    "Commitment",
    "EvidenceKind",
    "GateContext",
    "GateResult",
    "LoadedCommitments",
    "MetricBinding",
    "MetricRef",
    "MetricSnapshot",
    "NumberToken",
    "PrivateTerms",
    "ProfileLimits",
    "Section",
    "SectionType",
    "TimeInterval",
    "Violation",
    "action_targets_repo",
    "action_window_codes",
    "evaluate_briefing",
    "extract_number_tokens",
    "load_commitments",
    "load_private_terms",
    "metric_label_binding",
    "scan_outbound_text",
    "slot_window_codes",
    "text_check_codes",
]
