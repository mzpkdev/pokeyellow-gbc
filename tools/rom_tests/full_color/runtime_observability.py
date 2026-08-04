"""Observational readers for the versioned full-color debug-ROM carrier."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Sequence, TYPE_CHECKING
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r"Using SDL2 binaries from pysdl2-dll .+",
        category=UserWarning,
    )
    from tools.rom_tests.emulator import Emulator

from .enums import CancellationReason, JobState, Owner, Phase, RequestResult
from .snapshots import (
    REQUIRED_RECONSTRUCTION_ITEMS,
    SemanticSnapshot,
)
from .trace import (
    TRACE_LAYOUT_VERSION,
    TraceSymbols,
    WriterTrace,
    decode_writer_ring,
)
from .runner_output import (
    NULL_REPORTER,
    OutputMode,
    RunnerReporter,
    add_output_argument,
)

if TYPE_CHECKING:
    from .renderer_oracle import ConformanceCase


DEBUG_MAGIC = b"FCG0"
DEBUG_LAYOUT_VERSION = 2
DEBUG_SRAM_BANK = 3
DEBUG_TRACE_CAPACITY = 32
DEBUG_TRACE_RECORD_SIZE = 33
DIRTY_BITS = {"bg": 0x01, "obj": 0x02, "attributes": 0x04}
PHASE1_OWNERSHIP_REPLACEMENT_COMMAND = 1
PHASE1_OWNERSHIP_REPLACEMENT_CHECKPOINT = 1
PHASE1_RESTORE_YELLOW_COMMAND = 2
PHASE1_RESTORE_YELLOW_CHECKPOINT = 2
PHASE1_MAX_COMMAND_FRAMES = 120
PHASE1_DIAGNOSTIC_STACK_BYTES = 128
PHASE1_TRAP_ADDRESS = 0xFF80
PHASE1_TRAP_BYTES = 2
PHASE1_FIXED_WRAM_START = 0xC000
PHASE1_FIXED_WRAM_BYTES = 0x1000
PHASE1_HRAM_START = 0xFF80
PHASE1_HRAM_BYTES = 0x7F
PHASE1_CASE_ID = "RC-OWNERSHIP-REPLACEMENT"
PHASE1_CHECKPOINT = "phase1-ownership-replacement"
_CAPTURE_GUARD_REGISTERS = {
    "FF70": 0xFF70,
    "FF4F": 0xFF4F,
    "FF68": 0xFF68,
    "FF6A": 0xFF6A,
}

_UNSUPPORTED_BASELINE_SCALARS = {
    "wFullColorDebugLastRequestResult": 1,
    "wFullColorDebugCommitUnitID": 2,
    "wFullColorDebugWriterID": 2,
    "wFullColorDebugLastWriterID": 2,
    "wFullColorDebugLastResourceID": 2,
    "wFullColorDebugReconstructionItems": 2,
    "wFullColorDebugPresentationBarrierStatus": 1,
    "wFullColorDebugOAMFallbackKind": 1,
    "wFullColorDebugOAMFallbackObjectID": 2,
    "wFullColorDebugOAMFallbackTileID": 1,
    "wFullColorDebugTimingRowKey": 2,
    "wFullColorDebugAssertionCode": 2,
}
_RETAINED_PHASE1_DIAGNOSTIC_SCALARS = frozenset(
    {
        "wFullColorDebugLastRequestResult",
        "wFullColorDebugCommitUnitID",
        "wFullColorDebugWriterID",
        "wFullColorDebugLastWriterID",
        "wFullColorDebugLastResourceID",
    }
)

REQUIRED_DEBUG_SYMBOLS = (
    "wFullColorDebugStateStart",
    "wFullColorDebugMagic",
    "wFullColorDebugLayoutVersion",
    "wFullColorDebugActivationPhase",
    "wFullColorDebugOwner",
    "wFullColorDebugPhase",
    "wFullColorDebugGeneration",
    "wFullColorDebugLastRequestResult",
    "wFullColorDebugAdmissionOpen",
    "wFullColorDebugJobState",
    "wFullColorDebugJobGeneration",
    "wFullColorDebugCancellationReason",
    "wFullColorDebugDirtyFlags",
    "wFullColorDebugCommitUnitID",
    "wFullColorDebugWriterID",
    "wFullColorDebugCurrentROMBank",
    "wFullColorDebugCurrentWRAMBank",
    "wFullColorDebugCurrentVRAMBank",
    "wFullColorDebugLastWriterID",
    "wFullColorDebugLastResourceID",
    "wFullColorDebugReconstructionItems",
    "wFullColorDebugPresentationBarrierStatus",
    "wFullColorDebugOAMFallbackKind",
    "wFullColorDebugOAMFallbackObjectID",
    "wFullColorDebugOAMFallbackTileID",
    "wFullColorDebugTimingRowKey",
    "wFullColorDebugAssertionCode",
    "wFullColorDebugTraceStart",
    "wFullColorDebugTraceMagic",
    "wFullColorDebugTraceLayoutVersion",
    "wFullColorDebugTraceCapacity",
    "wFullColorDebugTraceCount",
    "wFullColorDebugTraceNextWrite",
    "wFullColorDebugTraceRecords",
    "wFullColorDebugTraceEnd",
    "wFullColorDebugStateEnd",
)

PHASE1_COMMAND_SYMBOLS = (
    "wFullColorDebugCommand",
    "wFullColorDebugCheckpoint",
)
PHASE1_DIAGNOSTIC_ROUTINES = {
    PHASE1_OWNERSHIP_REPLACEMENT_COMMAND: "RunPhase1OwnershipReplacementScenario",
    PHASE1_RESTORE_YELLOW_COMMAND: "RestoreYellowAfterPhase1Diagnostic",
}

PHASE1_TRACE_SYMBOLS = TraceSymbols(
    owners={
        0: Owner.RENDERER_YELLOW,
        1: Owner.RENDERER_FULL_COLOR_OVERWORLD,
    },
    phases={
        0: Phase.YELLOW_ACTIVE,
        1: Phase.HANDOFF_TO_OVERWORLD,
        2: Phase.OVERWORLD_RECONSTRUCTING,
        3: Phase.OVERWORLD_ACTIVE,
        4: Phase.OVERWORLD_OVERLAY,
        5: Phase.HANDOFF_TO_YELLOW,
    },
    job_states={
        0: JobState.PENDING,
        1: JobState.PREPARED,
        2: JobState.COMMITTING,
        3: JobState.COMPLETE,
        4: JobState.CANCELLED,
    },
    cancellations={
        0: CancellationReason.HANDOFF,
        1: CancellationReason.RESET,
        2: CancellationReason.SUPERSEDED,
        3: CancellationReason.STALE_GENERATION,
        0xFF: None,
    },
    writer_ids={1: "WR-RC-OWNERSHIP-REPLACEMENT"},
    commit_unit_ids={0: None, 1: "MU-RC-OWNERSHIP-REPLACEMENT"},
    job_ids={1: "JOB-OLD", 2: "JOB-REPLACEMENT"},
    request_ids={1: "REQ-RC-OWNERSHIP-REPLACEMENT"},
    resource_identities={1: "ownership_generation"},
)


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """One atomic ROM checkpoint and its independently decoded trace."""

    case_id: str
    rom_identity: str
    snapshot: SemanticSnapshot
    trace: WriterTrace

    def __post_init__(self) -> None:
        if self.case_id != PHASE1_CASE_ID:
            raise AssertionError(f"unexpected Phase 1 runtime case: {self.case_id}")
        if self.snapshot.scenario != self.case_id:
            raise AssertionError("runtime snapshot scenario does not match case identity")
        if self.snapshot.rom != self.rom_identity:
            raise AssertionError("runtime snapshot ROM identity does not match capture")
        if self.snapshot.evidence_kind != "RENDERER_RUNTIME":
            raise AssertionError("runtime snapshot has wrong evidence provenance")
        if self.snapshot.activation_phase != 1:
            raise AssertionError("Phase 1 runtime snapshot requires activation phase 1")


@dataclass(frozen=True, slots=True)
class BaselineDebugState:
    layout_version: int
    owner: int
    phase: int
    generation: int
    current_rom_bank: int
    current_wram_bank: int
    current_vram_bank: int
    assertion_code: int
    trace_capacity: int
    trace_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "assertion_code": self.assertion_code,
            "current_rom_bank": self.current_rom_bank,
            "current_vram_bank": self.current_vram_bank,
            "current_wram_bank": self.current_wram_bank,
            "generation": self.generation,
            "layout_version": self.layout_version,
            "owner": self.owner,
            "phase": self.phase,
            "trace_capacity": self.trace_capacity,
            "trace_count": self.trace_count,
        }


def require_debug_symbols(emulator: Emulator) -> None:
    missing = sorted(set(REQUIRED_DEBUG_SYMBOLS) - emulator.symbols.keys())
    if missing:
        raise AssertionError(f"debug ROM is missing symbols: {', '.join(missing)}")
    wrong_bank = sorted(
        symbol
        for symbol in REQUIRED_DEBUG_SYMBOLS
        if emulator.symbol_banks[symbol] != DEBUG_SRAM_BANK
    )
    if wrong_bank:
        raise AssertionError(
            "debug symbols are outside reserved SRAM bank 3: " + ", ".join(wrong_bank)
        )


def wait_until_debug_ready(emulator: Emulator, *, max_frames: int = 600) -> None:
    require_debug_symbols(emulator)
    for _ in range(max_frames + 1):
        if emulator.read_bytes("wFullColorDebugMagic", len(DEBUG_MAGIC)) == DEBUG_MAGIC:
            return
        emulator.tick()
    raise AssertionError(f"debug state did not initialize within {max_frames} frames")


def wait_until_phase1_capture_ready(emulator: Emulator) -> None:
    """Reach the first stable visual checkpoint after debug initialization."""

    wait_until_debug_ready(emulator)
    # Debug magic is published one DMA before hardware OAM catches its shadow.
    emulator.tick(3)


def read_baseline_debug_state(emulator: Emulator) -> BaselineDebugState:
    wait_until_debug_ready(emulator)

    decoded = read_writer_trace(emulator)

    state = BaselineDebugState(
        layout_version=emulator.read("wFullColorDebugLayoutVersion"),
        owner=emulator.read("wFullColorDebugOwner"),
        phase=emulator.read("wFullColorDebugPhase"),
        generation=_read_little_endian(emulator, "wFullColorDebugGeneration", 4),
        current_rom_bank=emulator.read("wFullColorDebugCurrentROMBank"),
        current_wram_bank=(emulator.read("wFullColorDebugCurrentWRAMBank") & 7) or 1,
        current_vram_bank=emulator.read("wFullColorDebugCurrentVRAMBank"),
        assertion_code=_read_little_endian(emulator, "wFullColorDebugAssertionCode", 2),
        trace_capacity=decoded.capacity,
        trace_count=len(decoded.entries),
    )
    expected = BaselineDebugState(
        layout_version=DEBUG_LAYOUT_VERSION,
        owner=0,
        phase=0,
        generation=1,
        current_rom_bank=1,
        current_wram_bank=1,
        current_vram_bank=0,
        assertion_code=0,
        trace_capacity=DEBUG_TRACE_CAPACITY,
        trace_count=0,
    )
    if state != expected:
        raise AssertionError(f"unexpected initialized debug state: {state!r}")
    return state


def _read_little_endian(emulator: Emulator, symbol: str, size: int) -> int:
    return int.from_bytes(emulator.read_bytes(symbol, size), "little")


def read_writer_trace(
    emulator: Emulator,
    *,
    symbols: TraceSymbols | None = None,
    permitted_writer_ids: Sequence[str] | None = None,
) -> WriterTrace:
    """Decode the bounded SRAM trace without changing the selected MBC bank."""

    trace_size = (
        emulator.symbols["wFullColorDebugTraceEnd"]
        - emulator.symbols["wFullColorDebugTraceStart"]
    )
    expected_trace_size = 11 + DEBUG_TRACE_CAPACITY * DEBUG_TRACE_RECORD_SIZE
    if trace_size != expected_trace_size:
        raise AssertionError(
            f"debug trace layout is {trace_size} bytes; expected {expected_trace_size}"
        )
    raw_trace = emulator.read_bytes("wFullColorDebugTraceStart", trace_size)
    selected_symbols = symbols or TraceSymbols(
        owners={0: Owner.RENDERER_YELLOW},
        phases={0: Phase.YELLOW_ACTIVE},
        job_states={0: JobState.PENDING},
        cancellations={0: None, 1: CancellationReason.HANDOFF},
        writer_ids={0: "WR-NONE"},
        commit_unit_ids={0: None},
        job_ids={0: "JOB-NONE"},
        request_ids={0: "REQ-NONE"},
    )
    return decode_writer_ring(
        raw_trace,
        selected_symbols,
        permitted_writer_ids=(
            tuple(permitted_writer_ids)
            if permitted_writer_ids is not None
            else ("WR-NONE",)
        ),
    )


def _rom_identity(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as rom_file:
        for chunk in iter(lambda: rom_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{path.name}:{digest.hexdigest()}"


def _stable_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _read_capture_guards(emulator: Emulator) -> dict[str, int]:
    return {
        "hLoadedROMBank": emulator.read("hLoadedROMBank"),
        **{
            name: emulator.read_memory(address, 1)[0]
            for name, address in _CAPTURE_GUARD_REGISTERS.items()
        },
    }


def capture_yellow_baseline_snapshot(
    emulator: Emulator,
    *,
    scenario: str,
    seed: int,
    checkpoint: str,
    retained_phase1_diagnostics: bool = False,
) -> SemanticSnapshot:
    """Capture one observational, schema-valid Yellow-owned CGB checkpoint."""
    wait_until_debug_ready(emulator)
    guards_before = _read_capture_guards(emulator)
    trace = read_writer_trace(
        emulator,
        symbols=PHASE1_TRACE_SYMBOLS if retained_phase1_diagnostics else None,
        permitted_writer_ids=("WR-RC-OWNERSHIP-REPLACEMENT",)
        if retained_phase1_diagnostics
        else None,
    )

    layout_version = emulator.read("wFullColorDebugLayoutVersion")
    owner_code = emulator.read("wFullColorDebugOwner")
    phase_code = emulator.read("wFullColorDebugPhase")
    if layout_version != DEBUG_LAYOUT_VERSION:
        raise AssertionError(f"unsupported debug layout version: {layout_version}")
    if (owner_code, phase_code) != (0, 0):
        raise AssertionError(
            "Yellow baseline requires debug owner/phase codes 0/0; "
            f"got {owner_code}/{phase_code}"
        )

    unsupported = {
        symbol: _read_little_endian(emulator, symbol, size)
        for symbol, size in _UNSUPPORTED_BASELINE_SCALARS.items()
    }
    nonzero = {
        symbol: value
        for symbol, value in unsupported.items()
        if value
        and not (
            retained_phase1_diagnostics
            and symbol in _RETAINED_PHASE1_DIAGNOSTIC_SCALARS
        )
    }
    if nonzero:
        details = ", ".join(
            f"{symbol}={value}" for symbol, value in sorted(nonzero.items())
        )
        raise AssertionError(
            "unsupported Yellow-baseline debug scalar is nonzero: " + details
        )
    job_state = emulator.read("wFullColorDebugJobState")
    cancellation = emulator.read("wFullColorDebugCancellationReason")
    if (job_state, cancellation) != (0xFF, 0xFF):
        raise AssertionError(
            "Yellow baseline requires an empty production job slot encoded as "
            f"0xff/0xff; got {job_state:#04x}/{cancellation:#04x}"
        )

    dirty_flags = emulator.read("wFullColorDebugDirtyFlags")
    known_dirty_mask = sum(DIRTY_BITS.values())
    if dirty_flags & ~known_dirty_mask:
        raise AssertionError(
            f"unknown debug dirty bits: {dirty_flags & ~known_dirty_mask:#04x}"
        )

    raw_wram_bank = emulator.read_memory(0xFF70, 1)[0] & 0x07
    banks = {
        "rom": emulator.read("hLoadedROMBank"),
        "wram": raw_wram_bank or 1,
        "vram": emulator.read_memory(0xFF4F, 1)[0] & 0x01,
    }
    traced_writer_ids = _stable_unique([entry.writer_id for entry in trace.entries])
    snapshot = SemanticSnapshot.from_dict(
        {
            "schema": "full-color-contract-v1",
            "rom": _rom_identity(Path(emulator.rom)),
            "scenario": scenario,
            "seed": seed,
            "checkpoint": checkpoint,
            "frame": emulator.frame,
            "evidence_kind": "YELLOW_BASELINE",
            "activation_phase": 0,
            "owner": Owner.RENDERER_YELLOW.value,
            "phase": Phase.YELLOW_ACTIVE.value,
            "generation": _read_little_endian(emulator, "wFullColorDebugGeneration", 4),
            "request_result": None,
            "job": None,
            "writer_id": None,
            "traced_writer_ids": list(traced_writer_ids),
            "banks": banks,
            "dirty": {
                name: bool(dirty_flags & mask) for name, mask in DIRTY_BITS.items()
            },
            "queued_jobs": [],
            "reconstruction": {
                "required_items": sorted(REQUIRED_RECONSTRUCTION_ITEMS),
                "completed_items": [],
                "item_provenance": {},
                "poisoned_items": [],
                "unknown_prior_state": False,
                "presentation_barrier_count": 0,
            },
            "bg_tile_ids": emulator.read_vram_bank(0, 0x9800, 0x800).hex(),
            "bg_attributes": emulator.read_vram_bank(1, 0x9800, 0x800).hex(),
            "bg_palettes": emulator.read_palette_ram().hex(),
            "obj_palettes": emulator.read_palette_ram(object_palettes=True).hex(),
            "shadow_oam": emulator.read_bytes("wShadowOAM", 160).hex(),
            "hardware_oam": emulator.read_memory(0xFE00, 160).hex(),
            "map_id": f"${emulator.read('wCurMap'):02X}",
            "tileset_id": f"${emulator.read('wCurMapTileset'):02X}",
            "transfer_state": None,
            "overlay_request": None,
            "oam_fallback": {
                "occurred": False,
                "fallback_kind": None,
                "object_id": None,
                "final_tile_id": None,
                "identity": None,
                "generation": None,
                "writer_id": None,
                "palette": None,
                "before_attributes": 0,
                "after_attributes": 0,
            },
            "timing_row_key": None,
            "timing_row": None,
            "artifacts": {},
        }
    )
    guards_after = _read_capture_guards(emulator)
    if guards_after != guards_before:
        changed = ", ".join(
            f"{name}={guards_before[name]:#04x}->{guards_after[name]:#04x}"
            for name in guards_before
            if guards_after[name] != guards_before[name]
        )
        raise AssertionError(
            "semantic snapshot capture changed guard state: " + changed
        )
    return snapshot


def run_debug_command(
    emulator: Emulator,
    *,
    command: int = PHASE1_OWNERSHIP_REPLACEMENT_COMMAND,
    checkpoint: int = PHASE1_OWNERSHIP_REPLACEMENT_CHECKPOINT,
    prior_checkpoint: int = 0,
    max_frames: int = PHASE1_MAX_COMMAND_FRAMES,
) -> None:
    """Call one unrooted debug routine through a controlled emulator seam."""

    wait_until_debug_ready(emulator)
    routine = PHASE1_DIAGNOSTIC_ROUTINES.get(command)
    if routine is None:
        raise AssertionError(f"unsupported Phase 1 diagnostic command: {command}")
    missing = sorted(
        (set(PHASE1_COMMAND_SYMBOLS) | {routine}) - emulator.symbols.keys()
    )
    if missing:
        raise AssertionError(
            "debug ROM is missing Phase 1 command symbols: " + ", ".join(missing)
        )
    wrong_bank = sorted(
        symbol
        for symbol in PHASE1_COMMAND_SYMBOLS
        if emulator.symbol_banks[symbol] != DEBUG_SRAM_BANK
    )
    if wrong_bank:
        raise AssertionError(
            "Phase 1 command symbols are outside reserved SRAM bank 3: "
            + ", ".join(wrong_bank)
        )
    routine_bank = emulator.symbol_banks[routine]
    if routine_bank == 0:
        raise AssertionError("Phase 1 diagnostic routine must be banked and unrooted")
    if emulator.read("wFullColorDebugLayoutVersion") != DEBUG_LAYOUT_VERSION:
        raise AssertionError("Phase 1 command requires debug layout version 2")
    if emulator.read("wFullColorDebugActivationPhase") != 1:
        raise AssertionError("Phase 1 command requires activation phase 1")
    actual_prior_checkpoint = emulator.read("wFullColorDebugCheckpoint")
    if actual_prior_checkpoint != prior_checkpoint:
        raise AssertionError(
            "Phase 1 command requires checkpoint "
            f"{prior_checkpoint}; got {actual_prior_checkpoint}"
        )
    register_file = emulator.pyboy.register_file
    registers = {
        name: getattr(register_file, name)
        for name in ("A", "F", "B", "C", "D", "E", "HL", "SP", "PC")
    }
    memory = emulator.pyboy.memory
    loaded_bank_address = emulator.symbols["hLoadedROMBank"]
    stack_top = emulator.symbols.get("wStack")
    if stack_top is None:
        raise AssertionError("Phase 1 diagnostic requires the real wStack symbol")
    if emulator.symbol_banks.get("wStack") != 1 or not 0xD000 <= stack_top < 0xE000:
        raise AssertionError(
            "Phase 1 diagnostic requires wStack in switchable WRAM bank 1"
        )
    stack_pointer = stack_top - 2
    stack_start = stack_top - PHASE1_DIAGNOSTIC_STACK_BYTES
    if stack_start < 0xD000 or stack_pointer + 1 >= stack_top:
        raise AssertionError(
            "Phase 1 diagnostic wStack lacks the required 128-byte headroom"
        )
    loaded_bank = memory[loaded_bank_address]
    selected_wram_bank = memory[0xFF70]
    interrupt_enable = memory[0xFFFF]
    interrupt_flags = memory[0xFF0F]
    return_trap = 0x0100
    stack_before = emulator.read_memory(
        stack_start, PHASE1_DIAGNOSTIC_STACK_BYTES, bank=1
    )
    shadow_oam_start = emulator.symbols.get("wShadowOAM")
    shadow_oam_bytes = 160
    fixed_wram_end = PHASE1_FIXED_WRAM_START + PHASE1_FIXED_WRAM_BYTES
    if (
        shadow_oam_start is None
        or emulator.symbol_banks.get("wShadowOAM") != 0
        or not PHASE1_FIXED_WRAM_START
        <= shadow_oam_start
        <= fixed_wram_end - shadow_oam_bytes
    ):
        raise AssertionError(
            "Phase 1 diagnostic requires the observed wShadowOAM WRAM0 range"
        )
    # wShadowOAM is the sole fixed-WRAM exclusion: semantic evidence observes it
    # directly, including the patchable negative-test mutation. Everything else
    # in fixed WRAM must remain byte-identical across the host seam.
    fixed_wram_regions = (
        (PHASE1_FIXED_WRAM_START, shadow_oam_start - PHASE1_FIXED_WRAM_START),
        (
            shadow_oam_start + shadow_oam_bytes,
            fixed_wram_end - shadow_oam_start - shadow_oam_bytes,
        ),
    )
    fixed_wram_before = tuple(
        emulator.read_memory(address, size)
        for address, size in fixed_wram_regions
    )
    hram_before = emulator.read_memory(PHASE1_HRAM_START, PHASE1_HRAM_BYTES)
    trap_offset = PHASE1_TRAP_ADDRESS - PHASE1_HRAM_START
    trap_before = hram_before[trap_offset : trap_offset + PHASE1_TRAP_BYTES]
    returned = False

    def stop(_: object) -> None:
        nonlocal returned
        returned = True
        memory[0xFFFF] = 0
        memory[PHASE1_TRAP_ADDRESS] = 0x18
        memory[PHASE1_TRAP_ADDRESS + 1] = 0xFE
        register_file.PC = PHASE1_TRAP_ADDRESS

    hook_registered = False
    diagnostic_pc = 0
    diagnostic_sp = 0
    try:
        memory[0xFF70] = 1
        memory[stack_pointer] = return_trap & 0xFF
        memory[stack_pointer + 1] = return_trap >> 8
        memory[0xFFFF] = 0
        memory[0x2000] = routine_bank & 0xFF
        memory[0x3000] = routine_bank >> 8
        memory[loaded_bank_address] = routine_bank
        register_file.SP = stack_pointer
        register_file.PC = emulator.symbols[routine]
        emulator.pyboy.hook_register(0, return_trap, stop, None)
        hook_registered = True
        emulator.pyboy.tick(1, render=False, sound=False)
    finally:
        diagnostic_pc = register_file.PC
        diagnostic_sp = register_file.SP
        if hook_registered:
            emulator.pyboy.hook_deregister(0, return_trap)
        memory[0xFF70] = 1
        for offset, value in enumerate(stack_before):
            memory[1, stack_start + offset] = value
        for offset, value in enumerate(trap_before):
            memory[PHASE1_TRAP_ADDRESS + offset] = value
        memory[0x2000] = loaded_bank & 0xFF
        memory[0x3000] = loaded_bank >> 8
        memory[loaded_bank_address] = loaded_bank
        memory[0xFF70] = selected_wram_bank
        memory[0xFFFF] = interrupt_enable
        memory[0xFF0F] = interrupt_flags
        for name, value in registers.items():
            setattr(register_file, name, value)
    if not returned:
        raise AssertionError(
            f"Phase 1 diagnostic did not return within {max_frames} frames "
            f"(PC={diagnostic_pc:#06x}, SP={diagnostic_sp:#06x})"
        )
    unchanged_regions = [
        ("fixed WRAM0", address, expected)
        for (address, _), expected in zip(
            fixed_wram_regions, fixed_wram_before, strict=True
        )
    ]
    unchanged_regions.append(("HRAM", PHASE1_HRAM_START, hram_before))
    for label, address, expected in unchanged_regions:
        actual_memory = emulator.read_memory(address, len(expected))
        if actual_memory != expected:
            offset = next(
                index
                for index, values in enumerate(
                    zip(expected, actual_memory, strict=True)
                )
                if values[0] != values[1]
            )
            raise AssertionError(
                f"Phase 1 diagnostic changed unrelated {label} at "
                f"{address + offset:#06x}: "
                f"{expected[offset]:#04x}->{actual_memory[offset]:#04x}"
            )
    actual = emulator.read("wFullColorDebugCheckpoint")
    if actual != checkpoint:
        raise AssertionError(
            f"Phase 1 diagnostic reached checkpoint {actual}; expected {checkpoint}"
        )


def restore_phase1_to_yellow(
    emulator: Emulator,
    *,
    scenario: str = "phase1-baseline",
    seed: int = 0,
    checkpoint: str = "after-phase1-restore",
) -> SemanticSnapshot:
    """Run the shared production handoff back to Yellow and capture its state."""

    run_debug_command(
        emulator,
        command=PHASE1_RESTORE_YELLOW_COMMAND,
        checkpoint=PHASE1_RESTORE_YELLOW_CHECKPOINT,
        prior_checkpoint=PHASE1_OWNERSHIP_REPLACEMENT_CHECKPOINT,
    )
    return capture_yellow_baseline_snapshot(
        emulator,
        scenario=scenario,
        seed=seed,
        checkpoint=checkpoint,
        retained_phase1_diagnostics=True,
    )


def _runtime_reconstruction() -> dict[str, object]:
    items = sorted(REQUIRED_RECONSTRUCTION_ITEMS)
    return {
        "required_items": items,
        "completed_items": [],
        "item_provenance": {},
        "poisoned_items": [],
        "unknown_prior_state": False,
        "presentation_barrier_count": 0,
    }


def capture_phase1_runtime_observation(
    emulator: Emulator,
    case: ConformanceCase,
    *,
    execute_command: bool = True,
    settle_debug_ready: bool = True,
) -> RuntimeObservation:
    """Capture the sole activated Phase 1 case from one real ROM checkpoint."""

    if case.case_id != PHASE1_CASE_ID:
        raise AssertionError(
            f"Phase 1 runtime capture only supports {PHASE1_CASE_ID}; got {case.case_id}"
        )
    if execute_command and settle_debug_ready:
        wait_until_phase1_capture_ready(emulator)
    else:
        wait_until_debug_ready(emulator)
    guards_before = _read_capture_guards(emulator)
    if execute_command:
        run_debug_command(emulator)
    elif emulator.read("wFullColorDebugCheckpoint") != PHASE1_OWNERSHIP_REPLACEMENT_CHECKPOINT:
        raise AssertionError("Phase 1 runtime checkpoint has not been reached")

    layout_version = emulator.read("wFullColorDebugLayoutVersion")
    activation_phase = emulator.read("wFullColorDebugActivationPhase")
    if layout_version != DEBUG_LAYOUT_VERSION:
        raise AssertionError(f"unsupported debug layout version: {layout_version}")
    if activation_phase != 1:
        raise AssertionError(
            f"Phase 1 runtime carrier has wrong activation phase: {activation_phase}"
        )
    trace = read_writer_trace(
        emulator,
        symbols=PHASE1_TRACE_SYMBOLS,
        permitted_writer_ids=("WR-RC-OWNERSHIP-REPLACEMENT",),
    )
    expected_generation = case.inputs["generation"]
    generation = _read_little_endian(emulator, "wFullColorDebugGeneration", 4)
    owner_code = emulator.read("wFullColorDebugOwner")
    phase_code = emulator.read("wFullColorDebugPhase")
    if owner_code != 1:
        raise AssertionError(f"Phase 1 runtime carrier has wrong owner code: {owner_code}")
    if phase_code != 3:
        raise AssertionError(f"Phase 1 runtime carrier has wrong phase code: {phase_code}")
    if generation != expected_generation:
        raise AssertionError(
            f"Phase 1 runtime carrier has wrong generation: {generation}; "
            f"expected {expected_generation}"
        )
    exact_scalars = {
        "wFullColorDebugLastRequestResult": 0,
        "wFullColorDebugAdmissionOpen": 1,
        "wFullColorDebugJobState": 3,
        "wFullColorDebugCancellationReason": 0xFF,
        "wFullColorDebugCommitUnitID": 1,
        "wFullColorDebugWriterID": 1,
        "wFullColorDebugLastWriterID": 1,
        "wFullColorDebugLastResourceID": 1,
    }
    observed_scalars: dict[str, int] = {}
    for symbol, expected in exact_scalars.items():
        size = 2 if symbol in {
            "wFullColorDebugCommitUnitID",
            "wFullColorDebugWriterID",
            "wFullColorDebugLastWriterID",
            "wFullColorDebugLastResourceID",
        } else 1
        actual = _read_little_endian(emulator, symbol, size)
        observed_scalars[symbol] = actual
        if actual != expected:
            raise AssertionError(
                f"Phase 1 runtime carrier {symbol}={actual}; expected {expected}"
            )
    assertion_code = _read_little_endian(
        emulator, "wFullColorDebugAssertionCode", 2
    )
    if assertion_code:
        raise AssertionError(
            f"Phase 1 runtime carrier reports assertion code {assertion_code}"
        )
    dirty_flags = emulator.read("wFullColorDebugDirtyFlags")
    known_dirty_mask = sum(DIRTY_BITS.values())
    if dirty_flags & ~known_dirty_mask:
        raise AssertionError(
            f"unknown debug dirty bits: {dirty_flags & ~known_dirty_mask:#04x}"
        )
    rom_identity = _rom_identity(Path(emulator.rom))
    writer_id = "WR-RC-OWNERSHIP-REPLACEMENT"
    raw_wram_bank = emulator.read_memory(0xFF70, 1)[0] & 0x07
    snapshot = SemanticSnapshot.from_dict(
        {
            "schema": "full-color-contract-v1",
            "rom": rom_identity,
            "scenario": case.case_id,
            "seed": 0,
            "checkpoint": PHASE1_CHECKPOINT,
            "frame": emulator.frame,
            "evidence_kind": "RENDERER_RUNTIME",
            "activation_phase": activation_phase,
            "owner": Owner.RENDERER_FULL_COLOR_OVERWORLD.value,
            "phase": Phase.OVERWORLD_ACTIVE.value,
            "generation": generation,
            "request_result": {
                0: RequestResult.ACCEPTED.value,
            }[observed_scalars["wFullColorDebugLastRequestResult"]],
            "job": {
                "job_id": "JOB-REPLACEMENT",
                "request_ids": ["REQ-RC-OWNERSHIP-REPLACEMENT"],
                "resources": ["ownership_generation"],
                "state": {
                    3: JobState.COMPLETE.value,
                }[observed_scalars["wFullColorDebugJobState"]],
                "cancellation_reason": None,
                "commit_unit_id": "MU-RC-OWNERSHIP-REPLACEMENT",
                "owner": Owner.RENDERER_FULL_COLOR_OVERWORLD.value,
                "generation": _read_little_endian(
                    emulator, "wFullColorDebugJobGeneration", 4
                ),
            },
            "writer_id": writer_id,
            "traced_writer_ids": list(
                _stable_unique([entry.writer_id for entry in trace.entries])
            ),
            "banks": {
                "rom": emulator.read("hLoadedROMBank"),
                "wram": raw_wram_bank or 1,
                "vram": emulator.read_memory(0xFF4F, 1)[0] & 1,
            },
            "dirty": {
                name: bool(dirty_flags & mask) for name, mask in DIRTY_BITS.items()
            },
            "queued_jobs": [],
            "reconstruction": _runtime_reconstruction(),
            "bg_tile_ids": emulator.read_vram_bank(0, 0x9800, 0x800).hex(),
            "bg_attributes": emulator.read_vram_bank(1, 0x9800, 0x800).hex(),
            "bg_palettes": emulator.read_palette_ram().hex(),
            "obj_palettes": emulator.read_palette_ram(object_palettes=True).hex(),
            "shadow_oam": emulator.read_bytes("wShadowOAM", 160).hex(),
            "hardware_oam": emulator.read_memory(0xFE00, 160).hex(),
            "map_id": f"${emulator.read('wCurMap'):02X}",
            "tileset_id": f"${emulator.read('wCurMapTileset'):02X}",
            "transfer_state": None,
            "overlay_request": None,
            "oam_fallback": {
                "occurred": False,
                "fallback_kind": None,
                "object_id": None,
                "final_tile_id": None,
                "identity": None,
                "generation": None,
                "writer_id": None,
                "palette": None,
                "before_attributes": 0,
                "after_attributes": 0,
            },
            "timing_row_key": None,
            "timing_row": None,
            "artifacts": {},
        }
    )
    guards_after = _read_capture_guards(emulator)
    if guards_after != guards_before:
        changed = ", ".join(
            f"{name}={guards_before[name]:#04x}->{guards_after[name]:#04x}"
            for name in guards_before
            if guards_after[name] != guards_before[name]
        )
        raise AssertionError(
            "Phase 1 command or runtime observation changed guard state: " + changed
        )
    return RuntimeObservation(case.case_id, rom_identity, snapshot, trace)


def run_smoke(
    root: Path,
    *,
    snapshot_output: Path | None = None,
    diagnostics_output: Path | None = None,
) -> dict[str, object]:
    if diagnostics_output is None:
        diagnostics_output = root / "test-results" / "full-color-debug-observability"
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=diagnostics_output,
        cgb=True,
    )
    try:
        state = read_baseline_debug_state(emulator)
        first_snapshot = capture_yellow_baseline_snapshot(
            emulator,
            scenario="gate-0-baseline",
            seed=0,
            checkpoint="debug-ready",
        )
        second_snapshot = capture_yellow_baseline_snapshot(
            emulator,
            scenario="gate-0-baseline",
            seed=0,
            checkpoint="debug-ready",
        )
    finally:
        emulator.close()

    snapshot_json = first_snapshot.to_json()
    if second_snapshot.to_json() != snapshot_json:
        raise AssertionError(
            "two semantic snapshots captured without ticking are not byte-identical"
        )
    if SemanticSnapshot.from_json(snapshot_json) != first_snapshot:
        raise AssertionError("semantic snapshot JSON did not round-trip exactly")
    snapshot_bytes = snapshot_json.encode("utf-8")
    if snapshot_output is not None:
        _write_text(snapshot_output, snapshot_json)

    return {
        "schema": "full-color-debug-observability-smoke-v1",
        "required_symbols": len(REQUIRED_DEBUG_SYMBOLS),
        "snapshot_bytes": len(snapshot_bytes),
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "state": state.to_dict(),
        "trace_layout_version": TRACE_LAYOUT_VERSION,
    }


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _write_text(
        path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    )


def _new_smoke_attempt(results_root: Path) -> Path:
    results_root.mkdir(parents=True, exist_ok=True)
    for number in range(1, 1_000_000):
        attempt = results_root / f"attempt-{number:04d}"
        try:
            attempt.mkdir()
        except FileExistsError:
            continue
        return attempt
    raise RuntimeError("smoke results root contains too many attempts")


def run_retained_smoke(
    root: Path,
    results_root: Path,
    *,
    reporter: RunnerReporter = NULL_REPORTER,
) -> dict[str, object]:
    """Run smoke into a fresh attempt, retaining both successes and failures."""
    root = root.resolve()
    attempt = _new_smoke_attempt(results_root.resolve())
    reporter.attempt(attempt)
    started = reporter.running("observability")
    status: dict[str, object] = {
        "schema": "full-color-debug-observability-attempt-v1",
        "attempt": attempt.name,
        "status": "running",
    }
    _write_json(attempt / "summary.json", status)
    try:
        report = run_smoke(
            root,
            snapshot_output=attempt / "semantic-snapshot.json",
            diagnostics_output=attempt / "diagnostics",
        )
        _write_json(attempt / "observability.json", report)
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        _write_json(attempt / "summary.json", status)
        reporter.failed("observability", exc, attempt / "summary.json")
        raise
    status["status"] = "passed"
    status["report"] = "observability.json"
    status["snapshot"] = "semantic-snapshot.json"
    _write_json(attempt / "summary.json", status)
    reporter.passed("observability", started)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Boot the debug ROM and validate Gate 0 observability"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository containing pokeyellow_debug.gbc and .sym",
    )
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        help="optional path for the canonical debug-ready semantic snapshot",
    )
    parser.add_argument(
        "--diagnostics-output",
        type=Path,
        help="directory for emulator diagnostics (defaults below the repository)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        help="retain this smoke invocation below a fresh attempt directory",
    )
    add_output_argument(parser)
    args = parser.parse_args(argv)
    if args.results is not None and (
        args.snapshot_output is not None or args.diagnostics_output is not None
    ):
        parser.error("--results cannot be combined with explicit output paths")
    reporter = RunnerReporter("smoke", args.output)
    summary_path: Path | None = None
    try:
        if args.results is not None:
            report = run_retained_smoke(
                args.root, args.results, reporter=reporter
            )
            summary_path = (
                args.results.resolve() / str(report["attempt"]) / "summary.json"
            )
        else:
            started = reporter.running("observability")
            report = run_smoke(
                args.root,
                snapshot_output=args.snapshot_output,
                diagnostics_output=args.diagnostics_output,
            )
            reporter.passed("observability", started)
    except Exception as exc:
        reporter.failed("observability", exc, summary_path or args.results)
        if reporter.mode is OutputMode.JSON:
            if summary_path is None and reporter.attempt_path is not None:
                summary_path = reporter.attempt_path / "summary.json"
            failed_report: dict[str, object] = {
                "status": "failed",
                "error": str(exc),
            }
            if summary_path is not None and summary_path.is_file():
                try:
                    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        failed_report = loaded
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    pass
            reporter.finish(failed_report, summary_path)
        return 1
    reporter.finish(report, summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
