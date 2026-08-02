"""Real audit-ROM transforms and Yellow-owned debug palette selection."""

from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import (
    Phase2Rom,
    numeric_symbols,
    phase2_rom,
)


def _transformed(payload: bytes) -> bytes:
    result = bytearray()
    for low, high in zip(payload[::2], payload[1::2], strict=True):
        result.extend((0x1F - (low & 0x1F), (high & 0x7C) ^ 0x7C))
    return bytes(result)


def test_base_is_immutable_and_full_transform_commits(phase2_rom: Phase2Rom) -> None:
    payload = bytes((index * 7) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC900, payload)
    descriptor = phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC900, flags=2,
    )
    assert phase2_rom.admit(descriptor)[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.read_wram2("wFullColorBGPaletteBase", 64) == payload
    assert phase2_rom.read_wram2("wFullColorBGPaletteTransformed", 64) == _transformed(payload)
    assert phase2_rom.emulator.read_palette_ram() == _transformed(payload)


def test_hostile_canary_palette_authority_is_audit_only() -> None:
    audit = (REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym").read_text(
        encoding="utf-8"
    )
    assert "FullColorCanaryBGPalettes" in audit
    assert "FullColorCanaryOBJPalettes" in audit
    for product in ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc"):
        symbols = (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8")
        assert "FullColorCanaryBGPalettes" not in symbols
        assert "FullColorCanaryOBJPalettes" not in symbols
        assert "QueueYellowPaletteLane" not in symbols
        assert "CommitYellowPaletteLaneVBlank" not in symbols


def _symbol_bytes(rom: Path, sym: Path, name: str, size: int) -> bytes:
    location = next(
        line.split(maxsplit=1)[0]
        for line in sym.read_text(encoding="utf-8").splitlines()
        if line.endswith(f" {name}")
    )
    bank, address = (int(part, 16) for part in location.split(":"))
    offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
    return rom.read_bytes()[offset : offset + size]


def _publish_overworld_packet(
    product: str, tmp_path: Path, *, map_id: int, palette_id: int
) -> tuple[bytes, bytes]:
    rom = REPOSITORY_ROOT / f"{product}.gbc"
    sym = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(rom=rom, symbols=sym, results=tmp_path / product, cgb=True)
    harness = Phase2Rom(emulator, numeric_symbols(sym))
    try:
        packet = bytearray(_symbol_bytes(rom, sym, "PalPacket_Empty", 16))
        packet[1] = palette_id
        harness.write_fixed(0xC700, packet)
        emulator.write("wDefaultPaletteCommand", 9)  # SET_PAL_OVERWORLD
        emulator.write("wCurMap", map_id)
        emulator.pyboy.memory[0xFF40] = 0  # synchronous LCD-off publisher
        emulator.pyboy.memory[0xFF47] = 0xE4
        emulator.pyboy.memory[0xFF48] = 0xD0
        emulator.pyboy.memory[0xFF49] = 0xE4
        if product == "pokeyellow_debug":
            harness.call("InitCGBPalettesWithCommand", c=9, hl=0xC700)
        else:
            harness.call("InitCGBPalettes", hl=0xC700)
        return (
            emulator.read_palette_ram(),
            emulator.read_palette_ram(object_palettes=True),
        )
    finally:
        emulator.close()


@pytest.mark.parametrize(
    ("map_id", "palette_id", "payload_symbol"),
    (
        (0x00, 1, "YellowDebugPalletBGPalette"),
        (0x0C, 0, "YellowDebugRouteBGPalette"),
    ),
)
def test_yellow_publisher_duplicates_selected_map_bg_without_touching_obj(
    tmp_path: Path, map_id: int, palette_id: int, payload_symbol: str
) -> None:
    release_bg, release_obj = _publish_overworld_packet(
        "pokeyellow", tmp_path, map_id=map_id, palette_id=palette_id
    )
    debug_bg, debug_obj = _publish_overworld_packet(
        "pokeyellow_debug", tmp_path, map_id=map_id, palette_id=palette_id
    )
    base = _symbol_bytes(
        REPOSITORY_ROOT / "pokeyellow_debug.gbc",
        REPOSITORY_ROOT / "pokeyellow_debug.sym",
        payload_symbol,
        8,
    )
    assert debug_bg[:32] == base * 4
    assert debug_bg[32:] == release_bg[32:]
    assert debug_obj == release_obj
    assert debug_bg != release_bg


def test_debug_map_payloads_are_distinct_luminance_ordered_canaries() -> None:
    rom = REPOSITORY_ROOT / "pokeyellow_debug.gbc"
    sym = REPOSITORY_ROOT / "pokeyellow_debug.sym"
    payloads = tuple(
        _symbol_bytes(rom, sym, name, 8)
        for name in (
            "YellowDebugPalletBGPalette",
            "YellowDebugRouteBGPalette",
        )
    )
    assert payloads[0] != payloads[1]
    for payload in payloads:
        colors = tuple(
            int.from_bytes(payload[index : index + 2], "little")
            for index in range(0, 8, 2)
        )
        channels = tuple(
            (color & 0x1F, (color >> 5) & 0x1F, (color >> 10) & 0x1F)
            for color in colors
        )
        luminance = tuple(sum(color) for color in channels)
        assert channels[0] == (31, 31, 31)
        assert channels[-1] == (0, 0, 0)
        assert all(left > right for left, right in zip(luminance, luminance[1:]))
        assert channels[1] != channels[2]


def _publish_party_packet(
    product: str, tmp_path: Path,
) -> tuple[bytes, bytes]:
    rom = REPOSITORY_ROOT / f"{product}.gbc"
    sym = REPOSITORY_ROOT / f"{product}.sym"
    emulator = Emulator(
        rom=rom, symbols=sym, results=tmp_path / f"{product}-party", cgb=True
    )
    harness = Phase2Rom(emulator, numeric_symbols(sym))
    try:
        packet = _symbol_bytes(rom, sym, "PalPacket_PartyMenu", 16)
        harness.write_fixed(0xC700, packet)
        emulator.write("wDefaultPaletteCommand", 9)  # stale overworld default
        emulator.write("wCurMap", 0)  # Pallet Town
        emulator.pyboy.memory[0xFF40] = 0
        emulator.pyboy.memory[0xFF47] = 0xE4
        emulator.pyboy.memory[0xFF48] = 0xD0
        emulator.pyboy.memory[0xFF49] = 0xE4
        if product == "pokeyellow_debug":
            harness.call("InitCGBPalettesWithCommand", c=10, hl=0xC700)
        else:
            harness.call("InitCGBPalettes", hl=0xC700)
        return (
            emulator.read_palette_ram(),
            emulator.read_palette_ram(object_palettes=True),
        )
    finally:
        emulator.close()


def test_explicit_party_publication_in_pallet_is_byte_identical_to_release(
    tmp_path: Path,
) -> None:
    release = _publish_party_packet("pokeyellow", tmp_path)
    debug = _publish_party_packet("pokeyellow_debug", tmp_path)
    assert debug == release


def test_normal_debug_source_has_one_palette_authority() -> None:
    overworld = (REPOSITORY_ROOT / "home/overworld.asm").read_text(encoding="utf-8")
    vblank = (REPOSITORY_ROOT / "home/vblank.asm").read_text(encoding="utf-8")
    palettes = (REPOSITORY_ROOT / "engine/gfx/palettes.asm").read_text(
        encoding="utf-8"
    )
    assert "QueueYellowPaletteLane" not in overworld
    assert "CommitYellowPaletteLaneVBlank" not in vblank
    assert "SelectYellowDebugOverworldBGPalette" in palettes
    assert "call TransferCurBGPData" in palettes
