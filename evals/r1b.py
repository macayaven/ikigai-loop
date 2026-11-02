"""Ticket 16b: the R1b runner (D4, D5, D8, D9, D11, D14-D18, D20-D22).

Every arm calls Ticket 11's ``propose`` itself through one validation
path. No model call happens without ``IKIGAI_R1B_LIVE=1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from pydantic import (
    AwareDatetime,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from evals.r1b_clients import (
    LocalWonderClient,
    ReplayWonderClient,
    SwappingWonderClient,
)
from evals.r1b_prompts import (
    build_plain_prompt,
    build_plain_response_schema,
)
from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.briefing.labels import MetricBinding, metric_label_binding
from framework.briefing.schemas import Commitment
from framework.proposal.client import EFFORTS, refuse_contributor_model
from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    ModelParams,
    WonderClient,
    propose,
)
from framework.proposal.hour import allowed_windows
from framework.proposal.muse_client import MuseExecClient
from framework.proposal.prompt import Delta, compute_deltas, offered_metrics
from framework.schemas.base import SchemaModel
from framework.schemas.core import Fact

SUBJECT_ID = "subject-1"

# Set by the mechanical copy session from the frozen bytes; no implementation
# session ever prints those bytes. Until then every live run is refused.
EXPECTED_CASES_SHA256 = (
    "45db53c766476fabf06888cf400c55b54e43bc720807790e892892a73fcf23d4"
)
FIXTURE_CASES_SHA256 = (
    "293ce1a5e26e554598bf57e4e0dfe9a6600028fcf6828fc0fd401ce28f4bd520"
)

DEFAULT_CASES_PATH = _REPOS_ROOT / "evals" / "r1b_cases.json"
FIXTURE_CASES_PATH = _REPOS_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json"
DEFAULT_RESULTS_DIR = _REPOS_ROOT / "evals" / "results" / "r1b"
DEMO_REAL_REJECTION_PATH = _REPOS_ROOT / "evals" / "demo_real_rejection.json"
DOC_PATH = _REPOS_ROOT / "docs" / "r1b.md"

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNAVAILABLE_STOP = 3

GATE_SOURCE_FILES = (
    "framework/briefing/gate.py",
    "framework/briefing/labels.py",
    "framework/briefing/numbers.py",
    "framework/briefing/context.py",
    "framework/briefing/schemas.py",
    "framework/proposal/assembly.py",
    "framework/proposal/schemas.py",
    "framework/proposal/core.py",
)

TRAP_VALUES = (
    "rounding",
    "confusable-metrics",
    "flat-direction",
    "orphan-number",
    "advice",
    "injection",
    "mixed-direction",
    "period-scope",
)

LIMITS = ProfileLimits(
    timezone="Europe/Madrid",
    allowed_start=time(13, 0),
    allowed_end=time(23, 30),
    max_actions=3,
)

_PERIOD_ORDER = {"earlier": 0, "prior": 1, "last": 2}


class GateIdentityError(Exception):
    """The gate cannot be labelled: dirty files or no repository."""


class Refusal(Exception):
    """A pre-run refusal; the message names the rule only."""

    def __init__(self, message: str, *, code: int = EXIT_REFUSED) -> None:
        super().__init__(message)
        self.code = code


# Cases ---------------------------------------------------------------------


class R1bCase(SchemaModel):
    """One benchmark case in the D8 shape."""

    id: str
    slot: AwareDatetime
    profile: Literal["builder", "disconnect"]
    hour: TimeInterval
    commitments: tuple[Commitment, ...] = Field(min_length=1)
    facts: tuple[Fact, ...] = ()
    metrics: dict[str, float] = Field(min_length=1)
    parent_snapshot: dict[str, float] | None = None
    trap: (
        Literal[
            "rounding",
            "confusable-metrics",
            "flat-direction",
            "orphan-number",
            "advice",
            "injection",
            "mixed-direction",
            "period-scope",
        ]
        | None
    ) = None

    @field_validator("slot")
    @classmethod
    def _valid_slot(cls, slot: datetime) -> datetime:
        offset = slot.utcoffset()
        if offset != timedelta(hours=1):
            raise ValueError("slot-offset")
        if (
            slot.second != 0
            or slot.microsecond != 0
            or slot.minute not in (0, 15, 30, 45)
        ):
            raise ValueError("slot-quarter-hour")
        if not (
            datetime(2026, 11, 3).date() <= slot.date() <= datetime(2026, 11, 20).date()
        ):
            raise ValueError("slot-window")
        if not (time(13, 0) <= slot.timetz().replace(tzinfo=None) <= time(22, 30)):
            raise ValueError("slot-window")
        return slot

    @field_validator("metrics", "parent_snapshot")
    @classmethod
    def _finite_values(cls, values: dict[str, float] | None) -> dict[str, float] | None:
        import math

        if values is None:
            return None
        for value in values.values():
            if not math.isfinite(value):
                raise ValueError("metric-finite")
        return values

    @model_validator(mode="after")
    def _consistent_case(self) -> R1bCase:
        if self.hour.start != self.slot:
            raise ValueError("hour-start")
        if self.hour.end != self.slot + timedelta(hours=1):
            raise ValueError("hour-end")
        seen_commitments: set[str] = set()
        for commitment in self.commitments:
            if commitment.id in seen_commitments:
                raise ValueError("duplicate-commitment-id")
            seen_commitments.add(commitment.id)
            if commitment.profile_id != self.profile:
                raise ValueError("commitment-profile")
        seen_facts: set[str] = set()
        for fact in self.facts:
            if fact.id in seen_facts:
                raise ValueError("duplicate-fact-id")
            seen_facts.add(fact.id)
            if fact.subject_id != SUBJECT_ID:
                raise ValueError("fact-subject")
            if fact.tier == "sensitive":
                raise ValueError("sensitive-fact")
        return self


def _sanitised_error(case_id: str, errors: list[Any]) -> ValueError:
    rules = sorted({str(error.get("msg", "shape")) for error in errors})
    return ValueError(f"{case_id} " + "; ".join(rules))


def load_cases(path: str | Path) -> tuple[R1bCase, ...]:
    """Parse the case file; failure output names case ids and rules only."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("shape: top-level array")
    cases: list[R1bCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        candidate = item.get("id") if isinstance(item, dict) else None
        case_id = (
            candidate if isinstance(candidate, str) and candidate else f"index-{index}"
        )
        if case_id in seen:
            raise ValueError(f"{case_id} duplicate-case-id")
        seen.add(case_id)
        try:
            cases.append(R1bCase.model_validate(item))
        except ValidationError as exc:
            raise _sanitised_error(case_id, exc.errors()) from None
    return tuple(cases)


def cases_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pinned_hash_for(cases_path: Path) -> str:
    resolved = cases_path.resolve()
    if resolved == DEFAULT_CASES_PATH.resolve():
        return EXPECTED_CASES_SHA256
    if resolved == FIXTURE_CASES_PATH.resolve():
        return FIXTURE_CASES_SHA256
    raise Refusal("unpinned cases file")


def check_cases_hash(cases_path: Path) -> str:
    """Refuse unless the file's hash equals its pinned constant."""
    digest = cases_sha256(cases_path)
    if digest != _pinned_hash_for(cases_path):
        raise Refusal("case-file hash mismatch")
    return digest


def require_cases_file_for_results(cases_path: Path, results_dir: Path) -> None:
    """From D11e: once rows exist, the case file must exist."""
    if (
        results_dir.is_dir()
        and any(results_dir.glob("*.jsonl"))
        and not cases_path.exists()
    ):
        raise AssertionError("case-file-missing: result rows without cases")


# Context -------------------------------------------------------------------


def case_parent_briefing(case: R1bCase) -> tuple[Any | None, dict[str, float] | None]:
    """Synthesise the parent briefing, exactly like Ticket 11's cases."""
    if case.parent_snapshot is None:
        return None, None
    from framework.briefing.schemas import Briefing

    slot = datetime.fromisoformat(str(case.slot))
    parent = Briefing(
        id=f"brf-{case.profile}-r1b-parent-{case.id}",
        profile_id=case.profile,
        subject_id=SUBJECT_ID,
        slot=slot - timedelta(hours=24),
        parent_briefing_id=None,
        sections=[],
    )
    return parent, dict(case.parent_snapshot)


def offered_deltas_for(case: R1bCase) -> tuple[Delta, ...]:
    if case.parent_snapshot is None:
        return ()
    return compute_deltas(
        offered_metrics(dict(case.metrics)), dict(case.parent_snapshot)
    )


def build_case_hour(case: R1bCase) -> TimeInterval:
    return case.hour


def build_case_context(case: R1bCase) -> GateContext:
    slot = datetime.fromisoformat(str(case.slot))
    parent, parent_values = case_parent_briefing(case)
    parent_metrics = (
        MetricSnapshot(values=dict(parent_values))
        if parent_values is not None
        else None
    )
    if (
        parent is not None
        and parent_metrics is not None
        and not compute_deltas(offered_metrics(dict(case.metrics)), parent_values or {})
    ):
        parent = None
        parent_metrics = None
    return GateContext(
        facts={fact.id: fact for fact in case.facts},
        metrics=MetricSnapshot(values=dict(case.metrics)),
        parent_briefing=parent,
        parent_metrics=parent_metrics,
        free_intervals=allowed_windows(slot, LIMITS),
        busy_intervals=(),
        limits=LIMITS,
        private_terms=(),
        private_terms_available=True,
        forbidden_raw_literals=(),
        commitments=tuple(case.commitments),
        commitments_available=True,
    )


def metric_sort_key(metric_id: str) -> tuple[str, int]:
    binding = metric_label_binding(metric_id)
    if binding is None:
        return (metric_id, -1)
    return (binding.family, _PERIOD_ORDER.get(binding.period or "", -1))


def metric_binding_for(metric_id: str) -> MetricBinding | None:
    return metric_label_binding(metric_id)


def shortest_label(binding: MetricBinding) -> str:
    # Two-line sort mirroring the product's label order; not a minimum.
    return sorted(sorted(binding.labels, reverse=True), key=len)[0]  # noqa: FURB192


def plain_materials_for_case(case: R1bCase) -> tuple[str, dict[str, Any]]:
    """The plain prompt and schema against the case's effective parent."""
    deltas = offered_deltas_for(case)
    prompt = build_plain_prompt(
        profile_name=case.profile.capitalize(),
        hour=build_case_hour(case),
        facts=list(case.facts),
        metrics=dict(case.metrics),
        deltas=deltas,
        commitments=list(case.commitments),
    )
    return prompt, build_plain_response_schema(has_parent=bool(deltas))


# Arms and matrix ------------------------------------------------------------


@dataclass(frozen=True)
class ArmSpec:
    name: str
    prompt_source: Literal["product", "plain"]
    schema_source: Literal["product", "plain"]


ARM_REGISTRY: tuple[ArmSpec, ...] = (
    ArmSpec("product", "product", "product"),
    ArmSpec("plain", "plain", "plain"),
)


@dataclass(frozen=True)
class MatrixRow:
    model: str
    effort: str
    route: Literal["muse", "local"]
    concurrency: int


MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow("muse-wonder-1.0", "high", "muse", 4),
    MatrixRow("muse-wonder-full-1.0", "high", "muse", 4),
    MatrixRow("muse-spark-1.3", "medium", "muse", 4),
    MatrixRow("muse-spark-1.3", "low", "muse", 4),
    MatrixRow("muse-glimmer-30b", "none", "local", 1),
)


def resolve_arm(name: str, registry: tuple[ArmSpec, ...] = ARM_REGISTRY) -> ArmSpec:
    for spec in registry:
        if spec.name == name:
            return spec
    raise Refusal("unknown arm: " + ", ".join(spec.name for spec in registry))


# Gate identity --------------------------------------------------------------


def gate_identity() -> tuple[str, str]:
    """(commit, content hash) over the pinned gate source files."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *GATE_SOURCE_FILES],
            cwd=_REPOS_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        log = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", *GATE_SOURCE_FILES],
            cwd=_REPOS_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateIdentityError("unknown-gate-identity") from exc
    if status.returncode != 0 or log.returncode != 0:
        raise GateIdentityError("unknown-gate-identity")
    if status.stdout.strip():
        raise GateIdentityError("uncommitted-gate-files")
    commit = log.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise GateIdentityError("unknown-gate-identity")
    digest = hashlib.sha256()
    for name in sorted(GATE_SOURCE_FILES):
        data = (_REPOS_ROOT / name).read_bytes()
        digest.update(name.encode() + b"\0" + data + b"\0")
    return commit, digest.hexdigest()


# Clients --------------------------------------------------------------------


def build_base_client(route: str, llm_config: Any = None) -> WonderClient:
    if route == "muse":
        return MuseExecClient(private_terms=(), private_terms_available=True)
    if route == "local":
        if llm_config is None:
            raise Refusal("LOCAL_LLM_MODEL")
        return LocalWonderClient(llm_config)
    raise Refusal("unknown route")


class StopTimeGuard:
    """Refuse a retry once the stop time has passed (D14).

    The first call of a ``propose`` execution already started, so it runs
    to completion; any later call would start a new model call after the
    instant, so it raises ``MetaUnavailableError`` with the closed reason
    ``stop time`` instead. ``propose`` records that as an unavailable
    attempt, which the summary counts on its retry-unavailable line.
    """

    def __init__(self, wrapped: WonderClient, stop_time: datetime | None) -> None:
        self._wrapped = wrapped
        self._stop_time = stop_time
        self.calls = 0

    @property
    def transport(self) -> str:
        return self._wrapped.transport

    @property
    def transport_version(self) -> str | None:
        return self._wrapped.transport_version

    @property
    def harness_rules_file(self) -> bool | None:
        return self._wrapped.harness_rules_file

    def complete(self, request: Any) -> Any:
        self.calls += 1
        if self.calls > 1 and _stop_due(self._stop_time):
            raise MetaUnavailableError("stop time", latency_ms=0)
        return self._wrapped.complete(request)


def _wrap_for_arm(
    base: WonderClient, arm: ArmSpec, case: R1bCase
) -> SwappingWonderClient:
    prompt_override: str | None = None
    schema_override: dict[str, Any] | None = None
    if arm.prompt_source == "plain" or arm.schema_source == "plain":
        prompt, schema = plain_materials_for_case(case)
        if arm.prompt_source == "plain":
            prompt_override = prompt
        if arm.schema_source == "plain":
            schema_override = schema
    return SwappingWonderClient(
        base, prompt_override=prompt_override, schema_override=schema_override
    )


# Rows ------------------------------------------------------------------------


def _sanitise_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def results_path(
    results_dir: Path, model: str, effort: str, arm: str, gate12: str
) -> Path:
    return (
        results_dir
        / f"{_sanitise_name(model)}__{_sanitise_name(effort)}__{_sanitise_name(arm)}__{gate12}.jsonl"
    )


def read_result_rows(
    results_dir: Path, *, include_regated: bool = False
) -> list[dict[str, Any]]:
    """Read attempt rows; re-gated files are included only on request.

    Resume and the live tables always use the default, so re-gated rows
    never mark a case finished and never move a live number.
    """
    rows: list[dict[str, Any]] = []
    if not results_dir.is_dir():
        return rows
    for path in sorted(results_dir.glob("*.jsonl")):
        if path.name.startswith("regate__") and not include_regated:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _row_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row["case_id"]),
        str(row["arm"]),
        str(row["model"]),
        str(row["effort"]),
        str(row["gate_commit"]),
        str(row["gate_hash"]),
        str(row["cases_sha256"]),
    )


def _attempt_rows(
    rows: list[dict[str, Any]], identity: tuple[str, ...], execution: int
) -> list[dict[str, Any]]:
    return sorted(
        (
            row
            for row in rows
            if _row_identity(row) == identity and int(row["execution"]) == execution
        ),
        key=lambda row: int(row["attempt"]),
    )


def _execution_complete(exec_rows: list[dict[str, Any]]) -> bool:
    """Complete: a first attempt exists, is not unavailable, is not a fragment."""
    first = [row for row in exec_rows if int(row["attempt"]) == 1]
    if not first:
        return False
    codes = [pair[0] for pair in first[0]["codes"]]
    return "MODEL_UNAVAILABLE" not in codes


def finished_identities(rows: list[dict[str, Any]]) -> set[tuple[str, ...]]:
    """Identities holding a counted (last complete) execution."""
    by_identity: dict[tuple[str, ...], set[int]] = {}
    for row in rows:
        if row.get("regated"):
            continue
        identity = _row_identity(row)
        by_identity.setdefault(identity, set()).add(int(row["execution"]))
    finished: set[tuple[str, ...]] = set()
    for identity, executions in by_identity.items():
        ordered = sorted(executions)
        if any(
            _execution_complete(_attempt_rows(rows, identity, number))
            for number in ordered
        ):
            finished.add(identity)
    return finished


def _next_executions(
    rows: list[dict[str, Any]],
    cases: list[R1bCase],
    arms: list[ArmSpec],
    model: str,
    effort: str,
    gate_commit: str,
    gate_hash: str,
    cases_sha256: str,
) -> dict[tuple[str, str], int]:
    highest: dict[tuple[str, str], int] = {}
    for row in rows:
        if row.get("regated"):
            continue
        identity = _row_identity(row)
        if identity[2:] != (model, effort, gate_commit, gate_hash, cases_sha256):
            continue
        key = (identity[0], identity[1])
        highest[key] = max(highest.get(key, 0), int(row["execution"]))
    return {
        (case.id, arm.name): highest.get((case.id, arm.name), 0) + 1
        for case in cases
        for arm in arms
    }


def run_case_arm(
    *,
    case: R1bCase,
    arm: ArmSpec,
    model: str,
    effort: str,
    client: WonderClient,
    gate_commit: str,
    gate_hash: str,
    cases_sha256: str,
    execution: int,
    stop_time: datetime | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Run one (case, arm) through ``propose``; return rows and finished."""
    context = build_case_context(case)
    hour = build_case_hour(case)
    slot = datetime.fromisoformat(str(case.slot))
    wrapper = _wrap_for_arm(StopTimeGuard(client, stop_time), arm, case)
    models = ModelParams(
        first_model=model,
        first_effort=effort,
        retry_model=model,
        retry_effort=effort,
    )
    result = propose(
        profile_id=case.profile,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=slot,
        cycle_id=f"r1b-{case.id}",
        run=1,
        hour=hour,
        eligible=list(case.commitments),
        context=context,
        client=wrapper,
        models=models,
        policy="",
        stale_after_s=12 * 3600,
        cycle_as_of=slot,
        offered={},
    )
    rows: list[dict[str, Any]] = []
    recorded = datetime.now(UTC).isoformat()
    for index, attempt in enumerate(result.attempts):
        if arm.prompt_source == "product":
            prompt_hash = attempt.prompt_hash
        else:
            prompt_hash = wrapper.sent_hashes[index]
        rows.append(
            {
                "schema": 1,
                "case_id": case.id,
                "trap": case.trap,
                "arm": arm.name,
                "model": model,
                "model_reported": attempt.model_reported,
                "effort": effort,
                "attempt": attempt.number,
                "execution": execution,
                "raw_text": attempt.raw_text,
                "parsed_ok": attempt.parsed_ok,
                "blocked": attempt.blocked,
                "codes": [list(pair) for pair in attempt.codes],
                "latency_ms": attempt.latency_ms,
                "prompt_tokens": attempt.prompt_tokens,
                "completion_tokens": attempt.completion_tokens,
                "reasoning_tokens": attempt.reasoning_tokens,
                "cached_tokens": attempt.cached_tokens,
                "finish_reason": attempt.finish_reason,
                "prompt_hash": prompt_hash,
                "cases_sha256": cases_sha256,
                "gate_commit": gate_commit,
                "gate_hash": gate_hash,
                "transport": attempt.transport,
                "muse_version": attempt.transport_version,
                "harness_rules_file": attempt.harness_rules_file,
                "recorded_at": recorded,
            }
        )
    finished = _execution_complete(rows)
    return rows, finished


# Run loop --------------------------------------------------------------------


def _stop_due(stop_time: datetime | None) -> bool:
    return stop_time is not None and datetime.now(UTC) >= stop_time


def run_selection(
    *,
    cases: list[R1bCase],
    arms: list[ArmSpec],
    model: str,
    effort: str,
    route: str,
    results_dir: Path,
    concurrency: int,
    limit: int | None,
    stop_time: datetime | None,
    paired_prefix: bool,
    registry: tuple[ArmSpec, ...],
    client_factory: Any,
    gate_commit: str,
    gate_hash: str,
    cases_sha256: str,
    cases_path: Path,
) -> int:
    """Run the selection; return 0, or 3 after 3 unavailable executions."""
    _ = registry
    _ = cases_path
    if concurrency < 1:
        raise Refusal("concurrency below 1")
    if route == "local" and concurrency != 1:
        raise Refusal("local concurrency is 1")
    if limit is not None:
        cases = cases[:limit]
    results_dir.mkdir(parents=True, exist_ok=True)
    seen_stems: dict[str, tuple[str, str, str]] = {}
    for arm in arms:
        stem = (
            f"{_sanitise_name(model)}__{_sanitise_name(effort)}"
            f"__{_sanitise_name(arm.name)}__{gate_hash[:12]}"
        )
        identity = (model, effort, arm.name)
        if stem in seen_stems and seen_stems[stem] != identity:
            raise Refusal("result name collision")
        seen_stems[stem] = identity
    existing = read_result_rows(results_dir)
    done = finished_identities(existing)
    todo = [
        case
        for case in cases
        if not all(
            (
                case.id,
                arm.name,
                model,
                effort,
                gate_commit,
                gate_hash,
                cases_sha256,
            )
            in done
            for arm in arms
        )
    ]
    next_numbers = _next_executions(
        existing, todo, arms, model, effort, gate_commit, gate_hash, cases_sha256
    )
    lock = threading.Lock()
    stop = threading.Event()
    stopped_for_unavailable = threading.Event()
    unavailable_streak = 0
    ran = 0
    base_client = client_factory(route)

    def _append(path: Path, rows: list[dict[str, Any]]) -> None:
        with lock, path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def _run_one(case: R1bCase) -> None:
        nonlocal unavailable_streak, ran
        for arm in arms:
            if (
                case.id,
                arm.name,
                model,
                effort,
                gate_commit,
                gate_hash,
                cases_sha256,
            ) in done:
                continue
            if stop.is_set() or _stop_due(stop_time):
                stop.set()
                return
            rows, _finished = run_case_arm(
                case=case,
                arm=arm,
                model=model,
                effort=effort,
                client=base_client,
                gate_commit=gate_commit,
                gate_hash=gate_hash,
                cases_sha256=cases_sha256,
                execution=next_numbers[(case.id, arm.name)],
                stop_time=stop_time,
            )
            ends_unavailable = bool(rows) and not _execution_complete(rows)
            _append(
                results_path(results_dir, model, effort, arm.name, gate_hash[:12]), rows
            )
            with lock:
                ran += 1
                if ends_unavailable:
                    unavailable_streak += 1
                    if unavailable_streak >= 3:
                        stopped_for_unavailable.set()
                        stop.set()
                else:
                    unavailable_streak = 0

    if paired_prefix:
        try:
            for case in todo:
                if stop.is_set():
                    break
                _run_one(case)
                if stopped_for_unavailable.is_set():
                    break
        except ContributorModelRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
    else:
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(_run_one, todo))
        except ContributorModelRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
    remaining = len(cases) - len(todo)
    print(f"cases run: {ran}; cases already finished: {remaining}")
    if stopped_for_unavailable.is_set():
        print("stopping after 3 consecutive unavailable executions")
        return EXIT_UNAVAILABLE_STOP
    if stop.is_set():
        print("stopping at the stop time; rerun to resume")
    return EXIT_OK


# Pick ------------------------------------------------------------------------


PICK_CODES = frozenset(
    {
        "L1B_NUMBER_WITHOUT_METRIC_REF",
        "L1B_METRIC_VALUE_MISMATCH",
        "L1B_DELTA_MISMATCH",
        "L1B_UNKNOWN_METRIC",
        "L1B_DIRECTION_MISMATCH",
    }
)


def run_pick(
    *,
    rows: list[dict[str, Any]],
    cases: list[R1bCase],
    cases_sha256: str,
    gate_hash12: str,
    output_path: Path,
) -> dict[str, Any] | None:
    """Select one kept draft per D20; write it verbatim or write nothing."""
    from evals.r1b_summary import select_counted_first_attempts

    order = {case.id: index for index, case in enumerate(cases)}
    matrix_order = {(row.model, row.effort): index for index, row in enumerate(MATRIX)}
    counted = select_counted_first_attempts(
        [
            row
            for row in rows
            if not row.get("regated")
            and str(row["cases_sha256"]) == cases_sha256
            and str(row["gate_hash"])[:12] == gate_hash12
        ],
        order,
    )
    by_execution: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("regated"):
            continue
        if str(row["cases_sha256"]) != cases_sha256:
            continue
        if str(row["gate_hash"])[:12] != gate_hash12:
            continue
        key = (
            str(row["model"]),
            str(row["effort"]),
            str(row["arm"]),
            str(row["case_id"]),
            int(row["execution"]),
        )
        by_execution.setdefault(key, []).append(row)
    candidates: list[
        tuple[tuple[int, int, tuple[int, object, object], int, int], dict[str, Any]]
    ] = []
    for key, first in counted.items():
        _gate_commit, _gate_hash, model, effort, arm, case_id = key
        if not bool(first["parsed_ok"]) or bool(first["blocked"]):
            continue
        codes = [list(pair) for pair in first["codes"]]
        if not any(code in PICK_CODES for code, _location in codes):
            continue
        same = sorted(
            by_execution.get(
                (model, effort, arm, case_id, int(first["execution"])), []
            ),
            key=lambda row: int(row["attempt"]),
        )
        second = next((row for row in same if int(row["attempt"]) == 2), None)
        retry_passed = (
            second is not None
            and bool(second["parsed_ok"])
            and list(second["codes"]) == []
        )
        matrix_rank: tuple[int, object, object] = (
            (0, matrix_order[(model, effort)], "")
            if (model, effort) in matrix_order
            else (1, model, effort)
        )
        sort_key = (
            0 if retry_passed else 1,
            0 if arm == "product" else 1,
            matrix_rank,
            order.get(case_id, len(order)),
            int(first["execution"]),
        )
        record = {
            "synthetic": True,
            "label": "synthetic data only",
            "model": model,
            "effort": effort,
            "arm": arm,
            "case_id": case_id,
            "trap": first["trap"],
            "gate_commit": str(first["gate_commit"]),
            "gate_hash": str(first["gate_hash"]),
            "draft_text": str(first["raw_text"]),
            "codes": codes,
            "retry_text": str(second["raw_text"]) if second is not None else None,
            "retry_passed": retry_passed,
        }
        candidates.append((sort_key, record))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    picked = candidates[0][1]
    output_path.write_text(json.dumps(picked, indent=2) + "\n", encoding="utf-8")
    return picked


# CLI --------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals.r1b")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--arm", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--pick-rejection", action="store_true")
    parser.add_argument("--gate-identity", default=None)
    parser.add_argument("--regate", action="store_true")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stop-time", default=None)
    parser.add_argument("--paired-prefix", action="store_true")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    return parser.parse_args(argv)


def _parse_stop_time(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        raise Refusal("bad stop time") from None
    if instant.tzinfo is None:
        raise Refusal("bad stop time")
    return instant


def _refuse_contributor(model: str) -> None:
    try:
        refuse_contributor_model(model)
    except ContributorModelRefused as exc:
        raise Refusal(str(exc) or "contributor models are refused") from None


def _evidence_checks(route: str) -> Any:
    if route == "muse":
        if os.environ.get("META_API_KEY", ""):
            raise Refusal("META_API_KEY is set")
        if os.environ.get("MUSE_NO_AUTO_UPDATE") != "1":
            raise Refusal("MUSE_NO_AUTO_UPDATE is not 1")
        return None
    from framework.glimmer.llm import load_llm_config, sanitise_model_id

    try:
        config = load_llm_config()
    except SystemExit as exc:
        raise Refusal(f"local config: {exc}") from None
    if sanitise_model_id(config.model) != "muse-glimmer-30b":
        raise Refusal("local model is not muse-glimmer-30b")
    return config


def _route_for(model: str) -> str:
    from framework.glimmer.llm import sanitise_model_id

    if sanitise_model_id(model) == "muse-glimmer-30b":
        return "local"
    return "muse"


def _run_single_row(
    *,
    model: str,
    effort: str,
    arm_name: str | None,
    cases_path: Path,
    results_dir: Path,
    concurrency: int | None,
    limit: int | None,
    stop_time: datetime | None,
    paired_prefix: bool,
    registry: tuple[ArmSpec, ...],
    client_factory: Any,
    llm_config: Any = None,
) -> int:
    # The local route and --paired-prefix always run the product and plain
    # arms back to back per case in file order, whatever --arm says.
    paired = paired_prefix or _route_for(model) == "local"
    if paired:
        return _run_row_arms(
            model=model,
            effort=effort,
            arm_names=[spec.name for spec in registry],
            cases_path=cases_path,
            results_dir=results_dir,
            concurrency=1 if _route_for(model) != "local" else concurrency,
            limit=limit,
            stop_time=stop_time,
            paired_prefix=True,
            registry=registry,
            client_factory=client_factory,
            llm_config=llm_config,
        )
    if arm_name is None:
        raise Refusal("need --model, --effort and --arm, or --all")
    return _run_row_arms(
        model=model,
        effort=effort,
        arm_names=[arm_name],
        cases_path=cases_path,
        results_dir=results_dir,
        concurrency=concurrency,
        limit=limit,
        stop_time=stop_time,
        paired_prefix=False,
        registry=registry,
        client_factory=client_factory,
        llm_config=llm_config,
    )


def _run_row_arms(
    *,
    model: str,
    effort: str,
    arm_names: list[str],
    cases_path: Path,
    results_dir: Path,
    concurrency: int | None,
    limit: int | None,
    stop_time: datetime | None,
    paired_prefix: bool,
    registry: tuple[ArmSpec, ...],
    client_factory: Any,
    llm_config: Any = None,
) -> int:
    arms = [resolve_arm(arm_name, registry) for arm_name in arm_names]
    _refuse_contributor(model)
    route = _route_for(model)
    if route == "local":
        if effort != "none":
            raise Refusal("local effort is none")
    elif effort not in EFFORTS:
        raise Refusal("unknown effort")
    if os.environ.get("IKIGAI_R1B_LIVE") != "1":
        raise Refusal("IKIGAI_R1B_LIVE is not 1")
    if llm_config is None:
        llm_config = _evidence_checks(route)
    elif route == "muse":
        _evidence_checks(route)
    try:
        gate_commit, gate_hash = gate_identity()
    except GateIdentityError as exc:
        raise Refusal(str(exc)) from None
    cases_sha = check_cases_hash(cases_path)
    cases = list(load_cases(cases_path))
    if route == "local":
        concurrency_value = 1
        if concurrency is not None and concurrency != 1:
            raise Refusal("local concurrency is 1")
        paired_prefix = True
    else:
        concurrency_value = concurrency if concurrency is not None else 4
    factory = client_factory or build_base_client

    def _one(route_name: str) -> WonderClient:
        if llm_config is None:
            return factory(route_name)
        return factory(route_name, llm_config)

    return run_selection(
        cases=cases,
        arms=arms,
        model=model,
        effort=effort,
        route=route,
        results_dir=results_dir,
        concurrency=concurrency_value,
        limit=limit,
        stop_time=stop_time,
        paired_prefix=paired_prefix,
        registry=registry,
        client_factory=_one,
        gate_commit=gate_commit,
        gate_hash=gate_hash,
        cases_sha256=cases_sha,
        cases_path=cases_path,
    )


def _run_all(
    *,
    cases_path: Path,
    results_dir: Path,
    limit: int | None,
    stop_time: datetime | None,
    client_factory: Any,
) -> int:
    if os.environ.get("IKIGAI_R1B_LIVE") != "1":
        raise Refusal("IKIGAI_R1B_LIVE is not 1")
    local_vars = [key for key in os.environ if key.startswith("LOCAL_LLM_")]
    llm_config = None
    local_wanted = bool(local_vars)
    if local_wanted:
        from framework.glimmer.llm import load_llm_config, sanitise_model_id

        try:
            llm_config = load_llm_config()
        except SystemExit as exc:
            raise Refusal(f"local config: {exc}") from None
        if sanitise_model_id(llm_config.model) != "muse-glimmer-30b":
            raise Refusal("local model is not muse-glimmer-30b")
        for key in local_vars:
            del os.environ[key]
    factory = client_factory or build_base_client
    code = EXIT_OK
    not_started: list[str] = []
    for entry in MATRIX:
        if entry.route == "local":
            if local_wanted:
                not_started.append(f"{entry.model} ({entry.effort})")
        else:
            for arm_name in ("product", "plain"):
                not_started.append(f"{entry.model} ({entry.effort}) arm {arm_name}")
    for entry in MATRIX:
        if entry.route == "local":
            if not local_wanted:
                print("local row was not run")
                continue
            print(f"row: {entry.model} ({entry.effort})")
            not_started.remove(f"{entry.model} ({entry.effort})")
            local_factory = lambda route_name, _config=None: factory(
                route_name, _config if _config is not None else llm_config
            )
            row_code = _run_row_arms(
                model=entry.model,
                effort=entry.effort,
                arm_names=["product", "plain"],
                cases_path=cases_path,
                results_dir=results_dir,
                concurrency=1,
                limit=limit,
                stop_time=stop_time,
                paired_prefix=True,
                registry=ARM_REGISTRY,
                client_factory=local_factory,
                llm_config=llm_config,
            )
            code = max(code, row_code)
            if row_code == EXIT_UNAVAILABLE_STOP:
                print(
                    "stopping the whole run after 3 consecutive unavailable "
                    f"executions; rows that did not start: "
                    f"{', '.join(not_started) or 'none'}"
                )
                return EXIT_UNAVAILABLE_STOP
            continue
        muse_factory = lambda route_name, _config=None: factory(route_name, _config)
        for arm_name in ("product", "plain"):
            print(f"row: {entry.model} ({entry.effort}) arm {arm_name}")
            not_started.remove(f"{entry.model} ({entry.effort}) arm {arm_name}")
            row_code = _run_single_row(
                model=entry.model,
                effort=entry.effort,
                arm_name=arm_name,
                cases_path=cases_path,
                results_dir=results_dir,
                concurrency=entry.concurrency,
                limit=limit,
                stop_time=stop_time,
                paired_prefix=False,
                registry=ARM_REGISTRY,
                client_factory=muse_factory,
            )
            code = max(code, row_code)
            if row_code == EXIT_UNAVAILABLE_STOP:
                print(
                    "stopping the whole run after 3 consecutive unavailable "
                    f"executions; rows that did not start: "
                    f"{', '.join(not_started) or 'none'}"
                )
                return EXIT_UNAVAILABLE_STOP
    return code


def _run_summary(*, cases_path: Path, results_dir: Path) -> int:
    from evals.r1b_summary import render_summary

    rows = read_result_rows(results_dir, include_regated=True)
    if rows:
        require_cases_file_for_results(cases_path, results_dir)
    cases = list(load_cases(cases_path)) if cases_path.exists() else []
    if rows and not cases:
        raise Refusal("case-file-missing: result rows without cases")
    text = render_summary(rows, cases, arm_order=[spec.name for spec in ARM_REGISTRY])
    DOC_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {DOC_PATH}")
    return EXIT_OK


def _run_pick_command(
    *,
    cases_path: Path,
    results_dir: Path,
    gate_identity12: str | None,
    output_path: Path,
) -> int:
    if gate_identity12 is not None:
        gate12 = gate_identity12
    else:
        try:
            _commit, gate_hash = gate_identity()
        except GateIdentityError as exc:
            raise Refusal(str(exc)) from None
        gate12 = gate_hash[:12]
    rows = read_result_rows(results_dir)
    cases = list(load_cases(cases_path))
    cases_sha = cases_sha256(cases_path)
    picked = run_pick(
        rows=rows,
        cases=cases,
        cases_sha256=cases_sha,
        gate_hash12=gate12,
        output_path=output_path,
    )
    if picked is None:
        print("no qualifying rejection")
        return EXIT_OK
    print(f"kept {picked['model']} ({picked['arm']}) {picked['case_id']}")
    return EXIT_OK


def _run_regate(*, cases_path: Path, results_dir: Path) -> int:
    from evals.r1b_summary import select_counted_first_attempts

    try:
        gate_commit, gate_hash = gate_identity()
    except GateIdentityError as exc:
        raise Refusal(str(exc)) from None
    cases = list(load_cases(cases_path))
    order = {case.id: index for index, case in enumerate(cases)}
    by_id = {case.id: case for case in cases}
    cases_sha = check_cases_hash(cases_path)
    rows = read_result_rows(results_dir)
    live = [row for row in rows if not row.get("regated")]
    counted = select_counted_first_attempts(
        [row for row in live if str(row["cases_sha256"]) == cases_sha], order
    )
    out_path = results_dir / f"regate__{gate_hash[:12]}.jsonl"
    already: set[tuple[str, ...]] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stored = json.loads(line)
            already.add(
                (
                    str(stored["orig_gate_commit"]),
                    str(stored["orig_gate_hash"]),
                    str(stored["model"]),
                    str(stored["effort"]),
                    str(stored["arm"]),
                    str(stored["case_id"]),
                    str(stored["execution"]),
                    str(stored["cases_sha256"]),
                )
            )
    appended = 0
    with out_path.open("a", encoding="utf-8") as handle:
        for _key, first in sorted(counted.items()):
            fingerprint = (
                str(first["gate_commit"]),
                str(first["gate_hash"]),
                str(first["model"]),
                str(first["effort"]),
                str(first["arm"]),
                str(first["case_id"]),
                str(first["execution"]),
                str(first["cases_sha256"]),
            )
            if fingerprint in already:
                continue
            already.add(fingerprint)
            case = by_id.get(str(first["case_id"]))
            if case is None:
                continue
            context = build_case_context(case)
            hour = build_case_hour(case)
            slot = datetime.fromisoformat(str(case.slot))
            replay = ReplayWonderClient(str(first["raw_text"]))
            model = str(first["model"])
            effort = str(first["effort"])
            result = propose(
                profile_id=case.profile,
                subject_id=SUBJECT_ID,
                slot=slot,
                as_of=slot,
                cycle_id=f"r1b-{case.id}",
                run=1,
                hour=hour,
                eligible=list(case.commitments),
                context=context,
                client=replay,
                models=ModelParams(model, effort, model, effort),
                policy="",
                stale_after_s=12 * 3600,
                cycle_as_of=slot,
                offered={},
            )
            if not result.attempts:
                continue
            recomputed = [list(pair) for pair in result.attempts[0].codes]
            record = dict(first)
            record.update(
                {
                    "regated": True,
                    "orig_gate_commit": str(first["gate_commit"]),
                    "orig_gate_hash": str(first["gate_hash"]),
                    "gate_commit": gate_commit,
                    "gate_hash": gate_hash,
                    "codes": recomputed,
                    "parsed_ok": result.attempts[0].parsed_ok,
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            )
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            appended += 1
    print(f"re-gated {appended} first drafts")
    return EXIT_OK


def main(argv: list[str] | None = None, client_factory: Any = None) -> int:
    args = _parse_args(argv)
    cases_path = Path(args.cases)
    results_dir = Path(args.results_dir)
    try:
        if args.summary:
            return _run_summary(cases_path=cases_path, results_dir=results_dir)
        if args.pick_rejection:
            return _run_pick_command(
                cases_path=cases_path,
                results_dir=results_dir,
                gate_identity12=args.gate_identity,
                output_path=DEMO_REAL_REJECTION_PATH,
            )
        if args.regate:
            return _run_regate(cases_path=cases_path, results_dir=results_dir)
        stop_time = _parse_stop_time(args.stop_time)
        if args.all:
            return _run_all(
                cases_path=cases_path,
                results_dir=results_dir,
                limit=args.limit,
                stop_time=stop_time,
                client_factory=client_factory,
            )
        if (
            not args.model
            or not args.effort
            or (
                not args.arm
                and not args.paired_prefix
                and _route_for(args.model) != "local"
            )
        ):
            print("need --model, --effort and --arm, or --all", file=sys.stderr)
            return EXIT_REFUSED
        if args.concurrency is not None and args.concurrency < 1:
            raise Refusal("concurrency below 1")
        return _run_single_row(
            model=args.model,
            effort=args.effort,
            arm_name=args.arm,
            cases_path=cases_path,
            results_dir=results_dir,
            concurrency=args.concurrency,
            limit=args.limit,
            stop_time=stop_time,
            paired_prefix=args.paired_prefix,
            registry=ARM_REGISTRY,
            client_factory=client_factory,
        )
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return exc.code
    except GateIdentityError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
