# Models

My card path uses two Meta models for one job each, plain code does the rest, and Muse Code wrote all of it.

| Job | Model | Where | What crosses |
|---|---|---|---|
| Facts | Muse Glimmer, open weights (Unsloth's GGUF) | My DGX Spark, private, behind llama-swap | Nothing goes to Meta |
| Proposal | Muse Wonder, through headless Muse Code on my subscription, Contributor mode off | Wonder runs on Meta's servers | One prompt per goal, per `docs/PRIVACY.md`, never raw rows |
| Gate, code facts, metrics, hour, chart, since line | Plain code, no model | My machine | Nothing, except card text and chart to Telegram |
| All code | Muse Code wrote it; see `CONTRIBUTIONS.md` | On Meta's servers, from my machine, in Contributor mode, on this public repo and made-up data | That content reaches Meta |

Checks:

- I read `facts_cited`, `cycle_origin`, `delivery` in `head -1 docs/provenance.jsonl`. The log holds only counts and codes per slot, so it cannot show what a sentence said.
- I run `make glimmer-proof` with `LOCAL_LLM_*` at llama-swap. It refuses 25 to 4 minutes before a slot. It sends one invented calendar title to Glimmer and gets back one of eight labels. This proves the weights and serving path; labels stay off on real runs. `facts_cited` carries the fact path.
- I run `uv run pytest tests/test_provenance_export.py tests/test_provenance_glimmer_proof.py tests/test_provenance_docs.py`: these tests need none of my data and plant made-up private strings in every column to show none reach the log. Only the export (`uv run python -m framework.provenance.export --db <store>`) needs my store, so judges cannot run it.

When `facts_cited.model` is 0 on a card, no Glimmer fact reached that card, Wonder still wrote the words, its cited facts and numbers came from code, and I publish those zeros. I use no Muse Image, SAM 3.1, or Muse Spark Open. Voice correction: Meta transcribes the note through Muse Code, Muse Spark compiles one operation, and Wonder redrafts the card.
