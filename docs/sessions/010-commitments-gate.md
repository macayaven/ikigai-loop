# Session evidence — 010-commitments-gate (2026-11-01)

Ticket 10 only: commitments the model may schedule, and gate checks that bind each action and each claim to what it cites. This note summarises the work; the raw session exports are kept privately.

Sessions, all headless, started by Claude Code. Plan and two plan amendments on muse-wonder-1.0 (effort high). Implementation, two review-fix sessions and this commit session on muse-spark-1.3 (effort medium).

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, and `git` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Drawn from the plan Goal and Success Criteria. A model must only schedule commitments I wrote, and a claim must name what it cites:

- The `Commitment` schema and fail-closed loader: `IKIGAI_COMMITMENTS_FILE`, `profiles/commitments.example.json` with 14 made-up entries.
- `Action.commitment_id` required, and `exercise` removed from `ActionKind`.
- New codes: `L1_ACTION_NOT_COMMITTED`, `L1_ACTION_TEXT_MISMATCH`, `L1_COMMITMENTS_UNAVAILABLE`, `L1_ADVICE`, `L1B_METRIC_LABEL_MISSING`, `L1B_METRIC_LABEL_UNKNOWN`, `L1B_PERIOD_WORD_MISSING`, `L1B_DIRECTION_MISMATCH`, `L1B_TOO_MANY_METRICS`.
- Wider number tokens in `framework/briefing/numbers.py`.
- This repo counted as build evidence, with `L1_ACTION_TARGETS_REPO` kept.
- The old Profile B id renamed to `disconnect` in code ids and fixtures.
- Public helpers `text_check_codes`, `action_targets_repo`, `action_window_codes` for Ticket 11.
- README status and the GitHub row of `profiles/builder.md` brought up to date, at the coordinator's request, because the docs ticket landed first.

## Where this differs from the ticket

The plan Disagreements section (X1 to X8) records each reading the brief left open and the pinned resolution. One further count difference: `L1_COMMITMENTS_UNAVAILABLE` is one more code than the ticket listed, so an unset or unreadable file fails closed and can't be mistaken for a model inventing actions.

## Review

Claude Code reviewed the plan and the diff before the commit. What the review changed:

- Plan review, through two amendment sessions: the schema regeneration set (Section and Briefing embed Action); a mutant for every new code; loader availability and private terms checked at load; label forms that would falsely reject normal prose (`PRs`, `pull requests`, `Pushed`, `Feeds`, `canceled`); an empty label matching everything; hyphen compounds (`follow-up`, `wind-down`) counting as direction words; an uncited period word (`Pushes reached 3 in last` citing the window total); one registry instead of two.
- Code review, through two fix sessions: a period prefix on families Ticket 9 never emits was accepted, now `L1B_METRIC_LABEL_UNKNOWN`; `one-off` and `one-on-one call` read as the number 1, now free; a NUL in the commitments path raised instead of failing closed; underscore-joined words and words inside a metric's own label counted as direction words; G6 now builds its actions through `_action()`.
- Test strength: Claude Code patched a throwaway copy of the code outside the repo, one change at a time, and ran the tests. On the first pass 60 of 87 changes were caught. 24 tests were added in the review. On the final tree 98 of 100 were caught. The 2 left change nothing observable: the three-ref upper bound can't be reached when periods must differ, and an unknown period name already falls through to `None`.
- Attack scripts, also outside the repo, final tree: 163 gate sentences (51 that must pass, including the three sentences the ticket named, 102 that must fail, 10 since_last), 176 number-token rows, 57 loader inputs, all as expected.

## Acceptance tests

Run by Claude Code outside Muse's sandbox on the reviewed tree:

| Test | Result |
|---|---|
| AT1 | 73 passed |
| AT2 | 59 passed |
| AT3 | 40 passed, 169 deselected |
| AT4 | 90 passed, 119 deselected |
| AT5 | 59 passed (38 mutants with exact codes, 20 known-good, counts asserted) |
| AT6 | 234 passed |
| AT7 | 6 passed |
| AT8 | both greps no hits, builder.md diff one row |
| AT9 | no hits, `tests/fixtures/sample-disconnect.json` present |
| AT10 | no `exercise`, `commitment_id` on `Action` |
| AT11 | Inspect offline on `mockllm/model` exit 0, four tasks of 58 samples, all 58 scored correct in each |
| AT12 | 568 passed |
| AT14 | negative control on the base: both test files fail at collection with no `framework.briefing.commitments`, and both greps give 0 |

`make check` exit 0: ruff, format, pyright 0 errors, 568 passed, gitleaks no leaks. AT13 is this commit, checked afterwards. Inspect logs, gitignored: `logs/2026-11-01T14-12-18-00-00_briefing-gate_awbD5JELSmiDCPJ29EdaXs.eval`, `logs/2026-11-01T14-12-17-00-00_briefing-l0_EwcTFg8WynKf2Gc22N4mPs.eval`, `logs/2026-11-01T14-12-17-00-00_briefing-l1_AbiMayBsEsXALgqaeh9u3Q.eval`, `logs/2026-11-01T14-12-17-00-00_briefing-l1b_4cBeCCBsQofHLSuM4J988C.eval`. Inside Muse's sandbox `tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails because the sandbox denies the loopback bind; that is the only difference.

All test data is synthetic, and the real commitments file and the path in `HIDDEN_CRITERIA_DIR` were never opened.

## Known gaps

The header of `framework/briefing/numbers.py` states what the gate still does not catch. Added here: a real proposal and a real card don't exist yet, so false rejections on what the model actually writes are only measured against hand-written sentences, including the three the ticket named.
