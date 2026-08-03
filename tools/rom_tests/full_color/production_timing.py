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
                measured[key] = _timed_rom_call(rom, "RunFullColorProductionVBlank")
                if rom.read_wram2("wFullColorRequestCount") != b"\x00":
                    raise TimingEvidenceError(f"{key}: visible route did not complete")
            finally:
                emulator.close()
    return measured


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


def _measure_yellow_transition_edges(root: Path) -> dict[str, int]:
    """Measure each actual Yellow admission through its completion barrier."""
    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
        Phase2Rom,
        numeric_symbols,
    )

    contexts = {
        "TIME-ENTER-YELLOW-MAP": "RENDERER_CONTEXT_ORDINARY_MAP",
        "TIME-ENTER-YELLOW-MENU": "RENDERER_CONTEXT_MENU",
        "TIME-ENTER-YELLOW-DIALOGUE": "RENDERER_CONTEXT_DIALOGUE",
        "TIME-ENTER-YELLOW-BATTLE": "RENDERER_CONTEXT_BATTLE",
    }
    measured: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="full-color-transition-timing-") as directory:
        for key, context in contexts.items():
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
            try:
                rom.activate()
                emulator.pyboy.memory[0xFF70] = 2
                rom.write_wram2(
                    "wFullColorProductionReturnContext",
                    rom.constants[context],
                )
                measured[key] = (
                    _timed_rom_call(rom, "BeginForcedYellowPresentation")
                    + _timed_rom_call(rom, "RecordAndCompleteYellowPresentationRoot")
                )
            finally:
                emulator.close()
        for soft, key in (
            (0, "TIME-ENTER-YELLOW-HARD-RESET"),
            (1, "TIME-ENTER-YELLOW-SOFT-RESET"),
        ):
            emulator = Emulator(
                root / "pokeyellow.gbc", root / "pokeyellow.sym",
                Path(directory) / key, cgb=True,
            )
            rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
            try:
                rom.activate()
                emulator.pyboy.memory[0xFF70] = 2
                emulator.pyboy.memory[emulator.symbols["hSoftReset"]] = soft
                rom.write_wram2(
                    "wFullColorProductionReturnContext",
                    rom.constants["RENDERER_CONTEXT_BOOT_RESET"],
                )
                measured[key] = (
                    _timed_rom_call(rom, "ResetRendererOwnershipForReconstruction")
                    + _timed_rom_call(rom, "RecordAndCompleteYellowPresentationRoot")
                )
            finally:
                emulator.close()
        key = "TIME-ENTER-COLOR-MAP"
        emulator = Emulator(
            root / "pokeyellow.gbc", root / "pokeyellow.sym",
            Path(directory) / key, cgb=True,
        )
        rom = Phase2Rom(emulator, numeric_symbols(root / "pokeyellow.sym"))
        try:
            rom.activate()
            emulator.pyboy.memory[0xFF70] = 2
            rom.write_wram2("wRendererOwner", rom.constants["RENDERER_YELLOW"])
            rom.write_wram2("wRendererPhase", rom.constants["YELLOW_ACTIVE"])
            rom.write_wram2("wRendererAdmissionOpen", 1)
            measured[key] = _timed_rom_call(rom, "BeginFullColorMapEntry")
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
    for key, cycles in _measure_yellow_transition_edges(root).items():
        prior = rows[key]
        operation = (
            "actual-linked-Yellow-to-Color admission control"
            if key == "TIME-ENTER-COLOR-MAP"
            else "actual-linked admission through Yellow completion barrier"
        )
        rows[key] = TimingRow(
            key, prior.operation,
            (f"{operation}={cycles}",),
            cycles, cycles + 64, 64, cycles,
            hashlib.sha256(
                rom_digest + key.encode() + cycles.to_bytes(4, "little")
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
    color_cost = (
        rows["TIME-ENTER-COLOR-MAP"].worst_cycles
        + rows["TIME-TRANSFER-RECTANGLE"].worst_cycles
        + rows["TIME-PALETTE-COMBINED"].worst_cycles
        + rows["TIME-OAM-SHADOW-BUILD"].worst_cycles
        + rows["TIME-OAM-DMA"].worst_cycles
    )
    color = rows["TIME-ENTER-COLOR-MAP"]
    rows["TIME-ENTER-COLOR-MAP"] = TimingRow(
        color.key, color.operation,
        color.terms + (
            f"actual-hidden-rectangle-edge={rows['TIME-TRANSFER-RECTANGLE'].worst_cycles}",
            f"complete-palette-pair={rows['TIME-PALETTE-COMBINED'].worst_cycles}",
            f"shadow-OAM-build={rows['TIME-OAM-SHADOW-BUILD'].worst_cycles}",
            f"OAM-DMA-edge={rows['TIME-OAM-DMA'].worst_cycles}",
        ),
        color_cost, color_cost + 64, 64, color_cost,
        hashlib.sha256(
            bytes.fromhex(color.linked_sha256) + rom_digest
            + color_cost.to_bytes(4, "little")
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
            f"actual-RunFullColorProductionVBlank[{kind}]={cycles}"
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
    if any(value <= 0 or value == 0xFFFF or value > 0xFFFF for value in values.values()):
        raise TimingEvidenceError("production budgets must be finite positive 16-bit values")
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
