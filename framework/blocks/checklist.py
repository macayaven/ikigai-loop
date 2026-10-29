"""Checklist block (type "checklist"); the renderer is pure (ticket 6)."""

from typing import Annotated

from pydantic import Field

from framework.blocks.context import RenderContext
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {"love", "good_at", "world_needs", "paid_for", "limit"}
)

SAMPLE_DIMENSION: Dimension = "good_at"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Ship one artifact",
    "items": [
        {"id": "draft", "label": "Draft the change", "done": True},
        {"id": "test", "label": "Run the tests", "done": False},
    ],
}


class ChecklistItem(SchemaModel):
    """One checklist row."""

    id: NonEmptyStr
    label: NonEmptyStr
    done: bool = False


class ChecklistConfig(SchemaModel):
    """Inner config for the "checklist" block type."""

    label: NonEmptyStr
    items: Annotated[list[ChecklistItem], Field(min_length=1, max_length=20)]


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="checklist" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
<form method="post" action="#" data-block-id="{{ block_id }}" data-block-type="checklist" data-telemetry="app.tap">
{% for item in items %}<label><input type="checkbox" name="item" value="{{ item.id }}" data-action="tick"{% if item.done %} checked{% endif %}> {{ item.label }}</label>
{% endfor %}</form>
</section>"""


def render_checklist(
    block_id: str, config: ChecklistConfig, context: RenderContext
) -> str:
    """Render a checklist fragment; pure, reads no context beyond its shape."""
    _ = context
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        items=[
            {"id": item.id, "label": item.label, "done": item.done}
            for item in config.items
        ],
    )
