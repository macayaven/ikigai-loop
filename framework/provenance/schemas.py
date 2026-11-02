"""Ticket 22: closed shapes for the public provenance log.

Every string the export prints passes through these models, so a line
cannot hold free text by construction. The ``clean_*`` helpers map
anything out of shape to a fixed word before construction; construction
itself is the last guard before anything is written.
"""

from __future__ import annotations

import getpass
import re
import socket
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from framework.schemas.base import SchemaModel

UNKNOWN = "unknown"
OTHER_CODE = "OTHER_CODE"

CountValue = Annotated[int, Field(ge=0)] | Literal["unknown"]
NonNeg = Annotated[int, Field(ge=0)]

ProfileName = Literal["builder", "disconnect", "unknown"]
SideKind = Literal["proposal", "fallback", "noop", "unknown"]
Letter = Literal["A", "B", "unknown"]
Transport = Literal["muse", "api", "unknown"]
Effort = Literal["minimal", "low", "medium", "high", "unknown"]
Delivery = Literal[
    "delivered",
    "DELIVERY_UNKNOWN",
    "SEND_NOT_SENT",
    "SEND_REFUSED",
    "intent_open",
    "not_sent",
    "no_card",
    "unknown",
]
PassName = Literal["personal", "feed", "unknown"]
FactsModelStep = Literal[
    "ok",
    "SKIPPED",
    "FACTS_DEADLINE",
    "MODEL_DOWN",
    "FACTS_UNPARSED",
    "killed",
    "OTHER_CODE",
    "unknown",
]
SideOrigin = Literal["model", "code", "none", "unknown"]
CycleOrigin = Literal["model", "code", "none", "mixed", "unknown"]

# The line's slot is a Madrid instant with offset: CET (+01:00) or CEST (+02:00).
SlotStr = Annotated[
    str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?\+0[12]:00$")
]
CodeStr = Annotated[
    str,
    Field(
        max_length=64,
        pattern=(
            r"^(?:NO_CYCLE|OTHER_CODE|(?:L0_|L1_|L1B_|NOOP_|FACT_|"
            r"CODE_|FALLBACK_|MODEL_|PROPOSAL_|DRAFT_|PARENT_|CYCLE_|SLOT_|"
            r"SEND_|DELIVERY_|CHART_|PREFLIGHT_|TERMS_|STALE_|COMMITMENT_|"
            r"COMMITMENTS_|FACTS_|DISCONNECT_|LEARNER_|CALENDAR_|BUCKET_|"
            r"CORRECTION_|CONTRIBUTOR_)[A-Z0-9_]*)$"
        ),
    ),
]
CodeOrUnknown = CodeStr | Literal["unknown"]
FinalCode = CodeStr | Literal["delivered", "killed", "unknown"]
ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
VersionStr = (
    Annotated[str, Field(pattern=r"^\d+\.\d+(\.\d+){0,2}$")] | Literal["unknown"]
)
FinishReason = Literal[
    "stop",
    "length",
    "completed",
    "tool_calls",
    "content_filter",
    "cancelled",
    "unknown",
]

_CODE_FAMILIES = (
    "L0_",
    "L1_",
    "L1B_",
    "NOOP_",
    "FACT_",
    "CODE_",
    "FALLBACK_",
    "MODEL_",
    "PROPOSAL_",
    "DRAFT_",
    "PARENT_",
    "CYCLE_",
    "SLOT_",
    "SEND_",
    "DELIVERY_",
    "CHART_",
    "PREFLIGHT_",
    "TERMS_",
    "STALE_",
    "COMMITMENT_",
    "COMMITMENTS_",
    "FACTS_",
    "DISCONNECT_",
    "LEARNER_",
    "CALENDAR_",
    "BUCKET_",
    "CORRECTION_",
    "CONTRIBUTOR_",
)
_EXACT_CODES = frozenset({"NO_CYCLE"})
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+){0,2}")


def clean_code(value: object) -> str:
    """A listed code survives; anything else is the fixed placeholder."""
    if (
        isinstance(value, str)
        and (value in _EXACT_CODES or value.startswith(_CODE_FAMILIES))
        and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is not None
    ):
        return value
    return OTHER_CODE


def clean_profile(value: object) -> ProfileName:
    return value if value in ("builder", "disconnect") else UNKNOWN  # type: ignore[return-value]


def clean_kind(value: object) -> SideKind:
    return value if value in ("proposal", "fallback", "noop") else UNKNOWN  # type: ignore[return-value]


def clean_letter(value: object) -> Letter:
    return value if value in ("A", "B") else UNKNOWN  # type: ignore[return-value]


def clean_transport(value: object) -> Transport:
    return value if value in ("muse", "api") else UNKNOWN  # type: ignore[return-value]


def clean_effort(value: object) -> Effort:
    if value in ("minimal", "low", "medium", "high"):
        return value  # type: ignore[return-value]
    return UNKNOWN  # type: ignore[return-value]


def clean_pass_name(value: object) -> PassName:
    return value if value in ("personal", "feed") else UNKNOWN  # type: ignore[return-value]


_FINISH_WORDS = frozenset(
    {"stop", "length", "completed", "tool_calls", "content_filter", "cancelled"}
)


def clean_finish_reason(value: object) -> str:
    if isinstance(value, str) and value in _FINISH_WORDS:
        return value
    return UNKNOWN


def clean_version(value: object) -> str:
    """Only the version number from the stored first line, else unknown."""
    if not isinstance(value, str) or not value:
        return UNKNOWN
    first = value.split("\n", 1)[0][:200]
    match = _VERSION_RE.search(first)
    return match.group(0) if match is not None else UNKNOWN


def _optional_name(reader: Callable[[], str]) -> str | None:
    try:
        return reader()
    except Exception:  # noqa: BLE001 -- a name probe never stops the export
        return None


def _runtime_names() -> tuple[str | None, str | None, str | None]:
    user = _optional_name(getpass.getuser)
    host = _optional_name(socket.gethostname)
    home = _optional_name(lambda: Path.home().name)
    return user, host, home


_HOST_SUFFIXES = frozenset({"net", "com", "org", "local", "lan", "internal", "home"})
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def bounded_contains(haystack: str, needle: str) -> bool:
    """The whole name inside, bounded by non-alphanumerics or string ends."""

    def is_word_char(char: str) -> bool:
        return char.isascii() and char.isalnum()

    start = 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return False
        before = haystack[at - 1] if at > 0 else ""
        after = haystack[at + len(needle)] if at + len(needle) < len(haystack) else ""
        if (not before or not is_word_char(before)) and (
            not after or not is_word_char(after)
        ):
            return True
        start = at + 1


def clean_model_id(
    raw: object,
    *,
    username: str | None = None,
    hostname: str | None = None,
    home_name: str | None = None,
) -> str:
    """Only a safe basename ever gets out, else the word unknown.

    A trailing separator means a directory, so unknown. A last component
    directly under a parent named ``home`` or ``Users``, or ``/root``
    itself, is unknown whoever runs the export, on a plain path and on
    a URL's path alike. For a URL the basename comes from its path only,
    and no path means unknown. A basename with no letter in it, such as
    a bare port number, is unknown. A name ending in a domain suffix
    looks like a host, so unknown. A basename holding the runtime
    username, the home directory's name or the hostname as a whole name,
    bounded by non-alphanumerics or the string's ends, refuses, except
    that a name shorter than 3 characters is ignored.
    """
    if username is None or hostname is None or home_name is None:
        runtime = _runtime_names()
        if username is None:
            username = runtime[0]
        if hostname is None:
            hostname = runtime[1]
        if home_name is None:
            home_name = runtime[2]
    if not isinstance(raw, str):
        return UNKNOWN
    text = raw.strip()
    if not text:
        return UNKNOWN
    core = text.split("?", 1)[0].split("#", 1)[0]
    if not core or core.endswith(("/", "\\")):
        return UNKNOWN
    if _URL_RE.match(core) is not None:
        try:
            path = urllib.parse.urlsplit(core).path
        except ValueError:
            return UNKNOWN
        if not path or path == "/":
            return UNKNOWN
        base = path.rsplit("/", 1)[-1]
        path_parts = [part for part in path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[-2].lower() in ("home", "users"):
            return UNKNOWN
        if path_parts == ["root"]:
            return UNKNOWN
    else:
        base = re.split(r"[/\\]", core)[-1]
        if ":" in base and "://" not in core:
            base = base.rsplit(":", 1)[-1]
        parts = [part for part in re.split(r"[/\\]", core) if part]
        if len(parts) >= 2 and parts[-2].lower() in ("home", "users"):
            return UNKNOWN
        if len(parts) == 1 and parts[0].lower() == "root" and core.startswith("/"):
            return UNKNOWN
    if base in ("", "unreported"):
        return UNKNOWN
    if not re.search(r"[A-Za-z]", base):
        return UNKNOWN
    if _MODEL_RE.fullmatch(base) is None:
        return UNKNOWN
    if "." in base and base.rsplit(".", 1)[-1].lower() in _HOST_SUFFIXES:
        return UNKNOWN
    lowered = base.lower()
    for name in (username, hostname, home_name):
        if (
            name is not None
            and len(name) >= 3
            and bounded_contains(lowered, name.lower())
        ):
            return UNKNOWN
    return base


class OriginCounts(SchemaModel):
    code: CountValue
    model: CountValue
    unknown: CountValue


class GlimmerPass(SchemaModel):
    name: PassName
    attempts: CountValue
    model_reported: ModelName
    latency_ms: CountValue
    completion_tokens: CountValue
    finish_reason: FinishReason
    kept: CountValue
    noop_reason: CodeOrUnknown | Literal["none"]


class SideCycle(SchemaModel):
    origin: SideOrigin
    facts_available: OriginCounts
    dropped_codes: tuple[CodeStr, ...] | Literal["unknown"]
    passes: tuple[GlimmerPass, ...] | Literal["unknown"]


class Attempt(SchemaModel):
    model_requested: ModelName
    model_reported: ModelName
    transport: Transport
    muse_version: VersionStr
    effort: Effort
    latency_ms: CountValue
    prompt_tokens: CountValue
    completion_tokens: CountValue
    reasoning_tokens: CountValue
    cached_tokens: CountValue
    parsed_ok: bool | Literal["unknown"]
    blocked: bool | Literal["unknown"]
    gate_codes: tuple[CodeStr, ...] | Literal["unknown"]


class Side(SchemaModel):
    letter: Letter
    profile: ProfileName
    kind: SideKind
    reason_codes: tuple[CodeStr, ...] | Literal["unknown"]
    local_retries: NonNeg | Literal["unknown"]
    timeout_retries: NonNeg | Literal["unknown"]
    facts_cited: OriginCounts
    metrics_cited: CountValue
    cycle: SideCycle
    attempts: tuple[Attempt, ...] | Literal["unknown"]


class NotOnCard(SchemaModel):
    profile: ProfileName
    kind: SideKind
    reason_codes: tuple[CodeStr, ...] | Literal["unknown"]


class ProvenanceLine(SchemaModel):
    slot: SlotStr
    delivery: Delivery
    final_code: FinalCode
    facts_model_step: FactsModelStep
    forced: bool | Literal["unknown"]
    superseded_cards: NonNeg
    cycle_origin: CycleOrigin
    facts_cited: OriginCounts
    not_on_card: tuple[NotOnCard, ...]
    sides: tuple[Side, ...]
