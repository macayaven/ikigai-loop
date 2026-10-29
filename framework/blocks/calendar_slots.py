"""Calendar slots block (type "calendar_slots"); the renderer is pure (ticket 6)."""

from typing import Annotated

from pydantic import Field

from framework.blocks.context import RenderContext
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {"love", "world_needs", "limit", "contrast"}
)

SAMPLE_DIMENSION: Dimension = "world_needs"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Call slots",
    "rule": "weekday afternoons",
    "max_slots": 3,
}


class CalendarSlotsConfig(SchemaModel):
    """Inner config for the "calendar_slots" block type."""

    label: NonEmptyStr
    rule: NonEmptyStr
    max_slots: Annotated[int, Field(ge=1, le=10)] = 3


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="calendar_slots" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
<p>{{ rule }}</p>
{% if slots %}<ul>
{% for slot in slots %}<li><time datetime="{{ slot.start_iso }}">{{ slot.start_text }}</time>–<time datetime="{{ slot.end_iso }}">{{ slot.end_text }}</time> {{ slot.label }}</li>
{% endfor %}</ul>
{% else %}<p data-empty>No free slots</p>
{% endif %}</section>"""


def render_calendar_slots(
    block_id: str, config: CalendarSlotsConfig, context: RenderContext
) -> str:
    """Render free slots in caller order; pure, no timezone conversion."""
    slots = [
        {
            "start_iso": slot.start.isoformat(),
            "end_iso": slot.end.isoformat(),
            "start_text": slot.start.strftime("%Y-%m-%d %H:%M"),
            "end_text": slot.end.strftime("%H:%M"),
            "label": slot.label,
        }
        for slot in context.free_slots[: config.max_slots]
    ]
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        rule=config.rule,
        slots=slots,
    )
