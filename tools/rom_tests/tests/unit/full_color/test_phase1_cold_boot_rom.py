"""Real-ROM regressions for Phase 1 cold and soft reset ownership setup."""

from __future__ import annotations

import os
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


RSVBK = 0xFF70
RENDERER_WRAM_BANK = 2


def _numeric_symbols(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            values[match.group(2)] = int(match.group(1), 16)
    return values


@pytest.fixture
def debug_rom(request: pytest.FixtureRequest) -> tuple[Emulator, dict[str, int]]:
    rom_path = Path(
        os.environ.get("ROM_TEST_ROM", REPOSITORY_ROOT / "pokeyellow_debug.gbc")
    )
    symbols_path = Path(
        os.environ.get(
            "ROM_TEST_SYMBOLS", REPOSITORY_ROOT / "pokeyellow_debug.sym"
        )
    )
    emulator = Emulator(
        rom=rom_path,
        symbols=symbols_path,
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    required = {
        "Init",
        "DMARoutine",
        "DMARoutine.End",
        "SoftReset",
        "hDMARoutine",
        "hSoftReset",
        "wRendererOwner",
        "wRendererPhase",
        "wRendererGeneration",
        "wRendererAdmissionOpen",
        "wRendererJobState",
        "wRendererJobGeneration",
        "wRendererJobCancellationReason",
    }
    missing = sorted(required - emulator.symbols.keys())
    assert not missing, "debug ROM is missing reset symbols: " + ", ".join(missing)
    try:
        yield emulator, _numeric_symbols(symbols_path)
    finally:
        emulator.close()


def _read_generation(emulator: Emulator) -> int:
    return int.from_bytes(emulator.read_bytes("wRendererGeneration", 4), "little")


def _write_renderer_state(
    emulator: Emulator, symbol: str, value: int, size: int = 1
) -> None:
    prior = emulator.pyboy.memory[RSVBK]
    emulator.pyboy.memory[RSVBK] = RENDERER_WRAM_BANK
    try:
        address = emulator.symbols[symbol]
        for offset, byte in enumerate(value.to_bytes(size, "little")):
            emulator.pyboy.memory[address + offset] = byte
    finally:
        emulator.pyboy.memory[RSVBK] = prior


def _wait_for_generation(
    emulator: Emulator, expected: int, *, max_frames: int = 180
) -> None:
    for _ in range(max_frames):
        emulator.tick()
        if _read_generation(emulator) == expected:
            return
    raise AssertionError(f"ownership generation did not reach {expected}")


def test_cold_boot_rejects_hostile_soft_reset_marker(
    debug_rom: tuple[Emulator, dict[str, int]],
) -> None:
    emulator, constants = debug_rom
    dma_start = emulator.symbols["DMARoutine"]
    dma_end = emulator.symbols["DMARoutine.End"]
    dma_bank = emulator.symbol_banks["DMARoutine"]
    hram_start = emulator.symbols["hDMARoutine"]
    for offset in range(dma_end - dma_start):
        emulator.pyboy.memory[hram_start + offset] = emulator.pyboy.memory[
            dma_bank, dma_start + offset
        ]
    emulator.pyboy.memory[emulator.symbols["hSoftReset"]] = 1

    _wait_for_generation(emulator, 1)

    assert emulator.read("wRendererOwner") == constants["RENDERER_YELLOW"]
    assert emulator.read("wRendererPhase") == constants["YELLOW_ACTIVE"]
    assert emulator.read("wRendererAdmissionOpen") == 1


def test_genuine_soft_reset_preserves_fresh_generation_through_init(
    debug_rom: tuple[Emulator, dict[str, int]],
) -> None:
    emulator, constants = debug_rom
    _wait_for_generation(emulator, 1)
    for _ in range(180):
        if emulator.pyboy.memory[emulator.symbols["hSoftReset"]] == 16:
            break
        emulator.tick()
    else:
        raise AssertionError(
            "cold boot did not finish initializing HRAM: "
            f"hSoftReset={emulator.pyboy.memory[emulator.symbols['hSoftReset']]}, "
            f"pc={emulator.pyboy.register_file.PC:#06x}"
        )

    old_generation = 41
    _write_renderer_state(emulator, "wRendererGeneration", old_generation, 4)
    _write_renderer_state(
        emulator, "wRendererOwner", constants["RENDERER_FULL_COLOR_OVERWORLD"]
    )
    _write_renderer_state(emulator, "wRendererPhase", constants["OVERWORLD_ACTIVE"])
    _write_renderer_state(emulator, "wRendererAdmissionOpen", 1)
    _write_renderer_state(emulator, "wRendererJobState", constants["PREPARED"])
    _write_renderer_state(emulator, "wRendererJobGeneration", old_generation, 4)

    emulator.pyboy.register_file.PC = emulator.symbols["SoftReset"]
    emulator.pyboy.register_file.SP = emulator.symbols["wStack"]

    expected_generation = old_generation + 1
    for _ in range(240):
        emulator.tick()
        if (
            _read_generation(emulator) == expected_generation
            and emulator.pyboy.memory[emulator.symbols["hSoftReset"]] == 16
        ):
            break
    else:
        raise AssertionError(
            "genuine soft reset did not complete Init: "
            f"generation={_read_generation(emulator)}, "
            f"hSoftReset={emulator.pyboy.memory[emulator.symbols['hSoftReset']]}, "
            f"pc={emulator.pyboy.register_file.PC:#06x}"
        )

    assert emulator.read("wRendererOwner") == constants["RENDERER_YELLOW"]
    assert emulator.read("wRendererPhase") == constants["YELLOW_ACTIVE"]
    assert emulator.read("wRendererAdmissionOpen") == 1
    assert emulator.read("wRendererJobState") == constants["RENDERER_JOB_NONE"]
    assert emulator.read_bytes("wRendererJobGeneration", 4) == bytes(4)
    assert (
        emulator.read("wRendererJobCancellationReason")
        == constants["CANCELLATION_NONE"]
    )
