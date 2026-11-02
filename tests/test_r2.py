"""R2 end-to-end tests: whole slots, arms, controls, staleness."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from evals import r2
from evals.r2 import (
    CANARIES,
    CHANNELS,
    CONTROL_PHRASE,
    CONTROL_WORD,
    N_PLANTED,
)

REPO = Path(__file__).resolve().parent.parent
REQUIRED_CONTROL_CHANNELS = [
    "wonder_prompt",
    "meta_body",
    "telegram",
    "card_stored",
    "trace",
]
OUTBOUND_CHANNELS = [c for c in CHANNELS if c != "meta_body"]


def _canary(cid: str) -> dict:
    return next(c for c in CANARIES if c["id"] == cid)


def _run_once(root: Path) -> dict:
    return r2.run_r2(root)


def test_r2_receipt_end_to_end(tmp_path: Path) -> None:
    outcome = _run_once(tmp_path / "r2")
    report = outcome["report"]
    main = outcome["main"]

    assert report["planted"] == N_PLANTED == 39
    assert set(report["channels_scanned"]) == set(CHANNELS)
    assert {c["id"] for c in CANARIES} == {
        row["canary_id"] for row in report["by_field"]
    }
    by_id = {row["canary_id"]: row for row in report["by_field"]}

    for arm in ("copying", "targeted", "meta"):
        escaped = {
            row["canary_id"]
            for row in report["by_field"]
            if any(ch != "stored_outbound" for ch in row["found_in"][arm])
        }
        assert report["arms"][arm]["escaped"] == len(escaped), arm
        assert report["arms"][arm]["headline"] == (
            f"{len(escaped)} of {N_PLANTED} tested canaries escaped"
        ), arm
        by_design = sum(1 for cid in escaped if by_id[cid]["by_design"] is not None)
        assert report["arms"][arm]["by_design_escaped"] == by_design, arm
        assert report["arms"][arm]["finding_escaped"] == len(escaped) - by_design, arm
    worse = max(
        ("copying", "targeted", "meta"),
        key=lambda name: (
            report["arms"][name]["escaped"],
            report["arms"][name]["finding_escaped"],
        ),
    )
    assert report["headline_arm"] == worse
    assert report["headline"] == report["arms"][worse]["headline"]
    assert report["prediction"] == "0 escape"
    assert report["prediction_held"] == (report["arms"][worse]["escaped"] == 0)

    for channel in REQUIRED_CONTROL_CHANNELS:
        assert r2.corpus_holds(
            main["corpora"][channel], CONTROL_PHRASE, CONTROL_WORD
        ), channel

    worlds = {"main": main, **outcome["targeted"]}
    for name, world in worlds.items():
        for channel in CHANNELS:
            assert not r2.corpus_holds(
                world["corpora"][channel], "Flurble iki-care trundle", "iki-care"
            ), (name, channel)
            assert "iki-care" not in r2._normalise(world["corpora"][channel]), (
                name,
                channel,
            )
    assert "iki-care" in r2._normalise(r2._events_text(Path(main["db"])))

    deny_world = outcome["targeted"]["deny-term"]
    assert deny_world["runner_calls"] == 0
    conn = sqlite3.connect(f"file:{deny_world['db']}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT kind, reason_codes FROM proposal_results"
        ).fetchall()
    finally:
        conn.close()
    assert rows, "deny-term world stored no proposal rows"
    assert all(kind == "noop" for kind, _ in rows)
    assert all("NOOP_OUTBOUND_BLOCKED" in codes for _, codes in rows)

    leak_world = outcome["targeted"]["gh-private-repo"]
    assert "FACT_PRIVATE_TEXT_LEAK" in {d["code"] for d in leak_world["dropped"]}
    assert not r2.corpus_holds(
        leak_world["corpora"]["wonder_prompt"],
        "quarnkeep/wumblenpriv",
        "wumblenpriv",
    )

    proposal_sides = 0
    cardless = []
    for cid, world in outcome["targeted"].items():
        if not world["corpora"]["card_stored"]:
            cardless.append(cid)
            continue
        card = json.loads(world["corpora"]["card_stored"])
        sides = card.get("proposals", [])
        if any(side.get("kind") == "proposal" for side in sides):
            assert card.get("statements"), cid
            proposal_sides += 1
    assert cardless == ["deny-term"]
    assert proposal_sides >= 1

    usage = _canary("usage-model")
    for name, world in worlds.items():
        for channel in CHANNELS:
            assert not r2.corpus_holds(
                world["corpora"][channel], usage["phrase"], usage["word"]
            ), (name, channel)
        assert not r2.corpus_holds(
            r2._stored_local_text(Path(world["db"])), usage["phrase"], usage["word"]
        ), name

    for canary in CANARIES:
        assert not r2.corpus_holds(
            main["corpora"]["stdout_stderr"], canary["phrase"], canary["word"]
        ), canary["id"]

    blob = json.dumps(report)
    for canary in CANARIES:
        assert canary["phrase"] not in blob, canary["id"]
        assert canary["word"] not in blob, canary["id"]

    assert main["run_slot_exit"] == 0
    assert report["run_slot_exit"] == 0
    assert report["gaps"] == [
        "chart pixels (no OCR)",
        "voice-note audio to Meta for transcription",
        "voice reply texts to Telegram (they echo the transcript)",
        "corrected cards from the voice worker",
        "the Nov 3 11:30 extra slot's limits/profile branch (same sends, narrower allowed hours)",
        "anything not planted",
    ]


def test_r2_title_term_refuses_with_no_outbound_records(tmp_path: Path) -> None:
    local = r2._CopyingLocal()
    local.world_dropped = []
    local.world_facts = []
    world = r2.run_world(
        tmp_path / "refuse",
        local=local,
        runner=r2.EchoRunner(),
        labels=[
            f"{CONTROL_PHRASE} wumblen pages",
            f"{CONTROL_PHRASE} wumblen notes",
            f"{CONTROL_PHRASE} wumblen stroll",
            f"{CONTROL_PHRASE} wumblen tea",
        ],
    )
    assert world["run_slot_exit"] == 1
    assert world["corpora"]["card_id"] == ""
    assert world["corpora"]["telegram"] == ""
    assert "COMMITMENTS_UNAVAILABLE" in world["corpora"]["stdout_stderr"]


def test_targeted_local_copies_only_what_it_saw() -> None:
    import json

    from evals.r2 import _TargetedLocal

    phrase, word = "Flimbrel morning drift", "flimbrel"

    personal_word_only = 'fact line holding flimbrel with alias "e1"'
    personal_neither = 'fact line holding nothing relevant with alias "e1"'
    feed_word_only = 'FEED_DATA feed line holding flimbrel with alias "e1"'
    feed_neither = 'FEED_DATA feed line holding nothing relevant with alias "e1"'

    local = _TargetedLocal(phrase, word)
    body = json.loads(local.complete(personal_word_only).text)
    assert body["facts"][0]["statement"] == word
    body = json.loads(local.complete(feed_word_only).text)
    assert body["topics"][0]["topic"] == word

    local = _TargetedLocal(phrase, word)
    body = json.loads(local.complete(personal_neither).text)
    assert body["facts"] == []
    body = json.loads(local.complete(feed_neither).text)
    assert body["topics"] == []

    local = _TargetedLocal(phrase, word)
    prompt = f'fact line holding "{phrase}" with alias "e1"'
    body = json.loads(local.complete(prompt).text)
    assert body["facts"][0]["statement"] == phrase


def test_r2_stored_only_is_stopped_and_guard_covers_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    import framework.cycle.trace as trace_module

    seen: dict[str, bool] = {}
    real_meta = r2.run_meta_arm
    real_trace = trace_module.trace

    def _denied() -> bool:
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9))
        except AssertionError:
            return True
        except OSError:
            return False
        return False

    def meta_probe(db):  # type: ignore[no-untyped-def]
        seen["meta"] = _denied()
        return real_meta(db)

    def trace_probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        seen["trace"] = _denied()
        return real_trace(*args, **kwargs)

    monkeypatch.setattr(r2, "run_meta_arm", meta_probe)
    monkeypatch.setattr(trace_module, "trace", trace_probe)

    outcome = _run_once(tmp_path / "r2-guard")
    report = outcome["report"]
    by_id = {row["canary_id"]: row for row in report["by_field"]}

    assert seen.get("meta") is True
    assert seen.get("trace") is True

    deny = by_id["deny-term"]
    assert deny["found_in"]["targeted"] == ["stored_outbound"]
    assert deny["found_in"]["copying"] == []
    assert deny["found_in"]["meta"] == []
    assert deny["stage_reached"] == "stored-then-stopped"
    targeted_ids = [
        row["canary_id"]
        for row in report["by_field"]
        if row["found_in"]["targeted"]
        and any(ch != "stored_outbound" for ch in row["found_in"]["targeted"])
    ]
    assert "deny-term" not in targeted_ids
    assert report["arms"]["targeted"]["escaped"] == len(targeted_ids)

    by_design = next(
        row
        for row in report["by_field"]
        if row["by_design"] is not None
        and any(
            ch != "stored_outbound"
            for channels in row["found_in"].values()
            for ch in channels
        )
    )
    assert by_design["stage_reached"] == "escaped"


def test_r2_sentinel_env_is_never_read(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    (sentinel / "deny-terms.txt").write_text(CONTROL_WORD + "\n", encoding="utf-8")
    old = os.environ.get("HIDDEN_CRITERIA_DIR")
    os.environ["HIDDEN_CRITERIA_DIR"] = str(sentinel)
    try:
        outcome = _run_once(tmp_path / "r2")
    finally:
        if old is None:
            os.environ.pop("HIDDEN_CRITERIA_DIR", None)
        else:
            os.environ["HIDDEN_CRITERIA_DIR"] = old
    committed = json.loads((REPO / "evals" / "results" / "r2.json").read_text())
    assert outcome["report"] == committed


def test_r2_outputs_match_committed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals" / "results").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    assert r2.main() == 0
    assert (tmp_path / "evals" / "results" / "r2.json").read_bytes() == (
        REPO / "evals" / "results" / "r2.json"
    ).read_bytes()
    assert (tmp_path / "docs" / "r2.md").read_bytes() == (
        REPO / "docs" / "r2.md"
    ).read_bytes()
