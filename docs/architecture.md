# Architecture

I drew the parts here so I can find them when I need them.

## Components

```mermaid
flowchart TD
    cycle["the cycle:<br/>one card per slot"]
    collectors["collectors: screen time,<br/>calendars, GitHub"]
    glimmer["glimmer: facts from<br/>counted signals, on my GB10"]
    proposal["proposal:<br/>Muse Wonder's options"]
    briefing["briefing: the gate"]
    telegram["telegram:<br/>the card and my taps"]
    voice["voice: a note becomes<br/>one typed edit"]
    learner["learner: what I pick"]
    metrics["metrics:<br/>the run in numbers"]
    store["store: rows,<br/>facts and attempts"]
    provenance["provenance: the public<br/>per-slot log"]
    verify["verify: the checker's core"]
    checker["the checker page,<br/>in the browser"]
    audit["source_audit: the<br/>independent recount"]
    cycle --> collectors
    cycle --> glimmer
    cycle --> proposal
    cycle --> briefing
    cycle --> telegram
    cycle --> voice
    cycle --> learner
    glimmer --> collectors
    proposal --> briefing
    voice --> proposal
    verify --> briefing
    checker --> verify
    metrics --> store
    provenance --> cycle
```

Arrows show the main imports between packages; schemas, which every package uses, and small helper imports are left out. source_audit imports nothing from framework/, so the GitHub recount shares no code with what it checks.

## The pieces

This is the design in more detail, and Status says what exists.

1. Two goals compete for the same hour: Builder and Disconnect (family time, screens off).
2. Collectors store my own signals on my own machine.
3. Muse Glimmer, an open-weight model on my own hardware, turns them into facts that cite their events.
4. Muse Wonder, through Muse Code headless on my subscription, sees only those facts and my commitments, and proposes one commitment per goal for the next free slot.
5. A deterministic gate with no model and no network rejects whatever it can't reconcile.
6. A Telegram card offers both proposals and I choose with a tap.
7. A voice note corrects the system and the next card changes. Its audio goes through Muse Code on my subscription for transcription, and nothing on the voice path calls the API directly; raw screen, calendar and GitHub rows stay on my machine.

## Code off the card path

Apple Health ingest, the Spotify collector and framework/blocks/ were built earlier in the hackathon. The current design doesn't use them.

