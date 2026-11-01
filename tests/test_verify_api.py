"""Ticket 17a: public verify API verdicts, input rules and import pins."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from framework.verify import (
    LIMITS_NOTE,
    Report,
    VerifyInputError,
    verify_claims,
)

EXPECTED_LIMITS_NOTE = (
    "This check covers parseable numbers, cited sources, labels and direction. "
    "It does not check that a sentence is true. "
    "Without labels it cannot tell which metric a number belongs to, "
    "and a cited fact is only checked to exist."
)


def _base(
    claims: list[dict[str, object]],
    facts: dict[str, str] | None = None,
    metrics: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "claims": claims,
        "facts": facts if facts is not None else {},
        "metrics": metrics if metrics is not None else {},
    }
    payload.update(extra)
    return payload


def _claim(cid: str, text: str, **extra: object) -> dict[str, object]:
    claim: dict[str, object] = {"id": cid, "text": text}
    claim.update(extra)
    return claim


def _codes(report: Report) -> list[str]:
    return [v.code for v in report.violations]


def test_limits_note_constant() -> None:
    assert LIMITS_NOTE == EXPECTED_LIMITS_NOTE


def test_clean_pass_carries_limits_note() -> None:
    report = verify_claims(
        _base(
            [_claim("c1", "The support queue note is filed", fact_ids=["t1"])],
            facts={"t1": "Support queue note filed on Monday"},
        )
    )
    assert report.passed is True
    assert report.violations == ()
    assert report.limits == LIMITS_NOTE
    assert report.feedback() == ""


def test_fail_carries_limits_note() -> None:
    report = verify_claims(_base([_claim("c1", "Scored 42 points in the trial")]))
    assert report.passed is False
    assert report.limits == LIMITS_NOTE
    assert "L1B_CLAIM_WITHOUT_EVIDENCE" in _codes(report)


def test_claim_without_evidence() -> None:
    report = verify_claims(
        _base([_claim("c1", "The queue looks steady today")], facts={"t1": "x"})
    )
    assert _codes(report) == ["L1B_CLAIM_WITHOUT_EVIDENCE"]


def test_unknown_fact() -> None:
    report = verify_claims(
        _base([_claim("c1", "The queue looks steady", fact_ids=["t-missing"])])
    )
    assert _codes(report) == ["L1B_UNKNOWN_FACT"]


def test_unknown_metric() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 5",
                    metric_refs=[{"metric_id": "deploys.nov", "value": 5}],
                )
            ],
            metrics={},
        )
    )
    assert _codes(report) == ["L1B_UNKNOWN_METRIC"]


def test_metric_value_mismatch_and_int_float_equality() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 9 in November",
                    metric_refs=[{"metric_id": "deploys.nov", "value": 9}],
                )
            ],
            metrics={"deploys.nov": 5},
            labels={"deploys.nov": ["deploys", "november"]},
        )
    )
    assert _codes(report) == ["L1B_METRIC_VALUE_MISMATCH"]
    same = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 3 in November",
                    metric_refs=[{"metric_id": "deploys.nov", "value": 3}],
                )
            ],
            metrics={"deploys.nov": 3.0},
            labels={"deploys.nov": ["deploys", "november"]},
        )
    )
    assert same.passed is True


def test_big_ints_stay_distinct() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 9007199254740993",
                    metric_refs=[
                        {"metric_id": "deploys.nov", "value": 9007199254740993}
                    ],
                )
            ],
            metrics={"deploys.nov": 9007199254740992},
        )
    )
    assert "L1B_METRIC_VALUE_MISMATCH" in _codes(report)


def test_number_without_metric_ref() -> None:
    report = verify_claims(
        _base(
            [_claim("c1", "Scored 42 points in the trial", fact_ids=["t1"])],
            facts={"t1": "Trial log filed"},
        )
    )
    assert _codes(report) == ["L1B_NUMBER_WITHOUT_METRIC_REF"]


def test_too_many_metrics_swapped_values_rejected() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Pushes reached 5 while the feed held 3",
                    metric_refs=[
                        {"metric_id": "pushes", "value": 3},
                        {"metric_id": "feed", "value": 5},
                    ],
                )
            ],
            metrics={"pushes": 3, "feed": 5},
            labels={"pushes": ["pushes"], "feed": ["feed"]},
        )
    )
    assert _codes(report) == ["L1B_TOO_MANY_METRICS"]
    assert (
        report.violations[0].message
        == "claim cites several metrics outside one declared series; "
        "split the claim or list them in order"
    )


def test_generic_id_with_no_label_entry_passes_label_arm() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 5",
                    metric_refs=[{"metric_id": "batch.count", "value": 5}],
                )
            ],
            metrics={"batch.count": 5},
        )
    )
    assert report.passed is True


def test_label_missing_needs_every_word() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Opened 12 tickets",
                    metric_refs=[{"metric_id": "tickets.closed", "value": 12}],
                )
            ],
            metrics={"tickets.closed": 12},
            labels={"tickets.closed": ["closed", "tickets"]},
        )
    )
    assert _codes(report) == ["L1B_METRIC_LABEL_MISSING"]


def test_label_match_is_whole_word() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Pushes reached 3",
                    metric_refs=[{"metric_id": "pushes", "value": 3}],
                )
            ],
            metrics={"pushes": 3},
            labels={"pushes": ["push"]},
        )
    )
    assert _codes(report) == ["L1B_METRIC_LABEL_MISSING"]


def test_direction_mismatch_single_ref() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys rose to 9 in November",
                    metric_refs=[{"metric_id": "deploys.nov", "value": 9}],
                )
            ],
            metrics={"deploys.nov": 9},
            labels={"deploys.nov": ["deploys", "november"]},
        )
    )
    assert _codes(report) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_agrees_with_declared_order() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Deploys rose from 5 in October to 9 in November",
                metric_refs=[
                    {"metric_id": "deploys.oct", "value": 5},
                    {"metric_id": "deploys.nov", "value": 9},
                ],
            )
        ],
        metrics={"deploys.oct": 5, "deploys.nov": 9},
        labels={
            "deploys.oct": ["deploys", "october"],
            "deploys.nov": ["deploys", "november"],
        },
        order=[["deploys.oct", "deploys.nov"]],
    )
    assert verify_claims(payload).passed is True


def test_order_is_not_agent_controlled() -> None:
    def _payload(ref_order: list[dict[str, object]]) -> dict[str, object]:
        return _base(
            [
                _claim(
                    "c1",
                    "Deploys rose from 5 in October to 9 in November",
                    metric_refs=ref_order,
                )
            ],
            metrics={"deploys.oct": 5, "deploys.nov": 9},
            labels={
                "deploys.oct": ["deploys", "october"],
                "deploys.nov": ["deploys", "november"],
            },
            order=[["deploys.oct", "deploys.nov"]],
        )

    fwd = _payload(
        [
            {"metric_id": "deploys.oct", "value": 5},
            {"metric_id": "deploys.nov", "value": 9},
        ]
    )
    rev = _payload(
        [
            {"metric_id": "deploys.nov", "value": 9},
            {"metric_id": "deploys.oct", "value": 5},
        ]
    )
    assert _codes(verify_claims(fwd)) == _codes(verify_claims(rev))

    falling = _base(
        [
            _claim(
                "c1",
                "Deploys fell from 9 to 5",
                metric_refs=[
                    {"metric_id": "deploys.nov", "value": 9},
                    {"metric_id": "deploys.oct", "value": 5},
                ],
            )
        ],
        metrics={"deploys.oct": 5, "deploys.nov": 9},
        labels={"deploys.oct": ["deploys"], "deploys.nov": ["deploys"]},
        order=[["deploys.oct", "deploys.nov"]],
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(verify_claims(falling))


def test_secret_pii_private_term_and_advice() -> None:
    secret = verify_claims(
        _base(
            [_claim("c1", "Rotate token: abcdefghijklmnop now", fact_ids=["t1"])],
            facts={"t1": "Rotation note filed"},
        )
    )
    assert "L1_SECRET" in _codes(secret)

    pii = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Contact synthetic@example.invalid for notes",
                    fact_ids=["t1"],
                )
            ],
            facts={"t1": "Contact note filed"},
        )
    )
    assert "L1_PII" in _codes(pii)

    leaked = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "The Harborlight Ledger note is attached",
                    fact_ids=["t1"],
                )
            ],
            facts={"t1": "Ledger note filed"},
            deny_terms=["harborlight ledger"],
        )
    )
    assert _codes(leaked) == ["L1_PRIVATE_TERM"]

    advised = verify_claims(
        _base(
            [_claim("c1", "You should log the result", fact_ids=["t1"])],
            facts={"t1": "Log note filed"},
            advice_words=["should"],
        )
    )
    assert _codes(advised) == ["L1_ADVICE"]

    no_advice_by_default = verify_claims(
        _base(
            [_claim("c1", "You should log the result", fact_ids=["t1"])],
            facts={"t1": "Log note filed"},
        )
    )
    assert no_advice_by_default.passed is True


def test_no_message_echoes_a_matched_term() -> None:
    term = "harborlight ledger"
    word = "should"
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    f"The {term} says you {word} rotate token: abcdefghijklmnop",
                    fact_ids=["t1"],
                )
            ],
            facts={"t1": "Note filed"},
            deny_terms=[term],
            advice_words=[word],
        )
    )
    assert report.passed is False
    blob = "\n".join(v.message for v in report.violations)
    assert term not in blob
    assert word not in blob
    assert "abcdefghijklmnop" not in blob
    assert "synthetic@example.invalid" not in "\n".join(
        v.message
        for v in verify_claims(
            _base(
                [_claim("c2", "Mail synthetic@example.invalid today", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
            )
        ).violations
    )


def test_feedback_lines() -> None:
    report = verify_claims(_base([_claim("c1", "Scored 42 points", fact_ids=["t9"])]))
    assert report.feedback() == (
        "L1B_UNKNOWN_FACT c1: cited fact is unknown\n"
        "L1B_NUMBER_WITHOUT_METRIC_REF c1: number token has no backing metric ref"
    )


def test_dedup_per_code_and_claim() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "The queue looks steady",
                    fact_ids=["t-missing-1", "t-missing-2"],
                )
            ]
        )
    )
    assert _codes(report) == ["L1B_UNKNOWN_FACT"]


def test_accepts_text_and_model_forms() -> None:
    payload = _base(
        [_claim("c1", "The queue looks steady", fact_ids=["t1"])],
        facts={"t1": "Support queue note filed on Monday"},
    )
    from framework.verify import VerifyInput

    assert verify_claims(payload).passed is True
    assert verify_claims(json.dumps(payload)).passed is True
    assert verify_claims(VerifyInput.model_validate(payload)).passed is True


@pytest.mark.parametrize(
    "payload",
    [
        _base([]),
        _base([_claim("c1", "Steady", fact_ids=["t1"]), _claim("c1", "Calm")]),
        _base([_claim("  ", "Steady", fact_ids=["t1"])]),
        _base([_claim("c1", "   ", fact_ids=["t1"])]),
        _base([_claim("c1", "Steady", fact_ids=["  "])]),
        _base([_claim("c1", "Steady")], facts={"  ": "Note filed"}),
        _base([_claim("c1", "Steady")], facts={"t1": "   "}),
        _base(
            [_claim("c1", "Steady", metric_refs=[{"metric_id": "  ", "value": 1}])],
            metrics={"m": 1},
        ),
        _base([_claim("c1", "Steady")], labels={"m": []}),
        _base([_claim("c1", "Steady")], labels={"m": ["  "]}),
        _base([_claim("c1", "Steady")], deny_terms=["  "]),
        _base([_claim("c1", "Steady")], advice_words=["  "]),
        _base(
            [_claim("c1", "Steady", metric_refs=[{"metric_id": "m", "value": "3"}])],
            metrics={"m": 3},
        ),
        _base(
            [_claim("c1", "Steady", metric_refs=[{"metric_id": "m", "value": True}])],
            metrics={"m": 1},
        ),
        _base([_claim("c1", "Steady")], metrics={"m": None}),
        _base([_claim("c1", "Steady")], metrics={"m": True}),
        _base([_claim("c1", "Steady")], order=[["only-one"]]),
        _base([_claim("c1", "Steady")], order=[["a", "b"], ["b", "c"]]),
        _base([_claim("c1", "Steady")], order=[["a", "a"]]),
    ],
)
def test_bad_input_raises_verify_input_error(payload: dict[str, object]) -> None:
    with pytest.raises(VerifyInputError):
        verify_claims(payload)


def test_unknown_key_is_bad_input() -> None:
    payload = _base([_claim("c1", "Steady", fact_ids=["t1"])], label=["oops"])
    with pytest.raises(VerifyInputError):
        verify_claims(payload)


def test_facts_and_metrics_are_required() -> None:
    with pytest.raises(VerifyInputError, match="facts"):
        verify_claims(
            {
                "claims": [
                    {"id": "c1", "text": "The queue looks steady", "fact_ids": ["t1"]}
                ],
                "metrics": {},
            }
        )
    with pytest.raises(VerifyInputError, match="metrics"):
        verify_claims(
            {
                "claims": [
                    {"id": "c1", "text": "The queue looks steady", "fact_ids": ["t1"]}
                ],
                "facts": {"t1": "Ticket note filed"},
            }
        )


def _series_payload(text: str, refs: list[dict[str, object]]) -> dict[str, object]:
    return _base(
        [_claim("c1", text, metric_refs=refs)],
        metrics={"deploys.oct": 5, "deploys.nov": 9},
        labels={
            "deploys.oct": ["deploys", "october"],
            "deploys.nov": ["deploys", "november"],
        },
        order=[["deploys.oct", "deploys.nov"]],
    )


def test_uncited_series_member_word_rejected() -> None:
    report = verify_claims(
        _series_payload(
            "Deploys reached 9 in November and October",
            [{"metric_id": "deploys.nov", "value": 9}],
        )
    )
    assert [v.code for v in report.violations] == ["L1B_METRIC_LABEL_MISSING"]
    assert (
        report.violations[0].message
        == "claim names another metric in its series without citing it"
    )


def test_cited_only_member_passes() -> None:
    report = verify_claims(
        _series_payload(
            "Deploys reached 9 in November",
            [{"metric_id": "deploys.nov", "value": 9}],
        )
    )
    assert report.passed is True


def test_citing_both_members_passes() -> None:
    report = verify_claims(
        _series_payload(
            "Deploys rose from 5 in October to 9 in November",
            [
                {"metric_id": "deploys.oct", "value": 5},
                {"metric_id": "deploys.nov", "value": 9},
            ],
        )
    )
    assert report.passed is True


def test_sibling_rule_needs_order() -> None:
    payload = _series_payload(
        "Deploys reached 9 in November and October",
        [{"metric_id": "deploys.nov", "value": 9}],
    )
    del payload["order"]
    assert verify_claims(payload).passed is True


def test_sibling_rule_needs_sibling_labels() -> None:
    payload = _series_payload(
        "Deploys reached 9 in November and October",
        [{"metric_id": "deploys.nov", "value": 9}],
    )
    payload["labels"] = {"deploys.nov": ["deploys", "november"]}
    assert verify_claims(payload).passed is True


def test_labelled_metric_outside_any_series_gets_no_sibling_finding() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "solo other 5",
                    metric_refs=[{"metric_id": "solo", "value": 5}],
                )
            ],
            metrics={"solo": 5},
            labels={"solo": ["solo"], "b1": ["other"]},
            order=[["a1", "a2"], ["b1", "b2"]],
        )
    )
    assert report.passed is True


def test_lone_surrogate_is_bad_input() -> None:
    from framework.verify import load_input

    with pytest.raises(VerifyInputError):
        load_input("\ud800")
    with pytest.raises(VerifyInputError):
        verify_claims("\ud800")


def test_huge_int_values_are_bad_input() -> None:
    huge = 10**5000
    with pytest.raises(VerifyInputError, match="too large"):
        verify_claims(
            _base(
                [
                    _claim(
                        "c1",
                        "Steady",
                        metric_refs=[{"metric_id": "m", "value": huge}],
                    )
                ],
                metrics={"m": 1},
            )
        )
    with pytest.raises(VerifyInputError, match="too large"):
        verify_claims(_base([_claim("c1", "Steady")], metrics={"m": huge}))


def test_label_word_cap() -> None:
    eleven = [f"word{i}" for i in range(11)]
    with pytest.raises(VerifyInputError, match="MAX_LABEL_WORDS"):
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                labels={"m": eleven},
            )
        )
    ten = [f"word{i}" for i in range(10)]
    report = verify_claims(
        _base(
            [_claim("c1", "Steady", fact_ids=["t1"])],
            facts={"t1": "Note filed"},
            labels={"m": ten},
        )
    )
    assert report.passed is True


def test_series_id_cap() -> None:
    over = [f"m{i}" for i in range(367)]
    with pytest.raises(VerifyInputError, match="MAX_SERIES_IDS"):
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                order=[over],
            )
        )
    ok = [f"m{i}" for i in range(366)]
    report = verify_claims(
        _base(
            [_claim("c1", "Steady", fact_ids=["t1"])],
            facts={"t1": "Note filed"},
            order=[ok],
        )
    )
    assert report.passed is True


def test_json_depth_cap() -> None:
    from framework.verify import load_input

    with pytest.raises(VerifyInputError, match="MAX_JSON_DEPTH"):
        load_input("[" * 65)
    with pytest.raises(VerifyInputError, match="input must be a JSON object"):
        load_input("[" * 64 + "]" * 64)
    report = verify_claims(
        _base(
            [_claim("c1", "Brackets " + "[" * 100, fact_ids=["t1"])],
            facts={"t1": "Note filed"},
        )
    )
    assert report.passed is True


def test_safe_messages_use_plain_words() -> None:
    with pytest.raises(VerifyInputError) as top:
        verify_claims("[]")
    assert str(top.value) == "input must be a JSON object"

    with pytest.raises(VerifyInputError) as string_metric:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                metrics={"m": "3"},
            )
        )
    assert str(string_metric.value) == "metrics.<key>: must be a number"

    with pytest.raises(VerifyInputError) as unknown_key:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                unknown_key="x",
            )
        )
    assert str(unknown_key.value) == "<key>: unknown key"

    with pytest.raises(VerifyInputError) as blank_term:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                deny_terms=["  "],
            )
        )
    assert "Value error" not in str(blank_term.value)


def test_known_ids_mask_cited_identifiers() -> None:
    text = "Ticket t1 and t1 are filed"
    masked = verify_claims(
        _base(
            [_claim("c1", text, fact_ids=["t1"])],
            facts={"t1": "Ticket note filed"},
        )
    )
    assert masked.passed is True
    other = verify_claims(
        _base(
            [_claim("c1", text, fact_ids=["t2"])],
            facts={"t1": "Ticket note filed"},
        )
    )
    assert _codes(other) == ["L1B_UNKNOWN_FACT", "L1B_NUMBER_WITHOUT_METRIC_REF"]


def test_error_message_never_echoes_input() -> None:
    secret = "harborlight ledger"
    try:
        verify_claims(
            _base([_claim("c1", "Steady")], deny_terms=[secret], unknown_key="x")  # type: ignore[arg-type]
        )
    except VerifyInputError as exc:
        assert secret not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected VerifyInputError")


ALLOWED_IMPORT_PREFIXES = (
    "framework.verify",
    "framework.briefing.gate",
    "framework.briefing.numbers",
    "framework.schemas.base",
    "pydantic",
)


_STDLIB_TOP_LEVELS = frozenset(
    {
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "io",
        "itertools",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "subprocess",
        "sys",
        "typing",
    }
)


def _import_is_allowed(stripped: str) -> bool:
    if not stripped.startswith(("import ", "from ")):
        return True
    if stripped.startswith(
        (
            "import __future__",
            "from __future__",
            "from .",
            "from framework.verify",
            "import framework.verify",
        )
    ):
        return True
    if any(
        stripped.startswith((f"import {prefix}", f"from {prefix}"))
        for prefix in ALLOWED_IMPORT_PREFIXES
    ):
        return True
    return stripped.split()[1].split(".")[0] in _STDLIB_TOP_LEVELS


def test_verify_source_imports_stay_in_the_allowed_set() -> None:
    root = Path(__file__).resolve().parents[1] / "framework" / "verify"
    files = sorted(root.glob("*.py"))
    assert len(files) >= 4
    bad: list[str] = []
    for path in files:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if not _import_is_allowed(stripped):
                bad.append(f"{path.name}:{lineno}:{stripped}")
    assert bad == []


def test_fresh_import_loads_no_store_or_model_modules() -> None:
    script = (
        "import sys, framework.verify; "
        "banned = [m for m in "
        "('sqlite3', 'jinja2', 'inspect_ai', 'icalendar', "
        "'framework.store', 'framework.collectors', 'framework.blocks') "
        "if m in sys.modules]; "
        "assert not banned, banned; print('ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def _passing_claim(cid: str, text: str) -> dict[str, object]:
    return _claim(cid, text, fact_ids=["t1"])


def _facts_only() -> dict[str, str]:
    return {"t1": "Ticket note filed"}


def test_cap_claim_text_boundary() -> None:
    ok = verify_claims(_base([_passing_claim("c1", "x" * 2000)], facts=_facts_only()))
    assert ok.passed is True
    with pytest.raises(VerifyInputError, match="MAX_CLAIM_TEXT_CHARS"):
        verify_claims(_base([_passing_claim("c1", "x" * 2001)], facts=_facts_only()))


def test_cap_total_claim_text_boundary() -> None:
    claims_ok = [_passing_claim(f"c{i}", "x" * 1000) for i in range(100)]
    assert verify_claims(_base(claims_ok, facts=_facts_only())).passed is True
    claims_over = [_passing_claim(f"c{i}", "x" * 1000) for i in range(99)]
    claims_over.append(_passing_claim("c-last", "x" * 1001))
    with pytest.raises(VerifyInputError, match="MAX_TOTAL_CLAIM_TEXT_CHARS"):
        verify_claims(_base(claims_over, facts=_facts_only()))


def test_cap_claims_boundary() -> None:
    many = [_passing_claim(f"c{i}", "Steady note") for i in range(5000)]
    assert verify_claims(_base(many, facts=_facts_only())).passed is True
    many.append(_passing_claim("c-last", "Steady note"))
    with pytest.raises(VerifyInputError, match="MAX_CLAIMS"):
        verify_claims(_base(many, facts=_facts_only()))


def test_cap_refs_per_claim_boundary() -> None:
    refs_ok = [{"metric_id": f"m{i}", "value": 1} for i in range(100)]
    metrics_ok: dict[str, object] = {f"m{i}": 1 for i in range(100)}
    unbound = _base(
        [_claim("c1", "Steady note", metric_refs=refs_ok)],
        metrics=metrics_ok,
    )
    assert "L1B_TOO_MANY_METRICS" not in _codes(verify_claims(unbound))
    refs_over = [{"metric_id": f"m{i}", "value": 1} for i in range(101)]
    with pytest.raises(VerifyInputError, match="MAX_REFS_PER_CLAIM"):
        verify_claims(
            _base(
                [_claim("c1", "Steady note", metric_refs=refs_over)], metrics=metrics_ok
            )
        )


@pytest.mark.parametrize("field", ["deny_terms", "advice_words"])
def test_cap_terms_boundary(field: str) -> None:
    passing = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    passing[field] = ["term"] * 1000
    assert verify_claims(passing).passed is True
    over = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    over[field] = ["term"] * 1001
    with pytest.raises(VerifyInputError, match="MAX_TERMS"):
        verify_claims(over)


def test_cap_word_chars_label_word() -> None:
    ok = verify_claims(
        _base(
            [_passing_claim("c1", "Steady note")],
            facts=_facts_only(),
            labels={"m": ["w" * 100]},
        )
    )
    assert ok.passed is True
    with pytest.raises(VerifyInputError, match="MAX_WORD_CHARS"):
        verify_claims(
            _base(
                [_passing_claim("c1", "Steady note")],
                facts=_facts_only(),
                labels={"m": ["w" * 101]},
            )
        )


@pytest.mark.parametrize("field", ["deny_terms", "advice_words"])
def test_cap_word_chars_term_lists(field: str) -> None:
    passing = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    passing[field] = ["d" * 100]
    assert verify_claims(passing).passed is True
    over = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    over[field] = ["d" * 101]
    with pytest.raises(VerifyInputError, match="MAX_WORD_CHARS"):
        verify_claims(over)


def test_cap_claim_id_chars() -> None:
    ok = verify_claims(
        _base([_passing_claim("c" * 200, "Steady note")], facts=_facts_only())
    )
    assert ok.passed is True
    with pytest.raises(VerifyInputError, match="MAX_CLAIM_ID_CHARS"):
        verify_claims(
            _base([_passing_claim("c" * 201, "Steady note")], facts=_facts_only())
        )


def test_cap_metric_int_bit_length() -> None:
    big_ok = 1 << 13999
    assert big_ok.bit_length() == 14000
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Steady note",
                    metric_refs=[{"metric_id": "m", "value": big_ok}],
                )
            ],
            metrics={"m": big_ok},
        )
    )
    assert report.passed is True
    big_over = 1 << 14000
    assert big_over.bit_length() == 14001
    with pytest.raises(VerifyInputError, match="too large"):
        verify_claims(
            _base(
                [
                    _claim(
                        "c1",
                        "Steady note",
                        metric_refs=[{"metric_id": "m", "value": big_over}],
                    )
                ],
                metrics={"m": 1},
            )
        )


def test_cap_input_bytes_through_load_input() -> None:
    from framework.verify import load_input

    payload = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    raw = json.dumps(payload).encode()
    assert len(raw) < 10_000_000
    padded = raw + b" " * (10_000_000 - len(raw))
    assert len(padded) == 10_000_000
    assert load_input(padded).claims[0].id == "c1"
    with pytest.raises(VerifyInputError, match="MAX_INPUT_BYTES"):
        load_input(padded + b" ")


def test_error_summary_tails() -> None:
    with pytest.raises(VerifyInputError) as five:
        verify_claims(
            {
                "claims": [{"id": 1, "text": 2, "fact_ids": 3, "metric_refs": 4}],
                "facts": 5,
                "metrics": {},
            }
        )
    assert str(five.value).count(";") == 4
    assert "more" not in str(five.value)

    with pytest.raises(VerifyInputError) as six:
        verify_claims(
            {
                "claims": [{"id": 1, "text": 2, "fact_ids": 3, "metric_refs": 4}],
                "facts": 5,
                "metrics": 6,
            }
        )
    assert str(six.value) == (
        "claims.0.id: must be a string; claims.0.text: must be a string; "
        "claims.0.fact_ids: must be a list; claims.0.metric_refs: must be a list; "
        "facts: must be an object; and 1 more"
    )

    with pytest.raises(VerifyInputError) as ten:
        verify_claims(
            {
                "claims": [{"id": 1, "text": 2, "fact_ids": 3, "metric_refs": 4}],
                "facts": 5,
                "metrics": 6,
                "deny_terms": 7,
                "advice_words": 8,
                "labels": 9,
                "order": 10,
            }
        )
    assert str(ten.value).endswith("; and 5 more")


def test_error_lists_stop_at_first_bad_item() -> None:
    with pytest.raises(VerifyInputError) as labels_err:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                labels={"a": [1, 2, 3, 4, 5, 6, 7]},  # type: ignore[dict-item]
            )
        )
    assert str(labels_err.value) == "labels.<key>.0: must be a string"

    with pytest.raises(VerifyInputError) as order_err:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                order=[[1, 2, 3, 4, 5, 6, 7]],  # type: ignore[list-item]
            )
        )
    assert str(order_err.value) == "order.0.0: must be a string"

    with pytest.raises(VerifyInputError) as advice_err:
        verify_claims(
            _base(
                [_claim("c1", "Steady", fact_ids=["t1"])],
                facts={"t1": "Note filed"},
                advice_words=[1, 2, 3, 4, 5, 6, 7],  # type: ignore[list-item]
            )
        )
    assert str(advice_err.value) == "advice_words.0: must be a string"


def test_depth_ignores_brackets_inside_strings() -> None:
    from framework.verify import load_input

    payload = _base(
        [_passing_claim("c1", "Brackets " + "[" * 100)], facts=_facts_only()
    )
    assert load_input(json.dumps(payload)).claims[0].id == "c1"


def test_depth_counts_closing_brackets() -> None:
    series = [[f"m{i}a", f"m{i}b"] for i in range(100)]
    payload = _base(
        [_passing_claim("c1", "Steady note")], facts=_facts_only(), order=series
    )
    assert verify_claims(payload).passed is True


def test_depth_through_the_string_path() -> None:
    from framework.verify import load_input

    with pytest.raises(VerifyInputError) as flat_brackets:
        load_input("[" + ",".join(["[]"] * 100) + "]")
    assert str(flat_brackets.value) == "input must be a JSON object"

    with pytest.raises(VerifyInputError) as flat_braces:
        load_input("[" + ",".join(["{}"] * 100) + "]")
    assert str(flat_braces.value) == "input must be a JSON object"

    with pytest.raises(VerifyInputError, match="MAX_JSON_DEPTH"):
        load_input("[[]," + "[" * 64 + "]" * 64 + "]")


def test_unclosed_string_is_invalid_json() -> None:
    from framework.verify import load_input

    with pytest.raises(VerifyInputError, match="input is not valid JSON"):
        load_input('"never closed')


def test_string_and_dict_forms_agree() -> None:
    from framework.verify import load_input

    passing = _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    assert verify_claims(load_input(json.dumps(passing))).passed is True
    assert verify_claims(json.dumps(passing)).passed is True
    failing = _base([_claim("c1", "Scored 42 points in the trial")])
    assert _codes(verify_claims(load_input(json.dumps(failing)))) == _codes(
        verify_claims(json.dumps(failing))
    )


def test_load_input_rejects_non_text() -> None:
    from framework.verify import load_input

    with pytest.raises(VerifyInputError, match="input must be text or bytes"):
        load_input(123)  # type: ignore[arg-type]


def _direction_payload(
    text: str,
    refs: list[dict[str, object]],
    series: list[str],
    values: dict[str, object],
) -> dict[str, object]:
    return _base(
        [_claim("c1", text, metric_refs=refs)],
        metrics=values,  # type: ignore[arg-type]
        order=[series],
    )


def test_direction_without_labels_single_series() -> None:
    assert (
        verify_claims(
            _direction_payload(
                "Deploys rose from 5 to 6",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 6},
                ],
                ["d1", "d2"],
                {"d1": 5, "d2": 6},
            )
        ).passed
        is True
    )
    assert (
        verify_claims(
            _direction_payload(
                "Deploys rose from 5 to 5.5",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 5.5},
                ],
                ["d1", "d2"],
                {"d1": 5, "d2": 5.5},
            )
        ).passed
        is True
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys rose from 5 to 5",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 5},
                ],
                ["d1", "d2"],
                {"d1": 5, "d2": 5},
            )
        )
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys rose from 5 to 9 to 7",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 9},
                    {"metric_id": "d3", "value": 7},
                ],
                ["d1", "d2", "d3"],
                {"d1": 5, "d2": 9, "d3": 7},
            )
        )
    )
    assert (
        verify_claims(
            _direction_payload(
                "Deploys fell from 6 to 5",
                [
                    {"metric_id": "d1", "value": 6},
                    {"metric_id": "d2", "value": 5},
                ],
                ["d1", "d2"],
                {"d1": 6, "d2": 5},
            )
        ).passed
        is True
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys fell from 5 to 5",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 5},
                ],
                ["d1", "d2"],
                {"d1": 5, "d2": 5},
            )
        )
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys fell from 9 to 5 to 7",
                [
                    {"metric_id": "d1", "value": 9},
                    {"metric_id": "d2", "value": 5},
                    {"metric_id": "d3", "value": 7},
                ],
                ["d1", "d2", "d3"],
                {"d1": 9, "d2": 5, "d3": 7},
            )
        )
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys rose and fell from 5 to 9",
                [
                    {"metric_id": "d1", "value": 5},
                    {"metric_id": "d2", "value": 9},
                ],
                ["d1", "d2"],
                {"d1": 5, "d2": 9},
            )
        )
    )
    assert "L1B_DIRECTION_MISMATCH" in _codes(
        verify_claims(
            _direction_payload(
                "Deploys rose and fell from 9 to 5",
                [
                    {"metric_id": "d1", "value": 9},
                    {"metric_id": "d2", "value": 5},
                ],
                ["d1", "d2"],
                {"d1": 9, "d2": 5},
            )
        )
    )


def test_direction_needs_a_bound_ref() -> None:
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys rose to 5",
                    metric_refs=[{"metric_id": "batch.count", "value": 5}],
                )
            ],
            metrics={"batch.count": 5},
        )
    )
    assert "L1B_DIRECTION_MISMATCH" not in _codes(report)


def test_series_member_plus_outside_label_is_too_many() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Cee steady note",
                metric_refs=[
                    {"metric_id": "a", "value": 1},
                    {"metric_id": "c", "value": 2},
                ],
            )
        ],
        metrics={"a": 1, "b": 1, "c": 2},
        labels={"c": ["cee"]},
        order=[["a", "b"]],
    )
    assert _codes(verify_claims(payload)) == ["L1B_TOO_MANY_METRICS"]
    two_series = _base(
        [
            _claim(
                "c1",
                "Steady note",
                metric_refs=[
                    {"metric_id": "a", "value": 1},
                    {"metric_id": "c", "value": 2},
                ],
            )
        ],
        metrics={"a": 1, "b": 1, "c": 2, "d": 2},
        order=[["a", "b"], ["c", "d"]],
    )
    assert _codes(verify_claims(two_series)) == ["L1B_TOO_MANY_METRICS"]


def test_two_bound_refs_naming_one_label_word() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Deploys reached 9 in November",
                metric_refs=[
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "nov", "value": 9},
                ],
            )
        ],
        metrics={"oct": 5, "nov": 9},
        labels={"oct": ["october"], "nov": ["november"]},
        order=[["oct", "nov"]],
    )
    report = verify_claims(payload)
    assert [v.code for v in report.violations] == ["L1B_METRIC_LABEL_MISSING"]


def test_sibling_word_from_another_series_is_no_sibling() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Alfa reached 5 and cee",
                metric_refs=[{"metric_id": "a", "value": 5}],
            )
        ],
        metrics={"a": 5, "b": 5, "c": 5, "d": 5},
        labels={"a": ["alfa"], "b": ["bravo"], "c": ["cee"], "d": ["dee"]},
        order=[["a", "b"], ["c", "d"]],
    )
    assert verify_claims(payload).passed is True


def test_sibling_word_matching_only_in_case_is_no_sibling() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Deploys reached 5",
                metric_refs=[{"metric_id": "a", "value": 5}],
            )
        ],
        metrics={"a": 5, "b": 5},
        labels={"a": ["Deploys"], "b": ["DEPLOYS"]},
        order=[["a", "b"]],
    )
    assert verify_claims(payload).passed is True


def test_third_series_word_with_two_cited_is_rejected() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Alfa and bravo reached 5 with cee",
                metric_refs=[
                    {"metric_id": "a", "value": 5},
                    {"metric_id": "b", "value": 5},
                ],
            )
        ],
        metrics={"a": 5, "b": 5, "c": 5},
        labels={"a": ["alfa"], "b": ["bravo"], "c": ["cee"]},
        order=[["a", "b", "c"]],
    )
    report = verify_claims(payload)
    assert [v.code for v in report.violations] == ["L1B_METRIC_LABEL_MISSING"]


def test_shared_word_between_cited_and_sibling_is_no_sibling() -> None:
    payload = _base(
        [
            _claim(
                "c1",
                "Deploys reached 5",
                metric_refs=[{"metric_id": "a", "value": 5}],
            )
        ],
        metrics={"a": 5, "b": 5},
        labels={"a": ["deploys"], "b": ["deploys"]},
        order=[["a", "b"]],
    )
    assert verify_claims(payload).passed is True


def test_new_text_code_reaches_report_but_advice_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.verify import core

    monkeypatch.setattr(
        core,
        "text_check_codes",
        lambda text, private_terms=(): ("L1_NEW_RULE", "L1_ADVICE"),
    )
    report = verify_claims(
        _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
    )
    assert [v.code for v in report.violations] == ["L1_NEW_RULE"]
    assert report.violations[0].message == "text check failed"


def test_page_render_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    from framework.verify import core

    assert (
        json.loads(
            core.page_render(json.dumps(_base([_claim("c1", "Scored 42 points")])))
        )["exit_code"]
        == 1
    )
    assert (
        json.loads(
            core.page_render(
                json.dumps(
                    _base([_passing_claim("c1", "Steady note")], facts=_facts_only())
                )
            )
        )["exit_code"]
        == 0
    )
    assert json.loads(core.page_render("not json"))["exit_code"] == 2

    def _boom(data: object) -> Report:
        raise RuntimeError("private detail")

    monkeypatch.setattr(core, "verify_claims", _boom)
    body = json.loads(core.page_render(json.dumps(_base([_passing_claim("c1", "x")]))))
    assert body["exit_code"] == 2
    assert body["text"] == "could not check that input"


def test_repeated_sibling_word_searched_once_per_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.verify import core

    real = core.contains_token
    seen: list[str] = []

    def _wrap(text: str, literal: str) -> bool:
        seen.append(literal)
        return real(text, literal)

    monkeypatch.setattr(core, "contains_token", _wrap)
    members = [f"m{i}" for i in range(300)]
    labels: dict[str, list[str]] = {"m0": ["alfa"]}
    for member in members[1:]:
        labels[member] = ["zed"]
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Alfa steady note zedzed",
                    metric_refs=[{"metric_id": "m0", "value": 5}],
                )
            ],
            metrics={"m0": 5},
            labels=labels,
            order=[members],
        )
    )
    assert report.passed is True
    assert seen.count("zed") == 1


def test_shared_label_word_searched_once_for_two_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.verify import core

    real = core.contains_token
    seen: list[str] = []

    def _wrap(text: str, literal: str) -> bool:
        seen.append(literal)
        return real(text, literal)

    monkeypatch.setattr(core, "contains_token", _wrap)
    report = verify_claims(
        _base(
            [
                _claim(
                    "c1",
                    "Deploys reached 5",
                    metric_refs=[
                        {"metric_id": "a", "value": 5},
                        {"metric_id": "b", "value": 5},
                    ],
                )
            ],
            metrics={"a": 5, "b": 5},
            labels={"a": ["deploys"], "b": ["deploys"]},
            order=[["a", "b"]],
        )
    )
    assert report.passed is True
    assert seen.count("deploys") <= 1


def test_deny_term_case_variants_reach_text_check_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.verify import core

    real = core.text_check_codes
    seen: list[tuple[str, ...]] = []

    def _wrap(text: str, private_terms: tuple[str, ...] = ()) -> tuple[str, ...]:
        seen.append(tuple(private_terms))
        return real(text, private_terms=private_terms)

    monkeypatch.setattr(core, "text_check_codes", _wrap)
    report = verify_claims(
        _base(
            [_claim("c1", "The ledger note is attached", fact_ids=["t1"])],
            facts={"t1": "Ledger note filed"},
            deny_terms=["Ledger", "ledger", "LEDGER", "ledger"],
        )
    )
    assert seen == [("ledger",)]
    assert [v.code for v in report.violations] == ["L1_PRIVATE_TERM"]


def test_advice_word_case_variants_reach_word_list_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.verify import core

    real = core.word_list_hit
    seen: list[tuple[str, ...]] = []

    def _wrap(text: str, words: tuple[str, ...] | list[str]) -> bool:
        seen.append(tuple(words))
        return real(text, words)

    monkeypatch.setattr(core, "word_list_hit", _wrap)
    report = verify_claims(
        _base(
            [_claim("c1", "You should log the result", fact_ids=["t1"])],
            facts={"t1": "Log note filed"},
            advice_words=["Should", "should"],
        )
    )
    assert seen == [("should",)]
    assert [v.code for v in report.violations] == ["L1_ADVICE"]
