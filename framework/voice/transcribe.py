"""Ticket 14: the guarded transcription client.

One code path for every clip: the downloaded bytes are written to
``note.oga`` in one 0700 directory, converted to 16 kHz mono WAV with the
plan's conversion command, then passed to the subscription call. Both files
are 0600 and the directory is removed on every path. The mode check runs
first: a refused check returns ``mode_not_confirmed`` with zero runner
calls and no temp file. The child environment never holds the API key and
always pins the contributor variable; output other than stdout is ignored
because the default runner already sends it away.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from framework.proposal import muse_client as _muse_client
from framework.proposal.muse_client import resolve_muse_bin
from framework.voice.mode import contributor_mode_status

TranscriptionKind = Literal[
    "words", "silence", "unreadable", "unavailable", "mode_not_confirmed"
]

_FFMPEG_ARGV_TAIL: tuple[str, ...] = ("-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le")


@dataclass(frozen=True)
class TranscriptionResult:
    """One transcription attempt: the closed kind, the heard text, step times."""

    kind: TranscriptionKind
    text: str
    convert_s: float
    transcribe_s: float


class MuseVoiceTranscriber:
    """Convert one clip, then transcribe it through the runner seam."""

    def __init__(
        self,
        *,
        muse_bin: str | None = None,
        ffmpeg_bin: str = "ffmpeg",
        runner: _muse_client.Runner | None = None,
        convert_timeout_s: float = 30.0,
        timeout_s: float = 60.0,
        environ: Mapping[str, str] | None = None,
        settings_path: Path | None = None,
    ) -> None:
        self._muse_bin = muse_bin if muse_bin is not None else resolve_muse_bin(environ)
        self._ffmpeg_bin = ffmpeg_bin
        self._runner = runner if runner is not None else _muse_client._default_runner  # pyright: ignore[reportPrivateUsage]
        self._convert_timeout_s = convert_timeout_s
        self._timeout_s = timeout_s
        self._environ = environ
        self._settings_path = settings_path

    def _child_env(self) -> dict[str, str]:
        if self._environ is None:
            env = dict(os.environ)
        else:
            env = dict(self._environ)
        env.pop("META_API_KEY", None)
        env["MUSE_CONTRIBUTOR_MODE"] = "0"
        return env

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        """Convert ``audio`` and transcribe it; never raises on audio trouble."""
        if contributor_mode_status(
            self._environ if self._environ is not None else os.environ,
            settings_path=self._settings_path,
        ):
            return TranscriptionResult(
                kind="mode_not_confirmed", text="", convert_s=0.0, transcribe_s=0.0
            )
        try:
            root = tempfile.mkdtemp(prefix="ikigai-voice-")
        except OSError:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=0.0, transcribe_s=0.0
            )
        convert_s = 0.0
        transcribe_s = 0.0
        cleanup_failed = False
        try:
            result = self._run(root, audio)
            convert_s = result.convert_s
            transcribe_s = result.transcribe_s
            outcome = result
        finally:
            try:
                shutil.rmtree(root)
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            return TranscriptionResult(
                kind="unavailable",
                text="",
                convert_s=convert_s,
                transcribe_s=transcribe_s,
            )
        return outcome

    def _run(self, root: str, audio: bytes) -> TranscriptionResult:
        in_path = os.path.join(root, "note.oga")
        out_path = os.path.join(root, "note.wav")
        try:
            fd = os.open(in_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=0.0, transcribe_s=0.0
            )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(audio)
        except OSError:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=0.0, transcribe_s=0.0
            )
        env = self._child_env()
        start = time.monotonic()
        try:
            converted = self._runner(
                [
                    self._ffmpeg_bin,
                    "-nostdin",
                    "-i",
                    in_path,
                    *_FFMPEG_ARGV_TAIL,
                    out_path,
                ],
                env=env,
                timeout_s=self._convert_timeout_s,
                cwd=None,
            )
        except OSError:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=0.0, transcribe_s=0.0
            )
        convert_s = time.monotonic() - start
        if converted.timed_out or converted.returncode is None:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=convert_s, transcribe_s=0.0
            )
        if converted.returncode != 0:
            return TranscriptionResult(
                kind="unreadable", text="", convert_s=convert_s, transcribe_s=0.0
            )
        start = time.monotonic()
        try:
            outcome = self._runner(
                [self._muse_bin, "voice", "transcribe", out_path],
                env=env,
                timeout_s=self._timeout_s,
                cwd=None,
            )
        except OSError:
            return TranscriptionResult(
                kind="unavailable", text="", convert_s=convert_s, transcribe_s=0.0
            )
        transcribe_s = time.monotonic() - start
        if outcome.timed_out or outcome.returncode is None:
            return TranscriptionResult(
                kind="unavailable",
                text="",
                convert_s=convert_s,
                transcribe_s=transcribe_s,
            )
        if outcome.returncode == 7:
            return TranscriptionResult(
                kind="silence", text="", convert_s=convert_s, transcribe_s=transcribe_s
            )
        if outcome.returncode == 0:
            try:
                text = outcome.stdout.decode("utf-8").strip()
            except UnicodeDecodeError:
                return TranscriptionResult(
                    kind="unavailable",
                    text="",
                    convert_s=convert_s,
                    transcribe_s=transcribe_s,
                )
            if text:
                return TranscriptionResult(
                    kind="words",
                    text=text,
                    convert_s=convert_s,
                    transcribe_s=transcribe_s,
                )
            return TranscriptionResult(
                kind="silence", text="", convert_s=convert_s, transcribe_s=transcribe_s
            )
        if outcome.returncode == 3:
            return TranscriptionResult(
                kind="unreadable",
                text="",
                convert_s=convert_s,
                transcribe_s=transcribe_s,
            )
        return TranscriptionResult(
            kind="unavailable", text="", convert_s=convert_s, transcribe_s=transcribe_s
        )
