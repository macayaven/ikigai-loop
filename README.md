# Ikigai Loop

An AI assistant that suggests, five times a day, how to spend my next free hour, on my work goals or with my family, and that never shows me a number it can't back with my own records.

It runs on me now. The first real card reached my phone on Nov 2 at 13:30, on time, and I chose with a tap. An independent recount of its pull-request figure, straight from GitHub's own records rather than from my store, matched. Anyone who wants the same check on their own agent: [Check your own agent](#check-your-own-agent).

## How it works

It looks at what I actually did, from my screen time, calendar and GitHub, picks two options from a list of promises I wrote down myself, and sends them to my phone as a Telegram card. Before the card goes out, plain code checks every figure in it, say "you coded 4.7 hours yesterday", against those records, and a wrong one is sent back. I choose with a tap, or correct it with a voice note, and later cards learn from what I pick.

## Try it

One command for a stranger. You need `uv` and `git`, and a network connection the first time; uv fetches Python itself if needed. It runs with no key, no model, no phone and no account, stores nothing, writes only the file you name (uv keeps its own download cache, as it does for any tool), and reads no real data:

```sh
uvx --from git+https://github.com/macayaven/ikigai-loop try-ikigai --save card.png
```

It replays made-up data through the same checks my real run uses and prints the card, the choice, a planted wrong number the gate rejects, and the records behind one sentence; `card.png` is the chart image. On my machine the first run took under 10 seconds from an empty cache, Python download included, and about a second after that.

From a clone, `make try` runs the same replay.

## Check your own agent

If your agent says it shipped 12 deploys and your records say 7, the checker catches it.

The number, source, label and direction checks in my gate also run on your agent's output, against records you supply. You need `uv` for the command below; the browser page needs nothing, and takes the sentence and your records in plain words, with no JSON. Grab the worked input and run the checker:

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

## What works today, and what doesn't

Works: cards reach my phone five times a day on a schedule, and the first real one went out on time. Every figure on a card is checked against my records by plain code with no model before it is sent, and a recount of the first card's pull-request figure from GitHub matched. A voice note can correct a card, and that code is built. Anyone can run the checker on their own agent, on the command line or in the browser.

Doesn't, yet: this is set up for one person, me, with no installer and no ready-made timer files in the repo. There are no results yet: the run I registered before the first card continues to Nov 4 and I will report its numbers then. There is no viewer for past cards, and the proof harness is not built.

This is for me first, and the checker is for anyone whose agent cites numbers.

## What the real loop needs

- Python 3.12 and `uv`.
- A machine serving Muse Glimmer, Meta's open-weight model, behind an OpenAI-compatible endpoint.
- Muse Code on a subscription, for the proposals from Muse Wonder and for voice transcription.
- A Telegram bot and my private chat with it.
- My calendar as ICS links, my GitHub user and a token, and ActivityWatch for screen time.
- A JSON list of my own promises, with made-up examples in `profiles/commitments.example.json`.
- A private word list the gate refuses to send.
- Something that runs `python -m framework.cycle run-slot` on a schedule.

Every variable is in `.env.example`. Try it and the checker need none of this.

## Words I use below

- Builder and Disconnect: my two goals, work and family time with screens off.
- Muse Glimmer: Meta's open-weight model, on my own hardware, that turns my records into facts.
- Muse Wonder: Meta's model through Muse Code on my subscription, that proposes one commitment per goal.
- The gate: plain code with no model that checks every figure before a card goes out.
- A slot: one of the five card times.
- The R-numbers: my benchmarks, registered in `docs/PREREG.md`, except R10, defined in `evals/README.md`.

## The pieces

This is the design in more detail, and Status says what exists.

1. Two goals compete for the same hour: Builder and Disconnect (family time, screens off).
2. Collectors store my own signals on my own machine.
3. Muse Glimmer, an open-weight model on my own hardware, turns them into facts that cite their events.
4. Muse Wonder, through Muse Code headless on my subscription, sees only those facts and my commitments, and proposes one commitment per goal for the next free slot.
5. A deterministic gate with no model and no network rejects whatever it can't reconcile.
6. A Telegram card offers both proposals and I choose with a tap.
7. A voice note corrects the system and the next card changes. Its audio goes through Muse Code on my subscription for transcription, and nothing on the voice path calls the API directly; raw screen, calendar and GitHub rows stay on my machine.

## Status

Built and merged:

- Event store (`framework/store/`): append-only SQLite log with conflict detection; a trigger blocks updates and `purge_before` is the only delete path; 20 tests in `tests/test_store.py` and `tests/test_collector.py`, passing.
- Collectors (`framework/collectors/`): calendar (`calendar_ics.py`), GitHub activity (`github_events.py`), public build feed (`build_feed.py`), screen time (`activitywatch.py`); 111 tests passing, 96 across those four collector suites and 15 in the CLI suite they share with the off-path code.
- Deterministic gate (`framework/briefing/gate.py`, cases in `evals/briefing_cases.py`): no model, no network; it catches all 38 mutant briefings and passes all 20 known-good ones (`tests/test_briefing_mutants.py`, passing).
- Commitments and the gate additions they need (`framework/briefing/commitments.py`, `framework/briefing/labels.py`, made-up examples in `profiles/commitments.example.json`): an action passes only if it is a commitment I wrote, in my words; a claim that cites a metric passes only if it names that metric and its period and any direction word agrees with the values; advice wording fails. 18 of those 38 mutants and 8 of those 20 known-good briefings test these additions. What the gate still misses is listed at the top of `framework/briefing/numbers.py`.
- Public checker (`framework/verify/`, `verify-claims` CLI, page at `docs/verify/`): the gate's number, source, label and direction checks over plain JSON anyone can supply, with a parity test against the gate's own cases; the same Python runs in the visitor's browser through Pyodide with nothing sent anywhere; 187 tests in `tests/test_verify_*.py`, passing.
- Glimmer fact layer (`framework/glimmer/`, `framework/store/fact_store.py`, `framework/cycle/`): filters events to an allowlist, computes metrics and three 24-hour periods with no model, asks Muse Glimmer in two isolated passes, and drops any fact that fails its deterministic checks; 464 tests in `tests/test_glimmer_*.py`, `tests/test_fact_store.py` and `tests/test_cycle_cli.py`, passing.
- Glimmer code facts (`framework/glimmer/code_facts.py`): a rule reports the largest change in each of five families (screen hours, pushes, PRs, calendar tag hours, cancelled blocks), so a cycle still has facts when the local model fails, and `--no-personal-pass`/`--no-feed-pass` skip the model passes; 57 tests in `tests/test_glimmer_code_facts.py`, counted in the line above, passing. One live cycle ran on synthetic rows; it ran on my real store for the first real card, on Nov 2 at 13:30.
- Clock fixes (Ticket 9e): fact numbers are cut at the whole hour at or before each cycle, with the open hour counted whole on the next card; busy and tag hours are unions of clipped intervals; calendar revisions reconcile per calendar and combine across calendars, and a moved block is not a cancellation; the calendar collector diffs on content or stamp with revision identities; GitHub paging follows up to three pages; each number binds to the period its statement names. 464 tests in `tests/test_glimmer_*.py`, `tests/test_fact_store.py` and `tests/test_cycle_cli.py`, passing.
- Learner core (`framework/learner/`): Beta posteriors per time bucket over which of my two goals I take, commitment ranking, scoring each prediction before the choice it predicts, byte-identical replay, and a known-preference test on simulated choices; 146 tests in `tests/test_learner_*.py`, passing. The orchestrator replays it at every slot, see `framework/cycle/orchestrator.py`, and my first real tap, on Nov 2 at 13:30, is the first choice it learns from.
- Pre-registration ([docs/PREREG.md](docs/PREREG.md)): the Nov 2-4 live run's predictions and rules, committed before the first card, with the R3 steering pairs as data (`evals/r3_pairs.json`). Nov 1 deviations, made before any card, are logged at its end.
- Telegram card (`framework/telegram/`): one photo message with a chart and buttons, taps stored as `app.tap`, long polling with no public endpoint; 218 tests in `tests/test_telegram_*.py`, passing. The first real card went out through it via the orchestrator on Nov 2 at 13:30, with my tap stored.
- The Wonder proposal step (`framework/proposal/`, `framework/store/proposal_store.py`): one guarded Muse Wonder call per goal for the next free hour through Muse Code headless on my subscription, with the Model API transport still in the code for anyone with a key; every draft is gated with one retry on the violations, and anything else becomes a labelled fallback or a noop; attempts and results persist append-only for the next run and the first-draft failure report; 334 tests in `tests/test_proposal_*.py`, passing. The orchestrator calls it at every slot.
- Calendar labels (Ticket 9c): a local step reads a title on my machine and returns one of eight labels, off by default. R10 on 80 invented titles, one pass: `model correct: 77/80 strict: 77/80`, `keywords correct: 51/80 strict: 50/80`, `decision: eligible`. Eligible means the rule I fixed first passed; nothing turns on by itself, and no real title is ever scored. The titles and the circumstances in their notes are invented test fixtures, not my calendar; see [evals/README.md](evals/README.md). 95 tests in `tests/test_cycle_labels.py` and `tests/test_r10.py`, and 129 in `tests/test_glimmer_label*.py` counted in the fact layer line above, passing.
- Model benchmark R1b (`evals/r1b.py`, results in `docs/r1b.md`): the same 54 synthetic cases through the same gate on five rows, each with the product prompt and a plain prompt that teaches none of the gate's rules; first-draft gate failures per row and arm are 1/44 for muse-wonder-1.0 (high), 0/43 for muse-wonder-full-1.0 (high, subscription-only, Power or Maximum), 0/36 for muse-spark-1.3 (medium) and 1/27 for muse-spark-1.3 (low), and muse-glimmer-30b ran after the others under the same gate and follows as data in `docs/r1b.md`; the set is synthetic, one pass per case, hand-written case by case by a fresh Muse Code session on muse-wonder-full-1.0 at high in Contributor mode on made-up data from a written description alone after Claude Code rejected that model's earlier script-built pooled set, that model is also one of the arms with no memory across sessions, and the private-term check is not exercised. 106 tests in `tests/test_r1b_*.py`, passing.

- The orchestrator (`framework/cycle/`): one command, `python -m framework.cycle run-slot`, runs one pinned Madrid slot from facts to delivered card, with an append-only slot ledger, no blind retry on a send whose delivery is unknown, Disconnect limits by code, a kill file, a card that never waits for a hung model, one more try after a Wonder timeout when a full call's time remains, a watchdog `check-slot` and a read-only `trace`; 363 tests in `tests/test_cycle_orchestrator.py`, `tests/test_cycle_orchestrator_processes.py`, `tests/test_cycle_card_build.py`, `tests/test_cycle_slot_ledger.py`, `tests/test_cycle_trace.py`, `tests/test_cycle_rehearse.py`, `tests/test_proposal_local_retry.py` and `tests/test_proposal_timeout_retry.py`, passing.
- Public provenance (`framework/provenance/`, `docs/MODELS.md`, `docs/provenance.jsonl`): a read-only export writes one JSON line per slot with counts and codes and no card text, and `make glimmer-proof` runs one synthetic label through llama-swap, prints the served weights' basename, and refuses during a real slot's Glimmer window; 58 tests in `tests/test_provenance_export.py`, `tests/test_provenance_glimmer_proof.py` and `tests/test_provenance_docs.py`, passing.
- Voice correction (`framework/voice/`): a voice note corrects the card, transcribed through Muse Code on my subscription, compiled to one typed operation by a guarded model call, applied as append-only events, with a corrected card for the same slot when the offer changed; 342 tests in `tests/test_voice_*.py` and `tests/test_r9_*.py`, passing. R9 on the frozen set of 60, one pass each: the literal matcher 13; muse-spark-1.3 minimal 58, the default; muse-spark-1.3 low 57; muse-wonder-1.0 low 58; muse-glimmer-30b local 54.

- Source audit (`source_audit/`): I recount my pull requests and pushes from a public GitHub snapshot with code that shares nothing with the product, then walk the recount through the stored metric, the fact statement, and the delivered card; nothing schedules it, I run it by hand after a real card, and a network-free negative control covers the failure modes; 135 tests in `tests/test_source_audit_*.py`, passing.

Not built yet:
- The proof harness.
- The replay viewer.

Muse Glimmer has generated facts through this code in a seeded run on synthetic data. Muse Wonder has written proposals through this code on synthetic data, on Muse Code headless on my subscription, with the numbers in [docs/sessions/011-wonder-proposal.md](docs/sessions/011-wonder-proposal.md). A full synthetic slot ran through this code on my local model and Muse Wonder, with a scratch database and a fake Bot API, as [docs/sessions/013-orchestrator.md](docs/sessions/013-orchestrator.md) records. The first real card went out on Nov 2 at 13:30, on time, as the public line in `docs/provenance.jsonl` records. I tapped my choice. An independent recount of its pull-request figure from GitHub's own records matched at every stage, as [docs/sessions/020-source-audit.md](docs/sessions/020-source-audit.md) records under "The first real card". The registered run continues to Nov 4 and I claim no results before it ends.

## No medical advice

It gives no medical advice by design: it only schedules commitments I wrote, and Apple Health is out of the design. The gate enforces this with two rules: `L1_ACTION_NOT_COMMITTED` rejects any action that isn't one of those commitments, and `L1_ADVICE` rejects advice wording in claims and actions. `L1_ADVICE` is a fixed word list, so it catches wording, not meaning.

## Built during the hackathon

Every commit here falls inside the building period, Oct 27 to Nov 4, first commit e62fcc8. Not built here: Meta's model weights, Unsloth's GGUF quantization of Glimmer, llama.cpp and llama-swap, ActivityWatch, Telegram, and my accounts and hardware. Muse Code wrote the code; the exceptions, such as held-out test sets and one frozen baseline written by Claude Code, are named in [CONTRIBUTIONS.md](CONTRIBUTIONS.md), and the full record is in [docs/sessions/](docs/sessions/).

## Code off the card path

Apple Health ingest, the Spotify collector and framework/blocks/ were built earlier in the hackathon. The current design doesn't use them.

## About the Venn diagram

The four-circle ikigai diagram comes from Marc Winn's 2014 blog post, adapted from Andrés Zuzunaga's purpose diagram, and Winn says it misses the Japanese meaning. I use it only as a prompt for my own values. IkigaiWeights are my preference weights, not a validated scale.

## Links

- The two goals: [profiles/](profiles/)
- Design record and past plans: [docs/](docs/)
- What the literature supports and doesn't: [docs/LITERATURE.md](docs/LITERATURE.md)
