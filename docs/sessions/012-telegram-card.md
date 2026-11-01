# Session evidence — 012-telegram-card (2026-11-01)

Ticket 12 only: the Telegram card, its taps and the poll loop. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code. Plan and two plan amendments on muse-wonder-1.0 (effort high). Implementation, three review-fix sessions, two paperwork sessions and the commit session on muse-spark-1.3 (effort medium). Prompts and review by Claude Code.

`~/.local/bin/muse --version` (paperwork session, first line, verbatim):

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit`, `git` and `make` command in this session ran under `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"` `UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## What changed and why

Cards reach my phone and a tap rules between two proposals. Each tap is the signal the learner uses later, so a tap has to store once, and the bot token, which sits in every request URL, has to stay out of everything.

- `framework/telegram/`: Bot API over HTTPS with long polling, standard library only for HTTP, no public endpoint. One function makes requests and errors are raised after it returns, so no exception carries the URL.
- The card's input is plain frozen types with no import from the gate or from Ticket 11. Each side is a gated proposal or a labelled fallback from my own commitments, and a side with nothing to offer is left out. The text is plain with no `parse_mode`.
- The chart is drawn with Pillow from plain values passed in, with no titles or URLs. Pillow is the one new dependency, resolved to 13.0.0, because it draws bars and text with a bundled font and gives the same bytes for the same input. I rejected matplotlib for its large dependency tree and the axes and title habits this chart must not have, and a hand-rolled PNG writer because a graphics library hidden in a ticket about rulings would be mine alone to debug.
- Taps are stored as the existing `app.tap` event with the card id as `block_id`. A double tap stores once, a late tap is stored against its own card, and the first ruling on a card stands.
- Voice notes from me reach a handler seam, and the default handler records only that one arrived. Ticket 14 fills it.
- Nothing here schedules a card. Ticket 13 calls `send_card` and `run_poll_loop`.
- `python -m framework.telegram send-sample` and `poll` let a person run it by hand.
- `docs/PRIVACY.md` exists because Telegram's Bot Developer Terms ask for an accessible privacy policy.

The decisions and their reasons are D1 to D23 in the plan.

## Live test

Run by Claude Code outside the Muse sessions, against the real Bot API, with the token and chat id read by variable name from the process context, a scratch database, and the sample card, whose text and chart are labelled synthetic and hold made-up values. No value of either variable appears in any output, log or file of this test: a script that prints counts only found the token 0 times across the 69 scratch files and logs and the 227 files of the working tree.

Two messages reached my phone: the sample card photo, and one silent Why? reply, `Sample statement, synthetic values.`, attached to it.

- `send-sample` exited 0. The caption Telegram returned equals the rendered text, and the keyboard equals the built one. The PNG is 25013 bytes. Telegram stored it at 90, 320, 800 and 1080 px wide. Claude Code downloaded and viewed the 320 and 800 px JPEGs, and every label and value reads at both.
- `poll --once` exited 0 with `updates=1 unhandled=1`, which was my own `/start`. Nothing was stored except the cursor.
- The side-effect paths, driven on that message: the Why? reply, the ruled keyboard, an identical edit, then the original keyboard back, with `side_effect_errors` at 0 throughout. The real description for the identical edit starts `Bad Request: message is not modified`, the case the code treats as success. An answer on a query id that never existed counted `answer_errors=1` and `side_effect_errors=0`, with the real description `Bad Request: query is too old and response timeout expired or query ID is invalid`.
- Two real `poll --long-poll 5` processes for 14 s on one scratch database: both stayed alive, the real 409s were counted (`conflicts=2` and `conflicts=1` in their last lines), and SIGINT exited 0 with nothing on stderr.
- A made-up token through the real API, by the CLI: `error: getUpdates failed (status 401): Unauthorized` and `error: sendPhoto failed (status 401): Unauthorized`, each exit 1, with no token in the output.
- A 4-minute `poll --long-poll 20` ended with `poll_errors=1` and nothing else. The counts line gives no cause, which is why the DEBUG lines in D17 exist. A bounded 15-minute loop that names each failure then ran 36 polls with no failure, so I don't know what that one poll error was.
- That loop also showed 5 of its 36 real 20 s polls taking about 55 s, which is the 35 s socket timeout plus the 20 s poll. A scratch probe explains it: from my network, 9 of 90 fresh IPv6 connections to the API host timed out at 8 s and 0 of 90 IPv4 connections failed, so a fresh connection sometimes stalls on the IPv6 address for a full socket timeout before falling back to IPv4. No tap is lost, because Telegram holds an unconfirmed update for up to 24 hours, and the tap just waits for the next poll. I changed no code for this, and Ticket 13 gets the number.

## What review found

Claude Code read the whole diff, ran every acceptance test and `make check`, ran the client against a fake Bot API on loopback with real processes and a scratch database, and tried to break it from scratch scripts outside this repo. Each fix went back through a new Muse session.

- **Two pollers starting together killed the loop.** `database is locked` from opening the store escaped. Unit tests with fakes didn't see it, and two real processes on loopback did. One `try` now covers the whole iteration, and a database error is counted, backed off and retried.
- **A bad API base put the token in an exception.** `urllib.request.Request` raised `ValueError` with the whole URL for a scheme-less base, from outside the `try`. The request is now built inside it, and the CLI prints a clean error.
- **A malformed cursor backed off forever in silence.** It now stops with `error: telegram cursor is malformed`, exit 1.
- **A handler error followed by a failing cursor write escaped `handle()`.** Both are now counted.
- **A 409 was silent.** The Ctrl-C line said `conflicts=0`, and nothing printed while it happened. The counts line now prints after each counted failure, and `poll_errors` replaced a field that nothing set.
- **`$` with `re.match` let a trailing newline through** callback ids and reason codes. These checks use `fullmatch` now.
- **Statements were forced onto one line**, which contradicted verbatim. Newlines are allowed.
- **`retry_after` of zero or below** either raised from `time.sleep` or spun the loop with no sleep. Both now count as absent.
- **`poll --once` blocked for 50 s** by default. It now uses a long poll of 0.
- **`send_photo` had its own copy of the retry loop.** There is one helper now.
- **The sample looked real.** Its text and chart now say they are synthetic, and a test holds them to it.
- **Tests that could not fail.** On the first implementation, 20 source mutants survived and a few hung the suite, because `stop` waited on a list that never grew. Every `run_poll_loop` test now has a bounded stop, and new tests cover the survivors. The fake's HTML 502 now raises a real `HTTPError`, as `urllib` does.

## Checks run outside the repo

These scripts are not in this repo. I record them as what was run, with what came back.

- Source mutants: 95 on the final code, one exact edit each, in scratch copies, covering every row K1 to K59 in the plan's table. Every test the table names was among the failures of its row. 94 fail named tests. The other one lets `KeyboardInterrupt` out of `poll --once`, which aborts the pytest session and so fails the gate too.
- A strict fake Bot API on loopback, with real poller and CLI processes and a scratch database: 29 scenarios, all passing on the final code. They include a double tap across real processes, a restart mid-stream, a kill and restart during an idle long poll, A then B, foreign updates, poison updates, a locked database, two pollers on an existing file and on a fresh one, and the call shape Ticket 13 is told to use, where `stop` returned 1.0 s after it went true with a 1 s long poll. Real 409 gaps on loopback were 1.0, 2.0 and 4.0 s.
- The chart bytes are equal across `PYTHONHASHSEED` 0, 1 and 12345.
- The chart with the collector's eight categories, after Ticket 7b, is 1080 x 1228 px. Claude Code viewed it at 390 px wide, and the labels and values read.
- `make check` on this tree before this paperwork, outside the sandbox: exit 0, 1152 passed, gitleaks no leaks.

## Acceptance tests

I ran each with its exact command from the plan's table, under the env prefix.

| Test | Result |
|---|---|
| AT1 | exit 0, 43 passed |
| AT2 | exit 0, 12 passed |
| AT3 | exit 0, 25 passed |
| AT4 | exit 0, 12 passed |
| AT5 | exit 0, 4 passed (50 deselected) |
| AT6 | exit 0, 3 passed (51 deselected) |
| AT7 | exit 0, 2 passed (52 deselected) |
| AT8 | exit 0, 10 passed (44 deselected) |
| AT9 | exit 0, 4 passed (50 deselected) |
| AT10 | exit 0, 9 passed (45 deselected) |
| AT11 | exit 0, 8 passed (46 deselected) |
| AT12 | exit 0, 3 passed (51 deselected) |
| AT13 | exit 0, 14 passed |
| AT14 | exit 0, 21 passed (58 deselected) |
| AT15 | no hits from the first grep; the second grep shows only framework.collectors.common, framework.schemas (base, events), framework.store (and store.store) and framework.telegram (chart, client, ledger, models, sample, service); the third is an empty diff |
| AT16 | no hits from the first grep; count 2 from the second |
| AT17 | exit 0, 3 passed; the schemas diff is empty |
| AT18 | see the `make check` line below the table |
| AT19 | `git status --short` shows exactly the plan's Files to Create and Files to Modify |

AT20, the negative control, was run by Claude Code on an archive of the base `e126366`: `framework/telegram` is absent, and with the telegram test files copied on, pytest stops with `2 errors during collection`.

Telegram suite: 160 passed.

`make check` in this session: ruff check passes, `ruff format --check .` passes (157 files already formatted), pyright 0 errors, pytest 1151 passed with 1 failed. The one failure is the known sandbox gap, not this ticket: `tests/test_ingest.py::test_live_loopback_server_health_round_trip` fails where the sandbox denies the loopback bind, so `make` stops before gitleaks, and `gitleaks git --redact` run on its own found no leaks.

## Public-repo sweep

I ran a case-insensitive grep of the banned-word list and a grep of `/Users/` over the plan, this note, `docs/PRIVACY.md`, the added README and CONTRIBUTIONS lines, `framework/telegram/` and the telegram tests: no touched source, test or doc line carries either. All data in the tests is synthetic, with the token `1:synthetic-token-marker`.

## Not verified

- No real tap has reached the poll loop. A real tap needs my thumb, and none arrived while it ran. Double taps, restarts and late taps ran on the fake and on loopback only.
- How the card looks on a real phone: whether `Something's wrong` truncates in the three-button row, and how the chart reads on a real screen. I checked Telegram's own re-encoded images by downloading them, not on the phone.
- Nothing schedules cards yet, and no model has generated one. No real card or ruling has gone through this code.
- The cause of the one `poll_errors=1` in the live window, as above.
- The chart and these tests have only run on macOS so far. The CI run on Linux will be the first run there.

Follow-up: on my real iPhone on Nov 1, `Something's wrong` read `Somethin...` in the three-button row before a ruling and `Something's wro...` in the two-button row after one, so I gave it its own row.
