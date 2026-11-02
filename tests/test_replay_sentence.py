"""Ticket 24: replay-sentence command tests.

M119 carries a real sentence from a delivered card with the real values it
cited; the rest of each briefing is made up."""

from __future__ import annotations


def _m119():
    from evals.briefing_cases import MUTANTS

    return next(c for c in MUTANTS if c.name == "M119-since-last-period-phrase")


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _expected_context() -> str:
    case = _m119()
    section = next(s for s in case.briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    metric_id = claim["metric_refs"][0]["metric_id"]
    assert case.context.parent_metrics is not None
    previous = case.context.parent_metrics.values[metric_id]
    current = case.context.metrics.values[metric_id]
    delta = claim["metric_refs"][0]["value"]
    return (
        "Context: the 15:30 card on Nov 2; "
        f"{metric_id} changed by {_fmt(delta)}, "
        f"from {_fmt(previous)} to {_fmt(current)}, "
        "since the last card; the rest of the briefing is made up."
    )


def test_no_argument_gates_default_sentence(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main([])
    out = capsys.readouterr()
    assert code == 1
    assert _expected_context() in out.out
    assert "L1B_SINCE_LAST_WORDING" in out.out


def test_taught_wording_passes(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["Prs rose by 3 since the last card."])
    out = capsys.readouterr()
    assert code == 0
    assert _expected_context() in out.out
    assert "passed" in out.out


def test_direction_gap_passes(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["Prs softened since the last card."])
    out = capsys.readouterr()
    assert code == 0
    assert "passed" in out.out


def test_value_gap_passes(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["Prs were 3 since the last card."])
    out = capsys.readouterr()
    assert code == 0
    assert "passed" in out.out


def test_containment_gap_passes(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["Prs rose by 3 through the last period."])
    out = capsys.readouterr()
    assert code == 0
    assert "passed" in out.out


def test_clumsy_true_shape_stops(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(
        ["Prs in the last period increased by 3 since the last card."]
    )
    out = capsys.readouterr()
    assert code == 1
    assert "L1B_SINCE_LAST_WORDING" in out.out


def test_two_arguments_is_usage_error(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["one", "two"])
    out = capsys.readouterr()
    assert code == 2
    assert "L1B_" not in out.out
    assert out.err.strip() != ""


def test_hyphen_argument_is_usage_error(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main(["--help"])
    out = capsys.readouterr()
    assert code == 2
    assert "L1B_" not in out.out
    assert "usage: python -m evals.replay_sentence [sentence]" in out.err


def test_empty_argument_is_usage_error(capsys) -> None:
    from evals import replay_sentence

    code = replay_sentence.main([""])
    out = capsys.readouterr()
    assert code == 2
    assert "L1B_" not in out.out


def test_context_line_names_card_and_case_values() -> None:
    case = _m119()
    section = next(s for s in case.briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    metric_id = claim["metric_refs"][0]["metric_id"]
    assert case.context.parent_metrics is not None
    line = _expected_context()
    assert "15:30 card on Nov 2" in line
    assert metric_id in line
    assert _fmt(claim["metric_refs"][0]["value"]) in line
    assert _fmt(case.context.parent_metrics.values[metric_id]) in line
    assert _fmt(case.context.metrics.values[metric_id]) in line
