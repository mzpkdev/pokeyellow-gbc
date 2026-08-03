"""Canonical authority and honest open-progress coverage."""

from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import tools.rom_tests.full_color.baseline_inventory as baseline_inventory

from tools.rom_tests.full_color.baseline_discovery import (
    discover_baseline_rom,
    discover_baseline_sources,
)
from tools.rom_tests.full_color.baseline_inventory import (
    PROGRESS_SCHEMA,
    REVIEWED_SLICE,
    build_progress,
    PHASE2_PLANNED_ROW_IDS,
    progress_json,
    _phase2_transition_state,
    _select_inventory_rows,
    _validate_assignment_targets,
)
from tools.rom_tests.full_color.discovery_assignment import (
    DiscoveryAssignmentAuthority,
    StaleDiscoveryAssignmentError,
)
from tools.rom_tests.full_color.discovery_review import source_finding_subject
from tools.rom_tests.full_color.inventory import (
    InventoryReconciliationError,
    InventoryValidationError,
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


def reviewed_authorities():
    writers, scenes, mutations, assignments = authorities()
    normal = assignments.for_product()
    normal_ids = {row.row_id for row in normal.rows}
    return (
        _select_inventory_rows(writers, normal_ids),
        _select_inventory_rows(scenes, normal_ids),
        _select_inventory_rows(mutations, normal_ids),
        normal,
    )


def assignments_for_reports(assignments, source, rom_report):
    """Keep assignment evidence current while retaining reviewed subjects."""
    raw = assignments.to_dict()
    for row in raw["rows"]:
        if row.get("product", "pokeyellow_debug") != "pokeyellow_debug":
            continue
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
    return (
        *authorities(),
        source,
        rom,
        (ROOT / "pokeyellow_debug.gbc").read_bytes(),
    )


def test_canonical_authorities_load_and_round_trip() -> None:
    writers, scenes, mutations, assignments = authorities()
    assert WriterInventory.from_json(writers.to_json()) == writers
    assert SceneInventory.from_json(scenes.to_json()) == scenes
    assert MutationInventory.from_json(mutations.to_json()) == mutations
    assert DiscoveryAssignmentAuthority.from_json(assignments.to_json()) == assignments
    assert len(assignments.for_product().rows) == 8
    assert len(assignments.for_product("pokeyellow_phase2_audit").rows) == 1379


def test_exact_reviewed_map_entry_tranche() -> None:
    writers, scenes, mutations, _ = authorities()
    normal_ids = {row.row_id for row in authorities()[3].for_product().rows}
    reviewed_writers = tuple(row for row in writers.rows if row["id"] in normal_ids)
    reviewed_scenes = tuple(row for row in scenes.rows if row["id"] in normal_ids)
    reviewed_mutations = tuple(row for row in mutations.rows if row["id"] in normal_ids)
    planned = tuple(
        row
        for row in (*writers.rows, *scenes.rows, *mutations.rows)
        if row["planned"]
    )
    writer = {row["id"]: row for row in reviewed_writers}
    scene = reviewed_scenes[0]
    mutation = reviewed_mutations[0]
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
        for row in (*reviewed_writers, *reviewed_scenes, *reviewed_mutations)
    )
    assert all(
        not row["planned"]
        for row in (*reviewed_writers, *reviewed_scenes, *reviewed_mutations)
    )
    assert not planned
    phase2 = tuple(
        row for row in (*writers.rows, *scenes.rows, *mutations.rows)
        if row["id"] in PHASE2_PLANNED_ROW_IDS
    )
    assert len(phase2) == 18
    assert all(row["evidence"]["reviewed"] for row in phase2)


def test_normal_product_partition_never_selects_audit_inventory_rows() -> None:
    writers, scenes, mutations, assignments = authorities()
    normal_ids = {
        row.row_id for row in assignments.for_product().rows
    }
    for document in (writers, scenes, mutations):
        selected = _select_inventory_rows(document, normal_ids)
        assert all(row["id"] in normal_ids for row in selected.rows)
        assert not ({row["id"] for row in selected.rows} & PHASE2_PLANNED_ROW_IDS)


def test_partial_phase2_closure_fails_atomically() -> None:
    writers, scenes, mutations, assignments = authorities()
    raw = writers.to_dict()
    row = next(item for item in raw["rows"] if item["id"] in PHASE2_PLANNED_ROW_IDS)
    row["planned"] = True
    row["evidence"]["reviewed"] = False
    with pytest.raises(InventoryReconciliationError, match="transition all 18 rows"):
        _phase2_transition_state(
            writers=WriterInventory.from_dict(raw), scenes=scenes,
            mutations=mutations, assignments=assignments,
        )


def test_planned_phase2_rows_reject_audit_assignments() -> None:
    writers, scenes, mutations, _ = authorities()

    def reopen(document):
        raw = document.to_dict()
        for row in raw["rows"]:
            if row["id"] in PHASE2_PLANNED_ROW_IDS:
                row["planned"] = True
                row["evidence"]["reviewed"] = False
        return type(document).from_dict(raw)

    class MixedAuthority:
        def for_product(self, product):
            return SimpleNamespace(
                rows=(SimpleNamespace(row_id=next(iter(PHASE2_PLANNED_ROW_IDS))),)
            )

    with pytest.raises(InventoryReconciliationError, match="consume closure assignments"):
        _phase2_transition_state(
            writers=reopen(writers), scenes=reopen(scenes), mutations=reopen(mutations),
            assignments=MixedAuthority(),
        )


def test_audit_scene_direction_must_match_inventory_vocabulary() -> None:
    writers, scenes, mutations, _ = authorities()
    target = next(row for row in scenes.rows if row["id"] == "SC-P2-PARTY-ENTRY")
    assignment = SimpleNamespace(
        id="AS-P2-PARTY-WRONG-DIRECTION",
        row_id=target["id"],
        category=SimpleNamespace(value="scene"),
        subject=SimpleNamespace(
            kind=SimpleNamespace(value="SOURCE_FINDING"),
            metadata={
                "path": target["source"]["path"],
                "line": target["source"]["line"],
                "symbol": target["source"]["symbol"],
            },
        ),
        mutation=None,
        scene=SimpleNamespace(
            row_kind=target["row_kind"],
            direction="YELLOW_TO_MAP",
            destination_path=target["destination"]["path"],
            destination_line=target["destination"]["line"],
            destination_symbol=target["destination"]["symbol"],
        ),
    )
    with pytest.raises(InventoryReconciliationError, match="scene shape does not match"):
        _validate_assignment_targets(
            SimpleNamespace(rows=(assignment,)), writers, scenes, mutations
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
    assert progress["planned_rows"] == {"row_ids": [], "total_count": 0}
    assert progress["assigned"]["source_count"] == 4
    assert progress["assigned"]["rom_count"] == 4
    assert progress["matched"]["source_count"] == 4
    assert progress["matched"]["machine_count"] == 4
    assert progress["backlog"]["errors"] > 0
    assert progress["backlog"]["rom_candidates"] > 0


def test_real_progress_applies_transition_after_evidence_identity_refresh(
    real_bundle,
) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    normal = assignments.for_product()
    assert {row.evidence.source_sha256 for row in normal.rows} == {
        source.source_sha256
    }
    raw_subjects = {
        source_finding_subject(finding).sha256 for finding in source.findings
    }
    reviewed_subjects = {
        row.subject.sha256
        for row in normal.rows
        if row.subject.kind.value == "SOURCE_FINDING"
    }
    assert not reviewed_subjects <= raw_subjects

    progress = build_progress(
        writers=writers,
        scenes=scenes,
        mutations=mutations,
        assignments=assignments,
        source_report=source,
        rom_report=rom_report,
        rom=rom,
    )

    assert progress["closed"] is True
    assert progress["reviewed_slice"]["source_unlisted_count"] == 0


def test_audit_transition_rejects_source_changes_outside_bound_manifest(
    real_bundle, monkeypatch
) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    real_manifest = baseline_inventory._source_path_manifest

    def changed_manifest(repository, paths):
        manifest = real_manifest(repository, paths)
        manifest["audio.asm"] = "0" * 64
        return manifest

    monkeypatch.setattr(baseline_inventory, "_source_path_manifest", changed_manifest)
    with pytest.raises(
        InventoryReconciliationError,
        match="outside the hash-bound audit-only change set",
    ):
        build_progress(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
            source_report=source,
            rom_report=rom_report,
            rom=rom,
            repository=ROOT,
        )


@pytest.mark.parametrize("mode", ["duplicate", "traversal", "no-delta", "phantom"])
def test_audit_transition_manifest_has_exact_safe_delta_paths(
    real_bundle, tmp_path, monkeypatch, mode
) -> None:
    _, _, _, assignments, source, _, _ = real_bundle
    assignments = assignments.for_product()
    transition_path = ROOT / baseline_inventory.SOURCE_TRANSITION_PATH
    text = transition_path.read_text(encoding="utf-8")
    if mode == "duplicate":
        text = text.replace(
            '"audit_only_paths": {',
            '"audit_only_paths": {}, "audit_only_paths": {',
            1,
        )
    else:
        raw = json.loads(text)
        if mode == "traversal":
            raw["audit_only_paths"]["../main.asm"] = raw["audit_only_paths"].pop("main.asm")
        elif mode == "no-delta":
            raw["audit_only_paths"]["main.asm"]["reviewed_sha256"] = raw["audit_only_paths"]["main.asm"]["audit_sha256"]
        else:
            raw["audit_only_paths"]["phantom.asm"] = {
                "reviewed_sha256": None,
                "audit_sha256": None,
            }
        text = json.dumps(raw)
    changed = tmp_path / "transition.json"
    changed.write_text(text, encoding="utf-8")
    monkeypatch.setattr(baseline_inventory, "SOURCE_TRANSITION_PATH", changed)
    with pytest.raises(
        InventoryReconciliationError,
        match="valid audit-only transition|not normalized|no actual delta|malformed audit path hash",
    ):
        baseline_inventory._reviewed_source_view(assignments, source, ROOT)


def test_closed_row_cannot_become_unreviewed(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    raw = json.loads(writers.to_json())
    planned = next(row for row in raw["rows"] if row["id"] in PHASE2_PLANNED_ROW_IDS)
    planned["evidence"]["reviewed"] = False
    changed = WriterInventory.from_dict(raw)
    with pytest.raises(
        InventoryReconciliationError, match="transition all 18 rows"
    ):
        build_progress(
            writers=changed,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
            source_report=source,
            rom_report=rom_report,
            rom=rom,
        )


def test_closed_row_cannot_return_to_planned_state(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    raw = json.loads(writers.to_json())
    planned = next(row for row in raw["rows"] if row["id"] in PHASE2_PLANNED_ROW_IDS)
    planned["planned"] = True
    planned["evidence"]["reviewed"] = False
    changed = WriterInventory.from_dict(raw)
    with pytest.raises(
        InventoryReconciliationError, match="transition all 18 rows"
    ):
        build_progress(
            writers=changed,
            scenes=scenes,
            mutations=mutations,
            assignments=assignments,
            source_report=source,
            rom_report=rom_report,
            rom=rom,
        )


@pytest.mark.parametrize(
    "mutation", ["machine-site", "bytes", "root", "resources", "commit"]
)
def test_closed_palette_inventory_mutation_does_not_affect_gate0_partition(
    real_bundle, mutation
) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    raw = json.loads(writers.to_json())
    row = next(
        item for item in raw["rows"] if item["id"] == "WR-P2-YELLOW-BG-PALETTE"
    )
    if mutation == "machine-site":
        row["machine_sites"] = []
    elif mutation == "bytes":
        row["machine_sites"][0]["bytes"] = "fb1acf"
    elif mutation == "root":
        row["reachability"]["roots"] = ["RunPaletteCommand.altered"]
        row["reachability"]["call_paths"] = [["RunPaletteCommand.altered"]]
    elif mutation == "resources":
        row["resources"][0]["end"] = 0xFF6A
    else:
        row["commit_unit"] = "BYTE"
    progress = build_progress(
        writers=WriterInventory.from_dict(raw), scenes=scenes,
        mutations=mutations, assignments=assignments, source_report=source,
        rom_report=rom_report, rom=rom,
    )
    assert progress["reviewed_rows"]["row_ids"] == list(ROW_IDS)


def test_closed_writer_schema_requires_declared_source_evidence() -> None:
    writers = WriterInventory.load(AUTHORITY / "writers.json")
    raw = json.loads(writers.to_json())
    row = next(item for item in raw["rows"] if item["id"] in PHASE2_PLANNED_ROW_IDS)
    row["source_sites"] = []
    with pytest.raises(
        InventoryValidationError,
        match="source_sites.*non-empty array",
    ):
        WriterInventory.from_dict(raw)


def test_closed_row_without_machine_evidence_is_not_a_gate0_subject(real_bundle) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    raw = json.loads(writers.to_json())
    row = next(
        item for item in raw["rows"]
        if item["id"] == "WR-P2-YELLOW-ANIMATION-TILES"
    )
    row["machine_sites"] = []
    progress = build_progress(
        writers=WriterInventory.from_dict(raw), scenes=scenes,
        mutations=mutations, assignments=assignments, source_report=source,
        rom_report=rom_report, rom=rom,
    )
    assert progress["matched"]["machine_count"] == 4


@pytest.mark.parametrize("mode", ["delete", "unreview", "substitute"])
def test_phase2_row_ids_are_an_exact_closed_set(real_bundle, mode) -> None:
    writers, scenes, mutations, assignments, source, rom_report, rom = real_bundle
    raw = json.loads(writers.to_json())
    planned_index = next(
        i for i, row in enumerate(raw["rows"])
        if row["id"] in PHASE2_PLANNED_ROW_IDS
    )
    if mode == "delete":
        raw["rows"].pop(planned_index)
    elif mode == "unreview":
        raw["rows"][planned_index]["evidence"]["reviewed"] = False
    else:
        raw["rows"][planned_index]["id"] = "WR-P2-SUBSTITUTED"
        raw["rows"].sort(key=lambda row: row["id"])
    with pytest.raises(
        InventoryReconciliationError,
        match="exact closed set|transition all 18 rows",
    ):
        build_progress(
            writers=WriterInventory.from_dict(raw), scenes=scenes, mutations=mutations,
            assignments=assignments, source_report=source, rom_report=rom_report, rom=rom,
        )


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
    required_sources = {
        *(relative for relative, _ in source.include_graph),
        str(baseline_inventory.SOURCE_TRANSITION_PATH),
    }
    for relative in sorted(required_sources):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    changed_rom = bytearray((ROOT / "pokeyellow_debug.gbc").read_bytes())
    changed_rom[0x77:0x79] = bytes.fromhex("e040")
    (tmp_path / "pokeyellow_debug.gbc").write_bytes(changed_rom)
    changed_report = discover_baseline_rom(tmp_path, source_report=source)
    assert any(
        finding.root == "DisableLCD.wait" and finding.address == 0x77
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
    for row in stale_raw["rows"]:
        if row.get("product", "pokeyellow_debug") == "pokeyellow_debug":
            row["evidence"]["source_sha256"] = "0" * 64
    stale_assignments = DiscoveryAssignmentAuthority.from_dict(stale_raw)
    with pytest.raises(
        (StaleDiscoveryAssignmentError, InventoryReconciliationError),
        match="stale baseline evidence|does not bind reviewed source hash",
    ):
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
        match="audit-only transition target subject is absent",
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
