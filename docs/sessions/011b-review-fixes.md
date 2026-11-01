# Session evidence — 011b-review-fixes (2026-11-02)

Ticket 11b on branch `t11b-review-fixes`, per `docs/plans/011b-review-fixes.md`. All headless, started by Claude Code. Plan on muse-wonder-1.0 (effort high), two sessions. Implementation and fixes on muse-spark-1.3 (effort medium). These sessions ran in Contributor mode, on this public repo and made-up data only.

`muse --version` read `Muse Code 1.4.14 (1.4.14-R7309.1)`.

## Where it came from

Muse Wonder Full reviewed Ticket 11 blind, at `0493046`, and found twelve problems. Its sandbox could not run anything, so it marked each as a code trace. Claude Code ran its three reproduction scripts from a normal shell, and every traced finding reproduced. This ticket fixes eight: items 4, 6, 7, 8, 9, 10, 11 and 12. Items 1, 2 and 3 belong to the gate's own ticket. Item 5 is dropped: the orchestrator in Ticket 13 pins `as_of` before the slot and refuses a stale card, so its path never reaches this, and that was tested there. A hand run of `propose` with a late `as_of` can still propose an hour already past, and nothing schedules that path.

## What the live run found that the review could not

Claude Code ran a real `muse exec --json --contributor-mode on` on a made-up prompt. The configured event and the usage row both said the clean `muse-spark-1.3`. The only place outside free text with the word contributor was a provider detail in a `task_lifecycle` event, `muse-spark-1.3-contributor`, which the parser never read. So the check I shipped in Ticket 11 accepted a real Contributor run and could never fire on one, and I have put dated corrections on the two lines of that note. The forced `--contributor-mode off` was and is the real safeguard. The fix reads any `model` or `model_id` field at any depth, and free text cannot trip it.

## Before and after, from the review's own scripts

| Item | Before | After |
|---|---|---|
| 4 | A `builder` fallback wraps a `disconnect` commitment, `kind=fallback` | `kind=noop`, `NOOP_NO_ELIGIBLE_COMMITMENT` |
| 6 | The reader shows the fallback, and `latest_proposal` returns the superseded proposal | `latest_proposal` returns none when nothing earlier exists, and the earlier proposal when one does |
| 7 | `fetch_latest_cycle` returns `cycle-z-old` although `cycle-a-new` was recorded last | `cycle-a-new` |
| 8 | A contributor model in an earlier usage or configured event, and a run with no model event, all accepted, and a failed terminal followed by a completed one accepted too | `contributor model` twice, `no model evidence`, `muse terminal` |
| 9 | A reported contributor model accepted, with `prompt_tokens=True` and `completion=-5` | `contributor model`, and a boolean or negative token value gives `None`, checked by a test |
| 10 | `working_claim_count=12` | `DRAFT_UNPARSEABLE`, one retry, `FALLBACK_UNPARSEABLE`. The review script scripts one reply, so unmodified it stops at the retry with `client called more times than scripted`; a copy with a second scripted reply, and only that change, runs to the end |
| 11 | Two different drafts at one slot with one commitment share an id | They differ, the same draft gives the same id. The review's own line records one result twice, so it still shows one id, which is right: a byte-identical briefing is one briefing |
| 12 | A 5 MB garbage reply with a valid end accepted | `output too large` |

## Model evidence, measured at scale

A missing provider detail now fails closed. Claude Code kept stdout from real runs with the product's own flags, including `--preset empty`, on made-up prompts: 168 clean runs, all completed, and 168 of 168 carry the provider detail. `muse-wonder-1.0` at high 72, at low 20; `muse-spark-1.3` at high 15, at low 21, at minimal 40; 80 of the low and minimal runs used the voice-correction schema shape. Muse's own session logs on the same machine hold 1,759 completed model calls and 1,759 provider details, and 113 of 113 completed runs carry one, including a retried attempt. Muse's tracing logs hold 1,473 processes with the empty preset and a completed model call, 1,474 calls, each with a provider stream terminal line and a request id. Their stdout was not kept, so I cannot read the detail for those. In the 169 runs where both exist, the line and the detail match on request id, bytes read and wire events, 169 of 169. Those counts are the night of November 1 to 2. After the fix, the parser run over the 169 kept streams closed the one Contributor stream and accepted the 168 clean ones, and a fresh real Contributor run and a fresh real clean run went the same way.

## The cap

4 MiB, one constant, per call. Peak memory growth, through the real runner and a real loopback server:

| Reply | Before | After |
|---|---|---|
| 5 MiB reply | 15 MiB, accepted | 4 to 8 MiB, refused |
| 64 MiB reply | 161 to 192 MiB, accepted | 4 to 8 MiB, refused |
| 256 MiB reply | 635 to 768 MiB, accepted | 4 to 8 MiB, refused |
| 1 GiB reply | 3,071 to 3,279 MiB, accepted, 3.3 to 16.8 seconds | 4 to 8 MiB, refused, 0.04 seconds or less |

The cap is 93 times the largest real stream I measured, 45,036 bytes. A real child past the cap is dead in about 0.01 seconds, and a child writing exactly the cap comes back whole.

## A line that could crash a slot

A line of deeply nested JSON made `json.loads` raise `RecursionError`, and `_parse_stdout` let it escape. Claude Code found that while reading the code for item 12. It is now skipped like any unreadable line.

## Existing databases

A file written by main's code, holding cycles at one `as_of` with different offsets and a proposal then a fallback at one slot, opens with this code with no migration. `fetch_latest_cycle` picks the row recorded last, `latest_proposal` gives none, and `results_for_slot`, `last_offered_by_commitment` and the first-draft report all read it. Rowids ascend in recording order because rows are never deleted. A byte-identical replay adds no row, so it does not move the pick; a recording that differs adds one and wins, even over a richer pass. A `VACUUM` on a copy kept the order and the pick, and nothing in this repo vacuums.

## Hour checks

The review's `repro_hour.py`, rerun on this tree, printed the same output as before the ticket: all five live slots land on the slot's own hour, 22:31 gives no hour, and the busy edges and the 59-minute gap behave. Its `SLOT_has_seconds` case moves a slot at 13:30:01 to 13:45, which matters only if a slot time ever carries seconds.

## Tests

The new and flipped tests, run against main's code in a separate clone, give 58 failures. The tests that pass there are the existing ones and those that pin kept behaviour. On this tree `make check` gives 3,197 passed and 1 skipped, with ruff, format and pyright clean and gitleaks clean. `make eval` is still green, with `proposal_gate` at 37 of 37. The live acceptance test passed again against real Muse on this tree.

This ticket was moved onto main after Tickets 13, 13b and 14 landed. The runner keeps Ticket 13's stderr file. The cap check runs before the exit branch, so an oversized run can't read as a fast failed start. Neither retry wrapper retries `output too large` or `no model evidence`, and tests show each passes through after one call. The test streams in those tickets' tests gained the provider event, and no assertion changed.

## What I did not verify

The fix has not run through the orchestrator's real slot flow. The tracing-log calls with no kept stdout are unread, not confirmed. The Model API transport ran on loopback only, because my key is revoked. Nothing ran on a Mac tonight. A runner injected by a caller that raises something other than `OSError` still escapes `complete`, as it did before; the default runner does not do that.

Every `uv`, `pre-commit`, and `git` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.
