"""Ticket 5: collectors CLI tests (counts only, never content)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from framework.collectors.__main__ import build_collector, main
from framework.collectors.common import HttpResponse

GITHUB_USER = "synthetic-user"
GITHUB_URL = f"https://api.github.com/users/{GITHUB_USER}/events?per_page=100"
NOW = datetime.fromisoformat("2026-10-30T12:00:00+01:00")


def github_http_get(url: str, headers: dict[str, str]) -> HttpResponse:
    assert url == GITHUB_URL, f"unexpected URL: {url}"
    body = json.dumps(
        [
            {
                "id": "1001",
                "type": "PushEvent",
                "repo": {"name": "synthetic/push-repo"},
                "payload": {"size": 2},
                "created_at": "2026-10-29T10:00:00Z",
            }
        ]
    ).encode("utf-8")
    return HttpResponse(status=200, headers={}, body=body)


def failing_http_get(url: str, headers: dict[str, str]) -> HttpResponse:
    return HttpResponse(status=500, headers={}, body=b"[]")


def test_build_collector_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert build_collector("calendar", github_http_get).name == "calendar-personal"
    assert (
        build_collector("calendar", github_http_get, label="home").name
        == "calendar-home"
    )
    assert build_collector("github", github_http_get).name == "github"
    assert build_collector("feed", github_http_get).name == "feed"
    with pytest.raises(ValueError, match="unknown collector"):
        build_collector("frobnicator", github_http_get)
    with pytest.raises(ValueError, match="invalid calendar label"):
        build_collector("calendar", github_http_get, label="Home")


def test_cli_happy_path_prints_only_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    db_path = tmp_path / "cli.db"
    code = main(["run", "github"], http_get=github_http_get, db_path=db_path)
    assert code == 0
    out, err = capsys.readouterr()
    assert out == "inserted=1 conflicts=0\n"
    assert err == ""
    for forbidden in ("synthetic/push-repo", "1001", "api.github.com", "push"):
        assert forbidden not in out


def test_cli_error_path_reports_only_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    code = main(["run", "github"], http_get=failing_http_get, db_path=tmp_path / "e.db")
    assert code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert err.endswith("\n")
    assert "api.github.com" not in err


def test_cli_calendar_label_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "ICAL_URL_HOME", "https://example.invalid/secret-home-calendar-token.ics"
    )
    monkeypatch.delenv("ICAL_URL_PERSONAL", raising=False)
    monkeypatch.delenv("ICAL_URL", raising=False)
    home_ics = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//ikigai-loop//synthetic//EN\n"
        b"BEGIN:VEVENT\nUID:synthetic-home-1\nDTSTAMP:20261025T080000Z\n"
        b"DTSTART:20261102T150000Z\nDTEND:20261102T160000Z\n"
        b"LAST-MODIFIED:20261025T090000Z\nSUMMARY:Home synthetic session\n"
        b"END:VEVENT\nEND:VCALENDAR\n"
    )

    def home_http_get(url: str, headers: dict[str, str]) -> HttpResponse:
        assert url == "https://example.invalid/secret-home-calendar-token.ics"
        return HttpResponse(status=200, headers={}, body=home_ics)

    db_path = tmp_path / "home.db"
    code = main(
        ["run", "calendar", "--label", "home"],
        http_get=home_http_get,
        now_fn=lambda: NOW,
        db_path=db_path,
    )
    assert code == 0
    out, err = capsys.readouterr()
    assert out == "inserted=1 conflicts=0\n"
    assert err == ""
    for forbidden in (
        "synthetic-home-1",
        "secret-home-calendar-token",
        "Home synthetic",
    ):
        assert forbidden not in out


def test_cli_label_rejected_for_other_collectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    with pytest.raises(SystemExit) as excinfo:
        main(
            ["run", "github", "--label", "home"],
            http_get=github_http_get,
            db_path=tmp_path / "y.db",
        )
    assert excinfo.value.code == 2


def test_cli_unknown_name_is_argparse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(
            ["run", "frobnicator"],
            http_get=github_http_get,
            db_path=tmp_path / "x.db",
        )
    assert excinfo.value.code == 2
    out, _ = capsys.readouterr()
    assert "inserted=" not in out


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_RECENT_URL = "https://api.spotify.com/v1/me/player/recently-played?limit=50"
AW_BUCKETS_URL = "http://127.0.0.1:5600/api/0/buckets/"
AW_WINDOW = "2026-10-28T12:00:00+00:00"
AW_END = "2026-10-30T12:00:00+00:00"
AW_NOW = datetime.fromisoformat("2026-10-30T12:30:00+00:00")
PUSH_INGEST_URL = "https://example.invalid/ingest"
PUSH_INGEST_TOKEN = "synthetic-ingest-token"


def spotify_token_post(url: str, headers: dict[str, str], body: bytes):
    from framework.collectors.common import HttpResponse

    assert url == SPOTIFY_TOKEN_URL
    return HttpResponse(
        status=200,
        headers={},
        body=json.dumps(
            {
                "access_token": "synthetic-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        ).encode(),
    )


def spotify_recent_get(url: str, headers: dict[str, str]):
    from framework.collectors.common import HttpResponse

    assert url == SPOTIFY_RECENT_URL
    assert headers.get("Authorization") == "Bearer synthetic-access-token"
    return HttpResponse(
        status=200,
        headers={},
        body=json.dumps(
            {
                "items": [
                    {
                        "track": {
                            "id": "synthetic-track-1",
                            "name": "Synthetic Track One",
                            "artists": [{"name": "Synthetic Artist"}],
                        },
                        "played_at": "2026-10-30T10:00:00Z",
                    }
                ]
            }
        ).encode(),
    )


def test_build_collector_spotify_and_no_run_activitywatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = build_collector("spotify", spotify_recent_get, spotify_token_post)
    assert collector.name == "spotify"
    with pytest.raises(ValueError, match="unknown collector"):
        build_collector("activitywatch", spotify_recent_get)


def test_cli_run_spotify_prints_only_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "synthetic-refresh-token")
    code = main(
        ["run", "spotify"],
        http_get=spotify_recent_get,
        http_post=spotify_token_post,
        now_fn=lambda: NOW,
        db_path=tmp_path / "spotify-cli.db",
    )
    assert code == 0
    out, err = capsys.readouterr()
    assert out == "inserted=1 conflicts=0\n"
    assert err == ""
    for forbidden in (
        "Synthetic Track One",
        "Synthetic Artist",
        "synthetic-client-secret",
        "synthetic-refresh-token",
        "synthetic-access-token",
    ):
        assert forbidden not in out
        assert forbidden not in err


def test_cli_run_activitywatch_is_argparse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "activitywatch"], db_path=tmp_path / "x.db")
    assert excinfo.value.code == 2


def aw_cli_get(url: str, headers: dict[str, str]):
    from framework.collectors.common import HttpResponse

    if url == AW_BUCKETS_URL:
        return HttpResponse(
            status=200,
            headers={},
            body=json.dumps(
                {
                    "aw-watcher-window-synthetic": {},
                    "aw-watcher-afk-synthetic": {},
                }
            ).encode(),
        )
    assert url.startswith("http://127.0.0.1:5600/api/0/buckets/")
    return HttpResponse(
        status=200,
        headers={},
        body=json.dumps(
            [
                {
                    "timestamp": "2026-10-30T11:00:00+00:00",
                    "duration": 3600.0,
                    "data": (
                        {"status": "not-afk"}
                        if "afk" in url
                        else {
                            "app": "Code",
                            "title": "Synthetic secret window title",
                            "url": "https://example.invalid/secret-page",
                        }
                    ),
                }
            ]
        ).encode(),
    )


def test_cli_push_activitywatch_prints_counts_and_opens_no_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.collectors.common import HttpResponse

    monkeypatch.setenv("INGEST_URL", PUSH_INGEST_URL)
    monkeypatch.setenv("INGEST_TOKEN", PUSH_INGEST_TOKEN)
    seen: list[tuple[str, dict[str, str], bytes]] = []

    def fake_ingest_post(
        url: str, headers: dict[str, str], body: bytes
    ) -> HttpResponse:
        seen.append((url, headers, body))
        assert url == f"{PUSH_INGEST_URL}/events/screen-hour"
        assert headers["Authorization"] == f"Bearer {PUSH_INGEST_TOKEN}"
        return HttpResponse(
            status=201,
            headers={},
            body=json.dumps({"inserted": 1, "total": 1}).encode(),
        )

    db_path = tmp_path / "should-not-exist.db"
    code = main(
        ["push", "activitywatch"],
        http_get=aw_cli_get,
        http_post=fake_ingest_post,
        now_fn=lambda: AW_NOW,
        db_path=db_path,
    )
    assert code == 0
    out, err = capsys.readouterr()
    assert out == "inserted=1 conflicts=0\n"
    assert err == ""
    assert not db_path.exists()
    assert "Synthetic secret window title" not in out
    assert "example.invalid/secret-page" not in seen[0][2].decode()


def test_cli_push_activitywatch_missing_env_reports_variable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("INGEST_URL", raising=False)
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    code = main(
        ["push", "activitywatch"],
        http_get=aw_cli_get,
        db_path=tmp_path / "y.db",
    )
    assert code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "error: activitywatch: INGEST_URL is not set\n"


def test_cli_ingest_health_happy_and_repost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "date": "2026-10-29",
        "sleep_h": 7.25,
        "steps": 8234,
        "daylight_min": 95.0,
    }
    payload_path = tmp_path / "shortcut.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "health-cli.db"
    code = main(
        ["ingest-health", str(payload_path)],
        now_fn=lambda: NOW,
        db_path=db_path,
    )
    assert code == 0
    out, err = capsys.readouterr()
    assert out == "inserted=1 conflicts=0\n"
    assert err == ""
    code = main(
        ["ingest-health", str(payload_path)],
        now_fn=lambda: NOW,
        db_path=db_path,
    )
    assert code == 0
    out, _ = capsys.readouterr()
    assert out == "inserted=0 conflicts=0\n"
    assert "8234" not in out


def test_cli_ingest_health_error_reports_only_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text('{"sleep_h": 7.0}', encoding="utf-8")
    code = main(["ingest-health", str(bad_path)], db_path=tmp_path / "e.db")
    assert code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "7.0" not in err


def test_cli_serve_ingest_without_token_refuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    code = main(
        ["serve-ingest", "--host", "127.0.0.1", "--port", "18099"],
        db_path=tmp_path / "s.db",
    )
    assert code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "error: ingest: INGEST_TOKEN is not set\n"


def test_cli_serve_health_is_argparse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["serve-health"], db_path=tmp_path / "x.db")
    assert excinfo.value.code == 2
