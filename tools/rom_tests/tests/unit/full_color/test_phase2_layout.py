"""Exact audit layout and shipped passive-renderer layout checks."""

import re
from pathlib import Path

import pytest

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


PRODUCTS = ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc")


def symbols(product: str) -> dict[str, tuple[int, int]]:
    result = {}
    for line in (REPOSITORY_ROOT / f"{product}.sym").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if match:
            result[match.group(3)] = (int(match.group(1), 16), int(match.group(2), 16))
    return result


def test_exact_wram_sram_and_rom_placements() -> None:
    audit = symbols("pokeyellow_phase2_audit")
    assert audit["wRendererStateStart"] == (2, 0xD000)
    assert audit["wRendererStateEnd"] == (2, 0xD00D)
    assert audit["wFullColorPhase2StateStart"] == (2, 0xD00D)
    assert audit["wFullColorPhase2StateEnd"] == (2, 0xD3D5)
    assert audit["wFullColorPhase2DebugStart"] == (3, 0xBEAF)
    assert audit["wFullColorPhase2DebugEnd"] == (3, 0xBFCF)
    assert audit["RouteRendererOwnershipVBlank"] == (0x3B, 0x452B)
    assert audit["InitFullColorSchedulerSelected"][0] == 0x3B


def test_phase2_rom_window_is_exact_and_normal_products_exclude_audit_surface() -> None:
    audit_map = (REPOSITORY_ROOT / "pokeyellow_phase2_audit.map").read_text(encoding="utf-8")
    assert '$452b-$552a ($1000 bytes) ["Full Color Phase 2 Pipelines"]' in audit_map

    forbidden = (b"Phase2Audit", b"FullColorPhase2", b"Phase2Hostile", b"P2AUDIT1")
    for product in ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc"):
        for suffix in (".sym", ".map", ".gbc"):
            blob = Path(REPOSITORY_ROOT / f"{product}{suffix}").read_bytes()
            assert not any(marker in blob for marker in forbidden)


@pytest.mark.parametrize("product", PRODUCTS)
def test_shipped_products_keep_passive_state_outside_audit_allocation(
    product: str,
) -> None:
    linked = symbols(product)
    assert linked["wRendererStateStart"] == (2, 0xD000)
    assert linked["wRendererStateEnd"] == (2, 0xD00D)
    assert linked["wPassiveFullColorStateStart"] == (2, 0xD800)
    assert linked["wPassiveFullColorStateEnd"] == (2, 0xD96C)
    assert linked["RouteRendererOwnershipVBlank"] == (0x3B, 0x44AC)
    assert linked["FullColorOverworldBGPalettes"] == (0x3B, 0x452B)
    assert "wFullColorPhase2StateStart" not in linked
    assert "InitFullColorSchedulerSelected" not in linked
