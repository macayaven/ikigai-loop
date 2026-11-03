"""Ticket 26: the domain pack runner.

Builds the prompt for one window, validates a proposal with the checker
plus one plain commitment rule check, and runs the generate/validate
repair loop once with a retry.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from typing import Any, cast

from framework.domains.csv_adapter import WindowReference
from framework.domains.schema import DomainPack, Rule, WindowMetric
from framework.proposal.core import (
    MetaUnavailableError,
    OutboundBlocked,
    WonderRequest,
    WonderResponse,
)
from framework.verify.core import VerifyInputError
from framework.verify.hardened import check_claims
from framework.verify.repair import FailedValidation

_RULE_WORDS = {
    ">=": "at least",
    ">": "more than",
    "==": "exactly",
    "<=": "at most",
    "<": "fewer than",
}

_DOMAIN_MESSAGES = {
    "DOMAIN_UNPARSEABLE": "proposal is not valid JSON or has the wrong shape",
    "DOMAIN_UNKNOWN_COMMITMENT": "commitment id is not declared in the pack",
    "DOMAIN_COMMITMENT_RULE": "the chosen commitment rule does not hold on the window",
    "DOMAIN_CHECK_INPUT": "the checker input could not be built",
}


def _rule_holds(rule: Rule, metrics: dict[str, int]) -> bool:
    value = metrics[rule.metric]
    if rule.op == ">=":
        return value >= rule.value
    if rule.op == ">":
        return value > rule.value
    if rule.op == "==":
        return value == rule.value
    if rule.op == "<=":
        return value <= rule.value
    return value < rule.value


def expected_commitment(pack: DomainPack, ref: WindowReference) -> str:
    """The id of the one commitment whose rule holds on the window."""
    hits = [item.id for item in pack.commitments if _rule_holds(item.when, ref.metrics)]
    if len(hits) != 1:
        raise ValueError("expected exactly one commitment rule to hold")
    return hits[0]


def _rule_words(rule: Rule) -> str:
    return f"{_RULE_WORDS[rule.op]} {rule.value}"


def _window_definition(metric: WindowMetric) -> str:
    if metric.op == "sum":
        return f"sum of {metric.of} over the window's dates"
    if metric.op == "max":
        return f"largest daily {metric.of}"
    assert metric.above is not None
    return f"number of dates whose {metric.of} is above {metric.above}"


def build_prompt(
    pack: DomainPack, ref: WindowReference, feedback: str | None = None
) -> str:
    """Plain words: the decision, every metric, every fact, the writing rules."""
    window_metrics = {metric.id: metric for metric in pack.window_metrics}
    definitions = {
        metric_id: _window_definition(metric)
        for metric_id, metric in window_metrics.items()
    }
    lines = [
        pack.note,
        f"Goal: {pack.goal.text}",
        "Decision: choose exactly one commitment.",
        "Commitments (choose the one whose rule holds):",
    ]
    for item in pack.commitments:
        lines.append(
            f"- {item.id}: {item.text} "
            f"Choose it when {item.when.metric} is {_rule_words(item.when)}."
        )
    period = pack.window.period_phrase.replace("{start}", ref.window_start)
    lines.append(
        f"Window: {period}, the {len(ref.dates)} dates "
        f"from {ref.dates[0]} to {ref.dates[-1]}."
    )
    lines.append("Metrics, computed from the pinned source files:")
    for metric_id in ref.metrics:
        value = ref.metrics[metric_id]
        labels = " ".join(ref.labels[metric_id])
        detail = f"unit {ref.units[metric_id]}; {ref.periods[metric_id]}"
        if metric_id in definitions:
            detail = f"{detail}; {definitions[metric_id]}"
        lines.append(f"- {metric_id}: {value} [{labels}] ({detail})")
    lines.append("Facts (cite the fact id when a claim is about the fact):")
    for fact_id in pack.facts:
        lines.append(f"- {fact_id}: {pack.facts[fact_id]}")
    lines.extend(
        [
            "Writing rules:",
            "- Choose exactly one commitment whose rule holds on the listed values.",
            "- Write 1 to 3 claims giving the reasons, each one plain sentence of at most 25 words.",
            "- Every number in a sentence is the exact listed value of a metric the claim cites, written in digits.",
            "- A claim that cites a metric writes all its label words and its period phrase as listed.",
            "- Cite one metric per claim, or two metrics from the same daily series when comparing two dates,",
            "  writing each value next to its own date.",
            "- Never write a number that appears only in a metric definition, such as a threshold;",
            "  a claim about a rule cites the matching fact and states no number.",
            "- No other numbers, no other units, no negations.",
        ]
    )
    if feedback is not None:
        lines.append("Previous attempt feedback:")
        lines.append(feedback)
        lines.append("Write a complete new draft.")
    return "\n".join(lines)


def response_schema(pack: DomainPack, ref: WindowReference) -> dict[str, Any]:
    """The JSON schema for a domain proposal draft."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["commitment_id", "claims"],
        "properties": {
            "commitment_id": {
                "type": "string",
                "enum": [item.id for item in pack.commitments],
            },
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "text", "metric_refs", "fact_ids"],
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                        "metric_refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["metric_id", "value"],
                                "properties": {
                                    "metric_id": {
                                        "type": "string",
                                        "enum": sorted(ref.metrics),
                                    },
                                    "value": {"type": "integer"},
                                },
                            },
                        },
                        "fact_ids": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(pack.facts),
                            },
                        },
                    },
                },
            },
        },
    }


@dataclass(frozen=True)
class DomainValidation:
    """The validation verdict for one proposal draft."""

    passed: bool
    codes: tuple[tuple[str, str], ...]
    commitment_id: str | None
    check_complete: bool | None
    messages: tuple[str, ...] = ()

    def feedback(self) -> str:
        """One `CODE claim_id: message` line per finding."""
        return "\n".join(
            f"{code} {claim_id}: {message}"
            for (code, claim_id), message in zip(self.codes, self.messages, strict=True)
        )


def _shape_claims(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    import json as _json

    try:
        parsed: Any = _json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    mapping = cast("dict[str, Any]", parsed)
    if set(mapping.keys()) != {"commitment_id", "claims"}:
        return None
    commitment_id: Any = mapping.get("commitment_id")
    raw_claims: Any = mapping.get("claims")
    if not isinstance(commitment_id, str) or not isinstance(raw_claims, list):
        return None
    claim_items = cast("list[Any]", raw_claims)
    if not 1 <= len(claim_items) <= 3:
        return None
    claims: list[dict[str, Any]] = []
    for raw_claim in claim_items:
        if not isinstance(raw_claim, dict):
            return None
        claim_map = cast("dict[str, Any]", raw_claim)
        if set(claim_map.keys()) != {"id", "text", "metric_refs", "fact_ids"}:
            return None
        claim_id: Any = claim_map.get("id")
        claim_text: Any = claim_map.get("text")
        raw_refs: Any = claim_map.get("metric_refs")
        raw_fact_ids: Any = claim_map.get("fact_ids")
        if not isinstance(claim_id, str) or not isinstance(claim_text, str):
            return None
        if not isinstance(raw_refs, list) or not isinstance(raw_fact_ids, list):
            return None
        fact_items = cast("list[Any]", raw_fact_ids)
        if any(not isinstance(item, str) for item in fact_items):
            return None
        refs: list[dict[str, Any]] = []
        ref_items = cast("list[Any]", raw_refs)
        for raw_ref in ref_items:
            if not isinstance(raw_ref, dict):
                return None
            ref_map = cast("dict[str, Any]", raw_ref)
            if set(ref_map.keys()) != {"metric_id", "value"}:
                return None
            metric_id: Any = ref_map.get("metric_id")
            value: Any = ref_map.get("value")
            if not isinstance(metric_id, str):
                return None
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            refs.append({"metric_id": metric_id, "value": value})
        claims.append(
            {
                "id": claim_id,
                "text": claim_text,
                "metric_refs": refs,
                "fact_ids": fact_items,
            }
        )
    return commitment_id, claims


def validate_proposal(
    pack: DomainPack, ref: WindowReference, text: str
) -> DomainValidation:
    """Validate one proposal draft: shape, commitment, rule, then the checker."""
    shaped = _shape_claims(text)
    if shaped is None:
        message = _DOMAIN_MESSAGES["DOMAIN_UNPARSEABLE"]
        return DomainValidation(
            False, (("DOMAIN_UNPARSEABLE", "-"),), None, None, (message,)
        )
    commitment_id, claims = shaped
    first_claim = str(claims[0]["id"]) if claims else "-"
    codes: list[tuple[str, str]] = []
    messages: list[str] = []
    known = {item.id: item for item in pack.commitments}
    if commitment_id not in known:
        codes.append(("DOMAIN_UNKNOWN_COMMITMENT", first_claim))
        messages.append(_DOMAIN_MESSAGES["DOMAIN_UNKNOWN_COMMITMENT"])
    elif not _rule_holds(known[commitment_id].when, ref.metrics):
        codes.append(("DOMAIN_COMMITMENT_RULE", first_claim))
        messages.append(_DOMAIN_MESSAGES["DOMAIN_COMMITMENT_RULE"])
    try:
        report = check_claims(ref.check_input(claims))
    except VerifyInputError as exc:
        codes.append(("DOMAIN_CHECK_INPUT", first_claim))
        messages.append(f"{_DOMAIN_MESSAGES['DOMAIN_CHECK_INPUT']}: {exc}")
        return DomainValidation(
            False, tuple(codes), commitment_id, None, tuple(messages)
        )
    codes.extend((item.code, item.claim_id) for item in report.violations)
    messages.extend(item.message for item in report.violations)
    return DomainValidation(
        not codes, tuple(codes), commitment_id, report.complete, tuple(messages)
    )


@dataclass(frozen=True)
class AttemptRecord:
    """One proposal attempt and its validation."""

    number: int
    latency_ms: int
    model_reported: str
    prompt_sha256: str
    raw_text: str
    passed: bool
    codes: tuple[tuple[str, str], ...]
    commitment_id: str | None
    commitment_matches_expected: bool | None
    check_complete: bool | None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None

    def to_json(self) -> dict[str, Any]:
        """Plain JSON for the run record."""
        return {
            "number": self.number,
            "latency_ms": self.latency_ms,
            "model_reported": self.model_reported,
            "prompt_sha256": self.prompt_sha256,
            "raw_text": self.raw_text,
            "passed": self.passed,
            "codes": [
                {"code": code, "claim_id": claim_id} for code, claim_id in self.codes
            ],
            "commitment_id": self.commitment_id,
            "commitment_matches_expected": self.commitment_matches_expected,
            "check_complete": self.check_complete,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True)
class WindowRun:
    """The recorded run of one window through the repair loop."""

    pack_id: str
    window_start: str
    model: str
    effort: str
    expected_commitment: str
    attempts: tuple[AttemptRecord, ...]
    first_pass_accepted: bool
    repaired: bool
    final_passed: bool
    transport_error: str | None
    latency_ms_total: int

    def to_json(self) -> dict[str, Any]:
        """Plain JSON for the run record."""
        return {
            "pack_id": self.pack_id,
            "window_start": self.window_start,
            "model": self.model,
            "effort": self.effort,
            "expected_commitment": self.expected_commitment,
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "first_pass_accepted": self.first_pass_accepted,
            "repaired": self.repaired,
            "final_passed": self.final_passed,
            "transport_error": self.transport_error,
            "latency_ms_total": self.latency_ms_total,
        }


def _transport_error(exc: BaseException) -> str:
    name = type(exc).__name__
    detail = str(exc)
    raw_codes: Any = getattr(exc, "codes", None)
    names: list[str] = []
    if isinstance(raw_codes, tuple):
        entries = cast("tuple[Any, ...]", raw_codes)
        for entry in entries:
            if isinstance(entry, str):
                names.append(entry)
    if names:
        suffix = ",".join(names)
        detail = f"{detail} [{suffix}]" if detail else f"[{suffix}]"
    return f"{name}: {detail}" if detail else name


def _error_latency(exc: BaseException) -> int:
    latency = getattr(exc, "latency_ms", 0)
    return latency if isinstance(latency, int) else 0


def _record_attempt(
    number: int,
    prompt: str,
    response: WonderResponse,
    report: DomainValidation | FailedValidation,
    expected: str,
) -> AttemptRecord:
    if isinstance(report, DomainValidation):
        passed = report.passed
        codes = report.codes
        commitment_id = report.commitment_id
        check_complete: bool | None = report.check_complete
    else:
        passed = False
        codes = (("DOMAIN_CHECK_INPUT", "-"),)
        commitment_id = None
        check_complete = None
    return AttemptRecord(
        number=number,
        latency_ms=response.latency_ms,
        model_reported=response.model_reported,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        raw_text=response.text,
        passed=passed,
        codes=codes,
        commitment_id=commitment_id,
        commitment_matches_expected=(commitment_id == expected)
        if commitment_id
        else None,
        check_complete=check_complete,
        finish_reason=response.finish_reason,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        reasoning_tokens=response.reasoning_tokens,
    )


def run_window(
    pack: DomainPack,
    ref: WindowReference,
    client: Any,
    *,
    model: str,
    effort: str,
    max_retries: int = 1,
) -> WindowRun:
    """Run one window: generate, validate, repair once, record everything."""
    expected = expected_commitment(pack, ref)
    base_prompt = build_prompt(pack, ref)
    schema = response_schema(pack, ref)
    prompts: list[str] = []
    finished: list[tuple[WonderResponse, DomainValidation | FailedValidation]] = []
    transport_error: str | None = None
    failed_latency = 0
    feedback: str | None = None
    for _ in range(max(1, 1 + max_retries)):
        prompt = (
            base_prompt
            if feedback is None
            else build_prompt(pack, ref, feedback=feedback)
        )
        prompts.append(prompt)
        request = WonderRequest(
            prompt=prompt,
            model=model,
            effort=effort,
            response_schema=schema,
            schema_name="domain_proposal",
        )
        try:
            response = client.complete(request)
        except (MetaUnavailableError, OutboundBlocked) as exc:
            transport_error = _transport_error(exc)
            failed_latency = _error_latency(exc)
            break
        try:
            report: DomainValidation | FailedValidation = validate_proposal(
                pack, ref, response.text
            )
            ok = bool(report.passed)
        except Exception:  # noqa: BLE001 - any validator failure is a failed attempt
            report = FailedValidation()
            ok = False
        finished.append((response, report))
        if ok:
            break
        feedback = report.feedback()
    attempts = tuple(
        _record_attempt(number, prompts[number - 1], response, report, expected)
        for number, (response, report) in enumerate(finished, start=1)
    )
    first_pass = attempts[0].passed if attempts else False
    final_pass = (attempts[-1].passed if attempts else False) and (
        transport_error is None
    )
    return WindowRun(
        pack_id=pack.pack_id,
        window_start=ref.window_start,
        model=model,
        effort=effort,
        expected_commitment=expected,
        attempts=attempts,
        first_pass_accepted=first_pass,
        repaired=len(attempts) >= 2 and not first_pass and final_pass,
        final_passed=final_pass,
        transport_error=transport_error,
        latency_ms_total=sum(item.latency_ms for item in attempts) + failed_latency,
    )


def git_commit() -> str | None:
    """The current commit hash, or None when git is missing or unusable."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = proc.stdout.strip()
    if proc.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return None
    return commit
