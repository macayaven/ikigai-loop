"""Source-audit fetch through an injected fake (Ticket E2 plan, fetch file)."""

import json

import pytest

from source_audit import fetch as F
from source_audit import snapshot as S

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"


def _resp(body, link=None, status=200):
    headers = {}
    if link is not None:
        headers["link"] = link
    return (status, headers, json.dumps(body).encode())


def _pull(i):
    return {
        "id": i,
        "number": i,
        "created_at": "2026-10-29T01:00:00Z",
        "user": {"login": USER},
    }


def _activity(i):
    return {
        "id": str(7000 + i),
        "timestamp": "2026-10-29T01:00:00Z",
        "activity_type": "pr_merge",
        "before": "b" * 40,
        "after": "a" * 40,
        "actor": {"login": USER},
    }


def _event(i, action: str | None = "opened"):
    payload = {"action": action, "number": i} if action else {"push_id": i}
    if action:
        payload = {"action": action, "number": i}
        out = {
            "id": str(i),
            "type": "PullRequestEvent",
            "repo": {"name": REPO},
            "actor": {"login": USER},
            "created_at": "2026-10-29T01:00:00Z",
            "payload": payload,
        }
    else:
        out = {
            "id": str(i),
            "type": "PushEvent",
            "repo": {"name": REPO},
            "actor": {"login": USER},
            "created_at": "2026-10-29T01:00:00Z",
            "payload": {"push_id": i, "head": "a" * 40, "before": "b" * 40},
        }
    out["payload"]["title_sentinel"] = "sentinel-title-abc"
    return out


class _Fake:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []
        self.headers = []

    def __call__(self, url, headers):
        self.urls.append(url)
        self.headers.append(dict(headers))
        return self.pages[len(self.urls) - 1]


def _three_endpoint_fake():
    return _Fake(
        [
            _resp(
                [_event(1), _event(0, None)],
                '<https://api.github.com/user/42/events/public?page=2>; rel="next"',
            ),
            _resp([]),
            _resp([_pull(1)]),
            _resp([_activity(1)]),
        ]
    )


def test_no_authorization_header_with_token_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token-value")
    fake = _three_endpoint_fake()
    F.run_fetch(USER, REPO, tmp_path / "s.json", http_get=fake)
    assert fake.headers
    for headers in fake.headers:
        assert "Authorization" not in headers
        assert headers["User-Agent"] == "ikigai-loop-source-audit"


def test_only_three_endpoints():
    fake = _three_endpoint_fake()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        F.run_fetch(USER, REPO, tmp + "/s.json", http_get=fake)
    assert fake.urls[0] == (
        f"https://api.github.com/users/{USER}/events/public?per_page=100"
    )
    assert fake.urls[2] == (
        f"https://api.github.com/repos/{REPO}/pulls"
        "?state=all&sort=created&direction=desc&per_page=100"
    )
    assert fake.urls[3] == (
        f"https://api.github.com/repos/{REPO}/activity?per_page=100"
    )
    assert fake.urls[1] == "https://api.github.com/user/42/events/public?page=2"
    for url in fake.urls:
        assert url.startswith("https://api.github.com/")


def test_sentinels_in_payload_never_reach_file(tmp_path):
    out = tmp_path / "s.json"
    F.run_fetch(USER, REPO, out, http_get=_three_endpoint_fake())
    raw = out.read_bytes()
    assert b"sentinel-title-abc" not in raw
    snap = S.load_snapshot(out)
    assert snap["user"] == USER


def test_short_page_with_next_link_keeps_going(tmp_path):
    out = tmp_path / "s.json"
    F.run_fetch(USER, REPO, out, http_get=_three_endpoint_fake())
    snap = S.load_snapshot(out)
    assert len(snap["events"]) == 2
    assert len(snap["pulls"]) == 1


def test_all_endpoints_follow_link_only(tmp_path):
    out = tmp_path / "s.json"
    fake = _three_endpoint_fake()
    F.run_fetch(USER, REPO, out, http_get=fake)
    firsts = {
        f"https://api.github.com/users/{USER}/events/public?per_page=100",
        (
            f"https://api.github.com/repos/{REPO}/pulls"
            "?state=all&sort=created&direction=desc&per_page=100"
        ),
        f"https://api.github.com/repos/{REPO}/activity?per_page=100",
    }
    advertised = {
        "https://api.github.com/user/42/events/public?page=2",
    }
    for url in fake.urls:
        assert url in firsts or url in advertised, url


def test_refused_later_page_is_coverage_not_failure(tmp_path):
    out = tmp_path / "s.json"
    fake = _Fake(
        [
            _resp(
                [_event(1)],
                '<https://api.github.com/user/42/events/public?page=2>; rel="next"',
            ),
            (403, {}, b"{}"),
            _resp([_pull(1)]),
            _resp([_activity(1)]),
        ]
    )
    F.run_fetch(USER, REPO, out, http_get=fake)
    snap = S.load_snapshot(out)
    assert out.exists()
    assert snap["coverage"]["events"]["stop"] == "github_pagination_refusal"


def test_first_page_403_fails_with_no_file(tmp_path):
    out = tmp_path / "snap.json"
    fake = _Fake([(403, {}, b"{}")])
    with pytest.raises(F.FetchError) as exc:
        F.run_fetch(USER, REPO, out, http_get=fake)
    assert exc.value.code == "FETCH_RATE_LIMITED"
    assert not out.exists()
    assert not any(out.parent.glob("snap.json.*"))
    assert list(out.parent.iterdir()) == []


def test_bad_user_rejected_before_any_request(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: calls.append(args) or None
    )
    with pytest.raises(F.FetchError) as exc:
        F.run_fetch("bad user!", REPO, tmp_path / "s.json")
    assert exc.value.code == "USAGE_BAD_USER"
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_coverage_counts_unprojected_rows(tmp_path):
    out = tmp_path / "s.json"
    fake = _Fake(
        [
            _resp(
                [_event(1), {"junk": "row"}],
                '<https://api.github.com/user/42/events/public?page=2>; rel="next"',
            ),
            _resp([]),
            _resp([_pull(1)]),
            _resp([_activity(1)]),
        ]
    )
    F.run_fetch(USER, REPO, out, http_get=fake)
    snap = S.load_snapshot(out)
    assert snap["coverage"]["events"]["rows"] == 2
    assert len(snap["events"]) == 1


class _RawResponse:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _http_error(code):
    import io
    import urllib.error
    from email.message import Message

    return urllib.error.HTTPError(
        "https://api.github.com/x", code, "reason", Message(), io.BytesIO(b"{}")
    )


def _urlopen_fake(monkeypatch, behaviours):
    import urllib.request

    calls = []

    def _fake(request, timeout=None):
        calls.append(request.full_url)
        action = behaviours[min(len(calls) - 1, len(behaviours) - 1)]
        if isinstance(action, Exception):
            raise action
        status, headers, body = action
        return _RawResponse(status, headers, body)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    return calls


def _ok_page(body, link=None):
    import json as _json

    headers = {}
    if link is not None:
        headers["link"] = link
    return (200, headers, _json.dumps(body).encode())


def test_first_page_403_is_rate_limited_without_socket(tmp_path, monkeypatch):
    _urlopen_fake(monkeypatch, [_http_error(403)])
    with pytest.raises(F.FetchError) as exc:
        F.run_fetch(USER, REPO, tmp_path / "s.json")
    assert exc.value.code == "FETCH_RATE_LIMITED"
    assert list(tmp_path.iterdir()) == []


def test_first_page_404_fails_without_socket(tmp_path, monkeypatch):
    _urlopen_fake(monkeypatch, [_http_error(404)])
    with pytest.raises(F.FetchError) as exc:
        F.run_fetch(USER, REPO, tmp_path / "s.json")
    assert exc.value.code == "FETCH_FIRST_PAGE_FAILED"
    assert list(tmp_path.iterdir()) == []


def test_later_page_422_is_coverage_without_socket(tmp_path, monkeypatch):
    link = '<https://api.github.com/user/42/events/public?page=2>; rel="next"'
    _urlopen_fake(
        monkeypatch,
        [
            _ok_page([_event(1)], link),
            _http_error(422),
            _ok_page([_pull(1)]),
            _ok_page([_activity(1)]),
        ],
    )
    out = tmp_path / "s.json"
    snap = F.run_fetch(USER, REPO, out)
    assert snap["coverage"]["events"]["stop"] == "github_pagination_refusal"
    assert out.exists()


def test_later_page_network_failure_is_coverage_without_socket(tmp_path, monkeypatch):
    import urllib.error

    link = '<https://api.github.com/user/42/events/public?page=2>; rel="next"'
    _urlopen_fake(
        monkeypatch,
        [
            _ok_page([_event(1)], link),
            urllib.error.URLError("boom"),
            _ok_page([_pull(1)]),
            _ok_page([_activity(1)]),
        ],
    )
    out = tmp_path / "s.json"
    snap = F.run_fetch(USER, REPO, out)
    assert snap["coverage"]["events"]["stop"] == "github_pagination_refusal"
    assert out.exists()


def test_next_url_on_other_host_never_requested(tmp_path):
    out = tmp_path / "s.json"
    fake = _Fake(
        [
            _resp(
                [_event(1)],
                '<https://evil-owner.example.com/user/42/events>; rel="next"',
            ),
            _resp([_pull(1)]),
            _resp([_activity(1)]),
        ]
    )
    F.run_fetch(USER, REPO, out, http_get=fake)
    snap = S.load_snapshot(out)
    assert snap["coverage"]["events"]["stop"] == "github_pagination_refusal"
    assert len(snap["events"]) == 1
    assert not any("evil-owner.example.com" in url for url in fake.urls)
    assert len(fake.urls) == 3


def test_next_url_with_http_scheme_never_requested(tmp_path):
    out = tmp_path / "s.json"
    fake = _Fake(
        [
            _resp(
                [_event(1)],
                '<http://api.github.com/user/42/events/public?page=2>; rel="next"',
            ),
            _resp([_pull(1)]),
            _resp([_activity(1)]),
        ]
    )
    F.run_fetch(USER, REPO, out, http_get=fake)
    snap = S.load_snapshot(out)
    assert snap["coverage"]["events"]["stop"] == "github_pagination_refusal"
    assert len(snap["events"]) == 1
    assert not any(url.startswith("http://") for url in fake.urls)
    assert len(fake.urls) == 3


def _base_snapshot():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = tmp + "/s.json"
        F.run_fetch(USER, REPO, out, http_get=_three_endpoint_fake())
        return S.load_snapshot(out)


def test_snapshot_reader_rejects_each_shape_violation():
    import copy

    cases = []
    event_extra = lambda s: s["events"][0].update(title="x")
    cases.append(("event-unknown-field", event_extra))
    cases.append(("pull-unknown-field", lambda s: s["pulls"][0].update(title="x")))
    cases.append(
        ("activity-unknown-field", lambda s: s["activity"][0].update(title="x"))
    )
    cases.append(("top-unknown-field", lambda s: s.update(extra="x")))
    cases.append(
        ("coverage-unknown-field", lambda s: s["coverage"]["events"].update(extra="x")),
    )
    cases.append(("event-missing-field", lambda s: s["events"][0].pop("id")))
    cases.append(("event-bad-head", lambda s: s["events"][0].update(head="ZZZ")))
    cases.append(("event-bad-before", lambda s: s["events"][0].update(before="Q")))
    cases.append(("activity-bad-after", lambda s: s["activity"][0].update(after="xyz")))
    cases.append(
        ("event-login-space", lambda s: s["events"][0].update(actor="bad user"))
    )
    cases.append(
        ("event-repo-no-slash", lambda s: s["events"][0].update(repo="noslash"))
    )
    cases.append(
        ("event-bad-instant", lambda s: s["events"][0].update(created_at="yesterday")),
    )
    cases.append(("event-negative-pr", lambda s: s["events"][0].update(pr_number=-1)))
    cases.append(
        ("coverage-bad-stop", lambda s: s["coverage"]["events"].update(stop="bogus")),
    )
    for name, mutate in cases:
        snap = copy.deepcopy(_base_snapshot())
        mutate(snap)
        try:
            S.validate_snapshot(snap)
        except S.SnapshotError as exc:
            assert exc.code == "SNAPSHOT_INVALID", name
        else:
            raise AssertionError(f"{name} was accepted")


def test_bad_repo_rejected(tmp_path):
    with pytest.raises(F.FetchError) as exc:
        F.run_fetch(
            USER, "no-slash-here", tmp_path / "s.json", http_get=_three_endpoint_fake()
        )
    assert exc.value.code == "USAGE_BAD_REPO"
