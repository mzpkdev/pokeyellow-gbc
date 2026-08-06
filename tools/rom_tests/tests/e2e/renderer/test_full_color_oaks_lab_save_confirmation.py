"""Natural visual regression for Oak's Lab's Color-mode save confirmation."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import (
    OAKS_LAB,
    SCRIPT_OAKSLAB_PLAYER_DONT_GO_AWAY,
    walk_from_bedroom_to_oak,
)
from tools.rom_tests.scenarios.renderer_mode import move_cursor_to
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


LAB_TILESET = 5  # Oak's Lab uses Yellow's DOJO tileset.
START_MENU_SAVE_INDEX = 3  # A fresh game has no Pokédex entry.
TWO_OPTION_MENU = 0x14
PAD_A_OR_B = 0x03
WINDOW_MAP = 0x9C00
RLCDC = 0xFF40
RWY = 0xFF4A
RWX = 0xFF4B
SCREEN_WIDTH = 20
SCREEN_HEIGHT = 18
PALETTE_MASK = 0x07
TEXT_PALETTE = 7

# PrintText's bottom dialogue box plus SaveTheGame_YesOrNo's hlcoord 0,7 box.
SAVE_UI_RECTS = ((0, 12, 20, 18), (0, 7, 6, 12))


def _linked_bytes(product: str, symbol: str, size: int) -> bytes:
    symbol_lines = (REPOSITORY_ROOT / f"{product}.sym").read_text(
        encoding="utf-8"
    ).splitlines()
    addresses = Emulator._parse_symbols(symbol_lines)
    banks = Emulator._parse_symbol_banks(symbol_lines)
    address = addresses[symbol]
    offset = banks[symbol] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[offset : offset + size]


def _window_plane(emulator: Emulator, bank: int) -> bytes:
    return b"".join(
        emulator.read_vram_bank(bank, WINDOW_MAP + row * 32, SCREEN_WIDTH)
        for row in range(SCREEN_HEIGHT)
    )


def _ui_cell_indexes() -> tuple[int, ...]:
    return tuple(
        row * SCREEN_WIDTH + column
        for left, top, right, bottom in SAVE_UI_RECTS
        for row in range(top, bottom)
        for column in range(left, right)
    )


def _rgb555(color: bytes) -> tuple[int, int, int]:
    value = int.from_bytes(color, "little")
    # PyBoy presents each CGB RGB555 channel in its upper five RGB888 bits.
    return tuple(((value >> shift) & 0x1F) << 3 for shift in (0, 5, 10))


def _tile_color_zero_pixels(
    emulator: Emulator,
    tile: int,
    attribute: int,
) -> tuple[tuple[int, int], ...]:
    if emulator.pyboy.memory[RLCDC] & 0x10:
        address = 0x8000 + tile * 16
    else:
        signed_tile = tile if tile < 0x80 else tile - 0x100
        address = 0x9000 + signed_tile * 16
    tile_data = emulator.read_vram_bank((attribute >> 3) & 1, address, 16)
    pixels = []
    for output_y in range(8):
        source_y = 7 - output_y if attribute & 0x40 else output_y
        low, high = tile_data[source_y * 2 : source_y * 2 + 2]
        for output_x in range(8):
            source_x = 7 - output_x if attribute & 0x20 else output_x
            bit = 7 - source_x
            color = ((high >> bit) & 1) << 1 | ((low >> bit) & 1)
            if color == 0:
                pixels.append((output_x, output_y))
    return tuple(pixels)


def _render_window_region(
    emulator: Emulator,
    tiles: bytes,
    attributes: bytes,
    palettes: bytes,
    rect: tuple[int, int, int, int],
) -> Image.Image:
    left, top, right, bottom = rect
    image = Image.new("RGB", ((right - left) * 8, (bottom - top) * 8))
    pixels = image.load()
    for row in range(top, bottom):
        for column in range(left, right):
            index = row * SCREEN_WIDTH + column
            tile = tiles[index]
            attribute = attributes[index]
            if emulator.pyboy.memory[RLCDC] & 0x10:
                address = 0x8000 + tile * 16
            else:
                signed_tile = tile if tile < 0x80 else tile - 0x100
                address = 0x9000 + signed_tile * 16
            tile_data = emulator.read_vram_bank((attribute >> 3) & 1, address, 16)
            for output_y in range(8):
                source_y = 7 - output_y if attribute & 0x40 else output_y
                low, high = tile_data[source_y * 2 : source_y * 2 + 2]
                for output_x in range(8):
                    source_x = 7 - output_x if attribute & 0x20 else output_x
                    bit = 7 - source_x
                    color = ((high >> bit) & 1) << 1 | ((low >> bit) & 1)
                    palette_offset = (attribute & PALETTE_MASK) * 8 + color * 2
                    pixels[
                        (column - left) * 8 + output_x,
                        (row - top) * 8 + output_y,
                    ] = _rgb555(palettes[palette_offset : palette_offset + 2])
    return image


def _is_save_confirmation(emulator: Emulator) -> bool:
    return (
        emulator.read("wCurMap") == OAKS_LAB
        and emulator.read("wBattleAndStartSavedMenuItem") == START_MENU_SAVE_INDEX
        and emulator.read("wTextBoxID") == TWO_OPTION_MENU
        and emulator.read("wTopMenuItemY") == 8
        and emulator.read("wTopMenuItemX") == 1
        and emulator.read("wMaxMenuItem") == 1
        and emulator.read("wMenuWatchedKeys") == PAD_A_OR_B
        and emulator.read("wCurrentMenuItem") == 0
    )


def test_natural_color_oaks_lab_save_confirmation_is_true_white() -> None:
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_oaks_lab_save_confirmation.py::oak-lab-save-confirmation"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )
    expected_palettes = _linked_bytes(product, "FullColorIndoorBGPalettes", 64)
    expected_attributes = _linked_bytes(product, "FullColorGymTileAttributes", 256)

    try:
        reach_bedroom_overworld(emulator)
        walk_from_bedroom_to_oak(emulator)
        emulator.advance_until(
            lambda: emulator.read("wCurMap") == OAKS_LAB,
            button="a",
            max_presses=80,
            description="Oak's natural escort into his lab",
        )
        emulator.advance_until(
            lambda: emulator.read("wOaksLabCurScript")
            == SCRIPT_OAKSLAB_PLAYER_DONT_GO_AWAY,
            button="a",
            max_presses=80,
            description="Oak's Lab starter-selection control",
        )
        emulator.tick(60)

        assert emulator.read("wCurMap") == OAKS_LAB
        assert emulator.read("wCurMapTileset") == LAB_TILESET
        assert emulator.read("wUnusedObtainedBadges") & 1 == 0
        assert emulator.read("wPassiveFullColorActive") == 1

        emulator.press("start", wait_frames=60)
        move_cursor_to(
            emulator,
            "wCurrentMenuItem",
            START_MENU_SAVE_INDEX,
            description="the fresh-game Start-menu Save item",
        )
        emulator.tick(5)
        before_image = emulator.capture_screen()
        before_attributes = _window_plane(emulator, 1)
        before_image.save(results / "before-start-menu-save.png")

        emulator.press("a", wait_frames=60)
        emulator.advance_until(
            lambda: _is_save_confirmation(emulator),
            button="a",
            max_presses=3,
            description="Save Yes/No confirmation",
        )
        emulator.tick()
        assert _is_save_confirmation(emulator)
        assert emulator.pyboy.memory[RWY] == 0
        assert emulator.pyboy.memory[RWX] == 7

        actual_image = emulator.capture_screen()
        actual_tiles = _window_plane(emulator, 0)
        actual_attributes = _window_plane(emulator, 1)
        hardware_palettes = emulator.read_palette_ram()
        ui_indexes = _ui_cell_indexes()
        expected_ui_attributes = bytes(
            expected_attributes[actual_tiles[i]] for i in ui_indexes
        )
        actual_ui_attributes = bytes(actual_attributes[i] for i in ui_indexes)
        attribute_mismatches = [
            {
                "column": index % SCREEN_WIDTH,
                "row": index // SCREEN_WIDTH,
                "tile": actual_tiles[index],
                "actual": actual_attributes[index],
                "expected": expected_attributes[actual_tiles[index]],
            }
            for index in ui_indexes
            if actual_attributes[index] != expected_attributes[actual_tiles[index]]
        ]
        stale_exposure_cells = [
            (index % SCREEN_WIDTH, index // SCREEN_WIDTH)
            for index in ui_indexes
            if before_attributes[index] & PALETTE_MASK == 0
            and expected_attributes[actual_tiles[index]] & PALETTE_MASK == TEXT_PALETTE
        ]

        expected_white = _rgb555(expected_palettes[56:58])
        lab_off_white = _rgb555(expected_palettes[0:2])
        reference_image = actual_image.copy()
        mask_image = Image.new("RGB", actual_image.size, (0, 0, 0))
        reference_pixels = reference_image.load()
        mask_pixels = mask_image.load()
        white_pixel_mismatches = []
        white_pixel_count = 0
        for index in ui_indexes:
            column, row = index % SCREEN_WIDTH, index // SCREEN_WIDTH
            expected_attribute = expected_attributes[actual_tiles[index]]
            for tile_x, tile_y in _tile_color_zero_pixels(
                emulator, actual_tiles[index], expected_attribute
            ):
                x, y = column * 8 + tile_x, row * 8 + tile_y
                white_pixel_count += 1
                if actual_image.getpixel((x, y)) != expected_white:
                    white_pixel_mismatches.append((x, y, actual_image.getpixel((x, y))))
                reference_pixels[x, y] = expected_white
                mask_pixels[x, y] = (255, 255, 255)

        difference = ImageChops.difference(actual_image, reference_image)
        actual_image.save(results / "actual-save-confirmation.png")
        reference_image.save(results / "reference-true-white-ui.png")
        difference.save(results / "diff-true-white-ui.png")
        mask_image.save(results / "true-white-ui-mask.png")
        (results / "actual-ui-attributes.bin").write_bytes(actual_ui_attributes)
        (results / "reference-ui-attributes.bin").write_bytes(expected_ui_attributes)
        diagnostics = {
            "route_endpoint": {
                "map": emulator.read("wCurMap"),
                "tileset": emulator.read("wCurMapTileset"),
                "y": emulator.read("wYCoord"),
                "x": emulator.read("wXCoord"),
                "oak_lab_script": emulator.read("wOaksLabCurScript"),
            },
            "confirmation_menu": {
                "text_box_id": emulator.read("wTextBoxID"),
                "top_y": emulator.read("wTopMenuItemY"),
                "top_x": emulator.read("wTopMenuItemX"),
                "max_item": emulator.read("wMaxMenuItem"),
                "watched_keys": emulator.read("wMenuWatchedKeys"),
                "current_item": emulator.read("wCurrentMenuItem"),
            },
            "expected_true_white_rgb": expected_white,
            "oak_lab_palette0_off_white_rgb": lab_off_white,
            "hardware_palette7_hex": hardware_palettes[56:64].hex(),
            "reference_palette7_hex": expected_palettes[56:64].hex(),
            "ui_cell_count": len(ui_indexes),
            "white_pixel_count": white_pixel_count,
            "stale_palette0_exposure_cells": stale_exposure_cells,
            "attribute_mismatches": attribute_mismatches,
            "white_pixel_mismatch_count": len(white_pixel_mismatches),
            "first_white_pixel_mismatches": white_pixel_mismatches[:32],
            "diff_bbox": difference.getbbox(),
        }
        (results / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        assert expected_white == (248, 248, 248)
        assert lab_off_white != expected_white
        assert hardware_palettes == expected_palettes
        assert stale_exposure_cells, "test did not cover Oak's Lab palette-0 cells"
        assert all(
            attribute & PALETTE_MASK == TEXT_PALETTE
            for attribute in expected_ui_attributes
        )
        assert not attribute_mismatches, diagnostics
        assert white_pixel_count > 1000
        assert not white_pixel_mismatches, diagnostics
        assert difference.getbbox() is None, diagnostics

        restored: dict[str, object] = {}

        def capture_restored_underlying_screen(_: object) -> None:
            if restored:
                return
            restored_tiles = _window_plane(emulator, 0)
            restored_attributes = _window_plane(emulator, 1)
            restored["image"] = emulator.capture_screen()
            restored["tiles"] = restored_tiles
            restored["attributes"] = restored_attributes
            restored["reference"] = _render_window_region(
                emulator,
                restored_tiles,
                bytes(expected_attributes[tile] for tile in restored_tiles),
                expected_palettes,
                SAVE_UI_RECTS[1],
            )
            restored["tilemap"] = emulator.read_memory(
                emulator.symbols["wTileMap"], SCREEN_WIDTH * SCREEN_HEIGHT
            )
            restored["wy"] = emulator.pyboy.memory[RWY]
            restored["wx"] = emulator.pyboy.memory[RWX]
            restored["current_item"] = emulator.read("wCurrentMenuItem")

        restore_boundary = "LoadScreenTilesFromBuffer2"
        restore_hook = (
            emulator.symbol_banks[restore_boundary],
            emulator.symbols[restore_boundary],
        )
        emulator.pyboy.hook_register(
            *restore_hook,
            capture_restored_underlying_screen,
            "capture restored two-option background",
        )
        try:
            emulator.press("b", wait_frames=60)
        finally:
            emulator.pyboy.hook_deregister(*restore_hook)

        assert restored, "two-option cancellation never restored its underlying screen"
        restored_image = restored["image"]
        restored_tiles = restored["tiles"]
        restored_attributes = restored["attributes"]
        restored_reference = restored["reference"]
        restored_tilemap = restored["tilemap"]
        assert isinstance(restored_image, Image.Image)
        assert isinstance(restored_tiles, bytes)
        assert isinstance(restored_attributes, bytes)
        assert isinstance(restored_reference, Image.Image)
        assert isinstance(restored_tilemap, bytes)
        expected_restored_attributes = bytes(
            expected_attributes[tile] for tile in restored_tiles
        )
        restored_attribute_mismatches = [
            {
                "column": index % SCREEN_WIDTH,
                "row": index // SCREEN_WIDTH,
                "tile": restored_tiles[index],
                "actual": restored_attributes[index],
                "expected": expected_restored_attributes[index],
            }
            for index in range(SCREEN_WIDTH * SCREEN_HEIGHT)
            if restored_attributes[index] != expected_restored_attributes[index]
        ]
        restored_region = restored_image.crop(
            tuple(coordinate * 8 for coordinate in SAVE_UI_RECTS[1])
        )
        restored_difference = ImageChops.difference(
            restored_region, restored_reference
        )
        restored_image.save(results / "actual-restored-underlying-screen.png")
        restored_region.save(results / "actual-restored-underlying-region.png")
        restored_reference.save(results / "reference-restored-underlying-region.png")
        restored_difference.save(results / "diff-restored-underlying-region.png")
        (results / "actual-restored-attributes.bin").write_bytes(
            restored_attributes
        )
        (results / "reference-restored-attributes.bin").write_bytes(
            expected_restored_attributes
        )
        diagnostics["dismissal"] = {
            "window_y": restored["wy"],
            "window_x": restored["wx"],
            "current_item": restored["current_item"],
            "tilemap_matches_published_tiles": restored_tilemap == restored_tiles,
            "attribute_mismatches": restored_attribute_mismatches,
            "restored_region_diff_bbox": restored_difference.getbbox(),
            "final_window_y": emulator.pyboy.memory[RWY],
            "final_map": emulator.read("wCurMap"),
            "final_passive_active": emulator.read("wPassiveFullColorActive"),
        }
        (results / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        assert restored["wy"] == 0
        assert restored["wx"] == 7
        assert restored["current_item"] == 1
        assert restored_tilemap == restored_tiles
        assert not restored_attribute_mismatches, diagnostics
        assert restored_difference.getbbox() is None, diagnostics
        assert emulator.read("wCurMap") == OAKS_LAB
        assert emulator.read("wPassiveFullColorActive") == 1
    except BaseException:
        emulator.save_screenshot("failure.png")
        raise
    finally:
        emulator.close()
