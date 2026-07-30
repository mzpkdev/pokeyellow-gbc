"""Integration coverage for the complete opening Oak's Lab sequence."""

from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.oaks_lab import (
    OAKS_LAB,
    PALLET_TOWN,
    PIKACHU,
    SCRIPT_OAKSLAB_NOOP,
    complete_oaks_lab_intro,
)


SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots"

EVENT_BEAT_BROCK = 0x77
EVENT_BEAT_LT_SURGE = 0x167
EVENT_RESCUED_MR_FUJI = 0x4CF
EVENT_LOST_TO_LT_SURGE_WITH_STARTER_PIKACHU = 0x8D5
PIKACOMPANION_REACTION_GIFT_READY = 5
PIKACOMPANION_REACTION_AMBIENT_FIND = 6
PIKACOMPANION_REACTION_PORTRAIT_READY = 7
PIKACHU_PENDING_EMOTION_ALERTED = 0x80
QUESTION_BUBBLE = 1
SMILE_BUBBLE = 2
POTION = 0x14
ESCAPE_ROPE = 0x1D
THUNDER_STONE = 0x21
RAICHU = 0x55
LIGHT_BALL_GSC = 0xA3


def _set_event(emulator: Emulator, event: int) -> None:
    address = emulator.symbols["wEventFlags"] + event // 8
    emulator.pyboy.memory[address] |= 1 << (event % 8)


def _clear_event(emulator: Emulator, event: int) -> None:
    address = emulator.symbols["wEventFlags"] + event // 8
    emulator.pyboy.memory[address] &= ~(1 << (event % 8))


def _take_step(emulator: Emulator, button: str, description: str) -> None:
    coordinate = "wXCoord" if button in ("left", "right") else "wYCoord"
    start = emulator.read(coordinate)
    for _ in range(3):
        emulator.pyboy.button(button, delay=2)
        for _ in range(120):
            emulator.tick()
            if emulator.read(coordinate) != start:
                return
    raise AssertionError(f"Timed out waiting for {description}")


def _give_one_thunder_stone(emulator: Emulator) -> None:
    bag = emulator.symbols["wBagItems"]
    emulator.write("wNumBagItems", 1)
    emulator.pyboy.memory[bag] = THUNDER_STONE
    emulator.pyboy.memory[bag + 1] = 1
    emulator.pyboy.memory[bag + 2] = 0xFF


def _use_thunder_stone_on_pikachu(emulator: Emulator) -> None:
    emulator.press("start")
    emulator.press("down", wait_frames=20)
    emulator.press("a")
    emulator.press("a", wait_frames=80)
    emulator.press("a")
    emulator.press("a")


def _advance_to_evolution_confirmation(emulator: Emulator) -> None:
    emulator.advance_until(
        lambda: (
            emulator.read("wTopMenuItemY") == 8
            and emulator.read("wMaxMenuItem") == 1
        ),
        button="a",
        max_presses=16,
        description="starter evolution confirmation",
    )


def test_receive_pikachu_battle_rival_and_leave_lab(emulator: Emulator) -> None:
    complete_oaks_lab_intro(emulator)

    assert emulator.read("wPartyCount") == 1
    assert emulator.read("wPartySpecies") == PIKACHU
    assert emulator.read("wStarterPikachuParticipatedInBattle") == 1
    assert emulator.read("wPartyMon1CatchRate") == LIGHT_BALL_GSC
    assert emulator.read("wStarterCompanionDVs") == emulator.read("wPartyMon1DVs")
    assert (
        emulator.pyboy.memory[emulator.symbols["wStarterCompanionDVs"] + 1]
        == emulator.pyboy.memory[emulator.symbols["wPartyMon1DVs"] + 1]
    )
    assert emulator.read("wOaksLabCurScript") == SCRIPT_OAKSLAB_NOOP
    assert not emulator.is_in_battle()
    assert emulator.read("wCurMap") == PALLET_TOWN
    assert emulator.read("wCurMap") != OAKS_LAB
    assert (emulator.read("wYCoord"), emulator.read("wXCoord")) == (12, 12)
    emulator.assert_screen_matches(
        SNAPSHOTS / "oaks-lab-exit.png",
        name="oaks-lab-exit-upper",
        crop=(0, 0, 160, 80),
    )


def test_companion_fingerprint_requires_marker_and_matching_dvs(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    saved_dv = emulator.read("wPartyMon1DVs")
    emulator.write("wPikachuHappiness", 30)
    emulator.write("wPikachuCompanionStepCounter", 0xFF)
    emulator.write("wPartyMon1CatchRate", 190)

    _take_step(emulator, "left", "non-companion marker step")
    assert emulator.read("wPikachuCompanionStepCounter") == 0xFF
    assert emulator.read("wPikachuHappiness") == 30

    emulator.write("wPartyMon1CatchRate", LIGHT_BALL_GSC)
    emulator.write("wPartyMon1DVs", saved_dv ^ 0x01)
    _take_step(emulator, "right", "non-companion DV step")
    assert emulator.read("wPikachuCompanionStepCounter") == 0xFF
    assert emulator.read("wPikachuHappiness") == 30

    emulator.write("wPartyMon1DVs", saved_dv)
    second_dv = emulator.symbols["wPartyMon1DVs"] + 1
    emulator.pyboy.memory[second_dv] ^= 0x01
    _take_step(emulator, "left", "non-companion second DV step")
    assert emulator.read("wPikachuCompanionStepCounter") == 0xFF
    assert emulator.read("wPikachuHappiness") == 30

    emulator.pyboy.memory[second_dv] ^= 0x01
    _take_step(emulator, "left", "restored companion fingerprint step")
    assert emulator.read("wPikachuCompanionStepCounter") == 0
    assert emulator.read("wPikachuHappiness") == 32


def test_eligible_starter_evolution_can_be_declined_without_using_stone(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    _give_one_thunder_stone(emulator)
    emulator.write("wPikachuHappiness", 200)
    _set_event(emulator, EVENT_LOST_TO_LT_SURGE_WITH_STARTER_PIKACHU)

    _use_thunder_stone_on_pikachu(emulator)
    _advance_to_evolution_confirmation(emulator)
    emulator.press("down", wait_frames=20)
    emulator.press("a")

    assert emulator.read("wPartySpecies") == PIKACHU
    assert emulator.read("wEvolutionOccurred") == 0
    assert emulator.bag_contains(THUNDER_STONE)


def test_story_trigger_still_refuses_below_happiness_requirement(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    _give_one_thunder_stone(emulator)
    emulator.write("wPikachuHappiness", 199)
    _set_event(emulator, EVENT_RESCUED_MR_FUJI)

    _use_thunder_stone_on_pikachu(emulator)
    emulator.advance_until(
        lambda: (emulator.read("wd49c") & 0x7F) == 4,
        button="a",
        max_presses=4,
        description="starter evolution refusal",
    )

    assert emulator.read("wPartySpecies") == PIKACHU
    assert emulator.read("wEvolutionOccurred") == 0
    assert emulator.bag_contains(THUNDER_STONE)


def test_pending_portrait_uses_idle_prompt_without_consuming_it(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wJoyIgnore", 0)
    emulator.write("wStatusFlags5", 0)
    emulator.write("wd49c", 1)

    emulator.tick(3)

    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_PORTRAIT_READY
    )
    assert emulator.read("wd49c") == 1

    emulator.write("wPikachuCompanionIdleCounter", 59)
    emulator.tick(180)

    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wd49c") == (
        PIKACHU_PENDING_EMOTION_ALERTED | 1
    )


def test_pending_portrait_alert_waits_behind_high_priority_reaction(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wJoyIgnore", 0)
    emulator.write("wStatusFlags5", 0)
    emulator.write("wd49c", 2)
    emulator.write(
        "wPikachuCompanionQueuedReaction",
        PIKACOMPANION_REACTION_GIFT_READY,
    )

    emulator.tick(3)

    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_GIFT_READY
    )
    assert emulator.read("wd49c") == 2


def test_fuji_route_evolves_starter_and_recalls_unsupported_raichu(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    _give_one_thunder_stone(emulator)
    emulator.write("wPikachuHappiness", 200)
    _set_event(emulator, EVENT_RESCUED_MR_FUJI)

    _use_thunder_stone_on_pikachu(emulator)
    _advance_to_evolution_confirmation(emulator)
    emulator.press("a")
    emulator.advance_until(
        lambda: (
            emulator.read("wPartySpecies") == RAICHU
            and emulator.read("wNumBagItems") == 0
        ),
        button="a",
        max_presses=40,
        description="starter Raichu evolution",
    )

    companion_flags = emulator.read("wPikachuOverworldStateFlags")
    assert companion_flags & (1 << 1)  # following disabled
    assert companion_flags & (1 << 3)  # sprite drawing disabled
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0


def test_companion_step_rollover_updates_happiness_and_mood(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wPikachuHappiness", 49)
    emulator.write("wPikachuMood", 127)
    emulator.write("wPikachuCompanionStepCounter", 0xFF)
    emulator.write("wPikachuCompanionQueuedReaction", 0)
    emulator.write("wWalkBikeSurfState", 0)
    emulator.write("wStatusFlags5", emulator.read("wStatusFlags5") & 0x7F)

    start_x = emulator.read("wXCoord")
    emulator.advance_until(
        lambda: emulator.read("wXCoord") < start_x,
        button="left",
        max_presses=3,
        description="companion test step",
    )

    assert emulator.read("wPikachuCompanionStepCounter") == 0
    assert emulator.read("wPikachuHappiness") == 51
    assert emulator.read("wPikachuMood") == 128
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0

    emulator.write("wWalkBikeSurfState", 1)
    emulator.advance_until(
        lambda: emulator.read("wXCoord") == start_x,
        button="right",
        max_presses=3,
        description="companion bicycle test step",
    )

    assert emulator.read("wPikachuCompanionStepCounter") == 0


def test_gift_cooldown_counts_only_eligible_steps(emulator: Emulator) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wPikachuHappiness", 80)
    _set_event(emulator, EVENT_BEAT_BROCK)
    emulator.write("wPikachuGiftCooldown", 128)
    emulator.write("wPikachuCompanionStepCounter", 1)
    emulator.write("wWalkBikeSurfState", 0)

    _take_step(emulator, "left", "gift cooldown walking step")
    assert emulator.read("wPikachuGiftCooldown") == 127
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0

    emulator.write("wWalkBikeSurfState", 1)
    _take_step(emulator, "right", "gift cooldown bicycle step")
    assert emulator.read("wPikachuGiftCooldown") == 127
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0

    emulator.write("wWalkBikeSurfState", 0)
    emulator.write("wPikachuGiftCooldown", 1)
    _take_step(emulator, "left", "gift cooldown final walking step")
    assert emulator.read("wPikachuGiftCooldown") == 0
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_GIFT_READY
    )


def test_ordered_gift_eligibility_and_alert_priority(emulator: Emulator) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wPikachuHappiness", 79)
    emulator.write("wPikachuCompanionStepCounter", 1)
    emulator.write("wPikachuNextGift", 0)
    emulator.write("wPikachuAmbientItem", POTION)
    emulator.write(
        "wPikachuCompanionQueuedReaction",
        PIKACOMPANION_REACTION_AMBIENT_FIND,
    )
    _set_event(emulator, EVENT_BEAT_LT_SURGE)
    _clear_event(emulator, EVENT_BEAT_BROCK)

    _take_step(emulator, "left", "blocked first gift step")
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_AMBIENT_FIND
    )

    _set_event(emulator, EVENT_BEAT_BROCK)
    _take_step(emulator, "right", "first gift below happiness threshold")
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_AMBIENT_FIND
    )

    emulator.write("wPikachuHappiness", 80)
    emulator.write(
        "wPikachuCompanionQueuedReaction",
        PIKACOMPANION_REACTION_PORTRAIT_READY,
    )
    _take_step(emulator, "left", "eligible first gift step")
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_GIFT_READY
    )

    emulator.write("wPikachuCompanionQueuedReaction", 0)
    emulator.write("wPikachuNextGift", 1)
    emulator.write("wPikachuHappiness", 130)
    _take_step(emulator, "right", "eligible second gift step")
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_GIFT_READY
    )


def test_talking_to_pikachu_delivers_gift_after_complete_dialogue(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wPikachuHappiness", 80)
    emulator.write("wPikachuGiftCooldown", 0)
    emulator.write("wPikachuNextGift", 0)
    _set_event(emulator, EVENT_BEAT_BROCK)

    # Pikachu is directly above the player after the opening scenario.
    emulator.write("wSpritePlayerStateData1FacingDirection", 4)
    emulator.advance_until(
        lambda: emulator.read("wPikachuNextGift") == 1,
        button="a",
        max_presses=16,
        description="first Pikachu gift dialogue",
    )

    assert emulator.read("wWhichEmotionBubble") == SMILE_BUBBLE
    assert emulator.bag_contains(ESCAPE_ROPE)
    assert emulator.read("wPikachuGiftCooldown") == 128
    assert emulator.read("wPikachuGiftAlerted") == 0


def test_talking_to_pikachu_delivers_ambient_find_after_complete_dialogue(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wPikachuAmbientItem", POTION)
    emulator.write("wPikachuAmbientAlerted", 1)

    # Pikachu is directly above the player after the opening scenario.
    emulator.write("wSpritePlayerStateData1FacingDirection", 4)
    emulator.advance_until(
        lambda: emulator.read("wPikachuAmbientItem") == 0,
        button="a",
        max_presses=16,
        description="Pikachu ambient-find dialogue",
    )

    assert emulator.read("wWhichEmotionBubble") == SMILE_BUBBLE
    assert emulator.bag_contains(POTION)
    assert emulator.read("wPikachuAmbientAlerted") == 0


def test_queued_companion_reaction_waits_for_idle(emulator: Emulator) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wJoyIgnore", 0)
    emulator.write("wStatusFlags5", 0)
    emulator.write("wPikachuCompanionQueuedReaction", 2)
    emulator.write("wPikachuCompanionIdleCounter", 30)

    emulator.pyboy.button("b", delay=2)
    emulator.tick(3)

    assert emulator.read("wPikachuCompanionQueuedReaction") == 2
    assert emulator.read("wPikachuCompanionIdleCounter") == 0

    emulator.write("wPikachuCompanionIdleCounter", 59)
    emulator.tick(180)

    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wPikachuCompanionIdleCounter") == 0

    emulator.write("wPikachuCompanionQueuedReaction", 4)
    emulator.write("wPikachuCompanionIdleCounter", 59)
    emulator.tick(300)

    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wPikachuCompanionIdleCounter") == 0


def test_gift_and_ambient_alerts_wait_for_idle_and_mark_announced(
    emulator: Emulator,
) -> None:
    complete_oaks_lab_intro(emulator)
    emulator.write("wJoyIgnore", 0)
    emulator.write("wStatusFlags5", 0)

    emulator.write(
        "wPikachuCompanionQueuedReaction",
        PIKACOMPANION_REACTION_GIFT_READY,
    )
    emulator.write("wPikachuCompanionIdleCounter", 30)
    emulator.pyboy.button("b", delay=2)
    emulator.tick(3)
    assert (
        emulator.read("wPikachuCompanionQueuedReaction")
        == PIKACOMPANION_REACTION_GIFT_READY
    )
    assert emulator.read("wPikachuCompanionIdleCounter") == 0
    assert emulator.read("wPikachuGiftAlerted") == 0

    emulator.write("wPikachuCompanionIdleCounter", 59)
    emulator.tick(180)
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wPikachuCompanionIdleCounter") == 0
    assert emulator.read("wPikachuGiftAlerted") == 1
    assert emulator.read("wWhichEmotionBubble") == QUESTION_BUBBLE

    emulator.write(
        "wPikachuCompanionQueuedReaction",
        PIKACOMPANION_REACTION_AMBIENT_FIND,
    )
    emulator.write("wPikachuCompanionIdleCounter", 59)
    emulator.tick(180)
    assert emulator.read("wPikachuCompanionQueuedReaction") == 0
    assert emulator.read("wPikachuCompanionIdleCounter") == 0
    assert emulator.read("wPikachuAmbientAlerted") == 1
    assert emulator.read("wWhichEmotionBubble") == QUESTION_BUBBLE
