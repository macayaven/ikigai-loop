"""Slice A, AD9: score returned result files against their keys."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from framework.rater.pack import collect, copy_store, remove_copy

LABELS = ("supported", "not_supported", "cant_tell")


def _refusal(reason: str) -> tuple[int, list[str]]:
    return 1, [f"ok=0 reason={reason}"]


def score_pairs(
    pairs: list[tuple[Path, Path]],
    *,
    db: Path | None,
) -> tuple[int, list[str]]:
    """Validate and tally every pair, then the combined block."""
    loaded: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    seen_sources: set[tuple[str, str]] = set()
    for index, (key_path, result_path) in enumerate(pairs):
        name = f"pair={index}"
        try:
            raw_key: Any = json.loads(key_path.read_text(encoding="utf-8"))
            raw_result: Any = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _refusal("unreadable_pair_file")
        if not isinstance(raw_key, dict) or not isinstance(raw_result, dict):
            return _refusal("unreadable_pair_file")
        key = cast("dict[str, Any]", raw_key)
        result = cast("dict[str, Any]", raw_result)
        if result.get("pack_id") != key.get("pack_id"):
            return _refusal("pack_id_mismatch")
        if result.get("pack_hash") != key.get("pack_hash"):
            return _refusal("pack_hash_mismatch")
        if not isinstance(key.get("items"), dict) or not isinstance(
            result.get("answers"), list
        ):
            return _refusal("unreadable_pair_file")
        items = cast("dict[str, Any]", key.get("items"))
        answers = cast("list[Any]", result.get("answers"))
        seen: set[str] = set()
        tallies: dict[str, str] = {}
        for raw_answer in answers:
            if not isinstance(raw_answer, dict):
                return _refusal("bad_label")
            answer = cast("dict[str, Any]", raw_answer)
            item_id = answer.get("item_id")
            label = answer.get("label")
            if item_id not in items:
                return _refusal("unknown_item")
            if item_id in seen:
                return _refusal("repeated_item")
            if label not in LABELS:
                return _refusal("bad_label")
            seen.add(str(item_id))
            tallies[str(item_id)] = str(label)
        for item_id, raw_item in items.items():
            if not isinstance(raw_item, dict):
                return _refusal("unreadable_pair_file")
            item = cast("dict[str, Any]", raw_item)
            source = (str(item.get("proposal_key")), str(item.get("claim_id")))
            if source in seen_sources:
                return _refusal("keys_overlap")
            seen_sources.add(source)
        loaded.append((key, result, name))
    lines: list[str] = []
    combined = {
        "claims": 0,
        "rated": 0,
        "supported": 0,
        "not_supported": 0,
        "cant_tell": 0,
        "unanswered": 0,
    }
    for key, result, name in loaded:
        items = cast("dict[str, Any]", key["items"])
        answers = cast("list[Any]", result["answers"])
        tallies = {str(a["item_id"]): str(a["label"]) for a in answers}
        total = len(items)
        supported = sum(1 for label in tallies.values() if label == "supported")
        not_supported = sum(1 for label in tallies.values() if label == "not_supported")
        cant_tell = sum(1 for label in tallies.values() if label == "cant_tell")
        unanswered = total - len(tallies)
        rated = len(tallies)
        rate = supported / total if total else 0.0
        lines.append(f"{name} claims_in_pack={total}")
        lines.append(f"{name} rated={rated}")
        lines.append(f"{name} supported={supported}")
        lines.append(f"{name} not_supported={not_supported}")
        lines.append(f"{name} cant_tell={cant_tell}")
        lines.append(f"{name} unanswered={unanswered}")
        lines.append(f"{name} support_rate={rate:.4f} n={total}")
        groups: dict[tuple[str, str], list[str]] = {}
        for item_id, raw_item in items.items():
            item = cast("dict[str, Any]", raw_item)
            groups.setdefault(
                (str(item.get("model")), str(item.get("effort"))), []
            ).append(str(item_id))
        for (model, effort), members in sorted(groups.items()):
            kept = sum(1 for member in members if tallies.get(member) == "supported")
            group_rate = kept / len(members) if members else 0.0
            lines.append(
                f"{name} rate model={model} effort={effort}"
                f" supported={kept} n={len(members)} rate={group_rate:.4f}"
            )
        for field, value in (
            ("claims", total),
            ("rated", rated),
            ("supported", supported),
            ("not_supported", not_supported),
            ("cant_tell", cant_tell),
            ("unanswered", unanswered),
        ):
            combined[field] += value
    total = combined["claims"]
    combined_rate = combined["supported"] / total if total else 0.0
    lines.append(f"combined claims_in_pack={total}")
    lines.append(f"combined rated={combined['rated']}")
    lines.append(f"combined supported={combined['supported']}")
    lines.append(f"combined not_supported={combined['not_supported']}")
    lines.append(f"combined cant_tell={combined['cant_tell']}")
    lines.append(f"combined unanswered={combined['unanswered']}")
    lines.append(f"combined support_rate={combined_rate:.4f} n={total}")
    if db is not None:
        if not db.exists() or not db.is_file():
            return 2, ["ok=0 reason=missing_db_file"]
        copy, garbage = copy_store(db)
        try:
            excluded: set[tuple[str, str]] = set()
            for key, _, _ in loaded:
                items = cast("dict[str, Any]", key["items"])
                for raw_item in items.values():
                    item = cast("dict[str, Any]", raw_item)
                    excluded.add(
                        (str(item.get("proposal_key")), str(item.get("claim_id")))
                    )
            rerun = collect(copy_db=copy, cut=None, exclude=frozenset(excluded))
        finally:
            remove_copy(garbage)
        lines.append(f"unlabelled_atomic_claims={rerun.counts['claims_atomic_total']}")
    return 0, lines


def parse_cut(raw: str | None) -> datetime | None:
    """Parse an ISO cut instant; naive stamps are refused by the caller."""
    if raw is None:
        return None
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("naive cut")
    return moment
