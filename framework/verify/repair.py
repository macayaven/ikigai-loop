"""Ticket 17a: one generic generate/validate repair loop.

Ticket 11 imports this loop with a validator around the full gate; the
wrapper here pins it to ``verify_claims``. No briefing import, no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from framework.verify import core as _core


class Validation(Protocol):
    """What ``repair_loop`` needs from a validator's return value."""

    passed: bool

    def feedback(self) -> str:
        """One-line summary of what failed; empty string when passed."""
        ...  # pragma: no cover


@dataclass(frozen=True)
class FailedValidation:
    """A draft the validator could not parse: a failed attempt, not a crash."""

    passed: bool = False

    def feedback(self) -> str:
        """Fixed string: no exception text, no draft content."""
        return "draft could not be parsed"


@dataclass(frozen=True)
class Attempt:
    """One draft plus its report, in run order."""

    draft: Any
    report: Any


@dataclass(frozen=True)
class RepairResult:
    """The last attempt's pair plus the full attempt history."""

    draft: Any
    report: Any
    attempts: tuple[Attempt, ...]


def repair_loop(generate: Any, validate: Any, *, max_retries: int = 1) -> RepairResult:
    """Run generate/validate up to ``1 + max_retries`` times.

    ``generate`` takes ``None`` first, then each report's ``feedback()``
    text. A validator exception records a failed attempt with the fixed
    feedback string; a generator exception propagates to its caller.
    """
    attempts: list[Attempt] = []
    feedback: str | None = None
    total = max(1, 1 + max_retries)
    for _ in range(total):
        draft = generate(feedback)
        try:
            report = validate(draft)
            ok = bool(report.passed)
        except Exception:  # noqa: BLE001 - any validator failure is a failed attempt
            report = FailedValidation()
            ok = False
        attempts.append(Attempt(draft=draft, report=report))
        if ok:
            break
        feedback = report.feedback()
    last = attempts[-1]
    return RepairResult(draft=last.draft, report=last.report, attempts=tuple(attempts))


def verify_and_repair(
    generate: Any, build_input: Any, *, max_retries: int = 1
) -> RepairResult:
    """Thin wrapper: the validator runs ``verify_claims`` on built input."""

    def _validate(draft: Any) -> Any:
        return _core.verify_claims(build_input(draft))

    return repair_loop(generate, _validate, max_retries=max_retries)
