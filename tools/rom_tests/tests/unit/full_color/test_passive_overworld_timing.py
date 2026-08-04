"""Natural-VBlank timing gates for the shipped passive renderer."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _linked_overworld_tile_attributes,
    numeric_symbols,
)


RSVBK = 0xFF70
RVBK = 0xFF4F
RSTAT = 0xFF41
RLY = 0xFF44
RLYC = 0xFF45
RLCDC = 0xFF40
INTERRUPT_FLAGS = 0xFF0F
INTERRUPT_ENABLE = 0xFFFF
BOOTROM_DISABLE = 0xFF50
VBLANK_INTERRUPT = 1 << 0
STAT_INTERRUPT = 1 << 1
LYC_INTERRUPT_ENABLE = 1 << 6
WRAM_PROGRAM = 0xD100
RETURN_PROBE = 0x0100
RETI_TRAMPOLINE = 0xFF90
HARNESS_HALT = 0xC6F0
ENTRY_ROM_BANK = 5
ENTRY_WRAM_BANK = 6
REAL_BANKED_STACK = 0xDFF0
PALLET_TOWN = 0
VIRIDIAN_CITY = 1
REDRAW_COL = 1
REDRAW_ROW = 2
VBLANK_CYCLES = 10 * 456
VBLANK_TAIL_STAGES = (
    "VBlankCopy",
    "VBlankCopyDouble",
    "UpdateMovingBgTiles",
    "hDMARoutine",
    "PrepareOAMData",
    "TrackPlayTime",
)
WATER_TILE = 0x9140
FLOWER_TILE = 0x9030
TILE_SIZE = 16
SCREEN_WIDTH = 20
SCREEN_HEIGHT = 18
SCREEN_AREA = SCREEN_WIDTH * SCREEN_HEIGHT
VBG_MAP_1 = 0x9C00
AUTO_BG_TRANSFER_ENABLED = 1 << 0
PASSIVE_OVERLAY_ATTRIBUTE_PHASE = 1 << 6
PASSIVE_OVERLAY_COMPLETE = 1 << 5
PASSIVE_OVERLAY_TRANSFER = 1 << 7
OVERLAY_ROWS_PER_PHASE = 2
PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
TIMING_PRODUCTS = PRODUCTS + ("pokeyellow_phase2_audit",)


def _open_product(request: pytest.FixtureRequest, product: str, suffix: str):
    rom = Path(REPOSITORY_ROOT / f"{product}.gbc")
    sym = Path(REPOSITORY_ROOT / f"{product}.sym")
    emulator = Emulator(
        rom=rom,
        symbols=sym,
        results=result_directory(request.node.nodeid) / suffix,
        cgb=True,
    )
    dma_stub = bytes(
        (0x3E, 0xC3, 0xE0, 0x46, 0x3E, 0x28, 0x3D, 0x20, 0xFD, 0xC9)
    )
    for offset, value in enumerate(dma_stub):
        emulator.pyboy.memory[0xFF80 + offset] = value
    return Phase2Rom(emulator, numeric_symbols(sym))


@pytest.fixture(name="phase2_rom", params=PRODUCTS)
def phase2_rom_fixture(request: pytest.FixtureRequest):
    instance = _open_product(request, request.param, request.param)
    try:
        yield instance
    finally:
        instance.emulator.close()


@pytest.fixture
def audit_rom(request: pytest.FixtureRequest):
    instance = _open_product(
        request, "pokeyellow_phase2_audit", "pokeyellow_phase2_audit"
    )
    try:
        yield instance
    finally:
        instance.emulator.close()


@dataclass(frozen=True, slots=True)
class NaturalVBlankMeasurement:
    operation: str
    vblank_cycle: int
    vblank_ly: int
    passive_entry_cycle: int | None
    passive_entry_ly: int | None
    passive_end_cycle: int | None
    passive_end_ly: int | None
    tail_end_cycle: int
    tail_end_ly: int
    deadline_span: int
    downstream: tuple[tuple[str, int, int], ...]

    @property
    def passive_headroom(self) -> int:
        assert self.passive_end_cycle is not None
        return self.vblank_cycle + self.deadline_span - self.passive_end_cycle

    @property
    def full_tail_headroom(self) -> int:
        return self.vblank_cycle + self.deadline_span - self.tail_end_cycle


def _write_banked(rom: Phase2Rom, bank: int, address: int, data: bytes) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = bank
    try:
        for offset, value in enumerate(data):
            emu.memory[address + offset] = value
    finally:
        emu.memory[RSVBK] = prior


def _write_vram(rom: Phase2Rom, bank: int, address: int, data: bytes) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RVBK]
    emu.memory[RVBK] = bank
    try:
        for offset, value in enumerate(data):
            emu.memory[address + offset] = value
    finally:
        emu.memory[RVBK] = prior


def _calibrate_natural_vblank_deadline(rom: Phase2Rom) -> int:
    """Measure natural LY144 VBlank-vector to natural LY0 STAT-vector cycles."""
    emu = rom.emulator.pyboy
    checkpoint = BytesIO()
    emu.save_state(checkpoint)
    regs = emu.register_file
    observed: dict[str, tuple[int, int]] = {}
    _write_banked(rom, ENTRY_WRAM_BANK, WRAM_PROGRAM, b"\xfb\x76\x76\x18\xfd")
    emu.memory[RETI_TRAMPOLINE] = 0xD9
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[RLCDC] |= 0x80
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.memory[INTERRUPT_FLAGS] = 0
    emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    regs.PC = WRAM_PROGRAM
    regs.SP = 0xFFFC

    def vblank_vector(_: object) -> None:
        observed["vblank"] = (emu._cycles(), emu.memory[RLY])
        emu.memory[RLYC] = 0
        emu.memory[RSTAT] |= LYC_INTERRUPT_ENABLE
        emu.memory[INTERRUPT_ENABLE] = STAT_INTERRUPT
        emu.memory[INTERRUPT_FLAGS] = 0
        regs.PC = RETI_TRAMPOLINE

    def ly0_vector(_: object) -> None:
        observed["ly0"] = (emu._cycles(), emu.memory[RLY])
        emu.memory[INTERRUPT_ENABLE] = 0
        emu.memory[HARNESS_HALT] = 0x76
        regs.PC = HARNESS_HALT

    emu.hook_register(0, 0x0040, vblank_vector, None)
    emu.hook_register(0, 0x0048, ly0_vector, None)
    try:
        for _ in range(3):
            emu.tick(1, render=False, sound=False)
            if "ly0" in observed:
                break
    finally:
        emu.hook_deregister(0, 0x0040)
        emu.hook_deregister(0, 0x0048)
        checkpoint.seek(0)
        emu.load_state(checkpoint)
    assert observed["vblank"][1] == 144
    assert observed["ly0"][1] == 0
    span = observed["ly0"][0] - observed["vblank"][0]
    assert span == VBLANK_CYCLES
    return span


def _run_natural_vblank(
    rom: Phase2Rom,
    *,
    operation: str,
    expect_passive: bool,
    passive_symbol: str = "PassiveFullColorVBlank",
    finish_interrupt: bool = False,
) -> NaturalVBlankMeasurement:
    emu = rom.emulator.pyboy
    regs = emu.register_file
    symbols = rom.emulator.symbols
    deadline_span = _calibrate_natural_vblank_deadline(rom)
    observed: dict[str, tuple[int, int]] = {}
    downstream: list[tuple[str, int, int]] = []
    _write_banked(
        rom,
        ENTRY_WRAM_BANK,
        WRAM_PROGRAM,
        # EI takes effect after the following instruction. Keep an explicit NOP
        # before HALT so a pending VBlank cannot trigger the HALT bug and make a
        # one-interrupt measurement silently consume the next frame as well.
        bytes((0xFB, 0x00, 0x76, 0xC3, RETURN_PROBE & 0xFF, RETURN_PROBE >> 8)),
    )
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[RLCDC] |= 0x80
    emu.memory[0x2000] = ENTRY_ROM_BANK
    emu.memory[0x3000] = 0
    emu.memory[symbols["hLoadedROMBank"]] = ENTRY_ROM_BANK
    emu.memory[RVBK] = 1
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.memory[INTERRUPT_FLAGS] = 0
    emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    regs.PC = WRAM_PROGRAM
    regs.SP = 0xFFFC

    def mark_vblank(_: object) -> None:
        observed["vblank"] = (emu._cycles(), emu.memory[RLY])
        if finish_interrupt:
            # Return directly to the probe after this one ISR. Depending on
            # pending-interrupt timing, a HALT-based harness can otherwise
            # remain asleep and silently execute a second VBlank before Python
            # regains control.
            emu.memory[regs.SP] = RETURN_PROBE & 0xFF
            emu.memory[regs.SP + 1] = RETURN_PROBE >> 8

    def mark_passive(_: object) -> None:
        observed["passive"] = (emu._cycles(), emu.memory[RLY])

    def mark_downstream(name: str) -> None:
        if not any(item[0] == name for item in downstream):
            downstream.append((name, emu._cycles(), emu.memory[RLY]))
        if name == "VBlankCopy" and expect_passive:
            observed["passive_end"] = (emu._cycles(), emu.memory[RLY])
        if name == VBLANK_TAIL_STAGES[-1]:
            observed["complete"] = (emu._cycles(), emu.memory[RLY])
            if finish_interrupt:
                return
            emu.memory[INTERRUPT_ENABLE] = 0
            emu.memory[HARNESS_HALT] = 0x76
            regs.PC = HARNESS_HALT

    def mark_return(_: object) -> None:
        observed["returned"] = (emu._cycles(), emu.memory[RLY])
        emu.memory[INTERRUPT_ENABLE] = 0
        # Leave the emulator in an executable spin loop so a direct-call setup
        # can arm the next frame after this warm VBlank. A CPU left internally
        # halted cannot reliably be resumed merely by assigning PC.
        emu.memory[HARNESS_HALT] = 0x18
        emu.memory[HARNESS_HALT + 1] = 0xFE
        regs.PC = HARNESS_HALT

    hooks: list[tuple[int, int]] = [(0, symbols["VBlank"])]
    emu.hook_register(0, symbols["VBlank"], mark_vblank, None)
    if finish_interrupt:
        hooks.append((0, RETURN_PROBE))
        emu.hook_register(0, RETURN_PROBE, mark_return, None)
    if expect_passive:
        passive_bank = rom.emulator.symbol_banks[passive_symbol]
        passive_address = symbols[passive_symbol]
        hooks.append((passive_bank, passive_address))
        emu.hook_register(passive_bank, passive_address, mark_passive, None)
    for name in VBLANK_TAIL_STAGES:
        if name == "hDMARoutine":
            start = symbols["VBlank"]
            blob = rom.emulator.rom.read_bytes()[start : symbols["DelayFrame"]]
            pattern = bytes((0xCD, symbols[name] & 0xFF, symbols[name] >> 8))
            assert blob.count(pattern) == 1
            bank = 0
            address = start + blob.index(pattern)
        else:
            bank = rom.emulator.symbol_banks[name]
            address = symbols[name]
        hooks.append((bank, address))
        emu.hook_register(bank, address, mark_downstream, name)
    try:
        for _ in range(3):
            emu.tick(1, render=False, sound=False)
            if (finish_interrupt and "returned" in observed) or (
                not finish_interrupt and "complete" in observed
            ):
                break
    finally:
        for bank, address in hooks:
            emu.hook_deregister(bank, address)
    assert observed["vblank"][1] == 144
    assert "complete" in observed
    assert tuple(item[0] for item in downstream) == VBLANK_TAIL_STAGES
    if expect_passive:
        assert {"passive", "passive_end"} <= observed.keys()
    vblank_cycle, vblank_ly = observed["vblank"]
    passive = observed.get("passive")
    passive_end = observed.get("passive_end")
    tail_end_cycle, tail_end_ly = observed["complete"]
    return NaturalVBlankMeasurement(
        operation=operation,
        vblank_cycle=vblank_cycle,
        vblank_ly=vblank_ly,
        passive_entry_cycle=None if passive is None else passive[0],
        passive_entry_ly=None if passive is None else passive[1],
        passive_end_cycle=None if passive_end is None else passive_end[0],
        passive_end_ly=None if passive_end is None else passive_end[1],
        tail_end_cycle=tail_end_cycle,
        tail_end_ly=tail_end_ly,
        deadline_span=deadline_span,
        downstream=tuple(downstream),
    )


def _activate_passive_map(rom: Phase2Rom) -> None:
    emu = rom.emulator.pyboy
    rom.call("InitRendererOwnership")
    emu.memory[rom.emulator.symbols["wCurMap"]] = PALLET_TOWN
    emu.memory[RLCDC] &= 0x7F
    rom.call("PassiveFullColorApplyMap")


def _assert_passive_finishes_before_ly0(measurement: NaturalVBlankMeasurement) -> None:
    assert measurement.passive_end_ly is not None
    assert 144 <= measurement.passive_end_ly <= 153, (
        f"{measurement.operation}: passive work ended at LY"
        f"{measurement.passive_end_ly} with {measurement.passive_headroom} "
        "cycles of natural VBlank headroom"
    )
    assert measurement.passive_headroom > 0
    for name, cycle, ly in measurement.downstream:
        headroom = measurement.vblank_cycle + measurement.deadline_span - cycle
        if name == "UpdateMovingBgTiles" and ly < 144:
            assert ly == 0 and headroom > 0, (
                f"{measurement.operation}: animation guard reached unexpected active "
                f"scanline LY{ly} with {headroom} cycles of calibrated headroom"
            )
            break
        assert 144 <= ly <= 153 and headroom > 0, (
            f"{measurement.operation}: downstream Yellow writer {name} reached "
            f"LY{ly} with {headroom} cycles of natural VBlank headroom"
        )
        if name == "UpdateMovingBgTiles":
            break


def _assert_complete_vblank_tail_finishes_before_ly0(
    measurement: NaturalVBlankMeasurement,
) -> None:
    assert 144 <= measurement.tail_end_ly <= 153, (
        f"{measurement.operation}: complete VBlank-sensitive tail reached LY"
        f"{measurement.tail_end_ly} with {measurement.full_tail_headroom} "
        "cycles of calibrated headroom"
    )
    assert measurement.full_tail_headroom > 0
    for name, cycle, ly in measurement.downstream:
        headroom = measurement.vblank_cycle + measurement.deadline_span - cycle
        assert 144 <= ly <= 153 and headroom > 0, (
            f"{measurement.operation}: VBlank tail stage {name} reached "
            f"LY{ly} with {headroom} cycles of natural VBlank headroom"
        )


def _assert_natural_vblank_restores_real_banked_cpu_state(
    phase2_rom: Phase2Rom,
) -> None:
    """Interrupt WRAM6 and require the complete VBlank ABI to round-trip."""
    emu = phase2_rom.emulator.pyboy
    regs = emu.register_file
    symbols = phase2_rom.emulator.symbols
    _write_banked(
        phase2_rom,
        ENTRY_WRAM_BANK,
        WRAM_PROGRAM,
        bytes((0xFB, 0x76, 0xC3, RETURN_PROBE & 0xFF, RETURN_PROBE >> 8)),
    )
    _write_banked(
        phase2_rom,
        1,
        REAL_BANKED_STACK - 0x40,
        bytes((0x05,)) * 0x40,
    )
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[RLCDC] |= 0x80
    emu.memory[0x2000] = ENTRY_ROM_BANK
    emu.memory[0x3000] = 0
    emu.memory[symbols["hLoadedROMBank"]] = ENTRY_ROM_BANK
    emu.memory[RVBK] = 1
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.memory[INTERRUPT_FLAGS] = 0
    emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    regs.PC = WRAM_PROGRAM
    regs.SP = REAL_BANKED_STACK
    regs.A = 0x12
    regs.F = 0xB0
    regs.B = 0x34
    regs.C = 0x56
    regs.D = 0x78
    regs.E = 0x9A
    regs.HL = 0xBCDE

    observed: dict[str, tuple[int, ...]] = {}

    def returned(_: object) -> None:
        observed["state"] = (
            regs.PC,
            regs.SP,
            emu.memory[RSVBK] & 0x07,
            emu.memory[RVBK] & 0x01,
            emu.memory[symbols["hLoadedROMBank"]],
            regs.A,
            regs.F,
            regs.B,
            regs.C,
            regs.D,
            regs.E,
            regs.HL,
        )
        emu.memory[INTERRUPT_ENABLE] = 0
        emu.memory[HARNESS_HALT] = 0x76
        regs.PC = HARNESS_HALT

    emu.hook_register(0, RETURN_PROBE, returned, None)
    try:
        for _ in range(3):
            emu.tick(1, render=False, sound=False)
            if "state" in observed:
                break
    finally:
        emu.hook_deregister(0, RETURN_PROBE)

    assert observed.get("state") == (
        RETURN_PROBE,
        REAL_BANKED_STACK,
        ENTRY_WRAM_BANK,
        1,
        ENTRY_ROM_BANK,
        0x12,
        0xB0,
        0x34,
        0x56,
        0x78,
        0x9A,
        0xBCDE,
    )


def _initial_animation_tile() -> bytes:
    return bytes((0x81 + offset * 7) & 0xFF for offset in range(TILE_SIZE))


def _expected_animation_update(
    rom: Phase2Rom, counter: int,
) -> tuple[int, bytes]:
    if counter == 19:
        return 1, bytes(
            (value >> 1) | ((value & 1) << 7)
            for value in _initial_animation_tile()
        )
    assert counter == 20
    symbols = rom.emulator.symbols
    return 0, rom.emulator.read_memory(symbols["FlowerTile1"], TILE_SIZE)


def _assert_single_bounded_animation_update(
    rom: Phase2Rom,
    *,
    counter: int,
    write_frame: int,
    entries: tuple[tuple[int, int], ...],
    writes: tuple[tuple[int, int, int], ...],
    returns: tuple[tuple[int, int, bytes], ...],
) -> None:
    assert tuple(frame for frame, _ in entries) == (1, 2)
    assert len(writes) == TILE_SIZE
    assert {frame for frame, _, _ in writes} == {write_frame}
    assert all(144 <= ly <= 153 for _, ly, _ in writes), writes

    moving_counter, expected_tile = _expected_animation_update(rom, counter)
    if write_frame == 1:
        assert returns == (
            (0, moving_counter, expected_tile),
            (1, moving_counter, expected_tile),
        )
    else:
        assert returns == (
            (counter, 0, _initial_animation_tile()),
            (0, moving_counter, expected_tile),
        )


def _run_animation_across_two_vblanks(
    rom: Phase2Rom,
    *,
    counter: int,
    tile_address: int,
    overlay_phase: bool = False,
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int, int], ...],
    tuple[tuple[int, int, bytes], ...],
]:
    """Run, rather than intercept, moving-tile work across two VBlanks."""
    emu = rom.emulator.pyboy
    regs = emu.register_file
    symbols = rom.emulator.symbols
    initial_tile = _initial_animation_tile()
    prior_vbk = emu.memory[RVBK]
    emu.memory[RVBK] = 0
    try:
        for offset, value in enumerate(initial_tile):
            emu.memory[tile_address + offset] = value
    finally:
        emu.memory[RVBK] = prior_vbk
    emu.memory[symbols["hTileAnimations"]] = 1
    emu.memory[symbols["hMovingBGTilesCounter1"]] = counter
    _write_banked(rom, 1, symbols["wMovingBGTilesCounter2"], b"\x00")
    if overlay_phase:
        rom.write_fixed(symbols["wTileMap"], b"\x80" * SCREEN_AREA)
        emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
        emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
        emu.memory[symbols["hAutoBGTransferPortion"]] = 0
        emu.memory[symbols["hAutoBGTransferEnabled"]] = (
            AUTO_BG_TRANSFER_ENABLED
            | PASSIVE_OVERLAY_TRANSFER
            | PASSIVE_OVERLAY_COMPLETE
        )

    _write_banked(
        rom,
        ENTRY_WRAM_BANK,
        WRAM_PROGRAM,
        bytes((0xFB, 0x76, 0xC3, RETURN_PROBE & 0xFF, RETURN_PROBE >> 8)),
    )
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[RLCDC] |= 0x80
    emu.memory[0x2000] = ENTRY_ROM_BANK
    emu.memory[0x3000] = 0
    emu.memory[symbols["hLoadedROMBank"]] = ENTRY_ROM_BANK
    emu.memory[RVBK] = 1
    emu.memory[RSVBK] = ENTRY_WRAM_BANK
    emu.memory[INTERRUPT_FLAGS] = 0
    emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    regs.PC = WRAM_PROGRAM
    regs.SP = 0xFFFC

    frame = 0
    entries: list[tuple[int, int]] = []
    writes: list[tuple[int, int, int]] = []
    returns: list[tuple[int, int, bytes]] = []

    def mark_vblank(_: object) -> None:
        nonlocal frame
        frame += 1

    def mark_animation_entry(_: object) -> None:
        entries.append((frame, emu.memory[RLY]))

    def mark_animation_write(_: object) -> None:
        writes.append((frame, emu.memory[RLY], regs.PC))

    def returned(_: object) -> None:
        prior_vbk = emu.memory[RVBK]
        prior_svbk = emu.memory[RSVBK]
        emu.memory[RVBK] = 0
        emu.memory[RSVBK] = 1
        tile = bytes(emu.memory[tile_address + offset] for offset in range(TILE_SIZE))
        moving_counter = emu.memory[symbols["wMovingBGTilesCounter2"]]
        emu.memory[RSVBK] = prior_svbk
        emu.memory[RVBK] = prior_vbk
        returns.append(
            (
                emu.memory[symbols["hMovingBGTilesCounter1"]],
                moving_counter,
                tile,
            )
        )
        if len(returns) == 1:
            if overlay_phase:
                emu.memory[symbols["hAutoBGTransferEnabled"]] = 0
            emu.memory[INTERRUPT_FLAGS] = 0
            emu.memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
            regs.PC = WRAM_PROGRAM
        else:
            emu.memory[INTERRUPT_ENABLE] = 0
            emu.memory[HARNESS_HALT] = 0x76
            regs.PC = HARNESS_HALT

    write_sites = (
        symbols["UpdateMovingBgTiles.right"] + 2,
        symbols["UpdateMovingBgTiles.left"] + 2,
        symbols["UpdateMovingBgTiles.loop"] + 1,
    )
    emu.hook_register(0, symbols["VBlank"], mark_vblank, None)
    emu.hook_register(
        0,
        symbols["UpdateMovingBgTiles"],
        mark_animation_entry,
        None,
    )
    emu.hook_register(0, RETURN_PROBE, returned, None)
    for site in write_sites:
        emu.hook_register(0, site, mark_animation_write, None)
    try:
        for _ in range(4):
            emu.tick(1, render=False, sound=False)
            if len(returns) == 2:
                break
    finally:
        emu.hook_deregister(0, symbols["VBlank"])
        emu.hook_deregister(0, symbols["UpdateMovingBgTiles"])
        emu.hook_deregister(0, RETURN_PROBE)
        for site in write_sites:
            emu.hook_deregister(0, site)

    assert len(returns) == 2
    assert frame == 2
    return tuple(entries), tuple(writes), tuple(returns)


@pytest.mark.parametrize(
    ("case", "mode"),
    (("idle", 0), ("pending+row", REDRAW_ROW), ("pending+column", REDRAW_COL)),
)
def test_passive_paths_finish_before_natural_ly0(
    phase2_rom: Phase2Rom, case: str, mode: int,
) -> None:
    _activate_passive_map(phase2_rom)
    symbols = phase2_rom.emulator.symbols
    emu = phase2_rom.emulator.pyboy
    if mode:
        phase2_rom.write_fixed(
            symbols["wRedrawRowOrColumnSrcTiles"], bytes(range(40))
        )
        emu.memory[symbols["hRedrawRowOrColumnDest"]] = 0x20
        emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = 0x98
        if mode == REDRAW_ROW:
            phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
        else:
            phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
        emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode
        emu.memory[symbols["hAutoBGTransferEnabled"]] = 0
        phase2_rom.call("PassiveFullColorHandleConnection")

    measurement = _run_natural_vblank(
        phase2_rom, operation=case, expect_passive=True,
    )

    _assert_passive_finishes_before_ly0(measurement)


@pytest.mark.parametrize(
    (
        "case",
        "phase_flags",
        "expected_portion",
        "expected_attribute_phase",
        "expected_complete",
        "expected_bank",
    ),
    (
        (
            "paired-overlay attributes",
            PASSIVE_OVERLAY_TRANSFER | PASSIVE_OVERLAY_ATTRIBUTE_PHASE,
            0,
            False,
            False,
            1,
        ),
        (
            "paired-overlay tiles",
            PASSIVE_OVERLAY_TRANSFER,
            OVERLAY_ROWS_PER_PHASE,
            True,
            False,
            0,
        ),
        (
            "coherent-overlay tiles",
            PASSIVE_OVERLAY_TRANSFER | PASSIVE_OVERLAY_COMPLETE,
            OVERLAY_ROWS_PER_PHASE,
            False,
            True,
            0,
        ),
    ),
)
@pytest.mark.parametrize("product", TIMING_PRODUCTS)
def test_bounded_overlay_phase_leaves_complete_vblank_tail_headroom(
    request: pytest.FixtureRequest,
    product: str,
    case: str,
    phase_flags: int,
    expected_portion: int,
    expected_attribute_phase: bool,
    expected_complete: bool,
    expected_bank: int,
) -> None:
    phase2_rom = _open_product(request, product, product)
    try:
        _activate_passive_map(phase2_rom)
        emu = phase2_rom.emulator.pyboy
        symbols = phase2_rom.emulator.symbols
        phase2_rom.write_fixed(
            symbols["wTileMap"],
            b"\x80" * SCREEN_AREA,
        )
        phase2_rom.call("PassiveFullColorTranslateTileMap")
        extent = SCREEN_HEIGHT * 32
        _write_vram(phase2_rom, 0, VBG_MAP_1, b"\x55" * extent)
        _write_vram(phase2_rom, 1, VBG_MAP_1, b"\xee" * extent)
        emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
        emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
        emu.memory[symbols["hAutoBGTransferPortion"]] = 0
        emu.memory[symbols["hAutoBGTransferEnabled"]] = (
            AUTO_BG_TRANSFER_ENABLED | phase_flags
        )
        emu.memory[symbols["hTileAnimations"]] = 1
        emu.memory[symbols["hMovingBGTilesCounter1"]] = 19

        measurement = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} {case}",
            expect_passive=True,
            passive_symbol="PassiveFullColorAutoBgMapTransfer",
        )

        _assert_passive_finishes_before_ly0(measurement)
        _assert_complete_vblank_tail_finishes_before_ly0(measurement)
        assert emu.memory[symbols["hMovingBGTilesCounter1"]] == 19
        assert emu.memory[symbols["hAutoBGTransferPortion"]] == expected_portion
        enabled = emu.memory[symbols["hAutoBGTransferEnabled"]]
        assert (
            bool(enabled & PASSIVE_OVERLAY_ATTRIBUTE_PHASE)
            is expected_attribute_phase
        )
        assert bool(enabled & PASSIVE_OVERLAY_COMPLETE) is expected_complete
        expected_writes = {
            row * 32 + column
            for row in range(OVERLAY_ROWS_PER_PHASE)
            for column in range(SCREEN_WIDTH)
        }
        bank0 = phase2_rom.emulator.read_vram_bank(0, VBG_MAP_1, extent)
        bank1 = phase2_rom.emulator.read_vram_bank(1, VBG_MAP_1, extent)
        changed0 = {index for index, value in enumerate(bank0) if value != 0x55}
        changed1 = {index for index, value in enumerate(bank1) if value != 0xEE}
        assert (changed0, changed1) == (
            (expected_writes, set()) if expected_bank == 0
            else (set(), expected_writes)
        )
    finally:
        phase2_rom.emulator.close()


@pytest.mark.parametrize("mode", (REDRAW_ROW, REDRAW_COL))
@pytest.mark.parametrize("product", TIMING_PRODUCTS)
def test_overlay_defers_armed_redraw_until_overlay_clears(
    request: pytest.FixtureRequest,
    product: str,
    mode: int,
) -> None:
    phase2_rom = _open_product(request, product, product)
    try:
        _activate_passive_map(phase2_rom)
        emu = phase2_rom.emulator.pyboy
        symbols = phase2_rom.emulator.symbols
        destination = 0x9820
        source = bytes(0x80 + index for index in range(40))
        attributes = _linked_overworld_tile_attributes(phase2_rom)
        phase2_rom.write_fixed(symbols["wRedrawRowOrColumnSrcTiles"], source)
        emu.memory[symbols["hRedrawRowOrColumnDest"]] = destination & 0xFF
        emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = destination >> 8
        if mode == REDRAW_ROW:
            phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
            staging_size = SCREEN_WIDTH * 4
            redraw_addresses = tuple(
                range(destination, destination + SCREEN_WIDTH)
            ) + tuple(
                range(
                    destination + 32,
                    destination + 32 + SCREEN_WIDTH,
                )
            )
        else:
            phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
            staging_size = SCREEN_HEIGHT * 4
            redraw_addresses = tuple(
                destination + row * 32 + column
                for row in range(SCREEN_HEIGHT)
                for column in range(2)
            )
        frozen_redraw = phase2_rom.read_wram2(
            "wPassiveFullColorRedrawStaging", staging_size
        )
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == bytes((0x80 | mode,))
        frozen_destinations = tuple(
            frozen_redraw[index] | (frozen_redraw[index + 1] << 8)
            for index in range(0, staging_size, 4)
        )
        assert all(0x9800 <= address <= 0x9FFF for address in frozen_destinations)

        # Exercise the hostile order: overlay translation happens only after the
        # redraw records are frozen, then owns one complete natural VBlank.
        phase2_rom.write_fixed(symbols["wTileMap"], b"\x70" * SCREEN_AREA)
        phase2_rom.call("PassiveFullColorTranslateTileMap")
        assert phase2_rom.read_wram2(
            "wPassiveFullColorRedrawStaging", staging_size
        ) == frozen_redraw
        emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode
        _write_vram(phase2_rom, 0, 0x9800, b"\x55" * 0x400)
        _write_vram(phase2_rom, 1, 0x9800, b"\xee" * 0x400)
        emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
        emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
        emu.memory[symbols["hAutoBGTransferPortion"]] = 0
        emu.memory[symbols["hAutoBGTransferEnabled"]] = (
            AUTO_BG_TRANSFER_ENABLED
            | PASSIVE_OVERLAY_TRANSFER
            | PASSIVE_OVERLAY_COMPLETE
        )

        overlay = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} overlay+redraw {mode}",
            expect_passive=True,
            passive_symbol="PassiveFullColorAutoBgMapTransfer",
            finish_interrupt=True,
        )

        _assert_complete_vblank_tail_finishes_before_ly0(overlay)
        assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == mode
        assert phase2_rom.read_wram2(
            "wPassiveFullColorRedrawStaging", staging_size
        ) == frozen_redraw
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == bytes((0x80 | mode,))
        bank0 = phase2_rom.emulator.read_vram_bank(0, 0x9800, 0x400)
        bank1 = phase2_rom.emulator.read_vram_bank(1, 0x9800, 0x400)
        assert all(bank0[address - 0x9800] == 0x55 for address in redraw_addresses)
        assert all(bank1[address - 0x9800] == 0xEE for address in redraw_addresses)

        emu.memory[symbols["hAutoBGTransferEnabled"]] = 0
        yellow_redraw = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} deferred Yellow redraw {mode}",
            expect_passive=True,
            passive_symbol="PassiveFullColorScheduleRedrawMirror",
            finish_interrupt=True,
        )

        _assert_passive_finishes_before_ly0(yellow_redraw)
        _assert_complete_vblank_tail_finishes_before_ly0(yellow_redraw)
        assert emu.memory[symbols["hRedrawRowOrColumnMode"]] == 0
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == bytes((mode,))
        bank0 = phase2_rom.emulator.read_vram_bank(0, 0x9800, 0x400)
        bank1 = phase2_rom.emulator.read_vram_bank(1, 0x9800, 0x400)
        assert bytes(
            bank0[address - 0x9800] for address in redraw_addresses
        ) == source[: len(redraw_addresses)]
        assert all(bank1[address - 0x9800] == 0xEE for address in redraw_addresses)

        passive_mirror = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} deferred passive mirror {mode}",
            expect_passive=True,
            finish_interrupt=True,
        )

        _assert_passive_finishes_before_ly0(passive_mirror)
        _assert_complete_vblank_tail_finishes_before_ly0(passive_mirror)
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == b"\x00"
        bank0 = phase2_rom.emulator.read_vram_bank(0, 0x9800, 0x400)
        bank1 = phase2_rom.emulator.read_vram_bank(1, 0x9800, 0x400)
        assert bytes(
            bank0[address - 0x9800] for address in redraw_addresses
        ) == source[: len(redraw_addresses)]
        assert bytes(
            bank1[address - 0x9800] for address in redraw_addresses
        ) == bytes(attributes[tile] for tile in source[: len(redraw_addresses)])
    finally:
        phase2_rom.emulator.close()


@pytest.mark.parametrize("mode", (REDRAW_ROW, REDRAW_COL))
@pytest.mark.parametrize("product", TIMING_PRODUCTS)
def test_warm_idle_then_ordinary_redraw_keeps_both_full_vblank_tails_in_budget(
    request: pytest.FixtureRequest,
    product: str,
    mode: int,
) -> None:
    phase2_rom = _open_product(request, product, product)
    try:
        _activate_passive_map(phase2_rom)
        emu = phase2_rom.emulator.pyboy
        symbols = phase2_rom.emulator.symbols
        destination = 0x9820
        source = bytes(0x80 + index for index in range(40))
        attributes = _linked_overworld_tile_attributes(phase2_rom)

        # Pay one-time cold VBlank costs before the ordinary redraw is armed.
        _run_natural_vblank(
            phase2_rom,
            operation=f"{product} warm idle",
            expect_passive=True,
            finish_interrupt=True,
        )

        phase2_rom.write_fixed(symbols["wRedrawRowOrColumnSrcTiles"], source)
        emu.memory[symbols["hRedrawRowOrColumnDest"]] = destination & 0xFF
        emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = destination >> 8
        if mode == REDRAW_ROW:
            phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
            redraw_addresses = tuple(
                range(destination, destination + SCREEN_WIDTH)
            ) + tuple(
                range(destination + 32, destination + 32 + SCREEN_WIDTH)
            )
        else:
            phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
            redraw_addresses = tuple(
                destination + row * 32 + column
                for row in range(SCREEN_HEIGHT)
                for column in range(2)
            )
        _write_vram(phase2_rom, 0, 0x9800, b"\x55" * 0x400)
        _write_vram(phase2_rom, 1, 0x9800, b"\xee" * 0x400)
        emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode

        yellow_redraw = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} warm ordinary Yellow redraw {mode}",
            expect_passive=True,
            passive_symbol="PassiveFullColorScheduleRedrawMirror",
            finish_interrupt=True,
        )

        _assert_passive_finishes_before_ly0(yellow_redraw)
        _assert_complete_vblank_tail_finishes_before_ly0(yellow_redraw)
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == bytes((mode,))
        bank0 = phase2_rom.emulator.read_vram_bank(0, 0x9800, 0x400)
        bank1 = phase2_rom.emulator.read_vram_bank(1, 0x9800, 0x400)
        assert bytes(
            bank0[address - 0x9800] for address in redraw_addresses
        ) == source[: len(redraw_addresses)]
        assert all(bank1[address - 0x9800] == 0xEE for address in redraw_addresses)

        passive_mirror = _run_natural_vblank(
            phase2_rom,
            operation=f"{product} warm ordinary passive mirror {mode}",
            expect_passive=True,
            finish_interrupt=True,
        )

        _assert_passive_finishes_before_ly0(passive_mirror)
        _assert_complete_vblank_tail_finishes_before_ly0(passive_mirror)
        assert phase2_rom.read_wram2(
            "wPassiveFullColorDeferredRedrawState"
        ) == b"\x00"
        bank0 = phase2_rom.emulator.read_vram_bank(0, 0x9800, 0x400)
        bank1 = phase2_rom.emulator.read_vram_bank(1, 0x9800, 0x400)
        assert bytes(
            bank0[address - 0x9800] for address in redraw_addresses
        ) == source[: len(redraw_addresses)]
        assert bytes(
            bank1[address - 0x9800] for address in redraw_addresses
        ) == bytes(attributes[tile] for tile in source[: len(redraw_addresses)])
    finally:
        phase2_rom.emulator.close()


def test_paired_overlay_publication_completes_only_after_exact_row_pairs(
    phase2_rom: Phase2Rom,
) -> None:
    _activate_passive_map(phase2_rom)
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    tiles = bytes((0x80 + index) & 0xFF for index in range(SCREEN_AREA))
    phase2_rom.write_fixed(symbols["wTileMap"], tiles)
    phase2_rom.call("PassiveFullColorTranslateTileMap")
    _write_vram(phase2_rom, 0, VBG_MAP_1, b"\x55" * (SCREEN_HEIGHT * 32))
    _write_vram(phase2_rom, 1, VBG_MAP_1, b"\xee" * (SCREEN_HEIGHT * 32))
    emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
    emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
    emu.memory[symbols["hAutoBGTransferPortion"]] = 0
    emu.memory[symbols["hAutoBGTransferEnabled"]] = (
        AUTO_BG_TRANSFER_ENABLED
        | PASSIVE_OVERLAY_TRANSFER
        | PASSIVE_OVERLAY_ATTRIBUTE_PHASE
    )

    for row in range(0, SCREEN_HEIGHT, OVERLAY_ROWS_PER_PHASE):
        phase2_rom.call("PassiveFullColorAutoBgMapTransfer")
        enabled = emu.memory[symbols["hAutoBGTransferEnabled"]]
        assert not enabled & PASSIVE_OVERLAY_ATTRIBUTE_PHASE
        assert not enabled & PASSIVE_OVERLAY_COMPLETE
        assert emu.memory[symbols["hAutoBGTransferPortion"]] == row
        bank0 = phase2_rom.emulator.read_vram_bank(
            0, VBG_MAP_1, SCREEN_HEIGHT * 32
        )
        bank1 = phase2_rom.emulator.read_vram_bank(
            1, VBG_MAP_1, SCREEN_HEIGHT * 32
        )
        for published_row in range(SCREEN_HEIGHT):
            bank0_published = published_row < row
            bank1_published = published_row < row + OVERLAY_ROWS_PER_PHASE
            offset = published_row * 32
            assert (
                bank0[offset : offset + SCREEN_WIDTH] != b"\x55" * SCREEN_WIDTH
            ) is bank0_published
            assert (
                bank1[offset : offset + SCREEN_WIDTH] != b"\xee" * SCREEN_WIDTH
            ) is bank1_published

        phase2_rom.call("PassiveFullColorAutoBgMapTransfer")
        enabled = emu.memory[symbols["hAutoBGTransferEnabled"]]
        expected_row = (row + OVERLAY_ROWS_PER_PHASE) % SCREEN_HEIGHT
        assert emu.memory[symbols["hAutoBGTransferPortion"]] == expected_row
        assert bool(enabled & PASSIVE_OVERLAY_COMPLETE) is (
            row + OVERLAY_ROWS_PER_PHASE == SCREEN_HEIGHT
        )
        assert bool(enabled & PASSIVE_OVERLAY_ATTRIBUTE_PHASE) is (
            row + OVERLAY_ROWS_PER_PHASE < SCREEN_HEIGHT
        )
        bank0 = phase2_rom.emulator.read_vram_bank(
            0, VBG_MAP_1, SCREEN_HEIGHT * 32
        )
        bank1 = phase2_rom.emulator.read_vram_bank(
            1, VBG_MAP_1, SCREEN_HEIGHT * 32
        )
        for published_row in range(SCREEN_HEIGHT):
            paired = published_row < row + OVERLAY_ROWS_PER_PHASE
            offset = published_row * 32
            assert (
                bank0[offset : offset + SCREEN_WIDTH] != b"\x55" * SCREEN_WIDTH
            ) is paired
            assert (
                bank1[offset : offset + SCREEN_WIDTH] != b"\xee" * SCREEN_WIDTH
            ) is paired


@pytest.mark.parametrize(
    ("counter", "tile_address"),
    ((19, WATER_TILE), (20, FLOWER_TILE)),
)
def test_audit_scheduler_column_redraw_runs_bounded_animation_with_headroom(
    audit_rom: Phase2Rom,
    counter: int,
    tile_address: int,
) -> None:
    phase2_rom = audit_rom
    _activate_passive_map(phase2_rom)
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.write_fixed(
        symbols["wRedrawRowOrColumnSrcTiles"],
        bytes(range(40)),
    )
    emu.memory[symbols["hRedrawRowOrColumnDest"]] = 0x20
    emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = 0x98
    phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
    emu.memory[symbols["hRedrawRowOrColumnMode"]] = REDRAW_COL
    phase2_rom.call("PassiveFullColorHandleConnection")
    phase2_rom.write_wram2("wPassiveFullColorPalettePending", 0)

    entries, writes, returns = _run_animation_across_two_vblanks(
        phase2_rom,
        counter=counter,
        tile_address=tile_address,
    )

    _assert_single_bounded_animation_update(
        phase2_rom,
        counter=counter,
        write_frame=1,
        entries=entries,
        writes=writes,
        returns=returns,
    )


@pytest.mark.parametrize(
    ("counter", "tile_address"),
    ((19, WATER_TILE), (20, FLOWER_TILE)),
)
@pytest.mark.parametrize("product", TIMING_PRODUCTS)
def test_two_frame_row_redraw_runs_bounded_animation_with_headroom(
    request: pytest.FixtureRequest,
    product: str,
    counter: int,
    tile_address: int,
) -> None:
    phase2_rom = _open_product(request, product, product)
    try:
        _activate_passive_map(phase2_rom)
        emu = phase2_rom.emulator.pyboy
        symbols = phase2_rom.emulator.symbols
        phase2_rom.write_fixed(
            symbols["wRedrawRowOrColumnSrcTiles"], bytes(range(40))
        )
        emu.memory[symbols["hRedrawRowOrColumnDest"]] = 0x20
        emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = 0x98
        phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
        emu.memory[symbols["hRedrawRowOrColumnMode"]] = REDRAW_ROW
        phase2_rom.call("PassiveFullColorHandleConnection")
        phase2_rom.write_wram2("wPassiveFullColorPalettePending", 0)

        entries, writes, returns = _run_animation_across_two_vblanks(
            phase2_rom,
            counter=counter,
            tile_address=tile_address,
        )

        _assert_single_bounded_animation_update(
            phase2_rom,
            counter=counter,
            write_frame=1,
            entries=entries,
            writes=writes,
            returns=returns,
        )
    finally:
        phase2_rom.emulator.close()


@pytest.mark.parametrize(
    ("counter", "tile_address"),
    ((19, WATER_TILE), (20, FLOWER_TILE)),
)
@pytest.mark.parametrize("product", TIMING_PRODUCTS)
def test_overlay_phase_defers_animation_but_next_idle_vblank_runs_it(
    request: pytest.FixtureRequest,
    product: str,
    counter: int,
    tile_address: int,
) -> None:
    phase2_rom = _open_product(request, product, product)
    try:
        _activate_passive_map(phase2_rom)
        entries, writes, returns = _run_animation_across_two_vblanks(
            phase2_rom,
            counter=counter,
            tile_address=tile_address,
            overlay_phase=True,
        )

        _assert_single_bounded_animation_update(
            phase2_rom,
            counter=counter,
            write_frame=2,
            entries=entries,
            writes=writes,
            returns=returns,
        )
    finally:
        phase2_rom.emulator.close()


def test_exit_path_finishes_before_natural_ly0(phase2_rom: Phase2Rom) -> None:
    _activate_passive_map(phase2_rom)
    phase2_rom.emulator.pyboy.memory[
        phase2_rom.emulator.symbols["wCurMap"]
    ] = VIRIDIAN_CITY
    phase2_rom.call("PassiveFullColorHandleConnection")

    measurement = _run_natural_vblank(
        phase2_rom, operation="exit homogenize+clear", expect_passive=True,
    )

    _assert_passive_finishes_before_ly0(measurement)


def test_activation_two_row_publish_finishes_before_natural_ly0(
    phase2_rom: Phase2Rom,
) -> None:
    _activate_passive_map(phase2_rom)
    phase2_rom.call("PassiveFullColorWriteActive", a=0)
    phase2_rom.write_wram2("wPassiveFullColorPalettePending", 5)
    phase2_rom.write_wram2("wPassiveFullColorClearChunks", 18)

    measurement = _run_natural_vblank(
        phase2_rom, operation="activation two-row publish", expect_passive=True,
    )

    _assert_passive_finishes_before_ly0(measurement)
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x05"
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x10"


@pytest.mark.parametrize("mode", (REDRAW_ROW, REDRAW_COL))
def test_natural_passive_redraw_restores_real_banked_stack_and_cpu_state(
    phase2_rom: Phase2Rom, mode: int,
) -> None:
    """Exercise the interrupt ABI with the stack in switchable WRAM.

    A stack in HRAM cannot expose an SVBK save that is pushed in one WRAM bank
    and popped after selecting another. Keep hostile bytes in Yellow's bank 1
    while the interrupted program and its stack live in bank 6, then require a
    complete natural interrupt return after passive row/column work.
    """
    _activate_passive_map(phase2_rom)
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.write_fixed(symbols["wRedrawRowOrColumnSrcTiles"], bytes(range(40)))
    emu.memory[symbols["hRedrawRowOrColumnDest"]] = 0x20
    emu.memory[symbols["hRedrawRowOrColumnDest"] + 1] = 0x98
    if mode == REDRAW_ROW:
        phase2_rom.call("PassiveFullColorPrepareRedrawAttributes")
    else:
        phase2_rom.call("PassiveFullColorPrepareColumnAttributes")
    emu.memory[symbols["hRedrawRowOrColumnMode"]] = mode
    phase2_rom.call("PassiveFullColorHandleConnection")

    _assert_natural_vblank_restores_real_banked_cpu_state(phase2_rom)


@pytest.mark.parametrize(
    ("case", "pending", "clear_chunks", "expected_pending", "expected_clear"),
    (
        ("pending-palette", 1, 0, 0, 0),
        ("inactive-homogenize", 3, 32, 0, 32),
        ("inactive-clear", 0, 32, 0, 31),
    ),
)
def test_natural_passive_non_redraw_paths_restore_real_banked_cpu_state(
    phase2_rom: Phase2Rom,
    case: str,
    pending: int,
    clear_chunks: int,
    expected_pending: int,
    expected_clear: int,
) -> None:
    """Cover palette and cleanup work that nests renderer-state helpers."""
    _activate_passive_map(phase2_rom)
    if case.startswith("inactive-"):
        phase2_rom.emulator.pyboy.memory[
            phase2_rom.emulator.symbols["wCurMap"]
        ] = VIRIDIAN_CITY
        phase2_rom.call("PassiveFullColorHandleConnection")
    phase2_rom.write_wram2("wPassiveFullColorPalettePending", pending)
    phase2_rom.write_wram2("wPassiveFullColorClearChunks", clear_chunks)

    _assert_natural_vblank_restores_real_banked_cpu_state(phase2_rom)

    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == bytes(
        (expected_pending,)
    )
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == bytes(
        (expected_clear,)
    )


def test_audit_diagnostics_and_product_renderer_keep_yellow_writers_in_vblank(
    phase2_rom: Phase2Rom, audit_rom: Phase2Rom,
) -> None:
    _activate_passive_map(phase2_rom)
    _activate_passive_map(audit_rom)
    product = _run_natural_vblank(
        phase2_rom, operation="production idle", expect_passive=True,
    )
    audit = _run_natural_vblank(
        audit_rom, operation="audit idle", expect_passive=True,
    )

    assert tuple(name for name, _, _ in audit.downstream) == tuple(
        name for name, _, _ in product.downstream
    )
    for name, audit_cycle, ly in audit.downstream:
        _, product_cycle, product_ly = next(
            item for item in product.downstream if item[0] == name
        )
        audit_offset = audit_cycle - audit.vblank_cycle
        product_offset = product_cycle - product.vblank_cycle
        assert 0 < audit_offset < audit.deadline_span
        assert 0 < product_offset < product.deadline_span, (
            f"{name}: audit reached LY{ly} at +{audit_offset} cycles; product "
            f"reached LY{product_ly} at +{product_offset} cycles"
        )
        assert abs(audit_offset - product_offset) < 456
