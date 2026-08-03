"""Cold-boot parity coverage for the first full-color overworld slice."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import cast

from PIL import Image

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import complete_oaks_lab_intro
from tools.rom_tests.scenarios.viridian_city import (
    VIRIDIAN_CITY,
    reach_viridian_city,
    walk_from_oaks_lab_to_viridian,
    walk_to_value,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RESULTS_ROOT = REPOSITORY_ROOT / "test-results" / "full-color-cold-boot"

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
COLOR_CHECKPOINTS = frozenset(
    {
        "pallet-before-oak",
        "oak-interception",
        "post-lab-pallet",
        "route1-south",
        "route1-mid",
        "route1-north",
    }
)


@dataclass(frozen=True)
class JourneyObservation:
    frame: int
    logical_state: tuple[int, ...]
    rng_state: tuple[int, int]
    renderer_state: tuple[int, int]
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
) -> dict[str, BoundaryObservation]:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    observations: dict[str, BoundaryObservation] = {}

    def observe(name: str) -> None:
        observations[name] = _observe_boundary(
            emulator,
            f"{product}-{name}.png",
        )

    try:
        complete_oaks_lab_intro(emulator)

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
        emulator.save_screenshot(f"{product}-boundary-failure.png")
        raise
    finally:
        emulator.close()

    return observations


def _run_journey(
    product: str,
    results: Path,
    *,
    use_debug_repel: bool,
) -> dict[str, JourneyObservation]:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )
    observations: dict[str, JourneyObservation] = {}

    def checkpoint(name: str, current: Emulator) -> None:
        observations[name] = _observe(current, f"{product}-{name}.png")

    try:
        reach_viridian_city(
            emulator,
            checkpoint,
            use_debug_repel=use_debug_repel,
        )
    except BaseException:
        emulator.save_screenshot(f"{product}-journey-failure.png")
        failure_state = {
            "frame": emulator.frame,
            "map": emulator.read("wCurMap"),
            "y": emulator.read("wYCoord"),
            "x": emulator.read("wXCoord"),
            "party_count": emulator.read("wPartyCount"),
            "oak_script": emulator.read("wOaksLabCurScript"),
            "in_battle": emulator.read("wIsInBattle"),
        }
        (results / f"{product}-journey-failure.json").write_text(
            json.dumps(failure_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    assert tuple(observations) == CHECKPOINTS
    (results / f"{product}-journey-state.json").write_text(
        json.dumps(
            {
                name: {
                    "frame": observation.frame,
                    "logical_state": observation.logical_state,
                    "passive_state": observation.passive_state,
                    "lcdc": observation.lcdc,
                    "renderer_state": observation.renderer_state,
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


def _run_route1_wild_battle_round_trip(
    product: str,
    results: Path,
) -> WildBattleRoundTrip:
    emulator = Emulator(
        rom=REPOSITORY_ROOT / f"{product}.gbc",
        symbols=REPOSITORY_ROOT / f"{product}.sym",
        results=results,
        cgb=True,
    )

    def press_until_value(
        symbol: str,
        value: int,
        button: str,
        description: str,
        *,
        max_presses: int = 160,
    ) -> bool:
        for _ in range(max_presses):
            if emulator.is_in_battle():
                return True
            if emulator.read(symbol) == value:
                return False
            emulator.press(button)
        raise AssertionError(f"Timed out walking to {description}")

    try:
        complete_oaks_lab_intro(emulator)

        # Follow the real south-to-north route without suppressing encounters.
        # Once at the first clearing, pace on traversable Route 1 tiles until
        # Yellow's own random encounter machinery starts a battle.
        for symbol, value, button, description in (
            ("wXCoord", 8, "left", "west side of Oak's Lab"),
            ("wYCoord", 2, "up", "north Pallet Town"),
            ("wXCoord", 10, "right", "Route 1 entrance"),
            ("wCurMap", 0x0C, "up", "Route 1"),
            ("wYCoord", 30, "up", "south Route 1 clearing"),
        ):
            if press_until_value(symbol, value, button, description):
                break

        for _ in range(80):
            if emulator.is_in_battle():
                break
            emulator.press("down" if emulator.read("wYCoord") <= 30 else "up")
        assert emulator.is_in_battle(), "no natural wild encounter after 80 grass steps"

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
        battle_menu = _observe(emulator, f"{product}-wild-battle-menu.png")
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
        emulator.tick(120)
        restored_route = _observe(emulator, f"{product}-route1-restored.png")
    except BaseException:
        emulator.save_screenshot(f"{product}-wild-battle-failure.png")
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
        }
        (results / f"{product}-wild-battle-failure.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        emulator.close()

    return WildBattleRoundTrip(battle_menu, battle_state, restored_route)


def _linked_bytes(product: str, symbol: str, size: int) -> bytes:
    symbols = (
        (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines()
    )
    addresses = Emulator._parse_symbols(symbols)
    banks = Emulator._parse_symbol_banks(symbols)
    address = addresses[symbol]
    offset = banks[symbol] * 0x4000 + (address & 0x3FFF)
    return (REPOSITORY_ROOT / f"{product}.gbc").read_bytes()[offset : offset + size]


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


def test_stock_debug_cold_boot_reaches_viridian_without_state_injection() -> None:
    _prepare_results(RESULTS_ROOT / "stock-natural")
    observations = _run_journey(
        "pokeyellow_debug",
        RESULTS_ROOT / "stock-natural",
        use_debug_repel=False,
    )

    assert observations["bedroom"].logical_state[:3] == (0x26, 6, 3)
    assert observations["viridian-entry"].logical_state[:3] == (0x01, 35, 20)
    assert observations["viridian-entry"].logical_state[3] == 1


def test_audit_cold_boot_changes_only_color_state_in_the_slice() -> None:
    results = RESULTS_ROOT / "paired-audit"
    _prepare_results(results)
    vanilla = _run_journey(
        "pokeyellow_debug",
        results,
        use_debug_repel=True,
    )
    audit = _run_journey(
        "pokeyellow_phase2_audit",
        results,
        use_debug_repel=True,
    )

    expected_palettes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldBGPalettes", 64
    )
    expected_attributes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldTileAttributes", 256
    )
    diagnostics = {}
    for name in CHECKPOINTS:
        baseline = vanilla[name]
        candidate = audit[name]
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

    color_difference_seen = False
    for name in CHECKPOINTS:
        baseline = vanilla[name]
        candidate = audit[name]
        assert candidate.logical_state == baseline.logical_state, name
        assert candidate.renderer_state == (0, 0), name
        _assert_visible_bg_parity(candidate, baseline, name)

        if name in COLOR_CHECKPOINTS:
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
        else:
            assert candidate.passive_state[:3] == (0, 0, 0), name
            assert candidate.attributes == baseline.attributes, name
            if name == "viridian-entry":
                # Cleanup makes every visible attribute select palette 0; the
                # other seven slots are inert and may remain homogenized.
                assert candidate.bg_palettes[:8] == baseline.bg_palettes[:8], name
            else:
                assert candidate.bg_palettes == baseline.bg_palettes, name
            assert candidate.screen.tobytes() == baseline.screen.tobytes(), name

        _assert_oam_semantics(candidate, baseline, name)

    assert color_difference_seen, "audit ROM never exposed the guarded color slice"


def test_pallet_dialogue_party_round_trip_preserves_yellow_and_color_state() -> None:
    results = RESULTS_ROOT / "pallet-ui-boundary"
    _prepare_results(results)
    vanilla = _run_pallet_ui_boundary("pokeyellow_debug", results)
    audit = _run_pallet_ui_boundary("pokeyellow_phase2_audit", results)

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
    assert tuple(vanilla) == expected_names
    assert tuple(audit) == expected_names

    expected_palettes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldBGPalettes", 64
    )
    expected_attributes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldTileAttributes", 256
    )
    expected_free_descriptors = b"".join(bytes((0xF0,)) + bytes(19) for _ in range(8))
    expected_dormant_scheduler: tuple[object, ...] = (
        0xFF,
        expected_free_descriptors,
        bytes(160),
        0,
        0,
        bytes((0x3F, 0)),
        bytes((0xFF, 0xFF)),
        0,
        0,
        0,
        bytes(8),
        bytes(2),
    )

    initial_generation = audit["stable-overworld"].journey.renderer_generation
    for name in expected_names:
        baseline = vanilla[name]
        candidate = audit[name]
        assert candidate.journey.logical_state == baseline.journey.logical_state, name
        assert candidate.menu_state == baseline.menu_state, name
        assert candidate.input_state == baseline.input_state, name
        assert candidate.journey.renderer_state == (0, 0), name
        assert candidate.journey.renderer_generation == initial_generation, name
        assert candidate.scheduler_state == expected_dormant_scheduler, name
        _assert_visible_bg_parity(candidate.journey, baseline.journey, name)
        _assert_oam_semantics(candidate.journey, baseline.journey, name)

    stable = audit["stable-overworld"].journey
    restored = audit["restored-overworld"].journey
    assert stable.logical_state == (0, 10, 7, 1, 22, 0)
    assert restored.logical_state == stable.logical_state
    assert audit["stable-overworld"].input_state == (0, 0, 0)
    assert audit["restored-overworld"].input_state == (0, 0, 0)

    assert audit["start-menu"].menu_state[:3] == (0, 6, 0xCB)
    assert audit["party"].menu_state[:5] == (0, 0, 0x03, 2, 0)
    assert audit["returned-start-menu"].menu_state[:3] == (0, 6, 0xCB)

    assert stable.passive_state == (1, 0, 0, initial_generation[0])
    assert restored.passive_state == stable.passive_state
    assert stable.bg_palettes == expected_palettes
    assert restored.bg_palettes == expected_palettes
    boundary_diagnostics = {}
    for name in (
        "stable-overworld",
        "dialogue-restored",
        "direct-start-restored",
        "restored-overworld",
    ):
        mismatches = [
            {
                "row": visible_index // 20,
                "column": visible_index % 20,
                "tile": tile,
                "actual": attribute,
                "expected": expected_attributes[tile],
            }
            for visible_index, (tile, attribute) in enumerate(
                _visible_attribute_pairs(audit[name].journey)
            )
            if attribute != expected_attributes[tile]
        ]
        boundary_diagnostics[name] = {
            "visible_mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }
    (results / "boundary-attribute-diagnostics.json").write_text(
        json.dumps(boundary_diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert not boundary_diagnostics["dialogue-restored"]["mismatches"]
    assert not boundary_diagnostics["direct-start-restored"]["mismatches"]
    assert not boundary_diagnostics["restored-overworld"]["mismatches"]
    _assert_visible_bg_parity(restored, stable, "restored-overworld")

    assert audit["viridian-entry"].journey.logical_state[:4] == (
        VIRIDIAN_CITY,
        35,
        20,
        1,
    )


def test_route1_wild_battle_round_trip_restores_passive_color_slice() -> None:
    results = RESULTS_ROOT / "route1-wild-battle"
    _prepare_results(results)
    vanilla = _run_route1_wild_battle_round_trip("pokeyellow_debug", results)
    audit = _run_route1_wild_battle_round_trip("pokeyellow_phase2_audit", results)

    expected_palettes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldBGPalettes", 64
    )
    expected_attributes = _linked_bytes(
        "pokeyellow_phase2_audit", "FullColorOverworldTileAttributes", 256
    )

    battle = audit.battle_menu
    baseline_battle = vanilla.battle_menu
    assert audit.battle_state[0] == vanilla.battle_state[0] == 0
    assert audit.battle_state[1] != 0 and vanilla.battle_state[1] != 0
    assert audit.battle_state[2] != 0 and vanilla.battle_state[2] != 0
    assert audit.battle_state[3:] == vanilla.battle_state[3:]
    assert battle.logical_state[0] == baseline_battle.logical_state[0] == 0x0C
    assert battle.logical_state[2:5] == baseline_battle.logical_state[2:5]
    assert battle.logical_state[-1] == baseline_battle.logical_state[-1] == 1
    # Battle setup owns the screen while the guarded Route 1 context remains
    # active for the eventual return. No pending passive write may survive.
    assert battle.passive_state[1:3] == (0, 0)
    assert battle.renderer_state == (0, 0)
    # Wild species and levels legitimately follow DIV cadence, so the enemy
    # name and picture can differ. The stable player HUD and battle command UI
    # must remain exact Yellow pixels, and no passive CGB color may leak in.
    assert battle.screen.crop((0, 80, 160, 144)).tobytes() == (
        baseline_battle.screen.crop((0, 80, 160, 144)).tobytes()
    )
    assert bytes(
        battle.attributes[index] for index in _visible_indices(battle)
    ) == bytes(
        baseline_battle.attributes[index] for index in _visible_indices(baseline_battle)
    )
    assert battle.bg_palettes[:8] == baseline_battle.bg_palettes[:8]
    assert battle.hardware_oam == baseline_battle.hardware_oam
    assert battle.shadow_oam == baseline_battle.shadow_oam

    restored = audit.restored_route
    baseline_restored = vanilla.restored_route
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
    _assert_visible_bg_parity(restored, baseline_restored, "post-wild-battle-route1")
    _assert_oam_semantics(restored, baseline_restored, "post-wild-battle-route1")
    assert restored.bg_palettes == expected_palettes
    for tile, attribute in _visible_attribute_pairs(restored):
        assert attribute == expected_attributes[tile]
