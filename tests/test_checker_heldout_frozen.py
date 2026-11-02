"""Held-out checker set v1 freeze test: exact bytes of the blind 40-case set."""

import hashlib
from pathlib import Path

CHECKER_HELDOUT_V1_SHA256 = (
    "937789f47824e6a073e72a73f027eadf95e24787acb1a77bc97c269513bc2610"
)


def test_checker_heldout_v1_frozen() -> None:
    data = Path("evals/heldout/checker-heldout-v1.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == CHECKER_HELDOUT_V1_SHA256
