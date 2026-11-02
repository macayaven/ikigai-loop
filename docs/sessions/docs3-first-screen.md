# Session evidence — docs3-first-screen (2026-11-02)

The top of `README.md` rewritten for a stranger: what it is, how it works, try it, the checker, then what works and what doesn't. Docs only; no behaviour, schema, fixture or test change. This note summarises the work; the raw exports are kept privately.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## What changed and why

A no-context reviewer read the old opening as a riddle: it changed audiences before showing the product and asked the reader to guess words like "ruling", "Glimmer" and "Wonder". So the top now goes in stranger order: one sentence saying what it is, two sentences of status true at the moment of merge, how it works in plain words, Try it, the checker, what works and what doesn't, what the loop needs, the words used below, and the design list renamed `The pieces`. The Status lines the merged code had made untrue are fixed against the code: Glimmer code facts ran on my real store for the first card; the orchestrator replays the learner at every slot and my first tap is the first choice it learns from; the first real card went out through the Telegram code with my tap stored; the orchestrator calls the Wonder step at every slot; the Glimmer R1b row ran after the others under the same gate; and the closing paragraph keeps its synthetic-run sentences and says the first real card went out on time with its pull-request figure recounted from GitHub. "Choice" and "tap" replace "ruling" throughout the README.

- `README.md`: the new first screen (title, approved sentence, status, `How it works`, `Try it`, `Check your own agent`, `What works today, and what doesn't`, `What the real loop needs`, `Words I use below`, `The pieces`), then Status with the six fixes above and its counts unchanged, and everything after untouched.
- `docs/sessions/docs3-first-screen.md`: this note.
- `CONTRIBUTIONS.md`: the Docs 3 entry.

The opening sentence and the How it works paragraph were drafted by Claude Code in a working doc, then I edited and approved them on Nov 2. The "Built during the hackathon" sentence changed: it claimed Muse Code wrote all the code, and CONTRIBUTIONS.md names exceptions. The order and the plain words answer GPT Terra 6.1's no-context test, run through Codex, and section 3 of GPT Astra 6's pre-mortem, also through Codex. GPT Sol 6.1, GPT Terra 6.1, GPT Astra 6, Muse Wonder Full and Claude Code's advisor voted for this pass unanimously. The status facts about the first card come from the live run's logs, and the recount from the source audit run at 13:35; the audit has since merged as Ticket 20 and the README points to its note.

Prompts and review by Claude Code. Implementation on muse-spark-1.3 (effort medium), in a headless session Claude Code started, with the commit step at effort low, in Contributor mode on this public repo. The raw exports stay private.

Every `uv`, `pre-commit`, and `git` command in this session ran with the caches pointed at the clone's own git directory, written as an absolute path.

## Review

Claude Code's review found, and Muse Code changed: R10 wasn't registered where the README said; the two model names had lost who made them; the Telegram sentence; the unnamed slot command; this note's quote and command-prefix sentences; and the `CONTRIBUTIONS.md` entry's missing credit.

Known gap: `docs/r1b.md` does not hold the Glimmer row yet.
