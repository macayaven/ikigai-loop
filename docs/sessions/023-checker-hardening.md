# Session evidence - 023-checker-hardening (2026-11-02)

## What changed

The command line and both panes of the page now run a wider checker, framework/verify/hardened.py, which adds negation, quantity forms, and units and periods where the caller declares them, on top of everything the older checker reports, and says per claim which checks didn't run for lack of metadata. The input gains two optional maps, units and periods. framework.verify.verify_claims keeps the earlier, smaller set of checks, because it sits inside the import closure my live run's gate is pinned to. I point to the plan for the decisions behind each of these: [docs/plans/023-checker-hardening.md](../plans/023-checker-hardening.md).

## The bug report

In the Nov 1 night review, outside reviewers reproduced that the public checker passed a negated value and the same value in minutes against an hours metric. On main at 5b8dad6, on Nov 2 at 21:00, Claude Code ran the command line on these, each citing a metric of 1.75 labelled programming and last: "Programming in last was not 1.75 hours", "Programming in last was 1.75 minutes", "Programming in last was 1.75%", "Programming in last was over 1.75 hours" and "Programming in last was about 1.75 hours" all passed with no violation, and so did "Deploys were 9 in October and 5 in November" citing October 5 and November 9 in one declared series. The controls held: "Programming in last was 1.75 hours" passed, "Programming in last was 1.85 hours" failed with L1B_NUMBER_WITHOUT_METRIC_REF, "Deploys were 5 in October and 9 in November" passed, and "Deploys were 5 in October and 8 in November" failed with L1B_NUMBER_WITHOUT_METRIC_REF. The live page gave the same verdicts in headless Chrome, and its plain form passed the negated and the minutes sentences.

## After

On this branch, through the Python function, the command line and the unpacked page bundle, which agree on all 20 inputs: with units hours and period last declared, the negated sentence fails with L1B_NEGATED_CLAIM, minutes and percent fail with L1B_UNIT_MISMATCH, over and about fail with L1B_UNVERIFIABLE_QUANTITY; with periods October and November and units count declared, the swapped months fail with L1B_VALUE_PERIOD_MISMATCH. The true sentence passes with the first line PASS; 1.85 still fails with L1B_NUMBER_WITHOUT_METRIC_REF alone; the true months pass; 8 in November fails with L1B_NUMBER_WITHOUT_METRIC_REF and L1B_VALUE_PERIOD_MISMATCH. With no units or periods declared, the negated, over and about sentences still fail with the same codes, while minutes, percent and the swapped months pass with the first line PASS - checks skipped and the unit and period checks listed as not checked.

## The page

Claude Code served it from this tree on the Spark, in headless Chrome with a fresh profile. It was ready in 2.9 seconds, made 12 requests while loading (the page host and cdn.jsdelivr.net) and none after. In the JSON pane the negated, minutes, percent, about and swapped-months inputs fail with the new codes, the true sentence passes and the wrong digit fails. In the plain form the negated and about sentences fail, and the true sentence passes with a line saying some checks didn't run and naming them. The page's verdict lines now say that the numbers in a sentence match the records and that other words weren't checked, and a failing line says the sentence didn't pass and points to why, because the checker never judges whether a sentence is true; an outside review on Nov 2 asked for that. The page at the public address runs main's checker until this merges.

## Parity

tests/test_verify_parity.py is byte-unchanged and still pins the older checker: 33 of 119 mutants and 45 of 57 known-good cases expressible. The new tests/test_verify_hardened_parity.py compares the gate with the new checker: 59 of 119 mutants and 45 of 57 known-good cases are expressible, and on all 104 the gate and the new checker give the same codes and verdict; the command line agrees on every verdict and the unpacked bundle on every code. 26 mutants became expressible through negation, quantity forms, units and period binding. 7 more were tried and stay excluded with their reasons in the file.

## The freeze

The gate's import closure was 47 files with hash 907b228d92cd991b49915aca610de560135ec34467b2a152e29e3966c956ec07 before and after; no file in it changed, and a test pins the new module outside it.

## Speed

Natively on the Spark, the worst case under the existing caps, 50 claims of 2,000 characters, took 3.4 seconds on the older checker and 4.7 on the new one. Hostile shapes after review: a 5 MB cited fact 0.0 seconds, 100,000 declared series with 5,000 claims 1.6, 1,000 claims citing 100 metrics with units 1.3, 5,000 failing claims 1.4.

## What review changed

Claude Code's review found, and Muse Code changed: a name scan over cited facts that is quadratic in a long run of letters, so a 5 MB fact never finished (names are no longer read from facts, which can only make the check stricter); the period and series maps, unit tokens and base findings rebuilt per claim (a run with 100,000 series took over 150 seconds); a depth scan that lost an alternation and counted brackets inside strings; glued units such as 1.75h failing on an hours metric; a stated zero that depended on set order, so the same input gave different codes from run to run; a value-period check that treated a metric outside every series as part of one; equal values that gave no difference of 0; cited values turned into floats; an unreadable message for a bad unit; and a pytest pin on the closure hash that would have turned every later gate change red.

## What it rejects that is true

Of 19 true sentences with units and periods declared, 4 fail. "Deploys rose by 2, from 5 in October to 7 in November." fails because 2 is not a cited value, as on the older checker. "Tickets closed in Q3 came to 120." fails because the 3 in Q3 reads as a number, as on the older checker. "Deploys were 5 in October, followed by 7 in November." fails because by 7 reads as a stated change. "Deploys in November were 7, with no rollbacks." fails because a negation word fails a claim with a metric unless it states a cited zero.

## What isn't verified

The page at the public address, until this merges; a real phone and a slow connection; how the new arms behave on a stranger's wording beyond the gate's cases and these probes; mutation testing of the new module. The live gate didn't change and the live clone wasn't touched.

I never opened the path in HIDDEN_CRITERIA_DIR and no test used the network. The implementation sessions ran the repo's checks; this session ran none and changed no code, test or other doc beyond the README line the ticket names.
