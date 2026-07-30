"""Visual regression coverage for the beginning of a new game."""

from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld


SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots"


def test_new_game_reaches_bedroom_overworld(emulator: Emulator) -> None:
    reach_bedroom_overworld(emulator)

    assert emulator.read("wPikachuHappiness") == 30
    assert emulator.read("wPikachuMood") == 0
    assert emulator.read("wPikachuCompanionStepCounter") == 0
    assert emulator.read("wPikachuNextGift") == 0
    assert emulator.read("wPikachuGiftCooldown") == 0
    assert emulator.read("wPikachuGiftAlerted") == 0
    assert emulator.read("wPikachuAmbientItem") == 0
    assert emulator.read("wPikachuAmbientAlerted") == 0
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wPikachuCompanionIdleCounter") == 0
    assert emulator.read("wStarterPikachuParticipatedInBattle") == 0
    assert emulator.read("wCurMap") == 0x26
    assert (emulator.read("wYCoord"), emulator.read("wXCoord")) == (6, 3)
    emulator.assert_screen_matches(
        SNAPSHOTS / "new-game-bedroom.png",
        name="new-game-bedroom",
    )
