"""Ticket 10: metric label bindings (which prose names which metric).

One pure function over the metric id: no I/O, no env, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

_PUSH_LABELS = frozenset({"push", "pushes", "pushed", "pushing"})
_PR_LABELS = frozenset({"pr", "prs", "pull request", "pull requests"})
_FEED_LABELS = frozenset({"feed", "feeds"})
_BUSY_LABELS = frozenset({"busy"})

_PINNED_FORM_SETS = (_PUSH_LABELS, _PR_LABELS, _FEED_LABELS, _BUSY_LABELS)


def label_forms(label: str) -> frozenset[str]:
    """All accepted prose forms of one label (casefolded match set).

    Labels from a pinned family return the whole family set; anything
    else returns just the label itself.
    """
    folded = label.casefold()
    for forms in _PINNED_FORM_SETS:
        if folded in forms:
            return forms
    return frozenset({label})


_PERIODS = ("earlier", "prior", "last")
_FEED_PREFIX = "feed.item.count"


@dataclass(frozen=True)
class MetricBinding:
    """Accepted prose for one metric id."""

    labels: frozenset[str]
    period: str | None
    family: str
    requires_cancel: bool


def _screen_labels(category: str) -> frozenset[str] | None:
    if not category or not category.strip():
        return None
    last = category.rsplit("/", 1)[-1]
    if not last or not last.strip():
        return None
    return frozenset({category, last})


def _tag_labels(tag: str) -> frozenset[str] | None:
    if not tag or not tag.strip():
        return None
    if tag.startswith("iki-"):
        word = tag[len("iki-") :]
        if not word or not word.strip():
            return None
        return frozenset({tag, word})
    return frozenset({tag})


def metric_unit_class(metric_id: str) -> str | None:
    """Return the unit class (``hours`` or ``count``) for ``metric_id``.

    Derived from the same family parse as ``metric_label_binding``;
    unknown families give ``None``.
    """
    remainder = metric_id
    for name in _PERIODS:
        prefix = f"period.{name}."
        if metric_id.startswith(prefix):
            remainder = metric_id[len(prefix) :]
            break
    else:
        if metric_id.startswith("period."):
            return None
    if remainder.startswith("screen_hours."):
        return "hours" if _screen_labels(remainder[len("screen_hours.") :]) else None
    if remainder.startswith("tag_hours."):
        return "hours" if _tag_labels(remainder[len("tag_hours.") :]) else None
    if remainder.startswith("cancelled."):
        return "count" if _tag_labels(remainder[len("cancelled.") :]) else None
    if remainder in ("pushes", "prs"):
        return "count"
    if remainder in (
        "github.push.count",
        "github.pr.count",
        "calendar.busy_hours",
        _FEED_PREFIX,
    ):
        return "hours" if remainder == "calendar.busy_hours" else "count"
    if remainder.startswith(_FEED_PREFIX + "."):
        return "count" if remainder[len(_FEED_PREFIX) + 1 :].strip() else None
    return None


def metric_label_binding(metric_id: str) -> MetricBinding | None:
    """Return the prose binding for ``metric_id``, or ``None`` (unknown)."""
    period: str | None = None
    remainder = metric_id
    for name in _PERIODS:
        prefix = f"period.{name}."
        if metric_id.startswith(prefix):
            period, remainder = name, metric_id[len(prefix) :]
            break
    else:
        if metric_id.startswith("period."):
            return None

    if remainder.startswith("screen_hours."):
        labels = _screen_labels(remainder[len("screen_hours.") :])
        if labels is None:
            return None
        return MetricBinding(labels, period, remainder, False)
    if remainder.startswith("tag_hours."):
        labels = _tag_labels(remainder[len("tag_hours.") :])
        if labels is None:
            return None
        return MetricBinding(labels, period, remainder, False)
    if period is None:
        if remainder == "github.push.count":
            return MetricBinding(_PUSH_LABELS, period, remainder, False)
        if remainder == "github.pr.count":
            return MetricBinding(_PR_LABELS, period, remainder, False)
        if remainder == "calendar.busy_hours":
            return MetricBinding(frozenset({"busy"}), period, remainder, False)
        if remainder == _FEED_PREFIX:
            return MetricBinding(_FEED_LABELS, period, remainder, False)
        if remainder.startswith(_FEED_PREFIX + "."):
            if not remainder[len(_FEED_PREFIX) + 1 :].strip():
                return None
            return MetricBinding(_FEED_LABELS, period, remainder, False)
        return None
    if remainder == "pushes":
        return MetricBinding(_PUSH_LABELS, period, remainder, False)
    if remainder == "prs":
        return MetricBinding(_PR_LABELS, period, remainder, False)
    if remainder.startswith("cancelled."):
        labels = _tag_labels(remainder[len("cancelled.") :])
        if labels is None:
            return None
        return MetricBinding(labels, period, remainder, True)
    return None
