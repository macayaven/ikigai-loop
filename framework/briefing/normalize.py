"""Ticket 10b: one public text normalisation for every briefing text rule.

``normalize_text`` returns the checked copy only: it never mutates its
input and the gate never writes it back, so what is read stays the
original text. It preserves case (the numbers module masks month names
only when capitalised, and the Roman-numeral rule needs case), so every
comparison casefolds the result instead.
"""

from __future__ import annotations

import unicodedata

# Pinned cross-script confusables folded to Latin (D10). A lookalike
# list, not a transliteration: only these code points map.
CONFUSABLES: dict[str, str] = {
    # Cyrillic small letters and their capitals.
    "а": "a",
    "А": "A",
    "е": "e",
    "Е": "E",
    "о": "o",
    "О": "O",
    "р": "p",
    "Р": "P",
    "с": "c",
    "С": "C",
    "х": "x",
    "Х": "X",
    "у": "y",
    "У": "Y",
    "і": "i",
    "І": "I",
    "ј": "j",
    "Ј": "J",
    "ѕ": "s",
    "Ѕ": "S",
    # Greek lookalikes from the pinned table.
    "ο": "o",
    "Ο": "O",
    "α": "a",
    "Α": "A",
}

# Pinned Latin lookalikes that do not decompose (D4 step 6).
LATIN_LOOKALIKES: dict[str, str] = {
    "ı": "i",
    "ł": "l",
    "Ł": "L",
    "ø": "o",
    "Ø": "O",
    "đ": "d",
    "Đ": "D",
}

# Unsafe characters outside the category arms below (D5): blank-rendering
# and default-ignorable characters that are not all Cf.
_EXTRA_UNSAFE: frozenset[str] = frozenset(
    [
        "\u034f",  # combining grapheme joiner
        "\u115f",  # Hangul choseong filler
        "\u1160",  # Hangul jungseong filler
        "\u17b4",  # Khmer vowel inherent aq
        "\u17b5",  # Khmer vowel inherent aa
        "\u2800",  # braille pattern blank
        "\u3164",  # Hangul filler
        "\uffa0",  # halfwidth Hangul filler
    ]
)
_EXTRA_UNSAFE_RANGES: tuple[tuple[int, int], ...] = (
    (0x180B, 0x180F),
    (0xFE00, 0xFE0F),
    (0xE0100, 0xE01EF),
)

_QUOTES: dict[str, str] = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
}

_HYPHENS: frozenset[str] = frozenset(["‐", "‑", "‒", "–", "—", "―", "−"])


def _is_extra_unsafe(char: str) -> bool:
    if char in _EXTRA_UNSAFE:
        return True
    point = ord(char)
    return any(start <= point <= end for start, end in _EXTRA_UNSAFE_RANGES)


def has_unsafe_text(text: str) -> bool:
    """Whether the original text holds a D5 unsafe character.

    Claims only: ``text_check_codes`` strips these for matching and never
    reports them; the claim path rejects them outright.
    """
    for char in text:
        if _is_extra_unsafe(char):
            return True
        category = unicodedata.category(char)
        if category == "Cf":
            return True
        if category == "Cc" and char not in ("\t", "\n", "\r"):
            return True
        if category in ("Co", "Cs", "Cn", "Me"):
            return True
    return False


def _strip_unsafe(text: str) -> str:
    out: list[str] = []
    for char in text:
        if _is_extra_unsafe(char):
            continue
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if category == "Cc" and char not in ("\t", "\n", "\r"):
            continue
        if category in ("Co", "Cs", "Cn", "Me"):
            continue
        out.append(char)
    return "".join(out)


def _fold_once(out: str) -> str:
    """One pass of steps (2) to (6); repeated to a fixpoint below."""
    # (2) Pinned cross-script confusables to Latin.
    out = "".join(CONFUSABLES.get(char, char) for char in out)
    # (3) Every Nd digit (full-width, Arabic-Indic, Devanagari) to ASCII.
    folded: list[str] = []
    for char in out:
        digit = unicodedata.digit(char, None)
        if digit is not None and not ("0" <= char <= "9"):
            folded.append(str(digit))
        else:
            folded.append(char)
    out = "".join(folded)
    # (4) Drop unsafe characters for matching (rejection on claims is
    # decided first, in the claim path).
    out = _strip_unsafe(out)
    # (5) Quotes, hyphen variants and Unicode spaces to plain forms.
    out = "".join(_QUOTES.get(char, char) for char in out)
    out = "".join("-" if char in _HYPHENS else char for char in out)
    out = "".join(
        " "
        if unicodedata.category(char) in ("Zs", "Zl", "Zp") and char != " "
        else char
        for char in out
    )
    # (6) Drop combining marks so accented forms read as base letters,
    # then the pinned Latin lookalikes that do not decompose. A second
    # pass is needed because NFKC can compose a marked letter (such as
    # omicron plus acute) that only the later NFKD split exposes to the
    # confusable map.
    out = unicodedata.normalize(
        "NFC",
        "".join(
            char
            for char in unicodedata.normalize("NFKD", out)
            if unicodedata.category(char) != "Mn"
        ),
    )
    return "".join(LATIN_LOOKALIKES.get(char, char) for char in out)


def normalize_text(text: str) -> str:
    """Return the checked copy of ``text`` (idempotent, case-preserving)."""
    # (1) Compatibility fold: full-width letters, vulgar fractions,
    # superscripts, ligatures and Roman numeral forms read as ASCII here.
    out = unicodedata.normalize("NFKC", text)
    for _ in range(3):
        folded = _fold_once(out)
        if folded == out:
            break
        out = folded
    # (7) Collapse whitespace runs to one space and strip.
    return " ".join(out.split())
