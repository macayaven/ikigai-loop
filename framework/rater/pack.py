"""Slice A, AD2-AD4 + AD6 + AD8-AD10: from a store copy to pack and key."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from framework.briefing.context import load_private_terms
from framework.briefing.gate import scan_outbound_text
from framework.briefing.labels import metric_label_binding
from framework.briefing.schemas import Briefing, Claim, MetricRef
from framework.cycle import forbidden_literals_for
from framework.cycle.card_build import build_statements
from framework.proposal.prompt import display_value
from framework.rater import delivery as delivery_mod
from framework.rater.delivery import (
    column_rows,
    delivered_cards,
    inside_git_tree,
    run_slots,
)

_inside_git_tree = inside_git_tree
from framework.rater.page import render_page
from framework.rater.split import split_atomic
from framework.store.fact_store import FactStore
from framework.store.store import EventStore
from framework.telegram.models import Card

MADRID = delivery_mod.MADRID
GENERATED_FROM = "copy"


@dataclass
class AtomicEntry:
    """One rateable atomic claim with its provenance."""

    proposal_key: str
    claim_id: str
    text: str
    fact_ids: tuple[str, ...]
    metric_refs: tuple[MetricRef, ...]
    section_type: str
    atomic_index: int
    fact_statements: tuple[str, ...]
    evidence_lines: tuple[str, ...]
    card_ids: tuple[str, ...]
    slot: datetime
    profile: str
    model: str
    effort: str


@dataclass
class CollectResult:
    """Recovered atomics plus the closed counters."""

    atomics: tuple[AtomicEntry, ...] = ()
    counts: dict[str, int] = field(default_factory=dict[str, int])


@dataclass
class PackRefusal(Exception):
    """A data refusal: exit 1, counts only, no partial files."""

    reason: str
    counts: dict[str, int]


def copy_store(db_path: Path) -> tuple[Path, Sequence[Path]]:
    """Copy the live DB through a read-only handle, sqlite backup API."""
    if not db_path.exists() or not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    fd, name = tempfile.mkstemp(prefix="rater-copy-", suffix=".db")
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


def _load_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    for table in ("slot_card_payloads", "telegram_cards"):
        try:
            row = conn.execute(
                f"SELECT card_json FROM {table} WHERE card_id = ?", (card_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            continue
        if row is not None:
            try:
                return Card.model_validate(json.loads(str(row[0])))
            except ValueError:
                return None
    return None


def _ordered_claims(briefing: Briefing) -> list[tuple[str, Claim]]:
    """Claims in build_statements order with their section types."""
    ordered: list[Claim] = [
        claim for section in briefing.sections for claim in section.claims
    ]
    first = next(
        (
            claim
            for section in briefing.sections
            if section.type == "overall_state"
            for claim in section.claims
        ),
        None,
    )
    if first is not None:
        rest = [claim for claim in ordered if claim.id != first.id]
        ordered = [first, *rest]
    out: list[tuple[str, Claim]] = []
    for claim in ordered[:3]:
        section = next(
            section.type
            for section in briefing.sections
            if any(item.id == claim.id for item in section.claims)
        )
        out.append((section, claim))
    return out


@dataclass
class _Candidate:
    rowid: int
    proposal_key: str
    cycle_id: str
    run: int
    briefing: Briefing
    snapshot: dict[str, Any]


def _snapshot_mapping(raw: Any) -> dict[str, Any]:
    """Parse a stored snapshot; unparseable JSON lacks every metric."""
    if raw is None:
        return {}
    try:
        parsed: Any = json.loads(str(raw))
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw_mapping = cast("dict[Any, Any]", parsed)
    return {str(key): value for key, value in raw_mapping.items()}


def _candidates(
    conn: sqlite3.Connection, slot: datetime, profile_id: str
) -> list[_Candidate]:
    rows = column_rows(
        conn,
        "proposal_results",
        "rowid, proposal_key, cycle_id, run, slot, profile_id, briefing_json, snapshot",
        " WHERE kind = 'proposal'",
    )
    out: list[_Candidate] = []
    for rowid, key, cycle_id, run, stamp, profile, raw, snapshot_raw in rows:
        if str(profile) != profile_id or raw is None:
            continue
        try:
            moment = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if moment != slot:
            continue
        try:
            briefing = Briefing.model_validate(json.loads(str(raw)))
        except ValueError:
            continue
        out.append(
            _Candidate(
                rowid=int(rowid),
                proposal_key=str(key),
                cycle_id=str(cycle_id),
                run=int(run),
                briefing=briefing,
                snapshot=_snapshot_mapping(snapshot_raw),
            )
        )
    out.sort(key=lambda item: item.rowid)
    return out


def _parent_snapshots(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Map each stored briefing id to every snapshot recorded with that id."""
    index: dict[str, list[dict[str, Any]]] = {}
    for _, raw_briefing, raw_snapshot in column_rows(
        conn,
        "proposal_results",
        "rowid, briefing_json, snapshot",
        " WHERE kind = 'proposal'",
    ):
        if raw_briefing is None:
            continue
        try:
            briefing = Briefing.model_validate(json.loads(str(raw_briefing)))
        except ValueError:
            continue
        index.setdefault(briefing.id, []).append(_snapshot_mapping(raw_snapshot))
    return index


def _is_json_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve_since_last(
    metric_id: str,
    change: float,
    source_snapshot: dict[str, Any],
    carriers: list[dict[str, Any]],
) -> tuple[Any, Any] | None:
    """Resolve (previous, this) under the delta arithmetic, exactly or not at all."""
    this_value = source_snapshot.get(metric_id)
    if not _is_json_number(this_value):
        return None
    if not carriers:
        return None
    previous_values = [carrier.get(metric_id) for carrier in carriers]
    if any(not _is_json_number(value) for value in previous_values):
        return None
    first = previous_values[0]
    if any(value != first for value in previous_values[1:]):
        return None
    if Decimal(str(this_value)) - Decimal(str(first)) != Decimal(str(change)):
        return None
    return first, this_value


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _what(binding_family: str, labels: frozenset[str]) -> str:
    if binding_family.startswith("screen_hours."):
        shortest = min(len(label) for label in labels)
        word = max(label for label in labels if len(label) == shortest)
        return f"{word} screen time"
    if binding_family.startswith("tag_hours."):
        tag = binding_family[len("tag_hours.") :]
        return f"calendar time tagged {tag.removeprefix('iki-')}"
    if binding_family in ("pushes", "github.push.count"):
        return "pushes"
    if binding_family in ("prs", "github.pr.count"):
        return "pull requests"
    if binding_family == "calendar.busy_hours":
        return "busy calendar time"
    if binding_family == "feed.item.count" or binding_family.startswith(
        "feed.item.count."
    ):
        return "feed items"
    if binding_family.startswith("cancelled."):
        tag = binding_family[len("cancelled.") :]
        return f"cancelled blocks tagged {tag.removeprefix('iki-')}"
    raise AssertionError(f"unrenderable family {binding_family}")


_HOUR_FAMILIES = ("screen_hours.", "tag_hours.", "calendar.busy_hours")


def _unit(family: str) -> str:
    if family.startswith(_HOUR_FAMILIES):
        return " hours"
    return ""


def _render_ref(
    metric_id: str,
    value: float,
    section_type: str,
    resolved: tuple[Any, Any] | None = None,
) -> str | None:
    binding = metric_label_binding(metric_id)
    if binding is None:
        return None
    what = _what(binding.family, binding.labels)
    period = (
        f"in the {binding.period} period"
        if binding.period is not None
        else "across the whole three-day window"
    )
    shown = display_value(value)
    unit = _unit(binding.family)
    if section_type == "since_last":
        if resolved is None:
            return None
        previous, current = resolved
        shown_previous = f"{display_value(previous)}{unit}"
        shown_current = f"{display_value(current)}{unit}"
        if value > 0:
            change = f"+{shown}{unit}"
        elif value < 0:
            change = f"-{display_value(abs(value))}{unit}"
        else:
            change = f"0{unit}"
        rendered = (
            f"{what} {period}: {shown_previous} on the previous card, "
            f"{shown_current} on this card, {change} since the previous card"
        )
    else:
        rendered = f"{what} {period}: {shown}{unit}"
    return rendered[:1].upper() + rendered[1:]


def collect(
    copy_db: Path,
    *,
    cut: datetime | None,
    exclude: frozenset[tuple[str, str]] = frozenset(),
) -> CollectResult:
    """Recover every rateable atomic claim on delivered run cards."""
    join = delivered_cards(copy_db)
    run = set(run_slots())
    conn = sqlite3.connect(f"file:{copy_db}?mode=ro", uri=True)
    try:
        fact_cache: dict[tuple[str, int], dict[str, str]] = {}
        attempt_cache: dict[str, tuple[str, str]] = {}

        def _facts(cycle_id: str, number: int) -> dict[str, str]:
            key = (cycle_id, number)
            cached = fact_cache.get(key)
            if cached is None:
                store = FactStore(db_path=copy_db)
                try:
                    rows = store.fetch_facts(cycle_id, number)
                finally:
                    store.close()
                cached = {row["fact_id"]: row["statement"] for row in rows}
                fact_cache[key] = cached
            return cached

        def _attempt(key: str) -> tuple[str, str]:
            cached = attempt_cache.get(key)
            if cached is None:
                try:
                    row = conn.execute(
                        "SELECT model_requested, effort FROM proposal_attempts"
                        " WHERE proposal_key = ? ORDER BY attempt DESC LIMIT 1",
                        (key,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
                cached = (str(row[0]), str(row[1])) if row else ("", "")
                attempt_cache[key] = cached
            return cached

        counts = dict(join.counts)
        parent_index: dict[str, list[dict[str, Any]]] | None = None
        counts.update(
            {
                "statements_total": 0,
                "statements_distinct": 0,
                "statements_unmatched": 0,
                "statements_ambiguous": 0,
                "sides_profile_from_display": 0,
                "facts_missing": 0,
                "metrics_unbound": 0,
                "claims_since_last_unresolved": 0,
                "so_clauses_cut": 0,
                "so_clauses_kept_with_digit": 0,
                "possibly_compound": 0,
                "claims_atomic_total": 0,
                "delivered_cards_in_pack": 0,
                "delivered_cards_without_payload": 0,
            }
        )
        by_source: dict[tuple[str, str, int], AtomicEntry] = {}
        counted_sources: set[tuple[str, str]] = set()
        cards_seen: set[str] = set()
        for card_id in join.delivered:
            slot = join.slots.get(card_id)
            if slot is None or slot not in run:
                continue
            if cut is not None and slot > cut:
                continue
            card = _load_card(conn, card_id)
            if card is None:
                counts["delivered_cards_without_payload"] += 1
                continue
            try:
                rows = conn.execute(
                    "SELECT letter, profile_id, as_of FROM slot_cards"
                    " WHERE card_id = ? ORDER BY letter",
                    (card_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            profiles = {str(letter): str(profile) for letter, profile, _ in rows}
            headers = {
                f"{side.letter} · {side.profile}": side for side in card.proposals
            }
            grouped: dict[str, list[str]] = {}
            unmatched: list[str] = []
            current: str | None = None
            for piece in card.statements:
                side = headers.get(piece)
                if side is not None:
                    current = side.letter if side.kind == "proposal" else None
                    if side.kind == "proposal":
                        grouped.setdefault(side.letter, [])
                    continue
                if current is None:
                    unmatched.append(piece)
                else:
                    grouped[current].append(piece)
            counts["statements_unmatched"] += len(unmatched)
            fallback_letters = {
                side.letter for side in card.proposals if side.kind != "proposal"
            }
            for letter in fallback_letters:
                grouped.pop(letter, None)
            for letter in [letter for letter in grouped if letter not in profiles]:
                display_name = next(
                    side.profile for side in card.proposals if side.letter == letter
                )
                candidate = display_name.lower()
                if candidate in ("builder", "disconnect") and (
                    candidate.capitalize() == display_name
                ):
                    profiles[letter] = candidate
                    counts["sides_profile_from_display"] += 1
                else:
                    counts["statements_unmatched"] += len(grouped.pop(letter))
            sides = sorted(grouped)
            if not sides:
                continue
            cards_seen.add(card_id)
            for letter in sides:
                pieces = grouped[letter]
                counts["statements_total"] += len(pieces)
                profile_id = profiles[letter]
                display = next(
                    side.profile for side in card.proposals if side.letter == letter
                )
                options = _candidates(conn, slot, profile_id)
                expected = (f"{letter} · {display}", *pieces)
                qualifying = [
                    option
                    for option in options
                    if build_statements(((letter, display, option.briefing),))
                    == expected
                ]
                if not qualifying:
                    counts["statements_unmatched"] += len(pieces)
                    continue
                ordered = [_ordered_claims(option.briefing) for option in qualifying]
                first_shapes = [
                    (
                        tuple(item.fact_ids),
                        tuple((ref.metric_id, ref.value) for ref in item.metric_refs),
                    )
                    for _, item in ordered[0]
                ]
                if any(
                    [
                        (
                            tuple(item.fact_ids),
                            tuple(
                                (ref.metric_id, ref.value) for ref in item.metric_refs
                            ),
                        )
                        for _, item in shape
                    ]
                    != first_shapes
                    for shape in ordered[1:]
                ):
                    counts["statements_ambiguous"] += len(pieces)
                    continue
                source = qualifying[0]
                claims = [item for _, item in ordered[0]]
                sections = [name for name, _ in ordered[0]]
                for index, claim in enumerate(claims):
                    if index >= len(pieces):
                        continue
                    known = _facts(source.cycle_id, source.run)
                    if any(fid not in known for fid in claim.fact_ids):
                        counts["facts_missing"] += 1
                        continue
                    pairs: list[tuple[Any, Any]] | None = None
                    if sections[index] == "since_last" and claim.metric_refs:
                        if parent_index is None:
                            parent_index = _parent_snapshots(conn)
                        parent_id = source.briefing.parent_briefing_id
                        carriers = (
                            parent_index.get(parent_id, [])
                            if parent_id is not None
                            else []
                        )
                        resolved: list[tuple[Any, Any]] = []
                        gated_unbound = False
                        gated_unresolved = False
                        for ref in claim.metric_refs:
                            if metric_label_binding(ref.metric_id) is None:
                                gated_unbound = True
                                break
                            pair = _resolve_since_last(
                                ref.metric_id,
                                ref.value,
                                source.snapshot,
                                carriers,
                            )
                            if pair is None:
                                gated_unresolved = True
                                break
                            resolved.append(pair)
                        if gated_unbound:
                            counts["metrics_unbound"] += 1
                            continue
                        if gated_unresolved:
                            counts["claims_since_last_unresolved"] += 1
                            continue
                        pairs = resolved
                    lines: list[str] = []
                    unbound = False
                    for position, ref in enumerate(claim.metric_refs):
                        pair = pairs[position] if pairs is not None else None
                        rendered = _render_ref(
                            ref.metric_id, ref.value, sections[index], pair
                        )
                        if rendered is None:
                            unbound = True
                            break
                        lines.append(rendered)
                    if unbound:
                        counts["metrics_unbound"] += 1
                        continue
                    key = (source.proposal_key, str(claim.id))
                    if key in exclude:
                        continue
                    fresh = key not in counted_sources
                    if fresh:
                        counted_sources.add(key)
                        counts["statements_distinct"] += 1
                    outcome = split_atomic(
                        pieces[index],
                        fact_ids=tuple(claim.fact_ids),
                        metric_refs=tuple(claim.metric_refs),
                        section_type=sections[index],
                    )
                    if fresh:
                        counts["so_clauses_cut"] += outcome.so_clauses_cut
                        counts["so_clauses_kept_with_digit"] += (
                            outcome.so_clauses_kept_with_digit
                        )
                        counts["possibly_compound"] += outcome.possibly_compound
                    model, effort = _attempt(source.proposal_key)
                    statements = tuple(known[fid] for fid in claim.fact_ids)
                    entry_lines = (*statements, *lines)
                    for atom in outcome.atomics:
                        sub = by_source.get((key[0], key[1], atom.atomic_index))
                        if sub is None:
                            by_source[(key[0], key[1], atom.atomic_index)] = (
                                AtomicEntry(
                                    proposal_key=key[0],
                                    claim_id=key[1],
                                    text=atom.text,
                                    fact_ids=atom.fact_ids,
                                    metric_refs=atom.metric_refs,
                                    section_type=atom.section_type,
                                    atomic_index=atom.atomic_index,
                                    fact_statements=statements,
                                    evidence_lines=tuple(
                                        line for line in entry_lines if line
                                    ),
                                    card_ids=(card_id,),
                                    slot=slot,
                                    profile=profile_id,
                                    model=model,
                                    effort=effort,
                                )
                            )
                        else:
                            known_cards = set(sub.card_ids) | {card_id}
                            by_source[(key[0], key[1], atom.atomic_index)] = (
                                AtomicEntry(
                                    proposal_key=sub.proposal_key,
                                    claim_id=sub.claim_id,
                                    text=sub.text,
                                    fact_ids=sub.fact_ids,
                                    metric_refs=sub.metric_refs,
                                    section_type=sub.section_type,
                                    atomic_index=sub.atomic_index,
                                    fact_statements=sub.fact_statements,
                                    evidence_lines=sub.evidence_lines,
                                    card_ids=tuple(sorted(known_cards)),
                                    slot=min(sub.slot, slot),
                                    profile=sub.profile,
                                    model=sub.model,
                                    effort=sub.effort,
                                )
                            )
        ordered_entries = sorted(
            by_source.values(),
            key=lambda entry: (entry.proposal_key, entry.claim_id, entry.atomic_index),
        )
        counts["claims_atomic_total"] = len(ordered_entries)
        counts["delivered_cards_in_pack"] = len(cards_seen)
        return CollectResult(atomics=tuple(ordered_entries), counts=counts)
    finally:
        conn.close()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _title_pattern(title: str) -> re.Pattern[str]:
    """A commitment title as a whole phrase, not inside a longer word."""
    return re.compile(r"(?<!\w)" + re.escape(title) + r"(?!\w)")


def _write_owner_only(path: Path, text: str) -> None:
    """Create the file owner-only from the start, never at a looser mode."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def build_pack(
    *,
    db: Path,
    out_dir: Path,
    seed: int,
    cut: datetime | None,
    pack_id: str | None,
    exclude_keys: Sequence[Path],
    environ: Mapping[str, str],
) -> tuple[int, dict[str, str]]:
    """Build the page and key; (exit code, stdout fields)."""
    resolved = out_dir.resolve()
    root = _repo_root()
    if resolved == root or root in resolved.parents:
        return 2, {"ok": "0", "reason": "output_dir_inside_repo"}
    if _inside_git_tree(resolved):
        return 2, {"ok": "0", "reason": "output_dir_inside_git_tree"}
    if not db.exists() or not db.is_file():
        return 2, {"ok": "0", "reason": "missing_db_file"}
    subject = environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject:
        return 2, {"ok": "0", "reason": "missing_subject_id"}
    terms = load_private_terms(dict(environ))
    if not terms.available:
        return 1, {
            "pack_refused": "1",
            "reason": "TERMS_UNAVAILABLE",
            "private_term_hits": "0",
            "raw_literal_hits": "0",
            "title_hits": "0",
        }
    from framework.briefing.commitments import load_commitments

    loaded = load_commitments(
        dict(environ),
        private_terms=terms.terms,
        forbidden_raw_literals=(),
    )
    if not loaded.available:
        return 1, {
            "pack_refused": "1",
            "reason": "COMMITMENTS_UNAVAILABLE",
            "private_term_hits": "0",
            "raw_literal_hits": "0",
            "title_hits": "0",
        }
    titles = [_collapse(commitment.title) for commitment in loaded.commitments]
    title_shapes = [_title_pattern(title) for title in titles if title]
    excluded: set[tuple[str, str]] = set()
    for path in exclude_keys:
        try:
            prior: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 2, {"ok": "0", "reason": "unreadable_exclude_key"}
        for item in prior.get("items", {}).values():
            excluded.add((str(item["proposal_key"]), str(item["claim_id"])))
    if cut is None:
        cut = datetime.now(delivery_mod.MADRID)
    copy, garbage = copy_store(db)
    try:
        collected = collect(copy_db=copy, cut=cut, exclude=frozenset(excluded))
        # Privacy scans before anything is written.
        term_hits = 0
        literal_hits = 0
        title_hits = 0
        literals_cache: dict[datetime, tuple[str, ...]] = {}
        event_store = EventStore(db_path=copy)
        try:
            for entry in collected.atomics:
                if entry.slot not in literals_cache:
                    literals_cache[entry.slot] = forbidden_literals_for(
                        event_store, subject, entry.slot
                    )
                literals = literals_cache[entry.slot]
                for text in (entry.text, *entry.fact_statements, *entry.evidence_lines):
                    if scan_outbound_text(
                        text,
                        private_terms=terms.terms,
                        private_terms_available=True,
                        forbidden_raw_literals=literals,
                    ):
                        codes = scan_outbound_text(
                            text,
                            private_terms=terms.terms,
                            private_terms_available=True,
                            forbidden_raw_literals=(),
                        )
                        if codes:
                            term_hits += 1
                        else:
                            literal_hits += 1
                    flat = _collapse(text)
                    if any(shape.search(flat) for shape in title_shapes):
                        title_hits += 1
        finally:
            event_store.close()
    finally:
        remove_copy(garbage)
    if term_hits or literal_hits or title_hits:
        reason = (
            "PRIVATE_TERM_HIT"
            if term_hits
            else "RAW_LITERAL_HIT"
            if literal_hits
            else "TITLE_HIT"
        )
        return 1, {
            "pack_refused": "1",
            "reason": reason,
            "private_term_hits": str(term_hits),
            "raw_literal_hits": str(literal_hits),
            "title_hits": str(title_hits),
        }
    keyed = sorted(
        collected.atomics,
        key=lambda entry: (entry.proposal_key, entry.claim_id, entry.atomic_index),
    )
    shuffled = list(keyed)
    random.Random(seed).shuffle(shuffled)
    items = [
        (f"item-{index + 1:04d}", entry.text, list(entry.evidence_lines))
        for index, entry in enumerate(shuffled)
    ]
    digest = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    resolved_pack_id = pack_id or f"pack-{digest[:12]}"
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out_dir, 0o700)
    page_path = out_dir / f"{resolved_pack_id}.html"
    key_path = out_dir / f"{resolved_pack_id}.key.json"
    _write_owner_only(
        page_path,
        render_page(
            resolved_pack_id,
            digest,
            [(item_id, text, tuple(lines)) for item_id, text, lines in items],
        ),
    )
    keyed_items = {
        item_id: {
            "card_id": min(entry.card_ids),
            "slot": entry.slot.isoformat(),
            "profile": entry.profile,
            "model": entry.model,
            "effort": entry.effort,
            "claim_id": entry.claim_id,
            "proposal_key": entry.proposal_key,
            "atomic_index": entry.atomic_index,
            "delivered_cards_shown": len(entry.card_ids),
        }
        for (item_id, _, _), entry in zip(items, shuffled)
    }
    _write_owner_only(
        key_path,
        json.dumps(
            {
                "pack_id": resolved_pack_id,
                "pack_hash": digest,
                "seed": seed,
                "cut": cut.isoformat(),
                "generated_from": GENERATED_FROM,
                "items": keyed_items,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
    )
    os.chmod(page_path, 0o600)
    os.chmod(key_path, 0o600)
    fields = {name: str(value) for name, value in collected.counts.items()}
    fields.update(
        {
            "pack_id": resolved_pack_id,
            "pack_hash": digest,
            "seed": str(seed),
            "cut": cut.isoformat(),
        }
    )
    return 0, fields
