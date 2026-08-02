"""Product-matrix proof for Phase 2 hostile-slice activation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
)


PRODUCTS = {
    "release": "pokeyellow",
    "debug": "pokeyellow_debug",
    "audit": "pokeyellow_phase2_audit",
    "vc": "pokeyellow_vc",
}


def _symbol_names(product: str) -> set[str]:
    lines = (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines()
    return {
        line.split(maxsplit=1)[1]
        for line in lines
        if line and not line.startswith(";") and len(line.split(maxsplit=1)) == 2
    }


def _symbol_addresses(product: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in (REPOSITORY_ROOT / f"{product}.sym").read_text(
        encoding="utf-8",
    ).splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or ":" not in fields[0]:
            continue
        result[fields[1]] = int(fields[0].split(":", maxsplit=1)[1], 16)
    return result


def test_only_normal_debug_exports_live_slice_and_runtime_carrier() -> None:
    symbols = {name: _symbol_names(product) for name, product in PRODUCTS.items()}
    live = {
        "BeginFullColorMapEntry",
        "FullColorVBlankOwnerConsumed",
        "FullColorCanaryBGPalettes",
    }
    runtime = {
        "wFullColorPhase2RuntimeCarrierStart",
        "wFullColorPhase2RuntimeRecords",
        "wFullColorRuntimeTimingEvent",
        "RunFullColorPhase2RuntimeArm",
    }

    assert live | runtime <= symbols["debug"]
    assert "Phase2AuditProvenance" not in symbols["debug"]
    assert live <= symbols["audit"]
    assert "Phase2AuditProvenance" in symbols["audit"]
    assert not (runtime & symbols["audit"])
    for product in ("release", "vc"):
        assert not (live | runtime | {"Phase2AuditProvenance"}) & symbols[product]


def test_debug_runtime_carrier_layout_and_exact_timing_markers() -> None:
    symbols = _symbol_addresses("pokeyellow_debug")
    start = symbols["wFullColorPhase2RuntimeCarrierStart"]
    records = symbols["wFullColorPhase2RuntimeRecords"]
    end = symbols["wFullColorPhase2RuntimeCarrierEnd"]

    assert start == 0xBEAF
    assert records - start == 16
    assert end - start == 288
    assert symbols["wFullColorPhase2RuntimeWriteIndex"] - start == 14
    assert symbols["wFullColorRuntimeTimingEvent"] == 0xD7FA
    assert symbols["wFullColorRuntimeTimingRow"] == 0xD7FB
    assert symbols["wFullColorRuntimeTimingSequence"] == 0xD7FC
    assert symbols["wFullColorRuntimeTimingProbeResult"] == 0xD7FE
    assert symbols["wFullColorRuntimeTimingProbeCycles"] == 0xD7FF


def test_rom_consumes_host_threshold_probe_without_entering_committing(
    request: pytest.FixtureRequest,
) -> None:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        symbols=REPOSITORY_ROOT / "pokeyellow_debug.sym",
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = Phase2Rom(emulator, numeric_symbols(REPOSITORY_ROOT / "pokeyellow_debug.sym"))
    try:
        emulator.pyboy.memory[0xFF70] = 2
        _, flags = rom.call(
            "BeginFullColorRuntimeTimingSampleSelected",
            a=rom.constants["FULL_COLOR_TIMING_ROW_OAM_MAXIMUM"],
        )
        assert flags & 0x10 == 0
        assert rom.read_wram2("wFullColorRuntimeTimingRow") == b"\x0c"
        assert rom.read_wram2("wFullColorRuntimeTimingSequence", 2) == b"\x01\x00"
        rom.write_wram2("wFullColorRuntimeTimingProbeCycles", b"\x01\x02\x03\x04")
        rom.call("EndFullColorRuntimeTimingSampleSelected")
        assert rom.read_wram2("wFullColorRuntimeTimingRow") == b"\x0c"
        assert rom.read_wram2("wFullColorRuntimeTimingProbeResult") == b"\x01"
        assert rom.read_wram2("wFullColorRuntimeTimingEvent") == b"\x06"
        assert rom.read_wram2("wFullColorRuntimeTimingSequence", 2) == b"\x01\x00"
    finally:
        emulator.close()


def test_normal_debug_executes_real_handoff_while_phase1_mailbox_remains(
    request: pytest.FixtureRequest,
) -> None:
    symbols_path = REPOSITORY_ROOT / "pokeyellow_debug.sym"
    names = _symbol_names("pokeyellow_debug")
    assert {"PollFullColorDebugCommand", "wFullColorDebugStateStart"} <= names
    emulator = Emulator(
        rom=REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        symbols=symbols_path,
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = Phase2Rom(emulator, numeric_symbols(symbols_path))
    try:
        rom.call("InitRendererOwnership")
        emulator.pyboy.memory[emulator.symbols["wCurMap"]] = 0
        _, flags = rom.call("BeginFullColorMapEntry")
        assert flags & 0x10 == 0
        assert rom.read_wram2("wRendererOwner") == bytes((
            rom.constants["RENDERER_FULL_COLOR_OVERWORLD"],
        ))
        assert rom.read_wram2("wRendererPhase") == bytes((
            rom.constants["OVERWORLD_RECONSTRUCTING"],
        ))
    finally:
        emulator.close()


def test_normal_debug_vblank_acknowledges_phase2_arm_mailbox(
    request: pytest.FixtureRequest,
) -> None:
    """The production VBlank route must poll the ordinary debug mailbox."""

    emulator = Emulator(
        rom=REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        symbols=REPOSITORY_ROOT / "pokeyellow_debug.sym",
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        for _ in range(601):
            if emulator.read_bytes("wFullColorDebugMagic", 4) == b"FCG0":
                break
            emulator.tick()
        else:
            pytest.fail("debug ROM did not initialize within 600 frames")

        emulator.write("wFullColorPhase2RuntimeScenario", 1)
        emulator.write("wFullColorDebugCommand", 0x30)
        emulator.write("hFullColorDebugCommandPending", 1)
        for _ in range(121):
            emulator.tick()
            header = emulator.read_bytes("wFullColorPhase2RuntimeCarrierStart", 16)
            if header[:4] == b"FCP2" and header[13] == 0x30:
                break
        else:
            pytest.fail("Phase 2 ARM command was not acknowledged by VBlank")

        emulator.write("wFullColorDebugCommand", 0x32)
        emulator.write("hFullColorDebugCommandPending", 1)
        for _ in range(121):
            emulator.tick()
            header = emulator.read_bytes("wFullColorPhase2RuntimeCarrierStart", 16)
            if header[13] == 0x32:
                break
        else:
            pytest.fail("Phase 2 ACK command was not acknowledged by VBlank")
    finally:
        emulator.close()


@pytest.mark.parametrize("product", ("pokeyellow", "pokeyellow_vc"))
def test_release_products_keep_real_palette_zero_oam_fallback_without_recorder(
    product: str, request: pytest.FixtureRequest,
) -> None:
    symbols_path = REPOSITORY_ROOT / f"{product}.sym"
    names = _symbol_names(product)
    assert "MapFullColorOAMAttribute" in names
    assert "MapFullColorOAMAttributeFar" in names
    assert "RecordFullColorOAMFallbackSelected" not in names
    assert not any(name.startswith("FullColorCanary") for name in names)

    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=symbols_path,
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = Phase2Rom(emulator, numeric_symbols(symbols_path))
    try:
        for identity, original in ((0xFF, 0xF7), (0x08, 0xAD), (0x00, 0x5E)):
            emulator.pyboy.memory[0xC700] = original
            value, flags = rom.call(
                "MapFullColorOAMAttributeFar", c=identity, de=0xC700,
            )
            assert value == 0
            assert flags & 0x10
            assert emulator.pyboy.memory[0xC700] == original & 0xF8
    finally:
        emulator.close()
