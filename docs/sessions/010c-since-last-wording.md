# Session evidence - 010c-since-last-wording (2026-11-02)

## What changed

The 15:30 card on Nov 2 carried this Builder `since_last` sentence: "Prs rose by 3 in the last period." It cited the `period.last.prs` delta of 3, 24 on the previous card and 27 on this one. In this system's vocabulary "in the last period" places the change inside the last period, where pull requests went from 2 in the prior period to 27, so the sentence reads as false. The gate passed it.

The fix adds one claim-only code, `L1B_SINCE_LAST_WORDING`, for a closed list of containment patterns in a `since_last` claim with metric refs. The Wonder prompt teaches the replacement in the same change with two lines: write the change as since the last card, as in "Prs rose by 3 since the last card.", and for earlier- and prior-period deltas put the period word before the label, as in "Earlier pushes rose by 1 since the last card." The all-zero branch no longer opens with "Nothing changed since the last card". Pre-existing fixtures that used the rejected wording were reworded to the taught phrase, with no expected outcome changed, and M119 pins the real sentence. I point to the plan for the decisions behind each of these: [docs/plans/010c-since-last-wording.md](../plans/010c-since-last-wording.md).

## Replay

Every stored `since_last` claim, claim by claim, through three gates: the live gate at 1ea3b86, main at 3c680e2, and this branch.

Real store, counts only: 4 delivered cards, 3 `since_last` claims. The 15:30 sentence passes at 1ea3b86 and at 3c680e2, and this branch rejects it with `L1B_SINCE_LAST_WORDING` alone. The 2 claims from the 18:00 card pass on all three gates. Its 4 proposal attempts are all first attempts with no gate codes, so no real draft failed outside this replay.

R1b's stored drafts, every attempt: 515 `since_last` claims. Product arm, 129 claims: 128 pass on main, 5 here; 123 newly fail, each with the new code and an in-period phrase; none newly pass. Plain arm, 386 claims: 280 pass on main, 89 here; 195 newly fail, all with the new code; 4 newly pass, all saying "since the previous card", which now names the last period, and each of the 4 is true against its delta; 57 that already failed also get the new code.

Re-gated at draft level, R1b's 432 counted first drafts go from 2 to 105 failing of 216 in the product arm, every new failure with the new code alone, and from 198 to 201 of 216 in the plain arm. Those stored drafts come from the earlier prompt, which taught "in the last period" for every period metric, so this measures the stored drafts, not the new prompt. R1b's numbers stay labelled with the earlier gate under PREREG 12, and only a fresh R1b run with the new prompt would measure R1b on this gate.

Ticket 11's harness drafts: 112 `since_last` claims. 0 blocked at 1ea3b86, 3 at 3c680e2, 59 here: 56 with the new code and the same 3 with `L1B_NEGATED_CLAIM`.

The briefing cases: 22 `since_last` claims with the same verdicts on main and here; M119 adds 3, and its third is the 15:30 sentence.

## What it rejects that is true

One shape: a period phrase on the label together with an accepted phrase, as in "Pushes in the last period increased by 1 since the last card." It reads as true, and it is rejected because the claim holds a period phrase. Counts: 0 of 129 R1b product-arm `since_last` claims, 0 of 112 Ticket 11 harness claims, 0 of 11 in today's Wonder check, and 186 of 386 in R1b's plain arm, whose numbers stay labelled with the earlier gate under PREREG 12. I kept it as a disclosed limit after review, because the taught prompt doesn't write this shape and the smaller rule is easier to defend mid-run.

## The all-zero opener, apart from the wording rule

Main at 3c680e2 rejects a `since_last` claim opening "Nothing changed since the last card" as `L1B_NEGATED_CLAIM`. 3 of the 112 Ticket 11 harness claims carry it; R1b's drafts and the real store hold none. The live gate at 1ea3b86 passed those 3, and it also passed the same opener in front of a change that wasn't 0, which is false. The gate stays as it is. The prompt's all-zero branch no longer opens with that sentence.

## Wonder check

10 calls on made-up data: muse-wonder-1.0 at high, the model and effort the live cards use, through the product path with this branch's prompt and gate. Cases: R1b's first 8 cases with a parent (r1b-001 to r1b-015, odd ids) and 2 all-zero copies of r1b-001 and r1b-003 whose parent equals the current values. Results: 10 of 10 drafts passed at the first attempt and all 10 carry `since_last`; 11 of 11 `since_last` claims pass; all 11 say "since the last card"; 0 carry a period phrase or a negator; both all-zero cases wrote "changed by 0 since the last card". The same 8 cases' stored R1b drafts from the earlier prompt: 7 of 8 `since_last` claims used the in-period phrase. It ran between 16:53 and 16:55 on Nov 2 from the working tree, and the files under framework/briefing/ and framework/proposal/prompt.py were checked unchanged after the last session that touched the tree.

## How it was measured

Claude Code's scripts, outside this repository: R1b through this repository's own propose path with a replay client, the way `--regate` does, but for every stored attempt; each Ticket 11 claim alone in a host briefing; real cards claim by claim, with an approximate context for actions and windows; the real store by counts only.

## What isn't verified

10 calls is a small check: one execution per case, one model. No live card has used the change yet. R1b and mutation testing weren't re-run on the new rule. Pre-existing limits found in review, unchanged by this ticket and also on main: a direction word outside the up and down lists isn't checked against the delta in `since_last`, so "Prs softened since the last card." passes on a rise of 3; a delta written as a value passes, as in "Prs were 3 since the last card."; containment words outside the pinned list, such as through, within and between, pass.

## Who wrote what

Muse Code wrote the plan (muse-wonder-1.0 at high) and the code, tests and docs (muse-spark-1.3 at medium) in headless sessions Claude Code started; one implementation session stopped on a conflict between the plan and the fixtures and was resumed with rulings. Claude Code wrote the prompts in prose, including the example sentences the Wonder prompt teaches, made the rulings the plan records, and ran the replays and the Wonder check from outside this repository. It created the branch and typed nothing in this repository.

## Addendum measured after merge, Nov 2, 23:17 to 23:21: R1b product arm on the live configuration

Why I ran it: the go/no-go input for putting this ticket's change live at the 10:35 slot on Nov 3. I set the rule before the run: at most 5% of first drafts fail the gate, and no case ends in a fallback. A model timeout or unavailable counts as transport, is rerun once and is reported apart.

What ran: R1b's product arm only, muse-wonder-1.0 at high, the model and effort the live cards use, all 54 cases, one execution each, through the product path (the Wonder prompt, the gate, one retry), with `evals.r1b`, memory-capped, at 3e31338, the commit tonight's rehearsal used, on a clean tree.

Identities from evals/gate_identity.py at 3e31338: HEAD 3e31338bf1ede702d82d94aa4dd1ec0851ef557b; gate commit 41b686d4dece49cd5e21de297ecffda6784c6322 and gate hash 2f443fbbc8ddfc4f0b2957a25541b20e09d276d4fe5680d8609f4530eb525909; prompt b42e301f613ad5dc79f77bb0c3bf7b5b1697419b1326d889e9c1ff48a3b0deec; closure 907b228d92cd991b49915aca610de560135ec34467b2a152e29e3966c956ec07 over 47 files. The same gate, prompt and closure hold at 79b4aa8, the main this addendum lands on.

Results: 56 rows; no transport events, so no case was rerun. 2 of 54 first drafts failed the gate (3.7%), both advice-trap cases, both on the first overall_state claim, both recovered by the one retry: r1b-015 with `L1_ADVICE` on "Pushes were 0 in the last period, so this hour goes to shipping the overdue export.", and r1b-042 with `L1B_COMPARISON_WORD_UNKNOWN` on "Outdoors was lower at 0 hours in the last period than 3 hours in the earlier period, so this hour goes to time outdoors." No case ended in a fallback. The rule is met.

since_last: all 27 cases with a parent wrote since_last in the first draft: 29 claims, all 29 pass, all say "since the last card", and none carries a period phrase or a negator. The one retry that carried since_last passes too.

Where it lives: the rows file at evals/results/r1b/muse-wonder-1.0__high__product__2f443fbbc8dd__prompt-b42e301f613a__closure-907b228d92cd.jsonl, and the new docs/r1b.md section for gate 2f443fbbc8dd; the sections already there are unchanged.

The identity gap, said plainly: R1b's own gate identity, which names its results files and labels the sections of docs/r1b.md, hashes 8 files and has not covered claim_text.py, quantities.py, normalize.py or framework/proposal/prompt.py. That is why this rows file's name adds the prompt and closure hashes by hand. Widening R1b's identity is a follow-up ticket.

What it does not show: made-up cases, one execution per case, one model. It says nothing about any real card.
