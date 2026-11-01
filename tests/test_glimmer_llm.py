"""Ticket 9: LLM edge client with a monkeypatched urlopen (no network)."""

from __future__ import annotations

import json
import urllib.error
from typing import Any, Self

import pytest

from framework.glimmer import llm as llm_module
from framework.glimmer.facts import LLMUnavailableError
from framework.glimmer.llm import OpenAICompatibleClient, load_llm_config

PROMPT = "Say facts."
KEY = "secret-key-xyz"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._body = json.dumps(payload).encode()
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://example.invalid/v1",
        model="requested-model",
        api_key=KEY,
    )


def _body(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        seen["request"] = request
        seen["timeout"] = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    return seen


def _content(text: str, **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"content": text}
    message.update(extra)
    return {
        "model": "registry/models/mock-7b",
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 12},
    }


def test_request_shape_and_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _body(monkeypatch, _content("ok"))
    response = _client().complete(PROMPT)
    assert response.text == "ok"
    request = seen["request"]
    assert request.full_url == "https://example.invalid/v1/chat/completions"
    sent = json.loads(request.data.decode())
    assert sent == {
        "model": "requested-model",
        "temperature": 0,
        "max_tokens": 32768,
        "messages": [{"role": "user", "content": PROMPT}],
    }
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert seen["timeout"] == 1800
    assert response.finish_reason == "stop"
    assert response.completion_tokens == 12


def test_model_id_sanitises_posix_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _content("ok")
    payload["model"] = "registry/models/mock-7b"
    _body(monkeypatch, payload)
    assert _client().complete(PROMPT).model_id == "mock-7b"


def test_model_id_sanitises_windows_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _content("ok")
    payload["model"] = "C:\\models\\mock-7b"
    _body(monkeypatch, payload)
    assert _client().complete(PROMPT).model_id == "mock-7b"


def test_model_id_unreported_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _content("ok")
    del payload["model"]
    _body(monkeypatch, payload)
    assert _client().complete(PROMPT).model_id == "unreported"


def test_reasoning_content_never_reaches_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _content("visible", reasoning_content="hidden chain of thought")
    _body(monkeypatch, payload)
    response = _client().complete(PROMPT)
    assert response.text == "visible"
    assert "hidden chain" not in response.text


def test_timeout_raises_unavailable_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert KEY not in str(excinfo.value)


def test_url_error_raises_unavailable_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert KEY not in str(excinfo.value)


def test_non_2xx_raises_unavailable_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise urllib.error.HTTPError(
            url="https://example.invalid/v1/chat/completions",
            code=500,
            msg="boom",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert "500" in str(excinfo.value)
    assert KEY not in str(excinfo.value)


def test_load_llm_config_missing_names_variable() -> None:
    with pytest.raises(SystemExit) as excinfo:
        load_llm_config(environ={})
    assert "LOCAL_LLM_BASE_URL" in str(excinfo.value)


def test_load_llm_config_empty_names_variable() -> None:
    env = {
        "LOCAL_LLM_BASE_URL": "https://example.invalid/v1",
        "LOCAL_LLM_MODEL": "",
        "LOCAL_LLM_API_KEY": KEY,
    }
    with pytest.raises(SystemExit) as excinfo:
        load_llm_config(environ=env)
    assert "LOCAL_LLM_MODEL" in str(excinfo.value)
    assert KEY not in str(excinfo.value)


def _raises_without_context(fn: object) -> LLMUnavailableError:
    import traceback

    try:
        assert callable(fn)
        fn()  # type: ignore[operator]
    except LLMUnavailableError as exc:
        assert exc.__context__ is None
        assert exc.__cause__ is None
        formatted = "".join(traceback.format_exception(exc))
        assert "SENTINEL" not in formatted, formatted
        return exc
    raise AssertionError("expected LLMUnavailableError")


def test_header_value_error_leaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise ValueError("Invalid header value b'Bearer SENTINEL\\n'")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    exc = _raises_without_context(lambda: _client().complete(PROMPT))
    assert str(exc) == "transport error"


def test_remote_disconnected_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import http.client

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise http.client.RemoteDisconnected("Remote end closed SENTINEL")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    _raises_without_context(lambda: _client().complete(PROMPT))


def test_incomplete_read_leaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise http.client.IncompleteRead(b"SENTINEL", 8)

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    _raises_without_context(lambda: _client().complete(PROMPT))


def test_invalid_url_leaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise http.client.InvalidURL("SENTINEL")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    exc = _raises_without_context(lambda: _client().complete(PROMPT))
    assert str(exc) == "transport error"


def test_connection_reset_leaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise ConnectionResetError("SENTINEL reset by peer")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    _raises_without_context(lambda: _client().complete(PROMPT))


def test_read_failure_leaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadRead(_FakeResponse):
        def read(self) -> bytes:
            raise ConnectionResetError("SENTINEL during read")

    def fake_urlopen(request: object, timeout: object = None) -> _BadRead:
        return _BadRead({})

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    _raises_without_context(lambda: _client().complete(PROMPT))


def test_bad_base_url_gives_transport_error() -> None:
    client = OpenAICompatibleClient(
        base_url="not-a-url", model="m", api_key="k", timeout_s=5
    )
    with pytest.raises(LLMUnavailableError) as excinfo:
        client.complete(PROMPT)
    assert str(excinfo.value) == "transport error"
    assert excinfo.value.__context__ is None
    assert excinfo.value.__cause__ is None


def _invalid_body(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> None:
    class _Raw(_FakeResponse):
        def read(self) -> bytes:
            return raw

    def fake_urlopen(request: object, timeout: object = None) -> _Raw:
        return _Raw({})

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert str(excinfo.value) == "invalid response"
    assert KEY not in str(excinfo.value)


def test_wrong_shape_bodies_are_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    for payload in (
        b"[]",
        b"{}",
        b'{"choices": []}',
        b'{"choices": [{}]}',
        b'{"choices": [{"message": []}]}',
    ):
        _invalid_body(monkeypatch, payload)


def test_bad_json_and_encoding_are_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalid_body(monkeypatch, b"{not json")
    _invalid_body(monkeypatch, b"\xff\xfe invalid utf-8 \x00")
    _invalid_body(monkeypatch, b"[" * 50000 + b"]" * 50000)


def test_non_string_content_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    for content in (42, ["a"], {"text": "a"}):
        payload = _content("ok")
        payload["choices"][0]["message"]["content"] = content  # type: ignore[index]
        seen = _body(monkeypatch, payload)
        assert seen is not None
        with pytest.raises(LLMUnavailableError) as excinfo:
            _client().complete(PROMPT)
        assert str(excinfo.value) == "invalid response"


def test_null_and_absent_content_give_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _content("ok")
    payload["choices"][0]["message"]["content"] = None  # type: ignore[index]
    _body(monkeypatch, payload)
    response = _client().complete(PROMPT)
    assert response.text == ""
    assert response.finish_reason == "stop"
    payload = _content("ok")
    del payload["choices"][0]["message"]["content"]  # type: ignore[index]
    _body(monkeypatch, payload)
    response = _client().complete(PROMPT)
    assert response.text == ""
    assert response.finish_reason == "stop"


def test_non_object_usage_gives_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _content("ok")
    payload["usage"] = ["completion_tokens"]  # type: ignore[assignment]
    _body(monkeypatch, payload)
    response = _client().complete(PROMPT)
    assert response.text == "ok"
    assert response.completion_tokens is None


def test_no_redirect_handler_unit() -> None:
    import urllib.request

    handler = llm_module.NoRedirectHandler()
    request = urllib.request.Request("https://example.invalid/v1/chat/completions")
    assert (
        handler.redirect_request(request, None, 302, "Found", {}, "https://x/") is None
    )
    assert isinstance(handler, urllib.request.HTTPRedirectHandler)


def test_redirect_surfaces_as_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise http.client.HTTPException("unused")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert str(excinfo.value) == "transport error"


def test_unavailable_carries_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise TimeoutError("slow")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert str(excinfo.value) == "timeout"
    assert excinfo.value.latency_ms >= 0
    assert LLMUnavailableError("x").latency_ms == 0


def test_trailing_slash_base_url_single_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _body(monkeypatch, _content("ok"))
    client = OpenAICompatibleClient(
        base_url="https://example.invalid/v1/", model="m", api_key=KEY
    )
    client.complete(PROMPT)
    url = seen["request"].full_url
    assert url == "https://example.invalid/v1/chat/completions"
    assert url.count("chat/completions") == 1
    assert "/chat/completions" in url
    assert "//chat/completions" not in url


def test_api_key_shape_rejected_without_value() -> None:
    bad_keys = (
        "key with space",
        "key\nnewline",
        "key\ttab",
        "Ünïcödé-key",
        "key\x00null",
        " key-lead",
    )
    for bad in bad_keys:
        env = {
            "LOCAL_LLM_BASE_URL": "https://example.invalid/v1",
            "LOCAL_LLM_MODEL": "m",
            "LOCAL_LLM_API_KEY": bad,
        }
        with pytest.raises(SystemExit) as excinfo:
            load_llm_config(environ=env)
        message = str(excinfo.value)
        assert "LOCAL_LLM_API_KEY" in message
        assert bad not in message


def test_base_url_shape_rejected_without_value() -> None:
    bad_urls = (
        "not-a-url",
        "ftp://example.invalid/v1",
        "https://example.invalid/v1 with space",
        "https://example.invalid/v1\n",
        "https:///v1",
        "https://\x00/v1",
    )
    for bad in bad_urls:
        env = {
            "LOCAL_LLM_BASE_URL": bad,
            "LOCAL_LLM_MODEL": "m",
            "LOCAL_LLM_API_KEY": KEY,
        }
        with pytest.raises(SystemExit) as excinfo:
            load_llm_config(environ=env)
        message = str(excinfo.value)
        assert "LOCAL_LLM_BASE_URL" in message
        assert bad not in message


def test_unavailable_error_carries_elapsed_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([1000.0, 1001.5])
    monkeypatch.setattr(llm_module.time, "monotonic", lambda: next(ticks))

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        raise TimeoutError("slow")

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert str(excinfo.value) == "timeout"
    assert excinfo.value.latency_ms == 1500


def test_invalid_response_error_carries_elapsed_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([800.0, 800.25])
    monkeypatch.setattr(llm_module.time, "monotonic", lambda: next(ticks))

    class _Raw(_FakeResponse):
        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: object = None) -> _Raw:
        return _Raw({})

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert str(excinfo.value) == "invalid response"
    assert excinfo.value.latency_ms == 250


def test_opener_refuses_redirects_without_stock_handler() -> None:
    import urllib.request

    opener = llm_module._OPENER
    handlers = list(opener.handlers)  # type: ignore[attr-defined]
    assert any(isinstance(h, llm_module.NoRedirectHandler) for h in handlers)
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in handlers)


def test_opener_holds_no_proxy_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    monkeypatch.setenv("https_proxy", "http://proxy.invalid:9")
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:9")
    opener = llm_module._OPENER
    registries = (
        getattr(opener, "handle_open", {}),
        getattr(opener, "handle_error", {}),
        getattr(opener, "process_response", {}),
        getattr(opener, "process_request", {}),
    )
    assert registries[0] != {}
    for registry in registries:
        for kind, handlers in registry.items():
            assert not any(
                isinstance(h, urllib.request.ProxyHandler) for h in handlers
            ), kind
    # Positive control: a default opener routes http through a ProxyHandler,
    # so the scan above is capable of finding one.
    default_open = getattr(urllib.request.build_opener(), "handle_open", {})
    default_http = default_open.get("http", [])
    assert any(isinstance(h, urllib.request.ProxyHandler) for h in default_http)


def test_redirect_30x_surfaces_as_unavailable_with_single_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            url="https://example.invalid/v1/chat/completions",
            code=302,
            msg="Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailableError) as excinfo:
        _client().complete(PROMPT)
    assert "302" in str(excinfo.value)
    assert KEY not in str(excinfo.value)
    assert calls == 1


def test_proxy_env_ignored_in_fresh_interpreter() -> None:
    """Proxy variables set before import still reach no local request.

    The module-level ``_OPENER`` is built with ``ProxyHandler({})``, which
    the stdlib registers nowhere, so a process started with
    ``http_proxy``/``https_proxy`` pointing at an unused loopback port must
    hold no proxy on the local opener. Runs in a subprocess so the import
    happens with the variables already set, and opens no socket: it only
    inspects handler state. A default opener built in the same process is
    the positive control: it must show the injected proxy, proving the
    scan is capable of finding one.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["http_proxy"] = "http://127.0.0.1:9/"
    env["https_proxy"] = "http://127.0.0.1:9/"
    env["PYTHONPATH"] = str(root)
    script = (
        "import json, urllib.request;"
        "import framework.glimmer.llm as m;"
        "seen = [h.proxies for reg in"
        " ('handle_open', 'handle_error', 'process_response',"
        " 'process_request')"
        " for handlers in getattr(m._OPENER, reg).values()"
        " for h in handlers"
        " if isinstance(h, urllib.request.ProxyHandler)];"
        "default = urllib.request.build_opener();"
        "control = [h.proxies for handlers in"
        " default.handle_open.values() for h in handlers"
        " if isinstance(h, urllib.request.ProxyHandler)];"
        "print(json.dumps({'seen': seen, 'control': control}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(root),
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    import json as _json

    payload = _json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["seen"] == []
    assert len(payload["control"]) >= 1
    assert all(entry != {} for entry in payload["control"])


def test_request_body_gains_response_format_only_on_label_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _body(monkeypatch, _content("ok"))
    _client().complete(PROMPT)
    sent = json.loads(seen["request"].data.decode())
    assert "response_format" not in sent

    from framework.glimmer.label_step import LABEL_RESPONSE_FORMAT

    labelled = OpenAICompatibleClient(
        base_url="https://example.invalid/v1",
        model="requested-model",
        api_key=KEY,
        response_format=LABEL_RESPONSE_FORMAT,
    )
    seen_labelled = _body(monkeypatch, _content('{"label": "iki-deep"}'))
    labelled.complete(PROMPT)
    sent_labelled = json.loads(seen_labelled["request"].data.decode())
    assert sent_labelled["response_format"] == LABEL_RESPONSE_FORMAT
    assert sent_labelled["model"] == "requested-model"
    assert sent_labelled["temperature"] == 0
    assert sent_labelled["max_tokens"] == 32768
