"""Ticket 14 Step 5: no matcher in production, and the service seam (D30, D2).

No keyword path may turn a transcript into an operation: the only way is
the compile call plus coded validation. The literal matcher lives in
``evals/`` for the R9 baseline alone. Synthetic checks only, no network.
"""

from __future__ import annotations

from pathlib import Path

# Names ported from the D31 matcher rules; none may appear under framework/.
# Whole identifiers only: the frozen schema module holds ``_UNTIL_WORDS``
# (until display words), which is not the matcher's ``UNTIL_WORDS`` table.
_MATCHER_RES = (
    r"r9_matcher",
    r"(?<![A-Za-z0-9_])OPERATION_WORDS(?![A-Za-z0-9_])",
    r"(?<![A-Za-z0-9_])UNTIL_WORDS(?![A-Za-z0-9_])",
)


def _framework_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "framework"
    return [path for path in root.rglob("*.py") if path.is_file()]


def test_no_matcher_filename_under_framework() -> None:
    hits = [str(path) for path in _framework_files() if "matcher" in path.name]
    assert hits == []


def test_no_matcher_import_or_symbol_under_framework() -> None:
    import re

    hits: list[str] = []
    for path in _framework_files():
        text = path.read_text(encoding="utf-8")
        if any(re.search(mark, text) for mark in _MATCHER_RES):
            hits.append(str(path))
    assert hits == []


def test_service_imports_nothing_from_voice() -> None:
    text = (
        Path(__file__).resolve().parent.parent / "framework" / "telegram" / "service.py"
    ).read_text(encoding="utf-8")
    assert "framework.voice" not in text
    assert "framework/voice" not in text
