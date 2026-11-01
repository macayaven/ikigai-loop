"""Ticket 11: assemble a full briefing from a narrow draft.

Pure: every id, value, and window comes from the arguments. Unknown ids
become placeholder values so the gate, not assembly, reports them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from framework.briefing.context import TimeInterval
from framework.briefing.schemas import (
    Action,
    Briefing,
    Claim,
    Commitment,
    MetricRef,
    Section,
)
from framework.proposal.schemas import ClaimDraft, ProposalDraft

_SECTIONS = ("overall_state", "since_last", "working", "not_working")


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _claim(
    draft: ClaimDraft,
    section: str,
    index: int,
    values: Mapping[str, float],
) -> Claim:
    refs = [
        MetricRef(metric_id=metric_id, value=values.get(metric_id, 0.0))
        for metric_id in _dedupe(draft.metric_refs)
    ]
    return Claim(
        id=f"c-{section}-{index}",
        text=draft.text,
        fact_ids=_dedupe(draft.fact_ids),
        metric_refs=refs,
    )


def assemble_briefing(
    draft: ProposalDraft,
    *,
    profile_id: str,
    subject_id: str,
    slot: datetime,
    parent: Briefing | None,
    commitments_by_id: Mapping[str, Commitment],
    snapshot: Mapping[str, float],
    parent_snapshot: Mapping[str, float] | None,
    deltas: Mapping[str, float],
    hour: TimeInterval,
) -> Briefing:
    """Fill every briefing field the draft does not carry."""
    _ = parent_snapshot
    has_parent = parent is not None
    digest = hashlib.sha256(draft.commitment_id.encode()).hexdigest()[:8]
    stamp = slot.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    sections: list[Section] = []
    for section in _SECTIONS:
        if section == "since_last" and not has_parent:
            continue
        drafts = getattr(draft, section)
        claims = [
            _claim(
                claim_draft,
                section,
                index,
                deltas if section == "since_last" else snapshot,
            )
            for index, claim_draft in enumerate(drafts, start=1)
        ]
        sections.append(Section(type=section, claims=claims))  # type: ignore[arg-type]
    commitment = commitments_by_id.get(draft.commitment_id)
    if commitment is None:
        kind = "plan"
        text = "unknown commitment"
        dimension = "limit"
    else:
        kind = commitment.kind
        text = commitment.title
        dimension = commitment.dimension
    sections.append(
        Section(
            type="actions",
            claims=[],
            actions=[
                Action(
                    id="act-1",
                    commitment_id=draft.commitment_id,
                    kind=kind,  # type: ignore[arg-type]
                    text=text,
                    dimension=dimension,  # type: ignore[arg-type]
                    proposed_start=hour.start,
                    proposed_end=hour.end,
                )
            ],
        )
    )
    return Briefing(
        id=f"brf-{profile_id}-{stamp}-{digest}",
        profile_id=profile_id,
        subject_id=subject_id,
        slot=slot,
        parent_briefing_id=parent.id if parent is not None else None,
        sections=sections,
    )
