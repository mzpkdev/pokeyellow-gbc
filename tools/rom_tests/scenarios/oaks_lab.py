"""Automation for receiving Pikachu and completing the first rival battle."""

from collections.abc import Callable

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld


PALLET_TOWN = 0x00
REDS_HOUSE_1F = 0x25
OAKS_LAB = 0x28
PIKACHU = 0x54

SCRIPT_OAKSLAB_PLAYER_DONT_GO_AWAY = 6
SCRIPT_OAKSLAB_RIVAL_CHALLENGES_PLAYER = 12
SCRIPT_OAKSLAB_NOOP = 22

JourneyCheckpoint = Callable[[str, Emulator], None]


def _advance_to_value(
    emulator: Emulator,
    symbol: str,
    value: int,
    button: str,
    description: str,
    max_presses: int = 140,
) -> None:
    emulator.advance_until(
        lambda: emulator.read(symbol) == value,
        button=button,
        max_presses=max_presses,
        description=description,
    )


def walk_from_bedroom_to_pallet(emulator: Emulator) -> None:
    """Leave Red's bedroom and stop at the first stable Pallet Town frame."""
    _advance_to_value(emulator, "wXCoord", 5, "right", "bedroom aisle")
    _advance_to_value(emulator, "wYCoord", 1, "up", "bedroom stairs")
    _advance_to_value(emulator, "wCurMap", REDS_HOUSE_1F, "right", "first floor")

    _advance_to_value(emulator, "wYCoord", 6, "down", "house exit row")
    _advance_to_value(emulator, "wXCoord", 3, "left", "house exit")
    _advance_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "Pallet Town")
    emulator.tick(60)


def walk_from_pallet_to_oak(emulator: Emulator) -> None:
    """Walk north from Pallet Town until Oak intercepts the player."""
    if emulator.read("wCurMap") != PALLET_TOWN:
        raise AssertionError("Oak approach must start in Pallet Town")

    _advance_to_value(emulator, "wXCoord", 10, "right", "north exit column")
    _advance_to_value(emulator, "wYCoord", 0, "up", "Oak interception")
    emulator.tick(60)


def walk_from_bedroom_to_oak(
    emulator: Emulator,
    checkpoint: JourneyCheckpoint | None = None,
) -> None:
    """Leave Red's house and walk north until Oak intercepts the player."""
    walk_from_bedroom_to_pallet(emulator)
    if checkpoint is not None:
        checkpoint("pallet-before-oak", emulator)
    walk_from_pallet_to_oak(emulator)
    if checkpoint is not None:
        checkpoint("oak-interception", emulator)


def follow_oak_and_receive_pikachu(emulator: Emulator) -> None:
    """Advance Oak's scripted sequence and interact with the starter ball."""
    _advance_to_value(emulator, "wCurMap", OAKS_LAB, "a", "Oak's Lab")
    _advance_to_value(
        emulator,
        "wOaksLabCurScript",
        SCRIPT_OAKSLAB_PLAYER_DONT_GO_AWAY,
        "a",
        "starter selection",
    )

    # Approach the Poké Ball from below. The rival takes Eevee, after which
    # Oak gives Pikachu to the player.
    _advance_to_value(emulator, "wYCoord", 4, "down", "starter aisle")
    _advance_to_value(emulator, "wXCoord", 7, "right", "starter Poké Ball")
    emulator.press("up")
    emulator.press("a")
    _advance_to_value(emulator, "wPartyCount", 1, "a", "receiving Pikachu")


def finish_rival_battle_and_leave_lab(emulator: Emulator) -> None:
    """Complete the mandatory battle, accepting either a win or a loss."""
    _advance_to_value(
        emulator,
        "wOaksLabCurScript",
        SCRIPT_OAKSLAB_RIVAL_CHALLENGES_PLAYER,
        "a",
        "rival challenge",
    )
    _advance_to_value(emulator, "wYCoord", 6, "down", "rival battle trigger")
    emulator.advance_until(
        emulator.is_in_battle,
        button="a",
        max_presses=80,
        description="rival battle start",
    )

    # Repeated A presses select FIGHT and the first available move. Both battle
    # outcomes advance to the same post-battle lab script.
    _advance_to_value(
        emulator,
        "wOaksLabCurScript",
        SCRIPT_OAKSLAB_NOOP,
        "a",
        "post-battle lab sequence",
        max_presses=300,
    )

    _advance_to_value(emulator, "wYCoord", 10, "down", "lab exit row")
    if emulator.read("wXCoord") < 4:
        _advance_to_value(emulator, "wXCoord", 4, "right", "lab exit")
    elif emulator.read("wXCoord") > 5:
        _advance_to_value(emulator, "wXCoord", 5, "left", "lab exit")
    _advance_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "leaving Oak's Lab")
    emulator.tick(120)


def complete_oaks_lab_intro(
    emulator: Emulator,
    checkpoint: JourneyCheckpoint | None = None,
) -> None:
    """Start a new game, receive Pikachu, battle the rival, and leave the lab."""
    reach_bedroom_overworld(emulator)
    if checkpoint is not None:
        checkpoint("bedroom", emulator)
    walk_from_bedroom_to_oak(emulator, checkpoint)
    follow_oak_and_receive_pikachu(emulator)
    finish_rival_battle_and_leave_lab(emulator)
    if checkpoint is not None:
        checkpoint("post-lab-pallet", emulator)
