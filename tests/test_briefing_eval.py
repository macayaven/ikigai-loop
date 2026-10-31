"""Ticket 8: Inspect task construction only (no eval run in pytest)."""

from inspect_ai.scorer import CORRECT, INCORRECT

from evals.briefing_cases import KNOWN_GOOD, MUTANTS
from evals.briefing_gate import (
    briefing_gate,
    briefing_l0,
    briefing_l1,
    briefing_l1b,
    layer_of,
    score_briefing,
)
from framework.briefing.context import GateContext
from framework.briefing.gate import evaluate_briefing


def test_four_tasks_exist_with_case_name_sample_ids() -> None:
    expected_ids = [c.name for c in (*MUTANTS, *KNOWN_GOOD)]
    for make_task in (briefing_l0, briefing_l1, briefing_l1b, briefing_gate):
        task = make_task()
        assert [s.id for s in task.dataset] == expected_ids


def test_per_layer_targets_are_layer_filtered_codes() -> None:
    layers = {"briefing_l0": ("L0",), "briefing_l1": ("L1",)}
    tasks = {"briefing_l0": briefing_l0(), "briefing_l1": briefing_l1()}
    for task_name, task in tasks.items():
        wanted = layers[task_name]
        for sample, case in zip(task.dataset, (*MUTANTS, *KNOWN_GOOD)):
            filtered = [c for c in case.expected if layer_of(c) in wanted]
            assert sample.target == ("PASS" if not filtered else ",".join(filtered)), (
                task_name,
                case.name,
            )


def test_gate_task_target_is_full_code_list() -> None:
    for sample, case in zip(briefing_gate().dataset, (*MUTANTS, *KNOWN_GOOD)):
        assert sample.target == (
            "PASS" if not case.expected else ",".join(case.expected)
        )


def test_scorer_logic_agrees_with_gate_on_every_case() -> None:
    for layers in (("L0",), ("L1",), ("L1b",), ("L0", "L1", "L1b")):
        for case in (*MUTANTS, *KNOWN_GOOD):
            context_json = case.context.model_dump(mode="json")
            GateContext.model_validate(context_json)
            filtered = [c for c in case.expected if layer_of(c) in layers]
            target = "PASS" if not filtered else ",".join(filtered)
            score = score_briefing(case.briefing, context_json, layers, target)
            assert score.value == CORRECT, (layers, case.name)
            actual = [
                v.code
                for v in evaluate_briefing(case.briefing, case.context).violations
                if layer_of(v.code) in layers
            ]
            assert score.answer == ("PASS" if not actual else ",".join(actual))


def test_scorer_marks_wrong_layer_target_incorrect() -> None:
    case = next(c for c in MUTANTS if c.name == "M4-pii-email")
    context_json = case.context.model_dump(mode="json")
    score = score_briefing(case.briefing, context_json, ("L0",), "L1_PII")
    assert score.value == INCORRECT
    assert "L1_PII" not in (score.answer or "")
