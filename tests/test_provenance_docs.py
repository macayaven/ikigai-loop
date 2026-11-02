"""Ticket 22: MODELS.md and provenance.jsonl tests. Made-up data only."""

from __future__ import annotations

from pathlib import Path

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

WORD_LIMIT = 340


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_models_doc_names_commands_and_log() -> None:
    """Removing the doc, a command name or the schema check makes it fail."""
    from framework.provenance.schemas import ProvenanceLine

    doc = _root() / "docs" / "MODELS.md"
    assert doc.exists()
    text = doc.read_text()
    assert "make glimmer-proof" in text
    assert "framework.provenance.export" in text
    assert "docs/provenance.jsonl" in text
    words = text.split()
    assert len(words) <= WORD_LIMIT, len(words)
    lowered = text.lower()
    for banned in BANNED:
        assert banned not in lowered, banned
    log = _root() / "docs" / "provenance.jsonl"
    assert log.exists()
    for line in log.read_text().splitlines():
        if line.strip():
            ProvenanceLine.model_validate_json(line)
