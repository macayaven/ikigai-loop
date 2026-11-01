# Ikigai Loop

I write down what I promised myself. The agent picks which promise gets my next free hour, and a deterministic gate checks the numbers and sources it cites against my own data before I see them. Anyone can run the same checks on their own agent: [Check your own agent](#check-your-own-agent).

## Check your own agent

The number, source, label and direction checks in my gate also run on your agent's output, against records you supply. You need `uv` for the command below; the browser page needs nothing. Grab the worked input and run the checker:

```sh
curl -sLO https://raw.githubusercontent.com/macayaven/ikigai-loop/main/examples/verify/input.json
uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims input.json; echo exit=$?
```

You should see exit 1 with `L1B_METRIC_VALUE_MISMATCH`: the sample says
November deploys reached 12 while the records say 7. Or run it in your
browser at [https://macayaven.github.io/ikigai-loop/verify/](https://macayaven.github.io/ikigai-loop/verify/), where the same Python runs
on your machine and nothing is sent anywhere.

This check covers parseable numbers, cited sources, labels and direction. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist.

Start from [examples/verify/README.md](examples/verify/README.md) for the
full worked case, and [docs/ADAPTER.md](docs/ADAPTER.md) to map your own
agent's output shape to this input.

## How it works

This is the design. Status below says which parts exist today.

1. Two goals compete for the same hour: Builder and Disconnect (family time, screens off).
2. Collectors store my own signals on my own machine.
3. Muse Glimmer, an open-weight model on my own hardware, turns them into facts that cite their events.
4. Muse Wonder, through Muse Code headless on my subscription, sees only those facts and my commitments, and proposes one commitment per goal for the next free slot.
5. A deterministic gate with no model and no network rejects whatever it can't reconcile.
6. A Telegram card offers both proposals and a tap rules between them.
7. A voice note corrects the system and the next card changes. Its audio goes to Meta's API for transcription by Muse Voice Transcribe; raw screen, calendar and GitHub rows stay on my machine.

## Status

Built and merged:

- Event store (`framework/store/`): append-only SQLite log with conflict detection; a trigger blocks updates and `purge_before` is the only delete path; 20 tests in `tests/test_store.py` and `tests/test_collector.py`, passing.
- Collectors (`framework/collectors/`): calendar (`calendar_ics.py`), GitHub activity (`github_events.py`), public build feed (`build_feed.py`), screen time (`activitywatch.py`); 90 tests passing, 75 across those four collector suites and 15 in the CLI suite they share with the off-path code.
- Deterministic gate (`framework/briefing/gate.py`, cases in `evals/briefing_cases.py`): no model, no network; it catches all 38 mutant briefings and passes all 20 known-good ones (`tests/test_briefing_mutants.py`, passing).
- Commitments and the gate additions they need (`framework/briefing/commitments.py`, `framework/briefing/labels.py`, made-up examples in `profiles/commitments.example.json`): an action passes only if it is a commitment I wrote, in my words; a claim that cites a metric passes only if it names that metric and its period and any direction word agrees with the values; advice wording fails. 18 of those 38 mutants and 8 of those 20 known-good briefings test these additions. What the gate still misses is listed at the top of `framework/briefing/numbers.py`.
- Public checker (`framework/verify/`, `verify-claims` CLI, page at `docs/verify/`): the gate's number, source, label and direction checks over plain JSON anyone can supply, with a parity test against the gate's own cases; the same Python runs in the visitor's browser through Pyodide with nothing sent anywhere; 187 tests in `tests/test_verify_*.py`, passing.
- Glimmer fact layer (`framework/glimmer/`, `framework/store/fact_store.py`, `framework/cycle/`): filters events to an allowlist, computes metrics and three 24-hour periods with no model, asks Muse Glimmer in two isolated passes, and drops any fact that fails its deterministic checks; 416 tests in `tests/test_glimmer_*.py`, `tests/test_fact_store.py` and `tests/test_cycle_cli.py`, passing.
- Glimmer code facts (`framework/glimmer/code_facts.py`): a rule reports the largest change in each of five families (screen hours, pushes, PRs, calendar tag hours, cancelled blocks), so a cycle still has facts when the local model fails, and `--no-personal-pass`/`--no-feed-pass` skip the model passes; 57 tests in `tests/test_glimmer_code_facts.py`, counted in the line above, passing. One live cycle ran on synthetic rows; it has not run on my real store yet.
- Learner core (`framework/learner/`): Beta posteriors per time bucket over which of my two goals I take, commitment ranking, scoring each prediction before the ruling it predicts, byte-identical replay, and a known-preference test on simulated rulings; 146 tests in `tests/test_learner_*.py`, passing. Nothing calls it yet, and no real ruling has gone through it.
- Pre-registration ([docs/PREREG.md](docs/PREREG.md)): the Nov 2-4 live run's predictions and rules, committed before the first card, with the R3 steering pairs as data (`evals/r3_pairs.json`). Nov 1 deviations, made before any card, are logged at its end.
- Telegram card (`framework/telegram/`): one photo message with a chart and buttons, taps stored as `app.tap`, long polling with no public endpoint; 160 tests in `tests/test_telegram_*.py`, passing. Nothing schedules it yet, and no real card or ruling has gone through it.
- The Wonder proposal step (`framework/proposal/`, `framework/store/proposal_store.py`): one guarded Muse Wonder call per goal for the next free hour through Muse Code headless on my subscription, with the Model API transport still in the code for anyone with a key; every draft is gated with one retry on the violations, and anything else becomes a labelled fallback or a noop; attempts and results persist append-only for the next run and the first-draft failure report; 238 tests in `tests/test_proposal_*.py`, passing. Nothing schedules it yet.
- Calendar labels (Ticket 9c): a local step reads a title on my machine and returns one of eight labels, off by default. R10 on 80 invented titles, one pass: `model correct: 77/80 strict: 77/80`, `keywords correct: 51/80 strict: 50/80`, `decision: eligible`. Eligible means the rule I fixed first passed; nothing turns on by itself, and no real title is ever scored. The titles and the circumstances in their notes are invented test fixtures, not my calendar; see [evals/README.md](evals/README.md). 95 tests in `tests/test_cycle_labels.py` and `tests/test_r10.py`, and 129 in `tests/test_glimmer_label*.py` counted in the fact layer line above, passing.

Not built yet:
- The orchestrator.
- Voice correction.
- The proof harness.
- The replay viewer.

Muse Glimmer has generated facts through this code in a seeded run on synthetic data. Muse Wonder has written proposals through this code on synthetic data, on Muse Code headless on my subscription, with the numbers in [docs/sessions/011-wonder-proposal.md](docs/sessions/011-wonder-proposal.md). No model has generated a card yet. The only card delivered so far is a sample with made-up values, sent to my phone to test the transport, and I claim no results.

## No medical advice

It gives no medical advice by design: it only schedules commitments I wrote, and Apple Health is out of the design. The gate enforces this with two rules: `L1_ACTION_NOT_COMMITTED` rejects any action that isn't one of those commitments, and `L1_ADVICE` rejects advice wording in claims and actions. `L1_ADVICE` is a fixed word list, so it catches wording, not meaning.

## Built during the hackathon

Every commit here falls inside the building period, Oct 27 to Nov 4, first commit e62fcc8. Not built here: Meta's model weights, Unsloth's GGUF quantization of Glimmer, llama.cpp and llama-swap, ActivityWatch, Telegram, and my accounts and hardware. Muse Code wrote all the code; the record is in [CONTRIBUTIONS.md](CONTRIBUTIONS.md) and [docs/sessions/](docs/sessions/).

## Code off the card path

Apple Health ingest, the Spotify collector and framework/blocks/ were built earlier in the hackathon. The current design doesn't use them.

## About the Venn diagram

The four-circle ikigai diagram comes from Marc Winn's 2014 blog post, adapted from Andrés Zuzunaga's purpose diagram, and Winn says it misses the Japanese meaning. I use it only as a prompt for my own values. IkigaiWeights are my preference weights, not a validated scale.

## Links

- The two goals: [profiles/](profiles/)
- Design record and past plans: [docs/](docs/)
- What the literature supports and doesn't: [docs/LITERATURE.md](docs/LITERATURE.md)
