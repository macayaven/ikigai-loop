## Goal

Ticket 15a — learner core. After this ticket, `framework/learner/` holds a pure package that turns my card rulings into per-slot preference counts, scores four predictors before each posterior-moving ruling, ranks my own commitments for the proposal prompt, and answers a prior question on simulated rulings: getting a known preference back from simulated rulings (Wilson & Collins 2019). The package fits no real data. It reads no real rulings. A later ticket builds the proof harness (R2–R4). Randomization is out of scope and starts after the hackathon. Ticket T10 merged to main while this ticket was open, and T9, T11, T12 and T13 run on other branches. Commitment ids enter as plain strings and the package imports nothing from any of those tickets.

Grounding, checked 2026-11-01 in this plan session: I read `AGENTS.md:1` first (typed manifests only, hidden criteria stay outside the repo and no agent reads that path, `make check`, one worktree per ticket, never commit or push unless asked in the session, stop after the plan for approval). I then read `docs/plans/008-briefing-gate.md:1` for the plan shape used here. Code claims below are checked against the tree and cited as `file:line`.

- `framework/schemas/base.py:11`: `SchemaModel` is frozen with `extra="forbid"` and `populate_by_name=True`.
- `framework/schemas/events.py:9`: `NonEmptyStr = Annotated[str, Field(min_length=1)]`. Pydantic `AwareDatetime` is already the house type for aware slots, as in `framework/briefing/schemas.py:122`.
- `framework/schemas/export_schemas.py:66`: `EXPORTED_MODELS` is one tuple, appended to by ticket, with `schema_text()` at line 123 and `find_drift()` at line 137. On the base the briefing block ends the tuple, so the learner block goes after it as one block.
- `tests/test_schemas_export.py:12`: the committed set under `schemas/` must equal the exported set exactly, and drift names the model. Appending 8 models therefore means 8 new generated files and no hand edits.
- `framework/briefing/gate.py:504`: the slot check is `allowed_start <= local < allowed_end`, start-inclusive and end-exclusive. `bucket_for` copies that half-open convention.
- `framework/briefing/schemas.py:43`: briefing models sit on `SchemaModel`, use `AwareDatetime`, and validate finite floats with `math.isfinite`. The learner follows the same pattern.
- `framework/blocks/__main__.py:48`: the CLI shape is `main(argv: list[str] | None = None) -> int` with `raise SystemExit(main())` at line 66. `framework/learner/__main__.py` mirrors it.
- `pyproject.toml:27`: pyright `strict = ["framework"]`, so `framework/learner/` is already under strict checking with no config change. Project dependencies at lines 6–12 have no scipy and no stats package.
- `uv.lock`: `grep -c '"scipy"' uv.lock` is `0` in this tree, and `grep -c scipy uv.lock` is also `0`. That fact drives the exact-interval decision in §7 of the brief and in Approach below.
- `Makefile:3`: `make check` is ruff check, ruff format check, pyright, pytest, then gitleaks. Acceptance tests use it as the final gate.
- Current branch is `t15-learner`, rebased on `main` at `8419879`. `framework/learner/` does not exist yet. The `## Ticket 10` entry in `CONTRIBUTIONS.md` ends just before the `AI assistance outside the Muse family` section at `CONTRIBUTIONS.md:135`, which fixes where the 15a entry goes: after the Ticket 10 entry and before that section.
- The path in `HIDDEN_CRITERIA_DIR` was never opened in this plan session, and no file outside this repository was read.

Text rules bind every file this ticket writes, the plan included. I state them here without reproducing the banned strings themselves, because reproducing them in the plan would break the rule in the plan:

- The banned-word list is the list in the brief's Text rules. It binds code, identifiers, file names, tests, docstrings, this plan, the session note and `CONTRIBUTIONS.md`. Where a check must search for one of those strings, the command builds the pattern so the literal string never sits in any repo file (see AT-BAN).
- The banned noun from that list is also the target of a T10 acceptance grep over `framework tests evals`. T10 has merged, and that grep must keep returning nothing. The verb form is fine, and the simulation function is named `recover`.
- Synthetic ids only: commitments `b-1`, `b-2`, `d-1`, `d-2`, cards `card-001`, simulated commitments `sim-builder`, `sim-disconnect`. No real commitment wording, no names, no hosts, no private paths in any file.
- No language from the health domain. Prose that speaks as a person speaks as me, Carlos, first person, concrete, with no empty superlatives.

## Success Criteria

- **Package.** New package `framework/learner/` with exactly `__init__.py`, `schemas.py`, `beta.py`, `policy.py`, `scoring.py`, `simulate.py`, `__main__.py`. Pure: standard library and pydantic only, plus `SchemaModel` from `framework/schemas/base.py` and `NonEmptyStr` from `framework/schemas/events.py`. No clock read, no env read, no network, no model call anywhere in the package. Only `simulate.py` imports `random`, and only through its own seeded `random.Random` instance. Only `__main__.py` touches the filesystem, and only for `--json`. Pyright strict passes on the package with no config change.
- **Schemas.** Every model in `schemas.py` sits on `SchemaModel` (frozen, extra-forbid). The 8 wire models (`Proposal`, `Ruling`, `BucketState`, `CommitmentState`, `PredictorScore`, `ScoreEntry`, `PickLogEntry`, `PolicyState`) join `EXPORTED_MODELS` as one appended block; their 8 JSON Schemas are generated, never hand-edited, and the existing drift test passes. Report and simulation types are not exported.
- **Buckets and update.** `initial_state()` returns the Day 0 policy. `bucket_for` maps a wall-clock time to `afternoon`, `evening` or `night` on half-open bounds and raises `ValueError` outside them. `update` is pure, never mutates its input, and follows the counting table in Approach row for row, one test per row. One card moves the posterior at most once. Only a real choice between two offered proposals moves the posterior.
- **Scoring.** `predict` sees state and bucket only, never the ruling. `score_before_update` logs one `ScoreEntry` only when the ruling would move the posterior. `observe` is `update` after `score_before_update` and is the one call the live loop makes. `replay` folds `observe` and gives byte-identical `state_json` in any process, under any `PYTHONHASHSEED`, and after a JSON round trip of the state at any prefix. `score_report` gives per-predictor means and call counts.
- **Ranking and prompt data.** `rank_commitments` is deterministic, independent of candidate order, and carries the pinned reason strings. `policy_block` returns one deterministic compact JSON string of numbers and candidate ids only (D-25); same inputs give the same bytes, and candidates stay in rank order in the list. `policy_diff` lists exact leaf differences between two states, sorted by path.
- **Exact intervals.** `beta.py` computes the equal-tailed 95% interval with exact integer work: no scipy, no normal approximation, byte-stable across platforms, matching the frozen quantile references within 1e-9.
- **Known-preference simulation.** `recover` and `recover_table` feed simulated rulings through the real `update`, never a parallel formula. The frozen exact grid in Approach is the correctness oracle; simulated cells must land within the stated tolerance of it. Interval width is reported alongside coverage, because coverage alone cannot show what a small `n` cannot show.
- **CLI.** `python -m framework.learner recover --seed 1` prints the full table, first line stating the data is simulated. Same seed gives same bytes on stdout and in the `--json` file. No timestamps, paths or durations in any output. The default full table runs in under 60 s on a laptop, measured and recorded in the session note.
- **Limits stated, not hidden.** A card nobody tapped produces no ruling, so `offered` means "shown on a card that got at least one ruling". That limit is written here for T13. The meaning of `n_cards` is written here, in the JSON and under the printed table. Ranking uses per-commitment counts across all slots, so nobody can claim a rank is per bucket.
- **Bookkeeping.** Tests are written first and fail on the base tree at collection. `docs/sessions/015-learner.md` and the `CONTRIBUTIONS.md` Ticket 15a entry exist in the shapes pinned under Files. `make check` is green. One commit, made only in a later session that is explicitly asked to commit. Not pushed.

## Approach

### Binding decisions

Every pin in the brief is copied here as binding on the implementer. Where the brief leaves a shape open, I decide it here and give the reason. Numbered decisions D-1 to D-25 are the full list; nobody re-decides them in the session.

- **D-1 Package boundary (brief pin).** `framework/learner/` holds exactly the 7 files named in Success Criteria. Imports allowed: standard library, pydantic, `SchemaModel` (`framework/schemas/base.py:11`) and `NonEmptyStr` (`framework/schemas/events.py:9`). No import from T9–T13 code, including T10's, which merged while this ticket was open. Reason: the learner must stand alone against in-flight branches, and commitment ids as plain strings are the only contract those branches need.
- **D-2 Purity (brief pin).** No clock, no env, no network, no model call. Only `simulate.py` may import `random`, only as a seeded `random.Random` instance owned by that call. Only `__main__.py` may touch the filesystem, only to write the `--json` path. Reason: replay must be byte-identical in any process, so nothing outside the inputs may leak in.
- **D-3 Dependencies (brief pin).** `pyproject.toml` and `uv.lock` stay untouched. A perceived need for a new dependency stops the ticket for amendment. Reason: the interval math in D-18 is designed to need nothing beyond the standard library, and a silent dependency would break that claim.
- **D-4 All learner data types are `SchemaModel`s in `schemas.py`.** That includes the non-exported types (`Prediction`, `RankedCommitment`, `PolicyChange`, `ScoreReport`, `PredictorReport`, `RecoverCell`, `RecoverTable`). Reason: one validation and serialization story for the whole package, `model_dump(mode="json")` for the CLI and for `policy_diff`, and no second dataclass dialect to review. Only the 8 named wire models are exported; see D-7.
- **D-5 Dicts inside frozen models are copied, never mutated.** `update`, `score_before_update`, `observe` and `replay` build the next state with `model_copy(update=...)` over shallow-copied dicts and appended tuples. Reason: `SchemaModel` is frozen at `framework/schemas/base.py:12`, but a `dict` field stays mutable underneath, so purity needs explicit copies. The brief's budget note pins the same choice: copy shallowly rather than re-validate, because state grows only through `cards` and `pick_log`.
- **D-6 `rulings_seen` rises exactly once per `update` call.** The counting table's `+1` column is that one rise, read once per call, not once per row that matches. A first sighting, a decisive tap, a `wrong` tap and a duplicate tap each add 1 in total. Reason: any other reading double-counts a first decisive ruling, and the table's duplicate row only makes sense if the rise is per call.
- **D-7 Export block (brief pin).** `Proposal`, `Ruling`, `BucketState`, `CommitmentState`, `PredictorScore`, `ScoreEntry`, `PickLogEntry`, `PolicyState` are appended to `EXPORTED_MODELS` in `framework/schemas/export_schemas.py:66` as one block at the end of the tuple, after the briefing block. `RecoverCell`, `RecoverTable` and the report types are not exported. Reason: another ticket appends to the same tuple, and one learner block at the end keeps that merge to one hunk. The 8 generated files are `schemas/Proposal.json`, `schemas/Ruling.json`, `schemas/BucketState.json`, `schemas/CommitmentState.json`, `schemas/PredictorScore.json`, `schemas/ScoreEntry.json`, `schemas/PickLogEntry.json`, `schemas/PolicyState.json`.
- **D-8 The label is data (brief pin).** A proposal's `label` is `A` or `B` as shown on the card. Label A is not assumed to be Builder. Scoring and counting resolve the chosen profile through the labelled proposal, so a card that shows Disconnect first or alone still scores correctly. Reason: T12 decides card layout; the learner must not bake in a layout guess. Two tests pin this: a lone Disconnect proposal labelled A takes `taken` and leaves the posterior alone, and a two-proposal card with A = Disconnect and B = Builder moves `beta` on target A.
- **D-9 Fixed prior (brief pin).** The prior is Beta(1, 1) everywhere: bucket posteriors start at `alpha = beta = 1`, and `pooled_rate` uses the same `(k + 1) / (n + 2)`. Alpha and beta are stored as integers; means are derived, never stored. Because both are at least 1, no posterior mean is ever exactly 0 or 1, and a state JSON with `alpha: 0` fails validation. Reason: one prior story across learner, comparator and interval keeps the three numbers comparable.
- **D-10 Only a real choice moves the posterior (brief pin).** A posterior step needs two proposals, an undecided card, and target A or B. One-proposal cards, `neither`, `wrong`, `why` and duplicates never move it. Reason given in the brief, kept here: a repeat step on one card would inflate the posterior, and a lone proposal carries no choice between my two profiles.
- **D-11 Offered means ruled-on (brief pin, stated as a limit).** A card nobody tapped produces no ruling, so `offered` counts cards that got at least one ruling, not cards that were shown. Reason: the learner only ever sees rulings. T13 owns shown-but-untapped cards and must not read `offered` as impressions.
- **D-12 Canonical bytes (brief pin).** `state_json(state)` is `json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))` and nothing else. `replay` byte tests and `policy_diff` both go through it. Reason: one serialization means one thing to compare, on macOS and Linux alike.
- **D-13 Floats are rounded before they are logged (brief pin).** Every float entering a `PredictorScore` passes through `round(x, 12)` first. Brier uses `d * d`, never `**`. Log loss uses the natural log, computed from exact fractions where possible so `1 - p` keeps precision. Reason: `math.log` can differ in the last bit across platforms, and frozen bytes must hold on both.
- **D-14 The hard vote's log loss is clipped, its Brier is not (brief pin).** For `majority` only, log loss is computed on the vote clipped to `[0.01, 0.99]`; its Brier uses the unclipped vote. The learner and `pooled_rate` never reach 0 or 1 under D-9, and a test pins that after 2000 one-sided rulings. Reason: JSON cannot carry infinity, and an unclipped hard vote hits infinite log loss on its first miss. Reading rule, stated here for R8: the majority's log loss is dominated by that clipping constant, and its Brier is the number to read.
- **D-15 `pooled_rate` stays as the third comparator (brief pin, my addition in the brief).** A hard vote is a poor probability forecast, so beating it says little. `pooled_rate` shows whether splitting by bucket pays for itself. Its side always equals the majority vote, and in a run with all rulings in one bucket it equals `learner` exactly; a test pins that equality. Reason: without it, a bucket split could look good against a straw comparator while adding nothing over one pooled count.
- **D-16 Ranking counts are across all slots (brief pin).** `rank_commitments` sorts on per-commitment `offered` / `taken` / `declined` totals. The `bucket` argument is recorded on each `RankedCommitment` and changes nothing about the order. Reason: per-bucket commitment counts would be too thin to rank on at this scale, and the plan says so plainly so nobody later claims a per-bucket rank.
- **D-17 Reason strings are pinned (brief pin).** The five shapes in the Ranking subsection are exact, with the rate printed as a fraction such as `3/4`. Reason: the strings explain a rank to me in the prompt path, and a test must be able to assert them word for word.
- **D-18 Exact intervals, no approximation (brief pin).** With integer `alpha, beta >= 1`, the regularized incomplete beta is a finite binomial sum, evaluated in exact integer work and bisected over `k / 2^64`. No scipy (absent from the lock, checked above), no `statistics.NormalDist`. Reason, with the brief's measurements kept: at true_p = 0.6, n = 5 the normal interval's fixed-p coverage is 0.8352 against 0.9898 for the exact interval, and at Beta(6, 1) its upper limit goes above 1. An approximation that fails at exactly the small `n` this ticket studies is not a shortcut, it is a wrong answer.
- **D-19 Simulation goes through the real `update` (brief pin).** No parallel counting formula anywhere in `simulate.py`. Ruling objects are built once per `recover` call and reused across sims, and `score_before_update` is not called there. Reason: the known-preference test only means something if the code under test is the live counting code; the reuse and the skipped scoring are the speed choices that keep the default table under its budget.
- **D-20 One seeded generator per cell (brief pin).** Each `recover` call makes one `random.Random(f"{seed}:{true_p}:{n_cards}")` and calls only `.random()` on it. Reason: a cell must not depend on which other cells ran, and `.random()` is the one method whose stream is stable across Python versions. The seed string uses the default `str()` of the values as passed, so `0.7` in the call is `0.7` in the seed.
- **D-21 Coverage is read with width, never alone (brief pin).** `RecoverCell` carries `mean_interval_width` as a fourth result beyond the three first asked for, and it stays. Reason: a wide enough interval always covers, so coverage alone cannot show what `n` cannot show.
- **D-22 Interval coverage has three readings (brief pin).** A credible interval is not a confidence interval: exact coverage at a fixed true_p wanders on this grid (the frozen cells run from 0.9185 to 0.9898), and it is 95% only on average over the prior. Tests therefore check the prior-averaged reading, the fixed-p reading against enumeration, and a stated floor. Reason: pinning one simulated coverage number to 0.95 would fail a correct interval.
- **D-23 The reading note is fixed text.** The note pinned in the `n_cards` subsection appears word for word in the `RecoverTable` JSON, under the printed table, and in the plan. Reason: the same caution must travel with the numbers wherever they are read, including by me in three days.
- **D-24 No new file outside the ticket list.** Every new file belongs to Ticket 15a and is named under Files. A need that falls outside that list stops the ticket for amendment. Reason: AGENTS.md requires every new file to belong to a ticket, and T9–T13 branches must merge against a known file set.
- **D-25 `policy_block` returns a string.** `policy_block` returns `json.dumps(block, sort_keys=True, separators=(",", ":"))`: one deterministic compact JSON string. It stays pure. Reason: T11 takes the policy block as an opaque string argument and imports nothing from this package, so the string is the contract.

### 1. Schemas (`schemas.py`)

All models on `SchemaModel` (`framework/schemas/base.py:11`). Types first, then models, field for field.

```python
Bucket = Literal["afternoon", "evening", "night"]
BUCKETS: tuple[Bucket, ...] = ("afternoon", "evening", "night")
ProfileId = Literal["builder", "disconnect"]
Target = Literal["A", "B", "neither", "wrong", "why"]
```

- `Proposal`: `label: Literal["A", "B"]`, `profile_id: ProfileId`, `commitment_id: NonEmptyStr`, `policy_pick: NonEmptyStr`, `policy_alternative: NonEmptyStr | None = None`. `policy_pick` is position 1 of `rank_commitments` for this profile when the card was built; `policy_alternative` is position 2, or `None` when that profile had one candidate.
- `Ruling`: `card_id: NonEmptyStr`, `slot: AwareDatetime` (the card's slot, passed by the caller), `bucket: Bucket`, `proposals: tuple[Proposal, ...]`, `target: Target`. Model validators: 1 or 2 proposals; one proposal must have label A; two proposals must have labels A and B, different `profile_id` values and different `commitment_id` values; target B needs a proposal labelled B, so target B on a one-proposal card is a validation error.
- `BucketState`: `alpha: int = 1` (ge 1; equals 1 + real choices of Builder in this bucket), `beta: int = 1` (ge 1; equals 1 + real choices of Disconnect), `neither: int = 0`, `wrong: int = 0`, `why: int = 0`, `single_taken: int = 0` (each ge 0). Integers by D-9.
- `CommitmentState`: `profile_id: ProfileId`, `offered: int` (ge 0), `taken: int` (ge 0), `declined: int` (ge 0), `last_offered_slot: AwareDatetime`. Model validator: `taken + declined <= offered`. A record exists only once a commitment has been offered.
- `PredictorScore`: `prediction: float`, `brier: float`, `log_loss: float`. Each is finite (`math.isfinite`, the pattern at `framework/briefing/schemas.py:52`) and `prediction` lies in [0, 1].
- `ScoreEntry`: `card_id: NonEmptyStr`, `bucket: Bucket`, `outcome: Literal[0, 1]` (1 means Builder was taken), `learner: PredictorScore`, `always_half: PredictorScore`, `majority: PredictorScore`, `pooled_rate: PredictorScore`.
- `PickLogEntry`: `card_id: NonEmptyStr`, `slot: AwareDatetime`, `bucket: Bucket`, `profile_id: ProfileId`, `label: Literal["A", "B"]` (the label shown on the card), `offered: NonEmptyStr` (the commitment on the card), `pick: NonEmptyStr`, `alternative: NonEmptyStr | None = None`.
- `PolicyState`: `preference: Literal["builder_over_disconnect"] = "builder_over_disconnect"` (a constant, so the JSON says what alpha and beta mean), `rulings_seen: int = 0` (ge 0), `duplicates: int = 0` (ge 0), `buckets: dict[Bucket, BucketState]`, `commitments: dict[NonEmptyStr, CommitmentState]`, `cards: dict[NonEmptyStr, Literal["A", "B", "neither"] | None]`, `score_log: tuple[ScoreEntry, ...] = ()`, `pick_log: tuple[PickLogEntry, ...] = ()`. A `cards` key present means the card has been seen; its value is the decisive target or `None` if none yet. Model validator: `buckets` holds exactly the three `BUCKETS` keys.

Non-exported types, also in `schemas.py` by D-4:

- `Prediction`: `learner: float`, `always_half: float`, `majority: float`, `pooled_rate: float`, each finite and in [0, 1]. Returned by `predict`; carries no ruling data.
- `RankedCommitment`: `commitment_id: NonEmptyStr`, `position: int` (ge 1, 1-based), `role: Literal["pick", "alternative", "other"]` (`pick` at position 1, `alternative` at 2, `other` after), `profile_id: ProfileId`, `bucket: Bucket`, `offered: int`, `taken: int`, `declined: int`, `smoothed_rate: float` (display only), `reason: str`.
- `PolicyChange`: `path: str`, `kind: Literal["added", "removed", "changed"]`, `before: object = None`, `after: object = None`. For `added`, `before` is `None`; for `removed`, `after` is `None`; the `kind` field carries the distinction when a leaf value is itself `None` (a `cards` entry).
- `PredictorReport`: `mean_brier: float | None`, `mean_log_loss: float | None`, `correct: int`, `wrong: int`, `no_call: int`. `ScoreReport`: `n: int`, `learner: PredictorReport`, `always_half: PredictorReport`, `majority: PredictorReport`, `pooled_rate: PredictorReport`. `correct` counts calls on the right side of 0.5, `wrong` counts calls on the wrong side, `no_call` counts predictions of exactly 0.5; the three sum to `n` per predictor.
- `RecoverCell`: `true_p: float`, `n_cards: int`, `n_sims: int`, `seed: int`, `correct_side: float | None`, `mean_absolute_error: float`, `coverage: float`, `mean_interval_width: float`.
- `RecoverTable`: `label: Literal["simulated"] = "simulated"`, `seed: int`, `n_sims: int`, `note: str`, `cells: tuple[RecoverCell, ...]`. The `note` value is the fixed text in the `n_cards` subsection.

### 2. Buckets and `update` (`policy.py`)

- `initial_state() -> PolicyState`: the Day 0 policy. `preference` at its constant, both counters 0, one default `BucketState` per bucket in `BUCKETS`, empty `commitments` and `cards`, empty logs.
- `bucket_for(local_time: datetime.time) -> Bucket`: half-open bounds copying the gate convention at `framework/briefing/gate.py:504`: [13:00, 17:00) is `afternoon`, [17:00, 21:00) is `evening`, [21:00, 23:30) is `night`. Anything else, 23:30 included, raises `ValueError`. The function reads only the wall-clock fields of the value it is given (`hour`, `minute`, `second`, `microsecond`), never a tz-aware comparison, so a `time` carrying tzinfo cannot raise a comparison error.
- `update(state: PolicyState, ruling: Ruling) -> PolicyState`: pure; returns a new state; never mutates its input (D-5). Exactly one `rulings_seen` rise per call (D-6). A commitment id already recorded under another profile raises `ValueError`, checked before any counter moves. Counting table, one test per row:

| Ruling | `rulings_seen` | Commitment counters | Posterior | Other |
|---|---|---|---|---|
| Any ruling, first time this `card_id` is seen | +1 | each proposal's `offered` +1, `last_offered_slot` = max(previous, `slot`) compared as instants, one `PickLogEntry` per proposal | none | `cards[card_id] = None` before the rows below apply |
| A or B on an undecided two-proposal card | +1 | chosen `taken` +1, other `declined` +1 | chosen profile builder: `alpha` +1; disconnect: `beta` +1 | `cards[card_id] = target` |
| A on an undecided one-proposal card | +1 | `taken` +1 | none | bucket `single_taken` +1, `cards[card_id] = "A"` |
| neither on an undecided card | +1 | every proposal's `declined` +1 | none | bucket `neither` +1, `cards[card_id] = "neither"` |
| wrong | +1 | none beyond first sighting | none | bucket `wrong` +1; the card stays undecided |
| why | +1 | none beyond first sighting | none | bucket `why` +1; the card stays undecided |
| A, B or neither on an already decided card | +1 | none | none | `duplicates` +1 |

Reading of the table, pinned so the tests have one target: "undecided" means the `card_id` is in `cards` with value `None` after the first-sighting row runs. A first sighting that is also decisive applies both its rows in one call. `wrong` and `why` on an already decided card add their bucket count and no duplicate count, because the duplicate row names only A, B and neither. So "why" then "A" on one card offers once and moves the posterior once; a double tap moves it once; "A" then "B" keeps the first (D-10). A commitment first offered by a card creates its `CommitmentState` with `offered = 1` and `last_offered_slot = slot`; `last_offered_slot` compares as instants, so equal instants in different offsets tie. For a decisive tap, the chosen and other commitments come from the ruling in hand, and the profile-consistency check runs against the records that ruling would touch. A later ruling on an already seen card must describe the same card: same `slot`, `bucket` and proposals, labels included, in the same tuple order. If it doesn't, `update` raises `ValueError` before any counter moves. Check it by building the `PickLogEntry` values this ruling would produce and comparing them with those logged for that `card_id`, scanning `pick_log` only when the card is already in `cards`, so the first-sighting path stays fast. Reason: a decisive tap on a commitment the first sighting never offered would count `taken` with no `offered`, and silently mix two cards.

- `state_json(state: PolicyState) -> str`: exactly `json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))` (D-12).

### 3. Scoring (`scoring.py`)

- `predict(state: PolicyState, bucket: Bucket) -> Prediction`: takes no ruling, so the prediction cannot see it. Four probabilities that Builder is taken, from state only:
  - `learner`: the bucket's `alpha / (alpha + beta)`.
  - `always_half`: 0.5.
  - `majority`: the plain hard vote across all buckets on real choices so far. With k = sum of (`alpha` - 1) and n - k = sum of (`beta` - 1) over the three buckets: 1.0 if k > n - k, 0.0 if k < n - k, 0.5 on a tie or with no data.
  - `pooled_rate`: `(k + 1) / (n + 2)`, the same uniform prior with buckets ignored (D-15).
- Scores: Brier is `(p - y)^2` computed as `d * d`; always 0.5 therefore scores exactly 0.25. Log loss is the natural log: `-ln(p)` if y = 1, else `-ln(1 - p)`. Counts k and n are integers, so each probability starts as an exact `Fraction`, Brier is exact in `Fraction`, and log loss takes `math.log` on the `Fraction` (or on `1 - p` as a `Fraction`) before the D-13 rounding. For `majority` only, the log-loss probability is clipped to `[0.01, 0.99]` first (D-14).
- `score_before_update(state: PolicyState, ruling: Ruling) -> PolicyState`: returns a new state with one `ScoreEntry` appended to `score_log`, predictions from the private helper `predict` also uses, so one formula serves both, outcome 1 if the labelled-chosen proposal's profile is builder else 0. It appends only if this ruling would move the posterior under D-10: a real choice (target A or B) on an undecided two-proposal card. Otherwise it returns the state unchanged. Calling it after `update` on the same card therefore logs nothing, and the prediction cannot leak the ruling through ordering. It changes no counter.
- `observe(state: PolicyState, ruling: Ruling) -> PolicyState`: `update(score_before_update(state, ruling), ruling)`. The one call the live loop makes.
- `replay(initial: PolicyState, rulings: Iterable[Ruling]) -> PolicyState`: a fold of `observe` in the given order. Same rulings give identical `state_json` in any process, under any `PYTHONHASHSEED`, and after a JSON round trip of the state at any prefix (`PolicyState.model_validate_json(state_json(state))` then continuing).
- `score_report(state: PolicyState) -> ScoreReport`: per predictor, `mean_brier` and `mean_log_loss` by `math.fsum` (`None` when n = 0), plus exact `correct` / `wrong` / `no_call` counts. This is what R8 reports.

Frozen scoring example, computed by hand from the table rules and checked against the brief's literals. Rulings in order, outcome 1 = Builder: (evening, 1), (evening, 1), (afternoon, 0), (evening, 0). Each row is the prediction made before that ruling:

| # | learner p, Brier, log loss | always_half Brier, log loss | majority p, Brier, clipped log loss | pooled_rate p, Brier, log loss |
|---|---|---|---|---|
| 1 | 1/2, 0.25, 0.69314718056 | 0.25, 0.69314718056 | 1/2, 0.25, 0.69314718056 | 1/2, 0.25, 0.69314718056 |
| 2 | 2/3, 0.111111111111, 0.405465108108 | 0.25, 0.69314718056 | 1, 0.0, 0.010050335854 | 2/3, 0.111111111111, 0.405465108108 |
| 3 | 1/2, 0.25, 0.69314718056 | 0.25, 0.69314718056 | 1, 1.0, 4.605170185988 | 3/4, 0.5625, 1.38629436112 |
| 4 | 3/4, 0.5625, 1.38629436112 | 0.25, 0.69314718056 | 1, 1.0, 4.605170185988 | 3/5, 0.36, 0.916290731874 |

Means (Brier, log loss): learner 0.293402777778, 0.794513457587; always_half 0.25, 0.69314718056; majority 0.5625, 2.478384472097; pooled_rate 0.320902777778, 0.850299345416. Tests carry these as literals after the D-13 rounding.

### 4. Ranking (`policy.py`)

`rank_commitments(state: PolicyState, profile: ProfileId, candidates: tuple[NonEmptyStr, ...], bucket: Bucket) -> tuple[RankedCommitment, ...]`. Deterministic, no randomness, independent of candidate order (D-16). Sort keys, in order:

1. Smoothed taken rate `(taken + 1) / (offered + 2)` descending, compared exactly as `Fraction`. A candidate with no record has zero counts, so a never-offered candidate sits at 1/2 and ties with a candidate at (1 taken, 2 offered).
2. Least recently offered first: a never-offered candidate is least recent of all; otherwise the earlier `last_offered_slot` wins, compared as instants, not strings.
3. Commitment id ascending by code point.

Duplicate candidates raise `ValueError`. A candidate recorded under another profile raises `ValueError`. An empty candidate tuple returns `()`. Each result carries its `profile_id` and `bucket` from the arguments, its counts from the record (zeros when none), `smoothed_rate` as the float of the exact fraction (display only), and a `reason` built against the next candidate in the final order:

- Higher rate than the next: `higher smoothed taken rate: 3/4 over 1/2` (own rate, then next rate, each as a reduced fraction).
- Tied rate, offered less recently than the next: `tied at 1/2 with b-2: less recently offered`.
- Tied rate, same last-offered instant as the next (both never offered counts as same): `tied at 1/2 with b-2: same last-offered slot, lower id`.
- Last of several: `lowest of the candidates: 1/3`.
- Only candidate: `only candidate: 1/2`.

Rates in reason strings are the reduced `Fraction` printed as `num/den`, or as the bare numerator when the denominator is 1. A `Proposal` built from a ranking copies position 1 into `policy_pick` and position 2 (when present) into `policy_alternative`; the pick log test asserts both land in `pick_log`.

### 5. Prompt block (`policy.py`)

`policy_block(state: PolicyState, bucket: Bucket, candidates: tuple[NonEmptyStr, ...]) -> str`, for one profile's candidates at a time. It stays pure. It builds the structure below and returns `json.dumps(block, sort_keys=True, separators=(",", ":"))`: one deterministic compact JSON string (D-25).

```python
{
    "bucket": {
        "builder_taken": alpha - 1,
        "disconnect_taken": beta - 1,
        "neither": ...,
        "wrong": ...,
        "why": ...,
        "posterior_mean": round(mean, 3),
    },
    "candidates": [
        {"id": ..., "rank": ..., "offered": ..., "taken": ..., "declined": ...},
        ...,
    ],
}
```

Counts come from the named bucket's `BucketState`; the mean is `alpha / (alpha + beta)` for that bucket. Candidates appear in rank order in the list. The profile for ranking is the one profile shared by the recorded candidates; candidates recorded under two different profiles raise `ValueError`. When no candidate has a record, ranking falls back to zero counts for all, which orders by candidate id. Every value in the block is a number or a candidate id: no reason strings, no datetimes, no `None`, no bucket or profile name as a value. Tests parse the returned string with `json.loads` for the recursive value walk and assert every string value is one of the candidates, and also freeze the exact string for a small state; same inputs give the same bytes. These numbers are not metrics: if Wonder repeats one in claim text, the gate rejects it for want of a metric ref, which is the correct outcome.

### 6. State diff (`policy.py`)

`policy_diff(a: PolicyState, b: PolicyState) -> tuple[PolicyChange, ...]`: the exact differences between two states, for the Day 0 policy against final policy comparison. Both states go through `state_json`, then `json.loads`, then flattening to leaf paths: dict keys join with `.` (`buckets.evening.alpha`, `commitments.b-1.taken`, `cards.card-001`), list items use `[i]` (`score_log[0].learner.brier`). A leaf is any non-dict, non-list value. A path only in `b` is `added`, only in `a` is `removed`, in both with unequal values is `changed`. Output sorts by path in code point order. Invariants, each with a test: the diff is empty if and only if `state_json(a) == state_json(b)`; swapping the arguments swaps before/after and added/removed; every field of `PolicyState` that differs shows up, checked field by field.

### 7. Exact intervals (`beta.py`)

Decision and reason, stated for the record (D-18): the lock has no scipy (grep count 0, checked in Goal); numpy reaches the lock only through inspect-ai, has no Beta quantile, and the package may use only the standard library and pydantic in any case. `statistics.NormalDist` would be a normal approximation, and the brief's outside-repo measurements show that approximation failing at this ticket's scale: fixed-p coverage 0.8352 against 0.9898 exact at true_p = 0.6, n = 5, and an upper limit above 1 at Beta(6, 1). With the fixed uniform prior and integer counts, alpha and beta are always integers at least 1, so the regularized incomplete beta is a finite binomial sum: I_x(a, b) = P(Binomial(a + b - 1, x) >= a). Evaluated in exact integer arithmetic at x = k / 2^64 and bisected over k, the quantile is correct to 2^-64 with no libm call, so bytes hold across platforms. The brief's outside-repo prototype matched scipy to 12 decimals and took 0.65 s for all 242 (a, b) pairs of the grid, memoized. Nobody in this repo runs scipy; the frozen references below are the oracle.

API:

- `beta_cdf(x: Fraction, a: int, b: int) -> Fraction`: the binomial sum above with `math.comb` integer coefficients and `Fraction` powers. `x <= 0` gives 0 and `x >= 1` gives 1. Non-integer or below-1 `a` or `b` raises `ValueError`; a `bool` is not an integer for this check.
- `beta_quantile(q: Fraction, a: int, b: int) -> float`: must not call `beta_cdf`; it uses the integer-only test below, memoized with `functools.cache`. Bisection keeps `lo = 0, hi = D` with the test false at `lo` and true at `hi` until `hi - lo == 1`, then returns `hi / D` as a float. `q <= 0` gives 0.0 and `q >= 1` gives 1.0. Same parameter validation as `beta_cdf`. `beta_cdf` with `Fraction` powers is fine for the tests, but bisecting 64 times over it for 242 (a, b) pairs is far too slow; the integer-only test below is the binding algorithm, which is what the 0.65 s prototype measured.

```python
D = 2**64


def _cdf_at_least(k: int, a: int, b: int, q: Fraction) -> bool:
    """True iff I_x(a, b) >= q at x = k / D, in exact integers. a, b >= 1."""
    n = a + b - 1
    m = D - k
    t, m_power, c = 1, 1, 1
    for j in range(n - 1, a - 1, -1):
        c = c * (j + 1) // (n - j)  # C(n, j) from C(n, j + 1)
        m_power *= m
        t = t * k + c * m_power
    return t * k**a * q.denominator >= q.numerator * D**n
```

- `credible_interval(alpha: int, beta: int) -> tuple[float, float]`: the equal-tailed 95% interval, `beta_quantile(Fraction(1, 40), alpha, beta)` and `beta_quantile(Fraction(39, 40), alpha, beta)`. Coverage is inclusive: `lo <= p <= hi`.

Frozen quantile references (q0.025, q0.975), computed with scipy outside this repo on 2026-11-01 and carried in tests as literals with that sentence attached: Beta(1,1) 0.025000000000, 0.975000000000; Beta(2,1) 0.158113883008, 0.987420882907; Beta(1,6) 0.004210744514, 0.459258126440; Beta(6,1) 0.540741873560, 0.995789255486; Beta(3,4) 0.118117248757, 0.777221904496; Beta(4,3) 0.222778095504, 0.881882751243; Beta(8,7) 0.288609400038, 0.769639458552; Beta(10,5) 0.418964742816, 0.872401570141; Beta(14,1) 0.768364238350, 0.998193219341; Beta(51,51) 0.403643067510, 0.596356932490; Beta(71,31) 0.603852871352, 0.781021273696; Beta(1,101) 0.000250639951, 0.035864620390. Tests assert each within 1e-9, plus closed forms for Beta(1, n) and Beta(n, 1), plus `beta_cdf(Fraction(hi)) - beta_cdf(Fraction(lo))` within 1e-9 of 0.95 for every (a, b) with a + b - 2 in {5, 13}.

### 8. Known-preference simulation (`simulate.py`)

`recover(true_p: float, n_cards: int, n_sims: int, seed: int) -> RecoverCell`:

- All `n_cards` rulings go to one bucket, `evening`. Slots sit at 18:00 on consecutive synthetic days starting 2026-01-01 in UTC, so `bucket_for(slot.time())` agrees with the ruling bucket. Card ids are `card-001`, `card-002`, and so on by position. Each ruling is a real choice between `sim-builder` (label A, profile builder) and `sim-disconnect` (label B, profile disconnect), target A when Builder is taken and B otherwise. Ruling objects are built once per call and reused across sims; each sim folds them through the real `update` from `initial_state()` (D-19).
- Randomness: one `random.Random(f"{seed}:{true_p}:{n_cards}")` per call (D-20); `rng.random() < true_p` means Builder is taken. Only `.random()` is called.
- Per sim, the posterior mean is the evening bucket's `alpha / (alpha + beta)` and the interval is `credible_interval(alpha, beta)` on that bucket. Results over sims:
  - `correct_side: float | None`: the share of sims whose posterior mean sits strictly on the correct side of 0.5 (above when true_p > 0.5, below when true_p < 0.5). `None` at true_p = 0.5. A mean of exactly 0.5, which happens at even n, counts as not correct.
  - `mean_absolute_error`: mean of |posterior mean - true_p| by `math.fsum`.
  - `coverage`: the share of sims with `lo <= true_p <= hi`.
  - `mean_interval_width`: mean of `hi - lo` (D-21).
- Validation: `0 < true_p < 1` (an equal-tailed interval can never cover exactly 0 or 1), `n_cards >= 1`, `n_sims >= 1`, else `ValueError`.

`recover_table(seed: int, n_sims: int, true_ps: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9), n_cards: tuple[int, ...] = (5, 13, 30, 100)) -> RecoverTable`: one `recover` per (true_p, n_cards) pair, true_p outer and n_cards inner, `label` fixed at `"simulated"`, `note` at the fixed text below.

What `n_cards` means, stated here, in the JSON and under the printed table (D-23). Fixed note text:

> n_cards is the number of real two-proposal choices fed to one posterior. Cards with one proposal, and neither, wrong or why taps, add none. My live run expects about 13 cards over three days, and Disconnect appears on at most 3 of the 5 slots a day, so at most about 9 of them can be real choices, split over three buckets. A live bucket's posterior will hold about 3 choices, so even the n = 5 row is optimistic for it. The n = 13 row is an upper bound on the pooled reading, available only if the preference does not vary by bucket.

Frozen exact grid, computed by enumeration outside this repo on 2026-11-01 and carried in tests as literals with that sentence attached. Each cell is (correct_side, mean_absolute_error, coverage, mean_interval_width) at (true_p, n_cards):

```text
(0.5, 5): (None, 0.133929, 0.937500, 0.627244)
(0.6, 5): (0.682560, 0.127808, 0.989760, 0.620604)
(0.7, 5): (0.836920, 0.120255, 0.969220, 0.600559)
(0.8, 5): (0.942080, 0.123163, 0.942080, 0.566739)
(0.9, 5): (0.991440, 0.114286, 0.918540, 0.518524)
(0.5, 13): (None, 0.097754, 0.977539, 0.466939)
(0.6, 13): (0.771156, 0.092461, 0.955290, 0.459225)
(0.7, 13): (0.937625, 0.091485, 0.972088, 0.435385)
(0.8, 13): (0.992996, 0.078483, 0.969965, 0.393082)
(0.9, 13): (0.999901, 0.070279, 0.965839, 0.327538)
(0.5, 30): (None, 0.067718, 0.957226, 0.333603)
(0.6, 30): (0.824631, 0.067180, 0.961577, 0.327388)
(0.7, 30): (0.983063, 0.063645, 0.929793, 0.308004)
(0.8, 30): (0.999769, 0.056556, 0.963861, 0.272738)
(0.9, 30): (1.000000, 0.044272, 0.974173, 0.214475)
(0.5, 100): (None, 0.039014, 0.943112, 0.191775)
(0.6, 100): (0.972901, 0.038369, 0.948118, 0.187990)
(0.7, 100): (0.999978, 0.036030, 0.949558, 0.176150)
(0.8, 100): (1.000000, 0.031622, 0.940520, 0.154416)
(0.9, 100): (1.000000, 0.024034, 0.936398, 0.117443)
```

Budget: the default full table (5 true_p values × 4 n_cards values × 2000 sims) runs in under 60 s on a laptop, and `recover(0.7, 13, 2000, 1)` in a second or two. The session note records the measured times. Shallow copies (D-5) and ruling reuse (D-19) are how the budget is met; no timing value appears in any output.

### 9. CLI (`__main__.py`)

`python -m framework.learner recover --seed 1` prints the full table. Shape mirrors `framework/blocks/__main__.py:48`: `main(argv: list[str] | None = None) -> int`, argparse, `raise SystemExit(main())`. Options: `--seed` (required int), `--sims` (default 2000), `--n-cards` (zero or more ints, default the grid (5, 13, 30, 100)), `--json PATH` (also writes the table as JSON). A zero-length `--n-cards` list falls back to the default grid. A `ValueError` from bad values (`--sims 0`, `--n-cards 0`) becomes `parser.error`, exit code 2 and no traceback. The JSON file is `json.dumps(table.model_dump(mode="json"), indent=2, sort_keys=True)` plus a trailing newline.

Printed layout, pinned so byte tests have one target. First line exactly:

```text
SIMULATED rulings from a known preference. No real data. seed=1 sims=2000
```

with the call's seed and sims in place of the example values. Then one header row and one row per cell, true_p outer and n_cards inner, fixed 3 decimals, `n/a` for `correct_side` at true_p = 0.5:

```text
true_p n_cards correct_side mean_absolute_error coverage mean_interval_width
0.500 5 n/a 0.134 0.938 0.627
```

Columns are separated by single spaces; each numeric cell is `f"{value:.3f}"`; `n_cards` prints as a plain integer. The fixed note text from §8 prints as the last block, one line as written there. No timestamps, no paths, no durations anywhere in stdout or in the file. Same seed gives same bytes in both.

### What T11 and T13 call

Exact signatures, so both tickets can build against this plan without reading the code first:

```python
def bucket_for(local_time: datetime.time) -> Bucket: ...
def rank_commitments(
    state: PolicyState,
    profile: ProfileId,
    candidates: tuple[NonEmptyStr, ...],
    bucket: Bucket,
) -> tuple[RankedCommitment, ...]: ...
def policy_block(
    state: PolicyState, bucket: Bucket, candidates: tuple[NonEmptyStr, ...]
) -> str: ...
def initial_state() -> PolicyState: ...
def update(state: PolicyState, ruling: Ruling) -> PolicyState: ...
def observe(state: PolicyState, ruling: Ruling) -> PolicyState: ...
def replay(initial: PolicyState, rulings: Iterable[Ruling]) -> PolicyState: ...
def state_json(state: PolicyState) -> str: ...
def score_report(state: PolicyState) -> ScoreReport: ...
def policy_diff(a: PolicyState, b: PolicyState) -> tuple[PolicyChange, ...]: ...
```

- **T11** imports nothing from `framework.learner`: it receives the policy block as an opaque `str` argument and puts it in the Wonder prompt unchanged. The numbers in the block are not metrics, so if Wonder repeats one in claim text the gate rejects it; that rejection is correct, not a bug to route around.
- **T13** is the only caller of the learner in the live path. The ids come from T10's `Commitment` (`framework/briefing/schemas.py`): `Commitment.id` is the `commitment_id`, a profile's candidates are the ids of its commitments, and `Commitment.profile_id` must be `builder` or `disconnect` for a `Proposal` to validate. When building a card: `bucket_for` on the slot's local time; for each profile, `rank_commitments` and `policy_block`; pass the string to T11's proposal call; build each `Proposal` from what comes back, with `policy_pick` and `policy_alternative` copied from ranking positions 1 and 2. On each tap: build a `Ruling` with the same `card_id`, `slot`, `bucket` and `proposals` as the card, in the same order, and the target; `observe`; persist `state_json`; reload with `PolicyState.model_validate_json`. It reads `offered` under the D-11 limit: shown-but-untapped cards are T13's own count, not the learner's. A two-proposal card's labels pass through unchanged; a one-proposal card must be labelled A whichever profile it shows, because the `Ruling` validator requires it, so a lone Disconnect proposal is label A. R8 and T16 use `replay`, `score_report`, `policy_diff(initial_state(), final)`.

## Files to Create

| File | Contents |
|---|---|
| `framework/learner/__init__.py` | Re-exports every public name from `schemas`, `beta`, `policy`, `scoring`, `simulate` with `__all__`; imports nothing else |
| `framework/learner/schemas.py` | `Bucket`, `BUCKETS`, `ProfileId`, `Target`, and all models in Approach §1 on `SchemaModel`, with the pinned validators |
| `framework/learner/beta.py` | `beta_cdf`, `beta_quantile` (memoized, integer bisection over 2^64), `credible_interval` per Approach §7; `math`, `functools`, `fractions` only |
| `framework/learner/policy.py` | `initial_state`, `bucket_for`, `update`, `state_json`, `rank_commitments`, `policy_block`, `policy_diff` per Approach §2, §4–§6 |
| `framework/learner/scoring.py` | `predict`, `score_before_update`, `observe`, `replay`, `score_report` per Approach §3; exact `Fraction` scores, D-13 rounding, D-14 clipping |
| `framework/learner/simulate.py` | `recover`, `recover_table` per Approach §8; the only file importing `random`, only as a seeded instance |
| `framework/learner/__main__.py` | `main(argv)` CLI per Approach §9; the only file touching the filesystem, only for `--json` |
| `schemas/Proposal.json`, `schemas/Ruling.json`, `schemas/BucketState.json`, `schemas/CommitmentState.json`, `schemas/PredictorScore.json`, `schemas/ScoreEntry.json`, `schemas/PickLogEntry.json`, `schemas/PolicyState.json` | Generated by the export command, never hand-edited (8 files) |
| `tests/test_learner_schemas.py` | Round trips and rejections for every model in Approach §1, incl. each `Ruling` validator, `alpha: 0` rejection, `taken + declined > offered`, wrong bucket key set |
| `tests/test_learner_policy.py` | One test per counting-table row, purity of `update`, `why` then A, double tap, A then B, neither then A, two-profile commitment raise, bucket bounds incl. tz-carrying `time`, ranking arms and reason strings, `policy_block` walk, `policy_diff` invariants |
| `tests/test_learner_scoring.py` | The frozen 4-ruling table and means, prediction-blindness pair, no-entry cases, ordering case, 2000 one-sided rulings, no `Infinity`/`NaN`/`null` in any logged score, replay bytes, round trip at every prefix, hash-seed subprocess |
| `tests/test_learner_beta.py` | Frozen quantiles within 1e-9, closed forms, CDF mass at the interval ends, monotone quantiles, bad-parameter raises |
| `tests/test_learner_simulate.py` | Exact-grid enumeration against literals within 1e-4, prior-averaged coverage, simulated cells within 4 standard errors, stated floor, getting-better-with-n on grid and on simulated cells, symmetry at 0.3/0.7, determinism, alone-vs-table cell equality, one frozen `recover(0.7, 13, 500, 1)` literal, validation raises |
| `tests/test_learner_cli.py` | `main([...])` twice byte-identical, file bytes match stdout contract, first-line and JSON `label` checks, `n/a` only in p = 0.5 rows, note printed, subprocess smoke run |
| `tests/test_learner_purity.py` | AST walk over `framework/learner/*.py`: import allowlist, `random` only in `simulate.py`, filesystem modules only in `__main__.py`, no attribute access to `now`, `utcnow`, `today`, `environ`, `getenv` |
| `docs/sessions/015-learner.md` | Evidence note in the shape of `docs/sessions/008-briefing-gate.md:1`: first line of `muse --version` in the session that does the work, models and efforts per phase, acceptance results with pytest counts, measured CLI timing, public-repo sweep result, statement that the raw redacted export is kept privately; also carries the full default table printed by `python -m framework.learner recover --seed 1`, labelled simulated, as the record of what was run |

## Files to Modify

| File | Change |
|---|---|
| `framework/schemas/export_schemas.py:66` | Import the 8 learner wire models and append them to `EXPORTED_MODELS` as one block at the end of the tuple. No other change |
| `CONTRIBUTIONS.md:135` | Add the entry pinned below, placed after the `## Ticket 10` entry and before the `AI assistance outside the Muse family` section at `CONTRIBUTIONS.md:135`. No other change |
| `README.md` | Two edits only, and only if every acceptance test passed. Under "Built and merged:", as the last bullet of that list, add exactly: "- Learner core (`framework/learner/`): Beta posteriors per time bucket over which of my two goals I take, commitment ranking, scoring each prediction before the ruling it predicts, byte-identical replay, and a known-preference test on simulated rulings; <N> tests in `tests/test_learner_*.py`, passing. Nothing calls it yet, and no real ruling has gone through it." Under "Not built yet:", replace "- The learner and the proof harness." with "- The proof harness." `<N>` is the real number printed by `uv run pytest tests/test_learner_*.py -q` under the env prefix, filled in at the commit, never estimated. No other change |
| `docs/plans/015-learner.md` | This plan, committed with the work in the later session |

The `CONTRIBUTIONS.md` entry, exact heading and required attribution sentence:

```markdown
## Ticket 15a — learner core (2026-11-01)

Built on branch `t15-learner` per [docs/plans/015-learner.md](docs/plans/015-learner.md):
`framework/learner/`, a pure package that turns card rulings into per-slot
preference counts, scores four predictors before each posterior-moving
ruling, ranks commitments for the proposal prompt, and runs the
known-preference test on simulated rulings. Evidence in
[docs/sessions/015-learner.md](docs/sessions/015-learner.md).

Prompts and review by Claude Code. Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code, in headless sessions Claude Code started.
```

No other existing file changes beyond `README.md` and the files in the table above. In particular: nothing under `framework/blocks/`, nothing under `framework/briefing/`, nothing under `framework/schemas/` except `export_schemas.py`, no test file that exists today, `pyproject.toml`, `uv.lock`, `Makefile`, `AGENTS.md`, `docs/SPEC.md`, `docs/PLAN.md`, `docs/WORKFLOW.md`. Tickets T9–T13 own their trees on their branches; this ticket touches none of them.

## Steps

Every `uv`, `pre-commit` and `git` command below and in Acceptance Tests runs with `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home" UV_CACHE_DIR="$PWD/.git/uv-cache"` prefixed. The shorthand "the env prefix" means exactly that string.

1. Pre-flight on `t15-learner`: `git branch --show-current` prints `t15-learner`; `git status` is clean apart from this plan file. Negative control (AT-NEG): the learner tests fail at collection and `framework/learner/` does not exist.
2. Write the tests first: the seven `tests/test_learner_*.py` files against synthetic ids only (`b-1`, `b-2`, `d-1`, `d-2`, `card-001`, `sim-builder`, `sim-disconnect`), frozen instants, the frozen literals in Approach §3, §7 and §8. Confirm they fail because the package does not exist yet. No test reads the path in `HIDDEN_CRITERIA_DIR`, binds a socket, or calls the network or a model. Simulated cells sit behind a module-scoped cache so the whole learner suite stays under 15 s.
3. Build `framework/learner/schemas.py`, then `beta.py`, then `policy.py`, then `scoring.py`, then `simulate.py`, then `__main__.py`, then `__init__.py`. Append the 8 models to `EXPORTED_MODELS` as one end block, run (env prefix) `uv run python -m framework.schemas.export_schemas`, and confirm the diff under `schemas/` adds exactly the 8 new files. Stop and report if the export rewrites any existing schema file.
4. Run (env prefix) `uv run pytest tests/test_learner_schemas.py tests/test_learner_policy.py tests/test_learner_scoring.py tests/test_learner_beta.py tests/test_learner_simulate.py tests/test_learner_cli.py tests/test_learner_purity.py tests/test_schemas_export.py` until green. Fix findings in the new code only; never relax config, never change a frozen literal to fit the code. A frozen literal comes from an oracle outside the repo, and a mismatch means the code is wrong or the literal is: the session stops and reports it, and changes neither. Otherwise a bug in the interval would "correct" the oracle to match itself. The two regression pins captured from a reviewed run (the golden `state_json`, the `recover(0.7, 13, 500, 1)` literal) are the only literals an implementer captures, and each is captured once.
5. Measure the CLI budget: time `python -m framework.learner recover --seed 1` (default sims) and `recover(0.7, 13, 2000, 1)` through the CLI path. Record both times in the session note. No timing value enters any output.
6. Run the full gate under the env prefix: `make check` (ruff check, ruff format check, pyright strict on `framework/`, full pytest, gitleaks). The one known sandbox failure is named in Acceptance Tests and is not this ticket's to fix.
7. Public-repo sweep over every touched file: banned words (AT-BAN), real names, hosts beyond the pinned synthetic ones, private paths, tokens. Confirm `git diff --stat origin/main` shows `framework/blocks/`, `framework/briefing/`, `pyproject.toml`, `uv.lock` and `Makefile` untouched.
8. Write `docs/sessions/015-learner.md` and the `CONTRIBUTIONS.md` Ticket 15a entry with the real models and efforts. Run every Acceptance Test one final time.
9. One commit on `t15-learner`, made only in a later session that is explicitly asked to commit, under the env prefix, containing exactly: `docs/plans/015-learner.md`, `framework/learner/` (7 files), `framework/schemas/export_schemas.py`, the 8 new `schemas/*.json`, the seven `tests/test_learner_*.py` files, `CONTRIBUTIONS.md`, `README.md`, `docs/sessions/015-learner.md`. Not pushed. This plan session makes no commit.

## Acceptance Tests

AT1 writes the env prefix out in full; every later `(env prefix)` is that exact string, prepended to every `uv`, `pre-commit` and `git commit` command in the session that does the work. AT-NEG runs on the base tree; the rest run on the branch.

| # | Command | Expected result |
|---|---|---|
| AT-NEG | On the base tree: (env prefix) `uv run pytest tests/test_learner_policy.py tests/test_learner_scoring.py` and `test -d framework/learner` | Collection fails (no learner package), `framework/learner` does not exist. The tests measure this ticket's work |
| AT1 | `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home" UV_CACHE_DIR="$PWD/.git/uv-cache" uv run pytest tests/test_learner_schemas.py tests/test_schemas_export.py` | Exit 0. Every model round-trips; each `Ruling` validator rejects its pinned bad shape; a state JSON with `alpha: 0` fails validation; `find_drift` is empty and `schemas/` gained exactly the 8 learner files |
| AT2 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "counting or why_then or double_tap or a_then_b or neither_then or two_profiles or purity_of_update or card_mismatch or decided_wrong_why"` | Exit 0. One test per counting-table row passes; `state_json(input)` is unchanged after `update`; "why" then A offers once and moves the posterior once; a double tap moves it once; A then B keeps the first; a commitment under two profiles raises `ValueError`; a later ruling on an already seen card with a different `slot`, `bucket` or proposals or labels raises `ValueError` before any counter moves; `wrong` and `why` on an already decided card add their bucket count and no duplicate count |
| AT3 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "bucket"` | Exit 0. 12:59 raises; 13:00, 16:59, 16:59:59 land in `afternoon`; 17:00, 20:59 in `evening`; 21:00, 23:29 in `night`; 23:30 and 00:00 raise; a `time` with a fixed-offset tzinfo raises no `TypeError` |
| AT4 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "label_is_data or lone or disconnect_first"` | Exit 0. Target A on a lone Disconnect proposal labelled A adds `taken` to that commitment and leaves the posterior alone; on a two-proposal card with A = Disconnect and B = Builder, target A moves `beta` |
| AT5 | (env prefix) `uv run pytest tests/test_learner_scoring.py -k "frozen or means"` | Exit 0. The 4-ruling table and the four means match the Approach §3 literals after rounding, computed by hand: learner 0.293402777778, 0.794513457587; always_half 0.25, 0.69314718056; majority 0.5625, 2.478384472097; pooled_rate 0.320902777778, 0.850299345416 |
| AT6 | (env prefix) `uv run pytest tests/test_learner_scoring.py -k "blind or no_entry or ordering or counters or pooled_equals or pooled_majority_side"` | Exit 0. Two rulings that differ only in `target` give identical predictions from all four predictors; neither, wrong, why, a one-proposal card and a duplicate each add no entry; `update` then `score_before_update` on one card adds no entry; `score_before_update` changes no counter; `update` alone adds no entry; `score_report` counts match by hand on the frozen sequence: `correct`, `wrong`, `no_call` are learner 1, 1, 2; always_half 0, 0, 4; majority 1, 2, 1; pooled_rate 1, 2, 1; with all rulings in one bucket, `pooled_rate` equals `learner` exactly; for every builder count and disconnect count from 0 to 20, through `predict` on a constructed state, `pooled_rate` is above 0.5 exactly when `majority` is 1.0, below exactly when 0.0, and equal to 0.5 exactly when 0.5 |
| AT7 | (env prefix) `uv run pytest tests/test_learner_scoring.py -k "one_sided or finite or json_safe"` | Exit 0. After 2000 one-sided rulings the learner and `pooled_rate` predictions stay strictly inside (0, 1) and the log loss of the opposite outcome is finite; a `state_json` holding any score contains no `Infinity`, `NaN` or `null` inside a `PredictorScore` |
| AT8 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "rank"` | Exit 0. Each tie arm and each pinned reason string matches word for word; a never-offered candidate ranks before an offered one at equal rate (1/2 ties 2/4); slots compare as instants across offsets (`...T18:00:00+01:00` is earlier than `...T17:30:00Z`); candidate order changes nothing; exact-fraction ties hold (1/3 against 2/6); duplicates and a wrong-profile candidate raise; an empty list returns `()`; a single candidate logs pick with no alternative |
| AT9 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "policy_block"` | Exit 0. The returned string for a small frozen state matches the frozen exact string byte for byte; same inputs give the same bytes; tests parse it with `json.loads` for the recursive value walk, which finds every string value among the candidates; candidates stay in rank order in the list; no reason text appears |
| AT10 | (env prefix) `uv run pytest tests/test_learner_scoring.py -k "replay or golden or prefix or hashseed"` | Exit 0. Two runs give byte-identical `state_json`; the frozen golden string for the small synthetic ruling list matches; a JSON round trip at every prefix then continuing gives identical bytes; a subprocess under `PYTHONHASHSEED=1` and `=2` gives identical bytes; `replay` equals the live fold of `observe` |
| AT11 | (env prefix) `uv run pytest tests/test_learner_policy.py -k "diff"` | Exit 0. The diff is empty iff the two `state_json` strings are equal; swapping arguments swaps before/after and added/removed; each differing `PolicyState` field shows up path by path; the frozen diff between `initial_state()` and the small state matches |
| AT12 | (env prefix) `uv run pytest tests/test_learner_beta.py` | Exit 0. The 12 frozen quantile pairs match within 1e-9 (literals labelled as computed with scipy outside this repo on 2026-11-01); Beta(1, n) and Beta(n, 1) closed forms hold; CDF mass between the interval ends is within 1e-9 of 0.95 for every (a, b) with a + b - 2 in {5, 13}; quantiles are monotone in q; non-integer or below-1 parameters raise `ValueError`; `_cdf_at_least(k, a, b, q)` agrees with `beta_cdf(Fraction(k, D), a, b) >= q` on a small set of (k, a, b, q), so the two can't drift apart |
| AT13 | (env prefix) `uv run pytest tests/test_learner_simulate.py -k "exact_grid or floor"` | Exit 0. Enumeration with `math.comb` and the package interval reproduces each frozen grid cell (labelled as computed outside this repo on 2026-11-01) within 1e-4, and every frozen coverage cell lies in [0.91, 1.0] |
| AT14 | (env prefix) `uv run pytest tests/test_learner_simulate.py -k "prior_average or simulated_close"` | Exit 0. Prior-averaged coverage on simulated data through the real `update` (true_p drawn from Uniform(0, 1) with a seeded generator, 5000 draws at n = 5 and 5000 at n = 13) lands within 0.95 ± 0.0125; simulated `recover` values lie within 4 standard errors of the frozen exact value at every p for n in {5, 13, 30} with `n_sims` = 500, and at n = 100, p = 0.7 with `n_sims` = 100, the standard error taken from the enumerated variance at that cell |
| AT15 | (env prefix) `uv run pytest tests/test_learner_simulate.py -k "better_with_n or symmetry or determin or validation"` | Exit 0. On the frozen grid and on simulated cells, error strictly falls and width strictly falls along n = 5, 13, 30, 100 at every p, and `correct_side` never falls; `correct_side` is `None` at p = 0.5 and symmetric for p = 0.3 against p = 0.7 within tolerance; `recover` twice is identical, a different seed differs, a cell computed alone equals the same cell inside `recover_table`; the one frozen `recover(0.7, 13, 500, 1)` literal matches; true_p of 0 or 1 and `n_cards` or `n_sims` of 0 raise `ValueError` |
| AT16 | (env prefix) `uv run pytest tests/test_learner_cli.py` | Exit 0. `main([...])` twice gives identical stdout and the `--json` file bytes match the pinned JSON form; the first line carries `SIMULATED`; the JSON carries `"label": "simulated"`; `n/a` appears exactly in the p = 0.5 rows; the fixed note prints last; a `ValueError` from bad values (`--sims 0`, `--n-cards 0`) becomes `parser.error`, exit code 2 and no traceback |
| AT17 | (env prefix) `uv run python -m framework.learner recover --seed 1 --sims 20 --n-cards 5` | Exit 0 in a subprocess; stdout opens with the `SIMULATED` line for seed 1, sims 20, and prints one row for n_cards 5 at each default true_p. The full default run (`--seed 1`, sims 2000) is timed in step 5 and recorded in the session note against the 60 s budget |
| AT18 | (env prefix) `uv run pytest tests/test_learner_purity.py` | Exit 0. The AST walk finds no import outside the allowlist, no `random` outside `simulate.py`, no filesystem module outside `__main__.py`, and no attribute access to `now`, `utcnow`, `today`, `environ` or `getenv` anywhere in `framework/learner/` |
| AT-BAN | New files checked whole: `grep -rniE '<pattern>' framework/learner tests/test_learner_schemas.py tests/test_learner_policy.py tests/test_learner_scoring.py tests/test_learner_beta.py tests/test_learner_simulate.py tests/test_learner_cli.py tests/test_learner_purity.py docs/plans/015-learner.md docs/sessions/015-learner.md` over the working tree, run once per banned string. Existing files checked on added lines only: `git diff origin/main -- CONTRIBUTIONS.md README.md | grep -E '^\+' | grep -iE '<pattern>'`, run once per banned string | Both must print nothing. Any hit is a ticket failure, including in identifiers and file names. The pattern comes from the implementation prompt, and the reviewer runs it again. The same check over `framework tests evals` for the banned noun is T10's gate; this ticket keeps its own files clean so that gate keeps passing |
| AT-PATH | `grep -c '/Users[/]' docs/plans/015-learner.md docs/sessions/015-learner.md` (the pattern is built so the literal string sits in no repo file) | `0` for each file. No private path sits in either file |
| AT-DIFF | `git diff --stat origin/main` and `git status --short` | The diff touches only the Files lists above, including `README.md` with only its two pinned edits. `framework/blocks/`, `framework/briefing/`, `pyproject.toml`, `uv.lock` and `Makefile` show no change. Any `git diff` against the base uses `origin/main` |
| AT19 | (env prefix) `make check`, then `git log --oneline origin/main..HEAD` after the step-9 commit | `make check` exits 0 (ruff, format, pyright strict on `framework/`, full pytest, gitleaks). One known exception outside this ticket's control: `tests/test_ingest.py::test_live_loopback_server_health_round_trip` can fail where a sandbox denies loopback binds, as recorded in `docs/sessions/008-briefing-gate.md:201`; that failure, when it shows the bind error and also fails on the clean base tree, is reported as a gap, never as a pass and never fixed here. After the commit: exactly 1 commit on `t15-learner` holding the step-9 file set, made under the env prefix; no push |

## Risks

- **Thirteen real rulings will be read for meaning they cannot carry.** That is the reason this ticket exists ahead of any fit on real data (Wilson & Collins 2019). The frozen grid already bounds the claim: at n = 5 the interval is about 0.62 wide and coverage at a fixed p swings from 0.9185 to 0.9898. Residual risk: the printed table gets quoted without its note. Mitigated by D-23: the note is fixed text in the JSON, under the table and here.
- **A credible interval is not a confidence interval (D-22).** A test that pins fixed-p coverage to 0.95 would fail a correct interval, and a reader who expects 0.95 at every p will misread the grid. Mitigated by the three readings in AT13–AT14 and by the floor statement, all pinned before any code exists.
- **The hard vote invites a wrong comparison.** Its log loss is dominated by the clipping constant (D-14), so a learner win on that column says little. Mitigated by `pooled_rate` (D-15) and by the reading rule in Approach §3: read the majority Brier, not its log loss.
- **Dict mutation under frozen models (D-5).** A single missed copy makes `update` impure and breaks replay bytes in ways a small test set might not catch. Mitigated by the purity assertion inside AT2 (`state_json(input)` unchanged) and by replay byte tests at AT10, including a round trip at every prefix.
- **Platform float drift.** `math.log` can differ in the last bit between macOS and Linux. Mitigated by exact `Fraction` scores, D-13 rounding before any float is logged, the 2^-64 exact interval with no libm step, and `sort_keys` canonical JSON. The golden `state_json` at AT10 is the tripwire.
- **Seed-string formatting.** D-20 builds the per-cell seed from `str(true_p)`, so a caller passing `0.70` and a caller passing `0.7` get the same float and the same stream, while a future caller passing a `Fraction` would get a different stream and a different cell. Accepted: the CLI and the grid only ever pass the pinned float literals, and AT15 pins determinism on those.
- **A mean of exactly 0.5 counts as not correct.** At even n this is common, and it pulls `correct_side` down at small n. Stated in Approach §8 rather than smoothed over, because the alternative (counting a tie as half a hit) would need its own defence and would change every frozen cell.
- **Shown-but-untapped cards stay invisible (D-11).** `offered` understates how often a commitment was put in front of me. T13 owns that count. The risk is a later reader treating `offered` as impressions; the limit is written in Success Criteria, in Approach §2 and in the T13 contract for that reason.
- **Simulation speed.** The default table is 40,000 sims through the real `update`. Ruling reuse and skipped scoring (D-19) plus shallow copies (D-5) carry the 60 s budget; if the measurement in step 5 misses it, the fix is a faster copy path in `update`, never a parallel counting formula in `simulate.py`.
- **Export merge with the other appending ticket.** Both append to `EXPORTED_MODELS`. D-7 keeps the learner block as one end block so the merge is one hunk; a conflict there is resolved by keeping both blocks, never by interleaving.

## Test Plan

Committed tests are the deliverable: the seven `tests/test_learner_*.py` files plus the pre-existing `tests/test_schemas_export.py:12` drift test now covering the 8 learner schemas. Written before the package (step 2) so they fail on the base and pass on the branch, per the Definition of Done. Pure throughout: no network, no model call, no socket, no env read, no clock read; instants are frozen fixtures; every id is synthetic. The frozen literals come in three labelled kinds, and tests keep the labels: hand-computed scoring values (Approach §3), quantile references computed with scipy outside this repo on 2026-11-01 (Approach §7), and the exact grid computed by enumeration outside this repo on 2026-11-01 (Approach §8). Enumeration inside the test tree (AT13) is the in-repo check on the third kind; the frozen simulated cell at AT15 guards against later drift and is never the correctness oracle. Simulated cells sit behind a module-scoped cache; the whole learner suite runs in under 15 s. Sequence: AT-NEG on the base, AT1–AT18 on the branch, AT-BAN and AT-DIFF sweeps, `make check` (AT19), then the commit-contents check. No eval or block changes in this ticket, so no Inspect log and no mutant run attach to it; the DoD line about mutants does not apply here and the session note says so rather than claiming one.

## Out of Scope

- The proof harness (R2–R4). This ticket builds the learner and the known-preference test; reading real rulings for meaning is a later ticket.
- Randomization of any kind. It starts after the hackathon.
- Fitting real data, including my roughly 13 real rulings. No real ruling enters any test, fixture or run in this ticket.
- The Wonder prompt wiring (T11). T11 imports nothing from `framework.learner` and takes the policy block as an opaque `str`; this ticket supplies the `policy_block` string (D-25) and writes no prompt.
- The card and its taps (T12), and slots, persistence and the live loop (T13). T13 is the only caller of the learner in the live path; this ticket supplies `Ruling`, `observe`, `state_json` and the reload path; it builds no card, stores nothing, and runs no loop.
- Metrics regeneration (T16), and any change to what counts as a metric for the briefing gate.
- Any import from, or edit to, the T9–T13 trees. Their branches merge against the signatures in "What T11 and T13 call" and nothing else from this ticket.
- A scipy or numpy dependency, a normal-approximation interval, and any edit to `pyproject.toml` or `uv.lock` (D-3, D-18).

## Disagreements with the brief

Nothing here overrides a pin. Each item keeps the pin as written and records my objection or the reading I had to choose where the brief left two readings open. Approval of this plan accepts these readings.

- **X1 — `policy_block` has no profile argument, yet its candidates must rank under one profile.** The brief pins `policy_block(state, bucket, candidates)` and also pins that candidates recorded under two different profiles raise `ValueError`. With plain-string candidates, a profile exists only where a record exists. Reading pinned in Approach §5: the shared record profile ranks the list, mixed records raise, and an all-unrecorded list ranks on zero counts by id. Objection kept on record: an explicit profile argument would be clearer, and T11 may ask for one as an amendment. The pinned signature stands in this ticket.
- **X2 — The counting table's `+1` column reads two ways.** Read per matching row, a first decisive ruling would add 2 to `rulings_seen`; read per call, it adds 1. D-6 pins per call, because the duplicate row only makes sense that way and because `rulings_seen` should count rulings seen. If the brief meant per row, the fix is a one-line change to `update` plus its tests, recorded as an amendment, not a silent choice.
- **X3 — `wrong` and `why` on an already decided card match no table row.** The duplicate row names A, B and neither only. Reading pinned in Approach §2: they add their bucket count and no duplicate count, in any card state. Objection: counting them as duplicates would also be defensible. The pinned reading follows the table's letter.
- **X5 — `majority` is scored as a probability at all.** A hard vote at 0 or 1 is not a forecast, and D-14's clipping constant dominates its log loss. The brief pins the predictor and the clipping, and both stand. My objection, already answered inside the brief by `pooled_rate` (D-15), is recorded so R8 reads the Brier for that predictor and does not headline a log-loss win against it.
- **X6 — The banned-word list bans common code words by substring.** The "contains it" rule removes several ordinary words from identifiers, docstrings and prose, and forces phrasing such as "getting a known preference back" in places where a shorter word exists. The rule stands everywhere the brief puts it, this plan included, and AT-BAN enforces it. Recorded because the constraint shapes naming in ways a reader of the diff might otherwise take for style.
- **X7 — The default simulation grid spends most of its budget where I will never be.** n = 100 at 2000 sims is about two thirds of the table's rulings (100 of 148), while my live reading sits near n = 5. The grid stands as pinned: the falling error and width curves across n are the argument the ticket makes, and they need the long arm. The 60 s budget and the module-scoped test cache keep the cost contained.

## Open Questions

None that block the work. Assumptions stated for approval: (1) the counting table is read per D-6 and X2–X3; (2) `policy_block` ranks under the shared record profile per X1; (3) every learner data type is a `SchemaModel` in `schemas.py`, with only the 8 named wire models exported (D-4, D-7); (4) the CLI layout, header row, `n/a` placement and JSON form in Approach §9 are the byte contract; (5) the frozen grid and quantile literals are oracles as labelled, with in-repo enumeration (AT13) as the check; a frozen literal comes from an oracle outside the repo, and a mismatch means the code is wrong or the literal is: the session stops and reports it, and changes neither, and the two regression pins captured from a reviewed run (the golden `state_json`, the `recover(0.7, 13, 500, 1)` literal) are the only literals an implementer captures, and each is captured once; (6) branch is the existing `t15-learner`, the work lands as one commit under the env prefix in a later session that is explicitly asked to commit, and this plan session commits nothing. Approval of this plan accepts D-1 to D-25, X1 to X7, and these six assumptions.


