"""Observational reader and CI smoke check for Gate 0 debug-ROM state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence

from tools.rom_tests.emulator import Emulator

from .enums import CancellationReason, JobState, Owner, Phase
from .trace import TRACE_LAYOUT_VERSION, TraceSymbols, decode_writer_ring


DEBUG_MAGIC = b"FCG0"
DEBUG_LAYOUT_VERSION = 1
DEBUG_SRAM_BANK = 3
DEBUG_TRACE_CAPACITY = 32
DEBUG_TRACE_RECORD_SIZE = 33

REQUIRED_DEBUG_SYMBOLS = (
    "wFullColorDebugStateStart",
    "wFullColorDebugMagic",
    "wFullColorDebugLayoutVersion",
    "wFullColorDebugOwner",
    "wFullColorDebugPhase",
    "wFullColorDebugGeneration",
    "wFullColorDebugLastRequestResult",
    "wFullColorDebugJobState",
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


def read_baseline_debug_state(emulator: Emulator) -> BaselineDebugState:
    wait_until_debug_ready(emulator)

    def little_endian(symbol: str, size: int) -> int:
        return int.from_bytes(emulator.read_bytes(symbol, size), "little")

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
    decoded = decode_writer_ring(
        raw_trace,
        TraceSymbols(
            owners={0: Owner.RENDERER_YELLOW},
            phases={0: Phase.YELLOW_ACTIVE},
            job_states={0: JobState.PENDING},
            cancellations={0: None, 1: CancellationReason.HANDOFF},
            writer_ids={0: "WR-NONE"},
            commit_unit_ids={0: None},
            job_ids={0: "JOB-NONE"},
            request_ids={0: "REQ-NONE"},
        ),
        permitted_writer_ids=("WR-NONE",),
    )
    state = BaselineDebugState(
        layout_version=emulator.read("wFullColorDebugLayoutVersion"),
        owner=emulator.read("wFullColorDebugOwner"),
        phase=emulator.read("wFullColorDebugPhase"),
        generation=little_endian("wFullColorDebugGeneration", 4),
        current_rom_bank=emulator.read("wFullColorDebugCurrentROMBank"),
        current_wram_bank=emulator.read("wFullColorDebugCurrentWRAMBank"),
        current_vram_bank=emulator.read("wFullColorDebugCurrentVRAMBank"),
        assertion_code=little_endian("wFullColorDebugAssertionCode", 2),
        trace_capacity=decoded.capacity,
        trace_count=len(decoded.entries),
    )
    if state != BaselineDebugState(
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
    ):
        raise AssertionError(f"unexpected initialized debug state: {state!r}")
    return state


def run_smoke(root: Path) -> dict[str, object]:
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=root / "test-results" / "full-color-debug-observability",
        cgb=True,
    )
    try:
        state = read_baseline_debug_state(emulator)
    finally:
        emulator.close()
    return {
        "schema": "full-color-debug-observability-smoke-v1",
        "required_symbols": len(REQUIRED_DEBUG_SYMBOLS),
        "state": state.to_dict(),
        "trace_layout_version": TRACE_LAYOUT_VERSION,
    }


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
    args = parser.parse_args(argv)
    print(json.dumps(run_smoke(args.root), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
