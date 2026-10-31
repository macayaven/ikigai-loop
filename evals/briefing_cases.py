"""Ticket 8: briefing-gate meta-eval cases (single source of truth).

Both the pytest meta-eval (``tests/test_briefing_mutants.py``) and the
Inspect tasks (``evals/briefing_gate.py``) build from ``MUTANTS`` and
``KNOWN_GOOD`` here so the two harnesses can never drift apart.

Every value is synthetic: ``subject-1`` is the repo's existing placeholder
subject, facts are ``fact:synthetic-*``, metrics are ``agg.*`` aggregates
(``raw.health.*`` only where a mutant needs a raw ID), and free text avoids
real names, real measurements, and real contact details. Times are frozen on
2026-10-31 (Europe/Madrid, CET, UTC+1) unless a case moves them.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.briefing.schemas import Briefing

SUBJECT_ID = "subject-1"
TIMEZONE = "Europe/Madrid"
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
        "agg.focus_minutes": 90.0,
        "agg.walk_minutes": 30.0,
        "agg.tasks_done": 3.0,
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
    kind: str,
    text: str,
    dimension: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    return {
        "id": aid,
        "kind": kind,
        "text": text,
        "dimension": dimension,
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
    if profile == "recovery":
        return [
            _action(
                "act-walk-1",
                "walk",
                "Walk the synthetic garden loop",
                "love",
                _iso(31, 14, 0),
                _iso(31, 14, 45),
            ),
            _action(
                "act-rest-1",
                "rest",
                "Rest with quiet music",
                "limit",
                _iso(31, 18, 0),
                _iso(31, 19, 0),
            ),
        ]
    return [
        _action(
            "act-build-1",
            "build",
            "Build the synthetic parser sketch",
            "good_at",
            _iso(31, 14, 0),
            _iso(31, 14, 45),
        ),
        _action(
            "act-write-1",
            "write",
            "Write notes on the synthetic trial",
            "love",
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
                        "plan",
                        "Plan the synthetic week",
                        "love",
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
                "Focus total moved by 10 since the parent briefing",
                refs=[_ref("agg.focus_minutes", -10.0)],
            ),
            _claim(
                "claim-s2",
                "Walk total is unchanged since the parent briefing",
                refs=[_ref("agg.walk_minutes", 0.0)],
            ),
            _claim(
                "claim-s3",
                "Tasks completed rose by 1 since the parent briefing",
                refs=[_ref("agg.tasks_done", 1.0)],
            ),
        ],
        "actions": [],
    }


def base_case_with_parent(profile: str) -> Case:
    """Passing briefing with a parent pair and delta-correct ``since_last``.

    Current metrics are ``{focus 90, walk 30, tasks 3}``; parent metrics are
    ``{focus 100, walk 30, tasks 2}``, so the deltas are ``-10``, ``0``,
    ``+1`` (negative and zero deltas included).
    """
    briefing = _base_briefing(profile, f"brf-{profile}-child")
    parent_id = f"brf-{profile}-parent"
    briefing["parent_briefing_id"] = parent_id
    sections = briefing["sections"]
    sections.insert(1, _since_last_section())
    parent_metrics = MetricSnapshot(
        values={
            "agg.focus_minutes": 100.0,
            "agg.walk_minutes": 30.0,
            "agg.tasks_done": 2.0,
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
                    "plan",
                    "Plan the synthetic follow-up",
                    "love",
                    _iso(31, 16, 30),
                    _iso(31, 17, 0),
                ),
                _action(
                    "act-extra-2",
                    "read",
                    "Read the synthetic appendix",
                    "world_needs",
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
        claim["text"] = "Completed 99 synthetic tasks"
        claim["metric_refs"] = [_ref("agg.tasks_done", 99.0)]
        return context

    def m13(briefing: dict[str, Any], context: GateContext) -> GateContext:
        claim = _get_claim(_section(briefing, "since_last"), "claim-s1")
        claim["text"] = "Focus total moved by 11 since the parent briefing"
        claim["metric_refs"] = [_ref("agg.focus_minutes", -11.0)]
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
        parent = context.parent_briefing.model_copy(update={"profile_id": "recovery"})
        return context.model_copy(update={"parent_briefing": parent})

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
    )


MUTANTS: tuple[Case, ...] = _build_mutants()


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

    recovery = base_case("recovery")
    g3 = Case(
        name="G3-recovery-first",
        briefing=recovery.briefing,
        context=recovery.context,
        expected=(),
    )

    def g4_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        working = _section(briefing, "working")
        working["claims"].append(
            _claim(
                "claim-wpct",
                "Half the synthetic list is done at 50% completion",
                facts=["fact:synthetic-1"],
                refs=[_ref("agg.completion_pct", 50.0)],
            )
        )
        working["claims"].append(
            _claim(
                "claim-wdec",
                "Morning pages averaged 7.5 lines",
                facts=["fact:synthetic-2"],
                refs=[_ref("agg.pages_lines", 7.5)],
            )
        )
        values = dict(context.metrics.values)
        values["agg.completion_pct"] = 50.0
        values["agg.pages_lines"] = 7.5
        parent_values = dict(context.parent_metrics.values)  # type: ignore[union-attr]
        parent_values["agg.completion_pct"] = 40.0
        parent_values["agg.pages_lines"] = 7.0
        return context.model_copy(
            update={
                "metrics": MetricSnapshot(values=values),
                "parent_metrics": MetricSnapshot(values=parent_values),
            }
        )

    parented_recovery = base_case_with_parent("recovery")
    g4 = _mutate(parented_recovery, "G4-recovery-parent-pct-dec", (), g4_fn)

    g5_base = base_case("builder")
    g5 = Case(
        name="G5-slot-at-open",
        briefing=g5_base.briefing,
        context=g5_base.context,
        expected=(),
    )

    def g6_fn(briefing: dict[str, Any], context: GateContext) -> GateContext:
        briefing["slot"] = _iso(31, 21, 0)
        actions = _section(briefing, "actions")["actions"]
        actions[0]["id"] = "act-eve-1"
        actions[0]["kind"] = "plan"
        actions[0]["text"] = "Plan the synthetic evening review"
        actions[0]["proposed_start"] = _iso(31, 21, 0)
        actions[0]["proposed_end"] = _iso(31, 22, 0)
        actions[1]["id"] = "act-eve-2"
        actions[1]["kind"] = "checkin"
        actions[1]["text"] = "Log the synthetic evening checkin"
        actions[1]["proposed_start"] = _iso(31, 23, 0)
        actions[1]["proposed_end"] = _iso(31, 23, 30)
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
                "read",
                "Read the synthetic reference notes",
                "world_needs",
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
                "claim-m2",
                "Focus total reached 90 with 3 tasks done",
                facts=["fact:synthetic-1", "fact:synthetic-2"],
                refs=[
                    _ref("agg.focus_minutes", 90.0),
                    _ref("agg.tasks_done", 3.0),
                ],
            )
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
                "Output quality sits at 21.2 this week",
                facts=["fact:synthetic-1"],
                refs=[_ref("agg.quality", 21.1544)],
            ),
            _claim(
                "claim-r2",
                "Energy is down 5 from last time",
                facts=["fact:synthetic-2"],
                refs=[_ref("agg.energy", -5.0)],
            ),
            _claim(
                "claim-r3",
                "Range check 3-5 passed twice",
                facts=["fact:synthetic-1"],
                refs=[_ref("agg.low", 3.0), _ref("agg.high", 5.0)],
            ),
        ]
        values = dict(context.metrics.values)
        values["agg.quality"] = 21.1544
        values["agg.energy"] = -5.0
        values["agg.low"] = 3.0
        values["agg.high"] = 5.0
        return context.model_copy(update={"metrics": MetricSnapshot(values=values)})

    g12 = _mutate(base_case("builder"), "G12-rounded-absolute-backing", (), g12_fn)

    return (g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11, g12)


KNOWN_GOOD: tuple[Case, ...] = _build_known_good()
