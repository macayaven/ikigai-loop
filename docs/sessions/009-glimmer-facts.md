# Session evidence — 009-glimmer-facts (2026-11-01)

Ticket 9 only; two sessions per ticket (plan, then implementation). This
note summarises the work.

The plan was written with muse-wonder-1.0 at high effort, in an interactive
session I ran. That session also wrote a first draft of four files
(`framework/glimmer/schemas.py`, `metrics.py`, `prompt.py`, `checks.py`)
before I stopped it.

Implementation and fixes were muse-spark-1.3 at medium effort, in headless
sessions Claude Code started (implementation, four rounds of fixes,
this note, the commit). Prompts and review by Claude Code. The raw session
exports are kept privately.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Plan

- Plan: `docs/plans/009-glimmer-facts.md` (implemented as written: C1–C8,
  D2, D4, D5, D6, the replaced D1, and the rejected D3).
- The fact layer is implemented exactly as briefed: `framework/glimmer/`
  (pure core plus CLI-edge client), `framework/store/fact_store.py`
  (append-only cycles/facts/responses in the existing DB file),
  `framework/cycle/` (`run_cycle` seam plus the counts-only `facts` CLI),
  `evals/` replay task plus the 6-known-good / 24-mutant meta-eval, and 8
  test files. No manifest, renderer, deployer, attention,
  Wonder decision, jury, or `framework/blocks/` change (C1, C3); the
  allowlist is step 1 with no exception and dropped types are byte-identical
  absent (C2, F9); no per-profile split (C4); `.env.example` gains only the
  two pinned lines (C5); no model name or path is hardcoded — only the last
  path component of the server `model` field is ever recorded (C6, item 3);
  only the T9 counts are claimed (C7: 6 known-good + 24 mutants); facts are
  objective-agnostic, no profile/dimension/ikigai import in
  `framework/glimmer/` (C8).
- Disagreements resolved as pinned in the plan: pinned window/caps/budget
  (replaced D1); dropped rows are compared against nothing, check 3 consults
  kept winning rows only (rejected D3, pinned by F9); latency/model/
  `finish_reason` travel inside `LLMResponse` (D2); `OUT_OF_WINDOW` is
  defensive at check level (D4); no snapshot keys for issue/release (D5);
  the core mints content-hash IDs and the highest-evidence tier (D6, item 13).
- Every `uv`, `pre-commit`, and `git` command in this session ran under
  `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
  `UV_CACHE_DIR="$PWD/.git/uv-cache"`.
- Departures from the plan's letter, each stated as what the code does and
  why: (1) the eval file bootstraps `sys.path` to the repo root so the
  exact AT10 command works under the Inspect loader; (2) the `Case` record
  carries small harness fields beyond the plan's eight
  (`expected_statements`, `expected_personal`, `expected_feed`,
  `via_store`); (3) `check_fact` runs the winning-membership half of 1a
  before 1b, matching the plan's table order; (4) the cycles row records
  `latency_ms` as the pass sum, and `raw_valid` as true when at least one
  pass ran and every pass that ran was valid — the plan pins the columns,
  not the aggregation; (5) a repair retry that raises records
  `NOOP_LLM_UNAVAILABLE`, and one that truncates records
  `NOOP_LLM_TRUNCATED` — a malformed 2xx envelope maps to
  `LLMUnavailableError`; (6) null or absent `message.content` becomes empty
  text with `finish_reason` kept, so `length` gives `NOOP_LLM_TRUNCATED`:
  the real model's reasoning-exhausted answer has no content, and calling it
  unavailable would hide why; (7) markers are stripped until none remain,
  from feed titles as the plan says and also from each personal event line,
  because a repo value can carry them; (8) the count arm treats cited
  `calendar.event.created` and `calendar.event.updated` rows as one family,
  since both are live blocks — cited repo names and their `/` segments join
  `known_ids`, so a digit inside a cited repo name is not read as a number;
  (9) `as_of` is pinned to its own fixed offset before any arithmetic,
  because subtracting from a named-zone datetime is wall-clock time and gave
  a 25-hour period across a DST change; (10) the client refuses redirects,
  because urllib would carry the `Authorization` header to the new location
  — `LLMUnavailableError` carries `latency_ms`, so a pass that timed out
  does not report `0.0s` — `load_llm_config` rejects a malformed key or base
  URL, naming the variable only — `FactDraft.statement` and
  `FeedTopicDraft.topic` strip edge whitespace, and a blank one fails
  validation; the exported schemas did not change; (11) plan step 10 and
  AT13 describe a second commit for the live lines — the seeded run happened
  before the commit, so this one commit holds its line — the real-data line
  is added when that run happens; (12) live run (a) seeded the larger table
  described under Live runs instead of `base_case()`, to repeat the
  conditions of the earlier probes; (13) `ruff format` reflowed the Python
  block in the plan, because `ruff format --check .` covers Markdown — no other plan text changed; (14) cited repo names are blanked before the number check, because Ticket 10's parser reads `seven` in `example-user/seven-tower` as the number 7, and `known_ids` only masks a name holding a digit.

## Implementation

- Files: `docs/plans/009-glimmer-facts.md` (given),
  `framework/glimmer/` (`__init__.py`, `schemas.py`,
  `metrics.py`, `prompt.py`, `checks.py`, `facts.py`, `llm.py`),
  `framework/store/fact_store.py`, `framework/cycle/` (`__init__.py`,
  `__main__.py`), `framework/schemas/export_schemas.py` (4 draft schemas
  appended, nothing else), 4 `schemas/*.json` (generated, exactly 4 added),
  `.env.example` (2 lines plus the pinned comment), `evals/glimmer_cases.py`,
  `evals/glimmer_facts.py`, 8 test files, `CONTRIBUTIONS.md`, and this note.
- Draft review (the four unreviewed `framework/glimmer/` files): `schemas.py`
  and `metrics.py` matched the plan line by line (one behaviour-preserving
  ruff autofix, `removesuffix`, in `metrics.py`). Three known defects, each
  with a committed test: (1) `prompt.py` used `str.format` on templates with
  literal JSON braces, so both builders raised `KeyError` — replaced with a
  single-pass regex substitution, pinned by
  `test_prompt_literal_braces_unchanged` (`{feed_lines}` in a title and
  `{period_json}` in an event value pass through); (2) `checks.py`
  `_family_match` had an unreachable second `screen_hours` branch — removed,
  pinned by `test_family_match_has_single_screen_hours_branch` plus the
  category-presence family tests; (3) `checks.py` period backing used the
  row's start time for `tag_hours`, dropping true statements about periods a
  crossing block overlaps — period `tag_hours` now requires clipped overlap,
  cancelled rows back only `cancelled.<tag>` keys (never `tag_hours` or
  busy), and `cancelled.<tag>` keeps start-time assignment as
  `build_period_rollup` does, pinned by
  `test_period_tag_hours_requires_overlap_not_start`,
  `test_cancelled_row_backs_only_cancelled_keys`, and
  `test_cancelled_period_uses_row_start_time` (F19 pins the wrong-period
  drop end to end). The single-pass substitution in `prompt.py` still stands
  on the final tree: data is inserted verbatim with no second scan.
- Tests were written before the packages and failed on collection with
  `ModuleNotFoundError: No module named 'framework.glimmer.facts'`.
- Public-repo sweep over every touched file: no real names, values, contact
  details, or device IDs (all fixtures use `subject-1`, invented
  repos/titles/tags/categories, and frozen instants); no host beyond
  `example.invalid` and the pinned mock names; no private path; no secret
  (the only key-shaped string is the test sentinel `secret-key-xyz`,
  asserted absent from every exception); server model strings appear only as
  synthetic test doubles and only their last path component is ever recorded
  (POSIX/Windows/`"unreported"` pinned in `test_glimmer_llm.py`); no stored
  `reasoning_content` anywhere (`content` only, asserted never to contain
  it). I never opened `HIDDEN_CRITERIA_DIR` in this session.

## Review: what running it found

The reviewer ran the code from scratch scripts kept outside this repo: real
collectors, a fake server on loopback, hostile model output, and deliberate
breaks in a scratch copy. Each item below names its fix, in plain terms.

- **A true statement dropped.** Period keys for a screen category, a tag or
  a cancelled tag are absent when zero, so `Media/Video screen hours rose
  from 0 in prior to 4.0 in last.` dropped `FACT_NUMBER_UNBACKED`. A zero
  token is now backed when a cited row's family has no value in some period.
  The real model's five statements from the earlier probe are now a
  regression test, and the live run below wrote one statement of this kind.
- **The key could reach a traceback.** A key with a trailing newline made
  `http.client` raise a `ValueError` holding the whole header, and the CLI
  printed it. A bad base URL did the same with the URL. Only a test sentinel
  was exposed. `complete()` now raises only `LLMUnavailableError`, with
  fixed text and no chained exception.
- **Exceptions escaped.** A dropped connection, a short body and a bad
  status line crashed the CLI and lost the other pass. So did
  `decimal.InvalidOperation` on a 30-decimal number, `RecursionError` on deep
  JSON, and every database error. The CLI now prints one
  `error: <ExceptionClassName>` line and exits 1, and reads its config
  before opening a database.
- **Counts could be inflated.** `Exactly 7 pushes` citing one row seven times
  was kept. Evidence is now de-duplicated before any check.
- **Blank text.** A whitespace-only statement or topic was kept, and a topic
  could hold newlines. Blank now fails validation, and topic whitespace
  collapses.
- **Identity.** Replay identity included latency, against the plan's list. A
  repeat with the same content now returns the same run. `raw_valid` could
  never be true for a cycle with no feed rows.
- **Boundary.** `feed.item.count` and per-source feed counts reached the
  personal prompt. `<<>>><FEED_DATA` survived one pass of marker stripping
  as `<<<FEED_DATA`. Both fixed. Non-ASCII titles bypassed the five-word
  overlap check. Fixed.
- **Dedup.** The logical keys included `source`, against the plan, so one
  invite on two calendars counted twice. The screen key compared local text,
  not the instant. Both fixed.
- **Tests that did not fail when the code was wrong.** 66 deliberate breaks
  in a scratch copy: 46 caught, 20 passed every test. After the fixes and new
  tests: 117 breaks, 114 caught. The three that still pass change nothing observable: `rsplit` already removes `#cancelled` with the last segment, the always-present push and PR keys are handled by the older arm, and the order repo names are blanked in can't matter, because a name only matches where it stands alone.
- **Fuzz.** 20,000 generated batches and 33 hand-picked malformed answers
  through `extract_facts` after the fixes: no exception escaped, no fact
  broke its invariants. 124 checks of the client against a fake server on
  loopback (500, 503, 401, 404, a hang, a dropped connection, a short body,
  a bad status line, malformed JSON, HTML, redirects, truncation, the repair
  retry, a newline in the key) and 79 checks of the CLI's failure paths all
  pass.

## Moving onto Ticket 10

Ticket 10 merged first, so this tree moved onto it. The reviewer re-ran
everything on the moved tree. What that turned up:

- One import conflict in `framework/schemas/export_schemas.py`, resolved by
  keeping both sides. Regenerating the schemas changed no file.
- Ticket 10's parser now reads spelled numbers. The 35 statements Muse Glimmer
  wrote in the recorded probes and the live run below hold none, and all 35
  still keep.
- One regression, fixed: a repo name holding a number word read as a number,
  so `Pushes to example-user/seven-tower happened in last.` dropped
  `FACT_NUMBER_UNBACKED`. The number check now blanks the names of cited
  repos. The leak and overlap checks still read the original statement.
- A real snapshot through `metric_label_binding`: all 30 keys of the live
  run's snapshot bind, and so do all 48 of a synthetic snapshot using the
  collectors' real category, tag and source names. A test pins this.
- The live run's facts as claims through `evaluate_briefing`, with metric
  refs holding the snapshot's exact values: the pushes, pull request,
  Work/Programming and Comms/Chat statements pass. `Cancelled iki-deep blocks
  were 0 in earlier and 1 in prior.` fails `L1B_UNKNOWN_METRIC`, because a
  zero period key for a screen category, a tag or a cancelled tag is absent
  from the snapshot. A later ticket is planned to add those keys.
- A ref holding the rounded value from the prompt fails
  `L1B_METRIC_VALUE_MISMATCH`, so whatever writes a ref must copy the value
  from the snapshot by code. A feed fact quoted with its count fails
  `L1B_NUMBER_WITHOUT_METRIC_REF`, because no metric holds a topic's count.
  Quoted without the count, it passes.

## Known limits, measured

Each is real, and none is hidden.

- Truth is not checked. Measured on the live table: `Work/Programming screen
  hours rose from 7.0 in earlier to 4.75 in prior.` (wrong direction),
  `Work/Programming screen hours were 4.75 in earlier and 7.0 in prior.`
  (labels swapped), and `Comms/Chat screen hours fell from 7.0 in earlier to
  4.75 in prior.` (wrong category, on rows holding both) are all kept.
  Ticket 10's gate now checks a claim that carries metric refs. On the same statements, the wrong direction fails `L1B_DIRECTION_MISMATCH`, the wrong category fails `L1B_METRIC_LABEL_MISSING`, and the swapped labels still pass.
- Step 1 filters on `time` as the plan says. A calendar block that started
  before the window contributes nothing, even where it overlaps the window.
  A recurring instance moved past `as_of` keeps counting at its old time.
- A moved non-recurring block reads as one cancelled block and one new
  block, because that is what the collector emits. When one invite sits on
  two calendars and is cancelled on one, the later `collected_at` wins.
- A feed topic carrying a version number (`GPT-4`) or a spelled number (`Two-stage retrieval`, `Top ten tricks`) drops `FACT_FEED_TOPIC_SHAPE`, by the plan's rule and Ticket 10's parser. `One-shot learning` is kept.
- A true statement holding a number nothing backs still drops `FACT_NUMBER_UNBACKED`: `Pushes happened in each of the three periods.` citing two rows, or `Pushes happened in each 24-hour period.` No recorded statement from the real model has done this.
- A mistyped `--db` creates an empty database and prints a noop line with no
  model call. A read-only database loses the model's answers after the calls
  are made: the CLI prints `error: <ExceptionClassName>`.

## Acceptance results

On top of `main` at `8419879`. All with the env prefix, run by the reviewer
outside any sandbox on this tree.

- AT1 `uv run pytest tests/test_glimmer_metrics.py tests/test_schemas_export.py`: exit 0, 17 passed.
- AT2 `uv run pytest tests/test_glimmer_checks.py tests/test_glimmer_llm.py`: exit 0, 67 passed.
- AT3 `uv run pytest tests/test_glimmer_facts.py -k "dropped or allowlist or collected"`: exit 0, 15 passed.
- AT4 `... -k "truncated or unavailable or invalid or repair or raises"`: exit 0, 12 passed.
- AT5 `... -k "determin or replay or alias or tier or cap"`: exit 0, 9 passed.
- AT6 `uv run pytest tests/test_glimmer_mutants.py`: exit 0, 38 passed (6 known-good and 24 mutant cases exact, counts asserted).
- AT7 `uv run pytest tests/test_glimmer_mutants.py -k "F10"`: exit 0, 9 passed.
- AT8 `uv run pytest tests/test_fact_store.py tests/test_store.py`: exit 0, 21 passed.
- AT9 `uv run pytest tests/test_cycle_cli.py tests/test_glimmer_eval.py`: exit 0, 18 passed.
- AT10 the plan's Inspect command: exit 0 offline, log `logs/2026-11-01T14-44-09-00-00_glimmer-facts_UsFfh5JcRBomZkLqwcyDCG.eval`. `make eval` unchanged.
- AT11 `grep -n "LOCAL_LLM" .env.example`: exactly 3 lines, all empty values. `git diff .env.example` adds the comment and the two lines.
- AT12 (base negative control), run on a scratch export of `main` with the two test files copied in: collection fails (2 errors, exit 2), and `framework/glimmer` is absent.
- AT13 `make check`: `ruff check`, `ruff format --check`, `pyright` with 0 errors, the full `pytest` with 764 passed, including the loopback test in `tests/test_ingest.py` that fails only inside a Muse sandbox, and `gitleaks`. The Ticket 9 suites alone are 196 tests. `tests/Untitled` stays untracked. No push.

## Live runs

(a) Seeded scratch run, run by the reviewer against Muse Glimmer through
this code, on a scratch database with synthetic rows only. 82 rows through
`EventStore`: 44 personal rows (the table from the earlier probe, in real
collector `source_id` shapes), 21 feed rows in real shape including two
prompt-injection titles, 3 superseded rows (calendar, screen, feed), 12 rows
of dropped types with marker values, one row collected after `as_of`, one
row at exactly `as_of`. Printed line:

```
cycle=<redacted> run=1 kept=11 dropped=0 noop=- personal=6:-:456.0s:stop feed=5:-:265.3s:stop codes=-
```

Personal pass: 6 kept, one attempt, 6,022 completion tokens. Feed pass: 5
kept, one attempt, 3,581 completion tokens. About 12 minutes in all. No
fact dropped, no repair retry. The prompts held 44 and 21 rows, and no
marker value, superseded row, tier, `source_id` or real ID.

The six personal statements, each read by the reviewer against the code's
table, all true:

- `GitHub pushes were 3 in earlier and 1 in prior.`
- `GitHub pull requests were 0 in earlier and 1 in prior.`
- `Work/Programming screen hours were 7.0 in earlier and 4.75 in prior.`
- `Comms/Chat screen hours were 1.27 in prior and 3.45 in last.`
- `In prior, a GitHub pull request opening and a GitHub push occurred in the same period.`
- `Cancelled iki-deep blocks were 0 in earlier and 1 in prior.` (this one needs the zero rule above; it would have dropped before the fix)

The five feed labels: `On-device inference optimization` (5 items), `Agent
systems evaluation` (4), `Retrieval and vector search` (2), `Prompt
engineering and reliability` (3), `Model benchmarks and distillation` (2).
They are loose but defensible by reading, and nothing proves them. Neither
injection title was cited, and no fact carries their instructions. That shows
one run on this model, not a defence.

The model again missed the largest change in the table, Media/Video from 0
in prior to 4.0 in last. Its statements about what changed are true, and
whether they are the ones that matter is not something this layer decides.

Replaying the recorded answers through the core on the final tree gives the
same `prompt_hash`, snapshot and kept facts, and recording them returns the
same run. The live run used the client as it stood after the first round of
fixes. The second round changed how the opener is built and the latency on a
bad envelope. The final client was checked against the same endpoint with a
model name that does not exist: it got a 404 and loaded nothing. The live run also predates the move onto Ticket 10. The replay ran on the moved tree, with the wider parser and the repo-name mask, and its result did not change.

(b) Real-data run, on a copy of the real database:

`cycle=<redacted> run=1 kept=9 dropped=0 noop=- personal=4:-:464.2s:stop feed=5:-:186.4s:stop codes=-`

Run on Nov 1 on a copy of my real store of 1,000 rows, on the Spark, through llama-swap, in about 11 minutes. Claude Code read the statements in review and checked them against the rows. Of the 4 personal statements, 1 was a real comparison across periods, and its numbers match the rows. The other 3 were co-occurrence counts nobody would act on, and all 3 undercount: 4 where the period has 11 such rows, 4 where it has 9, and 3 where it has 8. Each number is how many rows the model cited, and `check_fact` accepted that as backing, so "kept=9 dropped=0" hides a hole in this ticket's checks. The fix goes in Ticket 9b. The 5 feed labels fit the items they cite, one of them loosely, and no statement tripped the private-term check. The largest category in that run was 'other', which is why Ticket 7b maps more apps.
