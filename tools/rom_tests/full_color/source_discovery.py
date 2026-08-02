"""Deterministic RGBDS source/include discovery for Gate 0b.

This is deliberately a candidate finder rather than an assembler.  It follows
the real include graph, retains source evidence, understands labels, aliases
and macros, and marks computed destinations unresolved for mandatory review.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

_INCLUDE = re.compile(r'^\s*INCLUDE\s+"([^"]+)"', re.IGNORECASE)
_LABEL = re.compile(r"^\s*((?:[A-Za-z_][\w#.]*)|(?:\.[A-Za-z_][\w#.]*))::?\s*(.*)$")
_LOCAL_LABEL = re.compile(r"^\s*(\.[A-Za-z_][\w#.]*)(?:::?)?\s*(.*)$")
_MAP_HEADER = re.compile(r"^\s*map_header\s+([A-Za-z_][\w#.]*)\s*,", re.IGNORECASE)
_ALIAS = re.compile(
    r"^\s*(?:DEF\s+)?([A-Za-z_][\w#.]*)\s+EQU\s+"
    r"(.+?)(?:\s*;.*)?$",
    re.IGNORECASE,
)
_MACRO_BEGIN = re.compile(r"^\s*MACRO\??\s+([A-Za-z_][\w#.]*)", re.IGNORECASE)
_MACRO_END = re.compile(r"^\s*ENDM\b", re.IGNORECASE)
_STORE = re.compile(r"^\s*(ldh?|LDH?)\s+\[([^\]]+)\]\s*,\s*(.+?)(?:\s*;.*)?$")
_DIRECTIVE = re.compile(
    r";\s*@full-color\s+(scene-edge|writer|scene|lifecycle|mutation)\b(.*)$",
    re.IGNORECASE,
)
_EXPRESSION = re.compile(
    r"^\s*([A-Za-z_][\w#.]*|\$[0-9a-f]+|[0-9]+)"
    r"(?:\s*([+-])\s*(\$[0-9a-f]+|[0-9]+))?\s*$",
    re.IGNORECASE,
)
_CONTROL_FLOW = re.compile(
    r"^\s*(call|jp|jr|farcall|farjp|predef)\s+(.+?)(?:\s*;.*)?$",
    re.IGNORECASE,
)
_TABLE = re.compile(r"^\s*d[wb]\s+(.+?)(?:\s*;.*)?$", re.IGNORECASE)

REGISTER_SYMBOLS: dict[str, int] = {
    "rLCDC": 0xFF40,
    "rSTAT": 0xFF41,
    "rSCY": 0xFF42,
    "rSCX": 0xFF43,
    "rLYC": 0xFF45,
    "rDMA": 0xFF46,
    "rBGP": 0xFF47,
    "rOBP0": 0xFF48,
    "rOBP1": 0xFF49,
    "rWY": 0xFF4A,
    "rWX": 0xFF4B,
    "rVBK": 0xFF4F,
    "rHDMA1": 0xFF51,
    "rHDMA2": 0xFF52,
    "rHDMA3": 0xFF53,
    "rHDMA4": 0xFF54,
    "rHDMA5": 0xFF55,
    "rBGPI": 0xFF68,
    "rBGPD": 0xFF69,
    "rOBPI": 0xFF6A,
    "rOBPD": 0xFF6B,
    "rSVBK": 0xFF70,
}

# Exact source roots retained by the compile-time-only Phase 2 audit product.
PHASE2_HOSTILE_LIFECYCLE_ROOTS = ("EnterMap",)
PHASE2_HOSTILE_SCENE_ROOTS = (
    "DisplayPartyMenu",
    "DisplayStartMenu",
    "DisplayTextID",
    "PalletTown_h",
    "PartyMenuInit",
    "RestoreScreenTilesAndReloadTilePatterns",
    "Route1_h",
    "StartMenu_Pokemon.exitMenu",
)
PHASE2_HOSTILE_MUTATION_ROOTS = (
    "AutoBgMapTransfer",
    "DMARoutine",
    "LoadGBPal",
    "LoadMapData",
    "LoadNorthSouthConnectionsTileMap",
    "PrepareOAMData",
    "RedrawRowOrColumn",
    "ScheduleEastColumnRedraw",
    "ScheduleNorthRowRedraw",
    "ScheduleSouthRowRedraw",
    "ScheduleWestColumnRedraw",
    "TransferBGPPals",
    "UpdateMovingBgTiles",
)


def _resource(address: int) -> str | None:
    if 0xFF40 <= address <= 0xFF4B:
        return "DISPLAY_REGISTER"
    if address == 0xFF4F:
        return "VRAM_BANK"
    if 0xFF51 <= address <= 0xFF55:
        return "HDMA_GDMA"
    if 0xFF68 <= address <= 0xFF6B:
        return "CGB_PALETTE"
    if address == 0xFF70:
        return "WRAM_BANK"
    if 0x9800 <= address <= 0x9FFF:
        return "BG_WINDOW_MAP"
    if 0xFE00 <= address <= 0xFE9F:
        return "HARDWARE_OAM"
    return None


@dataclass(frozen=True, order=True, slots=True)
class SourceFinding:
    category: str
    path: str
    line: int
    symbol: str
    mechanism: str
    destination: str
    resource: str
    aliases: tuple[str, ...] = ()
    object: str | None = None
    owner_gate: str | None = None
    resolved: bool = True
    evidence_sha256: str = ""
    row_kind: str | None = None
    direction: str | None = None
    destination_path: str | None = None
    destination_line: int | None = None
    condition: str | None = None

    @property
    def site_key(self) -> tuple[str, int, str]:
        return self.path, self.line, self.symbol

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "path": self.path,
            "line": self.line,
            "symbol": self.symbol,
            "mechanism": self.mechanism,
            "destination": self.destination,
            "resource": self.resource,
            "aliases": list(self.aliases),
            "object": self.object,
            "owner_gate": self.owner_gate,
            "resolved": self.resolved,
            "evidence_sha256": self.evidence_sha256,
            "row_kind": self.row_kind,
            "direction": self.direction,
            "destination_path": self.destination_path,
            "destination_line": self.destination_line,
            "condition": self.condition,
        }


@dataclass(frozen=True, slots=True)
class SourceDiscoveryReport:
    roots: tuple[str, ...]
    include_graph: tuple[tuple[str, tuple[str, ...]], ...]
    findings: tuple[SourceFinding, ...]
    errors: tuple[str, ...]
    source_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "full-color-source-discovery-v1",
            "source_sha256": self.source_sha256,
            "roots": list(self.roots),
            "include_graph": {
                path: list(children) for path, children in self.include_graph
            },
            "findings": [finding.to_dict() for finding in self.findings],
            "errors": list(self.errors),
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


@dataclass(frozen=True, slots=True)
class _ParsedFile:
    path: str
    lines: tuple[str, ...]
    labels: tuple[tuple[int, str], ...]
    aliases: tuple[tuple[str, str], ...]
    macros: tuple[tuple[str, tuple[str, ...]], ...]


class SourceDiscoverer:
    """Follow RGBDS includes and find owner-sensitive sink candidates."""

    def __init__(
        self,
        repository: str | Path,
        *,
        owner_gates: Mapping[str, str] | None = None,
        object_paths: Mapping[str, str] | None = None,
        lifecycle_roots: Iterable[str] = (),
        scene_roots: Iterable[str] = (),
        mutation_roots: Iterable[str] = (),
        lifecycle_sinks: Iterable[str] = (),
        scene_sinks: Iterable[str] = (),
        mutation_sinks: Iterable[str] = (),
        scene_edge_classifications: Mapping[
            tuple[str, str], tuple[str, str]
        ] | None = None,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.owner_gates = dict(owner_gates or {})
        self.object_paths = dict(object_paths or {})
        self.lifecycle_roots = frozenset(lifecycle_roots)
        self.scene_roots = frozenset(scene_roots)
        self.mutation_roots = frozenset(mutation_roots)
        self.lifecycle_sinks = frozenset(lifecycle_sinks)
        self.scene_sinks = frozenset(scene_sinks)
        self.mutation_sinks = frozenset(mutation_sinks)
        self.scene_edge_classifications = dict(scene_edge_classifications or {})

    def discover(self, roots: Iterable[str | Path]) -> SourceDiscoveryReport:
        root_names = tuple(
            sorted(self._relative(self._resolve_root(root)) for root in roots)
        )
        graph: dict[str, list[str]] = defaultdict(list)
        parsed: dict[str, _ParsedFile] = {}
        source_blobs: dict[str, bytes] = {}
        errors: list[str] = []
        queue = deque(root_names)
        while queue:
            name = queue.popleft()
            if name in parsed:
                continue
            path = self.repository / name
            if not path.is_file():
                errors.append(f"{name}: included source does not exist")
                continue
            blob = path.read_bytes()
            try:
                text = blob.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{name}: source is not valid UTF-8")
                continue
            source_blobs[name] = blob
            item = self._parse_file(name, text)
            parsed[name] = item
            for line_number, line in enumerate(item.lines, 1):
                match = _INCLUDE.match(line)
                if not match:
                    continue
                child = self._include_name(name, match.group(1))
                graph[name].append(child)
                queue.append(child)
            graph[name] = sorted(set(graph[name]))

        aliases: dict[str, set[str]] = defaultdict(set)
        constants: dict[str, int] = {}
        macros: dict[str, tuple[str, ...]] = {}
        for item in parsed.values():
            for left, right in item.aliases:
                expression = _EXPRESSION.fullmatch(right)
                if expression and (
                    expression.group(1).startswith("$") or expression.group(1).isdigit()
                ):
                    base = (
                        int(expression.group(1)[1:], 16)
                        if expression.group(1).startswith("$")
                        else int(expression.group(1))
                    )
                    delta = self._expression_delta(expression)
                    constants[left] = (base + delta) & 0xFFFF
                elif expression:
                    target = expression.group(1)
                    aliases[left].add(target)
                    aliases[target].add(left)
            for name, body in item.macros:
                macros[name.lower()] = body
        changed = True
        while changed:
            changed = False
            for item in parsed.values():
                for left, right in item.aliases:
                    expression = _EXPRESSION.fullmatch(right)
                    if (
                        left not in constants
                        and expression
                        and (
                            expression.group(1) in constants
                            or expression.group(1) in REGISTER_SYMBOLS
                        )
                    ):
                        constants[left] = (
                            (
                                constants[expression.group(1)]
                                if expression.group(1) in constants
                                else REGISTER_SYMBOLS[expression.group(1)]
                            )
                            + self._expression_delta(expression)
                        ) & 0xFFFF
                        changed = True

        findings: list[SourceFinding] = []
        self._symbol_locations = {}
        for item in parsed.values():
            current_global = "<top-level>"
            for line, label in item.labels:
                if label.startswith("."):
                    qualified = current_global + label
                else:
                    current_global = qualified = label
                self._symbol_locations[qualified] = (item.path, line)
        for name in sorted(parsed):
            findings.extend(
                self._find_in_file(parsed[name], aliases, macros, constants)
            )
        findings = sorted(set(findings))
        for finding in findings:
            if not finding.resolved and finding.resource == "COMPUTED_CONTROL_FLOW":
                errors.append(
                    f"{finding.path}:{finding.line}:{finding.symbol}: "
                    f"unresolved {finding.mechanism} destination "
                    f"{finding.destination}"
                )
            elif (
                not finding.resolved
                and finding.category == "scene_edge"
                and finding.resource == "CONTROL_FLOW"
            ):
                errors.append(
                    f"{finding.path}:{finding.line}:{finding.symbol}: "
                    f"unclassified scene edge to {finding.destination}"
                )
        defined = set(self._symbol_locations)
        discovered_control_roots = {
            finding.symbol
            for finding in findings
            if finding.category in {"lifecycle", "scene", "scene_edge", "mutation"}
        }
        for symbol in sorted(
            ((self.lifecycle_roots | self.scene_roots | self.mutation_roots) & defined)
            - discovered_control_roots
        ):
            errors.append(
                f"configured control-flow root {symbol!r} produced no "
                "lifecycle/scene/mutation finding"
            )
        configured = (
            self.lifecycle_roots
            | self.scene_roots
            | self.mutation_roots
            | self.lifecycle_sinks
            | self.scene_sinks
            | self.mutation_sinks
        )
        for symbol in sorted(configured - defined):
            errors.append(
                f"configured lifecycle/scene/mutation symbol {symbol!r} was not discovered"
            )
        source_digest = hashlib.sha256()
        for name in sorted(parsed):
            source_digest.update(name.encode("utf-8"))
            source_digest.update(b"\0")
            source_digest.update(source_blobs[name])
            source_digest.update(b"\0")
        return SourceDiscoveryReport(
            root_names,
            tuple((name, tuple(graph.get(name, ()))) for name in sorted(parsed)),
            tuple(findings),
            tuple(sorted(set(errors))),
            source_digest.hexdigest(),
        )

    @staticmethod
    def _expression_delta(match: re.Match[str]) -> int:
        if match.group(2) is None:
            return 0
        raw = match.group(3)
        value = int(raw[1:], 16) if raw.startswith("$") else int(raw)
        return value if match.group(2) == "+" else -value

    def _resolve_root(self, value: str | Path) -> Path:
        path = Path(value)
        return (
            path.resolve() if path.is_absolute() else (self.repository / path).resolve()
        )

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.repository).as_posix()
        except ValueError as exc:
            raise ValueError(f"{path}: source escapes repository") from exc

    def _include_name(self, including: str, requested: str) -> str:
        # RGBDS projects conventionally resolve includes at the repository root.
        root_candidate = (self.repository / requested).resolve()
        local_candidate = (
            (self.repository / including).parent.joinpath(requested).resolve()
        )
        candidate = root_candidate if root_candidate.exists() else local_candidate
        return self._relative(candidate)

    @staticmethod
    def _parse_file(name: str, text: str) -> _ParsedFile:
        lines = tuple(text.splitlines())
        labels: list[tuple[int, str]] = []
        aliases: list[tuple[str, str]] = []
        macros: list[tuple[str, tuple[str, ...]]] = []
        macro_name: str | None = None
        macro_body: list[str] = []
        for number, line in enumerate(lines, 1):
            if macro_name:
                if _MACRO_END.match(line):
                    macros.append((macro_name, tuple(macro_body)))
                    macro_name, macro_body = None, []
                else:
                    macro_body.append(line)
                continue
            match = _MACRO_BEGIN.match(line)
            if match:
                macro_name = match.group(1)
                continue
            match = _LABEL.match(line)
            if match:
                labels.append((number, match.group(1)))
            elif match := _LOCAL_LABEL.match(line):
                labels.append((number, match.group(1)))
            elif match := _MAP_HEADER.match(line):
                labels.append((number, match.group(1) + "_h"))
            match = _ALIAS.match(line)
            if match:
                aliases.append((match.group(1), match.group(2)))
        return _ParsedFile(name, lines, tuple(labels), tuple(aliases), tuple(macros))

    def _find_in_file(
        self,
        item: _ParsedFile,
        aliases: Mapping[str, set[str]],
        macros: Mapping[str, tuple[str, ...]],
        constants: Mapping[str, int],
    ) -> list[SourceFinding]:
        findings: list[SourceFinding] = []
        current_global = "<top-level>"
        current_symbol = current_global
        in_macro = False
        for number, line in enumerate(item.lines, 1):
            if _MACRO_BEGIN.match(line):
                in_macro = True
                continue
            if in_macro:
                if _MACRO_END.match(line):
                    in_macro = False
                continue
            instruction = line
            label = _LABEL.match(line)
            if label is None and (local := _LOCAL_LABEL.match(line)):
                # Every local label begins a new lexical scope.  Configuration
                # controls evidence emission, never where the previous root ends.
                label = local
            if label is None and (map_header := _MAP_HEADER.match(line)):
                # map_header emits a real linked <Map>_h symbol.
                synthetic = map_header.group(1) + "_h"
                if synthetic in self.scene_roots:
                    findings.append(
                        self._finding(
                            item.path, number, synthetic, "scene", "configured-root",
                            synthetic, "SCENE_BOUNDARY", aliases, line,
                            resolved=True, row_kind="DIRECTED_EDGE",
                        )
                    )
            if label:
                raw = label.group(1)
                if raw.startswith("."):
                    current_symbol = current_global + raw
                else:
                    current_global = current_symbol = raw
                instruction = label.group(2)
                if current_symbol in self.lifecycle_roots:
                    findings.append(
                        self._finding(
                            item.path,
                            number,
                            current_symbol,
                            "lifecycle",
                            "configured-root",
                            current_symbol,
                            "LIFECYCLE",
                            aliases,
                            line,
                            resolved=True,
                            row_kind="LIFECYCLE",
                        )
                    )
                elif current_symbol in self.scene_roots:
                    findings.append(
                        self._finding(
                            item.path,
                            number,
                            current_symbol,
                            "scene",
                            "configured-root",
                            current_symbol,
                            "SCENE_BOUNDARY",
                            aliases,
                            line,
                            resolved=True,
                            row_kind="DIRECTED_EDGE",
                        )
                    )
                elif current_symbol in self.mutation_roots:
                    findings.append(
                        self._finding(
                            item.path,
                            number,
                            current_symbol,
                            "mutation",
                            "configured-root",
                            current_symbol,
                            "MUTATION",
                            aliases,
                            line,
                            resolved=True,
                        )
                    )
                if not instruction or instruction.lstrip().startswith(";"):
                    continue
            directive = _DIRECTIVE.search(instruction)
            if directive:
                category = directive.group(1).lower().replace("-", "_")
                fields = self._directive_fields(directive.group(2))
                findings.append(
                    self._finding(
                        item.path,
                        number,
                        current_symbol,
                        category,
                        fields.get("mechanism", "annotation"),
                        fields.get("destination", fields.get("to", "annotated")),
                        fields.get("resource", category.upper()),
                        aliases,
                        line,
                        resolved=(
                            category != "scene_edge"
                            or (
                                fields.get("row_kind") is not None
                                and fields.get("direction") is not None
                            )
                        ),
                        row_kind=fields.get(
                            "row_kind",
                            "LIFECYCLE" if category == "lifecycle" else None,
                        ),
                        direction=fields.get("direction"),
                    )
                )
                continue
            store = _STORE.match(instruction)
            if store:
                finding = self._store_finding(
                    item.path,
                    number,
                    current_symbol,
                    store.group(2).strip(),
                    aliases,
                    constants,
                    line,
                    "direct",
                )
                if finding:
                    findings.append(finding)
                continue
            control = _CONTROL_FLOW.match(instruction)
            if control:
                findings.append(
                    self._control_flow_finding(
                        item.path,
                        number,
                        current_symbol,
                        control.group(1).lower(),
                        control.group(2).strip(),
                        aliases,
                        line,
                    )
                )
                continue
            table = _TABLE.match(instruction)
            if table and self._is_configured_control_symbol(current_symbol):
                for destination in (part.strip() for part in table.group(1).split(",")):
                    findings.append(
                        self._control_flow_finding(
                            item.path,
                            number,
                            current_symbol,
                            "table",
                            destination,
                            aliases,
                            line,
                        )
                    )
                continue
            token = (
                instruction.strip().split(None, 1)[0].lower()
                if instruction.strip()
                else ""
            )
            if token in macros:
                args = [
                    part.strip()
                    for part in instruction.strip()[len(token) :].split(",")
                ]
                for destination, expansion in self._expand_macro_stores(
                    token, args, macros
                ):
                    finding = self._store_finding(
                        item.path,
                        number,
                        current_symbol,
                        destination,
                        aliases,
                        constants,
                        line,
                        f"macro:{expansion}",
                    )
                    if finding:
                        findings.append(finding)
        return findings

    def _is_configured_control_symbol(self, symbol: str) -> bool:
        return symbol in (self.lifecycle_roots | self.scene_roots | self.mutation_roots)

    def _configured_category(self, symbol: str, destination: str = "") -> str:
        if symbol in self.mutation_roots or destination in self.mutation_sinks:
            return "mutation"
        if (
            (symbol, destination) in self.scene_edge_classifications
            or destination in self.scene_sinks
        ):
            return "scene_edge"
        if symbol in self.scene_roots:
            return "control_flow" if self.scene_edge_classifications else "scene_edge"
        return "lifecycle"

    def _control_flow_finding(
        self,
        path: str,
        line: int,
        symbol: str,
        mechanism: str,
        raw_destination: str,
        aliases: Mapping[str, set[str]],
        evidence: str,
    ) -> SourceFinding:
        conditional = re.fullmatch(
            r"\s*(nz|z|nc|c)\s*,\s*(.+?)\s*", raw_destination, re.IGNORECASE
        )
        condition = conditional.group(1).lower() if conditional else None
        destination = (
            conditional.group(2).strip()
            if conditional
            else raw_destination.split(",", 1)[0].strip()
        )
        computed = (
            destination.lower() in {"hl", "de", "bc"}
            or destination.startswith("[")
            or "\\" in destination
        )
        category = self._configured_category(symbol, destination)
        configured_edge = self._is_configured_control_symbol(symbol) or destination in (
            self.lifecycle_sinks | self.scene_sinks | self.mutation_sinks
        )
        resolved = not computed and configured_edge
        row_kind = direction = None
        if category == "scene_edge":
            # Discovery proves an edge exists, but root/sink membership alone
            # cannot invent its ownership-transfer direction.
            classification = self.scene_edge_classifications.get((symbol, destination))
            if classification is None:
                resolved = False
            else:
                row_kind, direction = classification
        return self._finding(
            path,
            line,
            symbol,
            category if configured_edge else "control_flow",
            mechanism,
            destination,
            "COMPUTED_CONTROL_FLOW" if computed else "CONTROL_FLOW",
            aliases,
            evidence,
            resolved=resolved,
            condition=condition,
            row_kind=row_kind,
            direction=direction,
        )

    @classmethod
    def _expand_macro_stores(
        cls,
        token: str,
        args: list[str],
        macros: Mapping[str, tuple[str, ...]],
        *,
        stack: tuple[str, ...] = (),
    ) -> list[tuple[str, str]]:
        """Expand nested RGBDS macros just far enough to expose stores."""
        if token in stack:
            return []
        if len(stack) >= 16:
            return []
        stores: list[tuple[str, str]] = []
        for template in macros[token]:
            expanded = template
            for index, arg in enumerate(args, 1):
                expanded = expanded.replace(f"\\{index}", arg)
            if store := _STORE.match(expanded):
                stores.append((store.group(2).strip(), ">".join(stack + (token,))))
                continue
            stripped = expanded.strip()
            nested = stripped.split(None, 1)[0].lower() if stripped else ""
            if nested not in macros:
                continue
            nested_args = [part.strip() for part in stripped[len(nested) :].split(",")]
            stores.extend(
                cls._expand_macro_stores(
                    nested, nested_args, macros, stack=stack + (token,)
                )
            )
        return stores

    @staticmethod
    def _directive_fields(text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for match in re.finditer(r"([a-z_]+)=([^\s]+)", text, re.IGNORECASE):
            fields[match.group(1).lower()] = match.group(2)
        return fields

    def _store_finding(
        self,
        path: str,
        line_number: int,
        symbol: str,
        destination: str,
        aliases: Mapping[str, set[str]],
        constants: Mapping[str, int],
        evidence: str,
        mechanism: str,
    ) -> SourceFinding | None:
        normalized = destination.replace(" ", "")
        address = self._evaluate_expression(normalized, constants)
        if address is not None:
            resource = _resource(address)
            if resource is None:
                return None
            return self._finding(
                path,
                line_number,
                symbol,
                "writer",
                mechanism,
                f"{address:04x}",
                resource,
                aliases,
                evidence,
                resolved=True,
            )
        lower = normalized.lower()
        if lower == "c":
            return self._finding(
                path,
                line_number,
                symbol,
                "writer",
                "ldh-c",
                "ff00+c",
                "COMPUTED_HIGH_MEMORY",
                aliases,
                evidence,
                resolved=False,
            )
        if lower in {"hl", "hli", "hld", "de", "bc"} or "\\" in lower:
            return self._finding(
                path,
                line_number,
                symbol,
                "writer",
                "pointer",
                normalized,
                "COMPUTED_POINTER",
                aliases,
                evidence,
                resolved=False,
            )
        # Symbolic destinations may alias any of the audited ranges.  Retain
        # likely display/OAM/DMA names and require object/ROM reconciliation.
        if re.search(
            r"(vram|bgmap|tilemap|oam|dma|palette|attr|lcdc|vbk)", normalized, re.I
        ):
            return self._finding(
                path,
                line_number,
                symbol,
                "writer",
                "symbolic",
                normalized,
                "SYMBOLIC_SINK",
                aliases,
                evidence,
                resolved=False,
            )
        return None

    @staticmethod
    def _evaluate_expression(
        expression: str, constants: Mapping[str, int]
    ) -> int | None:
        match = _EXPRESSION.fullmatch(expression)
        if not match:
            return None
        base_name = match.group(1)
        if base_name in REGISTER_SYMBOLS:
            base = REGISTER_SYMBOLS[base_name]
        elif base_name in constants:
            base = constants[base_name]
        elif base_name.startswith("$"):
            base = int(base_name[1:], 16)
        elif base_name.isdigit():
            base = int(base_name)
        else:
            return None
        return (base + SourceDiscoverer._expression_delta(match)) & 0xFFFF

    def _finding(
        self,
        path: str,
        line: int,
        symbol: str,
        category: str,
        mechanism: str,
        destination: str,
        resource: str,
        aliases: Mapping[str, set[str]],
        evidence: str,
        *,
        resolved: bool,
        row_kind: str | None = None,
        direction: str | None = None,
        condition: str | None = None,
    ) -> SourceFinding:
        alias_names = tuple(sorted(aliases.get(symbol, set())))
        owner = self.owner_gates.get(symbol)
        if owner is None and "." in symbol:
            owner = self.owner_gates.get(symbol.split(".", 1)[0])
        object_path = self.object_paths.get(path)
        digest = hashlib.sha256(
            f"{path}\0{line}\0{evidence.rstrip()}".encode("utf-8")
        ).hexdigest()
        destination_location = getattr(self, "_symbol_locations", {}).get(destination)
        return SourceFinding(
            category,
            path,
            line,
            symbol,
            mechanism,
            destination,
            resource,
            alias_names,
            object_path,
            owner,
            resolved,
            digest,
            row_kind,
            direction,
            None if destination_location is None else destination_location[0],
            None if destination_location is None else destination_location[1],
            condition,
        )


def discover_sources(
    repository: str | Path,
    roots: Iterable[str | Path],
    *,
    owner_gates: Mapping[str, str] | None = None,
    object_paths: Mapping[str, str] | None = None,
    lifecycle_roots: Iterable[str] = (),
    scene_roots: Iterable[str] = (),
    mutation_roots: Iterable[str] = (),
    lifecycle_sinks: Iterable[str] = (),
    scene_sinks: Iterable[str] = (),
    mutation_sinks: Iterable[str] = (),
    scene_edge_classifications: Mapping[
        tuple[str, str], tuple[str, str]
    ] | None = None,
) -> SourceDiscoveryReport:
    lifecycle_roots = tuple(lifecycle_roots)
    scene_roots = tuple(scene_roots)
    mutation_roots = tuple(mutation_roots)
    return SourceDiscoverer(
        repository,
        owner_gates=owner_gates,
        object_paths=object_paths,
        lifecycle_roots=lifecycle_roots,
        scene_roots=scene_roots,
        mutation_roots=mutation_roots,
        lifecycle_sinks=lifecycle_sinks,
        scene_sinks=scene_sinks,
        mutation_sinks=mutation_sinks,
        scene_edge_classifications=scene_edge_classifications,
    ).discover(roots)
