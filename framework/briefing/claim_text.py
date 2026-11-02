"""Ticket 10b: claim-only text rules (D9, D12, D13, D14, D21).

``claim_text_codes`` runs the rules that apply to claim text only: titles
and outbound prompts never see them. ``fact_claim_codes`` checks fact-only
claims against their cited statements. Every comparison runs on
``normalize_text`` output, casefolded locally; the normaliser itself
preserves case.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections.abc import Collection
from decimal import Decimal

from framework.briefing.labels import (
    label_forms,
    metric_label_binding,
    metric_unit_class,
)
from framework.briefing.normalize import has_unsafe_text, normalize_text
from framework.briefing.numbers import NumberToken, find_known_names
from framework.briefing.quantities import (
    find_unverifiable_quantities,
    quantity_fired_tokens,
)

UP_WORDS: frozenset[str] = frozenset(
    {
        "up",
        "rose",
        "rise",
        "rises",
        "rising",
        "risen",
        "increase",
        "increased",
        "increases",
        "increasing",
        "more",
        "higher",
        "grew",
        "grow",
        "grows",
        "growing",
        "grown",
        "climb",
        "climbs",
        "climbed",
        "climbing",
        "growth",
        "surge",
        "surges",
        "surged",
        "soar",
        "soars",
        "soared",
        "exceed",
        "exceeds",
        "exceeded",
        "exceeding",
        "gain",
        "gains",
        "gained",
        "jump",
        "jumps",
        "jumped",
        "uptick",
        "expansion",
        "expand",
        "expands",
        "expanded",
        "spike",
        "spikes",
        "spiked",
        "spiking",
        "surging",
        "soaring",
        "gaining",
        "jumping",
        "upturn",
        "upswing",
        "uptrend",
        "upward",
        "upwards",
        "expanding",
        "boost",
        "boosts",
        "boosted",
        "rebound",
        "rebounds",
        "rebounded",
        "rally",
        "rallied",
        "rallies",
        "leap",
        "leaps",
        "leapt",
        "rocket",
        "rockets",
        "rocketed",
        "skyrocket",
        "skyrockets",
        "skyrocketed",
        "balloon",
        "balloons",
        "ballooned",
        "swell",
        "swelled",
        "swells",
        "mounted",
        "overtook",
        "overtake",
        "overtakes",
        "outpaced",
        "outpaces",
        "outnumbered",
        "outnumbers",
        "surpassed",
        "surpasses",
        "beat",
        "beats",
        "dwarfed",
        "dwarfs",
        "eclipsed",
        "eclipses",
        "topped",
        "tops",
        "greater",
        "bigger",
        "larger",
        "stronger",
        "better",
        "improved",
        "improves",
        "improvement",
        "heavier",
        "longer",
        "busier",
        "bounce",
        "bounces",
        "bounced",
        "recover",
        "recovers",
        "recovered",
        "recovering",
        "uptrending",
        "uptrended",
        "upticking",
        "upticked",
    }
)
DOWN_WORDS: frozenset[str] = frozenset(
    {
        "down",
        "fell",
        "fall",
        "falls",
        "falling",
        "fallen",
        "decrease",
        "decreased",
        "decreases",
        "decreasing",
        "less",
        "fewer",
        "lower",
        "dropped",
        "drop",
        "drops",
        "dropping",
        "decline",
        "declines",
        "declined",
        "declining",
        "shrink",
        "shrinks",
        "shrank",
        "shrunk",
        "contract",
        "contracts",
        "contracted",
        "plunge",
        "plunges",
        "plunged",
        "tumble",
        "tumbles",
        "tumbled",
        "slip",
        "slips",
        "slipped",
        "slide",
        "slides",
        "slid",
        "sliding",
        "sink",
        "sinks",
        "sank",
        "sunk",
        "sinking",
        "dip",
        "dips",
        "dipped",
        "dipping",
        "downturn",
        "downtrend",
        "downswing",
        "downward",
        "downwards",
        "slump",
        "slumps",
        "slumped",
        "sag",
        "sagged",
        "wane",
        "waned",
        "waning",
        "ebb",
        "ebbed",
        "recede",
        "receded",
        "retreat",
        "retreated",
        "dwindle",
        "dwindled",
        "dwindling",
        "fade",
        "faded",
        "taper",
        "tapered",
        "ease",
        "eased",
        "collapse",
        "collapsed",
        "crash",
        "crashed",
        "crater",
        "cratered",
        "plummet",
        "plummets",
        "plummeted",
        "nosedive",
        "nosedived",
        "cut",
        "cuts",
        "reduce",
        "reduced",
        "reduces",
        "reduction",
        "lost",
        "loss",
        "losses",
        "lose",
        "loses",
        "shed",
        "smaller",
        "weaker",
        "worse",
        "worsened",
        "shorter",
        "quieter",
        "lighter",
        "slower",
        "bottomed",
        "downtrending",
        "downtrended",
        "downtick",
        "downticking",
        "downticked",
    }
)
SAME_WORDS = frozenset(
    {
        "unchanged",
        "flat",
        "constant",
        "stayed",
        "remained",
        "same",
        "level",
        "held",
        "matched",
        "equalled",
        "equaled",
        "equal",
        "equals",
        "tied",
        "mirrored",
    }
)
STEADY_WORDS = frozenset({"steady", "stable"})

NEGATORS_SINGLE = frozenset(
    {
        "not",
        "never",
        "no",
        "none",
        "neither",
        "nor",
        "without",
        "hardly",
        "barely",
        "scarcely",
        "rarely",
        "seldom",
        "nothing",
        "nobody",
        "cannot",
        "unable",
        "failed",
        "fails",
        "fail",
        "false",
        "untrue",
        "incorrect",
        "wrong",
        "contrary",
        "opposite",
        "reverse",
        "instead",
        "unlike",
        "non-zero",
        "nonzero",
    }
)
NEGATORS_PHRASE = (
    "rather than",
    "instead of",
    "anything but",
    "far from",
    "other than",
    "apart from",
    "aside from",
    "except for",
)

PERIOD_WORDS = ("earlier", "prior", "last")
SINCE_LAST_PHRASES = (
    ("since", "the", "last", "card"),
    ("since", "my", "last", "card"),
    ("since", "the", "previous", "card"),
)
_SINCE_LAST_PREPS = ("in", "during", "for", "over", "across")
_SINCE_LAST_GENERIC_PREPS = ("in", "during", "over", "across")
ADVICE_PHRASES = ("push harder", "rest more")

SPACED_PERIOD_COMPOUNDS = (
    "second to last",
    "next to last",
    "third to last",
    "one before last",
    "before last",
    "last but one",
    "penultimate",
)
# Compounds naming the window before last read as ``prior``; the third
# window back reads as ``earlier``. Spaced and hyphenated alike; their
# own words never count as period words.
_PRIOR_COMPOUNDS = (
    "second to last",
    "next to last",
    "one before last",
    "before last",
    "last but one",
    "penultimate",
)
_EARLIER_COMPOUNDS = ("third to last",)
_NON_PERIOD_SENSES = (
    "at last",
    "last year",
    "last month",
    "last week",
    "last night",
    "last time",
    "prior year",
    "prior month",
    "prior week",
    "earlier today",
    "earlier than",
    "earlier this",
    "last place",
    "last resort",
    "last hour",
    "last minute",
    "last minutes",
    "last few",
    "last one",
    "last ones",
    "last card",
    "last session",
    "last stand",
    "last word",
    "last call",
    "last commit",
    "prior art",
    "prior knowledge",
)

_HYPHEN_COMPOUND_RE = re.compile(r"\w+(?:-\w+)+")
_DIRECTION_TOKEN_RE = re.compile(r"\w+(?:-\w+)*")
_FROM_TO_RE = re.compile(
    r"\bfrom\s+(earlier|prior|last)\b.*?\bto\s+(earlier|prior|last)\b"
)

COMPARISON_VOCABULARY = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "on",
        "of",
        "to",
        "from",
        "and",
        "or",
        "then",
        "through",
        "across",
        "between",
        "at",
        "by",
        "for",
        "with",
        "while",
        "than",
        "as",
        "that",
        "those",
        "this",
        "these",
        "it",
        "its",
        "their",
        "there",
        "both",
        "each",
        "all",
        "also",
        "still",
        "only",
        "just",
        "again",
        "further",
        "after",
        "before",
        "during",
        "over",
        "into",
        "compared",
        "versus",
        "vs",
        "period",
        "periods",
        "window",
        "screen",
        "hours",
        "hour",
        "hr",
        "hrs",
        "time",
        "count",
        "counts",
        "total",
        "totals",
        "number",
        "activity",
        "blocks",
        "block",
        "calendar",
        "github",
        "cancelled",
        "canceled",
        "cancel",
        "cancels",
        "cancellation",
        "cancellations",
        "were",
        "was",
        "is",
        "are",
        "be",
        "been",
        "had",
        "has",
        "have",
        "went",
        "moved",
        "moves",
        "changed",
        "changes",
        "shifted",
        "stood",
        "ranged",
        "numbered",
        "totaled",
        "totalled",
        "came",
        "reached",
        "recorded",
        "showed",
        "saw",
        "logged",
        "landed",
        "ended",
        "sharply",
        "steadily",
        "slightly",
        "down",
        "up",
        "feed",
        "feeds",
        "i",
        "you",
        "we",
        "my",
        "your",
        "our",
        "me",
        "us",
        "spent",
        "worked",
        "opened",
        "closed",
        "merged",
        "made",
        "did",
        "got",
        "done",
        "times",
        "but",
        "whereas",
        "overall",
        "respectively",
    }
)

SPANISH_DIRECTION = frozenset(
    {
        "subieron",
        "subió",
        "suben",
        "sube",
        "aumentaron",
        "aumentó",
        "aumentan",
        "aumenta",
        "crecieron",
        "creció",
        "crecen",
        "crece",
        "cayeron",
        "cayó",
        "caen",
        "cae",
        "descendieron",
        "descendió",
        "descienden",
        "desciende",
        "disminuyeron",
        "disminuyó",
        "disminuyen",
        "disminuye",
        "decrecieron",
        "decreció",
        "decrecen",
        "decrece",
        "subir",
        "aumentar",
        "crecer",
        "caer",
        "descender",
        "disminuir",
        "decrecer",
    }
)
SPANISH_NUMBERS = frozenset(
    {
        "uno",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
    }
)
SPANISH_ADVICE = frozenset({"debes", "deberías"})
FRENCH_DIRECTION = frozenset(
    {
        "montent",
        "baissent",
        "augmentent",
        "diminuent",
        "chutent",
        "grimpent",
    }
)
FRENCH_NUMBERS = frozenset({"deux", "trois", "quatre", "cinq", "huit", "neuf", "dix"})
FRENCH_ADVICE = frozenset({"devez", "envoyez", "expédiez"})
GERMAN_DIRECTION = frozenset(
    {"steigt", "steigen", "stieg", "sinkt", "sinken", "sanken"}
)
GERMAN_NUMBERS = frozenset(
    {
        "eins",
        "zwei",
        "drei",
        "vier",
        "fünf",
        "sechs",
        "sieben",
        "acht",
        "neun",
        "zehn",
    }
)
GERMAN_ADVICE = frozenset({"musst", "sende", "schicke"})
ITALIAN_DIRECTION = frozenset(
    {
        "aumentano",
        "aumentato",
        "diminuiscono",
        "diminuito",
        "crescono",
        "cresciuto",
        "calano",
        "calato",
        "salgono",
        "salito",
        "scendono",
        "sceso",
    }
)
ITALIAN_NUMBERS = frozenset(
    {
        "uno",
        "tre",
        "quattro",
        "cinque",
        "sei",
        "sette",
        "nove",
        "dieci",
    }
)
ITALIAN_ADVICE = frozenset({"devi", "invia", "prova"})
PORTUGUESE_DIRECTION = frozenset(
    {
        "subiram",
        "subiu",
        "aumentaram",
        "aumentou",
        "diminuiram",
        "diminuiu",
        "cresceram",
        "cresceu",
        "desceram",
        "desceu",
    }
)
PORTUGUESE_NUMBERS = frozenset(
    {
        "dois",
        "três",
        "quatro",
        "cinco",
        "seis",
        "sete",
        "oito",
        "nove",
        "dez",
    }
)
PORTUGUESE_ADVICE = frozenset({"deves", "envia", "tenta"})
DUTCH_DIRECTION = frozenset(
    {
        "stijgt",
        "stegen",
        "daalt",
        "daalden",
        "groeit",
        "krimpt",
    }
)
DUTCH_NUMBERS = frozenset(
    {
        "twee",
        "drie",
        "vijf",
        "zes",
        "zeven",
        "negen",
        "tien",
    }
)
DUTCH_ADVICE = frozenset({"verzend", "stuur", "moet", "probeer"})

FOREIGN_DIRECTION_TOKENS = (
    SPANISH_DIRECTION
    | FRENCH_DIRECTION
    | GERMAN_DIRECTION
    | ITALIAN_DIRECTION
    | PORTUGUESE_DIRECTION
    | DUTCH_DIRECTION
)
FOREIGN_NUMBER_TOKENS = (
    SPANISH_NUMBERS
    | FRENCH_NUMBERS
    | GERMAN_NUMBERS
    | ITALIAN_NUMBERS
    | PORTUGUESE_NUMBERS
    | DUTCH_NUMBERS
)
FOREIGN_ADVICE_TOKENS = (
    SPANISH_ADVICE
    | FRENCH_ADVICE
    | GERMAN_ADVICE
    | ITALIAN_ADVICE
    | PORTUGUESE_ADVICE
    | DUTCH_ADVICE
)

FOREIGN_STOPWORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        {
            "el",
            "la",
            "los",
            "las",
            "de",
            "en",
            "y",
            "una",
            "por",
            "para",
            "del",
            "al",
            "es",
            "son",
            "durante",
            "próximo",
            "próxima",
            "sin",
            "con",
            "semana",
            "pero",
            "que",
            "muy",
        }
    ),
    "fr": frozenset(
        {
            "le",
            "la",
            "les",
            "de",
            "des",
            "une",
            "du",
            "au",
            "aux",
            "est",
            "sont",
            "pendant",
            "prochain",
            "prochaine",
            "petit",
            "libre",
        }
    ),
    "de": frozenset(
        {
            "der",
            "die",
            "das",
            "und",
            "den",
            "von",
            "zu",
            "mit",
            "für",
            "ist",
            "sind",
            "während",
            "nächste",
            "kleinen",
        }
    ),
    "it": frozenset(
        {
            "il",
            "lo",
            "gli",
            "le",
            "della",
            "delle",
            "durante",
            "prossimo",
            "prossima",
            "sono",
            "nel",
            "nella",
        }
    ),
    "pt": frozenset(
        {
            "os",
            "uma",
            "durante",
            "próxima",
            "são",
            "pelo",
            "pela",
            "foram",
            "era",
            "sobre",
            "entre",
        }
    ),
    "nl": frozenset(
        {
            "de",
            "het",
            "een",
            "en",
            "van",
            "op",
            "voor",
            "naar",
            "volgende",
            "vrije",
            "uur",
            "kleine",
        }
    ),
}
ENGLISH_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "on",
        "of",
        "to",
        "from",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "at",
        "by",
        "for",
        "with",
        "since",
        "last",
        "prior",
    }
)

CLAIM_ONLY_PHRASES = (
    "ought to",
    "need to",
    "needs to",
    "have to",
    "has to",
    "supposed to",
    "be sure to",
    "make sure to",
    "don't forget to",
    "remember to",
    "it is time to",
    "it's time to",
    "why not",
    "why don't you",
    "why not try",
    "consider",
    "you could",
    "could try",
    "might want to",
    "may want to",
    "i recommend",
    "i suggest",
    "we recommend",
    "we suggest",
    "recommend that",
    "suggest that",
    "please",
    "let's",
    "let us",
    "how about",
    "what about",
    "what if",
    "try to",
    "next step",
    "best to",
    "better to",
    "wise to",
    "you can",
    "you could",
    "you may",
    "you might",
    "you will",
    "you'll",
    "you would",
    "you'd",
    "you need",
    "you want",
    "you had better",
    "you better",
    "advise",
    "advised",
    "recommend",
    "recommended",
    "recommends",
    "recommendation",
    "suggest",
    "suggested",
    "suggests",
    "suggestion",
    "encourage",
    "encouraged",
    "urge",
    "urged",
    "worth trying",
)

STRONG_VERBS = frozenset(
    {
        "ship",
        "build",
        "write",
        "go",
        "take",
        "make",
        "do",
        "try",
        "start",
        "stop",
        "finish",
        "keep",
        "get",
        "spend",
        "use",
        "schedule",
        "book",
        "buy",
        "eat",
        "drink",
        "sleep",
        "focus",
        "aim",
        "stick",
        "pick",
        "carry",
        "turn",
        "switch",
        "leave",
        "bring",
        "set",
        "put",
        "fix",
        "add",
        "remove",
        "delete",
        "update",
        "create",
        "deploy",
        "merge",
        "open",
        "close",
        "send",
        "check",
        "review",
        "polish",
        "launch",
        "finalize",
        "prepare",
        "think",
        "wait",
        "pause",
        "skip",
        "avoid",
        "publish",
        "ask",
        "learn",
        "look",
    }
)
AMBIGUOUS_VERBS = frozenset(
    {
        "walk",
        "rest",
        "read",
        "plan",
        "call",
        "join",
        "log",
        "play",
        "move",
        "push",
        "commit",
        "exercise",
        "show",
        "hide",
        "release",
        "draft",
        "share",
        "post",
        "practice",
        "talk",
        "meet",
        "test",
        "run",
    }
)
_DETERMINERS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "his",
        "her",
        "its",
        "our",
        "their",
    }
)
_NOUN_USE_WORDS = frozenset(
    {
        "total",
        "totals",
        "count",
        "counts",
        "hours",
        "hour",
        "time",
        "activity",
        "output",
        "list",
        "log",
        "logs",
        "notes",
        "session",
        "sessions",
        "block",
        "blocks",
        "work",
    }
)
_COPULAS = frozenset({"is", "are", "was", "were", "has", "had"})
_NUMBER_WORDS_DET = frozenset(
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
# Spelled numbers the value-period rule reads as values: whole words at
# most twelve (plus dozen), which never count as unknown comparison words.
_READABLE_SPELLED = frozenset(
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
        "dozen",
    }
)

_FACT_PARTICLES = (
    "lined up",
    "showed up",
    "shows up",
    "show up",
    "showing up",
    "took up",
    "takes up",
    "take up",
    "taking up",
    "set up",
    "wrote up",
    "wrapped up",
    "followed up",
    "follow up",
    "wrote down",
    "sat down",
)

_HOUR_WORDS = frozenset({"hour", "hours", "hr", "hrs"})
_TIME_UNITS = frozenset(
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
    }
)
_DAY_UNITS = frozenset(
    {
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
    }
)
_GLUED_UNIT_RE = re.compile(r"\d+(?:\.\d+)?(?:min|mins|m|s|sec|secs|h|hr|hrs)\b")


def _fold(text: str) -> str:
    """Accent-folded casefold of ``text`` (list entries stored folded)."""
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
        if unicodedata.category(c) != "Mn"
    ).casefold()


def _tokens(lower: str) -> list[str]:
    return _DIRECTION_TOKEN_RE.findall(lower)


def _contains_token(haystack: str, needle: str) -> bool:
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        before = haystack[index - 1] if index > 0 else ""
        end = index + len(needle)
        after = haystack[end] if end < len(haystack) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            return True
        start = index + 1


def _token_spans(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Whole-token occurrence spans of ``needle`` in ``haystack``."""
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        before = haystack[index - 1] if index > 0 else ""
        end = index + len(needle)
        after = haystack[end] if end < len(haystack) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            spans.append((index, end))
        start = index + 1
    return spans


def _remove_whole(text: str, phrase: str) -> str:
    return re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", text)


def _space_underscores_after_blank(
    text: str,
    known_ids: Collection[str] = (),
    known_names: Collection[str] = (),
) -> str:
    """Copy of ``text`` with every ``_`` outside cited ids/names as a space.

    Known ids and names are blanked first so an id the claim cites stays
    whole; any other underscore reads as a space on the working copy.
    """
    out = text
    lowered = out.casefold()
    for token in list(known_ids) + list(known_names):
        if not token:
            continue
        needle = token.casefold()
        chars = list(out)
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            for pos in range(index, index + len(needle)):
                chars[pos] = " "
            start = index + len(needle)
        out = "".join(chars)
        lowered = out.casefold()
    return out.replace("_", " ")


def without_count_held(text: str) -> str:
    """Blank ``held`` used as containment (``held 9``), not direction."""
    return re.sub(
        r"\bheld(?=\s+(?:\d|" + "|".join(sorted(_NUMBER_WORDS_DET)) + r")\b)",
        " ",
        normalize_text(text),
        flags=re.IGNORECASE,
    )


_THAN_COMPARATIVES = frozenset(
    {
        "higher",
        "lower",
        "more",
        "less",
        "fewer",
        "greater",
        "bigger",
        "larger",
        "smaller",
        "better",
        "worse",
        "longer",
        "shorter",
    }
)
_ABOVE_BASES = frozenset({"average", "normal", "usual", "target", "expected"})
_FACT_HYPHEN_PARTICLES = (
    "up-to-date",
    "up-to",
    "up-front",
    "follow-up",
    "write-up",
    "wrap-up",
    "set-up",
    "sign-up",
    "start-up",
    "check-up",
    "pick-up",
    "line-up",
    "back-up",
    "round-up",
    "roll-up",
    "clean-up",
    "sit-down",
    "top-down",
    "drop-down",
)


def hyphen_directions(text: str) -> set[str]:
    """Direction words read from hyphen compounds in ``text``.

    A comparative joined by ``than`` adds that comparative; ``above-``
    (``below-``) before a baseline word adds up (down); otherwise an
    ``up-`` (``down-``) prefix adds that side, except ``up-to``,
    ``up-front`` and ``down-to``. Used on the metric path and the fact
    arm alike.
    """
    out: set[str] = set()
    for match in _DIRECTION_TOKEN_RE.finditer(text):
        token = match.group(0)
        if "-" not in token:
            continue
        parts = token.split("-")
        if parts[0] in _THAN_COMPARATIVES and len(parts) >= 2 and parts[1] == "than":
            out.add(parts[0])
            continue
        if token in {"above-" + base for base in _ABOVE_BASES}:
            out.add("up")
            continue
        if token in {"below-" + base for base in _ABOVE_BASES}:
            out.add("down")
            continue
        if (
            parts[0] == "up"
            and token != "up-to"
            and not token.startswith("up-to-")
            and token != "up-front"
            and not token.startswith("up-front-")
            and len(parts) > 1
            and parts[1][:1].isalpha()
        ):
            out.add("up")
        elif (
            parts[0] == "down"
            and token != "down-to"
            and len(parts) > 1
            and parts[1][:1].isalpha()
        ):
            out.add("down")
    return out


_HYPHEN_SPACED_PARTICLES = tuple(phrase.replace(" ", "-") for phrase in _FACT_PARTICLES)


def _remove_hyphen_particles(text: str) -> str:
    """Copy of ``text`` without the hyphenated phrasal particles.

    Every spaced particle also counts hyphenated, past tenses too, so
    ``followed-up`` reads like ``follow up`` and hides no direction word.
    """
    out = text
    particles = set(_FACT_HYPHEN_PARTICLES) | set(_HYPHEN_SPACED_PARTICLES)
    for particle in sorted(particles, key=len, reverse=True):
        out = _remove_whole(out, particle)
    return out


_TIED_TO_RE = re.compile(r"(?<!\w)tied(?=\s+to(?!\w))", re.IGNORECASE)


def drop_tied_to(text: str) -> str:
    """Copy of ``text`` with connective ``tied`` blanked.

    ``tied`` immediately followed by ``to`` states a connection, never
    equality, so the direction rule reads no same-direction word there;
    bare ``tied`` or ``tied with`` still reads as one.
    """
    return _TIED_TO_RE.sub("    ", text)


def direction_side(tokens: Collection[str], *, metric_claim: bool) -> str | None:
    """Effective direction side of ``tokens``: up, down, same or mixed."""
    present = set(tokens)
    ups = any(t in UP_WORDS for t in present)
    downs = any(t in DOWN_WORDS for t in present)
    sames = any(t in SAME_WORDS for t in present)
    if metric_claim:
        sames = sames or any(t in STEADY_WORDS for t in present)
    total = (1 if ups else 0) + (1 if downs else 0) + (1 if sames else 0)
    if total == 0:
        return None
    if total > 1:
        return "mixed"
    if ups:
        return "up"
    if downs:
        return "down"
    return "same"


#: Verbs after which ``steady``/``stable`` state sameness on a metric claim.
_STEADY_COPULAS = frozenset(
    {
        "was",
        "were",
        "is",
        "are",
        "stayed",
        "stays",
        "remained",
        "remains",
        "held",
        "holds",
        "kept",
        "keeps",
        "looked",
        "looks",
        "sat",
    }
)


def steady_same_counts(lower: str, label_forms: Collection[str]) -> bool:
    """Whether ``steady``/``stable`` states sameness in ``lower``.

    Only right after one of ``label_forms`` or after a copula-like verb;
    before a noun they read as adjectives and state no direction.
    """
    words = [match.group(0) for match in re.finditer(r"[a-z]+", lower)]
    form_lists = [
        [match.group(0) for match in re.finditer(r"[a-z]+", form.casefold())]
        for form in label_forms
        if form and re.search(r"[a-z]", form)
    ]
    for index, word in enumerate(words):
        if word not in STEADY_WORDS:
            continue
        if index > 0 and words[index - 1] in _STEADY_COPULAS:
            return True
        for form_words in form_lists:
            if not form_words:
                continue
            start = index - len(form_words)
            if start >= 0 and words[start:index] == form_words:
                return True
    return False


def _compound_variants(phrase: str) -> tuple[str, str]:
    """Spaced and hyphenated forms of one period compound."""
    return (phrase, "-".join(phrase.split()))


def remove_period_phrases(lower: str) -> str:
    """Copy of ``lower`` with period compounds and non-period senses gone.

    Compounds naming the window before last read as ``prior`` (third
    back as ``earlier``); their own words never count as period words.
    """
    out = lower
    for phrase in sorted(_PRIOR_COMPOUNDS + _EARLIER_COMPOUNDS, key=len, reverse=True):
        word = "prior" if phrase in _PRIOR_COMPOUNDS else "earlier"
        for variant in _compound_variants(phrase):
            out = re.sub(r"(?<!\w)" + re.escape(variant) + r"(?!\w)", f" {word} ", out)
    out = _HYPHEN_COMPOUND_RE.sub(" ", out)
    for phrase in sorted(SPACED_PERIOD_COMPOUNDS, key=len, reverse=True):
        out = _remove_whole(out, phrase)
    for phrase in sorted(_NON_PERIOD_SENSES, key=len, reverse=True):
        out = _remove_whole(out, phrase)
    out = re.sub(r"\bprior to(?=\s+(?:earlier|prior|last)\b)", " ", out)
    return out


def _from_to_periods(lower: str) -> set[str]:
    found: set[str] = set()
    for match in _FROM_TO_RE.finditer(lower):
        found.add(match.group(1))
        found.add(match.group(2))
    return found


def counted_periods(lower: str) -> set[str]:
    """Period words the claim really states (D9 removals plus from-to)."""
    cleaned = remove_period_phrases(lower)
    present = {w for w in PERIOD_WORDS if _contains_token(cleaned, w)}
    return present | (_from_to_periods(lower) & set(PERIOD_WORDS))


def has_negator(
    lower: str,
    known_ids: Collection[str] = (),
    known_names: Collection[str] = (),
) -> bool:
    """Whether a closed D9 negator appears anywhere in ``lower``.

    An underscore reads as a space once cited ids and names are blanked,
    so ``not_fell`` negates like ``not fell``.
    """
    work = _space_underscores_after_blank(lower, known_ids, known_names)
    if "n't" in work:
        return True
    for token in _tokens(work):
        if token in NEGATORS_SINGLE:
            return True
        if "-" in token and any(part in NEGATORS_SINGLE for part in token.split("-")):
            return True
    for phrase in NEGATORS_PHRASE:
        if _contains_token(work, phrase):
            return True
    return False


def stated_zero_code(
    lower: str,
    cited: Collection[tuple[str, float]],
    cited_labels: Collection[str],
) -> str | None:
    """None when a stated zero passes; otherwise the failing code."""
    for word in ("no", "zero"):
        for match in re.finditer(r"(?<!\w)" + word + r"(?!\w)", lower):
            # The zero inside non-zero/nonzero/non zero is the negator
            # itself, never a stated zero.
            if word == "zero" and re.search(
                r"(?<!\w)non[ -]?$", lower[: match.start()]
            ):
                continue
            rest = lower[match.end() :].lstrip()
            for label in cited_labels:
                if re.match(re.escape(label) + r"(?!\w)", rest) is None:
                    continue
                values = [
                    value
                    for metric_id, value in cited
                    if (
                        (binding := metric_label_binding(metric_id)) is not None
                        and label in {item.casefold() for item in binding.labels}
                    )
                ]
                if values:
                    if any(value == 0 for value in values):
                        return None
                    return "L1B_NUMBER_WITHOUT_METRIC_REF"
    return "L1B_NEGATED_CLAIM"


def _strip_for_vocab(
    lower: str,
    *,
    cited_label_tokens: Collection[str],
    negator: bool,
    quantity_tokens: Collection[str],
) -> list[str]:
    cleaned = lower
    for phrase in sorted(_PRIOR_COMPOUNDS + _EARLIER_COMPOUNDS, key=len, reverse=True):
        word = "prior" if phrase in _PRIOR_COMPOUNDS else "earlier"
        for variant in _compound_variants(phrase):
            cleaned = re.sub(
                r"(?<!\w)" + re.escape(variant) + r"(?!\w)", f" {word} ", cleaned
            )
    cleaned = _remove_hyphen_particles(cleaned)
    for token in set(_DIRECTION_TOKEN_RE.findall(cleaned)):
        if "-" in token and hyphen_directions(token):
            cleaned = _remove_whole(cleaned, token)
    # A compound holding a direction word as one part is not known
    # vocabulary through its other part: `over-` joined to a direction
    # word hides a direction the values may contradict. Only compounds
    # the direction rule reads stay known here.
    direction_parts = UP_WORDS | DOWN_WORDS | SAME_WORDS | STEADY_WORDS
    for token in set(_HYPHEN_COMPOUND_RE.findall(cleaned)):
        if "-" not in token or hyphen_directions(token):
            continue
        if any(part in direction_parts for part in token.split("-")):
            cleaned = re.sub(
                r"(?<!\w)" + re.escape(token) + r"(?!\w)", " zzunknownword ", cleaned
            )
    for token in cited_label_tokens:
        if "-" in token:
            cleaned = _remove_whole(cleaned, token)
    cleaned = re.sub(r"(?<=\w)-(?=\w)", " ", cleaned)
    for phrase in sorted(SPACED_PERIOD_COMPOUNDS, key=len, reverse=True):
        cleaned = _remove_whole(cleaned, phrase)
    for phrase in sorted(_NON_PERIOD_SENSES, key=len, reverse=True):
        cleaned = _remove_whole(cleaned, phrase)
    cleaned = re.sub(r"\bprior to(?=\s+(?:earlier|prior|last)\b)", " ", cleaned)
    for token in cited_label_tokens:
        cleaned = _remove_whole(cleaned, token)
    for word in PERIOD_WORDS:
        cleaned = _remove_whole(cleaned, word)
    for word in UP_WORDS | DOWN_WORDS | SAME_WORDS | STEADY_WORDS:
        cleaned = _remove_whole(cleaned, word)
    if negator:
        for token in NEGATORS_SINGLE:
            cleaned = _remove_whole(cleaned, token)
        cleaned = re.sub(r"n't", " ", cleaned)
        for phrase in NEGATORS_PHRASE:
            cleaned = _remove_whole(cleaned, phrase)
    for token in (
        FOREIGN_DIRECTION_TOKENS | FOREIGN_ADVICE_TOKENS | FOREIGN_NUMBER_TOKENS
    ):
        cleaned = _remove_whole(cleaned, _fold(token))
    for token in quantity_tokens:
        cleaned = _remove_whole(cleaned, token)
    for token in _READABLE_SPELLED:
        cleaned = _remove_whole(cleaned, token)
    # Digit strings joined by underscores are numbers, not words: `3_000`
    # reads as digits, so the vocabulary rule leaves it to the number rules.
    return [
        t
        for t in _tokens(cleaned)
        if not t.isdigit() and not t.replace("_", "").isdigit()
    ]


def eligible_comparison(cited: Collection[tuple[str, float]]) -> bool:
    """D9 eligibility: 2-3 refs, one family, distinct periods, all period."""
    items = list(cited)
    if not 2 <= len(items) <= 3:
        return False
    bindings = [metric_label_binding(metric) for metric, _v in items]
    if any(b is None for b in bindings):
        return False
    known = [b for b in bindings if b is not None]
    periods = [b.period for b in known]
    families = {b.family for b in known}
    return (
        all(p is not None for p in periods)
        and len(families) == 1
        and len(set(periods)) == len(periods)
    )


_MAGNITUDE_UNITS = frozenset(
    {
        "k",
        "m",
        "mn",
        "b",
        "bn",
        "km",
        "kg",
        "mb",
        "gb",
        "tb",
        "kb",
        "lakh",
        "crore",
        "mph",
        "kph",
        "grand",
        "score",
        "gross",
    }
)
_ALLOWED_FOLLOW = frozenset(
    {
        "in",
        "of",
        "during",
        "for",
        "at",
        "on",
        "across",
        "over",
        "within",
        "through",
        "throughout",
        "between",
        "around",
        "to",
        "from",
        "than",
        "and",
        "or",
        "but",
        "while",
        "with",
        "then",
        "before",
        "after",
        "compared",
        "versus",
        "vs",
        "as",
        "when",
        "since",
        "by",
        "per",
        "the",
        "this",
        "that",
        "these",
        "those",
        "which",
        "so",
        "because",
        "though",
        "although",
        "yet",
        "until",
        "till",
        "last",
        "prior",
        "earlier",
        "period",
        "periods",
        "window",
        "windows",
        "total",
        "overall",
        "altogether",
        "combined",
        "alone",
        "more",
        "less",
        "fewer",
        "up",
        "down",
        "higher",
        "lower",
        "respectively",
        "both",
        "today",
        "tonight",
        "tomorrow",
        "yesterday",
        "overnight",
        "daily",
        "weekly",
        "monthly",
        "nightly",
        "hourly",
        "line",
        "lines",
        "page",
        "pages",
    }
)
_HOURS_NOUNS = frozenset(
    {"hour", "hours", "hr", "hrs", "h", "screen", "time", "busy", "calendar"}
)
_COUNT_NOUNS = frozenset(
    {
        "push",
        "pushes",
        "pull",
        "request",
        "requests",
        "pr",
        "prs",
        "item",
        "items",
        "feed",
        "feeds",
        "github",
        "hf",
        "hn",
        "entry",
        "entries",
        "post",
        "posts",
        "story",
        "stories",
        "paper",
        "papers",
        "repo",
        "repos",
        "article",
        "articles",
        "link",
        "links",
        "source",
        "sources",
        "piece",
        "pieces",
        "cancel",
        "cancels",
        "cancellation",
        "cancellations",
        "change",
        "changes",
        "time",
        "times",
        "task",
        "tasks",
    }
)


def _fact_number_word_hit(
    fact_statements: Collection[str], value: Decimal, word: str
) -> bool:
    """Whether a cited statement holds ``value`` directly before ``word``."""
    for statement in fact_statements:
        slow = normalize_text(statement).casefold()
        for match in re.finditer(
            r"(?<!\w)\d+(?:\.\d+)?(?=\s+" + re.escape(word) + r"(?!\w))", slow
        ):
            if Decimal(match.group(0)) == value:
                return True
    return False


def _unit_violations(
    lower: str,
    tokens: Collection[NumberToken],
    cited: Collection[tuple[str, float]],
    fact_statements: Collection[str] = (),
) -> bool:
    if not cited:
        return False
    cited_list = list(cited)
    known = [
        (metric_id, value)
        for metric_id, value in cited_list
        if metric_label_binding(metric_id) is not None
    ]
    classes = {metric_unit_class(metric) for metric, _v in known}
    nouns: set[str] = set()
    for metric_id, _v in known:
        binding = metric_label_binding(metric_id)
        if binding is not None:
            for label in binding.labels:
                nouns.update(_DIRECTION_TOKEN_RE.findall(label.casefold()))
    if "hours" in classes:
        nouns |= _HOURS_NOUNS
    if "count" in classes:
        nouns |= _COUNT_NOUNS
    for token in tokens:
        after = lower[token.end :] if token.end < len(lower) else ""
        words = _tokens(after)
        first = words[0] if words else None
        second = words[1] if len(words) > 1 else None
        if first is not None and _fact_number_word_hit(
            fact_statements, token.value, first
        ):
            continue
        if token.raw.endswith("%"):
            backers = [v for m, v in known if m == "calendar.busy_hours"]
            if not backers or not any(v == float(token.value) for v in backers):
                return True
            continue
        if first in ("percent", "pct") or (first == "per" and second == "cent"):
            return True
        if first is None:
            continue
        if first in _MAGNITUDE_UNITS:
            return True
        if not known:
            continue
        if first in _ALLOWED_FOLLOW:
            continue
        if first in nouns or second in nouns:
            continue
        if first.endswith(("ing", "ed", "ly")):
            continue
        if first in _NUMBER_WORDS_DET:
            continue
        rest = after.lstrip()
        if rest[:1].isdigit():
            continue
        if rest[:1] in ("-", ":", "/", "⁄"):
            tail = rest[1:].lstrip()
            if tail[:1].isdigit() or (tail[:1] == "." and tail[1:2].isdigit()):
                continue
        if rest[:1] == "." and rest[1:2].isdigit():
            continue
        return True
    return False


def snapshot_label_forms(
    snapshot_ids: Collection[str],
    cited_ids: Collection[str],
) -> list[tuple[frozenset[str], bool]]:
    """Label forms per snapshot metric plus whether the claim cites it."""
    out: list[tuple[frozenset[str], bool]] = []
    cited = set(cited_ids)
    for metric_id in snapshot_ids:
        binding = metric_label_binding(metric_id)
        if binding is None:
            continue
        forms: set[str] = set()
        for label in binding.labels:
            forms.update(form.casefold() for form in label_forms(label))
        out.append((frozenset(forms), metric_id in cited))
    return out


def _conflicting_label_hit(
    norm: str,
    lower: str,
    snapshot_forms: Collection[tuple[frozenset[str], bool]],
) -> bool:
    # The pick after `this hour goes` names the commitment, never another
    # metric: neither working copy reads it, with or without `to`.
    lower = _blank_goes_to_pick(lower)
    cited_forms: set[str] = set()
    for forms, is_cited in snapshot_forms:
        if is_cited:
            cited_forms.update(forms)
    # The cited metrics' own labels are read first: a cited label holding
    # another metric's label as one of its words (`Video Calls` holding
    # `Video`) must not read as naming the other metric. A hit counts only
    # when no longer cited-label mention covers it, so a shorter label
    # named on its own as well, outside the cited label, still fires.
    spaced = _blank_goes_to_pick(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", norm).casefold())
    cited_spans = [span for form in cited_forms for span in _token_spans(lower, form)]
    cited_spans_spaced = [
        span for form in cited_forms for span in _token_spans(spaced, form)
    ]

    def _covered(hit: tuple[int, int], spans: Collection[tuple[int, int]]) -> bool:
        return any(
            start <= hit[0] and hit[1] <= end and (end - start) > (hit[1] - hit[0])
            for start, end in spans
        )

    for forms, is_cited in snapshot_forms:
        if is_cited:
            continue
        if forms <= cited_forms or forms & cited_forms:
            continue
        for form in forms:
            if any(
                not _covered(span, cited_spans) for span in _token_spans(lower, form)
            ) or (
                spaced != lower
                and any(
                    not _covered(span, cited_spans_spaced)
                    for span in _token_spans(spaced, form)
                )
            ):
                return True
    return False


def _language_code(
    text: str,
    folded: str,
    cited_label_tokens: Collection[str],
    verbatim_tokens: Collection[str],
    known_ids: Collection[str] = (),
    known_names: Collection[str] = (),
) -> str | None:
    exempt = set(cited_label_tokens) | set(verbatim_tokens)
    # Arm (c) runs on the NFKC copy, before confusable mapping (D12).
    # An underscore reads as a space once cited ids and names are blanked.
    cleaned = _space_underscores_after_blank(
        unicodedata.normalize("NFKC", text).casefold(), known_ids, known_names
    )
    for token in exempt:
        cleaned = _remove_whole(cleaned, token)
    for char in cleaned:
        if char.isalpha() and ord(char) > 127:
            return "L1_CLAIM_LANGUAGE"
    exempt_folded = {_fold(token) for token in exempt}
    folded_work = _space_underscores_after_blank(folded, known_ids, known_names)
    for token in _tokens(folded_work):
        if (
            token in _FOLD_FOREIGN
            and token not in exempt
            and token not in exempt_folded
        ):
            return "L1_CLAIM_LANGUAGE"
    english = {stop for stop in ENGLISH_STOPWORDS if _contains_token(folded_work, stop)}
    for stops in FOREIGN_STOPWORDS.values():
        folded_stops = {_fold(stop) for stop in stops}
        hits = {stop for stop in folded_stops if _contains_token(folded_work, stop)}
        hits -= exempt
        if len(hits) >= 3 and len(hits) > len(english):
            return "L1_CLAIM_LANGUAGE"
    return None


_FOLD_FOREIGN: frozenset[str] = frozenset(
    {
        _fold(t)
        for t in FOREIGN_DIRECTION_TOKENS
        | FOREIGN_NUMBER_TOKENS
        | FOREIGN_ADVICE_TOKENS
    }
)


_CLAUSE_OPENERS = frozenset(
    {
        "now",
        "today",
        "tonight",
        "tomorrow",
        "next",
        "then",
        "just",
        "so",
        "first",
        "finally",
        "simply",
        "instead",
        "also",
        "and",
        "soon",
        "later",
        "therefore",
        "thus",
        "hence",
        "again",
    }
)
_QUESTION_OPENERS = frozenset(
    {
        "would",
        "could",
        "can",
        "shall",
        "should",
        "might",
        "may",
        "must",
        "will",
        "do",
        "does",
        "did",
        "is",
        "are",
        "how",
        "why",
    }
)
# Claim-path advice phrases. ``ADVICE_PHRASES`` above stays exactly as it
# is: Ticket 11's prompt test requires each of its entries in its prompt.
_CLAIM_ADVICE_PHRASES = (
    "would help",
    "would be good",
    "would be a good",
    "would be wise",
    "would be smart",
    "would pay off",
    "good idea",
    "great idea",
    "next move",
    "best move",
    "right move",
    "the move",
    "best bet",
    "would you",
    "could you",
    "will you",
    "can you",
    "you are due",
    "you're due",
    "you are ready",
    "you're ready",
    "calls for",
    "this hour needs",
    "this hour is for",
    "the fix is to",
    "the answer is to",
    "the plan is to",
    "the goal is to",
    "the aim is to",
    "the idea is to",
    "the way forward",
    "shall",
    "overdue",
    "is due",
    "is in order",
    "is needed",
    "is required",
    "is called for",
)
#: Claim path's whole advice phrase list: the claim-only phrases plus the
#: ticket-10b claim phrases (``ADVICE_PHRASES`` above stays exactly as it
#: is for Ticket 11's prompt test). Exported for callers replicating the
#: gate's list alongside ``gate.ADVICE_WORDS``.
CLAIM_ADVICE_PHRASES = CLAIM_ONLY_PHRASES + _CLAIM_ADVICE_PHRASES
# Direction words that read as comparatives (an instruction to change the
# value) rather than a plain statement of direction in second position.
_COMPARATIVE_OK = frozenset(
    {
        "up",
        "down",
        "more",
        "less",
        "fewer",
        "higher",
        "lower",
        "greater",
        "bigger",
        "larger",
        "smaller",
        "better",
        "worse",
        "longer",
        "shorter",
        "heavier",
        "lighter",
        "stronger",
        "weaker",
        "quieter",
        "busier",
        "slower",
    }
)
_DIR_WORDS = UP_WORDS | DOWN_WORDS
_FITS_WORDS = frozenset({"fits", "fit", "suits", "suit", "matches"})
_DET_POSS_NUM = _DETERMINERS | _NUMBER_WORDS_DET
_OBJECT_WORDS = _DET_POSS_NUM | {"it", "them"}
_JOIN_WORDS = frozenset({"and", "but", "or"})
_CLAUSE_DASH_RE = re.compile(r"(?<!\w)-(?!\w)")
_CLAUSE_BRACKET_RE = re.compile(r"[\[\](){}]")
_GLUED_DASH_RE = re.compile(r"(?<=\S)[\u2013\u2014]+(?=\S)")


def _strip_clause_openers(words: list[str]) -> list[str]:
    index = 0
    while index < len(words) and words[index] in _CLAUSE_OPENERS:
        index += 1
    return words[index:]


def _imperative_clause_fires(
    words: list[str], cited_label_tokens: Collection[str]
) -> bool:
    """Strong/ambiguous verb test for one clause, openers already stripped."""
    if not words:
        return False
    first = words[0]
    if first in cited_label_tokens:
        return False
    if first in STRONG_VERBS:
        rest = words[1:]
        if not rest:
            return True
        second = rest[0]
        if second == "of":
            return False
        if second in _NOUN_USE_WORDS:
            return False
        if second in _FITS_WORDS:
            return False
        if second in _DIR_WORDS and second not in _COMPARATIVE_OK:
            return False
        if any(word in ("was", "were", "has", "had") for word in words[1:4]):
            return False
        if second in ("is", "are"):
            return False
        if (
            len(words) > 2
            and words[2] in ("is", "are")
            and second not in ("what", "that", "which", "who", "whatever")
        ):
            return False
        if any(
            word in _DIR_WORDS and word not in _COMPARATIVE_OK for word in words[1:4]
        ):
            return False
        return not (
            len(words) > 2
            and words[2].endswith("ed")
            and second not in _DET_POSS_NUM
            and not second.isdigit()
        )
    if first in AMBIGUOUS_VERBS:
        rest = words[1:]
        if not rest:
            return True
        second = rest[0]
        if second in _DETERMINERS or second in _NUMBER_WORDS_DET:
            return True
        if second.isdigit():
            return True
        return first == "commit" and second == "to"
    return False


def _resumed_imperative_fires(
    words: list[str], cited_label_tokens: Collection[str]
) -> bool:
    """``so``/``then`` directly before a strong verb counts as a clause start."""
    for index in range(1, len(words)):
        if (
            words[index - 1] in ("so", "then")
            and words[index] in STRONG_VERBS
            and _imperative_clause_fires(words[index:], cited_label_tokens)
        ):
            return True
    return False


def _joined_imperative_fires(
    words: list[str], cited_label_tokens: Collection[str]
) -> bool:
    """Strong verb joined by ``and``/``but``/``or`` with an object word."""
    for index, word in enumerate(words):
        if word not in _JOIN_WORDS:
            continue
        tail = words[index + 1 :]
        if (
            len(tail) >= 2
            and tail[0] in STRONG_VERBS
            and (tail[1] in _OBJECT_WORDS or tail[1].isdigit())
            and _imperative_clause_fires(list(tail), cited_label_tokens)
        ):
            return True
    return False


def _bracketed_imperative_fires(
    words: list[str], cited_label_tokens: Collection[str]
) -> bool:
    """Strong verb with an object word right after it (bracket/dash join).

    Brackets and spaced dashes join clauses only for this pass: an
    imperative inside brackets, or after a spaced dash, still fires when
    an object word (or digit) follows the verb, while a bare verb form
    after a bracketed noun stays quiet.
    """
    if not words:
        return False
    first = words[0]
    if first in cited_label_tokens:
        return False
    if first in STRONG_VERBS:
        if len(words) < 2:
            return False
        second = words[1]
        if second not in _OBJECT_WORDS and not second.isdigit():
            return False
        return _imperative_clause_fires(words, cited_label_tokens)
    if first in AMBIGUOUS_VERBS:
        return _imperative_clause_fires(words, cited_label_tokens)
    return False


def _starts_with_digit_ordinal(unit: str) -> bool:
    """Whether a clause-shaped string opens with a digit ordinal.

    A sentence or clause starting with one is never an imperative: the
    ordinal is a noun modifier, not a dropped word before the verb.
    """
    return re.match(r"\s*\d+(?:st|nd|rd|th)(?!\w)", unit) is not None


def _advice_hit(
    norm: str,
    lower: str,
    cited_label_tokens: Collection[str],
    raw_text: str = "",
    known_ids: Collection[str] = (),
    known_names: Collection[str] = (),
) -> bool:
    # An underscore reads as a space once cited ids and names are blanked,
    # so ``Launch_the`` still opens an imperative clause.
    norm = _space_underscores_after_blank(norm, known_ids, known_names)
    lower = _space_underscores_after_blank(lower, known_ids, known_names)
    raw_text = _space_underscores_after_blank(raw_text or norm, known_ids, known_names)
    for phrase in CLAIM_ADVICE_PHRASES:
        if _contains_token(lower, phrase):
            return True
    if "?" in norm:
        return True
    split_text = normalize_text(_GLUED_DASH_RE.sub(",", raw_text or norm))
    sentences = re.split(r"[.!?;:]+(?:\s+|$)", split_text)
    for sentence in sentences:
        words = _tokens(sentence.casefold())
        alpha = [w for w in words if w[:1].isalpha()]
        if not alpha:
            continue
        if alpha[0] in _QUESTION_OPENERS:
            return True
        for comma_clause in sentence.split(","):
            # First pass splits on commas only: a bracketed noun can no
            # longer promote the word after it to a clause start. A
            # clause opening with a digit ordinal is never an imperative.
            ordinal_start = _starts_with_digit_ordinal(comma_clause)
            clause = _strip_clause_openers(
                [w for w in _tokens(comma_clause.casefold()) if w[:1].isalpha()]
            )
            if clause:
                if clause[:2] == ["time", "to"]:
                    return True
                if not ordinal_start and (
                    _imperative_clause_fires(clause, cited_label_tokens)
                    or _resumed_imperative_fires(clause, cited_label_tokens)
                    or _joined_imperative_fires(clause, cited_label_tokens)
                ):
                    return True
            for bracket_part in _CLAUSE_BRACKET_RE.split(comma_clause):
                for dash_part in _CLAUSE_DASH_RE.split(bracket_part):
                    sub = _strip_clause_openers(
                        [w for w in _tokens(dash_part.casefold()) if w[:1].isalpha()]
                    )
                    if (
                        sub
                        and not _starts_with_digit_ordinal(dash_part)
                        and _bracketed_imperative_fires(sub, cited_label_tokens)
                    ):
                        return True
    return False


def _damerau_le1(first: str, second: str) -> bool:
    if first == second:
        return True
    len_a, len_b = len(first), len(second)
    if abs(len_a - len_b) > 1:
        return False
    if len_a == len_b:
        diffs = [i for i, (x, y) in enumerate(zip(first, second)) if x != y]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2:
            i, j = diffs
            return j == i + 1 and first[i] == second[j] and first[j] == second[i]
        return False
    short, long = (first, second) if len_a < len_b else (second, first)
    return any(short == long[:i] + long[i + 1 :] for i in range(len(long)))


_LEET_SINGLE = {
    "0": "o",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
    "!": "i",
}
_MASK_CHARS = frozenset({"*", "_", "#", "?", ".", "-"})


def _leet_hit(ctoken: str, ttoken: str) -> bool:
    if len(ctoken) != len(ttoken):
        return False
    for c, t in zip(ctoken, ttoken):
        if c == t:
            continue
        if c == "1" and t in ("i", "l"):
            continue
        if c in _LEET_SINGLE and _LEET_SINGLE[c] == t:
            continue
        return False
    return True


def _fold_li(token: str) -> str:
    """Read ``l`` and ``i`` as one letter (they look the same in sans fonts)."""
    return token.replace("l", "i")


def _rotation_hit(first: str, second: str) -> bool:
    """Same-length rotation of a 6-or-more-character term (halves swapped)."""
    if len(first) != len(second) or len(first) < 6:
        return False
    return any(
        first[index:] + first[:index] == second for index in range(1, len(first))
    )


def _squashed_contains(normalized: str, term: str, vocab: Collection[str] = ()) -> bool:
    """Shared-arm whole-term match skipping every non-alphanumeric character.

    A hit that only joins two or more whole claim-vocabulary words does
    not count (see ``squashed_span_exempt``); every other hit does.
    """
    squashed: list[str] = []
    index_map: list[int] = []
    for pos, char in enumerate(normalized):
        if not char.isalnum():
            continue
        squashed.append(char)
        index_map.append(pos)
    if not squashed:
        return False
    squashed_term = "".join(c for c in term if c.isalnum())
    if len(squashed_term) < 5:
        return False
    joined = "".join(squashed)
    start = 0
    while True:
        index = joined.find(squashed_term, start)
        if index < 0:
            return False
        first = index_map[index]
        last = index_map[index + len(squashed_term) - 1]
        before = normalized[first - 1] if first > 0 else ""
        after = normalized[last + 1] if last + 1 < len(normalized) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            if vocab and squashed_span_exempt(normalized, first, last, vocab):
                start = index + 1
                continue
            return True
        start = index + 1


def claim_vocab_words(label_words: Collection[str] = ()) -> frozenset[str]:
    """Every word the card itself may join around a private term.

    The gate's closed word lists (period words, up/down/same/steady
    words, the comparison vocabulary, the English stopwords), the unit
    words ``hour`` and ``hours``, plus every label form of the snapshot's
    metrics supplied by the caller. Number tokens come from the text
    being checked (see ``number_word_tokens``).
    """
    vocab = (
        set(PERIOD_WORDS)
        | set(UP_WORDS)
        | set(DOWN_WORDS)
        | set(SAME_WORDS)
        | set(STEADY_WORDS)
        | set(COMPARISON_VOCABULARY)
        | set(ENGLISH_STOPWORDS)
        | {"hour", "hours"}
    )
    for label in label_words:
        for form in label_forms(label):
            vocab.update(re.findall(r"[a-z0-9]+", form.casefold()))
    return frozenset(vocab)


_LEET_READINGS = {
    "0": "o",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
}


def number_word_tokens(lower: str) -> set[str]:
    """Pure-digit runs of ``lower``, and their readings.

    A number token counts as vocabulary in every form a fuzzy arm
    consumes it in, so each digit run also contributes its
    digit-for-letter readings (``0`` reads as ``o``, ``5`` as ``s``).
    Tokens that mix letters and digits are spellings, not numbers, and
    stay outside the vocabulary, so the digit-for-letter arm keeps
    catching them.
    """
    tokens = set(re.findall(r"[0-9]+", lower))
    readings: set[str] = set()
    for token in tokens:
        if len(token) > 8:
            continue
        variants = {""}
        for char in token:
            if char in _LEET_READINGS:
                reading = _LEET_READINGS[char]
                variants = {v + c for v in variants for c in (char, reading)}
            else:
                variants = {v + char for v in variants}
        readings.update(variants)
    return tokens | readings


_SQUASH_WORD_RE = re.compile(r"\w+")


def squashed_span_exempt(
    normalized: str, first: int, last: int, vocab: Collection[str]
) -> bool:
    """Whether a squashed hit from ``first`` to ``last`` only joins words.

    True when the span covers two or more whole words end to end and
    every word it covers belongs to ``vocab``. A match inside one word,
    or across word fragments, is never exempt; neither is a
    letter-by-letter spelling (every covered word a single character),
    whatever separators it uses.
    """
    words = [
        match
        for match in _SQUASH_WORD_RE.finditer(normalized)
        if match.start() >= first and match.end() <= last + 1
    ]
    if len(words) < 2:
        return False
    if words[0].start() != first or words[-1].end() != last + 1:
        return False
    tokens = [match.group() for match in words]
    if not all(token in vocab for token in tokens):
        return False
    return any(len(token) >= 2 for token in tokens)


def _pair_exempt(left: str, right: str, vocab: Collection[str]) -> bool:
    """Whether two neighbouring words are both claim vocabulary."""
    pieces = re.findall(r"[a-z0-9]+", left) + re.findall(r"[a-z0-9]+", right)
    return bool(pieces) and all(piece in vocab for piece in pieces)


def _ctoken_exempt(ctoken: str, vocab: Collection[str]) -> bool:
    """Whether one consumed claim token is all claim vocabulary."""
    pieces = re.findall(r"[a-z0-9]+", ctoken)
    return bool(pieces) and all(piece in vocab for piece in pieces)


def _span_exempt(lower: str, start: int, end: int, vocab: Collection[str]) -> bool:
    """Whether ``lower[start:end]`` covers whole vocabulary words only."""
    words = [
        match
        for match in _SQUASH_WORD_RE.finditer(lower)
        if match.start() >= start and match.end() <= end
    ]
    if not words:
        return False
    if words[0].start() != start or words[-1].end() != end:
        return False
    return all(match.group() in vocab for match in words)


def _term_word_gate(norm_term: str) -> tuple[bool, tuple[str, ...]]:
    """Split one private term into whole-only or per-word matching.

    Returns ``(whole_only, words)``: a hyphen- or dot-joined name matches
    whole only, never on its parts; a spaced term matches on a word alone
    only when that word has at least 4 characters and is all letters, and
    only the whole term fires when none qualifies; a one-word term keeps
    its word at any length.
    """
    if "-" in norm_term or "." in norm_term:
        return True, ()
    pieces = norm_term.split(" ")
    if len(pieces) <= 1:
        return False, (norm_term,) if norm_term else ()
    qualified = tuple(w for w in pieces if len(w) >= 4 and w.isalpha())
    if not qualified:
        return True, ()
    return False, qualified


def _private_claim_hit(
    lower: str, private_terms: Collection[str], vocab: Collection[str] = ()
) -> bool:
    _vocab: frozenset[str] = frozenset(vocab)
    terms = [t for t in private_terms if t]
    if not terms:
        return False
    claim_tokens = _tokens(lower)
    raw_pool: list[str] = []
    for raw in lower.split():
        for form in (raw.rstrip(".?"), raw):
            if form and form not in claim_tokens and form not in raw_pool:
                raw_pool.append(form)
    pool = claim_tokens + raw_pool
    token_pairs = list(itertools.pairwise(claim_tokens))
    skipped: frozenset[str] = (
        frozenset(token for token in pool if _ctoken_exempt(token, _vocab))
        if _vocab
        else frozenset()
    )
    for term in terms:
        norm_term = normalize_text(term).casefold()
        if not norm_term:
            continue
        term_tokens = _DIRECTION_TOKEN_RE.findall(norm_term)
        if not term_tokens:
            continue
        whole_only, words = _term_word_gate(norm_term)
        if not whole_only:
            for ctoken in pool:
                if ctoken in skipped:
                    continue
                for word in words:
                    if _leet_hit(ctoken, word):
                        return True
            for ctoken in pool:
                if ctoken in skipped:
                    continue
                for word in words:
                    if len(word) >= 4 and _damerau_le1(ctoken, word):
                        return True
            for ctoken in pool:
                if ctoken in skipped:
                    continue
                for word in words:
                    if len(word) >= 3 and ctoken == word[::-1]:
                        return True
            for word in words:
                if len(word) < 5:
                    continue
                needle = word[::-1]
                if not _contains_token(lower, needle):
                    continue
                if _vocab and all(
                    _span_exempt(lower, start, end, _vocab)
                    for start, end in _token_spans(lower, needle)
                ):
                    continue
                return True
        if "-" not in norm_term and "." not in norm_term:
            target = re.sub(r"\s+", "", norm_term)
            if len(target) >= 6:
                folded_target = _fold_li(target)
                for ctoken in pool:
                    if ctoken in skipped:
                        continue
                    if len(ctoken) == len(target) and (
                        _fold_li(ctoken) == folded_target
                    ):
                        return True
                    if _rotation_hit(ctoken, target):
                        return True
                for left, right in token_pairs:
                    joined = left + right
                    if not joined:
                        continue
                    if _vocab and _pair_exempt(left, right, _vocab):
                        continue
                    if joined[0] == target[0] and _damerau_le1(joined, target):
                        return True
                    if _rotation_hit(joined, target):
                        return True
        if len(norm_term) > 3 and norm_term in lower:
            return True
        if _squashed_contains(lower, norm_term, _vocab):
            return True
        for raw in lower.split():
            stripped = raw.rstrip(".?")
            if not stripped:
                continue
            if not any(c in _MASK_CHARS for c in stripped):
                continue
            if sum(1 for c in stripped if c not in _MASK_CHARS) < 2:
                continue
            if stripped in skipped:
                continue
            for ttoken in term_tokens:
                pattern = "".join(
                    "." if c in _MASK_CHARS else re.escape(c) for c in stripped
                )
                if re.fullmatch(pattern, ttoken):
                    return True
    return False


_BAG_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "on",
        "in",
        "of",
        "to",
        "at",
        "by",
        "for",
        "and",
        "or",
    }
)


def _bag_match(content_token: str, claim_token: str) -> bool:
    """One literal content word read in one claim token (D10 bag rule)."""
    if claim_token == content_token:
        return True
    if len(content_token) >= 6 and _damerau_le1(claim_token, content_token):
        return True
    return (
        len(claim_token) >= 3
        and len(claim_token) * 2 >= len(content_token)
        and content_token.startswith(claim_token)
    )


def _raw_bag_hit(lower: str, forbidden: Collection[str]) -> bool:
    claim_tokens = _tokens(lower)
    for literal in forbidden:
        norm_lit = normalize_text(literal).casefold()
        content = [
            t
            for t in _DIRECTION_TOKEN_RE.findall(norm_lit)
            if len(t) >= 3 and t not in _BAG_STOPWORDS
        ]
        if len(content) < 2:
            continue
        limit = len(content) + 2
        matches: list[list[int]] = []
        for piece in content:
            hits = [
                index
                for index, token in enumerate(claim_tokens)
                if _bag_match(piece, token)
            ]
            if not hits:
                break
            matches.append(hits)
        else:
            for combo in itertools.product(*matches):
                span = [
                    index
                    for index in range(min(combo), max(combo) + 1)
                    if claim_tokens[index] not in _BAG_STOPWORDS
                ]
                if len(span) <= limit:
                    return True
    return False


_ONE_DETERMINERS = frozenset(
    {"the", "this", "that", "each", "any", "no", "every", "which", "last"}
)
_ONE_FOLLOW = frozenset(
    {
        "in",
        "during",
        "for",
        "at",
        "and",
        "or",
        "but",
        "across",
        "over",
        "than",
        "to",
        "from",
    }
)
_BACKWARD_SEP = (
    r"(?:was|were|at|of|with|had|saw|showed|reached|hit|totaled|totalled"
    r"|stood\s+at|came\s+to|[:=])"
)
_COMMA_SEP = ("was", "were", "at", "reached", "totaled", "totalled")
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<!\w)(?:and|but|while|whereas|then|to|from|than|versus|vs"
    r"|after|before|between|across|over)(?!\w)"
)
_STATED_OF_RE = re.compile(
    r"(?<!\w)(?:drop|fall|rise|gain|loss|gap|difference|change|decline"
    r"|increase|decrease|delta|swing|shift|jump)\s+of\b"
)
_STATED_BY_RE = re.compile(r"(?<!\w)(?:by|net)\b")
_FRACTION_HINT_RE = re.compile(
    r"\d\s*[⁄/]\s*\d|(?<!\w)(?:half|halves|quarter|quarters|point)(?!\w)"
)


def _bare_one_spans(work: str) -> list[tuple[int, int]]:
    """Spans of ``one`` used as a count (D11 rule 3 positions only)."""
    out: list[tuple[int, int]] = []
    for match in re.finditer(r"(?<!\w)one(?!\w)", work):
        start, end = match.start(), match.end()
        if start > 0 and work[start - 1] == "-":
            continue
        if end < len(work) and work[end] == "-":
            continue
        prev_word = re.search(r"[A-Za-z]+$", work[:start].rstrip())
        if prev_word is not None and prev_word.group(0) in _ONE_DETERMINERS:
            continue
        rest = work[end:].lstrip()
        if rest == "":
            out.append((start, end))
            continue
        word = re.match(r"[A-Za-z]+", rest)
        follows = word is not None and word.group(0) in _ONE_FOLLOW
        punctuated = not (rest[0].isalnum() or rest[0] == "_")
        if follows or punctuated:
            out.append((start, end))
    return out


def _value_signed(work: str, start: int) -> bool:
    """Whether the value at ``start`` carries a minus sign (D8 sign rule)."""
    if start < len(work) and work[start] == "-":
        return True
    return (
        start > 0
        and work[start - 1] == "-"
        and (start < 2 or not work[start - 2].isdigit())
    )


def _value_period_hit(
    lower: str,
    tokens: Collection[NumberToken],
    cited: Collection[tuple[str, float]],
) -> bool:
    from framework.briefing.numbers import token_backed_by

    cited_list = list(cited)
    if not eligible_comparison(cited_list):
        return False
    work = re.sub(r"[\(\)\[\]\"'\u2018\u2019\u201c\u201d]", " ", lower)
    # A compound naming a period reads as that period here, hyphenated
    # or spaced alike. Same-length replacement keeps every token offset
    # valid for the pair, comma and clause rules below.
    compounds = [(phrase, "prior") for phrase in _PRIOR_COMPOUNDS] + [
        (phrase, "earlier") for phrase in _EARLIER_COMPOUNDS
    ]
    for phrase, word in sorted(compounds, key=lambda item: len(item[0]), reverse=True):
        for variant in sorted(_compound_variants(phrase), key=len, reverse=True):
            work = re.sub(
                r"(?<!\w)" + re.escape(variant) + r"(?!\w)",
                lambda match, word=word: word + " " * (len(match.group(0)) - len(word)),
                work,
            )
    voids: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in _HYPHEN_COMPOUND_RE.finditer(work)
    ]
    for phrase in SPACED_PERIOD_COMPOUNDS + _NON_PERIOD_SENSES:
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", work):
            voids.append((match.start(), match.end()))
    for match in re.finditer(r"\bprior to(?=\s+(?:earlier|prior|last)\b)", work):
        voids.append((match.start(), match.end()))

    def in_void(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in voids)

    spans = [
        (m.group(0), m.start(), m.end()) for m in _DIRECTION_TOKEN_RE.finditer(work)
    ]
    skip: set[int] = set()
    for i, (word, _s, _e) in enumerate(spans):
        if word not in PERIOD_WORDS:
            continue
        for step in (-1, 1):
            k = i + step
            if 0 <= k < len(spans) and spans[k][0] in ("and", ","):
                nxt = k + step
                if 0 <= nxt < len(spans) and spans[nxt][0] in PERIOD_WORDS:
                    skip.add(i)
    label_tokens: set[str] = set()
    for metric_id, _v in cited_list:
        binding = metric_label_binding(metric_id)
        if binding is not None:
            for label in binding.labels:
                label_tokens.update(_DIRECTION_TOKEN_RE.findall(label.casefold()))
    period_of = {
        metric: binding.period
        for metric, _v in cited_list
        if (binding := metric_label_binding(metric)) is not None
    }
    cited_periods = {period for period in period_of.values() if period is not None}

    values: list[tuple[int, int, Decimal, int]] = []
    for token in tokens:
        if token.raw.isalpha() and int(token.value) > 12:
            continue
        values.append((token.start, token.end, token.value, token.places))
    seen_starts = {v[0] for v in values}
    for start, end in _bare_one_spans(work):
        if start not in seen_starts:
            values.append((start, end, Decimal(1), 0))
    values.sort()
    by_start = {v[0]: i for i, v in enumerate(values)}

    def backed(period: str, value: tuple[int, int, Decimal, int]) -> bool:
        refs = [ref for metric, ref in cited_list if period_of.get(metric) == period]
        return any(
            token_backed_by(
                ref,
                value[3],
                abs(value[2]),
                signed=_value_signed(work, value[0]),
                section_type="working",
            )
            for ref in refs
        )

    def positional_skip(value_end: int) -> bool:
        """A value run on into ``and``/comma plus another value is a list."""
        match = re.match(r"[ ]*(?:[A-Za-z]+[ ]+)?(?:and\b|,)[ ]*", work[value_end:])
        return match is not None and value_end + match.end() in by_start

    used: set[int] = set()
    middle = label_tokens | _HOUR_WORDS
    for vi, value in enumerate(values):
        if in_void(value[0], value[1]):
            continue
        k = next(
            (i for i, (_w, s, _e) in enumerate(spans) if s >= value[1]), len(spans)
        )
        kk = k
        if kk < len(spans) and spans[kk][0] in middle:
            kk += 1
        prep = kk < len(spans) and spans[kk][0] in ("in", "during", "for")
        if prep:
            kk += 1
        if kk < len(spans) and spans[kk][0] == "the":
            kk += 1
        if kk >= len(spans) or spans[kk][0] not in PERIOD_WORDS:
            continue
        if not prep and not (
            kk + 1 < len(spans) and spans[kk + 1][0] in ("period", "window")
        ):
            continue
        if re.search(r"[,;:]", work[value[1] : spans[kk][2]]):
            continue
        if kk in skip or in_void(spans[kk][1], spans[kk][2]):
            continue
        if spans[kk][0] not in cited_periods:
            continue
        used.add(vi)
        if not backed(spans[kk][0], value):
            return True

    for vi, value in enumerate(values):
        if vi in used or in_void(value[0], value[1]):
            continue
        found: str | None = None
        for pi in range(len(spans) - 1, -1, -1):
            word, start, end = spans[pi]
            if end > value[0] or word not in PERIOD_WORDS:
                continue
            if pi in skip or in_void(start, end):
                continue
            gap = work[end : value[0]]
            if (
                re.fullmatch(
                    r"\s*(?:period\s+|window\s+)?(?:" + _BACKWARD_SEP + r")?\s*", gap
                )
                and gap.strip()
            ):
                found = word
                break
        if found is None or found not in cited_periods:
            continue
        if positional_skip(value[1]):
            continue
        used.add(vi)
        if not backed(found, value):
            return True

    for vi, value in enumerate(values):
        if vi in used or in_void(value[0], value[1]):
            continue
        si = next(
            (
                i
                for i in range(len(spans) - 1, -1, -1)
                if spans[i][2] <= value[0] and spans[i][1] < value[0]
            ),
            -1,
        )
        if si < 0 or spans[si][0] not in _COMMA_SEP:
            continue
        if not re.fullmatch(r"\s*", work[spans[si][2] : value[0]]):
            continue
        pi = next(
            (
                i
                for i in range(si - 1, -1, -1)
                if spans[i][0] in PERIOD_WORDS and spans[i][2] <= spans[si][1]
            ),
            -1,
        )
        if pi < 0 or pi in skip or in_void(spans[pi][1], spans[pi][2]):
            continue
        qi = pi + 1 if pi + 1 < si and spans[pi + 1][0] in ("period", "window") else pi
        between = spans[qi + 1 : si]
        if len(between) > 4:
            continue
        if any(w in PERIOD_WORDS and not in_void(s, e) for w, s, e in between):
            continue
        anchor = spans[qi][2]
        edge = between[0][1] if between else spans[si][1]
        if "," not in work[anchor:edge]:
            continue
        if spans[pi][0] not in cited_periods:
            continue
        if positional_skip(value[1]):
            continue
        used.add(vi)
        if not backed(spans[pi][0], value):
            return True

    seps: list[tuple[int, int]] = []
    for match in re.finditer(r",|;|:", work):
        if (
            match.start() > 0
            and work[match.start() - 1].isdigit()
            and match.end() < len(work)
            and work[match.end()].isdigit()
        ):
            continue
        seps.append((match.start(), match.end()))
    for match in _CLAUSE_SPLIT_RE.finditer(work):
        seps.append((match.start(), match.end()))
    seps.sort()
    clauses: list[tuple[int, int]] = []
    pos = 0
    for start, end in seps:
        clauses.append((pos, start))
        pos = end
    clauses.append((pos, len(work)))
    clause_periods: list[list[tuple[str, int]]] = []
    clause_values: list[list[int]] = []
    for start, end in clauses:
        clause_periods.append(
            [
                (w, i)
                for i, (w, s, e) in enumerate(spans)
                if s >= start and e <= end and w in PERIOD_WORDS and not in_void(s, e)
            ]
        )
        clause_values.append(
            [vi for vi, v in enumerate(values) if v[0] >= start and v[1] <= end]
        )
    named = 0
    for index, ((start, end), periods, owned) in enumerate(
        zip(clauses, clause_periods, clause_values)
    ):
        named += len(periods)
        if len(periods) != 1 or len(owned) != 1:
            continue
        if _FRACTION_HINT_RE.search(work[start:end]):
            continue
        period, pi = periods[0]
        if period not in cited_periods:
            continue
        if pi in skip:
            continue
        if named >= 2 and index + 1 < len(clauses):
            nxt_periods = clause_periods[index + 1]
            nxt_values = clause_values[index + 1]
            if nxt_values and not nxt_periods:
                continue
        if not backed(period, values[owned[0]]):
            return True

    diffs: set[Decimal] = set()
    decimals = [Decimal(str(ref)) for _, ref in cited_list]
    for ai, first in enumerate(decimals):
        for bi, second in enumerate(decimals):
            if ai != bi:
                diffs.add(abs(first - second))
    for pattern in (_STATED_BY_RE, _STATED_OF_RE):
        for match in pattern.finditer(work):
            at = match.end()
            while at < len(work) and work[at] == " ":
                at += 1
            if at not in by_start:
                continue
            value = values[by_start[at]]
            if not any(
                token_backed_by(
                    float(diff),
                    value[3],
                    abs(value[2]),
                    signed=_value_signed(work, value[0]),
                    section_type="working",
                )
                for diff in diffs
            ):
                return True
    return False


_SPELLED_LETTER_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z](?:[ .\-_/,\*+&]+[A-Za-z]){2,}(?![A-Za-z0-9])"
)
_PHONETIC_WORDS = frozenset(
    {
        "alfa",
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
        "romeo",
        "sierra",
        "tango",
        "uniform",
        "victor",
        "whiskey",
        "xray",
        "yankee",
        "zulu",
    }
)
_LINK_RE = re.compile(r"(?i)(?:https?://|www\.)(?=[A-Za-z0-9])")


def _spelled_out_hit(norm: str, lower: str) -> bool:
    """Letters spelled out one by one, or NATO words standing in for them."""
    if _SPELLED_LETTER_RE.search(norm):
        return True
    run = 0
    for word in re.findall(r"[a-z]+", lower):
        if word in _PHONETIC_WORDS:
            run += 1
            if run >= 3:
                return True
        else:
            run = 0
    return False


def _squashed_holds_private(
    lower: str, private_terms: Collection[str], vocab: Collection[str] = ()
) -> bool:
    """Whether the claim's squashed text holds a private term outright."""
    for term in private_terms:
        if not term:
            continue
        norm_term = normalize_text(term).casefold()
        if not norm_term:
            continue
        if len(norm_term) <= 3 and _contains_token(lower, norm_term):
            return True
        if len(norm_term) > 3 and norm_term in lower:
            return True
        if _squashed_contains(lower, norm_term, vocab):
            return True
    return False


def _consecutive(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(haystack) < len(needle):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def _drop_fillers(words: list[str]) -> list[str]:
    return [
        word
        for word in words
        if word not in _DETERMINERS and word not in _NUMBER_WORDS_DET
    ]


# The pick named after `this hour goes`, with or without `to`
# (or toward/towards), in the same clause is the commitment the claim
# argues for, never its title nor another metric's label.
_GOES_TO_PICK_RE = re.compile(
    r"(?<!\w)(?:this hour goes(?: to| toward| towards)?|goes (?:toward|towards))(?!\w)"
)
_CLAUSE_STOP_RE = re.compile(r"[,;:.!?]")


def _blank_goes_to_pick(lower: str) -> str:
    """Copy of ``lower`` with each goes-to pick blanked to its clause end."""
    out = lower
    for match in _GOES_TO_PICK_RE.finditer(lower):
        stop = _CLAUSE_STOP_RE.search(lower, match.end())
        end = stop.start() if stop is not None else len(lower)
        out = out[: match.end()] + " " * (end - match.end()) + out[end:]
    return out


def _title_hit(
    lower: str,
    cited_fact_statements: Collection[str],
    titles: Collection[str],
) -> bool:
    """Whether the claim names a commitment's title or its object (D13).

    The whole title of 2 or more tokens, or its object (the tokens after
    the first, when the title has 3 or more), occurring as consecutive
    tokens in the claim fires, unless the same sequence occurs in a cited
    fact's statement. Determiners and spelled numbers dropped from both
    sides are compared the same way when at least 3 tokens remain.
    """
    claim_tokens = _tokens(_blank_goes_to_pick(lower))
    dropped_claim = _drop_fillers(claim_tokens)
    statements = list(cited_fact_statements)
    stmt_token_lists = [
        _tokens(normalize_text(statement).casefold()) for statement in statements
    ]
    dropped_stmts = [_drop_fillers(tokens) for tokens in stmt_token_lists]
    for raw_title in titles:
        title = normalize_text(raw_title).casefold()
        if not title:
            continue
        words = _tokens(title)
        variants: list[list[str]] = []
        if len(words) >= 2:
            variants.append(words)
        if len(words) >= 3:
            variants.append(words[1:])
        for variant in variants:
            if _consecutive(claim_tokens, variant) and not any(
                _consecutive(tokens, variant) for tokens in stmt_token_lists
            ):
                return True
            dropped = _drop_fillers(variant)
            if (
                len(dropped) >= 3
                and _consecutive(dropped_claim, dropped)
                and not any(_consecutive(tokens, dropped) for tokens in dropped_stmts)
            ):
                return True
    return False


def _word_tokens(lower: str) -> list[str]:
    """Word tokens of the normalised casefolded copy (D1/D2 matching)."""
    return re.findall(r"[a-z0-9]+", lower)


def since_last_accepted(lower: str) -> bool:
    """Whether ``lower`` carries a D1 accepted phrase as token sequence."""
    tokens = _word_tokens(lower)
    return any(
        tokens[start : start + len(phrase)] == list(phrase)
        for phrase in SINCE_LAST_PHRASES
        for start in range(len(tokens) - len(phrase) + 1)
    )


def since_last_containment_hit(lower: str) -> bool:
    """Whether a D2 containment pattern names a period in ``lower``."""
    tokens = _word_tokens(lower)
    for index, token in enumerate(tokens):
        if token not in _SINCE_LAST_PREPS:
            continue
        rest = tokens[index + 1 :]
        if (
            token in _SINCE_LAST_GENERIC_PREPS
            and rest[:1] in (["a"], ["the"])
            and rest[1:2] == ["period"]
        ):
            return True
        if rest[:1] == ["the"]:
            rest = rest[1:]
        if rest[:1] in (["earlier"], ["prior"], ["last"]):
            return True
    return False


def claim_text_codes(
    text: str,
    *,
    section_type: str,
    has_metric_refs: bool,
    cited_refs: Collection[tuple[str, float]] = (),
    cited_fact_statements: Collection[str] = (),
    has_backed_fifty: bool = False,
    snapshot_metric_ids: Collection[str] = (),
    known_names: Collection[str] = (),
    private_terms: Collection[str] = (),
    private_terms_available: bool = True,
    forbidden_raw_literals: Collection[str] = (),
    number_tokens: Collection[NumberToken] | None = None,
    cited_ids: Collection[str] = (),
    titles: Collection[str] = (),
) -> tuple[str, ...]:
    """Claim-only codes for one claim (never titles or actions)."""
    codes: list[str] = []
    norm = normalize_text(text)
    lower = norm.casefold()
    folded = _fold(norm)
    vocab = claim_vocab_words(
        [
            form
            for group, _cited in snapshot_label_forms(snapshot_metric_ids, ())
            for form in group
        ]
    ) | number_word_tokens(lower)
    spelled_out = _spelled_out_hit(norm, lower) and not _squashed_holds_private(
        lower, private_terms if private_terms_available else (), vocab
    )
    if (
        has_unsafe_text(text)
        or not any(char.isalnum() for char in text)
        or _LINK_RE.search(text) is not None
        or spelled_out
    ):
        codes.append("L1_UNSAFE_TEXT")
    cited = list(cited_refs)
    cited_ids = [metric for metric, _v in cited]
    cited_labels: set[str] = set()
    cited_label_tokens: set[str] = set()
    for metric_id in cited_ids:
        binding = metric_label_binding(metric_id)
        if binding is not None:
            for label in binding.labels:
                cited_labels.add(label.casefold())
                cited_label_tokens.update(_DIRECTION_TOKEN_RE.findall(label.casefold()))
    verbatim: set[str] = set()
    # Compared as written (NFKC only), before accent folding (D12).
    for statement in cited_fact_statements:
        verbatim.update(_tokens(unicodedata.normalize("NFKC", statement).casefold()))
    names = find_known_names(cited_fact_statements) | set(known_names)
    known_ids = set(cited_ids) | {metric for metric, _v in cited}
    lang = _language_code(text, folded, cited_label_tokens, verbatim, known_ids, names)
    if lang is not None:
        codes.append(lang)
    if _advice_hit(
        norm, lower, cited_label_tokens, text, known_ids, names
    ) or _title_hit(lower, cited_fact_statements, titles):
        codes.append("L1_ADVICE")
    quantities = find_unverifiable_quantities(
        text,
        has_metric_refs=has_metric_refs,
        has_backed_fifty=has_backed_fifty,
        in_since_last=section_type == "since_last",
        cites_hours_metric=any(
            metric_unit_class(metric) == "hours" for metric in cited_ids
        ),
        known_names=names,
        cited_labels=cited_labels,
        known_ids=known_ids,
        cited_label_tokens=cited_label_tokens,
        single_forms=None
        if has_metric_refs
        else {
            form
            for group, _cited in snapshot_label_forms(snapshot_metric_ids, ())
            for form in group
        },
    )
    if quantities:
        codes.append("L1B_UNVERIFIABLE_QUANTITY")
    if has_metric_refs:
        from framework.briefing.numbers import token_backed_by as _backed_by

        unbacked_one = False
        for start, _end in _bare_one_spans(lower):
            if not any(
                _backed_by(
                    ref,
                    0,
                    Decimal(1),
                    signed=_value_signed(lower, start),
                    section_type=section_type,
                )
                for _, ref in cited
            ):
                unbacked_one = True
        if unbacked_one:
            codes.append("L1B_NUMBER_WITHOUT_METRIC_REF")
    if has_negator(lower, known_ids, names):
        if has_metric_refs:
            zero_code = stated_zero_code(lower, cited, cited_labels)
            if zero_code is not None:
                codes.append(zero_code)
        else:
            words = set(_tokens(lower))
            if words & (UP_WORDS | DOWN_WORDS | SAME_WORDS) or counted_periods(lower):
                codes.append("L1B_NEGATED_CLAIM")
    if private_terms_available and _private_claim_hit(lower, private_terms, vocab):
        codes.append("L1_PRIVATE_TERM")
    if _raw_bag_hit(lower, forbidden_raw_literals):
        codes.append("L1_RAW_VALUE")
    if (
        section_type != "since_last"
        and number_tokens is not None
        and _value_period_hit(lower, number_tokens, cited)
    ):
        codes.append("L1B_VALUE_PERIOD_MISMATCH")
    if (
        section_type == "since_last"
        and has_metric_refs
        and since_last_containment_hit(lower)
    ):
        codes.append("L1B_SINCE_LAST_WORDING")
    if section_type != "since_last" and has_metric_refs and eligible_comparison(cited):
        qtokens = quantity_fired_tokens(
            text,
            has_metric_refs=has_metric_refs,
            has_backed_fifty=has_backed_fifty,
            in_since_last=False,
            cites_hours_metric=False,
            known_names=names,
            cited_labels=cited_labels,
            known_ids=known_ids,
            cited_label_tokens=cited_label_tokens,
        )
        residual = _strip_for_vocab(
            lower,
            cited_label_tokens=cited_label_tokens,
            negator=has_negator(lower, known_ids, names),
            quantity_tokens=qtokens,
        )
        if any(t not in COMPARISON_VOCABULARY for t in residual):
            codes.append("L1B_COMPARISON_WORD_UNKNOWN")
    if _unit_violations(
        lower, list(number_tokens or ()), cited, tuple(cited_fact_statements)
    ):
        codes.append("L1B_UNIT_MISMATCH")
    if has_metric_refs and all(
        metric_label_binding(metric) is not None for metric in cited_ids
    ):
        forms = snapshot_label_forms(snapshot_metric_ids, cited_ids)
        if _conflicting_label_hit(norm, lower, forms):
            codes.append("L1B_METRIC_LABEL_MISMATCH")
    return tuple(codes)


def _fact_universal_hit(
    lower: str,
    statements: Collection[str],
    snapshot_metric_ids: Collection[str],
) -> bool:
    """Whether a universal over a snapshot label fires on a fact-only claim."""
    labels: set[str] = set()
    for forms, _cited in snapshot_label_forms(snapshot_metric_ids, ()):
        for form in forms:
            labels.update(_DIRECTION_TOKEN_RE.findall(form))
    if not labels:
        return False
    words = [m.group(0) for m in re.finditer(r"[a-z]+", lower)]
    # Word counts where each sentence ends, so `both` can look for a
    # later `and` in its own sentence (a coordination, never a count).
    ends: list[int] = []
    count = 0
    for match in re.finditer(r"[a-z]+|[.!?]", lower):
        if match.group(0) in (".", "!", "?"):
            ends.append(count)
        else:
            count += 1
    ends.append(count)
    hit = False
    for i, word in enumerate(words):
        # `both` before one label, with no `and` after it in the same
        # sentence, implies a count of two.
        if word not in ("all", "every", "each", "both"):
            continue
        j = i + 1
        if j < len(words) and words[j] == "of":
            j += 1
        if j < len(words) and words[j] in ("the", "my", "your", "our"):
            j += 1
        if j >= len(words) or words[j] not in labels:
            continue
        if word == "both":
            bound = next(end for end in ends if end > i)
            if "and" in words[i + 1 : bound]:
                continue
        hit = True
        break
    if not hit:
        return False
    for statement in statements:
        slow = normalize_text(statement).casefold()
        if any(
            _contains_token(slow, word) for word in ("all", "every", "each", "both")
        ):
            return False
    return True


def fact_claim_codes(
    claim_text: str,
    fact_statements: Collection[str],
    *,
    snapshot_metric_ids: Collection[str] = (),
    known_ids: Collection[str] = (),
) -> tuple[str, ...]:
    """Fact-only claim checked against its cited statements (D14)."""
    codes: list[str] = []
    statements = list(fact_statements)
    names = find_known_names(statements)
    # An underscore reads as a space on the claim's working copies once the
    # cited ids and statement names are blanked, so ``well_rose`` still
    # states its direction word.
    norm = normalize_text(_space_underscores_after_blank(claim_text, known_ids, names))
    lower = norm.casefold()
    held_clean = drop_tied_to(
        _space_underscores_after_blank(
            without_count_held(claim_text), known_ids, names
        ).casefold()
    )
    for particle in _FACT_PARTICLES:
        held_clean = _remove_whole(held_clean, particle)
    held_clean = _remove_hyphen_particles(held_clean)
    claim_toks = set(_tokens(held_clean)) | hyphen_directions(held_clean)
    for token in _tokens(held_clean):
        if "-" in token:
            claim_toks.update(token.split("-"))
    cleaned_stmts: list[str] = []
    for statement in statements:
        low = without_count_held(statement).casefold()
        for particle in _FACT_PARTICLES:
            low = _remove_whole(low, particle)
        cleaned_stmts.append(drop_tied_to(_remove_hyphen_particles(low)))
    if has_negator(lower, known_ids, names):
        claim_periods = counted_periods(lower)
        forms = snapshot_label_forms(snapshot_metric_ids, ())
        named = {
            form
            for group, _cited in forms
            for form in group
            if _contains_token(lower, form)
        }
        if claim_toks & (UP_WORDS | DOWN_WORDS | SAME_WORDS) or claim_periods or named:
            codes.append("L1B_NEGATED_CLAIM")
    stmt_sides: set[str] = set()
    for low in cleaned_stmts:
        tokens = set(_tokens(low)) | hyphen_directions(low)
        for token in _tokens(low):
            if "-" in token:
                tokens.update(token.split("-"))
        side = direction_side(tokens, metric_claim=False)
        if side == "mixed":
            stmt_sides.update({"up", "down", "same"})
        elif side is not None:
            stmt_sides.add(side)
    claim_side = direction_side(claim_toks, metric_claim=False)
    claim_sides: set[str] = set()
    if claim_side == "mixed":
        claim_sides.update({"up", "down", "same"})
    elif claim_side is not None:
        claim_sides.add(claim_side)
    if claim_sides and not claim_sides <= stmt_sides:
        codes.append("L1B_DIRECTION_MISMATCH")
    if _fact_universal_hit(lower, statements, snapshot_metric_ids):
        codes.append("L1B_UNVERIFIABLE_QUANTITY")
    claim_periods = counted_periods(lower)
    if claim_periods:
        stmt_periods: set[str] = set()
        for low in cleaned_stmts:
            stmt_periods.update(counted_periods(low))
        if claim_periods - stmt_periods:
            codes.append("L1B_PERIOD_WORD_MISSING")
    if claim_side is not None:
        forms = snapshot_label_forms(snapshot_metric_ids, ())
        # The pick after `this hour goes` names the commitment, never
        # another metric: the label check does not read it either.
        pick_blanked = _blank_goes_to_pick(lower)
        mismatch = False
        for group, _cited in forms:
            if not any(_contains_token(pick_blanked, form) for form in group):
                continue
            # One label: evidenced when a cited statement holds any form
            # of it (`push` over `pushes`), a mismatch only when no cited
            # statement holds any form of a label the claim names.
            if not any(
                _contains_token(low, form) for low in cleaned_stmts for form in group
            ):
                mismatch = True
                break
        if mismatch:
            codes.append("L1B_METRIC_LABEL_MISMATCH")
    return tuple(codes)
