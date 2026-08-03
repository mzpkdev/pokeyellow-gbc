"""Natural-VBlank timing gates for the passive PHASE2_AUDIT renderer."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
    phase2_rom as _phase2_rom,  # noqa: F401 - registered by pytest
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
DOWNSTREAM_WRITERS = ("VBlankCopy", "VBlankCopyDouble", "UpdateMovingBgTiles")
WATER_TILE = 0x9140
FLOWER_TILE = 0x9030
TILE_SIZE = 16


@pytest.fixture(name="phase2_rom")
def phase2_rom_fixture(request: pytest.FixtureRequest) -> Phase2Rom:
    return request.getfixturevalue("_phase2_rom")


@pytest.fixture
def stock_debug_rom(request: pytest.FixtureRequest):
    rom = Path(REPOSITORY_ROOT / "pokeyellow_debug.gbc")
    sym = Path(REPOSITORY_ROOT / "pokeyellow_debug.sym")
    emulator = Emulator(
        rom=rom,
        symbols=sym,
        results=result_directory(request.node.nodeid) / "stock-debug",
        cgb=True,
    )
    instance = Phase2Rom(emulator, numeric_symbols(sym))
    try:
        instance.call("InitRendererOwnership")
        yield instance
    finally:
        emulator.close()


@dataclass(frozen=True, slots=True)
class NaturalVBlankMeasurement:
    operation: str
    vblank_cycle: int
    vblank_ly: int
    passive_entry_cycle: int | None
    passive_entry_ly: int | None
    passive_end_cycle: int | None
    passive_end_ly: int | None
    deadline_span: int
    downstream: tuple[tuple[str, int, int], ...]

    @property
    def passive_headroom(self) -> int:
        assert self.passive_end_cycle is not None
        return self.vblank_cycle + self.deadline_span - self.passive_end_cycle


def _write_banked(rom: Phase2Rom, bank: int, address: int, data: bytes) -> None:
    emu = rom.emulator.pyboy
    prior = emu.memory[RSVBK]
    emu.memory[RSVBK] = bank
    try:
        for offset, value in enumerate(data):
            emu.memory[address + offset] = value
    finally:
        emu.memory[RSVBK] = prior


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
    rom: Phase2Rom, *, operation: str, expect_passive: bool,
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

    def mark_vblank(_: object) -> None:
        observed["vblank"] = (emu._cycles(), emu.memory[RLY])

    def mark_passive(_: object) -> None:
        observed["passive"] = (emu._cycles(), emu.memory[RLY])

    def mark_downstream(name: str) -> None:
        if not any(item[0] == name for item in downstream):
            downstream.append((name, emu._cycles(), emu.memory[RLY]))
        if name == "VBlankCopy" and expect_passive:
            observed["passive_end"] = (emu._cycles(), emu.memory[RLY])
        if name == DOWNSTREAM_WRITERS[-1]:
            observed["complete"] = (emu._cycles(), emu.memory[RLY])
            emu.memory[INTERRUPT_ENABLE] = 0
            emu.memory[HARNESS_HALT] = 0x76
            regs.PC = HARNESS_HALT

    hooks: list[tuple[int, int]] = [(0, symbols["VBlank"])]
    emu.hook_register(0, symbols["VBlank"], mark_vblank, None)
    if expect_passive:
        passive_bank = rom.emulator.symbol_banks["PassiveFullColorVBlank"]
        passive_address = symbols["PassiveFullColorVBlank"]
        hooks.append((passive_bank, passive_address))
        emu.hook_register(passive_bank, passive_address, mark_passive, None)
    for name in DOWNSTREAM_WRITERS:
        bank = rom.emulator.symbol_banks[name]
        address = symbols[name]
        hooks.append((bank, address))
        emu.hook_register(bank, address, mark_downstream, name)
    try:
        for _ in range(3):
            emu.tick(1, render=False, sound=False)
            if "complete" in observed:
                break
    finally:
        for bank, address in hooks:
            emu.hook_deregister(bank, address)
    assert observed["vblank"][1] == 144
    assert "complete" in observed
    assert tuple(item[0] for item in downstream) == DOWNSTREAM_WRITERS
    if expect_passive:
        assert {"passive", "passive_end"} <= observed.keys()
    vblank_cycle, vblank_ly = observed["vblank"]
    passive = observed.get("passive")
    passive_end = observed.get("passive_end")
    return NaturalVBlankMeasurement(
        operation=operation,
        vblank_cycle=vblank_cycle,
        vblank_ly=vblank_ly,
        passive_entry_cycle=None if passive is None else passive[0],
        passive_entry_ly=None if passive is None else passive[1],
        passive_end_cycle=None if passive_end is None else passive_end[0],
        passive_end_ly=None if passive_end is None else passive_end[1],
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
    assert measurement.passive_headroom >= 0
    for name, cycle, ly in measurement.downstream:
        headroom = measurement.vblank_cycle + measurement.deadline_span - cycle
        assert 144 <= ly <= 153 and headroom >= 0, (
            f"{measurement.operation}: downstream Yellow writer {name} reached "
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


def _run_animation_across_overloaded_and_idle_vblanks(
    rom: Phase2Rom,
    *,
    counter: int,
    tile_address: int,
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int, int], ...],
    tuple[tuple[int, int, bytes], ...],
]:
    """Run, rather than intercept, moving-tile work across two VBlanks."""
    emu = rom.emulator.pyboy
    regs = emu.register_file
    symbols = rom.emulator.symbols
    initial_tile = bytes((0x81 + offset * 7) & 0xFF for offset in range(TILE_SIZE))
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
    assert returns[0] == (counter, 0, initial_tile)
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
        phase2_rom.call("PassiveFullColorHandleConnection")

    measurement = _run_natural_vblank(
        phase2_rom, operation=case, expect_passive=True,
    )

    _assert_passive_finishes_before_ly0(measurement)


@pytest.mark.parametrize(
    ("counter", "tile_address"),
    ((19, WATER_TILE), (20, FLOWER_TILE)),
)
def test_audit_column_redraw_defers_tile_animation_until_idle_natural_vblank(
    phase2_rom: Phase2Rom,
    counter: int,
    tile_address: int,
) -> None:
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

    entries, writes, returns = _run_animation_across_overloaded_and_idle_vblanks(
        phase2_rom,
        counter=counter,
        tile_address=tile_address,
    )

    assert entries == ((1, 153), (2, 146))
    assert len(writes) == TILE_SIZE
    assert {frame for frame, _, _ in writes} == {2}
    assert all(144 <= ly <= 153 for _, ly, _ in writes)
    assert returns[0][0:2] == (counter, 0)
    assert returns[1][2] != returns[0][2]
    if counter == 19:
        assert returns[1][0:2] == (0, 1)
    else:
        assert returns[1][0:2] == (0, 0)


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


def test_audit_does_not_push_downstream_yellow_writers_past_ly153(
    phase2_rom: Phase2Rom, stock_debug_rom: Phase2Rom,
) -> None:
    _activate_passive_map(phase2_rom)
    audit = _run_natural_vblank(
        phase2_rom, operation="audit idle", expect_passive=True,
    )
    stock = _run_natural_vblank(
        stock_debug_rom, operation="stock debug", expect_passive=False,
    )

    assert tuple(name for name, _, _ in audit.downstream) == tuple(
        name for name, _, _ in stock.downstream
    )
    for name, audit_cycle, ly in audit.downstream:
        _, stock_cycle, stock_ly = next(
            item for item in stock.downstream if item[0] == name
        )
        audit_offset = audit_cycle - audit.vblank_cycle
        stock_offset = stock_cycle - stock.vblank_cycle
        assert stock_offset <= audit_offset < audit.deadline_span, (
            f"{name}: audit reached LY{ly} at +{audit_offset} cycles; stock debug "
            f"reached LY{stock_ly} at +{stock_offset} cycles"
        )
