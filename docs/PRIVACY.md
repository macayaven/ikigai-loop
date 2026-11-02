# Privacy

This bot serves one person, me. I send myself one card over Telegram, so the card text and the chart go to Telegram when a card goes out.

When I tap Why?, the cited statements and reason codes go to Telegram as the reply.

My taps and voice notes pass through Telegram because I send them there. Telegram handles what passes through it under its own privacy policy.

The event store, the card ledger and the bot token stay on my machine. The published log in `docs/provenance.jsonl` holds counts and codes per slot and no card text, and the ledger itself stays on my machine. The audit export holds only closed codes, counts, instants, and public GitHub identifiers that pass a shape check, and it holds no statement, title, or value from my store.

Only my own messages are handled; anything else is counted and ignored.

When I send a voice note, its audio goes to Meta, through Muse Code on my subscription, for transcription. The clip cannot be scanned before it goes, because there is no text to scan; it is converted on my machine, sent for that one call, and the local files are deleted at once.

The transcript then goes to Meta, through Muse Code, to compile my correction into one typed operation, after a scan on my machine. What that call carries is the transcript, my commitment ids and titles, what the card offered, its cited statements, and the time — the same commitments and facts the card itself was drafted from.

What stays on my machine afterwards: the transcript in one local table, the operation it compiled to, the events it applied, and how long each step took. The audio does not stay.

A real voice note and its transcript stay out of Muse Code's Contributor mode, because its terms forbid personal information there. The compile and the corrected card force it off on every call: `MuseExecClient` passes `--contributor-mode off` and refuses contributor model ids. `muse voice transcribe` has no mode flag, so the poller refuses to transcribe unless `MUSE_CONTRIBUTOR_MODE` is exactly `0` and the saved setting `contributor_mode_enabled` is exactly `false`. If it can't confirm both, the note waits, I'm told, and the audio goes nowhere.

There is a limit I can't close from here. I watched the transcription request on loopback: it carries no mode marker under any setting, the same handshake and the same first-frame keys with the variable at `0`, at `1`, or unset. So these checks prove what my side says, not how Meta's service treats that call.

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
