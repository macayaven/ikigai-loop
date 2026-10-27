# Session evidence — 001-toolchain (2026-10-27)

Tickets 0 and 1 shared one Muse session; from ticket 2 on, one fresh session per ticket. This note summarises the work; the raw
`muse export --redacted` is kept privately and published only if gitleaks
plus a manual check of names and context is clean.

## Plan

- Model: muse-wonder-1.0 (effort high), 2 rounds (initial + amendments).
- Usage: 26 model calls, 19.6k output tokens, 4.2k reasoning, 2.68M input (98% cached).

## Implementation

- Model: muse-spark-1.3 (effort medium), 1 fix round after review.
- Usage: 68 model calls, 23.2k output tokens, 10.4k reasoning, 9.91M input (98% cached).

## Wall time

19.6 min including human review gaps (plan ~9.7, implement ~9.2, fixes ~1.2).

## Acceptance tests

AT1–AT8 and AT10 passed locally on 2026-10-27; AT9 pending CI.

## Notes

- Input tokens are summed per call (context re-sent each call).
- Counts are lower bounds (export reports a history gap).
- Parsed from the export, not reported by Muse.
- Raw redacted export kept privately; it quotes pre-scrub docs.
