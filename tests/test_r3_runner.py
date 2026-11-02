"""Ticket 15b: R3 runner tests (D27, D36).

Scripted fake clients only: no network, no real ``muse`` binary, no
model call. The one real-wiring test injects a recording runner into
the default client factory.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals import gate_identity as identity
from evals import r3
from evals.r3 import load_pairs, scenario_for
from framework.glimmer.labels import INTERNAL_ONLY_LABELS
from framework.proposal.core import (
    MetaUnavailableError,
    ModelParams,
    OutboundBlocked,
    WonderResponse,
    propose,
)
from framework.proposal.muse_client import MuseExecClient

_PINNED_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_default_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the runner's default clock outside every quiet window and drain.

    Guard tests keep their own explicit clocks; the ticking-clock test
    keeps its own clock too. This only fixes the default both ``clock``
    and ``now`` fall back to, and asserts the guard lets a run start
    there so a slot-time move fails loudly.
    """
    from datetime import timedelta

    from evals.live_guard import quiet_windows, start_blocked

    monkeypatch.setattr(r3, "utc_now", lambda: _PINNED_NOW)
    assert (
        start_blocked(
            _PINNED_NOW,
            quiet_windows(_PINNED_NOW, 25, 5),
            timedelta(minutes=10),
            None,
        )
        is None
    )


class ScriptedClient:
    """Replay scripted outcomes; thread-safe for concurrent repeats."""

    transport = "scripted"
    transport_version: str | None = "scripted-1"
    harness_rules_file: bool | None = False

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self._script = list(script)
        self._lock = threading.Lock()
        self.requests: list[Any] = []
        self.calls = 0

    def complete(self, request: Any) -> Any:
        with self._lock:
            self.requests.append(request)
            index = self.calls
            self.calls += 1
            if index >= len(self._script):
                raise AssertionError("client called more times than scripted")
            kind, payload = self._script[index]
        if kind == "unavailable":
            raise MetaUnavailableError(payload or "timeout", latency_ms=3)
        if kind == "blocked":
            raise OutboundBlocked((payload,))
        return WonderResponse(
            text=payload,
            model_reported="scripted-client",
            latency_ms=7,
            finish_reason="stop",
            prompt_tokens=11,
            completion_tokens=13,
            reasoning_tokens=None,
            cached_tokens=None,
        )


class AlwaysUnavailableClient(ScriptedClient):
    def __init__(self) -> None:
        super().__init__([])

    def complete(self, request: Any) -> Any:
        self.requests.append(request)
        self.calls += 1
        raise MetaUnavailableError("timeout", latency_ms=3)


_STATEMENT_FAMILIES = (
    ("Pushes", "pushes"),
    ("Programming screen hours", "screen_hours.Work/Programming"),
    ("Video screen hours", "screen_hours.Media/Video"),
    ("Chat screen hours", "screen_hours.Comms/Chat"),
    ("iki-family calendar hours", "tag_hours.iki-family"),
)


def _metric_ids_for(statement: str, metrics: dict[str, Any]) -> list[str]:
    if "feed items" in statement:
        sub = sorted(
            metric_id
            for metric_id in metrics
            if metric_id.startswith("feed.item.count.")
            and metric_id.removeprefix("feed.item.count.").lower() in statement.lower()
        )
        if sub:
            return sub
        return ["feed.item.count"]
    for start, family in _STATEMENT_FAMILIES:
        if statement.startswith(start):
            ids = []
            for period in ("earlier", "prior", "last"):
                if re.search(rf"\b{period}\b", statement):
                    ids.append(f"period.{period}.{family}")
            assert ids, statement
            return ids
    raise AssertionError(f"statement matches no family: {statement!r}")


def passing_draft(scenario: dict[str, Any], profile: str) -> str:
    """A gate-passing draft for the scenario's first fact, like _gate_shell."""
    fact = scenario["facts"][0]
    metric_ids = _metric_ids_for(str(fact["statement"]), scenario["metrics"])
    commitment = next(
        c["id"] for c in scenario["commitments"] if c["profile"] == profile
    )
    return json.dumps(
        {
            "commitment_id": commitment,
            "overall_state": [
                {
                    "text": fact["statement"],
                    "fact_ids": [fact["id"]],
                    "metric_refs": metric_ids,
                }
            ],
            "working": [],
            "not_working": [],
            "since_last": [],
        }
    )


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path | None = None) -> None:
    monkeypatch.setenv("IKIGAI_R3_LIVE", "1")
    monkeypatch.setenv("MUSE_NO_AUTO_UPDATE", "1")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("HIDDEN_CRITERIA_DIR", raising=False)
    if tmp_path is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
    factory: Any,
    **kwargs: Any,
) -> tuple[int, Path]:
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        ["--results-dir", str(results), *args], client_factory=factory, **kwargs
    )
    return code, results


def _rows(results: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _slot_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (str(row["pair_id"]), str(row["arm"]), int(row["repeat"]))


def test_disabled_without_live_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.delenv("IKIGAI_R3_LIVE", raising=False)
    results = tmp_path / "r3"
    calls: list[Any] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code = r3.main(
        [
            "--model",
            "muse-wonder-1.0",
            "--effort",
            "high",
            "--repeats",
            "3",
            "--results-dir",
            str(results),
        ],
        client_factory=_factory,
    )
    assert code == 0
    assert "disabled" in capsys.readouterr().out
    assert calls == []
    assert not results.exists()


def test_row_carries_identity_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory_calls: list[int] = []

    def _factory() -> Any:
        factory_calls.append(1)
        return ScriptedClient([("text", "{}"), ("text", "{}")] * 10)

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "1"],
        _factory,
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 1
    row = rows[0]
    gate_commit, gate_hash = identity.gate_identity()
    assert row["gate_commit"] == gate_commit
    assert row["gate_hash"] == gate_hash
    assert row["prompt_sha256"] == identity.prompt_identity()
    assert row["closure_sha256"] == identity.closure_identity()
    _doc, pairs_sha = load_pairs()
    assert row["pairs_sha256"] == pairs_sha
    assert row["model"] == "m"
    assert row["effort"] == "high"
    assert row["transport"] == "scripted"
    assert row["muse_version"] == "scripted-1"
    assert row["harness_rules_file"] is False
    assert row["muse_no_auto_update"] is True
    assert row["tree_commit"] == identity.tree_identity()[0]
    assert isinstance(row["tree_dirty"], bool)
    assert row["pair_id"] == "D1"
    assert row["arm"] == "base"
    assert row["repeat"] == 1
    assert row["execution"] == 1
    assert row["start_seq"] == 1
    assert row["drawn"] is True
    assert len(row["attempts"]) == 2
    assert row["timeout_retries"] == 0
    assert row["local_retries"] == []
    assert factory_calls != []


def test_row_records_timeout_retries_beside_local_retries() -> None:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "D1")
    inner = ScriptedClient([("text", "{}"), ("text", "{}")])
    inner.failures = ()  # type: ignore[attr-defined]
    inner.retries = 1  # type: ignore[attr-defined]

    row = r3.run_repeat(
        pair=pair,
        arm="base",
        repeat=1,
        execution=1,
        start_seq=1,
        scenario=scenario_for(doc, pair, "base"),
        model="m",
        effort="high",
        client=inner,
        static={"model": "m", "effort": "high"},
        recorded_at="2026-11-03T10:00:00+00:00",
    )
    assert row["timeout_retries"] == 1
    assert row["local_retries"] == []


def test_limit_smoke_then_resume_never_repeats_drawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = [("text", "{}"), ("text", "{}")] * 10

    def _factory() -> Any:
        return ScriptedClient(script)

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "2"],
        _factory,
    )
    assert code == 4
    assert len(_rows(results)) == 2
    code, _results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "3"],
        _factory,
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 5
    assert all(int(row["execution"]) == 1 for row in rows)
    assert len({_slot_key(row) for row in rows}) == 5


def test_unavailable_then_success_draws_on_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "D1")
    draft = passing_draft(scenario_for(doc, pair, "base"), "builder")
    shared = ScriptedClient([("unavailable", "timeout"), ("text", draft)])

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "1", "--concurrency", "1"],
        _factory,
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 1
    assert rows[0]["drawn"] is False
    code, _results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "1", "--concurrency", "1"],
        _factory,
    )
    assert code == 4
    rows = _rows(results)
    assert [int(row["execution"]) for row in rows] == [1, 2]
    assert [bool(row["drawn"]) for row in rows] == [False, True]
    assert rows[1]["pick"] == "b-ship"
    assert rows[1]["unavailable_reason"] is None
    assert rows[0]["unavailable_reason"] == "timeout"


def test_three_unavailable_executions_exhaust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _factory() -> Any:
        return AlwaysUnavailableClient()

    args = ["--model", "m", "--effort", "high", "--limit", "1", "--concurrency", "1"]
    results = tmp_path / "r3"
    for _ in range(3):
        code, _seen = _run(monkeypatch, tmp_path, args, _factory)
        assert code == 4
    rows = _rows(results)
    assert [int(row["execution"]) for row in rows] == [1, 2, 3]
    assert all(row["drawn"] is False for row in rows)
    code, _seen = _run(monkeypatch, tmp_path, args, _factory)
    assert code == 4
    rows = _rows(results)
    slot1 = [row for row in rows if _slot_key(row) == ("D1", "base", 1)]
    assert len(slot1) == 3
    assert len(rows) == 4


def test_retry_unavailable_keeps_fallback_and_never_reruns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = [
        ("text", "{}"),
        ("unavailable", "timeout"),
        ("text", "{}"),
        ("text", "{}"),
    ]

    def _factory() -> Any:
        return ScriptedClient(script)

    args = ["--model", "m", "--effort", "high", "--limit", "1", "--concurrency", "1"]
    code, results = _run(monkeypatch, tmp_path, args, _factory)
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 1
    assert rows[0]["drawn"] is True
    assert rows[0]["result_kind"] == "fallback"
    code, _results = _run(monkeypatch, tmp_path, args, _factory)
    assert code == 4
    rows = _rows(results)
    slot1 = [row for row in rows if _slot_key(row) == ("D1", "base", 1)]
    assert len(slot1) == 1
    assert len(rows) == 2


def test_blocked_never_reruns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _factory() -> Any:
        return ScriptedClient([("blocked", "L1_TEST_BLOCK")] * 10)

    args = ["--model", "m", "--effort", "high", "--limit", "1", "--concurrency", "1"]
    code, results = _run(monkeypatch, tmp_path, args, _factory)
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 1
    assert rows[0]["drawn"] is True
    assert rows[0]["result_kind"] == "noop"
    assert rows[0]["pick"] is None
    code, _results = _run(monkeypatch, tmp_path, args, _factory)
    assert code == 4
    rows = _rows(results)
    assert len([row for row in rows if _slot_key(row) == ("D1", "base", 1)]) == 1


def test_three_consecutive_unavailable_stop_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _factory() -> Any:
        return AlwaysUnavailableClient()

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--concurrency", "1"],
        _factory,
    )
    assert code == 3
    assert len(_rows(results)) == 3


def test_unavailable_stop_fires_at_concurrency_4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _factory() -> Any:
        return AlwaysUnavailableClient()

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--concurrency", "4", "--no-quiet-guard"],
        _factory,
    )
    assert code == 3
    rows = _rows(results)
    assert 3 <= len(rows) <= 12
    assert all(row["drawn"] is False for row in rows)
    assert all(row["unavailable_reason"] == "timeout" for row in rows)


def test_full_run_with_one_slot_left_exits_4_then_resume_draws_it_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = [("unavailable", "timeout")]
    script += [("text", "{}"), ("text", "{}")] * 240
    shared = ScriptedClient(script)

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--concurrency", "1", "--no-quiet-guard"],
        _factory,
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 120
    left = [row for row in rows if not bool(row["drawn"])]
    assert len(left) == 1

    def _draw_factory() -> Any:
        return ScriptedClient([("text", "{}"), ("text", "{}")] * 4)

    code, _resumed = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--concurrency", "1", "--no-quiet-guard"],
        _draw_factory,
    )
    assert code == 0
    assert len(_rows(results)) == 121


class _RecordingBlockedClient:
    """Record the request, then stop at the outbound scan: one attempt."""

    transport = "recording"
    transport_version: str | None = "recording-1"
    harness_rules_file: bool | None = False

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def complete(self, request: Any) -> Any:
        self.requests.append(request)
        raise OutboundBlocked(("L1_TEST_BLOCK",))


def _propose_request(scenario: dict[str, Any], profile: str) -> Any:
    """The prompt-diff test's own propose call for one scenario."""
    materials = r3.build_slot_materials(scenario, profile)
    client = _RecordingBlockedClient()
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


def test_repeat_sends_policy_free_prompt_byte_equal_to_propose() -> None:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "D1")
    scenario = scenario_for(doc, pair, "base")
    client = _RecordingBlockedClient()
    row = r3.run_repeat(
        pair=pair,
        arm="base",
        repeat=1,
        execution=1,
        start_seq=1,
        scenario=scenario,
        model="m",
        effort="high",
        client=client,
        static={"model": "m", "effort": "high"},
        recorded_at="2026-11-03T10:00:00+00:00",
    )
    assert len(client.requests) == 1
    via_repeat = client.requests[0].prompt
    assert "POLICY_DATA" not in via_repeat
    assert _propose_request(scenario, str(pair["profile"])).prompt == via_repeat
    assert row["result_kind"] == "noop"


def test_internal_only_labels_carried_and_blocked_before_runner() -> None:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "D1")
    scenario = scenario_for(doc, pair, "base")
    materials = r3.build_slot_materials(scenario, str(pair["profile"]))
    assert INTERNAL_ONLY_LABELS
    assert materials.context.forbidden_raw_literals == tuple(
        sorted(INTERNAL_ONLY_LABELS)
    )
    label = min(INTERNAL_ONLY_LABELS)
    tainted = scenario_for(doc, pair, "base")
    tainted["facts"][0]["statement"] = (
        f"Pushes were 2 in earlier, 2 in prior and 2 in last {label}."
    )
    tainted_materials = r3.build_slot_materials(tainted, str(pair["profile"]))
    calls: list[Any] = []

    def _runner(argv: Any, *, env: Any, timeout_s: float, cwd: Any) -> Any:
        calls.append(argv)
        raise AssertionError("runner must not run on a blocked prompt")

    result = propose(
        profile_id=str(pair["profile"]),
        subject_id="subject-1",
        slot=tainted_materials.slot,
        as_of=tainted_materials.slot,
        cycle_id="r3-test",
        run=1,
        hour=tainted_materials.hour,
        eligible=tainted_materials.eligible,
        context=tainted_materials.context,
        client=MuseExecClient(
            private_terms=(), private_terms_available=True, runner=_runner
        ),
        models=ModelParams("muse-wonder-1.0", "high", "muse-wonder-1.0", "high"),
        policy="",
        stale_after_s=12 * 3600.0,
        cycle_as_of=tainted_materials.slot,
        offered={},
    )
    assert result.kind == "noop"
    assert "NOOP_OUTBOUND_BLOCKED" in result.reason_codes
    # The scan fires before any prompt-carrying runner call: the only
    # runner traffic the block path allows is the `muse --version` probe
    # that recording the blocked attempt performs.
    assert all(argv[-1] == "--version" for argv in calls)
    assert not any("exec" in argv for argv in calls)


def test_i8_hour_line_both_instants_utc_and_equal_to_base() -> None:
    from datetime import timedelta

    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "I8")
    base = _propose_request(scenario_for(doc, pair, "base"), str(pair["profile"]))
    perturbed = _propose_request(
        scenario_for(doc, pair, "perturbed"), str(pair["profile"])
    )
    assert base.prompt != perturbed.prompt

    def _hour_bounds(prompt: str) -> tuple[str, str]:
        line = next(text for text in prompt.splitlines() if text.startswith("HOUR:"))
        start_raw, end_raw = line.removeprefix("HOUR: ").split(" to ")
        return start_raw, end_raw

    base_start_raw, base_end_raw = _hour_bounds(base.prompt)
    pert_start_raw, pert_end_raw = _hour_bounds(perturbed.prompt)
    assert pert_start_raw.endswith("+00:00")
    assert pert_end_raw.endswith("+00:00")
    pert_start = datetime.fromisoformat(pert_start_raw)
    pert_end = datetime.fromisoformat(pert_end_raw)
    assert pert_start.utcoffset() == timedelta(0)
    assert pert_end.utcoffset() == timedelta(0)
    assert pert_start == datetime.fromisoformat(base_start_raw)
    assert pert_end == datetime.fromisoformat(base_end_raw)


def test_retry_request_names_same_model_and_effort() -> None:
    doc, _sha = load_pairs()
    pair = next(p for p in doc["pairs"] if p["id"] == "D1")
    client = ScriptedClient([("text", "{}"), ("text", "{}")])
    row = r3.run_repeat(
        pair=pair,
        arm="base",
        repeat=1,
        execution=1,
        start_seq=1,
        scenario=scenario_for(doc, pair, "base"),
        model="m",
        effort="high",
        client=client,
        static={"model": "m", "effort": "high"},
        recorded_at="2026-11-03T10:00:00+00:00",
    )
    assert len(row["attempts"]) == 2
    assert len(client.requests) == 2
    assert client.requests[0].model == client.requests[1].model == "m"
    assert client.requests[0].effort == client.requests[1].effort == "high"


def test_stop_time_in_past_with_no_quiet_guard_stops_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, results = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--stop-time",
            "2000-01-01T00:00:00+00:00",
            "--no-quiet-guard",
        ],
        _factory,
    )
    assert code == 4
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_second_run_on_locked_results_file_exits_2_with_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    import fcntl

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    results.mkdir()
    gate_hash = identity.gate_identity()[1]
    name = r3.results_filename(
        "m", "high", gate_hash, identity.prompt_identity(), identity.closure_identity()
    )
    target = results / name
    target.write_text("", encoding="utf-8")
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    with open(target, "a", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        code = r3.main(
            ["--model", "m", "--effort", "high", "--results-dir", str(results)],
            client_factory=_factory,
        )
    assert code == 2
    assert calls == []
    captured = capsys.readouterr()
    lines = (captured.out + captured.err).strip().splitlines()
    assert len(lines) == 1


def test_recorded_at_is_read_after_the_repeat_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datetime import timedelta

    current = [datetime(2026, 11, 2, 12, 0, tzinfo=UTC)]

    class _Advancing(ScriptedClient):
        def complete(self, request: Any) -> Any:
            current[0] = current[0] + timedelta(seconds=60)
            return super().complete(request)

    def _factory() -> Any:
        return _Advancing([("text", "{}"), ("text", "{}")] * 4)

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(results),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
        clock=lambda: current[0],
        now=lambda: current[0],
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 1
    assert rows[0]["recorded_at"] == current[0].isoformat()


def test_muse_versions_are_deduplicated_in_summary_info() -> None:
    base = {
        "gate_commit": "a" * 40,
        "gate_hash": "b" * 64,
        "prompt_sha256": "c" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commit": "a" * 40,
        "model": "m",
        "effort": "high",
        "transport": "muse",
        "muse_version": "muse 1.4.14",
        "harness_rules_file": False,
        "recorded_at": "2026-11-03T10:00:00+00:00",
        "attempts": [],
        "local_retries": [],
    }
    info = r3._summary_info([dict(base) for _ in range(3)])
    assert info["muse_versions"] == ["muse 1.4.14"]


def test_quiet_window_exit_4_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    madrid = ZoneInfo("Europe/Madrid")
    clock = lambda: datetime(2026, 11, 3, 15, 30, tzinfo=madrid)
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        ["--model", "m", "--effort", "high", "--results-dir", str(results)],
        client_factory=_factory,
        clock=clock,
    )
    assert code == 4
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_stop_time_exit_4_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, results = _run(
        monkeypatch,
        tmp_path,
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--stop-time",
            "2000-01-01T00:00:00+00:00",
        ],
        _factory,
    )
    assert code == 4
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


@pytest.mark.parametrize(
    "extra_env,extra_args",
    [
        ({"META_API_KEY": "x"}, []),
        ({"MUSE_NO_AUTO_UPDATE": None}, []),
        ({}, ["--repeats", "2"]),
    ],
)
def test_refusals_make_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
    extra_env: dict[str, str | None],
    extra_args: list[str],
) -> None:
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    _clean_env(monkeypatch, tmp_path)
    for key, value in extra_env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    results = tmp_path / "r3"
    code = r3.main(
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--results-dir",
            str(results),
            *extra_args,
        ],
        client_factory=_factory,
    )
    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_rules_file_refusal_and_allow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    xdg = tmp_path / "xdg"
    (xdg / "muse").mkdir(parents=True)
    (xdg / "muse" / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    def _factory() -> Any:
        return ScriptedClient([("text", "{}"), ("text", "{}")] * 4)

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "1"],
        _factory,
    )
    assert code == 2
    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--model", "m", "--effort", "high", "--limit", "1", "--allow-rules-file"],
        _factory,
    )
    assert code == 4
    assert len(_rows(results)) == 1


def test_dirty_nine_refuses_in_temp_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    for name in (*identity.GATE_SOURCE_FILES, identity.PROMPT_SOURCE_FILE):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"contents of {name}\n", encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    first = next(iter(identity.GATE_SOURCE_FILES))
    (repo / first).write_text("changed\n", encoding="utf-8")
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        ["--model", "m", "--effort", "high", "--results-dir", str(results)],
        client_factory=_factory,
        root=repo,
    )
    assert code == 2
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_pairs_hash_mismatch_on_resume_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    results.mkdir()
    gate_commit, gate_hash = identity.gate_identity()
    name = r3.results_filename(
        "m", "high", gate_hash, identity.prompt_identity(), identity.closure_identity()
    )
    row = {
        "pair_id": "D1",
        "arm": "base",
        "repeat": 1,
        "execution": 1,
        "drawn": True,
        "model": "m",
        "effort": "high",
        "gate_commit": gate_commit,
        "gate_hash": gate_hash,
        "prompt_sha256": identity.prompt_identity(),
        "pairs_sha256": "0" * 64,
    }
    (results / name).write_text(
        json.dumps(row, sort_keys=True) + "\n", encoding="utf-8"
    )
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code = r3.main(
        ["--model", "m", "--effort", "high", "--results-dir", str(results)],
        client_factory=_factory,
    )
    assert code == 2
    assert calls == []
    assert len((results / name).read_text(encoding="utf-8").splitlines()) == 1


def test_sentinel_hidden_criteria_dir_unread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixed = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    script = [("text", "{}"), ("text", "{}")] * 4

    def _factory() -> Any:
        return ScriptedClient(script)

    seen: list[list[Any]] = []

    def _recording_factory() -> Any:
        client = ScriptedClient(script)
        seen.append(client.requests)
        return client

    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", "/nonexistent-r3-sentinel-xyz")
    first_results = tmp_path / "first"
    code = r3.main(
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(first_results),
        ],
        client_factory=_recording_factory,
        now=lambda: fixed,
    )
    assert code == 4
    terms = tmp_path / "terms"
    terms.mkdir()
    sentinel = terms / "deny-terms.txt"
    sentinel.write_text("forbiddenphrase\n", encoding="utf-8")
    before = sentinel.read_bytes()
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(terms))
    second_results = tmp_path / "second"
    code = r3.main(
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(second_results),
        ],
        client_factory=_recording_factory,
        now=lambda: fixed,
    )
    assert code == 4
    assert sentinel.read_bytes() == before
    assert [r.prompt for r in seen[0]] == [r.prompt for r in seen[1]]
    first_rows = [
        json.loads(line)
        for path in sorted(first_results.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    second_rows = [
        json.loads(line)
        for path in sorted(second_results.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert first_rows == second_rows


def test_default_factory_builds_the_real_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.cycle.orchestrator import WONDER_TIMEOUT_S
    from framework.proposal.core import WonderRequest
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import MuseExecClient, RunResult
    from framework.proposal.timeout_retry import TimeoutRetryClient

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    seen: list[dict[str, Any]] = []

    def _runner(argv: Any, *, env: Any, timeout_s: float, cwd: Any) -> RunResult:
        seen.append({"argv": list(argv), "env": dict(env), "timeout_s": timeout_s})
        if list(argv)[-1] == "--version":
            return RunResult(returncode=0, stdout=b"muse 1.4.14\n", timed_out=False)
        body = (
            b'{"payload": {"kind": "run_usage", "models": '
            b'[{"model": "muse-wonder-1.0", "input_tokens": 10, '
            b'"output_tokens": 5}]}}\n'
            b'{"payload": {"kind": "task_lifecycle", "event": {"kind": "status", '
            b'"details": {"phase": "stream_succeeded", "facets": [{"kind": '
            b'"producer", "detail": {"kind": "provider", "model": '
            b'"muse-wonder-1.0", "provider": "meta"}}]}}}}\n'
            b'{"payload": {"kind": "run_terminal", "terminal": "completed", '
            b'"text": "{\\"a\\": 1}"}}\n'
        )
        return RunResult(returncode=0, stdout=body, timed_out=False)

    monkeypatch.setenv("META_API_KEY", "sentinel-key")
    client = r3.default_client_factory(runner=_runner)
    assert isinstance(client, TimeoutRetryClient)
    assert isinstance(client._inner, LocalRetryClient)
    assert isinstance(client._inner._inner, MuseExecClient)
    assert client._min_seconds_left == WONDER_TIMEOUT_S
    assert client._inner._seconds_left is None
    response = client.complete(
        WonderRequest(
            prompt="hello",
            model="muse-wonder-1.0",
            effort="high",
            response_schema={},
        )
    )
    assert response.text == '{"a": 1}'
    assert response.model_reported == "muse-wonder-1.0"
    exec_calls = [call for call in seen if "--version" not in call["argv"]]
    assert len(exec_calls) == 1
    argv = exec_calls[0]["argv"]
    assert "--preset" in argv and argv[argv.index("--preset") + 1] == "empty"
    assert "--contributor-mode" in argv
    assert argv[argv.index("--contributor-mode") + 1] == "off"
    assert exec_calls[0]["timeout_s"] == 120.0
    assert "META_API_KEY" not in exec_calls[0]["env"]


def test_summary_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    def _factory() -> Any:
        return ScriptedClient([("text", "{}"), ("text", "{}")] * 6)

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        [
            "--model",
            "m-one",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(results),
        ],
        client_factory=_factory,
    )
    assert code == 4
    code = r3.main(
        [
            "--model",
            "m-two",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(results),
        ],
        client_factory=_factory,
    )
    assert code == 4
    assert len(list(results.glob("*.jsonl"))) == 2

    code = r3.main(["--summary", "--results-dir", str(results)])
    assert code == 0
    out = capsys.readouterr().out
    assert "m-two" in out

    _gate_commit, gate_hash = identity.gate_identity()
    code = r3.main(
        ["--summary", "--results-dir", str(results), "--identity", gate_hash[:12]]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert ".jsonl" in err

    code = r3.main(
        ["--summary", "--results-dir", str(results), "--identity", "deadbeef"]
    )
    assert code == 2

    code = r3.main(["--summary", "--results-dir", str(results)])
    first_text = capsys.readouterr().out
    assert code == 0
    doc_path = tmp_path / "r3.md"
    monkeypatch.setattr(r3, "DOC_PATH", doc_path)
    code = r3.main(["--summary", "--results-dir", str(results), "--write-doc"])
    second_text = capsys.readouterr().out
    assert code == 0
    assert doc_path.read_text(encoding="utf-8") == second_text == first_text


def test_results_filename_carries_closure_part() -> None:
    gate_hash = "a" * 64
    prompt_sha = "b" * 64
    closure_sha = "c" * 64
    assert r3.results_filename("m", "high", gate_hash, prompt_sha, closure_sha) == (
        "m__high__g" + "a" * 12 + "__p" + "b" * 12 + "__c" + "c" * 12 + ".jsonl"
    )
    assert r3.results_filename("m", "high", gate_hash, prompt_sha) == (
        "m__high__g" + "a" * 12 + "__p" + "b" * 12 + ".jsonl"
    )


def test_new_closure_writes_new_file_never_resumes_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    results.mkdir()
    gate_commit, gate_hash = identity.gate_identity()
    prompt_sha = identity.prompt_identity()
    closure_sha = identity.closure_identity()
    _doc, pairs_sha = load_pairs()
    old_name = r3.results_filename("m", "high", gate_hash, prompt_sha)
    old_row = {
        "pair_id": "D1",
        "arm": "base",
        "repeat": 1,
        "execution": 1,
        "drawn": True,
        "model": "m",
        "effort": "high",
        "gate_commit": gate_commit,
        "gate_hash": gate_hash,
        "prompt_sha256": prompt_sha,
        "pairs_sha256": pairs_sha,
    }
    (results / old_name).write_text(
        json.dumps(old_row, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = (results / old_name).read_text(encoding="utf-8")

    def _factory() -> Any:
        return ScriptedClient([("text", "{}"), ("text", "{}")] * 4)

    code = r3.main(
        [
            "--model",
            "m",
            "--effort",
            "high",
            "--limit",
            "1",
            "--results-dir",
            str(results),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
    )
    assert code == 4
    assert (results / old_name).read_text(encoding="utf-8") == before
    new_name = r3.results_filename("m", "high", gate_hash, prompt_sha, closure_sha)
    assert new_name != old_name
    new_rows = [
        json.loads(line)
        for line in (results / new_name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(new_rows) == 1
    assert new_rows[0]["closure_sha256"] == closure_sha


def test_dirty_closure_only_file_refuses_in_temp_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    helper = "framework/proposal/hour.py"
    for name in (*identity.GATE_SOURCE_FILES, identity.PROMPT_SOURCE_FILE):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == next(iter(identity.GATE_SOURCE_FILES)):
            path.write_text(
                "from framework.proposal.hour import fallback_window_codes\n"
                "VALUE = 1\n",
                encoding="utf-8",
            )
        else:
            path.write_text(f"contents of {name}\n", encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=repo, check=True)
    helper_path = repo / helper
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(
        "def fallback_window_codes():\n    return ()\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", helper], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    assert helper in identity.closure_files(repo)
    helper_path.write_text(
        "def fallback_window_codes():\n    return ('changed',)\n", encoding="utf-8"
    )
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r3"
    code = r3.main(
        ["--model", "m", "--effort", "high", "--results-dir", str(results)],
        client_factory=_factory,
        root=repo,
    )
    assert code == 2
    assert calls == []
    assert list(results.glob("*.jsonl")) == []
