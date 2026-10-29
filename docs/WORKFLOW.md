# Ikigai Loop: How we build it (v0.1)

Carlos does all the hands-on work with the Muse family. Claude advises and reviews only: it reads plans and diffs and gives findings, and never edits the repo or makes commits.

Everything here is grounded in what Muse Code 1.4.10 exposes (`muse --help`, checked 2026-10-27). Items marked **verify** are flags or paths I saw in help text but haven't exercised yet.

---

## 1. Principles

1. **Every change is a ticket with acceptance criteria.** It's planned and implemented in its own worktree, and the Definition of Done (§6) is checked before merging. No "quick fixes" on `main`.
2. **The repo teaches the agent.** Rules live in `AGENTS.md`, repeatable procedures live in project skills, and hard guarantees live in hooks or CI. When Muse makes the same mistake twice, fix the rule, not the prompt.
3. **Separate the roles.** Wonder plans and reviews, Spark implements, and a fresh session reviews the work. Nothing reviews its own output in the same session.
4. **Evidence is part of the deliverable.** Each merged ticket keeps its plan, its redacted Muse session export and its check results. These records also prove which work was "built during the event".
5. **Dogfood it.** The framework's C3 path (Wonder writes a spec, Muse Code builds the block) uses the same `AGENTS.md`, skills and checks that Carlos uses. Judges see one pipeline, not two.

---

## 2. One-time repo setup (Oct 27–28, about 60 min, done with Muse)

| # | Step | How |
|---|---|---|
| 1 | Create the public repo | Carlos runs `gh repo create ikigai-loop --public` (outward-facing, so you do it yourself) |
| 2 | Scaffold the agent config | `muse init`, then rewrite `AGENTS.md` with Wonder (see §3) |
| 3 | Pin the toolchain | Ask Muse for: `uv` project on Python 3.12, `ruff`, `pyright`, `pytest`, `inspect-ai`, a `Makefile` with `make check`, `pre-commit` with gitleaks |
| 4 | CI | Ask Muse for GitHub Actions running `make check` on PRs, with branch protection on `main` |
| 5 | Project skills | Create the 4 skills in §4. Check them with `muse skills validate <path>` and `muse skills list --source project` |
| 6 | Isolate from your personal setup | Run with `--no-foreign-personal-context` so your Claude/Codex rules, skills and homelab details stay out of the run and out of public traces. Before relying on it, confirm with `muse skills list --source all` |
| 7 | Board | GitHub Issues: one per SPEC §9 checkpoint item, with labels `C1 / C2 / C3`, `eval`, `ops`, `demo` |

Don't use `muse skills import --from claude` wholesale. Your homelab skills mean nothing to this repo, and importing them leaks infrastructure names into a public project.

---

## 3. `AGENTS.md` (draft with Wonder, keep under ~120 lines)

Sections:
- **Mission:** a two-line summary of the SPEC, plus a link to `SPEC.md`.
- **Commands:** `make check`, `make test`, `make eval`, `make demo`.
- **Layout:** `framework/`, `blocks/`, `evals/`, `personas/`, `fixtures/`, `ops/`, `docs/plans/`, `docs/sessions/`.
- **Hard rules:**
  - Typed manifests only (Pydantic).
  - A new block requires a schema, renderer, unit test and an L0 eval sample.
  - No network in tests.
  - No secrets in code or logs; keys come from the environment at runtime.
  - Every new file belongs to a ticket.
- **Definition of Done:** §6, copied in.
- **Don'ts:**
  - Don't edit `evals/hidden/`.
  - Don't change the mutant fixtures to make the gate pass.
  - Don't widen permissions.

The hidden-criteria rule needs enforcing, not just stating. Add a CI check that fails any PR touching `evals/hidden/` without the `eval-owner` label, which only Carlos applies.

---

## 4. Project skills (repeatable procedures, written once)

| Skill | What it does |
|---|---|
| `ticket-plan` | Reads the issue and SPEC sections. Writes `docs/plans/NNN-slug.md` with goal, acceptance tests, files touched, risks and test plan. Stops for approval. |
| `new-block` | Scaffolds a block: Pydantic schema, renderer, unit test, L0 Inspect sample and registry entry. Runs `make check`. |
| `eval-task` | Adds or edits an Inspect task under `evals/`. Runs it on the fixtures and attaches the log path. The meta-eval mutants must still be caught. |
| `ship` | Runs `make check`, writes a conventional commit, exports the redacted session to `docs/sessions/`, opens the PR from the template |

The product's C3 path calls `new-block` headless. That makes this skill both a developer tool and a runtime component.

---

## 5. Lifecycle of one ticket

```
Issue ──► PLAN ──► (Carlos approves; Claude reviews plan) ──► IMPLEMENT in worktree
      ──► VERIFY (make check + evals) ──► REVIEW (fresh session + Claude) ──► FIX
      ──► SHIP (PR, CI green, squash-merge, session export)
```

| Phase | Model / mode | Command shape | Output |
|---|---|---|---|
| **Plan** | Wonder, effort `high` | `muse --model muse-wonder-1.0 --effort high -w create` → "use ticket-plan for #12" | `docs/plans/012-*.md` |
| **Approve** | You (+ Claude) | Paste the plan to me if it's non-trivial; I return a short go/no-go and risks | Edited plan |
| **Implement** | Spark 1.3, effort `medium`. Use Wonder if the plan is marked hard | Same worktree, interactive, `--approval-mode on-request` | Code + tests, tests written first |
| **Verify** | Spark | "run make check and make eval; fix until green; don't touch tests to pass" | Green checks |
| **Review** | **New** Wonder session, read-only | `muse exec --model muse-wonder-1.0 --output-schema review.schema.json "review the diff vs main against docs/plans/012"` | JSON findings |
| **Second opinion** | Claude | You paste `git diff main...` or the PR link | Ranked findings |
| **Fix** | Spark | Address findings, re-verify | |
| **Ship** | Spark + `ship` skill | `gh pr create`, CI, squash-merge | PR + evidence note `docs/sessions/012-slug.md` (models, efforts, wall time, tokens, plan/review rounds, AT results); the raw `muse export --redacted` is kept privately and published only if gitleaks plus a manual check of names and context is clean. Two sessions per ticket: plan (muse-wonder-1.0, high) and implementation (muse-spark-1.3, medium); the approved plan file is the handoff. |

Model split: check per-model defaults with `muse model-profile show muse-spark-1.3 --effort medium` (**verify**). Measure cost and rework per ticket for 2 days, then adjust.

**Review output schema** (`--output-schema`, Meta provider):

```json
{"findings":[{"severity":"blocker|major|minor","file":"…","line":0,"claim":"…","evidence":"…"}],
 "plan_coverage":[{"acceptance_test":"…","met":true}]}
```

Structured findings let you count blockers per ticket. That number is good material for the write-up.

---

## 6. Definition of Done

- [ ] The acceptance tests from the plan exist, and they fail on `main` and pass on the branch.
- [ ] `make check` is green: ruff, pyright strict on `framework/`, pytest, gitleaks.
- [ ] If an eval or block changed: the Inspect log is attached, and all 7 mutants are still caught.
- [ ] The review has no open blockers. Majors are fixed or recorded as issues.
- [ ] The evidence note `docs/sessions/NNN-slug.md` (models, efforts, wall time, tokens, plan/review rounds, AT results, plus the `muse --version` output) is in `docs/sessions/`, and the PR links the plan and the note; the raw `muse export --redacted` is kept privately and published only if gitleaks plus a manual check of names and context is clean. Two sessions per ticket: plan (muse-wonder-1.0, high) and implementation (muse-spark-1.3, medium); the approved plan file is the handoff.
- [ ] `CONTRIBUTIONS.md` is updated with what was built, when, with which Muse models, and the advisory role.

---

## 7. Headless Muse Code (the loop's C3 path and night jobs)

Fixed flags, in a wrapper script under `ops/`:

```
muse exec --api-key-stdin --model muse-wonder-1.0 --reasoning-effort medium \
  -w create --workspace <repo> --approval-mode never --permission-profile c3-block \
  --max-model-steps 60 --max-tool-output-bytes 20000 --disable-web-tools \
  --no-foreign-personal-context --output-schema c3-result.schema.json --json \
  --prompt-file specs/<id>.md
```

- **Never use `--yolo`.** Safety comes from the worktree, the restricted permission profile (**verify** how profiles are defined) and the eval gate. A broken candidate is discarded, not repaired by hand.
- **Feed the key with `op run … -- sh -c 'printf %s "$META_API_KEY" | muse exec --api-key-stdin …'`,** as tested on 2026-10-27.
- **Save the JSONL event stream next to the cycle record.** `muse trace inspect` reads it back when a cycle fails.

---

## 8. Daily rhythm (operator window 13:00–23:30)

| Time | What |
|---|---|
| 13:00–13:30 | Read the 12:30 digest and the night's cycles, then triage. Pick at most 3 tickets for the day. |
| 13:30–14:00 | Plan tickets with Wonder. Send me the non-trivial plans. |
| 14:00–18:30 | Implement and verify, one worktree per ticket, max 2 in parallel |
| 18:30–19:00 | Review round: fresh Wonder session, then me |
| 19:00–21:30 | Fixes and shipping. Daily ratings for both apps (2 min). |
| 21:30–22:30 | Integration on `main`, then a full `make eval` and a dry run on the personas |
| 22:30–23:15 | Arm the night cycle, check alerts reach ntfy, write tomorrow's 3 tickets |
| 23:15–23:30 | Buffer. Nothing new starts after 23:00. |

---

## 9. My role (Claude, advisor)

**I do:**
- Review plans, diffs and eval logs.
- Act as the second reviewer on anything that touches the gate, the hidden criteria or the autonomy levels.
- Check facts and run read-only checks on the homelab.
- Give daily go/no-go calls on scope cuts.

**I don't:**
- Write code into the repo or commit.
- Write the README or the video script. Wonder drafts those and you edit; I can review.

**Decided 2026-10-27:** `CONTRIBUTIONS.md` discloses the advisory role (wording below), and the daily rhythm in §8 is adopted.

```markdown
## AI assistance outside the Muse family

- **Claude Code (Anthropic)** was used as an advisor and reviewer. It co-drafted the
  planning documents (SPEC.md, the pitch, this workflow), reviewed plans and diffs,
  and ran feasibility checks on Oct 27 outside this repo (one call each to Muse Glimmer,
  Muse Wonder and Muse Code, plus an Inspect AI hello-world).
- It wrote no code in this repository and made no commits. All code here was produced
  by Carlos with Muse Code, as recorded in `docs/sessions/`.
```

---

## 10. What we measure about the process (for judges and the write-up)

| Metric | Source |
|---|---|
| Tickets shipped / reopened | GitHub |
| Review blockers per ticket (Muse reviewer vs Claude) | review JSON, PR comments |
| Tokens and wall time per phase | session exports |
| % of code produced via Muse Code | git blame × session exports |
| C3 attempts → passed gate → shipped | loop DB |
