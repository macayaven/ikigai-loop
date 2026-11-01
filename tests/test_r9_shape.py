"""Step 6 (D31): R9 held-out shape checks.

The synthetic fixture exercises the loader with the file absent; the real
``evals/r9_cases.json`` is checked only when it exists (sha256 plus the same
shape checks), and this ticket never creates it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.r9 import CASES_PATH, REAL_FILE_SHA256, load_cases


def synthetic_file() -> dict:
    """A small file with the brief's shape: 2 commitments, 1 card, 4 cases."""
    return {
        "schema": 1,
        "commitments": [
            {"id": "write-up", "title": "Write-up", "side": "builder"},
            {"id": "run", "title": "Morning run", "side": "disconnect"},
        ],
        "card": {
            "shown_at": "2026-10-31T13:00:00+01:00",
            "proposals": [
                {
                    "label": "A",
                    "title": "Write-up",
                    "slot": "2026-10-31T14:00:00+01:00",
                },
                {
                    "label": "B",
                    "title": "Morning run",
                    "slot": "2026-10-31T14:00:00+01:00",
                },
            ],
            "cited_statement": "Screen hours decreased from 4.75 to 1.75.",
        },
        "cases": [
            {
                "id": 101,
                "now": "2026-10-31T13:30:00+01:00",
                "weekday": "Saturday",
                "transcript": "Skip the write-up today",
                "trap": None,
                "accepted": [
                    {
                        "commitment_id": "write-up",
                        "operation": "skip",
                        "until": "today",
                    }
                ],
                "requires_question": False,
                "pinned_by_coordinator_silence": [],
                "lang": "en",
                "noise": False,
            },
            {
                "id": 102,
                "now": "2026-10-31T14:05:00+01:00",
                "weekday": "Saturday",
                "transcript": "Did the morning run",
                "trap": "already_done",
                "accepted": [
                    {"commitment_id": "run", "operation": "done", "until": "today"}
                ],
                "requires_question": False,
                "pinned_by_coordinator_silence": ["until"],
                "lang": "en",
                "noise": True,
            },
            {
                "id": 103,
                "now": "2026-10-31T15:00:00+01:00",
                "weekday": "Saturday",
                "transcript": "Move it",
                "trap": "underdetermined",
                "accepted": [
                    {"commitment_id": None, "operation": "none", "until": None}
                ],
                "requires_question": True,
                "pinned_by_coordinator_silence": [],
                "lang": "mixed",
                "noise": False,
            },
            {
                "id": 104,
                "now": "2026-10-31T16:00:00+01:00",
                "weekday": "Saturday",
                "transcript": "Olvida el write-up",
                "trap": "negation",
                "accepted": [
                    {
                        "commitment_id": "write-up",
                        "operation": "drop",
                        "until": "open",
                    }
                ],
                "requires_question": False,
                "pinned_by_coordinator_silence": [],
                "lang": "es",
                "noise": False,
            },
        ],
    }


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_synthetic_fixture_loads(tmp_path: Path) -> None:
    data = load_cases(
        _write(tmp_path / "cases.json", synthetic_file()), expected_cases=4
    )
    assert [c.id for c in data.commitments] == ["write-up", "run"]
    assert [o.label for o in data.card.proposals] == ["A", "B"]
    assert [c.id for c in data.cases] == [101, 102, 103, 104]
    assert data.cases[1].pinned == ("until",)
    assert data.cases[2].requires_question is True


def test_case_count_is_checked(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path / "cases.json", synthetic_file()), expected_cases=5)


def test_unknown_trap_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    payload["cases"][0]["trap"] = "not_a_trap"
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_unknown_lang_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    payload["cases"][0]["lang"] = "fr"
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_disallowed_accepted_pair_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    payload["cases"][0]["accepted"] = [
        {"commitment_id": "write-up", "operation": "defer", "until": "slot"}
    ]
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_missing_case_field_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    del payload["cases"][0]["transcript"]
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_bool_case_id_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    payload["cases"][0]["id"] = True
    with pytest.raises(TypeError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_float_case_id_is_rejected(tmp_path: Path) -> None:
    payload = synthetic_file()
    assert isinstance(payload["cases"], list)
    payload["cases"][0]["id"] = 1.5
    with pytest.raises(TypeError):
        load_cases(_write(tmp_path / "cases.json", payload), expected_cases=4)


def test_real_file_shape_conditional() -> None:
    """Only when the held-out file exists: pinned sha256 plus shape checks."""
    path = Path(str(CASES_PATH))
    if not path.exists():
        pytest.skip("held-out set absent")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == REAL_FILE_SHA256
    data = load_cases(path)
    assert len(data.cases) == 60
