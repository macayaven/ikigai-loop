"""Ticket 17a: public claim checker (API, CLI, repair loop, page bundle)."""

from framework.verify.core import (
    LIMITS_NOTE,
    MAX_LABEL_CHECKS,
    ClaimInput,
    MetricRefInput,
    Report,
    VerifyInput,
    VerifyInputError,
    Violation,
    load_input,
    verify_claims,
)
from framework.verify.repair import (
    Attempt,
    FailedValidation,
    RepairResult,
    repair_loop,
    verify_and_repair,
)

__all__ = [
    "LIMITS_NOTE",
    "MAX_LABEL_CHECKS",
    "Attempt",
    "ClaimInput",
    "FailedValidation",
    "MetricRefInput",
    "RepairResult",
    "Report",
    "VerifyInput",
    "VerifyInputError",
    "Violation",
    "load_input",
    "repair_loop",
    "verify_and_repair",
    "verify_claims",
]
