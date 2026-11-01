"""Ticket 15a: counting table, buckets, labels, ranking, block, diff."""

import datetime
from datetime import UTC, timezone
from datetime import datetime as _datetime
from typing import Literal
from zoneinfo import ZoneInfo

import pytest

from framework.learner.policy import (
    bucket_for,
    initial_state,
    policy_block,
    policy_diff,
    rank_commitments,
    state_json,
    update,
)
from framework.learner.schemas import (
    Bucket,
    PolicyState,
    ProfileId,
    Proposal,
    Ruling,
    Target,
)

SLOT = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)


def _prop(label: Literal["A", "B"], profile: ProfileId, commitment: str) -> Proposal:
    return Proposal(
        label=label,
        profile_id=profile,
        commitment_id=commitment,
        policy_pick=commitment,
        policy_alternative=None,
    )


def _two_card(
    card: str = "card-001",
    slot: _datetime = SLOT,
    bucket: Bucket = "evening",
    target: Target = "A",
    swap: bool = False,
) -> Ruling:
    if swap:
        proposals = (_prop("A", "disconnect", "d-1"), _prop("B", "builder", "b-1"))
    else:
        proposals = (_prop("A", "builder", "b-1"), _prop("B", "disconnect", "d-1"))
    return Ruling(
        card_id=card,
        slot=slot,
        bucket=bucket,
        proposals=proposals,
        target=target,
    )


def _lone_card(target: Target = "A") -> Ruling:
    return Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=(_prop("A", "builder", "b-1"),),
        target=target,
    )


def test_initial_state_day_zero() -> None:
    s = initial_state()
    assert s.preference == "builder_over_disconnect"
    assert s.rulings_seen == 0
    assert s.duplicates == 0
    assert set(s.buckets) == {"afternoon", "evening", "night"}
    assert s.commitments == {}
    assert s.cards == {}
    assert s.score_log == ()
    assert s.pick_log == ()


def test_counting_first_sighting_decisive() -> None:
    after = update(initial_state(), _two_card())
    assert after.rulings_seen == 1
    assert after.commitments["b-1"].offered == 1
    assert after.commitments["d-1"].offered == 1
    assert after.commitments["b-1"].last_offered_slot == SLOT
    assert len(after.pick_log) == 2
    assert after.cards == {"card-001": "A"}


def test_counting_first_sighting_case_records_slot() -> None:
    slot = _datetime(2026, 1, 3, 19, 30, tzinfo=UTC)
    after = update(initial_state(), _two_card(slot=slot))
    assert after.commitments["b-1"].last_offered_slot == slot
    assert after.commitments["d-1"].last_offered_slot == slot


def test_counting_decisive_a_moves_alpha() -> None:
    after = update(initial_state(), _two_card(target="A"))
    assert after.buckets["evening"].alpha == 2
    assert after.buckets["evening"].beta == 1
    assert after.commitments["b-1"].taken == 1
    assert after.commitments["d-1"].declined == 1


def test_counting_decisive_b_moves_beta() -> None:
    after = update(initial_state(), _two_card(target="B"))
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 2
    assert after.commitments["d-1"].taken == 1
    assert after.commitments["b-1"].declined == 1


def test_counting_single_taken() -> None:
    after = update(initial_state(), _lone_card())
    assert after.commitments["b-1"].taken == 1
    assert after.commitments["b-1"].offered == 1
    assert after.buckets["evening"].single_taken == 1
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1
    assert after.cards == {"card-001": "A"}


def test_counting_neither() -> None:
    after = update(initial_state(), _two_card(target="neither"))
    assert after.buckets["evening"].neither == 1
    assert after.commitments["b-1"].declined == 1
    assert after.commitments["d-1"].declined == 1
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1
    assert after.cards == {"card-001": "neither"}


def test_counting_neither_on_lone_card() -> None:
    after = update(initial_state(), _lone_card(target="neither"))
    assert after.commitments["b-1"].declined == 1
    assert after.buckets["evening"].neither == 1
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1
    assert after.cards == {"card-001": "neither"}


def test_counting_lone_double_tap() -> None:
    first = update(initial_state(), _lone_card(target="A"))
    after = update(first, _lone_card(target="A"))
    assert after.commitments["b-1"].taken == 1
    assert after.buckets["evening"].single_taken == 1
    assert after.duplicates == 1


def test_counting_wrong() -> None:
    after = update(initial_state(), _two_card(target="wrong"))
    assert after.rulings_seen == 1
    assert after.buckets["evening"].wrong == 1
    assert after.commitments["b-1"].offered == 1
    assert after.commitments["b-1"].taken == 0
    assert after.cards == {"card-001": None}
    assert after.duplicates == 0
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1


def test_counting_why() -> None:
    after = update(initial_state(), _two_card(target="why"))
    assert after.rulings_seen == 1
    assert after.buckets["evening"].why == 1
    assert after.cards == {"card-001": None}
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1


def test_counting_last_offered_slot_keeps_latest_instant() -> None:
    late = _datetime(2026, 1, 3, 18, 0, tzinfo=UTC)
    early = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
    s = update(initial_state(), _pair_card("card-001", "why", "b-1", "d-1", late))
    s = update(s, _pair_card("card-002", "why", "b-1", "d-2", early))
    assert s.commitments["b-1"].last_offered_slot == late
    later = _datetime(2026, 1, 4, 18, 0, tzinfo=UTC)
    s = update(s, _pair_card("card-003", "why", "b-1", "d-3", later))
    assert s.commitments["b-1"].last_offered_slot == later


def test_counting_duplicate() -> None:
    s = update(initial_state(), _two_card(target="A"))
    before = state_json(s)
    after = update(s, _two_card(target="A"))
    assert after.rulings_seen == 2
    assert after.duplicates == 1
    assert after.buckets["evening"].alpha == 2
    assert after.commitments["b-1"].taken == 1
    assert after.commitments["b-1"].offered == 1
    assert len(after.pick_log) == len(s.pick_log)
    assert state_json(s) == before


def test_purity_of_update() -> None:
    s = update(initial_state(), _two_card(target="A"))
    before = state_json(s)
    update(s, _two_card(card="card-002", target="B"))
    assert state_json(s) == before


def test_why_then_a_offers_once_and_moves_posterior_once() -> None:
    s = update(initial_state(), _two_card(target="why"))
    after = update(s, _two_card(target="A"))
    assert after.commitments["b-1"].offered == 1
    assert after.buckets["evening"].alpha == 2
    assert after.buckets["evening"].why == 1
    assert after.duplicates == 0


def test_double_tap_moves_posterior_once() -> None:
    s = update(initial_state(), _two_card(target="A"))
    after = update(s, _two_card(target="A"))
    assert after.buckets["evening"].alpha == 2
    assert after.duplicates == 1


def test_a_then_b_keeps_first() -> None:
    s = update(initial_state(), _two_card(target="A"))
    after = update(s, _two_card(target="B"))
    assert after.buckets["evening"].alpha == 2
    assert after.buckets["evening"].beta == 1
    assert after.duplicates == 1
    assert after.cards == {"card-001": "A"}


def test_neither_then_a_is_duplicate() -> None:
    s = update(initial_state(), _two_card(target="neither"))
    after = update(s, _two_card(target="A"))
    assert after.duplicates == 1
    assert after.buckets["evening"].alpha == 1
    assert after.commitments["b-1"].taken == 0


def test_counting_a_then_neither_is_duplicate() -> None:
    s = update(initial_state(), _two_card(target="A"))
    after = update(s, _two_card(target="neither"))
    assert after.duplicates == 1
    assert after.buckets["evening"].neither == 0
    assert after.commitments["b-1"].taken == 1
    assert after.commitments["b-1"].declined == 0
    assert after.commitments["d-1"].declined == 1
    assert after.buckets["evening"].alpha == 2
    assert after.buckets["evening"].beta == 1
    assert after.cards == {"card-001": "A"}


def test_two_profiles_for_one_commitment_raise() -> None:
    s = update(initial_state(), _two_card())
    before = state_json(s)
    bad = Ruling(
        card_id="card-002",
        slot=SLOT,
        bucket="evening",
        proposals=(
            _prop("A", "disconnect", "b-1"),
            _prop("B", "builder", "b-2"),
        ),
        target="A",
    )
    with pytest.raises(ValueError):
        update(s, bad)
    assert state_json(s) == before
    assert s.rulings_seen == 1


def test_card_mismatch_slot_raises() -> None:
    s = update(initial_state(), _two_card())
    other_slot = _datetime(2026, 1, 4, 18, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        update(s, _two_card(slot=other_slot, target="why"))
    assert s.rulings_seen == 1


def test_card_mismatch_bucket_raises() -> None:
    s = update(initial_state(), _two_card())
    with pytest.raises(ValueError):
        update(s, _two_card(bucket="night", target="why"))
    assert s.rulings_seen == 1


def test_card_mismatch_proposals_raise() -> None:
    s = update(initial_state(), _two_card())
    changed = Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=(
            _prop("A", "builder", "b-1"),
            _prop("B", "disconnect", "d-2"),
        ),
        target="why",
    )
    with pytest.raises(ValueError):
        update(s, changed)
    assert s.rulings_seen == 1


def test_card_mismatch_label_swap_raises() -> None:
    s = update(initial_state(), _two_card(target="why"))
    before = state_json(s)
    swapped = Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=(
            _prop("B", "builder", "b-1"),
            _prop("A", "disconnect", "d-1"),
        ),
        target="A",
    )
    with pytest.raises(ValueError):
        update(s, swapped)
    assert state_json(s) == before
    assert s.buckets["evening"].alpha == 1
    assert s.buckets["evening"].beta == 1


def test_card_same_instant_other_offset_is_the_same_card() -> None:
    madrid = ZoneInfo("Europe/Madrid")
    first_slot = _datetime(2026, 11, 2, 13, 30, tzinfo=madrid)
    s = update(initial_state(), _two_card(slot=first_slot, target="why"))
    s = PolicyState.model_validate_json(state_json(s))
    same_instant_utc = _datetime(2026, 11, 2, 12, 30, tzinfo=UTC)
    assert same_instant_utc == first_slot
    after = update(s, _two_card(slot=same_instant_utc, target="A"))
    assert after.buckets["evening"].alpha == 2


def test_decided_wrong_adds_bucket_count_only() -> None:
    s = update(initial_state(), _two_card(target="A"))
    after = update(s, _two_card(target="wrong"))
    assert after.buckets["evening"].wrong == 1
    assert after.duplicates == 0
    assert after.rulings_seen == 2


def test_decided_why_adds_bucket_count_only() -> None:
    s = update(initial_state(), _two_card(target="A"))
    after = update(s, _two_card(target="why"))
    assert after.buckets["evening"].why == 1
    assert after.duplicates == 0


def test_bucket_bounds() -> None:
    assert bucket_for(datetime.time(13, 0)) == "afternoon"
    assert bucket_for(datetime.time(16, 59)) == "afternoon"
    assert bucket_for(datetime.time(16, 59, 59)) == "afternoon"
    assert bucket_for(datetime.time(17, 0)) == "evening"
    assert bucket_for(datetime.time(20, 59)) == "evening"
    assert bucket_for(datetime.time(21, 0)) == "night"
    assert bucket_for(datetime.time(23, 29)) == "night"
    with pytest.raises(ValueError):
        bucket_for(datetime.time(12, 59))
    with pytest.raises(ValueError):
        bucket_for(datetime.time(23, 30))
    with pytest.raises(ValueError):
        bucket_for(datetime.time(0, 0))


def test_bucket_tz_carrying_time_reads_wall_clock() -> None:
    tz = timezone(datetime.timedelta(hours=1))
    assert bucket_for(datetime.time(18, 0, tzinfo=tz)) == "evening"
    assert (
        bucket_for(datetime.time(13, 30, tzinfo=ZoneInfo("Europe/Madrid")))
        == "afternoon"
    )


def test_label_is_data_lone_disconnect() -> None:
    lone = Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=(_prop("A", "disconnect", "d-1"),),
        target="A",
    )
    after = update(initial_state(), lone)
    assert after.commitments["d-1"].taken == 1
    assert after.buckets["evening"].alpha == 1
    assert after.buckets["evening"].beta == 1
    assert after.buckets["evening"].single_taken == 1


def test_disconnect_first_two_proposal_card() -> None:
    after = update(initial_state(), _two_card(target="A", swap=True))
    assert after.buckets["evening"].beta == 2
    assert after.buckets["evening"].alpha == 1
    assert after.commitments["d-1"].taken == 1
    assert after.commitments["b-1"].declined == 1


def _pair_card(
    card: str,
    target: Target,
    b: str,
    d: str,
    slot: _datetime = SLOT,
) -> Ruling:
    return Ruling(
        card_id=card,
        slot=slot,
        bucket="evening",
        proposals=(_prop("A", "builder", b), _prop("B", "disconnect", d)),
        target=target,
    )


def _ranked_state() -> PolicyState:
    s = initial_state()
    s = update(s, _two_card(card="card-001", target="A"))
    s = update(s, _pair_card("card-002", "A", "b-2", "d-2"))
    s = update(s, _pair_card("card-003", "B", "b-2", "d-2"))
    return s


def test_rank_highest_rate_first_with_pinned_reason() -> None:
    ranked = rank_commitments(_ranked_state(), "builder", ("b-1", "b-2"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    assert ranked[0].position == 1 and ranked[0].role == "pick"
    assert ranked[1].position == 2 and ranked[1].role == "alternative"
    assert ranked[0].reason == "higher smoothed taken rate: 2/3 over 1/2"
    assert ranked[1].reason == "lowest of the candidates: 1/2"


def test_rank_tied_less_recently_offered() -> None:
    s = initial_state()
    early = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
    late = _datetime(2026, 1, 3, 18, 0, tzinfo=UTC)
    s = update(s, _pair_card("card-001", "neither", "b-1", "d-1", early))
    s = update(s, _pair_card("card-002", "neither", "b-2", "d-2", late))
    ranked = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    assert ranked[0].reason == "tied at 1/3 with b-2: less recently offered"


def test_rank_never_offered_before_offered_at_equal_rate() -> None:
    s = update(initial_state(), _two_card(card="card-001", target="A"))
    s = update(s, _two_card(card="card-002", target="B"))
    ranked = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-2", "b-1"]
    assert ranked[0].offered == 0
    assert ranked[0].reason == "tied at 1/2 with b-1: less recently offered"
    assert ranked[1].reason == "lowest of the candidates: 1/2"


def test_rank_same_instant_lower_id() -> None:
    ranked = rank_commitments(initial_state(), "builder", ("b-2", "b-1"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    assert ranked[0].reason == "tied at 1/2 with b-2: same last-offered slot, lower id"


def test_rank_offered_tie_same_instant_lower_id() -> None:
    plus_one = timezone(datetime.timedelta(hours=1))
    wall = _datetime(2026, 1, 2, 19, 0, tzinfo=plus_one)
    zulu = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
    assert wall == zulu
    s = initial_state()
    s = update(s, _pair_card("card-001", "neither", "b-1", "d-1", wall))
    s = update(s, _pair_card("card-002", "neither", "b-2", "d-2", zulu))
    ranked = rank_commitments(s, "builder", ("b-2", "b-1"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    assert ranked[0].reason == "tied at 1/3 with b-2: same last-offered slot, lower id"


def test_rank_carries_profile_and_bucket_and_bucket_changes_no_order() -> None:
    s = update(initial_state(), _two_card(card="card-001", target="A"))
    s = update(s, _two_card(card="card-002", target="B"))
    orders: list[list[str]] = []
    buckets: tuple[Bucket, ...] = ("afternoon", "evening", "night")
    for bucket in buckets:
        ranked = rank_commitments(s, "disconnect", ("d-1", "d-2"), bucket)
        assert all(r.profile_id == "disconnect" for r in ranked)
        assert all(r.bucket == bucket for r in ranked)
        orders.append([r.commitment_id for r in ranked])
    assert orders[0] == orders[1] == orders[2]


def test_rank_slots_compare_as_instants_across_offsets() -> None:
    plus_one = timezone(datetime.timedelta(hours=1))
    early_wall = _datetime(2026, 1, 2, 18, 0, tzinfo=plus_one)
    late_wall = _datetime(2026, 1, 2, 17, 30, tzinfo=UTC)
    s = initial_state()
    s = update(s, _pair_card("card-001", "neither", "b-1", "d-1", early_wall))
    s = update(s, _pair_card("card-002", "neither", "b-2", "d-2", late_wall))
    ranked = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]


def test_rank_candidate_order_changes_nothing() -> None:
    s = _ranked_state()
    first = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    second = rank_commitments(s, "builder", ("b-2", "b-1"), "evening")
    assert first == second


def test_rank_exact_fraction_ties() -> None:
    s = initial_state()
    early = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
    s = update(s, _pair_card("card-001", "neither", "b-1", "d-1", early))
    s = update(s, _pair_card("card-002", "A", "b-2", "d-2"))
    for i, card in enumerate(("card-003", "card-004", "card-005"), start=3):
        slot = _datetime(2026, 1, i, 18, 0, tzinfo=UTC)
        s = update(s, _pair_card(card, "neither", "b-2", "d-2", slot))
    ranked = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    assert ranked[0].smoothed_rate == ranked[1].smoothed_rate == 1 / 3
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    assert ranked[0].reason == "tied at 1/3 with b-2: less recently offered"


def test_rank_duplicate_candidates_raise() -> None:
    with pytest.raises(ValueError):
        rank_commitments(initial_state(), "builder", ("b-1", "b-1"), "evening")


def test_rank_wrong_profile_candidate_raises() -> None:
    s = update(initial_state(), _two_card())
    with pytest.raises(ValueError):
        rank_commitments(s, "disconnect", ("b-1",), "evening")


def test_rank_empty_returns_empty() -> None:
    assert rank_commitments(initial_state(), "builder", (), "evening") == ()


def test_rank_single_candidate_logs_pick_without_alternative() -> None:
    s = update(initial_state(), _two_card())
    ranked = rank_commitments(s, "builder", ("b-1",), "evening")
    assert ranked[0].reason == "only candidate: 2/3"
    assert s.pick_log[0].pick == "b-1"
    assert s.pick_log[0].alternative is None


def test_rank_pick_log_carries_pick_and_alternative() -> None:
    s = _ranked_state()
    ranked = rank_commitments(s, "builder", ("b-1", "b-2"), "evening")
    assert [r.commitment_id for r in ranked] == ["b-1", "b-2"]
    ruling = Ruling(
        card_id="card-010",
        slot=SLOT,
        bucket="evening",
        proposals=(
            Proposal(
                label="A",
                profile_id="builder",
                commitment_id=ranked[1].commitment_id,
                policy_pick=ranked[0].commitment_id,
                policy_alternative=ranked[1].commitment_id,
            ),
            Proposal(
                label="B",
                profile_id="disconnect",
                commitment_id="d-1",
                policy_pick="d-1",
                policy_alternative=None,
            ),
        ),
        target="A",
    )
    after = update(s, ruling)
    entry = next(
        e for e in after.pick_log if e.card_id == "card-010" and e.offered == "b-2"
    )
    assert entry.pick == "b-1"
    assert entry.alternative == "b-2"
    assert entry.label == "A"


def test_policy_block_exact_string_and_shape() -> None:
    s = update(initial_state(), _two_card())
    block = policy_block(s, "evening", ("b-1", "b-2"))
    assert block == (
        '{"bucket":{"builder_taken":1,"disconnect_taken":0,"neither":0,'
        '"posterior_mean":0.667,"why":0,"wrong":0},'
        '"candidates":[{"declined":0,"id":"b-1","offered":1,"rank":1,"taken":1},'
        '{"declined":0,"id":"b-2","offered":0,"rank":2,"taken":0}]}'
    )


def test_policy_block_same_inputs_same_bytes() -> None:
    s = update(initial_state(), _two_card())
    first = policy_block(s, "evening", ("b-1", "b-2"))
    second = policy_block(s, "evening", ("b-2", "b-1"))
    assert first == second


def test_policy_block_walk_finds_only_candidate_strings() -> None:
    import json as _json

    s = update(initial_state(), _two_card())
    parsed = _json.loads(policy_block(s, "evening", ("b-1", "b-2", "b-3")))
    seen: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            seen.append(value)
        elif isinstance(value, list):
            for item in value:
                _walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)

    _walk(parsed)
    assert seen
    assert all(v in {"b-1", "b-2", "b-3"} for v in seen)
    ids = [c["id"] for c in parsed["candidates"]]
    assert ids == ["b-1", "b-2", "b-3"]
    assert "higher smoothed" not in policy_block(s, "evening", ("b-1",))


def test_policy_block_mixed_profiles_raise() -> None:
    s = update(initial_state(), _two_card())
    with pytest.raises(ValueError):
        policy_block(s, "evening", ("b-1", "d-1"))


def _rich_state() -> PolicyState:
    slot = _datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
    night = _datetime(2026, 1, 2, 22, 0, tzinfo=UTC)
    s = initial_state()
    s = update(s, _pair_card("card-001", "A", "b-1", "d-1", slot))
    s = update(s, _pair_card("card-002", "A", "b-1", "d-1", slot))
    s = update(s, _pair_card("card-003", "A", "b-2", "d-1", slot))
    s = update(s, _pair_card("card-004", "B", "b-2", "d-1", slot))
    s = update(s, _pair_card("card-005", "neither", "b-3", "d-1", slot))
    s = update(s, _pair_card("card-006", "wrong", "b-3", "d-1", slot))
    s = update(s, _pair_card("card-006", "wrong", "b-3", "d-1", slot))
    s = update(s, _pair_card("card-007", "why", "b-3", "d-1", slot))
    s = update(s, _pair_card("card-007", "why", "b-3", "d-1", slot))
    s = update(s, _pair_card("card-007", "why", "b-3", "d-1", slot))
    night_card = Ruling(
        card_id="card-008",
        slot=night,
        bucket="night",
        proposals=(_prop("A", "builder", "b-1"), _prop("B", "disconnect", "d-1")),
        target="B",
    )
    return update(s, night_card)


def test_policy_block_rich_state_exact_strings() -> None:
    s = _rich_state()
    assert policy_block(s, "evening", ("b-3", "b-1", "b-4", "b-2")) == (
        '{"bucket":{"builder_taken":3,"disconnect_taken":1,"neither":1,'
        '"posterior_mean":0.667,"why":3,"wrong":2},"candidates":['
        '{"declined":1,"id":"b-1","offered":3,"rank":1,"taken":2},'
        '{"declined":0,"id":"b-4","offered":0,"rank":2,"taken":0},'
        '{"declined":1,"id":"b-2","offered":2,"rank":3,"taken":1},'
        '{"declined":1,"id":"b-3","offered":3,"rank":4,"taken":0}]}'
    )
    assert policy_block(s, "night", ("b-3", "b-1", "b-4", "b-2")) == (
        '{"bucket":{"builder_taken":0,"disconnect_taken":1,"neither":0,'
        '"posterior_mean":0.333,"why":0,"wrong":0},"candidates":['
        '{"declined":1,"id":"b-1","offered":3,"rank":1,"taken":2},'
        '{"declined":0,"id":"b-4","offered":0,"rank":2,"taken":0},'
        '{"declined":1,"id":"b-2","offered":2,"rank":3,"taken":1},'
        '{"declined":1,"id":"b-3","offered":3,"rank":4,"taken":0}]}'
    )
    assert '{"declined":4,"id":"d-1","offered":8,"rank":1,"taken":2}' in policy_block(
        s, "evening", ("d-1",)
    )


def test_rank_rich_state_reasons() -> None:
    ranked = rank_commitments(
        _rich_state(), "builder", ("b-3", "b-1", "b-4", "b-2"), "evening"
    )
    by_id = {r.commitment_id: r for r in ranked}
    assert [r.commitment_id for r in ranked] == ["b-1", "b-4", "b-2", "b-3"]
    assert by_id["b-1"].reason == "higher smoothed taken rate: 3/5 over 1/2"
    assert by_id["b-4"].reason == "tied at 1/2 with b-2: less recently offered"
    assert by_id["b-2"].reason == "higher smoothed taken rate: 1/2 over 1/5"
    assert by_id["b-3"].reason == "lowest of the candidates: 1/5"


def test_diff_empty_iff_equal_json() -> None:
    s = update(initial_state(), _two_card())
    assert policy_diff(s, s) == ()
    other = update(initial_state(), _two_card(target="B"))
    assert policy_diff(s, other) != ()
    assert (state_json(s) == state_json(other)) == (policy_diff(s, other) == ())


def test_diff_swap_swaps_before_after() -> None:
    s = update(initial_state(), _two_card())
    other = update(initial_state(), _two_card(target="B"))
    forward = {(c.path, c.kind, c.before, c.after) for c in policy_diff(s, other)}
    backward = {(c.path, c.kind, c.before, c.after) for c in policy_diff(other, s)}
    swapped = {
        (p, {"added": "removed", "removed": "added"}.get(k, k), a, b)
        for (p, k, b, a) in backward
    }
    assert forward == swapped


def test_diff_covers_every_changed_field() -> None:
    from framework.learner.scoring import replay

    ruling = _two_card()
    final = replay(initial_state(), [ruling, ruling])
    paths = [c.path for c in policy_diff(initial_state(), final)]
    for want in (
        "rulings_seen",
        "duplicates",
        "buckets.evening.alpha",
        "commitments.b-1.taken",
        "cards.card-001",
        "pick_log[0].pick",
        "pick_log[0].label",
        "score_log[0].learner.brier",
    ):
        assert want in paths, want
    assert paths == sorted(paths)


def test_diff_reverse_lists_removed() -> None:
    from framework.learner.scoring import replay

    final = replay(initial_state(), [_two_card()])
    flat = [
        (c.path, c.kind, c.before, c.after) for c in policy_diff(final, initial_state())
    ]
    assert ("cards.card-001", "removed", "A", None) in flat
    assert ("commitments.b-1.offered", "removed", 1, None) in flat


def test_diff_frozen_initial_against_small_state() -> None:
    other = update(initial_state(), _two_card(target="B"))
    diff = policy_diff(initial_state(), other)
    flat = [(c.path, c.kind, c.before, c.after) for c in diff]
    assert ("rulings_seen", "changed", 0, 1) in flat
    assert ("buckets.evening.beta", "changed", 1, 2) in flat
    assert ("cards.card-001", "added", None, "B") in flat
    assert ("commitments.b-1.declined", "added", None, 1) in flat
    assert ("commitments.d-1.offered", "added", None, 1) in flat
    by_path = {c.path: c for c in diff}
    assert by_path["commitments.d-1.taken"].after == 1
    assert by_path["pick_log[1].offered"].after == "d-1"
