"""Ticket 15b: pure R4 case building (D37-D40).

Cases derive from already-committed R3 base draws by a traversal fixed
here, before any regeneration exists: per profile, in pair-file order,
the first 5 eligible drafts. The cited fact is the lowest eligible id;
the matched control is the lowest-id fact cited in no claim and whose
family appears in no metric ref. No model, no clock, no filesystem
beyond the rows and pairs doc passed in.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.r3_scenario import apply_ops
from framework.proposal.schemas import ProposalDraft, UnparseableDraft, parse_draft

REPO_ROOT = Path(__file__).resolve().parents[1]
PAIRS_PATH = REPO_ROOT / "evals" / "r3_pairs.json"

PROFILES = ("builder", "disconnect")
CASES_PER_PROFILE = 5
PERIODS = ("earlier", "prior", "last")

# Fact id -> (statement label, metric family). f6 is changeable in
# principle but has no matched control, so it never qualifies a case.
FAMILY_BY_FACT = {
    "f1": ("Pushes", "pushes"),
    "f2": ("Programming screen hours", "screen_hours.Work/Programming"),
    "f3": ("Video screen hours", "screen_hours.Media/Video"),
    "f4": ("Chat screen hours", "screen_hours.Comms/Chat"),
    "f5": ("iki-family calendar hours", "tag_hours.iki-family"),
}
CHANGEABLE = ("f1", "f2", "f3", "f4", "f5")

DISCARD_REASONS = (
    "no_fact_cited",
    "only_feed_fact",
    "unparseable",
    "no_matched_control",
)


@dataclass(frozen=True)
class Case:
    """One R4 case: one shared base draft, two changed facts."""

    case_id: str
    profile: str
    pair_id: str
    repeat: int
    cited_fact: str
    control_fact: str
    base_prompt_hash: str
    base_draft_json: str


def _default_pairs() -> dict[str, Any]:
    return json.loads(PAIRS_PATH.read_text(encoding="utf-8"))


def _num(value: Any) -> str:
    """Render a metric value the way the registered statements do."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_base_draft(raw_text: str) -> ProposalDraft | None:
    """Parse a stored first-attempt draft under the flags propose used."""
    try:
        draft = parse_draft(
            raw_text, has_facts=True, has_metrics=True, has_parent=False
        )
    except Exception:  # noqa: BLE001 -- any parse failure discards the draft
        return None
    if isinstance(draft, UnparseableDraft):
        return None
    return draft


def cited_facts(draft: ProposalDraft) -> list[str]:
    """Sorted union of fact ids over the three parent-free sections."""
    found: set[str] = set()
    for section in (draft.overall_state, draft.working, draft.not_working):
        for claim in section:
            found.update(str(fact_id) for fact_id in claim.fact_ids)
    return sorted(found)


def metric_families(draft: ProposalDraft) -> set[str]:
    """Families appearing in any claim's metric refs, both senses covered."""
    families: set[str] = set()
    for section in (draft.overall_state, draft.working, draft.not_working):
        for claim in section:
            for ref in claim.metric_refs:
                family = family_of_metric_ref(str(ref))
                if family is not None:
                    families.add(family)
    return families


def family_of_metric_ref(ref: str) -> str | None:
    """The family a period metric ref belongs to, else None."""
    for period in PERIODS:
        prefix = f"period.{period}."
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    return None


def select_cited(draft: ProposalDraft) -> str | None:
    """The lowest cited fact id with a changeable family, else None."""
    eligible = [fact for fact in cited_facts(draft) if fact in CHANGEABLE]
    return min(eligible) if eligible else None


def select_control(draft: ProposalDraft) -> str | None:
    """The lowest f1-f5 fact uncited in both senses, else None."""
    cited = set(cited_facts(draft))
    families = metric_families(draft)
    for fact in CHANGEABLE:
        if fact in cited:
            continue
        if FAMILY_BY_FACT[fact][1] in families:
            continue
        return fact
    return None


def changed_statement(label: str, prior: Any) -> str:
    """The registered directional phrasing for a last-period fall to 0."""
    return f"{label} fell from {_num(prior)} in prior to 0 in last."


def changed_ops(fact_id: str, statement: str, family: str) -> list[dict[str, Any]]:
    """The set_fact + set_metric ops changing one fact's last period to 0."""
    return [
        {"op": "set_fact", "id": fact_id, "statement": statement},
        {"op": "set_metric", "id": f"period.last.{family}", "value": 0},
    ]


def changed_scenario(base: dict[str, Any], fact_id: str) -> dict[str, Any]:
    """The base scenario with one fact's last period at 0, ids untouched."""
    label, family = FAMILY_BY_FACT[fact_id]
    prior = base["metrics"][f"period.prior.{family}"]
    return apply_ops(
        base, changed_ops(fact_id, changed_statement(label, prior), family)
    )


def base_scenario(doc: dict[str, Any]) -> dict[str, Any]:
    """The R3 base scenario every case starts from."""
    return {
        "slot": doc["slot"],
        "hour": copy.deepcopy(doc["hour"]),
        "commitments": copy.deepcopy(doc["commitments"]),
        "facts": copy.deepcopy(doc["facts"]),
        "metrics": dict(doc["metrics"]),
    }


def _slot_first_drawn(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The first drawn execution of one slot, in execution order."""
    drawn = [row for row in rows if bool(row.get("drawn", False))]
    if not drawn:
        return None
    return min(drawn, key=lambda row: int(row.get("execution", 0)))


def _walk(
    r3_rows: list[dict[str, Any]], pairs_doc: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Per profile, each base slot in pair-file order with its draft or why not.

    Each entry holds the pair index, pair id, repeat, the parsed draft or
    None, the discard reason or None, and the first drawn row with its raw
    text. Slots with no rows at all are not walked: they were never drawn,
    not discarded. A walked slot with no drawn execution offers no draft
    and counts as unparseable: from this traversal's view there is nothing
    to parse.
    """
    by_slot: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in r3_rows:
        if str(row.get("arm")) != "base":
            continue
        key = (
            str(row.get("pair_id")),
            str(row.get("arm")),
            int(row.get("repeat") or 0),
        )
        by_slot.setdefault(key, []).append(row)
    walked: dict[str, list[dict[str, Any]]] = {profile: [] for profile in PROFILES}
    for index, pair in enumerate(pairs_doc["pairs"]):
        profile = str(pair["profile"])
        if profile not in walked:
            continue
        for repeat in (1, 2, 3):
            slot_rows = by_slot.get((str(pair["id"]), "base", repeat), [])
            if not slot_rows:
                continue
            entry: dict[str, Any] = {
                "index": index,
                "pair_id": str(pair["id"]),
                "profile": profile,
                "repeat": repeat,
                "draft": None,
                "reason": None,
                "row": None,
                "raw": None,
            }
            first = _slot_first_drawn(slot_rows)
            if first is not None:
                attempts = first.get("attempts") or []
                raw = attempts[0].get("raw_text") if attempts else None
                draft = parse_base_draft(raw) if isinstance(raw, str) else None
                entry["row"] = first
                entry["raw"] = raw
                if draft is None:
                    entry["reason"] = "unparseable"
                elif not cited_facts(draft):
                    entry["reason"] = "no_fact_cited"
                elif select_cited(draft) is None:
                    entry["reason"] = "only_feed_fact"
                elif select_control(draft) is None:
                    entry["reason"] = "no_matched_control"
                else:
                    entry["draft"] = draft
            else:
                entry["reason"] = "unparseable"
            walked[profile].append(entry)
    return walked


def build_cases(
    r3_rows: list[dict[str, Any]], pairs_doc: dict[str, Any] | None = None
) -> tuple[Case, ...]:
    """The 10 cases: first 5 eligible drafts per profile, ids in pair order."""
    doc = pairs_doc if pairs_doc is not None else _default_pairs()
    walked = _walk(r3_rows, doc)
    selected: list[dict[str, Any]] = []
    for profile in PROFILES:
        taken = 0
        for entry in walked[profile]:
            if taken >= CASES_PER_PROFILE:
                break
            if entry["draft"] is None:
                continue
            selected.append(entry)
            taken += 1
    selected.sort(key=lambda entry: (int(entry["index"]), int(entry["repeat"])))
    cases: list[Case] = []
    for number, entry in enumerate(selected, start=1):
        draft = entry["draft"]
        cited = select_cited(draft)
        control = select_control(draft)
        assert cited is not None and control is not None
        row = entry["row"]
        attempts = row.get("attempts") or []
        prompt_hash = str(attempts[0].get("prompt_hash", "") if attempts else "")
        if not prompt_hash:
            prompt_hash = str(row.get("prompt_hash") or "")
        cases.append(
            Case(
                case_id=f"r4-{number:02d}",
                profile=str(entry["profile"]),
                pair_id=str(entry["pair_id"]),
                repeat=int(entry["repeat"]),
                cited_fact=cited,
                control_fact=control,
                base_prompt_hash=prompt_hash,
                base_draft_json=str(entry["raw"]),
            )
        )
    return tuple(cases)


def case_build_report(
    r3_rows: list[dict[str, Any]], pairs_doc: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Per profile: eligible drafts found and discards counted by reason."""
    doc = pairs_doc if pairs_doc is not None else _default_pairs()
    report: dict[str, dict[str, Any]] = {}
    for profile, entries in _walk(r3_rows, doc).items():
        discards: dict[str, int] = {}
        eligible = 0
        for entry in entries:
            if entry["draft"] is None:
                reason = str(entry["reason"])
                discards[reason] = discards.get(reason, 0) + 1
            else:
                eligible += 1
        report[profile] = {"eligible": eligible, "discards": discards}
    return report
