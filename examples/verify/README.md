# Check your agent's claims against your own records

This is a small checker that reconciles the numbers and sources an agent states against records you supply. This folder holds one copyable case: an agent output with a false number, the command, the output, and the fix. Everything here is made up: ticket queues and deploy counts, no real person or company.

## The case

`input.json` says November deploys reached 12. The records in the same file say 7. From a clone of this repo:

```sh
uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims examples/verify/input.json; echo exit=$?
```

```text
FAIL
This check covers parseable numbers, cited sources, labels, direction, negation, quantity forms, and units and periods where you declare them. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist. A check listed as not checked did not run.
L1B_METRIC_VALUE_MISMATCH c1: metric value differs from the snapshot
exit=1
```

The claim cites `deploys.nov` as 12 and `metrics` says 7, so the run fails with exit 1. `input-fixed.json` corrects the claim to 7, leaves the records alone, and passes with exit 0. The fix goes in the agent's output, never in your records.

Exit 0 is a pass, 1 means violations, 2 means bad input. A check that could not run for lack of metadata is listed as not checked and never changes the exit code. Add `--json` for machine output, or pass `-` to read stdin. The [browser page](https://carloscrespomacaya.com/ikigai-loop/verify/) runs the same check on your machine with nothing sent anywhere.

## Every input field

| Field | Rule |
|---|---|
| `claims` | Required, at least one. Each claim has a non-blank `id`, unique in the file, at most 200 characters; non-blank `text`, at most 2,000 characters; and the evidence it cites: `fact_ids`, a list of fact ids, and `metric_refs`, a list of `{"metric_id": ..., "value": ...}`, at most 100. A claim with neither fails. Every number in the text needs a cited value behind it. |
| `facts` | Required, may be empty. Dict of id to string, from your records, never from the agent's output. A cited fact is only checked to exist. |
| `metrics` | Required, may be empty. Dict of id to number, from your records, never from the agent's output. `3` and `3.0` match. Strings, booleans and null are bad input. |
| `labels` | Optional. Dict of metric id to the words a claim citing it must contain, at most 10, each at most 100 characters. Every listed word must appear as a whole word, case-insensitive. Alternatives can't be expressed, so pick the form the agent writes. A claim citing a labelled metric fails when it holds every word of a labelled metric it does not cite, or a time word outside its cited metric's listed words. At most MAX_LABEL_CHECKS (2,000,000) label checks run per input, distinct label lists times the claims citing a labelled or ordered metric; over that the input is rejected naming the cap. |
| `order` | Optional. List of series, each 2 to 366 metric ids, earliest first, each id once across all series. Direction words are checked against it, and a word only an uncited member of the series lists must not appear in the claim. |
| `units` | Optional. Dict of metric id to one of `count`, `hours`, `minutes`, `seconds`, `days`, `percent`. A unit, magnitude (`thousand` and up) or percent form beside a number must agree with the declared unit; a number with no unit word after it always passes this check. At most 1,000 entries. |
| `periods` | Optional. Dict of metric id to the period phrase as the agent writes it, for example `October` or `last week`, at most 100 characters and holding a letter or digit. A cited metric with a declared period must be named by that period. At most 1,000 entries. |
| `deny_terms` | Optional. A term of 3 characters or fewer matches whole words only, a longer term matches anywhere in the text, case-insensitive. At most 1,000, each at most 100 characters. |
| `advice_words` | Optional. Whole word, case-insensitive. No default list. At most 1,000, each at most 100 characters. |

With `labels` or `order` declared for its metrics, a claim may cite one such metric, or several from one series; otherwise split the claim. A direction word on a claim citing one such metric always fails, because one value can't show a change. Secrets and contact details in claim text are always checked. Input over 10 MB, over 5,000 claims, over 100,000 characters of claim text, or nested deeper than 64 levels is bad input.

## What this does not catch

This check covers parseable numbers, cited sources, labels, direction, negation, quantity forms, and units and periods where you declare them. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist. A check listed as not checked did not run. The Python function verify_claims keeps the earlier, smaller set of checks; the command line and the [browser page](https://carloscrespomacaya.com/ikigai-loop/verify/) run the wider checker described here.

What this checker does not check: it never checks that a sentence is true; a word after a number that is not a unit, a magnitude or a percent form isn't checked; disguised spellings of your private terms aren't caught; advice and instructions in the text aren't caught unless you list advice words.

Also:

- A false sentence around correct numbers.
- What fails now: a claim with a negation word fails, unless it states a zero right before a word of the cited metric's labels and the cited value is 0 (for example "No deploys failed" with labels deploys and failed); quantity words in place of digits fail (about, over, nearly, half, a couple, twice); with a declared unit, a unit word that disagrees fails; with a declared period, a missing or stray period fails, and so does a value beside the wrong period.
- Without labels, a number only has to match some ref on its claim, and a metric with no `labels` or `order` entry gets no label or direction check. On a claim citing a labelled metric, only labelled metrics back its numbers.
- Inside one declared series, when periods are declared, each cited value must sit beside its own declared period phrase: "Deploys were 9 in October and 5 in November" fails when October was 5 and November was 9.
- Direction words outside the direction word lists are not seen.
- Rounding and sign: a number with decimals is backed when a cited value rounds to it at the precision written, so 4.8 passes for 4.75; a whole number is backed only when the value rounds to it at two decimal places, so 5 passes for 4.9999999; a minus sign counts against a positive value, and not the other way round, so -7 fails for 7 while 7 passes for -7.
- Units: declare a metric's unit in `units` to check it. Without a declared unit the unit check is listed as not checked.
- Number forms the parser does not read, such as `7k` or `8th`, plus dates and clock times. The full list is at the top of [framework/briefing/numbers.py](../../framework/briefing/numbers.py).
- Claim ids are echoed as given, so never put private terms in ids.
- Disclosed limits: the bare word one as a value, period compounds and comparisons with than are not checked; a number-like or quantity-like word inside a name that a cited fact carries is not skipped, which can only make the check stricter; a unit word that agrees with one cited metric can still fail against another, because the sentence does not say which metric the word belongs to; `verify_and_repair` still wraps the earlier `verify_claims`.
