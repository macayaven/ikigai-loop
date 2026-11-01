"""Ticket 9: ``python -m framework.cycle facts`` CLI (counts/codes only)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from framework.briefing import load_commitments
from framework.briefing.context import ProfileLimits, load_private_terms
from framework.collectors.common import event_id
from framework.cycle import (
    UnknownCycleError,
    forbidden_literals_for,
    run_cycle,
    run_proposals,
)
from framework.cycle.labels import CALENDAR_TYPES, STORED_LABEL_TYPES, run_label_sweep
from framework.glimmer.facts import FactResult, LLMClient, LLMResponse
from framework.glimmer.label_step import LabelStepResult, build_label_client
from framework.glimmer.labels import CalendarLabelData, effective_label
from framework.glimmer.llm import OpenAICompatibleClient, load_llm_config
from framework.glimmer.metrics import select_winners
from framework.proposal.client import (
    ContributorModelRefused,
    MetaClient,
    MetaConfigError,
    load_meta_config,
    refuse_contributor_model,
)
from framework.proposal.core import ModelParams, ProposalResult
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
from framework.proposal.muse_client import MuseExecClient, resolve_muse_bin
from framework.schemas.events import Event
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.store.store import EventStore


def _build_llm() -> LLMClient:
    config = load_llm_config()
    return OpenAICompatibleClient(
        base_url=config.base_url, model=config.model, api_key=config.api_key
    )


def _format_pass(
    kept: int, reason: str | None, latency_ms: int, finish: str | None
) -> str:
    return f"{kept}:{reason or '-'}:{latency_ms / 1000:.1f}s:{finish or '-'}"


class _NeverCalledStub:
    """LLM stand-in for code-only cycles; any call is a bug."""

    def complete(self, prompt: str) -> LLMResponse:
        raise AssertionError("model pass skipped: the stub must never be called")


def _format_line(result: FactResult, run: int) -> str:
    personal, feed = result.passes
    codes = ",".join(d.code for d in result.dropped) or "-"
    code = len(result.code_fact_ids)
    return (
        f"cycle={result.cycle_id} run={run} kept={len(result.facts)}"
        f" code={code} model={len(result.facts) - code}"
        f" dropped={len(result.dropped)} noop={result.noop_reason or '-'}"
        f" personal={_format_pass(personal.kept, personal.noop_reason, personal.latency_ms, personal.finish_reason)}"
        f" feed={_format_pass(feed.kept, feed.noop_reason, feed.latency_ms, feed.finish_reason)}"
        f" codes={codes}"
    )


def _format_proposal_line(result: ProposalResult) -> str:
    codes = sorted(
        set(result.reason_codes)
        | {code for attempt in result.attempts for code, _ in attempt.codes}
    )
    seconds = sum(attempt.latency_ms for attempt in result.attempts) / 1000
    tokens = sum(attempt.completion_tokens or 0 for attempt in result.attempts)
    stale = "-" if result.cycle_id == "no-cycle" else str(int(result.cycle_age_s))
    return (
        f"profile={result.profile_id} kind={result.kind}"
        f" attempts={len(result.attempts)} codes={','.join(codes) or '-'}"
        f" seconds={seconds:.1f}s tokens={tokens} stale={stale}"
    )


def _parse_proposal_instant(raw: str) -> datetime | None:
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        return None
    return instant


def parse_proposal_limits(
    *, timezone: str, allowed_start: str, allowed_end: str
) -> ProfileLimits:
    """Parse the clock flags; on any failure raise ValueError naming the flag."""
    try:
        start = datetime.strptime(allowed_start, "%H:%M").time()
    except ValueError:
        raise ValueError("error: --allowed-start must be HH:MM") from None
    try:
        end = datetime.strptime(allowed_end, "%H:%M").time()
    except ValueError:
        raise ValueError("error: --allowed-end must be HH:MM") from None
    if not start < end:
        raise ValueError(
            "error: --allowed-start must be before --allowed-end"
        ) from None
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("error: --timezone must be a valid IANA timezone") from None
    try:
        return ProfileLimits(
            timezone=timezone,
            allowed_start=start,
            allowed_end=end,
            max_actions=3,
        )
    except ValueError:
        raise ValueError("error: --timezone must be a valid IANA timezone") from None


def _run_propose(args: argparse.Namespace) -> int:
    try:
        refuse_contributor_model(args.model)
        refuse_contributor_model(args.retry_model)
    except ContributorModelRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    required = ["HIDDEN_CRITERIA_DIR", "IKIGAI_COMMITMENTS_FILE"]
    if args.transport == "api":
        required = ["META_API_KEY", *required]
    for variable in required:
        if not os.environ.get(variable, ""):
            print(f"error: {variable}", file=sys.stderr)
            return 2
    as_of = _parse_proposal_instant(args.as_of)
    if as_of is None:
        print("error: --as-of must be an ISO-8601 datetime", file=sys.stderr)
        return 2
    slot = _parse_proposal_instant(args.slot)
    if slot is None:
        print("error: --slot must be an ISO-8601 datetime", file=sys.stderr)
        return 2
    subject_id = args.subject_id or os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print("error: IKIGAI_SUBJECT_ID", file=sys.stderr)
        return 2
    try:
        limits = parse_proposal_limits(
            timezone=args.timezone,
            allowed_start=args.allowed_start,
            allowed_end=args.allowed_end,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    api_key = ""
    muse_bin = ""
    if args.transport == "api":
        try:
            api_key = load_meta_config().api_key
        except MetaConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        muse_bin = resolve_muse_bin()
        if not (os.path.isfile(muse_bin) and os.access(muse_bin, os.X_OK)):
            print("error: MUSE_BIN", file=sys.stderr)
            return 2
    try:
        terms = load_private_terms()
        db_path = Path(args.db) if args.db else None
        store = EventStore(db_path=db_path)
        try:
            fact_store = FactStore(db_path=store.db_path)
            try:
                proposal_store = ProposalStore(db_path=store.db_path)
                try:
                    if args.cycle_id is not None and not fact_store.runs(args.cycle_id):
                        print("error: unknown --cycle-id", file=sys.stderr)
                        return 2
                    literals = forbidden_literals_for(store, subject_id, as_of)
                    loaded = load_commitments(
                        os.environ,
                        private_terms=terms.terms,
                        forbidden_raw_literals=literals,
                    )
                    if not loaded.available:
                        print(
                            f"error: commitments unavailable: {loaded.reason}",
                            file=sys.stderr,
                        )
                        return 2
                    eligible_by_profile = {
                        profile_id: tuple(
                            commitment
                            for commitment in loaded.commitments
                            if commitment.profile_id == profile_id
                        )
                        for profile_id in args.profile
                    }
                    if args.transport == "api":
                        client = MetaClient(
                            api_key=api_key,
                            private_terms=terms.terms,
                            private_terms_available=terms.available,
                        )
                    else:
                        client = MuseExecClient(
                            private_terms=terms.terms,
                            private_terms_available=terms.available,
                            muse_bin=muse_bin,
                        )
                    try:
                        results = run_proposals(
                            as_of=as_of,
                            slot=slot,
                            subject_id=subject_id,
                            profiles=tuple(args.profile),
                            store=store,
                            fact_store=fact_store,
                            proposal_store=proposal_store,
                            client=client,
                            private_terms=terms,
                            eligible_by_profile=eligible_by_profile,
                            limits=limits,
                            models=ModelParams(
                                first_model=args.model,
                                first_effort=args.effort,
                                retry_model=args.retry_model,
                                retry_effort=args.retry_effort,
                            ),
                            stale_after_s=float(args.stale_cycle_hours) * 3600.0,
                            cycle_id=args.cycle_id,
                        )
                    except UnknownCycleError:
                        print("error: unknown --cycle-id", file=sys.stderr)
                        return 2
                    for result in results:
                        print(_format_proposal_line(result))
                finally:
                    proposal_store.close()
            finally:
                fact_store.close()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 -- the CLI maps every failure to one line
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


def _merge_results(results: list[LabelStepResult]) -> LabelStepResult:
    errors: dict[str, int] = {}
    merged = LabelStepResult()
    for result in results:
        for name, count in result.errors_by_type.items():
            errors[name] = errors.get(name, 0) + count
        merged = LabelStepResult(
            called=merged.called + result.called,
            valid=merged.valid + result.valid,
            invalid=merged.invalid + result.invalid,
            deduped=merged.deduped + result.deduped,
            conflicts=merged.conflicts + result.conflicts,
            unavailable=merged.unavailable + result.unavailable,
            errors_by_type=errors,
            skipped_hand_tagged=merged.skipped_hand_tagged + result.skipped_hand_tagged,
            skipped_already_labelled=merged.skipped_already_labelled
            + result.skipped_already_labelled,
            skipped_no_title=merged.skipped_no_title + result.skipped_no_title,
            skipped_not_busy=merged.skipped_not_busy + result.skipped_not_busy,
            skipped_cancelled=merged.skipped_cancelled + result.skipped_cancelled,
        )
    return merged


def _format_labels_line(result: LabelStepResult, cover: str) -> str:
    errors = (
        ",".join(
            f"{name}:{result.errors_by_type[name]}"
            for name in sorted(result.errors_by_type)
        )
        or "-"
    )
    return (
        "labels=done"
        f" called={result.called} valid={result.valid} invalid={result.invalid}"
        f" deduped={result.deduped} conflicts={result.conflicts}"
        f" unavailable={result.unavailable} errors={errors}"
        f" skipped_hand={result.skipped_hand_tagged}"
        f" skipped_labelled={result.skipped_already_labelled}"
        f" skipped_no_title={result.skipped_no_title}"
        f" skipped_not_busy={result.skipped_not_busy}"
        f" skipped_cancelled={result.skipped_cancelled}"
        f" cover={cover}"
    )


def _coverage(store: EventStore, subject_id: str, as_of: datetime) -> str:
    """Count winners by label provenance; counts and codes only."""
    window_start = as_of - timedelta(days=2)
    window_end = as_of + timedelta(days=14)
    winners = select_winners(
        store.events_between(subject_id, window_start, window_end, types=CALENDAR_TYPES)
    )
    rows = store.events_between(
        subject_id, window_start, window_end, types=STORED_LABEL_TYPES
    )
    by_target: dict[str, Event] = {}
    for row in rows:
        if isinstance(row.data, CalendarLabelData):
            current = by_target.get(row.data.target_event_id)
            if current is None or row.collected_at > current.collected_at:
                by_target[row.data.target_event_id] = row
    counts = {"hand": 0, "local_model": 0, "none": 0}
    for event in winners:
        target_id = event.id
        if event.type == "calendar.event.cancelled":
            target_id = event_id(
                event.source, event.source_id.removesuffix("#cancelled")
            )
        view = effective_label(event, by_target.get(target_id))
        counts[view.source] += 1
    return f"hand:{counts['hand']}/model:{counts['local_model']}/none:{counts['none']}"


def _run_labels(args: argparse.Namespace) -> int:
    if os.environ.get("IKIGAI_LABEL_CALENDAR_TITLES") != "1":
        print("labels=disabled")
        return 0
    subject_id = os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print(
            "error: set IKIGAI_SUBJECT_ID",
            file=sys.stderr,
        )
        return 2
    db_path = Path(args.db) if args.db else None
    as_of = datetime.now(UTC)
    budget_s = float(args.budget_s)
    try:
        llm = build_label_client(os.environ)
        store = EventStore(db_path=db_path)
        try:
            started = time.monotonic()
            results: list[LabelStepResult] = []
            for label in args.label:
                remaining = budget_s - (time.monotonic() - started)
                results.append(
                    run_label_sweep(
                        store,
                        subject_id,
                        [label],
                        llm,
                        as_of=as_of,
                        budget_s=max(0.0, remaining),
                        monotonic=time.monotonic,
                    )
                )
            cover = _coverage(store, subject_id, as_of)
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 -- the CLI maps every failure to one line
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(_format_labels_line(_merge_results(results), cover))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m framework.cycle")
    sub = parser.add_subparsers(dest="command", required=True)
    facts = sub.add_parser("facts")
    facts.add_argument("--as-of", required=True)
    facts.add_argument("--subject-id", default=None)
    facts.add_argument("--db", default=None)
    facts.add_argument("--no-personal-pass", action="store_true")
    facts.add_argument("--no-feed-pass", action="store_true")
    propose = sub.add_parser("propose")
    propose.add_argument("--as-of", required=True)
    propose.add_argument("--slot", required=True)
    propose.add_argument("--subject-id", default=None)
    propose.add_argument("--db", default=None)
    propose.add_argument("--cycle-id", default=None)
    propose.add_argument("--profile", action="append", default=None)
    propose.add_argument("--model", default=DEFAULT_MODEL)
    propose.add_argument("--effort", default=DEFAULT_EFFORT)
    propose.add_argument("--retry-model", default=DEFAULT_MODEL)
    propose.add_argument("--retry-effort", default=DEFAULT_EFFORT)
    propose.add_argument("--transport", choices=("muse", "api"), default="muse")
    propose.add_argument("--timezone", default="Europe/Madrid")
    propose.add_argument("--allowed-start", default="13:00")
    propose.add_argument("--allowed-end", default="23:30")
    propose.add_argument("--stale-cycle-hours", default="12.0")
    labels = sub.add_parser("labels")
    labels.add_argument("--label", action="append", default=None)
    labels.add_argument("--db", default=None)
    labels.add_argument("--budget-s", type=float, default=240)
    args = parser.parse_args(argv)
    if args.command == "labels":
        if args.label is None:
            args.label = ["personal"]
        return _run_labels(args)
    if args.command == "propose":
        if args.profile is None:
            args.profile = ["builder", "disconnect"]
        if args.effort not in ("minimal", "low", "medium", "high"):
            print("error: --effort must be minimal|low|medium|high", file=sys.stderr)
            return 2
        if args.retry_effort not in ("minimal", "low", "medium", "high"):
            print(
                "error: --retry-effort must be minimal|low|medium|high",
                file=sys.stderr,
            )
            return 2
        try:
            args.stale_cycle_hours = float(args.stale_cycle_hours)
        except (TypeError, ValueError):
            print("error: --stale-cycle-hours must be a number", file=sys.stderr)
            return 2
        return _run_propose(args)
    try:
        as_of = datetime.fromisoformat(args.as_of)
    except ValueError:
        print("error: --as-of must be an ISO-8601 datetime", file=sys.stderr)
        return 2
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        print("error: --as-of must carry a UTC offset", file=sys.stderr)
        return 2
    subject_id = args.subject_id or os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print(
            "error: set --subject-id or IKIGAI_SUBJECT_ID",
            file=sys.stderr,
        )
        return 2
    db_path = Path(args.db) if args.db else None
    skip_personal = bool(args.no_personal_pass)
    skip_feed = bool(args.no_feed_pass)
    if skip_personal and skip_feed:
        llm: LLMClient = _NeverCalledStub()
    else:
        llm = _build_llm()
    try:
        store = EventStore(db_path=db_path)
        try:
            fact_store = FactStore(db_path=store.db_path)
            try:
                result, run = run_cycle(
                    as_of,
                    subject_id,
                    store,
                    fact_store,
                    llm,
                    personal_pass=not skip_personal,
                    feed_pass=not skip_feed,
                )
            finally:
                fact_store.close()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 -- the CLI maps every failure to one line
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(_format_line(result, run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
