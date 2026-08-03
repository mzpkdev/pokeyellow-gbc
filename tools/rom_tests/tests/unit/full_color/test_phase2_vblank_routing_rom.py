"""Real-interrupt routing checks for the Phase 2 full-color VBlank owner."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    phase2_rom as _phase2_rom,  # noqa: F401 - registered by pytest
)


RSVBK = 0xFF70
RVBK = 0xFF4F
INTERRUPT_FLAGS = 0xFF0F
INTERRUPT_ENABLE = 0xFFFF
BOOTROM_DISABLE = 0xFF50
VBLANK_INTERRUPT = 1 << 0
JOYPAD_INTERRUPT = 1 << 4
WRAM_PROGRAM = 0xD100
RETURN_PROBE = 0x0100
HARNESS_HALT = 0xC6F0
ENTRY_ROM_BANK = 5
ENTRY_WRAM_BANK = 6


YELLOW_VISIBLE_WRITES = {
    "scroll-x register publish": b"\xe0\x43",
    "scroll-y register publish": b"\xe0\x42",
    "window-y register publish": b"\xe0\x4a",
    "legacy hDMARoutine": b"\xcd\x80\xff",
}

YELLOW_VISIBLE_CALLS = (
    "AutoBgMapTransfer",
    "VBlankCopyBgMap",
    "RedrawRowOrColumn",
    "VBlankCopy",
    "VBlankCopyDouble",
    "UpdateMovingBgTiles",
    "PrepareOAMData",
)

COMMON_SERVICE_CALLS = (
    "TrackPlayTime",
    "Random",
    "ReadJoypad",
    "FadeOutAudio",
    "Music_DoLowHealthAlarm",
    "Audio1_UpdateMusic",
    "SerialFunction",
)

YELLOW_VISIBLE_NAMES = (
    "scroll-x register publish",
    "scroll-y register publish",
    "window-y register publish",
    "AutoBgMapTransfer",
    "VBlankCopyBgMap",
    "RedrawRowOrColumn",
    "VBlankCopy",
    "VBlankCopyDouble",
    "UpdateMovingBgTiles",
    "legacy hDMARoutine",
    "PrepareOAMData",
)


@pytest.fixture(name="phase2_rom")
def phase2_rom_fixture(request: pytest.FixtureRequest) -> Phase2Rom:
    return request.getfixturevalue("_phase2_rom")


@dataclass(frozen=True, slots=True)
class VBlankObservation:
    stack_pointer: int
    rsvbk: int
    rvbk: int
    interrupt_enable: int
    interrupt_flags: int
    loaded_rom_bank: int
    mapped_rom: bytes
    call_sites: tuple[str, ...]


def _write_banked(rom: Phase2Rom, bank: int, address: int, data: bytes) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = bank
    try:
        for offset, value in enumerate(data):
            emu.memory[address + offset] = value
    finally:
        emu.memory[RSVBK] = prior


def _read_banked(rom: Phase2Rom, bank: int, address: int, size: int) -> bytes:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = bank
    try:
        return bytes(emu.memory[address + offset] for offset in range(size))
    finally:
        emu.memory[RSVBK] = prior


def _unique_site(blob: bytes, pattern: bytes, *, base: int, name: str) -> int:
    offsets = [
        offset
        for offset in range(len(blob) - len(pattern) + 1)
        if blob[offset:offset + len(pattern)] == pattern
    ]
    assert len(offsets) == 1, f"expected one {name} call site, found {len(offsets)}"
    return base + offsets[0]


def _vblank_call_sites(rom: Phase2Rom) -> dict[int, str]:
    start = rom.emulator.symbols["VBlank"]
    end = rom.emulator.symbols["DelayFrame"]
    blob = rom.emulator.rom.read_bytes()[start:end]
    sites: dict[int, str] = {}
    patterns = dict(YELLOW_VISIBLE_WRITES)
    for name in YELLOW_VISIBLE_CALLS + COMMON_SERVICE_CALLS:
        address = rom.emulator.symbols[name]
        patterns[name] = bytes((0xCD, address & 0xFF, address >> 8))
    for name, pattern in patterns.items():
        sites[_unique_site(blob, pattern, base=start, name=name)] = name
    return sites


def _run_actual_vblank(rom: Phase2Rom) -> VBlankObservation:
    emu = rom.emulator.pyboy
    loaded_bank = rom.emulator.symbols["hLoadedROMBank"]

    # Direct-call fixtures deliberately bypass boot.  Unmap the CGB boot ROM so
    # interrupt vector $0040 is the cartridge's production VBlank vector.
    emu.memory[BOOTROM_DISABLE] = 1

    # First quiesce interrupts in the same non-default bank that will receive
    # RETI.  The WRAM program then requests one real VBlank interrupt and
    # returns to a fixed-bank probe where the state is sampled immediately.
    _write_banked(rom, ENTRY_WRAM_BANK, WRAM_PROGRAM, b"\xf3\x18\xfe")
    emu.memory[INTERRUPT_ENABLE] = 0
    emu.memory[INTERRUPT_FLAGS] = 0
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.register_file.PC = WRAM_PROGRAM
    emu.register_file.SP = 0xFFFC
    emu.tick(1, render=False, sound=False)

    _write_banked(
        rom,
        ENTRY_WRAM_BANK,
        WRAM_PROGRAM,
        bytes((0xFB, 0xC3, RETURN_PROBE & 0xFF, RETURN_PROBE >> 8)),
    )
    emu.register_file.PC = WRAM_PROGRAM
    emu.register_file.SP = 0xFFFC
    emu.memory[0x2000] = ENTRY_ROM_BANK
    emu.memory[0x3000] = 0
    emu.memory[loaded_bank] = ENTRY_ROM_BANK
    emu.memory[RVBK] = 1
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    emu.memory[INTERRUPT_FLAGS] = VBLANK_INTERRUPT | JOYPAD_INTERRUPT

    call_sites: list[str] = []
    observation: VBlankObservation | None = None

    def reached_site(context: str) -> None:
        call_sites.append(context)

    def returned(_: object) -> None:
        nonlocal observation
        observation = VBlankObservation(
            stack_pointer=emu.register_file.SP,
            rsvbk=emu.memory[RSVBK],
            rvbk=emu.memory[RVBK],
            interrupt_enable=emu.memory[INTERRUPT_ENABLE],
            interrupt_flags=emu.memory[INTERRUPT_FLAGS],
            loaded_rom_bank=emu.memory[loaded_bank],
            mapped_rom=bytes(emu.memory[0x4000:0x4040]),
            call_sites=tuple(call_sites),
        )
        emu.memory[INTERRUPT_ENABLE] = 0
        emu.memory[HARNESS_HALT] = 0x76
        emu.register_file.PC = HARNESS_HALT

    sites = _vblank_call_sites(rom)
    for address, name in sites.items():
        emu.hook_register(0, address, reached_site, name)
    emu.hook_register(0, RETURN_PROBE, returned, None)
    try:
        emu.tick(1, render=False, sound=False)
    finally:
        emu.hook_deregister(0, RETURN_PROBE)
        for address in sites:
            emu.hook_deregister(0, address)

    assert observation is not None, (
        "VBlank did not return through RETI "
        f"(PC={emu.register_file.PC:#06x}, SP={emu.register_file.SP:#06x}, "
        f"sites={call_sites[-8:]})"
    )
    return observation


def _assert_all_yellow_visible_writers(observation: VBlankObservation) -> None:
    for name in YELLOW_VISIBLE_NAMES:
        assert name in observation.call_sites, f"Yellow visible writer skipped: {name}"


def test_route1_passive_vblank_keeps_yellow_visible_and_sprite_authority(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C  # ROUTE_1
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] = 0xFF

    observation = _run_actual_vblank(phase2_rom)

    _assert_all_yellow_visible_writers(observation)
    assert tuple(
        name for name in observation.call_sites if name in COMMON_SERVICE_CALLS
    ) == COMMON_SERVICE_CALLS
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )


def test_passive_actual_vblank_runs_yellow_and_restores_raw_machine_state(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    saved_rom_bank = phase2_rom.emulator.symbols["wVBlankSavedROMBank"]
    assert phase2_rom.emulator.symbol_banks["wVBlankSavedROMBank"] == 1

    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] = 0xFF
    _write_banked(
        phase2_rom,
        1,
        phase2_rom.emulator.symbols["wIgnoreInputCounter"],
        b"\x08",
    )
    emu.memory[phase2_rom.emulator.symbols["hFrameCounter"]] = 4
    emu.memory[phase2_rom.emulator.symbols["hVBlankOccurred"]] = 0xA5
    _write_banked(phase2_rom, ENTRY_WRAM_BANK, saved_rom_bank, b"\x6a")
    wram_alias_before = _read_banked(
        phase2_rom, ENTRY_WRAM_BANK, saved_rom_bank, 1,
    )

    observation = _run_actual_vblank(phase2_rom)

    _assert_all_yellow_visible_writers(observation)
    assert _read_banked(
        phase2_rom, 1, phase2_rom.emulator.symbols["wIgnoreInputCounter"], 1,
    ) == b"\x07"
    assert emu.memory[phase2_rom.emulator.symbols["hFrameCounter"]] == 3
    assert emu.memory[phase2_rom.emulator.symbols["hVBlankOccurred"]] == 0
    assert observation.stack_pointer == 0xFFFC
    assert observation.rsvbk == ENTRY_WRAM_BANK
    assert observation.rvbk & 1 == 1
    assert observation.interrupt_enable & 0x1F == VBLANK_INTERRUPT
    assert observation.interrupt_flags & 0x1F == JOYPAD_INTERRUPT
    assert observation.loaded_rom_bank == ENTRY_ROM_BANK
    rom = phase2_rom.emulator.rom.read_bytes()
    assert observation.mapped_rom == rom[
        ENTRY_ROM_BANK * 0x4000:ENTRY_ROM_BANK * 0x4000 + 64
    ]
    assert _read_banked(
        phase2_rom, ENTRY_WRAM_BANK, saved_rom_bank, 1,
    ) == wram_alias_before
    assert _read_banked(phase2_rom, 1, saved_rom_bank, 1) == bytes((ENTRY_ROM_BANK,))


def test_skipped_yellow_writer_mutation_trips_named_routing_assertion(
    phase2_rom: Phase2Rom,
) -> None:
    observation = _run_actual_vblank(phase2_rom)
    observation = VBlankObservation(
        stack_pointer=observation.stack_pointer,
        rsvbk=observation.rsvbk,
        rvbk=observation.rvbk,
        interrupt_enable=observation.interrupt_enable,
        interrupt_flags=observation.interrupt_flags,
        loaded_rom_bank=observation.loaded_rom_bank,
        mapped_rom=observation.mapped_rom,
        call_sites=tuple(
            name for name in observation.call_sites
            if name != "scroll-x register publish"
        ),
    )
    with pytest.raises(
        AssertionError,
        match="Yellow visible writer skipped: scroll-x register publish",
    ):
        _assert_all_yellow_visible_writers(observation)
