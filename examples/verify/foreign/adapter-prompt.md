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
