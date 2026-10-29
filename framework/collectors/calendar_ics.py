"""Calendar collector over a secret iCal URL (ticket 5)."""

import os
import re
import urllib.error
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]

from framework.collectors.common import (
    CollectorError,
    HttpGet,
    as_dict,
    event_id,
    subject_id_from_env,
    urllib_http_get,
)
from framework.schemas import (
    CalendarEventCancelledData,
    CalendarEventCreatedData,
    CalendarEventUpdatedData,
    Event,
)

MADRID = ZoneInfo("Europe/Madrid")
TAG_PATTERN = re.compile(r"iki-[a-z]+")
LABEL_PATTERN = re.compile(r"[a-z]+")


def _as_aware(value: date | datetime) -> datetime | None:
    """Normalise an iCal date/datetime to an aware datetime, or None."""
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
                return value.replace(tzinfo=MADRID)
            return value
        return datetime(value.year, value.month, value.day, tzinfo=MADRID)
    except (ValueError, OverflowError, OSError):
        return None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _decoded(component: icalendar.Event, name: str) -> Any | None:
    try:
        return component.decoded(name, None)
    except (KeyError, ValueError, AttributeError, TypeError):
        return None


class CalendarIcsCollector:
    """Poll one secret iCal feed; titles derive tags, then are dropped."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        label: str = "personal",
    ) -> None:
        if LABEL_PATTERN.fullmatch(label) is None:
            raise ValueError(f"invalid calendar label: {label!r}")
        self._http_get = http_get
        self._now_fn = now_fn
        self.label = label
        self.name = f"calendar-{label}"
        self.version = "calendar@0.1.0"

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        now = self._now_fn()
        env_var = f"ICAL_URL_{self.label.upper()}"
        url = os.environ.get(env_var)
        if not url and self.label == "personal":
            url = os.environ.get("ICAL_URL")
        if not url:
            raise CollectorError(f"{self.name}: {env_var} is not set")
        subject_id = subject_id_from_env()
        try:
            response = self._http_get(url, {})
        except CollectorError:
            raise CollectorError(f"{self.name}: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError(f"{self.name}: network error") from None
        if response.status != 200:
            raise CollectorError(
                f"{self.name}: fetch failed (status {response.status})"
            )
        try:
            cal = icalendar.Calendar.from_ical(response.body)
            window_start = now - timedelta(days=2)
            window_end = now + timedelta(days=14)
            expanded = cast(
                "list[icalendar.Event]",
                recurring_ical_events.of(cal).between(window_start, window_end),
            )
        except (KeyError, ValueError, AttributeError, TypeError):
            raise CollectorError(f"{self.name}: invalid response") from None

        current: dict[str, dict[str, Any]] = {}
        for component in expanded:
            snapshot = self._snapshot_instance(component, window_start, window_end)
            if snapshot is not None:
                current[str(snapshot["key"])] = as_dict(snapshot["data"]) or {}

        prev: dict[str, Any] = {}
        cursor_dict = as_dict(cursor)
        if cursor_dict is not None:
            instances = as_dict(cursor_dict.get("instances"))
            if instances is not None:
                prev = instances

        events: list[Event] = []
        for key, data in current.items():
            previous = as_dict(prev.get(key))
            if previous is None:
                events.append(
                    self._build_event(
                        "calendar.event.created",
                        CalendarEventCreatedData,
                        subject_id,
                        data,
                        now,
                    )
                )
            elif previous.get("source_id") != data["source_id"]:
                events.append(
                    self._build_event(
                        "calendar.event.updated",
                        CalendarEventUpdatedData,
                        subject_id,
                        data,
                        now,
                    )
                )
        for key, stored in prev.items():
            if key in current:
                continue
            stored_dict = as_dict(stored)
            if stored_dict is None:
                continue
            try:
                stored_start = datetime.fromisoformat(str(stored_dict["start"]))
            except (ValueError, KeyError, TypeError):
                continue
            if stored_start < window_start:
                continue
            events.append(self._build_cancelled(subject_id, stored_dict, now))

        events.sort(key=lambda e: (e.time, e.source_id))
        return events, {"instances": current}

    def _snapshot_instance(
        self, component: icalendar.Event, window_start: datetime, window_end: datetime
    ) -> dict[str, Any] | None:
        raw_uid = component.get("UID")
        uid = str(raw_uid) if raw_uid is not None else ""
        if not uid:
            return None
        raw_start = _decoded(component, "DTSTART")
        if raw_start is None or not isinstance(raw_start, (date, datetime)):
            return None
        start = _as_aware(raw_start)
        if start is None:
            return None
        if not (window_start <= start < window_end):
            return None
        raw_end = _decoded(component, "DTEND")
        end: datetime | None = None
        if isinstance(raw_end, (date, datetime)):
            end = _as_aware(raw_end)
        if end is None:
            raw_duration = _decoded(component, "DURATION")
            if isinstance(raw_duration, timedelta):
                try:
                    end = start + raw_duration
                except (OverflowError, ValueError):
                    end = None
        if end is None:
            end = start

        raw_rid = _decoded(component, "RECURRENCE-ID")
        rid_dt = _as_aware(raw_rid) if isinstance(raw_rid, (date, datetime)) else None
        rid = _utc_iso(rid_dt) if rid_dt is not None else _utc_iso(start)
        key = f"{uid}@{rid}"

        raw_modified = _decoded(component, "LAST-MODIFIED")
        modified = (
            _as_aware(raw_modified)
            if isinstance(raw_modified, (date, datetime))
            else None
        )
        if modified is not None:
            last_modified = _utc_iso(modified)
        else:
            raw_seq = _decoded(component, "SEQUENCE")
            if isinstance(raw_seq, (int, str)):
                try:
                    last_modified = f"seq{int(raw_seq)}"
                except ValueError:
                    last_modified = "seq0"
            else:
                last_modified = "seq0"
        source_id = f"{key}@{last_modified}"

        raw_summary = component.get("SUMMARY")
        summary = str(raw_summary) if raw_summary is not None else ""
        tags = list(dict.fromkeys(TAG_PATTERN.findall(summary)))
        is_new = summary.strip().startswith("new:")
        raw_transp = component.get("TRANSP", "OPAQUE")
        busy = str(raw_transp).upper() != "TRANSPARENT"
        return {
            "key": key,
            "data": {
                "source_id": source_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "busy": busy,
                "tags": tags,
                "is_new": is_new,
            },
        }

    def _build_event(
        self,
        event_type: Literal["calendar.event.created", "calendar.event.updated"],
        data_cls: (type[CalendarEventCreatedData] | type[CalendarEventUpdatedData]),
        subject_id: str,
        data: dict[str, Any],
        now: datetime,
    ) -> Event:
        start = datetime.fromisoformat(str(data["start"]))
        end = datetime.fromisoformat(str(data["end"]))
        payload = data_cls(
            start=start,
            end=end,
            busy=bool(data["busy"]),
            category=self.label,
            tags=list(data["tags"]),
            is_new=bool(data["is_new"]),
        )
        source_id = str(data["source_id"])
        return Event(
            id=event_id(self.name, source_id),
            subject_id=subject_id,
            source=self.name,
            type=event_type,
            time=start,
            source_id=source_id,
            data=payload,
            tier="private",
            collected_at=now,
            collector_version=self.version,
        )

    def _build_cancelled(
        self, subject_id: str, stored: dict[str, Any], now: datetime
    ) -> Event:
        start = datetime.fromisoformat(str(stored["start"]))
        end = datetime.fromisoformat(str(stored["end"]))
        payload = CalendarEventCancelledData(
            start=start,
            end=end,
            busy=bool(stored["busy"]),
            category=self.label,
            tags=list(stored["tags"]),
            is_new=bool(stored["is_new"]),
        )
        source_id = str(stored["source_id"]) + "#cancelled"
        return Event(
            id=event_id(self.name, source_id),
            subject_id=subject_id,
            source=self.name,
            type="calendar.event.cancelled",
            time=start,
            source_id=source_id,
            data=payload,
            tier="private",
            collected_at=now,
            collector_version=self.version,
        )
