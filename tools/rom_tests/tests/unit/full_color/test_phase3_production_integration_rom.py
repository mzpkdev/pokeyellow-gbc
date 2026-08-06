"""Bounded real-ROM proof for shipped passive-renderer integration roots.

The lower-level Phase 2 suites prove the lifecycle and scheduler contracts in
isolation.  These checks start at the Yellow production labels named by the
audit inventory and stop only at a later production boundary. Hooks bound
boot-, audio-, and input-dependent work while presentation code runs from each
shipped normal, debug, and VC product.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.unit.full_color.test_phase2_guarded_runtime_rom import (
    _set_wram1_word,
)
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _linked_overworld_tile_attributes,
    numeric_symbols,
)
from tools.rom_tests.tests.unit.full_color.test_phase2_vblank_routing_rom import (
    _run_actual_vblank,
)
from tools.rom_tests.tests.unit.full_color.test_passive_overworld_rom import (
    _apply_dmg_palette_mapping,
    _linked_palette_entry,
    _linked_overworld_bg_palettes,
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
RBGP = 0xFF47
YELLOW_NORMAL_BGP = 0xE4
VBLANK_INTERRUPT = 1 << 0
VBG_MAP_1 = 0x9800
PASSIVE_OVERLAY_COMPLETE = 1 << 5
PALLET_TOWN = 0
VIRIDIAN_CITY = 1
ROUTE_1 = 0x0C
POKECENTER_TILESET = 6
PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")


@pytest.fixture(name="phase2_rom", params=PRODUCTS)
def phase2_rom_fixture(request: pytest.FixtureRequest):
    product = request.param
    rom = REPOSITORY_ROOT / f"{product}.gbc"
    sym = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(
        rom=rom,
        symbols=sym,
        results=result_directory(request.node.nodeid) / product,
        cgb=True,
    )
    instance = Phase2Rom(emulator, numeric_symbols(sym))
    dma_stub = bytes(
        (0x3E, 0xC3, 0xE0, 0x46, 0x3E, 0x28, 0x3D, 0x20, 0xFD, 0xC9)
    )
    for offset, value in enumerate(dma_stub):
        emulator.pyboy.memory[0xFF80 + offset] = value
    try:
        yield instance
    finally:
        emulator.close()


@dataclass(frozen=True, slots=True)
class BoundaryState:
    events: tuple[str, ...]
    rom_bank: int
    wram_bank: int
    vram_bank: int
    sp: int
    return_address: int
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
    observe_actions: dict[str, Callable[[], None]] | None = None,
    stub_returns: dict[str, Callable[[], None] | None] | None = None,
    entry_rom_bank: int = 5,
    entry_wram_bank: int = 1,
    run_vblank_interrupts: bool = False,
    max_frames: int = 64,
) -> BoundaryState:
    """Run one linked production route, optionally including production VBlanks."""

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
    actions = observe_actions or {}
    stubs = stub_returns or {}
    for name in observed:
        if name in stubs:
            continue

        def observe_label(_context: object, label: str = name) -> None:
            events.append(label)
            action = actions.get(label)
            if action is not None:
                action()

        register(name, observe_label)
    for name, action in stubs.items():
        if name in observed:

            def observed_action(label: str = name, inner=action) -> None:
                events.append(label)
                observation = actions.get(label)
                if observation is not None:
                    observation()
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
            return_address=(
                memory[regs.SP] | memory[(regs.SP + 1) & 0xFFFF] << 8
            ),
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
    memory[RSVBK] = entry_wram_bank
    memory[RVBK] = 1
    memory[IE] = VBLANK_INTERRUPT if run_vblank_interrupts else ENTRY_IE
    memory[IF] = 0 if run_vblank_interrupts else ENTRY_IF
    memory[ENTRY_SP] = 0
    memory[ENTRY_SP + 1] = 1
    regs.SP = ENTRY_SP
    memory[RUN_TRAMPOLINE] = 0xFB if run_vblank_interrupts else 0xF3  # EI / DI
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


def _enable_production_overlay_video(rom: Phase2Rom) -> None:
    """Restore the LCD/transfer state established by Yellow's boot path."""

    emu = rom.emulator.pyboy
    symbols = rom.emulator.symbols
    emu.memory[symbols["hAutoBGTransferDest"]] = VBG_MAP_1 & 0xFF
    emu.memory[symbols["hAutoBGTransferDest"] + 1] = VBG_MAP_1 >> 8
    emu.memory[0xFF40] |= 0x80


def test_load_map_data_runs_yellow_palette_then_passive_publish_before_enable(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C  # ROUTE_1
    emu.memory[phase2_rom.emulator.symbols["wUnusedObtainedBadges"]] = 0
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
def test_production_movement_keeps_yellow_request_and_passive_mirror(
    phase2_rom: Phase2Rom,
    wrapper: str,
    mode: int,
    destination: int,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C
    emu.memory[phase2_rom.emulator.symbols["wUnusedObtainedBadges"]] = 0
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
    assert "wFullColorRequestCount" not in phase2_rom.emulator.symbols
    attributes = _linked_overworld_tile_attributes(phase2_rom)
    if "South" in wrapper:
        expected = source[16 * 20 : 18 * 20]
        redraw_addresses = tuple(
            destination + row * 32 + column
            for row in range(2)
            for column in range(20)
        )
    else:
        column = 18 if "East" in wrapper else 0
        expected = b"".join(
            source[row * 20 + column : row * 20 + column + 2] for row in range(18)
        )
        redraw_addresses = tuple(
            destination + row * 32 + offset
            for row in range(18)
            for offset in range(2)
        )

    def read_redraw(bank: int) -> bytes:
        return bytes(
            phase2_rom.emulator.read_vram_bank(bank, address, 1)[0]
            for address in redraw_addresses
        )

    bank1_before_yellow = read_redraw(1)
    assert phase2_rom.read_wram2(
        "wPassiveFullColorDeferredRedrawState"
    ) == bytes((0x80 | mode,))

    # Frame A is Yellow's operation: publish the exact tile strip to bank 0,
    # consume its HRAM request, and leave only the matching passive mirror due.
    _run_actual_vblank(phase2_rom)
    assert read_redraw(0) == expected
    assert read_redraw(1) == bank1_before_yellow
    assert emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] == 0
    assert phase2_rom.read_wram2(
        "wPassiveFullColorDeferredRedrawState"
    ) == bytes((mode,))

    # Frame B is redraw-free Yellow work plus the bank-1 mirror. It must not
    # disturb bank 0 and must retire the frozen record only after the exact
    # translated attribute strip has landed.
    _run_actual_vblank(phase2_rom)
    assert read_redraw(0) == expected
    assert read_redraw(1) == bytes(attributes[value] for value in expected)
    assert emu.memory[phase2_rom.emulator.symbols["hRedrawRowOrColumnMode"]] == 0
    assert phase2_rom.read_wram2("wPassiveFullColorDeferredRedrawState") == b"\x00"


def test_connected_map_transition_is_disable_yellow_command_publish_enable(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0x0C
    emu.memory[phase2_rom.emulator.symbols["wUnusedObtainedBadges"]] = 0
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
    assert "wFullColorRequestCount" not in phase2_rom.emulator.symbols


def test_active_color_connection_queues_new_map_palette_without_stock_handoff(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = PALLET_TOWN
    emu.memory[symbols["wCurMapTileset"]] = 0  # OVERWORLD
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    pallet_palettes = _linked_overworld_bg_palettes(
        phase2_rom, PALLET_TOWN, y_coord=0
    )
    viridian_palettes = _linked_overworld_bg_palettes(
        phase2_rom, VIRIDIAN_CITY, y_coord=0
    )
    assert phase2_rom.emulator.read_palette_ram() == pallet_palettes
    emu.memory[0xFF40] |= 0x80

    def load_viridian_header() -> None:
        emu.memory[symbols["wCurMap"]] = VIRIDIAN_CITY
        emu.memory[symbols["wCurMapTileset"]] = 0  # OVERWORLD

    state = _run_to_boundary(
        phase2_rom,
        "CheckMapConnections.loadNewMap",
        "OverworldLoopLessDelay",
        observe=(
            "DisableLCD",
            "RunPaletteCommand",
            "PassiveFullColorApplyMap",
            "EnableLCD",
            "LoadTileBlockMap",
            "PassiveFullColorHandleConnection",
        ),
        stub_returns={
            "LoadMapHeader": load_viridian_header,
            "PlayDefaultMusicFadeOutCurrent": None,
            "InitMapSprites": None,
            "LoadTileBlockMap": None,
        },
        entry_rom_bank=0,
    )

    assert state.events == (
        "LoadTileBlockMap",
        "PassiveFullColorHandleConnection",
        "OverworldLoopLessDelay",
    )
    assert emu.memory[0xFF40] & 0x80
    assert phase2_rom.emulator.read_palette_ram() == pallet_palettes
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x01"
    assert phase2_rom.read_wram2("wPassiveFullColorClearChunks") == b"\x00"

    _run_actual_vblank(phase2_rom)

    assert phase2_rom.emulator.read_palette_ram() == viridian_palettes
    assert viridian_palettes[6 * 8 + 2 : 6 * 8 + 6] != pallet_palettes[
        6 * 8 + 2 : 6 * 8 + 6
    ]
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"


def test_overworld_palette_guard_suppresses_steady_yellow_bg_publication(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    emu.memory[symbols["hOnCGB"]] = 1
    emu.memory[RSVBK] = 1
    emu.memory[symbols["wMapPalOffset"]] = 0
    emu.memory[symbols["wLastBGP"]] = 0
    expected_palette = phase2_rom.emulator.read_palette_ram()

    state = _run_to_boundary(
        phase2_rom,
        "OverworldLoopLessDelay",
        "HandleMidJump",
        observe=("TransferBGPPals", "PassiveFullColorHandleConnection"),
        stub_returns={
            "DelayFrame": None,
            "IsSurfingPikachuInParty": None,
        },
        entry_rom_bank=0,
    )

    # The active protected seam updates Yellow's BGP cache directly; it must
    # not enter the legacy four-palette hardware writer at all.
    assert state.events == ("HandleMidJump",)
    assert phase2_rom.emulator.read_palette_ram() == expected_palette
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorBGPaletteProtected") == b"\x00"
    assert "wFullColorRequestCount" not in phase2_rom.emulator.symbols


def test_overworld_palette_change_detector_ignores_unchanged_yellow_state(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    state = _run_to_boundary(
        phase2_rom,
        "OverworldLoopLessDelay",
        "HandleMidJump",
        observe=("PassiveFullColorHandleConnection",),
        stub_returns={
            "DelayFrame": None,
            "IsSurfingPikachuInParty": None,
            "LoadGBPal": None,
        },
        entry_rom_bank=0,
    )

    assert state.events == ("HandleMidJump",)
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"
    assert "wFullColorRequestCount" not in phase2_rom.emulator.symbols


def test_display_text_id_reaches_passive_overlay_after_yellow_finishes_window(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE
    emu.memory[symbols["hTextID"]] = 1
    state = _run_to_boundary(
        phase2_rom,
        "DisplayTextIDInit",
        "Delay3",
        observe=(
            "PassiveFullColorShouldColorOverlay",
            "LoadFontTilePatterns",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareTextOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={
            "TextBoxBorder": None,
            "UpdateSprites": None,
            "CopyScreenTileBufferToVRAM": None,
        },
        entry_rom_bank=4,
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "LoadFontTilePatterns",
        "PassiveFullColorPrepareTextOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"


def test_print_text_prepares_finalized_message_box_before_existing_delay(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "PrintText",
        "Delay3",
        observe=(
            "DisplayTextBoxID",
            "UpdateSprites",
            "PassiveFullColorPrepareTextOverlay",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={
            "DisplayTextBoxID": None,
            "UpdateSprites": None,
        },
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "DisplayTextBoxID",
        "UpdateSprites",
        "PassiveFullColorPrepareTextOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert symbols["PrintText_NoCreatingTextBox"] - symbols["PrintText"] == 0x10
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"


def test_print_text_overlay_seam_is_inert_outside_active_color_slice(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x33
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "PrintText",
        "Delay3",
        observe=(
            "DisplayTextBoxID",
            "UpdateSprites",
            "PassiveFullColorPrepareTextOverlay",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={
            "DisplayTextBoxID": None,
            "UpdateSprites": None,
        },
    )

    assert state.events == (
        "DisplayTextBoxID",
        "UpdateSprites",
        "PassiveFullColorPrepareTextOverlay",
        "PassiveFullColorShouldColorOverlay",
        "Delay3",
    )
    assert not emu.memory[symbols["hAutoBGTransferEnabled"]] & (
        PASSIVE_OVERLAY_COMPLETE | 1 << 7
    )


def test_forced_yellow_attribute_packet_suspends_print_text_projection(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    phase2_rom.call("LoadBGMapAttributes", c=5)  # party/full-screen packet
    _enable_production_overlay_video(phase2_rom)

    state = _run_to_boundary(
        phase2_rom,
        "PrintText",
        "Delay3",
        observe=(
            "DisplayTextBoxID",
            "UpdateSprites",
            "PassiveFullColorPrepareTextOverlay",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={"DisplayTextBoxID": None, "UpdateSprites": None},
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "DisplayTextBoxID",
        "UpdateSprites",
        "PassiveFullColorPrepareTextOverlay",
        "PassiveFullColorShouldColorOverlay",
        "Delay3",
    )
    assert phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended") == b"\x01"


def test_overlay_translation_admits_vblank_between_bounded_wram2_stores(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wCurMapTileset"]] = 0
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    state = _run_to_boundary(
        phase2_rom,
        "PassiveFullColorTranslateTileMap",
        "PassiveFullColorAttributeForTileWRAM1",
        run_vblank_interrupts=True,
    )

    assert state.events == ("PassiveFullColorAttributeForTileWRAM1",)
    assert state.ie == VBLANK_INTERRUPT
    assert state.wram_bank == 1


def test_redraw_map_view_pairs_each_yellow_row_with_passive_attributes(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wCurMapTileset"]] = 0
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    scoped_protection: list[tuple[bytes, bytes]] = []

    def observe_default_palette_command() -> None:
        scoped_protection.append(
            (
                phase2_rom.read_wram2("wPassiveFullColorBGPaletteProtected"),
                phase2_rom.read_wram2("wPassiveFullColorBGAttributesProtected"),
            )
        )

    state = _run_to_boundary(
        phase2_rom,
        "RedrawMapView",
        "DelayFrame",
        observe=(
            "LoadCurrentMapView",
            "PassiveFullColorRunDefaultPaletteCommand",
            "PassiveFullColorPrepareRedrawAttributes",
        ),
        stub_returns={
            "LoadCurrentMapView": None,
            "RunDefaultPaletteCommand": observe_default_palette_command,
        },
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "LoadCurrentMapView",
        "PassiveFullColorRunDefaultPaletteCommand",
        "PassiveFullColorPrepareRedrawAttributes",
        "DelayFrame",
    )
    assert scoped_protection == [(b"\x01", b"\x01")]
    assert phase2_rom.read_wram2("wPassiveFullColorBGPaletteProtected") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorBGAttributesProtected") == b"\x00"


def test_pokecenter_redisplay_hides_window_until_paired_attribute_publish(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x00
    emu.memory[symbols["wCurMapTileset"]] = POKECENTER_TILESET
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)

    state = _run_to_boundary(
        phase2_rom,
        "DisplayPokemonCenterDialogue_.notInParty",
        "Delay3",
        observe=(
            "LoadCurrentMapView",
            "PassiveFullColorRedisplayMapView",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={"LoadCurrentMapView": None},
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "LoadCurrentMapView",
        "PassiveFullColorRedisplayMapView",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert emu.memory[0xFF4A] == 144


def test_two_option_menu_prepares_finalized_structure_before_input_delay(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "DisplayTwoOptionMenu",
        "Delay3",
        observe=(
            "TextBoxBorder",
            "UpdateSprites",
            "PlaceString",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
            "PlaceMenuCursor",
        ),
        stub_returns={
            "TwoOptionMenu_SaveScreenTiles": None,
            "TextBoxBorder": None,
            "UpdateSprites": None,
            "PlaceString": None,
            "PlaceMenuCursor": None,
        },
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "TextBoxBorder",
        "UpdateSprites",
        "PlaceString",
        "PassiveFullColorShouldColorOverlay",
        "PlaceMenuCursor",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert emu.memory[0xFF4A] == 144


def test_two_option_menu_restoration_rebuilds_attributes_before_tile_sweep(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "TwoOptionMenu_RestoreScreenTiles",
        "Delay3",
        observe=(
            "UpdateSprites",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={"UpdateSprites": None},
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "UpdateSprites",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert emu.memory[0xFF4A] == 144


def test_two_option_menu_restoration_keeps_stock_timing_outside_color_slice(
    phase2_rom: Phase2Rom,
) -> None:
    state = _run_to_boundary(
        phase2_rom,
        "TwoOptionMenu_RestoreScreenTiles",
        "TwoOptionMenu_RestoreScreenTiles.restored",
        observe=(
            "UpdateSprites",
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "Delay3",
        ),
        stub_returns={"UpdateSprites": None},
    )

    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "UpdateSprites",
        "PassiveFullColorShouldColorOverlay",
        "TwoOptionMenu_RestoreScreenTiles.restored",
    )


def test_display_start_menu_reaches_passive_overlay_after_yellow_draw(
    phase2_rom: Phase2Rom,
) -> None:
    symbols = phase2_rom.emulator.symbols
    menu = bytes((index * 23 + 11) & 0xFF for index in range(20 * 18))

    def draw_menu() -> None:
        phase2_rom.write_fixed(symbols["wTileMap"], menu)

    phase2_rom.call("InitRendererOwnership")
    phase2_rom.emulator.pyboy.memory[symbols["wCurMap"]] = 0x0C
    phase2_rom.emulator.pyboy.memory[symbols["wUnusedObtainedBadges"]] = 0
    phase2_rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    phase2_rom.emulator.pyboy.memory[
        symbols["hAutoBGTransferEnabled"]
    ] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "DisplayStartMenu",
        "HandleMenuInput_.loop2",
        observe=(
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "FullColorStartMenuReveal",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={
            "PlaySound": None,
            "DrawStartMenu": draw_menu,
            "PrintSafariZoneSteps": None,
            "UpdateSprites": None,
            "Delay3": None,
        },
        entry_rom_bank=4,
        run_vblank_interrupts=True,
    )
    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "FullColorStartMenuReveal",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "HandleMenuInput_.loop2",
    )
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"


@pytest.mark.parametrize(
    ("entry", "expected_events"),
    (
        (
            "RedisplayStartMenu",
            (
                "PassiveFullColorResumeOverlays",
                "PassiveFullColorRestoreInvalidatedPalettes",
                "DrawStartMenu",
                "PassiveFullColorInvalidateOverlayAttributes",
                "PassiveFullColorPrepareMenuOverlay",
                "Delay3",
                "HandleMenuInput_.loop2",
            ),
        ),
        (
            "RedisplayStartMenu_DoNotDrawStartMenu",
            (
                "PassiveFullColorResumeOverlays",
                "PassiveFullColorRestoreInvalidatedPalettes",
                "PassiveFullColorInvalidateOverlayAttributes",
                "PassiveFullColorPrepareMenuOverlay",
                "Delay3",
                "HandleMenuInput_.loop2",
            ),
        ),
    ),
)
def test_start_menu_redisplay_resumes_once_before_rebuilding_overlay(
    phase2_rom: Phase2Rom,
    entry: str,
    expected_events: tuple[str, ...],
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = ROUTE_1
    emu.memory[symbols["wCurMapTileset"]] = 0
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    authored = _linked_overworld_bg_palettes(phase2_rom, ROUTE_1, y_coord=0)
    bgp = 0x1B
    palette_ids = (1, 2, 3, 4)
    pointers = b"".join(
        (symbols["CGBBasePalettes"] + index * 8).to_bytes(2, "little")
        for index in palette_ids
    )
    phase2_rom.write_fixed(symbols["wCGBBasePalPointers"], pointers)
    phase2_rom.write_wram2("wPassiveFullColorOverlaySuspended", 1)
    phase2_rom.write_wram2("wPassiveFullColorPaletteInvalidated", 0)
    emu.memory[symbols["hOnCGB"]] = 1
    emu.memory[RBGP] = bgp
    emu.memory[symbols["wLastBGP"]] = bgp ^ 0xFF
    phase2_rom.call("UpdateCGBPal_BGP")
    yellow = _apply_dmg_palette_mapping(
        b"".join(_linked_palette_entry(phase2_rom, index) for index in palette_ids),
        bgp,
    )
    expected = _apply_dmg_palette_mapping(authored, bgp)
    assert phase2_rom.emulator.read_palette_ram() == yellow + authored[32:]
    assert phase2_rom.emulator.read_palette_ram() != expected
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x01"
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE
    emu.memory[symbols["hWY"]] = 0
    preparation_boundaries: list[tuple[bytes, bytes, int]] = []

    def observe_preparation_boundary() -> None:
        preparation_boundaries.append(
            (
                phase2_rom.emulator.read_palette_ram(),
                phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated"),
                emu.memory[symbols["hWY"]],
            )
        )

    state = _run_to_boundary(
        phase2_rom,
        entry,
        "HandleMenuInput_.loop2",
        observe=(
            "PassiveFullColorResumeOverlays",
            "PassiveFullColorRestoreInvalidatedPalettes",
            "DrawStartMenu",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "Delay3",
        ),
        observe_actions={
            "PassiveFullColorPrepareMenuOverlay": observe_preparation_boundary,
            "Delay3": observe_preparation_boundary,
        },
        stub_returns={
            "DrawStartMenu": None,
            "PrintSafariZoneSteps": None,
            "UpdateSprites": None,
            "Delay3": None,
        },
        entry_rom_bank=4,
        run_vblank_interrupts=True,
    )

    assert state.events == expected_events
    assert state.events.count("PassiveFullColorResumeOverlays") == 1
    assert state.events.count("PassiveFullColorRestoreInvalidatedPalettes") == 1
    assert preparation_boundaries == [(expected, b"\x00", 144)] * 2
    assert phase2_rom.emulator.read_palette_ram() == expected
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended") == b"\x00"


@pytest.mark.parametrize(
    ("entry", "expected_events"),
    (
        (
            "RedisplayStartMenu",
            (
                "PassiveFullColorResumeOverlays",
                "DrawStartMenu",
                "PassiveFullColorInvalidateOverlayAttributes",
            ),
        ),
        (
            "RedisplayStartMenu_DoNotDrawStartMenu",
            (
                "PassiveFullColorResumeOverlays",
                "PassiveFullColorInvalidateOverlayAttributes",
            ),
        ),
    ),
)
def test_start_menu_redisplay_preserves_yellow_window_and_palette_behavior(
    phase2_rom: Phase2Rom,
    entry: str,
    expected_events: tuple[str, ...],
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = ROUTE_1
    emu.memory[symbols["wUnusedObtainedBadges"]] = 1
    emu.memory[symbols["hWY"]] = 37
    palettes = phase2_rom.emulator.read_palette_ram()

    state = _run_to_boundary(
        phase2_rom,
        entry,
        "PassiveFullColorInvalidateOverlayAttributes",
        observe=(
            "PassiveFullColorResumeOverlays",
            "PassiveFullColorRestoreInvalidatedPalettes",
            "DrawStartMenu",
        ),
        stub_returns={"DrawStartMenu": None},
        entry_rom_bank=4,
    )

    assert state.events == expected_events
    assert state.events.count("PassiveFullColorResumeOverlays") == 1
    assert emu.memory[symbols["hWY"]] == 37
    assert phase2_rom.emulator.read_palette_ram() == palettes


def test_pikachu_map_redisplay_restores_pikapic_state_before_paired_barrier(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = ROUTE_1
    emu.memory[symbols["wCurMapTileset"]] = 0
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[symbols["hOnCGB"]] = 1
    emu.memory[RBGP] = YELLOW_NORMAL_BGP
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[IF] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    authored = phase2_rom.emulator.read_palette_ram()
    phase2_rom.call("LoadOverworldPikachuFrontpicPalettes")
    mixed = phase2_rom.emulator.read_palette_ram()

    assert mixed[:32] != authored[:32]
    assert mixed[32:] == authored[32:]
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x01"
    assert phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended") == b"\x01"

    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE
    emu.memory[symbols["hWY"]] = 0
    boundaries: dict[str, tuple[bytes, bytes, bytes, int]] = {}
    delay_frames: list[tuple[bytes, bytes, bytes, int]] = []

    def capture_boundary(label: str) -> None:
        boundaries[label] = (
            phase2_rom.emulator.read_palette_ram(),
            phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated"),
            phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended"),
            emu.memory[symbols["hWY"]],
        )

    boundary_labels = (
        "PassiveFullColorRestoreInvalidatedPalettes",
        "PassiveFullColorTransferFadedPalettes",
        "PassiveFullColorRecordPalettePublished",
        "PassiveFullColorRedisplayMapView",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )

    state = _run_to_boundary(
        phase2_rom,
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3",
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3.done",
        observe=(
            "LoadCurrentMapView",
            "UpdateSprites",
            "PassiveFullColorResumeOverlays",
            "PassiveFullColorRestoreInvalidatedPalettes",
            "PassiveFullColorTransferFadedPalettes",
            "PassiveFullColorRecordPalettePublished",
            "PassiveFullColorRedisplayMapView",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
            "Delay3",
            "DelayFrame",
        ),
        observe_actions={
            **{
                label: lambda label=label: capture_boundary(label)
                for label in boundary_labels
            },
            "DelayFrame": lambda: delay_frames.append(
                (
                    phase2_rom.emulator.read_palette_ram(),
                    phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated"),
                    phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended"),
                    emu.memory[symbols["hWY"]],
                )
            ),
        },
        stub_returns={"LoadCurrentMapView": None, "UpdateSprites": None},
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "LoadCurrentMapView",
        "UpdateSprites",
        "PassiveFullColorResumeOverlays",
        "PassiveFullColorRestoreInvalidatedPalettes",
        "PassiveFullColorTransferFadedPalettes",
        "PassiveFullColorRecordPalettePublished",
        "PassiveFullColorRedisplayMapView",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorPrepareMenuOverlay",
        "DelayFrame",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
        "DelayFrame",
        "DelayFrame",
        "DelayFrame",
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3.done",
    )
    assert boundaries["PassiveFullColorRestoreInvalidatedPalettes"] == (
        mixed,
        b"\x01",
        b"\x00",
        144,
    )
    assert boundaries["PassiveFullColorTransferFadedPalettes"] == (
        mixed,
        b"\x01",
        b"\x00",
        144,
    )
    assert boundaries["PassiveFullColorRecordPalettePublished"] == (
        authored,
        b"\x01",
        b"\x00",
        144,
    )
    assert all(
        boundaries[label] == (authored, b"\x00", b"\x00", 144)
        for label in (
            "PassiveFullColorRedisplayMapView",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
            "Delay3",
        )
    )
    assert delay_frames == [(authored, b"\x00", b"\x00", 144)] * 4
    assert phase2_rom.emulator.read_palette_ram() == authored
    assert phase2_rom.read_wram2("wPassiveFullColorPaletteInvalidated") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended") == b"\x00"
    assert emu.memory[symbols["hWY"]] == 0
    assert state.sp == ENTRY_SP


def test_pikachu_map_redisplay_keeps_yellow_palette_window_and_delay(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = ROUTE_1
    emu.memory[symbols["wCurMapTileset"]] = 0
    emu.memory[symbols["wUnusedObtainedBadges"]] = 1
    emu.memory[symbols["hOnCGB"]] = 1
    emu.memory[RBGP] = YELLOW_NORMAL_BGP
    emu.memory[BOOTROM_DISABLE] = 1
    emu.memory[IF] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    phase2_rom.call("LoadOverworldPikachuFrontpicPalettes")
    stock_palettes = phase2_rom.emulator.read_palette_ram()
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hWY"]] = 37
    delay_frames: list[tuple[bytes, int]] = []

    state = _run_to_boundary(
        phase2_rom,
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3",
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3.done",
        observe=(
            "LoadCurrentMapView",
            "UpdateSprites",
            "PassiveFullColorResumeOverlays",
            "PassiveFullColorRestoreInvalidatedPalettes",
            "PassiveFullColorRedisplayMapView",
            "Delay3",
            "DelayFrame",
        ),
        observe_actions={
            "DelayFrame": lambda: delay_frames.append(
                (phase2_rom.emulator.read_palette_ram(), emu.memory[symbols["hWY"]])
            )
        },
        stub_returns={"LoadCurrentMapView": None, "UpdateSprites": None},
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "LoadCurrentMapView",
        "UpdateSprites",
        "PassiveFullColorResumeOverlays",
        "PassiveFullColorRedisplayMapView",
        "Delay3",
        "DelayFrame",
        "DelayFrame",
        "DelayFrame",
        "Pikachu_LoadCurrentMapViewUpdateSpritesAndDelay3.done",
    )
    assert delay_frames == [(stock_palettes, 37)] * 3
    assert phase2_rom.emulator.read_palette_ram() == stock_palettes
    assert emu.memory[symbols["hWY"]] == 37
    assert state.sp == ENTRY_SP


def test_initial_options_screen_invalidates_prior_completed_overlay(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wCurMap"]] = 0x0C
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")
    _enable_production_overlay_video(phase2_rom)
    emu.memory[symbols["hAutoBGTransferEnabled"]] = PASSIVE_OVERLAY_COMPLETE

    state = _run_to_boundary(
        phase2_rom,
        "InitOptionsMenu",
        "Delay3",
        observe=(
            "PassiveFullColorShouldColorOverlay",
            "PassiveFullColorInvalidateOverlayAttributes",
            "PassiveFullColorPrepareMenuOverlay",
            "PassiveFullColorOverlayAttributeGDMA",
        ),
        stub_returns={
            "TextBoxBorder": None,
            "PlaceString": None,
            "GetOptionPointer": None,
        },
        run_vblank_interrupts=True,
    )

    assert state.events == (
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorInvalidateOverlayAttributes",
        "PassiveFullColorPrepareMenuOverlay",
        "PassiveFullColorShouldColorOverlay",
        "PassiveFullColorOverlayAttributeGDMA",
        "Delay3",
    )
    assert phase2_rom.read_wram2("wPassiveFullColorActive") == b"\x01"


def test_party_entry_stays_yellow_and_exit_schedules_passive_restore(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    symbols = phase2_rom.emulator.symbols
    emu.memory[symbols["wCurMap"]] = 0x0C
    phase2_rom.call("InitRendererOwnership")
    emu.memory[symbols["wUnusedObtainedBadges"]] = 0
    emu.memory[0xFF40] &= 0x7F
    phase2_rom.call("PassiveFullColorApplyMap")

    entry = _run_to_boundary(
        phase2_rom,
        "DisplayPartyMenu",
        "PartyMenuInit",
        stub_returns={"GBPalWhiteOutWithDelay3": None, "ClearSprites": None},
        entry_rom_bank=4,
    )
    assert entry.events == ("PartyMenuInit",)
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    generation = phase2_rom.generation
    exit_state = _run_to_boundary(
        phase2_rom,
        "StartMenu_Pokemon.exitMenu",
        "RedisplayStartMenu",
        observe=(
            "PassiveFullColorScheduleAttributeRestore",
        ),
        stub_returns={
            "GBPalWhiteOutWithDelay3": None,
            "RestoreScreenTilesAndReloadTilePatterns": None,
            "LoadGBPal": None,
        },
        entry_rom_bank=4,
    )
    assert exit_state.events == (
        "PassiveFullColorScheduleAttributeRestore",
        "RedisplayStartMenu",
    )
    assert phase2_rom.generation == generation
    assert phase2_rom.read_wram2("wPassiveFullColorPalettePending") == b"\x00"
    assert phase2_rom.read_wram2("wPassiveFullColorAttributesInvalidated") == b"\x01"
    assert phase2_rom.read_wram2("wPassiveFullColorOverlaySuspended") == b"\x01"
    assert phase2_rom.read_wram2("wRendererOwner") == bytes(
        (phase2_rom.constants["RENDERER_YELLOW"],)
    )
    assert exit_state.sp == ENTRY_SP
    assert (exit_state.ie, exit_state.interrupt_flags) == (ENTRY_IE, ENTRY_IF)
