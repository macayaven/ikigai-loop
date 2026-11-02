"""Ticket 13: slots, the run, the watchdog check and the CLI seams.

Pure parts (slots, eligibility, learner replay) plus ``Seams``,
``run_slot`` and ``check_slot``. The CLI dispatch lives in
``framework/cycle/__main__.py``; ``trace`` and ``rehearse`` live in
their own modules.
"""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast
from zoneinfo import ZoneInfo

from framework.briefing import load_commitments
from framework.briefing.context import (
    PrivateTerms,
    ProfileLimits,
    TimeInterval,
    load_private_terms,
)
from framework.briefing.schemas import Commitment
from framework.cycle import (
    forbidden_literals_for,
    run_cycle,
    run_proposals,
)
from framework.cycle.card_build import (
    build_card,
    build_chart_data,
    build_tally,
    minimal_chart_data,
    since_counts,
    since_line,
)
from framework.cycle.slot_ledger import (
    LedgerWriteBlocked,
    SlotCardRow,
    SlotLedger,
    parse_detail,
    sanitise_detail_value,
)
from framework.glimmer.facts import LLMResponse
from framework.glimmer.metrics import floor_hour
from framework.learner import Proposal as LearnerProposal
from framework.learner.policy import (
    bucket_for,
    initial_state,
    policy_block,
    rank_commitments,
    state_json,
)
from framework.learner.schemas import (
    Bucket,
    PolicyState,
    ProfileId,
    Ruling,
)
from framework.learner.scoring import observe
from framework.proposal.core import (
    MetaUnavailableError,
    ModelParams,
    ProposalResult,
    WonderClient,
    WonderRequest,
    WonderResponse,
)
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
from framework.proposal.hour import (
    fallback_window_codes,
    future_busy_intervals,
    pick_hour,
)
from framework.proposal.local_retry import LocalRetryClient
from framework.proposal.muse_client import MuseExecClient, resolve_muse_bin
from framework.proposal.schemas import FallbackProposal
from framework.schemas.events import AppTapData, Event
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore, StoredResult
from framework.store.store import EventStore, resolve_db_path
from framework.telegram.chart import render_chart_png
from framework.telegram.client import (
    TelegramApiError,
    TelegramAuthError,
    TelegramConfigError,
    TelegramDeliveryUnknown,
    TelegramRateLimited,
    TelegramTransportError,
)
from framework.telegram.models import Card, ChartData
from framework.telegram.service import RULING_WINDOW_START, send_card

MADRID = ZoneInfo("Europe/Madrid")

SLOT_TIMES: tuple[day_time, ...] = (
    day_time(13, 30),
    day_time(15, 30),
    day_time(18, 0),
    day_time(20, 30),
    day_time(22, 30),
)

_BUILDER_ONLY_TIMES = frozenset({day_time(13, 30), day_time(18, 0)})
_NIGHT_START = day_time(21, 0)
_CUTOFF = day_time(23, 0)

SLOT_LIMITS = ProfileLimits(
    timezone="Europe/Madrid",
    allowed_start=day_time(13, 0),
    allowed_end=day_time(23, 30),
    max_actions=3,
)
MODEL_PARAMS = ModelParams(
    first_model=DEFAULT_MODEL,
    first_effort=DEFAULT_EFFORT,
    retry_model=DEFAULT_MODEL,
    retry_effort=DEFAULT_EFFORT,
)
STALE_AFTER_S = 12 * 3600.0
CALENDAR_STALE_AFTER = timedelta(hours=1)


def _madrid(moment: datetime) -> datetime:
    return moment.astimezone(MADRID)


def slot_profiles(slot: datetime) -> tuple[str, ...]:
    """Allowed profiles for one slot: Builder always, Disconnect before
    the night cut-off except at the two Builder-only pinned times. A
    forced hand run keeps both until the cut-off; the pinned schedule
    never reaches any other time."""
    if slot.tzinfo is None or slot.tzinfo.utcoffset(slot) is None:
        raise ValueError("slot must carry a UTC offset")
    mark = _madrid(slot).time()
    if mark >= _CUTOFF or mark in _BUILDER_ONLY_TIMES:
        return ("builder",)
    return ("builder", "disconnect")


def classify_slot(slot: datetime) -> str:
    """One of ``ok``, ``unpinned`` or ``bad_offset``.

    ``unpinned`` is a Madrid stamp at a time no timer fires: ``--force-slot``
    may still run it. ``bad_offset`` is a naive stamp or an offset that is
    not Madrid on that date: ``--force-slot`` never lifts that refusal.
    """
    if slot.tzinfo is None or slot.tzinfo.utcoffset(slot) is None:
        return "bad_offset"
    if slot.utcoffset() != _madrid(slot).utcoffset():
        return "bad_offset"
    if _madrid(slot).time() not in SLOT_TIMES:
        return "unpinned"
    return "ok"


def validate_slot(slot: datetime) -> str | None:
    """``None`` when a slot may run; ``SLOT_NOT_PINNED`` otherwise.

    A naive stamp, an offset that is not Madrid on that date, and an
    unpinned Madrid time all refuse the same way here. ``run_slot``
    uses ``classify_slot`` to tell the forceable refusal apart.
    """
    if classify_slot(slot) != "ok":
        return "SLOT_NOT_PINNED"
    return None


@dataclass(frozen=True)
class EligibilityState:
    """The one extra input eligibility reads besides the slot and hour."""

    disconnect_sent_today: int
    now_local: datetime
    hour_start_local: datetime | None


def eligible_commitments(
    commitments: Sequence[Commitment],
    *,
    profile_id: str,
    slot_local: datetime,
    state: EligibilityState,
) -> tuple[Commitment, ...]:
    """The profile's commitments in file order, minus the night rules.

    From 21:00 Madrid Disconnect keeps only ``music`` and ``rest``; at or
    after 23:00 it returns nothing. The 21:00 rule reads the hour the
    proposal is for when one was picked, else the slot. The count in
    ``state`` stays for the daily-cap step; this function does not read it.
    """
    own = tuple(
        commitment for commitment in commitments if commitment.profile_id == profile_id
    )
    if profile_id != "disconnect":
        return own
    effective = state.hour_start_local or slot_local
    mark = effective.astimezone(MADRID).time()
    if mark >= _CUTOFF:
        return ()
    if mark >= _NIGHT_START:
        return tuple(
            commitment for commitment in own if commitment.kind in ("music", "rest")
        )
    return own


def disconnect_send_blocked(card_carries_disconnect: bool, now_local: datetime) -> bool:
    """Whether a card carrying Disconnect must not go out by the clock."""
    return card_carries_disconnect and now_local.astimezone(MADRID).time() >= _CUTOFF


def _ruling_for(
    card_id: str, target: str, rows: Sequence[SlotCardRow]
) -> Ruling | None:
    if target not in ("A", "B", "neither", "wrong", "why"):
        return None
    ordered = sorted(rows, key=lambda row: row.letter)
    try:
        proposals = tuple(
            LearnerProposal(
                label=row.letter,  # type: ignore[arg-type]
                profile_id=row.profile_id,  # type: ignore[arg-type]
                commitment_id=row.commitment_id,
                policy_pick=row.policy_pick,  # type: ignore[arg-type]
                policy_alternative=row.policy_alternative,
            )
            for row in ordered
            if row.policy_pick is not None
        )
        if len(proposals) != len(ordered):
            return None
        return Ruling(
            card_id=card_id,
            slot=ordered[0].slot,
            bucket=ordered[0].bucket,  # type: ignore[arg-type]
            proposals=proposals,
            target=target,  # type: ignore[arg-type]
        )
    except ValueError:
        return None


def rebuild_state(
    taps: Sequence[Event], card_rows: Sequence[SlotCardRow]
) -> tuple[PolicyState, int]:
    """Replay taps in handled-at order; count skipped rulings.

    Every ``app.tap`` feeds ``observe``, ``wrong`` and ``why`` included.
    A tap with no stored row, a row with a ``NULL`` pick, or a rejected
    ruling is skipped and counted, never fatal.
    """
    by_card: dict[str, list[SlotCardRow]] = {}
    for row in card_rows:
        by_card.setdefault(row.card_id, []).append(row)
    ordered = sorted(taps, key=lambda event: (event.time, event.id))
    state = initial_state()
    skipped = 0
    for event in ordered:
        if event.source != "telegram" or event.type != "app.tap":
            continue
        if not isinstance(event.data, AppTapData):
            continue
        rows = by_card.get(event.data.block_id)
        if not rows:
            skipped += 1
            continue
        ruling = _ruling_for(event.data.block_id, event.data.target, rows)
        if ruling is None:
            skipped += 1
            continue
        try:
            state = observe(state, ruling)
        except Exception:  # noqa: BLE001 - a bad ruling is counted, never fatal
            skipped += 1
    return (state, skipped)


def rank_and_block(
    state: PolicyState,
    profile: ProfileId,
    candidates: Sequence[str],
    bucket: Bucket,
) -> tuple[str | None, str | None, str]:
    """The policy pick, its alternative, and the prompt block.

    A moved commitment or a mixed-profile list carries on with no pick,
    no alternative and an empty block.
    """
    names = tuple(candidates)
    try:
        ranked = rank_commitments(state, profile, names, bucket)
        block = policy_block(state, bucket, names)
    except ValueError:
        return (None, None, "")
    if not ranked:
        return (None, None, "")
    pick = ranked[0].commitment_id
    alternative = ranked[1].commitment_id if len(ranked) > 1 else None
    return (pick, alternative, block)


CHECK_TIMEOUT_S = 300.0
CHECK_POLL_S = 5.0
_FACTS_CYCLE_RE = re.compile(rb"cycle=(\S+)")
_FACTS_RUN_RE = re.compile(rb"run=(\d+)")
_SEND_RETRY_DELAYS = (30.0, 60.0, 120.0)
_KILL_POLL_S = 5.0


@dataclass(frozen=True)
class FactsChildResult:
    """What the facts child run gave back to the slot."""

    outcome: str
    cycle_id: str | None
    run: int | None


@dataclass(frozen=True)
class Seams:
    """The fake points: production builds the real ones at the CLI edge.

    ``facts`` runs the model cycle and reports its cycle id; ``wonder``
    builds the client one propose call uses; ``telegram`` is the client
    ``send_card`` sends through (``None`` builds the real one, which a
    dry run never does); ``clock`` is wall time; ``sleep`` waits;
    ``home`` is the only home directory the run may look at.
    """

    facts: Callable[..., FactsChildResult]
    wonder: Callable[..., WonderClient]
    telegram: Any | None
    clock: Callable[[], datetime]
    sleep: Callable[[float], None] = time.sleep
    home: Path = field(default_factory=Path.home)
    ledger_sleep: Callable[[float], None] = time.sleep
    ledger_clock: Callable[[], float] = time.monotonic
    check_timeout_s: float = CHECK_TIMEOUT_S
    check_poll_s: float = CHECK_POLL_S


class _CodeOnlyStub:
    """LLM stand-in for the in-process code cycle; any call is a bug."""

    def complete(self, prompt: str) -> LLMResponse:
        raise AssertionError("model pass skipped: the stub must never be called")


def slot_from_today(value: str, now: datetime) -> datetime:
    """Resolve ``HH:MM`` on today's Madrid date to an aware instant."""
    try:
        mark = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise ValueError("error: --slot-today must be HH:MM") from None
    day = now.astimezone(MADRID).date()
    return datetime(day.year, day.month, day.day, mark.hour, mark.minute, tzinfo=MADRID)


def _kill_path() -> Path | None:
    raw = os.environ.get("IKIGAI_KILL_FILE", "")
    if not raw.strip():
        return None
    return Path(raw)


def _killed(kill_path: Path | None) -> bool:
    return kill_path is not None and os.path.lexists(kill_path)


def production_facts_runner(
    *,
    as_of: datetime,
    subject_id: str,
    db_path: str,
    deadline: datetime,
    kill_path: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    argv: Sequence[str] | None = None,
) -> FactsChildResult:
    """Run the model facts as a child in its own session until a deadline.

    The child's stderr is never captured and its stdout is parsed for
    ``cycle=`` and ``run=`` only. At the deadline, or when the kill file
    appears, the process group dies and the slot carries on with code
    facts. Real processes only; tests pass a short sleep command.
    """
    now = clock or (lambda: datetime.now(MADRID))
    cmd = (
        list(argv)
        if argv is not None
        else [
            sys.executable,
            "-m",
            "framework.cycle",
            "facts",
            "--as-of",
            as_of.isoformat(),
            "--subject-id",
            subject_id,
            "--db",
            db_path,
        ]
    )
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert proc.stdout is not None
    try:
        while True:
            if _killed(kill_path):
                _kill_facts_group(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return FactsChildResult("killed", None, None)
            if now() >= deadline:
                _kill_facts_group(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return FactsChildResult("FACTS_DEADLINE", None, None)
            try:
                raw, _ = proc.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                sleep(0.2)
                continue
            if proc.returncode != 0:
                return FactsChildResult("MODEL_DOWN", None, None)
            return _parse_facts_stdout(raw)
    except BaseException:
        _kill_facts_group(proc.pid)
        raise


def _kill_facts_group(pid: int) -> None:
    try:
        os.killpg(pid, 9)
    except (ProcessLookupError, PermissionError):
        pass


def _parse_facts_stdout(raw: bytes) -> FactsChildResult:
    cycle_match = _FACTS_CYCLE_RE.search(raw)
    run_match = _FACTS_RUN_RE.search(raw)
    if cycle_match is None or run_match is None:
        return FactsChildResult("FACTS_UNPARSED", None, None)
    try:
        cycle_id = cycle_match.group(1).decode("ascii")
        run = int(run_match.group(1).decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return FactsChildResult("FACTS_UNPARSED", None, None)
    return FactsChildResult("ok", cycle_id, run)


WONDER_TIMEOUT_S = 120.0
FACTS_SLOT_RESERVE = timedelta(minutes=4)
PROPOSE_SLOT_RESERVE = timedelta(seconds=30)
PROPOSE_STEP_BUDGET = timedelta(seconds=150)


class DeadlineWonderClient:
    """A Wonder client with a wall-clock deadline for one propose step.

    Every ``complete`` builds a fresh ``MuseExecClient`` with the time
    left, capped at 120 s, so two profiles with retries still land
    before the slot. Under 20 s left it raises at once. Transport facts
    forward to a probe client built the same way.
    """

    def __init__(
        self,
        *,
        make_client: Callable[[float], WonderClient],
        deadline: datetime,
        clock: Callable[[], datetime],
    ) -> None:
        self._make_client = make_client
        self._deadline = deadline
        self._clock = clock
        self._probe: WonderClient | None = None

    def _probe_client(self) -> WonderClient:
        if self._probe is None:
            self._probe = self._make_client(WONDER_TIMEOUT_S)
        return self._probe

    @property
    def transport(self) -> str:
        return self._probe_client().transport

    @property
    def transport_version(self) -> str | None:
        return self._probe_client().transport_version

    @property
    def harness_rules_file(self) -> bool | None:
        return self._probe_client().harness_rules_file

    def complete(self, request: WonderRequest) -> WonderResponse:
        left = (self._deadline - self._clock()).total_seconds()
        if left < 20.0:
            raise MetaUnavailableError("slot deadline", latency_ms=0)
        return self._make_client(min(WONDER_TIMEOUT_S, left)).complete(request)


def production_wonder_client(
    terms: PrivateTerms,
    deadline: datetime,
    clock: Callable[[], datetime],
    *,
    muse_bin: str | None = None,
) -> DeadlineWonderClient:
    """Build the production deadline client for one propose call."""

    def _make(timeout_s: float) -> MuseExecClient:
        return MuseExecClient(
            private_terms=terms.terms,
            private_terms_available=terms.available,
            muse_bin=muse_bin or resolve_muse_bin(),
            timeout_s=timeout_s,
        )

    return DeadlineWonderClient(make_client=_make, deadline=deadline, clock=clock)


_BUSY_TYPES = (
    "calendar.event.created",
    "calendar.event.updated",
    "calendar.event.cancelled",
)

_SENTINEL_START = datetime.min.replace(tzinfo=UTC)
_SENTINEL_END = datetime.max.replace(tzinfo=UTC)


def calendar_is_stale(ledger: SlotLedger, as_of: datetime) -> bool:
    """Whether the calendar feed is too old to trust for one slot.

    Stale means no ``calendar-`` cursor at all, or the oldest one more
    than an hour older than the slot's raw ``as_of``. Exactly one hour
    is still fresh. The collector polls every 15 minutes, so an hour
    means several missed polls. A card must never depend on this alert:
    any unexpected exception from the check reads as stale, so the
    slot carries on and still sends.
    """
    try:
        stamps = ledger.calendar_cursor_times()
    except Exception:  # noqa: BLE001 -- the alert never stops the slot
        return True
    try:
        if not stamps:
            return True
        return as_of - min(stamps) > CALENDAR_STALE_AFTER
    except Exception:  # noqa: BLE001 -- the alert never stops the slot
        return True


def plan_hour(
    *,
    as_of: datetime,
    slot: datetime,
    subject_id: str,
    store: EventStore,
    limits: ProfileLimits = SLOT_LIMITS,
) -> Any:
    """The free hour for one slot from the same calls ``run_proposals`` uses.

    Calendar rows load whole, as ``run_cycle`` does: a later revision of an
    invitation that moved more than 31 days away still reaches
    ``select_winners``, so its old hour stays free. ``future_busy_intervals``
    still keeps only what overlaps the day.
    """
    busy_events = store.events_between(
        subject_id, _SENTINEL_START, _SENTINEL_END, types=list(_BUSY_TYPES)
    )
    busy = future_busy_intervals(busy_events, as_of=as_of, slot=slot)
    return pick_hour(slot, busy, limits)


class _SlotDone(Exception):
    """Carries the exit code out of the run body."""

    def __init__(self, code: int) -> None:
        super().__init__(str(code))
        self.code = code


_EXPLAINED_ZERO = frozenset(
    {
        "DELIVERED",
        "delivered",
        "NOOP_NO_FREE_HOUR",
        "NOOP_NO_ELIGIBLE_COMMITMENT",
        "NOOP_SLOT_OUTSIDE_ALLOWED_HOURS",
        "NOOP_FALLBACK_WINDOW",
        "NOOP_MIXED",
        "DISCONNECT_DAILY_CAP",
        "DISCONNECT_AFTER_CUTOFF",
        "STALE_CARD",
        "killed",
        "SLOT_NOT_PINNED",
    }
)
_ALERT_ONE = frozenset(
    {
        "DELIVERY_UNKNOWN",
        "SEND_NOT_SENT",
        "SEND_REFUSED",
        "CHART_FAILED",
        "PREFLIGHT_RULES_FILE",
        "PREFLIGHT_META_API_KEY",
        "NOOP_OUTBOUND_BLOCKED",
        "COMMITMENTS_UNAVAILABLE",
        "TERMS_UNAVAILABLE",
    }
)
_DEGRADED_FACTS = frozenset({"MODEL_DOWN", "FACTS_DEADLINE", "FACTS_UNPARSED"})


def _noop_code(results: Sequence[Any]) -> str:
    """The slot's noop code from the first ``NOOP_`` code of each result.

    Raw reason codes such as ``CYCLE_STALE`` and gate codes never become
    the slot's code. An alert code beside a quiet one still alerts; one
    distinct code wins; anything else is ``NOOP_MIXED``.
    """
    firsts = [
        next(
            (code for code in result.reason_codes if code.startswith("NOOP_")),
            None,
        )
        for result in results
    ]
    codes = [code for code in firsts if code is not None]
    alerts = [code for code in codes if code in _ALERT_ONE]
    if alerts:
        return alerts[0]
    if len(set(codes)) == 1:
        return codes[0]
    return "NOOP_MIXED"


def run_slot(
    *,
    slot: datetime,
    subject_id: str,
    db_path: Path | str | None,
    dry_run: bool = False,
    fresh: bool = False,
    force_slot: bool = False,
    no_wait: bool = False,
    lead_minutes: int = 25,
    skip_local_model: bool = False,
    resend_unknown: bool = False,
    night_cutoff: bool = True,
    seams: Seams,
) -> int:
    """Run one slot end to end, once, safely.

    Stdout is one line of counts and codes only, never text. Exit 0 is
    done, killed, an explained noop, stale, ``ALREADY_DONE`` or
    ``DISCONNECT_AFTER_CUTOFF``; 2 is bad arguments, an unpinned slot
    without ``--force-slot``, preflight, ``FRESH_REFUSED``,
    ``RESEND_NOT_UNKNOWN`` or a missing named variable; 3 is another
    run holding the slot; 1 is everything else that sent nothing.
    """
    start_wall = seams.clock()
    kill = _kill_path()
    kill_flag = "set" if kill is not None else "unset"
    iso = slot.isoformat()
    real_db = resolve_db_path(Path(db_path) if db_path else None)
    dry_flag = 1 if dry_run else 0

    def _early(code: str) -> int:
        if code == "ALREADY_RUNNING":
            print(f"slot={iso} code={code}")
            return 3
        print(f"slot={iso} code={code} kill={kill_flag}")
        return 2

    lock_fd: int | None = None
    if not dry_run:
        lock_path = Path(str(real_db) + ".run-slot.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            print(f"slot={iso} code=LOCK_UNAVAILABLE kill={kill_flag}")
            return 1
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(lock_fd)
            return _early("ALREADY_RUNNING")

    scratch: Path | None = None
    try:
        work_db = real_db
        if dry_run:
            fd, name = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            scratch = Path(name)
            if real_db.exists():
                src = sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
                try:
                    dst = sqlite3.connect(scratch)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                finally:
                    src.close()
            work_db = scratch
        return _run_slot_body(
            slot=slot,
            subject_id=subject_id,
            work_db=work_db,
            dry_run=dry_run,
            fresh=fresh,
            force_slot=force_slot,
            no_wait=no_wait,
            lead_minutes=lead_minutes,
            skip_local_model=skip_local_model,
            resend_unknown=resend_unknown,
            night_cutoff=night_cutoff,
            seams=seams,
            start_wall=start_wall,
            kill=kill,
            kill_flag=kill_flag,
            iso=iso,
            dry_flag=dry_flag,
        )
    except _SlotDone as done:
        return done.code
    except LedgerWriteBlocked:
        print(f"slot={iso} code=LEDGER_WRITE_BLOCKED kill={kill_flag}")
        return 1
    except Exception as exc:  # noqa: BLE001 -- the edge maps to the class only
        print(f"slot={iso} code={type(exc).__name__} kill={kill_flag}")
        return 1
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if scratch is not None:
            for extra in (
                scratch,
                Path(str(scratch) + "-wal"),
                Path(str(scratch) + "-shm"),
            ):
                if extra.exists():
                    extra.unlink()


def _run_slot_body(
    *,
    slot: datetime,
    subject_id: str,
    work_db: Path,
    dry_run: bool,
    fresh: bool,
    force_slot: bool,
    no_wait: bool,
    lead_minutes: int,
    skip_local_model: bool,
    resend_unknown: bool,
    night_cutoff: bool,
    seams: Seams,
    start_wall: datetime,
    kill: Path | None,
    kill_flag: str,
    iso: str,
    dry_flag: int,
) -> int:
    """The run after the lock and the dry-run copy. Raises ``_SlotDone``."""
    ledger = SlotLedger(work_db, sleep=seams.ledger_sleep, clock=seams.ledger_clock)

    def _elapsed() -> float:
        return max(0.0, (seams.clock() - start_wall).total_seconds())

    def _finish(
        results: Sequence[Any], card_id: str | None, code: str | None, exit_code: int
    ) -> NoReturn:
        kinds = ",".join(result.kind for result in results) if results else "-"
        line = (
            f"slot={iso} profiles={len(results)} kind={kinds}"
            f" card={card_id or '-'} seconds={int(_elapsed())}"
            f" dry={dry_flag} kill={kill_flag}"
        )
        if code is not None:
            line += f" code={code}"
        print(line)
        raise _SlotDone(exit_code)

    def _refuse(code: str) -> NoReturn:
        print(f"slot={iso} code={code} kill={kill_flag}")
        raise _SlotDone(2)

    def _step_failed(step: str, exc: BaseException) -> NoReturn:
        ledger.append_step(slot, step, type(exc).__name__, _elapsed(), None, None)
        _finish((), None, type(exc).__name__, 1)

    def _killed_at(step: str) -> NoReturn:
        ledger.append_step(slot, step, "killed", _elapsed(), None, None)
        _finish((), None, "killed", 0)

    kind = classify_slot(slot)
    forced = False
    if kind != "ok":
        if kind == "unpinned" and force_slot:
            forced = True
        else:
            _refuse("SLOT_NOT_PINNED")

    state = ledger.send_state(slot)
    if fresh and state in ("delivered", "intent_open", "DELIVERY_UNKNOWN"):
        _refuse("FRESH_REFUSED")
    if resend_unknown and state not in ("DELIVERY_UNKNOWN", "intent_open"):
        _refuse("RESEND_NOT_UNKNOWN")

    rows = ledger.rows_for_slot(slot)
    if any(row.step == "done" for row in rows) and not fresh:
        print(f"slot={iso} code=ALREADY_DONE kill={kill_flag}")
        raise _SlotDone(0)

    existing_as_of = ledger.latest_start_as_of(slot)
    if fresh or existing_as_of is None:
        as_of = slot - timedelta(minutes=lead_minutes)
        start_detail: dict[str, object] = {"as_of": as_of.isoformat()}
        if forced:
            start_detail["forced"] = "1"
        ledger.append_step(slot, "start", "ok", _elapsed(), None, start_detail)
    else:
        as_of = existing_as_of

    if _killed(kill):
        _killed_at("start")

    config_dir = os.environ.get("XDG_CONFIG_HOME", "")
    rules_candidates = [seams.home / ".config" / "muse" / "AGENTS.md"]
    if config_dir.strip():
        rules_candidates.append(Path(config_dir) / "muse" / "AGENTS.md")
    preflight_code: str | None = None
    if any(os.path.lexists(candidate) for candidate in rules_candidates):
        preflight_code = "PREFLIGHT_RULES_FILE"
    elif os.environ.get("META_API_KEY", "").strip():
        preflight_code = "PREFLIGHT_META_API_KEY"
    if preflight_code is not None:
        ledger.append_step(slot, "preflight", preflight_code, _elapsed(), None, None)
        _refuse(preflight_code)
    ledger.append_step(slot, "preflight", "ok", _elapsed(), None, None)

    store = EventStore(db_path=work_db)
    try:
        fact_store = FactStore(db_path=store.db_path)
        try:
            proposal_store = ProposalStore(db_path=store.db_path)
            try:
                return _run_slot_stores(
                    slot=slot,
                    subject_id=subject_id,
                    ledger=ledger,
                    store=store,
                    fact_store=fact_store,
                    proposal_store=proposal_store,
                    as_of=as_of,
                    dry_run=dry_run,
                    fresh=fresh,
                    no_wait=no_wait,
                    lead_minutes=lead_minutes,
                    skip_local_model=skip_local_model,
                    resend_unknown=resend_unknown,
                    night_cutoff=night_cutoff,
                    seams=seams,
                    start_wall=start_wall,
                    kill=kill,
                    iso=iso,
                    finish=_finish,
                    step_failed=_step_failed,
                    killed_at=_killed_at,
                )
            finally:
                proposal_store.close()
        finally:
            fact_store.close()
    finally:
        store.close()


def _send_stored(
    *,
    slot: datetime,
    ledger: SlotLedger,
    card_id: str,
    sides: Sequence[SlotCardRow],
    payload: tuple[str, str],
    dry_run: bool,
    no_wait: bool,
    resend_unknown: bool,
    night_cutoff: bool,
    seams: Seams,
    start_wall: datetime,
    kill: Path | None,
    iso: str,
    finish: Callable[..., NoReturn],
    killed_at: Callable[[str], NoReturn],
) -> NoReturn:
    """Resume a stored card straight at the send stage. Never returns."""
    send_card_obj = Card.model_validate_json(payload[0])
    send_chart = ChartData.model_validate_json(payload[1])
    results = tuple(SimpleNamespace(kind=side.kind) for side in sides)
    if dry_run:
        finish(results, card_id, None, 0)
    slot_local = slot.astimezone(MADRID)
    carries = any(side.profile_id == "disconnect" for side in sides)
    cap_hit = (
        "disconnect" in slot_profiles(slot)
        and ledger.disconnect_count(slot_local.date()) >= 3
        and not carries
    )
    _send_card_rows(
        slot=slot,
        ledger=ledger,
        results=results,
        card=send_card_obj,
        chart=send_chart,
        card_id=card_id,
        carries_disconnect=any(side.profile_id == "disconnect" for side in sides),
        is_resend=resend_unknown,
        cap_hit=cap_hit,
        no_wait=no_wait,
        night_cutoff=night_cutoff,
        seams=seams,
        start_wall=start_wall,
        kill=kill,
        kill_flag="set" if kill is not None else "unset",
        iso=iso,
        finish=finish,
        killed_at=killed_at,
    )


def _run_slot_stores(
    *,
    slot: datetime,
    subject_id: str,
    ledger: SlotLedger,
    store: EventStore,
    fact_store: FactStore,
    proposal_store: ProposalStore,
    as_of: datetime,
    dry_run: bool,
    fresh: bool,
    no_wait: bool,
    lead_minutes: int,
    skip_local_model: bool,
    resend_unknown: bool,
    night_cutoff: bool,
    seams: Seams,
    start_wall: datetime,
    kill: Path | None,
    iso: str,
    finish: Callable[..., NoReturn],
    step_failed: Callable[[str, BaseException], NoReturn],
    killed_at: Callable[[str], NoReturn],
) -> int:
    """Facts, hour, learner, proposals, card, wait and send."""

    clock = seams.clock

    def _elapsed() -> float:
        return max(0.0, (clock() - start_wall).total_seconds())

    if _killed(kill):
        killed_at("start")

    resume_id = None if fresh else ledger.latest_card_id(slot)
    if resume_id is not None:
        payload = ledger.load_card_payload(resume_id)
        resume_sides = ledger.slot_cards_for_card(resume_id)
        if payload is not None and resume_sides:
            _send_stored(
                slot=slot,
                ledger=ledger,
                card_id=resume_id,
                sides=resume_sides,
                payload=payload,
                dry_run=dry_run,
                no_wait=no_wait,
                resend_unknown=resend_unknown,
                night_cutoff=night_cutoff,
                seams=seams,
                start_wall=start_wall,
                kill=kill,
                iso=iso,
                finish=finish,
                killed_at=killed_at,
            )

    if not dry_run and clock() > slot + timedelta(minutes=30):
        ledger.append_step(slot, "done", "STALE_CARD", _elapsed(), None, None)
        finish((), None, "STALE_CARD", 0)

    try:
        terms = load_private_terms()
    except Exception as exc:  # noqa: BLE001 -- closed code, never the value
        step_failed("commitments", exc)
    if not terms.available:
        ledger.append_step(
            slot, "commitments", "TERMS_UNAVAILABLE", _elapsed(), None, None
        )
        finish((), None, "TERMS_UNAVAILABLE", 1)
    try:
        literals = forbidden_literals_for(store, subject_id, as_of)
        loaded = load_commitments(
            os.environ,
            private_terms=terms.terms,
            forbidden_raw_literals=literals,
        )
    except Exception as exc:  # noqa: BLE001 -- closed code, never the value
        step_failed("commitments", exc)
    if not loaded.available:
        ledger.append_step(
            slot, "commitments", "COMMITMENTS_UNAVAILABLE", _elapsed(), None, None
        )
        finish((), None, "COMMITMENTS_UNAVAILABLE", 1)
    commitments = loaded.commitments
    ledger.append_step(
        slot,
        "commitments",
        "ok",
        _elapsed(),
        None,
        {"count": str(len(commitments))},
    )
    if _killed(kill):
        killed_at("commitments")

    rows = ledger.rows_for_slot(slot)
    by_step: dict[str, list[Any]] = {}
    for row in rows:
        by_step.setdefault(row.step, []).append(row)

    def _reused_cycle(step: str) -> str | None:
        if fresh:
            return None
        for row in by_step.get(step, []):
            if row.outcome == "ok":
                return parse_detail(row.detail).get("cycle")
        return None

    code_cycle_id = _reused_cycle("facts_code")
    if code_cycle_id is None:
        try:
            code_result, _code_run = run_cycle(
                as_of,
                subject_id,
                store,
                fact_store,
                _CodeOnlyStub(),  # type: ignore[arg-type]
                personal_pass=False,
                feed_pass=False,
            )
            code_cycle_id = code_result.cycle_id
        except Exception as exc:  # noqa: BLE001 -- closed code, never the value
            ledger.append_step(
                slot, "facts_code", type(exc).__name__, _elapsed(), None, None
            )
            code_cycle_id = None
        else:
            ledger.append_step(
                slot,
                "facts_code",
                "ok",
                _elapsed(),
                None,
                {"cycle": code_cycle_id},
            )
    if _killed(kill):
        killed_at("facts_code")

    facts_deadline = min(
        slot - FACTS_SLOT_RESERVE,
        start_wall + timedelta(minutes=lead_minutes + 10),
    )
    model_cycle_id: str | None = None
    facts_model_done = False
    if not fresh:
        for row in by_step.get("facts_model", []):
            if row.outcome == "killed":
                model_cycle_id = None
                facts_model_done = False
            else:
                facts_model_done = True
                model_cycle_id = (
                    parse_detail(row.detail).get("cycle")
                    if row.outcome == "ok"
                    else None
                )
    if facts_model_done:
        pass
    elif skip_local_model:
        ledger.append_step(slot, "facts_model", "SKIPPED", _elapsed(), None, None)
    elif clock() >= facts_deadline:
        ledger.append_step(
            slot, "facts_model", "FACTS_DEADLINE", _elapsed(), None, None
        )
    else:
        try:
            child = seams.facts(
                as_of=as_of,
                subject_id=subject_id,
                db_path=str(store.db_path),
                deadline=facts_deadline,
            )
        except Exception as exc:  # noqa: BLE001 -- closed code, never the value
            ledger.append_step(
                slot, "facts_model", type(exc).__name__, _elapsed(), None, None
            )
            child = None
        if child is not None:
            if child.outcome == "killed":
                killed_at("facts_model")
            elif child.outcome == "ok" and child.cycle_id is not None:
                model_cycle_id = child.cycle_id
                ledger.append_step(
                    slot,
                    "facts_model",
                    "ok",
                    _elapsed(),
                    None,
                    {"cycle": child.cycle_id},
                )
            else:
                ledger.append_step(
                    slot, "facts_model", child.outcome, _elapsed(), None, None
                )

    chosen_cycle = model_cycle_id or code_cycle_id

    hour: TimeInterval | None = None
    hour_rows = [
        row for row in by_step.get("hour", []) if row.outcome in ("ok", "none")
    ]
    if hour_rows and not fresh:
        hour_detail = parse_detail(hour_rows[-1].detail)
        if "start" in hour_detail and "end" in hour_detail:
            try:
                hour = TimeInterval(
                    start=datetime.fromisoformat(hour_detail["start"]),
                    end=datetime.fromisoformat(hour_detail["end"]),
                )
            except ValueError:
                hour = None
    else:
        try:
            _stale = calendar_is_stale(ledger, as_of)
        except Exception:  # noqa: BLE001 -- the alert never stops the slot
            _stale = True
        stale_detail: dict[str, object] | None = (
            {"calendar_stale": "1"} if _stale else None
        )
        try:
            hour = plan_hour(as_of=as_of, slot=slot, subject_id=subject_id, store=store)
        except Exception as exc:  # noqa: BLE001 -- closed code, never the value
            ledger.append_step(
                slot, "hour", type(exc).__name__, _elapsed(), None, stale_detail
            )
            hour = None
        else:
            write_detail: dict[str, object] | None = None
            if hour is not None:
                write_detail = {
                    "start": hour.start.isoformat(),
                    "end": hour.end.isoformat(),
                }
            if stale_detail is not None:
                write_detail = {**(write_detail or {}), **stale_detail}
            ledger.append_step(
                slot,
                "hour",
                "ok" if hour is not None else "none",
                _elapsed(),
                None,
                write_detail,
            )

    try:
        stored_state = None if fresh else ledger.learner_state_for_slot(slot)
        learner_state = (
            PolicyState.model_validate_json(stored_state)
            if stored_state is not None
            else None
        )
        learner_skipped = 0
    except Exception as exc:  # noqa: BLE001 -- closed code, never the value
        ledger.append_step(slot, "learner", type(exc).__name__, _elapsed(), None, None)
        learner_state = initial_state()
        learner_skipped = 0
    if learner_state is None:
        try:
            taps = store.events_between(
                subject_id,
                RULING_WINDOW_START,
                clock() + timedelta(days=1),
                types=["app.tap"],
            )
            rebuilt, learner_skipped = rebuild_state(taps, ledger.all_slot_cards())
            ledger.append_learner_state(slot, state_json(rebuilt))
            ledger.append_step(
                slot,
                "learner",
                "ok",
                _elapsed(),
                None,
                (
                    {"LEARNER_RULING_SKIPPED": str(learner_skipped)}
                    if learner_skipped
                    else None
                ),
            )
            learner_state = rebuilt
        except Exception as exc:  # noqa: BLE001 -- closed code, never the value
            step_failed("learner", exc)
    slot_local = slot.astimezone(MADRID)
    now_local = clock().astimezone(MADRID)
    sent_today = ledger.disconnect_count(slot_local.date())
    hour_local = hour.start.astimezone(MADRID) if hour is not None else None
    eligibility = EligibilityState(
        disconnect_sent_today=sent_today,
        now_local=now_local,
        hour_start_local=hour_local,
    )
    profiles = [profile for profile in slot_profiles(slot)]
    cap_hit = False
    if "disconnect" in profiles and sent_today >= 3:
        profiles.remove("disconnect")
        cap_hit = True
        ledger.append_step(
            slot, "propose_disconnect", "DISCONNECT_DAILY_CAP", _elapsed(), None, None
        )
    if _killed(kill):
        killed_at("learner")

    try:
        bucket: Bucket | None = bucket_for(slot_local.time())
        bucket_code: str | None = None
    except ValueError:
        bucket = None
        bucket_code = "BUCKET_OUTSIDE"

    policy_by_profile: dict[str, str] = {}
    picks: dict[str, tuple[str | None, str | None]] = {}
    learner_codes: list[str] = []
    if bucket_code is not None:
        learner_codes.append(bucket_code)
    for profile in profiles:
        eligible_here = eligible_commitments(
            commitments,
            profile_id=profile,
            slot_local=slot_local,
            state=eligibility,
        )
        names = tuple(item.id for item in eligible_here)
        if bucket is None or not names:
            pick, alternative, block = (None, None, "")
        else:
            pick, alternative, block = rank_and_block(
                learner_state, cast("ProfileId", profile), names, bucket
            )
            if (pick, alternative, block) == (None, None, ""):
                learner_codes.append("LEARNER_PROFILE_MISMATCH")
        policy_by_profile[profile] = block
        picks[profile] = (pick, alternative)
        if _killed(kill):
            killed_at(f"propose_{profile}")

    parents: dict[str, tuple[Any, Any]] = {}
    for profile in profiles:
        parent_slot = ledger.latest_proposal_slot(profile, slot)
        if parent_slot is None:
            continue
        found = proposal_store.latest_proposal(
            subject_id, profile, before_slot=parent_slot + timedelta(microseconds=1)
        )
        if found is not None:
            briefing, metrics, _ = found
            parents[profile] = (briefing, metrics)

    stored_results: dict[str, StoredResult] = {}
    if not fresh:
        for stored in proposal_store.results_for_slot(subject_id, slot):
            stored_results.setdefault(stored.profile_id, stored)

    results: list[Any] = []
    if chosen_cycle is None:
        busy_events = store.events_between(
            subject_id, _SENTINEL_START, _SENTINEL_END, types=list(_BUSY_TYPES)
        )
        busy = future_busy_intervals(busy_events, as_of=as_of, slot=slot)
        for profile in profiles:
            if profile in stored_results and not fresh:
                stored = stored_results[profile]
                results.append(stored)
                ledger.append_step(
                    slot,
                    f"propose_{profile}",
                    stored.kind,
                    _elapsed(),
                    None,
                    {"reused": "1", "cycle": stored.cycle_id},
                )
                continue
            eligible_here = eligible_commitments(
                commitments,
                profile_id=profile,
                slot_local=slot_local,
                state=eligibility,
            )
            if not eligible_here:
                continue
            if hour is None:
                continue
            shown = eligible_here[0]
            window_codes = fallback_window_codes(
                slot=slot,
                start=hour.start,
                end=hour.end,
                limits=SLOT_LIMITS,
                busy_intervals=busy,
            )
            if window_codes:
                window_noop = ProposalResult(
                    kind="noop",
                    profile_id=profile,
                    subject_id=subject_id,
                    cycle_id="no-cycle",
                    run=0,
                    slot=slot,
                    hour=hour,
                    briefing=None,
                    fallback=None,
                    reason_codes=(
                        "NOOP_FALLBACK_WINDOW",
                        *sorted(set(window_codes)),
                    ),
                    attempts=(),
                    cycle_age_s=0.0,
                    prompt_hash="",
                )
                proposal_store.record(window_noop, snapshot={})
                results.append(window_noop)
                ledger.append_step(
                    slot,
                    f"propose_{profile}",
                    window_noop.kind,
                    _elapsed(),
                    None,
                    {"reasons": ",".join(window_noop.reason_codes)},
                )
                continue
            manual = _manual_fallback(
                profile=profile,
                subject_id=subject_id,
                slot=slot,
                hour=hour,
                commitment=shown,
            )
            proposal_store.record(manual, snapshot={})
            results.append(manual)
            ledger.append_step(
                slot,
                f"propose_{profile}",
                "fallback",
                _elapsed(),
                None,
                {"reasons": "FALLBACK_NO_FACTS"},
            )
    propose_deadline = max(
        slot - PROPOSE_SLOT_RESERVE,
        clock() + PROPOSE_STEP_BUDGET,
    )
    seconds_left = lambda: (propose_deadline - clock()).total_seconds()
    client: Any = None
    for profile in profiles if chosen_cycle is not None else ():
        eligible_here = eligible_commitments(
            commitments,
            profile_id=profile,
            slot_local=slot_local,
            state=eligibility,
        )
        if profile in stored_results and not fresh:
            stored = stored_results[profile]
            results.append(stored)
            ledger.append_step(
                slot,
                f"propose_{profile}",
                stored.kind,
                _elapsed(),
                None,
                {"reused": "1", "cycle": stored.cycle_id},
            )
            continue
        if client is None:
            client = seams.wonder(terms, propose_deadline)
        retrying = LocalRetryClient(
            client, sleep=seams.sleep, seconds_left=seconds_left
        )
        try:
            produced = run_proposals(
                as_of=as_of,
                slot=slot,
                subject_id=subject_id,
                profiles=(profile,),
                store=store,
                fact_store=fact_store,
                proposal_store=proposal_store,
                client=retrying,
                private_terms=terms,
                eligible_by_profile={profile: eligible_here},
                limits=SLOT_LIMITS,
                models=MODEL_PARAMS,
                stale_after_s=STALE_AFTER_S,
                cycle_id=chosen_cycle,
                policy_by_profile={profile: policy_by_profile.get(profile, "")},
                parents=parents,
            )
        except Exception as exc:  # noqa: BLE001 -- closed code, never the value
            _record_local_retries(ledger, slot, profile, retrying)
            step_failed(f"propose_{profile}", exc)
        (result,) = produced
        results.append(result)
        local_retries = _record_local_retries(ledger, slot, profile, retrying)
        detail: dict[str, object] = {
            "cycle": result.cycle_id,
            "tokens": str(
                sum(attempt.completion_tokens or 0 for attempt in result.attempts)
            ),
            "tokens_in": str(
                sum(attempt.prompt_tokens or 0 for attempt in result.attempts)
            ),
            "reasons": ",".join(result.reason_codes) or "-",
        }
        if result.attempts:
            first_attempt = result.attempts[0]
            detail["transport"] = first_attempt.transport
            version = first_attempt.transport_version
            detail["transport_version"] = (
                "" if version is None else sanitise_detail_value(str(version))
            )
        else:
            detail["transport"] = getattr(client, "transport", "unknown")
            version = getattr(client, "transport_version", None)
            detail["transport_version"] = (
                "" if version is None else sanitise_detail_value(str(version))
            )
        if result.kind == "fallback" and any(
            code == "MODEL_UNAVAILABLE"
            for attempt in result.attempts
            for code, _ in attempt.codes
        ):
            detail["wonder_down"] = "1"
        for attempt in result.attempts:
            rules_file = attempt.harness_rules_file
            if rules_file is not None:
                detail["rules_file"] = "1" if rules_file else "0"
                break
        if local_retries:
            detail["local_retries"] = str(local_retries)
        ledger.append_step(
            slot, f"propose_{profile}", result.kind, _elapsed(), None, detail
        )
        if _killed(kill):
            killed_at(f"propose_{profile}")

    if not results:
        empty_code = (
            "NOOP_NO_FREE_HOUR" if hour is None else "NOOP_NO_ELIGIBLE_COMMITMENT"
        )
        ledger.append_step(
            slot, "card", empty_code, _elapsed(), None, {"reasons": empty_code}
        )
        ledger.append_step(slot, "done", empty_code, _elapsed(), None, None)
        finish((), None, empty_code, 0)
    if all(result.kind == "noop" for result in results):
        reasons = sorted({code for result in results for code in result.reason_codes})
        noop_code = _noop_code(results)
        ledger.append_step(
            slot,
            "card",
            noop_code,
            _elapsed(),
            None,
            {"reasons": ",".join(reasons) or "-"},
        )
        ledger.append_step(slot, "done", noop_code, _elapsed(), None, None)
        finish(results, None, noop_code, 0)

    commitments_by_id = {item.id: item for item in commitments}
    previous_card_id = ledger.latest_delivered_card_id(slot)
    if previous_card_id is None:
        previous_as_of = as_of - timedelta(hours=24)
        first_card = True
        previous_local = slot_local
    else:
        previous_rows = ledger.slot_cards_for_card(previous_card_id)
        previous_as_of = previous_rows[0].as_of
        first_card = False
        previous_local = previous_rows[0].slot.astimezone(MADRID)
    since_events = store.events_between(
        subject_id, floor_hour(previous_as_of), floor_hour(as_of)
    )
    counts = since_counts(since_events, previous_as_of, as_of)
    has_proposal = any(result.kind == "proposal" for result in results)
    line = (
        since_line(previous_local, counts, first=first_card) if has_proposal else None
    )
    chart_codes: list[str] = []
    try:
        tally_events = store.events_between(
            subject_id,
            RULING_WINDOW_START,
            clock() + timedelta(days=1),
            types=["app.tap"],
        )
        tally = build_tally(tally_events, ledger.all_slot_cards())
        chart_start = as_of - timedelta(days=4)
        chart_events = store.events_between(subject_id, chart_start, as_of)
        chart = build_chart_data(chart_events, as_of, tally)
    except Exception:  # noqa: BLE001 -- a build failure gets the minimal chart
        tally = ()
        chart = minimal_chart_data(tally)
        chart_codes.append("CHART_MINIMAL")
    try:
        render_chart_png(chart)
    except Exception:  # noqa: BLE001 -- minimal chart carries the slot
        chart = minimal_chart_data(tally)
        chart_codes.append("CHART_MINIMAL")
        try:
            render_chart_png(chart)
        except Exception:  # noqa: BLE001 -- closed code, never the value
            ledger.append_step(slot, "card", "CHART_FAILED", _elapsed(), None, None)
            finish(results, None, "CHART_FAILED", 1)
    try:
        built = build_card(
            slot=slot,
            subject_id=subject_id,
            as_of=as_of,
            bucket=(
                None if bucket is None else str(bucket)  # type: ignore[arg-type]
            ),
            results=results,
            commitments_by_id=commitments_by_id,
            picks=picks,
            since_line=line,
        )
    except Exception as exc:  # noqa: BLE001 -- closed code, never the value
        step_failed("card", exc)
    if built.card is None:
        codes = sorted(set(built.detail_codes) | set(learner_codes))
        ledger.append_step(
            slot,
            "card",
            "COMMITMENT_GONE",
            _elapsed(),
            None,
            {"codes": ",".join(codes) or "-"},
        )
        finish(results, None, "COMMITMENT_GONE", 0)
    card_codes = sorted(set(built.detail_codes) | set(chart_codes) | set(learner_codes))
    try:
        ledger.save_card_step(
            slot,
            built.card.card_id,
            {"codes": ",".join(card_codes) or "-"},
            built.sides,
            built.card.model_dump_json(),
            chart.model_dump_json(),
            _elapsed(),
        )
    except LedgerWriteBlocked:
        raise
    except Exception as exc:  # noqa: BLE001 -- closed code, never the value
        step_failed("card", exc)

    if dry_run:
        finish(results, built.card.card_id, None, 0)

    stored_card_id = ledger.latest_card_id(slot)
    if stored_card_id is not None:
        payload = ledger.load_card_payload(stored_card_id)
    else:
        payload = None
    if payload is not None and stored_card_id is not None:
        send_card_obj = Card.model_validate_json(payload[0])
        send_chart = ChartData.model_validate_json(payload[1])
        send_id = stored_card_id
    else:
        send_card_obj = built.card
        send_chart = chart
        send_id = built.card.card_id
    send_sides = ledger.slot_cards_for_card(send_id)
    carries_disconnect = any(side.profile_id == "disconnect" for side in send_sides)

    _send_card_rows(
        slot=slot,
        ledger=ledger,
        results=results,
        card=send_card_obj,
        chart=send_chart,
        card_id=send_id,
        carries_disconnect=carries_disconnect,
        is_resend=resend_unknown,
        cap_hit=cap_hit,
        no_wait=no_wait,
        night_cutoff=night_cutoff,
        seams=seams,
        start_wall=start_wall,
        kill=kill,
        kill_flag="set" if kill is not None else "unset",
        iso=iso,
        finish=finish,
        killed_at=killed_at,
    )


def _record_local_retries(
    ledger: SlotLedger,
    slot: datetime,
    profile: str,
    retrying: LocalRetryClient,
) -> int:
    """Store each recorded local start failure; return how many."""
    for record in retrying.failures:
        ledger.append_local_retry(
            slot,
            profile,
            record.attempt,
            record.reason,
            record.latency_ms,
            record.exit_code,
            record.stderr_masked,
        )
    return len(retrying.failures)


def _manual_fallback(
    *,
    profile: str,
    subject_id: str,
    slot: datetime,
    hour: TimeInterval | None,
    commitment: Commitment,
) -> Any:
    """A fallback result when no cycle exists at all: prose-free, listed."""
    return ProposalResult(
        kind="fallback",
        profile_id=profile,
        subject_id=subject_id,
        cycle_id="no-cycle",
        run=0,
        slot=slot,
        hour=hour,
        briefing=None,
        fallback=FallbackProposal(
            kind="fallback",
            profile_id=profile,  # type: ignore[arg-type]
            subject_id=subject_id,
            slot=slot,
            commitment=commitment,
            proposed_start=hour.start if hour is not None else slot,
            proposed_end=(
                hour.end if hour is not None else slot + timedelta(minutes=60)
            ),
            reason_codes=("FALLBACK_NO_FACTS",),
        ),
        reason_codes=("FALLBACK_NO_FACTS",),
        attempts=(),
        cycle_age_s=0.0,
        prompt_hash="",
    )


def _send_card_rows(
    *,
    slot: datetime,
    ledger: SlotLedger,
    results: Sequence[Any],
    card: Card,
    chart: ChartData,
    card_id: str,
    carries_disconnect: bool,
    is_resend: bool,
    cap_hit: bool,
    no_wait: bool,
    night_cutoff: bool,
    seams: Seams,
    start_wall: datetime,
    kill: Path | None,
    kill_flag: str,
    iso: str,
    finish: Callable[..., NoReturn],
    killed_at: Callable[[str], NoReturn],
) -> NoReturn:
    """State rules first, then the wait, the kill checks and the attempts."""
    clock = seams.clock
    sleep = seams.sleep

    def _elapsed() -> float:
        return max(0.0, (clock() - start_wall).total_seconds())

    def _stale_done() -> NoReturn:
        ledger.append_step(slot, "done", "STALE_CARD", _elapsed(), card_id, None)
        finish(results, card_id, "STALE_CARD", 0)

    def _cutoff_done() -> NoReturn:
        ledger.append_step(
            slot, "done", "DISCONNECT_AFTER_CUTOFF", _elapsed(), card_id, None
        )
        finish(results, card_id, "DISCONNECT_AFTER_CUTOFF", 0)

    state = ledger.send_state(slot)
    if state == "intent_open":
        ledger.append_step(
            slot,
            "send",
            "DELIVERY_UNKNOWN",
            _elapsed(),
            card_id,
            {"reason": "intent_without_outcome"},
        )
        if not is_resend:
            finish(results, card_id, "DELIVERY_UNKNOWN", 1)
    elif state == "DELIVERY_UNKNOWN" and not is_resend:
        finish(results, card_id, "DELIVERY_UNKNOWN", 1)
    elif state == "delivered":
        ledger.append_step(slot, "done", "delivered", _elapsed(), card_id, None)
        finish(results, card_id, "DELIVERED", 0)

    if not no_wait:
        while clock() < slot:
            remaining = (slot - clock()).total_seconds()
            sleep(min(_KILL_POLL_S, max(0.0, remaining)))
            if _killed(kill):
                killed_at("card")
    if _killed(kill):
        killed_at("card")
    if clock() > slot + timedelta(minutes=30):
        ledger.append_step(slot, "done", "STALE_CARD", _elapsed(), card_id, None)
        finish(results, card_id, "STALE_CARD", 0)
    if night_cutoff and carries_disconnect and disconnect_send_blocked(True, clock()):
        _cutoff_done()

    delays = (0.0, *_SEND_RETRY_DELAYS)
    for attempt, wait_s in enumerate(delays, start=1):
        if attempt > 1:
            sleep(wait_s)
            if (
                night_cutoff
                and carries_disconnect
                and disconnect_send_blocked(True, clock())
            ):
                _cutoff_done()
            if clock() > slot + timedelta(minutes=30):
                _stale_done()
        if _killed(kill):
            killed_at("send_intent")
        detail: dict[str, object] = {"try": str(attempt)}
        if is_resend:
            detail["resend_unknown"] = "1"
        ledger.append_step(slot, "send_intent", "intent", _elapsed(), card_id, detail)
        try:
            sent = send_card(card, chart, db_path=ledger.db_path, client=seams.telegram)
        except TelegramDeliveryUnknown as exc:
            ledger.append_step(
                slot,
                "send",
                "DELIVERY_UNKNOWN",
                _elapsed(),
                card_id,
                {"reason": type(exc).__name__},
            )
            finish(results, card_id, "DELIVERY_UNKNOWN", 1)
        except (TelegramRateLimited, TelegramTransportError) as exc:
            ledger.append_step(
                slot,
                "send",
                "SEND_NOT_SENT",
                _elapsed(),
                card_id,
                {"reason": type(exc).__name__},
            )
            if attempt == len(delays):
                finish(results, card_id, "SEND_NOT_SENT", 1)
            continue
        except sqlite3.Error as exc:
            ledger.append_step(
                slot,
                "send",
                "SEND_NOT_SENT",
                _elapsed(),
                card_id,
                {"reason": type(exc).__name__},
            )
            if attempt == len(delays):
                finish(results, card_id, "SEND_NOT_SENT", 1)
            continue
        except (
            TelegramAuthError,
            TelegramConfigError,
            TelegramApiError,
        ) as exc:
            ledger.append_step(
                slot,
                "send",
                "SEND_REFUSED",
                _elapsed(),
                card_id,
                {"reason": type(exc).__name__},
            )
            finish(results, card_id, "SEND_REFUSED", 1)
        except Exception as exc:  # noqa: BLE001 -- class name only, never value
            ledger.append_step(
                slot,
                "send",
                "DELIVERY_UNKNOWN",
                _elapsed(),
                card_id,
                {"reason": type(exc).__name__},
            )
            finish(results, card_id, "DELIVERY_UNKNOWN", 1)
        remaining = (slot + timedelta(minutes=30) - clock()).total_seconds()
        try:
            ledger.append_step(
                slot,
                "send",
                "delivered",
                _elapsed(),
                card_id,
                {"message_id": str(sent.message_id)},
                timeout_s=max(0.1, remaining),
            )
        except LedgerWriteBlocked:
            print(
                f"slot={iso} code=LEDGER_WRITE_BLOCKED"
                f" message={sent.message_id} kill={kill_flag}"
            )
            raise _SlotDone(1)
        done_code = "DISCONNECT_DAILY_CAP" if cap_hit else "delivered"
        ledger.append_step(slot, "done", done_code, _elapsed(), card_id, None)
        finish(results, card_id, done_code if cap_hit else None, 0)
    finish(results, card_id, "SEND_NOT_SENT", 1)


def check_slot(
    *,
    slot: datetime,
    db_path: Path | str | None,
    seams: Seams,
) -> int:
    """Read the ledger only; print one line, exit with the pinned code."""
    iso = slot.isoformat()
    real_db = resolve_db_path(Path(db_path) if db_path else None)
    lock_path = Path(str(real_db) + ".run-slot.lock")

    def _held() -> bool:
        try:
            probe = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            return False
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(probe)
            return True
        try:
            fcntl.flock(probe, fcntl.LOCK_UN)
        finally:
            os.close(probe)
        return False

    def _say(code: str) -> int:
        print(f"slot={iso} code={code}")
        return _check_exit(code)

    if _held():
        polls = max(1, int(seams.check_timeout_s / seams.check_poll_s) + 1)
        for _ in range(polls):
            seams.sleep(seams.check_poll_s)
            if not _held():
                break
        else:
            print(f"slot={iso} code=SLOT_STILL_RUNNING")
            return 4

    ledger = SlotLedger(real_db, sleep=seams.ledger_sleep, clock=seams.ledger_clock)
    rows = ledger.rows_for_slot(slot)
    if not rows:
        if classify_slot(slot) != "ok":
            print(f"slot={iso} code=SLOT_NOT_PINNED")
            return 0
        print(f"slot={iso} code=NO_RUN")
        return 1
    if rows[-1].outcome == "killed":
        print(f"slot={iso} code=killed")
        return 0
    state = ledger.send_state(slot)
    done = [row.outcome for row in rows if row.step == "done"]
    if state == "intent_open" or state == "DELIVERY_UNKNOWN":
        print(f"slot={iso} code=DELIVERY_UNKNOWN")
        return 1
    if state in ("SEND_NOT_SENT", "SEND_REFUSED"):
        print(f"slot={iso} code={state}")
        return 1
    if done:
        last = "DELIVERED" if done[-1] == "delivered" else done[-1]
        if last in _ALERT_ONE:
            return _say(last)
        if last in _EXPLAINED_ZERO:
            return _check_degraded(ledger, slot, iso, last, 0)
        return _say("UNEXPLAINED")
    if state == "delivered":
        return _check_degraded(ledger, slot, iso, "DELIVERED", 0)
    card_rows = [row for row in rows if row.step == "card"]
    if card_rows and card_rows[-1].outcome == "COMMITMENT_GONE":
        return _say("COMMITMENT_GONE")
    coded = [row.outcome for row in rows if row.outcome in _ALERT_ONE]
    if coded:
        return _say(coded[-1])
    return _say("UNEXPLAINED")


def _check_exit(code: str) -> int:
    if code in _EXPLAINED_ZERO or code in ("DEGRADED_REPEAT",):
        return 0
    if code in ("SLOT_STILL_RUNNING",):
        return 4
    if code in ("DEGRADED",):
        return 5
    return 1


def _check_degraded(
    ledger: SlotLedger, slot: datetime, iso: str, code: str, exit_code: int
) -> int:
    """Report a degraded slot once per Madrid day, then stay quiet."""
    degraded: set[str] = set()
    for row in ledger.rows_for_slot(slot):
        if row.step == "facts_model" and row.outcome in _DEGRADED_FACTS:
            degraded.add(row.outcome)
        if row.step.startswith("propose_") and "wonder_down=1" in row.detail.split(" "):
            degraded.add("WONDER_TRANSPORT")
        if row.step == "hour" and parse_detail(row.detail).get("calendar_stale") == "1":
            degraded.add("CALENDAR_STALE")
    if any(side.kind == "fallback" for side in ledger.slot_cards_for_slot(slot)):
        degraded.add("FALLBACK_SIDE")
    if not degraded:
        print(f"slot={iso} code={code}")
        return exit_code
    day = slot.astimezone(MADRID).date()
    fresh_codes = sorted(
        item for item in degraded if not ledger.watchdog_alerted(item, day)
    )
    if fresh_codes:
        ledger.append_watchdog(slot, fresh_codes[0])
        print(f"slot={iso} code=DEGRADED detail={fresh_codes[0]}")
        return 5
    print(f"slot={iso} code=DEGRADED_REPEAT")
    return 0


__all__ = [
    "CALENDAR_STALE_AFTER",
    "CHECK_POLL_S",
    "CHECK_TIMEOUT_S",
    "FACTS_SLOT_RESERVE",
    "MADRID",
    "MODEL_PARAMS",
    "PROPOSE_SLOT_RESERVE",
    "PROPOSE_STEP_BUDGET",
    "SLOT_LIMITS",
    "SLOT_TIMES",
    "STALE_AFTER_S",
    "DeadlineWonderClient",
    "EligibilityState",
    "FactsChildResult",
    "Seams",
    "calendar_is_stale",
    "check_slot",
    "classify_slot",
    "disconnect_send_blocked",
    "eligible_commitments",
    "plan_hour",
    "production_facts_runner",
    "rank_and_block",
    "rebuild_state",
    "run_slot",
    "slot_from_today",
    "slot_profiles",
    "state_json",
    "validate_slot",
]
