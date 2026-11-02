"""Ticket 16b: the plain prompt and schema (D6, D7)."""

from __future__ import annotations

import json
from pathlib import Path

from evals.r1b_prompts import build_plain_prompt, build_plain_response_schema

REPO_ROOT = Path(__file__).resolve().parents[1]


def _f01() -> dict[str, object]:
    import json as _json

    raw = _json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    return raw[0]  # type: ignore[no-any-return]


def _materials(index: int) -> tuple[str, dict[str, object], bool]:
    from datetime import datetime

    from framework.briefing.labels import metric_label_binding
    from framework.glimmer.prompt import strip_feed_title
    from framework.proposal.prompt import (
        _dump,
        _metric_sort_key,
        _ordered_labels,
        compute_deltas,
        display_value,
        offered_metrics,
    )

    raw = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json").read_text(
            encoding="utf-8"
        )
    )[index]
    metrics = {k: float(v) for k, v in raw["metrics"].items()}
    offered = offered_metrics(metrics)
    parent = raw.get("parent_snapshot")
    deltas = (
        compute_deltas(offered, {k: float(v) for k, v in parent.items()})
        if parent
        else ()
    )
    ordered = sorted(offered, key=_metric_sort_key)
    metric_lines = []
    for metric_id in ordered:
        binding = metric_label_binding(metric_id)
        assert binding is not None
        metric_lines.append(
            _dump(
                {
                    "id": metric_id,
                    "value": display_value(offered[metric_id]),
                    "labels": _ordered_labels(binding.labels),
                    "period": binding.period,
                }
            )
        )
    delta_lines = [
        _dump({"id": delta.metric_id, "value": delta.display}) for delta in deltas
    ]
    fact_lines = [
        _dump({"id": fact["id"], "statement": strip_feed_title(fact["statement"])})
        for fact in raw["facts"]
    ]
    commitment_lines = [
        _dump(
            {
                "id": item["id"],
                "title": strip_feed_title(item["title"]),
                "kind": item["kind"],
                "dimension": item["dimension"],
            }
        )
        for item in raw["commitments"]
    ]
    hour = raw["hour"]
    _ = datetime  # slot parsing lives in the loader; the prompt takes strings here
    return (
        "\n".join(metric_lines),
        {
            "profile_name": str(raw["profile"]).capitalize(),
            "hour_start": hour["start"],
            "hour_end": hour["end"],
            "metric_lines": "\n".join(metric_lines),
            "delta_lines": "\n".join(delta_lines),
            "fact_lines": "\n".join(fact_lines),
            "commitment_lines": "\n".join(commitment_lines),
            "has_parent": bool(deltas),
        },
        bool(deltas),
    )


def _expected_prompt(ctx: dict[str, object], has_parent: bool) -> str:
    since_last_field = ", since_last" if has_parent else ""
    since_last_sentence = (
        " since_last holds claims about what changed since the last card."
        if has_parent
        else ""
    )
    delta_block = (
        "DELTAS SINCE THE LAST CARD (one JSON object per line):\n"
        "<<<DELTA_DATA\n" + str(ctx["delta_lines"]) + "\nDELTA_DATA>>>\n"
        if has_parent
        else ""
    )
    return (
        "You are writing a short briefing card for one goal. Pick the commitment below "
        "that most deserves the hour shown, and write a few short claims about what the "
        "data shows for this goal. Use only the data below.\n"
        "\n"
        "Return JSON only, with this shape: an object with commitment_id (the id of the "
        "commitment you pick), overall_state, working and not_working"
        + since_last_field
        + ". Each of those is a list of claims. Each claim is an object with text (one "
        "sentence in English), fact_ids (a list of fact ids from the facts below that "
        "support the claim) and metric_refs (a list of metric ids from the metrics below "
        "that support the claim)." + since_last_sentence + "\n"
        "\n"
        "PROFILE: " + str(ctx["profile_name"]) + "\n"
        "HOUR: " + str(ctx["hour_start"]) + " to " + str(ctx["hour_end"]) + "\n"
        "METRICS (one JSON object per line):\n"
        "<<<METRIC_DATA\n"
        + str(ctx["metric_lines"])
        + "\nMETRIC_DATA>>>\n"
        + delta_block
        + "FACTS (one JSON object per line):\n"
        "<<<FACT_DATA\n" + str(ctx["fact_lines"]) + "\nFACT_DATA>>>\n"
        "\n"
        "COMMITMENTS (one JSON object per line; choose one id):\n"
        "<<<COMMITMENT_DATA\n" + str(ctx["commitment_lines"]) + "\nCOMMITMENT_DATA>>>"
    )


def _prompt_inputs(index: int) -> dict[str, object]:
    from evals.r1b import build_case_hour, load_cases

    case = load_cases(REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json")[
        index
    ]
    from evals.r1b import offered_deltas_for

    return {
        "profile_name": case.profile.capitalize(),
        "hour": build_case_hour(case),
        "facts": list(case.facts),
        "metrics": dict(case.metrics),
        "deltas": offered_deltas_for(case),
        "commitments": list(case.commitments),
    }


def test_plain_prompt_no_parent_snapshot() -> None:
    _lines, ctx, has_parent = _materials(0)
    assert not has_parent
    assert build_plain_prompt(**_prompt_inputs(0)) == _expected_prompt(ctx, False)  # type: ignore[arg-type]


def test_plain_prompt_parent_snapshot() -> None:
    _lines, ctx, has_parent = _materials(1)
    assert has_parent
    assert build_plain_prompt(**_prompt_inputs(1)) == _expected_prompt(ctx, True)  # type: ignore[arg-type]


def test_plain_prompt_carries_the_first_instinct_sentence() -> None:
    assert "Use only the data below." in build_plain_prompt(**_prompt_inputs(0))  # type: ignore[arg-type]


def test_plain_schema_no_parent_snapshot() -> None:
    assert build_plain_response_schema(has_parent=False) == {
        "type": "object",
        "properties": {
            "commitment_id": {"type": "string"},
            "overall_state": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "fact_ids": {"type": "array", "items": {"type": "string"}},
                        "metric_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "fact_ids", "metric_refs"],
                    "additionalProperties": False,
                },
            },
            "working": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "fact_ids": {"type": "array", "items": {"type": "string"}},
                        "metric_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "fact_ids", "metric_refs"],
                    "additionalProperties": False,
                },
            },
            "not_working": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "fact_ids": {"type": "array", "items": {"type": "string"}},
                        "metric_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "fact_ids", "metric_refs"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["commitment_id", "overall_state", "working", "not_working"],
        "additionalProperties": False,
    }


def test_plain_schema_parent_snapshot_adds_since_last() -> None:
    schema = build_plain_response_schema(has_parent=True)
    assert schema["required"] == [
        "commitment_id",
        "overall_state",
        "working",
        "not_working",
        "since_last",
    ]
    assert set(schema["properties"]) == {
        "commitment_id",
        "overall_state",
        "working",
        "not_working",
        "since_last",
    }
    assert schema["properties"]["since_last"]["items"]["required"] == [
        "text",
        "fact_ids",
        "metric_refs",
    ]


def test_plain_schema_has_no_enum() -> None:
    assert "enum" not in json.dumps(build_plain_response_schema(has_parent=False))
    assert "enum" not in json.dumps(build_plain_response_schema(has_parent=True))


def test_plain_and_product_carry_identical_data_lines() -> None:
    from evals.r1b import build_case_hour, load_cases, offered_deltas_for
    from framework.proposal.prompt import build_prompt

    cases = load_cases(REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json")
    for case in cases:
        hour = build_case_hour(case)
        deltas = offered_deltas_for(case)
        product = build_prompt(
            profile_id=case.profile,
            profile_name=case.profile.capitalize(),
            facts=list(case.facts),
            metrics=dict(case.metrics),
            deltas=deltas,
            commitments=list(case.commitments),
            hour=hour,
            policy="",
        )
        plain = build_plain_prompt(
            profile_name=case.profile.capitalize(),
            hour=hour,
            facts=list(case.facts),
            metrics=dict(case.metrics),
            deltas=deltas,
            commitments=list(case.commitments),
        )

        def _block(prompt: str, start: str, end: str) -> list[str]:
            lines = prompt.splitlines()
            inside = lines[lines.index(start) + 1 : lines.index(end)]
            return inside

        assert _block(plain, "<<<METRIC_DATA", "METRIC_DATA>>>") == _block(
            product, "<<<METRIC_DATA", "METRIC_DATA>>>"
        ), case.id
        assert _block(plain, "<<<FACT_DATA", "FACT_DATA>>>") == _block(
            product, "<<<FACT_DATA", "FACT_DATA>>>"
        ), case.id
        assert _block(plain, "<<<COMMITMENT_DATA", "COMMITMENT_DATA>>>") == _block(
            product, "<<<COMMITMENT_DATA", "COMMITMENT_DATA>>>"
        ), case.id
        if deltas:
            assert _block(plain, "<<<DELTA_DATA", "DELTA_DATA>>>") == _block(
                product, "<<<DELTA_DATA", "DELTA_DATA>>>"
            ), case.id


def test_plain_module_builds_no_product_copy() -> None:
    import evals.r1b_prompts as prompts

    source = (REPO_ROOT / "evals" / "r1b_prompts.py").read_text(encoding="utf-8")
    assert "overall_state says" not in source
    assert callable(prompts.build_plain_prompt)
    assert callable(prompts.build_plain_response_schema)
