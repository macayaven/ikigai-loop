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


def test_readme_nov2_glimmer_live_facts_bound_to_provenance() -> None:
    """The README's Nov 2 Glimmer opener must state the provenance counts."""
    import json

    root = _root()
    readme = (root / "README.md").read_text(encoding="utf-8")
    nov2_all = 0
    nov2_cited = 0
    for raw in (
        (root / "docs" / "provenance.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        if not raw.strip():
            continue
        entry = json.loads(raw)
        if not str(entry.get("slot", "")).startswith("2026-11-02"):
            continue
        if entry.get("delivery") != "delivered":
            continue
        if entry.get("facts_model_step") != "ok":
            continue
        sides = entry.get("sides", [])
        if not sides:
            continue
        ok = True
        for side in sides:
            passes = (side.get("cycle", {}) or {}).get("passes", [])
            names = {
                str(p.get("name"))
                for p in passes
                if "Muse-Glimmer" in str(p.get("model_reported", ""))
            }
            if "personal" not in names or "feed" not in names:
                ok = False
                break
        if not ok:
            continue
        nov2_all += 1
        cited = (entry.get("facts_cited", {}) or {}).get("model", 0)
        if isinstance(cited, int) and cited > 0:
            nov2_cited += 1
    expected = (
        f"On Nov 2, Muse Glimmer ran on my own hardware for every "
        f"scheduled live card: all {nov2_all} slots, two passes each, "
        f"and {nov2_cited} of those {nov2_all} cards cite at least one "
        f"of its facts (docs/provenance.jsonl)."
    )
    assert expected in readme
    line = next(
        line
        for line in readme.splitlines()
        if "Muse Glimmer has generated facts through this code in a seeded run" in line
    )
    assert line.startswith(expected)


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
