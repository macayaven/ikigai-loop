"""Ticket 11: Muse Code transport for Wonder calls (CLI edge only).

Runs the headless ``muse exec`` binary on my subscription instead of the
Model API. The prompt, schema, and workspace travel through temp files that
are removed on every path; the child's environment never holds the API key.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from framework.briefing.gate import scan_outbound_text
from framework.glimmer.llm import sanitise_model_id
from framework.proposal.client import EFFORTS, refuse_contributor_model
from framework.proposal.core import (
    MetaUnavailableError,
    OutboundBlocked,
    WonderRequest,
    WonderResponse,
)

TRANSPORT = "muse"
DEFAULT_MUSE_BIN = "~/.local/bin/muse"
MAX_MODEL_STEPS = 3
TIMEOUT_S = 300
LOCAL_START_THRESHOLD_S = 2.0
LOCAL_START_THRESHOLD_MS = int(LOCAL_START_THRESHOLD_S * 1000)
STDERR_HEAD_BYTES = 8 * 1024
PRIVATE_TMP_DIRNAME = "ikigai-muse-tmp"

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_VERSION_CACHE: dict[str, str | None] = {}
_VERSION_LOCK = threading.Lock()


def resolve_muse_bin(environ: Mapping[str, str] | None = None) -> str:
    """Read ``MUSE_BIN`` at call time, else the default; expand ``~``."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    return os.path.expanduser(env.get("MUSE_BIN") or DEFAULT_MUSE_BIN)


def rules_file_path(environ: Mapping[str, str] | None = None) -> str:
    """Harness rules file path; presence only, the contents are never read."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    xdg = env.get("XDG_CONFIG_HOME") or ""
    if xdg:
        return os.path.join(xdg, "muse", "AGENTS.md")
    return os.path.expanduser("~/.config/muse/AGENTS.md")


@dataclass(frozen=True)
class RunResult:
    returncode: int | None  # None when timed out
    stdout: bytes
    timed_out: bool
    stderr: bytes = b""


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult: ...


class LocalStartFailure(MetaUnavailableError):
    """A call that failed in under 2 s, before any model request ran.

    Carries the same closed reason as its message, the same
    ``latency_ms``, the exit code when there is one, and the masked
    stderr. The stderr lives on ``stderr_masked`` only: never in the
    message, never in ``repr``, never chained.
    """

    def __init__(
        self,
        message: str = "",
        *,
        latency_ms: int = 0,
        exit_code: int | None = None,
        stderr_masked: str = "",
    ) -> None:
        super().__init__(message, latency_ms=latency_ms)
        self.exit_code = exit_code
        self.stderr_masked = stderr_masked


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("META_API_KEY", None)
    return env


def _private_tmp_root() -> str:
    """Private temp folder under the home's cache folder, made owner-only."""
    root = Path.home() / ".cache" / PRIVATE_TMP_DIRNAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return str(root)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _default_runner(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_s: float,
    cwd: str | None,
) -> RunResult:
    """Run the binary; stderr goes to an anonymous temp file, never a pipe.

    The file is unlinked on creation, so nothing is left behind on any
    path, even when the run is killed outright. It is read, at most the
    first 8 KiB, only when the child exited non-zero; on success or a
    timeout the result's stderr stays empty and the file is never read.
    The stdout read stays exactly as it is, and the process group always
    dies first.
    """
    with tempfile.TemporaryFile(prefix="ikigai-muse-stderr-") as err_handle:
        proc = subprocess.Popen(
            list(argv),
            env=dict(env),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=err_handle,
            start_new_session=True,
        )
        try:
            stdout_data, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return RunResult(None, b"", True)
        except BaseException:
            _kill_group(proc.pid)
            raise
        if proc.returncode != 0:
            err_handle.seek(0)
            stderr_data = err_handle.read(STDERR_HEAD_BYTES)
        else:
            stderr_data = b""
        return RunResult(proc.returncode, stdout_data or b"", False, stderr_data)


def _write_exclusive(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(data)


def _add_token(current: int | None, value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return (current or 0) + value
    return current


def _has_terminal_event(stdout: bytes) -> bool:
    """Whether stdout holds any ``run_terminal`` payload at all."""
    for raw_line in stdout.split(b"\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded: Any = json.loads(line)
        except ValueError:
            continue
        if not isinstance(decoded, dict):
            continue
        payload: Any = cast("dict[str, Any]", decoded).get("payload")
        if not isinstance(payload, dict):
            continue
        entry = cast("dict[str, Any]", payload)
        if entry.get("kind") == "run_terminal":
            return True
    return False


def _is_local_start(failure: str, stdout: bytes) -> bool:
    """Whether a failure reason says the run never got anywhere.

    A non-zero exit, an unrunnable binary and lost temp files always do.
    An invalid response does only when stdout holds no terminal event;
    a completed terminal that the client rejects is a real model answer.
    Timeouts, contributor refusals, muse terminals and anything else keep
    the plain class at any speed.
    """
    if failure.startswith("exit "):
        return True
    if failure in ("muse not runnable", "temp files"):
        return True
    if failure == "invalid response":
        return not _has_terminal_event(stdout)
    return False


def _local_start(
    reason: str,
    latency_ms: int,
    exit_code: int | None,
    stderr_raw: bytes,
    private_terms: tuple[str, ...],
) -> LocalStartFailure:
    # Imported here so the masking module can catch this class without
    # a top-level cycle back into this module.
    from framework.proposal.local_retry import mask_stderr

    return LocalStartFailure(
        reason,
        latency_ms=latency_ms,
        exit_code=exit_code,
        stderr_masked=mask_stderr(stderr_raw, private_terms),
    )


def _first_version_line(stdout: bytes) -> str | None:
    if not stdout:
        return None
    try:
        text = stdout.split(b"\n")[0].decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    if not text or len(text) > 80:
        return None
    if all(32 <= ord(char) <= 126 for char in text):
        return text
    return None


class MuseExecClient:
    """Run one ``muse exec`` call per request; each request names its model."""

    transport = "muse"

    def __init__(
        self,
        *,
        private_terms: tuple[str, ...] = (),
        private_terms_available: bool = False,
        muse_bin: str | None = None,
        timeout_s: float = TIMEOUT_S,
        runner: Runner | None = None,
    ) -> None:
        self._private_terms = private_terms
        self._private_terms_available = private_terms_available
        self._muse_bin = muse_bin if muse_bin is not None else resolve_muse_bin()
        self._timeout_s = timeout_s
        self._runner: Runner = runner if runner is not None else _default_runner

    @property
    def harness_rules_file(self) -> bool:
        """Whether the harness rules file exists; read per attempt, not cached."""
        return os.path.isfile(rules_file_path())

    @property
    def transport_version(self) -> str | None:
        """The ``muse --version`` line, read once per binary per process."""
        with _VERSION_LOCK:
            if self._muse_bin in _VERSION_CACHE:
                return _VERSION_CACHE[self._muse_bin]
        version: str | None
        try:
            result = self._runner(
                [self._muse_bin, "--version"],
                env=_child_env(),
                timeout_s=10,
                cwd=None,
            )
        except Exception:  # noqa: BLE001 -- a version probe never raises
            version = None
        else:
            if result.timed_out or result.returncode != 0:
                version = None
            else:
                version = _first_version_line(result.stdout)
        with _VERSION_LOCK:
            _VERSION_CACHE[self._muse_bin] = version
        return version

    def complete(self, request: WonderRequest) -> WonderResponse:
        codes = scan_outbound_text(
            request.prompt,
            private_terms=self._private_terms,
            private_terms_available=self._private_terms_available,
            forbidden_raw_literals=request.forbidden_raw_literals,
        )
        if codes:
            raise OutboundBlocked(codes)
        refuse_contributor_model(request.model)
        if request.effort not in EFFORTS:
            raise ValueError("unknown effort")
        if _MODEL_RE.fullmatch(request.model) is None:
            raise ValueError("unknown model")
        start = time.monotonic()
        failure: str | None = None
        text = ""
        prompt_tokens: int | None = None
        cached_tokens: int | None = None
        completion_tokens: int | None = None
        reasoning_tokens: int | None = None
        model_reported = "unreported"
        latency_ms = 0
        temp_files_failed = False
        exit_code: int | None = None
        stdout_raw = b""
        stderr_raw = b""
        try:
            private_tmp = _private_tmp_root()
            with tempfile.TemporaryDirectory(
                prefix="ikigai-muse-", dir=private_tmp
            ) as root:
                workspace = os.path.join(root, "workspace")
                os.mkdir(workspace)
                prompt_path = os.path.join(root, "prompt.txt")
                schema_path = os.path.join(root, "schema.json")
                _write_exclusive(prompt_path, request.prompt.encode("utf-8"))
                _write_exclusive(
                    schema_path, json.dumps(request.response_schema).encode("utf-8")
                )
                argv: list[str] = [
                    self._muse_bin,
                    "exec",
                    "--json",
                    "--no-session-log",
                    "--preset",
                    "empty",
                    "--model",
                    request.model,
                    "--reasoning-effort",
                    request.effort,
                    "--contributor-mode",
                    "off",
                    "--approval-mode",
                    "never",
                    "--trust-workspace",
                    "--workspace",
                    workspace,
                    "--no-foreign-personal-context",
                    "--disable-web-tools",
                    "--disable-request-user-input",
                    "--disable-reminders",
                    "--disable-shell",
                    "--disable-write",
                    "--max-model-steps",
                    str(MAX_MODEL_STEPS),
                    "--output-schema",
                    schema_path,
                    "--prompt-file",
                    prompt_path,
                ]
                child_env = _child_env()
                child_env["TMPDIR"] = private_tmp
                try:
                    outcome = self._runner(
                        argv,
                        env=child_env,
                        timeout_s=self._timeout_s,
                        cwd=workspace,
                    )
                except OSError:
                    outcome = None
                latency_ms = int((time.monotonic() - start) * 1000)
                if outcome is None:
                    failure = "muse not runnable"
                    text = ""
                    prompt_tokens = None
                    cached_tokens = None
                    completion_tokens = None
                    reasoning_tokens = None
                    model_reported = "unreported"
                elif outcome.timed_out:
                    failure = "timeout"
                    text = ""
                    prompt_tokens = None
                    cached_tokens = None
                    completion_tokens = None
                    reasoning_tokens = None
                    model_reported = "unreported"
                elif outcome.returncode != 0:
                    failure = f"exit {outcome.returncode}"
                    exit_code = outcome.returncode
                    stdout_raw = outcome.stdout
                    stderr_raw = outcome.stderr
                    text = ""
                    prompt_tokens = None
                    cached_tokens = None
                    completion_tokens = None
                    reasoning_tokens = None
                    model_reported = "unreported"
                else:
                    stdout_raw = outcome.stdout
                    (
                        failure,
                        text,
                        prompt_tokens,
                        cached_tokens,
                        completion_tokens,
                        reasoning_tokens,
                        model_reported,
                    ) = _parse_stdout(outcome.stdout)
        except OSError:
            temp_files_failed = True
        if temp_files_failed:
            # Raised outside the handler so ``__context__`` stays empty.
            # A cleanup failure after a good response lands here too: the
            # files may still exist, so the response is never used.
            latency_ms = int((time.monotonic() - start) * 1000)
            if latency_ms < LOCAL_START_THRESHOLD_MS:
                raise _local_start(
                    "temp files", latency_ms, None, b"", self._private_terms
                )
            raise MetaUnavailableError("temp files", latency_ms=latency_ms)
        if failure is not None:
            # Raised outside the handler so runner detail stays out of
            # ``__context__`` and ``__cause__``; the reason never holds output.
            if latency_ms < LOCAL_START_THRESHOLD_MS and _is_local_start(
                failure, stdout_raw
            ):
                raise _local_start(
                    failure, latency_ms, exit_code, stderr_raw, self._private_terms
                )
            raise MetaUnavailableError(failure, latency_ms=latency_ms)
        return WonderResponse(
            text=text,
            model_reported=model_reported,
            latency_ms=latency_ms,
            finish_reason="completed",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
        )


def _is_contributor_model(value: Any) -> bool:
    return isinstance(value, str) and "contributor" in value.lower()


def _parse_stdout(
    stdout: bytes,
) -> tuple[str | None, str, int | None, int | None, int | None, int | None, str]:
    """Read the last ``run_terminal`` and ``run_usage`` payloads."""
    last_terminal: dict[str, Any] | None = None
    last_usage: dict[str, Any] | None = None
    last_configured_model_id: Any = None
    have_configured_model_id = False
    for raw_line in stdout.split(b"\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded: Any = json.loads(line)
        except ValueError:
            continue
        if not isinstance(decoded, dict):
            continue
        payload: Any = cast("dict[str, Any]", decoded).get("payload")
        if not isinstance(payload, dict):
            continue
        entry = cast("dict[str, Any]", payload)
        kind: Any = entry.get("kind")
        if kind == "run_terminal":
            last_terminal = entry
        elif kind == "run_usage":
            last_usage = entry
        elif kind == "run_model_configured":
            last_configured_model_id = entry.get("model_id")
            have_configured_model_id = True
    rows: list[Any] = []
    usage_models: Any = last_usage.get("models") if last_usage is not None else None
    if isinstance(usage_models, list):
        rows = cast("list[Any]", usage_models)
    if have_configured_model_id and _is_contributor_model(last_configured_model_id):
        return ("contributor model", "", None, None, None, None, "unreported")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _is_contributor_model(cast("dict[str, Any]", row).get("model")):
            return ("contributor model", "", None, None, None, None, "unreported")
    if last_terminal is None:
        return ("invalid response", "", None, None, None, None, "unreported")
    terminal_state: Any = last_terminal.get("terminal")
    if not isinstance(terminal_state, str) or terminal_state != "completed":
        return ("muse terminal", "", None, None, None, None, "unreported")
    text: Any = last_terminal.get("text")
    if not isinstance(text, str):
        return ("invalid response", "", None, None, None, None, "unreported")
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields = cast("dict[str, Any]", row)
        prompt_tokens = _add_token(prompt_tokens, fields.get("input_tokens"))
        cached_tokens = _add_token(cached_tokens, fields.get("cached_tokens"))
        completion_tokens = _add_token(completion_tokens, fields.get("output_tokens"))
        reasoning_tokens = _add_token(reasoning_tokens, fields.get("reasoning_tokens"))
    first_model: Any = None
    if rows:
        head: Any = rows[0]
        if isinstance(head, dict):
            first_model = cast("dict[str, Any]", head).get("model")
    return (
        None,
        text,
        prompt_tokens,
        cached_tokens,
        completion_tokens,
        reasoning_tokens,
        sanitise_model_id(first_model),
    )
