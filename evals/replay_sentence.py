"""Ticket 24: gate one sentence in M119's context (read-only replay).

No model, no network, no file writes: it reads the M119 case, swaps one
sentence into its ``since_last`` claim, and gates the copy.
Exit 0 when the gate passes the sentence, 1 when it stops it,
2 on usage error.
"""

from __future__ import annotations

import copy
import sys
from typing import Any

DEFAULT_SENTENCE = "Prs rose by 3 in the last period."


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _m119_case():
    from evals.briefing_cases import MUTANTS

    return next(c for c in MUTANTS if c.name == "M119-since-last-period-phrase")


def _context_line() -> str:
    case = _m119_case()
    section = next(s for s in case.briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    metric_id = str(claim["metric_refs"][0]["metric_id"])
    assert case.context.parent_metrics is not None
    previous = case.context.parent_metrics.values[metric_id]
    current = case.context.metrics.values[metric_id]
    delta = claim["metric_refs"][0]["value"]
    return (
        "Context: the 15:30 card on Nov 2; "
        f"{metric_id} changed by {_fmt(delta)}, "
        f"from {_fmt(previous)} to {_fmt(current)}, "
        "since the last card; the rest of the briefing is made up."
    )


def _briefing_with(sentence: str) -> dict[str, Any]:
    case = _m119_case()
    briefing = copy.deepcopy(case.briefing)
    section = next(s for s in briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    claim["text"] = sentence
    return briefing


def main(argv: list[str]) -> int:
    if len(argv) > 1 or (argv and (not argv[0].strip() or argv[0].startswith("-"))):
        print("usage: python -m evals.replay_sentence [sentence]", file=sys.stderr)
        return 2
    sentence = argv[0] if argv else DEFAULT_SENTENCE
    print(_context_line())
    from framework.briefing.gate import evaluate_briefing

    result = evaluate_briefing(_briefing_with(sentence), _m119_case().context)
    if result.passed:
        print("passed")
        return 0
    for violation in result.violations:
        print(f"{violation.code} at {violation.location}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
