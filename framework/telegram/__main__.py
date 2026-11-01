"""CLI: send the sample card or poll for taps (ticket 12, voice in 14)."""

import argparse
import sys
from collections.abc import Callable
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from framework.proposal.client import EFFORTS, refuse_contributor_model
from framework.proposal.core import ContributorModelRefused
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
    poll_parser.add_argument("--voice", action="store_true")
    poll_parser.add_argument("--compile-model", default="muse-spark-1.3")
    poll_parser.add_argument("--compile-effort", default="minimal")
    poll_parser.add_argument("--correction-model", default="muse-wonder-1.0")
    poll_parser.add_argument("--correction-effort", default="low")
    args = parser.parse_args(argv)
    if args.command == "send-sample":
        return _send_sample(client, db_path)
    if args.long_poll is not None and (args.long_poll < 0 or args.long_poll > 50):
        parser.error("--long-poll must be 0-50")
    if args.voice:
        _check_voice_args(parser, args)
        return _poll_voice(client, db_path, args, now_fn)
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


def _check_voice_args(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Refuse bad voice efforts and contributor models before any runner call."""
    if args.compile_effort not in EFFORTS:
        parser.error("--compile-effort must be minimal|low|medium|high")
    if args.correction_effort not in EFFORTS:
        parser.error("--correction-effort must be minimal|low|medium|high")
    try:
        refuse_contributor_model(args.compile_model)
        refuse_contributor_model(args.correction_model)
    except ContributorModelRefused as exc:
        parser.error(str(exc))


def _poll_voice(
    client: TelegramClient | None,
    db_path: Path | None,
    args: argparse.Namespace,
    now_fn: Callable[[], datetime] | None,
) -> int:
    """Poll with the voice worker; startup prints codes only, then counts."""
    import os
    import threading

    from framework.voice.mode import contributor_mode_status
    from framework.voice.worker import (
        VoiceWorker,
        build_voice_deps,
        make_voice_handler,
    )

    environ = dict(os.environ)
    codes = contributor_mode_status(environ)
    print(
        "voice_contributor_mode=" + ("confirmed" if not codes else ",".join(codes)),
        flush=True,
    )
    deps = build_voice_deps(
        environ,
        client=client if client is not None else TelegramClient(),
        db_path=db_path,
        now_fn=now_fn,
        compile_model=args.compile_model,
        compile_effort=args.compile_effort,
        correction_model=args.correction_model,
        correction_effort=args.correction_effort,
    )
    terms = deps.load_private_terms_fn()
    print(
        f"voice_private_terms={'ok' if terms.available else 'unavailable'}",
        flush=True,
    )
    loaded = deps.load_commitments_fn()
    print(
        f"voice_commitments={'ok' if loaded.available else 'unavailable'}",
        flush=True,
    )
    wake = threading.Event()
    worker = VoiceWorker(deps, wake)
    long_poll = args.long_poll if args.long_poll is not None else 50
    if args.once:
        try:
            stats = poll_once(
                db_path=db_path,
                client=client,
                long_poll_s=args.long_poll if args.long_poll is not None else 0,
                on_voice=make_voice_handler(wake),
                now_fn=now_fn,
            )
        except KeyboardInterrupt:
            print(_counts_line(PollStats()), flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001 - error line, not a catch-all
            print(f"error: {exc}", file=sys.stderr, flush=True)
            return 1
        print(_counts_line(stats), flush=True)
        worker.drain(timeout_s=120.0)
        return 0
    last = PollStats()

    def _on_batch(stats: PollStats) -> None:
        nonlocal last
        last = stats
        print(_counts_line(stats), flush=True)

    worker.start()
    try:
        total = run_poll_loop(
            db_path=db_path,
            client=client,
            long_poll_s=long_poll,
            on_voice=make_voice_handler(wake),
            now_fn=now_fn,
            on_batch=_on_batch,
        )
    except KeyboardInterrupt:
        print(_counts_line(last), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - error line, not a catch-all
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        worker.stop()
    print(_counts_line(total), flush=True)
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
