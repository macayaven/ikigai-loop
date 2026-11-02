"""Ticket 15b: the R3 steering runner (D23-D29, D36).

Each (pair, arm, repeat) goes through Ticket 11's real ``propose`` once,
with the context built from the product's own constants and functions.
No model call happens without ``IKIGAI_R3_LIVE=1``. ``--summary`` is
pure and offline.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
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
from evals.r3_scenario import apply_ops
from evals.r3_score import (
    render_no_runs,
    render_r3,
    render_r3_history_section,
    score_rows,
)
from framework.briefing.context import GateContext, MetricSnapshot, TimeInterval
from framework.briefing.schemas import Commitment
from framework.cycle.orchestrator import (
    SLOT_LIMITS,
    STALE_AFTER_S,
    WONDER_TIMEOUT_S,
    EligibilityState,
    eligible_commitments,
    slot_profiles,
    validate_slot,
)
from framework.glimmer.labels import INTERNAL_ONLY_LABELS
from framework.proposal.core import ModelParams, WonderClient, propose
from framework.proposal.hour import allowed_windows
from framework.proposal.local_retry import LocalRetryClient
from framework.proposal.muse_client import MuseExecClient, rules_file_path
from framework.proposal.timeout_retry import TimeoutRetryClient
from framework.schemas.core import Fact, FactWindow

LIVE_VAR = "IKIGAI_R3_LIVE"
SUBJECT_ID = "subject-1"

PAIRS_PATH = _REPOS_ROOT / "evals" / "r3_pairs.json"
DEFAULT_RESULTS_DIR = _REPOS_ROOT / "evals" / "results" / "r3"
DOC_PATH = _REPOS_ROOT / "docs" / "r3.md"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_UNAVAILABLE_STOP = 3
EXIT_STOPPED = 4


def utc_now() -> datetime:
    """The default live-run clock: the current UTC instant."""
    return datetime.now(UTC)


class RowsUnreadable(Refusal):
    """A results file ends torn or holds no JSON; it is never skipped."""


@dataclass(frozen=True)
class SlotMaterials:
    slot: datetime
    hour: TimeInterval
    eligible: tuple[Commitment, ...]
    context: GateContext


def _sanitise_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def load_pairs(path: Path | None = None) -> tuple[dict[str, Any], str]:
    """Load the committed pairs; the sha covers the raw bytes as loaded."""
    target = path if path is not None else PAIRS_PATH
    raw = target.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def scenario_for(doc: dict[str, Any], pair: dict[str, Any], arm: str) -> dict[str, Any]:
    """The pair's scenario for one arm: own base arm, never shared."""
    base = {
        "slot": doc["slot"],
        "hour": copy.deepcopy(doc["hour"]),
        "commitments": copy.deepcopy(doc["commitments"]),
        "facts": copy.deepcopy(doc["facts"]),
        "metrics": dict(doc["metrics"]),
    }
    if arm == "base":
        return base
    if arm == "perturbed":
        return apply_ops(base, list(pair["perturb"]))
    raise Refusal("unknown arm")


def build_slot_materials(scenario: dict[str, Any], profile: str) -> SlotMaterials:
    """Scenario dicts into the product's own types, in scenario order."""
    slot = datetime.fromisoformat(scenario["slot"])
    hour = TimeInterval(
        start=datetime.fromisoformat(scenario["hour"]["start"]),
        end=datetime.fromisoformat(scenario["hour"]["end"]),
    )
    offered = tuple(
        Commitment(
            id=item["id"],
            profile_id=item["profile"],
            title=item["title"],
            kind=item["kind"],
            dimension=item["dimension"],
            evidence=item["evidence"],
        )
        for item in scenario["commitments"]
    )
    eligible = eligible_commitments(
        offered,
        profile_id=profile,
        slot_local=slot,
        state=EligibilityState(
            disconnect_sent_today=0, now_local=slot, hour_start_local=hour.start
        ),
    )
    window_start = slot - timedelta(hours=72)
    facts = {
        str(item["id"]): Fact(
            id=str(item["id"]),
            subject_id=SUBJECT_ID,
            window=FactWindow(start=window_start, end=slot),
            statement=str(item["statement"]),
            evidence=["r3-synthetic"],
            tier="public",
        )
        for item in scenario["facts"]
    }
    metrics = MetricSnapshot(
        values={str(key): float(value) for key, value in scenario["metrics"].items()}
    )
    context = GateContext(
        facts=facts,
        metrics=metrics,
        parent_briefing=None,
        parent_metrics=None,
        free_intervals=allowed_windows(slot, SLOT_LIMITS),
        busy_intervals=(),
        limits=SLOT_LIMITS,
        private_terms=(),
        private_terms_available=True,
        forbidden_raw_literals=tuple(sorted(INTERNAL_ONLY_LABELS)),
        commitments=eligible,
        commitments_available=True,
    )
    return SlotMaterials(slot=slot, hour=hour, eligible=eligible, context=context)


def default_client_factory(runner: Any = None) -> WonderClient:
    """The one default stack, shared with R4: timeout retry around local retry around muse exec."""
    inner = MuseExecClient(
        private_terms=(),
        private_terms_available=True,
        timeout_s=WONDER_TIMEOUT_S,
        runner=runner,
    )
    retrying = LocalRetryClient(inner, seconds_left=None)
    return TimeoutRetryClient(  # type: ignore[return-value]
        retrying,
        seconds_left=lambda: float("inf"),
        min_seconds_left=WONDER_TIMEOUT_S,
    )


def results_filename(
    model: str,
    effort: str,
    gate_hash: str,
    prompt_sha256: str,
    closure_sha256: str | None = None,
) -> str:
    base = (
        f"{_sanitise_name(model)}__{_sanitise_name(effort)}"
        f"__g{gate_hash[:12]}__p{prompt_sha256[:12]}"
    )
    if closure_sha256:
        base += f"__c{closure_sha256[:12]}"
    return base + ".jsonl"


def load_rows_file(path: Path) -> list[dict[str, Any]]:
    """Parse one JSONL file; a torn final line is a hard error."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    if not text.endswith("\n"):
        raise RowsUnreadable(f"unreadable rows: {path.name}")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            raise RowsUnreadable(f"unreadable rows: {path.name}") from None
    return rows


def _three_unavailable_in_a_row(order: list[int], outcomes: dict[int, bool]) -> bool:
    """Any three consecutive started slots, in start order, all ended unavailable.

    ``outcomes[seq]`` is True only once that started slot has finished
    unavailable; in-flight or drawn slots break the run.
    """
    for pos in range(len(order) - 2):
        if all(outcomes.get(seq) is True for seq in order[pos : pos + 3]):
            return True
    return False


def _remaining_slots(doc: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    """Count planned slots neither drawn nor exhausted, from the rows on file."""
    by_slot: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["pair_id"]), str(row["arm"]), int(row["repeat"]))
        by_slot.setdefault(key, []).append(row)
    remaining = 0
    for pair in doc["pairs"]:
        for arm in ("base", "perturbed"):
            for repeat in (1, 2, 3):
                slot_rows = by_slot.get((str(pair["id"]), arm, repeat), [])
                if any(bool(row.get("drawn", False)) for row in slot_rows):
                    continue
                if len(slot_rows) >= 3:
                    continue
                remaining += 1
    return remaining


def run_repeat(
    *,
    pair: dict[str, Any],
    arm: str,
    repeat: int,
    execution: int,
    start_seq: int,
    scenario: dict[str, Any],
    model: str,
    effort: str,
    client: WonderClient,
    static: dict[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    """One repeat slot through ``propose``; one execution, one row."""
    materials = build_slot_materials(scenario, str(pair["profile"]))
    result = propose(
        profile_id=str(pair["profile"]),
        subject_id=SUBJECT_ID,
        slot=materials.slot,
        as_of=materials.slot,
        cycle_id="r3-synthetic",
        run=1,
        hour=materials.hour,
        eligible=materials.eligible,
        context=materials.context,
        client=client,
        models=ModelParams(model, effort, model, effort),
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=materials.slot,
        offered={},
    )
    attempts: list[dict[str, Any]] = []
    for attempt in result.attempts:
        attempts.append(
            {
                "number": attempt.number,
                "model_requested": attempt.model_requested,
                "model_reported": attempt.model_reported,
                "effort": attempt.effort,
                "parsed_ok": attempt.parsed_ok,
                "blocked": attempt.blocked,
                "codes": [list(pair_) for pair_ in attempt.codes],
                "latency_ms": attempt.latency_ms,
                "prompt_tokens": attempt.prompt_tokens,
                "completion_tokens": attempt.completion_tokens,
                "reasoning_tokens": attempt.reasoning_tokens,
                "cached_tokens": attempt.cached_tokens,
                "finish_reason": attempt.finish_reason,
                "prompt_hash": attempt.prompt_hash,
                "raw_text": attempt.raw_text,
            }
        )
    first = result.attempts[0] if result.attempts else None
    if first is None:
        drawn = False
        unavailable_reason: str | None = "no-attempt"
    elif len(first.codes) == 1 and first.codes[0][0] == "MODEL_UNAVAILABLE":
        drawn = False
        unavailable_reason = str(first.codes[0][1])
    else:
        drawn = True
        unavailable_reason = None
    pick: str | None = None
    if result.kind == "proposal" and result.briefing is not None:
        for section in result.briefing.sections:
            if section.type == "actions" and section.actions:
                pick = section.actions[0].commitment_id
                break
    if result.kind == "fallback" and result.fallback is not None:
        fallback_id: str | None = result.fallback.commitment.id
    else:
        fallback_id = None
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
    if first is not None:
        rules_value = first.harness_rules_file
        reported = first.model_reported
    else:
        rules_value = client.harness_rules_file
        reported = "unreported"
    return {
        "schema": 1,
        "pair_id": pair["id"],
        "kind": pair["kind"],
        "profile": pair["profile"],
        "profile_id": pair["profile"],
        "expect_pick": pair.get("expect_pick"),
        "expect_avoid": pair.get("expect_avoid"),
        "arm": arm,
        "repeat": repeat,
        "execution": execution,
        "start_seq": start_seq,
        "drawn": drawn,
        "unavailable_reason": unavailable_reason,
        "result_kind": result.kind,
        "pick": pick,
        "fallback_commitment_id": fallback_id,
        "reason_codes": list(result.reason_codes),
        "prompt_hash": result.prompt_hash,
        "latency_ms": sum(attempt.latency_ms for attempt in result.attempts),
        "prompt_tokens": sum(attempt.prompt_tokens or 0 for attempt in result.attempts),
        "completion_tokens": sum(
            attempt.completion_tokens or 0 for attempt in result.attempts
        ),
        "model_reported": reported,
        "local_retries": local_retries,
        "timeout_retries": timeout_retries,
        "attempts": attempts,
        "transport": client.transport,
        "muse_version": client.transport_version,
        "harness_rules_file": rules_value,
        "recorded_at": recorded_at,
        **static,
    }


def run_live(
    *,
    model: str,
    effort: str,
    results_dir: Path,
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
    """Run the 120-slot matrix into the identity file; return an exit code."""
    try:
        doc, pairs_sha = load_pairs()
    except (OSError, ValueError, KeyError) as exc:
        print(f"broken pair: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        scenarios: dict[tuple[str, str], dict[str, Any]] = {}
        for pair in doc["pairs"]:
            for arm in ("base", "perturbed"):
                scenario = scenario_for(doc, pair, arm)
                build_slot_materials(scenario, str(pair["profile"]))
                scenarios[(str(pair["id"]), arm)] = scenario
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
    by_slot: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in existing:
        key = (str(row["pair_id"]), str(row["arm"]), int(row["repeat"]))
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
    todo: list[tuple[dict[str, Any], str, int, int, int]] = []
    start_seq = 0
    skipped = 0
    for pair in doc["pairs"]:
        for arm in ("base", "perturbed"):
            for repeat in (1, 2, 3):
                start_seq += 1
                slot_rows = by_slot.get((str(pair["id"]), arm, repeat), [])
                if any(bool(r.get("drawn", False)) for r in slot_rows):
                    skipped += 1
                    continue
                if len(slot_rows) >= 3:
                    skipped += 1
                    continue
                todo.append((pair, arm, repeat, len(slot_rows) + 1, start_seq))
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

    def _task(
        spec: tuple[dict[str, Any], str, int, int, int],
    ) -> None:
        pair, arm, repeat, execution, seq = spec
        client = client_factory()
        row = run_repeat(
            pair=pair,
            arm=arm,
            repeat=repeat,
            execution=execution,
            start_seq=seq,
            scenario=scenarios[(str(pair["id"]), arm)],
            model=model,
            effort=effort,
            client=client,
            static=static,
            recorded_at="",
        )
        # The stamp means when the repeat finished, so read it after ``propose``.
        row["recorded_at"] = now().isoformat()
        _append(row)
        with lock:
            outcomes[seq] = not bool(row["drawn"])

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending: dict[Any, tuple[dict[str, Any], str, int, int, int]] = {}
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
                    order.append(spec[4])
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
    remaining = _remaining_slots(doc, finished)
    if remaining:
        print(f"{remaining} repeat slots still need a draw; rerun to resume")
        return EXIT_STOPPED
    return EXIT_OK


def _identity_fields(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    fields = ["model", "effort", "gate_hash", "prompt_sha256", "pairs_sha256"]
    if any(row.get("closure_sha256") is not None for row in rows):
        fields.append("closure_sha256")
    return tuple(fields)


def _summary_info(rows: list[dict[str, Any]]) -> dict[str, Any]:
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


def run_summary(results_dir: Path, identity_prefix: str | None, write_doc: bool) -> int:
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
    full = score_rows(rows)
    text = render_r3(full, _summary_info(rows))
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
            old_full = score_rows(old_rows)
            old_info = _summary_info(old_rows)
            text += "\n" + render_r3_history_section(
                old_full, old_info, first=position == 0
            )
    sys.stdout.write(text)
    try:
        _commit, current_hash = identity.gate_identity()
        current_closure: str | None = identity.closure_identity()
    except identity.GateIdentityError:
        current_hash, current_closure = None, None
    rows_closure = rows[0].get("closure_sha256")
    if current_hash is not None and (
        current_hash != rows[0].get("gate_hash")
        or (
            rows_closure is not None
            and current_closure is not None
            and current_closure != rows_closure
        )
    ):
        note = (
            f"note: tree gate {current_hash[:12]} differs from rows gate "
            f"{str(rows[0].get('gate_hash'))[:12]}"
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
    parser = argparse.ArgumentParser(prog="evals.r3")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--identity", default=None)
    parser.add_argument("--write-doc", action="store_true")
    parser.add_argument("--allow-rules-file", action="store_true")
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
    if args.summary:
        return run_summary(results_dir, args.identity, args.write_doc)
    if not args.model or not args.effort:
        print("need --model and --effort", file=sys.stderr)
        return EXIT_REFUSED
    if args.repeats != 3:
        print("refused: --repeats must be 3", file=sys.stderr)
        return EXIT_REFUSED
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
        model=args.model,
        effort=args.effort,
        results_dir=results_dir,
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
