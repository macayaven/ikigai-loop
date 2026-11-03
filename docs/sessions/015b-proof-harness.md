# Session evidence — 015b-proof-harness (2026-11-02)

Ticket 15b: the proof harness (R2 privacy, R3 steering, R4 evidence sensitivity).
R2, R3 and R4 were already built in the working tree, uncommitted, and the live
evidence was already stored, when this session started. This session did Step 6,
the wiring, and Step 8, the docs, plus the small fixes the ticket lists. Then it
stopped before any commit. Nothing in this session makes a model call.

Sessions, all headless, started by Claude Code. Plan on muse-wonder-full-1.0
(effort high), in two sessions. Implementation and fixes on muse-spark-1.3
(effort medium), except eight short mechanical sessions on muse-spark-1.3
at low effort: one test fix, the commit, the PREREG line, three docs
fixes, one labelling fix and one wording fix. Prompts and review by Claude Code. Sessions ran in Contributor
mode on made-up data. The benchmark's own model calls ran from Claude Code's own
shell through MuseExecClient in Standard mode.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, and `git` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Step 6 wiring, drawn from the plan D7, D14 and D46:

- `tests/test_receipts_docs.py`: `docs/r3.md` and `docs/r4.md` equal byte for
  byte what `--summary` renders from the stored rows; every committed JSONL and
  `r2.json` passes the hygiene scan D14 lists; `--summary` for R3 and R4 passes
  with `MuseExecClient` patched to raise on construction.
- `Makefile`: `.PHONY` targets `r2`, `r3-doc` and `r4-doc`, exactly as D46 says.
  `EVAL_FILES` unchanged.
- Regenerated from what is stored: `make r2 r3-doc r4-doc`, then all three
  again, with `cmp` confirming nothing changed the second time.

Small fixes from the ticket:

- `tests/test_r3_runner.py::test_unavailable_stop_fires_at_concurrency_4` failed
  once in a combined run, 9 slots started against a bound of 8, and passed alone.
  The runner submits eagerly while completions land out of order, so the stop
  check sees the third consecutive failure late. The test now uses a fake that
  hands out tickets in factory call order and fails each call on its ticket's
  turn with a short pause, so failures land in start order with one recording
  per wake: 4 submitted up front, one refill per observed failure, stop on the
  third, exactly 6 rows. Same check added as R4's twin in
  `tests/test_r4_runner.py`.
- The plan's Open Questions item 7 still said the drain is 5 minutes. It is 10.
- `evals/r2.py` renderer: the by-design list is grouped by line, one item per
  line naming its canary ids with the reason written once; the stopped paragraph
  says each stop plainly; it writes "my private terms list" rather than the file
  name; and it adds that the internal-only label reached no outbound channel.
  Regenerated with `make r2`. No test pinned the old wording, so none changed.

Claude Code's earlier review findings (the unavailable stop above concurrency 1,
exit 0 with work left, two processes drawing a slot twice, uninformative pairs
printed as fail, overlapping canary words, a targeted model copying unseen text,
a stopped canary counted as escaped, a partial R4 reading as held, R4 picking the
wrong R3 file, and the D1/I2 block added after the first R3 run) were already
fixed in the tree before this session; I changed none of that code.

## Acceptance

- `tests/test_receipts_docs.py`: 4 passed.
- `make r2 r3-doc r4-doc` twice: second run changed nothing (`cmp` on `docs/r2.md`,
  `docs/r3.md`, `docs/r4.md` and `evals/results/r2.json`).
- Stop tests: R3 15 of 15 solo, R4 twin 10 of 10 solo; both runner files together:
  51 passed.
- New tests counted with `pytest --collect-only -q` over the 11 new test files:
  207 collected.
- R2 suites after the renderer change: `tests/test_r2.py`,
  `tests/test_r2_inventory.py`, `tests/test_receipts_docs.py`: 42 passed.
- `make check`: ruff check clean, ruff format clean (after formatting my two
  files), pyright 0 errors, gitleaks "no leaks found". pytest: 2655 passed,
  1 skipped, 34 failed, all 34 from this sandbox: 33 fail because the home cache
  folder is read-only here, so the client's owner-only temp folder setup fails
  before any model path runs; the last is the known loopback bind test the plan
  names. Re-running those three files with a writable home folder gives 207
  passed with only the loopback test failing. No other failure was waved through.
- `make eval` exit 0: hello 1/1, briefing 58/58 on all four lines, glimmer 30/30,
  proposal_gate 37/37.
- None of my paths is a forbidden one: `git status` over `framework/`,
  `evals/r1b.py`, `evals/r1b_clients.py`, `evals/r1b_summary.py`,
  `evals/r3_pairs.json`, `evals/r3_scenario.py` and `docs/PREREG.md` is empty.
  The literal `git diff main` over those paths is not empty, because main sits
  at the orchestrator ticket while this branch also holds the R1b, try-it and
  stall-retry tickets; none of that is this session's doing.

## Evidence runs

Claude Code ran the live evidence from its own shell, on a host with no personal
rules file. I ran nothing live myself; the numbers below come from the stored
rows and the run facts I was given.

R3: `IKIGAI_R3_LIVE=1 python -m evals.r3 --model muse-wonder-1.0 --effort high
--repeats 3`, run in batches with `--limit 24` at concurrency 4. 120 slots,
122 calls (2 gate retries, 0 unavailable), 9 min 3 s. The 5-hour window moved
from 0% to 8% and the weekly figure from 6% to 9%, with other sessions running.
Gate 42b57031c11b, prompt e06fce3c434d, before Ticket 13b, so none of its calls
used the stalled-call retry.

R4: 20 arms, 20 calls, 0 unavailable, 1 min 52 s. The 5-hour window moved from
0% to 1% and the weekly figure from 9% to 10%. Same gate and prompt, after
Ticket 13b's retry joined the client stack.

R2 ran offline in this ticket's tree with `make r2`, no model and no network.
Its findings, by field, verbatim from `docs/r2.md`:

> What the findings mean: a local model that misbehaves can copy any digit-free word it sees in its prompt into a fact, because the fact layer checks statements for aliases, digits, whole private values and feed headlines, not against these fields. What it did not see that way: calendar titles and locations, commit text, and window and app titles. The findings are the category field on calendar.event.created rows (cal-category); the counts field on github.push rows (gh-counts-key).

I never opened the path in `HIDDEN_CRITERIA_DIR`. No session in this ticket did,
and no planned command reads it. All data in tests and fixtures is made up. This
session stopped before the commit: no commit and no push from this session.

Assumptions I had to make with nobody to answer: the exact-6 stop count rests on
the pool popping tasks in submission order, which holds in practice and which I
checked with 15 solo runs plus the combined runner suites, and on the pause
being long against scheduling jitter; a different scheduler could still move the
count, and the test would fail loudly rather than pass wrongly. The R3/R4
headline numbers in the README are copied from the generated docs; where the
ticket's prescribed sentence and the docs agreed, I kept the docs' wording. The
nine review findings above are named from the ticket text, not re-verified here.

## Rebase onto 1ea3b86 (Ticket 14 and Ticket 22)

After the ticket's work was done, the branch moved onto `origin/main` at
1ea3b86, which adds Ticket 22 (public provenance) and Ticket 14 (voice
correction). The conflicts were in README.md, CONTRIBUTIONS.md and the
Makefile, resolved by keeping both sides: the status keeps their lines and
the proof-harness line, the Makefile keeps every target from both sides, and
CONTRIBUTIONS.md keeps their entries with this ticket's entry directly before
"AI assistance outside the Muse family". Nothing under `framework/` changed.

R2 on the rebased tree: I gave all 20 new string, string-list and
string-keyed fields on `app.correction`, `app.fact_dispute` and
`app.voice_note` a `controlled` disposition, because I read what writes each
field and none of them carries transcript or user words. Correction
commitment ids are validated against the known ids, dispute ids are
product-generated ids from the stored card, and voice-note fields are closed
outcome, operation and until codes, known commitment and card ids, product
config and transport values, code-defined step names and closed validation
codes. No new canary was warranted, so the overlap audit passes unchanged
with N still 39. `make r2` regenerated byte-identical `evals/results/r2.json`
and `docs/r2.md`: the headline stays 10 of 39 with 8 by design and the same 2
findings, so the expected new escape did not appear and there is nothing to
record. The voice worker's Telegram sends (reply texts echoing the transcript
and the silently sent corrected card) cannot run in R2's offline slot, so
they joined the gaps instead of the channels. `make r3-doc` and `make r4-doc`
regenerated byte-identical docs. One new test in `tests/test_r4_score.py`
pins that the first of two drawn executions stands and the count prints.

Claude Code's `make check` outside the sandbox before the rebase: 2704
passed, 1 skipped, ruff, pyright and gitleaks clean. My `make check` in this
session: 3156 passed, 1 skipped, with ruff, pyright and gitleaks clean; the
sandbox needed two workarounds (a writable HOME for the client's private temp
root and no proxy env for the loopback test), and without them 34
temp-file tests and 1 loopback test fail for environmental reasons only. My
`make eval`: exit 0, hello 1/1, briefing 58/58 on every level, glimmer_facts
30/30, proposal_gate 37/37. The README's R2 numbers still match the docs, so
they stand.

## Follow-up: wall-clock tests, client stack, rebase

Claude Code's `make check` at 12:56 on 288c886, outside the sandbox: 3145
passed, 11 failed, 1 skipped. All 11 failures were runner tests in
`tests/test_r3_runner.py`, each stopping with "stopping: drain margin"
inside the drain margin before the 13:05 window. The cause: the test helper
and several direct `main` calls start live runs with the quiet guard on and
the real clock, so they fail inside every quiet window and the 10 minutes
before it. R4's helper passes `--no-quiet-guard`, which is why R4 did not
fail. The fix: `evals/r3.py` and `evals/r4.py` each gained its own module-level
`utc_now` instead of a lambda local to `main`, and each runner test
file pins it with an autouse fixture to 10:00 UTC on 2026-11-03, an instant
the fixture also checks the guard would let start, so a slot-time move
fails loudly. Guard tests keep their own explicit clocks and the
ticking-clock test keeps its own. I proved the pin matters by moving it to
12:00 UTC inside the drain margin and showing the same 11 fail, then
putting 10:00 UTC back and showing all pass; the file was restored byte
for byte, with the same hash before and after. The audit of the other nine
new test files and the eval modules found no other clock read that reaches
a verdict: the scorers and R2 use fixed stamps, and the only live clock
reads are elapsed-time timers.

I rebased onto `origin/main` (579e0d2, Ticket 17a's follow-up) with no conflicts. The gate identity there is commit
`e18dd3251d3cab9b0671108c8de366aea9d34e00` with hash
`42b57031c11b72ec5cf221f2e9ccb9eddd4fd84e455e103dfc8f6bd1d792f2a2`, the same prefix as before since nothing under `framework/` moved. The ticket's CONTRIBUTIONS entry still sits directly before "AI
assistance outside the Muse family".

I rebased again onto `origin/main` (a94e574), which adds, oldest first: the first-real-card provenance log (#34); Ticket 20's source audit (#35); the labels clock fix (#36); Docs 3's README first screen (#37); Ticket 11b's Wonder proposal review fixes (#38); the 15:30-card provenance log (#39); Ticket 10b's red-team gate rounds (#40); Ticket 16's rater pack and metrics (#41); the 18:00-card provenance log (#42); Ticket 10c's since_last wording change (#43); Ticket 13c's 11:30 card (#44). Three files conflicted. Makefile: one .PHONY line holds every target from both sides, with both sides' recipes (r2/r3-doc/r4-doc beside metrics/audit-control) and the unchanged shared EVAL_FILES. docs/PREREG.md: main's Deviation entries 12-18 first in main's order, then this ticket's R3-report line. README.md: the Status section keeps both sides' lines, with the rater/source-audit lines beside the proof-harness line, which stays in Built and merged. CONTRIBUTIONS.md merged itself, this ticket's entry still directly before "AI assistance outside the Muse family". Nothing else conflicted. The new gate identity is commit 41b686d with hash prefix 2f443fbbc8ddfc4f, and the new prompt identity prefix is b42e301f613ad5dc. To follow main I changed: `evals/live_guard.py` covers the dated 11:30 extra slot from the product's EXTRA_SLOT constant, with a new guard test that an instant inside its window is blocked; the R3/R4 runner fixtures moved their pinned clock from 10:00 to 09:00 UTC on 2026-11-03, clear of the new window and drain; R2 names the extra slot's limits/profile branch in its gaps (same sends, narrower allowed hours); the R3 wiring test's fake stream gained the task_lifecycle provider payload that Ticket 11b's fail-closed client requires; and the closure-count test went 44 to 47 for Ticket 10b's three new gate modules. R3 and R4 still call the product's own propose path, prompt builders and client stack, so the method text and departures list stand unchanged, and `docs/r3.md` and `docs/r4.md` stayed byte-identical.

Method corrections: both renderers now name the client stack from the rows.
Rows carrying `timeout_retries` went through TimeoutRetryClient around
LocalRetryClient around MuseExecClient, with the retry count from the rows;
rows without it went through LocalRetryClient around MuseExecClient; a
mixed file names both with row counts. R3's predates-13b departure now
prints only for rows without the field and takes the gate prefix from the
rows; where the rows carry the field, the tenth departure says the
stalled-call retry runs without a deadline like the local one, with the
timed-out call count from the rows. `make r3-doc` leaves `docs/r3.md`
byte-identical and `make r4-doc` changes `docs/r4.md` in that sentence
only. Six new renderer tests cover rows without the field, rows with it,
and a mixed file in each scorer. The plan's D11, D41 and AT6 lines now
name the three-layer stack. The reports now show every stored run: the newest in full as the headline, and older ones under "First run" and "Earlier run" headings.

My `make check` inside the sandbox: ruff and pyright clean and gitleaks clean when run
on their own; pytest gives 3195 passed, 34 failed, 1 skipped. All 34
failures are outside this ticket's files: 33 need a writable temp root
the sandbox denies (20 in `tests/test_cycle_orchestrator.py`, 13 in
`tests/test_proposal_local_retry.py`) and 1 is the loopback health check
the sandbox proxy blocks. I re-ran one of the cycle failures on the
untouched base and it fails there too. Every test in the 11 new files
passes. My `make
eval`: exit 0, hello 1/1, briefing 58/58 on every level, glimmer_facts
30/30, proposal_gate 37/37. I updated the README count to 229 tests in
the 11 new files.

Claude Code's `make check` at 14:00 on f1f310e, outside the sandbox: 3228 passed, 1 failed, 1 skipped; ruff, ruff format and pyright clean; gitleaks found no leaks in 67 commits; `make eval` exit 0. In this ticket's files, f1f310e differs from the final commit only in docs. The one failure, `tests/test_cycle_labels.py::test_canary_exception_cli_reports_type_only`, also fails on main, and has since 14:00 CET today. Its calendar row is fixed at 2026-10-31 14:00 +01:00, and the `labels` command reads two days back from the real clock, so the row now falls outside the window. It belongs to Ticket 9c, outside this ticket, and I left it alone. Main fixed that test in #36.

The gate and prompt hashes missed the other 35 files the gate imports: two runs differing only in an imported module shared one results file name, so R3's resume would have treated the second run as the first. The identity now also hashes the full 44-file import closure of the gate and the prompt, and the closure travels in the file name, the rows, the refusals and the reports.

## Declaration before the re-run

2026-11-02 15:39:19 +0100 (CET)

Before any re-run, I declare: after rebasing onto the main that includes Tickets 10b and 10c, I run R3 and then R4 on the gate and prompt at HEAD, resuming each until it completes and never starting either over. Both runs get reported, each named by its gate and prompt identity. The README's headline R3 and R4 numbers come from that run, whatever it shows, a miss included. The first run stays in the docs as "first run, gate 42b57031c11b". That is the gate the live cards ran on: the live clone has been on three commits since it was cloned at 02:41 on 2026-11-02, f40096f, b955508 and 1ea3b86, and all three carry gate commit e18dd32 with hash 42b57031c11b and the same prompt file, prompt identity e06fce3c434d.

Edited 2026-11-02 18:44:12 +0100 (CET), before any re-run: the gate identity that named the first run covers R1b's eight gate files only. Over the full import closure of the gate and the prompt, the first run's closure is 69d89df4cec5, and so are the live clone's first two commits, f40096f and b955508. The live clone at 1ea3b86, live since 12:12 on 2026-11-02, is a041eb51b004, which differs from the first run's only in Ticket 14's two schema files, framework/schemas/events.py and framework/schemas/__init__.py. So "the gate the live cards ran on" holds under the 8-file identity only.

Edited 2026-11-02 19:01:24 +0100 (CET), before any re-run: Ticket 10c, which changes both the gate and the Wonder prompt, now merges before the re-run, because the live 15:30 card on 2026-11-02 showed a since_last wording hole that the gate let through. The headline run is on the gate and prompt at HEAD after Ticket 10c.

## Re-run on gate 2f443fbbc8dd

After the live rehearsal, the live cards moved to 3e31338 at 23:29 on 2026-11-02. I ran both receipts on a branch at exactly that commit. Before the first call, evals/gate_identity.py gave gate commit 41b686d, gate hash 2f443fbbc8dd, prompt b42e301f613a, and closure 907b228d92cd over 47 files. Muse Code was 1.4.14 (1.4.14-R7309.1).

R3 used `IKIGAI_R3_LIVE=1 python -m evals.r3 --model muse-wonder-1.0 --effort high --repeats 3`, in batches of 24 at concurrency 4 with a stop time of 10:40 the next morning. It ran 23:30:24 to 23:38:59 CET and covered 120 slots with 121 calls: 1 gate retry, on L1B_DIRECTION_MISMATCH. There were 0 unavailable calls and 0 timeouts. The Muse usage window went from 10% to 16% and the weekly from 15% to 17%, with other sessions also running.

R4 used `IKIGAI_R4_LIVE=1 python -m evals.r4 --model muse-wonder-1.0 --effort high`. It ran 23:39:34 to 23:41:11 CET: 20 arms, 20 calls, 0 unavailable, 0 timeouts. Window 16% to 17%, weekly 17% to 18%.

The rows record tree commit 3e31338. That commit is on main and already carries this note's declaration, which merged as #45 before the run. tree_dirty is true on rows written after the first batch only because the run's own new results file was untracked. No closure file was dirty, and the runner refuses otherwise.

The results, copied from the regenerated docs. R3's Result:

> registered prediction: "at least 70% of informative directional pairs and at least 8 of 10 invariance"
>
> directional: held; invariance: held; combined: held
>
> - directional: 4/5 passes over informative pairs (Wilson 95% 0.38 to 0.96; this interval describes these fixed pairs only and generalizes nowhere); informative 5/10 of 10 directional pairs
> - uninformative: D10 (base-never-picks-avoid), D4 (base-picks-expect-3-of-3), D5 (base-never-picks-avoid), D6 (base-picks-expect-3-of-3), D7 (base-picks-expect-3-of-3)
> - invariance: 10/10 passes (Wilson 95% 0.72 to 1.00); pairs failing on an arm with no picks: 0

R4's Result:

> registered prediction: "cited changes more often than control"
>
> - pick: 5/10 cited vs 1/10 control -- held
> - whole signature: 10/10 cited vs 10/10 control -- not held -- no differential sensitivity detected
> - reason signature: 10/10 cited vs 6/10 control -- held

R4's pooled noise floor: pick 29/870, whole 719/870, reason 379/870 over 870 pairs.

As declared, the README's headline comes from this run. The first run stays in docs/r3.md and docs/r4.md under its own heading. The receipts tests assumed one stored run per directory, and now read every stored run.
