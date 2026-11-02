"""Phone chart drawn only from passed-in values, with Pillow."""

from collections.abc import Callable
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from framework.telegram.models import ChartData

Measure = Callable[[str], float]

WIDTH = 1080
MARGIN = 36
FONT_SIZE = 32
BAR_H = 28
BAR_GAP = 6
BLOCK_GAP = 18
PANEL_GAP = 28
SWATCH = 22
LABEL_BAR_GAP = 24
VALUE_GAP = 12
ITEM_GAP = 36

EARLIER = "#86b6ef"
PRIOR = "#2a78d6"
LAST = "#104281"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
GRAY = "#52514e"

PERIOD_COLORS = (EARLIER, PRIOR, LAST)

PERIOD_MISSING = ("screen earlier", "screen prior", "screen last")


def format_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _load_font() -> ImageFont.FreeTypeFont:
    font = ImageFont.load_default(size=FONT_SIZE)
    if not isinstance(font, ImageFont.FreeTypeFont):
        raise RuntimeError("chart needs a FreeType font")  # noqa: TRY004 - plan pins RuntimeError
    return font


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    draw.text(xy, text, fill=fill, font=font)


def _bar(
    draw: ImageDraw.ImageDraw, x0: float, y: float, width: float, fill: str
) -> None:
    if width <= 0:
        return
    radius = BAR_H / 2
    x1 = x0 + width
    if width >= BAR_H:
        draw.rectangle([x0, y, x1 - radius, y + BAR_H], fill=fill)
        draw.ellipse([x1 - BAR_H, y, x1, y + BAR_H], fill=fill)
    else:
        draw.ellipse([x0, y, x1, y + BAR_H], fill=fill)


def _missing_periods(data: ChartData) -> tuple[int, ...]:
    """Period rows with no bar, in fixed earlier/prior/last order."""
    return tuple(
        index for index, entry in enumerate(PERIOD_MISSING) if entry in data.missing
    )


def render_chart_png(data: ChartData) -> bytes:
    """Render the two-panel chart; same input gives the same bytes."""
    font = _load_font()
    measure = font.getlength
    present = list(data.screen)
    if data.pushes is not None:
        present.append(data.pushes)
    labels = [item.label for item in present]
    label_w = max([measure(label) for label in labels] or [0.0])
    values = [format_value(item.last) for item in present]
    value_w = max([measure(value) for value in values] or [0.0])
    bar_x0 = MARGIN + label_w + LABEL_BAR_GAP
    bar_area = max(WIDTH - MARGIN - value_w - VALUE_GAP - bar_x0, 8.0)

    top = font.getbbox("Ag")[1]
    text_h = font.getbbox("Ag")[3] - top
    legend_pitch = max(text_h + 12, SWATCH + 12)
    tally_pitch = text_h + 12
    block_h = 3 * BAR_H + 2 * BAR_GAP

    height = _layout_height(data, measure, legend_pitch, tally_pitch, block_h)
    image = Image.new("RGB", (WIDTH, height), SURFACE)
    draw = ImageDraw.Draw(image)
    _paint(
        draw,
        data,
        font,
        bar_x0,
        bar_area,
        top,
        text_h,
        legend_pitch,
        tally_pitch,
        block_h,
    )
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _legend_rows(data: ChartData, measure: Measure, legend_pitch: float) -> int:
    rows = 1
    x = float(MARGIN)
    for name in data.period_labels:
        width = measure(name) + SWATCH + 8
        if x + width > WIDTH - MARGIN and x > MARGIN:
            x = float(MARGIN)
            rows += 1
        x += width + ITEM_GAP + 4
    return rows


def _tally_rows(data: ChartData, measure: Measure, tally_pitch: float) -> float:
    extra = 0.0
    x = float(MARGIN)
    for tally in data.tally:
        width = measure(f"{tally.label} {tally.count}")
        if x + width > WIDTH - MARGIN and x > MARGIN:
            x = float(MARGIN)
            extra += tally_pitch
        x += width + ITEM_GAP
    return extra


def _layout_height(
    data: ChartData,
    measure: Measure,
    legend_pitch: float,
    tally_pitch: float,
    block_h: float,
) -> int:
    y = float(MARGIN)
    y += _legend_rows(data, measure, legend_pitch) * legend_pitch + PANEL_GAP
    if "screen" in data.missing:
        y += block_h + PANEL_GAP
    else:
        y += len(_missing_periods(data)) * tally_pitch
        if data.screen:
            y += len(data.screen) * block_h + (len(data.screen) - 1) * BLOCK_GAP
            y += PANEL_GAP
    y += block_h + PANEL_GAP
    y += _tally_rows(data, measure, tally_pitch)
    if data.tally:
        y += tally_pitch
    return int(y + MARGIN)


def _paint(
    draw: ImageDraw.ImageDraw,
    data: ChartData,
    font: ImageFont.FreeTypeFont,
    bar_x0: float,
    bar_area: float,
    top: float,
    text_h: float,
    legend_pitch: float,
    tally_pitch: float,
    block_h: float,
) -> None:
    y = float(MARGIN)
    x = float(MARGIN)
    row_top = y
    for name, color in zip(data.period_labels, PERIOD_COLORS, strict=True):
        width = draw.textlength(name, font=font)
        if x + SWATCH + 8 + width > WIDTH - MARGIN and x > MARGIN:
            x = float(MARGIN)
            row_top += legend_pitch
        draw.rectangle(
            [
                x,
                row_top + (legend_pitch - SWATCH) / 2,
                x + SWATCH,
                row_top + (legend_pitch + SWATCH) / 2,
            ],
            fill=color,
        )
        _text(
            draw,
            (x + SWATCH + 8, row_top + (legend_pitch - text_h) / 2 - top),
            name,
            INK,
            font,
        )
        x += SWATCH + 8 + width + ITEM_GAP + 4
    y = row_top + legend_pitch + PANEL_GAP

    def draw_block(
        top_y: float,
        label: str,
        trio: tuple[float, float, float],
        color_max: float,
        skip: tuple[int, ...] = (),
    ) -> None:
        _text(draw, (MARGIN, top_y + (block_h - text_h) / 2 - top), label, INK, font)
        for row, (value, color) in enumerate(zip(trio, PERIOD_COLORS, strict=True)):
            if row in skip:
                continue
            bar_y = top_y + row * (BAR_H + BAR_GAP)
            width = round(value / color_max * bar_area) if color_max > 0 else 0
            if value > 0:
                width = max(width, 4)
            _bar(draw, bar_x0, bar_y, float(width), color)
            if row == 2:
                _text(
                    draw,
                    (bar_x0 + width + VALUE_GAP, bar_y + (BAR_H - text_h) / 2 - top),
                    format_value(trio[2]),
                    GRAY,
                    font,
                )

    def no_data_line(top_y: float, entry: str) -> None:
        _text(draw, (MARGIN, top_y - top), f"{entry}: no data", INK, font)

    skipped = _missing_periods(data)
    if "screen" in data.missing:
        _text(
            draw,
            (MARGIN, y + (block_h - text_h) / 2 - top),
            "screen: no data",
            INK,
            font,
        )
        y += block_h + PANEL_GAP
    else:
        for index in skipped:
            no_data_line(y, PERIOD_MISSING[index])
            y += tally_pitch
        if data.screen:
            screen_vals = [
                v for item in data.screen for v in (item.earlier, item.prior, item.last)
            ]
            screen_max = max(screen_vals) if screen_vals else 0.0
            for index, item in enumerate(data.screen):
                if index:
                    y += BLOCK_GAP
                draw_block(
                    y,
                    item.label,
                    (item.earlier, item.prior, item.last),
                    screen_max,
                    skipped,
                )
                y += block_h
            y += PANEL_GAP

    pushes = data.pushes
    if pushes is None:
        _text(
            draw,
            (MARGIN, y + (block_h - text_h) / 2 - top),
            "pushes + PRs: no data",
            INK,
            font,
        )
    else:
        pushes_vals = [pushes.earlier, pushes.prior, pushes.last]
        pushes_max = max(pushes_vals) if pushes_vals else 0.0
        draw_block(
            y, pushes.label, (pushes.earlier, pushes.prior, pushes.last), pushes_max
        )
    y += block_h + PANEL_GAP

    x = float(MARGIN)
    for tally in data.tally:
        piece = f"{tally.label} {tally.count}"
        width = draw.textlength(piece, font=font)
        if x + width > WIDTH - MARGIN and x > MARGIN:
            x = float(MARGIN)
            y += tally_pitch
        _text(draw, (x, y - top), piece, INK, font)
        x += width + ITEM_GAP
