"""Ticket 13 slice 2: pure card assembly over passed-in rows and results.

Statements, the since line, chart data and the card. No store, no clock,
no model. Display names come from the profile id with a capital first
letter, the same mapping the proposal prompt uses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from framework.briefing.schemas import Briefing, Commitment
from framework.cycle.slot_ledger import SlotCardRow
from framework.glimmer.metrics import (
    build_period_rollup,
    floor_hour,
    is_opened_pr,
    period_bounds,
    select_winners,
    window_bounds,
)
from framework.learner import Proposal as LearnerProposal
from framework.proposal.core import ProposalResult
from framework.schemas.events import Event
from framework.store.proposal_store import StoredResult
from framework.telegram import Proposal as CardProposal
from framework.telegram.models import (
    Card,
    ChartData,
    ChartSeries,
    MissingEntry,
    TallyItem,
    first_rulings,
)

CATEGORIES = ("code", "ai", "comms", "feed", "browse", "media")

Letter = Literal["A", "B"]

_PUSHES_LABEL = "pushes + PRs"
_PUSHES_MISSING: MissingEntry = "pushes + PRs"
_SCREEN_MISSING: MissingEntry = "screen"
_PERIOD_MISSING: tuple[MissingEntry, MissingEntry, MissingEntry] = (
    "screen earlier",
    "screen prior",
    "screen last",
)
_AB: tuple[Letter, Letter] = ("A", "B")


def _display_name(profile_id: str) -> str:
    return profile_id.capitalize()


def build_statements(
    sides: Sequence[tuple[str, str, Briefing]],
) -> tuple[str, ...]:
    """Header plus at most 3 claims per proposal side.

    The first statement of a side is the first ``overall_state`` claim,
    whichever order the sections came in; then the remaining claims in
    section order, up to 3. The header piece does not count, because the
    model's ``maxItems`` is not re-checked after it returns.
    """
    pieces: list[str] = []
    for letter, display, briefing in sides:
        pieces.append(f"{letter} · {display}")
        ordered = [claim for section in briefing.sections for claim in section.claims]
        first_overall = next(
            (
                claim
                for section in briefing.sections
                if section.type == "overall_state"
                for claim in section.claims
            ),
            None,
        )
        if first_overall is not None:
            rest = [claim for claim in ordered if claim.id != first_overall.id]
            ordered = [first_overall, *rest]
        pieces.extend(claim.text for claim in ordered[:3])
    return tuple(pieces)


def since_counts(
    events: Sequence[Event], previous_as_of: datetime, as_of: datetime
) -> dict[str, float]:
    """One plain count over the floored interval between two cards.

    A row counts when its ``time`` sits at or after the earlier card's
    floor and before this card's floor, and it was collected by this
    card's raw ``as_of``. ``select_winners`` picks the latest version of
    each row, so an hour inside the interval counts whole at its latest
    version, and a row dated before the last card never counts as since.
    Nothing can go negative, so there is no subtraction and no clamp. A
    first card passes ``as_of`` minus 24 hours as its earlier instant, so
    it is a plain count over the floored 24 hours with no special case.
    """
    previous_floor = floor_hour(previous_as_of)
    current_floor = floor_hour(as_of)
    rows = [
        event
        for event in events
        if previous_floor <= event.time < current_floor and event.collected_at <= as_of
    ]
    counts: dict[str, float] = {"pushes": 0.0}
    counts.update({category: 0.0 for category in CATEGORIES})
    for event in select_winners(rows):
        if event.type == "github.push" or (
            event.type == "github.pr" and is_opened_pr(event)
        ):
            counts["pushes"] += 1.0
        elif event.type == "screen.hour":
            minutes = getattr(event.data, "minutes_by_category", {})
            for category in CATEGORIES:
                counts[category] += float(minutes.get(category, 0.0)) / 60.0
    return counts


def since_line(
    previous_slot_local: datetime,
    counts: Mapping[str, float],
    *,
    first: bool = False,
) -> str:
    """The exact since line for one card."""
    head = previous_slot_local.strftime("%H:%M")
    pieces: list[str] = []
    pushes = counts.get("pushes", 0.0)
    if f"{pushes:.0f}" != "0":
        count = int(pushes)
        pieces.append(f"{count} push + PR" if count == 1 else f"{count} pushes + PRs")
    for category in CATEGORIES:
        value = counts.get(category, 0.0)
        if f"{value:.1f}" == "0.0":
            continue
        pieces.append(f"{category} {value:.1f}h")
    if first:
        if not pieces:
            return "First card, last 24h: nothing recorded."
        return f"First card, last 24h: {', '.join(pieces)}."
    if not pieces:
        return f"Since {head}: nothing new recorded."
    return f"Since {head}: {', '.join(pieces)}."


def build_tally(
    taps: Sequence[Event], card_rows: Sequence[SlotCardRow]
) -> tuple[TallyItem, ...]:
    """Standing rulings keyed by profile, never by letter.

    A lone Disconnect card carries label A, so the letter alone would
    misread it. Cards with no stored row stay out.
    """
    letters: dict[str, dict[str, str]] = {}
    for row in sorted(card_rows, key=lambda item: (item.card_id, item.letter)):
        letters.setdefault(row.card_id, {})[row.letter] = row.profile_id
    counts = {"Builder": 0, "Disconnect": 0, "Neither": 0}
    for card_id, target in first_rulings(taps).items():
        mapping = letters.get(card_id)
        if mapping is None:
            continue
        if target == "neither":
            counts["Neither"] += 1
        elif target in mapping:
            counts[_display_name(mapping[target])] += 1
    return tuple(
        TallyItem(label=name, count=counts[name])
        for name in ("Builder", "Disconnect", "Neither")
    )


def build_chart_data(
    events: Sequence[Event],
    as_of: datetime,
    tally: Sequence[TallyItem],
    *,
    period_labels: tuple[str, str, str] = ("earlier", "prior", "last"),
) -> ChartData:
    """Chart values from winning rows collected in time.

    "In the window" is ``window_bounds(as_of)``, the floored window the
    snapshot reads, so a push only in the open hour is no data on this
    card and a screen row only in the open hour does not count as the
    window having screen data. Screen is missing when no winning
    ``screen.hour`` row sits in the floored window; each quiet period is
    its own ``screen <name>`` entry. Pushes are missing only when no push
    or pull-request winner exists in the floored window; otherwise the
    series sums pushes and opened requests per period.
    """
    rows = [event for event in events if event.collected_at <= as_of]
    winners = select_winners(rows)
    window_start, window_end = window_bounds(as_of)
    in_window = [event for event in winners if window_start <= event.time < window_end]
    bounds = period_bounds(as_of)
    screen = [event for event in in_window if event.type == "screen.hour"]
    missing: list[MissingEntry] = []
    series: list[ChartSeries] = []
    if not screen:
        missing.append(_SCREEN_MISSING)
    else:
        for index, (_, start, end) in enumerate(bounds):
            if not any(start <= event.time < end for event in screen):
                missing.append(_PERIOD_MISSING[index])
        rollup = build_period_rollup(as_of, winners)
        for category in CATEGORIES:
            values = tuple(
                float(rollup[name]["screen_hours"].get(category, 0.0))
                for name, _, _ in bounds
            )
            if any(values):
                series.append(
                    ChartSeries(
                        label=category,
                        earlier=values[0],
                        prior=values[1],
                        last=values[2],
                    )
                )
        if not series:
            missing.append(_SCREEN_MISSING)
    pushes: ChartSeries | None
    if not any(event.type in ("github.push", "github.pr") for event in in_window):
        pushes = None
        missing.append(_PUSHES_MISSING)
    else:
        rollup = build_period_rollup(as_of, winners)
        pushes = ChartSeries(
            label=_PUSHES_LABEL,
            earlier=float(rollup["earlier"]["pushes"] + rollup["earlier"]["prs"]),
            prior=float(rollup["prior"]["pushes"] + rollup["prior"]["prs"]),
            last=float(rollup["last"]["pushes"] + rollup["last"]["prs"]),
        )
    return ChartData(
        period_labels=period_labels,
        screen=tuple(series),
        pushes=pushes,
        tally=tuple(tally),
        missing=tuple(missing),
    )


def minimal_chart_data(
    tally: Sequence[TallyItem] = (),
    *,
    period_labels: tuple[str, str, str] = ("earlier", "prior", "last"),
) -> ChartData:
    """The chart a build failure still renders: tally only, all else missing."""
    return ChartData(
        period_labels=period_labels,
        screen=(),
        pushes=None,
        tally=tuple(tally),
        missing=(_SCREEN_MISSING, _PUSHES_MISSING),
    )


@dataclass(frozen=True)
class CardBuild:
    """One built card, its ledger rows, and codes for the ledger detail."""

    card: Card | None
    sides: tuple[SlotCardRow, ...]
    detail_codes: tuple[str, ...]


def _action_commitment(result: ProposalResult | StoredResult) -> str | None:
    if result.briefing is None:
        return None
    for section in result.briefing.sections:
        if section.type == "actions" and section.actions:
            return section.actions[0].commitment_id
    return None


def build_card(
    *,
    slot: datetime,
    subject_id: str,
    as_of: datetime,
    bucket: str | None,
    results: Sequence[ProposalResult | StoredResult],
    commitments_by_id: Mapping[str, Commitment],
    picks: Mapping[str, tuple[str | None, str | None]],
    since_line: str | None,
) -> CardBuild:
    """Build one card from shown results, plus the per-side ledger rows.

    A proposal side carries ``reason_codes=()``; the result's codes move to
    ``detail_codes``. A lone proposal is labelled A whichever profile shows.
    Two noops build no card.
    """
    shown = [result for result in results if result.kind != "noop"]
    if not shown:
        return CardBuild(card=None, sides=(), detail_codes=())
    for result in shown:
        if result.profile_id not in ("builder", "disconnect"):
            raise ValueError(f"unknown profile {result.profile_id!r}")
    ordered = sorted(shown, key=lambda item: item.profile_id != "builder")
    survivors: list[ProposalResult | StoredResult] = []
    codes: list[str] = []
    for result in ordered:
        if result.kind != "proposal":
            survivors.append(result)
            continue
        action_id = _action_commitment(result)
        shown_commitment = commitments_by_id.get(action_id) if action_id else None
        if shown_commitment is None or result.briefing is None:
            codes.append("COMMITMENT_GONE")
            continue
        survivors.append(result)
    if not survivors:
        return CardBuild(card=None, sides=(), detail_codes=tuple(codes))
    letters: dict[str, Letter] = (
        {survivors[0].profile_id: "A"}
        if len(survivors) == 1
        else {
            result.profile_id: letter
            for result, letter in zip(survivors, _AB, strict=True)
        }
    )
    sides: list[CardProposal] = []
    prose: list[tuple[str, str, Briefing]] = []
    rows: list[SlotCardRow] = []
    for result in survivors:
        letter = letters[result.profile_id]
        display = _display_name(result.profile_id)
        hour = result.hour
        assert hour is not None
        if result.kind == "proposal":
            assert result.briefing is not None
            action_id = _action_commitment(result)
            shown_commitment = commitments_by_id.get(action_id) if action_id else None
            assert shown_commitment is not None
            codes.extend(result.reason_codes)
            sides.append(
                CardProposal(
                    letter=letter,
                    kind="proposal",
                    profile=display,
                    title=shown_commitment.title,
                    start=hour.start,
                    end=hour.end,
                )
            )
            prose.append((letter, display, result.briefing))
            commitment_id = shown_commitment.id
        else:
            assert result.fallback is not None
            sides.append(
                CardProposal(
                    letter=letter,
                    kind="fallback",
                    reason_codes=tuple(result.reason_codes),
                    profile=display,
                    title=result.fallback.commitment.title,
                    start=hour.start,
                    end=hour.end,
                )
            )
            commitment_id = result.fallback.commitment.id
        pick, alternative = picks.get(result.profile_id, (None, None))
        if pick is not None:
            LearnerProposal(
                label=letter,
                profile_id=cast("Literal['builder', 'disconnect']", result.profile_id),
                commitment_id=commitment_id,
                policy_pick=pick,
                policy_alternative=alternative,
            )
        rows.append(
            SlotCardRow(
                card_id="",
                letter=letter,
                slot=slot,
                subject_id=subject_id,
                as_of=as_of,
                bucket=bucket,
                profile_id=result.profile_id,
                commitment_id=commitment_id,
                kind=result.kind,
                policy_pick=pick,
                policy_alternative=alternative,
            )
        )
    if not sides:
        return CardBuild(card=None, sides=(), detail_codes=tuple(codes))
    has_proposal = any(side.kind == "proposal" for side in sides)
    if has_proposal and since_line is None:
        raise ValueError("a proposal side needs a since line")
    card = Card(
        slot=slot,
        since_line=since_line if has_proposal else None,
        proposals=tuple(sides),
        statements=build_statements(sorted(prose, key=lambda item: item[0])),
    )
    return CardBuild(
        card=card,
        sides=tuple(
            SlotCardRow(
                card_id=card.card_id,
                letter=row.letter,
                slot=row.slot,
                subject_id=row.subject_id,
                as_of=row.as_of,
                bucket=row.bucket,
                profile_id=row.profile_id,
                commitment_id=row.commitment_id,
                kind=row.kind,
                policy_pick=row.policy_pick,
                policy_alternative=row.policy_alternative,
            )
            for row in rows
        ),
        detail_codes=tuple(codes),
    )
