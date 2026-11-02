"""Ticket 17a follow-up: the checker page's own Python.

Two jobs, each taking text and returning JSON text, neither ever raising
to the page:

* ``build_checker_input`` turns pasted agent words plus record rows into
  the checker's JSON input.
* ``explain_report`` turns checker input into plain words per claim.

The page fetches this file by relative path during loading, writes it
into Pyodide's filesystem next to the bundle files, and imports it.
pytest imports it by file path. Only the standard library plus the
checker's public pieces are used: ``load_check_input`` and
``check_claims`` from ``framework.verify.hardened``,
``page_render_hardened`` from ``framework.verify.hardened``,
``extract_number_tokens`` from ``framework.briefing.numbers``, and
``collapse_text``, ``contains_token`` and ``ref_backs_token`` from the
gate's public block.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from framework.briefing.gate import collapse_text, contains_token, ref_backs_token
from framework.briefing.numbers import NumberToken, extract_number_tokens
from framework.verify.hardened import (
    check_claims,
    load_check_input,
    page_render_hardened,
)

JOB_ERROR = "could not put that into words"
"""Fixed short message both jobs return when anything unexpected happens."""

type MetricNumber = int | float
"""A JSON number that stays an int when whole, so big values stay exact."""

_NO_NUMBER_REASON = "It has no number in it."

_MARKER_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
_SPLIT_RE = re.compile(r"(?<=[.?!]) +")


@dataclass(frozen=True)
class _Record:
    """One valid records-table row: metric id, value, 1-based row number."""

    name: str
    value: MetricNumber
    row: int


def _json_number(value: Decimal) -> MetricNumber | None:
    """Plain int or float for a token value, or None when it cannot be held."""
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


def _split_sentences(text: str) -> list[str]:
    """Lines minus one leading list marker each, then split after . ? !."""
    sentences: list[str] = []
    for line in text.splitlines():
        line = _MARKER_RE.sub("", line)
        for piece in _SPLIT_RE.split(line):
            piece = piece.strip()
            if piece:
                sentences.append(piece)
    return sentences


def _parse_rows(rows_json: str) -> tuple[list[_Record], list[str]]:
    """Read the records table; every flaw comes back as a plain problem."""
    try:
        raw = json.loads(rows_json)
    except (ValueError, RecursionError):
        return [], ["The records table could not be read."]
    if not isinstance(raw, list):
        return [], ["The records table could not be read."]
    records: list[_Record] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(raw):
        lineno = index + 1
        if isinstance(row, dict):
            name_raw: Any = row.get("name", "")
            number_raw: Any = row.get("number", "")
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            name_raw, number_raw = row
        else:
            problems.append(f"Row {lineno} is not a name-and-number pair.")
            continue
        name = " ".join(str(name_raw).split()) if name_raw is not None else ""
        number = str(number_raw).strip() if number_raw is not None else ""
        if not name and not number:
            continue
        if not name:
            problems.append(
                f"Row {lineno} gives a number but no name. Add a name or clear the row."
            )
            continue
        if not number:
            problems.append(
                f'Row {lineno} names "{name}" but gives no number. '
                "Add the number your records show."
            )
            continue
        tokens = extract_number_tokens(number)
        if len(tokens) != 1:
            problems.append(
                f'Row {lineno} ("{name}") is not a single number: '
                f'"{number}". Write one number per row.'
            )
            continue
        value = _json_number(tokens[0].value)
        if value is None:
            problems.append(
                f'Row {lineno} ("{name}") is too large to check. '
                "Write one plain number per row."
            )
            continue
        first = seen.get(name.casefold())
        if first is not None:
            problems.append(
                f'Row {lineno} repeats the name "{name}" '
                f"from row {first}. Keep one row per name."
            )
            continue
        seen[name.casefold()] = lineno
        records.append(_Record(name=name, value=value, row=lineno))
    return records, problems


def _phrase_spans(sentence: str, name: str) -> list[tuple[int, int]]:
    """Spans of the name read as one run of words, whatever the case."""
    pattern = (
        r"(?<![\w])"
        + r"\s+".join(re.escape(word) for word in name.split())
        + r"(?![\w])"
    )
    return [
        (match.start(), match.end())
        for match in re.finditer(pattern, sentence, re.IGNORECASE)
    ]


def _counting_records(sentence: str, records: list[_Record]) -> list[_Record]:
    """Rows whose every name word sits in the sentence as a whole word.

    A shorter name whose words all sit inside a longer counting name still
    counts when it also appears outside that longer name: blank every run
    of each beating longer name, and keep the shorter one when its words
    still all match in what is left.
    """
    collapsed = collapse_text(sentence)
    counting: list[_Record] = []
    for record in records:
        words = collapse_text(record.name).split(" ")
        if all(contains_token(collapsed, word) for word in words):
            counting.append(record)
    kept: list[_Record] = []
    for candidate in counting:
        candidate_words = set(collapse_text(candidate.name).split(" "))
        beaters = [
            other
            for other in counting
            if candidate is not other
            and candidate_words <= set(collapse_text(other.name).split(" "))
            and len(collapse_text(other.name).split(" ")) > len(candidate_words)
        ]
        if not beaters:
            kept.append(candidate)
            continue
        blanked = sentence
        for beater in beaters:
            for start, end in _phrase_spans(blanked, beater.name):
                blanked = blanked[:start] + " " * (end - start) + blanked[end:]
        if all(
            contains_token(collapse_text(blanked), word) for word in candidate_words
        ):
            kept.append(candidate)
    return kept


def _word_starts(sentence: str, word: str) -> list[int]:
    """Starts of whole-word hits in the original text, whatever the case."""
    return [
        match.start()
        for match in re.finditer(
            r"(?<![\w])" + re.escape(word) + r"(?![\w])", sentence, re.IGNORECASE
        )
    ]


def _pair_rows(
    sentence: str, counting: list[_Record]
) -> tuple[list[tuple[_Record, NumberToken]], list[str]]:
    """Cite the one named record with its nearest number, or cite nothing.

    One record per sentence: a sentence naming exactly one record cites it
    with the nearest number; a sentence naming two or more records, or none,
    cites nothing, so the checker fails it. Numbers come from the original
    sentence, exactly as the checker reads that claim, with the cited
    record's name masking its own digits.
    """

    def _first_hit(record: _Record) -> int:
        hits = [
            hit
            for word in collapse_text(record.name).split(" ")
            for hit in _word_starts(sentence, word)
        ]
        return min(hits) if hits else len(sentence)

    ordered = sorted(counting, key=_first_hit)
    if len(counting) == 1:
        record = ordered[0]
        tokens = extract_number_tokens(sentence, [record.name])
        hits = [
            hit
            for word in collapse_text(record.name).split(" ")
            for hit in _word_starts(sentence, word)
        ]
        if tokens and hits:
            nearest = min(
                tokens, key=lambda token: min(abs(token.start - hit) for hit in hits)
            )
            return [(record, nearest)], [f"{record.name} was read as {nearest.raw}."]
        return [], [
            f"{record.name} names no number in that sentence, so it is not cited."
        ]
    if counting:
        names = " and ".join(record.name for record in ordered)
        return [], [
            (
                f"It names {names} in one sentence, so it cites none of them. "
                "Put each in its own sentence."
            )
        ]
    return [], ["None of your record names appear in it, so it cites nothing."]


def _build_checker_input(agent_text: str, rows_json: str) -> str:
    records, problems = _parse_rows(rows_json)
    sentences = _split_sentences(agent_text)
    pairings: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for position, sentence in enumerate(sentences):
        claim_id = f"s{position + 1}"
        if not extract_number_tokens(sentence):
            unchecked.append({"sentence_id": claim_id, "reason": _NO_NUMBER_REASON})
            continue
        counting = _counting_records(sentence, records)
        pairs, lines = _pair_rows(sentence, counting)
        pairings.append({"sentence_id": claim_id, "lines": lines})
        claims.append(
            {
                "id": claim_id,
                "text": sentence,
                "metric_refs": [
                    {
                        "metric_id": record.name,
                        "value": _json_number(token.value),
                    }
                    for record, token in pairs
                ],
            }
        )
    # No labels, no order, no deny_terms, no advice_words, and empty facts:
    # with labels declared, the checker fails a lone value next to words
    # like "rose" or "fell", and fails any sentence that names two records.
    # Both are right for the full checker, and both read as nonsense in a
    # plain two-column form. Without them the checker compares each number
    # with its record, and a number with no record behind it still fails, so
    # no period column is needed: a name can carry a month, such as
    # "November deploys", when someone needs one.
    built: str | None = None
    if not problems and claims:
        built = json.dumps(
            {
                "claims": claims,
                "facts": {},
                "metrics": {record.name: record.value for record in records},
            },
            indent=2,
        )
    return json.dumps(
        {
            "input": built,
            "pairings": pairings,
            "unchecked": unchecked,
            "problems": problems,
        }
    )


def build_checker_input(agent_text: str, rows_json: str) -> str:
    """Job 1: pasted words plus record rows as JSON text to checker input."""
    try:
        return _build_checker_input(agent_text, rows_json)
    except Exception:  # noqa: BLE001 - the page gets a fixed message, never a traceback
        return json.dumps({"error": JOB_ERROR})


_MEANINGS: dict[str, str] = {
    "L1B_CLAIM_WITHOUT_EVIDENCE": "the sentence names no record",
    "L1B_UNKNOWN_FACT": "a cited source is not in your records",
    "L1B_UNKNOWN_METRIC": "a named record is not in your table",
    "L1B_METRIC_VALUE_MISMATCH": "a number differs from your records",
    "L1B_NUMBER_WITHOUT_METRIC_REF": "a number names no record",
    "L1B_METRIC_LABEL_MISSING": "the wording does not name the record",
    "L1B_TOO_MANY_METRICS": "the sentence mixes records that belong apart",
    "L1B_DIRECTION_MISMATCH": "a direction word disagrees with the numbers",
    "L1B_NEGATED_CLAIM": "the sentence says the opposite of the number",
    "L1B_UNVERIFIABLE_QUANTITY": "the sentence uses a quantity word instead of digits",
    "L1B_UNIT_MISMATCH": "the unit in the sentence differs from the record's unit",
    "L1B_PERIOD_WORD_MISSING": "the sentence does not name the record's period",
    "L1B_VALUE_PERIOD_MISMATCH": "a number sits beside the wrong period",
    "L1_PRIVATE_TERM": "private wording",
    "L1_SECRET": "secret-like value",
    "L1_PII": "contact detail",
    "L1_ADVICE": "advice-like wording",
}

_GAP_WORDS: dict[str, str] = {
    "metric naming": "naming words beyond the record name were not asked for",
    "direction": "direction words were not asked for",
    "unit": "a unit was not asked for",
    "period name": "a period was not asked for",
    "value-period binding": "period binding was not asked for",
}


def _differs(left: MetricNumber, right: MetricNumber) -> bool:
    try:
        return bool(Decimal(str(left)) != Decimal(str(right)))
    except Exception:  # noqa: BLE001 - an unreadable number counts as different
        return True


def _backs(value: MetricNumber, token: NumberToken) -> bool:
    try:
        return bool(ref_backs_token(value, token.places, abs(token.value)))
    except Exception:  # noqa: BLE001 - an unreadable ref backs nothing
        return False


def _finding_sentence(
    code: str,
    message: str,
    text: str,
    fact_ids: list[str],
    refs: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    """Plain words for one finding; values come from the input, never messages."""
    if code == "L1B_METRIC_VALUE_MISMATCH":
        parts = [
            f"It gives {ref['value']} for {ref['metric_id']}; "
            f"your records say {metrics[ref['metric_id']]}."
            for ref in refs
            if ref["metric_id"] in metrics
            and _differs(ref["value"], metrics[ref["metric_id"]])
        ]
        return " ".join(parts) if parts else "It gives a number your records deny."
    if code == "L1B_NUMBER_WITHOUT_METRIC_REF":
        known = list(fact_ids) + [str(ref["metric_id"]) for ref in refs]
        bare = [
            f"It says {token.raw} and none of your records backs that number."
            for token in extract_number_tokens(text, known)
            if not any(_backs(ref["value"], token) for ref in refs)
        ]
        return (
            " ".join(bare)
            if bare
            else "It says a number and none of your records backs that number."
        )
    if code == "L1B_CLAIM_WITHOUT_EVIDENCE":
        return "Nothing from your records was checked against it."
    if code == "L1B_UNKNOWN_METRIC":
        missing = [
            f"It names {ref['metric_id']}, which is not in your records table."
            for ref in refs
            if ref["metric_id"] not in metrics
        ]
        return " ".join(missing) if missing else "It names a record you never gave."
    if code == "L1B_UNKNOWN_FACT":
        return "It cites a source your records do not list."
    if code == "L1B_METRIC_LABEL_MISSING":
        if "without citing it" in message:
            return "It names another record it does not cite."
        return "It does not name the record it cites."
    if code == "L1B_TOO_MANY_METRICS":
        return "It mixes records that belong in separate sentences."
    if code == "L1B_DIRECTION_MISMATCH":
        return "A direction word in it disagrees with the cited numbers."
    if code == "L1B_NEGATED_CLAIM":
        return "The sentence says the opposite of the number."
    if code == "L1B_UNVERIFIABLE_QUANTITY":
        return "The sentence uses a quantity word instead of digits."
    if code == "L1B_UNIT_MISMATCH":
        return "The unit in the sentence differs from the record's unit."
    if code == "L1B_PERIOD_WORD_MISSING":
        return "The sentence does not name the record's period."
    if code == "L1B_VALUE_PERIOD_MISMATCH":
        return "A number sits beside the wrong period."
    if code == "L1_PRIVATE_TERM":
        return (
            "Its wording is hidden: it tripped a private-word check, "
            "so the page shows nothing from it."
        )
    if code == "L1_SECRET":
        return (
            "Its wording is hidden: it looks like it carries a secret-like "
            "value, so the page shows nothing from it."
        )
    if code == "L1_PII":
        return (
            "Its wording is hidden: it looks like it carries contact "
            "details, so the page shows nothing from it."
        )
    if code == "L1_ADVICE":
        return (
            "Its wording is hidden: it reads like advice, "
            "so the page shows nothing from it."
        )
    return f"The checker flagged this sentence ({code})."


def _gaps_line(skipped: list[Any]) -> str | None:
    """One grouped plain line naming every skipped check on a claim."""
    parts = []
    for skip in skipped:
        words = _GAP_WORDS.get(str(skip.check), str(skip.check))
        parts.append("not checked: " + words)
    if not parts:
        return None
    return (
        "Not checked: "
        + "; ".join(part[len("not checked: ") :] for part in parts)
        + "."
    )


def _explain_report(checker_input: str) -> str:
    rendered = json.loads(page_render_hardened(checker_input))
    if not isinstance(rendered, dict) or rendered.get("exit_code") == 2:
        return json.dumps({"error": JOB_ERROR})
    passed = rendered.get("exit_code") == 0
    validated = load_check_input(checker_input)
    report = check_claims(validated)
    by_claim: dict[str, list[Any]] = {}
    for violation in report.violations:
        by_claim.setdefault(violation.claim_id, []).append(violation)
    metrics: dict[str, Any] = dict(validated.metrics)
    total = len(validated.claims)
    bad = sum(1 for claim in validated.claims if claim.id in by_claim)
    gaps_by_claim: dict[str, str] = {}
    for entry in report.coverage:
        line = _gaps_line(list(entry.skipped))
        if line is not None:
            gaps_by_claim[entry.claim_id] = line
    if total == 1:
        if passed:
            overall = "The numbers in this sentence match your records. Other words weren't checked."
        else:
            overall = "This sentence didn't pass. See why below."
    elif passed:
        overall = f"The numbers in all {total} checked sentences match your records. Other words weren't checked."
    else:
        overall = f"{bad} of {total} checked sentences didn't pass. See why below."
    if passed and gaps_by_claim:
        overall += " Some checks didn't run."
    out_claims: list[dict[str, Any]] = []
    for claim in validated.claims:
        findings = by_claim.get(claim.id, [])
        hidden = any(not item.code.startswith("L1B_") for item in findings)
        refs = [
            {"metric_id": ref.metric_id, "value": ref.value}
            for ref in claim.metric_refs
        ]
        plain: list[dict[str, Any]] = []
        for item in findings:
            if hidden and item.code.startswith("L1B_"):
                sentence = (
                    "One more finding on it: "
                    + _MEANINGS.get(item.code, "a finding with no plain words yet")
                    + "."
                )
            else:
                sentence = _finding_sentence(
                    item.code,
                    item.message,
                    claim.text,
                    list(claim.fact_ids),
                    refs,
                    metrics,
                )
            plain.append(
                {
                    "code": item.code,
                    "sentence": sentence,
                    "meaning": _MEANINGS.get(
                        item.code, "a finding with no plain words yet"
                    ),
                }
            )
        out_claims.append(
            {
                "id": claim.id,
                "passed": not findings,
                "text": None if hidden else claim.text,
                "hidden": hidden,
                "findings": plain,
                "gaps": gaps_by_claim.get(claim.id),
            }
        )
    return json.dumps({"overall": overall, "passed": passed, "claims": out_claims})


def explain_report(checker_input: str) -> str:
    """Job 2: checker input as JSON text to an overall line plus plain claims."""
    try:
        return _explain_report(checker_input)
    except Exception:  # noqa: BLE001 - the page gets a fixed message, never a traceback
        return json.dumps({"error": JOB_ERROR})
