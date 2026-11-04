"""Ticket 26: a lint for pack authors.

Quotes every fact and states every metric once, then runs each
sentence through the checker on its own. A pack lints clean when its
own words already survive quoting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.domains.csv_adapter import WindowReference
from framework.domains.schema import DomainPack
from framework.verify.hardened import check_claims


@dataclass(frozen=True)
class LintResult:
    """The verdict for one quoted fact or one stated metric."""

    subject: str
    passed: bool
    codes: tuple[str, ...]


def _display_name(labels: list[str]) -> str:
    name = " ".join(labels)
    return name[:1].upper() + name[1:] if name else name


def _fact_claim(fact_id: str, text: str) -> dict[str, Any]:
    return {
        "id": f"lint-fact-{fact_id}",
        "text": text,
        "metric_refs": [],
        "fact_ids": [fact_id],
    }


def _metric_claim(
    metric_id: str, name: str, value: int, period: str, daily: bool, total: bool
) -> dict[str, Any]:
    shown = f"{value:,}"
    if daily:
        text = f"{name} were {shown} on {period}."
    elif total:
        text = f"{name} were {shown} in the {period}."
    else:
        text = f"{name} numbered {shown} in the {period}."
    return {
        "id": f"lint-metric-{metric_id}",
        "text": text,
        "metric_refs": [{"metric_id": metric_id, "value": value}],
        "fact_ids": [],
    }


def lint_pack(pack: DomainPack, ref: WindowReference) -> list[LintResult]:
    """Quote every fact and state every metric against one window."""
    kinds = {metric.id: metric.op for metric in pack.window_metrics}
    prefixes = {metric.prefix for metric in pack.daily_metrics}
    results: list[LintResult] = []
    for fact_id, text in pack.facts.items():
        report = check_claims(ref.check_input([_fact_claim(fact_id, text)]))
        results.append(
            LintResult(
                subject=f"fact {fact_id}",
                passed=report.passed,
                codes=tuple(item.code for item in report.violations),
            )
        )
    for metric_id, value in ref.metrics.items():
        head = metric_id.split(".", 1)[0]
        daily = head in prefixes and "." in metric_id
        claim = _metric_claim(
            metric_id,
            _display_name(ref.labels[metric_id]),
            value,
            ref.periods[metric_id],
            daily,
            kinds.get(metric_id) == "sum",
        )
        report = check_claims(ref.check_input([claim]))
        results.append(
            LintResult(
                subject=f"metric {metric_id}",
                passed=report.passed,
                codes=tuple(item.code for item in report.violations),
            )
        )
    return results
