"""Slice A, AD11: `python -m framework.rater pack|score`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from framework.rater.pack import build_pack
from framework.rater.score import parse_cut, score_pairs


def _pack_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--db", required=True)
    command.add_argument("--out-dir", required=True)
    command.add_argument("--seed", required=True)
    command.add_argument("--cut", default=None)
    command.add_argument("--pack-id", default=None)
    command.add_argument("--exclude-key", action="append", default=[])


def _score_args(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--pair", action="append", default=[], nargs=2, metavar=("KEY", "RESULT")
    )
    command.add_argument("--db", default=None)


def main(argv: list[str] | None = None) -> int:
    """Run one rater subcommand; exit 0, 1 (data refusal) or 2 (usage)."""
    parser = argparse.ArgumentParser(prog="framework.rater")
    commands = parser.add_subparsers(dest="command", required=True)
    pack_command = commands.add_parser("pack")
    _pack_args(pack_command)
    score_command = commands.add_parser("score")
    _score_args(score_command)
    args = parser.parse_args(argv)
    if args.command == "pack":
        try:
            seed = int(str(args.seed))
        except ValueError:
            print("ok=0 reason=bad_seed")
            return 2
        try:
            cut = parse_cut(args.cut)
        except ValueError:
            print("ok=0 reason=bad_cut")
            return 2
        code, fields = build_pack(
            db=Path(str(args.db)),
            out_dir=Path(str(args.out_dir)),
            seed=seed,
            cut=cut,
            pack_id=args.pack_id,
            exclude_keys=[Path(str(path)) for path in args.exclude_key],
            environ=os.environ,
        )
        for name in sorted(fields):
            print(f"{name}={fields[name]}")
        return code
    if not args.pair:
        print("ok=0 reason=missing_pair")
        return 2
    code, lines = score_pairs(
        [(Path(key), Path(result)) for key, result in args.pair],
        db=Path(str(args.db)) if args.db else None,
    )
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
