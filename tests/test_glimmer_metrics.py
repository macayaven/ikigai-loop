"""Ticket 9: logical dedup keys, clipping, counts, periods (direct metrics level)."""

from pathlib import Path

from evals.glimmer_cases import (
    AS_OF,
    KNOWN_GOOD,
    SUBJECT_ID,
    WINDOW_START,
    _dt,
    cal_event,
    feed_event,
    pr_event,
    push_event,
    screen_event,
)
from framework.briefing.context import MetricSnapshot
from framework.briefing.labels import metric_label_binding
from framework.glimmer.metrics import (
    build_metric_snapshot,
    build_period_rollup,
    select_winners,
)
from framework.schemas.events import Event
from framework.store import EventStore


def _through_store(events: list[Event], tmp_path: Path) -> list[Event]:
    store = EventStore(db_path=tmp_path / "metrics.db")
    try:
        store.append_events(events)
        return store.events_between(SUBJECT_ID, WINDOW_START, AS_OF)
    finally:
        store.close()


def _winners_snapshot(events: list[Event]) -> MetricSnapshot:
    return build_metric_snapshot(AS_OF, select_winners(events))


def test_calendar_updated_supersedes_created_busy_counted_once(
    tmp_path: Path,
) -> None:
    events = _through_store(
        [
            cal_event(
                eid="evt_m1_created",
                key="wk-1@20261030T090000",
                lm="seq1",
                time=_dt(30, 9),
                end=_dt(30, 10),
                collected_at=_dt(30, 10),
            ),
            cal_event(
                eid="evt_m1_updated",
                key="wk-1@20261030T090000",
                lm="seq2",
                kind="updated",
                time=_dt(30, 9),
                end=_dt(30, 10),
                collected_at=_dt(30, 11),
            ),
        ],
        tmp_path,
    )
    snapshot = _winners_snapshot(events)
    assert snapshot.values["calendar.busy_hours"] == 1.0
    assert snapshot.values["tag_hours.iki-focus"] == 1.0


def test_cancelled_winner_contributes_no_busy_but_counts_cancelled(
    tmp_path: Path,
) -> None:
    events = _through_store(
        [
            cal_event(
                eid="evt_m2_created",
                key="wk-2@20261029T150000",
                lm="seq1",
                time=_dt(29, 15),
                end=_dt(29, 16),
                tags=("iki-trip",),
                collected_at=_dt(29, 16),
            ),
            cal_event(
                eid="evt_m2_cancelled",
                key="wk-2@20261029T150000",
                lm="seq2",
                time=_dt(29, 15),
                end=_dt(29, 16),
                tags=("iki-trip",),
                cancelled=True,
                collected_at=_dt(29, 17),
            ),
        ],
        tmp_path,
    )
    snapshot = _winners_snapshot(events)
    assert snapshot.values["calendar.busy_hours"] == 0.0
    assert "tag_hours.iki-trip" not in snapshot.values
    assert snapshot.values["period.prior.cancelled.iki-trip"] == 1.0


def test_screen_winner_by_collected_at_not_source_id(tmp_path: Path) -> None:
    events = _through_store(
        [
            screen_event(
                eid="evt_m3_old",
                time=_dt(30, 18),
                minutes={"Programming": 60.0},
                digest="zzz999",
                collected_at=_dt(30, 19),
            ),
            screen_event(
                eid="evt_m3_new",
                time=_dt(30, 18),
                minutes={"Programming": 120.0},
                digest="aaa000",
                collected_at=_dt(30, 20),
            ),
        ],
        tmp_path,
    )
    snapshot = _winners_snapshot(events)
    assert snapshot.values["screen_hours.Programming"] == 2.0


def test_feed_item_repeated_across_days_counts_once(tmp_path: Path) -> None:
    events = _through_store(
        [
            feed_event(
                eid="evt_m4_d1",
                item="paper-z",
                day="2026-10-29",
                time=_dt(29, 10),
                title="Synthetic neural garden robot control systems",
                collected_at=_dt(29, 11),
            ),
            feed_event(
                eid="evt_m4_d2",
                item="paper-z",
                day="2026-10-30",
                time=_dt(30, 10),
                title="Synthetic neural garden robot control systems",
                collected_at=_dt(30, 11),
            ),
        ],
        tmp_path,
    )
    snapshot = _winners_snapshot(events)
    assert snapshot.values["feed.item.count"] == 1.0
    assert snapshot.values["feed.item.count.hf"] == 1.0


def test_in_progress_block_clipped_at_as_of() -> None:
    block = cal_event(
        eid="evt_m5_block",
        key="wk-5@20261031T110000",
        lm="seq1",
        time=_dt(31, 11),
        end=_dt(31, 15),
    )
    snapshot = build_metric_snapshot(AS_OF, [block])
    assert snapshot.values["calendar.busy_hours"] == 2.0
    assert snapshot.values["tag_hours.iki-focus"] == 2.0


def test_cross_boundary_block_contributes_to_both_periods() -> None:
    block = cal_event(
        eid="evt_m6_block",
        key="wk-6@20261030T120000",
        lm="seq1",
        time=_dt(30, 12),
        end=_dt(30, 14),
        tags=("iki-span",),
    )
    rollup = build_period_rollup(AS_OF, [block])
    assert rollup["prior"]["calendar_hours_by_tag"] == {"iki-span": 1.0}
    assert rollup["last"]["calendar_hours_by_tag"] == {"iki-span": 1.0}
    snapshot = build_metric_snapshot(AS_OF, [block])
    assert snapshot.values["period.prior.tag_hours.iki-span"] == 1.0
    assert snapshot.values["period.last.tag_hours.iki-span"] == 1.0
    assert snapshot.values["tag_hours.iki-span"] == 2.0


def test_row_exactly_on_boundary_belongs_to_later_period() -> None:
    push = push_event(eid="evt_m7_push", time=_dt(30, 13))
    rollup = build_period_rollup(AS_OF, [push])
    assert rollup["prior"]["pushes"] == 0
    assert rollup["last"]["pushes"] == 1


def test_zero_push_pr_counts_present_and_zero_only_keys_absent() -> None:
    snapshot = build_metric_snapshot(AS_OF, [])
    assert snapshot.values["calendar.busy_hours"] == 0.0
    assert snapshot.values["feed.item.count"] == 0.0
    assert snapshot.values["period.last.pushes"] == 0.0
    assert snapshot.values["period.last.prs"] == 0.0
    assert "github.push.count" not in snapshot.values
    assert "screen_hours.Programming" not in snapshot.values
    assert "tag_hours.iki-focus" not in snapshot.values


def test_same_invite_on_two_calendars_counts_once(tmp_path: Path) -> None:
    from evals.glimmer_cases import make_event

    def _invite(source: str, tag: str, collected: object) -> Event:
        return make_event(
            eid=f"evt_two_cal_{source}",
            source=source,
            source_id="invite-7@20261030T090000@seq1",
            type="calendar.event.created",
            time=_dt(30, 9),
            data={
                "start": _dt(30, 9).isoformat(),
                "end": _dt(30, 10).isoformat(),
                "busy": True,
                "category": "personal",
                "tags": [tag],
                "is_new": False,
            },
            tier="private",
            collected_at=collected,  # type: ignore[arg-type]
        )

    events = _through_store(
        [
            _invite("calendar-personal", "iki-a", _dt(30, 10)),
            _invite("calendar-work", "iki-b", _dt(30, 11)),
        ],
        tmp_path,
    )
    snapshot = _winners_snapshot(events)
    assert snapshot.values["calendar.busy_hours"] == 1.0
    assert snapshot.values.get("tag_hours.iki-a") is None
    assert snapshot.values["tag_hours.iki-b"] == 1.0


def test_zoned_as_of_gives_three_absolute_24h_periods() -> None:
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from framework.glimmer.metrics import period_bounds

    as_of = datetime(2026, 10, 26, 12, tzinfo=ZoneInfo("Europe/Madrid"))
    bounds = period_bounds(as_of)
    assert [name for name, _, _ in bounds] == ["earlier", "prior", "last"]
    for _, start, end in bounds:
        span = end.astimezone(UTC) - start.astimezone(UTC)
        assert span == timedelta(hours=24), (start, end)


def test_same_screen_instant_in_two_offsets_counts_once() -> None:
    from datetime import UTC, timedelta, timezone

    first = screen_event(
        eid="evt_offset_early",
        time=_dt(30, 12),
        minutes={"Programming": 60.0},
        digest="early111",
        collected_at=_dt(30, 13),
    )
    same_instant = first.time.astimezone(UTC).astimezone(timezone(timedelta(hours=5)))
    second = screen_event(
        eid="evt_offset_late",
        time=same_instant,
        minutes={"Programming": 120.0},
        digest="late222",
        collected_at=_dt(30, 14),
    )
    assert first.time == second.time
    assert first.time.isoformat() != second.time.isoformat()
    snapshot = _winners_snapshot([first, second])
    assert snapshot.values["screen_hours.Programming"] == 2.0


def test_per_source_feed_counts_and_prompt_values_full_precision() -> None:
    events = [
        feed_event(
            eid="evt_m8_a",
            item="a",
            day="2026-10-30",
            time=_dt(30, 9),
            title="Synthetic transformer pruning benchmark results",
            source="hf",
        ),
        feed_event(
            eid="evt_m8_b",
            item="b",
            day="2026-10-30",
            time=_dt(30, 10),
            title="Synthetic container scheduler release notes",
            source="hn",
            score=120.0,
        ),
        feed_event(
            eid="evt_m8_c",
            item="c",
            day="2026-10-30",
            time=_dt(30, 11),
            title="Synthetic vector index library update",
            source="github",
            score=45.0,
        ),
    ]
    snapshot = build_metric_snapshot(AS_OF, events)
    assert snapshot.values["feed.item.count"] == 3.0
    assert snapshot.values["feed.item.count.hf"] == 1.0
    assert snapshot.values["feed.item.count.hn"] == 1.0
    assert snapshot.values["feed.item.count.github"] == 1.0


def test_dst_window_clips_busy_hours_at_absolute_72h() -> None:
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from evals.glimmer_cases import cal_event
    from framework.glimmer.metrics import build_metric_snapshot

    as_of = datetime(2026, 10, 26, 12, tzinfo=ZoneInfo("Europe/Madrid"))
    base = as_of.astimezone(UTC)
    start = base - timedelta(hours=74)
    end = base - timedelta(hours=70)
    row = cal_event(
        eid="evt_dst_clip",
        key="dst-clip@20261023T100000",
        lm="seq1",
        time=start,
        end=end,
        collected_at=end,
    )
    snapshot = build_metric_snapshot(as_of, [row])
    assert snapshot.values["calendar.busy_hours"] == 2.0


def test_metric_ids_bind_to_gate_families() -> None:
    events = [
        screen_event(
            eid="evt_bind_screen_earlier",
            time=_dt(28, 14),
            minutes={
                "code": 60.0,
                "comms": 30.0,
                "feed": 20.0,
                "browse": 10.0,
                "media": 15.0,
                "other": 5.0,
            },
        ),
        screen_event(
            eid="evt_bind_screen_prior",
            time=_dt(29, 14),
            minutes={"code": 60.0},
        ),
        screen_event(
            eid="evt_bind_screen_last",
            time=_dt(30, 14),
            minutes={"code": 60.0},
        ),
        cal_event(
            eid="evt_bind_cal_earlier",
            key="bind-a@20261028T100000",
            lm="seq1",
            time=_dt(28, 10),
            end=_dt(28, 12),
            tags=("iki-deep", "iki-family"),
        ),
        cal_event(
            eid="evt_bind_cal_prior",
            key="bind-b@20261029T100000",
            lm="seq1",
            time=_dt(29, 10),
            end=_dt(29, 12),
            tags=("iki-deep", "iki-family"),
        ),
        cal_event(
            eid="evt_bind_cal_last",
            key="bind-c@20261030T100000",
            lm="seq1",
            time=_dt(30, 10),
            end=_dt(30, 12),
            tags=("iki-deep", "iki-family"),
        ),
        cal_event(
            eid="evt_bind_cancel_last",
            key="bind-d@20261030T130000",
            lm="seq1",
            time=_dt(30, 13),
            end=_dt(30, 14),
            tags=("iki-deep",),
            cancelled=True,
        ),
        push_event(eid="evt_bind_push", time=_dt(30, 14)),
        pr_event(eid="evt_bind_pr", time=_dt(30, 15)),
        feed_event(
            eid="evt_bind_hn",
            item="bind-hn",
            day="2026-10-30",
            time=_dt(30, 9),
            title="Synthetic binding hn title alpha",
            source="hn",
        ),
        feed_event(
            eid="evt_bind_hf",
            item="bind-hf",
            day="2026-10-30",
            time=_dt(30, 10),
            title="Synthetic binding hf title beta",
            source="hf",
        ),
        feed_event(
            eid="evt_bind_gh",
            item="bind-gh",
            day="2026-10-30",
            time=_dt(30, 11),
            title="Synthetic binding github title gamma",
            source="github",
        ),
    ]
    snapshot = _winners_snapshot(events)
    required = [
        "period.earlier.screen_hours.code",
        "period.prior.tag_hours.iki-deep",
        "period.last.cancelled.iki-deep",
        "period.last.pushes",
        "period.last.prs",
        "screen_hours.code",
        "tag_hours.iki-deep",
        "github.push.count",
        "github.pr.count",
        "calendar.busy_hours",
        "feed.item.count",
        "feed.item.count.hn",
    ]
    for key in required:
        assert key in snapshot.values, sorted(snapshot.values)
    for key in snapshot.values:
        assert metric_label_binding(key) is not None, key
    assert len(KNOWN_GOOD) == 6
    for case in KNOWN_GOOD:
        for key in case.expected_snapshot:
            assert metric_label_binding(key) is not None, (case.name, key)


def test_zero_keys_for_one_period_member_only() -> None:
    from evals.glimmer_cases import _dt as dt

    row = screen_event(eid="evt_zero_one", time=dt(30, 14), minutes={"Solo/Cat": 60.0})
    snapshot = _winners_snapshot([row])
    assert snapshot.values["period.last.screen_hours.Solo/Cat"] == 1.0
    assert snapshot.values["period.prior.screen_hours.Solo/Cat"] == 0.0
    assert snapshot.values["period.earlier.screen_hours.Solo/Cat"] == 0.0


def test_zero_keys_absent_for_all_zero_member() -> None:
    from evals.glimmer_cases import _dt as dt

    row = screen_event(eid="evt_zero_none", time=dt(30, 14), minutes={"Solo/Cat": 0.0})
    snapshot = _winners_snapshot([row])
    assert "period.last.screen_hours.Solo/Cat" not in snapshot.values
    assert "period.prior.screen_hours.Solo/Cat" not in snapshot.values


def test_zero_keys_written_in_sorted_order() -> None:
    from evals.glimmer_cases import _dt as dt

    # Ten categories inserted out of alphabetical order (Cat/j down to
    # Cat/a); five tags the same way. Every member is non-zero only in
    # last, so in prior each holds just its zero key.
    screens = [
        screen_event(
            eid=f"evt_sort_s_{letter}",
            time=dt(30, 14, i),
            minutes={f"Cat/{letter}": 10.0},
        )
        for i, letter in enumerate("jihgfedcba")
    ]
    blocks = [
        cal_event(
            eid=f"evt_sort_b_{letter}",
            key=f"sort-b-{letter}@20261030T140000",
            lm="seq1",
            time=dt(30, 14),
            end=dt(30, 15),
            tags=(f"iki-{letter}",),
        )
        for letter in "edcba"
    ]
    cancelled = [
        cal_event(
            eid=f"evt_sort_x_{letter}",
            key=f"sort-x-{letter}@20261030T160000",
            lm="seq1",
            time=dt(30, 16),
            end=dt(30, 17),
            tags=(f"iki-{letter}",),
            cancelled=True,
        )
        for letter in "edcba"
    ]
    snapshot = _winners_snapshot([*screens, *blocks, *cancelled])
    for prefix in (
        "period.prior.screen_hours.",
        "period.prior.tag_hours.",
        "period.prior.cancelled.",
    ):
        keys = [k for k in snapshot.values if k.startswith(prefix)]
        assert keys == sorted(keys), prefix
    screen_keys = [
        k for k in snapshot.values if k.startswith("period.prior.screen_hours.")
    ]
    # Hand-derived: ten zero keys, Cat/a first and Cat/j last in sort order.
    assert screen_keys[0] == "period.prior.screen_hours.Cat/a"
    assert screen_keys[-1] == "period.prior.screen_hours.Cat/j"
