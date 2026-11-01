# Session evidence — 017a-verify-claims (2026-11-01)

Ticket 17a only, the checks my gate runs on my own briefings, opened to any agent's JSON through one command or a browser page; this note summarises the work and the raw session exports are kept privately.

Sessions, all headless, started by Claude Code. Plan and two plan amendments on muse-wonder-1.0 (effort high). A one-line network probe, implementation, five review-fix sessions, the recipe's live run, the commit session and two sessions that amended the commit (one corrected a sentence, one rebased it on main), on muse-spark-1.3 (effort medium). One fix session stopped on a network error partway through, and the next one finished its list. The first recipe run was stopped from outside before it finished, for a billing reason that has nothing to do with the recipe; its partial output was set aside and the recipe ran again from a clean folder.

`muse --version`, run by Claude Code on the machine these sessions ran on, first line, verbatim:

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, and `git` command these sessions were told to run used `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Anyone shipping an agent over private data has my problem, because the agent states numbers and cites sources and nobody checks them before a person reads them, and my gate only understood my own Briefing type.

- `framework/verify/`: `verify_claims`, `load_input`, `VerifyInputError`, `Report`, `Violation` and `LIMITS_NOTE` over plain JSON. `claims`, `facts` and `metrics` are required; `labels`, `order`, `deny_terms` and `advice_words` are optional. It calls nothing in commitments, profiles, the store, Telegram or Meta.
- One appended public block in `framework/briefing/gate.py`, 56 lines added and 0 removed. No existing gate function, gate test, fixture or eval changed.
- A parity test: every case in `evals/briefing_cases.py` that the public shape can express gives the same verdict through the gate and through `verify_claims`: 18 mutants and 17 known-good. Each excluded case is named with its reason.
- The CLI, `python -m framework.verify` and `verify-claims`: exit 0 on pass, 1 on violations, 2 on bad input, `--json`, `-` for stdin.
- `framework/verify/repair.py`: `repair_loop` and `verify_and_repair`, the one repair loop in the repo, for Ticket 11 to import.
- A static page at `docs/verify/` that runs the same Python on the visitor's machine: Pyodide 0.27.7 from jsDelivr, `docs/verify/bundle.json` built by `make verify-page`, three example buttons, a CSP, no upload. `docs/.nojekyll`.
- `examples/verify/`: a worked case with a false number, its fix and a table of every field. `docs/ADAPTER.md` and `examples/verify/foreign/`: one prompt and one command that turn a stranger's output shape into this input. `adapter.py` and `test_adapter.py` there are the output of one live run of that recipe, with only `ruff format` applied afterwards.
- The README section `Check your own agent`, and what the check doesn't do, quoted from `LIMITS_NOTE`.
- Packaging: hatchling and a `verify-claims` script. Runtime dependencies are pydantic only, so a stranger's `uvx` installs 6 packages; the full app set was 87 when measured. Everything else moved to an `app` dependency group that stays on by default for local work.

## Where this differs from the ticket

The plan's Disagreements section (X1 to X7) and its section Amendments after code review (A13 to A29) each record the reading taken and why.

## Review

Claude Code reviewed the plan and the diff before the commit. Every number below was measured by Claude Code outside Muse's sandbox on 2026-11-01, on the final tree unless it says otherwise.

- Plan review, through two amendment sessions: direction order was read from `metric_refs`, which is the agent's own output under test; a single-ref direction carve-out and dropping `L1B_TOO_MANY_METRICS` each let a claim pass that the gate rejects; any-of labels became all-of; empty claims passed vacuously and duplicate ids went through, and both became bad input; a checked-in wheel went stale and needed the network in tests, so the page loads a text bundle; the install fell from 87 packages and 383 MB to pydantic only; the adapter recipe let an agent verify itself, so it now separates agent output from source data.
- Code review of the first build, through the fix sessions. A differential fuzz found one false-pass class: 306 of 39,222 generated claims, such as "PRs stood at 3 in prior and last", citing one period while naming another. The gate rejected them and `verify_claims` passed them; the checker now rejects them with the same code. Also: `facts` and `metrics` had empty defaults, the API raised tracebacks on some bad input, the docs claimed more than the check does, the recipe used a flag that doesn't exist, and `input-fixed.json` changed the records to match the agent, which is the exact mistake this tool exists to catch.
- Input that ran long, all fixed and capped: a depth check quadratic on an unclosed string (0.4 MB past 25 s), error de-duplication quadratic (100,000 bad claims, 22 s), 4.9 million bad items costing about 4 GB, a claim walking every series (100,000 series and 5,000 claims past 25 s), a 4 MB label word, and repeated searches for one word (3,660 entries, 43 s, now 1.4 s). A fixed list of kept text codes would have dropped a future gate rule without a sound, so now every code but advice reaches the report. The CLI gave tracebacks on closed streams; it no longer does.
- Test strength: Claude Code patched a throwaway copy of the code outside the repo, one token at a time, and ran the tests. On the first complete pass 169 of 188 changes were caught. On the final tree 179 of 188 were caught. The 9 left change nothing a caller can see: three flags on `exc.errors` whose extra fields are never read; a floor in the depth walk that only differs after the top value has closed, which is invalid JSON and exit 2 either way; the no-series sentinel as -1 or -2; `break` after the flag is already set; reading one more byte past the cap, on file and on stdin; and the `dup2` target on the closed pipe path, where nothing writes afterwards.
- Differential fuzz, gate against `verify_claims`, skipping only the one shape the plan excludes (M38). Final tree, two seeds: 39,246 and 39,252 claims compared, with 0 false passes, 0 over-rejections and 0 differing codes. Six more seeds on earlier fixed trees gave the same zeros.
- Attack scripts, outside the repo: 244 hostile-input rows through the CLI, 0 bad (each exits 2 or gives a clean report, never a traceback); 26 timing shapes built to run long, 0 timeouts, slowest 1.42 s. False passes that remain pass the gate too, and are listed under Known gaps.
- Drift proof, in a throwaway copy with the framework imported from the copy. 8 changes made the parity test fail: four gate rules switched off or narrowed (single-ref direction, value comparison, eligibility limited to 2 refs, claim without evidence), three arms changed on the verify side, and a new unclassified mutant in `evals/briefing_cases.py`. 2 changes to code both sides share did not, by design, because they move both sides together: removing `rose` from the up words, which the gate's own suites and the verify API tests catch, and a percent parsing change that leaves the value read unchanged, so nothing catches it and nothing changes.
- Browser, reviewer step AT10, headless Chrome on a loopback sub-path `/ikigai-loop/verify/` with the CSP on: 31 checks, 0 failures. Run stays disabled until load; the three example buttons' reports equal the Python API; requests went only to the page, the bundle and the pinned CDN address, and none after load; an XSS-shaped id rendered as text; 119 hostile rows through the page gave 0 differences from the Python API, slowest 4.87 to 7.55 s across reruns under load; 26 timing shapes through the page, slowest 3.27 s; no horizontal scroll at 390 px. Playwright's Firefox 157 and WebKit 27.2 builds on this Mac also loaded it and matched on all three examples.
- Load time, 5 fresh browser contexts, real CDN over this machine's connection, page and bundle from loopback: cold median 2.70 s (2.31 to 2.84), 7.6 MB by content-length; warm median 1.03 s. One earlier cold load took 15.55 s while the machine was busy.
- Stranger's path, in an empty folder with a fresh `uv` cache and the local clone standing in for the public URLs: `uvx --from` cold 2.26 s, 6 packages, exit 1 naming `L1B_METRIC_VALUE_MISMATCH`.
- Live recipe, reviewer step AT11, run once against `examples/verify/foreign/` with the command in `docs/ADAPTER.md` plus a session id: 49 s, exit 0, its tests passed first time (8 tests under `python3 -m unittest`). The session log shows 7 main model requests, 252,453 input tokens (197,030 cached) and 7,446 output tokens (4,824 reasoning). The result named the adapter file, test file, test command, 2 unconfirmed mappings and 7 assumptions. Piping its output through `verify-claims -` gave exit 1 with `L1B_METRIC_VALUE_MISMATCH` on `s1`.

## Acceptance tests

Run by Claude Code outside Muse's sandbox on the reviewed tree:

| Test | Result |
|---|---|
| AT1 | 92 passed |
| AT2 | 4 passed |
| AT3 | 332 passed; `gate.py` removed lines 0; other gate or eval files changed 0 |
| AT4 | 64 passed; `input.json` exit 1; `input-fixed.json` exit 0; `import inspect_ai` exit 0; `make eval` exit 0, 6 tasks success |
| AT5 | 9 passed; one `def repair_loop`, in `framework/verify/repair.py`; no briefing or Meta import in it |
| AT6 | 18 passed |
| AT7 | wheel built, 132 KB; isolated run from outside the repo exit 0; framework from site-packages; `sqlite3`, `jinja2`, `inspect_ai`, `icalendar`, `PIL`, `framework.store`, `framework.collectors`, `framework.blocks` and `framework.telegram` not loaded |
| AT8 | Jekyll markers 0; `.nojekyll` present; `docs/verify` holds `bundle.json`, `examples`, `index.html`; dangerous DOM 0; only pinned jsDelivr and repo links as absolute URLs |
| AT9 | imports reviewed against D3 |
| AT10 | browser pass above |
| AT11 | live recipe above |
| AT12 | 1413 passed |
| AT14 | negative control on the base: collection error, no `framework/verify` |

`make check` exit 0: ruff, format, pyright 0 errors, 1413 passed, gitleaks no leaks. `make demo` passed. AT13 is this commit, checked afterwards. Inside Muse's sandbox `tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails because the sandbox denies the loopback bind; that is the only difference.

All test data and the recipe's data are synthetic, the new tests use no network, and the path in `HIDDEN_CRITERIA_DIR` was never opened.

## Live check, Nov 1

After merge, with Pages on, Claude Code checked the page live at https://carloscrespomacaya.com/ikigai-loop/verify/ and at https://macayaven.github.io/ikigai-loop/verify/, which redirects there. In Chrome, Firefox and emulated iPhone WebKit: 11 GET requests while loading, to the page host and cdn.jsdelivr.net, then 0 after load; a canary in the pasted input appeared in no request; no cookies, storage or service workers. The README command ran for real from an empty folder with a fresh uv cache: exit 1 with `L1B_METRIC_VALUE_MISMATCH`, in 6 seconds.

Still unmeasured: a real phone, and how long a person takes.
I changed the page after this check so it opens with the labelled made-up example already run, and I will rerun this live check after merge.

## Known gaps

- `LIMITS_NOTE` and the header of `framework/briefing/numbers.py` state what the check doesn't do.
- These false forms pass both the gate and `verify_claims`, so they are gate limits and not drift: `7k`, `7M`, `$7`, `7%` next to a metric of 7 that isn't a percent, Arabic and circled digits, `8th`, `VIII`, `dozens`, `doubled`, `half`, `twice`, dates and clock times, `-7` read as 7, rounding such as 5 for 4.75, direction words not in the lists such as `climbed`, a reversed sentence with true refs and a direction word that agrees, and zero-width characters inside a deny term.
- Now verified live (see Live check, Nov 1 above): the real Pages URL, the `uvx` git URL and the raw GitHub URL. Not verified: real phones and iOS Safari, because only desktop browser builds and one emulated iPhone WebKit run loaded it; how long a person takes, because no person was timed.
