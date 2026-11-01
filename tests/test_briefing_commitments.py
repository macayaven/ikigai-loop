"""Ticket 10: commitment schema, loader, and context tests (AT1)."""

from __future__ import annotations

import json
import logging
from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from framework.briefing.commitments import LoadedCommitments, load_commitments
from framework.briefing.context import GateContext, MetricSnapshot, ProfileLimits
from framework.briefing.schemas import COMMITMENT_TAG_PATTERN, Commitment
from framework.collectors.calendar_ics import TAG_PATTERN

EXAMPLE_FILE = (
    Path(__file__).resolve().parents[1] / "profiles" / "commitments.example.json"
)

_VALID_ITEM = {
    "id": "cm-builder-parser",
    "profile_id": "builder",
    "title": "Build the synthetic parser sketch",
    "kind": "build",
    "dimension": "good_at",
    "evidence": "github_push",
}


def _write_items(tmp_path: Path, items: object) -> str:
    path = tmp_path / "commitments.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return str(path)


def _load(
    tmp_path: Path,
    items: object,
    **kwargs: object,
) -> LoadedCommitments:
    path = _write_items(tmp_path, items)
    return load_commitments({"IKIGAI_COMMITMENTS_FILE": path}, **kwargs)  # type: ignore[arg-type]


def test_commitment_round_trip() -> None:
    commitment = Commitment.model_validate(_VALID_ITEM)
    assert Commitment.model_validate(commitment.model_dump(mode="json")) == commitment


def test_commitment_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate({**_VALID_ITEM, "proof": "nope"})


def test_commitment_unknown_evidence_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate({**_VALID_ITEM, "evidence": "teleport"})


def test_commitment_calendar_tag_without_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate({**_VALID_ITEM, "evidence": "calendar_tag"})


def test_commitment_tag_on_non_calendar_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate({**_VALID_ITEM, "tag": "iki-review"})


def test_commitment_blank_title_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate({**_VALID_ITEM, "title": "   "})


def test_commitment_bad_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate(
            {**_VALID_ITEM, "evidence": "calendar_tag", "tag": "bad tag!"}
        )


def test_commitment_tag_pattern_matches_collector() -> None:
    assert COMMITMENT_TAG_PATTERN == TAG_PATTERN.pattern


def test_commitment_unknown_kind_rejected_including_exercise() -> None:
    for kind in ("teleport", "exercise"):
        with pytest.raises(ValidationError):
            Commitment.model_validate({**_VALID_ITEM, "kind": kind})


def test_loader_unset_var(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    loaded = load_commitments({})
    assert loaded.commitments == ()
    assert loaded.available is False
    assert loaded.reason == "unset"
    assert capsys.readouterr() == ("", "")
    assert caplog.text == ""


def test_loader_empty_var_is_unset() -> None:
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": ""})
    assert loaded.available is False
    assert loaded.reason == "unset"


def test_loader_missing_file_is_unreadable(tmp_path: Path) -> None:
    loaded = load_commitments(
        {"IKIGAI_COMMITMENTS_FILE": str(tmp_path / "absent.json")}
    )
    assert loaded.commitments == ()
    assert loaded.available is False
    assert loaded.reason == "unreadable"


def test_loader_directory_path_is_unreadable(tmp_path: Path) -> None:
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": str(tmp_path)})
    assert loaded.available is False
    assert loaded.reason == "unreadable"


def test_loader_not_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "commitments.json"
    path.write_bytes(b"\xff\xfe\x00nope\n")
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": str(path)})
    assert loaded.available is False
    assert loaded.reason == "not_utf8"


def test_loader_bad_json_is_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "commitments.json"
    path.write_text("{nope", encoding="utf-8")
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": str(path)})
    assert loaded.available is False
    assert loaded.reason == "invalid_json"


def test_loader_top_level_object_is_not_a_list(tmp_path: Path) -> None:
    loaded = _load(tmp_path, {"id": "cm-x"})
    assert loaded.available is False
    assert loaded.reason == "not_a_list"


def test_loader_empty_list_is_empty(tmp_path: Path) -> None:
    loaded = _load(tmp_path, [])
    assert loaded.available is False
    assert loaded.reason == "empty"


def test_loader_invalid_item(tmp_path: Path) -> None:
    loaded = _load(tmp_path, [{**_VALID_ITEM, "kind": "teleport"}])
    assert loaded.available is False
    assert loaded.reason == "invalid_item"


def test_loader_duplicate_id(tmp_path: Path) -> None:
    other = {**_VALID_ITEM, "title": "Write notes on the synthetic trial"}
    loaded = _load(tmp_path, [_VALID_ITEM, other])
    assert loaded.available is False
    assert loaded.reason == "duplicate_id"


def test_loader_advice_title_rejected(tmp_path: Path) -> None:
    item = {**_VALID_ITEM, "title": "You should log the synthetic result"}
    loaded = _load(tmp_path, [item])
    assert loaded.available is False
    assert loaded.reason == "title_failed"


def test_loader_repo_naming_title_rejected(tmp_path: Path) -> None:
    item = {**_VALID_ITEM, "title": "Fix ikigai-loop docs tonight"}
    loaded = _load(tmp_path, [item])
    assert loaded.available is False
    assert loaded.reason == "title_failed"


def test_loader_private_term_title_rejected_only_with_terms(tmp_path: Path) -> None:
    item = {**_VALID_ITEM, "title": "Tend the synthetic garden plot"}
    assert _load(tmp_path, [item]).available is True
    loaded = _load(tmp_path, [item], private_terms=("synthetic garden",))
    assert loaded.available is False
    assert loaded.reason == "title_failed"


def test_loader_blank_title_is_invalid_item(tmp_path: Path) -> None:
    loaded = _load(tmp_path, [{**_VALID_ITEM, "title": "   "}])
    assert loaded.available is False
    assert loaded.reason == "invalid_item"


def test_loader_bad_tag_is_invalid_item(tmp_path: Path) -> None:
    item = {
        **_VALID_ITEM,
        "evidence": "calendar_tag",
        "tag": "bad tag!",
    }
    loaded = _load(tmp_path, [item])
    assert loaded.available is False
    assert loaded.reason == "invalid_item"


def test_loader_deeply_nested_json_is_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "commitments.json"
    path.write_text("[" * 100000, encoding="utf-8")
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": str(path)})
    assert loaded.commitments == ()
    assert loaded.available is False
    assert loaded.reason == "invalid_json"


def test_loader_failure_hides_path_and_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_items(tmp_path, [{"secret": "synthetic-content-marker"}])
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": path})
    assert loaded.available is False
    out, err = capsys.readouterr()
    assert str(path) not in out + err
    assert "synthetic-content-marker" not in out + err
    assert caplog.text == ""


def test_loader_example_file_loads_all_14() -> None:
    loaded = load_commitments({"IKIGAI_COMMITMENTS_FILE": str(EXAMPLE_FILE)})
    assert loaded.available is True
    assert loaded.reason is None
    assert len(loaded.commitments) == 14
    by_profile: dict[str, int] = {}
    for commitment in loaded.commitments:
        by_profile[commitment.profile_id] = by_profile.get(commitment.profile_id, 0) + 1
    assert by_profile == {"builder": 9, "disconnect": 5}


def test_loader_advice_copy_of_example_file_fails(tmp_path: Path) -> None:
    items = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    items[0]["title"] = "You should log the synthetic result"
    loaded = _load(tmp_path, items)
    assert loaded.commitments == ()
    assert loaded.available is False
    assert loaded.reason == "title_failed"


def test_gate_context_commitments_fail_closed_by_default() -> None:
    context = GateContext(
        facts={},
        metrics=MetricSnapshot(values={}),
        limits=ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start=time(13, 0),
            allowed_end=time(23, 30),
        ),
    )
    assert context.commitments == ()
    assert context.commitments_available is False


def test_gate_context_duplicate_commitment_id_rejected() -> None:
    commitment = Commitment.model_validate(_VALID_ITEM)
    with pytest.raises(ValidationError):
        GateContext(
            facts={},
            metrics=MetricSnapshot(values={}),
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
            ),
            commitments=(commitment, commitment),
            commitments_available=True,
        )


def test_gate_context_commitments_round_trip() -> None:
    from evals.briefing_cases import base_case

    context = base_case("builder").context
    assert context.commitments_available is True
    assert len(context.commitments) == 14
    assert GateContext.model_validate(context.model_dump(mode="json")) == context


def test_loader_reads_env_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_items(tmp_path, [_VALID_ITEM])
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", path)
    loaded = load_commitments()
    assert loaded.available is True
    assert loaded.reason is None
    assert len(loaded.commitments) == 1
    monkeypatch.delenv("IKIGAI_COMMITMENTS_FILE")
    reloaded = load_commitments()
    assert reloaded.commitments == ()
    assert reloaded.available is False
    assert reloaded.reason == "unset"


def test_loader_raw_literal_title_rejected(tmp_path: Path) -> None:
    literal = "Synthetic Raw Title Zqx"
    item = dict(_VALID_ITEM, title=f"Build the synthetic sketch {literal}")
    path = _write_items(tmp_path, [item])
    rejected = load_commitments(
        {"IKIGAI_COMMITMENTS_FILE": path},
        forbidden_raw_literals=(literal,),
    )
    assert rejected.commitments == ()
    assert rejected.available is False
    assert rejected.reason == "title_failed"
    assert load_commitments({"IKIGAI_COMMITMENTS_FILE": path}).available is True


@pytest.mark.parametrize(
    ("arm", "reason"),
    [
        ("unset", "unset"),
        ("missing", "unreadable"),
        ("directory", "unreadable"),
        ("nul", "unreadable"),
        ("not_utf8", "not_utf8"),
        ("bad_json", "invalid_json"),
        ("top_level_object", "not_a_list"),
        ("empty", "empty"),
        ("invalid_item", "invalid_item"),
        ("duplicate_id", "duplicate_id"),
        ("failing_title", "title_failed"),
    ],
)
def test_loader_every_failure_is_silent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    arm: str,
    reason: str,
) -> None:
    marker = f"SILENT-{arm}-7zq"
    environ: dict[str, str] = {}
    if arm == "unset":
        path = tmp_path / f"silent-unset-{marker}.json"
        path.write_text(json.dumps(marker), encoding="utf-8")
        environ = {"IKIGAI_COMMITMENTS_FILE": ""}
    elif arm == "missing":
        environ = {
            "IKIGAI_COMMITMENTS_FILE": str(tmp_path / f"silent-missing-{marker}.json")
        }
    elif arm == "directory":
        path = tmp_path / f"silent-directory-{marker}"
        path.mkdir()
        environ = {"IKIGAI_COMMITMENTS_FILE": str(path)}
    elif arm == "nul":
        environ = {
            "IKIGAI_COMMITMENTS_FILE": str(tmp_path / f"silent-nul-{marker}.json")
            + "\0"
        }
    elif arm == "not_utf8":
        path = tmp_path / f"silent-not-utf8-{marker}.json"
        path.write_bytes(marker.encode("utf-8") + b"\xff\xfe")
        environ = {"IKIGAI_COMMITMENTS_FILE": str(path)}
    elif arm == "bad_json":
        path = tmp_path / f"silent-bad-json-{marker}.json"
        path.write_text("{not json " + marker, encoding="utf-8")
        environ = {"IKIGAI_COMMITMENTS_FILE": str(path)}
    elif arm == "top_level_object":
        path = _write_items(tmp_path, {"key": marker})
        environ = {"IKIGAI_COMMITMENTS_FILE": path}
    elif arm == "empty":
        path = _write_items(tmp_path, [])
        environ = {"IKIGAI_COMMITMENTS_FILE": path}
    elif arm == "invalid_item":
        path = _write_items(tmp_path, [{"id": 1, marker: 1}])
        environ = {"IKIGAI_COMMITMENTS_FILE": path}
    elif arm == "duplicate_id":
        item = dict(_VALID_ITEM, title=f"Build the synthetic sketch {marker}")
        path = _write_items(tmp_path, [item, item])
        environ = {"IKIGAI_COMMITMENTS_FILE": path}
    elif arm == "failing_title":
        item = dict(_VALID_ITEM, title=f"You should log {marker} here")
        path = _write_items(tmp_path, [item])
        environ = {"IKIGAI_COMMITMENTS_FILE": path}
    else:
        raise AssertionError(arm)
    with caplog.at_level(logging.DEBUG):
        result = load_commitments(environ)
    assert result.commitments == ()
    assert result.available is False
    assert result.reason == reason, arm
    out, err = capsys.readouterr()
    assert marker not in out + err, arm
    assert marker not in caplog.text, arm
    assert marker not in repr(result), arm


@pytest.mark.parametrize(
    "tag",
    ["iki-sister-call", "iki-Deep", "iki-deep\n", "deep", "iki-deep extra"],
)
def test_commitment_tag_must_fully_match(tag: str) -> None:
    with pytest.raises(ValidationError):
        Commitment.model_validate(
            {**_VALID_ITEM, "evidence": "calendar_tag", "tag": tag}
        )
    assert (
        Commitment.model_validate(
            {**_VALID_ITEM, "evidence": "calendar_tag", "tag": "iki-deep"}
        ).tag
        == "iki-deep"
    )


def test_title_with_digits_and_direction_loads_and_passes(
    tmp_path: Path,
) -> None:
    # Action text is never number checked or direction checked, so a title
    # carrying digits and a direction word still loads and still passes.
    item = {
        "id": "cm-synthetic-clock",
        "profile_id": "builder",
        "title": "Stop the synthetic screens down by 00:00",
        "kind": "plan",
        "dimension": "love",
        "evidence": "tap",
    }
    loaded = _load(tmp_path, [item])
    assert loaded.available is True

    from evals.briefing_cases import base_case

    case = base_case("builder")
    briefing = dict(case.briefing)
    sections = [dict(s) for s in briefing["sections"]]
    briefing["sections"] = sections
    actions_section = next(s for s in sections if s["type"] == "actions")
    actions_section["actions"] = [dict(a) for a in actions_section["actions"][:1]]
    action = actions_section["actions"][0]
    action["commitment_id"] = item["id"]
    action["kind"] = item["kind"]
    action["text"] = item["title"]
    action["dimension"] = item["dimension"]
    context = case.context.model_copy(
        update={
            "commitments": loaded.commitments,
            "commitments_available": True,
        }
    )
    from framework.briefing.gate import evaluate_briefing

    assert evaluate_briefing(briefing, context).passed is True
