"""Focus session block (type "focus_session"); the renderer is pure (ticket 6)."""

from typing import Annotated

from pydantic import Field

from framework.blocks.context import RenderContext
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {"love", "good_at", "paid_for", "limit"}
)

SAMPLE_DIMENSION: Dimension = "good_at"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Deep build window",
    "minutes": 50,
    "goal": "One artifact by the end",
}


class FocusSessionConfig(SchemaModel):
    """Inner config for the "focus_session" block type."""

    label: NonEmptyStr
    minutes: Annotated[int, Field(ge=5, le=180)]
    goal: str = ""


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="focus_session" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
{% if goal %}<p>{{ goal }}</p>
{% endif %}<p data-timer-display data-duration-minutes="{{ minutes }}">{{ minutes }}:00</p>
<form method="post" action="#" data-block-id="{{ block_id }}" data-block-type="focus_session" data-telemetry="app.tap">
<button type="button" data-action="focus-start">Start</button>
<button type="button" data-action="focus-pause">Pause</button>
</form>
</section>"""


def render_focus_session(
    block_id: str, config: FocusSessionConfig, context: RenderContext
) -> str:
    """Render a focus session fragment; pure, reads no context values."""
    _ = context
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        goal=config.goal,
        minutes=config.minutes,
    )
