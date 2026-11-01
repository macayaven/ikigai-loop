# Check your agent's claims against your own records

This is a small checker that reconciles the numbers and sources an agent states against records you supply. This folder holds one copyable case: an agent output with a false number, the command, the output, and the fix. Everything here is made up: ticket queues and deploy counts, no real person or company.

## The case

`input.json` says November deploys reached 12. The records in the same file say 7. From a clone of this repo:

```sh
uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims examples/verify/input.json; echo exit=$?
```

```text
FAIL
This check covers parseable numbers, cited sources, labels and direction. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist.
L1B_METRIC_VALUE_MISMATCH c1: metric value differs from the snapshot
exit=1
```

The claim cites `deploys.nov` as 12 and `metrics` says 7, so the run fails with exit 1. `input-fixed.json` corrects the claim to 7, leaves the records alone, and passes with exit 0. The fix goes in the agent's output, never in your records.

Exit 0 is a pass, 1 means violations, 2 means bad input. Add `--json` for machine output, or pass `-` to read stdin. The [browser page](https://macayaven.github.io/ikigai-loop/verify/) runs the same check on your machine with nothing sent anywhere.

## Every input field

| Field | Rule |
|---|---|
| `claims` | Required, at least one. Each claim has a non-blank `id`, unique in the file, at most 200 characters; non-blank `text`, at most 2,000 characters; and the evidence it cites: `fact_ids`, a list of fact ids, and `metric_refs`, a list of `{"metric_id": ..., "value": ...}`, at most 100. A claim with neither fails. Every number in the text needs a cited value behind it. |
| `facts` | Required, may be empty. Dict of id to string, from your records, never from the agent's output. A cited fact is only checked to exist. |
| `metrics` | Required, may be empty. Dict of id to number, from your records, never from the agent's output. `3` and `3.0` match. Strings, booleans and null are bad input. |
| `labels` | Optional. Dict of metric id to the words a claim citing it must contain, at most 10, each at most 100 characters. Every listed word must appear as a whole word, case-insensitive. Alternatives can't be expressed, so pick the form the agent writes. |
| `order` | Optional. List of series, each 2 to 366 metric ids, earliest first, each id once across all series. Direction words are checked against it, and a word only an uncited member of the series lists must not appear in the claim. |
| `deny_terms` | Optional. A term of 3 characters or fewer matches whole words only, a longer term matches anywhere in the text, case-insensitive. At most 1,000, each at most 100 characters. |
| `advice_words` | Optional. Whole word, case-insensitive. No default list. At most 1,000, each at most 100 characters. |

With `labels` or `order` declared for its metrics, a claim may cite one such metric, or several from one series; otherwise split the claim. A direction word on a claim citing one such metric always fails, because one value can't show a change. Secrets and contact details in claim text are always checked. Input over 10 MB, over 5,000 claims, over 100,000 characters of claim text, or nested deeper than 64 levels is bad input.

## What this does not catch

This check covers parseable numbers, cited sources, labels and direction. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist.

Also:

- A false sentence around correct numbers.
- Without labels, a number only has to match some ref on its claim, and a metric with no `labels` or `order` entry gets no label or direction check.
- Inside one series, a value is not bound to its place in the sentence unless a direction word exposes it: "rose from 9 in October to 5 in November" passes when October was 5 and November was 9.
- Direction words outside the gate's lists are not seen.
- Rounding and sign: a number is backed when a cited value rounds to it at the precision written, with the sign ignored, so 5 passes for 4.75 and -7 for 7.
- Number forms the parser does not read, such as `7k` or `8th`, plus dates and clock times. The full list is at the top of [framework/briefing/numbers.py](../../framework/briefing/numbers.py).
- Claim ids are echoed as given, so never put private terms in ids.
