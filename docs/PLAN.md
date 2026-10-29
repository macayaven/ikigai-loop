# Ikigai Loop: build plan (from BUILD-PLAN v0.4, 2026-10-28)

Working plan for Oct 28 → Nov 4. It sits on top of [docs/SPEC.md](SPEC.md) and
[docs/WORKFLOW.md](WORKFLOW.md). The museum demo follows
[docs/MUSEUM-CONTRACT.md](MUSEUM-CONTRACT.md).

---

## 0. Decisions since SPEC v0.3

| # | Decision | Why |
|---|---|---|
| D1 | Profile A becomes **Builder: make original, useful things that are mine**. It is not "win the hackathon". | That goal expires on Nov 4, steers the app toward working on its own repo, and reads as gaming to the judges |
| D2 | New shared signals: **Apple Health daily aggregates**, **ActivityWatch app categories (Mac)**, **public build feed** (HF daily papers, HN front page, GitHub new-and-rising repos) | Recovery needs body and mood data. Builder needs "what the world needs" |
| D3 | Email and iPhone Screen Time become **Won't (v2)** | Email: little extra signal for a high privacy cost. Screen Time: no supported API |
| D4 | GitHub signal **excludes the `ikigai-loop` repo** | Otherwise the Builder profile rewards the loop for its own commits |
| D5 | Collectors are deterministic and write to an append-only event log. Agents never call the sources live | Keeps the stream identical for both profiles and replayable for the evals |
| D6 | Two privacy tiers. **Raw events never leave the local machine. Wonder sees only facts.** Public outputs carry IDs, aggregates and scores | n=1 personal data, health included |
| D7 | **Collectors start before day 0** (by Oct 30 evening). The loop itself starts at day 0 | Day 0 begins with history in the knowledge base. Both profiles still see the same stream |
| D8 | **Day 0 is Oct 31 at 13:00 Europe/Madrid.** SPEC's own fallback date, with the fallback "Oct 31 evening or Nov 1 13:00 if T11–T13 are not done" stated in SPEC §9 | The schema/blocks/L0/L1 checkpoint is more than 3 tickets. That leaves 4 days of cycles, the minimum in SPEC §12 |
| D9 | The demo becomes a "museum": a 2D page and a WebXR room per profile, built from one `tour.json` and gated by the same eval. Go/no-go on XR at **Nov 2, 13:00 Europe/Madrid** | See [docs/MUSEUM-CONTRACT.md](MUSEUM-CONTRACT.md) |
| D10 | The schema has `subject_id` separate from `profile_id` from the start | Lets more subjects join later at no cost to the critical path |

The SPEC changes from D1–D10 are ticket **T2** (docs only).

## 2. Input map

### 2.1 Sources

| Source | Collector | Event types (examples) | Raw tier | Feeds | Effort | Ticket |
|---|---|---|---|---|---|---|
| Google Calendar | API, `calendar.readonly`, `syncToken`, poll 15 min | `calendar.event.{created,updated,cancelled}` with start, end, busy, category (title kept private) | private | A, B | low | T5 |
| GitHub (own activity) | `GET /users/{u}/events`, fine-grained read-only token or public scope; **exclude `ikigai-loop`** | `github.{push,pr,issue,release}` with repo, counts | public anyway | A | low | T5 |
| Public build feed | HF daily papers, HN top stories, GitHub search (new repos, stars, last 7 d); no auth | `feed.item` with title, url, source, score | public | A (B ignores it) | low | T5 |
| Spotify | Recently played, OAuth `user-read-recently-played` | `music.play` with track, artist, time | private | B, A | low | T7 |
| Apple Health | iOS Shortcuts automation, daily at 08:00: "Find Health Samples" → POST JSON to the ingest endpoint on the private network | `health.daily` with daily aggregates (sleep, resting HR, HRV, steps, mindful minutes, State of Mind) | **private, sensitive** | B | ~2 h, time-boxed | T7 |
| ActivityWatch (Mac) | Local REST API, hourly roll-up; **window titles dropped at the collector** | `screen.hour` with minutes per category (code, comms, browse, media, other) | private | A, B | ~1 h | T7 |
| App telemetry | Built into the app | `app.{view,tap,thumb,rating,approve,reject}` | private | per profile only | in T13 | T13 |

### 2.2 Event envelope (one for every source)

```jsonc
{
  "id": "evt_01J…",            // ULID, idempotency key = source + source_id
  "subject_id": "subject-1",   // whose life this is (D10)
  "source": "calendar",         // collector name
  "type": "calendar.event.created",
  "time": "2026-10-29T18:00:00+01:00",
  "source_id": "…",             // the upstream ID, for dedupe
  "data": { },                  // typed per type (Pydantic model per event type)
  "tier": "private",            // private | public
  "collected_at": "…",
  "collector_version": "calendar@0.1.0"
}
```

Rules:
- Upsert on `(source, source_id)`.
- One cursor row per collector.
- Each night, write a **hash of the day's batch** to a public log. This proves the stream existed and wasn't edited, without revealing it.
- Raw events expire 14 days after Nov 9.

### 2.3 Privacy line

| Stays on the local machine | May go to the Meta API (Wonder) | May be public (repo, video, museum) |
|---|---|---|
| raw events, calendar titles, track names, health values, screen minutes | Glimmer facts (abstract daily aggregates), manifests, criteria | manifests, changelogs with evidence IDs, eval scores, κ, divergence, attribution, daily batch hashes, synthetic fixtures |

Health values never appear in a public chart. In the video, Recovery's evidence is shown as fact IDs plus a pass/fail, never as a number.

## 3. Tickets

Up to 3 a day, in the 13:00–23:30 window. One fresh Muse session per ticket (plan with Wonder high, implement with Spark medium). "Cut" means the first things dropped if a day slips.

| T | Day | Title | Done when | Depends |
|---|---|---|---|---|
| T2 | Oct 28 | SPEC v0.4 (docs only) | D1–D10 in SPEC. §9 dates moved. AT9 line in the 001 evidence note fixed | — |
| T3 | Oct 28 | Core schemas | Pydantic models: `Event` (+ typed `data` per type), `Fact`, `Profile(subject_id, profile_id)`, `Criterion`, `Manifest`, `BlockConfig` base, `Decision`. JSON Schema exported to `schemas/`. Round-trip tests | T2 |
| T4 | Oct 28 | Event store and collector framework | SQLite append-only `events`, `cursors`, idempotent upsert, nightly batch hash, `Collector` protocol (`poll(cursor) -> (events, cursor)`), fixture collector. Tests offline | T3 |
| T5 | Oct 29 | Collectors wave 1: Calendar, GitHub (exclusion), public feed | Each passes a recorded-fixture test; one live poll each writes events; no titles or bodies in public tier | T4 |
| T6 | Oct 29 | Blocks v0 (6) and renderer | `checklist, focus_session, checkin, calendar_slots, insight_card, link_list`: schema, renderer, unit test, L0 sample each. Manifest renders to a web page | T3 |
| T7 | Oct 29 | Collectors wave 2: Spotify, Health ingest endpoint, ActivityWatch | Same bar as T5. Health: Shortcut documented in `ops/`, POST validated against the model. AW: titles dropped. **Collectors run on a timer from Oct 30 evening (D7)** | T4 |
| T8 | Oct 30 | Gate L0/L1 and mutants | Inspect tasks for structure and rules (PII, secrets, unavailable time, limits). 7 mutants, all caught. In CI | T6 |
| T9 | Oct 30 | Glimmer cycle | events → objective-agnostic facts via `LOCAL_LLM_BASE_URL`. Every fact cites event IDs. Invalid twice → noop. Recorded-fixture test | T4 |
| T10 | Oct 30 | Profiles and criteria | Load A and B. Wonder drafts criteria; owner approves (CLI). Visible criteria in repo, hidden ones in `HIDDEN_CRITERIA_DIR`. The hidden-criteria CI guard (follow-up from T1) lands here | T3 |
| T11 | Oct 31 AM* | Jury, L2/L3, Wonder decision → C1/C2 diff | Panel (Glimmer + Wonder), position swap, binary criteria. Decision schema. Attention score. Budgets | T8–T10 |
| T12 | Oct 31 AM* | Deployer, A0 cards, feedback, kill switch | Blue/green pointer, rollback CLI, `PAUSED` file, 👍/👎 and pairwise ratings stored per profile | T6, T11 |
| T13 | Oct 31 | Orchestrator and ops | systemd timers, persisted state machine, ntfy topics, 12:30 digest, watchdog hook. **Day 0 tag at 13:00** | T11, T12 |
| T14 | Oct 31 | Synthetic personas ×3 and dry run | Personas run on fixtures; one overnight run without the operator | T13 |
| T15 | Nov 1 | κ, calibration, autonomy promotion | κ per profile with n; A0 → A1 rule; automatic demotion | T13 |
| T16 | Nov 1 | Run export and `tour.json` | `export_run`, `draft_tour`, `validate_tour` per [docs/MUSEUM-CONTRACT.md](MUSEUM-CONTRACT.md); tour gate in CI | T13 |
| T17 | Nov 1 | Museum 2D (in repo) | Renders `tour.json`. Built by Muse from the contract; the parallel PoC is a reference only | T16 |
| T18 | Nov 2 | **Cut:** C3 via Muse Code headless | One new block passes gate + block tests; max 1/day/profile | T13 |
| T19 | Nov 2 | **Cut:** L4 canary | 3 h canary, auto rollback on regression | T13 |
| T20 | Nov 2–3 | **Gated (Nov 2, 13:00 Europe/Madrid):** Museum XR | WebXR mode of T17 on Quest 3; 60 s headset recording | T17 |
| T21 | Nov 3 | Metrics notebook and blind attribution kit | Metrics regenerate from logs; rater packet without labels; 2 raters booked | T15 |
| T22 | Nov 4 | Submission | Attribution run, video, README, CONTRIBUTIONS; submit by 21:00 ET | all |

\* The window opens at 13:00, so "Oct 31 AM" really means the first tickets after 13:00. If T11/T12 don't fit before 13:00, day 0 becomes Oct 31 evening or Nov 1 13:00 if T11–T13 are not done. Collectors already run from Oct 30 evening, so the stream loses nothing.

**Load:** 21 tickets in 7 days is ~3/day with no slack. If a day slips, cut in this order: T19, T18, T20, then personas down to 1 in T14.

### 3.1 Creating the GitHub issues

One Muse prompt, once T2 is merged:

```
Read docs/PLAN.md §3. For each row T3–T22, create a GitHub issue with gh:
title "T<n>: <title>", body = "Done when" + "Depends" + link to docs/PLAN.md,
labels: ops / eval / demo / C1-C2 / C3 as fitting, and "cut" for rows marked Cut.
Show me the list of commands before running any.
```
