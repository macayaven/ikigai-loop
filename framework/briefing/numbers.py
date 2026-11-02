"""Ticket 10b: number-token extraction.

Mask-then-extract, strict by default: when in doubt the gate rejects. The
gate now checks that claim prose names the metric it cites (label, and
period word for period metrics) and that direction words agree with the
cited values. Direction on fact-only claims is checked against the cited
fact statements, and a value written beside its period word is checked
against that period's ref (side-by-side binding).

What is still not caught, all of it: a claim can name the right metric,
period and direction and still say something false in its other words,
including comparison words outside the pinned lists in single-ref and
fact-only claims, and evaluative prose; in a multi ref claim, a value is
bound to a period where a clause holds exactly one period word and one
value, and a value placed any other way is not bound; ``eight and a half
hours`` backs as 8; two metrics that share a label can swap, since a feed
source and the feed total both read as ``feed``; a digit or number word
inside a category or tag name, such as ``seven-tower`` or ``3D``, reads
as a number and is rejected unless a cited fact evidences the name; a
single-decimal rounding to a token's stated places stays for tokens with
decimals, and signed or absolute-value backing inside ``since_last``
stays as pinned. Backing compares absolute values inside ``since_last``
only; outside it a minus-signed token needs a negative cited ref, and a
token with no decimal places needs an integral cited value (up to float
noise). Direction is checked separately by the binding rule, not by
backing.

A number with a letter glued to it still extracts as the bare digits, an
ordinal extracts as nothing, and dates and clock times are masked away:
the gate's quantity rule rejects the first two on a metric claim, and
``verify_claims`` doesn't run that rule.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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
# D16: only valid clock times (hour 0-23, minute/second 00-59) are masked;
# ``3:99`` is not a time, so its digits tokenise as numbers.
_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\s*(?:am|pm)?"
    rf"(?!\s*(?i:{_UNMASK})\b)",
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
    "billion": 1000000000,
    "trillion": 1000000000000,
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

    @property
    def end(self) -> int:
        """Offset just past the token in the normalised copy."""
        return self.start + len(self.raw)


def _mask(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: " " * len(match.group(0)), text)


def _mask_known(text: str, pattern: re.Pattern[str], known_ids: Collection[str]) -> str:
    """Blank only matches that exactly equal a cited fact/metric ID."""

    def repl(match: re.Match[str]) -> str:
        if match.group(0) in known_ids:
            return " " * len(match.group(0))
        return match.group(0)

    return pattern.sub(repl, text)


def token_backed_by(
    value: float,
    places: int,
    token_abs: Decimal,
    *,
    signed: bool = False,
    section_type: str = "working",
) -> bool:
    """Whether ``value`` backs a token of ``token_abs`` at ``places``.

    Inside ``since_last`` backing compares absolute values, as pinned.
    Outside it a minus-signed token needs a negative cited ref. A token
    with no decimal places is backed exactly when ``value`` rounded
    half-up to two places (as ``format_metric_value`` prints it) equals
    the token. An ``InvalidOperation`` from rounding means no backing,
    never a raise.
    """
    import decimal

    token_abs = Decimal(str(token_abs))
    try:
        if places == 0:
            rounded = Decimal(str(value)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            quantum = Decimal(1).scaleb(-places)
            rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except decimal.InvalidOperation:
        return False
    if abs(rounded) != token_abs:
        return False
    if section_type == "since_last":
        return True
    sign_ok = not signed or Decimal(str(value)) < 0
    return bool(sign_ok)


_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-/]*[-_/][A-Za-z0-9_.\-/]*")


def blank_known_names(text: str, known_names: Collection[str]) -> str:
    """Blank every ``known_names`` occurrence with spaces (length kept)."""
    names = [name for name in known_names if name]
    if not names:
        return text
    lowered = text.casefold()
    chars = list(text)
    for name in names:
        needle = name.casefold()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            for pos in range(index, index + len(needle)):
                if pos < len(chars):
                    chars[pos] = " "
            start = index + len(needle)
    return "".join(chars)


def find_known_names(statements: Collection[str]) -> frozenset[str]:
    """Casefolded name tokens from cited statements (D22).

    A name is a maximal run of letters, digits, ``_``, ``.``, ``-`` and
    ``/`` that starts with a letter and holds at least one of ``-``,
    ``_``, ``/`` or a digit; for a ``/`` path each qualifying segment
    counts alone as well.
    """
    from framework.briefing.normalize import normalize_text

    found: set[str] = set()
    for statement in statements:
        for match in _NAME_PATTERN.finditer(normalize_text(statement)):
            name = match.group(0)
            found.add(name.casefold())
            for segment in name.split("/"):
                if (
                    segment
                    and segment[0].isalpha()
                    and any(c.isdigit() or c in "-_/" for c in segment)
                ):
                    found.add(segment.casefold())
    return frozenset(found)


def extract_number_tokens(
    text: str,
    known_ids: Collection[str] = (),
    known_names: Collection[str] = (),
) -> tuple[NumberToken, ...]:
    """Extract quantity tokens left to right after masking non-quantities.

    ``known_ids`` holds the fact/metric IDs cited on the claim being
    scanned: an identifier or colon reference is masked only when it
    exactly equals one of them. ``known_names`` holds casefolded names
    from the cited facts' statements (D22): a number word inside an
    evidenced name reads as a name, not a number. Both are normalised
    the same way as the text before masking, so an accented id or name
    written in a claim still masks. With the default the function
    returns exactly what it returned before, and ``known_ids`` keeps its
    exact-match meaning. Offsets refer to the normalised copy.
    """
    from framework.briefing.normalize import normalize_text

    normalized = normalize_text(text)
    normalized = blank_known_names(
        normalized, [normalize_text(name) for name in known_names]
    )
    known_ids = {normalize_text(known_id) for known_id in known_ids}
    masked = _mask(normalized, _ISO_DATE_RE)
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
