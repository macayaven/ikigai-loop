"""Choosing the target, the window guard, calling the stages, the verdicts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, NamedTuple

from source_audit import recount as R
from source_audit import report as RP
from source_audit import stages as S
from source_audit import store as ST
from source_audit.parse import parse_since_line
from source_audit.snapshot import validate_snapshot

METRICS = ("prs", "pushes", "pushes_plus_prs")


class Selection(NamedTuple):
    """The chosen target: card request, instant, cycle and picked card."""

    want_card: str | None
    as_of: str | None
    cycle: Any
    picked: Any
    pick_code: str
    joined: Any
    ambiguous: bool


class StageContext(NamedTuple):
    """The inputs stage 4 compares against the card and the recount."""

    pick_code: str
    picked: Any
    joined: Any
    card_count: Any
    proven: bool
    delta_texts: Any


class PickResult(NamedTuple):
    """One delivered-card pick with its join, ambiguity and previous instant."""

    picked: Any
    code: str
    joined: Any
    ambiguous: bool
    prev: Any


class CompareError(Exception):
    """A usage or operational failure carrying its closed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _blank(code: str) -> tuple[dict, dict]:
    """Return an empty stage result before its stage runs."""
    row = {"status": "unavailable", "earlier": None, "prior": None, "last": None}
    return row | {"total": None, "codes": [code] if code else []}, {}


def _recount(snapshot: dict, moment: Any) -> Any:
    """Recount the feed at one instant for the snapshot's user and repo."""
    return R.recount(snapshot, moment, snapshot["user"], snapshot["repo"])


def _verdict(statuses: list[str]) -> str:
    """Fold four stage statuses into one verdict."""
    if "mismatch" in statuses:
        return "FAIL"
    return "PASS" if all(s == "match" for s in statuses) else "INCOMPLETE"


def _gap_23(metric: str, count: Any) -> bool:
    """Check whether stage 1 coverage blocks stages 2 and 3 for one metric."""
    if count is None:
        return False
    if metric == "prs":
        return not count["prs_covered"]
    if metric == "pushes":
        return not count["feed_ok"]
    return not count["prs_covered"]


def _gap_4(metric: str, card_count: Any) -> bool:
    """Check whether card-window coverage blocks stage 4 for one metric."""
    if card_count is None:
        return False
    if metric == "prs":
        return not card_count["prs_covered"]
    if metric == "pushes":
        return not card_count["feed_ok"]
    return not card_count["prs_covered"]


def _force_gap(stage: dict) -> dict:
    """Force one stage to unavailable, keeping its numbers, adding the gap code."""
    stage = dict(stage)
    stage["status"] = "unavailable"
    codes = list(stage.get("codes", []))
    if "COVERAGE_GAP" not in codes:
        codes.append("COVERAGE_GAP")
    stage["codes"] = codes
    return stage


def _apply_since(stage: dict, since_info: dict) -> dict:
    """Fold the since-line check into the summed metric's stage 4."""
    codes = list(since_info.get("codes", []))
    if not codes:
        return stage
    if "SINCE_LINE_WRONG" in codes:
        stage = dict(stage)
        stage["status"] = "mismatch"
        merged = list(stage.get("codes", []))
        if "SINCE_LINE_WRONG" not in merged:
            merged.append("SINCE_LINE_WRONG")
        stage["codes"] = merged
        return stage
    if "SINCE_LINE_UNREADABLE" in codes:
        if stage.get("status") == "mismatch":
            return stage
        stage = dict(stage)
        stage["status"] = "unavailable"
        merged = list(stage.get("codes", []))
        if "SINCE_LINE_UNREADABLE" not in merged:
            merged.append("SINCE_LINE_UNREADABLE")
        stage["codes"] = merged
        return stage
    return stage


def run_compare(
    snapshot: dict[str, Any],
    conn: Any,
    *,
    as_of: str | None = None,
    card: str | None = None,
    metric: str = "all",
    tz: str = "Europe/Madrid",
    subject: str | None = None,
) -> dict[str, Any]:
    """Run the four stages for the chosen metrics over an open store."""
    snapshot = validate_snapshot(snapshot)
    try:
        R.require_tz(tz)
    except ValueError:
        raise CompareError("USAGE_BAD_TZ") from None
    if metric not in METRICS + ("all",):
        raise CompareError("USAGE_BAD_METRIC")
    chosen = [metric] if metric != "all" else list(METRICS)
    subjects = [subject] if subject is not None else ST.distinct_subjects(conn)
    if len(subjects) != 1:
        raise CompareError("USAGE_SUBJECT_AMBIGUOUS")
    subject = subjects[0]
    try:
        cycle_as_of = R.parse_instant(as_of) if as_of is not None else None
        instant = R.parse_instant(card) if card not in (None, "latest") else None
    except ValueError:
        raise CompareError("USAGE_BAD_INSTANT") from None
    cycle = ST.cycle_at(conn, subject, cycle_as_of) if cycle_as_of is not None else None
    want_card, choice = card, "latest" if card == "latest" else None
    pick_result = _pick(conn, subject, choice, instant)
    picked = pick_result.picked
    pick_code = pick_result.code
    slot_joined = list(pick_result.joined)
    ambiguous = pick_result.ambiguous
    prev = pick_result.prev
    t13 = all(ST.has(conn, name) for name in ST.TICKET13)
    corrections: list[dict] = []
    slot_rows: list[dict] = slot_joined
    if t13 and picked is not None:
        slot_rows = ST.results_rows_at(conn, subject, picked["slot"])
        if slot_rows:
            slot_joined = ST.own_rows_for(slot_rows, _card_statements(picked))
            corrections = ST.corrected_cards(conn, picked)
            only = {(row["cycle_id"], row["run"]) for row in slot_joined}
            if len(only) > 1:
                ambiguous, pick_code = True, "CARD_CYCLE_AMBIGUOUS"
            else:
                ambiguous, pick_code = False, ""
    sel = Selection(
        want_card=want_card,
        as_of=as_of,
        cycle=cycle,
        picked=picked,
        pick_code=pick_code,
        joined=slot_joined,
        ambiguous=ambiguous,
    )
    cycle, pick_code = _resolve(conn, subject, sel)
    guard_fail = guard_note = False
    if cycle is not None:
        cycle_as_of = cycle["as_of"]
        facts = ST.facts_for(conn, cycle["cycle_id"], cycle["run"])
        want = R.window_bounds(cycle_as_of)
        guard_fail = any((f["window_start"], f["window_end"]) != want for f in facts)
        guard_note = not facts
    count = _recount(snapshot, cycle_as_of) if cycle_as_of else None
    moment = picked.get("as_of") if picked else None
    card_window = R.window_bounds(moment) if moment else None
    stamp = moment or cycle_as_of
    card_count = _recount(snapshot, stamp) if picked and stamp else None
    stages, diagnostics = {}, {}
    identifiers: dict[str, list] = {
        "disagree": [],
        "duplicate": [],
        "item_not_stored": [],
        "snapshot_diverges": [],
        "statements": [],
    }
    scope = (conn, subject, snapshot)
    first = S.stage1(count, snapshot)
    blank_code = "NO_CYCLE" if count is None else "WINDOW_RULE_MISMATCH"
    for name in chosen:
        stages[name] = [first[name][0], _blank("")[0], _blank("")[0]]
        identifiers["disagree"].extend(first[name][1].get("disagree", []))
        for entry in first[name][1].get("duplicate", []):
            if "repo" not in entry or entry not in identifiers["duplicate"]:
                identifiers["duplicate"].append(entry)
        if count is None or guard_fail:
            stages[name][1:] = [_blank(blank_code)[0] for _ in range(2)]
            diag = _diag0(conn)
        elif cycle is None:
            stages[name][1:3] = [_blank("NO_CYCLE")[0] for _ in range(2)]
            diag, dprobs = S.diagnostics(scope, cycle_as_of, count, name)
            identifiers["item_not_stored"].extend(dprobs.get("item_not_stored", []))
        else:
            (two, probs), diag = S.stage2(
                scope, cycle, count, slot_joined, guard_note, name
            )
            stages[name][1] = two
            identifiers["snapshot_diverges"].extend(probs.get("snapshot_diverges", []))
            identifiers["item_not_stored"].extend(probs.get("item_not_stored", []))
            stages[name][2], tprobs = S.stage3(scope, cycle, count, name)
            identifiers["statements"].extend(tprobs.get("statements", []))
        if not guard_fail and _gap_23(name, count):
            stages[name][1] = _force_gap(stages[name][1])
            stages[name][2] = _force_gap(stages[name][2])
        diagnostics[name] = diag
    proven = isinstance(picked, dict) and picked.get("proven", False) is True
    multi = bool(corrections)
    cards_ctx: list[tuple[int, StageContext, dict]] = []
    if not multi:
        _, delta_texts = S.split_claims(slot_joined)
        card_body = picked.get("card") if isinstance(picked, dict) else None
        deltas = card_body.get("statements") if isinstance(card_body, dict) else None
        deltas = deltas if isinstance(deltas, list) else []
        deltas_not_audited = sum(
            1 for t in deltas if isinstance(t, str) and t in delta_texts
        )
        delta_codes = ["CARD_DELTA_NOT_AUDITED"] if delta_texts else []
        ctx = StageContext(
            pick_code=pick_code,
            picked=picked,
            joined=slot_joined,
            card_count=card_count,
            proven=proven,
            delta_texts=delta_texts,
        )
        cards_ctx = [(0, ctx, _since(snapshot, picked, prev))]
    else:
        _, slot_deltas = S.split_claims(slot_joined)
        slot_ctx = StageContext(
            pick_code=pick_code,
            picked=picked,
            joined=slot_joined,
            card_count=card_count,
            proven=proven,
            delta_texts=slot_deltas,
        )
        cards_ctx = [(1, slot_ctx, _since(snapshot, picked, prev))]
        for ordinal, corr in enumerate(corrections, 2):
            own = ST.own_rows_for(slot_rows, _card_statements(corr))
            cycles = {(row["cycle_id"], row["run"]) for row in own}
            if not own:
                code, moment = "CARD_NO_RESULT_ROW", None
            elif len(cycles) > 1:
                code, moment = "CARD_CYCLE_AMBIGUOUS", None
            else:
                code, moment = "", None
                found = ST.cycle_get(conn, *next(iter(cycles))) if cycles else None
                moment = found["as_of"] if found else None
            entry = dict(corr) | {"as_of": moment}
            own_count = _recount(snapshot, moment) if moment else None
            _, own_deltas = S.split_claims(own)
            cards_ctx.append(
                (
                    ordinal,
                    StageContext(
                        pick_code=code,
                        picked=entry,
                        joined=own,
                        card_count=own_count,
                        proven=True,
                        delta_texts=own_deltas,
                    ),
                    _since(snapshot, entry, prev),
                )
            )
        all_deltas: set[str] = set()
        total = 0
        for _, card_ctx, _ in cards_ctx:
            for text in _card_statements(card_ctx.picked):
                if isinstance(text, str) and text in card_ctx.delta_texts:
                    total += 1
            all_deltas |= set(card_ctx.delta_texts)
        deltas_not_audited = total
        delta_codes = ["CARD_DELTA_NOT_AUDITED"] if all_deltas else []
    card_verdicts: dict[str, list] = {}
    for name in chosen:
        if guard_fail:
            for ordinal, _ctx, _ in cards_ctx:
                row = _blank("WINDOW_RULE_MISMATCH")[0]
                if multi:
                    row = dict(row) | {"card": ordinal}
                stages[name].append(row)
            continue
        for ordinal, card_ctx, since_each in cards_ctx:
            row, fprobs = S.stage4(card_ctx, name)
            if multi:
                row = dict(row) | {"card": ordinal}
                for entry in fprobs.get("statements", []):
                    entry["card"] = ordinal
            stages[name].append(row)
            identifiers["statements"].extend(fprobs.get("statements", []))
            if name == "pushes_plus_prs" and card_ctx.proven:
                stages[name][-1] = _apply_since(stages[name][-1], since_each)
            if _gap_4(name, card_ctx.card_count):
                stages[name][-1] = _force_gap(stages[name][-1])
    since_info = cards_ctx[0][2]
    if multi:
        for name in chosen:
            first_three = [row["status"] for row in stages[name][:3]]
            fourths = stages[name][-len(cards_ctx) :]
            card_verdicts[name] = [
                {"verdict": _verdict(first_three + [row["status"]]), "card": ordinal}
                for (ordinal, _, _), row in zip(cards_ctx, fourths)
            ]
    verdicts = {n: _verdict([s["status"] for s in stages[n]]) for n in chosen}
    worst = max({"FAIL": 3, "INCOMPLETE": 2, "PASS": 1}[v] for v in verdicts.values())
    exit_code = {3: 1, 2: 3, 1: 0}[worst]
    res = {
        "stages": stages,
        "verdicts": verdicts,
        "card_verdicts": card_verdicts,
        "exit": exit_code,
        "diagnostics": diagnostics,
        "identifiers": identifiers,
        "delta_codes": delta_codes,
        "deltas_not_audited": deltas_not_audited,
        "delivery_proven": proven,
        "feed_settled": count["feed_settled"] if count else False,
        "other_repos_feed_only": count["prs"]["other_repos_feed_only"] if count else 0,
        "card_window": card_window,
        "since_line": since_info,
    }
    res["export"] = RP.build_export(res, count, card_window, picked, snapshot)
    res["lines"] = RP.render_lines(res["export"], tz)
    return res


def _resolve(conn: Any, subject: str, sel: tuple) -> tuple[Any, str]:
    """Join the card to a cycle, applying the first-match target rules."""
    want_card, as_of, cycle, picked, pick_code, joined, ambiguous = sel
    if picked is None and cycle is None and (want_card is not None or as_of is None):
        cycle = ST.latest_cycle(conn, subject)
        if cycle is None:
            raise CompareError("USAGE_NO_TARGET")
    if want_card is None:
        pick_code = "CARD_NOT_SELECTED"
    if ambiguous:
        found = [ST.cycle_get(conn, r["cycle_id"], r["run"]) for r in joined]
        best = max([r for r in found if r], key=lambda r: r["as_of"], default=None)
        return best, "CARD_CYCLE_AMBIGUOUS"
    if picked is not None and not joined and pick_code == "CARD_NO_RESULT_ROW":
        cycle = cycle or ST.latest_cycle(conn, subject)
    elif picked is not None and joined:
        only = {(r["cycle_id"], r["run"]) for r in joined}
        if len(only) == 1:
            cycle = ST.cycle_get(conn, *next(iter(only))) or cycle
    return cycle, pick_code


def _diag0(conn: Any) -> dict:
    """Return null diagnostics with the events-table note where needed."""
    diag: dict[str, Any] = {
        "counted": None,
        "late": None,
        "not_in_snapshot": None,
        "items": None,
    }
    diag["rows_unreadable"] = None
    diag["codes"] = ["EVENTS_TABLE_MISSING"] if not ST.has(conn, "events") else []
    return diag


def _since(snapshot: dict, picked: Any, prev: Any) -> dict[str, Any]:
    """Report the card's floored since count against its stated number."""
    if not isinstance(picked, dict) or picked.get("proven") is not True:
        return {"stated": None, "recounted": None, "codes": []}
    end = picked.get("as_of")
    if not isinstance(end, datetime):
        return {"stated": None, "recounted": None, "codes": []}
    card = picked.get("card")
    line = card.get("since_line") if isinstance(card, dict) else None
    start_raw = prev if isinstance(prev, datetime) else end - timedelta(hours=24)
    start = R.floor_hour(start_raw)
    finish = R.floor_hour(end)
    recounted = R.count_between(
        snapshot, str(snapshot["user"]), str(snapshot["repo"]), start, finish
    )
    if line is None:
        return {"stated": None, "recounted": recounted, "codes": []}
    stated = parse_since_line(line)
    if stated is None:
        return {"stated": None, "recounted": None, "codes": ["SINCE_LINE_UNREADABLE"]}
    if recounted is None:
        return {"stated": stated, "recounted": None, "codes": []}
    if stated != recounted:
        return {
            "stated": stated,
            "recounted": recounted,
            "codes": ["SINCE_LINE_WRONG"],
        }
    return {"stated": stated, "recounted": recounted, "codes": []}


def _card_statements(picked: Any) -> list:
    """Return a picked card's statements, or an empty list when unreadable."""
    card = picked.get("card") if isinstance(picked, dict) else None
    statements = card.get("statements") if isinstance(card, dict) else None
    return list(statements) if isinstance(statements, list) else []


def _pick(
    conn: Any, subject: str, choice: str | None, instant: datetime | None
) -> PickResult:
    """Pick the delivered card, the joined rows, ambiguity, and the previous as_of."""
    if choice is None and instant is None:
        return PickResult(
            picked=None, code="CARD_NOT_SELECTED", joined=[], ambiguous=False, prev=None
        )
    t13 = all(ST.has(conn, name) for name in ST.TICKET13)
    rows = ST.ticket13_cards(conn, subject) if t13 else ST.fallback_cards(conn)
    if rows is None:
        return PickResult(
            picked=None,
            code="CARD_TABLE_MISSING",
            joined=[],
            ambiguous=False,
            prev=None,
        )
    all_cards = [c for c in rows if isinstance(c.get("slot"), datetime)]
    if instant is not None:
        cards = [c for c in all_cards if c.get("slot") == instant]
    elif choice == "latest":
        cards = list(all_cards)
    else:
        cards = []
    if not cards:
        return PickResult(
            picked=None, code="CARD_NOT_FOUND", joined=[], ambiguous=False, prev=None
        )
    cards.sort(key=lambda c: (c["slot"], c["rowid"]))
    picked = dict(cards[-1]) | {"proven": t13}
    prev = None
    if t13:
        earlier = [c for c in all_cards if c["slot"] < picked["slot"]]
        if earlier:
            earlier.sort(key=lambda c: (c["slot"], c["rowid"]))
            prev = earlier[-1].get("as_of")
    joined = ST.results_at(conn, subject, picked["slot"])
    if not joined:
        return PickResult(
            picked=picked,
            code="CARD_NO_RESULT_ROW",
            joined=[],
            ambiguous=False,
            prev=prev,
        )
    if len({(r["cycle_id"], r["run"]) for r in joined}) > 1:
        return PickResult(
            picked=picked,
            code="CARD_CYCLE_AMBIGUOUS",
            joined=joined,
            ambiguous=True,
            prev=prev,
        )
    return PickResult(picked=picked, code="", joined=joined, ambiguous=False, prev=prev)
