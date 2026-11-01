"""Ticket 14: voice correction state as a pure fold over append-only events.

Effective state replays from the store: later words win in ``(said_at,
message_id)`` order, ``keep`` clears any earlier entry, and fact disputes
drop cited facts and the metrics their numbers would rebuild. Pure: no
store writes here. Imports nothing from ``framework.cycle`` or
``framework.voice.worker``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from framework.briefing.context import MetricSnapshot
from framework.briefing.numbers import extract_number_tokens
from framework.briefing.schemas import Commitment
from framework.proposal.prompt import display_value
from framework.schemas.core import Fact
from framework.schemas.events import (
    AppCorrectionData,
    AppFactDisputeData,
    Event,
)
from framework.store.store import EventStore
from framework.telegram.models import first_rulings

MADRID = ZoneInfo("Europe/Madrid")

SKIPPED_OPEN = "skipped_open"
DROPPED = "dropped"

_VOICE_STATE_TYPES = ("app.correction", "app.fact_dispute")


@dataclass(frozen=True)
class CommitmentStateEntry:
    """One commitment's standing correction, if any."""

    status: str
    hidden_for_slot: datetime | None = None
    hidden_until: datetime | None = None
    done_day: date | None = None


@dataclass(frozen=True)
class MetricCitation:
    """One disputed metric citation: id, value, cycle, and Madrid day."""

    metric_id: str
    value: float
    cycle_id: str
    day: date


@dataclass(frozen=True)
class DisputedCitations:
    """Every disputed fact id and metric citation in the window."""

    fact_ids: frozenset[str] = frozenset()
    metrics: tuple[MetricCitation, ...] = ()


def _madrid_midnight(day: date, plus_days: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MADRID) + timedelta(
        days=plus_days
    )


def _next_monday(day: date) -> datetime:
    ahead = 7 - day.weekday() if day.weekday() else 7
    return _madrid_midnight(day, plus_days=ahead)


def _entry_for_correction(data: AppCorrectionData) -> CommitmentStateEntry | None:
    """Map one validated correction to its fold entry; None clears or skips."""
    operation = data.operation
    until = data.until
    if data.commitment_id is None:
        return None
    if operation == "keep" and until is None:
        return None
    said_day = data.said_at.astimezone(MADRID).date()
    if operation == "skip":
        if until == "slot":
            return CommitmentStateEntry(status="skip", hidden_for_slot=data.slot)
        if until == "today":
            return CommitmentStateEntry(
                status="skip", hidden_until=_madrid_midnight(said_day, 1)
            )
        if until == "tomorrow":
            return CommitmentStateEntry(
                status="skip", hidden_until=_madrid_midnight(said_day, 2)
            )
        if until == "this_week":
            return CommitmentStateEntry(
                status="skip", hidden_until=_next_monday(said_day)
            )
        if until == "open":
            return CommitmentStateEntry(status=SKIPPED_OPEN)
        return None
    if operation == "defer":
        if until == "today":
            return CommitmentStateEntry(status="defer", hidden_for_slot=data.slot)
        if until in ("tomorrow", "this_week"):
            return CommitmentStateEntry(
                status="defer", hidden_until=_madrid_midnight(said_day, 1)
            )
        return None
    if operation == "drop" and until == "open":
        return CommitmentStateEntry(status=DROPPED)
    if operation == "done" and until == "today":
        return CommitmentStateEntry(
            status="done",
            hidden_until=_madrid_midnight(said_day, 1),
            done_day=said_day,
        )
    return None


def fold_corrections(events: Iterable[Event]) -> dict[str, CommitmentStateEntry]:
    """Last wins per commitment in ``(said_at, message_id)`` order.

    A note that waited can be applied after a later one; the later word
    still wins because the fold orders by when it was said, not stored.
    ``keep`` clears the entry, undoing skip, defer, drop, and done.
    """
    corrections = [
        event.data for event in events if isinstance(event.data, AppCorrectionData)
    ]
    corrections.sort(key=_correction_key)
    entries: dict[str, CommitmentStateEntry] = {}
    for data in corrections:
        if data.commitment_id is None:
            continue
        if data.operation == "keep" and data.until is None:
            entries.pop(data.commitment_id, None)
            continue
        entry = _entry_for_correction(data)
        if entry is not None:
            entries[data.commitment_id] = entry
    return entries


def _correction_key(data: AppCorrectionData) -> tuple[datetime, int]:
    return (data.said_at, data.message_id)


def is_hidden(entry: CommitmentStateEntry | None, slot: datetime) -> bool:
    """True when the entry hides its commitment at slot ``S``."""
    if entry is None:
        return False
    if entry.status in (DROPPED, SKIPPED_OPEN):
        return True
    if entry.hidden_for_slot is not None and entry.hidden_for_slot == slot:
        return True
    return entry.hidden_until is not None and slot < entry.hidden_until


def filter_eligible(
    commitments: Sequence[Commitment],
    entries: Mapping[str, CommitmentStateEntry],
    *,
    slot: datetime,
) -> tuple[Commitment, ...]:
    """Keep file order; drop commitments hidden at ``slot``."""
    return tuple(
        commitment
        for commitment in commitments
        if not is_hidden(entries.get(commitment.id), slot)
    )


def fold_disputes(events: Iterable[Event]) -> DisputedCitations:
    """Collect every disputed fact id and metric citation in the window."""
    fact_ids: set[str] = set()
    metrics: list[MetricCitation] = []
    for event in events:
        data = event.data
        if not isinstance(data, AppFactDisputeData):
            continue
        if data.fact_id is not None:
            fact_ids.add(data.fact_id)
        elif data.metric_id is not None:
            assert data.metric_value is not None and data.cycle_id is not None
            metrics.append(
                MetricCitation(
                    metric_id=data.metric_id,
                    value=data.metric_value,
                    cycle_id=data.cycle_id,
                    day=event.time.astimezone(MADRID).date(),
                )
            )
    metrics.sort(key=lambda m: (m.metric_id, m.value, m.cycle_id, m.day))
    return DisputedCitations(fact_ids=frozenset(fact_ids), metrics=tuple(metrics))


def disputes_for_cycle(
    disputed: DisputedCitations, cycle_id: str, day: date
) -> DisputedCitations:
    """Narrow a dispute set to one cycle's claim about the world on one day.

    Fact disputes outlive their cycle: the mint hashes the statement and
    its sorted evidence, so the same statement over the same evidence
    mints the same id next cycle and the dispute still bites. A disputed
    metric citation bites at the same value for the cycle it was
    disputed in, and for any other cycle on the same Madrid day as the
    dispute, because the same value on the same day is the same claim
    restated; the same metric at a new value is a new claim about the
    world, not the one rejected. The day after, the windows have moved,
    so an equal number is a coincidence and it no longer bites. A fact
    dropped for holding a disputed metric's number follows the same
    rule, since it reads the narrowed citations. Ticket 13 makes a new
    cycle for every slot, so a same-cycle rule alone would last one
    corrected card; that is why a dispute now holds for any cycle on
    the same Madrid day.
    """
    return DisputedCitations(
        fact_ids=disputed.fact_ids,
        metrics=tuple(
            citation
            for citation in disputed.metrics
            if citation.cycle_id == cycle_id or citation.day == day
        ),
    )


def load_voice_state(
    store: EventStore, subject_id: str, *, start: datetime, end: datetime
) -> tuple[dict[str, CommitmentStateEntry], DisputedCitations]:
    """Fold corrections and disputes over ``[start, end)``.

    Callers pass a fixed early instant as ``start`` so a drop from weeks
    ago still holds at re-proposal time.
    """
    events = store.events_between(
        subject_id, start, end, types=list(_VOICE_STATE_TYPES)
    )
    return (fold_corrections(events), fold_disputes(events))


def standing_chain_ruling(
    events: Iterable[Event], chain_card_ids: Sequence[str]
) -> tuple[str, str] | None:
    """One standing ruling for a replaced-card chain, oldest to newest.

    The newest card's ruling wins when it has one, else the newest older
    card with one, else None. A late tap on an old card still stores, but
    it cannot win over a tap on the new card.
    """
    rulings = first_rulings(events)
    for card_id in reversed(list(chain_card_ids)):
        if card_id in rulings:
            return (card_id, rulings[card_id])
    return None


def disputed_number_displays(
    fact_rows: Iterable[tuple[str, str]], disputed: DisputedCitations
) -> frozenset[str]:
    """Display values of number tokens in disputed facts' statements.

    Takes ``(fact_id, statement)`` pairs and returns ``display_value`` of
    each number token of each statement whose id is in
    ``disputed.fact_ids``.
    """
    displays: set[str] = set()
    for fact_id, statement in fact_rows:
        if fact_id not in disputed.fact_ids:
            continue
        for token in extract_number_tokens(statement):
            displays.add(display_value(float(token.value)))
    return frozenset(displays)


def disputed_numbers(
    disputed: DisputedCitations, fact_rows: Iterable[tuple[str, str]]
) -> frozenset[str]:
    """One shared definition of the numbers a dispute takes out of a cycle.

    The display value of every disputed metric citation, together with the
    display value of every number token in the statement of every disputed
    fact present among ``fact_rows``. Comparing display values means a
    statement token written ``7.0`` matches a metric citation at ``7``.
    Only id-disputed facts feed the set: a fact dropped for sharing a
    number is not itself a dispute, so its other numbers stay usable.
    """
    displays = {display_value(citation.value) for citation in disputed.metrics}
    displays |= set(disputed_number_displays(fact_rows, disputed))
    return frozenset(displays)


def statement_holds_number(statement: str, numbers: frozenset[str]) -> bool:
    """True when any number token of the statement shows a disputed number."""
    if not numbers:
        return False
    return any(
        display_value(float(token.value)) in numbers
        for token in extract_number_tokens(statement)
    )


def apply_disputes(
    facts: Sequence[Fact],
    snapshot: MetricSnapshot,
    parent_metrics: MetricSnapshot | None,
    disputed: DisputedCitations | None,
) -> tuple[list[Fact], MetricSnapshot, MetricSnapshot | None]:
    """Drop disputed facts and metrics; pure, returns filtered copies.

    A fact goes when it is disputed by id, or when a number token of its
    statement shows a disputed number: a disputed metric citation's
    display value or a number from a disputed fact's statement. A metric
    goes when it is a disputed citation (same id at the same value), or
    when its display value is a number from a disputed fact's statement.
    A disputed metric's own display value drops no other metric.
    A fact dropped only for sharing a number is not a dispute itself: it
    writes no event, and its other numbers do not join the disputed set,
    so it comes back once the metric disputes stop biting.
    """
    if disputed is None or (not disputed.fact_ids and not disputed.metrics):
        return (list(facts), snapshot, parent_metrics)
    fact_rows = tuple((fact.id, fact.statement) for fact in facts)
    numbers = disputed_numbers(disputed, fact_rows)
    fact_numbers = disputed_number_displays(fact_rows, disputed)
    kept_facts = [
        fact
        for fact in facts
        if fact.id not in disputed.fact_ids
        and not statement_holds_number(fact.statement, numbers)
    ]

    def _disputed_value(metric_id: str, value: float) -> bool:
        if any(
            citation.metric_id == metric_id and citation.value == value
            for citation in disputed.metrics
        ):
            return True
        return display_value(value) in fact_numbers

    def _filter_snapshot(values: Mapping[str, float]) -> MetricSnapshot:
        return MetricSnapshot(
            values={
                metric_id: value
                for metric_id, value in values.items()
                if not _disputed_value(metric_id, value)
            }
        )

    filtered_parent: MetricSnapshot | None = None
    if parent_metrics is not None:
        filtered_parent = _filter_snapshot(parent_metrics.values)
    return (kept_facts, _filter_snapshot(snapshot.values), filtered_parent)


__all__ = [
    "CommitmentStateEntry",
    "DisputedCitations",
    "MetricCitation",
    "apply_disputes",
    "disputed_number_displays",
    "disputed_numbers",
    "disputes_for_cycle",
    "filter_eligible",
    "fold_corrections",
    "fold_disputes",
    "is_hidden",
    "load_voice_state",
    "standing_chain_ruling",
    "statement_holds_number",
]
