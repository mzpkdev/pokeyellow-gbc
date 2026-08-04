"""Production-linkage quarantine checks for the bounded Color substrate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
PRODUCTION_SUBSTRATE = frozenset(
    {
        "RouteRendererOwnershipVBlank",
        "RunFullColorOwnershipVBlank",
        "InitFullColorSchedulerSelected",
        "CancelFullColorSchedulerSelected",
        "PrepareFullColorVisibleUnitSelected",
        "CommitFullColorVisibleUnitSelected",
        "PrepareFullColorPairedTransferSelected",
        "CommitFullColorPairedTransferSelected",
        "MapFullColorOAMAttribute",
        "FullColorOverworldBGPalettes",
        "FullColorOverworldTileAttributes",
        "InitFullColorProductionLifecycleSelected",
        "SnapshotFullColorMapAuthority",
        "PoisonLegacyVideoRequests",
        "BeginFullColorMapEntry",
        "CompleteFullColorMapReconstruction",
        "wFullColorProductionSchedulerStateStart",
        "wFullColorProductionSchedulerStateEnd",
        "wFullColorProductionLifecycleStateStart",
        "wFullColorProductionReconstructionBarrier",
        "wFullColorProductionLifecycleStateEnd",
    }
)
FORBIDDEN_PRODUCTION_MARKERS = (
    "Phase2Audit",
    "Phase2Hostile",
    "PollFullColorPhase2DebugCommand",
    "SnapshotFullColorPhase2DebugSelected",
    "wFullColorPhase2Debug",
    "wFullColorDebugCarrier",
    "wPassiveFullColor",
    "PassiveFullColor",
    "FullColorCanary",
)
REQUIRED_COLOR_WRITERS_AND_ACTIVATION = frozenset(
    {
        "ActivateFullColorOwnerForDiagnostic",
        "SelectFullColorOwnerForDiagnostic",
        "BeginFullColorMapEntry",
        "CompleteFullColorMapReconstruction",
        "ReconstructFullColorMapEntry",
        "RunFullColorOwnershipVBlank",
        "PrepareFullColorVisibleUnitSelected",
        "CommitFullColorVisibleUnitSelected",
        "CommitFullColorBGPaletteSelected",
        "CommitFullColorOBJPaletteSelected",
        "CommitFullColorPairedTransferSelected",
        "CommitFullColorAnimationReplacementSelected",
        "CommitFullColorOAMBatchSelected",
        "FullColorVBlankOwnerConsumed",
        "EnqueueFullColorCurrentTileMapOverlayFar",
        "EnqueueFullColorWindowTileMapOverlayFar",
        "MapFullColorOAMAttributeFar",
        "EnqueueFullColorOAMBatchFar",
    }
)
PRODUCTION_ROOTS = (
    "Start",
    "VBlank",
    "InitRendererOwnership",
    "ResetRendererOwnership",
    "SoftResetRendererOwnership",
    "OverworldLoop",
    "DisplayStartMenu",
    "DisplayPartyMenu",
    "InitBattle",
    "DisplayBattleMenu",
)
YELLOW_VBLANK_CALLS = (
    "AutoBgMapTransfer",
    "VBlankCopyBgMap",
    "RedrawRowOrColumn",
    "VBlankCopy",
    "VBlankCopyDouble",
    "UpdateMovingBgTiles",
    "PrepareOAMData",
)
RSVBK = 0xFF70
RVBK = 0xFF4F
INTERRUPT_FLAGS = 0xFF0F
INTERRUPT_ENABLE = 0xFFFF
BOOTROM_DISABLE = 0xFF50
VBLANK_INTERRUPT = 1
WRAM_PROGRAM = 0xD100
RETURN_PROBE = 0x0100
HARNESS_LOOP = 0xFF80


def _symbols(product: str) -> tuple[dict[str, tuple[int, int]], dict[tuple[int, int], str]]:
    by_name: dict[str, tuple[int, int]] = {}
    by_address: dict[tuple[int, int], str] = {}
    for line in (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if match is None:
            continue
        location = (int(match.group(1), 16), int(match.group(2), 16))
        by_name[match.group(3)] = location
        if "." not in match.group(3):
            by_address.setdefault(location, match.group(3))
    return by_name, by_address


def _constants(product: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+) (\S+)", line)
        if match is not None:
            result[match.group(2)] = int(match.group(1), 16)
    return result


@pytest.mark.parametrize("product", PRODUCTS)
def test_production_products_link_only_the_allowlisted_substrate(product: str) -> None:
    symbols, _ = _symbols(product)
    assert PRODUCTION_SUBSTRATE <= symbols.keys()
    assert {
        "FULL_COLOR_FLAG_OAM_FINISHED": 4,
        "FULL_COLOR_FLAG_MOVEMENT_STRIP": 8,
    }.items() <= _constants(product).items()
    assert not {
        name
        for name in symbols
        if any(marker in name for marker in FORBIDDEN_PRODUCTION_MARKERS)
    }

    assert symbols["wRendererStateStart"] == (2, 0xD000)
    assert symbols["wRendererStateEnd"] == (2, 0xD00D)
    assert symbols["wFullColorProductionSchedulerStateStart"] == (2, 0xD00D)
    assert symbols["wFullColorProductionSchedulerStateEnd"] == (2, 0xD3D5)
    assert symbols["wFullColorProductionLifecycleStateStart"] == (2, 0xD3D5)
    timing = symbols["wFullColorTimingState"][1]
    barrier = symbols["wFullColorProductionReconstructionBarrier"][1]
    lifecycle_end = symbols["wFullColorProductionLifecycleStateEnd"][1]
    assert timing + 4 <= barrier < lifecycle_end < 0xD800


def _read_wram2(emulator: Emulator, start: int, end: int) -> bytes:
    prior = emulator.pyboy.memory[0xFF70]
    emulator.pyboy.memory[0xFF70] = 2
    try:
        return bytes(emulator.pyboy.memory[address] for address in range(start, end))
    finally:
        emulator.pyboy.memory[0xFF70] = prior


def _visible_resources(emulator: Emulator) -> tuple[bytes, ...]:
    return (
        emulator.read_vram_bank(0, 0x8000, 0x2000),
        emulator.read_vram_bank(1, 0x8000, 0x2000),
        emulator.read_palette_ram(),
        emulator.read_palette_ram(object_palettes=True),
        emulator.read_memory(0xFE00, 160),
        emulator.read_bytes("wShadowOAM", 160),
    )


def _authoritative_color_boundaries(product: str) -> frozenset[str]:
    symbols, _ = _symbols(product)
    prefixes = (
        "ActivateFullColor",
        "SelectFullColor",
        "BeginFullColor",
        "CompleteFullColor",
        "ReconstructFullColor",
        "RunFullColor",
        "PrepareFullColor",
        "CommitFullColor",
        "EnqueueFullColor",
        "MapFullColorOAM",
        "FullColorVBlankOwnerConsumed",
    )
    linked_family = {name for name in symbols if name.startswith(prefixes)}
    inventory = json.loads(
        (REPOSITORY_ROOT / "specs/full-colors/inventory/writers.json").read_text(
            encoding="utf-8"
        )
    )
    inventory_family = {
        site["symbol"].split(".", 1)[0]
        for row in inventory["rows"]
        if row["owner"] != "RENDERER_YELLOW"
        for site in row["source_sites"]
        if site["symbol"].split(".", 1)[0] in symbols
    }
    boundaries = frozenset(linked_family | inventory_family)
    assert REQUIRED_COLOR_WRITERS_AND_ACTIVATION <= boundaries
    return boundaries


def _write_wram2(emulator: Emulator, symbol: str, data: bytes) -> None:
    prior = emulator.pyboy.memory[RSVBK]
    emulator.pyboy.memory[RSVBK] = 2
    try:
        address = emulator.symbols[symbol]
        for offset, value in enumerate(data):
            emulator.pyboy.memory[address + offset] = value
    finally:
        emulator.pyboy.memory[RSVBK] = prior


def _run_complete_vblank(
    emulator: Emulator, observed_symbols: frozenset[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    memory = emulator.pyboy.memory
    registers = emulator.pyboy.register_file
    memory[BOOTROM_DISABLE] = 1
    prior_bank = memory[RSVBK]
    memory[RSVBK] = 6
    memory[WRAM_PROGRAM : WRAM_PROGRAM + 3] = b"\xf3\x18\xfe"
    memory[INTERRUPT_ENABLE] = 0
    memory[INTERRUPT_FLAGS] = 0
    registers.PC = WRAM_PROGRAM
    registers.SP = 0xFFFC
    emulator.pyboy.tick(1, render=False, sound=False)
    memory[WRAM_PROGRAM : WRAM_PROGRAM + 4] = bytes(
        (0xFB, 0xC3, RETURN_PROBE & 0xFF, RETURN_PROBE >> 8)
    )
    registers.PC = WRAM_PROGRAM
    registers.SP = 0xFFFC
    memory[RSVBK] = 6
    memory[RVBK] = 1
    memory[INTERRUPT_ENABLE] = VBLANK_INTERRUPT
    memory[INTERRUPT_FLAGS] = VBLANK_INTERRUPT
    yellow_calls: list[str] = []
    color_calls: list[str] = []
    returned = False

    def record_yellow(context: str) -> None:
        yellow_calls.append(context)

    def record_color(context: str) -> None:
        color_calls.append(context)

    def returned_to_probe(_: object) -> None:
        nonlocal returned
        returned = True
        memory[INTERRUPT_ENABLE] = 0
        memory[HARNESS_LOOP] = 0x18
        memory[HARNESS_LOOP + 1] = 0xFE
        registers.PC = HARNESS_LOOP

    hooks: list[tuple[int, int]] = []
    locations: dict[tuple[int, int], list[str]] = {}
    for name in observed_symbols:
        locations.setdefault(
            (emulator.symbol_banks[name], emulator.symbols[name]), []
        ).append(name)
    for (bank, address), names in locations.items():
        label = "/".join(sorted(names))
        emulator.pyboy.hook_register(bank, address, record_color, label)
        hooks.append((bank, address))
    for name in YELLOW_VBLANK_CALLS:
        bank = emulator.symbol_banks[name]
        address = emulator.symbols[name]
        emulator.pyboy.hook_register(bank, address, record_yellow, name)
        hooks.append((bank, address))
    emulator.pyboy.hook_register(0, RETURN_PROBE, returned_to_probe, None)
    try:
        emulator.pyboy.tick(1, render=False, sound=False)
    finally:
        emulator.pyboy.hook_deregister(0, RETURN_PROBE)
        for bank, address in reversed(hooks):
            emulator.pyboy.hook_deregister(bank, address)
        memory[RSVBK] = prior_bank
    assert returned, "production VBlank did not return through RETI"
    return tuple(yellow_calls), tuple(color_calls)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("hostile", (False, True), ids=("yellow", "hostile-color"))
def test_complete_production_vblank_is_forced_yellow_and_color_inert(
    request: pytest.FixtureRequest, product: str, hostile: bool
) -> None:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        for _ in range(180):
            emulator.tick()
            if emulator.read_bytes("wRendererGeneration", 4) == b"\x01\x00\x00\x00":
                break
        else:
            raise AssertionError("hard boot did not initialize renderer ownership")
        assert emulator.read("wRendererOwner") == 0
        assert emulator.read("wRendererPhase") == 0
        assert emulator.read("wRendererAdmissionOpen") == 1
        assert emulator.read("wRendererJobState") == 0xFF
        assert emulator.read("wFullColorRequestCount") == 0
        assert emulator.read("wFullColorProducerPending") == 0

        symbols, _ = _symbols(product)
        start = symbols["wRendererStateStart"][1]
        end = symbols["wFullColorProductionLifecycleStateEnd"][1]
        if hostile:
            _write_wram2(emulator, "wRendererOwner", b"\x01")
            _write_wram2(emulator, "wRendererPhase", b"\x03")
            _write_wram2(emulator, "wRendererGeneration", b"\xef\xbe\xad\xde")
            _write_wram2(emulator, "wRendererAdmissionOpen", b"\x01")
            _write_wram2(emulator, "wRendererJobState", b"\x02")
            _write_wram2(emulator, "wFullColorRequestCount", b"\xff")
            _write_wram2(emulator, "wFullColorProducerPending", b"\x01")
            assert emulator.read("wRendererOwner") == 1
            assert emulator.read_bytes("wRendererGeneration", 4) == b"\xef\xbe\xad\xde"
            assert emulator.read("wFullColorRequestCount") == 0xFF
            assert emulator.read("wFullColorProducerPending") == 1
        state_before = _read_wram2(emulator, start, end)
        yellow_calls, color_calls = _run_complete_vblank(
            emulator, _authoritative_color_boundaries(product)
        )
        assert color_calls == ()
        assert set(YELLOW_VBLANK_CALLS) <= set(yellow_calls)
        assert _read_wram2(emulator, start, end) == state_before
    finally:
        emulator.close()


def _instruction_length(mnemonic: str, opcode: int) -> int:
    if opcode == 0xCB:
        return 2
    if "d16" in mnemonic or "a16" in mnemonic:
        return 3
    if "d8" in mnemonic or "a8" in mnemonic or "r8" in mnemonic:
        return 2
    return 1


def _reachable_symbols(
    product: str,
    roots: tuple[str, ...],
) -> set[str]:
    from pyboy.core.opcodes import CPU_COMMANDS

    symbols, by_address = _symbols(product)
    rom = (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()
    work = [symbols[root] for root in roots]
    visited_instructions: set[tuple[int, int]] = set()
    reached: set[str] = set()
    while work:
        bank, address = work.pop()
        location = (bank, address)
        if location in visited_instructions:
            continue
        visited_instructions.add(location)
        if location in by_address:
            symbol = by_address[location]
            reached.add(symbol)
        offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
        opcode = rom[offset]
        mnemonic = CPU_COMMANDS[opcode]
        length = _instruction_length(mnemonic, opcode)
        fallthrough = (bank, address + length)
        if opcode in {0xC9, 0xD9, 0xE9, 0x10, 0x76}:
            continue
        if opcode in {0x18, 0x20, 0x28, 0x30, 0x38}:
            displacement = int.from_bytes(rom[offset + 1 : offset + 2], "little", signed=True)
            work.append((bank, (address + 2 + displacement) & 0xFFFF))
            if opcode != 0x18:
                work.append(fallthrough)
            continue
        if opcode in {0xC2, 0xC3, 0xCA, 0xD2, 0xDA, 0xC4, 0xCC, 0xCD, 0xD4, 0xDC}:
            target_address = int.from_bytes(rom[offset + 1 : offset + 3], "little")
            target_bank = 0 if target_address < 0x4000 else bank
            target = (target_bank, target_address)
            bankswitch = symbols.get("Bankswitch")
            if target == bankswitch and offset >= 5 and rom[offset - 5] == 0x06 and rom[offset - 3] == 0x21:
                target = (rom[offset - 4], int.from_bytes(rom[offset - 2 : offset], "little"))
            work.append(target)
            if opcode != 0xC3:
                work.append(fallthrough)
            continue
        if opcode in {0xC0, 0xC8, 0xD0, 0xD8}:
            work.append(fallthrough)
            continue
        if opcode in {0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF}:
            work.append((0, opcode & 0x38))
        work.append(fallthrough)
    return reached


@pytest.mark.parametrize("product", PRODUCTS)
def test_static_production_roots_cannot_reach_color_writers_or_activation(product: str) -> None:
    symbols, _ = _symbols(product)
    bank, address = symbols["RouteRendererOwnershipVBlank"]
    offset = bank * 0x4000 + address - 0x4000
    route = (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[offset : offset + 4]
    assert route[0] == 0xC9
    assert "PollFullColorDebugCommand" not in symbols
    assert set(PRODUCTION_ROOTS) <= symbols.keys()
    reached = _reachable_symbols(product, PRODUCTION_ROOTS)
    assert reached.isdisjoint(_authoritative_color_boundaries(product))


def test_audit_identity_and_surface_are_unchanged() -> None:
    expected = {
        "pokeyellow_phase2_audit.gbc": "40b0a702c94ebddeb3fd26202c10a60b6dd00b66a392da7ab9598d61c092dcd6",
        "pokeyellow_phase2_audit.map": "f6c9ca2f315bed0432e4e6964377262ccd0202f2674eeaf584cffdd387b53f25",
        "pokeyellow_phase2_audit.sym": "11c50853e72e28fdff47b721ac0cf6f5fe14396b311a59d9b993fc5ef2b619d3",
    }
    assert {
        name: hashlib.sha256((REPOSITORY_ROOT / name).read_bytes()).hexdigest()
        for name in expected
    } == expected
    audit, _ = _symbols("pokeyellow_phase2_audit")
    assert {
        "PollFullColorPhase2DebugCommand",
        "wFullColorDebugCarrierStart",
        "wPassiveFullColorActive",
        "PassiveFullColorVBlank",
        "FullColorCanaryBGPalettes",
        "FullColorCanaryOBJPalettes",
        "FullColorCanaryOverworldTileClasses",
    } <= audit.keys()
    assert audit["RouteRendererOwnershipVBlank"] == (0x3B, 0x452B)
    assert audit["wFullColorPhase2StateStart"] == (2, 0xD00D)
    assert audit["wFullColorPhase2LifecycleStateEnd"] == (2, 0xD7FA)
