"""CLI: read-only voice chain viewer (ticket 14)."""

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from framework.voice.worker import show_chain


def main(
    argv: list[str] | None = None,
    *,
    db_path: Path | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> int:
    """Print one voice note or a whole replacement chain; never writes."""
    _ = now_fn
    parser = argparse.ArgumentParser(
        prog="framework.voice",
        description="Show voice note chains from the local record.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    chain = sub.add_parser("show-chain", help="Print a voice note chain.")
    picked = chain.add_mutually_exclusive_group(required=True)
    picked.add_argument("--card", default=None)
    picked.add_argument("--message", type=int, default=None)
    chain.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    resolved = Path(args.db) if args.db is not None else db_path
    print(
        show_chain(resolved, card_id=args.card, message_id=args.message),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
