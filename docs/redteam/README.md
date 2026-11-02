# Red team

This is the record of two attack rounds against the briefing gate, plus the findings reviewers brought in from other tickets.

A Muse Code session with no part in writing the gate writes the attacks. I rule on them by hand in the adjudication files. The runner keeps the score: it replays every attack and every review row through the real gate in one fixed synthetic context, and `--summary` prints the counts. Nothing here is hand-scored.

## Round 1

34 attacks. All 34 got through the gate they attacked, which was the unfixed gate at commit `8419879`, the commit named in `round-1.frozen.json`. The attacker predicted all 34, so predicted/actual agreement is 34/34. My verdicts: 32 `real_hole`, A20 `not_false`, A25 `disclosed_limit`. A20's `why_false` is wrong, because the 4 it sets against 3 is the three-period total. On the gate as it stands now, 32 are fixed and 2 get through: A20, which is true, and A25, which is false only in words I disclose as left out. Both pass by ruling.

## Round 2

32 attacks. All 32 got through the draft they attacked, and the attacker predicted all 32. All 32 were ruled `real_hole`. That draft held fixes whose code Claude Code had written. It was discarded and rewritten, so the rows in `round-2.frozen.json` describe a gate that is not in this repository: its `gate_files_sha256` is the record of what was attacked, and no patch here rebuilds it. The "now" numbers are measured on the code that is here: 0 get through, 32 fixed.

Round 2 ran as a fresh session, muse-wonder-1.0 at high effort, with `--output-schema` and `--disable-write`, no part in writing the gate. Its reading list was every file in `framework/briefing/`, wider than round 1's, because the fixes had added modules. Its slips: N25 says five tokens between the words and it is four, N21 cites a path that does not exist, and N10's stated mechanism misses the real one, the positional-list skip.

## Found in review

54 rows, kept apart from the attacker totals: 44 `real_hole`, 9 `over_block`, 1 `not_false` (R45, text with no letters or digits, which the gate rejects as a form). R1 to R3 came from Ticket 9's review. R4 to R28, R31 and R33 to R35 came from Claude Code's review. R29 and R30 came from an external code review by GPT Sol 6.1 through Codex. R32 came from Ticket 17a's review. R36 to R39 came from an independent review by Muse Wonder Full. R40 to R46 came from Ticket 11's gate report and Claude Code's review of it. R47 to R54 came from Muse Wonder Full's blind review of Ticket 11.

The eight false claims R47 to R54, with what happened to each:

| id | codes now | fate |
|---|---|---|
| R47 | `L1B_DIRECTION_MISMATCH`, `L1B_METRIC_LABEL_MISMATCH` | stopped at the first attempt |
| R48 | `L1B_UNIT_MISMATCH` | stopped at the first attempt |
| R49 | `L1B_UNIT_MISMATCH` | stopped at the first attempt |
| R50 | `L1B_NEGATED_CLAIM` | stopped at the first attempt |
| R51 | `L1B_UNVERIFIABLE_QUANTITY` | stopped at the first attempt |
| R52 | `L1B_UNVERIFIABLE_QUANTITY` | stopped at the first attempt |
| R53 | `L1B_NUMBER_WITHOUT_METRIC_REF` | stopped at the first attempt |
| R54 | `L1B_UNVERIFIABLE_QUANTITY` | stopped at the first attempt |

"Stopped" means through Ticket 11's real proposal core, with its own wording, each is now stopped at the first attempt. Seven were stopped by rules the rewrite already had. The eighth, a digit ordinal before an ordinary noun, had also got through the discarded draft, so that rule got wider: any digit ordinal outside a date on a metric claim. R51 and R54 are worded to fit the runner's fixed context.

## Summary

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

## What the gate still can't catch

- A word outside a closed list passes, because closed lists stay closed.
- A paraphrased private term, an acrostic, or one part of a hyphenated term.
- Limit 1: a sentence naming the right metric, period and direction that is false in its other words.
- Limit 2: a value with no period word in its clause, and positional lists.
- Advice phrased outside the phrase list.
- Plain ASCII foreign words outside the pinned languages.
- A label joined in lower case.
- In `verify_claims`: units, approximators, foreign number words and imperatives, which it leaves to the gate.
- Words after `this hour goes` naming the pick, which the title rule and the other-label check do not read, so a commitment's words or another metric's label written there pass.
- In `since_last`: containment words outside the pinned list, a direction word outside the lists, and a delta written as a value.

A list of attacks that fails is evidence about those attacks, not proof the gate is complete.

## What it rejects that's true

These are known costs, each pinned in a test:

- A stated change that is not a cited value.
- A spelled count on a fact-only claim.
- `failed` on a fact-only claim.
- A direction implied only by two numbers on a fact-only claim.
- `no time` or `none` over a statement of 0.
- Time words on a period-less metric claim.
- A quoted title with a dash or colon before a strong verb.
- An unlisted noun after a number.
- A since_last change that keeps a period phrase on the label next to the accepted phrase, as in "Pushes in the last period increased by 1 since the last card." It reads as true and the gate rejects it with `L1B_SINCE_LAST_WORDING` alone, because the claim still holds a period phrase.
