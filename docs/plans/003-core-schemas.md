## Goal

Ticket 3 — core schemas. After this ticket, `framework/schemas/` holds the typed contract every later ticket builds on: the `Event` envelope with a discriminated `data` union (one Pydantic model per event type), `Fact`, `Profile`, `Criterion`, `Manifest` with `BlockConfig` base, and `Decision`, all Pydantic v2, frozen, `extra="forbid"`, clean under pyright strict. Committed JSON Schema exports under `schemas/*.json` cannot drift without a test failing. No collectors, no event store, no profile-file loading, no blocks, no gate.

Grounding, checked 2026-10-29 in this session: [docs/SPEC.md](../SPEC.md) §3 (manifest example and block library), §5.2 ("Pydantic for every structured output"), §5.3 (criteria from ikigai), §6 (data model, `subject_id` separate from `profile_id` per D10); [docs/PLAN.md](../PLAN.md) §2.1 (sources table), §2.2 (event envelope and its rules), §2.3 (privacy line), §3 row T3 ("Pydantic models: `Event` (+ typed `data` per type), `Fact`, `Profile(subject_id, profile_id)`, `Criterion`, `Manifest`, `BlockConfig` base, `Decision`. JSON Schema exported to `schemas/`. Round-trip tests"); `profiles/TEMPLATE.md`, `profiles/builder.md`, `profiles/recovery.md` read only to shape `Profile` and `Criterion` (four ikigai dimensions, weights summing to 1.0, a `Limits` section, binary criteria tagged by dimension including `limit`), and not loaded or parsed anywhere in this ticket; [docs/plans/001-toolchain.md](001-toolchain.md) and [docs/plans/002-spec-v04.md](002-spec-v04.md) set the plan format and the acceptance-test style this file follows; `pyproject.toml` already pins the toolchain (Python 3.12, `pydantic` runtime dep, pyright `strict = ["framework"]`, ruff, pytest with `testpaths = ["tests"]`); `Makefile` `check` is ruff check, `ruff format --check`, pyright, pytest, `gitleaks git --redact`. Approved amendment 1: branch `t3-core-schemas` was created from updated `main` (T2 merged as PR #2, commit `26310bb`); `framework/` holds only the trivial `__init__.py` skeleton and `tests/` only `tests/test_smoke.py`. The private companion repo and the path in `HIDDEN_CRITERIA_DIR` are never read.

## Success Criteria

- `framework/schemas/` is a package of frozen, `extra="forbid"` Pydantic v2 models covering: the `Event` envelope; 21 event-payload models (one per `type`, listed in Approach); `Fact`; `Profile`; `Criterion`; `Manifest` and the `BlockConfig` base; `Decision`.
- `Event.tier` is `public | private | sensitive`; `health.daily` and `app.journal` events validate only with `tier = "sensitive"`. Calendar payloads have no title field at all: a `title` key is rejected, not ignored.
- `Profile` weights for `love / good_at / world_needs / paid_for` sum to 1.0 or validation fails; `Criterion.dimension` covers the four ikigai dimensions plus `limit` and `contrast`.
- `Manifest` follows SPEC §3: `version`, `parent`, `layout`, `blocks`, `changelog` whose entries carry evidence ids. `Decision.kind` is `noop | evolve | recalibrate | refine_objective`, with rationale, evidence ids, and an optional manifest diff.
- Running the export script writes one JSON Schema file per model to `schemas/*.json`; the committed files match the models byte-for-byte and a committed test fails when they drift.
- Tests cover a round-trip for every model and every event type, plus rejections for: extra fields, unknown event `type`, weights not summing to 1.0, a `Fact` without evidence, `health`/`journal` events not marked `sensitive`, and check-in energy outside 1–5.
- `README.md` gains exactly the Status section given in the ticket, nothing else. `docs/sessions/003-core-schemas.md` evidence note and a `CONTRIBUTIONS.md` Ticket 3 entry (real models, real efforts) exist.
- `make check` is green; exactly one commit on branch `t3-core-schemas`, not pushed.

## Approach

All models share one base: `model_config = ConfigDict(frozen=True, extra="forbid")`, defined once in `framework/schemas/base.py` as a `SchemaModel(BaseModel)` and subclassed everywhere, so no model can silently accept extra keys or be mutated after validation. Pyright strict already covers `framework/` via `pyproject.toml`; tests live in `tests/` under standard mode. No new dependencies: `pydantic` is already a runtime dep, and its version stays whatever `uv.lock` already pins (nothing is invented or upgraded in this ticket).

Key decisions:

- **Envelope shape follows PLAN §2.2, tier follows the ticket.** Fields: `id`, `subject_id`, `source`, `type`, `time`, `source_id`, `data`, `tier`, `collected_at`, `collector_version`. PLAN §2.2 shows `tier` as `private | public`; the ticket widens it to `public | private | sensitive`, and the ticket wins. `time` and `collected_at` are timezone-aware `datetime`s (a naive datetime is rejected); `id`, `subject_id`, `source`, `source_id`, `collector_version` are non-empty `str`. No ULID format check: `id` is an opaque string here; format enforcement, dedupe on `(source, source_id)`, cursors and the nightly batch hash are T4's store concerns, not schema concerns.
- **`data` is discriminated on the payload's own `type`.** Every payload model carries `type: Literal["<its event type>"]` and `Event.data` is `Annotated[<union of all 21 payloads>, Field(discriminator="type")]`. `Event.type` is the same literal at the envelope level, and a model validator rejects an envelope whose `type` differs from `data.type`. An unknown `type` therefore fails twice over: it matches no union member and no envelope literal.
- **Tier rules that depend on the event type live on `Event`, not on the payload.** A model validator enforces: `type == "health.daily"` or `type == "app.journal"` requires `tier == "sensitive"`; every other type accepts any tier. This keeps payloads source-shaped and puts the privacy rule where both fields are visible (PLAN §2.3: health values and journal text never leave the local machine in a lower tier).
- **Calendar payloads structurally cannot carry a title.** The three calendar payloads simply have no `title` field; with `extra="forbid"` a collector that passes one fails validation instead of leaking it (PLAN §2.1: "title kept private"). A test asserts `title` is rejected and that no calendar model has a `title` field/property.
- **Counts are typed, not free dicts, where the stages are fixed; open where they are not.** `jobs.snapshot` gets a frozen `JobStageCounts` (`applied`, `screen`, `interview`, `offer`, each `int >= 0`, extra-forbid) because PLAN/profiles fix those four stages. `github.*` keeps `repo: str` plus `counts: dict[str, int]` with values `>= 0`, and `screen.hour` keeps minutes per category as `dict[str, float]` with values `>= 0`, because GitHub count keys and ActivityWatch category sets are collector-defined and not fixed by SPEC/PLAN. `editor.hour` gets `project: str`, `language: str`, `minutes: float >= 0` (the ticket text reads "project, langu minutes"; read as language + minutes, stated here for approval).
- **App telemetry payloads get the smallest fields that make each type usable, and nothing personal.** `app.view`: `block_id`, optional `screen`; `app.tap`: `block_id`, `target`; `app.thumb`: `block_id`, `value` in `{-1, 1}`; `app.rating`: `block_id` (optional), `value: float`; `app.approve` / `app.reject`: `manifest_version`, optional `card_id`; `app.checkin`: `energy: int` in 1–5 (the range is the field constraint itself, so energy 6 fails as a plain validation error); `app.journal`: `text: str` non-empty. These mirror SPEC §4's feedback row ("usage, 👍/👎, ratings") and §5.6 (approve/reject as labels); any field a later ticket needs is added there, under `extra="forbid"` discipline.
- **`Fact.window` is a typed range, not a string.** A frozen `FactWindow` (`start`, `end`, both timezone-aware, `end >= start` validated) so Glimmer (T9) cannot emit an inverted window. `Fact` is `id`, `subject_id`, `window`, `statement` (non-empty), `evidence: list[str]` with `min_length=1` (a fact citing no event is invalid, per SPEC §5.2's "Every fact cites event IDs"), and `tier` (same three-tier literal; facts derived from sensitive events may stay sensitive).
- **`Profile` mirrors the profile files' shape without parsing them.** `subject_id`, `profile_id`, `label`, `version: int >= 1`, and a frozen `IkigaiWeights` (`love`, `good_at`, `world_needs`, `paid_for`, each in [0, 1]) whose validator requires the sum to equal 1.0 within an absolute tolerance of 1e-6 (float weights like 0.30/0.30/0.30/0.10 from `profiles/builder.md` must pass; 0.9 must fail). Loading the markdown into this model is T10, not this ticket.
- **`Criterion.dimension` is one enum including the non-ikigai tags.** `Literal["love", "good_at", "world_needs", "paid_for", "limit", "contrast"]`: the four dimensions from §5.3, `limit` from the profiles' Limits sections and TEMPLATE's example criteria ("(limit)"), and `contrast` per the ticket. `Criterion` is `id`, `profile_id`, `dimension`, `text` (non-empty, the binary criterion wording), `hidden: bool`, `version: int >= 1`. The model never reads `HIDDEN_CRITERIA_DIR`; it only carries the `hidden` flag.
- **`Manifest` and `BlockConfig` follow the SPEC §3 example literally.** `Manifest`: `version: str`, `parent: str | None` (None for the day-0 root), `layout: list[str]` (ordered block ids like `"playlist#evening"`), `blocks: dict[str, BlockConfig]`, `changelog: list[ChangelogEntry]`. `ChangelogEntry`: `change: str`, `why: str`, `evidence: list[str]` with `min_length=1`, plus optional `from_version: str | None` (SPEC's example writes `"from": "v13"`; the field is named `from_version` with alias `from` accepted on input, since `from` is a Python keyword). `BlockConfig` is the base later blocks subclass in T6: `type: str`, `dimension` (the same dimension literal), `config: dict[str, Any]` defaulting to empty, `rationale: str` defaulting to `""`. It stays a base, not a discriminated union: per-block config schemas arrive with the blocks themselves.
- **`Decision` follows the ticket's four kinds.** `kind: Literal["noop", "evolve", "recalibrate", "refine_objective"]` (SPEC §4's diagram labels one arrow `recalibrate_evals`; the ticket's `recalibrate` wins and T11 uses this literal). Fields: `kind`, `rationale: str` (may be empty only for `noop`), `evidence: list[str]` of evidence ids with `min_length=1` except that `noop` may carry an empty list, and `manifest_diff: ManifestDiff | None`. `ManifestDiff` is a frozen model (`base_version: str`, `candidate: Manifest`). A validator enforces: `kind == "evolve"` requires `manifest_diff` whose `candidate.parent == base_version`; any other kind forbids `manifest_diff`.
- **JSON Schema export is generated, never hand-edited, and drift is a test failure.** `framework/schemas/export_schemas.py`, run as `uv run python -m framework.schemas.export_schemas`, writes `schemas/<ModelName>.json` for every exported model (envelope, all 21 payloads, the small value models, `Fact`, `Profile`, `Criterion`, `Manifest`, `BlockConfig`, `Decision`) using `model_json_schema()` with sorted keys and a trailing newline, so output is deterministic. A test regenerates each schema in memory and compares it to the committed file; any difference fails with the model name. The export target is the top-level `schemas/` directory from PLAN §3/T3, distinct from the `framework/schemas/` package.
- **Fixtures are synthetic only.** Tests build events for `subject-1` (the generic placeholder PLAN §2.2/§2.3 use) with invented repos, tracks and values. No real names beyond that placeholder, no hosts, no paths, no personal values; nothing reads `~/workspace/ikigai-loop-private` or `HIDDEN_CRITERIA_DIR`.
- **README change is byte-exact and isolated.** The only edit to `README.md` appends the ticket's `## Status` section verbatim (three lines plus the three bullets). It is diffed against the ticket text before commit.
- **Branch and commit follow the established pattern.** Work happens on `t3-core-schemas`, created from updated `main` after T2 merged (amendment 1). This plan stays uncommitted in the working tree until implementation; plan, implementation and evidence note land as one commit, not pushed.

Event payload inventory (21 models; every field required unless marked optional; all counts/minutes/scores non-negative):

| Event `type` | Payload fields (beyond the `type` literal) |
|---|---|
| `calendar.event.created` / `.updated` / `.cancelled` | `start`, `end` (tz-aware datetimes, `end >= start`), `busy: bool`, `category: str`, `tags: list[str]`, `is_new: bool`. No `title` field exists |
| `github.push` | `repo: str`, `counts: dict[str, int >= 0]` (e.g. commits) |
| `github.pr` | `repo: str`, `counts: dict[str, int >= 0]` (e.g. opened, merged) |
| `github.issue` | `repo: str`, `counts: dict[str, int >= 0]` (e.g. opened, closed) |
| `github.release` | `repo: str`, `counts: dict[str, int >= 0]` (e.g. published) |
| `feed.item` | `title: str`, `url: str`, `source: str`, `score: float` |
| `music.play` | `track: str`, `artist: str`, `played_at` (tz-aware datetime) |
| `health.daily` | Every metric optional (`None` when the source has no sample that day; amendment 2): `sleep_h: float \| None`, `resting_hr: float \| None`, `hrv_ms: float \| None`, `steps: int \| None`, `exercise_min: float \| None`, `mindful_min: float \| None`, `mood_valence: float \| None` in [-1, 1] (Apple State of Mind). Envelope tier must be `sensitive` |
| `screen.hour` | `device: Literal["mac", "iphone"]`, `minutes_by_category: dict[str, float >= 0]` |
| `editor.hour` | `project: str`, `language: str`, `minutes: float >= 0` |
| `jobs.snapshot` | `counts: JobStageCounts` (`applied`, `screen`, `interview`, `offer`; each `int >= 0`) |
| `app.view` | `block_id: str`, `screen: str | None = None` |
| `app.tap` | `block_id: str`, `target: str` |
| `app.thumb` | `block_id: str`, `value: Literal[-1, 1]` |
| `app.rating` | `block_id: str | None = None`, `value: float` |
| `app.approve` / `app.reject` | `manifest_version: str`, `card_id: str | None = None` |
| `app.checkin` | `energy: int`, constrained 1–5 |
| `app.journal` | `text: str` non-empty. Envelope tier must be `sensitive` |

## Files to Create

| File | Contents |
|---|---|
| `framework/schemas/__init__.py` | Package marker plus re-exports of every public model (`Event`, the 21 payloads, `Fact`, `Profile`, `Criterion`, `Manifest`, `BlockConfig`, `Decision` and the small value models), with `__all__` |
| `framework/schemas/base.py` | `SchemaModel`: `BaseModel` with `ConfigDict(frozen=True, extra="forbid")`, shared tier/dimension literals if placed here |
| `framework/schemas/events.py` | The 21 payload models, the payload union, and the `Event` envelope with the type/tier validators |
| `framework/schemas/core.py` | `FactWindow`, `Fact`, `IkigaiWeights`, `Profile`, `Criterion` |
| `framework/schemas/manifest.py` | `BlockConfig`, `ChangelogEntry`, `Manifest`, `ManifestDiff`, `Decision` |
| `framework/schemas/export_schemas.py` | Runnable module (`python -m framework.schemas.export_schemas`) writing `schemas/<ModelName>.json` deterministically for every exported model |
| `schemas/*.json` | One committed JSON Schema per exported model, generated by the export module, never hand-edited |
| `tests/test_schemas_events.py` | Round-trip for the envelope and all 21 event types, plus a `health.daily` round-trip with all metrics `None`; rejections: extra field, unknown type, envelope/payload type mismatch, calendar `title`, non-sensitive `health.daily` / `app.journal`, check-in energy 0 and 6, naive datetime |
| `tests/test_schemas_core.py` | Round-trips for `Fact`, `Profile`, `Criterion`, `Manifest`, `BlockConfig`, `Decision`; rejections: `Fact` with empty evidence, weights summing to 0.9, weight outside [0, 1], inverted fact window, `evolve` without a diff, diff on a non-`evolve` kind, changelog entry without evidence, extra fields on each model |
| `tests/test_schemas_export.py` | Drift test: regenerate every model's JSON Schema in memory and assert equality with the committed `schemas/*.json`; assert one file exists per exported model; negative case writes a modified schema to `tmp_path` and asserts the drift check fails naming the model (amendment 3) |
| `docs/sessions/003-core-schemas.md` | Evidence note mirroring `docs/sessions/002-spec-v04.md`: models and efforts for plan/implementation, wall time, acceptance-test results, the statement that the raw redacted export is kept privately |

## Files to Modify

| File | Change |
|---|---|
| `README.md` | Append exactly the ticket's `## Status` section (heading, the "Building. Day 0…" line, and the three bullets), nothing else |
| `CONTRIBUTIONS.md` | Add a `Ticket 3 — core schemas` entry after the Ticket 2 entry (chronological; amendment 4), same shape as the existing entries: what was built, the branch and plan link, date, and the real Muse models and efforts used for plan and implementation |
| `docs/plans/003-core-schemas.md` | This plan, committed with the implementation (per the Ticket 1/2 pattern) |

No other existing files change. `pyproject.toml` and `uv.lock` stay untouched (no new deps), `profiles/*.md` are read-only shaping input and are not opened by any code or test, and nothing reads the path in `HIDDEN_CRITERIA_DIR` or the private companion repo.

## Steps

1. Pre-flight: confirm `git branch --show-current` is `t3-core-schemas` created from updated `main` (T2 merged, amendment 1). Negative control on `main` first: `uv run pytest` has no schema tests and `framework/schemas/` and `schemas/` do not exist (AT10).
2. Write the tests first (`tests/test_schemas_events.py`, `tests/test_schemas_core.py`, `tests/test_schemas_export.py`) against synthetic `subject-1` fixtures, and confirm they fail because the models do not exist yet.
3. Implement `framework/schemas/base.py`, then `events.py`, `core.py`, `manifest.py`, then the re-exporting `__init__.py`, keeping every model frozen and extra-forbid. Run `make test` until green, then pyright/ruff via `make check` and fix findings in the schemas, not by relaxing config.
4. Add `framework/schemas/export_schemas.py`, run it to generate `schemas/*.json`, and confirm the drift test passes; re-run the export and confirm `git status` shows no change (deterministic output).
5. Append the exact `## Status` section to `README.md` and diff the appended block against the ticket text; add the `CONTRIBUTIONS.md` Ticket 3 entry after the Ticket 2 entry (amendment 4) with the real models/efforts.
6. Public-repo sweep over every touched file: real names (beyond the published `subject-1` placeholder and Carlos's own name where it already appears), hosts, ports, private paths, personal or health values, secrets. Health/mood/track values in tests must be obviously synthetic.
7. Write `docs/sessions/003-core-schemas.md`; run all acceptance tests and `make check`.
8. One commit on `t3-core-schemas` containing exactly: `docs/plans/003-core-schemas.md`, `framework/schemas/` (6 files), `schemas/*.json`, `tests/test_schemas_events.py`, `tests/test_schemas_core.py`, `tests/test_schemas_export.py`, `README.md`, `CONTRIBUTIONS.md`, `docs/sessions/003-core-schemas.md`. Do not push.

## Acceptance Tests

Each is a command plus its expected result. AT1–AT9 pass on the branch; AT10 is the negative control on the base.

| # | Command | Expected result |
|---|---|---|
| AT1 | `uv run pytest tests/test_schemas_events.py` | Exit 0; a round-trip test (`model_validate` → `model_dump` → `model_validate`, plus a JSON round-trip) passes for the envelope and each of the 21 event types, including a `health.daily` round-trip with all metrics `None` (amendment 2) |
| AT2 | `uv run pytest tests/test_schemas_events.py -k reject` (rejection tests) | Exit 0; extra field, unknown `type`, envelope/payload `type` mismatch, calendar `title`, `health.daily` with `tier="private"`, `app.journal` with `tier="private"`, check-in `energy` 0 and 6, and a naive `time` datetime each raise `ValidationError` |
| AT3 | `uv run pytest tests/test_schemas_core.py` | Exit 0; round-trips pass for `Fact`, `Profile`, `Criterion`, `Manifest`, `BlockConfig`, `Decision`; rejections raise for empty `Fact.evidence`, weights summing to 0.9, a weight of 1.5, an inverted fact window, `evolve` without `manifest_diff`, `manifest_diff` on `noop`, and a changelog entry with empty `evidence` |
| AT4 | `uv run python -m framework.schemas.export_schemas` then `git status --porcelain schemas/` | Exit 0; no output from `git status` (committed schemas are current and generation is deterministic); one `schemas/*.json` exists per exported model |
| AT5 | `uv run pytest tests/test_schemas_export.py` | Exit 0; the committed tree passes, and the negative case writes a modified schema to `tmp_path` and asserts the drift check fails naming the model (amendment 3) |
| AT6 | `sed -n '/^## Status/,$p' README.md` diffed against the ticket's section text | Byte-identical to the section in the ticket; `git diff README.md` shows only those lines added |
| AT7 | Manual public-repo sweep (step 6) recorded in the evidence note, then `make check` | Sweep clean; `make check` exit 0 (ruff check, `ruff format --check`, pyright strict on `framework/`, pytest including `tests/test_smoke.py`, `gitleaks git --redact` no leaks) |
| AT8 | `uv run python -c "import json,glob; [json.load(open(f)) for f in glob.glob('schemas/*.json')]"` and a grep that no `schemas/*.json` or test fixture contains a real name/host/path | Exit 0; every exported schema parses as JSON; fixtures use only `subject-1` and invented values |
| AT9 | `git log --oneline main..HEAD` and `git show --stat HEAD` and `git status -sb` | Plain `git log --oneline main..HEAD` shows exactly 1 commit on `t3-core-schemas` (amendment 1), containing only the files in step 8; no upstream push (no tracking branch) |
| AT10 | Negative control on `main`: `test -d framework/schemas; test -d schemas; uv run pytest` | Neither directory exists and no schema test is collected on `main` (amendment 1), confirming the tests measure this ticket's work |

## Risks

- **Underspecified payload fields.** The ticket fixes some payloads field-by-field (`health.daily`, `jobs.snapshot`, `app.checkin`, `app.journal`) and others only by theme (GitHub "repo, counts", app telemetry types other than check-in/journal). A wrong guess here forces edits in T5/T7/T13 collectors. Mitigated by keeping those payloads minimal and collector-shaped (step 3), and by `extra="forbid"` making any later addition an explicit, test-visible change. The `editor.hour` reading ("language + minutes") is the one explicit interpretation; approval of this plan accepts it.
- **Naming collisions and drift between `Event.type` and `data.type`.** Two literals that must agree can drift when T5 adds a type. Mitigated by the agreement validator now and by the round-trip test enumerating all 21 types explicitly, so a 22nd type added without tests is visible in review.
- **`ManifestDiff` shape.** SPEC §3 shows diffs only as rendered changelog text; a structured diff is this plan's design. If T11's Wonder step wants a field-level diff instead, `ManifestDiff` changes there — contained, because only `Decision` references it and the drift test pins its schema.
- **Float weight tolerance.** Too tight and 0.30/0.30/0.30/0.10 fails on float error; too loose and 0.99 passes as "1.0". Fixed at 1e-6 absolute, with AT3 testing both 0.9 (fail) and the real profile weight sets (pass).
- **JSON Schema drift test brittleness.** Pydantic emits schemas that can change across versions; `uv.lock` pins the version, and any future bump regenerates `schemas/*.json` in the same commit, which the drift test enforces rather than hides.
- **Leaking private context through fixtures.** Event payloads are exactly where real track names, health values or calendar details would sneak in. Mitigated by synthetic `subject-1` fixtures, the step 6 sweep, and gitleaks in `make check`.

## Test Plan

Committed tests are the deliverable: `tests/test_schemas_events.py` (every event type round-trips, plus the all-`None` `health.daily` case; the eight rejection cases), `tests/test_schemas_core.py` (the six core models round-trip; the seven rejection cases), `tests/test_schemas_export.py` (drift, including the `tmp_path` negative case). Written before the models (step 2) so they fail on the base and pass on the branch, per the Definition of Done. No network in any test; no test reads `profiles/*.md`, `HIDDEN_CRITERIA_DIR`, or any path outside the repo. Sequence: AT10 negative control on `main`, AT1–AT8 on the branch, `make check`, then AT9 after committing. No eval or block changes, so no Inspect log or mutant run applies to this ticket.

## Out of Scope

- Loading or parsing `profiles/*.md` into `Profile`/`Criterion`, drafting criteria, and any handling of hidden criteria beyond the `hidden: bool` flag (T10; the hidden-criteria CI guard lands there too).
- Event store, upsert/dedupe, cursors, nightly batch hash, and the `Collector` protocol (T4); collectors themselves (T5, T7, T13).
- Concrete block config schemas and the renderer (T6); `Manifest` is only validated as data here, never rendered.
- Glimmer fact extraction (T9), Wonder decisions in the loop (T11): `Fact` and `Decision` are schemas only.
- ULID generation/format enforcement, timezone database handling, and any migration of these models into SQLite (T4).

## Open Questions

None. Assumptions stated for approval: (1) `editor.hour` carries `project`, `language`, `minutes`; (2) GitHub counts and screen minutes stay open `dict`s while job stages get the typed `JobStageCounts`; (3) app telemetry payloads get the minimal fields in the inventory table; (4) `ManifestDiff` is `base_version` + a full `candidate: Manifest`, required exactly for `evolve`; (5) `Decision` uses the ticket's `recalibrate` literal over SPEC's `recalibrate_evals` label, and `Event.tier` uses the ticket's three tiers over PLAN §2.2's two; (6) branch base as originally written, superseded by amendment 1 (`t3-core-schemas` from updated `main`). Approval of this plan accepts those six, as amended.

Approved amendments (2026-10-29): (1) `t3-core-schemas` from updated `main`, AT9 plain `git log --oneline main..HEAD` = 1, AT10 on `main`; (2) `health.daily` metrics all optional, `mood_valence: float | None` in [-1, 1], all-`None` round-trip; (3) AT5 negative drift case in `tmp_path` naming the model; (4) `CONTRIBUTIONS.md` Ticket 3 entry after Ticket 2. The six assumptions above are accepted.
