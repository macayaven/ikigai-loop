"""Single Jinja2 helper with autoescape on (ticket 6)."""

from typing import Any

from jinja2 import Environment

_ENV = Environment(autoescape=True)


def render_fragment(source: str, **values: Any) -> str:
    """Render one in-memory template string with autoescaping enabled."""
    return _ENV.from_string(source).render(values)
