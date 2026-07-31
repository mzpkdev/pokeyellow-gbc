"""Strict v1 authority schemas and exact reconciliation mutations."""

from copy import deepcopy
import hashlib

import pytest

from tools.rom_tests.full_color.discovery_review import (
    DiscoveryRejectionAuthority,
    REJECTION_SCHEMA,
    rom_finding_subject,
    source_finding_subject,
    source_error_subject,
)
from tools.rom_tests.full_color.inventory import (
    InventoryReconciliationError,
    InventoryValidationError,
    MutationInventory,
    SceneInventory,
    WriterInventory,
    reconcile,
)
from tools.rom_tests.full_color.rom_discovery import (
    MapSection,
    RomDiscoveryReport,
    RomFinding,
)
from tools.rom_tests.full_color.source_discovery import (
    SourceDiscoveryReport,
    SourceFinding,
)

HASH = "0" * 64
SYM_HASH = "1" * 64
MAP_HASH = "2" * 64
ROM = bytes.fromhex("00" * 0x100 + "e046cd0002")
ROM_HASH = hashlib.sha256(ROM).hexdigest()
ROM_SECTIONS = (MapSection(0, 0x100, 0x104, "test", "ROM0"),)


def evidence(*, reviewed: bool = True) -> dict[str, object]:
    return {
        "source_sha256": HASH,
        "rom_sha256": ROM_HASH,
        "sym_sha256": SYM_HASH,
        "map_sha256": MAP_HASH,
        "reviewer": "gate-0-review",
        "reviewed": reviewed,
    }


def source_site(symbol: str, line: int) -> dict[str, object]:
    return {
        "path": "engine/test.asm",
        "line": line,
        "symbol": symbol,
        "aliases": [],
        "object": "build/engine/test.o",
    }


def machine_site(address: int, data: str = "e046") -> dict[str, object]:
    return {
        "bank": 0,
        "address": address,
        "rom_offset": address,
        "bytes": data,
        "runtime_copy": None,
    }


def writer_row(
    writer_id: str = "WR-TEST",
    *,
    symbol: str = "Writer",
    line: int = 10,
    address: int = 0x100,
) -> dict[str, object]:
    return {
        "id": writer_id,
        "resources": [
            {
                "resource": "VRAM_BANK",
                "start": 0xFF4F,
                "end": 0xFF4F,
                "vram_bank": None,
                "aliases": ["rVBK"],
            }
        ],
        "source_sites": [source_site(symbol, line)],
        "machine_sites": [machine_site(address)],
        "kind": "DIRECT",
        "wrappers": [],
        "downstream": [],
        "reachability": {
            "roots": ["Reset"],
            "call_paths": [["Reset", symbol]],
            "scenes": ["SC-TEST"],
            "phases": ["YELLOW_ACTIVE"],
            "interrupt": False,
        },
        "owner": "RENDERER_YELLOW",
        "generation_checked": True,
        "bank_restore_permission": False,
        "commit_unit": "CU-VBK",
        "disposition": "KEEP",
        "requirements": ["R1.7"],
        "checks": ["CHK-INV-01"],
        "evidence": evidence(),
        "planned": False,
    }


def scene_row() -> dict[str, object]:
    return {
        "id": "SC-TEST",
        "row_kind": "DIRECTED_EDGE",
        "source": {
            "path": "engine/test.asm",
            "line": 20,
            "symbol": "EnterMap",
            "aliases": [],
        },
        "destination": {
            "path": "engine/test.asm",
            "line": 21,
            "symbol": "MapInit",
            "aliases": [],
        },
        "classification": "SCENE_BOUNDARY",
        "direction": "YELLOW_TO_MAP",
        "owner_before_destination_initialization": "RENDERER_YELLOW",
        "first_display_writers": ["WR-TEST"],
        "reconstruction": "REQUIRED",
        "edges": {"normal": [], "reset": [], "nested": [], "error": []},
        "machine_sites": [machine_site(0x102, "cd0002")],
        "requirements": ["R1.7"],
        "checks": ["CHK-INV-01"],
        "evidence": evidence(),
        "planned": False,
    }


def mutation_row() -> dict[str, object]:
    return {
        "id": "MU-TEST",
        "behavior": "RECTANGLE",
        "resources": ["BG_ATTRIBUTES", "BG_TILE_IDS"],
        "commit_unit": "RECTANGLE",
        "source_sites": [source_site("MutateMap", 30)],
        "machine_sites": [],
        "reachability": {
            "roots": ["Reset"],
            "call_paths": [["Reset", "MutateMap"]],
            "scenes": ["SC-TEST"],
            "phases": ["OVERWORLD_ACTIVE"],
            "interrupt": False,
        },
        "trigger": "map event",
        "destination": "BG_MAP_9800",
        "coordinate_handling": "signed source, unsigned destination",
        "clipping": "clip to visible map",
        "wrapping": "wrap 32x32 hardware map",
        "tile_source": "authoritative metatile expansion",
        "attribute_source": "authoritative full-byte attribute expansion",
        "dependencies": ["BG_ATTRIBUTES", "BG_TILE_IDS"],
        "baseline_commits": ["BG_TILE_IDS"],
        "required_commits": ["BG_ATTRIBUTES", "BG_TILE_IDS"],
        "owner": "RENDERER_FULL_COLOR_OVERWORLD",
        "phases": ["OVERWORLD_ACTIVE"],
        "generation_checked": True,
        "writer_ids": ["WR-TEST"],
        "disposition": "ROUTE",
        "requirements": ["R1.7"],
        "checks": ["CHK-INV-01"],
        "evidence": evidence(),
        "planned": False,
    }


def inventories():
    writers = WriterInventory.from_dict(
        {"schema": "full-color-writer-inventory-v1", "rows": [writer_row()]}
    )
    scenes = SceneInventory.from_dict(
        {"schema": "full-color-scene-inventory-v1", "rows": [scene_row()]}
    )
    mutations = MutationInventory.from_dict(
        {"schema": "full-color-mutation-inventory-v1", "rows": [mutation_row()]}
    )
    return writers, scenes, mutations


def findings():
    source_findings = [
        {
            "category": "writer",
            "path": "engine/test.asm",
            "line": 10,
            "symbol": "Writer",
            "resolved": True,
        },
        {
            "category": "scene_edge",
            "path": "engine/test.asm",
            "line": 20,
            "symbol": "EnterMap",
            "row_kind": "DIRECTED_EDGE",
            "direction": "YELLOW_TO_MAP",
            "destination_path": "engine/test.asm",
            "destination_line": 21,
            "destination": "MapInit",
            "resolved": True,
        },
        {
            "category": "mutation",
            "path": "engine/test.asm",
            "line": 30,
            "symbol": "MutateMap",
            "destination": "BG_MAP_9800",
            "resolved": True,
        },
    ]
    rom_findings = (
        {"category": "writer", "bank": 0, "address": 0x100, "resolved": True},
        {"category": "scene", "bank": 0, "address": 0x102, "resolved": True},
    )
    return (
        SourceDiscoveryReport(("main.asm",), (), tuple(source_findings), (), HASH),
        RomDiscoveryReport(
            rom_findings,
            (),
            ((0, 0x100), (0, 0x102)),
            ROM_HASH,
            SYM_HASH,
            MAP_HASH,
            (),
            (),
            ROM_SECTIONS,
        ),
    )


def test_all_three_authorities_round_trip_byte_stably_and_reconcile() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()

    assert WriterInventory.from_json(writers.to_json()) == writers
    assert SceneInventory.from_json(scenes.to_json()) == scenes
    assert MutationInventory.from_json(mutations.to_json()) == mutations
    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
    )
    assert report.closed
    assert report.to_json() == report.to_json()


def test_reviewed_rejections_are_exact_consumed_and_reported() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    rejected_source = SourceFinding(
        "writer",
        "engine/noise.asm",
        40,
        "Noise",
        "pointer",
        "hl",
        "COMPUTED_POINTER",
        resolved=False,
        evidence_sha256="4" * 64,
    )
    rejected_rom = RomFinding(
        0,
        0x104,
        0x104,
        "02",
        "pointer",
        None,
        None,
        "UNKNOWN_DESTINATION",
        None,
        None,
        "Noise",
        ("Noise",),
        None,
        False,
        "writer",
        None,
        None,
        None,
    )
    source_error = "engine/noise.asm:40: reviewed computed destination"
    source_report = SourceDiscoveryReport(
        source_report.roots,
        source_report.include_graph,
        source_report.findings + (rejected_source,),
        (source_error,),
        source_report.source_sha256,
    )
    rom_report = RomDiscoveryReport(
        rom_report.findings + (rejected_rom,),
        rom_report.unresolved_destinations,
        rom_report.visited + ((0, 0x104),),
        rom_report.rom_sha256,
        rom_report.sym_sha256,
        rom_report.map_sha256,
        rom_report.unresolved_control_flow,
        rom_report.candidate_findings,
        rom_report.candidate_sections,
    )
    review_evidence = evidence()

    def rejection(row_id, subject, reason):
        return {
            "id": row_id,
            "subject": subject.to_dict(),
            "reason": reason,
            "detail": "Reviewed exact baseline evidence proves this is not a writer.",
            "evidence": review_evidence,
        }

    rejections = DiscoveryRejectionAuthority.from_dict(
        {
            "schema": REJECTION_SCHEMA,
            "rows": [
                rejection(
                    "RV-ROM-NOISE",
                    rom_finding_subject(rejected_rom),
                    "UNREACHABLE_CODE_OR_DATA",
                ),
                rejection(
                    "RV-SOURCE-ERROR",
                    source_error_subject(source_error),
                    "CONTROL_FLOW_PROVED_BY_REVIEW",
                ),
                rejection(
                    "RV-SOURCE-NOISE",
                    source_finding_subject(rejected_source),
                    "NOT_A_WRITE",
                ),
            ],
        }
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        rejections=rejections,
    )

    assert report.closed
    assert report.matched_rejection_ids == (
        "RV-ROM-NOISE",
        "RV-SOURCE-ERROR",
        "RV-SOURCE-NOISE",
    )


def test_reviewed_machine_row_can_classify_distinct_unresolved_path() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    unresolved = RomFinding(
        0,
        0x100,
        0x100,
        "e046",
        "ldh-direct",
        None,
        None,
        "UNKNOWN_DESTINATION",
        None,
        None,
        "DifferentRoot",
        ("DifferentRoot",),
        None,
        False,
        "writer",
        None,
        None,
        None,
    )
    rom_report = RomDiscoveryReport(
        rom_report.findings + (unresolved,),
        rom_report.unresolved_destinations,
        rom_report.visited,
        rom_report.rom_sha256,
        rom_report.sym_sha256,
        rom_report.map_sha256,
        rom_report.unresolved_control_flow,
        rom_report.candidate_findings,
        rom_report.candidate_sections,
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        raise_on_error=False,
    )

    assert report.closed


def test_reviewed_writer_row_must_cover_resolved_rom_resource_and_range() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    wrong_resource = RomFinding(
        0,
        0x100,
        0x100,
        "e046",
        "ldh-direct",
        0xFF46,
        0xFF46,
        "DISPLAY_REGISTER",
        None,
        None,
        "Writer",
        ("Writer",),
        None,
        True,
        "writer",
        None,
        None,
        None,
    )
    rom_report = RomDiscoveryReport(
        (wrong_resource,) + rom_report.findings[1:],
        rom_report.unresolved_destinations,
        rom_report.visited,
        rom_report.rom_sha256,
        rom_report.sym_sha256,
        rom_report.map_sha256,
        rom_report.unresolved_control_flow,
        rom_report.candidate_findings,
        rom_report.candidate_sections,
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        raise_on_error=False,
    )

    assert any("DISPLAY_REGISTER ff46-ff46 is not reviewed" in e for e in report.errors)


def test_reviewed_writer_row_must_cover_resolved_source_address() -> None:
    raw_writer = writer_row()
    raw_writer["resources"][0]["start"] = 0xFF4E
    raw_writer["resources"][0]["end"] = 0xFF4E
    writers = WriterInventory.from_dict(
        {"schema": "full-color-writer-inventory-v1", "rows": [raw_writer]}
    )
    _, scenes, mutations = inventories()
    source_report, rom_report = findings()
    source_writer = SourceFinding(
        "writer",
        "engine/test.asm",
        10,
        "Writer",
        "direct",
        "ff4f",
        "VRAM_BANK",
        resolved=True,
        evidence_sha256="4" * 64,
    )
    source_report = SourceDiscoveryReport(
        source_report.roots,
        source_report.include_graph,
        (source_writer,) + source_report.findings[1:],
        source_report.errors,
        source_report.source_sha256,
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        raise_on_error=False,
    )

    assert any("VRAM_BANK ff4f is not reviewed" in e for e in report.errors)


@pytest.mark.parametrize(
    ("authority", "mutate", "message"),
    [
        ("scene", lambda row: row.pop("direction"), "missing fields: direction"),
        (
            "scene",
            lambda row: row.update({"classification": "RESOURCE"}),
            "unknown value",
        ),
        (
            "scene",
            lambda row: row.update(
                {"direction": "MAP_TO_YELLOW", "reconstruction": "REQUIRED"}
            ),
            "reconstruction is required only",
        ),
        ("mutation", lambda row: row.update({"dependencies": []}), "non-empty array"),
        (
            "mutation",
            lambda row: row.update({"commit_unit": "PARTIAL"}),
            "unknown value",
        ),
        (
            "writer",
            lambda row: row.update({"owner": "ANY_OWNER"}),
            "unknown value",
        ),
    ],
)
def test_missing_direction_category_dependency_and_bad_owner_are_rejected(
    authority, mutate, message
) -> None:
    rows = {
        "writer": (
            WriterInventory,
            "full-color-writer-inventory-v1",
            writer_row(),
        ),
        "scene": (SceneInventory, "full-color-scene-inventory-v1", scene_row()),
        "mutation": (
            MutationInventory,
            "full-color-mutation-inventory-v1",
            mutation_row(),
        ),
    }
    cls, schema, row = rows[authority]
    mutate(row)

    with pytest.raises(InventoryValidationError, match=message):
        cls.from_dict({"schema": schema, "rows": [row]})


def test_duplicate_machine_site_and_stale_or_orphan_findings_fail() -> None:
    duplicate = writer_row("WR-SECOND", symbol="Other", line=11)
    with pytest.raises(InventoryValidationError, match="duplicate machine site"):
        WriterInventory.from_dict(
            {
                "schema": "full-color-writer-inventory-v1",
                "rows": [duplicate, writer_row()],
            }
        )

    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    source = list(source_report.findings)
    source.pop(0)
    source.append(
        {
            "category": "writer",
            "path": "engine/other.asm",
            "line": 99,
            "symbol": "Orphan",
        }
    )
    source_report = SourceDiscoveryReport(
        source_report.roots,
        source_report.include_graph,
        tuple(source),
        source_report.errors,
        source_report.source_sha256,
    )
    with pytest.raises(InventoryReconciliationError) as exc:
        reconcile(
            writers,
            scenes,
            mutations,
            source_report=source_report,
            rom_report=rom_report,
            rom=ROM,
        )
    assert "orphan finding" in str(exc.value)
    assert "stale source site" in str(exc.value)


def test_unresolved_rom_and_reachable_unreviewed_planned_rows_fail() -> None:
    raw_writer = writer_row()
    raw_writer["evidence"] = evidence(reviewed=False)
    raw_writer["planned"] = True
    raw_writer["disposition"] = "PLANNED"
    writers = WriterInventory.from_dict(
        {"schema": "full-color-writer-inventory-v1", "rows": [raw_writer]}
    )
    scenes = SceneInventory.from_dict(
        {"schema": "full-color-scene-inventory-v1", "rows": [scene_row()]}
    )
    mutations = MutationInventory.from_dict(
        {"schema": "full-color-mutation-inventory-v1", "rows": [mutation_row()]}
    )
    source_report, rom_report = findings()
    bad_rom_findings = list(rom_report.findings)
    bad_rom_findings[0] = {
        "category": "writer",
        "bank": 0,
        "address": 0x100,
        "resolved": False,
    }
    rom_report = RomDiscoveryReport(
        tuple(bad_rom_findings),
        ("unresolved pointer",),
        rom_report.visited,
        ROM_HASH,
        SYM_HASH,
        MAP_HASH,
        (),
        (),
        ROM_SECTIONS,
    )

    with pytest.raises(InventoryReconciliationError) as exc:
        reconcile(
            writers,
            scenes,
            mutations,
            source_report=source_report,
            rom_report=rom_report,
            rom=ROM,
        )
    assert "planned row is reachable before review" in str(exc.value)
    assert "ROM unresolved" in str(exc.value)
    assert "unreviewed row" in str(exc.value)


def test_bad_hash_and_second_destination_require_separate_reviewed_rows() -> None:
    row = writer_row()
    row["evidence"]["source_sha256"] = "not-a-hash"
    with pytest.raises(InventoryValidationError, match="hashes must be"):
        WriterInventory.from_dict(
            {"schema": "full-color-writer-inventory-v1", "rows": [row]}
        )

    second = deepcopy(mutation_row())
    second["id"] = "MU-TEST-SECOND"
    second["destination"] = "BG_MAP_9C00"
    second["source_sites"][0]["line"] = 31
    inventory = MutationInventory.from_dict(
        {
            "schema": "full-color-mutation-inventory-v1",
            "rows": [mutation_row(), second],
        }
    )
    assert [row["destination"] for row in inventory.rows] == [
        "BG_MAP_9800",
        "BG_MAP_9C00",
    ]


def test_reconciliation_can_verify_hashes_and_machine_bytes() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    rom = bytes(0x102)

    with pytest.raises(InventoryReconciliationError) as exc:
        reconcile(
            writers,
            scenes,
            mutations,
            source_report=source_report,
            rom_report=rom_report,
            rom=rom,
        )
    assert "ROM report hash" in str(exc.value)
    assert "machine bytes do not match" in str(exc.value)


def test_reconciliation_rejects_incomplete_candidate_section_coverage() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    incomplete = RomDiscoveryReport(
        rom_report.findings,
        rom_report.unresolved_destinations,
        rom_report.visited,
        rom_report.rom_sha256,
        rom_report.sym_sha256,
        rom_report.map_sha256,
        rom_report.unresolved_control_flow,
        rom_report.candidate_findings,
        (MapSection(0, 0x102, 0x104, "incomplete", "ROM0"),),
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=incomplete,
        rom=ROM,
        raise_on_error=False,
    )

    assert not report.closed
    assert any(
        "candidate scan coverage omits 00:0100" in error for error in report.errors
    )


@pytest.mark.parametrize(
    ("bank", "address", "offset"),
    (
        (0, 0x4000, 0x4000),
        (1, 0x3FFF, 0x3FFF),
        (1, 0x8000, 0x8000),
    ),
)
def test_machine_sites_use_exact_rom_normalization(bank, address, offset) -> None:
    row = writer_row()
    row["machine_sites"][0].update(
        {"bank": bank, "address": address, "rom_offset": offset}
    )
    with pytest.raises(
        InventoryValidationError, match="invalid ROM address|cannot map"
    ):
        WriterInventory.from_dict(
            {"schema": "full-color-writer-inventory-v1", "rows": [row]}
        )


def test_hashless_empty_and_report_level_unresolved_never_close() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    source_report = SourceDiscoveryReport(
        source_report.roots,
        source_report.include_graph,
        source_report.findings,
        (),
        "",
    )
    rom_report = RomDiscoveryReport(
        rom_report.findings,
        (),
        rom_report.visited,
        rom_report.rom_sha256,
        rom_report.sym_sha256,
        rom_report.map_sha256,
        ("computed jump",),
        (),
        ROM_SECTIONS,
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        raise_on_error=False,
    )
    assert not report.closed
    assert any("source_sha256" in error for error in report.errors)
    assert any("unresolved control flow" in error for error in report.errors)

    empty_writers = WriterInventory.from_dict(
        {"schema": "full-color-writer-inventory-v1", "rows": []}
    )
    empty_scenes = SceneInventory.from_dict(
        {"schema": "full-color-scene-inventory-v1", "rows": []}
    )
    empty_mutations = MutationInventory.from_dict(
        {"schema": "full-color-mutation-inventory-v1", "rows": []}
    )
    empty_report = reconcile(
        empty_writers,
        empty_scenes,
        empty_mutations,
        source_report=SourceDiscoveryReport((), (), (), (), ""),
        rom_report=RomDiscoveryReport((), (), (), "", "", "", (), (), ()),
        rom=b"",
        raise_on_error=False,
    )
    assert not empty_report.closed
    assert all(
        any(f"{kind} authority is empty" in error for error in empty_report.errors)
        for kind in ("writer", "scene", "mutation")
    )


def test_scene_edge_identity_includes_direction_destination_line_and_site() -> None:
    writers, scenes, mutations = inventories()
    source_report, rom_report = findings()
    altered = list(source_report.findings)
    altered[1] = {
        **altered[1],
        "direction": "MAP_TO_YELLOW",
        "destination_line": 22,
    }
    source_report = SourceDiscoveryReport(
        source_report.roots,
        source_report.include_graph,
        tuple(altered),
        (),
        source_report.source_sha256,
    )

    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=source_report,
        rom_report=rom_report,
        rom=ROM,
        raise_on_error=False,
    )
    assert not report.closed
    assert any("orphan finding" in error for error in report.errors)
    assert any("stale source site" in error for error in report.errors)
