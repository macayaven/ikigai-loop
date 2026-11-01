"""Ticket 9c: R10 loader, frozen baseline, gated runner, decision rule."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals import r10 as r10_module
from evals.r10 import (
    R10_CASES_SHA256,
    R10Stats,
    compute_stats,
    is_correct,
    is_strict,
    load_r10_cases,
    mcnemar_p,
    r10_decision,
    render_report,
)

KEYWORDS_SHA256 = "51019576487276a0fb04e6d3c94690c2bc85acd33e45cf65259beb505319c441"

LABELS8 = [
    "iki-deep",
    "iki-meeting",
    "iki-family",
    "iki-social",
    "iki-care",
    "iki-rest",
    "iki-admin",
    "iki-unknown",
]


def _good_payload() -> dict:
    return {
        "labels": list(LABELS8),
        "cases": [
            {
                "id": "r10-t1",
                "title": "Morning solo build block",
                "label": "iki-deep",
                "accepted": ["iki-deep"],
                "class": "work-solo",
                "lang": "en",
                "note": "invented case one",
            },
            {
                "id": "r10-t2",
                "title": "Llamada semanal de proyecto",
                "label": "iki-meeting",
                "accepted": ["iki-meeting", "iki-deep"],
                "class": "work-group",
                "lang": "es",
                "note": "invented case two",
            },
            {
                "id": "r10-t3",
                "title": "Quiet evening with a record",
                "label": "iki-rest",
                "accepted": ["iki-rest"],
                "class": "off",
                "lang": "en",
                "note": "invented case three",
            },
        ],
    }


def _write(payload: dict, tmp_path: Path, name: str = "cases.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loader_accepts_three_invented_cases(tmp_path: Path) -> None:
    loaded = load_r10_cases(_write(_good_payload(), tmp_path))
    assert list(loaded.labels) == LABELS8
    assert len(loaded.cases) == 3
    assert loaded.cases[1].accepted == ("iki-meeting", "iki-deep")


def _rejection_payloads() -> "list[tuple[str, object]]":
    good = _good_payload()
    cases: list[tuple[str, object]] = []

    top = {"labels": good["labels"], "cases": good["cases"], "extra": 1}
    cases.append(("top-level", top))

    wrong_keys = dict(good["cases"][0])
    wrong_keys["bogus"] = 1
    cases.append(("case-keys", {"labels": good["labels"], "cases": [wrong_keys]}))

    bad_labels = {"labels": LABELS8[:7] + ["iki-secret"], "cases": good["cases"]}
    cases.append(("labels-set", bad_labels))

    dup = [dict(good["cases"][0]), dict(good["cases"][0]), dict(good["cases"][2])]
    cases.append(("duplicate-id", {"labels": good["labels"], "cases": dup}))

    empty = [dict(good["cases"][0], title="")]
    cases.append(("empty-title", {"labels": good["labels"], "cases": empty}))

    bad_label = [dict(good["cases"][0], label="iki-secret")]
    cases.append(("label-range", {"labels": good["labels"], "cases": bad_label}))

    bad_acc = [dict(good["cases"][0], accepted=["iki-secret"])]
    cases.append(("accepted-range", {"labels": good["labels"], "cases": bad_acc}))

    swapped = [dict(good["cases"][1], accepted=["iki-deep", "iki-meeting"])]
    cases.append(("accepted-first", {"labels": good["labels"], "cases": swapped}))

    none_acc = [dict(good["cases"][0], accepted=[])]
    cases.append(("accepted-empty", {"labels": good["labels"], "cases": none_acc}))

    three_acc = [
        dict(good["cases"][0], accepted=["iki-deep", "iki-meeting", "iki-rest"])
    ]
    cases.append(("accepted-three", {"labels": good["labels"], "cases": three_acc}))
    return cases


@pytest.mark.parametrize("name,payload", _rejection_payloads())
def test_loader_rejects_each_fault(tmp_path: Path, name: str, payload: object) -> None:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_r10_cases(path)
    message = str(excinfo.value)
    assert "Morning solo build block" not in message
    assert "invented case" not in message
    if name != "top-level" and name != "labels-set":
        assert "r10 case " in message


def test_r10_keywords_frozen() -> None:
    data = Path("evals/r10_keywords.py").read_bytes()
    assert hashlib.sha256(data).hexdigest() == KEYWORDS_SHA256


def test_keyword_list_always_valid_and_deterministic() -> None:
    from evals.r10_keywords import LABELS as KEY_LABELS
    from evals.r10_keywords import keyword_label

    assert tuple(KEY_LABELS) == tuple(LABELS8)
    assert keyword_label("") == "iki-unknown"
    assert keyword_label("xqzv blorp zzz") == "iki-unknown"
    first = keyword_label("Invented Thursday block")
    assert first in LABELS8
    assert keyword_label("Invented Thursday block") == first


def test_keyword_accent_folding_is_consistent() -> None:
    from evals.r10_keywords import keyword_label

    assert keyword_label("música tranquila") == keyword_label("musica tranquila")


def test_disabled_runner_exits_2_without_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def _forbidden(environ: Any, **kwargs: Any) -> Any:
        raise AssertionError("no client while disabled")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.delenv("IKIGAI_R10_LIVE", raising=False)
    code = r10_module.main(
        ["--model", "synthetic-model", "--out", str(tmp_path / "r.jsonl")]
    )
    assert code == 2
    assert "IKIGAI_R10_LIVE=1" in capsys.readouterr().out
    assert not (tmp_path / "r.jsonl").exists()


def test_default_cases_hash_mismatch_exits_2_without_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _write(_good_payload(), tmp_path)
    monkeypatch.setattr(r10_module, "DEFAULT_CASES_PATH", cases)

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("no client on hash mismatch")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        ["--model", "synthetic-model", "--out", str(tmp_path / "r.jsonl")]
    )
    assert code == 2
    assert not (tmp_path / "r.jsonl").exists()


def test_r10_cases_pin_constant_shape() -> None:
    assert len(R10_CASES_SHA256) == 64
    assert all(ch in "0123456789abcdef" for ch in R10_CASES_SHA256)


def test_r10_cases_match_pin() -> None:
    path = Path("evals/r10_cases.json")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == R10_CASES_SHA256
    loaded = load_r10_cases(path)
    count = len(loaded.cases)
    assert count == 80


def test_mcnemar_hand_computed_values() -> None:
    assert mcnemar_p(0, 0) == 1.0
    assert mcnemar_p(8, 0) == pytest.approx(2 / 256)
    assert mcnemar_p(7, 1) == pytest.approx(18 / 256)
    assert mcnemar_p(5, 5) == 1.0


def test_invalid_answer_wrong_against_gold_unknown() -> None:
    assert is_correct("iki-unknown", False, ("iki-unknown",)) is False
    assert is_strict("iki-unknown", False, "iki-unknown") is False
    assert is_correct("iki-unknown", True, ("iki-unknown",)) is True
    assert is_strict("iki-unknown", True, "iki-unknown") is True


def test_keyword_list_ignores_literal_tokens() -> None:
    from evals.r10_keywords import keyword_label

    assert keyword_label("iki-rest") == "iki-unknown"
    assert keyword_label("IKI-REST") == "iki-unknown"
    assert keyword_label("Lunch iki-care") == "iki-social"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("fisio", "iki-care"),
        ("mama", "iki-family"),
        ("sprint", "iki-meeting"),
        ("hack", "iki-deep"),
        ("tapas", "iki-social"),
        ("senderismo", "iki-rest"),
        ("gestoria", "iki-admin"),
        ("date night", "iki-family"),
    ],
)
def test_keyword_added_words_hit_each_label(title: str, expected: str) -> None:
    from evals.r10_keywords import keyword_label

    assert keyword_label(title) == expected


def _pass_stats() -> R10Stats:
    return R10Stats(
        n=80,
        answered=80,
        model_correct=55,
        keyword_correct=40,
        model_strict=50,
        keyword_strict=38,
        discordant_b=20,
        discordant_c=5,
        discordant_b_strict=18,
        discordant_c_strict=6,
        mcnemar_p=mcnemar_p(20, 5),
        mcnemar_p_strict=mcnemar_p(18, 6),
        committed=60,
        committed_correct=50,
        committed_strict=48,
        care_model_correct=8,
        care_keyword_correct=6,
        care_model_strict=8,
        care_keyword_strict=6,
        model_invalid=1,
    )


def _replace(stats: R10Stats, **kwargs: object) -> R10Stats:
    import dataclasses

    return dataclasses.replace(stats, **kwargs)  # type: ignore[arg-type]


def test_decision_passes_when_all_conditions_hold() -> None:
    decision = r10_decision(_pass_stats())
    assert decision.eligible is True
    assert len(decision.reasons) == 6
    assert all("PASS" in reason for reason in decision.reasons)


def test_decision_fails_each_condition_alone() -> None:
    base = _pass_stats()
    variants = [
        _replace(base, answered=79),
        _replace(base, model_correct=40, keyword_correct=40),
        _replace(base, mcnemar_p=0.4, mcnemar_p_strict=0.4),
        _replace(base, discordant_b=8, discordant_c=0),
        _replace(base, committed_correct=40),
        _replace(base, care_model_correct=5),
        _replace(base, model_invalid=2),
    ]
    for variant in variants:
        decision = r10_decision(variant)
        assert decision.eligible is False, variant
        assert any("FAIL" in reason for reason in decision.reasons)


def test_decision_fails_partial_run_and_zero_commits() -> None:
    assert r10_decision(_replace(_pass_stats(), answered=70)).eligible is False
    zero = _replace(_pass_stats(), committed=0, committed_correct=0, committed_strict=0)
    assert r10_decision(zero).eligible is False


def test_compute_stats_hand_worked_against_stubbed_keywords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Thirteen invented cases; the keyword arm is stubbed by title so the
    # frozen word list cannot matter. Hand-worked per case (model
    # correct/strict, keyword correct/strict):
    #   k1 deep/[deep,meeting]: model meeting (C,.) kw rest (.,.) -> b
    #   k2 family/[family,social]: model social (C,.) kw deep (.,.) -> b
    #   k3 admin/[admin,rest]: model deep (.,.) kw rest (C,.) -> c
    #   k4 care/[care]: model care (C,S) kw social (.,.) -> b,bs,care-m
    #   k5 care/[care]: model meeting (.,.) kw care (C,S) -> c,cs,care-k
    #   k6 meeting/[meeting,deep]: model meeting (C,S) kw deep (C,.) -> bs
    #   k7 rest/[rest,admin]: model rest (C,S) kw admin (C,.) -> bs
    #   k8 social/[social,family]: model family (C,.) kw admin (.,.) -> b
    #   k9 unknown/[unknown]: model unknown valid (C,S) kw meeting (.,.) -> b,bs
    #   k10 unknown/[unknown]: model invalid (.,.) kw unknown (C,S) -> c,cs
    #   k11 deep/[deep]: model deep (C,S) kw deep (C,S) -> neither
    #   k12 care/[care,rest]: model rest (C,.) kw deep (.,.) -> b,care-m
    #   k13 care/[care,rest]: model deep (.,.) kw rest (C,.) -> c,care-k
    # Totals: model C=9 S=5; kw C=7 S=3; b=6 c=4 bs=4 cs=2; committed 11,
    # committed C=8 S=4; care m=2/k=2, care strict m=1/k=1; invalid=1.
    titles = {f"stub-title-{n}": f"Invented stub block {n}" for n in range(1, 14)}
    stub = {
        titles["stub-title-1"]: "iki-rest",
        titles["stub-title-2"]: "iki-deep",
        titles["stub-title-3"]: "iki-rest",
        titles["stub-title-4"]: "iki-social",
        titles["stub-title-5"]: "iki-care",
        titles["stub-title-6"]: "iki-deep",
        titles["stub-title-7"]: "iki-admin",
        titles["stub-title-8"]: "iki-admin",
        titles["stub-title-9"]: "iki-meeting",
        titles["stub-title-10"]: "iki-unknown",
        titles["stub-title-11"]: "iki-deep",
        titles["stub-title-12"]: "iki-deep",
        titles["stub-title-13"]: "iki-rest",
    }
    monkeypatch.setattr(r10_module, "keyword_label", lambda title: stub[title])
    payload = {
        "labels": list(LABELS8),
        "cases": [
            {
                "id": f"k{n}",
                "title": titles[f"stub-title-{n}"],
                "label": label,
                "accepted": list(accepted),
                "class": "stub",
                "lang": "en",
                "note": f"invented stub case {n}",
            }
            for n, (label, accepted) in enumerate(
                [
                    ("iki-deep", ("iki-deep", "iki-meeting")),
                    ("iki-family", ("iki-family", "iki-social")),
                    ("iki-admin", ("iki-admin", "iki-rest")),
                    ("iki-care", ("iki-care",)),
                    ("iki-care", ("iki-care",)),
                    ("iki-meeting", ("iki-meeting", "iki-deep")),
                    ("iki-rest", ("iki-rest", "iki-admin")),
                    ("iki-social", ("iki-social", "iki-family")),
                    ("iki-unknown", ("iki-unknown",)),
                    ("iki-unknown", ("iki-unknown",)),
                    ("iki-deep", ("iki-deep",)),
                    ("iki-care", ("iki-care", "iki-rest")),
                    ("iki-care", ("iki-care", "iki-rest")),
                ],
                start=1,
            )
        ],
    }
    cases = load_r10_cases(_write(payload, tmp_path))
    predictions = [
        ("iki-meeting", True),
        ("iki-social", True),
        ("iki-deep", True),
        ("iki-care", True),
        ("iki-meeting", True),
        ("iki-meeting", True),
        ("iki-rest", True),
        ("iki-family", True),
        ("iki-unknown", True),
        ("iki-deep", False),
        ("iki-deep", True),
        ("iki-rest", True),
        ("iki-deep", True),
    ]
    records = {
        f"k{n}": {"predicted": text, "valid": valid}
        for n, (text, valid) in enumerate(predictions, start=1)
    }
    stats = compute_stats(cases, records)
    assert stats == R10Stats(
        n=13,
        answered=13,
        model_correct=9,
        keyword_correct=7,
        model_strict=5,
        keyword_strict=3,
        discordant_b=6,
        discordant_c=4,
        discordant_b_strict=4,
        discordant_c_strict=2,
        mcnemar_p=mcnemar_p(6, 4),
        mcnemar_p_strict=mcnemar_p(4, 2),
        committed=11,
        committed_correct=8,
        committed_strict=4,
        care_model_correct=2,
        care_keyword_correct=2,
        care_model_strict=1,
        care_keyword_strict=1,
        model_invalid=1,
    )


class _FakeR10Client:
    def __init__(self, texts: list[str], finish: str | None = "stop") -> None:
        self._texts = list(texts)
        self.finish = finish
        self.calls = 0
        self.response_format: object = {"sent": True}

    def complete(self, prompt: str) -> object:
        from framework.glimmer.facts import LLMResponse

        text = self._texts[self.calls]
        self.calls += 1
        return LLMResponse(
            text=text,
            model_id="fake-model",
            latency_ms=3,
            finish_reason=self.finish,
            completion_tokens=5,
        )


def _run_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    texts: list[str],
    extra: list[str] | None = None,
) -> tuple[int, Path, int]:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "run.jsonl"
    client = _FakeR10Client(texts)
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    args = [
        "--model",
        "synthetic-model",
        "--cases",
        str(cases),
        "--out",
        str(out),
    ] + (extra or [])
    code = r10_module.main(args)
    return code, out, client.calls


def test_live_run_writes_resumable_file_and_report_has_no_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', "prose, not a label", '{"label": "iki-rest"}'],
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    header = json.loads(lines[0])
    assert header["model"] == "synthetic-model"
    assert "raw_answer" not in json.loads(lines[1])
    assert "raw_answer" in json.loads(lines[2])
    report = capsys.readouterr().out
    assert "custom cases, not the frozen set" in report
    assert "no decision" in report
    for forbidden in (
        "Morning solo build block",
        "Llamada semanal",
        "Quiet evening with a record",
        "invented case",
        "r10-t1",
        "r10-t2",
        "r10-t3",
    ):
        assert forbidden not in report, forbidden


def test_resume_skips_stored_ids_without_new_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    before = out.read_text(encoding="utf-8")

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("stored answers are never asked again")

    cases = tmp_path / "cases.json"
    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    again = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
        ]
    )
    assert again == 0
    assert out.read_text(encoding="utf-8") == before


def test_differing_header_exits_2_without_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    other = _write(_good_payload(), tmp_path, name="other.json")
    other.write_text(
        other.read_text(encoding="utf-8").replace("r10-t1", "r10-x1"),
        encoding="utf-8",
    )

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("no call on header mismatch")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(other), "--out", str(out)]
    )
    assert code == 2


def test_torn_final_line_is_reasked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    lines[-1] = '{"id": "r10-t3", "brok'
    out.write_text("\n".join(lines), encoding="utf-8")
    client = _FakeR10Client(['{"label": "iki-rest"}'])
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert client.calls == 1
    assert len(out.read_text(encoding="utf-8").splitlines()) == 4


def test_torn_earlier_line_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    lines[1] = '{"id": "r10-t1", "brok'
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("no call on a torn earlier line")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 2


def test_report_only_and_comparison_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
        extra=["--role", "comparison"],
    )
    assert code == 0
    report = capsys.readouterr().out
    assert "COMPARISON, not the product" in report
    cases = tmp_path / "cases.json"
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--role",
            "comparison",
            "--report-only",
        ]
    )
    assert code == 0
    again = capsys.readouterr().out
    assert "COMPARISON, not the product" in again
    assert "Llamada semanal de proyecto" not in again


def test_length_finish_records_invalid_unknown_with_raw_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "length.jsonl"
    client = _FakeR10Client(
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
        finish="length",
    )
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    for line in lines[1:]:
        record = json.loads(line)
        assert record["predicted"] == "iki-unknown"
        assert record["valid"] is False
        assert record["finish_reason"] == "length"
        assert "raw_answer" in record


def test_refused_endpoint_exits_2_with_no_file_and_no_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "refused.jsonl"
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://8.8.8.8/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "synthetic-model")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "synthetic-key")
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 2
    assert not out.exists()
    captured = capsys.readouterr()
    assert captured.err.strip() == "r10: refused endpoint"
    assert "8.8.8.8" not in captured.out
    assert "8.8.8.8" not in captured.err


def test_missing_base_url_exits_before_any_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "missing.jsonl"
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LOCAL_LLM_MODEL", "synthetic-model")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "synthetic-key")
    with pytest.raises(SystemExit) as excinfo:
        r10_module.main(
            ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
        )
    assert "LOCAL_LLM_BASE_URL" in str(excinfo.value)
    assert not out.exists()


def test_parseable_torn_last_line_is_reasked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    data = out.read_bytes()
    assert data.endswith(b"\n")
    out.write_bytes(data[:-1])
    client = _FakeR10Client(['{"label": "iki-rest"}'])
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert client.calls == 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert out.read_bytes().endswith(b"\n")
    for line in lines:
        json.loads(line)


def test_report_only_ignores_torn_last_line_without_touching_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    data = out.read_bytes()
    out.write_bytes(data[:-1])
    before = out.read_bytes()

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("report-only builds no client")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.delenv("IKIGAI_R10_LIVE", raising=False)
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--report-only",
        ]
    )
    assert code == 0
    assert out.read_bytes() == before
    report = capsys.readouterr().out
    assert "1 complete 2/3: FAIL" in report
    assert "model correct: 2/3" in report
    assert "no decision" in report


def test_corrupt_newline_terminated_last_line_is_reasked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    out.write_bytes(("\n".join(lines[:-1]) + "\nNOT-JSON-AT-ALL\n").encode("utf-8"))
    client = _FakeR10Client(['{"label": "iki-rest"}'])
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert client.calls == 1
    final = out.read_text(encoding="utf-8").splitlines()
    assert len(final) == 4
    for line in final:
        json.loads(line)


def test_report_only_ignores_corrupt_last_line_without_touching_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    out.write_bytes(("\n".join(lines[:-1]) + "\nNOT-JSON-AT-ALL\n").encode("utf-8"))
    before = out.read_bytes()

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("report-only builds no client")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.delenv("IKIGAI_R10_LIVE", raising=False)
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--report-only",
        ]
    )
    assert code == 0
    assert out.read_bytes() == before
    assert "1 complete 2/3: FAIL" in capsys.readouterr().out


def test_report_only_over_header_without_newline_leaves_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    header_line = out.read_text(encoding="utf-8").splitlines()[0]
    out.write_bytes(header_line.encode("utf-8"))
    before = out.read_bytes()

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("report-only builds no client")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.delenv("IKIGAI_R10_LIVE", raising=False)
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--report-only",
        ]
    )
    assert code == 0
    assert out.read_bytes() == before


def test_header_without_newline_is_kept_and_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0
    header_line = out.read_text(encoding="utf-8").splitlines()[0]
    out.write_bytes(header_line.encode("utf-8"))
    client = _FakeR10Client(
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}']
    )
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert client.calls == 3
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert json.loads(lines[0])["type"] == "header"


def test_unavailable_second_call_exits_3_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from framework.glimmer.facts import LLMResponse, LLMUnavailableError

    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "unavail.jsonl"

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str) -> LLMResponse:
            self.calls += 1
            if self.calls == 2:
                raise LLMUnavailableError("synthetic down")
            return LLMResponse(
                text='{"label": "iki-deep"}',
                model_id="fake-model",
                latency_ms=3,
                finish_reason="stop",
                completion_tokens=5,
            )

    flaky = _Flaky()
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: flaky)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    args = ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    assert r10_module.main(args) == 3
    assert (
        "r10: model unavailable (synthetic down), stopped, rerun resumes"
        in capsys.readouterr().err
    )
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2
    good = _FakeR10Client(['{"label": "iki-meeting"}', '{"label": "iki-rest"}'])
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: good)
    assert r10_module.main(args) == 0
    assert good.calls == 2
    assert len(out.read_text(encoding="utf-8").splitlines()) == 4


def test_report_only_needs_no_live_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out, _ = _run_live(
        tmp_path,
        monkeypatch,
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}'],
    )
    assert code == 0

    def _forbidden(environ: object, **kwargs: object) -> object:
        raise AssertionError("report-only builds no client")

    monkeypatch.setattr(r10_module, "build_label_client", _forbidden)
    monkeypatch.delenv("IKIGAI_R10_LIVE", raising=False)
    cases = tmp_path / "cases.json"
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--report-only",
        ]
    )
    assert code == 0
    assert "model correct" in capsys.readouterr().out


def test_render_report_roles_and_partial(tmp_path: Path) -> None:
    cases = load_r10_cases(_write(_good_payload(), tmp_path))
    full = {case.id: {"predicted": "iki-deep", "valid": True} for case in cases.cases}
    kwargs: dict[str, Any] = {
        "model": "synthetic-model",
        "cases": cases,
        "cases_sha": "1" * 64,
        "keywords_sha": "0" * 64,
        "response_format": True,
        "frozen": True,
    }
    comparison = render_report(role="comparison", records=full, **kwargs)  # type: ignore[arg-type]
    assert "no decision: comparison role" in comparison
    assert not any(line.startswith("decision: ") for line in comparison.splitlines())
    partial = {key: full[key] for key in list(full)[:2]}
    partial_report = render_report(role="product", records=partial, **kwargs)  # type: ignore[arg-type]
    assert "no decision: partial file (2/3 answered)" in partial_report
    assert not any(
        line.startswith("decision: ") for line in partial_report.splitlines()
    )
    complete = render_report(role="product", records=full, **kwargs)  # type: ignore[arg-type]
    expected = r10_decision(compute_stats(cases, full)).eligible
    assert f"decision: {'eligible' if expected else 'not eligible'}" in complete


def test_report_invalid_answer_lands_in_invalid_column(tmp_path: Path) -> None:
    payload = {
        "labels": list(LABELS8),
        "cases": [
            {
                "id": "v1",
                "title": "Invented morning block one",
                "label": "iki-deep",
                "accepted": ["iki-deep"],
                "class": "stub",
                "lang": "en",
                "note": "invented invalid case one",
            },
            {
                "id": "v2",
                "title": "Invented morning block two",
                "label": "iki-deep",
                "accepted": ["iki-deep"],
                "class": "stub",
                "lang": "en",
                "note": "invented invalid case two",
            },
        ],
    }
    cases = load_r10_cases(_write(payload, tmp_path))
    records = {
        "v1": {"predicted": "iki-unknown", "valid": False},
        "v2": {"predicted": "iki-unknown", "valid": True},
    }
    report = render_report(
        role="product",
        model="synthetic-model",
        cases=cases,
        records=records,
        cases_sha="1" * 64,
        keywords_sha="0" * 64,
        response_format=True,
        frozen=False,
    )
    assert "  iki-deep 0 0 0 0 0 0 0 1 1" in report.splitlines()


def test_report_frozen_stamp_names_custom_cases(tmp_path: Path) -> None:
    cases = load_r10_cases(_write(_good_payload(), tmp_path))
    records = {
        case.id: {"predicted": "iki-deep", "valid": True} for case in cases.cases
    }
    kwargs: dict[str, Any] = {
        "model": "synthetic-model",
        "cases": cases,
        "cases_sha": "1" * 64,
        "keywords_sha": "0" * 64,
        "response_format": True,
    }
    custom = render_report(role="product", records=records, frozen=False, **kwargs)  # type: ignore[arg-type]
    assert "frozen cases: no, custom cases, not the frozen set" in custom.splitlines()
    frozen = render_report(role="product", records=records, frozen=True, **kwargs)  # type: ignore[arg-type]
    assert "frozen cases: yes" in frozen.splitlines()


def test_report_p90_nearest_rank(tmp_path: Path) -> None:
    payload = {
        "labels": list(LABELS8),
        "cases": [
            {
                "id": f"p{n}",
                "title": f"Invented timing block {n}",
                "label": "iki-deep",
                "accepted": ["iki-deep"],
                "class": "stub",
                "lang": "en",
                "note": f"invented timing case {n}",
            }
            for n in range(1, 11)
        ],
    }
    cases = load_r10_cases(_write(payload, tmp_path))
    records = {
        f"p{n}": {"predicted": "iki-deep", "valid": True, "seconds": float(n)}
        for n in range(1, 11)
    }
    report = render_report(
        role="product",
        model="synthetic-model",
        cases=cases,
        records=records,
        cases_sha="1" * 64,
        keywords_sha="0" * 64,
        response_format=True,
        frozen=False,
    )
    assert "p90 9.00" in report


def test_no_response_format_flag_stamps_header_and_clears_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "nrf.jsonl"
    client = _FakeR10Client(
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}']
    )
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        [
            "--model",
            "synthetic-model",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--no-response-format",
        ]
    )
    assert code == 0
    assert client.response_format is None
    header = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert header["response_format"] is False


def test_default_keeps_response_format_on_client_and_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "rf.jsonl"
    client = _FakeR10Client(
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}']
    )
    monkeypatch.setattr(r10_module, "build_label_client", lambda environ, **kw: client)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert client.response_format == {"sent": True}
    header = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert header["response_format"] is True


def test_runner_passes_model_timeout_to_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from framework.glimmer.llm import MODEL_TIMEOUT_S

    cases = _write(_good_payload(), tmp_path)
    out = tmp_path / "timeout.jsonl"
    client = _FakeR10Client(
        ['{"label": "iki-deep"}', '{"label": "iki-meeting"}', '{"label": "iki-rest"}']
    )
    seen: dict[str, Any] = {}

    def _spy(environ: object, **kwargs: object) -> object:
        seen.update(kwargs)
        return client

    monkeypatch.setattr(r10_module, "build_label_client", _spy)
    monkeypatch.setenv("IKIGAI_R10_LIVE", "1")
    code = r10_module.main(
        ["--model", "synthetic-model", "--cases", str(cases), "--out", str(out)]
    )
    assert code == 0
    assert seen["timeout_s"] == MODEL_TIMEOUT_S


def test_decision_equal_counts_fail_each_scoring() -> None:
    base = _pass_stats()
    assert r10_decision(_replace(base, model_correct=40)).eligible is False
    assert r10_decision(_replace(base, model_strict=38)).eligible is False


def test_decision_mcnemar_boundary() -> None:
    base = _pass_stats()
    assert r10_decision(_replace(base, mcnemar_p=0.05)).eligible is False
    assert r10_decision(_replace(base, mcnemar_p_strict=0.05)).eligible is False
    assert r10_decision(_replace(base, mcnemar_p=0.049)).eligible is True
    assert r10_decision(_replace(base, mcnemar_p_strict=0.049)).eligible is True


def test_decision_discordant_pair_boundaries() -> None:
    base = _pass_stats()
    assert r10_decision(_replace(base, discordant_b=4)).eligible is False
    assert r10_decision(_replace(base, discordant_b_strict=3)).eligible is False
    assert r10_decision(_replace(base, discordant_b=5)).eligible is True
    assert r10_decision(_replace(base, discordant_b_strict=4)).eligible is True


def test_decision_commit_accuracy_boundaries() -> None:
    base = _pass_stats()
    assert r10_decision(_replace(base, committed_correct=47)).eligible is False
    assert r10_decision(_replace(base, committed_strict=47)).eligible is False
    both = _replace(base, committed_correct=48, committed_strict=48)
    assert r10_decision(both).eligible is True


def test_decision_care_boundaries() -> None:
    base = _pass_stats()
    assert r10_decision(_replace(base, care_model_correct=5)).eligible is False
    assert r10_decision(_replace(base, care_model_strict=5)).eligible is False
    tied = _replace(base, care_model_correct=6, care_model_strict=6)
    assert r10_decision(tied).eligible is True


def test_decision_invalid_boundaries() -> None:
    base = _pass_stats()
    assert r10_decision(base).eligible is True
    assert r10_decision(_replace(base, model_invalid=2)).eligible is False
