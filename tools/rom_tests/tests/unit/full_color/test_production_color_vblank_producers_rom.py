"""Real-ROM checks for production Color palette/animation producers."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
)


RVBK = 0xFF4F


@pytest.fixture
def production_rom(request: pytest.FixtureRequest) -> Phase2Rom:
    symbols = REPOSITORY_ROOT / "pokeyellow_debug.sym"
    emulator = Emulator(
        REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        symbols,
        result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = Phase2Rom(emulator, numeric_symbols(symbols))
    try:
        required = {
            "ProduceFullColorProductionVBlankWork",
            "ProduceFullColorProductionAnimatedTileSelected",
            "EnqueueFullColorProductionPaletteSelected",
            "CancelFullColorSchedulerSelected",
            "FullColorOverworldBGPalettes",
            "FullColorProductionOBJPalettes",
            "FullColorProductionFlowerTile1",
        }
        assert required <= emulator.symbols.keys()
        rom.activate()
        # The selected producer seam intentionally assumes its caller already
        # owns the WRAM2 critical section.
        emulator.pyboy.memory[0xFF70] = 2
        yield rom
    finally:
        emulator.close()


def _write_vram(rom: Phase2Rom, bank: int, address: int, payload: bytes) -> None:
    memory = rom.emulator.pyboy.memory
    prior = memory[RVBK]
    memory[RVBK] = bank
    try:
        for offset, value in enumerate(payload):
            memory[address + offset] = value
    finally:
        memory[RVBK] = prior


def _prepare_visible_tile(rom: Phase2Rom, tile: int) -> None:
    rom.write_fixed(rom.emulator.symbols["wTileMap"], bytes([tile]) + bytes(359))
    rom.write_wram2("wFullColorAuthorityVRAMView", (0x9800).to_bytes(2, "little"))


def test_wrong_owner_animation_producer_fails_closed(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    rom.write_wram2("wRendererOwner", rom.constants["RENDERER_YELLOW"])
    memory = rom.emulator.pyboy.memory
    memory[rom.emulator.symbols["hTileAnimations"]] = 1
    memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] = 19
    _prepare_visible_tile(rom, 0x14)
    before_vram = rom.emulator.read_vram_bank(0, 0x9140, 16)

    _, flags = rom.call("ProduceFullColorProductionAnimatedTileSelected")

    assert flags & 0x10
    assert memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] == 19
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
    assert rom.emulator.read_vram_bank(0, 0x9140, 16) == before_vram


def test_wrong_owner_production_palette_root_stays_closed(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    rom.write_wram2("wRendererOwner", rom.constants["RENDERER_YELLOW"])
    before_base = rom.read_wram2("wFullColorOBJPaletteBase", 64)
    before_hardware = rom.emulator.read_palette_ram(object_palettes=True)

    result, flags = rom.call("ProduceFullColorProductionVBlankWork")

    assert result == rom.constants["REJECTED_WRONG_OWNER"] and flags & 0x10
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
    assert rom.read_wram2("wFullColorOBJPaletteBase", 64) == before_base
    assert rom.emulator.read_palette_ram(object_palettes=True) == before_hardware


@pytest.mark.parametrize(
    ("symbol", "request_class", "base", "object_palettes"),
    (
        (
            "FullColorOverworldBGPalettes",
            "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD",
            "wFullColorBGPaletteBase",
            False,
        ),
        (
            "FullColorProductionOBJPalettes",
            "FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD",
            "wFullColorOBJPaletteBase",
            True,
        ),
    ),
)
def test_authored_palette_is_one_complete_nonzero_scheduler_commit(
    production_rom: Phase2Rom,
    symbol: str,
    request_class: str,
    base: str,
    object_palettes: bool,
) -> None:
    rom = production_rom
    address = rom.emulator.symbols[symbol]
    bank = rom.emulator.symbol_banks[symbol]
    expected = rom.emulator.read_memory(address, 64, bank=bank)
    poisoned_snapshot = b"\xa5" * 64
    assert expected != bytes(64) and expected != poisoned_snapshot
    rom.write_wram2("wFullColorProducerTiles", poisoned_snapshot)

    result, flags = rom.call(
        "EnqueueFullColorProductionPaletteSelected",
        a=rom.constants[request_class],
        de=address,
    )

    assert result == rom.constants["ACCEPTED"]
    # The internal selected helper returns A as its semantic result; the public
    # producer root normalizes carry before exposing it.
    assert rom.read_wram2("wFullColorRequestCount") == b"\x01"
    descriptor = rom.read_wram2("wFullColorRequestDescriptors", 20)
    assert int.from_bytes(descriptor[8:10], "little") == address
    assert rom.read_wram2(base, 64) == expected
    rom.call("RunFullColorOwnershipVBlank")
    committed = rom.emulator.read_palette_ram(object_palettes=object_palettes)
    assert committed == expected
    assert any(committed)


def test_cancel_discards_deferred_movement_and_admits_exactly_one_replacement(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    first = bytes(range(40))
    deferred = bytes((0x80 + index) & 0xFF for index in range(36))
    replacement = bytes((0x40 + index) & 0xFF for index in range(40))
    rom.write_fixed(0xC900, first)
    assert rom.call(
        "EnqueueFullColorMovementRowStrip", hl=0xC900, de=0x9800,
    )[0] == rom.constants["ACCEPTED"]
    rom.write_fixed(0xC940, deferred)
    assert rom.call(
        "EnqueueFullColorMovementColumnStrip", hl=0xC940, de=0x9840,
    )[0] == rom.constants["DEFERRED"]
    assert rom.read_wram2("wFullColorProducerPending") == b"\x01"

    rom.call("CancelFullColorSchedulerSelected")

    assert rom.read_wram2("wFullColorProducerPending") == b"\x00"
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
    rom.write_fixed(0xC980, replacement)
    assert rom.call(
        "EnqueueFullColorMovementRowStrip", hl=0xC980, de=0x9880,
    )[0] == rom.constants["ACCEPTED"]
    assert rom.read_wram2("wFullColorRequestCount") == b"\x01"
    rom.call("RunFullColorOwnershipVBlank")
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
    assert rom.emulator.read_vram_bank(0, 0x9880, 20) == replacement[:20]
    assert rom.emulator.read_vram_bank(0, 0x98A0, 20) == replacement[20:]


def test_cancel_discards_deferred_palette_and_admits_exactly_one_replacement(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    obj = "FullColorProductionOBJPalettes"
    bg = "FullColorOverworldBGPalettes"
    assert rom.call(
        "EnqueueFullColorProductionPaletteSelected",
        a=rom.constants["FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD"],
        de=rom.emulator.symbols[obj],
    )[0] == rom.constants["ACCEPTED"]
    assert rom.call(
        "EnqueueFullColorProductionPaletteSelected",
        a=rom.constants["FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD"],
        de=rom.emulator.symbols[bg],
    )[0] == rom.constants["DEFERRED"]
    assert rom.read_wram2("wFullColorProducerPending") == b"\x01"

    rom.call("CancelFullColorSchedulerSelected")

    assert rom.read_wram2("wFullColorProducerPending") == b"\x00"
    assert rom.call(
        "EnqueueFullColorProductionPaletteSelected",
        a=rom.constants["FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD"],
        de=rom.emulator.symbols[bg],
    )[0] == rom.constants["ACCEPTED"]
    assert rom.read_wram2("wFullColorRequestCount") == b"\x01"
    rom.call("RunFullColorOwnershipVBlank")
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_color_water_animation_is_a_paired_scheduler_commit(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    memory = rom.emulator.pyboy.memory
    source = bytes((index * 17 + 3) & 0xFF for index in range(16))
    _write_vram(rom, 0, 0x9140, source)
    _prepare_visible_tile(rom, 0x14)
    memory[rom.emulator.symbols["hTileAnimations"]] = 1
    memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] = 19
    memory[rom.emulator.symbols["wMovingBGTilesCounter2"]] = 0

    result, flags = rom.call("ProduceFullColorProductionAnimatedTileSelected")

    assert result == rom.constants["ACCEPTED"] and not flags & 0x10
    descriptor = rom.read_wram2("wFullColorRequestDescriptors", 20)
    assert descriptor[0] == (
        rom.constants["PREPARED"] << 4
        | rom.constants["FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT"]
    )
    assert memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] == 0
    rom.call("RunFullColorOwnershipVBlank")
    assert rom.emulator.read_vram_bank(0, 0x9140, 16) == bytes(
        ((value >> 1) | ((value & 1) << 7)) for value in source
    )
    assert rom.emulator.read_vram_bank(1, 0x9800, 1) == b"\x03"


def test_flower_field_replacement_uses_owned_immutable_authority(
    production_rom: Phase2Rom,
) -> None:
    rom = production_rom
    memory = rom.emulator.pyboy.memory
    _prepare_visible_tile(rom, 0x03)
    memory[rom.emulator.symbols["hTileAnimations"]] = 2
    memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] = 20
    memory[rom.emulator.symbols["wMovingBGTilesCounter2"]] = 0
    expected = (REPOSITORY_ROOT / "gfx/tilesets/flower/flower1.2bpp").read_bytes()
    assert len(expected) == 16

    result, flags = rom.call("ProduceFullColorProductionAnimatedTileSelected")

    assert result == rom.constants["ACCEPTED"] and not flags & 0x10
    assert memory[rom.emulator.symbols["hMovingBGTilesCounter1"]] == 0
    rom.call("RunFullColorOwnershipVBlank")
    assert rom.emulator.read_vram_bank(0, 0x9030, 16) == expected
    assert rom.emulator.read_vram_bank(1, 0x9800, 1) == b"\x01"


def test_production_root_orders_complete_producers_before_commit() -> None:
    lifecycle = (REPOSITORY_ROOT / "engine/full_color/lifecycle.asm").read_text()
    route = lifecycle.split("RunFullColorProductionVBlank::", 1)[1].split("ENDC", 1)[0]
    ordered = (
        "RetryFullColorProducer",
        "RunFullColorOwnershipVBlank",
    )
    assert [route.index(symbol) for symbol in ordered] == sorted(
        route.index(symbol) for symbol in ordered
    )
    vblank = (REPOSITORY_ROOT / "home/vblank.asm").read_text()
    boundary = vblank.index("FullColorProductionVBlankVisibleRouteComplete::")
    assert boundary < vblank.index("PrepareFullColorProductionPostVisibleRoute")
    post = lifecycle.split("PrepareFullColorProductionPostVisibleRoute::", 1)[1]
    assert "ProduceFullColorProductionVBlankWork" in post
    assert "PrepareFullColorProductionOAMForOwnedVBlank" in post

    producer = (REPOSITORY_ROOT / "engine/full_color/palettes.asm").read_text()
    guard = producer.split("ProduceFullColorProductionVBlankWork::", 1)[1]
    owner_check = guard.index("cp RENDERER_FULL_COLOR_OVERWORLD")
    for operation in (
        "FullColorProductionOBJPaletteDueSelected",
        "FullColorProductionBGPaletteDueSelected",
        "ProduceFullColorProductionAnimatedTileSelected",
    ):
        assert owner_check < guard.index(operation)

    transfers = (REPOSITORY_ROOT / "engine/full_color/transfers.asm").read_text()
    assert "vTileset tile $14" in transfers
    assert "FullColorProductionFlowerTile1" in transfers
    assert "BuildAndPrepareFullColorAnimationDescriptorSelected" in transfers
