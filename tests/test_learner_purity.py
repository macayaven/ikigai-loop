"""Ticket 15a: the learner package keeps its import and purity bounds."""

import ast
from pathlib import Path

LEARNER_DIR = Path(__file__).resolve().parent.parent / "framework" / "learner"

ALLOWED_IMPORTS = {
    "argparse",
    "datetime",
    "fractions",
    "functools",
    "json",
    "math",
    "pathlib",
    "pydantic",
    "random",
    "typing",
}

ALLOWED_FROM = {
    "collections.abc",
    "framework.learner",
    "framework.learner.beta",
    "framework.learner.policy",
    "framework.learner.schemas",
    "framework.learner.scoring",
    "framework.learner.simulate",
    "framework.schemas.base",
    "framework.schemas.events",
    "pydantic",
    "typing",
}

FILESYSTEM_MODULES = {"pathlib", "os", "shutil", "open"}

CLOCK_ENV_ATTRS = {"now", "utcnow", "today", "environ", "getenv"}


def _trees() -> dict[str, ast.AST]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(LEARNER_DIR.glob("*.py"))
    }


def test_package_holds_exactly_seven_files() -> None:
    names = sorted(p.name for p in LEARNER_DIR.glob("*.py"))
    assert names == [
        "__init__.py",
        "__main__.py",
        "beta.py",
        "policy.py",
        "schemas.py",
        "scoring.py",
        "simulate.py",
    ]


def test_import_allowlist() -> None:
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in ALLOWED_IMPORTS, (
                        name,
                        alias.name,
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module in ALLOWED_FROM or (
                    node.module is not None
                    and node.module.split(".")[0] in ALLOWED_IMPORTS
                ), (name, node.module)


def test_random_only_in_simulate() -> None:
    for name, tree in _trees().items():
        hits = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            and any(a.name == "random" for a in node.names)
        ]
        if name == "simulate.py":
            assert hits
        else:
            assert not hits, name


def _filesystem_hits(tree: ast.AST) -> list[ast.AST]:
    hits: list[ast.AST] = []
    for node in ast.walk(tree):
        plain = isinstance(node, ast.Import) and any(
            a.name.split(".")[0] in FILESYSTEM_MODULES for a in node.names
        )
        from_form = (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.split(".")[0] in FILESYSTEM_MODULES
        )
        if plain or from_form:
            hits.append(node)
    return hits


def test_filesystem_only_in_main() -> None:
    for name, tree in _trees().items():
        hits = _filesystem_hits(tree)
        if name == "__main__.py":
            assert hits
        else:
            assert not hits, name


def test_no_clock_or_env_access() -> None:
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in CLOCK_ENV_ATTRS:
                raise AssertionError((name, node.attr))


def test_no_open_call_outside_main() -> None:
    for name, tree in _trees().items():
        if name == "__main__.py":
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ):
                raise AssertionError(name)


def test_simulate_rng_only_calls_random() -> None:
    tree = _trees()["simulate.py"]
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "rng"
    ]
    assert hits
    assert all(node.attr == "random" for node in hits)
