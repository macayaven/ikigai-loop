"""Ticket 10: number-token extraction.

Mask-then-extract, strict by default: when in doubt the gate rejects. The
gate now checks that claim prose names the metric it cites (label, and
period word for period metrics) and that direction words agree with the
cited values.

What is still not caught, all of it: a claim can name the right metric,
period and direction and still say something false in its other words,
including comparison words outside the pinned lists (``climbed``,
``declined``, ``below``, ``above``); in a multi ref claim the values are
not bound to their order in the sentence; a claim with only ``fact_ids``
has no metric binding, so its direction words are not checked; ``eight
and a half hours`` backs as 8; ``twenty-one`` backs as 20 whatever
follows, because a ``one`` joined to the word before it is not a token;
two metrics that share a label can swap,
since a feed source and the feed total both read as ``feed``; a digit or
number word inside a category or tag name, such as ``3D``, reads as a
number and is rejected unless a ref backs it. Backing still compares
absolute values. Direction is checked separately by the binding rule, not
by backing.
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

# A date or clock time directly followed by a measure word (singular or
# plural) or a plural count word is a quantity, not a time: a quantity
# above one takes the plural, so "the 14:00 call" stays a time while
# "10:30 calls" is a number. Lookaheads are case-insensitive.
_UNMASK_MEASURE = (
    r"hour|hours|hr|hrs|h|minute|minutes|min|mins|"
    r"step|steps|day|days|percent|times"
)
_UNMASK_PLURAL_COUNT = r"pushes|commits|events|blocks|tasks|items|calls|cards|prs"
_UNMASK = rf"(?:{_UNMASK_MEASURE}|{_UNMASK_PLURAL_COUNT})"

_ISO_DATE_RE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b(?!\s*(?i:{_UNMASK})\b)")
_DAY_FIRST_RE = re.compile(rf"\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b(?!\s*(?i:{_UNMASK})\b)")
_MONTH_DATE_RE = re.compile(
    rf"(?:\b\d{{1,2}}\s+(?:{_MONTHS})\b(?:\s*,?\s*{_YEAR})?"
    rf"|\b(?:{_MONTHS})\s+\d{{1,2}}\b(?:\s*,?\s*{_YEAR})?"
    rf"|\b(?:{_MONTHS})\s+{_YEAR}\b)(?!\s*(?i:{_UNMASK})\b)"
)
# A clock time followed by a measure or plural count word is a quantity.
_TIME_RE = re.compile(
    rf"\b\d{{1,2}}:\d{{2}}(?::\d{{2}})?\s*(?:am|pm)?(?!\s*(?i:{_UNMASK})\b)",
    re.IGNORECASE,
)
_REF_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*:[A-Za-z0-9_.-]+")
_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*")
_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
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
    "hundred": 100,
    "thousand": 1000,
    "million": 1000000,
    "dozen": 12,
}
# Every spelled-out number except "one" is a token whatever word follows.
_UNCONDITIONAL_WORDS = tuple(word for word in _NUMBER_WORDS if word != "one")
# "one" stays a token only before a unit or count word, or joined by a
# hyphen to a word on that same list ("one-hour", "one-day"): "one-off"
# and "one-on-one" are normal words and stay free.
_ONE_LOOKAHEAD = (
    r"hour|hours|hr|hrs|h|minute|minutes|min|mins|"
    r"step|steps|day|days|percent|"
    r"push|pushes|commit|commits|event|events|block|blocks|"
    r"task|tasks|item|items|call|calls|card|cards|pr|prs|times"
)
_WORD_NUMBER_RE = re.compile(
    r"\b(" + "|".join(sorted(_UNCONDITIONAL_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_ONE_NUMBER_RE = re.compile(
    r"(?<!-)\b(one)(?=\s+(?:" + _ONE_LOOKAHEAD + r")\b|-(?:" + _ONE_LOOKAHEAD + r")\b)",
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
    for pattern in (_WORD_NUMBER_RE, _ONE_NUMBER_RE):
        for match in pattern.finditer(masked):
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
