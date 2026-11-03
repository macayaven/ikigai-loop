# Session evidence - 025-checker-page-for-everyone (2026-11-03)

## What changed

The checker page at `docs/verify/index.html` is now the one part of this
project a stranger can enjoy in 60 seconds on a phone. It runs a worked
example by itself on load, speaks in plain sentences instead of codes, puts
the plain-words form first, and moves the JSON box to the bottom. The
checker's verdict logic did not change. Nothing under `framework/` changed,
`docs/verify/bundle.json` was not rebuilt, every file under
`docs/verify/examples/` keeps its verdict and codes, and the command-line
checker, its README instructions and the held-out sets did not change.

On load the plain form holds the worked example ("Deploys reached 12 in
November." with "November deploys" = 7) and `boot()` runs it once, with no
tap, so the result card shows the catch: "Caught it." with "The sentence
says 12; your record says 7." and the code in small print. A row of three
one-tap examples (a wrong number, a matching sentence, a sneaky "not") fills
the form and runs. "Why I built this" carries the four paragraphs pinned in
the plan, ending in a link to TRUST.md on GitHub. The JSON pane sits last,
inside one collapsed "For engineers: JSON input" section.

I point to the plan for the decisions behind each of these:
[docs/plans/025-checker-page-for-everyone.md](../plans/025-checker-page-for-everyone.md).

## Rulings applied

Claude Code reviewed the plan, and the session prompt carried four rulings,
which I wrote into the plan first and then implemented:

- R1: the old D9 (create `docs/TRUST.md` here) is dropped. That file lives
  on the trust-page branch, which merges before this ticket. The page links
  to `https://github.com/macayaven/ikigai-loop/blob/main/docs/TRUST.md` as
  planned. Tests pin the link's text and address; no test requires the file
  on this branch.
- R2: the three "Why I built this" paragraphs became the four pinned
  paragraphs, word for word, with the link on the final "TRUST.md".
- R3: the third example's label is `A sneaky "not"`, not "Sneaky negation".
  Its sentence, record and verdict are as the plan pins them.
- R4: the page's voice is mine, Carlos's, plain and warm, first person where
  the page speaks as me. The rest of the copy stays as the plan pins it.

## The helper

`docs/verify/verify_page.py`, presentation only, per D3: the
`L1B_METRIC_VALUE_MISMATCH` sentence is now "The sentence says {cited};
your record says {record}." (the worked example gives exactly "The sentence
says 12; your record says 7."); the overall lines are the pinned headlines
("Caught it.", "Caught it. {bad} of {total} checked sentences did not
pass.", and the two pass wordings ending "it checks numbers, sources and
wording, nothing else."); the fallback is "The checker flagged this
sentence." with no code in it. No change to `build_checker_input`, to which
checker functions are called, or to any code, flag or exit path.

## Re-pinned expectations (named before re-pinning, per the plan)

In `tests/test_verify_page_plain.py`: the worked-example finding (exact new
sentence, code still `L1B_METRIC_VALUE_MISMATCH`); the one- and
several-sentence overall lines; the one- and several-sentence catch
headlines. New: the three plain examples give exactly their pinned code
lists through `build_checker_input` and `check_claims` (fail with
`L1B_METRIC_VALUE_MISMATCH` only, pass with none, fail with
`L1B_NEGATED_CLAIM` only); the worked mismatch wording; the one/several
pass wording; the fallback sentence with no code in it.

In `tests/test_verify_page.py`: the h1, the one plain sentence, the privacy
line and the loading/ready/failed wordings; step labels; the pre-filled
form; disabled-until-ready buttons with auto-run on `boot()` success
(replacing the queue-a-click `pendingRun` pins); the removed made-up card,
`example-check` and `try-fill` pins; the `A sneaky "not"` label; the
invitation and honest-list heading ("What this does not check"); the Why
paragraphs and TRUST.md link; the JSON section moved last and collapsed
(replacing the "Check JSON directly (for developers)" summary pin); tap
targets and reduced motion; no em dashes; small-print codes; the extended
hype-word list (excited, game-changer, revolutionary, magic, coach,
wellness). Verdict, bundle, embedded-example and network pins pass unedited.

## Acceptance results

- AT1: `uv run pytest tests/test_verify_page_plain.py` — 48 passed.
- AT2: `uv run pytest tests/test_verify_page.py` — 52 passed, with only
  the named page-pin updates changed.
- AT3: `git diff --stat HEAD -- framework/ docs/verify/bundle.json
  docs/verify/examples/ examples/ README.md evals/` is empty, and
  `git status --porcelain docs/verify/bundle.json docs/verify/examples/`
  is empty.
- AT4: `uv run pytest tests/test_verify_page.py
  tests/test_verify_page_plain.py -k "example or verdict or code or wording
  or fallback"` — 25 passed.
- AT5: order, banned-word and em-dash pins pass as part of AT2's run.
- AT6: structure pins (pre-filled form, disabled markup, boot enables and
  auto-runs, JSON last and collapsed, live regions, 44 px targets,
  reduced-motion rule) pass as part of AT2's run.
- AT7: the TRUST.md link text and address are pinned; no test requires
  `docs/TRUST.md` on this branch.
- AT8/AT9: not run here — no headless browser exists in this session
  (no chromium, no playwright). The static pins cover order, labels,
  live regions, tap-target and reduced-motion CSS, but the live auto-run,
  widths, themes, motion and failure states are unverified from this
  session.
- AT10 (negative control): the new and updated tests run against the base
  page and helper failed as required (8 failed in the plain file, 22 in the
  page file — no pre-filled auto-run, no example row, no pinned sentences),
  while the unedited verdict pins passed.
- AT11: not run in this session. `make check` is left to Claude Code's
  follow-up under a memory cap, per the session prompt. `ruff check`,
  `ruff format` and `pyright` on the three changed Python files are clean
  (ruff reformatted two test files; pyright 0 errors).

## What review changed

There was no in-session review round: this session is headless and nobody
could answer questions. The four rulings above arrived with the session
prompt, from Claude Code's review of the plan, and I wrote each into the
plan before implementing.

## What isn't verified

The live page in a real browser (AT8, AT9); a real phone and a slow
connection; the full suite and `make check`; how the new wording reads to a
stranger beyond the pinned strings. The live page at the public address
runs main's page until this merges.

## Copy rule tension, decided and recorded

The plan requires every non-Why page sentence under 20 words, and also
requires the honest-list rules and the JSON technical paragraphs to keep
today's wording (D9: the JSON section is a move, not a rewrite; the honest
list keeps the plain rules the page carries today). Those carried-over
paragraphs have longer sentences (for example "Every word of a row's name
must appear in the sentence..." at 24 words, and the "What fails now"
paragraph). Rewriting them would break the move-not-rewrite rule and the
existing pins, so I kept them byte-identical and applied the 20-word rule
to every sentence I wrote or changed. All new copy passes it; banned words
(leverage, delve, robust, seamless, thrilled, excited, game-changer,
revolutionary, magic, coach, wellness) and em dashes are absent from page
copy and the helper.

I never opened anything under `evals/heldout/`, and I never read the path
in `HIDDEN_CRITERIA_DIR`. No test uses the network, a model, or either of
those paths. The public-repo sweep over every touched file found no real
names, real values, private terms, hosts beyond the pinned CDN and GitHub
links, private paths or tokens ("Prs rose by 3 in the last period" is the
ruling's pinned fictional sentence).

Implementation ran on Muse Code, powered by Meta Muse Spark, headless, in
one session (model version and effort are not surfaced in-session).
Plan: same session, written first per the session prompt. No model calls
beyond this session's own work.
