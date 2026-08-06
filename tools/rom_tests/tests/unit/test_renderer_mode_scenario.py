"""Focused contract tests for natural renderer-mode navigation."""

from __future__ import annotations

from typing import cast

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.renderer_mode import select_renderer_mode


class _MenuEmulator:
    def __init__(self) -> None:
        self.preference = 0
        self.start_cursor = 0
        self.options_cursor = 0
        self.screen = "overworld"
        self.buttons: list[str] = []
        self.ticks = 0
        self.joy_last = 0
        self.pending_down_until: int | None = None
        self.next_down_poll: int | None = None
        self.tilemap_version = 0
        self.wy = 0
        self.pyboy = _Controller(self)

    def _apply_button(self, button: str) -> None:
        self.buttons.append(button)
        if self.screen == "overworld" and button == "start":
            self.screen = "start"
        elif self.screen == "start" and button == "down":
            self.start_cursor += 1
        elif self.screen == "start" and button == "a":
            self.screen = "options"
        elif self.screen == "options" and button == "down":
            self.options_cursor += 1
        elif self.screen == "options" and button == "right":
            self.preference ^= 1
        elif self.screen == "options" and button == "b":
            self.screen = "start"
            self.tilemap_version += 1
        elif self.screen == "start" and button == "b":
            self.screen = "overworld"
            self.wy = 144

    def read(self, symbol: str) -> int:
        return {
            "wUnusedObtainedBadges": self.preference,
            "wCurrentMenuItem": self.start_cursor,
            "wOptionsCursorLocation": self.options_cursor,
            "hJoyLast": self.joy_last,
            "hWY": self.wy,
            "wJoyIgnore": 0,
        }[symbol]

    def read_bytes(self, symbol: str, size: int) -> bytes:
        assert symbol == "wTileMap"
        return bytes((self.tilemap_version,)) * size

    def press(self, button: str, wait_frames: int = 120) -> None:
        del wait_frames
        self._apply_button(button)

    def tick(self, frames: int = 1) -> None:
        for _ in range(frames):
            self.ticks += 1
            if self.next_down_poll != self.ticks:
                continue
            pressed = (
                self.pending_down_until is not None
                and self.ticks < self.pending_down_until
            )
            if pressed:
                if self.joy_last == 0:
                    self._apply_button("down")
                self.joy_last = 1 << 7
            else:
                self.joy_last = 0
                self.pending_down_until = None
            self.next_down_poll += 15


class _Controller:
    def __init__(self, emulator: _MenuEmulator) -> None:
        self.emulator = emulator

    def button(self, button: str, delay: int) -> None:
        assert delay == 10
        if button in {"right", "b"}:
            self.emulator._apply_button(button)
            return
        assert button == "down"
        self.emulator.pending_down_until = self.emulator.ticks + delay + 1
        self.emulator.next_down_poll = self.emulator.ticks + 1


def test_select_yellow_mode_uses_only_controller_navigation() -> None:
    emulator = _MenuEmulator()

    select_renderer_mode(cast(Emulator, emulator), yellow_mode=True)

    assert emulator.preference == 1
    assert emulator.screen == "overworld"
    assert emulator.buttons == [
        "start",
        *("down",) * 4,
        "a",
        *("down",) * 5,
        "right",
        "b",
        "b",
    ]


def test_select_color_mode_visits_the_same_menu_without_changing_preference() -> None:
    emulator = _MenuEmulator()

    select_renderer_mode(cast(Emulator, emulator), yellow_mode=False)

    assert emulator.preference == 0
    assert emulator.screen == "overworld"
    assert "right" not in emulator.buttons
    assert emulator.ticks == 9 * 16 + 33 + 2


def test_each_down_press_waits_until_the_menu_samples_its_release() -> None:
    emulator = _MenuEmulator()

    select_renderer_mode(cast(Emulator, emulator), yellow_mode=True)

    assert emulator.start_cursor == 4
    assert emulator.options_cursor == 5
    assert emulator.buttons.count("down") == 9
    assert emulator.joy_last == 0
