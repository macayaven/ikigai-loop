# Held-out sets

## Checker set v1

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

Scored once on 1cd8db8: [checker-results-v1.md](checker-results-v1.md) and [checker-results-v1.json](checker-results-v1.json) from [../heldout_score.py](../heldout_score.py), with [checker-author-task.md](checker-author-task.md), [checker-author-manifest.txt](checker-author-manifest.txt) and [checker-author-commands.txt](checker-author-commands.txt).

## Gate set v1

`gate-heldout-v1.json` holds 40 test sentences for the briefing gate, in the
shape of the red-team round files: one object whose only key is `attacks`,
each row with `id`, `target`, `predicted_passes` and `claim`, plus `kind`
and one line of `why`. 20 are true sentences a correct gate must let
through, and 20 are false ones it must stop, each false in exactly one way:
4 since_last, 4 negation, 3 unit, 3 period, 3 mislabelled_metric and
3 invented_fact.

`predicted_passes` holds the expected verdict, not a guess about the gate:
true for a true sentence, false for a false one. The `target` letters follow
this set's own legend: A since_last, B negation, C unit, D period,
E mislabelled_metric, F invented_fact. A true sentence takes the letter of
the kind it stands closest to. That legend differs from rounds 1 and 2.

GPT Sol 6.1 (OpenAI) wrote the sentences through the Codex CLI at maximum
reasoning effort, on Nov 2, 2026, in a read-only sandbox with web search
disabled. Its folder held only public documents from main at commit aa3c0e8:
`docs/redteam/README.md`, `docs/PREREG.md`, the session notes
`docs/sessions/010b-redteam.md` and `docs/sessions/010c-since-last-wording.md`,
and every other line of the docs that names a gate code. Its task restated
the red-team runner's fixed synthetic context as plain data. It got no code
from `framework/`, no tests, no runner, no plans, and none of the red-team
round files, true-sentence files or adjudications the gate was hardened
against.

The run was blind: the author's run log shows 7 shell commands, all inside
its folder: one printed the working directory and listed the instruction
files in the folder, one listed the contract files, and five read the task
and the contract documents. None opened the gate's code. Three published
files let anyone check what it saw and ran: `gate-author-task.md` (the exact
task the author was given), `gate-author-manifest.txt` (the sha256 of every
file the author saw, and where each came from), and
`gate-author-commands.txt` (the shell commands in the author's run log, with
relative paths only).

Its task told it to label each sentence by the truth judged from the records
alone, not by what the gate is documented to catch. So a false sentence can
be one the docs list as a known limit.

I froze this set in this commit, before any scoring. No sentence is edited
after this commit, whatever the score: a miss is a result.

sha256 of `gate-heldout-v1.json`:

```
aa927912bae204a44a4c906387ca70e26fd5c8936c071653470482028af430cf
```

## Scoring rule for the gate set

I register this rule now, before any score exists:

- It is scored once, on the commit the live cards move to tonight. The
  results name that commit and the gate files' sha256, which the runner
  stamps. If the gate files there differ from the ones at this commit, I say
  so before scoring.
- The scoring commit copies the data file byte for byte to
  `docs/redteam/round-3.json` and runs the red-team runner once on it,
  writing `round-3.frozen.json`, stamped with the gate commit, the gate
  files' sha256 and the input's sha256, and `round-3.results.json`. The
  runner's summary then reports it like any round.
- A sentence the gate lets through counts as PASS, and a stopped one as
  STOP. A sentence that makes the gate raise is "no verdict", counted apart.
- The results give the counts of true pass, true stop, false pass (a false
  sentence let through), false stop (a true sentence stopped) and no verdict,
  and list every miss by id with the gate's codes. Codes are reported, and
  they never change a count.
- Because `predicted_passes` holds the expected verdict, the runner's
  predicted/actual agreement is the number of correct verdicts.
- The author's expected verdicts are taken as written. If I disagree with one
  after scoring, that is a ruling I disclose in the results, never an edit
  to the data file.
