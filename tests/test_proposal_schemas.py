"""Ticket 11: draft/fallback schemas, the hand-built response schema, parsing."""

from __future__ import annotations

import json
from typing import Any

from framework.proposal.schemas import (
    MAX_DRAFT_CHARS,
    ClaimDraft,
    FallbackProposal,
    ProposalDraft,
    UnparseableDraft,
    build_response_schema,
    parse_draft,
)


def _walk_required(schema: dict[str, Any], path: str = "$") -> list[str]:
    """Paths where an object level is not fully required."""
    problems: list[str] = []
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if set(properties) - required:
            problems.append(path)
        for name, sub in properties.items():
            problems.extend(_walk_required(sub, f"{path}.{name}"))
    definitions = schema.get("$defs", {})
    for name, sub in definitions.items():
        problems.extend(_walk_required(sub, f"{path}.$defs.{name}"))
    if schema.get("type") == "array" and "items" in schema:
        problems.extend(_walk_required(schema["items"], f"{path}[]"))
    return problems


def test_exported_models_are_all_required_recursively() -> None:
    for model in (ProposalDraft, ClaimDraft):
        schema = model.model_json_schema()
        assert _walk_required(schema) == [], model.__name__
    own = FallbackProposal.model_json_schema()
    assert set(own["properties"]) <= set(own["required"])


def test_models_are_frozen_and_forbid_extra() -> None:
    import pytest
    from pydantic import ValidationError

    claim = ClaimDraft(text="x", fact_ids=[], metric_refs=[])
    assert claim.model_dump() == {"text": "x", "fact_ids": [], "metric_refs": []}
    with pytest.raises(ValidationError):
        ClaimDraft.model_validate(
            {"text": "x", "fact_ids": [], "metric_refs": [], "zzz": 1}
        )
    with pytest.raises(ValidationError):
        ProposalDraft.model_validate(
            {
                "commitment_id": "c",
                "overall_state": [],
                "working": [],
                "not_working": [],
                "since_last": [],
                "zzz": 1,
            }
        )


def _schema_for(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "commitment_ids": ["cm-a", "cm-b"],
        "fact_ids": ["fact:one", "fact:two"],
        "snapshot_metric_ids": ["period.last.pushes"],
        "delta_metric_ids": ["period.last.pushes"],
        "has_facts": True,
        "has_metrics": True,
        "has_parent": True,
    }
    base.update(kwargs)
    return build_response_schema(**base)


def _serialised(**kwargs: Any) -> str:
    return json.dumps(_schema_for(**kwargs), sort_keys=True)


def test_never_enum_empty_or_max_items_zero_for_any_input() -> None:
    variants = [
        {},
        {"commitment_ids": ["cm-a"]},
        {"fact_ids": [], "has_facts": False},
        {"snapshot_metric_ids": [], "has_metrics": False},
        {"delta_metric_ids": [], "has_parent": False},
        {
            "fact_ids": [],
            "snapshot_metric_ids": [],
            "delta_metric_ids": [],
            "has_facts": False,
            "has_metrics": False,
            "has_parent": False,
        },
    ]
    for variant in variants:
        text = _serialised(**variant)
        assert '"enum": []' not in text, variant
        assert '"maxItems": 0' not in text, variant
        assert "enum.*[]" not in text.replace('"enum": []', ""), variant


def test_empty_id_lists_leave_the_property_out() -> None:
    schema = _schema_for(
        fact_ids=[], snapshot_metric_ids=[], has_facts=False, has_metrics=False
    )
    claim = schema["properties"]["overall_state"]["items"]
    assert "fact_ids" not in claim["properties"]
    assert "metric_refs" not in claim["properties"]
    assert set(claim["required"]) == {"text"}
    assert "since_last" in schema["properties"]
    reduced = _schema_for(
        fact_ids=[],
        snapshot_metric_ids=[],
        delta_metric_ids=[],
        has_facts=False,
        has_metrics=False,
        has_parent=False,
    )
    assert "since_last" not in reduced["properties"]


def test_schema_keywords_match_the_plan() -> None:
    schema = _schema_for()
    props = schema["properties"]
    assert props["commitment_id"]["enum"] == ["cm-a", "cm-b"]
    assert props["overall_state"]["minItems"] == 1
    assert props["overall_state"]["maxItems"] == 3
    assert props["since_last"]["minItems"] == 1
    since_claim = props["since_last"]["items"]
    assert since_claim["properties"]["metric_refs"]["minItems"] == 1
    assert since_claim["properties"]["metric_refs"]["items"]["enum"] == [
        "period.last.pushes"
    ]
    assert "title" not in json.dumps(schema)
    assert "$defs" not in schema
    text_prop = props["overall_state"]["items"]["properties"]["text"]
    assert text_prop["minLength"] == 1


def test_schema_property_names_match_the_models() -> None:
    full = _schema_for()
    assert set(full["properties"]) == set(ProposalDraft.model_fields)
    for section in ("overall_state", "working", "not_working", "since_last"):
        items = full["properties"][section]["items"]
        assert set(items["properties"]) == set(ClaimDraft.model_fields), section
    reduced = _schema_for(
        fact_ids=[],
        snapshot_metric_ids=[],
        delta_metric_ids=[],
        has_facts=False,
        has_metrics=False,
        has_parent=False,
    )
    assert set(reduced["properties"]) == set(ProposalDraft.model_fields) - {
        "since_last"
    }
    items = reduced["properties"]["overall_state"]["items"]
    assert set(items["properties"]) == {"text"}


def _good_payload() -> dict[str, Any]:
    return {
        "commitment_id": "cm-a",
        "overall_state": [{"text": "x", "fact_ids": ["fact:one"], "metric_refs": []}],
        "working": [],
        "not_working": [],
        "since_last": [
            {"text": "y", "fact_ids": [], "metric_refs": ["period.last.pushes"]}
        ],
    }


def test_parse_draft_round_trip() -> None:
    draft = parse_draft(
        json.dumps(_good_payload()),
        has_facts=True,
        has_metrics=True,
        has_parent=True,
    )
    assert isinstance(draft, ProposalDraft)
    assert draft.commitment_id == "cm-a"


def test_parse_draft_inserts_defaults_for_absent_properties() -> None:
    payload = {
        "commitment_id": "cm-a",
        "overall_state": [{"text": "x"}],
        "working": [{"text": "y"}],
        "not_working": [],
    }
    draft = parse_draft(
        json.dumps(payload), has_facts=False, has_metrics=False, has_parent=False
    )
    assert isinstance(draft, ProposalDraft)
    assert draft.overall_state[0].fact_ids == []
    assert draft.overall_state[0].metric_refs == []
    assert draft.since_last == []


def test_parse_draft_discards_since_last_without_a_parent() -> None:
    payload = _good_payload()
    draft = parse_draft(
        json.dumps(payload), has_facts=True, has_metrics=True, has_parent=False
    )
    assert isinstance(draft, ProposalDraft)
    assert draft.since_last == []


def test_letterless_claim_text_is_unparseable() -> None:
    for text in ("", "   ", "...", "123 456", "-- .. --"):
        payload = {
            "commitment_id": "cm-a",
            "overall_state": [
                {"text": text, "fact_ids": ["fact:one"], "metric_refs": []}
            ],
            "working": [],
            "not_working": [],
            "since_last": [],
        }
        result = parse_draft(
            json.dumps(payload), has_facts=True, has_metrics=True, has_parent=True
        )
        assert isinstance(result, UnparseableDraft), repr(text)


def test_parse_draft_never_raises_on_model_output() -> None:
    bad_inputs = [
        "",
        "not json",
        "null",
        "[]",
        "{}",
        '{"commitment_id": ""}',
        '{"commitment_id": "cm-a", "overall_state": "nope"}',
        '{"commitment_id": "cm-a", "overall_state": [{"text": ""}]}',
        "\x00\x01",
        "[BINARY_PLACEHOLDER_1]",
    ]
    for raw in bad_inputs:
        result = parse_draft(raw, has_facts=True, has_metrics=True, has_parent=True)
        assert isinstance(result, UnparseableDraft), raw


def test_parse_draft_size_cap_boundary() -> None:
    base = json.dumps(_good_payload())
    assert len(base) < MAX_DRAFT_CHARS
    exact = base + " " * (MAX_DRAFT_CHARS - len(base))
    assert len(exact) == MAX_DRAFT_CHARS
    assert isinstance(
        parse_draft(exact, has_facts=True, has_metrics=True, has_parent=True),
        ProposalDraft,
    )
    over = base + " " * (MAX_DRAFT_CHARS + 1 - len(base))
    assert len(over) == MAX_DRAFT_CHARS + 1
    assert isinstance(
        parse_draft(over, has_facts=True, has_metrics=True, has_parent=True),
        UnparseableDraft,
    )


def test_largest_allowed_draft_stays_under_cap() -> None:
    # A draft far larger than any real one: 4 sections of 3 claims, 320-char text,
    # 20 fact ids and 20 metric refs of 60 characters each, json.dumps.
    text = "x" * 320
    assert len(text) == 320
    fact_ids = [f"f{i:02d}" + "a" * 57 for i in range(20)]
    metric_refs = [f"m{i:02d}" + "b" * 57 for i in range(20)]
    assert all(len(i) == 60 for i in fact_ids + metric_refs)
    claim = {"text": text, "fact_ids": fact_ids, "metric_refs": metric_refs}
    payload = {
        "commitment_id": "cm-a",
        "overall_state": [dict(claim) for _ in range(3)],
        "working": [dict(claim) for _ in range(3)],
        "not_working": [dict(claim) for _ in range(3)],
        "since_last": [dict(claim) for _ in range(3)],
    }
    assert len(json.dumps(payload)) < MAX_DRAFT_CHARS
