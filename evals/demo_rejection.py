"""Offline replay of the briefing-gate rejection for mutant M12.

No model, no network: it loads case M12 from evals/briefing_cases.py, gates
the draft with the deterministic gate, prints the rejection, then gates a
fixed version of the same draft. Everything is derived from the M12 case,
so this keeps working untouched if M12's wording or metric changes.
Exit 0 on a clean reject-then-pass replay, 1 with a reason otherwise.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.briefing_cases import MUTANTS
from framework.briefing.gate import evaluate_briefing


def _fmt(value: float) -> str:
    """Format a metric value the way the draft sentence holds it."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def main() -> int:
    print("Synthetic data only: frozen synthetic fixtures, no personal data.")
    case = next(c for c in MUTANTS if c.name == "M12-metric-mismatch")
    working = next(s for s in case.briefing["sections"] if s["type"] == "working")
    claim = next(c for c in working["claims"] if c["id"] == "claim-w1")
    ref = claim["metric_refs"][0]
    metric_id = ref["metric_id"]
    source = case.context.metrics.values[metric_id]
    draft = str(claim["text"])
    print(f"DRAFT: {draft}")
    result = evaluate_briefing(case.briefing, case.context)
    for violation in result.violations:
        print(f"REJECTED {violation.code} at {violation.location}")
    if [v.code for v in result.violations] != list(case.expected):
        print(
            f"draft violations {[v.code for v in result.violations]} "
            f"do not match expected {list(case.expected)}",
            file=sys.stderr,
        )
        return 1
    fixed = copy.deepcopy(case.briefing)
    fixed_claim = next(
        c
        for s in fixed["sections"]
        if s["type"] == "working"
        for c in s["claims"]
        if c["id"] == "claim-w1"
    )
    fixed_claim["metric_refs"][0]["value"] = source
    fixed_claim["text"] = draft.replace(_fmt(ref["value"]), _fmt(source), 1)
    print(f"SOURCE: {metric_id} is {_fmt(source)}")
    print(f"FIXED: {fixed_claim['text']}")
    passing = evaluate_briefing(fixed, case.context)
    if not passing.passed:
        print(
            "fixed briefing still rejected: "
            + "; ".join(f"{v.code} at {v.location}" for v in passing.violations),
            file=sys.stderr,
        )
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
