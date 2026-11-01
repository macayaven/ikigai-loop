"""Chart rendering: bytes, chunks, labels, layout floors (synthetic only)."""

import io
import struct

import PIL.ImageDraw
import PIL.ImageFont
import pytest
from PIL import Image, ImageFont
from telegram_fake import no_sockets  # noqa: F401  (autouse fixture)

from framework.telegram import chart as chart_module
from framework.telegram.chart import format_value, render_chart_png
from framework.telegram.models import ChartData, ChartSeries, TallyItem


def series(label: str, earlier: float, prior: float, last: float) -> ChartSeries:
    return ChartSeries(label=label, earlier=earlier, prior=prior, last=last)


def data(**extra: object) -> ChartData:
    payload: dict[str, object] = {
        "period_labels": ["Morning", "Midday", "Evening"],
        "screen": [
            series("Build minutes", 20.0, 35.0, 42.0),
            series("Call minutes", 0.0, 15.0, 10.0),
        ],
        "pushes": series("Pushes", 1.0, 2.0, 3.0),
        "tally": [
            TallyItem(label="Build sessions", count=4),
            TallyItem(label="Calls logged", count=2),
        ],
    }
    payload.update(extra)
    return ChartData.model_validate(payload)


def worst_case() -> ChartData:
    screen = [
        series(f"W{'M' * 16}{i}", 1000000.0, 999999.0, 999998.0) for i in range(8)
    ]
    return ChartData.model_validate(
        {
            "period_labels": ["Morning hours", "Midday hours", "Evening hours"],
            "screen": screen,
            "pushes": series(f"P{'W' * 16}0", 500000.0, 750000.0, 999999.0),
            "tally": [
                TallyItem(label=f"Tally tally {i} WW", count=123456 + i)
                for i in range(4)
            ],
        }
    )


def chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    found: list[tuple[bytes, bytes]] = []
    pos = 8
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        found.append((kind, png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return found


def recorded_texts(
    monkeypatch: pytest.MonkeyPatch, payload: ChartData
) -> tuple[bytes, list[tuple[str, tuple[float, float]]]]:
    seen: list[tuple[str, tuple[float, float]]] = []
    original = PIL.ImageDraw.ImageDraw.text

    def spy(
        self: object,
        xy: tuple[float, float],
        text: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        seen.append((text, (float(xy[0]), float(xy[1]))))
        return original(self, xy, text, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PIL.ImageDraw.ImageDraw, "text", spy)
    return render_chart_png(payload), seen


def expected_strings(payload: ChartData) -> set[str]:
    wanted = set(payload.period_labels)
    for item in list(payload.screen) + [payload.pushes]:
        wanted.add(item.label)
        wanted.add(format_value(item.last))
    for tally in payload.tally:
        wanted.add(f"{tally.label} {tally.count}")
    return wanted


def test_png_signature_and_determinism() -> None:
    payload = data()
    first = render_chart_png(payload)
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_chart_png(payload) == first


def test_no_text_or_time_chunks() -> None:
    kinds = {kind for kind, _ in chunks(render_chart_png(data()))}
    assert kinds.isdisjoint({b"tEXt", b"iTXt", b"zTXt", b"tIME"})
    assert b"IEND" in kinds


def test_label_seam_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = data()
    _, seen = recorded_texts(monkeypatch, payload)
    drawn = {text for text, _ in seen}
    assert drawn == expected_strings(payload)


def test_odd_labels_drawn_with_no_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = data(
        period_labels=["Q1; revival?", "H2 (draft)", "Wk-12_final"],
        screen=[series("mix & match 7", 5.0, 0.0, 9.0)],
        pushes=series("push-9_x", 0.0, 0.0, 1.0),
        tally=[TallyItem(label="n/a count!", count=0)],
    )
    _, seen = recorded_texts(monkeypatch, payload)
    drawn = {text for text, _ in seen}
    assert drawn == expected_strings(payload)
    assert "mix & match 7" in drawn


def test_worst_case_layout_inside_canvas_without_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = worst_case()
    png, seen = recorded_texts(monkeypatch, payload)
    image = Image.open(io.BytesIO(png))
    width, height = image.size
    assert max(width, height) < 1280
    font = ImageFont.load_default(size=32)
    boxes: list[tuple[float, float, float, float, str]] = []
    for text, (x, y) in seen:
        left, top, right, bottom = font.getbbox(text)
        boxes.append((x + left, y + top, x + right, y + bottom, text))
    assert boxes, "worst case must draw strings"
    for left, top, right, bottom, text in boxes:
        assert 0 <= left and 0 <= top, f"{text!r} outside canvas"
        assert right <= width and bottom <= height, f"{text!r} outside canvas"
    for i, first in enumerate(boxes):
        for second in boxes[i + 1 :]:
            overlap = not (
                first[2] <= second[0]
                or second[2] <= first[0]
                or first[3] <= second[1]
                or second[3] <= first[1]
            )
            assert not overlap, f"{first[4]!r} overlaps {second[4]!r}"


def ramp_pixels(png: bytes) -> bool:
    raw = Image.open(io.BytesIO(png)).tobytes()
    triples = {bytes(raw[i : i + 3]) for i in range(0, len(raw), 3)}
    return bool(triples & {b"\x86\xb6\xef", b"\x2a\x78\xd6", b"\x10\x42\x81"})


def ellipse_calls(monkeypatch: pytest.MonkeyPatch, payload: ChartData) -> int:
    count = {"n": 0}
    original = PIL.ImageDraw.ImageDraw.ellipse

    def spy(self: object, *args: object, **kwargs: object) -> None:
        count["n"] += 1
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PIL.ImageDraw.ImageDraw, "ellipse", spy)
    render_chart_png(payload)
    return count["n"]


def test_all_zero_input_renders_without_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = data(
        screen=[series("Idle", 0.0, 0.0, 0.0)],
        pushes=series("Pushes", 0.0, 0.0, 0.0),
        tally=[],
    )
    png = render_chart_png(payload)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # Only the legend swatches carry ramp colours; no bar draws any.
    assert ellipse_calls(monkeypatch, payload) == 0


def test_tiny_value_stays_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = data(
        screen=[series("Tiny", 0.001, 1000.0, 1000.0)],
        pushes=series("Pushes", 0.0, 0.0, 1.0),
        tally=[],
    )
    png = render_chart_png(payload)
    assert ramp_pixels(png)
    # Every non-zero bar draws exactly one ellipse; the tiny value would
    # round to zero without the 4 px floor, so the count pins the floor.
    values = [0.001, 1000.0, 1000.0, 0.0, 0.0, 1.0]
    assert ellipse_calls(monkeypatch, payload) == sum(1 for v in values if v > 0)


def test_panels_use_independent_scales(monkeypatch: pytest.MonkeyPatch) -> None:
    rights: list[float] = []
    original = PIL.ImageDraw.ImageDraw.ellipse

    def spy(self: object, xy: object, *args: object, **kwargs: object) -> None:
        assert isinstance(xy, list)
        rights.append(float(xy[2]))
        return original(self, xy, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PIL.ImageDraw.ImageDraw, "ellipse", spy)
    payload = data(
        screen=[series("Big", 1000.0, 1000.0, 1000.0)],
        pushes=series("Pushes", 3.0, 3.0, 3.0),
        tally=[],
    )
    render_chart_png(payload)
    # Six non-zero bars, and both panel maxima span the full bar area.
    assert len(rights) == 6
    assert len(set(rights)) == 1


def test_empty_screen_drops_panel_but_keeps_legend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = data(screen=[], tally=[])
    png, seen = recorded_texts(monkeypatch, payload)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    drawn = {text for text, _ in seen}
    assert {"Morning", "Midday", "Evening"} <= drawn
    assert "Build minutes" not in drawn


def test_tally_wraps_to_further_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = worst_case()
    _, seen = recorded_texts(monkeypatch, payload)
    tally_texts = {f"Tally tally {i} WW {123456 + i}" for i in range(4)}
    rows = {y for text, (_, y) in seen if text in tally_texts}
    assert len(rows) >= 2


def test_value_formatting_whole_and_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = data(
        screen=[series("Whole", 1.0, 2.0, 42.0)],
        pushes=series("Pushes", 0.0, 0.0, 42.5),
        tally=[],
    )
    _, seen = recorded_texts(monkeypatch, payload)
    drawn = {text for text, _ in seen}
    assert "42" in drawn
    assert "42.5" in drawn


def test_non_freetype_font_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BitmapStandIn:
        def getlength(self, text: str) -> float:
            raise AssertionError("must raise before measuring")

    monkeypatch.setattr(PIL.ImageFont, "load_default", lambda *a, **k: BitmapStandIn())
    with pytest.raises(RuntimeError):
        chart_module.render_chart_png(data())
