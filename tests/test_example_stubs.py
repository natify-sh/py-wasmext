"""The stubs committed beside the .wasm of the examples are what the generator makes now (they are not made at the build of the wheel, so they go stale).

When this fails: `uv run python tools/make_example_stubs.py` and commit the stubs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_example_stubs  # pyright: ignore[reportMissingImports]

STUBS = sorted((ROOT / "examples").glob("*/src/*/*.pyi"))


def test_there_are_stubs_to_check() -> None:
    assert len(STUBS) >= 10


@pytest.mark.parametrize("pyi", STUBS, ids=lambda p: f"{p.parent.parent.parent.name}/{p.name}")
def test_the_committed_stub_is_the_one_the_generator_makes(pyi: Path) -> None:
    assert pyi.read_text(encoding="utf-8") == make_example_stubs.stub_of(pyi)  # pyright: ignore[reportUnknownMemberType]
