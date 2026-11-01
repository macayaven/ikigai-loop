"""Ticket 9: ``run_cycle`` seam (load, extract, record)."""

from __future__ import annotations

from datetime import datetime

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    PrivateTerms,
    ProfileLimits,
)
from framework.briefing.schemas import Briefing, Commitment
from framework.glimmer.checks import private_free_text_values
from framework.glimmer.facts import ALLOWED_TYPES, FactResult, LLMClient, extract_facts
from framework.glimmer.metrics import WINDOW, fixed_offset
from framework.proposal.core import ModelParams, ProposalResult, WonderClient, propose
from framework.proposal.hour import (
    allowed_windows,
    busy_query_span,
    cycle_window,
    future_busy_intervals,
    pick_hour,
)
from framework.schemas.core import Fact, FactWindow
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.store.store import EventStore


def run_cycle(
    as_of: datetime,
    subject_id: str,
    store: EventStore,
    fact_store: FactStore,
    llm: LLMClient,
    *,
    personal_pass: bool = True,
    feed_pass: bool = True,
) -> tuple[FactResult, int]:
    """Load the window, extract facts, record the cycle, return ``(result, run)``."""
    as_of = fixed_offset(as_of)
    events = store.events_between(
        subject_id, as_of - WINDOW, as_of, types=ALLOWED_TYPES
    )
    result = extract_facts(
        as_of, subject_id, events, llm, personal_pass=personal_pass, feed_pass=feed_pass
    )
    return result, fact_store.record_cycle(result)


class UnknownCycleError(Exception):
    """A named cycle id is not stored; the message names no id value."""


_BUSY_TYPES = (
    "calendar.event.created",
    "calendar.event.updated",
    "calendar.event.cancelled",
)


def forbidden_literals_for(
    store: EventStore, subject_id: str, as_of: datetime
) -> tuple[str, ...]:
    """Forbidden raw literals over all cycle-window rows collected in time."""
    start, end = cycle_window(as_of)
    events = store.events_between(subject_id, start, end)
    rows = [event for event in events if event.collected_at <= as_of]
    return private_free_text_values(rows)


def _rebuild_facts(fact_store: FactStore, cycle_id: str, run: int) -> list[Fact]:
    facts: list[Fact] = []
    for row in fact_store.fetch_facts(cycle_id, run):
        facts.append(
            Fact(
                id=row["fact_id"],
                subject_id=row["subject_id"],
                window=FactWindow(
                    start=datetime.fromisoformat(row["window_start"]),
                    end=datetime.fromisoformat(row["window_end"]),
                ),
                statement=row["statement"],
                evidence=list(row["evidence"]),
                tier=row["tier"],
            )
        )
    return [fact for fact in facts if fact.tier in ("public", "private")]


def run_proposals(
    *,
    as_of: datetime,
    slot: datetime,
    subject_id: str,
    profiles: tuple[str, ...] | list[str],
    store: EventStore,
    fact_store: FactStore,
    proposal_store: ProposalStore,
    client: WonderClient,
    private_terms: PrivateTerms,
    eligible_by_profile: dict[str, tuple[Commitment, ...]],
    limits: ProfileLimits,
    models: ModelParams,
    stale_after_s: float,
    cycle_id: str | None = None,
    policy_by_profile: dict[str, str] | None = None,
    parents: dict[str, tuple[Briefing, MetricSnapshot]] | None = None,
) -> tuple[ProposalResult, ...]:
    """Resolve the cycle, pick one hour, propose per profile, record all."""
    as_of = fixed_offset(as_of)
    if cycle_id is not None:
        runs = fact_store.runs(cycle_id)
        if not runs:
            raise UnknownCycleError("unknown cycle")
        cycle = fact_store.fetch_cycle(cycle_id, max(runs))
        if cycle.get("subject_id") != subject_id:
            raise UnknownCycleError("unknown cycle")
        cycle["cycle_id"] = cycle_id
        cycle["run"] = max(runs)
    else:
        cycle = fact_store.fetch_latest_cycle(subject_id, not_after=as_of)
    if cycle is None:
        no_cycle_results: list[ProposalResult] = []
        for profile_id in profiles:
            no_cycle_results.append(
                ProposalResult(
                    kind="noop",
                    profile_id=profile_id,
                    subject_id=subject_id,
                    cycle_id="no-cycle",
                    run=0,
                    slot=slot,
                    hour=None,
                    briefing=None,
                    fallback=None,
                    reason_codes=("NO_CYCLE",),
                    attempts=(),
                    cycle_age_s=0.0,
                    prompt_hash="",
                )
            )
        for no_cycle_result in no_cycle_results:
            proposal_store.record(no_cycle_result, snapshot={})
        return tuple(no_cycle_results)
    facts = _rebuild_facts(fact_store, cycle["cycle_id"], cycle["run"])
    snapshot = MetricSnapshot(values=dict(cycle["snapshot"]))
    cycle_as_of = datetime.fromisoformat(cycle["as_of"])
    literals = forbidden_literals_for(store, subject_id, as_of)
    busy_start, busy_end = busy_query_span(as_of)
    busy_events = store.events_between(
        subject_id, busy_start, busy_end, types=_BUSY_TYPES
    )
    busy = future_busy_intervals(busy_events, as_of=as_of, slot=slot)
    hour = pick_hour(slot, busy, limits)
    free = allowed_windows(slot, limits)
    results: list[ProposalResult] = []
    for profile_id in profiles:
        eligible = eligible_by_profile.get(profile_id, ())
        if parents is not None and profile_id in parents:
            parent_briefing, parent_metrics = parents[profile_id]
        else:
            found = proposal_store.latest_proposal(
                subject_id, profile_id, before_slot=slot
            )
            if found is None:
                parent_briefing, parent_metrics = None, None
            else:
                parent_briefing, parent_metrics, _ = found
        context = GateContext(
            facts={fact.id: fact for fact in facts},
            metrics=snapshot,
            parent_briefing=parent_briefing,
            parent_metrics=parent_metrics,
            free_intervals=free,
            busy_intervals=busy,
            limits=limits,
            private_terms=private_terms.terms,
            private_terms_available=private_terms.available,
            forbidden_raw_literals=literals,
            commitments=eligible,
            commitments_available=True,
        )
        offered = proposal_store.last_offered_by_commitment(subject_id, profile_id)
        policy = policy_by_profile.get(profile_id, "") if policy_by_profile else ""
        result = propose(
            profile_id=profile_id,
            subject_id=subject_id,
            slot=slot,
            as_of=as_of,
            cycle_id=cycle["cycle_id"],
            run=cycle["run"],
            hour=hour,
            eligible=eligible,
            context=context,
            client=client,
            models=models,
            policy=policy,
            stale_after_s=stale_after_s,
            cycle_as_of=cycle_as_of,
            offered=offered,
        )
        proposal_store.record(result, snapshot=dict(snapshot.values))
        results.append(result)
    return tuple(results)
