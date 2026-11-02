"""Ticket 22: read-only public provenance export.

One JSON line per slot that has ledger rows, sorted by slot instant.
Same database, same bytes: no export time, stable key order, ASCII
only. The export opens the database read-only by URI, never constructs
a store or ledger (they run DDL and migrations), and runs all SELECTs
in one read transaction. Only allowlisted columns are selected; the
one exception is ``briefing_json``, parsed in memory only to walk fact
and metric ids, of which nothing but counts leaves.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from framework.briefing.schemas import Briefing, Claim
from framework.provenance.schemas import (
    OTHER_CODE,
    ProvenanceLine,
    clean_code,
    clean_effort,
    clean_finish_reason,
    clean_kind,
    clean_letter,
    clean_model_id,
    clean_pass_name,
    clean_profile,
    clean_transport,
    clean_version,
)

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

_SEND_OUTCOMES = ("delivered", "DELIVERY_UNKNOWN", "SEND_NOT_SENT", "SEND_REFUSED")
_FACTS_MODEL_WORDS = frozenset(
    {"ok", "SKIPPED", "FACTS_DEADLINE", "MODEL_DOWN", "FACTS_UNPARSED", "killed"}
)
_PUBLIC_TIERS = ("public", "private")


class ExportError(Exception):
    """A closed failure: ``code`` prints, ``exit_code`` exits."""

    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def select_claims(briefing: Briefing) -> list[Claim]:
    """The export's own claim selection, mirroring ``build_statements``.

    The first ``overall_state`` claim first, then the remaining claims in
    section order, up to 3. A shared-briefing test pins this against
    ``build_statements``, so a later change there fails loudly.
    """
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
    return ordered[:3]


def select_claim_texts(briefing: Briefing) -> list[str]:
    """The selected claim texts, in card order."""
    return [claim.text for claim in select_claims(briefing)]


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_count(value: Any) -> int | str:
    parsed = _as_int(value)
    if parsed is not None and parsed >= 0:
        return parsed
    return "unknown"


def _as_bool_or_unknown(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    parsed = _as_int(value)
    if parsed is not None:
        return parsed != 0
    return "unknown"


def _parse_moment(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment


def _utc_key(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse_detail(detail: Any) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not isinstance(detail, str) or not detail:
        return parsed
    for pair in detail.split(" "):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        parsed[key] = value
    return parsed


def _timeout_retries(ledger_rows: list[tuple[Any, ...]], profile: str) -> int | str:
    """The retried timeouts summed over every propose row of one side.

    A resumed or fresh run writes another row, so the side sums them.
    A row with no such key adds nothing, because older code never
    retried. A value that is not a non-negative whole number makes the
    side's count the word unknown, and a side with no propose row at
    all prints unknown. Nothing else from detail is read here.
    """
    step = f"propose_{profile}"
    rows = [row for row in ledger_rows if str(row[2]) == step]
    if not rows:
        return "unknown"
    total = 0
    for row in rows:
        parsed = _parse_detail(row[5])
        if "timeout_retries" not in parsed:
            continue
        value = parsed["timeout_retries"]
        if not value.isascii() or not value.isdigit():
            return "unknown"
        total += int(value)
    return total


def _parse_json_list(raw: Any) -> list[Any] | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed: Any = json.loads(raw)
    except (ValueError, RecursionError):
        # Deep JSON is unparseable here, and must never print a traceback.
        return None
    if not isinstance(parsed, list):
        return None
    return cast(list[Any], parsed)


def _codes(raw: Any) -> list[str] | str:
    """A real list maps element-wise; anything unreadable is the word unknown.

    An empty list only ever means a real empty list. A missing, NULL,
    unparseable or non-list value prints unknown, never an empty list and
    never a one-item placeholder list.
    """
    parsed = _parse_json_list(raw)
    if parsed is None:
        return "unknown"
    return [clean_code(item) for item in parsed]


def _zero_counts() -> dict[str, int | str]:
    return {"code": 0, "model": 0, "unknown": 0}


def _unknown_counts() -> dict[str, int | str]:
    return {"code": "unknown", "model": "unknown", "unknown": "unknown"}


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise ExportError("NO_DB", 2)
    uri = f"file:{quote(str(db_path))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise ExportError("UNREADABLE_DB", 2) from exc
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        if "not a database" in str(exc):
            raise ExportError("NOT_A_DATABASE", 2) from exc
        raise ExportError("UNREADABLE_DB", 2) from exc
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _maybe_rows(
    conn: sqlite3.Connection, tables: set[str], table: str, query: str
) -> list[tuple[Any, ...]]:
    if table not in tables:
        return []
    try:
        return [tuple(row) for row in conn.execute(query).fetchall()]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "no such column" in str(exc):
            return []
        raise


def _read_all(conn: sqlite3.Connection) -> dict[str, Any]:
    """Every allowlisted column, in one read transaction."""
    tables = _tables(conn)
    if "slot_ledger" not in tables:
        return {"tables": tables, "empty": True}
    conn.execute("BEGIN")
    try:
        ledger = _maybe_rows(
            conn,
            tables,
            "slot_ledger",
            "SELECT rowid, slot, step, outcome, card_id, detail"
            " FROM slot_ledger ORDER BY rowid",
        )
        cards = _maybe_rows(
            conn,
            tables,
            "slot_cards",
            "SELECT card_id, letter, slot, profile_id, kind"
            " FROM slot_cards ORDER BY card_id, letter",
        )
        results = _maybe_rows(
            conn,
            tables,
            "proposal_results",
            "SELECT rowid, proposal_key, cycle_id, run, profile_id,"
            " slot, kind, briefing_json, reason_codes FROM proposal_results",
        )
        attempts = _maybe_rows(
            conn,
            tables,
            "proposal_attempts",
            "SELECT proposal_key, attempt, model_requested, model_reported,"
            " effort, latency_ms, prompt_tokens, completion_tokens,"
            " reasoning_tokens, finish_reason, cached_tokens, transport,"
            " transport_version, parsed_ok, blocked, gate_codes"
            " FROM proposal_attempts ORDER BY attempt",
        )
        cycles = _maybe_rows(
            conn,
            tables,
            "cycles",
            "SELECT cycle_id, run, passes, dropped_codes FROM cycles",
        )
        facts: list[tuple[Any, ...]] = []
        facts_ok = False
        if "facts" in tables:
            try:
                columns = [
                    str(row[1]) for row in conn.execute("PRAGMA table_info(facts)")
                ]
            except sqlite3.OperationalError:
                columns = []
            if "origin" in columns:
                try:
                    facts = [
                        tuple(row)
                        for row in conn.execute(
                            "SELECT cycle_id, run, fact_id, tier, origin FROM facts"
                        ).fetchall()
                    ]
                    facts_ok = True
                except sqlite3.OperationalError:
                    facts = []
        retries = _maybe_rows(
            conn,
            tables,
            "local_start_retries",
            "SELECT slot, profile FROM local_start_retries",
        )
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    return {
        "tables": tables,
        "empty": False,
        "ledger": ledger,
        "cards": cards,
        "results": results,
        "attempts": attempts,
        "attempts_missing": "proposal_attempts" not in tables,
        "cycles": cycles,
        "facts": facts,
        "facts_ok": facts_ok,
        "retries": retries,
        "retries_missing": "local_start_retries" not in tables,
    }


def _attempt_entry(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        _key,
        _num,
        requested,
        reported,
        effort,
        latency,
        prompt_tokens,
        completion_tokens,
        reasoning_tokens,
        _finish,
        cached_tokens,
        transport,
        version,
        parsed_ok,
        blocked,
        gate,
    ) = row
    gate_list = _parse_json_list(gate)
    codes: list[str] | str
    if gate_list is None:
        codes = "unknown"
    else:
        codes = [_gate_code(item) for item in gate_list]
    return {
        "model_requested": clean_model_id(requested),
        "model_reported": clean_model_id(reported),
        "transport": clean_transport(transport),
        "muse_version": clean_version(version),
        "effort": clean_effort(effort),
        "latency_ms": _as_count(latency),
        "prompt_tokens": _as_count(prompt_tokens),
        "completion_tokens": _as_count(completion_tokens),
        "reasoning_tokens": _as_count(reasoning_tokens),
        "cached_tokens": _as_count(cached_tokens),
        "parsed_ok": _as_bool_or_unknown(parsed_ok),
        "blocked": _as_bool_or_unknown(blocked),
        "gate_codes": codes,
    }


def _gate_code(item: Any) -> str:
    if not isinstance(item, dict):
        return OTHER_CODE
    return clean_code(cast(dict[str, Any], item).get("code"))


def _pass_entry(raw: Any) -> dict[str, Any]:
    """One stored Glimmer pass: missing numbers print unknown, never 0.

    A stored JSON null ``noop_reason`` is a real value meaning no noop
    happened, so it prints none; a missing key prints unknown.
    """
    if not isinstance(raw, dict):
        return {
            "name": "unknown",
            "attempts": "unknown",
            "model_reported": "unknown",
            "latency_ms": "unknown",
            "completion_tokens": "unknown",
            "finish_reason": "unknown",
            "kept": "unknown",
            "noop_reason": "unknown",
        }
    data = cast(dict[str, Any], raw)
    if "noop_reason" not in data:
        noop: str = "unknown"
    elif data["noop_reason"] is None:
        noop = "none"
    else:
        noop = clean_code(data["noop_reason"])
    return {
        "name": clean_pass_name(data.get("name")),
        "attempts": _as_count(data.get("attempts")),
        "model_reported": clean_model_id(data.get("model_id")),
        "latency_ms": _as_count(data.get("latency_ms")),
        "completion_tokens": _as_count(data.get("completion_tokens")),
        "finish_reason": clean_finish_reason(data.get("finish_reason")),
        "kept": _as_count(data.get("kept")),
        "noop_reason": noop,
    }


def _cycle_block(
    cycle_id: str,
    run: int,
    cycles: dict[tuple[str, int], tuple[Any, ...]],
    facts_by_cycle: dict[tuple[str, int], list[tuple[str, str]]],
    facts_ok: bool,
) -> dict[str, Any]:
    """The side's cycle reading from its own stored ``(cycle_id, run)``.

    Origin is model if any pass has attempts above zero, code only if
    the list holds entries and every one has a real zero, else unknown.
    A side on no-cycle keeps real empty lists; anything unreadable
    prints the word unknown, never an empty list.
    """
    if cycle_id == "no-cycle":
        return {
            "origin": "none",
            "facts_available": _zero_counts(),
            "dropped_codes": [],
            "passes": [],
        }
    stored = cycles.get((cycle_id, run))
    if stored is None:
        return {
            "origin": "unknown",
            "facts_available": _unknown_counts(),
            "dropped_codes": "unknown",
            "passes": "unknown",
        }
    _cid, _run, passes_raw, dropped_raw = stored
    passes_list = _parse_json_list(passes_raw)
    if passes_list is None:
        return {
            "origin": "unknown",
            "facts_available": _unknown_counts(),
            "dropped_codes": "unknown",
            "passes": "unknown",
        }
    passes = [_pass_entry(item) for item in passes_list]
    tried = [item["attempts"] for item in passes]

    def _is_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    if any(_is_int(value) and value > 0 for value in tried):
        origin = "model"
    elif len(passes) > 0 and all(_is_int(value) and value == 0 for value in tried):
        origin = "code"
    else:
        origin = "unknown"
    dropped_list = _parse_json_list(dropped_raw)
    dropped: list[str] | str
    if dropped_list is None:
        dropped = "unknown"
    else:
        dropped = [clean_code(item) for item in dropped_list]
    if not facts_ok:
        available = _unknown_counts()
    else:
        available = _zero_counts()
        for tier, fact_origin in facts_by_cycle.get((cycle_id, run), []):
            if tier not in _PUBLIC_TIERS:
                continue
            bucket = fact_origin if fact_origin in ("code", "model") else "unknown"
            current = available[bucket]
            available[bucket] = (current if isinstance(current, int) else 0) + 1
    return {
        "origin": origin,
        "facts_available": available,
        "dropped_codes": dropped,
        "passes": passes,
    }


def _cited_counts(
    claims: Sequence[Claim] | None,
    cycle_id: str,
    run: int,
    facts_ok: bool,
    fact_index: dict[tuple[str, int, str], str],
) -> tuple[dict[str, int | str], int | str]:
    """Distinct cited facts by origin, plus distinct metric ids.

    A fact cited twice on a side counts once. A cited id with no row in
    that cycle counts as unknown. A side with no claims has real zeros;
    anything unreadable is unknown, never 0.
    """
    if claims is None:
        return _unknown_counts(), "unknown"
    if len(claims) == 0:
        return _zero_counts(), 0
    if not facts_ok:
        return _unknown_counts(), "unknown"
    seen: set[str] = set()
    counts = _zero_counts()
    for claim in claims:
        for fid in claim.fact_ids:
            if fid in seen:
                continue
            seen.add(fid)
            origin = fact_index.get((cycle_id, run, fid))
            if origin is None:
                current = counts["unknown"]
                counts["unknown"] = (current if isinstance(current, int) else 0) + 1
            else:
                bucket = origin if origin in ("code", "model") else "unknown"
                current = counts[bucket]
                counts[bucket] = (current if isinstance(current, int) else 0) + 1
    metrics: set[str] = set()
    for claim in claims:
        for ref in claim.metric_refs:
            metrics.add(ref.metric_id)
    return counts, len(metrics)


def _final_code(outcome: Any) -> str:
    if outcome == "delivered" or outcome == "killed":
        return str(outcome)
    if outcome == "ok" or outcome == "none":
        return "unknown"
    return clean_code(outcome)


def _delivery(send_rows: Sequence[tuple[str, str]], has_card: bool) -> str:
    if not has_card:
        return "no_card"
    if not send_rows:
        return "not_sent"
    step, outcome = send_rows[-1]
    if step == "send_intent":
        return "intent_open"
    if outcome in _SEND_OUTCOMES:
        return str(outcome)
    return "unknown"


def _build_line(
    slot: datetime,
    ledger_rows: list[tuple[Any, ...]],
    card_rows: list[tuple[Any, ...]],
    results: dict[tuple[str, str], tuple[Any, ...]],
    attempts_by_key: dict[str, list[tuple[Any, ...]]],
    attempts_missing: bool,
    cycles: dict[tuple[str, int], tuple[Any, ...]],
    facts_by_cycle: dict[tuple[str, int], list[tuple[str, str]]],
    facts_ok: bool,
    fact_index: dict[tuple[str, int, str], str],
    retries: list[tuple[str, str]],
    retries_missing: bool,
) -> dict[str, Any]:
    """One closed line for one slot instant.

    The file holds one subject, so no subject filter is applied: join
    keys are read and never printed, which is the one allowance.
    """
    key = _utc_key(slot)
    # The slot's last card step row decides the card, as latest_card_id
    # does: a trailing card row with a NULL id (a --fresh run whose build
    # never became a card) means no card, and the older id counts as
    # superseded.
    card_steps = [
        (rowid, card) for rowid, _s, step, _o, card, _d in ledger_rows if step == "card"
    ]
    seen_ids = {str(card) for _rowid, card in card_steps if card is not None}
    latest_card: str | None = None
    if card_steps and card_steps[-1][1] is not None:
        latest_card = str(card_steps[-1][1])
    superseded = len(seen_ids - ({latest_card} if latest_card is not None else set()))
    # Delivery reads that card id's own send and send_intent rows.
    send_rows: list[tuple[str, str]] = [
        (str(step), str(outcome))
        for _rowid, _s, step, outcome, card, _d in ledger_rows
        if step in ("send", "send_intent")
        and card is not None
        and latest_card is not None
        and str(card) == latest_card
    ]
    non_watchdog = [row for row in ledger_rows if str(row[2]) != "watchdog"]
    final = _final_code(non_watchdog[-1][3]) if non_watchdog else "unknown"
    facts_rows = [row for row in ledger_rows if str(row[2]) == "facts_model"]
    if not facts_rows:
        facts_step: str = "unknown"
    else:
        last_outcome = str(facts_rows[-1][3])
        facts_step = last_outcome if last_outcome in _FACTS_MODEL_WORDS else OTHER_CODE
    start_rows = [row for row in ledger_rows if str(row[2]) == "start"]
    if not start_rows:
        forced: bool | str = "unknown"
    else:
        forced = any(_parse_detail(row[5]).get("forced") == "1" for row in start_rows)
    slot_sides = [
        row
        for row in card_rows
        if latest_card is not None and str(row[0]) == latest_card
    ]
    slot_sides.sort(key=lambda row: str(row[1]))
    side_profiles = {str(row[3]) for row in slot_sides}
    sides: list[dict[str, Any]] = []
    side_origins: list[str] = []
    side_triples: set[tuple[str, int, str]] = set()
    card_unknown = False
    for side_row in slot_sides:
        _card, letter, _slot, profile_raw, kind_raw = side_row
        profile = str(profile_raw)
        result = results.get((key, profile))
        if result is None:
            cycle_id = ""
            run = 0
            reason: list[str] | str = "unknown"
            briefing_claims: Sequence[Claim] | None = (
                [] if clean_kind(kind_raw) != "proposal" else None
            )
            attempts: Any = "unknown"
        else:
            (
                _rowid,
                _pkey,
                cycle_raw,
                run_raw,
                _prof,
                _rslot,
                _rkind,
                briefing_raw,
                codes_raw,
            ) = result
            cycle_id = str(cycle_raw)
            parsed_run = _as_int(run_raw)
            run = parsed_run if parsed_run is not None else 0
            reason = _codes(codes_raw)
            briefing_claims = _claims_for(briefing_raw, clean_kind(kind_raw))
            if attempts_missing:
                attempts = "unknown"
            else:
                rows = attempts_by_key.get(str(_pkey), [])
                attempts = [_attempt_entry(item) for item in rows]
        cycle = _cycle_block(cycle_id, int(run), cycles, facts_by_cycle, facts_ok)
        cited, metrics = _cited_counts(
            briefing_claims, cycle_id, int(run), facts_ok, fact_index
        )
        if any(value == "unknown" for value in cited.values()):
            card_unknown = True
        else:
            for claim in briefing_claims or []:
                for fid in claim.fact_ids:
                    side_triples.add((cycle_id, int(run), fid))
        side_origins.append(str(cycle["origin"]))
        if retries_missing:
            local: int | str = "unknown"
        else:
            local = sum(
                1 for stamp, prof in retries if stamp == key and prof == profile
            )
        sides.append(
            {
                "letter": clean_letter(letter),
                "profile": clean_profile(profile),
                "kind": clean_kind(kind_raw),
                "reason_codes": reason,
                "local_retries": local,
                "timeout_retries": _timeout_retries(ledger_rows, profile),
                "facts_cited": cited,
                "metrics_cited": metrics,
                "cycle": cycle,
                "attempts": attempts,
            }
        )
    # Profiles whose latest result at the slot has no side on the card.
    not_on_card: list[dict[str, Any]] = []
    for (stamp, profile), result in sorted(results.items()):
        if stamp != key:
            continue
        if profile in side_profiles:
            continue
        not_on_card.append(
            {
                "profile": clean_profile(profile),
                "kind": clean_kind(result[6]),
                "reason_codes": _codes(result[8]),
            }
        )
    has_card = latest_card is not None
    if card_unknown or (has_card and not sides):
        # A card whose side rows are gone (or whose table is missing)
        # prints unknown: the zero would not be real. A real no-card
        # slot keeps none and real zeros below.
        card_cited: dict[str, int | str] = _unknown_counts()
    else:
        card_cited = _zero_counts()
        for cid, crun, fid in side_triples:
            origin = fact_index.get((cid, crun, fid))
            bucket = origin if origin in ("code", "model") else "unknown"
            current = card_cited[bucket]
            card_cited[bucket] = (current if isinstance(current, int) else 0) + 1
    if not sides:
        origin_all = "none" if not has_card else "unknown"
    elif any(item == "unknown" for item in side_origins):
        origin_all = "unknown"
    elif len(set(side_origins)) == 1:
        origin_all = side_origins[0]
    else:
        origin_all = "mixed"
    return {
        "slot": slot.astimezone(MADRID).isoformat(),
        "delivery": _delivery(send_rows, latest_card is not None),
        "final_code": final,
        "facts_model_step": facts_step,
        "forced": forced,
        "superseded_cards": superseded,
        "cycle_origin": origin_all,
        "facts_cited": card_cited,
        "not_on_card": not_on_card,
        "sides": sides,
    }


def _claims_for(briefing_raw: Any, kind: str) -> Sequence[Claim] | None:
    """Selected claims for one side, or None when unreadable.

    A fallback side has no claims, so real zeros. A proposal side whose
    briefing cannot be read has unknown counts.
    """
    if kind != "proposal":
        return []
    if not isinstance(briefing_raw, str) or not briefing_raw:
        return None
    try:
        briefing = Briefing.model_validate_json(briefing_raw)
    except (ValidationError, RecursionError):
        return None
    return select_claims(briefing)


def build_lines(db_path: Path) -> tuple[list[str], dict[str, int]]:
    """Every line for the database, validated before anything is written."""
    conn = _connect(db_path)
    try:
        data = _read_all(conn)
    finally:
        conn.close()
    if data.get("empty"):
        return [], {
            "slots": 0,
            "cards": 0,
            "delivered": 0,
            "code": 0,
            "model": 0,
            "unknown": 0,
        }
    ledger: list[tuple[Any, ...]] = data["ledger"]
    cards: list[tuple[Any, ...]] = data["cards"]
    results_raw: list[tuple[Any, ...]] = data["results"]
    attempts_raw: list[tuple[Any, ...]] = data["attempts"]
    attempts_missing = bool(data["attempts_missing"])
    cycles_raw: list[tuple[Any, ...]] = data["cycles"]
    facts_raw: list[tuple[Any, ...]] = data["facts"]
    facts_ok = bool(data["facts_ok"])
    retries_raw: list[tuple[Any, ...]] = data["retries"]
    retries_missing = bool(data["retries_missing"])
    by_slot: dict[str, list[tuple[Any, ...]]] = {}
    moments: dict[str, datetime] = {}
    for row in ledger:
        moment = _parse_moment(row[1])
        if moment is None:
            raise ExportError("LINE_INVALID", 1)
        stamp = _utc_key(moment)
        by_slot.setdefault(stamp, []).append(row)
        moments[stamp] = moment
    results: dict[tuple[str, str], tuple[Any, ...]] = {}
    for row in results_raw:
        moment = _parse_moment(row[5])
        if moment is None:
            continue
        stamp = _utc_key(moment)
        prior = results.get((stamp, str(row[4])))
        if prior is None or int(row[0]) > int(prior[0]):
            results[(stamp, str(row[4]))] = row
    attempts_by_key: dict[str, list[tuple[Any, ...]]] = {}
    for row in attempts_raw:
        attempts_by_key.setdefault(str(row[0]), []).append(row)
    cycles: dict[tuple[str, int], tuple[Any, ...]] = {}
    for row in cycles_raw:
        run = _as_int(row[1])
        if run is None:
            continue
        cycles[(str(row[0]), run)] = (str(row[0]), run, row[2], row[3])
    facts_by_cycle: dict[tuple[str, int], list[tuple[str, str]]] = {}
    fact_index: dict[tuple[str, int, str], str] = {}
    for row in facts_raw:
        run = _as_int(row[1])
        if run is None:
            continue
        facts_by_cycle.setdefault((str(row[0]), run), []).append(
            (str(row[3]), str(row[4]))
        )
        fact_index[(str(row[0]), run, str(row[2]))] = str(row[4])
    retries: list[tuple[str, str]] = []
    for row in retries_raw:
        moment = _parse_moment(row[0])
        if moment is None:
            continue
        retries.append((_utc_key(moment), str(row[1])))
    lines: list[str] = []
    counts = {
        "slots": 0,
        "cards": 0,
        "delivered": 0,
        "code": 0,
        "model": 0,
        "unknown": 0,
    }
    for stamp in sorted(by_slot):
        raw = _build_line(
            moments[stamp],
            by_slot[stamp],
            cards,
            results,
            attempts_by_key,
            attempts_missing,
            cycles,
            facts_by_cycle,
            facts_ok,
            fact_index,
            retries,
            retries_missing,
        )
        try:
            line = ProvenanceLine.model_validate(raw)
        except ValidationError as exc:
            raise ExportError("LINE_INVALID", 1) from exc
        # Reading order, never sorted: slot comes first on head -1, and
        # bytes stay stable because the model fixes the field order.
        lines.append(json.dumps(line.model_dump(mode="json"), ensure_ascii=True))
        counts["slots"] += 1
        if raw["delivery"] != "no_card":
            counts["cards"] += 1
        if raw["delivery"] == "delivered":
            counts["delivered"] += 1
        cited_raw: Any = raw["facts_cited"]
        cited = cast(dict[str, Any], cited_raw) if isinstance(cited_raw, dict) else {}
        for bucket in ("code", "model", "unknown"):
            value = cited.get(bucket)
            if isinstance(value, int):
                counts[bucket] += value
    return lines, counts


def _read_target_slots(target: Path) -> set[str]:
    try:
        text = target.read_text()
    except OSError as exc:
        raise ExportError("UNREADABLE_DB", 2) from exc
    slots: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parsed: Any = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise ExportError("TARGET_UNPARSEABLE", 2) from exc
        slot_value = (
            cast(dict[str, Any], parsed).get("slot")
            if isinstance(parsed, dict)
            else None
        )
        if not isinstance(slot_value, str):
            raise ExportError("TARGET_UNPARSEABLE", 2)
        slots.add(slot_value)
    return slots


def _write_out(target: Path, lines: list[str]) -> None:
    body = "".join(f"{line}\n" for line in lines)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        wanted = _read_target_slots(target)
        fresh = {str(json.loads(line)["slot"]) for line in lines}
        if not wanted.issubset(fresh):
            raise ExportError("SLOT_LOST", 2)
        keep: int | None = stat_mode(target)
    else:
        keep = None
    fd, name = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(body)
        if keep is None:
            current = os.umask(0)
            os.umask(current)
            os.chmod(name, 0o666 & ~current)
        else:
            os.chmod(name, keep)
        os.replace(name, target)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def stat_mode(target: Path) -> int:
    return 0o777 & os.stat(target).st_mode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="framework.provenance.export")
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=False, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Any other exception prints its class name as a closed code, exit 1."""
    args = _parser().parse_args(argv)
    try:
        lines, counts = build_lines(Path(str(args.db)))
    except ExportError as exc:
        print(f"code={exc.code}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 -- the edge maps to the class only
        print(f"code={type(exc).__name__}", file=sys.stderr)
        return 1
    out = args.out
    if out is not None:
        try:
            _write_out(Path(str(out)), lines)
        except ExportError as exc:
            print(f"code={exc.code}", file=sys.stderr)
            return exc.exit_code
        except Exception as exc:  # noqa: BLE001 -- the edge maps to the class only
            print(f"code={type(exc).__name__}", file=sys.stderr)
            return 1
    elif lines:
        sys.stdout.write("".join(f"{line}\n" for line in lines))
    print(
        f"slots={counts['slots']} cards={counts['cards']}"
        f" delivered={counts['delivered']} facts_code={counts['code']}"
        f" facts_model={counts['model']} facts_unknown={counts['unknown']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
