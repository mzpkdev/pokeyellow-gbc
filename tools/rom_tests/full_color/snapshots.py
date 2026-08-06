"""Versioned semantic snapshots and exact-offset structured comparison."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from ._validation import (
    require_bool,
    require_enum,
    require_hex,
    require_int,
    require_object,
    require_str,
)
from .enums import (
    CancellationReason,
    JobState,
    OAMFallbackKind,
    OverlayCell,
    OverlayDestination,
    Owner,
    Phase,
    ReconstructionProvenance,
    RequestResult,
)
from .errors import SnapshotValidationError

SNAPSHOT_SCHEMA = "full-color-contract-v1"
TILEMAP_BYTES = 2 * 32 * 32
PALETTE_BYTES = 64
OAM_BYTES = 160
REQUIRED_RECONSTRUCTION_ITEMS = frozenset(
    {
        "map_tileset_overrides",
        "viewport_scroll_window_destination",
        "tiles_animation_field_replacements",
        "tilemaps_and_attributes",
        "base_transformed_hardware_palettes",
        "player_follower_object_shadow_oam",
        "request_scheduler_state",
        "machine_state_restored",
    }
)
RECONSTRUCTION_ITEM_PROVENANCE = {
    "map_tileset_overrides": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "viewport_scroll_window_destination": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "tiles_animation_field_replacements": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "tilemaps_and_attributes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "base_transformed_hardware_palettes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "player_follower_object_shadow_oam": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "request_scheduler_state": ReconstructionProvenance.INITIALIZED_SCHEDULER_STATE,
    "machine_state_restored": ReconstructionProvenance.RESTORED_MACHINE_STATE,
}
FORBIDDEN_RECONSTRUCTION_PROVENANCE = frozenset(
    {
        ReconstructionProvenance.CAPTURED_VRAM,
        ReconstructionProvenance.SAVED_VRAM,
        ReconstructionProvenance.CAPTURED_PALETTE_RAM,
        ReconstructionProvenance.SAVED_PALETTE_RAM,
        ReconstructionProvenance.CAPTURED_OAM,
        ReconstructionProvenance.SAVED_OAM,
        ReconstructionProvenance.CAPTURED_SCREEN_BUFFER,
        ReconstructionProvenance.SAVED_SCREEN_BUFFER,
    }
)


@dataclass(frozen=True, slots=True)
class BankState:
    rom: int
    wram: int
    vram: int

    @classmethod
    def from_dict(cls, raw: object) -> BankState:
        obj = require_object(
            raw,
            path="banks",
            required={"rom", "wram", "vram"},
            error=SnapshotValidationError,
        )
        return cls(
            rom=require_int(obj["rom"], path="banks.rom", maximum=0x1FF, error=SnapshotValidationError),
            wram=require_int(obj["wram"], path="banks.wram", maximum=7, error=SnapshotValidationError),
            vram=require_int(obj["vram"], path="banks.vram", maximum=1, error=SnapshotValidationError),
        )

    def to_dict(self) -> dict[str, int]:
        return {"rom": self.rom, "wram": self.wram, "vram": self.vram}


@dataclass(frozen=True, slots=True)
class SnapshotJob:
    job_id: str
    request_ids: tuple[str, ...]
    resources: tuple[str, ...]
    state: JobState
    cancellation_reason: CancellationReason | None
    commit_unit_id: str | None
    owner: Owner
    generation: int

    @classmethod
    def from_dict(cls, raw: object, *, path: str = "job") -> SnapshotJob:
        obj = require_object(
            raw,
            path=path,
            required={
                "job_id", "request_ids", "resources", "state",
                "cancellation_reason", "commit_unit_id", "owner", "generation",
            },
            error=SnapshotValidationError,
        )
        state = require_enum(
            JobState, obj["state"], path=f"{path}.state", error=SnapshotValidationError
        )
        reason_raw = obj["cancellation_reason"]
        reason = (
            None
            if reason_raw is None
            else require_enum(
                CancellationReason,
                reason_raw,
                path=f"{path}.cancellation_reason",
                error=SnapshotValidationError,
            )
        )
        if state is JobState.CANCELLED and reason is None:
            raise SnapshotValidationError(
                f"{path}.cancellation_reason: CANCELLED jobs require exactly one reason"
            )
        if state is not JobState.CANCELLED and reason is not None:
            raise SnapshotValidationError(
                f"{path}.cancellation_reason: only CANCELLED jobs may carry a reason"
            )
        commit_raw = obj["commit_unit_id"]
        commit = (
            None
            if commit_raw is None
            else require_str(
                commit_raw,
                path=f"{path}.commit_unit_id",
                error=SnapshotValidationError,
            )
        )
        request_ids = _string_array(obj["request_ids"], path=f"{path}.request_ids")
        resources = _string_array(obj["resources"], path=f"{path}.resources")
        if not request_ids:
            raise SnapshotValidationError(f"{path}.request_ids: expected at least one ID")
        if not resources:
            raise SnapshotValidationError(f"{path}.resources: expected at least one resource")
        return cls(
            job_id=require_str(obj["job_id"], path=f"{path}.job_id", error=SnapshotValidationError),
            request_ids=request_ids,
            resources=resources,
            state=state,
            cancellation_reason=reason,
            commit_unit_id=commit,
            owner=require_enum(
                Owner, obj["owner"], path=f"{path}.owner", error=SnapshotValidationError
            ),
            generation=require_int(
                obj["generation"], path=f"{path}.generation", error=SnapshotValidationError
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "request_ids": list(self.request_ids),
            "resources": list(self.resources),
            "state": self.state.value,
            "cancellation_reason": (
                None if self.cancellation_reason is None else self.cancellation_reason.value
            ),
            "commit_unit_id": self.commit_unit_id,
            "owner": self.owner.value,
            "generation": self.generation,
        }


@dataclass(frozen=True, slots=True)
class ReconstructionState:
    required_items: tuple[str, ...]
    completed_items: tuple[str, ...]
    item_provenance: tuple[tuple[str, ReconstructionProvenance], ...]
    poisoned_items: tuple[str, ...]
    unknown_prior_state: bool
    presentation_barrier_count: int

    @classmethod
    def from_dict(cls, raw: object) -> ReconstructionState:
        obj = require_object(
            raw,
            path="reconstruction",
            required={
                "required_items", "completed_items", "poisoned_items",
                "item_provenance", "unknown_prior_state",
                "presentation_barrier_count",
            },
            error=SnapshotValidationError,
        )
        required = _string_array(
            obj["required_items"], path="reconstruction.required_items"
        )
        completed = _string_array(
            obj["completed_items"], path="reconstruction.completed_items"
        )
        poisoned = _string_array(
            obj["poisoned_items"], path="reconstruction.poisoned_items"
        )
        provenance_obj = require_object(
            obj["item_provenance"],
            path="reconstruction.item_provenance",
            required=set(completed),
            error=SnapshotValidationError,
        )
        provenance = tuple(
            (
                item,
                require_enum(
                    ReconstructionProvenance,
                    provenance_obj[item],
                    path=f"reconstruction.item_provenance.{item}",
                    error=SnapshotValidationError,
                ),
            )
            for item in sorted(provenance_obj)
        )
        if set(required) != REQUIRED_RECONSTRUCTION_ITEMS:
            missing = sorted(REQUIRED_RECONSTRUCTION_ITEMS - set(required))
            extra = sorted(set(required) - REQUIRED_RECONSTRUCTION_ITEMS)
            raise SnapshotValidationError(
                "reconstruction.required_items: authoritative ledger mismatch "
                f"(missing={missing}, extra={extra})"
            )
        if set(completed) - set(required):
            raise SnapshotValidationError(
                "reconstruction.completed_items: contains undeclared items"
            )
        if set(poisoned) - set(required):
            raise SnapshotValidationError(
                "reconstruction.poisoned_items: contains undeclared items"
            )
        for item, source in provenance:
            if source in FORBIDDEN_RECONSTRUCTION_PROVENANCE:
                raise SnapshotValidationError(
                    "reconstruction.item_provenance: captured/saved display state "
                    f"cannot satisfy {item}"
                )
            expected = RECONSTRUCTION_ITEM_PROVENANCE[item]
            if source is not expected:
                raise SnapshotValidationError(
                    f"reconstruction.item_provenance.{item}: expected authoritative "
                    f"source {expected.value}, got {source.value}"
                )
        return cls(
            required_items=required,
            completed_items=completed,
            item_provenance=provenance,
            poisoned_items=poisoned,
            unknown_prior_state=require_bool(
                obj["unknown_prior_state"],
                path="reconstruction.unknown_prior_state",
                error=SnapshotValidationError,
            ),
            presentation_barrier_count=require_int(
                obj["presentation_barrier_count"],
                path="reconstruction.presentation_barrier_count",
                maximum=1,
                error=SnapshotValidationError,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_items": list(self.required_items),
            "completed_items": list(self.completed_items),
            "item_provenance": {
                item: provenance.value for item, provenance in self.item_provenance
            },
            "poisoned_items": list(self.poisoned_items),
            "unknown_prior_state": self.unknown_prior_state,
            "presentation_barrier_count": self.presentation_barrier_count,
        }


@dataclass(frozen=True, slots=True)
class OverlayRequestState:
    destination_selector: OverlayDestination
    map_id: str
    tileset_id: str
    rectangle: tuple[int, int, int, int]
    world_origin: tuple[int, int] | None
    world_transform: tuple[int, int, int, int, int, int] | None
    coordinate_overrides: tuple[tuple[str, int], ...]
    classifications: tuple[OverlayCell, ...]
    tile_ids: bytes
    attributes: bytes | None
    clipped_mappings: tuple[tuple[int, int, int, int, int], ...]
    oracle_sources: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: object) -> OverlayRequestState:
        obj = require_object(
            raw,
            path="overlay_request",
            required={
                "destination_selector", "map_id", "tileset_id", "rectangle",
                "world_origin", "world_transform", "coordinate_overrides",
                "classifications", "tile_ids", "attributes",
                "clipped_mappings", "oracle_sources",
            },
            error=SnapshotValidationError,
        )
        destination = require_enum(
            OverlayDestination,
            obj["destination_selector"],
            path="overlay_request.destination_selector",
            error=SnapshotValidationError,
        )
        rectangle_obj = require_object(
            obj["rectangle"],
            path="overlay_request.rectangle",
            required={"x", "y", "width", "height"},
            error=SnapshotValidationError,
        )
        rectangle = (
            _require_signed_int(
                rectangle_obj["x"], path="overlay_request.rectangle.x"
            ),
            _require_signed_int(
                rectangle_obj["y"], path="overlay_request.rectangle.y"
            ),
            require_int(
                rectangle_obj["width"],
                path="overlay_request.rectangle.width",
                error=SnapshotValidationError,
            ),
            require_int(
                rectangle_obj["height"],
                path="overlay_request.rectangle.height",
                error=SnapshotValidationError,
            ),
        )
        if rectangle[2] < 1 or rectangle[3] < 1:
            raise SnapshotValidationError(
                "overlay_request.rectangle: width and height must be positive"
            )
        area = rectangle[2] * rectangle[3]
        origin = _optional_coordinate(obj["world_origin"], path="overlay_request.world_origin")
        transform = _optional_int_array(
            obj["world_transform"], path="overlay_request.world_transform", length=6
        )
        if (origin is None) == (transform is None):
            raise SnapshotValidationError(
                "overlay_request: exactly one world_origin or world_transform is required"
            )
        if transform is not None:
            a, b, c, d, _, _ = transform
            if a * d - b * c == 0:
                raise SnapshotValidationError(
                    "overlay_request.world_transform: singular transform loses "
                    "source-to-world mapping"
                )
        overrides_obj = require_object(
            obj["coordinate_overrides"],
            path="overlay_request.coordinate_overrides",
            required=set(),
            optional=(
                set(obj["coordinate_overrides"])
                if isinstance(obj["coordinate_overrides"], dict)
                else set()
            ),
            error=SnapshotValidationError,
        )
        overrides = tuple(
            (
                require_str(
                    key,
                    path="overlay_request.coordinate_overrides key",
                    error=SnapshotValidationError,
                ),
                require_int(
                    overrides_obj[key],
                    path=f"overlay_request.coordinate_overrides.{key}",
                    maximum=0xFF,
                    error=SnapshotValidationError,
                ),
            )
            for key in sorted(overrides_obj)
        )
        classifications_raw = obj["classifications"]
        if not isinstance(classifications_raw, list) or len(classifications_raw) != area:
            raise SnapshotValidationError(
                f"overlay_request.classifications: expected exactly {area} cells"
            )
        classifications = tuple(
            require_enum(
                OverlayCell,
                value,
                path=f"overlay_request.classifications[{index}]",
                error=SnapshotValidationError,
            )
            for index, value in enumerate(classifications_raw)
        )
        tile_ids = require_hex(
            obj["tile_ids"],
            path="overlay_request.tile_ids",
            length=area,
            error=SnapshotValidationError,
        )
        attributes = (
            None
            if obj["attributes"] is None
            else require_hex(
                obj["attributes"],
                path="overlay_request.attributes",
                length=area,
                error=SnapshotValidationError,
            )
        )
        mappings_raw = obj["clipped_mappings"]
        if not isinstance(mappings_raw, list):
            raise SnapshotValidationError("overlay_request.clipped_mappings: expected an array")
        mappings: list[tuple[int, int, int, int, int]] = []
        for index, mapping_raw in enumerate(mappings_raw):
            path = f"overlay_request.clipped_mappings[{index}]"
            mapping_obj = require_object(
                mapping_raw,
                path=path,
                required={"source_index", "destination_x", "destination_y", "world_x", "world_y"},
                error=SnapshotValidationError,
            )
            mapping = (
                require_int(
                    mapping_obj["source_index"],
                    path=f"{path}.source_index",
                    error=SnapshotValidationError,
                ),
                _require_signed_int(
                    mapping_obj["destination_x"], path=f"{path}.destination_x"
                ),
                _require_signed_int(
                    mapping_obj["destination_y"], path=f"{path}.destination_y"
                ),
                _require_signed_int(mapping_obj["world_x"], path=f"{path}.world_x"),
                _require_signed_int(mapping_obj["world_y"], path=f"{path}.world_y"),
            )
            if mapping[0] >= area:
                raise SnapshotValidationError(f"{path}.source_index: outside source rectangle")
            mappings.append(mapping)
        mapped_sources = {item[0] for item in mappings}
        expected_sources = {
            source_index
            for source_index in range(area)
            if 0
            <= rectangle[0] + source_index % rectangle[2]
            < 32
            and 0
            <= rectangle[1] + source_index // rectangle[2]
            < 32
        }
        if len(mapped_sources) != len(mappings) or mapped_sources != expected_sources:
            raise SnapshotValidationError(
                "overlay_request.clipped_mappings: source mapping loss or duplicate"
            )
        for mapping in mappings:
            source_index, destination_x, destination_y, world_x, world_y = mapping
            expected_destination = (
                rectangle[0] + source_index % rectangle[2],
                rectangle[1] + source_index // rectangle[2],
            )
            if (destination_x, destination_y) != expected_destination:
                raise SnapshotValidationError(
                    "overlay_request.clipped_mappings: destination mapping loss"
                )
            source_x = source_index % rectangle[2]
            source_y = source_index // rectangle[2]
            if origin is not None:
                expected_world = (origin[0] + source_x, origin[1] + source_y)
            else:
                if transform is None:
                    raise SnapshotValidationError(
                        "overlay_request.world_transform: required for transform mapping"
                    )
                a, b, c, d, tx, ty = transform
                expected_world = (
                    a * source_x + b * source_y + tx,
                    c * source_x + d * source_y + ty,
                )
            if (world_x, world_y) != expected_world:
                raise SnapshotValidationError(
                    "overlay_request.clipped_mappings: world-coordinate mapping loss "
                    "or transform contamination"
                )
        if attributes is not None and any(attribute & 0x10 for attribute in attributes):
            raise SnapshotValidationError(
                "overlay_request.attributes: attribute bit 4 must be canonical zero"
            )
        oracle_sources = _string_array(
            obj["oracle_sources"], path="overlay_request.oracle_sources"
        )
        forbidden = sorted(set(oracle_sources) & {"VRAM", "AMBIENT_MAP"})
        if forbidden:
            raise SnapshotValidationError(
                "overlay_request.oracle_sources: contaminated by " + ", ".join(forbidden)
            )
        if set(oracle_sources) != {"REQUEST_DATA"}:
            raise SnapshotValidationError(
                "overlay_request.oracle_sources: REQUEST_DATA must be the sole oracle"
            )
        return cls(
            destination_selector=destination,
            map_id=require_str(obj["map_id"], path="overlay_request.map_id", error=SnapshotValidationError),
            tileset_id=require_str(
                obj["tileset_id"], path="overlay_request.tileset_id", error=SnapshotValidationError
            ),
            rectangle=rectangle,
            world_origin=origin,
            world_transform=transform,
            coordinate_overrides=overrides,
            classifications=classifications,
            tile_ids=tile_ids,
            attributes=attributes,
            clipped_mappings=tuple(mappings),
            oracle_sources=oracle_sources,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_selector": self.destination_selector.value,
            "map_id": self.map_id,
            "tileset_id": self.tileset_id,
            "rectangle": dict(zip(("x", "y", "width", "height"), self.rectangle, strict=True)),
            "world_origin": (
                None if self.world_origin is None else {"x": self.world_origin[0], "y": self.world_origin[1]}
            ),
            "world_transform": (
                None if self.world_transform is None else list(self.world_transform)
            ),
            "coordinate_overrides": dict(self.coordinate_overrides),
            "classifications": [item.value for item in self.classifications],
            "tile_ids": self.tile_ids.hex(),
            "attributes": None if self.attributes is None else self.attributes.hex(),
            "clipped_mappings": [
                dict(
                    zip(
                        ("source_index", "destination_x", "destination_y", "world_x", "world_y"),
                        item,
                        strict=True,
                    )
                )
                for item in self.clipped_mappings
            ],
            "oracle_sources": list(self.oracle_sources),
        }


@dataclass(frozen=True, slots=True)
class OAMFallbackState:
    occurred: bool
    fallback_kind: OAMFallbackKind | None
    object_id: str | None
    final_tile_id: int | None
    identity: int | None
    generation: int | None
    writer_id: str | None
    palette: int | None
    before_attributes: int
    after_attributes: int

    @classmethod
    def from_dict(cls, raw: object) -> OAMFallbackState:
        obj = require_object(
            raw,
            path="oam_fallback",
            required={
                "occurred", "fallback_kind", "object_id", "final_tile_id",
                "identity", "generation", "writer_id", "palette",
                "before_attributes", "after_attributes",
            },
            error=SnapshotValidationError,
        )
        occurred = require_bool(
            obj["occurred"], path="oam_fallback.occurred", error=SnapshotValidationError
        )
        kind_raw = obj["fallback_kind"]
        kind = (
            None
            if kind_raw is None
            else require_enum(
                OAMFallbackKind,
                kind_raw,
                path="oam_fallback.fallback_kind",
                error=SnapshotValidationError,
            )
        )
        object_id = _optional_string_value(obj["object_id"], path="oam_fallback.object_id")
        final_tile = _optional_int(obj["final_tile_id"], path="oam_fallback.final_tile_id")
        identity = _optional_int(obj["identity"], path="oam_fallback.identity")
        generation = _optional_int(obj["generation"], path="oam_fallback.generation")
        writer_id = _optional_string_value(obj["writer_id"], path="oam_fallback.writer_id")
        palette = _optional_int(obj["palette"], path="oam_fallback.palette", maximum=7)
        before = require_int(
            obj["before_attributes"], path="oam_fallback.before_attributes",
            maximum=0xFF, error=SnapshotValidationError
        )
        after = require_int(
            obj["after_attributes"], path="oam_fallback.after_attributes",
            maximum=0xFF, error=SnapshotValidationError
        )
        evidence = (kind, object_id, final_tile, generation, writer_id)
        if occurred and (any(value is None for value in evidence) or palette != 0):
            raise SnapshotValidationError(
                "oam_fallback: fallback requires kind, object, final tile, "
                "generation, writer ID, and palette 0"
            )
        if not occurred and any(
            value is not None
            for value in (kind, object_id, final_tile, identity, generation, writer_id)
        ):
            raise SnapshotValidationError(
                "oam_fallback: diagnostic evidence requires occurred=true"
            )
        if occurred and kind is OAMFallbackKind.MISSING_IDENTITY and identity is not None:
            raise SnapshotValidationError(
                "oam_fallback.identity: missing-identity fallback requires null"
            )
        if occurred and kind is not OAMFallbackKind.MISSING_IDENTITY and identity is None:
            raise SnapshotValidationError(
                "oam_fallback.identity: range/unmapped fallback requires numeric identity"
            )
        if before & 0xF8 != after & 0xF8:
            raise SnapshotValidationError(
                "oam_fallback: attribute control bits 3-7 must be preserved"
            )
        if after & 0x07 != (palette or 0):
            raise SnapshotValidationError(
                "oam_fallback: attribute palette bits do not match selected palette"
            )
        return cls(
            occurred, kind, object_id, final_tile, identity, generation,
            writer_id, palette, before, after
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurred": self.occurred,
            "fallback_kind": (
                None if self.fallback_kind is None else self.fallback_kind.value
            ),
            "object_id": self.object_id,
            "final_tile_id": self.final_tile_id,
            "identity": self.identity,
            "generation": self.generation,
            "writer_id": self.writer_id,
            "palette": self.palette,
            "before_attributes": self.before_attributes,
            "after_attributes": self.after_attributes,
        }


@dataclass(frozen=True, slots=True)
class TimingRow:
    key: str
    operation: str
    mode: str
    rom: str
    tool_device: str
    samples: int
    worst_cycles: int
    instrumentation_cycles: int
    start_cycle: int
    deadline_cycle: int
    guard_cycles: int
    margin_cycles: int
    margin_percent: int | float
    defer_threshold: int
    threshold_plus_one_result: str
    threshold_plus_one_entered_committing: bool
    result: str
    evidence_kind: str
    activation_phase: int

    @classmethod
    def from_dict(cls, raw: object) -> TimingRow:
        names = {
            "key", "operation", "mode", "rom", "tool_device", "samples",
            "worst_cycles", "instrumentation_cycles", "start_cycle",
            "deadline_cycle", "guard_cycles", "margin_cycles",
            "margin_percent", "defer_threshold", "result", "evidence_kind",
            "threshold_plus_one_result", "threshold_plus_one_entered_committing",
            "activation_phase",
        }
        obj = require_object(raw, path="timing_row", required=names, error=SnapshotValidationError)
        numeric = {
            name: require_int(obj[name], path=f"timing_row.{name}", error=SnapshotValidationError)
            for name in (
                "samples", "worst_cycles", "instrumentation_cycles", "start_cycle",
                "deadline_cycle", "guard_cycles", "activation_phase",
            )
        }
        numeric["margin_cycles"] = _require_signed_int(
            obj["margin_cycles"], path="timing_row.margin_cycles"
        )
        numeric["defer_threshold"] = _require_signed_int(
            obj["defer_threshold"], path="timing_row.defer_threshold"
        )
        margin_percent = _require_number(
            obj["margin_percent"], path="timing_row.margin_percent"
        )
        if numeric["samples"] < 1:
            raise SnapshotValidationError("timing_row.samples: expected at least one sample")
        usable_budget = (
            numeric["deadline_cycle"]
            - numeric["start_cycle"]
            - numeric["guard_cycles"]
        )
        if usable_budget <= 0:
            raise SnapshotValidationError(
                "timing_row: deadline/start/guard leave no usable budget"
            )
        expected_threshold = (
            usable_budget
            - numeric["instrumentation_cycles"]
        )
        expected_margin = expected_threshold - numeric["worst_cycles"]
        if numeric["margin_cycles"] != expected_margin:
            raise SnapshotValidationError(
                "timing_row.margin_cycles: inconsistent with required budget equation"
            )
        expected_percent = expected_margin * 100 / usable_budget
        if not math.isclose(
            margin_percent, expected_percent, rel_tol=0.0, abs_tol=1e-9
        ):
            raise SnapshotValidationError(
                "timing_row.margin_percent: inconsistent with numeric margin"
            )
        if numeric["defer_threshold"] != expected_threshold:
            raise SnapshotValidationError(
                "timing_row.defer_threshold: expected exact maximum safe workload"
            )
        result = require_str(obj["result"], path="timing_row.result", error=SnapshotValidationError)
        expected_result = "PASS" if expected_margin >= 0 else "DEFER"
        if result != expected_result:
            raise SnapshotValidationError(
                f"timing_row.result: expected {expected_result} from budget equation"
            )
        threshold_plus_one_result = require_str(
            obj["threshold_plus_one_result"],
            path="timing_row.threshold_plus_one_result",
            error=SnapshotValidationError,
        )
        threshold_plus_one_entered_committing = require_bool(
            obj["threshold_plus_one_entered_committing"],
            path="timing_row.threshold_plus_one_entered_committing",
            error=SnapshotValidationError,
        )
        if (
            threshold_plus_one_result != "DEFER"
            or threshold_plus_one_entered_committing
        ):
            raise SnapshotValidationError(
                "timing_row: defer_threshold + 1 must DEFER before COMMITTING"
            )
        evidence_kind = require_str(
            obj["evidence_kind"], path="timing_row.evidence_kind", error=SnapshotValidationError
        )
        if evidence_kind not in {"YELLOW_BASELINE", "SCHEMA_FIXTURE", "RENDERER_RUNTIME"}:
            raise SnapshotValidationError("timing_row.evidence_kind: unknown evidence kind")
        if evidence_kind == "RENDERER_RUNTIME" and numeric["activation_phase"] == 0:
            raise SnapshotValidationError(
                "timing_row: baseline evidence cannot claim renderer runtime activation"
            )
        return cls(
            key=require_str(obj["key"], path="timing_row.key", error=SnapshotValidationError),
            operation=require_str(obj["operation"], path="timing_row.operation", error=SnapshotValidationError),
            mode=require_str(obj["mode"], path="timing_row.mode", error=SnapshotValidationError),
            rom=require_str(obj["rom"], path="timing_row.rom", error=SnapshotValidationError),
            tool_device=require_str(obj["tool_device"], path="timing_row.tool_device", error=SnapshotValidationError),
            result=result,
            evidence_kind=evidence_kind,
            margin_percent=margin_percent,
            threshold_plus_one_result=threshold_plus_one_result,
            threshold_plus_one_entered_committing=threshold_plus_one_entered_committing,
            **numeric,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "operation": self.operation, "mode": self.mode,
            "rom": self.rom, "tool_device": self.tool_device, "samples": self.samples,
            "worst_cycles": self.worst_cycles,
            "instrumentation_cycles": self.instrumentation_cycles,
            "start_cycle": self.start_cycle, "deadline_cycle": self.deadline_cycle,
            "guard_cycles": self.guard_cycles, "margin_cycles": self.margin_cycles,
            "margin_percent": self.margin_percent,
            "defer_threshold": self.defer_threshold, "result": self.result,
            "threshold_plus_one_result": self.threshold_plus_one_result,
            "threshold_plus_one_entered_committing": (
                self.threshold_plus_one_entered_committing
            ),
            "evidence_kind": self.evidence_kind,
            "activation_phase": self.activation_phase,
        }


@dataclass(frozen=True, slots=True)
class SemanticSnapshot:
    rom: str
    scenario: str
    seed: int
    checkpoint: str
    frame: int
    evidence_kind: str
    activation_phase: int
    owner: Owner
    phase: Phase
    generation: int
    request_result: RequestResult | None
    job: SnapshotJob | None
    writer_id: str | None
    traced_writer_ids: tuple[str, ...]
    banks: BankState
    dirty: tuple[tuple[str, bool], ...]
    queued_jobs: tuple[SnapshotJob, ...]
    reconstruction: ReconstructionState
    bg_tile_ids: bytes
    bg_attributes: bytes
    bg_palettes: bytes
    obj_palettes: bytes
    shadow_oam: bytes
    hardware_oam: bytes
    map_id: str | None
    tileset_id: str | None
    transfer_state: str | None
    overlay_request: OverlayRequestState | None
    oam_fallback: OAMFallbackState
    timing_row_key: str | None
    timing_row: TimingRow | None
    artifacts: tuple[tuple[str, str], ...]
    schema: str = SNAPSHOT_SCHEMA

    @classmethod
    def from_dict(cls, raw: object) -> SemanticSnapshot:
        required = {
            "schema", "rom", "scenario", "seed", "checkpoint", "frame",
            "evidence_kind", "activation_phase",
            "owner", "phase", "generation", "request_result", "job",
            "writer_id", "traced_writer_ids", "banks", "dirty", "queued_jobs",
            "reconstruction", "bg_tile_ids", "bg_attributes", "bg_palettes",
            "obj_palettes", "shadow_oam", "hardware_oam", "map_id",
            "tileset_id", "transfer_state", "oam_fallback", "timing_row_key",
            "overlay_request", "timing_row", "artifacts",
        }
        obj = require_object(
            raw, path="snapshot", required=required, error=SnapshotValidationError
        )
        if obj["schema"] != SNAPSHOT_SCHEMA:
            raise SnapshotValidationError(
                f"snapshot.schema: unsupported schema {obj['schema']!r}; expected {SNAPSHOT_SCHEMA!r}"
            )

        def optional_string(name: str) -> str | None:
            value = obj[name]
            return (
                None
                if value is None
                else require_str(value, path=f"snapshot.{name}", error=SnapshotValidationError)
            )

        traced_raw = obj["traced_writer_ids"]
        if not isinstance(traced_raw, list):
            raise SnapshotValidationError("snapshot.traced_writer_ids: expected an array")
        traced = tuple(
            require_str(
                value,
                path=f"snapshot.traced_writer_ids[{index}]",
                error=SnapshotValidationError,
            )
            for index, value in enumerate(traced_raw)
        )
        if len(set(traced)) != len(traced):
            raise SnapshotValidationError("snapshot.traced_writer_ids: duplicate writer ID")

        dirty_obj = require_object(
            obj["dirty"],
            path="snapshot.dirty",
            required={"bg", "obj", "attributes"},
            error=SnapshotValidationError,
        )
        dirty = tuple(
            (
                key,
                require_bool(
                    dirty_obj[key],
                    path=f"snapshot.dirty.{key}",
                    error=SnapshotValidationError,
                ),
            )
            for key in sorted(dirty_obj)
        )

        queued_raw = obj["queued_jobs"]
        if not isinstance(queued_raw, list):
            raise SnapshotValidationError("snapshot.queued_jobs: expected an array")
        queued = tuple(
            SnapshotJob.from_dict(value, path=f"snapshot.queued_jobs[{index}]")
            for index, value in enumerate(queued_raw)
        )

        artifacts_obj = require_object(
            obj["artifacts"],
            path="snapshot.artifacts",
            required=set(),
            optional=set(obj["artifacts"]) if isinstance(obj["artifacts"], dict) else set(),
            error=SnapshotValidationError,
        )
        artifacts = tuple(
            (
                key,
                require_str(
                    artifacts_obj[key],
                    path=f"snapshot.artifacts.{key}",
                    error=SnapshotValidationError,
                ),
            )
            for key in sorted(artifacts_obj)
        )
        request_result_raw = obj["request_result"]
        request_result = (
            None
            if request_result_raw is None
            else require_enum(
                RequestResult,
                request_result_raw,
                path="snapshot.request_result",
                error=SnapshotValidationError,
            )
        )
        job_raw = obj["job"]
        job = None if job_raw is None else SnapshotJob.from_dict(job_raw)
        snapshot = cls(
            schema=SNAPSHOT_SCHEMA,
            rom=require_str(obj["rom"], path="snapshot.rom", error=SnapshotValidationError),
            scenario=require_str(
                obj["scenario"], path="snapshot.scenario", error=SnapshotValidationError
            ),
            seed=require_int(obj["seed"], path="snapshot.seed", error=SnapshotValidationError),
            checkpoint=require_str(
                obj["checkpoint"], path="snapshot.checkpoint", error=SnapshotValidationError
            ),
            frame=require_int(obj["frame"], path="snapshot.frame", error=SnapshotValidationError),
            evidence_kind=require_str(
                obj["evidence_kind"],
                path="snapshot.evidence_kind",
                error=SnapshotValidationError,
            ),
            activation_phase=require_int(
                obj["activation_phase"],
                path="snapshot.activation_phase",
                maximum=9,
                error=SnapshotValidationError,
            ),
            owner=require_enum(
                Owner, obj["owner"], path="snapshot.owner", error=SnapshotValidationError
            ),
            phase=require_enum(
                Phase, obj["phase"], path="snapshot.phase", error=SnapshotValidationError
            ),
            generation=require_int(
                obj["generation"], path="snapshot.generation", error=SnapshotValidationError
            ),
            request_result=request_result,
            job=job,
            writer_id=optional_string("writer_id"),
            traced_writer_ids=traced,
            banks=BankState.from_dict(obj["banks"]),
            dirty=dirty,
            queued_jobs=queued,
            reconstruction=ReconstructionState.from_dict(obj["reconstruction"]),
            bg_tile_ids=require_hex(
                obj["bg_tile_ids"],
                path="snapshot.bg_tile_ids",
                length=TILEMAP_BYTES,
                error=SnapshotValidationError,
            ),
            bg_attributes=require_hex(
                obj["bg_attributes"],
                path="snapshot.bg_attributes",
                length=TILEMAP_BYTES,
                error=SnapshotValidationError,
            ),
            bg_palettes=require_hex(
                obj["bg_palettes"],
                path="snapshot.bg_palettes",
                length=PALETTE_BYTES,
                error=SnapshotValidationError,
            ),
            obj_palettes=require_hex(
                obj["obj_palettes"],
                path="snapshot.obj_palettes",
                length=PALETTE_BYTES,
                error=SnapshotValidationError,
            ),
            shadow_oam=require_hex(
                obj["shadow_oam"],
                path="snapshot.shadow_oam",
                length=OAM_BYTES,
                error=SnapshotValidationError,
            ),
            hardware_oam=require_hex(
                obj["hardware_oam"],
                path="snapshot.hardware_oam",
                length=OAM_BYTES,
                error=SnapshotValidationError,
            ),
            map_id=optional_string("map_id"),
            tileset_id=optional_string("tileset_id"),
            transfer_state=optional_string("transfer_state"),
            overlay_request=(
                None
                if obj["overlay_request"] is None
                else OverlayRequestState.from_dict(obj["overlay_request"])
            ),
            oam_fallback=OAMFallbackState.from_dict(obj["oam_fallback"]),
            timing_row_key=optional_string("timing_row_key"),
            timing_row=(
                None if obj["timing_row"] is None else TimingRow.from_dict(obj["timing_row"])
            ),
            artifacts=artifacts,
        )
        allowed = {
            Phase.YELLOW_ACTIVE: {Owner.RENDERER_YELLOW},
            Phase.HANDOFF_TO_OVERWORLD: set(Owner),
            Phase.OVERWORLD_RECONSTRUCTING: {
                Owner.RENDERER_FULL_COLOR_OVERWORLD
            },
            Phase.OVERWORLD_ACTIVE: {Owner.RENDERER_FULL_COLOR_OVERWORLD},
            Phase.OVERWORLD_OVERLAY: {Owner.RENDERER_FULL_COLOR_OVERWORLD},
            Phase.HANDOFF_TO_YELLOW: set(Owner),
        }
        if snapshot.owner not in allowed[snapshot.phase]:
            raise SnapshotValidationError(
                "snapshot.owner/snapshot.phase: invalid pair "
                f"{snapshot.owner.value}/{snapshot.phase.value}"
            )
        if snapshot.evidence_kind not in {
            "YELLOW_BASELINE",
            "SCHEMA_FIXTURE",
            "RENDERER_RUNTIME",
        }:
            raise SnapshotValidationError(
                "snapshot.evidence_kind: unknown evidence kind"
            )
        if snapshot.evidence_kind == "SCHEMA_FIXTURE" and snapshot.activation_phase != 0:
            raise SnapshotValidationError(
                "snapshot.activation_phase: verification contract fixtures require phase 0"
            )
        if snapshot.evidence_kind == "YELLOW_BASELINE":
            if snapshot.activation_phase != 0 or snapshot.owner is not Owner.RENDERER_YELLOW:
                raise SnapshotValidationError(
                    "snapshot.evidence_kind: Yellow baseline must be Phase 0 Yellow-owned evidence"
                )
        if (
            snapshot.evidence_kind == "RENDERER_RUNTIME"
            and snapshot.activation_phase == 0
        ):
            raise SnapshotValidationError(
                "snapshot.evidence_kind: baseline evidence cannot claim renderer runtime activation"
            )
        if snapshot.phase is Phase.OVERWORLD_OVERLAY and snapshot.overlay_request is None:
            raise SnapshotValidationError(
                "snapshot.overlay_request: required during OVERWORLD_OVERLAY"
            )
        if snapshot.phase is not Phase.OVERWORLD_OVERLAY and snapshot.overlay_request is not None:
            raise SnapshotValidationError(
                "snapshot.overlay_request: only valid during OVERWORLD_OVERLAY"
            )
        if (snapshot.timing_row_key is None) != (snapshot.timing_row is None):
            raise SnapshotValidationError(
                "snapshot.timing_row: timing_row_key and structured timing row must be paired"
            )
        if (
            snapshot.timing_row is not None
            and snapshot.timing_row.key != snapshot.timing_row_key
        ):
            raise SnapshotValidationError(
                "snapshot.timing_row.key: does not match timing_row_key"
            )
        required = set(snapshot.reconstruction.required_items)
        completed = set(snapshot.reconstruction.completed_items)
        if snapshot.phase is Phase.OVERWORLD_RECONSTRUCTING:
            if not snapshot.reconstruction.unknown_prior_state:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: prior state must be poisoned/unknown"
                )
            if snapshot.reconstruction.presentation_barrier_count:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: barrier cannot occur before reconstruction completes"
                )
            if set(snapshot.reconstruction.poisoned_items) != required:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: every prior resource must be poisoned"
                )
        phase1_ownership_diagnostic = (
            snapshot.evidence_kind == "RENDERER_RUNTIME"
            and snapshot.activation_phase == 1
            and snapshot.scenario == "RC-OWNERSHIP-REPLACEMENT"
            and snapshot.checkpoint == "phase1-ownership-replacement"
            and snapshot.phase is Phase.OVERWORLD_ACTIVE
        )
        if (
            snapshot.phase in {Phase.OVERWORLD_ACTIVE, Phase.OVERWORLD_OVERLAY}
            and not phase1_ownership_diagnostic
        ):
            if not snapshot.reconstruction.unknown_prior_state:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: active overworld requires poisoned/unknown prior state"
                )
            if completed != required:
                missing = sorted(required - completed)
                raise SnapshotValidationError(
                    "snapshot.reconstruction: active overworld has incomplete authoritative items: "
                    + ", ".join(missing)
                )
            if set(snapshot.reconstruction.poisoned_items) != required:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: active overworld lacks complete poison record"
                )
            if snapshot.reconstruction.presentation_barrier_count != 1:
                raise SnapshotValidationError(
                    "snapshot.reconstruction: active overworld requires exactly one presentation barrier"
                )
        if phase1_ownership_diagnostic and (
            snapshot.reconstruction.completed_items
            or snapshot.reconstruction.item_provenance
            or snapshot.reconstruction.poisoned_items
            or snapshot.reconstruction.unknown_prior_state
            or snapshot.reconstruction.presentation_barrier_count
        ):
            raise SnapshotValidationError(
                "snapshot.reconstruction: Phase 1 ownership diagnostic cannot claim reconstruction"
            )
        return snapshot

    @classmethod
    def from_json(cls, payload: str | bytes) -> SemanticSnapshot:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotValidationError(f"snapshot: invalid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "rom": self.rom,
            "scenario": self.scenario,
            "seed": self.seed,
            "checkpoint": self.checkpoint,
            "frame": self.frame,
            "evidence_kind": self.evidence_kind,
            "activation_phase": self.activation_phase,
            "owner": self.owner.value,
            "phase": self.phase.value,
            "generation": self.generation,
            "request_result": (
                None if self.request_result is None else self.request_result.value
            ),
            "job": None if self.job is None else self.job.to_dict(),
            "writer_id": self.writer_id,
            "traced_writer_ids": list(self.traced_writer_ids),
            "banks": self.banks.to_dict(),
            "dirty": dict(self.dirty),
            "queued_jobs": [job.to_dict() for job in self.queued_jobs],
            "reconstruction": self.reconstruction.to_dict(),
            "bg_tile_ids": self.bg_tile_ids.hex(),
            "bg_attributes": self.bg_attributes.hex(),
            "bg_palettes": self.bg_palettes.hex(),
            "obj_palettes": self.obj_palettes.hex(),
            "shadow_oam": self.shadow_oam.hex(),
            "hardware_oam": self.hardware_oam.hex(),
            "map_id": self.map_id,
            "tileset_id": self.tileset_id,
            "transfer_state": self.transfer_state,
            "overlay_request": (
                None if self.overlay_request is None else self.overlay_request.to_dict()
            ),
            "oam_fallback": self.oam_fallback.to_dict(),
            "timing_row_key": self.timing_row_key,
            "timing_row": None if self.timing_row is None else self.timing_row.to_dict(),
            "artifacts": dict(self.artifacts),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


@dataclass(frozen=True, slots=True)
class Difference:
    path: str
    expected: object
    actual: object

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "expected": self.expected, "actual": self.actual}


_BYTE_FIELDS = {
    "bg_tile_ids",
    "bg_attributes",
    "bg_palettes",
    "obj_palettes",
    "shadow_oam",
    "hardware_oam",
}


def diff_snapshots(expected: SemanticSnapshot, actual: SemanticSnapshot) -> tuple[Difference, ...]:
    """Return deterministic leaf differences, with one entry per byte offset."""
    left = expected.to_dict()
    right = actual.to_dict()
    differences: list[Difference] = []
    for field in sorted(left):
        if field in _BYTE_FIELDS:
            left_bytes = bytes.fromhex(left[field])
            right_bytes = bytes.fromhex(right[field])
            for offset, (expected_byte, actual_byte) in enumerate(zip(left_bytes, right_bytes)):
                if expected_byte != actual_byte:
                    differences.append(
                        Difference(
                            path=f"{field}[0x{offset:04x}]",
                            expected=f"0x{expected_byte:02x}",
                            actual=f"0x{actual_byte:02x}",
                        )
                    )
            continue
        _diff_value(field, left[field], right[field], differences)
    return tuple(differences)


def _diff_value(path: str, expected: object, actual: object, out: list[Difference]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in expected:
                out.append(Difference(child, "<missing>", actual[key]))
            elif key not in actual:
                out.append(Difference(child, expected[key], "<missing>"))
            else:
                _diff_value(child, expected[key], actual[key], out)
    elif isinstance(expected, list) and isinstance(actual, list):
        for index in range(max(len(expected), len(actual))):
            child = f"{path}[{index}]"
            if index >= len(expected):
                out.append(Difference(child, "<missing>", actual[index]))
            elif index >= len(actual):
                out.append(Difference(child, expected[index], "<missing>"))
            else:
                _diff_value(child, expected[index], actual[index], out)
    elif expected != actual:
        out.append(Difference(path, expected, actual))


def _string_array(value: object, *, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SnapshotValidationError(f"{path}: expected an array")
    result = tuple(
        require_str(item, path=f"{path}[{index}]", error=SnapshotValidationError)
        for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise SnapshotValidationError(f"{path}: duplicate value")
    return result


def _optional_string_value(value: object, *, path: str) -> str | None:
    return (
        None
        if value is None
        else require_str(value, path=path, error=SnapshotValidationError)
    )


def _optional_int(
    value: object, *, path: str, maximum: int | None = None
) -> int | None:
    return (
        None
        if value is None
        else require_int(
            value, path=path, maximum=maximum, error=SnapshotValidationError
        )
    )


def _optional_coordinate(
    value: object, *, path: str
) -> tuple[int, int] | None:
    if value is None:
        return None
    obj = require_object(
        value,
        path=path,
        required={"x", "y"},
        error=SnapshotValidationError,
    )
    return (
        _require_signed_int(obj["x"], path=f"{path}.x"),
        _require_signed_int(obj["y"], path=f"{path}.y"),
    )


def _optional_int_array(
    value: object, *, path: str, length: int
) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != length:
        raise SnapshotValidationError(f"{path}: expected exactly {length} integers")
    return tuple(
        _require_signed_int(item, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    )


def _require_signed_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotValidationError(f"{path}: expected an integer")
    return value


def _require_number(value: object, *, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnapshotValidationError(f"{path}: expected a number")
    if not math.isfinite(value):
        raise SnapshotValidationError(f"{path}: expected a finite number")
    return value
