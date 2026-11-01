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

## Ticket 8 — briefing gate (2026-10-31)

Built on branch `t8-briefing-gate` per [docs/plans/008-briefing-gate.md](docs/plans/008-briefing-gate.md):
the artifact changes from a mutating app to a gated briefing (conflicts
C1–C6 with SPEC/PLAN recorded in the plan, neither file edited):
`framework/briefing/` with the `Briefing` Pydantic schema (JSON Schemas
exported, drift-tested), the pure deterministic gate
(`evaluate_briefing`, no network, no model call, no env/clock read —
L0 structure, L1 rules, L1b reconciliation against reference data), and
`evals/` Inspect tasks with deterministic scorers on `mockllm/model`;
the pytest meta-eval catches all 16 named mutants with their stable
violation codes and passes all 12 known-good synthetic briefings with
0 false rejections. Also the `push activitywatch` count label fix
(`conflicts=` to `noop=`) and the time-bounded evening-window wording in
`profiles/builder.md`. Evidence in
[docs/sessions/008-briefing-gate.md](docs/sessions/008-briefing-gate.md).

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Docs reconcile (2026-11-01)

Built on branch `docs-reconcile`: `README.md` rewritten around the current entry pitch (first person, about 60 lines, with built/not-built status, the no-medical-advice line, the hackathon record, and the off-the-card-path list); `profiles/recovery.md` moved to `profiles/disconnect.md` and rewritten for family time with screens off; `profiles/builder.md` trimmed to the card path (calendar as busy intervals and `iki-*` tags, Low energy and Pace rows and criteria gone); superseded notes in `docs/SPEC.md`, `docs/PLAN.md`, `docs/MUSEUM-CONTRACT.md` and `docs/WORKFLOW.md`; card-path comments in three framework docstrings; the `AGENTS.md` Mission paragraph now matches the README and points at it, with every rule in that file unchanged. Docs and comments only: no behaviour, schema, fixture or test change. Why: the README still pitched two diverging apps and the second profile read as a health advisor, and neither is the entry any more. Ticket 8's review added M17–M20, so the gate has the 20 mutants the README counts where the Ticket 8 entry above says 16.

Prompts and review by Claude Code. Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Ticket 10 — commitments and gate additions (2026-11-01)

Built on branch `t10-commitments` per [docs/plans/010-commitments-gate.md](docs/plans/010-commitments-gate.md): a typed `Commitment` set loaded fail closed from `IKIGAI_COMMITMENTS_FILE` with a 14-entry synthetic example file as the only registry, actions bound to commitments by id with matching wording and `commitment_id` required on `Action`, an advice scan, wider number tokens, and claim-to-metric binding over label, period word and direction with nine new violation codes, plus this repo counted as build evidence with the no-target guard kept and the old Profile B id renamed to `disconnect` in code ids and fixtures. The pytest meta-eval now catches all 38 named mutants with their stable violation codes and passes all 20 known-good synthetic briefings. Evidence in [docs/sessions/010-commitments-gate.md](docs/sessions/010-commitments-gate.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Ticket 9 — Glimmer fact layer (2026-11-01)

Built on branch `t9-glimmer-facts` per [docs/plans/009-glimmer-facts.md](docs/plans/009-glimmer-facts.md):
the two-pass fact layer later tickets call from `run_cycle`. A pure core
`extract_facts` (allowlist-first filtering, logical-key winners, deterministic
`MetricSnapshot` plus three-period rollup with no model, isolated personal and
feed model passes, deterministic checks, content-hash IDs with core-minted
tiers), the stdlib OpenAI-compatible edge client (content only, sanitised
model ID), append-only `cycles`/`facts`/`cycle_responses` in the existing DB
file with byte-identical replay as a no-op, the `run_cycle` seam, the
counts-only `python -m framework.cycle facts` CLI, and the Inspect replay task
with the 6-known-good / 24-mutant meta-eval. Offline tests on synthetic
fixtures, plus one seeded live run against Muse Glimmer on synthetic rows; the
real-data run is still pending. Evidence in
[docs/sessions/009-glimmer-facts.md](docs/sessions/009-glimmer-facts.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high), in an interactive session I ran, which also wrote a first draft of four files before I stopped it. Implementation and fixes: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Ticket 9b — code facts (2026-11-01)

Built on branch `t9b-code-facts` per [docs/plans/009b-code-facts.md](docs/plans/009b-code-facts.md):
code facts for the Glimmer fact layer. A pure `framework/glimmer/code_facts.py`
reports the largest change in each of five families (screen hours, pushes, PRs,
calendar tag hours, cancelled blocks) with pinned templates, floors, and
evidence; the snapshot writes explicit zero keys so "from 0" cites a real key;
code facts come first, outside the model cap, and model repeats drop as
duplicates; the store records a per-fact code/model origin with a migration;
and `extract_facts` gains `personal_pass`/`feed_pass` flags with matching CLI
switches, so a cycle still returns code facts when the model fails or is off.
The fact check lets a count of cited rows back a number only when every cited
row is a feed item; `other` and `system` never win the screen family while
staying in the snapshot; and `ai` prints as `AI`.
The 6-known-good / 24-mutant meta-eval is re-baselined by hand with no new
cases. Claude Code ran one live cycle on synthetic rows outside the Muse sessions; the real-data run is still pending.
Evidence in [docs/sessions/009b-code-facts.md](docs/sessions/009b-code-facts.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation and fixes: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Ticket 15a — learner core (2026-11-01)

Built on branch `t15-learner` per [docs/plans/015-learner.md](docs/plans/015-learner.md):
`framework/learner/`, a pure package that turns card rulings into per-slot
preference counts, scores four predictors before each posterior-moving
ruling, ranks commitments for the proposal prompt, and runs the
known-preference test on simulated rulings. Evidence in
[docs/sessions/015-learner.md](docs/sessions/015-learner.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Pre-registration (2026-11-01)

Built on branch `prereg`: [docs/PREREG.md](docs/PREREG.md) pre-registers the Nov 2-4 live run (questions, design, receipts table, ruling split, R3 pass rules, base scenario, 20 pairs, completion rules, limits); [evals/r3_pairs.json](evals/r3_pairs.json) holds the base scenario and the 20 pairs with `apply_ops` in [evals/r3_scenario.py](evals/r3_scenario.py) as the exact code the later harness uses; [tests/test_r3_pairs.py](tests/test_r3_pairs.py) pins the shape, checks the JSON against the document table by table, and checks every arm through the gate with one claim per fact; `make eval` runs every Inspect task file in `EVAL_FILES` on the mock model through [evals/run_tasks.py](evals/run_tasks.py), which fails on an errored task or any incorrect sample, with [tests/test_eval_tasks.py](tests/test_eval_tasks.py) pinning the listing; `make demo` replays the M12 rejection offline via [evals/demo_rejection.py](evals/demo_rejection.py), covered by [tests/test_demo_rejection.py](tests/test_demo_rejection.py). Evidence in [docs/sessions/prereg.md](docs/sessions/prereg.md).

The text of docs/PREREG.md was drafted by Claude Code and adopted by me. The ruling split in it is my own forecast, which I gave on Nov 1. Claude Code's review sent the first session's output back for the runner, the per-fact gate check, the document-match test and the demo derived from the M12 case. The amendment corrected the I7 row and the wording points the review had left open, and removed the I7 marker, so no open items remain. The session note lists the decisions.

Prompts and review by Claude Code. Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## Ticket 7b — screen categories (2026-11-01)

Built on branch `t7b-screen-categories`: the ActivityWatch `CATEGORY_TABLE`
gains an `ai` category after `code` and a `system` category last, and the
comms needle `telegram` becomes `telegra` so the iOS bundle id matches too;
tests pin every added needle, the code/system ordering wins, and the gate
pass for both new categories. Also records the Ticket 9 real-store run line
in [docs/sessions/009-glimmer-facts.md](docs/sessions/009-glimmer-facts.md).
It also bumps the collector version to `activitywatch@0.2.0` for the new
category table. The push path already prints `inserted=N noop=M` (Ticket 8),
with a CLI test pinning it, so no log-label change was needed.

Prompts and review by Claude Code. Implementation by muse-spark-1.3, in Muse Code, in a headless session Claude Code started.

## Ticket 12 — Telegram card (2026-11-01)

Built on branch `t12-telegram-card` per [docs/plans/012-telegram-card.md](docs/plans/012-telegram-card.md):
`framework/telegram/`, one photo card with a chart and buttons, taps stored as
`app.tap`, long polling with no public endpoint, and a seam for voice notes;
`docs/PRIVACY.md`; and `pillow` as one new dependency for the chart. Claude Code
ran the live test against the real Bot API outside the Muse sessions, with a
sample card labelled synthetic. Evidence in
[docs/sessions/012-telegram-card.md](docs/sessions/012-telegram-card.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

Follow-up: I gave `Something's wrong` its own row in both keyboards; prompts and review by Claude Code, implementation: muse-spark-1.3 (effort medium), in Muse Code, in a headless session Claude Code started.

## Ticket 9d — pull request counted once (2026-11-01)

Built on branch `t9d-pr-count`: one `github.pr` row exists per action, so an
opened-plus-merged pull request counted 2. New `is_opened_pr` helper in
`framework/glimmer/metrics.py` (a row counts only on `opened` above 0) now
gates all three sites — the period rollup, the `github.pr.count` window
value, and the `prs` code-fact pool, whose evidence cites only opened rows.
The `pr_event` fixture default changed from `{"prs": 1}` to `{"opened": 1}`;
no schema, collector, stored-row, or push change. 9 new tests (4 metrics, 5
code facts including both briefing-gate citation forms); README counts moved
to 279 and 57. Evidence in
[docs/sessions/009d-pr-count.md](docs/sessions/009d-pr-count.md).

Prompt and review by Claude Code. Implementation by muse-spark-1.3, in Muse Code, in a headless session Claude Code started.

## Ticket 17a — verify_claims (2026-11-01)

Built on branch `t17a-verify-claims` per [docs/plans/017a-verify-claims.md](docs/plans/017a-verify-claims.md):
`framework/verify/`, a public `verify_claims` API and `verify-claims` CLI over
plain JSON that reuse the gate's checks, with a parity test against the gate's
own cases; a general `repair_loop`; a static page at `docs/verify/` that runs
the same Python in the visitor's browser through Pyodide; a worked example in
`examples/verify/`; an adapter recipe in `docs/ADAPTER.md`, whose `adapter.py`
and `test_adapter.py` are the output of one live Muse Code run with only
`ruff format` after it; a `Check your own agent` section in the README; and
packaging with pydantic as the only runtime dependency. Claude Code ran the
browser passes and the live recipe outside the implementation sessions, on
synthetic data. A follow-up said what the page takes on its first line, listed the checker as built in the README, and recorded the Nov 1 live check, prompted and reviewed by Claude Code and implemented in Muse Code in a headless session Claude Code started.

Evidence in [docs/sessions/017a-verify-claims.md](docs/sessions/017a-verify-claims.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started. I asked for a second follow-up so the page opens with a labelled made-up example already run; prompts and review by Claude Code, implementation: muse-spark-1.3 (effort medium), in Muse Code, in a headless session Claude Code started.

## Docs 2 — literature check and deviations (2026-11-01)

[docs/LITERATURE.md](docs/LITERATURE.md), dated Deviations in [docs/PREREG.md](docs/PREREG.md), a note at SPEC §5.1 and two README lines.

GPT Sol 6.1, through Codex, checked every citation and proposed the deviations. Claude Code re-read 15 sources and drafted the text. Muse Code placed it. Implementation: muse-spark-1.3 (effort medium), in a headless session Claude Code started.

## Ticket 11 — Wonder proposal step (2026-11-01)

Built on branch `t11-wonder-proposal` per [docs/plans/011-wonder-proposal.md](docs/plans/011-wonder-proposal.md): the guarded Wonder call that turns a cycle into one proposal per goal. `framework/proposal/` holds the pure core (narrow draft and fallback schemas with a hand-built per-call response schema, free-hour picking over the slot's local day, offerable current-minus-parent deltas, the exact prompt with a one-pass filler, draft-to-briefing assembly, and `propose` with its pre-send scan, one retry on the violations, and labelled fallback or noop outcomes) plus the headless Muse Code transport `framework/proposal/muse_client.py` as the default (with `--preset empty`, because the default preset hands the model file tools that read outside the workspace), `framework/proposal/defaults.py` for the product's default model and effort, and the Model API `MetaClient`, still in the code for anyone with a key, which scans every outbound request with that request's forbidden literals and never logs the key. It imports `repair_loop` from Ticket 17a's `framework/verify/`, `framework/store/proposal_store.py` holds the append-only attempts and results with the first-draft failure report, and `framework/cycle/` holds the `run_proposals` seam and the `propose` CLI. The pytest meta-eval replays 37 scripted cases (P1-P37) through the real core and gate, and `make eval` adds the 37-sample replay task, all green on the mock model. Review found sixteen problems and I fixed them with tests first: the clock flags parse before any store opens with fixed errors, contributor refusal runs first, a foreign cycle id fails like an unknown one, stale and parent-without-deltas codes survive on every result exactly once, the policy block is marker-stripped, the report counts fallbacks and noops per model, the client re-sends once on a dropped connection, and the prompt carries the measured first-claim, number, period, hours, comparison, and positive-wording rules. A later review round added five more, fixed the same way: the two measured prompt lines restored exactly, `URLError`-wrapped drops re-sent under the same rules, newline claims failed as non-plain, and minus zero stripped of its sign. Moving to Muse Code found eight more, fixed the same way, with the numbers in [docs/sessions/011-wonder-proposal.md](docs/sessions/011-wonder-proposal.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started; the last sessions ran in Contributor mode, on this public repo and made-up data only. Claude Code ran the live measurements outside those sessions, on made-up data.

## Ticket 9c — Glimmer calendar labels (2026-11-01)

Built on branch `t9c-glimmer-labels` per [docs/plans/009c-glimmer-labels.md](docs/plans/009c-glimmer-labels.md): the closed 8-label set defined once in `framework/schemas/events.py` with `CalendarLabelData` as a new `calendar.label` event type; the in-memory tag overlay in `framework/glimmer/labels.py` with `iki-care` kept out of every prompt, snapshot, rollup, and fact; the pinned prompt, strict two-shape parser, private-endpoint guard, and per-title queue in `framework/glimmer/label_step.py`; the collector tag boundary fix plus the in-memory title sink; the label sweep in `framework/cycle/labels.py` behind the off-by-default `labels` subcommand; the frozen keyword baseline in `evals/r10_keywords.py`; the gated R10 runner in `evals/r10.py`; five new test files plus additions to three existing ones, all on synthetic titles with fakes instead of any network; and the docs (the calendar section of `docs/PRIVACY.md`, the README Status line, the profile lines, this entry). Evidence in [docs/sessions/009c-glimmer-labels.md](docs/sessions/009c-glimmer-labels.md).

R10 on the frozen set, one pass: `model correct: 77/80 strict: 77/80`, `keywords correct: 51/80 strict: 50/80`, `decision: eligible`. Claude Code started the run, and the switch stays off in this repo.

On Ticket 11's main, `forbidden_literals_for` in `framework/cycle/__init__.py` also returns the internal-only labels, so the outbound scan is a second check behind the strip in `extract_facts`.

`evals/r10_cases.json` isn't Muse Code's: a separate Claude Code agent wrote those 80 invented titles and froze them by hash before the plan was written, so no session writing the prompt, the list or the rule could see them. `evals/r10_results/` is the runner's output, with `seconds` rounded in one file as the session note says.

Two outside reviewers, GPT Sol 6.1 through Codex and Gemini 4 Argon, read the set read-only before it went public. The notice in `evals/README.md` was Sol's suggestion, and no entry changed. Argon asked to replace four care titles and rename two people; I declined, because rewriting cases after seeing results would break the claim that they were frozen first.

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.

## AI assistance outside the Muse family

- **Claude Code (Anthropic)** was used as an advisor and reviewer. It co-drafted the
  planning documents (SPEC.md, the pitch, docs/WORKFLOW.md) and helped structure the ikigai profiles from my interview answers; it reviewed plans and diffs,
  and ran feasibility checks on Oct 27 outside this repo (one call each to Muse Glimmer,
  Muse Wonder and Muse Code, plus an Inspect AI hello-world).
- Claude Code doesn't edit files or make branch commits in this repository; those are Muse Code's, as summarised in `docs/sessions/`. The exception is the held-out test sets a ticket's entry names. Its prompts sometimes spelled out a small fix in a few lines of code, or exact wording for a doc or session note, and Muse Code applied them. The largest such code blocks I found are about a dozen lines, in Tickets 9, 9b, 15a and 17a. Through Oct 31 I ran every Muse Code session myself. From Nov 1, at my request, Claude Code also wrote the prompts, started and supervised the Muse Code sessions and reviewed their output. It also runs pushes and squash merges, so the merge commits on main come from those.
- **GPT Sol 6.1 and GPT Astra 6 (OpenAI), through Codex,** reviewed this project read-only on Nov 1: literature, code, demo plan, failure modes and launch plan. They wrote nothing in this repository. Findings that changed something are credited in the ticket that used them.
