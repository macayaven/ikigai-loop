"""Ticket 9c: closed calendar-label set and its in-memory tag overlay.

The eight labels are defined once in ``framework.schemas.events`` and only
re-exported here. Labels reach the metrics as an in-memory overlay on
``tags``; the store is never rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from framework.collectors.common import event_id
from framework.schemas.events import LABELS, CalendarLabelData, Event, Label

__all__ = [
    "INTERNAL_ONLY_LABELS",
    "LABELS",
    "CalendarLabelData",
    "Label",
    "LabelView",
    "apply_labels",
    "effective_label",
    "strip_internal_tags",
]

INTERNAL_ONLY_LABELS: frozenset[str] = frozenset({"iki-care"})

_CALENDAR_PREFIX = "calendar.event."
_CANCELLED_SUFFIX = "#cancelled"


def _tags_of(event: Event) -> list[str]:
    tags: Any = getattr(event.data, "tags", None)
    if not isinstance(tags, list):
        return []
    return cast(list[str], tags)


def _with_tags(event: Event, tags: list[str]) -> Event:
    return event.model_copy(
        update={"data": event.data.model_copy(update={"tags": tags})}
    )


def _label_target_id(event: Event) -> str | None:
    """Event id whose label row applies, or None for non-calendar rows."""
    if not event.type.startswith(_CALENDAR_PREFIX):
        return None
    if event.type == "calendar.event.cancelled":
        return event_id(event.source, event.source_id.removesuffix(_CANCELLED_SUFFIX))
    return event.id


@dataclass(frozen=True)
class LabelView:
    label: str  # first hand tag, the model label, or "iki-unknown"
    source: Literal["hand", "local_model", "none"]
    model_id: str | None  # None unless source == "local_model"


def effective_label(event: Event, label_row: Event | None) -> LabelView:
    """Read the provenance of one calendar row's label."""
    tags = _tags_of(event)
    if tags:
        return LabelView(label=tags[0], source="hand", model_id=None)
    if label_row is not None:
        data = label_row.data
        assert isinstance(data, CalendarLabelData)
        return LabelView(label=data.label, source="local_model", model_id=data.model_id)
    return LabelView(label="iki-unknown", source="none", model_id=None)


def apply_labels(events: Sequence[Event], label_rows: Sequence[Event]) -> list[Event]:
    """Overlay model labels onto untagged calendar rows, in memory only."""
    by_target: dict[str, Event] = {}
    for row in label_rows:
        data = row.data
        if not isinstance(data, CalendarLabelData):
            continue
        current = by_target.get(data.target_event_id)
        if current is None or row.collected_at > current.collected_at:
            by_target[data.target_event_id] = row
    out: list[Event] = []
    for event in list(events):
        target_id = _label_target_id(event)
        if target_id is None or _tags_of(event):
            out.append(event)
            continue
        row = by_target.get(target_id)
        if row is None:
            out.append(event)
            continue
        data = row.data
        assert isinstance(data, CalendarLabelData)
        if data.label == "iki-unknown" or data.label in INTERNAL_ONLY_LABELS:
            out.append(event)
            continue
        out.append(_with_tags(event, [data.label]))
    return out


def strip_internal_tags(events: Sequence[Event]) -> list[Event]:
    """Drop internal-only tags from calendar rows; other events unchanged."""
    lowered = {tag.casefold() for tag in INTERNAL_ONLY_LABELS}
    out: list[Event] = []
    for event in list(events):
        if not event.type.startswith(_CALENDAR_PREFIX):
            out.append(event)
            continue
        kept = [tag for tag in _tags_of(event) if tag.casefold() not in lowered]
        if len(kept) == len(_tags_of(event)):
            out.append(event)
        else:
            out.append(_with_tags(event, kept))
    return out
