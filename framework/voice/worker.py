"""Ticket 14 Step 5: the voice worker.

One daemon thread per ``poll --voice`` process claims durable voice rows
and runs each note through the pinned step order: match the card, kill
check, download and transcribe unless stored, pre-scan before the
transcript is stored, kill check, compile unless stored, validate, kill
check, apply with the row's ``applied_at``, kill check, guards cheapest
first, re-proposal with one thread per affected profile, post-check, the
corrected card sent silently with ``new_card_id`` recorded before the
reply, the reply, then the row close and exactly one ``app.voice_note``
event. An unexpected exception in ``process_one`` is caught in the worker
loop as a transient ``worker_error`` with no exception text stored,
printed, or logged, and the thread lives on.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from framework.briefing.commitments import LoadedCommitments, load_commitments
from framework.briefing.context import PrivateTerms, ProfileLimits, load_private_terms
from framework.briefing.gate import scan_outbound_text
from framework.briefing.schemas import Commitment
from framework.collectors.common import as_dict, event_id, subject_id_from_env
from framework.cycle import forbidden_literals_for, run_proposals
from framework.cycle.card_build import build_statements
from framework.cycle.orchestrator import EligibilityState, eligible_commitments
from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
from framework.proposal.core import (
    MetaUnavailableError,
    ModelParams,
    OutboundBlocked,
    ProposalResult,
    WonderClient,
)
from framework.proposal.local_retry import LocalRetryClient
from framework.proposal.muse_client import MuseExecClient
from framework.proposal.prompt import display_value
from framework.schemas.events import (
    AppCorrectionData,
    AppFactDisputeData,
    AppTapData,
    AppVoiceNoteData,
    Event,
)
from framework.store import ConflictingEvent, EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore, StoredResult
from framework.telegram.client import (
    VOICE_MAX_BYTES,
    TelegramClient,
    TelegramDeliveryUnknown,
    TelegramError,
    TelegramFileUnreadable,
)
from framework.telegram.ledger import VOICE_NOTES_DDL, CardLedger
from framework.telegram.models import Card, Proposal, VoiceNote, split_messages
from framework.telegram.sample import SAMPLE_CARD
from framework.telegram.service import (
    COLLECTOR_VERSION,
    RULING_WINDOW_START,
    send_card,
)
from framework.voice.compile import compile_correction
from framework.voice.ledger import VoiceLedger, VoiceRow, retry_delay_s
from framework.voice.prompt import PromptCommitment, PromptOffer
from framework.voice.schemas import (
    CompiledCorrection,
    UnparseableCorrection,
    change_line,
    validate_compiled,
)
from framework.voice.state import (
    CommitmentStateEntry,
    DisputedCitations,
    disputed_number_displays,
    disputed_numbers,
    disputes_for_cycle,
    load_voice_state,
    statement_holds_number,
)
from framework.voice.transcribe import MuseVoiceTranscriber

logger = logging.getLogger(__name__)

MADRID = ZoneInfo("Europe/Madrid")
_EARLY = datetime(2000, 1, 1, tzinfo=UTC)
_FAR_FUTURE_DAYS = 2
_GIVE_UP_AFTER = timedelta(hours=24)
_MODE_RETRY_AFTER_S = 60
_MAX_CORRECTED_PER_SLOT = 3
_PRIVATE_TERMS_UNAVAILABLE = "L1_PRIVATE_TERMS_UNAVAILABLE"

ProposeFn = Callable[..., tuple[ProposalResult, ...]]
ClientFactory = Callable[[tuple[str, ...], bool], WonderClient]

_SECTION_ORDER = ("overall_state", "since_last", "working", "not_working")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class VoiceDeps:
    """Everything one note needs: stores by path, models, limits, clock."""

    db_path: Path | None
    subject_id: str
    chat_id: int
    client: TelegramClient
    transcriber: MuseVoiceTranscriber
    make_compile_client: ClientFactory
    make_wonder_client: ClientFactory
    propose_fn: ProposeFn
    load_commitments_fn: Callable[[], LoadedCommitments]
    load_private_terms_fn: Callable[[], PrivateTerms]
    forbidden_literals_fn: Callable[[EventStore, str, datetime], tuple[str, ...]] = (
        forbidden_literals_for
    )
    compile_model: str = "muse-spark-1.3"
    compile_effort: str = "minimal"
    correction_model: str = "muse-wonder-1.0"
    correction_effort: str = "low"
    limits: ProfileLimits = field(
        default_factory=lambda: ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start=dtime(13, 0),
            allowed_end=dtime(23, 30),
        )
    )
    stale_after_s: float = 43200.0
    kill_file: Path | None = None
    now_fn: Callable[[], datetime] = _utcnow


def make_voice_handler(wake: threading.Event) -> Callable[[VoiceNote], None]:
    """The poller's voice branch calls this; it only wakes the worker."""

    def _handle(_note: VoiceNote) -> None:
        wake.set()

    return _handle


def build_voice_deps(
    environ: Mapping[str, str],
    *,
    client: TelegramClient,
    db_path: Path | None,
    now_fn: Callable[[], datetime] | None = None,
    transcriber: MuseVoiceTranscriber | None = None,
    make_compile_client: ClientFactory | None = None,
    make_wonder_client: ClientFactory | None = None,
    propose_fn: ProposeFn | None = None,
    compile_model: str = "muse-spark-1.3",
    compile_effort: str = "minimal",
    correction_model: str = "muse-wonder-1.0",
    correction_effort: str = "low",
) -> VoiceDeps:
    """One public wiring function: ``poll --voice`` and the harness share it."""
    env = dict(environ)
    clock = now_fn if now_fn is not None else _utcnow
    subject = (env.get("IKIGAI_SUBJECT_ID") or subject_id_from_env()).strip()
    try:
        chat_id = int((env.get("TELEGRAM_CHAT_ID") or "").strip())
    except ValueError:
        chat_id = 0
    kill_raw = (env.get("IKIGAI_KILL_FILE") or "").strip()
    kill_file = Path(kill_raw) if kill_raw else None

    def _load_terms() -> PrivateTerms:
        return load_private_terms(env)

    def _load_commitments() -> LoadedCommitments:
        terms = _load_terms()
        store = EventStore(db_path)
        try:
            literals = forbidden_literals_for(store, subject, clock())
        finally:
            store.close()
        return load_commitments(
            env,
            private_terms=terms.terms,
            forbidden_raw_literals=literals,
        )

    def _compile_factory(terms: tuple[str, ...], available: bool) -> WonderClient:
        return MuseExecClient(
            private_terms=terms, private_terms_available=available, timeout_s=60.0
        )

    def _wonder_factory(terms: tuple[str, ...], available: bool) -> WonderClient:
        # The Wonder call alone retries fast local start failures in-client;
        # the compile call keeps its own 5 s wait and tries again, so it
        # stays unwrapped. Retried failures are recorded in _repropose.
        # A timed-out call is not retried here, unlike the slot path (D26).
        return LocalRetryClient(
            MuseExecClient(
                private_terms=terms,
                private_terms_available=available,
                timeout_s=60.0,
            )
        )

    return VoiceDeps(
        db_path=db_path,
        subject_id=subject,
        chat_id=chat_id,
        client=client,
        transcriber=transcriber
        if transcriber is not None
        else MuseVoiceTranscriber(
            ffmpeg_bin=env.get("FFMPEG_BIN") or "ffmpeg",
            environ=env,
        ),
        make_compile_client=make_compile_client
        if make_compile_client is not None
        else _compile_factory,
        make_wonder_client=make_wonder_client
        if make_wonder_client is not None
        else _wonder_factory,
        propose_fn=propose_fn if propose_fn is not None else run_proposals,
        load_commitments_fn=_load_commitments,
        load_private_terms_fn=_load_terms,
        compile_model=compile_model,
        compile_effort=compile_effort,
        correction_model=correction_model,
        correction_effort=correction_effort,
        kill_file=kill_file,
        now_fn=clock,
    )


class _TerminalOutcome(Exception):
    """Unwind to a terminal close with this outcome code."""

    def __init__(self, outcome: str) -> None:
        super().__init__("voice terminal")
        self.outcome = outcome


class _TransientWait(Exception):
    """Unwind to the transient wait path; attempts are counted."""


class _KilledWait(Exception):
    """Unwind to the kill-switch wait path; no attempt is counted."""


class _ModeWait(Exception):
    """Unwind to the contributor-mode wait path; no attempt is counted."""


class _SendFailed(Exception):
    """One reply send did not land."""


class _ReproposalFailed(Exception):
    """The corrected card cannot stand; closed with its pinned reply."""


@dataclass
class _Ctx:
    """Mutable per-note run state; the row stays the durable truth."""

    deps: VoiceDeps
    voice: VoiceLedger
    cards: CardLedger
    message_id: int
    received: datetime
    said: datetime
    now: datetime
    applied_at: datetime | None = None
    steps: dict[str, float] = field(default_factory=dict[str, float])
    newest_id: str | None = None
    newest: Card | None = None
    slot: datetime | None = None
    transcript: str | None = None
    correction: CompiledCorrection | None = None
    validation_codes: tuple[str, ...] = ()
    new_card_id: str | None = None
    terms: tuple[str, ...] = ()
    terms_available: bool = False
    literals: tuple[str, ...] = ()


def _killed(deps: VoiceDeps) -> bool:
    """True while the kill file exists; failures close over silence."""
    if deps.kill_file is None:
        return False
    try:
        return deps.kill_file.exists()
    except OSError:
        return True


def _latest_sent_card(db_path: Path) -> tuple[str, datetime | None]:
    """Newest mapped card and its send instant; empty when none was sent."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(VOICE_NOTES_DDL)
        row = conn.execute(
            "SELECT card_id, sent_at FROM telegram_card_messages"
            " ORDER BY sent_at DESC, message_id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return ("", None)
    try:
        sent_at = datetime.fromisoformat(str(row[1]))
    except ValueError:
        return (str(row[0]), None)
    return (str(row[0]), sent_at)


def _walk_forward(ledger: VoiceLedger, card_id: str) -> str:
    """Follow matched-to-new links to the newest descendant card."""
    current = card_id
    seen = {current}
    for _ in range(100):
        nxt: VoiceRow | None = None
        for row in ledger.rows_for_card(current):
            if (
                row.matched_card_id == current
                and row.new_card_id
                and (nxt is None or row.message_id > nxt.message_id)
            ):
                nxt = row
        if nxt is None:
            return current
        nid = nxt.new_card_id
        if not nid:
            return current
        current = nid
        if current in seen:
            return current
        seen.add(current)
    return current


def match_card(
    note: VoiceRow,
    *,
    ledger: VoiceLedger,
    card_ledger: CardLedger,
    store: EventStore,
    subject_id: str,
    now: datetime,
) -> str | None:
    """Match a note to the newest card in its chain, or None.

    Order: the reply target in the message map, then the latest ``wrong``
    tap (only when no card was sent after that tap was handled), then the
    latest sent card. The sample card is never mapped and never matches.
    """
    if note.reply_to_message_id is not None:
        mapped = card_ledger.load_card_message(note.reply_to_message_id)
        if mapped is not None and mapped != SAMPLE_CARD.card_id:
            return _walk_forward(ledger, mapped)
    try:
        taps = store.events_between(
            subject_id,
            RULING_WINDOW_START,
            now + timedelta(days=_FAR_FUTURE_DAYS),
            types=["app.tap"],
        )
    except Exception:  # noqa: BLE001 -- a store failure here only loses a hint
        taps = []
    latest: Event | None = None
    for event in taps:
        data = event.data
        if not isinstance(data, AppTapData) or data.target != "wrong":
            continue
        if data.block_id == SAMPLE_CARD.card_id:
            continue
        if latest is None or (event.time, event.id) > (latest.time, latest.id):
            latest = event
    if latest is not None and isinstance(latest.data, AppTapData):
        _, newest_sent_at = _latest_sent_card(card_ledger.db_path)
        if newest_sent_at is None or latest.time >= newest_sent_at:
            return _walk_forward(ledger, latest.data.block_id)
    newest_id, _ = _latest_sent_card(card_ledger.db_path)
    if newest_id and newest_id != SAMPLE_CARD.card_id:
        return _walk_forward(ledger, newest_id)
    return None


def _parse_instant(value: str | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


def _load_steps(row: VoiceRow) -> dict[str, float]:
    if not row.step_seconds:
        return {}
    try:
        loaded: Any = json.loads(row.step_seconds)
    except ValueError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    table = cast("dict[Any, Any]", loaded)
    out: dict[str, float] = {}
    try:
        for key, value in table.items():
            item: Any = value
            out[str(key)] = float(item)
    except (ValueError, TypeError):
        return {}
    return out


def _bump(steps: dict[str, float], name: str, amount: float) -> None:
    steps[name] = steps.get(name, 0.0) + max(amount, 0.0)


def _ensure_terms(ctx: _Ctx) -> None:
    """Load private terms and literals; unavailable terms wait, never block."""
    if ctx.terms_available or ctx.terms:
        return
    terms = ctx.deps.load_private_terms_fn()
    ctx.terms = terms.terms
    ctx.terms_available = terms.available
    if not terms.available:
        raise _TransientWait
    store = EventStore(ctx.deps.db_path)
    try:
        ctx.literals = ctx.deps.forbidden_literals_fn(
            store, ctx.deps.subject_id, ctx.now
        )
    finally:
        store.close()


def _download_audio(ctx: _Ctx, row: VoiceRow) -> bytes:
    """Fetch one voice file; oversize or 400/404 reads as unreadable."""
    if row.file_size is not None and row.file_size > VOICE_MAX_BYTES:
        raise _TerminalOutcome("unreadable")
    if not row.file_id:
        raise _TerminalOutcome("unreadable")
    start = time.monotonic()
    try:
        path = ctx.deps.client.get_file_path(row.file_id)
    except TelegramFileUnreadable:
        raise _TerminalOutcome("unreadable") from None
    except TelegramError:
        raise _TransientWait from None
    try:
        audio = ctx.deps.client.download_file(
            path, max_bytes=VOICE_MAX_BYTES, timeout_s=30.0
        )
    except TelegramFileUnreadable:
        raise _TerminalOutcome("unreadable") from None
    except TelegramError:
        raise _TransientWait from None
    _bump(ctx.steps, "download", time.monotonic() - start)
    return audio


def _transcribe_step(ctx: _Ctx, row: VoiceRow) -> str:
    """Download and transcribe; silence and unreadable clips end the note."""
    audio = _download_audio(ctx, row)
    result = ctx.deps.transcriber.transcribe(audio)
    _bump(ctx.steps, "convert", result.convert_s)
    _bump(ctx.steps, "transcribe", result.transcribe_s)
    if result.kind == "mode_not_confirmed":
        raise _ModeWait
    if result.kind == "unavailable":
        raise _TransientWait
    if result.kind == "silence":
        raise _TerminalOutcome("silence")
    if result.kind == "unreadable":
        raise _TerminalOutcome("unreadable")
    return result.text


def _prescan_and_store(ctx: _Ctx, transcript: str) -> None:
    """Scan before storing: a real hit stores no transcript and ends blocked."""
    _ensure_terms(ctx)
    codes = scan_outbound_text(
        transcript,
        private_terms=ctx.terms,
        private_terms_available=ctx.terms_available,
        forbidden_raw_literals=ctx.literals,
    )
    if _PRIVATE_TERMS_UNAVAILABLE in codes:
        raise _TransientWait
    if codes:
        raise _TerminalOutcome("outbound_blocked")
    ctx.voice.update(ctx.message_id, transcript=transcript)
    ctx.transcript = transcript


def _send_text(ctx: _Ctx, body: str) -> float:
    """Send one reply in my chat; raises when any part does not land."""
    spent = 0.0
    for part in split_messages([body]):
        start = time.monotonic()
        try:
            result = ctx.deps.client.call(
                "sendMessage",
                {
                    "chat_id": ctx.deps.chat_id,
                    "text": part,
                    "disable_notification": True,
                    "link_preview_options": {"is_disabled": True},
                    "reply_parameters": {
                        "message_id": ctx.message_id,
                        "allow_sending_without_reply": True,
                    },
                },
                timeout_s=10.0,
                attempts=2,
            )
        except TelegramError:
            raise _SendFailed from None
        spent += time.monotonic() - start
        message = as_dict(result)
        if message is None or not isinstance(message.get("message_id"), int):
            raise _SendFailed
    return spent


def _send_simple(ctx: _Ctx, body: str) -> bool:
    """Best-effort send for waiting replies; False when it did not land."""
    try:
        _send_text(ctx, body)
    except _SendFailed:
        return False
    return True


def _tell_waiting_once(
    deps: VoiceDeps,
    voice: VoiceLedger,
    message_id: int,
    *,
    attempts: int,
    waiting_told: int,
) -> None:
    """Send the D5 waiting reply once per note, never while killed.

    Shared by the transient wait and the worker-error wait: after the
    third attempt the note tells me once through ``waiting_told``. No
    Telegram send happens while the kill switch is on (D23).
    """
    if _killed(deps):
        return
    if attempts < 3 or waiting_told:
        return
    now = deps.now_fn()
    ctx = _Ctx(
        deps=deps,
        voice=voice,
        cards=CardLedger(deps.db_path),
        message_id=message_id,
        received=now,
        said=now,
        now=now,
    )
    if _send_simple(ctx, _WAITING_REPLY):
        voice.update(message_id, waiting_told=1)


_WAITING_REPLY = (
    "That note is saved, but I can't process it yet. "
    "Nothing has changed. I'll keep trying."
)
_MODE_REPLY = (
    "I can't confirm Contributor mode is off, so this note hasn't gone "
    "anywhere. It's saved and runs once that's fixed."
)


def _wait_killed(ctx: _Ctx) -> str:
    """Park the note: no send, no attempt counted, looked at again soon."""
    ctx.voice.update(
        ctx.message_id,
        status="pending",
        next_attempt_at=None,
        outcome="killed_waiting",
        step_seconds=dict(ctx.steps),
    )
    return "killed_waiting"


def _wait_transient(ctx: _Ctx, row: VoiceRow) -> str:
    """Count one attempt and park the note; the third failure tells me once."""
    now = ctx.deps.now_fn()
    if now - ctx.received > _GIVE_UP_AFTER:
        raise _TerminalOutcome("gave_up")
    attempts = (row.attempts or 0) + 1
    delay = retry_delay_s(attempts)
    ctx.voice.update(
        ctx.message_id,
        status="pending",
        attempts=attempts,
        next_attempt_at=(now + timedelta(seconds=delay)).isoformat(),
        step_seconds=dict(ctx.steps),
        outcome=None,
    )
    _tell_waiting_once(
        ctx.deps,
        ctx.voice,
        ctx.message_id,
        attempts=attempts,
        waiting_told=row.waiting_told or 0,
    )
    return "waiting"


def _wait_mode(ctx: _Ctx, row: VoiceRow) -> str:
    """Park the note without counting an attempt; told once per note."""
    if _killed(ctx.deps):
        return _wait_killed(ctx)
    now = ctx.deps.now_fn()
    ctx.voice.update(
        ctx.message_id,
        status="pending",
        next_attempt_at=(now + timedelta(seconds=_MODE_RETRY_AFTER_S)).isoformat(),
        step_seconds=dict(ctx.steps),
        outcome="mode_not_confirmed",
    )
    if not row.waiting_told and _send_simple(ctx, _MODE_REPLY):
        ctx.voice.update(ctx.message_id, waiting_told=1)
    return "mode_not_confirmed"


def _stored_briefings(
    ctx: _Ctx,
) -> tuple[tuple[PromptOffer, ...], tuple[str, ...], list[StoredResult]]:
    """Offers, cited claim texts, and stored rows for the newest card."""
    if ctx.newest is None:
        return ((), (), [])
    offers = tuple(
        PromptOffer(label=side.letter, title=side.title, slot=side.start)
        for side in ctx.newest.proposals
    )
    store = ProposalStore(ctx.deps.db_path)
    try:
        stored = list(store.results_for_slot(ctx.deps.subject_id, ctx.newest.slot))
    finally:
        store.close()
    statements: list[str] = []
    for result in stored:
        if result.briefing is None:
            continue
        for section in result.briefing.sections:
            if section.type not in _SECTION_ORDER:
                continue
            statements.extend(claim.text for claim in section.claims)
    return (offers, tuple(statements), stored)


def _compile_step(ctx: _Ctx, row: VoiceRow) -> None:
    """Compile the stored transcript once; failures end or wait the note."""
    _ensure_terms(ctx)
    loaded = ctx.deps.load_commitments_fn()
    if not loaded.available:
        raise _TransientWait
    commitments = loaded.commitments
    offers, statements, _ = _stored_briefings(ctx)
    said_local = ctx.said.astimezone(MADRID)
    client = ctx.deps.make_compile_client(ctx.terms, ctx.terms_available)
    start = time.monotonic()
    try:
        outcome = compile_correction(
            client=client,
            transcript=ctx.transcript or "",
            commitments=[
                PromptCommitment(id=item.id, title=item.title, side=item.profile_id)
                for item in commitments
            ],
            offers=offers,
            statements=statements,
            now_local=said_local,
            model=ctx.deps.compile_model,
            effort=ctx.deps.compile_effort,
            private_terms=ctx.terms,
            private_terms_available=ctx.terms_available,
            forbidden_raw_literals=ctx.literals,
        )
    except (MetaUnavailableError, OutboundBlocked) as exc:
        raise _TransientWait from exc
    # ``compile_correction`` maps transport trouble to ``unavailable`` and a
    # full-prompt scan hit to ``blocked``; anything else escaping it is a bug.
    _bump(ctx.steps, "compile", time.monotonic() - start)
    if outcome.kind == "unavailable":
        raise _TransientWait
    if outcome.kind == "blocked":
        raise _TerminalOutcome("outbound_blocked")
    if outcome.kind == "unparseable" or isinstance(
        outcome.correction, UnparseableCorrection
    ):
        ctx.voice.update(ctx.message_id, validation_codes=[])
        raise _TerminalOutcome("not_understood")
    correction = outcome.correction
    assert correction is not None
    codes = validate_compiled(
        correction,
        [item.id for item in commitments],
        private_terms=ctx.terms,
        private_terms_available=ctx.terms_available,
        forbidden_raw_literals=ctx.literals,
    )
    try:
        version = client.transport_version
    except Exception:  # noqa: BLE001 -- a version probe never fails a note
        version = None
    try:
        rules_flag = getattr(client, "harness_rules_file", None)
    except Exception:  # noqa: BLE001 -- a flag probe never fails a note
        rules_flag = None
    ctx.voice.update(
        ctx.message_id,
        operation=correction.operation,
        commitment_id=correction.commitment_id,
        until_value=correction.until,
        question=correction.question,
        validation_codes=list(codes),
        compile_model=ctx.deps.compile_model,
        compile_effort=ctx.deps.compile_effort,
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        muse_version=version,
        rules_file_present=None if rules_flag is None else int(bool(rules_flag)),
    )
    ctx.correction = correction
    ctx.validation_codes = codes
    if codes:
        raise _TerminalOutcome("not_understood")
    if correction.operation == "none":
        raise _TerminalOutcome("question")


def _took_line(ctx: _Ctx) -> str:
    took = (ctx.deps.now_fn() - ctx.received).total_seconds()
    return f"Took {took:.1f}s."


def _finish(
    ctx: _Ctx,
    row: VoiceRow,
    *,
    outcome: str,
    body: str,
    terminal_on_send_failure: str | None = None,
) -> str:
    """Send the reply, close the row, and append the one voice_note event."""
    full = f"{body} {_took_line(ctx)}"
    try:
        send_s = _send_text(ctx, full)
    except _SendFailed:
        if terminal_on_send_failure is None:
            raise _TransientWait from None
        outcome = terminal_on_send_failure
        send_s = 0.0
    else:
        _bump(ctx.steps, "send_reply", send_s)
    total = (ctx.deps.now_fn() - ctx.received).total_seconds()
    step_total = sum(ctx.steps.values())
    arrival_lag = (ctx.received - ctx.said).total_seconds()
    ctx.voice.update(
        ctx.message_id,
        status="done" if outcome != "gave_up" else "gave_up",
        outcome=outcome,
        step_seconds=dict(ctx.steps),
        total_s=total,
        unaccounted_s=total - step_total,
        arrival_lag_s=arrival_lag,
        new_card_id=ctx.new_card_id,
    )
    _append_voice_event(ctx, row, outcome=outcome, total_s=total)
    return outcome


def _append_voice_event(
    ctx: _Ctx, row: VoiceRow, *, outcome: str, total_s: float
) -> None:
    """Append ``app.voice_note`` exactly once; a conflict is already recorded."""
    try:
        codes = tuple(json.loads(row.validation_codes or "[]"))
    except ValueError:
        codes = ()
    fresh = ctx.voice.load(ctx.message_id)
    validation = ctx.validation_codes or codes
    if fresh is not None and fresh.validation_codes:
        try:
            validation = tuple(json.loads(fresh.validation_codes))
        except ValueError:
            pass
    rules_present: bool | None = None
    if fresh is not None and fresh.rules_file_present is not None:
        rules_present = bool(fresh.rules_file_present)
    moment = ctx.deps.now_fn()
    message_id = ctx.message_id
    event = Event(
        id=event_id("telegram", f"voice-note:{message_id}"),
        subject_id=ctx.deps.subject_id,
        source="telegram",
        type="app.voice_note",
        time=moment,
        source_id=f"voice-note:{message_id}",
        data=AppVoiceNoteData(
            message_id=message_id,
            outcome=outcome,
            operation=fresh.operation if fresh else None,
            commitment_id=fresh.commitment_id if fresh else None,
            until=fresh.until_value if fresh else None,
            old_card_id=ctx.newest_id,
            new_card_id=ctx.new_card_id,
            step_seconds=dict(ctx.steps),
            total_s=max(total_s, 0.0),
            compile_model=fresh.compile_model if fresh else None,
            compile_effort=fresh.compile_effort if fresh else None,
            muse_version=fresh.muse_version if fresh else None,
            rules_file_present=rules_present,
            validation_codes=tuple(str(code) for code in validation),
            reported_by="user",
        ),
        tier="private",
        collected_at=moment,
        collector_version=COLLECTOR_VERSION,
    )
    store = EventStore(ctx.deps.db_path)
    try:
        try:
            store.append_event(event)
        except ConflictingEvent:
            pass
    finally:
        store.close()


def _slot_rows(deps: VoiceDeps, card_id: str) -> tuple[SlotCardRow, ...]:
    """The card's ``slot_cards`` rows, or () when none were saved."""
    if deps.db_path is None:
        return ()
    return SlotLedger(deps.db_path).slot_cards_for_card(card_id)


def _profile_id_for_side(
    side: Proposal,
    commitments: Sequence[Commitment],
    rows: Sequence[SlotCardRow] = (),
) -> str | None:
    """Match a card side to a profile id through its ``slot_cards`` row.

    The row is keyed by the side's letter, so a title accidentally shared
    with the other side cannot misroute the match. A relettered lone side
    keeps its display string but not its letter, so a letter hit whose
    profile disagrees with the display falls through to the display match.
    """
    for row in rows:
        if row.letter == side.letter:
            if row.profile_id.casefold() == side.profile.casefold():
                return row.profile_id
            break
    for row in rows:
        if row.profile_id.casefold() == side.profile.casefold():
            return row.profile_id
    # No rows, or rows that know nothing of this side: a card from before
    # slot rows were written keeps the display-string comparison that stood
    # in until ``slot_cards`` existed.
    for commitment in commitments:
        if side.profile.casefold() == commitment.profile_id.casefold():
            return commitment.profile_id
    return None


def _offered_side(
    newest: Card,
    commitments: Sequence[Commitment],
    commitment: Commitment,
    rows: Sequence[SlotCardRow] = (),
) -> Proposal | None:
    """The side that offered this commitment, or None when it did not."""
    if rows:
        by_letter = {row.letter: row for row in rows}
        for side in newest.proposals:
            row = by_letter.get(side.letter)
            if row is not None and row.commitment_id == commitment.id:
                return side
        return None
    # No rows: a card from before slot rows were written keeps the
    # display-string and title comparison that stood in until
    # ``slot_cards`` existed.
    for side in newest.proposals:
        if side.profile.casefold() != commitment.profile_id.casefold():
            continue
        if side.title == commitment.title:
            return side
    return None


def _apply_correction(ctx: _Ctx, row: VoiceRow) -> None:
    """Append the one correction event; a resumed append dedupes by identity."""
    correction = ctx.correction
    assert correction is not None and correction.commitment_id is not None
    assert ctx.slot is not None
    assert ctx.applied_at is not None
    start = time.monotonic()
    source_id = f"voice:{ctx.message_id}"
    event = Event(
        id=event_id("telegram", source_id),
        subject_id=ctx.deps.subject_id,
        source="telegram",
        type="app.correction",
        time=ctx.applied_at,
        source_id=source_id,
        data=AppCorrectionData(
            commitment_id=correction.commitment_id,
            operation=correction.operation,  # type: ignore[arg-type]
            until=correction.until,  # type: ignore[arg-type]
            slot=ctx.slot,
            said_at=ctx.said,
            message_id=ctx.message_id,
            reported_by="user",
        ),
        tier="private",
        collected_at=ctx.applied_at,
        collector_version=COLLECTOR_VERSION,
    )
    store = EventStore(ctx.deps.db_path)
    try:
        try:
            store.append_event(event)
        except ConflictingEvent:
            pass
    finally:
        store.close()
    _bump(ctx.steps, "apply", time.monotonic() - start)


def _later_note_stands(ctx: _Ctx, commitment_id: str) -> bool:
    """True when a later-said correction for this commitment is on record."""
    mine = (ctx.said, ctx.message_id)
    store = EventStore(ctx.deps.db_path)
    try:
        events = store.events_between(
            ctx.deps.subject_id,
            _EARLY,
            ctx.now + timedelta(days=_FAR_FUTURE_DAYS),
            types=["app.correction"],
        )
    finally:
        store.close()
    for event in events:
        data = event.data
        if not isinstance(data, AppCorrectionData):
            continue
        if data.commitment_id != commitment_id:
            continue
        if (data.said_at, data.message_id) > mine:
            return True
    return False


def _apply_disputes(
    ctx: _Ctx, stored: list[StoredResult]
) -> tuple[int, list[tuple[str, float, str]]]:
    """Dispute every citation on the card, facts and metric refs alike.

    Returns the cited-claim count for the change line and the new citations.
    """
    assert ctx.newest is not None
    assert ctx.applied_at is not None
    start = time.monotonic()
    claims = 0
    fact_ids: list[str] = []
    metrics: list[tuple[str, float, str]] = []
    for result in stored:
        if result.briefing is None:
            continue
        for section in result.briefing.sections:
            if section.type not in _SECTION_ORDER:
                continue
            for claim in section.claims:
                claims += 1
                fact_ids.extend(claim.fact_ids)
                metrics.extend(
                    (ref.metric_id, ref.value, result.cycle_id)
                    for ref in claim.metric_refs
                )
    store = EventStore(ctx.deps.db_path)
    try:
        for fact_id in dict.fromkeys(fact_ids):
            try:
                store.append_event(
                    Event(
                        id=event_id("telegram", f"voice:{ctx.message_id}:{fact_id}"),
                        subject_id=ctx.deps.subject_id,
                        source="telegram",
                        type="app.fact_dispute",
                        time=ctx.applied_at,
                        source_id=f"voice:{ctx.message_id}:{fact_id}",
                        data=AppFactDisputeData(
                            fact_id=fact_id,
                            card_id=ctx.newest.card_id,
                            message_id=ctx.message_id,
                            reported_by="user",
                        ),
                        tier="private",
                        collected_at=ctx.applied_at,
                        collector_version=COLLECTOR_VERSION,
                    )
                )
            except ConflictingEvent:
                pass
        for metric_id, value, cycle_id in dict.fromkeys(metrics):
            try:
                store.append_event(
                    Event(
                        id=event_id("telegram", f"voice:{ctx.message_id}:{metric_id}"),
                        subject_id=ctx.deps.subject_id,
                        source="telegram",
                        type="app.fact_dispute",
                        time=ctx.applied_at,
                        source_id=f"voice:{ctx.message_id}:{metric_id}",
                        data=AppFactDisputeData(
                            metric_id=metric_id,
                            metric_value=value,
                            cycle_id=cycle_id,
                            card_id=ctx.newest.card_id,
                            message_id=ctx.message_id,
                            reported_by="user",
                        ),
                        tier="private",
                        collected_at=ctx.applied_at,
                        collector_version=COLLECTOR_VERSION,
                    )
                )
            except ConflictingEvent:
                pass
    finally:
        store.close()
    _bump(ctx.steps, "apply", time.monotonic() - start)
    return (claims, metrics)


def _repropose(
    ctx: _Ctx,
    profiles: Sequence[str],
    eligible: Mapping[str, tuple[Commitment, ...]],
    disputed: DisputedCitations,
) -> dict[str, ProposalResult]:
    """One thread per affected profile, each with its own stores."""
    assert ctx.slot is not None
    stored_cycle: str | None = None
    store = ProposalStore(ctx.deps.db_path)
    try:
        stored = store.results_for_slot(ctx.deps.subject_id, ctx.slot)
        if stored:
            stored_cycle = stored[0].cycle_id
    finally:
        store.close()
    if stored_cycle is not None and not _cycle_is_stored(ctx.deps, stored_cycle):
        # A manual-fallback row names ``no-cycle``, which no fact cycle
        # carries: pass no id so ``run_proposals`` takes the latest cycle
        # or records its own noop instead of raising ``UnknownCycleError``.
        stored_cycle = None
    params = ModelParams(
        first_model=ctx.deps.correction_model,
        first_effort=ctx.deps.correction_effort,
        retry_model=ctx.deps.correction_model,
        retry_effort=ctx.deps.correction_effort,
    )
    terms = PrivateTerms(terms=ctx.terms, available=ctx.terms_available)
    outcomes: dict[str, ProposalResult] = {}
    failures: list[BaseException] = []
    clients: dict[str, Any] = {}
    lock = threading.Lock()

    def _run(profile_id: str) -> None:
        store = EventStore(ctx.deps.db_path)
        fact_store = FactStore(ctx.deps.db_path)
        proposal_store = ProposalStore(ctx.deps.db_path)
        try:
            client = ctx.deps.make_wonder_client(ctx.terms, ctx.terms_available)
            with lock:
                clients[profile_id] = client
            results = ctx.deps.propose_fn(
                as_of=ctx.now,
                slot=ctx.slot,
                subject_id=ctx.deps.subject_id,
                profiles=(profile_id,),
                store=store,
                fact_store=fact_store,
                proposal_store=proposal_store,
                client=client,
                private_terms=terms,
                eligible_by_profile={profile_id: eligible.get(profile_id, ())},
                limits=ctx.deps.limits,
                models=params,
                stale_after_s=ctx.deps.stale_after_s,
                cycle_id=stored_cycle,
                parents=None,
                disputed=disputed,
            )
        except BaseException as exc:  # noqa: BLE001 -- re-raised past the join
            with lock:
                failures.append(exc)
        else:
            with lock:
                if results:
                    outcomes[profile_id] = results[0]
        finally:
            proposal_store.close()
            fact_store.close()
            store.close()

    start = time.monotonic()
    threads = [
        threading.Thread(target=_run, args=(profile_id,), daemon=True)
        for profile_id in profiles
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    _bump(ctx.steps, "repropose", time.monotonic() - start)
    _record_local_retries(ctx, clients)
    if failures:
        raise failures[0]
    return outcomes


def _record_local_retries(ctx: _Ctx, clients: Mapping[str, Any]) -> None:
    """Store each retried local start failure for the note's slot and profile.

    A store error here never fails the note: the retries are evidence, and
    the corrected card must not depend on them.
    """
    if ctx.deps.db_path is None or ctx.slot is None:
        return
    try:
        ledger = SlotLedger(ctx.deps.db_path)
    except Exception:  # noqa: BLE001 -- retry rows never fail a note
        return
    for profile_id, client in clients.items():
        for record in getattr(client, "failures", ()):
            try:
                ledger.append_local_retry(
                    ctx.slot,
                    profile_id,
                    record.attempt,
                    record.reason,
                    record.latency_ms,
                    record.exit_code,
                    record.stderr_masked,
                )
            except Exception:  # noqa: BLE001 -- retry rows never fail a note
                logger.debug("voice local retry row skipped for %s", profile_id)


def _cycle_is_stored(deps: VoiceDeps, cycle_id: str) -> bool:
    """True when a fact cycle carries this id; a missing table is no."""
    try:
        facts = FactStore(deps.db_path)
    except Exception:  # noqa: BLE001 -- no fact home means no stored cycle
        return False
    try:
        return bool(facts.runs(cycle_id))
    except sqlite3.Error:
        return False
    finally:
        facts.close()


def _voice_state(
    ctx: _Ctx,
) -> tuple[dict[str, CommitmentStateEntry], DisputedCitations]:
    """Fold corrections and disputes over a window past the handling instant.

    ``events_between`` is half-open ``[start, end)``, so the end sits well
    past the handling instant: an end of exactly ``applied_at`` would miss
    the correction just applied and the re-proposal would offer what was
    just skipped.
    """
    assert ctx.slot is not None
    store = EventStore(ctx.deps.db_path)
    try:
        return load_voice_state(
            store,
            ctx.deps.subject_id,
            start=_EARLY,
            end=ctx.now + timedelta(days=_FAR_FUTURE_DAYS),
        )
    finally:
        store.close()


def _post_check(
    ctx: _Ctx,
    stored: list[StoredResult],
    profiles: Sequence[str],
) -> None:
    """Fail closed when a new claim repeats what I disputed.

    The same two sets as ``apply_disputes``: a cited fact fails when
    disputed by id or when its stored statement holds a disputed number
    (a disputed metric citation's display value or a number from a
    disputed fact's statement), and a cited metric fails on the
    same-id-same-value rule or on a number from a disputed fact's
    statement. A disputed metric's display value fails no other
    metric.
    """
    _, disputed = _voice_state(ctx)
    fact_store = FactStore(ctx.deps.db_path)
    try:
        for result in stored:
            if result.profile_id not in profiles:
                continue
            if result.briefing is None:
                continue
            narrowed = disputes_for_cycle(
                disputed, result.cycle_id, ctx.now.astimezone(MADRID).date()
            )
            rows = fact_store.fetch_facts(result.cycle_id, result.run)
            fact_rows = tuple((row["fact_id"], row["statement"]) for row in rows)
            numbers = disputed_numbers(narrowed, fact_rows)
            fact_numbers = disputed_number_displays(fact_rows, narrowed)
            statements = {row["fact_id"]: row["statement"] for row in rows}
            for section in result.briefing.sections:
                for claim in section.claims:
                    if set(claim.fact_ids) & narrowed.fact_ids:
                        raise _ReproposalFailed
                    for fact_id in claim.fact_ids:
                        statement = statements.get(fact_id)
                        if statement is not None and statement_holds_number(
                            statement, numbers
                        ):
                            raise _ReproposalFailed
                    for ref in claim.metric_refs:
                        if any(
                            item.metric_id == ref.metric_id and item.value == ref.value
                            for item in narrowed.metrics
                        ):
                            raise _ReproposalFailed
                        if display_value(ref.value) in fact_numbers:
                            raise _ReproposalFailed
    finally:
        fact_store.close()


def build_corrected_card(
    *,
    old: Card,
    results: Sequence[StoredResult],
    commitments_by_id: Mapping[str, Commitment],
    change: str,
    changed_profiles: frozenset[str] | set[str] | Sequence[str],
    card_rows: Sequence[SlotCardRow] = (),
) -> Card | None:
    """Build the corrected card from stored rows; None when it cannot stand.

    The unchanged sides are copied from the newest descendant card exactly;
    each changed side is rebuilt from its new stored result with the old
    side's letter and display profile string. Statements use Ticket 13's
    grouping, so a corrected card shows the same shape and the same cap as
    a regular one. A lone remaining side is relettered A. A ``ValueError``
    (such as the caption limit) propagates for the caller to close as
    ``reproposal_failed``. Each new side carries its profile id alongside,
    because a relettered lone side keeps its display string but not the
    letter its old row was keyed by.
    """
    changed = frozenset(changed_profiles)
    by_profile = {result.profile_id: result for result in results}
    commitments = tuple(commitments_by_id.values())
    sides: list[Proposal] = []
    profiles: list[str | None] = []
    for side in old.proposals:
        profile_id = _profile_id_for_side(side, commitments, card_rows)
        if profile_id is None or profile_id not in changed:
            sides.append(side)
            profiles.append(profile_id)
            continue
        result = by_profile.get(profile_id)
        if result is None:
            return None
        if result.kind == "noop":
            continue
        if result.kind == "fallback":
            if result.fallback is None:
                return None
            sides.append(
                Proposal(
                    letter=side.letter,
                    kind="fallback",
                    reason_codes=result.reason_codes,
                    profile=side.profile,
                    title=result.fallback.commitment.title,
                    start=result.fallback.proposed_start,
                    end=result.fallback.proposed_end,
                )
            )
            profiles.append(profile_id)
            continue
        briefing = result.briefing
        if briefing is None or result.hour is None:
            return None
        actions = [
            action for section in briefing.sections for action in section.actions
        ]
        if not actions:
            return None
        commitment = commitments_by_id.get(actions[0].commitment_id)
        if commitment is None:
            return None
        sides.append(
            Proposal(
                letter=side.letter,
                kind="proposal",
                reason_codes=(),
                profile=side.profile,
                title=commitment.title,
                start=result.hour.start,
                end=result.hour.end,
            )
        )
        profiles.append(profile_id)
    if not sides:
        return None
    if len(sides) == 1 and sides[0].letter != "A":
        sides = [sides[0].model_copy(update={"letter": "A"})]
    has_proposal = any(side.kind == "proposal" for side in sides)
    old_has_proposal = any(side.kind == "proposal" for side in old.proposals)
    if has_proposal and not old_has_proposal:
        return None
    prose: list[tuple[str, str, Any]] = []
    for side, profile_id in zip(sides, profiles, strict=True):
        if side.kind != "proposal":
            continue
        briefing = (
            by_profile[profile_id].briefing
            if profile_id is not None and profile_id in by_profile
            else None
        )
        if briefing is None:
            continue
        prose.append((side.letter, side.profile, briefing))
    statements = build_statements(prose)
    return Card(
        slot=old.slot,
        since_line=old.since_line if has_proposal else None,
        proposals=tuple(sides),
        statements=tuple(statements),
        correction_line=change,
        replaces_card_id=old.card_id,
    )


def _heard(transcript: str | None) -> str:
    return f'Heard: "{transcript}"' if transcript else ""


def process_one(deps: VoiceDeps, row: VoiceRow) -> str:
    """Run one claimed note through the pinned step order; one outcome."""
    voice = VoiceLedger(deps.db_path)
    cards = CardLedger(deps.db_path)
    now = deps.now_fn()
    message_id = row.message_id
    received = _parse_instant(row.received_at, now)
    said = (
        datetime.fromtimestamp(row.telegram_date, UTC)
        if row.telegram_date is not None
        else received
    )
    ctx = _Ctx(
        deps=deps,
        voice=voice,
        cards=cards,
        message_id=message_id,
        received=received,
        said=said,
        now=now,
        steps=_load_steps(row),
    )
    try:
        return _flow(ctx, row)
    except _KilledWait:
        return _wait_killed(ctx)
    except _ModeWait:
        return _wait_mode(ctx, voice.load(message_id) or row)
    except _TransientWait:
        try:
            return _wait_transient(ctx, voice.load(message_id) or row)
        except _TerminalOutcome as terminal:
            return _close_outcome(ctx, row, terminal.outcome)
    except _TerminalOutcome as terminal:
        return _close_outcome(ctx, row, terminal.outcome)


def _flow(ctx: _Ctx, row: VoiceRow) -> str:
    """The step order: match, transcribe, compile, apply, card, reply."""
    deps = ctx.deps
    message_id = ctx.message_id
    store = EventStore(deps.db_path)
    try:
        newest_id = match_card(
            row,
            ledger=ctx.voice,
            card_ledger=ctx.cards,
            store=store,
            subject_id=deps.subject_id,
            now=ctx.now,
        )
    finally:
        store.close()
    newest = ctx.cards.load(newest_id) if newest_id else None
    if newest_id is not None and newest is None:
        newest_id = None
    if row.new_card_id is not None and row.matched_card_id:
        # A resumed note past its card send keeps the card it matched:
        # re-walking would start from the card it just replaced.
        restored = ctx.cards.load(row.matched_card_id)
        if restored is not None:
            newest_id, newest = row.matched_card_id, restored
    ctx.newest_id = newest_id
    ctx.newest = newest
    if row.applied_at:
        applied_at = _parse_instant(row.applied_at, ctx.now)
    else:
        applied_at = ctx.now
        ctx.voice.update(message_id, applied_at=applied_at.isoformat())
    ctx.applied_at = applied_at
    ctx.slot = newest.slot if newest is not None else applied_at
    assert ctx.slot is not None
    if row.new_card_id is None:
        ctx.voice.update(
            message_id, matched_card_id=newest_id, slot=ctx.slot.isoformat()
        )
    if _killed(deps):
        raise _KilledWait
    if ctx.now - ctx.received > _GIVE_UP_AFTER:
        raise _TerminalOutcome("gave_up")
    if row.transcript:
        ctx.transcript = row.transcript
    else:
        _prescan_and_store(ctx, _transcribe_step(ctx, row))
        assert ctx.transcript is not None
    if _killed(deps):
        raise _KilledWait
    ctx.new_card_id = row.new_card_id
    if row.operation:
        stored = ctx.voice.load(message_id) or row
        ctx.correction = CompiledCorrection(
            operation=stored.operation or "none",  # type: ignore[arg-type]
            commitment_id=stored.commitment_id,
            until=stored.until_value,  # type: ignore[arg-type]
            question=stored.question,
        )
        try:
            ctx.validation_codes = tuple(json.loads(stored.validation_codes or "[]"))
        except ValueError:
            ctx.validation_codes = ()
        if ctx.validation_codes:
            raise _TerminalOutcome("not_understood")
        if ctx.correction.operation == "none":
            raise _TerminalOutcome("question")
    else:
        _compile_step(ctx, row)
        assert ctx.correction is not None
    correction = ctx.correction
    if _killed(deps):
        raise _KilledWait
    return _apply_and_answer(ctx, row, correction)


def _close_outcome(ctx: _Ctx, row: VoiceRow, outcome: str) -> str:
    """Close a terminal outcome raised mid-flow with its pinned reply."""
    transcript = ctx.transcript or row.transcript
    if outcome == "silence":
        return _finish(
            ctx,
            row,
            outcome=outcome,
            body="I heard no words in that note. Nothing changed.",
        )
    if outcome == "unreadable":
        return _finish(
            ctx,
            row,
            outcome=outcome,
            body="I couldn't read that clip. Nothing changed.",
        )
    if outcome == "outbound_blocked":
        return _finish(
            ctx, row, outcome=outcome, body="I couldn't use that note. Nothing changed."
        )
    if outcome == "not_understood":
        return _finish(
            ctx,
            row,
            outcome=outcome,
            body=f"{_heard(transcript)} I didn't get that, nothing changed.",
        )
    if outcome == "question":
        question = ctx.correction.question if ctx.correction else None
        return _finish(
            ctx,
            row,
            outcome=outcome,
            body=f"{_heard(transcript)} {question or ''} Nothing changed.",
        )
    if outcome == "gave_up":
        return _finish_gave_up(ctx, row)
    raise AssertionError(f"unhandled terminal outcome {outcome}")


def _apply_and_answer(ctx: _Ctx, row: VoiceRow, correction: CompiledCorrection) -> str:
    """Apply state, then guards, re-proposal, card, and reply."""
    operation = correction.operation
    if operation == "fact_correction":
        return _answer_fact_correction(ctx, row, correction)
    loaded = ctx.deps.load_commitments_fn()
    if not loaded.available:
        raise _TransientWait
    commitments = loaded.commitments
    by_id = {item.id: item for item in commitments}
    commitment = by_id.get(correction.commitment_id or "")
    if commitment is None:
        raise _TerminalOutcome("not_understood")
    _apply_correction(ctx, row)
    title = commitment.title
    line = change_line(correction, title)
    if _later_note_stands(ctx, commitment.id):
        return _finish(
            ctx,
            row,
            outcome="applied_superseded",
            body=f"{_heard(ctx.transcript)} {line} A later note already changed this.",
        )
    if _killed(ctx.deps):
        raise _KilledWait
    return _answer_correction(ctx, row, correction, commitments, commitment, line)


def _side_end(newest: Card, profile_id: str) -> datetime | None:
    """The old side's end for one profile, or None when the card lacks it."""
    for side in newest.proposals:
        if side.profile.casefold() == profile_id.casefold():
            return side.end
    return None


def _side_start(newest: Card, profile_id: str) -> datetime | None:
    """The old side's start for one profile, or None when the card lacks it."""
    for side in newest.proposals:
        if side.profile.casefold() == profile_id.casefold():
            return side.start
    return None


def _answer_fact_correction(
    ctx: _Ctx, row: VoiceRow, correction: CompiledCorrection
) -> str:
    """Dispute the card's citations, then correct the offer when one stands."""
    if ctx.newest is None:
        return _finish(
            ctx,
            row,
            outcome="fact_no_card",
            body=f"{_heard(ctx.transcript)} There was no cited statement "
            "to dispute. Nothing changed.",
        )
    _, _, stored = _stored_briefings(ctx)
    stored_count = (ctx.voice.load(ctx.message_id) or row).disputed_claims
    loaded = ctx.deps.load_commitments_fn()
    if not loaded.available:
        raise _TransientWait
    card_rows = _slot_rows(ctx.deps, ctx.newest.card_id)
    carried = {
        profile_id
        for side in ctx.newest.proposals
        if (profile_id := _profile_id_for_side(side, loaded.commitments, card_rows))
        is not None
    }
    if stored_count is None:
        claims, _ = _apply_disputes(ctx, stored)
        ctx.voice.update(ctx.message_id, disputed_claims=claims)
        affected = [
            result.profile_id
            for result in stored
            if result.profile_id in carried
            and result.briefing is not None
            and any(
                section.claims
                for section in result.briefing.sections
                if section.type in _SECTION_ORDER
            )
        ]
        affected = list(dict.fromkeys(affected))
    else:
        # A resumed note reuses the stored claim count and treats every
        # side the card carries as affected: the stored rows may be the
        # fallback rows this note's own first attempt wrote, which carry
        # no claims and must not read as nothing to correct.
        claims = stored_count
        affected = [
            profile_id
            for side in ctx.newest.proposals
            if (profile_id := _profile_id_for_side(side, loaded.commitments, card_rows))
            is not None
            and profile_id in carried
        ]
        affected = list(dict.fromkeys(affected))
    if claims == 0:
        return _finish(
            ctx,
            row,
            outcome="fact_no_card",
            body=f"{_heard(ctx.transcript)} There was no cited statement "
            "to dispute. Nothing changed.",
        )
    line = change_line(
        correction, f"{claims} claim" if claims == 1 else f"{claims} claims"
    )
    if _killed(ctx.deps):
        raise _KilledWait
    if not affected:
        return _finish(
            ctx,
            row,
            outcome="fact_disputed_stands",
            body=f"{_heard(ctx.transcript)} {line} The card stands.",
        )
    return _correct_offer(
        ctx,
        row,
        line,
        tuple(affected),
        base_outcome="fact_disputed",
    )


def _answer_correction(
    ctx: _Ctx,
    row: VoiceRow,
    correction: CompiledCorrection,
    commitments: Sequence[Commitment],
    commitment: Commitment,
    line: str,
) -> str:
    if ctx.newest is None or ctx.slot is None:
        return _finish(
            ctx,
            row,
            outcome="applied_no_card",
            body=f"{_heard(ctx.transcript)} {line}",
        )
    if correction.operation == "keep":
        return _finish(
            ctx,
            row,
            outcome="applied_card_stands",
            body=f"{_heard(ctx.transcript)} {line} The card stands.",
        )
    assert ctx.newest is not None
    side = _offered_side(
        ctx.newest, commitments, commitment, _slot_rows(ctx.deps, ctx.newest.card_id)
    )
    if side is None:
        return _finish(
            ctx,
            row,
            outcome="applied_card_stands",
            body=f"{_heard(ctx.transcript)} {line} The card stands.",
        )
    return _correct_offer(
        ctx,
        row,
        line,
        (commitment.profile_id,),
        base_outcome="applied",
    )


def _result_commitment(
    result: ProposalResult | StoredResult,
    commitments_by_id: Mapping[str, Commitment],
) -> tuple[str, str] | None:
    """The (commitment id, kind) a new result offers, or None with no offer."""
    if result.kind == "noop":
        return None
    if result.kind == "fallback":
        if result.fallback is None:
            return None
        return (result.fallback.commitment.id, result.kind)
    if result.briefing is None:
        return None
    actions = [
        action for section in result.briefing.sections for action in section.actions
    ]
    if not actions or actions[0].commitment_id not in commitments_by_id:
        return None
    return (actions[0].commitment_id, result.kind)


def _save_corrected_rows(
    ctx: _Ctx,
    card: Card,
    fresh: Sequence[StoredResult],
    changed: frozenset[str],
    commitments: Sequence[Commitment],
) -> None:
    """Save the new card's ``slot_cards`` rows before the send.

    An unchanged side copies the old card's row for that profile with the
    new card id and letter. A changed side takes commitment and kind from
    its new result; bucket, slot, subject, pick and alternative come from
    the old row for that profile, and ``as_of`` is the handling instant.
    Pick and alternative record what the policy said at this slot, and a
    correction does not change that. A card with no old rows saves none.
    The rows share one card id and commit atomically, so a key hit means
    this note's own earlier pass already saved them: never fatal.
    """
    assert ctx.newest is not None
    deps = ctx.deps
    if deps.db_path is None:
        return
    old_rows = _slot_rows(deps, ctx.newest.card_id)
    if not old_rows:
        return
    by_profile = {row.profile_id: row for row in old_rows}
    by_result = {result.profile_id: result for result in fresh}
    by_id = {item.id: item for item in commitments}
    out: list[SlotCardRow] = []
    for side in card.proposals:
        profile_id = _profile_id_for_side(side, commitments, old_rows)
        old = by_profile.get(profile_id) if profile_id is not None else None
        if profile_id is None or old is None:
            continue
        if profile_id in changed:
            result = by_result.get(profile_id)
            offered = _result_commitment(result, by_id) if result is not None else None
            if offered is None:
                continue
            commitment_id, kind = offered
            out.append(
                SlotCardRow(
                    card_id=card.card_id,
                    letter=side.letter,
                    slot=old.slot,
                    subject_id=old.subject_id,
                    as_of=ctx.now,
                    bucket=old.bucket,
                    profile_id=profile_id,
                    commitment_id=commitment_id,
                    kind=kind,
                    policy_pick=old.policy_pick,
                    policy_alternative=old.policy_alternative,
                )
            )
        else:
            out.append(replace(old, card_id=card.card_id, letter=side.letter))
    try:
        SlotLedger(deps.db_path).save_slot_cards(out)
    except sqlite3.IntegrityError:
        pass


def _correct_offer(
    ctx: _Ctx,
    row: VoiceRow,
    line: str,
    affected: tuple[str, ...],
    *,
    base_outcome: str,
) -> str:
    """Guards, re-proposal, post-check, silent card send, and reply."""
    deps = ctx.deps
    assert ctx.newest is not None and ctx.slot is not None
    if ctx.new_card_id is not None:
        return _finish(
            ctx,
            row,
            outcome=f"{base_outcome}_card",
            body=f"{_heard(ctx.transcript)} {line} New card above.",
            terminal_on_send_failure="reply_failed",
        )
    if ctx.voice.corrected_count_for_slot(ctx.slot.isoformat()) >= (
        _MAX_CORRECTED_PER_SLOT
    ):
        return _finish(
            ctx,
            row,
            outcome="card_limit",
            body=f"{_heard(ctx.transcript)} {line} "
            "That is 3 corrected cards for this slot, so no new card.",
        )
    chart = ctx.cards.load_chart(ctx.newest.card_id)
    if chart is None:
        return _finish(
            ctx,
            row,
            outcome="chart_missing",
            body=f"{_heard(ctx.transcript)} {line} The card stands.",
        )
    live = tuple(
        profile_id
        for profile_id in affected
        if _side_end(ctx.newest, profile_id) is None
        or _side_end(ctx.newest, profile_id) > ctx.now  # type: ignore[operator]
    )
    if not live:
        return _finish(
            ctx,
            row,
            outcome="hour_passed",
            body=f"{_heard(ctx.transcript)} {line} "
            "That hour has passed, so no new card.",
        )
    _ensure_terms(ctx)
    entries, disputed = _voice_state(ctx)
    loaded = deps.load_commitments_fn()
    if not loaded.available:
        raise _TransientWait
    # Ticket 13's eligibility, so the night rules hold on a corrected card
    # as on a regular one: the old side's start is the hour, the fold's
    # entries ride along. The daily count stays 0 for this seam: a
    # corrected card is the same slot's offer, not a new interruption.
    eligible = {
        profile_id: eligible_commitments(
            loaded.commitments,
            profile_id=profile_id,
            slot_local=ctx.slot,
            state=EligibilityState(
                disconnect_sent_today=0,
                now_local=ctx.now,
                hour_start_local=_side_start(ctx.newest, profile_id),
                entries=entries,
            ),
        )
        for profile_id in live
    }
    _repropose(ctx, live, eligible, disputed)
    fresh_store = ProposalStore(deps.db_path)
    try:
        fresh = list(fresh_store.results_for_slot(deps.subject_id, ctx.slot))
    finally:
        fresh_store.close()
    try:
        _post_check(ctx, fresh, live)
        for profile_id in live:
            result = next(
                (item for item in fresh if item.profile_id == profile_id), None
            )
            if result is None:
                raise _ReproposalFailed
            if result.kind != "noop" and (
                result.hour is None or result.hour.end <= ctx.now
            ):
                return _finish(
                    ctx,
                    row,
                    outcome="hour_passed",
                    body=f"{_heard(ctx.transcript)} {line} "
                    "That hour has passed, so no new card.",
                )
        try:
            card = build_corrected_card(
                old=ctx.newest,
                results=fresh,
                commitments_by_id={item.id: item for item in loaded.commitments},
                change=line,
                changed_profiles=frozenset(live),
                card_rows=_slot_rows(deps, ctx.newest.card_id),
            )
        except ValueError:
            raise _ReproposalFailed from None
        if card is None:
            raise _ReproposalFailed
    except _ReproposalFailed:
        return _finish(
            ctx,
            row,
            outcome="reproposal_failed",
            body=f"{_heard(ctx.transcript)} {line} "
            "I couldn't build a new card. The change is saved.",
        )
    _save_corrected_rows(ctx, card, fresh, frozenset(live), loaded.commitments)
    wall_start = time.monotonic()
    try:
        sent = send_card(
            card,
            chart,
            db_path=deps.db_path,
            client=deps.client,
            silent=True,
        )
    except TelegramDeliveryUnknown:
        # Unknown delivery is never resent: the photo may have landed, so a
        # second send could double it. The note closes at once with the one
        # outcome it can prove. Rate-limited and other transport errors mean
        # it was not sent, so they stay transient below.
        return _finish(
            ctx,
            row,
            outcome="delivery_unknown",
            body=f"{_heard(ctx.transcript)} {line} "
            "I can't tell whether the new card reached this chat.",
            terminal_on_send_failure="delivery_unknown",
        )
    except Exception as exc:  # noqa: BLE001 -- transport or store wait below
        if isinstance(exc, ValueError):
            return _finish(
                ctx,
                row,
                outcome="reproposal_failed",
                body=f"{_heard(ctx.transcript)} {line} "
                "I couldn't build a new card. The change is saved.",
            )
        raise _TransientWait from None
    _bump(ctx.steps, "send_card", time.monotonic() - wall_start)
    ctx.new_card_id = sent.card_id
    ctx.voice.update(ctx.message_id, new_card_id=sent.card_id)
    return _finish(
        ctx,
        row,
        outcome=f"{base_outcome}_card",
        body=f"{_heard(ctx.transcript)} {line} New card above.",
        terminal_on_send_failure="reply_failed",
    )


def _finish_gave_up(ctx: _Ctx, row: VoiceRow) -> str:
    """Best-effort farewell: the row still records ``gave_up`` on failure."""
    transcript = ctx.transcript or row.transcript
    if transcript:
        body = f'Heard: "{transcript}" I couldn\'t process that note. Nothing changed.'
    else:
        body = "I couldn't process that note. Nothing changed."
    full = f"{body} {_took_line(ctx)}"
    _send_simple(ctx, full)
    total = (ctx.deps.now_fn() - ctx.received).total_seconds()
    step_total = sum(ctx.steps.values())
    ctx.voice.update(
        ctx.message_id,
        status="gave_up",
        outcome="gave_up",
        step_seconds=dict(ctx.steps),
        total_s=total,
        unaccounted_s=total - step_total,
        arrival_lag_s=(ctx.received - ctx.said).total_seconds(),
        new_card_id=ctx.new_card_id,
    )
    _append_voice_event(ctx, row, outcome="gave_up", total_s=total)
    return "gave_up"


class VoiceWorker:
    """One daemon thread per poll process: wake, claim, process, repeat."""

    def __init__(self, deps: VoiceDeps, wake: threading.Event) -> None:
        self._deps = deps
        self._wake = wake
        self._stop = threading.Event()
        self._ledger = VoiceLedger(deps.db_path)
        self._thread = threading.Thread(
            target=self._run, name="voice-worker", daemon=True
        )

    def start(self) -> None:
        """Requeue orphaned rows, then run until stopped."""
        self._ledger.requeue_working()
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread; the durable rows wait for the next start."""
        self._stop.set()
        self._wake.set()
        self._thread.join()

    def drain(self, timeout_s: float) -> None:
        """Claim and process until no row is due or the budget passes."""
        self._ledger.requeue_working()
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() < deadline:
            row = self._ledger.claim_next(self._deps.now_fn())
            if row is None:
                return
            if self._process(row) == "killed_waiting":
                return

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(5.0)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self._ledger.requeue_working()
                while not self._stop.is_set():
                    row = self._ledger.claim_next(self._deps.now_fn())
                    if row is None:
                        break
                    if self._process(row) == "killed_waiting":
                        break
            except Exception:  # noqa: BLE001 -- one bad pass never kills the thread
                logger.debug("voice worker pass waiting after store trouble")

    def _process(self, row: VoiceRow) -> str:
        """Process one row; an unexpected exception waits transiently."""
        try:
            return process_one(self._deps, row)
        except Exception:  # noqa: BLE001 -- the worker thread never dies here
            logger.debug("voice note %s waiting after worker error", row.message_id)
            fresh = self._ledger.load(row.message_id) or row
            attempts = (fresh.attempts or 0) + 1
            self._ledger.update(
                row.message_id,
                status="pending",
                attempts=attempts,
                next_attempt_at=(
                    self._deps.now_fn() + timedelta(seconds=retry_delay_s(attempts))
                ).isoformat(),
                outcome=None,
            )
            _tell_waiting_once(
                self._deps,
                self._ledger,
                row.message_id,
                attempts=attempts,
                waiting_told=fresh.waiting_told or 0,
            )
            return "waiting"


def _chain_cards(cards: CardLedger, voice: VoiceLedger, card_id: str) -> list[str]:
    """The whole replacement chain holding a card, oldest to newest."""
    back = [card_id]
    seen = {card_id}
    current = card_id
    for _ in range(100):
        loaded = cards.load(current)
        parent = loaded.replaces_card_id if loaded is not None else None
        if parent is None or parent in seen:
            break
        back.append(parent)
        seen.add(parent)
        current = parent
    chain = list(reversed(back))
    current = card_id
    for _ in range(100):
        nxt: VoiceRow | None = None
        for row in voice.rows_for_card(current):
            if (
                row.matched_card_id == current
                and row.new_card_id
                and (nxt is None or row.message_id > nxt.message_id)
            ):
                nxt = row
        if nxt is None:
            break
        nid = nxt.new_card_id
        if not nid or nid in seen:
            break
        chain.append(nid)
        seen.add(nid)
        current = nid
    return chain


def _event_recorded(db_path: Path | None, message_id: int) -> bool:
    """True when the note's ``app.voice_note`` event is on record; read-only."""
    from framework.store.store import resolve_db_path

    conn = sqlite3.connect(resolve_db_path(db_path))
    try:
        try:
            found = conn.execute(
                "SELECT 1 FROM events WHERE source_id = ?",
                (f"voice-note:{message_id}",),
            ).fetchone()
        except sqlite3.Error:
            return False
        return found is not None
    finally:
        conn.close()


def _format_row(row: VoiceRow, *, event_present: bool) -> str:
    """One note as key=value lines; a blocked note hides its transcript."""
    lines = [
        f"message_id={row.message_id}",
        f"telegram_date={row.telegram_date if row.telegram_date is not None else ''}",
        f"received_at={row.received_at or ''}",
        f"outcome={row.outcome or ''}",
        f"operation={row.operation or ''}",
        f"commitment_id={row.commitment_id or ''}",
        f"until={row.until_value or ''}",
        f"old_card_id={row.matched_card_id or ''}",
        f"new_card_id={row.new_card_id or ''}",
    ]
    steps = _load_steps(row)
    for name in sorted(steps):
        lines.append(f"step_{name}_s={steps[name]:.3f}")
    lines.extend(
        [
            f"total_s={row.total_s if row.total_s is not None else ''}",
            f"unaccounted_s={row.unaccounted_s if row.unaccounted_s is not None else ''}",
            f"arrival_lag_s={row.arrival_lag_s if row.arrival_lag_s is not None else ''}",
            f"first_claimed_at={row.first_claimed_at or ''}",
            f"muse_version={row.muse_version or ''}",
            f"rules_file_present={row.rules_file_present if row.rules_file_present is not None else ''}",
        ]
    )
    if row.outcome == "outbound_blocked":
        lines.append("transcript=<blocked>")
    elif row.transcript:
        lines.append(f"transcript={row.transcript}")
    else:
        lines.append("transcript=<none>")
    lines.append(f"event={'recorded' if event_present else 'missing'}")
    return "\n".join(lines)


def show_chain(
    db_path: Path | None, *, card_id: str | None = None, message_id: int | None = None
) -> str:
    """Print one note or a whole replacement chain; reads only, never writes."""
    voice = VoiceLedger(db_path)
    cards = CardLedger(db_path)
    if message_id is not None:
        row = voice.load(message_id)
        if row is None:
            return ""
        return _format_row(row, event_present=_event_recorded(db_path, message_id))
    if card_id is None:
        return ""
    seen: set[int] = set()
    blocks: list[str] = []
    for chain_id in _chain_cards(cards, voice, card_id):
        for row in voice.rows_for_card(chain_id):
            if row.message_id in seen:
                continue
            seen.add(row.message_id)
            blocks.append(
                _format_row(row, event_present=_event_recorded(db_path, row.message_id))
            )
    return "\n\n".join(blocks)


__all__ = [
    "VoiceDeps",
    "VoiceWorker",
    "build_corrected_card",
    "build_voice_deps",
    "make_voice_handler",
    "match_card",
    "process_one",
    "show_chain",
]
