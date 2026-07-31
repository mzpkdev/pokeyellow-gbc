"""Reviewed entry configuration for the unmodified Yellow debug ROM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Sequence

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
LIFECYCLE_ROOTS = ("EnterMap",)
SCENE_ROOTS: tuple[str, ...] = ()
MUTATION_ROOTS = ("CopyMapViewToVRAM",)

_PREDEF = re.compile(
    r"^\s*add_predef\s+([A-Za-z_][\w#.]*)(?:\s*,\s*\$([0-9a-f]+))?"
    r"(?:\s*;.*)?$",
    re.IGNORECASE,
)


def discover_baseline_sources(repository: str | Path) -> SourceDiscoveryReport:
    """Discover every linked source translation unit in canonical order."""
    return discover_sources(
        repository,
        SOURCE_ROOTS,
        lifecycle_roots=LIFECYCLE_ROOTS,
        scene_roots=SCENE_ROOTS,
        mutation_roots=MUTATION_ROOTS,
    )


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
    scene_roots = tuple(sorted(set(LIFECYCLE_ROOTS) | set(SCENE_ROOTS)))
    roots = tuple(
        sorted(set(writer_roots(report)) | set(scene_roots) | set(MUTATION_ROOTS))
    )
    return discover_rom_batched(
        (root / "pokeyellow_debug.gbc").read_bytes(),
        symbols,
        roots,
        batch_size=batch_size,
        sections=load_map(root / "pokeyellow_debug.map"),
        farcall_labels=FARCALL_LABELS,
        predef_targets=load_predef_targets(root, symbols),
        copied_regions=COPIED_REGIONS,
        shadow_oam_ranges=SHADOW_OAM_RANGES,
        scene_roots=scene_roots,
        mutation_roots=MUTATION_ROOTS,
        dma_control_labels=DMA_CONTROL_LABELS,
        follow_calls=False,
    )


def baseline_summary(repository: str | Path) -> dict[str, Any]:
    """Return byte-stable evidence that the real baseline audit completed."""
    source = discover_baseline_sources(repository)
    rom = discover_baseline_rom(repository, source_report=source)
    return {
        "schema": "full-color-baseline-discovery-summary-v1",
        "source": {
            "sha256": source.source_sha256,
            "roots": len(source.roots),
            "files": len(source.include_graph),
            "findings": len(source.findings),
            "writer_roots": len(writer_roots(source)),
            "diagnostics": len(source.errors),
        },
        "rom": {
            "sha256": rom.rom_sha256,
            "sym_sha256": rom.sym_sha256,
            "map_sha256": rom.map_sha256,
            "findings": len(rom.findings),
            "visited_sites": len(rom.visited),
            "unresolved_destinations": len(rom.unresolved_destinations),
            "unresolved_control_flow": len(rom.unresolved_control_flow),
            "candidate_findings": len(rom.candidate_findings),
            "candidate_sections": len(rom.candidate_sections),
        },
    }


def summary_json(repository: str | Path) -> str:
    return (
        json.dumps(
            baseline_summary(repository),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic full-color Gate 0 baseline discovery."
    )
    parser.add_argument(
        "--repository",
        default=".",
        help="repository containing pokeyellow_debug.gbc/.sym/.map",
    )
    args = parser.parse_args(argv)
    print(summary_json(args.repository), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
