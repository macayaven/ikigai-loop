"""One send function and one poll loop over the Bot API."""

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from framework.collectors.common import (
    as_dict,
    event_id,
    subject_id_from_env,
)
from framework.schemas import AppTapData, Event
from framework.store import ConflictingEvent, EventStore
from framework.telegram.chart import render_chart_png
from framework.telegram.client import (
    TelegramApiError,
    TelegramAuthError,
    TelegramClient,
    TelegramConfigError,
    TelegramConflict,
    TelegramError,
    TelegramRateLimited,
    TelegramTransportError,
    _allowed_chat_id,  # pyright: ignore[reportPrivateUsage]
)
from framework.telegram.ledger import CardLedger
from framework.telegram.models import (
    TARGET_LABELS,
    TOAST_HANDLER_ERROR,
    TOAST_INVALID,
    TOAST_SAMPLE,
    TOAST_STORE_ERROR,
    TOAST_WHY,
    TOAST_WHY_UNKNOWN,
    TOAST_WRONG_DUP,
    TOAST_WRONG_NEW,
    VOICE_REQUEST_TEXT,
    Card,
    ChartData,
    PollStats,
    SentCard,
    VoiceHandler,
    VoiceNote,
    build_keyboard,
    build_ruled_keyboard,
    first_rulings,
    parse_callback,
    render_card_text,
    split_messages,
    toast_already,
    toast_recorded,
    toast_standing,
    why_reply_pieces,
)
from framework.telegram.sample import SAMPLE_CARD

COLLECTOR_VERSION = "telegram@0.1.0"
CURSOR_NAME = "telegram"
RULING_WINDOW_START = datetime(2000, 1, 1, tzinfo=UTC)

logger = logging.getLogger(__name__)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int_or_none(value: Any) -> int | None:
    return value if _is_int(value) else None


def _bump(stats: PollStats, field: str) -> PollStats:
    return replace(stats, **{field: getattr(stats, field) + 1})


def _add(first: PollStats, second: PollStats) -> PollStats:
    return PollStats(
        updates=first.updates + second.updates,
        stored=first.stored + second.stored,
        duplicates=first.duplicates + second.duplicates,
        foreign=first.foreign + second.foreign,
        unhandled=first.unhandled + second.unhandled,
        invalid=first.invalid + second.invalid,
        sample=first.sample + second.sample,
        voice=first.voice + second.voice,
        voice_errors=first.voice_errors + second.voice_errors,
        answered=first.answered + second.answered,
        answer_errors=first.answer_errors + second.answer_errors,
        side_effect_errors=first.side_effect_errors + second.side_effect_errors,
        conflicts=first.conflicts + second.conflicts,
        malformed=first.malformed + second.malformed,
        store_errors=first.store_errors + second.store_errors,
        handler_errors=first.handler_errors + second.handler_errors,
        rate_limited=first.rate_limited + second.rate_limited,
        poll_errors=first.poll_errors + second.poll_errors,
    )


def _parse_cursor(cursor: Any) -> tuple[int | None, int]:
    if cursor is None:
        return (None, 0)
    cursor_dict = as_dict(cursor)
    if cursor_dict is None:
        raise TelegramConfigError("telegram cursor is malformed")
    offset: Any = cursor_dict.get("offset")
    foreign_total: Any = cursor_dict.get("foreign_total")
    if not _is_int(offset) or not _is_int(foreign_total):
        raise TelegramConfigError("telegram cursor is malformed")
    return (offset, foreign_total)


class _StoreFailure(Exception):
    """sqlite3 hit this update: answer the store toast, hold, stop."""

    def __init__(self, query_id: str | None, silent: bool = False) -> None:
        super().__init__("store failure")
        self.query_id = query_id
        self.silent = silent


def _never_stop() -> bool:
    return False


def send_card(
    card: Card,
    chart: ChartData,
    *,
    db_path: Path | None = None,
    client: TelegramClient | None = None,
) -> SentCard:
    """Ledger first, then one photo message; no half-sent card."""
    if card.card_id != SAMPLE_CARD.card_id:
        CardLedger(db_path).save_card(card)
    chat = _allowed_chat_id()
    if chat is None:
        raise TelegramConfigError("TELEGRAM_CHAT_ID is not set or is malformed")
    tg = client if client is not None else TelegramClient()
    message = tg.send_photo(
        chat,
        render_chart_png(chart),
        render_card_text(card),
        build_keyboard(card),
    )
    message_id: Any = message.get("message_id")
    if not _is_int(message_id):
        raise TelegramTransportError("sendPhoto invalid response")
    return SentCard(card_id=card.card_id, message_id=message_id)


def load_card(card_id: str, db_path: Path | None = None) -> Card | None:
    return CardLedger(db_path).load(card_id)


def _parse_voice(message: dict[str, Any], voice: Any) -> VoiceNote | None:
    voice_dict = as_dict(voice)
    if voice_dict is None:
        return None
    voice = voice_dict
    message_id = _int_or_none(message.get("message_id"))
    date = _int_or_none(message.get("date"))
    file_id: Any = voice.get("file_id")
    file_unique_id: Any = voice.get("file_unique_id")
    duration = _int_or_none(voice.get("duration"))
    if (
        message_id is None
        or date is None
        or not isinstance(file_id, str)
        or not isinstance(file_unique_id, str)
        or duration is None
    ):
        return None
    mime_type: Any = voice.get("mime_type")
    if mime_type is not None and not isinstance(mime_type, str):
        return None
    file_size: Any = voice.get("file_size")
    if file_size is not None and not _is_int(file_size):
        return None
    reply_to: int | None = None
    reply_dict = as_dict(message.get("reply_to_message"))
    if "reply_to_message" in message and reply_dict is None:
        return None
    if reply_dict is not None:
        reply_to = _int_or_none(reply_dict.get("message_id"))
        if reply_to is None:
            return None
    return VoiceNote(
        message_id=message_id,
        date=date,
        file_id=file_id,
        file_unique_id=file_unique_id,
        duration_s=duration,
        mime_type=mime_type,
        file_size=file_size,
        reply_to_message_id=reply_to,
    )


def _query_id_of(update: Any) -> str | None:
    update_dict = as_dict(update)
    if update_dict is None:
        return None
    query = as_dict(update_dict.get("callback_query"))
    if query is None:
        return None
    query_id = query.get("id")
    return query_id if isinstance(query_id, str) else None


class _Poller:
    """Per-batch state: store, ledger, counts, cursor."""

    def __init__(
        self,
        *,
        store: EventStore,
        db_path: Path | None,
        client: TelegramClient,
        allowed: int,
        now: Callable[[], datetime],
        on_voice: VoiceHandler | None,
    ) -> None:
        self.store = store
        self.ledger = CardLedger(db_path)
        self.client = client
        self.allowed = allowed
        self.now = now
        self.on_voice = on_voice
        self.stats = PollStats()
        self.offset: int | None = None
        self.foreign_total = 0

    # -- small effects --

    def _answer(self, query_id: str, text: str) -> None:
        try:
            self.client.call(
                "answerCallbackQuery",
                {"callback_query_id": query_id, "text": text},
                timeout_s=10.0,
                attempts=2,
            )
        except TelegramApiError as exc:
            if exc.description and "query is too old" in exc.description.lower():
                self.stats = _bump(self.stats, "answer_errors")
            else:
                self.stats = _bump(self.stats, "side_effect_errors")
        except TelegramError:
            self.stats = _bump(self.stats, "side_effect_errors")
        else:
            self.stats = _bump(self.stats, "answered")

    def _edit(self, chat_id: int, message_id: int, markup: dict[str, Any]) -> None:
        try:
            self.client.call(
                "editMessageReplyMarkup",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": markup,
                },
                timeout_s=10.0,
                attempts=2,
            )
        except TelegramApiError as exc:
            if exc.description and (
                "message is not modified" in exc.description.lower()
            ):
                return
            self.stats = _bump(self.stats, "side_effect_errors")
        except TelegramError:
            self.stats = _bump(self.stats, "side_effect_errors")

    def _send_text(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            self.client.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "disable_notification": True,
                    "link_preview_options": {"is_disabled": True},
                    "reply_parameters": {
                        "message_id": message_id,
                        "allow_sending_without_reply": True,
                    },
                },
                timeout_s=10.0,
                attempts=2,
            )
        except TelegramError:
            self.stats = _bump(self.stats, "side_effect_errors")

    def _advance(
        self, update_id: int, query_id: str | None = None, silent: bool = False
    ) -> None:
        current = self.offset if self.offset is not None else update_id + 1
        new_offset = max(current, update_id + 1)
        try:
            self.store.poll_transaction(
                CURSOR_NAME,
                [],
                {"offset": new_offset, "foreign_total": self.foreign_total},
            )
        except sqlite3.Error:
            raise _StoreFailure(query_id, silent) from None
        self.offset = new_offset

    def _foreign(self, update_id: int) -> bool:
        self.stats = _bump(self.stats, "foreign")
        self.foreign_total += 1
        self._advance(update_id, silent=True)
        return True

    def _store_failure(self, query_id: str | None, silent: bool) -> bool:
        if query_id is not None and not silent:
            self._answer(query_id, TOAST_STORE_ERROR)
        self.stats = _bump(self.stats, "store_errors")
        return False

    # -- dispatch --

    def handle(self, update: Any) -> bool:
        try:
            return self._handle_inner(update)
        except _StoreFailure as failed:
            return self._store_failure(failed.query_id, failed.silent)
        except Exception:  # noqa: BLE001 - D10 counts any other per-update error
            query_id = _query_id_of(update)
            if query_id is not None:
                self._answer(query_id, TOAST_HANDLER_ERROR)
            self.stats = _bump(self.stats, "handler_errors")
            try:
                update_dict = as_dict(update)
                raw: Any = (
                    update_dict.get("update_id") if update_dict is not None else None
                )
                if _is_int(raw):
                    self._advance(raw, silent=True)
                return True
            except (_StoreFailure, sqlite3.Error):
                self.stats = _bump(self.stats, "store_errors")
                return False

    def _handle_inner(self, update: Any) -> bool:
        update_dict = as_dict(update)
        if update_dict is None:
            self.stats = _bump(self.stats, "malformed")
            return True
        raw_id: Any = update_dict.get("update_id")
        if not _is_int(raw_id):
            self.stats = _bump(self.stats, "malformed")
            return True
        update_id: int = raw_id
        callback = as_dict(update_dict.get("callback_query"))
        if callback is not None:
            return self._callback(update_id, callback)
        message = as_dict(update_dict.get("message"))
        if message is not None:
            return self._message(update_id, message)
        self.stats = _bump(self.stats, "unhandled")
        self._advance(update_id)
        return True

    def _identity(self, query: dict[str, Any]) -> tuple[int, int] | None:
        sender = as_dict(query.get("from"))
        posted = as_dict(query.get("message"))
        if sender is None or posted is None:
            return None
        user_id = _int_or_none(sender.get("id"))
        chat = as_dict(posted.get("chat"))
        if chat is None:
            return None
        chat_id = _int_or_none(chat.get("id"))
        if user_id is None or chat_id is None:
            return None
        return (user_id, chat_id)

    @staticmethod
    def _posted_ids(query: dict[str, Any]) -> tuple[int, int]:
        """Chat and message ids of a filtered callback; raises TelegramError."""
        posted = as_dict(query.get("message"))
        if posted is None:
            raise TelegramError("telegram callback has no message")
        chat = as_dict(posted.get("chat"))
        chat_id = _int_or_none(chat.get("id")) if chat is not None else None
        message_id = _int_or_none(posted.get("message_id"))
        if chat_id is None or message_id is None:
            raise TelegramError("telegram callback has no message ids")
        return (chat_id, message_id)

    def _callback(self, update_id: int, query: dict[str, Any]) -> bool:
        identity = self._identity(query)
        if identity is None:
            return self._foreign(update_id)
        user_id, chat_id = identity
        if user_id != self.allowed or chat_id != self.allowed:
            return self._foreign(update_id)
        query_id: Any = query.get("id")
        if not isinstance(query_id, str):
            self.stats = _bump(self.stats, "malformed")
            self._advance(update_id)
            return True
        raw_data: Any = query.get("data")
        parsed = parse_callback(raw_data) if isinstance(raw_data, str) else None
        if parsed is None:
            self._answer(query_id, TOAST_INVALID)
            self.stats = _bump(self.stats, "invalid")
            self._advance(update_id, query_id)
            return True
        card_id, target = parsed
        if card_id == SAMPLE_CARD.card_id:
            return self._sample(update_id, query, query_id, card_id, target)
        return self._tap(update_id, query, query_id, card_id, target)

    def _tap(
        self,
        update_id: int,
        query: dict[str, Any],
        query_id: str,
        card_id: str,
        target: str,
    ) -> bool:
        chat_id, message_id = self._posted_ids(query)
        card: Card | None = None
        if target in ("A", "B"):
            try:
                card = self.ledger.load(card_id)
            except sqlite3.Error:
                raise _StoreFailure(query_id) from None
            if card is not None and target not in {
                side.letter for side in card.proposals
            }:
                self._answer(query_id, TOAST_INVALID)
                self.stats = _bump(self.stats, "invalid")
                self._advance(update_id, query_id)
                return True
        moment = self.now()
        source_id = f"{card_id}:{target}"
        event = Event(
            id=event_id("telegram", source_id),
            subject_id=subject_id_from_env(),
            source="telegram",
            type="app.tap",
            time=moment,
            source_id=source_id,
            data=AppTapData(block_id=card_id, target=target),
            tier="private",
            collected_at=moment,
            collector_version=COLLECTOR_VERSION,
        )
        try:
            inserted = self.store.append_event(event)
        except ConflictingEvent:
            inserted = False
            self.stats = _bump(self.stats, "duplicates")
        except sqlite3.Error:
            raise _StoreFailure(query_id) from None
        else:
            if inserted:
                self.stats = _bump(self.stats, "stored")
            else:
                self.stats = _bump(self.stats, "duplicates")
        if target in ("A", "B", "neither"):
            return self._ruling(
                update_id,
                query_id,
                card_id,
                target,
                chat_id,
                message_id,
                moment,
                inserted,
            )
        if target == "wrong":
            return self._wrong(update_id, query_id, chat_id, message_id, inserted)
        return self._why(update_id, query_id, card_id, chat_id, message_id)

    def _first_ruling(
        self, card_id: str, target: str, moment: datetime, query_id: str
    ) -> str:
        try:
            events = self.store.events_between(
                subject_id_from_env(),
                RULING_WINDOW_START,
                moment + timedelta(days=1),
                types=["app.tap"],
            )
        except sqlite3.Error:
            raise _StoreFailure(query_id) from None
        return first_rulings(events).get(card_id, target)

    def _ruling(
        self,
        update_id: int,
        query_id: str,
        card_id: str,
        target: str,
        chat_id: int,
        message_id: int,
        moment: datetime,
        inserted: bool,
    ) -> bool:
        first = self._first_ruling(card_id, target, moment, query_id)
        mine = TARGET_LABELS[target]
        standing = TARGET_LABELS[first]
        if target == first:
            toast = toast_recorded(mine) if inserted else toast_already(mine)
        else:
            toast = toast_standing(standing)
        self._answer(query_id, toast)
        self._edit(chat_id, message_id, build_ruled_keyboard(card_id, first))
        self._advance(update_id, query_id)
        return True

    def _wrong(
        self,
        update_id: int,
        query_id: str,
        chat_id: int,
        message_id: int,
        inserted: bool,
    ) -> bool:
        if inserted:
            self._answer(query_id, TOAST_WRONG_NEW)
            self._send_text(chat_id, message_id, VOICE_REQUEST_TEXT)
        else:
            self._answer(query_id, TOAST_WRONG_DUP)
        self._advance(update_id, query_id)
        return True

    def _why(
        self,
        update_id: int,
        query_id: str,
        card_id: str,
        chat_id: int,
        message_id: int,
    ) -> bool:
        try:
            card = self.ledger.load(card_id)
        except sqlite3.Error:
            raise _StoreFailure(query_id) from None
        if card is None:
            self._answer(query_id, TOAST_WHY_UNKNOWN)
        else:
            self._answer(query_id, TOAST_WHY)
            for text in split_messages(why_reply_pieces(card)):
                self._send_text(chat_id, message_id, text)
        self._advance(update_id, query_id)
        return True

    def _sample(
        self,
        update_id: int,
        query: dict[str, Any],
        query_id: str,
        card_id: str,
        target: str,
    ) -> bool:
        chat_id, message_id = self._posted_ids(query)
        self._answer(query_id, TOAST_SAMPLE)
        if target in ("A", "B", "neither"):
            self._edit(chat_id, message_id, build_ruled_keyboard(card_id, target))
        elif target == "wrong":
            self._send_text(chat_id, message_id, VOICE_REQUEST_TEXT)
        else:
            for text in split_messages(why_reply_pieces(SAMPLE_CARD)):
                self._send_text(chat_id, message_id, text)
        self.stats = _bump(self.stats, "sample")
        self._advance(update_id, query_id)
        return True

    def _message(self, update_id: int, message: Any) -> bool:
        message_dict = as_dict(message)
        if message_dict is None:
            return self._foreign(update_id)
        sender = as_dict(message_dict.get("from"))
        chat = as_dict(message_dict.get("chat"))
        user_id = _int_or_none(sender.get("id")) if sender is not None else None
        chat_id = _int_or_none(chat.get("id")) if chat is not None else None
        if user_id != self.allowed or chat_id != self.allowed:
            return self._foreign(update_id)
        if "voice" in message_dict:
            note = _parse_voice(message_dict, message_dict.get("voice"))
            if note is None:
                self.stats = _bump(self.stats, "malformed")
                self._advance(update_id)
                return True
            handler = self.on_voice
            try:
                if handler is None:
                    received = self.now().isoformat()
                    self.ledger.record_voice_arrival(
                        note.message_id, received, note.duration_s
                    )
                else:
                    handler(note)
            except Exception:  # noqa: BLE001 - D16 counts a raising handler
                self.stats = _bump(self.stats, "voice_errors")
            else:
                self.stats = _bump(self.stats, "voice")
            self._advance(update_id)
            return True
        self.stats = _bump(self.stats, "unhandled")
        self._advance(update_id)
        return True


def _run_batch(
    *,
    db_path: Path | None,
    tg: TelegramClient,
    allowed: int,
    long_poll_s: int,
    on_voice: VoiceHandler | None,
    now: Callable[[], datetime],
) -> tuple[PollStats, bool]:
    """Run one getUpdates and handle it; progressed says the cursor moved."""
    store = EventStore(db_path)
    try:
        before, foreign_total = _parse_cursor(store.get_cursor(CURSOR_NAME))
        updates = tg.get_updates(before, long_poll_s)
        poller = _Poller(
            store=store,
            db_path=db_path,
            client=tg,
            allowed=allowed,
            now=now,
            on_voice=on_voice,
        )
        poller.offset = before
        poller.foreign_total = foreign_total
        for update in updates:
            poller.stats = _bump(poller.stats, "updates")
            if not poller.handle(update):
                break
        return (poller.stats, poller.offset != before)
    finally:
        store.close()


def poll_once(
    *,
    db_path: Path | None = None,
    client: TelegramClient | None = None,
    long_poll_s: int = 0,
    on_voice: VoiceHandler | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> PollStats:
    """Run one getUpdates and handle it; every TelegramError propagates."""
    allowed = _allowed_chat_id()
    if allowed is None:
        raise TelegramConfigError("TELEGRAM_CHAT_ID is not set or is malformed")
    tg = client if client is not None else TelegramClient()
    now = now_fn if now_fn is not None else (lambda: datetime.now(UTC))
    stats, _ = _run_batch(
        db_path=db_path,
        tg=tg,
        allowed=allowed,
        long_poll_s=long_poll_s,
        on_voice=on_voice,
        now=now,
    )
    return stats


def run_poll_loop(
    *,
    db_path: Path | None = None,
    client: TelegramClient | None = None,
    long_poll_s: int = 50,
    on_voice: VoiceHandler | None = None,
    stop: Callable[[], bool] = _never_stop,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_batch: Callable[[PollStats], None] | None = None,
) -> PollStats:
    """Block until stop() is true; accumulate PollStats across batches.

    Only TelegramAuthError, TelegramConfigError and BaseException leave.
    """
    backoff = 1.0
    total = PollStats()
    tg = client if client is not None else TelegramClient()
    now = now_fn if now_fn is not None else (lambda: datetime.now(UTC))

    def report() -> None:
        if on_batch is not None:
            on_batch(total)

    def grow() -> None:
        nonlocal backoff
        sleep_fn(backoff)
        backoff = min(backoff * 2, 60.0)

    while not stop():
        try:
            allowed = _allowed_chat_id()
            if allowed is None:
                raise TelegramConfigError("TELEGRAM_CHAT_ID is not set or is malformed")
            batch, progressed = _run_batch(
                db_path=db_path,
                tg=tg,
                allowed=allowed,
                long_poll_s=long_poll_s,
                on_voice=on_voice,
                now=now,
            )
        except (TelegramAuthError, TelegramConfigError):
            raise
        except TelegramRateLimited as exc:
            total = _bump(total, "rate_limited")
            logger.debug("telegram poll loop: %s", type(exc).__name__)
            report()
            if exc.retry_after is not None:
                sleep_fn(float(exc.retry_after))
            else:
                grow()
            continue
        except TelegramConflict as exc:
            total = _bump(total, "conflicts")
            logger.debug("telegram poll loop: %s", type(exc).__name__)
            report()
            grow()
            continue
        except sqlite3.Error as exc:
            total = _bump(total, "store_errors")
            logger.debug("telegram poll loop: %s", type(exc).__name__)
            report()
            grow()
            continue
        except Exception as exc:  # noqa: BLE001 - only auth, config and BaseException leave
            total = _bump(total, "poll_errors")
            logger.debug("telegram poll loop: %s", type(exc).__name__)
            report()
            grow()
            continue
        total = _add(total, batch)
        if batch.updates > 0:
            report()
        if batch.store_errors:
            grow()
            continue
        if batch.updates > 0 and not progressed:
            grow()
            continue
        backoff = 1.0
    return total
