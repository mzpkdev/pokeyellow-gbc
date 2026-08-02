"""Real cold-boot coverage for the normal Phase 2 debug product."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import (
    PALLET_TOWN,
    REDS_HOUSE_1F,
    finish_rival_battle_and_leave_lab,
    follow_oak_and_receive_pikachu,
    walk_from_bedroom_to_oak,
)
from tools.rom_tests.scenarios.viridian_city import ROUTE_1
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


BOOT_SAMPLES = (120, 480, 540, 600)
POST_INPUT_SAMPLES = (900, 1050, 1200, 1500, 1800)
INPUTS = {
    650: "start",
    700: "a",
    750: "start",
    800: "a",
    900: "start",
    950: "a",
    1050: "start",
    1100: "a",
    1200: "start",
    1250: "a",
    1500: "start",
    1550: "a",
}
BROKEN_CANARY = Path("/tmp/pokeyellow-phase4-early-canary.gbc")
BROKEN_CANARY_SHA256 = (
    "4149a646dd3043c4bab6bff7c8a65b601688cf6ab89e5885ed31709bb5fa3df4"
)


@dataclass(frozen=True)
class ColdBootObservation:
    frames: dict[int, bytes]
    states: dict[int, tuple[int, int, int, int]]
    color_counts: dict[int, int]
    chromatic_samples: frozenset[int]
    longest_blank_run_after_title: int
    longest_static_run: int


@dataclass(frozen=True)
class MapEntryJourneyObservation:
    bedroom_digest: bytes
    pallet_digest: bytes
    bedroom_state: tuple[int, int, int, int, int, int, int]
    pallet_state: tuple[int, int, int, int, int, int, int]
    pallet_color_count: int
    pallet_tile_indices: bytes
    pallet_non_palette_attributes: bytes
    pallet_static_tile_graphics: bytes
    pallet_bg_palettes: bytes
    pallet_obj_palettes: bytes
    pallet_bg_palette_frames: tuple[bytes, ...]
    pallet_obj_palette_frames: tuple[bytes, ...]
    pallet_bg_maps: bytes
    pallet_shadow_oam: bytes
    pallet_hardware_oam: bytes
    pallet_display_registers: tuple[int, int, int, int, int]


def _rom_symbol_bytes(rom: Path, symbols: Path, name: str, size: int) -> bytes:
    location = next(
        line.split(maxsplit=1)[0]
        for line in symbols.read_text(encoding="utf-8").splitlines()
        if line.endswith(f" {name}")
    )
    bank, address = (int(part, 16) for part in location.split(":"))
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom.read_bytes()[offset : offset + size]


def _visible_bg_planes(emulator: Emulator) -> tuple[bytes, bytes]:
    """Read the 20x18 viewport from both CGB BG-map banks."""

    lcdc = emulator.pyboy.memory[0xFF40]
    map_base = 0x9C00 if lcdc & 0x08 else 0x9800
    tile_x = emulator.pyboy.memory[0xFF43] // 8
    tile_y = emulator.pyboy.memory[0xFF42] // 8
    tiles = bytearray()
    attributes = bytearray()
    for row in range(18):
        for column in range(20):
            offset = ((tile_y + row) & 31) * 32 + ((tile_x + column) & 31)
            address = map_base + offset
            tiles.extend(emulator.read_vram_bank(0, address, 1))
            attributes.append(emulator.read_vram_bank(1, address, 1)[0])
    return bytes(tiles), bytes(attributes)


def _static_overworld_tile_graphics(emulator: Emulator) -> bytes:
    return emulator.read_vram_bank(0, 0x8000, 0x1800)


def _oam_geometry_and_control(oam: bytes) -> bytes:
    """Keep the complete four-entry player OAM geometry/control surface."""
    assert len(oam) == 160
    return oam[:16]


def _digest(image: Image.Image) -> bytes:
    return hashlib.sha256(image.tobytes()).digest()


def _is_blank_presentation(image: Image.Image) -> bool:
    colors = image.getcolors(maxcolors=image.width * image.height)
    assert colors is not None
    return len(colors) <= 2 and all(max(rgb) - min(rgb) <= 8 for _, rgb in colors)


def _is_chromatic(image: Image.Image) -> bool:
    colors = image.getcolors(maxcolors=image.width * image.height)
    assert colors is not None
    return any(max(rgb) - min(rgb) >= 16 for _, rgb in colors)


def _observe(
    rom: Path,
    symbols: Path,
    results: Path,
    *,
    through_frame: int = 1800,
) -> ColdBootObservation:
    emulator = Emulator(rom=rom, symbols=symbols, results=results, cgb=True)
    frames: dict[int, bytes] = {}
    states: dict[int, tuple[int, int, int, int]] = {}
    color_counts: dict[int, int] = {}
    chromatic_samples: set[int] = set()
    blank_run = 0
    longest_blank_run = 0
    static_run = 0
    longest_static_run = 0
    prior_digest: bytes | None = None
    try:
        for frame in range(1, through_frame + 1):
            button = INPUTS.get(frame)
            if button is not None:
                emulator.pyboy.button(button, delay=2)
            emulator.tick()
            image = emulator.capture_screen()
            digest = _digest(image)

            static_run = static_run + 1 if digest == prior_digest else 1
            longest_static_run = max(longest_static_run, static_run)
            prior_digest = digest

            if frame >= 600 and _is_blank_presentation(image):
                blank_run += 1
                longest_blank_run = max(longest_blank_run, blank_run)
            else:
                blank_run = 0

            if frame in BOOT_SAMPLES + POST_INPUT_SAMPLES:
                colors = image.getcolors(maxcolors=image.width * image.height)
                assert colors is not None
                frames[frame] = digest
                color_counts[frame] = len(colors)
                if _is_chromatic(image):
                    chromatic_samples.add(frame)
                states[frame] = (
                    emulator.read("wCurMap"),
                    emulator.read("wStatusFlags6"),
                    emulator.read("hSoftReset"),
                    emulator.read("wMaxMenuItem"),
                )
    finally:
        emulator.close()

    return ColdBootObservation(
        frames=frames,
        states=states,
        color_counts=color_counts,
        chromatic_samples=frozenset(chromatic_samples),
        longest_blank_run_after_title=longest_blank_run,
        longest_static_run=longest_static_run,
    )


def _observe_map_entry_journey(
    rom: Path, symbols: Path, results: Path
) -> MapEntryJourneyObservation:
    emulator = Emulator(rom=rom, symbols=symbols, results=results, cgb=True)
    try:
        boot_inputs = {
            650: "start", 700: "a", 750: "start", 800: "a",
            900: "start", 950: "a", 1050: "start", 1100: "a",
            1200: "start", 1250: "a",
        }
        for frame in range(1, 1321):
            button = boot_inputs.get(frame)
            if button is not None:
                emulator.pyboy.button(button, delay=2)
            emulator.tick()
        emulator.advance_until(
            emulator.is_in_bedroom_overworld,
            button="a", max_presses=100, description="bedroom overworld",
        )
        emulator.tick(120)
        bedroom = emulator.capture_screen()
        bedroom_state = (
            emulator.read("wCurMap"), emulator.read("wXCoord"),
            emulator.read("wYCoord"), emulator.pyboy.memory[0xFF40],
            emulator.read("hLoadedROMBank"), emulator.read("wRendererOwner"),
            emulator.read("wRendererPhase"),
        )
        assert 0xD000 <= emulator.pyboy.register_file.SP <= 0xDFFF
        assert emulator.pyboy.memory[0xFFFF] == 0x0D

        def advance(symbol: str, value: int, button: str, description: str) -> None:
            emulator.advance_until(
                lambda: emulator.read(symbol) == value,
                button=button, max_presses=140, description=description,
            )

        advance("wXCoord", 5, "right", "bedroom aisle")
        advance("wYCoord", 1, "up", "bedroom stairs")
        advance("wCurMap", REDS_HOUSE_1F, "right", "first floor")
        advance("wYCoord", 6, "down", "house exit row")
        advance("wXCoord", 3, "left", "house exit")
        advance("wCurMap", PALLET_TOWN, "down", "Pallet Town")
        bg_palette_frames = []
        obj_palette_frames = []
        for _ in range(120):
            emulator.tick()
            bg_palette_frames.append(emulator.read_palette_ram())
            obj_palette_frames.append(
                emulator.read_palette_ram(object_palettes=True)
            )
        pallet = emulator.capture_screen()
        colors = pallet.getcolors(maxcolors=pallet.width * pallet.height)
        assert colors is not None
        pallet_state = (
            emulator.read("wCurMap"), emulator.read("wXCoord"),
            emulator.read("wYCoord"), emulator.pyboy.memory[0xFF40],
            emulator.read("hLoadedROMBank"), emulator.read("wRendererOwner"),
            emulator.read("wRendererPhase"),
        )
        pallet_tile_indices, pallet_non_palette_attributes = _visible_bg_planes(
            emulator
        )
        assert 0xD000 <= emulator.pyboy.register_file.SP <= 0xDFFF
        assert 0 < emulator.read("hLoadedROMBank") < 0x40
        advance("wYCoord", 7, "down", "Pallet movement")
        return MapEntryJourneyObservation(
            bedroom_digest=_digest(bedroom),
            pallet_digest=_digest(pallet),
            bedroom_state=bedroom_state,
            pallet_state=pallet_state,
            pallet_color_count=len(colors),
            pallet_tile_indices=pallet_tile_indices,
            pallet_non_palette_attributes=pallet_non_palette_attributes,
            pallet_static_tile_graphics=_static_overworld_tile_graphics(emulator),
            pallet_bg_palettes=emulator.read_palette_ram(),
            pallet_obj_palettes=emulator.read_palette_ram(object_palettes=True),
            pallet_bg_palette_frames=tuple(bg_palette_frames),
            pallet_obj_palette_frames=tuple(obj_palette_frames),
            pallet_bg_maps=(
                emulator.read_vram_bank(0, 0x9800, 0x800)
                + emulator.read_vram_bank(1, 0x9800, 0x800)
            ),
            pallet_shadow_oam=_oam_geometry_and_control(
                emulator.read_bytes("wShadowOAM", 160)
            ),
            pallet_hardware_oam=_oam_geometry_and_control(
                emulator.read_memory(0xFE00, 160)
            ),
            pallet_display_registers=tuple(
                emulator.pyboy.memory[address]
                for address in (0xFF43, 0xFF42, 0xFF4B, 0xFF4A, 0xFF40)
            ),
        )
    finally:
        emulator.close()


def test_release_and_normal_debug_cold_boot_and_advance_together(tmp_path: Path) -> None:
    """Use two fresh zero-RAM CGB sessions, never a loaded save-state."""

    release = _observe(
        REPOSITORY_ROOT / "pokeyellow.gbc",
        REPOSITORY_ROOT / "pokeyellow.sym",
        tmp_path / "release",
    )
    debug = _observe(
        REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        REPOSITORY_ROOT / "pokeyellow_debug.sym",
        tmp_path / "debug",
    )

    for frame in (480, 540, 600):
        assert debug.frames[frame] == release.frames[frame]
        assert debug.states[frame] == release.states[frame]

    # Real Game Freak and title frames contain visible non-white CGB color.
    assert release.color_counts[120] >= 4
    assert release.color_counts[480] >= 4
    assert {120, 480} <= release.chromatic_samples
    assert {120, 480} <= debug.chromatic_samples

    # Repeated real START/A input must leave the title path and converge on the
    # same main-menu/new-game states without comparing timing-sensitive PCs.
    for frame in (1500, 1800):
        assert debug.states[frame] == release.states[frame]
    assert release.frames[900] != release.frames[600]
    assert release.states[1500][3] == debug.states[1500][3] == 1
    assert release.states[1500][0] == debug.states[1500][0] == 0x26

    assert release.longest_blank_run_after_title < 300
    assert debug.longest_blank_run_after_title < 300
    assert release.longest_static_run < 300
    assert debug.longest_static_run < 300


def test_known_broken_phase4_preview_is_rejected_when_present(tmp_path: Path) -> None:
    """Keep the user-observed whiteout binary as a local negative control."""

    if not BROKEN_CANARY.is_file():
        return
    digest = hashlib.sha256(BROKEN_CANARY.read_bytes()).hexdigest()
    if digest != BROKEN_CANARY_SHA256:
        return

    broken = _observe(
        BROKEN_CANARY,
        REPOSITORY_ROOT / "pokeyellow_debug.sym",
        tmp_path / "broken-canary",
    )
    assert broken.longest_blank_run_after_title >= 900
    assert broken.longest_static_run >= 900


def test_debug_oak_intro_bedroom_movement_and_pallet_map_entry(tmp_path: Path) -> None:
    release = _observe_map_entry_journey(
        REPOSITORY_ROOT / "pokeyellow.gbc",
        REPOSITORY_ROOT / "pokeyellow.sym",
        tmp_path / "release-journey",
    )
    debug = _observe_map_entry_journey(
        REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        REPOSITORY_ROOT / "pokeyellow_debug.sym",
        tmp_path / "debug-journey",
    )

    assert debug.bedroom_digest == release.bedroom_digest
    assert debug.bedroom_state[0:4] == release.bedroom_state[0:4] == (
        0x26, 3, 6, 0xE3,
    )
    assert release.bedroom_state[5:] == debug.bedroom_state[5:] == (0, 0)
    assert 0 < release.bedroom_state[4] < 0x40
    assert 0 < debug.bedroom_state[4] < 0x40
    assert release.pallet_state[0:4] == debug.pallet_state[0:4] == (
        PALLET_TOWN, 5, 6, 0xE3,
    )
    assert release.pallet_state[5:] == (0, 0)
    assert debug.pallet_state[5:] == (0, 0)
    assert release.pallet_color_count >= 4
    assert debug.pallet_color_count >= 4
    assert debug.pallet_tile_indices == release.pallet_tile_indices
    assert debug.pallet_non_palette_attributes == release.pallet_non_palette_attributes
    assert debug.pallet_static_tile_graphics == release.pallet_static_tile_graphics
    assert debug.pallet_bg_maps == release.pallet_bg_maps
    assert debug.pallet_shadow_oam == release.pallet_shadow_oam
    assert debug.pallet_hardware_oam == release.pallet_hardware_oam
    assert debug.pallet_display_registers == release.pallet_display_registers
    assert debug.pallet_digest != release.pallet_digest
    pallet_payload = _rom_symbol_bytes(
        REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        REPOSITORY_ROOT / "pokeyellow_debug.sym",
        "YellowDebugPalletBGPalette", 8,
    )
    assert debug.pallet_bg_palettes[:32] == pallet_payload * 4
    assert debug.pallet_bg_palettes[32:] == release.pallet_bg_palettes[32:]
    assert debug.pallet_obj_palettes == release.pallet_obj_palettes
    assert len(set(debug.pallet_bg_palette_frames)) == 1
    assert len(set(debug.pallet_obj_palette_frames)) == 1
    assert len(set(release.pallet_bg_palette_frames)) == 1
    assert len(set(release.pallet_obj_palette_frames)) == 1


def test_normal_debug_gameplay_uses_only_yellows_palette_publisher() -> None:
    overworld = (REPOSITORY_ROOT / "home/overworld.asm").read_text(encoding="utf-8")
    vblank = (REPOSITORY_ROOT / "home/vblank.asm").read_text(encoding="utf-8")
    palettes = (REPOSITORY_ROOT / "engine/gfx/palettes.asm").read_text(
        encoding="utf-8"
    )
    assert "QueueYellowPaletteLane" not in overworld
    assert "CommitYellowPaletteLaneVBlank" not in vblank
    assert "SelectYellowDebugOverworldBGPalette" in palettes
    assert "ELIF DEF(FULL_COLOR_PHASE2_ACTIVE)" not in vblank


@pytest.mark.parametrize("product", ("pokeyellow", "pokeyellow_debug"))
def test_natural_oak_capture_route1_and_party_return_are_playable(
    tmp_path: Path, product: str,
) -> None:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=tmp_path / "natural-story",
        cgb=True,
    )
    try:
        boot_inputs = {
            650: "start", 700: "a", 750: "start", 800: "a",
            900: "start", 950: "a", 1050: "start", 1100: "a",
            1200: "start", 1250: "a",
        }
        for frame in range(1, 1321):
            button = boot_inputs.get(frame)
            if button is not None:
                emulator.pyboy.button(button, delay=2)
            emulator.tick()
        emulator.advance_until(
            emulator.is_in_bedroom_overworld,
            button="a", max_presses=100, description="bedroom overworld",
        )
        emulator.tick(120)
        walk_from_bedroom_to_oak(emulator)
        follow_oak_and_receive_pikachu(emulator)
        finish_rival_battle_and_leave_lab(emulator)
        assert emulator.read("wCurMap") == PALLET_TOWN
        assert (emulator.read("wRendererOwner"), emulator.read("wRendererPhase")) == (
            0, 0,
        )
        assert not _is_blank_presentation(emulator.capture_screen())
        emulator.save_screenshot("pallet-after-lab.png")

        def advance(symbol: str, value: int, button: str, description: str) -> None:
            emulator.advance_until(
                lambda: emulator.read(symbol) == value,
                button=button, max_presses=180, description=description,
            )

        # The lab blocks a direct northbound line from its door. Walk around
        # its west wall before taking the same x=10 north road used earlier.
        x = emulator.read("wXCoord")
        advance("wXCoord", 8, "right" if x < 8 else "left", "west of Oak's Lab")
        advance("wYCoord", 6, "up", "past Oak's Lab")
        advance("wXCoord", 10, "right", "Pallet north road")
        advance("wYCoord", 0, "up", "Pallet north edge")
        advance("wCurMap", ROUTE_1, "up", "Route 1 connection")
        route_bg_palette_frames = []
        route_obj_palette_frames = []
        for _ in range(120):
            emulator.tick()
            route_bg_palette_frames.append(emulator.read_palette_ram())
            route_obj_palette_frames.append(
                emulator.read_palette_ram(object_palettes=True)
            )
        assert len(set(route_bg_palette_frames)) == 1
        assert len(set(route_obj_palette_frames)) == 1
        assert (emulator.read("wRendererOwner"), emulator.read("wRendererPhase")) == (
            0, 0,
        )

        route_y = emulator.read("wYCoord")
        advance("wYCoord", route_y - 3, "up", "Route 1 sustained walking")
        emulator.tick(120)
        if emulator.is_in_battle():
            emulator.advance_until(
                lambda: not emulator.is_in_battle(),
                button="a", max_presses=300, description="Route 1 battle end",
            )
            emulator.tick(120)
        before_tiles, before_attributes = _visible_bg_planes(emulator)
        before_player_pixels = emulator.read_bytes("wSpritePlayerStateData1YPixels", 3)
        before_player_oam = tuple(
            emulator.read_bytes(f"wShadowOAMSprite{index:02d}", 2)
            for index in range(4)
        )
        emulator.save_screenshot("route1-before-menu.png")

        emulator.press("start")
        emulator.advance_until(
            lambda: emulator.read("wRendererOwner") == 0,
            button="start", max_presses=8, description="start-menu overlay",
        )
        assert emulator.read("wRendererPhase") == 0
        emulator.save_screenshot("route1-start-menu.png")
        emulator.press("a")
        assert emulator.read("wRendererPhase") == 0
        emulator.save_screenshot("route1-party.png")
        assert emulator.read("wMenuWatchedKeys") == 3
        assert emulator.read("wJoyIgnore") == 0
        emulator.press("b")
        emulator.press("b")
        emulator.tick(120)

        emulator.save_screenshot("route1-after-party-return.png")
        assert _visible_bg_planes(emulator) == (before_tiles, before_attributes)
        assert emulator.read_bytes("wSpritePlayerStateData1YPixels", 3) == before_player_pixels
        assert tuple(
            emulator.read_bytes(f"wShadowOAMSprite{index:02d}", 2)
            for index in range(4)
        ) == before_player_oam
        assert emulator.pyboy.memory[0xFF4A] == 0x90
        assert not _is_blank_presentation(emulator.capture_screen())
    finally:
        emulator.close()
