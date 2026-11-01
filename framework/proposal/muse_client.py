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


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult: ...


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("META_API_KEY", None)
    return env


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
    """Run the binary; stderr is never read, the group always dies first."""
    proc = subprocess.Popen(
        list(argv),
        env=dict(env),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
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
    return RunResult(proc.returncode, stdout_data or b"", False)


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
        try:
            with tempfile.TemporaryDirectory(prefix="ikigai-muse-") as root:
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
                try:
                    outcome = self._runner(
                        argv,
                        env=_child_env(),
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
                    text = ""
                    prompt_tokens = None
                    cached_tokens = None
                    completion_tokens = None
                    reasoning_tokens = None
                    model_reported = "unreported"
                else:
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
            raise MetaUnavailableError("temp files", latency_ms=latency_ms)
        if failure is not None:
            # Raised outside the handler so runner detail stays out of
            # ``__context__`` and ``__cause__``; the reason never holds output.
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
