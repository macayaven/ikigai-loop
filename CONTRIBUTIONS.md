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

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started. I asked for a second follow-up so the page opens with a labelled made-up example already run; prompts and review by Claude Code, implementation: muse-spark-1.3 (effort medium), in Muse Code, in a headless session Claude Code started. I asked for a third follow-up after a friend couldn't use the page, so a stranger can check a sentence of their own without JSON, with a plain-words verdict, a sentence box and a records table, and the page's own Python in docs/verify/verify_page.py, the checker itself unchanged; prompts and review by Claude Code, whose prompts gave several of the page's lines word for word; implementation and three fix rounds on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only; three no-context reviews of screenshots on muse-wonder-1.0 (effort high), each in an empty folder.

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

## Ticket 9e — facts match the clock (2026-11-01)

Built on branch `t9e-clock` per [docs/plans/009e-facts-match-the-clock.md](docs/plans/009e-facts-match-the-clock.md):
eleven clock fixes across the Glimmer fact layer and its collectors, so each
number means what its sentence says. Whole-hour cuts at `floor_hour(as_of)`
with the open hour counted on the next card and its zero dropped from facts
and the snapshot; busy and tag hours as unions of clipped intervals;
per-calendar reconcile with cross-calendar combine and the moved-block rule;
content-or-stamp calendar diff with revision identities and the empty-feed
guard; three-page GitHub paging; the `system` screen check arm with the
one-item grammar fix in code; and by-order period binding. New
`tests/test_glimmer_clock.py` plus cases in the calendar, checks and GitHub
suites, with the affected expectations re-derived by hand. Evidence in
[docs/sessions/009e-facts-match-the-clock.md](docs/sessions/009e-facts-match-the-clock.md).

These findings came from independent reviews by GPT Sol 6.1, run through Codex, and by Muse Wonder Full (items 8, 9, 10; items 1 to 4 were found by both), reproduced by Claude Code, and implemented by Muse Code.

Item 11, the moved block, was found by Claude Code during plan review and reproduced the same way.

Prompts and review by Claude Code. Plan: muse-wonder-full-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started. The commit step, the move onto main and the final text fixes ran on muse-spark-1.3 at effort low.
## Ticket 16b — models on the gate (R1b)

Built on branch `r1b-models` per [docs/plans/016b-models-on-the-gate.md](docs/plans/016b-models-on-the-gate.md):
the benchmark that puts five rows through the same gate on one fixed synthetic set.
`evals/r1b.py` (case loader, arm registry with exactly `product` and `plain`,
pinned five-row matrix, live-run loop with resume, re-gate through `propose`
with a replay client, and the kept-draft pick), `evals/r1b_prompts.py` (the
plain prompt that teaches none of the gate's rules, with byte-identical data
blocks, plus the constraint-free plain schema), `evals/r1b_clients.py` (the
prompt/schema swapping wrapper, the local endpoint adapter over Ticket 9c's
merged `response_format` argument, the re-gate replay client),
`evals/r1b_summary.py` (fixed preamble, absolute counts, paired comparison
with McNemar's exact test as a descriptive statistic, the mechanical threefold
verdict per row plus the one overall line), `evals/r1b_cases.json` (54 cases:
6 clean and 6 in each of 8 trap classes, in balanced rounds), the append-only
rows in `evals/results/r1b/`, the kept draft in `evals/demo_real_rejection.json`
when one qualifies, `docs/r1b.md` generated by `--summary`, the `make r1b`
target, and six pytest files (`tests/test_r1b_cases.py`,
`tests/test_r1b_prompts.py`, `tests/test_r1b_runner.py`,
`tests/test_r1b_summary.py`, `tests/test_r1b_pick.py`,
`tests/test_r1b_clients.py`) with three fixtures. I changed nothing under
`framework/`. Headline first-draft gate failures per row and arm, product
then plain, out of 54 counted first drafts: muse-wonder-1.0 (high) 1/44,
muse-wonder-full-1.0 (high, subscription-only, Power or Maximum) 0/43,
muse-spark-1.3 (medium) 0/36, muse-spark-1.3 (low) 1/27. The muse-glimmer-30b
row is still running under the same gate and follows as data.

The case set came from two author sessions, both on muse-wonder-full-1.0
at high: a first session wrote a set from a script that drew on pools of
stock sentences, and Claude Code rejected that file before any arm ran because its
facts had nothing to do with its commitments, so no model under test ever
saw it; a second fresh session, in Contributor mode on made-up data, in a
new empty folder holding only the case-author description, was told to stay
in that folder, to write every case by hand with no generator and no pooled
sentence, and that a pooled set had already been rejected, and it wrote the
54 cases with reminder agents off. Claude Code read that session's log: every
path it touched was inside that folder, and it wrote no generator. That
session then replaced two fact statements, in r1b-011 and r1b-028, because
the private-term scan Claude Code runs on public files hit a word in them, before any
arm ran. That session never saw this repository, the gate's source, the
product prompt or any result, and that model is also one of the arms, with
no memory across sessions; the file's sha256 was recorded right after, and
every result row carries it. Evidence in
[docs/sessions/016b-models-on-the-gate.md](docs/sessions/016b-models-on-the-gate.md).

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium). Mechanical steps: muse-spark-1.3 (effort low). Case set: muse-wonder-full-1.0 (effort high), as described above. Prompts and review by Claude Code. Sessions headless, started by Claude Code, in Contributor mode on made-up data. The benchmark's own model calls ran from Claude Code's shell through MuseExecClient in Standard mode, and the local row through Ticket 9's client.

## Ticket 13 — orchestrator (2026-11-02)

Built on branch `t13-orchestrator` per [docs/plans/013-orchestrator.md](docs/plans/013-orchestrator.md):
`python -m framework.cycle run-slot` runs one pinned Madrid slot from facts to
delivered card: code facts first in-process, the local model as a killable
child, one guarded Wonder call per allowed goal through headless Muse Code, the
card, the send, and an append-only ledger in the same database file. The card
never waits for a hung model: the local model's time ends four minutes before
the slot and Wonder's 30 s before it, with a labelled fallback stored by then.
A send whose delivery is unknown never retries by itself; `check-slot`
explains a slot or exits non-zero; `trace` shows what a card rests on;
`rehearse` sends one TEST card for a real tap. Evidence in
[docs/sessions/013-orchestrator.md](docs/sessions/013-orchestrator.md).

Prompts and review by Claude Code. Plan on muse-wonder-1.0 (effort high), implementation on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only, and Claude Code ran the live exercise outside those sessions, on made-up data.

The finding that a blind send retry could deliver a card twice, and the finding that a hung model could hold a card past its slot, came from independent reviews by GPT Sol 6.1, run through Codex. The check of D11 that found the redirect path came from a finding by GPT Terra 6.1, run through Codex. The fix that reads a parent from the delivered card came from Muse Wonder Full's blind review of Ticket 11, which also raised the three other items this ticket checked. The finding that the since line could read a late-collected batch as new came from a source-to-card audit Claude Code ran.

## Ticket 21 — try it (2026-11-02)

Built on branch `n1-try-it` per [docs/plans/021-try-it.md](docs/plans/021-try-it.md):
`try-ikigai` replays packaged made-up data through the real fact layer with
both model passes off, the real proposal step and gate against hand-written
replies in the model's shape, ticket 13's card builder and chart, and the
real keyboards, and prints a five-section story: the card, the simulated tap,
a planted wrong number the gate stops and corrects on the one retry, the rows
behind one sentence, and the checker for the reader's own agent. No model,
network, store or Telegram client runs; `pillow`, `icalendar` and
`recurring-ical-events` moved into `[project].dependencies` with `uv.lock`
refreshed and no version changes, and CI runs the command through `uvx` from
the checkout. The README gained its `## Try it` section. Evidence in
[docs/sessions/021-try-it.md](docs/sessions/021-try-it.md).

Prompts and review by Claude Code; plan on muse-wonder-1.0 (effort high), implementation on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only; the plan amendment and the commit step on muse-spark-1.3 at effort low.

GPT Terra 6.1, run through Codex, ran the no-context test that got the checker in 15 seconds and never saw the loop; GPT Sol 6.1, GPT Terra 6.1, GPT Astra 6, Muse Wonder Full and Claude Code's advisor voted for this unanimously.

## Ticket 13b — one more try after a Wonder timeout (2026-11-02)

Built on branch `t13b-stall-retry`, no plan file, the ticket text was the spec. A Wonder call in a slot that ends in a timeout gets one more attempt when a full call's time remains before the propose deadline, counted as `timeout_retries` apart from `local_retries`. With both models hung the timeline does not change. Evidence in [docs/sessions/013b-stall-retry.md](docs/sessions/013b-stall-retry.md).

Prompts and review by Claude Code; implementation on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only; Claude Code ran the live exercise outside those sessions, on made-up data. The stall itself was seen by the driver of Ticket 14, in its logs.

## Ticket 22 — public provenance (2026-11-02)

Built on branch `e7-provenance` per [docs/plans/022-provenance.md](docs/plans/022-provenance.md):
a public, checkable record of which model did what on each real card. `framework/provenance/` holds a read-only export (`python -m framework.provenance.export --db <path>`) that writes one JSON line per slot with counts and codes and no card text, closed Pydantic line shapes, and a `make glimmer-proof` check that runs one synthetic label through llama-swap, prints the served weights' basename, and refuses during a real slot's Glimmer window; plus `docs/MODELS.md` and an empty `docs/provenance.jsonl` that a test validates line by line. Nothing on the card path changed, and no file outside the new package imports it. Evidence in
[docs/sessions/022-provenance.md](docs/sessions/022-provenance.md).

`docs/provenance.jsonl` is generated by the export command after each real card. Commits touching only that file are made by a headless Muse Code session the coordinator starts, with no hand edits.

Prompts and review by Claude Code. Plan on muse-wonder-1.0 (effort high), implementation on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only. Claude Code ran the live checks outside those sessions.
## Ticket 14 — voice correction (2026-11-02)

Built on branch `t14-voice-correction` per [docs/plans/014-voice-correction.md](docs/plans/014-voice-correction.md): a voice note corrects the card. `framework/voice/` holds the typed compile schema, the frozen compile prompt, the Madrid-day fold with `keep` undoing a skip, defer, drop or done, the guarded transcription client through `muse voice transcribe`, the compile call through Ticket 11's client with coded validation, the durable `voice_notes` row as queue and transcript home, the worker with claim, retry and give-up rules, the kill switch and Contributor-mode waits, the same-slot corrected card from stored rows with the stored chart, the change line and replaced-card link, and the read-only `show-chain`; the Telegram poller persists first and sends through the message map, with the outbound scan before compile and the `app.voice_note` event closing each note. Evidence in [docs/sessions/014-voice-correction.md](docs/sessions/014-voice-correction.md).

R9 on the frozen set of 60, one pass each: the literal matcher 13; muse-spark-1.3 minimal 58, the default; muse-spark-1.3 low 57; muse-wonder-1.0 low 58; muse-glimmer-30b local 54. Earlier passes the same night are in `evals/r9_results/earlier/`, and the session note says why.

`evals/r9_cases.json` isn't Muse Code's: a separate Claude Code agent wrote those 60 invented notes and froze them by hash before this ticket's plan was written, without sight of the prompts or the keyword rules. `evals/r9_results/` is the runner's output.

`evals/r9_matcher.py` isn't Muse Code's in its rules. A Claude Code agent wrote the English rules on Nov 1 as a throwaway script for the first 12-case measurement, from a one-line rule list the coordinating Claude Code session gave it, and froze them by hash before that measurement's first model call. Claude Code then pasted them as a code block into the plan amendment prompt, with the Spanish operation words, before the held-out set was opened. muse-wonder-1.0 copied the block into the plan and muse-spark-1.3 ported it to functions. I kept it as it was, because it was fixed before any R9 result and rewriting it after seeing the score would be worse.

The compile prompt in `framework/voice/prompt.py` had three hands. Its operation and until definitions start from the prompt that same Claude Code agent wrote for the 12-case measurement. muse-wonder-full-1.0 wrote the template in the plan. Claude Code made three edits and measured them on the 12 unheld cases: the first sentence names the four keys, a literal test sentence gave way to a rule about reading every "don't" and "no", and the line that question is null on every other operation. It gave the whole text word for word in the amendment prompt, muse-wonder-1.0 copied it, and muse-spark-1.3 typed it into the file. It was frozen before the held-out set was opened.

The last two paragraphs added to `docs/PRIVACY.md` were given word for word by Claude Code in that amendment prompt. The rest were written by muse-wonder-full-1.0.

Claude Code's prompts for this ticket weren't all prose: besides that code block they name some signatures and one-line expressions. Muse Code wrote every file and every commit.

The raising-handler finding came from a review by GPT Sol 6.1, run through Codex. The Contributor-mode facts were measured live by Claude Code, and so were the live end-to-end numbers.

Prompts and review by Claude Code; plan by muse-wonder-full-1.0 (effort high); plan amendments by muse-wonder-1.0 (effort high) from the reviewer's findings; implementation and fixes by muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started; these code sessions ran in Contributor mode, on this public repo and made-up data only.
## Ticket 10b — red-team rounds (2026-11-02)

Built on branch `t10b-redteam` per [docs/plans/010b-redteam.md](docs/plans/010b-redteam.md):
the offline runner `evals/redteam.py`, the gate modules `normalize.py`,
`quantities.py` and `claim_text.py`, both rounds' files under `docs/redteam/`,
and the counts from the summary: round 1, 34 attacks with 32 fixed and 2
passing by ruling; round 2, 32 attacks with none getting through now;
54 review rows apart from the attacker totals; 156 sentences in all,
13 blocked on the frozen runs, 78 on the current gate. Evidence in
[docs/sessions/010b-redteam.md](docs/sessions/010b-redteam.md) and
[docs/redteam/README.md](docs/redteam/README.md).

The attacks came from Muse Code sessions with no part in writing the gate.
Claude Code wrote the prompts, reviewed, and wrote the adjudication files by
hand, including the sentences in the review rows. Muse Code wrote the plan,
the runner and the fixes in headless sessions Claude Code started. Claude
Code's own hands on the tree were mechanical: it archived the draft outside
this repository, put the affected files back to main's state with git,
deleted its own verbatim lines from the plan and from two runner tests,
fast-forwarded the branch to main twice and re-applied one comment line Muse
had written, and wrote R47 to R54 into the adjudication file by hand. It
typed no code. An earlier
draft of the fixes carried code written by Claude Code; it was discarded, and
Muse Code rewrote it from prose rules.

Models: the attacks, the plan and two blind sentence sets on muse-wonder-1.0
at high effort; one blind set and all implementation on muse-spark-1.3 at
medium effort. The false claims in R47 to R54 came from muse-wonder-full-1.0
at high effort, in a review I ran.

Reviews credited as in the plan: R1 to R3 from Ticket 9's review; R4 to R28,
R31 and R33 to R35 from Claude Code's review; R29 and R30 from the external
code review by GPT Sol 6.1 through Codex; R32 from Ticket 17a's review;
R36 to R39 from the independent review by Muse Wonder Full; R40 to R46 from
Ticket 11's gate report and Claude Code's review of it; R47 to R54 from Muse
Wonder Full's blind review of Ticket 11.

## Ticket E2 — source-to-card audit (2026-11-02)

Built on branch `e2-source-audit` per [docs/plans/020-source-audit.md](docs/plans/020-source-audit.md):
`source_audit/` recounts my pull requests and pushes from a public GitHub snapshot with code that imports nothing from the product, then walks the recount through the stored metric, the fact statement and the delivered card; `fetch`, `recount`, `compare`, `run` and a network-free `negative-control` cover the failure modes, and 135 tests in `tests/test_source_audit_*.py` hold it. Evidence in
[docs/sessions/020-source-audit.md](docs/sessions/020-source-audit.md).

The idea came from an outside review round on Nov 1, where GPT Sol 6.1, run through Codex, proposed it, and GPT Sol 6.1, GPT Terra 6.1 and GPT Astra 6, all run through Codex, Muse Wonder Full, and Claude as advisor voted for it, 5 of 5.

Prompts and review by Claude Code; plan on muse-wonder-1.0 (effort high), implementation on muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only. Claude Code ran the live fetches, the counts on scratch copies of my store and the break tests outside those sessions. The since-line finding was this ticket's, and Ticket 13 changed its rule because of it.
## Docs 3 — the README's first screen (2026-11-02)

The top of `README.md` rewritten for a stranger: what it is in one sentence, status true at the moment of merge, how it works in plain words, Try it, the checker, what works and what doesn't, what the loop needs, the words used below, and the design list renamed `The pieces`; Status lines the merged code made untrue fixed against the code (Glimmer code facts, learner core, Telegram card, the Wonder proposal step, R1b, the closing paragraph), with "choice" and "tap" in place of "ruling" throughout. Docs only: no behaviour, schema, fixture or test change. Evidence in [docs/sessions/docs3-first-screen.md](docs/sessions/docs3-first-screen.md).

Prompts and review by Claude Code. Implementation on muse-spark-1.3 (effort medium), in a headless session Claude Code started, with the commit step at effort low, in Contributor mode on this public repo. The opening sentence and the How it works paragraph were drafted by Claude Code in a working doc, then I edited and approved them. This pass also fixes the "Built during the hackathon" sentence, which had claimed Muse Code wrote all the code. GPT Terra 6.1's no-context test and section 3 of GPT Astra 6's pre-mortem, both run through Codex, asked for this pass; GPT Sol 6.1, GPT Terra 6.1, GPT Astra 6, Muse Wonder Full and Claude Code's advisor voted for it unanimously.

## Clock fix — a test that broke as the date moved (2026-11-02)

Built on branch `fix-clock-tests`, no plan file, the ticket text was the spec. `test_canary_exception_cli_reports_type_only` built its one calendar row at a fixed instant, Oct 31 14:00 at +01:00, while the `labels` command reads its as-of time from the real clock and only looks at rows from two days before to fourteen days after; once the real clock passed Nov 2 14:00 the row fell outside that window, the raising client never ran, and the output no longer named `RuntimeError`. The test now dates its row an hour before the real clock, like the two budget tests in the same file, and keeps every assertion; no product code changed.

Prompt and review by Claude Code; implementation on muse-spark-1.3 (effort low), in Muse Code, in a headless session Claude Code started, in Contributor mode, on this public repo and made-up data only. Claude Code looked for other tests at risk by running the whole suite with the clock moved forward to Nov 3, Nov 5 and Nov 9, in Madrid time and in UTC, outside that session, and no other test failed because of the date.
## Ticket 11b — review fixes (2026-11-02)

Built on branch `t11b-review-fixes` per [docs/plans/011b-review-fixes.md](docs/plans/011b-review-fixes.md): eight fixes from the blind review of Ticket 11 across the proposal core, both transports and the stores. A fallback now wraps only its own goal's commitment, the latest cycle is the row recorded last at the greatest `as_of`, the parent read agrees with the slot reader, both transports fail closed on a Contributor model or a missing provider model with shared token-count rules, the draft cap of three claims per section is shared by the sent schema and the local model, the briefing id digests the assembled briefing, and both transports refuse a reply over the 4 MiB cap. Evidence in [docs/sessions/011b-review-fixes.md](docs/sessions/011b-review-fixes.md).

Muse Wonder Full (muse-wonder-full-1.0) reviewed Ticket 11 blind, found the problems this ticket fixes, and wrote the reproduction scripts; Claude Code ran them from a normal shell, because the review's sandbox couldn't. The finding that a real Contributor run passed the parser came from Claude Code's live run, not the review. The review's `repro_hour.py`, rerun on this tree, printed the same output as before the ticket: all five live slots land on the slot's own hour, 22:31 gives no hour, and the busy edges and the 59-minute gap behave.

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started; those sessions ran in Contributor mode, on this public repo and made-up data only. Claude Code ran the live measurements outside those sessions, on made-up data. The first move onto main and the text fixes ran on muse-spark-1.3 at effort low, and the move onto main after Tickets 13, 13b and 14 ran on muse-spark-1.3 at effort medium.
## Ticket 16 — metrics and labels (2026-11-02)

Built on branch `t16-metrics` per [docs/plans/016-metrics-and-labels.md](docs/plans/016-metrics-and-labels.md):
two slices, one implementation commit for the whole ticket after the reviewer approves both.
Slice A (`framework/rater/`) builds a self-contained offline HTML page holding every atomic claim
from every delivered card with its cited evidence in plain words, plus a private key file, and a
scorer that prints the R1 support rate; the dated Deviations entries 13 to 16 in
[docs/PREREG.md](docs/PREREG.md) pin the claim-splitting rules.
Slice B (`framework/metrics/`, `make metrics`) prints the whole submission report as counts and
rates with `n` from a store copy: R1 first drafts as slot-path and re-proposal blocks off the
existing SQL with an opt-in proposal-key filter, delivered cards and sides from the delivery join,
fact disputes, the identities that must hold between the counts, with both sides printed,
gating the exit code, R7 follow-through per
evidence class with right-censored and unobserved-device unknowns, the before/during table from
independent evidence only, and R8 with the rebuilt learner state against the stored one,
Brier-primary scores with the clipping note, the policy diff, my forecast against my actual split
with the Neither and untapped lines, and the recovery grid.
109 tests in `tests/test_rater_*.py` and `tests/test_metrics_*.py`, passing.
Evidence in [docs/sessions/016-metrics-and-labels.md](docs/sessions/016-metrics-and-labels.md).
The real pack is private and never enters the repo.

Prompts and review by Claude Code. The plan and its amendment by muse-wonder-1.0 (effort high),
from Claude Code's prose briefs. Implementation and fixes by muse-spark-1.3 (effort medium), with three small amend sessions after the commit on muse-spark-1.3 at low effort,
in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo
and made-up data only. The PREREG entry's text was written by muse-wonder-1.0 in the plan from
Claude Code's instructions on what it must say; Claude Code's prompts named files, tables,
functions and one example sentence copied from the product prompt, and held no code.

## Ticket 10c — since_last wording (2026-11-02)

Built on branch `t10c-since-last` per [docs/plans/010c-since-last-wording.md](docs/plans/010c-since-last-wording.md):
one claim-only code `L1B_SINCE_LAST_WORDING` for containment patterns in
`since_last` claims with metric refs, two teaching lines in the Wonder prompt
with gate-checked examples, the all-zero branch reworded off the negated
opener, pre-existing fixtures reworded to the taught phrase with no outcome
changed, mutant M119 pinning the 15:30 sentence, and PREREG entry 17.
Evidence in
[docs/sessions/010c-since-last-wording.md](docs/sessions/010c-since-last-wording.md).

Prompts and review by Claude Code; plan on muse-wonder-1.0 (effort high);
code, tests and docs on muse-spark-1.3 (effort medium), with a final
muse-spark-1.3 session at medium for the commit and the rebase and small docs
amends after it on muse-spark-1.3 at low, in Muse Code, in
headless sessions Claude Code started. Claude Code wrote the prompts in
prose, including the example sentences the Wonder prompt teaches, made the
rulings the plan records, and ran the replays and the Wonder check from
outside this repository. It created the branch and typed nothing in this
repository.
## Ticket 13c — an 11:30 card on Nov 3 (2026-11-02)

Built on branch `t13c-1130-slot` per [docs/plans/013c-1130-slot.md](docs/plans/013c-1130-slot.md):
one more pinned Builder card on Nov 3 at 11:30 Madrid, since I have my phone from 11:00 that day; the daily schedule, the Builder-only times and the daily limits are untouched, and only that instant classifies as a pinned slot with limits starting at 11:30. Those limits reach the hour finder and the gate at the three places that already passed them on, a voice correction to that card re-proposes with its limits, and the Glimmer proof refuses its window before that card. Evidence in [docs/sessions/013c-1130-slot.md](docs/sessions/013c-1130-slot.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started; those sessions ran in Contributor mode, on this public repo and made-up data only.

## Ticket 15b — proof harness (2026-11-02)

Built on branch `t15b-proof-harness` per [docs/plans/015b-proof-harness.md](docs/plans/015b-proof-harness.md):
the receipts R2 (privacy), R3 (steering) and R4 (evidence sensitivity) from [docs/PREREG.md](docs/PREREG.md),
implemented as pre-registered, with the Nov 1 deviations and the Nov 2 one PREREG lists. `evals/r2.py` plants distinct synthetic
canaries in every inventoried free-text field and runs whole slots through the product's `run_slot` against
adversarial fakes, scanning every recorded outbound body; `evals/r3.py` runs the 20 registered pairs through
Ticket 11's prompt, retry and gate, resumable, with an unavailable stop; `evals/r4.py` reruns the registered
cited-vs-control sensitivity check from R3's stored base draws; a pure scorer and renderer beside each runner;
`evals/results/r2.json` plus identity-named JSONL under `evals/results/r3/` and `evals/results/r4/`; generated
[docs/r2.md](docs/r2.md), [docs/r3.md](docs/r3.md) and [docs/r4.md](docs/r4.md); `make r2`, `make r3-doc` and
`make r4-doc`; and 11 new pytest files with the wiring test. I changed nothing under `framework/`. Evidence in
[docs/sessions/015b-proof-harness.md](docs/sessions/015b-proof-harness.md).

Prompts and review by Claude Code. The plan ran on muse-wonder-full-1.0 at high effort, in two sessions.
Implementation and fixes ran on muse-spark-1.3 at medium effort, except eight short mechanical sessions that ran on muse-spark-1.3 at low effort: one test fix, the commit, the PREREG line, three docs fixes, one labelling fix and one wording fix. All ran in Muse Code, in headless sessions
Claude Code started, in Contributor mode, on this public repo and made-up data. Claude Code ran the live R3
and R4 receipts from its own shell through MuseExecClient in Standard mode. Claude Code ran the declared re-run of R3 and R4 on Nov 2 on the gate and prompt after Tickets 10b and 10c, gate 2f443fbbc8dd; two muse-spark-1.3 sessions at medium effort wrote it up and fixed the receipts tests for more than one stored run.

Claude Code's review changed code eleven times: the unavailable stop that never fired above concurrency 1;
exit 0 with work left; two processes drawing a slot twice, now refused by a lock; uninformative pairs printed
as fail; overlapping canary words that produced a false R2 finding; a targeted model copying text it hadn't
seen; a stopped canary counted as escaped; a partial R4 reading as held; R4 picking the wrong R3 file;
runner tests that read the wall clock and failed near every quiet window; and R4's method sentence naming
a two-layer stack for rows made through three.
The D1/I2 block was added after I saw R3's first run, and is labelled that way in the report.

## Held-out checker set v1 (2026-11-02)

GPT Sol 6.1 (OpenAI), through the Codex CLI at maximum reasoning effort, wrote
the 40 held-out checker cases in `evals/heldout/checker-heldout-v1.json` on
Nov 2: 20 PASS and 20 FAIL, each FAIL false in exactly one way, across the
registered kinds and domains, each case with an id, expected verdict, kind,
domain, one line on why, and a one-claim checker input. It worked blind from
the public description of the checker at commit 5b8dad6, in a read-only
sandbox with web search disabled, and labelled each case by the truth judged
from that input alone. I froze the file in this commit before any scoring.

Claude Code chose the public files the author saw, wrote the author's task,
checked the file's JSON shape but not its verdicts, and placed the file in
the working tree. Muse Code, muse-spark-1.3 at low effort, wrote the README
in `evals/heldout/README.md` and the freeze test and made this commit, in a
headless session Claude Code started, in Contributor mode, on this public
repo.

## Held-out gate set v1 (2026-11-02)

GPT Sol 6.1 (OpenAI), through the Codex CLI at maximum reasoning effort,
wrote the 40 held-out gate sentences in `evals/heldout/gate-heldout-v1.json`
on Nov 2: 20 true sentences a correct gate must let through, and 20 false
ones it must stop, each false in exactly one way, with the expected verdict
in `predicted_passes` and the target letters following this set's own legend.
It worked blind from the public documents at commit aa3c0e8, in a read-only
sandbox with web search disabled, and labelled each sentence by the truth
judged from the records alone. I froze the file in this commit before any
scoring.

Claude Code chose the public documents the author saw, wrote the author's
task, including the runner's fixed context as plain data, checked the file's
JSON shape and that the red-team runner's loader accepts it but not its
verdicts, and placed the data file and the three published files
(`gate-author-task.md`, `gate-author-manifest.txt`,
`gate-author-commands.txt`) in the working tree. Muse Code,
muse-spark-1.3 at low effort, wrote the README section and the freeze test
and made this commit, in a headless session Claude Code started, in
Contributor mode, on this public repo.
## Held-out gate set v1 scored (2026-11-02)

I scored the frozen gate set once, on the commit the live cards moved to
on Nov 2 at 23:29, `3e31338bf1ede702d82d94aa4dd1ec0851ef557b`: 18 true pass, 19
true stop, 1 false pass (G18), 2 false stop (G23 and G25), no verdict 0,
so predicted/actual agreement is 37 of 40. The results are in
`evals/heldout/gate-results-v1.md`, and the Round 3 section and the
runner summary now sit in `docs/redteam/README.md`.

Claude Code copied the frozen file to `docs/redteam/round-3.json`, ran
the red-team runner once with `--write-frozen` on the live cards' commit,
and checked the counts; the runner wrote `round-3.frozen.json` and
`round-3.results.json`. Muse Code, muse-spark-1.3 at medium effort, wrote
the Round 3 section, the results doc, the summary updates and the test,
and made this commit, in a headless session Claude Code started, in
Contributor mode, on this public repo. Muse Code wrote
`docs/redteam/round-3.adjudicated.json` by the registered rule.

I disclose that the registered rule said the runner runs once. After Muse Code
added the adjudication file, the repository's staleness test required
`round-3.results.json` to match a fresh regeneration, so Muse Code ran the runner
a second time on `round-3.json`, without `--write-frozen`, on this branch,
whose gate files are byte-identical to those at `3e31338`. Muse Code checked that
its 40 rows are identical to the scored run's rows in
`round-3.frozen.json`, and that it only added an empty review list. Muse Code left
`round-3.frozen.json`, the scored record with its stamps, unchanged, and Claude Code
checked the rows again. I
confirm the second run changed no verdict.

## Ticket 16c — since-last evidence (2026-11-02)

Built on branch `t16c-since-last-evidence` per [docs/plans/016c-since-last-evidence.md](docs/plans/016c-since-last-evidence.md):
for a claim in a `since_last` section, the rater page now shows each cited metric's value on the
previous card and on this card before the change, recovered from the two stored snapshots and
checked against the claim's change under the delta arithmetic; a claim whose numbers cannot be
recovered and checked exactly is left out and counted on its own line. The start screen says that
each card counts its own three periods. PREREG Deviation 19 records the change. Evidence in
[docs/sessions/016c-since-last-evidence.md](docs/sessions/016c-since-last-evidence.md).
The real pack is private and never enters the repo, and no rating exists yet. After the review, a follow-up added a display-name profile fallback so a delivered corrected card saved with no `slot_cards` rows still resolves its sides (counted as `sides_profile_from_display`), with no change to how a side matches its source.

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only.
## Ticket C1 — the gate's hardening in the public checker (2026-11-02)

Built on branch `c1-checker-hardening` per [docs/plans/023-checker-hardening.md](docs/plans/023-checker-hardening.md):
the command line and both panes of the page run a wider checker in `framework/verify/hardened.py`
that adds negation, quantity forms, and units and periods where the caller declares them on top of
everything the older checker reports, says per claim which checks didn't run for lack of metadata,
and agrees with the gate on every expressible case; `framework.verify.verify_claims` keeps the
earlier, smaller set of checks, because it sits inside the import closure the live run's gate is
pinned to. Evidence in
[docs/sessions/023-checker-hardening.md](docs/sessions/023-checker-hardening.md).

Prompts and review by Claude Code. Plan on muse-wonder-1.0 (effort high), in two sessions: the plan
and one amendment from Claude Code's review. Implementation and fixes on muse-spark-1.3, in four
sessions: two at medium effort and two short ones at low; Claude Code stopped the first after its
test run hung on the quadratic name scan its review had traced. Commit on muse-spark-1.3 (effort
medium). All ran in Muse Code, in headless sessions Claude Code started, in Contributor mode, on
this public repo and made-up data only. Claude Code wrote the prompts in prose, created the branch,
and ran the escape probes, the headless page check, the speed checks and make check from outside
this repository; it typed nothing in this repository. The page's four verdict lines were given word for word in a prompt, after an outside review asked for plainer verdicts. The bug report came from the Nov 1 night
review, where GPT Sol 6.1, GPT Terra 6.1 and GPT Astra 6, run through Codex, and Muse Wonder Full
each reproduced the negated and minutes escapes; the three GPT reviewers voted for this ticket,
Wonder Full voted against, and I approved it on Nov 2.

## Ticket 14c — a voice-corrected card keeps its slot rows (2026-11-02)

Built on branch `t14c-voice-slot-rows` per [docs/plans/014c-voice-slot-rows.md](docs/plans/014c-voice-slot-rows.md):
the live poller runs `poll --voice` with no store argument, so the voice worker's store path is None, and three worker functions returned early instead of resolving it: on Nov 2 the corrected cards at the 20:30 and 22:30 slots went out with no slot rows, and the learner's replay skipped my tap on the 20:30 one. `_slot_rows`, `_save_corrected_rows` and `_record_local_retries` now resolve the store path the way the rest of the worker does, with an explicit path unchanged; card matching for a correction uses the stored rows keyed by letter, and retried local start failures during a re-proposal are recorded. The row rules moved into one shared builder that the worker and the new backfill both call. `python -m framework.voice backfill-slot-rows` rebuilds missing rows for corrected cards from stored rows only, dry run by default with counts and ids only, writes only with --apply, one transaction per card, never touches a card that has rows; an unchanged side copies the replaced card's row, a changed side takes its commitment from the stored re-proposal result after dropping any stored result that would rebuild the replaced side itself, and a card the stored rows cannot settle is skipped with a closed reason. ProposalStore gained one read of every stored result at a slot; results_for_slot is unchanged. The closure hash over the 47 framework files the gate reaches was 907b228d92cd before and is 907b228d92cd after; no closure file changed. 14 new tests: B1 to B3 run the worker with no explicit path and IKIGAI_DATA_DIR at a made-up store, each failed before the fix, B4 pins the explicit-path rows, and K1 to K10 cover the backfill, all failed before the command existed; the voice, telegram and proposal store test files pass 231. make check: exit 0, ruff and ruff format clean, pyright 0 errors, pytest 4,469 passed and 1 skipped, gitleaks clean; make eval: hello 1 of 1, each briefing task 176 of 176, glimmer_facts 30 of 30, proposal_gate 37 of 37. A rehearsal from Claude Code's own shell, outside this repository, on scratch copies of my store with a loopback fake of the Bot API and the real `poll --voice` loop with no store argument, gave 10 taps with 2 skipped before the fix and 10 taps with 1 skipped after, the one left being my real tap on the Nov 2 20:30 card; the backfill's dry run on that copy saw 3 corrected cards with 2 to write and 4 rows, and --apply left the replay skipping 0 of 10 taps, with a second --apply writing nothing. Evidence in [docs/sessions/014c-voice-slot-rows.md](docs/sessions/014c-voice-slot-rows.md).

Prompts and review by Claude Code. The plan ran on muse-wonder-1.0 (effort high), 4 m 48 s. Implementation ran on muse-spark-1.3 (effort medium), 17 m 42 s, after Claude Code's review amended the plan through that session's prompt. This commit step ran on muse-spark-1.3 (effort medium). All sessions headless, started by Claude Code, in Contributor mode, on this public repo and made-up data only. Claude Code's prompts held no code blocks, patches or test rows; Muse Code wrote the plan, every file and this commit; Claude Code ran the rehearsal, the gate checks and make check from its own shell.

## Ticket 10d — squashed private-term matches made only of card wording (2026-11-03)

Built on branch `t10d-squashed-terms` per [docs/plans/010d-squashed-private-terms.md](docs/plans/010d-squashed-private-terms.md):
a squashed or fuzzy private-term match no longer fires when every token it
consumes is the card's own claim vocabulary (period, direction, comparison and
stop words, `hour` and `hours`, number tokens, and the snapshot's label
words); an exact whole-term match still fires, vocabulary or not; with an
empty vocabulary every arm returns its earlier verdict, pinned by a corpus
test over the repository's private-term sentences; plus PREREG entry 20.
Evidence in
[docs/sessions/010d-squashed-private-terms.md](docs/sessions/010d-squashed-private-terms.md).

Muse Code wrote the plan, the code, the tests, the PREREG entry and these
docs on muse-spark-1.3 at medium effort, with the commits on muse-spark-1.3
at low effort, in Muse Code, in headless sessions Claude Code started.
Claude Code wrote the prompts in prose, reproduced the false stop with
made-up terms, ran the checks, pushed the branch and opened the pull
request. Nobody read the deny list, and nobody opened evals/heldout/.

## Ticket 20b — corrected cards (2026-11-02)

Built on branch `e2b-corrected-cards` per [docs/plans/020b-corrected-cards.md](docs/plans/020b-corrected-cards.md):
the source audit now collects every delivered card at a slot — the slot card plus each corrected card with voice-note delivery proof — and runs stage 4 once per card against that card's own briefing rows, folding the per-card lines into the metric verdict; a one-card slot prints byte for byte what it printed before, and a change sentence with "by" is never read as a count. The provenance log gains one last field with one entry per closed voice note at the slot: the operation word, whether a new card was sent, and the time in whole milliseconds. Evidence in
[docs/sessions/020b-corrected-cards.md](docs/sessions/020b-corrected-cards.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation, the fix and this commit step: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started, in Contributor mode, on this public repo and made-up data only. Claude Code ran the re-audit and the provenance export on scratch copies of my store outside those sessions; it created the branch and typed nothing in this repository.
## Held-out checker set v1 scored (2026-11-02)

Claude Code ran the public checker once per case on 1cd8db8 from a scratch script outside the repository, and checked the counts. It also placed the three published files, including the author's task it had written.

Muse Code, muse-spark-1.3 at medium effort, wrote the scorer, its tests, the results doc and the README line, ran the scorer once to write the results JSON, and made this commit, in a headless session Claude Code started, in Contributor mode, on this public repo.
## Ticket 24 — trust page (2026-11-03)

Built on branch `trust-page` per [docs/plans/024-trust-page.md](docs/plans/024-trust-page.md):
[docs/TRUST.md](docs/TRUST.md), the public page of misses, limits and blind tests, bound to the code by [tests/test_trust_page.py](tests/test_trust_page.py); five new cases in [evals/briefing_cases.py](evals/briefing_cases.py) outside `MUTANTS` with the `PHONE_MISSES` record, so `MUTANTS` still holds 119 and `KNOWN_GOOD` still holds 57; [evals/replay_sentence.py](evals/replay_sentence.py), which gates one sentence in the 15:30 claim's context; [tests/test_replay_sentence.py](tests/test_replay_sentence.py); the scope sentence under the README's pitch line with a link to the page; and the rewritten AGENTS.md Mission around the same sentence. Evidence in [docs/sessions/024-trust-page.md](docs/sessions/024-trust-page.md).

Muse Code wrote the plan (muse-wonder-1.0 at high, three sessions) and the code, tests and docs (muse-spark-1.3 at medium, six sessions, including the move onto the current main), and this commit (muse-spark-1.3 at medium), in headless sessions Claude Code started; the outside-try paragraph's wording in the README was suggested by Claude Code from the engineer's report. Claude Code wrote the prompts in prose, including the scope sentence, the six card sentences and the other quoted sentences word for word, checked the facts on a copy of my store, ran the mutation pass and make check, and typed nothing in this repository. GPT Astra 6 (OpenAI), through Codex at maximum effort, read-only, reviewed the page for overclaiming in two passes; Muse Code applied the fixes. I opened the README's Glimmer paragraph with the Nov 2 live facts, bound by a test to docs/provenance.jsonl.

## Ticket 25 — a checker page anyone can use, with no setup (2026-11-03)

Built on branch `t25-checker-page` per [docs/plans/025-checker-page-for-everyone.md](docs/plans/025-checker-page-for-everyone.md):
the page at `docs/verify/index.html` runs the worked example by itself on load, speaks in plain sentences instead of codes ("The sentence says 12; your record says 7."), puts the plain-words form first with one-tap examples (a wrong number, a matching sentence, a sneaky "not"), and moves the JSON box into one collapsed section at the bottom. The checker's verdict logic did not change: nothing under `framework/` moved, the bundle and the file examples are byte-identical, and every code list is pinned through the plain pipeline. The page's copy was pinned in the plan, and the four rulings and the "Why I built this" wording came from Claude Code's review of the plan, written as Carlos. Evidence in
[docs/sessions/025-checker-page-for-everyone.md](docs/sessions/025-checker-page-for-everyone.md).

Muse Code wrote the plan update, the code, the tests and these docs, powered by Meta Muse Spark, in one headless session Claude Code started, in Contributor mode, on this public repo and made-up data only. Claude Code reviewed the plan (its four rulings are recorded in the plan and the session note) and runs the gate checks and `make check` afterwards. I never opened the held-out sets or the hidden-criteria path.

A follow-up in the same branch puts the Catch the AI game at the top of the page, built around six rounds Muse Wonder wrote in its own sessions from Claude Code's prose prompts: the mistakes in some sentences were asked for, and a design review by three outside models shaped the everyday-clutter theme. This session built the game around those rounds without touching them. Evidence in
[docs/sessions/025-checker-page-for-everyone.md](docs/sessions/025-checker-page-for-everyone.md).

Muse Code built the game, powered by Meta Muse Spark, in one headless session Claude Code started, in Contributor mode, on this public repo and made-up data only. I never opened the held-out sets or the hidden-criteria path.

## AI assistance outside the Muse family

- **Claude Code (Anthropic)** was used as an advisor and reviewer. It co-drafted the
  planning documents (SPEC.md, the pitch, docs/WORKFLOW.md) and helped structure the ikigai profiles from my interview answers; it reviewed plans and diffs,
  and ran feasibility checks on Oct 27 outside this repo (one call each to Muse Glimmer,
  Muse Wonder and Muse Code, plus an Inspect AI hello-world).
- Claude Code doesn't edit files or make branch commits in this repository; those are Muse Code's, as summarised in `docs/sessions/`. The exceptions are the held-out test sets a ticket's entry names, and Ticket 10b's adjudication files and the mechanical steps that entry lists. On Nov 3 Claude Code made the merge commits that brought main into the branches of pull requests #54 to #57 and of this page, so that both sides' sections of this file were kept; those merge commits change nothing else. Its prompts sometimes spelled out a small fix in a few lines of code, or exact wording for a doc or session note, and Muse Code applied them. The largest such code blocks I found are about a dozen lines, in Tickets 9, 9b, 15a and 17a. Through Oct 31 I ran every Muse Code session myself. From Nov 1, at my request, Claude Code also wrote the prompts, started and supervised the Muse Code sessions and reviewed their output. It also runs pushes and squash merges, so the merge commits on main come from those.
- **GPT Sol 6.1 and GPT Astra 6 (OpenAI), through Codex,** reviewed this project read-only on Nov 1: literature, code, demo plan, failure modes and launch plan. They wrote nothing in this repository, except that GPT Sol 6.1 wrote the held-out sets on Nov 2, `evals/heldout/checker-heldout-v1.json` and `evals/heldout/gate-heldout-v1.json`, and nothing else in the repository. Findings that changed something are credited in the ticket that used them.

## Docs 4 — the README's first screen (2026-11-03)

Replaced everything in `README.md` between the title line and `## How it works` with the owner's approved text (the two promises, the five daily cards, the checks before and after each card, what code can and cannot check with the TRUST.md link, the Nov 2 wrong-window sentence and the Nov 3 fix, the first real card, and the checker-page game invite). Nothing else in `README.md` changed. The owner wrote and approved the text word for word; Muse Code made the edit, updated the trust-page test pin from the old pitch line to the new scope line, and ran the tests.

Tests run: `tests/test_trust_page.py` and `tests/test_verify_page.py` (69 passed), the README pins in `tests/test_tryit.py` (2 passed), `tests/test_provenance_docs.py`, `tests/test_briefing_review_rules.py` and `tests/test_redteam.py` (420 passed), and ruff check and format on `tests/test_trust_page.py` (clean).

A correction to Ticket 25's section: Muse Code built the game in one headless session, then changed it in three more, from design-review and browser-play notes. Pull request #61 lists all six sessions behind the page.

## Ticket 25b - the game in plainer words (2026-11-03)

Built on branch `docs4-readme`: eight copy-only swaps on the checker page (`trap` for `fib`, `mistake` for the "Make your own round" verdict, the strawberry subhead, the in-browser privacy line), one matching sentence in the README first screen, the pins in `tests/test_verify_page.py` and `tests/test_verify_game.py` updated with no other check changed, and a new section in `docs/sessions/025-checker-page-for-everyone.md` recording the old and new strings. The verdict logic, `docs/verify/bundle.json`, `docs/verify/examples/`, `docs/verify/game/` and everything under `framework/` are untouched. Evidence in [docs/sessions/025-checker-page-for-everyone.md](docs/sessions/025-checker-page-for-everyone.md).

Implementation: Muse Code, powered by Meta Muse Spark, headless, in one session. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Ticket 25c: a consented study version of the game, with the plan registered first (2026-11-03)

Built on branch `t25c-study`: a consented Prolific study version of Catch the AI behind `?src=prolific` in `docs/verify/index.html` (consent screen with a disabled-until-checked Start, played-before and instruction-check questions, one random cyclic rotation of the six cards with no reveal, stamp, right-or-wrong sound or live score between taps (only the neutral tap), a submit screen opening a pre-filled Google Form in a new tab, then the debrief with the full reveal and a `You: N/6 · Checker: 5/6` line). The payload is one line carrying a 12-character salted SHA-256 of the Prolific ID and never the raw ID; with the form constants still empty the study shows only a not-open notice. The ordinary game flow is unchanged and the page still sends nothing by itself. First-person copy fixes: "and I asked it to set traps in some" in the byline, "I asked it to slip mistakes into some" in the rounds disclosure and its page copy, plus the disclosure-change record and the study note in How this works. New `docs/prereg-game.md` (the registered plan) and `docs/study-privacy.md` (the privacy notice), and new pins in `tests/test_verify_game.py` for the strings, the exact payload, the rotation, the no-send rule and the unchanged ordinary game. The verdict logic, `docs/verify/bundle.json`, `docs/verify/examples/`, `docs/verify/game/README.md` and everything under `framework/` are untouched. Evidence in [docs/sessions/025-checker-page-for-everyone.md](docs/sessions/025-checker-page-for-everyone.md).

Implementation: Muse Code, powered by Meta Muse Spark, headless, in one session. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.
## Ticket 16b — the local row's results (2026-11-03)

The muse-glimmer-30b row reached its stop time under gate 42b57031c11b: the product arm counted 38 of the 54 cases with 3 first-draft gate failures (1 beyond wording or form), the plain arm 37 with 32 (10 beyond wording or form); 16 cases not run on product and 17 on plain; recovered by one retry 3 on product and 12 on plain; verdict held (product failures 3, plain failures 32). The two row files joined `evals/results/r1b/`, `docs/r1b.md` was regenerated with `--summary`, and `--pick-rejection` kept muse-wonder-1.0. One plain-arm attempt (case r1b-008, attempt 1) took 252,436 ms for 2,497 tokens because a separate request to the same local model ran alongside it, and the row is kept as recorded. The numbers' source is `docs/r1b.md`. Evidence in [docs/sessions/016b-models-on-the-gate.md](docs/sessions/016b-models-on-the-gate.md).

Muse Code folded the local row's results in as data in a mechanical headless session, in Contributor mode, on this public repo and made-up data only. No model call was made and nothing under `framework/` moved. I never opened the held-out sets or the hidden-criteria path.
## Docs 5 - evidence that Muse Glimmer runs on my own hardware (2026-11-03)

Added [docs/glimmer-evidence.md](docs/glimmer-evidence.md): the screen captures of llama-swap serving the model and of the machine hardware, copied byte for byte from the private evidence files into `docs/evidence/`, plus the run log from the `make glimmer-proof` check and links to the per card provenance and the R10 sample outputs on made-up data. I added one pointer paragraph in `README.md` and changed nothing else there. The captures and the glimmer-proof run come from Claude Code's Nov 3 session on my machine; Muse Code made this edit headless in one session. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Docs 6 - two small text changes from the judges' feedback (2026-11-03)

I added one paragraph to the `README.md` first screen naming the four Meta models and the plain code check, and one paragraph after it with the worked checker case from an outside engineer. Docs only: no behaviour, schema, fixture or test change, and no pinned test needed an update.

Implementation: Muse Code, powered by Meta Muse Spark, headless, in one session. I never opened anything under `evals/heldout/` except `evals/heldout/README.md`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Docs 7 - study deviation note, export limit, and PRs spelled out (2026-11-03)

I made three small documentation edits and recorded them here. Docs only: no behaviour, schema, fixture or test change.

- `docs/prereg-game.md`: I replaced the Deviations line with the note that the study was not run before the deadline, with no answers collected and no results.
- `docs/TRUST.md`: I added the paragraph on the provenance export limit at the end of the Mistakes in my own tools section.
- `README.md`: I spelled out PRs as pull requests on GitHub in the Five times a day paragraph.
- `CONTRIBUTIONS.md`: this entry.

Claude Code started this session from a prose prompt and Muse Code (muse-spark-1.3, low effort) made the edits. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Docs 7b (2026-11-03)

I made two small documentation commits and recorded them here. Docs only: no behaviour, schema, fixture or test change.

- `docs/provenance.jsonl`: the five Nov 3 lines after 11:30, written by the export command from the store and committed unedited.
- `docs/TRUST.md`: I replaced the export limit paragraph with the live case, naming the Nov 3 22:30 line whose disconnect option shows a re-draft's stopped first attempt.

Claude Code started this session from a prose prompt and Muse Code (muse-spark-1.3, low effort) made the edits.

## Docs 8a (2026-11-03)

I put the live run in numbers on its own page and moved the checker paragraph up the README. Docs only: no behaviour, schema, fixture or test change.

- `docs/live-run.md`: I created the page with the numbers as of Nov 3 23:45 Madrid and how I counted them.
- `README.md`: I moved the checker paragraph to sit directly after the four models paragraph, and I added the live run link at the end of the first real card paragraph.
- `CONTRIBUTIONS.md`: this entry.

Claude Code started this session from a prose prompt with the numbers produced by a read-only script, and Muse Code (muse-spark-1.3, low effort) made the edits.

## Docs 9 (2026-11-04)

I published the R9 audio result. Docs and data only: no behaviour, schema, fixture or test change.

- `docs/r9-audio.md`: I wrote the result of the 60 spoken cases from the working report, with the per-language and paired tables, the failures table, the TTS confound and the Whisper check, the limits, and where the data is.
- `evals/r9_audio/results.json`: I committed the evaluation output unedited.
- `README.md`: I added one sentence at the end of the voice correction bullet with the audio score and the link to the new page.
- `CONTRIBUTIONS.md`: this entry.

A Claude Code agent ran the evaluation privately (cloned-voice TTS, Meta speech-to-text through the product's transcriber, R9's own runner) and Muse Code (muse-spark-1.3, medium effort) wrote the doc and committed the data unedited.
## Ticket 26 - domain packs: my checker on public records from two other domains (2026-11-04)

I added an isolated package, `framework/domains/`, that runs a domain pack: one JSON file declaring a goal, commitments with a rule each, CSV signals and metrics for a domain that isn't mine. It pins the data by sha256, checks declared identities, asks Muse Wonder for a commitment with reasons, and checks them with my public claim checker, which runs my gate's checks on records anyone supplies. Two packs ship on public data, bike-share operations (UCI Bike Sharing) and home energy (UCI Appliances Energy Prediction), each with its own standard-library oracle and a frozen evaluation; across both, 120 of 120 aimed planted errors were caught, 38 of 38 correct controls passed, and Wonder's first drafts passed on 28 of 38 weeks, 35 after one repair. The live loop doesn't import any of it. Plan: [docs/plans/026-domain-packs.md](docs/plans/026-domain-packs.md). Results and every failure: [docs/domains.md](docs/domains.md). Session note: [docs/sessions/026-domain-packs.md](docs/sessions/026-domain-packs.md).

Who did what. The council that asked for this was GPT Sol, GPT Terra and GPT Astra run through Codex, Muse Wonder Full and Grok; they recommended isolated packs over a refactor of the live loop. I delegated the overnight decisions to the Claude Code coordinator. Claude Code wrote every prompt in prose, downloaded and pinned the data, probed the checker on made-up claims outside this repository before the plan, reviewed each diff, ran the tests, the development-week proposals and the frozen evaluation commands, whose output is the four files under `evals/domains_results/`, and wrote the text of `docs/domains.md`, the session note, this entry and the README sentence for Muse Code to commit. Muse Code wrote every other file in this ticket and made every commit: the plan on muse-wonder-1.0 (high effort) in one session; the implementation, three rounds of fixes and the energy pack on muse-spark-1.3 (medium) in five sessions; the docs commit and this update on muse-spark-1.3 (low) in two sessions. After the runs, GPT Sol 6.1 through Codex reviewed the code and every number read-only; its four tooling findings are fixed and listed in docs/domains.md. All ran headless in Contributor mode, on this public repo and public data only. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Docs 8b (2026-11-04)

I regenerated the live-run page from the committed command output. Docs only: no behaviour, schema, fixture or test change.

- `docs/live-run.md` is regenerated from `make metrics` with every number naming its report key; the Nov 3 11:30 card is counted on its own line, outside the run, as PREREG item 18 says; the pre-registered R7 and R8 results are now on the page (R7: none of the 6 checkable accepted commitments completed by the independent evidence; R8: the learner no better than its baselines on 5 predictions).
- `CONTRIBUTIONS.md`: this entry.

Claude Code generated the page with read-only scripts and started this session from a prose prompt; Muse Code (muse-spark-1.3, low effort) committed it unedited.

## Docs 11 (2026-11-04)

I said why this exists, showed how it works in two diagrams, and said what the research changed. Docs only: no behaviour, schema, fixture or test change.

- `README.md`: I added the Why it exists paragraph after the first paragraph, with the Webb and Sheeran, Emmons and King, and Liu, Zhang and Liang quotes checked against docs/LITERATURE.md.
- `README.md`: I drew two mermaid flowcharts in How it works, one card end to end and what the number check does, with each step checked against the code.
- `README.md`: I added the What the research changed section with eight rows from docs/LITERATURE.md.
- `CONTRIBUTIONS.md`: this entry.

Claude Code wrote the "Why it exists" paragraph and the specification for the diagrams and the table and started this session from a prose prompt, and Muse Code (muse-spark-1.3, medium effort) wrote the diagrams and the table and checked them against the code.

## Docs 12 (2026-11-04)

I cut the README down to a landing page and moved the long sections to pages under docs/. Docs only: no behaviour, schema, fixture or test change.

- `docs/status.md`: new page with the moved Status section (all of it except the Nov 2 Glimmer paragraph) and What the real loop needs, with link targets fixed for use from docs/.
- `docs/architecture.md`: new page with the moved The pieces and Code off the card path sections, plus a Components flowchart of the framework packages with each arrow read from the import lines.
- `docs/glossary.md`: new page with the moved Words I use below (renamed Words I use) and About the Venn diagram sections.
- `README.md`: I added the three stills (the Nov 3 20:30 card, the Nov 2 15:30 check, one Catch the AI round), a third diagram of one card in time checked against the orchestrator, a Results section holding the Nov 2 Glimmer paragraph and a six-row table of measured results, and a Documentation table of the pages under docs/.
- `CONTRIBUTIONS.md`: this entry.

Claude Code made the three stills from the demo video's frames, which had passed its frame-by-frame privacy check, wrote this specification and started this session from a prose prompt, and Muse Code (muse-spark-1.3, medium effort) moved the sections, wrote the new sections and diagrams and checked them against the code.

## Docs 8c (2026-11-04)

I committed the final live-run page and the provenance log. Docs only: no behaviour, schema, fixture or test change.

- `docs/live-run.md` holds the final numbers of the live run, frozen at the 18:30 cut and regenerated from `make metrics` with every number naming its report key.
- `docs/provenance.jsonl` now has a line for every card of the run, written by the export command and committed unedited.
- `CONTRIBUTIONS.md`: this entry.

Claude Code generated both files with read-only scripts and started this session from a prose prompt, and Muse Code (muse-spark-1.3, low effort) committed them unedited.

## Checker clarity (2026-11-04)

I made the checker page say which side is the truth and what each sentence was checked against. No checker rule changed: the page still runs the same check in the browser.

- `docs/verify/index.html`: step 1 now reads "The card: your record, the truth" and step 2 reads "The sentence: what the AI wrote, checked against the card", with the same step numbers, strong text and input label as before.
- `docs/verify/verify_page.py` and `docs/verify/index.html`: each plain-form claim now shows "What it checked" built from the pairs the checker made for that claim, with the number as written and the card row name and number as typed, then the fixed limit line; when a claim names no card row, its finding also lists the card rows as typed, and the code line under it is unchanged.
- `tests/test_verify_page.py` and `tests/test_verify_page_plain.py`: I updated the old scope line pins to the new wording and added the first-time user case, the wrong number case, the matching number case and the step label pins.

- One sentence on the page now says the check compares the numbers on a card, not every number.

Claude Code started these sessions from prose prompts and Muse Code made the edits: muse-spark-1.3 at medium effort for the page and tests, then at low effort for the one-sentence fix and a neutral test example.

## Docs 10 (2026-11-04)

I aligned the README with the demo story and reported the finished live run. Docs only: no behaviour, schema, fixture or test change.

- `README.md`: I rewrote the opening around what ikigai means and goals that stop competing, and I closed the first screen by introducing the checker as an extra anyone can try without setting up the system.
- `README.md`: the Results section now gives the registered run's results from docs/live-run.md, R7 and R8 included, the two that went against me.
- `README.md`: two wording fixes now that the run has ended, in How it works and in What works today and what doesn't, plus the closing paragraph on balance over time.
- `docs/r9-audio.md`: it now states that Chatterbox and Whisper were evaluation tools only, never called by the product, and that every model the product calls at runtime is a Meta model.
- `CONTRIBUTIONS.md`: this entry.

Claude Code started this session from a prose prompt and Muse Code (muse-spark-1.3, low effort) made the edit.
