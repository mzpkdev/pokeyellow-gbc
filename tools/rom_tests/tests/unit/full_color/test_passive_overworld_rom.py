"""Linked-ROM proofs for the passive Pallet Town and Route 1 color layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _linked_overworld_tile_attributes,
    phase2_rom as _phase2_rom,  # noqa: F401 - registered by pytest
)
from tools.rom_tests.tests.unit.full_color.test_phase2_vblank_routing_rom import (
    ENTRY_ROM_BANK,
    ENTRY_WRAM_BANK,
    _run_actual_vblank,
)


RBGPI = 0xFF68
RBGPD = 0xFF69
RSVBK = 0xFF70
RVBK = 0xFF4F
VBG_MAP_0 = 0x9800
TILEMAP_AREA = 32 * 32
PALLET_TOWN = 0
ROUTE_1 = 0x0C
REDRAW_COL = 1
REDRAW_ROW = 2


@pytest.fixture(name="phase2_rom")
def phase2_rom_fixture(request: pytest.FixtureRequest) -> Phase2Rom:
    return request.getfixturevalue("_phase2_rom")


def _linked_bytes(rom: Phase2Rom, start: str, end: str) -> bytes:
    bank = rom.emulator.symbol_banks[start]
    assert rom.emulator.symbol_banks[end] == bank
    address = rom.emulator.symbols[start]
    size = rom.emulator.symbols[end] - address
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc").read_bytes()[
        offset : offset + size
    ]


def _write_palette(rom: Phase2Rom, payload: bytes) -> None:
    assert len(payload) == 64
    emu = rom.emulator.pyboy
    prior = emu.memory[RBGPI]
    try:
        for index, value in enumerate(payload):
            emu.memory[RBGPI] = index
            emu.memory[RBGPD] = value
    finally:
        emu.memory[RBGPI] = prior


def _write_vram(rom: Phase2Rom, bank: int, address: int, payload: bytes) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RVBK]
    emu.memory[RVBK] = bank
    try:
        for offset, value in enumerate(payload):
            emu.memory[address + offset] = value
    finally:
        emu.memory[RVBK] = prior


def _activate_passive_map(rom: Phase2Rom, map_id: int = PALLET_TOWN) -> None:
    emu = rom.emulator.pyboy
    rom.call("InitRendererOwnership")
    emu.memory[rom.emulator.symbols["wCurMap"]] = map_id
    emu.memory[0xFF40] &= 0x7F
    rom.call("PassiveFullColorApplyMap")


def test_cold_boot_map_zero_cannot_activate_without_a_real_map_publish(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    rom_palette = _linked_bytes(
        phase2_rom, "FullColorOverworldBGPalettes", "FullColorOverworldBGPalettesEnd"
    )
    sentinel_palette = bytes((index * 5 + 7) & 0x7F for index in range(64))
    sentinel_attributes = bytes((index * 3 + 1) & 7 for index in range(TILEMAP_AREA))
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = PALLET_TOWN
    _write_palette(phase2_rom, sentinel_palette)
    _write_vram(phase2_rom, 1, VBG_MAP_0, sentinel_attributes)

    phase2_rom.call("PassiveFullColorVBlank", de=0)

    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
    assert phase2_rom.emulator.read_palette_ram() == sentinel_palette
    assert phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == (
        sentinel_attributes
    )
    assert sentinel_palette != rom_palette


@pytest.mark.parametrize("map_id", (PALLET_TOWN, ROUTE_1))
def test_lcd_off_map_publish_keeps_yellow_owner_and_mirrors_all_1024_tiles(
    phase2_rom: Phase2Rom, map_id: int,
) -> None:
    emu = phase2_rom.emulator.pyboy
    tiles = bytes((index * 37 + 11) & 0xFF for index in range(TILEMAP_AREA))
    attributes = _linked_overworld_tile_attributes(phase2_rom)
    palettes = _linked_bytes(
        phase2_rom, "FullColorOverworldBGPalettes", "FullColorOverworldBGPalettesEnd"
    )
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = map_id
    emu.memory[0xFF40] &= 0x7F
    _write_vram(phase2_rom, 0, VBG_MAP_0, tiles)
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\x07" * TILEMAP_AREA)

    phase2_rom.call("PassiveFullColorApplyMap")

    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wRendererPhase") == bytes(
        (phase2_rom.constants["YELLOW_ACTIVE"],)
    )
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"
    assert phase2_rom.emulator.read_palette_ram() == palettes
    assert phase2_rom.emulator.read_vram_bank(0, VBG_MAP_0, TILEMAP_AREA) == tiles
    assert phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == bytes(
        attributes[tile] for tile in tiles
    )


@pytest.mark.parametrize(
    ("mode", "source", "destination", "expected_addresses"),
    (
        (
            REDRAW_ROW,
            bytes((index * 9 + 3) & 0xFF for index in range(40)),
            0x9820,
            tuple(range(0x9820, 0x9820 + 20)) + tuple(range(0x9840, 0x9840 + 20)),
        ),
        (
            REDRAW_COL,
            bytes((index * 11 + 5) & 0xFF for index in range(36)),
            0x9812,
            tuple(
                address
                for row in range(18)
                for address in (0x9812 + row * 32, 0x9813 + row * 32)
            ),
        ),
    ),
)
def test_real_vblank_runs_yellow_bank0_redraw_before_exact_passive_attributes(
    phase2_rom: Phase2Rom,
    mode: int,
    source: bytes,
    destination: int,
    expected_addresses: tuple[int, ...],
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    attributes = _linked_overworld_tile_attributes(phase2_rom)
    _activate_passive_map(phase2_rom)
    phase2_rom.write_fixed(symbols["wRedrawRowOrColumnSrcTiles"], source)
    emu.memory[symbols["hRedrawRowOrColumnDest"]] = destination & 0xFF
    emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = destination >> 8
    if mode == REDRAW_ROW:
        phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
    else:
        phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
    emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode

    observation = _run_actual_vblank(phase2_rom)

    assert "RedrawRowOrColumn" in observation.call_sites
    assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == 0
    assert bytes(
        phase2_rom.emulator.read_vram_bank(0, address, 1)[0]
        for address in expected_addresses
    ) == source
    assert bytes(
        phase2_rom.emulator.read_vram_bank(1, address, 1)[0]
        for address in expected_addresses
    ) == bytes(attributes[tile] for tile in source)


def test_pending_palette_refresh_commits_exact_payload_on_next_vblank_only(
    phase2_rom: Phase2Rom,
) -> None:
    expected = _linked_bytes(
        phase2_rom, "FullColorOverworldBGPalettes", "FullColorOverworldBGPalettesEnd"
    )
    damaged = bytes(value ^ 0x1F for value in expected)
    _activate_passive_map(phase2_rom, ROUTE_1)
    _write_palette(phase2_rom, damaged)

    phase2_rom.call("PassiveFullColorHandleConnection")

    assert phase2_rom.emulator.read_palette_ram() == damaged
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x01"
    phase2_rom.call("PassiveFullColorVBlank", de=0)
    assert phase2_rom.emulator.read_palette_ram() == expected
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"


def test_generation_mismatch_deactivates_persistently_across_low_byte_wrap(
    phase2_rom: Phase2Rom,
) -> None:
    expected = _linked_bytes(
        phase2_rom, "FullColorOverworldBGPalettes", "FullColorOverworldBGPalettesEnd"
    )
    damaged = bytes(value ^ 0x1F for value in expected)
    _activate_passive_map(phase2_rom)
    recorded_generation = phase2_rom.read_wram2("wPassiveFullColorGeneration")[0]
    phase2_rom.write_wram2(
        "wRendererGeneration", bytes(((recorded_generation + 1) & 0xFF, 0, 0, 0))
    )
    phase2_rom.write_wram2("wPassiveFullColorPalettePending", 1)

    phase2_rom.call("PassiveFullColorVBlank", de=0)

    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x00"

    # A later generation can share the recorded low byte after 256 handoffs.
    # The mismatch must have made the stale passive state permanently inert.
    phase2_rom.write_wram2(
        "wRendererGeneration", bytes((recorded_generation, 1, 0, 0))
    )
    _write_palette(phase2_rom, damaged)
    phase2_rom.call("PassiveFullColorVBlank", de=0)

    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
    assert phase2_rom.emulator.read_palette_ram() == damaged


def test_exit_makes_stale_attributes_inert_then_clears_every_bank1_address(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    _activate_passive_map(phase2_rom)
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\x07" * TILEMAP_AREA)
    emu.memory[symbols["wCurMap"]] = 1  # VIRIDIAN_CITY, outside the slice

    phase2_rom.call("PassiveFullColorHandleConnection")
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x20"

    phase2_rom.call("PassiveFullColorVBlank", de=0)
    palette = phase2_rom.emulator.read_palette_ram()
    assert all(
        palette[index * 8 : index * 8 + 8] == palette[:8] for index in range(8)
    ), palette.hex()
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x20"
    for _ in range(32):
        phase2_rom.call("PassiveFullColorVBlank", de=0)
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x00"
    assert phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == (
        b"\x00" * TILEMAP_AREA
    )


def test_actual_passive_vblank_restores_machine_state_and_never_runs_scheduler(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    _activate_passive_map(phase2_rom)
    queue_before = phase2_rom.read_wram2("wFullColorRequestCount")

    observation = _run_actual_vblank(phase2_rom)

    assert observation.stack_pointer == 0xFFFC
    assert observation.rsvbk == ENTRY_WRAM_BANK
    assert observation.rvbk & 1 == 1
    assert observation.loaded_rom_bank == ENTRY_ROM_BANK
    assert observation.interrupt_enable & 0x1F == 1
    assert observation.interrupt_flags & 0x1F == 1 << 4
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wFullColorRequestCount") == queue_before == b"\x00"
    assert emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] != 0
