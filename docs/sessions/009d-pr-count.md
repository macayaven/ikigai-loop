# Session evidence — 009d-pr-count (2026-11-01)

Ticket 9d on branch `t9d-pr-count`, in one headless session Claude Code
started. No plan file exists for this ticket; the ticket text was the spec,
and with nobody able to approve a plan I implemented it directly.

## What my real store showed

A code fact said "Pull requests rose from 0 in prior to 16 in last."
The public repo had 8 pull requests in that window. Each one emits two
`github.pr` rows (opened, then merged), and the rule added 1 per row, so 8
pull requests read as 16.

## The fix

One helper, `is_opened_pr`, in `framework/glimmer/metrics.py`: a row counts
only when its `counts` holds `opened` above 0. All three sites use it, with
no schema, collector, stored-row, or `github.push` change:

- period rollup `rollup[name]["prs"]` (`metrics.py`),
- window value `github.pr.count` (`metrics.py`; a window with only
  non-opened rows keeps the key absent),
- the `prs` pool in `framework/glimmer/code_facts.py`, so evidence cites
  only opened rows.

Fixture: the `pr_event` helper in `evals/glimmer_cases.py` carried
`{"prs": 1}`, which is not an `opened` row, so I changed its default to
`{"opened": 1}` and added an optional `counts` knob for merged/closed test
rows. The live-run `LIVE_ROWS` PR row already carries `{"opened": 1}`, so it
stays as is. No expected snapshot, statement, cycle id, or prompt hash moved.

Other `github.pr` hits from `git grep framework/`, none of which counts pull
requests, all left alone: the labels in `framework/briefing/labels.py`, the
collector mapping in `framework/collectors/github_events.py`, the allowlist
in `framework/glimmer/facts.py`, the gate's match helpers in
`framework/glimmer/checks.py` (`_family_match`, `_cited_period_families`),
and the schema in `framework/schemas/events.py`.

## Tests

9 new, all on synthetic rows: 4 in `tests/test_glimmer_metrics.py`
(opened+merged counts 1; opened-prior/merged-last splits 1 and 0;
merged-only gives period 0 with no `github.pr.count` key; closed, reopened,
other actions, and `{"opened": 0}` count nothing), 5 in
`tests/test_glimmer_code_facts.py` (evidence holds only opened rows with the
stated numbers equal to the rows counted; merged-only and non-opened rows
yield no `prs` fact; the fact passes the briefing gate in both citation
forms). 8 of the 9 fail on the pre-fix rule; the gate test passes either way
and pins the fixed behavior.

`make check`: ruff, ruff format, and pyright clean; pytest 1234 passed with
the single predicted sandbox failure (`test_live_loopback_server_health_round_trip`,
loopback bind forbidden here); gitleaks clean; all glimmer and briefing
mutants still caught. README counts moved with the new tests: 270 to 279 in
the glimmer group, 52 to 57 in the code-facts file.

## What I did not change

Pushes come from GitHub's public event feed. Since Oct 29 every change in
this repo has been one push that creates a branch plus a squash merge, and
the feed shows those as pull request events with no PushEvent. The newest
PushEvent in the feed is 2026-10-29T21:09Z, while the repo activity API lists
8 branch creations and 8 pull request merges on Nov 1. So the push count
reads 0 in those periods. That is true of the feed and low against what I
did, so the card's chart will show pushes plus pull requests.

Every `uv`, `pre-commit`, and `git` command in this session ran under
`PRE_COMMIT_HOME="$PWD/.git/pre-commit-home"`
`UV_CACHE_DIR="$PWD/.git/uv-cache"`. Stopped before the commit, as briefed.
