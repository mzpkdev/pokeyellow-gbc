"""Exact reviewed discovery-to-inventory assignment contracts."""

from copy import deepcopy

import pytest

from tools.rom_tests.full_color.discovery_assignment import (
    ASSIGNMENT_SCHEMA,
    BASELINE_PRODUCT,
    PHASE2_AUDIT_PRODUCT,
    AssignmentMatcher,
    DiscoveryAssignmentAuthority,
    DiscoveryAssignmentValidationError,
    DuplicateDiscoveryAssignmentConsumptionError,
    StaleDiscoveryAssignmentError,
)
from tools.rom_tests.full_color.discovery_review import (
    rom_finding_subject,
    source_finding_subject,
)
from tools.rom_tests.full_color.rom_discovery import RomFinding
from tools.rom_tests.full_color.source_discovery import SourceFinding

HASHES = {
    "source_sha256": "0" * 64,
    "rom_sha256": "1" * 64,
    "sym_sha256": "2" * 64,
    "map_sha256": "3" * 64,
}


def source(symbol: str) -> SourceFinding:
    return SourceFinding(
        "control_flow",
        "engine/test.asm",
        {"Writer": 10, "EnterMap": 20, "MutateMap": 30}[symbol],
        symbol,
        "call",
        "UnclassifiedTarget",
        "CONTROL_FLOW",
        evidence_sha256="4" * 64,
        resolved=False,
    )


def rom() -> RomFinding:
    return RomFinding(
        2,
        0x4000,
        0x8000,
        "cd0041",
        "call",
        0x4100,
        0x4100,
        "OAM_DMA_CONTROL",
        None,
        None,
        "Reset",
        ("Reset", "02:4000"),
        resolved=True,
        category="control_flow",
        control_flow_kind="call",
    )


def evidence(*, reviewed: bool = True) -> dict[str, object]:
    return {**HASHES, "reviewer": "baseline-reviewer", "reviewed": reviewed}


def row(
    assignment_id: str,
    row_id: str,
    finding: SourceFinding | RomFinding,
    *,
    category: str,
    scene: dict[str, object] | None = None,
    mutation: dict[str, object] | None = None,
    product: str = BASELINE_PRODUCT,
) -> dict[str, object]:
    subject = (
        source_finding_subject(finding)
        if isinstance(finding, SourceFinding)
        else rom_finding_subject(finding)
    )
    return {
        "id": assignment_id,
        "category": category,
        "row_id": row_id,
        "subject": subject.to_dict(),
        "scene": scene,
        "mutation": mutation,
        "evidence": evidence(),
        "product": product,
    }


def raw_authority() -> dict[str, object]:
    return {
        "schema": ASSIGNMENT_SCHEMA,
        "rows": [
            row(
                "AS-MUTATION",
                "MU-MAP-RECT",
                source("MutateMap"),
                category="mutation",
                mutation={"destination": "BG_MAP_9800"},
            ),
            row("AS-ROM", "WR-DMA", rom(), category="writer"),
            row(
                "AS-SCENE",
                "SC-ENTER-MAP",
                source("EnterMap"),
                category="scene",
                scene={
                    "row_kind": "DIRECTED_EDGE",
                    "direction": "YELLOW_TO_MAP",
                    "destination_path": "engine/map.asm",
                    "destination_line": 42,
                    "destination_symbol": "MapInit",
                },
            ),
            row("AS-WRITER", "WR-VBK", source("Writer"), category="writer"),
        ],
    }


def matcher(authority: DiscoveryAssignmentAuthority) -> AssignmentMatcher:
    return authority.matcher(**HASHES, product=BASELINE_PRODUCT)


def test_canonical_round_trip_and_exact_projection_for_all_categories() -> None:
    authority = DiscoveryAssignmentAuthority.from_dict(raw_authority())
    assert DiscoveryAssignmentAuthority.from_json(authority.to_json()) == authority
    assert authority.to_json().endswith("\n")
    assert len(authority.sha256) == 64

    review = matcher(authority)
    mutation = review.project_source_finding(source("MutateMap"))
    machine_writer = review.project_rom_finding(rom())
    scene = review.project_source_finding(source("EnterMap"))
    writer = review.project_source_finding(source("Writer"))

    assert (writer.category, machine_writer.category) == ("writer", "writer")
    assert mutation.category == "mutation"
    assert mutation.destination == "BG_MAP_9800"
    assert mutation.resolved
    assert authority.rows[0].mutation is not None
    assert (
        scene.category,
        scene.row_kind,
        scene.direction,
        scene.destination_path,
        scene.destination_line,
        scene.destination,
    ) == (
        "scene",
        "DIRECTED_EDGE",
        "YELLOW_TO_MAP",
        "engine/map.asm",
        42,
        "MapInit",
    )
    assert scene.resolved
    assert writer.resolved
    assert review.consumed_row_ids == (
        "MU-MAP-RECT",
        "SC-ENTER-MAP",
        "WR-DMA",
        "WR-VBK",
    )
    review.assert_all_consumed()


def test_stale_baseline_hashes_fail_before_matching() -> None:
    authority = DiscoveryAssignmentAuthority.from_dict(raw_authority())
    with pytest.raises(StaleDiscoveryAssignmentError, match="AS-MUTATION.*AS-WRITER"):
        authority.matcher(
            **{**HASHES, "rom_sha256": "f" * 64}, product=BASELINE_PRODUCT
        )


def test_product_scope_selects_explicit_baseline_and_audit_rows() -> None:
    raw = raw_authority()
    audit = deepcopy(raw["rows"][0])
    audit["id"] = "AS-PHASE2-AUDIT"
    audit["product"] = PHASE2_AUDIT_PRODUCT
    audit["subject"] = source_finding_subject(
        SourceFinding(**{**source("MutateMap").to_dict(), "line": 31, "aliases": ()})
    ).to_dict()
    audit["evidence"].update(
        source_sha256="a" * 64,
        rom_sha256="b" * 64,
        sym_sha256="c" * 64,
        map_sha256="d" * 64,
    )
    raw["rows"].append(audit)
    raw["rows"].sort(key=lambda item: item["id"])

    authority = DiscoveryAssignmentAuthority.from_dict(raw)
    assert len(authority.for_product(BASELINE_PRODUCT).rows) == len(raw["rows"]) - 1
    assert authority.for_product(PHASE2_AUDIT_PRODUCT).rows[0].product == (
        PHASE2_AUDIT_PRODUCT
    )
    assert all(
        row.product == BASELINE_PRODUCT
        for row in authority.for_product(BASELINE_PRODUCT).rows
    )
    assert '"product":"pokeyellow_phase2_audit"' in authority.to_json()


@pytest.mark.parametrize("mutation", ["unknown-product", "mixed-product-hashes"])
def test_product_scope_schema_and_hash_tuple_fail_closed(mutation: str) -> None:
    raw = raw_authority()
    if mutation == "unknown-product":
        raw["rows"][0]["product"] = "whatever-built-last"
        message = "unknown link product"
    else:
        raw["rows"][0]["evidence"]["rom_sha256"] = "f" * 64
        message = "mixed product hash tuple"
    with pytest.raises(DiscoveryAssignmentValidationError, match=message):
        DiscoveryAssignmentAuthority.from_dict(raw)


def test_product_is_required_for_every_assignment_row() -> None:
    raw = raw_authority()
    del raw["rows"][0]["product"]
    with pytest.raises(
        DiscoveryAssignmentValidationError, match="missing fields: product"
    ):
        DiscoveryAssignmentAuthority.from_dict(raw)


def test_wrong_audit_product_identity_does_not_match_normal_partition() -> None:
    raw = raw_authority()
    for item in raw["rows"]:
        item["product"] = PHASE2_AUDIT_PRODUCT
    authority = DiscoveryAssignmentAuthority.from_dict(raw)
    review = authority.matcher(**HASHES, product=BASELINE_PRODUCT)
    with pytest.raises(StaleDiscoveryAssignmentError, match="unreviewed discovery"):
        review.project_source_finding(source("Writer"))


def test_duplicate_consumption_and_unreviewed_subject_fail_closed() -> None:
    authority = DiscoveryAssignmentAuthority.from_dict(raw_authority())
    review = matcher(authority)
    review.project_source_finding(source("Writer"))
    with pytest.raises(
        DuplicateDiscoveryAssignmentConsumptionError, match="more than once"
    ):
        review.project_source_finding(source("Writer"))

    changed = SourceFinding(**{**source("Writer").to_dict(), "line": 11, "aliases": ()})
    with pytest.raises(StaleDiscoveryAssignmentError, match="unreviewed discovery"):
        matcher(authority).project_source_finding(changed)


def test_unreviewed_and_stale_subject_rows_are_rejected() -> None:
    raw = raw_authority()
    raw["rows"][0]["evidence"]["reviewed"] = False
    with pytest.raises(DiscoveryAssignmentValidationError, match="must be reviewed"):
        DiscoveryAssignmentAuthority.from_dict(raw)

    stale = raw_authority()
    stale["rows"][0]["subject"]["sha256"] = "f" * 64
    with pytest.raises(DiscoveryAssignmentValidationError, match="stale or invalid"):
        DiscoveryAssignmentAuthority.from_dict(stale)


def test_unused_assignments_and_duplicate_fingerprints_fail_closed() -> None:
    authority = DiscoveryAssignmentAuthority.from_dict(raw_authority())
    review = matcher(authority)
    review.project_source_finding(source("Writer"))
    with pytest.raises(StaleDiscoveryAssignmentError, match="AS-MUTATION"):
        review.assert_all_consumed()

    raw = raw_authority()
    duplicate = deepcopy(raw["rows"][0])
    duplicate["id"] = "AS-MUTATION-TWO"
    raw["rows"].insert(1, duplicate)
    with pytest.raises(DiscoveryAssignmentValidationError, match="duplicate subject"):
        DiscoveryAssignmentAuthority.from_dict(raw)


@pytest.mark.parametrize(
    ("category", "row_id"),
    (("writer", "SC-WRONG"), ("scene", "MU-WRONG"), ("mutation", "WR-WRONG")),
)
def test_category_and_inventory_id_prefix_must_agree(
    category: str, row_id: str
) -> None:
    raw = raw_authority()
    raw["rows"][0].update(category=category, row_id=row_id)
    with pytest.raises(DiscoveryAssignmentValidationError, match="requires"):
        DiscoveryAssignmentAuthority.from_dict(raw)


def test_source_scene_assignment_requires_explicit_shape() -> None:
    raw = raw_authority()
    raw["rows"][2]["scene"] = None

    with pytest.raises(
        DiscoveryAssignmentValidationError,
        match="source scene assignments require explicit enrichment",
    ):
        DiscoveryAssignmentAuthority.from_dict(raw)
