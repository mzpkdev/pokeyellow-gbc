"""Automation for starting a new game and completing Oak's introduction."""

from tools.rom_tests.emulator import Emulator


def reach_bedroom_overworld(emulator: Emulator) -> None:
    """Choose the default options and preset names, then enter Red's bedroom."""
    emulator.tick(600)
    emulator.press("start")

    # Advance through the title menu, difficulty selection, player selection,
    # and Oak's speech until the player-name presets are displayed.
    emulator.advance_until(
        emulator.is_preset_name_menu,
        max_presses=30,
        description="player name menu",
    )
    emulator.press("down")
    emulator.press("a")

    # Confirm the player name and continue Oak's speech to the rival-name menu.
    emulator.advance_until(
        emulator.is_preset_name_menu,
        max_presses=20,
        description="rival name menu",
    )
    emulator.press("down")
    emulator.press("a")

    # Confirm the rival name and finish the introduction.
    emulator.advance_until(
        emulator.is_in_bedroom_overworld,
        max_presses=40,
        description="bedroom overworld",
    )
    emulator.tick(120)
