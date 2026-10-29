# Session evidence — 007-collectors-wave2 (2026-10-29)

Ticket 7 only; two sessions per ticket (plan, then implementation). This
note summarises the work; the raw redacted export is kept privately and
published only if gitleaks plus a manual check of names and context is
clean.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Plan

- Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3
  (effort medium), in Muse Code.
- The five ticket decisions as implemented: (1) `daylight_min` is one
  optional field on `HealthDailyData`, nothing else in `framework/schemas/`
  changed; (2) the SPEC D3 edit is exactly the two pinned replacements
  (Email stays Won't, iPhone Screen Time moves to Could via the
  ActivityWatch Screen Time import, category minutes only);
  (3) the ActivityWatch payload boundary is
  `ScreenHourData.minutes_by_category` only — titles and URLs are dropped at
  the collector; (4) Apple Mail / `iki-jobs` stays a documented Could, no
  code; (5) every `uv` invocation and the commit ran under
  `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
  `UV_CACHE_DIR="$PWD/.git/uv-cache"`.
- Amendments as implemented: (A) per-poll Spotify refresh POST via the new
  `http_post` seam, rotations ignored, `ops/spotify-auth.md` with no
  values; (B) ActivityWatch pushes to the renamed `ingest.py` server
  (`POST /health/daily` + `POST /events/screen-hour`), stateless 48 h
  window, content-hash `source_id`s, trailing-slash buckets URL;
  (C) Mac minutes AFK-clipped against `not-afk` intervals and split at UTC
  hour boundaries, iPhone counted as-is; (D) skip-then-match category table
  over `code, comms, feed, browse, media, other`; (E) the Shortcut posts
  yesterday (Europe/Madrid), content-hash `source_id`, corrected re-posts
  supersede with latest `collected_at` winning.

## Implementation

- Files: `docs/plans/007-collectors-wave2.md` (committed with the
  implementation), `docs/SPEC.md` (two D3 replacements only),
  `framework/schemas/events.py` (`daylight_min` only),
  `schemas/HealthDailyData.json` + `schemas/Event.json` (regenerated via
  `uv run python -m framework.schemas.export_schemas`, no hand edits),
  `framework/collectors/` (`common.py` gains `HttpPost`/`urllib_http_post`,
  new `spotify.py`, `activitywatch.py`, `ingest.py`, `__init__.py`
  re-exports, `__main__.py` gains `run spotify`, `push activitywatch`,
  `ingest-health`, `serve-ingest`),
  `ops/health-shortcut.md`, `ops/spotify-auth.md`,
  `tests/test_spotify.py` (9 tests), `tests/test_ingest.py` (15 tests),
  `tests/test_activitywatch.py` (18 tests),
  `tests/test_collectors_cli.py` (9 new tests, existing assertions kept),
  `tests/test_schemas_events.py` (`daylight_min` round-trip),
  `.env.example` (six empty names), `CONTRIBUTIONS.md` (Ticket 7 entry),
  this file.
- Tests were written first and failed at collection with no
  `framework.collectors.{spotify,ingest,activitywatch}` modules before the
  collectors existed (AT14).
- Deviations from the plan's letter, all behaviour-preserving: (1) the
  test-only `played_at` filter uses plain `datetime.fromisoformat(value)`
  instead of `value.replace("Z", "+00:00")` — identical on Python 3.12,
  required by ruff FURB162; (2) the ingest handler test double drives
  `make_ingest_handler` through a `sendall`-capturing socket stand-in
  instead of a bound socket (this Python wraps `wfile` in a
  `sendall`-based writer, so the fake implements `sendall`); no bind, no
  network in any test.
- No live poll, live Shortcut POST, live `push activitywatch`, or live
  `serve-ingest` was run in this session; Carlos runs live polls/pushes and
  arms the Oct 30 timer after merge.

## Acceptance tests

- AT1 passed: `health or drift or schema` — drift list empty, one schema
  file per exported model, `daylight_min: 12.5` round-trips and all-`None`
  validates with `daylight_min is None`; `git diff schemas/` touched only
  `HealthDailyData.json` and `Event.json`.
- AT2 passed: `grep -n "iPhone Screen Time" docs/SPEC.md` returns the D3
  row (`Email moves to Won't; iPhone Screen Time moves to Could (arrives
  via ActivityWatch's Screen Time import; category minutes only)`) and one
  Could hit; the Won't column keeps `Email` with no `iPhone Screen Time`
  hit.
- AT3 passed: `refresh or token_endpoint` — one POST to
  `https://accounts.spotify.com/api/token` before any GET, Basic header
  shape and exact `grant_type=refresh_token` + `refresh_token` form keys
  asserted, rotated `refresh_token` ignored, no credential/token string in
  events, cursor, exception text, or `caplog`.
- AT4 passed: `refresh_failed or missing_credential` — non-`200` token
  response raises `spotify: refresh failed (status 401)` with no
  recently-played GET and nothing stored; each missing credential names
  only its variable; `grep -rn SPOTIFY_ACCESS_TOKEN framework/collectors/
  tests/` is empty.
- AT5 passed: `mapping or cursor or newer or skip` — exact
  track/artist/`played_at`, ascending order,
  `source_id="<track id>@<played_at UTC ISO>"`, strictly-newer second poll,
  cursor never moves backwards, artist-less and bad-time entries skipped.
- AT6 passed: `health_full or daylight or omitted` — full payload incl.
  `daylight_min: 95.0` maps with Madrid-midnight `time` and
  `health:<date>:<12 hex>` key; omitted/all-`None` payloads validate.
- AT7 passed: `health_repost or supersede or health_invalid` — identical
  re-post returns `False` with one stored event; corrected re-post stores a
  second event with a different hash suffix and latest-`collected_at`
  resolution picks the correction; invalid JSON / missing `date` / unknown
  key / negative metric raise `CollectorError` and write nothing.
- AT8 passed: `screen_hour or counts_only` — valid batch inserts,
  identical re-push inserts 0, any wrong `type`/`source`/`tier` or
  malformed item fails the whole batch with nothing written, responses are
  counts only.
- AT9 passed: `afk or clip or split or iphone_as_is` — partial overlap
  counts 15.0 of 30 min, hour-boundary span splits 30.0/30.0, `afk` time
  counts zero, iPhone counts as-is with no AFK bucket, missing AFK bucket
  yields zero Mac minutes.
- AT10 passed: `aggregat or categor or skip or bundle` — exact
  `minutes_by_category` per `(device, hour)`, skip-list app contributes
  nothing, unmapped app goes to `other`, bundle ids
  `com.apple.MobileSMS` → `comms` and `com.tweetie2` → `feed`,
  two-category app takes the earlier category, no UUID-shaped string.
- AT11 passed: `title_absent or url_absent or stateless or late or
  buckets_url or no_window or no_screentime` — trailing-slash buckets URL
  asserted, decoy title/URL in no pushed payload, stored event, or
  `caplog`; stateless re-derive, late-data new hash, no-window-bucket
  error, no-Screen-Time-bucket success, non-`200` raises before building.
- AT12 passed: `ingest or push or serve or cli` plus `make check` —
  handler 401s write nothing, `serve-ingest` refuses without
  `INGEST_TOKEN`, `run spotify` / `push activitywatch` / `ingest-health`
  print only counts with no local DB on the push path, `run
  activitywatch` and `serve-health` are argparse errors (exit 2), neither
  stream carries content or secrets. `make check` green — ruff, ruff
  format, pyright strict on `framework/` with 0 errors, full pytest green,
  gitleaks no leaks. No network in any test.
- AT13: `iki-jobs` appears only in the plan text (decision-4 Could), with
  no mail module or label handling in code; exactly 1 commit on
  `t7-collectors-wave2` with the step-9 files, made as
  `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"
  UV_CACHE_DIR="$PWD/.git/uv-cache" git commit -m "Ticket 7: collectors
  wave 2 (Spotify, Health ingest, ActivityWatch)"`, not pushed.
- AT14 passed (negative control on the base tree): collection failed with
  no wave-2 modules, `daylight_min` count `0`, the SPEC Could wording
  absent, `ingest.py` missing.
- Per-file pytest counts on the branch: `test_spotify.py` 9,
  `test_ingest.py` 15, `test_activitywatch.py` 18,
  `test_collectors_cli.py` 15 (6 pre-existing + 9 new).

## Notes

- Public-repo sweep over every touched file: no real names (beyond the
  published `subject-1` placeholder), real tracks/artists/health values,
  real window titles, real Spotify credentials, hosts beyond the pinned
  API hosts, private paths, device UUIDs, tokens, or secrets. Fixtures are
  obviously synthetic (`.invalid` URLs/hosts, `synthetic-*` ids and
  credential values).
- No eval or block changed, so no Inspect log or mutant run applies to
  this ticket.
- Nothing read the path in `HIDDEN_CRITERIA_DIR`, `profiles/*.md`, or
  the private companion repo.
- Raw redacted export kept privately.
