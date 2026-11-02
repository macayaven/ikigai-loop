"""Ticket 10b: unverifiable-quantity detection (D8)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection

from framework.briefing.normalize import normalize_text

_NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "trillion",
        "dozen",
    }
)

_FRACTION_WORDS = ("half", "halves", "quarters")

_VAGUE_PHRASES = (
    "a couple",
    "couple of",
    "a few",
    "several",
    "many",
    "numerous",
    "a handful",
    "dozens",
    "a pair",
    "pair of",
    "trio",
    "nil",
    "nought",
    "naught",
    "zilch",
    "loads",
    "tons",
    "lots",
    "plenty",
    "bunch",
    "multiple",
    "various",
    "countless",
    "half-dozen",
    "half dozen",
    "scores of",
)

_RATE_PHRASES = (
    "daily",
    "hourly",
    "weekly",
    "monthly",
    "nightly",
    "per day",
    "per week",
    "per hour",
    "a day",
    "a week",
)

_MULTIPLICATIVE_WORDS = (
    "double",
    "doubled",
    "doubling",
    "triple",
    "tripled",
    "tripling",
    "treble",
    "trebled",
    "trebles",
    "trebling",
    "quadruple",
    "quadrupled",
    "quadrupling",
    "multiply",
    "multiplied",
    "multiplies",
    "multiplying",
    "halved",
    "halving",
    "twice",
    "thrice",
)

_FOLD_RE = re.compile(
    r"(?<!\w)(?:multi|many|zero|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|eleven|twelve|\d+)-?fold(?!\w)"
)

_TALLY_RUN_RE = re.compile(r"[|\u00a6\u2016\u2017]{2,}")
_TALLY_WORD_RE = re.compile(r"(?<!\w)tallys?(?!\w)")

_FRACTION_DASH_RE = re.compile(
    r"(?<!\w)(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven)-(?:third|thirds|fourth|fourths|fifth|fifths|sixth|"
    r"sixths|eighth|eighths|tenth|tenths)(?!\w)"
)

_VULGAR_FRACTIONS = frozenset(
    "\u00bc\u00bd\u00be\u2150\u2151\u2152\u2153\u2154\u2155"
    "\u2156\u2157\u2158\u2159\u215a\u215b\u215c\u215d\u215e"
)
_FRACTION_SLASH = "\u2044"

_ONE_OH_RE = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|"
    r"ten)-oh(?!\w)"
)
_OH_N_RE = re.compile(
    r"(?<!\w)oh-(?:zero|one|two|three|four|five|six|seven|eight|"
    r"nine)(?!\w)"
)
_POINT_RE = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety)\s+point\s+"
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine)(?!\w)"
)
_TENS_UNITS_RE = re.compile(
    r"(?<!\w)(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety)-(?:one|two|three|four|five|six|seven|eight|nine)"
    r"(?!\w)"
)
_GLUED_X_RE = re.compile(r"(?<!\w)(?:\d+[a-zA-Z]|[a-zA-Z]\d+)")
_N_TIMES_RE = re.compile(
    r"(?<!\w)(?:\d+|zero|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve)\s+times\s+"
    r"(?:the|as|more|less|higher|lower|over|what|that|those)(?!\w)"
)

_APPROXIMATORS = (
    "close to",
    "at least",
    "at most",
    "no more than",
    "no fewer than",
    "more than",
    "less than",
    "fewer than",
    "up to",
    "upwards of",
    "just over",
    "just under",
    "as many as",
    "as few as",
    "as much as",
    "as little as",
    "north of",
    "south of",
    "shy of",
    "about",
    "some",
    "over",
    "under",
    "above",
    "below",
    "beyond",
    "past",
    "around",
    "roughly",
    "nearly",
    "almost",
    "approximately",
    "approx",
    "circa",
)
_UP_TO_GUARD = frozenset({"went", "moved", "rose", "climbed", "jumped", "came", "shot"})

_WORD_ORDINALS = frozenset(
    {
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
    }
)
_RANK_WORDS = frozenset(
    {
        "ranked",
        "ranking",
        "highest",
        "lowest",
        "top",
        "leading",
        "ahead",
        "behind",
        "most",
        "least",
        "biggest",
        "largest",
        "smallest",
        "peak",
        "record",
        "best",
        "worst",
        "led",
        "lead",
        "dominated",
        "topped",
        "majority",
        "minority",
        "bulk",
    }
)
_RECORD_PHRASES = (
    "new high",
    "new low",
    "all-time",
    "all time",
    "record high",
    "record low",
)
_AHEAD_GUARD_RE = re.compile(
    r"(?<!\w)(?:plan|plans|planned|planning|look|looking|think|"
    r"thinking)\s+ahead(?!\w)"
)
# `ahead` directly after a time noun is forward-looking, never a rank;
# `ahead of` still ranks, so the `of` phrase stays out of the guard.
_TIME_AHEAD_GUARD_RE = re.compile(
    r"(?<!\w)(?:day|days|week|weeks|month|months|hour|hours|time)"
    r"\s+ahead(?!\s+of\b)(?!\w)"
)
_COUNT_NOUNS = frozenset(
    {
        "push",
        "pushes",
        "commit",
        "event",
        "block",
        "task",
        "item",
        "call",
        "card",
        "pr",
        "prs",
        "hour",
        "minute",
        "day",
    }
)
_DIGIT_ORDINAL_RE = re.compile(r"\d+(?:st|nd|rd|th)")
_DIGIT_ORDINAL_NOUN_RE = re.compile(
    r"(?<!\w)\d+(?:st|nd|rd|th)\s+(?:push|pushes|commit|event|"
    r"block|task|item|call|card|pr|prs|hour|minute|day)(?!\w)"
)
_AFTER_WAS_ORDINAL_RE = re.compile(
    r"(?<!\w)(?:was|were|came|ranked|finished|placed)\s+"
    r"\d+(?:st|nd|rd|th)(?!\w)"
)

# Quantity words outside the number table. The plural scale words and
# the two phrases fire on every claim; the bare words only on metrics.
_QUANTITY_WORDS = frozenset({"hundreds", "thousands", "millions", "billions"})
_QUANTITY_PHRASES = ("tens of", "a single")
_METRIC_QUANTITY_WORDS = frozenset({"single", "once", "null", "zip", "nada"})

# A letter-digit run in either order. Digit runs with a unit, ordinal
# or clock suffix belong to those rules and never fire here.
_GLUED_RUN_RE = re.compile(
    r"(?<![\w-])(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+(?![\w-])"
)
_GLUED_OWNED_SUFFIX_RE = re.compile(
    r"\d(?:h|hr|hrs|m|min|mins|s|sec|secs|st|nd|rd|th|am|pm)$",
    re.IGNORECASE,
)
_DASH_SUFFIX_RE = re.compile(
    r"(?<!\w)(?:\d+|zero|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|trillion)-(?:ish|odd|plus|something)(?!\w)"
)

# Qualifiers after a number (at most one unit or label word between)
# and qualifiers directly before one. ``min`` stays with the unit rule.
_POST_QUALIFIER_SINGLE = frozenset(
    {
        "max",
        "maximum",
        "minimum",
        "plus",
        "per",
        "each",
        "apiece",
        "squared",
        "cubed",
    }
)
_POST_QUALIFIER_PHRASE = (
    "or so",
    "give or take",
    "or thereabouts",
    "at minimum",
    "at maximum",
    "at a minimum",
    "at the most",
    "at the least",
    "at most",
    "at least",
    "and change",
    "and counting",
    "and up",
    "and then some",
    "or more",
    "or less",
    "or fewer",
    "or higher",
    "or lower",
)
_PRE_QUALIFIER_PHRASE = (
    "a minimum of",
    "a maximum of",
    "minimum of",
    "maximum of",
    "minimum",
    "maximum",
    "max",
    "upper bound of",
    "lower bound of",
    "square of",
    "cube of",
    "sum of",
    "product of",
    "root of",
    "multiple of",
    "factor of",
    "power of",
    "average of",
    "mean of",
    "median of",
)
# Words allowed between a number and a following qualifier: units plus
# the caller-supplied label tokens.
_QUALIFIER_UNITS = frozenset(
    {
        "hour",
        "hours",
        "hr",
        "hrs",
        "minute",
        "minutes",
        "min",
        "mins",
        "second",
        "seconds",
        "sec",
        "secs",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "push",
        "pushes",
        "commit",
        "commits",
        "event",
        "events",
        "block",
        "blocks",
        "task",
        "tasks",
        "item",
        "items",
        "call",
        "calls",
        "card",
        "cards",
        "pr",
        "prs",
        "step",
        "steps",
        "percent",
        "times",
    }
)

# Spelled ordinals past tenth, plus tens-ordinal hyphen forms.
_SPELLED_ORDINAL_RE = re.compile(
    r"(?<!\w)(?:eleventh|twelfth|thirteenth|fourteenth|fifteenth|"
    r"sixteenth|seventeenth|eighteenth|nineteenth|twentieth|"
    r"thirtieth|fortieth|fiftieth|sixtieth|seventieth|eightieth|"
    r"ninetieth|hundredth|thousandth|millionth|billionth|"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|"
    r"ninth))(?!\w)"
)
# One word three or more times running, apart only by spaces or commas.
_TALLY_REPEAT_RE = re.compile(r"(?<![\w-])([a-z]+)(?:[\s,]+\1){2,}(?![\w-])")
# A digit, then a slash, underscore or apostrophe, then a digit; and a
# number ending in exactly three zeros after its decimal point.
_FRACTION_DIGIT_RE = re.compile(r"(?<!\w)\d+[/_']\d+(?!\w)")
_FRACTION_DECIMAL_RE = re.compile(r"(?<!\w)\d+\.000(?!\d)")
# A range over one named period, or ``between`` before a digit.
_RANGE_RE = re.compile(
    r"(?<!\w)(?:in|during)(?:\s+the)?\s+(?:earlier|prior|last)"
    r"(?:\s+(?:period|window))?\s+(?:range|ranged|ranging|ranges|"
    r"span|spans|spanned|spanning|varied|varies|varying)(?!\w)"
)
_BETWEEN_DIGIT_RE = re.compile(r"(?<!\w)between\s+\d")

# Universal quantifier before a label: all/every/each/both, optional
# of, optional determiner, then the label. ``both`` joined to the label
# by ``and`` is a coordination and never fires here.
_UNIVERSAL_WORDS = frozenset({"all", "every", "each", "both"})
_UNIVERSAL_DETERMINERS = frozenset({"the", "my", "your", "our"})

# Closed time-scope list for metric claims (item 7): a cited metric
# holds its window, so naming another time says something the metric
# does not. Includes the rate words and phrases above.
_TIME_SCOPE_PHRASES = (
    "today",
    "tonight",
    "tomorrow",
    "yesterday",
    "overnight",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "so far",
    "this morning",
    "this afternoon",
    "this evening",
    "this week",
    "this month",
    "this year",
    "last night",
    "last week",
    "last month",
    "last year",
    "last hour",
    "last minute",
    "last minutes",
    "past day",
    "past week",
    "past month",
    "past year",
    "past hour",
    "next week",
    "next month",
    "next year",
    "all day",
    "all week",
    "all month",
    "all year",
    "in the morning",
    "in the afternoon",
    "in the evening",
    "a month",
    "a year",
    "per month",
    "per year",
)

_CLOCK_ALLOWED_BEFORE = frozenset(
    {
        "at",
        "by",
        "from",
        "until",
        "till",
        "to",
        "before",
        "after",
        "around",
        "since",
        "between",
        "and",
        "or",
        "the",
    }
)
_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?")

# A clock directly followed by a measure or plural count word is a
# quantity, not a time: extraction leaves its digits as number tokens,
# so the clock-position rule must not fire on it either.
_CLOCK_UNMASK = re.compile(
    r"(?:hour|hours|hr|hrs|h|minute|minutes|min|mins|"
    r"step|steps|day|days|percent|times|"
    r"pushes|commits|events|blocks|tasks|items|calls|cards|prs)\b",
    re.IGNORECASE,
)

_ROMAN_RE = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})")
_ROMAN_TOKEN_RE = re.compile(r"\b[A-Z]+\b")
_I_RUN_RE = re.compile(r"I{4,}")

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DAY_FIRST_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_MONTH_DATE_RE = re.compile(
    r"(?:\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
    r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\b(?:\s*,?\s*(?:19\d{2}|20\d{2}))?"
    r"|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}\b"
    r"(?:\s*,?\s*(?:19\d{2}|20\d{2}))?"
    r"|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
    r"(?:19\d{2}|20\d{2})\b)"
)

_HYPHEN_COMPOUND_RE = re.compile(r"\w+(?:-\w+)+")
_DIGIT_ADJACENCY_RE = re.compile(r"\d\s+\d")
_SIGNED_PLUS_RE = re.compile(r"\+\s*\d")


def _blank_known_names(text: str, known_names: Collection[str]) -> str:
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
                chars[pos] = " "
            start = index + len(needle)
    return "".join(chars)


def _blank_dates(text: str) -> str:
    out = _ISO_DATE_RE.sub(lambda m: " " * len(m.group(0)), text)
    out = _DAY_FIRST_RE.sub(lambda m: " " * len(m.group(0)), out)
    return _MONTH_DATE_RE.sub(lambda m: " " * len(m.group(0)), out)


def _blank_valid_clocks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3)) if match.group(3) else 0
        if hour <= 23 and minute <= 59 and second <= 59:
            return " " * len(match.group(0))
        return match.group(0)

    return _CLOCK_RE.sub(repl, text)


def _word_hit(lower: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lower) is not None


def _scan(lower: str, work: str, work_dated: str) -> list[tuple[str, str]]:
    """Collect ``(kind, matched token)`` hits over the prepared copies."""
    hits: list[tuple[str, str]] = []
    for word in _FRACTION_WORDS:
        if _word_hit(lower, word) or _word_hit(lower, word + " of"):
            for match in re.finditer(r"(?<!\w)" + word + r"(?!\w)", lower):
                hits.append(("fraction", match.group(0)))
    if _word_hit(lower, "a quarter") or (_word_hit(lower, "quarter of")):
        hits.append(("fraction", "quarter"))
    for match in _FRACTION_DASH_RE.finditer(lower):
        hits.append(("fraction", match.group(0)))
    for char in _VULGAR_FRACTIONS:
        if char in work:
            hits.append(("fraction", char))
    if _FRACTION_SLASH in work:
        hits.append(("fraction", _FRACTION_SLASH))
    for word in _MULTIPLICATIVE_WORDS:
        if _word_hit(lower, word):
            hits.append(("multiplicative", word))
    for match in _FOLD_RE.finditer(lower):
        hits.append(("multiplicative", match.group(0)))
    for phrase in _VAGUE_PHRASES:
        if _word_hit(lower, phrase):
            hits.append(("vague", phrase))
    for phrase in _RATE_PHRASES:
        if _word_hit(lower, phrase):
            hits.append(("rate", phrase))
    one_oh = _ONE_OH_RE.search(lower)
    if one_oh is not None:
        hits.append(("spoken", one_oh.group(0)))
    oh_n = _OH_N_RE.search(lower)
    if oh_n is not None:
        hits.append(("spoken", oh_n.group(0)))
    if _POINT_RE.search(lower):
        hits.append(("spoken", "point"))
    for match in _TENS_UNITS_RE.finditer(lower):
        hits.append(("spoken", match.group(0)))
    if _DIGIT_ADJACENCY_RE.search(work_dated):
        hits.append(("spoken", "digit-adjacency"))
    for match in _GLUED_X_RE.finditer(work_dated):
        token = match.group(0)
        if (re.fullmatch(r"\d*[a-zA-Z]", token) and token[-1].casefold() == "x") or (
            re.fullmatch(r"[a-zA-Z]\d+", token) and token[0].casefold() == "x"
        ):
            hits.append(("spoken", token))
    if _N_TIMES_RE.search(lower):
        hits.append(("spoken", "n-times"))
    for match in _TALLY_RUN_RE.finditer(work):
        hits.append(("tally", match.group(0)))
    if _TALLY_WORD_RE.search(lower):
        hits.append(("tally", "tally"))
    return hits


_APPROX_WORD_RE = re.compile(r"[a-z0-9]+")


def _scan_approximators(
    work_dated: str, known_ids: Collection[str] = ()
) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    # Cited ids are blanked first so one holding an underscore stays whole;
    # any other underscore reads as a space. Words are read as words, so
    # brackets, quotes, emphasis marks or comma/colon/semicolon/slash marks
    # around the phrase or the number hide nothing.
    spaced = _blank_tokens(work_dated, known_ids).replace("_", " ")
    words = _APPROX_WORD_RE.findall(spaced.casefold())
    for phrase in _APPROXIMATORS:
        parts = phrase.split()
        for at in range(len(words) - len(parts) + 1):
            if words[at : at + len(parts)] != parts:
                continue
            if phrase == "up to" and at > 0 and words[at - 1] in _UP_TO_GUARD:
                continue
            window = words[at + len(parts) : at + len(parts) + 2]
            if any(w[:1].isdigit() or w in _NUMBER_WORDS for w in window):
                hits.append(("approximator", phrase))
                break
    if "~" in work_dated or "\u2248" in work_dated:
        hits.append(("approximator", "~"))
    return hits


def _scan_symbols(work_dated: str, in_since_last: bool) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for char in work_dated:
        if char in ("+", "=", "%", "`", "'"):
            continue
        if unicodedata.category(char) in ("So", "Sm", "Sk", "Sc"):
            hits.append(("symbol", char))
            break
    if not in_since_last and _SIGNED_PLUS_RE.search(work_dated):
        hits.append(("signed-plus", "+"))
    return hits


def _scan_clock(work: str) -> list[str]:
    hits: list[str] = []
    for match in _CLOCK_RE.finditer(work):
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3)) if match.group(3) else 0
        if not (hour <= 23 and minute <= 59 and second <= 59):
            continue
        if _CLOCK_UNMASK.match(work[match.end() :].lstrip()):
            continue
        before = work[: match.start()].rstrip()
        prev = before.split()[-1].casefold() if before.split() else ""
        prev = re.sub(r"[^a-z]", "", prev)
        if prev not in _CLOCK_ALLOWED_BEFORE:
            hits.append(match.group(0))
    return hits


def _scan_roman(
    blanked: str, cited_labels: Collection[str], has_metric_refs: bool
) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for match in _ROMAN_TOKEN_RE.finditer(blanked):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        if token.casefold() in cited_labels:
            continue
        if token in ("V", "X"):
            # Single V/X read as a numeral only on a metric claim (D8).
            if has_metric_refs:
                hits.append(token)
            continue
        if token == "I":
            continue
        only_ivx = set(token) <= {"I", "V", "X"}
        full = _ROMAN_RE.fullmatch(token) is not None
        if not full and not _I_RUN_RE.search(token):
            continue
        if (
            (full and only_ivx and len(token) >= 2)
            or (full and len(token) >= 4)
            or _I_RUN_RE.search(token)
        ):
            hits.append(token)
    return hits


def _scan_lower_roman(scrubbed: str, cited_labels: Collection[str]) -> list[str]:
    """Lower-case words the Roman rule would read once upper-cased."""
    hits: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<![\w-])[a-z]{2,}(?![\w-])", scrubbed.casefold()):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        upper = token.upper()
        if upper.casefold() in cited_labels:
            continue
        only_ivx = set(upper) <= {"I", "V", "X"}
        full = _ROMAN_RE.fullmatch(upper) is not None
        if not full and not _I_RUN_RE.search(upper):
            continue
        if (
            (full and only_ivx and len(upper) >= 2)
            or (full and len(upper) >= 4)
            or _I_RUN_RE.search(upper)
        ):
            hits.append(token)
    return hits


def _scan_ordinals_ranks(lower: str, work: str, has_metric_refs: bool) -> list[str]:
    hits: list[str] = []
    dehyphenated = _HYPHEN_COMPOUND_RE.sub(" ", work).casefold()
    dehyphenated = _AHEAD_GUARD_RE.sub(" ", dehyphenated)
    dehyphenated = _TIME_AHEAD_GUARD_RE.sub(" ", dehyphenated)
    if has_metric_refs:
        # A word ordinal inside a spaced period compound is the period,
        # never an order: blank those compounds like hyphens already do.
        from framework.briefing.claim_text import SPACED_PERIOD_COMPOUNDS

        for phrase in sorted(SPACED_PERIOD_COMPOUNDS, key=len, reverse=True):
            dehyphenated = re.sub(
                r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", dehyphenated
            )
        # R52, found by Muse Wonder Full's blind review of Ticket 11's
        # draft: on a metric claim any digit ordinal outside a date states
        # an order with no digit to back, whatever noun follows it. Dates
        # are blanked first so a day inside one stays quiet.
        for match in _DIGIT_ORDINAL_RE.finditer(_blank_dates(lower)):
            hits.append(match.group(0))
        for word in _WORD_ORDINALS | _RANK_WORDS:
            if _word_hit(dehyphenated, word):
                hits.append(word)
        for phrase in _RECORD_PHRASES:
            if _word_hit(lower, phrase) or _word_hit(dehyphenated, phrase):
                hits.append(phrase)
    else:
        noun = _DIGIT_ORDINAL_NOUN_RE.search(lower)
        if noun is not None:
            hits.append(noun.group(0))
    return hits


def _blank_tokens(text: str, tokens: Collection[str]) -> str:
    """Blank every ``tokens`` entry with spaces (length kept)."""
    names = [token for token in tokens if token]
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
                chars[pos] = " "
            start = index + len(needle)
    return "".join(chars)


def _scan_glued(work_dated: str) -> list[str]:
    """Letter-digit runs, minus the unit/ordinal/clock-owned suffixes."""
    hits: list[str] = []
    for match in _GLUED_RUN_RE.finditer(work_dated):
        token = match.group(0)
        if _GLUED_OWNED_SUFFIX_RE.search(token) is not None:
            continue
        hits.append(token)
    for match in _DASH_SUFFIX_RE.finditer(work_dated):
        hits.append(match.group(0))
    return hits


def _scan_qualifiers(lower: str, skip: Collection[str]) -> list[str]:
    """Qualifiers right after (past one unit/label word) or before a number."""
    skip_set = set(_QUALIFIER_UNITS) | {word.casefold() for word in skip}
    toks = [m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?|[a-z]+", lower)]

    def is_number(word: str) -> bool:
        return word[:1].isdigit() or word in _NUMBER_WORDS

    hits: list[str] = []
    for i, tok in enumerate(toks):
        if not is_number(tok):
            continue
        j = i + 1
        if j < len(toks) and toks[j] in skip_set:
            j += 1
        if j < len(toks):
            if toks[j] in _POST_QUALIFIER_SINGLE:
                hits.append(toks[j])
                continue
            rest = " ".join(toks[j : j + 3])
            if any(
                rest == phrase or rest.startswith(phrase + " ")
                for phrase in _POST_QUALIFIER_PHRASE
            ):
                hits.append(rest)
                continue
        prev = " ".join(toks[max(0, i - 3) : i])
        if any(
            prev == phrase or prev.endswith(" " + phrase)
            for phrase in _PRE_QUALIFIER_PHRASE
        ):
            hits.append(tok)
    return hits


def _single_before_form(lower: str, forms: Collection[str]) -> bool:
    """Whether ``a single`` sits right before one of ``forms``."""
    options = sorted({form.casefold() for form in forms if form}, key=len, reverse=True)
    if not options:
        return False
    for match in re.finditer(r"(?<!\w)a single(?!\w)", lower):
        rest = lower[match.end() :]
        for form in options:
            if re.match(r"\s*" + re.escape(form) + r"(?!\w)", rest) is not None:
                return True
    return False


def _scan_quantity_words(
    lower: str,
    has_metric_refs: bool,
    single_forms: Collection[str] | None = None,
) -> list[str]:
    """Scale words, tens/a-single phrases, and bare metric words.

    On a fact-only claim ``a single`` fires only right before one of
    ``single_forms`` (``None`` keeps the old every-claim behavior).
    """
    hits: list[str] = []
    for word in _QUANTITY_WORDS:
        if _word_hit(lower, word):
            hits.append(word)
    for phrase in _QUANTITY_PHRASES:
        if _word_hit(lower, phrase):
            if (
                phrase == "a single"
                and not has_metric_refs
                and single_forms is not None
                and not _single_before_form(lower, single_forms)
            ):
                continue
            hits.append(phrase)
    if has_metric_refs:
        for word in _METRIC_QUANTITY_WORDS:
            if _word_hit(lower, word):
                hits.append(word)
    return hits


def _scan_spelled_ordinals(lower: str) -> list[str]:
    return [m.group(0) for m in _SPELLED_ORDINAL_RE.finditer(lower)]


def _scan_tally(lower: str) -> list[str]:
    return [m.group(0) for m in _TALLY_REPEAT_RE.finditer(lower)]


def _scan_fractions(work_dated: str) -> list[str]:
    hits = [m.group(0) for m in _FRACTION_DIGIT_RE.finditer(work_dated)]
    return hits + [m.group(0) for m in _FRACTION_DECIMAL_RE.finditer(work_dated)]


def _scan_ranges(lower: str) -> list[str]:
    hits = [m.group(0) for m in _RANGE_RE.finditer(lower)]
    return hits + [m.group(0) for m in _BETWEEN_DIGIT_RE.finditer(lower)]


def _scan_universal(lower: str, label_tokens: Collection[str]) -> list[str]:
    """A universal word reaching a cited label token (not a coordination)."""
    labels = {label.casefold() for label in label_tokens if label}
    if not labels:
        return []
    hits: list[str] = []
    words = [m.group(0) for m in re.finditer(r"[a-z]+", lower)]
    for i, word in enumerate(words):
        if word not in _UNIVERSAL_WORDS:
            continue
        j = i + 1
        if j < len(words) and words[j] == "of":
            j += 1
        if j < len(words) and words[j] in _UNIVERSAL_DETERMINERS:
            j += 1
        if j >= len(words) or words[j] not in labels:
            continue
        if word == "both" and j + 1 < len(words) and words[j + 1] == "and":
            continue
        hits.append(word)
    return hits


def time_scope_hit(folded: str, exempt: Collection[str]) -> tuple[str, ...]:
    """Time-scope words in ``folded`` text outside ``exempt`` labels.

    ``folded`` is the casefolded normalised copy; ``verify_claims``
    calls this over its own texts later.
    """
    skip = {word.casefold() for word in exempt}
    hits: list[str] = []
    for phrase in _TIME_SCOPE_PHRASES + _RATE_PHRASES:
        if phrase in skip:
            continue
        if _word_hit(folded, phrase):
            hits.append(phrase)
    return tuple(sorted(set(hits)))


def find_unverifiable_quantities(
    text: str,
    *,
    has_metric_refs: bool,
    has_backed_fifty: bool,
    in_since_last: bool,
    cites_hours_metric: bool,
    known_names: Collection[str] = (),
    cited_labels: Collection[str] = (),
    known_ids: Collection[str] = (),
    cited_label_tokens: Collection[str] = (),
    single_forms: Collection[str] | None = None,
) -> tuple[str, ...]:
    """Kind tags for quantity shapes the gate cannot verify (D8)."""
    _ = cites_hours_metric
    norm = normalize_text(text)
    blanked = _blank_known_names(norm, known_names)
    # Cited ids are blanked before any underscore reads as a space, so an
    # id holding one stays whole in the underscore-sensitive scans.
    # Every kind reads that spaced copy: vague phrases, rank words and
    # qualifier phrases no less than approximators and quantity words.
    spaced = _blank_tokens(blanked, known_ids).replace("_", " ")
    lower_spaced = spaced.casefold()
    spaced_dated = _blank_valid_clocks(_blank_dates(spaced))
    unquoted = _blank_tokens(spaced, cited_label_tokens)
    unquoted_dated = _blank_valid_clocks(_blank_dates(unquoted))
    kinds: list[str] = []
    for kind, _tok in _scan(lower_spaced, spaced, spaced_dated):
        if (
            kind == "fraction"
            and has_backed_fifty
            and _tok
            in (
                "half",
                "halves",
            )
        ):
            continue
        kinds.append(kind)
    for kind, _tok in (
        _scan_approximators(spaced_dated, known_ids)
        + _scan_symbols(spaced_dated, in_since_last)
        + [("clock", t) for t in _scan_clock(spaced)]
        + [("roman", t) for t in _scan_roman(spaced, cited_labels, has_metric_refs)]
        + [
            ("ordinal", t)
            for t in _scan_ordinals_ranks(lower_spaced, spaced, has_metric_refs)
        ]
        + [
            ("approximator", t)
            for t in _scan_qualifiers(lower_spaced, cited_label_tokens)
        ]
        + [
            ("quantity", t)
            for t in _scan_quantity_words(lower_spaced, has_metric_refs, single_forms)
        ]
        + [("tally", t) for t in _scan_tally(lower_spaced)]
    ):
        kinds.append(kind)
    if has_metric_refs:
        for kind, _tok in (
            [("roman", t) for t in _scan_lower_roman(unquoted, cited_labels)]
            + [
                ("universal", t)
                for t in _scan_universal(lower_spaced, cited_label_tokens)
            ]
            + [("ordinal", t) for t in _scan_spelled_ordinals(lower_spaced)]
            + [("fraction", t) for t in _scan_fractions(spaced_dated)]
            + [("range", t) for t in _scan_ranges(lower_spaced)]
            + [("glued", t) for t in _scan_glued(unquoted_dated)]
        ):
            kinds.append(kind)
        kinds.extend("time" for _hit in time_scope_hit(lower_spaced, cited_labels))
    return tuple(sorted(set(kinds)))


def quantity_fired_tokens(
    text: str,
    *,
    has_metric_refs: bool,
    has_backed_fifty: bool,
    in_since_last: bool,
    cites_hours_metric: bool,
    known_names: Collection[str] = (),
    cited_labels: Collection[str] = (),
    known_ids: Collection[str] = (),
    cited_label_tokens: Collection[str] = (),
) -> set[str]:
    """Casefolded token texts behind the current quantity kinds."""
    _ = cites_hours_metric
    norm = normalize_text(text)
    blanked = _blank_known_names(norm, known_names)
    # Every kind reads the copy with underscores as spaces, matching
    # ``find_unverifiable_quantities`` so fired pieces stay exempt.
    spaced = _blank_tokens(blanked, known_ids).replace("_", " ")
    lower_spaced = spaced.casefold()
    spaced_dated = _blank_valid_clocks(_blank_dates(spaced))
    unquoted = _blank_tokens(spaced, cited_label_tokens)
    unquoted_dated = _blank_valid_clocks(_blank_dates(unquoted))
    out: set[str] = set()
    for kind, tok in _scan(lower_spaced, spaced, spaced_dated):
        if (
            kind == "fraction"
            and has_backed_fifty
            and tok
            in (
                "half",
                "halves",
            )
        ):
            continue
        for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
            out.add(piece)
    for kind, tok in _scan_approximators(spaced_dated, known_ids):
        for piece in phrase_pieces(tok):
            out.add(piece)
    for kind, tok in _scan_symbols(spaced_dated, in_since_last):
        if kind == "symbol" and len(tok) == 1:
            continue
        out.add(tok.casefold())
    for tok in _scan_clock(spaced):
        out.add(tok.casefold())
    for tok in _scan_roman(spaced, cited_labels, has_metric_refs):
        out.add(tok.casefold())
    if has_metric_refs:
        for tok in _scan_lower_roman(unquoted, cited_labels):
            out.add(tok.casefold())
    for tok in _scan_ordinals_ranks(lower_spaced, spaced, has_metric_refs):
        for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
            out.add(piece)
    for tok in _scan_spelled_ordinals(lower_spaced) if has_metric_refs else ():
        for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
            out.add(piece)
    for tok in _scan_tally(lower_spaced):
        out.add(tok.split(",")[0].strip().casefold())
        for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
            out.add(piece)
    for tok in _scan_qualifiers(lower_spaced, cited_label_tokens):
        for piece in phrase_pieces(tok):
            out.add(piece)
    for tok in _scan_quantity_words(lower_spaced, has_metric_refs):
        for piece in phrase_pieces(tok):
            out.add(piece)
    if has_metric_refs:
        for tok in _scan_universal(lower_spaced, cited_label_tokens):
            out.add(tok.casefold())
        for tok in _scan_fractions(spaced_dated):
            out.add(tok.casefold())
            for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
                out.add(piece)
        for tok in _scan_ranges(lower_spaced):
            for piece in phrase_pieces(tok):
                out.add(piece)
        for tok in _scan_glued(unquoted_dated):
            out.add(tok.casefold())
            for piece in re.findall(r"[a-z0-9]+", tok.casefold()):
                out.add(piece)
        for hit in time_scope_hit(lower_spaced, cited_labels):
            for piece in phrase_pieces(hit):
                out.add(piece)
    return out


def phrase_pieces(phrase: str) -> list[str]:
    """Casefolded word pieces of an approximator phrase."""
    return re.findall(r"[a-z0-9]+", phrase.casefold())
