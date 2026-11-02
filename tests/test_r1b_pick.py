"""Ticket 16b: the kept-draft pick rule (D20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.r1b import load_cases, run_pick

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CASES = REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json"

GATE_COMMIT = "0" * 40
GATE_HASH = "c" * 64
CASES_SHA = "f" * 64


def _row(
    *,
    arm: str,
    model: str,
    effort: str,
    case: str,
    codes: list[list[str]],
    attempt: int = 1,
    execution: int = 1,
    parsed_ok: bool = True,
    blocked: bool = False,
    raw: str = '{"a": 1}',
) -> dict[str, Any]:
    return {
        "schema": 1,
        "case_id": case,
        "trap": None,
        "arm": arm,
        "model": model,
        "model_reported": model,
        "effort": effort,
        "attempt": attempt,
        "execution": execution,
        "raw_text": raw,
        "parsed_ok": parsed_ok,
        "blocked": blocked,
        "codes": codes,
        "latency_ms": 5,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "reasoning_tokens": None,
        "finish_reason": "stop",
        "prompt_hash": "x",
        "cases_sha256": CASES_SHA,
        "gate_commit": GATE_COMMIT,
        "gate_hash": GATE_HASH,
        "transport": "muse",
        "muse_version": None,
        "harness_rules_file": False,
        "recorded_at": "2026-11-02T09:00:00+01:00",
    }


def _pick(rows: list[dict[str, Any]], tmp_path: Path) -> dict[str, Any] | None:
    out = tmp_path / "kept.json"
    picked = run_pick(
        rows=rows,
        cases=list(load_cases(FIXTURE_CASES)),
        cases_sha256=CASES_SHA,
        gate_hash12=GATE_HASH[:12],
        output_path=out,
    )
    if picked is None:
        assert not out.exists()
        return None
    assert out.exists()
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored["draft_text"] == picked["draft_text"]
    return picked


def test_passing_retry_outranks_arm(tmp_path: Path) -> None:
    rows = [
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f01",
            codes=[["L1B_NUMBER_WITHOUT_METRIC_REF", "loc"]],
            raw='{"k": "product"}',
        ),
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f01",
            codes=[["L1B_DIRECTION_MISMATCH", "loc"]],
            attempt=2,
            raw='{"k": "product-retry"}',
        ),
        _row(
            arm="plain",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f02",
            codes=[["L1B_DIRECTION_MISMATCH", "loc"]],
            raw='{"k": "plain"}',
        ),
        _row(
            arm="plain",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f02",
            codes=[],
            attempt=2,
            raw='{"k": "plain-retry"}',
        ),
    ]
    picked = _pick(rows, tmp_path)
    assert picked is not None
    assert picked["arm"] == "plain"
    assert picked["draft_text"] == '{"k": "plain"}'
    assert picked["retry_passed"] is True
    assert picked["retry_text"] == '{"k": "plain-retry"}'


def test_product_outranks_plain_without_passing_retry(tmp_path: Path) -> None:
    rows = [
        _row(
            arm="plain",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f01",
            codes=[["L1B_DIRECTION_MISMATCH", "loc"]],
        ),
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f02",
            codes=[["L1B_UNKNOWN_METRIC", "loc"]],
        ),
    ]
    picked = _pick(rows, tmp_path)
    assert picked is not None
    assert (picked["arm"], picked["case_id"]) == ("product", "r1b-f02")


def test_matrix_order_then_case_order(tmp_path: Path) -> None:
    rows = [
        _row(
            arm="product",
            model="muse-spark-1.3",
            effort="low",
            case="r1b-f01",
            codes=[["L1B_DELTA_MISMATCH", "loc"]],
        ),
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f02",
            codes=[["L1B_METRIC_VALUE_MISMATCH", "loc"]],
        ),
    ]
    picked = _pick(rows, tmp_path)
    assert picked is not None
    assert (picked["model"], picked["case_id"]) == ("muse-wonder-1.0", "r1b-f02")


def test_non_qualifying_codes_pick_nothing(tmp_path: Path) -> None:
    rows = [
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f01",
            codes=[["L1_ADVICE", "loc"]],
        ),
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f02",
            codes=[["DRAFT_UNPARSEABLE", "draft"]],
            parsed_ok=False,
        ),
        _row(
            arm="plain",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f03",
            codes=[["MODEL_UNAVAILABLE", "timeout"]],
            parsed_ok=False,
            raw="",
        ),
        _row(
            arm="plain",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f04",
            codes=[["L1_SECRET", "prompt"]],
            blocked=True,
            raw="",
        ),
    ]
    assert _pick(rows, tmp_path) is None


def test_other_gate_identity_ignored(tmp_path: Path) -> None:
    row = _row(
        arm="product",
        model="muse-wonder-1.0",
        effort="high",
        case="r1b-f01",
        codes=[["L1B_NUMBER_WITHOUT_METRIC_REF", "loc"]],
    )
    row["gate_hash"] = "d" * 64
    assert _pick([row], tmp_path) is None


def test_kept_record_shape(tmp_path: Path) -> None:
    rows = [
        _row(
            arm="product",
            model="muse-wonder-1.0",
            effort="high",
            case="r1b-f01",
            codes=[["L1B_NUMBER_WITHOUT_METRIC_REF", "loc"]],
            raw='{"k": 1}',
        ),
    ]
    picked = _pick(rows, tmp_path)
    assert picked is not None
    assert picked["synthetic"] is True
    assert picked["label"] == "synthetic data only"
    assert picked["trap"] is None
    assert picked["gate_hash"] == GATE_HASH
    assert picked["retry_text"] is None
    assert picked["retry_passed"] is False
    assert picked["effort"] == "high"
