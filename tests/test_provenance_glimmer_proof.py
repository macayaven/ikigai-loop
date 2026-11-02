"""Ticket 22: glimmer-proof tests. Loopback HTTP only, made-up data only."""

from __future__ import annotations

import getpass
import inspect
import json
import socket
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar, Self
from zoneinfo import ZoneInfo

import pytest

from framework.cycle import orchestrator
from framework.provenance import glimmer_proof
from framework.provenance.glimmer_proof import main

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

ALIAS = "glimmer-test-30b"
KEY = "plainword"
USER_DIR = "/home/figment/weights/cache"
MODEL_PATH = "/srv/figment/models/glimmer-30b.gguf"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


Route = tuple[int, str, float]


def _route(status: int, body: str, delay: float = 0.0) -> Route:
    return (status, body, delay)


class _Handler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, Route]] = {}
    log: ClassVar[list[str]] = []
    key: ClassVar[str] = KEY

    def _send(self, status: int, body: str, delay: float = 0.0) -> None:
        if delay:
            import time as _time

            _time.sleep(delay)
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, method: str) -> None:
        _Handler.log.append(f"{method} {self.path}")

    def _authorised(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {_Handler.key}"

    def do_GET(self) -> None:
        self._record("GET")
        if not self._authorised():
            self._send(401, '{"error": "unauthorised"}')
            return
        route = _Handler.routes.get(f"GET {self.path}")
        if route is None:
            self._send(404, '{"error": "no route"}')
            return
        status, body, delay = route
        self._send(status, body, delay)

    def do_POST(self) -> None:
        self._record("POST")
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if not self._authorised():
            self._send(401, '{"error": "unauthorised"}')
            return
        route = _Handler.routes.get(f"POST {self.path}")
        if route is None:
            self._send(404, '{"error": "no route"}')
            return
        self._send(*route)

    def log_message(self, format: str, *args: Any) -> None:
        _ = (format, args)


def _models_body(
    alias: str = ALIAS, owned_by: str = "llama-swap", quant: str = "q8"
) -> str:
    return json.dumps(
        {
            "data": [
                {
                    "id": alias,
                    "owned_by": owned_by,
                    "meta": {
                        "llamaswap": {"runtime": "cpu", "quant": quant, "extra": 1}
                    },
                }
            ]
        }
    )


def _entry(model: str = ALIAS, state: str = "ready", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model": model,
        "state": state,
        "cmd": f"{USER_DIR}/run --once",
        "proxy": "http://127.0.0.1:9/up",
        "ttl": 60,
        "name": "figment",
        "description": "made-up entry",
    }
    row.update(over)
    return row


def _running_body(
    alias: str = ALIAS, state: str = "ready", extra: list[dict[str, Any]] | None = None
) -> str:
    return json.dumps({"running": [_entry(alias, state), *(extra or [])]})


def _chat_body(
    label: str = "iki-meeting",
    model: str = MODEL_PATH,
    finish: str = "stop",
    tokens: int | None = 12,
) -> str:
    return json.dumps(
        {
            "model": model,
            "choices": [
                {
                    "message": {"content": json.dumps({"label": label})},
                    "finish_reason": finish,
                }
            ],
            "usage": {"completion_tokens": tokens},
        }
    )


def _props_body(model_path: str = MODEL_PATH) -> str:
    return json.dumps({"model_path": model_path, "other": 1})


class _Server:
    def __init__(self, routes: dict[str, Route]) -> None:
        _Handler.routes = routes
        _Handler.log = []
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    @property
    def log(self) -> list[str]:
        return list(_Handler.log)

    def base(self, path: str = "/v1") -> str:
        return f"http://127.0.0.1:{self.port}{path}"


def _env(base: str, alias: str = ALIAS) -> dict[str, str]:
    return {
        "LOCAL_LLM_BASE_URL": base,
        "LOCAL_LLM_MODEL": alias,
        "LOCAL_LLM_API_KEY": KEY,
    }


def _outside_windows() -> datetime:
    # Far from every Glimmer window: midday Madrid is hours from any slot.
    return datetime(2026, 11, 2, 12, 0, tzinfo=MADRID)


def _parse(stdout: str) -> dict[str, str]:
    got: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            got[key.strip()] = value.strip()
    return got


def _happy_routes() -> dict[str, Route]:
    return {
        "GET /v1/models": _route(200, _models_body()),
        "GET /running": _route(200, _running_body()),
        "POST /v1/chat/completions": _route(200, _chat_body()),
        f"GET /upstream/{ALIAS}/props": _route(200, _props_body()),
    }


class _RecordingEnv(dict[str, str]):
    """A valid environment that records every read; refusals must read none."""

    def __init__(self, base: dict[str, str]) -> None:
        super().__init__(base)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self.reads.append(key)
        return super().get(key, default)


def _prefixed(base_path: str) -> dict[str, Route]:
    """Happy routes under a path prefix, proving the prefix survives."""
    root = base_path
    if root == "/v1" or root.endswith("/v1"):
        root = root[: -len("/v1")]
    return {
        f"GET {root}/v1/models": _route(200, _models_body()),
        f"GET {root}/running": _route(200, _running_body()),
        f"POST {base_path}/chat/completions": _route(200, _chat_body()),
        f"GET {root}/upstream/{ALIAS}/props": _route(200, _props_body()),
    }


def test_proof_happy_path_over_loopback(capsys: pytest.CaptureFixture[str]) -> None:
    """The full proof passes against a llama-swap-shaped loopback server."""
    with _Server(_happy_routes()) as server:
        code = main([], clock=lambda: _outside_windows(), env=_env(server.base()))
    out = capsys.readouterr()
    assert code == 0, out.err
    got = _parse(out.out)
    assert got["weights"] == "glimmer-30b.gguf"
    assert got["corroborated"] == "yes"
    assert got["matched"] == "yes"
    assert got["verdict"] == "OK"
    assert got["front_door"] == "llama-swap"
    assert got["endpoint"] == "POST /v1/chat/completions"
    assert got["tls"] == "no"
    assert got["host"] == "loopback"
    assert got["synthetic_title"] == glimmer_proof.SYNTHETIC_TITLE
    assert got["synthetic_label"] == "iki-meeting"
    assert "title=" not in out.out.replace("synthetic_title=", "")
    blob = out.out + out.err
    for secret in ("figment", KEY, f":{server.port}", "127.0.0.1"):
        assert secret not in blob, secret
    assert "wait behind another request" in out.out


def test_gets_send_bearer_key(capsys: pytest.CaptureFixture[str]) -> None:
    """Every request carries the bearer key; a wrong key fails closed, no POST."""
    outside = _outside_windows()
    with _Server(_happy_routes()) as server:
        bad = _env(server.base())
        bad["LOCAL_LLM_API_KEY"] = "wrongword"
        code = main([], clock=lambda: outside, env=bad)
        out = capsys.readouterr()
        assert code == 2, out.err
        assert "FRONTDOOR_STATUS" in out.err
        assert "figment" not in out.out + out.err
        assert not [entry for entry in server.log if entry.startswith("POST")]
        assert any(entry.startswith("GET") for entry in server.log)


def test_empty_running_list_proceeds(capsys: pytest.CaptureFixture[str]) -> None:
    """An empty running list is the normal nothing-loaded state: resident no."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["GET /running"] = _route(200, json.dumps({"running": []}))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["resident"] == "no"
    assert _parse(out.out)["corroborated"] == "unknown"


def test_running_shape_failures(capsys: pytest.CaptureFixture[str]) -> None:
    """Only a missing key or a non-list running value is a shape failure."""
    outside = _outside_windows()
    for body in (json.dumps({}), json.dumps({"running": {}})):
        routes = dict(_happy_routes())
        routes["GET /running"] = _route(200, body)
        with _Server(routes) as server:
            code = main([], clock=lambda: outside, env=_env(server.base()))
            out = capsys.readouterr()
            assert code == 2, (body, out.err)
            assert "FRONTDOOR_SHAPE" in out.err
            assert not [e for e in server.log if e.startswith("POST")]


def test_other_model_in_any_state_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    """Another model refuses in any state; my own alias loading proceeds."""
    outside = _outside_windows()
    for state in ("ready", "starting", "loading"):
        routes = dict(_happy_routes())
        routes["GET /running"] = _route(
            200, json.dumps({"running": [_entry(ALIAS), _entry("other-9", state)]})
        )
        with _Server(routes) as server:
            code = main([], clock=lambda: outside, env=_env(server.base()))
            out = capsys.readouterr()
        assert code == 3, (state, out.err)
        assert "other-9" not in out.out + out.err
        assert not [e for e in server.log if e.startswith("POST")]
    # My own alias still starting: resident no, and the proof proceeds.
    routes = dict(_happy_routes())
    routes["GET /running"] = _route(
        200, json.dumps({"running": [_entry(ALIAS, "starting")]})
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    got = _parse(out.out)
    assert got["resident"] == "no"
    assert got["corroborated"] == "unknown"
    assert got["weights"] == "glimmer-30b.gguf"


def test_window_boundaries_refuse_first(capsys: pytest.CaptureFixture[str]) -> None:
    """Refusals read no env and send no request; one second outside allows."""
    assert (
        inspect.signature(orchestrator.run_slot).parameters["lead_minutes"].default
        == 25
    )
    assert glimmer_proof.WINDOW_LEAD_MINUTES == 25
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    with _Server(_happy_routes()) as server:
        for slot_time in orchestrator.SLOT_TIMES:
            slot = day.replace(hour=slot_time.hour, minute=slot_time.minute)
            start = slot - timedelta(minutes=25)
            end = slot - timedelta(minutes=4)
            # Exactly slot minus 25, exactly slot minus 4, and the look-ahead
            # boundary all refuse, with a valid environment that records reads.
            for moment in (start, end, start - timedelta(seconds=300)):
                env = _RecordingEnv(_env(server.base()))
                seen = len(server.log)
                code = main([], clock=lambda m=moment: m, env=env)
                err = capsys.readouterr().err
                assert code == 3, (slot_time, moment)
                assert "GLIMMER_WINDOW_REFUSED" in err
                assert "next=" in err
                assert env.reads == [], (slot_time, moment, env.reads)
                assert len(server.log) == seen, (slot_time, moment)
            # One second after slot minus 4, and one second before the
            # look-ahead start, allow and reach the server.
            for moment in (end + timedelta(seconds=1), start - timedelta(seconds=301)):
                env = _RecordingEnv(_env(server.base()))
                code = main([], clock=lambda m=moment: m, env=env)
                capsys.readouterr()
                assert code == 0, (slot_time, moment)
    assert any(entry.startswith("GET") for entry in server.log)


def test_refusal_next_is_madrid_first_second(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refusal names the first second it may run, in Madrid time."""
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    slot_time = orchestrator.SLOT_TIMES[0]
    slot = day.replace(hour=slot_time.hour, minute=slot_time.minute)
    end = slot - timedelta(minutes=4)
    with _Server(_happy_routes()) as server:
        code = main(
            [],
            clock=lambda: slot - timedelta(minutes=10),
            env=_RecordingEnv(_env(server.base())),
        )
        err = capsys.readouterr().err
    assert code == 3
    want = (end + timedelta(seconds=1)).isoformat()
    assert f"next={want}" in err


def test_root_keeps_prefix_and_brackets_ipv6() -> None:
    """Only a trailing /v1 comes off; a prefix and an IPv6 host survive."""
    assert (
        glimmer_proof._root_of("http://127.0.0.1:9/prefix/v1")
        == "http://127.0.0.1:9/prefix"
    )
    assert glimmer_proof._root_of("http://127.0.0.1:9/v1") == "http://127.0.0.1:9"
    assert (
        glimmer_proof._root_of("http://127.0.0.1:9/custom")
        == "http://127.0.0.1:9/custom"
    )
    assert glimmer_proof._root_of("http://[::1]:9/v1") == "http://[::1]:9"
    assert glimmer_proof._root_of("http://[::1]:9/prefix/v1") == "http://[::1]:9/prefix"


def test_prefix_base_proof_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    """A path prefix works and the endpoint shape prints as other."""
    outside = _outside_windows()
    with _Server(_prefixed("/prefix/v1")) as server:
        code = main([], clock=lambda: outside, env=_env(server.base("/prefix/v1")))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["endpoint"] == "other"


def test_window_clocks_agree_across_zones(capsys: pytest.CaptureFixture[str]) -> None:
    """A UTC clock and another zone clock give the same answers."""
    moment_madrid = datetime(2026, 11, 2, 12, 0, tzinfo=MADRID)
    moment_utc = moment_madrid.astimezone(UTC)
    other = moment_madrid.astimezone(ZoneInfo("Asia/Kathmandu"))
    with _Server(_happy_routes()) as server:
        codes = [
            main([], clock=lambda m=m: m, env=_env(server.base()))
            for m in (moment_madrid, moment_utc, other)
        ]
        capsys.readouterr()
    assert codes == [0, 0, 0]


def test_frontdoor_failures_stay_closed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """500, non-JSON, refused and timeout paths leak nothing and send no POST."""
    outside = _outside_windows()
    # 500 on the models endpoint.
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(500, "{}")
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
        assert code == 2, out.err
        assert "figment" not in out.out + out.err
        assert not [entry for entry in server.log if entry.startswith("POST")]
    # Non-JSON body.
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(200, "not json")
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
        assert code == 2, out.err
        assert not [entry for entry in server.log if entry.startswith("POST")]
    # Connection refused: nothing listening on this loopback port.
    env = _env(f"http://127.0.0.1:{_free_port()}/v1")
    code = main([], clock=lambda: outside, env=env)
    out = capsys.readouterr()
    assert code == 2, out.err
    assert KEY not in out.out + out.err
    assert "127.0.0.1" not in out.out + out.err
    # Timeout: the front door never answers in time; still no POST, no leak.
    # The GET timeout is patchable so this stays fast.
    monkeypatch.setattr(glimmer_proof, "GET_TIMEOUT_S", 1)
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(200, _models_body(), 3.0)
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 2, out.err
    assert "127.0.0.1" not in out.out + out.err


def test_frontdoor_plain_runtime_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    """A llamacpp front door refuses exit 2 with no POST."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(200, _models_body(owned_by="llamacpp"))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 2, out.err
    assert "FRONTDOOR" in out.err
    assert not [entry for entry in server.log if entry.startswith("POST")]


def test_resident_other_model_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    """Another resident model refuses exit 3 with no POST and no name."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["GET /running"] = _route(
        200,
        _running_body(
            extra=[
                {
                    "model": "other-weights-9",
                    "state": "ready",
                    "cmd": "x",
                    "proxy": "y",
                    "ttl": 1,
                    "name": "n",
                    "description": "d",
                }
            ]
        ),
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 3, out.err
    assert "other-weights-9" not in out.out + out.err
    assert not [entry for entry in server.log if entry.startswith("POST")]


def test_alias_must_name_glimmer(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-Glimmer alias refuses with no request at all."""
    outside = _outside_windows()
    with _Server(_happy_routes()) as server:
        code = main([], clock=lambda: outside, env=_env(server.base(), "wonder-1"))
        out = capsys.readouterr()
    assert code == 2, out.err
    assert server.log == []


def test_weights_must_name_glimmer(capsys: pytest.CaptureFixture[str]) -> None:
    """Served weights not named glimmer exit 1."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(
        200, _chat_body(model="/srv/figment/models/other-30b.gguf")
    )
    routes[f"GET /upstream/{ALIAS}/props"] = _route(
        200, _props_body("/srv/figment/models/other-30b.gguf")
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 1, out.err
    assert "figment" not in out.out + out.err


def test_upstream_order_after_chat(capsys: pytest.CaptureFixture[str]) -> None:
    """Moving the /upstream read before the chat call makes it fail."""
    outside = _outside_windows()
    with _Server(_happy_routes()) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        capsys.readouterr()
        assert code == 0
        log = server.log
    chat_at = next(i for i, entry in enumerate(log) if entry.startswith("POST"))
    up_at = next(i for i, entry in enumerate(log) if "/upstream/" in entry)
    assert chat_at < up_at


def test_exit_codes_matched_and_invalid(capsys: pytest.CaptureFixture[str]) -> None:
    """matched=no still exits 0; an invalid label exits 1; props vary."""
    outside = _outside_windows()
    # A valid label differing from expected prints matched=no, exit 0.
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(200, _chat_body(label="iki-rest"))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["matched"] == "no"
    # An invalid label exits 1.
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(
        200,
        json.dumps(
            {
                "model": MODEL_PATH,
                "choices": [
                    {"message": {"content": "nonsense!!"}, "finish_reason": "stop"}
                ],
                "usage": {"completion_tokens": 3},
            }
        ),
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        capsys.readouterr()
    assert code == 1
    # Props failure prints unknown and exits 0.
    routes = dict(_happy_routes())
    routes[f"GET /upstream/{ALIAS}/props"] = _route(500, "{}")
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["corroborated"] == "unknown"
    # Props disagreeing exits 1.
    routes = dict(_happy_routes())
    routes[f"GET /upstream/{ALIAS}/props"] = _route(
        200, _props_body("/srv/figment/models/glimmer-7b.gguf")
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        capsys.readouterr()
    assert code == 1
    # A base URL whose path is not exactly /v1 prints other.
    with _Server(_prefixed("/custom")) as server:
        code = main([], clock=lambda: outside, env=_env(server.base("/custom")))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["endpoint"] == "other"


def test_chat_alias_or_unknown_yields_props_weights(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A chat basename equal to the alias, or unknown, gives no basename."""
    outside = _outside_windows()
    # The chat field names the alias itself: weights come from props, one source.
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(200, _chat_body(model=ALIAS))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    got = _parse(out.out)
    assert got["weights"] == "glimmer-30b.gguf"
    assert got["corroborated"] == "unknown"
    # The chat field is missing: same single-source reading.
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(
        200,
        json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": json.dumps({"label": "iki-meeting"})},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"completion_tokens": 3},
            }
        ),
    )
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    got = _parse(out.out)
    assert got["weights"] == "glimmer-30b.gguf"
    assert got["corroborated"] == "unknown"
    # Neither source gives a basename: a closed code of its own, exit 1.
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(200, _chat_body(model=ALIAS))
    routes[f"GET /upstream/{ALIAS}/props"] = _route(500, "{}")
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 1, out.err
    assert "WEIGHTS_UNKNOWN" in out.err
    assert out.out == ""


def test_leak_check_fires_whole_value(capsys: pytest.CaptureFixture[str]) -> None:
    """A catalog quant equal to the secret puts it in the output: closed, no body."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(200, _models_body(quant=KEY))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 1, out.err
    assert "OUTPUT_LEAK" in out.err
    assert out.out == ""


def test_hyphenated_hostname_blocks_whole_name_only() -> None:
    """A hyphenated hostname blocks as a whole name, never as one piece."""
    from framework.provenance.glimmer_proof import _leaks

    tokens = {"my-host"}
    assert _leaks("weights my-host ready", [], tokens) is True
    assert _leaks("weights my ready", [], tokens) is False
    assert _leaks("weights host ready", [], tokens) is False


def test_quant_runtime_keep_original_case(capsys: pytest.CaptureFixture[str]) -> None:
    """UD-Q4_K_XL prints as itself through a closed shape."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["GET /v1/models"] = _route(200, _models_body(quant="UD-Q4_K_XL"))
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 0, out.err
    assert _parse(out.out)["quant"] == "UD-Q4_K_XL"


def test_model_id_short_names_and_home_user() -> None:
    """Short names never trip the checks; the home user always maps."""
    from framework.provenance.schemas import clean_model_id

    assert clean_model_id("ab", username="ab", hostname="xy") == "ab"
    assert clean_model_id("inference-9", username="bramble", hostname="node7") == (
        "inference-9"
    )
    assert (
        clean_model_id("bramble-9", username="bramble", hostname="node7") == "unknown"
    )
    assert clean_model_id("node7", username="bramble", hostname="node7") == "unknown"
    assert clean_model_id("/home/bramble", username="bramble", hostname="zz") == (
        "unknown"
    )
    assert clean_model_id("jo", username="jo", hostname="zz") == "jo"
    # The runtime username refuses through the /home/ form at any length.
    user = getpass.getuser()
    assert clean_model_id(f"/home/{user}") == "unknown"


def test_model_id_directory_url_host_and_suffix_rules() -> None:
    """Directories, bare hosts, URL roots and domain suffixes print unknown."""
    from framework.provenance.schemas import clean_model_id

    opts = {"username": "bramble", "hostname": "node7", "home_name": "bramble"}
    # A trailing separator means a directory, whatever the basename.
    assert clean_model_id("/srv/weights/glimmer-30b/", **opts) == "unknown"
    assert clean_model_id("C:\\models\\wonder-1\\", **opts) == "unknown"
    assert clean_model_id("/home/x/models/", **opts) == "unknown"
    # A last component directly under home or Users, or /root itself.
    assert clean_model_id("/home/otheruser", **opts) == "unknown"
    assert clean_model_id("/home/otheruser/", **opts) == "unknown"
    assert clean_model_id("/Users/otheruser", **opts) == "unknown"
    assert clean_model_id("/root", **opts) == "unknown"
    # A URL basename comes from its path only; no path means unknown.
    assert clean_model_id("https://host/x/wonder-1?tag=a", **opts) == "wonder-1"
    assert clean_model_id("https://host", **opts) == "unknown"
    assert clean_model_id("https://host/", **opts) == "unknown"
    # The home-user rule also runs on a URL's path.
    assert clean_model_id("file:///home/otheruser", **opts) == "unknown"
    assert clean_model_id("https://host/home/otheruser", **opts) == "unknown"
    assert clean_model_id("https://host/Users/otheruser", **opts) == "unknown"
    # A bare host:port prints the port, so a basename with no letter is unknown.
    assert clean_model_id("myhost:8080", **opts) == "unknown"
    assert clean_model_id("8080", **opts) == "unknown"
    # A name ending in a domain suffix looks like a host.
    for hostlike in ("node7.net", "weights.com", "cache.org", "srv.local"):
        assert clean_model_id(hostlike, **opts) == "unknown"
    # A hyphenated hostname matches whole, bounded by non-alphanumerics.
    assert (
        clean_model_id("my-host-weights", hostname="my-host", username="zz")
        == "unknown"
    )
    assert clean_model_id("amy-hostb", hostname="my-host", username="zz") == "amy-hostb"
    # Survivors: a normal weights path, a query URL, an scp-style path,
    # a dotted version id, and the T13 run's model id.
    assert (
        clean_model_id("/srv/figment/models/glimmer-30b.gguf", **opts)
        == "glimmer-30b.gguf"
    )
    assert (
        clean_model_id("figment@host:models/glimmer-30b.gguf", **opts)
        == "glimmer-30b.gguf"
    )
    assert clean_model_id("glimmer-30b.q4.gguf", **opts) == "glimmer-30b.q4.gguf"
    assert clean_model_id("muse-glimmer-30b", **opts) == "muse-glimmer-30b"


def test_window_reads_madrid_conversion_not_wall_clock(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reading the clock as Madrid wall time instead of converting makes it fail."""
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    kathmandu = ZoneInfo("Asia/Kathmandu")
    # Inside the 15:30 window in Madrid; the UTC and Kathmandu wall clocks
    # both read outside every window.
    inside = day.replace(hour=15, minute=10)
    assert inside.astimezone(UTC).strftime("%H:%M") == "14:10"
    assert inside.astimezone(kathmandu).strftime("%H:%M") == "19:55"
    with _Server(_happy_routes()) as server:
        for moment in (
            inside,
            inside.astimezone(UTC),
            inside.astimezone(kathmandu),
        ):
            code = main([], clock=lambda m=moment: m, env=_env(server.base()))
            err = capsys.readouterr().err
            assert code == 3, (moment, err)
            assert "GLIMMER_WINDOW_REFUSED" in err
        # The reverse: 16:10 Madrid sits outside every window, while its
        # UTC wall clock reads 15:10, inside the 15:30 window.
        outside = day.replace(hour=16, minute=10)
        assert outside.astimezone(UTC).strftime("%H:%M") == "15:10"
        code = main([], clock=lambda: outside.astimezone(UTC), env=_env(server.base()))
        out = capsys.readouterr()
        assert code == 0, out.err


def test_chat_weights_without_glimmer_refuses_when_props_unreadable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Removing the chat call's weights check makes it fail: props cannot save it."""
    outside = _outside_windows()
    routes = dict(_happy_routes())
    routes["POST /v1/chat/completions"] = _route(
        200, _chat_body(model="/srv/figment/models/other-30b.gguf")
    )
    routes[f"GET /upstream/{ALIAS}/props"] = _route(500, "{}")
    with _Server(routes) as server:
        code = main([], clock=lambda: outside, env=_env(server.base()))
        out = capsys.readouterr()
    assert code == 1, out.err
    assert "WEIGHTS_NOT_GLIMMER" in out.err
    assert "figment" not in out.out + out.err
