"""Ticket 9c: closed label set, hand-tag precedence, tag overlay."""

from typing import get_args

from evals.glimmer_cases import AS_OF, SUBJECT_ID, cal_event
from framework.collectors.common import event_id
from framework.glimmer.labels import (
    INTERNAL_ONLY_LABELS,
    LABELS,
    Label,
    apply_labels,
    effective_label,
    strip_internal_tags,
)
from framework.schemas.events import Event

PINNED_ORDER = (
    "iki-deep",
    "iki-meeting",
    "iki-family",
    "iki-social",
    "iki-care",
    "iki-rest",
    "iki-admin",
    "iki-unknown",
)


def _label_row(
    target: Event, label: str, model_id: str = "mock-model", valid: bool = True
) -> Event:
    source = "glimmer-labels"
    source_id = f"{target.id}#label"
    return Event.model_validate(
        {
            "id": event_id(source, source_id),
            "subject_id": SUBJECT_ID,
            "source": source,
            "type": "calendar.label",
            "time": target.time.isoformat(),
            "source_id": source_id,
            "data": {
                "type": "calendar.label",
                "target_event_id": target.id,
                "label": label,
                "label_source": "local_model",
                "model_id": model_id,
                "valid": valid,
            },
            "tier": "private",
            "collected_at": AS_OF.isoformat(),
            "collector_version": "glimmer-labels@0.1.0",
        }
    )


def test_label_set_has_eight_members_in_pinned_order() -> None:
    assert tuple(LABELS) == PINNED_ORDER
    assert LABELS == get_args(Label)


def test_label_set_defined_once_in_schemas() -> None:
    from framework.schemas.events import LABELS as SCHEMA_LABELS

    assert SCHEMA_LABELS is LABELS


def test_internal_only_is_care_only() -> None:
    assert INTERNAL_ONLY_LABELS == {"iki-care"}


def test_effective_label_hand_source() -> None:
    row = cal_event(
        eid="evt_eff_hand",
        key="synth-eff-hand@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=("iki-focus",),
    )
    view = effective_label(row, None)
    assert (view.label, view.source, view.model_id) == ("iki-focus", "hand", None)


def test_effective_label_hand_ignores_label_row() -> None:
    row = cal_event(
        eid="evt_eff_hand2",
        key="synth-eff-hand2@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=("iki-focus",),
    )
    stored = _label_row(row, "iki-meeting")
    view = effective_label(row, stored)
    assert (view.label, view.source, view.model_id) == ("iki-focus", "hand", None)


def test_effective_label_model_source() -> None:
    row = cal_event(
        eid="evt_eff_model",
        key="synth-eff-model@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    stored = _label_row(row, "iki-meeting", model_id="mock-model")
    view = effective_label(row, stored)
    assert (view.label, view.source, view.model_id) == (
        "iki-meeting",
        "local_model",
        "mock-model",
    )


def test_effective_label_none_source() -> None:
    row = cal_event(
        eid="evt_eff_none",
        key="synth-eff-none@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    view = effective_label(row, None)
    assert (view.label, view.source, view.model_id) == ("iki-unknown", "none", None)


def test_overlay_adds_model_label_only_to_untagged_rows() -> None:
    tagged = cal_event(
        eid="evt_ov_tagged",
        key="synth-ov-tagged@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=("iki-focus",),
    )
    plain = cal_event(
        eid="evt_ov_plain",
        key="synth-ov-plain@20261030T150000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    stored = _label_row(plain, "iki-deep")
    out = apply_labels([tagged, plain], [stored])
    assert out[0] is tagged
    assert list(out[1].data.tags) == ["iki-deep"]  # type: ignore[attr-defined]
    assert list(tagged.data.tags) == ["iki-focus"]  # type: ignore[attr-defined]


def test_overlay_never_rewrites_a_hand_tagged_row() -> None:
    row = cal_event(
        eid="evt_ov_handkept",
        key="synth-ov-handkept@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=("iki-focus",),
    )
    stored = _label_row(row, "iki-meeting")
    out = apply_labels([row], [stored])
    assert out[0] is row
    assert list(out[0].data.tags) == ["iki-focus"]  # type: ignore[attr-defined]


def test_overlay_unknown_and_internal_add_no_tag() -> None:
    first = cal_event(
        eid="evt_ov_unk",
        key="synth-ov-unk@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    second = cal_event(
        eid="evt_ov_care",
        key="synth-ov-care@20261030T150000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    out = apply_labels([first, second], [_label_row(first, "iki-unknown")])
    assert list(out[0].data.tags) == []  # type: ignore[attr-defined]
    out = apply_labels([second], [_label_row(second, "iki-care")])
    assert list(out[0].data.tags) == []  # type: ignore[attr-defined]


def test_overlay_cancelled_row_resolves_through_live_id() -> None:
    live_source_id = "synth-ov-live@20261030T140000@seq1"
    live = cal_event(
        eid=event_id("calendar-personal", live_source_id),
        key="synth-ov-live@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    cancelled = cal_event(
        eid="evt_ov_cancelled",
        key="synth-ov-live@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
        cancelled=True,
    )
    assert cancelled.source_id == live.source_id + "#cancelled"
    stored = _label_row(live, "iki-deep")
    out = apply_labels([cancelled], [stored])
    assert list(out[0].data.tags) == ["iki-deep"]  # type: ignore[attr-defined]


def test_stale_label_does_not_carry_to_updated_row() -> None:
    old = cal_event(
        eid="evt_ov_old",
        key="synth-ov-stale@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
        kind="created",
    )
    new = cal_event(
        eid="evt_ov_new",
        key="synth-ov-stale@20261030T140000",
        lm="seq2",
        time=AS_OF,
        end=AS_OF,
        tags=(),
        kind="updated",
    )
    assert new.id != old.id
    out = apply_labels([new], [_label_row(old, "iki-deep")])
    assert list(out[0].data.tags) == []  # type: ignore[attr-defined]


def test_overlay_later_label_row_wins_either_order() -> None:
    from datetime import timedelta

    row = cal_event(
        eid="evt_ov_two",
        key="synth-ov-two@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=(),
    )
    earlier = _label_row(row, "iki-deep").model_copy(
        update={"collected_at": AS_OF - timedelta(hours=1)}
    )
    later = _label_row(row, "iki-rest")
    assert later.collected_at > earlier.collected_at
    for order in ([earlier, later], [later, earlier]):
        out = apply_labels([row], order)
        assert list(out[0].data.tags) == ["iki-rest"]  # type: ignore[attr-defined]


def test_strip_internal_tags_removes_care_case_insensitively() -> None:
    row = cal_event(
        eid="evt_strip_care",
        key="synth-strip-care@20261030T140000",
        lm="seq1",
        time=AS_OF,
        end=AS_OF,
        tags=("iki-focus",),
    )
    mixed = row.model_copy(
        update={"data": row.data.model_copy(update={"tags": ["IKI-CARE", "iki-focus"]})}
    )
    out = strip_internal_tags([mixed])
    assert list(out[0].data.tags) == ["iki-focus"]  # type: ignore[attr-defined]
    assert list(mixed.data.tags) == ["IKI-CARE", "iki-focus"]  # type: ignore[attr-defined]


def test_strip_internal_tags_leaves_other_events_unchanged() -> None:
    from evals.glimmer_cases import push_event

    push = push_event(eid="evt_strip_push", time=AS_OF)
    out = strip_internal_tags([push])
    assert out[0] is push
