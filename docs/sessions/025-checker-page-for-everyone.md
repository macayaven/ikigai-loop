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

## Catch the AI game (follow-up, same branch, 2026-11-03)

The six rounds in `docs/verify/game/rounds.json` were written by Muse
Wonder in its own sessions from Claude Code's prose prompts, with the
mistakes asked for, and a design review by three outside models shaped
the everyday-clutter theme. This session built the game around those
rounds and never edited them, their README, or anything under
`framework/`, `docs/verify/bundle.json` or `docs/verify/examples/`.

Through the plain pipeline (`build_checker_input` and `check_claims`),
rounds 1 and 3 pass with no violations, round 2 fails with
`L1B_METRIC_VALUE_MISMATCH` only, round 4 (the blind spot) passes, round
5 fails with `L1B_NEGATED_CLAIM` only, and round 6 fails with
`L1B_METRIC_VALUE_MISMATCH` only. The checker agrees with the answer on
five of the six, so M is 5. New tests in `tests/test_verify_game.py` pin
all of this, the disclosure word for word, and every game string the
ticket names (tagline, question, advantage line, reveal lines, score
lines, copy text, send-link line, sound toggle, `ANSWERS_FORM_URL`
empty).

The game sits right under the heading with no start screen, ahead of a
new "Try your own" heading above the unchanged form and sections. Each
round shows dots, "Round N of 6", a running "You P · Checker C" score,
the card as a small table, the sentence in quotes, the question, and the
Right/Wrong buttons. The reveal keeps the ticket's order, highlights the
named row and its number in the pass or catch colour, runs the checker's
verdict live through the page's own Python, and moves focus to Next
round. A tap before the checker loads shows the player's part with
"Waiting for the checker..." and fills the badge in when `boot()`
finishes. Sound is Web Audio only (click, chime, miss tone, ding,
fanfare at 5 or 6, gain 0.08), context on first tap, toggle at the top
right, no storage. Motion is a 0.32 s reveal, 24-square confetti under a
second, and a score fade, all off under reduced motion.

Size note: the browser-game skill sized this as a Standard build inside
the existing page (inline markup, no new fetched files beyond
`game/rounds.json`, no images per the brief), so no art director ran and
no critic round ran. Verification instead: `node --check` on the page's
inline script, plus a headless Node playthrough against the shipped
bytes with a small DOM stub (`/tmp/game-harness.mjs`, kept out of the
repo). It plays all six rounds, the late-checker path with badge
fill-in, the 5/6 tie final with blind-spot credit, the exact copy text,
the no-send-link default, replay reset, and the sound toggle, and it
prints GAME PLAYTHROUGH OK. No browser exists on this machine
(`command -v chromium` is empty), so widths, themes, motion and the live
Pyodide path are covered by static pins only, not a real browser.

Acceptance results for the game: the three verify files pass together
(`tests/test_verify_game.py`, `tests/test_verify_page.py`,
`tests/test_verify_page_plain.py`), `ruff check` and `ruff format`
clean on the new test file, `pyright` 0 errors on it. The full suite
gives 4648 passed with 36 failures, all in
`tests/test_proposal_local_retry.py`, `tests/test_ingest.py` (live
loopback) and `tests/test_cycle_orchestrator.py`; every one of them
fails identically on the untouched base tree (checked via stash), so
they are pre-existing and environmental, not from this change.
`make check` itself could not run
here: neither `uv` nor `gitleaks` is on PATH, so the venv's pytest, ruff
and pyright ran directly. I never opened anything under `evals/heldout/`
at all, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## Second review pass: first screen, quick checker lines, share (2026-11-03, headless)

Claude Code played the game in a real browser at 390 px, and an outside
playtester sent notes. This pass answers both. The page now opens on
"Catch the AI", with the old heading as a small line under it, then the
six-sentence line, the Muse Wonder credit with its "How this works" link,
and the game at once. The checker status lives inside the game next to
the sound toggle. The card is tighter and both buttons sit side by side
from 340 px up, so the sentence and both buttons show without scrolling
at 390 by 844. "Make your own round" stays hidden until the score card
shows, with a skip link at the top of the game that reveals it. Taps dim
both buttons and mark the chosen one, highlights follow the card, and
the trick round underlines its season words. The reveal speaks in short
lines built from the checker's own numbers. The score card leads with
"You: N/6 · Checker: M/6" and shares through the Web Share API with a
copy fallback. The verdict logic, the bundle, the examples, the rounds
and everything under `framework/` are untouched, and every verdict pin
stays.

## The brief Muse Wonder got for the rounds

You are running headless. Nobody can answer questions during this session, so do not ask any: decide, and write down every assumption you make in your final reply.

You are rewriting the content for a small game on the public checker page, docs/verify/. An earlier session of yours wrote docs/verify/game/rounds.json and README.md; a design review found the cards correct but flat. Rewrite both files in your own words and nothing else, then commit them. Don't change any other file.

## The game: Catch the AI

A visitor who has never heard of this project sees a card with a few everyday numbers, then a sentence an AI wrote about that card. They tap Right or Wrong. Then the page reveals the right answer, and separately what the page's checker saw. Six rounds, then a score. Some sentences are right, some are wrong on purpose, and the page says so: "Muse Wonder, a Meta model, wrote these sentences from each card. We asked it to slip mistakes into some." You are that model: you write the sentences.

Read docs/verify/verify_page.py and the "What this does not check" list in docs/verify/index.html first, so you know exactly what the page's plain checker does: every word of a row's name must appear in the sentence (any letter case); the number in the sentence must equal that row's number; a sentence with a negation word fails; a quantity word instead of digits fails; it does not check time periods, units, or words like rose and fell.

## The six rounds, in this order

1. A right sentence. The checker passes it.
2. A wrong number: one number in the sentence differs from the card. The checker catches it.
3. A right sentence on a different card. The checker passes it.
4. The right number from the wrong time window. The card's title names its period (for example "This season") and its row name has no period word, so the checker matches the number and passes it, but the sentence puts it in another period (for example "last season"). This is the round the checker can't catch, and the page says so in advance. It's the same kind of mistake a real assistant made on 2 November: the right number, from the wrong window.
5. A sentence that uses "not" against the card (for example the card says 12 croissants and the sentence says it did not sell 12). The answer is wrong, and the checker catches the "not".
6. A wrong number again, on a different card, with the wrong number close to the right one so it's easy to miss.

Theme, new: a "tiny chaos audit" of everyday clutter almost everyone recognises and smiles at: browser tabs, screenshots, mystery cables, unfinished hobby projects, untitled files, recording retakes, odd socks, a busy group chat. Each card gets a short, playful title (for example the feeling of "I'll close these tabs eventually"), with plain row names. Write your own titles, rows and sentences; don't reuse these examples word for word. Never health, fitness, food intake, money, prices, salaries, politics, religion, real people, real companies or real places. Each card has two or three rows; each row is a short name and a whole number; row names are plain words that appear in the sentence exactly as written on the card. For round 4, the card's title names the period, for example "... this season", and the sentence says "last season".

## File 1: docs/verify/game/rounds.json

UTF-8 JSON, two-space indent, this shape and nothing more:
- "version": 1
- "written_by": "muse-wonder-1.0"
- "disclosure": "Muse Wonder, a Meta model, wrote these sentences from each card. We asked it to slip mistakes into some. Six fixed, made-up examples, not an accuracy test."
- "rounds": a list of six objects, each with:
  - "id": "r1" to "r6"
  - "title": the card's title, a few words, including the period where the round needs one
  - "rows": a list of objects with "name" (string) and "value" (whole number)
  - "sentence": the AI's sentence, under 15 words, one sentence, one number from the card or the slipped one
  - "answer": "right" or "wrong"
  - "why": one plain sentence under 20 words a non-engineer understands, saying why the answer is what it is, with the numbers (for example "The card says 12 croissants; the sentence says 15.")
  - "checker_sees_it": true when the checker's verdict agrees with the answer, false for round 4
  - "checker_note": only for round 4 and round 5, one plain sentence: round 4 says the checker only compares numbers here and can't see time windows; round 5 says the checker catches the "not" because it can't prove a "did not" sentence from the card

## File 2: docs/verify/game/README.md

Short and plain: say that a design review on Nov 3 asked for funnier, more relatable cards and suggested the everyday-clutter theme, and that you wrote every final title, row and sentence; say who wrote the rounds (Muse Wonder, in a headless Muse Code session that Claude Code started from a prose prompt), that the mistakes were asked for, which round the checker can't catch and why, and that tests pin the checker's verdict for each round.

## Checks before you commit

- For every round, run its sentence and rows through the page's plain pipeline exactly as the page does (read how index.html and verify_page.py build the checker input from the plain form; use build_checker_input and check_claims from docs/verify/verify_page.py, with the repository's Python), and report each round's checker result and codes. Rounds 1 and 3 must pass; rounds 2, 5 and 6 must fail; round 4 must pass. If any round doesn't behave this way, rewrite that round until it does, and say so.
- Every sentence and "why" is under the word limits above; no em dashes; none of the words leverage, delve, robust, seamless, thrilled, excited, game-changer, revolutionary, magic.

Then, with this prefix on every uv and git command, from the repository root: PRE_COMMIT_HOME="$PWD/.git/pre-commit-home" UV_CACHE_DIR="$PWD/.git/uv-cache", stage only those two files and make one commit with the message "Ticket 25: the game's rounds, rewritten by Muse Wonder on an everyday-clutter theme", with no trailers of any kind. Don't push, fetch, rebase, merge or reset. Do not open anything under evals/heldout/ except evals/heldout/README.md, and never read the directory HIDDEN_CRITERIA_DIR points to.

Reply with: the six rounds as written (title, rows, sentence, answer); each round's checker result and codes; the commit hash; and every assumption you made.

## Plain-words pass (2026-11-03, after the owner's playtest)

After the owner played "Catch the AI" on his phone, he asked for plainer words. Copy only: eight strings in `docs/verify/index.html` and one sentence in `README.md`, plus the test pins that hold them. The verdict logic, `docs/verify/bundle.json`, `docs/verify/examples/`, `docs/verify/game/` and everything under `framework/` are untouched, and every verdict pin stays.

Page strings, old to new:

1. Subhead: `Does your AI get your numbers right?` to `"Strawberry" has three r's. AI once said two.` The first version wrapped to two lines at 390 px, so the line was shortened to keep the first decision above the fold.
2. Tagline: `Six sentences an AI wrote. Some hide a fib. Can you beat the checker?` to `Six sentences an AI wrote. Some hide a trap. Can you beat the checker?`
3. Credit line: `Muse Wonder, Meta's AI, wrote these sentences, and we asked it to hide some fibs.` to `Muse Wonder, Meta's AI, wrote these sentences, and we asked it to set traps in some.`
4. Privacy line: `It runs on your device; nothing you type leaves it.` to `It runs in your browser; nothing you type leaves your device.`
5. "Make your own round" sub: `The checker tells you if it's a fib.` to `The checker tells you if the sentence gets your numbers wrong.`
6. Plain verdict head: `Caught a fib.` to `Caught a mistake.`
7. Game reveal: `It's a fib.` to `It's a trap.`
8. Score line: `You caught every fib.` to `You caught every trap.`

README first screen: `Muse Wonder wrote six sentences and hid a fib in some.` to `Muse Wonder wrote six sentences and set traps in some.` Nothing else in `README.md` changed.

Why: "fib" is a word many readers outside the UK and US do not know; "trap" fits the game because the mistakes were planted on purpose, while a real AI's wrong number in "Make your own round" is a mistake, not a trap; the strawberry line recalls a well-known 2024 counting slip by chat assistants; the page runs in the browser, and nothing typed leaves the device.

Pins updated in `tests/test_verify_page.py` (subhead, tagline, privacy line, "Make your own round" sub) and `tests/test_verify_game.py` (tagline, credit line, subhead assertion, game reveal, score line); no check was weakened in any other way.

Implementation: Muse Code, powered by Meta Muse Spark, headless, in one session. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.

## The study version (2026-11-03)

I added a consented study version of the game behind `?src=prolific`, leaving the ordinary game flow untouched: same reveals, live score, sounds and layout, and the old answers hook still empty and dormant. Only the surrounding copy changed, per the first-person fixes below. With the study query present, the page hides the game and the make-your-own form, then walks through consent (unchecked box, Start disabled until checked), the instructions with the played-before question, a one-question instruction check, the six cards in one random cyclic rotation with no reveal, stamp, right-or-wrong sound or live score between cards (only the neutral tap), a submit screen that opens a pre-filled Google Form in a new tab, and finally the debrief with the full reveal. The payload carries no raw Prolific ID, only the first 12 hex characters of its salted SHA-256.

I made the two first-person copy fixes the ticket asked for: the byline now reads "and I asked it to set traps in some", the rounds file disclosure reads "I asked it to slip mistakes into some", and How this works records that disclosure-line change and notes the paid study version. I registered the plan in `docs/prereg-game.md` and the notice in `docs/study-privacy.md` before any answer exists, and I extended `tests/test_verify_game.py` to pin the new strings, the payload shape, the rotation, the no-send rule and the unchanged ordinary game.

Implementation: Muse Code, powered by Meta Muse Spark, headless, in one session. I never opened anything under `evals/heldout/`, and I never read the path in `HIDDEN_CRITERIA_DIR`.
