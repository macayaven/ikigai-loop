# Session evidence - 010d-squashed-private-terms (2026-11-03)

## What broke

Tonight's rehearsal of the Nov 3 11:30 slot, on a scratch copy with the real deny list, fell back with FALLBACK_AFTER_GATE_FAILURE. On the rehearsal commit, 5 of 5 runs for the 11:30 data fell back, and all 10 attempts were stopped with `L1_PRIVATE_TERM` at two claims, overall_state claim 2 and not_working claim 1. Every draft for 13:30, 15:30, 18:00 and 20:30 passed at the first attempt. Ticket 10b's squashed and fuzzy private-term arms could match a term across ordinary word boundaries or as a near miss of a card word. No live card had used Ticket 10b's gate, so its first live use is the fixed one. The false stop failed closed: the slot sends a deterministic fallback card.

## The rule

I point to the plan for the decisions behind this: [docs/plans/010d-squashed-private-terms.md](../plans/010d-squashed-private-terms.md). A squashed or fuzzy match does not count when every token it consumes is card vocabulary; an exact whole-term match still fires; it covers every fuzzy arm. It only narrows: with an empty vocabulary every arm returns its earlier verdict, the vocabulary can only discard a match, and a corpus test checks that no private-term sentence in the repository gains a hit. No held-out row carries `L1_PRIVATE_TERM`, so a strictly narrowing fix leaves both held-out scores as they were.

## Made-up reproduction

The two 11:30-shaped comparison sentences, written with made-up numbers 0.5 and 3.25, as overall_state claim 2 with their code refs through the full gate:

- "Code was lower in the last period, 0.5 hours, than in the prior period, 3.25 hours."
- "Code was 0.5 hours in the last period and lower than 3.25 hours in the prior period."

Against 7 made-up terms that appear only by joining whole words ("Lowerin", "Thanin", "Inthelast", "Codewas", "Andlower", "Lowerthan", "Thelastperiod"). Before, on f099788, every one of them stopped at least one sentence, and 5 of the 7 stopped each sentence. After, all 7 pass on both. Still stopped before and after: "Zebra Finch", "Zebra; finch", "Zebra, finch", "Zebra-finch", "Q u i l l o n", "Q.u.i.l.l.o.n", "Q-u-i-l-l-o-n", "quetzal: garden" and "q u e t z a l - g a r d e n".

## Checks

The red-team runner's summary is byte-identical before and after. The pre-commit hooks pass on the changed files. Identities from evals/gate_identity.py at f7f8db4: gate commit f7f8db48af2e92f45332da5d667f11340979720d and gate hash 0b84319e4bd9bf4df29b19854e14634b69f21eafb5ccf99121e83b23afae67f6, prompt b42e301f613ad5dc79f77bb0c3bf7b5b1697419b1326d889e9c1ff48a3b0deec, unchanged, and closure 6e4f699a1b3d1adda530f08989a9f94508d40b4e2ee12ac5710089ea309b9648 over 47 files. `make check` on f7f8db4, memory-capped and outside the sandbox: 4635 passed, 1 skipped, ruff, format and pyright clean, gitleaks no leaks; the pull request's CI check passed.

## Open limits

The plan's limits stand. The open one, in one sentence: callers that pass no label words, which are the outbound scans of the prompt sent to Muse, of voice and of the rater pack, still flag a match that consumes a label word, while joins of the static vocabulary are exempt everywhere.

## Who wrote what

Muse Code wrote the plan, the code, the tests, the PREREG entry and these docs in headless sessions Claude Code started. Claude Code wrote the prompts in prose, reproduced the false stop with made-up terms, ran the checks, pushed the branch and opened the pull request. Nobody read the deny list, and nobody opened evals/heldout/.
