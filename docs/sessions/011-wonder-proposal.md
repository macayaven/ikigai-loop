# Session evidence — 011-wonder-proposal (2026-11-01)

Ticket 11 only: the Wonder proposal step. One guarded call per goal for the next free hour, with every draft gated, one retry, and a labelled fallback or noop otherwise. This note summarises the work; the raw session exports are kept privately.

Sessions, all headless, started by Claude Code. Plan on muse-wonder-1.0 (effort high). Implementation and review fixes on muse-spark-1.3 (effort medium). The last sessions ran in Contributor mode as `muse-spark-1.3-contributor`, on this public repo and made-up data only. The product client never does that: it forces `--contributor-mode off` and refuses contributor ids.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, and `git` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Drawn from the plan Goal and Success Criteria. The model proposes at most one commitment per goal, and the step can prove everything it sends from my own data:

- `framework/proposal/`: the pure core and two edge clients. `schemas.py` (narrow draft, fallback, hand-built response schema, sentinel parsing), `hour.py` (free-hour picking, allowed windows, busy list, fallback window check), `prompt.py` (offerable deltas, the exact Wonder prompt, one-pass filler), `assembly.py` (draft to full briefing), `core.py` (`propose`, the seam entry point, repair loop with one retry), `defaults.py` (the product's default model and effort, read by the CLI and by Ticket 15b), `muse_client.py` (headless Muse Code, the transport the product uses), and `client.py` (the Model API transport, for anyone with a key).
- Ticket 17a landed `framework/verify/` first, so I import `repair_loop` from it and write no copy.
- `framework/store/proposal_store.py`: append-only attempts and results, same-slot re-runs under suffixed keys, parent reads for the next run, and the first-draft failure report from one named SQL query.
- `framework/cycle/`: `forbidden_literals_for` plus `run_proposals` (resolve the cycle, rebuild public and private facts, pick one hour, propose per profile, record all), and the `propose` CLI subcommand with the exact line format and the exit-2/exit-1 rules.
- Gate additions: `slot_window_codes`, `scan_outbound_text`, and the public word-set names (`ADVICE_WORDS`, `ADVICE_PHRASES`, `UP_WORDS`, `DOWN_WORDS`, `PERIOD_WORDS`), with `_l1_slot_and_interval_checks` calling the slot helper so gate and core share one truth.
- Glimmer addition: public `private_free_text_values` over the existing leak list, re-exported.
- Store addition: `FactStore.fetch_latest_cycle` (greatest instant, then run, then cycle id), so the seam can pick up where the last cycle stopped.
- Export set: `ProposalDraft`, `ClaimDraft`, `FallbackProposal` join `EXPORTED_MODELS` with their three `schemas/*.json` files.
- Eval: `evals/proposal_cases.py` (the 37 cases, P1-P37, single source of truth) and `evals/proposal_gate.py` (one sample per case, deterministic replay scorer), wired into `EVAL_FILES`.
- Tests: ten new files; the frozen prompt snapshots byte-pin both rendered outputs from the plan.

## Where this differs from the ticket

Four review decisions landed in the plan text before implementation, and the plan carries them now:

- `propose` takes no `profile_name`; it calls `build_prompt` with `profile_name=profile_id.capitalize()`, so `builder` reads `Builder` and `disconnect` reads `Disconnect`. The seam takes profile id strings, and the CLI never opens `profiles/*.md`.
- Forbidden raw literals travel on each `WonderRequest` (`forbidden_raw_literals`, default empty), because the client is built once and the literals depend on `as_of`. `MetaClient.complete` scans with the request's literals and takes no literals argument. The public helper `forbidden_literals_for` holds the window query; the seam uses it for the context and the CLI uses it for `load_commitments`.
- The prompt filler is local to `framework/proposal/prompt.py` (`_fill` stays private to Glimmer); `strip_feed_title` is imported. Prompt label order is shortest first with equal lengths in reverse alphabetical order, which is the order the frozen snapshot pins.
- The prompt says "Cite a fact through fact_ids, not by restating its raw values", in the template and the rule-15 line.

Two smaller readings worth recording: `FallbackProposal` embeds `Commitment`, which keeps its optional `tag`, so the all-required recursive walk covers the two draft models and the fallback only at its own level. `latest_proposal` is strictly before the slot, so a same-slot re-run never reads itself as its own parent.

The headless command gained `--json` and `--preset empty` over the one I first tested, and the child runs with the temp workspace as its working directory. The default preset hands the model `read_file` and `search`, which read outside the workspace by absolute path even under `--disable-shell --disable-write`, and that read would happen after the outbound scan. With the empty preset a tool call comes back as an unknown tool. `MetaClient` stays for anyone with a key, and nothing in the product calls it.

## Review

Claude Code reviewed the plan before implementation (the four decisions above), then reviewed the first implementation pass and found sixteen problems, then ran one more round with five items, and a last round once the transport moved to Muse Code.

The sixteen, each as problem, then the fix:

- The free-hour picker raised inside the autumn clock change, so I made it round in the local zone and compute the block in UTC.
- A blocked or unavailable retry lost the first attempt's record, which broke the first-draft denominators, so I record every attempt with its codes.
- Deltas ran over all snapshot metrics, so I limited them to the offered set.
- `IKIGAI_SUBJECT_ID` was required even with the flag, so I let the flag satisfy it.
- Contributor refusal ran after the environment checks and pydantic text could reach stderr, so I moved refusal first and parse the clock flags before opening any store with fixed one-line errors.
- A cycle id of another subject ran on that subject's facts, so I fail it exactly like an unknown cycle.
- `PARENT_WITHOUT_DELTAS` and `CYCLE_STALE` were dropped on some results and doubled on one, so I carry each exactly once on every result.
- Policy text kept its markers, so I strip it before it enters the block while braces pass through.
- The first-draft report had no per-model fallbacks or noops, so I count them per model and effort.
- The source scan was near empty, so I pin every network token to `client.py`.
- Float-noise values printed as integers, so I keep two decimals and compare the zero rule by value.
- Blank claim text passed, so I send it down the unparseable route.
- Over-long claims and links or markup passed, so I fail them with fixed messages that never echo the text.
- The prompt wording changed after live measurements, so I taught the new rules and made the up and down check a subset test.
- A dropped connection cost a card, so I re-send it once after a short pause with identical bytes and a single scan.
- The README and plan needed to follow, so I updated them to say what the code does.

The next round's five, in the same shape:

- Two prompt lines were not the measured wording, so I restored them exactly and updated the plan, the snapshots, and the gate-checked examples.
- A reset during send arrived wrapped and read as a transport error, so I unwrap `URLError` after `HTTPError` under the same re-send rules.
- A claim with a carriage return or newline passed as plain, so I fail it because the card's first line must be single line.
- Minus zero printed a sign after rounding, so I strip it while keeping every other shape.
- This note said kept and already about broken things and claimed one session did it all, so I rewrote it to name each round.

The fixes were implemented by muse-spark-1.3 at medium in headless sessions Claude Code started, and the first fix session was cut off by a network error and the second finished the list.

Moving to Muse Code and measuring it live found eight more, in the same shape:

- The default preset let the model read files outside the workspace, so I added `--preset empty` and checked on the Spark that a planted instruction gets no tool: 4 runs, 0 tool results, the canary file never in a run.
- A failure creating, writing or removing a temp file could escape as a raw `OSError`, even after a good reply, so all of them take the unavailable path with the closed reason `temp files`.
- A run that resolved to a contributor model would have been accepted, so the client now fails closed on the model the run's own events report, with the closed reason `contributor model`.
- A personal rules file goes into every call and no flag removes it, so each attempt stores whether one was present, never its contents.
- 22 of 30 first claims said only that the commitment fits or suits the hour, and 17 of 30 cited a whole-window total, so the prompt now asks what the cited number or fact leaves undone or overdone and how the commitment answers it. After the change 0 of 30 say that and all 30 cite a period metric.
- A test with a 2 MB run of one letter sat in the gate's text scan for 16 minutes before it was killed, because that scan is quadratic on one unbroken run of word characters, and the client's timeout can't stop it since the child has already exited. A scripted claim of 160,000 x's took 130 s for its two attempts. So a reply over 64,000 characters now takes the unparseable path before the gate. The longest of 181 real replies was 1,443 characters, and a claim of 63,500 x's, the worst the cap lets through, costs 20 s for its two attempts.
- The product's default model ended up in the pure core, which a source test forbids, so it moved to `framework/proposal/defaults.py`.
- This ticket's own copy of the repair loop and its test went away when Ticket 17a landed, so there is one retry loop in the repo.

## Acceptance tests

Claude Code ran these on the final tree outside the Muse sessions, with no key in the environment. The numbering is the plan's.

| Test | Result |
|---|---|
| AT1 | 16 passed |
| AT2 | 24 passed |
| AT3 | 16 passed |
| AT4 | 38 passed across the 37 cases plus the count check |
| AT5 | 46 passed, the client's canaries and the shared repair contract |
| AT6 | 5 passed on the filter |
| AT7 | 20 passed |
| AT8 | 1 passed on the filter, the exact first-draft numbers |
| AT9 | 21 passed |
| AT10 | `make eval` exit 0: hello 1/1, briefing 58/58 x4, glimmer 30/30, proposal 37/37 |
| AT11 | `make check` exit 0: ruff clean, 206 files formatted, pyright 0 errors, 1665 passed and 1 skipped, gitleaks no leaks. The skipped test is the live one, which passed when run on its own |
| AT12 | On the base at `96a4dff` with `tests/test_proposal_core.py` copied in: collection fails and `framework/proposal` is absent |
| AT13 | One commit on the branch, not pushed, checked after the commit |
| AT14 | 63 passed, the Muse Code client with a fake runner |

All test data is synthetic, and the real commitments file and the path in `HIDDEN_CRITERIA_DIR` were never opened. Tests make no network calls. The live runs below are the only model calls, all on made-up data.

## How Wonder gets called

- Wonder runs through Muse Code headless on my subscription: `muse exec`, one fresh empty temp workspace per call, prompt and schema files at 0600 removed afterwards on success and on failure, no tools, no session log, and a wall-clock timeout that kills the child.
- The Model API transport is still in the code for anyone with a key, behind `--transport api`. Nothing here calls it live. My own key is revoked.
- `muse-wonder-full-1.0` isn't on the Model API, so the `api` transport can't reach it. That's a concrete reason the product runs through Muse Code. Plain `muse-wonder-1.0` at high stays the default.
- What the harness adds to each call: its own instructions, the real date, the temp workspace path and a catalog of skill names, about 16,000 input tokens in all, of which 9,844 usually came from cache. On a host with a personal rules file (`~/.config/muse/AGENTS.md`, or under `XDG_CONFIG_HOME`) it adds that too, and no flag removes it, so each attempt row stores whether one was present and never its contents. The evidence below comes from a host without one, the Spark. The one row from my Mac, which has one, is labelled.
- Temperature and max_tokens can't be set on this transport, so I don't pretend to. Effort can.
- The harness states the real date, and the prompt states the hour. I set them apart on the Spark in 3 calls, with hours on 2026-10-31, 2026-03-10 and 2027-02-14 against a real date of 2026-11-01, and the model took its date from the prompt's hour in all 3. In production they're the same date.
- `--no-session-log` works. Positive control: a marker in a logged run appeared in 5 files under Muse's data folders on the Spark and in 3 on my Mac. A marker in a no-log run appeared in 0 on both.
- Each attempt row records the transport and the `muse --version` line, because the harness prompt can change between versions. Every Muse Code row below reads `Muse Code 1.4.14 (1.4.14-R7309.1)`, and no row reports a `-contributor` model, including on my Mac, whose settings default to one.

## Live measurements

All on made-up data, through the real CLI path. The gate is the one on `main` at `45326d8`. First drafts passing is the number that matters most, because it says whether the prompt teaches the gate.

| Run | Where | Model at high | First drafts | Passing the gate | Seconds min / median / max | Input tokens median (cached) | Output tokens median | Picks |
|---|---|---|---|---|---|---|---|---|
| Before the last prompt change | the Spark | muse-wonder-1.0 | 30 | 29, and the retry fixed the other | 11.1 / 16.4 / 23.9 | 19,249 (9,844) | 2,607 | Builder: parser 15. Disconnect: walk 11, rest 4 |
| **Prompt as committed** | the Spark | muse-wonder-1.0 | 30 | 30 | 11.8 / 17.9 / 25.1 | 19,350 (9,844) | 2,818.5 | Builder: parser 14, review 1. Disconnect: walk 14, family 1 |
| Prompt as committed, with a policy block | the Spark | muse-wonder-1.0 | 6 | 6 | 9.8 / 12.5 / 26.4 | 19,285 (9,844) | 2,345.5 | The policy's rank 1 in 6 of 6 |
| Comparison: Wonder Full, prompt as committed, same cases | the Spark | muse-wonder-full-1.0 | 10 | 10 | 11.3 / 36.5 / 53.7 | 19,353 (9,844) | 2,532 | Builder: parser 5. Disconnect: walk 5. All 10 match plain Wonder's majority pick on the same case |
| Comparison: a host with a rules file, prompt as committed | my Mac | muse-wonder-1.0 | 12 | 12 | 9.8 / 16.1 / 25.4 | 19,039 (9,844) | 2,303.5 | Builder: parser 6. Disconnect: walk 6 |
| Comparison: earlier prompt, the direct run's data, Muse Code | the Spark | muse-wonder-1.0 | 12 | 12 | 10.2 / 17.3 / 32.2 | 18,983 (9,844) | 2,604.5 | Builder: parser 6. Disconnect: walk 4, rest 2 |
| Comparison: same earlier prompt, direct Model API | direct | muse-wonder-1.0 | 17 | 17 | 13.2 / 17.3 / 25.9 | 2,856 | 2,855 | Builder: parser 9. Disconnect: walk 5, rest 3 |

- A scratch run with the same prompt bytes, just before the final tree, also got 30 of 30.
- The harness doesn't change the picks, as far as this much data can say. Same data and same prompt: Muse Code picked parser 6 of 6 and walk 4, rest 2, and the direct API picked parser 9 of 9 and walk 5, rest 3. With a policy block both took rank 1 every time, 6 of 6 and 12 of 12. Time per call matches too, with a median of 17.3 s on both. What changes is the input tokens, about 19,000 against about 2,900.
- The prompt change did narrow one thing. Disconnect went from walk 11, rest 4 to walk 14, family 1, probably because the prompt's example says "time away from screens".
- The direct runs stay as a labelled comparison: 114 calls to muse-wonder-1.0 at high across four prompt versions, 107 of them from a scratch harness and 7 through the real CLI. First drafts passing by prompt version: 15 of 18, 53 of 54, 16 of 16 plus 2 dropped connections, and 17 of 17. Through the real CLI, 5 of 6 first drafts passed and the retry fixed the sixth.
- What Wonder wrote, read as I'd read it on my phone. Before: "Programming was 17.00 hours and fits building work this hour." After: "Chat was 3.95 hours in the last period, so this hour goes to time away from screens." and "Deep was 0 hours in the last period, so this hour goes to building." The first claim now gives a reason with a period number, and 69 of 143 claims cite a fact against 4 of 143 before, so `Why?` has real statements to show. It isn't good writing yet: all 30 first claims copy the example's "so this hour goes to", and some reasons are thin, like "Video was 4 hours in the last period, so this hour goes to building."
- The live acceptance test passed on the Spark with no key in the environment: Builder 11.5 s and 1,819 output tokens, Disconnect 12.8 s and 2,355, both `kind=proposal`, one attempt each.

## Known gaps

- The stricter gate text rules of Ticket 10b haven't landed, so nothing above ran live against them. Re-gating the stored first drafts offline on that branch as it stood on Nov 1 gave 29 of 30 on the committed prompt's Spark run and 12 of 12 and 6 of 6 on two smaller runs. Those failures would go to the retry.
- The product path hasn't run on real data. Everything above is made up.
- I never saw a usage limit on this transport. By the code it would be a non-zero exit, so a fallback, and the attempt row can't tell it apart from any other non-zero exit.
- Wonder Full's picks rest on 10 calls, and its median time is twice plain Wonder's.
- On the date check above, with a made-up schema that had free strings, 2 of 3 replies ran on past the right date into nonsense, one of them to 154,292 bytes. None of the 176 first drafts on the product schema did. The 64,000-character cap and the claim length rule are there if it comes.
- The gate's arithmetic check rejects about a third of correct deltas on minutes-over-60 values because of float noise, so this step only offers deltas that survive the round trip. The first-draft failure report has shapes only Ticket 16 will read.
- The gate's text scan stays quadratic on one unbroken run of word characters. The cap bounds it for replies and nothing changes the scan itself.
