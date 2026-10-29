# iOS Health Shortcut (ticket 7)

Daily 08:00 automation that POSTs yesterday's Health aggregates to the
ingest endpoint on the store host. All values below are synthetic examples.

## Automation steps

1. Create a Personal Automation for 08:00 daily, running the shortcut below.
2. Compute `date` as yesterday in Europe/Madrid (at the 08:00 run, the
   just-completed day).
3. Use "Find Health Samples" for the day of `date`:
   - Sleep: the session that ended on the morning of `date`. Sleep is the
     session that ended on the morning of `date` (a night's sleep belongs to
     the day it ends on).
   - Resting heart rate, heart-rate variability, steps, exercise minutes.
   - Mindful minutes, Time in Daylight (maps to `daylight_min`), State of
     Mind (maps to `mood_valence` in [-1, 1]).
4. Omit (or send `null` for) any metric the device has no sample for.
5. POST the JSON body to the store-host ingest endpoint
   `https://<store-host>/health/daily` with header
   `Authorization: Bearer <INGEST_TOKEN>`.

## Payload

```json
{
  "date": "2026-10-29",
  "sleep_h": 7.25,
  "resting_hr": 58.0,
  "hrv_ms": 42.5,
  "steps": 8234,
  "exercise_min": 31.0,
  "mindful_min": 10.0,
  "daylight_min": 95.0,
  "mood_valence": 0.4
}
```

`date` is yesterday in Europe/Madrid; `time` is stored as midnight
Europe/Madrid on that date. Unknown keys are rejected, so a Shortcut edit
that adds a field fails loudly instead of storing silently.

## Corrections supersede

A corrected re-post for the same `date` creates a new event; it never
overwrites and never returns `409`. Consumers take the latest `collected_at`
per date, so the correction wins. An identical re-post is a no-op.

## Privacy

Health values never appear in a public chart. Raw health events stay on the
local machine; only derived facts leave it.
