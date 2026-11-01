"""Every Inspect task file under evals/ runs under make eval.

The Makefile lists task files in EVAL_FILES and the eval recipe runs them
through evals/run_tasks.py, which exits non-zero on an errored task or any
incorrect sample. The tests below pin both sides: the listing (AST-based
task detection over the whole evals/ tree, compared in both directions)
and the runner (subprocess runs on small throwaway task files).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_TASKS = REPO_ROOT / "evals" / "run_tasks.py"
MOCK_COMPLETION = "Default output from mockllm/model"


def _makefile_eval_files() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^EVAL_FILES\s*=\s*(.+)$", text, re.MULTILINE)
    assert match is not None, "Makefile must define EVAL_FILES"
    return set(match.group(1).split())


def _is_task_decorator(decorator: ast.expr) -> bool:
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(func, ast.Name):
        return func.id == "task"
    if isinstance(func, ast.Attribute):
        return func.attr == "task"
    return False


def find_task_files(directory: Path) -> set[str]:
    """Task files under ``directory``: .py files with a @task decorator.

    Parsed with ``ast`` so a mention of ``@task`` inside a docstring or
    comment does not count. Paths are relative to ``directory``.
    """
    found = set()
    for path in sorted(directory.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_is_task_decorator(dec) for dec in node.decorator_list):
                found.add(path.relative_to(directory).as_posix())
                break
    return found


def test_eval_task_files_are_listed_in_makefile() -> None:
    listed = _makefile_eval_files()
    assert "evals/hello.py" in listed
    task_files = {f"evals/{name}" for name in find_task_files(REPO_ROOT / "evals")}
    assert task_files == listed
    for entry in listed:
        assert (REPO_ROOT / entry).exists(), f"listed eval file is missing: {entry}"


def test_eval_recipe_runs_listed_files() -> None:
    lines = (REPO_ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("eval:"))
    recipe = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            recipe.append(line)
        elif not line.strip():
            continue
        else:
            break
    assert recipe, "eval target has no recipe lines"
    assert any("$(EVAL_FILES)" in line for line in recipe)


def test_find_task_files_uses_ast(tmp_path: Path) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "nested_task.py").write_text(
        'from inspect_ai import task\n\n@task(name="x")\ndef my_task(): ...\n',
        encoding="utf-8",
    )
    (tmp_path / "docstring_only.py").write_text(
        '"""Mentions @task but defines no task."""\n\n\ndef helper(): ...\n',
        encoding="utf-8",
    )
    found = find_task_files(tmp_path)
    assert "sub/nested_task.py" in found
    assert "docstring_only.py" not in found


def _task_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg" / "cache")
    env["INSPECT_TRACE_FILE"] = str(tmp_path / "trace.log")
    return env


def _write_task(tmp_path: Path, name: str, body: str) -> str:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return name


_PASS_BODY = f"""\
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


@task
def tmp_pass() -> Task:
    return Task(
        dataset=[Sample(id="s-pass-1", input="Say hello.", target="{MOCK_COMPLETION}")],
        solver=[generate()],
        scorer=exact(),
    )
"""

_FAIL_BODY = """\
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


@task
def tmp_fail() -> Task:
    return Task(
        dataset=[Sample(id="s-fail-1", input="Say hello.", target="the mock never says this")],
        solver=[generate()],
        scorer=exact(),
    )
"""

_BOOM_BODY = f"""\
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState, generate


@scorer(metrics=[])
def boom() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        raise RuntimeError("boom")

    return score


@task
def tmp_boom() -> Task:
    return Task(
        dataset=[Sample(id="s-boom-1", input="Say hello.", target="{MOCK_COMPLETION}")],
        solver=[generate()],
        scorer=boom(),
    )
"""


def _run_tasks(tmp_path: Path, *files: str) -> subprocess.CompletedProcess[str]:
    # Task files go in as names relative to cwd: inspect resolves them
    # against the working directory and rejects absolute paths.
    return subprocess.run(
        [sys.executable, str(RUN_TASKS), "--log-dir", str(tmp_path / "logs"), *files],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        env=_task_env(tmp_path),
    )


def test_run_tasks_passes_on_correct_sample(tmp_path: Path) -> None:
    proc = _run_tasks(tmp_path, _write_task(tmp_path, "task_pass.py", _PASS_BODY))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_run_tasks_fails_and_names_bad_sample(tmp_path: Path) -> None:
    proc = _run_tasks(tmp_path, _write_task(tmp_path, "task_fail.py", _FAIL_BODY))
    assert proc.returncode != 0
    assert "s-fail-1" in proc.stdout + proc.stderr


def test_run_tasks_fails_when_scorer_raises(tmp_path: Path) -> None:
    proc = _run_tasks(tmp_path, _write_task(tmp_path, "task_boom.py", _BOOM_BODY))
    assert proc.returncode != 0
    assert "log status is error" in proc.stdout + proc.stderr


_NOTASK_BODY = '"""A module with no tasks in it."""\n\n\ndef helper(): ...\n'

_BROKEN_BODY = "def broken(:\n"


def test_run_tasks_fails_when_file_has_no_tasks(tmp_path: Path) -> None:
    proc = _run_tasks(
        tmp_path,
        _write_task(tmp_path, "task_pass.py", _PASS_BODY),
        _write_task(tmp_path, "task_empty.py", _NOTASK_BODY),
    )
    assert proc.returncode != 0
    assert "task_empty.py" in proc.stdout + proc.stderr


def test_run_tasks_fails_when_file_has_syntax_error(tmp_path: Path) -> None:
    proc = _run_tasks(
        tmp_path,
        _write_task(tmp_path, "task_pass.py", _PASS_BODY),
        _write_task(tmp_path, "task_broken.py", _BROKEN_BODY),
    )
    assert proc.returncode != 0
    assert "task_broken.py" in proc.stdout + proc.stderr


def test_run_tasks_fails_on_mixed_pass_and_fail(tmp_path: Path) -> None:
    proc = _run_tasks(
        tmp_path,
        _write_task(tmp_path, "task_pass.py", _PASS_BODY),
        _write_task(tmp_path, "task_fail.py", _FAIL_BODY),
    )
    assert proc.returncode != 0


def test_run_tasks_fails_with_no_files(tmp_path: Path) -> None:
    proc = _run_tasks(tmp_path)
    assert proc.returncode != 0
