"""Automation for traveling from Oak's Lab to Viridian City."""

from collections.abc import Callable

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import (
    PALLET_TOWN,
    complete_oaks_lab_intro,
)
from tools.rom_tests.test_support import apply_debug_repel


ROUTE_1 = 0x0C
VIRIDIAN_CITY = 0x01


def finish_unexpected_wild_battle(emulator: Emulator) -> None:
    """Fight with the first move until an encounter ends."""
    emulator.advance_until(
        lambda: not emulator.is_in_battle(),
        button="a",
        max_presses=200,
        description="unexpected Route 1 battle",
    )


def walk_until(
    emulator: Emulator,
    predicate: Callable[[], bool],
    button: str,
    description: str,
    max_presses: int = 160,
) -> None:
    for _ in range(max_presses):
        if predicate():
            return
        if emulator.is_in_battle():
            finish_unexpected_wild_battle(emulator)
            continue
        emulator.press(button)

    emulator.save_screenshot(f"timeout-{description}.png")
    raise AssertionError(f"Timed out walking to {description}")


def walk_to_value(
    emulator: Emulator,
    symbol: str,
    value: int,
    button: str,
    description: str,
) -> None:
    walk_until(
        emulator,
        lambda: emulator.read(symbol) == value,
        button,
        description,
    )


def walk_from_oaks_lab_to_viridian(emulator: Emulator) -> None:
    """Cross Pallet Town and Route 1, handling incidental wild battles."""
    if emulator.read("wCurMap") != PALLET_TOWN:
        raise AssertionError("Viridian route must start outside Oak's Lab")

    apply_debug_repel(emulator)

    # Walk around Oak's Lab and approach Pallet Town's north connection.
    walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
    walk_to_value(emulator, "wYCoord", 2, "up", "north Pallet Town")
    walk_to_value(emulator, "wXCoord", 10, "right", "Route 1 entrance")
    walk_to_value(emulator, "wCurMap", ROUTE_1, "up", "Route 1")
    emulator.tick(60)

    # Route 1 alternates narrow northbound passages at these coordinates.
    walk_to_value(emulator, "wYCoord", 30, "up", "south Route 1 clearing")
    walk_to_value(emulator, "wXCoord", 6, "left", "first passage")
    walk_to_value(emulator, "wYCoord", 25, "up", "first passage north")
    walk_to_value(emulator, "wXCoord", 12, "right", "second passage")
    walk_to_value(emulator, "wYCoord", 21, "up", "second passage north")
    walk_to_value(emulator, "wXCoord", 9, "left", "central passage")
    walk_to_value(emulator, "wYCoord", 15, "up", "central passage north")
    walk_to_value(emulator, "wXCoord", 14, "right", "final passage")
    walk_to_value(emulator, "wYCoord", 3, "up", "north Route 1 clearing")
    walk_to_value(emulator, "wXCoord", 10, "left", "Viridian entrance")
    walk_to_value(emulator, "wCurMap", VIRIDIAN_CITY, "up", "Viridian City")
    emulator.tick(180)


def reach_viridian_city(emulator: Emulator) -> None:
    """Start a new game and play continuously through to Viridian City."""
    complete_oaks_lab_intro(emulator)
    walk_from_oaks_lab_to_viridian(emulator)
