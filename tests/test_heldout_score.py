"""Tests for the held-out checker scorer.

The score is a record of one commit: no test runs the 40 cases through the
live checker, so a later checker change cannot turn this record into a
failing test.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals.heldout_score import (
    FROZEN_SHA256,
    bucket_for,
    checked_data,
    extract_input_texts,
    verdict_for_exit,
)

DATA_PATH = Path("evals/heldout/checker-heldout-v1.json")


@pytest.mark.parametrize(
    ("expected", "exit_code", "bucket"),
    [
        ("PASS", 0, "true_pass"),
        ("FAIL", 1, "true_fail"),
        ("FAIL", 0, "false_pass"),
        ("PASS", 1, "false_fail"),
        ("PASS", 2, "no_verdict"),
        ("FAIL", 2, "no_verdict"),
        ("PASS", 7, "no_verdict"),
        ("FAIL", 7, "no_verdict"),
        ("PASS", -1, "no_verdict"),
        ("FAIL", 130, "no_verdict"),
    ],
)
def test_bucket_mapping(expected: str, exit_code: int, bucket: str) -> None:
    assert verdict_for_exit(exit_code) == (
        "PASS" if exit_code == 0 else "FAIL" if exit_code == 1 else None
    )
    assert bucket_for(expected, exit_code) == bucket


def test_raw_input_texts_parse_to_case_inputs() -> None:
    raw = DATA_PATH.read_text(encoding="utf-8")
    cases = json.loads(raw)
    texts = extract_input_texts(raw, len(cases))
    assert len(texts) == 40
    for case, text in zip(cases, texts, strict=True):
        assert json.loads(text) == case["input"]
        assert text not in (json.dumps(case["input"]),)


def test_refuses_tampered_copy(tmp_path: Path) -> None:
    copy = tmp_path / "checker-heldout-v1.json"
    data = bytearray(DATA_PATH.read_bytes())
    data[10] ^= 0x01
    copy.write_bytes(bytes(data))
    assert hashlib.sha256(copy.read_bytes()).hexdigest() != FROZEN_SHA256
    with pytest.raises(ValueError, match="refusing to score"):
        checked_data(copy)
    proc = subprocess.run(
        [sys.executable, "evals/heldout_score.py", str(copy)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
