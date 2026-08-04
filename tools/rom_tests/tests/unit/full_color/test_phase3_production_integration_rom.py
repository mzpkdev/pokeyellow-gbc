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

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT
from tools.rom_tests.tests.unit.full_color.test_phase2_guarded_runtime_rom import (
    _set_wram1_word,
)
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _linked_overworld_tile_attributes,
    phase2_rom as _phase2_rom,  # noqa: F401 - registered by pytest
)
from tools.rom_tests.tests.unit.full_color.test_phase2_vblank_routing_rom import (
    _run_actual_vblank,
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
BOOTROM_DISABLE = 0xFF50


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
    # Direct-call fixtures bypass boot. Unmap it so fixed-bank production
    # routines below $0100 (notably DisableLCD/EnableLCD) are cartridge code.
    memory[BOOTROM_DISABLE] = 1
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


def test_production_player_graphics_uses_lcd_safe_copy_path() -> None:
    overworld = (REPOSITORY_ROOT / "home/overworld.asm").read_text()
    routine = overworld.split("LoadPlayerSpriteGraphicsCommon::", 1)[1].split(
        "; function to load data from the map header", 1
    )[0]
    assert routine.count("IF FULL_COLOR_PRODUCTION_ACTIVATED") == 2
    assert routine.count("CopyVideoDataAlternate") == 2
    assert routine.count("CopyVideoData") == 4


def test_load_map_data_runs_yellow_palette_then_passive_publish_before_enable(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C  # ROUTE_1
    emu.memory[0xFF40] |= 0x80
    tiles = bytes((index * 17 + 9) & 0xFF for index in range(32 * 32))
    for offset, value in enumerate(tiles):
        emu.memory[0x9800 + offset] = value

    def disable_lcd() -> None:
        emu.memory[0xFF40] &= 0x7F

    def enable_lcd() -> None:
        emu.memory[0xFF40] |= 0x80

    state = _run_to_boundary(
        phase2_rom,
        "LoadMapData",
        "LoadPlayerSpriteGraphics",
        observe=("DisableLCD", "RunPaletteCommand", "PassiveFullColorApplyMap", "EnableLCD"),
        stub_returns={
            "DisableLCD": disable_lcd,
            "ResetMapVariables": None,
            "LoadTextBoxTilePatterns": None,
            "LoadMapHeader": None,
            "InitMapSprites": None,
            "LoadScreenRelatedData": None,
            "CopyMapViewToVRAM": None,
            "RunPaletteCommand": None,
            "EnableLCD": enable_lcd,
        },
    )

    assert state.events == (
        "DisableLCD",
        "RunPaletteCommand",
        "PassiveFullColorApplyMap",
        "EnableLCD",
        "LoadPlayerSpriteGraphics",
    )
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    attributes = _linked_overworld_tile_attributes(phase2_rom)
    assert phase2_rom.emulator.read_vram_bank(0, 0x9800, 32 * 32) == tiles
    assert phase2_rom.emulator.read_vram_bank(1, 0x9800, 32 * 32) == bytes(
        attributes[tile] for tile in tiles
    )


@pytest.mark.parametrize(
    ("wrapper", "mode", "destination"),
    (
        (
            "ScheduleSouthRowRedraw",
            2,
            0x9800,
        ),
        (
            "ScheduleEastColumnRedraw",
            1,
            0x9812,
        ),
        (
            "ScheduleWestColumnRedraw",
            1,
            0x9800,
        ),
    ),
)
def test_production_movement_keeps_yellow_request_and_no_scheduler_handoff(
    phase2_rom: Phase2Rom,
    wrapper: str,
    mode: int,
    destination: int,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _set_wram1_word(
        phase2_rom, "wMapViewVRAMPointer", 0x9600 if "South" in wrapper else 0x9800
    )
    tile_map = phase2_rom.emulator.symbols["wTileMap"]
    source = bytes((index * 7 + 3) & 0xFF for index in range(20 * 18))
    phase2_rom.write_fixed(tile_map, source)
    phase2_rom.call(wrapper)

    assert emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] == mode
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"
    _run_actual_vblank(phase2_rom)
    attributes = _linked_overworld_tile_attributes(phase2_rom)
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
            ) == bytes(attributes[value] for value in row_data)
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
            ) == bytes(attributes[value] for value in pair)
    assert emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] == 0


def test_connected_map_transition_is_disable_yellow_command_publish_enable(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] |= 0x80
    tiles = bytes((index * 5 + 1) & 0xFF for index in range(32 * 32))
    for offset, value in enumerate(tiles):
        emu.memory[0x9800 + offset] = value

    def disable_lcd() -> None:
        emu.memory[0xFF40] &= 0x7F

    def enable_lcd() -> None:
        emu.memory[0xFF40] |= 0x80

    state = _run_to_boundary(
        phase2_rom,
        "CheckMapConnections.loadNewMap",
        "OverworldLoopLessDelay",
        observe=("DisableLCD", "RunPaletteCommand", "PassiveFullColorApplyMap", "EnableLCD"),
        stub_returns={
            "DisableLCD": disable_lcd,
            "LoadMapHeader": None,
            "PlayDefaultMusicFadeOutCurrent": None,
            "RunPaletteCommand": None,
            "EnableLCD": enable_lcd,
            "InitMapSprites": None,
            "LoadTileBlockMap": None,
        },
        entry_rom_bank=0,
    )
    assert state.events == (
        "DisableLCD",
        "RunPaletteCommand",
        "PassiveFullColorApplyMap",
        "EnableLCD",
        "OverworldLoopLessDelay",
    )
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_overworld_palette_change_detector_schedules_passive_vblank_refresh(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    def yellow_changes_palette() -> None:
        prior = emu.memory[0xFF68]
        emu.memory[0xFF68] = 0
        emu.memory[0xFF69] = 0
        emu.memory[0xFF68] = prior

    state = _run_to_boundary(
        phase2_rom,
        "OverworldLoopLessDelay",
        "HandleMidJump",
        observe=("PassiveFullColorHandleConnection",),
        stub_returns={
            "DelayFrame": None,
            "IsSurfingPikachuInParty": None,
            "LoadGBPal": yellow_changes_palette,
        },
        entry_rom_bank=0,
    )

    assert state.events == ("PassiveFullColorHandleConnection", "HandleMidJump")
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x01"
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_display_text_id_uses_yellow_video_without_overlay_handoff(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["hTextID"]] = 1
    state = _run_to_boundary(
        phase2_rom,
        "DisplayTextIDInit",
        "CopyScreenTileBufferToVRAM",
        observe=("EnterFullColorOverlay", "EnqueueFullColorWindowTileMapOverlayFar"),
        stub_returns={"TextBoxBorder": None, "UpdateSprites": None},
        entry_rom_bank=4,
    )

    assert state.events == ("CopyScreenTileBufferToVRAM",)
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_display_start_menu_reaches_yellow_input_without_overlay_request(
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
        "FullColorHandleStartMenuInput",
    )
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_party_production_entry_and_exit_remain_yellow_owned(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    emu.memory[symbols["wCurMap"]] = 0x0C
    phase2_rom.call("InitRendererOwnership")

    entry = _run_to_boundary(
        phase2_rom,
        "DisplayPartyMenu",
        "PartyMenuInit",
        observe=("EnsureFullColorPartyHandoff",),
        stub_returns={"GBPalWhiteOutWithDelay3": None, "ClearSprites": None},
        entry_rom_bank=4,
    )
    assert entry.events == ("PartyMenuInit",)
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\x00"
    generation = phase2_rom.generation
    exit_state = _run_to_boundary(
        phase2_rom,
        "StartMenu_Pokemon.exitMenu",
        "RedisplayStartMenu",
        observe=(
            "ReturnFullColorFromParty",
        ),
        stub_returns={
            "GBPalWhiteOutWithDelay3": None,
            "RestoreScreenTilesAndReloadTilePatterns": None,
            "LoadGBPal": None,
        },
        entry_rom_bank=4,
    )
    assert exit_state.events == ("RedisplayStartMenu",)
    assert phase2_rom.generation == generation
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\0"
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert exit_state.sp == ENTRY_SP
    assert (exit_state.ie, exit_state.interrupt_flags) == (ENTRY_IE, ENTRY_IF)
