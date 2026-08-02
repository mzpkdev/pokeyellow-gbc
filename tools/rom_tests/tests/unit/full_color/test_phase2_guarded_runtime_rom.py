"""Real-ROM contract tests for the guarded Phase 2 hostile lifecycle.

These tests deliberately enter only exported production seams in the audit
ROM.  They complement the class-level scheduler tests by proving that the
guarded lifecycle composes ownership, immutable requests and presentation in
the required order.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    _farcall_from_wram,
    phase2_rom,
)


def _set_wram1_word(rom: Phase2Rom, symbol: str, value: int) -> None:
    emu = rom.emulator.pyboy
    previous = emu.memory[0xFF70]
    emu.memory[0xFF70] = 1
    try:
        address = rom.emulator.symbols[symbol]
        emu.memory[address] = value & 0xFF
        emu.memory[address + 1] = value >> 8
    finally:
        emu.memory[0xFF70] = previous


def _rom_bytes(rom_path: Path, rom: Phase2Rom, start: str, end: str) -> bytes:
    bank = rom.emulator.symbol_banks[start]
    assert bank == rom.emulator.symbol_banks[end]
    address = rom.emulator.symbols[start]
    size = rom.emulator.symbols[end] - address
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom_path.read_bytes()[offset:offset + size]


def _assert_reconstructed_visible_state(
    rom: Phase2Rom, tiles: bytes, *, destination: int = 0x9800,
) -> None:
    for row in range(18):
        start = row * 20
        address = destination + row * 32
        assert rom.emulator.read_vram_bank(0, address, 20) == tiles[start:start + 20]
        assert rom.emulator.read_vram_bank(1, address, 20) == bytes(
            tile & 7 for tile in tiles[start:start + 20]
        )


def test_guarded_map_handoff_snapshots_authority_and_poisons_yellow_requests(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    # Begin from the real Yellow lifecycle, not the fixture's convenient active
    # full-color state, and make every legacy visible request observably armed.
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wCurMap"]] = 0
    emu.memory[phase2_rom.emulator.symbols["wCurMapTileset"]] = 0
    emu.memory[phase2_rom.emulator.symbols["wYCoord"]] = 7
    emu.memory[phase2_rom.emulator.symbols["wXCoord"]] = 11
    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9820)
    for symbol in (
        "hAutoBGTransferEnabled", "hVBlankCopyBGSource",
        "hVBlankCopyBGNumRows", "hVBlankCopySize",
        "hVBlankCopyDoubleSize", "hRedrawRowOrColumnMode",
    ):
        emu.memory[phase2_rom.emulator.symbols[symbol]] = 0xA5
    emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] = 1

    generation_before = phase2_rom.generation
    _, flags = _farcall_from_wram(
        phase2_rom, "BeginFullColorMapEntry", entry_bank=7,
    )

    assert flags & 0x10 == 0
    assert phase2_rom.generation == generation_before + 1
    assert phase2_rom.read_wram2("wRendererOwner") == bytes((
        phase2_rom.constants["RENDERER_FULL_COLOR_OVERWORLD"],
    ))
    assert phase2_rom.read_wram2("wRendererPhase") == bytes((
        phase2_rom.constants["OVERWORLD_RECONSTRUCTING"],
    ))
    assert phase2_rom.read_wram2("wRendererAdmissionOpen") == b"\0"
    assert phase2_rom.read_wram2("wFullColorAuthoritySnapshot", 8)[:4] == bytes((0, 0, 7, 11))
    assert phase2_rom.read_wram2("wFullColorAuthorityVRAMView", 2) == b"\x20\x98"
    for symbol in (
        "hAutoBGTransferEnabled", "hVBlankCopyBGSource",
        "hVBlankCopyBGNumRows", "hVBlankCopySize",
        "hVBlankCopyDoubleSize", "hRedrawRowOrColumnMode",
    ):
        assert emu.memory[phase2_rom.emulator.symbols[symbol]] == 0
    assert emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] == 0


def test_reconstruction_loads_font_palette_and_paired_map_before_one_barrier(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    rom_path = Path(REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc")
    tiles = bytes((index * 13 + 5) & 0xFF for index in range(20 * 18))
    phase2_rom.write_fixed(phase2_rom.emulator.symbols["wTileMap"], tiles)
    phase2_rom.call("InitRendererOwnership")
    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9800)
    assert _farcall_from_wram(
        phase2_rom, "BeginFullColorMapEntry", entry_bank=4,
    )[1] & 0x10 == 0

    font_address = phase2_rom.emulator.symbols["vFont"]
    font_source = _rom_bytes(
        rom_path, phase2_rom, "FontGraphics", "FontGraphicsEnd",
    )
    expected_font = b"".join(bytes((value, value)) for value in font_source)
    for offset in range(len(expected_font)):
        emu.memory[font_address + offset] = 0xE5
    emu.memory[0xFF40] &= 0x7F
    barrier_before = phase2_rom.read_wram2("wFullColorDebugReconstructionState")[0]

    _, flags = _farcall_from_wram(
        phase2_rom, "CompleteFullColorMapReconstruction", entry_bank=7,
    )

    assert flags & 0x10 == 0
    assert phase2_rom.read_wram2("wRendererPhase") == bytes((
        phase2_rom.constants["OVERWORLD_ACTIVE"],
    ))
    assert phase2_rom.read_wram2("wRendererAdmissionOpen") == b"\x01"
    assert emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] == 1
    assert phase2_rom.read_wram2("wFullColorDebugReconstructionState")[0] == (
        barrier_before + 1
    ) & 0xFF
    _assert_reconstructed_visible_state(phase2_rom, tiles)
    palette = _rom_bytes(
        rom_path, phase2_rom, "FullColorCanaryBGPalettes", "FullColorCanaryBGPalettesEnd",
    )
    assert phase2_rom.emulator.read_palette_ram() == palette
    assert bytes(emu.memory[font_address + i] for i in range(len(expected_font))) == expected_font


def test_reconstruction_failure_never_unpoisons_sprite_production(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    phase2_rom.call("InitRendererOwnership")
    emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] = 0
    emu.memory[0xFF40] &= 0x7F

    _, flags = _farcall_from_wram(
        phase2_rom, "CompleteFullColorMapReconstruction", entry_bank=7,
    )

    assert flags & 0x10
    assert emu.memory[phase2_rom.emulator.symbols["wUpdateSpritesEnabled"]] == 0
    assert phase2_rom.read_wram2("wRendererOwner") == bytes((
        phase2_rom.constants["RENDERER_YELLOW"],
    ))


def test_guarded_request_classes_commit_complete_units_and_freeze_sources(
    phase2_rom: Phase2Rom,
) -> None:
    # Complete palette request.
    palette = bytes((index * 5 + 1) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC900, palette)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC900,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    phase2_rom.write_fixed(0xC900, b"\xee" * 64)
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == palette

    # Semantic paired transfer freezes both planes before returning.
    paired = bytes((0x30 + index) & 0xFF for index in range(6))
    phase2_rom.write_fixed(0xC740, paired)
    assert phase2_rom.call(
        "EnqueueFullColorMapRectangle", hl=0xC740, de=0x9840, b=3, c=2,
    )[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.write_fixed(0xC740, b"\xdd" * 6)
    phase2_rom.call("RunFullColorOwnershipVBlank")
    for row in range(2):
        expected = paired[row * 3:row * 3 + 3]
        assert phase2_rom.emulator.read_vram_bank(0, 0x9840 + row * 32, 3) == expected
        assert phase2_rom.emulator.read_vram_bank(1, 0x9840 + row * 32, 3) == bytes(
            value & 7 for value in expected
        )

    # Overlay uses request authority, never ambient VRAM, and animation binds
    # one tile-data replacement to its matching attribute byte.
    overlay = b"\x18\x29\x3a\x4b"
    phase2_rom.write_fixed(0xC760, overlay)
    assert phase2_rom.call(
        "EnqueueFullColorMapOverlay", hl=0xC760, de=0x9C00, b=2, c=2,
    )[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.write_fixed(0xC760, b"\xcc" * 4)
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9C00, 2) == overlay[:2]
    assert phase2_rom.emulator.read_vram_bank(1, 0x9C20, 2) == bytes(v & 7 for v in overlay[2:])

    animation = bytes(range(0x40, 0x50))
    phase2_rom.write_fixed(0xC780, animation)
    assert phase2_rom.call(
        "EnqueueFullColorAnimation", hl=0xC780, de=0x9000, b=0x98, c=0x60,
    )[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.write_fixed(0xC780, b"\xbb" * 16)
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9000, 16) == animation
    assert phase2_rom.emulator.read_vram_bank(1, 0x9860, 1) == bytes((animation[0] & 7,))


def test_oam_fallback_party_handoff_poison_and_authoritative_return(
    phase2_rom: Phase2Rom,
) -> None:
    emu = phase2_rom.emulator.pyboy
    batch = bytearray(160)
    for index in range(40):
        batch[index * 4:index * 4 + 4] = bytes((16, 8, index, 0xF8 | 7))
    identities = bytes((3, 0xFF, 9, 0x80) + (0,) * 36)
    phase2_rom.write_fixed(0xC900, bytes(batch) + identities)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", source=0xC900,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert bytes(emu.memory[0xFE00 + i] for i in range(16))[3::4] == bytes(
        (0xFB, 0xF8, 0xF8, 0xF8)
    )
    assert phase2_rom.read_wram2("wFullColorReconstructionItems", 4) == bytes((
        39, phase2_rom.constants["FULL_COLOR_FALLBACK_UNMAPPED"], 0, 39,
    ))

    for symbol in ("hAutoBGTransferEnabled", "hVBlankCopySize", "hRedrawRowOrColumnMode"):
        emu.memory[phase2_rom.emulator.symbols[symbol]] = 1
    generation = phase2_rom.generation
    assert _farcall_from_wram(
        phase2_rom, "BeginFullColorPartyHandoff", entry_bank=4,
    )[1] & 0x10 == 0
    assert phase2_rom.generation == generation + 1
    assert phase2_rom.read_wram2("wRendererOwner") == bytes((
        phase2_rom.constants["RENDERER_YELLOW"],
    ))
    assert phase2_rom.read_wram2("wRendererPhase") == bytes((
        phase2_rom.constants["YELLOW_ACTIVE"],
    ))
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\x01"
    for symbol in ("hAutoBGTransferEnabled", "hVBlankCopySize", "hRedrawRowOrColumnMode"):
        assert emu.memory[phase2_rom.emulator.symbols[symbol]] == 0

    _set_wram1_word(phase2_rom, "wMapViewVRAMPointer", 0x9800)
    assert _farcall_from_wram(
        phase2_rom, "ReturnFullColorFromParty", entry_bank=7,
    )[1] & 0x10 == 0
    assert phase2_rom.read_wram2("wFullColorPartyReturnPending") == b"\0"
    assert phase2_rom.read_wram2("wRendererPhase") == bytes((
        phase2_rom.constants["OVERWORLD_RECONSTRUCTING"],
    ))
    assert phase2_rom.read_wram2("wRendererAdmissionOpen") == b"\0"


@pytest.mark.parametrize("mutation", ("wrong_owner", "stale_generation", "visible_reconstruction", "bad_overlay_phase"))
def test_targeted_guard_mutations_fail_closed(
    phase2_rom: Phase2Rom, mutation: str,
) -> None:
    if mutation in {"wrong_owner", "stale_generation"}:
        request = phase2_rom.descriptor(
            "FULL_COLOR_REQUEST_MAP_ROW_PAIRED",
            owner="RENDERER_YELLOW" if mutation == "wrong_owner" else "RENDERER_FULL_COLOR_OVERWORLD",
            generation=phase2_rom.generation + (mutation == "stale_generation"),
        )
        result, flags = phase2_rom.admit(request)
        expected = phase2_rom.constants[
            "REJECTED_WRONG_OWNER" if mutation == "wrong_owner" else "REJECTED_STALE_GENERATION"
        ]
        assert result == expected and flags & 0x10
        assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\0"
        return

    if mutation == "visible_reconstruction":
        phase2_rom.write_wram2("wRendererPhase", phase2_rom.constants["OVERWORLD_RECONSTRUCTING"])
        phase2_rom.write_wram2("wRendererAdmissionOpen", 0)
        phase2_rom.emulator.pyboy.memory[0xFF40] |= 0x80
        assert phase2_rom.call("ReconstructFullColorMapEntry")[1] & 0x10
        assert phase2_rom.read_wram2("wRendererPhase") == bytes((
            phase2_rom.constants["OVERWORLD_RECONSTRUCTING"],
        ))
        assert phase2_rom.read_wram2("wRendererAdmissionOpen") == b"\0"
        return

    phase2_rom.write_wram2("wRendererPhase", phase2_rom.constants["YELLOW_ACTIVE"])
    assert phase2_rom.call("EnterFullColorOverlay")[1] & 0x10
    assert phase2_rom.read_wram2("wRendererPhase") == bytes((
        phase2_rom.constants["YELLOW_ACTIVE"],
    ))
