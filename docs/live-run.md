# Live run: the numbers at the cut

These numbers update at the numbers cut, Nov 4 at 18:30 Madrid; until then they stand as of the time below.

The run had 13 registered card slots, Nov 2 13:30 to Nov 4 18:00 Madrid, and the numbers are cut at Nov 4 18:30 (PREREG, Design). Every number on this page comes from the committed command `make metrics` (`python -m framework.metrics report`, run read-only on a copy of my store) and names its key. The exceptions are the last two lines, which that report doesn't compute; they name their own source.

As of `scope.as_of`: Nov 4 02:41 Madrid, with 10 of the 13 slot times passed.

## Scope

- Registered run slots: 13 (`run.slots`).
- Outside them, 1 card went out: the Nov 3 11:30 card (`scope.slots_outside_run` 1, `delivered.cards_outside_run` 1). PREREG item 18 says it isn't one of the 13 registered slots, so no number on this page counts it; it has its own line below.
- Forced or unpinned slots: 0 (`scope.slots_forced`, `scope.slots_unpinned`).

## Cards that reached my phone

- 13 delivered cards in the run (`delivered.cards`), 3 of them voice-corrected cards (`scope.voice_corrected_cards`).
- They carried 22 options (`delivered.sides`): 22 proposals (`delivered.sides_proposal`) and 0 labelled fallbacks (`delivered.sides_fallback`).

## R1: first drafts against the gate

| Path | Model, effort | First drafts | Passed | Failed | Unavailable | Retries | Retry passed | Fallbacks | Noops |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Scheduled slot (`r1.slot`) | muse-wonder-1.0, high | 16 | 16 | 0 | 0 | 0 | 0 | 0 | 0 |
| Voice re-proposal (`r1.reproposal`) | muse-wonder-1.0, low | 3 | 2 | 1 | 0 | 1 | 1 | 0 | 0 |

Keys: `r1.slot.muse-wonder-1.0.high.*`, `r1.reproposal.muse-wonder-1.0.low.*` (first_drafts, first_passed, first_failed, unavailable, retries, retry_passed, fallbacks, noops).

- 1 of 19 first drafts failed the gate (5%; PREREG's drafted target was 0-20%). It failed with L1B_CLAIM_WITHOUT_EVIDENCE (`r1.reproposal.code.muse-wonder-1.0.low.L1B_CLAIM_WITHOUT_EVIDENCE` 1), and its retry passed (`retry.passed` 1). It was a re-draft for a voice-corrected card, not a scheduled card's first draft.
- No fallback or noop happened without a first attempt (`fallbacks.without_attempt1` 0, `noops.without_attempt1` 0).
- PREREG item 12 asks for R1 in two parts, before and after the gate change. The report pools them. Split by a private read-only script over my store (not in this repo): 10 first drafts on Nov 2's gate, 0 failed; 9 on the fixed gate, live since Nov 3 01:27, 1 failed.
- R1's outside-rater labels aren't in this report.

## R7: did I do what I accepted?

PREREG counts this descriptively: n per evidence class, unknowns counted, no causal claim. A tap means accepted.

| Evidence class | Accepted | Completed | Not completed | Unknown |
| --- | --- | --- | --- | --- |
| github_push (`r7.github_push.*`) | 2 | 0 | 2 | 0 |
| no_screen (`r7.no_screen.*`) | 4 | 0 | 4 | 0 |
| tap (`r7.tap.*`) | 2 | reported as accepted only | | |
| calendar_tag (`r7.calendar_tag.*`) | 0 | 0 | 0 | 0 |

- github_push: neither of the 2 reads "consistent with completion". There was no push to one of my other public repos in the picked hour or the 2 hours after it.
- no_screen: none of the 4 reads "no activity recorded on observed devices (iphone, mac)". Each picked hour had screen minutes recorded, and none of them were system-only minutes (`r7.no_screen.system_only_hours` 0).
- tap: nothing independent exists, so the 2 count as accepted only.
- Every accepted card had a known hour and commitment (`r7.accepted_hour_unknown` 0, `r7.accepted_commitment_unknown` 0).

So far the independent evidence shows none of the 6 checkable commitments I accepted as completed.

## R8: did the learner predict my taps?

Each prediction was scored before the learner updated on it. Over 5 predictions (`r8.scores.n`), its mean Brier was 0.261 (`r8.scores.learner.brier`), worse than both baselines: always-half 0.250 (`r8.scores.always_half.brier`) and the pooled rate 0.235 (`r8.scores.pooled_rate.brier`). Lower is better. Log loss, which is secondary, says the same: 0.717 against 0.693 and 0.680 (`r8.scores.learner.log_loss`, `r8.scores.always_half.log_loss`, `r8.scores.pooled_rate.log_loss`).

| Slot | My forecast, Builder | What I tapped |
| --- | --- | --- |
| 15:30 | 8 of 10 (`r8.forecast.15:30.builder`, `.n`) | 1 of 2 Builder, 1 Disconnect (`r8.actual.15:30.*`) |
| 20:30 | 5 of 10 | 0 of 2 Builder, 2 Disconnect |
| 22:30 | 0 of 10 | 0 of 1 Builder, 1 Disconnect, and 1 tap for neither |

- Policy diff from Day 0 to now, as changed fields (`r8.policy_diff.*`): preference 0, rulings_seen 1, buckets 11, commitments 35, cards 11, duplicates 0, score_log 0, pick_log 0. PREREG calls same-data replay adaptation, never better prediction.
- Bookkeeping: 2 rulings skipped (`r8.learner_rulings_skipped`), 1 tap pending (`r8.learner_state_pending_taps`), no state mismatch (`r8.learner_state_mismatch` 0).

## Outside the run

The Nov 3 11:30 Builder card went out on time and its one first draft passed the gate (from a private read-only script over my store, not in this repo; the report counts it only as `delivered.cards_outside_run` 1). Its settled recount: PRs incomplete (the card stated no PR figure), pushes differed.

## Two lines the committed report doesn't compute

- On time, from a private read-only script over my store (not in this repo), which reads each card's Telegram send time: Telegram accepted all 10 scheduled run cards within 300 s of their slot; the slowest took 2 s.
- GitHub recount, from the same private script, reading the settled recounts made by the committed `source_audit/` code; a recount settles 6 hours after its slot: PRs 6 matched, 0 differed, 1 not settled yet, 3 incomplete (Nov 3 15:30, 18:00, 20:30: CARD_NONE_FOUND, the card stated no PR figure); pushes 0 matched, 7 differed (GitHub's event feed adds push rows hours after the push; see TRUST.md), 1 not settled yet, 2 incomplete (Nov 2 13:30, 15:30: NO_INDEPENDENT_SOURCE, they agreed with GitHub's event feed, the only source for pushes). A pushes recount can't reach matched, because pushes have no source outside GitHub's feed.

## Regenerate

`make metrics` from a clone at main, then the private script for the two lines above; the exact commands are kept with the private run notes.
