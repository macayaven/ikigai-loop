"""Ticket 15a: CLI bytes, first line, JSON form, bad-value exits."""

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from framework.learner.__main__ import main

NOTE_LINE = (
    "n_cards is the number of real two-proposal choices fed to one posterior. "
    "Cards with one proposal, and neither, wrong or why taps, add none. "
    "My live run expects about 13 cards over three days, and Disconnect appears "
    "on at most 3 of the 5 slots a day, so at most about 9 of them can be real "
    "choices, split over three buckets. A live bucket's posterior will hold about "
    "3 choices, so even the n = 5 row is optimistic for it. The n = 13 row is an "
    "upper bound on the pooled reading, available only if the preference does "
    "not vary by bucket."
)


def _run(argv: list[str]) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    assert code == 0
    return buf.getvalue()


def test_main_twice_byte_identical() -> None:
    argv = ["recover", "--seed", "1", "--sims", "20", "--n-cards", "5"]
    assert _run(argv) == _run(argv)


def test_first_line_and_row_shape() -> None:
    out = _run(["recover", "--seed", "1", "--sims", "20", "--n-cards", "5"])
    lines = out.splitlines()
    assert (
        lines[0]
        == "SIMULATED rulings from a known preference. No real data. seed=1 sims=20"
    )
    assert lines[1] == (
        "true_p n_cards correct_side mean_absolute_error coverage mean_interval_width"
    )
    assert len(lines) == 2 + 5 + 1
    for row in lines[2:7]:
        parts = row.split(" ")
        assert len(parts) == 6
        assert parts[1] == "5"
    assert lines[-1] == NOTE_LINE


def test_default_grid_rows_in_order() -> None:
    out = _run(["recover", "--seed", "1", "--sims", "2"])
    lines = out.splitlines()
    assert len(lines) == 2 + 20 + 1
    rows = lines[2:22]
    want_ps = [p for p in (0.5, 0.6, 0.7, 0.8, 0.9) for _ in (5, 13, 30, 100)]
    want_ns = [n for _ in (0.5, 0.6, 0.7, 0.8, 0.9) for n in (5, 13, 30, 100)]
    for row, want_p, want_n in zip(rows, want_ps, want_ns):
        parts = row.split(" ")
        assert len(parts) == 6
        assert parts[0] == f"{want_p:.3f}"
        assert parts[1] == str(want_n)
    assert _run(["recover", "--seed", "1", "--sims", "2", "--n-cards"]) == out


def test_default_sims_is_2000(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.learner import __main__ as cli
    from framework.learner.simulate import recover_table as real_table

    seen: dict[str, object] = {}

    def _recorder(**kwargs: object) -> object:
        seen.update(kwargs)
        assert isinstance(kwargs["seed"], int)
        return real_table(seed=kwargs["seed"], n_sims=2, true_ps=(0.5,), n_cards=(5,))

    monkeypatch.setattr(cli, "recover_table", _recorder)
    assert cli.main(["recover", "--seed", "1"]) == 0
    assert seen["n_sims"] == 2000
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.endswith("sims=2000")


def test_rows_match_json_cells(tmp_path: Path) -> None:
    target = tmp_path / "table.json"
    argv = ["recover", "--seed", "1", "--sims", "20", "--n-cards", "5", "13"]
    stdout = _run([*argv, "--json", str(target)])
    parsed = json.loads(target.read_text(encoding="utf-8"))
    rows = stdout.splitlines()[2:12]
    assert len(rows) == len(parsed["cells"]) == 10
    for row, cell in zip(rows, parsed["cells"]):
        side = "n/a" if cell["correct_side"] is None else f"{cell['correct_side']:.3f}"
        assert row == (
            f"{cell['true_p']:.3f} {cell['n_cards']} {side} "
            f"{cell['mean_absolute_error']:.3f} {cell['coverage']:.3f} "
            f"{cell['mean_interval_width']:.3f}"
        )
    first_bytes = target.read_bytes()
    _run([*argv, "--json", str(target)])
    assert target.read_bytes() == first_bytes


def test_na_only_in_half_rows() -> None:
    out = _run(["recover", "--seed", "1", "--sims", "20", "--n-cards", "5", "13"])
    rows = out.splitlines()[2:12]
    assert len(rows) == 10
    for row in rows:
        parts = row.split(" ")
        if parts[0] == "0.500":
            assert parts[2] == "n/a"
        else:
            assert parts[2] != "n/a"
    assert sum(1 for r in rows if "n/a" in r.split(" ")) == 2


def test_json_file_matches_pinned_form(tmp_path: Path) -> None:
    target = tmp_path / "table.json"
    argv = [
        "recover",
        "--seed",
        "1",
        "--sims",
        "20",
        "--n-cards",
        "5",
        "--json",
        str(target),
    ]
    stdout = _run(argv)
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n") and not text.endswith("\n\n")
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    assert text == canonical
    parsed = json.loads(text)
    assert parsed["label"] == "simulated"
    assert parsed["seed"] == 1
    assert parsed["n_sims"] == 20
    assert parsed["note"] == NOTE_LINE
    assert len(parsed["cells"]) == 5
    assert stdout.splitlines()[0].startswith("SIMULATED")


def test_bad_values_exit_2_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["recover", "--seed", "1", "--sims", "0"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc2:
        main(["recover", "--seed", "1", "--n-cards", "0"])
    assert exc2.value.code == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_subprocess_smoke_run() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "framework.learner",
            "recover",
            "--seed",
            "1",
            "--sims",
            "20",
            "--n-cards",
            "5",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = proc.stdout.splitlines()
    assert (
        lines[0]
        == "SIMULATED rulings from a known preference. No real data. seed=1 sims=20"
    )
    assert len(lines) == 2 + 5 + 1
