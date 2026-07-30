"""Test-only state controls that never modify the built ROM."""

from tools.rom_tests.emulator import Emulator


MAX_REPEL_STEPS = 0xFF


def apply_debug_repel(emulator: Emulator) -> None:
    """Give the current test the maximum remaining Repel duration."""
    emulator.write("wRepelRemainingSteps", MAX_REPEL_STEPS)
    if emulator.read("wRepelRemainingSteps") != MAX_REPEL_STEPS:
        raise AssertionError("Failed to apply the test-only debug Repel")
