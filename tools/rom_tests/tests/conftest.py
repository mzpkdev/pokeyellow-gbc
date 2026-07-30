"""Shared pytest fixtures for ROM tests."""

import hashlib
import os
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPOSITORY_ROOT / "test-results"


def result_directory(node_id: str) -> Path:
    """Return a stable, collision-resistant result directory for one test."""
    readable_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_id).strip("-")[-80:]
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:8]
    return RESULTS / f"{readable_name}-{digest}"


@pytest.fixture
def emulator(request: pytest.FixtureRequest) -> Emulator:
    """Create isolated emulator state and failure output for each test."""
    driver = Emulator(
        rom=Path(os.environ.get("ROM_TEST_ROM", REPOSITORY_ROOT / "pokeyellow_debug.gbc")),
        symbols=Path(
            os.environ.get(
                "ROM_TEST_SYMBOLS",
                REPOSITORY_ROOT / "pokeyellow_debug.sym",
            )
        ),
        results=result_directory(request.node.nodeid),
    )
    try:
        yield driver
    finally:
        driver.close()
