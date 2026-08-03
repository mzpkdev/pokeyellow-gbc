"""Production-ROM proof for the saved Color Mode option."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
PAD_RIGHT = 0x10
PAD_LEFT = 0x20
PAD_UP = 0x40
PAD_DOWN = 0x80


def _constants(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            result[match.group(2)] = int(match.group(1), 16)
    return result


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


def _call(rom: Emulator, routine: str, *, stop_at: str | None = None) -> int:
    registers = rom.pyboy.register_file
    bank = rom.symbol_banks[routine]
    address = rom.symbols[routine]
    stack = 0xCFFE
    returned = False
    registers.SP = stack
    rom.pyboy.memory[0xFFFF] = 0
    rom.pyboy.memory[0xFF0F] = 0
    rom.pyboy.memory[stack] = 0x00
    rom.pyboy.memory[stack + 1] = 0x01
    rom.pyboy.memory[0x2000] = bank & 0xFF
    rom.pyboy.memory[0x3000] = bank >> 8
    rom.pyboy.memory[rom.symbols["hLoadedROMBank"]] = bank
    rom.pyboy.memory[0xFF80 : 0xFF84] = bytes(
        (0xF3, 0xC3, address & 0xFF, address >> 8)
    )
    registers.PC = 0xFF80

    stop_bank = rom.symbol_banks[stop_at] if stop_at else 0
    stop_address = rom.symbols[stop_at] if stop_at else 0x0100

    def stop(_: object) -> None:
        nonlocal returned
        returned = True
        rom.pyboy.memory[0xFF80 : 0xFF82] = b"\x18\xfe"
        registers.PC = 0xFF80

    rom.pyboy.hook_register(stop_bank, stop_address, stop, None)
    try:
        for _ in range(300):
            rom.pyboy.tick(1, render=False, sound=False)
            if returned:
                break
    finally:
        rom.pyboy.hook_deregister(stop_bank, stop_address)
    assert returned, (
        f"{routine} did not reach {stop_at or 'its return'} "
        f"(PC={registers.PC:#06x}, SP={registers.SP:#06x})"
    )
    return registers.F


def _visible_resources(rom: Emulator) -> tuple[bytes, ...]:
    return (
        rom.read_vram_bank(0, 0x8000, 0x2000),
        rom.read_vram_bank(1, 0x8000, 0x2000),
        rom.read_palette_ram(),
        rom.read_palette_ram(object_palettes=True),
        rom.read_memory(0xFE00, 160),
        rom.read_bytes("wShadowOAM", 160),
    )


def test_options_toggles_only_preference_and_renders_both_values(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, constants = product_rom
    rom.write("wUnusedObtainedBadges", 0xA4)
    owner_before = rom.read_bytes("wRendererStateStart", 13)
    visible_before = _visible_resources(rom)

    rom.write("hJoy5", PAD_RIGHT)
    _call(rom, "OptionsMenu_ColorMode")
    assert rom.read("wUnusedObtainedBadges") == 0xA5
    tilemap = rom.symbols["wTileMap"] + 12 * 20 + 14
    assert rom.read_memory(tilemap, 6) == bytes((0x98, 0x84, 0x8B, 0x8B, 0x8E, 0x96))

    rom.write("hJoy5", PAD_LEFT)
    _call(rom, "OptionsMenu_ColorMode")
    assert rom.read("wUnusedObtainedBadges") == 0xA4
    assert rom.read_memory(tilemap, 6) == bytes((0x82, 0x8E, 0x8B, 0x8E, 0x91, 0x7F))
    assert rom.read_bytes("wRendererStateStart", 13) == owner_before
    assert _visible_resources(rom) == visible_before
    assert constants["FULL_COLOR_PRODUCTION_ACTIVATED"] == 0


def test_cursor_reaches_color_mode_between_print_and_cancel(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, _ = product_rom
    rom.write("wOptionsCursorLocation", 4)
    rom.write("hJoy5", PAD_DOWN)
    _call(rom, "OptionsControl")
    assert rom.read("wOptionsCursorLocation") == 5
    rom.write("hJoy5", PAD_DOWN)
    _call(rom, "OptionsControl")
    assert rom.read("wOptionsCursorLocation") == 7
    rom.write("hJoy5", PAD_UP)
    _call(rom, "OptionsControl")
    assert rom.read("wOptionsCursorLocation") == 5
    rom.write("hJoy5", PAD_UP)
    _call(rom, "OptionsControl")
    assert rom.read("wOptionsCursorLocation") == 4


def test_new_game_initialization_and_oak_preservation(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, _ = product_rom
    rom.write("wUnusedObtainedBadges", 0xA5)
    rom.write("wObtainedBadges", 0xFF)
    _call(rom, "InitPlayerData2", stop_at="InitializeToggleableObjectsFlags")
    assert rom.read("wUnusedObtainedBadges") == 0xA5
    assert rom.read("wObtainedBadges") == 0

    rom.write("wUnusedObtainedBadges", 0xFF)
    _call(rom, "InitPlayerData", stop_at="InitializeToggleableObjectsFlags")
    assert rom.read("wUnusedObtainedBadges") == 0

    rom.write("wUnusedObtainedBadges", 0xA5)
    rom.write("wOptionsInitialized", 1)
    _call(rom, "PrepareOakSpeech", stop_at="PrepareOakSpeechPreferenceRestored")
    assert rom.read("wUnusedObtainedBadges") == 0xA5
    _call(rom, "InitPlayerData2", stop_at="InitializeToggleableObjectsFlags")
    assert rom.read("wUnusedObtainedBadges") == 0xA5


def test_preference_participates_in_unchanged_main_save_checksum_span(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, _ = product_rom
    start = rom.symbols["wMainDataStart"]
    end = rom.symbols["wMainDataEnd"]
    preference = rom.symbols["wUnusedObtainedBadges"]
    rom.write("wUnusedObtainedBadges", 0)
    color_data = bytearray(rom.read_memory(start, end - start))
    color_checksum = (~sum(color_data)) & 0xFF
    rom.write("wUnusedObtainedBadges", 1)
    yellow_data = bytearray(rom.read_memory(start, end - start))
    yellow_checksum = (~sum(yellow_data)) & 0xFF
    assert yellow_data[preference - start] == 1
    assert color_checksum != yellow_checksum
    assert ((color_checksum - yellow_checksum) & 0xFF) == 1


def test_preference_remains_inside_unchanged_main_save_span(
    product_rom: tuple[Emulator, dict[str, int]],
) -> None:
    rom, _ = product_rom
    assert rom.symbols["wUnusedObtainedBadges"] == rom.symbols["wObtainedBadges"] + 1
    assert rom.symbols["wMainDataStart"] <= rom.symbols["wUnusedObtainedBadges"]
    assert rom.symbols["wUnusedObtainedBadges"] < rom.symbols["wMainDataEnd"]
    assert rom.symbols["wMainDataStart"] == 0xD2F6
    assert rom.symbols["wMainDataEnd"] == 0xDA7F
