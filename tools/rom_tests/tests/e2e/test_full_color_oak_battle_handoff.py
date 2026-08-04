"""Natural framewise proof of the Pallet-to-battle Color handoff."""

from __future__ import annotations

from pathlib import Path

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.scenarios.new_game import reach_bedroom_overworld
from tools.rom_tests.scenarios.oaks_lab import walk_from_bedroom_to_oak
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


SCRIPT_PALLETTOWN_PIKACHU_BATTLE = 4
BATTLE_TYPE_PIKACHU = 4
VBG_MAP_0 = 0x9800
VBG_MAP_1 = 0x9C00
TILEMAP_AREA = 0x400
RLCDC = 0xFF40


def _linked_bytes(symbol: str, size: int) -> bytes:
    symbols = REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"
    lines = symbols.read_text(encoding="utf-8").splitlines()
    addresses = Emulator._parse_symbols(lines)
    banks = Emulator._parse_symbol_banks(lines)
    address = addresses[symbol]
    offset = banks[symbol] * 0x4000 + (address & 0x3FFF)
    rom = REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"
    return rom.read_bytes()[offset : offset + size]


def test_oak_battle_relinquishes_color_before_transition() -> None:
    results = result_directory(
        "test_full_color_oak_battle_handoff.py::oak-battle-handoff"
    )
    emulator = Emulator(
        rom=Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"),
        symbols=Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"),
        results=results,
        cgb=True,
    )
    donor_palettes = _linked_bytes("FullColorOverworldBGPalettes", 64)
    donor_attributes = _linked_bytes("FullColorOverworldTileAttributes", 256)
    empty_attributes = bytes(TILEMAP_AREA)
    handoff_seen = False

    def advance_framewise_to_script() -> None:
        for _ in range(30):
            if (
                emulator.read("wPalletTownCurScript")
                == SCRIPT_PALLETTOWN_PIKACHU_BATTLE
            ):
                return
            emulator.pyboy.button("a", delay=2)
            for _ in range(120):
                emulator.tick()
                if (
                    emulator.read("wPalletTownCurScript")
                    == SCRIPT_PALLETTOWN_PIKACHU_BATTLE
                ):
                    return
        raise AssertionError("timed out waiting for Oak facing the wild Pikachu")

    def assert_frame(frame: int) -> None:
        nonlocal handoff_seen
        active = emulator.read("wPassiveFullColorActive")
        assert emulator.pyboy.memory[RLCDC] & 0x80, (frame, "LCD disabled")
        if active:
            assert emulator.read_palette_ram() == donor_palettes, (
                frame,
                "active donor attributes with a non-donor palette",
            )
            return

        if not handoff_seen:
            emulator.save_screenshot("oak-battle-handoff.png")
            handoff_seen = True
        palette_is_donor = emulator.read_palette_ram() == donor_palettes
        for address in (VBG_MAP_0, VBG_MAP_1):
            tiles = emulator.read_vram_bank(0, address, TILEMAP_AREA)
            attributes = emulator.read_vram_bank(1, address, TILEMAP_AREA)
            assert all(
                attribute in {0, donor_attributes[tile]}
                for tile, attribute in zip(tiles, attributes)
            ), (frame, hex(address), "neither stock nor donor-compatible")
            if not palette_is_donor:
                assert attributes == empty_attributes, (
                    frame,
                    hex(address),
                    "stale donor attributes under a non-donor palette",
                )

    try:
        reach_bedroom_overworld(emulator)
        walk_from_bedroom_to_oak(emulator)
        advance_framewise_to_script()
        assert emulator.read("wPassiveFullColorActive") == 1
        assert_frame(emulator.frame)

        battle_established = False
        for _ in range(8):
            emulator.pyboy.button("a", delay=2)
            for _ in range(120):
                emulator.tick()
                assert_frame(emulator.frame)
                if (
                    emulator.read("wBattleType") == BATTLE_TYPE_PIKACHU
                    and emulator.is_in_battle()
                ):
                    battle_established = True
                    break
            if battle_established:
                break

        assert battle_established, "Oak's Pikachu battle was not established"
        assert handoff_seen, "passive Color remained active into battle setup"
        assert emulator.read_vram_bank(1, VBG_MAP_0, TILEMAP_AREA) == empty_attributes
        assert emulator.read_vram_bank(1, VBG_MAP_1, TILEMAP_AREA) == empty_attributes
        emulator.save_screenshot("oak-battle-established.png")
    except BaseException:
        emulator.save_screenshot("oak-battle-handoff-failure.png")
        raise
    finally:
        emulator.close()
