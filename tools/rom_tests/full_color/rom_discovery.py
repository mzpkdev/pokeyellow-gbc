"""Bank-aware built-ROM discovery utilities for Gate 0b."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
from typing import Any


class RomDiscoveryError(ValueError):
    """A linked artifact cannot be parsed or normalized safely."""


@dataclass(frozen=True, order=True, slots=True)
class BankAddress:
    bank: int
    address: int

    @property
    def rom_offset(self) -> int:
        return normalize_rom_offset(self.bank, self.address)


@dataclass(frozen=True, order=True, slots=True)
class Symbol:
    bank: int
    address: int
    name: str

    @property
    def rom_offset(self) -> int:
        return normalize_rom_offset(self.bank, self.address)


class SymbolTable:
    def __init__(
        self,
        symbols: Iterable[Symbol],
        *,
        artifact_sha256: str | None = None,
    ) -> None:
        ordered = tuple(sorted(symbols))
        names: dict[str, Symbol] = {}
        by_address: dict[tuple[int, int], list[str]] = defaultdict(list)
        for symbol in ordered:
            if symbol.name in names:
                raise RomDiscoveryError(f"duplicate symbol {symbol.name!r}")
            names[symbol.name] = symbol
            by_address[(symbol.bank, symbol.address)].append(symbol.name)
        self.symbols = ordered
        self.by_name = names
        self.by_address = {
            key: tuple(sorted(value)) for key, value in by_address.items()
        }
        self.artifact_sha256 = artifact_sha256

    def resolve(self, name: str) -> BankAddress:
        try:
            symbol = self.by_name[name]
        except KeyError as exc:
            raise RomDiscoveryError(f"unknown symbol {name!r}") from exc
        return BankAddress(symbol.bank, symbol.address)

    def aliases(self, bank: int, address: int) -> tuple[str, ...]:
        return self.by_address.get((bank, address), ())


_SYM = re.compile(r"^\s*([0-9a-f]+):([0-9a-f]{4})\s+(\S+)\s*$", re.IGNORECASE)
_SYM_CONSTANT = re.compile(r"^\s*[0-9a-f]+\s+\S+\s*$", re.IGNORECASE)


def parse_sym(text: str | bytes) -> SymbolTable:
    if isinstance(text, bytes):
        blob = text
        text = blob.decode("utf-8")
    else:
        blob = text.encode("utf-8")
    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        match = _SYM.match(line)
        if not match:
            if _SYM_CONSTANT.match(line):
                continue
            raise RomDiscoveryError(f".sym:{number}: malformed symbol line")
        bank, address = int(match.group(1), 16), int(match.group(2), 16)
        if bank > 0xFFFF or address > 0xFFFF:
            raise RomDiscoveryError(f".sym:{number}: bank/address exceeds 16 bits")
        symbols.append(Symbol(bank, address, match.group(3)))
    return SymbolTable(symbols, artifact_sha256=hashlib.sha256(blob).hexdigest())


def load_sym(path: str | Path) -> SymbolTable:
    return parse_sym(Path(path).read_bytes())


@dataclass(frozen=True, order=True, slots=True)
class MapSection:
    bank: int
    start: int
    end: int
    name: str
    region: str

    @property
    def size(self) -> int:
        return self.end - self.start + 1


class MapSections(tuple[MapSection, ...]):
    """Tuple-compatible parsed map sections retaining artifact identity."""

    def __new__(
        cls, sections: Iterable[MapSection], artifact_sha256: str
    ) -> "MapSections":
        value = super().__new__(cls, sections)
        value.artifact_sha256 = artifact_sha256
        return value


_MAP_BANK = re.compile(r"^(ROM0|ROMX) bank #([0-9]+):\s*$")
_MAP_ANY_BANK = re.compile(r"^[A-Z0-9]+ bank #[0-9]+:\s*$", re.IGNORECASE)
_MAP_SECTION = re.compile(
    r"^\s*SECTION:\s+\$([0-9a-f]{4})(?:-\$([0-9a-f]{4}))?"
    r'\s+\(\$([0-9a-f]+)\s+bytes?\)\s+\["([^"]+)"\]\s*$',
    re.IGNORECASE,
)


def parse_map(text: str | bytes) -> tuple[MapSection, ...]:
    if isinstance(text, bytes):
        blob = text
        text = blob.decode("utf-8")
    else:
        blob = text.encode("utf-8")
    region: str | None = None
    bank: int | None = None
    sections: list[MapSection] = []
    for number, line in enumerate(text.splitlines(), 1):
        if match := _MAP_BANK.match(line):
            region, bank = match.group(1), int(match.group(2))
            continue
        if _MAP_ANY_BANK.match(line):
            region = None
            bank = None
            continue
        if match := _MAP_SECTION.match(line):
            if region is None or bank is None:
                continue
            start = int(match.group(1), 16)
            size = int(match.group(3), 16)
            if size == 0:
                continue
            end = int(match.group(2), 16) if match.group(2) else start + size - 1
            normalize_rom_offset(bank, start)
            normalize_rom_offset(bank, end)
            if end < start:
                raise RomDiscoveryError(f".map:{number}: section end precedes start")
            if end - start + 1 != size:
                raise RomDiscoveryError(
                    f".map:{number}: section range does not match declared size"
                )
            sections.append(MapSection(bank, start, end, match.group(4), region))
    if not sections:
        raise RomDiscoveryError(".map: no ROM sections found")
    ordered = tuple(sorted(sections))
    for left, right in zip(ordered, ordered[1:]):
        if left.bank == right.bank and right.start <= left.end:
            raise RomDiscoveryError(
                f".map: overlapping sections {left.name!r} and {right.name!r}"
            )
    return MapSections(ordered, hashlib.sha256(blob).hexdigest())


def load_map(path: str | Path) -> tuple[MapSection, ...]:
    return parse_map(Path(path).read_bytes())


def normalize_rom_offset(bank: int, address: int) -> int:
    if isinstance(bank, bool) or isinstance(address, bool) or bank < 0 or address < 0:
        raise RomDiscoveryError("bank/address must be non-negative integers")
    if address < 0x4000:
        if bank != 0:
            raise RomDiscoveryError(
                f"banked address {bank:02x}:{address:04x} aliases fixed ROM bank"
            )
        return address
    if not 1 <= bank <= 0x1FF or address > 0x7FFF:
        raise RomDiscoveryError(f"invalid ROM address {bank:02x}:{address:04x}")
    return bank * 0x4000 + address - 0x4000


def bank_address_from_offset(offset: int) -> BankAddress:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise RomDiscoveryError("ROM offset must be non-negative")
    if offset < 0x4000:
        return BankAddress(0, offset)
    bank = offset // 0x4000
    return BankAddress(bank, 0x4000 + offset % 0x4000)


@dataclass(frozen=True, order=True, slots=True)
class Interval:
    low: int
    high: int

    def __post_init__(self) -> None:
        if not 0 <= self.low <= self.high <= 0xFFFF:
            raise ValueError("invalid register interval")

    @classmethod
    def exact(cls, value: int) -> "Interval":
        return cls(value, value)

    @property
    def value(self) -> int | None:
        return self.low if self.low == self.high else None

    def byte(self) -> "Interval":
        return Interval(self.low & 0xFF, self.high & 0xFF)


@dataclass(frozen=True, slots=True)
class DecoderState:
    bank: int
    address: int
    selected_bank: int | None = None
    bank_low: int | None = None
    bank_high: int | None = None
    a: Interval | None = None
    b: Interval | None = None
    c: Interval | None = None
    d: Interval | None = None
    e: Interval | None = None
    h: Interval | None = None
    l: Interval | None = None  # noqa: E741 - SM83 register name
    vbk: Interval | None = None

    def pair(self, high: str, low: str) -> Interval | None:
        hi, lo = getattr(self, high), getattr(self, low)
        if hi is None or lo is None:
            return None
        return Interval((hi.low << 8) | lo.low, (hi.high << 8) | lo.high)


@dataclass(frozen=True, order=True, slots=True)
class CopiedRegion:
    bank: int
    address: int
    runtime_address: int
    length: int
    launcher: str


@dataclass(frozen=True, order=True, slots=True)
class RomFinding:
    bank: int
    address: int
    rom_offset: int
    bytes: str
    mechanism: str
    destination_low: int | None
    destination_high: int | None
    resource: str
    vbk_low: int | None
    vbk_high: int | None
    root: str
    call_path: tuple[str, ...]
    runtime_copy: tuple[int, int, str] | None = None
    resolved: bool = True
    category: str = "writer"
    control_flow_kind: str | None = None
    dma_source_low: int | None = None
    dma_source_high: int | None = None

    @property
    def site_key(self) -> tuple[int, int]:
        return self.bank, self.address

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank": self.bank,
            "address": self.address,
            "rom_offset": self.rom_offset,
            "bytes": self.bytes,
            "mechanism": self.mechanism,
            "destination_low": self.destination_low,
            "destination_high": self.destination_high,
            "resource": self.resource,
            "vbk_low": self.vbk_low,
            "vbk_high": self.vbk_high,
            "root": self.root,
            "call_path": list(self.call_path),
            "runtime_copy": None
            if self.runtime_copy is None
            else {
                "address": self.runtime_copy[0],
                "length": self.runtime_copy[1],
                "launcher": self.runtime_copy[2],
            },
            "resolved": self.resolved,
            "category": self.category,
            "control_flow_kind": self.control_flow_kind,
            "dma_source_low": self.dma_source_low,
            "dma_source_high": self.dma_source_high,
        }


def _finding_sort_key(item: RomFinding) -> tuple[object, ...]:
    return (
        item.bank,
        item.address,
        -1 if item.destination_low is None else item.destination_low,
        -1 if item.destination_high is None else item.destination_high,
        item.root,
        item.call_path,
        item.mechanism,
    )


@dataclass(frozen=True, slots=True)
class RomDiscoveryReport:
    findings: tuple[RomFinding, ...]
    unresolved_destinations: tuple[str, ...]
    visited: tuple[tuple[int, int], ...]
    rom_sha256: str
    sym_sha256: str = ""
    map_sha256: str = ""
    unresolved_control_flow: tuple[str, ...] = ()
    candidate_findings: tuple[RomFinding, ...] = ()
    candidate_sections: tuple[MapSection, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "full-color-rom-discovery-v1",
            "rom_sha256": self.rom_sha256,
            "sym_sha256": self.sym_sha256,
            "map_sha256": self.map_sha256,
            "findings": [finding.to_dict() for finding in self.findings],
            "unresolved_destinations": list(self.unresolved_destinations),
            "unresolved_control_flow": list(self.unresolved_control_flow),
            "candidate_findings": [
                finding.to_dict() for finding in self.candidate_findings
            ],
            "candidate_sections": [
                {
                    "bank": section.bank,
                    "start": section.start,
                    "end": section.end,
                    "name": section.name,
                    "region": section.region,
                }
                for section in self.candidate_sections
            ],
            "visited": [
                {"bank": bank, "address": address} for bank, address in self.visited
            ],
        }

    def to_json(self) -> str:
        import json

        return (
            json.dumps(
                self.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        )


_BUILTIN_RESOURCE_RANGES = (
    (0xFF40, 0xFF4B, "DISPLAY_REGISTER"),
    (0xFF4F, 0xFF4F, "VRAM_BANK"),
    (0xFF51, 0xFF55, "HDMA_GDMA"),
    (0xFF68, 0xFF6B, "CGB_PALETTE"),
    (0xFF70, 0xFF70, "WRAM_BANK"),
    (0x9800, 0x9FFF, "BG_WINDOW_MAP"),
    (0xFE00, 0xFE9F, "HARDWARE_OAM"),
)


def _resource(
    low: int,
    high: int,
    extra_ranges: Sequence[tuple[int, int, str]] = (),
) -> str | None:
    ranges = _BUILTIN_RESOURCE_RANGES + tuple(extra_ranges)
    hits = {name for start, end, name in ranges if not (high < start or low > end)}
    if len(hits) == 1:
        return hits.pop()
    return "MIXED_OR_UNKNOWN" if hits else None


_LENGTHS = (
    (1, 3, 1, 1, 1, 1, 2, 1, 3, 1, 1, 1, 1, 1, 2, 1),
    (2, 3, 1, 1, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 2, 1),
    (2, 3, 1, 1, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 2, 1),
    (2, 3, 1, 1, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 2, 1),
    *((1,) * 16 for _ in range(8)),
    (1, 1, 3, 3, 3, 1, 2, 1, 1, 1, 3, 2, 3, 3, 2, 1),
    (1, 1, 3, 1, 3, 1, 2, 1, 1, 1, 3, 1, 3, 1, 2, 1),
    (2, 1, 1, 1, 1, 1, 2, 1, 2, 1, 3, 1, 1, 1, 2, 1),
    (2, 1, 1, 1, 1, 1, 2, 1, 2, 1, 3, 1, 1, 1, 2, 1),
)
OPCODE_LENGTH = tuple(length for row in _LENGTHS for length in row)

_CANDIDATE_OPCODES = frozenset(
    {
        0xE0,
        0xE2,
        0xEA,
        0x08,
        0x02,
        0x12,
        0x22,
        0x32,
        0x36,
        *range(0x70, 0x76),
        0x77,
    }
)


class SM83Decoder:
    """Conservative bank-aware worklist decoder for reviewed entry roots."""

    def __init__(
        self,
        rom: bytes,
        symbols: SymbolTable,
        *,
        sections: Sequence[MapSection] = (),
        farcall_labels: Iterable[str] = ("Bankswitch", "FarCall", "JumpToAddress"),
        predef_targets: Mapping[int, BankAddress] | None = None,
        jump_tables: Mapping[tuple[int, int], Sequence[BankAddress]] | None = None,
        copied_regions: Sequence[CopiedRegion] = (),
        owner_gated_ranges: Sequence[tuple[int, int, str]] = (),
        shadow_oam_ranges: Sequence[tuple[int, int]] = (),
        scene_roots: Iterable[str] = (),
        mutation_roots: Iterable[str] = (),
        dma_control_labels: Iterable[str] = (),
        follow_calls: bool = True,
    ) -> None:
        self.rom = bytes(rom)
        self.symbols = symbols
        self.sym_sha256 = symbols.artifact_sha256
        self.map_sha256 = getattr(sections, "artifact_sha256", None)
        self.sections = tuple(sections)
        self.farcall_addresses = {
            (site.bank, site.address)
            for name in farcall_labels
            if (site := symbols.by_name.get(name)) is not None
        }
        self.predef_targets = dict(predef_targets or {})
        self.jump_tables = {
            key: tuple(value) for key, value in (jump_tables or {}).items()
        }
        self.copied_regions = tuple(copied_regions)
        configured_ranges = list(owner_gated_ranges)
        configured_ranges.extend(
            (low, high, "SHADOW_OAM") for low, high in shadow_oam_ranges
        )
        for low, high, name in configured_ranges:
            if not 0 <= low <= high <= 0xFFFF or not name:
                raise RomDiscoveryError("invalid configured owner-gated range")
        self.owner_gated_ranges = tuple(sorted(configured_ranges))
        self.scene_roots = frozenset(scene_roots)
        self.mutation_roots = frozenset(mutation_roots)
        self.dma_control_labels = frozenset(dma_control_labels)
        self.follow_calls = follow_calls

    def _validate_candidate_coverage(self) -> None:
        if not self.sections:
            raise RomDiscoveryError(
                "non-empty linker ROM sections are required for candidate scanning"
            )
        for section in self.sections:
            if section.region == "ROM0":
                valid_region = section.bank == 0 and section.end < 0x4000
            elif section.region == "ROMX":
                valid_region = section.bank > 0 and section.start >= 0x4000
            else:
                valid_region = False
            try:
                start = normalize_rom_offset(section.bank, section.start)
                end = normalize_rom_offset(section.bank, section.end)
            except RomDiscoveryError as exc:
                raise RomDiscoveryError(
                    f"invalid linker ROM section {section.name!r}"
                ) from exc
            if (
                not section.name
                or not valid_region
                or section.end < section.start
                or end >= len(self.rom)
            ):
                raise RomDiscoveryError(f"invalid linker ROM section {section.name!r}")
            if start > end:
                raise RomDiscoveryError(f"invalid linker ROM section {section.name!r}")

        ordered = sorted(self.sections)
        for left, right in zip(ordered, ordered[1:]):
            if left.bank == right.bank and right.start <= left.end:
                raise RomDiscoveryError(
                    f"overlapping linker ROM sections {left.name!r} and {right.name!r}"
                )

        for offset, opcode in enumerate(self.rom):
            if opcode not in _CANDIDATE_OPCODES:
                continue
            site = bank_address_from_offset(offset)
            if not any(
                section.bank == site.bank
                and section.start <= site.address <= section.end
                for section in self.sections
            ):
                raise RomDiscoveryError(
                    "linker ROM sections omit candidate opcode at "
                    f"{site.bank:02x}:{site.address:04x}"
                )

    def _symbol_digest(self) -> str:
        if self.sym_sha256 is not None:
            return self.sym_sha256
        value = (
            "\n".join(
                f"{item.bank:04x}:{item.address:04x} {item.name}"
                for item in self.symbols.symbols
            )
            + "\n"
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _map_digest(self) -> str:
        if self.map_sha256 is not None:
            return self.map_sha256
        value = (
            "\n".join(
                f"{item.region}:{item.bank}:{item.start:04x}:{item.end:04x}:{item.name}"
                for item in self.sections
            )
            + "\n"
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def decode(
        self,
        roots: Iterable[str | BankAddress],
        *,
        scan_candidates: bool = True,
        validate_coverage: bool = True,
    ) -> RomDiscoveryReport:
        if validate_coverage:
            self._validate_candidate_coverage()
        queue: deque[tuple[DecoderState, str, tuple[str, ...]]] = deque()
        root_entries: dict[str, BankAddress] = {}
        for root in roots:
            if isinstance(root, str):
                site = self.symbols.resolve(root)
                root_name = root
                if root in self.scene_roots or root in self.mutation_roots:
                    root_entries[root] = site
            else:
                site, root_name = root, f"{root.bank:02x}:{root.address:04x}"
            queue.append(
                (
                    DecoderState(
                        site.bank,
                        site.address,
                        site.bank if site.bank else None,
                        (site.bank & 0xFF) if site.bank else None,
                        ((site.bank >> 8) & 1) if site.bank else None,
                    ),
                    root_name,
                    (root_name,),
                )
            )
        joined_states: dict[
            tuple[str, int, int, int | None, int | None, int | None],
            DecoderState,
        ] = {}
        visited_sites: set[tuple[int, int]] = set()
        findings: list[RomFinding] = []
        emitted_root_entries: set[str] = set()
        unresolved: set[str] = set()
        unresolved_control: set[str] = set()
        max_states = max(4096, len(self.rom) * 2)
        while queue:
            state, root, path = queue.popleft()
            key = (
                root,
                state.bank,
                state.address,
                state.selected_bank,
                state.bank_low,
                state.bank_high,
            )
            previous = joined_states.get(key)
            if previous is not None:
                joined = self._join_state(previous, state)
                if joined == previous:
                    continue
                state = joined
            joined_states[key] = state
            if len(joined_states) > max_states:
                raise RomDiscoveryError("decoder state limit exceeded")
            try:
                offset = normalize_rom_offset(state.bank, state.address)
            except RomDiscoveryError:
                unresolved.add(
                    f"{root}: invalid destination {state.bank:02x}:{state.address:04x}"
                )
                continue
            if offset >= len(self.rom):
                unresolved.add(
                    f"{root}: destination outside ROM {state.bank:02x}:{state.address:04x}"
                )
                continue
            if self.sections and not any(
                section.bank == state.bank
                and section.start <= state.address <= section.end
                for section in self.sections
            ):
                unresolved.add(
                    f"{root}: destination outside linked section {state.bank:02x}:{state.address:04x}"
                )
                continue
            visited_sites.add((state.bank, state.address))
            opcode = self.rom[offset]
            length = OPCODE_LENGTH[opcode]
            if offset + length > len(self.rom):
                unresolved.add(
                    f"{root}: truncated instruction {state.bank:02x}:{state.address:04x}"
                )
                continue
            data = self.rom[offset : offset + length]
            if (
                root not in emitted_root_entries
                and root_entries.get(root) == BankAddress(state.bank, state.address)
                and path == (root,)
            ):
                category = "mutation" if root in self.mutation_roots else "scene"
                findings.append(
                    RomFinding(
                        state.bank,
                        state.address,
                        offset,
                        data.hex(),
                        "root-entry",
                        state.address,
                        state.address,
                        "CONTROL_FLOW",
                        None,
                        None,
                        root,
                        path,
                        None,
                        True,
                        category,
                        "root-entry",
                    )
                )
                emitted_root_entries.add(root)
            next_state = replace(state, address=state.address + length)
            next_state = self._transfer(next_state, opcode, data)
            finding = self._sink(state, opcode, data, root, path)
            if finding:
                findings.append(finding)
                if not finding.resolved:
                    unresolved.add(
                        f"{root}: unresolved {finding.mechanism} destination "
                        f"{state.bank:02x}:{state.address:04x}"
                    )
                if (
                    finding.destination_low == 0xFF4F
                    and finding.destination_high == 0xFF4F
                ):
                    next_state = replace(
                        next_state,
                        vbk=self._store_value(state, opcode, data),
                    )
            # MBC5 low and high ROM-bank register effects.  A bank switch made
            # while executing ROMX changes the physical fallthrough bank too.
            bank_fallthrough_unknown = False
            store_destination = self._store_destination(state, opcode, data)
            if store_destination is not None and store_destination.value is not None:
                store_address = store_destination.value
                store_value = self._store_value(state, opcode, data)
                value = None if store_value is None else store_value.value
                if 0x2000 <= store_address <= 0x2FFF:
                    low_component = value
                    selected = (
                        (state.bank_high << 8) | low_component
                        if low_component is not None and state.bank_high is not None
                        else None
                    )
                    next_state = replace(
                        next_state,
                        selected_bank=selected,
                        bank_low=low_component,
                    )
                    if state.address >= 0x4000:
                        if selected is None:
                            bank_fallthrough_unknown = True
                        else:
                            next_state = replace(next_state, bank=selected)
                    if value is None:
                        unresolved_control.add(
                            f"{root}: unknown MBC5 low-bank write at "
                            f"{state.bank:02x}:{state.address:04x}"
                        )
                elif 0x3000 <= store_address <= 0x3FFF:
                    high_component = None if value is None else value & 1
                    selected = (
                        (high_component << 8) | state.bank_low
                        if high_component is not None and state.bank_low is not None
                        else None
                    )
                    next_state = replace(
                        next_state,
                        selected_bank=selected,
                        bank_high=high_component,
                    )
                    if state.address >= 0x4000:
                        if selected is None:
                            bank_fallthrough_unknown = True
                        else:
                            next_state = replace(next_state, bank=selected)
                    if value is None:
                        unresolved_control.add(
                            f"{root}: unknown MBC5 high-bank write at "
                            f"{state.bank:02x}:{state.address:04x}"
                        )

            def enqueue(target: BankAddress, suffix: str) -> None:
                queue.append(
                    (
                        replace(next_state, bank=target.bank, address=target.address),
                        root,
                        path + (suffix,),
                    )
                )

            # RET/RETI and illegal hard stops.
            if opcode in {0xC9, 0xD9}:
                continue
            # JP (HL) / indirect jump table.
            if opcode == 0xE9:
                hl = state.pair("h", "l")
                targets = self.jump_tables.get((state.bank, state.address), ())
                if targets:
                    for target in targets:
                        enqueue(target, f"{target.bank:02x}:{target.address:04x}")
                elif hl and hl.value is not None:
                    bank = 0 if hl.value < 0x4000 else state.selected_bank
                    if bank is None:
                        unresolved_control.add(
                            f"{root}: unresolved indirect jump bank "
                            f"{state.bank:02x}:{state.address:04x}"
                        )
                    else:
                        enqueue(
                            BankAddress(bank, hl.value), f"{bank:02x}:{hl.value:04x}"
                        )
                else:
                    unresolved.add(
                        f"{root}: unresolved indirect jump {state.bank:02x}:{state.address:04x}"
                    )
                continue
            # RST.
            if opcode & 0xC7 == 0xC7:
                enqueue(BankAddress(0, opcode & 0x38), f"00:{opcode & 0x38:04x}")
                queue.append((self._call_fallthrough(next_state, state), root, path))
                continue
            # CALL.
            if opcode in {0xC4, 0xCC, 0xD4, 0xDC, 0xCD}:
                target_address = data[1] | data[2] << 8
                target_bank = 0 if target_address < 0x4000 else state.selected_bank
                if target_bank is None:
                    unresolved_control.add(
                        f"{root}: unresolved call bank at "
                        f"{state.bank:02x}:{state.address:04x}"
                    )
                    target = None
                else:
                    target = BankAddress(target_bank, target_address)
                    if self.follow_calls:
                        enqueue(target, f"{target_bank:02x}:{target_address:04x}")
                    control = self._control_flow_finding(
                        state, data, root, path, "call", target
                    )
                    if control is not None:
                        findings.append(control)
                if (
                    self.follow_calls
                    and target is not None
                    and (target.bank, target.address) in self.farcall_addresses
                ):
                    b, hl = state.b, state.pair("h", "l")
                    if b and b.value is not None and hl and hl.value is not None:
                        enqueue(
                            BankAddress(b.value, hl.value),
                            f"{b.value:02x}:{hl.value:04x}",
                        )
                    else:
                        unresolved.add(
                            f"{root}: unresolved farcall at {state.bank:02x}:{state.address:04x}"
                        )
                if (
                    self.follow_calls
                    and target is not None
                    and target.address
                    in {
                        symbol.address
                        for name, symbol in self.symbols.by_name.items()
                        if name.lower().startswith("predef")
                    }
                ):
                    if state.a and state.a.value in self.predef_targets:
                        enqueue(
                            self.predef_targets[state.a.value],
                            f"predef:{state.a.value:02x}",
                        )
                    else:
                        unresolved.add(
                            f"{root}: unresolved predef at {state.bank:02x}:{state.address:04x}"
                        )
                fallthrough = self._call_fallthrough(next_state, state)
                queue.append((fallthrough, root, path))
                continue
            # Absolute JP.
            if opcode in {0xC2, 0xCA, 0xD2, 0xDA, 0xC3}:
                address = data[1] | data[2] << 8
                bank = 0 if address < 0x4000 else state.selected_bank
                if bank is None:
                    unresolved_control.add(
                        f"{root}: unresolved jump bank at "
                        f"{state.bank:02x}:{state.address:04x}"
                    )
                else:
                    target = BankAddress(bank, address)
                    enqueue(target, f"{bank:02x}:{address:04x}")
                    control = self._control_flow_finding(
                        state, data, root, path, "jump", target
                    )
                    if control is not None:
                        findings.append(control)
                if opcode != 0xC3:
                    queue.append((next_state, root, path))
                continue
            # Relative JR.
            if opcode in {0x18, 0x20, 0x28, 0x30, 0x38}:
                displacement = data[1] - 256 if data[1] >= 128 else data[1]
                target = state.address + 2 + displacement
                enqueue(
                    BankAddress(state.bank, target), f"{state.bank:02x}:{target:04x}"
                )
                if opcode != 0x18:
                    queue.append((next_state, root, path))
                continue
            if bank_fallthrough_unknown:
                unresolved_control.add(
                    f"{root}: unknown MBC5 bank write at "
                    f"{state.bank:02x}:{state.address:04x}"
                )
                continue
            queue.append((next_state, root, path))

        # Associate copied HRAM evidence with sites contained in reviewed copy ranges.
        adjusted = [self._with_copied_region(finding) for finding in findings]
        unique = {
            (
                item.bank,
                item.address,
                item.destination_low,
                item.destination_high,
                item.root,
                item.call_path,
                item.mechanism,
                item.category,
            ): item
            for item in adjusted
        }
        ordered = tuple(sorted(unique.values(), key=_finding_sort_key))
        return RomDiscoveryReport(
            ordered,
            tuple(sorted(unresolved)),
            tuple(sorted(visited_sites)),
            hashlib.sha256(self.rom).hexdigest(),
            self._symbol_digest(),
            self._map_digest(),
            tuple(sorted(unresolved_control)),
            self.scan_executable_candidates() if scan_candidates else (),
            self.sections,
        )

    def _with_copied_region(self, finding: RomFinding) -> RomFinding:
        copied = next(
            (
                region
                for region in self.copied_regions
                if region.bank == finding.bank
                and region.address <= finding.address < region.address + region.length
            ),
            None,
        )
        if copied is None:
            return finding
        runtime = copied.runtime_address + finding.address - copied.address
        return replace(
            finding,
            mechanism=f"copied-hram:{finding.mechanism}",
            runtime_copy=(runtime, copied.length, copied.launcher),
        )

    @staticmethod
    def _call_fallthrough(
        next_state: DecoderState, caller: DecoderState
    ) -> DecoderState:
        selected = caller.bank if caller.address >= 0x4000 else None
        return replace(
            next_state,
            selected_bank=selected,
            bank_low=None if selected is None else selected & 0xFF,
            bank_high=None if selected is None else (selected >> 8) & 1,
            a=None,
            b=None,
            c=None,
            d=None,
            e=None,
            h=None,
            l=None,
            vbk=None,
        )

    def _control_flow_finding(
        self,
        state: DecoderState,
        data: bytes,
        root: str,
        path: tuple[str, ...],
        mechanism: str,
        target: BankAddress,
    ) -> RomFinding | None:
        if root in self.mutation_roots:
            category = "mutation"
        elif root in self.scene_roots:
            category = "scene"
        else:
            target_names = self.symbols.aliases(target.bank, target.address)
            dma_names = tuple(
                name
                for name in target_names
                if (name in self.dma_control_labels or "DMA" in name or "OAM" in name)
            )
            if not dma_names:
                return None
            category = "writer"
            mechanism = (
                "dma-wait"
                if any("wait" in name.lower() for name in dma_names)
                else "dma-wrapper"
            )
        return RomFinding(
            state.bank,
            state.address,
            normalize_rom_offset(state.bank, state.address),
            data.hex(),
            mechanism,
            target.address,
            target.address,
            "OAM_DMA_CONTROL",
            None,
            None,
            root,
            path,
            None,
            True,
            category,
            mechanism,
        )

    @staticmethod
    def _store_destination(
        state: DecoderState, opcode: int, data: bytes
    ) -> Interval | None:
        if opcode in {0xEA, 0x08}:
            return Interval.exact(data[1] | data[2] << 8)
        if opcode == 0x02:
            return state.pair("b", "c")
        if opcode == 0x12:
            return state.pair("d", "e")
        if opcode in {
            0x22,
            0x32,
            0x36,
            0x70,
            0x71,
            0x72,
            0x73,
            0x74,
            0x75,
            0x77,
        }:
            return state.pair("h", "l")
        return None

    @staticmethod
    def _store_value(state: DecoderState, opcode: int, data: bytes) -> Interval | None:
        if opcode == 0x36:
            return Interval.exact(data[1])
        if opcode in {0x02, 0x12, 0x22, 0x32, 0x77, 0xE0, 0xE2, 0xEA}:
            return state.a
        register = {
            0x70: "b",
            0x71: "c",
            0x72: "d",
            0x73: "e",
            0x74: "h",
            0x75: "l",
        }.get(opcode)
        return None if register is None else getattr(state, register)

    @staticmethod
    def _join_state(left: DecoderState, right: DecoderState) -> DecoderState:
        changes: dict[str, Interval | None] = {}
        for name in ("a", "b", "c", "d", "e", "h", "l", "vbk"):
            old, new = getattr(left, name), getattr(right, name)
            if old == new:
                changes[name] = old
            elif old is None or new is None:
                changes[name] = None
            elif name == "vbk":
                changes[name] = Interval(0, 1)
            else:
                # Immediate widening makes loops converge and is conservative:
                # after two differing byte values, retain the whole byte range.
                changes[name] = Interval(0, 0xFF)
        return replace(
            left,
            selected_bank=(
                left.selected_bank
                if left.selected_bank == right.selected_bank
                else None
            ),
            bank_low=left.bank_low if left.bank_low == right.bank_low else None,
            bank_high=(left.bank_high if left.bank_high == right.bank_high else None),
            **changes,
        )

    @staticmethod
    def _transfer(state: DecoderState, opcode: int, data: bytes) -> DecoderState:
        # Immediate 8-bit loads.
        immediate = {
            0x06: "b",
            0x0E: "c",
            0x16: "d",
            0x1E: "e",
            0x26: "h",
            0x2E: "l",
            0x3E: "a",
        }
        if opcode in immediate:
            return replace(state, **{immediate[opcode]: Interval.exact(data[1])})
        # Immediate register pairs.
        pair = {0x01: ("b", "c"), 0x11: ("d", "e"), 0x21: ("h", "l")}
        if opcode in pair:
            high, low = pair[opcode]
            return replace(
                state,
                **{high: Interval.exact(data[2]), low: Interval.exact(data[1])},
            )
        if opcode == 0xAF:  # xor a
            return replace(state, a=Interval.exact(0))
        if opcode == 0xE6 and state.a:  # and immediate
            mask = data[1]
            if state.a.value is not None:
                return replace(state, a=Interval.exact(state.a.value & mask))
            return replace(state, a=None)
        # LD r,r including A/C and pointer-pair construction.
        registers = ("b", "c", "d", "e", "h", "l", None, "a")
        if 0x40 <= opcode <= 0x7F and opcode != 0x76:
            dst = registers[(opcode >> 3) & 7]
            src = registers[opcode & 7]
            if dst is not None:
                return replace(
                    state, **{dst: None if src is None else getattr(state, src)}
                )
        # Loads from memory and high-memory reads cannot preserve an older A.
        if opcode in {0x0A, 0x1A, 0x2A, 0x3A, 0xF0, 0xF2, 0xFA}:
            changes: dict[str, Interval | None] = {"a": None}
            if opcode in {0x2A, 0x3A}:
                hl = state.pair("h", "l")
                delta = 1 if opcode == 0x2A else -1
                if hl is not None and hl.value is not None:
                    value = (hl.value + delta) & 0xFFFF
                    changes.update(
                        h=Interval.exact(value >> 8),
                        l=Interval.exact(value & 0xFF),
                    )
                else:
                    changes.update(h=None, l=None)
            return replace(state, **changes)
        # Pointer stores with auto increment/decrement update HL after the write.
        if opcode in {0x22, 0x32}:
            hl = state.pair("h", "l")
            delta = 1 if opcode == 0x22 else -1
            if hl is not None and hl.value is not None:
                value = (hl.value + delta) & 0xFFFF
                return replace(
                    state,
                    h=Interval.exact(value >> 8),
                    l=Interval.exact(value & 0xFF),
                )
            return replace(state, h=None, l=None)
        # INC/DEC byte registers, conservatively bounded.
        for base, delta in ((0x04, 1), (0x05, -1)):
            if opcode & 0xC7 == base:
                register = registers[(opcode >> 3) & 7]
                if register:
                    value = getattr(state, register)
                    if value and 0 <= value.low + delta <= value.high + delta <= 0xFF:
                        return replace(
                            state,
                            **{
                                register: Interval(
                                    value.low + delta, value.high + delta
                                )
                            },
                        )
                    return replace(state, **{register: None})
        # 16-bit INC/DEC.
        pairs = {
            0x03: ("b", "c", 1),
            0x0B: ("b", "c", -1),
            0x13: ("d", "e", 1),
            0x1B: ("d", "e", -1),
            0x23: ("h", "l", 1),
            0x2B: ("h", "l", -1),
        }
        if opcode in pairs:
            high, low, delta = pairs[opcode]
            pair_value = state.pair(high, low)
            if pair_value is None or pair_value.value is None:
                return replace(state, **{high: None, low: None})
            value = (pair_value.value + delta) & 0xFFFF
            return replace(
                state,
                **{
                    high: Interval.exact(value >> 8),
                    low: Interval.exact(value & 0xFF),
                },
            )
        # ADD HL,rr and SP-derived HL loads.
        if opcode in {0x09, 0x19, 0x29, 0x39, 0xF8}:
            return replace(state, h=None, l=None)
        # POP replaces the complete tracked pair.
        pop_pairs = {
            0xC1: ("b", "c"),
            0xD1: ("d", "e"),
            0xE1: ("h", "l"),
            0xF1: ("a", None),
        }
        if opcode in pop_pairs:
            high, low = pop_pairs[opcode]
            changes = {high: None}
            if low is not None:
                changes[low] = None
            return replace(state, **changes)
        # CB operations either preserve registers (BIT) or replace their value.
        if opcode == 0xCB:
            cb = data[1]
            if 0x40 <= cb <= 0x7F:
                return state
            target = registers[cb & 7]
            return state if target is None else replace(state, **{target: None})
        # CP changes flags only. Other ALU operations replace A.
        if 0xB8 <= opcode <= 0xBF or opcode == 0xFE:
            return state
        if (
            0x80 <= opcode <= 0xB7
            or opcode in {0xC6, 0xCE, 0xD6, 0xDE, 0xEE, 0xF6}
            or opcode in {0x07, 0x0F, 0x17, 0x1F, 0x27, 0x2F}
        ):
            return replace(state, a=None)
        return state

    def _sink(
        self,
        state: DecoderState,
        opcode: int,
        data: bytes,
        root: str,
        path: tuple[str, ...],
    ) -> RomFinding | None:
        destination: Interval | None = None
        mechanism = ""
        if opcode == 0xE0:
            destination, mechanism = Interval.exact(0xFF00 + data[1]), "ldh-direct"
        elif opcode in {0xEA, 0x08}:
            destination = self._store_destination(state, opcode, data)
            mechanism = "direct" if opcode == 0xEA else "store-sp"
        elif opcode == 0xE2:
            destination = (
                None
                if state.c is None
                else Interval(0xFF00 + state.c.low, 0xFF00 + state.c.high)
            )
            mechanism = "ldh-c"
        elif opcode in {
            0x02,
            0x12,
            0x22,
            0x32,
            0x36,
            0x70,
            0x71,
            0x72,
            0x73,
            0x74,
            0x75,
            0x77,
        }:
            destination = self._store_destination(state, opcode, data)
            mechanism = "pointer-immediate" if opcode == 0x36 else "pointer"
        else:
            return None
        if destination is None:
            resource, resolved = "UNKNOWN_DESTINATION", False
            low = high = None
        else:
            low, high = destination.low, destination.high
            resource = _resource(low, high, self.owner_gated_ranges)
            if resource is None:
                if opcode == 0x36:
                    resource = "NON_AUDITED_DESTINATION"
                else:
                    # MBC5 bank writes are control-flow evidence, not display sinks.
                    return None
            resolved = resource != "MIXED_OR_UNKNOWN"
        vbk_low = None if state.vbk is None else state.vbk.low
        vbk_high = None if state.vbk is None else state.vbk.high
        dma_low = dma_high = None
        if low == high == 0xFF46 and state.a is not None:
            dma_low, dma_high = state.a.low << 8, state.a.high << 8
            mechanism = "dma-launch"
        return RomFinding(
            state.bank,
            state.address,
            normalize_rom_offset(state.bank, state.address),
            data.hex(),
            mechanism,
            low,
            high,
            resource,
            vbk_low,
            vbk_high,
            root,
            path,
            None,
            resolved,
            "writer",
            None,
            dma_low,
            dma_high,
        )

    def scan_executable_candidates(self) -> tuple[RomFinding, ...]:
        """Scan linked executable sections without pretending reachability."""
        self._validate_candidate_coverage()
        findings: list[RomFinding] = []
        for section in self.sections:
            tracked = self._linear_candidate_states(section)
            for address in range(section.start, section.end + 1):
                offset = normalize_rom_offset(section.bank, address)
                if self.rom[offset] not in _CANDIDATE_OPCODES:
                    continue
                opcode = self.rom[offset]
                length = OPCODE_LENGTH[opcode]
                if offset + length > len(self.rom):
                    continue
                state = tracked.get(
                    address,
                    DecoderState(
                        section.bank,
                        address,
                        section.bank if section.bank else None,
                        (section.bank & 0xFF) if section.bank else None,
                        ((section.bank >> 8) & 1) if section.bank else None,
                    ),
                )
                finding = self._sink(
                    state,
                    opcode,
                    self.rom[offset : offset + length],
                    "<candidate-scan>",
                    (section.name,),
                )
                if finding:
                    findings.append(self._with_copied_region(finding))
        return tuple(sorted(findings, key=_finding_sort_key))

    def _linear_candidate_states(self, section: MapSection) -> dict[int, DecoderState]:
        """Reconstruct only the conservative linear state within one section."""
        state = DecoderState(
            section.bank,
            section.start,
            section.bank if section.bank else None,
            (section.bank & 0xFF) if section.bank else None,
            ((section.bank >> 8) & 1) if section.bank else None,
        )
        states: dict[int, DecoderState] = {}
        while state.address <= section.end:
            states[state.address] = state
            offset = normalize_rom_offset(state.bank, state.address)
            opcode = self.rom[offset]
            length = OPCODE_LENGTH[opcode]
            if state.address + length - 1 > section.end:
                break
            data = self.rom[offset : offset + length]
            next_state = self._transfer(
                replace(state, address=state.address + length), opcode, data
            )
            finding = self._sink(
                state, opcode, data, "<candidate-scan>", (section.name,)
            )
            if (
                finding is not None
                and finding.destination_low == finding.destination_high == 0xFF4F
            ):
                next_state = replace(
                    next_state,
                    vbk=self._store_value(state, opcode, data),
                )
            if opcode in {0xC9, 0xD9, 0xC3, 0x18, 0xE9}:
                next_state = replace(
                    next_state,
                    a=None,
                    b=None,
                    c=None,
                    d=None,
                    e=None,
                    h=None,
                    l=None,
                    vbk=None,
                )
            elif opcode in {0xC4, 0xCC, 0xD4, 0xDC, 0xCD} or opcode & 0xC7 == 0xC7:
                next_state = self._call_fallthrough(next_state, state)
            state = next_state
        return states


def discover_rom(
    rom: bytes,
    symbols: SymbolTable,
    roots: Iterable[str | BankAddress],
    **kwargs: Any,
) -> RomDiscoveryReport:
    sections = kwargs.get("sections")
    if not sections:
        raise RomDiscoveryError("discover_rom requires non-empty linker ROM sections")
    return SM83Decoder(rom, symbols, **kwargs).decode(roots)


def discover_rom_batched(
    rom: bytes,
    symbols: SymbolTable,
    roots: Iterable[str | BankAddress],
    *,
    batch_size: int = 16,
    **kwargs: Any,
) -> RomDiscoveryReport:
    """Decode independent authority roots without multiplying candidate scans.

    Root identity is part of the decoder's state key because it is retained in
    every finding. A large root set can therefore make a single worklist grow
    in proportion to roots times reachable code. Bounded batches retain that
    provenance while limiting peak state and scan linked executable sections
    exactly once.
    """
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size < 1
    ):
        raise RomDiscoveryError("batch_size must be a positive integer")
    sections = kwargs.get("sections")
    if not sections:
        raise RomDiscoveryError(
            "discover_rom_batched requires non-empty linker ROM sections"
        )

    def root_key(root: str | BankAddress) -> tuple[int, int, int, str]:
        if isinstance(root, str):
            site = symbols.resolve(root)
            return site.bank, site.address, 0, root
        return root.bank, root.address, 1, ""

    ordered_roots = tuple(sorted(set(roots), key=root_key))
    if not ordered_roots:
        raise RomDiscoveryError("discover_rom_batched requires at least one root")

    decoder = SM83Decoder(rom, symbols, **kwargs)
    candidates = decoder.scan_executable_candidates()
    reports = tuple(
        decoder.decode(
            ordered_roots[start : start + batch_size],
            scan_candidates=False,
            validate_coverage=False,
        )
        for start in range(0, len(ordered_roots), batch_size)
    )
    first = reports[0]
    findings = {
        (
            finding.bank,
            finding.address,
            finding.destination_low,
            finding.destination_high,
            finding.root,
            finding.call_path,
            finding.mechanism,
            finding.category,
        ): finding
        for report in reports
        for finding in report.findings
    }
    return RomDiscoveryReport(
        tuple(sorted(findings.values(), key=_finding_sort_key)),
        tuple(
            sorted(
                {item for report in reports for item in report.unresolved_destinations}
            )
        ),
        tuple(sorted({item for report in reports for item in report.visited})),
        first.rom_sha256,
        first.sym_sha256,
        first.map_sha256,
        tuple(
            sorted(
                {item for report in reports for item in report.unresolved_control_flow}
            )
        ),
        candidates,
        decoder.sections,
    )
