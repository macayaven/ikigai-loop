# R1b — models on the gate

I asked each model to write one short briefing card per case: pick the commitment that most deserves the shown hour and write a few short claims about what the data shows. Each case ran twice, once with the product prompt (built by Ticket 11's `build_prompt` in framework/proposal/prompt.py) and once with a plain prompt that teaches none of the gate's rules (pinned verbatim in D6 of [docs/plans/016b-models-on-the-gate.md](plans/016b-models-on-the-gate.md) and built by evals/r1b_prompts.py). The Muse route carries the harness's own instructions of about 15,900 input tokens, per PREREG Deviation 10. The local route sends temperature 0 and max_tokens 32768; the Muse route exposes neither, so no cap is claimed there.

The set is synthetic, one pass per case (one first draft plus at most one retry through the product's own loop). It came from two author sessions, both on muse-wonder-full-1.0 at high: a first session wrote a set from a script that drew on pools of stock sentences, and Claude Code rejected that file before any arm ran because its facts had nothing to do with its commitments, so no model under test ever saw it; a second fresh session, in Contributor mode on made-up data, in a new empty folder holding only the case-author description, was told to stay in that folder, to write every case by hand with no generator and no pooled sentence, and that a pooled set had already been rejected, and it wrote the 54 cases in this file with reminder agents off for it. Claude Code read that session's log: every path it touched was inside that folder, and it wrote no generator. That session then replaced two fact statements, in r1b-011 and r1b-028, because the private-term scan Claude Code runs on public files hit a word in them, before any arm ran. That session never saw this repository, the gate's source, the product prompt or any result. muse-wonder-full-1.0 is also one of the arms under test, with no memory across sessions. The file's sha256 was recorded right after that, and every result row carries it.

The private-term check is not exercised in this benchmark: the runner passes an explicitly empty, available list, so L1_PRIVATE_TERM cannot fire and L1_PRIVATE_TERMS_UNAVAILABLE is suppressed by construction. A gate pass does not show a sentence is true, and a gate failure does not show a sentence is false. Injection cases score only what the gate sees, so a model that obeys a planted instruction in a way the gate cannot see still passes.

## Live rows — gate 42b57031c11b (commit e18dd3251d3cab9b0671108c8de366aea9d34e00)

| model | effort | arm | counted | pass | fail | fail beyond wording | proposal-only | recovered | stayed failed | unparseable | unavailable | blocked | latency median s | latency worst s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| muse-wonder-1.0 | high | product | 54/54 | 53 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 20.1 | 33.3 |
| muse-wonder-1.0 | high | plain | 54/54 | 10 | 44 | 15 | 0 | 28 | 16 | 0 | 0 | 0 | 7.6 | 18.8 |
| muse-wonder-full-1.0 | high | product | 54/54 | 54 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 47.7 | 137.3 |
| muse-wonder-full-1.0 | high | plain | 54/54 | 11 | 43 | 16 | 0 | 31 | 12 | 0 | 0 | 0 | 27.1 | 96.2 |
| muse-spark-1.3 | medium | product | 54/54 | 54 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 22.0 | 35.3 |
| muse-spark-1.3 | medium | plain | 54/54 | 18 | 36 | 12 | 0 | 24 | 12 | 0 | 0 | 0 | 6.9 | 15.7 |
| muse-spark-1.3 | low | product | 54/54 | 53 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 11.1 | 16.8 |
| muse-spark-1.3 | low | plain | 54/54 | 27 | 27 | 12 | 0 | 19 | 8 | 0 | 0 | 0 | 4.4 | 6.5 |

### muse-wonder-1.0 (high)

cases in the set: 54

#### arm: product

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 53
first-draft gate failures: 1
first-draft gate failures beyond wording or form: 1 (wording or form alone: 0)
failures by code (codes counted, one draft may count twice):
- L1B_CLAIM_WITHOUT_EVIDENCE: 1
- L1B_NUMBER_WITHOUT_METRIC_REF: 3
failures by category (drafts counted once per category they touch):
- Unbacked number: 1
- Wrong or unknown evidence: 1
- Direction: 0
- Advice: 0
- Wording or form: 0
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 0 of 6 counted
- clean: 0 of 6 counted
- confusable-metrics: 1 of 6 counted
- flat-direction: 0 of 6 counted
- injection: 0 of 6 counted
- mixed-direction: 0 of 6 counted
- orphan-number: 0 of 6 counted
- period-scope: 0 of 6 counted
- rounding: 0 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 1
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 54 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 20116.5
first-attempt latency worst ms: 33312
first-attempt prompt tokens median: 18154.5
first-attempt completion tokens median: 3023.5
first-attempt reasoning tokens median: 2687.5
first-attempt cached tokens median: 9844
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

#### arm: plain

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 10
first-draft gate failures: 44
first-draft gate failures beyond wording or form: 15 (wording or form alone: 29)
failures by code (codes counted, one draft may count twice):
- L0_EMPTY_SECTION: 2
- L1B_DIRECTION_MISMATCH: 14
- L1B_METRIC_LABEL_MISSING: 4
- L1B_NUMBER_WITHOUT_METRIC_REF: 16
- L1B_PERIOD_WORD_MISSING: 14
- L1B_TOO_MANY_METRICS: 36
failures by category (drafts counted once per category they touch):
- Unbacked number: 10
- Wrong or unknown evidence: 0
- Direction: 12
- Advice: 0
- Wording or form: 39
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 6 of 6 counted
- clean: 5 of 6 counted
- confusable-metrics: 4 of 6 counted
- flat-direction: 6 of 6 counted
- injection: 5 of 6 counted
- mixed-direction: 6 of 6 counted
- orphan-number: 6 of 6 counted
- period-scope: 5 of 6 counted
- rounding: 1 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 28
stayed failed: 16
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 38 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 7624.5
first-attempt latency worst ms: 18813
first-attempt prompt tokens median: 16842
first-attempt completion tokens median: 1247.5
first-attempt reasoning tokens median: 863.5
first-attempt cached tokens median: 9844
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

paired: 54 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 1; paired plain failures: 44
paired b (plain fails, product passes): 44; c (plain passes, product fails): 1; excluded from the pair: 0
paired beyond wording or form (not registered, no verdict): product 1, plain 15
paired McNemar exact two-sided p: p < 0.0001
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-wonder-1.0 (high): held (product failures 1, plain failures 44)

### muse-wonder-full-1.0 (high)

cases in the set: 54

#### arm: product

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 54
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
- advice: 0 of 6 counted
- clean: 0 of 6 counted
- confusable-metrics: 0 of 6 counted
- flat-direction: 0 of 6 counted
- injection: 0 of 6 counted
- mixed-direction: 0 of 6 counted
- orphan-number: 0 of 6 counted
- period-scope: 0 of 6 counted
- rounding: 0 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 0
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 54 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 47678.5
first-attempt latency worst ms: 137320
first-attempt prompt tokens median: 18157
first-attempt completion tokens median: 2688.5
first-attempt reasoning tokens median: 2365
first-attempt cached tokens median: 9844
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

#### arm: plain

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 11
first-draft gate failures: 43
first-draft gate failures beyond wording or form: 16 (wording or form alone: 27)
failures by code (codes counted, one draft may count twice):
- L1B_DIRECTION_MISMATCH: 6
- L1B_METRIC_LABEL_MISSING: 2
- L1B_NUMBER_WITHOUT_METRIC_REF: 23
- L1B_PERIOD_WORD_MISSING: 15
- L1B_TOO_MANY_METRICS: 39
failures by category (drafts counted once per category they touch):
- Unbacked number: 12
- Wrong or unknown evidence: 0
- Direction: 5
- Advice: 0
- Wording or form: 33
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 6 of 6 counted
- clean: 4 of 6 counted
- confusable-metrics: 5 of 6 counted
- flat-direction: 6 of 6 counted
- injection: 6 of 6 counted
- mixed-direction: 2 of 6 counted
- orphan-number: 4 of 6 counted
- period-scope: 6 of 6 counted
- rounding: 4 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 31
stayed failed: 12
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 42 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 27149
first-attempt latency worst ms: 96232
first-attempt prompt tokens median: 16844.5
first-attempt completion tokens median: 1600.5
first-attempt reasoning tokens median: 1226
first-attempt cached tokens median: 9844
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

paired: 54 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 0; paired plain failures: 43
paired b (plain fails, product passes): 43; c (plain passes, product fails): 0; excluded from the pair: 0
paired beyond wording or form (not registered, no verdict): product 0, plain 16
paired McNemar exact two-sided p: p < 0.0001
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-wonder-full-1.0 (high): not evaluable (product failures 0, plain failures 43; ratio undefined)

### muse-spark-1.3 (medium)

cases in the set: 54

#### arm: product

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 54
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
- advice: 0 of 6 counted
- clean: 0 of 6 counted
- confusable-metrics: 0 of 6 counted
- flat-direction: 0 of 6 counted
- injection: 0 of 6 counted
- mixed-direction: 0 of 6 counted
- orphan-number: 0 of 6 counted
- period-scope: 0 of 6 counted
- rounding: 0 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 0
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 54 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 22012.5
first-attempt latency worst ms: 35286
first-attempt prompt tokens median: 18783.5
first-attempt completion tokens median: 8148
first-attempt reasoning tokens median: 7709
first-attempt cached tokens median: 0
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

#### arm: plain

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 18
first-draft gate failures: 36
first-draft gate failures beyond wording or form: 12 (wording or form alone: 24)
failures by code (codes counted, one draft may count twice):
- L1B_DIRECTION_MISMATCH: 4
- L1B_METRIC_LABEL_MISSING: 2
- L1B_NUMBER_WITHOUT_METRIC_REF: 16
- L1B_PERIOD_WORD_MISSING: 28
- L1B_TOO_MANY_METRICS: 18
failures by category (drafts counted once per category they touch):
- Unbacked number: 9
- Wrong or unknown evidence: 0
- Direction: 3
- Advice: 0
- Wording or form: 30
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 4 of 6 counted
- clean: 3 of 6 counted
- confusable-metrics: 5 of 6 counted
- flat-direction: 5 of 6 counted
- injection: 4 of 6 counted
- mixed-direction: 3 of 6 counted
- orphan-number: 4 of 6 counted
- period-scope: 5 of 6 counted
- rounding: 3 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 24
stayed failed: 12
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 42 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 6884
first-attempt latency worst ms: 15703
first-attempt prompt tokens median: 17112.5
first-attempt completion tokens median: 2139.5
first-attempt reasoning tokens median: 1869.5
first-attempt cached tokens median: 0
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

paired: 54 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 0; paired plain failures: 36
paired b (plain fails, product passes): 36; c (plain passes, product fails): 0; excluded from the pair: 0
paired beyond wording or form (not registered, no verdict): product 0, plain 12
paired McNemar exact two-sided p: p < 0.0001
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-spark-1.3 (medium): not evaluable (product failures 0, plain failures 36; ratio undefined)

### muse-spark-1.3 (low)

cases in the set: 54

#### arm: product

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 53
first-draft gate failures: 1
first-draft gate failures beyond wording or form: 1 (wording or form alone: 0)
failures by code (codes counted, one draft may count twice):
- L1B_DIRECTION_MISMATCH: 1
failures by category (drafts counted once per category they touch):
- Unbacked number: 0
- Wrong or unknown evidence: 0
- Direction: 1
- Advice: 0
- Wording or form: 0
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 1 of 6 counted
- clean: 0 of 6 counted
- confusable-metrics: 0 of 6 counted
- flat-direction: 0 of 6 counted
- injection: 0 of 6 counted
- mixed-direction: 0 of 6 counted
- orphan-number: 0 of 6 counted
- period-scope: 0 of 6 counted
- rounding: 0 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 1
stayed failed: 0
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 54 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 11125.5
first-attempt latency worst ms: 16802
first-attempt prompt tokens median: 18783.5
first-attempt completion tokens median: 3591
first-attempt reasoning tokens median: 3256
first-attempt cached tokens median: 0
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

#### arm: plain

cases counted: 54
cases attempted but not complete: 0
cases not run: 0
first-draft passes: 27
first-draft gate failures: 27
first-draft gate failures beyond wording or form: 12 (wording or form alone: 15)
failures by code (codes counted, one draft may count twice):
- L1B_DIRECTION_MISMATCH: 7
- L1B_METRIC_LABEL_MISSING: 6
- L1B_NUMBER_WITHOUT_METRIC_REF: 8
- L1B_PERIOD_WORD_MISSING: 20
- L1B_TOO_MANY_METRICS: 17
failures by category (drafts counted once per category they touch):
- Unbacked number: 6
- Wrong or unknown evidence: 0
- Direction: 6
- Advice: 0
- Wording or form: 21
- Leak: 0
A plain-arm failure is not always a false sentence: the wording split above shows how much of it is wording or form the gate insists on.
failures by trap class (failures of counted cases in that class):
- advice: 6 of 6 counted
- clean: 3 of 6 counted
- confusable-metrics: 4 of 6 counted
- flat-direction: 3 of 6 counted
- injection: 0 of 6 counted
- mixed-direction: 4 of 6 counted
- orphan-number: 5 of 6 counted
- period-scope: 2 of 6 counted
- rounding: 0 of 6 counted
proposal-level codes (apart, never in the numerator):
- none
recovered by one retry: 19
stayed failed: 8
of those, retry passed the gate but kept a proposal-level code: 0
first-draft failure whose retry came back unavailable: 0
ended passing within one retry: 46 of 54 counted
unparseable first drafts recovered by retry: 0
proposal-level-only first drafts: 0
not-a-draft-outcome first drafts: 0
unparseable first drafts: 0
unavailable first attempts: 0
blocked first attempts: 0
first-attempt latency median ms: 4374
first-attempt latency worst ms: 6543
first-attempt prompt tokens median: 17112
first-attempt completion tokens median: 1185
first-attempt reasoning tokens median: 893
first-attempt cached tokens median: 0
medians take the middle value, or the mean of the middle two.
muse versions seen: Muse Code 1.4.14 (1.4.14-R7309.1)
rules-file values seen: False

paired: 54 cases with a parsed, unblocked first draft in both the product and the plain arm
paired product failures: 1; paired plain failures: 27
paired b (plain fails, product passes): 26; c (plain passes, product fails): 0; excluded from the pair: 0
paired beyond wording or form (not registered, no verdict): product 1, plain 12
paired McNemar exact two-sided p: p < 0.0001
the p-value is descriptive only: the counts are the result, and it generalises past them not at all.
registered prediction: the plain prompt fails at least 3 times as often as the product prompt, on every model
verdict: muse-spark-1.3 (low): held (product failures 1, plain failures 27)

overall: not evaluable (did not hold if any row did not hold, held if every row held, otherwise not evaluable)

