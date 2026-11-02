# Held-out checker set v1

This file describes `checker-heldout-v1.json`, a set of 40 test cases for the
public claim checker: the `verify-claims` command line and the browser page
that runs the same check.

GPT Sol 6.1 (OpenAI) wrote the cases through the Codex CLI at maximum
reasoning effort, on Nov 2, 2026, in a read-only sandbox with web search
disabled. Its folder held only the public description of the checker, taken
from main at commit 5b8dad6: the visible text of the checker page
(`docs/verify/index.html`), the page's three example inputs
(`docs/verify/examples/`), the README's "Check your own agent" section, the
worked example (`examples/verify/README.md`, `input.json` and
`input-fixed.json`), and the two lists "What the gate still can't catch" and
"What it rejects that's true" from `docs/redteam/README.md`. It got no source
code from `framework/`, no tests, no page script and no browser bundle.

The run was blind: the run log shows 6 shell commands, all inside that folder, one printing the working directory, one listing the folder's files and four reading them. None opened the checker's code.

The set holds 20 PASS cases (a true claim in a well-formed input) and 20
FAIL cases (a false claim, each false in exactly one way): 4 wrong_number,
4 negation, 3 wrong_unit, 3 wrong_period, 3 mislabelled_metric and
3 missing_fact. Domains: 7 deploys, 7 revenue, 7 latency, 7 tickets,
6 steps and 6 screen_hours, each with both verdicts. Each case has an id,
the expected verdict, its kind, its domain, one line on why, and the checker
input, which holds one claim.

Its task told it to label each case by the truth, judged from that input
alone, and not by what the checker is documented to catch. So a FAIL case
can be one the checker says it leaves to the gate.

I froze this set in this commit, before any scoring. No case is edited after
this commit, whatever the score: a miss is a result.

sha256 of `checker-heldout-v1.json`:

```
937789f47824e6a073e72a73f027eadf95e24787acb1a77bc97c269513bc2610
```

## Scoring rule

I register this rule now, before any score exists:

- It is scored once, on the first main that contains Ticket C1, the public
  checker update. The results name that commit.
- Each case's input goes to the public command line checker exactly as
  written in the file.
- Exit 0 counts as PASS and exit 1 as FAIL. Any other exit, or a crash, is
  "no verdict": counted apart, never as a pass.
- The results give the counts of true pass, true fail, false pass, false
  fail and no verdict, and list every miss by id with the checker's codes.
  Codes are reported, and they never change a count.
- The author's expected verdicts are taken as written. If I disagree with
  one after scoring, that is a ruling I disclose in the results, never an
  edit to this file.
