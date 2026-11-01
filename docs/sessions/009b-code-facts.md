# Session evidence — 009b-code-facts (2026-11-01)

Ticket 9b only. This was a headless run: nobody could answer questions,
so I decided every open point below and give the reason with each one.

Plan by muse-wonder-1.0 (effort high). Implementation by muse-spark-1.3
(effort medium), in Muse Code, in a headless session Claude Code started.
Prompts and review by Claude Code.

`muse --version` (this session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## What I built

On branch `t9b-code-facts`, built from main `e126366`; Claude Code
moved the uncommitted work onto main `301e413` before the commit, with no
conflict, per [docs/plans/009b-code-facts.md](docs/plans/009b-code-facts.md):

- `framework/glimmer/code_facts.py` (new): `HOURS_FLOOR`, `COUNT_FLOOR`,
  `SCREEN_SKIPPED_CATEGORIES`, `SCREEN_DISPLAY_NAMES`, `CodeFact`,
  `code_facts`, `format_metric_value`, `is_duplicate_of_code`. Pure,
  stdlib plus existing repo imports only.
- `framework/glimmer/metrics.py`: D7 zero keys in `build_metric_snapshot`
  only; the rollup is untouched.
- `framework/glimmer/checks.py`: D19 cited-count replacement only; the
  zero rule is untouched.
- `framework/glimmer/prompt.py`: D16 CODE FACTS block and do-not-restate
  rule, the D19 number-rule line, `code_fact_statements=()` parameter.
- `framework/glimmer/facts.py`: code facts minted and kept before the
  personal pass (`CODE_`-prefixed drops, outside `MAX_FACTS`),
  `FactResult.code_fact_ids`, `personal_pass`/`feed_pass` flags with
  `NOOP_PERSONAL_SKIPPED`/`NOOP_FEED_SKIPPED` checked before the
  nothing-to-read reasons, the D12 duplicate drop, model-only cap and
  per-pass deltas. The locals `personal_pass`/`feed_pass` are now
  `personal_result`/`feed_result`, since the names belong to the new
  keywords (pyright strict stays clean).
- `framework/glimmer/__init__.py`: the D20 constants and helpers
  re-exported.
- `framework/store/fact_store.py`: D10 `origin` column, a migration at
  open that takes `BEGIN IMMEDIATE` only on an old file, origin in
  inserts, `fetch_facts`, and replay identity on both sides.
- `framework/cycle/`: pass flags threaded through `run_cycle`, CLI flags
  `--no-personal-pass`/`--no-feed-pass`, `code=`/`model=` in the line, and
  the never-called stub when both passes are off.
- `evals/glimmer_cases.py`: the live fixture moved here unchanged as
  `LIVE_ROWS`/`live_table_events`/`LIVE_CONTENT`, plus the hand-derived
  re-baselining below.
- Tests: new `tests/test_glimmer_code_facts.py` (52 tests, C1–C21 and
  C27) plus 22 added tests across the five existing files (C22–C26).

Every `uv`, `pre-commit` and `git` command in this session ran under
`PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
`UV_CACHE_DIR="$PWD/.git/uv-cache"`.

Tests were written before the implementation and failed on the base for
the right reasons (AT7; the missing zero key probe below).

Public-repo sweep over every touched file: fixtures use `subject-1`,
invented repos/titles/tags/categories, and frozen instants; no host
beyond `example.invalid` and the pinned mock names; no private paths; no
secrets. HIDDEN_CRITERIA_DIR was never opened.

## Deliberate pin break

`tests/test_cycle_cli.py::LINE_RE` changed on purpose (D15): `kept=3`
is now `kept=7 code=4 model=3` on the base seed (4 code facts plus the 3
model facts). The `code=`/`model=` segments are new.

## Changed assertions with hand-derived values (D18)

Method: I derived each case's code facts from its rollup on paper
(period values from event times, tags, and minutes) and wrote the
expectations first; the implementation run afterwards only confirmed
them. No expectation below was pasted from a program run.

Fixture (all five): Media/Video prior to last rose 4.0 (beats
Work/Programming's 3.0 and Comms/Chat's 2.18); pushes earlier to prior
fell 2 (periods hold 3, 1, 0); prs tie 1/1, later pair wins, prior to
last fell; iki-deep prior to last fell 3; cancelled iki-deep tie 1/1,
later pair wins, prior to last fell.

`evals/glimmer_cases.py`:

- `base_snapshot` gains 4 zero keys: earlier.Programming 0.0 (prior
  6.75, last 2.0, no earlier rows), earlier.Social 0.0, prior.Social 0.0
  (Social only in last at 0.5), prior.tag.iki-focus 0.0 (earlier 1.5,
  last 2.0, no prior rows).
- New `base_code_statements` (4): Programming earlier to prior rose 6.75
  (changes 6.75 vs 4.75); Pushes prior to last rose 2; Pull requests
  prior to last rose 1; iki-focus prior to last rose 2 (changes 1.5 vs
  2.0).
- G1: kept 3 to 7, statements 4 code plus the 3 model lines.
- G2: kept 1 to 2, statements ("Pushes rose from 0 in prior to 2 in
  last.", model). Pushes hold 0/0/2.
- G3: kept 0 to 4, noop NOOP_NO_FACTS to None, statements 4 code.
- G5: kept 1 to 3; 2 zero keys (earlier/prior tag 0.0; the block sits in
  last at 2.0); statements (pushes "rose 0 to 1", tag "rose 0 to 2",
  model).
- G6: kept 1 to 2; 1 zero key (earlier Programming 0.0); statements
  (screen code earlier to prior 6.75, model). The model line names
  prior and last against code periods earlier and prior, so it stays
  kept.
- F1/F3/F4: kept 0 to 1, noop to None, statements ("Pushes rose from 0
  in prior to 1 in last.",). One push in last; drops unchanged.
- F6: kept 0 to 2, noop to None; 2 zero keys (earlier/prior Programming
  0.0; last holds 4.5); statements (screen "rose 0 to 4.5", pushes "rose
  0 to 2"). The model "4.5 hours" still drops NUMBER_UNBACKED (cited
  pushes only).
- F7: kept 1 to 2, statements (pushes code, feed line).
- F8: kept 1 to 2, statements (pushes code, model). The model line has
  no number token, so no duplicate match.
- F9/F13: reuse `base_case()` expectations verbatim (now 7 kept).
- F10a: kept 2 to 3, statements (pushes code, personal, feed).
- F10c: kept 1 to 2, statements (pushes code, personal).
- F11: kept 0 to 1, noop to None; 2 zero keys (earlier/last
  cancelled.iki-trip 0.0; prior holds 1); statements ("Cancelled iki-trip
  blocks fell from 1 in prior to 0 in last.", tie broken to the later
  pair).
- F12: kept 1 to 2; 2 zero keys (earlier/prior Programming 0.0; last
  2.0); statements (screen "rose 0 to 2", model). The model line names
  only last, so rule (b) cannot match and it stays kept.
- F14: kept 1 to 2, statements (pushes code, feed line). F15 inherits.
- F16: kept 1 to 2; 2 zero keys (earlier/prior tag 0.0; the block is
  clipped to 2.0 in last); statements (tag "rose 0 to 2", model). The
  model line names no period, so it stays kept.
- F18: kept 0 to 1, noop to None, statements ("Pushes rose from 0 in
  prior to 7 in last.",). Seven pushes hold 0/0/7.
- F19: kept 0 to 1, noop to None, statements (screen code earlier to
  prior 6.75,). The model line names the third period, so it reaches the
  normal checks and still drops FACT_NUMBER_UNBACKED.
- F2/F5/F10b/F10d/F10e/F10f/F17 and G4: confirmed unchanged (no personal
  rows, or an empty window).
- `expected_personal`/`expected_feed` unchanged in all 30 cases (the
  deltas equal the old kept counts). No `expected_dropped` changed.

`tests/test_glimmer_facts.py`:

- `test_unknown_alias_drops`: facts () to the pushes code line (one push
  in last survives the unknown-alias drop).
- `test_alias_in_statement_drops`: facts () to the pushes "rose 0 to 7"
  line.
- `test_tier_minted_as_highest_evidence_tier`: G1 tiers gain the code
  tiers in front ([private, public, public, private]: screen/tag rows are
  private, pushes/prs public); G5 gains [public, private].
- `test_max_facts_cap_overflow`: 12 to 13 facts, facts[0] the pushes code
  line, dropped still [FACT_OVER_LIMIT], personal.kept 12.
- `test_duplicate_aliases_do_not_inflate_cited_count`: facts () to the
  pushes code line; dropped still [FACT_NUMBER_UNBACKED].
- `test_kept_evidence_has_no_duplicates`: 1 to 2 facts; the model
  evidence is still exactly [push.id], now at facts[1].
- `test_blank_statement_takes_repair_retry`: 1 to 2 facts.
- `test_duplicate_statement_and_evidence_drops_second`: 1 to 2 facts.
- `test_duplicate_with_swapped_evidence_order_drops_second`: 1 to 2
  facts (two pushes: code "rose 0 to 2" plus one model fact).
- `test_live_model_output_all_five_kept`: 5 to 10 facts; facts[:5] the
  pinned five; `code_fact_ids` matches; personal.kept 5, feed.kept 0;
  tiers code [private, public, public, private, private] then model
  [public, private, private, private, private].
- `test_failed_personal_pass_keeps_feed_facts`: 1 to 2 facts; facts[0]
  the pushes code line.
- Three new C21 prompt tests (block header, the five lines,
  do-not-restate rule, `- none` state, the D19 number line, feed prompt
  without the block).
- All other tests in the file confirmed unchanged (pass fields, prompt
  bytes, snapshot values, store/CLI error paths).

`tests/test_glimmer_mutants.py`:

- `test_F10a_prompt_isolation_both_directions`: 2 to 3 facts, facts[0]
  the pushes code line. The block holds no feed text, so isolation
  stands.

`tests/test_cycle_cli.py`:

- `LINE_RE` (deliberate, above) and `fetch_facts` 3 to 7 in
  `test_second_run_replays_same_run_number`. Three new C23 flag tests.

`tests/test_fact_store.py`: three new C22 tests; the round-trip test is
unchanged (it reads single keys, and origins are pinned in the new test:
code 4 then model 3 on the base case).

`tests/test_glimmer_eval.py`:

- `test_scorer_rejects_tampered_expectation`: tamper value 1 to 2,
  because F3 now keeps 1 (the pushes code fact).

`tests/test_glimmer_metrics.py`: two new C24 tests (one-period member
gains 0.0 in the other two; an all-zero member gains no key). The empty
window test is unchanged.

`tests/test_glimmer_checks.py`:

- `test_created_and_updated_share_one_count_family` renamed to
  `test_calendar_block_count_needs_snapshot_backing`: "3 calendar blocks
  and 1 push in the last period" kept to FACT_NUMBER_UNBACKED (no
  snapshot metric counts blocks); added "1 push in the last period"
  citing the push, kept via period.last.pushes.
- `test_spelled_numbers_backed_by_cited_count` renamed to
  `test_spelled_numbers_backed_by_snapshot_count`, assertions unchanged
  (still passes, now through period.last.pushes at 2.0).
- Comments at :102, :405 and :487 reworded (cited counts no longer back
  numbers outside feed citations); assertions there unchanged.
- `test_personal_batch_without_tier_field_validates`: 1 to 2 facts;
  facts[0] the pushes code line; the tier assert moved to facts[1].
- Seven new C26 tests.

New file `tests/test_glimmer_code_facts.py`: 52 tests (C1 to C20 plus
C27; C21 lives in the facts file, which the plan allows; every case
value there re-derived from its own rollup).

## Fixture sensitivity (a test that cannot fail is worthless)

Each pinned guard below fails if its rule is removed; I checked all
four, three in a scratch process and one as a committed twin:

- Evidence reservation: with the reservation patched out in-process, the
  9-row fixture fact drops CODE_FACT_NUMBER_UNBACKED and facts go []. The
  committed test asserts it is kept, so it fails without the reservation.
- Either old cited-count clause: a replica of the number loop with the
  `type_counts` clause restored keeps the 4-of-11 draft (Cat/A and Cat/B
  total 1.83 hours, so the snapshot cannot back the 4). The committed
  test asserts the drop, so restoring either clause fails it.
- `all` to `any`: the same replica with `any()` keeps the mixed
  feed-plus-push citation (3 feed rows in the window, so no snapshot
  value is 2). The committed test asserts the drop.
- The zero key: the committed screen "to 0" gate twin passes with the
  key and fails with exactly L1B_UNKNOWN_METRIC without it.

## Decisions and departures

- C2: the fixture has no feed rows, so a strict reading gives the feed
  pass NOOP_NO_FEED_ITEMS, never a model call. I added two feed rows so
  both passes call the raising stub and both report NOOP_LLM_UNAVAILABLE.
  Reason: that is the ticket's intent (total model failure), and the
  code short-circuits nothing-to-read before any call by design.
- The CODE FACTS prompt block and the duplicate check use kept code
  facts only. Reason: a dropped code fact is a template bug, not output
  the model should avoid restating.
- F9/F13 reuse `base_case()` expectations verbatim. Reason: the base
  case already carries the new values, so copying them would fork the
  source of truth.
- CLI with both passes off uses a never-called stub (raises on any
  call). Reason: `run_cycle` requires an `llm` argument; this is the
  smallest reading of "does not build the client", per X7.
- `ruff format` touched the plan file: 3 blank-line insertions in the D1
  sketch, wording unchanged (the Ticket 9 precedent).
- My first reading of the threaded migration failure was wrong: I had
  added a retry on "database is locked" and blamed suite load. Review
  found the real cause: `_write_previous_schema_db` creates a
  rollback-journal file, and `PRAGMA journal_mode=WAL` on such a file
  needs an exclusive lock, so two openers collide at that pragma (two
  threads opening at once, 150 rounds per file kind: 17 of 300 opens
  failed with `database is locked` on a rollback-journal file, 0 of 300
  on a WAL file). The fixture now runs `PRAGMA journal_mode=WAL` right
  after connecting, matching main's real files, and the retry is gone.

Cycle ids move once: D7 zero keys and the D16 prompt block change
snapshots, prompt bytes, and therefore `cycle_id` versus Ticket 9. Old
runs stay stored and readable; nothing is backfilled.

## Review fixes

Headless review-fix session on the same branch. I decided each point
below; the reason sits with each one. No commit made; the change stays
uncommitted.

- Fix 1: the three zero-key loops in `build_metric_snapshot` now iterate
  `sorted(...)`, so snapshot key order never depends on the hash seed.
  Reason: the loops ran over sets, and a reader enumerating metric ids
  would see different prompt bytes across processes.
- Fix 2: `_write_previous_schema_db` now sets WAL right after connecting,
  and the retry left the concurrent test. Reason: my suite-load reading
  was wrong; the pragma collision on rollback-journal files was the cause
  (see the corrected bullet above).
- Fix 3: `_migrate_origin` reads the column list with no transaction and
  returns when `origin` is present; only an old file takes
  `BEGIN IMMEDIATE`. Reason: a reader opening the store while a cycle
  writes stalled 5 s or failed, which is a regression against main.
- Fix 4: `test_ai_template_claim_passes_gate_and_swap_fails` now builds
  from real output like the C14 round trip and runs both citation forms.
  Reason: the plan asks for both forms and the old test typed its metrics
  by hand.
- Fix 5: five new tests in `tests/test_glimmer_code_facts.py`, two new
  format rows, two extended tests, and one new prompt-order assertion in
  `tests/test_glimmer_facts.py` pin the gaps a one-line throwaway mutant
  sweep found. Reason: each mutant below survived the suite and each is a
  real gap.

Hand-derived values for every new or changed expectation (D18). I derived
each from its rollup on paper before running; the runs only confirmed.

- Fix 1 `test_zero_keys_written_in_sorted_order`: ten screens of 10
  minutes each (Cat/j down to Cat/a, one row each in last), five live
  blocks of 1 hour (iki-e down to iki-a, in last), five cancelled rows
  (same five tags, in last). In prior every member holds only its zero
  key: 10 screen keys, 5 tag keys, 5 cancelled keys. Each prefixed key
  list in dict order equals its own `sorted()`; the screen list runs
  `period.prior.screen_hours.Cat/a` first and `...Cat/j` last (common
  `Cat/` prefix, `a` < `j`). I checked the mutant too: with the loops
  unsorted the test fails on 8 of 8 hash seeds, and it passes sorted.
- Fix 2: no expectation changed; the concurrent test asserts the same
  (no exception, exactly one `origin` column) with the retry removed.
- Fix 3 `test_open_migrated_file_needs_no_write_lock`: the migrated file
  holds run 1 of the model-only result; while a second connection keeps
  `BEGIN IMMEDIATE` plus `CREATE TABLE _held (x)` open,
  `FactStore(db_path=db)` opens and `runs()` returns `[1]` with no
  retry. I checked the old shape fails it (5.4 s busy wait, then
  `database is locked`). `test_migration_waits_for_a_writer_then_migrates`:
  on a not-yet-migrated file the opener thread waits out the holder's
  0.5 s write transaction, then migrates; no exception, exactly one
  `origin` column. I checked a plain `BEGIN` fails it at once, because
  the deferred read cannot upgrade to the write after the holder commits.
- Fix 4: 60 minutes of `ai` in prior is 1.0, 120 in last is 2.0, earlier
  is 0; the two changes tie at 1.0, so the later pair wins and the kept
  fact reads `AI screen hours rose from 1 in prior to 2 in last.` with
  refs `[1.0, 2.0]`. Both citation forms (`fact_ids=[]` and
  `fact_ids=[kept.id]`) give no violations; the direction swap gives
  exactly `L1B_DIRECTION_MISMATCH`.
- Fix 5 `test_floor_tag_hours_uses_hours_floor`: 45 minutes is 0.75
  hours, at/above the 0.5 hours floor, so `iki-flr calendar hours rose
  from 0 in prior to 0.75 in last.`; 29 minutes is 0.4833 hours, below
  it, so no `tag_hours` fact.
- Fix 5 format rows: `0.125` rounds half-up at 2 places to `0.13`, and
  `1.005` to `1.01` (half-even would print `0.12` and `1.00`); both run
  through `_backs` and `_ref_backs_token` in the same loop.
- Fix 5 `test_evidence_exact_ids_reserve_newest_and_fill_newest`: prior
  is 3 rows of 20 minutes (accumulates to 0.9999999999999999, prints
  `1`), last is 9 rows of 20 minutes (3.0), earlier is 0; prior to last
  (2.0) beats earlier to prior (1.0), so `Ex/Cat screen hours rose from
  1 in prior to 3 in last.` The reservation keeps the newest row of each
  period (`evt_ex_last_08`, `evt_ex_prior_2`); the fill takes the six
  newest remaining rows (`_07` down to `_02`); the final order is newest
  first, which is the pinned eight-id list.
- Fix 5 `test_evidence_block_started_before_from_period`: the block
  overlaps earlier 11:00 to 13:00 (2 hours) and prior 13:00 to 16:00 (3
  hours), last is 0; prior to last (3) beats earlier to prior (1), so
  `iki-cross calendar hours fell from 3 in prior to 0 in last.` The
  evidence is exactly that block (its `time` sits in earlier, so only
  clipped overlap puts it in the prior pool), and the fact is kept
  through `extract_facts` on an empty stub batch.
- Fix 5 `test_evidence_cancelled_and_tag_pools_stay_separate`: cancelled
  counts are earlier 1, prior 2, last 0, so `Cancelled iki-keep blocks
  fell from 2 in prior to 0 in last.` with evidence exactly the two
  prior cancelled rows, newest first. Tag hours are earlier 0, prior 1,
  last 0, a 1/1 tie the later pair wins, so `iki-keep calendar hours
  fell from 1 in prior to 0 in last.` with evidence exactly the live
  block. Each row has its own logical key.
- Fix 5 `test_is_duplicate_unit_rules`: all five live fixture facts match
  their own statement and evidence; the cancelled fact does not match
  `iki-deep blocks fell from 1 in prior to 0 in last.` (no `cancel`);
  the pushes fact (earlier to prior) does not match a statement naming
  `last`; Near/Cat rows of 216/216/264 minutes (3.6/3.6/4.4, change 0.8)
  give `Near/Cat screen hours rose from 3.6 in prior to 4.4 in last.`
  which `Near/Cat stayed near 4 in last.` does not match (one token, one
  period word); `ai` rows of 60/120 do not match `Fair hours rose from 1
  in prior to 2 in last.` (`ai` occurs only inside `Fair`).
- Fix 5 `test_code_drop_visible_and_excluded_from_ids`: the run makes one
  personal prompt; `Top10/Video screen hours rose` is absent from it and
  the block reads `CODE FACTS (already reported by code; do not restate
  them):\n- none\n` (the dropped code fact is excluded from the ids).
- Fix 5 `test_personal_prompt_lists_code_facts_block`: `PERIODS (JSON`
  precedes `CODE FACTS (already`, which precedes `EVENTS (one JSON`.
- `test_second_opener_sees_the_column_the_first_added`: the holder's
  write is the migration itself, so the opener's first read misses the
  uncommitted column, it waits at `BEGIN IMMEDIATE`, and the re-read
  there finds the column. Without the re-read its own `ALTER` raises
  `duplicate column name`.
- The half-up case in `test_is_duplicate_unit_rules`: 7.5 minutes is
  0.125 hours, which prints `0.13`; half-even would give 0.12, which
  does not back that token.
- `test_evidence_time_tie_sorts_by_id`: earlier 6, prior 26, last 2, so
  prior to last (24) beats earlier to prior (20) and `iki-tie calendar
  hours fell from 26 in prior to 2 in last.` The evidence is exactly
  `evt_tie_z`, `evt_tie_b`, `evt_tie_a`, in that order.
- The C26 rows and statement now use the made-up categories `Cat/A`
  and `Cat/B`. The hand-derived values did not change.

## What review found

Claude Code read the whole diff, ran every acceptance test and `make
check`, ran the CLI against a fake model server on loopback with real
processes and scratch databases, and tried to break it from scratch
scripts outside this repo. Each fix went back through a new Muse
session.

- **A migrated file took a write lock on every open.** With another
  connection in the middle of a write, `FactStore` on main opened in
  0.00 s, and this ticket's first version waited 5 s and raised
  `database is locked`. A reader opening the store during a cycle would
  have stalled or failed. The tests passed because none of them opened
  a file while something else was writing. It now opens in 0.00 s.
- **Snapshot key order moved with the hash seed.** The zero keys were
  written by iterating sets, and three seeds gave three orders.
  Anything that enumerates metric ids, such as a per-call enum on
  Wonder's output, would have sent different prompt bytes from each
  process. The order is sorted now, and is the same across 4 seeds.
- **A retry hid a wrong diagnosis.** See the corrected bullet under
  "Decisions and departures".
- **Closing the one line named in the ticket left the hole open.**
  Changing only `checks.py:282` still kept the 4-of-11 statement
  through `:281`, so D19 replaces both clauses, and the prompt rule
  that asked the model for such counts went with them.
- **Tests that could not fail.** On the first implementation, 19 of 98
  one-line source mutants survived the suite, and 16 of those were real
  gaps: which rows the evidence holds, the pools staying separate, the
  tag family's floor, half-up rounding, the duplicate rule's branches,
  the prompt block's place and content, and the migration's lock. Each
  now has a test that catches it.
- **The `AI` claim was tested in one citation form.** It now runs in
  both, from real output.

Limits this ticket leaves in place:

- A number still has no unit. "4 events" stays kept when a cited
  family's value rounds to 4, and a test pins that at 4.03 hours. D19
  removes the cited-row count as a source of backing, not the whole
  class. True counts with no snapshot metric behind them, such as "3
  calendar blocks", now drop.
- The duplicate check is a rule and won't catch everything (list below).
- Exchanging the two cited period words in a claim still passes the
  gate, the limit listed at the top of `framework/briefing/numbers.py`.

## Checks run outside the repo

These scripts are not in this repo. I record them as what was run,
with what came back.

- Motivating case, with no model object at all: "Media/Video screen
  hours rose from 0 in prior to 4 in last.", with 8 evidence rows
  covering 240 of the 240 minutes.
- Gate round trip: each of the five families through a hand-built claim
  and the real `evaluate_briefing` passes in both citation forms. A
  swapped direction gives `L1B_DIRECTION_MISMATCH`, and a third period
  gives `L1B_PERIOD_WORD_MISSING`. Screen "to 0 in last" passes, and
  fails with exactly `L1B_UNKNOWN_METRIC` with its zero key removed.
- Snapshot size: 33 keys on the live fixture against 27 on main, 9 of
  them period zero keys. Ten categories in one period give 20 zero
  keys. No key appears for a member seen only in rows older than the
  window, collected after `as_of`, superseded, belonging to another
  subject, or zero everywhere.
- Templates: 102 sample statements across the real categories,
  including `AI`, trip no text rule in the merged gate.
- An oracle written from the plan's rules, not from the code: 30
  Glimmer cases and 600 fuzz trials, 0 mismatches.
- Pipeline fuzz: 400 trials through `extract_facts` and the gate, 1,693
  code facts, 692 gate runs, 0 problems. Code facts per trial: 0 in 9
  trials, 1 in 15, 2 in 20, 3 in 29, 4 in 84, 5 in 243.
- Model failure, with the real CLI against a fake server on loopback
  and scratch databases: HTTP 500, HTML, prose, truncated output and
  connection refused all exit 0 with `kept=5 code=5 model=0`, and each
  pass reports its own reason. With a 3 s client timeout and a server
  that sleeps 20 s, the cycle took 6.0 s and stored the 5 code facts.
  Both flags with no model env: exit 0. One flag or none with no env:
  exit 1, `missing required environment variable`, which is a config
  error and not a model failure.
- Duplicates, through `extract_facts`: 21 near-matches drop with
  `FACT_DUPLICATE_OF_CODE` (reordered periods, word and decimal forms
  of the values, delta wording, a flipped direction, synonyms the
  labels know), and 6 true different statements are kept. These still
  get through as kept facts: "Media/Video screen hours rose to 4 in
  last.", "YouTube rose from 0 in prior to 4 in last.", "Media rose
  from 0 in prior to 4 in last.", "Watching rose from 0 in prior to 4
  in last.", "Commits fell from 3 in earlier to 1 in prior.", "Pushes
  fell from 3 in earlier to one in prior.", "Pull request count fell
  from one in prior to zero in last.", and the compound "Media/Video
  rose from 0 in prior to about 4 in last, while Work/Programming fell
  by 3."
- Migration, on a file made by main's own code: one `origin` column,
  old column bytes and row counts unchanged, old rows read `model`,
  `fetch_cycle`, `fetch_facts` and `fetch_responses` equal main's
  reads, replaying main's results appends nothing, the triggers still
  abort, and main's code reads the migrated file. Two openers at once
  with no retry: 600 thread opens and 300 process opens, all fine.
- Source mutants on the final code before this paperwork: 104, one
  exact edit each, on throwaway copies, 100 caught and 4 survived.
  Three of the 4: stripping zeros from a value with no decimal point (a
  value quantised to 2 places always has one), the signed change in the
  duplicate rule (the comparison is on absolute values), and no
  rollback after a failed `ALTER` (no test makes the `ALTER` fail, and
  the failed open drops the connection). The fourth was the id tie-break
  in the final evidence sort. I first read it as unreachable, and a
  differential over 17,198 pool pairs found 9 differences, so
  `test_evidence_time_tie_sorts_by_id` pins it.
- `make eval`: hello 1/1, the four briefing tasks 58/58 each,
  glimmer_facts 30/30. `make demo`: exit 0.

## Acceptance results

All with the env prefix, inside the sandbox:

- AT1 `uv run pytest tests/test_glimmer_code_facts.py -k "fixture or
  template or format or floor or tie or empty or one_row or no_tag or
  screen_skips or ai_template"`: exit 0, 23 passed, 29 deselected.
- AT2 `... -k "gate or zero_backing or duplicate or cap or evidence or
  feed_title or code_drop"`: exit 0, 26 passed, 26 deselected.
- AT3 `... -k "unavailable or truncated or invalid or skipped or
  determin"`: exit 0, 7 passed, 45 deselected.
- AT4 `uv run pytest tests/test_glimmer_metrics.py
  tests/test_fact_store.py tests/test_cycle_cli.py`: exit 0, 48 passed.
- AT5 `uv run pytest tests/test_glimmer_mutants.py
  tests/test_glimmer_facts.py tests/test_glimmer_eval.py`: exit 0, 96
  passed (6 known-good and 24 mutant cases exact, counts asserted).
- AT6 `make eval`: exit 0 offline. hello 1/1, briefing l0/l1/l1b/gate
  58/58 each, glimmer_facts 30/30. Latest glimmer log:
  `logs/2026-11-01T17-37-09-00-00_glimmer-facts_mmTRuD33c5fbL5YyWaxcSy.eval`.
  No `@task` file added.
- AT7 on a scratch export of main with the new test file copied in:
  collection fails (1 error), and `framework/glimmer/code_facts.py` is
  absent. A probe there also shows the zero key missing
  (`period.last.screen_hours.Solo/Cat` not in the snapshot), so the C14
  "to 0" claim failing with `L1B_UNKNOWN_METRIC` on the base is expected,
  not a surprise. The reviewer ran it again on an export of main
  `301e413`: 1 error during collection,
  `framework/glimmer/code_facts.py` absent.
- AT8 `make check` inside the sandbox: ruff check clean, ruff format
  clean, pyright 0 errors, pytest 1225 passed with exactly the one known
  failure below, gitleaks "no leaks found" (run separately, since the
  pytest failure stops `make` before the gitleaks step). Outside the
  sandbox the reviewer ran `make check` on this tree before this
  paperwork: exit 0, 1225 passed, gitleaks no leaks. This paperwork adds
  one test.
- AT9 `uv run pytest tests/test_glimmer_checks.py`: exit 0, 43 passed.

Sandbox note: inside this sandbox,
`tests/test_ingest.py::test_live_loopback_server_health_round_trip`
fails because binding a loopback port is forbidden. It passes outside.
That is the one known failure; I changed nothing about that test.

## Live runs

Live runs: one, run by Claude Code outside the Muse sessions, on a
scratch database of synthetic rows, through llama-swap with
`muse-glimmer-30b`:

`cycle=cycle-subject-1-20261031T120000Z-64a87579 run=1 kept=15 code=5
model=10 dropped=0 noop=- personal=5:-:396.1s:stop feed=5:-:41.1s:stop
codes=-`

About 14 minutes of wall clock. The five code facts come first,
including the video rise from 0 to 4 that the model had missed in
Ticket 9's runs. The model restated none of them, so the duplicate rule
did not fire in this run. Its five personal statements are all true
against the table: four comparisons and one that only says two calendar
tags occurred together. The run used the tree before the last review
fixes, whose prompt code is the same. Replaying the recorded answers
through the final tree gives the same `prompt_hash`, cycle id and
snapshot and the same 15 kept facts, and recording them returns the
same run.

This has not run on my real store yet. That run happens after the
merge.

HIDDEN_CRITERIA_DIR was never opened
