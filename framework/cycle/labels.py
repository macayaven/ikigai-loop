"""Ticket 9c: same-process label sweep (poll with sink, append first, label second).

Titles live in one dict in this process and die with it. Events append
before any model call, so a model failure loses labels, never events. Each
answered title persists its label rows title by title, each append in its
own transaction, so a crash loses at most one call.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from framework.collectors.calendar_ics import CalendarIcsCollector
from framework.collectors.common import event_id
from framework.glimmer.facts import LLMClient
from framework.glimmer.label_step import LabelAssignment, LabelStepResult, label_events
from framework.glimmer.metrics import fixed_offset, select_winners
from framework.schemas.events import CalendarLabelData, Event, Label
from framework.store.collector import run_collector
from framework.store.store import ConflictingEvent, EventStore

LABEL_SOURCE = "glimmer-labels"
LABEL_VERSION = "glimmer-labels@0.1.0"


class SinkCollector(Protocol):
    """A calendar collector with an attachable in-memory title sink."""

    name: str
    version: str
    title_sink: dict[str, str] | None

    def poll(self, cursor: Any) -> tuple[list[Event], Any]: ...


CALENDAR_TYPES = frozenset(
    {
        "calendar.event.created",
        "calendar.event.updated",
        "calendar.event.cancelled",
    }
)
STORED_LABEL_TYPES = frozenset({"calendar.label"})


def _label_event(
    target: Event, assignment: LabelAssignment, collected_at: datetime
) -> Event:
    source_id = f"{assignment.event_id}#label"
    data = CalendarLabelData(
        target_event_id=assignment.event_id,
        label=cast(Label, assignment.label),
        label_source="local_model",
        model_id=assignment.model_id,
        valid=assignment.valid,
    )
    return Event(
        id=event_id(LABEL_SOURCE, source_id),
        subject_id=target.subject_id,
        source=LABEL_SOURCE,
        type="calendar.label",
        time=target.time,
        source_id=source_id,
        data=data,
        tier="private",
        collected_at=collected_at,
        collector_version=LABEL_VERSION,
    )


def run_label_sweep(
    store: EventStore,
    subject_id: str,
    collectors: Sequence[str | SinkCollector],
    llm: LLMClient,
    *,
    as_of: datetime,
    budget_s: float = 240,
    monotonic: Callable[[], float] = time.monotonic,
) -> LabelStepResult:
    """Poll each collector, then label the winners within budget."""
    as_of = fixed_offset(as_of)
    start = monotonic()
    window_start = as_of - timedelta(days=2)
    window_end = as_of + timedelta(days=14)
    sinks: list[dict[str, str]] = []
    for item in collectors:
        sink: dict[str, str] = {}
        if isinstance(item, str):
            collector: SinkCollector = CalendarIcsCollector(label=item, title_sink=sink)
        else:
            collector = item
            collector.title_sink = sink
        run_collector(store, collector)
        sinks.append(sink)
    titles: dict[str, str] = {}
    for sink in sinks:
        titles.update(sink)
    winners = select_winners(
        store.events_between(subject_id, window_start, window_end, types=CALENDAR_TYPES)
    )
    label_rows = store.events_between(
        subject_id, window_start, window_end, types=STORED_LABEL_TYPES
    )
    already = {
        row.data.target_event_id
        for row in label_rows
        if isinstance(row.data, CalendarLabelData)
    }
    targets = {event.id: event for event in winners}

    def should_continue() -> bool:
        return monotonic() - start < budget_s

    def on_assignments(batch: Sequence[LabelAssignment]) -> None:
        for assignment in batch:
            row = _label_event(targets[assignment.event_id], assignment, as_of)
            if not store.append_event(row):
                raise ConflictingEvent(row.source, row.source_id, "", "")

    return label_events(
        winners,
        titles,
        llm,
        already_labelled=already,
        should_continue=should_continue,
        on_assignments=on_assignments,
    )
