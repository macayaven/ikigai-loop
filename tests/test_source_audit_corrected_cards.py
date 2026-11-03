"""Ticket 20b: corrected cards on the read-only audit paths.

Made-up rows only. Each test fails on the pre-ticket tree for the reason
its docstring names, and passes once the per-card join lands.
"""

import json
import sqlite3

from source_audit import compare as C
from source_audit import export as E
from source_audit import parse as P

SUBJECT = "synthetic-subject-1"
AS_OF = "2026-10-31T00:05:00+00:00"
SLOT = "2026-10-31T00:30:00+00:00"
WINDOW = ("2026-10-28T00:00:00+00:00", "2026-10-31T00:00:00+00:00")
SINCE = "First card, last 24h: 8 pushes + PRs."

SLOT_CARD = "syn-card-slot-1"
FIX_CARD = "syn-card-fix-2"

T9 = "Pull requests rose from 0 in prior to 9 in last."
T8 = "Pull requests rose from 0 in prior to 8 in last."
T7 = "Pull requests rose from 0 in prior to 7 in last."
TU = "Pull requests rose from 0 in earlier to 0 in prior."
DELTA = "Pull requests increased by 2 in the last day."


def _snapshot():
    """Eight made-up pull requests, all in last, none in the other periods."""
    times = [
        f"2026-10-30T{h:02d}:{m:02d}:00Z"
        for h, m in [
            (1, 0),
            (1, 10),
            (1, 20),
            (1, 30),
            (2, 0),
            (2, 10),
            (2, 20),
            (2, 30),
        ]
    ]
    events, pulls = [], []
    for n, created in enumerate(times, 1):
        events.append(
            {
                "id": str(n),
                "type": "PullRequestEvent",
                "repo": "synthetic-owner/synthetic-repo",
                "actor": "synthetic-user",
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
                "repo": "synthetic-owner/synthetic-repo",
                "actor": "synthetic-user",
                "created_at": created,
                "action": "merged",
                "pr_number": n,
                "push_id": None,
                "head": None,
                "before": None,
            }
        )
        pulls.append({"number": n, "created_at": created, "author": "synthetic-user"})
    return {
        "fetched_at": "2026-10-31T07:00:00Z",
        "user": "synthetic-user",
        "repo": "synthetic-owner/synthetic-repo",
        "events": events,
        "pulls": pulls,
        "activity": [],
        "coverage": {
            "events": {
                "rows": len(events),
                "oldest": times[0],
                "newest": times[-1],
                "stop": "last_page",
            },
            "pulls": {
                "rows": len(pulls),
                "oldest": times[0],
                "newest": times[-1],
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


def _stored():
    """Stored numbers that agree with the recount: 0, 0, 8."""
    return json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 0,
            "period.last.prs": 8,
            "github.pr.count": 8,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
            "period.last.pushes": 0,
        }
    )


def _refs(prior, last):
    return [
        {"metric_id": "period.prior.prs", "value": prior},
        {"metric_id": "period.last.prs", "value": last},
    ]


_CLAIM_N = [0]


def _claim(text, refs=None):
    _CLAIM_N[0] += 1
    return {
        "id": f"syn-claim-{_CLAIM_N[0]}",
        "text": text,
        "fact_ids": [],
        "metric_refs": refs or [],
    }


def _briefing(overall, since=()):
    return json.dumps(
        {
            "sections": [
                {
                    "type": "overall_state",
                    "claims": [_claim(t, r) for t, r in overall],
                },
                {
                    "type": "since_last",
                    "claims": [_claim(t) for t in since],
                },
            ]
        }
    )


def _chart():
    return json.dumps(
        {"pushes": {"label": "synthetic chart", "earlier": 0, "prior": 0, "last": 8}}
    )


def _card_payload(statements, replaces=None):
    payload = {
        "slot": SLOT,
        "since_line": SINCE,
        "proposals": [{"letter": "A"}],
        "statements": list(statements),
    }
    if replaces is not None:
        payload["replaces_card_id"] = replaces
    return json.dumps(payload)


def _db(
    path,
    rows,
    slot_statements,
    facts,
    corrected_statements=None,
    voice="proof",
    extra_voice_texts=(),
):
    """Build a made-up store: one slot card plus an optional corrected card.

    rows: briefing JSONs in insertion order for (p1, p1-reproposal, p2).
    voice: "proof" plants the new_card_id proof row, "empty" leaves the
    table empty, "missing" skips the table, "foreign" names another card.
    """
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT,"
        " source_id TEXT, type TEXT, time TEXT, collected_at TEXT, data TEXT)"
    )
    times = [
        f"2026-10-30T{h:02d}:{m:02d}:00Z"
        for h, m in [
            (1, 0),
            (1, 10),
            (1, 20),
            (1, 30),
            (2, 0),
            (2, 10),
            (2, 20),
            (2, 30),
        ]
    ]
    for n, created in enumerate(times, 1):
        for eid, sid, action in ((f"o{n}", str(n), "opened"),):
            conn.execute(
                "INSERT INTO events VALUES (?, ?, 'github', ?, 'github.pr',"
                " ?, '2026-10-30T05:00:00+00:00', ?)",
                (
                    eid,
                    SUBJECT,
                    sid,
                    created,
                    json.dumps({"counts": {action: 1}}),
                ),
            )
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, snapshot TEXT)"
    )
    conn.execute(
        "INSERT INTO cycles VALUES ('c1', 1, ?, ?, ?)",
        (SUBJECT, AS_OF, _stored()),
    )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, window_start TEXT,"
        " window_end TEXT, statement TEXT, origin TEXT)"
    )
    for statement in facts:
        conn.execute(
            "INSERT INTO facts VALUES ('c1', 1, ?, ?, ?, 'code')",
            (WINDOW[0], WINDOW[1], statement),
        )
    conn.execute(
        "CREATE TABLE proposal_results (profile_id TEXT, cycle_id TEXT,"
        " run INTEGER, kind TEXT, slot TEXT, subject_id TEXT,"
        " briefing_json TEXT, snapshot TEXT)"
    )
    profiles = ["p1", "p1", "p2"][: len(rows)]
    for profile, briefing in zip(profiles, rows):
        conn.execute(
            "INSERT INTO proposal_results VALUES (?, 'c1', 1, 'proposal', ?, ?, ?, ?)",
            (profile, SLOT, SUBJECT, briefing, _stored()),
        )
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT, card_id TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', ?)",
        (SLOT, SLOT_CARD),
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, slot TEXT, subject_id TEXT, as_of TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES (?, ?, ?, ?)",
        (SLOT_CARD, SLOT, SUBJECT, AS_OF),
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES (?, ?, ?)",
        (SLOT_CARD, _card_payload(slot_statements), _chart()),
    )
    conn.execute("CREATE TABLE telegram_cards (card_id TEXT, card_json TEXT)")
    conn.execute("CREATE TABLE telegram_card_charts (card_id TEXT, chart_json TEXT)")
    if corrected_statements is not None:
        conn.execute(
            "INSERT INTO telegram_cards VALUES (?, ?)",
            (
                FIX_CARD,
                _card_payload(corrected_statements, replaces=SLOT_CARD),
            ),
        )
        conn.execute(
            "INSERT INTO telegram_card_charts VALUES (?, ?)", (FIX_CARD, _chart())
        )
    if voice != "missing":
        conn.execute(
            "CREATE TABLE voice_notes (message_id INTEGER, slot TEXT,"
            " status TEXT, operation TEXT, new_card_id TEXT, total_s REAL,"
            " transcript TEXT, question TEXT)"
        )
        if voice == "proof":
            conn.execute(
                "INSERT INTO voice_notes VALUES (5, ?, 'done', 'done', ?,"
                " 1.5, 'syn-transcript', 'syn-question')",
                (SLOT, FIX_CARD),
            )
        elif voice == "foreign":
            conn.execute(
                "INSERT INTO voice_notes VALUES (5, ?, 'done', 'done',"
                " 'syn-card-elsewhere', 1.5, 'syn-transcript', 'syn-question')",
                (SLOT,),
            )
        for n, text in enumerate(extra_voice_texts, 100):
            conn.execute(
                "INSERT INTO voice_notes VALUES (?, ?, 'done', 'done', NULL,"
                " NULL, ?, ?)",
                (n, SLOT, text, text),
            )
    conn.commit()
    return conn


def _run(conn, metric="prs"):
    try:
        return C.run_compare(
            _snapshot(), conn, metric=metric, subject=SUBJECT, card="latest"
        )
    finally:
        conn.close()


def _slot_rows():
    """The two slot-run briefings: texts say 9 and 0/0, refs say 8 and 0/0."""
    slot_p1 = _briefing([(T9, _refs(0, 8))], since=[DELTA])
    slot_p2 = _briefing(
        [
            (
                TU,
                [
                    {"metric_id": "period.earlier.prs", "value": 0},
                    {"metric_id": "period.prior.prs", "value": 0},
                ],
            )
        ],
        since=[DELTA],
    )
    return slot_p1, slot_p2


def _export_text(res):
    return json.dumps(res["export"], sort_keys=True)


def _two_card_db(tmp_path, name, repro_text=T8, repro_refs=None, voice="proof"):
    slot_p1, slot_p2 = _slot_rows()
    repro = _briefing(
        [(repro_text, repro_refs if repro_refs is not None else _refs(0, 8))],
        since=[DELTA],
    )
    conn = _db(
        str(tmp_path / name),
        [slot_p1, repro, slot_p2],
        [T9, TU, DELTA],
        [T8, TU],
        corrected_statements=[repro_text, TU, DELTA],
        voice=voice,
    )
    return conn


def test_two_cards_each_get_a_stage4_line(tmp_path):
    """Stage 4 reads the slot card against the re-proposal row on main."""
    res = _run(_two_card_db(tmp_path, "two.db"))
    assert res["verdicts"]["prs"] == "PASS", res["lines"]
    assert res["exit"] == 0
    fourths = [row for row in res["stages"]["prs"][3:]]
    assert [row.get("card") for row in fourths] == [1, 2]
    assert all(row["status"] == "match" for row in fourths), fourths
    assert res["deltas_not_audited"] == 2
    assert res["delta_codes"] == ["CARD_DELTA_NOT_AUDITED"]
    blob = "\n".join(res["lines"]) + _export_text(res)
    assert SLOT_CARD not in blob and FIX_CARD not in blob
    assert " card=1" in blob and " card=2" in blob


def test_two_cards_all_metrics_get_per_card_lines(tmp_path):
    """Every metric gets one stage 4 line per card in delivery order."""
    res = _run(_two_card_db(tmp_path, "all.db"), metric="all")
    for metric in ("prs", "pushes", "pushes_plus_prs"):
        fourths = [row for row in res["stages"][metric][3:]]
        assert len(fourths) == 2, (metric, fourths)
        assert [row.get("card") for row in fourths] == [1, 2]
    assert [e["verdict"] for e in res["card_verdicts"]["prs"]] == ["PASS", "PASS"]
    assert [e["card"] for e in res["card_verdicts"]["prs"]] == [1, 2]
    assert [e["verdict"] for e in res["card_verdicts"]["pushes"]] == [
        "INCOMPLETE",
        "INCOMPLETE",
    ]
    assert [e["card"] for e in res["card_verdicts"]["pushes"]] == [1, 2]
    assert [e["verdict"] for e in res["card_verdicts"]["pushes_plus_prs"]] == [
        "INCOMPLETE",
        "INCOMPLETE",
    ]
    assert [e["card"] for e in res["card_verdicts"]["pushes_plus_prs"]] == [1, 2]
    assert "PASS" not in [e["verdict"] for e in res["card_verdicts"]["pushes_plus_prs"]]
    cards = [
        entry.get("card") for entry in res["export"]["stages"] if entry["stage"] == "4"
    ]
    assert cards == [1, 1, 1, 2, 2, 2] or cards == [1, 2] * 3, cards


def test_wrong_number_on_corrected_card_only(tmp_path):
    """Only card 2 mismatches, the fold is FAIL, and card 2 is named."""
    res = _run(_two_card_db(tmp_path, "bad2.db", repro_text=T7, repro_refs=_refs(0, 7)))
    assert res["verdicts"]["prs"] == "FAIL", res["lines"]
    assert res["exit"] == 1
    fourths = [row for row in res["stages"]["prs"][3:]]
    assert [row.get("card") for row in fourths] == [1, 2]
    assert fourths[0]["status"] == "match", fourths[0]
    assert fourths[1]["status"] == "mismatch", fourths[1]
    assert "CARD_NUMBER_WRONG" in fourths[1]["codes"]
    named = [
        entry for entry in res["identifiers"]["statements"] if entry.get("card") == 2
    ]
    assert named, res["identifiers"]["statements"]
    assert all(entry["metric"] == "prs" for entry in named)


def test_no_proof_row_means_no_second_card(tmp_path):
    """Without a voice proof row the corrected card is not delivered.

    The guard half (no card key anywhere) passes on the pre-ticket tree;
    the PASS half fails there because the slot card is read against the
    re-proposal row.
    """
    for voice in ("empty", "foreign", "missing"):
        res = _run(_two_card_db(tmp_path, f"noproof-{voice}.db", voice=voice))
        assert res["verdicts"]["prs"] == "PASS", (voice, res["lines"])
        assert res["exit"] == 0
        assert len(res["stages"]["prs"]) == 4, voice
        assert all("card" not in row for row in res["stages"]["prs"]), voice
        assert all("card" not in row for row in res["export"]["stages"]), voice
        assert all("card" not in row for row in res["export"]["verdicts"]), voice
        assert res["identifiers"]["statements"] == [] or all(
            "card" not in entry for entry in res["identifiers"]["statements"]
        ), voice
        blob = "\n".join(res["lines"]) + _export_text(res)
        assert " card=" not in blob, voice
        assert SLOT_CARD not in blob and FIX_CARD not in blob, voice


def test_each_card_joins_its_own_rows(tmp_path):
    """A card built from the earlier row joins the earlier row.

    The later-built half passes on the pre-ticket tree; the earlier-built
    half fails there because results_at always keeps the later row.
    """
    slot_p1, slot_p2 = _slot_rows()
    repro = _briefing([(T8, _refs(0, 8))], since=[DELTA])
    later = _db(
        str(tmp_path / "later.db"),
        [slot_p1, repro, slot_p2],
        [T8, TU, DELTA],
        [T8, TU],
    )
    res = _run(later)
    assert res["verdicts"]["prs"] == "PASS", res["lines"]
    earlier = _db(
        str(tmp_path / "earlier.db"),
        [slot_p1, repro, slot_p2],
        [T9, TU, DELTA],
        [T8, TU],
    )
    res = _run(earlier)
    assert res["verdicts"]["prs"] == "PASS", res["lines"]
    assert res["stages"]["prs"][3]["status"] == "match", res["stages"]["prs"][3]


def test_by_sentences_are_unparsed(tmp_path):
    """A count brought in by straight after rose/fell is unparsed.

    The parser half fails on the pre-ticket tree because the no-period
    form parses as the total; the stage half fails there with
    CARD_NUMBER_WRONG instead of FACT_UNPARSED.
    """
    for metric in ("prs", "pushes"):
        noun = "Pull requests" if metric == "prs" else "Pushes"
        for word in (
            "rose",
            "fell",
            "increased",
            "decreased",
            "grew",
            "dropped",
            "climbed",
            "declined",
        ):
            assert (
                P.parse_statement(f"{noun} {word} by 2.", metric)["kind"] == "unparsed"
            ), (metric, word)
            assert (
                P.parse_statement(f"{noun} {word} by three in prior.", metric)["kind"]
                == "unparsed"
            ), (metric, word)
        assert P.parse_statement(f"{noun} went up by 2.", metric)["kind"] == "unparsed"
        assert (
            P.parse_statement(f"{noun} went up by 2 in last.", metric)["kind"]
            == "unparsed"
        )
        assert (
            P.parse_statement(f"{noun} went down by three.", metric)["kind"]
            == "unparsed"
        )
        assert (
            P.parse_statement(f"{noun} went down by three in prior.", metric)["kind"]
            == "unparsed"
        )
    assert (
        P.parse_statement("Pull requests rose from 0 in earlier to 1 in prior.", "prs")[
            "kind"
        ]
        == "parsed"
    )
    assert P.parse_statement("8 pull requests.", "prs")["kind"] == "parsed"
    assert P.parse_statement("Pull requests increased to 8.", "prs")["kind"] == "parsed"
    assert (
        P.parse_statement("Pushes fell from 1 in prior to 0 in last.", "pushes")["kind"]
        == "parsed"
    )
    by_text = "Pull requests increased by 2."
    briefing = _briefing([(by_text, [])])
    conn = _db(
        str(tmp_path / "by.db"),
        [briefing],
        [by_text],
        [by_text],
    )
    res = _run(conn)
    assert res["stages"]["prs"][2]["status"] == "unavailable", res["lines"]
    assert res["stages"]["prs"][2]["codes"] == ["FACT_UNPARSED"]
    assert res["stages"]["prs"][3]["status"] == "unavailable", res["lines"]
    assert res["stages"]["prs"][3]["codes"] == ["FACT_UNPARSED"]


def test_export_card_is_an_integer_only(tmp_path):
    """The export takes an int card and refuses a string or null one.

    On the pre-ticket tree the walk has no card key at all, so the int
    case fails there while the refusal cases pass for the wrong reason.
    """
    good = {
        "metric": "prs",
        "stage": "4",
        "status": "match",
        "earlier": 0,
        "prior": 0,
        "last": 8,
        "total": 8,
        "codes": [],
        "card": 2,
    }
    E.check_export(good)
    for bad in ("2", None, True):
        try:
            E.check_export(dict(good, card=bad))
        except E.ExportRefused:
            continue
        raise AssertionError(f"card={bad!r} was not refused")
    res = _run(_two_card_db(tmp_path, "ordinal.db"))
    fourths = [entry for entry in res["export"]["stages"] if entry["stage"] == "4"]
    assert [entry["card"] for entry in fourths] == [1, 2]
    assert all(type(entry["card"]) is int for entry in fourths)
    per_card = [entry for entry in res["export"]["verdicts"] if "card" in entry]
    assert [entry["card"] for entry in per_card] == [1, 2]
    folded = [entry for entry in res["export"]["verdicts"] if "card" not in entry]
    assert folded == [{"metric": "prs", "verdict": "PASS"}]
    solo = _run(_two_card_db(tmp_path, "solo.db", voice="missing"))
    blob = json.dumps(solo["export"], sort_keys=True)
    assert '"card":' not in blob.replace('"card_window":', "")


def test_voice_text_columns_never_reach_output(tmp_path):
    """A canary in any voice text column but new_card_id stays out.

    On the pre-ticket tree nothing reads the table, so this guard passes
    there; it fails only if the new read selects any other column.
    """
    canary = "syn-voice-canary-q1"
    slot_p1, slot_p2 = _slot_rows()
    repro = _briefing([(T8, _refs(0, 8))], since=[DELTA])
    conn = _db(
        str(tmp_path / "canary.db"),
        [slot_p1, repro, slot_p2],
        [T9, TU, DELTA],
        [T8, TU],
        corrected_statements=[T8, TU, DELTA],
        voice="proof",
        extra_voice_texts=[canary],
    )
    res = _run(conn)
    blob = "\n".join(res["lines"]) + _export_text(res)
    assert canary not in blob


AS_OF2A = "2026-10-31T01:05:00+00:00"
AS_OF2B = "2026-10-31T03:05:00+00:00"
TB = "Pull requests rose from 0 in earlier to 8 in prior."
TB2 = "Pull requests fell from 8 in prior to 0 in last."


def _early_refs(earlier, prior):
    return [
        {"metric_id": "period.earlier.prs", "value": earlier},
        {"metric_id": "period.prior.prs", "value": prior},
    ]


def _stored_b():
    """Stored numbers that agree with the recount at AS_OF2B: 0, 8, 0."""
    return json.dumps(
        {
            "period.earlier.prs": 0,
            "period.prior.prs": 8,
            "period.last.prs": 0,
            "github.pr.count": 8,
            "period.earlier.pushes": 0,
            "period.prior.pushes": 0,
            "period.last.pushes": 0,
        }
    )


def _mixed_db(path, rows, slot_statements, corrected_statements, cycles):
    """Build a made-up store whose proposal rows name two cycles.

    rows: list of (profile_id, cycle_id, run, briefing_json) in rowid order.
    cycles: list of (cycle_id, run, as_of, stored_json).
    """
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id TEXT, subject_id TEXT, source TEXT,"
        " source_id TEXT, type TEXT, time TEXT, collected_at TEXT, data TEXT)"
    )
    times = [
        f"2026-10-30T{h:02d}:{m:02d}:00Z"
        for h, m in [
            (1, 0),
            (1, 10),
            (1, 20),
            (1, 30),
            (2, 0),
            (2, 10),
            (2, 20),
            (2, 30),
        ]
    ]
    for n, created in enumerate(times, 1):
        conn.execute(
            "INSERT INTO events VALUES (?, ?, 'github', ?, 'github.pr',"
            " ?, '2026-10-30T05:00:00+00:00', ?)",
            (
                f"o{n}",
                SUBJECT,
                str(n),
                created,
                json.dumps({"counts": {"opened": 1}}),
            ),
        )
    conn.execute(
        "CREATE TABLE cycles (cycle_id TEXT, run INTEGER, subject_id TEXT,"
        " as_of TEXT, snapshot TEXT)"
    )
    for cycle_id, run, as_of, stored in cycles:
        conn.execute(
            "INSERT INTO cycles VALUES (?, ?, ?, ?, ?)",
            (cycle_id, run, SUBJECT, as_of, stored),
        )
    conn.execute(
        "CREATE TABLE facts (cycle_id TEXT, run INTEGER, window_start TEXT,"
        " window_end TEXT, statement TEXT, origin TEXT)"
    )
    for statement in [T8, TU]:
        conn.execute(
            "INSERT INTO facts VALUES ('c1', 1, ?, ?, ?, 'code')",
            (WINDOW[0], WINDOW[1], statement),
        )
    conn.execute(
        "CREATE TABLE proposal_results (profile_id TEXT, cycle_id TEXT,"
        " run INTEGER, kind TEXT, slot TEXT, subject_id TEXT,"
        " briefing_json TEXT, snapshot TEXT)"
    )
    for profile, cycle_id, run, briefing in rows:
        conn.execute(
            "INSERT INTO proposal_results VALUES (?, ?, ?, 'proposal', ?, ?, ?, ?)",
            (profile, cycle_id, run, SLOT, SUBJECT, briefing, _stored()),
        )
    conn.execute(
        "CREATE TABLE slot_ledger (slot TEXT, step TEXT, outcome TEXT, card_id TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_ledger VALUES (?, 'send', 'delivered', ?)",
        (SLOT, SLOT_CARD),
    )
    conn.execute(
        "CREATE TABLE slot_cards (card_id TEXT, slot TEXT, subject_id TEXT, as_of TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_cards VALUES (?, ?, ?, ?)",
        (SLOT_CARD, SLOT, SUBJECT, AS_OF),
    )
    conn.execute(
        "CREATE TABLE slot_card_payloads (card_id TEXT, card_json TEXT,"
        " chart_json TEXT)"
    )
    conn.execute(
        "INSERT INTO slot_card_payloads VALUES (?, ?, ?)",
        (SLOT_CARD, _card_payload(slot_statements), _chart()),
    )
    conn.execute("CREATE TABLE telegram_cards (card_id TEXT, card_json TEXT)")
    conn.execute("CREATE TABLE telegram_card_charts (card_id TEXT, chart_json TEXT)")
    conn.execute(
        "INSERT INTO telegram_cards VALUES (?, ?)",
        (FIX_CARD, _card_payload(corrected_statements, replaces=SLOT_CARD)),
    )
    conn.execute("INSERT INTO telegram_card_charts VALUES (?, ?)", (FIX_CARD, _chart()))
    conn.execute(
        "CREATE TABLE voice_notes (message_id INTEGER, slot TEXT,"
        " status TEXT, operation TEXT, new_card_id TEXT, total_s REAL,"
        " transcript TEXT, question TEXT)"
    )
    conn.execute(
        "INSERT INTO voice_notes VALUES (5, ?, 'done', 'done', ?,"
        " 1.5, 'syn-transcript', 'syn-question')",
        (SLOT, FIX_CARD),
    )
    conn.commit()
    return conn


def test_mixed_cycle_slot_card_still_audited(tmp_path):
    """The own-rows pick runs even when the latest-row join is ambiguous.

    The re-proposal row sits on a second cycle while the other profile's
    row stays on the slot's cycle. On the current tree the pick returns
    CARD_CYCLE_AMBIGUOUS before the own-rows pick runs, so stage 4 is
    ambiguous for the whole slot and the corrected card is never audited.
    After: the slot card's stage 4 runs on its own rows and matches, and
    the corrected card's stage 4 is unavailable with CARD_CYCLE_AMBIGUOUS.
    """
    slot_p1 = _briefing([(T9, _refs(0, 8))], since=[DELTA])
    slot_p2 = _briefing([(TU, _early_refs(0, 0))], since=[DELTA])
    repro = _briefing([(T8, _refs(0, 8))], since=[DELTA])
    conn = _mixed_db(
        str(tmp_path / "mixed.db"),
        [
            ("p1", "c1", 1, slot_p1),
            ("p2", "c1", 1, slot_p2),
            ("p1", "c2", 1, repro),
        ],
        [T9, TU, DELTA],
        [T8, TU, DELTA],
        [("c1", 1, AS_OF, _stored()), ("c2", 1, AS_OF2A, _stored())],
    )
    res = _run(conn)
    fourths = [row for row in res["stages"]["prs"][3:]]
    assert [row.get("card") for row in fourths] == [1, 2], fourths
    assert fourths[0]["status"] == "match", fourths[0]
    assert fourths[1]["status"] == "unavailable", fourths[1]
    assert fourths[1]["codes"] == ["CARD_CYCLE_AMBIGUOUS"], fourths[1]


def test_mixed_cycle_corrected_card_runs_at_its_cycle(tmp_path):
    """Both of the corrected card's rows sit on the second cycle.

    On the current tree the whole slot is CARD_CYCLE_AMBIGUOUS and the
    corrected card is never audited. After: its stage 4 runs at the second
    cycle's instant and matches.
    """
    slot_p1 = _briefing([(T9, _refs(0, 8))], since=[DELTA])
    slot_p2 = _briefing([(TU, _early_refs(0, 0))], since=[DELTA])
    repro_p1 = _briefing([(TB, _early_refs(0, 8))], since=[DELTA])
    repro_p2 = _briefing([(TB2, _refs(8, 0))], since=[DELTA])
    conn = _mixed_db(
        str(tmp_path / "mixed2.db"),
        [
            ("p1", "c1", 1, slot_p1),
            ("p2", "c2", 1, repro_p2),
            ("p1", "c2", 1, repro_p1),
            ("p2", "c1", 1, slot_p2),
        ],
        [T9, TU, DELTA],
        [TB, TB2, DELTA],
        [("c1", 1, AS_OF, _stored()), ("c2", 1, AS_OF2B, _stored_b())],
    )
    res = _run(conn)
    fourths = [row for row in res["stages"]["prs"][3:]]
    assert [row.get("card") for row in fourths] == [1, 2], fourths
    assert fourths[0]["status"] == "match", fourths[0]
    assert fourths[1]["status"] == "match", fourths[1]
    assert fourths[1]["prior"] == 8 and fourths[1]["last"] == 0, fourths[1]
