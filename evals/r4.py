"""Ticket 15b: the R4 evidence-sensitivity runner (D40, D41, D45).

Each case regenerates its cited arm and its matched-control arm once,
first attempt only, with Ticket 11's real prompt and response schema --
the request ``propose`` would send first. No model call happens without
``IKIGAI_R4_LIVE=1``. ``--summary`` is pure and offline.

R4 is a sensitivity test everywhere here, never proof of faithfulness.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from evals import gate_identity as identity
from evals.live_guard import (
    Refusal,
    add_shared_args,
    live_disabled,
    parse_stop_time,
    quiet_windows,
    start_blocked,
)
from evals.r3 import (
    RowsUnreadable,
    SlotMaterials,
    build_slot_materials,
    default_client_factory,
    load_pairs,
    load_rows_file,
    results_filename,
)
from evals.r3 import _remaining_slots as _r3_remaining_slots
from evals.r4_scenario import (
    Case,
    base_scenario,
    build_cases,
    case_build_report,
    changed_scenario,
)
from evals.r4_score import (
    noise_floor,
    render_no_runs,
    render_r4,
    render_r4_history_section,
    score_rows,
)
from framework.cycle.orchestrator import slot_profiles, validate_slot
from framework.proposal.core import (
    MetaUnavailableError,
    OutboundBlocked,
    WonderClient,
    WonderRequest,
)
from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
from framework.proposal.muse_client import rules_file_path
from framework.proposal.prompt import build_prompt, offered_metrics
from framework.proposal.schemas import (
    UnparseableDraft,
    build_response_schema,
    parse_draft,
)

LIVE_VAR = "IKIGAI_R4_LIVE"
SUBJECT_ID = "subject-1"

DEFAULT_RESULTS_DIR = _REPOS_ROOT / "evals" / "results" / "r4"
DEFAULT_R3_DIR = _REPOS_ROOT / "evals" / "results" / "r3"
DOC_PATH = _REPOS_ROOT / "docs" / "r4.md"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_UNAVAILABLE_STOP = 3
EXIT_STOPPED = 4

ARMS = ("cited", "control")


def utc_now() -> datetime:
    """The default live-run clock: the current UTC instant."""
    return datetime.now(UTC)


def arm_scenario(doc: dict[str, Any], case: Case, arm: str) -> dict[str, Any]:
    """The case's base scenario with one arm's fact changed, ids untouched."""
    if arm == "cited":
        return changed_scenario(base_scenario(doc), case.cited_fact)
    if arm == "control":
        return changed_scenario(base_scenario(doc), case.control_fact)
    raise Refusal("unknown arm")


def first_attempt_request(
    materials: SlotMaterials, profile: str, model: str, effort: str
) -> WonderRequest:
    """The request ``propose`` would send first for the same scenario.

    Built from the same public builders ``propose`` calls, with the same
    arguments: the scenario's facts in order, no deltas, no parent, an
    empty policy block, and the D26 literals. A test pins it
    byte/JSON-equal to a captured ``propose`` request.
    """
    context = materials.context
    metrics_map = offered_metrics(dict(context.metrics.values))
    prompt = build_prompt(
        profile_id=profile,
        profile_name=profile.capitalize(),
        facts=list(context.facts.values()),
        metrics=metrics_map,
        deltas=(),
        commitments=list(materials.eligible),
        hour=materials.hour,
        policy="",
    )
    schema = build_response_schema(
        commitment_ids=[commitment.id for commitment in materials.eligible],
        fact_ids=list(context.facts),
        snapshot_metric_ids=list(metrics_map),
        delta_metric_ids=[],
        has_facts=True,
        has_metrics=True,
        has_parent=False,
    )
    return WonderRequest(
        prompt=prompt,
        model=model,
        effort=effort,
        response_schema=schema,
        forbidden_raw_literals=context.forbidden_raw_literals,
    )


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def run_arm(
    *,
    case: Case,
    arm: str,
    scenario: dict[str, Any],
    execution: int,
    start_seq: int,
    model: str,
    effort: str,
    client: WonderClient,
    static: dict[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    """One arm-slot: a single first-attempt regeneration, one row."""
    materials = build_slot_materials(scenario, case.profile)
    request = first_attempt_request(materials, case.profile, model, effort)
    prompt_hash = _prompt_hash(request.prompt)
    if arm == "cited":
        changed_fact = case.cited_fact
    elif arm == "control":
        changed_fact = case.control_fact
    else:
        raise Refusal("unknown arm")
    try:
        response = client.complete(request)
    except OutboundBlocked as exc:
        attempt = {
            "number": 1,
            "model_requested": model,
            "model_reported": "unreported",
            "effort": effort,
            "parsed_ok": False,
            "blocked": True,
            "codes": [[code, "prompt"] for code in exc.codes],
            "latency_ms": 0,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "cached_tokens": None,
            "finish_reason": None,
            "prompt_hash": prompt_hash,
            "raw_text": "",
        }
        drawn = True
        unavailable_reason: str | None = None
        reported = "unreported"
    except MetaUnavailableError as exc:
        attempt = {
            "number": 1,
            "model_requested": model,
            "model_reported": "unreported",
            "effort": effort,
            "parsed_ok": False,
            "blocked": False,
            "codes": [["MODEL_UNAVAILABLE", str(exc) or "unknown"]],
            "latency_ms": exc.latency_ms,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "cached_tokens": None,
            "finish_reason": None,
            "prompt_hash": prompt_hash,
            "raw_text": "",
        }
        drawn = False
        unavailable_reason = str(exc) or "unknown"
        reported = "unreported"
    else:
        parsed_ok = not isinstance(
            parse_draft(
                response.text, has_facts=True, has_metrics=True, has_parent=False
            ),
            UnparseableDraft,
        )
        attempt = {
            "number": 1,
            "model_requested": model,
            "model_reported": response.model_reported,
            "effort": effort,
            "parsed_ok": parsed_ok,
            "blocked": False,
            "codes": [],
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "cached_tokens": response.cached_tokens,
            "finish_reason": response.finish_reason,
            "prompt_hash": prompt_hash,
            "raw_text": response.text,
        }
        drawn = True
        unavailable_reason = None
        reported = response.model_reported
    failures = getattr(client, "failures", None)
    if failures is None:
        failures = getattr(getattr(client, "_inner", None), "failures", ())
    local_retries = [
        {
            "attempt": failure.attempt,
            "reason": failure.reason,
            "latency_ms": failure.latency_ms,
            "exit_code": failure.exit_code,
            "stderr_masked": failure.stderr_masked,
        }
        for failure in failures
    ]
    timeout_retries = int(getattr(client, "retries", 0) or 0)
    latency = attempt["latency_ms"] or 0
    return {
        "schema": 1,
        "case_id": case.case_id,
        "arm": arm,
        "changed_fact": changed_fact,
        "profile": case.profile,
        "pair_id": case.pair_id,
        "repeat": case.repeat,
        "base_prompt_hash": case.base_prompt_hash,
        "base_draft_json": case.base_draft_json,
        "execution": execution,
        "start_seq": start_seq,
        "drawn": drawn,
        "unavailable_reason": unavailable_reason,
        "prompt_hash": prompt_hash,
        "latency_ms": latency,
        "prompt_tokens": attempt["prompt_tokens"] or 0,
        "completion_tokens": attempt["completion_tokens"] or 0,
        "model_reported": reported,
        "local_retries": local_retries,
        "timeout_retries": timeout_retries,
        "attempts": [attempt],
        "transport": client.transport,
        "muse_version": client.transport_version,
        "harness_rules_file": client.harness_rules_file,
        "recorded_at": recorded_at,
        **static,
    }


def _three_unavailable_in_a_row(order: list[int], outcomes: dict[int, bool]) -> bool:
    """Any three consecutive started slots, in start order, all unavailable."""
    for pos in range(len(order) - 2):
        if all(outcomes.get(seq) is True for seq in order[pos : pos + 3]):
            return True
    return False


def _remaining_slots(cases: tuple[Case, ...], rows: list[dict[str, Any]]) -> int:
    """Count planned arm-slots neither drawn nor exhausted, from the rows."""
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row["arm"]))
        by_slot.setdefault(key, []).append(row)
    remaining = 0
    for case in cases:
        for arm in ARMS:
            slot_rows = by_slot.get((case.case_id, arm), [])
            if any(bool(row.get("drawn", False)) for row in slot_rows):
                continue
            if len(slot_rows) >= 3:
                continue
            remaining += 1
    return remaining


def _expected_r3_path(
    model: str,
    effort: str,
    gate_hash: str,
    prompt_sha: str,
    closure_sha: str | None = None,
) -> Path:
    """The R3 file R3's own naming gives for this identity.

    Selection is by name, never by recency: a newer R3 file for another
    gate, model, effort, prompt or closure beside the right one must not
    win. An R3 file without the closure part keeps the old name.
    """
    return DEFAULT_R3_DIR / results_filename(
        model, effort, gate_hash, prompt_sha, closure_sha
    )


def run_live(
    *,
    model: str,
    effort: str,
    results_dir: Path,
    r3_file: Path | None,
    limit: int | None,
    concurrency: int,
    stop_time: datetime | None,
    quiet_before_min: int,
    quiet_after_min: int,
    drain_min: int,
    no_quiet_guard: bool,
    allow_rules_file: bool,
    client_factory: Callable[[], WonderClient],
    clock: Callable[[], datetime],
    now: Callable[[], datetime],
    root: Path | str,
) -> int:
    """Run the 20 arm-slots into the identity file; return an exit code."""
    try:
        doc, pairs_sha = load_pairs()
    except (OSError, ValueError, KeyError) as exc:
        print(f"broken pair: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        base_slot = datetime.fromisoformat(doc["slot"])
    except (ValueError, KeyError) as exc:
        print(f"broken pair: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if validate_slot(base_slot) is not None or any(
        str(pair["profile"]) not in slot_profiles(base_slot) for pair in doc["pairs"]
    ):
        print("broken pair: base slot invalid", file=sys.stderr)
        return EXIT_REFUSED
    try:
        gate_commit, gate_hash = identity.gate_identity(root)
        prompt_sha = identity.prompt_identity(root)
        closure_sha = identity.closure_identity(root)
    except identity.GateIdentityError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        tree_commit, tree_dirty = identity.tree_identity(root)
    except identity.GateIdentityError:
        tree_commit, tree_dirty = "unknown", True
    dirty = identity.dirty_files(root, identity.closure_files(root))
    if dirty:
        print(
            f"refused: dirty gate or prompt files ({', '.join(dirty)})",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if os.environ.get("META_API_KEY", ""):
        print("refused: META_API_KEY is set", file=sys.stderr)
        return EXIT_REFUSED
    if os.environ.get("MUSE_NO_AUTO_UPDATE") != "1":
        print("refused: MUSE_NO_AUTO_UPDATE is not 1", file=sys.stderr)
        return EXIT_REFUSED
    if os.path.isfile(rules_file_path()) and not allow_rules_file:
        print("refused: harness rules file present", file=sys.stderr)
        return EXIT_REFUSED
    if r3_file is not None:
        source_path = r3_file
    else:
        source_path = _expected_r3_path(
            model, effort, gate_hash, prompt_sha, closure_sha
        )
    if not source_path.is_file():
        print(
            f"refused: no matching R3 rows ({source_path.name} absent)",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    try:
        r3_rows = load_rows_file(source_path)
    except RowsUnreadable as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if not r3_rows:
        print("refused: no R3 rows to build cases from", file=sys.stderr)
        return EXIT_REFUSED
    source = r3_rows[0]
    if (
        source.get("model") != model
        or source.get("effort") != effort
        or source.get("gate_hash") != gate_hash
        or source.get("prompt_sha256") != prompt_sha
    ):
        print(
            "refused: R3 rows model "
            f"{source.get('model')} effort {source.get('effort')} gate "
            f"{str(source.get('gate_hash'))[:12]} prompt "
            f"{str(source.get('prompt_sha256'))[:12]} differs from tree model "
            f"{model} effort {effort} gate "
            f"{gate_hash[:12]} prompt {prompt_sha[:12]}",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    source_closure = source.get("closure_sha256")
    if source_closure is not None and source_closure != closure_sha:
        print(
            "refused: R3 rows closure "
            f"{str(source_closure)[:12]} differs from tree closure "
            f"{closure_sha[:12]}",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if source.get("pairs_sha256") != pairs_sha:
        print("refused: pairs file changed since these R3 rows", file=sys.stderr)
        return EXIT_REFUSED
    remaining_r3 = _r3_remaining_slots(doc, r3_rows)
    if remaining_r3:
        print(
            f"refused: R3 has {remaining_r3} remaining slots; "
            "finish R3 first so case numbers cannot shift",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    report = case_build_report(r3_rows, doc)
    counts = {
        profile: report[profile]["eligible"] for profile in ("builder", "disconnect")
    }
    if any(count < 5 for count in counts.values()):
        print(
            "refused: R4 needs 5 eligible base drafts per profile: "
            f"builder {counts['builder']}, disconnect {counts['disconnect']}",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    cases = build_cases(r3_rows, doc)
    try:
        scenarios: dict[tuple[str, str], dict[str, Any]] = {}
        for case in cases:
            for arm in ARMS:
                scenario = arm_scenario(doc, case, arm)
                build_slot_materials(scenario, case.profile)
                scenarios[(case.case_id, arm)] = scenario
    except (ValueError, KeyError) as exc:
        print(f"broken pair: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    results_dir.mkdir(parents=True, exist_ok=True)
    target = results_dir / results_filename(
        model, effort, gate_hash, prompt_sha, closure_sha
    )
    try:
        existing = load_rows_file(target)
    except RowsUnreadable as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    for row in existing:
        if row.get("pairs_sha256") != pairs_sha:
            print("refused: pairs file changed since these rows", file=sys.stderr)
            return EXIT_REFUSED
        if (
            row.get("model") != model
            or row.get("effort") != effort
            or row.get("gate_hash") != gate_hash
            or row.get("prompt_sha256") != prompt_sha
        ):
            print("refused: result file holds another identity", file=sys.stderr)
            return EXIT_REFUSED
        row_closure = row.get("closure_sha256")
        if row_closure is not None and row_closure != closure_sha:
            print("refused: result file holds another identity", file=sys.stderr)
            return EXIT_REFUSED
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in existing:
        key = (str(row["case_id"]), str(row["arm"]))
        by_slot.setdefault(key, []).append(row)
    static = {
        "model": model,
        "effort": effort,
        "muse_no_auto_update": os.environ.get("MUSE_NO_AUTO_UPDATE") == "1",
        "tree_commit": tree_commit,
        "tree_dirty": tree_dirty,
        "gate_commit": gate_commit,
        "gate_hash": gate_hash,
        "prompt_sha256": prompt_sha,
        "closure_sha256": closure_sha,
        "pairs_sha256": pairs_sha,
    }
    todo: list[tuple[Case, str, int, int]] = []
    start_seq = 0
    skipped = 0
    for case in cases:
        for arm in ARMS:
            start_seq += 1
            slot_rows = by_slot.get((case.case_id, arm), [])
            if any(bool(r.get("drawn", False)) for r in slot_rows):
                skipped += 1
                continue
            if len(slot_rows) >= 3:
                skipped += 1
                continue
            todo.append((case, arm, len(slot_rows) + 1, start_seq))
    stop_code: int | None = None
    started = 0
    order: list[int] = []
    outcomes: dict[int, bool] = {}
    drain = timedelta(minutes=drain_min)
    lock = threading.Lock()
    lock_handle: TextIO | None = None

    def _ensure_lock() -> bool:
        """Take the exclusive non-blocking lock on the results file once."""
        nonlocal lock_handle
        if lock_handle is not None:
            return True
        handle = target.open("a", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            print(
                "refused: results file is locked by another run",
                file=sys.stderr,
            )
            return False
        lock_handle = handle
        return True

    def _append(row: dict[str, Any]) -> None:
        line = json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
        with lock, target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _task(spec: tuple[Case, str, int, int]) -> None:
        case, arm, execution, seq = spec
        client = client_factory()
        row = run_arm(
            case=case,
            arm=arm,
            scenario=scenarios[(case.case_id, arm)],
            execution=execution,
            start_seq=seq,
            model=model,
            effort=effort,
            client=client,
            static=static,
            recorded_at="",
        )
        # The stamp means when the arm finished, so read it after the call.
        row["recorded_at"] = now().isoformat()
        _append(row)
        with lock:
            outcomes[seq] = not bool(row["drawn"])

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending: dict[Any, tuple[Case, str, int, int]] = {}
            index = 0
            while index < len(todo) or pending:
                while (
                    index < len(todo)
                    and len(pending) < concurrency
                    and stop_code is None
                ):
                    if limit is not None and started >= limit:
                        print("stopping: repeat limit reached")
                        stop_code = EXIT_STOPPED
                        break
                    moment = clock()
                    if stop_time is not None and moment >= stop_time:
                        print("stopping at the stop time; rerun to resume")
                        stop_code = EXIT_STOPPED
                        break
                    if not no_quiet_guard:
                        reason = start_blocked(
                            moment,
                            quiet_windows(
                                moment,
                                quiet_before_min,
                                quiet_after_min,
                            ),
                            drain,
                            stop_time,
                        )
                        if reason is not None:
                            print(f"stopping: {reason}; rerun to resume")
                            stop_code = EXIT_STOPPED
                            break
                    if _three_unavailable_in_a_row(order, outcomes):
                        print("stopping after 3 consecutive unavailable repeats")
                        stop_code = EXIT_UNAVAILABLE_STOP
                        break
                    if not _ensure_lock():
                        return EXIT_REFUSED
                    spec = todo[index]
                    index += 1
                    started += 1
                    order.append(spec[3])
                    pending[pool.submit(_task, spec)] = spec
                if not pending:
                    break
                done, _waiting = wait(set(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                    del pending[future]
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        if lock_handle is not None:
            lock_handle.close()
        return exc.code
    except Exception as exc:  # noqa: BLE001 -- a failed run reports its shape
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        if lock_handle is not None:
            lock_handle.close()
        return EXIT_ERROR
    if lock_handle is not None:
        lock_handle.close()
        lock_handle = None
    print(f"repeat slots run: {started}; repeat slots already finished: {skipped}")
    if stop_code is not None:
        return stop_code
    try:
        finished = load_rows_file(target)
    except RowsUnreadable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if started == 0 and not finished:
        return EXIT_OK
    remaining = _remaining_slots(cases, finished)
    if remaining:
        print(f"{remaining} repeat slots still need a draw; rerun to resume")
        return EXIT_STOPPED
    return EXIT_OK


def _identity_fields(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    fields = ["model", "effort", "gate_hash", "prompt_sha256", "pairs_sha256"]
    if any(row.get("closure_sha256") is not None for row in rows):
        fields.append("closure_sha256")
    return tuple(fields)


def _summary_info(rows: list[dict[str, Any]], r3_name: str) -> dict[str, Any]:
    first = rows[0]
    attempts = [a for row in rows for a in row.get("attempts", [])]
    stamps = sorted(str(row["recorded_at"]) for row in rows if "recorded_at" in row)
    closure = first.get("closure_sha256")
    return {
        "gate_commit": str(first["gate_commit"]),
        "gate_hash": str(first["gate_hash"]),
        "prompt_sha256": str(first["prompt_sha256"]),
        "closure_sha256": str(closure) if closure is not None else None,
        "pairs_sha256": str(first["pairs_sha256"]),
        "r3_file": r3_name,
        "tree_commit": str(first.get("tree_commit")),
        "tree_commits": sorted({str(row.get("tree_commit")) for row in rows}),
        "model": str(first["model"]),
        "effort": str(first["effort"]),
        "transports": sorted({str(row.get("transport")) for row in rows}),
        "muse_versions": sorted(
            {str(row.get("muse_version") or "unknown") for row in rows}
        ),
        "rules_values": sorted({bool(row.get("harness_rules_file")) for row in rows}),
        "calls": len(attempts),
        "local_starts": sum(len(row.get("local_retries", [])) for row in rows),
        "prompt_tokens": sum((a.get("prompt_tokens") or 0) for a in attempts),
        "completion_tokens": sum((a.get("completion_tokens") or 0) for a in attempts),
        "wall_start": stamps[0] if stamps else "unknown",
        "wall_end": stamps[-1] if stamps else "unknown",
        "three_layer_rows": sum(1 for row in rows if "timeout_retries" in row),
        "two_layer_rows": sum(1 for row in rows if "timeout_retries" not in row),
        "timeout_retries": sum(
            int(row.get("timeout_retries") or 0)
            for row in rows
            if "timeout_retries" in row
        ),
    }


def run_summary(
    results_dir: Path,
    identity_prefix: str | None,
    write_doc: bool,
    r3_file: Path | None,
) -> int:
    """Score one identity file offline; never constructs a client."""
    files = sorted(results_dir.glob("*.jsonl")) if results_dir.is_dir() else []
    file_rows: dict[Path, list[dict[str, Any]]] = {}
    for path in files:
        try:
            rows = load_rows_file(path)
        except RowsUnreadable as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        if rows:
            file_rows[path] = rows
    if identity_prefix:
        matches = [
            path
            for path, rows in file_rows.items()
            if any(
                str(row.get("gate_hash", "")).startswith(identity_prefix)
                for row in rows
            )
        ]
        if not matches:
            print(f"refused: unknown identity {identity_prefix}", file=sys.stderr)
            return EXIT_REFUSED
        if len(matches) > 1:
            names = ", ".join(path.name for path in sorted(matches))
            print(
                f"refused: identity matches more than one file: {names}",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        target = matches[0]
    elif not file_rows:
        try:
            gate_commit, gate_hash = identity.gate_identity()
            prompt_sha = identity.prompt_identity()
            closure_sha: str | None = identity.closure_identity()
        except identity.GateIdentityError:
            gate_commit, gate_hash, prompt_sha = "unknown", "unknown", "unknown"
            closure_sha = None
        _doc, pairs_sha = load_pairs()
        text = render_no_runs(
            gate_commit, gate_hash, prompt_sha, pairs_sha, closure_sha
        )
        sys.stdout.write(text)
        if write_doc:
            DOC_PATH.write_text(text, encoding="utf-8")
            print(f"wrote {DOC_PATH}", file=sys.stderr)
        return EXIT_OK
    else:
        target = max(
            file_rows,
            key=lambda p: (
                max(str(r.get("recorded_at", "")) for r in file_rows[p]),
                p.name,
            ),
        )
    rows = file_rows[target]
    identity_fields = _identity_fields(rows)
    if any(
        tuple(row.get(f) for f in identity_fields)
        != tuple(rows[0].get(f) for f in identity_fields)
        for row in rows
    ):
        print("refused: result file mixes identities", file=sys.stderr)
        return EXIT_REFUSED
    _doc, pairs_sha = load_pairs()
    if str(rows[0].get("pairs_sha256")) != pairs_sha:
        print("refused: pairs file changed since these rows", file=sys.stderr)
        return EXIT_REFUSED
    rows_closure = rows[0].get("closure_sha256")
    if r3_file is not None:
        source_path = r3_file
    else:
        source_path = _expected_r3_path(
            str(rows[0].get("model")),
            str(rows[0].get("effort")),
            str(rows[0].get("gate_hash")),
            str(rows[0].get("prompt_sha256")),
            str(rows_closure) if rows_closure is not None else None,
        )
    floor = None
    report = None
    r3_name = "none"
    r3_rows: list[dict[str, Any]] = []
    if source_path.is_file():
        try:
            r3_rows = load_rows_file(source_path)
        except RowsUnreadable as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
    if r3_rows:
        if (
            str(r3_rows[0].get("model")) != str(rows[0].get("model"))
            or str(r3_rows[0].get("effort")) != str(rows[0].get("effort"))
            or str(r3_rows[0].get("gate_hash")) != str(rows[0].get("gate_hash"))
            or str(r3_rows[0].get("prompt_sha256")) != str(rows[0].get("prompt_sha256"))
            or str(r3_rows[0].get("pairs_sha256")) != str(rows[0].get("pairs_sha256"))
        ):
            print("refused: R3 file holds another identity", file=sys.stderr)
            return EXIT_REFUSED
        r3_closure = r3_rows[0].get("closure_sha256")
        if (
            rows_closure is not None
            and r3_closure is not None
            and str(r3_closure) != str(rows_closure)
        ):
            print("refused: R3 file holds another identity", file=sys.stderr)
            return EXIT_REFUSED
        r3_name = source_path.name
        floor = noise_floor(r3_rows)
        report = case_build_report(r3_rows)
    planned = [case.case_id for case in build_cases(r3_rows, _doc)] if r3_rows else None
    full = score_rows(rows, cases=planned)
    text = render_r4(full, _summary_info(rows, r3_name), floor, report)
    if identity_prefix is None and len(file_rows) > 1:
        ordered = sorted(
            file_rows,
            key=lambda p: (
                max(str(r.get("recorded_at", "")) for r in file_rows[p]),
                p.name,
            ),
        )
        older = [p for p in ordered if p != target]
        for position, path in enumerate(older):
            old_rows = file_rows[path]
            old_fields = _identity_fields(old_rows)
            if any(
                tuple(row.get(f) for f in old_fields)
                != tuple(old_rows[0].get(f) for f in old_fields)
                for row in old_rows
            ):
                print(
                    f"refused: result file mixes identities: {path.name}",
                    file=sys.stderr,
                )
                return EXIT_REFUSED
            if str(old_rows[0].get("pairs_sha256")) != pairs_sha:
                print(
                    f"refused: pairs file changed since these rows: {path.name}",
                    file=sys.stderr,
                )
                return EXIT_REFUSED
            old_closure = old_rows[0].get("closure_sha256")
            old_expected = _expected_r3_path(
                str(old_rows[0].get("model")),
                str(old_rows[0].get("effort")),
                str(old_rows[0].get("gate_hash")),
                str(old_rows[0].get("prompt_sha256")),
                str(old_closure) if old_closure is not None else None,
            )
            old_planned: list[str] | None = None
            if old_expected.is_file():
                try:
                    old_r3_rows = load_rows_file(old_expected)
                except RowsUnreadable as exc:
                    print(f"refused: {exc}", file=sys.stderr)
                    return EXIT_REFUSED
                if (
                    old_r3_rows
                    and all(
                        str(old_r3_rows[0].get(f)) == str(old_rows[0].get(f))
                        for f in (
                            "model",
                            "effort",
                            "gate_hash",
                            "prompt_sha256",
                            "pairs_sha256",
                        )
                    )
                    and (
                        old_closure is None
                        or old_r3_rows[0].get("closure_sha256") is None
                        or str(old_r3_rows[0].get("closure_sha256")) == str(old_closure)
                    )
                ):
                    old_planned = [
                        case.case_id for case in build_cases(old_r3_rows, _doc)
                    ]
            old_full = score_rows(old_rows, cases=old_planned)
            old_info = _summary_info(old_rows, old_expected.name)
            text += "\n" + render_r4_history_section(
                old_full, old_info, first=position == 0
            )
    sys.stdout.write(text)
    try:
        _commit, current_hash = identity.gate_identity()
        current_prompt = identity.prompt_identity()
        current_closure: str | None = identity.closure_identity()
    except identity.GateIdentityError:
        current_hash, current_prompt, current_closure = None, None, None
    if current_hash is not None and (
        current_hash != rows[0].get("gate_hash")
        or current_prompt != rows[0].get("prompt_sha256")
        or (
            rows_closure is not None
            and current_closure is not None
            and current_closure != rows_closure
        )
    ):
        note = (
            f"note: tree gate {current_hash[:12]} prompt {str(current_prompt)[:12]} "
            f"differs from rows gate {str(rows[0].get('gate_hash'))[:12]} prompt "
            f"{str(rows[0].get('prompt_sha256'))[:12]}"
        )
        if rows_closure is not None and current_closure is not None:
            note += (
                f" closure {current_closure[:12]} differs from rows closure "
                f"{str(rows_closure)[:12]}"
            )
        print(note, file=sys.stderr)
    if write_doc:
        DOC_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {DOC_PATH}", file=sys.stderr)
    return EXIT_OK


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals.r4")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--identity", default=None)
    parser.add_argument("--write-doc", action="store_true")
    parser.add_argument("--allow-rules-file", action="store_true")
    parser.add_argument("--r3-file", default=None)
    add_shared_args(parser, str(DEFAULT_RESULTS_DIR))
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[], WonderClient] | None = None,
    clock: Callable[[], datetime] | None = None,
    now: Callable[[], datetime] | None = None,
    root: Path | str | None = None,
) -> int:
    args = _parse_args(argv)
    results_dir = Path(args.results_dir)
    r3_path = Path(args.r3_file) if args.r3_file is not None else None
    if args.summary:
        return run_summary(results_dir, args.identity, args.write_doc, r3_path)
    model = args.model if args.model is not None else DEFAULT_MODEL
    effort = args.effort if args.effort is not None else DEFAULT_EFFORT
    disabled = live_disabled(LIVE_VAR)
    if disabled is not None:
        print(disabled)
        return EXIT_OK
    try:
        stop_time = parse_stop_time(args.stop_time)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return exc.code
    concurrency = args.concurrency if args.concurrency is not None else 4
    if not isinstance(concurrency, int) or concurrency < 1:
        print("refused: concurrency below 1", file=sys.stderr)
        return EXIT_REFUSED
    if args.limit is not None and args.limit < 0:
        print("refused: bad limit", file=sys.stderr)
        return EXIT_REFUSED
    factory = client_factory if client_factory is not None else default_client_factory
    return run_live(
        model=model,
        effort=effort,
        results_dir=results_dir,
        r3_file=r3_path,
        limit=args.limit,
        concurrency=concurrency,
        stop_time=stop_time,
        quiet_before_min=args.quiet_before_minutes,
        quiet_after_min=args.quiet_after_minutes,
        drain_min=args.drain_minutes,
        no_quiet_guard=args.no_quiet_guard,
        allow_rules_file=args.allow_rules_file,
        client_factory=factory,
        clock=clock if clock is not None else utc_now,
        now=now if now is not None else utc_now,
        root=root if root is not None else _REPOS_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
