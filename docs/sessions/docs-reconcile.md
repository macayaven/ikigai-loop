# Session evidence — docs-reconcile (2026-11-01)

Docs and comments only; no behaviour, schema, fixture or test change.
Three headless implementation sessions: the rewrite, the review fixes, and
the commit. This note summarises the work; the raw session exports are kept
privately.

`muse --version` (implementation session, first line, verbatim):

```
Muse Code 1.4.14 (1.4.14-R7309.1)
```

## What changed and why

The README still pitched two diverging apps and the second profile read
as a health advisor. Neither is the entry any more, so the docs now say
what the entry is and what does and doesn't exist, with no claim ahead
of the code:

- `README.md` rewritten (first person, about 60 lines): the entry pitch,
  "How it works" as a numbered list, "Status" with built/not-built lists
  (each built item with its path and test counts verified by running the
  tests), the no-medical-advice line, the hackathon record, the
  off-the-card-path list, the Venn diagram note, and links.
- `profiles/recovery.md` moved to `profiles/disconnect.md` and rewritten
  (family time, screens off); everything else in the old file goes.
- `profiles/builder.md` trimmed to the card path: the Apple Health, job
  tracker and check-in signal rows go, the calendar row and limit now say
  busy intervals and `iki-*` tags with titles dropped, and the Low energy
  and Pace rows and criteria go with renumbering.
- Superseded notes in `docs/SPEC.md`, `docs/PLAN.md`,
  `docs/MUSEUM-CONTRACT.md`, and a build-process note in
  `docs/WORKFLOW.md`. History in `docs/plans/` and `docs/sessions/`
  untouched.
- Card-path comments in three framework docstrings only
  (`framework/blocks/__init__.py`, `framework/collectors/spotify.py`,
  `framework/collectors/ingest.py`).
- `AGENTS.md`: only the Mission paragraph changed. It now matches the README
  and points at it; the Commands section and every rule are unchanged.

Prompts and review by Claude Code. Implementation: muse-spark-1.3 (effort
medium), in Muse Code, in headless sessions Claude Code started.

Every `uv`, `pre-commit`, and `git` command in this session ran under
`PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
`UV_CACHE_DIR="$PWD/.git/uv-cache"`.

## Review

Claude Code reviewed the result before the commit: each README claim against
the code or a test run, and the pinned sentences byte for byte against the
prompt. What the review changed:

- `README.md`: a line under "How it works" says the list is the design and
  Status says what exists; the two voice-note sentences are one step; the
  store bullet names the update trigger and the one delete path; the
  collector count is split into 41 suite tests and 15 CLI tests.
- `AGENTS.md`: the Mission paragraph, added to this ticket by the review.
- `docs/WORKFLOW.md`: the note also says that who runs each step changed on
  Nov 1.

`make check`, run by Claude Code outside Muse's sandbox on the reviewed tree,
exits 0 with 322 tests passing, the same count as `main` at 139cc37. Inside
Muse's sandbox `tests/test_ingest.py::test_live_loopback_server_health_round_trip`
fails because the sandbox denies the loopback bind.

Known gap: the prompt's word check over `profiles/*.md` still matches lines
in `profiles/TEMPLATE.md`, a fictional sample this ticket leaves alone.
`profiles/builder.md` and `profiles/disconnect.md` have no match.

## Follow-up

- Narrowed the `README.md` opening pitch to what the deterministic gate actually checks, because the old line claimed the agent can't tell me anything it can't prove and the gate doesn't check that a sentence is true.
- Reworded the `CONTRIBUTIONS.md` Claude Code bullet to say the branch commits are Muse Code's and the merge commits on main come from Claude Code's pushes and squash merges.
- Shortened the `profiles/disconnect.md` "After 21:00" limit to drop the lights-out clause.
- Fixed `profiles/TEMPLATE.md` line 6 to say profile B (Disconnect) instead of profile B (Recovery).
- Added `.gitattributes` with `CONTRIBUTIONS.md merge=union`, because every ticket appends an entry at the same place in that file and parallel branches then conflict.
