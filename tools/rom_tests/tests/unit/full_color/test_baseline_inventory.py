"""Canonical authority and honest open-progress coverage."""

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from tools.rom_tests.full_color.baseline_discovery import (
    discover_baseline_rom,
    discover_baseline_sources,
)
from tools.rom_tests.full_color.baseline_inventory import (
    PROGRESS_SCHEMA,
    REVIEWED_SLICE,
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
from tools.rom_tests.full_color.rom_discovery import MapSection, discover_rom, parse_sym
from tools.rom_tests.full_color.source_discovery import discover_sources

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


def assignments_for_reports(assignments, source, rom_report):
    """Keep assignment evidence current while retaining reviewed subjects."""
    raw = assignments.to_dict()
    for row in raw["rows"]:
        row["evidence"].update(
            source_sha256=source.source_sha256,
            rom_sha256=rom_report.rom_sha256,
            sym_sha256=rom_report.sym_sha256,
            map_sha256=rom_report.map_sha256,
        )
    return DiscoveryAssignmentAuthority.from_dict(raw)


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
    fake = {"schema": PROGRESS_SCHEMA, "closed": True, "backlog": {"errors": 1}}
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_inventory.baseline_inventory_progress",
        lambda repository: fake,
    )
    expected = json.dumps(fake, sort_keys=True, separators=(",", ":")) + "\n"
    assert progress_json("repo") == expected == progress_json("repo")


def test_real_progress_closes_slice_and_keeps_global_backlog(real_bundle) -> None:
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
    assert progress["closed"] is True
    assert progress["reviewed_slice"] == {
        "closed": True,
        "name": REVIEWED_SLICE,
        "rom_unlisted_count": 0,
        "source_unlisted_count": 0,
    }
    assert tuple(progress["reviewed_rows"]["row_ids"]) == ROW_IDS
    assert progress["assigned"]["source_count"] == 4
    assert progress["assigned"]["rom_count"] == 4
    assert progress["matched"]["source_count"] == 4
    assert progress["matched"]["machine_count"] == 4
    assert progress["backlog"]["errors"] > 0
    assert progress["backlog"]["rom_candidates"] > 0


def test_unlisted_source_local_label_inside_reviewed_slice_fails_closed(
    real_bundle, tmp_path
) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    fixture = tmp_path / "local.asm"
    fixture.write_text(
        "DisableLCD::\n.extra:\n\tldh [$ff40], a\n\tret\n",
        encoding="utf-8",
    )
    changed = discover_sources(tmp_path, ("local.asm",))
    unexpected = next(
        finding for finding in changed.findings if finding.symbol == "DisableLCD.extra"
    )
    changed_source = replace(
        source,
        findings=(*source.findings, unexpected),
        source_sha256=changed.source_sha256,
    )
    changed_assignments = assignments_for_reports(
        assignments, changed_source, rom_report
    )

    with pytest.raises(
        InventoryReconciliationError,
        match=r"unexpected unlisted source item.*DisableLCD\.extra",
    ):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=changed_assignments,
            source_report=changed_source,
            rom_report=rom_report,
            rom=rom,
        )


def test_unlisted_rom_local_label_inside_reviewed_slice_fails_closed(
    real_bundle,
) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    changed = discover_rom(
        bytes.fromhex("00" * 0x100 + "e040c9"),
        parse_sym("00:0100 DisableLCD.extra\n"),
        ("DisableLCD.extra",),
        sections=(MapSection(0, 0x100, 0x102, "local", "ROM0"),),
    )
    unexpected = next(
        finding for finding in changed.findings if finding.root == "DisableLCD.extra"
    )
    changed_report = replace(
        rom_report,
        findings=(*rom_report.findings, unexpected),
        rom_sha256=changed.rom_sha256,
    )
    changed_assignments = assignments_for_reports(assignments, source, changed_report)

    with pytest.raises(
        InventoryReconciliationError,
        match=r"unexpected unlisted ROM item.*DisableLCD\.extra",
    ):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=changed_assignments,
            source_report=source,
            rom_report=changed_report,
            rom=rom,
        )


def test_real_rom_byte_mutation_reaches_unlisted_slice_failure(
    real_bundle, tmp_path
) -> None:
    writers, scenes, mutations, assignments, source, _, _ = real_bundle
    for name in ("pokeyellow_debug.sym", "pokeyellow_debug.map"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    (tmp_path / "data").mkdir()
    shutil.copyfile(
        ROOT / "data/predef_pointers.asm", tmp_path / "data/predef_pointers.asm"
    )
    changed_rom = bytearray((ROOT / "pokeyellow_debug.gbc").read_bytes())
    changed_rom[0x77:0x79] = bytes.fromhex("e040")
    (tmp_path / "pokeyellow_debug.gbc").write_bytes(changed_rom)
    changed_report = discover_baseline_rom(tmp_path, source_report=source)
    assert any(
        finding.root == "DisableLCD" and finding.address == 0x77
        for finding in changed_report.findings
    )
    changed_assignments = assignments_for_reports(assignments, source, changed_report)

    with pytest.raises(
        InventoryReconciliationError,
        match="unexpected unlisted ROM item.*DisableLCD",
    ):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=changed_assignments,
            source_report=source,
            rom_report=changed_report,
            rom=bytes(changed_rom),
        )


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
    with pytest.raises(
        InventoryReconciliationError,
        match="unexpected unlisted source item.*EnterMap",
    ):
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
