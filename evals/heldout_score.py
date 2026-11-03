"""Offline scorer for the held-out checker set v1.

Reads ``evals/heldout/checker-heldout-v1.json`` (refusing to run unless its
sha256 matches the frozen hash), feeds each case's input to the public
``verify-claims`` checker exactly as written in the file, and reports the
five counts registered in ``evals/heldout/README.md``.

Offline: no network, no model. Each case goes once through the checker run
under the current Python (``python -m framework.verify --json -``); exit 0
counts as PASS, exit 1 as FAIL, anything else as no verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FROZEN_SHA256 = "937789f47824e6a073e72a73f027eadf95e24787acb1a77bc97c269513bc2610"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO_ROOT / "evals" / "heldout" / "checker-heldout-v1.json"

BUCKETS = ("true_pass", "true_fail", "false_pass", "false_fail", "no_verdict")


def sha256_hex(data: bytes) -> str:
    """Return the hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def checked_data(data_path: Path) -> tuple[bytes, str]:
    """Read ``data_path`` and refuse unless it matches the frozen hash."""
    data = data_path.read_bytes()
    digest = sha256_hex(data)
    if digest != FROZEN_SHA256:
        raise ValueError(
            f"refusing to score {data_path}: sha256 {digest} "
            f"does not match the frozen {FROZEN_SHA256}"
        )
    return data, digest


def _skip_string(raw: str, pos: int) -> int:
    """Return the index just past the JSON string starting at ``pos``."""
    pos += 1
    end = len(raw)
    while pos < end:
        char = raw[pos]
        if char == "\\":
            pos += 2
            continue
        if char == '"':
            return pos + 1
        pos += 1
    raise ValueError("unterminated string in held-out data")


def _extract_value(raw: str, pos: int) -> tuple[str, int]:
    """Return the raw text and end index of the JSON value at ``pos``."""
    while pos < len(raw) and raw[pos] in " \t\n\r":
        pos += 1
    start = pos
    first = raw[pos]
    if first == '"':
        return raw[start : _skip_string(raw, pos)], _skip_string(raw, pos)
    if first in "{[":
        depth = 0
        while pos < len(raw):
            char = raw[pos]
            if char == '"':
                pos = _skip_string(raw, pos)
                continue
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    return raw[start : pos + 1], pos + 1
            pos += 1
        raise ValueError("unterminated container in held-out data")
    while pos < len(raw) and raw[pos] not in ",]}":
        pos += 1
    return raw[start:pos].strip(), pos


def extract_input_texts(raw: str, count: int) -> list[str]:
    """Return the raw text of each case's ``input`` object, in file order.

    The text is the object's characters as they stand in the file, not a
    re-serialisation. Only keys named ``input`` one level inside the top
    array (each case object) are taken.
    """
    texts: list[str] = []
    pos = 0
    end = len(raw)
    depth = 0
    while pos < end:
        char = raw[pos]
        if char == '"':
            token_end = _skip_string(raw, pos)
            token = json.loads(raw[pos:token_end])
            look = token_end
            while look < end and raw[look] in " \t\n\r":
                look += 1
            if depth == 2 and token == "input" and look < end and raw[look] == ":":
                value, value_end = _extract_value(raw, look + 1)
                texts.append(value)
                pos = value_end
                continue
            pos = token_end
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        pos += 1
    if len(texts) != count:
        raise ValueError(f"found {len(texts)} case inputs, expected {count}")
    return texts


def verdict_for_exit(exit_code: int) -> str | None:
    """Map a checker exit code to PASS, FAIL, or None for no verdict."""
    if exit_code == 0:
        return "PASS"
    if exit_code == 1:
        return "FAIL"
    return None


def bucket_for(expected: str, exit_code: int) -> str:
    """Put a case in one of the five registered buckets."""
    verdict = verdict_for_exit(exit_code)
    if verdict is None:
        return "no_verdict"
    if expected == "PASS" and verdict == "PASS":
        return "true_pass"
    if expected == "FAIL" and verdict == "FAIL":
        return "true_fail"
    if expected == "FAIL" and verdict == "PASS":
        return "false_pass"
    return "false_fail"


def run_case(raw_input: str) -> tuple[int, list[str], list[dict[str, str]]]:
    """Run one raw input through the public checker; return exit, codes, skipped."""
    proc = subprocess.run(
        [sys.executable, "-m", "framework.verify", "--json", "-"],
        check=False,
        input=raw_input.encode("utf-8"),
        capture_output=True,
        timeout=120,
        cwd=REPO_ROOT,
    )
    codes: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        payload = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return proc.returncode, codes, skipped
    if not isinstance(payload, dict):
        return proc.returncode, codes, skipped
    violations = payload.get("violations", [])
    if isinstance(violations, list):
        codes = [
            str(item.get("code", "")) for item in violations if isinstance(item, dict)
        ]
    coverage = payload.get("coverage", [])
    if isinstance(coverage, list):
        for entry in coverage:
            if not isinstance(entry, dict):
                continue
            claim_id = str(entry.get("claim_id", ""))
            entries = entry.get("skipped", [])
            if not isinstance(entries, list):
                continue
            for skip in entries:
                if not isinstance(skip, dict):
                    continue
                skipped.append(
                    {
                        "claim_id": claim_id,
                        "check": str(skip.get("check", "")),
                        "reason": str(skip.get("reason", "")),
                    }
                )
    return proc.returncode, codes, skipped


def checked_commit() -> str:
    """Return the current commit, naming the scored tree."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def score_all(data: bytes) -> tuple[list[dict[str, object]], list[str]]:
    """Run every case in file order; return result rows and raw input texts."""
    cases = json.loads(data.decode("utf-8"))
    if not isinstance(cases, list):
        raise TypeError("held-out data is not a JSON array")
    texts = extract_input_texts(data.decode("utf-8"), len(cases))
    rows: list[dict[str, object]] = []
    for case, text in zip(cases, texts, strict=True):
        if json.loads(text) != case["input"]:
            raise ValueError(
                f"raw input text does not parse to the input of {case['id']}"
            )
        exit_code, codes, skipped = run_case(text)
        rows.append(
            {
                "id": str(case["id"]),
                "expected": str(case["expected"]),
                "kind": str(case["kind"]),
                "domain": str(case["domain"]),
                "why": str(case["why"]),
                "exit_code": exit_code,
                "verdict": verdict_for_exit(exit_code) or "no verdict",
                "bucket": bucket_for(str(case["expected"]), exit_code),
                "codes": codes,
                "skipped": skipped,
            }
        )
    return rows, texts


def report_lines(rows: list[dict[str, object]]) -> list[str]:
    """Format the counts, counts by kind, and every miss for printing."""
    counts = {bucket: 0 for bucket in BUCKETS}
    for row in rows:
        counts[str(row["bucket"])] += 1
    correct = counts["true_pass"] + counts["true_fail"]
    lines = [
        f"true pass {counts['true_pass']}",
        f"true fail {counts['true_fail']}",
        f"false pass {counts['false_pass']}",
        f"false fail {counts['false_fail']}",
        f"no verdict {counts['no_verdict']}",
        f"{correct} of {len(rows)} correct",
        "by kind:",
    ]
    kinds: list[str] = []
    for row in rows:
        if str(row["kind"]) not in kinds:
            kinds.append(str(row["kind"]))
    for kind in kinds:
        kind_rows = [row for row in rows if row["kind"] == kind]
        kind_ok = sum(1 for row in kind_rows if str(row["bucket"]).startswith("true_"))
        lines.append(f"  {kind} {kind_ok} of {len(kind_rows)} correct")
    lines.append("misses:")
    for row in rows:
        if str(row["bucket"]) in ("false_pass", "false_fail", "no_verdict"):
            skipped = "; ".join(
                f"{skip['claim_id']}:{skip['check']}"
                for skip in row["skipped"]  # type: ignore[union-attr]
            )
            lines.append(
                f"  {row['id']} kind={row['kind']} expected={row['expected']} "
                f"verdict={row['verdict']} codes={list(row['codes'])} "  # type: ignore[arg-type]
                f"skipped=[{skipped}] why={row['why']}"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Score the frozen set; with --output also write the JSON results file."""
    parser = argparse.ArgumentParser(description="Score the held-out checker set v1.")
    parser.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    try:
        data, digest = checked_data(Path(args.data))
        rows, _ = score_all(data)
    except (ValueError, TypeError) as exc:
        print(f"heldout_score: {exc}", file=sys.stderr)
        return 1
    for line in report_lines(rows):
        print(line)
    if args.output is not None:
        counts = {
            bucket: sum(1 for row in rows if row["bucket"] == bucket)
            for bucket in BUCKETS
        }
        doc = {
            "commit": checked_commit(),
            "data_sha256": digest,
            "counts": counts,
            "cases": [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "expected",
                        "kind",
                        "domain",
                        "exit_code",
                        "verdict",
                        "bucket",
                        "codes",
                        "skipped",
                    )
                }
                for row in rows
            ],
        }
        Path(args.output).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
