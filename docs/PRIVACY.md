# Privacy

This bot serves one person, me. I send myself one card over Telegram, so the card text and the chart go to Telegram when a card goes out.

When I tap Why?, the cited statements and reason codes go to Telegram as the reply.

My taps and voice notes pass through Telegram because I send them there. Telegram handles what passes through it under its own privacy policy.

The event store, the card ledger and the bot token stay on my machine.

Only my own messages are handled; anything else is counted and ignored.

## Calendar titles

Local labels are off by default. The switch is `IKIGAI_LABEL_CALENDAR_TITLES=1`, exact value.

When off, I read each title only to find a literal tag and then drop it. No title is stored, logged or sent anywhere, and no model is called.

When on, one title at a time goes to one open-weight model on hardware I own, over loopback or my private network, and never to Meta's API.

What comes back is one of the eight words. A label is a guess, and I never check guesses against real titles.

Titles live in process memory during a sweep. No code in this repo writes one down: not in the event store, a cursor, a log, or a prompt or response file.

Two limits I state plainly. The shape check does not prove the network is mine. A literal tag in a title counts as a hand tag.
## What goes to Meta to draft a card
To draft a card, one prompt per goal goes to Meta through headless Muse Code on my subscription, with Contributor mode off. From what I read in `build_prompt` in `framework/proposal/prompt.py`, the prompt carries the fact statements, the metric values with their label words and periods, the deltas against the last delivered card, my commitment titles with their kind and dimension, and the policy block. Raw rows never go: no window titles, no commit messages, no calendar titles. The local model reads the filtered rows on my own machine. When a Muse Code run dies locally before any model request, its stderr is kept, masked, in the same database on my own machine, and nothing else keeps stderr.

A review on Nov 1 sent two invented titles through the model server I use (llama-swap v249) and looked. By default it holds recent request and response bodies in memory until they age out or the service restarts, and they can be read through its API with its key. Its journal, its log endpoint and a search of recently changed files under my home, temp and log directories held no copy. So `captureBuffer: 0` goes in that server's config before I switch this on.
