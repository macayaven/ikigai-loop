"""Slice B: the metrics report (BD1-BD8).

Reads a store copy (SD2 shape, duplicated from Slice A so neither slice
depends on the other) and prints the submission report as counts, rates
with their ``n``, codes and model ids. Never prints claim text, fact
text, commitment titles or commitment ids.

Sections: BD2 run scope and the slot-path/re-proposal split by proposal
key, BD3 R1 as two key-filtered blocks plus delivered cards/sides from
the delivery join and fact disputes, BD4 identities with both sides
gating the exit code, BD5 R7 follow-through per evidence class, BD6 the
before/during table from independent evidence, BD7 R8 learner scoring,
policy diff, forecast split and recovery table, BD8 PREREG bindings.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from framework.briefing.schemas import Commitment
from framework.cycle.card_build import chain_groups
from framework.cycle.orchestrator import classify_slot, replaces_map
from framework.cycle.slot_ledger import SlotLedger, parse_detail
from framework.glimmer.labels import apply_labels
from framework.glimmer.metrics import (
    floor_hour,
    is_opened_pr,
    select_winners,
)
from framework.learner.policy import initial_state, policy_diff, state_json
from framework.learner.scoring import score_report
from framework.learner.simulate import recover_table
from framework.rater.delivery import MADRID, delivered_cards, run_slots
from framework.schemas.events import AppTapData, Event
from framework.store.proposal_store import FirstDraftReport, ProposalStore
from framework.store.store import EventStore
from framework.telegram.models import Card
from framework.voice.state import standing_chain_ruling

RUN_SLOTS = run_slots()

THIS_REPO = "macayaven/ikigai-loop"
NUMBERS_CUT = datetime(2026, 11, 4, 18, 0, tzinfo=MADRID)
FORECAST: dict[str, tuple[int, int]] = {
    "15:30": (8, 10),
    "20:30": (5, 10),
    "22:30": (0, 10),
}
RECOVERY_N_CARDS = (2, 3, 7, 13)
RECOVERY_LABELS = {
    2: "per_bucket",
    3: "per_bucket",
    7: "pooled_constant_preference",
    13: "optimistic",
}
RECOVERY_SEED = 16
RECOVERY_N_SIMS = 200
RECOVERY_ASSUMPTION = (
    "Recovery assumes each ruling is an independent draw"
    " from a stationary Bernoulli preference."
)
SCORING_NOTE = (
    "Mean Brier is primary for learner, always-half and pooled-rate;"
    " log loss is secondary for all four predictors; the hard-majority"
    " predictor's log loss depends on its clipping to [0.01, 0.99]."
)
GITHUB_COMPLETED_NOTE = "consistent with completion"
NO_SCREEN_COMPLETED_NOTE = "no activity recorded on observed devices (iphone, mac)"
DEVICES = ("mac", "iphone")
TWO_GOAL_TIMES = ("15:30", "20:30", "22:30")

_FORECAST_ROW_RE = re.compile(
    r"^\|\s*(\d{2}:\d{2})\s*\|\s*(\d+)\s+of\s+(\d+)\s*\|", re.MULTILINE
)


def forecast_from_prereg(text: str) -> dict[str, tuple[int, int]]:
    """Parse the "My ruling split" table into {slot time: (builder, n)}."""
    return {
        hour: (int(builder), int(n))
        for hour, builder, n in _FORECAST_ROW_RE.findall(text)
    }


def copy_store(db_path: Path) -> tuple[Path, Sequence[Path]]:
    """Copy the live DB through a read-only handle, sqlite backup API."""
    if not db_path.exists() or not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    fd, name = tempfile.mkstemp(prefix="metrics-copy-", suffix=".db")
    os.close(fd)
    copy = Path(name)
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return copy, (
        copy,
        copy.with_name(copy.name + "-wal"),
        copy.with_name(copy.name + "-shm"),
    )


def remove_copy(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_all(conn: sqlite3.Connection, query: str) -> list[tuple[Any, ...]]:
    try:
        return [tuple(row) for row in conn.execute(query).fetchall()]
    except sqlite3.OperationalError:
        return []


def _parse_stamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        return None
    return moment


@dataclass
class ScopeSplit:
    """BD2: the run scope and the slot-path/re-proposal split by key."""

    forced: int = 0
    unpinned: int = 0
    outside: int = 0
    slot_keys: frozenset[str] = frozenset()
    reproposal_keys: frozenset[str] = frozenset()
    voice_corrected: int = 0


def scope_split(copy: Path) -> ScopeSplit:
    """Only the 13 run slots count; forced, unpinned and outside apart.

    The slot path is the earliest ``proposal_results`` row per (run slot,
    profile) by ``rowid``; every other row at a run slot is a re-proposal.
    ``proposal_results`` carries no origin marker, so a ``--fresh`` rerun
    at a run slot is indistinguishable from a voice re-proposal there
    (plan C4); the voice count beside it bounds the ambiguity.
    """
    run = set(RUN_SLOTS)
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        ledger_rows = _read_all(conn, "SELECT slot, step, detail FROM slot_ledger")
        result_rows = _read_all(
            conn, "SELECT rowid, proposal_key, slot, profile_id FROM proposal_results"
        )
        voice_rows = _read_all(conn, "SELECT new_card_id, slot FROM voice_notes")
    finally:
        conn.close()
    forced: set[datetime] = set()
    ledger_slots: set[datetime] = set()
    for stamp, step, detail in ledger_rows:
        moment = _parse_stamp(stamp)
        if moment is None:
            continue
        ledger_slots.add(moment)
        if step == "start" and parse_detail(str(detail)).get("forced") == "1":
            forced.add(moment)
    # Ledger stamps are UTC; classify the Madrid rendering of the instant.
    unpinned = {
        slot for slot in ledger_slots if classify_slot(slot.astimezone(MADRID)) != "ok"
    }
    outside = {slot for slot in ledger_slots if slot not in run} - forced - unpinned
    # Priority: a forced run slot counts as forced, not as outside/unpinned.
    unpinned -= forced
    excluded = forced | unpinned | outside
    earliest: dict[tuple[datetime, str], tuple[int, str]] = {}
    for rowid, key, stamp, profile in result_rows:
        moment = _parse_stamp(stamp)
        if moment is None or moment not in run or moment in excluded:
            continue
        slot_key = (moment, str(profile))
        if slot_key not in earliest or int(rowid) < earliest[slot_key][0]:
            earliest[slot_key] = (int(rowid), str(key))
    slot_keys = frozenset(key for _, key in earliest.values())
    usable = {
        str(key)
        for _, key, stamp, _ in result_rows
        if _parse_stamp(stamp) in run and _parse_stamp(stamp) not in excluded
    }
    voice = 0
    seen_cards: set[str] = set()
    for card_id, stamp in voice_rows:
        if card_id is None or card_id in seen_cards:
            continue
        moment = _parse_stamp(stamp)
        if moment is not None and moment in run:
            seen_cards.add(str(card_id))
    voice = len(seen_cards)
    return ScopeSplit(
        forced=len(forced),
        unpinned=len(unpinned),
        outside=len(outside),
        slot_keys=slot_keys,
        reproposal_keys=frozenset(usable - set(slot_keys)),
        voice_corrected=voice,
    )


def r1_block_fields(
    report: FirstDraftReport, prefix: str, fields: dict[str, str]
) -> None:
    """One R1 block: per-model grains, by-code lines, noop reasons, totals."""
    for stats in report.models:
        base = f"{prefix}.{stats.model}.{stats.effort}"
        fields[f"{base}.first_drafts"] = str(stats.first_drafts)
        fields[f"{base}.first_passed"] = str(stats.first_draft_passed)
        fields[f"{base}.first_failed"] = str(stats.first_draft_failed)
        fields[f"{base}.unavailable"] = str(stats.unavailable)
        fields[f"{base}.retries"] = str(stats.retries)
        fields[f"{base}.retry_passed"] = str(stats.retry_passed)
        fields[f"{base}.fallbacks"] = str(stats.fallbacks)
        fields[f"{base}.noops"] = str(stats.noops)
    for code_stats in report.codes:
        fields[
            f"{prefix}.code.{code_stats.model}.{code_stats.effort}.{code_stats.code}"
        ] = str(code_stats.drafts)
    for reason, count in report.noops_by_reason:
        fields[f"{prefix}.noop_reason.{reason}"] = str(count)
    fields[f"{prefix}.results"] = str(report.results)
    fields[f"{prefix}.proposals"] = str(report.proposals)
    fields[f"{prefix}.fallbacks"] = str(report.fallbacks)
    fields[f"{prefix}.noops"] = str(report.noops)


def delivered_fields(copy: Path, fields: dict[str, str]) -> None:
    """Delivered cards and sides by kind, from the AD1 join (BD3)."""
    run = set(RUN_SLOTS)
    join = delivered_cards(copy)
    in_run = sorted(
        card_id for card_id in join.delivered if join.slots.get(card_id) in run
    )
    fields["delivered.cards"] = str(len(in_run))
    fields["delivered.cards_outside_run"] = str(
        join.counts.get("delivered_cards_outside_run", 0)
    )
    if not in_run:
        fields["delivered.sides"] = "0"
        fields["delivered.sides_proposal"] = "0"
        fields["delivered.sides_fallback"] = "0"
        return
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        kinds = [
            str(kind)
            for (kind,) in conn.execute(
                "SELECT kind FROM slot_cards WHERE card_id IN ({})".format(
                    ", ".join(["?"] * len(in_run))
                ),
                in_run,
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        kinds = []
    finally:
        conn.close()
    fields["delivered.sides"] = str(len(kinds))
    fields["delivered.sides_proposal"] = str(sum(1 for k in kinds if k == "proposal"))
    fields["delivered.sides_fallback"] = str(sum(1 for k in kinds if k == "fallback"))


def dispute_fields(copy: Path, fields: dict[str, str]) -> None:
    """Fact disputes from app.fact_dispute events, with distinct notes."""
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT data FROM events WHERE type = 'app.fact_dispute'"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()
    notes: set[str] = set()
    for (raw,) in rows:
        try:
            notes.add(str(json.loads(str(raw)).get("message_id")))
        except (ValueError, AttributeError):
            continue
    fields["disputes.fact_dispute_events"] = str(len(rows))
    fields["disputes.fact_dispute_notes"] = str(len(notes))


@dataclass
class Identity:
    """One BD4 cross-check with both sides and its verdict."""

    name: str
    left: int
    right: int
    ok: bool


@dataclass
class IdentityInputs:
    """Attempts and results read raw from the copy for BD4."""

    attempts: tuple[tuple[str, str, str, int, int, str, int], ...] = ()
    kinds: dict[str, str] = field(default_factory=dict[str, str])


def identity_inputs(copy: Path) -> IdentityInputs:
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        attempts = tuple(
            (
                str(key),
                str(model),
                str(effort),
                int(blocked),
                int(parsed),
                str(codes),
                int(number),
            )
            for key, model, effort, blocked, parsed, codes, number in _read_all(
                conn,
                "SELECT proposal_key, model_requested, effort, blocked,"
                " parsed_ok, gate_codes, attempt FROM proposal_attempts",
            )
        )
        kinds: dict[str, str] = {
            str(key): str(kind)
            for key, kind in _read_all(
                conn, "SELECT proposal_key, kind FROM proposal_results"
            )
        }
    finally:
        conn.close()
    return IdentityInputs(attempts=attempts, kinds=kinds)


def check_identities(data: IdentityInputs) -> tuple[list[Identity], dict[str, int]]:
    """BD4: the cross-checks proving the SQL grains describe propose."""
    first: dict[str, tuple[str, str, int, int, str]] = {}
    attempts_per_key: dict[str, int] = {}
    second_unavailable = 0
    second_blocked = 0
    second_rows: list[tuple[str, str, str]] = []
    for key, model, effort, blocked, parsed, codes, number in data.attempts:
        attempts_per_key[key] = attempts_per_key.get(key, 0) + 1
        if number == 1 and key not in first:
            first[key] = (model, effort, blocked, parsed, codes)
        if number == 2:
            second_rows.append((key, model, effort))
            if "MODEL_UNAVAILABLE" in codes:
                second_unavailable += 1
            if blocked == 1:
                second_blocked += 1
    per: dict[tuple[str, str], dict[str, int]] = {}

    def _entry(model: str, effort: str) -> dict[str, int]:
        return per.setdefault(
            (model, effort),
            {
                "reached": 0,
                "passed": 0,
                "failed": 0,
                "retries": 0,
                "retry_passed": 0,
            },
        )

    for key, (model, effort, blocked, parsed, codes) in first.items():
        entry = _entry(model, effort)
        if blocked == 0 and "MODEL_UNAVAILABLE" not in codes:
            entry["reached"] += 1
            if parsed == 1 and codes == "[]":
                entry["passed"] += 1
            else:
                entry["failed"] += 1
    for key, model, effort in second_rows:
        entry = _entry(model, effort)
        entry["retries"] += 1
        if data.kinds.get(key) == "proposal":
            entry["retry_passed"] += 1
    identities: list[Identity] = []
    for (model, effort), entry in sorted(per.items()):
        identities.append(
            Identity(
                f"retries_eq_failed.{model}.{effort}",
                entry["retries"],
                entry["failed"],
                entry["retries"] == entry["failed"],
            )
        )
        identities.append(
            Identity(
                f"passed_plus_failed_eq_reached.{model}.{effort}",
                entry["passed"] + entry["failed"],
                entry["reached"],
                entry["passed"] + entry["failed"] == entry["reached"],
            )
        )
    total_retries = sum(entry["retries"] for entry in per.values())
    total_retry_passed = sum(entry["retry_passed"] for entry in per.values())
    fell_back = total_retries - total_retry_passed - second_unavailable - second_blocked
    identities.append(
        Identity(
            "retry_passed_le_retries",
            total_retry_passed,
            total_retries,
            total_retry_passed <= total_retries,
        )
    )
    identities.append(
        Identity(
            "retry_partition",
            total_retries,
            total_retry_passed + fell_back + second_unavailable + second_blocked,
            total_retries
            == total_retry_passed + fell_back + second_unavailable + second_blocked
            and fell_back >= 0,
        )
    )
    deepest = max(attempts_per_key.values(), default=0)
    identities.append(Identity("attempts_per_key_le_2", deepest, 2, deepest <= 2))
    model_fallbacks = sum(
        1 for key, kind in data.kinds.items() if kind == "fallback" and key in first
    )
    fallbacks = sum(1 for kind in data.kinds.values() if kind == "fallback")
    identities.append(
        Identity(
            "fallbacks_cover_attemptless",
            fallbacks,
            model_fallbacks,
            fallbacks >= model_fallbacks,
        )
    )
    model_noops = sum(
        1 for key, kind in data.kinds.items() if kind == "noop" and key in first
    )
    noops = sum(1 for kind in data.kinds.values() if kind == "noop")
    identities.append(
        Identity("noops_cover_attemptless", noops, model_noops, noops >= model_noops)
    )
    counts = {
        "retry.passed": total_retry_passed,
        "retry.fell_back": fell_back,
        "retry.unavailable": second_unavailable,
        "retry.blocked": second_blocked,
        "fallbacks.without_attempt1": fallbacks - model_fallbacks,
        "noops.without_attempt1": noops - model_noops,
    }
    return identities, counts


@dataclass
class ChainVerdict:
    """One accepted chain: the standing card, its ruling and its slot."""

    card_id: str
    target: str
    slot: datetime
    commitment_id: str | None
    hour_start: datetime | None
    hour_end: datetime | None


def _read_events(copy: Path, subject_id: str, end: datetime) -> list[Event]:
    """Every event for one subject up to ``end``, through the real reader."""
    store = EventStore(db_path=copy)
    try:
        return store.events_between(subject_id, datetime(2026, 1, 1, tzinfo=UTC), end)
    finally:
        store.close()


def _cut_winners(events: Sequence[Event], cutoff: datetime) -> tuple[Event, ...]:
    """Winners over rows collected at or before the evidence cut."""
    return select_winners([e for e in events if e.collected_at <= cutoff])


def _stored_card(copy: Path, card_id: str) -> Card | None:
    """The standing card's stored body: payload first, telegram copy after."""
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT card_json FROM slot_card_payloads WHERE card_id = ?",
                (card_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        raw = [str(row[0]) for row in rows]
        if not raw:
            try:
                rows = conn.execute(
                    "SELECT card_json FROM telegram_cards WHERE card_id = ?",
                    (card_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            raw = [str(row[0]) for row in rows]
    finally:
        conn.close()
    for text in raw:
        try:
            return Card.model_validate_json(text)
        except ValueError:
            continue
    return None


def accepted_chains(
    copy: Path, events: Sequence[Event]
) -> tuple[list[ChainVerdict], dict[str, dict[str, str]]]:
    """BD5 acceptance: one standing ruling per replaced-card chain.

    Returns the accepted chains plus, per card id, its letter rows keyed
    by letter for the commitment and hour lookups.
    """
    ledger = SlotLedger(copy)
    card_rows = ledger.all_slot_cards()
    run = set(RUN_SLOTS)
    ordered_ids = list(dict.fromkeys(row.card_id for row in card_rows))
    groups = chain_groups(ordered_ids, replaces_map(copy, card_rows))
    rows_by_card: dict[str, dict[str, str]] = {}
    slot_by_card: dict[str, datetime] = {}
    for row in card_rows:
        rows_by_card.setdefault(row.card_id, {})[row.letter] = row.commitment_id
        slot_by_card.setdefault(row.card_id, row.slot)
    chains: list[ChainVerdict] = []
    for members in groups.values():
        standing = standing_chain_ruling(events, members)
        if standing is None:
            continue
        standing_card, target = standing
        if target not in ("A", "B"):
            continue
        slot = slot_by_card.get(standing_card)
        if slot is None or slot not in run:
            continue
        stored = _stored_card(copy, standing_card)
        hour: tuple[datetime, datetime] | None = None
        if stored is not None:
            for side in stored.proposals:
                if side.letter == target:
                    hour = (side.start, side.end)
        chains.append(
            ChainVerdict(
                card_id=standing_card,
                target=target,
                slot=slot,
                commitment_id=rows_by_card.get(standing_card, {}).get(target),
                hour_start=hour[0] if hour is not None else None,
                hour_end=hour[1] if hour is not None else None,
            )
        )
    return chains, rows_by_card


def _clock_hours(start: datetime, end: datetime) -> list[datetime]:
    """Every UTC clock hour overlapping ``[start, end)``."""
    first = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hours: list[datetime] = []
    hour = first
    while hour < end:
        if hour + timedelta(hours=1) > start:
            hours.append(hour)
        hour += timedelta(hours=1)
    return hours


def _screen_minutes(
    winners: Sequence[Event],
) -> tuple[dict[str, dict[datetime, float]], dict[str, datetime]]:
    """Per-device per-clock-hour minutes, plus each device's first hour."""
    minutes: dict[str, dict[datetime, float]] = {}
    first: dict[str, datetime] = {}
    for event in winners:
        if event.type != "screen.hour":
            continue
        device = str(getattr(event.data, "device", ""))
        if device not in DEVICES:
            continue
        hour = event.time.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        total = float(sum(getattr(event.data, "minutes_by_category", {}).values()))
        minutes.setdefault(device, {})[hour] = (
            minutes.setdefault(device, {}).get(hour, 0.0) + total
        )
        if device not in first or hour < first[device]:
            first[device] = hour
    return minutes, first


def _observed(
    minutes: dict[str, dict[datetime, float]],
    first: dict[str, datetime],
    device: str,
    hour: datetime,
) -> bool:
    """BD5's observed rule: alive at the hour and alive after it."""
    start = first.get(device)
    if start is None or hour < start:
        return False
    return any(later > hour for later in minutes.get(device, {}))


def _github_verdict(
    winners: Sequence[Event],
    start: datetime,
    end: datetime,
    cutoff: datetime,
) -> tuple[str, str | None]:
    """Completed/unknown/not_completed for one github_push commitment."""
    window_end = end + timedelta(hours=2)
    if window_end > cutoff:
        return ("unknown", "right_censored")
    for event in winners:
        if event.type != "github.push":
            continue
        if getattr(event.data, "repo", "") == THIS_REPO:
            continue
        if start <= event.time < window_end:
            return ("completed", None)
    for event in winners:
        if not is_opened_pr(event):
            continue
        if getattr(event.data, "repo", "") == THIS_REPO:
            continue
        if start <= event.time < window_end:
            return ("unknown", "branch_push_possible")
    return ("not_completed", None)


def _screen_categories(
    winners: Sequence[Event],
) -> dict[tuple[str, datetime], dict[str, float]]:
    """Per-device per-clock-hour minutes by category."""
    out: dict[tuple[str, datetime], dict[str, float]] = {}
    for event in winners:
        if event.type != "screen.hour":
            continue
        device = str(getattr(event.data, "device", ""))
        if device not in DEVICES:
            continue
        hour = event.time.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        bucket = out.setdefault((device, hour), {})
        for category, value in getattr(event.data, "minutes_by_category", {}).items():
            bucket[str(category)] = bucket.get(str(category), 0.0) + float(value)
    return out


def _screen_verdict(
    winners: Sequence[Event],
    minutes: dict[str, dict[datetime, float]],
    first: dict[str, datetime],
    start: datetime,
    end: datetime,
    cutoff: datetime,
) -> tuple[str, str | None, bool]:
    """The no_screen verdict, plus whether only system minutes failed it."""
    if end > cutoff:
        return ("unknown", "right_censored", False)
    hours = _clock_hours(start, end)
    by_category = _screen_categories(winners)
    seen: dict[str, float] = {}
    for device in DEVICES:
        for hour in hours:
            for category, value in by_category.get((device, hour), {}).items():
                if value > 0.0:
                    seen[category] = seen.get(category, 0.0) + value
    if seen:
        only_system = all(category == "system" for category in seen)
        return ("not_completed", None, only_system)
    for device in DEVICES:
        for hour in hours:
            if not _observed(minutes, first, device, hour):
                return ("unknown", "device_unobserved", False)
    return ("completed", None, False)


def _calendar_verdict(
    winners: Sequence[Event],
    labels: Sequence[Event],
    start: datetime,
    end: datetime,
    cutoff: datetime,
    tag: str | None,
) -> tuple[str, str | None]:
    """Completed iff an active tagged block overlaps the shown hour."""
    if end > cutoff:
        return ("unknown", "right_censored")
    if tag is None:
        return ("not_completed", None)
    rows = [e for e in winners if e.type.startswith("calendar.event.")]
    effective = apply_labels(rows, [e for e in labels if e.type == "calendar.label"])
    for event in effective:
        if event.type == "calendar.event.cancelled":
            continue
        if tag not in list(getattr(event.data, "tags", []) or []):
            continue
        row_start = getattr(event.data, "start", None)
        row_end = getattr(event.data, "end", None)
        if row_start is None or row_end is None:
            continue
        if row_start < end and row_end > start:
            return ("completed", None)
    return ("not_completed", None)


def r7_fields(
    copy: Path,
    events: Sequence[Event],
    commitments: tuple[Commitment, ...],
    cutoff: datetime,
    fields: dict[str, str],
) -> None:
    """BD5: acceptance through chains, completion per evidence class."""
    winners = _cut_winners(events, cutoff)
    labels = [
        e for e in events if e.type == "calendar.label" and e.collected_at <= cutoff
    ]
    minutes, first = _screen_minutes(winners)
    by_id = {item.id: item for item in commitments}
    chains, _ = accepted_chains(copy, events)
    classes = ("github_push", "no_screen", "calendar_tag", "tap")
    totals: dict[str, Counter[str]] = {name: Counter() for name in classes}
    reasons: dict[str, Counter[str]] = {name: Counter() for name in classes}
    system_only = 0
    commitment_unknown = 0
    hour_unknown = 0
    for chain in chains:
        commitment = by_id.get(chain.commitment_id or "")
        if commitment is None:
            commitment_unknown += 1
            continue
        if chain.hour_start is None or chain.hour_end is None:
            hour_unknown += 1
            continue
        evidence = commitment.evidence
        totals[evidence]["accepted"] += 1
        if evidence == "tap":
            continue
        if evidence == "github_push":
            verdict, reason = _github_verdict(
                winners, chain.hour_start, chain.hour_end, cutoff
            )
        elif evidence == "no_screen":
            verdict, reason, only_system = _screen_verdict(
                winners, minutes, first, chain.hour_start, chain.hour_end, cutoff
            )
            if only_system and verdict == "not_completed":
                system_only += 1
        else:
            verdict, reason = _calendar_verdict(
                winners,
                labels,
                chain.hour_start,
                chain.hour_end,
                cutoff,
                commitment.tag,
            )
        totals[evidence][verdict] += 1
        if reason is not None:
            reasons[evidence][reason] += 1
    for name in classes:
        for verdict in ("accepted", "completed", "not_completed", "unknown"):
            fields[f"r7.{name}.{verdict}"] = str(totals[name][verdict])
        for reason, count in sorted(reasons[name].items()):
            fields[f"r7.{name}.unknown.{reason}"] = str(count)
    fields["r7.github_push.completed_note"] = GITHUB_COMPLETED_NOTE
    fields["r7.no_screen.completed_note"] = NO_SCREEN_COMPLETED_NOTE
    fields["r7.no_screen.system_only_hours"] = str(system_only)
    fields["r7.accepted_commitment_unknown"] = str(commitment_unknown)
    fields["r7.accepted_hour_unknown"] = str(hour_unknown)


def beforeduring_fields(
    events: Sequence[Event],
    cutoff: datetime,
    end: datetime,
    fields: dict[str, str],
) -> None:
    """BD6: independent evidence per 24 h period, unknown never screen-free."""
    winners = _cut_winners(events, cutoff)
    screen = [e for e in winners if e.type == "screen.hour"]
    pushes = [e for e in winners if e.type == "github.push"]
    evidence_times = [e.time for e in (*screen, *pushes)]
    anchor = floor_hour(RUN_SLOTS[0])
    day = timedelta(hours=24)
    if evidence_times:
        earliest = min(evidence_times)
        back = int((earliest - anchor).total_seconds() // day.total_seconds())
        if (earliest - anchor) < back * day:
            back -= 1
        first_start = anchor + back * day
    else:
        first_start = anchor
    starts: list[datetime] = []
    moment = first_start
    while moment < end:
        starts.append(moment)
        moment += day
    if not starts:
        starts = [anchor]
    minutes, first = _screen_minutes(winners)
    labels: list[str] = []
    for period_start in starts:
        step = int((period_start - anchor).total_seconds() // day.total_seconds())
        label = f"during_{step}" if step >= 0 else f"before_{-step}"
        labels.append(label)
        clip = min(period_start + day, end)
        covered = max(0, int((clip - period_start).total_seconds() // 3600))
        fields[f"beforeduring.{label}.hours"] = str(covered)
        other = this = 0
        for event in pushes:
            if period_start <= event.time < clip:
                if getattr(event.data, "repo", "") == THIS_REPO:
                    this += 1
                else:
                    other += 1
        fields[f"beforeduring.{label}.pushes_other_repos"] = str(other)
        fields[f"beforeduring.{label}.pushes_this_repo"] = str(this)
        free = activity = unknown = system_only = 0
        hour = period_start
        while hour < clip:
            if _period_hour_activity(minutes, hour):
                activity += 1
            elif _period_hour_free(minutes, first, hour):
                free += 1
            else:
                unknown += 1
            if _period_hour_system_only(winners, hour):
                system_only += 1
            hour += timedelta(hours=1)
        fields[f"beforeduring.{label}.screen_free_clock_hours"] = str(free)
        fields[f"beforeduring.{label}.screen_activity_hours"] = str(activity)
        fields[f"beforeduring.{label}.screen_unknown_hours"] = str(unknown)
        fields[f"beforeduring.{label}.screen_system_only_hours"] = str(system_only)
    fields["beforeduring.periods"] = ",".join(labels)
    for device in DEVICES:
        moment = first.get(device)
        fields[f"beforeduring.first_observed_{device}"] = (
            moment.isoformat() if moment is not None else "none"
        )
    versions: Counter[str] = Counter()
    for event in screen:
        versions[str(event.collector_version)] += 1
    for version, count in sorted(versions.items()):
        fields[f"beforeduring.screen_rows_by_collector_version.{version}"] = str(count)


def _period_hour_activity(
    minutes: dict[str, dict[datetime, float]], hour: datetime
) -> bool:
    """True when any device has minutes in one UTC clock hour."""
    utc = hour.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return any(minutes.get(device, {}).get(utc, 0.0) > 0.0 for device in DEVICES)


def _period_hour_free(
    minutes: dict[str, dict[datetime, float]],
    first: dict[str, datetime],
    hour: datetime,
) -> bool:
    """Screen-free: every device observed and none with minutes."""
    utc = hour.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    for device in DEVICES:
        if minutes.get(device, {}).get(utc, 0.0) > 0.0:
            return False
        if not _observed(minutes, first, device, utc):
            return False
    return True


def _period_hour_system_only(winners: Sequence[Event], hour: datetime) -> bool:
    """True when the hour's only minutes are in the system category."""
    utc = hour.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    seen = False
    for event in winners:
        if event.type != "screen.hour":
            continue
        if event.time.astimezone(UTC).replace(minute=0, second=0, microsecond=0) != utc:
            continue
        for category, value in getattr(event.data, "minutes_by_category", {}).items():
            if float(value) <= 0.0:
                continue
            seen = True
            if str(category) != "system":
                return False
    return seen


def _fmt_float(value: float | None) -> str:
    return "none" if value is None else str(value)


def r8_fields(
    copy: Path,
    events: Sequence[Event],
    fields: dict[str, str],
) -> None:
    """BD7: rebuild vs stored, scores, diff, forecast split, recovery."""
    from framework.cycle.orchestrator import rebuild_state

    ledger = SlotLedger(copy)
    card_rows = ledger.all_slot_cards()
    rebuilt, skipped = rebuild_state(events, card_rows, replaces_map(copy, card_rows))
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        try:
            found = conn.execute(
                "SELECT slot, state_json FROM learner_states ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            found = None
    finally:
        conn.close()
    taps = sorted(
        (
            event
            for event in events
            if event.type == "app.tap"
            and event.source == "telegram"
            and isinstance(event.data, AppTapData)
        ),
        key=lambda event: (event.time, event.id),
    )
    if found is None:
        fields["r8.learner_state_mismatch"] = (
            "0" if state_json(rebuilt) == state_json(initial_state()) else "1"
        )
        fields["r8.learner_state_pending_taps"] = str(len(taps))
    else:
        stored_json = str(found[1])
        stored_slot = _parse_stamp(found[0])
        if stored_slot is None:
            fields["r8.learner_state_mismatch"] = (
                "0" if state_json(rebuilt) == stored_json else "1"
            )
            fields["r8.learner_state_pending_taps"] = str(len(taps))
        else:
            # Like with like: the stored state was written at its slot's
            # learner step, before that slot's card existed and before the
            # tap that followed. Rebuild from the slot cards of earlier
            # slots and the taps stored before that step. The step's wall
            # time is not stored, but it falls between the slot's start
            # (whose as_of the start row records) and the slot instant,
            # so every tap prefix ending in that span is tried.
            subset = tuple(row for row in card_rows if row.slot < stored_slot)
            sub_replaces = replaces_map(copy, subset)
            try:
                start_as_of = ledger.latest_start_as_of(stored_slot)
            except (sqlite3.OperationalError, ValueError):
                start_as_of = None
            first = (
                sum(1 for event in taps if event.time <= start_as_of)
                if start_as_of is not None
                else 0
            )
            last = sum(1 for event in taps if event.time <= stored_slot)
            match = False
            for end in range(first, last + 1):
                candidate, _ = rebuild_state(taps[:end], subset, sub_replaces)
                if state_json(candidate) == stored_json:
                    match = True
                    break
            fields["r8.learner_state_mismatch"] = "0" if match else "1"
            fields["r8.learner_state_pending_taps"] = str(
                sum(1 for event in taps if event.time > stored_slot)
            )
    fields["r8.learner_rulings_skipped"] = str(skipped)
    report = score_report(rebuilt)
    fields["r8.scores.n"] = str(report.n)
    fields["r8.scores.learner.brier"] = _fmt_float(report.learner.mean_brier)
    fields["r8.scores.always_half.brier"] = _fmt_float(report.always_half.mean_brier)
    fields["r8.scores.pooled_rate.brier"] = _fmt_float(report.pooled_rate.mean_brier)
    fields["r8.scores.learner.log_loss"] = _fmt_float(report.learner.mean_log_loss)
    fields["r8.scores.always_half.log_loss"] = _fmt_float(
        report.always_half.mean_log_loss
    )
    fields["r8.scores.majority.log_loss"] = _fmt_float(report.majority.mean_log_loss)
    fields["r8.scores.pooled_rate.log_loss"] = _fmt_float(
        report.pooled_rate.mean_log_loss
    )
    fields["r8.scoring_note"] = SCORING_NOTE
    diff_counts: Counter[str] = Counter()
    for change in policy_diff(initial_state(), rebuilt):
        diff_counts[change.path.split(".")[0]] += 1
    for segment in (
        "preference",
        "rulings_seen",
        "duplicates",
        "buckets",
        "commitments",
        "cards",
        "score_log",
        "pick_log",
    ):
        fields[f"r8.policy_diff.{segment}"] = str(diff_counts[segment])
    _forecast_fields(copy, events, fields)
    table = recover_table(RECOVERY_SEED, RECOVERY_N_SIMS, n_cards=RECOVERY_N_CARDS)
    by_label: dict[str, list[int]] = {}
    for cell in table.cells:
        by_label.setdefault(RECOVERY_LABELS[cell.n_cards], []).append(cell.n_cards)
        tag = RECOVERY_LABELS[cell.n_cards]
        base = f"recovery.{tag}.p{cell.true_p}"
        fields[f"{base}.correct_side"] = (
            "none" if cell.correct_side is None else str(cell.correct_side)
        )
        fields[f"{base}.mean_absolute_error"] = str(cell.mean_absolute_error)
        fields[f"{base}.coverage"] = str(cell.coverage)
        fields[f"{base}.mean_interval_width"] = str(cell.mean_interval_width)
    for tag, sizes in sorted(by_label.items()):
        fields[f"recovery.{tag}.n_cards"] = ",".join(
            str(size) for size in sorted(set(sizes))
        )
    fields["recovery.seed"] = str(table.seed)
    fields["recovery.n_sims"] = str(table.n_sims)
    fields["recovery.assumption"] = RECOVERY_ASSUMPTION


def _forecast_fields(
    copy: Path, events: Sequence[Event], fields: dict[str, str]
) -> None:
    """My forecast against my actual split, Neither and untapped apart."""
    for hour, (builder, n) in FORECAST.items():
        fields[f"r8.forecast.{hour}.builder"] = str(builder)
        fields[f"r8.forecast.{hour}.n"] = str(n)
    ledger = SlotLedger(copy)
    card_rows = ledger.all_slot_cards()
    ordered_ids = list(dict.fromkeys(row.card_id for row in card_rows))
    groups = chain_groups(ordered_ids, replaces_map(copy, card_rows))
    kinds: dict[str, list[str]] = {}
    slot_by_card: dict[str, datetime] = {}
    for row in card_rows:
        kinds.setdefault(row.card_id, []).append(row.kind)
        slot_by_card.setdefault(row.card_id, row.slot)
    join = delivered_cards(copy)
    run = set(RUN_SLOTS)
    counts: dict[str, Counter[str]] = {label: Counter() for label in TWO_GOAL_TIMES}
    for members in groups.values():
        standing = standing_chain_ruling(events, members)
        standing_card = standing[0] if standing is not None else members[-1]
        slot = slot_by_card.get(standing_card)
        if slot is None or slot not in run:
            continue
        if standing_card not in join.delivered:
            continue
        member_kinds = kinds.get(standing_card, [])
        if len(member_kinds) != 2:
            continue
        label = slot.astimezone(MADRID).strftime("%H:%M")
        if label not in TWO_GOAL_TIMES:
            continue
        if standing is None:
            counts[label]["untapped"] += 1
        elif standing[1] == "neither":
            counts[label]["neither"] += 1
        elif standing[1] in ("A", "B"):
            profile = _ruled_profile(copy, standing_card, standing[1])
            if profile in ("builder", "disconnect"):
                counts[label][profile] += 1
    for label in TWO_GOAL_TIMES:
        builder = counts[label]["builder"]
        disconnect = counts[label]["disconnect"]
        total = builder + disconnect
        fields[f"r8.actual.{label}.builder"] = str(builder)
        fields[f"r8.actual.{label}.disconnect"] = str(disconnect)
        fields[f"r8.actual.{label}.n"] = str(total)
        fields[f"r8.actual.{label}.builder_rate"] = (
            f"{builder / total:.4f}" if total else "none"
        )
        fields[f"r8.actual.{label}.neither"] = str(counts[label]["neither"])
        fields[f"r8.actual.{label}.untapped"] = str(counts[label]["untapped"])


def _ruled_profile(copy: Path, card_id: str, target: str) -> str | None:
    """The profile id of the ruled side of one stored card."""
    conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT letter, profile_id FROM slot_cards WHERE card_id = ?",
                (card_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()
    for letter, profile in rows:
        if str(letter) == target:
            return str(profile)
    return None


def build_report(
    db: Path,
    *,
    as_of: datetime | None = None,
    subject_id: str,
    commitments: tuple[Commitment, ...],
) -> tuple[int, dict[str, str]]:
    """Assemble the BD1-BD7 sections; exit 1 when an identity fails."""
    if not db.exists() or not db.is_file():
        return 2, {"ok": "0", "reason": "missing_db_file"}
    as_of_eff = as_of if as_of is not None else datetime.now(MADRID)
    cutoff = min(as_of_eff, NUMBERS_CUT)
    copy, garbage = copy_store(db)
    try:
        fields: dict[str, str] = {}
        fields["run.slots"] = str(len(RUN_SLOTS))
        fields["scope.as_of"] = as_of_eff.isoformat()
        fields["scope.evidence_cut"] = cutoff.isoformat()
        split = scope_split(copy)
        fields["scope.slots_forced"] = str(split.forced)
        fields["scope.slots_unpinned"] = str(split.unpinned)
        fields["scope.slots_outside_run"] = str(split.outside)
        fields["scope.reproposal_results"] = str(len(split.reproposal_keys))
        fields["scope.voice_corrected_cards"] = str(split.voice_corrected)
        store = ProposalStore(db_path=copy)
        try:
            r1_block_fields(
                store.first_draft_report(proposal_keys=split.slot_keys),
                "r1.slot",
                fields,
            )
            r1_block_fields(
                store.first_draft_report(proposal_keys=split.reproposal_keys),
                "r1.reproposal",
                fields,
            )
        finally:
            store.close()
        delivered_fields(copy, fields)
        dispute_fields(copy, fields)
        identities, counts = check_identities(identity_inputs(copy))
        for name, value in sorted(counts.items()):
            fields[name] = str(value)
        failed = 0
        for identity in identities:
            fields[f"identity.{identity.name}.left"] = str(identity.left)
            fields[f"identity.{identity.name}.right"] = str(identity.right)
            fields[f"identity.{identity.name}.ok"] = "1" if identity.ok else "0"
            failed += 0 if identity.ok else 1
        events = _read_events(
            copy, subject_id, max(as_of_eff, NUMBERS_CUT) + timedelta(days=1)
        )
        r7_fields(copy, events, commitments, cutoff, fields)
        beforeduring_fields(
            events, cutoff, floor_hour(min(as_of_eff, NUMBERS_CUT)), fields
        )
        r8_fields(copy, events, fields)
        return (1 if failed else 0), fields
    finally:
        remove_copy(garbage)


def render_fields(fields: Mapping[str, str]) -> str:
    return "".join(f"{name}={fields[name]}\n" for name in sorted(fields))
