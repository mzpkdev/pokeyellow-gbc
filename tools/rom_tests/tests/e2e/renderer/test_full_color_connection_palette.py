"""Natural framewise proof of palette authority across an outdoor connection."""

from __future__ import annotations

from functools import partial
import hashlib
import json

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import complete_oaks_lab_intro
from tools.rom_tests.scenarios.renderer_mode import select_renderer_mode
from tools.rom_tests.scenarios.viridian_city import ROUTE_1, VIRIDIAN_CITY, walk_to_value
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory
from tools.rom_tests.tests.e2e.journey.test_full_color_cold_boot_journey import (
    _linked_bytes,
    _linked_overworld_bg_palettes,
)


RLCDC = 0xFF40
RSCX = 0xFF43
RSCY = 0xFF42
SCREEN_WIDTH = 20
SCREEN_HEIGHT = 18
TILEMAP_AREA = 0x400


def _visible_tile_attribute_state(emulator: Emulator) -> tuple[bytes, bytes]:
    lcdc = emulator.pyboy.memory[RLCDC]
    tilemap_base = 0x9C00 if lcdc & (1 << 3) else 0x9800
    tilemap = emulator.read_vram_bank(0, tilemap_base, TILEMAP_AREA)
    attributes = emulator.read_vram_bank(1, tilemap_base, TILEMAP_AREA)
    scroll_x = emulator.pyboy.memory[RSCX]
    scroll_y = emulator.pyboy.memory[RSCY]
    indices = tuple(
        ((scroll_y // 8 + row) & 31) * 32
        + ((scroll_x // 8 + column) & 31)
        for row in range(SCREEN_HEIGHT)
        for column in range(SCREEN_WIDTH)
    )
    return (
        bytes(tilemap[index] for index in indices),
        bytes(attributes[index] for index in indices),
    )


def test_route1_to_viridian_never_presents_destination_before_its_palette() -> None:
    results = result_directory(
        "test_full_color_connection_palette.py::route1-to-viridian-framewise"
    )
    emulator = Emulator(
        rom=REPOSITORY_ROOT / "pokeyellow.gbc",
        symbols=REPOSITORY_ROOT / "pokeyellow.sym",
        results=results,
        cgb=True,
    )
    attributes_by_tile = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )
    route_palettes = _linked_overworld_bg_palettes(
        "pokeyellow", ROUTE_1, y_coord=0
    )
    viridian_palettes = _linked_overworld_bg_palettes(
        "pokeyellow", VIRIDIAN_CITY, y_coord=35
    )
    frames: list[dict[str, object]] = []
    route_boundary_visible: tuple[bytes, bytes] | None = None
    route_presentation_seen = False
    first_destination_frame: int | None = None
    transition_established = False

    try:
        complete_oaks_lab_intro(
            emulator,
            bedroom_setup=partial(select_renderer_mode, yellow_mode=False),
        )

        # Reach the last Route 1 coordinate through ordinary player input.
        # Encounters, if any, are completed by the shared natural journey helper.
        for symbol, value, button, description in (
            ("wXCoord", 8, "left", "west side of Oak's Lab"),
            ("wYCoord", 2, "up", "north Pallet Town"),
            ("wXCoord", 10, "right", "Route 1 entrance"),
            ("wCurMap", ROUTE_1, "up", "Route 1"),
            ("wYCoord", 30, "up", "south Route 1 clearing"),
            ("wXCoord", 6, "left", "first passage"),
            ("wYCoord", 25, "up", "first passage north"),
            ("wXCoord", 12, "right", "second passage"),
            ("wYCoord", 21, "up", "second passage north"),
            ("wXCoord", 9, "left", "central passage"),
            ("wYCoord", 15, "up", "central passage north"),
            ("wXCoord", 14, "right", "final passage"),
            ("wYCoord", 3, "up", "north Route 1 clearing"),
            ("wXCoord", 10, "left", "Viridian entrance"),
            ("wYCoord", 0, "up", "Route 1 north boundary"),
        ):
            walk_to_value(emulator, symbol, value, button, description)

        assert (emulator.read("wCurMap"), emulator.read("wYCoord")) == (
            ROUTE_1,
            0,
        )
        assert emulator.read_palette_ram() == route_palettes
        route_boundary_visible = _visible_tile_attribute_state(emulator)
        emulator.save_screenshot("route1-before-viridian-connection.png")

        emulator.pyboy.button("up", delay=2)
        for _ in range(240):
            emulator.tick()
            lcdc = emulator.pyboy.memory[RLCDC]
            current_map = emulator.read("wCurMap")
            visible_tiles, visible_attributes = _visible_tile_attribute_state(emulator)
            palette = emulator.read_palette_ram()
            presented = bool(lcdc & 0x80)
            attribute_mismatches = sum(
                actual != attributes_by_tile[tile]
                for tile, actual in zip(visible_tiles, visible_attributes)
            )

            if presented and current_map == ROUTE_1:
                route_presentation_seen = True
            destination_visible = bool(
                presented
                and current_map == VIRIDIAN_CITY
                and route_boundary_visible is not None
                and (visible_tiles, visible_attributes) != route_boundary_visible
            )
            palette_is_viridian = palette == viridian_palettes
            frames.append(
                {
                    "frame": emulator.frame,
                    "map": current_map,
                    "y": emulator.read("wYCoord"),
                    "x": emulator.read("wXCoord"),
                    "lcdc": lcdc,
                    "scroll": [
                        emulator.pyboy.memory[RSCX],
                        emulator.pyboy.memory[RSCY],
                    ],
                    "active": emulator.read("wPassiveFullColorActive"),
                    "palette_pending": emulator.read(
                        "wPassiveFullColorPalettePending"
                    ),
                    "presented": presented,
                    "destination_visible": destination_visible,
                    "palette_is_route1": palette == route_palettes,
                    "palette_is_viridian": palette_is_viridian,
                    "visible_attribute_mismatches": attribute_mismatches,
                    "visible_tile_attribute_sha256": hashlib.sha256(
                        visible_tiles + visible_attributes
                    ).hexdigest(),
                }
            )

            if not destination_visible:
                continue
            if first_destination_frame is None:
                first_destination_frame = emulator.frame
                emulator.save_screenshot("first-presented-viridian-frame.png")
            assert attribute_mismatches == 0, (
                emulator.frame,
                "Viridian tiles were presented without their linked attributes",
                attribute_mismatches,
            )
            assert palette_is_viridian, (
                emulator.frame,
                "Viridian tiles/attributes preceded the Viridian roof palette",
                frames[-1],
            )
            if (
                emulator.read("wPassiveFullColorActive") == 1
                and emulator.read("wPassiveFullColorPalettePending") == 0
            ):
                transition_established = True
                break

        assert route_presentation_seen
        assert first_destination_frame is not None, (
            "Viridian destination VRAM was never presented during the bounded crossing"
        )
        assert transition_established, (
            "Viridian palette authority did not settle during the bounded crossing"
        )
        emulator.save_screenshot("viridian-connection-established.png")
    except BaseException:
        emulator.save_screenshot("route1-viridian-connection-failure.png")
        raise
    finally:
        (results / "route1-viridian-transition-frames.json").write_text(
            json.dumps(
                {
                    "first_destination_frame": first_destination_frame,
                    "transition_established": transition_established,
                    "frames": frames,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        emulator.close()
