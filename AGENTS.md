# AGENTS.md

Muse Code reads this file as project rules when it runs in this directory.

## Mission

Ikigai Loop: one person, same signals, two objective profiles, two apps that diverge.
The evaluator is built first and earns autonomy only by measured agreement with human judgment.
Spec: [docs/SPEC.md](docs/SPEC.md). Workflow: [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Commands

Planned (ticket 1): the `Makefile` does not exist yet.

- `make check` — ruff, pyright strict on `framework/`, pytest, gitleaks.
- `make test` — pytest only.
- `make eval` — Inspect AI eval gate (L0–L4) and mutant suite.
- `make demo` — run the public demo on fixtures.

## Layout

- `framework/` — Glimmer, Wonder, Muse Code runner, adapters, deployer, models.
- `blocks/` — one folder per block: schema, renderer, tests.
- `evals/` — Inspect tasks (L0–L4), scorers, jury, mutants, calibration.
- `profiles/` — objective profiles A and B (ikigai, weights).
- `personas/` — 3 synthetic personas (ikigai + event streams).
- `fixtures/` — synthetic data for tests and the public demo.
- `ops/` — systemd units, watchdog snippet, runbook.
- `docs/plans/` — one plan per ticket (`NNN-slug.md`).
- `docs/sessions/` — redacted Muse session export per merged ticket.

## Hard rules

- Typed manifests only (Pydantic). The app is data; no free-form app rewrites.
- A new block requires a Pydantic schema, a renderer, a unit test, and an L0 eval sample.
- No network in tests.
- No secrets in code or logs; keys from environment at runtime.
- No personal data in repo or traces; fixtures only; redact before tracing.
- Hidden criteria live outside the repo at the path in `HIDDEN_CRITERIA_DIR`; agents must never read that path. Only the gate's jury step loads them at runtime. They are published in the repo on Nov 4.
- Every new file belongs to a ticket.

## Definition of Done

- [ ] The acceptance tests from the plan exist, and they fail on `main` and pass on the branch.
- [ ] `make check` is green: ruff, pyright strict on `framework/`, pytest, gitleaks.
- [ ] If an eval or block changed: the Inspect log is attached, and all 7 mutants are still caught.
- [ ] The review has no open blockers. Majors are fixed or recorded as issues.
- [ ] The redacted session export is in `docs/sessions/`, and the PR links the plan and the export.
- [ ] `CONTRIBUTIONS.md` is updated with what was built, when, with which Muse models, and the advisory role.

## Workflow

- Follow [docs/WORKFLOW.md](docs/WORKFLOW.md) §5 for every ticket.
- Stop after the plan for approval; do not implement until the plan is approved.
- One worktree per ticket.
- Never commit or push unless asked in this session.

## Toolchain and models

- Python 3.12 with `uv`.
- Meta API at `https://api.meta.ai/v1` with key from `META_API_KEY`.
- Local models only via `LOCAL_LLM_BASE_URL`.
- No other model endpoints.

## Don'ts

- Don't read, copy, or edit the hidden criteria at the path in `HIDDEN_CRITERIA_DIR`, and don't add them to the repo before Nov 4.
- Don't change the mutant fixtures to make the gate pass.
- Don't widen permissions.
- Don't use `--yolo`; safety comes from the worktree, the restricted permission profile, and the eval gate.
- Don't ship without a gate pass; rollback is a pointer flip to the last known good manifest.

Planned (ticket 1): CI fails any PR that commits hidden criteria or copies them from `HIDDEN_CRITERIA_DIR` into the repo without the `eval-owner` label, which only Carlos applies.
