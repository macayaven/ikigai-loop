"""Offline replay of the briefing-gate rejection for mutant M12.

No model, no network: it loads case M12 from evals/briefing_cases.py, gates
the draft with the deterministic gate, prints the rejection, then gates a
fixed version of the same draft. Everything is derived from the M12 case,
so this keeps working untouched if M12's wording or metric changes.
Exit 0 on a clean reject-then-pass replay, 1 with a reason otherwise.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.briefing_cases import MUTANTS
from framework.briefing.gate import evaluate_briefing

REAL_REJECTION_FILE = _REPO_ROOT / "evals" / "demo_real_rejection.json"


def kept_rejection_path() -> Path:
    """The kept draft file, honouring the test override first.

    ``IKIGAI_R1B_DEMO_FILE`` points the demo at another file (tests point
    it at a missing file so the M12 replay holds with or without a kept
    draft in the tree); otherwise the kept draft lives at
    ``evals/demo_real_rejection.json``.
    """
    override = os.environ.get("IKIGAI_R1B_DEMO_FILE")
    if override:
        return Path(override)
    return REAL_REJECTION_FILE


def _fmt(value: float) -> str:
    """Format a metric value the way the draft sentence holds it."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _claim_text_at(draft: dict[str, object], location: str) -> str | None:
    """Extract the model's own sentence at a rejected location, display only.

    The kept draft is the draft JSON the model wrote (sections are top-level
    keys); assembly names its claims ``c-<section>-<n>`` in draft order.
    """
    import re

    match = re.fullmatch(r"sections\[(.+)\]\.claims\[(.+)\]", location)
    if match is None:
        return None
    section_name, claim_id = match.group(1), match.group(2)
    claims = draft.get(section_name)
    if not isinstance(claims, list) or not claims:
        return None
    position = re.fullmatch(r"c-" + re.escape(section_name) + r"-(\d+)", claim_id)
    if position is None:
        return None
    index = int(position.group(1)) - 1
    if not 0 <= index < len(claims):
        return None
    claim = claims[index]
    if isinstance(claim, dict) and isinstance(claim.get("text"), str):
        return str(claim["text"])
    return None


def _run_real_rejection() -> int:
    kept = json.loads(kept_rejection_path().read_text(encoding="utf-8"))
    print("Synthetic data only: frozen synthetic fixtures, no personal data.")
    print(
        f"MODEL: {kept['model']} EFFORT: {kept.get('effort', 'unreported')} "
        f"ARM: {kept['arm']}"
    )
    draft_text = str(kept["draft_text"])
    print(f"DRAFT: {draft_text}")
    try:
        draft = json.loads(draft_text)
    except ValueError:
        draft = None
    for code, location in kept["codes"]:
        if isinstance(draft, dict):
            sentence = _claim_text_at(draft, str(location))
            if sentence is not None:
                print(f"SENTENCE: {sentence}")
        print(f"REJECTED {code} at {location}")
    retry_text = kept.get("retry_text")
    if kept.get("retry_passed") and isinstance(retry_text, str):
        print(f"RETRY: {retry_text}")
        print("PASSED")
    else:
        if isinstance(retry_text, str):
            print(f"RETRY: {retry_text}")
        print("NO PASSING RETRY")
    return 0


def main() -> int:
    if kept_rejection_path().exists():
        return _run_real_rejection()
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
