"""Ticket 9: ``run_cycle`` seam (load, extract, record)."""

from __future__ import annotations

from datetime import datetime

from framework.glimmer.facts import ALLOWED_TYPES, FactResult, LLMClient, extract_facts
from framework.glimmer.metrics import WINDOW, fixed_offset
from framework.store.fact_store import FactStore
from framework.store.store import EventStore


def run_cycle(
    as_of: datetime,
    subject_id: str,
    store: EventStore,
    fact_store: FactStore,
    llm: LLMClient,
) -> tuple[FactResult, int]:
    """Load the window, extract facts, record the cycle, return ``(result, run)``."""
    as_of = fixed_offset(as_of)
    events = store.events_between(
        subject_id, as_of - WINDOW, as_of, types=ALLOWED_TYPES
    )
    result = extract_facts(as_of, subject_id, events, llm)
    return result, fact_store.record_cycle(result)
