"""Ticket 10b: no-raise fuzz over number tokens and random strings.

Seeded with ``random.Random`` under a pinned seed; no new dependency.
The D15 crash guard is load-bearing here: this file fails on the
unfixed gate (the R1 crash string raises ``InvalidOperation`` out of
``evaluate_briefing``) and fails again with the guard removed.
"""

from __future__ import annotations

import random
from typing import Any

from evals.briefing_cases import base_case_with_parent
from evals.redteam import build_context, build_host_briefing
from framework.briefing import claim_text as claim_text_module
from framework.briefing.gate import GateResult, evaluate_briefing
from framework.briefing.normalize import (
    has_unsafe_text,
    normalize_text,
)
from framework.briefing.numbers import extract_number_tokens
from framework.briefing.quantities import find_unverifiable_quantities

SEED = 20261101

_REF_VALUES = (0, 1, 3, 0.1, 4.75, 1e22, 1e308, 5e-324, -3)

_ALPHABET = (
    "\u200b\u200e\u202a\u202e\u2066\ufeff\u00ad"
    "\u0301\u034f\u0488\u20d0"
    "\u0001\u007f"
    "\uf000"
    "\u0378"
    "\U0001f600\U0001f4c8\u2192\u00d7\u00f7<>=~"
    "\uff21\uff42\ufb01\u00be\u2153\u2044\u00b2"
    "\u0430\u03b1\u03bf"
    "0123456789\u0663\u0968\uff12"
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " \t.,;:!?()\"'-+/%"
)


def _number_token_texts(rng: random.Random) -> list[str]:
    texts: list[str] = []
    digits = "0123456789"
    while len(texts) < 2000:
        kind = rng.randrange(10)
        if kind == 0:
            texts.append(
                "".join(rng.choice(digits) for _ in range(rng.randint(1, 400)))
            )
        elif kind == 1:
            texts.append(
                "".join(rng.choice(digits) for _ in range(rng.randint(1, 12)))
                + "."
                + "".join(rng.choice(digits) for _ in range(rng.randint(0, 400)))
            )
        elif kind == 2:
            groups = [str(rng.randint(100, 999)) for _ in range(rng.randint(2, 6))]
            texts.append(",".join(groups))
        elif kind == 3:
            texts.append("0" * rng.randint(1, 6) + str(rng.randint(0, 999)))
        elif kind == 4:
            texts.append(str(rng.randint(0, 999)) + "%")
        elif kind == 5:
            texts.append(rng.choice(["-", "+"]) + str(rng.randint(0, 999)))
        elif kind == 6:
            texts.append(
                "".join(
                    rng.choice("\u0660\u0661\u0662\u0663\u0966\uff11\uff12")
                    for _ in range(rng.randint(1, 6))
                )
            )
        elif kind == 7:
            texts.append(
                str(rng.randint(0, 9))
                + rng.choice("\u00b2\u00b3\u00bc\u00bd\u00be\u2153")
            )
        elif kind == 8:
            texts.append(str(rng.randint(0, 9)) + "e" + rng.choice(["9", "99", "308"]))
        else:
            texts.append(
                str(rng.randint(0, 99))
                + rng.choice([":", ".", "-", "/", " "])
                + str(rng.randint(0, 99))
            )
    return texts


def _single_refs(value: float) -> list[dict[str, Any]]:
    return [{"metric_id": "period.earlier.pushes", "value": value}]


def _two_refs(first: float, second: float) -> list[dict[str, Any]]:
    return [
        {"metric_id": "period.earlier.pushes", "value": first},
        {"metric_id": "period.last.pushes", "value": second},
    ]


def test_number_tokens_never_raise() -> None:
    rng = random.Random(SEED)
    context = build_context()
    texts = _number_token_texts(rng)
    assert len(texts) >= 2000
    checked = 0
    for index, token in enumerate(texts):
        first = _REF_VALUES[index % len(_REF_VALUES)]
        second = _REF_VALUES[(index + 3) % len(_REF_VALUES)]
        briefings = [
            build_host_briefing(
                f"Pushes in earlier were {token}.", [], _single_refs(first)
            ),
            build_host_briefing(
                f"Pushes moved from {token} in earlier to 0 in last.",
                [],
                _two_refs(first, second),
            ),
        ]
        parented = base_case_with_parent("builder")
        parented.briefing["sections"][1]["claims"][0]["text"] = (
            f"Programming moved by {token} since the parent briefing"
        )
        briefings.append(parented.briefing)
        for briefing in briefings:
            try:
                result = evaluate_briefing(briefing, context)
            except Exception as exc:
                raise AssertionError(
                    f"evaluate_briefing raised on {token!r}: {exc!r}"
                ) from exc
            assert isinstance(result, GateResult), token
            checked += 1
    assert checked >= 6000


def test_random_strings_never_raise() -> None:
    rng = random.Random(SEED + 1)
    context = build_context()
    statements = (
        "Pushes fell from 3 in earlier to 1 in prior and to 0 in last.",
        "Programming screen hours fell from 4.75 in prior to 1.75 in last.",
    )
    count = 0
    for _ in range(500):
        text = "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(1, 60)))
        if not text.strip():
            text = "x" + text
        label = f"random string {text!r}"
        try:
            result = evaluate_briefing(build_host_briefing(text, ["f1"], []), context)
        except Exception as exc:
            raise AssertionError(f"{label} raised in gate: {exc!r}") from exc
        assert isinstance(result, GateResult), label
        assert normalize_text(normalize_text(text)) == normalize_text(text), label
        assert isinstance(has_unsafe_text(text), bool), label
        tokens = extract_number_tokens(text, {"f1"})
        assert isinstance(tokens, tuple), label
        kinds = find_unverifiable_quantities(
            text,
            has_metric_refs=False,
            has_backed_fifty=False,
            in_since_last=False,
            cites_hours_metric=False,
        )
        assert isinstance(kinds, tuple), label
        claim_codes = claim_text_module.claim_text_codes(
            text,
            section_type="working",
            has_metric_refs=False,
            cited_refs=(),
            cited_fact_statements=statements,
            snapshot_metric_ids=tuple(context.metrics.values.keys()),
            number_tokens=tokens,
        )
        assert isinstance(claim_codes, tuple), label
        fact_codes = claim_text_module.fact_claim_codes(
            text,
            statements,
            snapshot_metric_ids=tuple(context.metrics.values.keys()),
        )
        assert isinstance(fact_codes, tuple), label
        count += 1
    assert count >= 500


def test_lone_surrogates_never_raise_direct_calls() -> None:
    context = build_context()
    statements = ("Pushes fell from 3 in earlier to 0 in last.",)
    for text in ("\ud800", "a\ud800b", "\udc00\ud800"):
        label = f"surrogate input {text!r}"
        assert normalize_text(normalize_text(text)) == normalize_text(text), label
        assert isinstance(has_unsafe_text(text), bool), label
        assert isinstance(extract_number_tokens(text, set()), tuple), label
        assert isinstance(
            find_unverifiable_quantities(
                text,
                has_metric_refs=False,
                has_backed_fifty=False,
                in_since_last=False,
                cites_hours_metric=False,
            ),
            tuple,
        ), label
        assert isinstance(
            claim_text_module.claim_text_codes(
                text,
                section_type="working",
                has_metric_refs=False,
                cited_fact_statements=statements,
                snapshot_metric_ids=tuple(context.metrics.values.keys()),
            ),
            tuple,
        ), label
        assert isinstance(
            claim_text_module.fact_claim_codes(text, statements), tuple
        ), label
