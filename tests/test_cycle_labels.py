"""Ticket 9c: sweep order, budget, off-by-default, invisibility, canaries."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from evals.glimmer_cases import (
    AS_OF,
    SUBJECT_ID,
    RecordingLLM,
    cal_event,
    personal_batch,
)
from framework.cycle import __main__ as cycle_main
from framework.cycle import labels as sweep_module
from framework.cycle import run_cycle
from framework.glimmer.facts import LLMResponse, LLMUnavailableError
from framework.glimmer.label_step import LABEL_CALL_TIMEOUT_S, build_label_client
from framework.schemas.events import Event
from framework.store import EventStore
from framework.store.collector import run_collector
from framework.store.fact_store import FactStore

CANARY = "CANARY-TITLE-9C-77341"


def _cal(
    eid: str,
    key: str,
    hour: int,
    tags: tuple[str, ...] = (),
    busy: bool = True,
    cancelled: bool = False,
    day: int = 31,
) -> Event:
    from datetime import datetime, timedelta, timezone

    plus1 = timezone(timedelta(hours=1))
    start = datetime(2026, 10, day, hour, 0, tzinfo=plus1)
    end = datetime(2026, 10, day, hour + 1, 0, tzinfo=plus1)
    return cal_event(
        eid=eid,
        key=key,
        lm="seq1",
        time=start,
        end=end,
        tags=tags,
        busy=busy,
        cancelled=cancelled,
    )


class _FakeCalendar:
    """Duck-typed calendar collector with an attachable title sink."""

    def __init__(
        self,
        events: Sequence[Event],
        titles: dict[str, str],
        name: str = "calendar-personal",
    ) -> None:
        self._events = list(events)
        self._titles = dict(titles)
        self.name = name
        self.version = "calendar@0.1.0"
        self.title_sink: dict[str, str] | None = None
        self.polls = 0

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        self.polls += 1
        if self.title_sink is not None:
            self.title_sink.update(self._titles)
        return list(self._events), {"instances": {"fake": True}}


class _ScriptLabels:
    """Label stub: one answer per call, in call order."""

    def __init__(self, texts: list[str], finish: str | None = "stop") -> None:
        self._texts = list(texts)
        self.finish = finish
        self.calls = 0

    def complete(self, prompt: str) -> LLMResponse:
        if self.calls >= len(self._texts):
            raise AssertionError("stub called more times than scripted")
        text = self._texts[self.calls]
        self.calls += 1
        return LLMResponse(
            text=text,
            model_id="mock-model",
            latency_ms=5,
            finish_reason=self.finish,
            completion_tokens=4,
        )


class _Down:
    def __init__(self, message: str = "synthetic down") -> None:
        self.message = message
        self.calls = 0

    def complete(self, prompt: str) -> LLMResponse:
        self.calls += 1
        raise LLMUnavailableError(self.message)


def _label_row(target: Event, label: str, model_id: str = "mock-model") -> Event:
    from framework.collectors.common import event_id

    source = "glimmer-labels"
    source_id = f"{target.id}#label"
    return Event.model_validate(
        {
            "id": event_id(source, source_id),
            "subject_id": SUBJECT_ID,
            "source": source,
            "type": "calendar.label",
            "time": target.time.isoformat(),
            "source_id": source_id,
            "data": {
                "type": "calendar.label",
                "target_event_id": target.id,
                "label": label,
                "label_source": "local_model",
                "model_id": model_id,
                "valid": True,
            },
            "tier": "private",
            "collected_at": AS_OF.isoformat(),
            "collector_version": "glimmer-labels@0.1.0",
        }
    )


def _store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "sweep.db")


def _grep_canary(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if CANARY.encode() in data:
            hits.append(str(path))
    return hits


def _sweep(
    store: EventStore,
    collectors: list[Any],
    llm: Any,
    budget_s: float = 60.0,
    monotonic: Callable[[], float] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"budget_s": budget_s}
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    return sweep_module.run_label_sweep(
        store, SUBJECT_ID, collectors, llm, as_of=AS_OF, **kwargs
    )


def test_append_first_model_failure_loses_labels_never_events(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_app_1", "synth-app-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        result = _sweep(store, [fake], _Down())
        assert result.unavailable == 1
        kept = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types=None
        )
        assert any(e.id == row.id for e in kept)
        assert (
            store.events_between(
                SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types={"calendar.label"}
            )
            == []
        )
    finally:
        store.close()


def test_off_by_default_builds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "off.db"
    factory_calls: list[dict[str, Any]] = []

    def _factory(environ: Any, **kwargs: Any) -> Any:
        factory_calls.append(dict(kwargs))
        raise AssertionError("client must not be built while off")

    monkeypatch.setattr(cycle_main, "build_label_client", _factory)
    monkeypatch.delenv("IKIGAI_LABEL_CALENDAR_TITLES", raising=False)
    code = cycle_main.main(["labels", "--db", str(db)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "labels=disabled"
    assert factory_calls == []
    assert not db.exists()


def test_off_by_default_true_value_stays_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "off-true.db"
    monkeypatch.setattr(
        cycle_main,
        "build_label_client",
        lambda environ, **kwargs: (_ for _ in ()).throw(
            AssertionError("client must not be built while off")
        ),
    )
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "true")
    code = cycle_main.main(["labels", "--db", str(db)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "labels=disabled"
    assert not db.exists()


def test_budget_stops_new_calls_and_leaves_queue_unlabelled(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        rows = [
            _cal("evt_bud_1", "synth-bud-1@20261031T140000", 14),
            _cal("evt_bud_2", "synth-bud-2@20261031T150000", 15),
            _cal("evt_bud_3", "synth-bud-3@20261031T160000", 16),
        ]
        fake = _FakeCalendar(rows, {r.id: f"Invented block {r.id[-1]}" for r in rows})
        ticks = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0])
        llm = _ScriptLabels(['{"label": "iki-deep"}'] * 3)
        result = _sweep(store, [fake], llm, monotonic=lambda: next(ticks))
        assert result.called == 1
        assert llm.calls == 1
        labels = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types={"calendar.label"}
        )
        assert len(labels) == 1
    finally:
        store.close()


def test_client_timeout_bound_is_300s() -> None:
    import inspect

    assert LABEL_CALL_TIMEOUT_S == 300
    assert inspect.signature(build_label_client).parameters["timeout_s"].default == 300


def test_cli_builds_client_with_default_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "cli-timeout.db"
    seen: dict[str, Any] = {}

    class _Client:
        def complete(self, prompt: str) -> LLMResponse:
            raise LLMUnavailableError("synthetic down")

    def _factory(environ: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return _Client()

    monkeypatch.setattr(cycle_main, "build_label_client", _factory)
    monkeypatch.setattr(sweep_module, "CalendarIcsCollector", _FakeCalendarWithNoEvents)
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(["labels", "--db", str(db)])
    assert code == 0
    assert "timeout_s" not in seen
    assert "labels=" in capsys.readouterr().out


class _FakeCalendarWithNoEvents(_FakeCalendar):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        label = kwargs.get("label", "personal")
        super().__init__([], {}, name=f"calendar-{label}")


def test_invalid_answer_stored_and_not_reasked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_inv_1", "synth-inv-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Some invented block"})
        first = _sweep(store, [fake], _ScriptLabels(["prose, not a label"]))
        assert (first.invalid, first.valid) == (1, 0)
        rows = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types={"calendar.label"}
        )
        assert len(rows) == 1
        assert rows[0].data.valid is False  # type: ignore[attr-defined]

        class _MustNotRun:
            def complete(self, prompt: str) -> LLMResponse:
                raise AssertionError("invalid rows are not re-asked")

        second = _sweep(store, [fake], _MustNotRun())
        assert second.called == 0
        assert second.skipped_already_labelled == 1
    finally:
        store.close()


def test_unavailable_sweep_retries_next_time(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_ret_1", "synth-ret-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        first = _sweep(store, [fake], _Down())
        assert first.unavailable == 1
        second = _sweep(store, [fake], _ScriptLabels(['{"label": "iki-deep"}']))
        assert second.valid == 1
        rows = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types={"calendar.label"}
        )
        assert len(rows) == 1
    finally:
        store.close()


def test_conflicting_label_append_counts_never_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_con_1", "synth-con-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        planted = Event.model_validate(
            {
                "id": "evt_con_planted",
                "subject_id": SUBJECT_ID,
                "source": "glimmer-labels",
                "type": "calendar.label",
                "time": row.time.isoformat(),
                "source_id": f"{row.id}#label",
                "data": {
                    "type": "calendar.label",
                    "target_event_id": "evt_con_other",
                    "label": "iki-rest",
                    "label_source": "local_model",
                    "model_id": "mock-model",
                    "valid": True,
                },
                "tier": "private",
                "collected_at": AS_OF.isoformat(),
                "collector_version": "glimmer-labels@0.1.0",
            }
        )
        assert store.append_event(planted) is True
        result = _sweep(store, [fake], _ScriptLabels(['{"label": "iki-deep"}']))
        assert result.conflicts == 1
    finally:
        store.close()


def test_label_rows_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_rt_1", "synth-rt-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        result = _sweep(store, [fake], _ScriptLabels(['{"label": "iki-deep"}']))
        assert result.valid == 1
        rows = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF.replace(hour=23), types={"calendar.label"}
        )
        assert len(rows) == 1
        data = rows[0].data
        assert (data.target_event_id, data.label, data.valid) == (  # type: ignore[attr-defined]
            row.id,
            "iki-deep",
            True,
        )
        assert rows[0].source == "glimmer-labels"
        assert rows[0].tier == "private"
    finally:
        store.close()


def test_pre_9c_store_migration_keeps_old_rows_identical(tmp_path: Path) -> None:
    db = tmp_path / "mig.db"
    row = _cal("evt_mig_1", "synth-mig-1@20261031T140000", 14)
    before: list[str] = []
    store = EventStore(db_path=db)
    try:
        assert store.append_event(row) is True
        before = [
            e.model_dump_json()
            for e in store.events_between(SUBJECT_ID, AS_OF, AS_OF.replace(hour=23))
            if e.type != "calendar.label"
        ]
    finally:
        store.close()
    reopened = EventStore(db_path=db)
    try:
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        result = sweep_module.run_label_sweep(
            reopened,
            SUBJECT_ID,
            [fake],
            _ScriptLabels(['{"label": "iki-deep"}']),
            as_of=AS_OF,
            budget_s=60.0,
        )
        assert result.valid == 1
        after = [
            e.model_dump_json()
            for e in reopened.events_between(SUBJECT_ID, AS_OF, AS_OF.replace(hour=23))
            if e.type != "calendar.label"
        ]
        assert after == before
    finally:
        reopened.close()


def test_internal_labels_invisible_through_run_cycle(tmp_path: Path) -> None:
    db = tmp_path / "invis.db"
    model_row = _cal("evt_invis_model", "synth-invis-m@20261030T140000", 14, day=30)
    hand_row = _cal(
        "evt_invis_hand",
        "synth-invis-h@20261030T150000",
        15,
        tags=("iki-care",),
        day=30,
    )
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    try:
        fake = _FakeCalendar(
            [model_row, hand_row],
            {
                model_row.id: "Invented morning block",
                hand_row.id: "Invented midday block",
            },
        )
        sweep_result = sweep_module.run_label_sweep(
            store,
            SUBJECT_ID,
            [fake],
            _ScriptLabels(['{"label": "iki-care"}']),
            as_of=AS_OF,
            budget_s=60.0,
        )
        assert sweep_result.valid == 1
        llm = RecordingLLM(personal=(personal_batch(),))
        result, _ = run_cycle(AS_OF, SUBJECT_ID, store, fact_store, llm)
        assert llm.prompts != []
        for prompt in llm.prompts:
            assert "iki-care" not in prompt
        assert not any("iki-care" in key for key in result.snapshot.values)
        assert result.snapshot.values["calendar.busy_hours"] == 2.0
        for response in fact_store.fetch_responses(result.cycle_id, 1):
            assert "iki-care" not in response["content"]
        cycle = fact_store.fetch_cycle(result.cycle_id, 1)
        assert "iki-care" not in str(cycle["snapshot"])
    finally:
        fact_store.close()
        store.close()


def test_internal_invisibility_byte_identical_to_untagged_run(tmp_path: Path) -> None:
    def _run(rows: list[Event], labels: list[Any]) -> Any:
        db = tmp_path / f"cmp-{len(rows)}-{len(labels)}.db"
        store = EventStore(db_path=db)
        fact = FactStore(db_path=db)
        try:
            assert store.append_events(rows) == len(rows)
            for label_row in labels:
                assert store.append_event(label_row) is True
            llm = RecordingLLM(personal=(personal_batch(),))
            result, _ = run_cycle(AS_OF, SUBJECT_ID, store, fact, llm)
            return result, list(llm.prompts)
        finally:
            fact.close()
            store.close()

    model_row = _cal("evt_cmp_m", "synth-cmp-m@20261030T140000", 14, day=30)
    hand_row = _cal(
        "evt_cmp_h", "synth-cmp-h@20261030T150000", 15, tags=("iki-care",), day=30
    )
    plain_model = _cal("evt_cmp_m", "synth-cmp-m@20261030T140000", 14, day=30)
    plain_hand = _cal("evt_cmp_h", "synth-cmp-h@20261030T150000", 15, day=30)

    labelled, prompts_labelled = _run(
        [model_row, hand_row], [_label_row(model_row, "iki-care")]
    )
    plain, prompts_plain = _run([plain_model, plain_hand], [])
    assert prompts_labelled == prompts_plain
    assert labelled.snapshot.values == plain.snapshot.values


def test_replay_at_as_of_ignores_later_label(tmp_path: Path) -> None:
    db = tmp_path / "replay.db"
    row = _cal("evt_rep_1", "synth-rep-1@20261030T140000", 14, day=30)
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    try:
        assert store.append_event(row) is True
        llm = RecordingLLM(personal=(personal_batch(),))
        first, run1 = run_cycle(AS_OF, SUBJECT_ID, store, fact_store, llm)

        late = _label_row(row, "iki-deep").model_copy(
            update={"collected_at": AS_OF.replace(hour=14)}
        )
        assert store.append_event(late) is True
        llm2 = RecordingLLM(personal=(personal_batch(),))
        second, run2 = run_cycle(AS_OF, SUBJECT_ID, store, fact_store, llm2)
        assert second.prompt_hash == first.prompt_hash
        assert second.cycle_id == first.cycle_id
        assert run2 == run1
    finally:
        fact_store.close()
        store.close()


def _run_canary_sweep(
    tmp_path: Path,
    llm: Any,
    capsys: Any,
    caplog: Any,
) -> Any:
    import logging

    store = EventStore(tmp_path / "canary.db")
    try:
        row = _cal("evt_can_1", "synth-can-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: CANARY})
        with caplog.at_level(logging.DEBUG):
            result = sweep_module.run_label_sweep(
                store, SUBJECT_ID, [fake], llm, as_of=AS_OF, budget_s=60.0
            )
        captured = capsys.readouterr()
        assert CANARY not in captured.out
        assert CANARY not in captured.err
        assert all(CANARY not in r.getMessage() for r in caplog.records)
        assert CANARY not in repr(result)
        assert _grep_canary(tmp_path) == []
        cursor = store.get_cursor("calendar-personal")
        assert CANARY not in str(cursor)
        for event in store.events_between(SUBJECT_ID, AS_OF, AS_OF.replace(hour=23)):
            assert CANARY not in event.model_dump_json()
        return result
    finally:
        store.close()


def test_canary_unavailable(tmp_path: Path, capsys: Any, caplog: Any) -> None:
    result = _run_canary_sweep(tmp_path, _Down(), capsys, caplog)
    assert result.unavailable == 1


def test_canary_timeout(tmp_path: Path, capsys: Any, caplog: Any) -> None:
    result = _run_canary_sweep(tmp_path, _Down("timeout"), capsys, caplog)
    assert result.unavailable == 1


def test_canary_malformed_answer(tmp_path: Path, capsys: Any, caplog: Any) -> None:
    result = _run_canary_sweep(
        tmp_path, _ScriptLabels(["prose about the invented block"]), capsys, caplog
    )
    assert result.invalid == 1


def test_canary_exception_message(tmp_path: Path, capsys: Any, caplog: Any) -> None:
    class _Boom:
        def complete(self, prompt: str) -> LLMResponse:
            raise RuntimeError(f"synthetic failure carrying {CANARY}")

    result = _run_canary_sweep(tmp_path, _Boom(), capsys, caplog)
    assert result.errors_by_type == {"RuntimeError": 1}


def test_canary_exception_cli_reports_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "canary-cli.db"

    class _Boom:
        def complete(self, prompt: str) -> LLMResponse:
            raise RuntimeError(f"synthetic failure carrying {CANARY}")

    row = _cal("evt_can_cli", "synth-can-cli@20261031T140000", 14)
    fake = _FakeCalendar([row], {row.id: CANARY})

    def _collector(*, label: str, title_sink: Any) -> Any:
        fake.title_sink = title_sink
        return fake

    monkeypatch.setattr(sweep_module, "CalendarIcsCollector", _collector)
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: _Boom())
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(["labels", "--db", str(db)])
    assert code == 0
    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    assert "RuntimeError" in captured.out
    assert _grep_canary(tmp_path) == []


def test_canary_helper_positive_control(tmp_path: Path) -> None:
    planted = tmp_path / "planted.txt"
    planted.write_text(CANARY, encoding="utf-8")
    store = EventStore(tmp_path / "control.db")
    try:
        row = _cal("evt_ctl_1", "synth-ctl-1@20261031T140000", 14, tags=(CANARY,))
        assert store.append_event(row) is True
        hits = _grep_canary(tmp_path)
        assert len(hits) == 2
    finally:
        store.close()


def test_canary_bad_ics_reports_clean_collector_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from framework.collectors.calendar_ics import CalendarIcsCollector
    from framework.collectors.common import HttpResponse

    db = tmp_path / "badics.db"
    body = b"BEGIN:VEVENT\nSUMMARY:" + CANARY.encode() + b"\nDTSTART:bad\nEND:VEVENT\n"

    def _http(url: str, headers: dict[str, str]) -> HttpResponse:
        return HttpResponse(status=200, headers={}, body=body)

    def _collector(*, label: str, title_sink: Any) -> Any:
        return CalendarIcsCollector(
            http_get=_http,
            now_fn=lambda: AS_OF,
            label=label,
            title_sink=title_sink,
        )

    class _Never:
        def complete(self, prompt: str) -> LLMResponse:
            raise AssertionError("no model call on a failed poll")

    monkeypatch.setattr(sweep_module, "CalendarIcsCollector", _collector)
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: _Never())
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    monkeypatch.setenv("ICAL_URL_PERSONAL", "https://example.invalid/synthetic.ics")
    monkeypatch.delenv("ICAL_URL", raising=False)
    code = cycle_main.main(["labels", "--db", str(db)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err == "error: CollectorError\n"
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    assert _grep_canary(tmp_path) == []


def test_run_collector_with_sink_opaque_cursor(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "cursor.db")
    try:
        row = _cal("evt_cur_1", "synth-cur-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        assert run_collector(store, fake) == (1, 0)
        assert CANARY not in str(store.get_cursor("calendar-personal"))
    finally:
        store.close()


def test_model_label_reaches_snapshot_and_rollup_through_run_cycle(
    tmp_path: Path,
) -> None:
    db = tmp_path / "overlay.db"
    row = _cal("evt_ovl_1", "synth-ovl-1@20261030T140000", 14, day=30)
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    try:
        assert store.append_event(row) is True
        assert store.append_event(_label_row(row, "iki-deep")) is True
        llm = RecordingLLM(personal=(personal_batch(),))
        result, _ = run_cycle(AS_OF, SUBJECT_ID, store, fact_store, llm)
        assert result.snapshot.values["tag_hours.iki-deep"] == 1.0
        assert result.snapshot.values["period.last.tag_hours.iki-deep"] == 1.0
        assert result.snapshot.values["period.prior.tag_hours.iki-deep"] == 0.0
        assert result.snapshot.values["period.earlier.tag_hours.iki-deep"] == 0.0
    finally:
        fact_store.close()
        store.close()


def test_uppercase_internal_label_statement_dropped(tmp_path: Path) -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases
    from framework.glimmer.facts import extract_facts

    row = cal_event(
        eid="evt_internal_upper",
        key="synth-internal-upper@20261030T140000",
        lm="seq1",
        time=dt(30, 14),
        end=dt(30, 15),
        tags=("iki-care",),
    )
    aliases = personal_aliases((row,))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Quiet IKI-CARE hours continued in the last period",
                    "evidence": [aliases[row.id]],
                },
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [row], llm)
    assert [d.code for d in result.dropped] == ["FACT_INTERNAL_LABEL"]


def test_canary_real_collector_stores_no_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from framework.collectors.calendar_ics import CalendarIcsCollector
    from framework.collectors.common import HttpResponse

    body = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//ikigai-loop//synthetic//EN\n"
        b"BEGIN:VEVENT\nUID:synthetic-realcan-1\nDTSTAMP:20261025T080000Z\n"
        b"DTSTART:20261102T150000Z\nDTEND:20261102T160000Z\n"
        b"LAST-MODIFIED:20261025T090000Z\nSUMMARY:" + CANARY.encode() + b"\n"
        b"END:VEVENT\nEND:VCALENDAR\n"
    )

    def _http(url: str, headers: dict[str, str]) -> HttpResponse:
        return HttpResponse(status=200, headers={}, body=body)

    monkeypatch.setenv("ICAL_URL_PERSONAL", "https://example.invalid/synth.ics")
    monkeypatch.delenv("ICAL_URL", raising=False)
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)

    class _RecordingLabels:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str) -> LLMResponse:
            self.prompts.append(prompt)
            return LLMResponse(
                text='{"label": "iki-deep"}',
                model_id="mock-model",
                latency_ms=5,
                finish_reason="stop",
                completion_tokens=4,
            )

    store = EventStore(tmp_path / "realcan.db")
    try:
        collector = CalendarIcsCollector(
            http_get=_http, now_fn=lambda: AS_OF, label="personal"
        )
        llm = _RecordingLabels()
        result = sweep_module.run_label_sweep(
            store, SUBJECT_ID, [collector], llm, as_of=AS_OF, budget_s=60.0
        )
        assert result.called == 1
        assert any(CANARY in prompt for prompt in llm.prompts)
        assert _grep_canary(tmp_path) == []
        assert CANARY not in str(store.get_cursor("calendar-personal"))
        from datetime import timedelta as _td

        for event in store.events_between(SUBJECT_ID, AS_OF, AS_OF + _td(days=14)):
            assert CANARY not in event.model_dump_json()
    finally:
        store.close()


def test_row_at_window_far_edge_gets_labelled(tmp_path: Path) -> None:
    from datetime import timedelta

    store = _store(tmp_path)
    try:
        start = AS_OF + timedelta(days=13)
        row = cal_event(
            eid="evt_edge_13",
            key="synth-edge-13@20261113T130000",
            lm="seq1",
            time=start,
            end=start + timedelta(hours=1),
            tags=(),
        )
        fake = _FakeCalendar([row], {row.id: "Invented far-edge block"})
        result = _sweep(store, [fake], _ScriptLabels(['{"label": "iki-deep"}']))
        assert result.valid == 1
        rows = store.events_between(
            SUBJECT_ID, AS_OF, AS_OF + timedelta(days=14), types={"calendar.label"}
        )
        assert len(rows) == 1
    finally:
        store.close()


def test_label_append_refused_counts_conflict_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    try:
        row = _cal("evt_ref_1", "synth-ref-1@20261031T140000", 14)
        fake = _FakeCalendar([row], {row.id: "Solo drafting block"})
        real_append = store.append_event

        def _refuse(event: Event) -> bool:
            if event.type == "calendar.label":
                return False
            return bool(real_append(event))

        monkeypatch.setattr(store, "append_event", _refuse)
        result = _sweep(store, [fake], _ScriptLabels(['{"label": "iki-deep"}']))
        assert result.conflicts == 1
    finally:
        store.close()


def _busy_row_near_now(eid: str, key: str) -> Event:
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC) - timedelta(hours=1)
    return cal_event(
        eid=eid,
        key=key,
        lm="seq1",
        time=start,
        end=start + timedelta(hours=1),
        tags=(),
    )


def _collector_with_row(row: Event, title: str) -> Any:
    fake = _FakeCalendar([row], {row.id: title})

    def _factory(*, label: str, title_sink: Any) -> Any:
        fake.title_sink = title_sink
        return fake

    return _factory


def test_labels_budget_zero_makes_no_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "b0.db"
    calls: list[str] = []

    class _Client:
        def complete(self, prompt: str) -> LLMResponse:
            calls.append(prompt)
            raise AssertionError("no model call on a zero budget")

    row = _busy_row_near_now("evt_b0_1", "synth-b0-1@now")
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: _Client())
    monkeypatch.setattr(
        sweep_module,
        "CalendarIcsCollector",
        _collector_with_row(row, "Solo drafting block"),
    )
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(["labels", "--db", str(db), "--budget-s", "0"])
    assert code == 0
    assert calls == []
    assert "labels=" in capsys.readouterr().out


def test_labels_positive_budget_calls_once_for_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    db = tmp_path / "b60.db"
    row = _busy_row_near_now("evt_b60_1", "synth-b60-1@now")
    llm = _ScriptLabels(['{"label": "iki-deep"}'])
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: llm)
    monkeypatch.setattr(
        sweep_module,
        "CalendarIcsCollector",
        _collector_with_row(row, "Solo drafting block"),
    )
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(["labels", "--db", str(db), "--budget-s", "60"])
    assert code == 0
    assert llm.calls == 1
    assert "called=1" in capsys.readouterr().out


def test_labels_sweeps_every_requested_label_and_adds_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from framework.glimmer.label_step import LabelStepResult

    db = tmp_path / "multi.db"
    seen: list[tuple[Any, float]] = []

    def _spy(*args: Any, **kwargs: Any) -> LabelStepResult:
        collectors = args[2]
        seen.append((list(collectors), kwargs["budget_s"]))
        return LabelStepResult(called=len(seen), valid=len(seen))

    monkeypatch.setattr(cycle_main, "run_label_sweep", _spy)
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: object())
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(
        ["labels", "--db", str(db), "--label", "personal", "--label", "home"]
    )
    assert code == 0
    assert [labels for labels, _ in seen] == [["personal"], ["home"]]
    assert "called=3" in capsys.readouterr().out


def test_labels_budget_is_shared_across_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    import time as stdlib_time

    from framework.glimmer.label_step import LabelStepResult

    db = tmp_path / "shared.db"
    clock = [0.0]
    budgets: list[float] = []

    def _spy(*args: Any, **kwargs: Any) -> LabelStepResult:
        budgets.append(kwargs["budget_s"])
        if len(budgets) == 1:
            clock[0] += 100.0
        return LabelStepResult()

    monkeypatch.setattr(stdlib_time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cycle_main, "run_label_sweep", _spy)
    monkeypatch.setattr(cycle_main, "build_label_client", lambda environ: object())
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT_ID)
    code = cycle_main.main(
        [
            "labels",
            "--db",
            str(db),
            "--budget-s",
            "240",
            "--label",
            "personal",
            "--label",
            "home",
        ]
    )
    assert code == 0
    assert budgets == [240, 140]
    assert "labels=" in capsys.readouterr().out


def test_labels_missing_subject_exits_2_without_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def _factory(environ: Any, **kwargs: Any) -> Any:
        raise AssertionError("no client without a subject")

    monkeypatch.setattr(cycle_main, "build_label_client", _factory)
    monkeypatch.setenv("IKIGAI_LABEL_CALENDAR_TITLES", "1")
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    code = cycle_main.main(["labels", "--db", str(tmp_path / "nosub.db")])
    assert code == 2
    err = capsys.readouterr().err
    assert "IKIGAI_SUBJECT_ID" in err
    assert "\n" not in err.strip()
