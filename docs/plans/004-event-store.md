## Goal

Ticket 4 — event store and collector framework. After this ticket, `framework/store/` holds an append-only SQLite event store (stdlib `sqlite3` only, no new dependencies, clean under pyright strict) plus a `Collector` protocol, a transactional `run_collector`, and a `FixtureCollector` over synthetic JSONL. The store is the single writer path for every later collector (T5, T7, T13): events are deduplicated on `(source, source_id)` over the compared fields `(subject_id, source, source_id, type, time, tier, data)` — differences only in `id`, `collected_at`, or `collector_version` are a no-op and the stored row wins; a difference in any compared field raises `ConflictingEvent` from `append_event`/`append_events`, while `run_collector` records conflicts in a `conflicts` table and keeps going (see Approach) — raw `UPDATE` is rejected by a trigger, the only delete is `purge_before(cutoff)`, each collector's cursor advances in the same transaction as its events, and `daily_batch_hash(day, subject_id)` records a SHA-256 of one Europe/Madrid day's events. Publishing that hash is T13, not this ticket. The frozen `Event` model from T3 (`framework/schemas/`) is used as-is; no schema changes.

Grounding, checked 2026-10-29 in this (plan) session: [docs/PLAN.md](../PLAN.md) §2.2 (event envelope, "Upsert on `(source, source_id)`", "One cursor row per collector", nightly batch hash, 14-day raw expiry after Nov 9), §2.3 (privacy tiers), §3 row T4 ("SQLite append-only `events`, `cursors`, idempotent upsert, nightly batch hash, `Collector` protocol (`poll(cursor) -> (events, cursor)`), fixture collector. Tests offline"); [docs/SPEC.md](../SPEC.md) §6 ("SQLite: one shared DB for `events` and `facts`, keyed by `subject_id`" — this ticket builds only the `events` side) and §4 (collectors are deterministic, append-only, agents never call sources live); `framework/schemas/events.py` as committed in T3 defines `Event` with fields `id`, `subject_id`, `source`, `type` (literal union of 21 types), `time` (aware datetime), `source_id`, `data` (discriminated union on `data.type`), `tier` (`public | private | sensitive`), `collected_at` (aware datetime), `collector_version`, frozen with `extra="forbid"`, and `SENSITIVE_TYPES = {health.daily, app.journal}` requiring `tier == "sensitive"` — imported, never modified; `framework/schemas/base.py` (`SchemaModel`, `Tier`); [docs/plans/003-core-schemas.md](003-core-schemas.md) sets the plan format and acceptance-test style; `pyproject.toml` pins Python 3.12, `pydantic` as the only relevant runtime dep, pyright `strict = ["framework"]`, pytest `testpaths = ["tests"]`, `pythonpath = ["."]`; `Makefile` `check` is `ruff check`, `ruff format --check`, `pyright`, `pytest`, `gitleaks git --redact`; `.gitignore` currently has no `data/` entry; `tests/` holds only T3 schema tests and `tests/test_smoke.py` (no `tests/fixtures/` yet). Branch `t4-event-store` already exists and is clean at `8a370eb` (Ticket 3). `muse --version` in this session: `Muse Code 1.4.14 (1.4.14-R7309.1)`. The private companion repo (`~/workspace/ikigai-loop-private`) and the path in `HIDDEN_CRITERIA_DIR` are never read.

## Success Criteria

- `framework/store/` (stdlib `sqlite3`, `json`, `hashlib`, `zoneinfo`, `os`, `pathlib`, `datetime` only; no new dependencies, `pyproject.toml`/`uv.lock` untouched) exposes `EventStore`, `ConflictingEvent`, `Collector`, `run_collector`, and `FixtureCollector`, all fully annotated and clean under pyright strict.
- `events` table stores every envelope column plus `data` as canonical JSON (recipe in Approach), with `UNIQUE (source, source_id)` and `UNIQUE (id)`. Identity compares only `(subject_id, source, source_id, type, time, tier, data)`: re-appending the same `(source, source_id)` differing only in `id`, `collected_at`, or `collector_version` is a no-op and the stored row wins; a difference in any compared field raises `ConflictingEvent` from `append_event`/`append_events` and writes nothing. A SQLite trigger makes any `UPDATE` on `events` fail. The only delete path in code is `purge_before(cutoff)`.
- `cursors` table holds one row per collector (`name`, opaque JSON cursor, `updated_at`). `run_collector` inserts a poll's events, records any conflicting events in a `conflicts` table (`detected_at`, `source`, `source_id`, `stored_json`, `incoming_json`) keeping the original rows, and advances that collector's cursor — all in one transaction, returning `(inserted, conflicts)`. A conflict never jams the collector; any non-conflict exception still rolls back the whole batch (events, conflict rows, and cursor).
- `daily_batch_hash(day, subject_id)` returns the SHA-256 hex digest over the canonical JSON of that subject's events on that Europe/Madrid calendar day, ordered by `id`, and upserts it into `batch_hashes`. Same data → same hash; changing one event that day → different hash. No publishing, no network.
- `events_between(subject_id, start, end, types=None)` returns only that subject's events in `[start, end)`, optionally filtered by type, ordered by `(time, id)`, reconstructed as `Event` objects. Two subjects' events never mix.
- `FixtureCollector` reads synthetic JSONL from `tests/fixtures/` and is idempotent across re-polls. All tests are offline and use `tmp_path` only; no test touches `./data` or `IKIGAI_DATA_DIR` on disk.
- `.gitignore` gains `data/`; DB path resolves from `IKIGAI_DATA_DIR` (default `./data`) as specified in Approach.
- `docs/WORKFLOW.md` wording change (exact strings in Files to Modify), evidence note `docs/sessions/004-event-store.md` recording `muse --version`, and a `CONTRIBUTIONS.md` Ticket 4 entry with the real model/effort per phase exist.
- `make check` is green; exactly one commit on branch `t4-event-store`, not pushed.

## Approach

Key decisions (all binding on the implementer; alternatives are rejected in Risks only where the choice was live):

- **Package layout is exactly three modules.** `framework/store/__init__.py` (docstring + re-exports + `__all__`), `framework/store/store.py` (`ConflictingEvent`, canonical-JSON helpers, DDL, `EventStore` with `append_event`, `append_events`, `get_cursor`, `events_between`, `daily_batch_hash`, `purge_before`, `close` and context-manager support), `framework/store/collector.py` (`Collector` protocol, `run_collector`, `FixtureCollector`). No other store modules; no CLI; no async.
- **`Event` is used as-is.** Import `Event` from `framework.schemas` (or `framework.schemas.events`). Never edit anything under `framework/schemas/` or `schemas/`. Every event entering the store is already a validated `Event`; the store never re-validates payload shapes beyond `Event.model_validate` on read-back.
- **Canonical JSON, one recipe everywhere.** `canonical_json(value) -> str` is `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. The `data` column stores `canonical_json(event.data.model_dump(mode="json"))`. The full-envelope serialisation `canonical_json(event.model_dump(mode="json"))` is used for the batch hash (`canonical_json([e.model_dump(mode="json") for e in day_events])` encoded as UTF-8) and for the `stored_json`/`incoming_json` columns of `conflicts` — never for identity. Identity (amendment 1) compares only the tuple `(subject_id, source, source_id, type, time instant, tier, canonical data JSON)`; `id`, `collected_at`, and `collector_version` are excluded from the comparison. Do not invent a second serialisation anywhere in the ticket.
- **Datetime storage is UTC-normalised ISO-8601 text.** `time` and `collected_at` are stored as `value.astimezone(UTC).isoformat()` (e.g. `2026-10-29T17:00:00+00:00`). Instants compare correctly as text, `events_between` bounds are converted the same way before comparison, and read-back via `Event.model_validate` yields an equal `Event` (datetimes compare by instant). Naive datetimes cannot occur: `Event` already requires aware datetimes, and `events_between`/`purge_before` raise `ValueError` on naive bounds.
- **DDL is exactly this** (created with `CREATE TABLE IF NOT EXISTS` / `CREATE TRIGGER IF NOT EXISTS` on open, so reopening a DB is a no-op):

```sql
CREATE TABLE IF NOT EXISTS events (
    id TEXT NOT NULL UNIQUE,
    subject_id TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    time TEXT NOT NULL,
    source_id TEXT NOT NULL,
    data TEXT NOT NULL,
    tier TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_events_subject_time ON events (subject_id, time, id);
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
CREATE TABLE IF NOT EXISTS cursors (
    name TEXT PRIMARY KEY,
    cursor TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_hashes (
    day TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (day, subject_id)
);
CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    stored_json TEXT NOT NULL,
    incoming_json TEXT NOT NULL
);
```

  `cursors.cursor` is `NULL` when the collector has never advanced, else `canonical_json(cursor_value)`. `batch_hashes.day` is the ISO calendar date (`YYYY-MM-DD`) in Europe/Madrid. `conflicts.detected_at` is the UTC ISO-8601 detection instant; `stored_json`/`incoming_json` are the full-envelope canonical JSON of the stored row and the rejected event respectively (full envelopes, so the differing field is visible even though identity excludes `id`/`collected_at`/`collector_version`). `events` has no `UPDATE` path in Python code either; `batch_hashes` and `cursors` are the only mutable tables, and `conflicts` is insert-only.
- **Append semantics: compare, then insert; never `INSERT OR IGNORE`/`REPLACE`.** `append_event(event) -> bool` runs in a `BEGIN IMMEDIATE` transaction: `SELECT` the row with the same `(source, source_id)`; if found, compare only the identity tuple `(subject_id, source, source_id, type, time instant, tier, canonical data JSON)` (stored `time` text vs the incoming instant, both UTC-normalised) — all equal → commit, return `False` (no-op; the stored row, including its original `id`/`collected_at`/`collector_version`, wins and the incoming values for those three fields are discarded); any compared field different → roll back and raise `ConflictingEvent` and write nothing. If not found, `INSERT` all ten columns and return `True`. Reusing an existing `id` under a different `(source, source_id)` hits `UNIQUE (id)` on insert: convert that `IntegrityError` to `ConflictingEvent` too (the `id` is already taken by a different event); any other `IntegrityError` propagates. `ConflictingEvent` carries `source`, `source_id`, `stored_json`, and `incoming_json` attributes (plus a message naming both) so `run_collector` can record it without re-querying. `append_events(events) -> int` does the same for a batch in one transaction and returns the count newly inserted, raising (and rolling back the whole batch) on the first conflict — the raising behaviour is unchanged by amendment 2; only `run_collector` swallows conflicts.
- **Collectors must make `source_id` unique per change.** Because changed content under the same `(source, source_id)` raises instead of updating, a collector whose upstream mutates (e.g. Calendar) must version the key, e.g. `source_id = "<upstream_id>@<updated_iso>"`, emitting a new event per change. This rule is stated verbatim in the `Collector` docstring (see below) so T5/T7 collectors inherit it.
- **Cursor + events atomicity lives in `run_collector`, not in collectors; conflicts are recorded, never fatal there (amendment 2).** `run_collector(store, collector) -> tuple[int, int]` returns `(inserted, conflicts)`: read the stored cursor via `store.get_cursor(collector.name)` (`None` if no row), call `collector.poll(cursor)` **outside** any transaction, then in one `BEGIN IMMEDIATE` transaction process the events in poll order with the same compare-then-insert rules — a newly inserted event increments `inserted`; a no-op (identity tuple equal, including the differs-only-in-`id`/`collected_at`/`collector_version` case) increments neither counter; a `ConflictingEvent` is caught per event: insert one row into `conflicts` (`detected_at` = now UTC ISO, `source`, `source_id`, `stored_json`, `incoming_json` taken from the exception), keep the original `events` row, increment `conflicts`, and continue with the rest of the batch — then `INSERT … ON CONFLICT(name) DO UPDATE` the cursor row with `canonical_json(new_cursor)` and `updated_at = datetime.now(UTC).isoformat()` **last**, and commit. Any other exception (including a non-serialisable `new_cursor` failing at that final step, after inserts) rolls back everything from the poll: no batch events, no `conflicts` rows, cursor unmoved. `EventStore` exposes the primitives (`append_events`, `get_cursor`, and a `set_cursor` used only inside that transaction — implement as one private method `_advance_cursor(conn, name, cursor)` or an `EventStore.poll_transaction(name, events, new_cursor)` helper; pick one and keep `run_collector` a thin wrapper). A poll returning zero events still advances the cursor and returns `(0, 0)`. If `poll` itself raises, nothing is written and the exception propagates. Direct callers of `append_event`/`append_events` still get the raising behaviour; only `run_collector` converts conflicts to rows.
- **`Collector` is a `typing.Protocol`, documented exactly so.** In `framework/store/collector.py`:

```python
class Collector(Protocol):
    """A deterministic source of events.

    ``poll`` receives the opaque cursor stored by the previous successful
    poll (``None`` on the first poll) and returns the new events plus the
    next cursor. Cursors are opaque JSON values owned by the collector;
    the store only persists them.

    Append-only rule: if an upstream item changes, the collector MUST emit
    it under a new ``source_id`` that is unique per change, e.g.
    ``"<upstream_id>@<updated_iso>"``. Reusing ``(source, source_id)`` with
    different compared content (subject, type, time, tier, data) is a
    conflict: ``append_event`` raises ``ConflictingEvent``, while
    ``run_collector`` records it in the ``conflicts`` table, keeps the
    stored event, and continues. The store never updates an event in place.
    """

    name: str
    version: str

    def poll(self, cursor: Any) -> tuple[list[Event], Any]: ...
```

  (`Any` is deliberate: the cursor is opaque JSON — `None`, number, string, list, or dict — serialised with `canonical_json`, so it must be JSON-serialisable; a non-serialisable cursor fails the transaction and advances nothing.) `version` is the collector's own version string; events still carry their own `collector_version` from the source data, and the store does not rewrite it.
- **`FixtureCollector` reads JSONL by line offset.** Constructor: `FixtureCollector(path: Path, *, name: str = "fixture", version: str = "fixture@0.1.0")`. `poll(cursor)`: cursor is `None` (→ offset 0) or an `int` line offset; read the file as UTF-8, skip blank lines (blank lines still count toward the physical line offset), parse each non-blank line from the offset onward with `Event.model_validate_json`, return `(events, total_physical_line_count)`. Re-polling with the returned cursor returns `([], same_cursor)`; appending lines to the file makes the next poll return only the new events. A missing file raises `FileNotFoundError` and a malformed line raises the Pydantic `ValidationError` — both propagate out of `run_collector` with nothing written. The committed fixture is `tests/fixtures/fixture_events.jsonl`: at least 3 synthetic events for `subject-1` (include one `health.daily` with `tier: "sensitive"` and obviously synthetic values, plus e.g. one `github.push` and one `music.play`; distinct `source`/`source_id`/`id` such as `evt_fixture_1…`, source `fixture`). No real names, tracks, hosts, or values anywhere in the fixture.
- **`daily_batch_hash(day: date, subject_id: str) -> str`.** Select the subject's events, keep those whose `time` instant falls on `day` in `Europe/Madrid` (`zoneinfo.ZoneInfo("Europe/Madrid")`; convert each stored UTC instant with `.astimezone(MADRID).date() == day` — do not approximate with UTC dates), order by `id` ascending, hash the canonical JSON list (Approach, canonical recipe) with `hashlib.sha256(...).hexdigest()`. Upsert into `batch_hashes` (`day.isoformat()`, `subject_id`, hash, `len(events)`, `computed_at` = now UTC ISO) in its own transaction and return the hash. An empty day hashes the canonical `[]` and is still recorded with `event_count = 0`. Recomputing the same day overwrites with the identical hash. Nothing is published or printed; T13 owns publishing.
- **`events_between(subject_id, start, end, types=None) -> list[Event]`.** Half-open `[start, end)` on the event instant. Raise `ValueError` if either bound is naive. If `start >= end`, return `[]` when equal and raise `ValueError` when `start > end`. Filter strictly by `subject_id`; when `types` is given (a collection of type strings), filter to those types (in SQL or in Python — result must be identical). Order by `(time, id)`. Reconstruct each row with `Event.model_validate({**envelope_columns, "data": json.loads(data)})`. No method ever returns another subject's events, including `daily_batch_hash` and `purge_before` accounting.
- **`purge_before(cutoff) -> int` is the only delete.** Raise `ValueError` on a naive cutoff. `DELETE FROM events WHERE time < ?` with the UTC-normalised cutoff text, in one transaction; return the deleted row count. It does not touch `cursors`, `batch_hashes`, or `conflicts` (the hash remains as proof after raw expiry, per PLAN §2.2). No other `DELETE`, `UPDATE`, or `DROP` statement exists in `framework/store/` (the `conflicts` and `events` tables are never deleted from).
- **DB path resolution.** `resolve_db_path(db_path: Path | None = None) -> Path`: explicit argument wins; else `Path(os.environ.get("IKIGAI_DATA_DIR", "./data")) / "ikigai.db"`; a relative env value is relative to the process cwd (document this; do not resolve against the repo). `EventStore(db_path=None)` calls it, creates the parent directory (`mkdir(parents=True, exist_ok=True)`), opens `sqlite3.connect(path)` with `isolation_level=None` (explicit `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` in code), and applies `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` (harmless under `tmp_path`). Tests always pass `tmp_path / "events.db"` (or a `FixtureCollector` JSONL under `tmp_path`) and never rely on the env default; one test may monkeypatch `IKIGAI_DATA_DIR` to a `tmp_path` subdir to prove resolution, and must not create `./data` in the repo. `EventStore` supports `close()` and `with` (context manager); using a closed store raises `sqlite3.ProgrammingError` naturally — do not add a custom guard.
- **pyright strict and style.** `framework/` is strict: annotate every function (including `-> None`), no untyped defs, no bare `dict`/`list` without parameters where the value type is known (cursor values are the one sanctioned `Any`). Follow the neighbouring style in `framework/schemas/` (short module docstrings, `from __future__` not used, double quotes, ruff format). Tests live in `tests/` (standard mode) but are still annotated `-> None` like the T3 tests.
- **`docs/WORKFLOW.md` change is part of this ticket's implementation** (exact strings in Files to Modify), as are the evidence note (which from now on records `muse --version` — run the command, paste its first line verbatim) and the `CONTRIBUTIONS.md` entry. This plan session changes nothing but this plan file.

## Files to Create

| File | Contents |
|---|---|
| `framework/store/__init__.py` | Docstring ("Append-only event store and collector framework (ticket 4)"), re-exports `EventStore`, `ConflictingEvent`, `resolve_db_path`, `Collector`, `run_collector`, `FixtureCollector`, with `__all__` |
| `framework/store/store.py` | `ConflictingEvent` (with `source`, `source_id`, `stored_json`, `incoming_json` attributes), `canonical_json`, Madrid/UTC constants, DDL strings (including `conflicts`), `resolve_db_path`, `EventStore` (`__init__`, `close`, `__enter__`/`__exit__`, `append_event`, `append_events`, `get_cursor`, cursor-advance helper, `events_between`, `daily_batch_hash`, `purge_before`) per Approach |
| `framework/store/collector.py` | `Collector` protocol with the exact docstring contract in Approach, `run_collector(store, collector) -> tuple[int, int]` returning `(inserted, conflicts)`, `FixtureCollector` (JSONL by line offset) |
| `tests/fixtures/fixture_events.jsonl` | Synthetic JSONL fixture (≥ 3 events, `subject-1`, one `health.daily`/`sensitive`) read by the `FixtureCollector` tests; also usable as the recorded-fixture shape for T5/T7 |
| `tests/test_store.py` | Store tests: append + read-back round-trip, idempotent re-append, identity amendments — re-delivery with new `id`/`collected_at`/`collector_version` is a no-op and the stored row wins, changed `data` (and changed `time`/`tier`) raises `ConflictingEvent` — trigger blocks `UPDATE`, two subjects never mix in `events_between` (+ `types` filter, half-open bounds), hash deterministic / changes on one changed event / Madrid day boundary, `purge_before` removes only older events — all on `tmp_path` |
| `tests/test_collector.py` | Collector tests: `run_collector` inserts + advances cursor returning `(inserted, conflicts)`, idempotent re-poll via `FixtureCollector` (second poll returns `(0, 0)`, cursor unchanged), conflict mid-batch is recorded in `conflicts` while the rest insert and the cursor advances, injected non-conflict failure after the first insert leaves no batch events and the old cursor, fixture append-then-repoll returns only new lines, missing-file poll writes nothing |
| `docs/sessions/004-event-store.md` | Evidence note mirroring `docs/sessions/003-core-schemas.md`: `muse --version` output (first line, verbatim), models/efforts per phase (plan: muse-wonder-1.0 high; implementation: muse-spark-1.3 medium — record what actually happened), wall time if known, AT results, public-repo sweep result, statement that the raw redacted export is kept privately |

## Files to Modify

| File | Change |
|---|---|
| `.gitignore` | Append one section `# local event data` + `data/` (so the default `./data` DB is never committed). No other `.gitignore` change |
| `docs/WORKFLOW.md` | Two replacements of the sentence `One fresh Muse session per ticket.` (in the §5 Ship table row and in the §6 Definition of Done bullet) with `Two sessions per ticket: plan (muse-wonder-1.0, high) and implementation (muse-spark-1.3, medium); the approved plan file is the handoff.` Keep the surrounding sentence text intact. Additionally, in §6, extend the evidence-note bullet so it requires recording the `` `muse --version` `` output in `docs/sessions/NNN-slug.md`. No other WORKFLOW edits |
| `CONTRIBUTIONS.md` | Add a `Ticket 4 — event store and collector framework` entry after the Ticket 3 entry (chronological), same shape as existing entries: what was built, branch `t4-event-store` + plan link, date, and the real Muse models/efforts per phase (plan vs implementation) |
| `docs/plans/004-event-store.md` | This plan, committed with the implementation |

No other existing files change. In particular: nothing under `framework/schemas/` or `schemas/`, `pyproject.toml`/`uv.lock` (no new deps), `Makefile`, `AGENTS.md` (its "One worktree per ticket" still holds; the two-session rule lives in WORKFLOW), `README.md`, and no file reads `HIDDEN_CRITERIA_DIR` or the private companion repo.

## Steps

1. Pre-flight on `t4-event-store`: `git branch --show-current` prints `t4-event-store`, `git status` clean. Negative control first (AT11): on the current tree, `uv run pytest tests/test_store.py tests/test_collector.py` fails at collection (no `framework.store`) and `test -d framework/store` fails.
2. Write the fixture and the tests first (`tests/fixtures/fixture_events.jsonl`, `tests/test_store.py`, `tests/test_collector.py`) with synthetic `subject-1`/`subject-2` data only, and confirm they fail because `framework.store` does not exist yet.
3. Implement `framework/store/store.py`, then `collector.py`, then `__init__.py`, per the Approach recipes (canonical JSON, UTC text, compare-then-insert, single-transaction cursor advance). Run `make test` until green, then the full `make check` (ruff, format, pyright strict on `framework/`, pytest, gitleaks) and fix findings in the new code, never by relaxing config.
4. Append the `data/` section to `.gitignore`; make the two `docs/WORKFLOW.md` replacements plus the §6 `muse --version` bullet extension, and diff them to confirm only those lines changed.
5. Public-repo sweep over every touched file: real names (beyond the published `subject-1`/`subject-2` placeholders and Carlos's own name where it already appears), hosts, ports, private paths, personal/health values, secrets. Fixture health values must be obviously synthetic.
6. Write `docs/sessions/004-event-store.md` (including the verbatim first line of `muse --version` run in the implementation session) and the `CONTRIBUTIONS.md` Ticket 4 entry with the real models/efforts per phase; run all acceptance tests and `make check` one final time.
7. One commit on `t4-event-store` containing exactly: `docs/plans/004-event-store.md`, `framework/store/` (3 files), `tests/test_store.py`, `tests/test_collector.py`, `tests/fixtures/fixture_events.jsonl`, `.gitignore`, `docs/WORKFLOW.md`, `CONTRIBUTIONS.md`, `docs/sessions/004-event-store.md`. Do not push.

## Acceptance Tests

Each is a command plus its expected result. AT1–AT10 pass on the branch; AT11 is the negative control on the base. Test names below are the names to use in `tests/test_store.py` / `tests/test_collector.py` so the mapping is checkable.

| # | Command | Expected result |
|---|---|---|
| AT1 | `uv run pytest tests/test_store.py -k "round_trip or readback"` | Exit 0; an appended `Event` reads back via `events_between` as an equal `Event` (all envelope fields + typed `data`), for at least one `private` and one `sensitive` event |
| AT2 | `uv run pytest tests/test_collector.py -k repoll` (idempotent re-poll) | Exit 0; first `run_collector` returns `(N, 0)` inserting all fixture events, second returns `(0, 0)`, the `events` count and the stored cursor are unchanged, no exception |
| AT3 | `uv run pytest tests/test_store.py -k "conflict or identity"` (identity, amendment 1) | Exit 0; (a) same `(source, source_id)` with identical compared fields but a new `id`, new `collected_at`, and new `collector_version` is a no-op: `append_event` returns `False`, the row count stays 1, and read-back returns the **stored** `id`/`collected_at`/`collector_version`; (b) same key with changed `data` raises `ConflictingEvent` and the original row is unchanged; (c) same key with changed `time` or changed `tier` also raises; (d) the same `id` under a different `(source, source_id)` also raises `ConflictingEvent` |
| AT4 | `uv run pytest tests/test_store.py -k update_blocked` | Exit 0; a raw `UPDATE events SET tier = …` on the store's own connection raises `sqlite3.IntegrityError` (trigger `RAISE(ABORT, 'events are append-only')`) and the row is unchanged |
| AT5 | `uv run pytest tests/test_collector.py -k "conflict_recorded or atomic_rollback"` (amendment 2) | Exit 0; (a) conflict mid-batch: a poll of `[new_a, conflicting_variant_of_stored, new_b]` returns `(2, 1)`, `new_a`/`new_b` are stored, the stored row for the conflicting key is unchanged, exactly one `conflicts` row exists with matching `source`/`source_id` and `stored_json`/`incoming_json` decoding to the stored and incoming envelopes, and `get_cursor(name)` returns the new cursor; (b) non-conflict rollback: a poll returning valid new events plus a non-JSON-serialisable `new_cursor` (e.g. `object()`), so failure is injected at the cursor-advance step **after** the first insert, raises, leaves **no** event from that batch in the store, writes no `conflicts` row for it, and `get_cursor(name)` still returns the pre-poll cursor |
| AT6 | `uv run pytest tests/test_store.py -k "subject or types_filter or bounds"` | Exit 0; `events_between` for `subject-1` never returns `subject-2` events (and vice versa), the `types` filter returns only requested types, and bounds are half-open (event exactly at `end` excluded, exactly at `start` included) |
| AT7 | `uv run pytest tests/test_store.py -k hash` | Exit 0; `daily_batch_hash` returns the same digest on recompute, a different digest after one of that day's events differs (new `source_id` variant appended / fresh DB with one field changed), ignores other subjects and other days, and places a `2026-10-29T23:30:00+00:00` event on Madrid day `2026-10-30`, not `2026-10-29` |
| AT8 | `uv run pytest tests/test_store.py -k purge` | Exit 0; `purge_before(cutoff)` deletes only events with `time < cutoff` (event exactly at `cutoff` survives), returns the exact deleted count, and leaves `cursors`, `batch_hashes`, and `conflicts` untouched |
| AT9 | `make check` | Exit 0: `ruff check`, `ruff format --check`, `pyright` (strict on `framework/`), full `pytest` (including T3 schema tests and `tests/test_smoke.py`), `gitleaks git --redact` no leaks. No network in any test (no sockets; `IKIGAI_DATA_DIR` touched only via `monkeypatch` onto `tmp_path`) |
| AT10 | `git log --oneline main..HEAD` and `git show --stat HEAD` and `git status -sb` | Exactly 1 commit on `t4-event-store` containing only the files in step 7; no upstream/tracking branch (not pushed) |
| AT11 | Negative control on the base tree: `uv run pytest tests/test_store.py` and `test -d framework/store` | Collection fails (no `framework.store` module) and `framework/store/` does not exist before the ticket, confirming the tests measure this ticket's work |

Additionally, before committing, the implementer records in the evidence note: the first line of `muse --version` run in the implementation session, and the result of `uv run pytest` counts per new test file.

## Risks

- **Text-stored datetimes comparing wrong across offsets.** Storing raw `isoformat()` with mixed offsets (`+01:00` vs `+00:00`) would make text range queries wrong. Mitigated by the UTC-normalisation rule in Approach for storage, bounds, and cutoff; AT1/AT6 use events authored with a `+01:00` offset to prove it.
- **Madrid day boundary off by one.** Hashing by UTC date would misfile late-evening events and break the T13 nightly proof. Mitigated by converting each instant with `ZoneInfo("Europe/Madrid")` and the explicit `23:30Z → next Madrid day` case in AT7.
- **`INSERT OR REPLACE` / `OR IGNORE` silently overwriting.** Either would destroy append-only evidence and hide conflicts. Forbidden in Approach; AT3 proves changed content raises and the original row survives, AT4 proves even raw SQL `UPDATE` fails.
- **Cursor advancing past unsaved events after a crash.** The classic collector bug. Mitigated by poll-outside-transaction + one `BEGIN IMMEDIATE` covering batch inserts, `conflicts` rows, and cursor upsert (cursor written last); AT5(b) injects a failure at the cursor step after inserts and asserts no batch event and the old cursor survive.
- **A conflict jamming a collector forever.** If `run_collector` raised on conflict, one changed upstream item would block every later poll. Mitigated by amendment 2: conflicts are recorded in `conflicts` with both envelopes, the stored event wins, and the cursor still advances; AT5(a) proves the rest of the batch inserts. Direct `append_event` callers keep the raising behaviour so non-collector writers cannot silently drop a conflict.
- **Excluded-field drift hiding a real change.** Ignoring `id`/`collected_at`/`collector_version` (amendment 1) could in principle mask a source that only bumps those fields. Accepted: those three are delivery metadata, not event content; any content change still differs in a compared field and conflicts. The full incoming envelope is preserved in `conflicts.incoming_json` whenever a compared field does differ, so nothing is lost silently.
- **`zoneinfo` tzdata availability.** Python 3.12 stdlib `zoneinfo` reads the system tz database (present on macOS/Linux dev machines). No `tzdata` dependency is added; if a future Windows/CI image lacks it, that ticket adds the dep explicitly. Tests use fixed October dates, so DST-transition ambiguity is exercised only via the boundary case already in AT7.
- **Leaking private context through fixtures or the DB.** The store is exactly where real events will land. Mitigated by synthetic fixtures only, `data/` gitignored, `tmp_path`-only tests, the step 5 sweep, and gitleaks in `make check`. No test or fixture may contain a real track, title, health value, host, or path.

## Test Plan

Committed tests are the deliverable: `tests/test_store.py` (read-back round-trip, idempotent re-append, amendment-1 identity: excluded-fields no-op with stored row winning + changed-`data`/`time`/`tier` conflicts + `id`-reuse conflict, trigger-blocks-`UPDATE`, subject isolation + `types` filter + half-open bounds, hash determinism/change/Madrid boundary/empty-day, `purge_before` exactness, env-path resolution via `monkeypatch` onto `tmp_path`) and `tests/test_collector.py` (`run_collector` happy path returning `(inserted, conflicts)`, idempotent re-poll, amendment-2 conflict-recorded-continues + non-conflict atomic rollback, fixture append-then-repoll, missing-file no-write), over `tests/fixtures/fixture_events.jsonl`. Written before the store (step 2) so they fail on the base and pass on the branch, per the Definition of Done. No network in any test; no test reads `profiles/*.md`, `HIDDEN_CRITERIA_DIR`, the private companion repo, or any path outside the repo and `tmp_path`. Sequence: AT11 negative control, AT1–AT8 on the branch, `make check` (AT9), then AT10 after committing. No eval or block changes, so no Inspect log or mutant run applies to this ticket.

## Out of Scope

- Real collectors (Calendar, GitHub, public feed in T5; Spotify, Health ingest, ActivityWatch in T7; app telemetry in T13) and any live poll, network call, OAuth, or timer.
- Publishing the daily batch hash anywhere (public log, repo, ntfy) — T13. This ticket only computes and stores it.
- Facts storage (SPEC §6's per-profile DBs), Glimmer (T9), retention scheduling (the 14-day expiry is enforced by calling `purge_before` from a later ops ticket; here it is only implemented and tested), DB migrations beyond create-if-not-exists, concurrency beyond SQLite's own locking, and any change to `Event` or the exported JSON Schemas.
- Editing `AGENTS.md`, `README.md`, `Makefile`, or `pyproject.toml`. The two-session workflow wording lands only in `docs/WORKFLOW.md` as specified.

## Open Questions

None. Assumptions: (1) DB file is `ikigai.db` inside `IKIGAI_DATA_DIR` (default `./data`), parent created on open, `WAL` + explicit `BEGIN IMMEDIATE` transactions; (2) **replaced by amendment 1** — identity compares only `(subject_id, source, source_id, type, time, tier, data)`; differences in `id`, `collected_at`, or `collector_version` on the same `(source, source_id)` are a no-op and the stored row wins; (3) `FixtureCollector` cursor is the physical JSONL line offset (`int`, `None` → 0), blank lines skipped but counted; (4) `events_between` is half-open `[start, end)`, `start == end` → `[]`, `start > end` or naive bounds → `ValueError`; (5) `daily_batch_hash` on an empty day stores and returns the hash of canonical `[]`; (6) `docs/WORKFLOW.md` gets exactly the two sentence replacements plus the §6 `muse --version` bullet extension, and `AGENTS.md` is untouched.

Approved amendments (2026-10-29): (1) identity compares only `(subject_id, source, source_id, type, time, tier, data)` — a re-delivery with a new `id` and `collected_at` is a no-op, changed `data` conflicts (AT3 rewritten); (2) a conflict must not jam a collector — `append_event`/`append_events` still raise `ConflictingEvent`, but `run_collector` records each conflict in the `conflicts` table, keeps the original row, inserts the rest, advances the cursor, and returns `(inserted, conflicts)`, while any other exception still rolls back events and cursor (AT5 rewritten as (a) conflict-recorded and (b) injected non-conflict rollback). Assumptions (1), (3), (4), (5), and (6) are accepted as written.
