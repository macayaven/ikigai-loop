"""Render both sample manifests to gitignored out/ for manual viewing (ticket 6)."""

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from framework.blocks.context import RenderContext
from framework.blocks.render import render_manifest
from framework.schemas.manifest import Manifest

MADRID = ZoneInfo("Europe/Madrid")


def _repo_root() -> Path:
    """Repo root resolved from this file, never from the working directory."""
    return Path(__file__).resolve().parents[2]


def _synthetic_context() -> RenderContext:
    """Fixed synthetic context shared by both sample renders."""
    return RenderContext.model_validate(
        {
            "free_slots": [
                {
                    "start": datetime(2026, 10, 31, 15, 0, tzinfo=MADRID).isoformat(),
                    "end": datetime(2026, 10, 31, 15, 30, tzinfo=MADRID).isoformat(),
                    "label": "Synthetic slot",
                },
                {
                    "start": datetime(2026, 10, 31, 16, 0, tzinfo=MADRID).isoformat(),
                    "end": datetime(2026, 10, 31, 16, 30, tzinfo=MADRID).isoformat(),
                    "label": "Synthetic slot",
                },
            ],
            "facts": [
                {"id": "fact_builder_1", "text": "Synthetic builder fact one line"},
                {"id": "fact_recovery_1", "text": "Synthetic recovery fact one line"},
            ],
            "links": [],
        }
    )


def main(argv: list[str] | None = None) -> int:
    """Render both fixtures to out/; print only the two written paths."""
    parser = argparse.ArgumentParser(prog="framework.blocks")
    parser.parse_args(argv)
    root = _repo_root()
    context = _synthetic_context()
    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sample-builder", "sample-recovery"):
        manifest = Manifest.model_validate_json(
            (root / "tests" / "fixtures" / f"{name}.json").read_text()
        )
        (out_dir / f"{name}.html").write_text(render_manifest(manifest, context))
        print(f"wrote out/{name}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
