"""Ticket 17a: build docs/verify/bundle.json from the import closure.

A fresh interpreter imports ``framework.verify`` and lists the loaded
modules whose files sit under ``framework/``; those sources ship as text
so the browser page runs the same code with no wheel and no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs" / "verify" / "bundle.json"


def closure_paths() -> list[str]:
    """Repo-relative paths of every loaded module under ``framework/``."""
    script = (
        "import sys",
        "import framework.verify",
        "for name in sorted(sys.modules):",
        "    path = getattr(sys.modules[name], '__file__', None)",
        "    if path:",
        "        print(path)",
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run(
        [sys.executable, "-c", "\n".join(script)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=120,
        check=True,
    )
    found: list[str] = []
    for line in proc.stdout.splitlines():
        try:
            rel = Path(line).resolve().relative_to((ROOT / "framework").resolve())
        except ValueError:
            continue
        found.append("framework/" + rel.as_posix())
    return sorted(set(found))


def build_bundle_text() -> str:
    """The exact bytes of ``bundle.json``: sorted keys, indent 1, newline."""
    files = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in closure_paths()}
    return json.dumps(files, sort_keys=True, indent=1) + "\n"


def main() -> int:
    """Write the bundle; rerun whenever the closure changes."""
    TARGET.write_text(build_bundle_text(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
