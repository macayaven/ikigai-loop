"""Ticket 15b: R3 prompt-diff test (D26, D29).

Every pair/arm goes through Ticket 11's real ``propose`` against a
recording fake client. The test asserts exactly what each op changes in
the first-attempt prompt and response schema. If any registered pair
cannot take effect through the real path, this test fails and the
ticket stops: pairs and path are never patched to pass.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from evals.r1b import metric_sort_key
from evals.r3 import build_slot_materials, load_pairs, scenario_for
from framework.cycle.orchestrator import (
    SLOT_LIMITS,
    EligibilityState,
    classify_slot,
    eligible_commitments,
    slot_profiles,
    validate_slot,
)
from framework.proposal.core import ModelParams, OutboundBlocked, propose
from framework.proposal.hour import allowed_windows, pick_hour
from framework.proposal.prompt import display_value

PAIR_IDS = [f"D{i}" for i in range(1, 11)] + [f"I{i}" for i in range(1, 11)]


class RecordingBlockedClient:
    """Record every request, then stop at the outbound scan: one attempt."""

    transport = "recording"
    transport_version: str | None = "recording-1"
    harness_rules_file: bool | None = False

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def complete(self, request: Any) -> Any:
        self.requests.append(request)
        raise OutboundBlocked(("L1_TEST_BLOCK",))


def _request_for(scenario: dict[str, Any], profile: str) -> Any:
    materials = build_slot_materials(scenario, profile)
    client = RecordingBlockedClient()
    propose(
        profile_id=profile,
        subject_id="subject-1",
        slot=materials.slot,
        as_of=materials.slot,
        cycle_id="r3-test",
        run=1,
        hour=materials.hour,
        eligible=materials.eligible,
        context=materials.context,
        client=client,
        models=ModelParams("m", "high", "m", "high"),
        policy="",
        stale_after_s=12 * 3600.0,
        cycle_as_of=materials.slot,
        offered={},
    )
    assert len(client.requests) == 1
    return client.requests[0]


def _blocks(prompt: str) -> dict[str, list[str]]:
    lines = prompt.splitlines()
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line == "<<<METRIC_DATA":
            current = "metrics"
            blocks[current] = []
        elif line == "<<<FACT_DATA":
            current = "facts"
            blocks[current] = []
        elif line == "<<<COMMITMENT_DATA":
            current = "commitments"
            blocks[current] = []
        elif line in ("METRIC_DATA>>>", "FACT_DATA>>>", "COMMITMENT_DATA>>>"):
            current = None
        elif current is not None:
            blocks[current].append(line)
    return blocks


def _hour_line(prompt: str) -> str:
    return next(line for line in prompt.splitlines() if line.startswith("HOUR:"))


def _fact_enum(schema: dict[str, Any]) -> list[str]:
    claim = schema["properties"]["overall_state"]["items"]
    return list(claim["properties"]["fact_ids"]["items"]["enum"])


def _commitment_enum(schema: dict[str, Any]) -> list[str]:
    return list(schema["properties"]["commitment_id"]["enum"])


def _pair_requests(pair_id: str) -> tuple[Any, Any, dict[str, Any]]:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == pair_id)
    base = scenario_for(doc, pair, "base")
    perturbed = scenario_for(doc, pair, "perturbed")
    return (
        _request_for(base, pair["profile"]),
        _request_for(perturbed, pair["profile"]),
        pair,
    )


def test_base_hour_equals_pick_hour() -> None:
    doc, _sha = load_pairs()
    slot = datetime.fromisoformat(doc["slot"])
    expected = pick_hour(slot, (), SLOT_LIMITS)
    assert expected is not None
    for pair in doc["pairs"]:
        base = scenario_for(doc, pair, "base")
        materials = build_slot_materials(base, pair["profile"])
        assert materials.hour == expected, pair["id"]
        assert materials.hour is not None and materials.slot == slot


def test_base_slot_valid_and_i8_refused() -> None:
    doc, _sha = load_pairs()
    base_slot = datetime.fromisoformat(doc["slot"])
    assert validate_slot(base_slot) is None
    assert set(slot_profiles(base_slot)) == {"builder", "disconnect"}
    for pair in doc["pairs"]:
        assert pair["profile"] in slot_profiles(base_slot), pair["id"]
    i8 = next(p for p in doc["pairs"] if p["id"] == "I8")
    perturbed = scenario_for(doc, i8, "perturbed")
    utc_slot = datetime.fromisoformat(perturbed["slot"])
    assert classify_slot(base_slot) == "ok"
    assert classify_slot(utc_slot) == "bad_offset"
    assert validate_slot(utc_slot) == "SLOT_NOT_PINNED"


def test_same_profile_base_prompts_byte_identical() -> None:
    doc, _sha = load_pairs()
    seen: dict[str, tuple[str, str]] = {}
    for pair in doc["pairs"]:
        base = scenario_for(doc, pair, "base")
        request = _request_for(base, pair["profile"])
        key = pair["profile"]
        prompt = request.prompt
        schema_text = json.dumps(request.response_schema, sort_keys=True)
        if key in seen:
            assert (prompt, schema_text) == seen[key], pair["id"]
        else:
            seen[key] = (prompt, schema_text)


def test_eligibility_keeps_profile_order_at_base_slot() -> None:
    doc, _sha = load_pairs()
    slot = datetime.fromisoformat(doc["slot"])
    hour_start = datetime.fromisoformat(doc["hour"]["start"])
    state = EligibilityState(
        disconnect_sent_today=0, now_local=slot, hour_start_local=hour_start
    )
    assert [c["id"] for c in doc["commitments"] if c["profile"] == "builder"] == [
        "b-ship",
        "b-read",
        "b-write",
        "b-apply",
    ]
    base = {
        "slot": doc["slot"],
        "hour": doc["hour"],
        "commitments": doc["commitments"],
        "facts": doc["facts"],
        "metrics": doc["metrics"],
    }
    materials = build_slot_materials(base, "disconnect")
    assert [c.id for c in materials.eligible] == [
        "d-family",
        "d-screens",
        "d-music",
        "d-date",
    ]
    _ = eligible_commitments(
        materials.context.commitments,
        profile_id="disconnect",
        slot_local=slot,
        state=state,
    )


def _assert_set_fact_metric(
    base: Any, perturbed: Any, fact_id: str, metric_id: str, value: float
) -> None:
    base_blocks = _blocks(base.prompt)
    pert_blocks = _blocks(perturbed.prompt)
    base_facts = [json.loads(line) for line in base_blocks["facts"]]
    pert_facts = [json.loads(line) for line in pert_blocks["facts"]]
    assert len(base_facts) == len(pert_facts)
    diffs = [
        index
        for index, (old, new) in enumerate(zip(base_facts, pert_facts))
        if old != new
    ]
    assert len(diffs) == 1
    (index,) = diffs
    assert base_facts[index]["id"] == fact_id
    assert pert_facts[index]["id"] == fact_id
    assert pert_facts[index]["statement"] != base_facts[index]["statement"]
    base_metrics = [json.loads(line) for line in base_blocks["metrics"]]
    pert_metrics = [json.loads(line) for line in pert_blocks["metrics"]]
    assert [m["id"] for m in base_metrics] == [m["id"] for m in pert_metrics]
    metric_diffs = [
        index
        for index, (old, new) in enumerate(zip(base_metrics, pert_metrics))
        if old != new
    ]
    assert len(metric_diffs) == 1
    (mindex,) = metric_diffs
    assert base_metrics[mindex]["id"] == metric_id
    assert pert_metrics[mindex]["value"] == display_value(value)
    assert _fact_enum(base.response_schema) == _fact_enum(perturbed.response_schema)


def _assert_add_fact_metrics(
    base: Any, perturbed: Any, fact_id: str, metrics: dict[str, float]
) -> None:
    base_blocks = _blocks(base.prompt)
    pert_blocks = _blocks(perturbed.prompt)
    base_facts = [json.loads(line) for line in base_blocks["facts"]]
    pert_facts = [json.loads(line) for line in pert_blocks["facts"]]
    assert len(pert_facts) == len(base_facts) + 1
    assert pert_facts[: len(base_facts)] == base_facts
    assert pert_facts[-1]["id"] == fact_id
    base_ids = [json.loads(line)["id"] for line in base_blocks["metrics"]]
    pert_ids = [json.loads(line)["id"] for line in pert_blocks["metrics"]]
    assert sorted(pert_ids, key=metric_sort_key) == pert_ids
    assert sorted(base_ids, key=metric_sort_key) == base_ids
    assert set(pert_ids) == set(base_ids) | set(metrics)
    pert_metrics = {
        json.loads(line)["id"]: json.loads(line) for line in pert_blocks["metrics"]
    }
    for metric_id, value in metrics.items():
        assert pert_metrics[metric_id]["value"] == display_value(value)


@pytest.mark.parametrize("pair_id", PAIR_IDS)
def test_pair_takes_effect_through_the_real_path(pair_id: str) -> None:
    base, perturbed, pair = _pair_requests(pair_id)
    assert base.prompt != perturbed.prompt
    ops = pair["perturb"]
    kinds = sorted(op["op"] for op in ops)
    if kinds == ["set_fact", "set_metric"]:
        (fact_op,) = [op for op in ops if op["op"] == "set_fact"]
        (metric_op,) = [op for op in ops if op["op"] == "set_metric"]
        _assert_set_fact_metric(
            base, perturbed, fact_op["id"], metric_op["id"], metric_op["value"]
        )
    elif kinds == ["set_fact", "set_fact", "set_metric", "set_metric"]:
        base_blocks = _blocks(base.prompt)
        pert_blocks = _blocks(perturbed.prompt)
        base_facts = [json.loads(line) for line in base_blocks["facts"]]
        pert_facts = [json.loads(line) for line in pert_blocks["facts"]]
        assert len(base_facts) == len(pert_facts)
        for fact_op in (op for op in ops if op["op"] == "set_fact"):
            matches = [
                (old, new)
                for old, new in zip(base_facts, pert_facts)
                if old["id"] == fact_op["id"]
            ]
            assert len(matches) == 1
            old, new = matches[0]
            assert new["statement"] == fact_op["statement"]
            assert old["statement"] != new["statement"]
        base_metrics = {
            json.loads(line)["id"]: json.loads(line) for line in base_blocks["metrics"]
        }
        pert_metrics = {
            json.loads(line)["id"]: json.loads(line) for line in pert_blocks["metrics"]
        }
        assert set(base_metrics) == set(pert_metrics)
        for metric_op in (op for op in ops if op["op"] == "set_metric"):
            assert pert_metrics[metric_op["id"]]["value"] == display_value(
                metric_op["value"]
            )
        changed = [
            mid for mid in base_metrics if base_metrics[mid] != pert_metrics[mid]
        ]
        assert len(changed) == 2
    elif pair_id in ("D3", "D9", "D10", "I7"):
        (fact_op,) = [op for op in ops if op["op"] == "add_fact"]
        metrics = {op["id"]: op["value"] for op in ops if op["op"] == "add_metric"}
        _assert_add_fact_metrics(base, perturbed, fact_op["id"], metrics)
        last = json.loads(_blocks(perturbed.prompt)["facts"][-1])
        assert last["statement"] == fact_op["statement"]
    elif pair_id in ("I3", "I4"):
        base_blocks = _blocks(base.prompt)
        pert_blocks = _blocks(perturbed.prompt)
        assert pert_blocks["facts"] == list(reversed(base_blocks["facts"]))
        assert pert_blocks["metrics"] == base_blocks["metrics"]
        assert pert_blocks["commitments"] == base_blocks["commitments"]
        assert _fact_enum(perturbed.response_schema) == list(
            reversed(_fact_enum(base.response_schema))
        )
        assert _commitment_enum(perturbed.response_schema) == _commitment_enum(
            base.response_schema
        )
    elif pair_id == "I5":
        (op,) = ops
        base_blocks = _blocks(base.prompt)
        pert_blocks = _blocks(perturbed.prompt)
        base_facts = [json.loads(line) for line in base_blocks["facts"]]
        pert_facts = [json.loads(line) for line in pert_blocks["facts"]]
        assert [f["id"] for f in pert_facts] == [
            f"{op['prefix']}{f['id']}" for f in base_facts
        ]
        assert [f["statement"] for f in pert_facts] == [
            f["statement"] for f in base_facts
        ]
        assert _fact_enum(perturbed.response_schema) == [
            f"{op['prefix']}{fid}" for fid in _fact_enum(base.response_schema)
        ]
        assert pert_blocks["metrics"] == base_blocks["metrics"]
        assert pert_blocks["commitments"] == base_blocks["commitments"]
    elif pair_id == "I6":
        base_blocks = _blocks(base.prompt)
        pert_blocks = _blocks(perturbed.prompt)
        assert pert_blocks["commitments"] == list(reversed(base_blocks["commitments"]))
        assert [json.loads(line)["id"] for line in pert_blocks["commitments"]] == [
            "d-date",
            "d-music",
            "d-screens",
            "d-family",
        ]
        assert _commitment_enum(perturbed.response_schema) == list(
            reversed(_commitment_enum(base.response_schema))
        )
        assert pert_blocks["facts"] == base_blocks["facts"]
        assert pert_blocks["metrics"] == base_blocks["metrics"]
    elif pair_id == "I8":
        merged_base = base.prompt.replace(_hour_line(base.prompt), "")
        merged_pert = perturbed.prompt.replace(_hour_line(perturbed.prompt), "")
        assert merged_base == merged_pert
        base_start, _, _ = (
            _hour_line(base.prompt).removeprefix("HOUR: ").partition(" to ")
        )
        pert_start, _, _ = (
            _hour_line(perturbed.prompt).removeprefix("HOUR: ").partition(" to ")
        )
        assert datetime.fromisoformat(pert_start) == datetime.fromisoformat(base_start)
        assert base.response_schema == perturbed.response_schema
    else:
        pytest.fail(f"unhandled perturb shape for {pair_id}: {kinds}")


def test_allowed_windows_match_run_proposals_construction() -> None:
    doc, _sha = load_pairs()
    slot = datetime.fromisoformat(doc["slot"])
    assert (
        allowed_windows(slot, SLOT_LIMITS)
        == build_slot_materials(
            scenario_for(doc, doc["pairs"][0], "base"), "builder"
        ).context.free_intervals
    )
