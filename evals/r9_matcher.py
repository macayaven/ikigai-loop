"""Ticket 14 Step 6: the literal keyword baseline for R9, and nothing else.

Ported from the matcher block in the plan (D32): English operation and until
words as pinned, Spanish adding only operation words, title words untouched.
Imported only by ``evals/r9.py``; production never imports it (D30).

These rules aren't Muse Code's: Claude Code wrote the English rules before
any model call and the Spanish words in the plan amendment, as
``CONTRIBUTIONS.md`` says.
"""

from __future__ import annotations

import re
from typing import Any

STOP = {"with", "the", "from", "by", "one"}

OPERATION_WORDS: list[tuple[str, str, str | None]] = [
    ("skip", "skip", "today"),
    ("drop", "drop", "open"),
    ("forget", "drop", "open"),
    ("done", "done", "today"),
    ("did", "done", "today"),
    ("move", "defer", "slot"),
    ("tomorrow", "defer", "tomorrow"),
    ("keep", "keep", None),
    ("salta", "skip", "today"),
    ("sáltate", "skip", "today"),
    ("omite", "skip", "today"),
    ("quita", "drop", "open"),
    ("elimina", "drop", "open"),
    ("borra", "drop", "open"),
    ("olvida", "drop", "open"),
    ("olvídate", "drop", "open"),
    ("hecho", "done", "today"),
    ("hice", "done", "today"),
    ("mueve", "defer", "slot"),
    ("mañana", "defer", "tomorrow"),
    ("mantén", "keep", None),
]

UNTIL_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("tomorrow",), "tomorrow"),
    (("today", "tonight"), "today"),
    (("week", "weekend"), "this_week"),
]


def keywords_for(commitments: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Title words per commitment id, from the rows passed in, not a file."""
    return {
        c["id"]: [
            w for w in re.findall(r"[a-z0-9:-]+", c["title"].lower()) if w not in STOP
        ]
        for c in commitments
    }


def has(word: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text) is not None


def match(transcript: str, commitments: list[dict[str, Any]]) -> dict[str, Any]:
    t = transcript.lower()
    keywords = keywords_for(commitments)
    cid = next(
        (c for c, words in keywords.items() if any(has(w, t) for w in words)),
        None,
    )
    if cid is None:
        return {
            "operation": "none",
            "commitment_id": None,
            "until": None,
            "question": "Which commitment do you mean?",
        }
    for word, operation, until in OPERATION_WORDS:
        if has(word, t):
            return {
                "operation": operation,
                "commitment_id": cid,
                "until": until,
                "question": None,
            }
    return {
        "operation": "none",
        "commitment_id": cid,
        "until": None,
        "question": None,
    }


def match_with_until_words(
    transcript: str, commitments: list[dict[str, Any]]
) -> dict[str, Any]:
    out = match(transcript, commitments)
    if out["operation"] in ("keep", "none"):
        return out
    t = transcript.lower()
    for words, until in UNTIL_WORDS:
        if any(has(w, t) for w in words):
            out["until"] = until
            break
    return out
