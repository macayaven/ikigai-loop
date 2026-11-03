# The live run in numbers

These numbers update at the numbers cut, Nov 4 at 18:30 Madrid. Until then they stand as of the time in the first line.

Ikigai Loop live run, numbers as of Nov 3 23:45 Madrid: 11 of 14 scheduled slots so far.

| Date | Slot | Delivered on time | First draft passed the gate | Retries | Fallback | Corrected card | Glimmer facts step ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Nov 2 | 13:30 | yes | yes | 0 | no | no | yes |
| Nov 2 | 15:30 | yes | yes | 0 | no | no | yes |
| Nov 2 | 18:00 | yes | yes | 0 | no | no | yes |
| Nov 2 | 20:30 | yes | yes | 0 | no | yes | yes |
| Nov 2 | 22:30 | yes | yes | 0 | no | yes | yes |
| Nov 3 | 11:30 | yes | yes | 0 | no | no | yes |
| Nov 3 | 13:30 | yes | yes | 0 | no | no | yes |
| Nov 3 | 15:30 | yes | yes | 0 | no | no | yes |
| Nov 3 | 18:00 | yes | yes | 0 | no | no | yes |
| Nov 3 | 20:30 | yes | yes | 0 | no | no | yes |
| Nov 3 | 22:30 | yes | no | 1 | no | yes | yes |

**Totals:** 11 scheduled cards, 11 delivered, 11 on time, 0 fallbacks, 3 voice-corrected cards; 20 first drafts, 1 stopped by the gate (Nov 3 22:30: L1B_CLAIM_WITHOUT_EVIDENCE, a repeat draft of an option); 1 retry. Settled recount against GitHub's own records: PRs 6 matched, 0 differed, 3 not settled yet, 2 incomplete (Nov 3 11:30, 15:30: CARD_NONE_FOUND, the card stated no PR figure); pushes 0 matched, 6 differed (GitHub's event feed adds push rows hours after the push; see TRUST.md), 3 not settled yet, 2 incomplete (Nov 2 13:30, 15:30: NO_INDEPENDENT_SOURCE, they agreed with GitHub's event feed, the only source for pushes).

How I counted: a slot counts once its five-minute send window has closed. On time means Telegram accepted the card within five minutes of the slot. The slowest was accepted 2 seconds after its slot. A first draft is a model's first attempt for one option; it is stopped when it didn't parse or the gate gave it any code, and retries count the attempts after the first, voice re-drafts included. The recount compares each card's figures with GitHub's own records, using code that shares nothing with the product, six hours after the card so late rows have arrived; pushes can never count as matched, because GitHub's event feed is their only source. A read-only script computed these from my private store, and the public provenance file (docs/provenance.jsonl) agrees on every slot it covers.
