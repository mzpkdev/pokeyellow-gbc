from __future__ import annotations

import pytest

from tools.rom_tests.full_color.runtime_observability import (
    DEBUG_TRACE_CAPACITY,
    DEBUG_TRACE_RECORD_SIZE,
    REQUIRED_DEBUG_SYMBOLS,
    require_debug_symbols,
)


class FakeEmulator:
    def __init__(self) -> None:
        self.symbols = {
            symbol: 0xA000 + index
            for index, symbol in enumerate(REQUIRED_DEBUG_SYMBOLS)
        }
        self.symbol_banks = {symbol: 3 for symbol in REQUIRED_DEBUG_SYMBOLS}


def test_required_debug_symbol_contract_is_complete_and_bounded() -> None:
    required = set(REQUIRED_DEBUG_SYMBOLS)
    assert len(required) == len(REQUIRED_DEBUG_SYMBOLS)
    assert {
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
        "wFullColorDebugTimingRowKey",
        "wFullColorDebugAssertionCode",
        "wFullColorDebugTraceStart",
        "wFullColorDebugTraceEnd",
    } <= required
    assert DEBUG_TRACE_CAPACITY == 32
    assert DEBUG_TRACE_RECORD_SIZE == 33


def test_debug_symbols_must_all_resolve_in_reserved_bank() -> None:
    emulator = FakeEmulator()
    require_debug_symbols(emulator)  # type: ignore[arg-type]

    del emulator.symbols["wFullColorDebugOwner"]
    with pytest.raises(AssertionError, match="missing symbols"):
        require_debug_symbols(emulator)  # type: ignore[arg-type]

    emulator = FakeEmulator()
    emulator.symbol_banks["wFullColorDebugOwner"] = 2
    with pytest.raises(AssertionError, match="outside reserved SRAM bank 3"):
        require_debug_symbols(emulator)  # type: ignore[arg-type]
