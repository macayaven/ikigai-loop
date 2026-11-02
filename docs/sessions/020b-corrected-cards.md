# Session evidence — 020b-corrected-cards (2026-11-02)

Headless, started by Claude Code, Contributor mode, this public repo and made-up data only: `e2b-plan`/`e2b-plan2` on muse-wonder-1.0 (effort high); `e2b-impl`, `e2b-fix1` and this commit step `e2b-commit` on muse-spark-1.3 (effort medium). Claude Code wrote the prompts in prose, reviewed every diff, ran the re-audit and export on scratch copies of my store outside those sessions reading counts and codes only, created the branch, and typed nothing in this repository. The version command named in the 020 note prints this first line, verbatim:

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Why I asked for it

The 20:30 slot on Nov 2 was the first real slot with a voice correction: the slot card plus a corrected card replacing it. The audit said FAIL for pull requests at stage 4, on the slot card's fourth statement, though every number on both cards was right. Cause: the audit joined a card to the latest briefing row per goal at the slot, and the re-proposal had written a newer row for one goal — so the slot card was read against the corrected card's briefing, its since-last statement matched neither the deltas nor the audited claims, and the parser read its small change as the 72-hour total. The provenance log, separately, recorded no voice notes at all.

## What changed

Each slot now audits every delivered card against its own rows: the slot card as before, plus each corrected card reaching the slot card through its replacement chain with a voice-note row naming it as the new card — the delivery proof. Per goal a card gets the latest briefing row at the slot whose card claims all appear word for word among its statements, else the latest row. Stage 4 runs once per card, one line and one verdict line per card when a slot has more than one, folded so every card must match for PASS. One-card slots print byte for byte what they printed before. A change sentence with "by" after a change word is never a count, at stage 3 or 4. The provenance log gains one last field: one entry per closed voice note at the slot, in message order — operation word, whether a new card was sent, time in whole milliseconds, nothing else.

## What was measured

Same snapshot before/after, scratch copy of my store: the 20:30 slot at its card instant, snapshot fetched at 20:47. Main: pull requests FAIL, stage 4 CARD_NUMBER_WRONG on the slot card's fourth statement, one delta counted. Branch: pull requests PASS, stage 4 matches on cards 1 and 2, four deltas counted; pushes INCOMPLETE (no independent source at stage 1); summed metric INCOMPLETE (stage 3 unavailable by design); exit 3. Stages 1–3 unchanged: earlier 0, prior 13, last 24. 22:30 also had a correction: main INCOMPLETE at stage 4 with FACT_UNPARSED from the same wrong join; branch PASS, both cards matching. Its pushes and summed metric are FAIL before and after, from stage 2 — two push rows reached my store after that slot's cycle was made (ROWS_COLLECTED_LATE), a separate finding untouched here. One-card slots (13:30, 15:30, 18:00) byte for byte the same before/after. Provenance export: existing fields identical on all five lines; new field empty on one-card slots, two entries on 20:30 (done with a new card in 24,891 ms; asked with no new card in 12,252 ms), one on 22:30 (done with a new card in 17,104 ms). Gate closure: same 47 files and hash, starting 907b228d.

## Tests

New audit file: 10 tests; new provenance file: 7. The canary test now plants a canary in every text column of the voice tables. Each new test failed on main for the reason the plan gives, except the guards the plan names. `make check` on the reviewed tree: 4,471 passed, 1 skipped; ruff, format, pyright and gitleaks clean. Claude Code also ran made-up break cases from outside the repo — no voice proof row, voice table with no new-card column, correction at another slot, two corrections in a row, re-proposal on a second cycle, planted text in the voice table — each behaved as the plan says, nothing planted reaching the output.

## What is not verified

No settled re-run yet: snapshot under 6 hours after the window closed, so feed_settled is false. The published provenance log is not regenerated here; the job after each card does that, and the 20:30/22:30 lines gain their voice entries then. A corrected card with its own slot-cards rows is exercised only on made-up rows — none in my store so far has any. On a corrected slot sides still describes the latest result row per goal, the re-proposal's; that pinned meaning stays, and the new field now shows a correction happened.
