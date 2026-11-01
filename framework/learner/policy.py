"""Counting, ranking, prompt block and diff over learner states."""

import datetime
import json
from fractions import Fraction
from typing import Literal

from framework.learner.schemas import (
    BUCKETS,
    Bucket,
    BucketState,
    CommitmentState,
    PickLogEntry,
    PolicyChange,
    PolicyState,
    ProfileId,
    RankedCommitment,
    Ruling,
)
from framework.schemas.events import NonEmptyStr

_MIN_SLOT = datetime.datetime.min.replace(tzinfo=datetime.UTC)


def initial_state() -> PolicyState:
    """The Day 0 policy: prior counts, no rulings, empty logs."""
    return PolicyState(buckets={bucket: BucketState() for bucket in BUCKETS})


def bucket_for(local_time: datetime.time) -> Bucket:
    """Map wall-clock time to a bucket on half-open bounds."""
    mark = (
        local_time.hour,
        local_time.minute,
        local_time.second,
        local_time.microsecond,
    )
    if (13, 0, 0, 0) <= mark < (17, 0, 0, 0):
        return "afternoon"
    if (17, 0, 0, 0) <= mark < (21, 0, 0, 0):
        return "evening"
    if (21, 0, 0, 0) <= mark < (23, 30, 0, 0):
        return "night"
    raise ValueError(f"time {local_time!s} sits in no bucket")


def state_json(state: PolicyState) -> str:
    """Canonical bytes for one state, on any platform."""
    return json.dumps(
        state.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def _pick_entries(ruling: Ruling) -> tuple[PickLogEntry, ...]:
    return tuple(
        PickLogEntry(
            card_id=ruling.card_id,
            slot=ruling.slot,
            bucket=ruling.bucket,
            profile_id=proposal.profile_id,
            label=proposal.label,
            offered=proposal.commitment_id,
            pick=proposal.policy_pick,
            alternative=proposal.policy_alternative,
        )
        for proposal in ruling.proposals
    )


def update(state: PolicyState, ruling: Ruling) -> PolicyState:
    """Fold one ruling into a new state; the input is never mutated."""
    for proposal in ruling.proposals:
        record = state.commitments.get(proposal.commitment_id)
        if record is not None and record.profile_id != proposal.profile_id:
            raise ValueError(
                f"commitment {proposal.commitment_id} sits under another profile"
            )
    seen = ruling.card_id in state.cards
    if seen:
        logged = tuple(e for e in state.pick_log if e.card_id == ruling.card_id)
        if logged != _pick_entries(ruling):
            raise ValueError(f"ruling on {ruling.card_id} describes another card")

    buckets = dict(state.buckets)
    commitments = dict(state.commitments)
    cards = dict(state.cards)
    pick_log = state.pick_log
    duplicates = state.duplicates

    if not seen:
        for proposal in ruling.proposals:
            record = commitments.get(proposal.commitment_id)
            if record is None:
                commitments[proposal.commitment_id] = CommitmentState(
                    profile_id=proposal.profile_id,
                    offered=1,
                    taken=0,
                    declined=0,
                    last_offered_slot=ruling.slot,
                )
            else:
                latest = max(ruling.slot, record.last_offered_slot)
                commitments[proposal.commitment_id] = record.model_copy(
                    update={"offered": record.offered + 1, "last_offered_slot": latest}
                )
        pick_log = pick_log + _pick_entries(ruling)
        cards[ruling.card_id] = None

    bucket_state = buckets[ruling.bucket]
    decided = cards[ruling.card_id]
    target = ruling.target
    if target in ("A", "B"):
        if len(ruling.proposals) == 2 and decided is None:
            chosen = next(p for p in ruling.proposals if p.label == target)
            other = next(p for p in ruling.proposals if p.label != target)
            taken_record = commitments[chosen.commitment_id]
            commitments[chosen.commitment_id] = taken_record.model_copy(
                update={"taken": taken_record.taken + 1}
            )
            declined_record = commitments[other.commitment_id]
            commitments[other.commitment_id] = declined_record.model_copy(
                update={"declined": declined_record.declined + 1}
            )
            if chosen.profile_id == "builder":
                bucket_state = bucket_state.model_copy(
                    update={"alpha": bucket_state.alpha + 1}
                )
            else:
                bucket_state = bucket_state.model_copy(
                    update={"beta": bucket_state.beta + 1}
                )
            cards[ruling.card_id] = target
        elif len(ruling.proposals) == 1 and target == "A" and decided is None:
            only = ruling.proposals[0]
            taken_record = commitments[only.commitment_id]
            commitments[only.commitment_id] = taken_record.model_copy(
                update={"taken": taken_record.taken + 1}
            )
            bucket_state = bucket_state.model_copy(
                update={"single_taken": bucket_state.single_taken + 1}
            )
            cards[ruling.card_id] = "A"
        elif decided is not None:
            duplicates += 1
    elif target == "neither":
        if decided is None:
            for proposal in ruling.proposals:
                record = commitments[proposal.commitment_id]
                commitments[proposal.commitment_id] = record.model_copy(
                    update={"declined": record.declined + 1}
                )
            bucket_state = bucket_state.model_copy(
                update={"neither": bucket_state.neither + 1}
            )
            cards[ruling.card_id] = "neither"
        else:
            duplicates += 1
    elif target == "wrong":
        bucket_state = bucket_state.model_copy(update={"wrong": bucket_state.wrong + 1})
    else:
        bucket_state = bucket_state.model_copy(update={"why": bucket_state.why + 1})
    buckets[ruling.bucket] = bucket_state

    return state.model_copy(
        update={
            "rulings_seen": state.rulings_seen + 1,
            "duplicates": duplicates,
            "buckets": buckets,
            "commitments": commitments,
            "cards": cards,
            "pick_log": pick_log,
        }
    )


def rank_commitments(
    state: PolicyState,
    profile: ProfileId,
    candidates: tuple[NonEmptyStr, ...],
    bucket: Bucket,
) -> tuple[RankedCommitment, ...]:
    """Order candidates by smoothed taken rate, then recency, then id."""
    if len(set(candidates)) != len(candidates):
        raise ValueError("candidates hold a duplicate")
    if len(candidates) == 0:
        return ()
    for candidate in candidates:
        record = state.commitments.get(candidate)
        if record is not None and record.profile_id != profile:
            raise ValueError(f"candidate {candidate} sits under another profile")

    rows: list[
        tuple[Fraction, datetime.datetime | None, NonEmptyStr, int, int, int]
    ] = []
    for candidate in candidates:
        record = state.commitments.get(candidate)
        if record is None:
            taken, offered, declined = 0, 0, 0
            last: datetime.datetime | None = None
        else:
            taken, offered, declined = record.taken, record.offered, record.declined
            last = record.last_offered_slot
        rows.append(
            (
                Fraction(taken + 1, offered + 2),
                last,
                candidate,
                taken,
                offered,
                declined,
            )
        )

    def _sort_key(
        row: tuple[Fraction, datetime.datetime | None, NonEmptyStr, int, int, int],
    ) -> tuple[Fraction, int, datetime.datetime, NonEmptyStr]:
        rate, slot, name, _, _, _ = row
        if slot is None:
            return (-rate, 0, _MIN_SLOT, name)
        return (-rate, 1, slot, name)

    ordered = sorted(rows, key=_sort_key)
    ranked: list[RankedCommitment] = []
    total = len(ordered)
    for index, row in enumerate(ordered):
        rate, last_seen, candidate, taken, offered, declined = row
        position = index + 1
        role: Literal["pick", "alternative", "other"] = (
            "pick" if position == 1 else ("alternative" if position == 2 else "other")
        )
        if total == 1:
            reason = f"only candidate: {rate}"
        elif position == total:
            reason = f"lowest of the candidates: {rate}"
        else:
            next_rate, next_last, next_id, _, _, _ = ordered[index + 1]
            if rate > next_rate:
                reason = f"higher smoothed taken rate: {rate} over {next_rate}"
            elif last_seen != next_last:
                reason = f"tied at {rate} with {next_id}: less recently offered"
            else:
                reason = (
                    f"tied at {rate} with {next_id}: same last-offered slot, lower id"
                )
        ranked.append(
            RankedCommitment(
                commitment_id=candidate,
                position=position,
                role=role,
                profile_id=profile,
                bucket=bucket,
                offered=offered,
                taken=taken,
                declined=declined,
                smoothed_rate=float(rate),
                reason=reason,
            )
        )
    return tuple(ranked)


def policy_block(
    state: PolicyState, bucket: Bucket, candidates: tuple[NonEmptyStr, ...]
) -> str:
    """One deterministic compact JSON string of numbers and ids only."""
    profiles: set[ProfileId] = {
        state.commitments[candidate].profile_id
        for candidate in candidates
        if candidate in state.commitments
    }
    if len(profiles) > 1:
        raise ValueError("candidates span two profiles")
    profile: ProfileId = next(iter(profiles)) if profiles else "builder"
    ranked = rank_commitments(state, profile, candidates, bucket)
    bucket_state = state.buckets[bucket]
    block = {
        "bucket": {
            "builder_taken": bucket_state.alpha - 1,
            "disconnect_taken": bucket_state.beta - 1,
            "neither": bucket_state.neither,
            "wrong": bucket_state.wrong,
            "why": bucket_state.why,
            "posterior_mean": round(
                bucket_state.alpha / (bucket_state.alpha + bucket_state.beta), 3
            ),
        },
        "candidates": [
            {
                "id": entry.commitment_id,
                "rank": entry.position,
                "offered": entry.offered,
                "taken": entry.taken,
                "declined": entry.declined,
            }
            for entry in ranked
        ],
    }
    return json.dumps(block, sort_keys=True, separators=(",", ":"))


JsonLeaf = str | float | int | bool | None
JsonValue = dict[str, "JsonValue"] | list["JsonValue"] | JsonLeaf


def _flatten(value: JsonValue, prefix: str, out: dict[str, JsonLeaf]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(item, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(item, f"{prefix}[{index}]", out)
    else:
        out[prefix] = value


def policy_diff(a: PolicyState, b: PolicyState) -> tuple[PolicyChange, ...]:
    """Exact leaf differences between two states, sorted by path."""
    flat_a: dict[str, JsonLeaf] = {}
    flat_b: dict[str, JsonLeaf] = {}
    _flatten(json.loads(state_json(a)), "", flat_a)
    _flatten(json.loads(state_json(b)), "", flat_b)
    changes: list[PolicyChange] = []
    for path in sorted(set(flat_a) | set(flat_b)):
        if path not in flat_a:
            changes.append(
                PolicyChange(path=path, kind="added", before=None, after=flat_b[path])
            )
        elif path not in flat_b:
            changes.append(
                PolicyChange(path=path, kind="removed", before=flat_a[path], after=None)
            )
        elif flat_a[path] != flat_b[path]:
            changes.append(
                PolicyChange(
                    path=path,
                    kind="changed",
                    before=flat_a[path],
                    after=flat_b[path],
                )
            )
    return tuple(changes)
