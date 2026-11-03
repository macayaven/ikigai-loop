# Session evidence - 026-domain-packs (2026-11-04)

## What changed

A new, isolated package, `framework/domains/`, runs a domain pack: one JSON file that declares a goal, commitments with a rule each, CSV signals and metrics for a domain that isn't mine. It pins the source files by sha256, checks declared identities, builds one week's metrics, asks Muse Wonder for a commitment with reasons through the existing proposal client, and checks the reasons with `check_claims` from `framework/verify/hardened.py`, with at most one repair. The repair loop has the same shape as `repair_loop` in `framework/verify/repair.py` but is written inline in `run_window`, so a transport error on the repair keeps the first attempt's record; `repair_loop` drops finished attempts when the generator raises. Two packs ship, bike-share operations and home energy, each with its own standard-library oracle and a frozen evaluation. No module that existed before this ticket changed: `git diff b8e75aa HEAD -- framework/` lists only files under `framework/domains/`. The plan is [docs/plans/026-domain-packs.md](../plans/026-domain-packs.md) and the results are in [docs/domains.md](../domains.md).

## Sessions

All Muse Code sessions ran headless in Contributor mode, on this public repo and public data only, started by Claude Code from prose prompts. `muse --version`: Muse Code 1.4.14 (1.4.14-R7309.1). Times are Madrid. Tokens are the sums the Muse session logs report; the logs stay private.

| Session | Model, effort | Wall time | Commit | What it did | Input tokens (cached) | Output | Reasoning |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Plan | muse-wonder-1.0, high | 23:29 to 23:34, Nov 3 | `1112e36` | plan, pinned data, attribution, pack, fixtures, five failing acceptance files | 4,697,641 (4,378,553) | 51,294 | 19,082 |
| Implementation | muse-spark-1.3, medium | 23:35 to 23:53 | `b451458` | package, oracle, evaluation commands, expected answers, frozen cases | 12,832,780 (12,294,883) | 131,578 | 76,723 |
| Review fixes | muse-spark-1.3, medium | 23:56 to 00:08 | `d303c74` | eight fixes from Claude Code's review, refreeze before any score | 7,745,287 (7,393,263) | 92,188 | 56,882 |
| Fact wording | muse-spark-1.3, medium | 00:11 to 00:14, Nov 4 | `ffdd615` | facts that survive quoting, `lint`, fence tests | 2,594,045 (2,287,784) | 36,997 | 23,206 |
| Energy pack | muse-spark-1.3, medium | 00:25 to 00:27 | `9685756` | second pack, its oracle, generic freeze path, frozen cases | 2,588,017 (2,350,647) | 43,326 | 24,073 |
| Docs | muse-spark-1.3, low | this session | this commit | this note, docs/domains.md, results files, CONTRIBUTIONS.md, one README sentence | not counted here | | |

## Acceptance tests

The five acceptance files from the plan session failed at `1112e36` with `ModuleNotFoundError: No module named 'framework.domains'` (four files) and six failures for missing files (the evaluation file). At this commit they pass, with the extra, fence and energy files: 70 domain tests at `ffdd615`, then the energy tests on top. Claude Code ran the full suite outside the sessions; the result is in the pull request.

## Review rounds

Claude Code's review of `b451458` found, and Muse Code fixed in `d303c74`: findings stopped at the first commitment error instead of also running the checker; a transport error on the repair attempt threw away the first attempt's record; the generic runner hardcoded the bikes fact id; the commitment rule read awkwardly and window metrics had no definitions in the prompt; two planted direction cases duplicated others word for word; the summary compared commitments with the run's own expected value instead of the oracle's. The first frozen file (sha256 `b343ab40`) was never scored; the refrozen file kept the same 20 controls.

Two real proposals on the development weeks then showed my own fact texts were traps: "A busy day is a day with more total rentals than the declared threshold." fails because "a day" reads as a quantity, and the source fact failed on "CC BY 4.0". `ffdd615` rewords both and adds `lint`. Reruns on the same two weeks passed, one on the first draft and one after its repair.

After the runs, a cold read-only review by GPT Sol 6.1 through Codex reproduced every planted verdict and all 48 draft verdicts from the stored drafts, and found four tooling problems that Muse Code fixed in the last commit: a one-day window broke the checker input, `summary` counted duplicate or missing weeks instead of refusing them, `wonder` could resume onto records from another configuration, and the recorded commit didn't say whether tracked files had changed. None of them touches the four result files, which come from single uninterrupted runs of 7-day windows.

## Frozen runs

Claude Code ran `evals/domains.py` with no change to tracked files, only the untracked result files present, after writing the anchor (commit, cases sha256, prompt sha256, model, headline rule) in its private run notes. The repository shows that both cases files were committed before the results; it can't show when those notes were written.

- Bikes, commit `ffdd615`, cases `9978379d`: planted 60/60, controls 20/20, twins 60/60. Wonder: first drafts 13/20, repaired 6/20, still failing 1/20, transport errors 0/20, commitment matches the oracle 20/20, median first-attempt latency 13.2 s. Result files `bikes-planted.json` (`6e40b8c2`) and `bikes-wonder.jsonl` (`3e659ff0`).
- Energy, commit `9685756`, cases `d3fabda4`, run cold: planted 60/60, controls 18/18, twins 60/60. Wonder: first drafts 15/18, repaired 1/18, still failing 2/18, transport errors 0/18, commitment matches the oracle 18/18, median first-attempt latency 11.8 s. Result files `energy-planted.json` (`9859b72d`) and `energy-wonder.jsonl` (`5ec48686`).

Claude Code also checked all 20 bikes control values and six energy values with awk on the raw files; all equal.

## What isn't verified

GitHub CI until the pull request runs; a clean clone on another machine; packs written by someone else; wording beyond these templates and these 38 weeks; whether any decision here helps a real operator. Historical public data is not a user, and the planted errors are aimed at shapes the checker declares, so their full catch is expected.

I never opened the path in `HIDDEN_CRITERIA_DIR`, nothing under `evals/heldout/` was opened, and no test uses the network.
