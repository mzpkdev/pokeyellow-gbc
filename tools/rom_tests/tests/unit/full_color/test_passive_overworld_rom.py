"""Linked-ROM proofs for the passive Pallet Town and Route 1 color layer."""

from __future__ import annotations

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _farcall_from_wram,
    _linked_overworld_tile_attributes,
    numeric_symbols,
)
from tools.rom_tests.tests.unit.full_color.test_phase2_vblank_routing_rom import (
    ENTRY_ROM_BANK,
    ENTRY_WRAM_BANK,
    _run_actual_vblank,
)


RBGPI = 0xFF68
RBGPD = 0xFF69
RBGP = 0xFF47
BOOTROM_DISABLE = 0xFF50
RSVBK = 0xFF70
RVBK = 0xFF4F
VBG_MAP_0 = 0x9800
TILEMAP_AREA = 32 * 32
PALLET_TOWN = 0
ROUTE_1 = 0x0C
REDRAW_COL = 1
REDRAW_ROW = 2
PAD_RIGHT = 1 << 4
YELLOW_NORMAL_BGP = 0xE4
SCREEN_WIDTH = 20
SCREEN_HEIGHT = 18
PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")


@pytest.fixture(name="phase2_rom", params=PRODUCTS)
def phase2_rom_fixture(request: pytest.FixtureRequest):
    product = request.param
    rom = REPOSITORY_ROOT / f"{product}.gbc"
    sym = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(
        rom=rom,
        symbols=sym,
        results=result_directory(request.node.nodeid) / product,
        cgb=True,
    )
    instance = Phase2Rom(emulator, numeric_symbols(sym))
    dma_stub = bytes(
        (0x3E, 0xC3, 0xE0, 0x46, 0x3E, 0x28, 0x3D, 0x20, 0xFD, 0xC9)
    )
    for offset, value in enumerate(dma_stub):
        emulator.pyboy.memory[0xFF80 + offset] = value
    try:
        yield instance
    finally:
        emulator.close()


def _linked_bytes(rom: Phase2Rom, start: str, end: str) -> bytes:
    bank = rom.emulator.symbol_banks[start]
    assert rom.emulator.symbol_banks[end] == bank
    address = rom.emulator.symbols[start]
    size = rom.emulator.symbols[end] - address
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom.emulator.rom.read_bytes()[offset : offset + size]


def _linked_palette_entry(rom: Phase2Rom, index: int) -> bytes:
    bank = rom.emulator.symbol_banks["CGBBasePalettes"]
    address = rom.emulator.symbols["CGBBasePalettes"] + index * 8
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom.emulator.rom.read_bytes()[offset : offset + 8]


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


def _write_player_data(rom: Phase2Rom, symbol: str, value: int) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = 1
    try:
        emu.memory[rom.emulator.symbols[symbol]] = value
    finally:
        emu.memory[RSVBK] = prior


def _read_player_data(rom: Phase2Rom, symbol: str) -> int:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = 1
    try:
        return emu.memory[rom.emulator.symbols[symbol]]
    finally:
        emu.memory[RSVBK] = prior


def _activate_passive_map(rom: Phase2Rom, map_id: int = PALLET_TOWN) -> None:
    emu = rom.emulator.pyboy
    rom.call("InitRendererOwnership")
    emu.memory[rom.emulator.symbols["wCurMap"]] = map_id
    _write_player_data(rom, "wUnusedObtainedBadges", 0)
    emu.memory[0xFF40] &= 0x7F
    rom.call("PassiveFullColorApplyMap")


def test_product_option_toggles_only_saved_renderer_preference_bit(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 0xA0)
    emu.memory[symbols["hJoy5"]] = PAD_RIGHT

    phase2_rom.call("OptionsMenu_ColorMode")

    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = 1
    try:
        assert emu.memory[symbols["wUnusedObtainedBadges"]] == 0xA1
    finally:
        emu.memory[RSVBK] = prior


def test_saved_yellow_preference_blocks_map_publish_and_clears_all_attributes(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = PALLET_TOWN
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 0x81)
    emu.memory[0xFF40] &= 0x7F
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\x07" * TILEMAP_AREA)

    phase2_rom.call("PassiveFullColorApplyMap")

    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
    assert phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == (
        b"\x00" * TILEMAP_AREA
    )


def test_menu_close_in_yellow_mode_restores_authoritative_pallet_palette(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = PALLET_TOWN
    emu.memory[symbols["wOnSGB"]] = 1
    emu.memory[symbols["hOnCGB"]] = 1
    emu.memory[RBGP] = YELLOW_NORMAL_BGP
    emu.memory[0xFF40] &= 0x7F

    # Pallet is palette ID 1 in Yellow's linked CGB base-palette authority.
    expected_yellow_pallet = _linked_palette_entry(phase2_rom, 1)
    _write_player_data(phase2_rom, "wLastBGP", YELLOW_NORMAL_BGP)
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 0)
    phase2_rom.call("PassiveFullColorApplyMap")
    stale_donor_palette = phase2_rom.emulator.read_palette_ram()
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\x07" * TILEMAP_AREA)
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 1)

    assert stale_donor_palette[:8] != expected_yellow_pallet
    assert _read_player_data(phase2_rom, "wLastBGP") == emu.memory[RBGP]
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"

    # Production has unmapped the boot ROM before this home-bank CopyData path.
    emu.memory[BOOTROM_DISABLE] = 1
    _farcall_from_wram(
        phase2_rom, "PassiveFullColorRestoreAfterMenu", entry_bank=5,
    )

    assert phase2_rom.emulator.read_palette_ram()[:8] == expected_yellow_pallet
    assert phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == (
        b"\x00" * TILEMAP_AREA
    )
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"


def test_overlay_presentation_stays_latched_after_color_preference_changes(
    phase2_rom: Phase2Rom,
) -> None:
    _activate_passive_map(phase2_rom)
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 1)

    _, flags = phase2_rom.call("PassiveFullColorShouldColorOverlay")

    assert flags & 0x10
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"


def test_inactive_live_activation_publishes_wrapped_visible_rows_before_color(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    attributes = _linked_overworld_tile_attributes(phase2_rom)
    palettes = _linked_bytes(
        phase2_rom, "FullColorOverworldBGPalettes", "FullColorOverworldBGPalettesEnd"
    )
    tiles = bytes((index * 29 + 7) & 0xFF for index in range(SCREEN_WIDTH * SCREEN_HEIGHT))
    pointer = 0x9BF5  # bottom row, x=21: exercises both horizontal and vertical wrap
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = PALLET_TOWN
    _write_player_data(phase2_rom, "wUnusedObtainedBadges", 0)
    phase2_rom.write_fixed(symbols["wTileMap"], tiles)
    phase2_rom.write_fixed(
        symbols["wMapViewVRAMPointer"], bytes((pointer & 0xFF, pointer >> 8))
    )
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\x07" * TILEMAP_AREA)
    phase2_rom.call("PassiveFullColorWriteActive", a=0)
    phase2_rom.call("PassiveFullColorTranslateTileMap")
    phase2_rom.call("PassiveFullColorWriteState", b=4, c=SCREEN_HEIGHT)

    phase2_rom.call("PassiveFullColorVBlank", de=0)
    neutral = phase2_rom.emulator.read_palette_ram()
    assert all(neutral[index * 8 : index * 8 + 8] == neutral[:8] for index in range(8))
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"

    expected_by_address: dict[int, int] = {}
    for row in range(SCREEN_HEIGHT):
        y = ((pointer - VBG_MAP_0) // 32 + row) & 31
        x = (pointer - VBG_MAP_0) & 31
        for column in range(SCREEN_WIDTH):
            address = VBG_MAP_0 + y * 32 + ((x + column) & 31)
            expected_by_address[address] = attributes[tiles[row * SCREEN_WIDTH + column]]

    for remaining in range(SCREEN_HEIGHT - 2, -1, -2):
        phase2_rom.call("PassiveFullColorVBlank", de=0)
        assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x00"
        assert phase2_rom.emulator.read_palette_ram() == neutral
        assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == bytes((remaining,))

    actual = phase2_rom.emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA)
    assert all(actual[address - VBG_MAP_0] == value for address, value in expected_by_address.items())
    offscreen = next(address for address in range(VBG_MAP_0, VBG_MAP_0 + TILEMAP_AREA) if address not in expected_by_address)
    assert actual[offscreen - VBG_MAP_0] == 7
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x06"

    phase2_rom.call("PassiveFullColorVBlank", de=0)
    assert phase2_rom.emulator.read_palette_ram() == palettes
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"


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
    assert phase2_rom.read_wram2(
        "wPassiveFullColorDeferredRedrawState"
    ) == bytes((0x80 | mode,))
    _write_vram(phase2_rom, 0, VBG_MAP_0, b"\x55" * TILEMAP_AREA)
    _write_vram(phase2_rom, 1, VBG_MAP_0, b"\xee" * TILEMAP_AREA)
    emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode

    yellow_observation = _run_actual_vblank(phase2_rom)

    assert "RedrawRowOrColumn" in yellow_observation.call_sites
    assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == 0
    assert phase2_rom.read_wram2(
        "wPassiveFullColorDeferredRedrawState"
    ) == bytes((mode,))
    assert bytes(
        phase2_rom.emulator.read_vram_bank(0, address, 1)[0]
        for address in expected_addresses
    ) == source
    assert bytes(
        phase2_rom.emulator.read_vram_bank(1, address, 1)[0]
        for address in expected_addresses
    ) == b"\xee" * len(expected_addresses)

    _run_actual_vblank(phase2_rom)

    assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == 0
    assert phase2_rom.read_wram2(
        "wPassiveFullColorDeferredRedrawState"
    ) == b"\x00"
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
    phase2_rom.write_wram2("wPassiveFullColorPaletteInvalidated", 1)

    phase2_rom.call("PassiveFullColorHandleConnection")

    assert phase2_rom.emulator.read_palette_ram() == damaged
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x01"
    phase2_rom.call("PassiveFullColorVBlank", de=0)
    assert phase2_rom.emulator.read_palette_ram() == expected
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"


@pytest.mark.parametrize("writer", ("TransferBGPPals", "TransferCurBGPData"))
def test_yellow_bg_palette_writers_invalidate_authored_palette_authority(
    phase2_rom: Phase2Rom,
    writer: str,
) -> None:
    emu = phase2_rom.emulator.pyboy
    _activate_passive_map(phase2_rom, ROUTE_1)
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"

    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call(writer)

    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x01"


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
    emu.memory[symbols["wCurMap"]] = 0x33  # VIRIDIAN_FOREST, outside the slice

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


def test_actual_passive_vblank_restores_machine_state_and_keeps_yellow_owner(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    _activate_passive_map(phase2_rom)
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
    assert emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] != 0
