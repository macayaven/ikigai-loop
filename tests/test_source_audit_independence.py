"""Source-audit independence (Ticket E2 plan, independence file)."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "source_audit"


def _iter_py_files():
    return sorted(PACKAGE.glob("*.py"))


def test_ast_scan_finds_no_framework_import():
    assert PACKAGE.is_dir(), "source_audit package missing"
    hits = []
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "framework" or alias.name.startswith("framework."):
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module == "framework" or (
                    node.module is not None and node.module.startswith("framework.")
                ):
                    hits.append((path.name, node.module))
            elif isinstance(node, ast.Call):
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in ("__import__", "import_module") and node.args:
                    arg = node.args[0]
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and (
                            arg.value == "framework"
                            or arg.value.startswith("framework.")
                        )
                    ):
                        hits.append((path.name, arg.value))
    assert hits == []


def test_subprocess_imports_package_with_framework_poisoned():
    code = (
        "import sys; sys.modules['framework'] = None; "
        "from source_audit import __main__ as m; "
        "code = m.main(['negative-control']); "
        "assert not any(k.startswith('framework.') for k in sys.modules), "
        "sorted(k for k in sys.modules if k.startswith('framework.')); "
        "sys.exit(code)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
