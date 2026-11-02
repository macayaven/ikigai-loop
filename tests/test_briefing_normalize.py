"""Ticket 10b: one public normalisation for every briefing text rule."""

import unicodedata

import pytest

from framework.briefing.normalize import has_unsafe_text, normalize_text


def test_fullwidth_folds_to_ascii() -> None:
    assert normalize_text("Ｑｕｉｌｌｏｎ") == "Quillon"


@pytest.mark.parametrize(
    "char",
    [
        "­",
        "\x00",
        "",
        "\ud800",
        "͸",
        "\u0488",
    ],
)
def test_unsafe_corpus_fires(char: str) -> None:
    assert has_unsafe_text(f"a{char}b")


def test_unsafe_corpus_members() -> None:
    assert ord("­") == 0x00AD
    assert ord("") == 0xE000
    assert ord("͸") == 0x0378
    assert ord("҈") == 0x0488


def test_nfkc_forms_fold() -> None:
    assert normalize_text("ﬁ") == "fi"
    assert normalize_text("30²") == "302"
    assert normalize_text("reached Ⅳ") == "reached IV"


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("２", "2"),
        ("٣", "3"),
        ("३", "3"),
        ("¾", "3⁄4"),
    ],
)
def test_digit_and_fraction_forms_fold(raw: str, want: str) -> None:
    assert normalize_text(raw) == want
    assert "⁄" in normalize_text("¾")


@pytest.mark.parametrize(
    ("raw", "point", "latin"),
    [
        ("а", 0x0430, "a"),
        ("і", 0x0456, "i"),
        ("ј", 0x0458, "j"),
        ("ѕ", 0x0455, "s"),
        ("р", 0x0440, "p"),
        ("ο", 0x03BF, "o"),
        ("α", 0x03B1, "a"),
    ],
)
def test_confusables_map_to_latin(raw: str, point: int, latin: str) -> None:
    assert ord(raw) == point
    assert normalize_text(f"Zebr{raw}finch") == f"Zebr{latin}finch"


def test_unsafe_strips_before_matching() -> None:
    assert normalize_text("a­b") == "ab"


def test_curly_quotes_map_to_straight() -> None:
    assert normalize_text("shouldn’t") == "shouldn't"


def test_hyphen_variants_map_to_hyphen() -> None:
    assert normalize_text("second–to–last") == "second-to-last"
    assert normalize_text("up−to") == "up-to"


def test_spaces_map_to_plain_space() -> None:
    assert normalize_text("a b") == "a b"
    assert has_unsafe_text("a b") is False


def test_combining_marks_fold_to_base() -> None:
    assert normalize_text("Gödel") == "Godel"
    assert normalize_text("Quíllon") == "Quillon"


@pytest.mark.parametrize(
    ("raw", "want"),
    [("ı", "i"), ("ł", "l"), ("ø", "o")],
)
def test_latin_lookalikes_map(raw: str, want: str) -> None:
    assert normalize_text(raw) == want


def test_whitespace_collapses_and_strips() -> None:
    assert normalize_text("  Pushes   reached\t3\n") == "Pushes reached 3"


def test_case_is_preserved() -> None:
    assert normalize_text("Planned for May 9") == "Planned for May 9"


def test_normalize_is_idempotent() -> None:
    texts = [
        "Ｑｕｉｌｌｏｎ subieron ¾ a­b",
        "Pushes reached 3 in last",
        "Gödel machines",
        "Notes mention quetzal\u200bgarden here",
    ]
    for text in texts:
        once = normalize_text(text)
        assert normalize_text(once) == once


def test_output_never_holds_unsafe_categories() -> None:
    texts = [
        "Ｑｕｉｌｌｏｎ",
        "a­b",
        "ﬁ²Ⅳ",
        "Gödel ıłø",
        "Notes mention quetzal\u200bgarden here",
        "shouldn’t second–to–last a b",
    ]
    for text in texts:
        for char in normalize_text(text):
            assert unicodedata.category(char) not in (
                "Cc",
                "Cf",
                "Co",
                "Cs",
                "Cn",
                "Me",
            ), (text, hex(ord(char)))
