"""Ticket 15b, Step 5: R4 scorer tests (D42-D44).

Hand-written R4 rows only: no model, no network, no filesystem beyond
the rows passed in.
"""

from __future__ import annotations

import json
from typing import Any

from evals import r4_score


def _draft(
    pick: str,
    overall: list[tuple[list[str], list[str], str]],
    *,
    working: list[tuple[list[str], list[str], str]] | None = None,
    not_working: list[tuple[list[str], list[str], str]] | None = None,
) -> str:
    def _claims(
        items: list[tuple[list[str], list[str], str]],
    ) -> list[dict[str, Any]]:
        return [
            {"text": text, "fact_ids": list(fact_ids), "metric_refs": list(refs)}
            for fact_ids, refs, text in items
        ]

    return json.dumps(
        {
            "commitment_id": pick,
            "overall_state": _claims(overall),
            "working": _claims(working or []),
            "not_working": _claims(not_working or []),
            "since_last": [],
        }
    )


def _row(
    case_id: str,
    arm: str,
    changed_fact: str,
    base_raw: str,
    arm_raw: str | None,
    *,
    profile: str = "builder",
    drawn: bool = True,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "arm": arm,
        "changed_fact": changed_fact,
        "profile": profile,
        "pair_id": "D1",
        "repeat": 1,
        "execution": 1,
        "start_seq": 1,
        "drawn": drawn,
        "unavailable_reason": unavailable_reason,
        "base_prompt_hash": "p" * 64,
        "base_draft_json": base_raw,
        "attempts": [{"raw_text": arm_raw or ""}],
    }


def _base() -> str:
    return _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes carry the week here")],
    )


def _case_rows(
    case_id: str, base_raw: str, cited_raw: str | None, control_raw: str | None
) -> list[dict[str, Any]]:
    return [
        _row(case_id, "cited", "f1", base_raw, cited_raw),
        _row(case_id, "control", "f2", base_raw, control_raw),
    ]


def test_digit_only_change_scores_unchanged_on_all_three() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes fell from 2 in prior to 0 in last")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, regen))
    case = score.cases["r4-01"]
    assert case.cited.changed_pick is False
    assert case.cited.changed_whole is False
    assert case.cited.changed_reason is False
    assert score.pick_rate.verdict == "not held"


def test_reworded_same_citations_scores_unchanged() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "The week rests on pushes entirely")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, regen))
    assert score.whole_rate.cited_changed == 0
    assert score.reason_rate.cited_changed == 0


def test_added_citation_changes_whole_but_not_reason_or_pick() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes carry the week here")],
        working=[(["f2"], [], "Programming adds context here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_whole is True
    assert case.cited.changed_reason is False
    assert case.cited.changed_pick is False


def test_section_move_changes_whole_but_not_reason() -> None:
    base = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes carry the week here")],
        working=[(["f2"], [], "Programming adds context here")],
    )
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes carry the week here")],
        not_working=[(["f2"], [], "Programming adds context here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_whole is True
    assert case.cited.changed_reason is False


def test_first_overall_swap_changes_reason() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f2"], [], "Programming carries the week here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_reason is True
    assert case.cited.changed_whole is True


def test_pick_only_change_leaves_both_signatures() -> None:
    base = _base()
    regen = _draft(
        "b-read",
        [(["f1"], ["period.last.pushes"], "Pushes carry the week here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_pick is True
    assert case.cited.changed_whole is False
    assert case.cited.changed_reason is False


def test_whole_signature_changed_by_metric_ref_only() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.prior.pushes"], "Pushes fell from 2 in prior to 0 in last")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_whole is True
    assert case.control.changed_whole is False


def test_whole_signature_counts_duplicate_claims_as_multiset() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [
            (["f1"], ["period.last.pushes"], "Pushes carry the week here"),
            (["f1"], ["period.last.pushes"], "Pushes carry the week here"),
        ],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_whole is True
    assert case.cited.changed_reason is False
    assert case.cited.changed_pick is False


def test_reason_signature_reads_first_overall_claim() -> None:
    first = (["f1"], ["period.last.pushes"], "Pushes carry the week here")
    second = (["f2"], [], "Programming fills the day here")
    later_changed = (["f3"], [], "Video fills the evening here")
    first_changed = (["f2"], [], "Programming carries the week here")
    base = _draft("b-ship", [first, second])
    same_first = _draft("b-ship", [first, later_changed])
    diff_first = _draft("b-ship", [first_changed, second])
    rows = _case_rows("r4-01", base, same_first, base)
    rows += _case_rows("r4-02", base, diff_first, base)
    score = r4_score.score_rows(rows)
    assert score.cases["r4-01"].cited.changed_reason is False
    assert score.cases["r4-01"].cited.changed_whole is True
    assert score.cases["r4-02"].cited.changed_reason is True


def test_reason_signature_changed_by_metric_ref_only() -> None:
    base = _base()
    regen = _draft(
        "b-ship",
        [(["f1"], ["period.prior.pushes"], "Pushes carry the week here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, regen, base))
    case = score.cases["r4-01"]
    assert case.cited.changed_reason is True
    assert case.cited.changed_whole is True


def test_noise_floor_over_all_unordered_pairs_of_four_draws() -> None:
    same_text = _draft("b-ship", [(["f1"], [], "Pushes hold the week instead")])
    same_cited = _draft("b-ship", [(["f1"], [], "Pushes carry the week")])
    pick_moved = _draft("b-read", [(["f1"], [], "Pushes carry the week")])
    cites_moved = _draft("b-ship", [(["f2"], [], "Programming fills the day")])
    r3_rows = [
        _r3_floor_row("D1", "base", 1, same_cited),
        _r3_floor_row("D1", "base", 2, same_text),
        _r3_floor_row("D1", "base", 3, pick_moved),
        _r3_floor_row("D2", "base", 1, cites_moved),
    ]
    floor = r4_score.noise_floor(r3_rows)
    assert floor["builder"]["draws"] == 4
    assert floor["builder"]["n"] == 6
    assert floor["builder"]["pick_changed"] == 3
    assert floor["builder"]["whole_changed"] == 3
    assert floor["builder"]["reason_changed"] == 3
    assert floor["pooled"]["n"] == 6


def test_cites_changed_fact_column_on_both_arms() -> None:
    base = _base()
    cited_regen = _draft(
        "b-ship",
        [(["f1"], ["period.last.pushes"], "Pushes fell to zero here")],
    )
    control_regen = _draft(
        "b-ship",
        [(["f2"], [], "Programming carries the week here")],
    )
    score = r4_score.score_rows(_case_rows("r4-01", base, cited_regen, control_regen))
    case = score.cases["r4-01"]
    assert case.cited.cites_changed is True
    assert case.control.cites_changed is True
    plain = _draft("b-ship", [(["f3"], [], "Video fills the evening here")])
    score = r4_score.score_rows(_case_rows("r4-02", base, plain, plain))
    assert score.cases["r4-02"].cited.cites_changed is False
    assert score.cases["r4-02"].control.cites_changed is False


def test_equal_rates_render_the_registered_sentence() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, moved)
    rows += _case_rows("r4-02", base, base, base)
    score = r4_score.score_rows(rows)
    assert (score.pick_rate.cited_changed, score.pick_rate.cited_n) == (1, 2)
    assert (score.pick_rate.control_changed, score.pick_rate.control_n) == (1, 2)
    text = r4_score.render_r4(score, _info(), None, _report())
    assert text.count("no differential sensitivity detected") == 3
    assert "decoration" not in text


def test_cited_moves_more_often_holds() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, base)
    rows += _case_rows("r4-02", base, base, base)
    score = r4_score.score_rows(rows)
    assert score.pick_rate.verdict == "held"
    assert score.whole_rate.verdict == "not held"
    text = r4_score.render_r4(score, _info(), None, _report())
    assert "pick: 1/2 cited vs 0/2 control" in text


def test_unscorable_arms_are_counted_and_excluded() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, base)
    rows += _case_rows("r4-02", base, "{not json", base)
    rows.append(
        _row(
            "r4-03",
            "cited",
            "f1",
            base,
            None,
            drawn=False,
            unavailable_reason="timeout",
        )
    )
    rows.append(_row("r4-03", "control", "f2", base, base))
    score = r4_score.score_rows(rows)
    assert score.pick_rate.cited_n == 1
    assert score.pick_rate.control_n == 3
    assert score.unscorable == ["r4-02 cited"]
    assert score.unavailable_by_reason == {"timeout": 1}
    text = r4_score.render_r4(score, _info(), None, _report())
    assert "r4-02 cited" in text
    assert "unscorable: 1" in text


def test_two_drawn_executions_first_stands_and_count_prints() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    first = _row("r4-01", "cited", "f1", base, moved)
    second = dict(_row("r4-01", "cited", "f1", base, base), execution=2)
    rows = [second, first, _row("r4-01", "control", "f2", base, base)]
    score = r4_score.score_rows(rows)
    assert score.multi_drawn_slots == 1
    case = score.cases["r4-01"]
    assert case.cited.pick == "b-read"
    assert case.cited.changed_pick is True
    text = r4_score.render_r4(score, _info(), None, _report())
    assert "- slots with more than one drawn execution: 1" in text


def test_noise_floor_counts_every_same_profile_pair() -> None:
    first = _draft("b-ship", [(["f1"], [], "Pushes carry the week")])
    second = _draft("b-read", [(["f1"], [], "Pushes carry the week")])
    third = _draft("b-ship", [(["f2"], [], "Programming fills the day")])
    r3_rows = [
        _r3_floor_row("D1", "base", 1, first),
        _r3_floor_row("D1", "base", 2, second),
        _r3_floor_row("D1", "base", 3, third),
    ]
    floor = r4_score.noise_floor(r3_rows)
    builder = floor["builder"]
    assert builder["n"] == 3
    assert builder["pick_changed"] == 2
    assert builder["whole_changed"] == 2
    assert builder["reason_changed"] == 2
    assert floor["pooled"]["n"] == 3
    text = r4_score.render_r4(r4_score.score_rows([]), _info(), floor, _report())
    assert "Noise floor (new, not registered; decides nothing)" in text
    assert "builder: pick 2/3" in text


def test_noise_floor_skips_unparseable_draws() -> None:
    first = _draft("b-ship", [(["f1"], [], "Pushes carry the week")])
    r3_rows = [
        _r3_floor_row("D1", "base", 1, first),
        _r3_floor_row("D1", "base", 2, "{broken"),
    ]
    floor = r4_score.noise_floor(r3_rows)
    assert floor["builder"]["n"] == 0


def test_missing_r3_rows_render_the_absent_line() -> None:
    text = r4_score.render_r4(r4_score.score_rows([]), _info(), None, None)
    assert text.count("no matching R3 rows") == 2


def _r3_floor_row(pair_id: str, arm: str, repeat: int, raw: str) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "arm": arm,
        "repeat": repeat,
        "execution": 1,
        "drawn": True,
        "attempts": [{"raw_text": raw}],
    }


def test_partial_cases_read_incomplete_with_missing_count() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, base)
    cases = [f"r4-{n:02d}" for n in range(1, 11)]
    score = r4_score.score_rows(rows, cases=cases)
    assert score.missing_slots == 18
    assert score.pick_rate.verdict == "incomplete"
    assert score.whole_rate.verdict == "incomplete"
    assert score.reason_rate.verdict == "incomplete"
    text = r4_score.render_r4(score, _info(), None, _report())
    assert "- pick: 1/1 cited vs 0/1 control -- incomplete (18 missing slots)" in text
    assert "- whole signature:" in text and "-- incomplete" in text
    assert "- reason signature:" in text and "-- incomplete" in text


def test_measure_lines_are_a_list_and_equal_rates_say_not_held() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, moved)
    rows += _case_rows("r4-02", base, base, base)
    score = r4_score.score_rows(rows)
    assert score.missing_slots == 0
    text = r4_score.render_r4(score, _info(), None, _report())
    for name in ("pick", "whole signature", "reason signature"):
        line = next(line for line in text.splitlines() if line.startswith(f"- {name}:"))
        assert "not held" in line
        assert "no differential sensitivity detected" in line
    assert "decoration" not in text


def test_deviation_7_caveat_in_first_person_where_definitions_sit() -> None:
    text = r4_score.render_r4(r4_score.score_rows([]), _info(), None, _report())
    assert "I read equal rates" in text
    assert "insensitive" in text
    assert "relevant control" in text
    assert "generation noise" in text
    assert "don't show what citations do" in text
    assert text.index("I read equal rates") < text.index("## Cases")


def test_cases_section_names_taking_and_combinations() -> None:
    base = _base()
    moved = _draft("b-read", [(["f1"], ["period.last.pushes"], "Pushes here")])
    rows = _case_rows("r4-01", base, moved, base)
    rows += _case_rows("r4-02", base, moved, base)
    text = r4_score.render_r4(r4_score.score_rows(rows), _info(), None, _report())
    assert "first 5 eligible drafts per profile in pair-file order" in text
    assert "f1/f2 x2" in text


def _stack_info(three: int, two: int, timeout_total: int) -> dict[str, Any]:
    info = _info()
    info["three_layer_rows"] = three
    info["two_layer_rows"] = two
    info["timeout_retries"] = timeout_total
    return info


def test_client_stack_two_layer_rows_name_two_layer_stack() -> None:
    base = _base()
    rows = _case_rows("r4-01", base, base, base)
    assert all("timeout_retries" not in row for row in rows)
    text = r4_score.render_r4(
        r4_score.score_rows(rows), _stack_info(0, 2, 0), None, _report()
    )
    assert "LocalRetryClient around MuseExecClient" in text
    assert "TimeoutRetryClient" not in text


def test_client_stack_three_layer_rows_name_three_layer_stack() -> None:
    base = _base()
    rows = _case_rows("r4-01", base, base, base)
    rows[0]["timeout_retries"] = 1
    rows[1]["timeout_retries"] = 0
    text = r4_score.render_r4(
        r4_score.score_rows(rows), _stack_info(2, 0, 1), None, _report()
    )
    assert "TimeoutRetryClient around LocalRetryClient around MuseExecClient" in text
    assert "with 1 timeout retries" in text


def test_client_stack_mixed_rows_name_both_with_counts() -> None:
    base = _base()
    rows = _case_rows("r4-01", base, base, base)
    rows[0]["timeout_retries"] = 3
    text = r4_score.render_r4(
        r4_score.score_rows(rows), _stack_info(1, 1, 3), None, _report()
    )
    assert (
        "TimeoutRetryClient around LocalRetryClient around MuseExecClient "
        "for 1 rows and LocalRetryClient around MuseExecClient for 1 rows" in text
    )
    assert "with 3 timeout retries" in text


def _info() -> dict[str, Any]:
    return {
        "gate_commit": "a" * 40,
        "gate_hash": "b" * 64,
        "prompt_sha256": "c" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commits": ["a" * 40],
        "model": "muse-wonder-1.0",
        "effort": "high",
        "transports": ["muse"],
        "muse_versions": ["muse 1.4.14"],
        "rules_values": [False],
        "r3_file": "r3-rows.jsonl",
        "calls": 4,
        "local_starts": 0,
        "prompt_tokens": 40,
        "completion_tokens": 12,
        "wall_start": "2026-11-03T10:00:00+00:00",
        "wall_end": "2026-11-03T10:02:00+00:00",
    }


def _report() -> dict[str, Any]:
    return {
        "builder": {"eligible": 5, "discards": {}},
        "disconnect": {"eligible": 5, "discards": {}},
    }


def _history_row(
    case_id: str,
    arm: str,
    changed_fact: str,
    base_raw: str,
    arm_raw: str,
    *,
    gate_hash: str,
    prompt_sha: str,
    pairs_sha: str,
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "arm": arm,
        "changed_fact": changed_fact,
        "profile": "builder",
        "pair_id": "D1",
        "repeat": 1,
        "execution": 1,
        "start_seq": 1,
        "drawn": True,
        "unavailable_reason": None,
        "base_prompt_hash": "p" * 64,
        "base_draft_json": base_raw,
        "attempts": [
            {
                "raw_text": arm_raw,
                "codes": [],
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }
        ],
        "model": "m",
        "effort": "high",
        "gate_commit": "e" * 40,
        "gate_hash": gate_hash,
        "prompt_sha256": prompt_sha,
        "pairs_sha256": pairs_sha,
        "tree_commit": "f" * 40,
        "transport": "muse",
        "muse_version": "muse 1.4.14",
        "harness_rules_file": False,
        "local_retries": [],
        "recorded_at": recorded_at,
    }


def _history_file_rows(
    cited_raw: str,
    control_raw: str,
    base_raw: str,
    *,
    gate_hash: str,
    prompt_sha: str,
    recorded_at: str,
) -> list[dict[str, Any]]:
    from evals.r3 import load_pairs as _load_pairs

    _doc_real, pairs_sha = _load_pairs()
    return [
        _history_row(
            "r4-01",
            "cited",
            "f1",
            base_raw,
            cited_raw,
            gate_hash=gate_hash,
            prompt_sha=prompt_sha,
            pairs_sha=pairs_sha,
            recorded_at=recorded_at,
        ),
        _history_row(
            "r4-01",
            "control",
            "f2",
            base_raw,
            control_raw,
            gate_hash=gate_hash,
            prompt_sha=prompt_sha,
            pairs_sha=pairs_sha,
            recorded_at=recorded_at,
        ),
    ]


def _write_history_file(path: Any, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _changed_draft() -> str:
    return _draft(
        "b-read",
        [(["f9"], ["period.last.pushes"], "Something else holds here")],
    )


def test_summary_single_run_is_byte_identical(tmp_path: Any, capsys: Any) -> None:
    from evals import r4 as _r4
    from evals.r3 import load_rows_file as _load_rows
    from evals.r4 import _summary_info as _r4_info

    base = _base()
    rows = _history_file_rows(
        _changed_draft(),
        base,
        base,
        gate_hash="a" * 64,
        prompt_sha="c" * 64,
        recorded_at="2026-11-01T10:00:00+00:00",
    )
    _write_history_file(tmp_path / "one.jsonl", rows)
    absent = tmp_path / "absent.jsonl"
    assert (
        _r4.main(
            ["--summary", "--results-dir", str(tmp_path), "--r3-file", str(absent)]
        )
        == 0
    )
    out = capsys.readouterr().out
    loaded = _load_rows(tmp_path / "one.jsonl")
    assert out == r4_score.render_r4(
        r4_score.score_rows(loaded), _r4_info(loaded, "none"), None, None
    )
    assert "First run" not in out
    assert "Earlier run" not in out


def test_summary_two_runs_newer_full_older_first_with_own_numbers(
    tmp_path: Any, capsys: Any
) -> None:
    from evals import r4 as _r4

    base = _base()
    changed = _changed_draft()
    old = _history_file_rows(
        changed,
        base,
        base,
        gate_hash="a" * 64,
        prompt_sha="c" * 64,
        recorded_at="2026-11-01T10:00:00+00:00",
    )
    new = _history_file_rows(
        base,
        base,
        base,
        gate_hash="b" * 64,
        prompt_sha="d" * 64,
        recorded_at="2026-11-02T10:00:00+00:00",
    )
    _write_history_file(tmp_path / "old.jsonl", old)
    _write_history_file(tmp_path / "new.jsonl", new)
    absent = tmp_path / "absent.jsonl"
    assert (
        _r4.main(
            ["--summary", "--results-dir", str(tmp_path), "--r3-file", str(absent)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.count("# R4 evidence sensitivity") == 1
    assert "First run, gate aaaaaaaaaaaa, prompt cccccccccccc" in out
    assert "Earlier run" not in out
    assert "The headline above is the newest run" in out
    headline_table = out.split("## Per-case table")[1].split("## First run")[0]
    assert "| r4-01 | b-ship | cited | f1 | b-ship | no |" in headline_table
    first_section = out.split("## First run")[1]
    assert "| r4-01 | b-ship | cited | f1 | b-read | yes |" in first_section
    assert "pick: 1/1 cited vs 0/1 control" in first_section


def test_summary_three_runs_labels_middle_earlier(tmp_path: Any, capsys: Any) -> None:
    from evals import r4 as _r4

    base = _base()
    changed = _changed_draft()
    _write_history_file(
        tmp_path / "a.jsonl",
        _history_file_rows(
            changed,
            base,
            base,
            gate_hash="a" * 64,
            prompt_sha="c" * 64,
            recorded_at="2026-11-01T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "b.jsonl",
        _history_file_rows(
            base,
            changed,
            base,
            gate_hash="b" * 64,
            prompt_sha="d" * 64,
            recorded_at="2026-11-02T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "c.jsonl",
        _history_file_rows(
            changed,
            changed,
            base,
            gate_hash="e" * 64,
            prompt_sha="f" * 64,
            recorded_at="2026-11-03T10:00:00+00:00",
        ),
    )
    absent = tmp_path / "absent.jsonl"
    assert (
        _r4.main(
            ["--summary", "--results-dir", str(tmp_path), "--r3-file", str(absent)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "First run, gate aaaaaaaaaaaa, prompt cccccccccccc" in out
    assert "Earlier run, gate bbbbbbbbbbbb, prompt dddddddddddd" in out
    assert out.index("## First run") < out.index("## Earlier run")
    middle_section = out.split("## Earlier run")[1]
    assert "| r4-01 | b-ship | control | f2 | b-read | yes |" in middle_section


def test_summary_identity_renders_one_file_alone(tmp_path: Any, capsys: Any) -> None:
    from evals import r4 as _r4
    from evals.r3 import load_rows_file as _load_rows
    from evals.r4 import _summary_info as _r4_info

    base = _base()
    changed = _changed_draft()
    _write_history_file(
        tmp_path / "old.jsonl",
        _history_file_rows(
            changed,
            base,
            base,
            gate_hash="a" * 64,
            prompt_sha="c" * 64,
            recorded_at="2026-11-01T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "new.jsonl",
        _history_file_rows(
            base,
            base,
            base,
            gate_hash="b" * 64,
            prompt_sha="d" * 64,
            recorded_at="2026-11-02T10:00:00+00:00",
        ),
    )
    assert (
        _r4.main(["--summary", "--results-dir", str(tmp_path), "--identity", "a" * 12])
        == 0
    )
    out = capsys.readouterr().out
    assert "First run" not in out
    assert "Earlier run" not in out
    loaded = _load_rows(tmp_path / "old.jsonl")
    assert "pick: 1/1 cited vs 0/1 control" in out
    assert out == r4_score.render_r4(
        r4_score.score_rows(loaded), _r4_info(loaded, "none"), None, None
    )


def test_closure_heading_and_line_with_field() -> None:
    info = {
        "gate_commit": "a" * 40,
        "gate_hash": "a" * 64,
        "prompt_sha256": "b" * 64,
        "closure_sha256": "c" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commit": "d" * 40,
        "tree_commits": ["d" * 40],
        "model": "m",
        "effort": "high",
    }
    assert r4_score.history_heading(info, first=True) == (
        "First run, gate " + "a" * 12 + ", prompt " + "b" * 12 + ", closure " + "c" * 12
    )
    assert r4_score.closure_line(info) == "- closure " + "c" * 12


def test_closure_heading_and_line_without_field() -> None:
    info = {
        "gate_commit": "a" * 40,
        "gate_hash": "a" * 64,
        "prompt_sha256": "b" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commit": "f" * 40,
        "tree_commits": ["f" * 40],
        "model": "m",
        "effort": "high",
    }
    assert r4_score.history_heading(info, first=True) == (
        "First run, gate "
        + "a" * 12
        + ", prompt "
        + "b" * 12
        + ", closure not recorded; tree "
        + "f" * 12
    )
    assert r4_score.closure_line(info) == "- closure not recorded; tree " + "f" * 12


def test_rendered_identity_carries_closure_line() -> None:
    base = _base()
    cited = _draft("b-ship", [(["f1"], ["period.last.pushes"], "Pushes stay here")])
    rows = _case_rows("r4-01", base, cited, cited)
    full = r4_score.score_rows(rows, cases=["r4-01"])
    text = r4_score.render_r4(full, _info(), None, _report())
    assert "- closure not recorded; tree " + "a" * 12 in text
    info = dict(_info())
    info["closure_sha256"] = "c" * 64
    text = r4_score.render_r4(full, info, None, _report())
    assert "- closure " + "c" * 12 in text
    assert "closure not recorded" not in text
