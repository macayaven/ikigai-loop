"""Held-out gate set v1 freeze test: exact bytes of the blind 40-sentence set."""

import hashlib
from pathlib import Path

GATE_HELDOUT_V1_SHA256 = (
    "aa927912bae204a44a4c906387ca70e26fd5c8936c071653470482028af430cf"
)


def test_gate_heldout_v1_frozen() -> None:
    data = Path("evals/heldout/gate-heldout-v1.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == GATE_HELDOUT_V1_SHA256
