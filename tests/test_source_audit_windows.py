"""Source-audit windows and definitions (Ticket E2 plan, windows file)."""

from datetime import UTC, datetime

from source_audit import recount as R

USER = "synthetic-user"
REPO = "synthetic-owner/synthetic-repo"
AS_OF = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)
WS = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)


def _event(eid, kind, created, action=None, number=None):
    return {
        "id": str(eid),
        "type": kind,
        "repo": REPO,
        "actor": USER,
        "created_at": created,
        "action": action,
        "pr_number": number,
        "push_id": None,
        "head": None,
        "before": None,
    }


def _pull(number, created, author=USER):
    return {"number": number, "created_at": created, "author": author}


def _snapshot(events, pulls=()):
    rows = list(events)
    times = sorted(e["created_at"] for e in rows)
    pulls = list(pulls)
    return {
        "fetched_at": "2026-10-31T00:10:00Z",
        "user": USER,
        "repo": REPO,
        "events": rows,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(rows),
                "oldest": times[0] if times else None,
                "newest": times[-1] if times else None,
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": min((p["created_at"] for p in pulls), default=None),
                "newest": max((p["created_at"] for p in pulls), default=None),
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


def test_half_open_bounds_at_each_edge():
    events = [
        _event(1, "PullRequestEvent", "2026-10-28T00:00:00Z", "opened", 1),
        _event(2, "PullRequestEvent", "2026-10-29T00:00:00Z", "opened", 2),
        _event(3, "PullRequestEvent", "2026-10-30T00:00:00Z", "opened", 3),
        _event(4, "PullRequestEvent", "2026-10-31T00:00:00Z", "opened", 4),
    ]
    pulls = [
        _pull(1, "2026-10-28T00:00:00Z"),
        _pull(2, "2026-10-29T00:00:00Z"),
        _pull(3, "2026-10-30T00:00:00Z"),
        _pull(4, "2026-10-31T00:00:00Z"),
    ]
    out = R.recount(_snapshot(events, pulls), AS_OF, USER, REPO)
    assert out["prs"]["periods"] == [1, 1, 1]
    assert out["prs"]["total"] == 3
    assert out["prs"]["open"] == 1


def test_open_hour_excluded_and_reported():
    events = [_event(1, "PullRequestEvent", "2026-10-31T00:02:00Z", "opened", 9)]
    pulls = [_pull(9, "2026-10-31T00:02:00Z")]
    out = R.recount(_snapshot(events, pulls), AS_OF, USER, REPO)
    assert out["prs"]["periods"] == [0, 0, 0]
    assert out["prs"]["total"] == 0
    assert out["prs"]["open"] == 1


def test_merged_closed_reopened_count_nothing():
    events = [
        _event(1, "PullRequestEvent", "2026-10-29T01:00:00Z", "merged", 1),
        _event(2, "PullRequestEvent", "2026-10-29T02:00:00Z", "closed", 2),
        _event(3, "PullRequestEvent", "2026-10-29T03:00:00Z", "reopened", 3),
    ]
    out = R.recount(_snapshot(events), AS_OF, USER, REPO)
    assert out["prs"]["total"] == 0
    assert out["prs"]["periods"] == [0, 0, 0]


def test_other_actor_and_author_excluded():
    events = [
        _event(1, "PushEvent", "2026-10-29T01:00:00Z"),
        _event(2, "PullRequestEvent", "2026-10-29T02:00:00Z", "opened", 5),
    ]
    events[0]["actor"] = "someone-else"
    events[0]["push_id"] = 7
    events[0]["head"] = "a" * 40
    events[0]["before"] = "b" * 40
    events[1]["actor"] = "someone-else"
    pulls = [_pull(5, "2026-10-29T02:00:00Z", author="someone-else")]
    out = R.recount(_snapshot(events, pulls), AS_OF, USER, REPO)
    assert out["prs"]["total"] == 0
    assert out["pushes"]["total"] == 0


def test_named_repo_per_repo_not_doubled():
    events = [
        _event(n, "PullRequestEvent", "2026-10-29T01:00:00Z", "opened", n)
        for n in range(1, 19)
    ]
    pulls = [_pull(n, "2026-10-29T01:00:00Z") for n in range(1, 19)]
    out = R.recount(_snapshot(events, pulls), AS_OF, USER, REPO)
    assert out["prs"]["total"] == 18
    named = [r for r in out["prs"]["per_repo"] if r["repo"] == REPO]
    assert len(named) == 1
    assert named[0]["prs"] == 18


def test_feed_only_other_repo_open_hour_counted():
    events = [
        _event(1, "PullRequestEvent", "2026-10-31T00:02:00Z", "opened", 9),
    ]
    events[0]["repo"] = "synthetic-owner/synthetic-other"
    out = R.recount(_snapshot(events), AS_OF, USER, REPO)
    assert out["prs"]["periods"] == [0, 0, 0]
    assert out["prs"]["total"] == 0
    assert out["prs"]["open"] == 1


def test_count_between_none_when_fetched_before_end():
    events = [_event(1, "PullRequestEvent", "2026-10-29T01:00:00Z", "opened", 1)]
    pulls = [_pull(1, "2026-10-29T01:00:00Z")]
    snap = _snapshot(events, pulls)
    snap["fetched_at"] = "2026-10-28T00:00:00Z"
    start = R.parse_instant("2026-10-28T00:00:00+00:00")
    end = R.parse_instant("2026-10-31T00:00:00+00:00")
    assert R.count_between(snap, USER, REPO, start, end) is None
    mid = R.parse_instant("2026-10-29T00:00:00+00:00")
    assert R.count_between(snap, USER, REPO, start, mid) is None


def test_count_between_none_when_feed_starts_after_bounds():
    events = [_event(1, "PullRequestEvent", "2026-10-30T01:00:00Z", "opened", 1)]
    pulls = [_pull(1, "2026-10-30T01:00:00Z")]
    snap = _snapshot(events, pulls)
    snap["fetched_at"] = "2026-10-31T00:10:00Z"
    snap["coverage"]["events"] = {
        "rows": 300,
        "oldest": "2026-10-30T01:00:00Z",
        "newest": "2026-10-30T01:00:00Z",
        "stop": "page_cap",
    }
    start = R.parse_instant("2026-10-28T00:00:00+00:00")
    end = R.parse_instant("2026-10-31T00:00:00+00:00")
    assert R.count_between(snap, USER, REPO, start, end) is None


def test_parse_instant_carries_no_value():
    import pytest

    with pytest.raises(ValueError) as exc:
        R.parse_instant("2026-10-31T00:00:00")
    assert "2026" not in str(exc.value)


def test_identity_is_repo_and_number_not_event_id():
    events = [
        _event(11, "PullRequestEvent", "2026-10-29T01:00:00Z", "opened", 6),
        _event(12, "PullRequestEvent", "2026-10-29T02:00:00Z", "opened", 6),
        _event(13, "PullRequestEvent", "2026-10-29T03:00:00Z", "opened", 7),
    ]
    events[2]["repo"] = "synthetic-owner/synthetic-other"
    pulls = [_pull(6, "2026-10-29T01:00:00Z"), _pull(7, "2026-10-29T03:00:00Z")]
    out = R.recount(_snapshot(events, pulls), AS_OF, USER, REPO)
    assert out["prs"]["feed_total"] == 1
    assert out["prs"]["total"] == 3
    assert [d["metric"] for d in out["prs"]["duplicates"]] == ["prs"]
    push_a = _event(21, "PushEvent", "2026-10-29T04:00:00Z")
    push_a.update({"push_id": 77, "head": "c" * 40, "before": "d" * 40})
    push_b = _event(22, "PushEvent", "2026-10-29T05:00:00Z")
    push_b.update({"push_id": 77, "head": "c" * 40, "before": "d" * 40})
    out = R.recount(_snapshot([push_a, push_b]), AS_OF, USER, REPO)
    assert out["pushes"]["total"] == 1
    assert [d["metric"] for d in out["pushes"]["duplicates"]] == ["pushes"]
    push_c = _event(23, "PushEvent", "2026-10-29T06:00:00Z")
    push_c.update({"push_id": None, "head": "e" * 40, "before": "f" * 40})
    push_d = _event(24, "PushEvent", "2026-10-29T07:00:00Z")
    push_d.update({"push_id": None, "head": "e" * 40, "before": "f" * 40})
    out = R.recount(_snapshot([push_c, push_d]), AS_OF, USER, REPO)
    assert out["pushes"]["total"] == 1
    assert [d["metric"] for d in out["pushes"]["duplicates"]] == ["pushes"]
