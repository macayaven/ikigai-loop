# Session evidence — 010b-redteam (2026-11-02)

## Red-team summary

| file | sentences | frozen blocked | current blocked |
|---|---|---|---|
| round-1.json | 34 | 0 | 32 |
| round-2.json | 32 | 0 | 32 |
| true-sentences-spark-rules.json | 30 | 4 | 4 |
| true-sentences-wonder-norules.json | 30 | 9 | 10 |
| true-sentences-wonder-rules.json | 30 | 0 | 0 |

Total sentences: 156, blocked on frozen: 13, blocked on current: 78.

### Round 1

Through on frozen: 34 (by verdict: {"disclosed_limit": 1, "not_false": 1, "real_hole": 32}; by target: {"A": 2, "B": 4, "C": 6, "D": 5, "E": 4, "F": 13}).
Predicted/actual agreement: 34/34.
Through on fixed gate: 2; fixed: 32.

Found in review (kept apart from attacker totals):

| id | verdict | passed | codes |
|---|---|---|---|
| R1 | real_hole | False | ["L1B_NUMBER_WITHOUT_METRIC_REF"] |
| R2 | over_block | True | [] |
| R3 | real_hole | False | ["L1B_VALUE_PERIOD_MISMATCH"] |
| R4 | over_block | True | [] |
| R5 | over_block | True | [] |
| R6 | over_block | True | [] |
| R7 | over_block | True | [] |
| R8 | real_hole | False | ["L1B_VALUE_PERIOD_MISMATCH"] |
| R9 | real_hole | False | ["L1B_VALUE_PERIOD_MISMATCH"] |
| R10 | real_hole | False | ["L1B_UNIT_MISMATCH"] |
| R11 | real_hole | False | ["L1B_UNIT_MISMATCH"] |
| R12 | real_hole | False | ["L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"] |
| R13 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R14 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R15 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R16 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R17 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R18 | real_hole | False | ["L1B_NEGATED_CLAIM", "L1B_NUMBER_WITHOUT_METRIC_REF"] |
| R19 | real_hole | False | ["L1B_DIRECTION_MISMATCH"] |
| R20 | real_hole | False | ["L1B_DIRECTION_MISMATCH"] |
| R21 | real_hole | False | ["L1B_PERIOD_WORD_MISSING"] |
| R22 | real_hole | False | ["L1_UNSAFE_TEXT"] |
| R23 | real_hole | False | ["L1_PRIVATE_TERM"] |
| R24 | real_hole | False | ["L1_RAW_VALUE"] |
| R25 | real_hole | False | ["L1_ADVICE"] |
| R26 | real_hole | False | ["L1_ADVICE"] |
| R27 | real_hole | False | ["L1_ADVICE"] |
| R28 | real_hole | False | ["L1_ADVICE"] |
| R29 | real_hole | False | ["L1B_UNIT_MISMATCH"] |
| R30 | real_hole | False | ["L1B_METRIC_LABEL_UNKNOWN"] |
| R31 | over_block | True | [] |
| R32 | real_hole | False | ["L1B_METRIC_VALUE_MISMATCH"] |
| R33 | real_hole | False | ["L1_ADVICE"] |
| R34 | real_hole | False | ["L1_ADVICE"] |
| R35 | real_hole | False | ["L1_ADVICE"] |
| R36 | real_hole | False | ["L1B_METRIC_LABEL_MISMATCH"] |
| R37 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R38 | real_hole | False | ["L1B_NUMBER_WITHOUT_METRIC_REF"] |
| R39 | real_hole | False | ["L1_PRIVATE_TERM"] |

### Round 2

Through on frozen: 32 (by verdict: {"real_hole": 32}; by target: {"A": 3, "B": 6, "C": 4, "D": 4, "E": 5, "F": 10}).
Predicted/actual agreement: 32/32.
Through on fixed gate: 0; fixed: 32.

Found in review (kept apart from attacker totals):

| id | verdict | passed | codes |
|---|---|---|---|
| R40 | over_block | True | [] |
| R41 | real_hole | False | ["L1B_DIRECTION_MISMATCH"] |
| R42 | over_block | True | [] |
| R43 | over_block | True | [] |
| R44 | real_hole | False | ["L1_UNSAFE_TEXT"] |
| R45 | not_false | False | ["L1_UNSAFE_TEXT"] |
| R46 | real_hole | False | ["L1_CLAIM_LANGUAGE"] |
| R47 | real_hole | False | ["L1B_DIRECTION_MISMATCH", "L1B_METRIC_LABEL_MISMATCH"] |
| R48 | real_hole | False | ["L1B_UNIT_MISMATCH"] |
| R49 | real_hole | False | ["L1B_UNIT_MISMATCH"] |
| R50 | real_hole | False | ["L1B_NEGATED_CLAIM"] |
| R51 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R52 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |
| R53 | real_hole | False | ["L1B_NUMBER_WITHOUT_METRIC_REF"] |
| R54 | real_hole | False | ["L1B_UNVERIFIABLE_QUANTITY"] |

round-1.json newly blocked: ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10", "A11", "A12", "A13", "A14", "A15", "A16", "A17", "A18", "A19", "A21", "A22", "A23", "A24", "A26", "A27", "A28", "A29", "A30", "A31", "A32", "A33", "A34"] by code {"L1B_COMPARISON_WORD_UNKNOWN": 2, "L1B_DIRECTION_MISMATCH": 2, "L1B_METRIC_LABEL_MISMATCH": 1, "L1B_NEGATED_CLAIM": 2, "L1B_NUMBER_WITHOUT_METRIC_REF": 3, "L1B_PERIOD_WORD_MISSING": 1, "L1B_UNIT_MISMATCH": 1, "L1B_UNVERIFIABLE_QUANTITY": 12, "L1B_VALUE_PERIOD_MISMATCH": 1, "L1_ADVICE": 3, "L1_CLAIM_LANGUAGE": 4, "L1_PRIVATE_TERM": 4, "L1_RAW_VALUE": 1, "L1_UNSAFE_TEXT": 1}; raised: {"current": [], "frozen": []}.
round-2.json newly blocked: ["N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09", "N10", "N11", "N12", "N13", "N14", "N15", "N16", "N17", "N18", "N19", "N20", "N21", "N22", "N23", "N24", "N25", "N26", "N27", "N28", "N29", "N30", "N31", "N32"] by code {"L1B_DIRECTION_MISMATCH": 2, "L1B_METRIC_LABEL_MISMATCH": 1, "L1B_NEGATED_CLAIM": 1, "L1B_NUMBER_WITHOUT_METRIC_REF": 1, "L1B_PERIOD_WORD_MISSING": 1, "L1B_UNIT_MISMATCH": 3, "L1B_UNVERIFIABLE_QUANTITY": 10, "L1B_VALUE_PERIOD_MISMATCH": 4, "L1_ADVICE": 4, "L1_CLAIM_LANGUAGE": 2, "L1_PRIVATE_TERM": 2, "L1_RAW_VALUE": 1, "L1_UNSAFE_TEXT": 1}; raised: {"current": [], "frozen": []}.
true-sentences-spark-rules.json newly blocked: [] by code {}; raised: {"current": [], "frozen": []}.
true-sentences-wonder-norules.json newly blocked: ["S16"] by code {"L1B_NEGATED_CLAIM": 1}; raised: {"current": [], "frozen": []}.
true-sentences-wonder-rules.json newly blocked: [] by code {}; raised: {"current": [], "frozen": []}.

## What happened

Claude Code drives my sessions, and it is not supposed to write code here. An earlier draft of this ticket's fixes carried code it wrote: six fix prompts held exact code, about 33 blocks and 586 lines between gate rules and tests by its count, Muse Spark typed them in, and one more prompt told a session to apply its patch. Committed as it stood, that would have made the sentence in CONTRIBUTIONS.md that it wrote no code in this repository false. Nothing was committed or public. The draft was discarded. It sits in an archive outside this repository. The affected files went back to main, and Muse Code rewrote the gate rules and tests from prose rules, in fresh sessions told not to read the old work. What came through a prompt in the rewrite: the behaviour of each rule, attack and row ids, closed word lists in prose, and what was wrong with a result. Claude Code's own hands on the tree, all mechanical: it archived the draft outside this repository, put the affected files back to main's state with git, deleted its own verbatim lines from the plan and two runner tests, fast-forwarded the branch to main twice and re-applied one comment line Muse had written, and wrote R47 to R54 into the adjudication file by hand. It typed no code.

## What stayed and what went

Stayed, because no code from a prompt landed in them: the attack files, the blind sentence files and their frozen results, verbatim; `evals/redteam.py` and `tests/test_redteam.py`, apart from two tests whose rows came from a prompt, which went and were rewritten; `framework/briefing/normalize.py` and its tests; `metric_unit_class` in `labels.py`. Claude Code decided this by comparing every line and quoted sentence in the draft against the text of every prompt it sent, with a script it keeps outside this repository.

Muse's own rows stayed. The attack files are verbatim. The 34 mutants from the plan's attack table, which the Muse Wonder plan session wrote, and the 28 known-good cases from the plan's true sentences were typed again from the plan: 30 of the 34 mutants read the same, 4 were adapted again to the cases file's private term, and every expected code list matches.

Rows that had come from prompts went: 30 mutants and 5 known-good cases, a whole test file of review rows, and rows in the verify and claim-text tests. Muse Code wrote new ones in its own sentences.

The review rows R1 to R54 in the adjudication files are Claude Code's by design, and the runner reads them from there. No test repeats their sentences.

Everything else in the draft went: `claim_text.py`, `quantities.py`, and the changes to `gate.py`, `numbers.py` and `framework/verify/core.py`.

## Rounds

Stage 1 ran the runner on the unfixed gate at the commit in `round-1.frozen.json`. 34 attacks, 34 through, predicted 34 of 34. Verdicts: 32 `real_hole`, A20 `not_false`, A25 `disclosed_limit`. Round 1's slip: A20's `why_false` is wrong, because the 4 it sets against 3 is the three-period total.

Round 2 ran as a fresh session, muse-wonder-1.0 at high effort, with `--output-schema` and `--disable-write`, no part in writing the gate, read-only. 32 attacks, 32 through the draft it attacked, predicted 32 of 32, all ruled `real_hole`. Its slips: N25 says five tokens between the words and it is four, N21 cites a path that does not exist, and N10's stated mechanism misses the real one, the positional-list skip.

## Over-blocking

Measured on this tree from outside the repository, with the scripts and corpora kept there:

- Ticket 9b's code-fact templates: 11,352 rows, 0 blocked.
- Ticket 11's drafts from the taught prompt: 39 drafts, 182 claims, 0 blocked. The same with my real term list and made-up literals: 0. With real label names: 33 drafts, 154 claims, 0 blocked.
- Ticket 11's drafts from the old prompt, before it taught these rules: 72 drafts, 38 blocked, and I keep that as the reason the prompt teaches them.
- Blind fact sets, written by a model: with the rules in its prompt, 0 of 30 fact-only and 0 of 10 metric sentences blocked. With no rules, 30 of 30 and 6 of 10 blocked, on rules that were already there.
- My real commitment titles and real term list against every corpus: 0 false hits, counts only.
- 195,850 made-up sentences through the discarded draft and this gate, side by side, are how I found what the rewrite first missed. The differences that stay are noise, or this gate being stricter on purpose.
- Ticket 16b's 432 stored first drafts re-gated on this gate with no model calls: the product prompt fails 2 of 216 on the earlier gate and 2 of 216 on this one; the plain prompt fails 150 of 216 on the earlier gate and 198 of 216 on this one. A first re-gate found over-blocks in the product's own shapes, and the narrowings in the plan's last decision fixed them.

Ticket 11's prompt still teaches a stricter form of comparison than the gate now needs, and that is harmless advice to the model. Ticket 16b's published numbers ran on the gate before this ticket. `tests/test_verify_parity.py` names each case the public subset leaves out.

I measured the two numbers the README's red-team bullet cites like this. The 11,352 is every Ticket 9b code-fact statement, rendered by framework/glimmer/code_facts.py's own template functions over a grid of metric families, period pairs and value pairs, run through the gate as a claim in two citation forms, refs alone and refs plus a fact whose statement is the same sentence: 11,352 rows, 0 blocked. The 182 is the claims of Ticket 11's 39 stored drafts from the taught prompt, written by live models on made-up data, each claim replayed alone through the gate against the snapshot and facts of the cycle it was drafted for: 182 claims, 0 blocked. Claude Code wrote the scripts that measured both numbers and ran them from outside this repository, so those scripts are not in this repository. The Ticket 16b re-gate in the same list is reproducible from here: `python -m evals.r1b --regate`.

## Reviews from outside

R29 and R30 came from the external code review by GPT Sol 6.1 through Codex. R29 named the unit-swap shape; it is closed on the gate by the unit rules. R30 named a hole in `verify_claims` that the gate already stopped, so it stays a stated limit on the public subset, with the label-word workaround: to require a unit, list it among the metric's label words, so the claim must name it.

R36 to R39 came from the independent review by Muse Wonder Full: a conflicting label, an unverifiable quantity, a number without a metric ref, and a private term. Each is closed by the rewrite's rules.

R32 came from Ticket 17a's review: a metric value mismatch, closed by the exact-decimal check.

Muse Wonder Full's blind review of Ticket 11 found eight false claims on main, R47 to R54. Through Ticket 11's real proposal core, with its own wording, all eight are now stopped at the first attempt. Seven were stopped by rules the rewrite already had. The eighth, a digit ordinal before an ordinary noun, had also got through the discarded draft, so that rule got wider: any digit ordinal outside a date on a metric claim.

## Mutation testing

I ran a removal mutation pass over this gate's rule arms, from outside this repository: each mutant turns one `if` test in the gate's files off and runs the briefing, verify and red-team tests until the first failure. 493 mutants, 340 killed, 153 survived, which is 31%, and 8 timeouts counted as killed.

| File | Survived of mutants |
| --- | --- |
| framework/briefing/claim_text.py | 105 of 253 |
| framework/briefing/quantities.py | 25 of 72 |
| framework/briefing/gate.py | 12 of 92 |
| framework/briefing/numbers.py | 3 of 10 |
| framework/verify/core.py | 8 of 66 |

About a third of the survivors are guards and early returns. Many sit in the value-period rule, whose overlapping shapes catch the same sentences. These arms have no test of their own: a question mark alone as advice, a hyphenated term as one name, the rotated-term arm, sign handling in since_last, mixed-direction sides, the cited-label guard on imperatives, and the public checker's cited-ids check. This is a known gap I leave for a follow-up ticket: I checked these behaviours from outside the repository, but those checks aren't tests here.

## Who wrote what

The attacks came from Muse Code sessions with no part in writing the gate. Claude Code wrote the prompts, reviewed, and wrote the adjudication files by hand, including the sentences in the review rows. Muse Code wrote the plan, the runner and the fixes in headless sessions Claude Code started.

Limits: what the gate still cannot catch, and what it rejects that is true, are the two lists in `docs/redteam/README.md`.
