"""Visual regression coverage for the beginning of a new game."""

from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld


SNAPSHOTS = Path(__file__).resolve().parents[3] / "snapshots"


def test_new_game_reaches_bedroom_overworld(emulator: Emulator) -> None:
    reach_bedroom_overworld(emulator)

    # InitPlayerData sets the canonical fresh-save happiness to 90.
    assert emulator.read("wPikachuHappiness") == 90
    assert emulator.read("wPikachuMood") == 0x80
    assert emulator.read("wCurMap") == 0x26
    assert (emulator.read("wYCoord"), emulator.read("wXCoord")) == (6, 3)
    emulator.assert_screen_matches(
        SNAPSHOTS / "new-game-bedroom.png",
        name="new-game-bedroom",
        ignored_regions=((64, 48, 80, 64),),  # player's idle animation frame
    )
