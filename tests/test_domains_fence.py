"""Ticket 26: fence tests for the domain pack isolation.

The domain code is throwaway scaffolding around the live loop: it may
only reach its own modules plus the checker, proposal and repair
contracts, and nothing on the live path may reach it.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ALLOWED_NON_STDLIB = frozenset(
    {
        "framework.domains",
        "framework.verify.core",
        "framework.verify.hardened",
        "framework.verify.repair",
        "framework.proposal.core",
        "framework.proposal.muse_client",
        "framework.proposal.defaults",
        "pydantic",
    }
)


def _imported_modules(tree: ast.AST, package: str) -> list[str]:
    """Every absolute module name one file imports."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.append(package)
            elif node.module:
                modules.append(node.module)
    return modules


def test_domain_code_reaches_only_what_it_needs() -> None:
    """Every import under framework/domains/ is allowed."""
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    package = ROOT / "framework" / "domains"
    files = sorted(package.glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree, "framework.domains"):
            root = module.split(".")[0]
            assert (
                root in stdlib
                or module in _ALLOWED_NON_STDLIB
                or module.startswith("framework.domains.")
            ), (str(path), module)


def test_nothing_on_live_path_reaches_domain_code() -> None:
    """No file outside framework/domains/ or the eval shell imports it."""
    targets: list[Path] = []
    for path in sorted((ROOT / "framework").rglob("*.py")):
        if path.relative_to(ROOT / "framework").parts[0] == "domains":
            continue
        targets.append(path)
    for path in sorted((ROOT / "evals").glob("*.py")):
        if path.name == "domains.py" or path.name.startswith("domains_"):
            continue
        targets.append(path)
    assert targets
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree, "framework"):
            assert module != "framework.domains" and not module.startswith(
                "framework.domains."
            ), (str(path), module)


def test_readme_worked_case_still_fails_on_value() -> None:
    """The README sample (12 deploys against a record of 7) still fails."""
    from framework.verify.hardened import check_claims

    payload = json.loads(
        (ROOT / "examples" / "verify" / "input.json").read_text(encoding="utf-8")
    )
    report = check_claims(payload)
    assert not report.passed
    assert "L1B_METRIC_VALUE_MISMATCH" in [item.code for item in report.violations]
