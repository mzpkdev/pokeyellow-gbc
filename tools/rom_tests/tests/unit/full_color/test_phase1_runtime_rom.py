"""Real debug-ROM integration for the activated Phase 1 runtime case."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.full_color.enums import (
    CancellationReason,
    JobState,
    Owner,
    Phase,
)
from tools.rom_tests.full_color.phase1_baseline import (
    GenerationContract,
    compare_phase1_baseline,
)
from tools.rom_tests.full_color.renderer_conformance_runtime import (
    canonical_phase1_case,
    check_runtime_observation,
)
from tools.rom_tests.full_color.runtime_observability import (
    PHASE1_MAX_COMMAND_FRAMES,
    capture_phase1_runtime_observation,
    capture_yellow_baseline_snapshot,
    restore_phase1_to_yellow,
    run_debug_command,
    wait_until_phase1_capture_ready,
)

ROOT = Path(__file__).resolve().parents[5]
VISIBLE_FIELDS = (
    "bg_tile_ids",
    "bg_attributes",
    "bg_palettes",
    "obj_palettes",
    "shadow_oam",
    "hardware_oam",
    "map_id",
    "tileset_id",
    "dirty",
)
INTERRUPT_FLAGS = 0xFF0F
INTERRUPT_ENABLE = 0xFFFF
VBLANK_INTERRUPT = 1
RSVBK = 0xFF70
WRAM0_START = 0xC000
WRAM0_SIZE = 0x1000
HRAM_START = 0xFF80
HRAM_SIZE = 0x7F


def _assert_bytes_identical(label: str, expected: bytes, actual: bytes) -> None:
    if expected == actual:
        return
    offset = next(
        index
        for index, pair in enumerate(zip(expected, actual, strict=True))
        if pair[0] != pair[1]
    )
    raise AssertionError(
        f"{label}[0x{offset:04x}]={expected[offset]:#04x}->{actual[offset]:#04x}"
    )


def _assert_later_vblanks_execute_healthy_dma(emulator: Emulator) -> None:
    entries = 0
    dma_calls = 0

    def enter_vblank(_: object) -> None:
        nonlocal entries
        entries += 1

    def enter_dma(_: object) -> None:
        nonlocal dma_calls
        dma_calls += 1

    vblank = emulator.symbols["VBlank"]
    dma = emulator.symbols["hDMARoutine"]
    dma_call = bytes((0xCD, dma & 0xFF, dma >> 8))
    vblank_body = emulator.rom.read_bytes()[vblank : vblank + 0x200]
    dma_call_offset = vblank_body.find(dma_call)
    assert dma_call_offset >= 0, "Yellow VBlank no longer calls hDMARoutine"
    dma_callsite = vblank + dma_call_offset
    dma_before = emulator.read_memory(dma, 0x15)
    emulator.pyboy.hook_register(0, vblank, enter_vblank, None)
    emulator.pyboy.hook_register(0, dma_callsite, enter_dma, None)
    try:
        emulator.tick(4)
    finally:
        emulator.pyboy.hook_deregister(0, vblank)
        emulator.pyboy.hook_deregister(0, dma_callsite)
    assert entries >= 3, f"expected at least 3 genuine later VBlanks; got {entries}"
    assert dma_calls == entries, (
        f"Yellow DMA ran {dma_calls} times across {entries} genuine later VBlanks"
    )
    _assert_bytes_identical(
        "hDMARoutine", dma_before, emulator.read_memory(dma, len(dma_before))
    )


def _fresh_run(results: Path) -> dict[str, str]:
    case = canonical_phase1_case(ROOT)
    emulator = Emulator(
        rom=Path(os.environ.get("ROM_TEST_ROM", ROOT / "pokeyellow_debug.gbc")),
        symbols=Path(
            os.environ.get("ROM_TEST_SYMBOLS", ROOT / "pokeyellow_debug.sym")
        ),
        results=results,
        cgb=True,
    )
    try:
        wait_until_phase1_capture_ready(emulator)
        before = capture_yellow_baseline_snapshot(
            emulator,
            scenario="phase1-baseline",
            seed=0,
            checkpoint="before-phase1-command",
        )
        ie_before = emulator.read_memory(INTERRUPT_ENABLE, 1)[0]
        if_before = emulator.read_memory(INTERRUPT_FLAGS, 1)[0]
        wram0_before = emulator.read_memory(WRAM0_START, WRAM0_SIZE)
        hram_before = emulator.read_memory(HRAM_START, HRAM_SIZE)
        observation = capture_phase1_runtime_observation(
            emulator, case, settle_debug_ready=False
        )
        assert emulator.read_memory(INTERRUPT_ENABLE, 1)[0] == ie_before
        if_after = emulator.read_memory(INTERRUPT_FLAGS, 1)[0]
        assert if_after & ~VBLANK_INTERRUPT == if_before & ~VBLANK_INTERRUPT

        assert emulator.frame - before.frame <= PHASE1_MAX_COMMAND_FRAMES
        assert observation.snapshot.owner is Owner.RENDERER_FULL_COLOR_OVERWORLD
        assert observation.snapshot.phase is Phase.OVERWORLD_ACTIVE
        assert observation.snapshot.generation == 8
        assert observation.snapshot.job is not None
        assert observation.snapshot.job.state is JobState.COMPLETE
        runtime_report = check_runtime_observation(case, observation)
        assert runtime_report.passed, runtime_report.to_json()

        entries = observation.trace.entries
        assert len(entries) == 7
        assert tuple(entry.sequence for entry in entries) == tuple(range(7))
        assert tuple(entry.job_id for entry in entries) == (
            "JOB-OLD",
            "JOB-OLD",
            "JOB-OLD",
            "JOB-REPLACEMENT",
            "JOB-REPLACEMENT",
            "JOB-REPLACEMENT",
            "JOB-REPLACEMENT",
        )
        assert tuple(entry.job_state for entry in entries) == (
            JobState.PENDING,
            JobState.PREPARED,
            JobState.CANCELLED,
            JobState.PENDING,
            JobState.PREPARED,
            JobState.COMMITTING,
            JobState.COMPLETE,
        )
        assert entries[2].cancellation_reason is CancellationReason.SUPERSEDED
        assert all(
            entry.cancellation_reason is None
            for index, entry in enumerate(entries)
            if index != 2
        )
        assert tuple(entry.generation for entry in entries) == (7, 7, 7, 8, 8, 8, 8)
        assert tuple(entry.job_generation for entry in entries) == (
            7,
            7,
            7,
            8,
            8,
            8,
            8,
        )
        assert tuple(entry.wrote for entry in entries) == (
            False,
            False,
            False,
            False,
            False,
            True,
            False,
        )
        assert observation.trace.resource_identities[entries[5].resource_id] == (
            "ownership_generation"
        )
        for field in VISIBLE_FIELDS:
            expected = getattr(before, field)
            actual = getattr(observation.snapshot, field)
            if isinstance(expected, bytes) and expected != actual:
                offset = next(
                    index
                    for index, pair in enumerate(zip(expected, actual, strict=True))
                    if pair[0] != pair[1]
                )
                raise AssertionError(f"{field}[0x{offset:04x}]")
            assert actual == expected, field

        _assert_bytes_identical(
            "WRAM0",
            wram0_before,
            emulator.read_memory(WRAM0_START, WRAM0_SIZE),
        )
        _assert_bytes_identical(
            "HRAM", hram_before, emulator.read_memory(HRAM_START, HRAM_SIZE)
        )

        after = restore_phase1_to_yellow(emulator)
        _assert_bytes_identical(
            "WRAM0",
            wram0_before,
            emulator.read_memory(WRAM0_START, WRAM0_SIZE),
        )
        _assert_bytes_identical(
            "HRAM", hram_before, emulator.read_memory(HRAM_START, HRAM_SIZE)
        )
        baseline_report = compare_phase1_baseline(before, after)
        assert baseline_report.passed, baseline_report.to_json()
        assert after.owner is Owner.RENDERER_YELLOW
        assert after.phase is Phase.YELLOW_ACTIVE
        assert after.generation == 9
        assert after.job is None
        assert not after.queued_jobs
        _assert_later_vblanks_execute_healthy_dma(emulator)

        return {
            "before": before.to_json(),
            "runtime": observation.snapshot.to_json(),
            "trace": observation.trace.to_json(),
            "after": after.to_json(),
            "baseline_report": baseline_report.to_json(),
        }
    finally:
        emulator.close()


def test_phase1_runtime_rom_is_causal_deterministic_and_visually_inert(
    tmp_path: Path,
) -> None:
    first = _fresh_run(tmp_path / "run-1")
    second = _fresh_run(tmp_path / "run-2")
    assert second == first


def test_phase1_diagnostic_failure_restores_host_trampoline_state(
    tmp_path: Path,
) -> None:
    emulator = Emulator(
        ROOT / "pokeyellow_debug.gbc",
        ROOT / "pokeyellow_debug.sym",
        tmp_path / "failure-cleanup",
        cgb=True,
    )
    try:
        wait_until_phase1_capture_ready(emulator)
        pyboy = emulator.pyboy
        regs = pyboy.register_file
        register_before = {
            name: getattr(regs, name)
            for name in ("A", "F", "B", "C", "D", "E", "HL", "SP", "PC")
        }
        stack_top = emulator.symbols["wStack"]
        stack_before = emulator.read_memory(stack_top - 128, 128, bank=1)
        hram_before = emulator.read_memory(HRAM_START, HRAM_SIZE)
        machine_before = {
            address: pyboy.memory[address]
            for address in (
                0xFF70,
                INTERRUPT_FLAGS,
                INTERRUPT_ENABLE,
                emulator.symbols["hLoadedROMBank"],
            )
        }

        class FailTickProxy:
            def __getattr__(self, name: str) -> object:
                return getattr(pyboy, name)

            def tick(self, *_: object, **__: object) -> None:
                raise RuntimeError("injected diagnostic tick failure")

        emulator.pyboy = FailTickProxy()  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="injected diagnostic tick failure"):
            run_debug_command(emulator)
        emulator.pyboy = pyboy

        assert {
            name: getattr(regs, name) for name in register_before
        } == register_before
        assert {
            address: pyboy.memory[address] for address in machine_before
        } == machine_before
        _assert_bytes_identical(
            "bank-1 diagnostic stack",
            stack_before,
            emulator.read_memory(stack_top - 128, 128, bank=1),
        )
        _assert_bytes_identical(
            "HRAM", hram_before, emulator.read_memory(HRAM_START, HRAM_SIZE)
        )
    finally:
        emulator.close()


@pytest.mark.parametrize("path", ("hard-boot", "forced-entry-bank-vblank"))
def test_real_unchanged_generation_baseline_reports(
    tmp_path: Path, path: str
) -> None:
    emulator = Emulator(
        ROOT / "pokeyellow_debug.gbc",
        ROOT / "pokeyellow_debug.sym",
        tmp_path / path,
        cgb=True,
    )
    try:
        wait_until_phase1_capture_ready(emulator)
        before = capture_yellow_baseline_snapshot(
            emulator, scenario=path, seed=0, checkpoint=f"{path}-before"
        )
        expected = before
        if path == "forced-entry-bank-vblank":
            emulator.pyboy.memory[RSVBK] = 7
            assert emulator.pyboy.memory[RSVBK] == 7
            expected = replace(before, banks=replace(before.banks, wram=7))
        emulator.tick()
        if path == "forced-entry-bank-vblank":
            assert emulator.pyboy.memory[RSVBK] == 7
        after = capture_yellow_baseline_snapshot(
            emulator, scenario=path, seed=0, checkpoint=f"{path}-after"
        )
        report = compare_phase1_baseline(
            expected, after, generation_contract=GenerationContract.UNCHANGED
        )
        assert report.passed, report.to_json()
    finally:
        emulator.close()


def test_real_soft_reset_baseline_report(tmp_path: Path) -> None:
    emulator = Emulator(
        ROOT / "pokeyellow_debug.gbc", ROOT / "pokeyellow_debug.sym",
        tmp_path / "soft-reset", cgb=True,
    )
    try:
        wait_until_phase1_capture_ready(emulator)
        before = capture_yellow_baseline_snapshot(
            emulator, scenario="soft-reset", seed=0, checkpoint="before"
        )
        for _ in range(180):
            if emulator.pyboy.memory[emulator.symbols["hSoftReset"]] == 16:
                break
            emulator.tick()
        emulator.pyboy.register_file.PC = emulator.symbols["SoftReset"]
        emulator.pyboy.register_file.SP = emulator.symbols["wStack"]
        for _ in range(240):
            emulator.tick()
            if int.from_bytes(
                emulator.read_bytes("wRendererGeneration", 4), "little"
            ) == 2 and emulator.pyboy.memory[emulator.symbols["hSoftReset"]] == 16:
                break
        else:
            raise AssertionError("genuine soft reset did not publish generation 2")
        emulator.tick(3)
        after = capture_yellow_baseline_snapshot(
            emulator, scenario="soft-reset", seed=0, checkpoint="after"
        )
        report = compare_phase1_baseline(before, after)
        assert report.passed, report.to_json()
    finally:
        emulator.close()


@pytest.mark.parametrize(
    ("symbol", "failure"),
    [
        ("FullColorDebugMutationOwner", "invalid owner/phase pair"),
        ("FullColorDebugMutationPhase", "invalid owner/phase pair"),
        ("FullColorDebugMutationGeneration", "stale job generation"),
        ("FullColorDebugMutationCancellation", "CANCELLED requires"),
        ("FullColorDebugMutationWrite", "cancelled work reports"),
    ],
)
def test_patched_debug_rom_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol: str, failure: str
) -> None:
    rom = bytearray((ROOT / "pokeyellow_debug.gbc").read_bytes())
    lines = (ROOT / "pokeyellow_debug.sym").read_text(encoding="utf-8").splitlines()
    locations = {
        name: (int(bank, 16), int(address, 16))
        for line in lines
        if line
            and not line.startswith(";")
            and ":" in line.split(maxsplit=1)[0]
        for location, name in [line.split(maxsplit=1)]
        for bank, address in [location.split(":", 1)]
    }
    bank, address = locations[symbol]
    rom[bank * 0x4000 + address - 0x4000] = 1
    patched = tmp_path / f"{symbol}.gbc"
    patched.write_bytes(rom)
    monkeypatch.setenv("ROM_TEST_ROM", str(patched))
    with pytest.raises(Exception, match=failure):
        _fresh_run(tmp_path / "results")


@pytest.mark.parametrize(
    ("symbol", "path"),
    [
        ("FullColorDebugMutationCompletion", "trace.complete_commit"),
        ("FullColorDebugMutationVideo", "shadow_oam[0x0000]"),
    ],
)
def test_patched_debug_rom_semantic_mutations_are_localized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbol: str, path: str
) -> None:
    rom = bytearray((ROOT / "pokeyellow_debug.gbc").read_bytes())
    symbols = Emulator._parse_symbols(
        (ROOT / "pokeyellow_debug.sym").read_text(encoding="utf-8").splitlines()
    )
    banks = Emulator._parse_symbol_banks(
        (ROOT / "pokeyellow_debug.sym").read_text(encoding="utf-8").splitlines()
    )
    rom[banks[symbol] * 0x4000 + symbols[symbol] - 0x4000] = 1
    patched = tmp_path / f"{symbol}.gbc"
    patched.write_bytes(rom)
    monkeypatch.setenv("ROM_TEST_ROM", str(patched))
    with pytest.raises(AssertionError) as raised:
        _fresh_run(tmp_path / "results")
    assert path in str(raised.value)
