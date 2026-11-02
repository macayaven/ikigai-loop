"""Step 6 (D31/D32): R9 runner checks on fakes only, never the network.

Refusals (no arm, no live variable, absent file), the matcher baseline from
the same runner, and the scoring rules including the ignoring-pinned verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals import r9
from evals.r9 import R9Case, load_cases


def fixture_file() -> dict:
    """Three cases: a skip, a pinned-until done, and a question case."""
    return {
        "schema": 1,
        "commitments": [
            {"id": "write-up", "title": "Write-up", "side": "builder"},
            {"id": "run", "title": "Morning run", "side": "disconnect"},
        ],
        "card": {
            "shown_at": "2026-10-31T13:00:00+01:00",
            "proposals": [
                {"label": "A", "title": "Write-up", "slot": "x"},
                {"label": "B", "title": "Morning run", "slot": "x"},
            ],
            "cited_statement": ["Screen hours decreased."],
        },
        "cases": [
            {
                "id": "skip-today",
                "now": "2026-10-31T13:30:00+01:00",
                "weekday": "Saturday",
                "transcript": "Skip the write-up today",
                "trap": None,
                "accepted": [
                    {
                        "commitment_id": "write-up",
                        "operation": "skip",
                        "until": "today",
                    }
                ],
                "requires_question": False,
                "pinned_by_coordinator_silence": [],
                "lang": "en",
                "noise": False,
            },
            {
                "id": "done-pinned",
                "now": "2026-10-31T14:05:00+01:00",
                "weekday": "Saturday",
                "transcript": "Did the morning run",
                "trap": "already_done",
                "accepted": [
                    {"commitment_id": "run", "operation": "done", "until": "today"}
                ],
                "requires_question": False,
                "pinned_by_coordinator_silence": ["until"],
                "lang": "en",
                "noise": True,
            },
            {
                "id": "needs-question",
                "now": "2026-10-31T15:00:00+01:00",
                "weekday": "Saturday",
                "transcript": "Move it",
                "trap": "underdetermined",
                "accepted": [
                    {"commitment_id": None, "operation": "none", "until": None}
                ],
                "requires_question": True,
                "pinned_by_coordinator_silence": [],
                "lang": "mixed",
                "noise": False,
            },
        ],
    }


def _write_cases(tmp_path: Path) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture_file()), encoding="utf-8")
    return path


def _load(tmp_path: Path):
    return load_cases(_write_cases(tmp_path), expected_cases=3)


def _case(data, case_id: str) -> R9Case:
    return next(c for c in data.cases if c.id == case_id)


def test_no_arm_chosen_runs_nothing(tmp_path: Path, capsys) -> None:
    code = r9.main([], environ={}, results_dir=tmp_path / "out")
    assert code != 0
    assert not (tmp_path / "out").exists()
    captured = capsys.readouterr()
    assert "matcher" in captured.err or "model" in captured.err


def test_model_arm_refuses_without_live_variable(tmp_path: Path, capsys) -> None:
    calls: list = []

    class FakeMuse:
        transport_version: str | None = "9.9-fake"

        def complete(self, request):  # pragma: no cover - must not run
            calls.append(request)
            raise AssertionError("must not run without the live variable")

    code = r9.main(
        ["--model", "muse-spark-1.3", "--effort", "minimal"],
        environ={},
        results_dir=tmp_path / "out",
        muse_client=FakeMuse(),
    )
    assert code != 0
    assert calls == []
    assert "IKIGAI_R9_LIVE" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_absent_file_refusal_names_pinned_path(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert not Path(str(r9.CASES_PATH)).exists()
    code = r9.main(["--matcher"], environ={})
    assert code != 0
    assert "evals/r9_cases.json" in capsys.readouterr().err
    assert not r9.RESULTS_DIR.exists()


def test_matcher_arm_writes_both_arms_without_live(tmp_path: Path) -> None:
    cases = _write_cases(tmp_path)
    out = tmp_path / "out"
    code = r9.main(["--matcher"], environ={}, cases_path=cases, results_dir=out)
    assert code == 0
    for arm in ("matcher", "matcher-until-words"):
        payload = json.loads((out / f"{arm}.json").read_text(encoding="utf-8"))
        assert payload["arm"] == arm
        assert payload["summary"]["total"] == 3
        for row in payload["rows"]:
            assert row["prompt_tokens"] is None
            assert row["completion_tokens"] is None
            assert row["transport"] == "matcher"
    baseline = json.loads((out / "matcher.json").read_text(encoding="utf-8"))
    assert baseline["summary"]["passed"] == 3


def test_prompt_comes_from_production_builders(tmp_path: Path) -> None:
    import framework.voice.prompt as voice_prompt
    import framework.voice.schemas as voice_schemas

    assert r9.build_compile_prompt is voice_prompt.build_compile_prompt
    assert r9.build_correction_schema is voice_schemas.build_correction_schema
    source = Path(r9.__file__).read_text(encoding="utf-8")
    assert "You are reading one voice note" not in source


def test_prompt_weekday_and_slot_are_the_case_now(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "skip-today")
    prompt = r9.prompt_for_case(data, case)
    assert f"It is {case.weekday} " in prompt
    assert "2026-10-31" in prompt
    assert '"slot":"2026-10-31T13:30:00+01:00"' in prompt


def test_invalid_json_is_wrong_on_all_fields(tmp_path: Path) -> None:
    data = _load(tmp_path)
    scored = r9.score_reply(
        '{"operation": "skip",',
        _case(data, "skip-today"),
        known_ids=("write-up", "run"),
    )
    assert scored.passed is False
    assert scored.fields == {
        "commitment_id": False,
        "operation": False,
        "until": False,
    }
    assert scored.fence_recovered is False


def test_abstention_without_question_is_wrong_on_all_fields(
    tmp_path: Path,
) -> None:
    data = _load(tmp_path)
    text = json.dumps(
        {
            "operation": "none",
            "commitment_id": None,
            "until": None,
            "question": "Which commitment do you mean?",
        }
    )
    scored = r9.score_reply(
        text, _case(data, "skip-today"), known_ids=("write-up", "run")
    )
    assert scored.passed is False
    assert all(v is False for v in scored.fields.values())


def test_missing_field_never_equals_null(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "needs-question")
    text = json.dumps(
        {"operation": "none", "commitment_id": None, "question": "Which one?"}
    )
    scored = r9.score_reply(text, case, known_ids=("write-up", "run"))
    assert scored.fields["until"] is False
    assert scored.passed is False


def test_question_rule(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "needs-question")
    good = json.dumps(
        {
            "operation": "none",
            "commitment_id": None,
            "until": None,
            "question": "Which commitment do you mean?",
        }
    )
    assert r9.score_reply(good, case, known_ids=("write-up", "run")).passed is True
    blank = json.dumps(
        {
            "operation": "none",
            "commitment_id": None,
            "until": None,
            "question": "   ",
        }
    )
    assert r9.score_reply(blank, case, known_ids=("write-up", "run")).passed is False


def test_fields_compare_against_best_entry_ties_first(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "skip-today")
    multi = R9Case(
        id=case.id,
        now=case.now,
        weekday=case.weekday,
        transcript=case.transcript,
        trap=case.trap,
        accepted=(
            {"commitment_id": "write-up", "operation": "skip", "until": "today"},
            {"commitment_id": "run", "operation": "defer", "until": "today"},
        ),
        requires_question=False,
        pinned=(),
        lang=case.lang,
        noise=case.noise,
    )
    text = json.dumps(
        {
            "operation": "defer",
            "commitment_id": "write-up",
            "until": "today",
            "question": None,
        }
    )
    scored = r9.score_reply(text, multi, known_ids=("write-up", "run"))
    assert scored.passed is False
    assert scored.fields == {
        "commitment_id": True,
        "operation": False,
        "until": True,
    }


def test_fence_recovered(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "skip-today")
    inner = json.dumps(
        {
            "operation": "skip",
            "commitment_id": "write-up",
            "until": "today",
            "question": None,
        }
    )
    scored = r9.score_reply(
        "```json\n" + inner + "\n```", case, known_ids=("write-up", "run")
    )
    assert scored.passed is False
    assert scored.fence_recovered is True


def test_ignoring_pinned_fields(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "done-pinned")
    exact = json.dumps(
        {
            "operation": "done",
            "commitment_id": "run",
            "until": "today",
            "question": None,
        }
    )
    scored = r9.score_reply(exact, case, known_ids=("write-up", "run"))
    assert scored.passed is True
    assert scored.correct_ignoring_pinned_fields is True
    other_until = json.dumps(
        {
            "operation": "done",
            "commitment_id": "run",
            "until": "tomorrow",
            "question": None,
        }
    )
    drifted = r9.score_reply(other_until, case, known_ids=("write-up", "run"))
    assert drifted.passed is False
    assert drifted.correct_ignoring_pinned_fields is True


def test_validation_codes_travel_with_rows(tmp_path: Path) -> None:
    data = _load(tmp_path)
    case = _case(data, "skip-today")
    text = json.dumps(
        {
            "operation": "skip",
            "commitment_id": "write-up",
            "until": "today",
            "question": "extra",
        }
    )
    scored = r9.score_reply(text, case, known_ids=("write-up", "run"))
    assert scored.passed is True
    assert "CORRECTION_QUESTION_INVALID" in scored.validation_codes


class _ScriptedMuse:
    """Fake muse transport: canned reply text per call, no network."""

    transport_version: str | None = "9.9-fake"

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts
        self.calls: list = []

    def complete(self, request):
        from framework.proposal.core import WonderResponse

        self.calls.append(request)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return WonderResponse(
            text=text,
            model_reported="unreported",
            latency_ms=3,
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=5,
            reasoning_tokens=None,
        )


def test_model_arm_counts_refused_passes(tmp_path: Path) -> None:
    cases = _write_cases(tmp_path)
    out = tmp_path / "out"
    text = json.dumps(
        {
            "operation": "skip",
            "commitment_id": "write-up",
            "until": "today",
            "question": "extra",
        }
    )
    fake = _ScriptedMuse([text])
    code = r9.main(
        ["--model", "muse-spark-1.3", "--effort", "minimal"],
        environ={"IKIGAI_R9_LIVE": "1"},
        cases_path=cases,
        results_dir=out,
        muse_client=fake,
    )
    assert code == 0
    assert len(fake.calls) == 3
    assert fake.calls[0].schema_name == "voice_correction"
    payload = json.loads(
        (out / "muse-muse-spark-1.3-minimal.json").read_text(encoding="utf-8")
    )
    assert payload["model"] == "muse-spark-1.3"
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["passes_refused_by_validation"] == 1
    assert payload["rows"][0]["muse_version"] == "9.9-fake"
    assert payload["rows"][0]["transport"] == "muse"


def test_model_arm_failing_call_is_a_failed_row(tmp_path: Path) -> None:
    from framework.proposal.core import MetaUnavailableError

    cases = _write_cases(tmp_path)
    out = tmp_path / "out"

    class _Failing:
        transport_version: str | None = None
        calls = 0

        def complete(self, request):
            type(self).calls += 1
            raise MetaUnavailableError("down", latency_ms=1)

    code = r9.main(
        ["--model", "muse-spark-1.3", "--effort", "minimal"],
        environ={"IKIGAI_R9_LIVE": "1"},
        cases_path=cases,
        results_dir=out,
        muse_client=_Failing(),
    )
    assert code == 0
    payload = json.loads(
        (out / "muse-muse-spark-1.3-minimal.json").read_text(encoding="utf-8")
    )
    assert payload["summary"]["passed"] == 0
    assert _Failing.calls == 3


def test_local_arm_records_local_effort_and_requested_model(
    tmp_path: Path,
) -> None:
    from framework.glimmer.facts import LLMResponse

    cases = _write_cases(tmp_path)
    out = tmp_path / "out"
    text = json.dumps(
        {
            "operation": "skip",
            "commitment_id": "write-up",
            "until": "today",
            "question": None,
        }
    )

    class _FakeLocal:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str):
            self.prompts.append(prompt)
            return LLMResponse(
                text=text,
                model_id="/tmp/evil-path",
                latency_ms=1,
                finish_reason="stop",
                completion_tokens=7,
            )

    fake = _FakeLocal()
    code = r9.main(
        ["--model", "req-model", "--effort", "low", "--transport", "local"],
        environ={
            "IKIGAI_R9_LIVE": "1",
            "LOCAL_LLM_BASE_URL": "http://127.0.0.1:1",
            "LOCAL_LLM_MODEL": "req-model",
            "LOCAL_LLM_API_KEY": "k",
        },
        cases_path=cases,
        results_dir=out,
        local_client=fake,
    )
    assert code == 0
    assert len(fake.prompts) == 3
    payload = json.loads(
        (out / "local-req-model-local.json").read_text(encoding="utf-8")
    )
    assert payload["effort"] == "local"
    assert payload["model"] == "req-model"
    dumped = (out / "local-req-model-local.json").read_text(encoding="utf-8")
    assert "/tmp/evil-path" not in dumped
    assert "evals/" not in dumped


def test_summary_counts_by_trap_lang_noise(tmp_path: Path) -> None:
    cases = _write_cases(tmp_path)
    out = tmp_path / "out"
    code = r9.main(["--matcher"], environ={}, cases_path=cases, results_dir=out)
    assert code == 0
    summary = json.loads((out / "matcher.json").read_text(encoding="utf-8"))["summary"]
    assert summary["per_trap"]["none"]["passed"] == 1
    assert summary["per_trap"]["already_done"]["passed"] == 1
    assert summary["per_trap"]["underdetermined"]["passed"] == 1
    assert summary["per_lang"]["en"]["total"] == 2
    assert summary["per_lang"]["mixed"]["total"] == 1
    assert summary["per_noise"]["true"]["total"] == 1
    assert summary["per_noise"]["false"]["total"] == 2
    assert summary["per_field"] == {
        "commitment_id": 3,
        "operation": 3,
        "until": 3,
    }


def test_results_hold_no_reply_model_or_path(tmp_path: Path) -> None:
    cases = _write_cases(tmp_path)
    out = tmp_path / "out"
    assert r9.main(["--matcher"], environ={}, cases_path=cases, results_dir=out) == 0
    for name in ("matcher.json", "matcher-until-words.json"):
        dumped = (out / name).read_text(encoding="utf-8")
        assert "model_reported" not in dumped
        assert "model_id" not in dumped
        assert str(cases) not in dumped


def test_score_needs_no_environment(tmp_path: Path) -> None:
    data = _load(tmp_path)
    scored = r9.score_reply(
        "not json at all",
        _case(data, "skip-today"),
        known_ids=("write-up", "run"),
    )
    assert scored.passed is False
    assert scored.validation_codes == ("CORRECTION_SCHEMA_INVALID",)


def _write_single_case(tmp_path: Path) -> Path:
    doc = fixture_file()
    doc["cases"] = [doc["cases"][0]]
    path = tmp_path / "single.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_muse_transport_error_is_recorded_not_leaked(tmp_path: Path) -> None:
    class MetaUnavailableError(Exception):
        pass

    cases = _write_single_case(tmp_path)
    out = tmp_path / "out"

    class _Boom:
        transport_version: str | None = None

        def complete(self, request):
            raise MetaUnavailableError("secret-detail-marker")

    code = r9.main(
        ["--model", "muse-spark-1.3", "--effort", "minimal"],
        environ={"IKIGAI_R9_LIVE": "1"},
        cases_path=cases,
        results_dir=out,
        muse_client=_Boom(),
    )
    assert code == 0
    dumped = (out / "muse-muse-spark-1.3-minimal.json").read_text(encoding="utf-8")
    assert "secret-detail-marker" not in dumped
    payload = json.loads(dumped)
    assert payload["rows"][0]["transport_error"] == "MetaUnavailableError"
    assert payload["rows"][0]["passed"] is False
    assert payload["summary"]["transport_errors"] == 1


def test_local_transport_error_uses_own_class_name(tmp_path: Path) -> None:
    class LocalBoomError(Exception):
        pass

    cases = _write_single_case(tmp_path)
    out = tmp_path / "out"

    class _FakeLocal:
        def complete(self, prompt: str):
            raise LocalBoomError("local-secret-detail-marker")

    code = r9.main(
        ["--model", "req-model", "--effort", "low", "--transport", "local"],
        environ={
            "IKIGAI_R9_LIVE": "1",
            "LOCAL_LLM_BASE_URL": "http://127.0.0.1:1",
            "LOCAL_LLM_MODEL": "req-model",
            "LOCAL_LLM_API_KEY": "k",
        },
        cases_path=cases,
        results_dir=out,
        local_client=_FakeLocal(),
    )
    assert code == 0
    dumped = (out / "local-req-model-local.json").read_text(encoding="utf-8")
    assert "local-secret-detail-marker" not in dumped
    payload = json.loads(dumped)
    assert payload["rows"][0]["transport_error"] == "LocalBoomError"
    assert payload["rows"][0]["passed"] is False
    assert payload["summary"]["transport_errors"] == 1


def test_empty_and_invalid_replies_have_null_transport_error(
    tmp_path: Path,
) -> None:
    cases = _write_single_case(tmp_path)
    for reply, stem in (("", "empty"), ('{"operation": "skip",', "invalid")):
        out = tmp_path / f"out-{stem}"
        fake = _ScriptedMuse([reply])
        code = r9.main(
            ["--model", "muse-spark-1.3", "--effort", "minimal"],
            environ={"IKIGAI_R9_LIVE": "1"},
            cases_path=cases,
            results_dir=out,
            muse_client=fake,
        )
        assert code == 0
        payload = json.loads(
            (out / "muse-muse-spark-1.3-minimal.json").read_text(encoding="utf-8")
        )
        assert payload["rows"][0]["passed"] is False
        assert payload["rows"][0]["transport_error"] is None
        assert payload["summary"]["transport_errors"] == 0


def test_matcher_rows_carry_null_transport_error(tmp_path: Path) -> None:
    cases = _write_single_case(tmp_path)
    out = tmp_path / "out"
    assert r9.main(["--matcher"], environ={}, cases_path=cases, results_dir=out) == 0
    for name in ("matcher.json", "matcher-until-words.json"):
        payload = json.loads((out / name).read_text(encoding="utf-8"))
        assert payload["rows"][0]["transport_error"] is None
        assert payload["summary"]["transport_errors"] == 0
