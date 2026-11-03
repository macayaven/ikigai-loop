"""Ticket 26: domain pack command line acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from framework.domains.__main__ import main

from framework.proposal.core import WonderRequest, WonderResponse

ROOT = Path(__file__).resolve().parents[1]
MINI_PACK = ROOT / "tests" / "fixtures" / "domains" / "mini" / "pack.json"


class FakeClient:
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


def _good_proposal() -> str:
    return json.dumps(
        {
            "commitment_id": "review-capacity",
            "claims": [
                {
                    "id": "c1",
                    "text": "Busy days numbered 2 in the week of 2030-01-07.",
                    "metric_refs": [{"metric_id": "busy_days", "value": 2}],
                    "fact_ids": [],
                }
            ],
        }
    )


def test_show_mini(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "--pack", str(MINI_PACK), "--window", "2030-01-07"])
    out = capsys.readouterr().out
    assert code == 0
    assert "identities: 2 of 2 hold" in out


def test_show_bad_window_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "--pack", str(MINI_PACK), "--window", "2030-01-08"])
    capsys.readouterr()
    assert code == 2


def test_check_pass_and_fail_and_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claims = [
        {
            "id": "c1",
            "text": "Total rentals were 110 on 2030-01-07.",
            "metric_refs": [{"metric_id": "total_rentals.2030-01-07", "value": 110}],
            "fact_ids": [],
        }
    ]
    good = tmp_path / "claims.json"
    good.write_text(json.dumps(claims), encoding="utf-8")
    code = main(
        [
            "check",
            "--pack",
            str(MINI_PACK),
            "--window",
            "2030-01-07",
            "--claims",
            str(good),
        ]
    )
    capsys.readouterr()
    assert code == 0
    claims[0]["metric_refs"][0]["value"] = 111  # type: ignore[index]
    bad = tmp_path / "claims_bad.json"
    bad.write_text(json.dumps(claims), encoding="utf-8")
    code = main(
        [
            "check",
            "--pack",
            str(MINI_PACK),
            "--window",
            "2030-01-07",
            "--claims",
            str(bad),
        ]
    )
    capsys.readouterr()
    assert code == 1
    not_list = tmp_path / "not_list.json"
    not_list.write_text(json.dumps({"claims": []}), encoding="utf-8")
    code = main(
        [
            "check",
            "--pack",
            str(MINI_PACK),
            "--window",
            "2030-01-07",
            "--claims",
            str(not_list),
        ]
    )
    capsys.readouterr()
    assert code == 2


def test_propose_with_fake_factory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_file = tmp_path / "run.json"

    def factory() -> FakeClient:
        return FakeClient([_response(_good_proposal())])

    code = main(
        [
            "propose",
            "--pack",
            str(MINI_PACK),
            "--window",
            "2030-01-07",
            "--out",
            str(out_file),
        ],
        client_factory=factory,
    )
    capsys.readouterr()
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["final_passed"] is True
    assert data["window_start"] == "2030-01-07"
