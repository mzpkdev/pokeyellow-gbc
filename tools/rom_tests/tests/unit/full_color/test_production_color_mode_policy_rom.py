"""Production-ROM proof for the inert Color/YELLOW policy resolver."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
CONTEXTS = (
    "RENDERER_CONTEXT_ORDINARY_MAP",
    "RENDERER_CONTEXT_OVERLAY",
    "RENDERER_CONTEXT_DIALOGUE",
    "RENDERER_CONTEXT_MENU",
    "RENDERER_CONTEXT_BATTLE",
    "RENDERER_CONTEXT_STANDALONE",
    "RENDERER_CONTEXT_BOOT_RESET",
)
MAPS = ("PALLET_TOWN", "ROUTE_1", "VIRIDIAN_CITY")
MAP_IDS = {"PALLET_TOWN": 0x00, "ROUTE_1": 0x0C, "VIRIDIAN_CITY": 0x01}


def _constants(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            result[match.group(2)] = int(match.group(1), 16)
    return result


def _call(rom: Emulator, routine: str, *, a: int, b: int, c: int) -> int:
    registers = rom.pyboy.register_file
    bank = rom.symbol_banks[routine]
    address = rom.symbols[routine]
    stack = 0xCFFE
    returned = False
    registers.A, registers.B, registers.C = a, b, c
    registers.SP = stack
    rom.pyboy.memory[stack] = 0x00
    rom.pyboy.memory[stack + 1] = 0x01
    rom.pyboy.memory[0x2000] = bank & 0xFF
    rom.pyboy.memory[0x3000] = bank >> 8
    rom.pyboy.memory[0xFF80 : 0xFF84] = bytes(
        (0xF3, 0xC3, address & 0xFF, address >> 8)
    )
    registers.PC = 0xFF80

    def stop(_: object) -> None:
        nonlocal returned
        returned = True
        rom.pyboy.memory[0xFF80 : 0xFF82] = b"\x18\xfe"
        registers.PC = 0xFF80

    rom.pyboy.hook_register(0, 0x0100, stop, None)
    try:
        rom.pyboy.tick(1, render=False, sound=False)
    finally:
        rom.pyboy.hook_deregister(0, 0x0100)
    assert returned, f"{routine} did not return"
    return registers.A


@pytest.fixture(params=PRODUCTS)
def product_rom(request: pytest.FixtureRequest) -> tuple[Emulator, dict[str, int]]:
    product = str(request.param)
    rom = Emulator(
        REPOSITORY_ROOT / f"{product}.gbc",
        REPOSITORY_ROOT / f"{product}.sym",
        result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        yield rom, _constants(REPOSITORY_ROOT / f"{product}.sym")
    finally:
        rom.close()


def _visible_resources(rom: Emulator) -> tuple[bytes, ...]:
    return (
        rom.read_vram_bank(0, 0x8000, 0x2000),
        rom.read_vram_bank(1, 0x8000, 0x2000),
        rom.read_palette_ram(),
        rom.read_palette_ram(object_palettes=True),
        rom.read_memory(0xFE00, 160),
        rom.read_bytes("wShadowOAM", 160),
    )


def test_effective_owner_matrix_and_hostile_preferences(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, constants = product_rom
    assert constants["NUM_RENDERER_CONTEXTS"] == len(CONTEXTS)
    assert constants["FULL_COLOR_PRODUCTION_ACTIVATED"] == 1
    assert "YELLOW_RECONSTRUCTING" in constants
    color_rows = 0
    for preference in ("COLOR_MODE_COLOR", "COLOR_MODE_YELLOW"):
        for context in CONTEXTS:
            for map_name in MAPS:
                actual = _call(
                    rom,
                    "ResolveEffectiveRendererOwner",
                    a=constants[preference],
                    b=constants[context],
                    c=MAP_IDS[map_name],
                )
                is_color = (
                    preference == "COLOR_MODE_COLOR"
                    and context == "RENDERER_CONTEXT_ORDINARY_MAP"
                    and map_name in {"PALLET_TOWN", "ROUTE_1"}
                )
                expected = (
                    "RENDERER_FULL_COLOR_OVERWORLD" if is_color else "RENDERER_YELLOW"
                )
                assert actual == constants[expected]
                color_rows += is_color
    assert color_rows == 2
    for hostile in (2, 0x7F, 0xFF):
        assert _call(
            rom,
            "ResolveEffectiveRendererOwner",
            a=hostile,
            b=constants["RENDERER_CONTEXT_ORDINARY_MAP"],
            c=MAP_IDS["PALLET_TOWN"],
        ) == constants["RENDERER_YELLOW"]


def test_preference_and_current_map_adapter_are_observational(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, constants = product_rom
    owner_before = rom.read_bytes("wRendererStateStart", 13)
    visible_before = _visible_resources(rom)
    rom.write("wCurMap", MAP_IDS["PALLET_TOWN"])
    rom.write("wUnusedObtainedBadges", 0xA4)
    assert _call(rom, "ResolveCurrentOrdinaryMapOwner", a=0, b=0, c=0) == constants[
        "RENDERER_FULL_COLOR_OVERWORLD"
    ]
    rom.write("wUnusedObtainedBadges", 0xA5)
    assert _call(rom, "ResolveCurrentOrdinaryMapOwner", a=0, b=0, c=0) == constants[
        "RENDERER_YELLOW"
    ]
    assert rom.read_bytes("wRendererStateStart", 13) == owner_before
    assert _visible_resources(rom) == visible_before
