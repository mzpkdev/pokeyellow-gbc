"""Real audit-ROM overlay oracle checks."""

from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import Phase2Rom

pytest_plugins = ("tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom",)


def _linked_overworld_tile_attributes(phase2_rom: Phase2Rom) -> bytes:
    """Read the independently linked 256-byte semantic attribute table."""
    emu = phase2_rom.emulator
    start_name = "FullColorOverworldTileAttributes"
    end_name = "FullColorOverworldTileAttributesEnd"
    bank = emu.symbol_banks[start_name]
    address = emu.symbols[start_name]
    assert emu.symbol_banks[end_name] == bank
    assert emu.symbols[end_name] - address == 0x100
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return emu.rom.read_bytes()[offset:offset + 0x100]


def test_overlay_uses_request_tiles_not_preexisting_vram(phase2_rom: Phase2Rom) -> None:
    tiles = b"\x18\x29\x3a\x4b"
    attribute_table = _linked_overworld_tile_attributes(phase2_rom)
    expected_attrs = bytes(attribute_table[tile] for tile in tiles)
    assert expected_attrs == b"\x06\x06\x00\x05"
    assert expected_attrs != bytes(tile & 7 for tile in tiles)
    phase2_rom.write_fixed(0xC900, tiles)
    for bank, fill in ((0, 0xA5), (1, 0x5A)):
        old = phase2_rom.emulator.pyboy.memory[0xFF4F]
        phase2_rom.emulator.pyboy.memory[0xFF4F] = bank
        for offset in range(4):
            phase2_rom.emulator.pyboy.memory[0x9BFE + offset] = fill
        phase2_rom.emulator.pyboy.memory[0xFF4F] = old
    assert phase2_rom.call(
        "EnqueueFullColorMapOverlay", hl=0xC900, de=0x9BFE, b=4, c=1,
    )[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.write_fixed(0xC900, b"\xcc" * 4)
    phase2_rom.call("RunFullColorOwnershipVBlank")
    addresses = (0x9BFE, 0x9BFF, 0x9800, 0x9801)
    observed_tiles = bytes(phase2_rom.emulator.read_vram_bank(0, a, 1)[0] for a in addresses)
    observed_attrs = bytes(phase2_rom.emulator.read_vram_bank(1, a, 1)[0] for a in addresses)
    assert observed_tiles == tiles
    assert observed_attrs == expected_attrs
