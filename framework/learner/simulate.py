"""Known-preference simulation through the real update."""

import datetime
import math
import random

from framework.learner.beta import credible_interval
from framework.learner.policy import initial_state, update
from framework.learner.schemas import Proposal, RecoverCell, RecoverTable, Ruling

NOTE = (
    "n_cards is the number of real two-proposal choices fed to one posterior. "
    "Cards with one proposal, and neither, wrong or why taps, add none. "
    "My live run expects about 13 cards over three days, and Disconnect appears "
    "at 15:30, 20:30 and 22:30, so at most about 7 of them can be real "
    "choices, 2 or 3 per time bucket. A live bucket's posterior will hold about "
    "3 choices, so even the n = 5 row is optimistic for it. The n = 13 row is an "
    "upper bound on the pooled reading, available only if the preference does "
    "not vary by bucket."
)

_DAY_ONE = datetime.datetime(2026, 1, 1, 18, 0, tzinfo=datetime.UTC)


def _sim_rulings(n_cards: int) -> tuple[tuple[Ruling, Ruling], ...]:
    """Both target variants per card, built once and reused across sims."""
    pairs: list[tuple[Ruling, Ruling]] = []
    for position in range(1, n_cards + 1):
        slot = _DAY_ONE + datetime.timedelta(days=position - 1)
        proposals = (
            Proposal(
                label="A",
                profile_id="builder",
                commitment_id="sim-builder",
                policy_pick="sim-builder",
                policy_alternative=None,
            ),
            Proposal(
                label="B",
                profile_id="disconnect",
                commitment_id="sim-disconnect",
                policy_pick="sim-disconnect",
                policy_alternative=None,
            ),
        )
        pairs.append(
            (
                Ruling(
                    card_id=f"card-{position:03d}",
                    slot=slot,
                    bucket="evening",
                    proposals=proposals,
                    target="A",
                ),
                Ruling(
                    card_id=f"card-{position:03d}",
                    slot=slot,
                    bucket="evening",
                    proposals=proposals,
                    target="B",
                ),
            )
        )
    return tuple(pairs)


def recover(true_p: float, n_cards: int, n_sims: int, seed: int) -> RecoverCell:
    """Feed simulated rulings at true_p through update; report four numbers."""
    if not 0.0 < true_p < 1.0:
        raise ValueError("true_p must sit strictly inside (0, 1)")
    if n_cards < 1:
        raise ValueError("n_cards must be at least 1")
    if n_sims < 1:
        raise ValueError("n_sims must be at least 1")
    pairs = _sim_rulings(n_cards)
    rng = random.Random(f"{seed}:{true_p}:{n_cards}")
    side_hits = 0
    covered = 0
    errors: list[float] = []
    widths: list[float] = []
    for _ in range(n_sims):
        takes_builder = [rng.random() < true_p for _ in range(n_cards)]
        state = initial_state()
        for take, (take_a, take_b) in zip(takes_builder, pairs):
            state = update(state, take_a if take else take_b)
        bucket_state = state.buckets["evening"]
        mean = bucket_state.alpha / (bucket_state.alpha + bucket_state.beta)
        lo, hi = credible_interval(bucket_state.alpha, bucket_state.beta)
        if (true_p > 0.5 and mean > 0.5) or (true_p < 0.5 and mean < 0.5):
            side_hits += 1
        errors.append(abs(mean - true_p))
        if lo <= true_p <= hi:
            covered += 1
        widths.append(hi - lo)
    return RecoverCell(
        true_p=true_p,
        n_cards=n_cards,
        n_sims=n_sims,
        seed=seed,
        correct_side=(None if true_p == 0.5 else side_hits / n_sims),
        mean_absolute_error=math.fsum(errors) / n_sims,
        coverage=covered / n_sims,
        mean_interval_width=math.fsum(widths) / n_sims,
    )


def recover_table(
    seed: int,
    n_sims: int,
    true_ps: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9),
    n_cards: tuple[int, ...] = (5, 13, 30, 100),
) -> RecoverTable:
    """One recover per grid point, true_p outer and n_cards inner."""
    cells = tuple(
        recover(true_p, n, n_sims, seed) for true_p in true_ps for n in n_cards
    )
    return RecoverTable(seed=seed, n_sims=n_sims, note=NOTE, cells=cells)
