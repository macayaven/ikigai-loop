"""Ticket 24: bind docs/TRUST.md to the cases, the gate and the counts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from evals.briefing_cases import (
    MUTANTS,
    PHONE_COVERED_MISSES,
    PHONE_MISSES,
    PHONE_TABLE_MISSES,
)
from framework.briefing.gate import evaluate_briefing

WORD_LIMIT = 1600

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

SCOPE = (
    "It checks numbers, sources and wording against my records. "
    "It doesn't check that a sentence is true."
)

COUNTS_TEMPLATE = (
    "On {cards} of those cards, {sentences} sentences described a change "
    "since the last card as if it happened inside a period."
)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _page() -> str:
    return (_root() / "docs" / "TRUST.md").read_text(encoding="utf-8")


def _table_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks


def _parse_table(block: list[str]) -> tuple[list[str], list[list[str]]]:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def is_separator(row: list[str]) -> bool:
        return bool(row) and all(re.fullmatch(r":?-{3,}:?", c) is not None for c in row)

    header = cells(block[0])
    rows = [cells(line) for line in block[1:] if not is_separator(cells(line))]
    return header, rows


def _phone_table() -> list[list[str]]:
    for block in _table_blocks(_page()):
        header, rows = _parse_table(block)
        if "Card" in header and "Gate at HEAD" in header:
            assert header == [
                "Card",
                "Sentence",
                "What the number really was",
                "Case",
                "Gate at HEAD",
            ]
            return rows
    raise AssertionError("phone table not found")


def _replay_table() -> list[list[str]]:
    for block in _table_blocks(_page()):
        header, rows = _parse_table(block)
        if "Sentence" in header and "Result" in header and "Gate at HEAD" not in header:
            assert header == ["Sentence", "Result", "What it shows"]
            return rows
    raise AssertionError("replay table not found")


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _case_by_name(name: str):
    for miss in PHONE_MISSES:
        if miss.case.name == name:
            return miss.case
    for case in MUTANTS:
        if case.name == name:
            return case
    raise AssertionError(f"unknown case {name}")


def _since_last_text(case) -> str:
    section = next(s for s in case.briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    return str(claim["text"])


def _since_last_ref(case) -> tuple[str, float, float, float]:
    section = next(s for s in case.briefing["sections"] if s["type"] == "since_last")
    claim = next(c for c in section["claims"] if c["id"] == "claim-s3")
    metric_id = str(claim["metric_refs"][0]["metric_id"])
    assert case.context.parent_metrics is not None
    previous = float(case.context.parent_metrics.values[metric_id])
    current = float(case.context.metrics.values[metric_id])
    return metric_id, previous, current, float(claim["metric_refs"][0]["value"])


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _whole(haystack: str, needle: str) -> re.Match[str] | None:
    return re.search(r"(?<![0-9.:])" + re.escape(needle) + r"(?![0-9.:])", haystack)


def _gate_codes() -> set[str]:
    text = (_root() / "framework" / "briefing" / "gate.py").read_text(encoding="utf-8")
    return set(re.findall(r'"(L[0-9][A-Z0-9_]*)"', text))


def _git_subjects() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%s"],
            cwd=_root(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError:
        pytest.fail("git log unavailable")
    assert proc.returncode == 0, "git log unavailable"
    return proc.stdout.splitlines()


def _replay(sentence: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "evals.replay_sentence", sentence],
        cwd=_root(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode == 0:
        assert "passed" in proc.stdout.splitlines(), proc.stdout
        return "passed"
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    codes: list[str] = []
    for line in proc.stdout.splitlines():
        match = re.fullmatch(r"(\S+) at (.+)", line.strip())
        if match:
            codes.append(match.group(1))
    assert codes, f"no code line for {sentence!r}: {proc.stdout!r}"
    return "stopped: " + " ".join(codes)


OPEN_PRS = ("54", "55", "56", "57", "58")


def test_pr_numbers_exist() -> None:
    numbers = sorted(set(re.findall(r"#(\d+)", _page())))
    assert numbers, "no PR numbers on the page"
    subjects = _git_subjects()
    lines = _page().splitlines()
    for number in numbers:
        if any(s.endswith(f"(#{number})") for s in subjects):
            continue
        assert number in OPEN_PRS, f"#{number}"
        citing = [line for line in lines if f"#{number}" in line]
        assert citing, f"#{number}"
        for line in citing:
            assert "open" in line.lower(), line
            assert "Nov 3" in line, line


def test_paths_exist() -> None:
    text = _page()
    missing: list[str] = []
    for match in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
        target = match.group(2).strip()
        if target.startswith(("http://", "https://", "#")):
            continue
        target = target.split("#", 1)[0]
        if not (_root() / "docs" / target).exists():
            missing.append(target)
    for match in re.finditer(r"`([^`]+)`", text):
        span = match.group(1)
        if " " in span or "/" not in span:
            continue
        if not (_root() / span).exists():
            missing.append(span)
    assert missing == [], missing


def test_tests_exist() -> None:
    text = _page()
    cited = sorted(set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", text)))
    assert cited, "no test file cited on the page"
    for name in cited:
        assert (_root() / name).is_file(), name
    for match in re.finditer(r"`([^`]+)`", text):
        span = match.group(1)
        if " " in span or "/" in span:
            continue
        if not re.fullmatch(r"test_[A-Za-z0-9_]+", span):
            continue
        found = [
            name
            for name in cited
            if re.search(
                rf"^def {re.escape(span)}\b",
                (_root() / name).read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        ]
        assert found, span


def test_gate_codes_are_real() -> None:
    codes = _gate_codes()
    assert "L1B_SINCE_LAST_WORDING" in codes
    for code in re.findall(r"L[0-9][A-Z0-9_]*", _page()):
        assert code in codes, code


COVERED_SENTENCE = (
    "On the 22:30 card and its corrected card, four more sentences about "
    "my screen hours made the same mistake. My screen numbers stay out of "
    "this repository; their cases use made-up values."
)


def test_phone_table_matches_the_cases() -> None:
    rows = _phone_table()
    assert len(rows) == len(PHONE_TABLE_MISSES) == 2
    for miss, row in zip(PHONE_TABLE_MISSES, rows):
        assert row[0] == miss.card
        assert row[3].strip("`") == miss.case.name
        assert _strip_quotes(row[1]) == _since_last_text(miss.case)
        result = evaluate_briefing(miss.case.briefing, miss.case.context)
        codes = [v.code for v in result.violations]
        assert row[4].startswith("stopped: ")
        stated = row[4].split("stopped: ", 1)[1].split()
        assert stated, row[4]
        assert codes == stated
        assert row[4] == "stopped: " + " ".join(stated)


def test_phone_table_values() -> None:
    rows = _phone_table()
    assert len(rows) == len(PHONE_TABLE_MISSES) == 2
    for miss, row in zip(PHONE_TABLE_MISSES, rows):
        metric_id, previous, current, _ = _since_last_ref(miss.case)
        del metric_id
        cell = row[2]
        prev_text, cur_text = _fmt(previous), _fmt(current)
        prev_match = _whole(cell, prev_text)
        cur_match = _whole(cell, cur_text)
        assert prev_match is not None, (miss.case.name, prev_text, cell)
        assert cur_match is not None, (miss.case.name, cur_text, cell)
        assert prev_match.start() < cur_match.start(), cell


def test_covered_screen_hour_sentence() -> None:
    assert len(PHONE_MISSES) == 6
    assert len(PHONE_COVERED_MISSES) == 4
    assert sorted({miss.card for miss in PHONE_COVERED_MISSES}) == [
        "22:30",
        "22:30 corrected",
    ]
    assert sorted({miss.card for miss in PHONE_TABLE_MISSES}) == [
        "15:30",
        "20:30 corrected",
    ]
    assert COVERED_SENTENCE in _page()


def test_all_phone_misses_stop_with_since_last_wording() -> None:
    assert len(PHONE_MISSES) == 6
    for miss in PHONE_MISSES:
        result = evaluate_briefing(miss.case.briefing, miss.case.context)
        assert [v.code for v in result.violations] == ["L1B_SINCE_LAST_WORDING"]


def test_counts_sentence() -> None:
    cards = len({miss.card for miss in PHONE_MISSES})
    expected = COUNTS_TEMPLATE.format(cards=cards, sentences=len(PHONE_MISSES))
    assert expected in _page()


def test_scheduled_count() -> None:
    matches = re.findall(r"(\d+) scheduled", _page())
    assert matches, "no scheduled count on the page"
    count = sum(
        1
        for line in (_root() / "docs" / "provenance.jsonl").read_text().splitlines()
        if line.strip()
        and json.loads(line)["slot"].startswith("2026-11-02")
        and json.loads(line)["delivery"] == "delivered"
    )
    for match in matches:
        assert int(match) == count, match


def test_replay_rows() -> None:
    assert "evals.replay_sentence" in _page()
    rows = _replay_table()
    assert len(rows) == 6
    for row in rows:
        assert _replay(_strip_quotes(row[0])) == row[1].strip(), row[0]


def test_scope_sentence_and_links() -> None:
    assert SCOPE in _page()
    lines = (_root() / "README.md").read_text(encoding="utf-8").splitlines()
    pitch = next(i for i, line in enumerate(lines) if "can't back" in line)
    index = pitch + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    paragraph: list[str] = []
    while index < len(lines) and lines[index].strip():
        paragraph.append(lines[index])
        index += 1
    para = "\n".join(paragraph)
    assert SCOPE in para
    assert "[Misses so far: see TRUST.md](docs/TRUST.md)" in para
    agents = (_root() / "AGENTS.md").read_text(encoding="utf-8")
    assert SCOPE in agents
    assert '"' + SCOPE + '"' in agents
    assert "In Carlos's words:" in agents
    assert "proposes one commitment per goal" in agents
    assert (
        "deterministic gate checks the card's reason sentences and "
        "the commitment it proposes before it is sent" in agents
    )
    assert "[Misses so far](docs/TRUST.md)" in agents


def test_old_claim_gone() -> None:
    agents = (_root() / "AGENTS.md").read_text(encoding="utf-8")
    assert "can't tell him anything it can't prove" not in agents


def test_banned_words_cap_and_em_dashes() -> None:
    text = _page()
    lowered = text.lower()
    for banned in BANNED:
        assert banned not in lowered, banned
    assert len(text.split()) <= WORD_LIMIT, len(text.split())
    assert "—" not in text
