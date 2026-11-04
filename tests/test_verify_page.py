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

PINNED_HEADLINE = "Catch the AI"
PINNED_SUBHEAD = '"Strawberry" has three r\'s. AI once said two.'
PINNED_TAGLINE = (
    "Six sentences an AI wrote. Some hide a trap. Can you beat the checker?"
)
PINNED_PLAIN_LIMIT = (
    "It only compares numbers with the card's names, "
    "so it doesn't check units, time windows or words like rose and fell."
)
PINNED_CHECKED_NONE = (
    "What it checked: nothing, because the sentence uses none of the card's names."
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
    assert f"<h1>{PINNED_HEADLINE}</h1>" in page
    assert PINNED_SUBHEAD in page
    assert PINNED_TAGLINE in page
    assert "Paste a sentence your AI wrote" not in page
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


PINNED_PRIVACY = "It runs in your browser; nothing you type leaves your device."
PINNED_MAKE_HEADING = "Make your own round"
PINNED_MAKE_SUB = (
    "Give a card a few numbers, then write a sentence about them, "
    "or paste one an AI told you. The checker tells you if the sentence gets your numbers wrong."
)


def test_privacy_line() -> None:
    page = PAGE.read_text()
    assert PINNED_PRIVACY in page


def test_make_your_own_round_heading_and_sub_are_pinned() -> None:
    page = PAGE.read_text()
    assert f'<h2 id="try-your-own">{PINNED_MAKE_HEADING}</h2>' in page
    assert PINNED_MAKE_SUB in page


def test_steps_label_the_plain_form_in_order() -> None:
    page = PAGE.read_text()
    step_1 = (
        '<p class="step-label"><span class="step-num" aria-hidden="true">1</span>'
        "<strong>The card: your record, the truth</strong></p>"
    )
    step_2 = (
        '<p class="step-label"><span class="step-num" aria-hidden="true">2</span>'
        '<label for="agent-text"><strong>The sentence: what the AI wrote, '
        "checked against the card</strong></label></p>"
    )
    step_3 = (
        '<p class="step-label"><span class="step-num" aria-hidden="true">3</span>'
        "<strong>Check it</strong></p>"
    )
    assert step_1 in page
    assert step_2 in page
    assert step_3 in page
    assert page.index(step_1) < page.index(step_2) < page.index(step_3)
    assert "<th" in page and "What" in page and "How many" in page


def test_step_labels_name_the_card_as_truth() -> None:
    page = PAGE.read_text()
    assert "The card: your record, the truth" in page
    assert "The sentence: what the AI wrote, checked against the card" in page
    assert '<label for="agent-text">' in page


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
    for verdict_id in ("try-verdict", "json-verdict"):
        match = re.search(r'<div id="' + verdict_id + r'"([^>]*)>', page)
        assert match is not None, verdict_id
        assert 'aria-live="polite"' in match.group(1), verdict_id
    assert "example-verdict" not in page


def test_example_is_labelled_made_up() -> None:
    page = PAGE.read_text()
    lowered = page.lower()
    assert "made up" in lowered or "made-up" in lowered


def test_form_starts_filled_with_the_worked_example() -> None:
    page = PAGE.read_text()
    assert "Deploys reached 12 in November." in page
    sentence_box = page.split('id="agent-text"')[1].split("</textarea>")[0]
    assert "Deploys reached 12 in November." in sentence_box
    assert 'value="November deploys"' in page
    assert 'value="7"' in page


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


def test_check_buttons_start_disabled_then_boot_enables_and_autoruns() -> None:
    page = PAGE.read_text()
    for button_id in (
        "try-check",
        "row-add",
        "try-ex1",
        "try-ex2",
        "try-ex3",
        "run",
        "ex1",
        "ex2",
        "ex3",
    ):
        match = re.search(r'<button id="' + button_id + r'"([^>]*)>', page)
        assert match is not None, button_id
        assert "disabled" in match.group(1), button_id
    assert "pendingRun" not in page
    assert "pendingArea" not in page
    assert "Your result will appear here by itself" not in page
    boot_and_after = page.split("async function boot()")[1]
    assert "runTryCheck()" in boot_and_after
    assert "disabled" in boot_and_after
    assert "runExample()" not in page
    assert "example-check" not in page
    assert "try-fill" not in page


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
    head = page.split(PINNED_MAKE_HEADING)[0]
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
    "excited",
    "game-changer",
    "revolutionary",
    "magic",
    "coach",
    "wellness",
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
    assert "Loading the checker" not in page
    assert "Starting the checker" not in page
    boot_and_after = page.split("async function boot()")[1]
    assert "statusEl.textContent = LOADING_SENTENCE;" in boot_and_after


PINNED_FAILED_STATUS = (
    "The checker could not load. Nothing was sent anywhere. "
    "Check your connection, then reload the page."
)


def test_failed_load_keeps_buttons_disabled() -> None:
    page = PAGE.read_text()
    assert PINNED_FAILED_STATUS in page
    boot_and_after = page.split("async function boot()")[1]
    assert PINNED_FAILED_STATUS in boot_and_after
    catch_branch = boot_and_after.split("catch")[1]
    assert "removeAttribute" not in catch_branch
    assert "disabled = false" not in catch_branch


def test_result_claims_render_as_cards_with_catch_motion() -> None:
    page = PAGE.read_text()
    style = page.split("<style>")[1].split("</style>")[0]
    assert ".card" in style
    assert '"claim card"' in page
    assert "catch" in page
    assert "@keyframes" in page
    assert "prefers-reduced-motion" in page


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
    assert "Codes and the exact report" not in page
    show_body = page.split("function showVerdict")[1].split("function fillPretty")[0]
    assert title in show_body
    assert show_body.index("extraLines") < show_body.index(title)


def test_verdict_scrolls_minimally() -> None:
    page = PAGE.read_text()
    assert 'scrollIntoView({block: "nearest"})' in page or (
        "scrollIntoView({ block:" in page and '"nearest"' in page
    )
    assert "root.scrollIntoView();" not in page


def test_record_row_starts_filled_with_the_worked_record() -> None:
    page = PAGE.read_text()
    rows = page.split("<tbody>")[1].split("</tbody>")[0]
    assert rows.count("<tr>") == 1
    assert 'value="November deploys"' in rows
    assert 'value="7"' in rows
    assert 'aria-label="Record name"' in rows
    assert 'aria-label="Record number"' in rows


def test_what_this_checks_plain_rules() -> None:
    page = PAGE.read_text()
    assert "<summary>What the checker can't see</summary>" in page
    assert "What this checks" not in page
    assert "What this does not check" not in page
    section = page.split("What the checker can't see")[1].split(
        "For engineers: JSON input"
    )[0]
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
    details = page.split("For engineers: JSON input")[1].split("</details>")[0]
    assert HARDENED_LIMITS_NOTE in details
    assert "examples/verify/README.md" in details
    assert "docs/ADAPTER.md" in details
    assert PINNED_PAGE_LINK in page
    assert "page_render_hardened" in page
    assert "The plain form does not supply units or periods" not in page
    before_form = page.split(PINNED_MAKE_HEADING)[0]
    assert "cited sources" not in before_form
    section = page.split("What the checker can't see")[1].split(
        "For engineers: JSON input"
    )[0]
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
    assert "The checker is ready." in page


def test_try_empty_states_guide_next_step() -> None:
    page = PAGE.read_text()
    assert "Fix the rows above and press Check again." in page
    assert "Paste what your agent wrote first." in page
    assert "None of them has a number to check." in page
    assert "There is nothing to check yet." not in page


def test_split_rule_has_example() -> None:
    page = PAGE.read_text()
    section = page.split("What the checker can't see")[1].split(
        "For engineers: JSON input"
    )[0]
    assert "more than one record" in section
    assert "We shipped 12 deploys and closed 40 tickets" in section
    assert "so split it into two sentences" in section


def test_json_summaries_name_audience() -> None:
    page = PAGE.read_text()
    assert "Show the JSON (for scripts)" in page
    assert "For engineers: JSON input" in page
    assert "Check JSON directly (for developers)" not in page


def test_source_line_names_open_source() -> None:
    page = PAGE.read_text()
    assert "The page and the checker it runs are open source in" in page
    assert '<a href="https://github.com/macayaven/ikigai-loop">' in page
    assert "Bad input shows a short message and sends nothing." in page


PINNED_TRUST_URL = "https://github.com/macayaven/ikigai-loop/blob/main/docs/TRUST.md"
PINNED_WHY_PARAGRAPHS = (
    (
        "Assistants that read your data and answer in numbers get some of them wrong. "
        "They sound just as sure either way, and nobody checks every number by hand."
    ),
    (
        "I built an assistant that offers each free hour of my day to promises I wrote down. "
        "Before a card reaches my phone, this check compares the numbers on it with my records."
    ),
    (
        "It still let some through. On Nov 2 a card said "
        '"Prs rose by 3 in the last period": the right number, from the wrong window. '
        "Five more sentences that day made the same mistake. "
        "A test that fails on that sentence came first, then the rule that stops it. "
        "Every miss so far is in TRUST.md."
    ),
    (
        "When it works, a wrong number is stopped before anyone acts on it. "
        "That's why you can try it here, for free, "
        "on any sentence an AI wrote for you."
    ),
)


def test_why_section_carries_the_pinned_paragraphs() -> None:
    page = PAGE.read_text()
    assert "<h2>Why I built this</h2>" in page
    why = page.split("Why I built this")[1].split("What the checker can't see")[0]
    for paragraph in PINNED_WHY_PARAGRAPHS:
        expected = paragraph.replace(
            "is in TRUST.md.",
            f'is in <a href="{PINNED_TRUST_URL}">TRUST.md</a>.',
        )
        assert expected in why, paragraph[:60]


def test_trust_link_text_and_address_are_pinned() -> None:
    page = PAGE.read_text()
    assert f'<a href="{PINNED_TRUST_URL}">TRUST.md</a>' in page
    why = page.split("Why I built this")[1].split("What the checker can't see")[0]
    assert f'<a href="{PINNED_TRUST_URL}">TRUST.md</a>' in why
    assert "docs/TRUST.md" not in page.replace(PINNED_TRUST_URL, "")


def test_example_row_offers_three_pinned_labels_in_order() -> None:
    page = PAGE.read_text()
    assert "Try one:" in page
    row = page.split("Try one:")[1].split("Can you fool it?")[0]
    wrong = row.index("Wrong number")
    matching = row.index("Matching numbers")
    sneaky = row.index('A sneaky "not"')
    assert wrong < matching < sneaky
    assert "Sneaky negation" not in page
    for button_id in ("try-ex1", "try-ex2", "try-ex3"):
        assert f'id="{button_id}"' in row, button_id


def test_invitation_links_to_the_honest_list() -> None:
    page = PAGE.read_text()
    assert "<h2>Can you fool it?</h2>" in page
    assert "Try a sentence that sounds right but bends a number" in page
    assert "or a time window." in page
    assert "See what the checker can't see" in page
    assert 'href="#limits"' in page
    assert 'id="limits"' in page


def test_first_screen_sections_appear_in_order() -> None:
    page = PAGE.read_text()
    marks = [
        f"<h1>{PINNED_HEADLINE}</h1>",
        PINNED_SUBHEAD,
        PINNED_TAGLINE,
        PINNED_PRIVACY,
        PINNED_MAKE_HEADING,
        PINNED_MAKE_SUB,
        "Try one:",
        "Wrong number",
        "Matching numbers",
        'A sneaky "not"',
        "Can you fool it?",
        "<summary>How this works</summary>",
        "Why I built this",
        "<summary>What the checker can't see</summary>",
        "For engineers: JSON input",
    ]
    positions = [page.index(mark) for mark in marks]
    assert positions == sorted(positions)


def test_json_section_is_last_and_starts_collapsed() -> None:
    page = PAGE.read_text()
    assert "<summary>For engineers: JSON input</summary>" in page
    after = page.split("<summary>For engineers: JSON input</summary>")[1]
    assert "<h2" not in after
    details_open = page.rindex("<details", 0, page.index("For engineers: JSON input"))
    assert "open" not in page[details_open : details_open + 40]


def test_tap_targets_and_reduced_motion_are_pinned() -> None:
    page = PAGE.read_text()
    style = page.split("<style>")[1].split("</style>")[0]
    assert "min-height" in style
    assert "44px" in style
    assert "@media (prefers-reduced-motion: reduce)" in style
    reduced = style.split("@media (prefers-reduced-motion: reduce)")[1]
    assert "animation" in reduced


def test_page_copy_has_no_em_dashes() -> None:
    page = PAGE.read_text()
    copy = re.sub(r"<style.*?</style>", "", page, flags=re.DOTALL)
    assert "\u2014" not in copy
    assert "\u2013" not in copy
    assert "--" not in copy


def test_finding_code_shows_in_small_print() -> None:
    page = PAGE.read_text()
    show_body = page.split("function showVerdict")[1].split("function fillPretty")[0]
    assert '"Code: " + finding.code' in show_body


def test_plain_card_scope_line_is_pinned() -> None:
    page = PAGE.read_text()
    assert PINNED_PLAIN_LIMIT in page
    assert "It checked the number against the card." not in page
    assert "The plain form does not supply units or periods" not in page
    show_body = page.split("function showVerdict")[1].split("function fillPretty")[0]
    assert "PLAIN_LIMIT_LINE" in show_body
    assert "claim.checked" in show_body
    assert "claim.limit" in show_body
    assert show_body.index('"Code: " + finding.code') < show_body.index("claim.checked")
    assert show_body.index("claim.checked") < show_body.index("Technical details")


def test_plain_card_orders_badge_headline_quote_and_code() -> None:
    page = PAGE.read_text()
    show_body = page.split("function showVerdict")[1].split("function fillPretty")[0]
    plain_branch = show_body.split("if (plain)")[1].split(
        "const overall = document.createElement"
    )[0]
    head_at = plain_branch.index("result-head")
    quote_at = plain_branch.index("result-quote")
    code_at = plain_branch.index('"Code: " + finding.code')
    checked_at = plain_branch.index("claim.checked")
    limit_at = plain_branch.index("claim.limit")
    details_at = plain_branch.index("Technical details")
    assert head_at < quote_at < code_at < checked_at < limit_at < details_at
    assert "notesById" in plain_branch
    assert plain_branch.index("notesById") > details_at
    assert "const overall = document.createElement" not in plain_branch
