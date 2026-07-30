"""Reusable helpers for driving the ROM through PyBoy."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from io import BytesIO
import os
from pathlib import Path

from PIL import Image, ImageChops
from pyboy import PyBoy


def screen_difference(
    actual: Image.Image,
    reference: Image.Image,
    ignored_regions: tuple[tuple[int, int, int, int], ...] = (),
) -> Image.Image:
    """Return a full-frame diff after masking explicitly unstable regions."""
    compared_actual = actual.copy()
    compared_reference = reference.copy()
    for region in ignored_regions:
        compared_actual.paste((0, 0, 0), region)
        compared_reference.paste((0, 0, 0), region)
    return ImageChops.difference(compared_actual, compared_reference)


class Emulator:
    """A deterministic, headless Game Boy test driver."""

    def __init__(self, rom: Path, symbols: Path, results: Path) -> None:
        self.results = results
        self.results.mkdir(parents=True, exist_ok=True)
        self.symbols = self._load_symbols(symbols)
        self.pyboy = PyBoy(
            str(rom),
            window="null",
            sound_emulated=False,
            ram_file=BytesIO(bytes(0x8000)),
        )
        self.pyboy.set_emulation_speed(0)

    @staticmethod
    def _load_symbols(path: Path) -> dict[str, int]:
        return Emulator._parse_symbols(path.read_text(encoding="utf-8").splitlines())

    @staticmethod
    def _parse_symbols(lines: Iterable[str]) -> dict[str, int]:
        symbols: dict[str, int] = {}
        for line in lines:
            if not line or line.startswith(";"):
                continue
            location, name = line.split(maxsplit=1)
            if ":" not in location:
                continue
            _, address = location.split(":", maxsplit=1)
            symbols[name] = int(address, 16)
        return symbols

    def close(self) -> None:
        self.pyboy.stop()

    def read(self, symbol: str) -> int:
        return self.pyboy.memory[self.symbols[symbol]]

    def write(self, symbol: str, value: int) -> None:
        if not 0 <= value <= 0xFF:
            raise ValueError(f"Byte value out of range: {value}")
        self.pyboy.memory[self.symbols[symbol]] = value

    def bag_contains(self, item: int) -> bool:
        bag_items = self.symbols["wBagItems"]
        return any(
            self.pyboy.memory[bag_items + index * 2] == item
            for index in range(self.read("wNumBagItems"))
        )

    def tick(self, frames: int = 1) -> None:
        for frame in range(frames):
            if not self.pyboy.tick():
                raise RuntimeError(f"Emulator stopped with {frames - frame} frames left")

    def press(self, button: str, wait_frames: int = 120) -> None:
        self.pyboy.button(button, delay=2)
        self.tick(3 + wait_frames)

    def advance_until(
        self,
        predicate: Callable[[], bool],
        *,
        button: str = "a",
        max_presses: int,
        description: str,
    ) -> None:
        for _ in range(max_presses):
            if predicate():
                return
            self.press(button)
        if not predicate():
            self.save_screenshot(f"timeout-{description}.png")
            raise AssertionError(f"Timed out waiting for {description}")

    def is_preset_name_menu(self) -> bool:
        return (
            self.read("wTopMenuItemY") == 2
            and self.read("wTopMenuItemX") == 1
            and self.read("wMaxMenuItem") == 4
            and self.read("wMenuWatchedKeys") == 1
        )

    def is_in_bedroom_overworld(self) -> bool:
        game_timer_counting = self.read("wStatusFlags6") & 1
        return self.read("wCurMap") == 0x26 and bool(game_timer_counting)

    def is_in_battle(self) -> bool:
        return self.read("wIsInBattle") != 0

    def save_screenshot(self, filename: str) -> Path:
        path = self.results / filename
        self.pyboy.screen.image.save(path)
        return path

    def assert_screen_matches(
        self,
        expected: Path,
        name: str,
        *,
        crop: tuple[int, int, int, int] | None = None,
        ignored_regions: tuple[tuple[int, int, int, int], ...] = (),
    ) -> None:
        actual = self.pyboy.screen.image.convert("RGB")
        if os.environ.get("UPDATE_ROM_SNAPSHOTS") == "1":
            expected.parent.mkdir(parents=True, exist_ok=True)
            actual.save(expected)
            return

        reference = Image.open(expected).convert("RGB")
        compared_actual = actual.crop(crop) if crop else actual
        compared_reference = reference.crop(crop) if crop else reference
        difference = screen_difference(
            compared_actual,
            compared_reference,
            ignored_regions,
        )
        if difference.getbbox() is None:
            return

        actual.save(self.results / f"{name}-actual.png")
        difference.save(self.results / f"{name}-diff.png")
        raise AssertionError(f"Screen does not match {expected}")
