"""Link list block (type "link_list"); the renderer is pure (ticket 6)."""

from typing import Annotated

from pydantic import Field, field_validator

from framework.blocks.context import RenderContext, check_http_url
from framework.blocks.template import render_fragment
from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

ALLOWED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {"love", "good_at", "world_needs", "paid_for"}
)

SAMPLE_DIMENSION: Dimension = "world_needs"
SAMPLE_CONFIG: dict[str, object] = {
    "label": "Worth a look",
    "links": [
        {
            "label": "Synthetic paper",
            "url": "https://example.invalid/paper",
            "note": "why it matters",
        }
    ],
}


class LinkItem(SchemaModel):
    """One curated link; only http(s) URLs are representable."""

    label: NonEmptyStr
    url: NonEmptyStr
    note: str = ""

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, url: str) -> str:
        return check_http_url(url)


class LinkListConfig(SchemaModel):
    """Inner config for the "link_list" block type."""

    label: NonEmptyStr
    links: Annotated[list[LinkItem], Field(min_length=1, max_length=20)]


_TEMPLATE = """<section data-block-id="{{ block_id }}" data-block-type="link_list" data-dimension="{{ dimension }}">
<h2>{{ label }}</h2>
<ul>
{% for link in links %}<li><a href="{{ link.url }}" rel="noopener noreferrer">{{ link.label }}</a>{% if link.note %} {{ link.note }}{% endif %}</li>
{% endfor %}</ul>
</section>"""


def render_link_list(
    block_id: str, config: LinkListConfig, context: RenderContext
) -> str:
    """Render config links only; context.links is unconsumed in v0."""
    _ = context
    return render_fragment(
        _TEMPLATE,
        block_id=block_id,
        dimension="",
        label=config.label,
        links=[
            {"label": link.label, "url": link.url, "note": link.note}
            for link in config.links
        ],
    )
