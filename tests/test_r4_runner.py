"""Ticket 15b, Step 5: R4 runner tests (D41, D45).

Scripted fake clients only: no network, no real ``muse`` binary, no
model call. Hand-written R3 rows live in temp dirs, never in
``evals/results/``.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals import gate_identity as identity
from evals import r3, r4
from evals.r3 import load_pairs
from evals.r4_scenario import build_cases
from framework.proposal.core import (
    MetaUnavailableError,
    ModelParams,
    OutboundBlocked,
    WonderResponse,
    propose,
)
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL

_PINNED_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_default_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the runner's default clock outside every quiet window and drain.

    Guard tests keep their own explicit clocks; ticking-clock tests keep
    theirs too. This only fixes the default both ``clock`` and ``now``
    fall back to, and asserts the guard lets a run start there so a
    slot-time move fails loudly.
    """
    from datetime import timedelta

    from evals.live_guard import quiet_windows, start_blocked

    monkeypatch.setattr(r4, "utc_now", lambda: _PINNED_NOW)
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


def _draft(pick: str, fact: str = "f1") -> str:
    return json.dumps(
        {
            "commitment_id": pick,
            "overall_state": [
                {
                    "text": f"Something about {fact} holds here",
                    "fact_ids": [fact],
                    "metric_refs": [],
                }
            ],
            "working": [],
            "not_working": [],
            "since_last": [],
        }
    )


def _r3_row(
    pair_id: str,
    profile: str,
    arm: str,
    repeat: int,
    raw: str,
    *,
    execution: int = 1,
    drawn: bool = True,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> dict[str, Any]:
    gate_commit, gate_hash = identity.gate_identity()
    _doc, pairs_sha = load_pairs()
    return {
        "pair_id": pair_id,
        "arm": arm,
        "repeat": repeat,
        "execution": execution,
        "drawn": drawn,
        "unavailable_reason": None if drawn else "timeout",
        "prompt_hash": "p" * 64,
        "profile": profile,
        "model": model,
        "effort": effort,
        "gate_commit": gate_commit,
        "gate_hash": gate_hash,
        "prompt_sha256": identity.prompt_identity(),
        "pairs_sha256": pairs_sha,
        "attempts": [{"raw_text": raw}],
    }


def _complete_r3_rows() -> list[dict[str, Any]]:
    """Every R3 slot drawn: the full 20-pair x 2-arm x 3-repeat matrix."""
    doc, _sha = load_pairs()
    rows: list[dict[str, Any]] = []
    for pair in doc["pairs"]:
        profile = str(pair["profile"])
        pick = "b-ship" if profile == "builder" else "d-family"
        for arm in ("base", "perturbed"):
            for repeat in (1, 2, 3):
                rows.append(
                    _r3_row(str(pair["id"]), profile, arm, repeat, _draft(pick))
                )
    return rows


def _write_r3_file(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path | None = None) -> None:
    monkeypatch.setenv("IKIGAI_R4_LIVE", "1")
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
    r3_path: Path,
    **kwargs: Any,
) -> tuple[int, Path]:
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r4"
    code = r4.main(
        [
            "--results-dir",
            str(results),
            "--r3-file",
            str(r3_path),
            "--no-quiet-guard",
            *args,
        ],
        client_factory=factory,
        **kwargs,
    )
    return code, results


def _rows(results: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_disabled_without_live_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.delenv("IKIGAI_R4_LIVE", raising=False)
    results = tmp_path / "r4"
    calls: list[Any] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code = r4.main(
        ["--results-dir", str(results)],
        client_factory=_factory,
    )
    assert code == 0
    assert capsys.readouterr().out.strip().startswith("disabled")
    assert calls == []
    assert not results.exists()


def test_default_factory_is_the_shared_r3_stack() -> None:
    from framework.cycle.orchestrator import WONDER_TIMEOUT_S
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import MuseExecClient
    from framework.proposal.timeout_retry import TimeoutRetryClient

    assert r4.default_client_factory is r3.default_client_factory
    client = r4.default_client_factory()
    assert isinstance(client, TimeoutRetryClient)
    assert isinstance(client._inner, LocalRetryClient)
    assert isinstance(client._inner._inner, MuseExecClient)
    assert client._inner._inner._timeout_s == 120.0
    assert client._min_seconds_left == WONDER_TIMEOUT_S
    assert client._inner._seconds_left is None


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


def test_first_attempt_request_equals_propose_for_both_arms() -> None:
    doc, _sha = load_pairs()
    cases = build_cases(_complete_r3_rows(), doc)
    case = next(c for c in cases if c.profile == "builder")
    for arm in ("cited", "control"):
        scenario = r4.arm_scenario(doc, case, arm)
        materials = r3.build_slot_materials(scenario, case.profile)
        request = r4.first_attempt_request(materials, case.profile, "m", "high")
        client = _RecordingBlockedClient()
        propose(
            profile_id=case.profile,
            subject_id="subject-1",
            slot=materials.slot,
            as_of=materials.slot,
            cycle_id="r4-test",
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
        via_propose = client.requests[0]
        assert request.prompt == via_propose.prompt
        assert request.response_schema == via_propose.response_schema
        assert request.forbidden_raw_literals == via_propose.forbidden_raw_literals
        assert request.model == via_propose.model == "m"
        assert request.effort == via_propose.effort == "high"


def test_full_live_run_draws_twenty_arms_then_resumes_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 40)

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _factory, r3_path
    )
    assert code == 0
    rows = _rows(results)
    assert len(rows) == 20
    assert sorted({str(row["case_id"]) for row in rows}) == [
        f"r4-{n:02d}" for n in range(1, 11)
    ]
    assert sorted({str(row["arm"]) for row in rows}) == ["cited", "control"]
    assert all(row["drawn"] is True for row in rows)
    assert all(row["model"] == DEFAULT_MODEL for row in rows)
    assert all(row["effort"] == DEFAULT_EFFORT for row in rows)
    assert all(len(row["attempts"]) == 1 for row in rows)
    assert all(row["base_draft_json"] for row in rows)
    row = next(r for r in rows if r["arm"] == "cited")
    assert row["changed_fact"] == "f1"
    row = next(r for r in rows if r["arm"] == "control")
    assert row["changed_fact"] == "f2"

    def _draw_factory() -> Any:
        return ScriptedClient([("text", regen)] * 4)

    code, _resumed = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _draw_factory, r3_path
    )
    assert code == 0
    assert len(_rows(results)) == 20


def test_gate_mismatch_refuses_naming_both_identities(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    rows = _complete_r3_rows()
    for row in rows:
        row["gate_hash"] = "0" * 64
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "000000000000" in err
    _commit, gate_hash = identity.gate_identity()
    assert gate_hash[:12] in err
    assert list(results.glob("*.jsonl")) == []


def test_prompt_mismatch_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    rows = _complete_r3_rows()
    for row in rows:
        row["prompt_sha256"] = "1" * 64
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "111111111111" in err
    assert identity.prompt_identity()[:12] in err


def test_pairs_mismatch_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = _complete_r3_rows()
    for row in rows:
        row["pairs_sha256"] = "2" * 64
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []


def test_missing_r3_file_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(
        monkeypatch, tmp_path, [], _factory, tmp_path / "src" / "absent.jsonl"
    )
    assert code == 2
    assert calls == []


def test_under_five_per_profile_refuses_naming_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    rows = _complete_r3_rows()
    for row in rows:
        if row["profile"] == "builder" and row["arm"] == "base":
            row["attempts"] = [{"raw_text": "not json at all"}]
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "builder 0" in err


def test_unfinished_r3_refuses_naming_remaining(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    rows = [
        row
        for row in _complete_r3_rows()
        if not (row["pair_id"] == "D1" and row["arm"] == "base" and row["repeat"] == 1)
    ]
    assert len(rows) == 119
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "remaining" in err and "1" in err


def test_default_r3_file_ignores_newer_other_gate_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from evals.r3 import results_filename

    _clean_env(monkeypatch, tmp_path)
    _gate_commit, gate_hash = identity.gate_identity()
    prompt_sha = identity.prompt_identity()
    closure_sha = identity.closure_identity()
    expected = results_filename(
        DEFAULT_MODEL, DEFAULT_EFFORT, gate_hash, prompt_sha, closure_sha
    )
    r3_dir = tmp_path / "r3store"
    r3_dir.mkdir()
    _write_r3_file(r3_dir / expected, _complete_r3_rows())
    other = [
        {
            **row,
            "gate_hash": "0" * 64,
            "recorded_at": "2999-01-01T00:00:00+00:00",
            "attempts": [{"raw_text": "newer"}],
        }
        for row in _complete_r3_rows()
    ]
    other_name = results_filename(
        DEFAULT_MODEL, DEFAULT_EFFORT, "0" * 64, prompt_sha, closure_sha
    )
    assert other_name != expected
    _write_r3_file(r3_dir / other_name, other)
    monkeypatch.setattr(r4, "DEFAULT_R3_DIR", r3_dir)
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 40)

    def _factory() -> Any:
        return shared

    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--no-quiet-guard"],
        client_factory=_factory,
    )
    assert code == 0
    assert len(_rows(results)) == 20


def test_default_r3_file_absent_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(r4, "DEFAULT_R3_DIR", tmp_path / "empty-r3")
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--no-quiet-guard"],
        client_factory=_factory,
    )
    assert code == 2
    assert calls == []
    assert "refused" in capsys.readouterr().err


def test_summary_without_matching_r3_renders_no_match_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 60)

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _factory, r3_path
    )
    assert code == 0
    monkeypatch.setattr(r4, "DEFAULT_R3_DIR", tmp_path / "empty-r3")
    code = r4.main(["--summary", "--results-dir", str(results)])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("no matching R3 rows") == 2


def test_r3_file_override_with_other_model_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    good_path = _write_r3_file(tmp_path / "src" / "good.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 60)

    def _draw_factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _draw_factory, good_path
    )
    assert code == 0
    bad_rows = _complete_r3_rows()
    for row in bad_rows:
        row["model"] = "some-other-model"
    bad_path = _write_r3_file(tmp_path / "src" / "bad.jsonl", bad_rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, bad_path)
    assert code == 2
    assert calls == []
    code = r4.main(
        ["--summary", "--results-dir", str(results), "--r3-file", str(bad_path)]
    )
    assert code == 2


def test_unavailable_then_exhausted_and_exit_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())

    def _factory() -> Any:
        return AlwaysUnavailableClient()

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _factory, r3_path
    )
    assert code == 3
    rows = _rows(results)
    assert len(rows) == 3
    assert all(row["drawn"] is False for row in rows)
    assert all(row["unavailable_reason"] == "timeout" for row in rows)


def test_unavailable_stop_fires_at_concurrency_4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())

    def _factory() -> Any:
        return AlwaysUnavailableClient()

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "4"], _factory, r3_path
    )
    assert code == 3
    rows = _rows(results)
    assert 3 <= len(rows) <= 12
    assert all(row["drawn"] is False for row in rows)
    assert all(row["unavailable_reason"] == "timeout" for row in rows)


def test_limit_exit_4_then_resume_draws_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 60)

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1", "--limit", "2"], _factory, r3_path
    )
    assert code == 4
    assert len(_rows(results)) == 2
    code, _resumed = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _factory, r3_path
    )
    assert code == 0
    assert len(_rows(results)) == 20


def test_blocked_arm_is_drawn_but_unscorable_in_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("blocked", "L1_TEST_BLOCK")] + [("text", regen)] * 40)

    def _factory() -> Any:
        return shared

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _factory, r3_path
    )
    assert code == 0
    rows = _rows(results)
    assert len(rows) == 20
    assert rows[0]["drawn"] is True
    assert rows[0]["attempts"][0]["blocked"] is True
    code = r4.main(
        [
            "--summary",
            "--results-dir",
            str(results),
            "--r3-file",
            str(r3_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "unscorable: 1" in out


def test_quiet_window_exit_4_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    madrid = ZoneInfo("Europe/Madrid")
    clock = lambda: datetime(2026, 11, 3, 15, 30, tzinfo=madrid)
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--r3-file", str(r3_path)],
        client_factory=_factory,
        clock=clock,
    )
    assert code == 4
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_refusals_make_zero_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    for extra_env in ({"META_API_KEY": "x"}, {"MUSE_NO_AUTO_UPDATE": None}):
        code, calls = _refusal_run(monkeypatch, tmp_path, r3_path, extra_env)
        assert code == 2
        assert "refused" in capsys.readouterr().err
        assert calls == []


def _refusal_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    r3_path: Path,
    extra_env: Mapping[str, str | None],
) -> tuple[int, list[int]]:
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
    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--r3-file", str(r3_path)],
        client_factory=_factory,
    )
    return code, calls


def test_sentinel_hidden_criteria_dir_unread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    seen: list[list[Any]] = []

    def _factory() -> Any:
        client = ScriptedClient([("text", regen)] * 4)
        seen.append(client.requests)
        return client

    fixed = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", "/nonexistent-r4-sentinel-xyz")
    first_results = tmp_path / "first"
    code = r4.main(
        [
            "--limit",
            "1",
            "--results-dir",
            str(first_results),
            "--r3-file",
            str(r3_path),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
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
    code = r4.main(
        [
            "--limit",
            "1",
            "--results-dir",
            str(second_results),
            "--r3-file",
            str(r3_path),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
        now=lambda: fixed,
    )
    assert code == 4
    assert sentinel.read_bytes() == before
    assert [r.prompt for r in seen[0]] == [r.prompt for r in seen[1]]


def test_summary_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    r3_one_rows = _complete_r3_rows()
    for row in r3_one_rows:
        row["model"] = "m-one"
    r3_one = _write_r3_file(tmp_path / "src" / "r3-one.jsonl", r3_one_rows)
    r3_two_rows = _complete_r3_rows()
    for row in r3_two_rows:
        row["model"] = "m-two"
    r3_two = _write_r3_file(tmp_path / "src" / "r3-two.jsonl", r3_two_rows)
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 60)

    def _factory() -> Any:
        return shared

    _clean_env(monkeypatch, tmp_path)
    both = tmp_path / "both"
    first = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    second = datetime(2026, 11, 2, 13, 0, tzinfo=UTC)
    code = r4.main(
        [
            "--model",
            "m-one",
            "--limit",
            "1",
            "--results-dir",
            str(both),
            "--r3-file",
            str(r3_one),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
        now=lambda: first,
    )
    assert code == 4
    code = r4.main(
        [
            "--model",
            "m-two",
            "--limit",
            "1",
            "--results-dir",
            str(both),
            "--r3-file",
            str(r3_two),
            "--no-quiet-guard",
        ],
        client_factory=_factory,
        now=lambda: second,
    )
    assert code == 4
    assert len(list(both.glob("*.jsonl"))) == 2
    code = r4.main(["--summary", "--results-dir", str(both), "--r3-file", str(r3_two)])
    assert code == 0
    assert "R4 evidence sensitivity" in capsys.readouterr().out

    _gate_commit, gate_hash = identity.gate_identity()
    code = r4.main(
        ["--summary", "--results-dir", str(both), "--identity", gate_hash[:12]]
    )
    assert code == 2
    assert ".jsonl" in capsys.readouterr().err

    code = r4.main(["--summary", "--results-dir", str(both), "--identity", "deadbeef"])
    assert code == 2

    code = r4.main(
        [
            "--summary",
            "--results-dir",
            str(tmp_path / "empty"),
            "--r3-file",
            str(tmp_path / "absent.jsonl"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "no recorded runs" in out

    doc_path = tmp_path / "r4.md"
    monkeypatch.setattr(r4, "DOC_PATH", doc_path)
    code = r4.main(
        [
            "--summary",
            "--results-dir",
            str(both),
            "--r3-file",
            str(r3_two),
            "--write-doc",
        ]
    )
    second_text = capsys.readouterr().out
    assert code == 0
    assert doc_path.read_text(encoding="utf-8") == second_text


@pytest.mark.parametrize("dirty_name", ["gate", "prompt"])
def test_dirty_gate_or_prompt_file_refuses_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
    dirty_name: str,
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
    if dirty_name == "gate":
        (repo / next(iter(identity.GATE_SOURCE_FILES))).write_text(
            "changed\n", encoding="utf-8"
        )
    else:
        (repo / identity.PROMPT_SOURCE_FILE).write_text("changed\n", encoding="utf-8")
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--r3-file", str(r3_path)],
        client_factory=_factory,
        root=repo,
    )
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "dirty gate or prompt files" in err
    assert list(results.glob("*.jsonl")) == []


def test_harness_rules_file_refuses_unless_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 40)

    def _factory() -> Any:
        return shared

    _clean_env(monkeypatch, tmp_path)
    xdg = tmp_path / "xdg"
    (xdg / "muse").mkdir(parents=True, exist_ok=True)
    (xdg / "muse" / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    results = tmp_path / "r4"
    code = r4.main(
        [
            "--results-dir",
            str(results),
            "--r3-file",
            str(r3_path),
            "--no-quiet-guard",
            "--limit",
            "1",
        ],
        client_factory=_factory,
    )
    assert code == 2
    assert shared.calls == 0
    assert "refused" in capsys.readouterr().err
    code = r4.main(
        [
            "--results-dir",
            str(results),
            "--r3-file",
            str(r3_path),
            "--no-quiet-guard",
            "--limit",
            "1",
            "--allow-rules-file",
        ],
        client_factory=_factory,
    )
    assert code == 4
    assert len(_rows(results)) == 1


def test_stop_time_in_past_with_no_quiet_guard_stops_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, results = _run(
        monkeypatch,
        tmp_path,
        ["--stop-time", "2000-01-01T00:00:00+00:00"],
        _factory,
        r3_path,
    )
    assert code == 4
    assert calls == []
    assert list(results.glob("*.jsonl")) == []


def test_unavailable_arm_exits_4_then_resume_draws_it_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    regen = _draft("b-ship")
    first = ScriptedClient([("unavailable", "timeout")] + [("text", regen)] * 40)

    def _first_factory() -> Any:
        return first

    code, results = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _first_factory, r3_path
    )
    assert code == 4
    rows = _rows(results)
    assert len(rows) == 20
    unavailable = [row for row in rows if not row["drawn"]]
    assert len(unavailable) == 1
    assert unavailable[0]["unavailable_reason"] == "timeout"

    def _second_factory() -> Any:
        return ScriptedClient([("text", regen)] * 4)

    code, _resumed = _run(
        monkeypatch, tmp_path, ["--concurrency", "1"], _second_factory, r3_path
    )
    assert code == 0
    final = _rows(results)
    assert len(final) == 21
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in final:
        by_slot.setdefault((str(row["case_id"]), str(row["arm"])), []).append(row)
    assert len(by_slot) == 20
    assert all(any(r["drawn"] for r in slot) for slot in by_slot.values())


def test_second_run_on_locked_results_file_exits_2_with_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    import fcntl

    from evals.r3 import results_filename

    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", _complete_r3_rows())
    _clean_env(monkeypatch, tmp_path)
    results = tmp_path / "r4"
    results.mkdir()
    gate_hash = identity.gate_identity()[1]
    name = results_filename(
        DEFAULT_MODEL,
        DEFAULT_EFFORT,
        gate_hash,
        identity.prompt_identity(),
        identity.closure_identity(),
    )
    target = results / name
    target.write_text("", encoding="utf-8")
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    with open(target, "a", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        code = r4.main(
            [
                "--results-dir",
                str(results),
                "--r3-file",
                str(r3_path),
                "--no-quiet-guard",
            ],
            client_factory=_factory,
        )
    assert code == 2
    assert calls == []
    captured = capsys.readouterr()
    lines = (captured.out + captured.err).strip().splitlines()
    assert len(lines) == 1


def test_cited_and_control_requests_change_their_own_fact() -> None:
    from evals import r4_scenario

    doc, _sha = load_pairs()
    cases = build_cases(_complete_r3_rows(), doc)
    case = next(c for c in cases if c.profile == "builder")
    base_statements = {fact["id"]: fact["statement"] for fact in doc["facts"]}
    for arm in ("cited", "control"):
        changed = case.cited_fact if arm == "cited" else case.control_fact
        other = case.control_fact if arm == "cited" else case.cited_fact
        scenario = r4.arm_scenario(doc, case, arm)
        materials = r3.build_slot_materials(scenario, case.profile)
        request = r4.first_attempt_request(materials, case.profile, "m", "high")
        fact_lines = {}
        for line in request.prompt.splitlines():
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and "statement" in payload:
                fact_lines[str(payload.get("id"))] = str(payload["statement"])
        label, family = r4_scenario.FAMILY_BY_FACT[changed]
        prior = doc["metrics"][f"period.prior.{family}"]
        expected = r4_scenario.changed_statement(label, prior)
        assert fact_lines[changed] == expected
        assert fact_lines[other] == base_statements[other]


def test_expected_r3_path_closure_naming() -> None:
    from evals.r3 import results_filename

    old = r4._expected_r3_path("m", "high", "a" * 64, "b" * 64)
    assert old.name == results_filename("m", "high", "a" * 64, "b" * 64)
    assert "__c" not in old.name
    new = r4._expected_r3_path("m", "high", "a" * 64, "b" * 64, "c" * 64)
    assert new.name == results_filename("m", "high", "a" * 64, "b" * 64, "c" * 64)
    assert new.name.endswith("__c" + "c" * 12 + ".jsonl")
    assert new.name != old.name


def test_r3_closure_mismatch_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    rows = _complete_r3_rows()
    for row in rows:
        row["closure_sha256"] = "0" * 64
    r3_path = _write_r3_file(tmp_path / "src" / "r3.jsonl", rows)
    calls: list[int] = []

    def _factory() -> Any:
        calls.append(1)
        return ScriptedClient([("text", "{}")])

    code, _results = _run(monkeypatch, tmp_path, [], _factory, r3_path)
    assert code == 2
    assert calls == []
    assert "closure" in capsys.readouterr().err


def test_default_r3_lookup_finds_closure_named_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from evals.r3 import results_filename

    _clean_env(monkeypatch, tmp_path)
    _gate_commit, gate_hash = identity.gate_identity()
    prompt_sha = identity.prompt_identity()
    closure_sha = identity.closure_identity()
    rows = _complete_r3_rows()
    for row in rows:
        row["closure_sha256"] = closure_sha
    r3_dir = tmp_path / "r3store"
    r3_dir.mkdir()
    name = results_filename(
        DEFAULT_MODEL, DEFAULT_EFFORT, gate_hash, prompt_sha, closure_sha
    )
    assert "__c" + closure_sha[:12] in name
    _write_r3_file(r3_dir / name, rows)
    monkeypatch.setattr(r4, "DEFAULT_R3_DIR", r3_dir)
    regen = _draft("b-ship")
    shared = ScriptedClient([("text", regen)] * 40)

    def _factory() -> Any:
        return shared

    results = tmp_path / "r4"
    code = r4.main(
        ["--results-dir", str(results), "--no-quiet-guard"],
        client_factory=_factory,
    )
    assert code == 0
    assert len(_rows(results)) == 20
    assert all(row.get("closure_sha256") == closure_sha for row in _rows(results))
