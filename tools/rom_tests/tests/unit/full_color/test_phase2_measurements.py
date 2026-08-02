"""Phase 2 hostile-slice measured-representation tests."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import tools.rom_tests.full_color.phase2_measurements as phase2_measurements
import tools.rom_tests.full_color.baseline_inventory as baseline_inventory

from tools.rom_tests.full_color.phase2_measurements import (
    DEFINITION_PATH,
    MINIMUM_STACK_MARGIN,
    PHASE1_STATE_BYTES,
    Phase2Candidate,
    Phase2Measurement,
    Phase2MeasurementError,
    RequestClassMeasurement,
    generate,
    discover_phase2_sources,
    load_definition,
    select_phase2_representation,
    verify_evidence,
    _phase2_roots,
    _verify_audit_product,
    audit_phase2_inventory,
)
from tools.rom_tests.full_color.inventory import WriterInventory
ROOT = Path(__file__).resolve().parents[5]
DEFINITION = load_definition(ROOT / DEFINITION_PATH)


def audit_product_fixture(root: Path) -> None:
    roots = _phase2_roots()
    marker_address = 0x4000
    table_address = marker_address + 8
    root_addresses = tuple(0x4100 + 2 * index for index in range(len(roots)))
    rom = bytearray(0x8000)
    rom[0x4000:0x4008] = b"P2AUDIT1"
    for index, address in enumerate(root_addresses):
        start = table_address + 2 * index
        rom[start:start + 2] = address.to_bytes(2, "little")
    (root / "pokeyellow_phase2_audit.gbc").write_bytes(rom)
    symbols = [
        f"01:{marker_address:04x} Phase2AuditProvenance",
        f"01:{table_address:04x} Phase2AuditRoots",
        f"01:{table_address + 2 * len(roots):04x} Phase2AuditRootsEnd",
        *(f"01:{address:04x} {name}" for name, address in zip(roots, root_addresses)),
    ]
    (root / "pokeyellow_phase2_audit.sym").write_text(
        "\n".join(symbols) + "\n", encoding="utf-8"
    )
    (root / "pokeyellow_phase2_audit.map").write_text(
        "ROMX bank #1:\n"
        '\tSECTION: $4000-$4040 ($0041 bytes) ["Phase 2 Audit Provenance"]\n',
        encoding="utf-8",
    )
    for stem in ("pokeyellow", "pokeyellow_debug", "pokeyellow_vc"):
        (root / f"{stem}.gbc").write_bytes(b"normal-product")
        (root / f"{stem}.sym").write_text("00:0000 NormalSymbol\n", encoding="utf-8")
        (root / f"{stem}.map").write_text(
            'ROM0 bank #0:\n\tSECTION: $0000 ($0001 bytes) ["Normal"]\n',
            encoding="utf-8",
        )


def candidate(**changes: object) -> Phase2Candidate:
    values = {
        "wram_bank": 2,
        "wram_start": 0xD00D,
        "wram_end": 0xDFFF,
        "sram_bank": 3,
        "sram_start": 0xBEAF,
        "sram_end": 0xBFFF,
        "rom_bank": 0x3B,
        "rom_start": 0x4754,
        "rom_end": 0x7FFF,
        "stack_margin_bytes": MINIMUM_STACK_MARGIN,
        "ownership_adjacent": True,
    }
    values.update(changes)
    return Phase2Candidate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("wrong-row", "wrong row"),
        ("missing", "missing audit subject"),
        ("extra", "extra audit subject"),
        ("stale-product", "missing audit subject"),
        ("stale-hash", "stale audit source identity"),
        ("root-mismatch", "missing audit subject"),
    ],
)
def test_closed_audit_assignment_coverage_fails_closed(mutation, message) -> None:
    hashes = {
        "source_sha256": "1" * 64,
        "rom_sha256": "2" * 64,
        "sym_sha256": "3" * 64,
        "map_sha256": "4" * 64,
    }

    def row(identifier, digest, row_id, product="pokeyellow_phase2_audit"):
        return SimpleNamespace(
            id=identifier,
            product=product,
            row_id=row_id,
            subject=SimpleNamespace(sha256=digest),
            evidence=SimpleNamespace(**hashes),
        )

    rows = [row("AS-A", "a", "WR-P2-A"), row("AS-B", "b", "MU-P2-B")]
    if mutation == "wrong-row":
        rows[0].row_id = "WR-P2-WRONG"
    elif mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append(row("AS-C", "c", "WR-P2-A"))
    elif mutation == "stale-product":
        rows[0].product = "pokeyellow_debug"
    elif mutation == "stale-hash":
        rows[0].evidence.source_sha256 = "0" * 64
    else:
        rows[0].subject.sha256 = "root-mutated"

    authority = SimpleNamespace(
        for_product=lambda product: SimpleNamespace(
            rows=tuple(item for item in rows if item.product == product)
        )
    )
    with pytest.raises(ValueError, match=message):
        phase2_measurements._validate_audit_assignment_coverage(
            authority, {"a": "WR-P2-A", "b": "MU-P2-B"}, hashes
        )


def measurement(*, candidates: tuple[Phase2Candidate, ...] | None = None):
    return Phase2Measurement(
        {"pokeyellow.gbc": "1" * 64},
        DEFINITION,
        DEFINITION.classes,
        DEFINITION.descriptor_bytes,
        DEFINITION.scratch_bytes,
        candidates or (candidate(),),
    )


def test_current_measurement_selects_concrete_bounded_representation() -> None:
    decision = select_phase2_representation(measurement())
    assert decision.descriptor_bytes == 20
    assert decision.capacity == 8
    assert decision.scratch_bytes == 808
    assert decision.wram_bank == 2
    assert decision.wram_start == 0xD00D
    assert decision.rom_bank == 0x3B
    assert decision.debug_carrier_capacity >= DEFINITION.aggregate_high_water
    assert decision.ownership_state_bytes == PHASE1_STATE_BYTES
    assert decision.normal_rom_reachable is False
    assert decision.inventory_audit == {}


def test_selection_and_json_are_independent_of_candidate_order() -> None:
    adjacent = candidate()
    other = candidate(rom_bank=0x20, rom_start=0x5000, ownership_adjacent=False)
    first = select_phase2_representation(measurement(candidates=(other, adjacent)))
    second = select_phase2_representation(measurement(candidates=(adjacent, other)))
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.rom_bank == 0x3B


def test_required_work_defers_with_observable_retry() -> None:
    decision = select_phase2_representation(measurement())
    assert all(
        item.required_work_policy == "DEFERRED_CALLER_RETRY"
        for item in decision.request_classes
    )
    assert all(item.retry_observable for item in decision.request_classes)


def test_equivalent_work_coalesces_at_capacity() -> None:
    decision = select_phase2_representation(measurement())
    coalesced = {
        item.name
        for item in decision.request_classes
        if item.capacity_equivalence_policy == "COALESCED_FINAL_STATE"
    }
    assert "MAP_ROW_PAIRED" in coalesced
    assert "MAP_COLUMN_PAIRED" in coalesced
    assert "OAM_BATCH_AND_DMA" not in coalesced


def test_required_work_without_retry_observation_is_rejected() -> None:
    broken = replace(DEFINITION.classes[0], retry_observable=False)
    with pytest.raises(Phase2MeasurementError, match="lacks runtime-observable retry"):
        changed = replace(DEFINITION, classes=(broken, *DEFINITION.classes[1:]))
        select_phase2_representation(replace(measurement(), definition=changed, classes=changed.classes))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"overlaps": ("Existing",)}, "no non-overlapping"),
        ({"stack_margin_bytes": MINIMUM_STACK_MARGIN - 1}, "no non-overlapping"),
        ({"rom_bank": 0x2C}, "no non-overlapping"),
    ],
)
def test_overlap_margin_and_forbidden_bank_fail_closed(changes, message) -> None:
    with pytest.raises(Phase2MeasurementError, match=message):
        select_phase2_representation(measurement(candidates=(candidate(**changes),)))


def test_capacity_plus_one_does_not_fit_wram() -> None:
    required = DEFINITION.scratch_bytes + DEFINITION.descriptor_bytes * DEFINITION.aggregate_high_water
    exact = candidate(wram_end=0xD00D + required - 1)
    selected = select_phase2_representation(measurement(candidates=(exact,)))
    assert selected.wram_end == exact.wram_end
    too_small = replace(exact, wram_end=exact.wram_end - 1)
    with pytest.raises(Phase2MeasurementError, match="candidate fits measured"):
        select_phase2_representation(measurement(candidates=(too_small,)))


def test_too_small_adjacent_candidate_cannot_mask_a_fitting_candidate() -> None:
    too_small = candidate(wram_end=0xD010)
    fitting = candidate(rom_bank=0x20, rom_start=0x5000, ownership_adjacent=False)
    selected = select_phase2_representation(
        measurement(candidates=(too_small, fitting))
    )
    assert selected.rom_bank == 0x20


def test_debug_carrier_capacity_is_blocking() -> None:
    bytes_for_too_few = DEFINITION.debug_header_bytes + DEFINITION.debug_record_bytes * (DEFINITION.aggregate_high_water - 1)
    too_small = candidate(sram_end=0xBEAF + bytes_for_too_few - 1)
    with pytest.raises(Phase2MeasurementError, match="candidate fits measured"):
        select_phase2_representation(measurement(candidates=(too_small,)))


def test_descriptor_scratch_and_ownership_abi_are_exact() -> None:
    with pytest.raises(Phase2MeasurementError, match="descriptor byte cost"):
        select_phase2_representation(replace(measurement(), descriptor_bytes=DEFINITION.descriptor_bytes + 1))
    with pytest.raises(Phase2MeasurementError, match="scratch byte cost"):
        select_phase2_representation(replace(measurement(), scratch_bytes=DEFINITION.scratch_bytes + 1))
    with pytest.raises(Phase2MeasurementError, match="ownership ABI"):
        select_phase2_representation(
            replace(measurement(), ownership_state_bytes=PHASE1_STATE_BYTES + 1)
        )


def test_concrete_definition_mutations_change_measured_sizes_and_pressure(tmp_path) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    raw["descriptor"][0]["bytes"] += 1
    raw["scratch"][0]["bytes"] += 1
    raw["scenario"][1]["enqueue"].append({
        "class": "MAP_COLUMN_PAIRED",
        "destination": "column-8",
        "desired_state": "east-8",
    })
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    changed = load_definition(path)
    selected = select_phase2_representation(
        replace(
            measurement(), definition=changed, classes=changed.classes,
            descriptor_bytes=changed.descriptor_bytes, scratch_bytes=changed.scratch_bytes,
        )
    )
    assert changed.descriptor_bytes == DEFINITION.descriptor_bytes + 1
    assert changed.scratch_bytes == DEFINITION.scratch_bytes + 1
    assert selected.capacity == DEFINITION.aggregate_high_water + 1


def test_pressure_replay_coalesces_equivalent_destination_but_counts_resident_work(tmp_path) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    horizontal = raw["scenario"][1]["enqueue"]
    for index, request in enumerate(horizontal):
        request["destination"] = "same-column"
        request["desired_state"] = "same-final-state"
    path = tmp_path / "coalesced.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    changed = load_definition(path)
    assert changed.class_high_water["MAP_COLUMN_PAIRED"] == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("owner", "RENDERER_YELLOW"),
        ("generation", "generation-distinct"),
        ("visible_boundary", "DISTINCT_VISIBLE_BOUNDARY"),
    ],
)
def test_same_destination_is_not_equivalent_across_identity_boundaries(
    tmp_path, field, replacement
) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    step = raw["scenario"][1]
    for request in step["enqueue"]:
        request["destination"] = "same-column"
        request["desired_state"] = "same-final-state"
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_definition(control_path).class_high_water["MAP_COLUMN_PAIRED"] == 1
    split = json.loads(json.dumps(step))
    split["identity"][field] = replacement
    split["enqueue"] = split["enqueue"][4:]
    split.pop("drain", None)
    step["enqueue"] = step["enqueue"][:4]
    raw["scenario"].insert(2, split)
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_definition(changed_path).class_high_water["MAP_COLUMN_PAIRED"] == 2


def test_same_destination_with_distinct_desired_state_is_not_equivalent(tmp_path) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    horizontal = raw["scenario"][1]["enqueue"]
    for index, request in enumerate(horizontal):
        request["destination"] = "same-column"
        request["desired_state"] = f"revision-{index}"
    path = tmp_path / "distinct-state.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_definition(path).class_high_water["MAP_COLUMN_PAIRED"] == 8


@pytest.mark.parametrize("mutation", ["omit", "unknown"])
def test_definition_identity_fields_fail_closed(tmp_path, mutation) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    identity = raw["scenario"][0]["identity"]
    if mutation == "omit":
        identity.pop("owner")
    else:
        identity["surprise"] = "not-authoritative"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Phase2MeasurementError, match="identity requires"):
        load_definition(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["request_classes"][0].__setitem__("required_work", "true"), "expected boolean"),
        (lambda raw: raw["descriptor"][0].__setitem__("bytes", True), "positive integer"),
        (lambda raw: raw["scenario"][0].__setitem__("drain", "false"), "expected boolean"),
        (lambda raw: raw["scenario"][0]["identity"].__setitem__("owner", 7), "non-empty string"),
        (lambda raw: raw["scenario"][0]["identity"].__setitem__("resources", ["UNKNOWN"]), "unknown resources"),
        (lambda raw: raw["scenario"][1]["identity"].__setitem__("resources", ["BG_MAP"]), "resources are incompatible"),
    ],
)
def test_definition_rejects_wrong_scalar_types_and_resource_contracts(
    tmp_path, mutate, message
) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Phase2MeasurementError, match=message):
        load_definition(path)


def test_definition_rejects_duplicate_json_keys(tmp_path) -> None:
    text = (ROOT / DEFINITION_PATH).read_text(encoding="utf-8")
    path = tmp_path / "duplicate.json"
    path.write_text(text.replace('"schema":', '"schema": "duplicate", "schema":', 1), encoding="utf-8")
    with pytest.raises(Phase2MeasurementError, match="duplicate JSON key"):
        load_definition(path)


@pytest.mark.parametrize("mode", ["delete", "unreview", "substitute"])
def test_standalone_audit_enforces_exact_phase2_row_ids(monkeypatch, mode) -> None:
    original = WriterInventory.load(ROOT / "specs/full-colors/inventory/writers.json")
    raw = original.to_dict()
    planned_index = next(
        index for index, row in enumerate(raw["rows"])
        if row["id"] in phase2_measurements.PHASE2_PLANNED_ROW_IDS
    )
    if mode == "delete":
        raw["rows"].pop(planned_index)
    elif mode == "unreview":
        raw["rows"][planned_index]["evidence"]["reviewed"] = False
    else:
        raw["rows"][planned_index]["id"] = "WR-P2-SUBSTITUTED"
        raw["rows"].sort(key=lambda row: row["id"])
    changed = WriterInventory.from_dict(raw)
    monkeypatch.setattr(phase2_measurements.WriterInventory, "load", lambda path: changed)
    with pytest.raises(
        Phase2MeasurementError,
        match="exact closed set|transition all 18 rows",
    ):
        audit_phase2_inventory(ROOT)


@pytest.mark.parametrize("kind", ["source", "rom"])
def test_same_coordinate_semantic_drift_fails_canonical_subject_audit(monkeypatch, kind) -> None:
    if kind == "source":
        report = phase2_measurements.discover_phase2_sources(ROOT)
        index = next(
            index for index, finding in enumerate(report.findings)
            if finding.mechanism == "configured-root" and finding.symbol == "UpdateMovingBgTiles"
        )
        findings = list(report.findings)
        findings[index] = replace(findings[index], resource="SEMANTIC_DRIFT")
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_sources",
            lambda root: replace(report, findings=tuple(findings)),
        )
    else:
        report = phase2_measurements.discover_phase2_rom(ROOT)
        index = next(
            index for index, finding in enumerate(report.findings)
            if finding.mechanism == "root-entry" and finding.root == "UpdateMovingBgTiles"
        )
        findings = list(report.findings)
        findings[index] = replace(findings[index], bytes="00")
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_rom",
            lambda root, guarded=True: replace(report, findings=tuple(findings)),
        )
    with pytest.raises(Phase2MeasurementError, match="subjects="):
        audit_phase2_inventory(ROOT)


@pytest.mark.parametrize("kind", ["source", "rom", "candidate"])
@pytest.mark.parametrize("mutation", ["omit", "alter"])
def test_descendant_subject_closure_is_mutation_sensitive(
    monkeypatch, kind, mutation
) -> None:
    if kind == "source":
        report = phase2_measurements.discover_phase2_sources(ROOT)
        index = next(
            index for index, finding in enumerate(report.findings)
            if finding.symbol.startswith("LoadMapData.")
        )
        findings = list(report.findings)
        if mutation == "omit":
            findings.pop(index)
        else:
            findings[index] = replace(findings[index], destination="ALTERED_DESCENDANT")
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_sources",
            lambda root: replace(report, findings=tuple(findings)),
        )
    else:
        report = phase2_measurements.discover_phase2_rom(ROOT)
        field = "candidate_findings" if kind == "candidate" else "findings"
        findings = list(getattr(report, field))
        if kind == "candidate":
            scoped_sites = {
                finding.site_key
                for finding in report.findings
                if finding.root in phase2_measurements._phase2_roots()
            }
            index = next(
                index for index, finding in enumerate(findings)
                if finding.site_key in scoped_sites
            )
        else:
            index = next(
                index for index, finding in enumerate(findings)
                if finding.root == "LoadMapData" and finding.mechanism != "root-entry"
            )
        if mutation == "omit":
            findings.pop(index)
        else:
            findings[index] = replace(findings[index], bytes="00")
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_rom",
            lambda root, guarded=True: replace(report, **{field: tuple(findings)}),
        )
    with pytest.raises(Phase2MeasurementError, match="subjects="):
        audit_phase2_inventory(ROOT)


def test_undispositioned_source_diagnostic_is_blocking(monkeypatch) -> None:
    report = phase2_measurements.discover_phase2_sources(ROOT)
    monkeypatch.setattr(
        phase2_measurements,
        "discover_phase2_sources",
        lambda root: replace(
            report,
            errors=(*report.errors, "home/pokemon.asm:194:DisplayPartyMenu: injected"),
        ),
    )
    with pytest.raises(Phase2MeasurementError, match="diagnostic dispositions changed"):
        audit_phase2_inventory(ROOT)


@pytest.mark.parametrize(
    "kind", ["source", "rom", "candidate", "diagnostic", "unresolved"]
)
def test_duplicate_discovery_items_fail_before_projection(monkeypatch, kind) -> None:
    if kind in {"source", "diagnostic"}:
        report = phase2_measurements.discover_phase2_sources(ROOT)
        field = "findings" if kind == "source" else "errors"
        values = getattr(report, field)
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_sources",
            lambda root: replace(report, **{field: (*values, values[0])}),
        )
    else:
        report = phase2_measurements.discover_phase2_rom(ROOT)
        field = {
            "rom": "findings",
            "candidate": "candidate_findings",
            "unresolved": "unresolved_destinations",
        }[kind]
        values = getattr(report, field)
        monkeypatch.setattr(
            phase2_measurements,
            "discover_phase2_rom",
            lambda root, guarded=True: replace(report, **{field: (*values, values[0])}),
        )
    with pytest.raises(Phase2MeasurementError, match="duplicate .* before projection"):
        audit_phase2_inventory(ROOT)


def test_empty_exact_closed_row_rom_mapping_is_blocking(tmp_path, monkeypatch) -> None:
    raw = json.loads(
        (ROOT / phase2_measurements.PLANNED_SUBJECTS_PATH).read_text(encoding="utf-8")
    )
    row_id = "WR-P2-YELLOW-OVERLAY-TRANSFER"
    for kind in ("rom_subjects", "rom_candidate_subjects"):
        removed = len(raw[kind][row_id])
        raw[kind][row_id] = []
        raw["authority_counts"][kind]["by_row"][row_id] = 0
        raw["authority_counts"][kind]["total"] -= removed
    authority = tmp_path / "empty-planned-row.json"
    authority.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(phase2_measurements, "PLANNED_SUBJECTS_PATH", authority)
    with pytest.raises(Phase2MeasurementError, match="ROM subjects"):
        audit_phase2_inventory(ROOT)


def test_closed_audit_requires_concrete_palette_and_overlay_subjects() -> None:
    subjects = {
        row_id: {"subject"} for row_id in phase2_measurements.PHASE2_PLANNED_ROW_IDS
    }
    subjects["WR-P2-YELLOW-BG-PALETTE"] = set()
    subjects["WR-P2-YELLOW-OVERLAY-TRANSFER"] = set()
    errors = phase2_measurements._closed_concrete_subject_errors(subjects)
    assert errors == (
        "WR-P2-YELLOW-BG-PALETTE: closed audit requires a discoverable concrete source subject",
        "WR-P2-YELLOW-OVERLAY-TRANSFER: closed audit requires a discoverable concrete source subject",
    )


def test_closed_party_directions_use_inventory_vocabulary() -> None:
    report = phase2_measurements.discover_phase2_sources(ROOT)
    normalized = phase2_measurements._normalize_closed_scene_directions(report)
    directions = {
        (finding.symbol, finding.destination): finding.direction
        for finding in normalized.findings
        if (finding.symbol, finding.destination)
        in phase2_measurements._CLOSED_SCENE_DIRECTIONS
    }
    assert directions == phase2_measurements._CLOSED_SCENE_DIRECTIONS


@pytest.mark.parametrize("kind", ["destination", "control"])
def test_unresolved_rom_disposition_is_mutation_sensitive(monkeypatch, kind) -> None:
    report = phase2_measurements.discover_phase2_rom(ROOT)
    field = "unresolved_destinations" if kind == "destination" else "unresolved_control_flow"
    values = list(getattr(report, field))
    index = next(
        index for index, value in enumerate(values)
        if value.split(":", 1)[0] in phase2_measurements._phase2_roots()
    )
    values[index] += " altered"
    monkeypatch.setattr(
        phase2_measurements,
        "discover_phase2_rom",
        lambda root, guarded=True: replace(report, **{field: tuple(values)}),
    )
    with pytest.raises(Phase2MeasurementError, match="unresolved dispositions"):
        audit_phase2_inventory(ROOT)


@pytest.mark.parametrize("mutation", ["schema", "traversal"])
def test_standalone_audit_reuses_strict_v2_transition_validation(
    tmp_path, monkeypatch, mutation
) -> None:
    raw = json.loads((ROOT / phase2_measurements.SOURCE_TRANSITION_PATH).read_text())
    if mutation == "schema":
        raw["schema"] = "full-color-phase1-audit-source-transition-v1"
    else:
        path, binding = next(iter(raw["audit_only_paths"].items()))
        del raw["audit_only_paths"][path]
        raw["audit_only_paths"]["../" + path] = binding
    transition = tmp_path / "transition.json"
    transition.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(baseline_inventory, "SOURCE_TRANSITION_PATH", transition)
    with pytest.raises(
        Phase2MeasurementError,
        match="standalone hostile authority",
    ):
        audit_phase2_inventory(ROOT)


@pytest.mark.parametrize(
    "mutation",
    ["machine-site", "bytes", "root", "resources", "commit", "reviewed", "hash"],
)
def test_standalone_audit_reuses_strict_closed_row_validation(
    monkeypatch, mutation
) -> None:
    original = WriterInventory.load(ROOT / "specs/full-colors/inventory/writers.json")
    raw = original.to_dict()
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
    elif mutation == "commit":
        row["commit_unit"] = "BYTE"
    elif mutation == "reviewed":
        row["evidence"]["reviewed"] = False
    else:
        row["evidence"]["source_sha256"] = "0" * 64
    changed = WriterInventory.from_dict(raw)
    monkeypatch.setattr(phase2_measurements.WriterInventory, "load", lambda path: changed)
    with pytest.raises(
        Phase2MeasurementError,
        match="standalone hostile authority|hostile inventory audit lacks exact evidence",
    ):
        audit_phase2_inventory(ROOT)


def test_closed_authority_rejects_reintroduced_planned_only_disposition(
    tmp_path, monkeypatch
) -> None:
    raw = json.loads(
        (ROOT / phase2_measurements.PLANNED_SUBJECTS_PATH).read_text(encoding="utf-8")
    )
    raw["planned_only_dispositions"]["WR-P2-YELLOW-BG-PALETTE"] = {}
    authority = tmp_path / "planned-subjects.json"
    authority.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(phase2_measurements, "PLANNED_SUBJECTS_PATH", authority)
    with pytest.raises(Phase2MeasurementError, match="must be empty after audit closure"):
        audit_phase2_inventory(ROOT)


def test_pressure_replay_equivalence_policy_mutation_changes_residency(tmp_path) -> None:
    raw = json.loads((ROOT / DEFINITION_PATH).read_text(encoding="utf-8"))
    horizontal = raw["scenario"][1]["enqueue"]
    for request in horizontal:
        request["destination"] = "same-column"
        request["desired_state"] = "same-final-state"
    path = tmp_path / "coalesced.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    coalesced = load_definition(path)
    column = next(
        row for row in raw["request_classes"] if row["name"] == "MAP_COLUMN_PAIRED"
    )
    column["equivalent_at_capacity"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    independent = load_definition(path)
    assert coalesced.class_high_water["MAP_COLUMN_PAIRED"] == 1
    assert independent.class_high_water["MAP_COLUMN_PAIRED"] == 8


def test_guarded_source_discovery_requires_compiled_provenance(tmp_path) -> None:
    with pytest.raises(Phase2MeasurementError, match="missing compile-time PHASE2_AUDIT"):
        discover_phase2_sources(tmp_path)


@pytest.mark.parametrize("duplicate", [False, True])
def test_audit_root_table_rejects_wrong_or_duplicate_compiled_pointer(tmp_path, duplicate) -> None:
    audit_product_fixture(tmp_path)
    from tools.rom_tests.full_color.rom_discovery import load_sym, normalize_rom_offset
    symbols = load_sym(tmp_path / "pokeyellow_phase2_audit.sym")
    start = symbols.by_name["Phase2AuditRoots"]
    offset = normalize_rom_offset(start.bank, start.address)
    rom_path = tmp_path / "pokeyellow_phase2_audit.gbc"
    rom = bytearray(rom_path.read_bytes())
    replacement = symbols.by_name[_phase2_roots()[0]].address if duplicate else 0
    rom[offset + 2 : offset + 4] = replacement.to_bytes(2, "little")
    rom_path.write_bytes(rom)
    with pytest.raises(Phase2MeasurementError, match="duplicate pointers|does not match"):
        _verify_audit_product(tmp_path)


def test_committed_record_verifier_requires_byte_identical_evidence(
    tmp_path, monkeypatch
) -> None:
    decision = select_phase2_representation(measurement())
    monkeypatch.setattr(phase2_measurements, "generate", lambda root: decision)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(decision.to_json(), encoding="utf-8")
    assert verify_evidence(tmp_path, evidence) == decision
    evidence.write_text(decision.to_json() + " ", encoding="utf-8")
    with pytest.raises(Phase2MeasurementError, match="stale or edited"):
        verify_evidence(tmp_path, evidence)


@pytest.mark.parametrize("stem", ["pokeyellow", "pokeyellow_debug", "pokeyellow_vc"])
@pytest.mark.parametrize("suffix", [".gbc", ".map", ".sym"])
def test_normal_link_products_expose_no_phase2_audit_entries(
    tmp_path, stem, suffix
) -> None:
    audit_product_fixture(tmp_path)
    _verify_audit_product(tmp_path)
    path = tmp_path / f"{stem}{suffix}"
    path.write_bytes(path.read_bytes() + b"Phase2AuditForbidden")
    with pytest.raises(Phase2MeasurementError, match="forbidden Phase 2"):
        _verify_audit_product(tmp_path)
