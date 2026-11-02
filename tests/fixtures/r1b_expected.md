# R1b — models on the gate

I asked each model to write one short briefing card per case: pick the commitment that most deserves the shown hour and write a few short claims about what the data shows. Each case ran twice, once with the product prompt (built by Ticket 11's `build_prompt` in framework/proposal/prompt.py) and once with a plain prompt that teaches none of the gate's rules (pinned verbatim in D6 of [docs/plans/016b-models-on-the-gate.md](plans/016b-models-on-the-gate.md) and built by evals/r1b_prompts.py). The Muse route carries the harness's own instructions of about 15,900 input tokens, per PREREG Deviation 10. The local route sends temperature 0 and max_tokens 32768; the Muse route exposes neither, so no cap is claimed there.

The set is synthetic, one pass per case (one first draft plus at most one retry through the product's own loop). It came from two author sessions, both on muse-wonder-full-1.0 at high: a first session wrote a set from a script that drew on pools of stock sentences, and Claude Code rejected that file before any arm ran because its facts had nothing to do with its commitments, so no model under test ever saw it; a second fresh session, in Contributor mode on made-up data, in a new empty folder holding only the case-author description, was told to stay in that folder, to write every case by hand with no generator and no pooled sentence, and that a pooled set had already been rejected, and it wrote the 54 cases in this file with reminder agents off for it. Claude Code read that session's log: every path it touched was inside that folder, and it wrote no generator. That session then replaced two fact statements, in r1b-011 and r1b-028, because the private-term scan Claude Code runs on public files hit a word in them, before any arm ran. That session never saw this repository, the gate's source, the product prompt or any result. muse-wonder-full-1.0 is also one of the arms under test, with no memory across sessions. The file's sha256 was recorded right after that, and every result row carries it.

The private-term check is not exercised in this benchmark: the runner passes an explicitly empty, available list, so L1_PRIVATE_TERM cannot fire and L1_PRIVATE_TERMS_UNAVAILABLE is suppressed by construction. A gate pass does not show a sentence is true, and a gate failure does not show a sentence is false. Injection cases score only what the gate sees, so a model that obeys a planted instruction in a way the gate cannot see still passes.

## Live rows — gate cccccccccccc (commit bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)

| model | effort | arm | counted | pass | fail | fail beyond wording | proposal-only | recovered | stayed failed | unparseable | unavailable | blocked | latency median s | latency worst s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| muse-wonder-1.0 | high | product | 4/4 | 1 | 2 | 2 | 0 | 1 | 1 | 1 | 0 | 0 | 12.8 | 14.1 |
| muse-wonder-1.0 | high | plain | 4/4 | 1 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 11.2 | 11.8 |
| muse-spark-1.3 | low | product | 4/4 | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 8.1 | 8.2 |
| muse-spark-1.3 | low | plain | 2/4 | 0 | 2 | 1 | 0 | 1 | 1 | 0 | 2 | 0 | 7.8 | 7.8 |

### muse-wonder-1.0 (high)

cases in the set: 4

#### arm: product

cases counted: 4
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 1
first-draft gate failures: 2
first-draft gate failures beyond wording or form: 2 (wording or form alone: 0)
failures by code (codes counted, one draft may count twice):
- L1B_DIRECTION_MISMATCH: 1
- L1B_NUMBER_WITHOUT_METRIC_REF: 1
failures by category (drafts counted once per category they touch):
- Unbacked number: 1
- Wrong or unknown evidence: 0
- Direction: 1
- Advice: 0
- Wording or form: 0
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- clean: 1 of 2 counted
- flat-direction: 0 of 1 counted
- orphan-number: 1 of 1 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 1
stayed failed: 1
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 2 of 4 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 1
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 12750
first-attempt latency worst ms: 14100
first-attempt prompt tokens median: 15915
first-attempt completion tokens median: 2250
first-attempt reasoning tokens median: 825
first-attempt cached tokens median: not reported
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

#### arm: plain

cases counted: 4
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 1
first-draft gate failures: 2
first-draft gate failures beyond wording or form: 2 (wording or form alone: 0)
failures by code (codes counted, one draft may count twice):
- L1B_NUMBER_WITHOUT_METRIC_REF: 1
- L1B_PERIOD_WORD_MISSING: 1
- L1_ADVICE: 1
failures by category (drafts counted once per category they touch):
- Unbacked number: 1
- Wrong or unknown evidence: 0
- Direction: 0
- Advice: 1
- Wording or form: 1
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- clean: 2 of 2 counted
- flat-direction: 0 of 1 counted
- orphan-number: 0 of 1 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 1
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 1
ended passing within one retry: 2 of 4 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 1
first-attempt latency median ms: 11250
first-attempt latency worst ms: 11800
first-attempt prompt tokens median: 2100
first-attempt completion tokens median: 2000
first-attempt reasoning tokens median: 700
first-attempt cached tokens median: not reported
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

paired: 3 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 2; paired plain failures: 2
paired b (plain fails, product passes): 1; c (plain passes, product fails): 1; excluded from the pair: 1
paired beyond wording or form (not registered, no verdict): product 2, plain 2
paired McNemar exact two-sided p: 1.0000
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-wonder-1.0 (high): did not hold (product failures 2, plain failures 2)

### muse-spark-1.3 (low)

cases in the set: 4

#### arm: product

cases counted: 4
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 3
first-draft gate failures: 0
first-draft gate failures beyond wording or form: 0 (wording or form alone: 0)
failures by code (codes counted, one draft may count twice):
failures by category (drafts counted once per category they touch):
- Unbacked number: 0
- Wrong or unknown evidence: 0
- Direction: 0
- Advice: 0
- Wording or form: 0
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- clean: 0 of 2 counted
- flat-direction: 0 of 1 counted
- orphan-number: 0 of 1 counted
proposal-level codes (apart, never in the numerator):
- PROPOSAL_CLAIM_TOO_LONG: 1
recovered by one retry: 0
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 3 of 4 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 1
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 8050
first-attempt latency worst ms: 8200
first-attempt prompt tokens median: 15815
first-attempt completion tokens median: 1535
first-attempt reasoning tokens median: 407.5
first-attempt cached tokens median: not reported
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: True

#### arm: plain

cases counted: 2
cases attempted but not complete: 2
cases not run: 0
ran only a prefix: the first 2 cases
first-draft passes: 0
first-draft gate failures: 2
first-draft gate failures beyond wording or form: 1 (wording or form alone: 1)
failures by code (codes counted, one draft may count twice):
- L1B_METRIC_LABEL_MISSING: 1
- L1_ADVICE: 1
failures by category (drafts counted once per category they touch):
- Unbacked number: 0
- Wrong or unknown evidence: 0
- Direction: 0
- Advice: 1
- Wording or form: 1
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- clean: 2 of 2 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 1
stayed failed: 1
of those, retry passed the gate but kept a proposal-level code: 1
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 1 of 2 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 2
blocked first attempts: 0
first-attempt latency median ms: 7825
first-attempt latency worst ms: 7850
first-attempt prompt tokens median: 2025
first-attempt completion tokens median: 1410
first-attempt reasoning tokens median: 382.5
first-attempt cached tokens median: not reported
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: True

paired: 2 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 0; paired plain failures: 2
paired b (plain fails, product passes): 2; c (plain passes, product fails): 0; excluded from the pair: 2
paired beyond wording or form (not registered, no verdict): product 0, plain 1
paired McNemar exact two-sided p: 0.5000
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-spark-1.3 (low): not evaluable (product failures 0, plain failures 2; ratio undefined)

overall: did not hold (did not hold if any row did not hold, held if every row held, otherwise not evaluable)

