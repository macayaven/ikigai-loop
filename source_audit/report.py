"""Builds the export from a compare result and renders the report from the export."""

from __future__ import annotations

from typing import Any

from source_audit import recount as R
from source_audit import stages as S
from source_audit.export import check_export
from source_audit.limits import LIMITS

METRICS = ("prs", "pushes", "pushes_plus_prs")
ID3 = ("disagree", "duplicate", "item_not_stored")


def _num(value: Any) -> str:
    """Render a stage number or a dash."""
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "-"


def _dash(value: Any) -> str:
    """Render a value or a dash."""
    return str(value) if value is not None else "-"


def _codes(codes: list[str]) -> str:
    """Render stage codes or a dash."""
    return ",".join(codes) if codes else "-"


def _label(entry: dict[str, Any]) -> str:
    """Render one identifier without whitespace."""
    repo = str(entry["repo"]) if "repo" in entry else ""
    item = "#" + str(entry["item"]) if "item" in entry else ""
    event = "@" + str(entry["event"]) if "event" in entry else ""
    return repo + item + event or "-"


def _cov_row(source: str, count: Any, snapshot: dict) -> dict:
    """Render one coverage row for the export."""
    raw, block = snapshot["coverage"][source], count["coverage"][source]
    row = {
        "source": source,
        "rows": block["rows"],
        "stop": block["stop"],
        "oldest": raw.get("oldest"),
        "newest": raw.get("newest"),
    }
    return row


def _diag_row(name: str, diag: dict) -> dict:
    """Render one diagnostics row for the export."""
    row = {
        "metric": name,
        "rows_counted": diag["counted"],
        "rows_late": diag["late"],
        "rows_not_in_snapshot": diag["not_in_snapshot"],
        "items_not_stored": diag["items"],
        "rows_unreadable": diag.get("rows_unreadable", 0),
        "codes": diag["codes"],
    }
    return row


def _stage_entry(row: dict, metric: str, stage: str) -> dict:
    """Build one export stage entry, keeping a card marker last."""
    entry = {key: value for key, value in row.items() if key != "card"}
    entry["metric"] = metric
    entry["stage"] = stage
    if "card" in row:
        entry["card"] = row["card"]
    return entry


def _stage_entries(res: dict) -> list[dict]:
    """Build the export stage entries; extra fourth stages stay stage 4."""
    return [
        _stage_entry(r, n, str(i) if i < 4 else "4")
        for n, rows in res["stages"].items()
        for i, r in enumerate(rows, 1)
    ]


def _verdict_entries(res: dict) -> list[dict]:
    """Build the export verdict entries with per-card verdicts after folded."""
    folded = [{"metric": n, "verdict": v} for n, v in res["verdicts"].items()]
    if not res.get("card_verdicts"):
        return folded
    return folded + [
        {"metric": n, "verdict": entry["verdict"], "card": entry["card"]}
        for n in res["stages"]
        for entry in res["card_verdicts"].get(n, [])
    ]


def build_export(
    res: dict, count: Any, card_window: Any, picked: Any, snapshot: dict
) -> dict[str, Any]:
    """Build the allowlisted public export from a compare result."""
    proven = isinstance(picked, dict) and picked.get("proven", False) is True
    if count is None:
        export: dict[str, Any] = {
            "window_start": None,
            "window_end": None,
            "fetched_at": None,
            "card_window": None,
            "feed_settled": False,
            "delivery_proven": proven,
            "limits": _limit_codes(False),
            "other_repos_feed_only": 0,
            "deltas_not_audited": res["deltas_not_audited"],
            "stages": _stage_entries(res),
            "verdicts": _verdict_entries(res),
            "rows": [_diag_row(n, d) for n, d in res["diagnostics"].items()],
            "activity_unmatched": None,
            "identifiers": {k: res["identifiers"][k] for k in ID3},
            "statements": list(res["identifiers"]["statements"]),
            "per_repo": [],
            "open_hour": [],
            "coverage": [],
            "since_line": res["since_line"],
        }
        if res["identifiers"]["snapshot_diverges"]:
            export["snapshot_diverges"] = list(res["identifiers"]["snapshot_diverges"])
        if res["delta_codes"]:
            export["delta_codes"] = res["delta_codes"]
        check_export(export)
        return export
    activity = S.activity_unmatched(count, snapshot)
    acts = None
    if activity is not None:
        acts = [{"activity_type": k, "count": v} for k, v in sorted(activity.items())]
    export: dict[str, Any] = {
        "window_start": R.fmt_utc(count["window_start"]),
        "window_end": R.fmt_utc(count["window_end"]),
        "fetched_at": R.fmt_utc(count["fetched_at"]),
        "feed_settled": bool(count["feed_settled"]),
        "delivery_proven": proven,
        "limits": _limit_codes(bool(count["feed_settled"])),
        "other_repos_feed_only": count["prs"]["other_repos_feed_only"],
        "deltas_not_audited": res["deltas_not_audited"],
        "card_window": _card_window(card_window, count),
        "per_repo": [dict(r) for r in count["prs"]["per_repo"]],
        "open_hour": [{"metric": n, "count": count[n]["open"]} for n in METRICS],
        "coverage": [
            _cov_row(s, count, snapshot) for s in ("events", "pulls", "activity")
        ],
        "stages": _stage_entries(res),
        "verdicts": _verdict_entries(res),
        "rows": [_diag_row(n, d) for n, d in res["diagnostics"].items()],
        "activity_unmatched": acts,
        "identifiers": {k: res["identifiers"][k] for k in ID3},
        "statements": res["identifiers"]["statements"],
        "since_line": res["since_line"],
    }
    if res["identifiers"]["snapshot_diverges"]:
        export["snapshot_diverges"] = list(res["identifiers"]["snapshot_diverges"])
    if res["delta_codes"]:
        export["delta_codes"] = res["delta_codes"]
    check_export(export)
    return export


def _limit_codes(feed_settled: bool) -> list[str]:
    """Return the limit codes; the settle note rides only when unsettled."""
    codes = [c for c in LIMITS if c != "LIMIT_FEED_MAY_SETTLE" or not feed_settled]
    return sorted(codes)


def _card_window(card_window: Any, count: Any) -> Any:
    """Export the card window only when it differs from the cycle window."""
    if card_window is None or (
        card_window[0] == count["window_start"]
        and card_window[1] == count["window_end"]
    ):
        return None
    return {"start": R.fmt_utc(card_window[0]), "end": R.fmt_utc(card_window[1])}


def render_lines(export: dict[str, Any], tz: str) -> list[str]:
    """Render the pinned report lines from the export dict and nothing else."""
    check_export(export)
    if export["window_start"] is None or export["window_end"] is None:
        lines = [
            (
                f"window_start=- window_end=- tz={tz} fetched_at=- "
                "feed_settled=false "
                f"delivery_proven={'true' if export['delivery_proven'] else 'false'}"
            )
        ]
    else:
        zone = R.require_tz(tz)
        start = R.parse_instant(str(export["window_start"]))
        end = R.parse_instant(str(export["window_end"]))
        lines = [
            (
                f"window_start={export['window_start']} window_end={export['window_end']} "
                f"tz={tz} window_start_local={R.fmt_local(start, zone)} "
                f"window_end_local={R.fmt_local(end, zone)} "
                f"fetched_at={export['fetched_at']} "
                f"feed_settled={'true' if export['feed_settled'] else 'false'} "
                f"delivery_proven={'true' if export['delivery_proven'] else 'false'}"
            )
        ]
    if export.get("card_window") is not None:
        lines.append(
            f"card_window_start={export['card_window']['start']} "
            f"card_window_end={export['card_window']['end']}"
        )
    for r in export["stages"]:
        lines.append(
            f"metric={r['metric']} stage={r['stage']} status={r['status']} "
            f"earlier={_num(r['earlier'])} prior={_num(r['prior'])} "
            f"last={_num(r['last'])} total={_num(r['total'])} "
            f"codes={_codes(r['codes'])}"
            + (f" card={r['card']}" if "card" in r else "")
        )
    for r in export["verdicts"]:
        lines.append(
            f"metric={r['metric']} verdict={r['verdict']}"
            + (f" card={r['card']}" if "card" in r else "")
        )
    for r in export["rows"]:
        lines.append(
            f"metric={r['metric']} rows_counted={_num(r['rows_counted'])} "
            f"rows_late={_num(r['rows_late'])} "
            f"rows_not_in_snapshot={_num(r['rows_not_in_snapshot'])} "
            f"items_not_stored={_num(r['items_not_stored'])} "
            f"rows_unreadable={_num(r['rows_unreadable'])} codes={_codes(r['codes'])}"
        )
    activity = export["activity_unmatched"]
    if activity is None:
        lines.append("activity_unmatched=- codes=-")
        activity = []
    for a in activity:
        lines.append(
            f"activity_unmatched_{a['activity_type']}={a['count']} "
            "codes=ACTIVITY_UNMATCHED_INFO"
        )
    if activity == [] and export["activity_unmatched"] is not None:
        lines.append("activity_unmatched=0 codes=ACTIVITY_UNMATCHED_INFO")
    lines.append(f"other_repos_feed_only={export['other_repos_feed_only']}")
    for r in export["per_repo"]:
        lines.append(f"per_repo={r['repo']}:{r['prs']}:{r['pushes']}")
    for r in export["open_hour"]:
        lines.append(f"open_{r['metric']}={r['count']}")
    for r in export["coverage"]:
        lines.append(
            f"coverage_{r['source']}={r['stop']} rows={r['rows']} "
            f"oldest={_dash(r['oldest'])} newest={_dash(r['newest'])}"
        )
    kinds = export["identifiers"]
    for key in ("disagree", "duplicate", "item_not_stored"):
        joined = ",".join(_label(d) for d in kinds[key])
        lines.append(f"{key}=" + (joined if joined else "-"))
    if export.get("snapshot_diverges"):
        lines.append("snapshot_diverges=" + ",".join(export["snapshot_diverges"]))
    if export["statements"]:
        joined = ",".join(
            f"{d['metric']}:{d['stage']}:{d['item']}"
            + (f":card{d['card']}" if "card" in d else "")
            for d in export["statements"]
        )
        lines.append(f"statements={joined}")
    if export.get("delta_codes"):
        joined = ",".join(export["delta_codes"])
        lines.append(f"deltas={export['deltas_not_audited']} codes={joined}")
    since = export.get("since_line") or {}
    lines.append(
        f"since_line_stated={_dash(since.get('stated'))} "
        f"since_line_recounted={_dash(since.get('recounted'))} "
        f"codes={_codes(since.get('codes', []))}"
    )
    if "LIMIT_FEED_MAY_SETTLE" in export["limits"]:
        lines.append(LIMITS["LIMIT_FEED_MAY_SETTLE"])
    for code in sorted(export["limits"]):
        if code != "LIMIT_FEED_MAY_SETTLE":
            lines.append(LIMITS[code])
    return lines


def render_recount(count: dict, snapshot: dict, tz: str, metric: str) -> list[str]:
    """Render recount lines with the limits for the recount command."""
    zone = R.require_tz(tz)
    lines = [
        (
            f"window_start={R.fmt_utc(count['window_start'])} "
            f"window_end={R.fmt_utc(count['window_end'])} tz={tz} "
            f"window_start_local={R.fmt_local(count['window_start'], zone)} "
            f"window_end_local={R.fmt_local(count['window_end'], zone)} "
            f"fetched_at={R.fmt_utc(count['fetched_at'])} "
            f"feed_settled={'true' if count['feed_settled'] else 'false'}"
        )
    ]
    names = [metric] if metric != "all" else list(METRICS)
    for name in names:
        lines.append(
            f"metric={name} earlier={count[name]['periods'][0]} "
            f"prior={count[name]['periods'][1]} last={count[name]['periods'][2]} "
            f"total={count[name]['total']} open={count[name]['open']}"
        )
    for item in count["prs"]["items"]:
        at = f"@{item['event']}" if item["event"] else ""
        lines.append(
            f"pr={item['repo']}#{item['number']}{at} period={item['period']} "
            f"time={R.fmt_utc(item['time'])}"
        )
    for item in count["pushes"]["items"]:
        lines.append(
            f"push={item['identity']}@{item['event']} period={item['period']} "
            f"time={R.fmt_utc(item['time'])}"
        )
    for row in count["prs"]["per_repo"]:
        lines.append(f"per_repo={row['repo']}:{row['prs']}:{row['pushes']}")
    for source in ("events", "pulls", "activity"):
        r = _cov_row(source, count, snapshot)
        lines.append(
            f"coverage_{r['source']}={r['stop']} rows={r['rows']} "
            f"oldest={_dash(r['oldest'])} newest={_dash(r['newest'])}"
        )
    for dup in count["prs"]["duplicates"] + count["pushes"]["duplicates"]:
        lines.append(f"duplicate={dup['metric']}:{','.join(dup['events'])}")
    lines.append(f"feed_settled={'true' if count['feed_settled'] else 'false'}")
    if not count["feed_settled"]:
        lines.append(LIMITS["LIMIT_FEED_MAY_SETTLE"])
    for code in sorted(LIMITS):
        if code != "LIMIT_FEED_MAY_SETTLE":
            lines.append(LIMITS[code])
    return lines
