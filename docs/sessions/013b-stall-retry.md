# Session evidence — 013b-stall-retry (2026-11-02)

## Who did what

Ticket 13b on branch `t13b-stall-retry`. Sessions, all headless, started by Claude Code, in Contributor mode on this public repo and made-up data only: on muse-spark-1.3, one implementation session and one review-fix session at effort medium, and this commit session at low effort. Prompts and review by Claude Code. No plan file exists for this ticket: the ticket text was the spec, and D13, D18 and D35 of `docs/plans/013-orchestrator.md` say what changed.

## What happened

The driver of Ticket 14 saw two concurrent Wonder calls open, get a first event at about 2.5 s, then stall until the 120 s timeout. The same two requests, sent again one at a time, returned in 7.9 to 12.5 s. So it looks like a stall on the service side, though nothing here proves that. It happened once in about 2,400 runs. In a real slot both sides would have become fallback cards, with time to spare.

## The rule

A Wonder call in a slot that ends in a timeout gets one more attempt when one full call's time, `WONDER_TIMEOUT_S`, remains before the propose deadline. Otherwise it falls back as it did before. Only a timeout gets this. Each Wonder call gets at most one extra attempt, so a first draft and a repair draft can each get their own. Once the kill file exists there is no second attempt. It is counted as `timeout_retries=<n>` on that side's propose row and on `trace`'s side line, apart from `local_retries`, so R1's denominators stay honest. It needs no new table, because a timeout has no stderr worth keeping. `check-slot` does not change.

## Why one full call

Ticket 11's stream measured 13 to 85 s per call, in D18. The 153 muse-wonder-1.0 calls at effort high in R1b's committed rows had a median of 11.2 s and a slowest of 33.3 s. So 120 s is more than a call needs, and a second attempt is never a weaker call than the first. With a hung local model, the first stall leaves about 90 s, so there is no second attempt and the timeline with both models hung stays what my outside reviewers voted on. In the one full slot where the local model finished, it reached the propose step at 974 s of the 25-minute lead, which leaves room for all of this.

## What it gives up

A second attempt that also stalls can take the time the other side's first call would have had: with the facts step ending 4.5 minutes before the slot, Builder's two calls use the whole budget and Disconnect falls back with no call at all. I accept that: it takes two stalls in a row, and the card still goes on the slot. A timed-out call leaves no row in `proposal_attempts`, because it produced no draft, so `timeout_retries` is the only record of it. A process killed during the propose step records neither count, the same as `local_retries` before it.

## Live test

Run by Claude Code outside the Muse sessions, on made-up data, with a made-up token and chat id against a fake Bot API on loopback. Nothing reached a phone. `MUSE_BIN` was a script that, on its first call or two, printed one event line and waited on a child that slept, then handed over to real Muse Code. Real time passed, on a clock shifted to a 15:30 slot. Facts, as a list:

- Started 300 s before the slot, one stall: Builder `proposal` at 137.7 s with `timeout_retries=1` and one stored attempt, Disconnect `proposal` at 148.8 s, sent at the slot's second, one photo.
- Started 260 s before the slot, one stall: about 110 s were left after it, so no second attempt. Builder labelled fallback at 120.4 s with no such key and `wonder_down=1`, Disconnect `proposal` at 134.5 s, sent at the slot's second.
- Started 600 s before the slot, two stalls: Builder labelled fallback at 240.6 s with `timeout_retries=1` and `wonder_down=1`, Disconnect `proposal` at 253.1 s, sent at the slot's second.
- After each of those, every stalled process was gone, and `trace` printed the count where the ledger held one and nothing where it didn't. `check-slot` read `DEGRADED detail=CALENDAR_STALE`, exit 5, as it should on a scratch file with no calendar cursor.
- Both models hung, on the wall clock, 25 real minutes: `FACTS_DEADLINE` at 15:26:00, Builder fallback at 15:28:10, Disconnect fallback at 15:29:30, card stored at 15:29:30, sent at 15:30:00, one photo, no `timeout_retries`. The same times as Ticket 13.
- A burst against real Wonder: `local_retries=2`, both sides proposals, one photo, the made-up path, email and token gone.
- Every unit's command under `env -i` again, with the same results as Ticket 13; the `rehearse` command with a scripted tap read `kind=proposal,proposal`, 35 s, `code=RULING_SEEN ruling=A`, last line `card=<id>`, exit 0, one photo.

## Checks run outside the repo

These scripts are not in this repo. Ticket 13's six hung cases on a fake clock, one-goal and two-goal, including a bad first draft with a hung retry: the send attempt landed on the slot in all six. A sweep on a fake clock with every call hung, the facts step ending at 31 distances from 1,500 s to 60 s before the slot, on a one-goal and a two-goal slot, 62 runs: the runner's timeouts and the retries matched a by-hand reckoning of the rule in all 62, with one send each. From 180 s out the send landed on the slot's second; closer than that, the hand-run budget from before this ticket decides, and there is no second attempt. The crash matrix: 401 checks, 0 failures. I reversed each new rule on a scratch copy to see whether the tests could fail: 21 reversals, the tests caught all 21.

## What review found

Claude Code read the diff and sent these back through a new Muse session. The second attempt ran inside the `except` block, so a second failure carried the first as its `__context__`, where the rest of this code keeps that field empty. No test held the order of the two wrappers, and with them swapped a local start failure would hand a call a second extra attempt. Two rules had no test that could fail: a `LocalStartFailure` that reads `timeout`, and a key on another side or another slot in `trace`. A test in the new test file wrote to the real home, and now uses a temporary one.

## Ticket 13's note

Its Acceptance sentence said a sandbox run was on that note's tree. That run was the first amend session, on the tree before the private temp folder's three tests. This ticket corrects it.

## Tests

All passing in Claude Code's own shell. No existing test had to change.

| File | Tests |
| --- | --- |
| `tests/test_proposal_timeout_retry.py` (new) | 20 |
| `tests/test_cycle_orchestrator.py` | 174 |
| `tests/test_cycle_trace.py` | 66 |

Then: `make check` from Claude Code's own shell on this tree on top of main: `ruff check` passes, `ruff format --check .` passes, pyright 0 errors, pytest 2482 passed, 1 skipped, exit 0, gitleaks clean. Inside a Muse session's sandbox, any test that builds a real `MuseExecClient` fails with `temp files` unless `HOME` points somewhere writable, because the temp root lives under the home and the sandbox holds it read-only.

## What the next tickets need

Ticket 14 rebases over this. `TimeoutRetryClient` in `framework/proposal/timeout_retry.py` takes any `WonderClient`, a `seconds_left` callable and a `min_seconds_left`, reads as no retry when `seconds_left` returns `None`, and gives its count on `retries`. Ticket 14's own calls keep what they have unless it wraps them.

## Not verified

A real stall on the service side has not met this rule: the stall here was a script. Nothing here proves the cause of the one stall that was seen. In that stall two calls ran at once, and a slot's calls run one after the other. No real card has gone through this code. A process killed during the propose step losing its count is read from the code, not run.
