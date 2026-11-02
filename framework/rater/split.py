"""Slice A, AD5: split one statement into atomic claims.

Pure: no I/O. Rules are fixed from the prompt's claim rules, applied in
order per statement: sentence split, semicolon split, the ", so" pick
clause, the period series, then the possibly-compound "and".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from framework.briefing.schemas import MetricRef

_PERIOD_WORDS = ("earlier", "prior", "last")
_PERIOD_RE = re.compile(r"\b(earlier|prior|last)\b")
_AND_RE = re.compile(r"\band\b")
_SO_RE = re.compile(r", so(?=\s|$)")


@dataclass(frozen=True)
class AtomicClaim:
    """One rated sentence plus the evidence of its source statement."""

    text: str
    fact_ids: tuple[str, ...]
    metric_refs: tuple[MetricRef, ...]
    section_type: str
    atomic_index: int


@dataclass(frozen=True)
class SplitOutcome:
    """Atomics in order, plus the closed counters for the cut made."""

    atomics: tuple[AtomicClaim, ...]
    so_clauses_cut: int = 0
    so_clauses_kept_with_digit: int = 0
    possibly_compound: int = 0


def _sentence_pieces(statement: str) -> list[str]:
    """Split at sentence ends; a period between digits never ends one."""
    cuts: list[str] = []
    start = 0
    index = 0
    while index < len(statement):
        mark = statement[index]
        if mark in ".!?":
            followed = index + 1 == len(statement) or statement[index + 1].isspace()
            between_digits = (
                mark == "."
                and index > 0
                and index + 1 < len(statement)
                and statement[index - 1].isdigit()
                and statement[index + 1].isdigit()
            )
            if followed and not between_digits:
                cuts.append(statement[start : index + 1])
                index += 1
                while index < len(statement) and statement[index].isspace():
                    index += 1
                start = index
                continue
        index += 1
    cuts.append(statement[start:])
    return [piece.strip() for piece in cuts if piece.strip()]


def _finish(text: str) -> str:
    """One trailing period, whatever the source punctuation was."""
    return text.rstrip(".!?").rstrip() + "."


def split_atomic(
    statement: str,
    *,
    fact_ids: Sequence[str] = (),
    metric_refs: Sequence[MetricRef] = (),
    section_type: str = "overall_state",
) -> SplitOutcome:
    """Split one claim statement into atomic claims with fixed rules."""
    texts: list[str] = []
    cut = 0
    kept_with_digit = 0
    compound = 0
    for sentence in _sentence_pieces(statement):
        for piece in [part.strip() for part in sentence.split(";")]:
            if not piece:
                continue
            split = _SO_RE.split(piece, maxsplit=1)
            if len(split) == 1:
                head = split[0]
                tail: str | None = None
            else:
                head, tail = split[0], split[1]
            if tail is not None:
                if any(mark.isdigit() for mark in tail):
                    texts.append(_finish(piece))
                    kept_with_digit += 1
                else:
                    texts.append(_finish(head))
                    cut += 1
                    if len(set(_PERIOD_RE.findall(head))) < 2 and (
                        _AND_RE.search(head) is not None
                    ):
                        compound += 1
                continue
            periods = set(_PERIOD_RE.findall(piece))
            if len(periods) >= 2:
                texts.append(_finish(piece))
                continue
            if _AND_RE.search(piece) is not None:
                texts.append(_finish(piece))
                compound += 1
                continue
            texts.append(_finish(piece))
    atomics = tuple(
        AtomicClaim(
            text=text,
            fact_ids=tuple(fact_ids),
            metric_refs=tuple(metric_refs),
            section_type=section_type,
            atomic_index=index,
        )
        for index, text in enumerate(texts)
    )
    return SplitOutcome(
        atomics=atomics,
        so_clauses_cut=cut,
        so_clauses_kept_with_digit=kept_with_digit,
        possibly_compound=compound,
    )
