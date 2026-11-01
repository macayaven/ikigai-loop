# Session evidence — prereg (2026-11-01)

Branch `prereg`. Five headless implementation sessions. The first added
the pre-registration, the pairs, the tests and the two Makefile targets.
The second and third fixed what the review found. The fourth, after
Ticket 10 merged, filled my ruling split and moved the checks to the
public helpers. The fifth wrote these results and made the commit. No
questions were possible during them, so open points were decided in the
session. The note summarises the work, and the raw session exports are
kept privately.

`muse --version` (this session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## What changed and why

The first session added `docs/PREREG.md` (the ticket's text, byte for
byte, with the PENDING section unfilled), `evals/r3_pairs.json`,
`evals/r3_scenario.py`, `evals/demo_rejection.py`, the three test files,
the Makefile targets, the README bullet, and the CONTRIBUTIONS entry.

The review sent that output back, so the next sessions fixed the code
and the tests:

- `evals/run_tasks.py` (new): runs the files in `EVAL_FILES` on
  `mockllm/model` and exits 1 unless every log has status `success`,
  holds samples, and scores every sample CORRECT. `inspect eval` exits 0
  on an INCORRECT sample and on an errored log (measured on 0.3.285), so
  the exit code could not come from Inspect itself.
- The runner calls Inspect once per file, in order, in a loop. Measured:
  one call over several files silently drops a file with a syntax error
  or no tasks when it sits beside a good file, exiting 0 as if nothing
  were wrong. One call per file makes a broken file raise (or return no
  logs) where it names itself, so one run shows every problem.
- `Makefile`: `EVAL_FILES` gains `evals/briefing_gate.py`; the eval
  recipe calls the runner; the demo recipe gains `@` so the first printed
  line is the synthetic notice, not the echoed command.
- `evals/r3_scenario.py`: `set_metric` on an unknown id raises
  `KeyError("unknown metric: <id>")`; a typo used to add a new metric.
- `tests/test_eval_tasks.py`: AST detection of `@task` over the whole
  `evals/` tree, equality with `EVAL_FILES` in both directions, a check
  that the eval recipe uses `$(EVAL_FILES)`, and subprocess tests for the
  runner (pass, wrong target naming the sample id, raising scorer,
  mixed pass/fail, no files, no-task file, syntax-error file).
- `tests/test_r3_pairs.py`: one claim per fact citing only that fact's
  own metrics, with a sentence-start to metric-family table; a feed
  statement cites its own `feed.item.count.<suffix>` sub-metric when the
  arm has one and the suffix appears in the statement; commitment
  titles, every arm's fact statements and metric ids checked with the
  public helpers from Ticket 10; each commitment validated through the
  `Commitment` schema; perturb non-empty and effective; expects derived
  from the JSON; and a test parsing `docs/PREREG.md` tables into the
  exact JSON perturb lists. `SAME_AS_GROUPS`, `BUILDER_IDS`,
  `DISCONNECT_IDS` and `EXPECTED_EXPECTS` are gone, subsumed by the
  document-match test.
- `evals/demo_rejection.py`: everything derived from the M12 case (claim
  `claim-w1`, its first metric ref, the snapshot value), printing
  notice, DRAFT, REJECTED lines, SOURCE, FIXED, PASSED in that order and
  returning 1 with a reason when the draft codes differ from expected or
  the fixed version still fails.
- `AGENTS.md`: only the `make eval` and `make demo` lines changed.
- `CONTRIBUTIONS.md`: the Pre-registration entry now says what the
  targets do, in first person.

The fourth session replaced the single PENDING line in `docs/PREREG.md`
with my table and my forecast sentence, as exact text, and changed
nothing else in that file. It also resolved the merge conflict in the
README list and fixed the blank line the merge dropped in
`CONTRIBUTIONS.md`.

## Decisions and reasons

- Runner failures go to stderr, per-task summaries to stdout: the
  transcript stays readable while failures are still named with task and
  sample id, and the spec allowed either stream.
- A per-file failure prints `FAIL <file>: <exception>: <message>` (or
  `no tasks ran` when the call returns no logs) and the loop goes on to
  the next file: one run shows every problem instead of stopping at the
  first.
- The runner imports only `inspect_ai`: `evals/briefing_gate.py` inserts
  its own repo root, so the `sys.path` lines in the runner were dead
  weight and went.
- No files to the runner exits 2, failures exit 1: misuse and a failing
  eval are different outcomes; both are non-zero as required.
- Runner subprocess tests use `cwd=tmp_path` with relative file names:
  measured that `inspect_ai.eval` rejects absolute task paths
  (`NotImplementedError: Non-relative patterns are unsupported`).
- Those tests set `XDG_DATA_HOME`, `XDG_CACHE_HOME` and
  `INSPECT_TRACE_FILE` under `tmp_path`: measured that without them
  Inspect writes traces outside the repo and fails under restriction.
- The raising-scorer test also asserts the log status line says error:
  otherwise it could pass for some other reason than the scorer blowing
  up.
- `find_task_files` lets a parse failure raise: a file that cannot be
  parsed must fail the test, not look like a file with no task.
- The recipe test stops at the first line after `eval:` that is neither
  tab-indented nor blank: the old version read every tab-indented line
  in the rest of the Makefile, including other targets.
- The `KeyError` text mirrors the existing `unknown fact:` shape in the
  same function.
- Feed statements match on `feed items` containment before the
  startswith table, and unmatched statements fail the test: a label typo
  must break the build, not slip through.
- A feed statement cites its own sub-metric when the arm has one and the
  suffix appears in the statement: without that, the corrected I7 row
  would still fail the arm.
- I7 carried a strict xfail with `raises=AssertionError`, not a skip and
  not an excuse, while the row was wrong: the JSON followed the frozen
  table, so the arm stayed a visible expected failure, strictness forced
  the marker off once it passed, and a crash in that arm was a real
  failure rather than an expected one. The amendment corrected the row
  and removed the marker, so every arm is now checked the same way.
- Titles, fact statements and metric ids call `text_check_codes`,
  `action_targets_repo` and `metric_label_binding` directly, and each
  commitment goes through the `Commitment` schema with the JSON's
  `profile` mapped to `profile_id`: they're public on main since
  Ticket 10, so nothing is reimplemented or skipped.
- Doc-match parses changes with one regex finditer in order and picks
  `set_metric` vs `add_metric` by base membership: the document is what
  was pre-registered, so the JSON has to match it row by row.
- Demo `_fmt` drops a trailing `.0` and replaces the first occurrence
  only: the replay keeps working untouched when M12's wording or metric
  changes.

## Open items (closed by the amendment before merge)

- (a) The I7 row of `docs/PREREG.md` could not pass the number check:
  f6 said 6 and f7 said 2 while the arm's only feed metric held 8.
  The amendment corrected the row to a fresh `feed.item.count.medieval`
  metric holding 2, corrected the JSON to match, and removed the
  strict xfail, so the arm is checked like every other.
- (b) The review also reported points in the document's wording for me
  to decide: how the invariance rule treats ties and arms with no
  picks, a noop arm passing an avoid pair, the R3 prediction's
  denominator once uninformative pairs leave it, the line saying the
  gate checks cited events, the wording of one cited result, and R3's
  base slot. The amendment decided every one of them in the document
  (ties must all match, no-pick arms fail and are counted, avoid pairs
  need 2 real perturbed picks, uninformative pairs leave the
  denominator and are counted, cited facts with a separate fact-layer
  drop, the corrected result wording, and the 15:30 base slot where
  both goals appear live). Nothing has been published, so Deviations
  stays "None yet".

## Review

Claude Code reviewed the first session's output. The review found the
eval exit-code gap, the listing-test exemption, that `set_metric`
didn't check its id, the gate shell that cited every metric on every
claim (plus its L1-only filter and the f6-only pin), the hard-coded demo
sentence, and the stale Commands lines. A second pass found Inspect
silently dropping a broken file listed beside a good one. To check the
pins, the review mutated a scratch copy of the JSON and ran the tests on
each copy: the first session's tests let 7 of 40 mutants through, and
after the fixes 47 of 47 sharper mutants were caught.

After Ticket 10 merged, the review ran every arm through the merged gate
with each fact citing its own metric. Of the 21 arms, only I7 fails, with
the code in item (a). All 22 metric ids bind to a label, and all 8
commitment titles pass the text checks. On that tree it reran the 47
mutants and all were caught. It aimed 13 more at the helper checks, running
each check alone, and all were caught. It also ran 20 checks on
`make eval`, `make demo` and the listing test against damaged scratch
copies, including both targets with all network denied, and all 20 came
out as expected. A whole-file byte compare shows `docs/PREREG.md` differs
from the frozen text only by the split replacement.

## Commands and results

Every `uv`, `pre-commit` and `git` command ran under
`PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
`UV_CACHE_DIR="$PWD/.git/uv-cache"`. Claude Code ran these outside Muse's
sandbox on the reviewed tree, on top of main `8419879`.

- `make check`: exit 0. ruff check clean, ruff format clean, pyright
  clean. pytest: 620 passed, 1 xfailed (I7, item (a) above). gitleaks:
  `no leaks found` (19 commits scanned).
- `make eval`: exit 0. Five logs, all `success`: hello 1/1,
  briefing_l0/l1/l1b/gate 58/58 each.
- `make demo`: exit 0. Draft `Pushed 99 tasks in the synthetic trial`
  rejected with `L1B_METRIC_VALUE_MISMATCH`, source
  `github.push.count is 3`, fixed
  `Pushed 3 tasks in the synthetic trial`, `PASSED`.

Inside Muse's sandbox the test
`tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails
because the sandbox denies the loopback bind, so `make check` ran in full
outside it. All test data is synthetic.

Prompts and review by Claude Code. Implementation: muse-spark-1.3
(effort medium), in Muse Code, in headless sessions Claude Code started.
