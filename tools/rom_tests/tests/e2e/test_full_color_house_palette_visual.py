"""Visual regression for Color activation followed by Red's-house re-entry."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import (
    PALLET_TOWN,
    REDS_HOUSE_1F,
    walk_from_bedroom_to_pallet,
)
from tools.rom_tests.scenarios.renderer_mode import select_renderer_mode
from tools.rom_tests.scenarios.viridian_city import walk_to_value
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


RLCDC = 0xFF40
RSCX = 0xFF43
RSCY = 0xFF42
RWY = 0xFF4A
SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144
ANIMATED_OVERWORLD_TILES = frozenset((0x03, 0x14))


def _visible_background_plane(emulator: Emulator, bank: int) -> bytes:
    lcdc = emulator.pyboy.memory[RLCDC]
    base = 0x9C00 if lcdc & (1 << 3) else 0x9800
    scx = emulator.pyboy.memory[RSCX]
    scy = emulator.pyboy.memory[RSCY]
    return bytes(
        emulator.read_vram_bank(
            bank,
            base
            + (((scy + y) & 0xFF) // 8) * 32
            + (((scx + x) & 0xFF) // 8),
            1,
        )[0]
        for y in range(SCREEN_HEIGHT)
        for x in range(SCREEN_WIDTH)
    )


def _visible_background_tiles(emulator: Emulator) -> bytes:
    return _visible_background_plane(emulator, 0)


def _visible_background_attributes(emulator: Emulator) -> bytes:
    return _visible_background_plane(emulator, 1)


def _capture_stable_background(
    emulator: Emulator,
) -> tuple[
    Image.Image,
    bytes,
    bytes,
    tuple[tuple[int, int, int, int], ...],
]:
    """Capture one natural frame and describe its dynamic background regions."""
    assert emulator.pyboy.memory[RWY] >= SCREEN_HEIGHT
    lcdc = emulator.pyboy.memory[RLCDC]
    image = emulator.capture_screen()
    visible_tiles = _visible_background_tiles(emulator)
    visible_attributes = _visible_background_attributes(emulator)

    sprite_height = 16 if lcdc & (1 << 2) else 8
    sprite_regions = []
    for offset in range(0, 0xA0, 4):
        y = emulator.pyboy.memory[0xFE00 + offset] - 16
        x = emulator.pyboy.memory[0xFE00 + offset + 1] - 8
        region = (
            max(0, x - 2),
            max(0, y - 2),
            min(SCREEN_WIDTH, x + 10),
            min(SCREEN_HEIGHT, y + sprite_height + 2),
        )
        if region[0] < region[2] and region[1] < region[3]:
            sprite_regions.append(region)
    return image, visible_tiles, visible_attributes, tuple(sprite_regions)


def _cross_map_on_first_visible_frame(
    emulator: Emulator,
    *,
    target_map: int,
    button: str,
    target_state: tuple[int, int, int, int, int],
    max_frames: int = 720,
) -> tuple[
    Image.Image,
    bytes,
    bytes,
    tuple[tuple[int, int, int, int], ...],
    tuple[int, int, int, int, int],
]:
    """Use natural input and capture the first rendered target-map frame."""
    for frame in range(max_frames):
        if frame % 30 == 0 and emulator.read("wCurMap") != target_map:
            emulator.pyboy.button(button, delay=10)
        emulator.tick()
        state = (
            emulator.read("wCurMap"),
            emulator.read("wYCoord"),
            emulator.read("wXCoord"),
            emulator.pyboy.memory[RSCY],
            emulator.pyboy.memory[RSCX],
        )
        if (
            state == target_state
            and emulator.pyboy.memory[RLCDC] & (1 << 7)
            and emulator.pyboy.memory[RWY] >= SCREEN_HEIGHT
            and emulator.read("wJoyIgnore") == 0
        ):
            # PyBoy exposes the framebuffer completed by the preceding tick.
            # Hold the exact camera state for one complete scanout before capture.
            emulator.tick()
            presented_state = (
                emulator.read("wCurMap"),
                emulator.read("wYCoord"),
                emulator.read("wXCoord"),
                emulator.pyboy.memory[RSCY],
                emulator.pyboy.memory[RSCX],
            )
            assert presented_state == state
            image, tiles, attributes, sprite_regions = _capture_stable_background(
                emulator
            )
            return image, tiles, attributes, sprite_regions, presented_state
    emulator.save_screenshot("timeout-first-visible-pallet-frame.png")
    raise AssertionError(
        f"Timed out waiting for first visible Pallet frame: "
        f"map={emulator.read('wCurMap')}, y={emulator.read('wYCoord')}, "
        f"x={emulator.read('wXCoord')}"
    )


def _first_mismatch(left: bytes, right: bytes) -> int | None:
    return next(
        (index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]),
        None,
    )


def test_color_pallet_pixels_survive_reds_house_round_trip() -> None:
    """Generate the good frame, repeat the house warp, and compare rendered pixels."""
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_house_palette_visual.py::color-pallet-house-round-trip"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )

    try:
        reach_bedroom_overworld(emulator)
        select_renderer_mode(emulator, yellow_mode=True)
        walk_from_bedroom_to_pallet(emulator)
        select_renderer_mode(emulator, yellow_mode=False)

        good_state = (
            emulator.read("wCurMap"),
            emulator.read("wYCoord"),
            emulator.read("wXCoord"),
            emulator.pyboy.memory[RSCY],
            emulator.pyboy.memory[RSCX],
        )
        emulator.tick()
        assert (
            emulator.read("wCurMap"),
            emulator.read("wYCoord"),
            emulator.read("wXCoord"),
            emulator.pyboy.memory[RSCY],
            emulator.pyboy.memory[RSCX],
        ) == good_state
        good_palette = emulator.read_palette_ram()
        good_attributes = emulator.read_vram_bank(1, 0x9800, 0x400)
        good, good_tiles, good_visible_attributes, good_sprite_regions = (
            _capture_stable_background(emulator)
        )

        walk_to_value(
            emulator,
            "wCurMap",
            REDS_HOUSE_1F,
            "up",
            "Red's house after Color activation",
        )
        emulator.tick(120)
        (
            bad,
            bad_tiles,
            bad_visible_attributes,
            bad_sprite_regions,
            bad_state,
        ) = _cross_map_on_first_visible_frame(
            emulator,
            target_map=PALLET_TOWN,
            button="down",
            target_state=good_state,
        )
        bad_palette = emulator.read_palette_ram()
        bad_attributes = emulator.read_vram_bank(1, 0x9800, 0x400)

        good.save(results / "good.png")
        bad.save(results / "bad.png")

        compared_good = good.copy()
        compared_bad = bad.copy()
        for image, visible_tiles in (
            (compared_good, good_tiles),
            (compared_bad, bad_tiles),
        ):
            pixels = image.load()
            for index, tile in enumerate(visible_tiles):
                if tile in ANIMATED_OVERWORLD_TILES:
                    pixels[index % SCREEN_WIDTH, index // SCREEN_WIDTH] = (0, 0, 0)
        for region in good_sprite_regions + bad_sprite_regions:
            compared_good.paste((0, 0, 0), region)
            compared_bad.paste((0, 0, 0), region)
        compared_good.save(results / "compared-good.png")
        compared_bad.save(results / "compared-bad.png")

        difference = ImageChops.difference(compared_good, compared_bad)
        difference.save(results / "diff.png")
        diagnostics = {
            "good_state": good_state,
            "bad_state": bad_state,
            "palette_first_mismatch": _first_mismatch(good_palette, bad_palette),
            "attribute_first_mismatch": _first_mismatch(
                good_attributes, bad_attributes
            ),
            "visible_tile_first_mismatch": _first_mismatch(good_tiles, bad_tiles),
            "visible_attribute_first_mismatch": _first_mismatch(
                good_visible_attributes, bad_visible_attributes
            ),
            "changed_pixel_bbox": difference.getbbox(),
        }
        (results / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        assert good_state == bad_state
        assert good_tiles == bad_tiles
        assert good_visible_attributes == bad_visible_attributes, diagnostics
        assert difference.getbbox() is None, diagnostics
    except BaseException:
        emulator.save_screenshot("failure.png")
        raise
    finally:
        emulator.close()
