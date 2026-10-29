## Goal

Ticket 6 — blocks v0 and renderer. After this ticket, `framework/blocks/` (pyright strict) holds six block types — `checklist`, `focus_session`, `checkin`, `calendar_slots`, `insight_card`, `link_list` — each with a frozen Pydantic config model validated against the existing `BlockConfig`, a pure render function to an HTML fragment, an allowed-dimension set, and one L0 sample config. A registry maps block type to (config model, renderer, allowed dimensions) and is the single validation entry point T8's L0 gate will call: unknown type, invalid config, disallowed dimension, and broken layout references all fail validation there. `render_manifest(manifest, context)` renders a full offline HTML page in layout order; `context` is a typed model of display-ready data only (free slots, facts' short text, links), never raw events. Two sample manifests in `tests/fixtures/` (`sample-builder`, `sample-recovery` — rendering samples, not day-0 manifests; see the Approved amendment), each using all six blocks plausibly for its profile, render via a script to a gitignored `out/` dir for manual viewing. The frozen schemas in `framework/schemas/manifest.py` (`Manifest`, `BlockConfig`) are used as-is and never modified.

Grounding, checked 2026-10-29 in this (plan) session: [docs/SPEC.md](../SPEC.md) §3 (manifest shape with `layout` as ordered `type#id` strings and `blocks` keyed by the same ids; block library table; change levels C1 configure / C2 compose / C3 new block; "each = Pydantic config schema + renderer + tests + allowed dimensions"); [framework/schemas/manifest.py](../../framework/schemas/manifest.py) as committed in T3 — `BlockConfig(SchemaModel)` with `type: NonEmptyStr`, `dimension: Dimension`, `config: dict[str, Any] = {}`, `rationale: str = ""`, and `Manifest` with `version`, `parent`, `layout: list[str]`, `blocks: dict[str, BlockConfig]`, `changelog` — note `Manifest` itself does **not** check that `layout` and `blocks` agree, so the registry must; [framework/schemas/base.py](../../framework/schemas/base.py) (`SchemaModel` = frozen, `extra="forbid"`, `populate_by_name=True`; `Dimension = Literal["love", "good_at", "world_needs", "paid_for", "limit", "contrast"]`); [framework/schemas/events.py](../../framework/schemas/events.py) (`NonEmptyStr = Annotated[str, Field(min_length=1)]`, reuse it, do not redefine); [docs/PLAN.md](../PLAN.md) §3 row T6 ("`checklist, focus_session, checkin, calendar_slots, insight_card, link_list`: schema, renderer, unit test, L0 sample each. Manifest renders to a web page", depends T3) and §9 (T6 due Oct 30); `profiles/builder.md` and `profiles/recovery.md` read **only** to choose realistic sample labels below — no code, test, or fixture loads or parses them; `pyproject.toml` pins Python 3.12, runtime deps today `pydantic` + `inspect-ai` + the T5 calendar stack, pyright `strict = ["framework"]`, pytest `testpaths = ["tests"]`, `pythonpath = ["."]`; `Makefile` `check` is `ruff check`, `ruff format --check`, `pyright`, `pytest`, `gitleaks git --redact`; `.gitignore` has no `out/` entry yet. Branch `t6-blocks-renderer` already exists and is clean at `38ac52a` (Ticket 5 amendment 4). `muse --version` in this session: `Muse Code 1.4.14 (1.4.14-R7309.1)`. The private companion repo and the path in `HIDDEN_CRITERIA_DIR` are never read.

## Success Criteria

- `framework/blocks/` (pyright strict clean) exposes the six block types below. Each block module defines exactly: a config model subclassing `SchemaModel` (frozen, `extra="forbid"` inherited), `ALLOWED_DIMENSIONS: frozenset[Dimension]`, a pure `render_<type>(block_id, config, context) -> str` returning an HTML fragment, and `SAMPLE_CONFIG: dict[str, object]` plus `SAMPLE_DIMENSION: Dimension` forming one valid L0 sample. Nothing under `framework/schemas/` changes.
- A registry maps each block type string to `(config model, renderer, allowed dimensions, sample)`. `validate_block(block_id, block)` and `validate_manifest(manifest)` are the L0 entry points T8 will call: unknown `type`, a `config` dict that fails the block's config model, a `dimension` outside the block's allowed set, a `layout` id missing from `blocks`, a `blocks` key missing from `layout`, and a duplicate `layout` id each raise `ValueError` or `pydantic.ValidationError` — never a silent pass, never a raw `KeyError`.
- `render_manifest(manifest, context) -> str` validates via the registry, then returns one complete HTML page: blocks as `<section>` fragments in `layout` order, inline CSS only, no external assets, no `<script>` element, readable at phone width. `context` is the pinned `RenderContext` model (free slots, fact short texts, links); no renderer accepts or reads raw events, files, env vars, or the network.
- Rendering is escaping-safe: every user-controlled string (labels, item text, fact text, link labels, URLs, manifest version, changelog text) goes through Jinja2 autoescaping, in text and attribute positions. A `<script>alert(1)</script>` label renders inert (escaped text, no live tag). Link URLs are restricted to `http://`/`https://` at config validation, so no `javascript:` href can be emitted.
- Interactive bits are plain HTML only: checklist tick (checkbox inputs), checkin tap (1–5 submit buttons), focus timer (start/pause buttons plus a display element), insight thumbs (up/down buttons) — all `<form method="post" action="#">` or `type="button"` elements carrying the pinned `data-block-id` / `data-block-type` / `data-action` / `data-telemetry` attributes for T12/T13 to wire to `app.*` telemetry. There is no JavaScript and no backend call anywhere in the output.
- `tests/fixtures/sample-builder.json` and `tests/fixtures/sample-recovery.json` are rendering samples, not day-0 manifests. They are valid `Manifest` JSON documents, each containing all six block types exactly once, built only from these blocks, with synthetic-plausible labels per profile (Approach). `python -m framework.blocks` renders both to `out/sample-builder.html` and `out/sample-recovery.html` (`out/` gitignored) for manual viewing and prints only the two paths.
- Tests prove: every sample config validates and renders; invalid config and unknown type are rejected; a dimension not allowed for a block is rejected; `<script>` in user text renders inert; both sample manifests render to a page containing every block in layout order. All tests are offline; no test reads `profiles/*.md`, `HIDDEN_CRITERIA_DIR`, or any path outside the repo and `tmp_path`.
- `pyproject.toml` / `uv.lock` gain exactly one new runtime dependency, `jinja2` (decision in Approach). `docs/sessions/006-blocks-renderer.md` evidence note (first line of `muse --version` run in the implementation session, models/efforts per phase) and a `CONTRIBUTIONS.md` Ticket 6 entry exist. The evidence note contains, as a standalone `rationale`-free note (the sentence alone, with no rationale or explanation attached), exactly: "Day 0 starts both profiles from one shared, byte-identical seed manifest (SPEC §9), created in T13; these fixtures are never deployed." `make check` is green; exactly one commit on `t6-blocks-renderer`, not pushed.

## Approach

Key decisions (all binding on the implementer; alternatives are rejected in Risks only where the choice was live):

- **Package layout is exactly ten modules under `framework/blocks/`** (no `blocks/` at repo root in this ticket, despite the SPEC §8 sketch — the ticket pins `framework/blocks/`, and SPEC's per-block-folder layout is for the later C3 path):
  - `framework/blocks/__init__.py` — docstring + re-exports + `__all__` (registry API, `RenderContext` and its item models, `render_manifest`, the six config models).
  - `framework/blocks/context.py` — `RenderContext`, `FreeSlot`, `FactText`, `ContextLink` (below).
  - `framework/blocks/template.py` — the single Jinja2 helper (below); the only module that imports `jinja2`.
  - `framework/blocks/checklist.py`, `focus_session.py`, `checkin.py`, `calendar_slots.py`, `insight_card.py`, `link_list.py` — one per block (config model, `ALLOWED_DIMENSIONS`, renderer, sample).
  - `framework/blocks/registry.py` — `BlockDefinition`, `BLOCKS`, `validate_block`, `validate_manifest`, `render_block`.
  - `framework/blocks/render.py` — `render_manifest` and the page shell.
  - `framework/blocks/__main__.py` — the sample-render script.
  No other modules; no async; no change to `framework/schemas/`, `framework/store/`, or `framework/collectors/`.
- **How block configs relate to `BlockConfig` (do not change `manifest.py`).** `BlockConfig.config` stays an opaque `dict[str, Any]` in the manifest. Each block defines its own inner config model for that dict — e.g. `ChecklistConfig(SchemaModel)` with typed fields — and the registry validates `block.config` through it (`config_model.model_validate(block.config)`). The block's identity fields (`type`, `dimension`, `rationale`) stay on `BlockConfig`; the inner model holds only the block-specific fields (so no inner model redeclares `type`/`dimension`). This is the "subclassing/validated against `BlockConfig`" seam the ticket allows: every block is validated against its `BlockConfig` envelope (type + dimension + rationale) and its inner model. Renderers receive the **parsed** inner model, never the raw dict.
- **Templating is Jinja2 with autoescape on; stdlib string building is rejected.** Justification: six renderers interpolate user text into both element text and HTML attributes (`href`, `data-*`, `value`); hand-escaping every site with `html.escape` is exactly where a missed attribute quote becomes an XSS hole, and the escaping test (AT5) would only sample that risk. Jinja2's `autoescape=True` escapes by construction at every interpolation. Add it with `uv add jinja2` and let `uv` resolve the version; commit `pyproject.toml` + `uv.lock`; invent no version numbers. Pin the seam in `template.py` so no other module touches Jinja2:

```python
from typing import Any

from jinja2 import Environment

_ENV = Environment(autoescape=True)


def render_fragment(source: str, **values: Any) -> str:
    return _ENV.from_string(source).render(values)
```

  Templates are string constants inside each block module (no template files, no filesystem access, page works offline). `Any` appears only in this helper's `**values` and in `BlockDefinition`'s parsed-config plumbing (registry below); pyright strict is satisfied by annotating everything else concretely. Renderers must never use `|safe`, `Markup`, or string-format HTML by hand — all HTML comes from `render_fragment`.
- **`RenderContext` (`context.py`) is display-ready data only.** Exactly:

```python
class FreeSlot(SchemaModel):
    start: AwareDatetime
    end: AwareDatetime
    label: str = ""
    # validator: end must not be before start (mirror FactWindow in core.py)


class FactText(SchemaModel):
    id: NonEmptyStr
    text: NonEmptyStr  # short display text only, already derived upstream


class ContextLink(SchemaModel):
    label: NonEmptyStr
    url: NonEmptyStr  # validated http/https by the same validator as link_list


class RenderContext(SchemaModel):
    free_slots: list[FreeSlot] = Field(default_factory=list)
    facts: list[FactText] = Field(default_factory=list)
    links: list[ContextLink] = Field(default_factory=list)
```

  No field may hold a raw event, a calendar title, a health value, or file/env data — this type is the privacy seam, and its docstring says so. Renderers select from it deterministically: `calendar_slots` takes `context.free_slots[:config.max_slots]` in the order given (sorting is the caller's job); `insight_card` looks facts up by `config.fact_ids` order and silently skips an id absent from `context.facts` (rendering the label and whatever matched, or the pinned empty text below); `link_list` renders **config** links only (config is the curated list; `context.links` exists for future blocks and is not consumed in v0 — stated here so the implementer does not invent a merge rule).
- **The six blocks, pinned.** Field bounds are part of the contract (tests assert the rejection cases). All string fields meant to be non-empty use `NonEmptyStr` imported from `framework.schemas.events`. Every renderer returns exactly one `<section data-block-id="…" data-block-type="…" data-dimension="…">…</section>` fragment; the section attributes come from the `BlockConfig`, escaped by Jinja2 like everything else.

  | Type | Config model (inner fields) | Allowed dimensions | Fragment contents |
  |---|---|---|---|
  | `checklist` | `ChecklistConfig`: `label: NonEmptyStr`; `items: list[ChecklistItem]` with `Field(min_length=1, max_length=20)`; `ChecklistItem(SchemaModel)`: `id: NonEmptyStr`, `label: NonEmptyStr`, `done: bool = False` | `{"love", "good_at", "world_needs", "paid_for", "limit"}` | `<h2>` label; one `<form method="post" action="#" data-block-id data-block-type="checklist" data-telemetry="app.tap">` with, per item, `<label><input type="checkbox" name="item" value="<item id>" data-action="tick" {% if done %}checked{% endif %}> <item label></label>` |
  | `focus_session` | `FocusSessionConfig`: `label: NonEmptyStr`; `minutes: Annotated[int, Field(ge=5, le=180)]`; `goal: str = ""` | `{"love", "good_at", "paid_for", "limit"}` | `<h2>` label; optional goal `<p>`; `<p data-timer-display data-duration-minutes="<minutes>"><minutes>:00</p>`; two `<button type="button" data-action="focus-start">` / `data-action="focus-pause"` inside a form carrying `data-telemetry="app.tap"` |
  | `checkin` | `CheckinConfig`: `label: NonEmptyStr`; `prompt: str = ""`; `metric: Literal["energy", "mood", "wellbeing"] = "energy"` | `{"love", "limit", "contrast"}` | `<h2>` label; optional prompt `<p>`; one form (`data-telemetry="app.checkin"`) with five `<button type="submit" name="value" value="1"…"5" data-action="checkin" data-metric="<metric>">1</button>`… |
  | `calendar_slots` | `CalendarSlotsConfig`: `label: NonEmptyStr`; `rule: NonEmptyStr` (display text, e.g. `"weekday afternoons"`); `max_slots: Annotated[int, Field(ge=1, le=10)] = 3` | `{"love", "world_needs", "limit", "contrast"}` | `<h2>` label; `<p>` rule; `<ul>` of `context.free_slots[:max_slots]`, each `<li><time datetime="<start ISO>">YYYY-MM-DD HH:MM</time>–<time …>HH:MM</time> <slot label></li>` (times rendered from the aware datetimes as-is, no timezone conversion); if no slots, `<p data-empty>No free slots</p>` |
  | `insight_card` | `InsightCardConfig`: `label: NonEmptyStr`; `fact_ids: Annotated[list[NonEmptyStr], Field(min_length=1, max_length=5)]` | all six dimensions | `<h2>` label; one `<p data-fact-id="…">` per matched fact in `fact_ids` order; if none matched, `<p data-empty>No insight yet</p>`; thumbs form (`data-telemetry="app.thumb"`) with `<button type="submit" name="thumb" value="up" data-action="thumb-up">` and `value="down" data-action="thumb-down"` |
  | `link_list` | `LinkListConfig`: `label: NonEmptyStr`; `links: Annotated[list[LinkItem], Field(min_length=1, max_length=20)]`; `LinkItem(SchemaModel)`: `label: NonEmptyStr`, `url: NonEmptyStr`, `note: str = ""` | `{"love", "good_at", "world_needs", "paid_for"}` | `<h2>` label; `<ul>` with `<li><a href="<url>" rel="noopener noreferrer"><label></a>` plus optional note text after it |

  URL rule (shared): `LinkItem.url` and `ContextLink.url` each get a `field_validator` that raises `ValueError("url must start with http:// or https://")` unless the value starts with `http://` or `https://` (exact, case-sensitive prefix check — no parsing, no normalisation). This is what keeps `javascript:`/`data:` hrefs unrepresentable.
- **Samples (L0).** Each block module pins `SAMPLE_DIMENSION` (the first-listed allowed dimension in the table order above is not required — use the pinned value here) and `SAMPLE_CONFIG` as a plain `dict[str, object]` of the inner config only:
  - `checklist`: dimension `good_at`, `{"label": "Ship one artifact", "items": [{"id": "draft", "label": "Draft the change", "done": True}, {"id": "test", "label": "Run the tests", "done": False}]}`.
  - `focus_session`: dimension `good_at`, `{"label": "Deep build window", "minutes": 50, "goal": "One artifact by the end"}`.
  - `checkin`: dimension `limit`, `{"label": "Energy check-in", "prompt": "How is your energy right now?", "metric": "energy"}`.
  - `calendar_slots`: dimension `world_needs`, `{"label": "Call slots", "rule": "weekday afternoons", "max_slots": 3}`.
  - `insight_card`: dimension `love`, `{"label": "Today in one line", "fact_ids": ["fact_synthetic_1"]}`.
  - `link_list`: dimension `world_needs`, `{"label": "Worth a look", "links": [{"label": "Synthetic paper", "url": "https://example.invalid/paper", "note": "why it matters"}]}`.
  All sample text is synthetic (`.invalid`, invented ids) — no real paper, repo, person, or profile text copied verbatim.
- **Registry (`registry.py`).** Exactly:

```python
@dataclass(frozen=True)
class BlockDefinition:
    type: str
    config_model: type[SchemaModel]
    renderer: Callable[[str, Any, RenderContext], str]
    allowed_dimensions: frozenset[Dimension]
    sample_dimension: Dimension
    sample_config: dict[str, object]


BLOCKS: dict[
    str, BlockDefinition
]  # keyed by the six type strings, built from the block modules
```

  Each block module's renderer is written with its concrete config type (e.g. `def render_checklist(block_id: str, config: ChecklistConfig, context: RenderContext) -> str`); the registry adapts it with a small typed wrapper or `cast` so `BLOCKS` stays pyright-strict clean — the wrapper validates nothing (validation already happened) and only narrows the type. Functions:
  - `get_definition(block_type: str) -> BlockDefinition` — raises `ValueError(f"unknown block type: {block_type}")` when absent.
  - `validate_block(block_id: str, block: BlockConfig) -> SchemaModel` — `get_definition(block.type)`; if `block.dimension not in definition.allowed_dimensions`, raise `ValueError(f"dimension {block.dimension} not allowed for block {block.type}")`; return `definition.config_model.model_validate(block.config)` (a bad config propagates `pydantic.ValidationError`). `block_id` is used in neither message except as pinned — keep messages exactly as written here so T8 can match on them.
  - `validate_manifest(manifest: Manifest) -> dict[str, SchemaModel]` — first: duplicate id in `layout` → `ValueError("duplicate block in layout: <id>")`; `layout` id not in `blocks` → `ValueError("layout block not in blocks: <id>")`; `blocks` key not in `layout` → `ValueError("block not in layout: <id>")` (check in layout order, then blocks order, so the failure is deterministic); then validate every block in `layout` order via `validate_block` and return parsed configs keyed by block id.
  - `render_block(block_id: str, block: BlockConfig, context: RenderContext) -> str` — validates via `validate_block`, then calls the renderer. Renderers are pure: same inputs, same string; no I/O, no clock, no randomness.
- **Page rendering (`render.py`).** `render_manifest(manifest: Manifest, context: RenderContext) -> str` calls `validate_manifest` first (so an invalid manifest raises before any HTML exists), renders each block via the registry in `layout` order, and wraps the fragments in this shell (also via `render_fragment`, so the version is escaped): `<!doctype html>`, `<html lang="en">`, `<head>` with `<meta charset="utf-8">`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, `<title>{{ version }}</title>`, and one inline `<style>` block; `<body><main>` with `<h1>{{ version }}</h1>`, the fragments, then — only when `manifest.changelog` is non-empty — a `<section data-changelog>` listing each entry's `change` and `why` as escaped text. The CSS is one pinned minimal block (write it literally, do not improvise a framework): system font stack, `main { max-width: 40rem; margin: 0 auto; padding: 1rem; }`, `section { border-top: 1px solid #ccc; padding: 0.75rem 0; }`, buttons/inputs at least `padding: 0.5rem` for phone tapping. No external assets means: no `<link>`, no `<script>` (there is no JavaScript at all), no `<img>`, no `@import`, no `url(` in the CSS. In-page `<a href>` from `link_list` is content, not an asset, and is allowed.
- **Sample manifests (`tests/fixtures/sample-builder.json`, `tests/fixtures/sample-recovery.json`).** These are rendering samples, not day-0 manifests. Hand-written JSON, each loadable as `Manifest.model_validate_json(...)`, `version` `"sample-builder"` / `"sample-recovery"`, `parent: null`, `changelog: []`, `layout` listing six `<type>#<slug>` ids, `blocks` with exactly those keys. Each manifest uses all six types exactly once. Labels are plausible per profile but synthetic (invented slugs/text; the profiles were read only for themes — builder: artifacts, focus windows, energy pace, papers; recovery: walks, music, family calls, wind-down). Pinned contents:

  | Block id | Sample Builder (`sample-builder`) | Sample Recovery (`sample-recovery`) |
  |---|---|---|
  | `checklist#…` | `checklist#ship`, dim `good_at`, label `"Ship one artifact today"`, items `draft`/`test`/`publish` | `checklist#day`, dim `love`, label `"A good day"`, items `walk` (`"25 min walk this afternoon"`)/`journal`/`music` |
  | `focus_session#…` | `focus_session#build`, dim `good_at`, 50 min, goal `"One artifact by 23:30"` | `focus_session#rest`, dim `love`, 15 min, goal `"Music, no goal beyond listening"` |
  | `checkin#…` | `checkin#energy`, dim `limit`, metric `energy`, prompt `"Energy right now?"` | `checkin#wellbeing`, dim `limit`, metric `wellbeing`, prompt `"How are you, honestly?"` |
  | `calendar_slots#…` | `calendar_slots#calls`, dim `world_needs`, rule `"weekday afternoons"`, max 3 | `calendar_slots#family`, dim `love`, rule `"afternoons, unhurried"`, max 3 |
  | `insight_card#…` | `insight_card#today`, dim `love`, `fact_ids: ["fact_builder_1"]` | `insight_card#today`, dim `love`, `fact_ids: ["fact_recovery_1"]` |
  | `link_list#…` | `link_list#reading`, dim `world_needs`, links to `https://example.invalid/paper-1` etc. | `link_list#listen`, dim `love`, links to `https://example.invalid/playlist-1` etc. |

  Every `dimension` above is in that block's allowed set (check against the table — this is deliberate, the fixtures must pass the registry). `rationale` on each block: one short synthetic sentence. No real URLs (`.invalid` only), no names, no health/calendar values.
- **Render script (`__main__.py`).** `main(argv: list[str] | None = None) -> int` with no arguments accepted (argparse with no positionals; an unexpected argument is an argparse error, exit 2). It loads both fixtures from `tests/fixtures/` (path relative to the repo root resolved from `Path(__file__).resolve().parents[2]`, never a cwd assumption), builds one fixed synthetic `RenderContext` (two `FreeSlot`s on 2026-10-31 Europe/Madrid-aware datetimes with labels `"Synthetic slot"`, `FactText`s for `fact_builder_1` and `fact_recovery_1` with one-line synthetic texts, `links: []`), renders both manifests, writes `out/sample-builder.html` and `out/sample-recovery.html` (creating `out/`), prints exactly two lines `wrote out/sample-builder.html` and `wrote out/sample-recovery.html`, returns 0. `if __name__ == "__main__": raise SystemExit(main())`. It prints no HTML and no fixture content beyond those paths. Add `out/` to `.gitignore` under a `# rendered samples` comment.
- **pyright strict and style.** `framework/` is strict: annotate every function including `-> None` on tests, no bare `dict`/`list` without parameters where the value type is known (`dict[str, object]` for sample configs and `Any` only where pinned above). Follow neighbouring style (`framework/schemas/`, `framework/collectors/`): short module docstrings naming the ticket, double quotes, ruff format. Every block module docstring states its type string and that its renderer is pure.

## Files to Create

| File | Contents |
|---|---|
| `framework/blocks/__init__.py` | Docstring ("Blocks v0 and renderer (ticket 6)"), re-exports `BLOCKS`, `BlockDefinition`, `get_definition`, `validate_block`, `validate_manifest`, `render_block`, `RenderContext`, `FreeSlot`, `FactText`, `ContextLink`, `render_manifest`, and the six config models, with `__all__` |
| `framework/blocks/context.py` | `FreeSlot` (with end-not-before-start validator), `FactText`, `ContextLink` (with the http/https URL validator), `RenderContext` — display-ready data only, per Approach |
| `framework/blocks/template.py` | The Jinja2 `Environment(autoescape=True)` singleton and `render_fragment(source, **values)` — the only `jinja2` import in the repo |
| `framework/blocks/checklist.py` | `ChecklistItem`, `ChecklistConfig`, `ALLOWED_DIMENSIONS`, `render_checklist`, `SAMPLE_DIMENSION`, `SAMPLE_CONFIG` per Approach |
| `framework/blocks/focus_session.py` | `FocusSessionConfig`, `ALLOWED_DIMENSIONS`, `render_focus_session`, sample per Approach |
| `framework/blocks/checkin.py` | `CheckinConfig`, `ALLOWED_DIMENSIONS`, `render_checkin`, sample per Approach |
| `framework/blocks/calendar_slots.py` | `CalendarSlotsConfig`, `ALLOWED_DIMENSIONS`, `render_calendar_slots`, sample per Approach |
| `framework/blocks/insight_card.py` | `InsightCardConfig`, `ALLOWED_DIMENSIONS`, `render_insight_card`, sample per Approach |
| `framework/blocks/link_list.py` | `LinkItem` (with URL validator), `LinkListConfig`, `ALLOWED_DIMENSIONS`, `render_link_list`, sample per Approach |
| `framework/blocks/registry.py` | `BlockDefinition`, `BLOCKS`, `get_definition`, `validate_block`, `validate_manifest`, `render_block` per Approach, with the pinned error messages |
| `framework/blocks/render.py` | `render_manifest` and the pinned page shell + inline CSS per Approach |
| `framework/blocks/__main__.py` | `main(argv=None) -> int` per Approach: renders both fixtures with the fixed synthetic context to `out/`, prints only the two `wrote …` lines |
| `tests/fixtures/sample-builder.json` | Rendering sample (not a day-0 manifest) per Approach (all six blocks, synthetic `.invalid` links only) |
| `tests/fixtures/sample-recovery.json` | Rendering sample (not a day-0 manifest) per Approach (all six blocks, synthetic `.invalid` links only) |
| `tests/test_blocks.py` | Registry/config tests: each sample validates + renders, invalid config rejected, unknown type rejected, disallowed dimension rejected, broken layout references rejected, URL scheme rejected (AT1–AT4, AT6) |
| `tests/test_render_manifest.py` | Page tests: `<script>` label renders inert, both fixtures render with every block in layout order, offline/phone shell properties, context-driven fragments (slots, insight lookup, empty states), checklist done state, `python -m framework.blocks` script writes both files under a `tmp_path`-redirected repo root or an `out/` dir the test creates and cleans (AT5, AT7–AT10) |
| `docs/sessions/006-blocks-renderer.md` | Evidence note mirroring `docs/sessions/005-collectors-wave1.md`: first line of `muse --version` run in the implementation session (verbatim), models/efforts per phase (plan: muse-wonder-1.0 high; implementation: muse-spark-1.3 medium — record what actually happened), wall time if known, AT results with pytest counts, public-repo sweep result, statement that the raw redacted export is kept privately, plus a standalone `rationale`-free note containing exactly this sentence and nothing attached to it: "Day 0 starts both profiles from one shared, byte-identical seed manifest (SPEC §9), created in T13; these fixtures are never deployed." |

## Files to Modify

| File | Change |
|---|---|
| `pyproject.toml` | Only via `uv add jinja2`: the name appears in `[project] dependencies`. No other edit (no tool config changes) |
| `uv.lock` | Regenerated by that same `uv add`; committed as resolved. No hand edits |
| `.gitignore` | Append `# rendered samples` and `out/` |
| `CONTRIBUTIONS.md` | Add a `Ticket 6 — blocks v0 and renderer` entry after the Ticket 5 entry (chronological), same shape as existing entries: what was built, branch `t6-blocks-renderer` + plan link, date, and the real Muse models/efforts per phase (plan vs implementation) |
| `docs/plans/006-blocks-renderer.md` | This plan, committed with the implementation |

No other existing files change. In particular: nothing under `framework/schemas/` (including `manifest.py`), `schemas/`, `framework/store/`, `framework/collectors/`, `profiles/`, `Makefile`, `AGENTS.md`, `README.md`, `docs/WORKFLOW.md`; no file reads `HIDDEN_CRITERIA_DIR`, the private companion repo, or `profiles/*.md` at runtime or in tests.

## Steps

1. Pre-flight on `t6-blocks-renderer`: `git branch --show-current` prints `t6-blocks-renderer`, `git status` clean (this plan file untracked is expected until step 6). Negative control first (AT11): on the current tree, `uv run pytest tests/test_blocks.py tests/test_render_manifest.py` fails at collection (no `framework.blocks`) and `test -d framework/blocks` fails.
2. Add the dependency: `uv add jinja2`; confirm `git diff pyproject.toml` shows only the `jinja2` name and `uv.lock` updated. Do not proceed on a `uv` failure — report it instead of falling back to hand-rolled escaping (that fallback needs a plan amendment, per Risks).
3. Write the fixtures and the tests first (`tests/fixtures/sample-builder.json`, `tests/fixtures/sample-recovery.json`, `tests/test_blocks.py`, `tests/test_render_manifest.py`) with synthetic data only, and confirm they fail because `framework.blocks` does not exist yet.
4. Implement `framework/blocks/` in this order: `context.py`, `template.py`, the six block modules, `registry.py`, `render.py`, `__init__.py`, `__main__.py`, per the Approach recipes. Run `make test` until green, then the full `make check` (ruff, format, pyright strict on `framework/`, pytest, gitleaks) and fix findings in the new code, never by relaxing config.
5. Append `out/` to `.gitignore`. Run the script once (`uv run python -m framework.blocks`), open both `out/*.html` files to confirm they read sensibly at a narrow width, then leave `out/` untracked (it is gitignored). Public-repo sweep over every touched file: real names, real URLs (only `https://example.invalid/…` may appear), profile text copied verbatim, private paths, secrets.
6. Write `docs/sessions/006-blocks-renderer.md` (including the verbatim first line of `muse --version` run in this implementation session, and the standalone `rationale`-free note pinned in Files to Create) and the `CONTRIBUTIONS.md` Ticket 6 entry with the real models/efforts per phase; run all acceptance tests and `make check` one final time.
7. One commit on `t6-blocks-renderer` containing exactly: `docs/plans/006-blocks-renderer.md`, `framework/blocks/` (10 files), `tests/test_blocks.py`, `tests/test_render_manifest.py`, `tests/fixtures/sample-builder.json`, `tests/fixtures/sample-recovery.json`, `pyproject.toml`, `uv.lock`, `.gitignore`, `CONTRIBUTIONS.md`, `docs/sessions/006-blocks-renderer.md`. Do not push.

## Acceptance Tests

Each is a command plus its expected result. AT1–AT10 pass on the branch; AT11 is the negative control on the base. Test names below are the names to use in the new test files so the mapping is checkable.

| # | Command | Expected result |
|---|---|---|
| AT1 | `uv run pytest tests/test_blocks.py -k sample` | Exit 0; for each of the six registry entries, `validate_block("sample#x", BlockConfig(type=…, dimension=SAMPLE_DIMENSION, config=SAMPLE_CONFIG))` returns the block's config model instance, and `render_block` returns a fragment containing `data-block-type="<type>"` and the sample label |
| AT2 | `uv run pytest tests/test_blocks.py -k invalid_config` | Exit 0; per block, at least one pinned bad config raises `ValidationError`: checklist with `items: []`, focus_session with `minutes: 4`, checkin with `metric: "sleep"`, calendar_slots with `max_slots: 0`, insight_card with `fact_ids: []`, link_list with `links: []`; plus one wrong-type case (checklist `items` as a string) |
| AT3 | `uv run pytest tests/test_blocks.py -k unknown_type` | Exit 0; `get_definition("playlist")` and `validate_block` on a `BlockConfig(type="playlist", …)` raise `ValueError` with message `unknown block type: playlist` (SPEC's `playlist` is deliberately not in v0) |
| AT4 | `uv run pytest tests/test_blocks.py -k dimension` | Exit 0; one disallowed pair per block raises `ValueError` naming the dimension and type: checklist/`contrast`, focus_session/`world_needs`, checkin/`good_at`, calendar_slots/`paid_for`, link_list/`limit` (insight_card allows all six, so it is covered positively in AT1); each block's `SAMPLE_DIMENSION` is asserted inside its allowed set |
| AT5 | `uv run pytest tests/test_render_manifest.py -k escap` | Exit 0; a checklist whose label is `<script>alert(1)</script>` and an insight fact whose text is `<b>bold</b> & "quoted"` render with the escaped forms (`&lt;script&gt;` etc.) present, and the page contains no literal `<script` substring anywhere and no unescaped `<b>bold</b>` |
| AT6 | `uv run pytest tests/test_blocks.py -k "layout or url"` | Exit 0; `validate_manifest` rejects: a `layout` id missing from `blocks`, a `blocks` key missing from `layout`, and a duplicated `layout` id (each `ValueError` with the pinned message shape); a `link_list` item and a `ContextLink` with `url: "javascript:alert(1)"` each raise `ValidationError` |
| AT7 | `uv run pytest tests/test_render_manifest.py -k sample_manifests` | Exit 0; both fixtures load as `Manifest`, pass `validate_manifest`, and `render_manifest` output contains all six `data-block-id` sections, with their byte offsets strictly increasing in `layout` order; the sample-builder page contains `Ship one artifact today`, the sample-recovery page contains `A good day`; each fixture's `version` is asserted equal to `sample-builder` / `sample-recovery` respectively |
| AT8 | `uv run pytest tests/test_render_manifest.py -k "offline or shell"` | Exit 0; the rendered page starts with `<!doctype html>`, contains `<meta name="viewport"`, an inline `<style>`, and the manifest version in `<title>` and `<h1>`; it contains no `<link`, no `<script`, no `<img`, no `@import`, and no `http` asset reference outside the pinned `link_list` hrefs |
| AT9 | `uv run pytest tests/test_render_manifest.py -k context` | Exit 0; with a context holding two free slots and one matching fact: `calendar_slots` renders both slot times and respects `max_slots: 1`; `insight_card` renders the matched fact's text under its `data-fact-id` and skips an unknown id without raising; with an empty context, `calendar_slots` shows `No free slots` and `insight_card` shows `No insight yet`; interactive attributes are present (`data-action="tick"` with the done item `checked`, five `data-action="checkin"` buttons, `data-action="focus-start"`, `data-action="thumb-up"`) |
| AT10 | `uv run pytest tests/test_render_manifest.py -k script` and `make check` | Exit 0 for both; the script test runs `main([])` against a temporary repo-root seam or asserts the two `wrote out/…` lines and that both files exist and contain their manifest version (the test must not write into the real `out/` — run it with the working tree's `out/` redirected via `tmp_path` and the pinned `parents[2]` resolution faked, or invoke `main` in a copied fixture tree); `make check`: `ruff check`, `ruff format --check`, `pyright` (strict on `framework/`), full `pytest` (including T3–T5 tests), `gitleaks git --redact` no leaks. No network in any test |
| AT11 | Negative control on the base tree: `uv run pytest tests/test_blocks.py` and `test -d framework/blocks` | Collection fails (no `framework.blocks` module) and `framework/blocks/` does not exist before the ticket, confirming the tests measure this ticket's work |

Additionally, before committing, the implementer records in the evidence note: the first line of `muse --version` run in the implementation session, and the `uv run pytest` counts per new test file. No Inspect log or mutant run applies (the gate is T8; this ticket only exposes what L0 will call).

## Risks

- **Jinja2 autoescape bypassed by accident.** A single `|safe`, `Markup(...)`, or hand-formatted HTML string reopens the hole AT5 samples. Mitigated by construction: `template.py` is the only HTML producer, block modules hold only template strings, and Success Criteria forbids the bypass spellings — the reviewer greps for `safe`, `Markup`, and f-string HTML in `framework/blocks/`.
- **`uv add jinja2` failing (offline registry).** Then step 2 stops and reports; the implementer must not silently switch to stdlib escaping. That switch changes the escaping guarantee from by-construction to per-site and needs a plan amendment plus a dedicated escaping-helper design (one `esc()` used in both text and attribute positions, `quote=True`).
- **`Manifest` not checking layout↔blocks agreement.** A manifest can be schema-valid yet unrenderable. Mitigated here: `validate_manifest` pins the three layout rules with deterministic messages (AT6), which is exactly what T8's L0 will surface as a structure failure.
- **Renderer signature drift breaking T8/T12.** T8 calls `validate_block`/`validate_manifest`; T12/T13 will parse the pinned `data-action`/`data-telemetry` attributes. Changing any pinned name, message, or attribute after this ticket is a breaking change for those tickets — they are therefore written literally in Approach, and AT9 asserts the interactive attributes.
- **`insight_card` fact lookup hiding errors.** Skipping unknown fact ids (rather than raising) is deliberate — a stale `fact_id` must not break the whole page at render time — but it can mask a bad manifest. Accepted for v0: validation still bounds `fact_ids` to 1–5 non-empty ids, and the empty state (`No insight yet`) is visible in the page.
- **Sample labels drifting into real personal data.** The fixtures are the public demo's seed. Mitigated by rule: synthetic text only, `.invalid` URLs only, profile files never loaded by code or tests, and the step-5 public-repo sweep.

## Test Plan

Committed tests are the deliverable: `tests/test_blocks.py` and `tests/test_render_manifest.py` over `tests/fixtures/sample-builder.json` and `tests/fixtures/sample-recovery.json`. Written before the blocks (step 3) so they fail on the base and pass on the branch, per the Definition of Done. No network in any test: Jinja2 renders from in-memory strings, fixtures are local JSON, and the script test redirects its output under `tmp_path` rather than the repo's real `out/`. No test reads `profiles/*.md` (sample plausibility is a fixture-authorship property, checked by eye in review, not by a test), `HIDDEN_CRITERIA_DIR`, the private companion repo, or any path outside the repo and `tmp_path`.

Test construction notes (so AT expectations are exact, not guesses): build manifests in tests via `Manifest.model_validate({...})` with `layout`/`blocks` mirroring the fixture shapes; build contexts via `RenderContext.model_validate({...})` with `Europe/Madrid`-aware datetimes (`ZoneInfo("Europe/Madrid")`, already used by `framework/store/`). AT5's assertions are substring checks on the rendered page (`&lt;script&gt;` present, `<script` absent — note the page shell itself contains no script element, so the absence check is exact). AT7's order check compares `page.index(f'data-block-id="{block_id}"')` across the fixture's `layout` list. Sequence: AT11 negative control, AT1–AT9 on the branch, AT10 (`make check`) last, then the commit contents check (`git show --stat HEAD` lists exactly the step-7 files; `git log --oneline main..HEAD` shows 1 commit; no upstream).

## Out of Scope

- The gate itself (Inspect L0/L1 tasks and the 7 mutants are T8 — this ticket only exposes `validate_block`/`validate_manifest`/`render_block` for L0 to call), Playwright rendering tests (SPEC §5.2 names them for L0 in T8), and any eval change.
- Wiring the interactive bits to telemetry or storage: no endpoints, no JavaScript, no `app.*` event emission — T12 (A0 cards, feedback) and T13 (telemetry, orchestrator) own that. This ticket emits only the pinned `data-*` hooks.
- The other four SPEC blocks (`habit`, `playlist`, `metric_chart`, `countdown`) and any C3 new-block machinery (T18); `playlist` is used in AT3 precisely as the unknown-type example.
- Deploying or serving the page (deployer is T12), the museum/`tour.json` rendering (T16/T17 — this page shell is not the museum), Glimmer fact production (T9 — `RenderContext.facts` arrives already derived), and any change to `Manifest`/`BlockConfig` or the exported JSON Schemas in `schemas/`.
- Loading or parsing `profiles/*.md` in code or tests; criteria (T10); live data of any kind.

## Open Questions

None. Assumptions: (1) the package is `framework/blocks/` with the ten pinned modules — the SPEC §8 root-level `blocks/` layout is deferred to the C3 era; (2) Jinja2 (new runtime dep via `uv add jinja2`) with autoescape is the templating choice, stdlib escaping rejected per Approach, and a `uv` failure stops the ticket for a plan amendment rather than a silent fallback; (3) inner config models validate `BlockConfig.config` through the registry — `manifest.py` is untouched and `type`/`dimension`/`rationale` are never redeclared inside a block config; (4) allowed dimensions, field bounds, sample configs, error-message strings, `data-action`/`data-telemetry` values, and the page shell are exactly as pinned in Approach — they are T8/T12/T13-facing contracts; (5) each rendering sample uses all six blocks exactly once, with `.invalid` URLs and synthetic labels only, is named `sample-builder`/`sample-recovery` with matching `version`, and is never a day-0 or deployed manifest (see Approved amendment); (6) `link_list` renders config links only and `context.links` is unconsumed in v0; (7) `insight_card` skips unknown fact ids and `calendar_slots` renders slots in caller order without timezone conversion; (8) the render script takes no arguments, resolves fixtures from `Path(__file__).resolve().parents[2]`, and writes only under the gitignored `out/`.

Approved amendment (2026-10-29): the two fixtures are rendering samples, not day-0 manifests. They are renamed `tests/fixtures/sample-builder.json` and `tests/fixtures/sample-recovery.json` with manifest versions `"sample-builder"` / `"sample-recovery"`, the render script writes `out/sample-builder.html` and `out/sample-recovery.html`, and AT7 and the commit file list use those names. Day 0 starts both profiles from one shared, byte-identical seed manifest (SPEC §9), created in T13; these fixtures are never deployed. The implementation evidence note (`docs/sessions/006-blocks-renderer.md`) repeats that sentence as a standalone `rationale`-free note. All other assumptions are accepted as written.
