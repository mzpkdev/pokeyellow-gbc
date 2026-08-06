"""Natural proof that Color-mode UI windows publish paired tile and attribute data."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import (
    complete_oaks_lab_intro,
    walk_from_bedroom_to_pallet,
)
from tools.rom_tests.scenarios.renderer_mode import move_cursor_to, select_renderer_mode
from tools.rom_tests.scenarios.viridian_city import ROUTE_1, walk_to_value
from tools.rom_tests.test_support import apply_debug_repel
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


VBG_MAP_1 = 0x9C00
RWY = 0xFF4A
RLCDC = 0xFF40
VBG_MAP_0 = 0x9800
HARDWARE_OAM = 0xFE00
OAM_BYTES = 0xA0
PLAYER_OAM_BYTES = 4 * 4
OAM_ENTRY_BYTES = 4
SCREEN_WIDTH_PX = 160
SCREEN_HEIGHT_PX = 144
OAM_X_OFFSET = 8
OAM_Y_OFFSET = 16
BLANK_TILE = 0x7F
MENU_CURSOR_TILE = 0xED
OPTIONS_CURSOR_COLUMN = 1
OPTIONS_CURSOR_FIRST_ROW = 2
OPTIONS_CURSOR_ROW_STRIDE = 2
CURSOR_RESPONSE_TIMEOUT_FRAMES = 90
# Cursor-only redraws use Yellow's stock three-frame sweep. Permit one frame
# for the deterministic input-poll boundary without accepting a slower redraw.
CURSOR_EXPECTED_SWEEP_FRAMES = 3
CURSOR_RESPONSE_TOLERANCE_FRAMES = 1
CURSOR_RESPONSE_CEILING_FRAMES = (
    CURSOR_EXPECTED_SWEEP_FRAMES + CURSOR_RESPONSE_TOLERANCE_FRAMES
)
COLOR_CURSOR_MAX_ADDED_FRAMES = 1
OVERLAY_COMPLETE = 1 << 5


def _linked_attributes(product: str) -> bytes:
    symbol_lines = (REPOSITORY_ROOT / f"{product}.sym").read_text(
        encoding="utf-8"
    ).splitlines()
    addresses = Emulator._parse_symbols(symbol_lines)
    banks = Emulator._parse_symbol_banks(symbol_lines)
    address = addresses["FullColorOverworldTileAttributes"]
    offset = banks["FullColorOverworldTileAttributes"] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[
        offset : offset + 256
    ]


def _window_plane(emulator: Emulator, bank: int) -> bytes:
    return b"".join(
        emulator.read_vram_bank(bank, VBG_MAP_1 + row * 32, 20)
        for row in range(18)
    )


def _assert_paired_window(emulator: Emulator, attributes: bytes, label: str) -> None:
    tiles = _window_plane(emulator, 0)
    actual = _window_plane(emulator, 1)
    expected = bytes(attributes[tile] for tile in tiles)
    emulator.save_screenshot(f"{label}.png")
    assert actual == expected, (label, next(
        index for index, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]
    ))


def _visible_map_plane(emulator: Emulator, bank: int) -> bytes:
    pointer = int.from_bytes(emulator.read_bytes("wMapViewVRAMPointer", 2), "little")
    offset = pointer - VBG_MAP_0
    x, y = offset & 31, (offset >> 5) & 31
    return bytes(
        emulator.read_vram_bank(
            bank, VBG_MAP_0 + ((y + row) & 31) * 32 + ((x + column) & 31), 1
        )[0]
        for row in range(18)
        for column in range(20)
    )


def _assert_paired_visible_map(emulator: Emulator, attributes: bytes) -> None:
    tiles = _visible_map_plane(emulator, 0)
    actual = _visible_map_plane(emulator, 1)
    assert actual == bytes(attributes[tile] for tile in tiles)


def _assert_not_blank(emulator: Emulator, label: str, frame: int) -> None:
    image = emulator.capture_screen().convert("RGB")
    assert emulator.pyboy.memory[RLCDC] & 0x80, (label, frame, "LCD disabled")
    assert any(channel[0] < 248 for channel in image.getextrema()), (
        label,
        frame,
        "near-white frame",
    )


def _visible_player_oam_entries(emulator: Emulator, oam: bytes) -> tuple[int, ...]:
    sprite_height = 16 if emulator.pyboy.memory[RLCDC] & (1 << 2) else 8
    return tuple(
        offset // OAM_ENTRY_BYTES
        for offset in range(0, PLAYER_OAM_BYTES, OAM_ENTRY_BYTES)
        if (
            oam[offset] < SCREEN_HEIGHT_PX + OAM_Y_OFFSET
            and oam[offset] + sprite_height > OAM_Y_OFFSET
            and oam[offset + 1] < SCREEN_WIDTH_PX + OAM_X_OFFSET
            and oam[offset + 1] > 0
        )
    )


def _assert_no_visible_player_sprite(emulator: Emulator) -> None:
    # Yellow's first four OAM entries are the player composite. The full-screen
    # Options menu must hide it in both the presented hardware image and the
    # next-frame shadow authority.
    for label, oam in (
        ("hardware", emulator.read_memory(HARDWARE_OAM, OAM_BYTES)),
        ("shadow", emulator.read_bytes("wShadowOAM", OAM_BYTES)),
    ):
        visible_entries = _visible_player_oam_entries(emulator, oam)
        assert not visible_entries, (
            "first visible Options frame exposes player sprite",
            label,
            visible_entries,
            tuple(
                oam[index * OAM_ENTRY_BYTES : (index + 1) * OAM_ENTRY_BYTES]
                for index in visible_entries
            ),
        )


def _press_until_first_reveal(
    emulator: Emulator,
    button: str,
    attributes: bytes,
    label: str,
    *,
    require_hidden_frame: bool,
    ready: Callable[[], bool],
    assert_first_reveal: Callable[[], None] | None = None,
    button_delay: int = 2,
) -> None:
    hidden_seen = not require_hidden_frame
    emulator.pyboy.button(button, delay=button_delay)
    for frame in range(600):
        if frame and frame % 120 == 0 and not hidden_seen:
            emulator.pyboy.button(button, delay=button_delay)
        emulator.tick()
        if emulator.pyboy.memory[RWY] >= 0x90:
            hidden_seen = True
            continue
        if hidden_seen and emulator.pyboy.memory[RWY] == 0 and ready():
            _assert_paired_window(emulator, attributes, label)
            if assert_first_reveal is not None:
                assert_first_reveal()
            emulator.tick()
            emulator.save_screenshot(f"{label}-rendered.png")
            emulator.tick(5)
            return
    emulator.save_screenshot(f"{label}-timeout.png")
    registers = emulator.pyboy.register_file
    raise AssertionError(
        f"timed out waiting for paired {label} reveal: "
        f"PC={registers.PC:#06x} SP={registers.SP:#06x} "
        f"bank={emulator.read('hLoadedROMBank'):#04x} "
        f"WY={emulator.pyboy.memory[RWY]:#04x} "
        f"joy5={emulator.read('hJoy5'):#04x} "
        f"auto={emulator.read('hAutoBGTransferEnabled'):#04x} "
        f"option={emulator.read('wOptionsCursorLocation'):#04x}"
    )


def test_natural_color_start_options_window_is_paired_before_reveal() -> None:
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-color-start-options"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )
    attributes = _linked_attributes(product)
    try:
        reach_bedroom_overworld(emulator)
        walk_from_bedroom_to_pallet(emulator)
        assert emulator.read("wCurMap") == 0
        assert emulator.read("wUnusedObtainedBadges") & 1 == 0
        palettes = emulator.read_palette_ram()

        _press_until_first_reveal(
            emulator,
            "start",
            attributes,
            "first-visible-start",
            require_hidden_frame=False,
            ready=lambda: (
                emulator.read("wMaxMenuItem") == 6
                and emulator.read("wMenuWatchedKeys") == 0xCB
                and emulator.read("hWY") == 0
                and emulator.read("hAutoBGTransferEnabled") & OVERLAY_COMPLETE
            ),
        )
        assert emulator.read_palette_ram() == palettes

        move_cursor_to(
            emulator,
            "wCurrentMenuItem",
            4,
            description="the Color Start-menu Options item",
        )
        _press_until_first_reveal(
            emulator,
            "a",
            attributes,
            "first-visible-options",
            require_hidden_frame=True,
            ready=lambda: emulator.read("wOptionsCursorLocation") == 0,
            assert_first_reveal=lambda: _assert_no_visible_player_sprite(emulator),
        )
        assert emulator.read_palette_ram() == palettes
        options_tiles = emulator.read_bytes("wTileMap", 360)
        emulator.tick(60)

        _press_until_first_reveal(
            emulator,
            "b",
            attributes,
            "first-visible-returned-start",
            require_hidden_frame=True,
            ready=lambda: (
                emulator.read("wMaxMenuItem") == 6
                and emulator.read_bytes("wTileMap", 360) != options_tiles
            ),
            button_delay=30,
        )
        assert emulator.read_palette_ram() == palettes

        emulator.pyboy.button("b", delay=2)
        for frame in range(80):
            emulator.tick()
            _assert_not_blank(emulator, "closing Start", frame)
        assert emulator.read("wJoyIgnore") == 0
        assert emulator.read("wWalkCounter") == 0
    except BaseException:
        emulator.save_screenshot("natural-color-start-options-failure.png")
        raise
    finally:
        emulator.close()


def _options_cursor_tile(emulator: Emulator, index: int) -> int:
    row = OPTIONS_CURSOR_FIRST_ROW + index * OPTIONS_CURSOR_ROW_STRIDE
    return _window_plane(emulator, 0)[row * 20 + OPTIONS_CURSOR_COLUMN]


def _options_cursor_is_visibly_at(emulator: Emulator, index: int) -> bool:
    return (
        _options_cursor_tile(emulator, index) == MENU_CURSOR_TILE
        and all(
            _options_cursor_tile(emulator, other) == BLANK_TILE
            for other in range(2)
            if other != index
        )
    )


def _wait_for_neutral_input(emulator: Emulator, label: str) -> None:
    for _ in range(CURSOR_RESPONSE_TIMEOUT_FRAMES):
        if emulator.read("hJoyLast") == 0:
            return
        emulator.tick()
    raise AssertionError(
        f"timed out waiting for neutral input before {label}: "
        f"hJoyLast={emulator.read('hJoyLast'):#04x}"
    )


def _open_options_after_reveal(
    emulator: Emulator,
    label: str,
    *,
    require_hidden_frame: bool,
) -> None:
    emulator.pyboy.button("start", delay=10)
    for _ in range(240):
        emulator.tick()
        if (
            emulator.pyboy.memory[RWY] == 0
            and emulator.read("wMaxMenuItem") == 6
            and emulator.read("wMenuWatchedKeys") == 0xCB
        ):
            break
    else:
        raise AssertionError(f"timed out opening {label} Start menu")
    _wait_for_neutral_input(emulator, f"{label} Options selection")

    move_cursor_to(
        emulator,
        "wCurrentMenuItem",
        4,
        description=f"{label} Start-menu Options item",
    )
    hidden_seen = not require_hidden_frame
    emulator.pyboy.button("a", delay=10)
    for _ in range(240):
        emulator.tick()
        if emulator.pyboy.memory[RWY] >= SCREEN_HEIGHT_PX:
            hidden_seen = True
            continue
        if (
            hidden_seen
            and emulator.pyboy.memory[RWY] == 0
            and emulator.read("wOptionsCursorLocation") == 0
            and _options_cursor_is_visibly_at(emulator, 0)
        ):
            # The menu is already visible and its input loop has resumed. Keep
            # cold opening and Color's structural barrier out of the timing.
            emulator.tick(6)
            _wait_for_neutral_input(emulator, f"{label} cursor measurement")
            assert _options_cursor_is_visibly_at(emulator, 0), label
            emulator.save_screenshot(f"{label}-options-before-cursor-input.png")
            return
    tilemap = emulator.read_bytes("wTileMap", 360)
    tilemap_cursors = tuple(
        tilemap[
            (OPTIONS_CURSOR_FIRST_ROW + index * OPTIONS_CURSOR_ROW_STRIDE) * 20
            + OPTIONS_CURSOR_COLUMN
        ]
        for index in range(2)
    )
    raise AssertionError(
        f"timed out waiting for revealed {label} Options menu: "
        f"WY={emulator.pyboy.memory[RWY]:#04x} "
        f"option={emulator.read('wOptionsCursorLocation')} "
        f"window-cursors={tuple(_options_cursor_tile(emulator, index) for index in range(2))} "
        f"tilemap-cursors={tilemap_cursors}"
    )


def _measure_visible_options_cursor_response(emulator: Emulator, label: str) -> int:
    assert emulator.read("wOptionsCursorLocation") == 0, label
    assert _options_cursor_is_visibly_at(emulator, 0), label
    emulator.pyboy.button("down", delay=10)
    for elapsed_frames in range(1, CURSOR_RESPONSE_TIMEOUT_FRAMES + 1):
        emulator.tick()
        if (
            emulator.read("wOptionsCursorLocation") == 1
            and _options_cursor_is_visibly_at(emulator, 1)
        ):
            emulator.save_screenshot(f"{label}-first-visible-moved-cursor.png")
            return elapsed_frames
    raise AssertionError(
        f"{label} cursor did not visibly move within "
        f"{CURSOR_RESPONSE_TIMEOUT_FRAMES} frames: "
        f"logical={emulator.read('wOptionsCursorLocation')} "
        f"old={_options_cursor_tile(emulator, 0):#04x} "
        f"new={_options_cursor_tile(emulator, 1):#04x}"
    )


def _natural_options_cursor_response(
    *,
    yellow_mode: bool,
    results: Path,
) -> int:
    label = "yellow" if yellow_mode else "color"
    product = "pokeyellow"
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results / label,
        cgb=True,
    )
    try:
        reach_bedroom_overworld(emulator)
        select_renderer_mode(emulator, yellow_mode=yellow_mode)
        walk_from_bedroom_to_pallet(emulator)
        assert bool(emulator.read("wUnusedObtainedBadges") & 1) is yellow_mode
        _open_options_after_reveal(
            emulator,
            label,
            require_hidden_frame=not yellow_mode,
        )
        return _measure_visible_options_cursor_response(emulator, label)
    except BaseException:
        emulator.save_screenshot(f"{label}-cursor-response-failure.png")
        raise
    finally:
        emulator.close()


def test_natural_options_cursor_response_is_bounded_and_tracks_yellow() -> None:
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-options-cursor-response"
    )
    yellow_frames = _natural_options_cursor_response(
        yellow_mode=True,
        results=results,
    )
    color_frames = _natural_options_cursor_response(
        yellow_mode=False,
        results=results,
    )
    added_frames = color_frames - yellow_frames
    diagnostics = {
        "yellow_frames": yellow_frames,
        "color_frames": color_frames,
        "color_added_frames": added_frames,
        "expected_sweep_frames": CURSOR_EXPECTED_SWEEP_FRAMES,
        "response_tolerance_frames": CURSOR_RESPONSE_TOLERANCE_FRAMES,
        "maximum_response_frames": CURSOR_RESPONSE_CEILING_FRAMES,
        "maximum_color_added_frames": COLOR_CURSOR_MAX_ADDED_FRAMES,
    }
    (results / "cursor-response.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert yellow_frames <= CURSOR_RESPONSE_CEILING_FRAMES, diagnostics
    assert color_frames <= CURSOR_RESPONSE_CEILING_FRAMES, diagnostics
    assert added_frames <= COLOR_CURSOR_MAX_ADDED_FRAMES, diagnostics


def test_natural_renderer_toggle_reconciles_only_on_outer_start_close() -> None:
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-renderer-toggle-transaction"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )
    attributes = _linked_attributes(product)
    try:
        reach_bedroom_overworld(emulator)
        walk_from_bedroom_to_pallet(emulator)
        donor_palettes = emulator.read_palette_ram()

        _press_until_first_reveal(
            emulator,
            "start",
            attributes,
            "toggle-open-color-start",
            require_hidden_frame=False,
            ready=lambda: emulator.read("wMaxMenuItem") == 6,
        )
        move_cursor_to(
            emulator,
            "wCurrentMenuItem",
            4,
            description="Color Start to Options",
        )
        _press_until_first_reveal(
            emulator,
            "a",
            attributes,
            "toggle-open-color-options",
            require_hidden_frame=True,
            ready=lambda: emulator.read("wOptionsCursorLocation") == 0,
        )
        emulator.tick(30)
        move_cursor_to(
            emulator,
            "wOptionsCursorLocation",
            5,
            description="Color Options to mode",
        )

        emulator.pyboy.button("right", delay=10)
        changed = False
        for frame in range(CURSOR_RESPONSE_TIMEOUT_FRAMES):
            emulator.tick()
            _assert_not_blank(emulator, "Color to Yellow inside Options", frame)
            assert emulator.read_palette_ram() == donor_palettes
            assert emulator.read("wPassiveFullColorActive") == 1
            if emulator.pyboy.memory[RWY] == 0:
                tiles = _window_plane(emulator, 0)
                assert _window_plane(emulator, 1) == bytes(attributes[tile] for tile in tiles)
            if emulator.read("wUnusedObtainedBadges") & 1 and not changed:
                emulator.save_screenshot(
                    "right-after-changing-to-yellow-mode-in-settings.png"
                )
                changed = True
        assert changed

        _press_until_first_reveal(
            emulator,
            "b",
            attributes,
            "toggle-return-color-start",
            require_hidden_frame=True,
            ready=lambda: emulator.read("wMaxMenuItem") == 6,
            button_delay=30,
        )
        emulator.tick(35)
        emulator.pyboy.button("b", delay=10)
        for frame in range(100):
            emulator.tick()
            _assert_not_blank(emulator, "outer close to Yellow", frame)
            if emulator.read_palette_ram() != donor_palettes:
                assert not any(_visible_map_plane(emulator, 1)), (
                    "Yellow palettes exposed through donor attributes",
                    frame,
                )
        assert emulator.read("wPassiveFullColorActive") == 0
        assert emulator.read("wUnusedObtainedBadges") & 1

        emulator.pyboy.button("start", delay=10)
        emulator.tick(40)
        move_cursor_to(
            emulator,
            "wCurrentMenuItem",
            4,
            description="Yellow Start to Options",
        )
        emulator.pyboy.button("a", delay=10)
        emulator.tick(40)
        move_cursor_to(
            emulator,
            "wOptionsCursorLocation",
            5,
            description="Yellow Options to mode",
        )
        emulator.pyboy.button("right", delay=10)
        emulator.tick(24)
        assert emulator.read("wUnusedObtainedBadges") & 1 == 0
        assert emulator.read("wPassiveFullColorActive") == 0
        emulator.pyboy.button("b", delay=10)
        emulator.tick(40)

        emulator.pyboy.button("b", delay=10)
        activated = False
        for frame in range(180):
            emulator.tick()
            _assert_not_blank(emulator, "bounded outer close to Color", frame)
            if emulator.read("wPassiveFullColorActive") == 1:
                activated = True
            if activated and emulator.read("wJoyIgnore") == 0:
                break
        assert activated
        _assert_paired_visible_map(emulator, attributes)

        start_x = emulator.read("wXCoord")
        walk_to_value(
            emulator, "wXCoord", start_x + 5, "right", "five east steps after Color activation"
        )
        _assert_paired_visible_map(emulator, attributes)
        emulator.save_screenshot(
            "right-after-changing-to-color-more-in-settings-and-moving-5-squares-to-the-right.png"
        )
    except BaseException:
        emulator.save_screenshot("natural-renderer-toggle-transaction-failure.png")
        raise
    finally:
        emulator.close()


def test_natural_pallet_route_1_connection_never_blanks_color_plane() -> None:
    # This journey uses the test-only Repel control to isolate the connection.
    product = "pokeyellow_debug"
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-pallet-route-1-connection"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )
    attributes = _linked_attributes(product)
    try:
        complete_oaks_lab_intro(emulator)
        apply_debug_repel(emulator)
        walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
        walk_to_value(emulator, "wYCoord", 2, "up", "north Pallet Town")
        walk_to_value(emulator, "wXCoord", 10, "right", "Route 1 entrance")
        palettes = emulator.read_palette_ram()

        for frame in range(240):
            if frame % 30 == 0 and emulator.read("wCurMap") != ROUTE_1:
                emulator.pyboy.button("up", delay=2)
            emulator.tick()
            _assert_not_blank(emulator, "Pallet to Route 1", frame)
            if emulator.read("wCurMap") == ROUTE_1:
                tiles = emulator.read_vram_bank(0, VBG_MAP_0, 0x400)
                actual = emulator.read_vram_bank(1, VBG_MAP_0, 0x400)
                assert actual == bytes(attributes[tile] for tile in tiles)
                assert emulator.read_palette_ram() == palettes
                emulator.save_screenshot("first-visible-route-1.png")
                return
        raise AssertionError("timed out crossing from Pallet Town to Route 1")
    except BaseException:
        emulator.save_screenshot("natural-pallet-route-1-failure.png")
        raise
    finally:
        emulator.close()


def test_natural_oak_dialogue_window_is_paired_before_reveal() -> None:
    product = "pokeyellow"
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-oak-dialogue"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / f"{product}.gbc"),
        symbols=Path(REPOSITORY_ROOT / f"{product}.sym"),
        results=results,
        cgb=True,
    )
    attributes = _linked_attributes(product)
    try:
        reach_bedroom_overworld(emulator)
        walk_from_bedroom_to_pallet(emulator)
        emulator.advance_until(
            lambda: emulator.read("wXCoord") == 10,
            button="right",
            max_presses=140,
            description="Oak interception column",
        )
        emulator.advance_until(
            lambda: emulator.read("wYCoord") == 1,
            button="up",
            max_presses=140,
            description="row below Oak interception",
        )
        palettes = emulator.read_palette_ram()

        emulator.pyboy.button("up", delay=2)
        for frame in range(1200):
            if frame and frame % 120 == 0 and emulator.read("wYCoord") != 0:
                emulator.pyboy.button("up", delay=2)
            emulator.tick()
            if (
                emulator.read("wYCoord") == 0
                and emulator.read("hWY") == 0
                and emulator.read("hAutoBGTransferEnabled") & OVERLAY_COMPLETE
            ):
                _assert_paired_window(
                    emulator, attributes, "first-visible-oak-dialogue"
                )
                emulator.tick()
                emulator.save_screenshot("first-visible-oak-dialogue-rendered.png")
                emulator.tick(60)
                _assert_paired_window(emulator, attributes, "oak-dialogue-text")
                assert emulator.read_palette_ram() == palettes
                return
        emulator.save_screenshot("natural-oak-dialogue-timeout.png")
        raise AssertionError("timed out waiting for Oak's paired dialogue window")
    except BaseException:
        emulator.save_screenshot("natural-oak-dialogue-failure.png")
        raise
    finally:
        emulator.close()
