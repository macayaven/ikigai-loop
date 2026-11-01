"""Ticket 6: page rendering tests (AT5, AT7–AT10)."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from framework.blocks import BLOCKS, RenderContext, render_block, render_manifest
from framework.blocks.__main__ import main
from framework.schemas.manifest import BlockConfig, Manifest

MADRID = ZoneInfo("Europe/Madrid")
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load_fixture(name: str) -> Manifest:
    return Manifest.model_validate_json((FIXTURES / name).read_text())


def _context_with_slots_and_fact() -> RenderContext:
    return RenderContext.model_validate(
        {
            "free_slots": [
                {
                    "start": datetime(2026, 10, 31, 15, 0, tzinfo=MADRID).isoformat(),
                    "end": datetime(2026, 10, 31, 15, 30, tzinfo=MADRID).isoformat(),
                    "label": "Synthetic slot one",
                },
                {
                    "start": datetime(2026, 10, 31, 16, 0, tzinfo=MADRID).isoformat(),
                    "end": datetime(2026, 10, 31, 16, 30, tzinfo=MADRID).isoformat(),
                    "label": "Synthetic slot two",
                },
            ],
            "facts": [{"id": "fact_1", "text": "Synthetic fact one"}],
            "links": [],
        }
    )


def test_escaping_renders_inert() -> None:
    block = BlockConfig.model_validate(
        {
            "type": "checklist",
            "dimension": BLOCKS["checklist"].sample_dimension,
            "config": {
                "label": "<script>alert(1)</script>",
                "items": [{"id": "a", "label": "Do it"}],
            },
            "rationale": "synthetic",
        }
    )
    manifest = Manifest.model_validate(
        {
            "version": "v-escape",
            "parent": None,
            "layout": ["checklist#x"],
            "blocks": {"checklist#x": block.model_dump()},
            "changelog": [],
        }
    )
    context = RenderContext.model_validate(
        {"facts": [{"id": "f1", "text": '<b>bold</b> & "quoted"'}]}
    )
    insight = BlockConfig.model_validate(
        {
            "type": "insight_card",
            "dimension": "love",
            "config": {"label": "Insight", "fact_ids": ["f1"]},
            "rationale": "synthetic",
        }
    )
    manifest2 = Manifest.model_validate(
        {
            "version": "v-escape",
            "parent": None,
            "layout": ["insight_card#y"],
            "blocks": {"insight_card#y": insight.model_dump()},
            "changelog": [],
        }
    )
    page = render_manifest(manifest, RenderContext.model_validate({}))
    page2 = render_manifest(manifest2, context)
    assert "&lt;script&gt;" in page
    assert "<script" not in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page2
    assert "<b>bold</b>" not in page2
    assert "<script" not in page2


def test_sample_manifests_render_in_layout_order() -> None:
    for name, version, marker in [
        ("sample-builder.json", "sample-builder", "Ship one artifact today"),
        ("sample-disconnect.json", "sample-disconnect", "A good day"),
    ]:
        manifest = _load_fixture(name)
        assert manifest.version == version
        context = RenderContext.model_validate(
            {
                "free_slots": [
                    {
                        "start": datetime(
                            2026, 10, 31, 15, 0, tzinfo=MADRID
                        ).isoformat(),
                        "end": datetime(
                            2026, 10, 31, 15, 30, tzinfo=MADRID
                        ).isoformat(),
                        "label": "Synthetic slot",
                    }
                ],
                "facts": [
                    {"id": "fact_builder_1", "text": "Synthetic builder fact"},
                    {"id": "fact_disconnect_1", "text": "Synthetic disconnect fact"},
                ],
                "links": [],
            }
        )
        page = render_manifest(manifest, context)
        assert marker in page
        offsets = [page.index(f'data-block-id="{b}"') for b in manifest.layout]
        assert offsets == sorted(offsets)
        assert len(offsets) == 6


def test_offline_shell_properties() -> None:
    manifest = _load_fixture("sample-builder.json")
    context = RenderContext.model_validate(
        {
            "free_slots": [],
            "facts": [{"id": "fact_builder_1", "text": "Synthetic builder fact"}],
            "links": [],
        }
    )
    page = render_manifest(manifest, context)
    assert page.startswith("<!doctype html>")
    assert '<meta name="viewport"' in page
    assert "<style>" in page
    assert "<title>sample-builder</title>" in page
    assert "<h1>sample-builder</h1>" in page
    assert "<link" not in page
    assert "<script" not in page
    assert "<img" not in page
    assert "@import" not in page
    single = Manifest.model_validate(
        {
            "version": "v-single",
            "parent": None,
            "layout": ["checklist#x"],
            "blocks": {
                "checklist#x": {
                    "type": "checklist",
                    "dimension": BLOCKS["checklist"].sample_dimension,
                    "config": BLOCKS["checklist"].sample_config,
                    "rationale": "synthetic",
                }
            },
            "changelog": [],
        }
    )
    single_page = render_manifest(single, RenderContext.model_validate({}))
    assert "http" not in single_page


def test_context_driven_fragments() -> None:
    context = _context_with_slots_and_fact()
    slots_block = BlockConfig.model_validate(
        {
            "type": "calendar_slots",
            "dimension": "world_needs",
            "config": {"label": "Slots", "rule": "weekday afternoons"},
            "rationale": "synthetic",
        }
    )
    both = render_block("calendar_slots#a", slots_block, context)
    assert "2026-10-31 15:00" in both
    assert "2026-10-31 16:00" in both
    limited_block = BlockConfig.model_validate(
        {
            "type": "calendar_slots",
            "dimension": "world_needs",
            "config": {"label": "Slots", "rule": "weekday afternoons", "max_slots": 1},
            "rationale": "synthetic",
        }
    )
    limited = render_block("calendar_slots#a", limited_block, context)
    assert "2026-10-31 15:00" in limited
    assert "2026-10-31 16:00" not in limited
    insight_block = BlockConfig.model_validate(
        {
            "type": "insight_card",
            "dimension": "love",
            "config": {"label": "Insight", "fact_ids": ["fact_1", "fact_missing"]},
            "rationale": "synthetic",
        }
    )
    insight = render_block("insight_card#i", insight_block, context)
    assert "Synthetic fact one" in insight
    assert 'data-fact-id="fact_1"' in insight
    empty = RenderContext.model_validate({})
    assert "No free slots" in render_block("calendar_slots#a", slots_block, empty)
    assert "No insight yet" in render_block("insight_card#i", insight_block, empty)
    checklist_block = BlockConfig.model_validate(
        {
            "type": "checklist",
            "dimension": BLOCKS["checklist"].sample_dimension,
            "config": {
                "label": "List",
                "items": [
                    {"id": "a", "label": "Done item", "done": True},
                    {"id": "b", "label": "Open item"},
                ],
            },
            "rationale": "synthetic",
        }
    )
    checklist = render_block("checklist#c", checklist_block, empty)
    assert 'data-action="tick"' in checklist
    assert "checked" in checklist
    checkin_block = BlockConfig.model_validate(
        {
            "type": "checkin",
            "dimension": "limit",
            "config": {"label": "Energy", "metric": "energy"},
            "rationale": "synthetic",
        }
    )
    checkin = render_block("checkin#e", checkin_block, empty)
    assert checkin.count('data-action="checkin"') == 5
    focus_block = BlockConfig.model_validate(
        {
            "type": "focus_session",
            "dimension": "good_at",
            "config": {"label": "Focus", "minutes": 25},
            "rationale": "synthetic",
        }
    )
    focus = render_block("focus_session#f", focus_block, empty)
    assert 'data-action="focus-start"' in focus
    assert 'data-action="thumb-up"' in insight


def test_script_writes_both_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import framework.blocks.__main__ as blocks_main

    repo_root = tmp_path / "repo"
    fixtures = repo_root / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    for name in ("sample-builder.json", "sample-disconnect.json"):
        (fixtures / name).write_text((FIXTURES / name).read_text())
    monkeypatch.setattr(blocks_main, "_repo_root", lambda: repo_root)
    code = main([])
    assert code == 0
    out, _ = capsys.readouterr()
    assert out == "wrote out/sample-builder.html\nwrote out/sample-disconnect.html\n"
    for name, version in [
        ("sample-builder.html", "sample-builder"),
        ("sample-disconnect.html", "sample-disconnect"),
    ]:
        path = repo_root / "out" / name
        assert path.exists()
        assert version in path.read_text()
        assert (
            json.loads((fixtures / name.replace(".html", ".json")).read_text())[
                "version"
            ]
            == version
        )


def test_script_rejects_unexpected_argument() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["extra"])
    assert excinfo.value.code == 2
