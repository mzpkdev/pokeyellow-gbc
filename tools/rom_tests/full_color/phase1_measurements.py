"""Measure and select Phase 1 renderer ownership placement.

The resulting JSON is deliberately a derived artifact: every address comes
from the current RGBDS map/symbol output (or from the CGB WRAM bank geometry),
and every input is bound by SHA-256.  The module contains no donor placement.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Sequence


SCHEMA = "full-color-phase1-ownership-placement-v1"
OWNERSHIP_STATE_LAYOUT = (
    ("owner", 1),
    ("phase", 1),
    ("generation", 4),
    ("admission_open", 1),
    ("job_state", 1),
    ("job_generation", 4),
    ("job_cancellation_reason", 1),
)
PHASE1_STATE_BYTES = sum(size for _, size in OWNERSHIP_STATE_LAYOUT)
MINIMUM_STACK_MARGIN = 128
WRAMX_START = 0xD000
WRAMX_END = 0xDFFF
ROMX_START = 0x4000
ROMX_END = 0x7FFF
FORBIDDEN_ROM_BANKS = {
    0x1C: "RGB bank $1c extension is not assumed free in Yellow",
    0x2C: "Yellow Text 7 occupies RGB bank $2c",
    0x31: "Yellow Pikachu cries occupy RGB bank $31",
}
SELECTION_RULE = (
    "WRAM: fewest interrupt bank switches, fewest runtime bank switches, "
    "largest measured stack margin, lowest bank, lowest start; ROM: largest "
    "contiguous measured free range, lowest bank, lowest start; forbidden "
    "donor banks are never eligible"
)

_BANK_RE = re.compile(r"^(ROMX|WRAM0|WRAMX) bank #(\d+):$")
_SECTION_RE = re.compile(
    r'^\s*SECTION: \$([0-9a-fA-F]{4})(?:-\$([0-9a-fA-F]{4}))? '
    r'\(\$([0-9a-fA-F]{4}) bytes?\) \["([^"]+)"\]$'
)
_EMPTY_RE = re.compile(
    r"^\s*EMPTY: \$([0-9a-fA-F]{4})-\$([0-9a-fA-F]{4}) "
    r"\(\$([0-9a-fA-F]{4}) bytes?\)$"
)
_SYMBOL_RE = re.compile(r"^([0-9a-fA-F]{2}):([0-9a-fA-F]{4}) (\S+)$")


class PlacementError(ValueError):
    """The measured inputs cannot support a safe Phase 1 placement."""


@dataclass(frozen=True, slots=True)
class WramCandidate:
    section: str
    bank: int
    start: int
    end: int
    interrupt_bank_switches: int
    runtime_bank_switches: int
    stack_margin_bytes: int
    fits: bool = True
    overlaps: tuple[str, ...] = ()
    allocated: bool = False

    @property
    def size(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class RomCandidate:
    bank: int
    start: int
    end: int
    allocated: bool = False

    @property
    def size(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    kind: str
    bank: int
    start: int
    end: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "bank": self.bank,
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LinkMeasurement:
    rom_sha256: str
    map_sha256: str
    sym_sha256: str
    state_bytes: int
    wram: tuple[WramCandidate, ...]
    rom: tuple[RomCandidate, ...]
    stack_margin_bytes: int
    input_rom: str = "pokeyellow_debug.gbc"
    input_map: str = "pokeyellow_debug.map"
    input_sym: str = "pokeyellow_debug.sym"


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    schema: str
    rom_sha256: str
    map_sha256: str
    sym_sha256: str
    state_bytes: int
    selected_wram_section: str
    selected_wram_bank: int
    selected_wram_start: int
    selected_wram_end: int
    allocation_status: str
    interrupt_access: str
    interrupt_bank_switches: int
    runtime_bank_switches: int
    stack_margin_bytes: int
    selected_rom_bank: int
    selected_rom_start: int
    selected_rom_end: int
    rom_allocation_status: str
    input_rom: str
    input_map: str
    input_sym: str
    rejected_candidates: tuple[RejectedCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "inputs": {
                "rom": {"path": self.input_rom, "sha256": self.rom_sha256},
                "map": {"path": self.input_map, "sha256": self.map_sha256},
                "sym": {"path": self.input_sym, "sha256": self.sym_sha256},
            },
            "ownership_state": {
                "byte_cost": self.state_bytes,
                "selected_wram_section": self.selected_wram_section,
                "selected_wram_bank": self.selected_wram_bank,
                "selected_wram_start": self.selected_wram_start,
                "selected_wram_end": self.selected_wram_end,
                "allocation_status": self.allocation_status,
                "fields": [
                    {"name": name, "bytes": size}
                    for name, size in OWNERSHIP_STATE_LAYOUT
                ],
                "interrupt_access": self.interrupt_access,
                "interrupt_bank_switches": self.interrupt_bank_switches,
                "runtime_bank_switches": self.runtime_bank_switches,
                "stack_margin_bytes": self.stack_margin_bytes,
                "minimum_stack_margin_bytes": MINIMUM_STACK_MARGIN,
            },
            "rom": {
                "allocation_status": self.rom_allocation_status,
                "selected_bank": self.selected_rom_bank,
                "selected_free_start": self.selected_rom_start,
                "selected_free_end": self.selected_rom_end,
                "selected_free_bytes": self.selected_rom_end
                - self.selected_rom_start
                + 1,
            },
            "rejected_candidates": [
                candidate.to_dict() for candidate in self.rejected_candidates
            ],
            "selection_rule": SELECTION_RULE,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_ranges(
    start: int, end: int, occupied: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    for occupied_start, occupied_end in sorted(occupied):
        if occupied_end < start or occupied_start > end:
            continue
        occupied_start = max(start, occupied_start)
        occupied_end = min(end, occupied_end)
        if occupied_start > cursor:
            result.append((cursor, occupied_start - 1))
        cursor = max(cursor, occupied_end + 1)
    if cursor <= end:
        result.append((cursor, end))
    return result


def _parse_map(
    map_path: Path,
) -> tuple[
    dict[int, list[tuple[int, int, str]]],
    list[tuple[int, int, str]],
    dict[int, list[tuple[int, int, str]]],
]:
    rom_sections: dict[int, list[tuple[int, int, str]]] = {
        bank: [] for bank in range(1, 64)
    }
    wram0_sections: list[tuple[int, int, str]] = []
    wramx_sections: dict[int, list[tuple[int, int, str]]] = {
        bank: [] for bank in range(1, 8)
    }
    current_kind: str | None = None
    current_bank: int | None = None
    for line in map_path.read_text(encoding="utf-8").splitlines():
        bank_match = _BANK_RE.match(line)
        if bank_match:
            current_kind = bank_match.group(1)
            current_bank = int(bank_match.group(2))
            continue
        section_match = _SECTION_RE.match(line)
        if not section_match or current_kind is None or current_bank is None:
            continue
        start = int(section_match.group(1), 16)
        end = int(section_match.group(2) or section_match.group(1), 16)
        name = section_match.group(4)
        if current_kind == "ROMX":
            rom_sections.setdefault(current_bank, []).append((start, end, name))
        elif current_kind == "WRAM0":
            wram0_sections.append((start, end, name))
        elif current_kind == "WRAMX":
            wramx_sections.setdefault(current_bank, []).append((start, end, name))
    if not rom_sections or not wram0_sections:
        raise PlacementError(f"{map_path}: missing RGBDS ROMX or WRAM0 sections")
    return rom_sections, wram0_sections, wramx_sections


def _stack_margin(sym_path: Path, wram0_sections: Sequence[tuple[int, int, str]]) -> int:
    stack_symbol: int | None = None
    for line in sym_path.read_text(encoding="utf-8").splitlines():
        match = _SYMBOL_RE.match(line)
        if match and match.group(3) == "wStack":
            stack_symbol = int(match.group(2), 16)
            break
    stack_sections = [item for item in wram0_sections if item[2] == "Stack"]
    if stack_symbol is None or len(stack_sections) != 1:
        raise PlacementError("map/sym do not define exactly one Stack section and wStack")
    start, end, _ = stack_sections[0]
    if not start <= stack_symbol <= end:
        raise PlacementError("wStack lies outside the measured Stack section")
    return stack_symbol - start + 1


def measure(root: Path) -> LinkMeasurement:
    root = root.resolve()
    rom_path = root / "pokeyellow_debug.gbc"
    map_path = root / "pokeyellow_debug.map"
    sym_path = root / "pokeyellow_debug.sym"
    for path in (rom_path, map_path, sym_path):
        if not path.is_file():
            raise PlacementError(f"missing measurement input: {path}")

    rom_sections, wram0_sections, wramx_sections = _parse_map(map_path)
    all_wram_sections = list(wram0_sections)
    all_wram_sections.extend(
        section
        for sections in wramx_sections.values()
        for section in sections
    )
    stack_margin = _stack_margin(sym_path, all_wram_sections)
    # On CGB hardware SVBK=1 exposes the same $d000-$dfff storage that this
    # legacy ROM links as WRAM0.  Treat those linked sections as measured
    # occupancy for bank 1; an apparently empty WRAMX map entry is not free.
    bank1_aliases = tuple(
        name
        for start, end, name in wram0_sections
        if start <= WRAMX_END and end >= WRAMX_START
    )
    wram_candidates: list[WramCandidate] = []
    for bank in sorted(wramx_sections):
        ownership_sections = [
            (start, end, name)
            for start, end, name in wramx_sections[bank]
            if name == "Full Color Ownership State"
        ]
        if len(ownership_sections) > 1:
            raise PlacementError("multiple linked Full Color Ownership State sections")
        if ownership_sections:
            start, end, _ = ownership_sections[0]
            overlaps = tuple(
                name
                for other_start, other_end, name in wramx_sections[bank]
                if name != "Full Color Ownership State"
                and other_start <= end
                and other_end >= start
            )
            wram_candidates.append(
                WramCandidate(
                    section="Full Color Ownership State",
                    bank=bank,
                    start=start,
                    end=end,
                    interrupt_bank_switches=0 if bank == 1 else 2,
                    runtime_bank_switches=0 if bank == 1 else 2,
                    stack_margin_bytes=stack_margin,
                    overlaps=overlaps,
                    allocated=True,
                )
            )
        free_ranges = _free_ranges(
            WRAMX_START,
            WRAMX_END,
            [(start, end) for start, end, _ in wramx_sections[bank]],
        )
        wram_candidates.extend(
            WramCandidate(
                section="Full Color Ownership State",
                bank=bank,
                start=start,
                end=end,
                interrupt_bank_switches=0 if bank == 1 else 2,
                runtime_bank_switches=0 if bank == 1 else 2,
                stack_margin_bytes=stack_margin,
                overlaps=bank1_aliases if bank == 1 else (),
            )
            for start, end in free_ranges
        )
        if bank == 1 and not free_ranges and not ownership_sections:
            wram_candidates.append(
                WramCandidate(
                    section="Full Color Ownership State",
                    bank=1,
                    start=WRAMX_START,
                    end=WRAMX_END,
                    interrupt_bank_switches=0,
                    runtime_bank_switches=0,
                    stack_margin_bytes=stack_margin,
                    fits=False,
                    overlaps=tuple(name for _, _, name in wramx_sections[1]),
                )
            )
    wram = tuple(wram_candidates)
    rom: list[RomCandidate] = []
    for bank in sorted(rom_sections):
        ownership_sections = [
            (start, end, name)
            for start, end, name in rom_sections[bank]
            if name == "Full Color Ownership Core"
        ]
        if len(ownership_sections) > 1:
            raise PlacementError("multiple linked Full Color Ownership Core sections")
        if ownership_sections:
            start, end, _ = ownership_sections[0]
            rom.append(RomCandidate(bank, start, end, allocated=True))
        occupied = [(start, end) for start, end, _ in rom_sections[bank]]
        rom.extend(
            RomCandidate(bank, start, end)
            for start, end in _free_ranges(ROMX_START, ROMX_END, occupied)
        )
    return LinkMeasurement(
        rom_sha256=_sha256(rom_path),
        map_sha256=_sha256(map_path),
        sym_sha256=_sha256(sym_path),
        state_bytes=PHASE1_STATE_BYTES,
        wram=wram,
        rom=tuple(rom),
        stack_margin_bytes=stack_margin,
    )


def select_placement(measurement: LinkMeasurement) -> PlacementDecision:
    if measurement.state_bytes != PHASE1_STATE_BYTES:
        raise PlacementError(
            f"ownership state byte cost must be {PHASE1_STATE_BYTES}, got "
            f"{measurement.state_bytes}"
        )
    if measurement.stack_margin_bytes < MINIMUM_STACK_MARGIN:
        raise PlacementError(
            f"insufficient stack margin: {measurement.stack_margin_bytes} < "
            f"{MINIMUM_STACK_MARGIN} bytes"
        )

    rejected: list[RejectedCandidate] = []
    eligible_wram: list[WramCandidate] = []
    for candidate in measurement.wram:
        reason: str | None = None
        if not 1 <= candidate.bank <= 7:
            reason = "outside valid CGB switchable WRAM banks 1..7"
        elif not (
            WRAMX_START <= candidate.start <= candidate.end <= WRAMX_END
        ):
            reason = "outside the CGB WRAMX address range"
        elif candidate.overlaps:
            reason = "overlaps measured section(s): " + ", ".join(candidate.overlaps)
        elif not candidate.fits or candidate.size < measurement.state_bytes:
            reason = "does not fit the measured ownership-state byte cost"
        elif candidate.stack_margin_bytes < MINIMUM_STACK_MARGIN:
            reason = "insufficient measured stack margin"
        if reason:
            rejected.append(
                RejectedCandidate("WRAM", candidate.bank, candidate.start, candidate.end, reason)
            )
        else:
            eligible_wram.append(candidate)
    if not eligible_wram:
        raise PlacementError("no WRAM candidate fits the Phase 1 ownership state")
    linked_wram = [candidate for candidate in eligible_wram if candidate.allocated]
    if len(linked_wram) > 1:
        raise PlacementError("ownership state is linked in multiple WRAM banks")
    ranked_wram = linked_wram or eligible_wram
    selected_wram = min(
        ranked_wram,
        key=lambda candidate: (
            candidate.interrupt_bank_switches,
            candidate.runtime_bank_switches,
            -candidate.stack_margin_bytes,
            candidate.bank,
            candidate.start,
        ),
    )
    for candidate in eligible_wram:
        if candidate != selected_wram:
            rejected.append(
                RejectedCandidate(
                    "WRAM",
                    candidate.bank,
                    candidate.start,
                    candidate.end,
                    "lower-ranked by the deterministic measured selection rule",
                )
            )

    eligible_rom: list[RomCandidate] = []
    for candidate in measurement.rom:
        reason: str | None = None
        if not 1 <= candidate.bank <= 0x1FF:
            reason = "outside valid MBC5 switchable ROM banks"
        elif not ROMX_START <= candidate.start <= candidate.end <= ROMX_END:
            reason = "outside the ROMX address range"
        else:
            reason = FORBIDDEN_ROM_BANKS.get(candidate.bank)
        if reason:
            rejected.append(
                RejectedCandidate("ROM", candidate.bank, candidate.start, candidate.end, reason)
            )
        else:
            eligible_rom.append(candidate)
    if not eligible_rom:
        forbidden_banks = sorted({candidate.bank for candidate in measurement.rom})
        if forbidden_banks and all(bank in FORBIDDEN_ROM_BANKS for bank in forbidden_banks):
            raise PlacementError(
                "forbidden ROM bank(s) are the only measured candidates: "
                + ", ".join(f"${bank:02x}" for bank in forbidden_banks)
            )
        raise PlacementError("no measured ROM candidate is available")
    linked_rom = [candidate for candidate in eligible_rom if candidate.allocated]
    if len(linked_rom) > 1:
        raise PlacementError("ownership core is linked in multiple ROM banks")
    ranked_rom = linked_rom or eligible_rom
    selected_rom = min(
        ranked_rom, key=lambda candidate: (-candidate.size, candidate.bank, candidate.start)
    )
    for candidate in eligible_rom:
        if candidate != selected_rom:
            rejected.append(
                RejectedCandidate(
                    "ROM",
                    candidate.bank,
                    candidate.start,
                    candidate.end,
                    "lower-ranked by the deterministic measured selection rule",
                )
            )

    selected_end = selected_wram.start + measurement.state_bytes - 1
    return PlacementDecision(
        schema=SCHEMA,
        rom_sha256=measurement.rom_sha256,
        map_sha256=measurement.map_sha256,
        sym_sha256=measurement.sym_sha256,
        state_bytes=measurement.state_bytes,
        selected_wram_section=selected_wram.section,
        selected_wram_bank=selected_wram.bank,
        selected_wram_start=selected_wram.start,
        selected_wram_end=selected_end,
        allocation_status="linked" if selected_wram.allocated else "proposed",
        interrupt_access="REQUIRES_BANKED_PRESERVE_RSVBK",
        interrupt_bank_switches=selected_wram.interrupt_bank_switches,
        runtime_bank_switches=selected_wram.runtime_bank_switches,
        stack_margin_bytes=selected_wram.stack_margin_bytes,
        selected_rom_bank=selected_rom.bank,
        selected_rom_start=selected_rom.start,
        selected_rom_end=selected_rom.end,
        rom_allocation_status="linked" if selected_rom.allocated else "proposed",
        input_rom=measurement.input_rom,
        input_map=measurement.input_map,
        input_sym=measurement.input_sym,
        rejected_candidates=tuple(
            sorted(rejected, key=lambda item: (item.kind, item.bank, item.start, item.end, item.reason))
        ),
    )


def generate(root: Path) -> PlacementDecision:
    return select_placement(measure(root))


def verify_evidence(root: Path, evidence_path: Path) -> PlacementDecision:
    decision = generate(root)
    actual = evidence_path.read_text(encoding="utf-8")
    expected = decision.to_json()
    if actual != expected:
        raise PlacementError(
            f"stale or edited placement evidence: regenerate {evidence_path} from current build"
        )
    return decision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="compare instead of writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify:
            verify_evidence(args.root, args.output)
        else:
            decision = generate(args.root)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(decision.to_json(), encoding="utf-8")
    except (OSError, PlacementError) as exc:
        _parser().error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
