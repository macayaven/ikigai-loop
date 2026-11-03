# Gate held-out set v1: results

I scored the frozen gate set once, on the commit the live cards moved to
on Nov 2 at 23:29.

- Scored commit: `3e31338bf1ede702d82d94aa4dd1ec0851ef557b`
- Gate files sha256, as stamped by the runner: `f204fa5813f75893e3b1400d49193ca4350a760d48c9a9e0ba522ea96662e226`
- Input sha256: `aa927912bae204a44a4c906387ca70e26fd5c8936c071653470482028af430cf`
- Run on Nov 2 at 23:30 CET.

On that commit the repository's gate identity tool gives gate commit
`41b686d`, gate `2f443fbbc8dd` and closure `907b228d92cd`, the identity
the live cards' gate is known by elsewhere in the docs. The gate files on
that commit are byte-identical to the ones at the freeze commit's parent,
`aa3c0e8`, so the registered precondition held.

## Counts

A sentence the gate let through counts as PASS, a stopped one as STOP, and
a raise would count apart as no verdict. `predicted_passes` holds the
expected verdict, so predicted/actual agreement is the number of correct
verdicts: 37 of 40.

| outcome | count |
|---|---|
| true pass | 18 |
| true stop | 19 |
| false pass (a false sentence let through) | 1 |
| false stop (a true sentence stopped) | 2 |
| no verdict | 0 |

By kind: since_last 4 of 4 stopped, negation 4 of 4, period 3 of 3,
mislabelled_metric 3 of 3, invented_fact 3 of 3, unit 2 of 3, and 18 of 20
true sentences let through.

## Misses

| id | kind | gate did | codes | author's why |
|---|---|---|---|---|
| G18 | unit | let through | none | The calendar's 6.5 is measured in hours, not minutes. |
| G23 | true | stopped | L1B_DIRECTION_MISMATCH | Existing fact f2 establishes that prior's programming total exceeds last's. |
| G25 | true | stopped | L1B_NUMBER_WITHOUT_METRIC_REF | The consecutive period counts sum to 3 + 1 + 0 = 4. |

G18 is a false sentence the gate let through: the claim says 6.5 busy
minutes while the record measures 6.5 busy hours. G23 is a true sentence
the gate stopped: the records support that prior programming exceeded
last, and the gate stopped it with `L1B_DIRECTION_MISMATCH`. G25 is a
true sentence the gate stopped: the three period counts sum to 4, and the
gate stopped it with `L1B_NUMBER_WITHOUT_METRIC_REF`.

What the misses have in common: all three turn on how a quantity is
worded. G18 names a unit word beside its number, and the records refute
the sentence: the calendar's 6.5 is hours, not minutes, so a false claim
got through on a missed unit. G23 compares two periods, and G25 states a
total summed across three periods: in each of those two cases the records
support the sentence and the gate read it otherwise, stopping a true claim
over its wording.

`round-3.adjudicated.json` holds the verdicts the registered rule implies,
18 `not_false` and G18 `real_hole`, with no ruling beyond the author's
labels.

## Second run

I disclose that the registered rule said the runner runs once. After I
added the adjudication file, the repository's staleness test required
`round-3.results.json` to match a fresh regeneration, so I ran the runner
a second time on `round-3.json`, without `--write-frozen`, on this branch,
whose gate files are byte-identical to those at `3e31338`. I checked that
its 40 rows are identical to the scored run's rows in
`round-3.frozen.json`, and that it only added an empty review list. I left
`round-3.frozen.json`, the scored record with its stamps, unchanged. I
confirm the second run changed no verdict.
