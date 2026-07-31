"""Reviewed entry configuration for the unmodified Yellow debug ROM."""

from __future__ import annotations

from pathlib import Path
import re

from .rom_discovery import (
    BankAddress,
    CopiedRegion,
    RomDiscoveryError,
    RomDiscoveryReport,
    SymbolTable,
    discover_rom_batched,
    load_map,
    load_sym,
)
from .source_discovery import SourceDiscoveryReport, discover_sources

SOURCE_ROOTS = (
    "audio.asm",
    "gfx/pics.asm",
    "gfx/pikachu.asm",
    "gfx/sprites.asm",
    "gfx/surfing_pikachu.asm",
    "gfx/tilesets.asm",
    "home.asm",
    "includes.asm",
    "main.asm",
    "maps.asm",
    "ram.asm",
    "text.asm",
)
SHADOW_OAM_RANGES = (
    (0xC300, 0xC39F),
    (0xC508, 0xC5A7),
)
COPIED_REGIONS = (
    CopiedRegion(
        bank=0x01,
        address=0x4AAC,
        runtime_address=0xFF80,
        length=0x0A,
        launcher="WriteDMACodeToHRAM",
    ),
)
FARCALL_LABELS = ("Bankswitch", "JumpToAddress")
DMA_CONTROL_LABELS = ("DMARoutine", "WriteDMACodeToHRAM", "hDMARoutine")

_PREDEF = re.compile(
    r"^\s*add_predef\s+([A-Za-z_][\w#.]*)(?:\s*,\s*\$([0-9a-f]+))?"
    r"(?:\s*;.*)?$",
    re.IGNORECASE,
)


def discover_baseline_sources(repository: str | Path) -> SourceDiscoveryReport:
    """Discover every linked source translation unit in canonical order."""
    return discover_sources(repository, SOURCE_ROOTS)


def writer_roots(report: SourceDiscoveryReport) -> tuple[str, ...]:
    """Return every source-backed writer label for ROM reachability."""
    return tuple(
        sorted(
            {
                finding.symbol
                for finding in report.findings
                if finding.category == "writer"
            }
        )
    )


def load_predef_targets(
    repository: str | Path,
    symbols: SymbolTable,
) -> dict[int, BankAddress]:
    """Resolve the ordered `add_predef` authority, including bank overrides."""
    path = Path(repository) / "data/predef_pointers.asm"
    targets: dict[int, BankAddress] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _PREDEF.match(line)
        if not match:
            continue
        name, override = match.groups()
        try:
            symbol = symbols.by_name[name]
        except KeyError as exc:
            raise RomDiscoveryError(
                f"{path.relative_to(repository)}: unknown predef symbol {name!r}"
            ) from exc
        bank = symbol.bank if override is None else int(override, 16)
        targets[len(targets)] = BankAddress(bank, symbol.address)
    if tuple(targets) != tuple(range(99)):
        raise RomDiscoveryError(
            "data/predef_pointers.asm: expected exactly 99 ordered predef rows"
        )
    return targets


def discover_baseline_rom(
    repository: str | Path,
    *,
    source_report: SourceDiscoveryReport | None = None,
    batch_size: int = 16,
) -> RomDiscoveryReport:
    """Run bounded source-rooted discovery against the baseline debug build."""
    root = Path(repository)
    report = source_report or discover_baseline_sources(root)
    symbols = load_sym(root / "pokeyellow_debug.sym")
    return discover_rom_batched(
        (root / "pokeyellow_debug.gbc").read_bytes(),
        symbols,
        writer_roots(report),
        batch_size=batch_size,
        sections=load_map(root / "pokeyellow_debug.map"),
        farcall_labels=FARCALL_LABELS,
        predef_targets=load_predef_targets(root, symbols),
        copied_regions=COPIED_REGIONS,
        shadow_oam_ranges=SHADOW_OAM_RANGES,
        dma_control_labels=DMA_CONTROL_LABELS,
        follow_calls=False,
    )
