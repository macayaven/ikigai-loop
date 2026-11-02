# Write a held-out test set for a claim checker

## What this is

A small open-source checker reads one JSON input, holding claims an AI agent wrote and the records those claims cite, and returns PASS or FAIL. You will write 40 test cases for it from its public description alone.

You have not seen the checker's code, and you must not look for it. These cases are worth something only because nobody tuned the checker against them. Once you hand them in they are frozen and scored once, and nobody edits them afterwards, whatever the score.

## Read only this folder

Everything you need is in `contract/`, copied from the public repository. Read all of it:

- `checker-page.md`: the visible text of the checker's web page.
- `readme-check-your-own-agent.md`: the checker section of the project README.
- `worked-example/README.md`: the field reference, with every input field and its rules, plus what the checker does not catch. `input.json` and `input-fixed.json` are its worked case. When the page or README mentions "the worked example", this is it.
- `page-examples/*.json`: the three example inputs from the web page.
- `redteam-limits-and-true-rejects.md`: two lists from the project's red-team record. They describe the project's private gate. The checker is the public subset of that gate, and the last line of the field reference's "What this does not catch" says what the checker leaves to the gate.

The adapter recipe the README links to is not included: it is about converting other output shapes into this input, not about what the checker accepts.

Rules for this task:

- Don't read, list or search anything outside this folder: not your home directory, not folders next to this one, not any repository, package or installed tool. If the contract seems silent on something, decide from what it says.
- Don't run the checker or any other code. You have no web access.
- Write no files. Your final message is saved for you as the answer.

## The 40 cases

- 20 cases with expected verdict PASS: a true claim in a well-formed input.
- 20 cases with expected verdict FAIL: a false claim in a well-formed input. Each is false in exactly one way, of one of these six kinds. Use each kind at least 3 times:
  - `wrong_number`: the claim's number differs from what the records hold.
  - `negation`: the claim negates what the records show, so it says the opposite of them.
  - `wrong_unit`: the claim gives the number in a unit other than the record's, so it is wrong for the unit it names.
  - `wrong_period`: the claim puts the number in a period the record doesn't cover.
  - `mislabelled_metric`: the claim attaches the number to a different metric from the one the record measures.
  - `missing_fact`: the claim cites a fact that doesn't exist in the records.
- Six domains: `deploys`, `revenue`, `latency`, `tickets`, `steps`, `screen_hours`. Each domain appears in at least 5 cases, with at least one PASS and one FAIL.
- Each case's input holds exactly one claim and stands alone, with its own records, facts and any labels or order it needs.
- Vary the claims the way real agent reports vary: single values, changes between periods, claims backed by facts instead of metrics, different number forms and sentence shapes.

## What "expected" means

The expected verdict is the truth, judged from that case's input alone. PASS means the claim is true against the records in the same input. FAIL means it is false against them.

Don't predict what this checker will do. The contract says some things are left unchecked and some true things are rejected; label by the truth anyway. Neither aim at those disclosed limits nor steer around them. Write claims an agent might really put in a report, in inputs written by a careful user who has read this contract.

The verdict must follow from the input alone. Someone who reads only that input JSON must be able to tell whether the claim is true or false. If a case turns on a unit or a period, the input must show that unit or period somewhere a reader can see it.

## Well-formed input

Every input, PASS or FAIL, follows the field table in `worked-example/README.md`: required fields present, the right types, within the limits. A FAIL case is false because of what its claim says or cites, never because the input breaks the table.

## Don't copy the examples

No case reuses the examples' metric names, values, sentences or facts: the October and November deploy counts of 5, 7 and 12, the support queue note, the deny term in the leaked-term example. Deploys as a domain is fine, with your own records.

## Made-up data, plain words

All records, names and numbers are made up: no real person, company or product, and no contact details or secrets. Steps and screen hours are plain activity counts, with no health framing and no advice. Don't use these words anywhere: coach, wellness, wellbeing, mental, recovery.

## Format

One JSON array of 40 objects, each with these fields in this order:

| field | value |
|---|---|
| `id` | `"H01"` to `"H40"`, in order |
| `expected` | `"PASS"` or `"FAIL"` |
| `kind` | `"true"` for a PASS case; for a FAIL case, one of the six kinds above |
| `domain` | one of the six domains above |
| `why` | one line, under 200 characters: what makes the claim true, or the one way it is false |
| `input` | the checker's input object, exactly as the checker would read it |

Mix PASS and FAIL cases through the list; don't group them.

Your final message is that array and nothing else: no Markdown fences, no text before or after it. It must parse as JSON.

## Before you answer

Check: 40 cases; 20 PASS and 20 FAIL; each FAIL kind used at least 3 times; each domain in at least 5 cases with both verdicts; ids unique and in order; every input holds one claim and follows the field table; nothing copied from the examples; every `why` is one line.
