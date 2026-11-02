# Session evidence — 014-voice-correction (2026-11-02)

Ticket 14 only: a voice note corrects the card. This note summarises the work; the raw session exports are kept privately.

Sessions, all headless, started by Claude Code. Plan on muse-wonder-full-1.0 (effort high), 13 m 43 s, 429 lines; amendments on muse-wonder-1.0 (effort high), 12 m 44 s; implementation and fixes on muse-spark-1.3 (effort medium); mechanical moves on muse-spark-1.3 (effort low). They ran in Contributor mode, on this public repo and made-up data only. The product's own calls don't: see [docs/PRIVACY.md](../PRIVACY.md).

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

The rules file was absent on the model host. Every `uv`, `pre-commit`, and `git` command in this session runs under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Drawn from the plan Goal and Success Criteria. A voice note in my chat is stored before anything can lose it, transcribed on my subscription, compiled into one typed operation by a guarded model call, checked by code, applied as append-only events, and answered in the chat with the transcript, the effect, and a real elapsed time. When the correction changes what the card offered, a new card for the same slot replaces the offer at once, reusing the facts already stored and re-proposing only the side that changed.

- `framework/voice/schemas.py`: `Operation`, `Until`, `CompiledCorrection`, `UnparseableCorrection`, `build_correction_schema` with the per-call id enum, `parse_compiled` with the empty-question normalisation, `validate_compiled` with the closed codes, and `change_line`.
- `framework/voice/prompt.py`: `build_compile_prompt` with the exact frozen template, the pinned weekday tuple, marker stripping, and fill-once.
- `framework/voice/state.py`: the pure fold over `(said_at, message_id)` with the pinned return table, `keep` undoing a skip, defer, drop or done, `filter_eligible`, dispute folding, `apply_disputes`, `disputes_for_cycle`, and `standing_chain_ruling`.
- `framework/voice/transcribe.py`: ffmpeg then `muse voice transcribe` through the runner seam, 0600 temp directory, the closed exit mapping, with the Contributor-mode check first.
- `framework/voice/compile.py`: the pre-scan, the client call, and the parse.
- `framework/voice/mode.py`: `contributor_mode_status` with the closed codes.
- `framework/voice/ledger.py`: `VoiceRow` and `VoiceLedger` on the `voice_notes` table, claim and requeue, retry waits, `rows_for_card`, corrected count.
- `framework/voice/worker.py` and `framework/voice/__main__.py`: the wake handler, `build_voice_deps`, card matching with the newest-descendant walk, `process_one` in the pinned step order, the corrected-card builder, reply builders, and read-only `show-chain`.
- Telegram: the poll loop in the service persists first and imports nothing from `framework.voice`; only the CLI's `--voice` path imports it; the ledger holds the voice row, the message map and the stored chart; the client gains `get_file_path` and a bounded download behind one token-read helper and one urlopen seam; `Card` gains the change line and the replaced-card link with conditional canonical keys; the poll CLI gains `--voice` with the model and effort parameters and the startup code lines.
- Schemas: `AppCorrectionData`, `AppFactDisputeData`, `AppVoiceNoteData` join the event union with their three `schemas/*.json` files generated, and the cycle seam passes `disputed` into `run_proposals` at the facts and snapshot build.
- Ticket 13 seam at rebase: the corrected path reads stored results and the stored chart, writes its `slot_cards` rows, reuses the grouping and letter rules, and the tally and learner group by chain through `standing_chain_ruling`.
- Evals: `evals/r9.py` with the loader, the pinned scoring and the one-pass runner writing one file per arm, and `evals/r9_matcher.py` with the literal baseline; the frozen set and the result files landed only in this final pass.
- Tests: eleven new files plus the new arms in the Telegram, cycle and leak suites; fakes throughout, no network.
- Docs: this plan, the session note, the Ticket 14 entry, the Status move with the real count, and the `docs/PRIVACY.md` lines.

## Where this differs from the ticket

- The brief's sentence that pinned fields must be null can't hold: those are `done` cases that accept `until` today, so it would fail every one by construction. The headline is the exact tuple plus question, with `correct_ignoring_pinned_fields` beside it.
- The set entered the tree only in this final pass, not straight after the freeze, so no implementation session could read it. The prompt and schema were frozen at a local commit before anyone opened the set, and the file hashes are unchanged since: `framework/voice/prompt.py` `660c5174d93c75fc87d720c9c51a519923147b1eaf167d7bd2abee233c1367f2`, `framework/voice/schemas.py` `339e45315305287759b3cd3a5d212f6fdda000092bf67d773d5c58ec69989927`. Both rendered shapes still give their recorded sha256 after every rebase.
- The first transient wait is 5 s, not 30 s, because of the fast local failure below.
- D17 grew after a live run, see Review.

## Who wrote what

The same facts as the `CONTRIBUTIONS.md` entry, stated plainly. All times Madrid, Nov 1. A Claude Code agent wrote the literal matcher's English rules as a throwaway script at 14:20, from a one-line rule list, and froze them by hash at 14:22, before that measurement's first model call. The same agent wrote that measurement's prompt, whose operation and until definitions the compile prompt starts from. A separate Claude Code agent wrote the 60 held-out notes at 15:16 and froze them at 15:22, under instructions not to read those prompts or keyword rules. At 20:37 Claude Code pasted the matcher, about 48 lines, with the Spanish operation words, into the plan amendment prompt, along with the compile template's three edits word for word, and the last two `docs/PRIVACY.md` paragraphs. The set was first opened at 21:03, for a shape check that prints counts only, after the freeze. I kept the matcher as it was: it was fixed before any R9 result, and rewriting it after seeing the score would be worse. Later prompts also name some signatures and one-line expressions; Muse Code wrote every file and every commit.

## R9

The frozen set of 60, one pass per arm, no retries, strict `json.loads`, on the model host, from a scratch clone of this code, Muse Code 1.4.14, rules file absent.

| Arm | Passed of 60 | Median | Worst | Transport errors | Tokens | Missed cases |
|---|---|---|---|---|---|---|
| matcher | 13 | no model | no model | 0 | no model | scored 13; `matcher-until-words` also 13 |
| muse-spark-1.3 minimal, the default | 58 | 2.48 s | 3.97 s | 0 | 1,048,926 | 114 and 157 |
| muse-spark-1.3 low | 57 | 2.61 s | 6.40 s | 0 | 1,065,160 | 114, 126 and 157 |
| muse-wonder-1.0 low | 58 | 3.36 s | 7.88 s | 0 | 1,044,788 | 114 and 157 |
| muse-glimmer-30b local | 54 | 149.2 s | 656.0 s | 0 | 118,497 | 102, 114, 126, 137, 145 and 154 |

The local arm's latency can include queueing behind other work on the same model server. It ran on an earlier tree of this ticket; the frozen prompt and the runner are byte-identical since, and the only change on its call path is one added attribute. It takes about three hours, so I didn't run it again.

On spark minimal, per language: English 29 of 30, Spanish 14 of 15, mixed 15 of 15; with transcription noise 36 of 36. Every trap class 3 of 3 except `scope_word` 1 of 3. Case 114, "Take the paper out for now. We'll see, I might bring it back.", accepts only skip until open. Spark minimal and Wonder low compiled skip until the slot; spark low and the local arm abstained with a question. Case 157, "Deja el borrador hasta el lunes." on a Sunday, accepts defer tomorrow or skip today; the three Muse arms compiled skip this_week, which under the fold returns Monday 00:00, the same instant as the accepted answers. The headline stays as scored, and the prompt didn't change because of this.

The numbers move a little between passes, so here are the others from the same night, same frozen prompt, on older builds of the client: spark minimal 58 and 58, spark low 58 and 58, Wonder low 58 and 56. One more Wonder low pass hit 19 transport errors and scored 40, with 41 answered and 40 of those right; I re-ran it because of those errors, see below. The files of the last rebase's pass, that one included, are in `evals/r9_results/earlier/`, so nobody has to take my word for it. `seconds` isn't touched, but in `evals/r9_results/muse-muse-spark-1.3-minimal.json` I rounded each row's `latency_s` to three decimals, because one long float happened to hold a digit run my repo hygiene scan flags. The summary and every answer are unchanged.

## Live end to end

On the model host, on a loopback fake of the Bot API, with real `muse voice transcribe`, real compile and real Wonder, made-up clips and commitments, Ticket 9's made-up table with that probe's model output replayed (ten facts, 36 metrics), slot today 15:30.

| Scene | What it heard | Outcome | Total | Steps worth naming |
|---|---|---|---|---|
| Skip, reply to the first card | "Don't drop the write up. I just can't do it today." | `applied_card` | 19.4 s | transcribe 2.14, compile 3.95, repropose 12.90, send_card 0.09; the negation holds and the offer changes |
| Fact correction, reply to the original card, chain walked to the newest | "That's wrong. I wasn't programming less..." | `fact_disputed_card` | 15.9 s | transcribe 2.88, compile 2.59, repropose 9.89; real proposal |
| The real `poll --voice` loop with its worker thread, same skip clip | same skip clip | `applied_card` | 16.4 s | a tap sent while the worker was busy was answered in 0.094 s with the row still `working`; SIGINT stopped loop and thread, rc 0 |
| Keep, misheard | "keep the right up I changed my mind" | `question` | 5.9 s | nothing changed |
| Spanish, misheard | "Hinoquedo con la Yamada familiar, de para mañana." | `applied_card_stands` | 4.2 s | compiled defer s1 tomorrow; that side was already gone |
| Abstention | "Move that one to later. I'm not sure which one." | `question` | 4.8 s | nothing changed |
| Silence | no words | `silence` | 1.3 s | no state change |
| Unreadable clip | undecodable bytes | `unreadable` | 0.16 s | no state change |
| Blocked by a made-up deny term | blocked text | `outbound_blocked` | 2.1 s | no transcript stored, no echo |
| A card whose hour is over | skip clip | `hour_passed` | 4.7 s | no Wonder call |
| Both tries of the reply failing after the corrected card went out | skip clip | `reply_failed` | 17.0 s | no second card |
| The fourth corrected card on one slot | skip clip | `card_limit` | 7.1 s | no Wonder call |
| Kill switch | skip clip | waits, then `question` | 3.8 s once off | waits with no send, no attempt, no event; once off, `question` |
| Mode not confirmed | skip clip | waits, then `question` | 66.6 s, 62 of them the wait | waits, told once; once fixed, `question` |
| No model | skip clip | `pending`, then `question` | 37.2 s, 32 of them the wait | no event while waiting; once back, `question` |
| Through Ticket 13's real `run-slot`, code facts only | skip then fact correction | `fact_disputed_card` | 16.3 s | a two-goal card sent to the fake, then a fact correction on it, with the corrected card's `slot_cards` rows saved; a tap on the corrected card, then `run-slot` for 18:00: the tally counts that chain once, the learner saw one ruling, and the card didn't offer the commitment I'd skipped that day |

At the end of the main run: 14 notes, 14 `app.voice_note` events. Leak checks over every table: the fake token in none, transcripts only in `voice_notes`. First corrections that reached Wonder took 15.9 to 19.7 s across these runs, so "about 20 seconds" holds when nothing goes wrong. A draft the gate refuses adds a Wonder call, about 10 s or more, and a stall costs about 67 s; see below. If the seconds on camera are different, the words change, not the number.

## A realistic card

What a fact correction does when a card has several facts, because a world with two facts made it look like every correction ends in "No checked facts". On ten facts and 36 metrics, Wonder's cards cite mostly metrics. In two worlds, one correction left 2 and 0 of the 10 facts, and 16 and 13 of the 36 metrics; Wonder was called and returned real proposals, in 19.2 s and 17.6 s. Second corrections on the same chain took 25.7 s and 31.8 s, the slow ones with a gate retry, third ones 15.6 s and 16.0 s, and a fourth ended `card_limit` or abstained. No corrected card said programming fell. "No checked facts" comes back only when the evidence really runs out, or when the model doesn't answer. The caption usually differs only in its first line, since Wonder tends to re-offer the same commitments and the chart and the since line don't change; what changed is in the cited statements behind Why?.

## Two ways the model call failed

- An instant failure. During the first re-run of Wonder low at 23:11 on Nov 1, 19 calls of `muse exec` died about 0.2 s after starting, in two bursts 10 seconds apart, with 2 good calls between. Muse Code's own per-run logs show each one stopped right after opening its local session, before any model request. I reproduced that failure later on made-up data: when the temp folder above the workspace holds a `.git`, `muse exec` exits 1 in 0.208 s with `runtime host failed to start: TMPDIR ... produced process-lifetime tool-output root ... inside the configured workspace or repository`, and its log ends the same way, 39 events and within one byte of the same size. A stray `/tmp/.git` did appear later that night, from a command run in the wrong folder. That it existed at 23:11 fits but isn't proven. Ticket 13 now keeps Muse Code's temp folder under the home directory, and retries a fast local failure after 5 s and 20 s; the re-proposal uses that same client. `muse voice transcribe` isn't affected: it returned 0 under the same condition. A failed compile or transcribe waits 5 s and tries again. The same two models then ran 600 calls in 30 minutes, and none failed.
- A stall. At 03:02 on Nov 2 two Wonder low calls both stalled after their first event, until the 120 s timeout, and the note got a labelled `(no checked facts)` card after a true 125.8 s. Both requests answered in 7.9 to 12.5 s when I sent them again, so it wasn't the prompt. I don't know the cause. It's the only such event in about 2,400 calls of Muse Code's logs that night. Measured on made-up data with every Wonder call scripted to hang after its first event: a fact correction got its labelled card in 67.0 s, 60.1 of them the re-proposal, and no hung process was left. I take no second attempt after a timeout here, unlike the slot path: my slot has minutes before its card is due and that card is the hour's offer, while a correction has already missed its 20 seconds when a call times out; the correction is stored before the re-proposal starts, and the labelled card still offers my commitments under the new state, only without cited reasons; a second hung attempt would put the reply near 125 s, and the one real stall had two calls hang at once, so nothing shows a retry a minute later goes through; and it would need its own count, like the slot path's `timeout_retries`.

## Review

Each finding as problem, then fix. These are all real and all fixed through Muse sessions:

- The post-check refused every re-proposal that cited a number. Found live, a plain skip ended `reproposal_failed`; fakes cited no numbers, so 53 green tests hid it.
- The next regular card repeated what I rejected. Found live through Ticket 13's real `run-slot`: metric disputes bit only in the same cycle, and Ticket 13 makes a new cycle per slot, so the 18:00 card said "Code fell from 6.75 hours..." right after I'd disputed it on the 15:30 card. They now hold for the rest of that Madrid day at the same value.
- A card whose delivery is unknown could be sent twice if the reply failed too. A Wonder client that couldn't be built looked like success and built a card from old rows. Retried failures went into step seconds as counts. All three were in the first pass at the Ticket 13 seam, found reading the diff.
- A fact correction could bring back the sentence I rejected. Found live on a realistic made-up card: Wonder cites mostly metrics, so the dispute left the facts in place, and after "I wasn't programming less" the corrected card's cited statements said "Programming screen time decreased in the last period." Now a fact holding a disputed metric's number or a disputed fact's number goes too.
- A resumed fact correction could say "The card stands" when its own first attempt had written fallback rows and the send had failed.
- A resumed note re-proposed with no private terms, so a side could vanish from a card saying "New card above".
- `hour_passed` and `reproposal_failed` raised into a close with no arm for them, so they retried and spent Wonder calls.
- The kill switch spun in a tight loop. A store error could kill the worker thread. `worker_error` never sent the waiting reply. `applied_at` was written and never used. A resumed fact correction disputed rows nobody saw. The resume path checked `none` before the validation codes. Offers carried the card's slot, not the side's start. `show-chain` ignored the event. A test deleted modules from `sys.modules` and broke later files.
- R9 hid transport failures as wrong answers, and refused the real file because its case ids are integers, which a synthetic fixture couldn't show. A test could only pass with the file absent.
- `transcribe.py` built the key's name at runtime to dodge my own grep; it's a plain pop now.
- Ten tests couldn't fail or left a branch uncovered, found by reading the diffs and by mutation. By the end, 123 mutations applied by hand on a scratch copy, 122 caught; the survivor, `U19c`, is equivalent, since the check refuses unless the variable is already `0`.
- The raising-handler finding came from a review by GPT Sol 6.1, run through Codex.

## Acceptance tests

Claude Code ran AT1 to AT14 and AT16 on this code before this docs pass: 77, 50, 59, 24, 14, 64, 118, 13, 8, 33, 18, 37 and 32 tests passing, with one skip until the set is in the tree; AT13's two refusals and AT14's greps as the plan says; AT16 the package absent on the base. `make check` on the same tree: 2832 passed, 2 skipped, ruff, format and pyright clean, gitleaks no leaks. This pass added only docs, the frozen set and the result files, and raised the line limit in `test_privacy_note_states_five_claims` from 30 to 45, because `docs/PRIVACY.md` gained the five voice paragraphs. Ticket 13b merged after these runs; the rebase over it conflicted only in `README.md`; the voice path and R9's runner are unchanged by it; this pass pinned that the re-proposal's client isn't wrapped for a timeout retry, and corrected the README counts this ticket changed. Ticket 22 merged after that. The rebase over it changed docs, including the last sentences of `docs/MODELS.md`, which said voice correction wasn't on main, and one fake in `tests/test_provenance_export.py`, whose `send_photo` lacked the silent flag this ticket added.

## Known gaps

- `results_for_slot` returns the latest stored row per profile, so after a re-proposal that sent no card (`reproposal_failed`, `hour_passed`), a later note's prompt and disputes read rows that never reached my screen.
- Small numbers coincide, so a dispute can drop many facts from one cycle: on the realistic card, 2 and 0 of 10 facts and 16 and 13 of 36 metrics stayed after one correction. That's the accepted cost. A corrected card usually differs in its first line and its cited statements, since Wonder tends to re-offer the same commitments and the chart doesn't change.
- The gate refusing a draft adds a Wonder call: second corrections on one chain took 25.7 s and 31.8 s, against 15.9 to 19.7 s for first ones.
- A disputed metric bites for its own cycle and for any cycle on the same Madrid day, at the same value. The next day the same number can come back, and I accept that: the windows have moved, and it's a coincidence as often as not.
- A tap on a corrected card counts as that slot's ruling, once per chain. The learner's pick log then shows the policy's original pick against the corrected offer, because a correction doesn't change what the policy said at that slot.
- `MUSE_CONTRIBUTOR_MODE` changes nothing I can observe on `muse voice transcribe`: the same handshake and frame keys at unset, `0` and `1`. The checks prove what my side says, not how the service treats that call.
- Everything above ran against a loopback fake of the Bot API with made-up clips. The real Telegram file path and a real voice note wait for the phone test.
- Ticket 22's provenance export takes the newest proposal row per slot and profile, and a re-proposal writes a newer one, so after a corrected card the slot's line shows the original card's sides with the re-proposal's counts. I ran the export on a made-up database after a fact correction: the 15:30 line showed effort low and no cited facts on both sides, from the corrected card's calls, while the card that went out at 15:30 cited one fact per side at effort high.
