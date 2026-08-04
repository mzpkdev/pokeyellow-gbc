"""Deterministic linked timing equations for the production Color renderer."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Iterable

from pyboy.core.opcodes import CPU_COMMANDS

from .rom_discovery import SymbolTable, load_sym


REQUIRED_TIMING_KEYS = (
    "TIME-SELECTOR",
    "TIME-ENTER-YELLOW-MAP", "TIME-ENTER-YELLOW-MENU",
    "TIME-ENTER-YELLOW-DIALOGUE", "TIME-ENTER-YELLOW-BATTLE",
    "TIME-ENTER-YELLOW-HARD-RESET", "TIME-ENTER-YELLOW-SOFT-RESET",
    "TIME-ENTER-COLOR-MAP",
    "TIME-VBLANK-YELLOW", "TIME-VBLANK-OVERWORLD",
    "TIME-PALETTE-BG", "TIME-PALETTE-OBJ", "TIME-PALETTE-COMBINED",
    "TIME-TRANSFER-LOAD", "TIME-TRANSFER-RELOAD",
    "TIME-STREAM-HORIZONTAL", "TIME-STREAM-VERTICAL",
    "TIME-STREAM-CONNECTION", "TIME-TRANSFER-ROW",
    "TIME-TRANSFER-COLUMN", "TIME-TRANSFER-RECTANGLE",
    "TIME-TRANSFER-THIRD-SCREEN", "TIME-TRANSFER-ALTERNATE-BG",
    "TIME-ANIMATED-TILE", "TIME-FIELD-REPLACEMENT",
    "TIME-OAM-SHADOW-BUILD", "TIME-OAM-DMA",
)

VBLANK_SCANLINES = 10
SCANLINE_DOTS = 456
CGB_DOUBLE_SPEED_DOTS_PER_MACHINE_CYCLE = 2
VBLANK_MACHINE_CYCLES = (
    VBLANK_SCANLINES * SCANLINE_DOTS // CGB_DOUBLE_SPEED_DOTS_PER_MACHINE_CYCLE
)
VBLANK_GUARD_CYCLES = 80
FRAME_MACHINE_CYCLES = 154 * SCANLINE_DOTS // CGB_DOUBLE_SPEED_DOTS_PER_MACHINE_CYCLE
DMA_MACHINE_CYCLES = 2 + 3 + 2 + 40 * (1 + 3) + 5


class TimingEvidenceError(ValueError):
    """Linked timing evidence is incomplete or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class Span:
    start: str
    end: str
    repeats: int = 1


@dataclass(frozen=True, slots=True)
class TimingRow:
    key: str
    operation: str
    terms: tuple[str, ...]
    worst_cycles: int
    deadline_cycles: int
    guard_cycles: int
    defer_threshold: int
    linked_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "operation": self.operation,
            "equation": " + ".join(self.terms),
            "worst_cycles": self.worst_cycles,
            "deadline_cycles": self.deadline_cycles,
            "guard_cycles": self.guard_cycles,
            "defer_threshold": self.defer_threshold,
            "exact_fit_result": "COMMIT",
            "threshold_plus_one_result": "DEFER",
            "threshold_plus_one_entered_committing": False,
            "linked_sha256": self.linked_sha256,
        }


_BASE_CYCLES = (
    (1, 3, 2, 2, 1, 1, 2, 1, 5, 2, 2, 2, 1, 1, 2, 1),
    (1, 3, 2, 2, 1, 1, 2, 1, 3, 2, 2, 2, 1, 1, 2, 1),
    (3, 3, 2, 2, 1, 1, 2, 1, 3, 2, 2, 2, 1, 1, 2, 1),
    (3, 3, 2, 2, 1, 1, 2, 1, 3, 2, 2, 2, 1, 1, 2, 1),
    *((1,) * 16,) * 4,
    *((1,) * 16,) * 4,
    (5, 3, 4, 4, 6, 4, 2, 4, 5, 4, 4, 0, 6, 6, 2, 4),
    (5, 3, 4, 0, 6, 4, 2, 4, 5, 4, 4, 0, 6, 0, 2, 4),
    (3, 3, 2, 0, 0, 4, 2, 4, 4, 1, 4, 0, 0, 0, 2, 4),
    (3, 3, 2, 1, 0, 4, 2, 4, 3, 2, 4, 1, 0, 0, 2, 4),
)


def _instruction_length(opcode: int) -> int:
    mnemonic = CPU_COMMANDS[opcode]
    if opcode == 0xCB:
        return 2
    if "d16" in mnemonic or "a16" in mnemonic:
        return 3
    if "d8" in mnemonic or "a8" in mnemonic or "r8" in mnemonic:
        return 2
    return 1


def _machine_cycles(opcode: int, following: int | None = None) -> int:
    if opcode == 0xCB:
        assert following is not None
        target_hl = (following & 7) == 6
        if not target_hl:
            return 2
        return 3 if 0x40 <= following <= 0x7F else 4
    if 0x40 <= opcode <= 0x7F:
        if opcode == 0x76:
            return 1
        return 2 if ((opcode >> 3) & 7) == 6 or (opcode & 7) == 6 else 1
    if 0x80 <= opcode <= 0xBF:
        return 2 if (opcode & 7) == 6 else 1
    cycles = _BASE_CYCLES[opcode >> 4][opcode & 0xF]
    if cycles <= 0:
        raise TimingEvidenceError(f"unsupported/illegal opcode ${opcode:02x}")
    return cycles


class LinkedTimingDecoder:
    def __init__(self, rom: bytes, symbols: SymbolTable) -> None:
        self.rom = rom
        self.symbols = symbols

    def _offset(self, symbol: str) -> tuple[int, int, int]:
        address = self.symbols.resolve(symbol)
        offset = address.address if address.bank == 0 else (
            address.bank * 0x4000 + address.address - 0x4000
        )
        return address.bank, address.address, offset

    def span(self, term: Span) -> tuple[int, bytes]:
        start_bank, start_address, start_offset = self._offset(term.start)
        end_bank, end_address, end_offset = self._offset(term.end)
        if start_bank != end_bank or end_address <= start_address:
            raise TimingEvidenceError(
                f"invalid linked span {term.start}..{term.end}"
            )
        blob = self.rom[start_offset:end_offset]
        cursor = 0
        cycles = 0
        while cursor < len(blob):
            opcode = blob[cursor]
            length = _instruction_length(opcode)
            if cursor + length > len(blob):
                raise TimingEvidenceError(
                    f"{term.start}..{term.end}: truncated instruction"
                )
            cycles += _machine_cycles(
                opcode, blob[cursor + 1] if opcode == 0xCB else None
            )
            cursor += length
        return cycles * term.repeats, blob


def _equation(
    decoder: LinkedTimingDecoder,
    *spans: Span,
    fixed: Iterable[tuple[str, int]] = (),
) -> tuple[int, tuple[str, ...], str]:
    total = 0
    terms: list[str] = []
    digest = hashlib.sha256()
    for span in spans:
        cycles, blob = decoder.span(span)
        total += cycles
        terms.append(f"{span.repeats}*linked({span.start}..{span.end})={cycles}")
        digest.update(span.start.encode())
        digest.update(b"\0")
        digest.update(span.end.encode())
        digest.update(span.repeats.to_bytes(4, "little"))
        digest.update(blob)
    for name, cycles in fixed:
        if cycles <= 0:
            raise TimingEvidenceError(f"{name}: fixed term must be positive")
        total += cycles
        terms.append(f"{name}={cycles}")
        digest.update(name.encode())
        digest.update(cycles.to_bytes(4, "little"))
    return total, tuple(terms), digest.hexdigest()


def _row(
    decoder: LinkedTimingDecoder,
    key: str,
    operation: str,
    spans: tuple[Span, ...],
    *,
    fixed: tuple[tuple[str, int], ...] = (),
    deadline: int,
    guard: int,
) -> TimingRow:
    cost, terms, digest = _equation(decoder, *spans, fixed=fixed)
    threshold = cost
    if not (0 < threshold < 0xFFFF and cost + guard <= deadline):
        raise TimingEvidenceError(
            f"{key}: cost {cost} plus guard {guard} does not fit deadline {deadline}"
        )
    return TimingRow(key, operation, terms, cost, deadline, guard, threshold, digest)


def _timed_rom_call(rom: object, name: str, **registers: int) -> int:
    """Return exact linked CPU machine cycles at the real ROM return edge."""
    emulator = rom.emulator
    register_file = emulator.pyboy.register_file
    address = emulator.symbols[name]
    bank = emulator.symbol_banks[name]
    stack = 0xCFFE
    register_file.A = registers.get("a", 0)
    register_file.B = registers.get("b", 0)
    register_file.C = registers.get("c", 0)
    de = registers.get("de", 0)
    register_file.D, register_file.E = (de >> 8) & 0xFF, de & 0xFF
    register_file.HL = registers.get("hl", 0)
    register_file.SP = stack
    emulator.pyboy.memory[stack] = 0
    emulator.pyboy.memory[stack + 1] = 1
    emulator.pyboy.memory[0xFFFF] = 0
    if bank:
        emulator.pyboy.memory[0x2000] = bank & 0xFF
        emulator.pyboy.memory[0x3000] = bank >> 8
        emulator.pyboy.memory[emulator.symbols["hLoadedROMBank"]] = bank
    register_file.PC = address
    start_cycles = emulator.pyboy._cycles()
    elapsed: list[int] = []

    def stop(_: object) -> None:
        elapsed.append(emulator.pyboy._cycles() - start_cycles)
        emulator.pyboy.memory[0xC6F0] = 0x18
        emulator.pyboy.memory[0xC6F1] = 0xFE
        register_file.PC = 0xC6F0

    emulator.pyboy.hook_register(0, 0x0100, stop, None)
    try:
        for _ in range(64):
            emulator.pyboy.tick(1, render=False, sound=False)
            if elapsed:
                break
    finally:
        emulator.pyboy.hook_deregister(0, 0x0100)
    if not elapsed:
        raise TimingEvidenceError(
            f"linked timing call {name} did not return "
            f"(PC={register_file.PC:#06x}, SP={register_file.SP:#06x})"
        )
    if elapsed[0] % 4:
        raise TimingEvidenceError(f"linked timing call {name} ended off machine-cycle boundary")
    return elapsed[0] // 4


def _timed_rom_root_to_barrier(
    rom: object,
    entry: str,
    barrier: str,
    *,
    stubs: dict[str, object] | None = None,
    observations: dict[str, object] | None = None,
    maximum_frames: int = 4096,
) -> int:
    """Execute a genuine game root until its linked destination barrier."""
    emulator = rom.emulator
    registers = emulator.pyboy.register_file
    memory = emulator.pyboy.memory
    barrier_bank = emulator.symbol_banks[barrier]
    elapsed: list[int] = []
    stub_hooks: list[tuple[int, int]] = []
    entry_bank = emulator.symbol_banks[entry]
    entry_address = emulator.symbols[entry]
    started = emulator.pyboy._cycles()

    def stop(_: object) -> None:
        elapsed.append(emulator.pyboy._cycles() - started)
        # The barrier may deliberately leave LCD off. Restore scanline timing
        # and park the CPU so PyBoy can finish the host frame after recording
        # the exact pre-display edge.
        memory[0xFF40] |= 0x80
        memory[0xC6F0:0xC6F2] = b"\x18\xfe"
        registers.PC = 0xC6F0

    def return_from_stub(action: object):
        def callback(_: object) -> None:
            if callable(action):
                action()
            stack = registers.SP
            registers.PC = memory[stack] | memory[stack + 1] << 8
            registers.SP = stack + 2
        return callback

    emulator.pyboy.hook_register(
        barrier_bank, emulator.symbols[barrier], stop, None,
    )
    for symbol, action in (stubs or {}).items():
        bank = emulator.symbol_banks[symbol]
        address = emulator.symbols[symbol]
        emulator.pyboy.hook_register(bank, address, return_from_stub(action), None)
        stub_hooks.append((bank, address))
    for symbol, action in (observations or {}).items():
        bank = emulator.symbol_banks[symbol]
        address = emulator.symbols[symbol]

        def observe(_: object, callback: object = action) -> None:
            if callable(callback):
                callback()

        emulator.pyboy.hook_register(bank, address, observe, None)
        stub_hooks.append((bank, address))
    memory[0xFF50] = 1
    memory[0xFFFF] = 0
    memory[0xFF0F] = 0
    registers.SP = 0xDFFF
    memory[0xDFFF] = 0
    memory[0xE000] = 1
    if entry_bank:
        memory[0x2000] = entry_bank & 0xFF
        memory[0x3000] = entry_bank >> 8
        memory[emulator.symbols["hLoadedROMBank"]] = entry_bank & 0xFF
    registers.PC = entry_address
    try:
        for _ in range(maximum_frames):
            emulator.pyboy.tick(1, render=False, sound=False)
            if elapsed:
                break
    finally:
        for bank, address in reversed(stub_hooks):
            emulator.pyboy.hook_deregister(bank, address)
        emulator.pyboy.hook_deregister(barrier_bank, emulator.symbols[barrier])
    if not elapsed:
        raise TimingEvidenceError(
            f"genuine root {entry} did not reach {barrier} "
            f"(bank={memory[emulator.symbols['hLoadedROMBank']]:#04x}, "
            f"PC={registers.PC:#06x}, SP={registers.SP:#06x}, "
            f"RET={(memory[registers.SP] | memory[(registers.SP + 1) & 0xffff] << 8):#06x}, "
            f"BC={registers.B:#04x}{registers.C:02x}, "
            f"DE={registers.D:#04x}{registers.E:02x}, HL={registers.HL:#06x})"
        )
    if elapsed[0] % 4:
        raise TimingEvidenceError(f"{entry} ended off machine-cycle boundary")
    return elapsed[0] // 4


def _timed_game_call(
    rom: object,
    name: str,
    *,
    stubs: dict[str, object] | None = None,
    **registers: int,
) -> int:
    """Time a complete direct call using the game-root harness ABI."""
    emulator = rom.emulator
    register_file = emulator.pyboy.register_file
    memory = emulator.pyboy.memory
    hooks: list[tuple[int, int]] = []

    def return_from_stub(action: object):
        def callback(_: object) -> None:
            if callable(action):
                action()
            stack = register_file.SP
            register_file.PC = memory[stack] | memory[stack + 1] << 8
            register_file.SP = stack + 2
        return callback

    for symbol, action in (stubs or {}).items():
        bank = emulator.symbol_banks[symbol]
        address = emulator.symbols[symbol]
        emulator.pyboy.hook_register(bank, address, return_from_stub(action), None)
        hooks.append((bank, address))
    started = rom.emulator.pyboy._cycles()
    try:
        try:
            rom.call(name, **registers)
        except AssertionError as error:
            loaded = memory[emulator.symbols["hLoadedROMBank"]]
            prior_bank = memory[0xFF70]
            memory[0xFF70] = 2
            state = {
                symbol: memory[emulator.symbols[symbol]]
                for symbol in (
                    "wRendererOwner", "wRendererPhase",
                    "wRendererAdmissionOpen", "wFullColorRequestCount",
                    "wFullColorProductionTransitionStatus",
                )
            }
            memory[0xFF70] = prior_bank
            raise TimingEvidenceError(
                f"{name} failed with loaded ROM bank ${loaded:02x}, "
                f"state={state}: {error}"
            ) from error
    finally:
        for bank, address in reversed(hooks):
            emulator.pyboy.hook_deregister(bank, address)
    elapsed = rom.emulator.pyboy._cycles() - started
    if elapsed <= 0 or elapsed % 4:
        raise TimingEvidenceError(f"{name} ended off machine-cycle boundary")
    return elapsed // 4


def _timed_home_vblank_to_visible_boundary(rom: object) -> int:
    """Execute the real interrupt root through its named visible barrier."""
    emulator = rom.emulator
    memory = emulator.pyboy.memory
    registers = emulator.pyboy.register_file
    program = 0xD100
    loop = 0xC6F0
    prior_bank = memory[0xFF70]
    memory[0xFF70] = 6
    memory[program : program + 4] = b"\xfb\xc3\x00\x01"  # ei; jp $0100
    memory[0xFF50] = 1
    memory[0xFFFF] = 1
    memory[0xFF0F] = 1
    registers.PC = program
    registers.SP = 0xFFFC
    started: list[int] = []
    elapsed: list[int] = []
    vblank = emulator.symbols["VBlank"]
    boundary = emulator.symbols["FullColorProductionVBlankVisibleRouteComplete"]

    def at_start(_: object) -> None:
        started.append(emulator.pyboy._cycles())

    def at_boundary(_: object) -> None:
        if started:
            elapsed.append(emulator.pyboy._cycles() - started[0])
        memory[0xFFFF] = 0
        memory[loop : loop + 2] = b"\x18\xfe"
        registers.PC = loop

    emulator.pyboy.hook_register(0, vblank, at_start, None)
    emulator.pyboy.hook_register(0, boundary, at_boundary, None)
    try:
        emulator.pyboy.tick(1, render=False, sound=False)
    finally:
        emulator.pyboy.hook_deregister(0, vblank)
        emulator.pyboy.hook_deregister(0, boundary)
        memory[0xFF70] = prior_bank
    if not elapsed or elapsed[0] % 4:
        raise TimingEvidenceError("real VBlank did not reach its visible boundary")
    return elapsed[0] // 4


def enqueue_timing_producer(rom: object, kind: str, source: int) -> tuple[int, int]:
    """Call the concrete production producer represented by a timing row."""
    if kind.startswith("palette-"):
        request_class = (
            "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD"
            if kind.endswith("bg") else "FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD"
        )
        palette = rom.emulator.symbols[
            "FullColorOverworldBGPalettes"
            if kind.endswith("bg") else "FullColorProductionOBJPalettes"
        ]
        return rom.call(
            "EnqueueFullColorProductionPaletteSelected",
            a=rom.constants[request_class], de=palette,
        )
    calls = {
        "row": ("EnqueueFullColorMapRow", dict(b=20, c=1, hl=source, de=0x9800)),
        "column": ("EnqueueFullColorMapColumn", dict(b=1, c=18, hl=source, de=0x9800)),
        "movement-row": ("EnqueueFullColorMovementRowStrip", dict(hl=source, de=0x9800)),
        "movement-column": ("EnqueueFullColorMovementColumnStrip", dict(hl=source, de=0x9800)),
        "connection": ("EnqueueFullColorMapConnection", dict(b=20, c=2, hl=source, de=0x9800)),
        "load": ("EnqueueFullColorMapRectangle", dict(b=20, c=18, hl=source, de=0x9800)),
        "third-screen": ("EnqueueFullColorMapRectangle", dict(b=20, c=6, hl=source, de=0x9800)),
        "alternate-bg": ("EnqueueFullColorMapRectangle", dict(b=20, c=18, hl=source, de=0x9C00)),
        "animation": ("EnqueueFullColorAnimation", dict(hl=source, de=0x8000, b=0x98, c=0)),
        "oam": ("EnqueueFullColorOAMBatch", dict(hl=source)),
    }
    name, registers = calls[kind]
    return rom.call(name, **registers)


def _measure_scheduler_edges(root: Path) -> dict[str, int]:
    """Execute each concrete production descriptor through PREPARED->COMPLETE."""
    # Phase2Rom is the shared direct-call ABI used by the scheduler conformance
    # suite. Importing lazily keeps the standalone decoder usable by unit tests.
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
        Phase2Rom,
        numeric_symbols,
    )

    scenarios = {
        "TIME-PALETTE-BG": ("palette-bg", 64),
        "TIME-PALETTE-OBJ": ("palette-obj", 64),
        "TIME-STREAM-HORIZONTAL": ("column-pair", 36),
        "TIME-STREAM-VERTICAL": ("row-pair", 40),
        "TIME-STREAM-CONNECTION": ("connection", 40),
        "TIME-TRANSFER-ROW": ("row", 20),
        "TIME-TRANSFER-COLUMN": ("column", 18),
        "TIME-TRANSFER-LOAD": ("rectangle", 360),
        "TIME-TRANSFER-RELOAD": ("rectangle", 360),
        "TIME-TRANSFER-RECTANGLE": ("rectangle", 360),
        "TIME-TRANSFER-THIRD-SCREEN": ("third", 120),
        "TIME-TRANSFER-ALTERNATE-BG": ("rectangle-alt", 360),
        "TIME-ANIMATED-TILE": ("animation", 17),
        "TIME-FIELD-REPLACEMENT": ("animation", 17),
        "TIME-OAM-DMA": ("oam", 160),
    }
    measured: dict[str, int] = {}
    hidden_keys = {
        "TIME-TRANSFER-LOAD", "TIME-TRANSFER-RELOAD",
        "TIME-TRANSFER-RECTANGLE", "TIME-TRANSFER-THIRD-SCREEN",
        "TIME-TRANSFER-ALTERNATE-BG",
    }
    with tempfile.TemporaryDirectory(prefix="full-color-timing-") as directory:
        for key, (kind, extent) in scenarios.items():
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
            try:
                rom.activate()
                emulator.pyboy.memory[0xFF70] = 2
                source = 0xC800
                rom.write_fixed(source, bytes((index * 29 + 7) & 0xFF for index in range(extent)))
                normalized = {
                    "row-pair": "movement-row", "column-pair": "movement-column",
                    "rectangle": "load", "rectangle-alt": "alternate-bg",
                    "third": "third-screen",
                }.get(kind, kind)
                result, flags = enqueue_timing_producer(rom, normalized, source)
                if result != rom.constants["ACCEPTED"]:
                    raise TimingEvidenceError(f"{key}: actual producer did not admit")
                rom.write_wram2("wFullColorCommitBudget", (0xFFFE).to_bytes(2, "little"))
                measured[key] = _timed_rom_call(rom, "RunFullColorOwnershipVBlank")
                if rom.read_wram2("wFullColorRequestCount") != b"\x00":
                    raise TimingEvidenceError(f"{key}: actual scheduler edge did not complete")
            finally:
                emulator.close()
    return measured


def _measure_color_vblank_routes(root: Path) -> dict[str, int]:
    """Execute the complete visible Color route for every reachable unit."""
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
        Phase2Rom,
        numeric_symbols,
    )

    scenarios = {
        "empty": ("empty", 0),
        "palette-bg": ("palette-bg", 64),
        "palette-obj": ("palette-obj", 64),
        "row": ("row", 20),
        "column": ("column", 18),
        "movement-row": ("movement-row", 40),
        "movement-column": ("movement-column", 36),
        "connection": ("connection", 40),
        "animation": ("animation", 17),
        "oam": ("oam", 160),
    }
    measured: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="full-color-vblank-timing-") as directory:
        for key, (kind, extent) in scenarios.items():
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
            try:
                rom.activate()
                emulator.pyboy.memory[0xFF70] = 2
                if kind != "empty":
                    source = 0xC800
                    source_extent = extent * 2 if kind in {
                        "row", "column", "movement-row", "movement-column", "connection",
                    } else extent
                    rom.write_fixed(
                        source,
                        bytes((index * 31 + 13) & 0xEF for index in range(source_extent)),
                    )
                    result, _ = enqueue_timing_producer(rom, kind, source)
                    if result != rom.constants["ACCEPTED"]:
                        raise TimingEvidenceError(f"{key}: actual producer did not admit")
                    rom.write_wram2("wFullColorCommitBudget", (0xFFFE).to_bytes(2, "little"))
                measured[key] = _timed_home_vblank_to_visible_boundary(rom)
                if rom.read_wram2("wFullColorRequestCount") != b"\x00":
                    raise TimingEvidenceError(f"{key}: visible route did not complete")
            finally:
                emulator.close()
    return measured


def _measure_yellow_vblank(root: Path) -> int:
    """Execute the active Yellow interrupt route to the same visible barrier."""
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
        Phase2Rom,
        numeric_symbols,
    )

    with tempfile.TemporaryDirectory(prefix="full-color-yellow-vblank-") as directory:
        emulator = Emulator(
            root / "pokeyellow.gbc", root / "pokeyellow.sym", Path(directory), cgb=True,
        )
        rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
        try:
            rom.activate()
            rom.write_wram2("wRendererOwner", rom.constants["RENDERER_YELLOW"])
            rom.write_wram2("wRendererPhase", rom.constants["YELLOW_ACTIVE"])
            rom.write_wram2("wRendererAdmissionOpen", 1)
            return _timed_home_vblank_to_visible_boundary(rom)
        finally:
            emulator.close()


def _measure_oam_post_boundary(root: Path) -> int:
    """Execute the complete next-frame OAM build and frozen enqueue."""
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
        Phase2Rom,
        numeric_symbols,
    )

    with tempfile.TemporaryDirectory(prefix="full-color-oam-timing-") as directory:
        emulator = Emulator(
            root / "pokeyellow.gbc", root / "pokeyellow.sym", Path(directory), cgb=True,
        )
        rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
        try:
            rom.activate()
            emulator.pyboy.memory[0xFF70] = 2
            emulator.pyboy.memory[emulator.symbols["wUpdateSpritesEnabled"]] = 1
            cycles = _timed_rom_call(rom, "PrepareFullColorProductionOAMForOwnedVBlank")
            if rom.read_wram2("wFullColorRequestCount") != b"\x01":
                raise TimingEvidenceError("actual post-boundary OAM producer did not enqueue")
            return cycles
        finally:
            emulator.close()


def _measure_yellow_transition_edges(
    root: Path,
    *,
    transition_budgets: dict[str, int] | None = None,
    yellow_map_id: int = 12,
    menu_map_id: int = 12,
    battle_transition_id: int = 0,
    trainer_class: int = 1,
    force_story_branch: bool = False,
    color_map_id: int = 12,
    only_keys: frozenset[str] | None = None,
) -> dict[str, int]:
    """Measure genuine game roots through their natural completion barriers."""
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_production_color_mode_transitions_rom import (
        TransitionRom,
        _constants,
    )

    def activate(rom: object) -> None:
        rom.call("InitRendererOwnership")
        rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
        rom.emulator.pyboy.memory[0xFF80] = 0xC9

    roots = {
        "TIME-ENTER-YELLOW-MAP": (
            "LoadMapData", "LoadMapData.fullColorProductionMapTransitionComplete",
        ),
        "TIME-ENTER-YELLOW-MENU": (
            "DisplayStartMenu",
            "RedisplayStartMenu_DoNotDrawStartMenu.fullColorProductionMenuTransitionComplete",
        ),
        "TIME-ENTER-YELLOW-DIALOGUE": (
            "DisplayTextID", "DisplayTextID.fullColorProductionDialogueTransitionComplete",
        ),
        "TIME-ENTER-YELLOW-BATTLE": (
            "InitBattleCommon", "_InitBattleCommon.fullColorProductionBattleTransitionComplete",
        ),
    }
    measured: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="full-color-transition-timing-") as directory:
        for key, (entry, barrier) in roots.items():
            if only_keys is not None and key not in only_keys:
                continue
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = TransitionRom(emulator, _constants(root / "pokeyellow.sym"))
            try:
                activate(rom)
                if transition_budgets and key in transition_budgets:
                    rom.write2(
                        "wFullColorTransitionBudget",
                        transition_budgets[key],
                        3,
                    )
                emulator.pyboy.memory[0xFF70] = 1
                emulator.pyboy.memory[emulator.symbols["hOnCGB"]] = 1
                emulator.pyboy.memory[emulator.symbols["wOnSGB"]] = 1
                emulator.pyboy.memory[0xFF50] = 1
                emulator.pyboy.memory[0xFF40] = 0x11
                emulator.pyboy.memory[0xFFFF] = 0
                emulator.pyboy.memory[0xFF0F] = 0
                current_map = {
                    "TIME-ENTER-YELLOW-MAP": yellow_map_id,
                    "TIME-ENTER-YELLOW-MENU": menu_map_id,
                    "TIME-ENTER-YELLOW-BATTLE": 0x3B if battle_transition_id & 4 else 12,
                }.get(key, 12)
                emulator.pyboy.memory[emulator.symbols["wCurMap"]] = current_map
                emulator.pyboy.memory[emulator.symbols["wUnusedObtainedBadges"]] = 1
                opponent = 200 + trainer_class if battle_transition_id & 1 else 16
                emulator.pyboy.memory[emulator.symbols["wEnemyMonSpecies2"]] = opponent
                emulator.pyboy.memory[emulator.symbols["wCurOpponent"]] = opponent
                emulator.pyboy.memory[emulator.symbols["wCurEnemyLevel"]] = 5
                emulator.pyboy.memory[emulator.symbols["wTrainerNo"]] = 1
                emulator.pyboy.memory[emulator.symbols["wPartyMon1HP"]] = 10
                emulator.pyboy.memory[emulator.symbols["wPartyMon1Level"]] = 5
                emulator.pyboy.memory[emulator.symbols["wPartyCount"]] = 1
                emulator.pyboy.memory[emulator.symbols["wPartySpecies"]] = 25
                emulator.pyboy.memory[emulator.symbols["wPartySpecies"] + 1] = 0xFF
                emulator.pyboy.memory[emulator.symbols["wPartyMon1Species"]] = 25
                emulator.pyboy.memory[emulator.symbols["wPartyMonNicks"]] = 0x50
                emulator.pyboy.memory[emulator.symbols["wPlayerName"]] = 0x50
                emulator.pyboy.memory[emulator.symbols["hTextID"]] = 3

                def menu_cancel() -> None:
                    emulator.pyboy.register_file.A = 1 << 1

                def advance_frame_counter() -> None:
                    counter = emulator.symbols["hFrameCounter"]
                    value = emulator.pyboy.memory[counter]
                    emulator.pyboy.memory[counter] = max(0, value - 1)
                    emulator.pyboy.memory[emulator.symbols["hJoyPressed"]] = 1

                common = {
                    "PlaySound": None,
                    "HandleMenuInput": menu_cancel,
                    "Joypad": None,
                    "DelayFrame": None,
                }
                if key == "TIME-ENTER-YELLOW-MAP":
                    stubs = common | {
                        "DisableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                        "EnableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                        "UpdateMusic6Times": None,
                        "PlayDefaultMusicFadeOutCurrent": None,
                    }
                elif key == "TIME-ENTER-YELLOW-MENU":
                    stubs = common
                elif key == "TIME-ENTER-YELLOW-BATTLE":
                    battle_events: list[str] = []

                    def select_battle_transition() -> None:
                        battle_events.append("BattleTransition")
                        emulator.pyboy.memory[emulator.symbols["wCurOpponent"]] = opponent
                        emulator.pyboy.memory[emulator.symbols["wCurEnemyLevel"]] = (
                            20 if battle_transition_id & 2 else 5
                        )
                        emulator.pyboy.memory[emulator.symbols["wPartyMon1HP"]] = 10
                        emulator.pyboy.memory[emulator.symbols["wPartyMon1Level"]] = 5

                    def record_trainer_pic() -> None:
                        pointer_address = emulator.symbols["wTrainerPicPointer"]
                        pointer = (
                            emulator.pyboy.memory[pointer_address]
                            | emulator.pyboy.memory[pointer_address + 1] << 8
                        )
                        trainer_class = emulator.pyboy.memory[emulator.symbols["wTrainerClass"]]
                        battle_events.append(
                            f"LoadTrainerPic(class={trainer_class},pointer={pointer:#06x})"
                        )
                        if force_story_branch:
                            emulator.pyboy.memory[emulator.symbols["wLoneAttackNo"]] = 1

                    def record_banked_event(name: str) -> None:
                        loaded = emulator.pyboy.memory[emulator.symbols["hLoadedROMBank"]]
                        default_palette = emulator.pyboy.memory[
                            emulator.symbols["wDefaultPaletteCommand"]
                        ]
                        wram_bank = emulator.pyboy.memory[0xFF70] & 7 or 1
                        battle_events.append(
                            f"{name}(bank={loaded:#04x},wram={wram_bank},default={default_palette:#04x})"
                        )

                    stubs = {
                        "Delay3": None,
                        "DelayFrame": None,
                        "Joypad": advance_frame_counter,
                        "PlaySound": None,
                        "DisableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                        "EnableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                        "SetScrollXForSlidingPlayerBodyLeft": None,
                    }
                else:
                    stubs = common
                observations = None
                if key == "TIME-ENTER-YELLOW-BATTLE":
                    observations = {
                        "GetTrainerInformation": lambda: battle_events.append("GetTrainerInformation"),
                        "ReadTrainer": lambda: battle_events.append("ReadTrainer"),
                        "DoBattleTransitionAndInitBattleVariables": lambda: battle_events.append("DoBattleTransition"),
                        "BattleTransition": select_battle_transition,
                        "_LoadTrainerPic": record_trainer_pic,
                        "CopyUncompressedPicToTilemap": lambda: battle_events.append("CopyTrainerTilemap"),
                        "_InitBattleCommon": lambda: record_banked_event("CommonPresentation"),
                        "PrintBeginningBattleText": lambda: battle_events.append("PrintBeginningBattleText"),
                        "PrintText": lambda: battle_events.append("PrintText"),
                        "RecordAndCompleteYellowPresentationRoot": lambda: record_banked_event("CompleteYellow"),
                        "CommitYellowPresentationTileMapForContext": lambda: record_banked_event("CommitYellowTilemap"),
                        "RecordYellowReconstructionComplete": lambda: record_banked_event("RecordYellow"),
                        "CompleteYellowPresentation": lambda: record_banked_event("ActivateYellow"),
                    }
                try:
                    measured[key] = _timed_rom_root_to_barrier(
                        rom,
                        entry,
                        barrier,
                        stubs=stubs,
                        observations=observations,
                    )
                except TimingEvidenceError as error:
                    raise TimingEvidenceError(
                        f"{key}: events={battle_events}: {error}"
                    ) from error
                if rom.read2("wRendererOwner") != rom.constants["RENDERER_YELLOW"]:
                    raise TimingEvidenceError(f"{key}: root did not finish under Yellow ownership")
                if rom.read2("wRendererPhase") != rom.constants["YELLOW_ACTIVE"]:
                    raise TimingEvidenceError(f"{key}: root did not reach Yellow active")
                if rom.read2("wRendererAdmissionOpen") != 1:
                    raise TimingEvidenceError(f"{key}: root did not reopen admission")
            finally:
                emulator.close()
        for soft, key, entry, barrier in (
            (
                0,
                "TIME-ENTER-YELLOW-HARD-RESET",
                "Init",
                "DisplayTitleScreen.fullColorProductionHardResetTransitionComplete",
            ),
            (
                1,
                "TIME-ENTER-YELLOW-SOFT-RESET",
                "SoftResetRendererOwnership",
                "DisplayTitleScreen.fullColorProductionSoftResetTransitionComplete",
            ),
        ):
            if only_keys is not None and key not in only_keys:
                continue
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = TransitionRom(emulator, _constants(root / "pokeyellow.sym"))
            try:
                activate(rom)
                if transition_budgets and key in transition_budgets and soft:
                    rom.write2(
                        "wFullColorTransitionBudget",
                        transition_budgets[key],
                        3,
                    )
                emulator.pyboy.memory[0xFF70] = 1
                emulator.pyboy.memory[emulator.symbols["hSoftReset"]] = soft
                emulator.pyboy.memory[emulator.symbols["hOnCGB"]] = 1
                emulator.pyboy.memory[0xFF50] = 1
                emulator.pyboy.memory[0xFF40] = 0x11
                emulator.pyboy.memory[0xFFFF] = 0
                emulator.pyboy.memory[0xFF0F] = 0

                def inject_hard_reset_budget() -> None:
                    if not transition_budgets or key not in transition_budgets:
                        return
                    rom.write2(
                        "wFullColorTransitionBudget",
                        transition_budgets[key],
                        3,
                    )

                measured[key] = _timed_rom_root_to_barrier(
                    rom,
                    entry,
                    barrier,
                    stubs={
                        "DelayFrame": None,
                        "DelayFrames": None,
                        "Joypad": advance_frame_counter,
                        "LoadSGB": None,
                        "PlaySound": None,
                        "StopAllSounds": None,
                        "DisableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x11),
                        "EnableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                    },
                    observations=(
                        {"CheckFullColorHardResetTransitionBudget": inject_hard_reset_budget}
                        if not soft
                        else None
                    ),
                )
                if rom.read2("wRendererOwner") != rom.constants["RENDERER_YELLOW"]:
                    raise TimingEvidenceError(f"{key}: root did not finish under Yellow ownership")
                if rom.read2("wRendererPhase") != rom.constants["YELLOW_ACTIVE"]:
                    raise TimingEvidenceError(f"{key}: root did not reach Yellow active")
                if rom.read2("wRendererAdmissionOpen") != 1:
                    raise TimingEvidenceError(f"{key}: root did not reopen admission")
            finally:
                emulator.close()
        key = "TIME-ENTER-COLOR-MAP"
        if only_keys is not None and key not in only_keys:
            return measured
        emulator = Emulator(
            root / "pokeyellow.gbc", root / "pokeyellow.sym",
            Path(directory) / key, cgb=True,
        )
        rom = TransitionRom(emulator, _constants(root / "pokeyellow.sym"))
        try:
            activate(rom)
            if transition_budgets and key in transition_budgets:
                rom.write2(
                    "wFullColorTransitionBudget",
                    transition_budgets[key],
                    3,
                )
            emulator.pyboy.memory[0xFF70] = 1
            rom.write2("wRendererOwner", rom.constants["RENDERER_YELLOW"])
            rom.write2("wRendererPhase", rom.constants["YELLOW_ACTIVE"])
            rom.write2("wRendererAdmissionOpen", 1)
            emulator.pyboy.memory[emulator.symbols["hOnCGB"]] = 1
            emulator.pyboy.memory[emulator.symbols["wOnSGB"]] = 1
            emulator.pyboy.memory[0xFF50] = 1
            emulator.pyboy.memory[0xFF40] = 0x11
            emulator.pyboy.memory[0xFFFF] = 0
            emulator.pyboy.memory[0xFF0F] = 0
            emulator.pyboy.memory[emulator.symbols["wCurMap"]] = color_map_id
            emulator.pyboy.memory[emulator.symbols["wUnusedObtainedBadges"]] = 0
            emulator.pyboy.memory[emulator.symbols["wDefaultPaletteCommand"]] = 0x08
            measured[key] = _timed_rom_root_to_barrier(
                rom,
                "LoadMapData",
                "CompleteOrdinaryMapPresentationRoot.fullColorProductionColorMapTransitionComplete",
                stubs={
                    "DisableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x11),
                    "EnableLCD": lambda: emulator.pyboy.memory.__setitem__(0xFF40, 0x91),
                    "DelayFrame": None,
                    "PlaySound": None,
                    "UpdateMusic6Times": None,
                    "PlayDefaultMusicFadeOutCurrent": None,
                },
            )
            if rom.read2("wRendererOwner") != rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]:
                raise TimingEvidenceError(f"{key}: root did not finish under Color ownership")
            if rom.read2("wRendererPhase") != rom.constants["OVERWORLD_ACTIVE"]:
                raise TimingEvidenceError(f"{key}: root did not reach Color active")
            if rom.read2("wRendererAdmissionOpen") != 1:
                raise TimingEvidenceError(f"{key}: root did not reopen admission")
        finally:
            emulator.close()
    return measured


def measure_rows(root: Path) -> dict[str, TimingRow]:
    rom = (root / "pokeyellow.gbc").read_bytes()
    decoder = LinkedTimingDecoder(rom, load_sym(root / "pokeyellow.sym"))
    _, speed_switch = decoder.span(Span("StartCGB", "StartCGB.speed_ready"))
    if b"\x3e\x01\xe0\x4d\x10\x00" not in speed_switch:
        raise TimingEvidenceError(
            "linked StartCGB path does not arm KEY1 and execute STOP for double speed"
        )
    speed_digest = hashlib.sha256(speed_switch).digest()
    selector = (Span("ResolveEffectiveRendererOwner", "ResolveCurrentOrdinaryMapOwner"),)
    yellow = (
        Span("BeginForcedYellowPresentation", "SetFullColorProductionReturnContext"),
        Span("RecordYellowReconstructionComplete", "CompleteYellowPresentation"),
        Span("CompleteYellowPresentation", "CompleteFullColorMapReconstruction"),
    )
    color = (
        Span("BeginFullColorMapEntry", "SelectYellowRendererForReconstruction"),
        Span("CompleteFullColorMapReconstruction", "LoadFullColorFontGraphicsSelected"),
        Span("ReconstructFullColorMapEntry", "BeginFullColorPartyHandoff"),
    )
    palette_bg = (
        Span("CommitFullColorBGPaletteSelected", "CommitFullColorBGPaletteSelected.copy"),
        Span("CommitFullColorBGPaletteSelected.copy", "CommitFullColorOBJPaletteSelected", 64),
    )
    palette_obj = (
        Span("CommitFullColorOBJPaletteSelected", "CommitFullColorOBJPaletteSelected.copy"),
        Span("CommitFullColorOBJPaletteSelected.copy", "PrepareFullColorPairedTransferSelected", 64),
    )
    paired_setup = Span("CommitFullColorPairedTransferSelected", "CommitFullColorMapPlaneSelected")
    paired_cell = Span("CommitFullColorMapPlaneSelected.cell", "AdvanceFullColorMapCellSelected")
    paired_row = Span("CommitFullColorMapPlaneSelected.row", "CommitFullColorMapPlaneSelected.cell")
    paired_tail = Span("AdvanceFullColorMapCellSelected", "LoadFullColorActiveDescriptorSelected")
    production_paired_prefix = Span(
        "CommitFullColorPairedTransferSelected",
        "CommitFullColorPairedTransferSelected.firstPlane",
    )
    production_paired_middle = Span(
        "CommitFullColorPairedTransferSelected.firstPlaneComplete",
        "CommitFullColorPairedTransferSelected.secondPlane",
    )
    production_paired_tail = Span(
        "CommitFullColorPairedTransferSelected.secondPlaneComplete",
        "CommitFullColorPairedTransferSelected.complete",
    )
    production_planes = {
        "TIME-STREAM-HORIZONTAL": Span(
            "CommitFullColorProductionMapColumnPairSelected",
            "CommitFullColorProductionMapColumnSelected",
        ),
        "TIME-STREAM-VERTICAL": Span(
            "CommitFullColorProductionMapRowPairSelected",
            "CommitFullColorProductionMapColumnPairSelected",
        ),
        "TIME-STREAM-CONNECTION": Span(
            "CommitFullColorProductionMapRowPairSelected",
            "CommitFullColorProductionMapColumnPairSelected",
        ),
        "TIME-TRANSFER-ROW": Span(
            "CommitFullColorProductionMapRowSelected",
            "CommitFullColorProductionMapRowPairSelected",
        ),
        "TIME-TRANSFER-COLUMN": Span(
            "CommitFullColorProductionMapColumnSelected",
            "CommitFullColorProductionMapColumnSelectedEnd",
        ),
    }

    rows: dict[str, TimingRow] = {}
    rows["TIME-SELECTOR"] = _row(
        decoder, "TIME-SELECTOR", "pure preference/context/map selector", selector,
        deadline=512, guard=16,
    )
    yellow_cost, _, _ = _equation(decoder, *yellow)
    for suffix in ("MAP", "MENU", "DIALOGUE", "BATTLE", "HARD-RESET", "SOFT-RESET"):
        key = f"TIME-ENTER-YELLOW-{suffix}"
        rows[key] = _row(
            decoder, key, f"complete Yellow {suffix.lower()} handoff", yellow,
            # Soft reset's 32-frame wait happens while both visible routes are
            # closed and is outside the transition cost. Its destination work
            # still ends at the same finite boot pre-display boundary.
            deadline=yellow_cost + 64,
            guard=64,
        )
    color_cost, _, _ = _equation(decoder, *color)
    rows["TIME-ENTER-COLOR-MAP"] = _row(
        decoder, "TIME-ENTER-COLOR-MAP", "complete Color map reconstruction", color,
        deadline=color_cost + 64, guard=64,
    )
    rows["TIME-VBLANK-YELLOW"] = _row(
        decoder, "TIME-VBLANK-YELLOW", "Yellow VBlank selector route",
        (Span("RouteRendererOwnershipVBlank", "RouteRendererOwnershipVBlank.color"),),
        deadline=VBLANK_MACHINE_CYCLES, guard=VBLANK_GUARD_CYCLES,
    )
    yellow_vblank = rows["TIME-VBLANK-YELLOW"]
    rows["TIME-VBLANK-YELLOW"] = TimingRow(
        yellow_vblank.key, yellow_vblank.operation,
        ("linked-StartCGB-KEY1-STOP=double-speed",) + yellow_vblank.terms,
        yellow_vblank.worst_cycles, yellow_vblank.deadline_cycles,
        yellow_vblank.guard_cycles, yellow_vblank.defer_threshold,
        hashlib.sha256(
            speed_digest + bytes.fromhex(yellow_vblank.linked_sha256)
        ).hexdigest(),
    )

    palette_deadline = VBLANK_MACHINE_CYCLES
    rows["TIME-PALETTE-BG"] = _row(
        decoder, "TIME-PALETTE-BG", "64-byte BG palette commit", palette_bg,
        deadline=palette_deadline, guard=VBLANK_GUARD_CYCLES,
    )
    rows["TIME-PALETTE-OBJ"] = _row(
        decoder, "TIME-PALETTE-OBJ", "64-byte OBJ palette commit", palette_obj,
        deadline=palette_deadline, guard=VBLANK_GUARD_CYCLES,
    )
    rows["TIME-PALETTE-COMBINED"] = _row(
        decoder, "TIME-PALETTE-COMBINED", "hidden BG and OBJ palette commit",
        palette_bg + palette_obj,
        deadline=(rows["TIME-PALETTE-BG"].worst_cycles
                  + rows["TIME-PALETTE-OBJ"].worst_cycles + 64),
        guard=64,
    )

    transfer_cells = {
        "TIME-TRANSFER-LOAD": 360,
        "TIME-TRANSFER-RELOAD": 360,
        "TIME-STREAM-HORIZONTAL": 36,
        "TIME-STREAM-VERTICAL": 40,
        "TIME-STREAM-CONNECTION": 40,
        "TIME-TRANSFER-ROW": 20,
        "TIME-TRANSFER-COLUMN": 18,
        "TIME-TRANSFER-RECTANGLE": 360,
        "TIME-TRANSFER-THIRD-SCREEN": 120,
        "TIME-TRANSFER-ALTERNATE-BG": 360,
    }
    for key, cells in transfer_cells.items():
        visible = cells <= 40
        if key in production_planes:
            plane = production_planes[key]
            spans = (
                production_paired_prefix, plane,
                production_paired_middle, plane, production_paired_tail,
            )
        else:
            spans = (paired_setup, Span(paired_cell.start, paired_cell.end, cells * 2),
                     Span(paired_row.start, paired_row.end, 2), paired_tail)
        transfer_cost, _, _ = _equation(decoder, *spans)
        rows[key] = _row(
            decoder, key, f"paired tile/attribute transfer ({cells} cells)",
            spans,
            deadline=VBLANK_MACHINE_CYCLES if visible else transfer_cost + 64,
            guard=VBLANK_GUARD_CYCLES if visible else 64,
        )
    animation = (
        Span("CommitFullColorAnimationReplacementSelected", "CommitFullColorAnimationReplacementSelected.tile"),
        Span("CommitFullColorAnimationReplacementSelected.tile", "PrepareFullColorOAMBatchSelected", 16),
    )
    for key, operation in (
        ("TIME-ANIMATED-TILE", "animated tile plus attribute"),
        ("TIME-FIELD-REPLACEMENT", "field replacement tile plus attribute"),
    ):
        rows[key] = _row(
            decoder, key, operation, animation,
            deadline=VBLANK_MACHINE_CYCLES, guard=VBLANK_GUARD_CYCLES,
        )
    rows["TIME-OAM-SHADOW-BUILD"] = _row(
        decoder, "TIME-OAM-SHADOW-BUILD", "bounded sixteen-sprite shadow build",
        (Span("PrepareOAMData.updateEnabled", "PrepareOAMData.asm_4a41"),),
        deadline=VBLANK_MACHINE_CYCLES, guard=VBLANK_GUARD_CYCLES,
    )
    rows["TIME-OAM-DMA"] = _row(
        decoder, "TIME-OAM-DMA", "160-byte hardware DMA", (),
        fixed=(("hardware-oam-dma", DMA_MACHINE_CYCLES),),
        deadline=VBLANK_MACHINE_CYCLES, guard=VBLANK_GUARD_CYCLES,
    )
    rows["TIME-VBLANK-OVERWORLD"] = _row(
        decoder, "TIME-VBLANK-OVERWORLD", "Color route selector and largest admitted visible unit",
        (Span("RouteRendererOwnershipVBlank.color", "RouteRendererOwnershipVBlank.closed"),),
        fixed=(("largest-visible-commit", max(
            rows["TIME-PALETTE-BG"].worst_cycles,
            rows["TIME-PALETTE-OBJ"].worst_cycles,
            rows["TIME-STREAM-VERTICAL"].worst_cycles,
            rows["TIME-OAM-DMA"].worst_cycles,
        )),),
        deadline=VBLANK_MACHINE_CYCLES, guard=VBLANK_GUARD_CYCLES,
    )

    actual_edges = _measure_scheduler_edges(root)
    hidden_keys = {
        "TIME-TRANSFER-LOAD", "TIME-TRANSFER-RELOAD",
        "TIME-TRANSFER-RECTANGLE", "TIME-TRANSFER-THIRD-SCREEN",
        "TIME-TRANSFER-ALTERNATE-BG",
    }
    rom_digest = hashlib.sha256(rom).digest()
    for key, cycles in actual_edges.items():
        prior = rows[key]
        guard = 64 if key in hidden_keys else VBLANK_GUARD_CYCLES
        deadline = cycles + guard if key in hidden_keys else VBLANK_MACHINE_CYCLES
        if cycles + guard > deadline:
            raise TimingEvidenceError(
                f"{key}: actual linked edge {cycles} plus guard {guard} misses {deadline}"
            )
        digest = hashlib.sha256(
            bytes.fromhex(prior.linked_sha256) + rom_digest
            + key.encode() + cycles.to_bytes(4, "little")
        ).hexdigest()
        rows[key] = TimingRow(
            key, prior.operation,
            prior.terms + ((
                f"actual-linked-PREPARED-to-COMPLETE={cycles}"
                if key in hidden_keys
                else f"actual-linked-PREPARED-to-COMPLETE={cycles}"
            ),),
            cycles, deadline, guard, cycles, digest,
        )
    oam_build_cycles = _measure_oam_post_boundary(root)
    oam_build = rows["TIME-OAM-SHADOW-BUILD"]
    if oam_build_cycles + 64 > FRAME_MACHINE_CYCLES:
        raise TimingEvidenceError("post-boundary OAM build misses the next visible boundary")
    rows["TIME-OAM-SHADOW-BUILD"] = TimingRow(
        oam_build.key,
        "actual next-frame OAM build and frozen scheduler enqueue",
        (f"actual-PrepareFullColorProductionOAMForOwnedVBlank={oam_build_cycles}",),
        oam_build_cycles, FRAME_MACHINE_CYCLES, 64, oam_build_cycles,
        hashlib.sha256(
            rom_digest + b"post-boundary-oam" + oam_build_cycles.to_bytes(4, "little")
        ).hexdigest(),
    )
    transition_scenarios = (
        ("route1-normal-id0", dict(yellow_map_id=0x0C, menu_map_id=0x0C, battle_transition_id=0, color_map_id=0x0C)),
        ("pallet-safari-id1", dict(yellow_map_id=0x00, menu_map_id=0xD9, battle_transition_id=1, color_map_id=0x00)),
        ("viridian-id2", dict(yellow_map_id=0x01, battle_transition_id=2)),
        ("route21-id3", dict(yellow_map_id=0x20, battle_transition_id=3)),
        ("battle-id4", dict(battle_transition_id=4)),
        ("battle-id5", dict(battle_transition_id=5)),
        ("battle-id6", dict(battle_transition_id=6)),
        ("battle-id7", dict(battle_transition_id=7)),
    )
    transition_measurements_list: list[tuple[str, dict[str, int]]] = []
    for name, parameters in transition_scenarios:
        try:
            measurement = _measure_yellow_transition_edges(root, **parameters)
        except TimingEvidenceError as error:
            raise TimingEvidenceError(f"transition scenario {name}: {error}") from error
        transition_measurements_list.append((name, measurement))
    for trainer_class in range(1, 48):
        if trainer_class in {13, 27}:  # no party data; unreachable classes
            continue
        name = f"trainer-class-{trainer_class:02x}"
        try:
            measurement = _measure_yellow_transition_edges(
                root,
                battle_transition_id=1,
                trainer_class=trainer_class,
                only_keys=frozenset({"TIME-ENTER-YELLOW-BATTLE"}),
            )
        except TimingEvidenceError as error:
            raise TimingEvidenceError(f"transition scenario {name}: {error}") from error
        transition_measurements_list.append((name, measurement))
    transition_measurements_list.append((
        "trainer-story-branch",
        _measure_yellow_transition_edges(
            root,
            battle_transition_id=1,
            trainer_class=1,
            force_story_branch=True,
            only_keys=frozenset({"TIME-ENTER-YELLOW-BATTLE"}),
        ),
    ))
    transition_measurements = tuple(transition_measurements_list)
    for key in (
        "TIME-ENTER-YELLOW-MAP",
        "TIME-ENTER-YELLOW-MENU",
        "TIME-ENTER-YELLOW-DIALOGUE",
        "TIME-ENTER-YELLOW-BATTLE",
        "TIME-ENTER-YELLOW-HARD-RESET",
        "TIME-ENTER-YELLOW-SOFT-RESET",
        "TIME-ENTER-COLOR-MAP",
    ):
        scenario_cycles = tuple(
            (name, measurements[key])
            for name, measurements in transition_measurements
            if key in measurements
        )
        scenario_max = max(value for _, value in scenario_cycles)
        cycles = scenario_max
        prior = rows[key]
        actual_roots = {
            "TIME-ENTER-YELLOW-MAP": "LoadMapData..LoadMapData.fullColorProductionMapTransitionComplete",
            "TIME-ENTER-YELLOW-MENU": "DisplayStartMenu..RedisplayStartMenu_DoNotDrawStartMenu.fullColorProductionMenuTransitionComplete",
            "TIME-ENTER-YELLOW-DIALOGUE": "DisplayTextID..DisplayTextID.fullColorProductionDialogueTransitionComplete",
            "TIME-ENTER-YELLOW-BATTLE": "InitBattleCommon.._InitBattleCommon.fullColorProductionBattleTransitionComplete",
            "TIME-ENTER-YELLOW-HARD-RESET": "Init..DisplayTitleScreen.fullColorProductionHardResetTransitionComplete",
            "TIME-ENTER-YELLOW-SOFT-RESET": "SoftResetRendererOwnership..DisplayTitleScreen.fullColorProductionSoftResetTransitionComplete",
            "TIME-ENTER-COLOR-MAP": "LoadMapData..CompleteOrdinaryMapPresentationRoot.fullColorProductionColorMapTransitionComplete",
        }
        exclusions = {
            "TIME-ENTER-YELLOW-MAP": "LCD scanline synchronization and post-barrier music excluded",
            "TIME-ENTER-YELLOW-MENU": "audio dispatch and post-barrier menu input excluded",
            "TIME-ENTER-YELLOW-DIALOGUE": "frame/input synchronization excluded; complete dialogue initialization executed",
            "TIME-ENTER-YELLOW-BATTLE": "frame/input/scanline synchronization excluded; complete wild and every reachable trainer-class presentation plus all eight animation branches executed",
            "TIME-ENTER-YELLOW-HARD-RESET": "SGB handshake plus frame/input/audio synchronization excluded; intro and title presentation executed",
            "TIME-ENTER-YELLOW-SOFT-RESET": "32-frame hold, SGB handshake, and frame/input/audio synchronization excluded; intro and title presentation executed",
            "TIME-ENTER-COLOR-MAP": "LCD scanline synchronization and post-barrier music excluded",
        }
        terms = (
            f"actual-linked-root({actual_roots[key]})={scenario_max}",
            *(f"scenario({name})={value}" for name, value in scenario_cycles),
            exclusions[key],
        )
        rows[key] = TimingRow(
            key, prior.operation,
            terms,
            cycles, cycles + 64, 64, cycles,
            hashlib.sha256(
                rom_digest + key.encode() + cycles.to_bytes(4, "little")
                + "\0".join(terms).encode()
            ).hexdigest(),
        )
    combined_cost = (
        rows["TIME-PALETTE-BG"].worst_cycles
        + rows["TIME-PALETTE-OBJ"].worst_cycles
    )
    combined = rows["TIME-PALETTE-COMBINED"]
    rows["TIME-PALETTE-COMBINED"] = TimingRow(
        combined.key, combined.operation,
        rows["TIME-PALETTE-BG"].terms + rows["TIME-PALETTE-OBJ"].terms,
        combined_cost, combined_cost + 64, 64, combined_cost,
        hashlib.sha256(
            bytes.fromhex(rows["TIME-PALETTE-BG"].linked_sha256)
            + bytes.fromhex(rows["TIME-PALETTE-OBJ"].linked_sha256)
        ).hexdigest(),
    )
    yellow_vblank_cycles = _measure_yellow_vblank(root)
    if yellow_vblank_cycles + VBLANK_GUARD_CYCLES > VBLANK_MACHINE_CYCLES:
        raise TimingEvidenceError(
            f"TIME-VBLANK-YELLOW: {yellow_vblank_cycles} misses double-speed VBlank"
        )
    rows["TIME-VBLANK-YELLOW"] = TimingRow(
        "TIME-VBLANK-YELLOW",
        "actual Yellow interrupt root through its presentation boundary",
        (
            "linked-StartCGB-KEY1-STOP=double-speed",
            f"actual-VBlank-to-FullColorProductionVBlankVisibleRouteComplete={yellow_vblank_cycles}",
        ),
        yellow_vblank_cycles, VBLANK_MACHINE_CYCLES, VBLANK_GUARD_CYCLES,
        yellow_vblank_cycles,
        hashlib.sha256(
            speed_digest + rom_digest + b"yellow-home-vblank"
            + yellow_vblank_cycles.to_bytes(4, "little")
        ).hexdigest(),
    )
    actual_vblank_routes = _measure_color_vblank_routes(root)
    worst_vblank_kind, vblank_cost = max(
        actual_vblank_routes.items(), key=lambda item: item[1]
    )
    if vblank_cost + VBLANK_GUARD_CYCLES > VBLANK_MACHINE_CYCLES:
        raise TimingEvidenceError(
            f"TIME-VBLANK-OVERWORLD: {vblank_cost} misses double-speed VBlank"
        )
    rows["TIME-VBLANK-OVERWORLD"] = TimingRow(
        "TIME-VBLANK-OVERWORLD",
        "actual Color visible route through its presentation boundary",
        ("linked-StartCGB-KEY1-STOP=double-speed",) + tuple(
            f"actual-VBlank-to-visible-boundary[{kind}]={cycles}"
            for kind, cycles in sorted(actual_vblank_routes.items())
        ) + (f"worst-case={worst_vblank_kind}",),
        vblank_cost, VBLANK_MACHINE_CYCLES, VBLANK_GUARD_CYCLES,
        vblank_cost,
        hashlib.sha256(
            speed_digest + rom_digest + b"".join(
                kind.encode() + cycles.to_bytes(4, "little")
                for kind, cycles in sorted(actual_vblank_routes.items())
            )
        ).hexdigest(),
    )
    if set(rows) != set(REQUIRED_TIMING_KEYS):
        missing = set(REQUIRED_TIMING_KEYS) - rows.keys()
        extra = rows.keys() - set(REQUIRED_TIMING_KEYS)
        raise TimingEvidenceError(f"timing key/order mismatch missing={missing} extra={extra}")
    return {key: rows[key] for key in REQUIRED_TIMING_KEYS}


def render_rgbds_constants(rows: dict[str, TimingRow]) -> str:
    values = {
        "FULL_COLOR_PRODUCTION_VBLANK_COMMIT_BUDGET": rows["TIME-VBLANK-OVERWORLD"].defer_threshold,
        "FULL_COLOR_PRODUCTION_HIDDEN_COMMIT_BUDGET": rows["TIME-TRANSFER-RECTANGLE"].defer_threshold,
        "FULL_COLOR_PRODUCTION_ROW_RESERVATION": rows["TIME-TRANSFER-ROW"].defer_threshold,
        "FULL_COLOR_PRODUCTION_COLUMN_RESERVATION": rows["TIME-TRANSFER-COLUMN"].defer_threshold,
        "FULL_COLOR_PRODUCTION_MOVEMENT_ROW_RESERVATION": rows["TIME-STREAM-VERTICAL"].defer_threshold,
        "FULL_COLOR_PRODUCTION_MOVEMENT_COLUMN_RESERVATION": rows["TIME-STREAM-HORIZONTAL"].defer_threshold,
        "FULL_COLOR_PRODUCTION_CONNECTION_RESERVATION": rows["TIME-STREAM-CONNECTION"].defer_threshold,
        "FULL_COLOR_PRODUCTION_RECTANGLE_RESERVATION": rows["TIME-TRANSFER-RECTANGLE"].defer_threshold,
        "FULL_COLOR_PRODUCTION_THIRD_SCREEN_RESERVATION": rows["TIME-TRANSFER-THIRD-SCREEN"].defer_threshold,
        "FULL_COLOR_PRODUCTION_PALETTE_RESERVATION": max(
            rows["TIME-PALETTE-BG"].worst_cycles, rows["TIME-PALETTE-OBJ"].worst_cycles
        ),
        "FULL_COLOR_PRODUCTION_ANIMATION_RESERVATION": rows["TIME-ANIMATED-TILE"].worst_cycles,
        "FULL_COLOR_PRODUCTION_OAM_RESERVATION": rows["TIME-OAM-DMA"].worst_cycles,
        "FULL_COLOR_TRANSITION_MAP_BUDGET": rows["TIME-ENTER-YELLOW-MAP"].worst_cycles,
        "FULL_COLOR_TRANSITION_MENU_BUDGET": rows["TIME-ENTER-YELLOW-MENU"].worst_cycles,
        "FULL_COLOR_TRANSITION_DIALOGUE_BUDGET": rows["TIME-ENTER-YELLOW-DIALOGUE"].worst_cycles,
        "FULL_COLOR_TRANSITION_BATTLE_BUDGET": rows["TIME-ENTER-YELLOW-BATTLE"].worst_cycles,
        "FULL_COLOR_TRANSITION_HARD_RESET_BUDGET": rows["TIME-ENTER-YELLOW-HARD-RESET"].worst_cycles,
        "FULL_COLOR_TRANSITION_SOFT_RESET_BUDGET": rows["TIME-ENTER-YELLOW-SOFT-RESET"].worst_cycles,
        "FULL_COLOR_TRANSITION_COLOR_MAP_BUDGET": rows["TIME-ENTER-COLOR-MAP"].worst_cycles,
    }
    if any(value <= 0 for value in values.values()):
        raise TimingEvidenceError("production budgets must be finite and positive")
    if any(
        value > (0xFFFFFF if name.startswith("FULL_COLOR_TRANSITION_") else 0xFFFF)
        for name, value in values.items()
    ):
        raise TimingEvidenceError("production budget exceeds its linked seam width")
    lines = [
        "; Generated by tools.rom_tests.full_color.production_timing; do not hand edit.\n",
    ]
    lines.extend(f"DEF {name} EQU {values[name]}\n" for name in sorted(values))
    return "".join(lines)


def render_evidence(rows: dict[str, TimingRow]) -> str:
    return json.dumps(
        {"schema": "full-color-production-timing-v1", "rows": [row.to_dict() for row in rows.values()]},
        indent=2,
        sort_keys=True,
    ) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    rows = measure_rows(root)
    _atomic_write(arguments.output, render_rgbds_constants(rows))
    if arguments.evidence is not None:
        _atomic_write(arguments.evidence, render_evidence(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
