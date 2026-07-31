"""Observational reader and CI smoke check for Gate 0 debug-ROM state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Sequence

from tools.rom_tests.emulator import Emulator

from .enums import CancellationReason, JobState, Owner, Phase
from .snapshots import REQUIRED_RECONSTRUCTION_ITEMS, SemanticSnapshot
from .trace import (
    TRACE_LAYOUT_VERSION,
    TraceSymbols,
    WriterTrace,
    decode_writer_ring,
)


DEBUG_MAGIC = b"FCG0"
DEBUG_LAYOUT_VERSION = 1
DEBUG_SRAM_BANK = 3
DEBUG_TRACE_CAPACITY = 32
DEBUG_TRACE_RECORD_SIZE = 33
DIRTY_BITS = {"bg": 0x01, "obj": 0x02, "attributes": 0x04}
_CAPTURE_GUARD_REGISTERS = {
    "FF70": 0xFF70,
    "FF4F": 0xFF4F,
    "FF68": 0xFF68,
    "FF6A": 0xFF6A,
}

_UNSUPPORTED_BASELINE_SCALARS = {
    "wFullColorDebugLastRequestResult": 1,
    "wFullColorDebugJobState": 1,
    "wFullColorDebugCancellationReason": 1,
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

    decoded = _read_writer_trace(emulator)

    state = BaselineDebugState(
        layout_version=emulator.read("wFullColorDebugLayoutVersion"),
        owner=emulator.read("wFullColorDebugOwner"),
        phase=emulator.read("wFullColorDebugPhase"),
        generation=_read_little_endian(emulator, "wFullColorDebugGeneration", 4),
        current_rom_bank=emulator.read("wFullColorDebugCurrentROMBank"),
        current_wram_bank=emulator.read("wFullColorDebugCurrentWRAMBank"),
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


def _read_writer_trace(emulator: Emulator) -> WriterTrace:
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
    return decode_writer_ring(
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
) -> SemanticSnapshot:
    """Capture one observational, schema-valid Yellow-owned CGB checkpoint."""
    wait_until_debug_ready(emulator)
    guards_before = _read_capture_guards(emulator)
    trace = _read_writer_trace(emulator)

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
    nonzero = {symbol: value for symbol, value in unsupported.items() if value}
    if nonzero:
        details = ", ".join(
            f"{symbol}={value}" for symbol, value in sorted(nonzero.items())
        )
        raise AssertionError(
            "unsupported Yellow-baseline debug scalar is nonzero: " + details
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


def run_smoke(
    root: Path,
    *,
    snapshot_output: Path | None = None,
) -> dict[str, object]:
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=root / "test-results" / "full-color-debug-observability",
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
        snapshot_output.parent.mkdir(parents=True, exist_ok=True)
        snapshot_output.write_text(snapshot_json, encoding="utf-8")

    return {
        "schema": "full-color-debug-observability-smoke-v1",
        "required_symbols": len(REQUIRED_DEBUG_SYMBOLS),
        "snapshot_bytes": len(snapshot_bytes),
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
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
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        help="optional path for the canonical debug-ready semantic snapshot",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run_smoke(args.root, snapshot_output=args.snapshot_output),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
