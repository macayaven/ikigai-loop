"""Ticket 15b, Step 6: wiring tests (D7, D14, D46).

Docs regenerate from stored rows only; stored rows pass the hygiene
scan; --summary for R3 and R4 constructs no client. No model, no
network, no real ``muse`` binary.
"""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path
from typing import Any

from evals import r3, r4
from evals.r1b import GATE_SOURCE_FILES
from framework.proposal import muse_client

REPO = Path(__file__).resolve().parent.parent
R3_DIR = REPO / "evals" / "results" / "r3"
R4_DIR = REPO / "evals" / "results" / "r4"
R2_PATH = REPO / "evals" / "results" / "r2.json"
PROMPT_FILE = "framework/proposal/prompt.py"

_TOKEN_SHAPE = re.compile(r"sk-[A-Za-z0-9_-]{6,}")


def _r3_files() -> list[Path]:
    files = sorted(R3_DIR.glob("*.jsonl"))
    assert files, "no stored R3 rows"
    return files


def _r4_files() -> list[Path]:
    files = sorted(R4_DIR.glob("*.jsonl"))
    assert files, "no stored R4 rows"
    return files


def test_r3_doc_matches_summary_from_stored_rows(capsys: Any) -> None:
    code = r3.main(["--summary", "--results-dir", str(R3_DIR)])
    assert code == 0
    out = capsys.readouterr().out
    assert out == (REPO / "docs" / "r3.md").read_text(encoding="utf-8")


def test_r4_doc_matches_summary_from_stored_rows(capsys: Any) -> None:
    code = r4.main(["--summary", "--results-dir", str(R4_DIR)])
    assert code == 0
    out = capsys.readouterr().out
    assert out == (REPO / "docs" / "r4.md").read_text(encoding="utf-8")


class _RaisesOnConstruction:
    """Tripwire: --summary must never construct a client."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("client constructed during --summary")


def test_summaries_construct_no_client(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(r3, "MuseExecClient", _RaisesOnConstruction)
    monkeypatch.setattr(muse_client, "MuseExecClient", _RaisesOnConstruction)
    assert r3.main(["--summary", "--results-dir", str(R3_DIR)]) == 0
    capsys.readouterr()
    assert r4.main(["--summary", "--results-dir", str(R4_DIR)]) == 0
    capsys.readouterr()


def _scanned_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "*.jsonl"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    tracked = [
        REPO / line
        for line in proc.stdout.splitlines()
        if line.strip() and (REPO / line.strip()).is_file()
    ]
    local = [R2_PATH, *sorted(R3_DIR.glob("*.jsonl")), *sorted(R4_DIR.glob("*.jsonl"))]
    seen: dict[str, Path] = {}
    for path in [*tracked, *local]:
        seen[str(path)] = path
    return sorted(seen.values())


def test_stored_rows_pass_hygiene_scan() -> None:
    files = _scanned_files()
    assert R2_PATH in files
    for path in _r3_files():
        assert path in files
    for path in _r4_files():
        assert path in files
    home = str(Path.home())
    hostname = socket.gethostname()
    identity_abs = [str(REPO / rel) for rel in (*GATE_SOURCE_FILES, PROMPT_FILE)]
    assert len(identity_abs) == 9
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert home not in text, (path, "home dir")
        assert "/home/" not in text, (path, "/home/")
        assert "/Users/" not in text, (path, "/Users/")
        if len(hostname) > 2:
            assert hostname not in text, (path, "hostname")
        assert "Bearer " not in text, (path, "bearer")
        assert _TOKEN_SHAPE.search(text) is None, (path, "secret shape")
        for abs_path in identity_abs:
            assert abs_path not in text, (path, abs_path)
