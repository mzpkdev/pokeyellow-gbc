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
TV_TABLE_TILE_SIGNATURE = (
    (0x26, 0x27, 0x28, 0x29),
    (0x36, 0x37, 0x38, 0x39),
    (0x2C, 0x2A, 0x2A, 0x2B),
    (0x3C, 0x3A, 0x3A, 0x3B),
)
TV_TABLE_PALETTE = 5


def _prepare_results(results: Path) -> None:
    expected_parent = REPOSITORY_ROOT / "test-results"
    if results.parent != expected_parent:
        raise AssertionError(f"refusing to clean unexpected result path: {results}")
    results.mkdir(parents=True, exist_ok=True)
    for artifact in results.iterdir():
        if artifact.is_file() or artifact.is_symlink():
            artifact.unlink()


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


def _visible_background_tile_grid(emulator: Emulator, bank: int) -> bytes:
    lcdc = emulator.pyboy.memory[RLCDC]
    base = 0x9C00 if lcdc & (1 << 3) else 0x9800
    scx = emulator.pyboy.memory[RSCX]
    scy = emulator.pyboy.memory[RSCY]
    plane = emulator.read_vram_bank(bank, base, 0x400)
    return bytes(
        plane[
            (((scy // 8) + row) % 32) * 32
            + (((scx // 8) + column) % 32)
        ]
        for row in range(SCREEN_HEIGHT // 8)
        for column in range(SCREEN_WIDTH // 8)
    )


def _find_tile_signature(
    tiles: bytes,
    signature: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, int], ...]:
    width = SCREEN_WIDTH // 8
    height = SCREEN_HEIGHT // 8
    signature_height = len(signature)
    signature_width = len(signature[0])
    return tuple(
        (row, column)
        for row in range(height - signature_height + 1)
        for column in range(width - signature_width + 1)
        if all(
            tiles[(row + dy) * width + column : (row + dy) * width + column + signature_width]
            == bytes(signature[dy])
            for dy in range(signature_height)
        )
    )


def _signature_values(
    plane: bytes,
    origin: tuple[int, int],
    signature: tuple[tuple[int, ...], ...],
) -> bytes:
    width = SCREEN_WIDTH // 8
    row, column = origin
    return bytes(
        plane[(row + dy) * width + column + dx]
        for dy in range(len(signature))
        for dx in range(len(signature[dy]))
    )


def _linked_bytes(product: str, symbol: str, size: int) -> bytes:
    symbol_lines = (
        (REPOSITORY_ROOT / f"{product}.sym")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    addresses = Emulator._parse_symbols(symbol_lines)
    banks = Emulator._parse_symbol_banks(symbol_lines)
    address = addresses[symbol]
    offset = banks[symbol] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[offset : offset + size]


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
    """Check the stable interior, then repeat its warp and compare Pallet pixels."""
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_house_palette_visual.py::color-pallet-house-round-trip"
    )
    _prepare_results(results)
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
        expected_overworld_palettes = _linked_bytes(
            product, "FullColorOverworldBGPalettes", 64
        )
        expected_overworld_attributes = _linked_bytes(
            product, "FullColorOverworldTileAttributes", 256
        )
        expected_interior_palettes = _linked_bytes(
            product, "FullColorIndoorBGPalettes", 64
        )
        expected_interior_attributes = _linked_bytes(
            product, "FullColorRedsHouseTileAttributes", 256
        )

        walk_to_value(
            emulator,
            "wCurMap",
            REDS_HOUSE_1F,
            "up",
            "Red's house after Color activation",
        )
        emulator.tick(120)
        interior_state = (
            emulator.read("wCurMap"),
            emulator.read("wYCoord"),
            emulator.read("wXCoord"),
            emulator.pyboy.memory[RSCY],
            emulator.pyboy.memory[RSCX],
        )
        interior_passive_state = (
            emulator.read("wPassiveFullColorActive"),
            emulator.read("wPassiveFullColorPalettePending"),
            emulator.read("wPassiveFullColorClearChunks"),
        )
        interior_palette = emulator.read_palette_ram()
        interior, _, _, _ = _capture_stable_background(emulator)
        interior_tiles = _visible_background_tile_grid(emulator, 0)
        interior_attributes = _visible_background_tile_grid(emulator, 1)
        interior_matches = _find_tile_signature(
            interior_tiles, TV_TABLE_TILE_SIGNATURE
        )
        furniture_attributes = (
            _signature_values(
                interior_attributes,
                interior_matches[0],
                TV_TABLE_TILE_SIGNATURE,
            )
            if len(interior_matches) == 1
            else b""
        )
        interior_visible_mismatches = [
            {
                "visible_index": index,
                "tile": tile,
                "actual": attribute,
                "expected": expected_interior_attributes[tile],
            }
            for index, (tile, attribute) in enumerate(
                zip(interior_tiles, interior_attributes)
            )
            if attribute != expected_interior_attributes[tile]
        ]
        interior.save(results / "reds-house-stable.png")

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
            "interior_state": interior_state,
            "interior_passive_state": interior_passive_state,
            "interior_palette_first_authority_mismatch": _first_mismatch(
                interior_palette, expected_interior_palettes
            ),
            "interior_visible_attribute_mismatch_count": len(
                interior_visible_mismatches
            ),
            "interior_visible_attribute_first_mismatch": (
                interior_visible_mismatches[0]
                if interior_visible_mismatches
                else None
            ),
            "tv_table_matches": interior_matches,
            "tv_table_attributes": list(furniture_attributes),
            "good_state": good_state,
            "bad_state": bad_state,
            "good_palette_first_authority_mismatch": _first_mismatch(
                good_palette, expected_overworld_palettes
            ),
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

        assert interior_state[:3] == (REDS_HOUSE_1F, 7, 2), diagnostics
        assert interior_passive_state == (1, 0, 0), diagnostics
        assert interior_palette == expected_interior_palettes, diagnostics
        assert not interior_visible_mismatches, diagnostics
        assert len(interior_matches) == 1, diagnostics
        assert all(
            expected_interior_attributes[tile] == TV_TABLE_PALETTE
            for row in TV_TABLE_TILE_SIGNATURE
            for tile in row
        ), diagnostics
        assert furniture_attributes == bytes(
            [TV_TABLE_PALETTE] * sum(map(len, TV_TABLE_TILE_SIGNATURE))
        ), diagnostics
        assert good_palette == expected_overworld_palettes, diagnostics
        assert all(
            attribute == expected_overworld_attributes[tile]
            for tile, attribute in zip(good_tiles, good_visible_attributes)
        ), diagnostics
        assert good_state == bad_state
        assert good_tiles == bad_tiles
        assert good_visible_attributes == bad_visible_attributes, diagnostics
        assert difference.getbbox() is None, diagnostics
    except BaseException:
        emulator.save_screenshot("failure.png")
        raise
    finally:
        emulator.close()
