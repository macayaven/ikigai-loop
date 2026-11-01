"""R3 steering pairs: pure scenario perturbation ops.

``apply_ops(base, ops)`` deep-copies ``base`` and applies each op in order.
Op shapes (every op is a plain object with an ``op`` field):

- ``set_metric`` {id, value}: set ``metrics[id]`` (must already exist).
- ``set_fact`` {id, statement}: replace the statement of fact ``id``.
- ``add_fact`` {id, statement}: append a new fact (id must be fresh).
- ``add_metric`` {id, value}: add a new metric (id must be fresh).
- ``reverse_facts``: reverse the facts list order.
- ``rename_facts`` {prefix}: prepend ``prefix`` to every fact id.
- ``reverse_commitments``: reverse the commitments list order.
- ``slot_in_utc``: rewrite ``slot`` and ``hour`` instants in UTC.

No model, no network, no I/O. The later R3 harness imports this exact code.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any


def _to_utc_iso(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).isoformat()


def apply_ops(base: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a new scenario with ``ops`` applied in order; ``base`` is untouched."""
    scenario: dict[str, Any] = copy.deepcopy(base)
    for op in ops:
        name = op["op"]
        if name == "set_metric":
            if op["id"] not in scenario["metrics"]:
                raise KeyError(f"unknown metric: {op['id']}")
            scenario["metrics"][op["id"]] = op["value"]
        elif name == "set_fact":
            for fact in scenario["facts"]:
                if fact["id"] == op["id"]:
                    fact["statement"] = op["statement"]
                    break
            else:
                raise KeyError(f"unknown fact: {op['id']}")
        elif name == "add_fact":
            if any(f["id"] == op["id"] for f in scenario["facts"]):
                raise KeyError(f"duplicate fact: {op['id']}")
            scenario["facts"].append({"id": op["id"], "statement": op["statement"]})
        elif name == "add_metric":
            if op["id"] in scenario["metrics"]:
                raise KeyError(f"duplicate metric: {op['id']}")
            scenario["metrics"][op["id"]] = op["value"]
        elif name == "reverse_facts":
            scenario["facts"] = list(reversed(scenario["facts"]))
        elif name == "rename_facts":
            prefix = op["prefix"]
            for fact in scenario["facts"]:
                fact["id"] = f"{prefix}{fact['id']}"
        elif name == "reverse_commitments":
            scenario["commitments"] = list(reversed(scenario["commitments"]))
        elif name == "slot_in_utc":
            scenario["slot"] = _to_utc_iso(scenario["slot"])
            scenario["hour"] = {
                "start": _to_utc_iso(scenario["hour"]["start"]),
                "end": _to_utc_iso(scenario["hour"]["end"]),
            }
        else:
            raise KeyError(f"unknown op: {name}")
    return scenario
