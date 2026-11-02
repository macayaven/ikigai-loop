"""R2 inventory tests: completeness, canary shape, scanner controls."""

from __future__ import annotations

import os
import socket
import sys
import urllib.parse
from typing import Any, get_args, get_origin

import pytest

from evals.r2 import (
    CANARIES,
    CHANNELS,
    CONTROL_PHRASE,
    CONTROL_WORD,
    DENY_WORD,
    INVENTORY,
    N_PLANTED,
    EchoRunner,
    GateRunner,
    capture_fds,
    corpus_holds,
    no_sockets,
)


def _field_kind(annotation: Any) -> str:
    """One of text, literal, or other for a schema field annotation."""
    from typing import Union

    from pydantic import BaseModel

    if annotation is None:
        return "other"
    if annotation is str:
        return "text"
    origin = get_origin(annotation)
    args = [a for a in get_args(annotation) if a is not type(None)]
    if origin is not None and "Annotated" in str(origin):
        return _field_kind(args[0]) if args else "other"
    if origin is Union or (origin is not None and "Union" in str(origin)):
        kinds = [_field_kind(a) for a in args]
        if "text" in kinds:
            return "text"
        if "literal" in kinds:
            return "literal"
        return "other"
    if str(origin) == "typing.Literal":
        if args and all(isinstance(a, str) for a in args):
            return "literal"
        return "other"
    if origin in (list, dict):
        if any(a is str or _field_kind(a) == "text" for a in args):
            return "text"
        return "other"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        sub = [_field_kind(f.annotation) for f in annotation.model_fields.values()]
        if "text" in sub:
            return "text"
        return "other"
    return "other"


def check_coverage(inventory: dict[tuple[str, str], dict[str, str]]) -> list[str]:
    """Every free-text schema field needs an inventory line."""
    from framework.schemas.core import Criterion, Fact, Profile
    from framework.schemas.events import EventData

    missing: list[str] = []
    union = get_args(EventData)[0]
    for member in get_args(union):
        etype = str(member.model_fields["type"].default)
        for name, field in member.model_fields.items():
            if name in ("type", "tier"):
                continue
            kind = _field_kind(field.annotation)
            if (
                kind == "literal"
                and inventory.get((etype, name), {}).get("disposition") != "controlled"
            ):
                missing.append(f"{etype}.{name} should be controlled")
            elif kind == "text" and (etype, name) not in inventory:
                missing.append(f"{etype}.{name} has no inventory line")
    for model, label in (
        (Fact, "Fact"),
        (Profile, "Profile"),
        (Criterion, "Criterion"),
    ):
        for name, field in model.model_fields.items():
            if name in (
                "id",
                "subject_id",
                "window",
                "tier",
                "version",
                "weights",
                "profile_id",
                "dimension",
                "hidden",
            ):
                continue
            if (
                _field_kind(field.annotation) == "text"
                and (label, name) not in inventory
            ):
                missing.append(f"{label}.{name} has no inventory line")
    for key in (("envelope", "source_id"), ("envelope", "collector_version")):
        if key not in inventory:
            missing.append(f"{key[0]}.{key[1]} has no inventory line")
    if ("manifest", "blocks") not in inventory:
        missing.append("manifest.blocks has no inventory line")
    return missing


def test_inventory_covers_every_free_text_field() -> None:
    assert check_coverage(INVENTORY) == []


def test_inventory_self_check_catches_a_dropped_row() -> None:
    trimmed = dict(INVENTORY)
    victim = ("feed.item", "title")
    del trimmed[victim]
    assert check_coverage(trimmed) != []


def test_every_canary_maps_to_an_inventory_line() -> None:
    for canary in CANARIES:
        assert (canary["type"], canary["field"]) in INVENTORY


def test_planted_count_matches() -> None:
    assert N_PLANTED == len(CANARIES) == 39


def test_canaries_hold_no_digit() -> None:
    for canary in CANARIES:
        assert not any(ch.isdigit() for ch in canary["phrase"]), canary["id"]
        assert not any(ch.isdigit() for ch in canary["word"]), canary["id"]


def test_canary_words_are_distinct_made_up_words() -> None:
    words = [c["word"] for c in CANARIES]
    assert len(set(words)) == len(words)
    for canary in CANARIES:
        assert canary["word"].replace("-", "").isalpha(), canary["id"]
        assert len(canary["word"]) >= 3, canary["id"]


# The one allowed overlap: the deny-term word sits inside the private-tier
# repo on purpose (D20) so the fact check and the outbound scan are exercised.
ALLOWED_OVERLAPS = {("wumblen", "gh-private-repo")}


def test_canary_words_never_overlap() -> None:
    """No canary word may sit inside another canary's word or phrase."""
    lowered = {
        c["id"]: (c["word"].casefold(), c["phrase"].casefold()) for c in CANARIES
    }
    bad: list[str] = []
    for outer in CANARIES:
        for inner in CANARIES:
            if outer["id"] == inner["id"]:
                continue
            word, _ = lowered[inner["id"]]
            other_word, other_phrase = lowered[outer["id"]]
            if (word, outer["id"]) in ALLOWED_OVERLAPS:
                continue
            if word in other_word or word in other_phrase:
                bad.append(f"{inner['id']} word inside {outer['id']}")
    assert bad == []


def test_canary_phrases_are_short() -> None:
    for canary in CANARIES:
        assert 1 <= len(canary["phrase"].split()) <= 4, canary["id"]


def test_pattern_fit_per_field() -> None:
    import re

    for canary in CANARIES:
        if canary["field"] == "repo":
            assert "/" in canary["phrase"], canary["id"]
            assert canary["word"] in canary["phrase"].split("/")[-1], canary["id"]
        if canary["id"] == "feed-url":
            assert canary["phrase"].startswith("https://example.invalid/"), canary["id"]
        if canary["id"] == "usage-model":
            assert "/" in canary["phrase"], canary["id"]
            assert canary["word"] in canary["phrase"], canary["id"]
        for token in canary["phrase"].split():
            if token.startswith("iki-"):
                assert token == token.lower(), canary["id"]
    tag = next(c for c in CANARIES if c["id"] == "cal-summary-tag")
    assert re.fullmatch(r"iki-[a-z]+", "iki-" + tag["word"]) is not None
    assert any(c["phrase"] != c["phrase"].lower() for c in CANARIES)
    assert any(" " in c["phrase"] for c in CANARIES)


def _encoded_forms(phrase: str) -> dict[str, str]:
    first = phrase[0]
    escaped = f"\\u{ord(first):04x}{phrase[1:]}"
    return {
        "plain": phrase,
        "upper": phrase.upper(),
        "spaced": "  ".join(phrase.split(" ")),
        "percent": urllib.parse.quote(urllib.parse.quote(phrase, safe=""), safe=""),
        "unicode": escaped,
    }


def _fully_percent_encoded(word: str) -> str:
    return "".join(f"%{ord(ch):02X}" for ch in word)


def _fully_unicode_escaped(word: str) -> str:
    return "".join(f"\\u{ord(ch):04x}" for ch in word)


@pytest.mark.parametrize("channel", list(CHANNELS))
def test_scanner_finds_fully_encoded_word_per_channel(channel: str) -> None:
    """Fully encoded distinctive word is found on every channel.

    Each form below breaks the distinctive word itself, so the scan can
    only find it by decoding: every character percent-encoded, and every
    character as a ``\\u`` escape. A letters-only word percent-encodes to
    itself, which is why the older percent control could not see the
    decoding step go missing.

    There is no whitespace-only control of its own: the scanner also
    searches each canary's distinctive word alone, so extra spacing still
    leaves the word intact and the word search covers it.
    """
    canary = next(c for c in CANARIES if c["id"] == "cal-category")
    forms = {
        "percent-every-char": _fully_percent_encoded(canary["word"]),
        "unicode-every-char": _fully_unicode_escaped(canary["word"]),
    }
    for name, form in forms.items():
        corpus = f"{channel} marker {form} tail"
        assert corpus_holds(corpus, canary["phrase"], canary["word"]), (channel, name)


@pytest.mark.parametrize("channel", list(CHANNELS))
def test_scanner_finds_all_encodings_per_channel(channel: str) -> None:
    canary = next(c for c in CANARIES if c["id"] == "cal-category")
    for name, form in _encoded_forms(canary["phrase"]).items():
        corpus = f"{channel} marker {form} tail"
        assert corpus_holds(corpus, canary["phrase"], canary["word"]), (channel, name)
    word_forms = _encoded_forms(canary["word"])
    for name, form in word_forms.items():
        corpus = f"{channel} marker {form} tail"
        assert corpus_holds(corpus, canary["phrase"], canary["word"]), (channel, name)


def test_capture_fds_catches_print_and_os_write_on_both_streams() -> None:
    old_out, old_err = sys.stdout, sys.stderr
    with capture_fds() as (first, second):
        print(f"marker-print-{CONTROL_WORD}")
        os.write(1, f"marker-fd-{CONTROL_WORD}\n".encode())
        print(f"marker-err-{CONTROL_WORD}", file=sys.stderr)
        os.write(2, f"marker-fderr-{CONTROL_WORD}\n".encode())
    assert sys.stdout is old_out
    assert sys.stderr is old_err
    out = first.read().decode()
    err = second.read().decode()
    assert f"marker-print-{CONTROL_WORD}" in out
    assert f"marker-fd-{CONTROL_WORD}" in out
    assert f"marker-err-{CONTROL_WORD}" in err
    assert f"marker-fderr-{CONTROL_WORD}" in err
    assert corpus_holds(out + err, CONTROL_PHRASE, CONTROL_WORD)


def test_no_sockets_guard_raises() -> None:
    with no_sockets():
        with pytest.raises(AssertionError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).bind(("127.0.0.1", 0))


def _stream_payloads(runner: EchoRunner | GateRunner) -> list[dict[str, Any]]:
    import json
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="r2-runner-"))
    prompt_path = tmp / "prompt.txt"
    prompt_path.write_text("hello", encoding="utf-8")
    schema_path = tmp / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "string", "enum": ["b-r2-one"]},
                    "overall_state": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "fact_ids": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": ["f1"]},
                                },
                                "metric_refs": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": ["m1"]},
                                },
                            },
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    argv = [
        "muse",
        "exec",
        "--model",
        "muse-wonder-1.0",
        "--prompt-file",
        str(prompt_path),
        "--output-schema",
        str(schema_path),
    ]
    result = runner(argv, env={}, timeout_s=60.0, cwd=None)
    payloads = []
    for line in result.stdout.decode().splitlines():
        payloads.append(json.loads(line)["payload"])
    return payloads


def test_runner_stream_carries_provider_detail() -> None:
    for runner in (EchoRunner(), GateRunner()):
        lifecycles = [
            p for p in _stream_payloads(runner) if p.get("kind") == "task_lifecycle"
        ]
        assert len(lifecycles) == 1
        event = lifecycles[0]["event"]
        assert event["kind"] == "status"
        details = event["details"]
        assert details["phase"] == "stream_succeeded"
        facets = details["facets"]
        assert isinstance(facets, list) and facets
        producer = next(f for f in facets if f["kind"] == "producer")
        detail = producer["detail"]
        assert detail["kind"] == "provider"
        assert detail["provider"] == "meta"
        assert detail["model"]


def test_runner_stream_still_parses_completed() -> None:
    from framework.proposal.muse_client import _parse_stdout

    for runner in (EchoRunner(), GateRunner()):
        import json
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="r2-runner-"))
        prompt_path = tmp / "prompt.txt"
        prompt_path.write_text("hello", encoding="utf-8")
        schema_path = tmp / "schema.json"
        schema_path.write_text(json.dumps({"type": "object"}), encoding="utf-8")
        argv = [
            "muse",
            "exec",
            "--prompt-file",
            str(prompt_path),
            "--output-schema",
            str(schema_path),
        ]
        result = runner(argv, env={}, timeout_s=60.0, cwd=None)
        failure, text, *_ = _parse_stdout(result.stdout)
        assert failure is None
        assert text


def test_deny_word_is_digit_free_and_single() -> None:
    assert DENY_WORD == "wumblen"
    assert not any(ch.isdigit() for ch in DENY_WORD)
