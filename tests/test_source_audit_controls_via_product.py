"""Source-audit controls through the real pipeline (Ticket E2 plan, controls file)."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from evals.glimmer_cases import SUBJECT_ID, make_event
from framework.briefing.schemas import Briefing, Claim, MetricRef, Section
from framework.cycle import run_cycle
from framework.proposal.core import AttemptOutcome, ProposalResult
from framework.store import EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.telegram.ledger import CardLedger
from framework.telegram.models import Card, Proposal
from source_audit import compare as C

SUBJECT = SUBJECT_ID
USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
AS_OF = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)
SLOT = datetime(2026, 10, 31, 0, 30, tzinfo=UTC)


def _fact_statement(path, cycle_id, run) -> str:
    """Read the recorded code-fact statement back from the store."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT statement FROM facts WHERE cycle_id = ? AND run = ? ORDER BY rowid",
            (cycle_id, run),
        ).fetchall()
    finally:
        conn.close()
    prs_rows = [str(row[0]) for row in rows if str(row[0]).startswith("Pull requests")]
    assert prs_rows, rows
    return prs_rows[0]


class _RaisingLLM:
    def complete(self, prompt):
        raise AssertionError("the model must not be called")


def _pr(eid, number, action, time):
    sid = str(number) if action == "opened" else str(100 + number)
    return make_event(
        eid=eid,
        source="github",
        source_id=sid,
        type="github.pr",
        time=time,
        data={"repo": REPO, "counts": {action: 1}},
        collected_at=AS_OF,
    )


def _snapshot(prs):
    events = []
    for n, created in prs:
        events.append(
            {
                "id": str(n),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created,
                "action": "opened",
                "pr_number": n,
                "push_id": None,
                "head": None,
                "before": None,
            }
        )
        events.append(
            {
                "id": str(100 + n),
                "type": "PullRequestEvent",
                "repo": REPO,
                "actor": USER,
                "created_at": created,
                "action": "merged",
                "pr_number": n,
                "push_id": None,
                "head": None,
                "before": None,
            }
        )
    pulls = [{"number": n, "created_at": created, "author": USER} for n, created in prs]
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": USER,
        "repo": REPO,
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(events),
                "oldest": events[0]["created_at"],
                "newest": events[-1]["created_at"],
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": pulls[0]["created_at"],
                "newest": pulls[-1]["created_at"],
                "stop": "last_page",
            },
            "activity": {
                "rows": 0,
                "oldest": None,
                "newest": None,
                "stop": "last_page",
            },
        },
    }


def _prs():
    return [
        (1, "2026-10-30T01:00:00Z"),
        (2, "2026-10-30T01:10:00Z"),
        (3, "2026-10-30T01:20:00Z"),
        (4, "2026-10-30T01:30:00Z"),
        (5, "2026-10-30T02:00:00Z"),
        (6, "2026-10-30T02:10:00Z"),
        (7, "2026-10-30T02:20:00Z"),
        (8, "2026-10-30T02:30:00Z"),
    ]


def _build(path, extra_events=(), tamper=None, tamper_ref=None):
    prs = _prs()
    store = EventStore(db_path=path)
    try:
        rows = []
        for n, created in prs:
            moment = datetime.fromisoformat(created)
            rows.append(_pr(f"o{n}", n, "opened", moment))
            rows.append(_pr(f"m{n}", n, "merged", moment))
        rows.extend(extra_events)
        store.append_events(rows)
        facts = FactStore(db_path=path)
        try:
            result, run = run_cycle(
                AS_OF,
                SUBJECT,
                store,
                facts,
                _RaisingLLM(),
                personal_pass=False,
                feed_pass=False,
            )
        finally:
            facts.close()
    finally:
        store.close()
    prior = int(dict(result.snapshot.values).get("period.prior.prs", 0))
    last = int(dict(result.snapshot.values).get("period.last.prs", 0))
    direction = "rose" if last > prior else "fell"
    honest = f"Pull requests {direction} from {prior} in prior to {last} in last."
    refs = [
        {"metric_id": "period.prior.prs", "value": prior},
        {"metric_id": "period.last.prs", "value": last},
    ]
    if tamper_ref is not None:
        refs = tamper_ref
    text = honest
    stored_text = _fact_statement(path, result.cycle_id, run)
    card_text = stored_text if tamper is None else tamper
    if callable(card_text):
        card_text = card_text(stored_text)
    briefing = Briefing(
        id="b1",
        profile_id="p1",
        subject_id=SUBJECT,
        slot=SLOT,
        sections=[
            Section(
                type="overall_state",
                claims=[
                    Claim(
                        id="c-overall_state-1",
                        text=text,
                        fact_ids=[],
                        metric_refs=[MetricRef.model_validate(ref) for ref in refs],
                    )
                ],
                actions=[],
            )
        ],
    )
    props = ProposalStore(db_path=path)
    try:
        props.record(
            ProposalResult(
                kind="proposal",
                profile_id="p1",
                subject_id=SUBJECT,
                cycle_id=result.cycle_id,
                run=run,
                slot=SLOT,
                hour=None,
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(
                    AttemptOutcome(
                        number=1,
                        model_requested="m",
                        model_reported="m",
                        effort="low",
                        prompt_hash="h",
                        raw_text="{}",
                        parsed_ok=True,
                        blocked=False,
                        codes=(),
                        latency_ms=1,
                        prompt_tokens=None,
                        completion_tokens=None,
                        reasoning_tokens=None,
                        finish_reason=None,
                    ),
                ),
                cycle_age_s=1.0,
                prompt_hash="h",
            ),
            snapshot=dict(result.snapshot.values),
        )
    finally:
        props.close()
    card = Card(
        slot=SLOT,
        since_line="one line",
        proposals=(
            Proposal(
                letter="A",
                kind="proposal",
                profile="p1",
                title="t",
                start=datetime(2026, 10, 31, 1, tzinfo=UTC),
                end=datetime(2026, 10, 31, 2, tzinfo=UTC),
            ),
        ),
        statements=(str(card_text),),
    )
    ledger = CardLedger(db_path=path)
    ledger.save_card(card, now=datetime(2026, 10, 31, 1, tzinfo=UTC))
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT card_id FROM telegram_cards").fetchone()
    card_id = row[0]
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT,"
        " card_id TEXT, detail TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, letter TEXT, slot TEXT,"
        " subject_id TEXT, as_of TEXT, bucket TEXT, profile_id TEXT,"
        " commitment_id TEXT, kind TEXT, policy_pick TEXT,"
        " policy_alternative TEXT)"
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', ?, NULL)",
        (SLOT.isoformat(), card_id),
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES (?, 'A', ?, ?, ?, 'b', 'p1', 'c',"
        " 'proposal', NULL, NULL)",
        (card_id, SLOT.isoformat(), SUBJECT, AS_OF.isoformat()),
    )
    chart = {"pushes": {"label": "pushes + PRs", "earlier": 2, "prior": 3, "last": 3}}
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES (?, ?, ?)",
        (card_id, card.model_dump_json(), json.dumps(chart)),
    )
    conn.commit()
    conn.close()
    return _snapshot(prs), result.cycle_id, run


def _opened_rule_holders():
    """Scan loaded framework modules for the old opened-PR rule."""
    import sys

    return [
        module
        for name, module in sys.modules.items()
        if (name == "framework" or name.startswith("framework."))
        and hasattr(module, "is_opened_pr")
    ]


def _expected_sentence():
    """Read the 009d code-fact sentence from the redacted session export."""
    text = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "sessions"
        / "009d-pr-count.md"
    ).read_text()
    matches = re.findall(
        r'"(Pull requests (?:rose|fell) from \d+ in (?:earlier|prior|last)'
        r" to \d+ in (?:earlier|prior|last)\.)\"",
        text,
    )
    assert len(matches) == 1, matches
    return matches[0]


def test_clean_scenario_via_product_passes_prs(tmp_path):
    snap, _cycle_id, _run = _build(tmp_path / "c.db")
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["verdicts"]["prs"] == "PASS"
    assert res["exit"] == 0
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res_all = C.run_compare(
            snap, conn, metric="all", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res_all["stages"]["pushes_plus_prs"][1]["status"] == "match"
    assert res_all["stages"]["pushes_plus_prs"][1]["total"] == 8


def test_historical_bug_via_patch_fails_at_16(tmp_path):
    import importlib

    for name in (
        "framework.glimmer.code_facts",
        "framework.glimmer.facts",
        "framework.glimmer.metrics",
    ):
        importlib.import_module(name)
    holders = _opened_rule_holders()
    names = [module.__name__ for module in holders]
    for known in (
        "framework.glimmer.metrics",
        "framework.glimmer.code_facts",
        "framework.glimmer.facts",
    ):
        assert known in names, names
    originals = {m: m.is_opened_pr for m in holders}
    try:
        for module in holders:
            holder = cast(Any, module)
            holder.is_opened_pr = lambda event: event.type == "github.pr"
        snap, bug_cycle_id, bug_run = _build(tmp_path / "c.db")
        stored_text = _fact_statement(tmp_path / "c.db", bug_cycle_id, bug_run)
    finally:
        for module, func in originals.items():
            cast(Any, module).is_opened_pr = func
    assert stored_text == _expected_sentence()
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["verdicts"]["prs"] == "FAIL"
    stages = res["stages"]["prs"]
    assert stages[0]["total"] == 8
    assert res["diagnostics"]["prs"]["counted"] == 8
    assert stages[1]["status"] == "mismatch"
    assert stages[1]["total"] == 16
    assert stages[1]["last"] == 16
    assert stages[2]["status"] == "mismatch"
    assert stages[2]["last"] == 16
    assert stages[3]["status"] == "mismatch"
    assert stages[3]["last"] == 16
    snap, _cycle_id, _run = _build(tmp_path / "twin.db")
    conn = sqlite3.connect(tmp_path / "twin.db")
    try:
        clean = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert clean["verdicts"]["prs"] == "PASS", clean["lines"]
    assert clean["stages"]["prs"][0]["total"] == 8
    assert clean["stages"]["prs"][1]["total"] == 8
    assert clean["stages"]["prs"][2]["last"] == 8
    assert clean["stages"]["prs"][3]["last"] == 8


def test_planted_duplicate_row_via_eventstore_fails_at_9(tmp_path):
    extra = (
        make_event(
            eid="extra1",
            source="github",
            source_id="extra-sid",
            type="github.pr",
            time=datetime(2026, 10, 30, 4, tzinfo=UTC),
            data={"repo": REPO, "counts": {"opened": 1}},
            collected_at=AS_OF,
        ),
    )
    snap, _cycle_id, _run = _build(tmp_path / "c.db", extra_events=extra)
    assert len(_prs()) == 8
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    assert res["verdicts"]["prs"] == "FAIL"
    stages = res["stages"]["prs"]
    assert stages[0]["total"] == 8
    assert stages[1]["total"] == 9
    assert res["diagnostics"]["prs"]["counted"] == 9
    assert res["diagnostics"]["prs"]["not_in_snapshot"] == 1


def test_tampered_card_statement_fails_stage4_only(tmp_path):
    snap, _cycle_id, _run = _build(
        tmp_path / "c.db",
        tamper=lambda s: s.replace("to 8 in last", "to 9 in last"),
    )
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    stages = res["stages"]["prs"]
    assert [s["status"] for s in stages[:3]] == ["match"] * 3
    assert stages[3]["status"] == "mismatch"
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res_all = C.run_compare(
            snap, conn, metric="all", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res_all["stages"]["pushes_plus_prs"][1]["status"] == "match"
    assert res_all["stages"]["pushes_plus_prs"][1]["total"] == 8


def test_tampered_metric_ref_fails_stage4_only(tmp_path):
    snap, _cycle_id, _run = _build(
        tmp_path / "c.db",
        tamper_ref=[
            {"metric_id": "period.prior.prs", "value": 0},
            {"metric_id": "period.last.prs", "value": 5},
        ],
    )
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res = C.run_compare(snap, conn, metric="prs", subject=SUBJECT, card="latest")
    finally:
        conn.close()
    stages = res["stages"]["prs"]
    assert [s["status"] for s in stages[:3]] == ["match"] * 3
    assert stages[3]["status"] == "mismatch"
    conn = sqlite3.connect(tmp_path / "c.db")
    try:
        res_all = C.run_compare(
            snap, conn, metric="all", subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()
    assert res_all["stages"]["pushes_plus_prs"][1]["status"] == "match"
    assert res_all["stages"]["pushes_plus_prs"][1]["total"] == 8
