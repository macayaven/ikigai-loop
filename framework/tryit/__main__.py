"""Ticket 21: try-ikigai command line."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Any, cast

from framework.tryit.replay import PICKS, ReplayMismatch, run_replay
from framework.tryit.text import build_output


def _warn(text: str) -> None:
    """Write a usage or failure line; a closed stderr is not an error."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text)
    except OSError:
        pass


def _emit(text: str) -> None:
    """Write the story; a closed pipe is not an error.

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
        devnull = open(os.devnull, "w")  # noqa: SIM115
        try:
            os.dup2(devnull.fileno(), 1)
        except OSError:
            pass
        sys.stdout = devnull  # type: ignore[assignment]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="try-ikigai",
        allow_abbrev=False,
        description=(
            "Replay packaged made-up data through the real fact, proposal, "
            "gate, card, chart and tap code and print the five-section story. "
            "No key, no model, no phone, no account; nothing is stored."
        ),
    )
    parser.add_argument(
        "--pick",
        choices=list(PICKS),
        default="A",
        help="which side the simulated tap takes (default: A)",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        default=None,
        help="write the chart image to PATH and say where it went",
    )
    return parser


def _write_save(path_text: str, png: bytes) -> str | None:
    """Write the chart bytes, or return a one-line error when refused.

    Never hangs: an existing path of any form that is not a regular file
    (directory, fifo, socket, symlink, ...) is refused without opening it.
    A regular file holding the same bytes is left untouched; holding other
    bytes it is refused. Otherwise the file is created exclusively.
    """
    try:
        st = os.lstat(path_text)
    except FileNotFoundError:
        pass
    except OSError:
        return f"try-ikigai: cannot write {path_text}\n"
    else:
        if not stat.S_ISREG(st.st_mode):
            return f"try-ikigai: refusing to overwrite {path_text}\n"
        try:
            if Path(path_text).read_bytes() == png:
                return None
        except OSError:
            return f"try-ikigai: cannot write {path_text}\n"
        return f"try-ikigai: refusing to overwrite {path_text}\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path_text, flags, 0o644)
    except OSError:
        return f"try-ikigai: cannot write {path_text}\n"
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(png)
    except OSError:
        try:
            os.unlink(path_text)
        except OSError:
            pass
        return f"try-ikigai: cannot write {path_text}\n"
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the replay: exit 0 on the recorded story, 1 on drift, 2 on misuse."""
    if hasattr(sys.stdout, "reconfigure"):
        cast("Any", sys.stdout).reconfigure(errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        cast("Any", sys.stderr).reconfigure(errors="backslashreplace")
    args = sys.argv[1:] if argv is None else argv
    try:
        parsed = _parser().parse_args(args)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        return 2
    try:
        result = run_replay(pick=parsed.pick)
    except ReplayMismatch as exc:
        _warn(f"try-ikigai: replay drifted: {exc}\n")
        return 1
    if parsed.save is not None:
        error = _write_save(parsed.save, result.png)
        if error is not None:
            _warn(error)
            return 2
    _emit(build_output(result, parsed.pick, parsed.save))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
