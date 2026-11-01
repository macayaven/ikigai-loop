"""Ticket 17a: foreign adapter example (fails until the reviewer recipe lands).

The recipe in docs/ADAPTER.md writes adapter.py and test_adapter.py under
examples/verify/foreign/ in reviewer step AT11. Until then this file is the
one expected failure, naming the missing files.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FOREIGN = ROOT / "examples" / "verify" / "foreign"
ADAPTER = FOREIGN / "adapter.py"
RECIPE_TESTS = FOREIGN / "test_adapter.py"


def _recipe_present() -> bool:
    return ADAPTER.exists() and RECIPE_TESTS.exists()


def test_recipe_files_present() -> None:
    assert _recipe_present(), (
        "missing recipe files: examples/verify/foreign/adapter.py and "
        "examples/verify/foreign/test_adapter.py are written by the reviewer "
        "recipe step (docs/ADAPTER.md, AT11), not by the implementation session"
    )


def _load_adapter():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("foreign_adapter", ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not _recipe_present(), reason="reviewer recipe step AT11 has not landed"
)
def test_adapter_maps_sample_to_promised_verdict() -> None:
    import json

    from framework.verify import verify_claims

    adapter = _load_adapter()
    agent_output = json.loads((FOREIGN / "agent-output.json").read_text())
    source_data = json.loads((FOREIGN / "source-data.json").read_text())
    report = verify_claims(adapter.to_verify_input(agent_output, source_data))
    assert report.passed is False
    assert [v.code for v in report.violations] == ["L1B_METRIC_VALUE_MISMATCH"]


@pytest.mark.skipif(
    not _recipe_present(), reason="reviewer recipe step AT11 has not landed"
)
def test_adapter_facts_and_metrics_come_only_from_source() -> None:
    import copy
    import json

    adapter = _load_adapter()
    agent_output = json.loads((FOREIGN / "agent-output.json").read_text())
    source_data = json.loads((FOREIGN / "source-data.json").read_text())
    before = adapter.to_verify_input(agent_output, source_data)
    mutated = copy.deepcopy(agent_output)
    mutated["report"]["statements"][0]["figures"][0]["figure"] = 999
    after = adapter.to_verify_input(mutated, source_data)
    assert after["metrics"] == before["metrics"]
    assert after["facts"] == before["facts"]


@pytest.mark.skipif(
    not _recipe_present(), reason="reviewer recipe step AT11 has not landed"
)
def test_adapter_missing_provenance_raises() -> None:
    import copy
    import json

    adapter = _load_adapter()
    agent_output = json.loads((FOREIGN / "agent-output.json").read_text())
    source_data = json.loads((FOREIGN / "source-data.json").read_text())
    mutated = copy.deepcopy(agent_output)
    mutated["report"]["statements"][0]["figures"].append(
        {"field": "unmapped_field", "figure": 1}
    )
    with pytest.raises(adapter.MissingProvenance):
        adapter.to_verify_input(mutated, source_data)


@pytest.mark.skipif(
    not _recipe_present(), reason="reviewer recipe step AT11 has not landed"
)
def test_recipe_tests_pass_under_unittest() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "test_adapter", "-v"],
        capture_output=True,
        text=True,
        cwd=FOREIGN,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
