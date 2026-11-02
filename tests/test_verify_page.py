"""Ticket 17a: browser page pins, bundle freshness and doc quotes."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from framework.verify.hardened import HARDENED_LIMITS_NOTE, check_claims
from framework.verify.page_bundle import build_bundle_text

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "verify" / "index.html"
BUNDLE = ROOT / "docs" / "verify" / "bundle.json"
EXAMPLES = ROOT / "docs" / "verify" / "examples"

PINNED_HEADLINE = (
    "If your agent says it shipped 12 deploys and your records say 7, "
    "this page catches it."
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
PINNED_PAGE_LINK = "https://carloscrespomacaya.com/ikigai-loop/verify/"


def test_example_files_give_promised_verdicts() -> None:
    passing = check_claims((EXAMPLES / "pass.json").read_text())
    assert passing.passed is True
    assert passing.limits == HARDENED_LIMITS_NOTE
    assert passing.complete is True

    bad_number = check_claims((EXAMPLES / "false-number.json").read_text())
    assert bad_number.passed is False
    assert [v.code for v in bad_number.violations] == ["L1B_METRIC_VALUE_MISMATCH"]

    leaked = check_claims((EXAMPLES / "leaked-term.json").read_text())
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
    assert "framework/verify/hardened.py" in bundle
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
        "from framework.verify.hardened import check_claims as check; ",
        "import framework; ",
        f"assert framework.__file__.startswith({str(tmp_path)!r}), framework.__file__; ",
        "from pathlib import Path; ",
        f"ex = Path({str(EXAMPLES)!r}); ",
        "assert check((ex / 'pass.json').read_text()).passed is True; ",
        "bad = check((ex / 'false-number.json').read_text()); ",
        "assert [x.code for x in bad.violations] == ['L1B_METRIC_VALUE_MISMATCH']; ",
        "leak = check((ex / 'leaked-term.json').read_text()); ",
        "assert [x.code for x in leak.violations] == ['L1_PRIVATE_TERM']; ",
        (
            'neg = check(\'{"claims": [{"id": "c1", "text": '
            '"Programming in last was not 1.75 hours", "fact_ids": [], '
            '"metric_refs": [{"metric_id": "m1", "value": 1.75}]}], '
            '"facts": {}, "metrics": {"m1": 1.75}, '
            '"labels": {"m1": ["programming", "last"]}}\'); '
        ),
        "assert [x.code for x in neg.violations] == ['L1B_NEGATED_CLAIM']; ",
        (
            'unit = check(\'{"claims": [{"id": "c1", "text": '
            '"Programming in last was 1.75 minutes", "fact_ids": [], '
            '"metric_refs": [{"metric_id": "m1", "value": 1.75}]}], '
            '"facts": {}, "metrics": {"m1": 1.75}, '
            '"labels": {"m1": ["programming", "last"]}, '
            '"units": {"m1": "hours"}}\'); '
        ),
        "assert [x.code for x in unit.violations] == ['L1B_UNIT_MISMATCH']; ",
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
    assert HARDENED_LIMITS_NOTE in page
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
                "https://carloscrespomacaya.com/ikigai-loop/verify/",
            )
        ), clean


def test_readme_quotes() -> None:
    readme = (ROOT / "README.md").read_text()
    assert HARDENED_LIMITS_NOTE in readme
    assert PINNED_UVX in readme
    assert PINNED_RAW in readme
    assert PINNED_PAGE_LINK in readme
    assert "examples/verify/README.md" in readme
    assert "docs/ADAPTER.md" in readme


def test_docs_carry_limits_note() -> None:
    assert (
        HARDENED_LIMITS_NOTE in (ROOT / "examples" / "verify" / "README.md").read_text()
    )
    assert (
        "examples/verify/README.md#every-input-field"
        in (ROOT / "docs" / "ADAPTER.md").read_text()
    )


def test_adapter_prompt_byte_identical() -> None:
    prompt = (
        ROOT / "examples" / "verify" / "foreign" / "adapter-prompt.md"
    ).read_text()
    doc = (ROOT / "docs" / "ADAPTER.md").read_text()
    assert prompt in doc


PINNED_PRIVACY = (
    "Everything runs on your machine: I load the checker once, "
    "then nothing you type is sent anywhere."
)
PINNED_TRY_LINE_1 = (
    "Paste what your agent wrote. Every sentence with a number gets checked."
)
PINNED_TRY_LINE_2 = (
    "For each number, add a row with what your records say: "
    "a name that appears in the sentence, like deploys, and the number. "
    "One record per sentence."
)


def test_privacy_line() -> None:
    page = PAGE.read_text()
    assert PINNED_PRIVACY in page


def test_try_your_own_explanation() -> None:
    page = PAGE.read_text()
    assert PINNED_TRY_LINE_1 in page
    assert PINNED_TRY_LINE_2 in page
    assert "JSON" not in page.split(PINNED_TRY_LINE_2)[0].split("Try your own")[-1]


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


def test_verdict_areas_are_polite_live_regions() -> None:
    page = PAGE.read_text()
    for verdict_id in ("example-verdict", "try-verdict", "json-verdict"):
        match = re.search(r'<div id="' + verdict_id + r'"([^>]*)>', page)
        assert match is not None, verdict_id
        assert 'aria-live="polite"' in match.group(1), verdict_id


def test_example_is_labelled_made_up() -> None:
    page = PAGE.read_text()
    lowered = page.lower()
    assert "made up" in lowered or "made-up" in lowered


def test_example_numbers_match_false_number_example() -> None:
    page = PAGE.read_text()
    data = json.loads(_embedded_examples(page)["ex-false-number"])
    claim_text = data["claims"][0]["text"]
    metric_id = data["claims"][0]["metric_refs"][0]["metric_id"]
    claim_value = data["claims"][0]["metric_refs"][0]["value"]
    metric_value = data["metrics"][metric_id]
    assert claim_text in page
    assert str(claim_value) in page
    assert f"{metric_id}: {metric_value}" in page


def test_made_up_label_sits_before_examples_in_same_row() -> None:
    page = PAGE.read_text()
    assert "Made-up examples:" in page
    rows = re.findall(r'<div class="controls">(.*?)</div>', page, re.DOTALL)
    assert rows, "page must keep a controls row"
    row = next(item for item in rows if "Made-up examples:" in item)
    assert "Made-up examples:" in row
    run_at = row.index('id="run"')
    label_at = row.index("Made-up examples:")
    ex1_at = row.index('id="ex1"')
    ex2_at = row.index('id="ex2"')
    ex3_at = row.index('id="ex3"')
    assert run_at < label_at < ex1_at < ex2_at < ex3_at
    assert "Clean pass" in row
    assert "False number" in row
    assert "Leaked private term" in row


def test_primary_button_waits_for_checker_then_runs() -> None:
    page = PAGE.read_text()
    match = re.search(r'<button id="example-check"([^>]*)>', page)
    assert match is not None
    assert "disabled" not in match.group(1)
    assert "Your result will appear here by itself" in page
    assert "pendingRun = fn" in page
    boot = page.split("async function boot()")[1].split("document.getElementById")[0]
    assert "pendingRun = null" in boot
    assert "pendingRun !== null" in boot
    assert "runExample()" not in boot
    assert "runTryCheck()" not in boot
    assert "runCheck()" not in boot


JARGON_BEFORE_TRY_YOUR_OWN = (
    "JSON",
    "L1B_",
    "claims",
    "facts",
    "metrics",
    "metric_refs",
    "Pyodide",
    "pydantic",
    "reconcile",
    "snapshot",
)


def test_no_jargon_before_try_your_own() -> None:
    page = PAGE.read_text()
    head = page.split("Try your own")[0]
    head = re.sub(r"<script.*?</script>", "", head, flags=re.DOTALL)
    head = re.sub(r"<style.*?</style>", "", head, flags=re.DOTALL)
    head = re.sub(r"<[^>]+>", "", head)
    for word in JARGON_BEFORE_TRY_YOUR_OWN:
        assert word not in head, word


HYPE_WORDS = (
    "thrilled",
    "delighted",
    "leverage",
    "delve",
    "tapestry",
    "robust",
    "seamless",
)


def test_no_hype_words_in_page_or_helper() -> None:
    page = (ROOT / "docs" / "verify" / "index.html").read_text().lower()
    helper = (ROOT / "docs" / "verify" / "verify_page.py").read_text().lower()
    for word in HYPE_WORDS:
        assert word not in page, word
        assert word not in helper, word


def test_page_fetches_helper_by_relative_path() -> None:
    page = PAGE.read_text()
    assert 'fetch("verify_page.py")' in page
    assert "/home/pyodide/verify_page.py" in page
    assert "build_checker_input" in page
    assert "explain_report" in page


def test_loading_line_names_size_and_time() -> None:
    page = PAGE.read_text()
    assert "8 MB" in page
    assert "3 seconds" in page
    assert "15 to 30" in page


def test_loading_steps_keep_the_line() -> None:
    page = PAGE.read_text()
    assert "LOADING_SENTENCE" in page
    definition = next(
        line for line in page.splitlines() if "LOADING_SENTENCE =" in line
    )
    assert "8 MB" in definition
    assert "15 to 30" in definition
    for line in page.splitlines():
        if "Loading the checker" in line or "Starting the checker" in line:
            assert "LOADING_SENTENCE" in line, line


def test_replaced_waiting_area_is_cleared() -> None:
    page = PAGE.read_text()
    assert "pendingArea" in page
    assert "Your result will appear here by itself" in page


def test_failed_load_marks_the_waiting_area() -> None:
    page = PAGE.read_text()
    assert page.count("The checker could not load. Nothing was sent anywhere.") >= 2
    assert "pendingArea" in page


def test_made_up_example_is_a_card() -> None:
    page = PAGE.read_text()
    assert "Made-up example" in page
    assert "Your agent wrote" in page
    assert "Your records say" in page
    assert 'class="card"' in page


def test_verdict_has_word_and_colour_badges() -> None:
    page = PAGE.read_text()
    assert "badge badge-pass" in page
    assert "badge badge-fail" in page
    assert ".badge-pass" in page
    assert ".badge-fail" in page
    assert "claim-passed" not in page


def test_try_verdict_shows_notes_under_each_claim() -> None:
    page = PAGE.read_text()
    assert "notesById" in page
    assert "pairing.sentence_id" in page


def test_unchecked_sentences_list_numbers_only() -> None:
    page = PAGE.read_text()
    assert "has no number in it, so it wasn't checked." in page
    assert "item.sentence_id.slice(1)" in page


def test_hidden_claim_shows_id_locator() -> None:
    page = PAGE.read_text()
    assert '"sentence " + claim.id.slice(1)' in page


def test_json_box_reports_an_empty_build() -> None:
    page = PAGE.read_text()
    assert "The latest check built nothing to show." in page


def test_what_this_checks_names_the_split_rule() -> None:
    page = PAGE.read_text()
    assert "more than one record" in page


def test_verdict_disclosure_is_technical_details_last() -> None:
    page = PAGE.read_text()
    title = "Technical details: codes, and the report the command line prints"
    assert title in page
    assert "Codes and the exact report" not in page
    body = page.split(title)[1].split("</body>")[0]
    assert "examples/verify/README.md" in body or "Check JSON directly" in page


def test_verdict_scrolls_minimally() -> None:
    page = PAGE.read_text()
    assert 'scrollIntoView({block: "nearest"})' in page or (
        "scrollIntoView({ block:" in page and '"nearest"' in page
    )
    assert "root.scrollIntoView();" not in page


def test_only_first_record_row_has_example_placeholders() -> None:
    page = PAGE.read_text()
    assert 'placeholder="e.g. deploys"' in page
    assert 'placeholder="e.g. 7"' in page
    assert page.count('placeholder="e.g. deploys"') == 1
    assert page.count('placeholder="e.g. 7"') == 1
    assert 'placeholder="deploys"' not in page
    assert 'placeholder="7"' not in page


def test_what_this_checks_plain_rules() -> None:
    page = PAGE.read_text()
    section = page.split("What this checks")[1].split("Check JSON directly")[0]
    assert "Every word of a row" in section
    assert "deploy doesn" in section
    assert "synonyms" in section
    assert "1,200" in section
    assert "3.5" in section
    assert "twelve" in section
    assert (
        "Dates and clock times" in section or "dates and clock times" in section.lower()
    )
    assert "percent sign" in section
    assert "3.50" in section
    assert "rose or fell" in section
    assert "whether its numbers match what you typed" in section
    assert "network panel" in section
    assert "no more requests" in section


def test_unchecked_lines_land_inside_verdict_before_details() -> None:
    page = PAGE.read_text()
    assert 'area.append(pe("p", "Sentence "' not in page
    show_body = page.split("function showVerdict")[1].split("function fillPretty")[0]
    assert "Technical details" in show_body
    assert "extraLines" in show_body
    assert show_body.index("extraLines") < show_body.index("Technical details")


def test_limits_note_lives_in_json_details() -> None:
    page = PAGE.read_text()
    assert HARDENED_LIMITS_NOTE in page
    details = page.split("Check JSON directly")[1].split("</details>")[0]
    assert HARDENED_LIMITS_NOTE in details
    assert "examples/verify/README.md" in details
    assert "docs/ADAPTER.md" in details
    assert PINNED_PAGE_LINK in page
    assert "page_render_hardened" in page
    assert "The plain form does not supply units or periods" in page
    before_try = page.split("Try your own")[0]
    assert "cited sources" not in before_try
    section = page.split("What this checks")[1].split("Check JSON directly")[0]
    assert "cited sources" not in section
    assert "labels and direction" not in section


def test_embedded_examples_declare_units_and_periods() -> None:
    embedded = _embedded_examples(PAGE.read_text())
    for block_id in ("ex-pass", "ex-false-number", "ex-leaked-term"):
        data = json.loads(embedded[block_id])
        assert "units" in data, block_id
        assert "periods" in data, block_id
        assert check_claims(json.dumps(data)).complete is True, block_id


def test_ready_line_points_to_example_and_try() -> None:
    page = PAGE.read_text()
    assert (
        "The checker is ready. Press Check this example or try your own below." in page
    )
    assert "Press a button to run it" not in page


def test_try_empty_states_guide_next_step() -> None:
    page = PAGE.read_text()
    assert "Fix the rows above and press Check again." in page
    assert "Paste what your agent wrote first." in page
    assert "None of them has a number to check." in page
    assert "There is nothing to check yet." not in page


def test_split_rule_has_example() -> None:
    page = PAGE.read_text()
    section = page.split("What this checks")[1].split("Check JSON directly")[0]
    assert "more than one record" in section
    assert "We shipped 12 deploys and closed 40 tickets" in section
    assert "so split it into two sentences" in section


def test_json_summaries_name_audience() -> None:
    page = PAGE.read_text()
    assert "Show the JSON (for scripts)" in page
    assert "Check JSON directly (for developers)" in page


def test_source_line_names_open_source() -> None:
    page = PAGE.read_text()
    assert "The page and the checker it runs are open source in" in page
    assert '<a href="https://github.com/macayaven/ikigai-loop">' in page
    assert "Bad input shows a short message and sends nothing." in page
