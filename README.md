# Ikigai Loop

I write down what I promised myself. The agent picks which promise gets my next free hour, and a deterministic gate checks the numbers and sources it cites against my own data before I see them.

## How it works

This is the design. Status below says which parts exist today.

1. Two goals compete for the same hour: Builder and Disconnect (family time, screens off).
2. Collectors store my own signals on my own machine.
3. Muse Glimmer, an open-weight model on my own hardware, turns them into facts that cite their events.
4. Muse Wonder, through Meta's API, sees only those facts and my commitments, and proposes one commitment per goal for the next free slot.
5. A deterministic gate with no model and no network rejects whatever it can't reconcile.
6. A Telegram card offers both proposals and a tap rules between them.
7. A voice note corrects the system and the next card changes. Its audio goes to Meta's API for transcription by Muse Voice Transcribe; raw screen, calendar and GitHub rows stay on my machine.

## Status

Built and merged:

- Event store (`framework/store/`): append-only SQLite log with conflict detection; a trigger blocks updates and `purge_before` is the only delete path; 20 tests in `tests/test_store.py` and `tests/test_collector.py`, passing.
- Collectors (`framework/collectors/`): calendar (`calendar_ics.py`), GitHub activity (`github_events.py`), public build feed (`build_feed.py`), screen time (`activitywatch.py`); 56 tests passing, 41 across those four collector suites and 15 in the CLI suite they share with the off-path code.
- Deterministic gate (`framework/briefing/gate.py`, cases in `evals/briefing_cases.py`): no model, no network; it catches all 20 mutant briefings and passes all 12 known-good ones (`tests/test_briefing_mutants.py`, passing).

Not built yet:

- The Glimmer fact layer.
- Commitments and the gate additions they need.
- The Wonder proposal step.
- The Telegram card.
- The orchestrator.
- Voice correction.
- The learner and the proof harness.
- The replay viewer.

No model has generated a fact or a card in this project yet, no card has been delivered, and I claim no results.

## No medical advice

It gives no medical advice by design: it only schedules commitments I wrote, and Apple Health is out of the design. The gate rule that enforces this is not built yet.

## Built during the hackathon

Every commit here falls inside the building period, Oct 27 to Nov 4, first commit e62fcc8. Not built here: Meta's model weights, Unsloth's GGUF quantization of Glimmer, llama.cpp and llama-swap, ActivityWatch, Telegram, and my accounts and hardware. Muse Code wrote all the code; the record is in [CONTRIBUTIONS.md](CONTRIBUTIONS.md) and [docs/sessions/](docs/sessions/).

## Code off the card path

Apple Health ingest, the Spotify collector and framework/blocks/ were built earlier in the hackathon. The current design doesn't use them.

## About the Venn diagram

The four-circle ikigai diagram comes from Marc Winn's 2014 blog post, adapted from Andrés Zuzunaga's purpose diagram, and Winn says it misses the Japanese meaning. I use it only as a prompt for my own values. IkigaiWeights are my preference weights, not a validated scale.

## Links

- The two goals: [profiles/](profiles/)
- Design record and past plans: [docs/](docs/)
