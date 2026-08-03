"""Real audit-ROM complete palette and transform checks."""

from pathlib import Path

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT
from tools.rom_tests.tests.unit.full_color.test_phase2_scheduler_rom import Phase2Rom, phase2_rom


def _transformed(payload: bytes) -> bytes:
    result = bytearray()
    for low, high in zip(payload[::2], payload[1::2], strict=True):
        result.extend((0x1F - (low & 0x1F), (high & 0x7C) ^ 0x7C))
    return bytes(result)


def test_base_is_immutable_and_full_transform_commits(phase2_rom: Phase2Rom) -> None:
    payload = bytes((index * 7) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC900, payload)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC900, flags=2,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.read_wram2("wFullColorBGPaletteBase", 64) == payload
    assert phase2_rom.read_wram2("wFullColorBGPaletteTransformed", 64) == _transformed(payload)
    assert phase2_rom.emulator.read_palette_ram() == _transformed(payload)


def test_normal_products_exclude_canary_palette_authority() -> None:
    audit = (REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym").read_text(encoding="utf-8")
    assert "FullColorCanaryBGPalettes" in audit and "FullColorCanaryOBJPalettes" in audit
    for product in ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc"):
        normal = (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8")
        assert "FullColorCanaryBGPalettes" not in normal
        assert "FullColorCanaryOBJPalettes" not in normal
