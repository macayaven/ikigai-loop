"""Ticket 26: domain pack command line (show, check, propose)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from framework.domains.csv_adapter import (
    IdentityError,
    SourceHashMismatch,
    WindowError,
    build_reference,
)
from framework.domains.runner import git_commit, run_window
from framework.domains.schema import DomainPack, PackError, load_pack
from framework.proposal.core import WonderClient
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
from framework.verify.core import VerifyInputError
from framework.verify.hardened import check_claims, format_check_report


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _load_pack(path: str) -> DomainPack | None:
    try:
        return load_pack(path)
    except PackError:
        return None


def _cmd_show(pack_path: str, window: str) -> int:
    pack = _load_pack(pack_path)
    if pack is None:
        return _fail("pack is invalid")
    try:
        ref = build_reference(pack, str(Path(pack_path).parent), window)
    except (WindowError, SourceHashMismatch, IdentityError):
        return _fail("window cannot be built")
    for metric_id in ref.metrics:
        labels = " ".join(ref.labels[metric_id])
        print(
            f"{metric_id}: {ref.metrics[metric_id]} "
            f"[{labels}] ({ref.units[metric_id]}; {ref.periods[metric_id]})"
        )
    for item in ref.identities:
        if item.held:
            print(
                f"identity {item.kind}: held on "
                f"{item.dates_checked} of {item.dates_checked} dates"
            )
        else:
            print(f"identity {item.kind}: did not hold")
    held = sum(1 for item in ref.identities if item.held)
    print(f"identities: {held} of {len(ref.identities)} hold")
    return 0


def _cmd_check(pack_path: str, window: str, claims_path: str) -> int:
    pack = _load_pack(pack_path)
    if pack is None:
        return _fail("pack is invalid")
    try:
        raw = Path(claims_path).read_bytes()
    except OSError:
        return _fail("claims file cannot be read")
    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except ValueError:
        return _fail("claims file is not valid JSON")
    if not isinstance(parsed, list):
        return _fail("claims file must hold a JSON list")
    claims = cast("list[Any]", parsed)
    try:
        ref = build_reference(pack, str(Path(pack_path).parent), window)
    except (WindowError, SourceHashMismatch, IdentityError):
        return _fail("window cannot be built")
    try:
        report = check_claims(ref.check_input(claims))
    except VerifyInputError:
        return _fail("claims are not valid checker input")
    print(format_check_report(report))
    return 0 if report.passed else 1


def _default_factory() -> WonderClient:
    from framework.proposal.muse_client import MuseExecClient

    return MuseExecClient(private_terms=(), private_terms_available=True)


def _cmd_propose(
    pack_path: str,
    window: str,
    model: str,
    effort: str,
    out: str | None,
    client_factory: Callable[[], WonderClient] | None,
) -> int:
    pack = _load_pack(pack_path)
    if pack is None:
        return _fail("pack is invalid")
    try:
        ref = build_reference(pack, str(Path(pack_path).parent), window)
    except (WindowError, SourceHashMismatch, IdentityError):
        return _fail("window cannot be built")
    factory = client_factory or _default_factory
    run = run_window(pack, ref, factory(), model=model, effort=effort)
    if out is not None:
        payload = dict(run.to_json())
        payload["git_commit"] = git_commit()
        try:
            Path(out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        except OSError:
            return _fail("run file cannot be written")
    if run.transport_error is not None:
        print(f"TRANSPORT {run.transport_error}")
        return 1
    attempts = len(run.attempts)
    if run.final_passed:
        print(f"PASS {run.expected_commitment} after {attempts} attempt(s)")
        return 0
    print(f"FAIL {run.expected_commitment} after {attempts} attempt(s)")
    return 1


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[], WonderClient] | None = None,
) -> int:
    """Run the domain pack CLI; returns the exit code."""
    parser = argparse.ArgumentParser(description="Domain packs for one domain.")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--pack", required=True)
    show.add_argument("--window", required=True)
    check = sub.add_parser("check")
    check.add_argument("--pack", required=True)
    check.add_argument("--window", required=True)
    check.add_argument("--claims", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--pack", required=True)
    propose.add_argument("--window", required=True)
    propose.add_argument("--model", default=DEFAULT_MODEL)
    propose.add_argument("--effort", default=DEFAULT_EFFORT)
    propose.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    command: str = args.command
    if command == "show":
        return _cmd_show(str(args.pack), str(args.window))
    if command == "check":
        return _cmd_check(str(args.pack), str(args.window), str(args.claims))
    if command == "propose":
        return _cmd_propose(
            str(args.pack),
            str(args.window),
            str(args.model),
            str(args.effort),
            args.out if args.out is None else str(args.out),
            client_factory,
        )
    return _fail("unknown command")


if __name__ == "__main__":
    sys.exit(main())
