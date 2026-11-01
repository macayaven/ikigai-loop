"""Ticket 17a: browser page pins, bundle freshness and doc quotes."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from framework.verify import LIMITS_NOTE, verify_claims
from framework.verify.page_bundle import build_bundle_text

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "verify" / "index.html"
BUNDLE = ROOT / "docs" / "verify" / "bundle.json"
EXAMPLES = ROOT / "docs" / "verify" / "examples"

PINNED_HEADLINE = (
    "Give it your agent's claims and your own records as JSON. "
    "See which numbers and sources don't reconcile."
)
PINNED_PYODIDE = "0.27.7"
PINNED_JSDELIVR = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js"
PINNED_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' "
    "https://cdn.jsdelivr.net; connect-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)
PINNED_UVX = (
    "uvx --from git+https://github.com/macayaven/ikigai-loop verify-claims input.json"
)
PINNED_RAW = "https://raw.githubusercontent.com/macayaven/ikigai-loop/main/examples/verify/input.json"
PINNED_PAGE_LINK = "https://macayaven.github.io/ikigai-loop/verify/"


def test_example_files_give_promised_verdicts() -> None:
    passing = verify_claims((EXAMPLES / "pass.json").read_text())
    assert passing.passed is True
    assert passing.limits == LIMITS_NOTE

    bad_number = verify_claims((EXAMPLES / "false-number.json").read_text())
    assert bad_number.passed is False
    assert [v.code for v in bad_number.violations] == ["L1B_METRIC_VALUE_MISMATCH"]

    leaked = verify_claims((EXAMPLES / "leaked-term.json").read_text())
    assert leaked.passed is False
    assert [v.code for v in leaked.violations] == ["L1_PRIVATE_TERM"]
    assert "harborlight ledger" not in "\n".join(v.message for v in leaked.violations)


def _embedded_examples(page: str) -> dict[str, str]:
    found = dict(
        re.findall(
            r'<script type="application/json" id="([^"]+)">(.*?)</script>',
            page,
            re.DOTALL,
        )
    )
    assert set(found) == {"ex-pass", "ex-false-number", "ex-leaked-term"}
    return found


def test_embedded_page_examples_equal_the_files() -> None:
    page = PAGE.read_text()
    embedded = _embedded_examples(page)
    for block_id, filename in (
        ("ex-pass", "pass.json"),
        ("ex-false-number", "false-number.json"),
        ("ex-leaked-term", "leaked-term.json"),
    ):
        assert json.loads(embedded[block_id]) == json.loads(
            (EXAMPLES / filename).read_text()
        )


def test_bundle_is_fresh() -> None:
    assert BUNDLE.read_text() == build_bundle_text(), (
        "docs/verify/bundle.json is stale: run make verify-page"
    )


def test_bundle_keys_equal_the_closure() -> None:
    bundle = json.loads(BUNDLE.read_text())
    assert "framework/verify/core.py" in bundle
    fresh = json.loads(build_bundle_text())
    assert sorted(bundle) == sorted(fresh)
    assert bundle == fresh


def test_subprocess_unpack_gives_promised_verdicts(tmp_path: Path) -> None:
    bundle = json.loads(BUNDLE.read_text())
    for relpath, source in bundle.items():
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    lines = [
        f"import sys; sys.path.insert(0, {str(tmp_path)!r}); ",
        "import framework.verify as v; ",
        "import framework; ",
        f"assert framework.__file__.startswith({str(tmp_path)!r}), framework.__file__; ",
        "from pathlib import Path; ",
        f"ex = Path({str(EXAMPLES)!r}); ",
        "assert v.verify_claims((ex / 'pass.json').read_text()).passed is True; ",
        "bad = v.verify_claims((ex / 'false-number.json').read_text()); ",
        "assert [x.code for x in bad.violations] == ['L1B_METRIC_VALUE_MISMATCH']; ",
        "leak = v.verify_claims((ex / 'leaked-term.json').read_text()); ",
        "assert [x.code for x in leak.violations] == ['L1_PRIVATE_TERM']; ",
        "print('ok')",
    ]
    proc = subprocess.run(
        [sys.executable, "-c", "".join(lines)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_page_pins() -> None:
    page = PAGE.read_text()
    assert PINNED_HEADLINE in page
    assert LIMITS_NOTE in page
    assert PINNED_PYODIDE in page
    assert PINNED_JSDELIVR in page
    assert PINNED_CSP in page
    assert 'fetch("bundle.json")' in page or "fetch('bundle.json')" in page
    assert "textContent" in page
    for token in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
    ):
        assert token not in page, token
    assert ".whl" not in page
    assert "site-packages" not in page
    urls = re.findall(r"https://[^\s\"'<>]+", page)
    assert urls, "page must link the pinned CDN address"
    assert PINNED_JSDELIVR in urls
    for url in urls:
        clean = url.rstrip(";")
        assert clean == "https://cdn.jsdelivr.net" or clean.startswith(
            (
                "https://cdn.jsdelivr.net/pyodide/v0.27.7/",
                "https://github.com/macayaven/",
            )
        ), clean


def test_readme_quotes() -> None:
    readme = (ROOT / "README.md").read_text()
    assert LIMITS_NOTE in readme
    assert PINNED_UVX in readme
    assert PINNED_RAW in readme
    assert PINNED_PAGE_LINK in readme
    assert "examples/verify/README.md" in readme
    assert "docs/ADAPTER.md" in readme


def test_docs_carry_limits_note() -> None:
    assert LIMITS_NOTE in (ROOT / "examples" / "verify" / "README.md").read_text()
    assert LIMITS_NOTE in (ROOT / "docs" / "ADAPTER.md").read_text()


def test_adapter_prompt_byte_identical() -> None:
    prompt = (
        ROOT / "examples" / "verify" / "foreign" / "adapter-prompt.md"
    ).read_text()
    doc = (ROOT / "docs" / "ADAPTER.md").read_text()
    assert prompt in doc


RECORDS_PARAGRAPH = (
    '<p class="note">The input holds your agent\'s claims plus your own records: '
    "facts and metrics come from your system of record, never from the "
    "agent's output. "
    '<a href="https://github.com/macayaven/ikigai-loop/blob/main/examples/verify/README.md">'
    "Every field</a> is in the worked example, and "
    '<a href="https://github.com/macayaven/ikigai-loop/blob/main/docs/ADAPTER.md">'
    "the adapter recipe</a> maps another shape to it.</p>"
)


def test_page_names_records_first() -> None:
    page = PAGE.read_text()
    machine = page.index("Everything runs on your machine")
    assert page.index(RECORDS_PARAGRAPH) > machine


def test_page_links_records_and_recipe() -> None:
    page = PAGE.read_text()
    assert "examples/verify/README.md" in page
    assert "docs/ADAPTER.md" in page


def test_example_buttons_fill_and_run() -> None:
    page = PAGE.read_text()
    assert "Checking…" not in page
    for button, block in (
        ("ex1", "ex-pass"),
        ("ex2", "ex-false-number"),
        ("ex3", "ex-leaked-term"),
    ):
        match = re.search(
            r'getElementById\("'
            + button
            + r'"\)\.addEventListener\("click", \(\) => \{([^}]*)\}\)',
            page,
        )
        assert match is not None, button
        body = match.group(1)
        assert block in body, button
        assert "runCheck(" in body, button


def test_report_pane_is_live_and_margins_line_up() -> None:
    page = PAGE.read_text()
    assert "pre { margin: 0; }" in page
    match = re.search(r'<pre id="report"([^>]*)>', page)
    assert match is not None
    assert 'aria-live="polite"' in match.group(1)
