# Domain packs: my checker on someone else's records

My live loop checks claims about my own records, so it's fair to ask whether any of it works for anyone else. A domain pack is my answer. It is one JSON file that declares a goal, the commitments allowed with a rule for each, the CSV columns to read and the metrics to compute, for a domain that isn't mine. The code in `framework/domains/` turns pinned CSV files into metrics, asks Muse Wonder for one commitment and the reasons for it, and checks those reasons with my public claim checker, `check_claims`, which runs my gate's checks on records anyone supplies. Nothing on the live path imports it, and a test keeps it that way.

I built two packs on public data whose answers anyone can recompute: bike-share operations and home energy use. Across both, the checker caught 120 of 120 planted errors and accepted 38 of 38 correct control sentences, and Muse Wonder's first drafts passed on 28 of 38 weeks, 35 after one repair, with the right commitment on all 38. What those numbers do and don't show is below the results.

## Try it

You need Python 3.12 and `uv` (run `uv sync` once). No key and no model:

```sh
uv run python -m framework.domains show --pack examples/domains/bikes/pack.json --window 2012-06-04
uv run python -m framework.domains check --pack examples/domains/bikes/pack.json --window 2012-06-04 --claims examples/domains/bikes/try-claims.json; echo exit=$?
uv run python -m framework.domains lint --pack examples/domains/bikes/pack.json --window 2012-06-04
```

`show` prints the 23 metrics for the week of 2012-06-04 and `identities: 2 of 2 hold`. `check` runs two sentences against that week: "Total rentals were 7,001 on 2012-06-05." passes, and "Total rentals were 7,010 on 2012-06-05." fails with `L1B_METRIC_VALUE_MISMATCH`, so you see exit 1. `lint` checks the pack itself before any model runs: every fact quoted alone as a sentence, and one correct sentence per metric.

To see one planted error from the frozen set stopped, run the same `check` with `--window 2012-06-11 --claims examples/domains/bikes/planted-example.json`. The sentence says "Casual rentals were 1,025 on 2012-06-11." and the record says 1,017, so it fails with `L1B_METRIC_VALUE_MISMATCH`.

`propose` asks Muse Wonder for one commitment with reasons and checks them, with one repair if they fail. It runs through Muse Code headless on my subscription:

```sh
uv run python -m framework.domains propose --pack examples/domains/bikes/pack.json --window 2012-06-04 --out run.json
```

## What a pack declares

The bikes pack, [examples/domains/bikes/pack.json](../examples/domains/bikes/pack.json):

| Part | What it says |
| --- | --- |
| Goal | Keep enough bikes on the street for the riders who show up. |
| Commitments | `review-capacity` when `busy_days` is at least 1; `continue-monitoring` when it is exactly 0 |
| Signals | `cnt`, `casual` and `registered` from `day.csv`; `cnt` from `hour.csv` |
| Metrics | total, casual and registered rentals per day; total rentals for the week; busy days (days with more than 7,000 total rentals) |
| Identities | casual + registered = cnt on every row; each day's cnt equals the sum of that day's hourly cnt |
| Source | UCI Bike Sharing, `day.csv` and `hour.csv` unchanged, pinned by sha256 |

A window is one Monday-start week. The adapter refuses a file whose hash differs from the pack, and refuses a week where an identity fails. The model sees the pack's note, goal and commitments, the week's metrics with their labels, units and periods, the facts and the writing rules, and nothing else.

## Where the answers come from

- The data is the UCI Bike Sharing dataset (CC BY 4.0; [ATTRIBUTION.md](../examples/domains/bikes/ATTRIBUTION.md)), copied byte for byte.
- The expected answers come from [evals/domains_oracle.py](../evals/domains_oracle.py), a separate script that uses only the standard library, hardcodes the column names, and imports nothing from my code. A test checks that the oracle and the adapter agree on every metric of all 104 complete weeks.
- You can recheck any number without Python: `tr -d '\r' < examples/domains/bikes/data/day.csv | awk -F, '$2=="2012-06-11" {print $14, $15, $16}'` prints `1017 5647 6664` (casual, registered, total).

## The frozen evaluation, bikes

How I froze it, before any result:

- 20 weeks drawn with seed 20261104 from the 104 complete weeks. I developed only on two other weeks, 2011-06-06 and 2012-06-04.
- From the oracle's numbers alone, one generator wrote 20 correct sentences (controls) and 60 planted errors, 10 of each kind: wrong value, wrong label, wrong period, wrong unit, wrong source, wrong direction. Each planted error keeps its correct twin.
- I committed the cases ([evals/domains_cases/bikes.json](../evals/domains_cases/bikes.json), sha256 `9978379d`) and the rule for headline wording: at least 51 of 60 errors caught and 18 of 20 controls accepted, or I call it exploratory.
- Then one run, on commit `ffdd615`: the checker on all 80 cases, and Muse Wonder (`muse-wonder-1.0`, high effort) on each of the 20 weeks, with at most one repair.

| Measure | Result |
| --- | --- |
| Planted errors caught | 60/60 |
| Correct controls accepted | 20/20 |
| Correct twins accepted | 60/60 |
| Wonder first drafts accepted | 13/20 |
| Accepted after one repair | 6/20 |
| Still failing after the repair | 1/20 |
| Transport errors | 0/20 |
| Commitment matches the oracle | 20/20 |
| Latency, first attempt (median) | 13.2 s |
| Latency, slowest week in total | 29.5 s |

Which check caught each planted kind:

| Kind | Caught | Code |
| --- | --- | --- |
| Wrong value | 10/10 | 5 `L1B_METRIC_VALUE_MISMATCH` (wrong number cited), 5 `L1B_NUMBER_WITHOUT_METRIC_REF` (wrong number written, right one cited) |
| Wrong label | 10/10 | `L1B_METRIC_LABEL_MISSING` |
| Wrong period | 10/10 | `L1B_PERIOD_WORD_MISSING` |
| Wrong unit | 10/10 | `L1B_UNIT_MISMATCH` |
| Wrong source | 10/10 | 5 `L1B_UNKNOWN_METRIC`, 5 `L1B_UNKNOWN_FACT` |
| Wrong direction | 10/10 | `L1B_DIRECTION_MISMATCH` |

Every failure, so nothing hides behind the totals. The planted set had no miss. These 7 Wonder first drafts failed:

- 2011-01-03, 2012-02-06, 2012-04-30: a claim that only restated the commitment, with no evidence (`L1B_CLAIM_WITHOUT_EVIDENCE`). Repaired.
- 2011-07-04: a claim that wrote a number and cited no metric. Repaired.
- 2012-08-06: one claim citing two metrics that aren't in one series (`L1B_TOO_MANY_METRICS`). Repaired.
- 2011-12-12: every claim had the same id, which the checker refuses as input, and the claims cited no metric. Repaired.
- 2011-01-24: the first draft wrote a number and cited no metric; the repair gave both claims the same id, which the checker refuses as input, so this week still failed. Checked separately with their own ids, both repaired sentences pass. My prompt never says ids must differ. I didn't change it after the run, so these numbers stand for the prompt I froze.

The raw drafts, codes and timings are in [evals/domains_results/bikes-wonder.jsonl](../evals/domains_results/bikes-wonder.jsonl), and the planted results in [evals/domains_results/bikes-planted.json](../evals/domains_results/bikes-planted.json).

## Pack 2: home energy, run cold

The second pack, [examples/domains/energy/pack.json](../examples/domains/energy/pack.json), reads one house's appliance and light logs from the UCI Appliances Energy Prediction dataset (CC BY 4.0), one row every 10 minutes from January to May 2016. It needed a JSON file, a three-column extract of the data and its own small oracle, [evals/domains_oracle_energy.py](../evals/domains_oracle_energy.py). It needed no change under `framework/`: `git diff ffdd615 9685756 -- framework/` is empty.

| Part | What it says |
| --- | --- |
| Goal | Notice the weeks when the appliances run heavy, before the bill does. |
| Commitments | `inspect-appliances` when `heavy_days` is at least 3; `keep-monitoring` when it is at most 2 |
| Signals | `Appliances` and `lights` from the extract |
| Metrics | high use intervals per day (appliances above 100 Wh in a 10-minute interval); light intervals per day (lights above 0 Wh); high use intervals for the week; heavy days (days with more than 36 high use intervals) |
| Identity | every day of a week has exactly 144 rows |
| Source | three columns cut from `energydata_complete.csv`, with the command and both hashes in [ATTRIBUTION.md](../examples/domains/energy/ATTRIBUTION.md) |

I ran it cold: no development week and no prompt change. The data has 18 complete Monday weeks, so all 18 are evaluation weeks with one control each, and the bar for headline wording scales to 17 of 18 controls. The adapter lists one more week, starting 2016-01-11, and refuses to build it, because its first day has 42 of 144 rows.

| Measure | Result |
| --- | --- |
| Planted errors caught | 60/60 |
| Correct controls accepted | 18/18 |
| Correct twins accepted | 60/60 |
| Wonder first drafts accepted | 15/18 |
| Accepted after one repair | 1/18 |
| Still failing after the repair | 2/18 |
| Transport errors | 0/18 |
| Commitment matches the oracle | 18/18 |
| Latency, first attempt (median) | 11.8 s |
| Latency, slowest week in total | 32.8 s |

Each planted kind was caught by the same check as in the bikes pack. The failures:

- 2016-02-08: "the heavy days is 6 week of 2016-02-08" failed with `L1B_UNIT_MISMATCH`. The number was right: the checker read the "week" right after "6" as its unit. That is a true value the checker rejected. Repaired.
- 2016-03-07: the first draft stated 3 and 211 but cited only a fact, no metric; the repair wrote one claim, "Commitment: inspect-appliances", with no evidence. Still failing.
- 2016-04-11: both drafts cited nothing, no metric and no fact id, though the first wrote the fact's name in its text. Still failing.

The raw drafts are in [evals/domains_results/energy-wonder.jsonl](../evals/domains_results/energy-wonder.jsonl), and the planted results in [evals/domains_results/energy-planted.json](../evals/domains_results/energy-planted.json).

## What this shows, and what it doesn't

- The planted errors are aimed: each kind is a shape the checker says it checks, so catching all of them is what I expected. It is not accuracy on surprises. My blind test is in [TRUST.md](TRUST.md): on 40 cases written by an outside model from the public docs, the checker stopped 17 of 20 false sentences and passed 18 of 20 true ones.
- Planted errors are not natural model failures. The natural failures are the Wonder drafts listed above.
- Historical public data is not a user. Nobody at Capital Bikeshare or in that house used this. It shows the path runs on someone else's records, with answers anyone can recompute.
- The checker checks numbers, sources, labels, units, periods and direction against the declared records. It does not check that a sentence is true.
- Choosing the right commitment is checked by a plain rule in the runner, such as busy days of at least 1, not by the checker.

## Limits

Found before the runs:

- The unit check knows only time, percent and magnitude words, so "5,000 kilometres" passes against a count, and so would "48 Wh". I drew the planted unit words from words it knows, and a test pins the kilometres case.
- Label words match exactly: "busy day" doesn't name the metric "busy days".
- A threshold declared as its own labelled metric made the natural sentence "above the threshold" fail, so neither pack declares one. The threshold lives in the metric's definition.
- On the two development weeks, Wonder's first drafts quoted my own fact, "A busy day is a day with more total rentals than the declared threshold.", and the checker failed it, because "a day" reads as a quantity. The source fact failed too, on the number in "CC BY 4.0". I reworded both facts and added `lint`, which catches this before a model runs. No evaluation week had run.
- My first freeze had two duplicate direction cases. I made the generator draw distinct cases and froze again before any score ran. The 20 controls didn't change.

Found in the runs:

- No draft cited a wrong value: all 61 numbers in the 48 drafts equal a value in that week's records. The 10 failed first drafts failed on citing and form: 5 wrote numbers without citing the metric, 3 only restated the commitment, 1 gave every claim the same id, 1 put two metrics in one claim, and 1 was the true value the unit check misread (one draft did two of these). My prompt already says every number must be a cited metric's value; it says nothing about restating the commitment or about ids.
- A number written right before the period phrase, as in "is 6 week of 2016-02-08", reads as "6 weeks" to the unit check.

## Reproduce

```sh
uv run python evals/domains_oracle.py examples/domains/bikes/data/day.csv examples/domains/bikes/data/hour.csv --threshold 7000 --windows 2012-06-11
uv run python evals/domains.py score --pack examples/domains/bikes/pack.json --cases evals/domains_cases/bikes.json --out /tmp/bikes-planted.json
uv run python evals/domains.py summary --score evals/domains_results/bikes-planted.json --wonder evals/domains_results/bikes-wonder.jsonl --expected examples/domains/bikes/expected.json
uv run python evals/domains.py summary --score evals/domains_results/energy-planted.json --wonder evals/domains_results/energy-wonder.jsonl --expected examples/domains/energy/expected.json
uv run pytest tests/test_domains_*.py -q
```

`wonder` reruns the real proposals and needs Muse Code on a subscription. Model output varies from run to run, so a rerun gives new drafts, not these.

## Attribution

Fanaee-T, H. (2013). Bike Sharing [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5W894. CC BY 4.0.

Candanedo, L. (2017). Appliances Energy Prediction [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5VC8G. CC BY 4.0.
