# Point the checker at your agent's output shape

First rule: facts and metrics come from your system of record, never from the agent's output, or the agent is checking its own numbers. Everything in `examples/verify/foreign/` is made up: ticket queues and deploy counts, no real person or company.

## The contract

Write `to_verify_input(agent_output: dict, source_data: dict) -> dict`:

- `claims` come from `agent_output`.
- `facts` and `metrics` come only from `source_data`.
- One explicit table maps each agent field to its system-of-record field. A figure whose field has no entry raises `MissingProvenance(ValueError)`. Missing provenance fails closed: the adapter raises rather than guessing a fact or metric id.
- Pure function, stdlib only. No network, no model at runtime. One function, the table and the exception, nothing else, with tests run under `python3 -m unittest`.

You still have to confirm units, windows and source mapping yourself: the units of each figure, the time window each figure covers, and which system-of-record field each agent field really comes from. A model can only read what the files show.

Muse Code sends what it reads to Meta's API, so the sample and source data you hand the recipe must be made up or scrubbed, never real private data. The command below also keeps out your personal rules and skills from other tools.

## The command

Put your agent's schema, one sample and your source data in a folder under the names used in `examples/verify/foreign/`, copy `adapter-prompt.md` and `adapter-result.schema.json` beside them, and run this from that folder. To try it as is, run it from `examples/verify/foreign/`.

```sh
muse exec --model muse-spark-1.3 --reasoning-effort medium \
  --contributor-mode off --disable-web-tools --disable-request-user-input \
  --no-foreign-personal-context \
  --approval-mode never --trust-workspace --workspace "$PWD" \
  --output-schema adapter-result.schema.json \
  --prompt-file adapter-prompt.md
```

It is one headless run. Nobody can answer it, so it writes `adapter.py` and `test_adapter.py`, runs the tests, and prints JSON naming the adapter file, the test file, the test command, whether the tests passed, the mappings you still have to confirm, and its assumptions. Any coding agent can take the same prompt.

## After the run

Read `unconfirmed_mappings` and confirm each entry, or fix the table, before you trust a verdict. Then feed the adapter's output to the checker:

```sh
python3 -c 'import json, adapter; print(json.dumps(adapter.to_verify_input(json.load(open("agent-output.json")), json.load(open("source-data.json")))))' | uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims -
```

On the sample that exits 1 with `L1B_METRIC_VALUE_MISMATCH`: the agent says November deploys hit 12, and the ledger says 7.

## The prompt

`examples/verify/foreign/adapter-prompt.md` holds this exact text:

```markdown
# Adapter task

Nobody can answer questions during this run, so state every assumption in your final answer, which is the JSON the output schema asks for.

This folder holds `agent-output.schema.json` (my agent's output shape), `agent-output.json` (one sample of it) and `source-data.json` (my system of record, in its own shape). Read all three.

Write a pure function `to_verify_input(agent_output: dict, source_data: dict) -> dict` plus a `MissingProvenance(ValueError)` exception in `adapter.py`, with tests in `test_adapter.py`. Run `python3 -m unittest` in this folder and confirm the tests pass before you answer.

## Hard rules

- `claims` come from `agent_output`. `facts` and `metrics` come only from `source_data`, never from the agent's output. The agent must not check its own numbers.
- Keep one explicit table in `adapter.py` from each agent field to its system-of-record field, and add an entry only where the files show the mapping. A figure whose field has no entry raises `MissingProvenance`: raise, never guess a fact or metric id.
- You cannot confirm the table yourself. List every entry under `unconfirmed_mappings`, with the source field and the units and time window you assumed, so I can confirm units, windows and source mapping after the run.
- A cited source id that the system of record does not hold stays in `fact_ids`, so the checker reports it.
- Declare `labels` for every metric, using words the agent's sentences use, and `order` for metrics that form a series over time.
- `adapter.py` is stdlib only. No network, no model call at runtime. One function, the table and the exception, nothing else.

## Target shape

The returned dict must validate as this checker input:

- `claims`: list of `id` (non-blank string, at most 200 chars), `text` (non-blank string, at most 2000 chars), `fact_ids` (list of non-blank strings, default empty), `metric_refs` (list of `metric_id` plus numeric `value`, at most 100 per claim, default empty). At least one claim. Claim ids unique.
- `facts`: required, dict of non-blank id to non-blank string, from the system of record only.
- `metrics`: required, dict of non-blank id to number (int or float, no strings, no booleans, no null), from the system of record only.
- `labels` (optional): dict of metric id to a non-empty list of at most 10 non-blank words of at most 100 chars each. Every listed word must appear in the claim as a whole word, case-insensitive. Alternatives cannot be expressed, so pick the form the agent writes.
- `order` (optional): list of series, each a list of 2 to 366 metric ids, earliest first. Each id appears at most once in at most one series. Direction words are checked against it, and a word only an uncited member of the series lists must not appear in the claim. With `labels` or `order` declared for its metrics, a claim may cite one such metric, or several from one series; otherwise split the claim.
- `deny_terms` (optional): list of non-blank strings of at most 100 chars each. A term of 3 characters or fewer matches whole words only, a longer term matches anywhere in the text, case-insensitive.
- `advice_words` (optional): list of non-blank strings of at most 100 chars each. Whole word, case-insensitive. No default list.

## Tests

Cover at least: a figure in the sample that disagrees with the source keeps the agent's value in `metric_refs` and the source's value in `metrics`; changing the agent's reported figure changes no value in `metrics`; a figure with no table entry raises `MissingProvenance`.
```

## What this does not catch

This check covers parseable numbers, cited sources, labels and direction. It does not check that a sentence is true. Without labels it cannot tell which metric a number belongs to, and a cited fact is only checked to exist.

Also:

- A false sentence around correct numbers.
- Without labels, a number only has to match some ref on its claim, and a metric with no `labels` or `order` entry gets no label or direction check.
- Inside one series, a value is not bound to its place in the sentence unless a direction word exposes it: "rose from 9 in October to 5 in November" passes when October was 5 and November was 9.
- Direction words outside the gate's lists are not seen.
- Rounding and sign: a number is backed when a cited value rounds to it at the precision written, with the sign ignored, so 5 passes for 4.75 and -7 for 7.
- Number forms the parser does not read, such as `7k` or `8th`, plus dates and clock times. The full list is at the top of [framework/briefing/numbers.py](../framework/briefing/numbers.py).
- Claim ids are echoed as given, so never put private terms in ids.
