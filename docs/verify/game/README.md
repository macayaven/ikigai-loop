# Catch the AI: the rounds

A design review on Nov 3 asked for funnier, more relatable cards and suggested an everyday-clutter theme: the small piles of tabs, files, cables and messages most people know well. I wrote every final title, row and sentence in [rounds.json](rounds.json) on that theme.

Muse Wonder, a Meta model, wrote the rounds in a headless Muse Code session that Claude Code started from a prose prompt. The mistakes in some sentences were asked for in that prompt. They were not accidents.

Round 4 is the one the checker cannot catch. Its card is for this season, and its sentence puts the same number last season. The plain checker compares numbers and row names only. It does not check time windows, so it passes a sentence that is still wrong.

Tests pin the checker verdict for each round: rounds 1, 3 and 4 pass, and rounds 2, 5 and 6 fail.
