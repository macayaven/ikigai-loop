# Session evidence — 009c-glimmer-labels (2026-11-01)

Ticket 9c only. This note covers stage one: the implementation session, which
ran Steps 1 to 9 of [docs/plans/009c-glimmer-labels.md](../plans/009c-glimmer-labels.md)
and stopped before any commit, with no model call and no network. Nobody could
answer questions during the run; every place I decided something the plan left
open is listed below. I read the whole plan before writing anything, wrote the
tests first, and confirmed they fail on the base before the code existed.

What was built, file by file:

- `framework/schemas/events.py`: `Label`, `LABELS`, `CalendarLabelData`
  (with `valid: bool`), plus `calendar.label` in the `EventData` union and in
  `EventType`. `framework/schemas/__init__.py` and
  `framework/schemas/export_schemas.py` export it. The schema diff is exactly
  one new file (`schemas/CalendarLabelData.json`) plus the regenerated
  `schemas/Event.json`.
- `framework/glimmer/labels.py`: re-exports `Label` and `LABELS`,
  `INTERNAL_ONLY_LABELS = {"iki-care"}`, `apply_labels`,
  `strip_internal_tags`, `LabelView`, `effective_label`.
- `framework/glimmer/label_step.py`: `build_label_prompt`,
  `LABEL_PROMPT_SHA256`, `LABEL_RESPONSE_FORMAT`, `parse_label_response`,
  `classify_label_response`, `LabelOutcome`, `LabelAssignment`,
  `LabelStepResult`, `label_events`, `is_private_llm_base_url`,
  `build_label_client`, `LABEL_CALL_TIMEOUT_S = 300`.
- `framework/collectors/calendar_ics.py`: the `TAG_PATTERN` left boundary,
  the optional `title_sink` argument with the event-id key. Nothing else.
- `framework/glimmer/llm.py`: the opener gains `ProxyHandler({})`, and the
  client gains the optional `response_format` constructor parameter, sent only
  when passed. T9 calls stay byte-identical.
- `framework/glimmer/facts.py`: one first line in `extract_facts`.
  `framework/glimmer/checks.py`: one additive `FACT_INTERNAL_LABEL` arm.
  `framework/glimmer/__init__.py`: the label re-exports.
- `framework/cycle/__init__.py`: `run_cycle` loads `calendar.label` rows in
  a separate call, keeps `collected_at <= as_of`, applies the overlay.
- `framework/cycle/labels.py`: `run_label_sweep`, poll with sink first,
  label second, persist per title, budget at this edge.
- `framework/cycle/__main__.py`: the `labels` subcommand with the
  off-by-default gate.
- `evals/r10_keywords.py`: the frozen keyword baseline.
  `evals/r10.py`: the gated R10 runner.
- Tests: `tests/test_glimmer_labels.py`,
  `tests/test_glimmer_label_step.py`,
  `tests/test_glimmer_label_guard.py`, `tests/test_cycle_labels.py`,
  `tests/test_r10.py`, plus additions to `tests/test_calendar_ics.py`,
  `tests/test_glimmer_llm.py`, and `tests/test_glimmer_facts.py`.
- Docs: `docs/PRIVACY.md`, the README Status line, the profile lines,
  the `.env.example` switches, this note.

One forced fix outside the plan's file tables: `evals/glimmer_cases.py`
gains a `calendar.label` payload branch in `_dropped_payload`. Adding the new
event type to `EventType` tripped the harness tripwire that enumerates every
non-allowlisted type, so every suite importing that module failed at import
until the branch existed. The F9 case now proves label rows are dropped from
the fact passes like every other non-allowlisted type. No pinned behavior
changed.

One forced re-freeze, still before any result: `evals/r10_keywords.py` needed
one lint fix (`%` to `.format`, identical compiled patterns, verified by
re-running the same smoke titles with identical outputs), so the frozen hash
moved from `b675a5…` to `0ec14016…`. No R10 result had been seen, no case file
exists in this session, and the keyword rules did not change: the set is still
held out.

Decisions the plan left open, each the smallest choice that keeps the pinned
behaviour testable:

1. `LABEL_PROMPT_SHA256` is the sha256 of the template bytes
   (`LABEL_PROMPT_TEMPLATE`, with the `{title}` slot).
2. The results-file header is one JSON object line; report and header shapes
   follow D9 field by field.
3. `LabelAssignment` carries `event_id`, `label`, `valid`, `model_id`.
   `valid`/`invalid` count assignments; `deduped` counts assignments served
   from an earlier call in the same sweep; `conflicts` counts assignments
   lost to `UNIQUE (source, source_id)`, including identical re-deliveries,
   which the sweep surfaces as `ConflictingEvent` so the step can count them.
4. `build_label_client` raises `SystemExit` naming the variable for a missing
   value and `ValueError` with a fixed URL-free message for a refused base.
5. `run_label_sweep` takes label names or collector objects, polls every
   collector before any model call, and shares one budget deadline across
   labels; the CLI calls it once per `--label` in argument order.
6. Label rows use `collected_at = as_of` from the sweep that stored them.
7. Zero-length busy rows count as `skipped_not_busy`; a non-first
   `on_assignments` failure other than `ConflictingEvent` propagates.
8. The R10 results filename sanitises the model id to alphanumerics,
   dot, dash, and underscore.
9. The `.ts.net` guard limit in `docs/PRIVACY.md` is paraphrased with no host,
   path, or person named, per my standing rules; the plan's substance is kept.
10. `run_cycle` loads the label rows before the allowlisted rows, same
    window both calls, so the pre-existing 72h-window spy test (whose file
    the plan does not list for modification) keeps passing unedited.
11. `COMMITMENT_TAG_PATTERN` in `framework/briefing/schemas.py` takes the
    same left boundary. Under `fullmatch`, its only use, the two patterns
    accept exactly the same strings, so this is zero behavior change; it
    keeps the equality the briefing test pins.
12. The parser body in `classify_label_response` was restructured once for
    strict typing (cast after `isinstance`, no logic change). The parser
    arms in the tests pin the behavior unchanged.
13. `docs/plans/009c-glimmer-labels.md` itself is formatted with
    `ruff format` (code-sample layout only), because `make check` gates
    every file including the plan. No meaning changed.

Verification: AT1 to AT11 per the plan, full `pytest` plus `make check`,
all synthetic, all offline. The keyword list, the prompt, and the parser did
not change after step 4; the frozen keyword hash and `LABEL_PROMPT_SHA256`
above are the record.

`evals/r10_cases.json` stayed absent for the whole session, and no
`evals/r10_results/` was created. I never opened `HIDDEN_CRITERIA_DIR` and
read nothing outside this repo.

Live runs: see the R10 section at the end.

## Review fixes, same session (headless, no questions possible)

A reviewer read the whole diff, ran it live on loopback, and mutated a
throwaway copy. I fixed every finding before any case file existed in this
clone, so nothing here responded to a result. Where the fix brief left a
choice open, I took the smallest one that keeps the tests honest.

Parser and sweep: `classify_label_response` now catches `RecursionError`
next to `ValueError`, so a deep-nesting answer becomes
`LabelOutcome("iki-unknown", valid=False)` and the sweep keeps labelling
the rest of the queue. One new function, `label_outcome(response)`, holds
the `finish_reason == "length"` rule plus the parser call, and both the
sweep and the R10 runner use it, so R10 measures what the product does.

R10 runner: pending cases are worked out first, the client is built when
something is pending, and the results file is created only after that, so
a refused endpoint or a missing variable leaves no file behind. A refused
base prints exactly `r10: refused endpoint` (exit 2, URL in neither
stream); a missing variable keeps its `SystemExit` naming the variable.
A last line with no trailing newline counts as torn even when it parses:
under `truncate=True` the tail is cut with `os.truncate` at the byte
offset where that line starts, then fsynced, never rewritten; a
header-only file with no newline keeps its header and gains the newline.
`--report-only` ignores a torn final line, leaves the bytes identical,
and exits 0. `LLMUnavailableError` prints
`r10: model unavailable (<message>), stopped, rerun resumes` (exit 3),
and the inline import moved to the top of the file. The `IKIGAI_R10_LIVE`
gate now applies only when a run could call a model, so `--report-only`
needs no switch.

Keyword rewrite: I rewrote `evals/r10_keywords.py` as if the list had to
win, general calendar language in English and Spanish, same shape
(`_fold`, whole-word matching, first match wins, default `iki-unknown`,
same rule order), with every word the brief named plus others in the same
spirit, and I moved "date night" from social to family. The literal-token
fix blanks every `iki-*` token (after folding) before any rule runs,
because in production such a token makes the row a hand tag that never
reaches a labeller, and the baseline must not win or lose on a token no
rule is meant to read. The other words in a title still count.
Re-frozen hash: `KEYWORDS_SHA256` is now
`ba48856fc4edfbd69924baece720d0c21a413908cb8c43d95f8a21810c345d17`.

CLI: `--subject-id` is gone from the `labels` subcommand; the subject
comes only from `IKIGAI_SUBJECT_ID`, and when it is unset the command
prints one line naming it and exits 2 with no model call. `facts` keeps
its flag.

Docs: I rewrote `docs/PRIVACY.md` short with the stated facts and no
others, and I pointed the two profile table cells at `docs/PRIVACY.md`
instead of themselves.

Tests: I added the brief's whole mutation-killer list across
`test_glimmer_labels.py`, `test_cycle_labels.py`,
`test_glimmer_label_step.py`, `test_glimmer_label_guard.py`,
`test_glimmer_llm.py` (fresh-interpreter proxy test), and `test_r10.py`,
and I corrected `test_invalid_answer_wrong_against_gold_unknown` to assert
an invalid `iki-unknown` answer is wrong under both scorings.

Assumptions I stated rather than asked about: the R10 header-only repair
appends the missing newline with a plain append plus fsync; the labels
missing-subject error reads exactly `error: set IKIGAI_SUBJECT_ID`; the
`_load_results` truncate path uses `os.truncate` on the path followed by
an fsync of a read handle; new keyword words keep every previously frozen
word so older invented titles label exactly as before.

`evals/r10_cases.json` is still absent, `test_r10_cases_match_pin` still
skips, and no `evals/r10_results/` was created. I never opened
`HIDDEN_CRITERIA_DIR` and read nothing outside this clone.

## Second review fixes (headless, no questions possible)

A reviewer re-ran the branch live and mutated a throwaway copy again,
still before any case file existed in this clone. I fixed everything in
this session and wrote the missing killer test for each mutation.

The one real bug: a corrupt last results line ending in a newline left a
stray byte. `_load_results` cut at `len(data) - len(chunk)`, which keeps
the first byte of the bad line when that line ends in `\n`; the next
append glued to it and the run after exited 2. The cut is now at the
byte offset where the bad line starts in both shapes. Killer tests: a
results file ending in `NOT-JSON-AT-ALL\n` is re-asked once with exit 0
and every line parsing after, and `--report-only` over it exits 0 with
the bytes untouched.

Small fixes: the freeze test is now named `test_r10_keywords_frozen` as
the plan and the `evals/r10_keywords.py` docstring say (docstring
untouched, hash unchanged); the `docs/PRIVACY.md` server sentence now
credits a review, not me; the plan's Risks now state the 300 s limit is
a socket read timeout. That limit bounds a silent server, not one that
trickles bytes: 301 s against a hanging server, 401 s against one that
sends a byte every 5 s and stops at 400 s, measured on loopback through
the real CLI with `--budget-s 1`. Whoever schedules the sweep holds
their own wall-clock limit.

Tests that could not fail before: the not-busy row now has a real hour
so only the `busy` check can skip it; the zero-budget CLI test now
queues one busy untagged row with a title (plus a positive control that
`--budget-s 60` calls once); new CLI tests spy that both `--label`
values are swept with counts added and that a 100 s first sweep leaves
140 s of a 240 s budget for the second; the discordant test pins strict
pairs at exactly 10 passing alone; the hand-worked stats test gains a
both-strictly-right case and two gold `iki-care` dual-accepted cases
(model right by the second label, list right by the second label), with
all thirteen totals reworked by hand; the report test pins the exact
`iki-deep` confusion row with one valid and one invalid `iki-unknown`
answer; the frozen stamp is pinned both ways; the overlay pins the
later `collected_at` row winning in either input order; and
`--report-only` over a newline-less header-only file exits 0 with bytes
identical.

Assumptions I stated rather than asked about: the CLI multi-label and
budget tests read the real clock only through `time.monotonic` (faked)
and build one row against the live clock so it sits inside the sweep
window; the hand-worked thirteen-case totals above are mine, computed
without running the code under test.

`evals/r10_cases.json` is still absent, `test_r10_cases_match_pin`
still skips, and no `evals/r10_results/` was created. The keyword hash
is unchanged at
`ba48856fc4edfbd69924baece720d0c21a413908cb8c43d95f8a21810c345d17`.
I never opened `HIDDEN_CRITERIA_DIR` and read nothing outside this
clone.

## Public-repo sweep fixes (headless, no questions possible)

My public-repo scan flagged four entries in the keyword list, and they
came out with nothing in their place. The reviewer ran the same scan
over the case file by counts, without reading it, and it reports no
hits, so no title in the frozen set holds any of those entries and the
list's score can't move because of this. The keyword file hash is now
`51019576487276a0fb04e6d3c94690c2bc85acd33e45cf65259beb505319c441`.

I replaced one public IPv6 literal in the guard tests and the plan
with another public address the guard still refuses, and I replaced
one word for my network in tests, docstring and plan. The invented
host now reads `synthetic-box.synthetic-net.ts.net` (upper case kept
upper case where it was upper case) and the prose says "private
network" where it used that word. The docstring now says ".ts.net
names".

Assumption I stated rather than asked about: I read "say `.ts.net
names`" as the sentence "Allowlist guard: loopback over http/https,
LAN and .ts.net names over https." Nothing else in that docstring
changed.

Still before any case was in the clone: `evals/r10_cases.json` is
still absent, `test_r10_cases_match_pin` still skips, and no
`evals/r10_results/` was created. I never opened
`HIDDEN_CRITERIA_DIR` and read nothing outside this clone.

The branch moved onto main at `98dee7e` (Ticket 9b). `docs/PRIVACY.md` already existed there so the calendar text is now a section of it. Beyond conflict markers I changed one assertion: `test_model_label_reaches_snapshot_and_rollup_through_run_cycle` now pins `period.last.tag_hours.iki-deep` to 1.0 and prior/earlier to 0.0, because Ticket 9b's rollup zero-fills every period. A new test pins that code facts skip `iki-care` even when it's the largest change. It moved again onto main at `96a4dff` (Tickets 9d and 17a, a Ticket 12 follow-up, Docs 2) with no conflict, and I regenerated `docs/verify/bundle.json` because this ticket changes files that page carries. It moved once more onto main at `0493046` (Ticket 11). I kept both sides in `.env.example`, `README.md`, `framework/glimmer/__init__.py` and the parser and dispatch in `framework/cycle/__main__.py`. That move also added a second check Ticket 11 made possible: `forbidden_literals_for` now always returns the internal-only labels, so Ticket 11's outbound scan refuses a prompt, draft or commitment title that names one, upper or lower case. One Ticket 11 assertion changed, from an empty tuple to `("iki-care",)`, and a new test shows a fact statement naming the label ends in `NOOP_OUTBOUND_BLOCKED` with nothing sent. The R10 report and its inputs didn't change.

## R10 run and stage two

Claude Code started R10 after the review: one pass through my local model server, from 19:28 to 20:06 Madrid on Nov 1, `python -m evals.r10 --model muse-glimmer-30b`, role product. This is the runner's report, printed again with `--report-only`, unedited:

```text
role: product
model: muse-glimmer-30b
n: 80
cases_sha: 9c346ea1ec17
prompt_sha: fc1753db4a07
keywords_sha: 510195764872
response_format: yes
frozen cases: yes
model correct: 77/80 strict: 77/80
keywords correct: 51/80 strict: 50/80
per-label correct (model, correct/strict by gold label):
  iki-deep: correct 10/10 strict 10/10
  iki-meeting: correct 10/10 strict 10/10
  iki-family: correct 10/10 strict 10/10
  iki-social: correct 10/10 strict 10/10
  iki-care: correct 10/10 strict 10/10
  iki-rest: correct 8/10 strict 8/10
  iki-admin: correct 9/10 strict 9/10
  iki-unknown: correct 10/10 strict 10/10
per-label correct (keywords, correct/strict by gold label):
  iki-deep: correct 6/10 strict 6/10
  iki-meeting: correct 8/10 strict 8/10
  iki-family: correct 8/10 strict 8/10
  iki-social: correct 6/10 strict 6/10
  iki-care: correct 6/10 strict 5/10
  iki-rest: correct 5/10 strict 5/10
  iki-admin: correct 6/10 strict 6/10
  iki-unknown: correct 6/10 strict 6/10
confusion model (rows gold, columns predicted):
  gold\pred iki-deep iki-meeting iki-family iki-social iki-care iki-rest iki-admin iki-unknown invalid
  iki-deep 10 0 0 0 0 0 0 0 0
  iki-meeting 0 10 0 0 0 0 0 0 0
  iki-family 0 0 10 0 0 0 0 0 0
  iki-social 0 0 0 10 0 0 0 0 0
  iki-care 0 0 0 0 10 0 0 0 0
  iki-rest 0 0 0 0 0 8 0 2 0
  iki-admin 0 0 0 0 1 0 9 0 0
  iki-unknown 0 0 0 0 0 0 0 10 0
confusion keywords (rows gold, columns predicted):
  gold\pred iki-deep iki-meeting iki-family iki-social iki-care iki-rest iki-admin iki-unknown invalid
  iki-deep 6 1 1 0 0 1 0 1 0
  iki-meeting 0 8 2 0 0 0 0 0 0
  iki-family 0 1 8 0 1 0 0 0 0
  iki-social 0 2 0 6 0 1 0 1 0
  iki-care 1 1 1 0 5 1 0 1 0
  iki-rest 1 0 0 2 1 5 0 1 0
  iki-admin 0 1 1 0 1 1 6 0 0
  iki-unknown 0 1 0 2 1 0 0 6 0
by class (correct scoring, both arms):
  ambiguous: model 8/8 keywords 4/8
  injection: model 7/7 keywords 7/7
  keyword_trap: model 18/20 keywords 6/20
  plain: model 34/35 keywords 28/35
  terse: model 10/10 keywords 6/10
by lang (correct scoring, both arms):
  en: model 47/50 keywords 30/50
  es: model 20/20 keywords 16/20
  mixed: model 10/10 keywords 5/10
keywords unknown: total 10 among gold not unknown 4
model invalid: 0
seconds per title: mean 28.77 median 25.64 p90 38.71 max 66.22 total 2301.87
completion tokens per title: mean 382.8 median 337.0 max 888 total 30625 unreported 0
mcnemar correct: b=27 c=1 p=2.161e-07
mcnemar strict: b=28 c=1 p=1.118e-07
mcnemar limits: the smallest p reachable with n discordant pairs is 2/2**n; the test says nothing about the size of the gap; per-label counts are small and carry no test; 80 synthetic titles say little about my real calendar, and no real title is ever scored, so nobody will know the accuracy on real titles after this is on.
condition 1 complete 80/80: PASS
condition 2 more right 77>51 strict 77>50: PASS
condition 3 not luck p=2.161e-07/1.118e-07 discordant=28/29: PASS
condition 4 right when it commits 67/68 strict 67/68: PASS
condition 5 iki-care 10>=6 strict 10>=5: PASS
condition 6 clean answers invalid=0/80: PASS
decision: eligible

```

The rule was fixed in the plan before any result existed, and the last line is its outcome: `decision: eligible`. Eligible means the rule passed. Nothing turns on by itself, and this commit leaves the switch off.

What it can't show: the titles are invented, ten per label, and a real calendar doesn't look like that. No real title is ever scored, so after this is on nobody will know the accuracy on my real titles.

Where the files came from:

- `evals/r10_cases.json`: a separate agent wrote these 80 invented titles and froze them by hash before this ticket's plan was written. None comes from my calendar or anyone else's. Muse Code didn't write them, and no session saw them before the run.
- `evals/r10_results/`: the runner's output. I made one edit after the run: in `muse-glimmer-30b.jsonl`, `seconds` is rounded to milliseconds, because two long floats happened to hold a digit run my repo hygiene scan flags. The report is byte-identical before and after, and no answer, token count or header changed.

What was known about the set before the run: 80 titles, the file's shape, and one count from a shape check, that six titles hold a literal `iki-` token. Nobody working on this ticket read a title. That count came before the keyword list's last rewrite, which added the blanking of literal tokens. After the run a scratch script ran the list with the blanking on and off: 51 correct and 50 strict with it, 49 and 48 without. It moved two titles, in the list's favour, and the decision doesn't depend on it.

Nothing changed after the result. The prompt hash, the keyword hash and the rule are the ones pinned before the run. Claude Code read the set and the model's misses only after the run.

The model's three misses: `Meet plumber 9-11` got `iki-care` where the set says `iki-admin`, and `Gig at Sala Quimera` and `Deep house set @ Sala Trébol` got `iki-unknown` where the set says `iki-rest`.

Seconds: the server's journal shows exactly 80 chat calls in that window, all status 200, so no other job shared the model and the numbers above aren't inflated by a queue. The slowest call took 66 s, under the 300 s read limit the sweep uses.

Before R10, one invented title went through the real `labels` command and the real endpoint, with a scratch data directory and a feed on loopback. It stored one valid label in 25 s. The title was in the feed, which is the control, and in no data file, stdout, stderr, server journal line or log endpoint response. The server's capture buffer is the exception `docs/PRIVACY.md` describes.

Review by Claude Code, on the tree at main `96a4dff` before these docs: the canary through every failure kind, the default off, the endpoint guard, injection titles, the model down and hand tags ran live against recording servers on loopback, and all passed. One change at a time in a throwaway copy, 164 mutants: 164 caught, 0 survived. The first round, on the early tree, was 84 caught and 39 survived of 123, and those survivors are why the review fixes above added tests.

A comparison, not the product: `nemotron-lightning-30b`, a faster local model, ran once over the same set to exercise the runner's comparison role. It's no evidence for this ticket, and the runner gives it no decision.

```text
COMPARISON, not the product
role: comparison
model: nemotron-lightning-30b
n: 80
cases_sha: 9c346ea1ec17
prompt_sha: fc1753db4a07
keywords_sha: 510195764872
response_format: yes
frozen cases: yes
model correct: 66/80 strict: 66/80
keywords correct: 51/80 strict: 50/80
per-label correct (model, correct/strict by gold label):
  iki-deep: correct 8/10 strict 8/10
  iki-meeting: correct 10/10 strict 10/10
  iki-family: correct 9/10 strict 9/10
  iki-social: correct 10/10 strict 10/10
  iki-care: correct 9/10 strict 9/10
  iki-rest: correct 3/10 strict 3/10
  iki-admin: correct 9/10 strict 9/10
  iki-unknown: correct 8/10 strict 8/10
per-label correct (keywords, correct/strict by gold label):
  iki-deep: correct 6/10 strict 6/10
  iki-meeting: correct 8/10 strict 8/10
  iki-family: correct 8/10 strict 8/10
  iki-social: correct 6/10 strict 6/10
  iki-care: correct 6/10 strict 5/10
  iki-rest: correct 5/10 strict 5/10
  iki-admin: correct 6/10 strict 6/10
  iki-unknown: correct 6/10 strict 6/10
confusion model (rows gold, columns predicted):
  gold\pred iki-deep iki-meeting iki-family iki-social iki-care iki-rest iki-admin iki-unknown invalid
  iki-deep 8 0 0 0 0 0 0 2 0
  iki-meeting 0 10 0 0 0 0 0 0 0
  iki-family 0 1 9 0 0 0 0 0 0
  iki-social 0 0 0 10 0 0 0 0 0
  iki-care 0 0 0 0 9 0 0 1 0
  iki-rest 0 0 0 2 0 3 0 5 0
  iki-admin 0 1 0 0 0 0 9 0 0
  iki-unknown 0 1 0 1 0 0 0 8 0
confusion keywords (rows gold, columns predicted):
  gold\pred iki-deep iki-meeting iki-family iki-social iki-care iki-rest iki-admin iki-unknown invalid
  iki-deep 6 1 1 0 0 1 0 1 0
  iki-meeting 0 8 2 0 0 0 0 0 0
  iki-family 0 1 8 0 1 0 0 0 0
  iki-social 0 2 0 6 0 1 0 1 0
  iki-care 1 1 1 0 5 1 0 1 0
  iki-rest 1 0 0 2 1 5 0 1 0
  iki-admin 0 1 1 0 1 1 6 0 0
  iki-unknown 0 1 0 2 1 0 0 6 0
by class (correct scoring, both arms):
  ambiguous: model 6/8 keywords 4/8
  injection: model 6/7 keywords 7/7
  keyword_trap: model 15/20 keywords 6/20
  plain: model 30/35 keywords 28/35
  terse: model 9/10 keywords 6/10
by lang (correct scoring, both arms):
  en: model 41/50 keywords 30/50
  es: model 16/20 keywords 16/20
  mixed: model 9/10 keywords 5/10
keywords unknown: total 10 among gold not unknown 4
model invalid: 0
seconds per title: mean 10.42 median 7.88 p90 15.97 max 81.43 total 833.94
completion tokens per title: mean 1198.7 median 991.0 max 6996 total 95892 unreported 0
mcnemar correct: b=19 c=4 p=0.002599
mcnemar strict: b=20 c=4 p=0.001544
mcnemar limits: the smallest p reachable with n discordant pairs is 2/2**n; the test says nothing about the size of the gap; per-label counts are small and carry no test; 80 synthetic titles say little about my real calendar, and no real title is ever scored, so nobody will know the accuracy on real titles after this is on.
condition 1 complete 80/80: PASS
condition 2 more right 66>51 strict 66>50: PASS
condition 3 not luck p=0.002599/0.001544 discordant=23/24: PASS
condition 4 right when it commits 58/64 strict 58/64: PASS
condition 5 iki-care 9>=6 strict 9>=5: PASS
condition 6 clean answers invalid=0/80: PASS
no decision: comparison role

```

I never opened `HIDDEN_CRITERIA_DIR`.
