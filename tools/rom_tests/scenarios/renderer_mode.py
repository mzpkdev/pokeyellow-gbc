"""Natural controller-input helpers for the saved renderer preference."""

from collections.abc import Callable

from tools.rom_tests.emulator import Emulator


YELLOW_MODE_MASK = 1
PAD_DOWN = 1 << 7
PAD_RIGHT = 1 << 4
PAD_B = 1 << 1
START_MENU_OPTIONS_INDEX = 4
OPTIONS_COLOR_MODE_INDEX = 5
INPUT_RESPONSE_FRAMES = 90


def _press_until(
    emulator: Emulator,
    button: str,
    predicate: Callable[[], bool],
    *,
    description: str,
) -> None:
    for _ in range(3):
        emulator.pyboy.button(button, delay=10)
        for _ in range(INPUT_RESPONSE_FRAMES * 2):
            emulator.tick()
            if predicate():
                for _ in range(INPUT_RESPONSE_FRAMES):
                    if emulator.read("hJoyLast") & PAD_B == 0:
                        return
                    emulator.tick()
                raise AssertionError(
                    f"Timed out waiting for {button} release after {description}"
                )
    raise AssertionError(f"Timed out waiting for {description}")


def _wait_for_down_release(
    emulator: Emulator,
    *,
    description: str,
) -> None:
    for _ in range(INPUT_RESPONSE_FRAMES):
        if emulator.read("hJoyLast") & PAD_DOWN == 0:
            return
        emulator.tick()
    raise AssertionError(
        f"Timed out waiting for Down release while moving {description}: "
        f"hJoyLast={emulator.read('hJoyLast'):#04x}"
    )


def move_cursor_to(
    emulator: Emulator,
    symbol: str,
    target: int,
    *,
    description: str,
    max_presses: int = 12,
) -> None:
    for _ in range(max_presses):
        current = emulator.read(symbol)
        if current == target:
            return
        _wait_for_down_release(emulator, description=description)
        emulator.pyboy.button("down", delay=10)
        for _ in range(INPUT_RESPONSE_FRAMES):
            emulator.tick()
            updated = emulator.read(symbol)
            if updated != current:
                break
        else:
            raise AssertionError(
                f"Timed out waiting for Down to move {description}: "
                f"{symbol}={current}"
            )
        if updated != current + 1:
            raise AssertionError(
                f"Down moved {description} by more than one row: "
                f"{symbol}={current}->{updated}"
            )
        # A short PyBoy press can be physically released before the menu's
        # low-sensitivity joypad poll observes that release. Do not queue the
        # next press until hJoyLast proves the game sampled the neutral state.
        _wait_for_down_release(emulator, description=description)
    raise AssertionError(
        f"Timed out moving {description}: "
        f"{symbol}={emulator.read(symbol)}, expected {target}"
    )


def select_renderer_mode(emulator: Emulator, *, yellow_mode: bool) -> None:
    """Open Start -> Options and naturally select the requested renderer mode."""
    emulator.press("start", wait_frames=60)
    move_cursor_to(
        emulator,
        "wCurrentMenuItem",
        START_MENU_OPTIONS_INDEX,
        description="the Start-menu Options item",
    )
    emulator.press("a", wait_frames=60)
    move_cursor_to(
        emulator,
        "wOptionsCursorLocation",
        OPTIONS_COLOR_MODE_INDEX,
        description="the Color Mode option",
    )
    is_yellow = bool(emulator.read("wUnusedObtainedBadges") & YELLOW_MODE_MASK)
    if is_yellow != yellow_mode:
        emulator.pyboy.button("right", delay=10)
        for _ in range(INPUT_RESPONSE_FRAMES):
            emulator.tick()
            if bool(
                emulator.read("wUnusedObtainedBadges") & YELLOW_MODE_MASK
            ) == yellow_mode:
                break
        else:
            raise AssertionError("Color Mode did not change through Options")
        for _ in range(INPUT_RESPONSE_FRAMES):
            if emulator.read("hJoyLast") & PAD_RIGHT == 0:
                break
            emulator.tick()
        else:
            raise AssertionError("Timed out waiting for Right release in Options")
    else:
        # Match the real directional input's frame cadence for paired journeys.
        emulator.tick(33)
    selected_yellow = bool(
        emulator.read("wUnusedObtainedBadges") & YELLOW_MODE_MASK
    )
    if selected_yellow != yellow_mode:
        raise AssertionError("Color Mode did not change through Options")

    options_tiles = emulator.read_bytes("wTileMap", 20 * 18)
    _press_until(
        emulator,
        "b",
        lambda: emulator.read_bytes("wTileMap", 20 * 18) != options_tiles,
        description="Options to return to Start",
    )
    _press_until(
        emulator,
        "b",
        lambda: emulator.read("hWY") >= 144 and emulator.read("wJoyIgnore") == 0,
        description="Start to return to the overworld",
    )
