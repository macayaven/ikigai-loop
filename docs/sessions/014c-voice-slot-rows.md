# Session evidence — 014c-voice-slot-rows (2026-11-02)

All sessions were headless, started by Claude Code, in Contributor mode, on this public repo and made-up data only. The plan was written on muse-wonder-1.0 (effort high), 4 m 48 s. Implementation ran on muse-spark-1.3 (effort medium), 17 m 42 s, after Claude Code's review amended the plan through that session's prompt. This commit step ran on muse-spark-1.3 (effort medium).

## Why I asked for it

The live poller runs `poll --voice` with no store argument, so the voice worker's store path is None. Every store the worker opens resolves None to the live file through IKIGAI_DATA_DIR, except the slot ledger, and three worker functions returned early instead. So on Nov 2 two voice-corrected cards, at the 20:30 and 22:30 slots, went out with no slot rows, and the learner's replay skipped my tap on the 20:30 one. Ticket 14's tests and its live runs always passed an explicit store path, so none of them could see it. A Claude Code session reviewing the learner's replay found it.

## What changed

`_slot_rows`, `_save_corrected_rows` and `_record_local_retries` resolve the store path the way the rest of the worker does; with an explicit path nothing changes. A search of the voice and telegram packages found no other place that skips work when the path is None. On the live path, card matching for a correction now uses the stored rows keyed by letter, the path the tests already ran with an explicit path, and retried local start failures during a re-proposal are recorded. The row rules moved into one shared builder that the worker and the new backfill both call. `python -m framework.voice backfill-slot-rows` rebuilds missing rows for corrected cards from stored rows only: a dry run by default, counts and ids only, writes only with --apply, one transaction per card, never touches a card that has rows. A side that kind, title and hour show to be unchanged copies the replaced card's row; a changed side takes its commitment from the stored re-proposal result, after dropping any stored result that would rebuild the replaced side itself, because a slot keeps the regular card's result next to the re-proposal's; it skips a card with a closed reason when the stored rows don't name exactly one commitment. ProposalStore gained one read of every stored result at a slot; results_for_slot is unchanged.

## The gate

The closure hash over the 47 framework files the gate reaches was 907b228d92cd before this change and is 907b228d92cd after it. No closure file changed.

## Tests

14 new. B1 to B3, in tests/test_voice_worker.py, run the worker with no explicit path and IKIGAI_DATA_DIR at a made-up store: the corrected card gets its rows, a tap on it is counted by the learner's replay, and a retried start failure is recorded. Each failed before the fix. B4 pins the explicit-path rows as they were. K1 to K10, in tests/test_voice_backfill.py, include rows equal to what the fixed worker writes for the same note, a dry run that writes nothing, a second --apply that writes nothing, the three skip reasons, no titles or transcript text in the output, a backfilled tap that counts, no commitments file needed, and the real slot's shape, the regular card's result next to the re-proposal's. All failed before the command existed. The voice, telegram and proposal store test files: 231 passed. make check on this code before the commit, run by Claude Code under a memory cap: exit 0, with ruff and ruff format clean, pyright at 0 errors, pytest at 4,469 passed and 1 skipped, and gitleaks finding no leaks. make eval: hello 1 of 1, each briefing task 176 of 176, glimmer_facts 30 of 30, proposal_gate 37 of 37.

## Rehearsal

Run by Claude Code from its own shell, outside this repository, on scratch copies of my store made with the SQLite backup API, with a loopback fake of the Bot API, a synthetic voice note spoken by ffmpeg's flite voice, and the real `poll --voice` loop called with no store argument, the store found through IKIGAI_DATA_DIR, as the live poller does. A regular card for the next day's 13:30 slot came from the real run-slot with code facts only. A note saying its side was already done today was transcribed, compiled and answered with a corrected card.

- Before the fix, on main's code: the corrected card went out with no slot rows, its tap was stored, and the learner's replay skipped it: 10 taps, 2 skipped.
- After the fix: the corrected card carried its row, with the note's applied instant as its time, and its tap was counted: 10 taps, 1 skipped, the one left being my real tap on the 20:30 card from Nov 2.
- The voice note took 25.5 s before and 33.1 s after, from arrival to the corrected card and the reply.
- In both runs strace showed no open of the live store file, and no open of the bot token's file or of the vault's env files; the fake Bot API stood in for Telegram, with a made-up token.
- The backfill's dry run on that copy saw 3 corrected cards: 2 to write, 4 rows, two for each of Nov 2's corrected cards, and the rehearsal's own card already present. With --apply on the copy, the learner's replay skipped 0 of 10 taps. A second --apply wrote nothing.

## Not verified

The fix on the live poller itself, since only the rehearsal ran it; the backfill on my real store, which is a separate decision; a dry run doesn't follow a chain, so a corrected card whose replaced card is itself a corrected card still missing rows shows NO_REPLACED_ROWS in the dry run, while --apply writes the chain in order; when a re-proposal offers the same commitment at the same hour, the backfill copies the replaced card's row, so its time is the old row's, not the note's, which the learner's replay doesn't read; and for a note resumed after its first pass, the backfill uses the first pass's applied instant, while the worker used the later pass's instant.

## Files

The ticket changes framework/voice/worker.py, framework/voice/__main__.py and framework/store/proposal_store.py, adds tests/test_voice_backfill.py and four tests to tests/test_voice_worker.py, plus the plan, this note and the entry. Nothing in framework/cycle, framework/telegram, framework/briefing, framework/proposal or evals changed, and no existing test changed.

## Who did what

Claude Code's prose prompts described the fault, the fix, the backfill and its rules, including the amendment for the slot's two stored results, which Claude Code found by reading the shape of the stored rows in a copy of my store, ids and counts only. Those prompts held no code blocks, patches or test rows; they named files, functions, tables, command-line flags and one environment variable. Muse Code wrote the plan, every file and this commit. Claude Code ran the rehearsal, the gate checks and make check from its own shell.
