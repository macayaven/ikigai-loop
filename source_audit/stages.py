"""The four stages and the row diagnostics, each as its own result."""

from __future__ import annotations

import math
from typing import Any

from source_audit import recount as R
from source_audit import store as ST
from source_audit.parse import parse_statement

LABELS = ("earlier", "prior", "last")
FAMILY_KEYS = {
    "prs": tuple(f"period.{p}.prs" for p in LABELS) + ("github.pr.count",),
    "pushes": tuple(f"period.{p}.pushes" for p in LABELS) + ("github.push.count",),
}


def _out(
    status: str, nums: list | None, codes: list, problems: dict | None = None
) -> tuple[dict, dict]:
    """Build one stage result: its row dict plus its own problem identifiers."""
    nums = nums if nums is not None else [None, None, None, None]
    row = {
        "status": status,
        "earlier": nums[0],
        "prior": nums[1],
        "last": nums[2],
        "total": nums[3],
        "codes": list(codes),
    }
    return row, problems or {}


def _add(codes: list[str], code: str) -> None:
    """Append a reason code once per stage; repeats carry no new information."""
    if code not in codes:
        codes.append(code)


def _int_or_none(value: Any) -> int | None:
    """Return an integral stored number as an int, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    return None


def _vals(stored: dict, keys: tuple[str, ...]) -> list:
    """Read stored keys as (present, integral-or-None) pairs."""
    return [
        (k in stored, _int_or_none(stored[k]) if k in stored else None) for k in keys
    ]


def _cmp(
    want: int, vals: list, pos: int, nums: dict, codes: list, status: str, key: str
) -> str:
    """Compare stored keys to one recount number; totals read missing as zero."""
    if all(present for present, _ in vals):
        got = [v for _, v in vals]
        if any(v is None for v in got) or sum(got) != want:
            nums[key] = None if any(v is None for v in got) else sum(got)
            _add(codes, "STORED_NUMBER_WRONG")
            return "mismatch"
        nums[key] = sum(got)
        return status
    if key == "total":
        if want == 0:
            nums[key] = 0
            return status
        nums[key] = 0
        _add(codes, "STORED_NUMBER_WRONG")
        return "mismatch"
    elif pos == 2 and want == 0:
        _add(codes, "STORED_PERIOD_WITHHELD")
        return status if status != "match" else "unavailable"
    _add(codes, "STORED_PERIOD_MISSING")
    return "mismatch"


def stage1(count: Any, snapshot: dict[str, Any]) -> dict[str, tuple[dict, dict]]:
    """Run stage 1, the recount itself, per metric."""
    repo, fold = str(snapshot["repo"]), str(snapshot["repo"]).casefold()
    one, two = _s1_prs(count, snapshot, repo, fold), _s1_pushes(count)
    if count is None:
        return {"prs": one, "pushes": two, "pushes_plus_prs": one}
    rec = count["pushes_plus_prs"]
    nums = rec["periods"] + [rec["total"]]
    order = {"mismatch": 0, "unavailable": 1, "match": 2}
    worse = one if order[one[0]["status"]] <= order[two[0]["status"]] else two
    codes = list(dict.fromkeys([*one[0]["codes"], *two[0]["codes"]]))
    problems = {
        k: [*one[1].get(k, []), *two[1].get(k, [])] for k in set(one[1]) | set(two[1])
    }
    return {
        "prs": one,
        "pushes": two,
        "pushes_plus_prs": _out(worse[0]["status"], nums, codes, problems),
    }


def _s1_prs(count: Any, snapshot: dict, repo: str, fold: str) -> tuple[dict, dict]:
    """Run stage 1 for prs: the pull list against the feed's opened rows."""
    if count is None:
        return _out("unavailable", None, ["NO_CYCLE"])
    prs = count["prs"]
    nums = prs["periods"] + [prs["total"]]
    seen: list[Any] = []
    for d in prs["duplicates"]:
        if d["metric"] != "prs":
            continue
        for e in d["events"]:
            entry = {
                "repo": R.spelling(snapshot, repo, str(d["identity"][0])),
                "item": str(d["identity"][1]),
            }
            if e != "pulls":
                entry["event"] = e
            if entry not in seen:
                seen.append(entry)
    pulled = set(prs["pulls"])
    fed = {k for k in prs["feed"] if k[0] == fold and prs["feed"][k][1] is not None}
    disagree = [
        {"repo": R.spelling(snapshot, repo, k[0]), "item": str(k[1])}
        for k in sorted(pulled - fed)
    ]
    disagree += [
        {
            "repo": R.spelling(snapshot, repo, k[0]),
            "item": str(k[1]),
            "event": prs["feed"][k][0],
        }
        for k in sorted(fed - pulled)
    ]
    problems: dict[str, list[Any]] = {}
    if seen:
        problems["duplicate"] = seen
    if disagree:
        problems["disagree"] = disagree
    if prs["duplicates"]:
        return _out("mismatch", nums, ["DUPLICATE_IN_SNAPSHOT"], problems)
    if not count["prs_covered"]:
        return _out("unavailable", nums, ["COVERAGE_GAP"], problems)
    if disagree:
        return _out("mismatch", nums, ["SOURCE_SET_DISAGREE"], problems)
    return _out("match", nums, [], problems)


def _s1_pushes(count: Any) -> tuple[dict, dict]:
    """Run stage 1 for pushes: the feed recount with no independent source."""
    if count is None:
        return _out("unavailable", None, ["NO_CYCLE"])
    pushes = count["pushes"]
    nums = pushes["periods"] + [pushes["total"]]
    if pushes["duplicates"]:
        problems = [
            {"item": R.identity_value(d["identity"]), "event": e}
            for d in pushes["duplicates"]
            for e in d["events"]
        ]
        return _out(
            "mismatch", nums, ["DUPLICATE_IN_SNAPSHOT"], {"duplicate": problems}
        )
    return _out("unavailable", nums, ["NO_INDEPENDENT_SOURCE"])


def _compare_family(
    fam: str, stored: Any, count: Any, joined: list
) -> tuple[dict, list, str, dict]:
    """Compare one family's stored keys to its recount."""
    nums: dict[str, Any] = {"earlier": None, "prior": None, "last": None, "total": None}
    codes: list[str] = []
    status = "match"
    problems: dict[str, list[Any]] = {}
    rec = list(count[fam]["periods"])
    rec_total = count[fam]["total"]
    pairs = list(zip(*[FAMILY_KEYS[fam][:3]]))
    totals = (FAMILY_KEYS[fam][3],)
    keys = tuple(FAMILY_KEYS[fam])
    if not isinstance(stored, dict) or ST.is_invalid(stored):
        _add(codes, "STORE_JSON_INVALID")
        status = "unavailable"
    else:
        for pos, pair in enumerate(pairs):
            status = _cmp(
                rec[pos], _vals(stored, pair), pos, nums, codes, status, LABELS[pos]
            )
        status = _cmp(rec_total, _vals(stored, totals), 0, nums, codes, status, "total")
        for row in joined:
            other = row.get("snapshot")
            if ST.is_invalid(other):
                _add(codes, "STORE_JSON_INVALID")
                status = "unavailable"
            elif isinstance(other, dict):
                for key in keys:
                    if key in stored and key in other and stored[key] != other[key]:
                        status = "mismatch"
                        _add(codes, "SNAPSHOT_DIVERGES")
                        problems.setdefault("snapshot_diverges", [])
                        if key not in problems["snapshot_diverges"]:
                            problems["snapshot_diverges"].append(key)
    return nums, codes, status, problems


def _merge_sum(
    prs_nums: dict,
    prs_codes: list,
    prs_status: str,
    pushes_nums: dict,
    pushes_codes: list,
    pushes_status: str,
    prs_problems: dict,
    pushes_problems: dict,
) -> tuple[dict, list, str, dict]:
    """Merge two families' stage 2 results into their sum."""
    order = {"mismatch": 0, "unavailable": 1, "match": 2}
    worse = prs_status if order[prs_status] <= order[pushes_status] else pushes_status
    nums: dict[str, Any] = {}
    for key in ("earlier", "prior", "last", "total"):
        left, right = prs_nums.get(key), pushes_nums.get(key)
        if (
            isinstance(left, int)
            and not isinstance(left, bool)
            and isinstance(right, int)
            and not isinstance(right, bool)
        ):
            nums[key] = left + right
        else:
            nums[key] = None
    codes = list(dict.fromkeys([*prs_codes, *pushes_codes]))
    problems: dict[str, list[Any]] = {}
    for key in set(prs_problems) | set(pushes_problems):
        merged = [*prs_problems.get(key, []), *pushes_problems.get(key, [])]
        seen: list[Any] = []
        for entry in merged:
            if entry not in seen:
                seen.append(entry)
        problems[key] = seen
    return nums, codes, worse, problems


def stage2(
    scope: tuple, cycle: dict, count: Any, joined: list, guard_note: bool, name: str
) -> tuple[tuple, dict]:
    """Run stage 2, the stored metric, with row diagnostics beside it."""
    stored = cycle.get("snapshot")
    if name == "pushes_plus_prs":
        prs_nums, prs_codes, prs_status, prs_problems = _compare_family(
            "prs", stored, count, joined
        )
        push_nums, push_codes, push_status, push_problems = _compare_family(
            "pushes", stored, count, joined
        )
        nums, codes, status, problems = _merge_sum(
            prs_nums,
            prs_codes,
            prs_status,
            push_nums,
            push_codes,
            push_status,
            prs_problems,
            push_problems,
        )
    else:
        nums, codes, status, problems = _compare_family(name, stored, count, joined)
    if guard_note and "WINDOW_GUARD_NO_FACTS" not in codes:
        codes.append("WINDOW_GUARD_NO_FACTS")
    diag, dproblems = diagnostics(scope, cycle["as_of"], count, name)
    problems.update(dproblems)
    return _out(
        status,
        [nums["earlier"], nums["prior"], nums["last"], nums["total"]],
        codes,
        problems,
    ), diag


def diagnostics(scope: tuple, as_of: Any, count: Any, name: str) -> tuple[dict, dict]:
    """Count stored rows the product would use against the public items."""
    conn, subject, snapshot = scope
    out = {
        "counted": 0,
        "late": 0,
        "not_in_snapshot": 0,
        "items": 0,
        "rows_unreadable": 0,
        "codes": [],
    }
    if not ST.has(conn, "events"):
        out["codes"].append("EVENTS_TABLE_MISSING")
        return out, {}
    start, end = R.window_bounds(as_of)
    rows, unreadable = ST.github_rows(conn, subject, start, end)
    public_ids = {str(e["id"]) for e in snapshot["events"]}
    kinds = ("prs", "pushes") if name == "pushes_plus_prs" else (name,)
    missing: list[Any] = []
    for kind in kinds:
        for row in rows:
            usable = _usable(row, kind)
            if usable and row["collected_at"] > as_of:
                out["late"] += 1
            elif usable:
                out["counted"] += 1
                if row["source_id"] not in public_ids:
                    out["not_in_snapshot"] += 1
        have = {r["source_id"] for r in rows if _usable(r, kind)}
        if kind == "prs":
            missing += _prs_missing(count, snapshot, have)
        else:
            missing += _push_missing(count, have)
        out["rows_unreadable"] += sum(
            1 for r in unreadable if (r["type"] == "github.pr") == (kind == "prs")
        )
    out["items"] = len(missing)
    if out["late"]:
        out["codes"].append("ROWS_COLLECTED_LATE")
    if out["not_in_snapshot"]:
        out["codes"].append("ROWS_NOT_IN_SNAPSHOT")
    if out["items"]:
        out["codes"].append("ITEMS_NOT_STORED")
    return out, ({"item_not_stored": missing} if missing else {})


def _usable(row: dict, kind: str) -> bool:
    """Check a stored row is one the product would count for one metric."""
    if kind == "prs":
        return row["type"] == "github.pr" and row["counts"].get("opened", 0) > 0
    return row["type"] == "github.push"


def _prs_missing(count: Any, snapshot: dict, have: set) -> list[Any]:
    """List public pull requests with no stored row, with identifiers."""
    repo = str(snapshot["repo"])
    named = {k: v for k, v in count["prs"]["feed"].items() if v[1] is not None}
    fed = {k for k in named if k[0] == repo.casefold()}
    missing = [
        {"repo": R.spelling(snapshot, repo, f), "item": str(n), "event": e}
        for (f, n), (e, _, _) in sorted(named.items())
        if e not in have
    ]
    return missing + [
        {"repo": R.spelling(snapshot, repo, f), "item": str(n)}
        for f, n in sorted(count["prs"]["pulls"])
        if (f, n) not in fed
    ]


def _push_missing(count: Any, have: set) -> list[Any]:
    """List public pushes with no stored row, with identifiers."""
    skip = set(count["pushes"].get("open_events", []))
    return [
        {"item": R.identity_value(i), "event": e}
        for i, e in count["pushes"]["counted"].items()
        if e not in skip and e not in have
    ]


def _fill(results: list[dict[str, Any]]) -> list:
    """Merge parsed numbers into one four-number stage line."""
    nums: list[Any] = [None, None, None, None]
    for result in results:
        for idx, value in result.get("periods", {}).items():
            nums[idx] = value
        if result.get("total") is not None:
            nums[3] = result["total"]
    if nums[3] is None and all(
        isinstance(v, int) and not isinstance(v, bool) for v in nums[:3]
    ):
        nums[3] = nums[0] + nums[1] + nums[2]
    return nums


def _check_numbers(parsed: dict[str, Any], periods: list[int], total: int) -> bool:
    """Check parsed numbers against a recount."""
    if any(want != periods[idx] for idx, want in parsed.get("periods", {}).items()):
        return False
    return not (parsed.get("total") is not None and parsed["total"] != total)


def stage3(scope: tuple, cycle: dict, count: Any, name: str) -> tuple[dict, dict]:
    """Run stage 3, the fact statements, with the standalone parser."""
    conn, _, _ = scope
    if name == "pushes_plus_prs":
        return _out("unavailable", None, ["FACT_FAMILY_NOT_STATED"])
    facts = ST.facts_for(conn, cycle["cycle_id"], cycle["run"])
    periods, total = count[name]["periods"], count[name]["total"]
    parsed: list[tuple[int, dict[str, Any]]] = []
    unparsed = ordinal = 0
    for fact in facts:
        result = parse_statement(fact["statement"], name)
        if result["kind"] == "ignored":
            continue
        ordinal += 1
        if result["kind"] == "parsed":
            parsed.append((ordinal, result))
        else:
            unparsed += 1
    if not parsed and not unparsed:
        return _out("unavailable", None, ["FACT_NONE_FOUND"])
    for ordinal, result in parsed:
        if not _check_numbers(result, periods, total):
            wrong = [{"metric": name, "stage": "3", "item": str(ordinal)}]
            return _out(
                "mismatch",
                _fill([result]),
                ["FACT_NUMBER_WRONG"],
                {"statements": wrong},
            )
    if unparsed:
        return _out("unavailable", None, ["FACT_UNPARSED"])
    return _out("match", _fill([r for _, r in parsed]), [])


def split_claims(joined: list[Any]) -> tuple[list[Any], set[str]]:
    """Split joined briefing claims into audited claims and delta texts."""
    audited: list[Any] = []
    deltas: set[str] = set()
    for row in joined:
        briefing = row.get("briefing")
        if not isinstance(briefing, dict):
            continue
        for section in briefing.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            for claim in section.get("claims", []) or []:
                if not isinstance(claim, dict):
                    continue
                if section.get("type") == "since_last":
                    if isinstance(claim.get("text"), str):
                        deltas.add(claim["text"])
                else:
                    audited.append(claim)
    return audited, deltas


def _ref_period(metric_id: str) -> tuple[str, int | None] | None:
    """Map a metric ref to a period index, a total, or None."""
    for pos, label in enumerate(LABELS):
        if metric_id in (f"period.{label}.prs", f"period.{label}.pushes"):
            return ("period", pos)
    if metric_id in ("github.pr.count", "github.push.count"):
        return ("total", None)
    return None


def stage4(ctx: tuple, name: str) -> tuple[dict, dict]:
    """Run stage 4, the delivered claim, split by metric by design."""
    pick_code, picked, joined, card_count, proven, delta_texts = ctx
    if pick_code == "CARD_NOT_SELECTED":
        return _out("unavailable", None, ["CARD_NOT_SELECTED"])
    if pick_code in (
        "CARD_NOT_FOUND",
        "CARD_TABLE_MISSING",
        "CARD_NO_RESULT_ROW",
        "CARD_CYCLE_AMBIGUOUS",
    ):
        return _out("unavailable", None, [pick_code])
    if card_count is None:
        return _out("unavailable", None, ["NO_CYCLE"])
    if name == "pushes_plus_prs":
        return _chart(picked, card_count)
    card = picked.get("card") if isinstance(picked, dict) else None
    if ST.is_invalid(card):
        return _out("unavailable", None, ["STORE_JSON_INVALID"])
    for row in joined:
        if ST.is_invalid(row.get("briefing")):
            return _out("unavailable", None, ["STORE_JSON_INVALID"])
    statements = card.get("statements") if isinstance(card, dict) else None
    if not isinstance(statements, list):
        statements = []
    audited, _ = split_claims(joined)
    periods, total = card_count[name]["periods"], card_count[name]["total"]
    by_text = {c.get("text"): c for c in audited if isinstance(c.get("text"), str)}
    parsed_ok: list[dict[str, Any]] = []
    seen: list[Any] = [None, None, None, None]
    unparsed = stated = 0
    mismatch = False
    wrong: list[Any] = []
    for pos, text in enumerate(statements):
        if not isinstance(text, str) or text in delta_texts:
            continue
        claim = by_text.get(text)
        refs = claim.get("metric_refs", []) if isinstance(claim, dict) else []
        refs = [
            r
            for r in refs
            if isinstance(r, dict) and str(r.get("metric_id")) in FAMILY_KEYS[name]
        ]
        if isinstance(claim, dict) and refs:
            stated += 1
            for ref in refs:
                hit = _ref_period(str(ref.get("metric_id")))
                if hit is None:
                    continue
                idx = 3 if hit[1] is None else hit[1]
                want = total if hit[1] is None else periods[hit[1]]
                value = _int_or_none(ref.get("value"))
                if value is not None:
                    seen[idx] = value
                if value == want:
                    continue
                mismatch = True
                wrong.append({"metric": name, "stage": "4", "item": str(pos + 1)})
        else:
            result = parse_statement(text, name)
            if result["kind"] == "ignored":
                continue
            stated += 1
            if result["kind"] == "unparsed":
                unparsed += 1
            elif not _check_numbers(result, periods, total):
                mismatch = True
                wrong.append({"metric": name, "stage": "4", "item": str(pos + 1)})
            else:
                parsed_ok.append(result)
    merged = _fill(parsed_ok)
    for idx in range(4):
        if merged[idx] is None:
            merged[idx] = seen[idx]
    if mismatch:
        return _out("mismatch", merged, ["CARD_NUMBER_WRONG"], {"statements": wrong})
    if unparsed:
        return _out("unavailable", None, ["FACT_UNPARSED"])
    if not stated:
        return _out("unavailable", None, ["CARD_NONE_FOUND"])
    if not proven:
        return _out("unavailable", merged, ["DELIVERY_NOT_PROVEN"])
    return _out("match", merged, [])


def _chart(picked: Any, card_count: Any) -> tuple[dict, dict]:
    """Run the chart check for the summed metric."""
    chart = picked.get("chart") if isinstance(picked, dict) else None
    if ST.is_invalid(chart):
        return _out("unavailable", None, ["STORE_JSON_INVALID"])
    series = chart.get("pushes") if isinstance(chart, dict) else None
    if not isinstance(series, dict):
        return _out("unavailable", None, ["CHART_MISSING"])
    want = [
        a + b
        for a, b in zip(card_count["prs"]["periods"], card_count["pushes"]["periods"])
    ]
    nums: list[Any] = [None, None, None, None]
    for pos, label in enumerate(LABELS):
        try:
            value = series[label]
        except KeyError:
            return _out("unavailable", None, ["CHART_MISSING"])
        if _int_or_none(value) != want[pos]:
            nums[pos] = _int_or_none(value)
            return _out("mismatch", nums, ["CARD_NUMBER_WRONG"])
        nums[pos] = _int_or_none(value)
    return _out("match", nums, [])


def activity_unmatched(count: Any, snapshot: dict[str, Any]) -> dict[str, int] | None:
    """Count unmatched ref updates per activity type, information only."""
    if not count["coverage"]["activity"]["ok"]:
        return None
    start, end = count["window_start"], count["window_end"]
    heads = {
        str(e["head"])
        for e in snapshot["events"]
        if e["type"] == "PushEvent"
        and e["head"]
        and start <= (_parse_time(e["created_at"]) or end) < end
    }
    user = str(snapshot["user"]).casefold()
    out: dict[str, int] = {}
    for row in snapshot["activity"]:
        moment = _parse_time(row["timestamp"])
        if moment is None or row["actor"] is None or row["actor"].casefold() != user:
            continue
        if not start <= moment < end or not row["after"] or row["after"] in heads:
            continue
        kind = str(row["activity_type"])
        out[kind] = out.get(kind, 0) + 1
    return out


def _parse_time(text: Any) -> Any:
    """Parse an instant or return None; one helper for the activity walk."""
    try:
        return R.parse_instant(text)
    except (ValueError, TypeError):
        return None
