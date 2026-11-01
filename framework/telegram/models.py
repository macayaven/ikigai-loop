"""Typed Telegram card: proposals, text, keyboards, rulings, replies."""

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from framework.schemas.base import SchemaModel
from framework.schemas.events import AppTapData, Event

MADRID = ZoneInfo("Europe/Madrid")

TARGETS = ("A", "B", "neither", "wrong", "why")
RULING_TARGETS = frozenset({"A", "B", "neither"})

LABEL_A = "Take A"
LABEL_B = "Take B"
LABEL_NEITHER = "Neither now"
LABEL_WRONG = "Something's wrong"
LABEL_WHY = "Why?"

TARGET_LABELS = {
    "A": LABEL_A,
    "B": LABEL_B,
    "neither": LABEL_NEITHER,
    "wrong": LABEL_WRONG,
    "why": LABEL_WHY,
}

TOAST_INVALID = "That button is not on this card."
TOAST_WHY = "Sending the cited statements."
TOAST_WHY_UNKNOWN = "I no longer have that card."
TOAST_WRONG_NEW = "Noted. Voice note please."
TOAST_WRONG_DUP = "Already noted for this card."
TOAST_SAMPLE = "Sample card. Nothing stored."
TOAST_STORE_ERROR = "Not stored yet. Retrying."
TOAST_HANDLER_ERROR = "Could not handle that tap."

VOICE_REQUEST_TEXT = "Tell me what is wrong in a voice note."
NO_STATEMENTS_LINE = "No cited statements on this card."
NO_FACTS_HEADLINE = "No checked facts this time."
FALLBACK_SUFFIX = " (no checked facts)"

CALLBACK_RE = re.compile(r"^card-[0-9a-f]{16}$")
REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(/|$)")

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, so an astral character counts 2."""
    return len(text.encode("utf-16-le")) // 2


def _single_line(value: str, what: str) -> str:
    if "\n" in value or "\r" in value or not value.strip():
        raise ValueError(f"{what} must be single-line and non-blank")
    return value


def _non_blank(value: str, what: str) -> str:
    if not value.strip():
        raise ValueError(f"{what} must be non-blank")
    return value


def check_label(value: str) -> str:
    """Shared label rule for chart labels and period labels."""
    if len(value) > 18:
        raise ValueError("label must be at most 18 characters")
    _single_line(value, "label")
    if "://" in value or value.startswith("www.") or DOMAIN_RE.match(value):
        raise ValueError("label must not be URL-shaped")
    return value


def toast_recorded(label: str) -> str:
    return f"Recorded: {label}"


def toast_already(label: str) -> str:
    return f"Already recorded: {label}"


def toast_standing(first_label: str) -> str:
    return f"Stored. Standing ruling: {first_label}"


def fallback_line(letter: str, codes: tuple[str, ...]) -> str:
    line = f"{letter} has no checked facts this time."
    if codes:
        line += f" Reason codes: {', '.join(codes)}."
    return line


class Proposal(SchemaModel):
    """One card side, gated or fallback.

    It keeps this name for a fallback side too, because other tickets plan
    against the name; `title` prints exactly as given; the caller passes the
    commitment's own title, looked up by id, never `action.text`, because the
    gate lets case and whitespace variants of that wording through.
    """

    letter: Literal["A", "B"]
    kind: Literal["proposal", "fallback"]
    reason_codes: tuple[str, ...] = ()
    profile: str
    title: str
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _check_side(self) -> "Proposal":
        if self.end <= self.start:
            raise ValueError("proposal end must be after start")
        _single_line(self.profile, "profile")
        _single_line(self.title, "title")
        for code in self.reason_codes:
            if not REASON_RE.fullmatch(code):
                raise ValueError(f"bad reason code {code!r}")
        if self.kind == "proposal" and self.reason_codes:
            raise ValueError("a proposal side carries no reason codes")
        return self


class Card(SchemaModel):
    slot: AwareDatetime
    since_line: str | None = None
    proposals: tuple[Proposal, ...] = Field(min_length=1, max_length=2)
    statements: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_card(self) -> "Card":
        letters = [side.letter for side in self.proposals]
        if len(set(letters)) != len(letters):
            raise ValueError("proposal letters must be unique")
        if letters == ["B", "A"]:
            raise ValueError("two proposals read A before B")
        for statement in self.statements:
            _non_blank(statement, "statement")
        has_proposal = any(side.kind == "proposal" for side in self.proposals)
        if has_proposal:
            if self.since_line is None:
                raise ValueError("a proposal side needs a since_line")
            _single_line(self.since_line, "since_line")
        else:
            if self.since_line is not None:
                raise ValueError("a fallback-only card carries no since_line")
            if self.statements:
                raise ValueError("a fallback-only card carries no statements")
        if utf16_len(render_card_text(self)) > CAPTION_LIMIT:
            raise ValueError("card text exceeds the caption limit")
        return self

    @property
    def card_id(self) -> str:
        digest = hashlib.sha256(_canonical_card_json(self).encode("utf-8")).hexdigest()
        return "card-" + digest[:16]


def _canonical_card_json(card: Card) -> str:
    payload = {
        "proposals": [
            {
                "end": side.end.astimezone(UTC).isoformat(),
                "kind": side.kind,
                "letter": side.letter,
                "profile": side.profile,
                "reason_codes": list(side.reason_codes),
                "start": side.start.astimezone(UTC).isoformat(),
                "title": side.title,
            }
            for side in card.proposals
        ],
        "since_line": card.since_line,
        "slot": card.slot.astimezone(UTC).isoformat(),
        "statements": list(card.statements),
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _madrid_hm(moment: datetime) -> str:
    return moment.astimezone(MADRID).strftime("%H:%M")


def render_card_text(card: Card) -> str:
    """Card text exactly as sent; the caption check runs on this."""
    has_proposal = any(side.kind == "proposal" for side in card.proposals)
    head = card.since_line if has_proposal else NO_FACTS_HEADLINE
    lines = [f"{_madrid_hm(card.slot)}  {head}", ""]
    for side in card.proposals:
        line = (
            f"{side.letter}  {side.profile} \u00b7 {side.title}, "
            f"{_madrid_hm(side.start)}-{_madrid_hm(side.end)}"
        )
        if side.kind == "fallback":
            line += FALLBACK_SUFFIX
        lines.append(line)
    return "\n".join(lines)


def build_callback(card_id: str, target: str) -> str:
    return f"{card_id}:{target}"


def parse_callback(data: str) -> tuple[str, str] | None:
    """Strict parse: exactly two parts, a shaped id, a known target."""
    parts = data.split(":")
    if len(parts) != 2:
        return None
    card_id, target = parts
    if not CALLBACK_RE.fullmatch(card_id):
        return None
    if target not in TARGETS:
        return None
    return (card_id, target)


def build_keyboard(card: Card) -> dict[str, object]:
    rows: list[list[dict[str, str]]] = []
    for side in card.proposals:
        label = TARGET_LABELS[side.letter]
        rows.append(
            [
                {
                    "text": label,
                    "callback_data": build_callback(card.card_id, side.letter),
                }
            ]
        )
    rows.append(
        [
            {
                "text": LABEL_NEITHER,
                "callback_data": build_callback(card.card_id, "neither"),
            },
            {
                "text": LABEL_WRONG,
                "callback_data": build_callback(card.card_id, "wrong"),
            },
            {"text": LABEL_WHY, "callback_data": build_callback(card.card_id, "why")},
        ]
    )
    return {"inline_keyboard": rows}


def build_ruled_keyboard(card_id: str, target: str) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "\u2713 " + TARGET_LABELS[target],
                    "callback_data": build_callback(card_id, target),
                }
            ],
            [
                {
                    "text": LABEL_WRONG,
                    "callback_data": build_callback(card_id, "wrong"),
                },
                {"text": LABEL_WHY, "callback_data": build_callback(card_id, "why")},
            ],
        ]
    }


def first_rulings(events: Iterable[Event]) -> dict[str, str]:
    """Standing ruling per card: earliest telegram app.tap ruling by time, id."""
    best: dict[str, tuple[datetime, str, str]] = {}
    for event in events:
        if event.source != "telegram" or event.type != "app.tap":
            continue
        data = event.data
        if not isinstance(data, AppTapData):
            continue
        if data.target not in RULING_TARGETS:
            continue
        key = (event.time, event.id)
        current = best.get(data.block_id)
        if current is None or (key[0], key[1]) < (current[0], current[1]):
            best[data.block_id] = (event.time, event.id, data.target)
    return {card_id: target for card_id, (_, _, target) in best.items()}


def why_reply_pieces(card: Card) -> list[str]:
    """Why? reply pieces in send order: statements first, then fallback lines."""
    pieces = list(card.statements)
    if not pieces:
        pieces.append(NO_STATEMENTS_LINE)
    for side in card.proposals:
        if side.kind == "fallback":
            pieces.append(fallback_line(side.letter, side.reason_codes))
    return pieces


def split_messages(pieces: list[str], limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pack whole pieces with blank lines; cut one oversized piece cleanly."""
    out: list[str] = []
    current = ""
    queue = list(pieces)
    while queue:
        piece = queue.pop(0)
        candidate = piece if not current else current + "\n\n" + piece
        if utf16_len(candidate) <= limit:
            current = candidate
            continue
        if not current:
            head, rest = _cut_piece(piece, limit)
            out.append(head)
            if rest:
                queue.insert(0, rest)
        else:
            out.append(current)
            queue.insert(0, piece)
            current = ""
    if current:
        out.append(current)
    return out


def _cut_piece(piece: str, limit: int) -> tuple[str, str]:
    low, high = 1, len(piece)
    while low < high:
        mid = (low + high + 1) // 2
        if utf16_len(piece[:mid]) <= limit:
            low = mid
        else:
            high = mid - 1
    end = low
    while end > 1 and 0xD800 <= ord(piece[end - 1]) <= 0xDBFF:
        end -= 1
    return piece[:end], piece[end:]


@dataclass(frozen=True)
class VoiceNote:
    message_id: int
    date: int
    file_id: str
    file_unique_id: str
    duration_s: int
    mime_type: str | None = None
    file_size: int | None = None
    reply_to_message_id: int | None = None


VoiceHandler = Callable[[VoiceNote], None]


@dataclass(frozen=True)
class SentCard:
    card_id: str
    message_id: int


@dataclass(frozen=True)
class PollStats:
    updates: int = 0
    stored: int = 0
    duplicates: int = 0
    foreign: int = 0
    unhandled: int = 0
    invalid: int = 0
    sample: int = 0
    voice: int = 0
    voice_errors: int = 0
    answered: int = 0
    answer_errors: int = 0
    side_effect_errors: int = 0
    conflicts: int = 0
    malformed: int = 0
    store_errors: int = 0
    handler_errors: int = 0
    rate_limited: int = 0
    poll_errors: int = 0


class ChartSeries(SchemaModel):
    label: str
    earlier: float
    prior: float
    last: float

    @model_validator(mode="after")
    def _check_series(self) -> "ChartSeries":
        check_label(self.label)
        for name in ("earlier", "prior", "last"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or value > 1_000_000:
                raise ValueError(f"{name} must be finite within 0..1000000")
        return self


class TallyItem(SchemaModel):
    label: str
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_tally(self) -> "TallyItem":
        check_label(self.label)
        return self


class ChartData(SchemaModel):
    period_labels: tuple[str, str, str]
    screen: tuple[ChartSeries, ...] = Field(max_length=8)
    pushes: ChartSeries
    tally: tuple[TallyItem, ...] = Field(max_length=4)

    @model_validator(mode="after")
    def _check_periods(self) -> "ChartData":
        for label in self.period_labels:
            check_label(label)
        return self
