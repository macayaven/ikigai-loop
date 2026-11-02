"""Slice A, AT-A7: the scorer rates a returned file against its key."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.context import TimeInterval
from framework.briefing.schemas import Action, Briefing, Claim, MetricRef, Section
from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
from framework.glimmer.facts import FactResult, PassResult
from framework.proposal.core import AttemptOutcome, ProposalResult
from framework.rater.__main__ import main as rater_main
from framework.schemas.core import Fact, FactWindow
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.telegram.models import Card

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-rater-test"
DENY_TERM = "synthetic-denied-term"

_COMMITMENTS = [
    {
        "id": "b-write",
        "profile_id": "builder",
        "title": "Draft the weekly notes",
        "kind": "write",
        "dimension": "world_needs",
        "evidence": "tap",
    },
    {
        "id": "d-rest",
        "profile_id": "disconnect",
        "title": "Rest with music",
        "kind": "rest",
        "dimension": "love",
        "evidence": "no_screen",
    },
]


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    crit = tmp_path / "criteria"
    crit.mkdir(exist_ok=True)
    (crit / "deny-terms.txt").write_text(DENY_TERM + "\n", encoding="utf-8")
    cfile = tmp_path / "commitments.json"
    cfile.write_text(json.dumps(_COMMITMENTS), encoding="utf-8")
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(crit))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(cfile))
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
    return tmp_path / "store.db"


def _two_claim_store(db: Path, slot: datetime, value: float = 2.0) -> None:
    texts = ["Pushes were 2 in the last period.", "Pushes were 3 in the last period."]
    sections = [
        Section(  # type: ignore[arg-type]
            type="overall_state",
            claims=[
                Claim(
                    id="c-a",
                    text=texts[0],
                    fact_ids=["f1"],
                    metric_refs=[
                        MetricRef(metric_id="period.last.pushes", value=value)
                    ],
                )
            ],
        ),
        Section(
            type="actions",
            claims=[],
            actions=[  # type: ignore[arg-type]
                Action(
                    id="act-1",
                    commitment_id="b-write",
                    kind="write",  # type: ignore[arg-type]
                    text="side title",
                    dimension="love",  # type: ignore[arg-type]
                    proposed_start=slot + timedelta(minutes=30),
                    proposed_end=slot + timedelta(hours=1, minutes=30),
                )
            ],
        ),
    ]
    briefing = Briefing(
        id="brf-1",
        profile_id="builder",
        subject_id=SUBJECT,
        slot=slot,
        sections=sections,
    )
    second = Briefing.model_validate(
        {
            **briefing.model_dump(mode="json"),
            "id": "brf-2",
            "sections": [
                {
                    **sections[0].model_dump(mode="json"),
                    "claims": [
                        {
                            **sections[0].claims[0].model_dump(mode="json"),
                            "text": texts[1],
                        }
                    ],
                },
                sections[1].model_dump(mode="json"),
            ],
        }
    )
    store = ProposalStore(db)
    try:
        from framework.briefing.context import TimeInterval as _TI

        for item, model, effort in (
            (briefing, "muse-wonder-1.0", "high"),
            (second, "muse-wonder-1.0", "high"),
        ):
            store.record(
                ProposalResult(
                    kind="proposal",
                    profile_id="builder",  # type: ignore[arg-type]
                    subject_id=SUBJECT,
                    cycle_id="cycle-1",
                    run=1,
                    slot=slot,
                    hour=_TI(
                        start=slot + timedelta(minutes=30),
                        end=slot + timedelta(hours=1, minutes=30),
                    ),
                    briefing=item,
                    fallback=None,
                    reason_codes=(),
                    attempts=(
                        AttemptOutcome(
                            number=1,
                            model_requested=model,
                            model_reported=model,
                            effort=effort,
                            prompt_hash="h",
                            raw_text="{}",
                            parsed_ok=True,
                            blocked=False,
                            codes=(),
                            latency_ms=3,
                            prompt_tokens=None,
                            completion_tokens=None,
                            reasoning_tokens=None,
                            finish_reason="stop",
                            cached_tokens=None,
                            transport="muse",
                            transport_version=None,
                            harness_rules_file=None,
                        ),
                    ),
                    cycle_age_s=0.0,
                    prompt_hash="h",
                ),
                snapshot={},
            )
    finally:
        store.close()
    window = FactWindow(start=slot - timedelta(hours=72), end=slot)
    result = FactResult(
        facts=(
            Fact(
                id="f1",
                subject_id=SUBJECT,
                window=window,
                statement=texts[0],
                evidence=["evt-made-up-1"],
                tier="public",
            ),  # type: ignore[arg-type]
        ),
        code_fact_ids=(),
        snapshot=__import__(
            "framework.briefing.context", fromlist=["MetricSnapshot"]
        ).MetricSnapshot(values={}),
        passes=(
            PassResult(
                name="personal",
                attempts=0,
                raw_valid=False,
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
                raw_valid=False,
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
        as_of=slot,
        window_start=slot - timedelta(hours=72),
        prompt_hash="ph",
        dropped=(),
        is_noop=False,
        noop_reason=None,
    )
    facts = FactStore(db_path=db)
    try:
        facts.record_cycle(result)
    finally:
        facts.close()
    # Two delivered cards, one claim each.
    ledger = SlotLedger(db)
    for index, text in enumerate(texts):
        start = slot + timedelta(minutes=30)
        card = Card(
            slot=slot,
            since_line="Since 15:00: made-up notes.",
            proposals=(  # type: ignore[arg-type]
                {
                    "letter": "A",
                    "kind": "proposal",
                    "profile": "Builder",
                    "title": "Draft the weekly notes",
                    "start": start,
                    "end": start + timedelta(hours=1),
                },
            ),
            statements=("A · Builder", text),
        )
        assert index == 0 or card.card_id != ""
        ledger.save_card_step(
            slot,
            card.card_id,
            {},
            (
                SlotCardRow(
                    card_id=card.card_id,
                    letter="A",
                    slot=slot,
                    subject_id=SUBJECT,
                    as_of=slot,
                    bucket="evening",
                    profile_id="builder",
                    commitment_id="b-write",
                    kind="proposal",
                    policy_pick=None,
                    policy_alternative=None,
                ),
            ),
            card.model_dump_json(),
            "{}",
            0.5,
        )
        ledger.append_step(slot, "send", "delivered", 0.5, card.card_id, {})


def _pack_paths(outdir: Path) -> tuple[Path, Path]:
    key = next(outdir.glob("*.key.json"))
    html = next(outdir.glob("*.html"))
    return key, html


def _run_score(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> tuple[int, str]:
    code = rater_main(["score", *args])
    return code, capsys.readouterr().out


def _result_for(key_path: Path, labels: list[str]) -> Path:
    key = json.loads(key_path.read_text(encoding="utf-8"))
    ids = sorted(key["items"])
    assert len(labels) <= len(ids)
    result = {
        "pack_id": key["pack_id"],
        "pack_hash": key["pack_hash"],
        "started_at": "2026-11-03T10:00:00+01:00",
        "ended_at": "2026-11-03T10:08:00+01:00",
        "answers": [
            {
                "item_id": item_id,
                "label": label,
                "answered_at": "2026-11-03T10:01:00+01:00",
            }
            for item_id, label in zip(ids, labels)
        ],
    }
    path = key_path.parent / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def _pack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db: Path,
    out: Path,
    seed: str = "987654321",
    extra: tuple[str, ...] = (),
) -> tuple[int, str]:
    code = rater_main(
        [
            "pack",
            "--db",
            str(db),
            "--out-dir",
            str(out),
            "--seed",
            seed,
            "--cut",
            "2026-11-04T18:00:00+01:00",
            *extra,
        ]
    )
    return code, capsys.readouterr().out


def _parse(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        if line.startswith(("pair=", "combined ")):
            prefix, _, rest = line.partition(" ")
            for token in rest.split(" "):
                if "=" in token:
                    key, _, value = token.partition("=")
                    out[f"{prefix} {key}"] = value
        else:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def test_score_rates_over_every_atomic_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    outdir = tmp_path / "pack"
    code, out = _pack(monkeypatch, capsys, db, outdir)
    assert code == 0, out
    key, _ = _pack_paths(outdir)
    result = _result_for(key, ["supported", "supported"])
    code, out = _run_score(monkeypatch, capsys, ["--pair", str(key), str(result)])
    assert code == 0, out
    counts = _parse(out)
    assert counts["pair=0 claims_in_pack"] == "2"
    assert counts["pair=0 rated"] == "2"
    assert counts["pair=0 supported"] == "2"
    assert counts["pair=0 support_rate"] == "1.0000"
    assert counts["pair=0 n"] == "2"
    assert counts["combined support_rate"] == "1.0000"


def test_mixed_labels_have_own_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    outdir = tmp_path / "pack"
    code, out = _pack(monkeypatch, capsys, db, outdir)
    assert code == 0, out
    key, _ = _pack_paths(outdir)
    result = _result_for(key, ["cant_tell"])
    code, out = _run_score(monkeypatch, capsys, ["--pair", str(key), str(result)])
    assert code == 0, out
    counts = _parse(out)
    assert counts["pair=0 cant_tell"] == "1"
    assert counts["pair=0 unanswered"] == "1"
    assert counts["pair=0 rated"] == "1"
    assert counts["pair=0 support_rate"] == "0.0000"


def test_per_model_effort_rates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    outdir = tmp_path / "pack"
    code, out = _pack(monkeypatch, capsys, db, outdir)
    assert code == 0, out
    key, _ = _pack_paths(outdir)
    result = _result_for(key, ["supported", "not_supported"])
    code, out = _run_score(monkeypatch, capsys, ["--pair", str(key), str(result)])
    assert code == 0, out
    assert (
        "pair=0 rate model=muse-wonder-1.0 effort=high supported=1 n=2 rate=0.5000"
        in out
    )


def test_scorer_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    outdir = tmp_path / "pack"
    code, out = _pack(monkeypatch, capsys, db, outdir)
    assert code == 0, out
    key, _ = _pack_paths(outdir)
    good = _result_for(key, ["supported", "supported"])
    payload = json.loads(good.read_text(encoding="utf-8"))

    def _write(name: str, mutate: object) -> Path:
        import copy

        other = copy.deepcopy(payload)
        mutate(other)  # type: ignore[operator]
        path = outdir / name
        path.write_text(json.dumps(other), encoding="utf-8")
        return path

    bad_hash = _write("bad-hash.json", lambda doc: doc.update(pack_hash="0" * 64))
    bad_id = _write("bad-id.json", lambda doc: doc.update(pack_id="pack-nope"))
    unknown = _write(
        "unknown.json",
        lambda doc: doc["answers"].append(
            {
                "item_id": "item-9999",
                "label": "supported",
                "answered_at": "2026-11-03T10:01:00+01:00",
            }
        ),
    )
    repeated = _write(
        "repeated.json", lambda doc: doc["answers"].append(doc["answers"][0])
    )
    bad_label = _write(
        "bad-label.json",
        lambda doc: doc["answers"].__setitem__(
            0, {**doc["answers"][0], "label": "maybe"}
        ),
    )
    for name, path in (
        ("pack_hash_mismatch", bad_hash),
        ("pack_id_mismatch", bad_id),
        ("unknown_item", unknown),
        ("repeated_item", repeated),
        ("bad_label", bad_label),
    ):
        code, out = _run_score(monkeypatch, capsys, ["--pair", str(key), str(path)])
        assert code == 1, (name, out)
        assert name in out


def test_multi_pair_together_and_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    first = tmp_path / "pack1"
    code, out = _pack(monkeypatch, capsys, db, first)
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "2"
    key1, _ = _pack_paths(first)
    result1 = _result_for(key1, ["supported", "not_supported"])
    key_path = key1
    second = tmp_path / "pack2"
    code, out = _pack(
        monkeypatch, capsys, db, second, extra=("--exclude-key", str(key_path))
    )
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "0"
    code, out = _run_score(monkeypatch, capsys, ["--pair", str(key1), str(result1)])
    assert code == 0, out
    counts = _parse(out)
    assert counts["pair=0 supported"] == "1"
    assert counts["combined supported"] == "1"
    assert counts["combined claims_in_pack"] == "2"


def test_exclude_key_second_pack_omits_rated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    first = tmp_path / "pack1"
    code, out = _pack(
        monkeypatch, capsys, db, first, extra=("--cut", slot_at("15:30").isoformat())
    )
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "2"
    key1, _ = _pack_paths(first)
    # A later card adds one new claim.
    slot = slot_at("18:00")
    briefing = Briefing(
        id="brf-late",
        profile_id="builder",
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="overall_state",
                claims=[  # type: ignore[arg-type]
                    Claim(
                        id="c-a",
                        text="Pushes were 9 in the last period.",
                        fact_ids=["f9"],
                        metric_refs=[
                            MetricRef(metric_id="period.last.pushes", value=9.0)
                        ],
                    )
                ],
            ),
            Section(
                type="actions",
                claims=[],
                actions=[  # type: ignore[arg-type]
                    Action(
                        id="act-1",
                        commitment_id="b-write",
                        kind="write",  # type: ignore[arg-type]
                        text="side title",
                        dimension="love",  # type: ignore[arg-type]
                        proposed_start=slot + timedelta(minutes=30),
                        proposed_end=slot + timedelta(hours=1, minutes=30),
                    )
                ],
            ),
        ],
    )
    store = ProposalStore(db)
    try:
        store.record(
            ProposalResult(
                kind="proposal",
                profile_id="builder",  # type: ignore[arg-type]
                subject_id=SUBJECT,
                cycle_id="cycle-9",
                run=1,
                slot=slot,
                hour=TimeInterval(
                    start=slot + timedelta(minutes=30),
                    end=slot + timedelta(hours=1, minutes=30),
                ),
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(
                    AttemptOutcome(
                        number=1,
                        model_requested="muse-wonder-1.0",
                        model_reported="muse-wonder-1.0",
                        effort="high",
                        prompt_hash="h",
                        raw_text="{}",
                        parsed_ok=True,
                        blocked=False,
                        codes=(),
                        latency_ms=3,
                        prompt_tokens=None,
                        completion_tokens=None,
                        reasoning_tokens=None,
                        finish_reason="stop",
                        cached_tokens=None,
                        transport="muse",
                        transport_version=None,
                        harness_rules_file=None,
                    ),
                ),
                cycle_age_s=0.0,
                prompt_hash="h",
            ),
            snapshot={},
        )
    finally:
        store.close()
    window = FactWindow(start=slot - timedelta(hours=72), end=slot)
    facts = FactStore(db_path=db)
    try:
        facts.record_cycle(
            FactResult(
                facts=(
                    Fact(
                        id="f9",
                        subject_id=SUBJECT,
                        window=window,
                        statement="Pushes were 9 in the last period.",
                        evidence=["evt-made-up-9"],
                        tier="public",
                    ),
                ),  # type: ignore[arg-type]
                code_fact_ids=(),
                snapshot=__import__(
                    "framework.briefing.context", fromlist=["MetricSnapshot"]
                ).MetricSnapshot(values={}),
                passes=(
                    PassResult(
                        name="personal",
                        attempts=0,
                        raw_valid=False,
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
                        raw_valid=False,
                        model_id="",
                        latency_ms=0,
                        finish_reason=None,
                        completion_tokens=None,
                        kept=0,
                        noop_reason=None,
                    ),
                ),
                responses=(),
                cycle_id="cycle-9",
                subject_id=SUBJECT,
                as_of=slot,
                window_start=slot - timedelta(hours=72),
                prompt_hash="ph",
                dropped=(),
                is_noop=False,
                noop_reason=None,
            )
        )
    finally:
        facts.close()
    start = slot + timedelta(minutes=30)
    card = Card(
        slot=slot,
        since_line="Since 15:30: made-up notes.",
        proposals=(  # type: ignore[arg-type]
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": "Draft the weekly notes",
                "start": start,
                "end": start + timedelta(hours=1),
            },
        ),
        statements=("A · Builder", "Pushes were 9 in the last period."),
    )
    ledger = SlotLedger(db)
    ledger.save_card_step(
        slot,
        card.card_id,
        {},
        (
            SlotCardRow(
                card_id=card.card_id,
                letter="A",
                slot=slot,
                subject_id=SUBJECT,
                as_of=slot,
                bucket="evening",
                profile_id="builder",
                commitment_id="b-write",
                kind="proposal",
                policy_pick=None,
                policy_alternative=None,
            ),
        ),
        card.model_dump_json(),
        "{}",
        0.5,
    )
    ledger.append_step(slot, "send", "delivered", 0.5, card.card_id, {})
    second = tmp_path / "pack2"
    code, out = _pack(
        monkeypatch, capsys, db, second, extra=("--exclude-key", str(key1))
    )
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "1"
    key2, _ = _pack_paths(second)
    result2 = _result_for(key2, ["not_supported"])
    code, out = _run_score(
        monkeypatch,
        capsys,
        [
            "--pair",
            str(key1),
            str(_result_for(key1, ["supported", "supported"])),
            "--pair",
            str(key2),
            str(result2),
        ],
    )
    assert code == 0, out
    counts = _parse(out)
    assert counts["pair=0 supported"] == "2"
    assert counts["pair=1 not_supported"] == "1"
    assert counts["combined claims_in_pack"] == "3"
    assert counts["combined supported"] == "2"
    assert counts["combined support_rate"] == "0.6667"


def test_overlapping_keys_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    first, second = tmp_path / "pack1", tmp_path / "pack2"
    code, out = _pack(monkeypatch, capsys, db, first)
    assert code == 0, out
    code, out = _pack(monkeypatch, capsys, db, second)
    assert code == 0, out
    key1, _ = _pack_paths(first)
    key2, _ = _pack_paths(second)
    result1 = _result_for(key1, ["supported", "supported"])
    code, out = _run_score(
        monkeypatch,
        capsys,
        ["--pair", str(key1), str(result1), "--pair", str(key2), str(result1)],
    )
    assert code == 1
    assert "keys_overlap" in out


def test_hash_covers_evidence_and_default_id_hides_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    slot = slot_at("15:30")
    for name, value in (("a", 2.0), ("b", 5.0)):
        db = db_dir / f"{name}.db"
        crit = tmp_path / f"criteria-{name}"
        crit.mkdir()
        (crit / "deny-terms.txt").write_text(DENY_TERM + "\n", encoding="utf-8")
        cfile = tmp_path / f"commitments-{name}.json"
        cfile.write_text(json.dumps(_COMMITMENTS), encoding="utf-8")
        monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(crit))
        monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(cfile))
        monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
        _two_claim_store(db, slot, value=value)
    first, second = tmp_path / "pack1", tmp_path / "pack2"
    code, out = _pack(monkeypatch, capsys, db_dir / "a.db", first)
    assert code == 0, out
    key1, _ = _pack_paths(first)
    doc1 = json.loads(key1.read_text(encoding="utf-8"))
    code, out = _pack(monkeypatch, capsys, db_dir / "b.db", second)
    assert code == 0, out
    key2, _ = _pack_paths(second)
    doc2 = json.loads(key2.read_text(encoding="utf-8"))
    assert doc1["pack_hash"] != doc2["pack_hash"]
    assert doc1["pack_id"] != doc2["pack_id"]
    for doc in (doc1, doc2):
        assert doc["pack_id"] == "pack-" + doc["pack_hash"][:12]
        assert doc["pack_id"] != "987654321"
        assert "987654321" not in doc["pack_id"]


def test_unlabelled_claims_need_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    _two_claim_store(db, slot_at("15:30"))
    early = tmp_path / "pack1"
    code, out = _pack(
        monkeypatch, capsys, db, early, extra=("--cut", slot_at("15:30").isoformat())
    )
    assert code == 0, out
    key1, _ = _pack_paths(early)
    result = _result_for(key1, ["supported", "supported"])
    code, out = _run_score(
        monkeypatch, capsys, ["--pair", str(key1), str(result), "--db", str(db)]
    )
    assert code == 0, out
    assert "unlabelled_atomic_claims=0" in out
    # A card delivered after the cut was never in any key.
    slot = slot_at("18:00")
    briefing = Briefing(
        id="brf-late",
        profile_id="builder",
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="overall_state",
                claims=[  # type: ignore[arg-type]
                    Claim(
                        id="c-a",
                        text="Pushes were 9 in the last period.",
                        fact_ids=[],
                        metric_refs=[
                            MetricRef(metric_id="period.last.pushes", value=9.0)
                        ],
                    )
                ],
            ),
            Section(
                type="actions",
                claims=[],
                actions=[  # type: ignore[arg-type]
                    Action(
                        id="act-1",
                        commitment_id="b-write",
                        kind="write",  # type: ignore[arg-type]
                        text="side title",
                        dimension="love",  # type: ignore[arg-type]
                        proposed_start=slot + timedelta(minutes=30),
                        proposed_end=slot + timedelta(hours=1, minutes=30),
                    )
                ],
            ),
        ],
    )
    store = ProposalStore(db)
    try:
        store.record(
            ProposalResult(
                kind="proposal",
                profile_id="builder",  # type: ignore[arg-type]
                subject_id=SUBJECT,
                cycle_id="cycle-9",
                run=1,
                slot=slot,
                hour=TimeInterval(
                    start=slot + timedelta(minutes=30),
                    end=slot + timedelta(hours=1, minutes=30),
                ),
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(
                    AttemptOutcome(
                        number=1,
                        model_requested="muse-wonder-1.0",
                        model_reported="muse-wonder-1.0",
                        effort="high",
                        prompt_hash="h",
                        raw_text="{}",
                        parsed_ok=True,
                        blocked=False,
                        codes=(),
                        latency_ms=3,
                        prompt_tokens=None,
                        completion_tokens=None,
                        reasoning_tokens=None,
                        finish_reason="stop",
                        cached_tokens=None,
                        transport="muse",
                        transport_version=None,
                        harness_rules_file=None,
                    ),
                ),
                cycle_age_s=0.0,
                prompt_hash="h",
            ),
            snapshot={},
        )
    finally:
        store.close()
    start = slot + timedelta(minutes=30)
    card = Card(
        slot=slot,
        since_line="Since 15:30: made-up notes.",
        proposals=(  # type: ignore[arg-type]
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": "Draft the weekly notes",
                "start": start,
                "end": start + timedelta(hours=1),
            },
        ),
        statements=("A · Builder", "Pushes were 9 in the last period."),
    )
    ledger = SlotLedger(db)
    ledger.save_card_step(
        slot,
        card.card_id,
        {},
        (
            SlotCardRow(
                card_id=card.card_id,
                letter="A",
                slot=slot,
                subject_id=SUBJECT,
                as_of=slot,
                bucket="evening",
                profile_id="builder",
                commitment_id="b-write",
                kind="proposal",
                policy_pick=None,
                policy_alternative=None,
            ),
        ),
        card.model_dump_json(),
        "{}",
        0.5,
    )
    ledger.append_step(slot, "send", "delivered", 0.5, card.card_id, {})
    code, out = _run_score(
        monkeypatch, capsys, ["--pair", str(key1), str(result), "--db", str(db)]
    )
    assert code == 0, out
    assert "unlabelled_atomic_claims=1" in out
