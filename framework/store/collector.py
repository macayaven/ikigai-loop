"""Collector protocol, transactional runner, and fixture collector (ticket 4)."""

from pathlib import Path
from typing import Any, Protocol

from framework.schemas import Event
from framework.store.store import EventStore


class Collector(Protocol):
    """A deterministic source of events.

    ``poll`` receives the opaque cursor stored by the previous successful
    poll (``None`` on the first poll) and returns the new events plus the
    next cursor. Cursors are opaque JSON values owned by the collector;
    the store only persists them.

    Append-only rule: if an upstream item changes, the collector MUST emit
    it under a new ``source_id`` that is unique per change, e.g.
    ``"<upstream_id>@<updated_iso>"``. Reusing ``(source, source_id)`` with
    different compared content (subject, type, time, tier, data) is a
    conflict: ``append_event`` raises ``ConflictingEvent``, while
    ``run_collector`` records it in the ``conflicts`` table, keeps the
    stored event, and continues. The store never updates an event in place.
    """

    name: str
    version: str

    def poll(self, cursor: Any) -> tuple[list[Event], Any]: ...


def run_collector(store: EventStore, collector: Collector) -> tuple[int, int]:
    """Poll once outside any transaction, then apply events and cursor atomically."""
    cursor = store.get_cursor(collector.name)
    events, new_cursor = collector.poll(cursor)
    return store.poll_transaction(collector.name, events, new_cursor)


class FixtureCollector:
    """Read synthetic events from a JSONL file by physical line offset."""

    def __init__(
        self, path: Path, *, name: str = "fixture", version: str = "fixture@0.1.0"
    ) -> None:
        self._path = path
        self.name = name
        self.version = version

    def poll(self, cursor: Any) -> tuple[list[Event], int]:
        """Return events from the stored line offset onward plus the new offset."""
        offset: int = 0 if cursor is None else int(cursor)
        lines = self._path.read_text(encoding="utf-8").splitlines()
        events: list[Event] = []
        for line in lines[offset:]:
            if line.strip() == "":
                continue
            events.append(Event.model_validate_json(line))
        return events, len(lines)
