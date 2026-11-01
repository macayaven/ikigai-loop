"""Ticket 10: typed commitment registry loading (fail closed).

The real file lives outside the repo; only synthetic fixtures and
``tmp_path`` files are read in tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from framework.briefing.gate import action_targets_repo, text_check_codes
from framework.briefing.schemas import Commitment

_UNSET = "unset"
_UNREADABLE = "unreadable"
_NOT_UTF8 = "not_utf8"
_INVALID_JSON = "invalid_json"
_NOT_A_LIST = "not_a_list"
_EMPTY = "empty"
_INVALID_ITEM = "invalid_item"
_DUPLICATE_ID = "duplicate_id"
_TITLE_FAILED = "title_failed"


@dataclass(frozen=True)
class LoadedCommitments:
    """Loaded commitments plus their availability (fail closed)."""

    commitments: tuple[Commitment, ...]
    available: bool
    reason: str | None


def _failed(reason: str) -> LoadedCommitments:
    return LoadedCommitments((), False, reason)


def load_commitments(
    environ: Mapping[str, str] | None = None,
    *,
    private_terms: tuple[str, ...] = (),
    forbidden_raw_literals: tuple[str, ...] = (),
) -> LoadedCommitments:
    """Load the JSON commitment list named by ``IKIGAI_COMMITMENTS_FILE``.

    Reads the variable at call time only. Any failure returns no
    commitments with ``available`` False and one closed reason value, with
    no exception and no path or file content in any message, output or
    log. The whole file is rejected when any title fails the title
    checks.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    raw_path = env.get("IKIGAI_COMMITMENTS_FILE", "")
    if not raw_path:
        return _failed(_UNSET)
    try:
        data = Path(raw_path).read_bytes()
    except (OSError, ValueError):
        return _failed(_UNREADABLE)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _failed(_NOT_UTF8)
    try:
        parsed: Any = json.loads(text)
    except (ValueError, RecursionError):
        return _failed(_INVALID_JSON)
    if not isinstance(parsed, list):
        return _failed(_NOT_A_LIST)
    items = cast("list[Any]", parsed)
    if not items:
        return _failed(_EMPTY)
    commitments: list[Commitment] = []
    try:
        for item in items:
            commitments.append(Commitment.model_validate(item))
    except (ValidationError, TypeError):
        return _failed(_INVALID_ITEM)
    seen: set[str] = set()
    for commitment in commitments:
        if commitment.id in seen:
            return _failed(_DUPLICATE_ID)
        seen.add(commitment.id)
    for commitment in commitments:
        if text_check_codes(
            commitment.title,
            private_terms=private_terms,
            forbidden_raw_literals=forbidden_raw_literals,
        ):
            return _failed(_TITLE_FAILED)
        if action_targets_repo(commitment.title):
            return _failed(_TITLE_FAILED)
    return LoadedCommitments(tuple(commitments), True, None)
