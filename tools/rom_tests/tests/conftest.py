"""Shared pytest fixtures for ROM tests."""

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "test-results"


def configured_results_root(environment: Mapping[str, str] = os.environ) -> Path:
    """Resolve the one evidence root used by ROM tests."""
    return Path(
        environment.get("ROM_TEST_RESULTS", str(DEFAULT_RESULTS_ROOT))
    ).resolve()


def result_directory(node_id: str) -> Path:
    """Return a stable, collision-resistant result directory for one test."""
    readable_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_id).strip("-")[-80:]
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:8]
    return configured_results_root() / f"{readable_name}-{digest}"


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
