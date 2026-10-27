"""Ticket 1: the package skeleton imports and reports its version."""

import framework


def test_framework_imports() -> None:
    assert isinstance(framework.__version__, str)
    assert framework.__version__
