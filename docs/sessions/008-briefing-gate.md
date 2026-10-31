# Session evidence — 008-briefing-gate (2026-10-31)

Ticket 8 only; two sessions per ticket (plan, then implementation). This
note summarises the work; the raw redacted export is kept privately and
published only if gitleaks plus a manual check of names and context is
clean.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## Plan

- Plan: `docs/plans/008-briefing-gate.md` (approved as written, including
  C1–C6, D1–D8 and the seven stated assumptions; this implementation
  session did not observe the plan session's model). Implementation:
  muse-spark (Muse Code, this session).
- The artifact change from a mutating app to a gated briefing is
  implemented exactly as briefed: `framework/briefing/` holds the typed
  `Briefing` schema, the pure deterministic gate (L0/L1/L1b), and the
  reference-data context; `evals/` holds the Inspect tasks plus the
  16-mutant / 12-known-good meta-eval. No renderer, deployer, manifest
  diff, or `framework/blocks/` change (C1, C4); no L2/L3 jury, L4 canary,
  or model judge (C2); the meta-eval target is 16/16 caught + 12
  known-good with 0 false rejections, superseding the old 7-mutant /
  10-known-good wording for this ticket (C3); the gate consumes one
  briefing plus `GateContext`, with no objective/J scoring and no
  autonomy work (C5); the gate never parses markdown — the builder edit
  only documents the limits a caller encodes (C6).
- Disagreements resolved as pinned in the plan: `since_last` refs are
  deltas, other refs are snapshot-equal (D1); mask-then-extract number
  tokens with the spelled-out gap accepted (D2); raw-ness comes from
  caller-supplied `raw_metric_ids` / `forbidden_raw_literals` plus the
  `raw.*` prefix arm (D3); one-term-per-line sorted-file private-terms
  loader, fail closed (D4); no gate rule for the 20:00–22:30 window (D5);
  `Claim.id` added, sections keyed by `type` (D6); the gate claims
  exactly its pinned regex set, gitleaks stays the backstop (D7); the
  scorer is a meta-eval harness and CI binds on the pytest meta-eval (D8).
- Every `uv`, `pre-commit`, and `git` command in this session ran under
  `PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
  `UV_CACHE_DIR="$PWD/.git/uv-cache"`.
- Deviations from the plan's letter, all behaviour-preserving: (1) the
  eval file bootstraps `sys.path` to the repo root so the exact AT11
  command works under the Inspect loader (pytest already sets
  `pythonpath`); (2) pydantic list fields use the repo's
  `Annotated[list[X], Field(default_factory=list)]` form after pyright
  strict rejected the bare form for module-local models; (3) direct
  `TimeInterval` / `ProfileLimits` / `Action` constructions in fixtures
  and tests pass real `datetime` / `time` objects instead of strings;
  (4) the gate's raw pre-scan annotates JSON-shaped values as `object`
  with two narrow `cast`s to satisfy pyright strict. No rule, code,
  mutant, or known-good case was changed to make tests pass.

## Implementation

- Files: `docs/plans/008-briefing-gate.md` (committed with the
  implementation), `framework/briefing/` (`schemas.py`, `context.py`
  with `load_private_terms`, `numbers.py`, `gate.py`, `__init__.py`),
  `framework/schemas/export_schemas.py` (9 briefing models appended),
  9 new `schemas/*.json` (regenerated via
  `uv run python -m framework.schemas.export_schemas`, no hand edits),
  `evals/briefing_cases.py` (frozen `Case`, `base_case`,
  `base_case_with_parent`, `MUTANTS` M1–M16, `KNOWN_GOOD` G1–G12),
  `evals/briefing_gate.py` (`gate_scorer` + the four tasks),
  `tests/test_briefing_schemas.py`, `tests/test_briefing_numbers.py`,
  `tests/test_briefing_gate.py`, `tests/test_briefing_mutants.py`,
  `tests/test_briefing_eval.py`,
  `framework/collectors/__main__.py` (line 97 only: `conflicts=` to
  `noop=`), `tests/test_collectors_cli.py` (line 341 only),
  `profiles/builder.md` (line-43 bullet only), `CONTRIBUTIONS.md`
  (Ticket 8 entry), this file.
- Tests were written first and failed at collection with no
  `framework.briefing` package (AT15 pre-flight plus the step-2 run:
  5 collection errors).
- The real `HIDDEN_CRITERIA_DIR` was never opened in this session; the
  one-term-per-line format is an assumption flagged for Carlos to verify
  against the real directory himself. All fixtures are synthetic
  (`subject-1`, `fact:synthetic-*`, `agg.*`, `synthetic@example.invalid`,
  invented titles); no test reads the real directory, a real calendar /
  health source, `profiles/*.md` at runtime, or the network.
- No live briefing send, live poll, or live push was run; the gate does
  no network and no model call.

## Review fixes (same branch, before review approval, uncommitted)

Carlos's review found gate holes; all are fixed on `t8-briefing-gate`
without weakening any existing rule, mutant, or known-good case
(the meta-eval is 20/20 + 12/12 after the fixes). Principle applied
throughout: when in doubt the gate rejects.

- Numbers (`numbers.py`, `gate.py` L1b): bare years are tokens except
  inside full dates; identifiers/colon references mask only on exact
  equality with a fact/metric ID cited on that claim
  (`extract_number_tokens` takes `known_ids`; the gate passes each
  claim's cited IDs); month names match only capitalized (`May 9` free,
  `may 9` a token); dotted versions are never masked; colon times before
  duration words are quantities; spelled-out `one`–`twenty` and
  `thirty`–`ninety` are tokens only before unit words (`hours`, `hr`,
  `minutes`, `min`, `steps`, `days`, `percent`), so `nine hours` is
  rejected and `one of the` still passes. The eleven review strings
  (`2000 steps` ×3, `Sleep:9h`, `sleep:9`, `hrv-99`, `steps9065`,
  `8:30 hours`, `may 9 hours`, `1.2.3 hours`, `nine hours`) each fail
  with exactly `L1B_NUMBER_WITHOUT_METRIC_REF`; `On 2026-10-30 at 13:30`,
  `On Oct 30`, `May 9`, `the 3rd` still pass. G9 now cites `fact:212`
  (added as a synthetic context fact) and gains `May 9` / `3rd` claims.
- Raw literals match casefolded and whitespace-collapsed with the token
  boundary kept (lowercase, uppercase, double-spaced variants rejected).
- Parent: `L1B_PARENT_MISMATCH` also fires when the briefing names no
  parent while the context holds one (M17), on parent `profile_id`
  (M18) or `subject_id` (M19) mismatch, and when the parent slot is not
  strictly before the child slot (M20).
- Private terms, fail closed: `GateContext.private_terms_available`
  defaults to `False` (every fixture sets it explicitly); the loader
  reads only `deny-terms.txt` (other criteria files ignored), skips
  blanks and `#` lines, and returns available `False` when the file is
  missing, has no terms, is not UTF-8, or any line starts with `- ` or
  `* `; terms of 3 characters or fewer match whole words only. The
  format is documented in `.env.example` with no real term.
- Malformed input never raises: an unhashable or non-string section
  type is `L0_UNKNOWN_SECTION`; a non-mapping top level is
  `L0_SCHEMA_INVALID` at `briefing`.
- `L1_SECRET` also matches any hostname ending in `.ts.net` via a
  generic pattern containing no real hostname.
- Two disclosed L1b gaps, accepted (also added to the plan Risks): the
  gate checks that a value matches a ref, not that the prose attaches it
  to the right metric; backing compares absolute values, so direction
  words are not checked. Both are later-L2-criterion material, not fixed
  here.
- Known number-extraction misses, to revisit in T11: compound spelled-out
  numbers ('ten thousand steps', 'eight and a half hours'); a month plus
  a year-like number ('May 2000 steps'); a date ending in a year-like
  number ('12/25/2000 steps'); a time before a non-duration unit
  ('10:30 steps').

## Acceptance tests

- AT1 passed: `test_briefing_schemas + test_schemas_export` — round-trips
  for the briefing + context models pass, the pinned rejections raise,
  `find_drift == []`, and `git status` shows exactly the 9 new briefing
  schema files with no existing schema rewritten.
- AT2 passed: `test_briefing_numbers` — every masking arm
  (ISO/day-first/month-name dates, years-in-position, times/ranges,
  identifiers, dotted versions, references, ordinals) and every
  extraction arm (integers, commas, decimals, negatives, `50%` → `50`,
  word durations extracted, spelled-out ignored, hyphen rule, token
  `places`) matches the Approach spec.
- AT3 passed: `-k "l0 or schema or duplicate or action_count or
  missing_section or empty_section"` — all 8 L0 codes fire at their
  pinned locations and an L0-invalid briefing returns no L1/L1b.
- AT4 passed: `-k "secret or pii or private or raw or english"` —
  `L1_SECRET`, `L1_PII`, `L1_PRIVATE_TERM`, `L1_RAW_VALUE` (both arms)
  fire with no matched string in any message; the short-after-prefix and
  mid-word arms pass, `L1_PRIVATE_TERMS_UNAVAILABLE` fires when
  availability is false, and `load_private_terms` passes terms only from
  a synthetic `tmp_path` dir or under `allow_missing_for_tests=True`.
- AT5 passed: `-k "slot or busy or free or repo_target or before_slot or
  check_slot"` — slot boundaries (13:00 passes, 23:30 fails),
  `check_slot=False` skipping only the slot check,
  `L1_ACTION_BEFORE_SLOT` under both flag values with exactly-at-slot
  passing, busy overlap / free gap / boundary touch /
  busy-suppresses-not-free, and `L1_ACTION_TARGETS_REPO` all match
  Approach.
- AT6 passed: `-k "fact or evidence or number_backing or rounding or
  metric or delta or parent or determin"` — evidence, unknown /
  other-subject fact, unbacked number, `21.2`←`21.1544` / `down 5`←`-5`
  backing with snapshot-wrong refs still failing exactly, unknown metric,
  snapshot mismatch, parent mismatch, missing `since_last`,
  `since_last`-without-parent, wrong delta, repeat + reorder determinism.
- AT7 passed: `test_briefing_mutants` — 20 mutants each fail with exactly
  `[expected]`, 12 known-good pass with `()`, counts asserted (33 tests).
- AT8 passed: `test_briefing_eval` — the four tasks exist with case-name
  sample IDs, layer-filtered targets are correct, and `score_briefing`
  agrees with `evaluate_briefing` on every case (5 tests).
- AT9 passed: `grep` for `framework.blocks` imports across
  `framework/briefing/`, `evals/briefing_gate.py`,
  `evals/briefing_cases.py` is empty; `git diff --stat main --
  framework/blocks/ docs/SPEC.md docs/PLAN.md` is empty.
- AT10 passed: `test_collectors_cli` — the push assertion reads
  `inserted=1 noop=0`, every other `conflicts=` assertion unchanged
  (15 tests).
- AT11 passed: the four briefing tasks ran offline on `mockllm/model`
  (32 samples each after the review added M17–M20 — 20 mutants plus 12
  known-good — all scores correct, 128/128). Logs (gitignored, final-run
  paths recorded here):
  `logs/2026-10-31T22-48-09-00-00_briefing-l0_QaFpSqnver7PAoz4aHTdYn.eval`,
  `logs/2026-10-31T22-48-09-00-00_briefing-l1_6MeyegKww5gpW4fRantfte.eval`,
  `logs/2026-10-31T22-48-09-00-00_briefing-l1b_hLyyTfwaza2yQfzKePidmU.eval`,
  `logs/2026-10-31T22-48-09-00-00_briefing-gate_T7twRoCGVwrrfMJ4DGMGv9.eval`.
  `evals/hello.py` and `make eval` are unchanged.
- AT12 passed: line 97 prints `noop={noop}`; lines 72, 120, 122 still
  print `conflicts=`; `git diff framework/collectors/__main__.py` is one
  line.
- AT13 passed: the 20:00–22:30 bullet carries the until-2026-11-04 /
  from-2026-11-05 wording exactly; the 13:00–23:30 bullet is unchanged;
  the diff touches only that one bullet.
- AT14 partial: ruff check, ruff format check, and pyright strict on
  `framework/` are green; gitleaks reports no leaks (git history and a
  `--no-git` full-tree scan covering untracked fixtures). Full pytest is
  292 passed + 1 failed: the failure is the pre-existing
  `tests/test_ingest.py::test_live_loopback_server_health_round_trip`.
  Root-caused, not just re-run: the server thread dies at
  `HTTPServer(("127.0.0.1", 0), …)` with
  `PermissionError: [Errno 1] Operation not permitted` — this sandbox
  denies even loopback binds (a bare `socket.bind(("127.0.0.1", 0))`
  fails the same way), and the test fails identically on the clean base
  tree (verified via stash). It is untouched by this ticket and unrelated
  to the gate, which has no network code — per the ticket handoff, the
  live test here is adversarial cases, not the loopback run. The reviewer
  ran make check outside this sandbox on this tree: 322 passed, including
  the loopback test. The step-10 commit is NOT made yet (awaiting
  review).
- AT15 passed (negative control on the base tree): the briefing test
  files did not exist so pytest collected 0 items, `framework/briefing`
  did not exist, and the `noop=` count in `framework/collectors/
  __main__.py` was 0.
- Public-repo sweep over every touched file: no real names, no real
  health/calendar values, no private terms (the M6 term and the raw
  literal are invented), hosts limited to `example.invalid` plus the
  pinned mock names, no private paths or device IDs, no tokens or
  secrets (the M5 token string is 16 synthetic characters and gitleaks
  is clean on the full tree).
