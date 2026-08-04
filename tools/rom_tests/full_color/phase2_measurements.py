"""Measure and select the bounded Phase 2 hostile-slice representation.

The decision is derived from both release and debug linker products.  The
descriptor layout and the bounded hostile scenario are source authorities;
addresses and capacities are measurements.  Nothing in this module activates
the Phase 2 runtime.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from dataclasses import replace
from functools import lru_cache
import gc
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .baseline_discovery import (
    COPIED_REGIONS,
    DMA_CONTROL_LABELS,
    FARCALL_LABELS,
    SHADOW_OAM_RANGES,
    SOURCE_ROOTS,
    load_predef_targets,
    discover_baseline_rom,
    discover_baseline_sources,
)
from .baseline_inventory import (
    _PLANNED_ONLY_ROW_CONTRACTS,
    _phase2_transition_state,
    _reviewed_rom_view,
    _reviewed_source_view,
    _validate_planned_rows,
)
from .discovery_review import (
    rom_finding_subject,
    source_error_subject,
    source_finding_subject,
)
from .discovery_assignment import (
    DEBUG_PRODUCT,
    DiscoveryAssignmentAuthority,
    NORMAL_DEBUG_PRODUCT,
    NORMAL_PRODUCT,
    PHASE2_AUDIT_PRODUCT,
    PRODUCTION_PRODUCTS,
    StaleDiscoveryAssignmentError,
    VC_PRODUCT,
)
from .inventory import MutationInventory, SceneInventory, WriterInventory
from .phase1_measurements import (
    FORBIDDEN_ROM_BANKS,
    MINIMUM_STACK_MARGIN,
    PHASE1_STATE_BYTES,
)
from .rom_discovery import discover_rom_batched, load_map, load_sym, normalize_rom_offset
from .source_discovery import (
    PHASE2_HOSTILE_LIFECYCLE_ROOTS,
    PHASE2_HOSTILE_MUTATION_ROOTS,
    PHASE2_HOSTILE_SCENE_ROOTS, SourceDiscoveryReport, discover_sources,
)


SCHEMA = "full-color-phase2-hostile-slice-representation-v1"
MEASUREMENT_IDENTITY = "full-color-phase2-link-measurement-v1"
AUDIT_GUARD = "PHASE2_AUDIT"
AUDIT_MARKER = b"P2AUDIT1"
PRODUCT_ARTIFACTS = {
    NORMAL_PRODUCT: "pokeyellow",
    DEBUG_PRODUCT: "pokeyellow_debug",
    VC_PRODUCT: "pokeyellow_vc",
    PHASE2_AUDIT_PRODUCT: "pokeyellow_phase2_audit",
}
DEFINITION_PATH = "specs/full-colors/definitions/phase2-hostile-slice-representation.json"
SOURCE_TRANSITION_PATH = "specs/full-colors/definitions/phase1-audit-source-transition.json"
PLANNED_SUBJECTS_PATH = "specs/full-colors/definitions/phase2-planned-subjects.json"

PLANNED_ONLY_DISPOSITION_ROWS = frozenset()

PHASE2_SCENE_EDGE_CLASSIFICATIONS = {
    ("DisplayPartyMenu", "PartyMenuInit"): ("DIRECTED_EDGE", "MAP_TO_YELLOW"),
    (
        "StartMenu_Pokemon.exitMenu",
        "RestoreScreenTilesAndReloadTilePatterns",
    ): ("DIRECTED_EDGE", "YELLOW_TO_YELLOW"),
}

_CLOSED_SCENE_DIRECTIONS = {
    ("DisplayPartyMenu", "PartyMenuInit"): "YELLOW_TO_YELLOW",
    (
        "StartMenu_Pokemon.exitMenu",
        "RestoreScreenTilesAndReloadTilePatterns",
    ): "YELLOW_TO_YELLOW",
}

_CLOSED_PALETTE_ROW_CONTRACT = {
    "commit_unit": "PALETTE",
    "resources": (
        {
            "aliases": [],
            "end": 0xFF69,
            "resource": "CGB_PALETTE",
            "start": 0xFF68,
            "vram_bank": None,
        },
    ),
    "roots": (
        "PassiveFullColorCommitPalettes",
        "PassiveFullColorHomogenizeBGPalettes",
    ),
}

_PASSIVE_REQUIRED_EDGES = (
    ("LoadMapData", "RunPaletteCommand"),
    ("LoadMapData", "PassiveFullColorApplyMap"),
    ("CheckMapConnections.loadNewMap", "RunPaletteCommand"),
    ("CheckMapConnections.loadNewMap", "PassiveFullColorApplyMap"),
    ("PassiveFullColorApplyMap.apply", "PassiveFullColorCommitPalettes"),
    (
        "PassiveFullColorApplyMap.apply",
        "PassiveFullColorCommitVisibleAttributes",
    ),
    ("PassiveFullColorVBlank.slice", "PassiveFullColorCommitRedrawRow"),
    ("PassiveFullColorVBlank.slice", "PassiveFullColorCommitRedrawColumn"),
    ("PassiveFullColorVBlank.inactive", "PassiveFullColorHomogenizeBGPalettes"),
    ("PassiveFullColorVBlank.bounded_clear", "PassiveFullColorClearBGMapChunk"),
    ("DisplayPartyMenu", "PartyMenuInit"),
    (
        "StartMenu_Pokemon.exitMenu",
        "RestoreScreenTilesAndReloadTilePatterns",
    ),
    ("StartMenu_Pokemon.exitMenu", "LoadGBPal"),
    ("DisplayTextID.skipSpriteHandling", "PrintText_NoCreatingTextBox"),
    ("DisplayStartMenu", "FullColorDisplayStartMenu"),
    ("FullColorStartMenuReveal", "PrintSafariZoneSteps"),
    ("FullColorHandleStartMenuInput", "HandleMenuInput"),
    ("FullColorPlaceUnfilledStartMenuCursor", "PlaceUnfilledArrowMenuCursor"),
    ("PrepareOAMData.spriteusesOBP0", "MapFullColorOAMAttributeFar"),
)

_PASSIVE_REQUIRED_WRITERS = {
    "PassiveFullColorCommitPalettes": frozenset({"CGB_PALETTE"}),
    "PassiveFullColorCommitVisibleAttributes": frozenset(
        {"VRAM_BANK", "COMPUTED_POINTER"}
    ),
    "PassiveFullColorCommitRedrawColumn": frozenset(
        {"VRAM_BANK", "COMPUTED_POINTER"}
    ),
    "PassiveFullColorCommitRedrawRow": frozenset(
        {"VRAM_BANK", "COMPUTED_POINTER"}
    ),
    "PassiveFullColorHomogenizeBGPalettes": frozenset({"CGB_PALETTE"}),
    "PassiveFullColorClearBGMapChunk": frozenset(
        {"VRAM_BANK", "COMPUTED_POINTER"}
    ),
}

_FORBIDDEN_PRODUCTION_DESTINATIONS = frozenset({
    "BeginFullColorMapEntry",
    "EnqueueFullColorStartMenuOverlay",
    "EnqueueFullColorWindowTileMapOverlayFar",
    "EnsureFullColorPartyHandoff",
    "EnsureFullColorPartyMenuYellow",
    "EnterFullColorOverlay",
    "FullColorAuditBeginBoundedMapEntry",
    "FullColorAuditLoadMapData",
    "FullColorVBlankOwnerConsumed",
    "PrepareFullColorOAMDataForOwnedVBlank",
    "ReturnFullColorFromParty",
    "RunFullColorOwnershipVBlank",
})

_PRODUCTION_INTEGRATION_SYMBOLS = frozenset({
    "CheckMapConnections.loadNewMap",
    "FullColorDisplayStartMenu",
    "FullColorHandleStartMenuInput",
    "FullColorPlaceUnfilledStartMenuCursor",
    "FullColorStartMenuReveal",
})

# Each root maps its control/entry evidence first and its concrete writer
# evidence second.  This keeps duplicate inventory rows distinct without ever
# listing one canonical subject under more than one planned row.
PHASE2_ROOT_ROWS = {
    "AutoBgMapTransfer": ("MU-P2-START-MENU-OVERLAY", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "DMARoutine": ("WR-P2-YELLOW-OAM-DMA", "WR-P2-YELLOW-OAM-DMA"),
    "DisplayPartyMenu": ("SC-P2-PARTY-ENTRY", "SC-P2-PARTY-ENTRY"),
    "DisplayStartMenu": ("MU-P2-START-MENU-OVERLAY", "MU-P2-START-MENU-OVERLAY"),
    "DisplayTextID": ("MU-P2-DIALOGUE-OVERLAY", "MU-P2-DIALOGUE-OVERLAY"),
    "EnterMap": ("MU-P2-MAP-RECONSTRUCTION", "MU-P2-MAP-RECONSTRUCTION"),
    "LoadGBPal": ("MU-P2-PALETTE-PAYLOADS", "MU-P2-PALETTE-PAYLOADS"),
    "LoadMapData": ("MU-P2-MAP-RECONSTRUCTION", "MU-P2-MAP-RECONSTRUCTION"),
    "LoadNorthSouthConnectionsTileMap": ("MU-P2-MAP-CONNECTION-NORTH", "MU-P2-MAP-CONNECTION-NORTH"),
    "PassiveFullColorApplyMap": ("MU-P2-MAP-RECONSTRUCTION", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorClearBGMapAttributes": ("WR-P2-YELLOW-OVERLAY-TRANSFER", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorClearBGMapChunk": ("WR-P2-YELLOW-OVERLAY-TRANSFER", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorCommitPalettes": ("MU-P2-PALETTE-PAYLOADS", "WR-P2-YELLOW-BG-PALETTE"),
    "PassiveFullColorCommitRedrawColumn": ("MU-P2-MOVEMENT-HORIZONTAL", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorCommitRedrawRow": ("MU-P2-MOVEMENT-VERTICAL", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorCommitVisibleAttributes": ("MU-P2-MAP-RECONSTRUCTION", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorHandleConnection": ("MU-P2-MAP-CONNECTION-NORTH", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PassiveFullColorHomogenizeBGPalettes": ("MU-P2-PALETTE-PAYLOADS", "WR-P2-YELLOW-BG-PALETTE"),
    "PassiveFullColorVBlank": ("WR-P2-YELLOW-MAP-STREAM", "WR-P2-YELLOW-OVERLAY-TRANSFER"),
    "PalletTown_h": ("SC-P2-PALLET-ROUTE1-NORTH", "SC-P2-PALLET-ROUTE1-NORTH"),
    "PartyMenuInit": ("SC-P2-PARTY-ENTRY", "SC-P2-PARTY-ENTRY"),
    "PrepareOAMData": ("MU-P2-OAM-FOLLOWER-NPC", "WR-P2-YELLOW-OAM-BUILD"),
    "RedrawRowOrColumn": ("WR-P2-YELLOW-MAP-STREAM", "WR-P2-YELLOW-MAP-STREAM"),
    "RestoreScreenTilesAndReloadTilePatterns": ("SC-P2-PARTY-RETURN", "SC-P2-PARTY-RETURN"),
    "Route1_h": ("SC-P2-PALLET-ROUTE1-NORTH", "SC-P2-PALLET-ROUTE1-NORTH"),
    "ScheduleEastColumnRedraw": ("MU-P2-MOVEMENT-HORIZONTAL", "MU-P2-MOVEMENT-HORIZONTAL"),
    "ScheduleNorthRowRedraw": ("MU-P2-MOVEMENT-VERTICAL", "MU-P2-MOVEMENT-VERTICAL"),
    "ScheduleSouthRowRedraw": ("MU-P2-MOVEMENT-VERTICAL", "MU-P2-MOVEMENT-VERTICAL"),
    "ScheduleWestColumnRedraw": ("MU-P2-MOVEMENT-HORIZONTAL", "MU-P2-MOVEMENT-HORIZONTAL"),
    "StartMenu_Pokemon.exitMenu": ("SC-P2-PARTY-RETURN", "SC-P2-PARTY-RETURN"),
    "TransferBGPPals": ("MU-P2-PALETTE-PAYLOADS", "WR-P2-YELLOW-BG-PALETTE"),
    "UpdateMovingBgTiles": ("MU-P2-ANIMATED-TERRAIN", "WR-P2-YELLOW-ANIMATION-TILES"),
}

MINIMUM_ROM_BYTES = 0x1000
WRAMX_START, WRAMX_END = 0xD000, 0xDFFF
SRAM_START, SRAM_END = 0xA000, 0xBFFF
ROMX_START, ROMX_END = 0x4000, 0x7FFF

_BANK = re.compile(r"^([A-Z0-9]+) bank #(\d+):$")
_SECTION = re.compile(
    r'^\s*SECTION: \$([0-9a-fA-F]{4})(?:-\$([0-9a-fA-F]{4}))? '
    r'\(\$([0-9a-fA-F]{4}) bytes?\) \["([^"]+)"\]$'
)
_SYMBOL = re.compile(r"^([0-9a-fA-F]+):([0-9a-fA-F]{4}) (\S+)$")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

PHASE2_PLANNED_ROW_IDS = frozenset(
    {
        "MU-P2-ANIMATED-TERRAIN", "MU-P2-DIALOGUE-OVERLAY",
        "MU-P2-MAP-CONNECTION-NORTH", "MU-P2-MAP-RECONSTRUCTION",
        "MU-P2-MOVEMENT-HORIZONTAL", "MU-P2-MOVEMENT-VERTICAL",
        "MU-P2-OAM-FOLLOWER-NPC", "MU-P2-PALETTE-PAYLOADS",
        "MU-P2-START-MENU-OVERLAY", "SC-P2-PALLET-ROUTE1-NORTH",
        "SC-P2-PARTY-ENTRY", "SC-P2-PARTY-RETURN",
        "WR-P2-YELLOW-ANIMATION-TILES", "WR-P2-YELLOW-BG-PALETTE",
        "WR-P2-YELLOW-MAP-STREAM", "WR-P2-YELLOW-OAM-BUILD",
        "WR-P2-YELLOW-OAM-DMA", "WR-P2-YELLOW-OVERLAY-TRANSFER",
    }
)

RESOURCE_VOCABULARY = frozenset(
    {"ATTRIBUTES", "BG_MAP", "BG_TILES", "HARDWARE_OAM", "PALETTES", "SHADOW_OAM"}
)
REQUEST_CLASS_REQUIRED_RESOURCES = {
    "ANIMATION_REPLACEMENT": frozenset({"BG_TILES"}),
    "BG_PALETTE_PAYLOAD": frozenset({"PALETTES"}),
    "MAP_COLUMN_PAIRED": frozenset({"ATTRIBUTES", "BG_MAP"}),
    "MAP_CONNECTION_PAIRED": frozenset({"ATTRIBUTES", "BG_MAP"}),
    "MAP_OVERLAY_PAIRED": frozenset({"ATTRIBUTES", "BG_MAP"}),
    "MAP_RECTANGLE_PAIRED": frozenset({"ATTRIBUTES", "BG_MAP"}),
    "MAP_ROW_PAIRED": frozenset({"ATTRIBUTES", "BG_MAP"}),
    "OAM_BATCH_AND_DMA": frozenset({"HARDWARE_OAM", "SHADOW_OAM"}),
    "OBJ_PALETTE_PAYLOAD": frozenset({"PALETTES"}),
}


class Phase2MeasurementError(ValueError):
    """The measured products cannot safely host the Phase 2 representation."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Phase2MeasurementError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise Phase2MeasurementError(f"{path}: expected non-empty string")
    return value


def _positive_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Phase2MeasurementError(f"{path}: expected positive integer")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise Phase2MeasurementError(f"{path}: expected boolean")
    return value


def _array(value: object, path: str, *, nonempty: bool = False) -> list[object]:
    if not isinstance(value, list) or (nonempty and not value):
        raise Phase2MeasurementError(f"{path}: expected {'non-empty ' if nonempty else ''}array")
    return value


@dataclass(frozen=True, slots=True)
class Phase2Definition:
    descriptor_layout: tuple[tuple[str, int], ...]
    scratch_layout: tuple[tuple[str, int], ...]
    debug_header_bytes: int
    debug_record_bytes: int
    classes: tuple["RequestClassMeasurement", ...]
    scenario: tuple[tuple[str, tuple["PressureRequest", ...], bool], ...]
    aggregate_high_water: int
    class_high_water: Mapping[str, int]

    @property
    def descriptor_bytes(self) -> int:
        return sum(size for _, size in self.descriptor_layout)

    @property
    def scratch_bytes(self) -> int:
        return sum(size for _, size in self.scratch_layout)


@dataclass(frozen=True, slots=True)
class RequestClassMeasurement:
    name: str
    required_work: bool
    equivalent_at_capacity: bool
    high_water_mark: int
    retry_observable: bool = True
    fallback_observable: bool = False


@dataclass(frozen=True, slots=True)
class PressureRequest:
    request_class: str
    owner: str
    generation: str
    resources: tuple[str, ...]
    destination: str
    desired_state: str
    visible_boundary: str

    @property
    def equivalence_identity(self) -> tuple[object, ...]:
        return (
            self.request_class,
            self.owner,
            self.generation,
            self.resources,
            self.destination,
            self.desired_state,
            self.visible_boundary,
        )


@dataclass(frozen=True, slots=True)
class RequestClassDecision:
    name: str
    high_water_mark: int
    required_work_policy: str
    capacity_equivalence_policy: str
    retry_observable: bool
    fallback_observable: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "high_water_mark": self.high_water_mark,
            "required_work_policy": self.required_work_policy,
            "capacity_equivalence_policy": self.capacity_equivalence_policy,
            "retry_observable": self.retry_observable,
            "fallback_observable": self.fallback_observable,
        }


@dataclass(frozen=True, order=True, slots=True)
class Phase2Candidate:
    wram_bank: int
    wram_start: int
    wram_end: int
    sram_bank: int
    sram_start: int
    sram_end: int
    rom_bank: int
    rom_start: int
    rom_end: int
    stack_margin_bytes: int
    ownership_adjacent: bool = False
    overlaps: tuple[str, ...] = ()
    forbidden_reason: str | None = None

    @property
    def wram_bytes(self) -> int:
        return self.wram_end - self.wram_start + 1

    @property
    def sram_bytes(self) -> int:
        return self.sram_end - self.sram_start + 1

    @property
    def rom_bytes(self) -> int:
        return self.rom_end - self.rom_start + 1

    @property
    def selection_key(self) -> tuple[int, int, int, int, int, int]:
        return (
            0 if self.ownership_adjacent else 1,
            -self.rom_bytes,
            self.rom_bank,
            self.wram_bank,
            self.wram_start,
            self.sram_start,
        )


@dataclass(frozen=True, slots=True)
class Phase2Measurement:
    input_sha256: Mapping[str, str]
    definition: Phase2Definition
    classes: tuple[RequestClassMeasurement, ...]
    descriptor_bytes: int
    scratch_bytes: int
    valid_candidates: tuple[Phase2Candidate, ...]
    rejected_candidates: tuple[tuple[str, str], ...] = ()
    ownership_state_bytes: int = PHASE1_STATE_BYTES
    inventory_audit: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Phase2Decision:
    schema: str
    input_sha256: Mapping[str, str]
    request_classes: tuple[RequestClassDecision, ...]
    descriptor_bytes: int
    capacity: int
    scratch_bytes: int
    wram_bank: int
    wram_start: int
    sram_bank: int
    sram_start: int
    rom_bank: int
    wram_end: int
    sram_end: int
    rom_start: int
    rom_end: int
    debug_carrier_capacity: int
    ownership_state_bytes: int
    audit_guard: str
    normal_rom_reachable: bool
    rejected_candidates: tuple[tuple[str, str], ...]
    inventory_audit: Mapping[str, object]
    descriptor_layout: tuple[tuple[str, int], ...]
    scratch_layout: tuple[tuple[str, int], ...]
    debug_header_bytes: int
    debug_record_bytes: int
    pressure_scenario: tuple[tuple[str, tuple[PressureRequest, ...], bool], ...]

    @classmethod
    def from_measurement(
        cls,
        measurement: Phase2Measurement,
        decisions: tuple[RequestClassDecision, ...],
        candidate: Phase2Candidate,
    ) -> "Phase2Decision":
        capacity = measurement.definition.aggregate_high_water
        needed_wram = measurement.scratch_bytes + capacity * measurement.descriptor_bytes
        debug_capacity = (
            candidate.sram_bytes - measurement.definition.debug_header_bytes
        ) // measurement.definition.debug_record_bytes
        if candidate.wram_bytes < needed_wram:
            raise Phase2MeasurementError("selected WRAM candidate does not fit representation")
        if debug_capacity < capacity:
            raise Phase2MeasurementError("selected SRAM candidate lacks debug-carrier capacity")
        return cls(
            SCHEMA,
            dict(sorted(measurement.input_sha256.items())),
            decisions,
            measurement.descriptor_bytes,
            capacity,
            measurement.scratch_bytes,
            candidate.wram_bank,
            candidate.wram_start,
            candidate.sram_bank,
            candidate.sram_start,
            candidate.rom_bank,
            candidate.wram_start + needed_wram - 1,
            candidate.sram_start
            + measurement.definition.debug_header_bytes
            + capacity * measurement.definition.debug_record_bytes
            - 1,
            candidate.rom_start,
            candidate.rom_start + MINIMUM_ROM_BYTES - 1,
            debug_capacity,
            measurement.ownership_state_bytes,
            AUDIT_GUARD,
            True,
            measurement.rejected_candidates,
            dict(measurement.inventory_audit),
            measurement.definition.descriptor_layout,
            measurement.definition.scratch_layout,
            measurement.definition.debug_header_bytes,
            measurement.definition.debug_record_bytes,
            measurement.definition.scenario,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "inputs": {
                key: {"path": key, "sha256": value}
                for key, value in sorted(self.input_sha256.items())
            },
            "activation": {
                "normal_rom_reachable": self.normal_rom_reachable,
                "production_products": list(PRODUCTION_PRODUCTS),
                "audit_diagnostics": {
                    "guard": self.audit_guard,
                    "product": PHASE2_AUDIT_PRODUCT,
                },
            },
            "inventory_audit": dict(self.inventory_audit),
            "ownership_abi": {"preserved_prefix_bytes": self.ownership_state_bytes},
            "requests": {
                "descriptor_bytes": self.descriptor_bytes,
                "descriptor_layout": [
                    {"name": name, "bytes": size} for name, size in self.descriptor_layout
                ],
                "capacity": self.capacity,
                "classes": [item.to_dict() for item in self.request_classes],
                "pressure_measurement": {
                    "bounded": True,
                    "aggregate_high_water": self.capacity,
                    "steps": [
                        {
                            "name": name,
                            "drain_before": drain,
                            "enqueue": [
                                {
                                    "class": request.request_class,
                                    "owner": request.owner,
                                    "generation": request.generation,
                                    "resources": list(request.resources),
                                    "destination": request.destination,
                                    "desired_state": request.desired_state,
                                    "visible_boundary": request.visible_boundary,
                                }
                                for request in enqueue
                            ],
                        }
                        for name, enqueue, drain in self.pressure_scenario
                    ],
                },
            },
            "scratch": {
                "bytes": self.scratch_bytes,
                "layout": [{"name": name, "bytes": size} for name, size in self.scratch_layout],
            },
            "wram": {
                "bank": self.wram_bank,
                "start": self.wram_start,
                "end": self.wram_end,
            },
            "sram_debug_carrier": {
                "bank": self.sram_bank,
                "start": self.sram_start,
                "end": self.sram_end,
                "record_bytes": self.debug_record_bytes,
                "record_capacity": self.debug_carrier_capacity,
                "selected_records": self.capacity,
            },
            "rom": {
                "bank": self.rom_bank,
                "start": self.rom_start,
                "end": self.rom_end,
                "reserved_bytes": MINIMUM_ROM_BYTES,
            },
            "rejected_candidates": [
                {"candidate": name, "reason": reason}
                for name, reason in self.rejected_candidates
            ],
            "selection_rule": (
                "common release/debug space; preserve the 13-byte ownership ABI; "
                "prefer measured adjacency to the ownership core, then largest ROM span, "
                "lowest ROM/WRAM address; required work defers with observable caller retry"
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def load_definition(path: Path) -> Phase2Definition:
    """Parse concrete layouts and replay the bounded hostile pressure trace."""
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
        )
        if not isinstance(raw, dict):
            raise Phase2MeasurementError("Phase 2 definition must be an object")
        if set(raw) != {
            "schema", "descriptor", "scratch", "debug_carrier",
            "request_classes", "scenario",
        }:
            raise Phase2MeasurementError("unknown or omitted Phase 2 definition fields")
        if raw["schema"] != "full-color-phase2-hostile-slice-definition-v1":
            raise Phase2MeasurementError("unexpected Phase 2 definition schema")
        if (
            any(set(item) != {"name", "bytes"} for item in raw["descriptor"])
            or any(set(item) != {"name", "bytes"} for item in raw["scratch"])
            or set(raw["debug_carrier"]) != {"header_bytes", "record_bytes"}
            or any(
                set(item)
                != {
                    "name", "required_work", "equivalent_at_capacity",
                    "retry_observable", "fallback_observable",
                }
                for item in raw["request_classes"]
            )
        ):
            raise Phase2MeasurementError("unknown or omitted Phase 2 definition fields")
        descriptor_rows = _array(raw["descriptor"], "descriptor", nonempty=True)
        scratch_rows = _array(raw["scratch"], "scratch", nonempty=True)
        class_rows = _array(raw["request_classes"], "request_classes", nonempty=True)
        scenario_rows = _array(raw["scenario"], "scenario", nonempty=True)
        descriptor = tuple(
            (_string(item["name"], f"descriptor[{index}].name"),
             _positive_int(item["bytes"], f"descriptor[{index}].bytes"))
            for index, item in enumerate(descriptor_rows)
        )
        scratch = tuple(
            (_string(item["name"], f"scratch[{index}].name"),
             _positive_int(item["bytes"], f"scratch[{index}].bytes"))
            for index, item in enumerate(scratch_rows)
        )
        debug_header = _positive_int(raw["debug_carrier"]["header_bytes"], "debug_carrier.header_bytes")
        debug_record = _positive_int(raw["debug_carrier"]["record_bytes"], "debug_carrier.record_bytes")
        names = tuple(
            _string(item["name"], f"request_classes[{index}].name")
            for index, item in enumerate(class_rows)
        )
        if (
            names != tuple(sorted(set(names)))
            or set(names) != set(REQUEST_CLASS_REQUIRED_RESOURCES)
            or len({name for name, _ in descriptor}) != len(descriptor)
            or len({name for name, _ in scratch}) != len(scratch)
        ):
            raise Phase2MeasurementError("malformed Phase 2 layout or request classes")
        typed_class_rows = []
        for index, item in enumerate(class_rows):
            typed_class_rows.append(
                {
                    "name": names[index],
                    "required_work": _boolean(item["required_work"], f"request_classes[{index}].required_work"),
                    "equivalent_at_capacity": _boolean(item["equivalent_at_capacity"], f"request_classes[{index}].equivalent_at_capacity"),
                    "retry_observable": _boolean(item["retry_observable"], f"request_classes[{index}].retry_observable"),
                    "fallback_observable": _boolean(item["fallback_observable"], f"request_classes[{index}].fallback_observable"),
                }
            )
        class_rows = typed_class_rows
        # Resident descriptors are keyed by destination for request classes
        # whose final desired state may replace an older request.  Other work
        # remains independently resident even when its class matches.
        queue: list[PressureRequest] = []
        aggregate = 0
        per_class = {name: 0 for name in names}
        scenario = []
        for step_index, step in enumerate(scenario_rows):
            required_step_keys = {"name", "enqueue", "identity"}
            if set(step) not in (required_step_keys, required_step_keys | {"drain"}):
                raise Phase2MeasurementError(
                    "scenario step has unknown or omitted identity fields"
                )
            identity = step["identity"]
            if set(identity) != {"owner", "generation", "resources", "visible_boundary"}:
                raise Phase2MeasurementError(
                    "scenario identity requires owner, generation, resources, and visible_boundary"
                )
            step_name = _string(step["name"], f"scenario[{step_index}].name")
            owner = _string(identity["owner"], f"scenario[{step_index}].identity.owner")
            generation = _string(identity["generation"], f"scenario[{step_index}].identity.generation")
            resource_values = _array(identity["resources"], f"scenario[{step_index}].identity.resources", nonempty=True)
            resources = tuple(
                _string(resource, f"scenario[{step_index}].identity.resources[{index}]")
                for index, resource in enumerate(resource_values)
            )
            if resources != tuple(sorted(set(resources))):
                raise Phase2MeasurementError("scenario identity resources must be unique and sorted")
            unknown_resources = sorted(set(resources) - RESOURCE_VOCABULARY)
            if unknown_resources:
                raise Phase2MeasurementError(f"scenario identity uses unknown resources: {unknown_resources}")
            visible_boundary = _string(identity["visible_boundary"], f"scenario[{step_index}].identity.visible_boundary")
            drain = _boolean(step.get("drain", False), f"scenario[{step_index}].drain")
            if drain:
                queue.clear()
            enqueued_list = []
            for item_index, item in enumerate(_array(step["enqueue"], f"scenario[{step_index}].enqueue", nonempty=True)):
                if set(item) != {"class", "destination", "desired_state"}:
                    raise Phase2MeasurementError(
                        "scenario request has unknown or omitted definition fields"
                    )
                enqueued_list.append(
                    PressureRequest(
                        _string(item["class"], f"scenario[{step_index}].enqueue[{item_index}].class"),
                        owner,
                        generation,
                        resources,
                        _string(item["destination"], f"scenario[{step_index}].enqueue[{item_index}].destination"),
                        _string(item["desired_state"], f"scenario[{step_index}].enqueue[{item_index}].desired_state"),
                        visible_boundary,
                    )
                )
            enqueued = tuple(enqueued_list)
            unknown = sorted({item.request_class for item in enqueued} - set(names))
            if unknown:
                raise Phase2MeasurementError(f"scenario names unknown request classes: {unknown}")
            expected_resources = frozenset().union(
                *(REQUEST_CLASS_REQUIRED_RESOURCES[item.request_class] for item in enqueued)
            )
            if set(resources) != expected_resources:
                raise Phase2MeasurementError(
                    "scenario identity resources are incompatible with its request classes; "
                    f"expected {sorted(expected_resources)}, got {sorted(resources)}"
                )
            class_rows_by_name = {item["name"]: item for item in class_rows}
            for request in enqueued:
                request_class = request.request_class
                required_resources = REQUEST_CLASS_REQUIRED_RESOURCES[request_class]
                if not required_resources <= set(request.resources):
                    raise Phase2MeasurementError(
                        f"{request_class}: incompatible identity resources; requires "
                        f"{sorted(required_resources)}"
                    )
                if class_rows_by_name[request_class]["equivalent_at_capacity"]:
                    queue = [
                        resident
                        for resident in queue
                        if resident.equivalence_identity != request.equivalence_identity
                    ]
                queue.append(request)
            aggregate = max(aggregate, len(queue))
            for name in names:
                per_class[name] = max(
                    per_class[name], sum(item.request_class == name for item in queue)
                )
            scenario.append((step_name, enqueued, drain))
        if aggregate <= 0 or any(value <= 0 for value in per_class.values()):
            raise Phase2MeasurementError("bounded hostile scenario does not exercise every class")
        classes = tuple(
            RequestClassMeasurement(
                item["name"], item["required_work"], item["equivalent_at_capacity"],
                per_class[item["name"]], item["retry_observable"], item["fallback_observable"],
            )
            for item in class_rows
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise Phase2MeasurementError("malformed Phase 2 representation definition") from exc
    return Phase2Definition(
        descriptor, scratch, debug_header, debug_record, classes,
        tuple(scenario), aggregate, dict(sorted(per_class.items())),
    )


def select_required_defer_policy(item: RequestClassMeasurement) -> RequestClassDecision:
    if not item.name or item.high_water_mark <= 0:
        raise Phase2MeasurementError("request class requires a name and positive high-water mark")
    if item.required_work and not item.retry_observable:
        raise Phase2MeasurementError(
            f"{item.name}: required DEFERRED work lacks runtime-observable retry"
        )
    if not item.required_work and not item.fallback_observable:
        raise Phase2MeasurementError(
            f"{item.name}: optional work lacks runtime-observable fallback"
        )
    return RequestClassDecision(
        item.name,
        item.high_water_mark,
        "DEFERRED_CALLER_RETRY" if item.required_work else "REJECTED_OBSERVED_FALLBACK",
        "COALESCED_FINAL_STATE" if item.equivalent_at_capacity else "DEFERRED_CALLER_RETRY",
        item.retry_observable,
        item.fallback_observable,
    )


def select_phase2_representation(measurement: Phase2Measurement) -> Phase2Decision:
    if measurement.descriptor_bytes != measurement.definition.descriptor_bytes:
        raise Phase2MeasurementError(
            "descriptor byte cost does not match the hashed concrete definition"
        )
    if measurement.scratch_bytes != measurement.definition.scratch_bytes:
        raise Phase2MeasurementError(
            "scratch byte cost does not match the hashed concrete definition"
        )
    if measurement.classes != measurement.definition.classes:
        raise Phase2MeasurementError("request classes/policies do not match hostile trace definition")
    if measurement.ownership_state_bytes != PHASE1_STATE_BYTES:
        raise Phase2MeasurementError("Phase 1 ownership ABI prefix changed")
    decisions = tuple(select_required_defer_policy(item) for item in measurement.classes)
    if tuple(sorted(item.name for item in decisions)) != tuple(item.name for item in decisions):
        raise Phase2MeasurementError("request classes must be sorted by stable name")
    capacity = measurement.definition.aggregate_high_water
    needed_wram = measurement.scratch_bytes + capacity * measurement.descriptor_bytes
    needed_sram = (
        measurement.definition.debug_header_bytes
        + capacity * measurement.definition.debug_record_bytes
    )
    valid = []
    for candidate in measurement.valid_candidates:
        if candidate.overlaps or candidate.forbidden_reason:
            continue
        if candidate.stack_margin_bytes < MINIMUM_STACK_MARGIN:
            continue
        if candidate.rom_bank in FORBIDDEN_ROM_BANKS:
            continue
        if candidate.wram_bytes < needed_wram:
            continue
        if candidate.sram_bytes < needed_sram:
            continue
        if candidate.rom_bytes < MINIMUM_ROM_BYTES:
            continue
        valid.append(candidate)
    if not valid:
        raise Phase2MeasurementError(
            "no non-overlapping Phase 2 candidate fits measured WRAM/SRAM/ROM limits"
        )
    candidate = min(valid, key=lambda item: item.selection_key)
    return Phase2Decision.from_measurement(measurement, decisions, candidate)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_sections(path: Path) -> dict[tuple[str, int], list[tuple[int, int, str]]]:
    result: dict[tuple[str, int], list[tuple[int, int, str]]] = {}
    kind: str | None = None
    bank: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := _BANK.match(line):
            kind, bank = match.group(1), int(match.group(2))
            result.setdefault((kind, bank), [])
            continue
        if kind is None or bank is None or not (match := _SECTION.match(line)):
            continue
        start = int(match.group(1), 16)
        end = int(match.group(2) or match.group(1), 16)
        result[(kind, bank)].append((start, end, match.group(4)))
    return result


def _free(start: int, end: int, occupied: Sequence[tuple[int, int, str]]) -> list[tuple[int, int]]:
    ranges = []
    cursor = start
    for low, high, _ in sorted(occupied):
        if high < start or low > end:
            continue
        low, high = max(low, start), min(high, end)
        if cursor < low:
            ranges.append((cursor, low - 1))
        cursor = max(cursor, high + 1)
    if cursor <= end:
        ranges.append((cursor, end))
    return ranges


def _intersection(left: Sequence[tuple[int, int]], right: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    return [
        (max(a, c), min(b, d))
        for a, b in left
        for c, d in right
        if max(a, c) <= min(b, d)
    ]


def _stack_margin(sym_path: Path, sections: Mapping[tuple[str, int], list[tuple[int, int, str]]]) -> int:
    address = None
    for line in sym_path.read_text(encoding="utf-8").splitlines():
        match = _SYMBOL.match(line)
        if match and match.group(3) == "wStack":
            address = int(match.group(2), 16)
            break
    stacks = [item for values in sections.values() for item in values if item[2] == "Stack"]
    if address is None or len(stacks) != 1 or not stacks[0][0] <= address <= stacks[0][1]:
        raise Phase2MeasurementError("linker products do not define one valid wStack")
    return address - stacks[0][0] + 1


def _phase2_roots() -> tuple[str, ...]:
    return tuple(sorted(set(PHASE2_HOSTILE_LIFECYCLE_ROOTS) | set(PHASE2_HOSTILE_SCENE_ROOTS) | set(PHASE2_HOSTILE_MUTATION_ROOTS)))


@lru_cache(maxsize=4)
def discover_phase2_sources(root: Path, *, guarded: bool = True) -> SourceDiscoveryReport:
    """Run the real source discoverer over every declared hostile-slice root."""
    if guarded:
        _verify_audit_product(root)
    return discover_sources(
        root,
        SOURCE_ROOTS,
        lifecycle_roots=PHASE2_HOSTILE_LIFECYCLE_ROOTS,
        scene_roots=PHASE2_HOSTILE_SCENE_ROOTS,
        mutation_roots=PHASE2_HOSTILE_MUTATION_ROOTS,
        scene_edge_classifications=PHASE2_SCENE_EDGE_CLASSIFICATIONS,
    )


def _verify_audit_product(root: Path) -> tuple[Path, Path, Path]:
    rom_path = root / "pokeyellow_phase2_audit.gbc"
    sym_path = root / "pokeyellow_phase2_audit.sym"
    map_path = root / "pokeyellow_phase2_audit.map"
    if not all(path.is_file() for path in (rom_path, sym_path, map_path)):
        raise Phase2MeasurementError("missing compile-time PHASE2_AUDIT link product")
    symbols = load_sym(sym_path)
    try:
        marker = symbols.by_name["Phase2AuditProvenance"]
        roots_start = symbols.by_name["Phase2AuditRoots"]
        roots_end = symbols.by_name["Phase2AuditRootsEnd"]
    except KeyError as exc:
        raise Phase2MeasurementError("audit product lacks PHASE2_AUDIT provenance symbols") from exc
    rom = rom_path.read_bytes()
    offset = normalize_rom_offset(marker.bank, marker.address)
    if rom[offset : offset + len(AUDIT_MARKER)] != AUDIT_MARKER:
        raise Phase2MeasurementError("audit product has invalid compile-time provenance marker")
    if roots_end.address - roots_start.address != 2 * len(_phase2_roots()):
        raise Phase2MeasurementError("audit product root table does not cover configured roots")
    table_offset = normalize_rom_offset(roots_start.bank, roots_start.address)
    table = rom[table_offset : table_offset + 2 * len(_phase2_roots())]
    if len(table) != 2 * len(_phase2_roots()):
        raise Phase2MeasurementError("audit product root table is truncated")
    decoded = tuple(
        int.from_bytes(table[index : index + 2], "little")
        for index in range(0, len(table), 2)
    )
    try:
        expected = tuple(symbols.by_name[name].address for name in _phase2_roots())
    except KeyError as exc:
        raise Phase2MeasurementError(
            f"audit product lacks configured root symbol {exc.args[0]!r}"
        ) from exc
    if len(set(decoded)) != len(decoded):
        raise Phase2MeasurementError("audit product root table contains duplicate pointers")
    if decoded != expected:
        mismatch = next(
            (
                (name, actual, wanted)
                for name, actual, wanted in zip(_phase2_roots(), decoded, expected)
                if actual != wanted
            ),
            None,
        )
        raise Phase2MeasurementError(
            f"audit product root pointer does not match configured symbol: {mismatch}"
        )
    sections = load_map(map_path)
    if not any(section.name == "Phase 2 Audit Provenance" and section.bank == marker.bank and section.start <= marker.address <= section.end for section in sections):
        raise Phase2MeasurementError("audit marker is not linked in its provenance section")
    forbidden = (b"Phase2Audit", b"FullColorPhase2", b"Phase2Hostile", AUDIT_MARKER)
    for stem in ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc"):
        for suffix in (".sym", ".map", ".gbc"):
            product = root / f"{stem}{suffix}"
            blob = product.read_bytes()
            if any(marker in blob for marker in forbidden):
                raise Phase2MeasurementError(
                    f"normal product {product.name} exposes a forbidden Phase 2 entry, "
                    "section, marker, or call-path"
                )
    return rom_path, sym_path, map_path


@lru_cache(maxsize=8)
def discover_phase2_rom_product(root: Path, product: str):
    """Run exact hostile-slice discovery against one explicit link product."""
    stem = PRODUCT_ARTIFACTS.get(product)
    if stem is None:
        raise Phase2MeasurementError(f"unknown Phase 2 link product: {product}")
    if product == PHASE2_AUDIT_PRODUCT:
        rom_path, sym_path, map_path = _verify_audit_product(root)
    else:
        rom_path = root / f"{stem}.gbc"
        sym_path = root / f"{stem}.sym"
        map_path = root / f"{stem}.map"
        if not all(path.is_file() for path in (rom_path, sym_path, map_path)):
            raise Phase2MeasurementError(
                f"missing production link artifacts for {product}"
            )
    symbols = load_sym(sym_path)
    roots = _phase2_roots()
    return discover_rom_batched(
        rom_path.read_bytes(), symbols, roots, batch_size=16,
        sections=load_map(map_path), farcall_labels=FARCALL_LABELS,
        predef_targets=load_predef_targets(root, symbols), copied_regions=COPIED_REGIONS,
        shadow_oam_ranges=SHADOW_OAM_RANGES,
        scene_roots=tuple(sorted(set(PHASE2_HOSTILE_LIFECYCLE_ROOTS) | set(PHASE2_HOSTILE_SCENE_ROOTS))),
        mutation_roots=PHASE2_HOSTILE_MUTATION_ROOTS,
        dma_control_labels=DMA_CONTROL_LABELS, follow_calls=False,
    )


def discover_phase2_rom(root: Path, *, guarded: bool = True):
    """Compatibility wrapper for the diagnostic or debug product."""
    product = PHASE2_AUDIT_PRODUCT if guarded else DEBUG_PRODUCT
    return discover_phase2_rom_product(root, product)


def _load_planned_subjects(
    root: Path,
    *,
    closed: bool = False,
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, str],
    tuple[str, ...],
    dict[str, dict[str, str]],
]:
    try:
        raw = json.loads(
            (root / PLANNED_SUBJECTS_PATH).read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2MeasurementError("invalid planned semantic subject authority") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {
            "schema", "source_subjects", "rom_subjects",
            "rom_candidate_subjects", "rom_unresolved_dispositions",
            "source_error_subjects", "source_error_disposition",
            "planned_only_dispositions",
            "authority_counts",
        }
        or raw["schema"] != "full-color-phase2-planned-subjects-v4"
    ):
        raise Phase2MeasurementError("invalid planned semantic subject authority")
    result = []
    for kind in ("source_subjects", "rom_subjects", "rom_candidate_subjects"):
        mapping = raw[kind]
        if not isinstance(mapping, dict) or set(mapping) != PHASE2_PLANNED_ROW_IDS:
            raise Phase2MeasurementError(
                f"{kind}: must bind the exact planned Phase 2 row set"
            )
        checked: dict[str, tuple[str, ...]] = {}
        for row_id, values in mapping.items():
            items = tuple(
                _string(value, f"{kind}.{row_id}[{index}]")
                for index, value in enumerate(_array(values, f"{kind}.{row_id}"))
            )
            if items != tuple(sorted(set(items))) or any(not _SHA256.fullmatch(item) for item in items):
                raise Phase2MeasurementError(
                    f"{kind}.{row_id}: subjects must be unique sorted canonical SHA-256 digests"
                )
            checked[row_id] = items
        result.append(checked)
        flattened = [item for values in checked.values() for item in values]
        if len(flattened) != len(set(flattened)):
            raise Phase2MeasurementError(
                f"{kind}: one canonical subject may bind exactly one planned row"
            )
    unresolved = raw["rom_unresolved_dispositions"]
    if not isinstance(unresolved, dict):
        raise Phase2MeasurementError("rom_unresolved_dispositions: expected object")
    checked_unresolved = {
        _string(message, "rom_unresolved_dispositions key"):
        _string(row_id, f"rom_unresolved_dispositions.{message}")
        for message, row_id in unresolved.items()
    }
    if not set(checked_unresolved.values()) <= PHASE2_PLANNED_ROW_IDS:
        raise Phase2MeasurementError(
            "rom_unresolved_dispositions: disposition names an unknown planned row"
        )
    checked_source_errors = tuple(
        _string(value, f"source_error_subjects[{index}]")
        for index, value in enumerate(_array(raw["source_error_subjects"], "source_error_subjects"))
    )
    if (
        checked_source_errors != tuple(sorted(set(checked_source_errors)))
        or any(not _SHA256.fullmatch(item) for item in checked_source_errors)
        or raw["source_error_disposition"] != "KNOWN_DYNAMIC_JUMP_DISCOVERY_LIMITATION"
    ):
        raise Phase2MeasurementError(
            "source_error_subjects: dispositions must be unique sorted canonical SHA-256 digests"
        )

    planned_only = raw["planned_only_dispositions"]
    expected_planned_only = frozenset() if closed else PLANNED_ONLY_DISPOSITION_ROWS
    if not isinstance(planned_only, dict) or set(planned_only) != expected_planned_only:
        raise Phase2MeasurementError(
            "planned_only_dispositions: must be empty after audit closure"
            if closed
            else "planned_only_dispositions: must be the exact narrow planned-only row set"
        )
    checked_planned_only: dict[str, dict[str, object]] = {}
    for row_id, disposition in planned_only.items():
        contract = _PLANNED_ONLY_ROW_CONTRACTS[row_id]
        expected = {
            "commit_unit": contract["commit_unit"],
            "disposition": "PALETTE_GENERATION_DEFERRED_BY_PHASE2_PLAN",
            "machine_sites": list(contract["machine_sites"]),
            "resources": list(contract["resources"]),
            "role": "writer",
            "root": contract["root"],
        }
        if disposition != expected:
            raise Phase2MeasurementError(f"planned_only_dispositions.{row_id}: malformed disposition")
        checked = dict(disposition)
        root = checked["root"]
        if (
            checked["role"] != "writer"
            or checked["disposition"] != "PALETTE_GENERATION_DEFERRED_BY_PHASE2_PLAN"
            or root not in PHASE2_ROOT_ROWS
            or PHASE2_ROOT_ROWS[root][1] != row_id
        ):
            raise Phase2MeasurementError(
                f"planned_only_dispositions.{row_id}: disposition is not role-bound"
            )
        checked_planned_only[row_id] = checked

    counts = raw["authority_counts"]
    expected_counts = {
        "source_subjects": {
            "by_row": {row_id: len(values) for row_id, values in result[0].items()},
            "total": sum(map(len, result[0].values())),
        },
        "rom_subjects": {
            "by_row": {row_id: len(values) for row_id, values in result[1].items()},
            "total": sum(map(len, result[1].values())),
        },
        "rom_candidate_subjects": {
            "by_row": {row_id: len(values) for row_id, values in result[2].items()},
            "total": sum(map(len, result[2].values())),
        },
        "rom_unresolved_dispositions": {
            "by_row": {
                row_id: tuple(checked_unresolved.values()).count(row_id)
                for row_id in sorted(PHASE2_PLANNED_ROW_IDS)
            },
            "total": len(checked_unresolved),
        },
        "source_error_subjects": {"total": len(checked_source_errors)},
        "planned_only_dispositions": {"total": len(checked_planned_only)},
    }
    if counts != expected_counts:
        raise Phase2MeasurementError("authority_counts: exact cardinalities or per-bucket counts changed")
    return (
        result[0], result[1], result[2], checked_unresolved,
        checked_source_errors, checked_planned_only,
    )


def _reject_duplicate_projection(values: Sequence[str], label: str) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise Phase2MeasurementError(f"duplicate {label} before projection: {duplicates}")


def _reject_duplicate_rom_report(report: object, product: str = "") -> None:
    prefix = f"{product} " if product else ""
    _reject_duplicate_projection(
        tuple(rom_finding_subject(finding).sha256 for finding in report.findings),
        f"{prefix}ROM subjects",
    )
    _reject_duplicate_projection(
        tuple(
            rom_finding_subject(finding).sha256
            for finding in report.candidate_findings
        ),
        f"{prefix}ROM candidate subjects",
    )
    _reject_duplicate_projection(
        (*report.unresolved_destinations, *report.unresolved_control_flow),
        f"{prefix}ROM unresolved messages",
    )


def _source_finding_root(finding: object) -> str | None:
    symbol = finding.symbol
    return next(
        (
            root
            for root in sorted(_phase2_roots(), key=len, reverse=True)
            if symbol == root or symbol.startswith(root + ".")
        ),
        None,
    )


_PASSIVE_PALETTE_RESOURCES = frozenset({"CGB_PALETTE", "PALETTES"})
_PASSIVE_ATTRIBUTE_RESOURCES = frozenset({
    "ATTRIBUTES",
    "BG_WINDOW_MAP",
    "COMPUTED_POINTER",
    "SYMBOLIC_SINK",
    "VRAM_BANK",
    "WRAM_BANK",
})


def _planned_row_for(
    root: str, category: str, *, resource: str | None = None,
) -> str:
    if category == "writer" and root.startswith("PassiveFullColor"):
        if resource in _PASSIVE_PALETTE_RESOURCES:
            return "WR-P2-YELLOW-BG-PALETTE"
        if resource in _PASSIVE_ATTRIBUTE_RESOURCES:
            return "WR-P2-YELLOW-OVERLAY-TRANSFER"
        raise Phase2MeasurementError(
            f"{root}: passive writer has unclassified resource {resource!r}"
        )
    control_row, writer_row = PHASE2_ROOT_ROWS[root]
    return writer_row if category == "writer" else control_row


_PASSIVE_VISIBLE_POINTER_ROOTS = {
    "PassiveFullColorApplyMap": (
        (
            "PassiveFullColorApplyMap",
            "3b:534f",
            "3b:54bc",
        ),
    ),
    "PassiveFullColorCommitVisibleAttributes": (
        ("PassiveFullColorCommitVisibleAttributes",),
    ),
}
_PASSIVE_CLEAR_POINTER_ROOTS = {
    "PassiveFullColorClearBGMapChunk": (
        ("PassiveFullColorClearBGMapChunk",),
        ("PassiveFullColorClearBGMapChunk", "3b:5512"),
        ("PassiveFullColorClearBGMapChunk", "3b:5512", "3b:5512"),
    ),
    "PassiveFullColorVBlank": (
        (
            "PassiveFullColorVBlank", "3b:5436", "3b:547c", "3b:548f",
            "3b:549c", "3b:54eb",
        ),
        (
            "PassiveFullColorVBlank", "3b:5436", "3b:547c", "3b:548f",
            "3b:549c", "3b:54eb", "3b:5512",
        ),
        (
            "PassiveFullColorVBlank", "3b:5436", "3b:547c", "3b:548f",
            "3b:549c", "3b:54eb", "3b:5512", "3b:5512",
        ),
    ),
}
_PASSIVE_COLUMN_POINTER_ROOTS = {
    "PassiveFullColorCommitRedrawColumn": (
        ("PassiveFullColorCommitRedrawColumn",),
    ),
    "PassiveFullColorVBlank": (
        ("PassiveFullColorVBlank", "3b:5436", "3b:5455", "3b:5ab1"),
    ),
}
_PASSIVE_ROW_POINTER_ROOTS = {
    "PassiveFullColorCommitRedrawRow": (("PassiveFullColorCommitRedrawRow",),),
    "PassiveFullColorVBlank": (
        ("PassiveFullColorVBlank", "3b:5436", "3b:5455", "3b:5b6a"),
    ),
}

# Diagnostic ROM pointer sites remain a reviewed literal authority. Production
# products are independently bound by their product-specific assignments.
# Keep every reviewed pointer store literal: address drift, opcode drift, a new
# store, a new root, or different call ancestry must block projection.
_PASSIVE_ROM_POINTER_WRITES = {
    (0x3B, 0x54CE, "72"): _PASSIVE_VISIBLE_POINTER_ROOTS,
    (0x3B, 0x5512, "22"): _PASSIVE_CLEAR_POINTER_ROOTS,
    (0x3B, 0x5AC5, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AC8, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5ACE, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AD1, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AD7, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5ADA, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AE0, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AE3, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AE9, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AEC, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AF2, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AF5, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AFB, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5AFE, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B04, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B07, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B0D, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B10, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B16, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B19, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B1F, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B22, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B28, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B2B, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B31, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B34, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B3A, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B3D, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B43, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B46, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B4C, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B4F, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B55, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B58, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B5E, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B61, "12"): _PASSIVE_COLUMN_POINTER_ROOTS,
    (0x3B, 0x5B7E, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B81, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B87, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B8A, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B90, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B93, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B99, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5B9C, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BA2, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BA5, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BAB, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BAE, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BB4, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BB7, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BBD, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BC0, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BC6, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BC9, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BCF, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BD2, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BD8, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BDB, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BE1, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BE4, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BEA, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BED, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BF3, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BF6, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BFC, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5BFF, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C05, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C08, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C0E, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C11, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C17, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C1A, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C20, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C23, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C29, "12"): _PASSIVE_ROW_POINTER_ROOTS,
    (0x3B, 0x5C2C, "12"): _PASSIVE_ROW_POINTER_ROOTS,
}


def _validate_passive_rom_pointer_authority(findings: Sequence[object]) -> None:
    passive_pointer_findings = tuple(
        finding
        for finding in findings
        if finding.category == "writer"
        and finding.resource == "UNKNOWN_DESTINATION"
        and finding.root.startswith("PassiveFullColor")
    )
    actual_sites = {
        (finding.bank, finding.address, finding.bytes)
        for finding in passive_pointer_findings
    }
    expected_sites = set(_PASSIVE_ROM_POINTER_WRITES)
    if actual_sites != expected_sites:
        raise Phase2MeasurementError(
            "passive ROM pointer sites changed: "
            f"missing={sorted(expected_sites - actual_sites)} "
            f"added={sorted(actual_sites - expected_sites)}"
        )
    for site in sorted(expected_sites):
        actual_roots = {
            finding.root
            for finding in passive_pointer_findings
            if (finding.bank, finding.address, finding.bytes) == site
        }
        expected_roots = set(_PASSIVE_ROM_POINTER_WRITES[site])
        if actual_roots != expected_roots:
            raise Phase2MeasurementError(
                "passive ROM pointer roots changed at "
                f"{site[0]:02x}:{site[1]:04x}: "
                f"missing={sorted(expected_roots - actual_roots)} "
                f"added={sorted(actual_roots - expected_roots)}"
            )
        for root in sorted(expected_roots):
            actual_paths = {
                finding.call_path
                for finding in passive_pointer_findings
                if (finding.bank, finding.address, finding.bytes) == site
                and finding.root == root
            }
            expected_paths = set(_PASSIVE_ROM_POINTER_WRITES[site][root])
            if actual_paths != expected_paths:
                raise Phase2MeasurementError(
                    "passive ROM pointer ancestry changed at "
                    f"{site[0]:02x}:{site[1]:04x} for {root}: "
                    f"missing={sorted(expected_paths - actual_paths)} "
                    f"added={sorted(actual_paths - expected_paths)}"
                )


def _planned_rom_row_for(
    finding: object,
    *,
    reviewed_pointer_rows: Mapping[str, str] | None = None,
) -> str:
    """Project only reviewed passive pointer stores hidden by ROM dataflow."""
    if finding.category != "writer" or finding.resource != "UNKNOWN_DESTINATION":
        return _planned_row_for(
            finding.root, finding.category, resource=finding.resource,
        )
    if not finding.root.startswith("PassiveFullColor"):
        return _planned_row_for(
            finding.root, finding.category, resource=finding.resource,
        )
    if reviewed_pointer_rows is not None:
        digest = rom_finding_subject(finding).sha256
        row_id = reviewed_pointer_rows.get(digest)
        if (
            finding.mechanism != "pointer"
            or row_id != "WR-P2-YELLOW-OVERLAY-TRANSFER"
        ):
            raise Phase2MeasurementError(
                "unreviewed passive ROM pointer write: "
                f"{finding.root} {finding.bank:02x}:{finding.address:04x} "
                f"{finding.bytes} {finding.resource} {finding.mechanism} "
                f"{finding.call_path}"
            )
        return row_id
    expected_roots = _PASSIVE_ROM_POINTER_WRITES.get(
        (finding.bank, finding.address, finding.bytes)
    )
    allowed_paths = None if expected_roots is None else expected_roots.get(finding.root)
    root_allowed = expected_roots is not None and finding.root in expected_roots
    path_allowed = root_allowed and finding.call_path in allowed_paths
    if finding.mechanism != "pointer" or not path_allowed:
        raise Phase2MeasurementError(
            "unreviewed passive ROM pointer write: "
            f"{finding.root} {finding.bank:02x}:{finding.address:04x} "
            f"{finding.bytes} {finding.resource} {finding.mechanism} "
            f"{finding.call_path}"
        )
    return "WR-P2-YELLOW-OVERLAY-TRANSFER"


def _normalize_closed_scene_directions(report: SourceDiscoveryReport) -> SourceDiscoveryReport:
    """Translate hostile party edges into the inventory's stable vocabulary."""
    return replace(
        report,
        findings=tuple(
            replace(
                finding,
                direction=_CLOSED_SCENE_DIRECTIONS.get(
                    (finding.symbol, finding.destination), finding.direction
                ),
            )
            for finding in report.findings
        ),
    )


def _passive_production_contract_errors(
    report: SourceDiscoveryReport,
) -> tuple[str, ...]:
    """Prove that the audit product adds only passive palette/attribute work.

    The old scheduler and ownership helpers deliberately remain buildable as
    direct test seams.  They are rejected only when a configured production
    root (or one of its banked integration helpers) reaches them.
    """
    errors: list[str] = []
    edges = {(finding.symbol, finding.destination) for finding in report.findings}
    for edge in _PASSIVE_REQUIRED_EDGES:
        if edge not in edges:
            errors.append(
                f"passive production edge omitted: {edge[0]} -> {edge[1]}"
            )

    for symbol, resources in _PASSIVE_REQUIRED_WRITERS.items():
        discovered = {
            finding.resource
            for finding in report.findings
            if finding.category == "writer"
            and (finding.symbol == symbol or finding.symbol.startswith(symbol + "."))
        }
        missing = sorted(resources - discovered)
        if missing:
            errors.append(
                f"{symbol}: passive donor writer resources omitted: {missing}"
            )

    for finding in report.findings:
        production_source = (
            _source_finding_root(finding) is not None
            or finding.symbol in _PRODUCTION_INTEGRATION_SYMBOLS
            or any(
                finding.symbol.startswith(symbol + ".")
                for symbol in _PRODUCTION_INTEGRATION_SYMBOLS
            )
        )
        if production_source and finding.destination in _FORBIDDEN_PRODUCTION_DESTINATIONS:
            errors.append(
                "hostile ownership/scheduler edge resurrected in production: "
                f"{finding.symbol} -> {finding.destination}"
            )
        if production_source and finding.destination.startswith(
            ("wRendererOwner", "wRendererGeneration")
        ):
            errors.append(
                "passive production mutates Yellow ownership/generation: "
                f"{finding.symbol} -> {finding.destination}"
            )
    return tuple(errors)


def _closed_concrete_subject_errors(
    source_subjects: Mapping[str, set[str]],
) -> tuple[str, ...]:
    required = (
        "WR-P2-YELLOW-BG-PALETTE",
        "WR-P2-YELLOW-OVERLAY-TRANSFER",
    )
    return tuple(
        f"{row_id}: closed audit requires a discoverable concrete source subject"
        for row_id in required
        if not source_subjects.get(row_id)
    )


def _closed_inventory_row_errors(
    rows: Sequence[Mapping[str, object]],
    hashes: Mapping[str, str],
    rom: bytes,
) -> tuple[str, ...]:
    """Keep reviewed hostile rows bound to their audit product and ROM."""
    errors: list[str] = []
    for row in rows:
        row_id = str(row["id"])
        if row_id not in PHASE2_PLANNED_ROW_IDS:
            continue
        evidence = row["evidence"]
        assert isinstance(evidence, Mapping)
        if evidence["reviewed"] is not True:
            errors.append(f"{row_id}: closed audit row became unreviewed")
        for name, expected in hashes.items():
            if evidence[name] != expected:
                errors.append(f"{row_id}: stale audit {name.removesuffix('_sha256')} hash")
        source_sites = (row["source"],) if "source" in row else row.get("source_sites", ())
        if not source_sites:
            errors.append(f"{row_id}: closed audit row lacks source evidence")
        machine_sites = row.get("machine_sites", ())
        if not machine_sites:
            errors.append(f"{row_id}: closed audit row lacks machine evidence")
        for site in machine_sites:
            expected_bytes = bytes.fromhex(site["bytes"])
            start = site["rom_offset"]
            if rom[start : start + len(expected_bytes)] != expected_bytes:
                errors.append(
                    f"{row_id}: audit machine bytes do not match "
                    f"{site['bank']:02x}:{site['address']:04x}"
                )

    palette = next(
        row for row in rows if row["id"] == "WR-P2-YELLOW-BG-PALETTE"
    )
    contract = _CLOSED_PALETTE_ROW_CONTRACT
    reachability = palette["reachability"]
    assert isinstance(reachability, Mapping)
    comparisons = {
        "resource": tuple(palette["resources"]) == contract["resources"],
        "commit": palette["commit_unit"] == contract["commit_unit"],
        "root": tuple(sorted(reachability["roots"])) == contract["roots"],
        "source-site": {
            site["symbol"].split(".", 1)[0]
            for site in palette["source_sites"]
        }
        == set(contract["roots"]),
    }
    errors.extend(
        f"WR-P2-YELLOW-BG-PALETTE: closed audit {name} contract changed"
        for name, matches in comparisons.items()
        if not matches
    )
    return tuple(errors)


def _validate_audit_assignment_enrichments(
    assignments: DiscoveryAssignmentAuthority,
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
) -> None:
    """Validate row semantics without duplicating every descendant site.

    Exact subject ownership is checked separately against the discovered
    subject-to-row projection.  Inventory source and machine sites remain the
    semantic roots of each row instead of becoming an instruction manifest.
    """
    targets = {
        row["id"]: row
        for document in (writers, scenes, mutations)
        for row in document.rows
    }
    errors: list[str] = []
    for assignment in assignments.rows:
        target = targets.get(assignment.row_id)
        if target is None:
            errors.append(f"{assignment.id}: target row does not exist")
            continue
        if assignment.subject.kind.value != "SOURCE_FINDING":
            continue
        if assignment.category.value == "mutation":
            destination = (
                assignment.subject.metadata["destination"]
                if assignment.mutation is None
                else assignment.mutation.destination
            )
            if destination != target["destination"]:
                errors.append(
                    f"{assignment.id}: mutation destination does not match "
                    f"{assignment.row_id}"
                )
        elif assignment.category.value == "scene":
            enrichment = assignment.scene
            destination = target["destination"]
            expected_shape = (
                target["row_kind"],
                target["direction"],
                None if destination is None else destination["path"],
                None if destination is None else destination["line"],
                None if destination is None else destination["symbol"],
            )
            actual_shape = (
                enrichment.row_kind.value,
                enrichment.direction,
                enrichment.destination_path,
                enrichment.destination_line,
                enrichment.destination_symbol,
            )
            if actual_shape != expected_shape:
                errors.append(
                    f"{assignment.id}: scene shape does not match "
                    f"{assignment.row_id}"
                )
    if errors:
        raise ValueError("\n".join(errors))


def _validate_product_assignment_coverage(
    assignments: DiscoveryAssignmentAuthority,
    expected_subject_rows: Mapping[str, str],
    hashes: Mapping[str, str],
    product: str = PHASE2_AUDIT_PRODUCT,
) -> DiscoveryAssignmentAuthority:
    """Require one current assignment for every exact product subject."""
    selected = assignments.for_product(product)
    assigned: dict[str, str] = {}
    errors: list[str] = []
    for row in selected.rows:
        digest = row.subject.sha256
        if digest in assigned:
            errors.append(f"duplicate {product} subject assignment: {digest}")
        assigned[digest] = row.row_id
        for name, expected in hashes.items():
            if getattr(row.evidence, name) != expected:
                errors.append(f"{row.id}: stale {product} {name.removesuffix('_sha256')} identity")
    missing = sorted(set(expected_subject_rows) - set(assigned))
    extra = sorted(set(assigned) - set(expected_subject_rows))
    wrong = sorted(
        digest
        for digest in set(assigned) & set(expected_subject_rows)
        if assigned[digest] != expected_subject_rows[digest]
    )
    if missing:
        errors.append(f"missing {product} subject assignment(s): {missing}")
    if extra:
        errors.append(f"extra {product} subject assignment(s): {extra}")
    if wrong:
        errors.append(f"{product} subject assigned to wrong row: {wrong}")
    if errors:
        raise ValueError("\n".join(errors))
    return selected


# Public compatibility name used by focused guard tests.
_validate_audit_assignment_coverage = _validate_product_assignment_coverage


def _product_hashes(
    source_report: SourceDiscoveryReport, rom_report: object
) -> dict[str, str]:
    return {
        "source_sha256": source_report.source_sha256,
        "rom_sha256": rom_report.rom_sha256,
        "sym_sha256": rom_report.sym_sha256,
        "map_sha256": rom_report.map_sha256,
    }


def _scoped_product_subjects(
    source_report: SourceDiscoveryReport,
    rom_report: object,
    *,
    reviewed_pointer_rows: Mapping[str, str] | None = None,
) -> tuple[tuple[object, ...], tuple[tuple[object, str], ...]]:
    roots = set(_phase2_roots())
    source = tuple(
        finding
        for finding in source_report.findings
        if _source_finding_root(finding) is not None
    )
    rom = tuple(finding for finding in rom_report.findings if finding.root in roots)
    sites: dict[tuple[int, int], list[str]] = {}
    projected: list[tuple[object, str]] = []
    for finding in rom:
        row_id = _planned_rom_row_for(
            finding, reviewed_pointer_rows=reviewed_pointer_rows
        )
        projected.append((finding, row_id))
        sites.setdefault((finding.bank, finding.address), []).append(row_id)
    for finding in rom_report.candidate_findings:
        rows = sites.get((finding.bank, finding.address))
        if rows:
            projected.append((finding, sorted(rows)[0]))
    return source, tuple(projected)


def propose_phase2_subjects(root: Path) -> dict[str, object]:
    """Discover an explicitly unreviewed proposal without editing authority.

    The proposal deliberately contains raw canonical subjects and product
    identities, not assignments or inventory edits.  A reviewer can compare it
    with the checked-in authorities; the official evidence producer only
    verifies those authorities and cannot promote this output.
    """
    source_report = _normalize_closed_scene_directions(discover_phase2_sources(root))
    scoped_source = tuple(
        finding
        for finding in source_report.findings
        if _source_finding_root(finding) is not None
    )
    products: dict[str, object] = {}
    for product in (*PRODUCTION_PRODUCTS, PHASE2_AUDIT_PRODUCT):
        report = discover_phase2_rom_product(root, product)
        roots = set(_phase2_roots())
        products[product] = {
            "hashes": _product_hashes(source_report, report),
            "rom_subjects": [
                rom_finding_subject(finding).to_dict()
                for finding in report.findings
                if finding.root in roots
            ],
            "rom_candidate_subjects": [
                rom_finding_subject(finding).to_dict()
                for finding in report.candidate_findings
                if (finding.bank, finding.address)
                in {
                    (item.bank, item.address)
                    for item in report.findings
                    if item.root in roots
                }
            ],
        }
    return {
        "schema": "full-color-phase2-subject-proposal-v1",
        "reviewed": False,
        "source_sha256": source_report.source_sha256,
        "source_subjects": [
            source_finding_subject(finding).to_dict() for finding in scoped_source
        ],
        "products": products,
    }


def audit_phase2_inventory(root: Path) -> dict[str, object]:
    """Reconcile real guarded source/ROM subjects to declared inventory rows."""
    inventory_root = root / "specs/full-colors/inventory"
    writers = WriterInventory.load(inventory_root / "writers.json")
    scenes = SceneInventory.load(inventory_root / "scenes.json")
    mutations = MutationInventory.load(inventory_root / "mutations.json")
    assignments = DiscoveryAssignmentAuthority.load(inventory_root / "assignments.json")
    authority_rows = [
        row
        for document in (writers, scenes, mutations)
        for row in document.rows
    ]
    try:
        closure_state = _phase2_transition_state(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
        )
    except ValueError as exc:
        raise Phase2MeasurementError(
            f"standalone hostile authority validation failed: {exc}"
        ) from exc
    planned = [row for row in authority_rows if row["planned"]]
    normal_assignments = assignments.for_product(NORMAL_DEBUG_PRODUCT)
    audit_assignments = assignments.for_product(PHASE2_AUDIT_PRODUCT)

    configured_roots = set(_phase2_roots())
    rows = [
        row
        for row in authority_rows
        if configured_roots
        & {
            site["symbol"]
            for site in (
                list(row.get("source_sites", ()))
                + ([row["source"]] if "source" in row else [])
                + ([row["destination"]] if "source" in row and row["destination"] is not None else [])
            )
        }
    ]

    source_sites: dict[tuple[str, int, str], set[str]] = {}
    machine_sites: dict[tuple[int, int], set[str]] = {}
    row_roots: dict[str, set[str]] = {}
    for row in rows:
        allowed = row_roots.setdefault(row["id"], set())
        if "source" in row:
            site = row["source"]
            allowed.add(site["symbol"])
            source_sites.setdefault((site["path"], site["line"], site["symbol"]), set()).add(row["id"])
            if (
                row["destination"] is not None
                and row["destination"]["symbol"] in configured_roots
            ):
                site = row["destination"]
                allowed.add(site["symbol"])
                source_sites.setdefault((site["path"], site["line"], site["symbol"]), set()).add(row["id"])
        for site in row.get("source_sites", ()):
            allowed.add(site["symbol"])
            source_sites.setdefault((site["path"], site["line"], site["symbol"]), set()).add(row["id"])
        for site in row.get("machine_sites", ()):
            machine_sites.setdefault((site["bank"], site["address"]), set()).add(row["id"])

    roots = set(_phase2_roots())

    # Reuse Gate 0's strict v2 transition parser and hash/delta validation on
    # its native reviewed discovery surface.  The hostile report is a distinct
    # scoped projection and must not weaken that contract.
    try:
        baseline_source = discover_baseline_sources(root)
        _, transition = _reviewed_source_view(normal_assignments, baseline_source, root)
        baseline_rom = discover_baseline_rom(root, source_report=baseline_source)
        _reviewed_rom_view(normal_assignments, baseline_rom, transition)
        if closure_state == "planned":
            _validate_planned_rows(
                writers=writers,
                scenes=scenes,
                mutations=mutations,
                assignments=normal_assignments,
                source_report=baseline_source,
                rom_report=baseline_rom,
                rom=(root / "pokeyellow_debug.gbc").read_bytes(),
                repository=root,
            )
        del baseline_source, baseline_rom
        gc.collect()
        source_report = discover_phase2_sources(root)
        rom_report = discover_phase2_rom(root, guarded=True)
    except (OSError, ValueError) as exc:
        raise Phase2MeasurementError(
            f"standalone hostile authority validation failed: {exc}"
        ) from exc

    assignment_counts: dict[str, int] = {}
    if closure_state == "production-closed":
        source_report = _normalize_closed_scene_directions(source_report)

    _reject_duplicate_projection(
        tuple(source_finding_subject(finding).sha256 for finding in source_report.findings),
        "source subjects",
    )
    _reject_duplicate_rom_report(rom_report)
    _reject_duplicate_projection(tuple(source_report.errors), "source diagnostic messages")

    (
        planned_source_authority,
        planned_rom_authority,
        planned_candidate_authority,
        planned_unresolved_authority,
        planned_source_error_authority,
        planned_only_authority,
    ) = _load_planned_subjects(root, closed=closure_state == "production-closed")

    actual_source_errors = tuple(
        sorted(source_error_subject(message).sha256 for message in source_report.errors)
    )
    if closure_state == "production-closed":
        diagnostic_shapes = tuple(
            re.sub(r":\d+:", ":<line>:", message)
            for message in source_report.errors
        )
        if (
            len(diagnostic_shapes) != len(planned_source_error_authority)
            or len(set(diagnostic_shapes)) != len(diagnostic_shapes)
            or any(
                not message.endswith(": unresolved jp destination hl")
                for message in diagnostic_shapes
            )
        ):
            raise Phase2MeasurementError(
                "source diagnostic dispositions changed: expected one unique "
                "known dynamic-jump limitation per reviewed semantic site"
            )
    elif actual_source_errors != planned_source_error_authority:
        raise Phase2MeasurementError(
            "source diagnostic dispositions changed: every diagnostic must appear "
            "exactly once in the hash-bound authority"
        )

    scoped_source = tuple(
        finding
        for finding in source_report.findings
        if _source_finding_root(finding) is not None
    )
    scoped_rom = tuple(
        finding for finding in rom_report.findings if finding.root in roots
    )
    scoped_sites = {(finding.bank, finding.address) for finding in scoped_rom}
    scoped_candidates = tuple(
        finding
        for finding in rom_report.candidate_findings
        if (finding.bank, finding.address) in scoped_sites
    )
    scoped_unresolved = tuple(
        message
        for message in (
            *rom_report.unresolved_destinations,
            *rom_report.unresolved_control_flow,
        )
        if message.split(":", 1)[0] in roots
    )
    _validate_passive_rom_pointer_authority(scoped_rom)
    actual_source_subjects: dict[str, set[str]] = {
        row_id: set() for row_id in PHASE2_PLANNED_ROW_IDS
    }
    actual_rom_subjects: dict[str, set[str]] = {
        row_id: set() for row_id in PHASE2_PLANNED_ROW_IDS
    }
    actual_candidate_subjects: dict[str, set[str]] = {
        row_id: set() for row_id in PHASE2_PLANNED_ROW_IDS
    }
    for finding in scoped_source:
        finding_root = _source_finding_root(finding)
        assert finding_root is not None
        actual_source_subjects[_planned_row_for(
            finding_root, finding.category, resource=finding.resource,
        )].add(
            source_finding_subject(finding).sha256
        )
    site_rows: dict[tuple[int, int], list[tuple[bool, str]]] = {}
    for finding in scoped_rom:
        row_id = _planned_rom_row_for(finding)
        actual_rom_subjects[row_id].add(rom_finding_subject(finding).sha256)
        site_rows.setdefault((finding.bank, finding.address), []).append(
            (finding.category != "writer", row_id)
        )
    for finding in scoped_candidates:
        row_id = sorted(site_rows[(finding.bank, finding.address)])[0][1]
        actual_candidate_subjects[row_id].add(rom_finding_subject(finding).sha256)
    semantic_subject_errors = []
    for row_id in sorted(PHASE2_PLANNED_ROW_IDS):
        actual_source = tuple(sorted(actual_source_subjects[row_id]))
        actual_rom = tuple(sorted(actual_rom_subjects[row_id]))
        actual_candidates = tuple(sorted(actual_candidate_subjects[row_id]))
        if closure_state != "production-closed" and actual_source != planned_source_authority[row_id]:
            semantic_subject_errors.append(
                f"{row_id}: source subjects {actual_source} != {planned_source_authority[row_id]}"
            )
        if closure_state != "production-closed" and actual_rom != planned_rom_authority[row_id]:
            semantic_subject_errors.append(
                f"{row_id}: ROM subjects {actual_rom} != {planned_rom_authority[row_id]}"
            )
        if closure_state != "production-closed" and actual_candidates != planned_candidate_authority[row_id]:
            semantic_subject_errors.append(
                f"{row_id}: ROM candidate subjects {actual_candidates} != "
                f"{planned_candidate_authority[row_id]}"
            )
        if closure_state == "production-closed":
            if actual_source and not planned_source_authority[row_id]:
                semantic_subject_errors.append(
                    f"{row_id}: source subjects authority is empty for a non-empty "
                    "closed row"
                )
            if actual_rom and not planned_rom_authority[row_id]:
                semantic_subject_errors.append(
                    f"{row_id}: ROM subjects authority is empty for a non-empty "
                    "closed row"
                )
            if actual_candidates and not planned_candidate_authority[row_id]:
                semantic_subject_errors.append(
                    f"{row_id}: ROM candidate subjects authority is empty for a "
                    "non-empty closed row"
                )
        unresolved_count = tuple(planned_unresolved_authority.values()).count(row_id)
        has_role_evidence = bool(
            actual_source_subjects[row_id]
            or actual_rom_subjects[row_id]
            or actual_candidate_subjects[row_id]
            or unresolved_count
        )
        if not has_role_evidence and row_id not in planned_only_authority:
            semantic_subject_errors.append(
                f"{row_id}: exact planned row has no row-bound semantic evidence"
            )
    if closure_state != "production-closed" and dict(sorted((item, _planned_row_for(item.split(":", 1)[0], "control_flow")) for item in scoped_unresolved)) != planned_unresolved_authority:
        semantic_subject_errors.append("scoped ROM unresolved dispositions changed")

    if closure_state == "production-closed":
        product_reports = {
            product: discover_phase2_rom_product(root, product)
            for product in (*PRODUCTION_PRODUCTS, PHASE2_AUDIT_PRODUCT)
        }
        for product, product_report in product_reports.items():
            _reject_duplicate_rom_report(product_report, product)
            reviewed_pointer_rows = {
                row.subject.sha256: row.row_id
                for row in assignments.for_product(product).rows
                if row.subject.kind.value == "ROM_FINDING"
            }
            product_source, product_rom = _scoped_product_subjects(
                source_report,
                product_report,
                reviewed_pointer_rows=reviewed_pointer_rows,
            )
            expected_subject_rows: dict[str, str] = {}
            for finding in product_source:
                source_root = _source_finding_root(finding)
                assert source_root is not None
                expected_subject_rows[source_finding_subject(finding).sha256] = (
                    _planned_row_for(
                        source_root, finding.category, resource=finding.resource
                    )
                )
            for finding, row_id in product_rom:
                digest = rom_finding_subject(finding).sha256
                previous = expected_subject_rows.setdefault(digest, row_id)
                if previous != row_id:
                    semantic_subject_errors.append(
                        f"{product}: subject {digest} is ambiguously owned by "
                        f"{previous} and {row_id}"
                    )
            hashes = _product_hashes(source_report, product_report)
            try:
                product_assignments = _validate_product_assignment_coverage(
                    assignments, expected_subject_rows, hashes, product
                )
                _validate_audit_assignment_enrichments(
                    product_assignments, writers, scenes, mutations
                )
                matcher = product_assignments.matcher(**hashes, product=product)
                for finding in product_source:
                    matcher.project_source_finding(finding)
                for finding, _ in product_rom:
                    matcher.project_rom_finding(finding)
                matcher.assert_all_consumed()
                assignment_counts[product] = len(product_assignments.rows)
            except (ValueError, StaleDiscoveryAssignmentError) as exc:
                semantic_subject_errors.append(
                    f"{product} assignment closure failed: {exc}"
                )

        debug_report = product_reports[DEBUG_PRODUCT]
        debug_hashes = _product_hashes(source_report, debug_report)
        phase2_rows = {
            row["id"]: row for row in authority_rows
            if row["id"] in PHASE2_PLANNED_ROW_IDS
        }
        stale_rows = sorted(
            row_id
            for row_id, row in phase2_rows.items()
            if any(
                row["evidence"][name] != digest
                for name, digest in debug_hashes.items()
            )
        )
        if stale_rows:
            semantic_subject_errors.append(
                f"production inventory rows have stale debug identities: {stale_rows}"
            )
        semantic_subject_errors.extend(
            _closed_inventory_row_errors(
                authority_rows, debug_hashes,
                (root / "pokeyellow_debug.gbc").read_bytes(),
            )
        )
        semantic_subject_errors.extend(
            _closed_concrete_subject_errors(actual_source_subjects)
        )
        semantic_subject_errors.extend(
            _passive_production_contract_errors(source_report)
        )
    inventory_report = (
        discover_phase2_rom_product(root, DEBUG_PRODUCT)
        if closure_state == "production-closed"
        else rom_report
    )
    inventory_rom = tuple(
        finding for finding in inventory_report.findings if finding.root in roots
    )
    discovered_source_sites = {finding.site_key for finding in scoped_source}
    discovered_rom_sites = {finding.site_key for finding in inventory_rom}
    missing_source = sorted(set(source_sites) - discovered_source_sites)
    missing_rom = sorted(set(machine_sites) - discovered_rom_sites)
    # Every configured root must have both a source subject and ROM root-entry subject.
    source_root_names = {
        item.symbol for item in scoped_source if item.mechanism == "configured-root"
    }
    rom_root_names = {
        item.root for item in inventory_rom if item.mechanism == "root-entry"
    }
    missing_roots = sorted(roots - source_root_names | roots - rom_root_names)
    pallet_header = (root / "data/maps/headers/PalletTown.asm").read_text(
        encoding="utf-8"
    )
    route_header = (root / "data/maps/headers/Route1.asm").read_text(encoding="utf-8")
    concrete_slice_ok = (
        "map_header PalletTown, PALLET_TOWN, OVERWORLD" in pallet_header
        and "connection north, Route1, ROUTE_1" in pallet_header
        and "map_header Route1, ROUTE_1, OVERWORLD" in route_header
        and {"PalletTown_h", "Route1_h"} <= source_root_names
        and {"PalletTown_h", "Route1_h"} <= rom_root_names
    )
    yellow_restoration_ok = (
        any(
            item.symbol == "DisplayPartyMenu"
            and item.destination == "PartyMenuInit"
            and item.row_kind == "DIRECTED_EDGE"
            and item.direction
            == (
                "YELLOW_TO_YELLOW"
                if closure_state == "production-closed"
                else "MAP_TO_YELLOW"
            )
            for item in scoped_source
        )
        and any(
            item.symbol == "StartMenu_Pokemon.exitMenu"
            and item.destination == "RestoreScreenTilesAndReloadTilePatterns"
            and item.row_kind == "DIRECTED_EDGE"
            and item.direction == "YELLOW_TO_YELLOW"
            for item in scoped_source
        )
    )
    if missing_source or missing_rom or missing_roots or semantic_subject_errors:
        raise Phase2MeasurementError(
            "hostile inventory audit lacks exact evidence: source="
            f"{missing_source}, ROM={missing_rom}, roots={missing_roots}, "
            f"subjects={semantic_subject_errors}"
        )
    if not concrete_slice_ok or not yellow_restoration_ok:
        raise Phase2MeasurementError(
            "passive slice directed source/ROM identity is not exact"
        )
    return {
        "concrete_slice": ["PalletTown_h", "Route1_h", "OVERWORLD", "NORTH"],
        "guard": AUDIT_GUARD,
        "guarded_root_count": len(roots),
        "normal_rom_reachable": True,
        "production_products": list(PRODUCTION_PRODUCTS),
        "diagnostic_product": PHASE2_AUDIT_PRODUCT,
        "product_assignment_counts": assignment_counts,
        "planned_assignment_count": sum(assignment_counts.values()),
        "planned_row_count": len(planned),
        "inventory_state": closure_state,
        "coverage": "SCOPED_DESCENDANT_CLOSURE",
        "rom_candidate_subject_count": len(scoped_candidates),
        "rom_subject_count": len(scoped_rom),
        "rom_unlisted_subject_count": 0,
        "rom_unresolved_disposition_count": len(scoped_unresolved),
        "source_subject_count": len(scoped_source),
        "source_unlisted_subject_count": 0,
    }


def measure(root: Path) -> Phase2Measurement:
    root = root.resolve()
    paths = {
        name: root / name
        for name in (
            "pokeyellow.gbc", "pokeyellow.map", "pokeyellow.sym",
            "pokeyellow_debug.gbc", "pokeyellow_debug.map", "pokeyellow_debug.sym",
            "pokeyellow_vc.gbc", "pokeyellow_vc.map", "pokeyellow_vc.sym",
            "pokeyellow_phase2_audit.gbc", "pokeyellow_phase2_audit.map", "pokeyellow_phase2_audit.sym",
            DEFINITION_PATH, SOURCE_TRANSITION_PATH, PLANNED_SUBJECTS_PATH,
            "specs/full-colors/inventory/assignments.json",
            "specs/full-colors/inventory/mutations.json",
            "specs/full-colors/inventory/scenes.json",
            "specs/full-colors/inventory/writers.json",
        )
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise Phase2MeasurementError("missing measurement input(s): " + ", ".join(missing))
    release = _parse_sections(paths["pokeyellow.map"])
    debug = _parse_sections(paths["pokeyellow_debug.map"])
    margin = min(
        _stack_margin(paths["pokeyellow.sym"], release),
        _stack_margin(paths["pokeyellow_debug.sym"], debug),
    )
    if margin < MINIMUM_STACK_MARGIN:
        raise Phase2MeasurementError("measured stack margin regressed below minimum")

    ownership = [
        (bank, low, high)
        for (kind, bank), values in debug.items()
        if kind == "WRAMX"
        for low, high, name in values
        if name == "Full Color Ownership State"
    ]
    if len(ownership) != 1 or ownership[0][2] - ownership[0][1] + 1 != PHASE1_STATE_BYTES:
        raise Phase2MeasurementError("debug link does not preserve the Phase 1 ownership state")
    wbank, _, ownership_end = ownership[0]
    common_wram = _intersection(
        _free(WRAMX_START, WRAMX_END, release.get(("WRAMX", wbank), ())),
        _free(WRAMX_START, WRAMX_END, debug.get(("WRAMX", wbank), ())),
    )
    common_wram = [(max(low, ownership_end + 1), high) for low, high in common_wram if high > ownership_end]

    common_sram = _intersection(
        _free(SRAM_START, SRAM_END, release.get(("SRAM", 3), ())),
        _free(SRAM_START, SRAM_END, debug.get(("SRAM", 3), ())),
    )
    core = [
        (bank, low, high)
        for (kind, bank), values in debug.items()
        if kind == "ROMX"
        for low, high, name in values
        if name == "Full Color Ownership Core"
    ]
    if len(core) != 1:
        raise Phase2MeasurementError("debug link does not define one ownership core")
    core_bank, _, core_end = core[0]
    common_rom = _intersection(
        _free(ROMX_START, ROMX_END, release.get(("ROMX", core_bank), ())),
        _free(ROMX_START, ROMX_END, debug.get(("ROMX", core_bank), ())),
    )
    common_rom = [(max(low, core_end + 1), high) for low, high in common_rom if high > core_end]
    if not common_wram or not common_sram or not common_rom:
        raise Phase2MeasurementError("release/debug products have no common Phase 2 placement")

    candidates = tuple(
        Phase2Candidate(
            wbank, wl, wh, 3, sl, sh, core_bank, rl, rh, margin,
            ownership_adjacent=(wl == ownership_end + 1 and rl == core_end + 1),
        )
        for wl, wh in common_wram
        for sl, sh in common_sram
        for rl, rh in common_rom
    )
    rejected = tuple(
        (f"ROM bank ${bank:02x}", reason)
        for bank, reason in sorted(FORBIDDEN_ROM_BANKS.items())
    )
    definition = load_definition(paths[DEFINITION_PATH])
    return Phase2Measurement(
        {name: _sha(path) for name, path in paths.items()},
        definition,
        definition.classes,
        definition.descriptor_bytes,
        definition.scratch_bytes,
        candidates,
        rejected,
        inventory_audit=audit_phase2_inventory(root),
    )


def generate(root: Path) -> Phase2Decision:
    return select_phase2_representation(measure(root))


def verify_evidence(root: Path, evidence_path: Path) -> Phase2Decision:
    decision = generate(root)
    if evidence_path.read_text(encoding="utf-8") != decision.to_json():
        raise Phase2MeasurementError(
            f"stale or edited Phase 2 representation: regenerate {evidence_path}"
        )
    return decision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--output", type=Path)
    outputs.add_argument("--proposal-output", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--authority-reviewed",
        action="store_true",
        help="confirm human-reviewed authorities before writing accepted evidence",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.proposal_output is not None:
            if args.verify or args.authority_reviewed:
                raise Phase2MeasurementError(
                    "review/verify flags apply only to reviewed evidence, not proposals"
                )
            proposal = propose_phase2_subjects(args.root.resolve())
            args.proposal_output.parent.mkdir(parents=True, exist_ok=True)
            args.proposal_output.write_text(
                json.dumps(proposal, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.verify:
            if args.authority_reviewed:
                raise Phase2MeasurementError(
                    "--authority-reviewed is not needed for read-only verification"
                )
            assert args.output is not None
            verify_evidence(args.root, args.output)
        else:
            assert args.output is not None
            if not args.authority_reviewed:
                raise Phase2MeasurementError(
                    "writing accepted Phase 2 evidence requires --authority-reviewed "
                    "after human review"
                )
            decision = generate(args.root)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(decision.to_json(), encoding="utf-8")
    except (OSError, Phase2MeasurementError) as exc:
        _parser().error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
