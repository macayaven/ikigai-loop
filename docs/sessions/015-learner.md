# Session evidence — 015-learner (2026-11-01)

Ticket 15a only: the learner core and its known-preference test. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code. Plan and two plan amendments on muse-wonder-1.0 (effort high). Implementation, two review-fix sessions, this paperwork session and the commit session on muse-spark-1.3 (effort medium). Prompts and review by Claude Code.

`~/.local/bin/muse --version` (paperwork session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, and `git` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Drawn from the plan Goal and Success Criteria. The learner turns my card rulings into per-slot preference counts, nothing more:

- A pure package, `framework/learner/`, exactly seven files (`__init__.py`, `schemas.py`, `beta.py`, `policy.py`, `scoring.py`, `simulate.py`, `__main__.py`): standard library and pydantic only, plus `SchemaModel` and `NonEmptyStr` from the existing schema modules. No clock read, no env read, no network, no model call.
- The Beta posterior per time bucket from a uniform Beta(1, 1) prior, stored as integer alpha and beta. Only a real choice between two proposals on an undecided card moves it; one-proposal cards, neither, wrong, why and repeat taps never do.
- Each prediction scored before its ruling against three comparators: always 0.5, the majority vote so far, and the pooled rate across buckets. Scoring runs before the update, so the prediction cannot see the ruling it predicts.
- Deterministic ranking of my commitments with a pinned reason per position; the pick and the alternative land in the pick log on each card.
- `policy_block` as one compact JSON string of ids and numbers only, for the proposal prompt.
- Byte-identical `replay` over any ruling list, and `policy_diff` listing exact leaf differences between two states.
- The exact Beta quantile in integer arithmetic, bisected over k / 2^64: no scipy in the lock, and a normal approximation fails at the small n this ticket studies (fixed-preference coverage 0.8352 against 0.9898 exact at true_p = 0.6, n = 5).
- The CLI: `python -m framework.learner recover --seed 1` prints the full known-preference table, byte-stable for a given seed.

The decisions and their reasons are D-1 to D-25 in the plan, and the readings I chose are X1 to X7.

## The known-preference table (simulated)

Simulated rulings from a known preference, with no real data. This is the full default table, seed 1, 2000 simulations per cell. The note under the table is printed by the CLI and travels with the JSON too.

```text
SIMULATED rulings from a known preference. No real data. seed=1 sims=2000
true_p n_cards correct_side mean_absolute_error coverage mean_interval_width
0.500 5 n/a 0.134 0.937 0.627
0.500 13 n/a 0.093 0.983 0.468
0.500 30 n/a 0.068 0.961 0.334
0.500 100 n/a 0.039 0.948 0.192
0.600 5 0.700 0.126 0.990 0.620
0.600 13 0.778 0.093 0.949 0.459
0.600 30 0.825 0.068 0.965 0.327
0.600 100 0.968 0.039 0.941 0.188
0.700 5 0.842 0.121 0.968 0.600
0.700 13 0.935 0.091 0.970 0.436
0.700 30 0.982 0.064 0.930 0.308
0.700 100 1.000 0.037 0.948 0.176
0.800 5 0.946 0.125 0.946 0.568
0.800 13 0.993 0.079 0.972 0.392
0.800 30 1.000 0.057 0.964 0.273
0.800 100 1.000 0.031 0.943 0.155
0.900 5 0.989 0.116 0.911 0.519
0.900 13 1.000 0.070 0.966 0.328
0.900 30 1.000 0.044 0.974 0.215
0.900 100 1.000 0.024 0.943 0.118
n_cards is the number of real two-proposal choices fed to one posterior. Cards with one proposal, and neither, wrong or why taps, add none. My live run expects about 13 cards over three days, and Disconnect appears at 15:30, 20:30 and 22:30, so at most about 7 of them can be real choices, 2 or 3 per time bucket. A live bucket's posterior will hold about 3 choices, so even the n = 5 row is optimistic for it. The n = 13 row is an upper bound on the pooled reading, available only if the preference does not vary by bucket.
```

Coverage at a fixed preference is not meant to read 0.95. A credible interval is 95% only on average over the prior, and the plan's frozen exact grid runs from 0.9185 to 0.9898 across these cells. Read coverage with the interval width beside it, because a wide enough interval always covers.

## What review found

Claude Code read the whole diff, ran every acceptance test and `make check`, and tried to break the code from scratch scripts outside this repo. Each fix went back through a new Muse session.

- **`score_report` counted the wrong thing.** `correct` and `wrong` looked only at which side of 0.5 a call sat on, and ignored the outcome. On the frozen four-ruling sequence the learner read 2 correct, 0 wrong, 2 no call. The hand count is 1, 1, 2. R8 reports these numbers. Fixed, and the counts of all four predictors are now pinned.
- **A seen card could change its labels.** A later ruling on a card could swap A and B, pass the seen-card check, and move the posterior for the wrong profile, because the pick log held no label. `PickLogEntry` now carries the label and the check compares it.
- **Two copies of the prediction formulas.** `score_before_update` repeated `predict`. Both now call one private helper.
- **Tests that could not fail.** The blindness test compared `predict` with itself, and the one-sided test computed its loss by hand instead of reading a logged entry. Both now go through `score_before_update` and `observe`. Of 97 source mutants run against the first implementation, 22 survived, among them a `wrong` tap moving `beta`, `policy_block` reading a fixed bucket, a last-offered slot moving backwards, and a shortened default grid. New tests cover them.
- **`ruff format --check .` reads Python fences in Markdown**, so the plan failed `make check` until it was formatted.

## Checks run outside the repo

These scripts are not in this repo. I record them as what was run, with what came back.

- Source mutants: 137 on the final code, one exact edit each, in scratch copies. 135 caught. The other two change no behaviour: ignoring seconds in `bucket_for`, because every bound sits on a whole minute, and removing the mixed-profile check in `policy_block`, because `rank_commitments` raises `ValueError` for the same input. The plan's line about mutants is about eval mutants. This ticket changes no eval and no block, so no eval mutant run attaches to it.
- The interval against scipy on 962 (a, b) pairs: worst absolute difference 1.7e-15.
- The default table against exact enumeration, six seeds, 450 statistics: z-scores with mean -0.02 and standard deviation 0.98.
- A 25-seed fuzz against an independent model of the counting table and the scoring: no differences.
- The call sequence T13 is told to use, on the made-up commitments in `profiles/commitments.example.json`, reloading the state from its JSON before every call: the final bytes equal `replay`, including from rulings stored as JSON, and every policy block passes `text_check_codes` with no code.

## Acceptance tests

I ran each with its exact command from the plan's table, under the env prefix. AT-NEG was run by the implementation session on the bare tree: 2 collection errors, `framework/learner` absent.

| Test | Result |
|---|---|
| AT1 | 34 passed |
| AT2 | 23 passed, 33 deselected |
| AT3 | 6 passed, 50 deselected |
| AT4 | 4 passed, 52 deselected |
| AT5 | 4 passed, 19 deselected |
| AT6 | 12 passed, 11 deselected |
| AT7 | 2 passed, 21 deselected |
| AT8 | 15 passed, 41 deselected |
| AT9 | 5 passed, 51 deselected |
| AT10 | 5 passed, 18 deselected |
| AT11 | 5 passed, 51 deselected |
| AT12 | 9 passed |
| AT13 | 3 passed, 8 deselected |
| AT14 | 2 passed, 9 deselected |
| AT15 | 5 passed, 6 deselected |
| AT16 | 9 passed |
| AT17 | exit 0; stdout opens with the `SIMULATED` line for seed 1, sims 20 and prints one row per default true_p for n_cards 5 |
| AT18 | 7 passed |

Learner suite, `uv run pytest tests/test_learner_*.py -q`: 146 passed.

`make check` in this session: ruff check passes, `ruff format --check .` passes (109 files already formatted), pyright 0 errors, pytest 713 passed with 1 failed, so `make` stops before gitleaks with `make: *** [check] Error 1`. The one failure is the known sandbox gap, not this ticket: `tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails where the sandbox denies the loopback bind, as recorded in `docs/sessions/008-briefing-gate.md`. The bind in the server thread raises `PermissionError: [Errno 1] Operation not permitted` on `HTTPServer(("127.0.0.1", 0), handler)`, which surfaces as `assert ready.wait(timeout=15.0)` giving `assert False` at `tests/test_ingest.py:468`. I record this as a gap in this session's run. The reviewer's run outside the sandbox, on this tree before this paperwork: `make check` exit 0, 714 passed, gitleaks no leaks.

## Measured

I timed `uv run python -m framework.learner recover --seed 1` at 23.7 s wall against the 60 s budget: inside. I timed the learner suite at 146 passed in 10.2 s (10.6 s wall with `uv` startup) against the 15 s budget: inside.

## Public-repo sweep

Over every touched file, I ran the banned-word pattern from the plan's AT-BAN row over `framework/learner`, `tests/test_learner_*.py`, `docs/plans/015-learner.md` and `docs/sessions/015-learner.md`, and over the added lines of `CONTRIBUTIONS.md` and `README.md`: no hits anywhere. `grep -c '/Users[/]'` gives 0 for each of the two Markdown files. No URL sits in any touched source file, no real name sits in any touched text source (I checked both), and every id in the tests is synthetic (`b-1`, `b-2`, `d-1`, `d-2`, `card-001`, `sim-builder`, `sim-disconnect`) with frozen instants throughout. All data in the tests is synthetic.

## Not verified

- Byte-identical replay and the golden string have only run on macOS so far. The CI run on Linux will be the first run there.
- Nothing calls the package yet. T11 and T13 are on other branches, so no live call path has run, and no real ruling has gone through it.
- The table says what simulated choices fed to one posterior can show. My live run gives each bucket 2 or 3 real choices, which is below the smallest row.
