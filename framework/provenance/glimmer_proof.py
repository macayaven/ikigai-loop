"""Ticket 22: the Glimmer serving proof behind ``make glimmer-proof``.

The order is binding: refuse inside a real slot's Glimmer window first,
before reading the environment or touching the network; then configure;
then prove the front door without loading anything; then one synthetic
label; then the weights corroboration, with ``/upstream`` read only
after the chat call succeeded. Output is plain ``key=value`` lines that
carry the served weights' basename, the endpoint's shape and the one
synthetic result, and nothing private on any path, including failures.
"""

from __future__ import annotations

import getpass
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from framework.cycle.orchestrator import EXTRA_SLOT, FACTS_SLOT_RESERVE, SLOT_TIMES
from framework.glimmer.facts import LLMUnavailableError
from framework.glimmer.label_step import (
    LABEL_CALL_TIMEOUT_S,
    build_label_client,
    build_label_prompt,
    label_outcome,
)
from framework.glimmer.llm import urlopen
from framework.provenance.schemas import (
    bounded_contains,
    clean_finish_reason,
    clean_model_id,
)

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

WINDOW_LEAD_MINUTES = 25
WINDOW_REFUSE_AHEAD_S = LABEL_CALL_TIMEOUT_S
GET_TIMEOUT_S = 10
SYNTHETIC_TITLE = "Sprint planning"
SYNTHETIC_EXPECTED = "iki-meeting"
REQUIRED_WORD = "glimmer"

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class ProofFailure(Exception):
    """A closed failure: ``code`` prints to stderr, ``exit`` exits."""

    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def window_refusal(now: datetime) -> tuple[datetime, datetime] | None:
    """The refusing window containing ``now``, or None.

    The window is slot minus 25 minutes to slot minus 4 minutes, both
    ends inclusive, for every pinned slot time on any nearby day, in
    Madrid time whatever the machine's zone. A start that could still be
    running when the window opens also refuses, so the range reaches
    back one label-call timeout before the window's start.
    """
    local = now.astimezone(MADRID)
    for day_offset in (-1, 0, 1):
        day = (local + timedelta(days=day_offset)).date()
        candidates = [
            datetime(
                day.year,
                day.month,
                day.day,
                slot_time.hour,
                slot_time.minute,
                tzinfo=MADRID,
            )
            for slot_time in SLOT_TIMES
        ]
        if day == EXTRA_SLOT.date():
            candidates.append(EXTRA_SLOT)
        for slot in candidates:
            start = slot - timedelta(minutes=WINDOW_LEAD_MINUTES)
            end = slot - FACTS_SLOT_RESERVE
            if start - timedelta(seconds=WINDOW_REFUSE_AHEAD_S) <= local <= end:
                return (start, end)
    return None


def _closed_word(value: Any) -> str:
    """A closed catalog shape that keeps its original case, else unknown."""
    if isinstance(value, str) and _WORD_RE.fullmatch(value.lower()) is not None:
        return value
    return "unknown"


def _root_of(base_url: str) -> str:
    """The base URL's root: only a trailing ``/v1`` comes off the path."""
    parts = urllib.parse.urlsplit(base_url.rstrip("/"))
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = ""
    try:
        port_num = parts.port
    except ValueError:
        port_num = None
    if port_num is not None:
        port = f":{port_num}"
    path = parts.path
    if path == "/v1" or path.endswith("/v1"):
        path = path[: -len("/v1")]
    return f"{parts.scheme}://{host}{port}{path}"


def _get_json(url: str, api_key: str, timeout: float | None) -> Any:
    """One authenticated GET; the bearer key travels on every request."""
    wait = GET_TIMEOUT_S if timeout is None else timeout
    request = urllib.request.Request(
        url, method="GET", headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        with urlopen(request, timeout=wait) as response:
            raw = response.read()
    except TimeoutError as exc:
        raise ProofFailure("FRONTDOOR_TIMEOUT", 2) from exc
    except urllib.error.HTTPError as exc:
        raise ProofFailure("FRONTDOOR_STATUS", 2) from exc
    except (OSError, ValueError) as exc:
        raise ProofFailure("FRONTDOOR_TRANSPORT", 2) from exc
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ProofFailure("FRONTDOOR_SHAPE", 2) from exc


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return cast(dict[str, Any], raw)
    return {}


def _json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return cast(list[Any], raw)
    return []


def _resident(items: Any, alias: str) -> bool:
    """Whether the alias is ready; any entry naming another model refuses.

    An empty list is the normal nothing-loaded state. An entry for the
    alias in a state other than ready means resident no, and the proof
    proceeds. Only a missing key or a non-list value is a shape failure.
    """
    if not isinstance(items, list):
        raise ProofFailure("FRONTDOOR_SHAPE", 2)
    entries = cast(list[Any], items)
    resident = False
    for raw_item in entries:
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, Any], raw_item)
        model = item.get("model")
        if model is None:
            continue
        if model != alias:
            raise ProofFailure("RESIDENT_OTHER_MODEL", 3)
        if item.get("state") == "ready":
            resident = True
    return resident


def _front_door(
    root: str, alias: str, api_key: str, timeout: float | None = None
) -> tuple[str, str, bool]:
    """Shapes only: runtime, quant, and whether the alias is resident."""
    models = _json_dict(_get_json(f"{root}/v1/models", api_key, timeout))
    entries = _json_list(models.get("data"))
    if not entries:
        raise ProofFailure("FRONTDOOR_SHAPE", 2)
    alias_entry: dict[str, Any] | None = None
    for raw_entry in entries:
        entry = _json_dict(raw_entry) if isinstance(raw_entry, dict) else {}
        if entry.get("id") == alias:
            alias_entry = entry
            break
    owned = alias_entry.get("owned_by") if alias_entry is not None else None
    if owned != "llama-swap":
        raise ProofFailure("FRONTDOOR_NOT_LLAMASWAP", 2)
    meta = _json_dict(alias_entry.get("meta")) if alias_entry is not None else {}
    shape = _json_dict(meta.get("llamaswap"))
    runtime = _closed_word(shape.get("runtime"))
    quant = _closed_word(shape.get("quant"))
    running = _json_dict(_get_json(f"{root}/running", api_key, timeout))
    return runtime, quant, _resident(running.get("running"), alias)


def _alias_ready(
    root: str, alias: str, api_key: str, timeout: float | None = None
) -> bool:
    """Only ``/running`` decides whether ``/upstream`` is safe to read."""
    try:
        running = _json_dict(_get_json(f"{root}/running", api_key, timeout))
        return _resident(running.get("running"), alias)
    except ProofFailure:
        return False


def _host_class(host: str) -> str:
    if host == "localhost":
        return "loopback"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "private"
    if address.is_loopback:
        return "loopback"
    return "private"


def _optional_text(reader: Callable[[], str]) -> str | None:
    try:
        return reader()
    except Exception:  # noqa: BLE001 -- a name probe never stops the proof
        return None


def _leak_strings(base_url: str, api_key: str) -> list[str]:
    """Whole values that must never appear: the secret, the host, home."""
    found: list[str] = []
    try:
        host = urllib.parse.urlsplit(base_url).hostname
    except ValueError:
        host = None
    if host:
        found.append(host)
    if api_key:
        found.append(api_key)
    home = _optional_text(lambda: Path.home().as_posix())
    if home:
        found.append(home)
    return found


def _leak_tokens() -> set[str]:
    """Username, hostname and home name as whole names; short names ignored."""
    tokens: set[str] = set()

    def add(value: str | None) -> None:
        if value is None:
            return
        if len(value) >= 3:
            tokens.add(value.lower())

    add(_optional_text(getpass.getuser))
    add(_optional_text(socket.gethostname))
    add(_optional_text(lambda: Path.home().name))
    return tokens


def _leaks(output: str, strings: list[str], tokens: set[str]) -> bool:
    lowered = output.lower()
    for value in strings:
        if value.lower() in lowered:
            return True
    return any(bounded_contains(lowered, token) for token in tokens if len(token) >= 3)


def _run(
    clock: Callable[[], datetime],
    env: Mapping[str, str],
) -> int:
    # First, before reading the environment or touching the network.
    now = clock()
    refused = window_refusal(now)
    if refused is not None:
        _start, end = refused
        first_second = end + timedelta(seconds=1)
        print(
            f"code=GLIMMER_WINDOW_REFUSED next={first_second.isoformat()}",
            file=sys.stderr,
        )
        return 3
    try:
        client = build_label_client(env, timeout_s=LABEL_CALL_TIMEOUT_S)
    except SystemExit as exc:
        match = re.search(r"LOCAL_LLM_[A-Z_]+", str(exc.code))
        var = match.group(0) if match is not None else "unknown-var"
        print(f"code=CONFIG_MISSING var={var}", file=sys.stderr)
        return 2
    except ValueError:
        print("code=CONFIG_NOT_PRIVATE", file=sys.stderr)
        return 2
    base_url = env.get("LOCAL_LLM_BASE_URL", "")
    api_key = env.get("LOCAL_LLM_API_KEY", "")
    alias = env.get("LOCAL_LLM_MODEL", "")
    if REQUIRED_WORD not in alias.lower():
        print("code=CONFIG_ALIAS", file=sys.stderr)
        return 2
    root = _root_of(base_url)
    try:
        runtime, quant, resident = _front_door(root, alias, api_key)
    except ProofFailure as exc:
        print(f"code={exc.code}", file=sys.stderr)
        return exc.exit_code
    prompt = build_label_prompt(SYNTHETIC_TITLE)
    started = time.monotonic()
    try:
        response = client.complete(prompt)
    except LLMUnavailableError:
        print("code=MODEL_UNAVAILABLE", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- the edge maps to the class only
        print(f"code={type(exc).__name__}", file=sys.stderr)
        return 1
    latency_s = time.monotonic() - started
    outcome = label_outcome(response)
    if not outcome.valid:
        print("code=LABEL_INVALID", file=sys.stderr)
        return 1
    # The chat call gives no basename when its field names the alias
    # itself or is unreported: then the weights come from props alone.
    weights_chat = clean_model_id(response.model_id)
    alias_clean = clean_model_id(alias)
    chat_names_file = (
        weights_chat != "unknown"
        and response.model_id != alias
        and weights_chat != alias
        and weights_chat != alias_clean
    )
    if chat_names_file and REQUIRED_WORD not in weights_chat.lower():
        print("code=WEIGHTS_NOT_GLIMMER", file=sys.stderr)
        return 1
    corroborated = "unknown"
    weights = weights_chat if chat_names_file else "unknown"
    if _alias_ready(root, alias, api_key):
        try:
            props = _get_json(
                f"{root}/upstream/{urllib.parse.quote(alias, safe='')}/props",
                api_key,
                None,
            )
        except ProofFailure:
            props = None
        props_dict = _json_dict(props) if isinstance(props, dict) else None
        if props_dict is not None:
            weights_up = clean_model_id(props_dict.get("model_path"))
            if weights_up != "unknown":
                if REQUIRED_WORD not in weights_up.lower():
                    print("code=WEIGHTS_NOT_GLIMMER", file=sys.stderr)
                    return 1
                if chat_names_file:
                    if weights_up == weights_chat:
                        corroborated = "yes"
                    else:
                        print("code=WEIGHTS_DISAGREE", file=sys.stderr)
                        return 1
                else:
                    weights = weights_up
    if not chat_names_file and weights == "unknown":
        print("code=WEIGHTS_UNKNOWN", file=sys.stderr)
        return 1
    completion = response.completion_tokens
    if isinstance(completion, int) and completion >= 0 and latency_s > 0:
        rate = f"{completion / latency_s:.1f}"
        tokens_out = str(completion)
    else:
        rate = "unknown"
        tokens_out = "unknown"
    parts = urllib.parse.urlsplit(base_url.rstrip("/"))
    if parts.path == "/v1":
        endpoint = "POST /v1/chat/completions"
    else:
        endpoint = "other"
    lines = [
        f"weights={weights}",
        f"corroborated={corroborated}",
        f"alias={clean_model_id(alias)}",
        "front_door=llama-swap",
        f"runtime={runtime}",
        f"quant={quant}",
        f"resident={'yes' if resident else 'no'}",
        f"endpoint={endpoint}",
        f"tls={'yes' if parts.scheme == 'https' else 'no'}",
        f"host={_host_class(parts.hostname or '')}",
        f"synthetic_title={SYNTHETIC_TITLE}",
        f"synthetic_label={outcome.label}",
        "valid=yes",
        f"matched={'yes' if outcome.label == SYNTHETIC_EXPECTED else 'no'}",
        f"latency_s={latency_s:.1f}",
        f"completion_tokens={tokens_out}",
        f"tokens_per_second={rate}",
        f"finish_reason={clean_finish_reason(response.finish_reason)}",
        "verdict=OK",
        (
            "latency_note=latency includes any wait behind another request"
            " because Glimmer serves one at a time"
        ),
    ]
    body = "\n".join(lines) + "\n"
    if _leaks(body, _leak_strings(base_url, api_key), _leak_tokens()):
        print("code=OUTPUT_LEAK", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run the proof. The clock and env arguments exist for tests only."""
    _ = argv
    try:
        return _run(
            clock if clock is not None else lambda: datetime.now(UTC),
            env if env is not None else os.environ,
        )
    except ProofFailure as exc:
        print(f"code={exc.code}", file=sys.stderr)
        return exc.exit_code
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- the edge maps to the class only
        print(f"code={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
