# Session evidence — 013-orchestrator (2026-11-02)

Ticket 13 only: the orchestrator that runs one pinned slot from facts to delivered card. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code, in Contributor mode on this public repo and made-up data only. Plan and one plan amendment on muse-wonder-1.0 (effort high). On muse-spark-1.3 (effort medium): two sessions for a local overlay of Ticket 11's tree, which I never pushed and which was dropped at the rebase; four implementation slices; nine review-fix sessions, one of them at low effort; two rebase sessions; the commit session; and two amend sessions at low effort, of which this is the last. Prompts and review by Claude Code.

`~/.local/bin/muse --version` (paperwork session, first line, verbatim):

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, `git` and `make` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

One process tree runs a slot end to end, so a hand run needs no timer and the same command serves the timer. Code facts run first in-process; the local model runs as a child the parent can kill, so a hung model cannot take the slot.

The five pinned Madrid slots are 13:30, 15:30, 18:00, 20:30 and 22:30. Builder runs at every slot. Disconnect runs at 15:30, 20:30 and 22:30 only. Disconnect keeps three limits in code: at most 3 Disconnect cards a Madrid day, counting delivered and unknown sends; nothing at or after 23:00 by the slot or by the clock at send time; and from 21:00 only `music` and `rest` kinds by the hour the proposal is for.

The slot ledger is append-only and lives in the same database file. The learner replays at each slot with `observe`, never `update`, so a crash cannot double count; the price is that a tap counts from the next slot. At most one card rests on an unknown delivery, and only `--resend-unknown`, after I look at my phone, can send again. The Bot API path uses IPv4 only. Preflight refuses a wrong host before any model call. `check-slot` explains a slot or exits non-zero, `trace` shows what a card rests on and stays read-only, and `rehearse` sends one labelled TEST card for a real tap. `--slot-today` names a slot without shell date math.

A card never waits for a hung model: the local model's time ends four minutes before the slot and Wonder's 30 seconds before it, with a labelled fallback stored by then. A Muse Code run that dies locally before any model request retries after 5 s and 20 s inside the propose deadline, counted in the ledger and shown by `trace`. A calendar whose last good poll is over an hour old raises `CALENDAR_STALE` through the watchdog. No unit or host config lives in this repo.

## Independent reviews

I state who found what and what I did with it.

GPT Sol 6.1, run through Codex: a blind retry of `sendPhoto` could deliver the same card twice, when Telegram accepted the photo and the response was lost. I ruled: no blind retry on a send whose delivery is unknown. A request that never connected may retry. An unknown delivery records `DELIVERY_UNKNOWN` and alerts, and only `--resend-unknown`, after I look at my phone, can send again.

GPT Terra 6.1, run through Codex: D11 read any non-HTTP `URLError` as definitely unsent, though Python can wrap an error raised while the request body is written. It asked for a retry only when the failure is provably before transmission. I tested that finding before ruling on it. Claude Code tested this with the real client, real sockets and real TLS on loopback, the server resetting at random points in the body, near its end, after all of it, and acting as an eager parser that accepts on the closing delimiter. 2,124 trials, 0 attempts read as not sent on a connection where the server had accepted the request. At the real chart's size, 25,656 bytes, every reset read as unknown, so that case cannot duplicate a card. The same test found the one path that can: a 3xx on the POST, which urllib followed with a GET that failed to connect, then read as not sent, giving two accepted POSTs. So I stopped following redirects, and a 3xx on `sendPhoto` now reads as `DELIVERY_UNKNOWN`. I skipped the wider rule: it cannot be told from the exception types alone, and at the real chart's size it would change nothing I could measure.

GPT Sol 6.1 again: a hung local model holds the card past its slot, although code facts existed at `as_of`. A vote of my outside reviewers passed the rule that the card never waits for it, 5 of 5, with the condition that Wonder is bounded too. Measured on a fake clock with both models hung: before, the send attempt landed at 13:42:10 and 15:44:10 for the 13:30 and 15:30 slots. With only the local model's deadline moved, 15:30:10. With both moved, on the slot.

Muse Wonder Full, in a blind review of Ticket 11, raised four findings this ticket had to check on its own path. The next section gives what came of each.

The driver of Ticket 14, from its logs: 19 of 820 `muse exec` runs on Nov 1 died locally in about 0.15 s, before any model request, in two bursts. So a run that fails like that retries after 5 s and 20 s, inside the propose deadline, counted in the ledger and shown by `trace`. Stderr is now kept for those failures only, masked, in a table on my own machine.

## Live test

Run by Claude Code outside the Muse sessions, on made-up data, with a made-up token and chat id against a fake Bot API on loopback. Nothing reached a phone.

Facts:

- All of these ran on the tree just before the since-line fix and the private temp folder, with made-up rows and a clock shifted so a run could start at slot minus 25 for a 15:30 slot at any hour. Real time passed. Those two changed only the since line, `trace`'s reading of it, and where a Muse Code run keeps its temp files.
- On the final tree: real Wonder through real `muse exec`, a shifted clock, a fake Bot API. A first card on seeded rows read `First card, last 24h: code 1.8h, comms 3.4h, media 4.0h.`, the same hours as the chart's `last` period; before the fix the same seed read `First card, last 24h: 5 pushes + PRs, code 13.5h, comms 6.5h, media 4.2h.`, because every seeded row was first collected just before the card. The next slot read `Since 15:30: 2 pushes + PRs, code 0.7h, ai 0.1h.`, with a real `since_last` claim `Pushes rose by 2 in the last period.` and `trace` printing value 2, snapshot 2, parent 0. On the made-up shapes: a first card that read 17 now reads 2, a later card that read 6 now reads 1, a late screen batch that read 3.5 hours now reads 1.5. The crash matrix on the final tree: 401 checks, 0 failures. `make check` run from Claude Code's own shell, outside the sandbox, on the final tree: 2292 passed, 1 skipped, exit 0, gitleaks clean. With the system temp folder holding a `.git` folder, a dry run of a two-goal slot through real Muse Code on made-up data read `kind=fallback,fallback` on the commit before the fix and `kind=proposal,proposal` after it. Both models hung on a fake clock still sent on the slot in all six cases. Every unit's command ran under `env -i` again, and the `rehearse` command with a scripted tap read `kind=proposal,proposal`, 36 s, `code=RULING_SEEN ruling=A`, last line `card=<id>`, exit 0, one photo.
- A full slot through the CLI: real preflight, the real facts child on `muse-glimmer-30b` through llama-swap, real Wonder through real `muse exec`. Another eval of mine was using that model the whole time, and the child did not finish in its 21 minutes: `facts_model` `FACTS_DEADLINE` at 1,260 s, child killed, `facts_code` ok at 0.2 s. Builder proposal 18 s later, 2,461 completion tokens. Disconnect proposal 23 s after that, 3,188 completion tokens. Card stored at 1,302 s of the 25-minute lead. It waited and went out at 1,500 s, the slot's second: one photo, 0 API violations. This is the rule working on real parts: a slow model cost that card its model facts and no time. `check-slot` read `DEGRADED detail=CALENDAR_STALE`, exit 5, as it should on a scratch file with no calendar cursor. A scripted tap through `poll_once` stored one tap.
- The next pinned slot on that database, 18:00, on code facts, real Wonder: `kind=proposal`, 21 s. The since line read `Since 15:30: 2 pushes + PRs, code 0.7h, ai 0.1h.`, the rows added after the first card. The chart tally read Builder 1 from the tap, and replay saw the ruling. Wonder wrote a real `since_last` claim from the delta against the delivered card: `Pushes rose 2.`, with `trace` printing value 2, snapshot 6, parent 4. `check-slot` exit 0 on that slot, because the day's calendar alert had already gone. `trace` exit 0 on both cards.
- Both models hung, on the wall clock, 25 real minutes: the real facts child against a fake local model that takes the request and never answers, and `MUSE_BIN` a script that sleeps forever. `facts_code` ok at once, `facts_model` `FACTS_DEADLINE` at 15:26:00, Builder fallback at 15:28:10, Disconnect fallback at 15:29:30, card stored at 15:29:30, sent at 15:30:00, one photo.
- A burst against real Wonder: `MUSE_BIN` a script that dies at once on the first two `exec` calls with a made-up error, then hands over to the real binary. `local_retries=2` on Builder, both sides proposals, one photo, the masked stderr in its table and in `trace`, and the made-up path, email and token gone from stdout, the ledger, the table and `trace`.
- Every unit's command under `env -i`, with only the variables the plan's table names and a plain `PATH`, real Wonder, a made-up token and chat id, the Bot API base pointed at a fake: `run-slot` for a dry run and a real run, `kill=set` honoured, `SLOT_NOT_PINNED` on an unpinned time, `check-slot` with `IKIGAI_DATA_DIR` alone, `poll --once`, `trace`. The `rehearse` command with a scripted tap: seeded `TEST` titles, `kind=proposal,proposal`, 33 s to the send, `code=RULING_SEEN ruling=A`, last line `card=<id>`, exit 0, one photo. A real run with my thumb comes after this commit.
- Every Wonder attempt in these runs recorded `transport=muse` and `rules_file=0`.
- Earlier, on a tree before Ticket 9e: one full slot where the local model did finish, `facts_model` ok at 974 s, more than the 851 s measured before, card ready at 1,000 s, sent at the slot's second. And one real `getMe` through the IPv4 path from each of my two machines, with the real token read by variable name: ok, name lookups `AF_INET` only, no send and no poll. Those two are from before this session's later fixes.

## What review found

Claude Code read the diff, ran the acceptance tests, ran real processes on a scratch database, and tried to break it from scratch scripts outside this repo. Each fix went back through a new Muse session. Found:

- `facts_code` failed with `AssertionError` on every real run, because `run_cycle` was called without its two pass flags set off. Every fake test passed. A seeded run on the real `run_cycle` found it, and a test now holds it.
- A re-run reran the whole pipeline before it read the send state. It now reads the state first and resumes at the stored card.
- A dry run held the slot's lock, so a 12:50 dry run on the real file could have cost the 13:05 timer its card. A dry run now works on a backup copy and takes no lock.
- A refused slot wrote a `done` row. `killed` was not explained to the watchdog. The chart build sat outside its `try`. A stale slot spent model calls before it noticed. The 23:00 cut-off was checked once instead of at each send attempt. `TimeoutStartSec` of 45 minutes could kill a late send, so the plan now says 60.
- The series label had to read `pushes + PRs`. A lone Disconnect after a dropped Builder kept the letter B. An open send intent now counts toward the daily cap. The card and its sides now write atomically.
- A test paired a constant clock with a retry loop and hung the session for 7 minutes. Later prompts ask for time limits on real-process tests.
- `check-slot` read any `card` row with no send state as `COMMITMENT_GONE`, so a crash after the card step got the wrong name and a crash between the delivered row and `done` a false alert. `trace` printed the wrong parent when a noop slot sat between two cards. A resumed Disconnect card at the daily count ended with the cap's code. `rehearse` printed the card id only on a ruling, not after a card that got no tap or a 409.
- Three real-process tests took their slot from the wall clock, so they passed in the day and failed from about 22:30 until 13:00, which only a run from my own shell at night showed. A test pinned a hash of PNG bytes rendered on one machine, and the same code renders other bytes on Linux. The chart itself did not move: this code and the previous chart code render the same bytes on the same machine.
- From Muse Wonder Full's blind review of Ticket 11. A parent is now read from the delivered card, in the ledger: a refused card, then a `--fresh` run with Wonder down that delivered all fallbacks, used to leave a briefing I never saw as the next slot's parent. Only a hand run could reach it. Two cycles at one `as_of` do not reach a card: `run-slot` names the cycle it means, and the card read the model cycle in both string orders of the two ids, in a run where the store's own latest read picked the code cycle, and in a run where that read was made to raise. A late run cannot offer an hour that has ended: `as_of` is pinned before the slot, and past slot plus 30 minutes the card goes stale. It can offer an hour under way, by up to 30 minutes. Twelve working claims still pass the gate, and at most three per side reach the card and the Why? reply.
- Ticket 9e ended every period on a whole hour, and the card had not followed: a push in the open hour read as a chart of zeros beside a since line counting it. The since line and the chart now use the same floor, and an open-hour row shows on the next card, once. `trace` read the raw window too, and picked calendar rows by their start time, so it could print 2 source rows beside a snapshot value of 1.0, or none beside 2.0. It now selects rows the way the facts step does. The busy list loads calendar rows whole.
- A slot never asked whether the calendar collector was alive, so an empty busy list read as a free hour. A calendar whose last good poll is over an hour old now raises `CALENDAR_STALE` through the watchdog. The card still goes, and it does not say so.
- I reversed one rule at a time on a scratch copy to see whether the tests could fail. On the first pass 18 of 23 reversals in `trace` and `rehearse`, and 8 of 39 in the send path, the card and the client, left the tests green. So the tests that were missing now exist, among them that a slot already at `DELIVERY_UNKNOWN` sends nothing on a re-run. On the last pass, 1 of 23 survived in `trace` and `rehearse`: the replay check in `rehearse` cannot fail on its own seeded card. And 1 of 60 survived elsewhere: the kill-file check right after the wait, which the one before each send also covers.
- I kept the stderr for local start failures, and that same night it named the cause. A stray `.git` folder in `/tmp`, left by a `uv` command run from there, stopped every `muse exec` at startup, and both sides of a card fell back. The temp root and the child's `TMPDIR` now live in a private folder under the home.
- Claude Code ran a source-to-card audit on a scratch copy of my real store and found the first card's since line overcounting: a difference of two totals reads a late-collected batch as new. I reproduced it on made-up rows through the real `run_slot`: a first card with two pushes dated in the last 24 hours and 15 older ones first collected after the bound read `First card, last 24h: 17 pushes + PRs` instead of 2; a later card after a collector outage counted 6 instead of 1; a late screen batch counted 3.5 hours of code instead of 1.5. The line is now one plain count over the floored interval, and a row dated before the last card never counts as since.

## Checks run outside the repo

These scripts are not in this repo. I record them as what was run, with what came back.

- A crash matrix with real processes on this tree: a kill with `os._exit(137)` before and after each of 14 ledger writes, then a re-run, plus 14 failure scenarios on real processes and a fake Bot API on loopback (lost response, refused connection, 400, 429, 500, kill file, two runs racing, a stale slot, a dry run, preflight, missing files, a refused slot then a forced one, SIGKILL): 401 checks, 0 failures: at most one photo, one card id, whole card rows, right exit codes, no extra Wonder calls. An earlier pass showed 2 failures, both caused by my scratch script removing `META_API_KEY` from the context it was meant to test.
- The same kills with a real model cycle and a real facts child against a fake local model: 113 checks, 0 failures, and the proposals named a model cycle every time.
- Both models hung on a fake clock, six cases on a one-goal and a two-goal slot, including a bad first draft with a hung retry: the send attempt landed on the slot in all six.
- Real sockets on loopback, the client's failure classes: accepted with the response lost gives unknown with one complete request; refused gives not sent; 429 retries; 400 refuses; a reset while writing a large body retries with one complete request. All passed.
- The IPv4 HTTPS path keeps `CERT_REQUIRED` and `check_hostname`.
- Chart against snapshot: on seeded rows, every chart value equals the metric snapshot's value, and the since counts equal a by-hand count.
- I looked at the rendered PNG for the missing-data variants and for a real run's chart: they read.
- The evals on this tree: briefing gate 58 of 58, Glimmer facts 30 of 30, proposal gate 37 of 37.

## Acceptance tests

I ran each plan test file on its own, under the env prefix.

| File | Result |
|---|---|
| `tests/test_cycle_orchestrator.py` | exit 0, 157 passed |
| `tests/test_cycle_orchestrator_processes.py` | exit 0, 4 passed |
| `tests/test_cycle_card_build.py` | exit 0, 35 passed |
| `tests/test_cycle_slot_ledger.py` | exit 0, 20 passed |
| `tests/test_cycle_trace.py` | exit 0, 61 passed |
| `tests/test_cycle_rehearse.py` | exit 0, 8 passed |
| `tests/test_proposal_local_retry.py` | exit 0, 17 passed |

`make check` from Claude Code's own shell on the final tree: `ruff check` passes, `ruff format --check .` passes, pyright 0 errors, pytest 2292 passed, 1 skipped, exit 0, gitleaks clean. In the first amend session, inside its sandbox, on the tree before the private temp folder's three tests: pytest 2288 passed with 1 failed and 1 skipped. The one failure is the known sandbox gap, not this ticket: `tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails where the sandbox denies the loopback bind, and passes outside it. `test_default_runner_kills_group_on_timeout` passed here; its single earlier failure in a whole-suite run stands as recorded below. An earlier `make check` pass in this session also failed `tests/test_telegram_cli.py::test_privacy_note_states_five_claims`, because my first privacy section pushed the note to 33 lines against its 30-line limit; I shortened my own section to one paragraph and it passes. `gitleaks git --redact` run on its own found no leaks.

## Public-repo sweep

I ran a case-insensitive grep of the banned-word list and a grep of user home paths over every file in this commit. The banned-word grep found three hits, all pre-existing lines I did not write: the old profile filename, the old sample fixture name, and the docs-reconcile entry that renamed them. Nothing I wrote uses a banned word. The path grep found two hits, both masking-test fixtures with made-up paths in the local-retry test, and they stay. No line I touched carries a real path, and all data in the tests is made up.

## What the next tickets need

Ticket 14 adds skip, defer, drop and done through `EligibilityState` and `eligible_commitments` without changing call sites; proposals are not busy blocks, so two cards can propose overlapping hours; a Muse usage limit shows as `exit <n>` and a fallback, only `muse usage` by hand tells them apart, and product code never parses it; `raw_response` is stored at any size; Ticket 9c's labels stay off for Day 0, and when they come on the sweep runs after a cycle, is never waited on, keeps away from the next slot, and shares Glimmer's single slot; a run-slot `--dry-run` on the real file before 13:05 is worth doing, because a commitment title colliding with a raw literal only shows on real data; the Disconnect daily count still reads any card at a delivered slot, so after a `--fresh` it can count one too many, which only makes it stricter.

## Not verified

- No real tap has gone through this code path, and no real card has gone out. The dress rehearsal with a real tap (`rehearse`) comes after this commit.
- No slot has run on the real file yet. The one read of it for this ticket was the source-to-card audit's count of the since line, on a scratch copy, and no count from it is in this repo.
- No unit or timer has run this. The plan lists what each one needs.
- `test_default_runner_kills_group_on_timeout` failed once in a whole-suite run in a Muse session on my laptop, and that session's output kept no traceback. It races the shell's first write against a 0.5 s timeout. Claude Code could only make that race lose by shrinking the timeout to 10 ms or less under heavy load, where the kill lands before the shell writes its file, and could not make it fail at 0.5 s on the model host. So that is the likely mechanism, not a proven one. The group died in every run.
- A real Muse usage limit has not been hit: its path is tested with a fake runner only.
- The local model finishing inside its new 21 minutes has not been seen on this tree, because another eval of mine was using the model when I ran it. It finished in 974 s on the earlier tree.
- Tonight's local start burst is proven: a stray `.git` in the system temp folder stopped every `muse exec` at startup. Ticket 14's two earlier bursts fit it but aren't proven to be it. The retry has run against a script that fails fast, not against a real burst.
- Nothing in the send-race test ran against real Telegram: a server that acts before `Content-Length` is satisfied, plus a write failing on exactly the last bytes, is a case I could not build.
