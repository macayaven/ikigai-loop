"""Ticket 16b: runner tests over scripted fake clients (D5, D14-D18).

No network, no real client construction, no model call: every test drives
``evals.r1b.main`` or its helpers with a scripted ``WonderClient``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from evals import r1b
from evals.r1b import (
    ARM_REGISTRY,
    ArmSpec,
    R1bCase,
    load_cases,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json"


class ScriptedClient:
    """Replay scripted outcomes; snapshot the environment per call."""

    transport = "scripted"
    transport_version: str | None = "scripted-1"
    harness_rules_file: bool | None = False

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self._script = list(script)
        self.requests: list[Any] = []
        self.env_snapshots: list[dict[str, str]] = []
        self.calls = 0

    def complete(self, request: Any) -> Any:
        from framework.proposal.client import refuse_contributor_model
        from framework.proposal.core import (
            MetaUnavailableError,
            OutboundBlocked,
            WonderResponse,
        )

        self.requests.append(request)
        self.env_snapshots.append(dict(os.environ))
        refuse_contributor_model(request.model)
        if self.calls >= len(self._script):
            raise AssertionError("client called more times than scripted")
        kind, payload = self._script[self.calls]
        self.calls += 1
        if kind == "unavailable":
            raise MetaUnavailableError(payload or "timeout", latency_ms=3)
        if kind == "blocked":
            raise OutboundBlocked((payload,))
        if kind == "cached":
            return WonderResponse(
                text=payload,
                model_reported="scripted-client",
                latency_ms=7,
                finish_reason="stop",
                prompt_tokens=11,
                completion_tokens=13,
                reasoning_tokens=None,
                cached_tokens=5,
            )
        return WonderResponse(
            text=payload,
            model_reported="scripted-client",
            latency_ms=7,
            finish_reason="stop",
            prompt_tokens=11,
            completion_tokens=13,
            reasoning_tokens=None,
        )


def _draft_for(case: R1bCase, bad_number: bool = False) -> str:
    import json as _json

    from tests.test_r1b_cases import build_minimal_draft

    draft = build_minimal_draft(case)
    if bad_number:
        claim = draft["overall_state"][0]
        claim["text"] = claim["text"].replace("2.5", "2.6").replace(" 6 ", " 7 ")
        if "2.5" not in claim["text"] and " 6 " not in claim["text"]:
            claim["text"] = "Busy was 9 across the window"
    return _json.dumps(draft)


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("IKIGAI_R1B_LIVE", "1")
    monkeypatch.setenv("MUSE_NO_AUTO_UPDATE", "1")
    monkeypatch.delenv("META_API_KEY", raising=False)
    for key in ("LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL", "LOCAL_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    results = tmp_path / "r1b"
    results.mkdir(exist_ok=True)
    return results


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
    script: list[tuple[str, str]],
    routes: dict[str, ScriptedClient] | None = None,
) -> tuple[int, Path, dict[str, ScriptedClient]]:
    results = _clean_env(monkeypatch, tmp_path)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        _ = llm_config
        client = (routes or {}).get(route, ScriptedClient(script))
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        ["--cases", str(FIXTURE_PATH), "--results-dir", str(results), *args]
    )
    return code, results, made


def _rows(results: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            rows.append(json.loads(line))
    return rows


# Registry ------------------------------------------------------------------


def test_registry_holds_exactly_product_and_plain() -> None:
    assert tuple(spec.name for spec in ARM_REGISTRY) == ("product", "plain")
    assert ARM_REGISTRY[0] == ArmSpec("product", "product", "product")
    assert ARM_REGISTRY[1] == ArmSpec("plain", "plain", "plain")


def test_unregistered_arm_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--arm", "nope"],
        [("text", "{}")],
    )
    assert code == 2
    assert "product" in capsys.readouterr().err
    assert list(results.glob("*.jsonl")) == []


def test_matrix_pins_five_rows_in_order() -> None:
    assert [(row.model, row.effort, row.route) for row in r1b.MATRIX] == [
        ("muse-wonder-1.0", "high", "muse"),
        ("muse-wonder-full-1.0", "high", "muse"),
        ("muse-spark-1.3", "medium", "muse"),
        ("muse-spark-1.3", "low", "muse"),
        ("muse-glimmer-30b", "none", "local"),
    ]
    assert [row.concurrency for row in r1b.MATRIX] == [4, 4, 4, 4, 1]


# Rows and hashes -------------------------------------------------------------


def test_product_row_carries_propose_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    code, results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    rows = _rows(results)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == 1
    assert row["case_id"] == "r1b-f01"
    assert row["arm"] == "product"
    assert row["model"] == "muse-wonder-1.0"
    assert row["effort"] == "high"
    assert row["attempt"] == 1
    assert row["execution"] == 1
    assert row["parsed_ok"] is True
    assert row["blocked"] is False
    assert row["codes"] == []
    assert row["transport"] == "scripted"
    assert row["gate_commit"] == "0" * 40
    assert row["gate_hash"] == "c" * 64
    expected = hashlib.sha256(made["muse"].requests[0].prompt.encode()).hexdigest()
    assert row["prompt_hash"] == expected


def test_plain_row_carries_sent_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    code, results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "plain",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    rows = _rows(results)
    assert len(rows) == 1
    sent = made["muse"].requests[0].prompt
    assert sent.startswith("You are writing a short briefing card for one goal.")
    assert sent != made["muse"].requests[0].prompt or True
    assert rows[0]["prompt_hash"] == hashlib.sha256(sent.encode()).hexdigest()
    assert "enum" not in json.dumps(made["muse"].requests[0].response_schema)


def test_row_carries_cached_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [
        ("text", _draft_for(cases[0])),
        ("cached", _draft_for(cases[1])),
    ]
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "2",
            "--concurrency",
            "1",
        ],
        script,
    )
    assert code == 0
    by_case = {row["case_id"]: row for row in _rows(results)}
    assert by_case["r1b-f01"]["cached_tokens"] is None
    assert by_case["r1b-f02"]["cached_tokens"] == 5


def test_wrapper_replaces_prompt_and_schema_independently() -> None:
    from evals.r1b_clients import SwappingWonderClient
    from framework.proposal.core import WonderRequest
    from framework.proposal.schemas import build_response_schema

    inner = ScriptedClient([("text", "{}"), ("text", "{}")])
    product_schema = build_response_schema(
        commitment_ids=["cm-1"],
        fact_ids=["fact:1"],
        snapshot_metric_ids=["calendar.busy_hours"],
        delta_metric_ids=[],
        has_facts=True,
        has_metrics=True,
        has_parent=False,
    )
    request = WonderRequest(
        prompt="PRODUCT PROMPT",
        model="m",
        effort="high",
        response_schema=product_schema,
    )
    prompt_only = SwappingWonderClient(
        inner, prompt_override="PLAIN PROMPT", schema_override=None
    )
    prompt_only.complete(request)
    assert inner.requests[0].prompt == "PLAIN PROMPT"
    assert inner.requests[0].response_schema == product_schema
    schema_only = SwappingWonderClient(
        inner, prompt_override=None, schema_override={"type": "object"}
    )
    schema_only.complete(request)
    assert inner.requests[1].prompt == "PRODUCT PROMPT"
    assert inner.requests[1].response_schema == {"type": "object"}


def test_retry_tail_kept_from_last_marker() -> None:
    from evals.r1b_clients import SwappingWonderClient
    from framework.proposal.core import WonderRequest

    inner = ScriptedClient([("text", "{}")])
    wrapper = SwappingWonderClient(inner, prompt_override="PLAIN", schema_override=None)
    outbound = (
        "PRODUCT\n\nPREVIOUS ATTEMPT FAILED\nold feedback\n\n"
        "PREVIOUS ATTEMPT FAILED\nnew feedback"
    )
    wrapper.complete(
        WonderRequest(prompt=outbound, model="m", effort="high", response_schema={})
    )
    assert inner.requests[0].prompt == "PLAIN\n\nPREVIOUS ATTEMPT FAILED\nnew feedback"


def test_retry_tail_byte_identical_through_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [
        ("text", _draft_for(cases[0], bad_number=True)),
        ("text", _draft_for(cases[0])),
    ]
    code, results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "plain",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    rows = _rows(results)
    assert [row["attempt"] for row in rows] == [1, 2]
    assert rows[0]["codes"] != []
    assert rows[1]["codes"] == []
    first, second = (r.prompt for r in made["muse"].requests)
    assert second.startswith(first.split("\n\nPREVIOUS ATTEMPT FAILED\n")[0])
    marker = "\n\nPREVIOUS ATTEMPT FAILED\n"
    assert second[len(first.split(marker)[0]) :].startswith(marker)


def test_throwaway_third_arm_runs_same_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    results = _clean_env(monkeypatch, tmp_path)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = ScriptedClient(script)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    registry = (*ARM_REGISTRY, ArmSpec("mixed", "plain", "product"))
    code = r1b.run_selection(
        cases=[cases[0]],
        arms=[spec for spec in registry if spec.name == "mixed"],
        model="muse-wonder-1.0",
        effort="high",
        route="muse",
        results_dir=results,
        concurrency=1,
        limit=None,
        stop_time=None,
        paired_prefix=False,
        registry=registry,
        client_factory=_factory,
        gate_commit="0" * 40,
        gate_hash="c" * 64,
        cases_sha256="x",
        cases_path=FIXTURE_PATH,
    )
    assert code == 0
    rows = _rows(results)
    assert len(rows) == 1
    assert rows[0]["arm"] == "mixed"
    assert set(rows[0]) == set(_rows(results)[0])
    sent = made["muse"].requests[0]
    assert sent.prompt.startswith("You are writing a short briefing card for one goal.")
    assert "enum" in json.dumps(sent.response_schema)


# Resume, unavailable, stop ----------------------------------------------------


def test_rerun_appends_nothing_for_finished_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0]))] * 4
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    files = list(results.glob("*.jsonl"))
    assert len(files) == 1
    before = files[0].read_text(encoding="utf-8")
    code, _results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    assert files[0].read_text(encoding="utf-8") == before


def test_unavailable_never_finishes_and_three_stop_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--concurrency",
            "1",
        ],
        [("unavailable", "timeout")] * 20,
    )
    assert code == 3
    rows = _rows(results)
    assert len(rows) == 3
    assert {row["case_id"] for row in rows} == {"r1b-f01", "r1b-f02", "r1b-f03"}
    assert all(
        ["MODEL_UNAVAILABLE", "timeout"] in [list(pair) for pair in row["codes"]]
        for row in rows
    )


def test_stop_time_guards_the_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import time as _time
    from datetime import UTC, datetime, timedelta

    from evals.r1b_summary import render_summary

    cases = load_cases(FIXTURE_PATH)

    class SlowFirstClient(ScriptedClient):
        def complete(self, request: Any) -> Any:
            if self.calls == 0:
                _time.sleep(0.3)
            return super().complete(request)

    script = [
        ("text", _draft_for(cases[0], bad_number=True)),
        ("text", _draft_for(cases[0])),
    ]
    results = _clean_env(monkeypatch, tmp_path)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = SlowFirstClient(script)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    stop = (datetime.now(UTC) + timedelta(seconds=0.05)).isoformat()
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
            "--stop-time",
            stop,
        ]
    )
    assert code == 0
    assert made["muse"].calls == 1
    rows = _rows(results)
    assert [row["attempt"] for row in rows] == [1, 2]
    assert rows[0]["codes"] != []
    assert [list(pair) for pair in rows[1]["codes"]] == [
        ["MODEL_UNAVAILABLE", "stop time"]
    ]
    text = render_summary(rows, list(cases))
    assert "first-draft failure whose retry came back unavailable: 1" in text


def test_no_new_call_starts_after_stop_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0]))] * 4
    code, _results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--stop-time",
            "2020-01-01T00:00:00+01:00",
        ],
        script,
    )
    assert code == 0
    assert made["muse"].calls == 0


# Refusals ---------------------------------------------------------------------


def test_contributor_refused_before_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0-contributor",
            "--effort",
            "high",
            "--arm",
            "product",
        ],
        [("text", "{}")],
    )
    assert code == 2
    assert made == {}
    assert list(results.glob("*.jsonl")) == []


def test_live_flag_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.delenv("IKIGAI_R1B_LIVE", raising=False)
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "m",
            "--effort",
            "high",
            "--arm",
            "product",
        ]
    )
    assert code == 2


def test_meta_key_refuses_muse_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("META_API_KEY", "synthetic")
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "m",
            "--effort",
            "high",
            "--arm",
            "product",
        ]
    )
    assert code == 2
    assert list(results.glob("*.jsonl")) == []


def test_auto_update_flag_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MUSE_NO_AUTO_UPDATE", "0")
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "m",
            "--effort",
            "high",
            "--arm",
            "product",
        ]
    )
    assert code == 2


def test_dirty_gate_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    results = _clean_env(monkeypatch, tmp_path)

    def _dirty() -> tuple[str, str]:
        raise r1b.GateIdentityError("dirty")

    monkeypatch.setattr(r1b, "gate_identity", _dirty)
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "m",
            "--effort",
            "high",
            "--arm",
            "product",
        ]
    )
    assert code == 2


def test_cases_hash_mismatch_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    monkeypatch.setattr(r1b, "FIXTURE_CASES_SHA256", "0" * 64)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "m",
            "--effort",
            "high",
            "--arm",
            "product",
        ]
    )
    assert code == 2
    assert list(results.glob("*.jsonl")) == []


# Local labelling ----------------------------------------------------------------


def test_local_row_labels_and_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(case)) for case in cases for _ in range(2)]
    results = _clean_env(monkeypatch, tmp_path)
    for key, value in (
        ("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1"),
        ("LOCAL_LLM_MODEL", "muse-glimmer-30b"),
        ("LOCAL_LLM_API_KEY", "synthetic"),
    ):
        monkeypatch.setenv(key, value)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        assert route == "local"
        assert llm_config is not None
        assert llm_config.model == "muse-glimmer-30b"
        client = ScriptedClient(script)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "muse-glimmer-30b",
            "--effort",
            "none",
            "--arm",
            "product",
            "--paired-prefix",
        ]
    )
    assert code == 0
    rows = [row for row in _rows(results) if row["model"] == "muse-glimmer-30b"]
    assert all(row["effort"] == "none" for row in rows)
    assert all(row["transport"] == "scripted" for row in rows)


def test_local_wrong_effort_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "muse-glimmer-30b",
            "--effort",
            "low",
            "--arm",
            "product",
        ]
    )
    assert code == 2
    assert "none" in capsys.readouterr().err


def test_local_concurrency_forced_to_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(r1b, "build_base_client", lambda route, llm_config=None: None)
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "muse-glimmer-30b",
            "--effort",
            "none",
            "--arm",
            "product",
            "--concurrency",
            "2",
        ]
    )
    assert code == 2


def test_all_without_local_vars_skips_local_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(case)) for case in cases for _ in range(8)]
    results = _clean_env(monkeypatch, tmp_path)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        assert route == "muse"
        client = made.get(route)
        if client is None:
            client = ScriptedClient(list(script))
            made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--all",
            "--limit",
            "1",
        ]
    )
    assert code == 0
    assert "local row was not run" in capsys.readouterr().out


def test_all_strips_local_vars_before_first_muse_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(case)) for case in cases for _ in range(8)]
    results = _clean_env(monkeypatch, tmp_path)
    for key, value in (
        ("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1"),
        ("LOCAL_LLM_MODEL", "muse-glimmer-30b"),
        ("LOCAL_LLM_API_KEY", "synthetic"),
    ):
        monkeypatch.setenv(key, value)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = made.get(route)
        if client is None:
            client = ScriptedClient(list(script))
            made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--all",
            "--limit",
            "1",
        ]
    )
    assert code == 0
    first = made["muse"].env_snapshots[0]
    assert not [key for key in first if key.startswith("LOCAL_LLM_")]


def test_local_row_runs_back_to_back_in_file_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(case)) for case in cases[:2] for _ in range(2)]
    results = _clean_env(monkeypatch, tmp_path)
    for key, value in (
        ("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1"),
        ("LOCAL_LLM_MODEL", "muse-glimmer-30b"),
        ("LOCAL_LLM_API_KEY", "synthetic"),
    ):
        monkeypatch.setenv(key, value)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = made.get(route)
        if client is None:
            if route == "local":
                client = ScriptedClient(list(script))
            else:
                client = ScriptedClient([("text", _draft_for(cases[0]))] * 40)
            made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--all",
            "--limit",
            "2",
        ]
    )
    assert code == 0
    rows = [row for row in _rows(results) if row["model"] == "muse-glimmer-30b"]
    pairs = [(row["case_id"], row["arm"]) for row in rows if row["attempt"] == 1]
    assert sorted(
        pairs, key=lambda pair: (pair[0], 0 if pair[1] == "product" else 1)
    ) == [
        ("r1b-f01", "product"),
        ("r1b-f01", "plain"),
        ("r1b-f02", "product"),
        ("r1b-f02", "plain"),
    ]
    recorded = made["local"].requests
    assert len(recorded) == 4
    plain_flags = [
        request.prompt.startswith("You are writing a short briefing card")
        for request in recorded
    ]
    assert plain_flags == [False, True, False, True]


def test_single_row_paired_prefix_runs_both_arms_back_to_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    code, results, made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--paired-prefix",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    pairs = [(row["case_id"], row["arm"]) for row in _rows(results)]
    assert sorted(
        pairs, key=lambda pair: (pair[0], 0 if pair[1] == "product" else 1)
    ) == [("r1b-f01", "product"), ("r1b-f01", "plain")]
    prompts = [request.prompt for request in made["muse"].requests]
    assert len(prompts) == 2
    assert not prompts[0].startswith("You are writing a short briefing card")
    assert prompts[1].startswith("You are writing a short briefing card")


def test_single_row_paired_prefix_needs_no_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--paired-prefix",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    pairs = [(row["case_id"], row["arm"]) for row in _rows(results)]
    assert sorted(
        pairs, key=lambda pair: (pair[0], 0 if pair[1] == "product" else 1)
    ) == [("r1b-f01", "product"), ("r1b-f01", "plain")]


def test_single_row_local_route_runs_both_arms_without_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    results = _clean_env(monkeypatch, tmp_path)
    for key, value in (
        ("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1"),
        ("LOCAL_LLM_MODEL", "muse-glimmer-30b"),
        ("LOCAL_LLM_API_KEY", "synthetic"),
    ):
        monkeypatch.setenv(key, value)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        assert route == "local"
        client = ScriptedClient(script)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--model",
            "muse-glimmer-30b",
            "--effort",
            "none",
            "--limit",
            "1",
        ]
    )
    assert code == 0
    pairs = [
        (row["case_id"], row["arm"])
        for row in _rows(results)
        if row["model"] == "muse-glimmer-30b"
    ]
    assert sorted(
        pairs, key=lambda pair: (pair[0], 0 if pair[1] == "product" else 1)
    ) == [("r1b-f01", "product"), ("r1b-f01", "plain")]


def test_all_first_exit_three_ends_whole_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = made.get(route)
        if client is None:
            client = ScriptedClient([("unavailable", "timeout")] * 40)
            made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--all",
            "--limit",
            "3",
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    assert "did not start" in out
    assert "arm plain" in out
    files = sorted(path.name for path in results.glob("*.jsonl"))
    assert files == ["muse-wonder-1.0__high__product__cccccccccccc.jsonl"]
    assert made["muse"].calls == 3


def _live_rows_for_regate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(case)) for case in cases[:1] for _ in range(2)]
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    return results


def test_regate_then_summary_prints_regated_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    results = _live_rows_for_regate(monkeypatch, tmp_path)
    monkeypatch.setattr(r1b, "DOC_PATH", tmp_path / "r1b.md")
    code = r1b.main(
        ["--cases", str(FIXTURE_PATH), "--results-dir", str(results), "--regate"]
    )
    assert code == 0
    regate_files = sorted(results.glob("regate__*.jsonl"))
    assert len(regate_files) == 1
    live_before = {
        path.name: path.read_text(encoding="utf-8")
        for path in results.glob("*.jsonl")
        if not path.name.startswith("regate__")
    }
    code = r1b.main(
        ["--cases", str(FIXTURE_PATH), "--results-dir", str(results), "--summary"]
    )
    assert code == 0
    doc = (tmp_path / "r1b.md").read_text(encoding="utf-8")
    assert "Re-gated rows" in doc
    assert "Live rows" in doc
    live_after = {
        path.name: path.read_text(encoding="utf-8")
        for path in results.glob("*.jsonl")
        if not path.name.startswith("regate__")
    }
    assert live_after == live_before


def test_regate_twice_appends_nothing_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _live_rows_for_regate(monkeypatch, tmp_path)
    args = ["--cases", str(FIXTURE_PATH), "--results-dir", str(results), "--regate"]
    assert r1b.main(args) == 0
    regate_file = next(results.glob("regate__*.jsonl"))
    before = regate_file.read_text(encoding="utf-8")
    assert r1b.main(args) == 0
    assert regate_file.read_text(encoding="utf-8") == before


def test_resume_ignores_regate_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = _live_rows_for_regate(monkeypatch, tmp_path)
    args = ["--cases", str(FIXTURE_PATH), "--results-dir", str(results)]
    assert r1b.main([*args, "--regate"]) == 0
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0]))] * 4
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = ScriptedClient(script)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    live_before = {
        path.name: path.read_text(encoding="utf-8")
        for path in results.glob("*.jsonl")
        if not path.name.startswith("regate__")
    }
    code = r1b.main(
        [
            *args,
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ]
    )
    assert code == 0
    assert sum(client.calls for client in made.values()) == 0
    live_after = {
        path.name: path.read_text(encoding="utf-8")
        for path in results.glob("*.jsonl")
        if not path.name.startswith("regate__")
    }
    assert live_after == live_before


def test_all_refuses_wrong_local_model_before_any_muse_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    results = _clean_env(monkeypatch, tmp_path)
    for key, value in (
        ("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1"),
        ("LOCAL_LLM_MODEL", "other-model"),
        ("LOCAL_LLM_API_KEY", "synthetic"),
    ):
        monkeypatch.setenv(key, value)
    made: dict[str, ScriptedClient] = {}

    def _factory(route: str, llm_config: Any = None) -> ScriptedClient:
        client = ScriptedClient([("unavailable", "x")] * 10)
        made[route] = client
        return client

    monkeypatch.setattr(r1b, "build_base_client", _factory)
    monkeypatch.setattr(r1b, "gate_identity", lambda: ("0" * 40, "c" * 64))
    code = r1b.main(
        [
            "--cases",
            str(FIXTURE_PATH),
            "--results-dir",
            str(results),
            "--all",
            "--limit",
            "1",
        ]
    )
    assert code == 2
    assert "muse-glimmer-30b" in capsys.readouterr().err
    assert made == {}
    assert list(results.glob("*.jsonl")) == []


def test_concurrency_below_one_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, _results, _made = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--arm", "product", "--concurrency", "0"],
        [("text", "{}")],
    )
    assert code == 2


def test_no_local_vars_leak_into_row_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases = load_cases(FIXTURE_PATH)
    script = [("text", _draft_for(cases[0])), ("text", _draft_for(cases[0]))]
    code, results, _made = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--arm",
            "product",
            "--limit",
            "1",
        ],
        script,
    )
    assert code == 0
    blob = "".join(path.read_text(encoding="utf-8") for path in results.glob("*.jsonl"))
    assert "127.0.0.1" not in blob
    assert "LOCAL_LLM" not in blob


# Gate identity, through the real function ------------------------------------


def _fake_git(
    *,
    status_stdout: str = "",
    status_code: int = 0,
    log_stdout: str = "",
    log_code: int = 0,
) -> Any:
    def _run(cmd: Any, **kwargs: Any) -> Any:
        _ = kwargs
        if list(cmd)[1] == "status":
            return r1b.subprocess.CompletedProcess(
                cmd, status_code, stdout=status_stdout
            )
        return r1b.subprocess.CompletedProcess(cmd, log_code, stdout=log_stdout)

    return _run


def test_gate_identity_refuses_dirty_gate_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r1b.subprocess,
        "run",
        _fake_git(
            status_stdout=" M framework/briefing/gate.py\n",
            log_stdout="a" * 40,
        ),
    )
    with pytest.raises(r1b.GateIdentityError):
        r1b.gate_identity()


def test_gate_identity_refuses_when_git_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r1b.subprocess, "run", _fake_git(status_stdout="", log_code=1))
    with pytest.raises(r1b.GateIdentityError):
        r1b.gate_identity()


def test_gate_identity_returns_commit_and_content_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12"
    monkeypatch.setattr(r1b.subprocess, "run", _fake_git(log_stdout=commit + "\n"))
    got_commit, got_hash = r1b.gate_identity()
    assert got_commit == commit
    expected = hashlib.sha256()
    for name in sorted(r1b.GATE_SOURCE_FILES):
        data = (REPO_ROOT / name).read_bytes()
        expected.update(name.encode() + b"\0" + data + b"\0")
    assert got_hash == expected.hexdigest()
