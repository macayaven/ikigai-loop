# Session evidence — 022-provenance (2026-11-02)

Ticket 22 only: a public record of which model did what on each real card, with no card text and no change to the card path. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code, in Contributor mode on this public repo and made-up data only. The plan and one plan amendment on muse-wonder-1.0 (effort high). The implementation and three fix sessions on muse-spark-1.3 (effort medium). This commit step on muse-spark-1.3 (effort medium). A format fix and this amend ran on muse-spark-1.3 (effort low). This fix ran on muse-spark-1.3 (effort medium) after Ticket 13b landed. Prompts and review by Claude Code.

`~/.local/bin/muse --version` (commit session, first line, verbatim):

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, `git` and `make` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

The weakest reading of this entry is that Muse Code only wrote the code, so I publish a checkable record of what Meta's models added beyond deterministic code, including the cards where they added nothing. The new package `framework/provenance/` holds three things: a read-only export that writes one JSON line per slot with counts and codes and no card text, closed Pydantic shapes that every line must pass before anything is written, and a Glimmer proof that runs one synthetic label through my own model server and prints the served weights' basename. `make glimmer-proof` runs the proof and refuses inside a real slot's Glimmer window. `docs/MODELS.md` tells a judge which model does which job, where it runs, what crosses the network, and how to check each claim. `docs/provenance.jsonl` starts empty and is regenerated after each real card. One sentence went into `docs/PRIVACY.md`, one Status bullet into `README.md`, and one line each into the `AGENTS.md` Layout and Commands sections.

Nothing on the card path changed or imports the new package. A test walks the source tree and proves the import half: no file outside the new package imports it.

## Why this exists

Five outside reviewers voted for it unanimously (GPT Sol 6.1, GPT Terra 6.1 and GPT Astra 6 through Codex, Muse Wonder Full, and Claude Code's advisor). All four outside reviewers said one thing would convince them: evidence of what Meta's models added beyond deterministic code, including where they added nothing.

## What review found

Claude Code read the diff, ran the acceptance tests, and tried to break the new code from scratch scripts outside the Muse sessions. Each fix went back through a Muse session, with a failing test first. Found:

- The proof's GET requests sent no key, so my real server answered 401. The tests had missed it because their fake server asked for no auth. The fake server now answers 401 without the exact key, on every route.
- An empty `running` list refused instead of reading as the normal nothing-loaded state.
- The canary test exempted about 33 columns and planted nothing in claim text, fact ids or ledger detail, so it could not catch the leak it existed for. It was rebuilt with four exempt columns, each with its reason.
- A card with no side rows, and malformed passes, printed false zeros instead of the word `unknown`.
- A `--fresh` run ending in no card still printed the older card's send outcome.
- Model ids could print a username from `/home/<other>`, a bare host, and a hyphenated hostname. The rule now refuses all three.
- Deep JSON printed a traceback instead of a closed code.

Claude Code then ran a mutation pass on a throwaway copy: 45 small changes to the new modules, one at a time. The tests caught 35 at first, and the ten survivors each got a test, including the export's connection opened read-write and the proof reading the clock as Madrid wall time. All 45 are caught now.

## Checks run outside the repo

What Claude Code ran on the final tree outside the sessions is in its report to the coordinator, and this note says only this much: the export's numbers matched an independent recount on two ledgers the real orchestrator wrote during Ticket 13's live test on made-up data, and on a scratch copy of my real store, with Wonder and Telegram faked, and no string from the store's text cells reached the line beyond the closed words.

## Not verified

No real card exists at this commit, so the log is empty. The proof's chat call has not run against real Glimmer in this tree unless a later note says so.
