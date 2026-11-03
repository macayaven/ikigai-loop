# Trust: misses, limits and blind tests

It checks numbers, sources and wording against my records. It doesn't check that a sentence is true.

Counts come from my store, which is not public.

## Misses that reached my phone

7 cards were delivered on Nov 2: 5 scheduled (13:30, 15:30, 18:00, 20:30, 22:30), 2 voice-corrected (20:30, 22:30). They carried 36 reason sentences, the ones the Why? reply shows, at most three per option.

On 4 of those cards, 6 sentences described a change since the last card as if it happened inside a period.

The Wonder model wrote the sentences. The numbers were right; the wording placed them in the wrong window. The live gate at the time passed all six (gate `42b57031c11b`; the full hash is in [`docs/r3.md`](r3.md)).

| Card | Sentence | What the number really was | Case | Gate at HEAD |
| --- | --- | --- | --- | --- |
| 15:30 | "Prs rose by 3 in the last period." | 24 → 27 since 13:30 (same card: 27 against 2 for the period) | `M119-since-last-period-phrase` | stopped: L1B_SINCE_LAST_WORDING |
| 20:30 corrected | "Pushes rose 1 in the last period." | 0 → 1 since 18:00 | `T24-2030-corrected-builder-period-last-pushes` | stopped: L1B_SINCE_LAST_WORDING |

On the 22:30 card and its corrected card, four more sentences about my screen hours made the same mistake. My screen numbers stay out of this repository; their cases use made-up values.

PR `#43` added `L1B_SINCE_LAST_WORDING` and taught the prompt to write "since the last card". The rule went live on Nov 2 at 23:29 on commit `3e31338` (gate `2f443fbbc8dd`, prompt `b42e301f613a`). I rehearsed on a copy of my data and ran a go/no-go on 54 synthetic cases: 2 first drafts failed the gate and both passed on the retry; no card fell back; all 29 since-last claims said "since the last card". PR `#52` published them in [`docs/sessions/010c-since-last-wording.md`](sessions/010c-since-last-wording.md)'s addendum. The fixed gate went live on Nov 3 at 01:27 on commit `9825342` (gate `0b84319e4bd9`, prompt `b42e301f613a` unchanged, closure `6e4f699a1b3d`), before any card used the 23:29 gate. The Nov 3 11:30 card was the first real card on the new rule and the fixed gate: it went out on time, and its first draft passed the gate with no codes.

Late pushes: GitHub's feed reached my records after some cards were built. The settled recounts show it in three slots: the 18:00 chart gave 8 pushes and PRs for the prior period against a settled 10, the 20:30 charts 14 against 16, the 22:30 charts 17 against 20, and the 22:30 since line said 2 where the settled count is 3. Every sentence about pull requests matched. The gate checks the records at card time, so it couldn't see this; the source audit did, six hours later.

## Misses caught before any card

A code fact counted 16 pull requests where the repo held 8; each leaves two rows. I fixed the rule before the run ([`docs/sessions/009d-pr-count.md`](sessions/009d-pr-count.md)).

The first card's since line would have said 32 where the plain count was 17. The source audit caught it; Ticket 13 fixed it before merging ([`docs/sessions/020-source-audit.md`](sessions/020-source-audit.md)).

The gate that went live at 23:29 on Nov 2 stopped some ordinary sentences as private terms. A rehearsal on the product path with the real private-term list found it before any live card used that gate: the Nov 3 11:30 slot fell back 5 of 5 on that gate and 0 of 5 on the fixed gate, reading only error codes on a copy of the live store. It failed closed with a fallback card. Fixed in PR `#58`, merged on Nov 3, live since 01:27, before any card used the 23:29 gate.

## Mistakes in my own tools

The source audit marked the 20:30 card FAIL with correct numbers, reading one card's sentences against the other card's briefing after a voice correction left two cards; the fix is PR #54, merged on Nov 3.

Taps on voice-corrected cards never reached the learner, because those rows weren't saved: fixed in PR #53, on the live cards since Nov 3 at 01:27; at 01:28 the backfill wrote the 4 missing rows for the two voice-corrected cards, and a second run wrote 0; so their taps count from the 11:30 slot on.

Not fixed: the public provenance export (`framework/provenance/export.py`) keeps only the latest draft result per option of a slot, so after a voice correction a line can pair the scheduled option with the re-draft's attempts. Every draft so far passed first time, so no published count changes.

## What it still doesn't check

The gate leaves three since-last gaps open ([`docs/sessions/010c-since-last-wording.md`](sessions/010c-since-last-wording.md), "What isn't verified"): direction words outside the up/down lists stay unchecked; deltas written as values pass; containment words outside the list (through, within, between) pass.

A sentence that cites a fact and says the opposite of it passes: neither the gate nor the public checker reads what a fact says, only that it exists. Claude Code confirmed this with made-up facts on gate 2f443fbbc8dd and again on the fixed gate 0b84319e4bd9, and the checker's blind set found three false passes.

Two [`docs/r2.md`](r2.md) findings stay open: a word from a calendar category field or a GitHub push counts key can reach a card through a misbehaving local model.

The new rule stops one true shape: a period phrase on the label with an accepted phrase ([`docs/sessions/010c-since-last-wording.md`](sessions/010c-since-last-wording.md), "What it rejects that is true").

The store holds a few days of data about one person; when the source is wrong, a matching sentence passes.

The public checker stops true sentences: in one probe of 19 true sentences from PR `#51`'s session note, written the way a stranger might write them, it stopped 4. [`docs/sessions/023-checker-hardening.md`](sessions/023-checker-hardening.md) quotes all four.

The source audit recounts only GitHub numbers: pull requests against an independent source and pushes only from GitHub's own event feed, and it doesn't audit screen or calendar numbers, delta claims or direction words ([`docs/sessions/020-source-audit.md`](sessions/020-source-audit.md), "Limits"). Settled recounts say: for the 13:30 and 15:30 cards, pull requests PASS, pushes INCOMPLETE and pushes plus PRs INCOMPLETE; for the 18:00, 20:30 and 22:30 cards, pull requests PASS, pushes FAIL and pushes plus PRs FAIL.

The unit rule doesn't treat `calendar.busy_hours` as hours, so a false sentence giving busy time in minutes can pass; the gate's blind set found it as G18. The private-term stops (Ticket 10d) get fixed during the run and G18 doesn't, because a product-path rehearsal found those stops, so fixing them doesn't touch the held-out set, while that set found G18, so fixing it would use up that set.

## Blind tests

GPT Sol 6.1 wrote both sets blind from the public docs only; [`evals/heldout/README.md`](../evals/heldout/README.md) covers writing, freezing, scoring.

| Set | Correct | False stopped | True passed |
| --- | --- | --- | --- |
| Gate set, 40 cases (`3e31338`) | 37/40 | 19/20: since-last 4/4, negation 4/4, period 3/3, mislabelled metric 3/3, invented fact 3/3, unit 2/3 | 18/20 |
| Checker set, 40 cases (`1cd8db8`) | 35/40 | 17/20: wrong number 4/4, wrong unit 3/3, wrong period 3/3, mislabelled metric 3/3, missing fact 3/3, negation 1/4 | 18/20 |

Each set was scored once: the gate set at 23:30 on Nov 2 on the gate live at the time (commit `3e31338`) and the checker set on commit `1cd8db8`, the first main with C1; PR #55 and PR #56 hold the scoring files and were merged on Nov 3. The gate set has three misses: one false pass (G18), "The calendar shows 6.5 busy minutes.", citing `calendar.busy_hours` at 6.5, which the unit rule doesn't treat as hours; two true sentences stopped (G23 and G25), one for a direction word outside the list, one for a sum no single metric holds.

The checker set has five misses: three false passes citing a fact and saying its opposite. Two true sentences were rejected: H13 ("thirty-two") and H23 ("weekly").

No verdict in either blind set involved the private-term rule, and Ticket 10d only narrows that rule, so both blind scores hold for the fixed gate.

## Replay

The command `uv run python -m evals.replay_sentence` replays sentences at HEAD; no argument replays the 15:30 sentence. It swaps the sentence into the 15:30 claim, keeping its cited change and values inside a made-up briefing; it doesn't rebuild a delivered card.

| Sentence | Result | What it shows |
| --- | --- | --- |
| "Prs rose by 3 in the last period." | stopped: L1B_SINCE_LAST_WORDING | 15:30 sentence; false here |
| "Prs rose by 3 since the last card." | passed | Taught wording; true |
| "Prs softened since the last card." | passed | Direction gap; false on a rise of 3 |
| "Prs were 3 since the last card." | passed | Value gap; ambiguous, not false |
| "Prs rose by 3 through the last period." | passed | Containment gap; repeats 15:30 |
| "Prs in the last period increased by 3 since the last card." | stopped: L1B_SINCE_LAST_WORDING | True but stopped |

I check this page with [tests/test_trust_page.py](../tests/test_trust_page.py) and run `uv run pytest tests/test_trust_page.py -q`. That test checks the phone table against the cases and the gate at HEAD, the counts sentence, the scheduled count, the replay results, and that every cited file exists; for PRs it checks that a cited PR number matches a merged commit on main, or is one of the open PRs the test names; it doesn't check the store's totals, the blind scores, or the live-move facts.
