"""Ticket 26: domain pack CSV adapter.

Reads the pinned CSV sources (after checking their sha256), groups rows
by date, and builds one window reference per window start. Dates may be
ISO dates or ISO datetimes; only the first 10 characters count.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from framework.domains.schema import DomainPack

_START_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class SourceHashMismatch(ValueError):
    """A source file on disk does not match the hash pinned in the pack."""


class IdentityError(ValueError):
    """A pack identity failed on a window date."""


class WindowError(ValueError):
    """A window start is unknown, or a source date value is unusable."""


def _read_source(pack: DomainPack, pack_dir: Path, key: str) -> list[dict[str, str]]:
    spec = pack.sources[key]
    try:
        raw = (pack_dir / spec.path).read_bytes()
    except OSError:
        raise WindowError(f"cannot read source {key}") from None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != spec.sha256:
        raise SourceHashMismatch(f"source hash mismatch: {key}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise WindowError(f"cannot read source {key}") from None
    rows: list[dict[str, str]] = []
    for record in csv.DictReader(io.StringIO(text)):
        rows.append({name: (value or "") for name, value in record.items()})
    return rows


def load_sources(
    pack: DomainPack, pack_dir: str | Path
) -> dict[str, list[dict[str, str]]]:
    """Read every pack source after checking its pinned sha256."""
    base = Path(pack_dir)
    return {key: _read_source(pack, base, key) for key in pack.sources}


def _row_date(value: Any, source_key: str) -> str:
    if not isinstance(value, str) or not value:
        raise WindowError(f"bad date value in source {source_key}")
    day = value[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        raise WindowError(f"bad date value in source {source_key}") from None
    return day


def _grouped(
    rows: list[dict[str, str]], date_column: str, source_key: str
) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        day = _row_date(row.get(date_column), source_key)
        groups.setdefault(day, []).append(row)
    return groups


def _metric_source_keys(pack: DomainPack) -> list[str]:
    keys: list[str] = []
    for metric in pack.daily_metrics:
        if metric.source not in keys:
            keys.append(metric.source)
    return keys


def window_starts(pack: DomainPack, pack_dir: str | Path) -> list[str]:
    """Every window start: a `starts_on` weekday with full date coverage."""
    base = Path(pack_dir)
    groups = {
        key: _grouped(_read_source(pack, base, key), pack.sources[key].date_column, key)
        for key in _metric_source_keys(pack)
    }
    wanted = _START_WEEKDAY[pack.window.starts_on]
    candidates = {day for group in groups.values() for day in group}
    starts: list[str] = []
    for day in sorted(candidates):
        if date.fromisoformat(day).weekday() != wanted:
            continue
        first = date.fromisoformat(day)
        span = [
            (first + timedelta(days=offset)).isoformat()
            for offset in range(pack.window.days)
        ]
        if all(entry in group for group in groups.values() for entry in span):
            starts.append(day)
    return starts


def _window_dates(window_start: str, days: int) -> list[str]:
    first = date.fromisoformat(window_start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(days)]


def _int_value(raw: Any, source_key: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise WindowError(f"bad number value in source {source_key}") from None


@dataclass(frozen=True)
class IdentityResult:
    """Whether one identity held, and over how many dates."""

    kind: str
    dates_checked: int
    held: bool


@dataclass(frozen=True)
class WindowReference:
    """The checked numbers for one window, ready for the checker."""

    pack_id: str
    window_start: str
    dates: tuple[str, ...]
    metrics: dict[str, int]
    labels: dict[str, list[str]]
    units: dict[str, str]
    periods: dict[str, str]
    order: list[list[str]]
    facts: dict[str, str]
    identities: tuple[IdentityResult, ...]

    def check_input(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        """Return the full dict `check_claims` accepts for these claims."""
        return {
            "claims": claims,
            "facts": dict(self.facts),
            "metrics": dict(self.metrics),
            "labels": {key: list(value) for key, value in self.labels.items()},
            "units": dict(self.units),
            "periods": dict(self.periods),
            "order": [list(series) for series in self.order],
        }


def build_reference(
    pack: DomainPack, pack_dir: str | Path, window_start: str
) -> WindowReference:
    """Build the reference for one window; identities must hold."""
    base = Path(pack_dir)
    if window_start not in window_starts(pack, base):
        raise WindowError(f"unknown window start: {window_start}")
    groups = {key: _read_grouped(pack, base, key) for key in _grouped_keys(pack)}
    dates = _window_dates(window_start, pack.window.days)
    metrics: dict[str, int] = {}
    labels: dict[str, list[str]] = {}
    units: dict[str, str] = {}
    periods: dict[str, str] = {}
    daily_values: dict[str, list[int]] = {}
    for metric in pack.daily_metrics:
        group = groups[metric.source]
        values: list[int] = []
        for day in dates:
            rows = group.get(day, [])
            if metric.op == "sum":
                total = sum(
                    _int_value(row.get(metric.column), metric.source) for row in rows
                )
            else:
                assert metric.above is not None
                total = sum(
                    1
                    for row in rows
                    if _int_value(row.get(metric.column), metric.source) > metric.above
                )
            metric_id = f"{metric.prefix}.{day}"
            metrics[metric_id] = total
            labels[metric_id] = list(metric.labels)
            units[metric_id] = metric.unit
            periods[metric_id] = day
            values.append(total)
        daily_values[metric.prefix] = values
    for metric in pack.window_metrics:
        values = daily_values[metric.of]
        if metric.op == "sum":
            folded = sum(values)
        elif metric.op == "max":
            folded = max(values)
        else:
            assert metric.above is not None
            folded = sum(1 for item in values if item > metric.above)
        metrics[metric.id] = folded
        labels[metric.id] = list(metric.labels)
        units[metric.id] = metric.unit
        periods[metric.id] = pack.window.period_phrase.replace("{start}", window_start)
    order = [
        [f"{metric.prefix}.{day}" for day in dates] for metric in pack.daily_metrics
    ]
    results: list[IdentityResult] = []
    for identity in pack.identities:
        group = groups[identity.source]
        if identity.kind == "columns_sum":
            assert identity.parts is not None and identity.total is not None
            for day in dates:
                for row in group.get(day, []):
                    parts = sum(
                        _int_value(row.get(part), identity.source)
                        for part in identity.parts
                    )
                    if parts != _int_value(row.get(identity.total), identity.source):
                        raise IdentityError(f"identity columns_sum failed on {day}")
        elif identity.kind == "daily_matches":
            assert identity.metric is not None and identity.column is not None
            for day in dates:
                hourly = sum(
                    _int_value(row.get(identity.column), identity.source)
                    for row in group.get(day, [])
                )
                if metrics[f"{identity.metric}.{day}"] != hourly:
                    raise IdentityError(f"identity daily_matches failed on {day}")
        elif identity.kind == "rows_per_date":
            assert identity.count is not None
            for day in dates:
                if len(group.get(day, [])) != identity.count:
                    raise IdentityError(f"identity rows_per_date failed on {day}")
        results.append(
            IdentityResult(kind=identity.kind, dates_checked=len(dates), held=True)
        )
    return WindowReference(
        pack_id=pack.pack_id,
        window_start=window_start,
        dates=tuple(dates),
        metrics=metrics,
        labels=labels,
        units=units,
        periods=periods,
        order=order,
        facts=dict(pack.facts),
        identities=tuple(results),
    )


def _read_grouped(
    pack: DomainPack, base: Path, key: str
) -> dict[str, list[dict[str, str]]]:
    return _grouped(_read_source(pack, base, key), pack.sources[key].date_column, key)


def _grouped_keys(pack: DomainPack) -> list[str]:
    return list(pack.sources)
