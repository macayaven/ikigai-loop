"""Step 2 tests: voice compile schema shape, parsing, validation, change lines.

Synthetic data only. No network, no model, no private terms file.
"""

from __future__ import annotations

import pytest

from framework.voice.schemas import (
    CORRECTION_COMMITMENT_REQUIRED,
    CORRECTION_PAIR_INVALID,
    CORRECTION_QUESTION_INVALID,
    CORRECTION_UNKNOWN_COMMITMENT,
    CompiledCorrection,
    UnparseableCorrection,
    build_correction_schema,
    change_line,
    parse_compiled,
    validate_compiled,
)

CLEAN = {
    "private_terms": (),
    "private_terms_available": True,
    "forbidden_raw_literals": (),
}


def _correction(
    operation: str,
    commitment_id: str | None,
    until: str | None,
    question: str | None,
) -> CompiledCorrection:
    return CompiledCorrection(
        operation=operation,  # type: ignore[arg-type]
        commitment_id=commitment_id,
        until=until,  # type: ignore[arg-type]
        question=question,
    )


def test_build_correction_schema_with_ids() -> None:
    assert build_correction_schema(["write-up", "evening-rest"]) == {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "skip",
                    "defer",
                    "drop",
                    "done",
                    "keep",
                    "fact_correction",
                    "none",
                ],
            },
            "commitment_id": {
                "type": ["string", "null"],
                "enum": ["write-up", "evening-rest", None],
            },
            "until": {
                "type": ["string", "null"],
                "enum": ["slot", "today", "tomorrow", "this_week", "open", None],
            },
            "question": {"type": ["string", "null"]},
        },
        "required": ["operation", "commitment_id", "until", "question"],
        "additionalProperties": False,
    }


def test_build_correction_schema_no_ids_leaves_null_enum() -> None:
    schema = build_correction_schema([])
    assert schema["properties"]["commitment_id"] == {
        "type": ["string", "null"],
        "enum": [None],
    }
    assert schema["required"] == ["operation", "commitment_id", "until", "question"]
    assert schema["additionalProperties"] is False


def test_parse_compiled_happy_path() -> None:
    parsed = parse_compiled(
        '{"operation":"skip","commitment_id":"write-up","until":"today","question":null}'
    )
    assert parsed == CompiledCorrection(
        operation="skip", commitment_id="write-up", until="today", question=None
    )


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "",
        "[1, 2]",
        "null",
        "42",
        '{"operation":"skip","commitment_id":"write-up","until":"today"}',
        '{"operation":"skip","commitment_id":"write-up","until":"today","question":null,"extra":1}',
        '{"operation":"nap","commitment_id":"write-up","until":"today","question":null}',
        '{"operation":"skip","commitment_id":"write-up","until":"someday","question":null}',
        '{"operation":null,"commitment_id":null,"until":null,"question":null}',
    ],
)
def test_parse_compiled_unparseable_arms(text: str) -> None:
    assert isinstance(parse_compiled(text), UnparseableCorrection)


def test_parse_compiled_never_raises_on_wrong_types() -> None:
    assert isinstance(
        parse_compiled(
            '{"operation":["skip"],"commitment_id":7,"until":{},"question":[]}'
        ),
        UnparseableCorrection,
    )


@pytest.mark.parametrize("question", ["", "   ", "\t\n "])
def test_parse_compiled_empty_question_becomes_null(question: str) -> None:
    parsed = parse_compiled(
        '{"operation":"none","commitment_id":null,"until":null,"question":'
        + '"'
        + question.replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")
        + '"}'
    )
    assert parsed == CompiledCorrection(
        operation="none", commitment_id=None, until=None, question=None
    )


def test_parse_compiled_keeps_real_question_verbatim() -> None:
    parsed = parse_compiled(
        '{"operation":"none","commitment_id":null,"until":null,'
        '"question":"Which commitment do you mean?"}'
    )
    assert parsed == CompiledCorrection(
        operation="none",
        commitment_id=None,
        until=None,
        question="Which commitment do you mean?",
    )


ALLOWED_PAIRS = [
    ("skip", "slot"),
    ("skip", "today"),
    ("skip", "tomorrow"),
    ("skip", "this_week"),
    ("skip", "open"),
    ("defer", "today"),
    ("defer", "tomorrow"),
    ("defer", "this_week"),
    ("drop", "open"),
    ("done", "today"),
    ("keep", None),
    ("fact_correction", None),
]


@pytest.mark.parametrize(("operation", "until"), ALLOWED_PAIRS)
def test_validate_accepts_every_allowed_pair(operation: str, until: str | None) -> None:
    commitment_id = None if operation in ("fact_correction", "none") else "write-up"
    correction = _correction(operation, commitment_id, until, None)
    assert validate_compiled(correction, ["write-up", "evening-rest"], **CLEAN) == ()


def test_validate_accepts_none_with_question() -> None:
    correction = _correction("none", None, None, "Which commitment do you mean?")
    assert validate_compiled(correction, ["write-up"], **CLEAN) == ()


def test_validate_unknown_commitment() -> None:
    correction = _correction("skip", "nope", "today", None)
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_UNKNOWN_COMMITMENT,
    )


@pytest.mark.parametrize(
    ("operation", "commitment_id", "until"),
    [
        ("skip", None, "today"),
        ("defer", None, "tomorrow"),
        ("drop", None, "open"),
        ("done", None, "today"),
        ("keep", None, None),
        ("fact_correction", "write-up", None),
        ("none", "write-up", None),
    ],
)
def test_validate_commitment_required_arms(
    operation: str, commitment_id: str | None, until: str | None
) -> None:
    question = "Which commitment do you mean?" if operation == "none" else None
    correction = _correction(operation, commitment_id, until, question)
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_COMMITMENT_REQUIRED,
    )


@pytest.mark.parametrize(
    ("operation", "until"),
    [
        ("skip", None),
        ("defer", "slot"),
        ("defer", "open"),
        ("defer", None),
        ("drop", "today"),
        ("drop", None),
        ("done", "tomorrow"),
        ("done", None),
        ("keep", "today"),
        ("fact_correction", "slot"),
        ("fact_correction", "open"),
        ("none", "today"),
        ("none", "slot"),
    ],
)
def test_validate_pair_invalid_arms(operation: str, until: str | None) -> None:
    commitment_id = (
        "write-up" if operation in ("skip", "defer", "drop", "done", "keep") else None
    )
    question = "Which one?" if operation == "none" else None
    correction = _correction(operation, commitment_id, until, question)
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_PAIR_INVALID,
    )


def test_validate_none_needs_a_question() -> None:
    correction = _correction("none", None, None, None)
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_QUESTION_INVALID,
    )


def test_validate_other_operations_must_not_carry_a_question() -> None:
    correction = _correction("skip", "write-up", "today", "Why?")
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_QUESTION_INVALID,
    )


def test_validate_none_question_hit_by_forbidden_literal() -> None:
    correction = _correction("none", None, None, "Which write-up do you mean?")
    codes = validate_compiled(
        correction,
        ["write-up"],
        private_terms=(),
        private_terms_available=True,
        forbidden_raw_literals=("write-up",),
    )
    assert codes == (CORRECTION_QUESTION_INVALID,)


def test_validate_none_question_fails_when_terms_unavailable() -> None:
    correction = _correction("none", None, None, "Which commitment do you mean?")
    codes = validate_compiled(
        correction,
        ["write-up"],
        private_terms=(),
        private_terms_available=False,
        forbidden_raw_literals=(),
    )
    assert codes == (CORRECTION_QUESTION_INVALID,)


def test_validate_none_question_too_long_or_multiline() -> None:
    long_question = _correction("none", None, None, "x" * 201)
    assert validate_compiled(long_question, ["write-up"], **CLEAN) == (
        CORRECTION_QUESTION_INVALID,
    )
    two_lines = _correction("none", None, None, "Which one?\nTell me.")
    assert validate_compiled(two_lines, ["write-up"], **CLEAN) == (
        CORRECTION_QUESTION_INVALID,
    )
    ok_length = _correction("none", None, None, "x" * 200)
    assert validate_compiled(ok_length, ["write-up"], **CLEAN) == ()


def test_validate_codes_come_back_sorted() -> None:
    correction = CompiledCorrection.model_construct(
        operation="skip", commitment_id="nope", until="someday", question="Why?"
    )
    assert validate_compiled(correction, ["write-up"], **CLEAN) == (
        CORRECTION_PAIR_INVALID,
        CORRECTION_QUESTION_INVALID,
        CORRECTION_UNKNOWN_COMMITMENT,
    )


@pytest.mark.parametrize(
    ("operation", "until", "title", "expected"),
    [
        (
            "skip",
            "today",
            "Finish the write-up",
            "Skipped: Finish the write-up (today).",
        ),
        (
            "skip",
            "slot",
            "Finish the write-up",
            "Skipped: Finish the write-up (this slot).",
        ),
        (
            "skip",
            "this_week",
            "Finish the write-up",
            "Skipped: Finish the write-up (this week).",
        ),
        (
            "skip",
            "open",
            "Finish the write-up",
            "Skipped: Finish the write-up (no end date).",
        ),
        ("defer", "tomorrow", "Evening rest", "Put off: Evening rest (tomorrow)."),
        ("drop", "open", "Evening rest", "Dropped: Evening rest."),
        ("done", "today", "Evening rest", "Done: Evening rest."),
        ("keep", None, "Evening rest", "Kept: Evening rest."),
        (
            "fact_correction",
            None,
            "3 claims",
            "You disputed what this card cited (3 claims).",
        ),
        (
            "fact_correction",
            None,
            "1 claim",
            "You disputed what this card cited (1 claim).",
        ),
    ],
)
def test_change_line_templates(
    operation: str, until: str | None, title: str | None, expected: str
) -> None:
    correction = _correction(operation, "write-up", until, None)
    assert change_line(correction, title) == expected


def test_change_line_none_returns_the_question() -> None:
    correction = _correction("none", None, None, "Which commitment do you mean?")
    assert change_line(correction, None) == "Which commitment do you mean?"
