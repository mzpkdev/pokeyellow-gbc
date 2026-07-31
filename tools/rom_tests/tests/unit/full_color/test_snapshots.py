"""Semantic snapshot schema and exact-offset mutation tests."""

from copy import deepcopy

import pytest

from tools.rom_tests.full_color.snapshots import (
    REQUIRED_RECONSTRUCTION_ITEMS,
    RECONSTRUCTION_ITEM_PROVENANCE,
    SemanticSnapshot,
    SnapshotValidationError,
    diff_snapshots,
)


def snapshot_dict() -> dict[str, object]:
    job = {
        "job_id": "JOB-0012",
        "request_ids": ["REQ-0012"],
        "resources": ["BG_TILE_IDS", "BG_ATTRIBUTES"],
        "state": "PREPARED",
        "cancellation_reason": None,
        "commit_unit_id": "MU-TEST-PAIR",
        "owner": "RENDERER_FULL_COLOR_OVERWORLD",
        "generation": 12,
    }
    return {
        "schema": "full-color-contract-v1",
        "rom": "pokeyellow_debug.gbc:abc123",
        "scenario": "standalone_return",
        "seed": 83421,
        "checkpoint": "return_from_party",
        "frame": 1234,
        "evidence_kind": "SCHEMA_FIXTURE",
        "activation_phase": 0,
        "owner": "RENDERER_FULL_COLOR_OVERWORLD",
        "phase": "OVERWORLD_ACTIVE",
        "generation": 12,
        "request_result": "ACCEPTED",
        "job": job,
        "writer_id": "WR-TEST-PAIR",
        "traced_writer_ids": ["WR-TEST-PAIR"],
        "banks": {"rom": 3, "wram": 1, "vram": 0},
        "dirty": {"bg": False, "obj": False, "attributes": False},
        "queued_jobs": [],
        "reconstruction": {
            "required_items": sorted(REQUIRED_RECONSTRUCTION_ITEMS),
            "completed_items": sorted(REQUIRED_RECONSTRUCTION_ITEMS),
            "item_provenance": {
                item: provenance.value
                for item, provenance in RECONSTRUCTION_ITEM_PROVENANCE.items()
            },
            "poisoned_items": sorted(REQUIRED_RECONSTRUCTION_ITEMS),
            "unknown_prior_state": True,
            "presentation_barrier_count": 1,
        },
        "bg_tile_ids": bytes(2048).hex(),
        "bg_attributes": bytes(2048).hex(),
        "bg_palettes": bytes(64).hex(),
        "obj_palettes": bytes(64).hex(),
        "shadow_oam": bytes(160).hex(),
        "hardware_oam": bytes(160).hex(),
        "map_id": "PALLET_TOWN",
        "tileset_id": "OVERWORLD",
        "transfer_state": None,
        "overlay_request": None,
        "oam_fallback": {
            "occurred": False,
            "fallback_kind": None,
            "object_id": None,
            "final_tile_id": None,
            "identity": None,
            "generation": None,
            "writer_id": None,
            "palette": 0,
            "before_attributes": 0xA8,
            "after_attributes": 0xA8,
        },
        "timing_row_key": None,
        "timing_row": None,
        "artifacts": {"trace": "trace.json", "screenshot": "frame.png"},
    }


def test_snapshot_round_trip_is_canonical_and_deterministic() -> None:
    snapshot = SemanticSnapshot.from_dict(snapshot_dict())

    assert SemanticSnapshot.from_json(snapshot.to_json()) == snapshot
    assert snapshot.to_json() == SemanticSnapshot.from_dict(snapshot.to_dict()).to_json()
    assert snapshot.to_json().endswith("\n")


def test_idle_checkpoint_represents_absent_request_and_job_with_null() -> None:
    raw = snapshot_dict()
    raw.update({"request_result": None, "job": None})

    snapshot = SemanticSnapshot.from_dict(raw)

    assert snapshot.request_result is None
    assert snapshot.job is None
    assert snapshot.to_dict()["job"] is None


def test_one_byte_corruption_reports_resource_and_exact_offset() -> None:
    expected = SemanticSnapshot.from_dict(snapshot_dict())
    mutated = deepcopy(snapshot_dict())
    attributes = bytearray.fromhex(mutated["bg_attributes"])
    attributes[0x19A] = 0x07
    mutated["bg_attributes"] = attributes.hex()

    differences = diff_snapshots(expected, SemanticSnapshot.from_dict(mutated))

    assert [difference.to_dict() for difference in differences] == [
        {
            "path": "bg_attributes[0x019a]",
            "expected": "0x00",
            "actual": "0x07",
        }
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw.update({"schema": "full-color-contract-v99"}), "unsupported schema"),
        (lambda raw: raw.update({"surprise": True}), "unknown fields: surprise"),
        (lambda raw: raw.pop("generation"), "missing required fields: generation"),
        (lambda raw: raw.update({"bg_palettes": "00"}), "expected exactly 64 bytes"),
        (lambda raw: raw.update({"obj_palettes": "0G"}), "invalid hexadecimal"),
        (
            lambda raw: raw["job"].update(
                {"state": "CANCELLED", "cancellation_reason": None}
            ),
            "CANCELLED jobs require exactly one reason",
        ),
        (
            lambda raw: raw.update({"owner": "RENDERER_YELLOW"}),
            "invalid pair RENDERER_YELLOW/OVERWORLD_ACTIVE",
        ),
        (
            lambda raw: raw.update({"evidence_kind": "RENDERER_RUNTIME"}),
            "Gate 0 cannot claim renderer runtime evidence",
        ),
    ],
)
def test_malformed_snapshot_fails_with_specific_field(
    mutation: object, message: str
) -> None:
    raw = snapshot_dict()
    mutation(raw)

    with pytest.raises(SnapshotValidationError, match=message):
        SemanticSnapshot.from_dict(raw)


def overlay_request() -> dict[str, object]:
    return {
        "destination_selector": "WINDOW_MAP_9C00",
        "map_id": "PALLET_TOWN",
        "tileset_id": "OVERWORLD",
        "rectangle": {"x": 0, "y": 0, "width": 2, "height": 1},
        "world_origin": {"x": 10, "y": 20},
        "world_transform": None,
        "coordinate_overrides": {"10,20": 3},
        "classifications": ["OPAQUE_OVERLAY", "REVEALED_TERRAIN"],
        "tile_ids": "0102",
        "attributes": "0003",
        "clipped_mappings": [
            {
                "source_index": 0,
                "destination_x": 0,
                "destination_y": 0,
                "world_x": 10,
                "world_y": 20,
            },
            {
                "source_index": 1,
                "destination_x": 1,
                "destination_y": 0,
                "world_x": 11,
                "world_y": 20,
            },
        ],
        "oracle_sources": ["REQUEST_DATA"],
    }


def test_overlay_schema_rejects_oracle_contamination_and_mapping_loss() -> None:
    raw = snapshot_dict()
    raw["phase"] = "OVERWORLD_OVERLAY"
    raw["overlay_request"] = overlay_request()
    SemanticSnapshot.from_dict(raw)

    for oracle in ("VRAM", "AMBIENT_MAP"):
        contaminated = deepcopy(raw)
        contaminated["overlay_request"]["oracle_sources"] = ["REQUEST_DATA", oracle]
        with pytest.raises(SnapshotValidationError, match=f"contaminated by {oracle}"):
            SemanticSnapshot.from_dict(contaminated)

    mapping_loss = deepcopy(raw)
    mapping_loss["overlay_request"]["clipped_mappings"][1]["source_index"] = 0
    with pytest.raises(SnapshotValidationError, match="mapping loss or duplicate"):
        SemanticSnapshot.from_dict(mapping_loss)

    unknown_destination = deepcopy(raw)
    unknown_destination["overlay_request"]["destination_selector"] = "ARBITRARY"
    with pytest.raises(SnapshotValidationError, match="unknown symbol"):
        SemanticSnapshot.from_dict(unknown_destination)


def test_overlay_transform_derives_world_coordinates_after_clipping() -> None:
    raw = snapshot_dict()
    raw["phase"] = "OVERWORLD_OVERLAY"
    request = overlay_request()
    request.update(
        {
            "rectangle": {"x": -1, "y": 0, "width": 3, "height": 1},
            "world_origin": None,
            "world_transform": [2, 0, 0, -1, 100, 50],
            "classifications": ["OPAQUE_OVERLAY"] * 3,
            "tile_ids": "010203",
            "attributes": "000000",
            "clipped_mappings": [
                {
                    "source_index": 1,
                    "destination_x": 0,
                    "destination_y": 0,
                    "world_x": 102,
                    "world_y": 50,
                },
                {
                    "source_index": 2,
                    "destination_x": 1,
                    "destination_y": 0,
                    "world_x": 104,
                    "world_y": 50,
                },
            ],
        }
    )
    raw["overlay_request"] = request
    SemanticSnapshot.from_dict(raw)

    contaminated = deepcopy(raw)
    contaminated["overlay_request"]["clipped_mappings"][0]["world_x"] = 101
    with pytest.raises(
        SnapshotValidationError, match="mapping loss or transform contamination"
    ):
        SemanticSnapshot.from_dict(contaminated)

    singular = deepcopy(raw)
    singular["overlay_request"]["world_transform"] = [1, 2, 2, 4, 100, 50]
    with pytest.raises(SnapshotValidationError, match="singular transform"):
        SemanticSnapshot.from_dict(singular)

    mapping_loss = deepcopy(raw)
    mapping_loss["overlay_request"]["clipped_mappings"].pop()
    with pytest.raises(SnapshotValidationError, match="mapping loss or duplicate"):
        SemanticSnapshot.from_dict(mapping_loss)


def test_poisoned_reconstruction_and_barrier_are_phase_complete() -> None:
    raw = snapshot_dict()
    removed = raw["reconstruction"]["completed_items"].pop()
    raw["reconstruction"]["item_provenance"].pop(removed)
    with pytest.raises(SnapshotValidationError, match="incomplete authoritative items"):
        SemanticSnapshot.from_dict(raw)

    raw = snapshot_dict()
    raw["reconstruction"]["unknown_prior_state"] = False
    with pytest.raises(SnapshotValidationError, match="poisoned/unknown prior state"):
        SemanticSnapshot.from_dict(raw)

    raw = snapshot_dict()
    raw["reconstruction"]["poisoned_items"].pop()
    with pytest.raises(SnapshotValidationError, match="complete poison record"):
        SemanticSnapshot.from_dict(raw)

    raw = snapshot_dict()
    raw["reconstruction"]["presentation_barrier_count"] = 0
    with pytest.raises(SnapshotValidationError, match="exactly one presentation barrier"):
        SemanticSnapshot.from_dict(raw)


@pytest.mark.parametrize(
    "provenance",
    [
        "CAPTURED_VRAM",
        "SAVED_PALETTE_RAM",
        "CAPTURED_OAM",
        "SAVED_SCREEN_BUFFER",
    ],
)
def test_reconstruction_rejects_saved_or_captured_display_provenance(
    provenance: str,
) -> None:
    raw = snapshot_dict()
    raw["reconstruction"]["item_provenance"]["tilemaps_and_attributes"] = provenance

    with pytest.raises(SnapshotValidationError, match="captured/saved display state"):
        SemanticSnapshot.from_dict(raw)


def test_oam_fallback_requires_diagnostic_and_preserves_control_bits() -> None:
    raw = snapshot_dict()
    raw["oam_fallback"].update({"occurred": True})
    with pytest.raises(SnapshotValidationError, match="requires kind, object"):
        SemanticSnapshot.from_dict(raw)

    raw = snapshot_dict()
    raw["oam_fallback"].update(
        {
            "occurred": True,
            "fallback_kind": "MISSING_IDENTITY",
            "object_id": "OBJECT-03",
            "final_tile_id": 17,
            "generation": 12,
            "writer_id": "WR-OAM-FALLBACK",
            "palette": 0,
            "after_attributes": 0x28,
        }
    )
    with pytest.raises(SnapshotValidationError, match="control bits 3-7"):
        SemanticSnapshot.from_dict(raw)


@pytest.mark.parametrize(
    ("kind", "identity"),
    [
        ("MISSING_IDENTITY", None),
        ("OUT_OF_RANGE_IDENTITY", 999),
        ("UNMAPPED_IDENTITY", 42),
    ],
)
def test_oam_fallback_records_complete_structured_evidence(
    kind: str, identity: int | None
) -> None:
    raw = snapshot_dict()
    raw["oam_fallback"].update(
        {
            "occurred": True,
            "fallback_kind": kind,
            "object_id": "OBJECT-03",
            "final_tile_id": 17,
            "identity": identity,
            "generation": 12,
            "writer_id": "WR-OAM-FALLBACK",
            "palette": 0,
        }
    )

    assert SemanticSnapshot.from_dict(raw).oam_fallback.palette == 0

    raw["oam_fallback"]["palette"] = 1
    with pytest.raises(SnapshotValidationError, match="palette 0"):
        SemanticSnapshot.from_dict(raw)


def test_timing_key_requires_complete_numeric_row() -> None:
    raw = snapshot_dict()
    raw["timing_row_key"] = "TIME-YELLOW-BASELINE"
    with pytest.raises(SnapshotValidationError, match="must be paired"):
        SemanticSnapshot.from_dict(raw)

    raw["timing_row"] = {
        "key": "TIME-YELLOW-BASELINE",
        "operation": "yellow_vblank",
        "mode": "CGB",
        "rom": "pokeyellow_debug.gbc:abc123",
        "tool_device": "synthetic-counter",
        "samples": 3,
        "worst_cycles": 10,
        "instrumentation_cycles": 2,
        "start_cycle": 0,
        "deadline_cycle": 20,
        "guard_cycles": 3,
        "margin_cycles": 5,
        "margin_percent": 29.41176470588235,
        "defer_threshold": 15,
        "threshold_plus_one_result": "DEFER",
        "threshold_plus_one_entered_committing": False,
        "result": "PASS",
        "evidence_kind": "YELLOW_BASELINE",
        "activation_phase": 0,
    }
    assert SemanticSnapshot.from_dict(raw).timing_row is not None

    wrong = deepcopy(raw)
    wrong["timing_row"]["margin_percent"] = 24
    with pytest.raises(SnapshotValidationError, match="margin_percent"):
        SemanticSnapshot.from_dict(wrong)

    wrong = deepcopy(raw)
    wrong["timing_row"]["defer_threshold"] = 6
    with pytest.raises(SnapshotValidationError, match="maximum safe workload"):
        SemanticSnapshot.from_dict(wrong)

    wrong = deepcopy(raw)
    wrong["timing_row"]["threshold_plus_one_entered_committing"] = True
    with pytest.raises(SnapshotValidationError, match=r"threshold \+ 1"):
        SemanticSnapshot.from_dict(wrong)


def test_bank_leak_is_a_structured_snapshot_difference() -> None:
    expected = SemanticSnapshot.from_dict(snapshot_dict())
    leaked = snapshot_dict()
    leaked["banks"]["wram"] = 2

    assert [item.to_dict() for item in diff_snapshots(
        expected, SemanticSnapshot.from_dict(leaked)
    )] == [{"path": "banks.wram", "expected": 1, "actual": 2}]
