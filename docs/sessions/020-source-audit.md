# Session evidence — 020-source-audit (2026-11-02)

Ticket E2 only: an independent source-to-card audit of my GitHub numbers. It recounts my pull requests and pushes from a public GitHub snapshot with code that imports nothing from the product, then walks the recount through the stored metric, the fact statement, and the delivered card. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code, in Contributor mode on this repo and made-up data only: `e2-plan` and `e2-plan2` on muse-wonder-1.0 (effort high); `e2-impl`, `e2-fix1`, `e2-slim`, `e2-fix2` and `e2-fix3` on muse-spark-1.3 (effort medium); then `e2-probe` on muse-spark-1.3 (effort low); then this one, on muse-spark-1.3 (effort medium). Prompts and review by Claude Code.

`~/.local/bin/muse --version` (paperwork session, first line, verbatim):

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, `git` and `make` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What it does and why

The gate checks a claim against reference data, and it cannot catch reference data that is wrong and agrees with the prose. That happened once, and [docs/sessions/009d-pr-count.md](docs/sessions/009d-pr-count.md) records it. The audit recounts from a public GitHub snapshot with code that imports nothing from the product, and walks the number through four stages: source, stored metric, fact statement, delivered claim.

The package is `source_audit`, with five commands: `fetch`, `recount`, `compare`, `run`, and `negative-control`. The fetch is public by construction and uses no token. The scope is user-wide, with a per-repo breakdown. Pushes have no independent source.

## Sessions

In order, all headless, started by Claude Code, in Contributor mode on this repo and made-up data only: `e2-plan` and `e2-plan2` on muse-wonder-1.0 (effort high); `e2-impl`, `e2-fix1`, `e2-slim`, `e2-fix2` and `e2-fix3` on muse-spark-1.3 (effort medium); then `e2-probe` on muse-spark-1.3 (effort low), which changed nothing and only ran tests under memory caps to look for the growth described below; then this one, on muse-spark-1.3 (effort medium).

`e2-fix3` was stopped at 04:41 when the host stopped every session at once. Its work was in the tree and was kept, and it was checked afterwards. The stop came from one python process that grew to about 88 GB during that session's full test run inside the Muse sandbox. One minute earlier the same suite had finished there normally, and afterwards neither I, with memory caps outside the sandbox, nor `e2-probe`, with caps inside it, could make any file grow: the audit's own tests peak at about 70 MB, and the whole suite at about 0.5 GB outside and 1.3 GB inside. So the cause is not found, and the note says so. Every later session ran inside a memory-capped unit.

## What my review found and changed

Review caught whole classes of defect, and each one got a test. The real API pages, so pages come back short and errors come back that the fakes never raised. The audit double counted in its own per-repo breakdown. Rows in the open hour caused false disagreements. A sum metric would have failed every normal card. A coverage gap let later stages through unchecked. And some tests could not fail at all.

Then I broke the package one line at a time in a throwaway copy, 90 breaks in all, and every break now fails a test. The first two rounds had 5 of 50 and 17 of 41 surviving, and each survivor got a test.

## What real data showed

All counts are public GitHub counts. Every store run used a consistent scratch copy, removed afterwards, and printed nothing but counts.

- Live run of `run` at Nov 2 11:04 Madrid against a scratch copy of my store. Window Oct 30 10:00 to Nov 2 10:00 UTC. Stage 1 for `prs`: match, 0 in earlier, 1 in prior, 21 in last, 22 in total; the pull list and the feed's opened rows agree. Pushes: 0 in every period. The activity list showed 22 new branches and 22 merges in the window with no `PushEvent` behind them, information only. 22 stored opened rows counted, none collected late, none missing from the public snapshot. No cycle or card existed yet, so stages 2 to 4 were unavailable, exit 3.
- The product's own code-only cycle, the real `run_cycle` with no model, on a scratch copy of the same rows: stored 0, 1, 21, total 22, and the code fact said pull requests rose from 1 in prior to 21 in last. Stages 1 to 3 match.
- The pre-9d counting rule restored on those real rows, on another scratch copy: stored 0, 2, 42, total 44, fact 2 to 42. FAIL at stored and fact, against a source of 22.
- A dress rehearsal through the real `run_slot` at the pinned 22:30 slot of Nov 1, on a scratch copy, with a fake Telegram, no model, and a canned claim built from the stored numbers: `prs` PASS with source, stored, fact and delivered all 3, 0, 16; the chart's series 6, 0, 16 matched the recount of pushes plus pull requests; the since line said 16 and the recount said 16.

## The first real card

At 13:35 on Nov 2 I ran the audit on the first real card, the 13:30 slot, against a scratch copy of my store. `prs` passed at all four stages: 0 in earlier, 1 in prior and 24 in last, the same at the source, the stored metric, the fact statement and the delivered card. The card's chart matched the recount of pushes plus pull requests at 0, 2 and 24, and its since line said 24 against a recount of 24. 25 stored opened rows were counted, none collected late, none missing from the public snapshot. Delivery was proven by the slot ledger. `pushes` and `pushes_plus_prs` were INCOMPLETE by design, because pushes have no independent public source. The snapshot was taken 36 minutes after the window closed, so the feed hadn't settled, and the run after 19:00 is the settled one.

## The first catch

Before Ticket 13 merged, the since-line check was run against Ticket 13's own since rule on a scratch copy of my store. The first real card would have said "First card, last 24h: 32 pushes + PRs" where the plain count over those hours was 17, because 15 rows dated Oct 29 to 31 were first collected after the card's 24-hour bound and the window-difference rule counted them as new. Ticket 13 changed the rule to one plain count over floored hours before it merged, and the audit compares against that rule. The fifth negative-control scenario reproduces it.

## Negative control

`make audit-control` run in this session:

```text
scenario=clean source=0/0/8 stored=0/0/8 fact=-/0/8 delivered=-/0/8 rows_counted=8 rows_not_in_snapshot=0 verdict=PASS expected=PASS
scenario=doubled source=0/0/8 stored=0/0/16 fact=-/0/16 delivered=-/0/16 rows_counted=8 rows_not_in_snapshot=0 verdict=FAIL expected=FAIL
scenario=planted-row source=0/0/8 stored=0/0/9 fact=-/0/9 delivered=-/0/9 rows_counted=9 rows_not_in_snapshot=1 verdict=FAIL expected=FAIL rows_not_in_snapshot=1
scenario=planted-snap source=0/0/8 stored=0/0/8 fact=-/0/8 delivered=-/0/8 rows_counted=8 rows_not_in_snapshot=0 verdict=FAIL expected=FAIL duplicates=2
scenario=since-line stated=16 recounted=8 verdict=FAIL expected=FAIL
```

## Limits

One family against one source. The feed holds 300 events and 30 days, with up to 6 hours of latency, and I measured the gap: on Nov 1 the feed showed no push for 17 merges and 17 new branches that the repo's activity list did show. Pushes are not independently recounted. Other repos are feed-only. Delta claims, fact evidence lists and direction words are not audited. Screen and calendar numbers are not touched. A paraphrase the parser cannot read is unavailable, not wrong. The audit reads the store as it is at that moment.

## What isn't verified

The first real card, the 13:30 slot, has been audited at all four stages; see "The first real card" above. The real-store runs used scratch copies and, for the dress rehearsal, a canned claim with a fake Telegram. What stays unverified: the since line on a real second card, the settled run after 19:00, and a delivered claim the parser can't read, which has not come up yet.

## How I run it after a card

From the repo root, with placeholders for the user, repo, store path and output folder:

```text
python -m source_audit run --user <login> --repo <owner/name> --scratch-copy-of <store> --card latest --out <folder>
```

Exit 0 needs every chosen metric to pass, and with `--metric all` the best possible is 3, because `pushes` and `pushes_plus_prs` cannot pass by design, so the `prs` verdict line is the one to read first. Re-run after the feed settles, six hours after the window ends.

## Held-out criteria

I never opened the path in `HIDDEN_CRITERIA_DIR` in this session.
