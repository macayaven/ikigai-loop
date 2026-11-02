"""Ticket 10b Stage 1: red-team runner tests.

Tests first: this file is written before ``evals/redteam.py`` exists, so on
the base it fails at collection (AT10 negative control).

Scope note: Stage 1 built the runner checks; Stage 2 (Step 8) adds the
verbatim-markdown assertions for ``docs/redteam/README.md`` and
``docs/sessions/010b-redteam.md``. Here ``--summary`` is checked by
recomputing every count from the JSON files on disk with this file's own
loops; no runner counting helper is imported or called for that check.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals import redteam

ROOT = Path(__file__).resolve().parents[1]
REDTEAM_DIR = ROOT / "docs" / "redteam"

ATTACK_ROW_FIELDS = frozenset(
    {"id", "target", "predicted_passes", "passed", "codes", "raised"}
)
SENTENCE_ROW_FIELDS = frozenset({"id", "passed", "codes", "raised"})
REVIEW_ROW_FIELDS = frozenset({"id", "passed", "codes", "raised"})
FROZEN_FIELDS = frozenset(
    {
        "gate_commit",
        "gate_tree",
        "gate_files_sha256",
        "gate_dirty",
        "input_sha256",
        "rows",
    }
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_input(name: str, tmp_path: Path) -> Path:
    dest = tmp_path / name
    dest.write_bytes((REDTEAM_DIR / name).read_bytes())
    return dest


def _run(*args: str) -> int:
    return redteam.main(list(args))


# ---------------------------------------------------------------------------
# Host briefing and row semantics.
# ---------------------------------------------------------------------------


def test_host_passes_with_known_good_claim() -> None:
    context = redteam.build_context()
    briefing = redteam.build_host_briefing(
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
        [],
        [
            {"metric_id": "period.earlier.pushes", "value": 3},
            {"metric_id": "period.prior.pushes", "value": 1},
            {"metric_id": "period.last.pushes", "value": 0},
        ],
    )
    from framework.briefing.gate import evaluate_briefing

    result = evaluate_briefing(briefing, context)
    assert result.passed, [v.code for v in result.violations]
    assert result.violations == ()


def test_round1_produces_one_row_per_attack(tmp_path: Path) -> None:
    src = _copy_input("round-1.json", tmp_path)
    assert _run(str(src)) == 0
    results = _read_json(tmp_path / "round-1.results.json")
    assert set(results.keys()) == {"rows"}
    attacks = _read_json(src)["attacks"]
    assert len(results["rows"]) == len(attacks) == 34
    for row, attack in zip(results["rows"], attacks, strict=True):
        assert set(row.keys()) == ATTACK_ROW_FIELDS
        assert row["id"] == attack["id"]
        assert row["target"] == attack["target"]
        assert row["predicted_passes"] == attack["predicted_passes"]
        assert isinstance(row["passed"], bool)
        assert isinstance(row["codes"], list)
        assert row["raised"] is None
        assert row["codes"] == sorted(set(row["codes"]))


def test_true_sentences_produce_sentence_rows(tmp_path: Path) -> None:
    src = _copy_input("true-sentences-wonder-rules.json", tmp_path)
    assert _run(str(src)) == 0
    results = _read_json(tmp_path / "true-sentences-wonder-rules.results.json")
    sentences = _read_json(src)["sentences"]
    assert len(results["rows"]) == len(sentences) == 30
    for row, sentence in zip(results["rows"], sentences, strict=True):
        assert set(row.keys()) == SENTENCE_ROW_FIELDS
        assert row["id"] == sentence["id"]
        assert isinstance(row["passed"], bool)
        assert isinstance(row["codes"], list)
        assert row["raised"] is None


def test_raising_gate_gives_failed_row_without_killing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise ValueError("synthetic gate crash")

    monkeypatch.setattr(redteam, "evaluate_briefing", _boom)
    src = _copy_input("round-1.json", tmp_path)
    assert _run(str(src)) == 0
    results = _read_json(tmp_path / "round-1.results.json")
    assert len(results["rows"]) == 34
    for row in results["rows"]:
        assert row["passed"] is False
        assert row["codes"] == []
        assert row["raised"] == "ValueError"


def test_review_rows_from_temp_adjudication_fixture(tmp_path: Path) -> None:
    src = tmp_path / "round-9.json"
    src.write_text(
        json.dumps(
            {
                "attacks": [
                    {
                        "id": "A01",
                        "target": "A",
                        "predicted_passes": True,
                        "claim": {
                            "text": "Pushes in last were 0.",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.last.pushes", "value": 0}
                            ],
                        },
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "round-9.adjudicated.json").write_text(
        json.dumps(
            {
                "round": 9,
                "gate_commit": "synthetic",
                "verdicts": [],
                "found_in_review": [
                    {
                        "id": "R9",
                        "found_by": "synthetic reviewer",
                        "mechanism": "synthetic mechanism",
                        "claim": {
                            "text": "Pushes in last were 0.",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.last.pushes", "value": 0}
                            ],
                        },
                        "extra_facts": [
                            {
                                "id": "fx",
                                "statement": "Pushes in last were 0.",
                            }
                        ],
                        "unfixed_gate": "passes",
                        "verdict": "not_false",
                        "reason": "Synthetic reason.",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert _run(str(src)) == 0
    current = _read_json(tmp_path / "round-9.results.json")
    assert len(current["rows"]) == 1
    assert len(current["review_rows"]) == 1
    review = current["review_rows"][0]
    assert set(review.keys()) == REVIEW_ROW_FIELDS
    assert review["id"] == "R9"
    assert review["raised"] is None
    # Frozen files never hold review rows: they predate the adjudication.
    assert _run(str(src), "--write-frozen") == 0
    frozen = _read_json(tmp_path / "round-9.frozen.json")
    assert "review_rows" not in frozen


# ---------------------------------------------------------------------------
# Frozen versus current files.
# ---------------------------------------------------------------------------


def test_frozen_ids_match_input_order_with_all_stamps(
    tmp_path: Path,
) -> None:
    src = _copy_input("round-1.json", tmp_path)
    assert _run(str(src), "--write-frozen") == 0
    frozen = _read_json(tmp_path / "round-1.frozen.json")
    assert set(frozen.keys()) == FROZEN_FIELDS
    assert len(frozen["gate_commit"]) == 40
    assert len(frozen["gate_tree"]) == 40
    assert len(frozen["gate_files_sha256"]) == 64
    assert isinstance(frozen["gate_dirty"], bool)
    assert len(frozen["input_sha256"]) == 64
    attack_ids = [a["id"] for a in _read_json(src)["attacks"]]
    assert [r["id"] for r in frozen["rows"]] == attack_ids


def test_second_write_frozen_refuses_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _copy_input("round-1.json", tmp_path)
    assert _run(str(src), "--write-frozen") == 0
    before = (tmp_path / "round-1.frozen.json").read_bytes()
    before_current = (tmp_path / "round-1.results.json").read_bytes()
    assert _run(str(src), "--write-frozen") != 0
    assert (tmp_path / "round-1.frozen.json").read_bytes() == before
    assert (tmp_path / "round-1.results.json").read_bytes() == before_current
    assert "round-1.frozen.json" in capsys.readouterr().err


def test_current_file_is_byte_stable(tmp_path: Path) -> None:
    src = _copy_input("round-1.json", tmp_path)
    assert _run(str(src)) == 0
    first = (tmp_path / "round-1.results.json").read_bytes()
    assert _run(str(src)) == 0
    assert (tmp_path / "round-1.results.json").read_bytes() == first


# ---------------------------------------------------------------------------
# Malformed inputs: non-zero exit, nothing written.
# ---------------------------------------------------------------------------


def _assert_rejected(payload: object, name: str, tmp_path: Path) -> None:
    src = tmp_path / name
    src.write_text(json.dumps(payload), encoding="utf-8")
    assert _run(str(src)) != 0
    assert not (tmp_path / "round-1.results.json").exists()
    assert not (tmp_path / "round-1.frozen.json").exists()


def _good_claim() -> dict:
    return {
        "text": "Pushes in last were 0.",
        "fact_ids": [],
        "metric_refs": [{"metric_id": "period.last.pushes", "value": 0}],
    }


def _good_attack(aid: str = "A01", target: str = "A") -> dict:
    return {
        "id": aid,
        "target": target,
        "predicted_passes": True,
        "claim": _good_claim(),
    }


def test_malformed_inputs_rejected(tmp_path: Path) -> None:
    _assert_rejected([], "round-1.json", tmp_path)
    _assert_rejected({}, "round-1.json", tmp_path)
    _assert_rejected({"attacks": []}, "round-1.json", tmp_path)
    _assert_rejected(
        {"attacks": [_good_attack(), _good_attack()]}, "round-1.json", tmp_path
    )
    _assert_rejected({"attacks": [_good_attack(aid="")]}, "round-1.json", tmp_path)
    bad_target = _good_attack(aid="A02", target="Z")
    _assert_rejected({"attacks": [bad_target]}, "round-1.json", tmp_path)
    no_text = _good_attack()
    del no_text["claim"]["text"]
    _assert_rejected({"attacks": [no_text]}, "round-1.json", tmp_path)
    mixed = {"attacks": [_good_attack()], "sentences": [{"id": "S01"}]}
    _assert_rejected(mixed, "round-1.json", tmp_path)


# ---------------------------------------------------------------------------
# Summary: recomputed from the JSON files on disk with this file's own loops.
# ---------------------------------------------------------------------------


def _discover_inputs() -> tuple[list[Path], list[Path]]:
    rounds = sorted(p for p in REDTEAM_DIR.glob("round-*.json") if _is_attack_file(p))
    blinds = sorted(REDTEAM_DIR.glob("true-sentences-*.json"))
    blinds = [
        p
        for p in blinds
        if not p.name.endswith(".results.json") and not p.name.endswith(".frozen.json")
    ]
    return rounds, blinds


def _is_attack_file(path: Path) -> bool:
    if path.name.endswith((".results.json", ".frozen.json", ".adjudicated.json")):
        return False
    stem = path.name[: -len(".json")]
    rest = stem[len("round-") :]
    return rest.isdigit()


def test_summary_matches_recomputation_from_disk() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", "--summary"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)

    rounds, blinds = _discover_inputs()
    assert len(rounds) >= 1
    assert len(blinds) == 3

    total_sentences = 0
    total_blocked_frozen = 0
    total_blocked_current = 0
    for path in rounds + blinds:
        data = _read_json(path)
        entries = data.get("attacks", data.get("sentences"))
        assert isinstance(entries, list)
        name = path.name
        assert name in summary["files"], name
        reported = summary["files"][name]
        assert reported["sentences"] == len(entries)

        frozen_path = path.with_name(path.stem + ".frozen.json")
        current_path = path.with_name(path.stem + ".results.json")
        frozen_rows = _read_json(frozen_path)["rows"] if frozen_path.exists() else None
        current_rows = (
            _read_json(current_path)["rows"] if current_path.exists() else None
        )
        # Frozen ids equal the input ids in order.
        if frozen_rows is not None:
            want_ids = [e["id"] for e in entries]
            assert [r["id"] for r in frozen_rows] == want_ids

        def blocked(rows: list[dict] | None) -> int | None:
            if rows is None:
                return None
            count = 0
            for row in rows:
                if not row["passed"]:
                    count += 1
            return count

        assert reported["blocked_on_frozen"] == blocked(frozen_rows)
        assert reported["blocked_on_current"] == blocked(current_rows)

        by_code: dict[str, int] = {}
        if current_rows is not None:
            for row in current_rows:
                for code in row["codes"]:
                    by_code[code] = by_code.get(code, 0) + 1
        assert reported["blocked_by_code_on_current"] == by_code

        newly_ids: list[str] = []
        if frozen_rows is not None and current_rows is not None:
            frozen_by_id = {r["id"]: r for r in frozen_rows}
            for row in current_rows:
                old = frozen_by_id[row["id"]]
                if old["passed"] and not row["passed"]:
                    newly_ids.append(row["id"])
        assert reported["newly_blocked"]["ids"] == newly_ids
        newly_by_code: dict[str, int] = {}
        if current_rows is not None:
            current_by_id = {r["id"]: r for r in current_rows}
            for nid in newly_ids:
                for code in current_by_id[nid]["codes"]:
                    newly_by_code[code] = newly_by_code.get(code, 0) + 1
        assert reported["newly_blocked"]["by_code"] == newly_by_code

        for which, rows in (("frozen", frozen_rows), ("current", current_rows)):
            want_raised = []
            if rows is not None:
                for row in rows:
                    if row["raised"] is not None:
                        want_raised.append(row["id"])
            assert reported["raised_ids"][which] == want_raised

        total_sentences += len(entries)
        if blocked(frozen_rows) is not None:
            total_blocked_frozen += blocked(frozen_rows) or 0
        if blocked(current_rows) is not None:
            total_blocked_current += blocked(current_rows) or 0

    assert summary["total"]["sentences"] == total_sentences
    assert summary["total"]["blocked_on_frozen"] == total_blocked_frozen
    assert summary["total"]["blocked_on_current"] == total_blocked_current

    # Per-round verdict accounting comes from the adjudication files only.
    for path in rounds:
        stem = path.stem  # e.g. round-1
        number = stem[len("round-") :]
        reported_round = summary["rounds"][number]
        frozen_rows = _read_json(path.with_name(path.stem + ".frozen.json"))["rows"]
        through = []
        for row in frozen_rows:
            if row["passed"] or row["raised"] is not None:
                through.append(row)
        assert reported_round["through_total"] == len(through)
        adjudicated_path = path.with_name(path.stem + ".adjudicated.json")
        if adjudicated_path.exists():
            verdicts = {
                v["id"]: v["verdict"] for v in _read_json(adjudicated_path)["verdicts"]
            }
        else:
            verdicts = {}
        by_verdict: dict[str, int] = {}
        for row in through:
            verdict = verdicts.get(row["id"], "unadjudicated")
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        assert reported_round["through_by_verdict"] == by_verdict
        # Review findings are kept out of every attacker total.
        found = reported_round["found_in_review"]
        assert through_total_excludes_review(through, found)


def through_total_excludes_review(through: list[dict], found: dict) -> bool:
    review_ids = set(found.get("review_ids", []))
    return all(row["id"] not in review_ids for row in through)


def test_summary_round_targets_match_disk() -> None:
    rounds, _ = _discover_inputs()
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", "--summary"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    for path in rounds:
        number = path.stem[len("round-") :]
        frozen_rows = _read_json(path.with_name(path.stem + ".frozen.json"))["rows"]
        attacks = {a["id"]: a for a in _read_json(path)["attacks"]}
        want: dict[str, int] = {}
        for row in frozen_rows:
            if row["passed"] or row["raised"] is not None:
                target = attacks[row["id"]]["target"]
                want[target] = want.get(target, 0) + 1
        assert summary["rounds"][number]["through_by_target"] == want


def _summary_from_cli(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _expected_fixed(
    frozen_rows: list[dict], current_rows: list[dict], verdicts: dict[str, str]
) -> int:
    """D2: frozen-through real_hole rows now stopped, raised rows excluded."""
    fixed = 0
    current_by_id = {row["id"]: row for row in current_rows}
    for row in frozen_rows:
        if not (row["passed"] or row["raised"] is not None):
            continue
        if verdicts.get(row["id"]) != "real_hole":
            continue
        current = current_by_id[row["id"]]
        if current["raised"] is None and not current["passed"]:
            fixed += 1
    return fixed


def _expected_review_rows(current_path: Path, adjudication_path: Path) -> list[dict]:
    """D2/D17: full review rows joined with their verdicts, own loop."""
    current = _read_json(current_path)
    adjudication = _read_json(adjudication_path)
    verdicts = {v["id"]: v["verdict"] for v in adjudication["verdicts"]}
    verdicts.update(
        {e["id"]: e["verdict"] for e in adjudication.get("found_in_review", [])}
    )
    rows = []
    for row in current.get("review_rows", []):
        rows.append(
            {
                "id": row["id"],
                "verdict": verdicts[row["id"]],
                "passed": row["passed"],
                "codes": list(row["codes"]),
                "raised": row["raised"],
            }
        )
    return rows


def test_summary_found_in_review_carries_full_rows() -> None:
    summary = _summary_from_cli("--summary")
    rounds, _ = _discover_inputs()
    assert rounds, "no round inputs discovered"
    for path in rounds:
        number = path.stem[len("round-") :]
        reported = summary["rounds"][number]["found_in_review"]
        adjudication_path = path.with_name(path.stem + ".adjudicated.json")
        current_path = path.with_name(path.stem + ".results.json")
        if not adjudication_path.exists():
            assert reported["total"] == 0
            continue
        assert reported["rows"] == _expected_review_rows(
            current_path, adjudication_path
        )
        for row in reported["rows"]:
            assert set(row.keys()) == {"id", "verdict", "passed", "codes", "raised"}


def test_summary_fixed_excludes_raised_on_current() -> None:
    summary = _summary_from_cli("--summary")
    rounds, _ = _discover_inputs()
    for path in rounds:
        number = path.stem[len("round-") :]
        reported = summary["rounds"][number]
        frozen_rows = _read_json(path.with_name(path.stem + ".frozen.json"))["rows"]
        current_rows = _read_json(path.with_name(path.stem + ".results.json"))["rows"]
        adjudication_path = path.with_name(path.stem + ".adjudicated.json")
        verdicts = (
            {v["id"]: v["verdict"] for v in _read_json(adjudication_path)["verdicts"]}
            if adjudication_path.exists()
            else {}
        )
        assert reported["fixed"] == _expected_fixed(frozen_rows, current_rows, verdicts)


def test_summary_markdown_renders_one_row_per_finding() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", "--summary", "--markdown"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    rounds, _ = _discover_inputs()
    for path in rounds:
        adjudication_path = path.with_name(path.stem + ".adjudicated.json")
        if not adjudication_path.exists():
            continue
        for entry in _read_json(adjudication_path).get("found_in_review", []):
            assert f"| {entry['id']} | {entry['verdict']} |" in proc.stdout, entry["id"]


def test_repo_current_files_match_regeneration() -> None:
    """Staleness on the repo's own files: regen in a temp dir, diff bytes."""
    rounds, blinds = _discover_inputs()
    assert len(rounds) >= 1
    assert len(blinds) == 3
    for path in rounds + blinds:
        assert path.parent == REDTEAM_DIR
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        for path in rounds + blinds:
            dest = Path(work) / path.name
            dest.write_bytes(path.read_bytes())
            adjudication = path.with_name(path.stem + ".adjudicated.json")
            if adjudication.exists():
                (Path(work) / adjudication.name).write_bytes(adjudication.read_bytes())
            assert _run(str(dest)) == 0
            regenerated = (
                Path(work) / dest.with_name(dest.stem + ".results.json").name
            ).read_bytes()
            assert (
                path.with_name(path.stem + ".results.json").read_bytes() == regenerated
            ), path.name


def test_repo_frozen_files_are_fresh_and_stamped() -> None:
    """Every input has a frozen file: ids in order, stamps, hash, clean."""
    rounds, blinds = _discover_inputs()
    assert len(rounds) >= 1
    assert len(blinds) == 3
    for path in rounds + blinds:
        frozen_path = path.with_name(path.stem + ".frozen.json")
        assert frozen_path.exists(), f"missing frozen file for {path.name}"
        frozen = _read_json(frozen_path)
        assert set(frozen.keys()) == FROZEN_FIELDS, path.name
        data = _read_json(path)
        entries = data.get("attacks", data.get("sentences") or [])
        assert [r["id"] for r in frozen["rows"]] == [e["id"] for e in entries]
        assert len(frozen["gate_commit"]) == 40
        assert len(frozen["gate_tree"]) == 40
        assert len(frozen["gate_files_sha256"]) == 64
        assert isinstance(frozen["gate_dirty"], bool)
        import hashlib

        assert (
            frozen["input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        ), path.name
        # Round 2 attacks the fixed gate before its one commit (D3):
        # its frozen file records a dirty gate, every other file a clean one.
        if path.name == "round-2.json":
            assert frozen["gate_dirty"] is True, path.name
        else:
            assert frozen["gate_dirty"] is False, path.name


def test_round_adjudication_shape() -> None:
    """One verdict per frozen through-row; reasons end in a full stop."""
    rounds, _ = _discover_inputs()
    assert rounds, "no round inputs discovered"
    for path in rounds:
        adjudication_path = path.with_name(path.stem + ".adjudicated.json")
        assert adjudication_path.exists(), f"missing {adjudication_path.name}"
        adjudication = _read_json(adjudication_path)
        frozen = _read_json(path.with_name(path.stem + ".frozen.json"))
        assert adjudication["gate_commit"] == frozen["gate_commit"], path.name
        through = [
            r["id"] for r in frozen["rows"] if r["passed"] or r["raised"] is not None
        ]
        verdicts = adjudication["verdicts"]
        assert sorted(v["id"] for v in verdicts) == sorted(through), path.name
        assert len({v["id"] for v in verdicts}) == len(verdicts)
        for verdict in verdicts:
            assert verdict["verdict"] in {
                "real_hole",
                "disclosed_limit",
                "not_false",
            }, verdict
            assert isinstance(verdict["reason"], str) and verdict["reason"]
            assert verdict["reason"].endswith("."), verdict
        for entry in adjudication.get("found_in_review", []):
            assert set(entry.keys()) >= {
                "id",
                "found_by",
                "mechanism",
                "claim",
                "verdict",
                "reason",
            }, entry
            assert entry["verdict"] in {
                "real_hole",
                "disclosed_limit",
                "not_false",
                "over_block",
            }, entry
            assert isinstance(entry["reason"], str) and entry["reason"]
            assert entry["reason"].endswith("."), entry
            assert isinstance(entry["claim"]["text"], str) and entry["claim"]["text"]
            assert isinstance(entry["claim"]["fact_ids"], list)
            assert isinstance(entry["claim"]["metric_refs"], list)


def test_summary_markdown_is_verbatim_in_redteam_readme() -> None:
    # Stage 2 (Step 8): docs/redteam/README.md carries the current
    # --summary --markdown output word for word.
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", "--summary", "--markdown"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    readme = (REDTEAM_DIR / "README.md").read_text(encoding="utf-8")
    assert proc.stdout in readme


def test_summary_markdown_is_verbatim_in_session_note() -> None:
    # Stage 2 (Step 8): docs/sessions/010b-redteam.md carries the current
    # --summary --markdown output word for word.
    proc = subprocess.run(
        [sys.executable, "-m", "evals.redteam", "--summary", "--markdown"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    note = (ROOT / "docs" / "sessions" / "010b-redteam.md").read_text(encoding="utf-8")
    assert proc.stdout in note


def test_extra_metrics_apply_per_row_without_mutating_shared_context() -> None:
    # Checkpoint 3a (R4/R5): extra_metrics land in the row's snapshot copy.
    context = redteam.build_context()
    before_values = dict(context.metrics.values)
    before_facts = dict(context.facts)
    adjudication = {
        "found_in_review": [
            {
                "id": "R4",
                "claim": {
                    "text": "Programming was 17 hours.",
                    "fact_ids": [],
                    "metric_refs": [
                        {
                            "metric_id": "screen_hours.Work/Programming",
                            "value": 17.000000000000004,
                        }
                    ],
                },
                "extra_metrics": {"screen_hours.Work/Programming": 17.000000000000004},
            }
        ]
    }
    rows = redteam.run_review_rows(
        Path("round-1.adjudicated.json"), adjudication, context
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "R4"
    assert rows[0]["raised"] is None
    assert rows[0]["passed"] is True, rows[0]["codes"]
    assert dict(context.metrics.values) == before_values
    assert dict(context.facts) == before_facts


def test_extra_metrics_malformed_names_file_and_row() -> None:
    # Checkpoint 3a: a non-finite value or a non-object entry exits
    # non-zero with a message naming the file and the row.
    context = redteam.build_context()
    source = Path("round-1.adjudicated.json")

    def _entry(extra_metrics: object) -> dict:
        return {
            "found_in_review": [
                {
                    "id": "RX",
                    "claim": {
                        "text": "Pushes in last were 0.",
                        "fact_ids": [],
                        "metric_refs": [
                            {"metric_id": "period.last.pushes", "value": 0}
                        ],
                    },
                    "extra_metrics": extra_metrics,
                }
            ]
        }

    for bad in (
        {"period.last.pushes": "zero"},
        {"period.last.pushes": float("inf")},
        {"period.last.pushes": float("nan")},
        {"period.last.pushes": True},
        ["period.last.pushes"],
    ):
        with pytest.raises(ValueError, match="round-1.adjudicated.json"):
            redteam.run_review_rows(source, _entry(bad), context)
        try:
            redteam.run_review_rows(source, _entry(bad), context)
        except ValueError as exc:
            assert "RX" in str(exc)
        else:  # pragma: no cover - the match above already failed
            raise AssertionError(bad)


def test_extra_metrics_malformed_file_exits_nonzero(tmp_path: Path) -> None:
    src = tmp_path / "round-9.json"
    src.write_text(
        json.dumps(
            {
                "attacks": [
                    {
                        "id": "A01",
                        "target": "A",
                        "predicted_passes": True,
                        "claim": {
                            "text": "Pushes in last were 0.",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.last.pushes", "value": 0}
                            ],
                        },
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "round-9.adjudicated.json").write_text(
        json.dumps(
            {
                "round": 9,
                "gate_commit": "synthetic",
                "verdicts": [],
                "found_in_review": [
                    {
                        "id": "RX",
                        "found_by": "synthetic reviewer",
                        "mechanism": "synthetic mechanism",
                        "claim": {
                            "text": "Pushes in last were 0.",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": "period.last.pushes", "value": 0}
                            ],
                        },
                        "extra_metrics": {"period.last.pushes": "zero"},
                        "unfixed_gate": "passes",
                        "verdict": "not_false",
                        "reason": "Synthetic reason.",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert _run(str(src)) != 0
    assert not (tmp_path / "round-9.results.json").exists()


def test_extra_private_terms_apply_per_row_without_mutating_shared_context() -> None:
    # A term rides the row's private-terms copy: the row naming it fails,
    # and the shared context keeps its own terms.
    context = redteam.build_context()
    assert "Wrenfield" not in context.private_terms
    before_terms = tuple(context.private_terms)
    before_facts = dict(context.facts)
    before_values = dict(context.metrics.values)
    adjudication = {
        "found_in_review": [
            {
                "id": "R9",
                "claim": {
                    "text": "The notes mention Wrenfield today.",
                    "fact_ids": ["f1"],
                    "metric_refs": [],
                },
                "extra_private_terms": ["Wrenfield"],
            }
        ]
    }
    rows = redteam.run_review_rows(
        Path("round-1.adjudicated.json"), adjudication, context
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "R9"
    assert rows[0]["raised"] is None
    assert rows[0]["passed"] is False, rows[0]["codes"]
    assert rows[0]["codes"] == ["L1_PRIVATE_TERM"]
    assert tuple(context.private_terms) == before_terms
    assert dict(context.facts) == before_facts
    assert dict(context.metrics.values) == before_values


def test_extra_private_terms_malformed_names_file_and_row() -> None:
    # A value that is not a list of non-empty strings raises naming the
    # file and the row, as extra_metrics does.
    context = redteam.build_context()
    source = Path("round-1.adjudicated.json")

    def _entry(extra_terms: object) -> dict:
        return {
            "found_in_review": [
                {
                    "id": "RX",
                    "claim": {
                        "text": "The notes mention Wrenfield today.",
                        "fact_ids": ["f1"],
                        "metric_refs": [],
                    },
                    "extra_private_terms": extra_terms,
                }
            ]
        }

    for bad in (
        "Wrenfield",
        [""],
        ["Wrenfield", 7],
        ["Wrenfield", ""],
        7,
        None,
    ):
        with pytest.raises(ValueError, match="round-1.adjudicated.json"):
            redteam.run_review_rows(source, _entry(bad), context)
        try:
            redteam.run_review_rows(source, _entry(bad), context)
        except ValueError as exc:
            assert "RX" in str(exc)
        else:  # pragma: no cover - the match above already failed
            raise AssertionError(bad)


def test_deepcopy_keeps_host_stable_across_rows(tmp_path: Path) -> None:
    first = redteam.build_host_briefing(
        "Pushes in last were 0.",
        [],
        [{"metric_id": "period.last.pushes", "value": 0}],
    )
    snapshot = copy.deepcopy(first)
    redteam.build_host_briefing(
        "Pushes in last were 0.",
        [],
        [{"metric_id": "period.last.pushes", "value": 0}],
    )
    assert first == snapshot
