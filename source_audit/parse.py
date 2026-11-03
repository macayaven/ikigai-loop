"""The statement parser alone: two tiers, masked units, whole words."""

from __future__ import annotations

import re
from typing import Any

PAIRS = {("earlier", "prior"), ("prior", "last")}
IDX = {"earlier": 0, "prior": 1, "last": 2}


def _tier(family: str) -> re.Pattern[str]:
    """Build one exact code-fact sentence shape."""
    return re.compile(
        f"^{family} (rose|fell) from (\\d+) in (earlier|prior|last)"
        f" to (\\d+) in (earlier|prior|last)\\.$"
    )


TIER1 = {"prs": _tier("Pull requests"), "pushes": _tier("Pushes")}

UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:hours?|minutes?|mins?|seconds?|secs?|days?|[hs])\b"
)
CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s*[ap]m)?\b", re.IGNORECASE)
ISODATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DAYFIRST_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
MONTH_DAY_RE = re.compile(
    r"\b(?:" + _MONTHS + r")\.?\s+\d{1,2}\b|\b\d{1,2}\s+(?:" + _MONTHS + r")\b",
    re.IGNORECASE,
)
MAY_DAY_RE = re.compile(r"\bMay\.?\s+\d{1,2}\b|\b\d{1,2}\s+May\b")
REF_RE = re.compile(r"\b(?:prs?|pull requests?)\s*#\d+", re.IGNORECASE)
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")
DECIMAL_RE = re.compile(r"\d+\.\d+")
DIGIT_RE = re.compile(r"^\d+$")
HAS_DIGIT_RE = re.compile(r"\d")

WORDS: dict[str, int] = {
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
}
PUSH_WORDS = {"push", "pushes", "pushed", "pushing"}
OTHER_WORDS = {"screen", "calendar", "cancelled", "cancel", "tag", "hours", "hour"}
NEGATORS = ("no", "none")

SINCE_COUNT_RE = re.compile(r"(\d+)\s+push(?:es)?\s*\+\s*PRs?\b", re.IGNORECASE)
SINCE_FIRST_RE = re.compile(
    r"^\s*First card, last 24h:\s*(.*?)\s*\.?\s*$", re.IGNORECASE | re.DOTALL
)
SINCE_HEAD_RE = re.compile(
    r"^\s*Since\s+(\d{1,2}:\d{2})\s*:\s*(.*?)\s*\.?\s*$", re.IGNORECASE | re.DOTALL
)
SINCE_PIECE_RE = re.compile(r"^\d+\s+push(?:es)?\s*\+\s*PRs?$", re.IGNORECASE)
SINCE_OTHER_RE = re.compile(
    r"^(?:code|ai|comms|feed|browse|media)\s+\d+(?:\.\d+)?h$", re.IGNORECASE
)


def _tokens(text: str) -> list[str]:
    """Split whole words, keeping hyphenated compounds as one token."""
    return [tok.strip(".,;:!?()\"'") for tok in text.casefold().split()]


def _metric_ahead(toks: list[str], pos: int, metric: str) -> bool:
    """Check the token after pos starts this metric's word."""
    rest = toks[pos + 1 :]
    if metric == "prs":
        singles = rest[:1] in (["pr"], ["prs"])
        doubles = " ".join(rest[:2]) in ("pull request", "pull requests")
        return singles or doubles
    return bool(rest) and rest[0] in PUSH_WORDS


def parse_statement(text: str, metric: str) -> dict[str, Any]:
    """Parse one statement for one metric into claimed numbers."""
    toks = _tokens(text)
    if "feed" in toks:
        return {"kind": "ignored"}
    match = TIER1.get(metric, TIER1["prs"]).fullmatch(text.strip())
    if match and metric in ("prs", "pushes"):
        pair = (match.group(3), match.group(5))
        if pair in PAIRS:
            got = {IDX[pair[0]]: int(match.group(2)), IDX[pair[1]]: int(match.group(4))}
            return {"kind": "parsed", "periods": got, "total": None}
        return {"kind": "unparsed"}
    masked = text
    masks = (UNIT_RE, CLOCK_RE, ISODATE_RE, DAYFIRST_RE)
    for pattern in masks + (MONTH_DAY_RE, MAY_DAY_RE, PERCENT_RE, REF_RE):
        masked = pattern.sub(" ", masked)
    toks = _tokens(masked)
    joined = " ".join(toks)
    names_prs = "pull request" in joined or "pr" in toks or "prs" in toks
    names_pushes = any(t in toks for t in PUSH_WORDS)
    names = names_prs if metric == "prs" else names_pushes
    names_other = names_pushes if metric == "prs" else names_prs
    if not names:
        return {"kind": "ignored"}
    if names_other or any(t in toks for t in OTHER_WORDS):
        return {"kind": "unparsed"}
    if DECIMAL_RE.search(masked):
        return {"kind": "unparsed"}
    numbers: list[int] = []
    for pos, tok in enumerate(toks):
        if DIGIT_RE.fullmatch(tok):
            numbers.append(int(tok))
        elif tok in WORDS and (tok != "one" or _metric_ahead(toks, pos, metric)):
            numbers.append(WORDS[tok])
        elif tok in NEGATORS and _metric_ahead(toks, pos, metric):
            numbers.append(0)
    period_hits = [IDX[t] for t in toks if t in IDX]
    for pos, tok in enumerate(toks):
        if (
            tok
            in (
                "rose",
                "fell",
                "increased",
                "decreased",
                "grew",
                "dropped",
                "climbed",
                "declined",
                "up",
                "down",
            )
            and pos + 2 < len(toks)
            and toks[pos + 1] == "by"
            and (
                DIGIT_RE.fullmatch(toks[pos + 2]) is not None or toks[pos + 2] in WORDS
            )
        ):
            return {"kind": "unparsed"}
    if not numbers:
        for tok in toks:
            if tok.startswith("#"):
                continue
            if HAS_DIGIT_RE.search(tok):
                return {"kind": "unparsed"}
            if "-" in tok and any(part in WORDS for part in tok.split("-")):
                return {"kind": "unparsed"}
        return {"kind": "ignored"}
    if not period_hits and len(numbers) == 1:
        return {"kind": "parsed", "periods": {}, "total": numbers[0]}
    if len(numbers) == len(period_hits) and numbers:
        merged = dict(zip(period_hits, numbers))
        return {"kind": "parsed", "periods": merged, "total": None}
    return {"kind": "unparsed"}


def parse_since_line(since_line: Any) -> int | None:
    """Read the stated count from a card's since line; only an int ever leaves."""
    if not isinstance(since_line, str):
        return None
    tail: str
    first = SINCE_FIRST_RE.match(since_line)
    if first is not None:
        tail = first.group(1)
    else:
        head = SINCE_HEAD_RE.match(since_line)
        if head is None:
            return None
        tail = head.group(2)
    tail = tail.strip()
    if tail.endswith("."):
        tail = tail[:-1].strip()
    lowered = tail.casefold()
    if lowered in ("nothing recorded", "nothing new recorded"):
        return 0
    if not tail:
        return None
    pieces = [piece.strip() for piece in tail.split(",")]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return None
    found: int | None = None
    for piece in pieces:
        clean = piece[:-1].strip() if piece.endswith(".") else piece
        clean = clean.strip()
        count_hit = SINCE_PIECE_RE.fullmatch(clean)
        if count_hit is not None:
            number = SINCE_COUNT_RE.search(clean)
            if number is None:
                return None
            if found is not None:
                return None
            found = int(number.group(1))
            continue
        if SINCE_OTHER_RE.fullmatch(clean) is None:
            return None
    if found is not None:
        return found
    return 0
