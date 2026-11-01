"""Ticket 11: ``python -m framework.cycle propose`` lines, exits, and the seam."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from evals.proposal_cases import (
    BASE_ELIGIBLE,
    BASE_FACTS,
    BASE_SNAPSHOT,
    GOOD_DRAFT,
    ScriptedWonderClient,
    text_entry,
)
from framework.briefing.context import MetricSnapshot
from framework.cycle import __main__ as propose_main
from framework.glimmer.facts import FactResult, PassResult
from framework.store import EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT_ID = "subject-1"
AS_OF_ISO = "2026-10-31T14:00:00+01:00"
SLOT_ISO = "2026-10-31T15:07:00+01:00"
AS_OF = datetime.fromisoformat(AS_OF_ISO)


def _pass(name):  # type: ignore[no-untyped-def]
    return PassResult(
        name=name,
        attempts=0,
        raw_valid=True,
        model_id="",
        latency_ms=0,
        finish_reason=None,
        completion_tokens=None,
        kept=0,
        noop_reason=None,
    )


def _seed_cycle(db: Path) -> None:
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    try:
        result = FactResult(
            facts=tuple(BASE_FACTS),
            code_fact_ids=(),
            snapshot=MetricSnapshot(values=dict(BASE_SNAPSHOT)),
            passes=(_pass("personal"), _pass("feed")),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT_ID,
            as_of=AS_OF,
            window_start=AS_OF - timedelta(hours=72),
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
    finally:
        fact_store.close()
        store.close()


def _write_commitments(tmp_path: Path) -> Path:
    path = tmp_path / "commitments.json"
    path.write_text(
        json.dumps([c.model_dump(mode="json") for c in BASE_ELIGIBLE]),
        encoding="utf-8",
    )
    return path


def _write_terms(tmp_path: Path) -> Path:
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "deny-terms.txt").write_text("harbor-light\n", encoding="utf-8")
    return hidden


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Path) -> list[str]:
    monkeypatch.setenv("META_API_KEY", "synthetic-key")
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(_write_terms(tmp_path)))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(_write_commitments(tmp_path)))
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    return [
        "propose",
        "--as-of",
        AS_OF_ISO,
        "--slot",
        SLOT_ISO,
        "--db",
        str(db),
        "--transport",
        "api",
    ]


def _stub_client(script_texts: list[str]):  # type: ignore[no-untyped-def]
    from evals.proposal_cases import ScriptEntry

    script = tuple(ScriptEntry(kind="text", text=text) for text in script_texts)

    def _factory(**kwargs):  # type: ignore[no-untyped-def]
        return ScriptedWonderClient(script)

    return _factory


def test_exact_lines_per_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == [
        (
            "profile=builder kind=proposal attempts=1 codes=- seconds=0.0s "
            "tokens=13 stale=0"
        ),
        (
            "profile=disconnect kind=noop attempts=0 codes=NOOP_NO_ELIGIBLE_COMMITMENT "
            "seconds=0.0s tokens=0 stale=0"
        ),
    ]


def test_single_profile_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + ["--profile", "disconnect"]
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 0
    assert capsys.readouterr().out.strip().startswith("profile=disconnect ")


@pytest.mark.parametrize(
    "variable",
    [
        "META_API_KEY",
        "HIDDEN_CRITERIA_DIR",
        "IKIGAI_COMMITMENTS_FILE",
    ],
)
def test_unset_variable_exits_2_before_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.delenv(variable, raising=False)
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == f"error: {variable}\n", captured.err
    assert captured.out == ""


def test_naive_slot_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    args[args.index("--slot") + 1] = "2026-10-31T15:07:00"
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 2
    assert capsys.readouterr().out == ""


def test_unknown_cycle_id_exits_2_without_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + ["--cycle-id", "cycle-zzz-9"]
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert "cycle-zzz-9" not in captured.err
    assert captured.out == ""


def test_commitments_unavailable_exits_2_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(bad))
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: commitments unavailable: empty\n", captured.err
    assert str(bad) not in captured.err


def test_subject_flag_satisfies_without_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + ["--subject-id", SUBJECT_ID]
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 0
    assert (
        capsys.readouterr().out.strip().splitlines()[0].startswith("profile=builder ")
    )


def test_missing_subject_flag_and_variable_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: IKIGAI_SUBJECT_ID\n", captured.err
    assert captured.out == ""


def test_contributor_model_exits_2_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    args = _env(monkeypatch, tmp_path, db) + [
        "--model",
        "muse-wonder-1.0-contributor",
    ]
    monkeypatch.delenv("META_API_KEY", raising=False)
    code = propose_main.main(args)
    assert code == 2
    captured = capsys.readouterr()
    assert "contributor" in captured.err
    assert "META_API_KEY" not in captured.err
    assert captured.out == ""


def test_bad_timezone_exits_2_before_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + ["--timezone", "Mars/Olympus"]
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("no store may open before the limits parse")

    monkeypatch.setattr(propose_main, "EventStore", _boom)
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: --timezone must be a valid IANA timezone\n", (
        captured.err
    )
    assert captured.out == ""


def test_allowed_start_not_before_end_exits_2_before_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + [
        "--allowed-start",
        "23:30",
        "--allowed-end",
        "13:00",
    ]
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("no store may open before the limits parse")

    monkeypatch.setattr(propose_main, "EventStore", _boom)
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "error: --allowed-start must be before --allowed-end\n", (
        captured.err
    )
    assert captured.out == ""


def test_foreign_cycle_id_raises_unknown_cycle(tmp_path: Path) -> None:
    import pytest as _pytest

    from framework.briefing.context import PrivateTerms
    from framework.cycle import UnknownCycleError, run_proposals
    from framework.proposal.core import ModelParams

    db = tmp_path / "foreign.db"
    _seed_cycle(db)
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        with _pytest.raises(UnknownCycleError):
            run_proposals(
                as_of=AS_OF,
                slot=AS_OF,
                subject_id="subject-2",
                profiles=("builder",),
                store=store,
                fact_store=fact_store,
                proposal_store=proposal_store,
                client=_stub_client([])(),
                private_terms=PrivateTerms(terms=(), available=True),
                eligible_by_profile={},
                limits=propose_main.parse_proposal_limits(
                    timezone="Europe/Madrid",
                    allowed_start="13:00",
                    allowed_end="23:30",
                ),
                models=ModelParams(
                    first_model="muse-wonder-1.0",
                    first_effort="high",
                    retry_model="muse-wonder-1.0",
                    retry_effort="high",
                ),
                stale_after_s=3600.0,
                cycle_id="cycle-1",
            )
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


def test_foreign_cycle_id_exits_2_without_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db) + [
        "--cycle-id",
        "cycle-1",
        "--subject-id",
        "subject-2",
    ]
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 2
    captured = capsys.readouterr()
    assert "cycle-1" not in captured.err
    assert "subject-2" not in captured.err
    assert captured.out == ""


def test_terms_unavailable_runs_to_blocked_noops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    empty_hidden = tmp_path / "empty-hidden"
    empty_hidden.mkdir()
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(empty_hidden))
    assert propose_main.main(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "kind=noop" in lines[0]
    assert "NOOP_OUTBOUND_BLOCKED" in lines[0]
    assert "L1_PRIVATE_TERMS_UNAVAILABLE" in lines[0]


def test_unexpected_exception_exits_1_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([GOOD_DRAFT]))

    def _boom(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("SENTINEL marker must stay hidden")

    monkeypatch.setattr(propose_main, "run_proposals", _boom)
    assert propose_main.main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == "error: RuntimeError\n", captured.err
    assert "SENTINEL" not in captured.err
    assert captured.out == ""


def test_stdout_carries_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([GOOD_DRAFT]))
    assert propose_main.main(args) == 0
    out = capsys.readouterr().out
    for forbidden in (
        "Build the synthetic parser sketch",
        "Synthetic focus session completed yesterday",
        "fact:synthetic-1",
        "period.last.pushes",
        "cycle-1",
    ):
        assert forbidden not in out, forbidden


def test_no_cycle_records_noops_and_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([]))
    assert propose_main.main(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "kind=noop" in lines[0] and "NO_CYCLE" in lines[0]
    assert "stale=-" in lines[0]


def test_seam_shared_hour_and_sensitive_withheld(tmp_path: Path) -> None:
    from datetime import time

    from framework.briefing.context import ProfileLimits
    from framework.cycle import forbidden_literals_for, run_proposals
    from framework.proposal.core import ModelParams

    db = tmp_path / "seam.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        sensitive = BASE_FACTS[0].model_copy(
            update={"id": "fact:synthetic-9", "tier": "sensitive"}
        )
        result = FactResult(
            facts=(BASE_FACTS[1], sensitive),
            code_fact_ids=(),
            snapshot=MetricSnapshot(values=dict(BASE_SNAPSHOT)),
            passes=(_pass("personal"), _pass("feed")),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT_ID,
            as_of=AS_OF,
            window_start=AS_OF - timedelta(hours=72),
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        fact_store.record_cycle(result)
        assert forbidden_literals_for(store, SUBJECT_ID, AS_OF) == ("iki-care",)
        bad = json.dumps(
            {
                "commitment_id": "cm-builder-parser",
                "overall_state": [
                    {
                        "text": "The hidden session finished yesterday",
                        "fact_ids": ["fact:synthetic-9"],
                        "metric_refs": [],
                    }
                ],
                "working": [],
                "not_working": [],
            }
        )
        client = ScriptedWonderClient((text_entry(bad), text_entry(bad)))
        from framework.briefing.context import PrivateTerms

        results = run_proposals(
            as_of=AS_OF,
            slot=datetime.fromisoformat(SLOT_ISO),
            subject_id=SUBJECT_ID,
            profiles=("builder", "disconnect"),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={"builder": tuple(BASE_ELIGIBLE)},
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
        )
        assert len(results) == 2
        builder, disconnect = results
        assert builder.hour == disconnect.hour
        assert builder.hour is not None
        assert builder.kind == "fallback"
        assert builder.attempts[0].codes == (
            ("L1B_UNKNOWN_FACT", "sections[overall_state].claims[c-overall_state-1]"),
        )
        assert len(client.requests) == 2
        assert "hidden session finished" not in client.requests[0].prompt.lower()
        assert disconnect.kind == "noop"
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


def test_internal_only_label_blocks_the_outbound_prompt(tmp_path: Path) -> None:
    from datetime import time

    from framework.briefing.context import ProfileLimits
    from framework.cycle import forbidden_literals_for, run_proposals
    from framework.proposal.core import ModelParams

    db = tmp_path / "internal-label.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        labelled = BASE_FACTS[1].model_copy(
            update={
                "id": "fact:synthetic-8",
                "statement": "Synthetic walk before IKI-CARE time",
            }
        )
        result = FactResult(
            facts=(labelled,),
            code_fact_ids=(),
            snapshot=MetricSnapshot(values=dict(BASE_SNAPSHOT)),
            passes=(_pass("personal"), _pass("feed")),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT_ID,
            as_of=AS_OF,
            window_start=AS_OF - timedelta(hours=72),
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        fact_store.record_cycle(result)
        assert forbidden_literals_for(store, SUBJECT_ID, AS_OF) == ("iki-care",)
        client = ScriptedWonderClient((text_entry(GOOD_DRAFT),))
        from framework.briefing.context import PrivateTerms

        results = run_proposals(
            as_of=AS_OF,
            slot=datetime.fromisoformat(SLOT_ISO),
            subject_id=SUBJECT_ID,
            profiles=("builder",),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={"builder": tuple(BASE_ELIGIBLE)},
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
        )
        assert len(results) == 1
        assert results[0].kind == "noop"
        assert results[0].reason_codes == ("NOOP_OUTBOUND_BLOCKED",)
        assert results[0].attempts[0].blocked is True
        assert ("L1_RAW_VALUE", "prompt") in results[0].attempts[0].codes
        assert client.calls == 0
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


def test_model_effort_defaults_match_constants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL

    db = tmp_path / "cli.db"
    _seed_cycle(db)
    args = _env(monkeypatch, tmp_path, db)
    monkeypatch.setattr(propose_main, "MetaClient", _stub_client([GOOD_DRAFT]))
    seen: dict[str, Any] = {}
    real_run = propose_main.run_proposals

    def _capture(*call_args: Any, **call_kwargs: Any) -> Any:
        seen["models"] = call_kwargs["models"]
        return real_run(*call_args, **call_kwargs)

    monkeypatch.setattr(propose_main, "run_proposals", _capture)
    assert propose_main.main(args) == 0
    models = seen["models"]
    assert models.first_model == DEFAULT_MODEL
    assert models.first_effort == DEFAULT_EFFORT
    assert models.retry_model == DEFAULT_MODEL
    assert models.retry_effort == DEFAULT_EFFORT
