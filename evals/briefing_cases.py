"""Ticket 8: briefing-gate meta-eval cases (single source of truth).

Both the pytest meta-eval (``tests/test_briefing_mutants.py``) and the
Inspect tasks (``evals/briefing_gate.py``) build from ``MUTANTS`` and
``KNOWN_GOOD`` here so the two harnesses can never drift apart.

Every value is synthetic: ``subject-1`` is the repo's existing placeholder
subject, facts are ``fact:synthetic-*``, metrics use the Ticket 9 families
(``screen_hours.*``, ``tag_hours.*``, ``github.push.count``,
``calendar.busy_hours``, ``feed.item.count``, ``period.*``; ``raw.health.*``
only where a mutant needs a raw ID, ``agg.tasks_done`` only where a mutant
needs an unknown family), and free text avoids real names, real measurements,
and real contact details. Times are frozen on 2026-10-31 (Europe/Madrid, CET,
UTC+1) unless a case moves them. Actions come only from
``profiles/commitments.example.json``, the only registry, loaded once below.

Ticket 10c added M119 and Ticket 24 added the five ``T24-`` cases.
M119 and ``T24-2030-corrected-builder-period-last-pushes`` replay real
sentences from delivered cards with the real values they cited, both public
GitHub counts, and the rest of each briefing is made up. The four
screen-hour ``T24-`` cases keep a real sentence's shape (the same label,
direction word and wording) with made-up current, parent and change values
in the same shape, because screen-hour numbers are personal and stay out of
this repository.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

from framework.briefing.commitments import load_commitments
from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.briefing.schemas import Briefing, Commitment

SUBJECT_ID = "subject-1"
TIMEZONE = "Europe/Madrid"
_COMMITMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "profiles" / "commitments.example.json"
)
_LOADED_COMMITMENTS = load_commitments(
    {"IKIGAI_COMMITMENTS_FILE": str(_COMMITMENTS_PATH)}
)
assert _LOADED_COMMITMENTS.available, _LOADED_COMMITMENTS.reason
COMMITMENTS: tuple[Commitment, ...] = _LOADED_COMMITMENTS.commitments
_COMMITMENT_BY_ID: dict[str, Commitment] = {c.id: c for c in COMMITMENTS}
# Synthetic private term used only by M6; invented for this fixture.
SYNTHETIC_TERM = "quetzal-garden"
# Synthetic forbidden raw literal; no known-good text contains it.
RAW_LITERAL = "Invented Calendar Title Zqx"


@dataclass(frozen=True)
class Case:
    """One meta-eval case: raw briefing dict, typed context, expected codes."""

    name: str
    briefing: dict[str, Any]
    context: GateContext
    expected: tuple[str, ...] = ()


def _iso(day: int, hour: int, minute: int) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00+01:00"


def _dt(day: int, hour: int, minute: int) -> datetime:
    return datetime.fromisoformat(_iso(day, hour, minute))


def _facts() -> dict[str, Any]:
    window = {"start": _iso(30, 0, 0), "end": _iso(31, 12, 0)}
    return {
        "fact:synthetic-1": {
            "id": "fact:synthetic-1",
            "subject_id": SUBJECT_ID,
            "window": window,
            "statement": "Synthetic focus session completed yesterday",
            "evidence": ["synthetic session log"],
            "tier": "public",
        },
        "fact:synthetic-2": {
            "id": "fact:synthetic-2",
            "subject_id": SUBJECT_ID,
            "window": window,
            "statement": "Synthetic walk logged in the evening",
            "evidence": ["synthetic walk log"],
            "tier": "public",
        },
        "fact:212": {
            "id": "fact:212",
            "subject_id": SUBJECT_ID,
            "window": window,
            "statement": "Synthetic reference log filed under review",
            "evidence": ["synthetic reference log"],
            "tier": "public",
        },
    }


def _base_metrics() -> dict[str, float]:
    return {
        "screen_hours.Work/Programming": 90.0,
        "tag_hours.iki-walk": 30.0,
        "github.push.count": 3.0,
    }


def _limits() -> ProfileLimits:
    return ProfileLimits(
        timezone=TIMEZONE,
        allowed_start=time(13, 0),
        allowed_end=time(23, 30),
        max_actions=3,
    )


def _action(
    aid: str,
    commitment_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    commitment = _COMMITMENT_BY_ID[commitment_id]
    return {
        "id": aid,
        "commitment_id": commitment_id,
        "kind": commitment.kind,
        "text": commitment.title,
        "dimension": commitment.dimension,
        "proposed_start": start,
        "proposed_end": end,
    }


def _claim(
    cid: str,
    text: str,
    facts: list[str] | None = None,
    refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "text": text,
        "fact_ids": facts if facts is not None else [],
        "metric_refs": refs if refs is not None else [],
    }


def _ref(metric_id: str, value: float) -> dict[str, Any]:
    return {"metric_id": metric_id, "value": value}


def _base_actions(profile: str) -> list[dict[str, Any]]:
    if profile == "disconnect":
        return [
            _action(
                "act-walk-1",
                "cm-disconnect-walk",
                _iso(31, 14, 0),
                _iso(31, 14, 45),
            ),
            _action(
                "act-rest-1",
                "cm-disconnect-rest",
                _iso(31, 18, 0),
                _iso(31, 19, 0),
            ),
        ]
    return [
        _action(
            "act-build-1",
            "cm-builder-parser",
            _iso(31, 14, 0),
            _iso(31, 14, 45),
        ),
        _action(
            "act-write-1",
            "cm-builder-notes",
            _iso(31, 18, 0),
            _iso(31, 19, 0),
        ),
    ]


def _base_sections(profile: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "overall_state",
            "claims": [
                _claim(
                    "claim-o1",
                    "Focus is steady across synthetic sessions",
                    facts=["fact:synthetic-1"],
                )
            ],
            "actions": [],
        },
        {
            "type": "working",
            "claims": [
                _claim(
                    "claim-w1",
                    "Short planning loops keep momentum",
                    facts=["fact:synthetic-2"],
                )
            ],
            "actions": [],
        },
        {"type": "not_working", "claims": [], "actions": []},
        {"type": "actions", "claims": [], "actions": _base_actions(profile)},
    ]


def _base_briefing(profile: str, bid: str) -> dict[str, Any]:
    return {
        "id": bid,
        "profile_id": profile,
        "subject_id": SUBJECT_ID,
        "slot": _iso(31, 13, 0),
        "parent_briefing_id": None,
        "sections": _base_sections(profile),
    }


def _base_context(
    metrics: dict[str, float] | None = None,
    busy: list[tuple[str, str]] | None = None,
    free: list[tuple[str, str]] | None = None,
) -> GateContext:
    free = free if free is not None else [(_iso(31, 13, 0), _iso(31, 23, 30))]
    busy = busy if busy is not None else [(_iso(31, 15, 0), _iso(31, 16, 0))]
    return GateContext(
        facts=_facts(),
        metrics=MetricSnapshot(values=metrics or _base_metrics()),
        parent_briefing=None,
        parent_metrics=None,
        free_intervals=tuple(
            TimeInterval(start=datetime.fromisoformat(s), end=datetime.fromisoformat(e))
            for s, e in free
        ),
        busy_intervals=tuple(
            TimeInterval(start=datetime.fromisoformat(s), end=datetime.fromisoformat(e))
            for s, e in busy
        ),
        limits=_limits(),
        check_slot=True,
        private_terms=(),
        # Fail closed: availability is explicit, never the model default.
        private_terms_available=True,
        raw_metric_ids=frozenset({"raw.health.resting_hr"}),
        forbidden_raw_literals=(RAW_LITERAL,),
        commitments=COMMITMENTS,
        commitments_available=True,
    )


def base_case(profile: str) -> Case:
    """Fully synthetic, passing briefing + context for ``profile``."""
    return Case(
        name=f"base-{profile}",
        briefing=_base_briefing(profile, f"brf-{profile}-base"),
        context=_base_context(),
        expected=(),
    )


def _parent_briefing(profile: str) -> dict[str, Any]:
    week_commitment = (
        "cm-disconnect-week" if profile == "disconnect" else "cm-builder-week"
    )
    return {
        "id": f"brf-{profile}-parent",
        "profile_id": profile,
        "subject_id": SUBJECT_ID,
        "slot": _iso(30, 13, 0),
        "parent_briefing_id": None,
        "sections": [
            {
                "type": "overall_state",
                "claims": [
                    _claim(
                        "claim-po1",
                        "Parent window closed steadily",
                        facts=["fact:synthetic-1"],
                    )
                ],
                "actions": [],
            },
            {
                "type": "working",
                "claims": [
                    _claim(
                        "claim-pw1",
                        "Parent loops held together",
                        facts=["fact:synthetic-2"],
                    )
                ],
                "actions": [],
            },
            {"type": "not_working", "claims": [], "actions": []},
            {
                "type": "actions",
                "claims": [],
                "actions": [
                    _action(
                        "act-parent-1",
                        week_commitment,
                        _iso(30, 14, 0),
                        _iso(30, 15, 0),
                    )
                ],
            },
        ],
    }


def _since_last_section() -> dict[str, Any]:
    return {
        "type": "since_last",
        "claims": [
            _claim(
                "claim-s1",
                "Programming is down 10 since the parent briefing",
                refs=[_ref("screen_hours.Work/Programming", -10.0)],
            ),
            _claim(
                "claim-s2",
                "Walk total is unchanged since the parent briefing",
                refs=[_ref("tag_hours.iki-walk", 0.0)],
            ),
            _claim(
                "claim-s3",
                "Pushes rose by 1 since the parent briefing",
                refs=[_ref("github.push.count", 1.0)],
            ),
        ],
        "actions": [],
    }


def base_case_with_parent(profile: str) -> Case:
    """Passing briefing with a parent pair and delta-correct ``since_last``.

    Current metrics are ``{Programming 90, walk 30, pushes 3}``; parent
    metrics are ``{Programming 100, walk 30, pushes 2}``, so the deltas are
    ``-10``, ``0``, ``+1`` (negative and zero deltas included).
    """
    briefing = _base_briefing(profile, f"brf-{profile}-child")
    parent_id = f"brf-{profile}-parent"
    briefing["parent_briefing_id"] = parent_id
    sections = briefing["sections"]
    sections.insert(1, _since_last_section())
    parent_metrics = MetricSnapshot(
        values={
            "screen_hours.Work/Programming": 100.0,
            "tag_hours.iki-walk": 30.0,
            "github.push.count": 2.0,
        }
    )
    base_context = _base_context()
    context = base_context.model_copy(
        update={
            "parent_briefing": Briefing.model_validate(_parent_briefing(profile)),
            "parent_metrics": parent_metrics,
        }
    )
    return Case(
        name=f"base-{profile}-with-parent",
        briefing=briefing,
        context=context,
        expected=(),
    )


# ---------------------------------------------------------------------------
# Helpers for building mutants and known-good cases.
# ---------------------------------------------------------------------------


def _section(briefing: dict[str, Any], section_type: str) -> dict[str, Any]:
    return next(s for s in briefing["sections"] if s["type"] == section_type)


def _get_claim(section: dict[str, Any], claim_id: str) -> dict[str, Any]:
    return next(c for c in section["claims"] if c["id"] == claim_id)


def _action_in(section: dict[str, Any], action_id: str) -> dict[str, Any]:
    return next(a for a in section["actions"] if a["id"] == action_id)


Mutator = Callable[[dict[str, Any], GateContext], GateContext]


def _mutate(
    case: Case,
    name: str,
    expected: tuple[str, ...],
    fn: Mutator,
) -> Case:
    briefing = copy.deepcopy(case.briefing)
    context = fn(briefing, case.context)
    return Case(name=name, briefing=briefing, context=context, expected=expected)


def _build_mutants() -> tuple[Case, ...]:
    base = base_case("builder")
    parented = base_case_with_parent("builder")

    def m1(briefing: dict[str, Any], context: GateContext) -> GateContext:
        _section(briefing, "working")["type"] = "mystery"
        return context

    def m2(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["sections"] = [
            s for s in briefing["sections"] if s["type"] != "since_last"
        ]
        return context

    def m3(briefing: dict[str, Any], context: GateContext) -> GateContext:
        _section(briefing, "actions")["actions"].extend(
            [
                _action(
                    "act-extra-1",
                    "cm-builder-followup",
                    _iso(31, 16, 30),
                    _iso(31, 17, 0),
                ),
                _action(
                    "act-extra-2",
                    "cm-builder-appendix",
                    _iso(31, 19, 30),
                    _iso(31, 20, 30),
                ),
            ]
        )
        return context

    def m4(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " Contact synthetic@example.invalid for notes"
        return context

    def m5(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " Rotate ghp_abcdefghijklmnop now"
        return context

    def m6(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += f" Notes mention {SYNTHETIC_TERM} here"
        return context.model_copy(update={"private_terms": (SYNTHETIC_TERM,)})

    def m7(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " Resting average is 62 beats"
        claim["metric_refs"] = [_ref("raw.health.resting_hr", 62.0)]
        values = dict(context.metrics.values)
        values["raw.health.resting_hr"] = 62.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m8(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["slot"] = _iso(31, 9, 0)
        return context

    def m9(briefing: dict[str, Any], context: GateContext) -> GateContext:
        action = _action_in(_section(briefing, "actions"), "act-build-1")
        action["proposed_start"] = _iso(31, 15, 15)
        action["proposed_end"] = _iso(31, 15, 45)
        return context

    def m10(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["fact_ids"] = ["fact:synthetic-missing"]
        return context

    def m11(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Scored 42 points in the synthetic trial"
        return context

    def m12(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushed 99 tasks in the synthetic trial"
        claim["metric_refs"] = [_ref("github.push.count", 99.0)]
        return context

    def m13(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "since_last"), "claim-s1")
        claim["text"] = "Programming total moved by 11 since the parent briefing"
        claim["metric_refs"] = [_ref("screen_hours.Work/Programming", -11.0)]
        return context

    def m14(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["fact_ids"] = []
        claim["metric_refs"] = []
        return context

    def m15(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["slot"] = _iso(31, 18, 0)
        return context

    def m16(briefing: dict[str, Any], context: GateContext) -> GateContext:
        _section(briefing, "overall_state")["claims"] = []
        return context

    def m17(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["parent_briefing_id"] = None
        briefing["sections"] = [
            s for s in briefing["sections"] if s["type"] != "since_last"
        ]
        return context

    def m18(briefing: dict[str, Any], context: GateContext) -> GateContext:
        assert context.parent_briefing is not None
        parent = context.parent_briefing.model_copy(update={"profile_id": "disconnect"})
        return context.model_copy(update={"parent_briefing": parent})

    def m21(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Feed count reached 3"
        claim["metric_refs"] = [_ref("github.push.count", 3.0)]
        return context

    def m22(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes reached 3 in earlier"
        claim["metric_refs"] = [_ref("period.last.pushes", 3.0)]
        values = dict(context.metrics.values)
        values["period.last.pushes"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m23(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes fell from 1 in earlier to 3 in last"
        claim["metric_refs"] = [
            _ref("period.earlier.pushes", 1.0),
            _ref("period.last.pushes", 3.0),
        ]
        values = dict(context.metrics.values)
        values["period.earlier.pushes"] = 1.0
        values["period.last.pushes"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m24(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "since_last"), "claim-s1")
        claim["text"] = "Programming rose by 10 since the parent briefing"
        claim["metric_refs"] = [_ref("screen_hours.Work/Programming", -10.0)]
        return context

    def m25(briefing: dict[str, Any], context: GateContext) -> GateContext:
        action = _action_in(_section(briefing, "actions"), "act-build-1")
        action["commitment_id"] = "cm-builder-absent"
        return context

    def m26(briefing: dict[str, Any], context: GateContext) -> GateContext:
        action = _action_in(_section(briefing, "actions"), "act-build-1")
        action["commitment_id"] = "cm-disconnect-walk"
        return context

    def m27(briefing: dict[str, Any], context: GateContext) -> GateContext:
        action = _action_in(_section(briefing, "actions"), "act-build-1")
        action["text"] = "Build the synthetic parser sketch with extra words"
        return context

    def m28(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " You should log the synthetic result"
        return context

    def m29(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " You must log the synthetic result"
        return context

    def m30(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] += " Notes mention medication timing here"
        return context

    def m31(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "You did ten pushes in the synthetic trial"
        return context

    def m32(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Logged May 2000 steps in the synthetic trial"
        return context

    def m33(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes reached 3 while the feed held 5"
        claim["metric_refs"] = [
            _ref("github.push.count", 3.0),
            _ref("feed.item.count", 5.0),
        ]
        values = dict(context.metrics.values)
        values["feed.item.count"] = 5.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m34(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Completed 3 synthetic tasks"
        claim["metric_refs"] = [_ref("agg.tasks_done", 3.0)]
        values = dict(context.metrics.values)
        values["agg.tasks_done"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m35(briefing: dict[str, Any], context: GateContext) -> GateContext:
        return context.model_copy(update={"commitments_available": False})

    def m36(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes rose to 3 in last"
        claim["metric_refs"] = [_ref("period.last.pushes", 3.0)]
        values = dict(context.metrics.values)
        values["period.last.pushes"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m37(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes fell from 3 in earlier to 1 in prior and to 2 in last"
        claim["metric_refs"] = [
            _ref("period.earlier.pushes", 3.0),
            _ref("period.prior.pushes", 1.0),
            _ref("period.last.pushes", 2.0),
        ]
        values = dict(context.metrics.values)
        values["period.earlier.pushes"] = 3.0
        values["period.prior.pushes"] = 1.0
        values["period.last.pushes"] = 2.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    def m38(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "working"), "claim-w1")
        claim["text"] = "Pushes reached 3 in last"
        claim["metric_refs"] = [_ref("github.push.count", 3.0)]
        return context

    def m19(briefing: dict[str, Any], context: GateContext) -> GateContext:
        assert context.parent_briefing is not None
        parent = context.parent_briefing.model_copy(
            update={"subject_id": "subject-other"}
        )
        return context.model_copy(update={"parent_briefing": parent})

    def m20(briefing: dict[str, Any], context: GateContext) -> GateContext:
        assert context.parent_briefing is not None
        parent = context.parent_briefing.model_copy(
            update={"slot": datetime.fromisoformat(briefing["slot"])}
        )
        return context.model_copy(update={"parent_briefing": parent})

    return (
        _mutate(base, "M1-unknown-section", ("L0_UNKNOWN_SECTION",), m1),
        _mutate(
            parented,
            "M2-missing-since-last",
            ("L1B_MISSING_SINCE_LAST",),
            m2,
        ),
        _mutate(base, "M3-action-count", ("L0_ACTION_COUNT",), m3),
        _mutate(base, "M4-pii-email", ("L1_PII",), m4),
        _mutate(base, "M5-secret-token", ("L1_SECRET",), m5),
        _mutate(base, "M6-private-term", ("L1_PRIVATE_TERM",), m6),
        _mutate(base, "M7-raw-value", ("L1_RAW_VALUE",), m7),
        _mutate(
            base,
            "M8-slot-outside-hours",
            ("L1_SLOT_OUTSIDE_ALLOWED_HOURS",),
            m8,
        ),
        _mutate(
            base,
            "M9-action-in-busy",
            ("L1_ACTION_IN_BUSY_INTERVAL",),
            m9,
        ),
        _mutate(base, "M10-unknown-fact", ("L1B_UNKNOWN_FACT",), m10),
        _mutate(
            base,
            "M11-number-without-ref",
            ("L1B_NUMBER_WITHOUT_METRIC_REF",),
            m11,
        ),
        _mutate(
            base,
            "M12-metric-mismatch",
            ("L1B_METRIC_VALUE_MISMATCH",),
            m12,
        ),
        _mutate(parented, "M13-delta-mismatch", ("L1B_DELTA_MISMATCH",), m13),
        _mutate(
            base,
            "M14-claim-without-evidence",
            ("L1B_CLAIM_WITHOUT_EVIDENCE",),
            m14,
        ),
        _mutate(base, "M15-action-before-slot", ("L1_ACTION_BEFORE_SLOT",), m15),
        _mutate(base, "M16-empty-overall-state", ("L0_EMPTY_SECTION",), m16),
        _mutate(
            parented,
            "M17-child-without-parent-id",
            ("L1B_PARENT_MISMATCH",),
            m17,
        ),
        _mutate(
            parented,
            "M18-parent-profile-mismatch",
            ("L1B_PARENT_MISMATCH",),
            m18,
        ),
        _mutate(
            parented,
            "M19-parent-subject-mismatch",
            ("L1B_PARENT_MISMATCH",),
            m19,
        ),
        _mutate(parented, "M20-parent-slot-not-before", ("L1B_PARENT_MISMATCH",), m20),
        _mutate(base, "M21-swapped-metric-label", ("L1B_METRIC_LABEL_MISSING",), m21),
        _mutate(base, "M22-wrong-period-word", ("L1B_PERIOD_WORD_MISSING",), m22),
        _mutate(base, "M23-reversed-direction", ("L1B_DIRECTION_MISMATCH",), m23),
        _mutate(
            parented, "M24-reversed-delta-direction", ("L1B_DIRECTION_MISMATCH",), m24
        ),
        _mutate(base, "M25-action-not-committed", ("L1_ACTION_NOT_COMMITTED",), m25),
        _mutate(base, "M26-action-cross-profile", ("L1_ACTION_NOT_COMMITTED",), m26),
        _mutate(base, "M27-action-text-mismatch", ("L1_ACTION_TEXT_MISMATCH",), m27),
        _mutate(base, "M28-advice-should", ("L1_ADVICE",), m28),
        _mutate(base, "M29-advice-must", ("L1_ADVICE",), m29),
        _mutate(base, "M30-advice-medication", ("L1_ADVICE",), m30),
        _mutate(
            base,
            "M31-spelled-number-without-ref",
            ("L1B_NUMBER_WITHOUT_METRIC_REF",),
            m31,
        ),
        _mutate(
            base,
            "M32-date-number-without-ref",
            ("L1B_NUMBER_WITHOUT_METRIC_REF",),
            m32,
        ),
        _mutate(base, "M33-too-many-metrics", ("L1B_TOO_MANY_METRICS",), m33),
        _mutate(base, "M34-unknown-metric-family", ("L1B_METRIC_LABEL_UNKNOWN",), m34),
        _mutate(
            base,
            "M35-commitments-unavailable",
            ("L1_COMMITMENTS_UNAVAILABLE",),
            m35,
        ),
        _mutate(base, "M36-direction-single-ref", ("L1B_DIRECTION_MISMATCH",), m36),
        _mutate(base, "M37-direction-mixed-changes", ("L1B_DIRECTION_MISMATCH",), m37),
        _mutate(base, "M38-uncited-period-word", ("L1B_PERIOD_WORD_MISSING",), m38),
    )


def _install(
    briefing: dict[str, Any],
    context: GateContext,
    text: str,
    refs: list[tuple[str, float]],
    claim_id: str = "claim-w1",
) -> GateContext:
    """Point the working claim at ``text``/``refs`` and price them."""
    claim = _get_claim(_section(briefing, "working"), claim_id)
    claim["text"] = text
    claim["fact_ids"] = []
    claim["metric_refs"] = [_ref(metric_id, value) for metric_id, value in refs]
    values = dict(context.metrics.values)
    for metric_id, value in refs:
        values[metric_id] = value
    return context.model_copy(update={"metrics": MetricSnapshot(values=values)})


def _install_fact_only(
    briefing: dict[str, Any],
    context: GateContext,
    text: str,
    fact_id: str = "fact:synthetic-1",
    claim_id: str = "claim-w1",
) -> GateContext:
    """Point the working claim at fact-only ``text`` citing ``fact_id``."""
    claim = _get_claim(_section(briefing, "working"), claim_id)
    claim["text"] = text
    claim["fact_ids"] = [fact_id]
    claim["metric_refs"] = []
    return context


def _with_local_fact(context: GateContext, fact_id: str, statement: str) -> GateContext:
    """Add a case-local fact carrying ``statement`` to a copy of ``context``."""
    from framework.schemas.core import Fact

    fact = Fact.model_validate(
        {
            "id": fact_id,
            "subject_id": SUBJECT_ID,
            "window": {"start": _iso(30, 0, 0), "end": _iso(31, 12, 0)},
            "statement": statement,
            "evidence": ["synthetic log"],
            "tier": "public",
        }
    )
    facts = dict(context.facts)
    facts[fact_id] = fact
    return context.model_copy(update={"facts": facts})


def _redteam_mutants() -> tuple[Case, ...]:
    """Ticket 10b: one mutant per `real_hole` attack plus R1 and R3."""
    from framework.briefing.labels import metric_label_binding as _binding

    assert _binding is not None  # keep the labels import live if unused below
    cases: list[Case] = []

    def add(
        name: str, expected: tuple[str, ...], text: str, refs: list[tuple[str, float]]
    ) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            return _install(briefing, context, text, refs)

        cases.append(_mutate(base, name, expected, fn))

    push3 = ("period.earlier.pushes", 3.0)
    push1 = ("period.prior.pushes", 1.0)
    push0 = ("period.last.pushes", 0.0)
    prog475 = ("period.prior.screen_hours.Work/Programming", 4.75)
    prog175 = ("period.last.screen_hours.Work/Programming", 1.75)

    add(
        "M39-negated-direction",
        ("L1B_NEGATED_CLAIM",),
        "Pushes did not fall from 3 in earlier to 1 in prior and to 0 in last.",
        [push3, push1, push0],
    )
    add(
        "M40-negated-zero",
        ("L1B_NEGATED_CLAIM",),
        "Pushes in last were not 0.",
        [push0],
    )
    add(
        "M41-growth-synonym",
        ("L1B_DIRECTION_MISMATCH",),
        "Pushes showed growth from 3 in earlier to 0 in last.",
        [push3, push0],
    )
    add(
        "M42-exceeded-synonym",
        ("L1B_DIRECTION_MISMATCH",),
        "Programming screen hours in last exceeded those in prior.",
        [prog475, prog175],
    )
    add(
        "M43-spanish-direction",
        ("L1_CLAIM_LANGUAGE",),
        "Pushes subieron from 3 in earlier to 0 in last.",
        [push3, push0],
    )
    add(
        "M44-doubled",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Work/Programming screen hours doubled from 4.75 in prior to 1.75 in last.",
        [prog475, prog175],
    )
    add(
        "M45-half",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes fell by half from 3 in earlier to 0 in last.",
        [push3, push0],
    )
    add(
        "M46-vulgar-fraction",
        (
            "L1B_NUMBER_WITHOUT_METRIC_REF",
            "L1B_UNVERIFIABLE_QUANTITY",
            "L1B_VALUE_PERIOD_MISMATCH",
        ),
        "Pushes in last were \u00be of the pushes in earlier.",
        [push3, push0],
    )
    add(
        "M47-tally-marks",
        ("L1B_COMPARISON_WORD_UNKNOWN", "L1B_UNVERIFIABLE_QUANTITY"),
        "Pushes in last reached this tally: ||||, with earlier named for comparison.",
        [push3, push0],
    )
    add(
        "M48-roman-numeral",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last reached IV.",
        [push0],
    )
    add(
        "M49-french-number",
        ("L1_CLAIM_LANGUAGE",),
        "Pushes in last reached quatre.",
        [push0],
    )
    add(
        "M50-digit-ordinal",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last hit their 99th push.",
        [push0],
    )
    add(
        "M51-clock-duration",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Programming screen hours in last ran for 14:30.",
        [prog175],
    )
    add(
        "M52-invalid-clock",
        ("L1B_COMPARISON_WORD_UNKNOWN", "L1B_NUMBER_WITHOUT_METRIC_REF"),
        "Pushes split 3:99 between earlier and last.",
        [push3, push0],
    )
    add(
        "M53-tenfold",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last were tenfold the pushes in earlier.",
        [push3, push0],
    )
    add(
        "M54-a-couple",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last came to a couple.",
        [push0],
    )
    add(
        "M55-one-oh",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last reached one-oh.",
        [push0],
    )
    add(
        "M56-rounded-integer",
        ("L1B_NUMBER_WITHOUT_METRIC_REF",),
        "Programming screen hours were 5 in prior.",
        [prog475],
    )
    add(
        "M57-wrong-unit",
        ("L1B_UNIT_MISMATCH",),
        "Programming screen hours in last totalled 1.75 minutes.",
        [prog175],
    )
    add(
        "M58-period-compound",
        ("L1B_PERIOD_WORD_MISSING",),
        "Pushes in the second-to-last window reached 0.",
        [push0],
    )
    base59 = base_case("builder")

    def m59_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = _install(
            briefing,
            context,
            "Media/Video Programming screen hours in last reached 1.75.",
            [prog175],
        )
        values = dict(ctx.metrics.values)
        values["period.last.screen_hours.Media/Video"] = 4.0
        return ctx.model_copy(update={"metrics": MetricSnapshot(values=values)})

    cases.append(
        _mutate(
            base59,
            "M59-conflicting-category",
            ("L1B_METRIC_LABEL_MISMATCH",),
            m59_fn,
        )
    )
    add(
        "M60-rank-ordinal",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes ranked first in last, ahead of earlier and prior.",
        [push3, push1, push0],
    )
    add(
        "M61-rate-word",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last happened daily.",
        [push0],
    )

    def _fact(
        name: str,
        expected: tuple[str, ...],
        text: str,
        private_terms: tuple[str, ...] = (),
    ) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            ctx = _install_fact_only(briefing, context, text)
            if private_terms:
                return ctx.model_copy(update={"private_terms": private_terms})
            return ctx

        cases.append(_mutate(base, name, expected, fn))

    _fact(
        "M62-hidden-char-term",
        ("L1_PRIVATE_TERM", "L1_UNSAFE_TEXT"),
        "The notes mention quetzal\u200bgarden today.",
        (SYNTHETIC_TERM,),
    )
    _fact(
        "M63-fullwidth-term",
        ("L1_PRIVATE_TERM",),
        "The notes mention \uff51uetzal-garden today.",
        (SYNTHETIC_TERM,),
    )
    _fact(
        "M64-spaced-term",
        ("L1_PRIVATE_TERM",),
        "The notes spell q u e t z a l - g a r d e n today.",
        (SYNTHETIC_TERM,),
    )
    _fact(
        "M65-confusable-term",
        ("L1_CLAIM_LANGUAGE", "L1_PRIVATE_TERM"),
        "The notes mention quetz\u0430l-garden today.",
        (SYNTHETIC_TERM,),
    )
    _fact(
        "M66-punctuated-literal",
        ("L1_RAW_VALUE",),
        "The calendar note reads Invented Calendar, Title Zqx today.",
    )
    _fact(
        "M67-deontic-phrase",
        ("L1_ADVICE",),
        "You ought to ship one small change during the next free hour.",
    )
    _fact(
        "M68-bare-imperative",
        ("L1_ADVICE",),
        "Ship one small change during the next free hour.",
    )
    _fact(
        "M69-rhetorical-question",
        ("L1_ADVICE",),
        "Why not ship a small change during the next free hour?",
    )
    _fact(
        "M70-french-imperative",
        ("L1_CLAIM_LANGUAGE",),
        "Exp\u00e9diez un petit changement pendant la prochaine heure libre.",
    )
    add(
        "M71-crash-decimals",
        ("L1B_NUMBER_WITHOUT_METRIC_REF",),
        "Pushes in earlier were 3.000000000000000000000000000000.",
        [push3],
    )
    add(
        "M72-swapped-periods",
        ("L1B_VALUE_PERIOD_MISMATCH",),
        "Pushes fell from 1 in last to 0 in prior.",
        [push1, push0],
    )
    return tuple(cases)


def _round2_mutants() -> tuple[Case, ...]:
    """Ticket 10b: one mutant per round-2 class and leftover round-1 rule.

    Own sentences in the same synthetic context (``quetzal-garden``,
    the ``Invented Calendar Title Zqx`` literal, the example commitments).
    Each pins the exact ordered code list the gate emits today.
    """
    cases: list[Case] = []

    def add(
        name: str, expected: tuple[str, ...], text: str, refs: list[tuple[str, float]]
    ) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            return _install(briefing, context, text, refs)

        cases.append(_mutate(base, name, expected, fn))

    push3 = ("period.earlier.pushes", 3.0)
    push1 = ("period.prior.pushes", 1.0)
    push0 = ("period.last.pushes", 0.0)
    prog475 = ("period.prior.screen_hours.Work/Programming", 4.75)
    prog175 = ("period.last.screen_hours.Work/Programming", 1.75)
    screen90 = ("screen_hours.Work/Programming", 90.0)

    def add_fact(
        name: str,
        expected: tuple[str, ...],
        text: str,
        statement: str,
        private_terms: tuple[str, ...] = (),
    ) -> None:
        base = base_case("builder")
        fact_id = "fact:synthetic-local"

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            ctx = _with_local_fact(context, fact_id, statement)
            if private_terms:
                ctx = ctx.model_copy(update={"private_terms": private_terms})
            return _install_fact_only(briefing, ctx, text, fact_id)

        cases.append(_mutate(base, name, expected, fn))

    def add_term_fact(
        name: str,
        expected: tuple[str, ...],
        text: str,
        private_terms: tuple[str, ...],
    ) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            ctx = context.model_copy(update={"private_terms": private_terms})
            return _install_fact_only(briefing, ctx, text)

        cases.append(_mutate(base, name, expected, fn))

    add(
        "M73-N01-value-beside-wrong-period",
        ("L1B_VALUE_PERIOD_MISMATCH",),
        "Programming screen hours fell from 1.75 screen hours in prior "
        "to 4.75 screen hours in last.",
        [prog475, prog175],
    )
    add(
        "M74-R09-spelled-beside-wrong-period",
        ("L1B_VALUE_PERIOD_MISMATCH",),
        "Pushes sank from one in last to zero in prior.",
        [push1, push0],
    )
    add(
        "M75-N07-wrong-duration-word",
        ("L1B_UNIT_MISMATCH",),
        "Programming screen hours in last were 1.75 fortnights.",
        [prog175],
    )
    add(
        "M76-R11-magnitude-word",
        ("L1B_UNIT_MISMATCH",),
        "Programming screen hours in last were 1.75 gigawatts.",
        [prog175],
    )
    add(
        "M77-R12-glued-letter",
        ("L1B_UNIT_MISMATCH", "L1B_UNVERIFIABLE_QUANTITY"),
        "Pushes in earlier were 3x.",
        [push3],
    )
    add(
        "M78-R13-trailing-qualifier",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in earlier were about 3 or so.",
        [push3],
    )
    add(
        "M79-R14-single",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "A single push landed in earlier.",
        [push3],
    )
    add(
        "M80-R15-lower-roman",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last reached xiv.",
        [push0],
    )
    add(
        "M81-R16-share-word",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Most pushes landed in last.",
        [push0],
    )
    add(
        "M82-R17-universal-label",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Each push landed in last.",
        [push0],
    )
    add(
        "M83-R18-negated-one-word",
        ("L1B_NEGATED_CLAIM", "L1B_NUMBER_WITHOUT_METRIC_REF"),
        "Pushes in last ended non-zero.",
        [push0],
    )
    add_fact(
        "M84-R19-fact-both-directions",
        ("L1B_DIRECTION_MISMATCH",),
        "Pushes fell in prior and climbed in last.",
        "Pushes fell in prior and dropped in last.",
    )
    add(
        "M85-R20-hyphen-direction",
        ("L1B_DIRECTION_MISMATCH",),
        "Pushes in last stood higher-than-ever at 0.",
        [push0],
    )
    add(
        "M86-R21-period-other-sense",
        ("L1B_PERIOD_WORD_MISSING",),
        "Pushes stood at 0 at last.",
        [push0],
    )
    add(
        "M87-R22-spaced-negation",
        ("L1_UNSAFE_TEXT",),
        "Pushes in last stood at N O T 0.",
        [push0],
    )
    add_term_fact(
        "M88-R23-punctuated-term",
        ("L1_PRIVATE_TERM",),
        "The notes mention quetzal: garden today.",
        (SYNTHETIC_TERM,),
    )
    add_fact(
        "M89-R24-misspelled-literal",
        ("L1_RAW_VALUE",),
        "The calendar note reads Invented Calender Title Zqx today.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M90-R25-opener-imperative",
        ("L1_ADVICE",),
        "Today launch one small widget.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M91-R26-suggestion-phrase",
        ("L1_ADVICE",),
        "You could polish the widget in the free hour.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M92-R27-commitment-object",
        ("L1_ADVICE",),
        "The synthetic parser sketch is the next move.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M93-R28-strong-verb",
        ("L1_ADVICE",),
        "Finalize the widget.",
        "Synthetic reference log filed under review.",
    )
    add(
        "M94-R32-exactness-limit",
        ("L1B_METRIC_VALUE_MISMATCH",),
        "GitHub pushes reached 9007199254740994.",
        [("github.push.count", 9007199254740994.0)],
    )
    add_fact(
        "M95-R33-and-imperative",
        ("L1_ADVICE",),
        "Pushes fell in last and launch the parser.",
        "Pushes fell in last.",
    )
    add_fact(
        "M96-R34-dash-imperative",
        ("L1_ADVICE",),
        "Pushes fell in last \u2014 launch the parser.",
        "Pushes fell in last.",
    )
    add_fact(
        "M97-R35-hour-is-for",
        ("L1_ADVICE",),
        "This hour is for deep rest.",
        "Synthetic reference log filed under review.",
    )
    base98 = base_case("builder")

    def m98_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = _install(
            briefing,
            context,
            "Pushes were 0 in last, and pull requests were 0 in last.",
            [push0],
        )
        values = dict(ctx.metrics.values)
        values["period.last.prs"] = 9.0
        return ctx.model_copy(update={"metrics": MetricSnapshot(values=values)})

    cases.append(
        _mutate(
            base98,
            "M98-R36-named-not-cited",
            ("L1B_METRIC_LABEL_MISMATCH",),
            m98_fn,
        )
    )
    add(
        "M99-R37-time-word-periodless",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Programming ran 90 this week.",
        [screen90],
    )
    add(
        "M100-R38-scale-word",
        ("L1B_NUMBER_WITHOUT_METRIC_REF",),
        "Pushes reached 3 trillion.",
        [("github.push.count", 3.0)],
    )
    add_term_fact(
        "M101-R39-curly-term",
        ("L1_PRIVATE_TERM",),
        "The notes mention quetzal\u2019garden today.",
        (SYNTHETIC_TERM,),
    )
    add(
        "M102-N12-spelled-ordinal",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last hit the twelfth push.",
        [push0],
    )
    add(
        "M103-N14-tally",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in earlier went push, push, push.",
        [push3],
    )
    add(
        "M104-N08-slash-fraction",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes in last showed 0/3 with earlier at 3.",
        [push3, push0],
    )
    add(
        "M105-N15-range-one-period",
        ("L1B_NUMBER_WITHOUT_METRIC_REF", "L1B_UNVERIFIABLE_QUANTITY"),
        "Pushes in last ranged from 0 to 3.",
        [push0],
    )
    add(
        "M106-N05-wrong-change",
        ("L1B_NUMBER_WITHOUT_METRIC_REF", "L1B_VALUE_PERIOD_MISMATCH"),
        "Pushes fell by 2 from 1 in prior to 0 in last.",
        [push1, push0],
    )
    add(
        "M107-R41-periods-wrong-way",
        ("L1B_DIRECTION_MISMATCH",),
        "Programming stood lower in the prior period at 4.75 hours "
        "than in the last period at 1.75 hours.",
        [prog475, prog175],
    )
    add(
        "M108-N04-joined-label",
        ("L1B_METRIC_LABEL_MISSING", "L1B_PERIOD_WORD_MISSING"),
        "WorkProgramming screen hours in last were 90.",
        [screen90],
    )
    add(
        "M109-N06-percent-word",
        ("L1B_PERIOD_WORD_MISSING", "L1B_UNIT_MISMATCH"),
        "Programming screen hours in last were 90 percent.",
        [screen90],
    )
    add(
        "M110-R52-digit-ordinal-noun",
        ("L1B_UNVERIFIABLE_QUANTITY",),
        "Pushes reached the 3rd page in earlier.",
        [push3],
    )
    # The li-fold and rotation arms only run for terms without a hyphen,
    # so these two carry the spaced variant the round-2 rows introduced.
    add_term_fact(
        "M111-N22-lookalike-I",
        ("L1_PRIVATE_TERM",),
        "The notes mention QuetzaIgarden today.",
        ("quetzal garden",),
    )
    add_term_fact(
        "M112-N23-halves-swapped",
        ("L1_PRIVATE_TERM",),
        "The archive cites gardenquetzal today.",
        ("quetzal garden",),
    )
    add_fact(
        "M113-N24-phonetic-term",
        ("L1_UNSAFE_TEXT",),
        "The notes read Quebec Uniform Echo Tango Zulu Alfa Lima today.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M114-N25-stretched-literal",
        ("L1_RAW_VALUE",),
        "The calendar note reads Invented in the early Calendar Title Zqx today.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M115-N26-dutch",
        ("L1_CLAIM_LANGUAGE",),
        "Stuur een kleine update in het volgende vrije uur.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M116-N28-question-no-mark",
        ("L1_ADVICE",),
        "Would the free hour suit a short build.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M117-R44-link",
        ("L1_UNSAFE_TEXT",),
        "The full log sits at https://example.invalid/synthetic-log.",
        "Synthetic reference log filed under review.",
    )
    add_fact(
        "M118-R45-no-letters-digits",
        ("L1_UNSAFE_TEXT",),
        "- - -",
        "Synthetic reference log filed under review.",
    )
    return tuple(cases)


def _since_last_mutants() -> tuple[Case, ...]:
    """Ticket 10c: the since_last wording mutant, apart from the round-2 set."""
    cases: list[Case] = []

    def m119(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "since_last"), "claim-s3")
        claim["text"] = "Prs rose by 3 in the last period."
        claim["metric_refs"] = [_ref("period.last.prs", 3.0)]
        values = dict(context.metrics.values)
        values["period.last.prs"] = 27.0
        ctx = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
        parent_values = dict(ctx.parent_metrics.values)  # type: ignore[union-attr]
        parent_values["period.last.prs"] = 24.0
        return ctx.model_copy(
            update={"parent_metrics": MetricSnapshot(values=parent_values)}
        )

    cases.append(
        _mutate(
            base_case_with_parent("builder"),
            "M119-since-last-period-phrase",
            ("L1B_SINCE_LAST_WORDING",),
            m119,
        )
    )
    return tuple(cases)


MUTANTS: tuple[Case, ...] = (
    _build_mutants() + _redteam_mutants() + _round2_mutants() + _since_last_mutants()
)


# ---------------------------------------------------------------------------
# Ticket 24: phone misses (outside MUTANTS so its counts stay 119 and 57).
# ---------------------------------------------------------------------------


def _phone_case(
    profile: str,
    name: str,
    text: str,
    metric_id: str,
    ref_value: float,
    current: float,
    parent: float,
) -> Case:
    """One T24 case in M119's shape: sentence, change, current and parent.

    The sentence, its change and both values are real for the two public
    GitHub counts and made up in the same shape for the four screen hours;
    the rest of each briefing is made up either way.
    """
    base = base_case_with_parent(profile)

    def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "since_last"), "claim-s3")
        claim["text"] = text
        claim["metric_refs"] = [_ref(metric_id, ref_value)]
        values = dict(context.metrics.values)
        values[metric_id] = current
        ctx = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
        parent_values = dict(ctx.parent_metrics.values)  # type: ignore[union-attr]
        parent_values[metric_id] = parent
        return ctx.model_copy(
            update={"parent_metrics": MetricSnapshot(values=parent_values)}
        )

    return _mutate(base, name, ("L1B_SINCE_LAST_WORDING",), fn)


PHONE_CASES: tuple[Case, ...] = (
    _phone_case(
        "builder",
        "T24-2030-corrected-builder-period-last-pushes",
        "Pushes rose 1 in the last period.",
        "period.last.pushes",
        1.0,
        1.0,
        0.0,
    ),
    _phone_case(
        "builder",
        "T24-2230-builder-period-last-screen-hours-code",
        "Code fell -2.00 hours in the last period.",
        "period.last.screen_hours.code",
        -2.0,
        3.0,
        5.0,
    ),
    _phone_case(
        "disconnect",
        "T24-2230-disconnect-period-last-screen-hours-ai",
        "AI rose 2.00 hours in the last period.",
        "period.last.screen_hours.ai",
        2.0,
        6.0,
        4.0,
    ),
    _phone_case(
        "builder",
        "T24-2230-corrected-builder-period-last-screen-hours-code",
        "Code fell 2.00 hours in the last period.",
        "period.last.screen_hours.code",
        -2.0,
        3.0,
        5.0,
    ),
    _phone_case(
        "disconnect",
        "T24-2230-corrected-disconnect-period-last-screen-hours-ai",
        "AI rose 2.00 hours in the last period.",
        "period.last.screen_hours.ai",
        2.0,
        6.0,
        4.0,
    ),
)


@dataclass(frozen=True)
class PhoneMiss:
    """One real miss on a delivered card: its card label and its case.

    ``shown`` marks whether the trust page shows the entry in its phone
    table (the two public GitHub counts) or covers it with the sentence
    about the four screen-hour misses (the four made-up-value cases).
    """

    card: str
    case: Case
    shown: bool


_PHONE_M119 = next(c for c in MUTANTS if c.name == "M119-since-last-period-phrase")

PHONE_MISSES: tuple[PhoneMiss, ...] = (
    PhoneMiss(card="15:30", case=_PHONE_M119, shown=True),
    PhoneMiss(card="20:30 corrected", case=PHONE_CASES[0], shown=True),
    PhoneMiss(card="22:30", case=PHONE_CASES[1], shown=False),
    PhoneMiss(card="22:30", case=PHONE_CASES[2], shown=False),
    PhoneMiss(card="22:30 corrected", case=PHONE_CASES[3], shown=False),
    PhoneMiss(card="22:30 corrected", case=PHONE_CASES[4], shown=False),
)

#: Entries the trust page shows in its phone table.
PHONE_TABLE_MISSES: tuple[PhoneMiss, ...] = tuple(
    miss for miss in PHONE_MISSES if miss.shown
)

#: Entries the trust page covers with its screen-hour sentence.
PHONE_COVERED_MISSES: tuple[PhoneMiss, ...] = tuple(
    miss for miss in PHONE_MISSES if not miss.shown
)


def _build_known_good() -> tuple[Case, ...]:
    g1 = base_case("builder")
    g1 = Case(
        name="G1-builder-first",
        briefing=g1.briefing,
        context=g1.context,
        expected=(),
    )

    parented_builder = base_case_with_parent("builder")
    g2 = Case(
        name="G2-builder-with-parent",
        briefing=parented_builder.briefing,
        context=parented_builder.context,
        expected=(),
    )

    disconnect = base_case("disconnect")
    g3 = Case(
        name="G3-disconnect-first",
        briefing=disconnect.briefing,
        context=disconnect.context,
        expected=(),
    )

    def g4_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"].append(
            _claim(
                "claim-wpct",
                "Busy list is half done at 50% in the synthetic window",
                facts=["fact:synthetic-1"],
                refs=[_ref("calendar.busy_hours", 50.0)],
            )
        )
        working["claims"].append(
            _claim(
                "claim-wdec",
                "Reading pages averaged 7.5 lines",
                facts=["fact:synthetic-2"],
                refs=[_ref("screen_hours.Reading", 7.5)],
            )
        )
        values = dict(context.metrics.values)
        values["calendar.busy_hours"] = 50.0
        values["screen_hours.Reading"] = 7.5
        parent_values = dict(context.parent_metrics.values)  # type: ignore[union-attr]
        parent_values["calendar.busy_hours"] = 40.0
        parent_values["screen_hours.Reading"] = 7.0
        return context.model_copy(
            update={
                "metrics": MetricSnapshot(values=values),
                "parent_metrics": MetricSnapshot(values=parent_values),
            }
        )

    parented_disconnect = base_case_with_parent("disconnect")
    g4 = _mutate(parented_disconnect, "G4-disconnect-parent-pct-dec", (), g4_fn)

    g5_base = base_case("builder")
    g5 = Case(
        name="G5-slot-at-open",
        briefing=g5_base.briefing,
        context=g5_base.context,
        expected=(),
    )

    def g6_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["slot"] = _iso(31, 21, 0)
        _section(briefing, "actions")["actions"] = [
            _action("act-eve-1", "cm-builder-review", _iso(31, 21, 0), _iso(31, 22, 0)),
            _action(
                "act-eve-2", "cm-builder-checkin", _iso(31, 23, 0), _iso(31, 23, 30)
            ),
        ]
        return context.model_copy(
            update={
                "busy_intervals": (
                    TimeInterval(start=_iso(31, 22, 0), end=_iso(31, 23, 0)),  # type: ignore[arg-type]
                ),
            }
        )

    g6 = _mutate(base_case("builder"), "G6-evening-boundary-touch", (), g6_fn)

    def g7_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        _section(briefing, "actions")["actions"].pop()
        return context

    g7 = _mutate(base_case("builder"), "G7-one-action", (), g7_fn)

    def g8_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        _section(briefing, "actions")["actions"].append(
            _action(
                "act-third-1",
                "cm-builder-reference",
                _iso(31, 19, 30),
                _iso(31, 20, 30),
            )
        )
        return context

    g8 = _mutate(base_case("builder"), "G8-three-actions", (), g8_fn)

    def g9_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-d1",
                "Reviewed on 2026-10-31 at 14:30",
                facts=["fact:synthetic-1"],
            ),
            _claim(
                "claim-d2",
                "Notes from Oct 30 look steady",
                facts=["fact:synthetic-2"],
            ),
            _claim(
                "claim-d3",
                "The 1st draft followed the 2nd review",
                facts=["fact:synthetic-1"],
            ),
            _claim(
                "claim-d4",
                "See fact:212 for the synthetic log",
                facts=["fact:212"],
            ),
            _claim(
                "claim-d5",
                "Planned for May 9",
                facts=["fact:synthetic-1"],
            ),
            _claim(
                "claim-d6",
                "Notes from the 3rd session",
                facts=["fact:synthetic-2"],
            ),
        ]
        return context

    g9 = _mutate(base_case("builder"), "G9-datetime-prose", (), g9_fn)

    def g10_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-m2a",
                "Programming output reached 90 in the synthetic window",
                facts=["fact:synthetic-1"],
                refs=[_ref("screen_hours.Work/Programming", 90.0)],
            ),
            _claim(
                "claim-m2b",
                "Pushes reached 3 in the synthetic window",
                facts=["fact:synthetic-2"],
                refs=[_ref("github.push.count", 3.0)],
            ),
        ]
        actions = _section(briefing, "actions")["actions"]
        actions[0]["proposed_start"] = _iso(31, 14, 0)
        actions[0]["proposed_end"] = _iso(31, 17, 0)
        actions[1]["proposed_start"] = _iso(31, 17, 0)
        actions[1]["proposed_end"] = _iso(31, 17, 30)
        return context.model_copy(
            update={
                "free_intervals": (
                    TimeInterval(start=_iso(31, 13, 0), end=_iso(31, 15, 0)),  # type: ignore[arg-type]
                    TimeInterval(start=_iso(31, 15, 0), end=_iso(31, 18, 0)),  # type: ignore[arg-type]
                ),
                "busy_intervals": (
                    TimeInterval(start=_iso(31, 19, 0), end=_iso(31, 20, 0)),  # type: ignore[arg-type]
                ),
            }
        )

    g10 = _mutate(base_case("builder"), "G10-two-facts-merged-free", (), g10_fn)

    def g11_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        overall = _section(briefing, "overall_state")
        overall["claims"] = [
            _claim(
                "claim-e1",
                "A task-based routine keeps evenings calm",
                facts=["fact:synthetic-1"],
            ),
            _claim(
                "claim-e2",
                "The plan is risk-free and fully reversible",
                facts=["fact:synthetic-2"],
            ),
        ]
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-e3",
                "Notes from the desk-side reading lamp",
                facts=["fact:synthetic-1"],
            ),
            _claim(
                "claim-e4",
                "She is the standard-bearer of local news",
                facts=["fact:synthetic-2"],
            ),
        ]
        return context

    g11 = _mutate(base_case("builder"), "G11-plain-english", (), g11_fn)

    def g12_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-r1",
                "Programming quality sits at 21.2",
                facts=["fact:synthetic-1"],
                refs=[_ref("screen_hours.Work/Programming", 21.1544)],
            ),
            _claim(
                "claim-r3",
                "Pushes ranged 3-5 across prior and last",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.prior.pushes", 3.0),
                    _ref("period.last.pushes", 5.0),
                ],
            ),
        ]
        values = dict(context.metrics.values)
        values["screen_hours.Work/Programming"] = 21.1544
        values["period.prior.pushes"] = 3.0
        values["period.last.pushes"] = 5.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g12 = _mutate(base_case("builder"), "G12-rounded-absolute-backing", (), g12_fn)

    def g13_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g13",
                "Pushes in last reached 3",
                facts=["fact:synthetic-1"],
                refs=[_ref("period.last.pushes", 3.0)],
            )
        ]
        values = dict(context.metrics.values)
        values["period.last.pushes"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g13 = _mutate(base_case("builder"), "G13-one-period-ref", (), g13_fn)

    def g14_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g14",
                "Pushes fell from 3 in earlier to 1 in last",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.earlier.pushes", 3.0),
                    _ref("period.last.pushes", 1.0),
                ],
            )
        ]
        values = dict(context.metrics.values)
        values["period.earlier.pushes"] = 3.0
        values["period.last.pushes"] = 1.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g14 = _mutate(base_case("builder"), "G14-two-period-refs", (), g14_fn)

    def g15_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g15",
                "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.earlier.pushes", 3.0),
                    _ref("period.prior.pushes", 1.0),
                    _ref("period.last.pushes", 0.0),
                ],
            )
        ]
        values = dict(context.metrics.values)
        values["period.earlier.pushes"] = 3.0
        values["period.prior.pushes"] = 1.0
        values["period.last.pushes"] = 0.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g15 = _mutate(base_case("builder"), "G15-three-period-refs", (), g15_fn)

    def g16_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g16",
                "Programming in last reached 3",
                facts=["fact:synthetic-1"],
                refs=[_ref("period.last.screen_hours.Work/Programming", 3.0)],
            )
        ]
        values = dict(context.metrics.values)
        values["period.last.screen_hours.Work/Programming"] = 3.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g16 = _mutate(base_case("builder"), "G16-labelled-no-direction", (), g16_fn)

    def g17_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g17",
                "Work/Programming screen hours decreased from 4.75 in prior"
                " to 1.75 in last.",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.prior.screen_hours.Work/Programming", 4.75),
                    _ref("period.last.screen_hours.Work/Programming", 1.75),
                ],
            )
        ]
        values = dict(context.metrics.values)
        values["period.prior.screen_hours.Work/Programming"] = 4.75
        values["period.last.screen_hours.Work/Programming"] = 1.75
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g17 = _mutate(base_case("builder"), "G17-model-wording-screen", (), g17_fn)

    def g18_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g18",
                "Github pushes decreased from 3 in earlier to 1 in prior"
                " and to 0 in last.",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.earlier.pushes", 3.0),
                    _ref("period.prior.pushes", 1.0),
                    _ref("period.last.pushes", 0.0),
                ],
            )
        ]
        values = dict(context.metrics.values)
        values["period.earlier.pushes"] = 3.0
        values["period.prior.pushes"] = 1.0
        values["period.last.pushes"] = 0.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g18 = _mutate(base_case("builder"), "G18-model-wording-pushes", (), g18_fn)

    def g19_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"] = [
            _claim(
                "claim-g19",
                "Programming fell from 4.75 in the prior period"
                " to 1.75 in the last period.",
                facts=["fact:synthetic-1"],
                refs=[
                    _ref("period.prior.screen_hours.Work/Programming", 4.75),
                    _ref("period.last.screen_hours.Work/Programming", 1.75),
                ],
            )
        ]
        values = dict(context.metrics.values)
        values["period.prior.screen_hours.Work/Programming"] = 4.75
        values["period.last.screen_hours.Work/Programming"] = 1.75
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g19 = _mutate(base_case("builder"), "G19-model-wording-segment", (), g19_fn)

    def g20_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        since_last = _section(briefing, "since_last")
        since_last["claims"] = [
            _claim(
                "claim-s1",
                "Programming is down 10 since the parent briefing",
                refs=[_ref("screen_hours.Work/Programming", -10.0)],
            )
        ]
        return context

    g20 = _mutate(
        base_case_with_parent("builder"), "G20-negative-delta-absolute", (), g20_fn
    )

    return (
        g1,
        g2,
        g3,
        g4,
        g5,
        g6,
        g7,
        g8,
        g9,
        g10,
        g11,
        g12,
        g13,
        g14,
        g15,
        g16,
        g17,
        g18,
        g19,
        g20,
    )


KNOWN_GOOD: tuple[Case, ...] = _build_known_good()


def _redteam_known_good() -> tuple[Case, ...]:
    """Ticket 10b: N1 to N27 plus the R2 name case, all passing."""
    cases: list[Case] = []

    def add(name: str, text: str, refs: list[tuple[str, float]]) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            return _install(briefing, context, text, refs)

        cases.append(_mutate(base, name, (), fn))

    def add_fact(name: str, text: str, statement: str) -> None:
        base = base_case("builder")
        fact_id = "fact:synthetic-local"

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            ctx = _with_local_fact(context, fact_id, statement)
            return _install_fact_only(briefing, ctx, text, fact_id)

        cases.append(_mutate(base, name, (), fn))

    prog_last = "period.last.screen_hours.Work/Programming"
    prog_prior = "period.prior.screen_hours.Work/Programming"
    fell = "Pushes fell from 3 in earlier to 1 in prior and to 0 in last."
    add("G21-n1-stood", "Programming in last stood at 1.75 hours.", [(prog_last, 1.75)])
    add(
        "G22-n2-went-down",
        "Pushes went down from 1 in prior to 0 in last.",
        [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
    )
    add(
        "G23-n3-value-first",
        "Pushes in last were 0, down from 1 in prior.",
        [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
    )
    add(
        "G24-n4-busy-over",
        "Busy hours reached 6.5 over the window.",
        [("calendar.busy_hours", 6.5)],
    )
    add(
        "G25-n5-stated-zero",
        "There were no pushes in last.",
        [("period.last.pushes", 0.0)],
    )
    add_fact("G26-n6-absent", "Pushes were absent in the last period.", fell)
    add(
        "G27-n7-spent",
        "I spent 1.75 hours on Programming in last.",
        [(prog_last, 1.75)],
    )
    add_fact("G28-n8-shipped", "Shipped one small change in last.", fell)
    add_fact(
        "G29-n9-review-notes",
        "Review notes were written in prior.",
        "Review notes were written in prior.",
    )
    add_fact(
        "G30-n10-about",
        "Feed items about On-device inference optimization appeared.",
        "Feed items about On-device inference optimization appeared in the synthetic log.",
    )
    add(
        "G31-n11-moved",
        "Programming moved from 4.75 in prior to 1.75 in last.",
        [(prog_prior, 4.75), (prog_last, 1.75)],
    )
    add("G32-n12-totaled", "Pushes totaled 0 in last.", [("period.last.pushes", 0.0)])
    add_fact(
        "G33-n13-clock-the",
        "The 14:00 call ran long.",
        "Review notes were written in prior.",
    )
    add(
        "G34-n14-period-list",
        "Pushes were 1 and 0 in prior and last.",
        [("period.prior.pushes", 1.0), ("period.last.pushes", 0.0)],
    )
    add(
        "G35-n15-unit-pairs",
        "Programming screen hours were 4.75 hours in prior and 1.75 hours in last.",
        [(prog_prior, 4.75), (prog_last, 1.75)],
    )
    add_fact(
        "G36-n16-roman-free",
        "Feed items about ML and CI tooling appeared.",
        "Feed items about ML and CI tooling appeared.",
    )
    add(
        "G37-n17-up-to",
        "Chat screen hours went up to 3.45 in last from 1.27 in prior.",
        [
            ("period.prior.screen_hours.Chat", 1.27),
            ("period.last.screen_hours.Chat", 3.45),
        ],
    )
    add_fact(
        "G38-n18-use-of",
        "Use of the feed fell in last.",
        "Use of the feed fell in last.",
    )
    add_fact(
        "G39-n19-focus-dropped", "Focus dropped in last.", "Focus dropped in last."
    )
    add(
        "G40-n20-backticks",
        "Cancelled `iki-deep` blocks were 1 in prior.",
        [("period.prior.cancelled.iki-deep", 1.0)],
    )
    add(
        "G41-n21-you-spent",
        "You spent 4.75 hours on Programming in prior and 1.75 hours in last.",
        [(prog_prior, 4.75), (prog_last, 1.75)],
    )
    add_fact(
        "G42-n22-godel",
        "Feed items about G\u00f6del machines appeared in last.",
        "Feed items about G\u00f6del machines appeared in last.",
    )
    add_fact("G43-n23-due", "A review was due in last.", "A review was due in last.")
    add(
        "G44-n24-github-pushes",
        "GitHub pushes were 3 in earlier and 1 in prior.",
        [("period.earlier.pushes", 3.0), ("period.prior.pushes", 1.0)],
    )
    add(
        "G45-n25-cancelled-zero",
        "Cancelled iki-deep blocks were 0 in earlier and 1 in prior.",
        [
            ("period.earlier.cancelled.iki-deep", 0.0),
            ("period.prior.cancelled.iki-deep", 1.0),
        ],
    )
    add_fact(
        "G46-n26-glimmer-fact",
        "In prior, a GitHub pull request opening and a GitHub push occurred in the same period.",
        "In prior, a GitHub pull request opening and a GitHub push occurred in the same period.",
    )
    add(
        "G47-n27-slashed-category",
        "Work/Programming screen hours were 7.0 in earlier and 4.75 in prior.",
        [("period.earlier.screen_hours.Work/Programming", 7.0), (prog_prior, 4.75)],
    )
    base = base_case("builder")

    def r2_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = _with_local_fact(
            context,
            "fact:synthetic-r2",
            "Pushes to example-user/seven-tower happened in last.",
        )
        return _install_fact_only(
            briefing,
            ctx,
            "Pushes to example-user/seven-tower happened in last.",
            "fact:synthetic-r2",
        )

    cases.append(_mutate(base, "G48-r2-name-with-number", (), r2_fn))
    return tuple(cases)


def _round2_known_good() -> tuple[Case, ...]:
    """Ticket 10b: one known-good case per round-2 over-block class."""
    cases: list[Case] = []

    def add(name: str, text: str, refs: list[tuple[str, float]]) -> None:
        base = base_case("builder")

        def fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
            return _install(briefing, context, text, refs)

        cases.append(_mutate(base, name, (), fn))

    prog_last = "period.last.screen_hours.Work/Programming"
    prog_prior = "period.prior.screen_hours.Work/Programming"
    add(
        "G49-R04-whole-over-noise",
        "Programming reached 90 hours.",
        [("screen_hours.Work/Programming", 90.00000000000001)],
    )
    add(
        "G50-R05-held-count",
        "The feed held 9 items.",
        [("feed.item.count", 9.0)],
    )

    def g51_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = _with_local_fact(
            context,
            "fact:synthetic-g51",
            "A synthetic review opened and two synthetic runs "
            "finished in the same window.",
        )
        return _install_fact_only(
            briefing,
            ctx,
            "The review and the runs showed up in the window.",
            "fact:synthetic-g51",
        )

    cases.append(_mutate(base_case("builder"), "G51-R06-phrasal-particle", (), g51_fn))
    add(
        "G52-R07-ahead",
        "Busy hours ran 6.5, leaving this hour clear to plan ahead.",
        [("calendar.busy_hours", 6.5)],
    )

    def g53_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = _install(
            briefing,
            context,
            "Pushes in prior were 1.",
            [("period.prior.pushes", 1.0)],
        )
        return ctx.model_copy(update={"private_terms": ("I 7 depot",)})

    cases.append(_mutate(base_case("builder"), "G53-R31-short-word-value", (), g53_fn))

    def g54_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        ctx = context.model_copy(update={"private_terms": (SYNTHETIC_TERM,)})
        return _install_fact_only(briefing, ctx, "Quetzal left the notes today.")

    cases.append(_mutate(base_case("builder"), "G54-R42-hyphen-part-alone", (), g54_fn))
    add(
        "G55-R40-later-period-first",
        "Programming stood lower in the last period at 1.75 hours "
        "than in the prior period at 4.75 hours.",
        [(prog_prior, 4.75), (prog_last, 1.75)],
    )
    add(
        "G56-R43-cancel-comparison",
        "Cancelled deep blocks fell from 1 in prior to 0 in last.",
        [
            ("period.prior.cancelled.iki-deep", 1.0),
            ("period.last.cancelled.iki-deep", 0.0),
        ],
    )
    add(
        "G57-range-two-periods",
        "Pushes ranged from 3 in earlier to 0 in last.",
        [("period.earlier.pushes", 3.0), ("period.last.pushes", 0.0)],
    )
    return tuple(cases)


KNOWN_GOOD = KNOWN_GOOD + _redteam_known_good() + _round2_known_good()
