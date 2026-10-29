# Session evidence — 003-core-schemas (2026-10-29)

Ticket 3 only; one fresh Muse session for this ticket. This note summarises
the work; the raw `muse export --redacted` is kept privately and published
only if gitleaks plus a manual check of names and context is clean.

## Plan

- Plan and implementation: muse-wonder-1.0 (effort high), in Muse Code. Plan approved with 4 amendments:
  (1) branch `t3-core-schemas` created from updated `main` (T2 merged), AT9 is
  plain `git log --oneline main..HEAD` = 1 and AT10 runs on `main`;
  (2) `health.daily` metrics are all optional (`None` when the source has no
  sample that day), `mood` replaced by `mood_valence: float | None` in
  [-1, 1], with an all-`None` round-trip test;
  (3) AT5 negative drift case writes a modified schema to `tmp_path` and
  asserts the drift check fails naming the model;
  (4) the `CONTRIBUTIONS.md` Ticket 3 entry goes after Ticket 2
  (chronological). The plan's six assumptions were accepted.

## Implementation

- Plan and implementation: muse-wonder-1.0 (effort high), in Muse Code.
- Implementation ran in the same session, after approval.
- Files: `docs/plans/003-core-schemas.md` (amended), `framework/schemas/`
  (`base`, `events`, `core`, `manifest`, `export_schemas`, `__init__`),
  `schemas/*.json` (33 generated files), `tests/test_schemas_events.py`,
  `tests/test_schemas_core.py`, `tests/test_schemas_export.py`,
  `README.md` (Status section only), `CONTRIBUTIONS.md` (Ticket 3 entry
  after Ticket 2), `docs/sessions/003-core-schemas.md` (this file).
- All models are Pydantic v2, frozen, `extra="forbid"`. Tests were written
  first and failed with `ModuleNotFoundError: framework.schemas` before the
  models existed.

## Acceptance tests

- AT1 passed: round-trip for the envelope and all 21 event types, including
  the `health.daily` all-metrics-`None` round-trip. The events test file
  alone reports 34 passed, including the calendar no-`title`-property test.
- AT2 passed: rejections for extra field, unknown type, envelope/payload
  type mismatch, calendar `title`, non-sensitive `health.daily` and
  `app.journal`, check-in energy 0 and 6, naive datetime, and
  `mood_valence` out of [-1, 1].
- AT3 passed: round-trips for `Fact`, `Profile`, `Criterion`, `Manifest`,
  `BlockConfig`, `Decision`; rejections for empty `Fact` evidence, weights
  summing to 0.9, weight 1.5, inverted fact window, `evolve` without a
  diff, diff on `noop`, changelog entry without evidence, extra fields.
- AT4 passed: re-running `python -m framework.schemas.export_schemas`
  produces identical hashes (deterministic); 33 files, one per model.
- AT5 passed: committed schemas match the models, and the `tmp_path`
  negative case (one modified `HealthDailyData.json` in a copied tree)
  makes `find_drift` return exactly `["HealthDailyData"]`.
- AT6 passed: `git diff README.md` shows only the ticket's `## Status`
  section appended, byte-identical.
- AT7 passed: public-repo sweep over touched text files found no real
  names (beyond `subject-1` fixtures), hosts, private paths, or personal
  values; fixtures are synthetic. `make check` green (ruff, ruff format,
  pyright strict on `framework/` with 0 errors, pytest, gitleaks no leaks).
- AT8 passed: all 33 `schemas/*.json` parse as JSON; no `title` property
  exists in any calendar event schema.
- AT9: single commit on `t3-core-schemas` (verified with
  `git log --oneline main..HEAD` and `git show --stat HEAD` after
  committing); not pushed.
- AT10 passed (negative control on `main`): `git ls-tree -r main` shows
  no `schemas` paths and no schema tests on `main`.

## Notes

- No eval or block changed, so no Inspect log or mutant run applies.
- Nothing read the path in `HIDDEN_CRITERIA_DIR`, `profiles/*.md` was read
  only to shape `Profile`/`Criterion` (never loaded or parsed by code), and
  nothing read the private companion repo.
- Raw redacted export kept privately.
