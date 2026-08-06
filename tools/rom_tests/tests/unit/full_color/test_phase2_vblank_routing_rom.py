"""Real-interrupt routing checks for the shipped passive Color renderer."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
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
PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
AUTO_BG_TRANSFER_ENABLED = 1 << 0
PASSIVE_OVERLAY_TRANSFER = 1 << 7
VBG_MAP_1 = 0x9C00
OAM_BASE = 0xFE00
HIDDEN_SPRITE_Y = 0xA0

OVERLAY_REDRAW_DEFERRAL_ROUTE = "overlay redraw deferral route"
OVERLAY_REDRAW_BYPASS = "overlay redraw bypass"


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


def _call_sites(
    blob: bytes,
    pattern: bytes,
    *,
    base: int,
    name: str,
    expected: int = 1,
) -> tuple[int, ...]:
    offsets = [
        offset
        for offset in range(len(blob) - len(pattern) + 1)
        if blob[offset:offset + len(pattern)] == pattern
    ]
    assert len(offsets) == expected, (
        f"expected {expected} {name} call site(s), found {len(offsets)}"
    )
    return tuple(base + offset for offset in offsets)


def _relative_jump_site(
    blob: bytes,
    opcode: int,
    *,
    base: int,
    target: int,
    name: str,
) -> int:
    sites = []
    for offset in range(len(blob) - 1):
        displacement = int.from_bytes(blob[offset + 1 : offset + 2], signed=True)
        if blob[offset] == opcode and base + offset + 2 + displacement == target:
            sites.append(base + offset)
    assert len(sites) == 1, f"expected one {name}, found {len(sites)}"
    return sites[0]


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
        for address in _call_sites(
            blob, pattern, base=start, name=name,
        ):
            sites[address] = name

    ordinary_route = rom.emulator.symbols["VBlank.ordinaryAutoBgMapTransfer"]
    redraw_done = rom.emulator.symbols["VBlank.passiveFullColorVBlankDone"]
    oam_route = rom.emulator.symbols["VBlank.yellowOAMOperations"]
    visible_done = rom.emulator.symbols["VBlank.vblankSensitiveOperationsDone"]
    redraw_site = next(
        address for address, name in sites.items() if name == "RedrawRowOrColumn"
    )
    overlay_branch = _relative_jump_site(
        blob,
        0x28,  # JR Z
        base=start,
        target=ordinary_route,
        name="overlay selection branch",
    )
    overlay_bypass = _relative_jump_site(
        blob,
        0x18,  # JR
        base=start,
        target=oam_route,
        name="overlay redraw bypass",
    )
    overlay_route = overlay_branch + 2
    assert (
        overlay_route
        < overlay_bypass
        < ordinary_route
        <= redraw_site
        < redraw_done
        < oam_route
        < visible_done
    )
    sites[overlay_route] = OVERLAY_REDRAW_DEFERRAL_ROUTE
    sites[overlay_bypass] = OVERLAY_REDRAW_BYPASS
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


def test_overlay_vblank_bypasses_and_defers_pending_yellow_redraw(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_TRANSFER
    emu.memory[symbols["hRedrawRowOrColumnMode"]] = 2

    observation = _run_actual_vblank(phase2_rom)

    assert observation.call_sites.index(OVERLAY_REDRAW_DEFERRAL_ROUTE) < (
        observation.call_sites.index(OVERLAY_REDRAW_BYPASS)
    ) < observation.call_sites.index("TrackPlayTime")
    assert "AutoBgMapTransfer" not in observation.call_sites
    assert "VBlankCopyBgMap" not in observation.call_sites
    assert "RedrawRowOrColumn" not in observation.call_sites
    assert "VBlankCopy" not in observation.call_sites
    assert "legacy hDMARoutine" in observation.call_sites
    assert "PrepareOAMData" in observation.call_sites
    assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == 2
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )


def test_overlay_barrier_prepares_then_commits_hidden_oam(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    emu.memory[symbols["wUpdateSpritesEnabled"]] = 0
    emu.memory[symbols["wShadowOAM"]] = 0x40
    emu.memory[OAM_BASE] = 0x20
    emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
    emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
    emu.memory[symbols["hAutoBGTransferPortion"]] = 0
    emu.memory[symbols["hAutoBGTransferEnabled"]] = (
        AUTO_BG_TRANSFER_ENABLED | PASSIVE_OVERLAY_TRANSFER
    )

    attribute_frame = _run_actual_vblank(phase2_rom)

    assert "legacy hDMARoutine" in attribute_frame.call_sites
    assert "PrepareOAMData" in attribute_frame.call_sites
    assert emu.memory[OAM_BASE] == 0x40
    assert emu.memory[symbols["wShadowOAM"]] == HIDDEN_SPRITE_Y

    first_tile_frame = _run_actual_vblank(phase2_rom)

    assert "legacy hDMARoutine" in first_tile_frame.call_sites
    assert "PrepareOAMData" not in first_tile_frame.call_sites
    assert emu.memory[OAM_BASE] == HIDDEN_SPRITE_Y


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
