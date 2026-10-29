"""Check-in block (type "checkin"); the renderer is pure (ticket 6)."""

from typing import Literal

from framework.blocks.context import RenderContext
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset({"love", "limit", "contrast"})

SAMPLE_DIMENSION: Dimension = "limit"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Energy check-in",
    "prompt": "How is your energy right now?",
    "metric": "energy",
}

CheckinMetric = Literal["energy", "mood", "wellbeing"]


class CheckinConfig(SchemaModel):
    """Inner config for the "checkin" block type."""

    label: NonEmptyStr
    prompt: str = ""
    metric: CheckinMetric = "energy"


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="checkin" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
{% if prompt %}<p>{{ prompt }}</p>
{% endif %}<form method="post" action="#" data-block-id="{{ block_id }}" data-block-type="checkin" data-telemetry="app.checkin">
{% for value in values %}<button type="submit" name="value" value="{{ value }}" data-action="checkin" data-metric="{{ metric }}">{{ value }}</button>
{% endfor %}</form>
</section>"""


def render_checkin(block_id: str, config: CheckinConfig, context: RenderContext) -> str:
    """Render a check-in fragment; pure, reads no context values."""
    _ = context
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        prompt=config.prompt,
        metric=config.metric,
        values=[1, 2, 3, 4, 5],
    )
