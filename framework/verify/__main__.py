"""Ticket 17a: verify-claims command line."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, cast

from framework.verify.core import (
    MAX_INPUT_BYTES,
    VerifyInputError,
    format_report,
    verify_claims,
)


def _read_input(path: str) -> bytes:
    try:
        if path == "-":
            buffered = getattr(sys.stdin, "buffer", None)
            if buffered is None:
                raise VerifyInputError("input file cannot be read")
            return buffered.read(MAX_INPUT_BYTES + 1)
        with open(path, "rb") as handle:
            return handle.read(MAX_INPUT_BYTES + 1)
    except VerifyInputError:
        raise
    except (OSError, ValueError):
        raise VerifyInputError("input file cannot be read") from None


def _warn(text: str) -> None:
    """Write a usage or bad-input message; a closed stderr is not an error."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text)
    except OSError:
        pass


def _emit(text: str) -> None:
    """Write the report; a closed pipe is not an error.

    On ``OSError`` stdout is pointed at devnull so the
    interpreter's exit flush stays quiet, and the caller still returns
    the verdict's normal exit code.
    """
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except OSError:
        # Kept open on purpose: it becomes sys.stdout below.
        devnull = open(os.devnull, "w")  # noqa: SIM115
        try:
            os.dup2(devnull.fileno(), 1)
        except OSError:
            pass
        sys.stdout = devnull


def main(argv: list[str] | None = None) -> int:
    """Run the checker: exit 0 on pass, 1 on violations, 2 on bad input."""
    if hasattr(sys.stdout, "reconfigure"):
        cast("Any", sys.stdout).reconfigure(errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        cast("Any", sys.stderr).reconfigure(errors="backslashreplace")
    args = sys.argv[1:] if argv is None else argv
    as_json = False
    positional: list[str] = []
    for token in args:
        if token == "--json":
            as_json = True
        elif token == "-" or not token.startswith("-"):
            positional.append(token)
        else:
            _warn("usage: verify-claims [--json] <input.json|->\n")
            return 2
    if len(positional) != 1:
        _warn("usage: verify-claims [--json] <input.json|->\n")
        return 2
    try:
        report = verify_claims(_read_input(positional[0]))
    except KeyboardInterrupt:
        return 130
    except VerifyInputError as exc:
        _warn(f"{exc}\n")
        return 2
    if as_json:
        _emit(
            json.dumps(
                {
                    "passed": report.passed,
                    "limits": report.limits,
                    "violations": [
                        {
                            "code": item.code,
                            "claim_id": item.claim_id,
                            "message": item.message,
                        }
                        for item in report.violations
                    ],
                }
            )
            + "\n"
        )
    else:
        _emit(format_report(report) + "\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
