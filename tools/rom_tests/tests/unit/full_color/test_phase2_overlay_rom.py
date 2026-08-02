"""Real audit-ROM overlay oracle checks."""

from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import Phase2Rom, phase2_rom


def test_overlay_uses_request_tiles_not_preexisting_vram(phase2_rom: Phase2Rom) -> None:
    tiles = b"\x08\x19\x2a\x3b"
    phase2_rom.write_fixed(0xC900, tiles + b"ignored ambient bytes")
    for bank, fill in ((0, 0xA5), (1, 0x5A)):
        old = phase2_rom.emulator.pyboy.memory[0xFF4F]
        phase2_rom.emulator.pyboy.memory[0xFF4F] = bank
        for offset in range(4):
            phase2_rom.emulator.pyboy.memory[0x9BFE + offset] = fill
        phase2_rom.emulator.pyboy.memory[0xFF4F] = old
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED", destination=0x9BFE, source=0xC900,
        desired=0x0104, extent=4, reservation=8,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    addresses = (0x9BFE, 0x9BFF, 0x9800, 0x9801)
    observed_tiles = bytes(phase2_rom.emulator.read_vram_bank(0, a, 1)[0] for a in addresses)
    observed_attrs = bytes(phase2_rom.emulator.read_vram_bank(1, a, 1)[0] for a in addresses)
    assert observed_tiles == tiles
    assert observed_attrs == bytes(value & 7 for value in tiles)
