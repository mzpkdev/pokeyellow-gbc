"""Cold-boot parity coverage for the first full-color overworld slice."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
import json
import os
from pathlib import Path
from typing import cast

from PIL import Image

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import (
    OAKS_LAB,
    PALLET_TOWN,
    complete_oaks_lab_intro,
    walk_from_bedroom_to_oak,
)
from tools.rom_tests.scenarios.renderer_mode import select_renderer_mode
from tools.rom_tests.scenarios.viridian_city import (
    ROUTE_1,
    VIRIDIAN_CITY,
    reach_viridian_city,
    walk_from_oaks_lab_to_viridian,
    walk_to_value,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "test-results" / "full-color-cold-boot"


def _configured_results_root(environment: Mapping[str, str] = os.environ) -> Path:
    return Path(
        environment.get("FULL_COLOR_COLD_BOOT_RESULTS", str(DEFAULT_RESULTS_ROOT))
    ).resolve()


RESULTS_ROOT = _configured_results_root()

CHECKPOINTS = (
    "bedroom",
    "pallet-before-oak",
    "oak-interception",
    "post-lab-pallet",
    "route1-south",
    "route1-mid",
    "route1-north",
    "viridian-entry",
)
COLOR_CHECKPOINTS = frozenset(CHECKPOINTS)
REVERSE_CHECKPOINTS = (
    "viridian-southbound",
    "route1-reentry",
    "route1-north-ledge",
    "route1-central-ledge",
    "route1-south-ledge",
    "pallet-reentry",
)
REVERSE_COLOR_CHECKPOINTS = frozenset(REVERSE_CHECKPOINTS)
SCRIPT_PALLETTOWN_PIKACHU_BATTLE = 4
SCRIPT_PALLETTOWN_AFTER_PIKACHU_BATTLE = 5
BATTLE_TYPE_PIKACHU = 4
PIKACHU = 0x54
POKE_BALL = 0x04
CAPTURE_ANIMATION_IDS = frozenset({0xC1, 0xC2, 0xC3, 0xC8})


@dataclass(frozen=True)
class JourneyObservation:
    frame: int
    logical_state: tuple[int, ...]
    rng_state: tuple[int, int]
    renderer_state: tuple[int, int]
    renderer_preference: int
    renderer_generation: tuple[int, ...]
    passive_state: tuple[int, int, int, int]
    lcdc: int
    scroll: tuple[int, int]
    tile_data: bytes
    tilemap: bytes
    hardware_oam: bytes
    shadow_oam: bytes
    sprite_picture_ids: tuple[int, ...]
    bg_palettes: bytes
    attributes: bytes
    screen: Image.Image


@dataclass(frozen=True)
class BoundaryObservation:
    journey: JourneyObservation
    input_state: tuple[int, ...]
    menu_state: tuple[int, ...]
    scheduler_state: tuple[object, ...]


@dataclass(frozen=True)
class WildBattleRoundTrip:
    battle_menu: JourneyObservation
    battle_state: tuple[int, ...]
    restored_route: JourneyObservation
    encounter_steps: tuple[int, int]


@dataclass(frozen=True)
class SaveContinueRoundTrip:
    before_reset: JourneyObservation
    restored: JourneyObservation
    playable: JourneyObservation


@dataclass(frozen=True)
class PalletHouseRoundTrip:
    interior: JourneyObservation
    restored_pallet: JourneyObservation


@dataclass(frozen=True)
class OakCaptureSequence:
    oak_dialogue: JourneyObservation
    battle_presentation: JourneyObservation
    ball_animation: JourneyObservation
    post_capture: JourneyObservation
    lab_transition: JourneyObservation
    event_states: dict[str, tuple[int, ...]]


class _PresetMenuState:
    def __init__(self, max_menu_item: int) -> None:
        self.values = {
            "wTopMenuItemY": 2,
            "wTopMenuItemX": 1,
            "wMaxMenuItem": max_menu_item,
            "wMenuWatchedKeys": 1,
        }

    def read(self, symbol: str) -> int:
        return self.values[symbol]


def _prepare_results(results: Path) -> None:
    """Remove only stale files from one cold-boot scenario result directory."""
    if results.parent != RESULTS_ROOT:
        raise AssertionError(f"refusing to clean non-scenario result path: {results}")
    results.mkdir(parents=True, exist_ok=True)
    for artifact in results.iterdir():
        if artifact.is_file() or artifact.is_symlink():
            artifact.unlink()


def _mode_label(product: str, yellow_mode: bool) -> str:
    return f"{product}-{'yellow' if yellow_mode else 'color'}"


def _mode_setup(yellow_mode: bool) -> Callable[[Emulator], None]:
    return partial(select_renderer_mode, yellow_mode=yellow_mode)


def _observe(emulator: Emulator, filename: str) -> JourneyObservation:
    tilemap_base = 0x9C00 if emulator.pyboy.memory[0xFF40] & (1 << 3) else 0x9800
    screen = emulator.capture_screen()
    screen.save(emulator.results / filename)
    passive_state = (
        (
            emulator.read("wPassiveFullColorActive"),
            emulator.read("wPassiveFullColorPalettePending"),
            emulator.read("wPassiveFullColorClearChunks"),
            emulator.read("wPassiveFullColorGeneration"),
        )
        if "wPassiveFullColorActive" in emulator.symbols
        else (0, 0, 0, 0)
    )
    return JourneyObservation(
        frame=emulator.frame,
        logical_state=(
            emulator.read("wCurMap"),
            emulator.read("wYCoord"),
            emulator.read("wXCoord"),
            emulator.read("wPartyCount"),
            emulator.read("wOaksLabCurScript"),
            emulator.read("wIsInBattle"),
        ),
        rng_state=(emulator.read("hRandomAdd"), emulator.read("hRandomSub")),
        renderer_state=(
            emulator.read("wRendererOwner"),
            emulator.read("wRendererPhase"),
        ),
        renderer_preference=emulator.read("wUnusedObtainedBadges") & 1,
        renderer_generation=tuple(emulator.read_bytes("wRendererGeneration", 4)),
        passive_state=passive_state,
        lcdc=emulator.pyboy.memory[0xFF40],
        scroll=(emulator.pyboy.memory[0xFF43], emulator.pyboy.memory[0xFF42]),
        tile_data=emulator.read_vram_bank(0, 0x8000, 0x1800),
        tilemap=emulator.read_vram_bank(0, tilemap_base, 0x400),
        hardware_oam=emulator.read_memory(0xFE00, 0xA0),
        shadow_oam=emulator.read_bytes("wShadowOAM", 0xA0),
        sprite_picture_ids=tuple(
            emulator.read_bytes("wSpriteStateData1", 16 * 16)[::16]
        ),
        bg_palettes=emulator.read_palette_ram(),
        attributes=emulator.read_vram_bank(1, tilemap_base, 0x400),
        screen=screen,
    )


def _observe_boundary(
    emulator: Emulator,
    filename: str,
) -> BoundaryObservation:
    scheduler_state: tuple[object, ...] = ()
    if "wFullColorRequestCount" in emulator.symbols:
        scheduler_state = (
            emulator.read("wRendererJobState"),
            emulator.read_bytes("wFullColorRequestDescriptors", 8 * 20),
            emulator.read_bytes("wFullColorShadowOAMBatch", 160),
            emulator.read("wFullColorRequestCount"),
            emulator.read("wFullColorRequestCursor"),
            emulator.read_bytes("wFullColorAvailableResources", 2),
            emulator.read_bytes("wFullColorCommitBudget", 2),
            emulator.read("wFullColorRetryCounter"),
            emulator.read("wFullColorLastAdmissionResult"),
            emulator.read("wFullColorTransitionCount"),
            emulator.read_bytes("wFullColorTransitionLog", 8),
            emulator.read_bytes("wFullColorActiveDescriptor", 2),
        )
    return BoundaryObservation(
        journey=_observe(emulator, filename),
        input_state=(
            emulator.read("wJoyIgnore"),
            emulator.read("wWalkCounter"),
            emulator.read("wStatusFlags5"),
        ),
        menu_state=(
            emulator.read("wCurrentMenuItem"),
            emulator.read("wMaxMenuItem"),
            emulator.read("wMenuWatchedKeys"),
            emulator.read("wListMenuID"),
            emulator.read("wPartyMenuTypeOrMessageID"),
            emulator.read("hTextID"),
        ),
        scheduler_state=scheduler_state,
    )


def _run_pallet_ui_boundary(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> dict[str, BoundaryObservation]:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)
    observations: dict[str, BoundaryObservation] = {}

    def observe(name: str) -> None:
        observations[name] = _observe_boundary(
            emulator,
            f"{label}-{name}.png",
        )

    try:
        complete_oaks_lab_intro(
            emulator,
            bedroom_setup=_mode_setup(yellow_mode),
        )

        # Use the same repeated-input cadence as the natural Viridian journey.
        # The first post-warp direction can be consumed while Pikachu settles,
        # despite the authoritative input-lock fields already being clear.
        walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
        walk_to_value(emulator, "wXCoord", 7, "left", "Pallet sign column")
        walk_to_value(emulator, "wYCoord", 10, "up", "Pallet sign row")
        emulator.press("up")
        observe("stable-overworld")

        emulator.press("a")
        observe("dialogue")
        emulator.press("a")
        emulator.tick(60)
        observe("dialogue-restored")

        emulator.press("start")
        observe("start-menu")
        emulator.press("b")
        emulator.tick(60)
        observe("direct-start-restored")

        emulator.press("start")
        emulator.press("a")
        observe("party")
        emulator.press("b")
        observe("returned-start-menu")
        emulator.press("b")
        emulator.tick(60)
        observe("restored-overworld")

        # Prove that the UI round-trip returns to a naturally playable map,
        # rather than merely drawing a plausible-looking overworld frame.
        walk_to_value(emulator, "wXCoord", 8, "right", "Oak's Lab west side")
        walk_from_oaks_lab_to_viridian(emulator, use_debug_repel=True)
        observe("viridian-entry")
    except BaseException:
        emulator.save_screenshot(f"{label}-boundary-failure.png")
        raise
    finally:
        emulator.close()

    return observations


def _run_journey(
    product: str,
    results: Path,
    *,
    use_debug_repel: bool,
    yellow_mode: bool,
) -> dict[str, JourneyObservation]:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)
    observations: dict[str, JourneyObservation] = {}

    def checkpoint(name: str, current: Emulator) -> None:
        observations[name] = _observe(current, f"{label}-{name}.png")

    try:
        reach_viridian_city(
            emulator,
            checkpoint,
            use_debug_repel=use_debug_repel,
            bedroom_setup=_mode_setup(yellow_mode),
        )
    except BaseException:
        emulator.save_screenshot(f"{label}-journey-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "party_count": emulator.read("wPartyCount"),
            "oak_script": emulator.read("wOaksLabCurScript"),
            "in_battle": emulator.read("wIsInBattle"),
        }
        (results / f"{label}-journey-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    assert tuple(observations) == CHECKPOINTS
    (results / f"{label}-journey-state.json").write_text(
        json.dumps(
            {
                name: {
                    "frame": observation.frame,
                    "logical_state": observation.logical_state,
                    "passive_state": observation.passive_state,
                    "lcdc": observation.lcdc,
                    "renderer_state": observation.renderer_state,
                    "renderer_preference": observation.renderer_preference,
                    "renderer_generation": observation.renderer_generation,
                    "rng_state": observation.rng_state,
                    "scroll": observation.scroll,
                }
                for name, observation in observations.items()
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return observations


def _run_reverse_route1_journey(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> dict[str, JourneyObservation]:
    """Play naturally to Viridian, then return through Route 1's ledges."""
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)
    observations: dict[str, JourneyObservation] = {}

    def checkpoint(name: str) -> None:
        emulator.tick(60)
        observations[name] = _observe(emulator, f"{label}-{name}.png")

    try:
        reach_viridian_city(
            emulator,
            use_debug_repel=True,
            bedroom_setup=_mode_setup(yellow_mode),
        )

        # Leave Viridian through its south connection. Repel is the only
        # deterministic aid: all map travel, redraws, warps, and jumps run
        # through Yellow's normal input and VBlank paths.
        walk_to_value(emulator, "wYCoord", 29, "up", "south Viridian path")
        walk_to_value(emulator, "wXCoord", 19, "left", "Viridian main path")
        checkpoint("viridian-southbound")
        walk_to_value(emulator, "wXCoord", 20, "right", "Route 1 entrance")
        walk_to_value(emulator, "wCurMap", ROUTE_1, "down", "Route 1 re-entry")
        checkpoint("route1-reentry")

        # Southbound movement deliberately takes each one-way ledge. These
        # jumps advance multiple tiles through the stock movement engine and
        # exercise row redraws on a route the northbound journey cannot cover.
        walk_to_value(emulator, "wYCoord", 12, "down", "north Route 1 ledge")
        checkpoint("route1-north-ledge")
        walk_to_value(emulator, "wXCoord", 9, "left", "first ledge passage")
        walk_to_value(emulator, "wYCoord", 22, "down", "central Route 1 ledge")
        checkpoint("route1-central-ledge")
        walk_to_value(emulator, "wXCoord", 12, "right", "second ledge passage")
        walk_to_value(emulator, "wYCoord", 31, "down", "south Route 1 ledge")
        checkpoint("route1-south-ledge")

        walk_to_value(emulator, "wXCoord", 10, "left", "Pallet Town entrance")
        walk_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "Pallet Town")
        checkpoint("pallet-reentry")
    except BaseException:
        emulator.save_screenshot(f"{label}-reverse-journey-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "pc": emulator.pyboy.register_file.PC,
            "sp": emulator.pyboy.register_file.SP,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "in_battle": emulator.read("wIsInBattle"),
        }
        (results / f"{label}-reverse-journey-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    assert tuple(observations) == REVERSE_CHECKPOINTS
    return observations


def _run_route1_wild_battle_round_trip(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> WildBattleRoundTrip:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)
    route_steps = 0
    grass_pacing_steps = 0

    def standing_terrain_tile() -> int:
        # TryDoWildEncounter checks the lower-left tile of the half-block under
        # the player, which is the visible tilemap cell at (8, 9).
        return emulator.read_bytes("wTileMap", 20 * 18)[9 * 20 + 8]

    def press_until_value(
        symbol: str,
        value: int,
        button: str,
        description: str,
        *,
        max_presses: int = 160,
    ) -> bool:
        nonlocal route_steps
        for _ in range(max_presses):
            if emulator.is_in_battle():
                return True
            if emulator.read(symbol) == value:
                return False
            before_map = emulator.read("wCurMap")
            before_position = (
                emulator.read("wXCoord"),
                emulator.read("wYCoord"),
            )
            emulator.press(button)
            after_position = (
                emulator.read("wXCoord"),
                emulator.read("wYCoord"),
            )
            if after_position != before_position and (
                before_map == ROUTE_1 or emulator.read("wCurMap") == ROUTE_1
            ):
                route_steps += 1
        raise AssertionError(f"Timed out walking to {description}")

    try:
        complete_oaks_lab_intro(
            emulator,
            bedroom_setup=_mode_setup(yellow_mode),
        )

        # Follow the real south-to-north route without suppressing encounters.
        # Reach Route 1's first verified tall-grass corridor if an encounter
        # has not already started naturally on the way there.
        for symbol, value, button, description in (
            ("wXCoord", 8, "left", "west side of Oak's Lab"),
            ("wYCoord", 2, "up", "north Pallet Town"),
            ("wXCoord", 10, "right", "Route 1 entrance"),
            ("wCurMap", 0x0C, "up", "Route 1"),
            ("wYCoord", 32, "up", "south Route 1 grass corridor"),
        ):
            if press_until_value(symbol, value, button, description):
                break

        # (10, 32) and (10, 33) are both encounter-capable Route 1 grass. Pace
        # only between those two tiles. The generous 256-movement bound keeps
        # the deterministic product runs finite while leaving ample headroom
        # above their observed natural encounter cadence.
        if not emulator.is_in_battle():
            assert (
                emulator.read("wXCoord"),
                emulator.read("wYCoord"),
                standing_terrain_tile(),
            ) == (10, 32, emulator.read("wGrassTile"))
            for _ in range(1024):
                if grass_pacing_steps == 256:
                    break
                before_position = (
                    emulator.read("wXCoord"),
                    emulator.read("wYCoord"),
                )
                emulator.press("down" if before_position[1] == 32 else "up")
                after_position = (
                    emulator.read("wXCoord"),
                    emulator.read("wYCoord"),
                )
                if after_position == before_position:
                    continue
                route_steps += 1
                grass_pacing_steps += 1
                if emulator.is_in_battle():
                    break
                assert standing_terrain_tile() == emulator.read("wGrassTile")
        assert emulator.is_in_battle(), (
            "no natural wild encounter during bounded verified Route 1 grass pacing "
            f"(grass_pacing_steps={grass_pacing_steps}, "
            f"route_steps={route_steps}, rng="
            f"{emulator.read('hRandomAdd'):02x}/{emulator.read('hRandomSub'):02x})"
        )

        # Stop only at the actual battle command input loop, after the wild
        # reveal and Pikachu entrance animations have completed naturally.
        def is_battle_command_wait() -> bool:
            return (
                emulator.is_in_battle()
                and emulator.read("wTopMenuItemY") == 14
                and emulator.read("wTopMenuItemX") in {9, 15}
                and emulator.read("wMaxMenuItem") == 1
                and emulator.read("wMenuWatchedKeys") in {0x11, 0x21}
            )

        emulator.advance_until(
            is_battle_command_wait,
            button="a",
            max_presses=30,
            description="stable wild battle command screen",
        )
        emulator.tick(2)
        battle_menu = _observe(emulator, f"{label}-wild-battle-menu.png")
        battle_state = (
            emulator.read("wBattleType"),
            emulator.read("wEnemyMonSpecies"),
            emulator.read("wEnemyMonLevel"),
            emulator.read("wBattleMonSpecies"),
            emulator.read("wCurrentMenuItem"),
            emulator.read("wBattleAndStartSavedMenuItem"),
        )

        # The default cursor is FIGHT. Navigate to RUN and keep selecting it
        # if Pikachu fails to escape on the first attempt.
        emulator.press("down")
        emulator.press("right")
        emulator.press("a")
        emulator.advance_until(
            lambda: not emulator.is_in_battle(),
            button="a",
            max_presses=80,
            description="natural escape from Route 1 battle",
        )
        route_direction = "down" if emulator.read("wYCoord") < 30 else "up"
        walk_to_value(
            emulator,
            "wYCoord",
            30,
            route_direction,
            "fixed post-battle Route 1 clearing",
        )
        walk_to_value(
            emulator,
            "wXCoord",
            10,
            "right" if emulator.read("wXCoord") < 10 else "left",
            "fixed post-battle Route 1 column",
        )
        emulator.tick(120)
        restored_route = _observe(emulator, f"{label}-route1-restored.png")
        (results / f"{label}-wild-battle-steps.json").write_text(
            json.dumps(
                {
                    "grass_pacing_steps": grass_pacing_steps,
                    "route_steps_to_encounter": route_steps,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except BaseException:
        emulator.save_screenshot(f"{label}-wild-battle-failure.png")
        state = {
            "frame": emulator.frame,
            "pc": emulator.pyboy.register_file.PC,
            "sp": emulator.pyboy.register_file.SP,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "in_battle": emulator.read("wIsInBattle"),
            "battle_type": emulator.read("wBattleType"),
            "enemy_species": emulator.read("wEnemyMonSpecies"),
            "enemy_level": emulator.read("wEnemyMonLevel"),
            "grass_pacing_steps": grass_pacing_steps,
            "route_steps_to_encounter": route_steps,
        }
        (results / f"{label}-wild-battle-failure.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    return WildBattleRoundTrip(
        battle_menu,
        battle_state,
        restored_route,
        (route_steps, grass_pacing_steps),
    )


def _run_pallet_save_continue_round_trip(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> SaveContinueRoundTrip:
    """Save in Pallet, soft-reset, Continue, and resume natural movement."""
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)

    def save_ui(filename: str) -> None:
        emulator.save_screenshot(f"{label}-{filename}.png")

    try:
        complete_oaks_lab_intro(
            emulator,
            bedroom_setup=_mode_setup(yellow_mode),
        )
        walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
        walk_to_value(emulator, "wXCoord", 7, "left", "Pallet sign column")
        walk_to_value(emulator, "wYCoord", 10, "up", "Pallet sign row")
        emulator.tick(60)

        # This fresh game has no Pokédex, so SAVE is the fourth start-menu
        # item. Drive the real prompt, SRAM write, and dismissal path.
        emulator.press("start")
        for _ in range(3):
            emulator.press("down")
        emulator.press("a")
        emulator.press("a")
        save_ui("save-confirmation")
        emulator.press("a")
        assert emulator.read("wSaveFileStatus") == 2, "save did not become valid"
        emulator.press("a")
        save_ui("game-saved")
        emulator.press("b")
        emulator.tick(120)
        before_reset = _observe(emulator, f"{label}-before-reset.png")

        # Yellow's documented A+B+Start+Select soft-reset path keeps the SRAM
        # created above while rebuilding all volatile renderer state.
        for button in ("a", "b", "start", "select"):
            emulator.pyboy.button_press(button)
        emulator.tick(20)
        for button in ("a", "b", "start", "select"):
            emulator.pyboy.button_release(button)
        emulator.tick(120)
        save_ui("soft-reset")

        def is_continue_menu() -> bool:
            return (
                emulator.read("wSaveFileStatus") == 2
                and emulator.read("wTopMenuItemX") == 1
                and emulator.read("wTopMenuItemY") == 2
                and emulator.read("wMaxMenuItem") == 2
                and emulator.read("wMenuWatchedKeys") == 0x0B
            )

        for _ in range(24):
            if is_continue_menu():
                break
            emulator.press("start", wait_frames=30)
        assert is_continue_menu(), "soft reset did not reach a valid Continue menu"
        save_ui("continue-menu")

        emulator.press("a")
        save_ui("continue-info")
        emulator.press("a")
        for _ in range(30):
            if (
                emulator.read("wCurMap") == PALLET_TOWN
                and emulator.read("wStatusFlags6") & 1
            ):
                break
            emulator.tick(60)
        assert emulator.read("wCurMap") == PALLET_TOWN
        assert emulator.read("wStatusFlags6") & 1
        emulator.tick(120)
        restored = _observe(emulator, f"{label}-continued-pallet.png")

        # A plausible restored frame isn't enough: make Yellow accept movement
        # in both directions, then compare the same settled saved coordinate.
        walk_to_value(emulator, "wXCoord", 8, "right", "continued east step")
        walk_to_value(emulator, "wXCoord", 7, "left", "continued saved position")
        emulator.tick(120)
        playable = _observe(emulator, f"{label}-continued-playable.png")
    except BaseException:
        emulator.save_screenshot(f"{label}-save-continue-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "pc": emulator.pyboy.register_file.PC,
            "sp": emulator.pyboy.register_file.SP,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "save_status": emulator.read("wSaveFileStatus"),
        }
        (results / f"{label}-save-continue-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    return SaveContinueRoundTrip(before_reset, restored, playable)


def _run_pallet_house_round_trip(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> PalletHouseRoundTrip:
    """Enter Red's house from Pallet and return through its natural warp."""
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)

    try:
        complete_oaks_lab_intro(
            emulator,
            bedroom_setup=_mode_setup(yellow_mode),
        )
        walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
        walk_to_value(emulator, "wYCoord", 6, "up", "Red's house row")
        walk_to_value(emulator, "wXCoord", 5, "left", "Red's house door")
        walk_to_value(emulator, "wCurMap", 0x25, "up", "Red's house 1F")
        emulator.tick(120)
        interior = _observe(emulator, f"{label}-reds-house-1f.png")

        walk_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "Pallet Town")
        emulator.tick(120)
        restored_pallet = _observe(emulator, f"{label}-pallet-restored.png")
    except BaseException:
        emulator.save_screenshot(f"{label}-pallet-house-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "pc": emulator.pyboy.register_file.PC,
            "sp": emulator.pyboy.register_file.SP,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "in_battle": emulator.read("wIsInBattle"),
        }
        (results / f"{label}-pallet-house-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    return PalletHouseRoundTrip(interior, restored_pallet)


def _run_oak_capture_sequence(
    product: str,
    results: Path,
    *,
    yellow_mode: bool,
) -> OakCaptureSequence:
    """Play Oak's scripted Pikachu capture and retain its visual milestones."""
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    label = _mode_label(product, yellow_mode)
    observations: dict[str, JourneyObservation] = {}
    event_states: dict[str, tuple[int, ...]] = {}

    def event_state() -> tuple[int, ...]:
        return (
            emulator.read("wCurMap"),
            emulator.read("wPalletTownCurScript"),
            emulator.read("wBattleType"),
            emulator.read("wIsInBattle"),
            emulator.read("wCurOpponent"),
            emulator.read("wCurEnemyLevel"),
            emulator.read("wEnemyMonSpecies"),
            emulator.read("wCapturedMonSpecies"),
            emulator.read("wCurItem"),
            emulator.read("wAnimationID"),
            emulator.read("wPokeBallAnimData"),
        )

    def checkpoint(name: str) -> None:
        observations[name] = _observe(emulator, f"{label}-{name}.png")
        event_states[name] = event_state()

    def advance_framewise(
        predicate: Callable[[], bool],
        description: str,
        *,
        max_presses: int,
    ) -> None:
        for _ in range(max_presses):
            if predicate():
                return
            emulator.pyboy.button("a", delay=2)
            for _ in range(120):
                emulator.tick()
                if predicate():
                    return
        raise AssertionError(f"Timed out waiting for {description}")

    try:
        reach_bedroom_overworld(emulator)
        select_renderer_mode(emulator, yellow_mode=yellow_mode)
        walk_from_bedroom_to_oak(emulator)
        checkpoint("oak-capture-oak-dialogue")
        advance_framewise(
            lambda: (
                emulator.read("wPalletTownCurScript")
                == SCRIPT_PALLETTOWN_PIKACHU_BATTLE
            ),
            "Oak facing the wild Pikachu",
            max_presses=30,
        )
        event_states["oak-capture-script-ready"] = event_state()

        advance_framewise(
            lambda: (
                emulator.read("wBattleType") == BATTLE_TYPE_PIKACHU
                and emulator.is_in_battle()
            ),
            "Oak's Pikachu battle",
            max_presses=8,
        )

        # The simulated ITEM selection and toss are transient. Poll every real
        # frame while supplying ordinary A input so this exercises the exact
        # animation path that previously left corrupt sprites on the overworld.
        battle_presentation_seen = False
        ball_animation_seen = False
        post_capture_seen = False
        for _ in range(60):
            emulator.pyboy.button("a", delay=2)
            for _ in range(120):
                emulator.tick()
                if (
                    not battle_presentation_seen
                    and emulator.read("wBattleType") == BATTLE_TYPE_PIKACHU
                    and emulator.is_in_battle()
                    and emulator.read("wCurItem") == POKE_BALL
                    and emulator.read("wAnimationID") not in CAPTURE_ANIMATION_IDS
                ):
                    checkpoint("oak-capture-battle")
                    battle_presentation_seen = True
                if (
                    not ball_animation_seen
                    and emulator.read("wBattleType") == BATTLE_TYPE_PIKACHU
                    and emulator.read("wAnimationID") in CAPTURE_ANIMATION_IDS
                ):
                    checkpoint("oak-capture-ball-animation")
                    ball_animation_seen = True
                if (
                    ball_animation_seen
                    and not emulator.is_in_battle()
                    and emulator.read("wCurMap") == PALLET_TOWN
                ):
                    post_capture_seen = True
                    break
            if post_capture_seen:
                break
        assert battle_presentation_seen, (
            "Oak's simulated ITEM selection was not observed"
        )
        assert ball_animation_seen, "Oak's Poké Ball animation was not observed"
        assert post_capture_seen, "Oak's scripted capture battle did not clear"
        # Dismiss the final battle acknowledgement so Pallet's post-capture
        # script can render Oak's next real dialogue instead of a blank box.
        emulator.press("a", wait_frames=60)
        emulator.press("a", wait_frames=60)
        checkpoint("oak-capture-post-battle")

        emulator.advance_until(
            lambda: emulator.read("wCurMap") == OAKS_LAB,
            button="a",
            max_presses=40,
            description="following Oak into his lab after catching Pikachu",
        )
        emulator.tick(60)
        checkpoint("oak-capture-lab-transition")
    except BaseException:
        emulator.save_screenshot(f"{label}-oak-capture-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "pc": emulator.pyboy.register_file.PC,
            "sp": emulator.pyboy.register_file.SP,
            "event_state": event_state(),
        }
        (results / f"{label}-oak-capture-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    return OakCaptureSequence(
        oak_dialogue=observations["oak-capture-oak-dialogue"],
        battle_presentation=observations["oak-capture-battle"],
        ball_animation=observations["oak-capture-ball-animation"],
        post_capture=observations["oak-capture-post-battle"],
        lab_transition=observations["oak-capture-lab-transition"],
        event_states=event_states,
    )


def _linked_bytes(product: str, symbol: str, size: int) -> bytes:
    symbols = (
        (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines()
    )
    addresses = Emulator._parse_symbols(symbols)
    banks = Emulator._parse_symbol_banks(symbols)
    address = addresses[symbol]
    offset = banks[symbol] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[offset : offset + size]


def _linked_span(product: str, start: str, end: str) -> bytes:
    symbol_lines = (
        (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines()
    )
    addresses = Emulator._parse_symbols(symbol_lines)
    banks = Emulator._parse_symbol_banks(symbol_lines)
    assert banks[start] == banks[end], (product, start, end)
    return _linked_bytes(product, start, addresses[end] - addresses[start])


def _linked_overworld_bg_palettes(
    product: str,
    map_id: int,
    *,
    y_coord: int,
) -> bytes:
    """Resolve the linked map-specific palette payload published by the ROM."""
    palettes = bytearray(
        _linked_span(
            product,
            "FullColorOverworldBGPalettes",
            "FullColorOverworldBGPalettesEnd",
        )
    )
    assignments = _linked_span(
        product,
        "FullColorOverworldRoofAssignments",
        "FullColorOverworldRoofAssignmentsEnd",
    )
    roof_palettes = _linked_span(
        product,
        "FullColorOverworldRoofPalettes",
        "FullColorOverworldRoofPalettesEnd",
    )
    assert len(palettes) == 64
    assert 0 <= map_id < len(assignments), (product, map_id)
    route_6 = 0x11
    saffron_city = 0x0A
    roof_map_id = saffron_city if map_id == route_6 and y_coord < 2 else map_id
    roof_start = assignments[roof_map_id] * 4
    roof_middle_colors = roof_palettes[roof_start : roof_start + 4]
    assert len(roof_middle_colors) == 4, (product, map_id, roof_start)
    palettes[6 * 8 + 2 : 6 * 8 + 6] = roof_middle_colors
    return bytes(palettes)


def _visible_attribute_pairs(
    observation: JourneyObservation,
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (observation.tilemap[index], observation.attributes[index])
        for index in _visible_indices(observation)
    )


def _visible_indices(observation: JourneyObservation) -> tuple[int, ...]:
    scroll_x, scroll_y = observation.scroll
    indices = []
    for row in range(18):
        tile_y = (scroll_y // 8 + row) % 32
        for column in range(20):
            tile_x = (scroll_x // 8 + column) % 32
            indices.append(tile_y * 32 + tile_x)
    return tuple(indices)


def _visible_bg_patterns(observation: JourneyObservation) -> tuple[bytes, ...]:
    patterns = []
    unsigned_tiles = bool(observation.lcdc & (1 << 4))
    for index in _visible_indices(observation):
        tile = observation.tilemap[index]
        if unsigned_tiles:
            offset = tile * 16
        else:
            signed_tile = tile if tile < 0x80 else tile - 0x100
            offset = 0x1000 + signed_tile * 16
        patterns.append(observation.tile_data[offset : offset + 16])
    return tuple(patterns)


def _first_mismatch(actual: bytes, expected: bytes) -> dict[str, int] | None:
    for offset, (actual_byte, expected_byte) in enumerate(zip(actual, expected)):
        if actual_byte != expected_byte:
            return {
                "offset": offset,
                "actual": actual_byte,
                "expected": expected_byte,
            }
    return None


def _assert_visible_bg_parity(
    candidate: JourneyObservation,
    baseline: JourneyObservation,
    checkpoint: str,
) -> None:
    candidate_indices = _visible_indices(candidate)
    baseline_indices = _visible_indices(baseline)
    candidate_tiles = tuple(candidate.tilemap[index] for index in candidate_indices)
    baseline_tiles = tuple(baseline.tilemap[index] for index in baseline_indices)
    assert candidate_tiles == baseline_tiles, checkpoint

    candidate_patterns = _visible_bg_patterns(candidate)
    baseline_patterns = _visible_bg_patterns(baseline)
    for tile, candidate_pattern, baseline_pattern in zip(
        candidate_tiles,
        candidate_patterns,
        baseline_patterns,
    ):
        # Yellow animates flower and water pattern bytes in place. Their phase
        # follows DIV/RNG cadence, but their tile IDs and map geometry do not.
        if tile not in {0x03, 0x14}:
            assert candidate_pattern == baseline_pattern, (checkpoint, tile)


def _assert_oam_semantics(
    candidate: JourneyObservation,
    baseline: JourneyObservation,
    checkpoint: str,
) -> None:
    assert candidate.sprite_picture_ids == baseline.sprite_picture_ids, checkpoint
    # The first four entries are Yellow's deterministic player/follower
    # composite. NPC facing and coordinates legitimately follow hRandomAdd.
    assert candidate.hardware_oam[:16] == baseline.hardware_oam[:16], checkpoint
    assert candidate.shadow_oam[:16] == baseline.shadow_oam[:16], checkpoint
    # Yellow performs OAM DMA before PrepareOAMData in VBlank, so hardware OAM
    # is intentionally one frame behind the shadow buffer for moving NPCs.
    # Requiring byte equality here made a valid animation phase look corrupt.
    for offset in range(16, len(candidate.hardware_oam), 4):
        y, x = candidate.hardware_oam[offset : offset + 2]
        # Hardware coordinates wrap for sprites clipped above/left of screen.
        assert y == 0 or y <= 160 or y >= 240, (checkpoint, offset, "y", y)
        assert x == 0 or x <= 168 or x >= 248, (checkpoint, offset, "x", x)


def test_preset_name_menu_has_three_as_its_last_item() -> None:
    correct = cast(Emulator, _PresetMenuState(3))
    former_false_positive = cast(Emulator, _PresetMenuState(4))

    assert Emulator.is_preset_name_menu(correct)
    assert not Emulator.is_preset_name_menu(former_false_positive)


def test_scenario_setup_removes_stale_failure_evidence() -> None:
    results = RESULTS_ROOT / "cleanup-contract"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stale-failure.json").write_text("{}\n", encoding="utf-8")
    (results / "timeout-stale.png").write_bytes(b"stale")

    _prepare_results(results)

    assert not tuple(results.iterdir())


def test_production_cold_boot_reaches_viridian_without_state_injection() -> None:
    _prepare_results(RESULTS_ROOT / "production-natural")
    observations = _run_journey(
        "pokeyellow",
        RESULTS_ROOT / "production-natural",
        use_debug_repel=False,
        yellow_mode=False,
    )

    assert observations["bedroom"].logical_state[:3] == (0x26, 6, 3)
    assert observations["viridian-entry"].logical_state[:3] == (0x01, 35, 20)
    assert observations["viridian-entry"].logical_state[3] == 1


def test_production_cold_boot_changes_only_color_state_between_modes() -> None:
    results = RESULTS_ROOT / "paired-production"
    _prepare_results(results)
    yellow = _run_journey(
        "pokeyellow",
        results,
        use_debug_repel=False,
        yellow_mode=True,
    )
    color = _run_journey(
        "pokeyellow",
        results,
        use_debug_repel=False,
        yellow_mode=False,
    )

    overworld_attributes = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )
    pallet_palettes = _linked_overworld_bg_palettes(
        "pokeyellow", PALLET_TOWN, y_coord=0
    )
    bedroom_palettes = _linked_bytes(
        "pokeyellow", "FullColorIndoorBGPalettes", 64
    )
    bedroom_attributes = _linked_bytes(
        "pokeyellow", "FullColorRedsHouseTileAttributes", 256
    )
    diagnostics = {}
    for name in CHECKPOINTS:
        baseline = yellow[name]
        candidate = color[name]
        expected_palettes, expected_attributes = (
            (bedroom_palettes, bedroom_attributes)
            if name == "bedroom"
            else (
                _linked_overworld_bg_palettes(
                    "pokeyellow",
                    candidate.logical_state[0],
                    y_coord=candidate.logical_state[1],
                ),
                overworld_attributes,
            )
        )
        visible_pairs = _visible_attribute_pairs(candidate)
        candidate_visible_indices = _visible_indices(candidate)
        baseline_visible_indices = _visible_indices(baseline)
        candidate_visible_tilemap = bytes(
            candidate.tilemap[index] for index in candidate_visible_indices
        )
        baseline_visible_tilemap = bytes(
            baseline.tilemap[index] for index in baseline_visible_indices
        )
        candidate_visible_attributes = bytes(
            candidate.attributes[index] for index in candidate_visible_indices
        )
        baseline_visible_attributes = bytes(
            baseline.attributes[index] for index in baseline_visible_indices
        )
        visible_attribute_mismatches = [
            {
                "visible_index": index,
                "tile": tile,
                "actual": attribute,
                "expected": expected_attributes[tile],
            }
            for index, (tile, attribute) in enumerate(visible_pairs)
            if attribute != expected_attributes[tile]
        ]
        full_attribute_mismatches = [
            index
            for index, (tile, attribute) in enumerate(
                zip(candidate.tilemap, candidate.attributes)
            )
            if attribute != expected_attributes[tile]
        ]
        diagnostics[name] = {
            "frame": candidate.frame,
            "baseline_frame": baseline.frame,
            "rng_state": candidate.rng_state,
            "baseline_rng_state": baseline.rng_state,
            "logical_state": candidate.logical_state,
            "passive_state": candidate.passive_state,
            "renderer_state": candidate.renderer_state,
            "bank0_tile_data_equal": candidate.tile_data == baseline.tile_data,
            "bank0_tile_data_first_mismatch": _first_mismatch(
                candidate.tile_data, baseline.tile_data
            ),
            "bank0_tilemap_equal": candidate.tilemap == baseline.tilemap,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate.tilemap, baseline.tilemap
            ),
            "visible_bank0_tilemap_equal": (
                candidate_visible_tilemap == baseline_visible_tilemap
            ),
            "visible_bank0_tilemap_first_mismatch": _first_mismatch(
                candidate_visible_tilemap, baseline_visible_tilemap
            ),
            "visible_bg_patterns_equal": (
                _visible_bg_patterns(candidate) == _visible_bg_patterns(baseline)
            ),
            "hardware_oam_first_mismatch": _first_mismatch(
                candidate.hardware_oam, baseline.hardware_oam
            ),
            "shadow_oam_first_mismatch": _first_mismatch(
                candidate.shadow_oam, baseline.shadow_oam
            ),
            "palette_first_donor_mismatch": _first_mismatch(
                candidate.bg_palettes, expected_palettes
            ),
            "palette_first_baseline_mismatch": _first_mismatch(
                candidate.bg_palettes, baseline.bg_palettes
            ),
            "roof_middle_colors": list(candidate.bg_palettes[6 * 8 + 2 : 6 * 8 + 6]),
            "roof_middle_first_pallet_mismatch": _first_mismatch(
                candidate.bg_palettes[6 * 8 + 2 : 6 * 8 + 6],
                pallet_palettes[6 * 8 + 2 : 6 * 8 + 6],
            ),
            "visible_attribute_first_baseline_mismatch": _first_mismatch(
                candidate_visible_attributes, baseline_visible_attributes
            ),
            "full_attribute_first_baseline_mismatch": _first_mismatch(
                candidate.attributes, baseline.attributes
            ),
            "visible_attribute_mismatch_count": len(visible_attribute_mismatches),
            "visible_attribute_first_mismatch": (
                visible_attribute_mismatches[0]
                if visible_attribute_mismatches
                else None
            ),
            "full_attribute_mismatch_count": len(full_attribute_mismatches),
            "full_attribute_first_mismatch": (
                full_attribute_mismatches[0] if full_attribute_mismatches else None
            ),
        }
    (results / "paired-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert (
        diagnostics["viridian-entry"]["roof_middle_first_pallet_mismatch"]
        is not None
    )

    color_difference_seen = False
    for name in CHECKPOINTS:
        baseline = yellow[name]
        candidate = color[name]
        expected_palettes, expected_attributes = (
            (bedroom_palettes, bedroom_attributes)
            if name == "bedroom"
            else (
                _linked_overworld_bg_palettes(
                    "pokeyellow",
                    candidate.logical_state[0],
                    y_coord=candidate.logical_state[1],
                ),
                overworld_attributes,
            )
        )
        assert candidate.logical_state == baseline.logical_state, name
        assert candidate.renderer_state == (0, 0), name
        assert baseline.renderer_preference == 1, name
        assert candidate.renderer_preference == 0, name
        if name == "bedroom":
            # Switching the fresh-save default from Color to Yellow naturally
            # catches the bounded bank-1 cleanup in flight. The presentation
            # is already inactive and no palette publication may be pending.
            assert baseline.passive_state[:2] == (0, 0), name
            assert baseline.passive_state[2] > 0, name
        else:
            assert baseline.passive_state[:3] == (0, 0, 0), name
        _assert_visible_bg_parity(candidate, baseline, name)

        assert name in COLOR_CHECKPOINTS
        assert candidate.passive_state == (
            1,
            0,
            0,
            candidate.renderer_generation[0],
        ), name
        assert candidate.bg_palettes == expected_palettes, name
        for tile, attribute in _visible_attribute_pairs(candidate):
            assert attribute == expected_attributes[tile], (
                name,
                tile,
                attribute,
                expected_attributes[tile],
            )
        color_difference_seen |= (
            candidate.bg_palettes != baseline.bg_palettes
            or candidate.attributes != baseline.attributes
        )

        _assert_oam_semantics(candidate, baseline, name)

    assert color_difference_seen, "Color mode never exposed the guarded color slice"


def test_reverse_route1_ledges_preserve_yellow_and_passive_color_state() -> None:
    results = RESULTS_ROOT / "paired-reverse-route1"
    _prepare_results(results)
    yellow = _run_reverse_route1_journey(
        "pokeyellow_debug", results, yellow_mode=True
    )
    color = _run_reverse_route1_journey(
        "pokeyellow_debug", results, yellow_mode=False
    )

    expected_attributes = _linked_bytes(
        "pokeyellow_debug", "FullColorOverworldTileAttributes", 256
    )
    pallet_palettes = _linked_overworld_bg_palettes(
        "pokeyellow_debug", PALLET_TOWN, y_coord=0
    )
    diagnostics = {}

    for name in REVERSE_CHECKPOINTS:
        baseline = yellow[name]
        candidate = color[name]
        expected_palettes = _linked_overworld_bg_palettes(
            "pokeyellow_debug",
            candidate.logical_state[0],
            y_coord=candidate.logical_state[1],
        )
        visible_mismatches = [
            {
                "visible_index": index,
                "tile": tile,
                "actual": attribute,
                "expected": expected_attributes[tile],
            }
            for index, (tile, attribute) in enumerate(
                _visible_attribute_pairs(candidate)
            )
            if attribute != expected_attributes[tile]
        ]
        diagnostics[name] = {
            "frame": candidate.frame,
            "baseline_frame": baseline.frame,
            "logical_state": candidate.logical_state,
            "passive_state": candidate.passive_state,
            "renderer_state": candidate.renderer_state,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate.tilemap, baseline.tilemap
            ),
            "visible_attribute_mismatch_count": len(visible_mismatches),
            "visible_attribute_first_mismatch": (
                visible_mismatches[0] if visible_mismatches else None
            ),
            "palette_first_donor_mismatch": _first_mismatch(
                candidate.bg_palettes, expected_palettes
            ),
            "roof_middle_colors": list(candidate.bg_palettes[6 * 8 + 2 : 6 * 8 + 6]),
            "roof_middle_first_pallet_mismatch": _first_mismatch(
                candidate.bg_palettes[6 * 8 + 2 : 6 * 8 + 6],
                pallet_palettes[6 * 8 + 2 : 6 * 8 + 6],
            ),
        }

        assert candidate.logical_state == baseline.logical_state, name
        assert candidate.renderer_state == (0, 0), name
        assert baseline.renderer_preference == 1, name
        assert candidate.renderer_preference == 0, name
        assert baseline.passive_state[:3] == (0, 0, 0), name
        _assert_visible_bg_parity(candidate, baseline, name)
        _assert_oam_semantics(candidate, baseline, name)

        assert name in REVERSE_COLOR_CHECKPOINTS
        assert candidate.passive_state == (
            1,
            0,
            0,
            candidate.renderer_generation[0],
        ), name
        assert candidate.bg_palettes == expected_palettes, name
        assert not visible_mismatches, name

    assert color["route1-reentry"].logical_state[:3] == (ROUTE_1, 0, 10)
    assert color["pallet-reentry"].logical_state[:3] == (PALLET_TOWN, 0, 10)
    (results / "paired-reverse-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert diagnostics["viridian-southbound"][
        "roof_middle_first_pallet_mismatch"
    ] is not None


def test_pallet_house_round_trip_restores_passive_color_slice() -> None:
    results = RESULTS_ROOT / "paired-pallet-house"
    _prepare_results(results)
    yellow = _run_pallet_house_round_trip(
        "pokeyellow", results, yellow_mode=True
    )
    color = _run_pallet_house_round_trip(
        "pokeyellow", results, yellow_mode=False
    )

    expected_pallet_palettes = _linked_overworld_bg_palettes(
        "pokeyellow", PALLET_TOWN, y_coord=0
    )
    expected_pallet_attributes = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )
    expected_interior_palettes = _linked_bytes(
        "pokeyellow", "FullColorIndoorBGPalettes", 64
    )
    expected_interior_attributes = _linked_bytes(
        "pokeyellow", "FullColorRedsHouseTileAttributes", 256
    )

    baseline_inside = yellow.interior
    candidate_inside = color.interior
    assert candidate_inside.logical_state == baseline_inside.logical_state
    assert candidate_inside.logical_state == (0x25, 7, 2, 1, 22, 0)
    interior_visible_mismatches = [
        {
            "visible_index": index,
            "tile": tile,
            "actual": attribute,
            "expected": expected_interior_attributes[tile],
        }
        for index, (tile, attribute) in enumerate(
            _visible_attribute_pairs(candidate_inside)
        )
        if attribute != expected_interior_attributes[tile]
    ]
    assert candidate_inside.passive_state == (
        1,
        0,
        0,
        candidate_inside.renderer_generation[0],
    )
    assert candidate_inside.renderer_state == (0, 0)
    assert baseline_inside.renderer_preference == 1
    assert candidate_inside.renderer_preference == 0
    assert baseline_inside.passive_state[:3] == (0, 0, 0)
    _assert_visible_bg_parity(candidate_inside, baseline_inside, "reds-house-1f")
    _assert_oam_semantics(candidate_inside, baseline_inside, "reds-house-1f")
    assert candidate_inside.bg_palettes == expected_interior_palettes
    assert not interior_visible_mismatches
    assert candidate_inside.screen.tobytes() != baseline_inside.screen.tobytes()

    baseline_outside = yellow.restored_pallet
    candidate_outside = color.restored_pallet
    visible_mismatches = [
        {
            "visible_index": index,
            "tile": tile,
            "actual": attribute,
            "expected": expected_pallet_attributes[tile],
        }
        for index, (tile, attribute) in enumerate(
            _visible_attribute_pairs(candidate_outside)
        )
        if attribute != expected_pallet_attributes[tile]
    ]
    diagnostics = {
        "interior": {
            "logical_state": candidate_inside.logical_state,
            "passive_state": candidate_inside.passive_state,
            "renderer_state": candidate_inside.renderer_state,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate_inside.tilemap, baseline_inside.tilemap
            ),
            "palette_first_authority_mismatch": _first_mismatch(
                candidate_inside.bg_palettes, expected_interior_palettes
            ),
            "visible_attribute_mismatch_count": len(interior_visible_mismatches),
            "visible_attribute_first_mismatch": (
                interior_visible_mismatches[0]
                if interior_visible_mismatches
                else None
            ),
            "screen_equal": (
                candidate_inside.screen.tobytes() == baseline_inside.screen.tobytes()
            ),
        },
        "restored_pallet": {
            "logical_state": candidate_outside.logical_state,
            "passive_state": candidate_outside.passive_state,
            "renderer_state": candidate_outside.renderer_state,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate_outside.tilemap, baseline_outside.tilemap
            ),
            "palette_first_donor_mismatch": _first_mismatch(
                candidate_outside.bg_palettes, expected_pallet_palettes
            ),
            "visible_attribute_mismatch_count": len(visible_mismatches),
            "visible_attribute_first_mismatch": (
                visible_mismatches[0] if visible_mismatches else None
            ),
        },
    }
    (results / "paired-pallet-house-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert candidate_outside.logical_state == baseline_outside.logical_state
    assert candidate_outside.logical_state == (PALLET_TOWN, 6, 5, 1, 22, 0)
    assert candidate_outside.passive_state == (
        1,
        0,
        0,
        candidate_outside.renderer_generation[0],
    )
    assert candidate_outside.renderer_state == (0, 0)
    assert baseline_outside.renderer_preference == 1
    assert candidate_outside.renderer_preference == 0
    assert baseline_outside.passive_state[:3] == (0, 0, 0)
    _assert_visible_bg_parity(candidate_outside, baseline_outside, "restored-pallet")
    _assert_oam_semantics(candidate_outside, baseline_outside, "restored-pallet")
    assert candidate_outside.bg_palettes == expected_pallet_palettes
    assert not visible_mismatches


def test_oak_scripted_pikachu_capture_preserves_yellow_visuals_and_completes() -> None:
    """Cover the historic battle-over-overworld corruption from a cold boot."""
    results = RESULTS_ROOT / "paired-oak-capture"
    _prepare_results(results)
    yellow = _run_oak_capture_sequence(
        "pokeyellow", results, yellow_mode=True
    )
    color = _run_oak_capture_sequence(
        "pokeyellow", results, yellow_mode=False
    )

    expected_attributes = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )
    expected_lab_palettes = _linked_bytes(
        "pokeyellow", "FullColorIndoorBGPalettes", 64
    )
    expected_lab_attributes = _linked_bytes(
        "pokeyellow", "FullColorGymTileAttributes", 256
    )
    checkpoints = {
        "oak_dialogue": (yellow.oak_dialogue, color.oak_dialogue),
        "battle_presentation": (
            yellow.battle_presentation,
            color.battle_presentation,
        ),
        "ball_animation": (yellow.ball_animation, color.ball_animation),
        "post_capture": (yellow.post_capture, color.post_capture),
        "lab_transition": (yellow.lab_transition, color.lab_transition),
    }
    diagnostics = {}
    for name, (baseline, candidate) in checkpoints.items():
        assert candidate.logical_state == baseline.logical_state, name
        assert candidate.renderer_state == (0, 0), name
        assert baseline.renderer_preference == 1, name
        assert candidate.renderer_preference == 0, name
        assert baseline.passive_state[:3] == (0, 0, 0), name
        _assert_visible_bg_parity(candidate, baseline, name)
        _assert_oam_semantics(candidate, baseline, name)
        diagnostics[name] = {
            "frame": candidate.frame,
            "baseline_frame": baseline.frame,
            "event_state": color.event_states[
                {
                    "oak_dialogue": "oak-capture-oak-dialogue",
                    "battle_presentation": "oak-capture-battle",
                    "ball_animation": "oak-capture-ball-animation",
                    "post_capture": "oak-capture-post-battle",
                    "lab_transition": "oak-capture-lab-transition",
                }[name]
            ],
            "passive_state": candidate.passive_state,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate.tilemap, baseline.tilemap
            ),
            "hardware_oam_first_mismatch": _first_mismatch(
                candidate.hardware_oam, baseline.hardware_oam
            ),
            "screen_equal": candidate.screen.tobytes() == baseline.screen.tobytes(),
        }

    assert color.event_states == yellow.event_states
    assert color.event_states["oak-capture-script-ready"][1:4] == (
        SCRIPT_PALLETTOWN_PIKACHU_BATTLE,
        0,
        0,
    )
    for name in ("oak-capture-battle", "oak-capture-ball-animation"):
        assert color.event_states[name][2] == BATTLE_TYPE_PIKACHU, name
        assert color.event_states[name][3] != 0, name
        assert color.event_states[name][4:7] == (PIKACHU, 5, PIKACHU), name
    assert color.event_states["oak-capture-ball-animation"][9] in CAPTURE_ANIMATION_IDS
    assert color.event_states["oak-capture-post-battle"][0:4] == (
        PALLET_TOWN,
        SCRIPT_PALLETTOWN_AFTER_PIKACHU_BATTLE,
        0,
        0,
    )
    assert color.event_states["oak-capture-lab-transition"][0] == OAKS_LAB

    for name in ("oak_dialogue", "post_capture"):
        baseline, candidate = checkpoints[name]
        expected_palettes = _linked_overworld_bg_palettes(
            "pokeyellow",
            candidate.logical_state[0],
            y_coord=candidate.logical_state[1],
        )
        assert candidate.passive_state == (
            1,
            0,
            0,
            candidate.renderer_generation[0],
        ), name
        assert candidate.bg_palettes == expected_palettes, name
        for tile, attribute in _visible_attribute_pairs(candidate):
            assert attribute == expected_attributes[tile], name

    baseline_lab, candidate_lab = checkpoints["lab_transition"]
    assert candidate_lab.passive_state == (
        1,
        0,
        0,
        candidate_lab.renderer_generation[0],
    )
    assert candidate_lab.bg_palettes == expected_lab_palettes
    for tile, attribute in _visible_attribute_pairs(candidate_lab):
        assert attribute == expected_lab_attributes[tile], "lab_transition"
    assert candidate_lab.screen.tobytes() != baseline_lab.screen.tobytes()

    # Battles remain wholly stock-owned. The modes must be pixel-identical at
    # both transient checkpoints, including the real Poké Ball toss that the
    # old harness skipped completely.
    for name in ("battle_presentation", "ball_animation"):
        baseline, candidate = checkpoints[name]
        # The guarded Pallet context remains active for return, while the
        # battle owns VRAM and no passive transaction remains pending.
        assert candidate.passive_state[1:3] == (0, 0), name
        assert bytes(
            candidate.attributes[index] for index in _visible_indices(candidate)
        ) == bytes(
            baseline.attributes[index] for index in _visible_indices(baseline)
        ), name
        assert candidate.bg_palettes[:8] == baseline.bg_palettes[:8], name
        assert candidate.hardware_oam == baseline.hardware_oam, name
        assert candidate.shadow_oam == baseline.shadow_oam, name
        assert candidate.screen.tobytes() == baseline.screen.tobytes(), name

    (results / "paired-oak-capture-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_pallet_dialogue_party_round_trip_preserves_yellow_and_color_state() -> None:
    results = RESULTS_ROOT / "pallet-ui-boundary"
    _prepare_results(results)
    yellow = _run_pallet_ui_boundary(
        "pokeyellow_debug", results, yellow_mode=True
    )
    color = _run_pallet_ui_boundary(
        "pokeyellow_debug", results, yellow_mode=False
    )

    expected_names = (
        "stable-overworld",
        "dialogue",
        "dialogue-restored",
        "start-menu",
        "direct-start-restored",
        "party",
        "returned-start-menu",
        "restored-overworld",
        "viridian-entry",
    )
    assert tuple(yellow) == expected_names
    assert tuple(color) == expected_names

    expected_attributes = _linked_bytes(
        "pokeyellow_debug", "FullColorOverworldTileAttributes", 256
    )
    pallet_palettes = _linked_overworld_bg_palettes(
        "pokeyellow_debug", PALLET_TOWN, y_coord=0
    )
    initial_generation = color["stable-overworld"].journey.renderer_generation
    for name in expected_names:
        baseline = yellow[name]
        candidate = color[name]
        assert candidate.journey.logical_state == baseline.journey.logical_state, name
        assert candidate.menu_state == baseline.menu_state, name
        assert candidate.input_state == baseline.input_state, name
        assert candidate.journey.renderer_state == (0, 0), name
        assert baseline.journey.renderer_preference == 1, name
        assert candidate.journey.renderer_preference == 0, name
        assert baseline.journey.passive_state[:3] == (0, 0, 0), name
        assert candidate.journey.renderer_generation == initial_generation, name
        # Shipped products omit the audit-only retained scheduler diagnostics.
        assert candidate.scheduler_state == baseline.scheduler_state == (), name
        _assert_visible_bg_parity(candidate.journey, baseline.journey, name)
        _assert_oam_semantics(candidate.journey, baseline.journey, name)

    stable = color["stable-overworld"].journey
    restored = color["restored-overworld"].journey
    assert stable.logical_state == (0, 10, 7, 1, 22, 0)
    assert restored.logical_state == stable.logical_state
    assert color["stable-overworld"].input_state == (0, 0, 0)
    assert color["restored-overworld"].input_state == (0, 0, 0)

    assert color["start-menu"].menu_state[:3] == (0, 6, 0xCB)
    assert color["party"].menu_state[:5] == (0, 0, 0x03, 2, 0)
    assert color["returned-start-menu"].menu_state[:3] == (0, 6, 0xCB)

    assert stable.passive_state == (1, 0, 0, initial_generation[0])
    assert restored.passive_state == stable.passive_state
    boundary_diagnostics = {}
    for name in (
        "stable-overworld",
        "dialogue-restored",
        "direct-start-restored",
        "restored-overworld",
        "viridian-entry",
    ):
        observation = color[name].journey
        expected_palettes = _linked_overworld_bg_palettes(
            "pokeyellow_debug",
            observation.logical_state[0],
            y_coord=observation.logical_state[1],
        )
        mismatches = [
            {
                "row": visible_index // 20,
                "column": visible_index % 20,
                "tile": tile,
                "actual": attribute,
                "expected": expected_attributes[tile],
            }
            for visible_index, (tile, attribute) in enumerate(
                _visible_attribute_pairs(observation)
            )
            if attribute != expected_attributes[tile]
        ]
        boundary_diagnostics[name] = {
            "palette_first_authority_mismatch": _first_mismatch(
                observation.bg_palettes, expected_palettes
            ),
            "roof_middle_colors": list(
                observation.bg_palettes[6 * 8 + 2 : 6 * 8 + 6]
            ),
            "roof_middle_first_pallet_mismatch": _first_mismatch(
                observation.bg_palettes[6 * 8 + 2 : 6 * 8 + 6],
                pallet_palettes[6 * 8 + 2 : 6 * 8 + 6],
            ),
            "visible_mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }
        assert observation.bg_palettes == expected_palettes, name
        assert not mismatches, name
    (results / "boundary-attribute-diagnostics.json").write_text(
        json.dumps(boundary_diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert boundary_diagnostics["viridian-entry"][
        "roof_middle_first_pallet_mismatch"
    ] is not None
    _assert_visible_bg_parity(restored, stable, "restored-overworld")

    assert color["viridian-entry"].journey.logical_state[:4] == (
        VIRIDIAN_CITY,
        35,
        20,
        1,
    )


def test_route1_wild_battle_round_trip_restores_passive_color_slice() -> None:
    results = RESULTS_ROOT / "route1-wild-battle"
    _prepare_results(results)
    yellow = _run_route1_wild_battle_round_trip(
        "pokeyellow", results, yellow_mode=True
    )
    color = _run_route1_wild_battle_round_trip(
        "pokeyellow", results, yellow_mode=False
    )
    for journey in (yellow, color):
        route_steps, grass_pacing_steps = journey.encounter_steps
        assert route_steps > 0
        assert 0 <= grass_pacing_steps <= 256

    expected_attributes = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )

    battle = color.battle_menu
    baseline_battle = yellow.battle_menu
    assert color.battle_state[0] == yellow.battle_state[0] == 0
    assert color.battle_state[1] != 0 and yellow.battle_state[1] != 0
    assert color.battle_state[2] != 0 and yellow.battle_state[2] != 0
    assert color.battle_state[3:] == yellow.battle_state[3:]
    assert battle.logical_state[0] == baseline_battle.logical_state[0] == 0x0C
    assert battle.logical_state[2:5] == baseline_battle.logical_state[2:5]
    assert battle.logical_state[-1] == baseline_battle.logical_state[-1] == 1
    # Battle setup owns the screen while the guarded Route 1 context remains
    # active for the eventual return. No pending passive write may survive.
    assert battle.passive_state[1:3] == (0, 0)
    assert battle.renderer_state == (0, 0)
    assert baseline_battle.renderer_preference == 1
    assert battle.renderer_preference == 0
    assert baseline_battle.passive_state[:3] == (0, 0, 0)
    # Wild species, levels, and Pikachu's naturally generated DVs legitimately
    # follow DIV cadence, so combatants and HP digits can differ. The stable
    # battle command UI must remain exact Yellow pixels, and no passive CGB
    # color may leak in.
    assert battle.screen.crop((64, 96, 160, 144)).tobytes() == (
        baseline_battle.screen.crop((64, 96, 160, 144)).tobytes()
    )
    assert bytes(
        battle.attributes[index] for index in _visible_indices(battle)
    ) == bytes(
        baseline_battle.attributes[index] for index in _visible_indices(baseline_battle)
    )
    assert battle.bg_palettes[:8] == baseline_battle.bg_palettes[:8]
    assert battle.hardware_oam == baseline_battle.hardware_oam
    assert battle.shadow_oam == baseline_battle.shadow_oam

    restored = color.restored_route
    baseline_restored = yellow.restored_route
    expected_palettes = _linked_overworld_bg_palettes(
        "pokeyellow",
        restored.logical_state[0],
        y_coord=restored.logical_state[1],
    )
    assert restored.logical_state == baseline_restored.logical_state
    assert restored.logical_state[0] == 0x0C
    assert restored.logical_state[-1] == 0
    assert restored.passive_state == (
        1,
        0,
        0,
        restored.renderer_generation[0],
    )
    assert restored.renderer_state == (0, 0)
    assert baseline_restored.renderer_preference == 1
    assert restored.renderer_preference == 0
    assert baseline_restored.passive_state[:3] == (0, 0, 0)
    _assert_visible_bg_parity(restored, baseline_restored, "post-wild-battle-route1")
    _assert_oam_semantics(restored, baseline_restored, "post-wild-battle-route1")
    assert restored.bg_palettes == expected_palettes
    for tile, attribute in _visible_attribute_pairs(restored):
        assert attribute == expected_attributes[tile]


def test_pallet_save_reset_continue_restores_playable_color_slice() -> None:
    results = RESULTS_ROOT / "pallet-save-continue"
    _prepare_results(results)
    yellow = _run_pallet_save_continue_round_trip(
        "pokeyellow", results, yellow_mode=True
    )
    color = _run_pallet_save_continue_round_trip(
        "pokeyellow", results, yellow_mode=False
    )

    expected_attributes = _linked_bytes(
        "pokeyellow", "FullColorOverworldTileAttributes", 256
    )
    diagnostics = {}

    for name in ("before_reset", "restored", "playable"):
        baseline = getattr(yellow, name)
        candidate = getattr(color, name)
        expected_palettes = _linked_overworld_bg_palettes(
            "pokeyellow",
            candidate.logical_state[0],
            y_coord=candidate.logical_state[1],
        )
        visible_mismatches = [
            {
                "visible_index": index,
                "tile": tile,
                "actual": attribute,
                "expected": expected_attributes[tile],
            }
            for index, (tile, attribute) in enumerate(
                _visible_attribute_pairs(candidate)
            )
            if attribute != expected_attributes[tile]
        ]
        diagnostics[name] = {
            "frame": candidate.frame,
            "baseline_frame": baseline.frame,
            "logical_state": candidate.logical_state,
            "renderer_generation": candidate.renderer_generation,
            "passive_state": candidate.passive_state,
            "renderer_state": candidate.renderer_state,
            "bank0_tilemap_first_mismatch": _first_mismatch(
                candidate.tilemap, baseline.tilemap
            ),
            "palette_first_donor_mismatch": _first_mismatch(
                candidate.bg_palettes, expected_palettes
            ),
            "visible_attribute_mismatch_count": len(visible_mismatches),
            "visible_attribute_first_mismatch": (
                visible_mismatches[0] if visible_mismatches else None
            ),
        }

        assert candidate.logical_state == baseline.logical_state, name
        assert candidate.renderer_state == (0, 0), name
        assert baseline.renderer_preference == 1, name
        assert candidate.renderer_preference == 0, name
        assert baseline.passive_state[:3] == (0, 0, 0), name
        assert candidate.passive_state == (
            1,
            0,
            0,
            candidate.renderer_generation[0],
        ), name
        assert candidate.bg_palettes == expected_palettes, name
        assert not visible_mismatches, name
        _assert_visible_bg_parity(candidate, baseline, name)
        _assert_oam_semantics(candidate, baseline, name)

    assert color.before_reset.logical_state == (PALLET_TOWN, 10, 7, 1, 22, 0)
    assert color.restored.logical_state == color.before_reset.logical_state
    assert color.playable.logical_state == color.before_reset.logical_state
    assert color.before_reset.renderer_generation != color.restored.renderer_generation
    assert color.restored.renderer_generation == color.playable.renderer_generation
    (results / "paired-save-continue-diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
