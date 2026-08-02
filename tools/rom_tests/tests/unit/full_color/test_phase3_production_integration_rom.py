"""Bounded real-ROM proof for the Phase 3 production integration roots.

The lower-level Phase 2 suites prove the lifecycle and scheduler contracts in
isolation.  These checks start at the Yellow production labels named by the
audit inventory and stop only at a later production boundary.  Hooks bound
boot-, audio-, and input-dependent work; lifecycle and presentation code runs
from the linked audit ROM.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pytest

from tools.rom_tests.tests.unit.full_color.test_phase2_guarded_runtime_rom import (
    _assert_reconstructed_visible_state,
    _set_wram1_word,
)
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    phase2_rom as _phase2_rom,  # noqa: F401 - registered by pytest
)


IE = 0xFFFF
IF = 0xFF0F
RSVBK = 0xFF70
RVBK = 0xFF4F
RUN_TRAMPOLINE = 0xFF90
HALT_LOOP = 0xC6F0
ENTRY_SP = 0xCFFE
ENTRY_IE = 0x15
ENTRY_IF = 0x1A


@pytest.fixture(name="phase2_rom")
def phase2_rom_fixture(request: pytest.FixtureRequest) -> Phase2Rom:
    return request.getfixturevalue("_phase2_rom")


@dataclass(frozen=True, slots=True)
class BoundaryState:
    events: tuple[str, ...]
    rom_bank: int
    wram_bank: int
    vram_bank: int
    sp: int
    ie: int
    interrupt_flags: int


def _return_from_hook(rom: Phase2Rom, action: Callable[[], None] | None = None):
    def callback(_: object) -> None:
        if action is not None:
            action()
        regs = rom.emulator.pyboy.register_file
        memory = rom.emulator.pyboy.memory
        low = memory[regs.SP]
        high = memory[(regs.SP + 1) & 0xFFFF]
        regs.SP = (regs.SP + 2) & 0xFFFF
        regs.PC = low | high << 8

    return callback


def _run_to_boundary(
    rom: Phase2Rom,
    entry: str,
    terminal: str,
    *,
    observe: Iterable[str] = (),
    stub_returns: dict[str, Callable[[], None] | None] | None = None,
    entry_rom_bank: int = 5,
    max_frames: int = 64,
) -> BoundaryState:
    """Run one linked production route with pending interrupts held by DI."""

    emu = rom.emulator.pyboy
    symbols = rom.emulator.symbols
    banks = rom.emulator.symbol_banks
    regs = emu.register_file
    memory = emu.memory
    events: list[str] = []
    terminal_state: BoundaryState | None = None
    hooks: list[tuple[int, int]] = []

    def register(name: str, callback: Callable[[object], None]) -> None:
        key = (banks[name], symbols[name])
        emu.hook_register(*key, callback, name)
        hooks.append(key)

    observed = tuple(observe)
    stubs = stub_returns or {}
    for name in observed:
        if name in stubs:
            continue
        register(name, lambda _context, label=name: events.append(label))
    for name, action in stubs.items():
        if name in observed:

            def observed_action(label: str = name, inner=action) -> None:
                events.append(label)
                if inner is not None:
                    inner()

            register(name, _return_from_hook(rom, observed_action))
        else:
            register(name, _return_from_hook(rom, action))

    def stop(_: object) -> None:
        nonlocal terminal_state
        events.append(terminal)
        terminal_state = BoundaryState(
            events=tuple(events),
            rom_bank=memory[symbols["hLoadedROMBank"]],
            wram_bank=(memory[RSVBK] & 7) or 1,
            vram_bank=memory[RVBK] & 1,
            sp=regs.SP,
            ie=memory[IE],
            interrupt_flags=memory[IF],
        )
        memory[IE] = 0
        memory[HALT_LOOP] = 0x18
        memory[HALT_LOOP + 1] = 0xFE
        regs.PC = HALT_LOOP

    register(terminal, stop)
    memory[0x2000] = entry_rom_bank
    memory[symbols["hLoadedROMBank"]] = entry_rom_bank
    memory[RSVBK] = 6
    memory[RVBK] = 1
    memory[IE] = ENTRY_IE
    memory[IF] = ENTRY_IF
    memory[ENTRY_SP] = 0
    memory[ENTRY_SP + 1] = 1
    regs.SP = ENTRY_SP
    memory[RUN_TRAMPOLINE] = 0xF3  # DI
    memory[RUN_TRAMPOLINE + 1] = 0xC3  # JP entry
    memory[RUN_TRAMPOLINE + 2] = symbols[entry] & 0xFF
    memory[RUN_TRAMPOLINE + 3] = symbols[entry] >> 8
    if banks[entry]:
        memory[0x2000] = banks[entry]
        memory[symbols["hLoadedROMBank"]] = banks[entry]
    regs.PC = RUN_TRAMPOLINE
    try:
        for _ in range(max_frames):
            emu.tick(1, render=False, sound=False)
            if terminal_state is not None:
                break
    finally:
        for bank, address in reversed(hooks):
            emu.hook_deregister(bank, address)
    assert terminal_state is not None, (
        f"{entry} did not reach {terminal}; PC={regs.PC:#06x}, SP={regs.SP:#06x}, "
        f"events={events[-8:]}"
    )
    return terminal_state


def _stub_map_authority_loaders() -> dict[str, None]:
    return {
        "ResetMapVariables": None,
        "LoadTextBoxTilePatterns": None,
        "LoadMapHeader": None,
        "InitMapSprites": None,
        "LoadScreenRelatedData": None,
        "UpdateMusic6Times": None,
        "PlayDefaultMusicFadeOutCurrent": None,
    }


def _assert_owned_active(rom: Phase2Rom) -> None:
    assert rom.read_wram2("wRendererOwner") == bytes(
        (rom.constants["RENDERER_FULL_COLOR_OVERWORLD"],)
    )
    assert rom.read_wram2("wRendererPhase") == bytes(
        (rom.constants["OVERWORLD_ACTIVE"],)
    )
    assert rom.read_wram2("wRendererAdmissionOpen") == b"\x01"


def test_enter_map_and_load_map_data_reach_one_authoritative_reconstruction(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C  # ROUTE_1
    emu.memory[phase2_rom.emulator.symbols["wCurMapTileset"]] = 3
    emu.memory[phase2_rom.emulator.symbols["wYCoord"]] = 9
    emu.memory[phase2_rom.emulator.symbols["wXCoord"]] = 13
    emu.memory[phase2_rom.emulator.symbols["wStatusFlags7"]] = 1 << 1
    emu.memory[0xFF40] &= 0x7F
    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9820)
    tiles = bytes((index * 17 + 9) & 0xFF for index in range(20 * 18))
    phase2_rom.write_fixed(phase2_rom.emulator.symbols["wTileMap"], tiles)
    for symbol in (
        "hAutoBGTransferEnabled",
        "hVBlankCopyBGSource",
        "hVBlankCopyBGNumRows",
        "hVBlankCopySize",
        "hVBlankCopyDoubleSize",
        "hRedrawRowOrColumnMode",
    ):
        emu.memory[phase2_rom.emulator.symbols[symbol]] = 0xA5

    map_stubs = _stub_map_authority_loaders()
    map_stubs["ClearVariablesOnEnterMap"] = None
    state = _run_to_boundary(
        phase2_rom,
        "EnterMap",
        "EnterMap.skipGivingThreeStepsOfNoRandomBattles",
        observe=(
            "BeginFullColorMapEntry",
            "LoadMapData",
            "SnapshotFullColorMapAuthority",
            "ReconstructFullColorMapEntry",
        ),
        stub_returns=map_stubs,
    )

    assert state.events == (
        "BeginFullColorMapEntry",
        "SnapshotFullColorMapAuthority",
        "LoadMapData",
        "SnapshotFullColorMapAuthority",
        "ReconstructFullColorMapEntry",
        "EnterMap.skipGivingThreeStepsOfNoRandomBattles",
    )
    _assert_owned_active(phase2_rom)
    assert phase2_rom.read_wram2("wFullColorDebugReconstructionState")[0] == 1
    assert phase2_rom.read_wram2("wFullColorAuthoritySnapshot", 4) == bytes(
        (
            0x0C,
            3,
            9,
            13,
        )
    )
    _assert_reconstructed_visible_state(phase2_rom, tiles, destination=0x9820)
    for symbol in (
        "hAutoBGTransferEnabled",
        "hVBlankCopyBGSource",
        "hVBlankCopyBGNumRows",
        "hVBlankCopySize",
        "hVBlankCopyDoubleSize",
        "hRedrawRowOrColumnMode",
    ):
        assert emu.memory[phase2_rom.emulator.symbols[symbol]] == 0
    assert (state.rom_bank, state.wram_bank, state.vram_bank) == (5, 6, 1)
    assert state.sp == ENTRY_SP
    assert (state.ie, state.interrupt_flags) == (ENTRY_IE, ENTRY_IF)


@pytest.mark.parametrize(
    ("wrapper", "integration", "request_class", "destination"),
    (
        (
            "ScheduleSouthRowRedraw",
            "FullColorAuditScheduleMovementRow",
            "FULL_COLOR_REQUEST_MAP_ROW_PAIRED",
            0x9800,
        ),
        (
            "ScheduleEastColumnRedraw",
            "FullColorAuditScheduleMovementColumn",
            "FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED",
            0x9812,
        ),
        (
            "ScheduleWestColumnRedraw",
            "FullColorAuditScheduleMovementColumn",
            "FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED",
            0x9800,
        ),
    ),
)
def test_production_movement_redraw_wrappers_commit_exact_paired_units(
    phase2_rom: Phase2Rom,
    wrapper: str,
    integration: str,
    request_class: str,
    destination: int,
) -> None:
    emu = phase2_rom.emulator.pyboy
    _set_wram1_word(
        phase2_rom, "wMapViewVRAMPointer", 0x9600 if "South" in wrapper else 0x9800
    )
    tile_map = phase2_rom.emulator.symbols["wTileMap"]
    source = bytes((index * 7 + 3) & 0xFF for index in range(20 * 18))
    phase2_rom.write_fixed(tile_map, source)
    seen: list[str] = []
    bank = phase2_rom.emulator.symbol_banks[integration]
    address = phase2_rom.emulator.symbols[integration]
    emu.hook_register(bank, address, lambda _context: seen.append(integration), None)
    try:
        _, flags = phase2_rom.call(wrapper)
    finally:
        emu.hook_deregister(bank, address)

    assert flags & 0x10 == 0
    assert seen == [integration]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x01"
    assert (
        phase2_rom.read_wram2("wFullColorRequestDescriptors")[0] & 0x0F
    ) == phase2_rom.constants[request_class]
    frozen = phase2_rom.read_wram2(
        "wFullColorProducerTiles", 40 if "South" in wrapper else 36
    )
    phase2_rom.write_fixed(tile_map, b"\xee" * len(source))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    if "South" in wrapper:
        expected = source[16 * 20 : 18 * 20]
        for row in range(2):
            row_data = expected[row * 20 : (row + 1) * 20]
            assert (
                phase2_rom.emulator.read_vram_bank(0, destination + row * 32, 20)
                == row_data
            )
            assert phase2_rom.emulator.read_vram_bank(
                1, destination + row * 32, 20
            ) == bytes(value & 7 for value in row_data)
    else:
        column = 18 if "East" in wrapper else 0
        expected = b"".join(
            source[row * 20 + column : row * 20 + column + 2] for row in range(18)
        )
        for row in range(18):
            pair = expected[row * 2 : row * 2 + 2]
            assert (
                phase2_rom.emulator.read_vram_bank(0, destination + row * 32, 2) == pair
            )
            assert phase2_rom.emulator.read_vram_bank(
                1, destination + row * 32, 2
            ) == bytes(value & 7 for value in pair)
    assert frozen == expected


def test_production_north_connection_uses_connection_request_not_legacy_redraw(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0  # PALLET_TOWN
    emu.memory[phase2_rom.emulator.symbols["wYCoord"]] = 0
    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9800)
    source = bytes((index * 5 + 1) & 0xFF for index in range(40))
    phase2_rom.write_fixed(phase2_rom.emulator.symbols["wTileMap"], source)
    emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] = 0xA5
    seen: list[str] = []
    name = "FullColorAuditScheduleNorthRow"
    bank, address = (
        phase2_rom.emulator.symbol_banks[name],
        phase2_rom.emulator.symbols[name],
    )
    emu.hook_register(bank, address, lambda _context: seen.append(name), None)
    try:
        _, flags = phase2_rom.call("ScheduleNorthRowRedraw")
    finally:
        emu.hook_deregister(bank, address)
    assert flags & 0x10 == 0
    assert seen == [name]
    assert (
        phase2_rom.read_wram2("wFullColorRequestDescriptors")[0] & 0x0F
    ) == phase2_rom.constants["FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED"]
    assert emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] == 0
    phase2_rom.call("RunFullColorOwnershipVBlank")
    for row in range(2):
        expected = source[row * 20 : (row + 1) * 20]
        assert phase2_rom.emulator.read_vram_bank(0, 0x9800 + row * 32, 20) == expected
        assert phase2_rom.emulator.read_vram_bank(1, 0x9800 + row * 32, 20) == bytes(
            value & 7 for value in expected
        )


def test_display_text_id_enters_overlay_and_enqueues_bg1_authority_before_text(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["hTextID"]] = 1
    emu.memory[symbols["wCurMapTextPtr"]] = 0x00
    emu.memory[symbols["wCurMapTextPtr"] + 1] = 0xC9
    phase2_rom.write_fixed(0xC900, b"\x10\xc9")
    phase2_rom.write_fixed(0xC910, b"\x00")
    state = _run_to_boundary(
        phase2_rom,
        "DisplayTextID",
        "PrintText_NoCreatingTextBox",
        observe=(
            "DisplayTextIDInit",
            "EnterFullColorOverlay",
            "EnqueueFullColorWindowTileMapOverlayFar",
        ),
        entry_rom_bank=4,
    )

    assert state.events == (
        "DisplayTextIDInit",
        "EnterFullColorOverlay",
        "EnqueueFullColorWindowTileMapOverlayFar",
        "PrintText_NoCreatingTextBox",
    )
    assert phase2_rom.read_wram2("wRendererPhase") == bytes(
        (phase2_rom.constants["OVERWORLD_OVERLAY"],)
    )
    authority = bytes(
        emu.memory[symbols["wTileMap"] + index] for index in range(20 * 18)
    )
    phase2_rom.call("RunFullColorOwnershipVBlank")
    for row in range(18):
        expected = authority[row * 20 : (row + 1) * 20]
        assert phase2_rom.emulator.read_vram_bank(0, 0x9C00 + row * 32, 20) == expected
        assert phase2_rom.emulator.read_vram_bank(1, 0x9C00 + row * 32, 20) == bytes(
            value & 7 for value in expected
        )


def test_display_start_menu_reaches_guarded_start_overlay_before_input(
    phase2_rom: Phase2Rom,
) -> None:
    symbols = phase2_rom.emulator.symbols
    menu = bytes((index * 23 + 11) & 0xFF for index in range(20 * 18))

    def draw_menu() -> None:
        phase2_rom.write_fixed(symbols["wTileMap"], menu)

    state = _run_to_boundary(
        phase2_rom,
        "DisplayStartMenu",
        "FullColorHandleStartMenuInput",
        observe=(
            "FullColorStartMenuReveal",
            "EnqueueFullColorStartMenuOverlay",
            "EnqueueFullColorWindowTileMapOverlayFar",
        ),
        stub_returns={
            "PlaySound": None,
            "DrawStartMenu": draw_menu,
            "PrintSafariZoneSteps": None,
            "UpdateSprites": None,
        },
        entry_rom_bank=4,
    )
    assert state.events == (
        "FullColorStartMenuReveal",
        "EnqueueFullColorStartMenuOverlay",
        "EnqueueFullColorWindowTileMapOverlayFar",
        "FullColorHandleStartMenuInput",
    )
    assert (
        phase2_rom.read_wram2("wFullColorRequestDescriptors")[0] & 0x0F
    ) == phase2_rom.constants["FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9C00, 20) == menu[:20]


def test_party_production_entry_and_concrete_exit_reconstruct_authoritative_map(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    emu.memory[symbols["wCurMap"]] = 0x0C
    for symbol in (
        "hAutoBGTransferEnabled",
        "hVBlankCopySize",
        "hRedrawRowOrColumnMode",
    ):
        emu.memory[symbols[symbol]] = 0xA5

    entry = _run_to_boundary(
        phase2_rom,
        "DisplayPartyMenu",
        "PartyMenuInit",
        observe=("EnsureFullColorPartyHandoff",),
        stub_returns={"GBPalWhiteOutWithDelay3": None, "ClearSprites": None},
        entry_rom_bank=4,
    )
    assert entry.events == ("EnsureFullColorPartyHandoff", "PartyMenuInit")
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\x01"
    for symbol in (
        "hAutoBGTransferEnabled",
        "hVBlankCopySize",
        "hRedrawRowOrColumnMode",
    ):
        assert emu.memory[symbols[symbol]] == 0

    tiles = bytes((index * 29 + 5) & 0xFF for index in range(20 * 18))
    phase2_rom.write_fixed(symbols["wTileMap"], tiles)
    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9800)
    emu.memory[symbols["wStatusFlags7"]] = 1 << 1
    emu.memory[0xFF40] &= 0x7F
    generation = phase2_rom.generation
    exit_state = _run_to_boundary(
        phase2_rom,
        "StartMenu_Pokemon.exitMenu",
        "RedisplayStartMenu",
        observe=(
            "ReturnFullColorFromParty",
            "LoadMapData",
            "SnapshotFullColorMapAuthority",
            "ReconstructFullColorMapEntry",
        ),
        stub_returns={
            "GBPalWhiteOutWithDelay3": None,
            **_stub_map_authority_loaders(),
        },
        entry_rom_bank=4,
    )
    assert exit_state.events == (
        "ReturnFullColorFromParty",
        "SnapshotFullColorMapAuthority",
        "LoadMapData",
        "SnapshotFullColorMapAuthority",
        "ReconstructFullColorMapEntry",
        "RedisplayStartMenu",
    )
    assert phase2_rom.generation == generation + 1
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\0"
    assert phase2_rom.read_wram2("wFullColorDebugReconstructionState")[0] == 1
    _assert_owned_active(phase2_rom)
    _assert_reconstructed_visible_state(phase2_rom, tiles)
    assert (exit_state.rom_bank, exit_state.wram_bank, exit_state.vram_bank) == (
        4,
        6,
        1,
    )
    assert exit_state.sp == ENTRY_SP
    assert (exit_state.ie, exit_state.interrupt_flags) == (ENTRY_IE, ENTRY_IF)
