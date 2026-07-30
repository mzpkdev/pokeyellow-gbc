"""Integration coverage for reaching the first city."""

from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.viridian_city import (
    VIRIDIAN_CITY,
    reach_viridian_city,
)


SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots"


def test_new_game_reaches_viridian_city(emulator: Emulator) -> None:
    reach_viridian_city(emulator)

    assert not emulator.is_in_battle()
    assert emulator.read("wCurMap") == VIRIDIAN_CITY
    assert (emulator.read("wYCoord"), emulator.read("wXCoord")) == (35, 20)
    emulator.assert_screen_matches(
        SNAPSHOTS / "viridian-city-entry.png",
        name="viridian-city-entry",
    )
