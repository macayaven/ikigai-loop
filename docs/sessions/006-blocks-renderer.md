# Session evidence — 006-blocks-renderer (2026-10-29)

Ticket 6 only; two sessions per ticket (plan, then implementation). This
note summarises the work; the raw redacted export is kept privately and
published only if gitleaks plus a manual check of names and context is
clean.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Plan

- Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3
  (effort medium), in Muse Code.
- Approved amendment included: the two fixtures are rendering samples,
  not day-0 manifests — renamed `tests/fixtures/sample-builder.json`
  and `tests/fixtures/sample-recovery.json` with manifest versions
  `"sample-builder"` / `"sample-recovery"`, the render script writes
  `out/sample-builder.html` and `out/sample-recovery.html`, and AT7
  and the commit file list use those names.

## Implementation

- Files: `docs/plans/006-blocks-renderer.md` (committed with the
  implementation; whitespace-only `ruff format` inside its code fences,
  same precedent as ticket 5), `framework/blocks/` (`__init__.py`,
  `context.py`, `template.py`, `checklist.py`, `focus_session.py`,
  `checkin.py`, `calendar_slots.py`, `insight_card.py`, `link_list.py`,
  `registry.py`, `render.py`, `__main__.py`), `tests/test_blocks.py`
  (7 tests), `tests/test_render_manifest.py` (6 tests),
  `tests/fixtures/sample-builder.json`,
  `tests/fixtures/sample-recovery.json`, `pyproject.toml` + `uv.lock`
  (via `uv add jinja2`, no hand edits), `.gitignore` (`out/` under a
  `# rendered samples` comment), `CONTRIBUTIONS.md` (Ticket 6 entry),
  this file.
- Tests were written first and failed at collection with no
  `framework.blocks` module before the blocks existed (AT11).
- Deviations from the plan's letter, all behaviour-preserving: (1) the
  plan's `url.startswith("http://") or url.startswith("https://")` is
  written as `url.startswith(("http://", "https://"))` — identical
  exact-prefix semantics, required by ruff UP038; (2) the three
  `RenderContext` list fields use `Field(default_factory=list[Model])`
  instead of `Field(default_factory=list)` — runtime-identical
  (`list[Model]()` is `[]`), required so pyright strict sees no
  `Unknown` element type; (3) `BlockDefinition.config_model` is
  annotated as the string `"type[SchemaModel]"` — the field named
  `type` shadows the builtin inside the class body, and the quoted
  form resolves to the same builtin at module scope
  (reportInvalidTypeForm otherwise); (4) `ruff format` whitespace
  inside the plan's code fences, as in ticket 5; (5) page assembly:
  a single shell template would escape the already-rendered fragments
  under `autoescape=True`, so `render_manifest` concatenates complete
  `render_fragment` outputs (head, one fragment per block in layout
  order, changelog entries, tail) — every user string is still
  escaped at fragment-render time, and `framework/blocks/` contains
  no `|safe`, `Markup`, or f-string HTML; (6) `render_block` fills the
  section's `data-dimension` from the validated `BlockConfig`
  (closed `Dimension` literal set, injection-impossible) because the
  pinned renderer signature `(block_id, config, context)` cannot see
  it — renderers emit the placeholder the registry fills, so the
  contract "section attributes come from the BlockConfig" holds on
  every registry-rendered fragment.

## Acceptance tests

- AT1 passed: `sample` — 2 passed; all six samples validate and render
  with their `data-block-type` and label.
- AT2 passed: `invalid_config` — 1 passed; the six pinned bad configs
  plus the wrong-type case raise `ValidationError`.
- AT3 passed: `unknown_type` — 1 passed; `playlist` raises `ValueError`
  with message `unknown block type: playlist`.
- AT4 passed: `dimension` — 2 passed; the five disallowed pairs raise
  `ValueError` naming dimension and type; every sample dimension is
  inside its allowed set.
- AT5 passed: `escap` — 1 passed; `<script>` label and `<b>` fact text
  render escaped, no literal `<script` anywhere.
- AT6 passed: `layout or url` — 2 passed; the three layout rejections
  carry the pinned messages; `javascript:` URLs raise in both
  `LinkItem` and `ContextLink`.
- AT7 passed: `sample_manifests` — 1 passed; both fixtures load,
  validate, and render all six sections in layout order with the
  pinned markers.
- AT8 passed: `offline or shell` — 1 passed; doctype shell, viewport,
  inline style, version in title/h1; no link/script/img/import and no
  `http` outside link hrefs.
- AT9 passed: `context` — 1 passed; slots render and respect
  `max_slots`, insight matches/skips facts, empty states show, all
  pinned `data-action` attributes present.
- AT10 passed: `script` — 2 passed; `main([])` prints exactly the two
  `wrote out/…` lines into a `tmp_path` repo root (never the real
  `out/`), both files exist with their versions; unexpected argument
  exits 2. `make check` green — ruff, ruff format, pyright strict on
  `framework/` with 0 errors, full pytest 113 passed (13 new + 100
  pre-existing), gitleaks no leaks. No network in any test.
- AT11 passed (negative control on the base tree): collection failed
  with no `framework.blocks` module and `framework/blocks/` did not
  exist.
- Per-file pytest counts on the branch: `test_blocks.py` 7,
  `test_render_manifest.py` 6.
- The script was run once for real (`uv run python -m
  framework.blocks`); both `out/*.html` pages were read back and read
  sensibly at a narrow width. `out/` stays untracked (gitignored).

## Notes

- Public-repo sweep over every touched file: no real names, real URLs
  (only `https://example.invalid/…` links plus the `http://`/`https://`
  scheme literals in the URL validator), profile text copied verbatim,
  private paths, or secrets. No `|safe`, `Markup`, or f-string HTML in
  `framework/blocks/`.
- No eval or block changed beyond this ticket's own, so no Inspect log
  or mutant run applies (the gate is T8; this ticket only exposes what
  L0 will call).
- Nothing read the path in `HIDDEN_CRITERIA_DIR`, `profiles/*.md`, or
  the private companion repo.
- Raw redacted export kept privately.

Day 0 starts both profiles from one shared, byte-identical seed manifest (SPEC §9), created in T13; these fixtures are never deployed.
