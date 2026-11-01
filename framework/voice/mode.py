"""Ticket 14: the Contributor-mode gate for the voice path.

A real voice note and its transcript stay out of Contributor mode, whose
terms forbid personal information. The transcription call states no mode,
so the product refuses to transcribe unless this check confirms both the
process variable and the saved setting. Pure apart from reading that one
settings file: it never prints, logs, or stores the file's contents or its
path, and it never writes the file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

CONTRIBUTOR_ENV_NOT_ZERO = "CONTRIBUTOR_ENV_NOT_ZERO"
CONTRIBUTOR_SETTING_ON = "CONTRIBUTOR_SETTING_ON"
CONTRIBUTOR_SETTING_UNREADABLE = "CONTRIBUTOR_SETTING_UNREADABLE"

_SETTINGS_KEY = "contributor_mode_enabled"


def _settings_path_for(environ: Mapping[str, str]) -> Path | None:
    """The binary's own settings path: XDG first, else HOME's default."""
    xdg = environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / "muse" / "settings.json"
    home = environ.get("HOME", "")
    if not home:
        return None
    return Path(home) / ".config" / "muse" / "settings.json"


def contributor_mode_status(
    environ: Mapping[str, str],
    *,
    settings_path: Path | None = None,
) -> tuple[str, ...]:
    """Closed codes; empty means Contributor mode is confirmed off.

    ``CONTRIBUTOR_ENV_NOT_ZERO`` when the variable is not exactly ``"0"``.
    ``CONTRIBUTOR_SETTING_ON`` when the saved key is JSON ``true``.
    ``CONTRIBUTOR_SETTING_UNREADABLE`` when no path resolves, or the file
    is missing, unreadable, not JSON, not an object, lacks the key, or the
    value is not a boolean. Nothing of the file reaches any exception.
    """
    codes: list[str] = []
    if environ.get("MUSE_CONTRIBUTOR_MODE") != "0":
        codes.append(CONTRIBUTOR_ENV_NOT_ZERO)
    path = settings_path if settings_path is not None else _settings_path_for(environ)
    parsed: Any = None
    if path is not None:
        try:
            parsed = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError, RecursionError):
            parsed = None
    loaded: dict[str, Any] | None = (
        cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else None
    )
    value: object = loaded.get(_SETTINGS_KEY) if loaded is not None else None
    if not isinstance(value, bool):
        codes.append(CONTRIBUTOR_SETTING_UNREADABLE)
    elif value:
        codes.append(CONTRIBUTOR_SETTING_ON)
    return tuple(codes)
