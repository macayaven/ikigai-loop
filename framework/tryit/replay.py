"""Ticket 21: the replay flow through the real fact, proposal and gate code."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from importlib import resources
from io import BytesIO
from typing import Any

from PIL import Image

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.cycle.card_build import (
    build_card,
    build_chart_data,
    build_tally,
    since_counts,
    since_line,
)
from framework.cycle.slot_ledger import SlotCardRow
from framework.cycle.trace import metric_sources
from framework.glimmer.checks import private_free_text_values
from framework.glimmer.facts import LLMResponse, extract_facts
from framework.glimmer.labels import INTERNAL_ONLY_LABELS
from framework.glimmer.metrics import select_winners
from framework.proposal.core import (
    ModelParams,
    ProposalResult,
    WonderRequest,
    WonderResponse,
    propose,
)
from framework.proposal.hour import allowed_windows, future_busy_intervals, pick_hour
from framework.schemas.core import Fact
from framework.schemas.events import AppTapData, Event
from framework.telegram.chart import render_chart_png
from framework.telegram.models import Card, ChartData, TallyItem
from framework.tryit.models import ClaimTemplate, Recording

PICKS = ("A", "B", "neither")
PERIOD_LABELS = ("synthetic earlier", "synthetic prior", "synthetic last")


class ReplayMismatch(Exception):
    """The recording's story drifted from the real gate's verdicts."""


class _RaisingLlm:
    """LLM stand-in: both model passes are off, so a call is a loud failure."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> LLMResponse:
        self.calls += 1
        raise AssertionError("no model runs in this replay")


class _RecordedClient:
    """Wonder client that returns canned replies in call order."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    @property
    def transport(self) -> str:
        return "recorded"

    @property
    def transport_version(self) -> str | None:
        return "try-021"

    @property
    def harness_rules_file(self) -> bool | None:
        return False

    def complete(self, request: WonderRequest) -> WonderResponse:
        _ = request
        if self.calls >= len(self._texts):
            raise AssertionError("more model calls than canned replies")
        text = self._texts[self.calls]
        self.calls += 1
        return WonderResponse(
            text=text,
            model_reported="recorded",
            latency_ms=0,
            finish_reason="stop",
            prompt_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
            cached_tokens=None,
        )


@dataclass(frozen=True)
class ReplayResult:
    """Everything the output builder prints, sourced from the real run."""

    card: Card
    chart: ChartData
    png: bytes
    width: int
    height: int
    as_of: datetime
    slot: datetime
    hour: TimeInterval
    busy: tuple[TimeInterval, ...]
    events: tuple[Event, ...]
    builder_result: ProposalResult
    disconnect_result: ProposalResult
    planted_codes: tuple[str, ...]
    planted_text: str
    fixed_text: str
    said_value: float
    holds_value: float
    lied_metric: str
    traced_fact: Fact
    traced_metrics: dict[str, float]
    traced_rows: tuple[Event, ...]
    tally_before: tuple[TallyItem, ...]
    tally_after: tuple[TallyItem, ...]
    tap_event: Event
    card_id: str


def earlier_card_rows(
    earlier_taps: tuple[Event, ...],
    *,
    slot: datetime,
    subject_id: str,
    as_of: datetime,
    commitments: tuple[Any, ...],
) -> tuple[SlotCardRow, ...]:
    """One in-memory row per side of each earlier card: A is Builder, B is Disconnect."""
    by_profile = {item.profile_id: item.id for item in commitments}
    rows: list[SlotCardRow] = []
    card_ids = sorted(
        {tap.data.block_id for tap in earlier_taps if isinstance(tap.data, AppTapData)}
    )
    for card_id in card_ids:
        rows.append(
            SlotCardRow(
                card_id=card_id,
                letter="A",
                slot=slot,
                subject_id=subject_id,
                as_of=as_of,
                bucket=None,
                profile_id="builder",
                commitment_id=by_profile.get("builder", ""),
                kind="proposal",
                policy_pick=None,
                policy_alternative=None,
            )
        )
        rows.append(
            SlotCardRow(
                card_id=card_id,
                letter="B",
                slot=slot,
                subject_id=subject_id,
                as_of=as_of,
                bucket=None,
                profile_id="disconnect",
                commitment_id=by_profile.get("disconnect", ""),
                kind="proposal",
                policy_pick=None,
                policy_alternative=None,
            )
        )
    return tuple(rows)


def tap_event_for(
    *, card_id: str, target: str, slot: datetime, subject_id: str
) -> Event:
    """The app.tap the person's pick would store, built in memory, stored nowhere."""
    return Event.model_validate(
        {
            "id": f"tap-{target}",
            "subject_id": subject_id,
            "source": "telegram",
            "type": "app.tap",
            "time": slot.isoformat(),
            "source_id": f"{card_id}:{target}",
            "data": {"type": "app.tap", "block_id": card_id, "target": target},
            "tier": "private",
            "collected_at": slot.isoformat(),
            "collector_version": "tryit-021",
        }
    )


def load_recording() -> Recording:
    """Read the packaged manifest and parse it through the typed models."""
    raw = (resources.files("framework.tryit") / "recording.json").read_bytes()
    return Recording.model_validate(json.loads(raw))


def _find_fact_id(facts: tuple[Fact, ...], template: ClaimTemplate) -> str:
    """Fill a template's coverage marker with the real minted fact id."""
    family = template.fact_family
    member = template.fact_member
    if family == "pushes":
        wanted = "push"
    elif family == "screen_hours":
        wanted = member + " screen hours" if member else "screen hours"
    else:
        wanted = member or family
    hits = [
        fact
        for fact in facts
        if wanted in fact.statement.lower()
        and "prior" in fact.statement.lower()
        and "last" in fact.statement.lower()
    ]
    if len(hits) != 1:
        raise ReplayMismatch("a cited fact drifted from the recording")
    return hits[0].id


def _draft_text(commitment_id: str, claims: list[ClaimTemplate], ids: list[str]) -> str:
    draft: dict[str, Any] = {
        "commitment_id": commitment_id,
        "overall_state": [
            {
                "text": claim.text,
                "fact_ids": [fact_id],
                "metric_refs": list(claim.metric_refs),
            }
            for claim, fact_id in zip(claims, ids, strict=True)
        ],
        "working": [],
        "not_working": [],
    }
    return json.dumps(draft)


def _numbers_in(text: str) -> list[float]:
    return [float(token) for token in re.findall(r"\d+(?:\.\d+)?", text)]


def _context_for(
    facts: tuple[Fact, ...],
    snapshot_values: dict[str, float],
    free: tuple[TimeInterval, ...],
    busy: tuple[TimeInterval, ...],
    limits: ProfileLimits,
    literals: tuple[str, ...],
    eligible: tuple[Any, ...],
) -> GateContext:
    """One goal's gate context, shaped the way run_proposals builds it."""
    return GateContext(
        facts={fact.id: fact for fact in facts},
        metrics=MetricSnapshot(values=dict(snapshot_values)),
        free_intervals=free,
        busy_intervals=busy,
        limits=limits,
        private_terms=(),
        private_terms_available=True,
        forbidden_raw_literals=tuple(literals),
        commitments=tuple(eligible),
        commitments_available=True,
    )


def run_replay(*, pick: str = "A") -> ReplayResult:
    """Run the full replay; raise ReplayMismatch when the story drifted."""
    if pick not in PICKS:
        raise ValueError("unknown choice")
    recording = load_recording()
    subject = recording.subject_id
    as_of = recording.as_of
    slot = recording.slot
    events = sorted(recording.events, key=lambda e: (e.time, e.id))

    llm = _RaisingLlm()
    outcome = extract_facts(
        as_of, subject, events, llm, personal_pass=False, feed_pass=False
    )
    facts = outcome.facts
    snapshot = dict(outcome.snapshot.values)

    limits = ProfileLimits(
        timezone="Europe/Madrid",
        allowed_start=time(13, 0),
        allowed_end=time(23, 30),
    )
    busy = future_busy_intervals(events, as_of=as_of, slot=slot)
    hour = pick_hour(slot, busy, limits)
    if hour is None:
        raise ReplayMismatch("the free hour vanished")
    free = allowed_windows(slot, limits)
    literals = (*private_free_text_values(events), *sorted(INTERNAL_ONLY_LABELS))
    builder_commitments = [
        c for c in recording.commitments if c.profile_id == "builder"
    ]
    disconnect_commitments = [
        c for c in recording.commitments if c.profile_id == "disconnect"
    ]
    builder_context = _context_for(
        facts, snapshot, free, busy, limits, literals, tuple(builder_commitments)
    )
    disconnect_context = _context_for(
        facts, snapshot, free, busy, limits, literals, tuple(disconnect_commitments)
    )
    models = ModelParams(
        first_model="hand-written",
        first_effort="low",
        retry_model="hand-written",
        retry_effort="low",
    )
    planted_ids = [
        _find_fact_id(facts, claim) for claim in recording.builder_planted.overall_state
    ]
    fixed_ids = [
        _find_fact_id(facts, claim) for claim in recording.builder_fixed.overall_state
    ]
    disconnect_ids = [
        _find_fact_id(facts, claim) for claim in recording.disconnect.overall_state
    ]
    client = _RecordedClient(
        [
            _draft_text(
                recording.builder_planted.commitment_id,
                list(recording.builder_planted.overall_state),
                planted_ids,
            ),
            _draft_text(
                recording.builder_fixed.commitment_id,
                list(recording.builder_fixed.overall_state),
                fixed_ids,
            ),
            _draft_text(
                recording.disconnect.commitment_id,
                list(recording.disconnect.overall_state),
                disconnect_ids,
            ),
        ]
    )
    builder_result = propose(
        profile_id="builder",
        subject_id=subject,
        slot=slot,
        as_of=as_of,
        cycle_id=recording.cycle_id,
        run=1,
        hour=hour,
        eligible=tuple(builder_commitments),
        context=builder_context,
        client=client,
        models=models,
        policy="",
        stale_after_s=1_000_000_000.0,
        cycle_as_of=as_of,
        offered={},
    )
    disconnect_result = propose(
        profile_id="disconnect",
        subject_id=subject,
        slot=slot,
        as_of=as_of,
        cycle_id=recording.cycle_id,
        run=1,
        hour=hour,
        eligible=tuple(disconnect_commitments),
        context=disconnect_context,
        client=client,
        models=models,
        policy="",
        stale_after_s=1_000_000_000.0,
        cycle_as_of=as_of,
        offered={},
    )

    if llm.calls != 0:
        raise ReplayMismatch("the replay called a model")
    if len(builder_result.attempts) != 2 or not builder_result.attempts[0].codes:
        raise ReplayMismatch("the planted draft did not fail first")
    if builder_result.attempts[1].codes != ():
        raise ReplayMismatch("the corrected draft did not pass")
    if len(disconnect_result.attempts) != 1 or disconnect_result.attempts[0].codes:
        raise ReplayMismatch("the other goal did not pass first time")
    if builder_result.kind != "proposal" or disconnect_result.kind != "proposal":
        raise ReplayMismatch("a result was not a proposal")
    planted_text = recording.builder_planted.overall_state[0].text
    planted_refs = list(recording.builder_planted.overall_state[0].metric_refs)
    cited_values = [snapshot[ref] for ref in planted_refs if ref in snapshot]
    if len(cited_values) != len(planted_refs):
        raise ReplayMismatch("a cited metric is missing from the snapshot")
    unbacked = [
        token
        for token in _numbers_in(planted_text)
        if all(token != value for value in cited_values)
    ]
    if len(unbacked) != 1:
        raise ReplayMismatch("the planted number is not exactly one unbacked number")
    lied_metric = planted_refs[-1]
    holds = snapshot.get(lied_metric)
    if holds is None or unbacked[0] == holds:
        raise ReplayMismatch("the planted number matches the records")
    said_value = unbacked[0]

    builder_briefing = builder_result.briefing
    disconnect_briefing = disconnect_result.briefing
    if builder_briefing is None or disconnect_briefing is None:
        raise ReplayMismatch("a briefing is missing")
    builder_claims = [
        claim.text for section in builder_briefing.sections for claim in section.claims
    ]
    disconnect_claims = [
        claim.text
        for section in disconnect_briefing.sections
        if section.type == "overall_state"
        for claim in section.claims
    ]
    if not builder_claims or not disconnect_claims:
        raise ReplayMismatch("a briefing carries no claims")
    counts = since_counts(tuple(events), recording.prev_card, as_of)
    line = since_line(recording.prev_card, counts)
    rows_before = earlier_card_rows(
        tuple(recording.earlier_taps),
        slot=slot,
        subject_id=subject,
        as_of=as_of,
        commitments=tuple(recording.commitments),
    )
    tally_before = build_tally(tuple(recording.earlier_taps), rows_before)
    chart = build_chart_data(
        tuple(events), as_of, tally_before, period_labels=PERIOD_LABELS
    )
    png = render_chart_png(chart)
    built = build_card(
        slot=slot,
        subject_id=subject,
        as_of=as_of,
        bucket=None,
        results=[builder_result, disconnect_result],
        commitments_by_id={item.id: item for item in recording.commitments},
        picks={},
        since_line=line,
    )
    if built.card is None:
        raise ReplayMismatch("the card did not build")
    card = built.card
    tap = tap_event_for(
        card_id=card.card_id, target=pick, slot=slot, subject_id=subject
    )
    tally_after = build_tally(
        (*recording.earlier_taps, tap),
        (*rows_before, *built.sides),
    )

    traced_claim = next(
        claim
        for section in builder_briefing.sections
        if section.type == "overall_state"
        for claim in section.claims
    )
    traced_fact = builder_context.facts.get(
        traced_claim.fact_ids[0] if traced_claim.fact_ids else ""
    )
    if traced_fact is None:
        raise ReplayMismatch("the traced fact is unknown")
    traced_metrics = {
        ref.metric_id: snapshot[ref.metric_id] for ref in traced_claim.metric_refs
    }
    winners = select_winners(
        tuple(event for event in events if event.collected_at <= as_of)
    )
    rows: list[Event] = []
    for metric_id in traced_metrics:
        found = metric_sources(metric_id, as_of, winners)
        if found is None:
            raise ReplayMismatch("a traced metric has no rows")
        rows.extend(found)
    rows.sort(key=lambda e: (e.time, e.id))

    planted_codes = tuple(code for code, _ in builder_result.attempts[0].codes)
    width, height = _png_size(png)
    return ReplayResult(
        card=card,
        chart=chart,
        png=png,
        width=width,
        height=height,
        as_of=as_of,
        slot=slot,
        hour=hour,
        busy=busy,
        events=tuple(events),
        builder_result=builder_result,
        disconnect_result=disconnect_result,
        planted_codes=planted_codes,
        planted_text=planted_text,
        fixed_text=recording.builder_fixed.overall_state[0].text,
        said_value=said_value,
        holds_value=holds,
        lied_metric=lied_metric,
        traced_fact=traced_fact,
        traced_metrics=traced_metrics,
        traced_rows=tuple(rows),
        tally_before=tally_before,
        tally_after=tally_after,
        tap_event=tap,
        card_id=card.card_id,
    )


def _png_size(png: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(png)) as image:
        return int(image.size[0]), int(image.size[1])
