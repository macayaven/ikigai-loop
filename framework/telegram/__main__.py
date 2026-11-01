"""CLI: send the sample card or poll for taps (ticket 12)."""

import argparse
import sys
from collections.abc import Callable
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from framework.telegram.client import TelegramClient
from framework.telegram.models import PollStats
from framework.telegram.sample import SAMPLE_CARD, SAMPLE_CHART
from framework.telegram.service import poll_once, run_poll_loop, send_card


def _counts_line(stats: PollStats) -> str:
    return " ".join(
        f"{item.name}={getattr(stats, item.name)}" for item in fields(stats)
    )


def main(
    argv: list[str] | None = None,
    *,
    client: TelegramClient | None = None,
    db_path: Path | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> int:
    """Send the sample card or poll; print only counts or an error line."""
    parser = argparse.ArgumentParser(
        prog="framework.telegram",
        description="Send the sample card or poll for taps.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("send-sample", help="Send the sample card once.")
    poll_parser = sub.add_parser("poll", help="Poll for taps.")
    poll_parser.add_argument("--once", action="store_true")
    poll_parser.add_argument("--long-poll", type=int, default=None)
    args = parser.parse_args(argv)
    if args.command == "send-sample":
        return _send_sample(client, db_path)
    if args.long_poll is not None and (args.long_poll < 0 or args.long_poll > 50):
        parser.error("--long-poll must be 0-50")
    if args.once:
        long_poll = args.long_poll if args.long_poll is not None else 0
        return _poll_once(client, db_path, long_poll, now_fn)
    return _poll_loop(
        client, db_path, args.long_poll if args.long_poll is not None else 50, now_fn
    )


def _send_sample(client: TelegramClient | None, db_path: Path | None) -> int:
    try:
        sent = send_card(SAMPLE_CARD, SAMPLE_CHART, db_path=db_path, client=client)
    except Exception as exc:  # noqa: BLE001 - error line, not a catch-all
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    print(f"sent card_id={sent.card_id} message_id={sent.message_id}", flush=True)
    return 0


def _poll_once(
    client: TelegramClient | None,
    db_path: Path | None,
    long_poll_s: int,
    now_fn: Callable[[], datetime] | None,
) -> int:
    try:
        stats = poll_once(
            db_path=db_path,
            client=client,
            long_poll_s=long_poll_s,
            now_fn=now_fn,
        )
    except KeyboardInterrupt:
        print(_counts_line(PollStats()), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - error line, not a catch-all
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    print(_counts_line(stats), flush=True)
    return 0


def _poll_loop(
    client: TelegramClient | None,
    db_path: Path | None,
    long_poll_s: int,
    now_fn: Callable[[], datetime] | None,
) -> int:
    last = PollStats()

    def _on_batch(stats: PollStats) -> None:
        nonlocal last
        last = stats
        print(_counts_line(stats), flush=True)

    try:
        total = run_poll_loop(
            db_path=db_path,
            client=client,
            long_poll_s=long_poll_s,
            now_fn=now_fn,
            on_batch=_on_batch,
        )
    except KeyboardInterrupt:
        print(_counts_line(last), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - error line, not a catch-all
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    print(_counts_line(total), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
