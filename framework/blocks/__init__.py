"""Blocks v0 and renderer (ticket 6)."""

from framework.blocks.calendar_slots import CalendarSlotsConfig
from framework.blocks.checkin import CheckinConfig
from framework.blocks.checklist import ChecklistConfig
from framework.blocks.context import ContextLink, FactText, FreeSlot, RenderContext
from framework.blocks.focus_session import FocusSessionConfig
from framework.blocks.insight_card import InsightCardConfig
from framework.blocks.link_list import LinkListConfig
from framework.blocks.registry import (
    BLOCKS,
    BlockDefinition,
    get_definition,
    render_block,
    validate_block,
    validate_manifest,
)
from framework.blocks.render import render_manifest

__all__ = [
    "BLOCKS",
    "BlockDefinition",
    "CalendarSlotsConfig",
    "CheckinConfig",
    "ChecklistConfig",
    "ContextLink",
    "FactText",
    "FocusSessionConfig",
    "FreeSlot",
    "InsightCardConfig",
    "LinkListConfig",
    "RenderContext",
    "get_definition",
    "render_block",
    "render_manifest",
    "validate_block",
    "validate_manifest",
]
