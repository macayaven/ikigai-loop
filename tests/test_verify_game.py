"""Ticket 25 follow-up: Catch the AI, the six-round game on the checker page.

Rounds come from docs/verify/game/rounds.json, written by Muse Wonder in its
own sessions. Nothing here edits that file: the tests read it as it stands
and pin what the plain pipeline (build_checker_input and check_claims) says
for each round, plus the game copy and page rules from the ticket.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "verify" / "index.html"
ROUNDS_PATH = ROOT / "docs" / "verify" / "game" / "rounds.json"
VERIFY_PAGE_PATH = ROOT / "docs" / "verify" / "verify_page.py"

PINNED_PAGE_LINK = "https://carloscrespomacaya.com/ikigai-loop/verify/"
PINNED_SHARE_HEAD = '"I scored " + n + "/6 against the number checker. Can you beat us?'
PINNED_SHARE_ROW = (
    'Me " + marksEmojis(youMarks) + " · Checker " + marksEmojis(checkerMarks)'
)
PINNED_QUESTION = "Does the AI's sentence match the card?"
PINNED_RUNNING_SCORE = '"You " + gamePlayer + " · Checker " + gameCheckerDone'
PINNED_PROGRESS = '"Round " + (gameIndex + 1) + " of 6"'
PINNED_FINAL_LEAD = '"You: " + n + "/6 · Checker: " + m + "/6"'
PINNED_TAGLINE = (
    "Six sentences an AI wrote. Some hide a trap. Can you beat the checker?"
)
PINNED_BYLINE = "Muse Wonder, Meta's AI, wrote these sentences, and we asked it to set traps in some."
PINNED_HOW_LINE = (
    "Muse Wonder wrote the cards and sentences. Your browser checks their numbers."
)
PINNED_BRIEF_ANCHOR = "the-brief-muse-wonder-got-for-the-rounds"

BANNED_WORDS = (
    "leverage",
    "delve",
    "robust",
    "seamless",
    "thrilled",
    "excited",
    "game-changer",
    "revolutionary",
    "magic",
    "coach",
    "wellness",
)


def _load_verify_page() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_page_game", VERIFY_PAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_page_game"] = module
    spec.loader.exec_module(module)
    return module


VERIFY_PAGE = _load_verify_page()


def _rounds() -> dict[str, Any]:
    return json.loads(ROUNDS_PATH.read_text())  # type: ignore[no-any-return]


def _pipeline(round_: dict[str, Any]) -> tuple[bool, list[str]]:
    from framework.verify.hardened import check_claims

    rows = json.dumps(
        [{"name": row["name"], "number": str(row["value"])} for row in round_["rows"]]
    )
    built = json.loads(
        VERIFY_PAGE.build_checker_input(round_["sentence"], rows)  # type: ignore[no-untyped-call]
    )
    assert built["problems"] == [], built["problems"]
    assert isinstance(built["input"], str)
    report = check_claims(built["input"])
    return report.passed, [v.code for v in report.violations]


def test_rounds_file_has_six_rounds_with_pinned_fields() -> None:
    data = _rounds()
    assert data["version"] == 1
    assert isinstance(data["disclosure"], str) and data["disclosure"].strip() != ""
    rounds = data["rounds"]
    assert len(rounds) == 6
    seen_answers = []
    for round_ in rounds:
        assert set(round_) >= {
            "id",
            "title",
            "rows",
            "sentence",
            "answer",
            "why",
            "checker_sees_it",
        }
        assert round_["answer"] in ("right", "wrong")
        seen_answers.append(round_["answer"])
        assert len(round_["rows"]) == 3
        for row in round_["rows"]:
            assert set(row) >= {"name", "value"}
            assert isinstance(row["value"], int)
    assert "right" in seen_answers and "wrong" in seen_answers
    blind = [round_ for round_ in rounds if not round_["checker_sees_it"]]
    assert len(blind) == 1


def test_page_shows_disclosure_word_for_word() -> None:
    disclosure = str(_rounds()["disclosure"])
    assert disclosure in PAGE.read_text()


def test_round_checker_verdicts_and_codes_are_pinned() -> None:
    expected: dict[str, tuple[bool, list[str]]] = {
        "r1": (True, []),
        "r2": (False, ["L1B_METRIC_VALUE_MISMATCH"]),
        "r3": (True, []),
        "r4": (True, []),
        "r5": (False, ["L1B_NEGATED_CLAIM"]),
        "r6": (False, ["L1B_METRIC_VALUE_MISMATCH"]),
    }
    for round_ in _rounds()["rounds"]:
        assert _pipeline(round_) == expected[round_["id"]], round_["id"]


def test_seen_rounds_match_answers_and_blind_spot_passes() -> None:
    agree = 0
    for round_ in _rounds()["rounds"]:
        passed, _ = _pipeline(round_)
        verdict = "right" if passed else "wrong"
        if round_["checker_sees_it"]:
            assert verdict == round_["answer"], round_["id"]
        else:
            assert passed is True, round_["id"]
        agree += verdict == round_["answer"]
    assert agree == 5


def test_checker_score_M_is_pinned() -> None:
    agree = 0
    for round_ in _rounds()["rounds"]:
        passed, _ = _pipeline(round_)
        agree += ("right" if passed else "wrong") == round_["answer"]
    assert agree == 5
    page = PAGE.read_text()
    assert PINNED_FINAL_LEAD in page
    assert "on these six cards" not in page


def test_game_comes_first_with_no_start_screen() -> None:
    page = PAGE.read_text()
    assert "<h1>Catch the AI</h1>" in page
    assert '"Strawberry" has three r\'s. AI once said two.' in page
    assert PINNED_TAGLINE in page
    assert PINNED_BYLINE in page
    assert "Paste a sentence your AI wrote" not in page
    assert page.index("<h1>Catch the AI</h1>") < page.index("Make your own round")
    assert page.index(PINNED_BYLINE) < page.index('id="game-play"')
    assert PINNED_PROGRESS in page
    assert page.index(PINNED_TAGLINE) < page.index('id="game-play"')


def test_first_screen_fits_sentence_and_both_buttons() -> None:
    page = PAGE.read_text()
    sentence_at = page.index('id="game-sentence"')
    right_at = page.index('id="game-right"')
    wrong_at = page.index('id="game-wrong"')
    wrap_at = page.index('id="try-wrap"')
    assert sentence_at < wrap_at
    assert right_at < wrap_at
    assert wrong_at < wrap_at
    style = page.split("<style>")[1].split("</style>")[0]
    choices_rules = [
        chunk for chunk in style.split("}") if ".game-choices" in chunk.split("{")[0]
    ]
    assert choices_rules
    assert all("column" not in chunk for chunk in choices_rules)


def test_how_this_works_section_is_pinned() -> None:
    page = PAGE.read_text()
    assert 'id="game-how-link"' in page
    assert "How this works" in page
    assert 'id="game-how"' in page
    assert "<summary>How this works</summary>" in page
    assert PINNED_HOW_LINE in page
    assert "docs/verify/game/rounds.json" in page
    assert PINNED_BRIEF_ANCHOR in page
    assert "https://github.com/macayaven/ikigai-loop" in page


def test_round_question_buttons_and_no_hint_are_pinned() -> None:
    page = PAGE.read_text()
    assert PINNED_QUESTION in page
    assert page.index(PINNED_QUESTION) < page.index('id="game-right"')
    assert page.index(PINNED_QUESTION) < page.index('id="game-wrong"')
    assert ">It matches<" in page
    assert ">It doesn't<" in page
    assert "Your advantage" not in page
    assert "game-advantage" not in page
    assert PINNED_RUNNING_SCORE in page


def test_answer_buttons_dim_and_mark_the_chosen_one() -> None:
    page = PAGE.read_text()
    guess_body = page.split("function gameGuess")[1].split("function gameCheckerReady")[
        0
    ]
    assert "disabled = true" in guess_body
    assert 'classList.add("game-chosen")' in guess_body
    assert (
        "game-chosen"
        in page.split("function gameRenderRound")[1].split(
            "function gameCheckerVerdict"
        )[0]
    )
    style = page.split("<style>")[1].split("</style>")[0]
    assert "button:disabled" in style
    assert "button.game-chosen" in style


def test_highlights_follow_the_card_not_the_player() -> None:
    page = PAGE.read_text()
    guess_body = page.split("function gameGuess")[1].split("function gameCheckerReady")[
        0
    ]
    assert "gameRowMatches(round, hit, span)" in guess_body
    assert 'match ? "game-hit-pass" : "game-hit-catch"' in guess_body
    assert 'match ? "game-num-pass" : "game-num-catch"' in guess_body


def test_reveal_and_next_round_scroll_together() -> None:
    page = PAGE.read_text()
    guess_body = page.split("function gameGuess")[1].split("function gameCheckerReady")[
        0
    ]
    assert 'next.scrollIntoView({block: "nearest"})' in guess_body
    assert 'getElementById("game-card").scrollIntoView({block: "nearest"})' in page


def test_card_marks_are_pinned() -> None:
    page = PAGE.read_text()
    for line in (
        "The card",
        "What the AI wrote",
        "game-pill",
        "game-dot-blind",
        "game-dot-miss",
    ):
        assert line in page, line


def test_reveal_lines_are_pinned() -> None:
    page = PAGE.read_text()
    for line in (
        "Good call",
        "Caught it",
        "Slipped",
        "You both missed it.",
        '"You said: " + (guess === "right" ? "It matches" : "It doesn\'t")',
        "It matches the card.",
        "It's a trap.",
        "The number matches. The season doesn't.",
        "The checker says:",
        "PASS. The number matches the card.",
        'FAIL. It caught the \\"not\\".',
        "FAIL. The sentence says ",
        "; the card says ",
        "It only reads numbers, so this one slipped past it.",
        "You caught what the checker missed.",
        "Next round",
        "Waiting for the checker...",
    ):
        assert line in page, line
    assert "The answer: " not in page
    assert "What the checker saw:" not in page
    for gone in (
        "Same number, wrong season.",
        "The checker only reads numbers, so this one slipped past it.",
        "That one slipped past both of you.",
        'The checker spots the sneaky "not".',
    ):
        assert gone not in page, gone


def test_trick_round_underline_and_stamp_are_pinned() -> None:
    page = PAGE.read_text()
    assert "game-season-catch" in page
    assert '"this season"' in page
    assert '"last season"' in page
    style = page.split("<style>")[1].split("</style>")[0]
    assert "text-decoration: underline" in style
    assert "game-stamp" in style
    assert ".game-stamp.catch" in style


def test_score_card_lines_are_pinned() -> None:
    page = PAGE.read_text()
    for line in (
        PINNED_FINAL_LEAD,
        "One claim fooled you both.",
        "You caught every trap.",
        "You tied the checker.",
        "You beat the checker.",
        "The checker wins this round.",
        "You caught the one the checker can't see.",
        "The checker reads names and numbers, not seasons.",
        "Share challenge",
        "Copied.",
        "Play again",
        "Try the tricky one yourself",
        "Make your own round",
        "gameMarksRow",
        '"✅"',
        '"❌"',
    ):
        assert line in page, line
    assert PINNED_SHARE_HEAD in page
    assert PINNED_SHARE_ROW in page
    assert "Copy my score" not in page
    assert "Replay these six" not in page
    assert "Now try your own sentence" not in page


def test_share_uses_web_share_with_copy_fallback() -> None:
    page = PAGE.read_text()
    assert "navigator.share" in page
    assert "{text: shareText, url:" in page
    assert "gameCopy(shareText, share)" in page


def test_answers_form_url_empty_means_no_send_link() -> None:
    page = PAGE.read_text()
    assert 'const ANSWERS_FORM_URL = "";' in page
    assert "if (ANSWERS_FORM_URL)" in page
    assert "Send my answers (anonymous)" in page
    assert (
        "This sends only your six guesses and your score, "
        "and only if you tap it." in page
    )
    static_links = re.findall(r"<a [^>]*>", page)
    assert not any("Send my answers" in link for link in static_links)


def test_form_stays_hidden_until_the_score_card() -> None:
    page = PAGE.read_text()
    assert 'id="game-skip-form"' in page
    assert "Skip to make your own round" in page
    body = page.split("<body")[1]
    wrap_open = body.index('id="try-wrap"')
    assert "hidden" in body[wrap_open - 30 : wrap_open]
    final_body = page.split("function gameFinal")[1].split("function gameTryTricky")[0]
    assert 'getElementById("try-wrap")' in final_body
    assert 'removeAttribute("hidden")' in final_body
    skip_body = page.split('getElementById("game-skip-form")')[1].split("boot();")[0]
    assert 'getElementById("try-wrap")' in skip_body
    wrap_section = page.split('id="try-wrap"')[1].split('id="game-how"')[0]
    assert "Can you fool it?" in wrap_section


def test_make_your_own_round_keeps_everything_after_in_order() -> None:
    page = PAGE.read_text()
    marks = [
        "<h1>Catch the AI</h1>",
        "Make your own round",
        "Give a card a few numbers",
        "Can you fool it?",
        "<summary>How this works</summary>",
        "Why I built this",
        "What the checker can't see",
        "For engineers: JSON input",
    ]
    positions = [page.index(mark) for mark in marks]
    assert positions == sorted(positions)
    assert '"#try-your-own"' in page
    assert 'id="try-your-own"' in page


def test_page_loads_nothing_new_beyond_rounds() -> None:
    page = PAGE.read_text()
    fetches = re.findall(r'fetch\(\s*["\']([^"\']+)["\']', page)
    assert sorted(fetches) == ["bundle.json", "game/rounds.json", "verify_page.py"]
    assert "<audio" not in page.lower()
    for suffix in (".mp3", ".wav", ".ogg", ".m4a", ".flac"):
        assert suffix not in page.lower(), suffix


def test_no_storage_calls() -> None:
    page = PAGE.read_text()
    for token in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert token not in page, token


def test_reduced_motion_covers_the_new_motion() -> None:
    page = PAGE.read_text()
    style = page.split("<style>")[1].split("</style>")[0]
    assert "@keyframes game-reveal" in style
    assert "@keyframes game-confetti" in style
    assert "@keyframes game-score" in style
    assert "prefers-reduced-motion" in page
    assert "matchMedia" in page and "prefers-reduced-motion" in page


def test_game_sound_toggle_is_pinned() -> None:
    page = PAGE.read_text()
    assert "Sound: On" in page
    assert "Sound: Off" in page
    assert "aria-pressed" in page
    assert "AudioContext" in page
    assert "gameTriad" in page
    assert "gameMarimba" in page
    assert "lowpass" in page


def test_game_copy_rules() -> None:
    page = PAGE.read_text()
    lowered = page.lower()
    for word in BANNED_WORDS:
        assert word not in lowered, word
    assert "!!" not in page
