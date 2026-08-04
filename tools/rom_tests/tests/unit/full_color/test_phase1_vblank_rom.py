"""Real-interrupt regression checks for Phase 1 VBlank WRAM ownership."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


RSVBK = 0xFF70
RVBK = 0xFF4F
INTERRUPT_FLAGS = 0xFF0F
INTERRUPT_ENABLE = 0xFFFF
VBLANK_INTERRUPT = 1 << 0
WRAM_PROGRAM = 0xD100
RETURN_PROBE = 0x0100
HARNESS_HALT = 0xFF80
LEGACY_BANK = 1
RENDERER_BANK = 2
ENTRY_ROM_BANK = 5


@pytest.fixture
def cgb_debug_rom(request: pytest.FixtureRequest) -> Emulator:
    emulator = Emulator(
        rom=Path(
            os.environ.get(
                "ROM_TEST_ROM", REPOSITORY_ROOT / "pokeyellow_phase1_debug.gbc"
            )
        ),
        symbols=Path(
            os.environ.get(
                "ROM_TEST_SYMBOLS", REPOSITORY_ROOT / "pokeyellow_phase1_debug.sym"
            )
        ),
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        yield emulator
    finally:
        emulator.close()


def _write_banked(emulator: Emulator, bank: int, address: int, value: int) -> None:
    prior = emulator.pyboy.memory[RSVBK]
    emulator.pyboy.memory[RSVBK] = bank
    try:
        emulator.pyboy.memory[address] = value
    finally:
        emulator.pyboy.memory[RSVBK] = prior


def _read_banked(emulator: Emulator, bank: int, address: int) -> int:
    prior = emulator.pyboy.memory[RSVBK]
    emulator.pyboy.memory[RSVBK] = bank
    try:
        return emulator.pyboy.memory[address]
    finally:
        emulator.pyboy.memory[RSVBK] = prior


def _visible_resources(emulator: Emulator) -> tuple[bytes, ...]:
    """Presented hardware resources, excluding normal next-frame OAM scratch."""
    return (
        emulator.read_vram_bank(0, 0x8000, 0x2000),
        emulator.read_vram_bank(1, 0x8000, 0x2000),
        emulator.read_palette_ram(),
        emulator.read_palette_ram(object_palettes=True),
        emulator.read_memory(0xFE00, 160),
    )


@dataclass(frozen=True, slots=True)
class VBlankReturnObservation:
    program_counter: int
    stack_pointer: int
    rsvbk: int
    rvbk: int
    interrupt_enable: int
    interrupt_flags: int
    loaded_rom_bank: int
    mapped_rom: bytes
    visible_resources: tuple[bytes, ...]


@pytest.mark.parametrize("entry_bank", range(1, 8))
def test_actual_vblank_restores_renderer_bank_without_aliasing_legacy_wram(
    cgb_debug_rom: Emulator,
    entry_bank: int,
) -> None:
    emulator = cgb_debug_rom
    for _ in range(180):
        emulator.tick()
        if emulator.read_bytes("wRendererGeneration", 4) == b"\x01\x00\x00\x00":
            break
    else:
        raise AssertionError("hard boot did not initialize Phase 1 ownership")

    saved_rom_bank = emulator.symbols["wVBlankSavedROMBank"]
    disable_wy_update = emulator.symbols["wDisableVBlankWYUpdate"]
    assert emulator.symbol_banks["wVBlankSavedROMBank"] == LEGACY_BANK
    assert emulator.symbol_banks["wDisableVBlankWYUpdate"] == LEGACY_BANK

    _write_banked(emulator, LEGACY_BANK, disable_wy_update, 1)
    _write_banked(emulator, LEGACY_BANK, saved_rom_bank, 0xCC)
    alias_sentinels: dict[int, tuple[int, int]] = {}
    for bank in range(2, 8):
        values = (0xA0 + bank, 0x50 + bank)
        alias_sentinels[bank] = values
        _write_banked(emulator, bank, disable_wy_update, values[0])
        _write_banked(emulator, bank, saved_rom_bank, values[1])

    # Quiesce whatever interrupt state gameplay left behind before arming the
    # controlled request. PyBoy hooks replace the hooked opcode, so observing
    # vector $0040 with a hook would prevent the real handler from running.
    _write_banked(emulator, entry_bank, WRAM_PROGRAM, 0xF3)  # di
    _write_banked(emulator, entry_bank, WRAM_PROGRAM + 1, 0x18)  # jr -2
    _write_banked(emulator, entry_bank, WRAM_PROGRAM + 2, 0xFE)
    emulator.pyboy.memory[INTERRUPT_ENABLE] = 0
    emulator.pyboy.memory[INTERRUPT_FLAGS] = 0
    emulator.pyboy.memory[RSVBK] = entry_bank
    emulator.pyboy.register_file.PC = WRAM_PROGRAM
    emulator.pyboy.register_file.SP = 0xFFFC
    emulator.pyboy.tick(1, render=False, sound=False)

    # EI's delayed enable lets JP execute before interrupt service. The pending
    # request then enters vector $0040 and RETI returns to the fixed-bank probe,
    # where the hook captures the handler's state before touching IE or PC.
    _write_banked(emulator, entry_bank, WRAM_PROGRAM, 0xFB)  # ei
    _write_banked(emulator, entry_bank, WRAM_PROGRAM + 1, 0xC3)  # jp $0100
    _write_banked(emulator, entry_bank, WRAM_PROGRAM + 2, RETURN_PROBE & 0xFF)
    _write_banked(emulator, entry_bank, WRAM_PROGRAM + 3, RETURN_PROBE >> 8)
    emulator.pyboy.register_file.PC = WRAM_PROGRAM
    emulator.pyboy.register_file.SP = 0xFFFC
    emulator.pyboy.memory[0x2000] = ENTRY_ROM_BANK
    emulator.pyboy.memory[0x3000] = 0
    emulator.pyboy.memory[emulator.symbols["hLoadedROMBank"]] = ENTRY_ROM_BANK
    emulator.pyboy.memory[RVBK] = 1
    emulator.pyboy.memory[RSVBK] = entry_bank
    raw_entry_bank = emulator.pyboy.memory[RSVBK]
    raw_entry_vram_bank = emulator.pyboy.memory[RVBK]
    assert bytes(emulator.pyboy.memory[WRAM_PROGRAM : WRAM_PROGRAM + 4]) == bytes(
        (0xFB, 0xC3, 0x00, 0x01)
    )
    entry_ie = VBLANK_INTERRUPT
    emulator.pyboy.memory[INTERRUPT_ENABLE] = entry_ie
    emulator.pyboy.memory[INTERRUPT_FLAGS] = VBLANK_INTERRUPT
    visible_before = _visible_resources(emulator)
    rom = emulator.rom.read_bytes()
    expected_mapped_rom = rom[
        ENTRY_ROM_BANK * 0x4000 : ENTRY_ROM_BANK * 0x4000 + 64
    ]
    observation: VBlankReturnObservation | None = None

    def returned(_: object) -> None:
        nonlocal observation
        observation = VBlankReturnObservation(
            program_counter=emulator.pyboy.register_file.PC,
            stack_pointer=emulator.pyboy.register_file.SP,
            rsvbk=emulator.pyboy.memory[RSVBK],
            rvbk=emulator.pyboy.memory[RVBK],
            interrupt_enable=emulator.pyboy.memory[INTERRUPT_ENABLE],
            interrupt_flags=emulator.pyboy.memory[INTERRUPT_FLAGS],
            loaded_rom_bank=emulator.pyboy.memory[
                emulator.symbols["hLoadedROMBank"]
            ],
            mapped_rom=bytes(emulator.pyboy.memory[0x4000:0x4040]),
            visible_resources=_visible_resources(emulator),
        )
        emulator.pyboy.memory[INTERRUPT_ENABLE] = 0
        emulator.pyboy.memory[HARNESS_HALT] = 0x76
        emulator.pyboy.register_file.PC = HARNESS_HALT

    emulator.pyboy.hook_register(0, RETURN_PROBE, returned, None)
    try:
        emulator.pyboy.tick(1, render=False, sound=False)
    finally:
        emulator.pyboy.hook_deregister(0, RETURN_PROBE)

    assert observation is not None, "VBlank did not return through RETI"
    assert observation.program_counter == RETURN_PROBE
    assert observation.stack_pointer == 0xFFFC
    assert observation.rsvbk == raw_entry_bank
    assert observation.rvbk == raw_entry_vram_bank
    assert observation.interrupt_enable == entry_ie
    assert observation.interrupt_flags & VBLANK_INTERRUPT == 0
    assert observation.loaded_rom_bank == ENTRY_ROM_BANK
    assert observation.mapped_rom == expected_mapped_rom
    assert observation.visible_resources == visible_before
    assert _read_banked(emulator, LEGACY_BANK, saved_rom_bank) == ENTRY_ROM_BANK
    assert _read_banked(emulator, LEGACY_BANK, disable_wy_update) == 1
    for bank, (disable_alias, saved_alias) in alias_sentinels.items():
        assert _read_banked(emulator, bank, disable_wy_update) == disable_alias
        assert _read_banked(emulator, bank, saved_rom_bank) == saved_alias
