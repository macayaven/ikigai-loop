"""Ticket 13 slice 4: the read-only card trace.

It opens the database read-only and runs its own ``SELECT``s, because the
store constructors run DDL and migrations. It prints card text and cited
facts; that output stays private and must never go into the repo.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from framework.cycle.card_build import since_counts
from framework.glimmer.checks import event_touches_window
from framework.glimmer.metrics import (
    floor_hour,
    is_opened_pr,
    period_bounds,
    select_winners,
    window_bounds,
)
from framework.schemas.events import Event
from framework.store.store import resolve_db_path
from framework.telegram.models import (
    Card,
    ChartData,
    first_rulings,
    render_card_text,
)

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

_ACTIVE_CALENDAR_TYPES = (
    "calendar.event.created",
    "calendar.event.updated",
)
_CALENDAR_TYPES = (
    "calendar.event.created",
    "calendar.event.updated",
    "calendar.event.cancelled",
)
_EVENT_COLUMNS = (
    "id, subject_id, source, type, time, source_id, data, tier,"
    " collected_at, collector_version"
)


def _data(event: Event) -> Any:
    return event.data


def _active_calendar(event: Event) -> bool:
    """A non-cancelled calendar row, the kind the snapshot measures."""
    return event.type in _ACTIVE_CALENDAR_TYPES


def _touches(event: Event, span: tuple[datetime, datetime] | None) -> bool:
    return span is not None and event_touches_window(event, span[0], span[1])


def metric_sources(
    metric_id: str, as_of: datetime, winners: Sequence[Event]
) -> tuple[Event, ...] | None:
    """The winning rows behind one metric id, or ``None`` when unknown.

    Every family goes through ``event_touches_window``, the same D4 rule
    the facts step uses: a whole-window family reads ``window_bounds``,
    a period family reads that period's own bounds. The family filters
    match ``build_metric_snapshot`` and ``build_period_rollup`` one by
    one, so the caller recomputes the snapshot's value from the returned
    rows. A block crossing the window's start still touches it; a row
    only in the open hour touches nothing here.
    """
    window_span = window_bounds(as_of)
    if metric_id == "github.push.count":
        return tuple(
            event
            for event in winners
            if event.type == "github.push" and _touches(event, window_span)
        )
    if metric_id == "github.pr.count":
        return tuple(
            event
            for event in winners
            if event.type == "github.pr"
            and is_opened_pr(event)
            and _touches(event, window_span)
        )
    if metric_id.startswith("screen_hours."):
        category = metric_id.removeprefix("screen_hours.")
        if not category or "." in category:
            return None
        return tuple(
            event
            for event in winners
            if event.type == "screen.hour"
            and category in _data(event).minutes_by_category
            and _touches(event, window_span)
        )
    if ".screen_hours." in metric_id:
        head, _, category = metric_id.partition(".screen_hours.")
        period = head.removeprefix("period.")
        if not category or "." in category:
            return None
        span = _period_span(period, as_of)
        if span is None:
            return None
        return tuple(
            event
            for event in winners
            if event.type == "screen.hour"
            and category in _data(event).minutes_by_category
            and _touches(event, span)
        )
    if metric_id == "calendar.busy_hours":
        return tuple(
            event
            for event in winners
            if _active_calendar(event)
            and _data(event).busy is True
            and _touches(event, window_span)
        )
    if metric_id.startswith("tag_hours."):
        tag = metric_id.removeprefix("tag_hours.")
        if not tag or "." in tag:
            return None
        return tuple(
            event
            for event in winners
            if _active_calendar(event)
            and tag in _data(event).tags
            and _touches(event, window_span)
        )
    if ".tag_hours." in metric_id and ".cancelled." not in metric_id:
        head, _, tag = metric_id.partition(".tag_hours.")
        span = _period_span(head.removeprefix("period."), as_of)
        if not tag or "." in tag or span is None:
            return None
        return tuple(
            event
            for event in winners
            if _active_calendar(event)
            and tag in _data(event).tags
            and _touches(event, span)
        )
    if ".cancelled." in metric_id:
        parts = metric_id.split(".")
        if len(parts) != 4 or parts[0] != "period" or parts[2] != "cancelled":
            return None
        span = _period_span(parts[1], as_of)
        if span is None:
            return None
        return tuple(
            event
            for event in winners
            if event.type == "calendar.event.cancelled"
            and parts[3] in _data(event).tags
            and _touches(event, span)
        )
    if metric_id == "feed.item.count" or metric_id.startswith("feed.item.count."):
        source = metric_id.removeprefix("feed.item.count").removeprefix(".")
        if "/" in source:
            return None
        return tuple(
            event
            for event in winners
            if event.type == "feed.item"
            and (not source or _data(event).source == source)
            and _touches(event, window_span)
        )
    if metric_id.startswith("period.") and metric_id.endswith((".pushes", ".prs")):
        parts = metric_id.split(".")
        if len(parts) != 3:
            return None
        span = _period_span(parts[1], as_of)
        if span is None:
            return None
        if parts[2] == "pushes":
            return tuple(
                event
                for event in winners
                if event.type == "github.push" and _touches(event, span)
            )
        return tuple(
            event
            for event in winners
            if event.type == "github.pr"
            and is_opened_pr(event)
            and _touches(event, span)
        )
    return None


def _period_span(period: str, as_of: datetime) -> tuple[datetime, datetime] | None:
    for name, low, high in period_bounds(as_of):
        if name == period:
            return (low, high)
    return None


class _MissingDb(Exception):
    """The database file is not there."""


def _connect(db_path: Path) -> sqlite3.Connection:
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise _MissingDb from exc


def _parse_event(row: Any) -> Event:
    (eid, subject, source, etype, moment, source_id, data, tier, collected, version) = (
        row
    )
    return Event.model_validate(
        {
            "id": str(eid),
            "subject_id": str(subject),
            "source": str(source),
            "type": str(etype),
            "time": str(moment),
            "source_id": str(source_id),
            "data": {**json.loads(str(data)), "type": str(etype)},
            "tier": str(tier),
            "collected_at": str(collected),
            "collector_version": str(version),
        }
    )


def _window_events(
    conn: sqlite3.Connection, subject_id: str, start: datetime, end: datetime
) -> list[Event]:
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM events"
        " WHERE subject_id = ? AND time >= ? AND time < ?",
        (
            subject_id,
            start.astimezone(UTC).isoformat(),
            end.astimezone(UTC).isoformat(),
        ),
    ).fetchall()
    return [_parse_event(row) for row in rows]


def _calendar_events(conn: sqlite3.Connection, subject_id: str) -> list[Event]:
    """Every calendar row for one subject, with no time filter.

    A block crossing the window's start has its stamp outside it, so a
    time filter would drop it before ``select_winners``; the reconciliation
    in ``run_cycle`` loads calendar rows whole for the same reason.
    """
    placeholders = ", ".join("?" for _ in _CALENDAR_TYPES)
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM events"
        f" WHERE subject_id = ? AND type IN ({placeholders})",
        (subject_id, *_CALENDAR_TYPES),
    ).fetchall()
    return [_parse_event(row) for row in rows]


def _trace_winners(
    conn: sqlite3.Connection, subject_id: str, as_of: datetime
) -> tuple[Event, ...]:
    """The reconciled rows behind a card, as ``run_cycle`` loads them.

    Calendar rows load whole; other rows load from the floored window's
    start to the raw ``as_of``; the collected guard sits at the raw
    ``as_of``; then ``select_winners``. No time filter on calendar rows
    before ``select_winners``.
    """
    window_start, _ = window_bounds(as_of)
    calendar_rows = _calendar_events(conn, subject_id)
    other_rows = _window_events(conn, subject_id, window_start, as_of)
    other_rows = [event for event in other_rows if event.type not in _CALENDAR_TYPES]
    collected = [
        event for event in (*calendar_rows, *other_rows) if event.collected_at <= as_of
    ]
    return select_winners(collected)


def _madrid_hm(moment: datetime) -> str:
    return moment.astimezone(MADRID).strftime("%H:%M")


def _parse_detail(detail: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in detail.split(" "):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        parsed[key] = value
    return parsed


def trace(*, card_id: str, db_path: Path | str | None) -> int:
    """Print what one card sent, what each claim cited, and the rows behind it.

    Read-only: its own ``SELECT``s over a ``mode=ro`` connection, never a
    store or ledger constructor. Code fact evidence is capped at 8 ids, so
    a fact line can undercount while its metric line gives the full number.
    """
    db = resolve_db_path(Path(db_path) if db_path else None)
    try:
        conn = _connect(db)
    except _MissingDb:
        print("code=NO_DB")
        return 2
    try:
        try:
            sides = conn.execute(
                "SELECT card_id, letter, slot, subject_id, as_of, bucket,"
                " profile_id, commitment_id, kind, policy_pick, policy_alternative"
                " FROM slot_cards WHERE card_id = ? ORDER BY letter",
                (card_id,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            sides = []
        if not sides:
            print("code=UNKNOWN_CARD")
            return 2
        slot = datetime.fromisoformat(str(sides[0][2]))
        subject_id = str(sides[0][3])
        as_of = datetime.fromisoformat(str(sides[0][4]))
        payload = conn.execute(
            "SELECT card_json, chart_json FROM slot_card_payloads WHERE card_id = ?",
            (card_id,),
        ).fetchone()
        if payload is None:
            print("code=UNKNOWN_CARD")
            return 2
        card = Card.model_validate_json(str(payload[0]))
        chart = ChartData.model_validate_json(str(payload[1]))
        outcome = "none"
        message_id = "-"
        for step, step_outcome, detail in conn.execute(
            "SELECT step, outcome, detail FROM slot_ledger WHERE slot = ?"
            " AND step IN ('send', 'send_intent') ORDER BY rowid",
            (slot.astimezone(UTC).isoformat(),),
        ).fetchall():
            if str(step) == "send":
                outcome = str(step_outcome)
                message_id = _parse_detail(str(detail)).get("message_id", "-")
        taps = [
            _parse_event(row)
            for row in conn.execute(
                f"SELECT {_EVENT_COLUMNS} FROM events"
                " WHERE subject_id = ? AND source = 'telegram' AND type = 'app.tap'",
                (subject_id,),
            ).fetchall()
        ]
        ruling = first_rulings(taps).get(card_id, "-")
        results: dict[str, Any] = {}
        for row in conn.execute(
            "SELECT proposal_key, profile_id, cycle_id, run, kind, briefing_json,"
            " snapshot, hour_start, hour_end, reason_codes, cycle_age_s, slot"
            " FROM proposal_results WHERE subject_id = ?",
            (subject_id,),
        ).fetchall():
            if datetime.fromisoformat(str(row[11])) == slot:
                results[str(row[1])] = row
        attempts: dict[str, list[Any]] = {}
        for row in conn.execute(
            "SELECT proposal_key, transport, transport_version, completion_tokens,"
            " prompt_tokens, gate_codes, parsed_ok, blocked FROM proposal_attempts"
            " ORDER BY attempt",
        ).fetchall():
            attempts.setdefault(str(row[0]), []).append(row)
        facts: dict[str, Any] = {}
        for profile_row in results.values():
            for fact_row in conn.execute(
                "SELECT fact_id, statement, evidence, tier, origin FROM facts"
                " WHERE cycle_id = ? AND run = ? ORDER BY rowid",
                (str(profile_row[2]), int(profile_row[3])),
            ).fetchall():
                facts[str(fact_row[0])] = fact_row
        event_rows: dict[str, Event] = {}
        for row in conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events WHERE subject_id = ?",
            (subject_id,),
        ).fetchall():
            event = _parse_event(row)
            event_rows[event.id] = event
        parent_snapshots = {
            str(side[6]): _parent_snapshot(conn, subject_id, str(side[6]), slot)
            for side in sides
        }
        print(
            f"card={card_id} slot={slot.isoformat()} as_of={as_of.isoformat()}"
            f" delivery={outcome} message={message_id} ruling={ruling}"
        )
        print(render_card_text(card))
        by_letter = {side.letter: side for side in card.proposals}
        for row in sides:
            _print_side(
                row,
                results,
                attempts,
                by_letter,
                event_rows,
                facts,
                parent_snapshots,
                as_of,
                subject_id,
                conn,
            )
        _print_chart(chart, as_of, subject_id, conn)
        _print_since(conn, card, subject_id, slot, as_of)
        return 0
    finally:
        conn.close()


def _parent_snapshot(
    conn: sqlite3.Connection, subject_id: str, profile_id: str, slot: datetime
) -> dict[str, float]:
    best: datetime | None = None
    for (stamp,) in conn.execute(
        "SELECT DISTINCT slot FROM slot_cards WHERE profile_id = ?",
        (profile_id,),
    ).fetchall():
        moment = datetime.fromisoformat(str(stamp))
        if moment >= slot:
            continue
        delivered = conn.execute(
            "SELECT card_id FROM slot_ledger WHERE slot = ? AND step = 'send'"
            " AND outcome = 'delivered' ORDER BY rowid DESC LIMIT 1",
            (moment.astimezone(UTC).isoformat(),),
        ).fetchone()
        if delivered is None or delivered[0] is None:
            continue
        kinds = conn.execute(
            "SELECT kind FROM slot_cards WHERE card_id = ? AND profile_id = ?",
            (str(delivered[0]), profile_id),
        ).fetchall()
        if not any(str(kind[0]) == "proposal" for kind in kinds):
            continue
        if best is None or moment > best:
            best = moment
    if best is None:
        return {}
    latest: tuple[int, str] | None = None
    for rowid, stamp_text, snapshot_text in conn.execute(
        "SELECT rowid, slot, snapshot FROM proposal_results"
        " WHERE subject_id = ? AND profile_id = ? AND kind = 'proposal'",
        (subject_id, profile_id),
    ).fetchall():
        if datetime.fromisoformat(str(stamp_text)) != best:
            continue
        if latest is None or int(rowid) > latest[0]:
            latest = (int(rowid), str(snapshot_text))
    if latest is None:
        return {}
    return {k: float(v) for k, v in json.loads(latest[1]).items()}


def _retry_rows(conn: sqlite3.Connection, slot_text: str, profile: str) -> list[Any]:
    """Masked local start failures for one side, or nothing.

    A file written before the retry table existed has no such table;
    that prints nothing and does not fail.
    """
    try:
        return conn.execute(
            "SELECT try, reason, latency_ms, exit_code, stderr"
            " FROM local_start_retries WHERE slot = ? AND profile = ?"
            " ORDER BY try",
            (slot_text, profile),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return []


def _timeout_retries(conn: sqlite3.Connection, slot_text: str, profile: str) -> int:
    """The retried timeouts summed over every row of one side's propose step.

    A resumed run writes another row and a ``--fresh`` run writes a new
    one; each carries its own count, so the side line sums them. A
    database with no such key reads as zero.
    """
    total = 0
    for (detail,) in conn.execute(
        "SELECT detail FROM slot_ledger WHERE slot = ? AND step = ?",
        (slot_text, f"propose_{profile}"),
    ).fetchall():
        total += int(_parse_detail(str(detail)).get("timeout_retries", "0") or 0)
    return total


def _print_side(
    row: Any,
    results: dict[str, Any],
    attempts: dict[str, list[Any]],
    by_letter: dict[str, Any],
    event_rows: dict[str, Event],
    facts: dict[str, Any],
    parent_snapshots: dict[str, dict[str, float]],
    as_of: datetime,
    subject_id: str,
    conn: sqlite3.Connection,
) -> None:
    _, letter, _, _, _, _, profile, commitment, kind, pick, alternative = (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        str(row[4]),
        row[5],
        str(row[6]),
        str(row[7]),
        str(row[8]),
        row[9],
        row[10],
    )
    stored = results.get(profile)
    stored_attempts = attempts.get(str(stored[0]), []) if stored else []
    tokens = sum(int(item[3]) for item in stored_attempts if item[3] is not None)
    transport = str(stored_attempts[0][1]) if stored_attempts else "-"
    side = by_letter.get(letter)
    hour = "-"
    title = ""
    if side is not None:
        hour = f"{_madrid_hm(side.start)}-{_madrid_hm(side.end)}"
        title = side.title
    line = (
        f"side {letter} {profile} {kind} commitment={commitment}"
        f" title={title} hour={hour}"
        f" pick={pick or '-'} alt={alternative or '-'}"
        f" attempts={len(stored_attempts)} transport={transport}"
        f" tokens={tokens}"
    )
    codes: tuple[str, ...] = ()
    if side is not None and side.kind == "fallback":
        codes = tuple(side.reason_codes)
    elif stored is not None and str(stored[4]) != "proposal" and str(stored[9]):
        codes = tuple(str(stored[9]).split(","))
    if codes:
        line += f" codes={','.join(codes)}"
    retry_rows = _retry_rows(conn, str(row[2]), profile)
    if retry_rows:
        line += f" local_retries={len(retry_rows)}"
    timeout_retries = _timeout_retries(conn, str(row[2]), profile)
    if timeout_retries:
        line += f" timeout_retries={timeout_retries}"
    print(line)
    for attempt, reason, latency_ms, exit_code, stderr in retry_rows:
        code = "-" if exit_code is None else str(exit_code)
        print(
            f"local_retry try={attempt} reason={reason}"
            f" latency_ms={latency_ms} exit={code} stderr={stderr}"
        )
    briefing = None
    snapshot: dict[str, float] = {}
    if stored is not None and stored[5] is not None:
        briefing = json.loads(str(stored[5]))
        snapshot = {k: float(v) for k, v in json.loads(str(stored[6])).items()}
    if briefing is None:
        return
    for section in briefing.get("sections", []):
        for claim in section.get("claims", []):
            print(f"claim {section.get('type')} {claim.get('id')} {claim.get('text')}")
            for fact_id in claim.get("fact_ids", []):
                _print_fact(str(fact_id), facts.get(str(fact_id)), event_rows)
            for ref in claim.get("metric_refs", []):
                _print_metric(
                    ref,
                    snapshot,
                    parent_snapshots.get(profile, {}),
                    section.get("type") == "since_last",
                    as_of,
                    subject_id,
                    conn,
                )


def _print_fact(fact_id: str, row: Any, event_rows: dict[str, Event]) -> None:
    if row is None:
        print(f"fact {fact_id} origin=- tier=- cited=0 found=0 statement=-")
        return
    _, statement, evidence_json, tier, origin = row
    evidence = [str(item) for item in json.loads(str(evidence_json))]
    found = sum(1 for item in evidence if item in event_rows)
    print(
        f"fact {fact_id} origin={origin} tier={tier}"
        f" cited={len(evidence)} found={found} statement={statement}"
    )
    for item in evidence:
        stored = event_rows.get(item)
        if stored is None:
            print(f"event {item} missing")
            continue
        print(
            f"event {stored.id} {stored.type}"
            f" {stored.time.isoformat()} {stored.collected_at.isoformat()}"
        )


def _print_metric(
    ref: dict[str, Any],
    snapshot: dict[str, float],
    parent: dict[str, float],
    is_since_last: bool,
    as_of: datetime,
    subject_id: str,
    conn: sqlite3.Connection,
) -> None:
    metric_id = str(ref.get("metric_id"))
    value = ref.get("value")
    winners = _trace_winners(conn, subject_id, as_of)
    found = metric_sources(metric_id, as_of, winners) or ()
    current = snapshot.get(metric_id)
    line = (
        f"metric {metric_id} value={value}"
        f" snapshot={current if current is not None else '-'}"
        f" source_events={len(found)}"
    )
    if is_since_last:
        older = parent.get(metric_id)
        line += f" parent={older if older is not None else '-'}"
    print(line)


def _print_chart(
    chart: ChartData,
    as_of: datetime,
    subject_id: str,
    conn: sqlite3.Connection,
) -> None:
    winners = _trace_winners(conn, subject_id, as_of)
    for series in chart.screen:
        found = metric_sources(f"screen_hours.{series.label}", as_of, winners) or ()
        print(
            f"chart screen {series.label}"
            f" {series.earlier}/{series.prior}/{series.last}"
            f" source_events={len(found)}"
        )
    if chart.pushes is not None:
        pushes = metric_sources("github.push.count", as_of, winners) or ()
        prs = metric_sources("github.pr.count", as_of, winners) or ()
        series = chart.pushes
        print(
            f"chart pushes {series.earlier}/{series.prior}/{series.last}"
            f" source_events={len(pushes) + len(prs)}"
        )
    for entry in chart.missing:
        print(f"chart missing {entry}")
    for item in chart.tally:
        print(f"chart tally {item.label}={item.count}")


def _print_since(
    conn: sqlite3.Connection,
    card: Card,
    subject_id: str,
    slot: datetime,
    as_of: datetime,
) -> None:
    delivered = conn.execute(
        "SELECT slot, card_id FROM slot_ledger WHERE step = 'send'"
        " AND outcome = 'delivered' AND slot < ? ORDER BY slot DESC LIMIT 1",
        (slot.astimezone(UTC).isoformat(),),
    ).fetchone()
    if delivered is None:
        previous_as_of = as_of - timedelta(hours=24)
    else:
        previous_rows = conn.execute(
            "SELECT as_of FROM slot_cards WHERE card_id = ?", (str(delivered[1]),)
        ).fetchall()
        previous_as_of = (
            datetime.fromisoformat(str(previous_rows[0][0]))
            if previous_rows
            else as_of - timedelta(hours=24)
        )
    current_floor = floor_hour(as_of)
    previous_floor = floor_hour(previous_as_of)
    events = _window_events(conn, subject_id, previous_floor, current_floor)
    counts = since_counts(events, previous_as_of, as_of)
    winners = select_winners([event for event in events if event.collected_at <= as_of])
    behind = sum(
        1
        for event in winners
        if previous_floor <= event.time < current_floor and event.collected_at <= as_of
    )
    pieces = [
        f"{key}={counts[key]}"
        for key in ("pushes", "code", "ai", "comms", "feed", "browse", "media")
    ]
    print(f"since {' '.join(pieces)} rows={behind}")
