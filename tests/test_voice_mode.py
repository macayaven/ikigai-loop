"""Ticket 14 Step 5: Contributor-mode gate for the voice path (D34).

Synthetic data only. No network, no binary, no settings file outside tmp.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from framework.voice.mode import (
    CONTRIBUTOR_ENV_NOT_ZERO,
    CONTRIBUTOR_SETTING_ON,
    CONTRIBUTOR_SETTING_UNREADABLE,
    contributor_mode_status,
)


def _write_settings(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _env_with(tmp_path: Path, extra: dict[str, str]) -> dict[str, str]:
    base = {
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "HOME": str(tmp_path / "home"),
    }
    base.update(extra)
    return base


def test_confirmed_when_env_zero_and_setting_false(tmp_path: Path) -> None:
    settings = _write_settings(
        tmp_path / "xdg" / "muse" / "settings.json",
        {"contributor_mode_enabled": False},
    )
    env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
    assert contributor_mode_status(env, settings_path=settings) == ()


def test_setting_on_is_refused(tmp_path: Path) -> None:
    settings = _write_settings(
        tmp_path / "xdg" / "muse" / "settings.json",
        {"contributor_mode_enabled": True},
    )
    env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
    assert contributor_mode_status(env, settings_path=settings) == (
        CONTRIBUTOR_SETTING_ON,
    )


def test_xdg_path_used_by_default(tmp_path: Path) -> None:
    _write_settings(
        tmp_path / "xdg" / "muse" / "settings.json",
        {"contributor_mode_enabled": False},
    )
    env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
    assert contributor_mode_status(env) == ()


def test_home_path_used_when_no_xdg(tmp_path: Path) -> None:
    _write_settings(
        tmp_path / "home" / ".config" / "muse" / "settings.json",
        {"contributor_mode_enabled": False},
    )
    env = {"HOME": str(tmp_path / "home"), "MUSE_CONTRIBUTOR_MODE": "0"}
    assert contributor_mode_status(env) == ()


def test_home_setting_on_is_refused(tmp_path: Path) -> None:
    _write_settings(
        tmp_path / "home" / ".config" / "muse" / "settings.json",
        {"contributor_mode_enabled": True},
    )
    env = {"HOME": str(tmp_path / "home"), "MUSE_CONTRIBUTOR_MODE": "0"}
    assert contributor_mode_status(env) == (CONTRIBUTOR_SETTING_ON,)


def test_explicit_settings_path_wins_over_env_paths(tmp_path: Path) -> None:
    _write_settings(
        tmp_path / "xdg" / "muse" / "settings.json",
        {"contributor_mode_enabled": True},
    )
    override = _write_settings(
        tmp_path / "elsewhere.json", {"contributor_mode_enabled": False}
    )
    env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
    assert contributor_mode_status(env, settings_path=override) == ()


def test_env_must_be_exactly_zero(tmp_path: Path) -> None:
    settings = _write_settings(tmp_path / "s.json", {"contributor_mode_enabled": False})
    for bad in ("1", "off", "false", "", "00"):
        env = {"MUSE_CONTRIBUTOR_MODE": bad}
        assert contributor_mode_status(env, settings_path=settings) == (
            CONTRIBUTOR_ENV_NOT_ZERO,
        )


def test_missing_env_is_refused(tmp_path: Path) -> None:
    settings = _write_settings(tmp_path / "s.json", {"contributor_mode_enabled": False})
    assert contributor_mode_status({}, settings_path=settings) == (
        CONTRIBUTOR_ENV_NOT_ZERO,
    )


def test_env_and_setting_codes_combine_in_order(tmp_path: Path) -> None:
    settings = _write_settings(tmp_path / "s.json", {"contributor_mode_enabled": True})
    assert contributor_mode_status({}, settings_path=settings) == (
        CONTRIBUTOR_ENV_NOT_ZERO,
        CONTRIBUTOR_SETTING_ON,
    )


def test_unreadable_when_no_home_or_xdg() -> None:
    assert contributor_mode_status({"MUSE_CONTRIBUTOR_MODE": "0"}) == (
        CONTRIBUTOR_SETTING_UNREADABLE,
    )


def test_unreadable_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "settings.json"
    env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
    assert contributor_mode_status(env, settings_path=missing) == (
        CONTRIBUTOR_SETTING_UNREADABLE,
    )


def test_unreadable_arms(tmp_path: Path) -> None:
    cases = [
        "{not json",
        "[1, 2]",
        '"just a string"',
        "42",
        "null",
        '{"other_key": false}',
        '{"contributor_mode_enabled": "false"}',
        '{"contributor_mode_enabled": 0}',
        '{"contributor_mode_enabled": null}',
        '{"contributor_mode_enabled": 1}',
    ]
    for index, body in enumerate(cases):
        path = tmp_path / f"settings-{index}.json"
        path.write_text(body, encoding="utf-8")
        env = _env_with(tmp_path, {"MUSE_CONTRIBUTOR_MODE": "0"})
        assert contributor_mode_status(env, settings_path=path) == (
            CONTRIBUTOR_SETTING_UNREADABLE,
        ), body


def test_nothing_of_the_file_leaks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    secret_value = "sekret-hobby-phrase-xyz"
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "contributor_mode_enabled": True,
                "other": secret_value,
                "token": "tok-abc-123",
            }
        ),
        encoding="utf-8",
    )
    before = settings.read_bytes()
    with caplog.at_level(logging.DEBUG):
        codes = contributor_mode_status(
            {"MUSE_CONTRIBUTOR_MODE": "0"}, settings_path=settings
        )
    assert codes == (CONTRIBUTOR_SETTING_ON,)
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.records == []  # type: ignore[attr-defined]
    assert secret_value not in str(codes)
    assert "tok-abc-123" not in str(codes)
    assert str(settings) not in str(codes)
    assert settings.read_bytes() == before


def test_unreadable_leaks_nothing(tmp_path: Path, capsys: object) -> None:
    missing = tmp_path / "deep" / "secret-dir" / "settings.json"
    codes = contributor_mode_status(
        {"MUSE_CONTRIBUTOR_MODE": "0"}, settings_path=missing
    )
    assert codes == (CONTRIBUTOR_SETTING_UNREADABLE,)
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    assert captured.err == ""
    assert "secret-dir" not in str(codes)


def test_check_never_writes(tmp_path: Path) -> None:
    settings = _write_settings(tmp_path / "s.json", {"contributor_mode_enabled": False})
    before_stat = settings.stat()
    before = settings.read_bytes()
    contributor_mode_status({"MUSE_CONTRIBUTOR_MODE": "0"}, settings_path=settings)
    contributor_mode_status({"MUSE_CONTRIBUTOR_MODE": "1"}, settings_path=settings)
    assert settings.read_bytes() == before
    assert settings.stat().st_mtime_ns == before_stat.st_mtime_ns
