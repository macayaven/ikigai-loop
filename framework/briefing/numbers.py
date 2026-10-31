"""Ticket 8 (review fixes): number-token extraction.

Mask-then-extract, strict by default: when in doubt the gate rejects, so a
bare year, an uncited identifier, a dotted version, a colon time followed
by a duration word, and a spelled-out quantity are all tokens. Only full
dates, capitalized month-name dates, plain clock times, ordinals, cited
references, and spelled-out non-quantities are free.

Two disclosed gaps (see the session note): the gate checks that a value
matches a ref, not that the prose attaches it to the right metric; and
backing compares absolute values, so direction words are not checked.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

# Month names match only when capitalized, so "may 9" is not a date.
_MONTHS = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
)
_YEAR = r"(?:19\d{2}|20\d{2})"

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DAY_FIRST_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_MONTH_DATE_RE = re.compile(
    rf"\b\d{{1,2}}\s+(?:{_MONTHS})\b(?:\s*,?\s*{_YEAR})?"
    rf"|\b(?:{_MONTHS})\s+\d{{1,2}}\b(?:\s*,?\s*{_YEAR})?"
    rf"|\b(?:{_MONTHS})\s+{_YEAR}\b"
)
# A clock time followed by a duration word is a quantity, not a time.
_DURATION_WORD_RE = r"(?:hours?|hrs?|h|minutes?|mins?|min)"
_TIME_RE = re.compile(
    rf"\b\d{{1,2}}:\d{{2}}(?::\d{{2}})?\s*(?:am|pm)?"
    rf"(?!\s*{_DURATION_WORD_RE}\b)",
    re.IGNORECASE,
)
_REF_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*:[A-Za-z0-9_.-]+")
_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*")
_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
# A spelled-out number is a token only before one of these unit words, so
# "nine hours" is a quantity while "one of the" is free prose.
_UNIT_WORD_RE = r"(?:hours|hr|minutes|min|steps|days|percent)"
_WORD_NUMBER_RE = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS)) + rf")\b(?=\s+{_UNIT_WORD_RE}\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberToken:
    """One measured quantity: raw text, value, offset, and decimal places."""

    raw: str
    value: Decimal
    start: int
    places: int


def _mask(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: " " * len(match.group(0)), text)


def _mask_known(text: str, pattern: re.Pattern[str], known_ids: Collection[str]) -> str:
    """Blank only matches that exactly equal a cited fact/metric ID."""

    def repl(match: re.Match[str]) -> str:
        if match.group(0) in known_ids:
            return " " * len(match.group(0))
        return match.group(0)

    return pattern.sub(repl, text)


def extract_number_tokens(
    text: str, known_ids: Collection[str] = ()
) -> tuple[NumberToken, ...]:
    """Extract quantity tokens left to right after masking non-quantities.

    ``known_ids`` holds the fact/metric IDs cited on the claim being
    scanned: an identifier or colon reference is masked only when it
    exactly equals one of them.
    """
    masked = _mask(text, _ISO_DATE_RE)
    masked = _mask(masked, _DAY_FIRST_RE)
    masked = _mask(masked, _MONTH_DATE_RE)
    masked = _mask(masked, _TIME_RE)
    masked = _mask_known(masked, _REF_RE, known_ids)
    masked = _mask_known(masked, _IDENT_RE, known_ids)
    masked = _mask(masked, _ORDINAL_RE)
    tokens: list[NumberToken] = []
    for match in _NUMBER_RE.finditer(masked):
        raw = match.group(0)
        start = match.start()
        if raw.startswith("-"):
            prev = masked[start - 1] if start > 0 else ""
            if prev.isalpha() or prev.isdigit():
                raw = raw[1:]
                start += 1
        core = raw.removesuffix("%")
        core = core.replace(",", "")
        dot = core.find(".")
        places = len(core) - dot - 1 if dot >= 0 else 0
        tokens.append(
            NumberToken(raw=raw, value=Decimal(core), start=start, places=places)
        )
    for match in _WORD_NUMBER_RE.finditer(masked):
        word = match.group(1)
        tokens.append(
            NumberToken(
                raw=word,
                value=Decimal(_NUMBER_WORDS[word.casefold()]),
                start=match.start(1),
                places=0,
            )
        )
    tokens.sort(key=lambda token: token.start)
    return tuple(tokens)
