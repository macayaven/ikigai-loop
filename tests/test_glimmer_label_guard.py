"""Ticket 9c: the local-endpoint allowlist guard, allow and refuse cases."""

from typing import Self

import pytest

from framework.glimmer.label_step import is_private_llm_base_url

ALLOW = [
    "https://synthetic-box.synthetic-net.ts.net/v1",
    "https://SYNTHETIC-BOX.SYNTHETIC-NET.TS.NET:8443/v1",
    "http://127.0.0.1:8400/v1",
    "http://127.1.2.3:8400/v1",
    "http://[::1]:8400/v1",
    "http://localhost:8400/v1",
    "https://localhost/v1",
    "https://100.64.0.1/v1",
    "https://100.127.255.254/v1",
    "https://10.1.2.3/v1",
    "https://172.16.0.1/v1",
    "https://172.31.255.254/v1",
    "https://192.168.1.2/v1",
    "https://[fd7a:115c:a1e0::1]/v1",
]

REFUSE = [
    "https://api.meta.ai/v1",
    "https://api.openai.com/v1",
    "https://8.8.8.8/v1",
    "https://100.128.0.1/v1",
    "https://100.63.255.255/v1",
    "https://172.32.0.1/v1",
    "https://192.0.2.1/v1",
    "https://198.18.0.1/v1",
    "https://169.254.169.254/v1",
    "https://0.0.0.0/v1",
    "https://240.0.0.1/v1",
    "https://[::ffff:8.8.8.8]/v1",
    "https://[::ffff:127.0.0.1]/v1",
    "https://[2001:4860:4860::8888]/v1",
    "https://[fe80::1]/v1",
    "https://[2001:db8::1]/v1",
    "https://[64:ff9b::808:808]/v1",
    "https://134744072/v1",
    "https://0x08080808/v1",
    "https://2130706433/v1",
    "https://0177.0.0.1/v1",
    "https://010.0.0.1/v1",
    "https://synthetic-box/v1",
    "https://synthetic-box.local/v1",
    "https://ts.net/v1",
    "https://x.ts.net/v1",
    "https://a.b.c.ts.net/v1",
    "https://evilts.net/v1",
    "https://a.b.ts.net.evil.example/v1",
    "https://synthetic-box.synthetic-net.ts.net./v1",
    "http://evil.example\\.ts.net/v1",
    "http://evil.example%2f.ts.net/",
    "https://-a.b.ts.net/v1",
    "https://user@synthetic-box.synthetic-net.ts.net/v1",
    "https://a.b.ts.net:443@evil.example/",
    "https://127.0.0.1@evil.example/",
    "http://synthetic-box.synthetic-net.ts.net/v1",
    "http://10.0.0.1/v1",
    "http://100.64.0.1/v1",
    "http://[fd7a:115c:a1e0::1]/v1",
    "http://127.0.0.1:8400/v1\n",
    "https://a.b.ts.net/v1\t",
    "http://127.0.\t0.1:8400/v1",
    "http://127.0.0.1:8400/vé",
    "",
    "https://",
    "https:///v1",
    "ftp://127.0.0.1/",
    "127.0.0.1:8400",
    "https://localhost.evil.example/v1",
    "https://a.b.ts.net/v1?x=1",
    "https://a.b.ts.net/v1#f",
    "https://a.b.ts.net:99999/v1",
    "https://[::1/v1",
    "https://exam\tple.invalid/v1",
    "https://example.invalid/v1\n",
    "https://ex ample.invalid/v1",
    "https://\u00e9xample.invalid/v1",
]


@pytest.mark.parametrize("url", ALLOW)
def test_guard_allows_private_endpoints(url: str) -> None:
    assert is_private_llm_base_url(url) is True


@pytest.mark.parametrize("url", REFUSE)
def test_guard_refuses_everything_else(url: str) -> None:
    assert is_private_llm_base_url(url) is False


def test_build_client_refuses_public_url_without_naming_it() -> None:
    from framework.glimmer.label_step import build_label_client

    environ = {
        "LOCAL_LLM_BASE_URL": "https://8.8.8.8/v1",
        "LOCAL_LLM_MODEL": "synthetic-model",
        "LOCAL_LLM_API_KEY": "synthetic-key",
    }
    with pytest.raises(ValueError) as excinfo:
        build_label_client(environ)
    assert "8.8.8.8" not in str(excinfo.value)


def test_build_client_on_loopback_carries_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    import urllib.request

    from framework.glimmer import llm as llm_module
    from framework.glimmer.label_step import (
        LABEL_RESPONSE_FORMAT,
        build_label_client,
    )

    environ = {
        "LOCAL_LLM_BASE_URL": "http://127.0.0.1:8400/v1",
        "LOCAL_LLM_MODEL": "synthetic-model",
        "LOCAL_LLM_API_KEY": "synthetic-key",
    }
    client = build_label_client(environ)
    assert client.response_format == LABEL_RESPONSE_FORMAT

    seen: dict[str, object] = {}

    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "model": "synthetic-model",
                    "choices": [{"message": {"content": '{"label": "iki-deep"}'}}],
                }
            ).encode()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def _fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        seen["request"] = request
        return _FakeResponse()

    monkeypatch.setattr(llm_module, "urlopen", _fake_urlopen)
    client.complete("Invented prompt")
    request = seen["request"]
    assert isinstance(request, urllib.request.Request)
    assert isinstance(request.data, bytes)
    sent = json.loads(request.data.decode())
    assert sent["response_format"] == LABEL_RESPONSE_FORMAT
