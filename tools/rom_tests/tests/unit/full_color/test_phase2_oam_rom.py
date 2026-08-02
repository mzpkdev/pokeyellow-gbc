"""Real audit-ROM OAM full-batch, DMA and fallback checks."""

from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import Phase2Rom, phase2_rom


def test_oam_commits_full_shadow_batch_and_dma_with_fallback(phase2_rom: Phase2Rom) -> None:
    batch = bytearray(160)
    for index in range(40):
        batch[index * 4:index * 4 + 4] = bytes((16 + index, 8 + index, index, 0xF8 | 7))
    identities = bytes((3, 0xFF, 9, 0x80) + (0,) * 36)
    phase2_rom.write_fixed(0xC900, bytes(batch) + identities)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", source=0xC900,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    expected = bytearray(batch)
    for index, palette in enumerate((3, 0, 0, 0) + (0,) * 36):
        expected[index * 4 + 3] = 0xF8 | palette
    shadow = bytes(phase2_rom.emulator.pyboy.memory[0xC300 + i] for i in range(160))
    hardware = bytes(phase2_rom.emulator.pyboy.memory[0xFE00 + i] for i in range(160))
    assert shadow == expected
    assert hardware == expected
    assert phase2_rom.read_wram2("wFullColorReconstructionItems", 4) == bytes((
        3,
        phase2_rom.constants["FULL_COLOR_FALLBACK_UNMAPPED"],
        0x80,
        3,
    ))


def test_oam_fallback_ledger_is_bounded_exact_and_marks_overflow(phase2_rom: Phase2Rom) -> None:
    payload = bytes(160) + b"\xff" * 40
    phase2_rom.write_fixed(0xC900, payload)
    request = phase2_rom.descriptor("FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", source=0xC900)
    for _ in range(7):
        assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]
        phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.read_wram2("wFullColorReconstructionItems", 4) == bytes((
        0xFF,
        phase2_rom.constants["FULL_COLOR_FALLBACK_MISSING_IDENTITY"],
        0xFF,
        39,
    ))


def test_phase2_oam_never_touches_write_only_sram_controls(phase2_rom: Phase2Rom) -> None:
    # This is execution-sensitive: SRAM holds sentinel bytes in two banks and
    # the fallback path runs. No Phase 2 code may guess/restore bank zero.
    for bank, value in ((1, 0x51), (3, 0x73)):
        phase2_rom.emulator.pyboy.memory[0x0000] = 0x0A
        phase2_rom.emulator.pyboy.memory[0x4000] = bank
        phase2_rom.emulator.pyboy.memory[0xA000] = value
    phase2_rom.emulator.pyboy.memory[0x4000] = 1
    payload = bytes(160) + b"\xff" * 40
    phase2_rom.write_fixed(0xC900, payload)
    phase2_rom.admit(phase2_rom.descriptor("FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", source=0xC900))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.pyboy.memory[0xA000] == 0x51
