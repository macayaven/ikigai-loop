"""Ticket 15b: shared gate, prompt and tree identity (D4-D6).

The file list comes from R1b's constant so the two receipts cannot drift.
Unlike R1b's function, ``gate_identity`` takes a ``root`` argument for
temp-repo tests and does not itself refuse on dirty files: dirtiness is
D6's separate refusal, so identity stays computable for tests and for
``--summary``'s "tree gate differs" line.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from pathlib import Path

from evals.r1b import GATE_SOURCE_FILES, GateIdentityError

PROMPT_SOURCE_FILE = "framework/proposal/prompt.py"
IDENTITY_FILES = (*GATE_SOURCE_FILES, PROMPT_SOURCE_FILE)

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _git(root: Path | str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateIdentityError("unknown-gate-identity") from exc
    if result.returncode != 0:
        raise GateIdentityError("unknown-gate-identity")
    return result.stdout


def content_hash(root: Path | str, files: tuple[str, ...]) -> str:
    """Hash file bytes: per file in sorted order, name + NUL + bytes + NUL."""
    base = Path(root)
    digest = hashlib.sha256()
    for name in sorted(files):
        try:
            data = (base / name).read_bytes()
        except OSError as exc:
            raise GateIdentityError("unknown-gate-identity") from exc
        digest.update(name.encode() + b"\x00" + data + b"\x00")
    return digest.hexdigest()


def gate_identity(root: Path | str = _DEFAULT_ROOT) -> tuple[str, str]:
    """(commit, content hash) over R1b's eight gate files."""
    commit = _git(root, ["log", "-1", "--format=%H", "--", *GATE_SOURCE_FILES]).strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise GateIdentityError("unknown-gate-identity")
    return commit, content_hash(root, GATE_SOURCE_FILES)


def prompt_identity(root: Path | str = _DEFAULT_ROOT) -> str:
    """Content hash over the single prompt file, same construction."""
    return content_hash(root, (PROMPT_SOURCE_FILE,))


def dirty_files(
    root: Path | str = _DEFAULT_ROOT,
    files: tuple[str, ...] = IDENTITY_FILES,
) -> tuple[str, ...]:
    """Repo-relative names among ``files`` with uncommitted changes."""
    out = _git(root, ["status", "--porcelain", "--", *files])
    names: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        names.add(path.strip().strip('"'))
    return tuple(sorted(names))


def _module_candidate_files(root: Path, module: str) -> list[str]:
    """Existing framework files for a module name, if any."""
    if not module.startswith("framework"):
        return []
    parts = module.split(".")
    found: list[str] = []
    module_path = root.joinpath(*parts).with_suffix(".py")
    if module_path.is_file():
        try:
            found.append(module_path.relative_to(root).as_posix())
        except ValueError:
            pass
    package_init = root.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        try:
            found.append(package_init.relative_to(root).as_posix())
        except ValueError:
            pass
    return found


def _package_inits(root: Path, rel: str) -> list[str]:
    """Package __init__ files that run when ``rel`` is imported."""
    parts = Path(rel).with_suffix("").parts
    if not parts or parts[0] != "framework":
        return []
    if parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    found: list[str] = []
    for index in range(1, len(parts) + 1):
        init = root.joinpath(*parts[:index], "__init__.py")
        if init.is_file():
            try:
                found.append(init.relative_to(root).as_posix())
            except ValueError:
                pass
    return found


def _imported_modules(path: Path, module_name: str) -> set[str]:
    """Module names imported by one file, including inside functions."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    if path.name == "__init__.py":
        package = module_name
    else:
        package = module_name.rpartition(".")[0]
    package_parts = package.split(".") if package else []
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(";")[0].strip()
                if not name:
                    continue
                parts = name.split(".")
                for index in range(1, len(parts) + 1):
                    found.add(".".join(parts[:index]))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.add(node.module)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        found.add(f"{node.module}.{alias.name}")
            else:
                up = node.level - 1
                if up > len(package_parts):
                    continue
                prefix = package_parts[: len(package_parts) - up]
                if node.module:
                    base = ".".join([*prefix, node.module]) if prefix else node.module
                    found.add(base)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        found.add(f"{base}.{alias.name}")
                else:
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        name = ".".join([*prefix, alias.name]) if prefix else alias.name
                        found.add(name)
    return found


def closure_files(root: Path | str = _DEFAULT_ROOT) -> tuple[str, ...]:
    """Every file under framework/ reachable from the nine identity files.

    Reads the working tree, follows import statements including those
    inside functions, resolves relative imports, and includes the
    package __init__ files that run on import. Returns sorted
    repo-relative paths.
    """
    base = Path(root)
    seeds = (*GATE_SOURCE_FILES, PROMPT_SOURCE_FILE)
    seen: set[str] = set()
    for seed in seeds:
        seen.add(seed)
        for init in _package_inits(base, seed):
            seen.add(init)
    queue = sorted(seen)
    while queue:
        current = queue.pop()
        current_path = base / current
        if not current_path.is_file():
            continue
        module_name = current[:-3].replace("/", ".")
        for module in _imported_modules(current_path, module_name):
            if not module.startswith("framework"):
                continue
            for candidate in _module_candidate_files(base, module):
                if candidate not in seen:
                    seen.add(candidate)
                    for init in _package_inits(base, candidate):
                        if init not in seen:
                            seen.add(init)
                            queue.append(init)
                    queue.append(candidate)
    return tuple(sorted(seen))


def closure_identity(root: Path | str = _DEFAULT_ROOT) -> str:
    """Content hash over the full import closure, same construction."""
    return content_hash(root, closure_files(root))


def tree_identity(root: Path | str = _DEFAULT_ROOT) -> tuple[str, bool]:
    """(HEAD commit, whole-tree dirty flag); never refuses."""
    commit = _git(root, ["rev-parse", "HEAD"]).strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise GateIdentityError("unknown-gate-identity")
    dirty = bool(_git(root, ["status", "--porcelain"]).strip())
    return commit, dirty
