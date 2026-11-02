# Session evidence — 021-try-it (2026-11-02)

Ticket 21 only: `try-ikigai`, one command a stranger runs with no key, no model, no phone and no account, replaying packaged made-up data through the real fact, proposal, gate, card, chart and keyboard code. This note summarises the work; the raw session exports are kept privately, not in this repo.

Sessions, all headless, started by Claude Code, in Contributor mode on this public repo and made-up data only. Plan on muse-wonder-1.0 (effort high). One plan amendment and this commit step on muse-spark-1.3 (effort low). Implementation, two fix rounds and the move onto ticket 13 on muse-spark-1.3 (effort medium). Prompts and review by Claude Code.

`~/.local/bin/muse --version` (commit session, first line, verbatim):

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Every `uv`, `pre-commit` and `git` command in the sessions used the clone's own `.git` folder for its caches.

## Why it exists

A no-context reviewer got the checker in 15 seconds and never saw the loop, and five reviewers voted for this unanimously. GPT Terra 6.1 ran the no-context test through Codex; GPT Sol 6.1, GPT Terra 6.1, GPT Astra 6, Muse Wonder Full and Claude Code's advisor voted.

## What it reuses

The real fact layer with both model passes off, the real proposal step and gate with hand-written replies in the model's shape, ticket 13's card builder and chart, and the real keyboards. No model, network, store or Telegram client runs.

## The dependency decision

I moved pillow, icalendar and recurring-ical-events into `[project].dependencies`, because importing anything under `framework.telegram` or `framework.glimmer` pulls them in, and breaking that chain means editing live-path modules. An extra would keep the checker at 6 packages but would change the command's form and need quoting. The cost, measured by Claude Code on a clean temp home with an empty cache: the checker's no-clone install goes from 6 to 14 packages and about 24 MB to about 57 MB of cache, and from 2.3 to 3.3 seconds to 2.6 to 3.4 seconds from GitHub on the same network, about the same given the spread.

## Clean-install numbers

Measured by Claude Code outside Muse's sandbox, with `uv` already installed, an empty temp home and an empty cache, three runs each, from a local copy of this branch because it isn't pushed yet: 2.2 to 2.4 seconds with Python already on the machine, 4.7 to 5.4 seconds when uv downloads Python, 0.34 to 0.41 seconds on a second run. The demo itself: 0.25 to 0.27 seconds. A fresh clone's `make try` with no environment variables: under 2 seconds, without the dev and app groups. The GitHub route for this command can't be timed before the push. The README's "under 10 seconds" leaves room for that clone.

## What review found

Each fixed here: `--save` onto a named pipe hung forever, found by running it; a story check on the planted number that could never fail; tests that couldn't fail, including a dependency guard with a hard-coded map, a time-zone test that used one zone, and a no-writes test that didn't look in its own temp folder; a screen row claiming 105 minutes in one hour; and a stranger's first read, which made me rewrite the output's layout, who it addresses and what it says about the planted number.

## Evidence on the final tree

Measured by Claude Code: a system-call trace of one run with decoy environment values showed no network call, no child process, no file opened for writing and no decoy touched. Claude Code patched throwaway copies of the code one change at a time, and the tests caught 30 of 33 changes; of the other 3, two changed nothing that matters, because recurring-ical-events already requires icalendar and the patch hit only the CI step's name, and the third removed a check that another check makes redundant. Claude Code ran `make check` on the committed tree outside Muse's sandbox with exit 0: 2,440 passed and 1 skipped, with ruff, ruff format, pyright and gitleaks clean. A scratch overlay of ticket 10b's gate on this tree still rejects the planted draft, now with `L1B_VALUE_PERIOD_MISMATCH` as well. The command still exits 0 with ticket 14's and ticket 11b's working code laid over it.

## The no-context read

A no-context Muse Wonder session in an empty folder ran the README's command and said what it understood. It called this a personal scheduler for its author first and for anyone checking their own agent's numbers, followed the card, the tap, the planted number and the rows behind the fix correctly, opened the image, and named the code `L1B_NUMBER_WITHOUT_METRIC_REF` and the names Muse Glimmer and Muse Wonder as words it had to guess. A later run on the final commit is recorded in the ticket's report, not here.

## One incident

An acceptance check ran the `$PWD` cache prefix from the temp root, which created a stray `.git` folder there and broke other programs on this machine until it was removed. The plan now says the `$PWD` form holds only at the clone root.

## What isn't verified

macOS and Windows; the `uvx` route from GitHub itself; the CI step, until CI runs it.

## Not in this ticket

The README's first screen and status text, which a later pass rewrites once ticket 14 lands.
