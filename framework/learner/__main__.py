"""CLI: print the simulated known-preference table."""

import argparse
import json
from pathlib import Path

from framework.learner.simulate import NOTE, recover_table

DEFAULT_TRUE_PS = (0.5, 0.6, 0.7, 0.8, 0.9)
DEFAULT_N_CARDS = (5, 13, 30, 100)


def _format_cell_side(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def main(argv: list[str] | None = None) -> int:
    """Print the full table; same seed gives same bytes."""
    parser = argparse.ArgumentParser(prog="framework.learner")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("recover")
    cmd.add_argument("--seed", type=int, required=True)
    cmd.add_argument("--sims", type=int, default=2000)
    cmd.add_argument("--n-cards", type=int, nargs="*", default=None)
    cmd.add_argument("--json", type=str, default=None)
    args = parser.parse_args(argv)

    n_cards = tuple(args.n_cards) if args.n_cards else DEFAULT_N_CARDS
    try:
        table = recover_table(
            seed=args.seed,
            n_sims=args.sims,
            true_ps=DEFAULT_TRUE_PS,
            n_cards=n_cards,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        "SIMULATED rulings from a known preference. "
        f"No real data. seed={args.seed} sims={args.sims}"
    )
    print(
        "true_p n_cards correct_side mean_absolute_error coverage mean_interval_width"
    )
    for cell in table.cells:
        print(
            f"{cell.true_p:.3f} {cell.n_cards} "
            f"{_format_cell_side(cell.correct_side)} "
            f"{cell.mean_absolute_error:.3f} {cell.coverage:.3f} "
            f"{cell.mean_interval_width:.3f}"
        )
    print(NOTE)
    if args.json is not None:
        Path(args.json).write_text(
            json.dumps(table.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
