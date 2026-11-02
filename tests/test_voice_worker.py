"""Ticket 14 Step 5: the voice worker end to end on fakes (D18-D23, D26-D28).

One shared fake harness: fake Telegram on the _open_url seam, a fake
transcriber runner, a fake compile client and per-profile fake Wonder
clients that count calls, and a frozen clock. No network, no sockets,
no real binary, no real environment. All data is made up.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from telegram_fake import (  # noqa: F401  (autouse fixture)
    FAKE_API_BASE,
    FAKE_BOT_VALUE,
    FAKE_CHAT_ID,
    FakeTelegram,
    no_sockets,
)

from framework.proposal.core import ProposalResult, WonderRequest, WonderResponse
from framework.proposal.muse_client import RunResult
from framework.store import EventStore
from framework.store.proposal_store import ProposalStore
from framework.telegram import client as client_module
from framework.telegram.client import TelegramClient
from framework.telegram.ledger import CardLedger
from framework.telegram.models import Card, ChartData, ChartSeries, TallyItem, VoiceNote
from framework.voice.ledger import VoiceLedger
from framework.voice.transcribe import MuseVoiceTranscriber
from framework.voice.worker import (
    VoiceDeps,
    build_voice_deps,
    process_one,
)

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-voice-1"

SAT_SLOT = datetime(2026, 10, 31, 18, 0, tzinfo=MADRID)
SAT_RECEIVED = datetime(2026, 10, 31, 18, 5, tzinfo=MADRID)
SUN_SLOT = datetime(2026, 11, 1, 18, 0, tzinfo=MADRID)

WRITE_ID = "cm-write"
WRITE2_ID = "cm-write2"
REST_ID = "cm-rest"

NEGATION = "Don't drop the write-up, I just can't do it today"

COMMITMENTS_JSON = [
    {
        "id": WRITE_ID,
        "profile_id": "builder",
        "title": "Finish the write-up",
        "kind": "write",
        "dimension": "love",
        "evidence": "tap",
    },
    {
        "id": WRITE2_ID,
        "profile_id": "builder",
        "title": "Draft the release notes",
        "kind": "write",
        "dimension": "good_at",
        "evidence": "tap",
    },
    {
        "id": REST_ID,
        "profile_id": "disconnect",
        "title": "Evening rest",
        "kind": "rest",
        "dimension": "limit",
        "evidence": "tap",
    },
    {
        "id": "cm-rest2",
        "profile_id": "disconnect",
        "title": "Sip synthetic tea",
        "kind": "rest",
        "dimension": "limit",
        "evidence": "tap",
    },
]


def correction_json(
    operation: str,
    commitment_id: str | None,
    until: str | None,
    question: str | None = None,
) -> str:
    return json.dumps(
        {
            "operation": operation,
            "commitment_id": commitment_id,
            "until": until,
            "question": question,
        }
    )


class FakeRunner:
    """Scripted argv router: ffmpeg ok, transcribe scripted per test."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.transcribe_result: RunResult = RunResult(0, b"heard words", False)
        self.ffmpeg_result: RunResult = RunResult(0, b"", False)
        self.raise_on_ffmpeg: BaseException | None = None
        self.raise_on_transcribe: BaseException | None = None

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        self.calls.append(list(argv))
        if "transcribe" in list(argv):
            if self.raise_on_transcribe is not None:
                raise self.raise_on_transcribe
            return self.transcribe_result
        if self.raise_on_ffmpeg is not None:
            raise self.raise_on_ffmpeg
        return self.ffmpeg_result


class FakeCompileClient:
    """Scripted compile client; counts calls, never touches the network."""

    transport = "fake"
    harness_rules_file = None

    def __init__(self, script: list[str | BaseException] | None = None) -> None:
        self.script: list[str | BaseException] = list(script or [])
        self.requests: list[WonderRequest] = []

    @property
    def transport_version(self) -> str | None:
        return "muse-test-1.0"

    def complete(self, request: WonderRequest) -> WonderResponse:
        self.requests.append(request)
        if not self.script:
            raise AssertionError("compile client called with empty script")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return WonderResponse(
            text=item,
            model_reported="fake",
            latency_ms=5,
            finish_reason="stop",
            prompt_tokens=3,
            completion_tokens=7,
            reasoning_tokens=None,
        )


@dataclass
class Harness:
    """One shared fake world per test: db, telegram, models, clock."""

    tmp_path: Path
    db: Path
    fake: FakeTelegram
    runner: FakeRunner
    compile_client: FakeCompileClient
    wonder_calls: dict[str, int] = field(default_factory=dict)
    result_script: dict[str, list[Callable[..., ProposalResult]]] = field(
        default_factory=dict
    )
    now: datetime = SAT_RECEIVED
    deps: VoiceDeps | None = None
    environ: dict[str, str] = field(default_factory=dict)
    settings_path: Path | None = None
    raise_in_propose: BaseException | None = None

    def propose(self, **kwargs: Any) -> tuple[ProposalResult, ...]:
        if self.raise_in_propose is not None:
            raise self.raise_in_propose
        out: list[ProposalResult] = []
        for profile_id in kwargs["profiles"]:
            self.wonder_calls[profile_id] = self.wonder_calls.get(profile_id, 0) + 1
            script = self.result_script.get(profile_id, [])
            if script:
                out.append(script.pop(0)(**kwargs))
            else:
                out.append(default_result(profile_id, kwargs, self))
        for result in out:
            store = ProposalStore(self.db)
            try:
                store.record(result, snapshot={})
            finally:
                store.close()
        return tuple(out)


def default_result(profile_id: str, kwargs: Any, harness: Harness) -> ProposalResult:
    """A clean proposal for the first eligible commitment, no claims."""
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Action, Briefing, Section

    slot = kwargs["slot"]
    eligible = kwargs["eligible_by_profile"][profile_id]
    if not eligible:
        return ProposalResult(
            kind="noop",
            profile_id=profile_id,
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=1,
            slot=slot,
            hour=None,
            briefing=None,
            fallback=None,
            reason_codes=("ELIGIBLE_EMPTY",),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="h",
        )
    commitment = eligible[0]
    hour = TimeInterval(
        start=slot.replace(hour=19, minute=0, second=0, microsecond=0),
        end=slot.replace(hour=19, minute=25, second=0, microsecond=0),
    )
    briefing = Briefing(
        id=f"briefing-{profile_id}-new",
        profile_id=profile_id,
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="actions",
                actions=[
                    Action(
                        id="action-1",
                        commitment_id=commitment.id,
                        kind=commitment.kind,  # type: ignore[arg-type]
                        text=commitment.title,
                        dimension=commitment.dimension,  # type: ignore[arg-type]
                        proposed_start=hour.start,
                        proposed_end=hour.end,
                    )
                ],
            )
        ],
    )
    return ProposalResult(
        kind="proposal",
        profile_id=profile_id,
        subject_id=SUBJECT,
        cycle_id="cycle-1",
        run=1,
        slot=slot,
        hour=hour,
        briefing=briefing,
        fallback=None,
        reason_codes=(),
        attempts=(),
        cycle_age_s=0.0,
        prompt_hash="h",
    )


def make_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    compile_script: list[str | BaseException] | None = None,
    transcript: bytes = b"heard words here",
    commitments_json: list[dict[str, object]] | None = None,
) -> Harness:
    """Wire fakes: telegram, transcriber, compile, terms, commitments."""

    db = tmp_path / "voice-work.db"
    fake = FakeTelegram()
    monkeypatch.setattr(client_module, "_open_url", fake)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))

    terms_dir = tmp_path / "criteria"
    terms_dir.mkdir()
    (terms_dir / "deny-terms.txt").write_text(
        "synthetic-denied-term\n", encoding="utf-8"
    )
    commitments_file = tmp_path / "commitments.json"
    commitments_file.write_text(
        json.dumps(
            commitments_json if commitments_json is not None else COMMITMENTS_JSON
        ),
        encoding="utf-8",
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"contributor_mode_enabled": False}), encoding="utf-8"
    )
    environ = {
        "IKIGAI_SUBJECT_ID": SUBJECT,
        "IKIGAI_COMMITMENTS_FILE": str(commitments_file),
        "HIDDEN_CRITERIA_DIR": str(terms_dir),
        "MUSE_BIN": "/bin/muse-synthetic",
        "MUSE_CONTRIBUTOR_MODE": "0",
    }
    runner = FakeRunner()
    runner.transcribe_result = RunResult(0, transcript, False)
    compile_client = FakeCompileClient(
        compile_script if compile_script is not None else []
    )
    harness = Harness(
        tmp_path=tmp_path,
        db=db,
        fake=fake,
        runner=runner,
        compile_client=compile_client,
    )

    def _compile_factory(terms: tuple[str, ...], available: bool) -> FakeCompileClient:
        return compile_client

    def _wonder_factory(terms: tuple[str, ...], available: bool) -> FakeCompileClient:
        return compile_client

    transcriber = MuseVoiceTranscriber(
        muse_bin="/bin/muse-synthetic",
        ffmpeg_bin="/bin/ffmpeg-synthetic",
        runner=runner,
        environ=dict(environ),
        settings_path=settings,
    )
    deps = build_voice_deps(
        environ,
        client=TelegramClient(api_base=FAKE_API_BASE),
        db_path=db,
        now_fn=lambda: harness.now,
        transcriber=transcriber,
        make_compile_client=_compile_factory,  # type: ignore[arg-type]
        make_wonder_client=_wonder_factory,  # type: ignore[arg-type]
        propose_fn=harness.propose,  # type: ignore[arg-type]
    )
    harness.deps = deps
    harness.environ = environ
    harness.settings_path = settings
    return harness


def deps_of(harness: Harness) -> VoiceDeps:
    assert harness.deps is not None
    return harness.deps


def seed_chart() -> ChartData:
    series = ChartSeries(label="Code", earlier=1.0, prior=4.75, last=1.75)
    return ChartData(
        period_labels=("Prior", "Last", "Now"),
        screen=(series,),
        pushes=series,
        tally=(TallyItem(label="Items", count=2),),
    )


def seed_old_card(
    harness: Harness,
    *,
    slot: datetime = SAT_SLOT,
    statements: Sequence[str] = (),
    message_id: int = 700,
    titles: tuple[str, str] = ("Finish the write-up", "Evening rest"),
) -> Card:
    """Save an old two-side card with chart and message map, like send_card."""
    from datetime import timedelta

    start = slot.replace(hour=19, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=25)
    card = Card(
        slot=slot,
        since_line="Since 15:30: synthetic build notes.",
        proposals=(  # type: ignore[arg-type]
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": titles[0],
                "start": start,
                "end": end,
            },
            {
                "letter": "B",
                "kind": "proposal",
                "profile": "Disconnect",
                "title": titles[1],
                "start": start,
                "end": end,
            },
        ),
        statements=tuple(statements),
    )
    ledger = CardLedger(harness.db)
    ledger.save_card(card)
    ledger.save_chart(card.card_id, seed_chart())
    ledger.save_card_message(message_id, card.card_id)
    return card


def seed_results(
    harness: Harness,
    card: Card,
    *,
    cycle_id: str = "cycle-1",
    claims_a: Sequence[tuple[str, str, list[str], list[tuple[str, float]]]] = (),
    claims_b: Sequence[tuple[str, str, list[str], list[tuple[str, float]]]] = (),
) -> None:
    """Record stored proposal rows for the slot, one per profile.

    Each claim is ``(claim_id, text, fact_ids, [(metric_id, value)])``.
    """
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Action, Briefing, Claim, MetricRef, Section

    store = ProposalStore(harness.db)
    try:
        for profile_id, side, claims in (
            ("builder", card.proposals[0], claims_a),
            ("disconnect", card.proposals[1], claims_b),
        ):
            sections = [
                Section(
                    type="overall_state",
                    actions=[],
                    claims=[
                        Claim(
                            id=claim_id,
                            text=text,
                            fact_ids=list(fact_ids),
                            metric_refs=[
                                MetricRef(metric_id=metric_id, value=value)
                                for metric_id, value in metrics
                            ],
                        )
                        for claim_id, text, fact_ids, metrics in claims
                    ],
                ),
                Section(
                    type="actions",
                    claims=[],
                    actions=[
                        Action(
                            id=f"action-{profile_id}",
                            commitment_id=WRITE_ID
                            if profile_id == "builder"
                            else REST_ID,
                            kind="write" if profile_id == "builder" else "rest",
                            text=side.title,
                            dimension="love" if profile_id == "builder" else "limit",
                            proposed_start=side.start,
                            proposed_end=side.end,
                        )
                    ],
                ),
            ]
            briefing = Briefing(
                id=f"briefing-{profile_id}-old",
                profile_id=profile_id,
                subject_id=SUBJECT,
                slot=card.slot,
                sections=sections,
            )
            store.record(
                ProposalResult(
                    kind="proposal",
                    profile_id=profile_id,
                    subject_id=SUBJECT,
                    cycle_id=cycle_id,
                    run=1,
                    slot=card.slot,
                    hour=TimeInterval(start=side.start, end=side.end),
                    briefing=briefing,
                    fallback=None,
                    reason_codes=(),
                    attempts=(),
                    cycle_age_s=0.0,
                    prompt_hash="seed",
                ),
                snapshot={},
            )
    finally:
        store.close()


def seed_note(
    harness: Harness,
    message_id: int,
    *,
    said_at: datetime | None = None,
    received_at: datetime | None = None,
    reply_to: int | None = None,
    file_id: str = "synthetic-file-id",
    file_size: int | None = 4100,
    update_id: int | None = None,
) -> None:
    """Write one durable voice row through the poller's insert path."""
    said = said_at if said_at is not None else SAT_RECEIVED
    received = received_at if received_at is not None else harness.now
    note = VoiceNote(
        message_id=message_id,
        date=int(said.timestamp()),
        file_id=file_id,
        file_unique_id=f"uniq-{message_id}",
        duration_s=4,
        mime_type="audio/ogg",
        file_size=file_size,
        reply_to_message_id=reply_to,
    )
    inserted = CardLedger(harness.db).record_voice_note(
        note,
        update_id if update_id is not None else 5000 + message_id,
        received.isoformat(),
    )
    assert inserted is True


def claim_and_process(harness: Harness, at: datetime | None = None) -> str:
    """Claim the oldest due row and run one note; returns the outcome."""
    moment = at if at is not None else harness.now
    row = VoiceLedger(harness.db).claim_next(moment)
    assert row is not None
    return process_one(deps_of(harness), row)


def sent_texts(harness: Harness) -> list[dict[str, Any]]:
    """Every sendMessage payload the fake served, oldest first."""
    out: list[dict[str, Any]] = []
    for method, _, _, body, _ in harness.fake.requests:
        if method == "sendMessage":
            out.append(json.loads(body.decode("utf-8")))
    return out


def method_order(harness: Harness) -> list[str]:
    return [method for method, _, _, _, _ in harness.fake.requests]


def voice_events(harness: Harness) -> list[Any]:
    store = EventStore(harness.db)
    try:
        return store.events_between(
            SUBJECT,
            datetime(2000, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 1, tzinfo=UTC),
            types=["app.voice_note"],
        )
    finally:
        store.close()


def all_events(harness: Harness) -> list[Any]:
    store = EventStore(harness.db)
    try:
        return store.events_between(
            SUBJECT,
            datetime(2000, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 1, tzinfo=UTC),
        )
    finally:
        store.close()


def test_applied_with_card_reproposes_only_changed_side(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transcript = b"skip the write-up today"
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=transcript,
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    said = datetime(2026, 10, 31, 18, 4, tzinfo=MADRID)
    received = harness.now - timedelta(seconds=12.5)
    seed_note(harness, 91, said_at=said, received_at=received, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    assert harness.wonder_calls == {"builder": 1}

    row = VoiceLedger(harness.db).load(91)
    assert row is not None and row.new_card_id is not None
    assert row.operation == "skip" and row.until_value == "today"
    assert row.matched_card_id == old.card_id
    assert row.status == "done" and row.outcome == "applied_card"

    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    assert new.replaces_card_id == old.card_id
    assert new.slot == old.slot
    assert new.correction_line == "Skipped: Finish the write-up (today)."
    assert render_first_line(new) == new.correction_line
    assert [side.letter for side in new.proposals] == ["A", "B"]
    assert new.proposals[0].title == "Draft the release notes"
    assert new.proposals[0].profile == "Builder"
    assert (new.proposals[1].title, new.proposals[1].profile) == (
        "Evening rest",
        "Disconnect",
    )
    assert new.proposals[1].start == old.proposals[1].start
    assert new.proposals[1].end == old.proposals[1].end
    assert new.statements == ("A · Builder", "B · Disconnect")

    order = method_order(harness)
    assert order.index("sendPhoto") < order.index("sendMessage")
    texts = sent_texts(harness)
    assert len(texts) == 1
    reply = texts[0]["text"]
    assert reply.startswith('Heard: "skip the write-up today"')
    assert "Skipped: Finish the write-up (today)." in reply
    assert "New card above. Took 12.5s." in reply
    assert texts[0]["reply_parameters"]["message_id"] == 91

    events = voice_events(harness)
    assert len(events) == 1
    assert events[0].data.outcome == "applied_card"
    assert events[0].data.new_card_id == row.new_card_id


def render_first_line(card: Card) -> str:
    from framework.telegram.models import render_card_text

    return render_card_text(card).splitlines()[0]


def test_applied_stands_for_off_card_drop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("drop", REST_ID, "open")],
        transcript=b"drop the evening rest for good",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    # Narrow the old card to the builder side only: rest was never offered.
    ledger = CardLedger(harness.db)
    single = Card(
        slot=old.slot,
        since_line=old.since_line,
        proposals=(old.proposals[0],),
        statements=(),
    )
    ledger.save_card(single)
    ledger.save_chart(single.card_id, seed_chart())
    ledger.save_card_message(701, single.card_id)
    seed_note(harness, 92, reply_to=701)

    assert claim_and_process(harness) == "applied_card_stands"
    assert harness.wonder_calls == {}
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "Dropped: Evening rest." in reply
    assert "The card stands. Took" in reply
    row = VoiceLedger(harness.db).load(92)
    assert row is not None and row.new_card_id is None


def test_keep_never_reproposes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("keep", WRITE_ID, None)],
        transcript=b"keep the write-up as it is",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 93, reply_to=700)

    assert claim_and_process(harness) == "applied_card_stands"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "Kept: Finish the write-up." in reply


def test_applied_no_card_still_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    seed_note(harness, 94)

    assert claim_and_process(harness) == "applied_no_card"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "Skipped: Finish the write-up (today)." in reply
    assert "The card stands" not in reply
    assert "New card above" not in reply
    row = VoiceLedger(harness.db).load(94)
    assert row is not None and row.matched_card_id is None
    assert len(voice_events(harness)) == 1


def test_negation_lands_as_skip_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=NEGATION.encode(),
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 95, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(95)
    assert row is not None
    assert row.operation == "skip" and row.until_value == "today"
    assert row.transcript == NEGATION
    reply = sent_texts(harness)[0]["text"]
    assert f'Heard: "{NEGATION}"' in reply


def test_spanish_transcript_compiles_through_fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transcript = "Salta el informe de hoy"
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=transcript.encode(),
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 96, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    assert harness.compile_client.requests[0].prompt.find(transcript) != -1
    reply = sent_texts(harness)[0]["text"]
    assert f'Heard: "{transcript}"' in reply


def test_question_asks_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("none", None, None, "Which commitment do you mean?")
        ],
        transcript=b"something unclear here",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 101, reply_to=700)

    assert claim_and_process(harness) == "question"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "Which commitment do you mean?" in reply
    assert "Nothing changed. Took" in reply
    assert len(all_events(harness)) == 1  # only the voice_note record


def test_question_failing_scan_is_not_understood(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("none", None, None, "What about synthetic-denied-term?")
        ],
        transcript=b"something unclear here",
    )
    seed_note(harness, 102)

    assert claim_and_process(harness) == "not_understood"
    reply = sent_texts(harness)[0]["text"]
    assert "I didn't get that, nothing changed." in reply
    assert "synthetic-denied-term" not in reply


def test_validation_failure_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("defer", WRITE_ID, "slot")],
        transcript=b"move the write-up somehow",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 103, reply_to=700)

    assert claim_and_process(harness) == "not_understood"
    assert harness.wonder_calls == {}
    row = VoiceLedger(harness.db).load(103)
    assert row is not None
    assert "CORRECTION_PAIR_INVALID" in (row.validation_codes or "")
    reply = sent_texts(harness)[0]["text"]
    assert "I didn't get that, nothing changed." in reply


def test_unparseable_reply_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=["not json at all {{{"],
        transcript=b"mumble mumble",
    )
    seed_note(harness, 104)

    assert claim_and_process(harness) == "not_understood"
    assert sent_texts(harness)[0]["text"].endswith("nothing changed. Took 0.0s.")


def test_blocked_scan_stores_no_transcript_and_echoes_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip it synthetic-denied-term today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 105, reply_to=700)

    assert claim_and_process(harness) == "outbound_blocked"
    assert harness.compile_client.requests == []
    row = VoiceLedger(harness.db).load(105)
    assert row is not None and row.transcript is None
    reply = sent_texts(harness)[0]["text"]
    assert reply == "I couldn't use that note. Nothing changed. Took 0.0s."
    assert len(voice_events(harness)) == 1


def test_silence_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.proposal.muse_client import RunResult

    harness = make_harness(monkeypatch, tmp_path, transcript=b"heard words")
    harness.runner.transcribe_result = RunResult(7, b"", False)
    seed_note(harness, 106)

    assert claim_and_process(harness) == "silence"
    assert harness.compile_client.requests == []
    reply = sent_texts(harness)[0]["text"]
    assert reply == "I heard no words in that note. Nothing changed. Took 0.0s."


def test_unreadable_clip_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.proposal.muse_client import RunResult

    harness = make_harness(monkeypatch, tmp_path, transcript=b"heard words")
    harness.runner.transcribe_result = RunResult(3, b"", False)
    seed_note(harness, 107)

    assert claim_and_process(harness) == "unreadable"
    reply = sent_texts(harness)[0]["text"]
    assert reply == "I couldn't read that clip. Nothing changed. Took 0.0s."


def test_unreadable_getfile_is_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(monkeypatch, tmp_path)
    seed_note(harness, 108, file_id="gone")

    assert claim_and_process(harness) == "unreadable"
    assert harness.runner.calls == []


def test_oversize_file_fails_before_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(monkeypatch, tmp_path)
    seed_note(harness, 109, file_size=6_000_000)

    assert claim_and_process(harness) == "unreadable"
    assert "getFile" not in method_order(harness)
    assert "download" not in method_order(harness)
    assert harness.runner.calls == []


def test_removal_compile_unavailable_waits_then_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.proposal.core import MetaUnavailableError

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            MetaUnavailableError("muse transport down"),
            MetaUnavailableError("muse transport down"),
            MetaUnavailableError("muse transport down"),
            MetaUnavailableError("muse transport down"),
            correction_json("skip", WRITE_ID, "today"),
        ],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    received = harness.now
    seed_note(harness, 110, reply_to=700)

    assert claim_and_process(harness) == "waiting"
    row = VoiceLedger(harness.db).load(110)
    assert row is not None and row.status == "pending" and row.attempts == 1
    assert len(all_events(harness)) == 0

    harness.now = received + timedelta(seconds=6)
    assert claim_and_process(harness) == "waiting"
    row = VoiceLedger(harness.db).load(110)
    assert row is not None and row.attempts == 2

    harness.now = received + timedelta(seconds=6 + 31)
    assert claim_and_process(harness) == "waiting"
    row = VoiceLedger(harness.db).load(110)
    assert row is not None and row.attempts == 3 and row.waiting_told == 1
    waiting = [t for t in sent_texts(harness) if "keep trying" in t["text"]]
    assert len(waiting) == 1

    harness.now = received + timedelta(seconds=6 + 31 + 121)
    assert claim_and_process(harness) == "waiting"
    row = VoiceLedger(harness.db).load(110)
    assert row is not None and row.attempts == 4 and row.waiting_told == 1
    assert len([t for t in sent_texts(harness) if "keep trying" in t["text"]]) == 1

    harness.now = received + timedelta(seconds=6 + 31 + 121 + 901)
    assert claim_and_process(harness) == "applied_card"
    reply = sent_texts(harness)[-1]["text"]
    assert "New card above. Took 1059.0s." in reply
    assert len(voice_events(harness)) == 1


DISPUTED_STATEMENT = "Work screen hours decreased from 4.75 in prior to 1.75 in last."


def test_fact_correction_disputes_both_sides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement about screen hours is wrong",
    )
    old = seed_old_card(harness, message_id=700, statements=(DISPUTED_STATEMENT,))
    seed_results(
        harness,
        old,
        claims_a=[("c-a-1", DISPUTED_STATEMENT, ["fact:synthetic-7"], [])],
        claims_b=[("c-b-1", DISPUTED_STATEMENT, ["fact:synthetic-7"], [])],
    )
    seed_note(harness, 111, reply_to=700)

    assert claim_and_process(harness) == "fact_disputed_card"
    assert harness.wonder_calls == {"builder": 1, "disconnect": 1}
    reply = sent_texts(harness)[0]["text"]
    assert "You disputed what this card cited (2 claims)." in reply
    assert "New card above. Took" in reply
    disputes = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    assert {event.data.fact_id for event in disputes} == {"fact:synthetic-7"}
    new_id = VoiceLedger(harness.db).load(111).new_card_id  # type: ignore[union-attr]
    assert new_id is not None
    new = CardLedger(harness.db).load(new_id)
    assert new is not None
    assert new.correction_line == "You disputed what this card cited (2 claims)."


def test_claim_citing_fact_and_metrics_disputes_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that screen claim is wrong",
    )
    old = seed_old_card(harness, message_id=700, statements=(DISPUTED_STATEMENT,))
    seed_results(
        harness,
        old,
        claims_a=[
            (
                "c-a-1",
                DISPUTED_STATEMENT,
                ["fact:synthetic-9"],
                [("period.last.screen.code", 1.75)],
            )
        ],
    )
    seed_note(harness, 112, reply_to=700)

    assert claim_and_process(harness) in ("fact_disputed_card", "fact_disputed_stands")
    disputes = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    fact_hits = {event.data.fact_id for event in disputes if event.data.fact_id}
    metric_hits = {
        (event.data.metric_id, event.data.metric_value)
        for event in disputes
        if event.data.metric_id
    }
    assert fact_hits == {"fact:synthetic-9"}
    assert metric_hits == {("period.last.screen.code", 1.75)}


def test_disputed_metrics_are_not_offered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from evals.proposal_cases import ScriptedWonderClient, text_entry
    from framework.cycle import run_proposals

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that screen claim is wrong",
    )
    old = seed_old_card(harness, message_id=700, statements=(DISPUTED_STATEMENT,))
    seed_results(
        harness,
        old,
        claims_a=[
            (
                "c-a-1",
                DISPUTED_STATEMENT,
                ["fact:synthetic-7"],
                [
                    ("period.prior.screen.code", 4.75),
                    ("period.last.screen.code", 1.75),
                ],
            )
        ],
    )
    seed_note(harness, 113, reply_to=700)
    assert harness.deps is not None
    harness.deps = _replace_propose(harness.deps, run_proposals)

    bad = (
        '{"commitment_id": "cm-write", "overall_state": [{"text": '
        '"Work screen hours repeated", "fact_ids": ["fact:synthetic-7"], '
        '"metric_refs": []}], "working": [], "not_working": []}'
    )
    bad_metrics = (
        '{"commitment_id": "cm-write", "overall_state": [{"text": '
        '"Screen hours restated", "fact_ids": [], '
        '"metric_refs": [{"metric_id": "period.last.screen.code", '
        '"value": 1.75}]}], "working": [], "not_working": []}'
    )
    client = ScriptedWonderClient(
        (
            text_entry(bad),
            text_entry(bad),
            text_entry(bad_metrics),
            text_entry(bad_metrics),
        )
    )
    harness.deps = _replace_wonder(harness.deps, client)

    cycle_db = harness.db
    _record_dispute_cycle(cycle_db)
    outcome = claim_and_process(harness)
    assert outcome == "fact_disputed_card"
    store = ProposalStore(harness.db)
    try:
        fresh = store.results_for_slot(SUBJECT, SAT_SLOT)
        kinds = {result.profile_id: result.kind for result in fresh}
    finally:
        store.close()
    assert kinds["builder"] == "fallback"
    new_id = VoiceLedger(harness.db).load(113).new_card_id  # type: ignore[union-attr]
    assert new_id is not None
    new = CardLedger(harness.db).load(new_id)
    assert new is not None
    assert "4.75" not in " ".join(new.statements)
    assert "1.75" not in " ".join(new.statements)


def _replace_propose(deps: VoiceDeps, fn: object) -> VoiceDeps:
    import dataclasses

    return dataclasses.replace(deps, propose_fn=fn)  # type: ignore[arg-type]


def _replace_wonder(deps: VoiceDeps, client: object) -> VoiceDeps:
    import dataclasses

    def _factory(terms: tuple[str, ...], available: bool) -> object:
        return client

    return dataclasses.replace(deps, make_wonder_client=_factory)  # type: ignore[arg-type]


def _record_dispute_cycle(db: Path) -> None:
    from framework.briefing.context import MetricSnapshot
    from framework.glimmer.facts import FactResult, PassResult
    from framework.schemas.core import Fact, FactWindow
    from framework.store.fact_store import FactStore

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=MADRID)
    fact_store = FactStore(db_path=db)
    try:
        result = FactResult(
            facts=(
                Fact(
                    id="fact:synthetic-7",
                    subject_id=SUBJECT,
                    window=FactWindow(start=as_of, end=as_of),
                    statement=DISPUTED_STATEMENT,
                    evidence=["synthetic-source"],
                    tier="private",
                ),
            ),
            code_fact_ids=(),
            snapshot=MetricSnapshot(
                values={
                    "period.prior.screen.code": 4.75,
                    "period.last.screen.code": 1.75,
                    "calendar.busy_hours": 2.5,
                }
            ),
            passes=(
                PassResult(
                    name="personal",
                    attempts=0,
                    raw_valid=True,
                    model_id="",
                    latency_ms=0,
                    finish_reason=None,
                    completion_tokens=None,
                    kept=0,
                    noop_reason=None,
                ),
                PassResult(
                    name="feed",
                    attempts=0,
                    raw_valid=True,
                    model_id="",
                    latency_ms=0,
                    finish_reason=None,
                    completion_tokens=None,
                    kept=0,
                    noop_reason=None,
                ),
            ),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT,
            as_of=as_of,
            window_start=as_of,
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
    finally:
        fact_store.close()


def test_fact_correction_with_no_card_disputes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    seed_note(harness, 114)

    assert claim_and_process(harness) == "fact_no_card"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "There was no cited statement to dispute. Nothing changed." in reply
    assert len(all_events(harness)) == 1


def test_two_corrections_start_from_newest_descendant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("skip", WRITE_ID, "today"),
            correction_json("skip", WRITE2_ID, "tomorrow"),
        ],
        transcript=b"skip the write-up",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 115, reply_to=700)
    assert claim_and_process(harness) == "applied_card"
    first_new = VoiceLedger(harness.db).load(115).new_card_id  # type: ignore[union-attr]

    seed_note(harness, 116, reply_to=700)
    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(116)
    assert row is not None
    assert row.matched_card_id == first_new
    assert row.new_card_id is not None
    second = CardLedger(harness.db).load(row.new_card_id)
    assert second is not None
    assert second.replaces_card_id == first_new


def test_chain_ruling_prefers_new_card_tap() -> None:
    from framework.schemas.events import AppTapData, Event
    from framework.voice.state import standing_chain_ruling

    def _tap(card_id: str, target: str, moment: datetime, eid: str) -> Event:
        return Event(
            id=eid,
            subject_id=SUBJECT,
            source="telegram",
            type="app.tap",
            time=moment,
            source_id=f"{card_id}:{target}",
            data=AppTapData(block_id=card_id, target=target),
            tier="private",
            collected_at=moment,
            collector_version="voice-test@0.1.0",
        )

    old_id = "card-" + "a" * 16
    new_id = "card-" + "b" * 16
    moment = datetime(2026, 10, 31, 19, 0, tzinfo=MADRID)
    events = [
        _tap(new_id, "B", moment, "evt-new"),
        _tap(old_id, "A", moment + timedelta(seconds=5), "evt-old"),
    ]
    assert standing_chain_ruling(events, (old_id, new_id)) == (new_id, "B")
    assert standing_chain_ruling(events, (old_id,)) == (old_id, "A")
    assert standing_chain_ruling([], (old_id, new_id)) is None


def test_card_limit_stops_fourth_correction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("skip", WRITE_ID, "today"),
            correction_json("skip", WRITE2_ID, "today"),
            correction_json("skip", REST_ID, "today"),
            correction_json("skip", "cm-rest2", "today"),
        ],
        transcript=b"skip it today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    for message_id in (121, 122, 123):
        seed_note(harness, message_id, reply_to=700)
        assert claim_and_process(harness) == "applied_card"
    seed_note(harness, 124, reply_to=700)

    assert claim_and_process(harness) == "card_limit"
    assert harness.wonder_calls == {"builder": 2, "disconnect": 1}
    reply = sent_texts(harness)[-1]["text"]
    assert "That is 3 corrected cards for this slot, so no new card." in reply


def test_hour_passed_sends_no_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    harness.now = datetime(2026, 10, 31, 20, 0, tzinfo=MADRID)
    seed_note(harness, 125, reply_to=700)

    assert claim_and_process(harness) == "hour_passed"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "That hour has passed, so no new card." in reply


def test_chart_missing_sends_no_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    import sqlite3

    conn = sqlite3.connect(harness.db)
    try:
        conn.execute(
            "DELETE FROM telegram_card_charts WHERE card_id = ?", (old.card_id,)
        )
        conn.commit()
    finally:
        conn.close()
    seed_note(harness, 126, reply_to=700)

    assert claim_and_process(harness) == "chart_missing"
    assert harness.wonder_calls == {}
    reply = sent_texts(harness)[0]["text"]
    assert "The card stands. Took" in reply


def test_lone_side_relettered_a(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)

    def _noop(**kwargs: Any) -> ProposalResult:
        return ProposalResult(
            kind="noop",
            profile_id="builder",
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=1,
            slot=kwargs["slot"],
            hour=None,
            briefing=None,
            fallback=None,
            reason_codes=("ELIGIBLE_EMPTY",),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="h",
        )

    harness.result_script["builder"] = [_noop]
    seed_note(harness, 127, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(127)
    assert row is not None and row.new_card_id is not None
    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    assert [(side.letter, side.title) for side in new.proposals] == [
        ("A", "Evening rest")
    ]


def test_reproposal_failed_on_bad_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    long_title = "Synthetic oversized write-up " + "x" * 700
    commitments: list[dict[str, str]] = [
        dict(COMMITMENTS_JSON[0], title=long_title),
        COMMITMENTS_JSON[1],
    ]
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
        commitments_json=cast("list[dict[str, object]]", commitments),
    )
    old = seed_old_card(harness, message_id=700, titles=(long_title, "Evening rest"))
    seed_results(harness, old)

    def _longside(**kwargs: Any) -> ProposalResult:
        from framework.briefing.context import TimeInterval
        from framework.briefing.schemas import Action, Briefing, Section

        slot = kwargs["slot"]
        hour = TimeInterval(
            start=slot.replace(hour=19, minute=0),
            end=slot.replace(hour=19, minute=25),
        )
        return ProposalResult(
            kind="proposal",
            profile_id="builder",
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=1,
            slot=slot,
            hour=hour,
            briefing=Briefing(
                id="briefing-builder-long",
                profile_id="builder",
                subject_id=SUBJECT,
                slot=slot,
                sections=[
                    Section(
                        type="actions",
                        claims=[],
                        actions=[
                            Action(
                                id="action-builder",
                                commitment_id=WRITE_ID,
                                kind="write",
                                text="oversized",
                                dimension="love",
                                proposed_start=hour.start,
                                proposed_end=hour.end,
                            )
                        ],
                    )
                ],
            ),
            fallback=None,
            reason_codes=(),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="h",
        )

    harness.result_script["builder"] = [_longside]
    seed_note(harness, 128, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "I couldn't build a new card. The change is saved." in reply
    assert "the card stands" not in reply.lower()
    row = VoiceLedger(harness.db).load(128)
    assert row is not None and row.new_card_id is None
    assert len([e for e in all_events(harness) if e.type == "app.correction"]) == 1


def test_post_check_failure_sends_no_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c-a-1", "A steady synthetic claim.", ["fact:synthetic-9"], [])],
    )
    _append_dispute(harness.db, fact_id="fact:synthetic-9", message_id=200)

    def _citing(**kwargs: Any) -> ProposalResult:
        from framework.briefing.context import TimeInterval
        from framework.briefing.schemas import Action, Briefing, Claim, Section

        slot = kwargs["slot"]
        hour = TimeInterval(
            start=slot.replace(hour=19, minute=0),
            end=slot.replace(hour=19, minute=25),
        )
        briefing = Briefing(
            id="briefing-builder-citing",
            profile_id="builder",
            subject_id=SUBJECT,
            slot=slot,
            sections=[
                Section(
                    type="overall_state",
                    actions=[],
                    claims=[
                        Claim(
                            id="c-new-1",
                            text="A steady synthetic claim repeated.",
                            fact_ids=["fact:synthetic-9"],
                            metric_refs=[],
                        )
                    ],
                ),
                Section(
                    type="actions",
                    claims=[],
                    actions=[
                        Action(
                            id="action-builder",
                            commitment_id=WRITE_ID,
                            kind="write",
                            text="Finish the write-up",
                            dimension="love",
                            proposed_start=hour.start,
                            proposed_end=hour.end,
                        )
                    ],
                ),
            ],
        )
        return ProposalResult(
            kind="proposal",
            profile_id="builder",
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=1,
            slot=slot,
            hour=hour,
            briefing=briefing,
            fallback=None,
            reason_codes=(),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="h",
        )

    harness.result_script["builder"] = [_citing]
    seed_note(harness, 129, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "I couldn't build a new card. The change is saved." in reply


def _append_dispute(db: Path, *, fact_id: str, message_id: int) -> None:
    from framework.schemas.events import AppFactDisputeData, Event

    moment = datetime(2026, 10, 31, 17, 0, tzinfo=MADRID)
    store = EventStore(db)
    try:
        assert store.append_event(
            Event(
                id=f"evt-dispute-{message_id}",
                subject_id=SUBJECT,
                source="telegram",
                type="app.fact_dispute",
                time=moment,
                source_id=f"voice:{message_id}:{fact_id}",
                data=AppFactDisputeData(
                    fact_id=fact_id,
                    card_id="card-" + "c" * 16,
                    message_id=message_id,
                    reported_by="user",
                ),
                tier="private",
                collected_at=moment,
                collector_version="voice-test@0.1.0",
            )
        )
    finally:
        store.close()


def _killed_deps(harness: Harness) -> VoiceDeps:
    import dataclasses

    kill_file = harness.tmp_path / "kill.switch"
    kill_file.write_text("stop\n", encoding="utf-8")
    assert harness.deps is not None
    return dataclasses.replace(harness.deps, kill_file=kill_file)


def test_kill_before_download_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 131, reply_to=700)
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert method_order(harness) == []
    assert harness.runner.calls == []
    fresh = VoiceLedger(harness.db).load(131)
    assert fresh is not None
    assert fresh.status == "pending" and fresh.attempts == 0
    assert fresh.outcome == "killed_waiting"
    assert len(all_events(harness)) == 0


def test_kill_before_compile_keeps_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 132, reply_to=700)
    VoiceLedger(harness.db).update(132, transcript="skip the write-up today")
    calls_before = len(harness.runner.calls)
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert len(harness.runner.calls) == calls_before
    assert harness.compile_client.requests == []
    assert sent_texts(harness) == []
    fresh = VoiceLedger(harness.db).load(132)
    assert fresh is not None and fresh.attempts == 0


def test_kill_before_apply_writes_no_events_then_resumes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 133, reply_to=700)
    VoiceLedger(harness.db).update(
        133,
        transcript="skip the write-up today",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
    )
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert len(all_events(harness)) == 0

    kill_file = harness.tmp_path / "kill.switch"
    kill_file.unlink()
    assert claim_and_process(harness) == "applied_card"
    assert len([e for e in all_events(harness) if e.type == "app.correction"]) == 1


def test_kill_before_reproposal_keeps_applied_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.collectors.common import event_id
    from framework.schemas.events import AppCorrectionData, Event

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    said = datetime(2026, 10, 31, 18, 4, tzinfo=MADRID)
    seed_note(harness, 134, said_at=said, reply_to=700)
    VoiceLedger(harness.db).update(
        134,
        transcript="skip the write-up today",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
        applied_at=harness.now.isoformat(),
    )
    source_id = "voice:134"
    store = EventStore(harness.db)
    try:
        assert store.append_event(
            Event(
                id=event_id("telegram", source_id),
                subject_id=SUBJECT,
                source="telegram",
                type="app.correction",
                time=harness.now,
                source_id=source_id,
                data=AppCorrectionData(
                    commitment_id=WRITE_ID,
                    operation="skip",
                    until="today",
                    slot=old.slot,
                    said_at=said.astimezone(UTC),
                    message_id=134,
                    reported_by="user",
                ),
                tier="private",
                collected_at=harness.now,
                collector_version="telegram@0.1.0",
            )
        )
    finally:
        store.close()
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert harness.wonder_calls == {}
    assert len([e for e in all_events(harness) if e.type == "app.correction"]) == 1

    kill_file = harness.tmp_path / "kill.switch"
    kill_file.unlink()
    assert claim_and_process(harness) == "applied_card"
    assert len([e for e in all_events(harness) if e.type == "app.correction"]) == 1
    assert harness.wonder_calls == {"builder": 1}


def test_mode_not_confirmed_waits_then_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 135, reply_to=700)
    assert harness.settings_path is not None
    harness.settings_path.write_text(
        json.dumps({"contributor_mode_enabled": True}), encoding="utf-8"
    )

    assert claim_and_process(harness) == "mode_not_confirmed"
    assert harness.runner.calls == []
    row = VoiceLedger(harness.db).load(135)
    assert row is not None
    assert row.status == "pending" and row.attempts == 0 and row.waiting_told == 1
    told = sent_texts(harness)
    assert len(told) == 1
    assert "Contributor mode is off" in told[0]["text"]

    harness.now = harness.now + timedelta(seconds=61)
    assert claim_and_process(harness) == "mode_not_confirmed"
    assert len(sent_texts(harness)) == 1

    harness.settings_path.write_text(
        json.dumps({"contributor_mode_enabled": False}), encoding="utf-8"
    )
    harness.now = harness.now + timedelta(seconds=61)
    assert claim_and_process(harness) == "applied_card"


def test_mode_reply_suppressed_while_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 136, reply_to=700)
    assert harness.settings_path is not None
    harness.settings_path.write_text(
        json.dumps({"contributor_mode_enabled": True}), encoding="utf-8"
    )
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert sent_texts(harness) == []


def test_resume_reuses_transcript_compile_and_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 137, reply_to=700)
    assert claim_and_process(harness) == "applied_card"
    photos = method_order(harness).count("sendPhoto")
    transcribes = len([c for c in harness.runner.calls if "transcribe" in c])
    compiles = len(harness.compile_client.requests)

    VoiceLedger(harness.db).update(137, status="pending", outcome=None)
    assert claim_and_process(harness) == "applied_card"
    assert method_order(harness).count("sendPhoto") == photos
    assert len([c for c in harness.runner.calls if "transcribe" in c]) == transcribes
    assert len(harness.compile_client.requests) == compiles
    assert len(voice_events(harness)) == 1


def test_resume_reuses_applied_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 138, reply_to=700)
    stamp = (harness.now - timedelta(seconds=30)).isoformat()
    VoiceLedger(harness.db).update(
        138,
        transcript="skip the write-up today",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
        applied_at=stamp,
    )

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(138)
    assert row is not None and row.applied_at == stamp
    corrections = [
        event for event in all_events(harness) if event.type == "app.correction"
    ]
    assert len(corrections) == 1
    assert corrections[0].time == datetime.fromisoformat(stamp)


def test_applied_superseded_sends_no_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("skip", WRITE_ID, "today"),
            correction_json("skip", WRITE_ID, "tomorrow"),
        ],
        transcript=b"skip the write-up",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    later_said = datetime(2026, 10, 31, 18, 10, tzinfo=MADRID)
    earlier_said = datetime(2026, 10, 31, 18, 0, tzinfo=MADRID)
    seed_note(harness, 141, said_at=later_said, reply_to=700)
    assert claim_and_process(harness) == "applied_card"
    photos = method_order(harness).count("sendPhoto")

    seed_note(harness, 140, said_at=earlier_said, reply_to=700)
    assert claim_and_process(harness) == "applied_superseded"
    assert method_order(harness).count("sendPhoto") == photos
    row = VoiceLedger(harness.db).load(140)
    assert row is not None and row.new_card_id is None
    reply = sent_texts(harness)[-1]["text"]
    assert "A later note already changed this. Took" in reply


def test_overnight_note_folds_by_said_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    said = datetime(2026, 11, 2, 23, 59, tzinfo=MADRID)
    harness.now = datetime(2026, 11, 3, 0, 10, tzinfo=MADRID)
    seed_note(harness, 142, said_at=said)

    assert claim_and_process(harness) == "applied_no_card"
    prompt = harness.compile_client.requests[0].prompt
    assert "Monday 2026-11-02 23:59" in prompt


def test_clock_change_day_compiles_local_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    said = datetime(2026, 10, 25, 12, 0, tzinfo=MADRID)
    harness.now = datetime(2026, 10, 25, 12, 5, tzinfo=MADRID)
    seed_note(harness, 143, said_at=said)

    assert claim_and_process(harness) == "applied_no_card"
    prompt = harness.compile_client.requests[0].prompt
    assert "Sunday 2026-10-25 12:00" in prompt


def test_state_window_misses_event_at_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.state import load_voice_state

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 144, reply_to=700)
    assert claim_and_process(harness) == "applied_card"

    store = EventStore(harness.db)
    try:
        corrections = store.events_between(
            SUBJECT,
            datetime(2000, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 1, tzinfo=UTC),
            types=["app.correction"],
        )
        assert len(corrections) == 1
        applied_at = corrections[0].time
        missed, _ = load_voice_state(
            store,
            SUBJECT,
            start=datetime(2000, 1, 1, tzinfo=UTC),
            end=applied_at,
        )
        assert missed == {}
        found, _ = load_voice_state(
            store,
            SUBJECT,
            start=datetime(2000, 1, 1, tzinfo=UTC),
            end=applied_at + timedelta(days=2),
        )
        assert WRITE_ID in found
    finally:
        store.close()


def test_gave_up_after_24h(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from framework.proposal.core import MetaUnavailableError

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[MetaUnavailableError("muse transport down")],
        transcript=b"skip the write-up today",
    )
    seed_note(harness, 145)
    assert claim_and_process(harness) == "waiting"
    harness.now = harness.now + timedelta(hours=25)
    assert claim_and_process(harness) == "gave_up"
    row = VoiceLedger(harness.db).load(145)
    assert row is not None and row.status == "gave_up"
    reply = sent_texts(harness)[-1]["text"]
    assert reply.startswith('Heard: "skip the write-up today"')
    assert "I couldn't process that note. Nothing changed." in reply
    assert len(voice_events(harness)) == 1
    assert voice_events(harness)[0].data.outcome == "gave_up"


def test_reply_failed_after_card_is_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    harness.fake.queue_script("sendMessage", ("500",), ("500",))
    seed_note(harness, 146, reply_to=700)

    assert claim_and_process(harness) == "reply_failed"
    row = VoiceLedger(harness.db).load(146)
    assert row is not None
    assert row.status == "done" and row.new_card_id is not None
    assert len(voice_events(harness)) == 1
    assert voice_events(harness)[0].data.outcome == "reply_failed"


def test_wall_clock_totals_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    said = datetime(2026, 10, 31, 18, 4, tzinfo=MADRID)
    received = harness.now - timedelta(seconds=20)
    seed_note(harness, 147, said_at=said, received_at=received, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(147)
    assert row is not None
    assert row.total_s is not None and row.total_s >= 20.0
    steps = json.loads(row.step_seconds or "{}")
    assert set(steps) >= {"download", "transcribe", "compile", "apply", "send_reply"}
    assert row.unaccounted_s is not None
    assert abs(row.unaccounted_s - (row.total_s - sum(steps.values()))) < 0.01
    assert row.arrival_lag_s is not None
    assert row.first_claimed_at is not None
    event = voice_events(harness)[0]
    assert event.data.total_s == row.total_s
    assert event.data.step_seconds == steps
    assert event.data.compile_model == "muse-spark-1.3"
    assert event.data.compile_effort == "minimal"
    assert event.data.muse_version == "muse-test-1.0"
    assert event.data.rules_file_present is None
    assert event.data.validation_codes == ()


def test_worker_error_keeps_thread_alive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    harness.raise_in_propose = RuntimeError("boom-secret")
    seed_note(harness, 148, reply_to=700)

    worker = VoiceWorker(deps_of(harness), threading.Event())
    with caplog.at_level("DEBUG"):
        worker.drain(timeout_s=5.0)
    row = VoiceLedger(harness.db).load(148)
    assert row is not None and row.status == "pending" and row.attempts == 1
    assert "boom-secret" not in caplog.text
    captured = capsys.readouterr()
    assert "boom-secret" not in captured.out + captured.err
    assert "boom-secret" not in str(
        [r for r in VoiceLedger(harness.db).load(148).__dict__.values()]
    )

    harness.raise_in_propose = None
    harness.now = harness.now + timedelta(seconds=6)
    worker.drain(timeout_s=5.0)
    row = VoiceLedger(harness.db).load(148)
    assert row is not None and row.outcome == "applied_card"

    import sqlite3

    conn = sqlite3.connect(harness.db)
    try:
        stored = conn.execute(
            "SELECT outcome, step_seconds FROM voice_notes WHERE message_id = 148"
        ).fetchone()
        assert "boom-secret" not in str(stored)
    finally:
        conn.close()


def test_transcript_confined_to_row_and_chat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sqlite3

    secret = "supersecret transcript words 12345"
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=secret.encode(),
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 149, reply_to=700)

    with caplog.at_level("DEBUG"):
        assert claim_and_process(harness) == "applied_card"
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text
    assert secret in sent_texts(harness)[0]["text"]

    conn = sqlite3.connect(harness.db)
    try:
        event_rows = conn.execute("SELECT data FROM events").fetchall()
        assert secret not in str(event_rows)
        attempt_rows = conn.execute("SELECT * FROM proposal_attempts").fetchall()
        assert secret not in str(attempt_rows)
        result_rows = conn.execute("SELECT * FROM proposal_results").fetchall()
        assert secret not in str(result_rows)
        voice_rows = conn.execute(
            "SELECT transcript FROM voice_notes WHERE message_id = 149"
        ).fetchall()
        assert voice_rows == [(secret,)]
    finally:
        conn.close()


def test_worker_thread_and_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from framework.voice.worker import VoiceWorker, make_voice_handler

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 150, reply_to=700)

    wake = threading.Event()
    worker = VoiceWorker(deps_of(harness), wake)
    worker.start()
    try:
        wake.set()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            row = VoiceLedger(harness.db).load(150)
            if row is not None and row.status == "done":
                break
            time.sleep(0.05)
        row = VoiceLedger(harness.db).load(150)
        assert row is not None and row.outcome == "applied_card"
    finally:
        worker.stop()

    handler = make_voice_handler(wake)
    handler(
        VoiceNote(
            message_id=151,
            date=int(SAT_RECEIVED.timestamp()),
            file_id="synthetic-file-id",
            file_unique_id="uniq-151",
            duration_s=4,
        )
    )
    assert wake.is_set()


def test_show_chain_from_any_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.worker import show_chain

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 152, reply_to=700)
    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(152)
    assert row is not None and row.new_card_id is not None

    from_old = show_chain(harness.db, card_id=old.card_id)
    from_new = show_chain(harness.db, card_id=row.new_card_id)
    assert from_old == from_new
    assert "message_id=152" in from_old
    assert "outcome=applied_card" in from_old
    assert "operation=skip" in from_old
    assert f"old_card_id={old.card_id}" in from_old
    assert f"new_card_id={row.new_card_id}" in from_old
    assert "transcript=skip the write-up today" in from_old
    assert "total_s=" in from_old

    one = show_chain(harness.db, message_id=152)
    assert "message_id=152" in one
    assert "new_card_id=" not in one.replace(f"new_card_id={row.new_card_id}", "")


def test_show_chain_blocked_hides_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.worker import show_chain

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip it synthetic-denied-term today",
    )
    seed_note(harness, 153)
    assert claim_and_process(harness) == "outbound_blocked"
    printed = show_chain(harness.db, message_id=153)
    assert "transcript=<blocked>" in printed
    assert "synthetic-denied-term" not in printed


def test_bare_note_falls_to_latest_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 154, reply_to=999999)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(154)
    assert row is not None and row.matched_card_id == old.card_id


def test_wrong_tap_matches_until_a_newer_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.schemas.events import AppTapData, Event

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[
            correction_json("skip", WRITE_ID, "today"),
            correction_json("keep", WRITE_ID, None),
        ],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    tap_moment = datetime(2026, 10, 31, 18, 6, tzinfo=MADRID)
    store = EventStore(harness.db)
    try:
        assert store.append_event(
            Event(
                id="evt-wrong-old",
                subject_id=SUBJECT,
                source="telegram",
                type="app.tap",
                time=tap_moment,
                source_id=f"{old.card_id}:wrong",
                data=AppTapData(block_id=old.card_id, target="wrong"),
                tier="private",
                collected_at=tap_moment,
                collector_version="telegram@0.1.0",
            )
        )
    finally:
        store.close()
    seed_note(harness, 155)
    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(155)
    assert row is not None and row.matched_card_id == old.card_id

    newer = seed_old_card(
        harness, message_id=701, statements=("Another synthetic line.",)
    )
    seed_results(harness, newer)
    seed_note(harness, 156)
    assert claim_and_process(harness) == "applied_card_stands"
    row = VoiceLedger(harness.db).load(156)
    assert row is not None and row.matched_card_id == newer.card_id


FACT_STATEMENT = (
    "Work/Programming screen hours decreased from 4.75 in prior to 1.75 in last."
)
PRIOR_CODE = "period.prior.screen.code"


def proposal_with_claims(
    profile_id: str,
    kwargs: Any,
    claim_rows: Sequence[tuple[str, str, list[str], list[tuple[str, float]]]],
    *,
    run: int = 2,
    end_hour: int = 19,
) -> ProposalResult:
    """A re-proposal result whose briefing cites the given claim rows."""
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Action, Briefing, Claim, MetricRef, Section

    slot = kwargs["slot"]
    eligible = kwargs["eligible_by_profile"][profile_id]
    assert eligible, "expected an eligible commitment for the re-proposal"
    commitment = eligible[0]
    hour = TimeInterval(
        start=slot.replace(hour=end_hour, minute=0, second=0, microsecond=0),
        end=slot.replace(hour=end_hour, minute=25, second=0, microsecond=0),
    )
    briefing = Briefing(
        id=f"briefing-{profile_id}-new",
        profile_id=profile_id,
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="overall_state",
                actions=[],
                claims=[
                    Claim(
                        id=claim_id,
                        text=text,
                        fact_ids=list(fact_ids),
                        metric_refs=[
                            MetricRef(metric_id=metric_id, value=value)
                            for metric_id, value in metrics
                        ],
                    )
                    for claim_id, text, fact_ids, metrics in claim_rows
                ],
            ),
            Section(
                type="actions",
                actions=[
                    Action(
                        id=f"action-{profile_id}-new",
                        commitment_id=commitment.id,
                        kind=commitment.kind,  # type: ignore[arg-type]
                        text=commitment.title,
                        dimension=commitment.dimension,  # type: ignore[arg-type]
                        proposed_start=hour.start,
                        proposed_end=hour.end,
                    )
                ],
            ),
        ],
    )
    return ProposalResult(
        kind="proposal",
        profile_id=profile_id,
        subject_id=SUBJECT,
        cycle_id="cycle-1",
        run=run,
        slot=slot,
        hour=hour,
        briefing=briefing,
        fallback=None,
        reason_codes=(),
        attempts=(),
        cycle_age_s=0.0,
        prompt_hash="new",
    )


def seed_fact(
    harness: Harness,
    *,
    fact_id: str = "fact-1",
    statement: str = FACT_STATEMENT,
    run: int = 1,
) -> None:
    """Insert one stored fact row the post-check can read by cycle and run."""
    import sqlite3

    from framework.store.fact_store import FactStore

    FactStore(harness.db).close()  # ensure the facts table exists
    conn = sqlite3.connect(harness.db)
    try:
        conn.execute(
            "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
            " window_start, window_end, statement, evidence, tier, origin)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cycle-1",
                run,
                fact_id,
                SUBJECT,
                "2026-10-01T00:00:00+01:00",
                "2026-10-31T00:00:00+01:00",
                statement,
                "[]",
                "private",
                "model",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_post_check_ignores_numbers_in_undisputed_reproposal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Code reads 4.75 again.", [], [(PRIOR_CODE, 4.75)])],
        )
    ]
    seed_note(harness, 201, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(201)
    assert row is not None and row.new_card_id is not None


def test_post_check_refuses_disputed_metric_at_same_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", FACT_STATEMENT, ["fact-1"], [(PRIOR_CODE, 4.75)])],
    )
    seed_fact(harness, run=1)
    seed_fact(harness, run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Code reads 4.75 again.", [], [(PRIOR_CODE, 4.75)])],
        )
    ]
    seed_note(harness, 202, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(202)
    assert row is not None and row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "You disputed what this card cited (1 claim)." in reply
    assert "I couldn't build a new card. The change is saved." in reply


def test_post_check_passes_unrelated_metric_for_fact_dispute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", FACT_STATEMENT, ["fact-1"], [(PRIOR_CODE, 4.75)])],
    )
    seed_fact(harness, run=1)
    seed_fact(harness, run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c3", "Unrelated metric 3.0.", [], [("period.last.screen.other", 3.0)])],
        )
    ]
    seed_note(harness, 203, reply_to=700)

    assert claim_and_process(harness) == "fact_disputed_card"
    row = VoiceLedger(harness.db).load(203)
    assert row is not None and row.new_card_id is not None


def test_resumed_note_reloads_terms_before_reproposal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dataclasses

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 204, reply_to=700)
    VoiceLedger(harness.db).update(
        204,
        transcript="skip the write-up today",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
    )
    seen: dict[str, bool] = {}
    original_propose = harness.propose

    def spy_propose(**kwargs: Any) -> Any:
        seen["propose_available"] = kwargs["private_terms"].available
        return original_propose(**kwargs)

    def spy_factory(terms: tuple[str, ...], available: bool) -> Any:
        seen["factory_available"] = available
        return harness.compile_client

    deps = dataclasses.replace(
        deps_of(harness),
        make_wonder_client=spy_factory,  # type: ignore[arg-type]
        propose_fn=spy_propose,  # type: ignore[arg-type]
    )
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "applied_card"
    assert seen == {"factory_available": True, "propose_available": True}


def test_reproposal_hour_over_ends_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder", kwargs, [("c2", "New line.", [], [])], end_hour=16
        )
    ]
    seed_note(harness, 205, reply_to=700)

    assert claim_and_process(harness) == "hour_passed"
    row = VoiceLedger(harness.db).load(205)
    assert row is not None
    assert row.status == "done" and row.attempts == 0
    assert row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "Skipped: Finish the write-up (today)." in reply
    assert "That hour has passed, so no new card." in reply
    assert len(voice_events(harness)) == 1
    assert voice_events(harness)[0].data.outcome == "hour_passed"


def test_card_send_value_error_is_reproposal_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import framework.voice.worker as worker_module

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 206, reply_to=700)

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("synthetic caption overflow")

    monkeypatch.setattr(worker_module, "send_card", _boom)
    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(206)
    assert row is not None
    assert row.status == "done" and row.new_card_id is None
    reply = sent_texts(harness)[0]["text"]
    assert "I couldn't build a new card. The change is saved." in reply


def test_drain_with_kill_switch_claims_once_and_keeps_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 207, reply_to=700)
    VoiceLedger(harness.db).update(207, step_seconds={"download": 1.5})
    worker = VoiceWorker(_killed_deps(harness), threading.Event())

    start = time.monotonic()
    worker.drain(timeout_s=5.0)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    row = VoiceLedger(harness.db).load(207)
    assert row is not None
    assert row.outcome == "killed_waiting" and row.status == "pending"
    assert json.loads(row.step_seconds or "{}") == {"download": 1.5}
    assert method_order(harness) == []


def test_run_survives_claim_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sqlite3
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 208, reply_to=700)

    wake = threading.Event()
    worker = VoiceWorker(deps_of(harness), wake)
    calls = {"count": 0}
    original_claim = worker._ledger.claim_next

    def flaky(now: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.Error("synthetic store lock")
        return original_claim(now)

    monkeypatch.setattr(worker._ledger, "claim_next", flaky)
    worker.start()
    try:
        wake.set()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            row = VoiceLedger(harness.db).load(208)
            if row is not None and row.status == "done":
                break
            time.sleep(0.05)
        row = VoiceLedger(harness.db).load(208)
        assert row is not None and row.outcome == "applied_card"
        assert worker._thread.is_alive()
    finally:
        worker.stop()


def test_worker_error_tells_once_on_third_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    harness.raise_in_propose = RuntimeError("boom-secret")
    seed_note(harness, 209, reply_to=700)
    worker = VoiceWorker(deps_of(harness), threading.Event())

    worker.drain(timeout_s=2.0)
    row = VoiceLedger(harness.db).load(209)
    assert row is not None and row.attempts == 1 and row.waiting_told == 0
    assert sent_texts(harness) == []

    harness.now = harness.now + timedelta(seconds=6)
    worker.drain(timeout_s=2.0)
    row = VoiceLedger(harness.db).load(209)
    assert row is not None and row.attempts == 2 and row.waiting_told == 0
    assert sent_texts(harness) == []

    harness.now = harness.now + timedelta(seconds=31)
    worker.drain(timeout_s=2.0)
    row = VoiceLedger(harness.db).load(209)
    assert row is not None and row.attempts == 3 and row.waiting_told == 1
    texts = sent_texts(harness)
    assert len(texts) == 1
    assert "That note is saved, but I can't process it yet." in texts[0]["text"]
    assert "boom-secret" not in texts[0]["text"]

    harness.now = harness.now + timedelta(seconds=121)
    worker.drain(timeout_s=2.0)
    assert len(sent_texts(harness)) == 1


def test_transient_wait_sends_no_reply_while_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.worker import _Ctx, _wait_transient

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    seed_note(harness, 210)
    VoiceLedger(harness.db).update(210, attempts=2)
    deps = _killed_deps(harness)
    row = VoiceLedger(harness.db).load(210)
    assert row is not None
    ctx = _Ctx(
        deps=deps,
        voice=VoiceLedger(harness.db),
        cards=CardLedger(harness.db),
        message_id=210,
        received=harness.now,
        said=harness.now,
        now=harness.now,
    )

    assert _wait_transient(ctx, row) == "waiting"
    fresh = VoiceLedger(harness.db).load(210)
    assert fresh is not None
    assert fresh.attempts == 3 and fresh.waiting_told == 0
    assert sent_texts(harness) == []


def test_gave_up_from_transient_wait_closes_in_same_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dataclasses

    from framework.proposal.core import MetaUnavailableError

    harness = make_harness(
        monkeypatch,
        tmp_path,
        transcript=b"skip the write-up today",
    )
    seed_note(
        harness,
        211,
        received_at=harness.now - timedelta(hours=23, minutes=59),
    )

    class _AdvancingClient:
        """Moves the harness clock past 24 h, then fails the compile call."""

        transport = "fake"
        harness_rules_file = None

        def complete(self, request: Any) -> Any:
            harness.now = harness.now + timedelta(minutes=2)
            raise MetaUnavailableError("muse transport down")

    deps = dataclasses.replace(
        deps_of(harness),
        make_compile_client=lambda terms, available: _AdvancingClient(),  # type: ignore[arg-type]
    )
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    # The early check in the flow still sees a live note; the give-up comes
    # from the transient wait after the failed compile.
    assert process_one(deps, row) == "gave_up"
    fresh = VoiceLedger(harness.db).load(211)
    assert fresh is not None and fresh.status == "gave_up"
    assert len(voice_events(harness)) == 1
    assert voice_events(harness)[0].data.outcome == "gave_up"


def test_resumed_fact_correction_reuses_stored_claim_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", ["fact-a"], [("period.prior.screen.code", 1.0)])],
    )
    seed_note(harness, 212, reply_to=700)

    assert claim_and_process(harness) == "fact_disputed_card"
    disputes_before = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    assert len(disputes_before) == 2
    row = VoiceLedger(harness.db).load(212)
    assert row is not None and row.disputed_claims == 1

    # The re-proposal already wrote new rows with different citations; a
    # resumed note reuses the stored claim count and treats every side the
    # card carries as affected, so it corrects the offer instead of closing
    # fact_disputed_stands on rows its own attempt wrote.
    VoiceLedger(harness.db).update(
        212, status="pending", outcome=None, new_card_id=None
    )
    assert claim_and_process(harness) == "fact_disputed_card"
    disputes_after = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    assert len(disputes_after) == 2
    resumed = VoiceLedger(harness.db).load(212)
    assert resumed is not None and resumed.new_card_id is not None
    reply = sent_texts(harness)[-1]["text"]
    assert "You disputed what this card cited (1 claim)." in reply
    assert "New card above. Took" in reply


def test_stored_codes_beat_stored_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"something unclear here",
    )
    seed_note(harness, 213)
    VoiceLedger(harness.db).update(
        213,
        transcript="something unclear here",
        operation="none",
        question="Which commitment do you mean?",
        validation_codes=["CORRECTION_QUESTION_INVALID"],
    )

    assert claim_and_process(harness) == "not_understood"
    reply = sent_texts(harness)[0]["text"]
    assert "I didn't get that, nothing changed." in reply
    assert "Which commitment do you mean?" not in reply


def test_compile_prompt_offers_carry_side_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 214, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    prompt = harness.compile_client.requests[0].prompt
    expected = json.dumps(
        {
            "label": "A",
            "title": "Finish the write-up",
            "slot": old.proposals[0].start.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert expected in prompt


def test_show_chain_marks_recorded_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.worker import show_chain

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 215, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    assert "event=recorded" in show_chain(harness.db, message_id=215)
    assert "event=missing" not in show_chain(harness.db, message_id=215)


def test_show_chain_marks_missing_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from framework.voice.worker import show_chain

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 216, reply_to=700)
    deps = _killed_deps(harness)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    assert "event=missing" in show_chain(harness.db, message_id=216)


def test_compile_builds_one_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dataclasses

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 217, reply_to=700)
    calls = {"count": 0}

    def counting_factory(terms: tuple[str, ...], available: bool) -> Any:
        calls["count"] += 1
        return harness.compile_client

    deps = dataclasses.replace(
        deps_of(harness),
        make_compile_client=counting_factory,  # type: ignore[arg-type]
    )
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "applied_card"
    assert calls["count"] == 1


def test_new_card_id_stored_before_reply_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The row holds ``new_card_id`` when the reply's sendMessage arrives."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 218, reply_to=700)
    seen: dict[str, Any] = {}
    original = harness.fake

    def spy(request: urllib.request.Request, timeout: float | None = None) -> Any:
        if request.full_url.endswith("/sendMessage"):
            row = VoiceLedger(harness.db).load(218)
            seen["new_card_id"] = row.new_card_id if row is not None else None
        return original(request, timeout)

    monkeypatch.setattr(client_module, "_open_url", spy)

    assert claim_and_process(harness) == "applied_card"
    assert seen.get("new_card_id"), "row had no new_card_id at sendMessage time"
    row = VoiceLedger(harness.db).load(218)
    assert row is not None and row.new_card_id == seen["new_card_id"]


def test_corrected_card_photo_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The corrected card's sendPhoto carries disable_notification true."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 219, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    bodies = [
        body for method, _, _, body, _ in harness.fake.requests if method == "sendPhoto"
    ]
    assert len(bodies) == 1
    marker = b'name="disable_notification"\r\n\r\n'
    idx = bodies[0].find(marker)
    assert idx != -1, "sendPhoto has no disable_notification field"
    value = bodies[0][idx + len(marker) :].split(b"\r\n")[0]
    assert value == b"true"


def test_post_check_ignores_metric_dispute_from_other_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A metric dispute from another cycle on an earlier day passes post-check."""
    from framework.schemas.events import AppFactDisputeData, Event

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    moment = datetime(2026, 10, 30, 17, 0, tzinfo=MADRID)
    store = EventStore(harness.db)
    try:
        assert store.append_event(
            Event(
                id="evt-dispute-other-cycle",
                subject_id=SUBJECT,
                source="telegram",
                type="app.fact_dispute",
                time=moment,
                source_id=f"voice:220:{PRIOR_CODE}",
                data=AppFactDisputeData(
                    metric_id=PRIOR_CODE,
                    metric_value=4.75,
                    cycle_id="cycle-other",
                    card_id=old.card_id,
                    message_id=220,
                    reported_by="user",
                ),
                tier="private",
                collected_at=moment,
                collector_version="voice-test@0.1.0",
            )
        )
    finally:
        store.close()
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Code reads 4.75 again.", [], [(PRIOR_CODE, 4.75)])],
        )
    ]
    seed_note(harness, 221, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(221)
    assert row is not None and row.new_card_id is not None
    assert "sendPhoto" in method_order(harness)


def test_post_check_fails_metric_dispute_same_day_other_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A metric dispute from another cycle earlier the same day fails post-check."""
    from framework.schemas.events import AppFactDisputeData, Event

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    moment = datetime(2026, 10, 31, 17, 0, tzinfo=MADRID)
    store = EventStore(harness.db)
    try:
        assert store.append_event(
            Event(
                id="evt-dispute-same-day",
                subject_id=SUBJECT,
                source="telegram",
                type="app.fact_dispute",
                time=moment,
                source_id=f"voice:225:{PRIOR_CODE}",
                data=AppFactDisputeData(
                    metric_id=PRIOR_CODE,
                    metric_value=4.75,
                    cycle_id="cycle-other",
                    card_id=old.card_id,
                    message_id=225,
                    reported_by="user",
                ),
                tier="private",
                collected_at=moment,
                collector_version="voice-test@0.1.0",
            )
        )
    finally:
        store.close()
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Code reads 4.75 again.", [], [(PRIOR_CODE, 4.75)])],
        )
    ]
    seed_note(harness, 226, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(226)
    assert row is not None and row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)


def test_post_check_metric_citation_branch_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only a metric citation is disputed: the same id and value still fails.

    No stored fact holds the number, so the display-value branch cannot
    cover for the disputed-metric branch.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that metric claim is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    seed_fact(harness, statement="Synthetic unrelated line.", run=1)
    seed_fact(harness, statement="Synthetic unrelated line.", run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Code reads 4.75 again.", [], [(PRIOR_CODE, 4.75)])],
        )
    ]
    seed_note(harness, 222, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(222)
    assert row is not None and row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)


def test_post_check_passes_different_metric_at_disputed_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only a metric citation is disputed: another id at its value passes.

    A disputed metric's display value no longer drops other metrics, so a
    new claim citing a different metric id at 4.75 clears the post-check
    and the note ends ``fact_disputed_card``.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that metric claim is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    seed_fact(harness, statement="Synthetic unrelated line.", run=1)
    seed_fact(harness, statement="Synthetic unrelated line.", run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [
                (
                    "c2",
                    "Other metre reads 4.75.",
                    [],
                    [("period.last.screen.other", 4.75)],
                )
            ],
        )
    ]
    seed_note(harness, 230, reply_to=700)

    assert claim_and_process(harness) == "fact_disputed_card"
    row = VoiceLedger(harness.db).load(230)
    assert row is not None and row.new_card_id is not None
    assert "sendPhoto" in method_order(harness)


def test_post_check_fact_display_branch_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only a fact is disputed: a different metric id at its number fails.

    The new claim cites an id the dispute never named, so the exact-match
    branch cannot cover for the display-value branch.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", FACT_STATEMENT, ["fact-1"], [])],
    )
    seed_fact(harness, run=1)
    seed_fact(harness, run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [
                (
                    "c2",
                    "Other metre reads 4.75.",
                    [],
                    [("period.last.screen.other", 4.75)],
                )
            ],
        )
    ]
    seed_note(harness, 223, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(223)
    assert row is not None and row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)


def test_reproposal_citing_stored_fact_holding_disputed_number_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A new claim citing an undisputed fact holding a disputed number fails.

    Only the metric is disputed, so the cited fact is not disputed by id;
    it still fails because its stored statement holds the disputed number.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that metric claim is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", [], [(PRIOR_CODE, 4.75)])],
    )
    seed_fact(harness, fact_id="fact-2", run=1)
    seed_fact(harness, fact_id="fact-2", run=2)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [("c2", "Restated synthetic line.", ["fact-2"], [])],
        )
    ]
    seed_note(harness, 224, reply_to=700)

    assert claim_and_process(harness) == "reproposal_failed"
    row = VoiceLedger(harness.db).load(224)
    assert row is not None and row.new_card_id is None
    assert "sendPhoto" not in method_order(harness)
    reply = sent_texts(harness)[0]["text"]
    assert "I couldn't build a new card. The change is saved." in reply


def test_resumed_fact_correction_after_fallback_send_failure_retries_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fallback rows plus a failed card send still retry to a new card."""
    from framework.briefing.schemas import Commitment as _Commitment
    from framework.proposal.schemas import FallbackProposal

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", ["fact-1"], [(PRIOR_CODE, 4.75)])],
    )

    def _fallback(**kwargs: Any) -> Any:
        from framework.briefing.context import TimeInterval
        from framework.proposal.core import ProposalResult

        slot = kwargs["slot"]
        hour = TimeInterval(
            start=slot.replace(hour=19, minute=0, second=0, microsecond=0),
            end=slot.replace(hour=19, minute=25, second=0, microsecond=0),
        )
        return ProposalResult(
            kind="fallback",
            profile_id="builder",
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=2,
            slot=slot,
            hour=hour,
            briefing=None,
            fallback=FallbackProposal(
                kind="fallback",
                profile_id="builder",
                subject_id=SUBJECT,
                slot=slot,
                commitment=_Commitment(
                    id=WRITE_ID,
                    profile_id="builder",
                    title="Finish the write-up",
                    kind="write",
                    dimension="love",
                    evidence="tap",
                ),
                proposed_start=hour.start,
                proposed_end=hour.end,
                reason_codes=("SYNTHETIC_FALLBACK",),
            ),
            reason_codes=("SYNTHETIC_FALLBACK",),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="fallback",
        )

    harness.result_script["builder"] = [_fallback]
    # One scripted not-sent failure (a 5xx is delivery-unknown now, never
    # retried): the first pass waits transiently, the retry sends the card.
    harness.fake.queue_script("sendPhoto", ("429", 500))
    seed_note(harness, 225, reply_to=700)

    assert claim_and_process(harness) == "waiting"
    first = VoiceLedger(harness.db).load(225)
    assert first is not None and first.new_card_id is None
    assert first.disputed_claims == 1
    assert first.attempts == 1
    disputes_before = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    assert disputes_before != []

    harness.now = harness.now + timedelta(seconds=6)
    assert claim_and_process(harness) == "fact_disputed_card"
    row = VoiceLedger(harness.db).load(225)
    assert row is not None and row.new_card_id is not None
    assert row.disputed_claims == 1
    disputes_after = [
        event for event in all_events(harness) if event.type == "app.fact_dispute"
    ]
    assert len(disputes_after) == len(disputes_before)
    reply = sent_texts(harness)[-1]["text"]
    assert "You disputed what this card cited (1 claim)." in reply
    assert "New card above. Took" in reply


def test_wait_killed_records_transcribe_step_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The kill switch landing mid-flow keeps the transcribe seconds."""
    import dataclasses

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 226, reply_to=700)
    kill_file = harness.tmp_path / "kill.switch"
    deps = dataclasses.replace(deps_of(harness), kill_file=kill_file)
    original = harness.runner

    def _sneaky(
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> Any:
        result = original(argv, env=env, timeout_s=timeout_s, cwd=cwd)
        if "transcribe" in list(argv):
            kill_file.write_text("stop\n", encoding="utf-8")
        return result

    monkeypatch.setattr(deps.transcriber, "_runner", _sneaky)

    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "killed_waiting"
    fresh = VoiceLedger(harness.db).load(226)
    assert fresh is not None
    assert fresh.status == "pending" and fresh.attempts == 0
    steps = json.loads(fresh.step_seconds or "{}")
    assert "transcribe" in steps


def test_run_does_not_spin_while_waiting_on_kill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With the switch on, one wake claims once, not in a tight loop."""
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 227, reply_to=700)

    kill_file = harness.tmp_path / "kill.switch"
    kill_file.write_text("stop\n", encoding="utf-8")
    import dataclasses

    deps = dataclasses.replace(deps_of(harness), kill_file=kill_file)
    wake = threading.Event()
    worker = VoiceWorker(deps, wake)
    calls = {"count": 0}
    original_claim = worker._ledger.claim_next

    def _counting(now: Any) -> Any:
        calls["count"] += 1
        return original_claim(now)

    monkeypatch.setattr(worker._ledger, "claim_next", _counting)
    worker.start()
    try:
        wake.set()
        time.sleep(0.6)
    finally:
        worker.stop()
    assert calls["count"] <= 5


def test_run_requeues_working_row_at_pass_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A row left working after the thread started completes after a wake."""
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 228, reply_to=700)

    wake = threading.Event()
    worker = VoiceWorker(deps_of(harness), wake)
    worker.start()
    try:
        claimed = VoiceLedger(harness.db).claim_next(harness.now)
        assert claimed is not None and claimed.status == "working"
        wake.set()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            row = VoiceLedger(harness.db).load(228)
            if row is not None and row.status == "done":
                break
            time.sleep(0.05)
        row = VoiceLedger(harness.db).load(228)
        assert row is not None and row.outcome == "applied_card"
    finally:
        worker.stop()


def test_drain_requeues_working_row_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A row in working completes through drain, not left behind."""
    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 229, reply_to=700)
    claimed = VoiceLedger(harness.db).claim_next(harness.now)
    assert claimed is not None and claimed.status == "working"

    worker = VoiceWorker(deps_of(harness), __import__("threading").Event())
    worker.drain(timeout_s=5.0)
    row = VoiceLedger(harness.db).load(229)
    assert row is not None and row.outcome == "applied_card"


def test_fact_dispute_events_use_stored_applied_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A resumed fact correction stamps disputes at the stored instant."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_a=[("c1", "Old line.", ["fact-1"], [(PRIOR_CODE, 4.75)])],
    )
    stamp = (harness.now - timedelta(seconds=30)).isoformat()
    seed_note(harness, 230, reply_to=700)
    VoiceLedger(harness.db).update(
        230,
        transcript="that statement is wrong",
        operation="fact_correction",
        applied_at=stamp,
    )

    assert claim_and_process(harness) == "fact_disputed_card"
    moments = {
        (event.type, event.time, event.collected_at)
        for event in all_events(harness)
        if event.type == "app.fact_dispute"
    }
    assert moments != set()
    expected = datetime.fromisoformat(stamp)
    assert moments == {("app.fact_dispute", expected, expected)}


def test_no_card_correction_slot_uses_stored_applied_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A noteless slot correction carries the stored stamp as its slot."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    stamp = (harness.now - timedelta(seconds=30)).isoformat()
    seed_note(harness, 231)
    VoiceLedger(harness.db).update(
        231,
        transcript="skip the write-up today",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
        applied_at=stamp,
    )

    assert claim_and_process(harness) == "applied_no_card"
    corrections = [
        event for event in all_events(harness) if event.type == "app.correction"
    ]
    assert len(corrections) == 1
    assert corrections[0].data.slot == datetime.fromisoformat(stamp)


def seed_slot_rows(
    harness: Harness,
    card: Card,
    *,
    bucket: str | None = "loved",
    as_of: datetime | None = None,
    commitments: Sequence[str] = (WRITE_ID, REST_ID),
) -> None:
    """Old-card side rows as the orchestrator would have saved them."""
    from framework.cycle.slot_ledger import SlotCardRow, SlotLedger

    moment = as_of if as_of is not None else SAT_SLOT
    rows = [
        SlotCardRow(
            card_id=card.card_id,
            letter=side.letter,
            slot=card.slot,
            subject_id=SUBJECT,
            as_of=moment,
            bucket=bucket,
            profile_id=side.profile.lower(),
            commitment_id=commitment_id,
            kind="proposal",
            policy_pick=f"pick-{side.letter}",
            policy_alternative=None,
        )
        for side, commitment_id in zip(card.proposals, commitments, strict=True)
    ]
    SlotLedger(harness.db).save_slot_cards(rows)


def test_corrected_card_saves_slot_rows_before_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The new card's side rows land keyed by card id and letter.

    The changed side takes commitment and kind from its new result; the
    unchanged side copies the old row with the new card id and letter.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    seed_note(harness, 301, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    assert "sendPhoto" in method_order(harness)
    row = VoiceLedger(harness.db).load(301)
    assert row is not None and row.new_card_id is not None

    from framework.cycle.slot_ledger import SlotLedger

    saved = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert [(item.card_id, item.letter) for item in saved] == [
        (row.new_card_id, "A"),
        (row.new_card_id, "B"),
    ]
    changed, unchanged = saved
    assert (changed.commitment_id, changed.kind) == (WRITE2_ID, "proposal")
    assert changed.slot == old.slot and changed.subject_id == SUBJECT
    assert changed.bucket == "loved"
    assert changed.as_of == harness.now
    assert (changed.policy_pick, changed.policy_alternative) == ("pick-A", None)
    assert (unchanged.commitment_id, unchanged.kind) == (REST_ID, "proposal")
    assert unchanged.as_of == SAT_SLOT
    assert (unchanged.policy_pick, unchanged.policy_alternative) == ("pick-B", None)


def test_corrected_card_saves_no_rows_without_old_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A card with no old rows still sends, saving no rows."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 302, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(302)
    assert row is not None and row.new_card_id is not None

    from framework.cycle.slot_ledger import SlotLedger

    assert SlotLedger(harness.db).slot_cards_for_card(row.new_card_id) == ()


def test_relettered_lone_side_row_copies_old_letter_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone remaining side relettered A keeps the old B row's profile."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)

    def _noop(**kwargs: Any) -> ProposalResult:
        return ProposalResult(
            kind="noop",
            profile_id="builder",
            subject_id=SUBJECT,
            cycle_id="cycle-1",
            run=1,
            slot=kwargs["slot"],
            hour=None,
            briefing=None,
            fallback=None,
            reason_codes=("ELIGIBLE_EMPTY",),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="h",
        )

    harness.result_script["builder"] = [_noop]
    seed_note(harness, 303, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(303)
    assert row is not None and row.new_card_id is not None
    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    assert [(side.letter, side.title) for side in new.proposals] == [
        ("A", "Evening rest")
    ]

    from framework.cycle.slot_ledger import SlotLedger

    saved = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert len(saved) == 1
    assert (saved[0].card_id, saved[0].letter) == (row.new_card_id, "A")
    assert (saved[0].profile_id, saved[0].commitment_id) == (
        "disconnect",
        REST_ID,
    )
    assert (saved[0].policy_pick, saved[0].policy_alternative) == ("pick-B", None)


def test_retried_note_with_saved_rows_keeps_same_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rows saved before a not-sent failure do not fail the retry's save."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    harness.fake.queue_script("sendPhoto", ("429", 500))
    seed_note(harness, 304, reply_to=700)

    assert claim_and_process(harness) == "waiting"
    first = VoiceLedger(harness.db).load(304)
    assert first is not None and first.new_card_id is None
    assert first.attempts == 1

    harness.now = harness.now + timedelta(seconds=6)
    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(304)
    assert row is not None and row.new_card_id is not None

    from framework.cycle.slot_ledger import SlotLedger

    saved = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert len(saved) == 2


def test_offered_side_uses_rows_despite_matching_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A title accidentally shared with the other side still finds its row."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(
        harness,
        message_id=700,
        titles=("Draft the release notes", "Finish the write-up"),
    )
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    seed_note(harness, 305, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    assert harness.wonder_calls == {"builder": 1}
    row = VoiceLedger(harness.db).load(305)
    assert row is not None and row.new_card_id is not None
    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    assert new.proposals[0].title == "Draft the release notes"


def test_offered_side_uses_row_despite_changed_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A renamed side still counts as offered when its row names the commitment."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(
        harness,
        message_id=700,
        titles=("Draft the release notes", "Evening rest"),
    )
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    seed_note(harness, 307, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(307)
    assert row is not None and row.new_card_id is not None


def test_offered_side_ignores_title_match_without_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A title match without a row for the commitment is not an offer."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old, commitments=(WRITE2_ID, REST_ID))
    seed_note(harness, 308, reply_to=700)

    assert claim_and_process(harness) == "applied_card_stands"
    assert harness.wonder_calls == {}
    row = VoiceLedger(harness.db).load(308)
    assert row is not None and row.new_card_id is None


def test_delivery_unknown_closes_at_once_without_resend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unknown delivery ends the note; the card is never resent."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    harness.fake.queue_script("sendPhoto", ("500",))
    seed_note(harness, 306, reply_to=700)

    assert claim_and_process(harness) == "delivery_unknown"
    assert method_order(harness).count("sendPhoto") == 1
    texts = sent_texts(harness)
    assert len(texts) == 1
    reply = texts[0]["text"]
    assert reply.startswith('Heard: "skip the write-up today"')
    assert "Skipped: Finish the write-up (today)." in reply
    assert "I can't tell whether the new card reached this chat." in reply
    assert reply.endswith("Took 0.0s.")

    row = VoiceLedger(harness.db).load(306)
    assert row is not None
    assert row.status == "done" and row.outcome == "delivery_unknown"
    events = voice_events(harness)
    assert len(events) == 1
    assert events[0].data.outcome == "delivery_unknown"
    assert VoiceLedger(harness.db).claim_next(harness.now) is None


def test_delivery_unknown_with_failing_reply_still_closes_without_resend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unknown card send plus a failed reply still closes delivery_unknown.

    The reply failing must not reopen the note: a retry would re-propose
    and send a second card, breaking the one rule of this outcome.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    harness.fake.queue_script("sendPhoto", "accept-then-timeout")
    harness.fake.queue_script("sendMessage", ("500",), ("500",))
    seed_note(harness, 312, reply_to=700)

    assert claim_and_process(harness) == "delivery_unknown"
    assert method_order(harness).count("sendPhoto") == 1
    row = VoiceLedger(harness.db).load(312)
    assert row is not None
    assert row.status == "done" and row.outcome == "delivery_unknown"
    assert row.new_card_id is None
    events = voice_events(harness)
    assert len(events) == 1
    assert events[0].data.outcome == "delivery_unknown"

    # A later pass finds nothing due and sends nothing more.
    harness.now = harness.now + timedelta(seconds=900)
    assert VoiceLedger(harness.db).claim_next(harness.now) is None
    assert method_order(harness).count("sendPhoto") == 1
    assert len(voice_events(harness)) == 1


def test_wonder_factory_failure_waits_then_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Wonder client that cannot be built waits; the note completes later.

    The factory error must land in the worker's transient wait with the
    stores closed, never in a corrected card built from old rows.
    """
    import dataclasses
    import threading

    from framework.voice.worker import VoiceWorker

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    real_factory = deps_of(harness).make_wonder_client
    calls = {"n": 0}

    def _flaky(terms: tuple[str, ...], available: bool) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic wonder factory boom")
        return real_factory(terms, available)

    deps = dataclasses.replace(deps_of(harness), make_wonder_client=_flaky)
    seed_note(harness, 320, reply_to=700)
    worker = VoiceWorker(deps, threading.Event())
    worker.drain(timeout_s=5.0)
    row = VoiceLedger(harness.db).load(320)
    assert row is not None and row.status == "pending" and row.attempts == 1
    assert method_order(harness).count("sendPhoto") == 0

    harness.now = harness.now + timedelta(seconds=6)
    worker.drain(timeout_s=5.0)
    row = VoiceLedger(harness.db).load(320)
    assert row is not None and row.outcome == "applied_card"
    assert method_order(harness).count("sendPhoto") == 1


def test_corrected_statements_follow_ticket_13_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A corrected card shows at most 3 claims per side like a regular one."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(
        harness,
        old,
        claims_b=[(f"d{i}", f"Old disconnect line {i}.", [], []) for i in range(4)],
    )
    seed_slot_rows(harness, old)
    harness.result_script["builder"] = [
        lambda **kwargs: proposal_with_claims(
            "builder",
            kwargs,
            [(f"n{i}", f"New builder line {i}.", [], []) for i in range(5)],
        )
    ]
    seed_note(harness, 307, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(307)
    assert row is not None and row.new_card_id is not None
    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    assert new.statements == (
        "A · Builder",
        "New builder line 0.",
        "New builder line 1.",
        "New builder line 2.",
        "B · Disconnect",
        "Old disconnect line 0.",
        "Old disconnect line 1.",
        "Old disconnect line 2.",
    )


def test_night_rule_filters_disconnect_on_corrected_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """From 21:00 a corrected Disconnect side offers only music or rest."""
    night_commitments: list[dict[str, object]] = [
        {
            "id": WRITE_ID,
            "profile_id": "builder",
            "title": "Finish the write-up",
            "kind": "write",
            "dimension": "love",
            "evidence": "tap",
        },
        {
            "id": "cm-night-write",
            "profile_id": "disconnect",
            "title": "Night code",
            "kind": "write",
            "dimension": "love",
            "evidence": "tap",
        },
        {
            "id": REST_ID,
            "profile_id": "disconnect",
            "title": "Evening rest",
            "kind": "rest",
            "dimension": "limit",
            "evidence": "tap",
        },
    ]
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("fact_correction", None, None)],
        transcript=b"that statement is wrong",
        commitments_json=night_commitments,
    )
    slot = datetime(2026, 10, 31, 18, 0, tzinfo=MADRID)
    start = slot.replace(hour=21, minute=5, second=0, microsecond=0)
    end = slot.replace(hour=21, minute=30, second=0, microsecond=0)
    old = Card(
        slot=slot,
        since_line="Since 15:30: synthetic build notes.",
        proposals=(  # type: ignore[arg-type]
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": "Finish the write-up",
                "start": start,
                "end": end,
            },
            {
                "letter": "B",
                "kind": "proposal",
                "profile": "Disconnect",
                "title": "Night code",
                "start": start,
                "end": end,
            },
        ),
        statements=(),
    )
    ledger = CardLedger(harness.db)
    ledger.save_card(old)
    ledger.save_chart(old.card_id, seed_chart())
    ledger.save_card_message(700, old.card_id)
    seed_results(
        harness,
        old,
        claims_a=[("c-a-1", "Builder line.", ["fact-1"], [])],
        claims_b=[("c-b-1", "Disconnect line.", ["fact-2"], [])],
    )
    seed_slot_rows(harness, old, commitments=(WRITE_ID, "cm-night-write"))

    def _fresh(profile_id: str, line: str) -> Any:
        def _run(**kwargs: Any) -> Any:
            return proposal_with_claims(
                profile_id,
                kwargs,
                [(f"n-{profile_id}", line, [], [])],
                end_hour=21,
            )

        return _run

    harness.result_script["builder"] = [_fresh("builder", "Fresh builder line.")]
    harness.result_script["disconnect"] = [
        _fresh("disconnect", "Fresh disconnect line.")
    ]
    harness.now = datetime(2026, 10, 31, 21, 6, tzinfo=MADRID)
    seed_note(
        harness,
        308,
        reply_to=700,
        said_at=datetime(2026, 10, 31, 21, 5, tzinfo=MADRID),
        received_at=harness.now,
    )

    assert claim_and_process(harness) == "fact_disputed_card"
    row = VoiceLedger(harness.db).load(308)
    assert row is not None and row.new_card_id is not None
    new = CardLedger(harness.db).load(row.new_card_id)
    assert new is not None
    by_letter = {side.letter: side for side in new.proposals}
    assert by_letter["B"].title == "Evening rest"


def test_wonder_local_retry_still_applies_and_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One LocalStartFailure on Wonder still ends applied_card, sleep faked."""
    from framework.proposal.core import WonderResponse
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import LocalStartFailure

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)

    sleeps: list[float] = []

    class _FailOnce:
        transport = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: Any) -> WonderResponse:
            self.calls += 1
            if self.calls == 1:
                raise LocalStartFailure(
                    "exit 1", latency_ms=5, exit_code=1, stderr_masked="masked"
                )
            return WonderResponse(
                text="{}",
                model_reported="fake",
                latency_ms=5,
                finish_reason="stop",
                prompt_tokens=1,
                completion_tokens=1,
                reasoning_tokens=None,
            )

    inner = _FailOnce()

    def _retry_factory(terms: tuple[str, ...], available: bool) -> LocalRetryClient:
        return LocalRetryClient(inner, sleep=sleeps.append)  # type: ignore[arg-type]

    import dataclasses

    from framework.voice.worker import process_one as _process_one

    deps = dataclasses.replace(deps_of(harness), make_wonder_client=_retry_factory)

    def _propose(**kwargs: Any) -> Any:
        from framework.proposal.core import WonderRequest

        kwargs["client"].complete(
            WonderRequest(
                prompt="synthetic",
                model="synthetic",
                effort="low",
                response_schema={},
            )
        )
        return harness.propose(**kwargs)

    deps = dataclasses.replace(deps, propose_fn=_propose)
    seed_note(harness, 309, reply_to=700)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert _process_one(deps, row) == "applied_card"
    assert sleeps == [5.0]
    fresh = VoiceLedger(harness.db).load(309)
    assert fresh is not None and fresh.outcome == "applied_card"
    steps = json.loads(fresh.step_seconds or "{}")
    assert not [key for key in steps if key.startswith("wonder_retry_")]
    assert set(steps) >= {"download", "transcribe", "compile", "apply", "send_reply"}
    from framework.cycle.slot_ledger import SlotLedger

    retries = SlotLedger(harness.db).local_retries_for_slot(old.slot)
    assert len(retries) == 1
    retry = retries[0]
    assert retry.slot == old.slot and retry.profile == "builder"
    assert (retry.attempt, retry.reason) == (1, "exit 1")
    assert (retry.latency_ms, retry.exit_code) == (5, 1)
    assert retry.stderr_masked == "masked"
    reply = sent_texts(harness)[-1]["text"]
    assert "New card above. Took" in reply
    assert "masked" not in reply


def test_wonder_local_retry_store_error_still_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing retry-row write never fails the note."""
    import sqlite3

    from framework.cycle.slot_ledger import SlotLedger
    from framework.proposal.core import WonderResponse
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import LocalStartFailure

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)

    class _FailOnce:
        transport = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: Any) -> WonderResponse:
            self.calls += 1
            if self.calls == 1:
                raise LocalStartFailure(
                    "exit 1", latency_ms=5, exit_code=1, stderr_masked="masked"
                )
            return WonderResponse(
                text="{}",
                model_reported="fake",
                latency_ms=5,
                finish_reason="stop",
                prompt_tokens=1,
                completion_tokens=1,
                reasoning_tokens=None,
            )

    def _retry_factory(terms: tuple[str, ...], available: bool) -> LocalRetryClient:
        return LocalRetryClient(_FailOnce(), sleep=lambda s: None)  # type: ignore[arg-type]

    def _boom(self: Any, *args: Any, **kwargs: Any) -> int:
        raise sqlite3.Error("synthetic store failure")

    monkeypatch.setattr(SlotLedger, "append_local_retry", _boom)

    import dataclasses

    from framework.voice.worker import process_one as _process_one

    deps = dataclasses.replace(deps_of(harness), make_wonder_client=_retry_factory)

    def _propose(**kwargs: Any) -> Any:
        from framework.proposal.core import WonderRequest

        kwargs["client"].complete(
            WonderRequest(
                prompt="synthetic",
                model="synthetic",
                effort="low",
                response_schema={},
            )
        )
        return harness.propose(**kwargs)

    deps = dataclasses.replace(deps, propose_fn=_propose)
    seed_note(harness, 322, reply_to=700)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert _process_one(deps, row) == "applied_card"
    fresh = VoiceLedger(harness.db).load(322)
    assert fresh is not None and fresh.outcome == "applied_card"


def test_default_wonder_factory_retries_but_compile_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Wonder client is exactly LocalRetryClient around MuseExecClient.

    LocalRetryClient retries only fast local start failures, so a timed-out
    re-proposal call is not retried.
    """
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import MuseExecClient
    from framework.telegram import client as client_module
    from framework.telegram.client import TelegramClient

    harness = make_harness(
        monkeypatch, tmp_path, compile_script=[], transcript=b"heard words here"
    )
    monkeypatch.setattr(client_module, "_open_url", harness.fake)
    deps = build_voice_deps(
        harness.environ,
        client=TelegramClient(api_base=FAKE_API_BASE),
        db_path=harness.tmp_path / "factory-probe.db",
        now_fn=lambda: harness.now,
    )
    wonder = deps.make_wonder_client((), False)
    assert isinstance(wonder, LocalRetryClient)
    assert type(wonder) is LocalRetryClient
    assert type(wonder._inner) is MuseExecClient  # type: ignore[attr-defined]
    compile_client = deps.make_compile_client((), False)
    assert isinstance(compile_client, MuseExecClient)
    assert not isinstance(compile_client, LocalRetryClient)
    assert wonder._inner._timeout_s == 60.0  # type: ignore[attr-defined]
    assert compile_client._timeout_s == 60.0


def test_no_cycle_rows_pass_no_cycle_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stored no-cycle rows reach run_proposals with no cycle id."""
    from framework.cycle import UnknownCycleError

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old, cycle_id="no-cycle")
    seed_slot_rows(harness, old)
    seen: dict[str, Any] = {}

    def _propose(**kwargs: Any) -> Any:
        seen["cycle_id"] = kwargs["cycle_id"]
        if kwargs["cycle_id"] is not None:
            raise UnknownCycleError("unknown cycle")
        return harness.propose(**kwargs)

    import dataclasses

    deps = dataclasses.replace(deps_of(harness), propose_fn=_propose)
    seed_note(harness, 310, reply_to=700)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    from framework.voice.worker import process_one as _process_one

    assert _process_one(deps, row) == "applied_card"
    assert seen["cycle_id"] is None


def test_stored_cycle_id_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stored id naming a stored cycle still reaches run_proposals."""
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old, cycle_id="cycle-1")
    seed_slot_rows(harness, old)
    _record_dispute_cycle(harness.db)
    seen: dict[str, Any] = {}

    def _propose(**kwargs: Any) -> Any:
        seen["cycle_id"] = kwargs["cycle_id"]
        return harness.propose(**kwargs)

    import dataclasses

    deps = dataclasses.replace(deps_of(harness), propose_fn=_propose)
    seed_note(harness, 311, reply_to=700)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    from framework.voice.worker import process_one as _process_one

    assert _process_one(deps, row) == "applied_card"
    assert seen["cycle_id"] == "cycle-1"


def test_1130_voice_correction_reproposes_from_1130(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A correction to the Nov 3 11:30 card re-proposes from 11:30."""
    import dataclasses
    from datetime import time as _time

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    dated = datetime(2026, 11, 3, 11, 30, tzinfo=MADRID)
    old = seed_old_card(harness, slot=dated, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 91, reply_to=700)
    seen: dict[str, Any] = {}
    original_propose = harness.propose

    def spy_propose(**kwargs: Any) -> Any:
        seen["limits"] = kwargs["limits"]
        return original_propose(**kwargs)

    deps = dataclasses.replace(deps_of(harness), propose_fn=spy_propose)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "applied_card"
    assert seen["limits"].allowed_start == _time(11, 30)


def test_voice_correction_ordinary_slot_keeps_injected_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pinning: any other slot's correction sees the voice deps limits."""
    import dataclasses
    from datetime import time as _time

    from framework.briefing.context import ProfileLimits as _ProfileLimits

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_note(harness, 92, reply_to=700)
    unusual = _ProfileLimits(
        timezone="Europe/Madrid",
        allowed_start=_time(14, 0),
        allowed_end=_time(14, 30),
    )
    seen: dict[str, Any] = {}
    original_propose = harness.propose

    def spy_propose(**kwargs: Any) -> Any:
        seen["limits"] = kwargs["limits"]
        return original_propose(**kwargs)

    deps = dataclasses.replace(deps_of(harness), limits=unusual, propose_fn=spy_propose)
    row = VoiceLedger(harness.db).claim_next(harness.now)
    assert row is not None
    assert process_one(deps, row) == "applied_card"
    assert seen["limits"] is unusual


def _live_path_harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Harness:
    """The live poller's store shape: one folder, one file, no explicit path.

    The made-up store is seeded through explicit-path ledgers, then the
    deps carry ``db_path=None`` and the path is found from
    ``IKIGAI_DATA_DIR`` at call time, as the live poller leaves it.
    """
    import dataclasses

    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("IKIGAI_DATA_DIR", str(data))
    harness.db = data / "ikigai.db"
    harness.deps = dataclasses.replace(deps_of(harness), db_path=None)
    return harness


def test_corrected_card_saves_slot_rows_no_explicit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no explicit path a corrected card still gets its slot rows.

    The unchanged side copies the old row with the new card id and letter
    and its old ``as_of``; the changed side takes its new commitment and
    kind with the handling instant as ``as_of``.
    """
    harness = _live_path_harness(monkeypatch, tmp_path)
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    seed_note(harness, 301, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(301)
    assert row is not None and row.new_card_id is not None

    from framework.cycle.slot_ledger import SlotLedger

    saved = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert [(item.card_id, item.letter) for item in saved] == [
        (row.new_card_id, "A"),
        (row.new_card_id, "B"),
    ]
    changed, unchanged = saved
    assert (changed.commitment_id, changed.kind) == (WRITE2_ID, "proposal")
    assert changed.slot == old.slot and changed.subject_id == SUBJECT
    assert changed.bucket == "loved"
    assert changed.as_of == harness.now
    assert (changed.policy_pick, changed.policy_alternative) == ("pick-A", None)
    assert (unchanged.commitment_id, unchanged.kind) == (REST_ID, "proposal")
    assert unchanged.as_of == SAT_SLOT
    assert (unchanged.policy_pick, unchanged.policy_alternative) == ("pick-B", None)


def test_corrected_tap_counted_no_explicit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no explicit path a tap on the corrected card is counted.

    The tap's ruling comes from the rows the worker saved, read back
    through the same environment resolution the live path uses.
    """
    from framework.collectors.common import event_id
    from framework.cycle.orchestrator import rebuild_state
    from framework.cycle.slot_ledger import SlotLedger
    from framework.schemas.events import AppTapData, Event
    from framework.store import resolve_db_path
    from framework.telegram.service import COLLECTOR_VERSION

    harness = _live_path_harness(monkeypatch, tmp_path)
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old, bucket="evening")
    seed_note(harness, 301, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(301)
    assert row is not None and row.new_card_id is not None
    tap = Event(
        id=event_id("telegram", "tap:no-explicit-path"),
        subject_id=SUBJECT,
        source="telegram",
        type="app.tap",
        time=harness.now,
        source_id="tap:no-explicit-path",
        data=AppTapData(block_id=row.new_card_id, target="A"),
        tier="private",
        collected_at=harness.now,
        collector_version=COLLECTOR_VERSION,
    )
    through_env = SlotLedger(resolve_db_path(None)).slot_cards_for_card(row.new_card_id)
    through_path = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert tuple(through_env) == tuple(through_path)
    state, skipped = rebuild_state((tap,), through_env)
    expected, expected_skipped = rebuild_state((tap,), through_path)
    assert skipped == 0
    assert (state, skipped) == (expected, expected_skipped)


def test_local_retry_recorded_no_explicit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no explicit path a retried local start failure is recorded."""
    import dataclasses

    from framework.cycle.slot_ledger import SlotLedger
    from framework.proposal.local_retry import LocalRetryClient
    from framework.proposal.muse_client import LocalStartFailure
    from framework.voice.worker import process_one as _process_one

    harness = _live_path_harness(monkeypatch, tmp_path)
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)

    class _FailOnce:
        transport = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: Any) -> Any:
            from framework.proposal.core import WonderResponse

            self.calls += 1
            if self.calls == 1:
                raise LocalStartFailure(
                    "exit 1", latency_ms=5, exit_code=1, stderr_masked="masked"
                )
            return WonderResponse(
                text="{}",
                model_reported="fake",
                latency_ms=5,
                finish_reason="stop",
                prompt_tokens=1,
                completion_tokens=1,
                reasoning_tokens=None,
            )

    def _retry_factory(terms: tuple[str, ...], available: bool) -> LocalRetryClient:
        return LocalRetryClient(_FailOnce(), sleep=lambda s: None)  # type: ignore[arg-type]

    def _propose(**kwargs: Any) -> Any:
        from framework.proposal.core import WonderRequest

        kwargs["client"].complete(
            WonderRequest(
                prompt="synthetic",
                model="synthetic",
                effort="low",
                response_schema={},
            )
        )
        return harness.propose(**kwargs)

    deps = dataclasses.replace(
        deps_of(harness), make_wonder_client=_retry_factory, propose_fn=_propose
    )
    seed_note(harness, 309, reply_to=700)
    claimed = VoiceLedger(harness.db).claim_next(harness.now)
    assert claimed is not None
    assert _process_one(deps, claimed) == "applied_card"

    retries = SlotLedger(harness.db).local_retries_for_slot(old.slot)
    assert len(retries) == 1
    retry = retries[0]
    assert retry.slot == old.slot and retry.profile == "builder"
    assert (retry.attempt, retry.reason) == (1, "exit 1")
    assert (retry.latency_ms, retry.exit_code) == (5, 1)
    assert retry.stderr_masked == "masked"


def test_corrected_card_saves_slot_rows_explicit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pinning: the explicit-path corrected card writes today's rows.

    This is the behaviour D1 and D4 must keep line for line; it passes
    with and without the fix.
    """
    harness = make_harness(
        monkeypatch,
        tmp_path,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old = seed_old_card(harness, message_id=700)
    seed_results(harness, old)
    seed_slot_rows(harness, old)
    seed_note(harness, 301, reply_to=700)

    assert claim_and_process(harness) == "applied_card"
    row = VoiceLedger(harness.db).load(301)
    assert row is not None and row.new_card_id is not None

    from framework.cycle.slot_ledger import SlotLedger

    saved = SlotLedger(harness.db).slot_cards_for_card(row.new_card_id)
    assert [(item.card_id, item.letter) for item in saved] == [
        (row.new_card_id, "A"),
        (row.new_card_id, "B"),
    ]
    changed, unchanged = saved
    assert (changed.commitment_id, changed.kind) == (WRITE2_ID, "proposal")
    assert changed.slot == old.slot and changed.subject_id == SUBJECT
    assert changed.bucket == "loved"
    assert changed.as_of == harness.now
    assert (changed.policy_pick, changed.policy_alternative) == ("pick-A", None)
    assert (unchanged.commitment_id, unchanged.kind) == (REST_ID, "proposal")
    assert unchanged.as_of == SAT_SLOT
    assert (unchanged.policy_pick, unchanged.policy_alternative) == ("pick-B", None)
