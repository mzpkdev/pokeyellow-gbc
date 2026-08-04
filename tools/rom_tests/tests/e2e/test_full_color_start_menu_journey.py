"""Natural proof that Color-mode Start and Options publish paired window data."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import walk_from_bedroom_to_pallet
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


VBG_MAP_1 = 0x9C00
RWY = 0xFF4A


def _linked_attributes() -> bytes:
    symbol_lines = (REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym").read_text(
        encoding="utf-8"
    ).splitlines()
    addresses = Emulator._parse_symbols(symbol_lines)
    banks = Emulator._parse_symbol_banks(symbol_lines)
    address = addresses["FullColorOverworldTileAttributes"]
    offset = banks["FullColorOverworldTileAttributes"] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc").read_bytes()[
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


def _press_until_first_reveal(
    emulator: Emulator,
    button: str,
    attributes: bytes,
    label: str,
    *,
    require_hidden_frame: bool,
    ready: Callable[[], bool],
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
    results = result_directory(
        "test_full_color_start_menu_journey.py::natural-color-start-options"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"),
        symbols=Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"),
        results=results,
        cgb=True,
    )
    attributes = _linked_attributes()
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
                and emulator.read("hAutoBGTransferEnabled") & 0x80
            ),
        )
        assert emulator.read_palette_ram() == palettes

        for _ in range(4):
            emulator.press("down", wait_frames=12)
        assert emulator.read("wCurrentMenuItem") == 4
        _press_until_first_reveal(
            emulator,
            "a",
            attributes,
            "first-visible-options",
            require_hidden_frame=True,
            ready=lambda: emulator.read("wOptionsCursorLocation") == 0,
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

        emulator.press("b", wait_frames=60)
        assert emulator.read("wJoyIgnore") == 0
        assert emulator.read("wWalkCounter") == 0
    except BaseException:
        emulator.save_screenshot("natural-color-start-options-failure.png")
        raise
    finally:
        emulator.close()
