"""Block registry: validation entry points for T8's L0 gate (ticket 6)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from framework.blocks.calendar_slots import (
    ALLOWED_DIMENSIONS as CALENDAR_SLOTS_DIMENSIONS,
)
from framework.blocks.calendar_slots import (
    SAMPLE_CONFIG as CALENDAR_SLOTS_SAMPLE_CONFIG,
)
from framework.blocks.calendar_slots import (
    SAMPLE_DIMENSION as CALENDAR_SLOTS_SAMPLE_DIMENSION,
)
from framework.blocks.calendar_slots import (
    CalendarSlotsConfig,
    render_calendar_slots,
)
from framework.blocks.checkin import ALLOWED_DIMENSIONS as CHECKIN_DIMENSIONS
from framework.blocks.checkin import SAMPLE_CONFIG as CHECKIN_SAMPLE_CONFIG
from framework.blocks.checkin import SAMPLE_DIMENSION as CHECKIN_SAMPLE_DIMENSION
from framework.blocks.checkin import CheckinConfig, render_checkin
from framework.blocks.checklist import ALLOWED_DIMENSIONS as CHECKLIST_DIMENSIONS
from framework.blocks.checklist import SAMPLE_CONFIG as CHECKLIST_SAMPLE_CONFIG
from framework.blocks.checklist import SAMPLE_DIMENSION as CHECKLIST_SAMPLE_DIMENSION
from framework.blocks.checklist import ChecklistConfig, render_checklist
from framework.blocks.context import RenderContext
from framework.blocks.focus_session import (
    ALLOWED_DIMENSIONS as FOCUS_SESSION_DIMENSIONS,
)
from framework.blocks.focus_session import (
    SAMPLE_CONFIG as FOCUS_SESSION_SAMPLE_CONFIG,
)
from framework.blocks.focus_session import (
    SAMPLE_DIMENSION as FOCUS_SESSION_SAMPLE_DIMENSION,
)
from framework.blocks.focus_session import FocusSessionConfig, render_focus_session
from framework.blocks.insight_card import ALLOWED_DIMENSIONS as INSIGHT_CARD_DIMENSIONS
from framework.blocks.insight_card import SAMPLE_CONFIG as INSIGHT_CARD_SAMPLE_CONFIG
from framework.blocks.insight_card import (
    SAMPLE_DIMENSION as INSIGHT_CARD_SAMPLE_DIMENSION,
)
from framework.blocks.insight_card import InsightCardConfig, render_insight_card
from framework.blocks.link_list import ALLOWED_DIMENSIONS as LINK_LIST_DIMENSIONS
from framework.blocks.link_list import SAMPLE_CONFIG as LINK_LIST_SAMPLE_CONFIG
from framework.blocks.link_list import SAMPLE_DIMENSION as LINK_LIST_SAMPLE_DIMENSION
from framework.blocks.link_list import LinkListConfig, render_link_list
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.manifest import BlockConfig, Manifest


@dataclass(frozen=True)
class BlockDefinition:
    """One block type: config model, renderer, dimensions, L0 sample."""

    type: str
    config_model: "type[SchemaModel]"
    renderer: Callable[[str, Any, RenderContext], str]
    allowed_dimensions: frozenset[Dimension]
    sample_dimension: Dimension
    sample_config: dict[str, object]


def _wrap_checklist(block_id: str, config: Any, context: RenderContext) -> str:
    return render_checklist(block_id, cast(ChecklistConfig, config), context)


def _wrap_focus_session(block_id: str, config: Any, context: RenderContext) -> str:
    return render_focus_session(block_id, cast(FocusSessionConfig, config), context)


def _wrap_checkin(block_id: str, config: Any, context: RenderContext) -> str:
    return render_checkin(block_id, cast(CheckinConfig, config), context)


def _wrap_calendar_slots(block_id: str, config: Any, context: RenderContext) -> str:
    return render_calendar_slots(block_id, cast(CalendarSlotsConfig, config), context)


def _wrap_insight_card(block_id: str, config: Any, context: RenderContext) -> str:
    return render_insight_card(block_id, cast(InsightCardConfig, config), context)


def _wrap_link_list(block_id: str, config: Any, context: RenderContext) -> str:
    return render_link_list(block_id, cast(LinkListConfig, config), context)


BLOCKS: dict[str, BlockDefinition] = {
    "checklist": BlockDefinition(
        type="checklist",
        config_model=ChecklistConfig,
        renderer=_wrap_checklist,
        allowed_dimensions=CHECKLIST_DIMENSIONS,
        sample_dimension=CHECKLIST_SAMPLE_DIMENSION,
        sample_config=CHECKLIST_SAMPLE_CONFIG,
    ),
    "focus_session": BlockDefinition(
        type="focus_session",
        config_model=FocusSessionConfig,
        renderer=_wrap_focus_session,
        allowed_dimensions=FOCUS_SESSION_DIMENSIONS,
        sample_dimension=FOCUS_SESSION_SAMPLE_DIMENSION,
        sample_config=FOCUS_SESSION_SAMPLE_CONFIG,
    ),
    "checkin": BlockDefinition(
        type="checkin",
        config_model=CheckinConfig,
        renderer=_wrap_checkin,
        allowed_dimensions=CHECKIN_DIMENSIONS,
        sample_dimension=CHECKIN_SAMPLE_DIMENSION,
        sample_config=CHECKIN_SAMPLE_CONFIG,
    ),
    "calendar_slots": BlockDefinition(
        type="calendar_slots",
        config_model=CalendarSlotsConfig,
        renderer=_wrap_calendar_slots,
        allowed_dimensions=CALENDAR_SLOTS_DIMENSIONS,
        sample_dimension=CALENDAR_SLOTS_SAMPLE_DIMENSION,
        sample_config=CALENDAR_SLOTS_SAMPLE_CONFIG,
    ),
    "insight_card": BlockDefinition(
        type="insight_card",
        config_model=InsightCardConfig,
        renderer=_wrap_insight_card,
        allowed_dimensions=INSIGHT_CARD_DIMENSIONS,
        sample_dimension=INSIGHT_CARD_SAMPLE_DIMENSION,
        sample_config=INSIGHT_CARD_SAMPLE_CONFIG,
    ),
    "link_list": BlockDefinition(
        type="link_list",
        config_model=LinkListConfig,
        renderer=_wrap_link_list,
        allowed_dimensions=LINK_LIST_DIMENSIONS,
        sample_dimension=LINK_LIST_SAMPLE_DIMENSION,
        sample_config=LINK_LIST_SAMPLE_CONFIG,
    ),
}


def get_definition(block_type: str) -> BlockDefinition:
    """Return the definition for one block type string."""
    try:
        return BLOCKS[block_type]
    except KeyError:
        raise ValueError(f"unknown block type: {block_type}") from None


def validate_block(block_id: str, block: BlockConfig) -> SchemaModel:
    """Validate one block envelope plus its inner config; return parsed config."""
    _ = block_id
    definition = get_definition(block.type)
    if block.dimension not in definition.allowed_dimensions:
        raise ValueError(
            f"dimension {block.dimension} not allowed for block {block.type}"
        )
    return definition.config_model.model_validate(block.config)


def validate_manifest(manifest: Manifest) -> dict[str, SchemaModel]:
    """Validate layout↔blocks agreement then every block in layout order."""
    seen: set[str] = set()
    for block_id in manifest.layout:
        if block_id in seen:
            raise ValueError(f"duplicate block in layout: {block_id}")
        seen.add(block_id)
        if block_id not in manifest.blocks:
            raise ValueError(f"layout block not in blocks: {block_id}")
    for block_id in manifest.blocks:
        if block_id not in seen:
            raise ValueError(f"block not in layout: {block_id}")
    parsed: dict[str, SchemaModel] = {}
    for block_id in manifest.layout:
        parsed[block_id] = validate_block(block_id, manifest.blocks[block_id])
    return parsed


def render_block(block_id: str, block: BlockConfig, context: RenderContext) -> str:
    """Validate one block then render its fragment with the BlockConfig dimension."""
    parsed = validate_block(block_id, block)
    definition = get_definition(block.type)
    fragment = definition.renderer(block_id, parsed, context)
    return fragment.replace(
        'data-dimension=""', 'data-dimension="' + block.dimension + '"', 1
    )
