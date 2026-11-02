"""Ticket 21: try-ikigai replay tests."""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BANNER = (
    "Ikigai Loop synthetic replay: made-up data, no model, no network, nothing stored."
)
HEADINGS = [
    "1. The card (synthetic)",
    "2. The choice (synthetic)",
    "3. A wrong number, stopped (synthetic)",
    "4. Where a number comes from (synthetic)",
    "5. Check your own agent",
]
BANNED = [
    "thrilled",
    "delighted",
    "leverage",
    "delve",
    "tapestry",
    "robust",
    "seamless",
    "coach",
    "wellness",
    "wellbeing",
    "mental",
    "recovery",
]
FORBIDDEN = [
    "load_private_terms",
    "load_commitments",
    "subject_id_from_env",
    "resolve_db_path",
    "EventStore",
    "FactStore",
    "ProposalStore",
    "CardLedger",
    "send_card",
    "TelegramClient",
    "MuseExecClient",
    "MetaClient",
    "framework.cycle.orchestrator",
    "framework.cycle.rehearse",
    "os.environ",
    "input(",
    "time.sleep",
    "datetime.now",
]
ALLOWED_CYCLE_IMPORTS = {
    "framework.cycle.card_build": {
        "since_counts",
        "since_line",
        "build_tally",
        "build_chart_data",
        "build_card",
    },
    "framework.cycle.trace": {"metric_sources"},
    "framework.cycle.slot_ledger": {"SlotCardRow"},
}
RAW1 = "https://raw.githubusercontent.com/macayaven/ikigai-loop/main/examples/verify/input.json"
UVX1 = (
    "uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims input.json"
)
LINK1 = "https://macayaven.github.io/ikigai-loop/verify/"


def _run(argv: list[str]) -> tuple[int, str, str]:
    from io import StringIO

    from framework.tryit.__main__ import main

    old_out, old_err = sys.stdout, sys.stderr
    out, err = StringIO(), StringIO()
    sys.stdout, sys.stderr = out, err
    try:
        code = main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return code, out.getvalue(), err.getvalue()


def _replay(pick: str = "A"):
    from framework.tryit import replay as replay_mod

    return replay_mod.run_replay(pick=pick)


def _section(out: str, heading: str, nxt: str) -> str:
    return out.split(heading)[1].split(nxt)[0]


def _subprocess_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
    }
    if extra:
        env.update(extra)
    return env


def _run_subprocess(
    argv: list[str],
    cwd: Path,
    home: Path,
    extra: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "framework.tryit", *argv],
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=_subprocess_env(home, extra),
    )


def test_output_has_all_five_sections_in_order_labelled_synthetic() -> None:
    code, out, _ = _run([])
    assert code == 0
    assert out.splitlines()[0] == BANNER
    positions = [out.index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    assert out.count("synthetic") >= 5
    assert "Ikigai Loop" in out
    first = out.index("5. Check your own agent")
    tail = out[first:]
    assert "was synthetic" in tail.splitlines()[1]
    assert "your agent's output and your records" in " ".join(tail.split())


def test_output_within_length_limit() -> None:
    _, out, _ = _run([])
    assert len(out.splitlines()) <= 90
    assert len(out) <= 3800


def test_every_printed_error_code_is_followed_by_its_plain_sentence() -> None:
    from framework.tryit import text as text_mod

    result = _replay()
    assert result.planted_codes, "the replay must plant at least one code"
    _, out, _ = _run([])
    section = _section(
        out,
        "3. A wrong number, stopped (synthetic)",
        "4. Where a number comes from",
    )
    lines = section.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() in result.planted_codes:
            code = line.strip()
            found.append(code)
            following = " ".join(part.strip() for part in lines[i + 1 : i + 3])
            expected = text_mod.plain_sentence(code) + "."
            assert following.lower().startswith(expected.lower()), line
            assert following[:1].isupper(), line
    assert sorted(found) == sorted(result.planted_codes)


def test_unknown_error_code_gets_generic_sentence() -> None:
    from framework.tryit import text as text_mod

    sentence = text_mod.explain_code("L1B_SOME_FUTURE_CODE")
    assert "L1B_SOME_FUTURE_CODE" in sentence
    assert len(sentence.split()) >= 4


def test_chart_line_gives_pixel_size_and_save_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _replay()
    _, out, _ = _run([])
    assert f"{result.width}x{result.height}" in out
    assert "byte" not in out.lower()
    assert "memory" in out.lower()
    assert "--save card.png" in out
    assert "you can keep it" in out
    monkeypatch.chdir(tmp_path)
    code, out2, _ = _run(["--save", "card.png"])
    assert code == 0
    assert "saved to card.png" in out2
    assert f"{result.width}x{result.height}" in out2
    assert str(tmp_path) not in out2


def test_banned_words_absent_from_output_and_recording() -> None:
    _, out, _ = _run([])
    lowered = out.lower()
    assert "ruling" not in lowered
    for word in BANNED:
        assert word not in lowered, word
    recording = (ROOT / "framework" / "tryit" / "recording.json").read_text()
    assert "ruling" not in recording.lower()
    for word in BANNED:
        assert word not in recording.lower(), word


def test_card_text_is_render_card_text_of_the_replay_card() -> None:
    from framework.telegram.models import render_card_text

    result = _replay()
    _, out, _ = _run([])
    section = _section(out, "1. The card (synthetic)", "2. The choice (synthetic)")
    expected = render_card_text(result.card).splitlines()
    assert expected, "render_card_text must produce content lines"
    dedented = [line.removeprefix("  ") for line in section.splitlines()]
    starts = [
        i
        for i in range(len(dedented) - len(expected) + 1)
        if dedented[i : i + len(expected)] == expected
    ]
    assert len(starts) == 1, dedented


def test_saved_image_is_render_chart_png_of_the_replay_chart(
    tmp_path: Path,
) -> None:
    from PIL import Image

    from framework.telegram.chart import render_chart_png

    result = _replay()
    target = tmp_path / "keep.png"
    code, _, _ = _run(["--save", str(target)])
    assert code == 0
    assert target.read_bytes() == render_chart_png(result.chart)
    image = Image.open(target)
    assert (result.width, result.height) == (image.size[0], image.size[1])
    assert image.size[0] == 1080


def _keyboard_row_lines(keyboard: dict[str, object]) -> list[str]:
    from typing import cast

    rows = cast("list[list[dict[str, str]]]", keyboard["inline_keyboard"])
    return [" ".join(f"[{button['text']}]" for button in row) for row in rows]


def test_button_labels_come_from_build_keyboard() -> None:
    from framework.telegram.models import build_keyboard, build_ruled_keyboard

    result = _replay()
    _, out, _ = _run([])
    card_section = _section(out, "1. The card (synthetic)", "2. The choice (synthetic)")
    choice_section = _section(out, "2. The choice (synthetic)", "3. A wrong number")
    expected = _keyboard_row_lines(build_keyboard(result.card))
    assert len(expected) == 4
    positions = [card_section.index(f"  {line}") for line in expected]
    assert positions == sorted(positions)
    ruled = _keyboard_row_lines(build_ruled_keyboard(result.card_id, "A"))
    assert len(ruled) == 3
    ruled_positions = [choice_section.index(f"  {line}") for line in ruled]
    assert ruled_positions == sorted(ruled_positions)


def test_gate_passes_everything_makes_command_exit_1_with_no_story(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from framework.proposal import core

    monkeypatch.setattr(
        core,
        "evaluate_briefing",
        lambda briefing, context: types.SimpleNamespace(violations=(), passed=True),
    )
    code, out, err = _run([])
    assert code == 1
    assert out == ""
    assert len(err.strip().splitlines()) == 1


def test_gate_rejecting_everything_makes_command_exit_1_with_no_story(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from framework.proposal import core
    from framework.tryit import replay as replay_mod

    def _fail(briefing: object, context: object) -> object:
        return types.SimpleNamespace(
            violations=(
                types.SimpleNamespace(
                    code="L1_FORCED", layer="L1", location="x", message="forced"
                ),
            ),
            passed=False,
        )

    monkeypatch.setattr(core, "evaluate_briefing", _fail)
    real_client = replay_mod._RecordedClient

    def _looping_client(texts: list[str]) -> object:
        return real_client([*texts, texts[-1]])

    monkeypatch.setattr(replay_mod, "_RecordedClient", _looping_client)
    code, out, err = _run([])
    assert code == 1
    assert out == ""
    assert len(err.strip().splitlines()) == 1


def test_planted_draft_rejected_corrected_and_other_goal_pass_first_time() -> None:
    result = _replay()
    builder = result.builder_result
    assert len(builder.attempts) == 2
    assert len(builder.attempts[0].codes) >= 1
    assert builder.attempts[1].codes == ()
    assert builder.kind == "proposal"
    disconnect = result.disconnect_result
    assert len(disconnect.attempts) == 1
    assert disconnect.attempts[0].codes == ()
    assert disconnect.kind == "proposal"
    assert result.said_value == 5.0
    assert result.holds_value == 4.0
    assert result.lied_metric == "period.last.pushes"
    assert set(result.planted_codes) == {code for code, _ in builder.attempts[0].codes}


def test_planted_sentence_holding_the_true_number_fails_the_story_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.tryit import replay as replay_mod

    recording = replay_mod.load_recording()
    patched = recording.model_copy(
        update={
            "builder_planted": recording.builder_planted.model_copy(
                update={"overall_state": [recording.builder_fixed.overall_state[0]]}
            )
        }
    )
    monkeypatch.setattr(replay_mod, "load_recording", lambda: patched)
    code, out, err = _run([])
    assert code == 1
    assert out == ""
    assert len(err.strip().splitlines()) == 1


def _move_counts(line: str) -> tuple[dict[str, int], dict[str, int]]:
    match = re.search(
        r"move from Builder (\d+),\s+Disconnect (\d+),\s+Neither (\d+)"
        r"\s+to Builder (\d+),\s+Disconnect (\d+),\s+Neither (\d+)",
        line,
    )
    assert match is not None, line
    nums = [int(part) for part in match.groups()]
    return (
        {"Builder": nums[0], "Disconnect": nums[1], "Neither": nums[2]},
        {"Builder": nums[3], "Disconnect": nums[4], "Neither": nums[5]},
    )


def test_pick_a_b_and_neither_change_toast_and_counts() -> None:
    from framework.cycle.card_build import build_tally
    from framework.telegram.models import TARGET_LABELS, toast_recorded
    from framework.tryit import replay as replay_mod

    recording = replay_mod.load_recording()
    packaged = {
        item.label: item.count
        for item in build_tally(
            tuple(recording.earlier_taps),
            replay_mod.earlier_card_rows(
                tuple(recording.earlier_taps),
                slot=recording.slot,
                subject_id=recording.subject_id,
                as_of=recording.as_of,
                commitments=tuple(recording.commitments),
            ),
        )
    }
    side_of = {"A": "Builder", "B": "Disconnect", "neither": "Neither"}
    for pick in ("A", "B", "neither"):
        code, out, _ = _run(["--pick", pick])
        assert code == 0
        assert toast_recorded(TARGET_LABELS[pick]) in out
        before, after = _move_counts(" ".join(out.splitlines()))
        assert before == packaged
        for side in ("Builder", "Disconnect", "Neither"):
            assert after[side] == before[side] + (1 if side == side_of[pick] else 0)


def test_help_prints_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from framework.tryit import __main__ as main_mod

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("the replay must not run for --help")

    monkeypatch.setattr(main_mod, "run_replay", _boom)
    code, out, err = _run(["--help"])
    assert code == 0
    assert "try-ikigai" in out or "try-ikigai" in err
    assert "1. The card" not in out
    assert list(tmp_path.iterdir()) == []


def test_bad_pick_exits_2() -> None:
    for argv in (["--pick", "C"], ["--bogus"], ["--pick"], ["extra"]):
        code, out, _err = _run(argv)
        assert code == 2, argv
        assert out == ""


def test_stdin_is_never_read() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "framework.tryit"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0
    proc2 = subprocess.run(
        [sys.executable, "-m", "framework.tryit"],
        cwd=ROOT,
        input="A\n" * 10,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc2.returncode == 0
    assert proc2.stdout == proc.stdout


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    work0 = tmp_path / "work0"
    work1 = tmp_path / "work1"
    work0.mkdir()
    work1.mkdir()
    first = _run_subprocess([], ROOT, home, {"PYTHONHASHSEED": "0"})
    second = _run_subprocess([], ROOT, home, {"PYTHONHASHSEED": "12345"})
    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout
    saved_first = _run_subprocess(
        ["--save", "card.png"], work0, home, {"PYTHONHASHSEED": "0"}
    )
    saved_second = _run_subprocess(
        ["--save", "card.png"], work1, home, {"PYTHONHASHSEED": "12345"}
    )
    assert saved_first.returncode == 0
    assert saved_second.returncode == 0
    assert saved_first.stdout == saved_second.stdout
    assert (work0 / "card.png").read_bytes() == (work1 / "card.png").read_bytes()


def test_tz_and_cwd_change_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    work1 = tmp_path / "work1"
    work2 = tmp_path / "work2"
    work1.mkdir()
    work2.mkdir()
    first = _run_subprocess(
        ["--save", "card.png"], work1, home, {"TZ": "Pacific/Auckland"}
    )
    second = _run_subprocess(
        ["--save", "card.png"], work2, home, {"TZ": "America/New_York"}
    )
    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout
    assert (work1 / "card.png").read_bytes() == (work2 / "card.png").read_bytes()


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[rel + "@link"] = os.readlink(path).encode()
        elif path.is_dir():
            snapshot[rel + "@dir"] = b""
        elif path.is_file():
            snapshot[rel] = path.read_bytes()
    return snapshot


def test_no_save_writes_nothing_anywhere(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    scratch = tmp_path / "scratch"
    home.mkdir()
    work.mkdir()
    scratch.mkdir()
    before = _tree_snapshot(tmp_path)
    proc = _run_subprocess(
        [], work, home, {"TMPDIR": str(scratch), "PYTHONHASHSEED": "7"}
    )
    assert proc.returncode == 0
    assert _tree_snapshot(tmp_path) == before


def test_save_writes_then_refuses_different_and_accepts_identical(
    tmp_path: Path,
) -> None:
    target = tmp_path / "card.png"
    code, _, _ = _run(["--save", str(target)])
    assert code == 0
    first = target.read_bytes()
    assert first.startswith(b"\x89PNG")
    code2, _out2, _ = _run(["--save", str(target)])
    assert code2 == 0
    assert target.read_bytes() == first
    target.write_bytes(b"not a chart")
    code3, out3, _err3 = _run(["--save", str(target)])
    assert code3 == 2
    assert out3 == ""
    assert target.read_bytes() == b"not a chart"


def test_save_onto_directory_and_dangling_symlink_exit_2(tmp_path: Path) -> None:
    code, out, _ = _run(["--save", str(tmp_path)])
    assert code == 2
    assert out == ""
    link = tmp_path / "link.png"
    link.symlink_to(tmp_path / "absent-target.png")
    code2, out2, _ = _run(["--save", str(link)])
    assert code2 == 2
    assert out2 == ""
    assert link.is_symlink()


def test_save_onto_named_pipe_returns_without_hanging(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    pipe = tmp_path / "pipe.png"
    os.mkfifo(pipe)
    proc = _run_subprocess(["--save", str(pipe)], tmp_path, home, timeout=60)
    assert proc.returncode == 2
    assert proc.stdout == b""


def test_save_identical_bytes_leave_mtime_alone(tmp_path: Path) -> None:
    target = tmp_path / "card.png"
    code, _, _ = _run(["--save", str(target)])
    assert code == 0
    old = 1_000_000_000
    os.utime(target, (old, old))
    code2, _, _ = _run(["--save", str(target)])
    assert code2 == 0
    assert target.stat().st_mtime_ns == old * 1_000_000_000


def test_save_unwritable_path_exits_2_without_traceback(tmp_path: Path) -> None:
    code, out, err = _run(["--save", str(tmp_path / "nope" / "card.png")])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err


def test_isolation_decoy_env_and_db_are_untouched(tmp_path: Path) -> None:
    decoy_data = tmp_path / "decoy-data"
    decoy_data.mkdir()
    decoy_db = decoy_data / "ikigai.db"
    decoy_db.write_bytes(b"decoy-bytes")
    decoy_commitments = tmp_path / "decoy-commitments.json"
    decoy_commitments.write_text(
        json.dumps(
            [
                {
                    "dimension": "love",
                    "evidence": "calendar_tag",
                    "id": "cm-decoy-other",
                    "kind": "social",
                    "profile_id": "disconnect",
                    "tag": "iki-family",
                    "title": "Decoy title that would change the card",
                }
            ]
        ),
        encoding="utf-8",
    )
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "deny-terms.txt").write_text("rose\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    default_db = work / "data" / "ikigai.db"
    default_db.parent.mkdir()
    default_db.write_bytes(b"default-path-decoy")
    clean_work = tmp_path / "clean"
    clean_work.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    decoy_env = {
        "IKIGAI_DATA_DIR": str(decoy_data),
        "IKIGAI_COMMITMENTS_FILE": str(decoy_commitments),
        "HIDDEN_CRITERIA_DIR": str(hidden),
        "IKIGAI_SUBJECT_ID": "someone-else",
    }
    decoyed = _run_subprocess(["--save", "keep.png"], work, home, decoy_env)
    assert decoyed.returncode == 0
    assert decoy_db.read_bytes() == b"decoy-bytes"
    assert default_db.read_bytes() == b"default-path-decoy"
    assert b"Decoy title" not in decoyed.stdout
    clean = _run_subprocess(["--save", "keep.png"], clean_work, home, None)
    assert clean.returncode == 0
    assert decoyed.stdout == clean.stdout
    dirs_after = {p for p in tmp_path.rglob("*") if p.is_dir()}
    assert dirs_after == {
        home,
        work,
        work / "data",
        clean_work,
        decoy_data,
        hidden,
    }
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "keep.png" not in names
    assert sorted(p.name for p in work.iterdir()) == ["data", "keep.png"]


def test_in_process_with_sockets_blocked_and_sqlite_raising_exits_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("no sockets in tests")

    monkeypatch.setattr(socket.socket, "connect", _deny)
    monkeypatch.setattr(socket.socket, "bind", _deny)
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no db")),
    )
    code, out, _ = _run([])
    assert code == 0
    assert BANNER in out


def test_source_scan_forbidden_names() -> None:
    import ast

    package = ROOT / "framework" / "tryit"
    paths = sorted(package.glob("*.py"))
    sources = [p.read_text() for p in paths]
    assert sources, "new package has no modules"
    for name in FORBIDDEN:
        for source, path in zip(sources, paths):
            assert name not in source, (name, path.name)
    for source, path in zip(sources, paths):
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "framework.cycle" or module.startswith("framework.cycle."):
                    assert module in ALLOWED_CYCLE_IMPORTS, (path.name, module)
                    imported = {alias.name for alias in node.names}
                    assert imported <= ALLOWED_CYCLE_IMPORTS[module], (
                        path.name,
                        module,
                        sorted(imported),
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "framework.cycle", (path.name, alias.name)
                    assert not alias.name.startswith("framework.cycle."), (
                        path.name,
                        alias.name,
                    )


def _project_dependency_closure() -> set[str]:
    from importlib import metadata

    text = (ROOT / "pyproject.toml").read_text()
    block = text.split("dependencies = [")[1].split("]")[0]
    roots: list[str] = []
    for line in block.splitlines():
        token = line.strip().strip(",").strip('"').strip("'").strip()
        if token:
            roots.append(re.split(r"[>=<;\s\[]", token)[0])
    want = {name.lower().replace("_", "-") for name in roots if name}
    seen: set[str] = set()
    queue = sorted(want)
    dists = {
        d.metadata["Name"].lower().replace("_", "-"): d
        for d in metadata.distributions()
    }
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        dist = dists.get(name)
        if dist is None:
            continue
        for req in dist.requires or []:
            head, sep, marker = req.partition(";")
            if sep and "extra" in marker:
                continue
            req_name = re.split(r"[>=<;\s\[]", head.strip())[0]
            if req_name:
                queue.append(req_name.lower().replace("_", "-"))
    return seen


_DUMP_SNIPPET = [
    "import sys",
    "import importlib.metadata",
    (
        "known = {m.lower(): ds for m, ds in "
        "importlib.metadata.packages_distributions().items()}"
    ),
    "out = []",
    "for m in sys.modules:",
    "    top = m.split('.')[0]",
    "    mod = sys.modules.get(top)",
    "    f = getattr(mod, '__file__', None) or ''",
    "    known_dists = known.get(top.lower(), [])",
    "    out.append(top + '|' + f + '|' + ','.join(known_dists))",
    "print('\\n'.join(sorted(set(out))))",
]


def _dump_script(extra_imports: str, load_tryit: bool) -> str:
    lines = [extra_imports] if extra_imports else []
    if load_tryit:
        lines += [
            "import framework.tryit.replay",
            "import framework.tryit.text",
            "import framework.tryit.models",
            "import framework.tryit.__main__",
        ]
    return "\n".join(lines + _DUMP_SNIPPET)


def _site_packages_tops(script: str) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    tops: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if "site-packages" not in line:
            continue
        tops.add(parts[0])
    return tops


def _check_loaded_modules(extra_imports: str) -> tuple[set[str], set[str]]:
    started = _site_packages_tops(_dump_script("", load_tryit=False))
    proc = subprocess.run(
        [sys.executable, "-c", _dump_script(extra_imports, load_tryit=True)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    closure = _project_dependency_closure()
    loaded: set[str] = set()
    uncovered: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if "site-packages" not in line:
            continue
        top = parts[0]
        if top in started:
            continue
        dist_list = parts[-1]
        loaded.add(top)
        names = [d.lower().replace("_", "-") for d in dist_list.split(",") if d]
        if not any(name in closure for name in names):
            uncovered.add(top)
    return loaded, uncovered


def test_dependency_guard() -> None:
    loaded, uncovered = _check_loaded_modules("")
    assert "pydantic" in {m.lower() for m in loaded} or "PIL" in loaded
    assert uncovered == set(), sorted(uncovered)


def test_dependency_guard_reports_a_dev_group_module() -> None:
    _loaded, uncovered = _check_loaded_modules("import pytest;")
    assert "pytest" in uncovered


def test_package_data_guard() -> None:
    from importlib import resources

    recording_path = ROOT / "framework" / "tryit" / "recording.json"
    assert recording_path.is_file()
    assert not (ROOT / "framework" / "tryit" / "data").exists()
    raw = recording_path.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n"
    data = (resources.files("framework.tryit") / "recording.json").read_bytes()
    assert json.loads(data)["subject_id"] == "synthetic-subject-021"
    assert "made up" in json.loads(data)["note"]
    from framework.schemas.events import Event
    from framework.tryit import models as models_mod

    recording = models_mod.Recording.model_validate(json.loads(data))
    assert len(recording.events) > 0
    for row in recording.events:
        Event.model_validate(row.model_dump())
    proc = subprocess.run(
        ["git", "check-ignore", "framework/tryit/recording.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode != 0


def test_chart_period_labels_carry_synthetic_within_label_limit() -> None:
    result = _replay()
    assert result.chart.period_labels == (
        "synthetic earlier",
        "synthetic prior",
        "synthetic last",
    )
    for label in result.chart.period_labels:
        assert len(label) <= 18
    assert result.chart.pushes is not None
    assert result.chart.pushes.label == "pushes + PRs"
    order = [s.label for s in result.chart.screen]
    assert "feed" in order
    assert order == sorted(
        order,
        key=lambda name: (
            ["code", "ai", "comms", "feed", "browse", "media"].index(name)
            if name in ["code", "ai", "comms", "feed", "browse", "media"]
            else 99
        ),
    )


def test_replay_uses_ticket_thirteen_builders() -> None:
    from framework.cycle import card_build as builders
    from framework.tryit import replay as replay_mod

    result = _replay()
    recording = replay_mod.load_recording()
    events = tuple(sorted(recording.events, key=lambda e: (e.time, e.id)))
    line = builders.since_line(
        recording.prev_card,
        builders.since_counts(events, recording.prev_card, recording.as_of),
    )
    assert line.startswith("Since ")
    assert result.card.since_line == line
    rebuilt = builders.build_card(
        slot=recording.slot,
        subject_id=recording.subject_id,
        as_of=recording.as_of,
        bucket=None,
        results=[result.builder_result, result.disconnect_result],
        commitments_by_id={item.id: item for item in recording.commitments},
        picks={},
        since_line=line,
    )
    assert rebuilt.card == result.card
    rows = replay_mod.earlier_card_rows(
        tuple(recording.earlier_taps),
        slot=recording.slot,
        subject_id=recording.subject_id,
        as_of=recording.as_of,
        commitments=tuple(recording.commitments),
    )
    tally = builders.build_tally(tuple(recording.earlier_taps), rows)
    assert tally == tuple(result.tally_before)
    assert (
        builders.build_chart_data(
            events,
            recording.as_of,
            tally,
            period_labels=result.chart.period_labels,
        )
        == result.chart
    )


def test_why_trace_rows_are_the_rows_the_metric_counts() -> None:
    from framework.cycle.trace import metric_sources
    from framework.glimmer.metrics import select_winners
    from framework.tryit import replay as replay_mod

    result = _replay()
    _, out, _ = _run([])
    section = _section(
        out, "4. Where a number comes from (synthetic)", "5. Check your own agent"
    )
    assert "github.push" not in section
    assert result.traced_fact is not None
    assert result.traced_fact.id in section
    assert result.traced_fact.statement in out
    assert "no model" in section
    assert "answers with the sentences behind the card" in section
    assert "follow the first sentence back" in section
    assert "10-" not in section
    recording = replay_mod.load_recording()
    events = sorted(recording.events, key=lambda e: (e.time, e.id))
    winners = select_winners(
        tuple(event for event in events if event.collected_at <= result.as_of)
    )
    lines = section.splitlines()
    heads = [
        i
        for i, line in enumerate(lines)
        if re.match(r"^(\S+) is ([\d.]+), counted from these rows:$", line)
    ]
    assert len(heads) == len(result.traced_metrics)
    seen_periods: list[str] = []
    for pos, head in enumerate(heads):
        match = re.match(
            r"^(\S+) is ([\d.]+), counted from these rows:$",
            lines[head],
        )
        assert match is not None
        metric_id, raw_value = match.groups()
        seen_periods.append(metric_id.split(".")[1])
        value = float(raw_value)
        assert value == result.traced_metrics[metric_id]
        end = heads[pos + 1] if pos + 1 < len(heads) else len(lines)
        rows = [line for line in lines[head + 1 : end] if line.startswith("  ")]
        expected = metric_sources(metric_id, result.as_of, winners)
        assert expected is not None, metric_id
        assert len(rows) == len(expected), (metric_id, rows)
        for row in rows:
            row_match = re.search(r"id (\S+)\s*$", row)
            assert row_match is not None, row
            assert row_match.group(1) in [event.source_id for event in expected], row
            assert "a push to" in row
    assert seen_periods == sorted(
        seen_periods, key=lambda name: ["earlier", "prior", "last"].index(name)
    )


def test_readme_holds_published_command_and_verify_closure_unchanged() -> None:
    readme = (ROOT / "README.md").read_text()
    assert (
        "uvx --from git+https://github.com/macayaven/ikigai-loop try-ikigai" in readme
    )
    bundle = json.loads((ROOT / "docs" / "verify" / "bundle.json").read_text())
    from framework.verify import page_bundle

    assert sorted(bundle) == sorted(json.loads(page_bundle.build_bundle_text()))


def test_make_try_target_and_ci_step_exist() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "try:" in makefile
    assert "uv run --no-default-groups try-ikigai" in makefile
    agents = (ROOT / "AGENTS.md").read_text()
    assert "make try" in agents
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "uvx" in ci and "try-ikigai" in ci


def test_section_five_repeats_the_readme_checker_commands_and_link() -> None:
    _, out, _ = _run([])
    section = out.split("5. Check your own agent")[1]
    assert "curl -sLO " + RAW1 in section
    assert UVX1 in section
    assert LINK1 in section
    assert "exit 1" in section
    assert "12 deploys" in section
    assert "7" in section
    for word in ("Muse Glimmer", "Muse Wonder", "Telegram", "calendar"):
        assert word in section
    readme = (ROOT / "README.md").read_text()
    assert ("curl -sLO " + RAW1) in readme
    assert UVX1 in readme
    assert LINK1 in readme


def test_recording_instants_are_old_and_subject_is_synthetic() -> None:
    from importlib import resources

    data = json.loads(
        (resources.files("framework.tryit") / "recording.json").read_bytes()
    )
    assert data["subject_id"] == "synthetic-subject-021"
    for stamp in [data["as_of"], data["slot"], data["prev_card"]]:
        assert stamp < "2026-11-02"
    assert data["prev_card"] == "2026-10-24T13:30:00+02:00"
    assert "made up" in data["note"]
    assert any(
        data["prev_card"] < event["time"] <= data["slot"] for event in data["events"]
    )
    for event in data["events"]:
        if event["type"] == "github.push":
            assert event["tier"] == "public"
        elif event["type"] in ("screen.hour", "calendar.event.created"):
            assert event["tier"] == "private", event["id"]
        if event["type"] == "screen.hour":
            total = sum(event["data"]["minutes_by_category"].values())
            assert total <= 60, event["id"]
            for minutes in event["data"]["minutes_by_category"].values():
                assert minutes % 15 == 0, event["id"]
    feed_totals = []
    for period_events in (
        [
            e
            for e in data["events"]
            if "2026-10-21T16:00:00" <= e["time"] < "2026-10-22T16:00:00"
        ],
        [
            e
            for e in data["events"]
            if "2026-10-22T16:00:00" <= e["time"] < "2026-10-23T16:00:00"
        ],
        [
            e
            for e in data["events"]
            if "2026-10-23T16:00:00" <= e["time"] < "2026-10-24T16:00:00"
        ],
    ):
        feed_totals.append(
            sum(
                e["data"]["minutes_by_category"].get("feed", 0)
                for e in period_events
                if e["type"] == "screen.hour"
            )
        )
    assert len(set(feed_totals)) > 1
