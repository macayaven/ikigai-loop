"""Ticket 023: hardened checker tests, written from the bug report first.

Every bug-report sentence in docs/plans/023-checker-hardening.md fails
with its pinned code through the API, the CLI and the unpacked bundle;
the true sentence passes and the wrong-digit sentence fails with
L1B_NUMBER_WITHOUT_METRIC_REF only. Made-up data only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals.gate_identity import closure_files
from framework.verify import VerifyInputError
from framework.verify.hardened import (
    HARDENED_LIMITS_NOTE,
    CheckReport,
    check_claims,
    load_check_input,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs" / "verify" / "bundle.json"


def _base(labels: dict | None = None, order: list | None = None) -> dict:
    payload: dict = {
        "claims": [],
        "facts": {},
        "metrics": {"m1": 1.75},
    }
    if labels is not None:
        payload["labels"] = labels
    if order is not None:
        payload["order"] = order
    return payload


def _claim(
    text: str,
    refs: list | None = None,
    cid: str = "c1",
    facts: list | None = None,
) -> dict:
    return {
        "id": cid,
        "text": text,
        "fact_ids": facts or [],
        "metric_refs": refs
        if refs is not None
        else [{"metric_id": "m1", "value": 1.75}],
    }


def _payload(
    text: str,
    units: dict | None = None,
    periods: dict | None = None,
    labels: dict | None = None,
    order: list | None = None,
) -> dict:
    payload = _base(
        labels=labels if labels is not None else {"m1": ["programming", "last"]},
        order=order,
    )
    payload["claims"] = [_claim(text)]
    if units is not None:
        payload["units"] = units
    if periods is not None:
        payload["periods"] = periods
    return payload


def _codes(report: CheckReport) -> list[str]:
    return [v.code for v in report.violations]


def _run_cli(
    payload: dict, tmp_path: Path, args: list[str] | None = None
) -> tuple[int, str, str]:
    from framework.verify.__main__ import main

    target = tmp_path / "input.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    argv = [str(target)] + (args or [])
    import io as _io

    out, err = _io.StringIO(), _io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err  # type: ignore[assignment]
    try:
        code = main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return code, out.getvalue(), err.getvalue()


def _run_bundle(payload: dict, tmp_path: Path) -> tuple[list[str], bool]:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    for relpath, source in bundle.items():
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    data_path = tmp_path / "payload.json"
    data_path.write_text(json.dumps(payload), encoding="utf-8")
    script = (
        f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
        "from framework.verify.hardened import check_claims; "
        f"r = check_claims(open({str(data_path)!r}).read()); "
        "print('CODES:' + '|'.join(v.code for v in r.violations)); "
        "print('PASS' if r.passed else 'FAIL')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[0].startswith("CODES:")
    codes = lines[0][len("CODES:") :].split("|") if lines[0] != "CODES:" else []
    return codes, lines[1] == "PASS"


# Bug report: escapes fail with pinned codes.


def test_negated_claim_fails() -> None:
    report = check_claims(_payload("Programming in last was not 1.75 hours"))
    assert report.passed is False
    assert "L1B_NEGATED_CLAIM" in _codes(report)


def test_minutes_against_hours_fails_unit() -> None:
    report = check_claims(
        _payload("Programming in last was 1.75 minutes", units={"m1": "hours"})
    )
    assert "L1B_UNIT_MISMATCH" in _codes(report)


def test_percent_form_against_hours_fails_unit() -> None:
    report = check_claims(
        _payload("Programming in last was 1.75%", units={"m1": "hours"})
    )
    assert "L1B_UNIT_MISMATCH" in _codes(report)


def test_percent_form_against_count_fails_unit() -> None:
    report = check_claims(
        _payload("Programming in last was 1.75%", units={"m1": "count"})
    )
    assert "L1B_UNIT_MISMATCH" in _codes(report)


def test_over_hours_fails_quantity() -> None:
    report = check_claims(_payload("Programming in last was over 1.75 hours"))
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(report)


def test_about_hours_fails_quantity() -> None:
    report = check_claims(_payload("Programming in last was about 1.75 hours"))
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(report)


def _comparison_payload(text: str) -> dict:
    return {
        "claims": [
            {
                "id": "c1",
                "text": text,
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


def test_swapped_months_fails_value_period() -> None:
    report = check_claims(
        _comparison_payload("Deploys were 9 in October and 5 in November")
    )
    assert report.passed is False
    assert "L1B_VALUE_PERIOD_MISMATCH" in _codes(report)


# Controls.


def test_true_sentence_passes() -> None:
    report = check_claims(
        _payload("Programming in last was 1.75 hours", units={"m1": "hours"})
    )
    assert report.passed is True
    assert _codes(report) == []


def test_wrong_digit_fails_number_only() -> None:
    report = check_claims(
        _payload("Programming in last was 1.85 hours", units={"m1": "hours"})
    )
    assert report.passed is False
    assert _codes(report) == ["L1B_NUMBER_WITHOUT_METRIC_REF"]


def test_true_twin_passes() -> None:
    report = check_claims(
        _comparison_payload("Deploys were 5 in October and 9 in November")
    )
    assert report.passed is True


# Three surfaces agree on every bug-report case.

BUG_CASES: list[tuple[str, dict, list[str], bool]] = [
    (
        "neg",
        _payload("Programming in last was not 1.75 hours"),
        ["L1B_NEGATED_CLAIM"],
        False,
    ),
    (
        "min",
        _payload("Programming in last was 1.75 minutes", units={"m1": "hours"}),
        ["L1B_UNIT_MISMATCH"],
        False,
    ),
    (
        "pct",
        _payload("Programming in last was 1.75%", units={"m1": "hours"}),
        ["L1B_UNIT_MISMATCH"],
        False,
    ),
    (
        "over",
        _payload("Programming in last was over 1.75 hours"),
        ["L1B_UNVERIFIABLE_QUANTITY"],
        False,
    ),
    (
        "about",
        _payload("Programming in last was about 1.75 hours"),
        ["L1B_UNVERIFIABLE_QUANTITY"],
        False,
    ),
    (
        "swap",
        _comparison_payload("Deploys were 9 in October and 5 in November"),
        ["L1B_VALUE_PERIOD_MISMATCH"],
        False,
    ),
    (
        "true",
        _payload("Programming in last was 1.75 hours", units={"m1": "hours"}),
        [],
        True,
    ),
]


@pytest.mark.parametrize("name,payload,codes,want_pass", BUG_CASES)
def test_surfaces_agree(
    name: str, payload: dict, codes: list[str], want_pass: bool, tmp_path: Path
) -> None:
    report = check_claims(dict(payload))
    assert report.passed is want_pass
    for code in codes:
        assert code in _codes(report)
    cli_code, cli_out, _ = _run_cli(dict(payload), tmp_path)
    assert (cli_code == 0) is want_pass
    for code in codes:
        assert code in cli_out
    bundle_codes, bundle_pass = _run_bundle(dict(payload), tmp_path)
    assert bundle_pass is want_pass
    for code in codes:
        assert code in bundle_codes


# Metadata-free cases: negation and quantity still fire, unit/period skip.


def test_metadata_free_negation_still_fires() -> None:
    report = check_claims(_payload("Programming in last was not 1.75 hours"))
    assert "L1B_NEGATED_CLAIM" in _codes(report)
    cov = {c.claim_id: c for c in report.coverage}
    assert "unit" in [s.check for s in cov["c1"].skipped]
    assert "period name" in [s.check for s in cov["c1"].skipped]
    assert report.complete is False
    assert report.human_first_line() == "FAIL - checks skipped"


def test_metadata_free_quantity_still_fires() -> None:
    report = check_claims(_payload("Programming in last was over 1.75 hours"))
    assert "L1B_UNVERIFIABLE_QUANTITY" in _codes(report)
    assert report.complete is False
    assert report.human_first_line() == "FAIL - checks skipped"


def test_metadata_free_true_passes_with_skips() -> None:
    report = check_claims(_payload("Programming in last was 1.75 hours"))
    assert report.passed is True
    assert report.complete is False
    assert report.human_first_line() == "PASS - checks skipped"


def test_fact_only_claim_lists_no_metric_entries() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "The note is filed",
                "fact_ids": ["t1"],
                "metric_refs": [],
            }
        ],
        "facts": {"t1": "The note is filed on Monday"},
        "metrics": {},
    }
    report = check_claims(payload)
    cov = report.coverage[0]
    names = [s.check for s in cov.skipped] + list(cov.ran)
    assert "metric naming" not in names
    assert "direction" not in names
    assert "unit" not in names
    assert "period name" not in names
    assert "value-period binding" not in names


# Unit table rows.

UNIT_ROWS: list[tuple[str, str, str, bool]] = [
    ("hours", "Programming in last was 1.75 hours", "hours", True),
    ("hours", "Programming in last was 1.75 minutes", "hours", False),
    ("hours", "Programming in last was 1.75 min", "hours", False),
    ("hours", "Programming in last was 1.75min", "hours", False),
    ("hours", "Programming in last was 1.75h", "hours", True),
    ("hours", "Programming in last was 1.75hr", "hours", True),
    ("hours", "Programming in last was 1.75hrs", "hours", True),
    ("hours", "Programming in last was 90m", "hours", False),
    ("hours", "Programming in last was 90s", "hours", False),
    ("hours", "Programming in last was 1.75%", "hours", False),
    ("hours", "Programming in last was 2 thousand hours", "hours", False),
    ("hours", "Programming was 1.75", "hours", True),
    ("count", "Deploys reached 5", "count", True),
    ("count", "Deploys reached 5 hours", "count", False),
    ("count", "Deploys reached 5%", "count", False),
    ("minutes", "Programming took 30 minutes", "minutes", True),
    ("minutes", "Programming took 30 seconds", "minutes", False),
    ("minutes", "Programming took 90m", "minutes", True),
    ("minutes", "Programming took 90min", "minutes", True),
    ("minutes", "Programming took 90mins", "minutes", True),
    ("minutes", "Programming took 1.75h", "minutes", False),
    ("minutes", "Programming took 90s", "minutes", False),
    ("seconds", "Task took 90 seconds", "seconds", True),
    ("seconds", "Task took 90 minutes", "seconds", False),
    ("seconds", "Task took 90s", "seconds", True),
    ("seconds", "Task took 90sec", "seconds", True),
    ("seconds", "Task took 90secs", "seconds", True),
    ("seconds", "Task took 1.75h", "seconds", False),
    ("seconds", "Task took 90m", "seconds", False),
    ("days", "Away for 3 days", "days", True),
    ("days", "Away for 3 day", "days", True),
    ("days", "Away for 3 hours", "days", False),
    ("days", "Away for 3 weeks", "days", False),
    ("days", "Away for 3 months", "days", False),
    ("percent", "Share was 50%", "percent", True),
    ("percent", "Share was 50 percent", "percent", True),
    ("percent", "Share was 50 hours", "percent", False),
]


@pytest.mark.parametrize("unit,text,value_word,want_ok", UNIT_ROWS)
def test_unit_table(unit: str, text: str, value_word: str, want_ok: bool) -> None:
    import re

    match = re.search(r"[\d.]+", text)
    assert match is not None
    number = float(match.group(0))
    metric = "m1"
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": text,
                "fact_ids": [],
                "metric_refs": [{"metric_id": metric, "value": number}],
            }
        ],
        "facts": {},
        "metrics": {metric: number},
        "labels": {
            metric: [
                "away",
                "programming",
                "task",
                "share",
                "deploys",
                "took",
                "reached",
                "last",
                "was",
                "for",
            ]
        },
        "units": {metric: unit},
    }
    report = check_claims(payload)
    if want_ok:
        assert "L1B_UNIT_MISMATCH" not in _codes(report), (unit, text, _codes(report))
    else:
        assert "L1B_UNIT_MISMATCH" in _codes(report), (unit, text, _codes(report))


# Stated zero rows.


def test_stated_zero_passes_when_zero() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "There were no deploys, count 0",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 0}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 0},
        "labels": {"m1": ["deploys"]},
    }
    report = check_claims(payload)
    assert "L1B_NEGATED_CLAIM" not in _codes(report)
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" not in _codes(report)


def test_stated_zero_fails_number_when_nonzero() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "There were no deploys, count 5",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 5}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 5},
        "labels": {"m1": ["deploys"]},
    }
    report = check_claims(payload)
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in _codes(report)


def test_stated_zero_same_verdict_under_label_orders() -> None:
    def _report(labels: list[str], value: int) -> list[str]:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": "No deploys failed",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": value}],
                }
            ],
            "facts": {},
            "metrics": {"m1": value},
            "labels": {"m1": labels},
        }
        return sorted(v.code for v in check_claims(payload).violations)

    orders = (
        ["failed", "deploys", "prod"],
        ["deploys", "failed", "prod"],
        ["prod", "failed", "deploys"],
    )
    zero = [_report(list(order), 0) for order in orders]
    assert zero[0] == zero[1] == zero[2]
    assert "L1B_NEGATED_CLAIM" not in zero[0]
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" not in zero[0]
    nonzero = [_report(list(order), 5) for order in orders]
    assert nonzero[0] == nonzero[1] == nonzero[2]
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in nonzero[0]


def test_nonzero_never_counts_as_stated_zero() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "The nonzero count was 5",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 5}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 5},
        "labels": {"m1": ["count"]},
    }
    report = check_claims(payload)
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" not in _codes(report)


# Fact-only negation rows.


def _fact_only(text: str) -> dict:
    return {
        "claims": [{"id": "c1", "text": text, "fact_ids": ["t1"], "metric_refs": []}],
        "facts": {"t1": "The support note is filed"},
        "metrics": {},
    }


def test_fact_only_negation_with_direction_fires() -> None:
    report = check_claims(_fact_only("The note did not rise"))
    assert "L1B_NEGATED_CLAIM" in _codes(report)


def test_fact_only_negation_with_same_fires() -> None:
    report = check_claims(_fact_only("The note did not stay the same"))
    assert "L1B_NEGATED_CLAIM" in _codes(report)


def test_fact_only_negation_with_period_fires() -> None:
    report = check_claims(_fact_only("The note did not mention last"))
    assert "L1B_NEGATED_CLAIM" in _codes(report)


def test_fact_only_negator_alone_passes() -> None:
    report = check_claims(_fact_only("The note was never filed nowhere special"))
    assert "L1B_NEGATED_CLAIM" not in _codes(report)


# Quantity-argument rows.


def test_backed_fifty_frees_half() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Half the deploys, 50 in all",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 50}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 50},
        "labels": {"m1": ["deploys"]},
    }
    report = check_claims(payload)
    assert "L1B_UNVERIFIABLE_QUANTITY" not in _codes(report)


def test_cited_fact_name_blanked() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys for job-42 reached 7",
                "fact_ids": ["t1"],
                "metric_refs": [{"metric_id": "m1", "value": 7}],
            }
        ],
        "facts": {"t1": "Record for job-42"},
        "metrics": {"m1": 7},
        "labels": {"m1": ["deploys"]},
    }
    report = check_claims(payload)
    assert "L1B_UNVERIFIABLE_QUANTITY" not in _codes(report)


# Period-name rows.


def test_declared_period_named_passes() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys reached 5 in October",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "oct", "value": 5}],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5},
        "labels": {"oct": ["deploys"]},
        "periods": {"oct": "October"},
    }
    assert "L1B_PERIOD_WORD_MISSING" not in _codes(check_claims(payload))


def test_declared_period_unnamed_fails() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys reached 5",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "oct", "value": 5}],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5},
        "labels": {"oct": ["deploys"]},
        "periods": {"oct": "October"},
    }
    assert "L1B_PERIOD_WORD_MISSING" in _codes(check_claims(payload))


def test_label_word_does_not_satisfy_period() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "October deploys reached 5",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "oct", "value": 5}],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5},
        "labels": {"oct": ["october", "deploys"]},
        "periods": {"oct": "November"},
    }
    assert "L1B_PERIOD_WORD_MISSING" in _codes(check_claims(payload))


# D6 recomputation rows.


def test_split_period_phrase_passes() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Programming in last week was 1.75 hours",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 1.75}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 1.75},
        "labels": {"m1": ["programming", "last", "week"]},
        "periods": {"m1": "last week"},
        "units": {"m1": "hours"},
    }
    report = check_claims(payload)
    assert "L1B_METRIC_LABEL_MISSING" not in _codes(report)
    assert report.passed is True


def test_other_time_phrase_still_fails() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Programming in last week was 1.75 hours yesterday",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 1.75}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 1.75},
        "labels": {"m1": ["programming", "last", "week"]},
        "periods": {"m1": "last week"},
        "units": {"m1": "hours"},
    }
    assert "L1B_METRIC_LABEL_MISSING" in _codes(check_claims(payload))


def test_same_input_without_periods_keeps_old_verdict() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Programming in last week was 1.75 hours",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 1.75}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 1.75},
        "labels": {"m1": ["programming", "last", "week"]},
    }
    assert "L1B_METRIC_LABEL_MISSING" in _codes(check_claims(payload))


# Uncited-period rows.


def _series_payload(text: str, with_order: bool) -> dict:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": text,
                "fact_ids": [],
                "metric_refs": [{"metric_id": "nov", "value": 9}],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "nov": 9},
        "labels": {"oct": ["deploys", "october"], "nov": ["deploys", "november"]},
        "periods": {"oct": "October", "nov": "November"},
    }
    if with_order:
        payload["order"] = [["oct", "nov"]]
    return payload


def test_uncited_series_period_fails() -> None:
    report = check_claims(
        _series_payload("Deploys were 9 in November, the same as October", True)
    )
    assert "L1B_PERIOD_WORD_MISSING" in _codes(report)


def test_uncited_period_without_series_passes_arm() -> None:
    report = check_claims(
        _series_payload("Deploys were 9 in November, the same as October", False)
    )
    assert "L1B_PERIOD_WORD_MISSING" not in _codes(report)


# Coverage rows.


def test_missing_labels_lists_metric_naming_gap() -> None:
    payload = {
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
    }
    report = check_claims(payload)
    skipped = {s.check: s.reason for s in report.coverage[0].skipped}
    assert skipped["metric naming"] == "no labels declared for a cited metric"
    assert skipped["direction"] == "no labels or order declared for a cited metric"


def test_comparison_without_series_lists_value_period_gap() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys were 5 and 9",
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "nov", "value": 9},
                ],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "nov": 9},
        "labels": {"oct": ["deploys"], "nov": ["deploys"]},
        "periods": {"oct": "October", "nov": "November"},
    }
    report = check_claims(payload)
    skipped = {s.check: s.reason for s in report.coverage[0].skipped}
    assert skipped["value-period binding"] == "cited metrics share no declared series"


def test_missing_period_beats_missing_series_in_skip_order() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys were 5 and 9",
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "nov", "value": 9},
                ],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "nov": 9},
        "labels": {"oct": ["deploys"], "nov": ["deploys"]},
        "periods": {"oct": "October"},
    }
    report = check_claims(payload)
    skipped = {s.check: s.reason for s in report.coverage[0].skipped}
    assert (
        skipped["value-period binding"]
        == "no period declared for a cited metric in the comparison"
    )


def test_metric_outside_every_series_has_no_common_series() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys were 5 in October and 9",
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "solo", "value": 9},
                ],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "solo": 9},
        "labels": {"oct": ["deploys", "october"], "solo": ["deploys"]},
        "periods": {"oct": "October", "solo": "November"},
    }
    report = check_claims(payload)
    skipped = {s.check: s.reason for s in report.coverage[0].skipped}
    assert skipped["value-period binding"] == "cited metrics share no declared series"


def test_distinct_periods_required_for_binding() -> None:
    payload = dict(_comparison_payload("Deploys were 5 in October and 9 in November"))
    payload["periods"] = {"oct": "October", "nov": "october"}
    report = check_claims(payload)
    skipped = {s.check: s.reason for s in report.coverage[0].skipped}
    assert skipped["value-period binding"] == "declared periods are not distinct"


def test_json_coverage_and_complete_flag() -> None:
    report = check_claims(_payload("Programming in last was 1.75 hours"))
    assert report.complete is False
    data = json.loads(report.to_json())
    assert data["passed"] is True
    assert data["limits"] == HARDENED_LIMITS_NOTE
    assert data["coverage"][0]["claim_id"] == "c1"
    assert data["complete"] is False
    assert any(entry["check"] == "unit" for entry in data["coverage"][0]["skipped"])
    full = check_claims(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Deploys reached 5 in October",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 5}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 5},
            "labels": {"m1": ["deploys", "october"]},
            "units": {"m1": "count"},
            "periods": {"m1": "October"},
        }
    )
    assert full.passed is True
    assert full.complete is True
    assert full.human_first_line() == "PASS"
    assert full.to_json() is not None


# Stated-change rows.


def _change_payload(text: str, right: bool) -> dict:
    nov = 9 if right else 8
    return {
        "claims": [
            {
                "id": "c1",
                "text": text,
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "nov", "value": nov},
                ],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "nov": nov},
        "labels": {"oct": ["deploys", "october"], "nov": ["deploys", "november"]},
        "order": [["oct", "nov"]],
        "units": {"oct": "count", "nov": "count"},
        "periods": {"oct": "October", "nov": "November"},
    }


def test_stated_change_right_passes() -> None:
    report = check_claims(
        _change_payload("Deploys rose by 4, 5 in October and 9 in November", True)
    )
    assert "L1B_VALUE_PERIOD_MISMATCH" not in _codes(report)


def test_stated_change_wrong_fails() -> None:
    report = check_claims(
        _change_payload("Deploys rose by 4, 5 in October and 8 in November", False)
    )
    assert "L1B_VALUE_PERIOD_MISMATCH" in _codes(report)


def test_stated_change_zero_from_equal_values_passes() -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys were 5 in October and 5 in November, a change of 0",
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "oct", "value": 5},
                    {"metric_id": "nov", "value": 5},
                ],
            }
        ],
        "facts": {},
        "metrics": {"oct": 5, "nov": 5},
        "labels": {"oct": ["deploys", "october"], "nov": ["deploys", "november"]},
        "order": [["oct", "nov"]],
        "units": {"oct": "count", "nov": "count"},
        "periods": {"oct": "October", "nov": "November"},
    }
    report = check_claims(payload)
    assert "L1B_VALUE_PERIOD_MISMATCH" not in _codes(report)


# Loader and hostile rows.


def test_new_loader_rejects_bad_unit_without_echo() -> None:
    raw = json.dumps(
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
            "units": {"m1": "hourz-canary"},
        }
    )
    with pytest.raises(VerifyInputError) as excinfo:
        load_check_input(raw)
    assert "hourz-canary" not in str(excinfo.value)
    message = str(excinfo.value)
    assert "units" in message
    for name in ("count", "hours", "minutes", "seconds", "days", "percent"):
        assert name in message


def _loader_payload(text: str) -> str:
    return json.dumps(
        {
            "claims": [{"id": "c1", "text": text, "fact_ids": [], "metric_refs": []}],
            "facts": {},
            "metrics": {},
        }
    )


def test_brackets_inside_a_string_load_in_both_loaders() -> None:
    from framework.verify import load_input as old_load

    raw = _loader_payload("Deploys held steady " + "[" * 70 + "x")
    old_load(raw)
    load_check_input(raw)


def test_brackets_inside_strings_never_change_the_depth_count() -> None:
    from framework.verify import load_input as old_load

    stringy = _loader_payload("Deploys held steady " + "[" * 200 + "x")
    old_load(stringy)
    load_check_input(stringy)
    deep = "[" * 65 + "]" * 65
    with pytest.raises(VerifyInputError):
        old_load(deep)
    with pytest.raises(VerifyInputError):
        load_check_input(deep)


def test_new_loader_matches_old_on_shared_shape() -> None:
    from framework.verify import load_input as old_load

    rows = [
        "",
        "   ",
        "[1, 2]",
        json.dumps({"claims": [], "facts": {}, "metrics": {}}),
        json.dumps(
            {
                "claims": [
                    {"id": "c1", "text": "x", "fact_ids": [], "metric_refs": []}
                ],
                "facts": {},
                "metrics": {},
                "bogus": 1,
            }
        ),
    ]
    for raw in rows:
        try:
            old_load(raw)
            old_ok = True
        except VerifyInputError:
            old_ok = False
        try:
            load_check_input(raw)
            new_ok = True
        except VerifyInputError:
            new_ok = False
        assert old_ok == new_ok, raw


def test_uncited_entry_ignored() -> None:
    payload = _payload(
        "Programming in last was 1.75 hours", units={"m1": "hours", "ghost": "count"}
    )
    assert check_claims(payload).passed is True


def test_no_message_echoes_canary() -> None:
    raw = json.dumps(
        {
            "claims": [
                {
                    "id": "canary-claim-zz",
                    "text": "Deploys reached 5",
                    "fact_ids": [],
                    "metric_refs": [{"metric_id": "m1", "value": 5}],
                }
            ],
            "facts": {},
            "metrics": {"m1": 5, "m1-canary-val": 5},
            "labels": {"m1": ["deploys"]},
            "units": {"m1": "hourz-canary"},
        }
    )
    with pytest.raises(VerifyInputError) as excinfo:
        load_check_input(raw)
    assert "canary" not in str(excinfo.value)


# Old-code preservation and freeze.


def test_old_codes_still_fire() -> None:
    from framework.verify import verify_claims as old_check

    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys reached 9",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 9}],
            }
        ],
        "facts": {},
        "metrics": {"m1": 7},
        "labels": {"m1": ["deploys"]},
    }
    old_codes = sorted(v.code for v in old_check(dict(payload)).violations)
    new_codes = sorted(v.code for v in check_claims(dict(payload)).violations)
    for code in old_codes:
        assert code in new_codes


def test_new_module_stays_outside_the_gate_closure() -> None:
    assert "framework/verify/hardened.py" not in closure_files()


def test_hardened_imports_no_underscore_briefing() -> None:
    module = ROOT / "framework" / "verify" / "hardened.py"
    for lineno, line in enumerate(module.read_text().splitlines(), 1):
        stripped = line.strip()
        if (
            stripped.startswith(("import ", "from "))
            and "framework.briefing" in stripped
        ):
            assert "._" not in stripped.replace(
                "framework.briefing.", "framework.briefing/"
            ), f"{lineno}:{stripped}"


def test_hardened_limits_note_pinned() -> None:
    assert HARDENED_LIMITS_NOTE == (
        "This check covers parseable numbers, cited sources, labels, direction, negation, quantity forms, "
        "and units and periods where you declare them. It does not check that a sentence is true. "
        "Without labels it cannot tell which metric a number belongs to, "
        "and a cited fact is only checked to exist. A check listed as not checked did not run."
    )


def test_speed_big_fact_string() -> None:
    import time

    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "The queue looks steady",
                "fact_ids": ["t1"],
                "metric_refs": [],
            }
        ],
        "facts": {"t1": "n" * 5_000_000},
        "metrics": {},
    }
    start = time.perf_counter()
    check_claims(payload)
    assert time.perf_counter() - start < 30.0


def test_speed_many_series_many_claims() -> None:
    import time

    payload = {
        "claims": [
            {
                "id": f"c{i}",
                "text": "Deploys reached 5 in October",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 5}],
            }
            for i in range(500)
        ],
        "facts": {},
        "metrics": {"m1": 5},
        "labels": {"m1": ["deploys", "october"]},
        "periods": {"m1": "October"},
        "order": [[f"s{i}a", f"s{i}b"] for i in range(5000)],
    }
    start = time.perf_counter()
    check_claims(payload)
    assert time.perf_counter() - start < 20.0


def test_speed_many_claims_many_metrics() -> None:
    import time

    payload = {
        "claims": [
            {
                "id": f"c{i}",
                "text": "Deploys reached 5",
                "fact_ids": [],
                "metric_refs": [{"metric_id": f"m{j}", "value": 5} for j in range(50)],
            }
            for i in range(200)
        ],
        "facts": {},
        "metrics": {f"m{i}": 5 for i in range(50)},
        "labels": {f"m{i}": ["deploys"] for i in range(50)},
        "units": {f"m{i}": "count" for i in range(50)},
    }
    start = time.perf_counter()
    check_claims(payload)
    assert time.perf_counter() - start < 20.0


def test_speed_many_failing_claims() -> None:
    import time

    payload = {
        "claims": [
            {
                "id": f"c{i}",
                "text": "Deploys reached 9",
                "fact_ids": [],
                "metric_refs": [{"metric_id": "m1", "value": 9}],
            }
            for i in range(2000)
        ],
        "facts": {},
        "metrics": {"m1": 7},
        "labels": {"m1": ["deploys"]},
    }
    start = time.perf_counter()
    report = check_claims(payload)
    assert time.perf_counter() - start < 20.0
    assert len(report.violations) == 2000


def test_private_term_vocab_join_exempt_with_labels() -> None:
    """Ticket 10d: the public checker excuses a private-term match made
    only by joining the claim's own vocabulary words."""
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": (
                    "Code was 0.5 hours in the last and lower than "
                    "3.25 hours in the prior period."
                ),
                "fact_ids": [],
                "metric_refs": [
                    {"metric_id": "mp", "value": 3.25},
                    {"metric_id": "ml", "value": 0.5},
                ],
            }
        ],
        "facts": {},
        "metrics": {"mp": 3.25, "ml": 0.5},
        "labels": {"mp": ["code"], "ml": ["code"]},
        "deny_terms": ["codewas", "inthelast"],
    }
    assert "L1_PRIVATE_TERM" not in _codes(check_claims(payload))


def test_private_term_outside_join_still_stopped() -> None:
    """Ticket 10d: a join touching "finch" still stops in the public
    checker, with or without labels."""
    for labels in (None, {"m1": ["notes"]}):
        payload = _base(labels)
        payload["claims"] = [_claim("The notes mention Zebra, finch today.")]
        payload["deny_terms"] = ["Zebrafinch"]
        assert "L1_PRIVATE_TERM" in _codes(check_claims(payload))
