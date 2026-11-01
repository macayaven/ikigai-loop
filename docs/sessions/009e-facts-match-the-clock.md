# Session evidence — 009e-facts-match-the-clock (2026-11-01)

Ticket 9e only, slice E: the docs, and nothing else. This session changed no
code and no test. Slices A to D were built in earlier sessions on branch
`t9e-clock`; this session wrote `docs/PREREG.md`, `CONTRIBUTIONS.md`,
`README.md` and this note, then stopped before the commit. Headless: nobody
could answer questions during the run. Assumptions I stated rather than asked
about: the four collector suites are `tests/test_calendar_ics.py`,
`tests/test_github_events.py`, `tests/test_build_feed.py` and
`tests/test_activitywatch.py`, and the CLI suite is
`tests/test_collectors_cli.py`, the same suites the README line names; the
fact-layer count comes from collecting `tests/test_glimmer_*.py` with
`tests/test_fact_store.py` and `tests/test_cycle_cli.py`; the AT results, the
removal results and the before/after outputs below are my reviewer's, recorded
as Claude Code wrote them. I read nothing outside this repository.

Tool versions:

```
muse --version
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Models and efforts. Prompts and review by Claude Code. Plan:
muse-wonder-full-1.0 (effort high). Implementation: muse-spark-1.3 (effort
medium), in Muse Code, in headless sessions Claude Code started. The commit step, the move onto main and the final text fixes ran on muse-spark-1.3 at effort low.

These findings came from independent reviews by GPT Sol 6.1, run through Codex, and by Muse Wonder Full (items 8, 9, 10; items 1 to 4 were found by both), reproduced by Claude Code, and implemented by Muse Code.

Item 11, the moved block, was found by Claude Code during plan review and
reproduced the same way.

## Changed expectations, with hand-derived values

- `tests/test_calendar_ics.py`,
  `test_disappearance_emits_one_cancelled_and_bumped_emits_updated`: the
  updated row's source id now ends `#r1`. It is the key's second emission,
  and every emission after the first is `{key}@{stamp}#r{rev}`, rev 1.
- `tests/test_calendar_ics.py`, `test_two_labels_keep_independent_cursors`:
  home on an empty feed goes from (1, 0) to (0, 0), with no cancelled row.
  The feed parses with zero VEVENTs and the cursor holds an active instance,
  so nothing is emitted and the cursor stays.
- `tests/test_glimmer_metrics.py`,
  `test_same_invite_on_two_calendars_counts_once`: `tag_hours.iki-a` goes
  from absent to 1.0. One invitation on two calendars, Oct 30 09:00 to 10:00:
  both active rows stay, busy is the union, 1.0, and each tag holds 1.0.
- `tests/test_glimmer_code_facts.py`, `test_evidence_time_tie_sorts_by_id`:
  "fell from 26" becomes "fell from 24". As of Oct 31 13:00, blocks a Oct 29
  10:00 to Oct 30 15:00, b Oct 29 10:00 to 14:00, z Oct 29 16:00 to 17:00.
  Earlier union 3, prior union 24 because a alone covers it (the old sum was
  24 + 1 + 1), last 2. Changes 21 and 22, so prior to last wins.
- `tests/test_glimmer_code_facts.py`,
  `test_ai_template_duplicate_and_system_model_fact`: the model's "system
  screen hours rose..." goes from kept to dropped, `FACT_SCREEN_SYSTEM_CATEGORY`:
  it has the token `system` and cites a screen row.
- `tests/test_cycle_cli.py`,
  `test_run_cycle_asks_for_absolute_72h_window`: one load becomes three:
  labels and calendar over the sentinel bounds, everything else over the 72
  absolute hours before `as_of`, a whole hour in that test.
- `evals/glimmer_cases.py` (3 lines) and `tests/test_glimmer_facts.py`
  (3 lines): "1 feed items" becomes "1 feed item". Each cites exactly one
  item.

## Acceptance tests, as run by my reviewer

```
AT1: 15 passed, 17 deselected in 0.13s
AT2: 17 passed, 15 deselected in 0.11s
AT3: 8 passed, 42 deselected in 0.09s
AT4: 12 passed, 17 deselected in 0.10s
AT5: 16 passed in 0.09s
AT6: 239 passed in 2.01s
AT7 (on base, must fail): 2 failed, 6 passed, 74 deselected in 0.17s
AT7b, the whole clock suite on base: 28 failed, 4 passed in 0.25s
AT8 make eval exit=0: proposal_gate: 37/37 correct (status=success)
AT8 make check exit=0: ======================= 1963 passed, 1 skipped in 26.46s =======================
```

## Removal checks, as run by my reviewer

Each removal check took one fix back out on a scratch copy and ran the fix's
suites. The checks ran on a scratch copy, not in this tree; the results below
are Claude Code's.

```
killed       D1 period_bounds stops flooring: 11 red: test_floor_hour_half_hour_offset_lands_on_utc_hour, test_floor_madrid_fall_back, test_half_hour_cut_invents_no_chang
killed       D1 floor on the wall clock: 1 red: test_floor_hour_half_hour_offset_lands_on_utc_hour
killed       D1 snapshot totals keep the open hour: 1 red: test_snapshot_totals_stop_at_the_floor
killed       D2 check_fact open-hour arm off: 4 red: test_open_hour_calendar_blocks_false_zero, test_open_hour_cancelled_blocks_false_zero, test_open_hour_push_blocks_fal
killed       D2 snapshot omission off: 1 red: test_open_hour_zero_omitted_from_snapshot_and_gate
killed       D2 extract_facts stops passing families to the snapshot: 1 red: test_open_hour_zero_omitted_from_snapshot_and_gate
killed       D3 union back to a plain sum: 4 red: test_cancellation_is_per_calendar, test_evidence_time_tie_sorts_by_id, test_overlapping_blocks_union, test_same_invite_o
killed       D4 run_cycle loads calendar by time: 3 red: test_block_crossing_window_start_counts_clipped, test_revision_moved_out_wins, test_run_cycle_asks_for_absolute_7
killed       D4 run_cycle loads labels by time: 2 red: test_block_crossing_window_start_counts_clipped, test_run_cycle_asks_for_absolute_72h_window
killed       D4 facts time filter back: 2 red: test_block_crossing_window_start_counts_clipped, test_revision_moved_out_wins
killed       D4 selection off: all winners enter: 2 red: test_window_includes_start_excludes_as_of, test_zoned_as_of_excludes_row_72h30m_old
killed       D4 evidence test back to start-only: 1 red: test_block_crossing_window_start_counts_clipped
killed       D4 key loses the source: 3 red: test_cancellation_is_per_calendar, test_moved_block_second_calendar_not_yet_polled, test_same_invite_on_two_calendars_counts_
killed       D4 combine step off: 1 red: test_cancellation_is_per_calendar
killed       Item 11 move rule off: 5 red: test_moved_block_is_not_cancelled, test_moved_block_stamp_bump_keeps_move_suppression, test_moved_block_then_delete_one_cancell
killed       Item 11 scan narrowed to winners: 3 red: test_moved_block_stamp_bump_keeps_move_suppression, test_moved_block_then_delete_one_cancelled, test_recurring_insta
killed       Item 11 any active sibling counts: 1 red: test_recurring_instance_removed_with_master_stamp_bump_still_cancels
killed       D5 STATUS ignored: 3 red: test_cancelled_recurring_instance_override_one_cancelled_row, test_status_cancelled_emits_cancellation, test_tombstone_cancelled_ch
killed       D5 stamp arm removed: 2 red: test_content_change_with_same_stamp_emits, test_disappearance_emits_one_cancelled_and_bumped_emits_updated
killed       D5 content arm removed: 2 red: test_content_change_with_same_stamp_emits, test_unparseable_stored_start_emits_updated
killed       D5 instants compared as strings: 1 red: test_same_instant_different_offset_emits_nothing
killed       D5 empty-feed guard off: 2 red: test_empty_feed_cancels_nothing, test_two_labels_keep_independent_cursors
killed       D5 guard tests the expansion: 2 red: test_far_past_vevent_feed_emits_one_cancelled, test_instance_that_ages_out_of_window_emits_nothing
killed       D5 old cursor stamp not derived: 1 red: test_first_poll_on_old_cursor_emits_nothing
killed       D5 tombstone forgotten when key gone: 1 red: test_restored_after_gone_for_two_polls
killed       D5 sink written outside the final id: 2 red: test_content_change_with_same_stamp_emits, test_restored_event_wins_again
killed       D6 one page only: 7 red: test_github_follows_pages, test_github_pager_http_next_same_host_is_off_origin, test_github_pager_later_page_failure_leaves_cursor,
killed       D6 off-origin followed: 2 red: test_github_pager_http_next_same_host_is_off_origin, test_github_pager_off_origin_next_raises
killed       D6 ETag from the last page: 2 red: test_github_follows_pages, test_github_pager_stops_after_three_pages
killed       D6 conditional header on every page: 1 red: test_github_follows_pages
killed       D6 no dedup: 1 red: test_github_follows_pages
killed       D7 system arm off: 2 red: test_ai_template_duplicate_and_system_model_fact, test_model_system_screen_fact_dropped
killed       D7 feed grammar back: 4 red: test_blank_topic_takes_repair_retry, test_one_feed_item_singular, test_topic_citing_one_item_twice_counts_one, test_topic_intern
killed       D8 by-order pairing off: 1 red: test_number_bound_to_named_period
killed       D8 swap: pairing ignored in the scan: 1 red: test_number_bound_to_named_period
killed       D8 totals back a paired token: 1 red: test_total_does_not_back_a_paired_number
killed       D8 word boundary instead of lookaround: 1 red: test_number_bound_to_named_period
killed       D8 no-period statement loses period keys: 1 red: test_statement_naming_no_period_keeps_old_rule
survivors 0 of 38
```

## Before and after per item, made-up data, from the reproductions

**A screen hour across a half-hour cut.** The whole bucket now sits in the
floored `last`, where it was recorded; the reproduction's `actual_hours` line
is the old half-hour reading.

```
before:
facts=["code screen hours fell from 1 in prior to 0 in last."]
actual_hours: prior=0.5, last=0.5
after:
facts=["code screen hours rose from 0 in prior to 1 in last."]
actual_hours: prior=0.5, last=0.5
```

**A block crossing the window start.** At the reproduction's half-hour `as_of`
the floored window holds 1.5, 1.5 and 2.5 hours, 5.5 in all; the whole-hour
twin in `test_block_crossing_window_start_counts_clipped` reads 1, 2, 2
and 5.

```
before:
metrics={"calendar.busy_hours": 4.0, "period.earlier.tag_hours.iki-focus": 0.0, "period.last.tag_hours.iki-focus": 2.0, "period.prior.tag_hours.iki-focus": 2.0, "tag_hours.iki-focus": 4.0}
facts=["iki-focus calendar hours rose from 0 in earlier to 2 in prior."]
after:
metrics={"calendar.busy_hours": 5.5, "period.earlier.tag_hours.iki-focus": 1.5, "period.last.tag_hours.iki-focus": 2.5, "period.prior.tag_hours.iki-focus": 1.5, "tag_hours.iki-focus": 5.5}
facts=["iki-focus calendar hours rose from 1.5 in prior to 2.5 in last."]
```

**Two overlapping blocks.**

```
before:
metrics={"calendar.busy_hours": 2.0, "period.earlier.tag_hours.iki-focus": 0.0, "period.last.tag_hours.iki-focus": 2.0, "period.prior.tag_hours.iki-focus": 0.0, "tag_hours.iki-focus": 2.0}
facts=["iki-focus calendar hours rose from 0 in prior to 2 in last."]
actual_busy_clock_hours=1
after:
metrics={"calendar.busy_hours": 1.0, "period.earlier.tag_hours.iki-focus": 0.0, "period.last.tag_hours.iki-focus": 1.0, "period.prior.tag_hours.iki-focus": 0.0, "tag_hours.iki-focus": 1.0}
facts=["iki-focus calendar hours rose from 0 in prior to 1 in last."]
actual_busy_clock_hours=1
```

**A block moved out of the past.**

```
before:
metrics={"calendar.busy_hours": 1.0, "period.earlier.tag_hours.iki-focus": 0.0, "period.last.tag_hours.iki-focus": 0.0, "period.prior.tag_hours.iki-focus": 1.0, "tag_hours.iki-focus": 1.0}
facts=["iki-focus calendar hours fell from 1 in prior to 0 in last."]
after:
metrics={"calendar.busy_hours": 0.0}
facts=[]
```

**The same move through the collector.**

```
before:
metrics={"calendar.busy_hours": 1.0, "period.earlier.tag_hours.iki-focus": 0.0, "period.last.tag_hours.iki-focus": 0.0, "period.prior.tag_hours.iki-focus": 1.0, "tag_hours.iki-focus": 1.0}
facts=["iki-focus calendar hours fell from 1 in prior to 0 in last."]
after:
metrics={"calendar.busy_hours": 0.0}
facts=[]
```

**An explicit STATUS:CANCELLED.**

```
before:
mapped_types=['calendar.event.created']
facts=["iki-focus calendar hours rose from 0 in prior to 1 in last."]
after:
mapped_types=['calendar.event.cancelled']
facts=["Cancelled iki-focus blocks rose from 0 in prior to 1 in last."]
```

**A restored block.** This reproduction removes the block with an empty feed,
so after the fix it isn't cancelled at all;
`test_restored_event_wins_again` and `test_restored_after_gone_for_two_polls`
cover a restore from a feed that still holds other blocks.

```
before:
poll2_inserted=1
stored_winner=calendar.event.cancelled
facts=["Cancelled iki-focus blocks rose from 0 in prior to 1 in last."]
after:
poll2_inserted=0
stored_winner=calendar.event.created
facts=["iki-focus calendar hours rose from 0 in prior to 1 in last."]
```

**A copy deleted from one of two calendars.**

```
before:
winning_type=calendar.event.cancelled
facts=["Cancelled iki-focus blocks rose from 0 in prior to 1 in last."]
after:
winning_type=calendar.event.created
facts=["iki-focus calendar hours rose from 0 in prior to 1 in last."]
```

**Same-stamp revision.**

```
before:
same-start/same-LM revision (end 10->12, focus->family, busy->free): events= []
after:
same-start/same-LM revision (end 10->12, focus->family, busy->free): events= [one calendar.event.updated row]
```

**Numbers bound to periods.**

```
before:
check_fact 'Pushes were 0 in last' citing ['p-last-1', 'p-last-2'] -> None
check_fact 'Pushes were 2 in earlier' citing ['p-last-1', 'p-last-2'] -> None
check_fact screen swaps -> None
after:
check_fact 'Pushes were 0 in last' citing ['p-last-1', 'p-last-2'] -> FACT_NUMBER_UNBACKED
check_fact 'Pushes were 2 in earlier' citing ['p-last-1', 'p-last-2'] -> FACT_NUMBER_UNBACKED
check_fact screen swaps -> FACT_NUMBER_UNBACKED
```

**GitHub paging.**

The reproduction's stub answers every request with the same 100 events and the same next link, so the pager asks three times, keeps each id once, and stops at its three-page limit.

```
before:
requests= ['https://api.github.com/users/synthetic/events?per_page=100'] events= 100 cursor= {'etag': 'W/"new"'} (page2 never requested; older >100 since old etag are skipped forever)
after:
requests= ['https://api.github.com/users/synthetic/events?per_page=100', 'https://api.github.com/users/synthetic/events?per_page=100&page=2', 'https://api.github.com/users/synthetic/events?per_page=100&page=2'] events= 100 cursor= {'etag': 'W/"new"'}
```

**Partial hour and overlap, directly on the snapshot.**

```
before:
1 screen straddle prior/last {'code': 1.0} {} expected_clip prior~0.333 last~0.667 if uniform, at least not all prior
2 busy_hours two fully overlapping 2h = 4.0 wall-clock busy=2
5 partial current hour snapshot code= 1.0
after:
1 screen straddle prior/last {} {'code': 1.0} expected_clip prior~0.333 last~0.667 if uniform, at least not all prior
2 busy_hours two fully overlapping 2h = 2.0 wall-clock busy=2
5 partial current hour snapshot code= None
```

**A moved one-off block, the eleventh finding.**

```
before:
facts ['iki-family calendar hours rose from 0 in prior to 1 in last.', 'Cancelled iki-family blocks rose from 0 in prior to 1 in last.']
after:
facts ['iki-family calendar hours rose from 0 in prior to 1 in last.']
```

## After the move onto main, as run by Claude Code

1. Ticket 9c merged to main as `e18dd32` after the results above were run. This commit moved onto it with no conflict, in a session at effort low. `framework/`, `tests/` and `evals/glimmer_cases.py` are byte-identical to the tree those results ran on, so the removal checks and the before and after outputs stand.

2. On the moved tree: AT1 to AT7 give the same counts as above. `make check` exits 0 with 1963 passed and 1 skipped, ruff clean, pyright 0 errors and gitleaks finding no leaks. `make eval` exits 0. `make verify-page` leaves the bundle unchanged. The first poll after deploy, on a made-up store and a cursor the old code wrote: four polls, each (0, 0), and no title in the cursor.

3. The whole-hour differential my plan asks for in Slice B: the tree before this commit against this commit, on made-up data, with scripted model answers and no network. It covers every case in `evals/glimmer_cases.py`, the live fixture rows code-only at six whole hours, and 2100 seeded cycles through `run_cycle` with a real store: 300 seeds at each of seven whole hours, among them both 02:00 hours of Madrid's fall-back day and a +05:30 offset that lands on a UTC hour. Each cycle holds 91 to 157 made-up calendar, screen, GitHub and feed rows, with two calendars, revisions, real cancellations and rows collected after `as_of`. Those rows hold no overlapping blocks, no block crossing the window start and no moved block, because this ticket changes those on purpose.

4. The result. Across all 2100 cycles, which kept 12880 facts, and all 6 known-good cases: statements, fact ids, fact windows, stored windows, drop codes, prompt bytes, `prompt_hash` and `cycle_id` are identical. Of the 24 mutants, 18 are identical and 6 differ only by "1 feed items" becoming "1 feed item", and by what follows from that text: the statement, its minted id, or the hash of a dropped statement.

5. One thing isn't byte-identical, so I say it. In 532 of the 2100 cycles the snapshot's busy and tag hours differ in the last float digits, by at most 3.6e-15, because a union measures merged intervals where the old code added one block at a time. No statement in those runs quotes more than two decimals, so no sentence, prompt or id moved. The known-good cases' snapshots are exactly equal.

6. To show this check can fail, I ran the same rows with each difference put back: an `as_of` inside the hour (120 runs), two overlapping blocks (60 runs) and a block crossing the window start (60 runs). None of those 240 came back identical.

7. What it doesn't cover: the seeded cycles hold no `calendar.label` rows and no model sentence quoting a number. Only the eval cases exercise a numbered model sentence here.

HIDDEN_CRITERIA_DIR was never opened
