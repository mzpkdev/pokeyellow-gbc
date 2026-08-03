"""Real audit-ROM geometry and paired-plane transfer checks."""

from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT

from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom, numeric_symbols, phase2_rom,
)


def _vram(rom: Phase2Rom, bank: int, addresses: tuple[int, ...]) -> bytes:
    return bytes(rom.emulator.read_vram_bank(bank, address, 1)[0] for address in addresses)


def test_column_uses_32_byte_stride(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_fixed(0xC900, b"\x11\x22\x33\x01\x02\x03")
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED", destination=0x981F, source=0xC900,
        desired=0x0301, extent=3, reservation=6,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    addresses = (0x981F, 0x983F, 0x985F)
    assert _vram(phase2_rom, 0, addresses) == b"\x11\x22\x33"
    assert _vram(phase2_rom, 1, addresses) == b"\x01\x02\x03"


def test_rectangle_row_stride_and_map_wrap_are_explicit(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_fixed(0xC900, b"ABCD\x01\x02\x03\x04")
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED", destination=0x9BFF, source=0xC900,
        desired=0x0202, extent=4, reservation=8,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    addresses = (0x9BFF, 0x9800, 0x981F, 0x9820)
    assert _vram(phase2_rom, 0, addresses) == b"ABCD"
    assert _vram(phase2_rom, 1, addresses) == b"\x01\x02\x03\x04"


def test_animation_replaces_tile_data_and_matching_attribute(phase2_rom: Phase2Rom) -> None:
    tiles = bytes(range(16))
    phase2_rom.write_fixed(0xC900, tiles + b"\x9f")
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT", destination=0x97F0,
        desired=0x9FFF, source=0xC900,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x97F0, 16) == tiles
    assert phase2_rom.emulator.read_vram_bank(1, 0x9FFF, 1) == b"\x8f"


def test_prepared_animation_freezes_tile_and_attribute_source(phase2_rom: Phase2Rom) -> None:
    payload = bytes(range(16)) + b"\x9f"
    phase2_rom.write_fixed(0xC900, payload)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT", destination=0x9000,
        desired=0x9800, source=0xC900,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    phase2_rom.write_fixed(0xC900, b"\xee" * len(payload))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9000, 16) == payload[:16]
    assert phase2_rom.emulator.read_vram_bank(1, 0x9800, 1) == b"\x8f"


def test_max_prepared_pair_freezes_both_planes_across_scratch_alias(phase2_rom: Phase2Rom) -> None:
    width, height, extent = 20, 18, 360
    tiles = bytes(index & 0xFF for index in range(extent))
    attributes = bytes((index * 3) & 7 for index in range(extent))
    phase2_rom.write_fixed(0xC900, tiles + attributes)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED", destination=0x9800,
        desired=(height << 8) | width, source=0xC900,
        extent=extent, reservation=extent * 2,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    phase2_rom.write_fixed(0xC900, b"\xee" * (extent * 2))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    addresses = tuple(0x9800 + row * 32 + column for row in range(height) for column in range(width))
    assert _vram(phase2_rom, 0, addresses) == tiles
    assert _vram(phase2_rom, 1, addresses) == attributes


def test_animation_rejects_tile_or_attribute_destination_escape(phase2_rom: Phase2Rom) -> None:
    for changes in ({"destination": 0x97F1}, {"desired": 0xD000}):
        assert phase2_rom.admit(phase2_rom.descriptor(
            "FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT", **changes,
        ))[0] == phase2_rom.constants["DEFERRED"]


def test_rom_byte_stride_mutation_trips_geometry_assertion(tmp_path: Path) -> None:
    source_rom = REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"
    source_sym = REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"
    symbols = numeric_symbols(source_sym)
    probe = Emulator(rom=source_rom, symbols=source_sym, results=tmp_path / "probe", cgb=True)
    try:
        address = probe.symbols["AdvanceFullColorMapRowSelected"]
        bank = probe.symbol_banks["AdvanceFullColorMapRowSelected"]
    finally:
        probe.close()
    blob = bytearray(source_rom.read_bytes())
    offset = bank * 0x4000 + address - 0x4000
    assert blob[offset:offset + 3] == b"\x7d\xc6\x20"
    blob[offset + 2] = 1
    mutant_rom = tmp_path / "stride-mutant.gbc"
    mutant_rom.write_bytes(blob)
    emulator = Emulator(rom=mutant_rom, symbols=source_sym, results=tmp_path / "mutant", cgb=True)
    mutant = Phase2Rom(emulator, symbols)
    try:
        mutant.activate()
        mutant.write_fixed(0xC900, b"AB\x01\x02")
        mutant.admit(mutant.descriptor(
            "FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED", destination=0x981F,
            source=0xC900, desired=0x0201, extent=2, reservation=4,
        ))
        mutant.call("RunFullColorOwnershipVBlank")
        with pytest.raises(AssertionError, match="32-byte column stride"):
            observed = _vram(mutant, 0, (0x981F, 0x983F))
            assert observed == b"AB", "32-byte column stride mutation escaped"
    finally:
        emulator.close()
