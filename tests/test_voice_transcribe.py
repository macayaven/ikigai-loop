"""Ticket 14 Step 5: the guarded transcription client (D7, D8).

Fake runner throughout: no real binary, no audio device, no network.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from framework.proposal.muse_client import RunResult
from framework.voice.transcribe import MuseVoiceTranscriber


class FakeRunner:
    """Scripted runner: one outcome per call, or a strict argv router."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.ffmpeg_result: RunResult = RunResult(0, b"", False)
        self.transcribe_result: RunResult = RunResult(0, b"words here", False)
        self.raise_on_ffmpeg: BaseException | None = None
        self.raise_on_transcribe: BaseException | None = None

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        self.calls.append(
            {"argv": list(argv), "env": dict(env), "timeout_s": timeout_s, "cwd": cwd}
        )
        if "transcribe" in list(argv):
            if self.raise_on_transcribe is not None:
                raise self.raise_on_transcribe
            return self.transcribe_result
        if self.raise_on_ffmpeg is not None:
            raise self.raise_on_ffmpeg
        return self.ffmpeg_result


def _confirmed_env(
    tmp_path: Path, extra: dict[str, str] | None = None
) -> tuple[dict[str, str], Path]:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"contributor_mode_enabled": False}), encoding="utf-8"
    )
    env = {"MUSE_CONTRIBUTOR_MODE": "0", "MUSE_BIN": "/bin/muse"}
    if extra:
        env.update(extra)
    return env, settings


def _transcriber(
    runner: FakeRunner,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
    **kwargs: Any,
) -> MuseVoiceTranscriber:
    env, settings = _confirmed_env(tmp_path, extra_env)
    return MuseVoiceTranscriber(
        muse_bin="/bin/muse",
        ffmpeg_bin="/bin/ffmpeg",
        runner=runner,
        environ=env,
        settings_path=settings,
        **kwargs,
    )


def _temp_dirs_from(runner: FakeRunner) -> list[str]:
    dirs: list[str] = []
    for call in runner.calls:
        for arg in call["argv"]:
            if arg.endswith(("note.oga", "note.wav")):
                parent = os.path.dirname(arg)
                if parent not in dirs:
                    dirs.append(parent)
    return dirs


def test_refused_check_makes_zero_runner_calls_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner()
    missing = tmp_path / "missing-settings.json"
    transcribe = MuseVoiceTranscriber(
        muse_bin="/bin/muse",
        runner=runner,
        environ={},
        settings_path=missing,
    )

    def _no_temp(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("no temp directory may be created on a refused check")

    monkeypatch.setattr(tempfile, "mkdtemp", _no_temp)
    result = transcribe.transcribe(b"\x00\x01\x02")

    assert result.kind == "mode_not_confirmed"
    assert result.text == ""
    assert runner.calls == []


def test_env_not_zero_is_refused_even_with_setting_false(tmp_path: Path) -> None:
    runner = FakeRunner()
    env, settings = _confirmed_env(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "1"})
    transcribe = MuseVoiceTranscriber(
        muse_bin="/bin/muse", runner=runner, environ=env, settings_path=settings
    )
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "mode_not_confirmed"
    assert runner.calls == []


def test_child_env_is_key_free_and_pins_contributor_mode(tmp_path: Path) -> None:
    runner = FakeRunner()
    transcribe = _transcriber(
        runner, tmp_path, {"META_API_KEY": "sekret-key", "MUSE_CONTRIBUTOR_MODE": "0"}
    )
    result = transcribe.transcribe(b"\x00\x01")

    assert result.kind == "words"
    assert len(runner.calls) == 2
    for call in runner.calls:
        assert "META_API_KEY" not in call["env"]
        assert call["env"]["MUSE_CONTRIBUTOR_MODE"] == "0"
        assert call["env"]["MUSE_BIN"] == "/bin/muse"


def test_argv_shapes_have_no_contributor_flag(tmp_path: Path) -> None:
    runner = FakeRunner()
    transcribe = _transcriber(runner, tmp_path)
    transcribe.transcribe(b"\x00\x01")

    assert len(runner.calls) == 2
    ffmpeg_argv = runner.calls[0]["argv"]
    voice_argv = runner.calls[1]["argv"]
    wav_path = voice_argv[-1]
    oga_path = ffmpeg_argv[ffmpeg_argv.index("-i") + 1]
    assert ffmpeg_argv == [
        "/bin/ffmpeg",
        "-nostdin",
        "-i",
        oga_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        wav_path,
    ]
    assert os.path.basename(oga_path) == "note.oga"
    assert os.path.basename(wav_path) == "note.wav"
    assert os.path.dirname(oga_path) == os.path.dirname(wav_path)
    assert voice_argv == ["/bin/muse", "voice", "transcribe", wav_path]
    assert all("contributor" not in str(arg).lower() for arg in voice_argv)
    assert all("contributor" not in str(arg).lower() for arg in ffmpeg_argv)


def test_timeouts_reach_the_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    transcribe = _transcriber(runner, tmp_path, convert_timeout_s=7.0, timeout_s=9.0)
    transcribe.transcribe(b"\x00\x01")
    assert runner.calls[0]["timeout_s"] == 7.0
    assert runner.calls[1]["timeout_s"] == 9.0


def test_words_arm_strips_stdout(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(0, b"  skip the write-up\n", False)
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "words"
    assert result.text == "skip the write-up"
    assert result.convert_s >= 0.0
    assert result.transcribe_s >= 0.0


@pytest.mark.parametrize("stdout", [b"", b"   \n", b"  \t "])
def test_silence_on_empty_stdout(tmp_path: Path, stdout: bytes) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(0, stdout, False)
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "silence"
    assert result.text == ""


def test_silence_on_exit_7(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(7, b"", False)
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "silence"


def test_unreadable_on_exit_3(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(3, b"", False)
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unreadable"


def test_unreadable_when_ffmpeg_fails(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.ffmpeg_result = RunResult(1, b"boom", False)
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "unreadable"
    assert len(runner.calls) == 1


@pytest.mark.parametrize("stdout", [b"\xff\xfe\x00bad", b"\x80\x81"])
def test_unavailable_on_undecodable_stdout(tmp_path: Path, stdout: bytes) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(0, stdout, False)
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unavailable"


@pytest.mark.parametrize("returncode", [1, 2, 4, 5, 42, None])
def test_unavailable_on_other_exits(tmp_path: Path, returncode: int | None) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(returncode, b"nope", False)
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unavailable"


def test_unavailable_on_timeout(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.transcribe_result = RunResult(None, b"", True)
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unavailable"


def test_unavailable_on_ffmpeg_timeout(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.ffmpeg_result = RunResult(None, b"", True)
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "unavailable"
    assert len(runner.calls) == 1


@pytest.mark.parametrize("error", [OSError("gone"), FileNotFoundError("no ffmpeg")])
def test_unavailable_on_oserror(tmp_path: Path, error: BaseException) -> None:
    runner = FakeRunner()
    runner.raise_on_transcribe = error
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unavailable"


def test_unavailable_when_ffmpeg_binary_missing(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.raise_on_ffmpeg = FileNotFoundError("ffmpeg")
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "unavailable"
    assert len(runner.calls) == 1


def _run_every_arm(tmp_path: Path, index: int) -> tuple[FakeRunner, str]:
    if index == 0:
        runner = FakeRunner()
        kind = "words"
    elif index == 1:
        runner = FakeRunner()
        runner.transcribe_result = RunResult(0, b"", False)
        kind = "silence"
    elif index == 2:
        runner = FakeRunner()
        runner.transcribe_result = RunResult(7, b"", False)
        kind = "silence"
    elif index == 3:
        runner = FakeRunner()
        runner.transcribe_result = RunResult(3, b"", False)
        kind = "unreadable"
    elif index == 4:
        runner = FakeRunner()
        runner.ffmpeg_result = RunResult(1, b"x", False)
        kind = "unreadable"
    elif index == 5:
        runner = FakeRunner()
        runner.transcribe_result = RunResult(5, b"x", False)
        kind = "unavailable"
    else:
        runner = FakeRunner()
        runner.transcribe_result = RunResult(None, b"", True)
        kind = "unavailable"
    return runner, kind


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5, 6])
def test_temp_directory_gone_after_every_arm(tmp_path: Path, index: int) -> None:
    runner, expected = _run_every_arm(tmp_path, index)
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01\x02")
    assert result.kind == expected
    for gone in _temp_dirs_from(runner):
        assert not os.path.exists(gone)


def test_temp_directory_gone_after_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def _watch(*args: Any, **kwargs: Any) -> str:
        path = real_mkdtemp(*args, **kwargs)
        seen.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", _watch)
    runner = FakeRunner()
    runner.raise_on_transcribe = OSError("gone")
    transcribe = _transcriber(runner, tmp_path)
    assert transcribe.transcribe(b"\x00\x01").kind == "unavailable"
    assert seen != []
    assert all(not os.path.exists(path) for path in seen)


def test_cleanup_oserror_makes_note_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(path: str, *args: Any, **kwargs: Any) -> None:
        raise OSError("cannot remove")

    monkeypatch.setattr(shutil, "rmtree", _boom)
    runner = FakeRunner()
    transcribe = _transcriber(runner, tmp_path)
    result = transcribe.transcribe(b"\x00\x01")
    assert result.kind == "unavailable"
    assert result.text == ""


def test_stderr_is_never_read() -> None:
    source = Path("framework/voice/transcribe.py").read_text(encoding="utf-8")
    assert "stderr" not in source
    assert "stdout" in source
