"""Ticket 15b: shared gate/prompt/tree identity tests (D4-D6).

No network, no model. Git identity tests use temp repos plus one equality
test against R1b on this tree.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import evals.gate_identity as identity
from evals import r1b

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (args, result.stderr)
    return result.stdout


def _init_repo(repo: Path, files: dict[str, str]) -> str:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _git(repo, "add", name)
    _git(repo, "commit", "-qm", "init")
    return _git(repo, "rev-parse", "HEAD").strip()


def _eight_files() -> dict[str, str]:
    return {name: f"contents of {name}\n" for name in r1b.GATE_SOURCE_FILES}


def test_file_list_is_r1b_constant() -> None:
    assert identity.GATE_SOURCE_FILES is r1b.GATE_SOURCE_FILES
    assert len(identity.GATE_SOURCE_FILES) == 8
    assert identity.PROMPT_SOURCE_FILE == "framework/proposal/prompt.py"
    assert len(identity.IDENTITY_FILES) == 9
    assert set(identity.IDENTITY_FILES) == {
        *r1b.GATE_SOURCE_FILES,
        "framework/proposal/prompt.py",
    }


def test_digest_construction_by_hand_on_made_up_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"print('a')\n")
    (tmp_path / "b.py").write_bytes(b"print('b')\n")
    digest = hashlib.sha256()
    for name in ("a.py", "b.py"):
        data = (tmp_path / name).read_bytes()
        digest.update(name.encode() + b"\x00" + data + b"\x00")
    assert identity.content_hash(tmp_path, ("b.py", "a.py")) == digest.hexdigest()


def test_gate_identity_matches_hand_hash_in_temp_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _init_repo(repo, _eight_files())
    found_commit, found_hash = identity.gate_identity(repo)
    assert found_commit == commit
    digest = hashlib.sha256()
    for name in sorted(r1b.GATE_SOURCE_FILES):
        data = (repo / name).read_bytes()
        digest.update(name.encode() + b"\x00" + data + b"\x00")
    assert found_hash == digest.hexdigest()


def test_gate_identity_stays_computable_on_dirty_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _init_repo(repo, _eight_files())
    first = next(iter(r1b.GATE_SOURCE_FILES))
    (repo / first).write_text("changed\n", encoding="utf-8")
    found_commit, _found_hash = identity.gate_identity(repo)
    assert found_commit == commit
    assert identity.dirty_files(repo) == (first,)


def test_prompt_identity_is_single_file_construction(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo, _eight_files())
    prompt = repo / identity.PROMPT_SOURCE_FILE
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_bytes(b"prompt bytes\n")
    digest = hashlib.sha256()
    digest.update(
        identity.PROMPT_SOURCE_FILE.encode() + b"\x00" + b"prompt bytes\n" + b"\x00"
    )
    assert identity.prompt_identity(repo) == digest.hexdigest()


def test_dirty_check_covers_exactly_the_nine_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo, _eight_files())
    assert identity.dirty_files(repo) == ()
    (repo / "unrelated.txt").write_text("new\n", encoding="utf-8")
    assert identity.dirty_files(repo) == ()
    prompt = repo / identity.PROMPT_SOURCE_FILE
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("untracked prompt\n", encoding="utf-8")
    assert identity.dirty_files(repo) == (identity.PROMPT_SOURCE_FILE,)


def test_gate_identity_equals_r1b_on_this_tree() -> None:
    assert identity.gate_identity(REPO_ROOT) == r1b.gate_identity()


def test_tree_fields_never_refuse(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _init_repo(repo, _eight_files())
    assert identity.tree_identity(repo) == (commit, False)
    (repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")
    assert identity.tree_identity(repo) == (commit, True)


def test_closure_equals_runtime_loaded_set() -> None:
    import sys

    code = (
        "import pathlib, sys\n"
        "names = ["
        "'framework.briefing.gate', 'framework.briefing.labels', "
        "'framework.briefing.numbers', 'framework.briefing.context', "
        "'framework.briefing.schemas', 'framework.proposal.assembly', "
        "'framework.proposal.schemas', 'framework.proposal.core', "
        "'framework.proposal.prompt']\n"
        "for name in names:\n"
        "    __import__(name)\n"
        "root = pathlib.Path('.').resolve()\n"
        "out = set()\n"
        "for name, module in sys.modules.items():\n"
        "    if name == 'framework' or name.startswith('framework.'):\n"
        "        found = getattr(module, '__file__', None)\n"
        "        if not found:\n"
        "            continue\n"
        "        path = pathlib.Path(found).resolve()\n"
        "        try:\n"
        "            relative = path.relative_to(root)\n"
        "        except ValueError:\n"
        "            continue\n"
        "        if relative.parts[0] == 'framework' and path.suffix == '.py':\n"
        "            out.add(relative.as_posix())\n"
        "print('\\n'.join(sorted(out)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    runtime = tuple(sorted(line for line in result.stdout.splitlines() if line.strip()))
    assert runtime == identity.closure_files(REPO_ROOT)
    assert len(runtime) == 47


def _closure_repo_files() -> dict[str, str]:
    files = _eight_files()
    gate = next(iter(r1b.GATE_SOURCE_FILES))
    files[gate] = (
        "from framework.proposal.hour import fallback_window_codes\nVALUE = 1\n"
    )
    files["framework/proposal/hour.py"] = (
        "def fallback_window_codes():\n    return ()\n"
    )
    files[identity.PROMPT_SOURCE_FILE] = "prompt bytes\n"
    return files


def test_closure_changes_when_only_closure_module_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo, _closure_repo_files())
    helper = "framework/proposal/hour.py"
    assert helper in identity.closure_files(repo)
    assert helper not in r1b.GATE_SOURCE_FILES
    assert helper != identity.PROMPT_SOURCE_FILE
    _commit, gate_before = identity.gate_identity(repo)
    closure_before = identity.closure_identity(repo)
    (repo / helper).write_text(
        "def fallback_window_codes():\n    return ('changed',)\n",
        encoding="utf-8",
    )
    _commit, gate_after = identity.gate_identity(repo)
    assert gate_after == gate_before
    assert identity.closure_identity(repo) != closure_before
    assert identity.dirty_files(repo, identity.closure_files(repo)) == (helper,)
