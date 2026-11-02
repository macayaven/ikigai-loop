"""My own window, period, and recount rules, written fresh from the product meaning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

WINDOW = timedelta(hours=72)
SETTLE_AFTER = timedelta(hours=6)
FEED_MAX_AGE = timedelta(days=30)
FEED_ROW_CAP = 300

PERIOD_NAMES = ("earlier", "prior", "last")


def parse_instant(text: str) -> datetime:
    """Parse an aware instant or raise."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("naive instant")
    return moment


def parse_opt_instant(value: Any) -> datetime | None:
    """Parse an aware instant or return None."""
    try:
        return parse_instant(value) if isinstance(value, str) else None
    except ValueError:
        return None


def fmt_utc(moment: datetime) -> str:
    """Format an instant as UTC ISO 8601 with a Z suffix at second precision."""
    moment = moment.astimezone(UTC).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def require_tz(name: str) -> ZoneInfo:
    """Return a zone or raise a usage error without its name leaking."""
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, TypeError):
        raise ValueError("USAGE_BAD_TZ") from None


def fmt_local(moment: datetime, zone: ZoneInfo) -> str:
    """Format an instant on a named zone at second precision."""
    return moment.astimezone(zone).replace(microsecond=0).isoformat()


def floor_hour(as_of: datetime) -> datetime:
    """Floor an instant to the whole UTC hour, keeping its own fixed offset."""
    offset = as_of.utcoffset()
    if offset is None:
        raise ValueError("as_of must carry a UTC offset")
    floored = as_of.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return floored.astimezone(timezone(offset))


def window_bounds(as_of: datetime) -> tuple[datetime, datetime]:
    """Return the floored 72-hour data window (start, end)."""
    end = floor_hour(as_of)
    return (end - WINDOW, end)


def period_bounds(as_of: datetime) -> tuple[tuple[str, datetime, datetime], ...]:
    """Return the three half-open 24-hour periods ending at the floor."""
    end = floor_hour(as_of)
    cuts = [end - timedelta(hours=h) for h in (72, 48, 24, 0)]
    return tuple((name, cuts[i], cuts[i + 1]) for i, name in enumerate(PERIOD_NAMES))


def _period_index(moment: datetime, bounds: Any) -> int | None:
    """Return the period index holding a moment, or None."""
    for i, (_, start, end) in enumerate(bounds):
        if start <= moment < end:
            return i
    return None


def _same(left: str, right: str) -> bool:
    """Compare names case-insensitively."""
    return left.casefold() == right.casefold()


def spelling(snapshot: dict[str, Any], repo: str, folded: str) -> str:
    """Return the snapshot's own spelling of a folded repo name."""
    names = [snapshot["repo"]] + [e["repo"] for e in snapshot["events"]]
    return next((str(n) for n in names if str(n).casefold() == folded), folded)


def identity_value(identity: str) -> str:
    """Return the raw push id or head SHA behind an identity label."""
    for prefix in ("push:", "head:"):
        if identity.startswith(prefix):
            return identity[len(prefix) :]
    return identity


def _identity(event: dict[str, Any]) -> str:
    """Return the push identity behind one feed row."""
    if event["push_id"] is not None:
        return f"push:{event['push_id']}"
    return f"head:{event['head']}"


def recount(snapshot: dict[str, Any], as_of: datetime, user: str, repo: str) -> dict:
    """Recount prs, pushes, and their sum from a validated snapshot."""
    bounds = period_bounds(as_of)
    start, end = bounds[0][1], bounds[2][2]
    fetched_at = parse_instant(snapshot["fetched_at"])
    coverage = {
        name: _coverage(
            snapshot["coverage"][name], start, end, fetched_at, name == "events"
        )
        for name in ("events", "pulls", "activity")
    }
    prs = _recount_prs(snapshot, bounds, as_of, user, repo)
    pushes = _recount_pushes(snapshot, bounds, as_of, user)
    for name, count in pushes["by_repo"].items():
        slot = next((r for r in prs["per_repo"] if r["repo"].casefold() == name), None)
        if slot is None:
            slot = {"repo": spelling(snapshot, repo, name), "prs": 0, "pushes": 0}
            prs["per_repo"].append(slot)
            prs["per_repo"].sort(key=lambda r: r["repo"].casefold())
        slot["pushes"] = count
    out: dict = {
        "window_start": start,
        "window_end": end,
        "fetched_at": fetched_at,
        "feed_settled": fetched_at >= end + SETTLE_AFTER,
        "coverage": coverage,
        "prs": prs,
        "pushes": pushes,
        "pushes_plus_prs": {
            "periods": [a + b for a, b in zip(prs["periods"], pushes["periods"])],
            "total": prs["total"] + pushes["total"],
            "open": prs["open"] + pushes["open"],
        },
        "feed_ok": coverage["events"]["ok"],
        "pulls_ok": coverage["pulls"]["ok"],
        "prs_covered": coverage["events"]["ok"] and coverage["pulls"]["ok"],
    }
    return out


def count_between(
    snapshot: dict[str, Any], user: str, repo: str, start: datetime, end: datetime
) -> int | None:
    """Count pushes plus opened PRs in one half-open range, or None uncovered."""
    fetched_at = parse_instant(snapshot["fetched_at"])
    events = _coverage(snapshot["coverage"]["events"], start, end, fetched_at, True)
    pulls = _coverage(snapshot["coverage"]["pulls"], start, end, fetched_at, False)
    if not (events["ok"] and pulls["ok"]):
        return None
    fold = repo.casefold()
    prs: set[tuple[str, int]] = set()
    for pull in snapshot["pulls"]:
        if pull["author"] is None or not _same(str(pull["author"]), user):
            continue
        if start <= parse_instant(pull["created_at"]) < end:
            prs.add((fold, int(pull["number"])))
    for event in snapshot["events"]:
        if event["actor"] is None or not _same(str(event["actor"]), user):
            continue
        created = parse_instant(event["created_at"])
        if not start <= created < end:
            continue
        if event["type"] == "PullRequestEvent" and event["action"] == "opened":
            name = str(event["repo"])
            if not _same(name, repo):
                prs.add((name.casefold(), int(event["pr_number"])))
    pushes: set[str] = set()
    for event in snapshot["events"]:
        if event["type"] != "PushEvent":
            continue
        if event["actor"] is None or not _same(str(event["actor"]), user):
            continue
        if not start <= parse_instant(event["created_at"]) < end:
            continue
        pushes.add(_identity(event))
    return len(prs) + len(pushes)


def _coverage(
    block: dict[str, Any],
    start: datetime,
    end: datetime,
    fetched_at: datetime,
    is_feed: bool,
) -> dict[str, Any]:
    """Decide whether one source covers the window."""
    oldest = parse_opt_instant(block["oldest"])
    reached = oldest is not None and oldest <= start
    settled = block["stop"] in ("last_page", "empty_page")
    ok = fetched_at >= end and (settled or reached)
    if is_feed:
        ok = ok and start >= fetched_at - FEED_MAX_AGE
        ok = ok and (settled and block["rows"] < FEED_ROW_CAP or reached)
    return {"ok": ok, "stop": block["stop"], "rows": block["rows"]}


def _recount_prs(
    snapshot: dict[str, Any], bounds: Any, as_of: datetime, user: str, repo: str
) -> dict:
    """Recount opened pull requests from the pull list and the feed."""
    start, end = bounds[0][1], bounds[2][2]
    fold = repo.casefold()
    periods, feed_here, feed_other = [0, 0, 0], [0, 0, 0], [0, 0, 0]
    open_count = open_other = 0
    pulls: dict[tuple[str, int], tuple[int, datetime]] = {}
    feed: dict[tuple[str, int], tuple[str, int | None, datetime]] = {}
    dups: list[dict[str, Any]] = []
    per_repo: dict[str, list[int]] = {}
    open_pulls: list[dict[str, Any]] = []
    for pull in snapshot["pulls"]:
        if pull["author"] is None or not _same(str(pull["author"]), user):
            continue
        created = parse_instant(pull["created_at"])
        key = (fold, int(pull["number"]))
        if start <= created < end:
            idx = _period_index(created, bounds)
            if key in pulls:
                dup = {
                    "metric": "prs",
                    "identity": [str(snapshot["repo"]), key[1]],
                    "events": ["pulls", "pulls"],
                }
                dups.append(dup)
            else:
                pulls[key] = (idx or 0, created)
                periods[idx or 0] += 1
                per_repo.setdefault(fold, [0, 0])[0] += 1
        elif end <= created < as_of:
            open_count += 1
            entry = {
                "repo": str(snapshot["repo"]),
                "number": key[1],
                "event": None,
                "time": created,
                "period": "open",
            }
            open_pulls.append(entry)
    for event in snapshot["events"]:
        if event["type"] != "PullRequestEvent" or event["action"] != "opened":
            continue
        if event["actor"] is None or not _same(str(event["actor"]), user):
            continue
        created = parse_instant(event["created_at"])
        name = str(event["repo"])
        key = (name.casefold(), int(event["pr_number"]))
        here, late = start <= created < end, end <= created < as_of
        if not (here or late):
            continue
        if key in feed:
            if feed[key][0] != str(event["id"]):
                dup = {
                    "metric": "prs",
                    "identity": [name, key[1]],
                    "events": [feed[key][0], str(event["id"])],
                }
                dups.append(dup)
            continue
        idx = _period_index(created, bounds) if here else None
        feed[key] = (str(event["id"]), idx, created)
        if idx is not None:
            (feed_here if _same(name, repo) else feed_other)[idx] += 1
            if not _same(name, repo):
                per_repo.setdefault(name.casefold(), [0, 0])[0] += 1
        elif late and not _same(name, repo):
            open_other += 1
    by_repo = [
        {"repo": spelling(snapshot, repo, name), "prs": counts[0], "pushes": counts[1]}
        for name, counts in sorted(per_repo.items())
    ]
    items = []
    for (f, n), (e, i, t) in sorted(feed.items()):
        if i is None:
            continue
        item = {
            "repo": spelling(snapshot, repo, f),
            "number": n,
            "event": e,
            "time": t,
            "period": bounds[i][0],
        }
        items.append(item)
    seen = {(item["repo"].casefold(), item["number"]) for item in items}
    for (f, n), (i, t) in sorted(pulls.items()):
        if (f, n) in seen:
            continue
        item = {
            "repo": spelling(snapshot, repo, f),
            "number": n,
            "event": None,
            "time": t,
            "period": bounds[i][0],
        }
        items.append(item)
    for (f, n), (e, i, t) in sorted(feed.items()):
        if i is not None or _same(f, fold):
            continue
        item = {
            "repo": spelling(snapshot, repo, f),
            "number": n,
            "event": e,
            "time": t,
            "period": "open",
        }
        items.append(item)
    items.extend(open_pulls)
    headline = [a + b for a, b in zip(periods, feed_other)]
    out = {
        "periods": headline,
        "total": sum(headline),
        "open": open_count + open_other,
        "feed_periods": feed_here,
        "feed_total": sum(feed_here),
        "feed_other": feed_other,
        "per_repo": by_repo,
        "other_repos_feed_only": sum(feed_other),
        "duplicates": dups,
        "pulls": pulls,
        "feed": feed,
        "items": items,
    }
    return out


def _recount_pushes(
    snapshot: dict[str, Any], bounds: Any, as_of: datetime, user: str
) -> dict:
    """Recount feed pushes by push identity, never by event id."""
    start, end = bounds[0][1], bounds[2][2]
    open_count, periods = 0, [0, 0, 0]
    counted: dict[str, str] = {}
    open_events: set[str] = set()
    dups: list[dict[str, Any]] = []
    by_repo: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for event in snapshot["events"]:
        if event["type"] != "PushEvent":
            continue
        if event["actor"] is None or not _same(str(event["actor"]), user):
            continue
        created = parse_instant(event["created_at"])
        here, late = start <= created < end, end <= created < as_of
        if not (here or late):
            continue
        identity = _identity(event)
        if identity in counted:
            if counted[identity] != str(event["id"]):
                dup: dict[str, Any] = {
                    "metric": "pushes",
                    "identity": identity,
                    "events": [counted[identity], str(event["id"])],
                }
                dups.append(dup)
            continue
        counted[identity] = str(event["id"])
        if here:
            idx = _period_index(created, bounds)
            periods[idx or 0] += 1
            name = str(event["repo"]).casefold()
            by_repo[name] = by_repo.get(name, 0) + 1
            period = bounds[idx][0]
        else:
            open_count += 1
            open_events.add(str(event["id"]))
            period = "open"
        item: dict[str, Any] = {
            "identity": identity_value(identity),
            "event": str(event["id"]),
            "time": created,
            "period": period,
        }
        items.append(item)
    out = {
        "periods": periods,
        "total": sum(periods),
        "open": open_count,
        "duplicates": dups,
        "counted": counted,
        "open_events": sorted(open_events),
        "by_repo": by_repo,
        "items": items,
    }
    return out
