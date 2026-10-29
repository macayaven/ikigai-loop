"""Ticket 3: committed JSON Schemas must not drift from the models."""

import json
import shutil
from pathlib import Path

from framework.schemas.export_schemas import EXPORTED_MODELS, find_drift, schema_text

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def test_committed_schemas_match_models() -> None:
    assert find_drift(SCHEMAS_DIR) == []


def test_one_schema_file_per_exported_model() -> None:
    expected = {f"{model.__name__}.json" for model in EXPORTED_MODELS}
    actual = {path.name for path in SCHEMAS_DIR.glob("*.json")}
    assert actual == expected
    for model in EXPORTED_MODELS:
        parsed = json.loads(
            (SCHEMAS_DIR / f"{model.__name__}.json").read_text(encoding="utf-8")
        )
        assert parsed == json.loads(schema_text(model))


def test_drift_check_fails_naming_the_model(tmp_path: Path) -> None:
    copied = tmp_path / "schemas"
    shutil.copytree(SCHEMAS_DIR, copied)
    target = copied / "HealthDailyData.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert find_drift(copied) == ["HealthDailyData"]
