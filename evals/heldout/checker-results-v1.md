# Held-out checker set v1: results

I scored the frozen set once, on commit 1cd8db8, the first main that contains Ticket C1. The data file is `checker-heldout-v1.json` with sha256 `937789f47824e6a073e72a73f027eadf95e24787acb1a77bc97c269513bc2610`.

Claude Code took the score at 23:51 CET on Nov 2, running the public command line checker once per case from a scratch script outside the repository. Each case's input went in as the exact text it has in the file, with the JSON output flag. Exit 0 counted as PASS and exit 1 as FAIL; any other exit would have been no verdict, and there was none. I then wrote the scorer in `evals/heldout_score.py`, which feeds the same 40 raw texts to the same checker on the same commit and checks it reproduces those counts. It does.

## Counts

| group | count |
|---|---|
| true pass | 18 |
| true fail | 17 |
| false pass | 3 |
| false fail | 2 |
| no verdict | 0 |

35 of 40 correct.

By kind: wrong_number 4 of 4 failed, wrong_unit 3 of 3, wrong_period 3 of 3, mislabelled_metric 3 of 3, missing_fact 3 of 3, negation 1 of 4, and 18 of 20 true sentences passed.

## Misses

| id | kind | what the checker did | codes | skipped checks | author's why |
|---|---|---|---|---|---|
| H04 | negation | passed a false claim | none | none | The handoff record says the attachment checklist was included; the claim denies its inclusion. |
| H18 | negation | passed a false claim | none | none | The record confirms that the export was saved; the claim says it was never saved. |
| H38 | negation | passed a false claim | none | none | The record says the batch contains tickets and all have categories; the claim says none do. |
| H13 | true | failed a true sentence | L1B_NUMBER_WITHOUT_METRIC_REF, L1B_UNVERIFIABLE_QUANTITY | c13: unit, period name, value-period binding | The May and June records show a decrease from 32 deploys to 26. |
| H23 | true | failed a true sentence | L1B_UNVERIFIABLE_QUANTITY | none | The cited location record places the weekly export in the shared activity folder. |

## What the misses have in common

The three false passes are all negations of fact-only claims, and the checker only checks that a cited fact exists, which its own docs disclose. The two false fails are true sentences failed over how a quantity is written: the hyphenated spelled numbers in H13 were not read as values, and "weekly" in H23 was read as an unverifiable quantity, on a sentence word for word the same as its cited fact.
