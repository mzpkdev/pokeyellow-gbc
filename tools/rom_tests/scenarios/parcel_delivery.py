"""Automation for collecting Oak's Parcel and returning it to the lab."""

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import OAKS_LAB, PALLET_TOWN
from tools.rom_tests.scenarios.viridian_city import (
    ROUTE_1,
    VIRIDIAN_CITY,
    reach_viridian_city,
    walk_to_value,
)
from tools.rom_tests.test_support import apply_debug_repel


VIRIDIAN_MART = 0x2A
OAKS_PARCEL = 0x46

SCRIPT_VIRIDIANMART_PARCEL_RECEIVED = 2
SCRIPT_OAKSLAB_RIVAL_ARRIVES_WITH_PARCEL = 19
SCRIPT_OAKSLAB_NOOP = 22


def collect_oaks_parcel(emulator: Emulator) -> None:
    """Enter the Viridian Mart and accept Oak's Parcel from the clerk."""
    walk_to_value(emulator, "wYCoord", 29, "up", "south Viridian ledge")
    walk_to_value(emulator, "wXCoord", 19, "left", "Viridian main path")
    walk_to_value(emulator, "wYCoord", 20, "up", "Viridian Mart row")
    walk_to_value(emulator, "wXCoord", 29, "right", "Viridian Mart entrance")
    walk_to_value(emulator, "wCurMap", VIRIDIAN_MART, "up", "Viridian Mart")
    emulator.tick(60)

    emulator.advance_until(
        lambda: emulator.read("wViridianMartCurScript")
        == SCRIPT_VIRIDIANMART_PARCEL_RECEIVED,
        button="a",
        max_presses=80,
        description="receiving Oak's Parcel",
    )
    if not emulator.bag_contains(OAKS_PARCEL):
        raise AssertionError("The Mart clerk did not give Oak's Parcel")


def return_to_oaks_lab(emulator: Emulator) -> None:
    """Leave Viridian and take Route 1's southbound ledges to Pallet Town."""
    walk_to_value(emulator, "wYCoord", 6, "down", "Mart exit row")
    walk_to_value(emulator, "wXCoord", 3, "right", "Mart exit")
    walk_to_value(emulator, "wCurMap", VIRIDIAN_CITY, "down", "Viridian City")
    emulator.tick(60)

    walk_to_value(emulator, "wXCoord", 19, "left", "Viridian main path")
    walk_to_value(emulator, "wYCoord", 29, "down", "south Viridian path")
    walk_to_value(emulator, "wXCoord", 20, "right", "Route 1 entrance")
    walk_to_value(emulator, "wCurMap", ROUTE_1, "down", "Route 1")
    emulator.tick(60)
    apply_debug_repel(emulator)

    # The return trip uses Route 1's southbound ledges as a shortcut.
    walk_to_value(emulator, "wYCoord", 12, "down", "north Route 1 ledge")
    walk_to_value(emulator, "wXCoord", 9, "left", "first southbound ledge")
    walk_to_value(emulator, "wYCoord", 22, "down", "central Route 1 ledge")
    walk_to_value(emulator, "wXCoord", 12, "right", "second southbound ledge")
    walk_to_value(emulator, "wYCoord", 31, "down", "south Route 1 ledge")
    walk_to_value(emulator, "wXCoord", 10, "left", "Pallet Town entrance")
    walk_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "Pallet Town")
    emulator.tick(60)

    # Walk around the lab building and enter through its south-facing door.
    walk_to_value(emulator, "wYCoord", 2, "down", "north Pallet Town")
    walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
    walk_to_value(emulator, "wYCoord", 12, "down", "south side of Oak's Lab")
    walk_to_value(emulator, "wXCoord", 12, "right", "Oak's Lab entrance")
    walk_to_value(emulator, "wCurMap", OAKS_LAB, "up", "Oak's Lab")
    emulator.tick(60)


def deliver_parcel_and_leave_lab(emulator: Emulator) -> None:
    """Talk to Oak, complete the Pokédex dialogue, and leave the lab."""
    walk_to_value(emulator, "wYCoord", 3, "up", "Professor Oak")
    emulator.press("up")
    emulator.press("a")
    emulator.advance_until(
        lambda: emulator.read("wOaksLabCurScript")
        == SCRIPT_OAKSLAB_RIVAL_ARRIVES_WITH_PARCEL,
        button="a",
        max_presses=40,
        description="delivering Oak's Parcel",
    )
    if emulator.bag_contains(OAKS_PARCEL):
        raise AssertionError("Oak's Parcel was not removed from the bag")

    emulator.advance_until(
        lambda: emulator.read("wOaksLabCurScript") == SCRIPT_OAKSLAB_NOOP,
        button="a",
        max_presses=240,
        description="Oak's Pokédex dialogue",
    )
    emulator.tick(120)

    walk_to_value(emulator, "wYCoord", 10, "down", "lab exit row")
    walk_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "leaving Oak's Lab")
    emulator.tick(120)


def complete_parcel_delivery(emulator: Emulator) -> None:
    """Play from a new game through delivering Oak's Parcel."""
    reach_viridian_city(emulator)
    collect_oaks_parcel(emulator)
    return_to_oaks_lab(emulator)
    deliver_parcel_and_leave_lab(emulator)
