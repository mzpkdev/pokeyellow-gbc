"""Phase 1 CGB-only product-boundary contracts and ROM checks."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.full_color.runtime_observability import wait_until_debug_ready


ROOT = Path(__file__).parents[5]
CGB_HEADER_OFFSET = 0x143
CGB_ONLY = 0xC0
KEY1 = 0xFF4D
KEY1_DOUBLE_SPEED = 0x80
GATE0_BASELINE_PNG_SHA256 = (
    "526e3b7f513ec3428aa59874b9e5ef4c03a3187f0e2c2799626501f6a49af3b1"
)


def _built_rom(name: str) -> Path:
    path = ROOT / name
    assert path.is_file(), f"missing {name}; build it before running ROM tests"
    return path


def _hook_counter(emulator: Emulator, symbol: str) -> list[int]:
    calls: list[int] = []
    emulator.pyboy.hook_register(
        emulator.symbol_banks[symbol],
        emulator.symbols[symbol],
        lambda counter: counter.append(1),
        calls,
    )
    return calls


def _tick_until_called(
    emulator: Emulator, calls: list[int], *, max_frames: int = 120
) -> None:
    for _ in range(max_frames):
        if calls:
            return
        emulator.tick()
    assert calls, f"hook was not reached within {max_frames} frames"


def _png_sha256(emulator: Emulator) -> str:
    encoded = BytesIO()
    emulator.capture_screen().save(
        encoded,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return sha256(encoded.getvalue()).hexdigest()


def test_release_debug_and_vc_roms_are_cgb_only() -> None:
    for name in ("pokeyellow.gbc", "pokeyellow_debug.gbc", "pokeyellow_vc.gbc"):
        assert _built_rom(name).read_bytes()[CGB_HEADER_OFFSET] == CGB_ONLY


def test_startup_contract_rejects_non_cgb_and_switches_speed_once() -> None:
    source = (ROOT / "home" / "start.asm").read_text(encoding="utf-8")
    assert source.count("cp BOOTUP_A_CGB") == 1
    assert "RejectNonCGBStartup::\n\tdi\n.loop\n\thalt\n\tjr .loop" in source
    assert "jp RejectNonCGBStartup" in source
    assert source.count("\tldh [rSPD], a") == 1
    assert source.count("\tstop\n") == 1
    assert "bit B_SPD_DOUBLE, a" in source


def test_cgb_startup_reaches_init_once_at_double_speed(tmp_path: Path) -> None:
    emulator = Emulator(
        _built_rom("pokeyellow_debug.gbc"),
        _built_rom("pokeyellow_debug.sym"),
        tmp_path / "cgb",
        cgb=True,
    )
    try:
        init_calls = _hook_counter(emulator, "Init")
        _tick_until_called(emulator, init_calls)
        assert len(init_calls) == 1
        assert emulator.read_memory(KEY1, 1)[0] & KEY1_DOUBLE_SPEED
    finally:
        emulator.close()


@pytest.mark.parametrize(
    ("boot_identity", "boot_a"),
    (("DMG/SGB", 0x01), ("MGB/SGB2", 0xFF)),
)
def test_non_cgb_boot_identities_remain_in_rejection_path(
    tmp_path: Path, boot_identity: str, boot_a: int
) -> None:
    emulator = Emulator(
        _built_rom("pokeyellow_debug.gbc"),
        _built_rom("pokeyellow_debug.sym"),
        tmp_path / boot_identity.replace("/", "-"),
        cgb=True,
    )
    try:
        emulator.pyboy.hook_register(
            emulator.symbol_banks["_Start"],
            emulator.symbols["_Start"],
            lambda value: setattr(emulator.pyboy.register_file, "A", value),
            boot_a,
        )
        rejected = _hook_counter(emulator, "RejectNonCGBStartup")
        init_calls = _hook_counter(emulator, "Init")
        _tick_until_called(emulator, rejected)
        emulator.tick(5)
        assert rejected
        assert not init_calls
    finally:
        emulator.close()


def test_cgb_debug_ready_visual_matches_gate0_baseline(tmp_path: Path) -> None:
    emulator = Emulator(
        _built_rom("pokeyellow_debug.gbc"),
        _built_rom("pokeyellow_debug.sym"),
        tmp_path / "baseline",
        cgb=True,
    )
    try:
        wait_until_debug_ready(emulator)
        assert _png_sha256(emulator) == GATE0_BASELINE_PNG_SHA256
    finally:
        emulator.close()
