# Contributions

## Ticket 1 — toolchain (2026-10-27)

Built on branch `t1-toolchain` per [docs/plans/001-toolchain.md](docs/plans/001-toolchain.md):
`uv` project on Python 3.12, package skeleton, `Makefile` (`check`/`test`/`eval`/`demo`),
hello Inspect eval on the mock model, pre-commit, `.env.example`, GitHub Actions CI,
this file, `LICENSE`, and `README.md`.

Plan: muse-wonder-1.0 (effort high). Implementation: muse-spark-1.3 (effort medium), in Muse Code.

## Ticket 2 — SPEC v0.4 (2026-10-29)

Built on branch `t2-spec-v04` per [docs/plans/002-spec-v04.md](docs/plans/002-spec-v04.md):
`docs/SPEC.md` moved to v0.4 (decisions D1–D10), new `docs/PLAN.md`, new
`docs/MUSEUM-CONTRACT.md` (verbatim except ruff formatting of its Python snippet), and the two objective profiles
(`profiles/builder.md`, `profiles/recovery.md`) committed unchanged.

Plan and implementation: muse-wonder-1.0 (effort high), in Muse Code.

## AI assistance outside the Muse family

- **Claude Code (Anthropic)** was used as an advisor and reviewer. It co-drafted the
  planning documents (SPEC.md, the pitch, docs/WORKFLOW.md) and helped structure the ikigai profiles from my interview answers; it reviewed plans and diffs,
  and ran feasibility checks on Oct 27 outside this repo (one call each to Muse Glimmer,
  Muse Wonder and Muse Code, plus an Inspect AI hello-world).
- It wrote no code in this repository and made no commits. All code here was produced
  by Carlos with Muse Code, as summarised in `docs/sessions/`.
