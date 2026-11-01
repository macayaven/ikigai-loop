"""Ticket 11: live acceptance test (reviewer only, never CI).

Skipped unless ``IKIGAI_PROPOSAL_LIVE=1``. Sets its own synthetic world in
``tmp_path``: synthetic deny terms, the example commitments file, a
synthetic cycle, then one real call per profile to ``muse-wonder-1.0`` at
high through the real ``MuseExecClient`` on my subscription. Needs no key.
Fails on noop, fallback, or an escaping exception, with the codes in the
message.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

MADRID = ZoneInfo("Europe/Madrid")

pytestmark = pytest.mark.skipif(
    os.environ.get("IKIGAI_PROPOSAL_LIVE") != "1",
    reason="live muse run; the reviewer runs it outside the sandbox",
)


def test_live_proposals_both_profiles(tmp_path: Path) -> None:
    from framework.briefing.context import MetricSnapshot, PrivateTerms
    from framework.cycle import run_proposals
    from framework.glimmer.facts import FactResult, PassResult
    from framework.proposal.core import ModelParams
    from framework.proposal.muse_client import MuseExecClient
    from framework.schemas.core import Fact, FactWindow
    from framework.store import EventStore
    from framework.store.fact_store import FactStore
    from framework.store.proposal_store import ProposalStore

    subject_id = "subject-live"
    as_of = datetime(2026, 10, 31, 14, 0, 0, tzinfo=MADRID)
    slot = datetime(2026, 10, 31, 15, 7, 0, tzinfo=MADRID)

    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "deny-terms.txt").write_text("harbor-light\n", encoding="utf-8")
    environ = {
        "HIDDEN_CRITERIA_DIR": str(hidden),
        "IKIGAI_COMMITMENTS_FILE": str(
            Path("profiles/commitments.example.json").resolve()
        ),
    }
    terms = PrivateTerms(terms=("harbor-light",), available=True)

    from framework.briefing import load_commitments

    loaded = load_commitments(environ, private_terms=terms.terms)
    assert loaded.available, loaded.reason
    eligible = {
        profile: tuple(c for c in loaded.commitments if c.profile_id == profile)
        for profile in ("builder", "disconnect")
    }

    db = tmp_path / "live.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        window_start = as_of - timedelta(hours=72)
        facts = (
            Fact(
                id="fact:synthetic-1",
                subject_id=subject_id,
                window=FactWindow(start=window_start, end=as_of),
                statement="Synthetic focus session completed yesterday",
                evidence=["ev-live-1"],
                tier="public",
            ),
            Fact(
                id="fact:synthetic-2",
                subject_id=subject_id,
                window=FactWindow(start=window_start, end=as_of),
                statement="Synthetic walk logged in the evening",
                evidence=["ev-live-2"],
                tier="public",
            ),
        )
        snapshot = MetricSnapshot(
            values={
                "calendar.busy_hours": 2.5,
                "period.earlier.pushes": 1.0,
                "period.prior.pushes": 2.0,
                "period.last.pushes": 3.0,
            }
        )

        def _pass(name):  # type: ignore[no-untyped-def]
            return PassResult(
                name=name,
                attempts=0,
                raw_valid=True,
                model_id="",
                latency_ms=0,
                finish_reason=None,
                completion_tokens=None,
                kept=0,
                noop_reason=None,
            )

        fact_store.record_cycle(
            FactResult(
                facts=facts,
                code_fact_ids=(),
                snapshot=snapshot,
                passes=(_pass("personal"), _pass("feed")),
                responses=(),
                cycle_id="cycle-live",
                subject_id=subject_id,
                as_of=as_of,
                window_start=window_start,
                prompt_hash="live",
                dropped=(),
                is_noop=False,
                noop_reason=None,
            )
        )
        from datetime import time

        from framework.briefing.context import ProfileLimits

        limits = ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start=time(13, 0),
            allowed_end=time(23, 30),
            max_actions=3,
        )
        client = MuseExecClient(
            private_terms=terms.terms,
            private_terms_available=True,
        )
        models = ModelParams(
            first_model="muse-wonder-1.0",
            first_effort="high",
            retry_model="muse-wonder-1.0",
            retry_effort="high",
        )
        results = run_proposals(
            as_of=as_of,
            slot=slot,
            subject_id=subject_id,
            profiles=("builder", "disconnect"),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=terms,
            eligible_by_profile=eligible,
            limits=limits,
            models=models,
            stale_after_s=43200.0,
        )
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()
    for result in results:
        seconds = sum(a.latency_ms for a in result.attempts) / 1000
        tokens = sum(a.completion_tokens or 0 for a in result.attempts)
        codes = sorted(
            set(result.reason_codes)
            | {code for attempt in result.attempts for code, _ in attempt.codes}
        )
        print(
            f"profile={result.profile_id} kind={result.kind} "
            f"attempts={len(result.attempts)} codes={','.join(codes) or '-'} "
            f"seconds={seconds:.1f}s tokens={tokens}"
        )
        assert result.kind == "proposal", json.dumps(
            {"profile": result.profile_id, "codes": codes}
        )
