"""Direct production-ROM checks for the owner-transition core wrappers."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")
SET_PAL_GENERIC = 0x08
ROUTE_1 = 0x0C
STATE = (
    "wRendererOwner",
    "wRendererPhase",
    "wRendererGeneration",
    "wRendererAdmissionOpen",
    "wRendererJobState",
    "wRendererJobGeneration",
    "wRendererJobCancellationReason",
)
TRANSITION_STATE = (
    "wFullColorProductionYellowReconstructionBarrier",
    "wFullColorProductionColorReconstructionBarrier",
    "wFullColorProductionReconstructionLedger",
    "wFullColorProductionReturnContext",
    "wFullColorProductionTransitionStatus",
    "wFullColorProductionTransitionRoute",
    "wFullColorProductionSavedLCDC",
)


def _constants(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            values[match.group(2)] = int(match.group(1), 16)
    return values


@dataclass(slots=True)
class TransitionRom:
    emulator: Emulator
    constants: dict[str, int]

    def call(
        self,
        routine: str,
        *,
        a: int = 0,
        b: int | None = None,
        c: int | None = None,
    ) -> int:
        registers = self.emulator.pyboy.register_file
        address = self.emulator.symbols[routine]
        bank = self.emulator.symbol_banks[routine]
        stack = 0xCFFE
        registers.A = a
        if b is not None:
            registers.B = b
        if c is not None:
            registers.C = c
        registers.SP = stack
        self.emulator.pyboy.memory[stack] = 0
        self.emulator.pyboy.memory[stack + 1] = 1
        if bank:
            self.emulator.pyboy.memory[0x2000] = bank & 0xFF
            self.emulator.pyboy.memory[0x3000] = bank >> 8
            self.emulator.pyboy.memory[
                self.emulator.symbols["hLoadedROMBank"]
            ] = bank & 0xFF
        registers.PC = address
        returned = False

        def stop(_: object) -> None:
            nonlocal returned
            returned = True
            self.emulator.pyboy.memory[0xFF90 : 0xFF92] = b"\x18\xfe"
            registers.PC = 0xFF90

        self.emulator.pyboy.hook_register(0, 0x0100, stop, None)
        try:
            # Hidden reconstruction may legitimately exceed one emulated frame;
            # its production deadline is the named pre-display barrier, not a
            # VBlank slot. Keep direct calls finite without inventing a tighter
            # timing contract than the linked code owns.
            for _ in range(8):
                self.emulator.pyboy.tick(1, render=False, sound=False)
                if returned:
                    break
        finally:
            self.emulator.pyboy.hook_deregister(0, 0x0100)
        assert returned, f"{routine} did not return; PC={registers.PC:#06x}"
        return registers.F

    def read2(self, symbol: str, size: int = 1) -> int:
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            address = self.emulator.symbols[symbol]
            return int.from_bytes(
                bytes(self.emulator.pyboy.memory[address + i] for i in range(size)),
                "little",
            )
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def write2(self, symbol: str, value: int, size: int = 1) -> None:
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            address = self.emulator.symbols[symbol]
            for offset, byte in enumerate(value.to_bytes(size, "little")):
                self.emulator.pyboy.memory[address + offset] = byte
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def read1(self, symbol: str, size: int = 1) -> int:
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 1
        try:
            address = self.emulator.symbols[symbol]
            return int.from_bytes(
                bytes(self.emulator.pyboy.memory[address + i] for i in range(size)),
                "little",
            )
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def write1(self, symbol: str, value: int, size: int = 1) -> None:
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 1
        try:
            address = self.emulator.symbols[symbol]
            for offset, byte in enumerate(value.to_bytes(size, "little")):
                self.emulator.pyboy.memory[address + offset] = byte
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def set_owner(self, owner: str, phase: str, generation: int = 7) -> None:
        self.write2("wRendererOwner", self.constants[owner])
        self.write2("wRendererPhase", self.constants[phase])
        self.write2("wRendererGeneration", generation, 4)
        self.write2("wRendererAdmissionOpen", 1)
        self.write2("wRendererJobState", self.constants["RENDERER_JOB_NONE"])
        self.write2("wRendererJobGeneration", 0, 4)
        self.write2("wRendererJobCancellationReason", self.constants["CANCELLATION_NONE"])

    def snapshot(self) -> tuple[int, ...]:
        sizes = {"wRendererGeneration": 4, "wRendererJobGeneration": 4,
                 "wFullColorProductionReconstructionLedger": 2}
        return tuple(self.read2(name, sizes.get(name, 1)) for name in STATE + TRANSITION_STATE)


@pytest.fixture(params=PRODUCTS)
def transition_rom(request: pytest.FixtureRequest) -> TransitionRom:
    product = str(request.param)
    rom_path = REPOSITORY_ROOT / f"{product}.gbc"
    symbols = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(
        rom_path,
        symbols,
        result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        required = set(STATE + TRANSITION_STATE) | {
            "BeginForcedYellowPresentation", "CompleteYellowPresentation",
            "BeginRendererHandoff", "CompleteDepartingRendererCommitSelected",
            "RecordYellowReconstructionComplete",
            "CommitYellowPresentationTileMapForContext",
            "SetFullColorProductionReturnContext",
            "DrawStartMenu",
            "BeginForcedYellowPresentationRoot",
            "ConcealForcedYellowPresentation",
            "BeginFullColorMapEntry", "CompleteFullColorMapReconstruction",
            "ResetRendererOwnershipForReconstruction",
            "RouteRendererOwnershipVBlank",
            "PrepareFullColorProductionOAMForOwnedVBlank",
            "SubmitFullColorProductionNorthRowFar",
            "SubmitFullColorProductionSouthRowFar",
            "SubmitFullColorProductionEastColumnFar",
            "SubmitFullColorProductionWestColumnFar",
        }
        assert required <= emulator.symbols.keys()
        rom = TransitionRom(emulator, _constants(symbols))
        assert rom.constants["FULL_COLOR_PRODUCTION_ACTIVATED"] in (0, 1)
        rom.call("InitRendererOwnership")
        if rom.constants["FULL_COLOR_PRODUCTION_ACTIVATED"]:
            rom.set_owner("RENDERER_YELLOW", "YELLOW_ACTIVE", generation=1)
            for name in TRANSITION_STATE:
                rom.write2(
                    name,
                    0,
                    2 if name == "wFullColorProductionReconstructionLedger" else 1,
                )
        yield rom
    finally:
        emulator.close()


def test_same_owner_wrappers_are_exact_noops(transition_rom: TransitionRom) -> None:
    rom = transition_rom
    before = rom.snapshot()
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    assert rom.snapshot() == before

    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    before = rom.snapshot()
    assert not rom.call("BeginFullColorMapEntry") & 0x10
    assert not rom.call("CompleteFullColorMapReconstruction") & 0x10
    assert rom.snapshot() == before


def test_color_to_yellow_closes_reconstructs_and_reopens_once(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_YELLOW"]
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererGeneration", 4) == 8
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorProductionTransitionStatus") == rom.constants["TRANSITION_REQUIRED"]
    assert rom.read2("wFullColorProductionTransitionRoute") == rom.constants["TRANSITION_ROUTE_YELLOW"]
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == 0

    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_ACTIVE"]
    assert rom.read2("wRendererAdmissionOpen") == 1
    assert rom.read2("wRendererGeneration", 4) == 8
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == rom.constants["FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE"]
    assert rom.read2("wFullColorProductionYellowReconstructionBarrier") == 1


def test_yellow_completion_rejects_a_missing_tilemap_commit(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    assert rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == 0
    assert rom.read2("wFullColorProductionYellowReconstructionBarrier") == 0

    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    missing = rom.constants["FULL_COLOR_RECONSTRUCTION_ITEM_TILEMAPS_ATTRIBUTES"]
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == (
        rom.constants["FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE"] & ~missing
    )
    assert rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0

    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_ACTIVE"]
    assert rom.read2("wFullColorProductionTransitionStatus") == rom.constants["TRANSITION_NONE"]


def test_hostile_nonzero_transition_status_cannot_commit_or_reopen(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_YELLOW", "YELLOW_RECONSTRUCTING")
    rom.write2("wRendererAdmissionOpen", 0)
    rom.write2("wFullColorProductionTransitionStatus", 0xFF)
    rom.write2("wFullColorProductionTransitionRoute", rom.constants["TRANSITION_ROUTE_YELLOW"])
    assert rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert rom.call("RecordYellowReconstructionComplete") & 0x10
    assert rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == 0
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0


def _fill_vram_bank(rom: TransitionRom, bank: int, value: int) -> None:
    memory = rom.emulator.pyboy.memory
    prior = memory[0xFF4F]
    memory[0xFF4F] = bank
    try:
        memory[0x9C00:0xA000] = bytes([value]) * 0x400
    finally:
        memory[0xFF4F] = prior


def _read_window_rows(rom: TransitionRom, bank: int) -> bytes:
    memory = rom.emulator.pyboy.memory
    prior = memory[0xFF4F]
    memory[0xFF4F] = bank
    try:
        return b"".join(
            bytes(memory[0x9C00 + row * 32 + column] for column in range(20))
            for row in range(18)
        )
    finally:
        memory[0xFF4F] = prior


def _linked_bytes(rom: TransitionRom, symbol: str, size: int, *, skip: int = 0) -> bytes:
    address = rom.emulator.symbols[symbol] + skip
    bank = rom.emulator.symbol_banks[symbol]
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom.emulator.rom.read_bytes()[offset:offset + size]


def _require_activated(rom: TransitionRom) -> None:
    if not rom.constants["FULL_COLOR_PRODUCTION_ACTIVATED"]:
        pytest.skip("requires the production activation latch")


def _run_color_vblank_without_legacy_oam_build(rom: TransitionRom) -> None:
    """Run the real Color route while isolating uninitialized sprite mechanics."""
    symbol = "PrepareFullColorProductionOAMForOwnedVBlank"
    bank = rom.emulator.symbol_banks[symbol]
    address = rom.emulator.symbols[symbol]

    def skip_oam_build(_: object) -> None:
        stack = rom.emulator.pyboy.register_file.SP
        low = rom.emulator.pyboy.memory[stack]
        high = rom.emulator.pyboy.memory[stack + 1]
        rom.emulator.pyboy.register_file.SP = stack + 2
        rom.emulator.pyboy.register_file.PC = low | high << 8

    rom.emulator.pyboy.hook_register(bank, address, skip_oam_build, None)
    try:
        rom.call("RouteRendererOwnershipVBlank")
    finally:
        rom.emulator.pyboy.hook_deregister(bank, address)


def _return_from_hook(rom: TransitionRom, action=None):
    def callback(_: object) -> None:
        if action is not None:
            action()
        registers = rom.emulator.pyboy.register_file
        stack = registers.SP
        registers.PC = (
            rom.emulator.pyboy.memory[stack]
            | rom.emulator.pyboy.memory[stack + 1] << 8
        )
        registers.SP = stack + 2

    return callback


def _run_with_stubbed_mechanics(
    rom: TransitionRom,
    entry: str,
    stubs: dict[str, object],
) -> set[str]:
    reached: set[str] = set()
    hooks: list[tuple[int, int]] = []
    for symbol, action in stubs.items():
        bank = rom.emulator.symbol_banks[symbol]
        address = rom.emulator.symbols[symbol]

        def observed(inner=action, name=symbol) -> None:
            reached.add(name)
            if callable(inner):
                inner()

        rom.emulator.pyboy.hook_register(
            bank, address, _return_from_hook(rom, observed), None,
        )
        hooks.append((bank, address))
    try:
        try:
            rom.call(entry)
        except AssertionError as error:
            raise AssertionError(f"{error}; reached={sorted(reached)}") from error
    finally:
        for bank, address in reversed(hooks):
            rom.emulator.pyboy.hook_deregister(bank, address)
    return reached


def _visible_color_snapshot(rom: TransitionRom) -> tuple[bytes, ...]:
    return (
        rom.emulator.read_vram_bank(0, 0x9800, 0x800),
        rom.emulator.read_vram_bank(1, 0x9800, 0x800),
        rom.emulator.read_palette_ram(),
        rom.emulator.read_palette_ram(object_palettes=True),
        bytes(rom.emulator.pyboy.memory[0xFE00:0xFEA0]),
    )


def _prepare_actual_root_return(rom: TransitionRom) -> dict[str, object]:
    memory = rom.emulator.pyboy.memory
    tile_map = rom.emulator.symbols["wTileMap"]
    shadow_oam = rom.emulator.symbols["wShadowOAM"]

    def build_map() -> None:
        memory[tile_map:tile_map + 360] = bytes(
            (index * 19 + 11) & 0xFF for index in range(360)
        )

    def build_oam() -> None:
        memory[shadow_oam:shadow_oam + 160] = bytes(
            (index * 7 + 3) & 0xFF for index in range(160)
        )

    def menu_cancel() -> None:
        rom.emulator.pyboy.register_file.A = 1 << 1  # PAD_B

    def release_buttons() -> None:
        memory[rom.emulator.symbols["hJoyPressed"]] = 0
        memory[rom.emulator.symbols["hJoyHeld"]] = 0

    def disable_lcd() -> None:
        memory[0xFF40] &= 0x7F

    def enable_lcd() -> None:
        memory[0xFF40] |= 0x80

    return {
        "PlaySound": None,
        "PrintSafariZoneSteps": None,
        "HandleMenuInput": menu_cancel,
        "Joypad": release_buttons,
        "DelayFrame": None,
        "DisableLCD": disable_lcd,
        "EnableLCD": enable_lcd,
        "LoadTextBoxTilePatterns": None,
        "InitMapSprites": None,
        "LoadPlayerSpriteGraphics": None,
        "LoadCurrentMapView": build_map,
        "UpdateSprites": build_oam,
    }


def _assert_five_quiet_color_frames(rom: TransitionRom) -> None:
    forbidden = (
        "AutoBgMapTransfer",
        "VBlankCopyBgMap",
        "RedrawRowOrColumn",
        "UpdateMovingBgTiles",
    )
    hits: list[str] = []
    hooks: list[tuple[int, int]] = []
    for symbol in forbidden:
        bank = rom.emulator.symbol_banks[symbol]
        address = rom.emulator.symbols[symbol]
        rom.emulator.pyboy.hook_register(
            bank,
            address,
            lambda _context, name=symbol: hits.append(name),
            None,
        )
        hooks.append((bank, address))
    generation = rom.read2("wRendererGeneration", 4)
    baseline = _visible_color_snapshot(rom)
    try:
        for _ in range(5):
            _run_color_vblank_without_legacy_oam_build(rom)
            assert _visible_color_snapshot(rom) == baseline
            assert rom.read2("wRendererOwner") == rom.constants[
                "RENDERER_FULL_COLOR_OVERWORLD"
            ]
            assert rom.read2("wRendererPhase") == rom.constants["OVERWORLD_ACTIVE"]
            assert rom.read2("wRendererAdmissionOpen") == 1
            assert rom.read2("wRendererGeneration", 4) == generation
    finally:
        for bank, address in reversed(hooks):
            rom.emulator.pyboy.hook_deregister(bank, address)
    assert hits == []


def _write_palette_ram(rom: TransitionRom, payload: bytes) -> None:
    assert len(payload) == 64
    memory = rom.emulator.pyboy.memory
    prior = memory[0xFF68]
    try:
        for index, value in enumerate(payload):
            memory[0xFF68] = index
            memory[0xFF69] = value
    finally:
        memory[0xFF68] = prior


def test_color_to_start_menu_commits_complete_bank0_window_before_activation(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    # Direct-call fixtures bypass boot.  Model the production CGB flags and run
    # Yellow's real palette command once, making its WRAM palette buffer and
    # whole-screen attribute packet the destination authority for the handoff.
    rom.emulator.pyboy.memory[rom.emulator.symbols["hOnCGB"]] = 1
    rom.emulator.pyboy.memory[rom.emulator.symbols["wOnSGB"]] = 1
    rom.emulator.pyboy.memory[0xFF50] = 1
    rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    assert not rom.call("RunPaletteCommand", b=SET_PAL_GENERIC) & 0x10
    rom.emulator.pyboy.memory[rom.emulator.symbols["wDefaultPaletteCommand"]] = (
        SET_PAL_GENERIC
    )
    # Yellow exposes four active BG palettes; bank-1 zero attributes select
    # palette 0, while the remaining CGB palette slots are outside this scene's
    # logical authority.
    yellow_palette = rom.emulator.read_palette_ram()[:32]
    yellow_attributes = _read_window_rows(rom, 1)
    linked_yellow_attributes = _linked_bytes(
        rom, "BGMapAttributes_WholeScreen", 360, skip=16,
    )
    assert yellow_attributes == linked_yellow_attributes == bytes(360)

    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call(
        "SetFullColorProductionReturnContext",
        a=rom.constants["RENDERER_CONTEXT_MENU"],
    ) & 0x10
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_YELLOW"]
    assert rom.read2("wRendererAdmissionOpen") == 0

    tile_map = rom.emulator.symbols["wTileMap"]
    rom.emulator.pyboy.memory[tile_map:tile_map + 360] = bytes([0x7F]) * 360
    assert not rom.call("DrawStartMenu") & 0x10
    menu = bytes(rom.emulator.pyboy.memory[tile_map + i] for i in range(360))
    assert menu != bytes([0x7F]) * 360

    # Yellow's complete palette buffer and whole-screen attribute packet are
    # the independent destination authorities.  Start from the linked Color
    # palette and hostile bank-1 bytes so this cannot pass by accepting stale
    # Color presentation.
    color_palette = _linked_bytes(rom, "FullColorOverworldBGPalettes", 64)
    assert color_palette[:32] != yellow_palette
    _write_palette_ram(rom, color_palette)

    _fill_vram_bank(rom, 0, 0xC3)
    _fill_vram_bank(rom, 1, 0x5A)
    rom.emulator.pyboy.memory[0xFF4F] = 1
    rom.emulator.pyboy.memory[0xFFFF] = 0
    rom.emulator.pyboy.memory[0xFF0F] = 0
    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert rom.emulator.pyboy.memory[0xFF4F] & 1 == 1
    assert _read_window_rows(rom, 0) == menu
    assert _read_window_rows(rom, 1) == yellow_attributes
    assert rom.emulator.read_palette_ram()[:32] == yellow_palette

    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_ACTIVE"]
    assert rom.read2("wRendererAdmissionOpen") == 1


def test_rom_mutation_removing_menu_commit_keeps_completion_closed(
    tmp_path: Path,
) -> None:
    source_rom = REPOSITORY_ROOT / "pokeyellow.gbc"
    source_sym = REPOSITORY_ROOT / "pokeyellow.sym"
    probe = Emulator(source_rom, source_sym, tmp_path / "probe", cgb=True)
    try:
        address = probe.symbols["CommitYellowPresentationTileMapForContext"]
        bank = probe.symbol_banks["CommitYellowPresentationTileMapForContext"]
    finally:
        probe.close()
    blob = bytearray(source_rom.read_bytes())
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    blob[offset] = 0xC9  # ret -- remove the hidden tilemap commit
    mutant_path = tmp_path / "missing-menu-commit.gbc"
    mutant_path.write_bytes(blob)
    emulator = Emulator(mutant_path, source_sym, tmp_path / "mutant", cgb=True)
    mutant = TransitionRom(emulator, _constants(source_sym))
    try:
        mutant.call("InitRendererOwnership")
        mutant.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
        mutant.call(
            "SetFullColorProductionReturnContext",
            a=mutant.constants["RENDERER_CONTEXT_MENU"],
        )
        mutant.call("BeginForcedYellowPresentation")
        _fill_vram_bank(mutant, 0, 0xC3)
        assert not mutant.call("CommitYellowPresentationTileMapForContext") & 0x10
        assert not mutant.call("RecordYellowReconstructionComplete") & 0x10
        assert mutant.call("CompleteYellowPresentation") & 0x10
        missing = mutant.constants["FULL_COLOR_RECONSTRUCTION_ITEM_TILEMAPS_ATTRIBUTES"]
        assert not mutant.read2("wFullColorProductionReconstructionLedger", 2) & missing
        assert mutant.read2("wRendererPhase") == mutant.constants["YELLOW_RECONSTRUCTING"]
        assert mutant.read2("wRendererAdmissionOpen") == 0
        assert _read_window_rows(mutant, 0) == bytes([0xC3]) * 360
    finally:
        emulator.close()


@pytest.mark.parametrize(
    "item",
    (
        "FULL_COLOR_RECONSTRUCTION_ITEM_MAP_TILESET_OVERRIDES",
        "FULL_COLOR_RECONSTRUCTION_ITEM_VIEWPORT_DESTINATION",
        "FULL_COLOR_RECONSTRUCTION_ITEM_TILES_REPLACEMENTS",
        "FULL_COLOR_RECONSTRUCTION_ITEM_TILEMAPS_ATTRIBUTES",
        "FULL_COLOR_RECONSTRUCTION_ITEM_PALETTES",
        "FULL_COLOR_RECONSTRUCTION_ITEM_OAM",
        "FULL_COLOR_RECONSTRUCTION_ITEM_SCHEDULER",
        "FULL_COLOR_RECONSTRUCTION_ITEM_MACHINE_STATE",
    ),
)
def test_yellow_completion_rejects_each_missing_reconstruction_item(
    transition_rom: TransitionRom, item: str,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    complete = rom.constants["FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE"]
    rom.write2(
        "wFullColorProductionReconstructionLedger",
        complete & ~rom.constants[item],
        2,
    )

    assert rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorProductionYellowReconstructionBarrier") == 0


def test_reset_stays_closed_until_yellow_completion(transition_rom: TransitionRom) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call("ResetRendererOwnershipForReconstruction") & 0x10
    assert rom.read2("wRendererGeneration", 4) == 8
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorProductionTransitionRoute") == rom.constants["TRANSITION_ROUTE_RESET_YELLOW"]
    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_ACTIVE"]
    assert rom.read2("wRendererAdmissionOpen") == 1
    assert rom.read2("wFullColorProductionYellowReconstructionBarrier") == 1


def test_handoff_completes_departing_committing_job_before_one_generation(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    generation = rom.read2("wRendererGeneration", 4)
    rom.write2("wRendererJobState", rom.constants["COMMITTING"])
    rom.write2("wRendererJobGeneration", generation, 4)
    rom.write2("wRendererJobCancellationReason", rom.constants["CANCELLATION_NONE"])
    transition_count = rom.read2("wFullColorTransitionCount")

    flags = rom.call(
        "BeginRendererHandoff",
        a=rom.constants["HANDOFF_TO_YELLOW"],
    )

    assert not flags & 0x10
    assert rom.read2("wRendererJobState") == rom.constants["COMPLETE"]
    assert rom.read2("wRendererJobCancellationReason") == rom.constants["CANCELLATION_NONE"]
    assert rom.read2("wRendererGeneration", 4) == generation + 1
    assert rom.read2("wRendererPhase") == rom.constants["HANDOFF_TO_YELLOW"]
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorTransitionCount") == transition_count


def test_activated_soft_reset_closes_routing_before_lcd_on_delay() -> None:
    ownership = (REPOSITORY_ROOT / "engine/full_color/ownership.asm").read_text()
    soft_reset = _routine(
        ownership,
        "SoftResetRendererOwnership::",
        "ResetRendererOwnership::",
    )
    guarded = _routine(
        soft_reset,
        "IF FULL_COLOR_PRODUCTION_ACTIVATED",
        "ELSE",
    )
    assert guarded.index("ResetRendererOwnershipForReconstruction") < guarded.index(
        "GBPalWhiteOut"
    )
    assert guarded.index("GBPalWhiteOut") < guarded.index("call DelayFrames")
    assert guarded.index("call DelayFrames") < guarded.index("call DisableLCD")


def test_activated_soft_reset_reaches_init_with_one_reset_generation_and_barrier(
    request: pytest.FixtureRequest,
) -> None:
    rom_value = os.environ.get("FULL_COLOR_ACTIVATED_ROM")
    symbols_value = os.environ.get("FULL_COLOR_ACTIVATED_SYMBOLS")
    if not rom_value or not symbols_value:
        pytest.skip(
            "set FULL_COLOR_ACTIVATED_ROM and FULL_COLOR_ACTIVATED_SYMBOLS "
            "to an activation=1 build"
        )

    rom_path = Path(rom_value)
    symbols_path = Path(symbols_value)
    assert rom_path.is_file()
    assert symbols_path.is_file()
    constants = _constants(symbols_path)
    assert constants["FULL_COLOR_PRODUCTION_ACTIVATED"] == 1

    emulator = Emulator(
        rom_path,
        symbols_path,
        result_directory(request.node.nodeid),
        cgb=True,
    )
    rom = TransitionRom(emulator, constants)
    try:
        # Wait only for ownership initialization. The activated cold-boot path
        # deliberately starts closed; this test supplies a controlled active
        # Yellow source and known LCD/VBlank state before entering soft reset.
        for _ in range(180):
            emulator.tick()
            if rom.read2("wRendererGeneration", 4) == 1:
                break
        else:
            pytest.fail("activated ROM did not initialize renderer ownership")

        rom.set_owner("RENDERER_YELLOW", "YELLOW_ACTIVE", generation=7)
        for name in TRANSITION_STATE:
            rom.write2(
                name,
                0,
                2 if name == "wFullColorProductionReconstructionLedger" else 1,
            )
        barrier_before = rom.read2("wFullColorProductionYellowReconstructionBarrier")
        emulator.pyboy.memory[0xFF40] |= 0x80
        emulator.pyboy.memory[0xFF0F] = 0
        emulator.pyboy.memory[0xFFFF] = 0

        registers = emulator.pyboy.register_file
        soft_reset = emulator.symbols["SoftResetRendererOwnership"]
        soft_reset_bank = emulator.symbol_banks["SoftResetRendererOwnership"]
        delay_frame = emulator.symbols["DelayFrame"]
        delay_frame_bank = emulator.symbol_banks["DelayFrame"]
        reset = emulator.symbols["ResetRendererOwnershipForReconstruction"]
        reset_bank = emulator.symbol_banks["ResetRendererOwnershipForReconstruction"]
        soft_reset_init = emulator.symbols["SoftResetInit"]
        soft_reset_init_bank = emulator.symbol_banks["SoftResetInit"]
        delay_calls = 0
        reset_calls = 0
        reached_init = False
        delay_states: list[tuple[int, int]] = []
        observed: dict[str, int] = {}

        def count_delay(_: object) -> None:
            nonlocal delay_calls
            delay_calls += 1
            delay_states.append((
                rom.read2("wRendererPhase"),
                rom.read2("wRendererAdmissionOpen"),
            ))
            # Treat this hook as the completed frame boundary. The production
            # DelayFrame body itself is already covered by the LCD-on ordering
            # guard; returning here keeps this direct control-flow test finite
            # and deterministic under PyBoy's single-tick callback model.
            stack_pointer = registers.SP
            registers.PC = (
                emulator.pyboy.memory[stack_pointer]
                | emulator.pyboy.memory[stack_pointer + 1] << 8
            )
            registers.SP = stack_pointer + 2

        def count_reset(_: object) -> None:
            nonlocal reset_calls
            reset_calls += 1

        def at_soft_reset_init(_: object) -> None:
            nonlocal reached_init
            reached_init = True
            observed.update(
                generation=rom.read2("wRendererGeneration", 4),
                phase=rom.read2("wRendererPhase"),
                admission=rom.read2("wRendererAdmissionOpen"),
                route=rom.read2("wFullColorProductionTransitionRoute"),
                barrier=rom.read2("wFullColorProductionYellowReconstructionBarrier"),
                lcdc=emulator.pyboy.memory[0xFF40],
            )
            emulator.pyboy.memory[0xFFFF] = 0
            # Keep PyBoy's outer frame clock advancing after observing the real
            # LCD-off entry boundary; production continues into SoftResetInit.
            emulator.pyboy.memory[0xFF40] |= 0x80
            emulator.pyboy.memory[0xFFEF : 0xFFF1] = b"\x18\xfe"
            registers.PC = 0xFFEF

        emulator.pyboy.hook_register(delay_frame_bank, delay_frame, count_delay, None)
        emulator.pyboy.hook_register(reset_bank, reset, count_reset, None)
        emulator.pyboy.hook_register(
            soft_reset_init_bank, soft_reset_init, at_soft_reset_init, None
        )
        try:
            emulator.pyboy.memory[0x2000] = soft_reset_bank & 0xFF
            emulator.pyboy.memory[0x3000] = soft_reset_bank >> 8
            emulator.pyboy.memory[emulator.symbols["hLoadedROMBank"]] = soft_reset_bank
            registers.SP = 0xCFFE
            registers.PC = soft_reset
            for _ in range(3):
                emulator.pyboy.tick(1, render=False, sound=False)
                if reached_init:
                    break
        finally:
            emulator.pyboy.hook_deregister(delay_frame_bank, delay_frame)
            emulator.pyboy.hook_deregister(reset_bank, reset)
            emulator.pyboy.hook_deregister(soft_reset_init_bank, soft_reset_init)

        assert reached_init, (
            "activated soft reset stalled before SoftResetInit: "
            f"PC={registers.PC:#06x}, delay_calls={delay_calls}, "
            f"reset_calls={reset_calls}, LCDC={emulator.pyboy.memory[0xFF40]:#04x}, "
            f"IE={emulator.pyboy.memory[0xFFFF]:#04x}, IF={emulator.pyboy.memory[0xFF0F]:#04x}"
        )
        assert delay_calls == 32
        assert reset_calls == 1
        assert set(delay_states) == {(constants["YELLOW_RECONSTRUCTING"], 0)}
        assert not observed.pop("lcdc") & 0x80
        assert observed == {
            "generation": 8,
            "phase": constants["YELLOW_RECONSTRUCTING"],
            "admission": 0,
            "route": constants["TRANSITION_ROUTE_RESET_YELLOW"],
            "barrier": barrier_before,
        }

        rom.call("RouteRendererOwnershipVBlank")
        assert emulator.pyboy.register_file.E == constants["VBLANK_ROUTE_CLOSED"]
        rom.write2(
            "wFullColorProductionReconstructionLedger",
            constants["FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE"],
            2,
        )
        assert not rom.call("CompleteYellowPresentation") & 0x10
        assert rom.read2("wRendererGeneration", 4) == 8
        assert rom.read2("wFullColorProductionYellowReconstructionBarrier") == barrier_before + 1
        assert rom.read2("wRendererPhase") == constants["YELLOW_ACTIVE"]
        assert rom.read2("wRendererAdmissionOpen") == 1
    finally:
        emulator.close()


def test_yellow_to_color_selects_one_fresh_closed_generation(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_YELLOW", "YELLOW_ACTIVE")
    assert not rom.call("BeginFullColorMapEntry") & 0x10
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]
    assert rom.read2("wRendererPhase") == rom.constants["OVERWORLD_RECONSTRUCTING"]
    assert rom.read2("wRendererGeneration", 4) == 8
    assert rom.read2("wRendererAdmissionOpen") == 0
    assert rom.read2("wFullColorProductionTransitionRoute") == rom.constants["TRANSITION_ROUTE_FULL_COLOR"]
    assert rom.read2("wFullColorProductionColorReconstructionBarrier") == 0


def _routine(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_production_callgraph_places_completion_at_real_barriers() -> None:
    battle = (REPOSITORY_ROOT / "engine/battle/init_battle.asm").read_text()
    battle_reconstruction = _routine(battle, "_InitBattleCommon:", "_LoadTrainerPic:")
    assert battle_reconstruction.index("RecordAndCompleteYellowPresentationRoot") < battle_reconstruction.index("StartBattle")
    assert "RecordAndCompleteYellowPresentationRoot" not in _routine(battle, "InitBattleCommon:", "InitWildBattle:")

    title = (REPOSITORY_ROOT / "engine/movie/title.asm").read_text()
    hidden_title = _routine(title, "DisplayTitleScreen:", "; make pokemon logo bounce")
    assert hidden_title.index("TitleScreen_PlacePikachu") < hidden_title.index("RecordAndCompleteYellowPresentationRoot")
    assert hidden_title.rindex("TitleScreenCopyTileMapToVRAM") < hidden_title.index("RecordAndCompleteYellowPresentationRoot")
    assert hidden_title.index("UpdateCGBPal_OBP0") < hidden_title.index("RecordAndCompleteYellowPresentationRoot")
    assert hidden_title.index("RecordAndCompleteYellowPresentationRoot") < hidden_title.rindex("call EnableLCD")
    assert hidden_title.count("RecordAndCompleteYellowPresentationRoot") == 1
    assert "CompleteYellowPresentation" not in (REPOSITORY_ROOT / "home/init.asm").read_text()

    start_menu = (REPOSITORY_ROOT / "home/start_menu.asm").read_text()
    start_reconstruction = _routine(start_menu, "RedisplayStartMenu::", ".loop")
    assert start_reconstruction.index("UpdateSprites") < start_reconstruction.index("RecordAndCompleteYellowPresentationRoot")

    lifecycle = (REPOSITORY_ROOT / "engine/full_color/lifecycle.asm").read_text()
    recorder = _routine(
        lifecycle,
        "RecordYellowReconstructionComplete::",
        "CompleteYellowPresentation::",
    )
    for bit in (0, 1, 2, 4, 5, 6, 7):
        assert recorder.count(f"set {bit}, [hl]") == 1
    assert "set 3, [hl]" not in recorder
    assert "ld [wFullColorProductionReconstructionLedger], a" not in recorder
    completion = _routine(
        lifecycle,
        "RecordAndCompleteYellowPresentationRoot::",
        "; Resolve current ordinary-map policy while hidden.",
    )
    assert completion.index("and a") < completion.index("ret z")
    assert completion.index("cp TRANSITION_REQUIRED") < completion.index("jp nz, FullColorProductionTransitionFailed")
    begin_root = _routine(
        lifecycle,
        "BeginForcedYellowPresentationRoot::",
        "RecordAndCompleteYellowPresentationRoot::",
    )
    assert "DisableLCD" not in begin_root
    assert begin_root.index("ConcealForcedYellowPresentation") < begin_root.index("call BeginForcedYellowPresentation")
    assert completion.index("call nz, DisableLCD") < completion.index("CommitYellowPresentationTileMapForContext")
    assert completion.index("CompleteYellowPresentation") < completion.rindex("ldh [rLCDC], a")
    assert completion.index("CommitYellowPresentationTileMapForContext") < completion.index("RecordYellowReconstructionComplete")
    commit = _routine(
        lifecycle,
        "CommitYellowPresentationTileMapForContext::",
        "; Resolve current ordinary-map policy while hidden.",
    )
    assert commit.index("ldh [rVBK], a") < commit.index("set 3, [hl]")
    assert "ld de, vBGMap1" in commit
    assert "ld b, SCREEN_HEIGHT" in commit
    assert "ld c, SCREEN_WIDTH" in commit

    color = _routine(
        lifecycle,
        "ReconstructFullColorMapEntry::",
        "; No inputs. Returns carry clear when Yellow owns before PartyMenuInit.",
    )
    hidden_roots = color.index("CompleteFullColorProductionHiddenVisibleRootsSelected")
    assert hidden_roots < color.index("set 4, [hl]")
    assert hidden_roots < color.index("set 5, [hl]")
    assert color.index("set 7, [hl]") < color.index("ColorReconstructionBarrier")


def test_production_color_vblank_builds_next_oam_after_visible_commit() -> None:
    lifecycle = (REPOSITORY_ROOT / "engine/full_color/lifecycle.asm").read_text()
    route = lifecycle.split("RunFullColorProductionVBlank::", 1)[1].split("\n\tret\n", 1)[0]
    assert "PrepareFullColorProductionOAMForOwnedVBlank" not in route
    assert "RunFullColorOwnershipVBlank" in route
    vblank = (REPOSITORY_ROOT / "home/vblank.asm").read_text()
    assert vblank.index("FullColorProductionVBlankVisibleRouteComplete::") < vblank.index(
        "PrepareFullColorProductionPostVisibleRoute"
    )
    adapter = _routine(
        lifecycle,
        "PrepareFullColorProductionOAMForOwnedVBlank::",
        "; Called only after RouteRendererOwnershipVBlank",
    )
    assert "PrepareOAMData.build" in adapter
    assert "EnqueueFullColorOAMBatchFar" in adapter


def test_all_four_production_movement_roots_reach_paired_submissions() -> None:
    overworld = (REPOSITORY_ROOT / "home/overworld.asm").read_text()
    expected = {
        "ScheduleNorthRowRedraw::": "SubmitFullColorProductionNorthRowFar",
        "ScheduleSouthRowRedraw::": "SubmitFullColorProductionSouthRowFar",
        "ScheduleEastColumnRedraw::": "SubmitFullColorProductionEastColumnFar",
        "ScheduleWestColumnRedraw::": "SubmitFullColorProductionWestColumnFar",
    }
    labels = list(expected)
    for index, (label, adapter) in enumerate(expected.items()):
        end = labels[index + 1] if index + 1 < len(labels) else "; function to write the tiles"
        routine = _routine(overworld, label, end)
        assert "FULL_COLOR_PRODUCTION_ACTIVATED" in routine
        assert adapter in routine

    lifecycle = (REPOSITORY_ROOT / "engine/full_color/lifecycle.asm").read_text()
    movement = _routine(lifecycle, "SubmitFullColorProductionNorthRowFar::", "; Production-only bank adapter")
    assert movement.count("EnqueueFullColorMovementRowStrip") == 2
    assert "EnqueueFullColorMovementColumnStrip" in movement
    assert "EnqueueFullColorMapConnection" not in movement
    consume = _routine(
        lifecycle,
        "FullColorProductionConsumeAcceptedRedraw:",
        "SubmitFullColorProductionNorthRowFar::",
    )
    assert consume.index("ret c") < consume.index("hRedrawRowOrColumnMode")
    connection_root = _routine(overworld, ".loadNewMap ; load the connected map", ".didNotEnterConnectedMap")
    assert connection_root.index("LoadMapHeader") < connection_root.index("BeginOrdinaryMapPresentationRoot")
    assert connection_root.index("BeginOrdinaryMapPresentationRoot") < connection_root.index("RunPaletteCommand")
    assert connection_root.index("LoadTileBlockMap") < connection_root.index("CompleteConnectedMapPresentationRoot")
    assert "SubmitFullColorProductionConnectionFar" not in connection_root
    completion = _routine(
        lifecycle,
        "CompleteConnectedMapPresentationRoot::",
        "; Farcall-safe movement producers",
    )
    assert completion.index("SnapshotFullColorMapAuthority") < completion.index("EnqueueFullColorMapConnection")
    assert "EnqueueFullColorMapRectangle" not in completion
    assert completion.index("CancelFullColorSchedulerSelected") < completion.index("EnqueueFullColorMapConnection")
    assert completion.index("EnqueueFullColorMapConnection") < completion.index("CommitFullColorHiddenDestinationRoot")
    assert "ld hl, wTileMap + SCREEN_WIDTH * (SCREEN_HEIGHT - 2)" in completion
    assert "TILEMAP_WIDTH * (SCREEN_HEIGHT - 2)" in completion


def test_production_vblank_uses_farcall_stable_tristate_routing() -> None:
    scheduler = (REPOSITORY_ROOT / "engine/full_color/scheduler.asm").read_text()
    router = _routine(scheduler, "RouteRendererOwnershipVBlank::", "RunFullColorOwnershipVBlank::")
    assert "ld e, VBLANK_ROUTE_YELLOW" in router
    assert "ld e, VBLANK_ROUTE_COLOR" in router
    assert "ld e, VBLANK_ROUTE_CLOSED" in router
    vblank = (REPOSITORY_ROOT / "home/vblank.asm").read_text()
    dispatch = _routine(vblank, "IF FULL_COLOR_PRODUCTION_ACTIVATED", "ENDC")
    assert "farcall RouteRendererOwnershipVBlank" in dispatch
    assert "ld a, e" in dispatch
    assert "cp VBLANK_ROUTE_YELLOW" in dispatch


def test_vblank_router_returns_yellow_or_closed_in_farcall_stable_e(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    rom.set_owner("RENDERER_YELLOW", "YELLOW_ACTIVE")
    _run_color_vblank_without_legacy_oam_build(rom)
    assert rom.emulator.pyboy.register_file.E == rom.constants["VBLANK_ROUTE_YELLOW"]

    rom.write2("wRendererPhase", rom.constants["YELLOW_RECONSTRUCTING"])
    rom.write2("wRendererAdmissionOpen", 0)
    _run_color_vblank_without_legacy_oam_build(rom)
    assert rom.emulator.pyboy.register_file.E == rom.constants["VBLANK_ROUTE_CLOSED"]


def test_vblank_router_runs_color_route_and_returns_farcall_stable_e(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    called = False

    def finish_color_route(_: object) -> None:
        nonlocal called
        called = True
        stack = rom.emulator.pyboy.register_file.SP
        low = rom.emulator.pyboy.memory[stack]
        high = rom.emulator.pyboy.memory[stack + 1]
        rom.emulator.pyboy.register_file.SP = stack + 2
        rom.emulator.pyboy.register_file.PC = low | high << 8

    symbol = "RunFullColorProductionVBlank"
    bank = rom.emulator.symbol_banks[symbol]
    address = rom.emulator.symbols[symbol]
    rom.emulator.pyboy.hook_register(bank, address, finish_color_route, None)
    try:
        _run_color_vblank_without_legacy_oam_build(rom)
    finally:
        rom.emulator.pyboy.hook_deregister(bank, address)

    assert called
    assert rom.emulator.pyboy.register_file.E == rom.constants["VBLANK_ROUTE_COLOR"]


@pytest.mark.parametrize(
    ("wrapper", "destination", "source_offsets"),
    (
        ("ScheduleNorthRowRedraw", 0x9800, tuple(range(40))),
        ("ScheduleSouthRowRedraw", 0x9A00, tuple(range(320, 360))),
        (
            "ScheduleEastColumnRedraw",
            0x9812,
            tuple(offset for row in range(18) for offset in (row * 20 + 18, row * 20 + 19)),
        ),
        (
            "ScheduleWestColumnRedraw",
            0x9800,
            tuple(offset for row in range(18) for offset in (row * 20, row * 20 + 1)),
        ),
    ),
)
def test_real_movement_root_commits_authoritative_paired_strip(
    transition_rom: TransitionRom,
    wrapper: str,
    destination: int,
    source_offsets: tuple[int, ...],
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    rom.write1("wMapViewVRAMPointer", 0x9800, 2)
    tile_map = rom.emulator.symbols["wTileMap"]
    source = bytes((index * 29 + 7) & 0xFF for index in range(360))
    rom.emulator.pyboy.memory[tile_map:tile_map + len(source)] = source
    expected_tiles = bytes(source[offset] for offset in source_offsets)
    attributes = _linked_bytes(rom, "FullColorOverworldTileAttributes", 256)
    expected_attributes = bytes(attributes[tile] for tile in expected_tiles)

    assert not rom.call(wrapper) & 0x10
    assert rom.read2("wFullColorRequestCount") == 1
    assert rom.emulator.pyboy.memory[rom.emulator.symbols["hRedrawRowOrColumnMode"]] == 0
    _run_color_vblank_without_legacy_oam_build(rom)

    width = 20 if "Row" in wrapper else 2
    rows = 2 if "Row" in wrapper else 18
    for row in range(rows):
        start = row * width
        end = start + width
        address = destination + row * 32
        assert rom.emulator.read_vram_bank(0, address, width) == expected_tiles[start:end]
        assert rom.emulator.read_vram_bank(1, address, width) == expected_attributes[start:end]
    assert rom.read2("wFullColorRequestCount") == 0


@pytest.mark.parametrize(
    ("direction", "map_y", "source_row", "destination"),
    (
        ("northbound", 4, 0, 0x9800),
        ("southbound", 0, 16, 0x9A00),
    ),
)
def test_real_connection_root_commits_correct_authoritative_direction(
    transition_rom: TransitionRom,
    direction: str,
    map_y: int,
    source_row: int,
    destination: int,
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    rom.write1("wCurMap", ROUTE_1)
    rom.write1("wYCoord", map_y)
    rom.write1("wMapViewVRAMPointer", 0x9800, 2)
    rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    tile_map = rom.emulator.symbols["wTileMap"]
    source = bytes((index * 17 + 5) & 0xFF for index in range(360))
    rom.emulator.pyboy.memory[tile_map:tile_map + len(source)] = source
    expected_tiles = source[source_row * 20:(source_row + 2) * 20]
    attributes = _linked_bytes(rom, "FullColorOverworldTileAttributes", 256)
    expected_attributes = bytes(attributes[tile] for tile in expected_tiles)
    generation = rom.read2("wRendererGeneration", 4)
    assert bytes(rom.emulator.pyboy.memory[tile_map:tile_map + 360]) == source

    assert not rom.call("CompleteConnectedMapPresentationRoot") & 0x10, direction

    assert rom.read2("wRendererGeneration", 4) == generation
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]
    assert rom.read2("wFullColorAuthorityY") == map_y
    assert rom.read2("wFullColorAuthorityVRAMView", 2) == 0x9800
    assert rom.read2("wFullColorRequestCount") == 0
    prior_svbk = rom.emulator.pyboy.memory[0xFF70]
    rom.emulator.pyboy.memory[0xFF70] = 2
    try:
        staged = bytes(
            rom.emulator.pyboy.memory[
                rom.emulator.symbols["wFullColorProducerTiles"] + offset
            ]
            for offset in range(40)
        )
    finally:
        rom.emulator.pyboy.memory[0xFF70] = prior_svbk
    assert staged == expected_tiles
    for row in range(2):
        start = row * 20
        end = start + 20
        address = destination + row * 32
        assert rom.emulator.read_vram_bank(0, address, 20) == expected_tiles[start:end]
        assert rom.emulator.read_vram_bank(1, address, 20) == expected_attributes[start:end]


@pytest.mark.parametrize(
    "context",
    (
        "RENDERER_CONTEXT_MENU",
        "RENDERER_CONTEXT_DIALOGUE",
        "RENDERER_CONTEXT_BATTLE",
    ),
)
def test_forced_yellow_real_root_return_has_five_stable_color_frames(
    transition_rom: TransitionRom,
    context: str,
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    rom.write1("wCurMap", ROUTE_1)
    rom.write1("wUnusedObtainedBadges", 0)
    rom.write1("wMapViewVRAMPointer", 0x9800, 2)
    rom.emulator.pyboy.memory[rom.emulator.symbols["hOnCGB"]] = 1
    rom.write1("wDefaultPaletteCommand", SET_PAL_GENERIC)
    # The direct-root fixture begins at the real pre-display boundary, with
    # LCD already hidden. This avoids inventing scanline timing while leaving
    # every ownership and destination commit intact.
    rom.emulator.pyboy.memory[0xFF40] = 0x11
    rom.emulator.pyboy.memory[0xFFFF] = 0
    rom.emulator.pyboy.memory[0xFF0F] = 0

    assert not rom.call("BeginForcedYellowPresentationRoot", c=rom.constants[context]) & 0x10
    assert rom.read2("wFullColorProductionReturnContext") == rom.constants[context]
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_YELLOW"]
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_RECONSTRUCTING"]
    assert rom.read2("wFullColorProductionTransitionStatus") == rom.constants["TRANSITION_REQUIRED"]
    tile_map = rom.emulator.symbols["wTileMap"]
    destination = bytes((index * 13 + rom.constants[context]) & 0xFF for index in range(360))
    rom.emulator.pyboy.memory[tile_map:tile_map + len(destination)] = destination
    # OAM DMA and root call ordering have dedicated coverage. Drive the exact
    # three completion seams here so the direct-call fixture doesn't mistake
    # its synthetic HRAM return trap for boot's installed DMA routine.
    rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    assert not rom.call("RecordYellowReconstructionComplete") & 0x10
    assert not rom.call("CompleteYellowPresentation") & 0x10
    rom.emulator.pyboy.memory[0xFF40] = 0x91
    assert rom.read2("wFullColorProductionReconstructionLedger", 2) == 0xFF
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_YELLOW"]
    assert rom.emulator.pyboy.memory[0xFF40] & 0x80
    assert rom.read1("wCurMap") == ROUTE_1
    assert not rom.read1("wUnusedObtainedBadges") & 1
    assert rom.read2("wRendererPhase") == rom.constants["YELLOW_ACTIVE"]
    assert rom.read2("wRendererAdmissionOpen") == 1
    assert rom.read2("wRendererJobState") == rom.constants["RENDERER_JOB_NONE"]
    assert rom.read2("wFullColorProductionTransitionStatus") == rom.constants["TRANSITION_NONE"]
    rom.call("ResolveCurrentOrdinaryMapOwner")
    assert rom.emulator.pyboy.register_file.A == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]

    assert not rom.call(
        "SetFullColorProductionReturnContext",
        a=rom.constants["RENDERER_CONTEXT_ORDINARY_MAP"],
    ) & 0x10
    assert not rom.call("ResolveOrdinaryMapPresentation") & 0x10
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]
    assert rom.read2("wRendererPhase") == rom.constants["OVERWORLD_RECONSTRUCTING"]
    assert rom.read2("wRendererAdmissionOpen") == 0
    rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    rom.emulator.pyboy.memory[0xFF80] = 0xC9
    assert not rom.call("CompleteOrdinaryMapPresentationRoot") & 0x10
    generation = rom.read2("wRendererGeneration", 4)
    assert rom.read2("wRendererOwner") == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]
    assert rom.read2("wRendererAdmissionOpen") == 1

    for _ in range(5):
        _run_color_vblank_without_legacy_oam_build(rom)
        assert rom.emulator.pyboy.register_file.E == rom.constants["VBLANK_ROUTE_COLOR"]
        assert rom.read2("wRendererOwner") == rom.constants["RENDERER_FULL_COLOR_OVERWORLD"]
        assert rom.read2("wRendererPhase") == rom.constants["OVERWORLD_ACTIVE"]
        assert rom.read2("wRendererAdmissionOpen") == 1
        assert rom.read2("wRendererGeneration", 4) == generation


@pytest.mark.parametrize("root", ("menu", "dialogue", "battle"))
def test_actual_forced_root_and_natural_map_return_leave_five_quiet_color_frames(
    transition_rom: TransitionRom,
    root: str,
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    rom.write1("wCurMap", ROUTE_1)
    rom.write1("wUnusedObtainedBadges", 0)
    rom.write1("wMapViewVRAMPointer", 0x9800, 2)
    rom.emulator.pyboy.memory[rom.emulator.symbols["hOnCGB"]] = 1
    rom.emulator.pyboy.memory[rom.emulator.symbols["wOnSGB"]] = 1
    rom.write1("wDefaultPaletteCommand", SET_PAL_GENERIC)
    rom.emulator.pyboy.memory[0xFF50] = 1
    rom.emulator.pyboy.memory[0xFF40] = 0x11
    rom.emulator.pyboy.memory[0xFFFF] = 0
    rom.emulator.pyboy.memory[0xFF0F] = 0
    rom.emulator.pyboy.memory[0xFF80] = 0xC9  # installed hDMARoutine return
    mechanics = _prepare_actual_root_return(rom)

    if root == "menu":
        rom.emulator.pyboy.memory[rom.emulator.symbols["hTextID"]] = 0
        reached = _run_with_stubbed_mechanics(rom, "DisplayTextID", mechanics)
        assert {"HandleMenuInput", "LoadCurrentMapView"} <= reached
    elif root == "dialogue":
        rom.emulator.pyboy.memory[rom.emulator.symbols["hTextID"]] = 3
        rom.write1("wCurMapTextPtr", rom.emulator.symbols["Route1_TextPointers"], 2)
        mechanics.update({
            "PrintText_NoCreatingTextBox": None,
            "WaitForTextScrollButtonPress": None,
        })
        reached = _run_with_stubbed_mechanics(rom, "DisplayTextID", mechanics)
        assert {"PrintText_NoCreatingTextBox", "LoadCurrentMapView"} <= reached
    else:
        rom.write1("wEnemyMonSpecies2", 200)

        def select_battle_default() -> None:
            rom.write1("wDefaultPaletteCommand", 1)  # SET_PAL_BATTLE

        battle_mechanics = {
            "InitBattleVariables": None,
            "GetTrainerInformation": None,
            "ReadTrainer": None,
            "DoBattleTransitionAndInitBattleVariables": None,
            "_LoadTrainerPic": None,
            "CopyUncompressedPicToTilemap": None,
            "SlidePlayerAndEnemySilhouettesOnScreen": select_battle_default,
            "StartBattle": None,
            "EndOfBattle": None,
            "Delay3": None,
            "ClearSprites": None,
            "UpdateSprites": mechanics["UpdateSprites"],
        }
        reached = _run_with_stubbed_mechanics(rom, "InitBattleCommon", battle_mechanics)
        assert {"SlidePlayerAndEnemySilhouettesOnScreen", "StartBattle", "EndOfBattle"} <= reached
        assert rom.read2("wRendererOwner") == rom.constants["RENDERER_YELLOW"]
        map_mechanics = {
            "DisableLCD": mechanics["DisableLCD"],
            "EnableLCD": mechanics["EnableLCD"],
            "ResetMapVariables": None,
            "LoadTextBoxTilePatterns": None,
            "LoadMapHeader": None,
            "InitMapSprites": None,
            "LoadScreenRelatedData": mechanics["LoadCurrentMapView"],
            "UpdateMusic6Times": None,
            "PlayDefaultMusicFadeOutCurrent": None,
        }
        _run_with_stubbed_mechanics(rom, "LoadMapData", map_mechanics)

    assert rom.read2("wRendererOwner") == rom.constants[
        "RENDERER_FULL_COLOR_OVERWORLD"
    ]
    assert rom.read2("wRendererPhase") == rom.constants["OVERWORLD_ACTIVE"]
    assert rom.read2("wRendererAdmissionOpen") == 1
    _assert_five_quiet_color_frames(rom)


def test_battle_default_replays_genuine_battle_palette_not_black(
    transition_rom: TransitionRom,
) -> None:
    rom = transition_rom
    _require_activated(rom)
    rom.emulator.pyboy.memory[rom.emulator.symbols["hOnCGB"]] = 1
    rom.emulator.pyboy.memory[rom.emulator.symbols["wOnSGB"]] = 1
    rom.emulator.pyboy.memory[0xFF50] = 1
    rom.emulator.pyboy.memory[0xFF40] &= 0x7F
    rom.emulator.pyboy.memory[0xFFFF] = 0
    rom.emulator.pyboy.memory[0xFF0F] = 0
    rom.write1("wBattleMonSpecies", 25)
    rom.write1("wPartyMon1Species", 25)
    rom.write1("wPlayerMonNumber", 0)
    rom.write1("wPlayerHPBarColor", 0)
    rom.write1("wEnemyHPBarColor", 2)
    rom.write1("wEnemyMonSpecies2", 19)
    assert not rom.call("RunPaletteCommand", b=1) & 0x10  # SET_PAL_BATTLE
    assert rom.read1("wDefaultPaletteCommand") == 1
    # The genuine linked battle command above establishes SET_PAL_BATTLE as
    # Yellow's default. Give the commit seam distinct observable payloads for
    # DEFAULT and BATTLE_BLACK: mutating the linked selector changes both the
    # recorded command and hardware result, even when synthetic battle inputs
    # happen to map both stock packets to identical colors.
    battle_palette = bytes((index * 23 + 9) & 0xFF for index in range(64))
    battle_black = bytes((index * 5 + 1) & 0xFF for index in range(64))
    assert battle_palette != battle_black

    rom.set_owner("RENDERER_FULL_COLOR_OVERWORLD", "OVERWORLD_ACTIVE")
    assert not rom.call(
        "SetFullColorProductionReturnContext",
        a=rom.constants["RENDERER_CONTEXT_BATTLE"],
    ) & 0x10
    assert not rom.call("BeginForcedYellowPresentation") & 0x10
    _write_palette_ram(rom, _linked_bytes(rom, "FullColorOverworldBGPalettes", 64))
    _fill_vram_bank(rom, 1, 0x5A)
    rom.emulator.pyboy.memory[0xFF80] = 0xC9
    commands: list[int] = []

    def publish_selected_palette(_: object) -> None:
        command = rom.emulator.pyboy.register_file.B
        commands.append(command)
        _write_palette_ram(
            rom,
            battle_palette if command == 0xFF else battle_black,
        )
        _fill_vram_bank(rom, 1, 0)
        registers = rom.emulator.pyboy.register_file
        stack = registers.SP
        registers.PC = (
            rom.emulator.pyboy.memory[stack]
            | rom.emulator.pyboy.memory[stack + 1] << 8
        )
        registers.SP = stack + 2

    palette_bank = rom.emulator.symbol_banks["RunPaletteCommand"]
    palette_address = rom.emulator.symbols["RunPaletteCommand"]
    rom.emulator.pyboy.hook_register(
        palette_bank, palette_address, publish_selected_palette, None,
    )
    try:
        assert not rom.call("CommitYellowPresentationTileMapForContext") & 0x10
    finally:
        rom.emulator.pyboy.hook_deregister(palette_bank, palette_address)

    assert commands == [0xFF]  # SET_PAL_DEFAULT, never SET_PAL_BATTLE_BLACK
    observed = rom.emulator.read_palette_ram()
    assert observed == battle_palette
    assert observed != battle_black


def test_activated_oam_build_maps_final_picture_identity() -> None:
    source = (REPOSITORY_ROOT / "engine/gfx/sprite_oam.asm").read_text()
    mapping = _routine(source, ".spriteusesOBP0", ".nextSprite")
    assert "IF DEF(PHASE2_AUDIT) || FULL_COLOR_PRODUCTION_ACTIVATED" in mapping
    assert "MapFullColorOAMAttributeFar" in mapping
