"""Ticket 16b: the plain prompt and schema (D6, D7).

The prompt a competent engineer would write first: the same task, the same
data blocks byte-identical to the product arm's, none of the gate's rules.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from framework.briefing.context import TimeInterval
from framework.briefing.labels import metric_label_binding
from framework.briefing.schemas import Commitment
from framework.glimmer.prompt import strip_feed_title
from framework.proposal.prompt import (
    Delta,
    _dump,
    _metric_sort_key,
    _ordered_labels,
    display_value,
    fill_once,
)
from framework.schemas.core import Fact

_TEMPLATE = """You are writing a short briefing card for one goal. Pick the commitment below that most deserves the hour shown, and write a few short claims about what the data shows for this goal. Use only the data below.

Return JSON only, with this shape: an object with commitment_id (the id of the commitment you pick), overall_state, working and not_working{since_last_field}. Each of those is a list of claims. Each claim is an object with text (one sentence in English), fact_ids (a list of fact ids from the facts below that support the claim) and metric_refs (a list of metric ids from the metrics below that support the claim).{since_last_sentence}

PROFILE: {profile_name}
HOUR: {hour_start} to {hour_end}
{policy_block}METRICS (one JSON object per line):
<<<METRIC_DATA
{metric_lines}
METRIC_DATA>>>
{delta_block}FACTS (one JSON object per line):
<<<FACT_DATA
{fact_lines}
FACT_DATA>>>

COMMITMENTS (one JSON object per line; choose one id):
<<<COMMITMENT_DATA
{commitment_lines}
COMMITMENT_DATA>>>"""


def build_plain_prompt(
    *,
    profile_name: str,
    hour: TimeInterval,
    facts: Sequence[Fact],
    metrics: Mapping[str, float],
    deltas: Sequence[Delta],
    commitments: Sequence[Commitment],
    policy: str = "",
) -> str:
    """Render the plain prompt: same data lines as the product, plain rules."""
    from framework.proposal.prompt import offered_metrics

    _ = policy
    offered = offered_metrics(metrics)
    ordered_ids = sorted(offered, key=_metric_sort_key)
    metric_lines: list[str] = []
    for metric_id in ordered_ids:
        binding = metric_label_binding(metric_id)
        assert binding is not None
        metric_lines.append(
            _dump(
                {
                    "id": metric_id,
                    "value": display_value(offered[metric_id]),
                    "labels": _ordered_labels(binding.labels),
                    "period": binding.period,
                }
            )
        )
    delta_lines = [
        _dump({"id": delta.metric_id, "value": delta.display}) for delta in deltas
    ]
    fact_lines = [
        _dump({"id": fact.id, "statement": strip_feed_title(fact.statement)})
        for fact in facts
    ]
    commitment_lines = [
        _dump(
            {
                "id": commitment.id,
                "title": strip_feed_title(commitment.title),
                "kind": commitment.kind,
                "dimension": commitment.dimension,
            }
        )
        for commitment in commitments
    ]
    has_parent = bool(deltas)
    if has_parent:
        since_last_field = ", since_last"
        since_last_sentence = (
            " since_last holds claims about what changed since the last card."
        )
        delta_block = (
            "DELTAS SINCE THE LAST CARD (one JSON object per line):\n<<<DELTA_DATA\n"
            + "\n".join(delta_lines)
            + "\nDELTA_DATA>>>\n"
        )
    else:
        since_last_field = ""
        since_last_sentence = ""
        delta_block = ""
    return fill_once(
        _TEMPLATE,
        {
            "since_last_field": since_last_field,
            "since_last_sentence": since_last_sentence,
            "profile_name": profile_name,
            "hour_start": hour.start.isoformat(),
            "hour_end": hour.end.isoformat(),
            "policy_block": "",
            "metric_lines": "\n".join(metric_lines),
            "delta_block": delta_block,
            "fact_lines": "\n".join(fact_lines),
            "commitment_lines": "\n".join(commitment_lines),
        },
    )


def _plain_claim() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "fact_ids": {"type": "array", "items": {"type": "string"}},
            "metric_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text", "fact_ids", "metric_refs"],
        "additionalProperties": False,
    }


def _plain_section() -> dict[str, Any]:
    return {"type": "array", "items": _plain_claim()}


def build_plain_response_schema(*, has_parent: bool) -> dict[str, Any]:
    """Same required fields as the product schema, free strings, no enums."""
    properties: dict[str, Any] = {
        "commitment_id": {"type": "string"},
        "overall_state": _plain_section(),
        "working": _plain_section(),
        "not_working": _plain_section(),
    }
    required = ["commitment_id", "overall_state", "working", "not_working"]
    if has_parent:
        properties["since_last"] = _plain_section()
        required.append("since_last")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
