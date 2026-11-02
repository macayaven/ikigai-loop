"""Ticket 21: the five-section story builder, first person and plain."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from typing import cast

from framework.cycle.trace import metric_sources
from framework.glimmer.metrics import select_winners
from framework.schemas.events import AppTapData, Event
from framework.telegram.models import (
    TARGET_LABELS,
    TallyItem,
    build_keyboard,
    build_ruled_keyboard,
    render_card_text,
    toast_recorded,
    why_reply_pieces,
)
from framework.tryit.replay import ReplayResult

BANNER = (
    "Ikigai Loop synthetic replay: made-up data, no model, no network, nothing stored."
)

OPENING = (
    "I write down my promises; an agent proposes which one gets "
    "my next free hour. Plain code with no model, the gate, checks each "
    "number and source the agent cites against my own data before I see "
    "it, and I choose with a tap."
)

CODE_NOTES = {
    "L1B_NUMBER_WITHOUT_METRIC_REF": (
        "the sentence holds a number none of its cited records back up"
    ),
    "L1B_METRIC_VALUE_MISMATCH": "a cited value differs from the records",
    "L1B_VALUE_PERIOD_MISMATCH": (
        "a number is tied to the wrong one of the three periods"
    ),
}

CHECK_CURL = (
    "curl -sLO "
    "https://raw.githubusercontent.com/macayaven/ikigai-loop/main/examples/verify/input.json"
)
CHECK_UVX = (
    "uvx --from git+https://github.com/macayaven/ikigai-loop "
    "verify-claims input.json; echo exit=$?"
)
CHECK_LINK = "https://macayaven.github.io/ikigai-loop/verify/"


def explain_code(code: str) -> str:
    """One code plus its plain sentence; unknown codes degrade to a true line."""
    note = plain_sentence(code)
    return f"{code} -- {note}."


def plain_sentence(code: str) -> str:
    """The plain sentence for one gate code, without the code itself."""
    return CODE_NOTES.get(
        code, "a check on the cited numbers and sources did not pass on this claim"
    )


def _fmt_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _wrap(prose: str) -> str:
    return textwrap.fill(prose, width=78)


def _hm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _day(moment: datetime) -> str:
    return moment.strftime("%b %d")


def _indented(lines: list[str]) -> str:
    return "\n".join(f"  {line}" if line.strip() else "" for line in lines)


def _card_block(result: ReplayResult, saved: str | None) -> str:
    card_text = render_card_text(result.card)
    keyboard = build_keyboard(result.card)
    key_rows = cast("list[list[dict[str, str]]]", keyboard["inline_keyboard"])
    if saved is None:
        chart_line = (
            f"[chart: {result.width}x{result.height} pixels, made in "
            "memory; you can keep it with --save card.png]"
        )
    else:
        chart_line = f"[chart: {result.width}x{result.height} pixels, saved to {saved}]"
    lines = [chart_line]
    lines.extend(card_text.splitlines())
    for row in key_rows:
        lines.append(" ".join(f"[{button['text']}]" for button in row))
    return _indented(lines)


def _tap_block(result: ReplayResult, pick: str) -> str:
    label = TARGET_LABELS[pick]
    toast = toast_recorded(label)
    ruled = build_ruled_keyboard(result.card_id, pick)
    ruled_rows = cast("list[list[dict[str, str]]]", ruled["inline_keyboard"])
    lines = [toast]
    for row in ruled_rows:
        lines.append(" ".join(f"[{button['text']}]" for button in row))
    return _indented(lines)


def _free_hour_sentence(result: ReplayResult) -> str:
    hour_start = _hm(result.hour.start)
    blocker = next(
        (
            busy
            for busy in result.busy
            if busy.end > result.slot and busy.start < result.hour.end
        ),
        None,
    )
    if blocker is None:
        return f"My hour starts at {hour_start}."
    return (
        f"My hour starts at {hour_start} because "
        f"{_hm(blocker.start)}-{_hm(blocker.end)} is already busy."
    )


def _tally_line(tally: tuple[TallyItem, ...]) -> str:
    counts = {item.label: item.count for item in tally}
    return (
        f"Builder {counts.get('Builder', 0)}, "
        f"Disconnect {counts.get('Disconnect', 0)}, "
        f"Neither {counts.get('Neither', 0)}"
    )


def build_output(result: ReplayResult, pick: str, saved: str | None) -> str:
    """Assemble the whole story as one string; the caller emits it once."""
    label = TARGET_LABELS[pick]
    before = _tally_line(result.tally_before)
    after = _tally_line(result.tally_after)
    data = result.tap_event.data
    assert isinstance(data, AppTapData)
    row_line = json.dumps(
        {"type": data.type, "block_id": data.block_id, "target": data.target}
    )
    said = _fmt_value(result.said_value)
    holds = _fmt_value(result.holds_value)
    why_lines = list(why_reply_pieces(result.card))
    metric_names = sorted(result.traced_metrics, key=_metric_order)
    winners = select_winners(
        tuple(event for event in result.events if event.collected_at <= result.as_of)
    )
    rows_by_metric: dict[str, list[Event]] = {}
    for metric_id in metric_names:
        found = metric_sources(metric_id, result.as_of, winners) or ()
        rows_by_metric[metric_id] = [
            event for event in found if event in result.traced_rows
        ]
    trace_bits: list[str] = []
    for metric_id in metric_names:
        value = result.traced_metrics[metric_id]
        head = f"{metric_id} is {_fmt_value(value)}, counted from these rows:"
        rows = [_row_words(event) for event in rows_by_metric[metric_id]]
        trace_bits.append(head + "\n" + _indented(rows))

    section5 = (
        "5. Check your own agent\n"
        + _wrap(
            "Everything above was synthetic. This part runs on your "
            "agent's output and your records."
        )
        + "\n\n"
        + CHECK_CURL
        + "\n"
        + CHECK_UVX
        + "\n"
        + CHECK_LINK
        + "\n\n"
        + _wrap(
            "You should see exit 1: the sample says 12 deploys while the records say 7."
        )
        + "\n"
        + _wrap(
            "The real loop needs a machine serving Muse Glimmer, Meta's "
            "open-weight model, for facts; a Muse Code subscription for "
            "Muse Wonder proposals; a Telegram bot; and your calendar, "
            "GitHub and screen-time data. The README says what works "
            "today."
        )
    )
    blocks = [
        BANNER + "\n" + _wrap(OPENING),
        "1. The card (synthetic)\n" + _card_block(result, saved),
        _wrap(
            "I track two goals: Builder is my work, and Disconnect is "
            "family time with screens off. "
            + "Each chart row shows three bars for earlier, prior and "
            "last, the three most recent 24-hour periods; the counts "
            "below are my earlier taps. "
            + _free_hour_sentence(result)
            + " "
            + "The Something's wrong button asks for a voice note in "
            "the real app; that path is not in this replay."
        ),
        "2. The choice (synthetic)\n"
        + _wrap(f"The replay taps {pick} ({label}) for me; nothing waits."),
        _tap_block(result, pick),
        _wrap("A real tap stores this one row on my machine.")
        + "\n"
        + _indented([row_line])
        + "\n"
        + _wrap("Nothing is stored here. My next card's chart counts it.")
        + "\n"
        + _wrap(f"My earlier choices move from {before} to {after}.")
        + "\n"
        + _wrap(
            "To choose differently, you run the same command with "
            "--pick A, --pick B or --pick neither."
        ),
        "3. A wrong number, stopped (synthetic)\n"
        + _wrap(
            "I planted a wrong number, and the gate rejected the draft. "
            "Real drafts come from a model; these words are written by "
            "hand in the same shape, and no model ran."
        ),
        _indented([f'"{result.planted_text}"'])
        + "\n"
        + _codes_block(result.planted_codes)
        + "\n"
        + _wrap(
            f"The sentence said pushes reached {said} in last while "
            f"the records hold {holds} [{result.lied_metric}]. The gate "
            "sends its reasons back and allows one retry. The second "
            "draft passed and reached the card:"
        )
        + "\n"
        + _indented([f'"{result.fixed_text}"']),
        _wrap(
            "The real run also checks a private word list; this replay's "
            "list is empty because nothing here is private."
        ),
        "4. Where a number comes from (synthetic)\n"
        + _wrap('The "Why?" button answers with the sentences behind the card:')
        + "\n"
        + _indented(why_lines),
        _wrap(
            "You can follow the first sentence back. My card sentence "
            f'"{result.fixed_text}" cites fact {result.traced_fact.id}, '
            "written by rule from the rows below, with no model."
        )
        + "\n"
        + "\n".join(trace_bits),
        section5,
    ]
    return "\n\n".join(blocks) + "\n"


def _codes_block(codes: tuple[str, ...]) -> str:
    parts: list[str] = []
    for code in codes:
        parts.append(f"  {code}")
        sentence = plain_sentence(code)
        capped = sentence[:1].upper() + sentence[1:] if sentence else sentence
        for line in _wrap(capped + ".").splitlines():
            parts.append(f"    {line}")
    return "\n".join(parts)


def _metric_order(metric_id: str) -> tuple[int, str]:
    period = metric_id.split(".")[1] if "." in metric_id else ""
    order = {"earlier": 0, "prior": 1, "last": 2}
    return (order.get(period, 99), metric_id)


def _row_words(event: Event) -> str:
    repo = getattr(event.data, "repo", "unknown repo")
    return (
        f"{_day(event.time)} {_hm(event.time)}, a push to {repo}, id {event.source_id}"
    )
