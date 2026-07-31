"""Canonical authority and honest open-progress coverage."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.baseline_discovery import (
    discover_baseline_rom,
    discover_baseline_sources,
)
from tools.rom_tests.full_color.baseline_inventory import (
    PROGRESS_SCHEMA,
    build_progress,
    progress_json,
)
from tools.rom_tests.full_color.discovery_assignment import (
    DiscoveryAssignmentAuthority,
    StaleDiscoveryAssignmentError,
)
from tools.rom_tests.full_color.inventory import (
    InventoryReconciliationError,
    MutationInventory,
    SceneInventory,
    WriterInventory,
)

ROOT = Path(__file__).parents[5]
AUTHORITY = ROOT / "specs/full-colors/inventory"
ROW_IDS = (
    "MU-YELLOW-MAP-VIEW-INITIAL",
    "SC-YELLOW-MAP-ENTRY",
    "WR-YELLOW-LCDC-DISABLE",
    "WR-YELLOW-MAP-VIEW-TILE-COPY",
)


def authorities():
    return (
        WriterInventory.load(AUTHORITY / "writers.json"),
        SceneInventory.load(AUTHORITY / "scenes.json"),
        MutationInventory.load(AUTHORITY / "mutations.json"),
        DiscoveryAssignmentAuthority.load(AUTHORITY / "assignments.json"),
    )


@pytest.fixture(scope="module")
def real_bundle():
    source = discover_baseline_sources(ROOT)
    rom = discover_baseline_rom(ROOT, source_report=source)
    return (*authorities(), source, rom, (ROOT / "pokeyellow_debug.gbc").read_bytes())


def test_canonical_authorities_load_and_round_trip() -> None:
    writers, scenes, mutations, assignments = authorities()
    assert WriterInventory.from_json(writers.to_json()) == writers
    assert SceneInventory.from_json(scenes.to_json()) == scenes
    assert MutationInventory.from_json(mutations.to_json()) == mutations
    assert DiscoveryAssignmentAuthority.from_json(assignments.to_json()) == assignments
    assert len(assignments.rows) == 8


def test_exact_reviewed_map_entry_tranche() -> None:
    writers, scenes, mutations, _ = authorities()
    writer = {row["id"]: row for row in writers.rows}
    scene = scenes.rows[0]
    mutation = mutations.rows[0]
    assert tuple(sorted((*writer, scene["id"], mutation["id"]))) == ROW_IDS
    assert scene["classification"] == "MAP_BACKED"
    assert scene["first_display_writers"] == ["WR-YELLOW-LCDC-DISABLE"]
    assert mutation["behavior"] == "INITIAL_LOAD"
    assert mutation["destination"] == "BG_MAP_9800"
    assert mutation["commit_unit"] == "RECTANGLE"
    assert mutation["tile_source"] == "wTileMap"
    assert mutation["attribute_source"] == "none; the baseline writes no attributes"
    assert mutation["writer_ids"] == ["WR-YELLOW-MAP-VIEW-TILE-COPY"]
    assert writer["WR-YELLOW-MAP-VIEW-TILE-COPY"]["generation_checked"] is False
    assert all(
        row["evidence"]["reviewed"]
        for row in (*writers.rows, *scenes.rows, *mutations.rows)
    )
    assert all(
        not row["planned"] for row in (*writers.rows, *scenes.rows, *mutations.rows)
    )


def test_progress_json_is_canonical_for_fake_progress(monkeypatch) -> None:
    fake = {"schema": PROGRESS_SCHEMA, "closed": False, "pending": {"errors": 1}}
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_inventory.baseline_inventory_progress",
        lambda repository: fake,
    )
    expected = json.dumps(fake, sort_keys=True, separators=(",", ":")) + "\n"
    assert progress_json("repo") == expected == progress_json("repo")


def test_real_progress_is_open_and_matches_all_reviewed_rows(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    progress = build_progress(
        writers=writers,
        scenes=scenes,
        mutations=mutations,
        assignments=assignments,
        source_report=source,
        rom_report=rom_report,
        rom=rom,
    )
    assert progress["schema"] == PROGRESS_SCHEMA
    assert progress["closed"] is False
    assert tuple(progress["reviewed_rows"]["row_ids"]) == ROW_IDS
    assert progress["assigned"]["source_count"] == 4
    assert progress["assigned"]["rom_count"] == 4
    assert progress["matched"]["source_count"] == 4
    assert progress["matched"]["machine_count"] == 4
    assert progress["pending"]["errors"] > 0
    assert progress["pending"]["rom_candidates"] > 0


def test_stale_assignment_source_and_rom_bytes_fail_closed(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    stale_raw = assignments.to_dict()
    stale_raw["rows"][0]["evidence"]["source_sha256"] = "0" * 64
    stale_assignments = DiscoveryAssignmentAuthority.from_dict(stale_raw)
    with pytest.raises(StaleDiscoveryAssignmentError, match="stale baseline evidence"):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=stale_assignments,
            source_report=source,
            rom_report=rom_report,
            rom=rom,
        )

    changed = list(source.findings)
    index = next(i for i, finding in enumerate(changed) if finding.symbol == "EnterMap")
    changed[index] = replace(changed[index], line=2)
    with pytest.raises(StaleDiscoveryAssignmentError, match="not rediscovered"):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
            source_report=replace(source, findings=tuple(changed)),
            rom_report=rom_report,
            rom=rom,
        )

    changed_rom = bytearray(rom)
    changed_rom[0x75] ^= 0xFF
    with pytest.raises(InventoryReconciliationError, match="machine bytes"):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
            source_report=source,
            rom_report=rom_report,
            rom=bytes(changed_rom),
        )


def test_assignment_cannot_name_the_wrong_inventory_row(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    wrong_raw = assignments.to_dict()
    lcdc = next(
        row for row in wrong_raw["rows"] if row["id"].endswith("LCDC-DISABLE-SOURCE")
    )
    map_copy = next(
        row
        for row in wrong_raw["rows"]
        if row["id"].endswith("MAP-VIEW-TILE-COPY-SOURCE")
    )
    lcdc["row_id"], map_copy["row_id"] = map_copy["row_id"], lcdc["row_id"]
    wrong = DiscoveryAssignmentAuthority.from_dict(wrong_raw)

    with pytest.raises(
        InventoryReconciliationError,
        match="source subject does not belong",
    ):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=wrong,
            source_report=source,
            rom_report=rom_report,
            rom=rom,
        )
