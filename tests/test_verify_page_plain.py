"""Ticket 17a follow-up: plain-words page helpers (jobs 1 and 2)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from framework.verify.__main__ import main
from framework.verify.hardened import check_claims, page_render_hardened

ROOT = Path(__file__).resolve().parents[1]
VERIFY_PAGE_PATH = ROOT / "docs" / "verify" / "verify_page.py"
EXAMPLES = ROOT / "docs" / "verify" / "examples"


def _load_verify_page() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_page", VERIFY_PAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_page"] = module
    spec.loader.exec_module(module)
    return module


VERIFY_PAGE = _load_verify_page()


def _rows(pairs: list[tuple[str, str]]) -> str:
    return json.dumps([{"name": name, "number": number} for name, number in pairs])


def _job1(agent_text: str, pairs: list[tuple[str, str]]) -> Any:
    return json.loads(VERIFY_PAGE.build_checker_input(agent_text, _rows(pairs)))  # type: ignore[no-untyped-call]


def _job2(checker_input: str) -> Any:
    return json.loads(VERIFY_PAGE.explain_report(checker_input))  # type: ignore[no-untyped-call]


def _render(checker_input: str) -> Any:
    return json.loads(page_render_hardened(checker_input))


def _claims(built: Any) -> Any:
    assert isinstance(built["input"], str)
    return json.loads(built["input"])["claims"]


def test_made_up_example_fails_only_on_value() -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    report = check_claims(built["input"])
    assert [v.code for v in report.violations] == ["L1B_METRIC_VALUE_MISMATCH"]
    explained = _job2(built["input"])
    assert explained["passed"] is False
    findings = explained["claims"][0]["findings"]
    assert len(findings) == 1
    assert findings[0]["code"] == "L1B_METRIC_VALUE_MISMATCH"
    assert findings[0]["sentence"] == "The sentence says 12; your record says 7."


def test_plain_examples_give_pinned_code_lists() -> None:
    wrong = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    assert wrong["problems"] == []
    assert isinstance(wrong["input"], str)
    assert [v.code for v in check_claims(wrong["input"]).violations] == [
        "L1B_METRIC_VALUE_MISMATCH"
    ]

    matching = _job1("Deploys reached 7 in November.", [("November deploys", "7")])
    assert matching["problems"] == []
    assert isinstance(matching["input"], str)
    assert check_claims(matching["input"]).passed is True
    assert list(check_claims(matching["input"]).violations) == []

    sneaky = _job1("Deploys did not reach 7 in November.", [("November deploys", "7")])
    assert sneaky["problems"] == []
    assert isinstance(sneaky["input"], str)
    assert [v.code for v in check_claims(sneaky["input"]).violations] == [
        "L1B_NEGATED_CLAIM"
    ]


def test_worked_example_mismatch_wording_is_pinned() -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    assert isinstance(built["input"], str)
    explained = _job2(built["input"])
    findings = explained["claims"][0]["findings"]
    assert len(findings) == 1
    assert findings[0]["code"] == "L1B_METRIC_VALUE_MISMATCH"
    assert findings[0]["sentence"] == "The sentence says 12; your record says 7."


def test_pass_wording_for_one_and_several_sentences() -> None:
    one = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 7 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                    }
                ],
                "facts": {},
                "metrics": {"November deploys": 7},
            }
        )
    )
    assert one["passed"] is True
    assert one["overall"] == (
        "This number matches your record. That does not make the sentence true: "
        "it checks numbers, sources and wording, nothing else. Some checks didn't run."
    )
    assert "PASS" not in one["overall"]
    assert "FAIL" not in one["overall"]
    two = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 7 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                    },
                    {
                        "id": "c2",
                        "text": "October deploys were 5",
                        "metric_refs": [{"metric_id": "October deploys", "value": 5}],
                    },
                ],
                "facts": {},
                "metrics": {"November deploys": 7, "October deploys": 5},
            }
        )
    )
    assert two["passed"] is True
    assert two["overall"] == (
        "These numbers match your records. That does not make the sentence true: "
        "it checks numbers, sources and wording, nothing else. Some checks didn't run."
    )


def test_catch_verdict_headlines_for_one_and_several() -> None:
    one = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 9 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                    }
                ],
                "facts": {},
                "metrics": {"November deploys": 7},
            }
        )
    )
    assert one["passed"] is False
    assert one["overall"] == "Caught it."
    two = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 9 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                    },
                    {
                        "id": "c2",
                        "text": "October deploys were 5",
                        "metric_refs": [{"metric_id": "October deploys", "value": 5}],
                    },
                ],
                "facts": {},
                "metrics": {"November deploys": 7, "October deploys": 5},
            }
        )
    )
    assert two["passed"] is False
    assert two["overall"] == "Caught it. 1 of 2 checked sentences did not pass."


def test_fallback_sentence_has_no_code_in_it() -> None:
    sentence = VERIFY_PAGE._finding_sentence(  # type: ignore[no-untyped-call]
        "L1B_SOMETHING_NEW", "", "Deploys reached 7 in November.", [], [], {}
    )
    assert sentence == "The checker flagged this sentence."
    assert "L1B_SOMETHING_NEW" not in sentence


def test_records_matching_sentence_passes() -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "12")])
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    assert check_claims(built["input"]).passed is True
    assert _job2(built["input"])["passed"] is True


def test_sentence_number_never_changes_metrics() -> None:
    first = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    second = _job1("Deploys reached 9 in November.", [("November deploys", "7")])
    assert isinstance(first["input"], str)
    assert isinstance(second["input"], str)
    assert json.loads(first["input"])["metrics"] == {"November deploys": 7}
    assert json.loads(second["input"])["metrics"] == {"November deploys": 7}
    assert check_claims(first["input"]).passed is False
    assert check_claims(second["input"]).passed is False


def test_matching_sentence_against_matching_records_passes() -> None:
    built = _job1("Deploys reached 7 in November.", [("November deploys", "7")])
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    assert check_claims(built["input"]).passed is True


def test_number_with_no_record_fails() -> None:
    built = _job1("Latency was 42 seconds.", [("November deploys", "7")])
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    report = check_claims(built["input"])
    assert report.passed is False
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in [v.code for v in report.violations]


def test_sentence_without_number_is_not_a_claim() -> None:
    built = _job1(
        "Deploys reached 12 in November. The team is happy.",
        [("November deploys", "7")],
    )
    assert [claim["id"] for claim in _claims(built)] == ["s1"]
    unchecked = built["unchecked"]
    assert len(unchecked) == 1
    assert unchecked[0]["sentence_id"] == "s2"
    assert "no number" in unchecked[0]["reason"]


def test_two_records_in_one_sentence_cite_nothing() -> None:
    # One record per sentence: a sentence naming two records cites neither,
    # so the checker fails it instead of handing one record's number over.
    built = _job1(
        "Deploys reached 12, and tickets were steady.",
        [("deploys", "7"), ("tickets", "12")],
    )
    assert built["problems"] == []
    claims = _claims(built)
    assert len(claims) == 1
    assert claims[0]["metric_refs"] == []
    assert isinstance(built["input"], str)
    assert check_claims(built["input"]).passed is False
    lines = " ".join(built["pairings"][0]["lines"])
    assert "deploys" in lines
    assert "tickets" in lines
    assert "own sentence" in lines


def test_one_record_per_sentence_passes() -> None:
    built = _job1(
        "Apples reached 4. Oranges reached 12.",
        [("apples", "4"), ("oranges", "12")],
    )
    assert built["problems"] == []
    claims = _claims(built)
    assert len(claims) == 2
    refs = {
        ref["metric_id"]: ref["value"]
        for claim in claims
        for ref in claim["metric_refs"]
    }
    assert refs == {"apples": 4, "oranges": 12}
    assert check_claims(built["input"]).passed is True
    lines = " ".join(line for pairing in built["pairings"] for line in pairing["lines"])
    assert "apples was read as 4" in lines
    assert "oranges was read as 12" in lines


def test_month_date_is_not_a_number() -> None:
    # The checker reads the original text, where a capitalised month plus
    # a number is a date, so "May 9" is not a number and 12 is the one cite.
    built = _job1("On May 9 deploys reached 12.", [("deploys", "12")])
    assert built["problems"] == []
    claims = _claims(built)
    assert claims[0]["metric_refs"] == [{"metric_id": "deploys", "value": 12}]
    assert check_claims(built["input"]).passed is True


def test_shorter_name_outside_longer_name_counts_as_two() -> None:
    built = _job1(
        "3 failed deploys out of 12 deploys.",
        [("deploys", "12"), ("failed deploys", "3")],
    )
    assert built["problems"] == []
    claims = _claims(built)
    assert claims[0]["metric_refs"] == []
    assert isinstance(built["input"], str)
    assert check_claims(built["input"]).passed is False
    lines = " ".join(built["pairings"][0]["lines"])
    assert "deploys" in lines
    assert "failed deploys" in lines
    assert "own sentence" in lines


def test_shorter_name_only_inside_longer_name_is_dropped() -> None:
    built = _job1(
        "We had 3 failed deploys.",
        [("deploys", "99"), ("failed deploys", "3")],
    )
    assert built["problems"] == []
    claims = _claims(built)
    assert claims[0]["metric_refs"] == [{"metric_id": "failed deploys", "value": 3}]
    assert check_claims(built["input"]).passed is True


def test_sentence_naming_no_record_cites_nothing() -> None:
    built = _job1("Latency was 42 seconds.", [("November deploys", "7")])
    assert built["problems"] == []
    claims = _claims(built)
    assert claims[0]["metric_refs"] == []
    lines = " ".join(built["pairings"][0]["lines"])
    assert "None of your record names appear in it" in lines


def test_job1_carries_no_sentence_text() -> None:
    built = _job1(
        "Deploys reached 12 in November. The team is happy.",
        [("November deploys", "7")],
    )
    blob = json.dumps({"pairings": built["pairings"], "unchecked": built["unchecked"]})
    assert "Deploys reached 12 in November" not in blob
    assert "The team is happy" not in blob
    assert built["pairings"][0]["sentence_id"] == "s1"
    assert "sentence" not in built["pairings"][0]
    assert built["unchecked"][0]["sentence_id"] == "s2"
    assert "sentence" not in built["unchecked"][0]


def test_longer_name_wins() -> None:
    built = _job1(
        "Failed deploys reached 3.",
        [("deploys", "99"), ("failed deploys", "3")],
    )
    assert built["problems"] == []
    claims = _claims(built)
    assert claims[0]["metric_refs"] == [{"metric_id": "failed deploys", "value": 3}]
    assert check_claims(built["input"]).passed is True


def test_list_markers_are_dropped() -> None:
    built = _job1(
        "- Deploys reached 12 in November.\n* October deploys were 5.",
        [("November deploys", "12"), ("October deploys", "5")],
    )
    assert built["problems"] == []
    texts = [claim["text"] for claim in _claims(built)]
    assert texts == [
        "Deploys reached 12 in November.",
        "October deploys were 5.",
    ]
    assert check_claims(built["input"]).passed is True


def test_numbered_marker_is_dropped() -> None:
    built = _job1(
        "1. Deploys reached 12 in November.",
        [("November deploys", "12")],
    )
    assert [claim["text"] for claim in _claims(built)] == [
        "Deploys reached 12 in November."
    ]


def test_decimal_stays_whole() -> None:
    built = _job1("Latency was 3.5 seconds.", [("Latency", "3.5")])
    assert built["problems"] == []
    claims = _claims(built)
    assert len(claims) == 1
    assert claims[0]["metric_refs"] == [{"metric_id": "Latency", "value": 3.5}]
    assert check_claims(built["input"]).passed is True


def test_date_and_time_are_not_numbers() -> None:
    built = _job1(
        "The deploy finished on November 5. The call is at 3:30pm.",
        [("November deploys", "7")],
    )
    assert built["input"] is None
    assert len(built["unchecked"]) == 2


@pytest.mark.parametrize(
    ("pairs", "row"),
    [
        ([("November deploys", "")], 1),
        ([("", "7")], 1),
        ([("deploys", "1"), ("Deploys", "2")], 2),
        ([("November deploys", "lots")], 1),
        ([("November deploys", "5 and 7")], 1),
    ],
)
def test_row_problems_name_the_row_and_build_nothing(
    pairs: list[tuple[str, str]], row: int
) -> None:
    built = _job1("Deploys reached 12 in November.", pairs)
    assert built["input"] is None
    assert len(built["problems"]) == 1
    assert f"Row {row}" in built["problems"][0]


def test_blank_rows_are_ignored() -> None:
    built = _job1(
        "Deploys reached 12 in November.",
        [("", ""), ("November deploys", "12"), ("   ", "  ")],
    )
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    assert check_claims(built["input"]).passed is True


def test_word_number_in_records_table() -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "twelve")])
    assert built["problems"] == []
    assert isinstance(built["input"], str)
    assert json.loads(built["input"])["metrics"] == {"November deploys": 12}


def test_built_input_matches_cli_and_page_render_hardened(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    assert isinstance(built["input"], str)
    rendered = _render(built["input"])
    target = tmp_path / "input.json"
    target.write_text(built["input"])
    code = main([str(target)])
    out, err = capsys.readouterr()
    assert code == rendered["exit_code"] == 1
    assert err == ""
    assert out == rendered["text"] + "\n"


def test_built_passing_input_matches_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = _job1("Deploys reached 7 in November.", [("November deploys", "7")])
    assert isinstance(built["input"], str)
    rendered = _render(built["input"])
    target = tmp_path / "input.json"
    target.write_text(built["input"])
    code = main([str(target)])
    out, _err = capsys.readouterr()
    assert code == rendered["exit_code"] == 0
    assert out == rendered["text"] + "\n"


@pytest.mark.parametrize("name", ["pass.json", "false-number.json", "leaked-term.json"])
def test_explain_matches_page_render_hardened(name: str) -> None:
    raw = (EXAMPLES / name).read_text()
    explained = _job2(raw)
    rendered = _render(raw)
    assert explained["passed"] == (rendered["exit_code"] == 0)
    report = check_claims(raw)
    expected: dict[str, list[str]] = {
        claim["id"]: [] for claim in json.loads(raw)["claims"]
    }
    for violation in report.violations:
        expected.setdefault(violation.claim_id, []).append(violation.code)
    seen: dict[str, list[str]] = {}
    for claim in explained["claims"]:
        seen[claim["id"]] = [finding["code"] for finding in claim["findings"]]
    assert seen == expected
    assert [claim["id"] for claim in explained["claims"]] == [
        claim["id"] for claim in json.loads(raw)["claims"]
    ]


def test_leaked_term_appears_nowhere() -> None:
    raw = (EXAMPLES / "leaked-term.json").read_text()
    explained = _job2(raw)
    blob = json.dumps(explained).lower()
    assert "harborlight ledger" not in blob
    assert explained["claims"][0]["text"] is None
    rendered = _render(raw)
    assert "harborlight ledger" not in str(rendered["text"]).lower()


def test_secret_value_is_hidden() -> None:
    payload = json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys reached 7 in November, secret: abcdefghijklmnop",
                    "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                }
            ],
            "facts": {},
            "metrics": {"November deploys": 7},
        }
    )
    explained = _job2(payload)
    assert explained["passed"] is False
    assert explained["claims"][0]["text"] is None
    assert "abcdefghijklmnop" not in json.dumps(explained)


def test_phone_number_is_hidden() -> None:
    payload = json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys reached 7 in November, call +15551234567 today",
                    "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                }
            ],
            "facts": {},
            "metrics": {"November deploys": 7},
        }
    )
    explained = _job2(payload)
    assert explained["passed"] is False
    assert explained["claims"][0]["text"] is None
    assert "15551234567" not in json.dumps(explained)


def test_hidden_claim_extra_finding_has_plain_meaning_only() -> None:
    payload = json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys reached 9 in November and the Harborlight Ledger note is attached",
                    "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                }
            ],
            "facts": {},
            "deny_terms": ["harborlight ledger"],
            "metrics": {"November deploys": 7},
        }
    )
    explained = _job2(payload)
    assert explained["claims"][0]["hidden"] is True
    extra = [
        finding
        for finding in explained["claims"][0]["findings"]
        if finding["code"].startswith("L1B_")
    ]
    assert len(extra) == 1
    assert "differs from your records" in extra[0]["sentence"]
    assert "9" not in extra[0]["sentence"]
    assert "7" not in extra[0]["sentence"]
    assert "harborlight ledger" not in json.dumps(explained).lower()


def test_no_evidence_says_nothing_was_checked() -> None:
    payload = json.dumps(
        {
            "claims": [{"id": "c1", "text": "The queue looks steady today"}],
            "facts": {"t1": "Trial log filed"},
            "metrics": {},
        }
    )
    explained = _job2(payload)
    assert explained["passed"] is False
    sentence = explained["claims"][0]["findings"][0]["sentence"]
    assert "nothing from your records was checked against it" in sentence.lower()


def test_bare_number_names_itself_and_no_backing() -> None:
    payload = json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Scored 42 points in the trial",
                    "fact_ids": ["t1"],
                }
            ],
            "facts": {"t1": "Trial log filed"},
            "metrics": {},
        }
    )
    explained = _job2(payload)
    assert explained["passed"] is False
    sentence = explained["claims"][0]["findings"][0]["sentence"]
    assert "42" in sentence
    assert "none of your records backs that number" in sentence


def test_overall_says_does_not_match() -> None:
    failing = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 9 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                    }
                ],
                "facts": {},
                "metrics": {"November deploys": 7},
            }
        )
    )
    assert "didn't pass" not in failing["overall"]
    assert "differs from your records" not in failing["overall"]
    assert "PASS" not in failing["overall"]
    assert "FAIL" not in failing["overall"]
    assert failing["overall"] == "Caught it."
    passing = _job2(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "Deploys reached 7 in November",
                        "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                    }
                ],
                "facts": {},
                "metrics": {"November deploys": 7},
            }
        )
    )
    assert "PASS" not in passing["overall"]
    assert "FAIL" not in passing["overall"]
    assert passing["overall"] == (
        "This number matches your record. That does not make the sentence true: "
        "it checks numbers, sources and wording, nothing else. Some checks didn't run."
    )


def _overall_for(payload_claims: list[dict[str, object]]) -> str:
    payload = json.dumps(
        {
            "claims": payload_claims,
            "facts": {},
            "metrics": {"November deploys": 7, "October deploys": 5},
        }
    )
    return str(_job2(payload)["overall"])


def test_overall_grammar_for_one_and_several() -> None:
    assert (
        _overall_for(
            [
                {
                    "id": "c1",
                    "text": "Deploys reached 7 in November",
                    "metric_refs": [{"metric_id": "November deploys", "value": 7}],
                },
                {
                    "id": "c2",
                    "text": "October deploys were 5",
                    "metric_refs": [{"metric_id": "October deploys", "value": 5}],
                },
            ]
        )
        == "These numbers match your records. That does not make the sentence true: "
        "it checks numbers, sources and wording, nothing else. Some checks didn't run."
    )
    assert (
        _overall_for(
            [
                {
                    "id": "c1",
                    "text": "Deploys reached 9 in November",
                    "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                },
                {
                    "id": "c2",
                    "text": "October deploys were 5",
                    "metric_refs": [{"metric_id": "October deploys", "value": 5}],
                },
            ]
        )
        == "Caught it. 1 of 2 checked sentences did not pass."
    )
    assert (
        _overall_for(
            [
                {
                    "id": "c1",
                    "text": "Deploys reached 9 in November",
                    "metric_refs": [{"metric_id": "November deploys", "value": 9}],
                },
                {
                    "id": "c2",
                    "text": "October deploys were 9",
                    "metric_refs": [{"metric_id": "October deploys", "value": 9}],
                },
            ]
        )
        == "Caught it. 2 of 2 checked sentences did not pass."
    )


def test_only_checker_public_pieces_are_imported() -> None:
    source = VERIFY_PAGE_PATH.read_text()
    assert "from framework.verify.hardened import" in source
    assert "check_claims" in source
    assert "page_render_hardened" in source
    assert "extract_number_tokens" in source
    assert "collapse_text" in source and "contains_token" in source
    assert "ref_backs_token" in source
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            assert "framework.briefing.labels" not in line
            assert "framework.verify.repair" not in line
            assert "framework.verify.page_bundle" not in line
            assert "framework.store" not in line
            assert "framework.collectors" not in line
    assert "import socket" not in source


def test_bad_rows_json_gives_problems_not_an_error() -> None:
    out = json.loads(VERIFY_PAGE.build_checker_input("Deploys reached 12.", "[oops"))  # type: ignore[no-untyped-call]
    assert out["input"] is None
    assert out["problems"] != []


def test_bad_checker_input_gives_fixed_message() -> None:
    out = json.loads(VERIFY_PAGE.explain_report("not json"))  # type: ignore[no-untyped-call]
    assert out["error"] == VERIFY_PAGE.JOB_ERROR  # type: ignore[attr-defined]


def _explain_payload(payload: dict[str, object]) -> Any:
    return _job2(json.dumps(payload))


def test_plain_words_for_new_codes() -> None:
    negated = _explain_payload(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Programming in last was not 1.75 hours",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 1.75}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 1.75},
            "labels": {"m1": ["programming", "last"]},
        }
    )
    sentences = [finding["sentence"] for finding in negated["claims"][0]["findings"]]
    assert any("says the opposite of the number" in sentence for sentence in sentences)

    quantity = _explain_payload(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Programming in last was over 1.75 hours",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 1.75}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 1.75},
            "labels": {"m1": ["programming", "last"]},
        }
    )
    sentences = [finding["sentence"] for finding in quantity["claims"][0]["findings"]]
    assert any("quantity word instead of digits" in sentence for sentence in sentences)

    unit = _explain_payload(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Programming in last was 1.75 minutes",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 1.75}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 1.75},
            "labels": {"m1": ["programming", "last"]},
            "units": {"m1": "hours"},
        }
    )
    sentences = [finding["sentence"] for finding in unit["claims"][0]["findings"]]
    assert any("differs from the record's unit" in sentence for sentence in sentences)

    period = _explain_payload(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys reached 5",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 5}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 5},
            "labels": {"m1": ["deploys"]},
            "periods": {"m1": "October"},
        }
    )
    sentences = [finding["sentence"] for finding in period["claims"][0]["findings"]]
    assert any(
        "does not name the record's period" in sentence for sentence in sentences
    )

    value_period = _explain_payload(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys were 9 in October and 5 in November",
                    "fact_ids": [],
                    "metric_refs": [
                        {"metric_id": "oct", "value": 5},
                        {"metric_id": "nov", "value": 9},
                    ],
                }
            ],
            "facts": {},
            "metrics": {"oct": 5, "nov": 9},
            "labels": {"oct": ["deploys", "october"], "nov": ["deploys", "november"]},
            "order": [["oct", "nov"]],
            "units": {"oct": "count", "nov": "count"},
            "periods": {"oct": "October", "nov": "November"},
        }
    )
    sentences = [
        finding["sentence"] for finding in value_period["claims"][0]["findings"]
    ]
    assert any("sits beside the wrong period" in sentence for sentence in sentences)


def test_plain_pane_lists_every_gap_on_one_line() -> None:
    built = _job1("Deploys reached 12 in November.", [("November deploys", "7")])
    assert isinstance(built["input"], str)
    explained = _job2(built["input"])
    gaps = explained["claims"][0]["gaps"]
    assert gaps is not None
    assert "not checked" in gaps.lower()
    assert "a unit was not asked for" in gaps
    assert "a period was not asked for" in gaps
    assert "direction words were not asked for" in gaps
    assert "beyond the record name" in gaps
    page = (ROOT / "docs" / "verify" / "index.html").read_text()
    assert "The plain form does not supply units or periods" not in page
    assert (
        "It checked the number against your record. "
        "It didn't check units, time periods or words like rose and fell."
    ) in page
