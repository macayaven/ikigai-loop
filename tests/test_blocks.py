"""Ticket 6: registry and config tests (AT1–AT4, AT6)."""

import pytest
from pydantic import ValidationError

from framework.blocks import (
    BLOCKS,
    ContextLink,
    RenderContext,
    get_definition,
    render_block,
    validate_block,
    validate_manifest,
)
from framework.schemas.manifest import BlockConfig, Manifest


def _empty_context() -> RenderContext:
    return RenderContext.model_validate({})


def test_sample_configs_validate_and_render() -> None:
    assert len(BLOCKS) == 6
    context = _empty_context()
    for block_type, definition in BLOCKS.items():
        block = BlockConfig.model_validate(
            {
                "type": block_type,
                "dimension": definition.sample_dimension,
                "config": definition.sample_config,
                "rationale": "synthetic sample",
            }
        )
        parsed = validate_block("sample#x", block)
        assert isinstance(parsed, definition.config_model)
        fragment = render_block("sample#x", block, context)
        assert f'data-block-type="{block_type}"' in fragment
        assert "data-block-id" in fragment


def test_sample_dimension_inside_allowed_set() -> None:
    for block_type, definition in BLOCKS.items():
        assert definition.sample_dimension in definition.allowed_dimensions, block_type


def test_invalid_config_rejected() -> None:
    bad_configs: dict[str, dict[str, object]] = {
        "checklist": {"label": "L", "items": []},
        "focus_session": {"label": "L", "minutes": 4},
        "checkin": {"label": "L", "metric": "sleep"},
        "calendar_slots": {"label": "L", "rule": "r", "max_slots": 0},
        "insight_card": {"label": "L", "fact_ids": []},
        "link_list": {"label": "L", "links": []},
    }
    for block_type, config in bad_configs.items():
        dimension = BLOCKS[block_type].sample_dimension
        block = BlockConfig.model_validate(
            {
                "type": block_type,
                "dimension": dimension,
                "config": config,
                "rationale": "synthetic",
            }
        )
        with pytest.raises(ValidationError):
            validate_block("sample#x", block)
    dimension = BLOCKS["checklist"].sample_dimension
    wrong_type = BlockConfig.model_validate(
        {
            "type": "checklist",
            "dimension": dimension,
            "config": {"label": "L", "items": "not-a-list"},
            "rationale": "synthetic",
        }
    )
    with pytest.raises(ValidationError):
        validate_block("sample#x", wrong_type)


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValueError, match="unknown block type: playlist"):
        get_definition("playlist")
    block = BlockConfig.model_validate(
        {
            "type": "playlist",
            "dimension": "love",
            "config": {},
            "rationale": "synthetic",
        }
    )
    with pytest.raises(ValueError, match="unknown block type: playlist"):
        validate_block("playlist#x", block)


def test_dimension_not_allowed_rejected() -> None:
    pairs = [
        ("checklist", "contrast"),
        ("focus_session", "world_needs"),
        ("checkin", "good_at"),
        ("calendar_slots", "paid_for"),
        ("link_list", "limit"),
    ]
    for block_type, dimension in pairs:
        block = BlockConfig.model_validate(
            {
                "type": block_type,
                "dimension": dimension,
                "config": BLOCKS[block_type].sample_config,
                "rationale": "synthetic",
            }
        )
        with pytest.raises(ValueError, match=f"{dimension}.*{block_type}"):
            validate_block("sample#x", block)


def _manifest_payload(
    layout: list[str], blocks: dict[str, dict[str, object]]
) -> dict[str, object]:
    return {
        "version": "v-test",
        "parent": None,
        "layout": layout,
        "blocks": blocks,
        "changelog": [],
    }


def _good_block(block_type: str) -> dict[str, object]:
    definition = BLOCKS[block_type]
    return {
        "type": block_type,
        "dimension": definition.sample_dimension,
        "config": definition.sample_config,
        "rationale": "synthetic",
    }


def test_layout_references_rejected() -> None:
    base_blocks = {
        "checklist#a": _good_block("checklist"),
        "checkin#b": _good_block("checkin"),
    }
    missing_in_blocks = Manifest.model_validate(
        _manifest_payload(["checklist#a", "ghost#z"], base_blocks)
    )
    with pytest.raises(ValueError, match="layout block not in blocks: ghost#z"):
        validate_manifest(missing_in_blocks)
    missing_in_layout = Manifest.model_validate(
        _manifest_payload(["checklist#a"], base_blocks)
    )
    with pytest.raises(ValueError, match="block not in layout: checkin#b"):
        validate_manifest(missing_in_layout)
    duplicated = Manifest.model_validate(
        {
            "version": "v-test",
            "parent": None,
            "layout": ["checklist#a", "checklist#a"],
            "blocks": {"checklist#a": _good_block("checklist")},
            "changelog": [],
        }
    )
    with pytest.raises(ValueError, match="duplicate block in layout: checklist#a"):
        validate_manifest(duplicated)


def test_url_scheme_rejected() -> None:
    bad_link = BlockConfig.model_validate(
        {
            "type": "link_list",
            "dimension": BLOCKS["link_list"].sample_dimension,
            "config": {
                "label": "L",
                "links": [{"label": "x", "url": "javascript:alert(1)"}],
            },
            "rationale": "synthetic",
        }
    )
    with pytest.raises(ValidationError):
        validate_block("link_list#x", bad_link)
    with pytest.raises(ValidationError):
        ContextLink.model_validate({"label": "x", "url": "javascript:alert(1)"})
