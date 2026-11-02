"""Slice B, BD1: `python -m framework.metrics report`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from framework.briefing.commitments import load_commitments
from framework.metrics.report import build_report, render_fields
from framework.rater.delivery import inside_git_tree


def _parse_cut(raw: str | None) -> datetime:
    if raw is None:
        raise ValueError("missing cut")
    return datetime.fromisoformat(raw)


def main(argv: list[str] | None = None) -> int:
    """Run the metrics report; exit 0, 1 (identity failure) or 2 (usage)."""
    parser = argparse.ArgumentParser(prog="framework.metrics")
    commands = parser.add_subparsers(dest="command", required=True)
    report_command = commands.add_parser("report")
    report_command.add_argument("--db", required=True)
    report_command.add_argument("--as-of", default=None)
    report_command.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    as_of = None
    if args.as_of is not None:
        try:
            as_of = _parse_cut(str(args.as_of))
        except ValueError:
            print("ok=0 reason=bad_as_of")
            return 2
        if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
            print("ok=0 reason=bad_as_of")
            return 2
    subject_id = os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print("ok=0 reason=missing_subject_id")
        return 2
    if not os.environ.get("IKIGAI_COMMITMENTS_FILE", ""):
        print("ok=0 reason=missing_commitments_file")
        return 2
    loaded = load_commitments()
    if not loaded.available:
        print("ok=0 reason=commitments_unavailable")
        return 1
    code, fields = build_report(
        Path(str(args.db)),
        as_of=as_of,
        subject_id=subject_id,
        commitments=loaded.commitments,
    )
    if args.json is not None:
        target = Path(str(args.json))
        if target.is_absolute():
            resolved = target.resolve()
        else:
            resolved = (Path(os.getcwd()) / target).resolve()
        if inside_git_tree(resolved):
            print("ok=0 reason=json_path_inside_git_tree")
            return 2
        if code not in (0, 1):
            sys.stdout.write(render_fields(fields))
            return code
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fields, indent=2, sort_keys=True) + "\n")
        os.chmod(target, 0o600)
    sys.stdout.write(render_fields(fields))
    return code


if __name__ == "__main__":
    sys.exit(main())
