# Session evidence — 005-collectors-wave1 (2026-10-29)

Ticket 5 only; two sessions per ticket from here on (plan, then
implementation). This note summarises the work; the raw redacted export is
kept privately and published only if gitleaks plus a manual check of names
and context is clean.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Plan

- Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3
  (effort medium), in Muse Code.
- Approved amendments included: (1) ageing out is not cancellation —
  a missing instance emits `calendar.event.cancelled` only when its stored
  start is still `>= window_start`, older instances drop silently; (2) no
  `DTSTAMP` fallback — `last_modified` is `LAST-MODIFIED`, else
  `"seq<SEQUENCE>"`, else `"seq0"`, and `DTSTAMP` is never read; (3) a
  closed-and-merged `PullRequestEvent` yields `counts = {"merged": 1}`.

## Implementation

- Files: `docs/plans/005-collectors-wave1.md` (committed with the
  implementation; two blank lines added inside its code fence by
  `ruff format`, whitespace only), `framework/collectors/` (`common.py`,
  `calendar_ics.py`, `github_events.py`, `build_feed.py`,
  `__init__.py`, `__main__.py` — stdlib `urllib` for HTTP, new runtime
  deps exactly `icalendar==7.3.0` + `recurring-ical-events==3.8.2`),
  `tests/test_calendar_ics.py` (9 tests),
  `tests/test_github_events.py` (6 tests),
  `tests/test_build_feed.py` (4 tests),
  `tests/test_collectors_cli.py` (4 tests),
  `tests/fixtures/calendar_synthetic.ics` (invented UIDs/titles only),
  `pyproject.toml` + `uv.lock` (via `uv add`, no hand edits),
  `.env.example` (four empty names), `CONTRIBUTIONS.md` (Ticket 5 entry),
  this file.
- Tests were written first and failed at collection with no
  `framework.collectors` module before the collectors existed (AT12).
- Deviations from the plan's letter, all behaviour-preserving: (1) the
  plan's `datetime.fromisoformat(value.replace("Z", "+00:00"))` is written
  as plain `datetime.fromisoformat(value)` — identical on Python 3.12,
  required by ruff FURB162; (2) `common.py` carries two extra generic
  narrowing helpers (`as_dict`/`as_list`) so pyright strict stays at
  0 errors with no `Any`-derived `Unknown`; (3) the recurring-ical-events
  import carries one `# pyright: ignore[reportMissingTypeStubs]` because
  that package ships no type markers, with a `cast` at the single use
  site. No new dependency, no config change, no behaviour difference.

## Acceptance tests

- AT1 passed: `recurring` — 1 passed; the weekly event expands to exactly
  the Nov 2 and Nov 9 occurrences, each `calendar.event.created` with
  `source_id == "<UID>@<occurrence start>@<LAST-MODIFIED>"`.
- AT2 passed: `tags or is_new or busy` — 1 passed; `new: iki-partner …`
  yields `is_new=True`, `tags=["iki-partner"]`, `busy=False`
  (`TRANSP:TRANSPARENT`); plain events yield `is_new=False`, `busy=True`.
- AT3 passed: `disappearance or cancelled or ages_out or dtstamp` —
  3 passed; poll 2 emits exactly one `cancelled` (`#cancelled` source_id,
  snapshot data) plus one `updated` for the `LAST-MODIFIED` bump, poll 3
  emits nothing; clock +7 days on the same ICS emits nothing (aged out,
  snapshot emptied); a `DTSTAMP`-only change emits nothing.
- AT4 passed: `title_absent` — 1 passed; no stored event JSON contains any
  fixture `SUMMARY`, and no event `data` has a `title` attribute.
- AT5 passed: `ical_url_secret` — 1 passed; the fake
  `https://example.invalid/secret-calendar-token.ics` appears in neither
  exception text nor `caplog` on the 500, network-error, and success
  paths; missing `ICAL_URL` names only the variable.
- AT6 passed: `mapping or excluded` — 2 passed; push/pr/issue/release map
  with the pinned `counts` (`{"merged": 1}` vs `{"closed": 1}` covered),
  every `ikigai-loop` repo and the unlisted `WatchEvent` are absent.
- AT7 passed: `etag` — 1 passed; second poll sends `If-None-Match`, a
  `304` returns `([], same cursor)`, and `run_collector` returns `(0, 0)`.
- AT8 passed: `mapping or cap` — 2 passed; HF/HN/GitHub items map exactly,
  35 HN ids and 35 GitHub items each emit exactly 30.
- AT9 passed: `same_day or next_day` — 1 passed; same-Madrid-day re-poll
  emits 0 with no conflicts despite changed scores, next Madrid day
  re-emits with the new date in `source_id`.
- AT10 passed: `writes_nothing` — 3 passed; a 500/network-error/garbage
  poll raises out of `run_collector` with 0 events and cursor still `None`
  for all three collectors.
- AT11 passed: `tests/test_collectors_cli.py` — 4 passed; happy path
  prints exactly `inserted=<n> conflicts=<n>` and returns 0, error path
  returns 1 with only `error: …` on stderr, no content/titles/URLs in
  either stream. `make check` green — ruff, ruff format, pyright strict
  on `framework/` with 0 errors, full pytest 94 passed (23 new + 71
  pre-existing), gitleaks no leaks. No network in any test.
- AT12 passed (negative control on the base tree): collection failed with
  no `framework.collectors` module and `framework/collectors/` did not
  exist.
- Per-file pytest counts on the branch after the first commit:
  `test_calendar_ics.py` 9, `test_github_events.py` 6,
  `test_build_feed.py` 4, `test_collectors_cli.py` 4.

## Amendment 4 — multiple calendars (same models/efforts, second commit)

- `CalendarIcsCollector(label: str = "personal")`: non-`^[a-z]+$` labels
  raise `ValueError` at construction; `name = f"calendar-{label}"` (own
  cursor per calendar), `Event.source = name`, `category = label`,
  `version` stays `calendar@0.1.0`. URL env var is
  `f"ICAL_URL_{label.upper()}"`, with a `personal`-only fallback to
  legacy `ICAL_URL`; missing-env errors name only the variable, and all
  messages are prefixed with the collector `name`. CLI:
  `run calendar [--label <label>]` (default `personal`; `--label` with
  `github`/`feed` is an argparse error). `.env.example` now carries
  `ICAL_URL_PERSONAL=` and `ICAL_URL_HOME=` instead of `ICAL_URL=`.
- New tests: `test_two_labels_keep_independent_cursors` (personal +
  home on one store, own cursors, `category == label`, a home-only empty
  poll cancels only the home instance and leaves the personal cursor
  untouched), `test_env_var_naming_and_personal_fallback`,
  `test_home_secret_never_leaks`, `test_invalid_label_rejected`, plus
  `test_cli_calendar_label_flag` and
  `test_cli_label_rejected_for_other_collectors`. Existing calendar/CLI
  tests updated to the label contract (`calendar-personal` cursors and
  sources, `ICAL_URL_PERSONAL` env).
- `make check` green again — ruff, ruff format, pyright strict on
  `framework/` with 0 errors, full pytest 100 passed (29 new + 71
  pre-existing), gitleaks no leaks. No network in any test; the CLI
  label test pins its clock via `now_fn` so the window cannot age out.
- Per-file pytest counts after amendment 4: `test_calendar_ics.py` 13,
  `test_github_events.py` 6, `test_build_feed.py` 4,
  `test_collectors_cli.py` 6.
- No live poll was run; Carlos runs live polls per collector after merge.

## Notes

- Public-repo sweep over every touched file: no real names (beyond the
  published `subject-1` placeholder), real calendar/account data, hosts
  beyond the pinned public API hosts, private paths, or secrets. Fixture
  titles/repos/papers are obviously synthetic (`.invalid` URLs,
  `synthetic-*` ids).
- No eval or block changed, so no Inspect log or mutant run applies.
- Nothing read the path in `HIDDEN_CRITERIA_DIR`, `profiles/*.md`, or
  the private companion repo.
- No live poll was run in this session; Carlos runs one live poll per
  collector after merge.
- Raw redacted export kept privately.
