"""Ticket 11: the proposal core.

Pure except for the injected client: given eligible commitments, a gate
context, and a client, it runs one guarded Wonder call per profile, gates
the narrow draft, retries once with the violations fed back, and otherwise
returns a labelled fallback or a noop.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from framework.briefing.context import GateContext, TimeInterval
from framework.briefing.gate import (
    action_targets_repo,
    evaluate_briefing,
    slot_window_codes,
)
from framework.briefing.schemas import Briefing, Commitment
from framework.proposal.assembly import assemble_briefing
from framework.proposal.hour import fallback_window_codes
from framework.proposal.prompt import (
    Delta,
    build_prompt,
    compute_deltas,
    offered_metrics,
)
from framework.proposal.schemas import (
    FallbackProposal,
    ProposalDraft,
    UnparseableDraft,
    build_response_schema,
    parse_draft,
)
from framework.verify import RepairResult, repair_loop

_CLAIM_ID_LINE = (
    "Claim ids in this feedback number each section's claims from 1 in the "
    "order the model wrote them, so c-working-2 is its second working claim; "
    "return a complete new draft."
)

_EARLIEST = datetime(1, 1, 1, tzinfo=UTC)

_UNPARSEABLE_MESSAGE = "draft could not be parsed"
_TRUNCATED_MESSAGE = "draft was truncated"
_VALIDATION_ERROR_MESSAGE = "draft validation failed"
_SINCE_LAST_MESSAGE = "since_last cites no offered delta"
_TOO_LONG_MESSAGE = "write one sentence of at most 20 words"
_NOT_PLAIN_MESSAGE = "write plain sentences with no links or markup"

_NOT_PLAIN_RE = re.compile(r"https?://|www\.|\]\(|</?[A-Za-z]|[\r\n]")


class MetaUnavailableError(Exception):
    """Timeout, transport, or non-2xx failure; the message is a closed reason."""

    def __init__(self, message: str = "", *, latency_ms: int = 0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


class OutboundBlocked(Exception):
    """The outbound text failed the pre-send scan; carries codes only."""

    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__("outbound text blocked")
        self.codes = codes


class ContributorModelRefused(Exception):
    """A contributor model id was refused; the message names only the rule."""


class WonderClient(Protocol):
    @property
    def transport(self) -> str: ...
    @property
    def transport_version(self) -> str | None: ...
    @property
    def harness_rules_file(self) -> bool | None: ...
    def complete(self, request: WonderRequest) -> WonderResponse: ...


@dataclass(frozen=True)
class WonderRequest:
    prompt: str
    model: str
    effort: str
    response_schema: dict[str, Any]
    schema_name: str = "proposal_draft"
    forbidden_raw_literals: tuple[str, ...] = ()


@dataclass(frozen=True)
class WonderResponse:
    text: str
    model_reported: str
    latency_ms: int
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    cached_tokens: int | None = None


@dataclass(frozen=True)
class ModelParams:
    first_model: str
    first_effort: str
    retry_model: str
    retry_effort: str


@dataclass(frozen=True)
class AttemptOutcome:
    number: int
    model_requested: str
    model_reported: str
    effort: str
    prompt_hash: str
    raw_text: str
    parsed_ok: bool
    blocked: bool
    codes: tuple[tuple[str, str], ...]
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    finish_reason: str | None
    cached_tokens: int | None = None
    transport: str = "unknown"
    transport_version: str | None = None
    harness_rules_file: bool | None = None


@dataclass(frozen=True)
class ProposalResult:
    kind: Literal["proposal", "fallback", "noop"]
    profile_id: str
    subject_id: str
    cycle_id: str
    run: int
    slot: datetime
    hour: TimeInterval | None
    briefing: Briefing | None
    fallback: FallbackProposal | None
    reason_codes: tuple[str, ...]
    attempts: tuple[AttemptOutcome, ...]
    cycle_age_s: float
    prompt_hash: str


@dataclass
class _Generation:
    outbound: str
    model: str
    effort: str
    response: WonderResponse | None
    raised: Exception | None
    draft: ProposalDraft | UnparseableDraft | None
    findings: tuple[tuple[str, str, str], ...] | None = None


@dataclass(frozen=True)
class _Validation:
    passed: bool
    findings: tuple[tuple[str, str, str], ...]
    briefing: Briefing | None

    def feedback(self) -> str:
        lines = [
            f"{code} @ {location}: {message}"
            for code, location, message in self.findings
        ]
        return "\n".join([*lines, _CLAIM_ID_LINE])


def _prompt_hash(outbound: str) -> str:
    return hashlib.sha256(outbound.encode()).hexdigest()


def _with_stale(
    reasons: tuple[str, ...], extra: tuple[str, ...], *, stale: bool
) -> tuple[str, ...]:
    """Reasons plus extras plus CYCLE_STALE when stale, de-duplicated in order."""
    ordered = (*reasons, *extra)
    if stale:
        ordered = (*ordered, "CYCLE_STALE")
    return tuple(dict.fromkeys(ordered))


def propose(
    *,
    profile_id: str,
    subject_id: str,
    slot: datetime,
    as_of: datetime,
    cycle_id: str,
    run: int,
    hour: TimeInterval | None,
    eligible: Sequence[Commitment],
    context: GateContext,
    client: WonderClient,
    models: ModelParams,
    policy: str = "",
    stale_after_s: float,
    cycle_as_of: datetime,
    offered: Mapping[str, datetime],
) -> ProposalResult:
    """Run the guarded proposal step for one profile at one slot."""
    cycle_age_s = (as_of - cycle_as_of).total_seconds()

    def _finish_noop(
        reasons: tuple[str, ...],
        attempts: tuple[AttemptOutcome, ...],
        extra: tuple[str, ...] = (),
    ) -> ProposalResult:
        prompt_hash = attempts[0].prompt_hash if attempts else ""
        aged = _with_stale(reasons, extra, stale=cycle_age_s > stale_after_s)
        return ProposalResult(
            kind="noop",
            profile_id=profile_id,
            subject_id=subject_id,
            cycle_id=cycle_id,
            run=run,
            slot=slot,
            hour=hour,
            briefing=None,
            fallback=None,
            reason_codes=aged,
            attempts=attempts,
            cycle_age_s=cycle_age_s,
            prompt_hash=prompt_hash,
        )

    if slot_window_codes(slot, context.limits):
        return _finish_noop(("NOOP_SLOT_OUTSIDE_ALLOWED_HOURS",), ())
    if hour is None:
        return _finish_noop(("NOOP_NO_FREE_HOUR",), ())
    if not eligible:
        return _finish_noop(("NOOP_NO_ELIGIBLE_COMMITMENT",), ())

    metrics_map = offered_metrics(dict(context.metrics.values))
    has_facts = bool(context.facts)
    has_metrics = bool(metrics_map)

    parent_values = (
        dict(context.parent_metrics.values)
        if context.parent_metrics is not None
        else None
    )
    offered_deltas: tuple[Delta, ...] = ()
    parent_for_run = context.parent_briefing
    parent_extra: tuple[str, ...] = ()
    if parent_for_run is not None and parent_values is not None:
        offered_deltas = compute_deltas(metrics_map, parent_values)
        if not offered_deltas:
            parent_for_run = None
            parent_values = None
            parent_extra = ("PARENT_WITHOUT_DELTAS",)
    has_parent = parent_for_run is not None
    delta_values = {delta.metric_id: delta.value for delta in offered_deltas}

    prompt = build_prompt(
        profile_id=profile_id,
        profile_name=profile_id.capitalize(),
        facts=list(context.facts.values()),
        metrics=metrics_map,
        deltas=offered_deltas,
        commitments=list(eligible),
        hour=hour,
        policy=policy,
    )
    schema = build_response_schema(
        commitment_ids=[commitment.id for commitment in eligible],
        fact_ids=list(context.facts),
        snapshot_metric_ids=list(metrics_map),
        delta_metric_ids=list(delta_values),
        has_facts=has_facts,
        has_metrics=has_metrics,
        has_parent=has_parent,
    )

    for commitment in eligible:
        if action_targets_repo(commitment.title):
            blocked = AttemptOutcome(
                number=1,
                model_requested=models.first_model,
                model_reported="unreported",
                effort=models.first_effort,
                prompt_hash=_prompt_hash(prompt),
                raw_text="",
                parsed_ok=False,
                blocked=True,
                codes=(("L1_ACTION_TARGETS_REPO", "prompt"),),
                latency_ms=0,
                prompt_tokens=None,
                completion_tokens=None,
                reasoning_tokens=None,
                finish_reason=None,
                cached_tokens=None,
                transport=client.transport,
                transport_version=client.transport_version,
                harness_rules_file=client.harness_rules_file,
            )
            return _finish_noop(("NOOP_OUTBOUND_BLOCKED",), (blocked,), parent_extra)

    if not has_facts and not has_metrics:
        return _finish_fallback(
            ("FALLBACK_NO_EVIDENCE",),
            (),
            profile_id=profile_id,
            subject_id=subject_id,
            cycle_id=cycle_id,
            run=run,
            slot=slot,
            hour=hour,
            eligible=eligible,
            offered=offered,
            context=context,
            cycle_age_s=cycle_age_s,
            stale_after_s=stale_after_s,
            extra=parent_extra,
        )

    by_id = {commitment.id: commitment for commitment in eligible}
    snapshot_values = dict(context.metrics.values)
    if parent_for_run is None and context.parent_briefing is not None:
        gate_context = context.model_copy(
            update={"parent_briefing": None, "parent_metrics": None}
        )
    else:
        gate_context = context
    records: list[_Generation] = []

    def generate(feedback: str | None) -> ProposalDraft | UnparseableDraft:
        if feedback is None:
            outbound = prompt
            model, effort = models.first_model, models.first_effort
        else:
            outbound = prompt + "\n\nPREVIOUS ATTEMPT FAILED\n" + feedback
            model, effort = models.retry_model, models.retry_effort
        request = WonderRequest(
            prompt=outbound,
            model=model,
            effort=effort,
            response_schema=schema,
            forbidden_raw_literals=context.forbidden_raw_literals,
        )
        try:
            response = client.complete(request)
        except Exception as exc:
            records.append(
                _Generation(
                    outbound=outbound,
                    model=model,
                    effort=effort,
                    response=None,
                    raised=exc,
                    draft=None,
                )
            )
            raise
        draft = parse_draft(
            response.text,
            has_facts=has_facts,
            has_metrics=has_metrics,
            has_parent=has_parent,
        )
        records.append(
            _Generation(
                outbound=outbound,
                model=model,
                effort=effort,
                response=response,
                raised=None,
                draft=draft,
            )
        )
        return draft

    def validate(draft: ProposalDraft | UnparseableDraft) -> _Validation:
        record = records[-1]
        assert record.response is not None
        if isinstance(draft, UnparseableDraft):
            if record.response.finish_reason == "length":
                codes = (("DRAFT_TRUNCATED", "draft", _TRUNCATED_MESSAGE),)
            else:
                codes = (("DRAFT_UNPARSEABLE", "draft", _UNPARSEABLE_MESSAGE),)
            result = _Validation(passed=False, findings=codes, briefing=None)
            record.findings = result.findings
            return result
        try:
            briefing = assemble_briefing(
                draft,
                profile_id=profile_id,
                subject_id=subject_id,
                slot=slot,
                parent=parent_for_run,
                commitments_by_id=by_id,
                snapshot=snapshot_values,
                parent_snapshot=parent_values,
                deltas=delta_values,
                hour=hour,
            )
            violations = evaluate_briefing(briefing, gate_context).violations
            findings = [
                (violation.code, violation.location, violation.message)
                for violation in violations
            ]
            for section in briefing.sections:
                for claim in section.claims:
                    location = f"sections[{section.type}].claims[{claim.id}]"
                    if len(claim.text.split()) > 40 or len(claim.text) > 320:
                        findings.append(
                            ("PROPOSAL_CLAIM_TOO_LONG", location, _TOO_LONG_MESSAGE)
                        )
                    if _NOT_PLAIN_RE.search(claim.text):
                        findings.append(
                            ("PROPOSAL_CLAIM_NOT_PLAIN", location, _NOT_PLAIN_MESSAGE)
                        )
            if has_parent:
                offered_ids = set(delta_values)
                since_last = next(
                    (
                        section
                        for section in briefing.sections
                        if section.type == "since_last"
                    ),
                    None,
                )
                cited: set[str] = set()
                if since_last is not None:
                    cited = {
                        ref.metric_id
                        for claim in since_last.claims
                        for ref in claim.metric_refs
                    }
                if not (cited & offered_ids):
                    findings.append(
                        (
                            "PROPOSAL_SINCE_LAST_DELTA_MISSING",
                            "sections[since_last]",
                            _SINCE_LAST_MESSAGE,
                        )
                    )
        except Exception:  # noqa: BLE001 -- a broken draft is a failed attempt
            result = _Validation(
                passed=False,
                findings=(
                    ("DRAFT_VALIDATION_ERROR", "draft", _VALIDATION_ERROR_MESSAGE),
                ),
                briefing=None,
            )
            record.findings = result.findings
            return result
        result = _Validation(
            passed=not findings, findings=tuple(findings), briefing=briefing
        )
        record.findings = result.findings
        return result

    def _validated_attempt(number: int, record: _Generation) -> AttemptOutcome:
        assert record.response is not None
        codes = tuple((code, location) for code, location, _ in (record.findings or ()))
        return AttemptOutcome(
            number=number,
            model_requested=record.model,
            model_reported=record.response.model_reported,
            effort=record.effort,
            prompt_hash=_prompt_hash(record.outbound),
            raw_text=record.response.text,
            parsed_ok=not isinstance(record.draft, UnparseableDraft),
            blocked=False,
            codes=codes,
            latency_ms=record.response.latency_ms,
            prompt_tokens=record.response.prompt_tokens,
            completion_tokens=record.response.completion_tokens,
            reasoning_tokens=record.response.reasoning_tokens,
            finish_reason=record.response.finish_reason,
            cached_tokens=record.response.cached_tokens,
            transport=client.transport,
            transport_version=client.transport_version,
            harness_rules_file=client.harness_rules_file,
        )

    try:
        loop_result: RepairResult = repair_loop(generate, validate, max_retries=1)
    except OutboundBlocked as exc:
        record = records[-1]
        earlier = tuple(
            _validated_attempt(index + 1, prior)
            for index, prior in enumerate(records[:-1])
        )
        blocked_attempt = AttemptOutcome(
            number=len(records),
            model_requested=record.model,
            model_reported="unreported",
            effort=record.effort,
            prompt_hash=_prompt_hash(record.outbound),
            raw_text="",
            parsed_ok=False,
            blocked=True,
            codes=tuple((code, "prompt") for code in exc.codes),
            latency_ms=0,
            prompt_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
            finish_reason=None,
            cached_tokens=None,
            transport=client.transport,
            transport_version=client.transport_version,
            harness_rules_file=client.harness_rules_file,
        )
        return _finish_noop(
            ("NOOP_OUTBOUND_BLOCKED",), (*earlier, blocked_attempt), parent_extra
        )
    except MetaUnavailableError as exc:
        record = records[-1]
        reason = str(exc) or "unknown"
        earlier = tuple(
            _validated_attempt(index + 1, prior)
            for index, prior in enumerate(records[:-1])
        )
        unavailable = AttemptOutcome(
            number=len(records),
            model_requested=record.model,
            model_reported="unreported",
            effort=record.effort,
            prompt_hash=_prompt_hash(record.outbound),
            raw_text="",
            parsed_ok=False,
            blocked=False,
            codes=(("MODEL_UNAVAILABLE", reason),),
            latency_ms=exc.latency_ms,
            prompt_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
            finish_reason=None,
            cached_tokens=None,
            transport=client.transport,
            transport_version=client.transport_version,
            harness_rules_file=client.harness_rules_file,
        )
        return _finish_fallback(
            ("FALLBACK_MODEL_UNAVAILABLE",),
            (*earlier, unavailable),
            profile_id=profile_id,
            subject_id=subject_id,
            cycle_id=cycle_id,
            run=run,
            slot=slot,
            hour=hour,
            eligible=eligible,
            offered=offered,
            context=context,
            cycle_age_s=cycle_age_s,
            stale_after_s=stale_after_s,
            extra=parent_extra,
        )

    outcomes: list[AttemptOutcome] = []
    for index, attempt in enumerate(loop_result.attempts):
        record = records[index]
        assert record.response is not None
        report = attempt.report
        if isinstance(report, _Validation):
            codes = tuple((code, location) for code, location, _ in report.findings)
        else:
            codes = (("DRAFT_VALIDATION_ERROR", "draft"),)
        outcomes.append(
            AttemptOutcome(
                number=index + 1,
                model_requested=record.model,
                model_reported=record.response.model_reported,
                effort=record.effort,
                prompt_hash=_prompt_hash(record.outbound),
                raw_text=record.response.text,
                parsed_ok=not isinstance(record.draft, UnparseableDraft),
                blocked=False,
                codes=codes,
                latency_ms=record.response.latency_ms,
                prompt_tokens=record.response.prompt_tokens,
                completion_tokens=record.response.completion_tokens,
                reasoning_tokens=record.response.reasoning_tokens,
                finish_reason=record.response.finish_reason,
                cached_tokens=record.response.cached_tokens,
                transport=client.transport,
                transport_version=client.transport_version,
                harness_rules_file=client.harness_rules_file,
            )
        )
    aged = _with_stale((), parent_extra, stale=cycle_age_s > stale_after_s)
    final = loop_result.report
    if isinstance(final, _Validation) and final.passed:
        assert final.briefing is not None
        return ProposalResult(
            kind="proposal",
            profile_id=profile_id,
            subject_id=subject_id,
            cycle_id=cycle_id,
            run=run,
            slot=slot,
            hour=hour,
            briefing=final.briefing,
            fallback=None,
            reason_codes=aged,
            attempts=tuple(outcomes),
            cycle_age_s=cycle_age_s,
            prompt_hash=outcomes[0].prompt_hash if outcomes else "",
        )
    last_codes = [code for code, _ in outcomes[-1].codes]
    if not outcomes[-1].parsed_ok:
        fallback_reasons = ("FALLBACK_UNPARSEABLE",)
    else:
        fallback_reasons = (
            "FALLBACK_AFTER_GATE_FAILURE",
            *sorted(set(last_codes)),
        )
    return _finish_fallback(
        fallback_reasons,
        tuple(outcomes),
        profile_id=profile_id,
        subject_id=subject_id,
        cycle_id=cycle_id,
        run=run,
        slot=slot,
        hour=hour,
        eligible=eligible,
        offered=offered,
        context=context,
        cycle_age_s=cycle_age_s,
        stale_after_s=stale_after_s,
        extra=parent_extra,
    )


def _finish_fallback(
    reasons: tuple[str, ...],
    attempts: tuple[AttemptOutcome, ...],
    *,
    profile_id: str,
    subject_id: str,
    cycle_id: str,
    run: int,
    slot: datetime,
    hour: TimeInterval | None,
    eligible: Sequence[Commitment],
    offered: Mapping[str, datetime],
    context: GateContext,
    cycle_age_s: float,
    stale_after_s: float,
    extra: tuple[str, ...],
) -> ProposalResult:
    assert hour is not None
    choice = min(
        eligible,
        key=lambda commitment: (
            offered.get(commitment.id) is not None,
            offered.get(commitment.id) or _EARLIEST,
            commitment.id,
        ),
    )
    window_codes = fallback_window_codes(
        slot=slot,
        start=hour.start,
        end=hour.end,
        limits=context.limits,
        busy_intervals=context.busy_intervals,
    )
    prompt_hash = attempts[0].prompt_hash if attempts else ""
    stale = cycle_age_s > stale_after_s
    aged = _with_stale(reasons, extra, stale=stale)
    if window_codes:
        return ProposalResult(
            kind="noop",
            profile_id=profile_id,
            subject_id=subject_id,
            cycle_id=cycle_id,
            run=run,
            slot=slot,
            hour=hour,
            briefing=None,
            fallback=None,
            reason_codes=_with_stale(
                ("NOOP_FALLBACK_WINDOW", *sorted(set(window_codes))),
                extra,
                stale=stale,
            ),
            attempts=attempts,
            cycle_age_s=cycle_age_s,
            prompt_hash=prompt_hash,
        )
    return ProposalResult(
        kind="fallback",
        profile_id=profile_id,
        subject_id=subject_id,
        cycle_id=cycle_id,
        run=run,
        slot=slot,
        hour=hour,
        briefing=None,
        fallback=FallbackProposal(
            kind="fallback",
            profile_id=profile_id,
            subject_id=subject_id,
            slot=slot,
            commitment=choice,
            proposed_start=hour.start,
            proposed_end=hour.end,
            reason_codes=reasons,
        ),
        reason_codes=aged,
        attempts=attempts,
        cycle_age_s=cycle_age_s,
        prompt_hash=prompt_hash,
    )
