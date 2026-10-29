# Contributions

## Ticket 1 — toolchain (2026-10-27)

Built on branch `t1-toolchain` per [docs/plans/001-toolchain.md](docs/plans/001-toolchain.md):
`uv` project on Python 3.12, package skeleton, `Makefile` (`check`/`test`/`eval`/`demo`),
hello Inspect eval on the mock model, pre-commit, `.env.example`, GitHub Actions CI,
this file, `LICENSE`, and `README.md`.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Ticket 2 — SPEC v0.4 (2026-10-29)

Built on branch `t2-spec-v04` per [docs/plans/002-spec-v04.md](docs/plans/002-spec-v04.md):
`docs/SPEC.md` moved to v0.4 (decisions D1–D10), new `docs/PLAN.md`, new
`docs/MUSEUM-CONTRACT.md` (verbatim except ruff formatting of its Python snippet), and the two objective profiles
(`profiles/builder.md`, `profiles/recovery.md`) committed unchanged.

Plan and implementation: muse-wonder-1.0 (effort high), in Muse Code.

## Ticket 3 — core schemas (2026-10-29)

Built on branch `t3-core-schemas` per [docs/plans/003-core-schemas.md](docs/plans/003-core-schemas.md):
Pydantic v2 core schemas in `framework/schemas/` (Event envelope with discriminated
`data` union for 21 event types, Fact, Profile, Criterion, Manifest/BlockConfig,
Decision), JSON Schema exports in `schemas/`, round-trip/rejection/drift tests,
and the README Status section.

Plan and implementation: muse-wonder-1.0 (effort high), in Muse Code.

## Ticket 4 — event store and collector framework (2026-10-29)

Built on branch `t4-event-store` per [docs/plans/004-event-store.md](docs/plans/004-event-store.md):
append-only SQLite event store in `framework/store/` (stdlib `sqlite3` only:
`events` with `UNIQUE (source, source_id)` plus trigger-blocked `UPDATE`,
`cursors`, `batch_hashes`, `conflicts`), `Collector` protocol with the
append-only `source_id` contract, transactional `run_collector` returning
`(inserted, conflicts)`, `FixtureCollector` over synthetic JSONL,
`daily_batch_hash` on Europe/Madrid days, `events_between`, and the only
delete path `purge_before`, with store and collector tests.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Ticket 5 — collectors wave 1 (2026-10-29)

Built on branch `t5-collectors-wave1` per [docs/plans/005-collectors-wave1.md](docs/plans/005-collectors-wave1.md):
three deterministic collectors in `framework/collectors/` implementing the T4
`Collector` protocol (Calendar over a secret iCal URL with `icalendar` +
`recurring-ical-events` expansion, GitHub own-activity with ETag cursor and
`ikigai-loop` exclusion, public build feed from HF daily papers / HN top
stories / GitHub new-and-rising repos emitted once per Europe/Madrid day),
plus a `python -m framework.collectors run <name>` CLI that prints only
`inserted=<n> conflicts=<n>`. HTTP stays stdlib `urllib`; all tests are
offline on synthetic fixtures, and no live poll was run.

Amendment 4 (same branch, second commit, same models/efforts):
`CalendarIcsCollector(label="personal")` with `name = calendar-<label>`,
per-label `ICAL_URL_<LABEL>` env vars (legacy `ICAL_URL` fallback for
`personal` only), `run calendar [--label <label>]`, and
`ICAL_URL_PERSONAL=`/`ICAL_URL_HOME=` in `.env.example`.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Ticket 6 — blocks v0 and renderer (2026-10-29)

Built on branch `t6-blocks-renderer` per [docs/plans/006-blocks-renderer.md](docs/plans/006-blocks-renderer.md):
six block types in `framework/blocks/` (`checklist`, `focus_session`,
`checkin`, `calendar_slots`, `insight_card`, `link_list`), each with a
frozen Pydantic inner config validated against the existing
`BlockConfig` envelope, a pure Jinja2-autoescaped renderer (new runtime
dep `jinja2`), an allowed-dimension set, and an L0 sample; a registry
with `validate_block`/`validate_manifest`/`render_block` as the L0
entry points T8 will call; `render_manifest` for a full offline HTML
page from display-ready `RenderContext` data only; two rendering-sample
fixtures (`tests/fixtures/sample-builder.json`,
`tests/fixtures/sample-recovery.json`, never deployed — day 0 starts
both profiles from one shared seed manifest created in T13) rendered by
`python -m framework.blocks` to gitignored `out/`, plus registry and
page tests.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Ticket 7 — collectors wave 2 (2026-10-29)

Built on branch `t7-collectors-wave2` per [docs/plans/007-collectors-wave2.md](docs/plans/007-collectors-wave2.md):
`HealthDailyData` gains optional `daylight_min` (schema JSONs regenerated);
SPEC D3 moves iPhone Screen Time from Won't to Could (via the ActivityWatch
Screen Time import, category minutes only) while Email stays Won't;
`SpotifyCollector` (`spotify@0.1.0`) with a per-poll refresh-token POST and
`after_ms` cursor over `music.play` events; `ActivityWatchCollector`
(`activitywatch@0.1.0`) as a push source building `screen.hour` per-category
minutes over the last 48 complete UTC hours with AFK clipping and the pinned
category table (titles and URLs dropped at the collector); a single stdlib
`ingest.py` server with `POST /health/daily` (yesterday-in-Madrid dating,
content-hash `source_id`, corrected re-posts supersede) and
`POST /events/screen-hour` behind a required `INGEST_TOKEN` bearer; CLI
`run spotify`, `push activitywatch`, `ingest-health`, `serve-ingest`; the
`http_post` seam in `common.py`; `ops/health-shortcut.md` and
`ops/spotify-auth.md`; offline tests on synthetic fixtures only. No live
poll, live Shortcut POST, or live push was run.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## AI assistance outside the Muse family

- **Claude Code (Anthropic)** was used as an advisor and reviewer. It co-drafted the
  planning documents (SPEC.md, the pitch, docs/WORKFLOW.md) and helped structure the ikigai profiles from my interview answers; it reviewed plans and diffs,
  and ran feasibility checks on Oct 27 outside this repo (one call each to Muse Glimmer,
  Muse Wonder and Muse Code, plus an Inspect AI hello-world).
- It wrote no code in this repository and made no commits. All code here was produced
  by Carlos with Muse Code, as summarised in `docs/sessions/`.
