"""Numeric linked timing and production admission checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.full_color.production_timing import (
    LinkedTimingDecoder,
    REQUIRED_TIMING_KEYS,
    Span,
    _equation,
    enqueue_timing_producer,
    measure_rows,
    render_evidence,
    render_rgbds_constants,
)
from tools.rom_tests.full_color.rom_discovery import load_sym
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
)


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")


@pytest.fixture(params=PRODUCTS)
def timing_rom(request: pytest.FixtureRequest) -> Phase2Rom:
    product = str(request.param)
    symbols = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(
        REPOSITORY_ROOT / f"{product}.gbc",
        symbols,
        result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = Phase2Rom(emulator, numeric_symbols(symbols))
    try:
        rom.activate()
        emulator.pyboy.memory[0xFF70] = 2
        yield rom
    finally:
        emulator.close()


def _generated_constants() -> dict[str, int]:
    values: dict[str, int] = {}
    path = REPOSITORY_ROOT / "constants/full_color_timing_constants.asm"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEF "):
            _, name, _, value = line.split()
            values[name] = int(value, 0)
    return values


def test_required_linked_rows_are_complete_numeric_and_deterministic() -> None:
    first = measure_rows(REPOSITORY_ROOT)
    second = measure_rows(REPOSITORY_ROOT)
    assert tuple(first) == tuple(second) == REQUIRED_TIMING_KEYS
    assert render_evidence(first).encode() == render_evidence(second).encode()
    assert render_rgbds_constants(first).encode() == render_rgbds_constants(second).encode()
    assert render_rgbds_constants(first) == (
        REPOSITORY_ROOT / "constants/full_color_timing_constants.asm"
    ).read_text(encoding="utf-8")
    for row in first.values():
        assert 0 < row.worst_cycles == row.defer_threshold < 0xFFFF
        assert row.worst_cycles + row.guard_cycles <= row.deadline_cycles
        assert row.terms and len(row.linked_sha256) == 64


def test_linked_opcode_mutation_changes_timing_authority() -> None:
    symbols = load_sym(REPOSITORY_ROOT / "pokeyellow.sym")
    original = (REPOSITORY_ROOT / "pokeyellow.gbc").read_bytes()
    start = symbols.resolve("ResolveEffectiveRendererOwner")
    offset = start.bank * 0x4000 + start.address - 0x4000
    mutated = bytearray(original)
    # ld a,b -> ld a,[hl]: same instruction length, strictly slower linked path.
    mutated[offset + 4] = 0x7E
    term = Span("ResolveEffectiveRendererOwner", "ResolveCurrentOrdinaryMapOwner")
    before = _equation(LinkedTimingDecoder(original, symbols), term)
    after = _equation(LinkedTimingDecoder(bytes(mutated), symbols), term)
    assert before[0] != after[0]
    assert before[2] != after[2]


def test_generated_production_budgets_are_finite_and_class_specific() -> None:
    constants = _generated_constants()
    assert constants
    assert all(0 < value < 0xFFFF for value in constants.values())
    assert 0xFFFF not in constants.values()
    assert len({
        constants["FULL_COLOR_PRODUCTION_PALETTE_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_ANIMATION_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_OAM_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_ROW_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_COLUMN_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_MOVEMENT_ROW_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_MOVEMENT_COLUMN_RESERVATION"],
        constants["FULL_COLOR_PRODUCTION_RECTANGLE_RESERVATION"],
    }) == 8
    assert len([
        name for name in constants if name.startswith("FULL_COLOR_TRANSITION_")
    ]) == 7


@pytest.mark.parametrize("product", PRODUCTS)
def test_frozen_oam_dma_page_preserves_measured_stack_margin(product: str) -> None:
    symbols = load_sym(REPOSITORY_ROOT / f"{product}.sym")
    start = symbols.resolve("wFullColorShadowOAMBatch").address
    end = start + 160
    assert start & 0xFF == 0
    assert start >= symbols.resolve("wFullColorProductionLifecycleStateEnd").address
    assert symbols.resolve("wStack").address - end >= 128


SCHEDULER_CASES = (
    ("palette-bg", "FULL_COLOR_PRODUCTION_PALETTE_RESERVATION", 64),
    ("palette-obj", "FULL_COLOR_PRODUCTION_PALETTE_RESERVATION", 64),
    ("row", "FULL_COLOR_PRODUCTION_ROW_RESERVATION", 20),
    ("column", "FULL_COLOR_PRODUCTION_COLUMN_RESERVATION", 18),
    ("movement-row", "FULL_COLOR_PRODUCTION_MOVEMENT_ROW_RESERVATION", 40),
    ("movement-column", "FULL_COLOR_PRODUCTION_MOVEMENT_COLUMN_RESERVATION", 36),
    ("connection", "FULL_COLOR_PRODUCTION_CONNECTION_RESERVATION", 40),
    ("load", "FULL_COLOR_PRODUCTION_RECTANGLE_RESERVATION", 360),
    ("third-screen", "FULL_COLOR_PRODUCTION_THIRD_SCREEN_RESERVATION", 120),
    ("alternate-bg", "FULL_COLOR_PRODUCTION_RECTANGLE_RESERVATION", 360),
    ("animation", "FULL_COLOR_PRODUCTION_ANIMATION_RESERVATION", 17),
    ("oam", "FULL_COLOR_PRODUCTION_OAM_RESERVATION", 160),
)


@pytest.mark.parametrize("case", SCHEDULER_CASES)
@pytest.mark.parametrize("threshold_delta", (0, -1))
def test_every_actual_scheduler_edge_commits_exact_fit_and_defers_threshold_plus_one(
    timing_rom: Phase2Rom,
    case: tuple[str, str, int],
    threshold_delta: int,
) -> None:
    rom = timing_rom
    kind, budget_name, extent = case
    constants = _generated_constants()
    reservation = constants[budget_name]
    source = 0xC800
    source_extent = extent * 2 if kind in {
        "row", "column", "movement-row", "movement-column", "connection",
        "load", "third-screen", "alternate-bg",
    } else extent
    rom.write_fixed(
        source,
        bytes((index * 37 + 11) & 0xEF for index in range(source_extent)),
    )
    assert enqueue_timing_producer(rom, kind, source)[0] == rom.constants["ACCEPTED"]
    available = reservation + threshold_delta
    rom.write_wram2("wFullColorCommitBudget", available.to_bytes(2, "little"))
    before = (
        rom.emulator.read_palette_ram(),
        rom.emulator.read_palette_ram(object_palettes=True),
        rom.emulator.read_vram_bank(0, 0x8000, 0x2000),
        rom.emulator.read_vram_bank(1, 0x8000, 0x2000),
        rom.emulator.read_memory(0xFE00, 160),
    )

    rom.call("RunFullColorOwnershipVBlank")

    transitions = rom.read_wram2("wFullColorTransitionLog", 8)
    if threshold_delta == 0:
        assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
        assert rom.constants["COMMITTING"] in transitions
    else:
        assert rom.read_wram2("wFullColorRequestCount") == b"\x01"
        assert rom.constants["COMMITTING"] not in transitions
        after = (
            rom.emulator.read_palette_ram(),
            rom.emulator.read_palette_ram(object_palettes=True),
            rom.emulator.read_vram_bank(0, 0x8000, 0x2000),
            rom.emulator.read_vram_bank(1, 0x8000, 0x2000),
            rom.emulator.read_memory(0xFE00, 160),
        )
        assert after == before


@pytest.mark.parametrize(
    ("context", "budget_name"),
    (
        ("RENDERER_CONTEXT_ORDINARY_MAP", "FULL_COLOR_TRANSITION_MAP_BUDGET"),
        ("RENDERER_CONTEXT_MENU", "FULL_COLOR_TRANSITION_MENU_BUDGET"),
        ("RENDERER_CONTEXT_DIALOGUE", "FULL_COLOR_TRANSITION_DIALOGUE_BUDGET"),
        ("RENDERER_CONTEXT_BATTLE", "FULL_COLOR_TRANSITION_BATTLE_BUDGET"),
    ),
)
@pytest.mark.parametrize("threshold_delta", (0, 1))
def test_yellow_transition_budget_rejects_plus_one_before_any_lifecycle_mutation(
    timing_rom: Phase2Rom,
    context: str,
    budget_name: str,
    threshold_delta: int,
) -> None:
    rom = timing_rom
    constants = _generated_constants()
    rom.write_wram2("wFullColorProductionReturnContext", bytes((rom.constants[context],)))
    rom.write_wram2(
        "wFullColorTransitionBudget",
        (constants[budget_name] + threshold_delta).to_bytes(2, "little"),
    )
    state_names = (
        "wRendererOwner", "wRendererPhase", "wRendererGeneration",
        "wRendererAdmissionOpen", "wRendererJobState",
        "wFullColorProductionTransitionStatus",
        "wFullColorProductionReconstructionLedger",
    )
    sizes = {"wRendererGeneration": 4, "wFullColorProductionReconstructionLedger": 2}
    before = tuple(rom.read_wram2(name, sizes.get(name, 1)) for name in state_names)
    before_palette = rom.emulator.read_palette_ram()
    before_vram = rom.emulator.read_vram_bank(0, 0x9800, 0x400)

    _, flags = rom.call("BeginForcedYellowPresentation")

    if threshold_delta == 0:
        assert not flags & 0x10
        assert rom.read_wram2("wRendererOwner") == bytes((rom.constants["RENDERER_YELLOW"],))
    else:
        assert flags & 0x10
        after = tuple(rom.read_wram2(name, sizes.get(name, 1)) for name in state_names)
        assert after == before
        assert rom.emulator.read_palette_ram() == before_palette
        assert rom.emulator.read_vram_bank(0, 0x9800, 0x400) == before_vram


@pytest.mark.parametrize("threshold_delta", (0, 1))
def test_color_map_transition_budget_is_checked_before_authority_snapshot(
    timing_rom: Phase2Rom,
    threshold_delta: int,
) -> None:
    rom = timing_rom
    constants = _generated_constants()
    rom.write_wram2("wRendererOwner", bytes((rom.constants["RENDERER_YELLOW"],)))
    rom.write_wram2("wRendererPhase", bytes((rom.constants["YELLOW_ACTIVE"],)))
    rom.write_wram2("wRendererAdmissionOpen", b"\x01")
    rom.write_wram2(
        "wFullColorTransitionBudget",
        (constants["FULL_COLOR_TRANSITION_COLOR_MAP_BUDGET"] + threshold_delta).to_bytes(2, "little"),
    )
    before = rom.read_wram2("wFullColorAuthoritySnapshot", 16)
    _, flags = rom.call("BeginFullColorMapEntry")
    if threshold_delta == 0:
        assert not flags & 0x10
        assert rom.read_wram2("wRendererOwner") == bytes((rom.constants["RENDERER_FULL_COLOR_OVERWORLD"],))
    else:
        assert flags & 0x10
        assert rom.read_wram2("wRendererOwner") == bytes((rom.constants["RENDERER_YELLOW"],))
        assert rom.read_wram2("wFullColorAuthoritySnapshot", 16) == before


@pytest.mark.parametrize(
    ("soft_reset", "budget_name"),
    (
        (0, "FULL_COLOR_TRANSITION_HARD_RESET_BUDGET"),
        (1, "FULL_COLOR_TRANSITION_SOFT_RESET_BUDGET"),
    ),
)
@pytest.mark.parametrize("threshold_delta", (0, 1))
def test_reset_transition_budget_rejects_plus_one_before_lifecycle_mutation(
    timing_rom: Phase2Rom,
    soft_reset: int,
    budget_name: str,
    threshold_delta: int,
) -> None:
    rom = timing_rom
    constants = _generated_constants()
    rom.emulator.pyboy.memory[rom.emulator.symbols["hSoftReset"]] = soft_reset
    rom.write_wram2(
        "wFullColorTransitionBudget",
        (constants[budget_name] + threshold_delta).to_bytes(2, "little"),
    )
    state_names = (
        "wRendererOwner", "wRendererPhase", "wRendererGeneration",
        "wRendererAdmissionOpen", "wRendererJobState",
        "wFullColorProductionTransitionStatus",
        "wFullColorProductionReconstructionLedger",
    )
    sizes = {"wRendererGeneration": 4, "wFullColorProductionReconstructionLedger": 2}
    before = tuple(rom.read_wram2(name, sizes.get(name, 1)) for name in state_names)
    before_palette = rom.emulator.read_palette_ram()
    before_vram = rom.emulator.read_vram_bank(0, 0x9800, 0x400)

    _, flags = rom.call("ResetRendererOwnershipForReconstruction")

    if threshold_delta == 0:
        assert not flags & 0x10
        assert rom.read_wram2("wRendererOwner") == bytes((rom.constants["RENDERER_YELLOW"],))
    else:
        assert flags & 0x10
        after = tuple(rom.read_wram2(name, sizes.get(name, 1)) for name in state_names)
        assert after == before
        assert rom.emulator.read_palette_ram() == before_palette
        assert rom.emulator.read_vram_bank(0, 0x9800, 0x400) == before_vram


def test_exact_descriptor_authority_rejects_cancelling_field_mutations(
    timing_rom: Phase2Rom,
) -> None:
    rom = timing_rom
    constants = _generated_constants()
    source = 0xC800
    rom.write_fixed(source, bytes(range(40)))
    descriptor = rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_ROW_PAIRED",
        destination=0x9800,
        source=source,
        desired=0x0114,
        extent=20,
        reservation=constants["FULL_COLOR_PRODUCTION_ROW_RESERVATION"],
    )
    assert rom.admit(descriptor)[0] == rom.constants["ACCEPTED"]
    resident = bytearray(rom.read_wram2("wFullColorRequestDescriptors", 20))
    # This pair preserves an 8-bit additive checksum. Exact parallel authority
    # must still reject it before COMMITTING or any visible destination write.
    resident[6] = (resident[6] + 1) & 0xFF
    resident[7] = (resident[7] - 1) & 0xFF
    rom.write_wram2("wFullColorRequestDescriptors", resident)
    before = rom.emulator.read_vram_bank(0, 0x9800, 0x400)
    rom.write_wram2("wFullColorCommitBudget", (0xFFFE).to_bytes(2, "little"))

    rom.call("RunFullColorOwnershipVBlank")

    assert rom.constants["COMMITTING"] not in rom.read_wram2("wFullColorTransitionLog", 8)
    assert rom.read_wram2("wFullColorRequestCount") == b"\x00"
    assert rom.emulator.read_vram_bank(0, 0x9800, 0x400) == before
