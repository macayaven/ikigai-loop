"""Full-page manifest rendering: offline shell, inline CSS only (ticket 6)."""

from framework.blocks.context import RenderContext
from framework.blocks.registry import render_block, validate_manifest
from framework.blocks.template import render_fragment
from framework.schemas.manifest import Manifest

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ version }}</title>
<style>body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
main { max-width: 40rem; margin: 0 auto; padding: 1rem; }
section { border-top: 1px solid #ccc; padding: 0.75rem 0; }
button, input { padding: 0.5rem; }</style>
</head>
<body><main>
<h1>{{ version }}</h1>
"""

_ENTRY = """<p>{{ change }} — {{ why }}</p>
"""

_CHANGELOG_OPEN = """<section data-changelog>
"""

_CHANGELOG_CLOSE = """</section>
"""

_TAIL = """</main></body>
</html>
"""


def render_manifest(manifest: Manifest, context: RenderContext) -> str:
    """Validate the manifest, then render blocks in layout order into one page."""
    validate_manifest(manifest)
    parts = [render_fragment(_HEAD, version=manifest.version)]
    for block_id in manifest.layout:
        parts.append(render_block(block_id, manifest.blocks[block_id], context))
    if manifest.changelog:
        parts.append(render_fragment(_CHANGELOG_OPEN))
        for entry in manifest.changelog:
            parts.append(render_fragment(_ENTRY, change=entry.change, why=entry.why))
        parts.append(render_fragment(_CHANGELOG_CLOSE))
    parts.append(render_fragment(_TAIL))
    return "".join(parts)
