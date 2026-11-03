"""Ticket 26: domain pack runner acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.domains.csv_adapter import build_reference
from framework.domains.runner import (
    build_prompt,
    expected_commitment,
    response_schema,
    run_window,
    validate_proposal,
)
from framework.domains.schema import load_pack

from framework.proposal.core import (
    MetaUnavailableError,
    WonderRequest,
    WonderResponse,
)

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "domains" / "mini"


class FakeClient:
    """Queued client: returns responses or raises, records requests."""

    transport = "fake"
    transport_version = None
    harness_rules_file = None

    def __init__(self, queue: list[Any]) -> None:
        self.queue = list(queue)
        self.requests: list[WonderRequest] = []

    def complete(self, request: WonderRequest) -> WonderResponse:
        self.requests.append(request)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ref(window: str = "2030-01-07") -> tuple[Any, Any]:
    pack = load_pack(MINI / "pack.json")
    return pack, build_reference(pack, MINI, window)


def _response(text: str) -> WonderResponse:
    return WonderResponse(
        text=text,
        model_reported="fake-model",
        latency_ms=12,
        finish_reason="stop",
        prompt_tokens=None,
        completion_tokens=None,
        reasoning_tokens=None,
    )


def _proposal(commitment_id: str, value: int = 2) -> str:
    return json.dumps(
        {
            "commitment_id": commitment_id,
            "claims": [
                {
                    "id": "c1",
                    "text": "Busy days numbered 2 in the week of 2030-01-07.",
                    "metric_refs": [{"metric_id": "busy_days", "value": value}],
                    "fact_ids": [],
                }
            ],
        }
    )


def _enums(node: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        if "enum" in node:
            found.append(node["enum"])
        for value in node.values():
            found.extend(_enums(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_enums(value))
    return found


def _codes(result: Any) -> list[str]:
    return [code for code, _claim_id in result.codes]


def test_expected_commitment_both_mini_weeks() -> None:
    pack, ref = _ref("2030-01-07")
    assert expected_commitment(pack, ref) == "review-capacity"
    pack2, ref2 = _ref("2030-01-14")
    assert pack2 is not None
    assert expected_commitment(pack, ref2) == "continue-monitoring"


def test_build_prompt_contents() -> None:
    pack, ref = _ref()
    prompt = build_prompt(pack, ref)
    assert pack.goal.text in prompt
    assert "review-capacity" in prompt
    assert "continue-monitoring" in prompt
    for metric_id, value in ref.metrics.items():
        assert metric_id in prompt
        assert str(value) in prompt
    assert "busy_rule" in prompt
    assert "source" in prompt


def test_response_schema_enums() -> None:
    pack, ref = _ref()
    schema = response_schema(pack, ref)
    enums = _enums(schema)
    assert ["review-capacity", "continue-monitoring"] in enums
    metric_enums = [e for e in enums if set(e) == set(ref.metrics)]
    assert metric_enums


def test_validate_correct_proposal_passes() -> None:
    pack, ref = _ref()
    result = validate_proposal(pack, ref, _proposal("review-capacity"))
    assert result.passed
    assert result.codes == ()


def test_validate_wrong_commitment_rule() -> None:
    pack, ref = _ref()
    result = validate_proposal(pack, ref, _proposal("continue-monitoring"))
    assert not result.passed
    assert "DOMAIN_COMMITMENT_RULE" in _codes(result)


def test_validate_unknown_commitment() -> None:
    pack, ref = _ref()
    result = validate_proposal(pack, ref, _proposal("bogus-commitment"))
    assert not result.passed
    assert "DOMAIN_UNKNOWN_COMMITMENT" in _codes(result)


def test_validate_wrong_cited_value() -> None:
    pack, ref = _ref()
    result = validate_proposal(pack, ref, _proposal("review-capacity", value=3))
    assert not result.passed
    assert "L1B_METRIC_VALUE_MISMATCH" in _codes(result)


def test_validate_not_json_only_unparseable() -> None:
    pack, ref = _ref()
    result = validate_proposal(pack, ref, "not json")
    assert not result.passed
    assert _codes(result) == ["DOMAIN_UNPARSEABLE"]


def test_run_window_repair() -> None:
    pack, ref = _ref()
    client = FakeClient(
        [
            _response(_proposal("review-capacity", value=3)),
            _response(_proposal("review-capacity")),
        ]
    )
    run = run_window(pack, ref, client, model="fake-model", effort="medium")
    assert len(run.attempts) == 2
    assert run.first_pass_accepted is False
    assert run.repaired is True
    assert run.final_passed is True
    assert len(client.requests) == 2
    assert "L1B_METRIC_VALUE_MISMATCH" in client.requests[1].prompt


def test_run_window_first_pass() -> None:
    pack, ref = _ref()
    client = FakeClient([_response(_proposal("review-capacity"))])
    run = run_window(pack, ref, client, model="fake-model", effort="medium")
    assert len(run.attempts) == 1
    assert run.first_pass_accepted is True
    assert run.repaired is False
    assert run.final_passed is True


def test_run_window_transport_error() -> None:
    pack, ref = _ref()
    client = FakeClient([MetaUnavailableError("timeout")])
    run = run_window(pack, ref, client, model="fake-model", effort="medium")
    assert run.transport_error is not None
    assert "timeout" in run.transport_error
    assert "MetaUnavailableError" in run.transport_error
    assert run.final_passed is False


def test_window_run_to_json_round_trip() -> None:
    pack, ref = _ref()
    client = FakeClient([_response(_proposal("review-capacity"))])
    run = run_window(pack, ref, client, model="fake-model", effort="medium")
    data = json.loads(json.dumps(run.to_json()))
    assert set(data) == {
        "pack_id",
        "window_start",
        "model",
        "effort",
        "expected_commitment",
        "attempts",
        "first_pass_accepted",
        "repaired",
        "final_passed",
        "transport_error",
        "latency_ms_total",
    }
    assert data["pack_id"] == pack.pack_id
    assert data["window_start"] == "2030-01-07"
    assert data["expected_commitment"] == "review-capacity"
    assert data["final_passed"] is True


def test_fake_client_records_requests() -> None:
    pack, ref = _ref()
    client = FakeClient([_response(_proposal("review-capacity"))])
    run_window(pack, ref, client, model="fake-model", effort="medium")
    assert len(client.requests) == 1
    assert isinstance(client.requests[0], WonderRequest)
