# Session evidence — 004-event-store (2026-10-29)

Ticket 4 only; two sessions per ticket from here on (plan, then
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
- Approved amendments included: (1) identity compares only
  `(subject_id, source, source_id, type, time, tier, data)` — re-delivery
  with a new `id`/`collected_at`/`collector_version` is a no-op and the
  stored row wins, changed content raises `ConflictingEvent`; (2)
  `run_collector` records conflicts in `conflicts` and keeps going while
  `append_event`/`append_events` still raise.

## Implementation

- Files: `docs/plans/004-event-store.md` (committed with the
  implementation), `framework/store/` (`store.py`, `collector.py`,
  `__init__.py` — stdlib `sqlite3` only), `tests/test_store.py` (13
  tests), `tests/test_collector.py` (7 tests),
  `tests/fixtures/fixture_events.jsonl` (3 synthetic `subject-1` events:
  `health.daily`/`sensitive`, `github.push`, `music.play`), `.gitignore`
  (`data/` section), `docs/WORKFLOW.md` (two-session wording in §5 and
  §6, plus the `muse --version` evidence-note requirement),
  `CONTRIBUTIONS.md` (Ticket 4 entry), this file.
- Tests were written first and failed at collection with no
  `framework.store` module before the store existed (AT11); the one
  implementation bug found by the tests (missing `isolation_level=None`
  on `sqlite3.connect`, caught by the purge test) was fixed in the new
  code, never by relaxing config.

## Acceptance tests

- AT1 passed: `round_trip` — appended `private` and `sensitive` events
  (authored with a `+01:00` offset) read back as equal `Event` objects.
- AT2 passed: `repoll` — first `run_collector` returns `(3, 0)`, second
  returns `(0, 0)`, event count and cursor unchanged.
- AT3 passed: `conflict`/`identity` — excluded-fields re-delivery is a
  no-op with the stored row winning; changed `data`/`time`/`tier` and
  `id` reuse raise `ConflictingEvent` with the original row unchanged.
- AT4 passed: `update_blocked` — raw `UPDATE events` raises
  `sqlite3.IntegrityError` (`events are append-only`) and the row is
  unchanged.
- AT5 passed: `conflict_recorded` returns `(2, 1)` with the rest of the
  batch stored, one `conflicts` row, and the cursor advanced;
  `atomic_rollback` (non-serialisable cursor after the first insert)
  leaves no batch events, no `conflicts` rows, and the old cursor.
- AT6 passed: `subject` isolation, `types_filter`, and half-open
  `bounds` (event at `end` excluded, at `start` included; `start == end`
  returns `[]`, `start > end` and naive bounds raise `ValueError`).
- AT7 passed: `hash` deterministic on recompute, different after one
  event differs, ignores other subjects/days, `2026-10-29T23:30:00+00:00`
  falls on Madrid day `2026-10-30`, empty day hashes canonical `[]`.
- AT8 passed: `purge` deletes only `time < cutoff` (exact-cutoff row
  survives), returns the exact count, leaves `cursors`, `batch_hashes`,
  and `conflicts` untouched.
- AT9 passed: `make check` green — ruff, ruff format, pyright strict on
  `framework/` with 0 errors, full pytest 71 passed (13 store + 7
  collector + 51 pre-existing), gitleaks no leaks. No network in any
  test; `IKIGAI_DATA_DIR` touched only via `monkeypatch` onto `tmp_path`.
- AT10 verified after committing: exactly 1 commit on `t4-event-store`,
  containing only the files above; not pushed.
- AT11 passed (negative control on the base tree): collection failed
  with no `framework.store` module and `framework/store/` did not exist.

## Notes

- Public-repo sweep over every touched file: no real names (beyond the
  published `subject-1`/`subject-2` placeholders and Carlos's own name
  where it already appears), hosts, ports, private paths,
  personal/health values, or secrets. Fixture health values are
  obviously synthetic.
- No eval or block changed, so no Inspect log or mutant run applies.
- Nothing read the path in `HIDDEN_CRITERIA_DIR`, `profiles/*.md`, or
  the private companion repo.
- Raw redacted export kept privately.
