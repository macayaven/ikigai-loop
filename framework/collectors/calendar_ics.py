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
TAG_PATTERN = re.compile(r"(?<![\w-])iki-[a-z]+")
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


def _content_equal(current: dict[str, Any], stored: dict[str, Any]) -> bool:
    """Compare snapshot content as values, never as stored strings.

    `start`/`end` compare as instants so the same moment under a different
    offset is equal; a stored value that will not parse counts as changed
    and never raises.
    """
    try:
        for field in ("start", "end"):
            if datetime.fromisoformat(str(current[field])) != (
                datetime.fromisoformat(str(stored[field]))
            ):
                return False
        if list(current["tags"]) != list(stored["tags"]):
            return False
        for field in ("busy", "is_new", "cancelled"):
            if bool(current[field]) != bool(stored.get(field, False)):
                return False
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    return True


def _normalize_cursor_entry(raw: Any) -> dict[str, Any] | None:
    """Read one cursor entry in the v2 shape, filling v1 defaults.

    Today's on-disk shape carries only `source_id`, `start`, `end`,
    `busy`, `tags`, `is_new`: `cancelled` defaults to False, `rev` to 0,
    and `stamp` is derived from the stored `source_id` after the last `@`
    (UIDs may contain `@`, so only the trailing segment is the stamp).
    Anything that is not a dict reads as absent; nothing here raises.
    """
    stored = as_dict(raw)
    if stored is None:
        return None
    source_id = str(stored.get("source_id", ""))
    try:
        rev = int(stored.get("rev", 0))
    except (ValueError, TypeError):
        rev = 0
    stamp = stored.get("stamp")
    if not isinstance(stamp, str) or not stamp:
        stamp = source_id.rsplit("@", 1)[-1] if "@" in source_id else ""
    return {
        "source_id": source_id,
        "start": stored.get("start"),
        "end": stored.get("end"),
        "busy": stored.get("busy"),
        "tags": stored.get("tags"),
        "is_new": stored.get("is_new"),
        "cancelled": bool(stored.get("cancelled", False)),
        "rev": rev,
        "stamp": stamp,
    }


class CalendarIcsCollector:
    """Poll one secret iCal feed; titles derive tags, then are dropped."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        label: str = "personal",
        title_sink: dict[str, str] | None = None,
    ) -> None:
        if LABEL_PATTERN.fullmatch(label) is None:
            raise ValueError(f"invalid calendar label: {label!r}")
        self._http_get = http_get
        self._now_fn = now_fn
        self.label = label
        self.name = f"calendar-{label}"
        self.version = "calendar@0.1.0"
        self.title_sink = title_sink

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
                current[str(snapshot["key"])] = snapshot

        prev: dict[str, Any] = {}
        cursor_dict = as_dict(cursor)
        if cursor_dict is not None:
            instances = as_dict(cursor_dict.get("instances"))
            if instances is not None:
                prev = instances

        if not cal.walk("VEVENT") and any(  # pyright: ignore[reportUnknownMemberType]
            (entry := as_dict(raw)) is not None and not entry.get("cancelled", False)
            for raw in prev.values()
        ):
            return [], cursor

        events: list[Event] = []
        next_instances: dict[str, dict[str, Any]] = {}
        for key, snapshot in current.items():
            content = snapshot["content"]
            stamp = str(snapshot["stamp"])
            cancelled_now = bool(snapshot["cancelled"])
            entry = _normalize_cursor_entry(prev.get(key))
            if entry is None:
                source_id = f"{key}@{stamp}"
                next_instances[key] = {
                    **content,
                    "source_id": source_id,
                    "cancelled": cancelled_now,
                    "rev": 0,
                    "stamp": stamp,
                }
                if cancelled_now:
                    events.append(
                        self._build_cancelled(
                            subject_id, content, source_id + "#cancelled", now
                        )
                    )
                else:
                    events.append(
                        self._build_event(
                            "calendar.event.created",
                            CalendarEventCreatedData,
                            subject_id,
                            {**content, "source_id": source_id},
                            now,
                        )
                    )
                continue
            if entry["cancelled"]:
                if cancelled_now:
                    next_instances[key] = {
                        **content,
                        "source_id": entry["source_id"],
                        "cancelled": True,
                        "rev": entry["rev"],
                        "stamp": stamp,
                    }
                else:
                    rev = int(entry["rev"]) + 1
                    source_id = f"{key}@{stamp}#r{rev}"
                    next_instances[key] = {
                        **content,
                        "source_id": source_id,
                        "cancelled": False,
                        "rev": rev,
                        "stamp": stamp,
                    }
                    events.append(
                        self._build_event(
                            "calendar.event.updated",
                            CalendarEventUpdatedData,
                            subject_id,
                            {**content, "source_id": source_id},
                            now,
                        )
                    )
                continue
            if cancelled_now:
                source_id = str(entry["source_id"]) + "#cancelled"
                next_instances[key] = {
                    **content,
                    "source_id": str(entry["source_id"]),
                    "cancelled": True,
                    "rev": entry["rev"],
                    "stamp": stamp,
                }
                events.append(
                    self._build_cancelled(subject_id, content, source_id, now)
                )
            elif _content_equal(content, entry) and stamp == str(entry["stamp"]):
                next_instances[key] = entry
            else:
                rev = int(entry["rev"]) + 1
                source_id = f"{key}@{stamp}#r{rev}"
                next_instances[key] = {
                    **content,
                    "source_id": source_id,
                    "cancelled": False,
                    "rev": rev,
                    "stamp": stamp,
                }
                events.append(
                    self._build_event(
                        "calendar.event.updated",
                        CalendarEventUpdatedData,
                        subject_id,
                        {**content, "source_id": source_id},
                        now,
                    )
                )
        for key, stored_raw in prev.items():
            if key in current:
                continue
            stored = as_dict(stored_raw)
            if stored is None:
                continue
            try:
                stored_start = datetime.fromisoformat(str(stored["start"]))
            except (ValueError, KeyError, TypeError):
                continue
            try:
                too_old = stored_start < window_start
            except TypeError:
                continue
            if too_old:
                continue
            entry = _normalize_cursor_entry(stored)
            if entry is None:
                continue
            if entry["cancelled"]:
                next_instances[key] = entry
                continue
            source_id = str(entry["source_id"]) + "#cancelled"
            next_instances[key] = {
                "source_id": str(entry["source_id"]),
                "start": entry["start"],
                "end": entry["end"],
                "busy": entry["busy"],
                "tags": entry["tags"],
                "is_new": entry["is_new"],
                "cancelled": True,
                "rev": entry["rev"],
                "stamp": entry["stamp"],
            }
            events.append(self._build_cancelled(subject_id, entry, source_id, now))

        if self.title_sink is not None:
            for key, snapshot in current.items():
                if bool(snapshot["cancelled"]):
                    continue
                summary = str(snapshot["summary"])
                if not summary.strip():
                    continue
                final_source_id = str(next_instances[key]["source_id"])
                self.title_sink[event_id(self.name, final_source_id)] = summary

        events.sort(key=lambda e: (e.time, e.source_id))
        return events, {"instances": next_instances}

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

        raw_summary = component.get("SUMMARY")
        summary = str(raw_summary) if raw_summary is not None else ""
        tags = list(dict.fromkeys(TAG_PATTERN.findall(summary)))
        is_new = summary.strip().startswith("new:")
        raw_transp = component.get("TRANSP", "OPAQUE")
        busy = str(raw_transp).upper() != "TRANSPARENT"
        cancelled = str(component.get("STATUS", "") or "").upper() == "CANCELLED"
        return {
            "key": key,
            "stamp": last_modified,
            "cancelled": cancelled,
            "summary": summary,
            "content": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "busy": busy,
                "tags": tags,
                "is_new": is_new,
                "cancelled": cancelled,
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
        self, subject_id: str, fields: dict[str, Any], source_id: str, now: datetime
    ) -> Event:
        start = datetime.fromisoformat(str(fields["start"]))
        try:
            end = datetime.fromisoformat(str(fields["end"]))
        except (ValueError, KeyError, TypeError):
            end = start
        raw_tags: Any = fields.get("tags")
        tag_list: list[str] = (
            [str(tag) for tag in cast("list[Any]", raw_tags)]
            if isinstance(raw_tags, list)
            else []
        )
        payload = CalendarEventCancelledData(
            start=start,
            end=end,
            busy=bool(fields.get("busy", False)),
            category=self.label,
            tags=tag_list,
            is_new=bool(fields.get("is_new", False)),
        )
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
