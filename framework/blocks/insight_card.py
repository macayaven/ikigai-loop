"""Insight card block (type "insight_card"); the renderer is pure (ticket 6)."""

from typing import Annotated

from pydantic import Field

from framework.blocks.context import RenderContext
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {"love", "good_at", "world_needs", "paid_for", "limit", "contrast"}
)

SAMPLE_DIMENSION: Dimension = "love"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Today in one line",
    "fact_ids": ["fact_synthetic_1"],
}


class InsightCardConfig(SchemaModel):
    """Inner config for the "insight_card" block type."""

    label: NonEmptyStr
    fact_ids: Annotated[list[NonEmptyStr], Field(min_length=1, max_length=5)]


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="insight_card" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
{% if facts %}{% for fact in facts %}<p data-fact-id="{{ fact.id }}">{{ fact.text }}</p>
{% endfor %}{% else %}<p data-empty>No insight yet</p>
{% endif %}<form method="post" action="#" data-block-id="{{ block_id }}" data-block-type="insight_card" data-telemetry="app.thumb">
<button type="submit" name="thumb" value="up" data-action="thumb-up">Up</button>
<button type="submit" name="thumb" value="down" data-action="thumb-down">Down</button>
</form>
</section>"""


def render_insight_card(
    block_id: str, config: InsightCardConfig, context: RenderContext
) -> str:
    """Render matched facts in fact_ids order; unknown ids are skipped."""
    by_id = {fact.id: fact.text for fact in context.facts}
    facts = [
        {"id": fact_id, "text": by_id[fact_id]}
        for fact_id in config.fact_ids
        if fact_id in by_id
    ]
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        facts=facts,
    )
