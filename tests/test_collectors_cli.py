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
