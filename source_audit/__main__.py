"""The audit CLI: fetch, recount, compare, run, and negative-control."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from typing import Any

from source_audit import compare as C
from source_audit import control as CTL
from source_audit import fetch as F
from source_audit import recount as R
from source_audit import report as RP
from source_audit import store as ST
from source_audit.export import ExportRefused, check_export, write_export
from source_audit.snapshot import SnapshotError, load_snapshot

_METRICS = ("prs", "pushes", "pushes_plus_prs", "all")


def _check(args: argparse.Namespace) -> str | None:
    """Return a usage code or None when the arguments are usable."""
    if args.as_of is not None and args.card is not None:
        return "USAGE_AS_OF_WITH_CARD"
    if bool(args.store) == bool(args.scratch_copy_of):
        return "USAGE_STORE_FLAG"
    try:
        R.require_tz(args.tz)
    except ValueError:
        return "USAGE_BAD_TZ"
    return None


def _do_fetch(args: argparse.Namespace) -> int:
    """Run fetch and print its row counts."""
    try:
        snapshot = F.run_fetch(args.user, args.repo, args.out)
    except (F.FetchError, SnapshotError) as exc:
        print(exc.code)
        return 2
    counts = [len(snapshot[k]) for k in ("events", "pulls", "activity")]
    print(f"events={counts[0]} pulls={counts[1]} activity={counts[2]}")
    return 0


def _do_recount(args: argparse.Namespace) -> int:
    """Run recount and print its numbers with the limits."""
    try:
        snapshot = load_snapshot(args.snapshot)
        as_of = R.parse_instant(args.as_of)
    except SnapshotError as exc:
        print(exc.code)
        return 2
    except ValueError:
        print("USAGE_BAD_INSTANT")
        return 2
    try:
        R.require_tz(args.tz)
    except ValueError:
        print("USAGE_BAD_TZ")
        return 2
    count = R.recount(snapshot, as_of, snapshot["user"], snapshot["repo"])
    for line in RP.render_recount(count, snapshot, args.tz, args.metric):
        print(line)
    return 0


def _open(args: argparse.Namespace) -> Any:
    """Open the store read-only or take a scratch copy of the live one."""
    if bool(args.store) == bool(args.scratch_copy_of):
        raise ST.StoreError("USAGE_STORE_FLAG")
    if args.store:
        return ST.open_ro(args.store), None
    scratch = ST.Scratch(args.scratch_copy_of)
    return scratch.__enter__(), scratch


def _do_compare(args: argparse.Namespace) -> int:
    """Run compare, check the export, print the report, write the export."""
    if (code := _check(args)) is not None:
        print(code)
        return 2
    try:
        conn, scratch = _open(args)
    except ST.StoreError as exc:
        print(exc.code)
        return 2
    try:
        try:
            snapshot = load_snapshot(args.snapshot)
            kw = {
                k: getattr(args, k)
                for k in ("as_of", "card", "metric", "tz", "subject")
            }
            result = C.run_compare(snapshot, conn, **kw)
        except (C.CompareError, SnapshotError, ExportRefused) as exc:
            print(exc.code)
            return 2
        try:
            check_export(result["export"])
            if args.export is not None:
                write_export(args.export, result["export"])
        except ExportRefused as exc:
            print(exc.code)
            return 2
        for line in result["lines"]:
            print(line)
        return result["exit"]
    finally:
        with contextlib.suppress(Exception):
            conn.close()
        if scratch is not None:
            scratch.__exit__(None, None, None)


def _do_run(args: argparse.Namespace) -> int:
    """Fetch into a folder, then compare and write both files."""
    if (code := _check(args)) is not None:
        print(code)
        return 2
    os.makedirs(args.out, exist_ok=True)
    try:
        F.run_fetch(args.user, args.repo, os.path.join(args.out, "snapshot.json"))
    except (F.FetchError, SnapshotError) as exc:
        print(exc.code)
        return 2
    args.snapshot = os.path.join(args.out, "snapshot.json")
    args.export = os.path.join(args.out, "export.json")
    return _do_compare(args)


def _store_args(sub: argparse.ArgumentParser) -> None:
    """Add the common store and selection options."""
    sub.add_argument("--store", default=None)
    sub.add_argument("--scratch-copy-of", default=None)
    sub.add_argument("--as-of", default=None)
    sub.add_argument("--metric", choices=_METRICS, default="all")
    sub.add_argument("--tz", default="Europe/Madrid")
    sub.add_argument("--card", default=None)
    sub.add_argument("--subject-id", dest="subject", default=None)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the five commands."""
    parser = argparse.ArgumentParser(prog="source_audit")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    for flag in ("--user", "--repo", "--out"):
        fetch.add_argument(flag, required=True)
    recount = sub.add_parser("recount")
    recount.add_argument("--snapshot", required=True)
    recount.add_argument("--as-of", required=True)
    recount.add_argument("--tz", required=True)
    recount.add_argument("--metric", required=True, choices=_METRICS)
    compare = sub.add_parser("compare")
    compare.add_argument("--snapshot", required=True)
    _store_args(compare)
    compare.add_argument("--export", default=None)
    run = sub.add_parser("run")
    run.add_argument("--user", required=True)
    run.add_argument("--repo", required=True)
    run.add_argument("--out", required=True)
    _store_args(run)
    sub.add_parser("negative-control")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run one command, and map errors to exit codes."""
    commands = {
        "fetch": _do_fetch,
        "recount": _do_recount,
        "compare": _do_compare,
        "run": _do_run,
        "negative-control": lambda a: CTL.run_control(),
    }
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return commands[args.command](args)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR_{type(exc).__name__}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
