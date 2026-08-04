"""Fail-closed checks for the source-transition evidence producer."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest

from tools.rom_tests.full_color import audit_evidence_identities, source_transition
from tools.rom_tests.full_color.discovery_assignment import (
    DiscoveryAssignmentAuthority,
    NORMAL_DEBUG_PRODUCT,
)
from tools.rom_tests.full_color.discovery_review import source_finding_subject
from tools.rom_tests.full_color.rom_discovery import load_map
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


def test_source_transition_generation_is_idempotent_and_preserves_authority() -> None:
    first = source_transition.generate_json(REPOSITORY_ROOT)
    second = source_transition.generate_json(REPOSITORY_ROOT)
    assert second == first
    generated = json.loads(first)
    authority = json.loads(
        (REPOSITORY_ROOT / source_transition.TRANSITION_PATH).read_text(
            encoding="utf-8"
        )
    )
    for name in (
        "reviewed_source_sha256",
        "baseline_manifest_sha256",
    ):
        assert generated[name] == authority[name]
    assert {
        path: binding["reviewed_sha256"]
        for path, binding in generated["audit_only_paths"].items()
    } == {
        path: binding["reviewed_sha256"]
        for path, binding in authority["audit_only_paths"].items()
    }
    assert len(set(generated["subject_rebindings"].values())) == len(
        generated["subject_rebindings"]
    )
    assert len(set(generated["rom_subject_rebindings"].values())) == len(
        generated["rom_subject_rebindings"]
    )


@pytest.mark.parametrize("mutation", ("missing", "ambiguous", "semantic"))
def test_source_transition_rejects_non_unique_or_changed_subjects(mutation: str) -> None:
    report = source_transition.baseline.discover_baseline_sources(REPOSITORY_ROOT)
    assignments = DiscoveryAssignmentAuthority.load(
        REPOSITORY_ROOT / source_transition.ASSIGNMENTS_PATH
    ).for_product(NORMAL_DEBUG_PRODUCT)
    row = next(
        row
        for row in assignments.rows
        if row.subject.kind.value == "SOURCE_FINDING"
    )
    matching = next(
        finding
        for finding in report.findings
        if source_finding_subject(source_transition._reviewed_source_location(finding, row)).sha256
        == row.subject.sha256
    )
    findings = [matching]
    if mutation == "missing":
        findings = []
    elif mutation == "ambiguous":
        findings.append(matching)
    else:
        findings[0] = replace(matching, resource="SEMANTIC_CHANGE")
    with pytest.raises(source_transition.SourceTransitionError, match="semantic matches"):
        source_transition._unique_rebindings(
            (row,),
            findings,
            subject=source_finding_subject,
            rebound=source_transition._reviewed_source_location,
            kind="source",
        )


def test_source_transition_prefers_the_reviewed_source_root_before_proximity() -> None:
    report = source_transition.baseline.discover_baseline_sources(REPOSITORY_ROOT)
    assignments = DiscoveryAssignmentAuthority.load(
        REPOSITORY_ROOT / source_transition.ASSIGNMENTS_PATH
    ).for_product(NORMAL_DEBUG_PRODUCT)
    row = next(
        row
        for row in assignments.rows
        if row.subject.metadata.get("symbol") == "CopyMapViewToVRAM2"
    )
    semantic_matches = [
        finding
        for finding in report.findings
        if source_finding_subject(
            source_transition._reviewed_source_location(finding, row)
        ).sha256
        == row.subject.sha256
    ]
    expected = next(
        finding
        for finding in semantic_matches
        if finding.symbol.startswith("CopyMapViewToVRAM2.")
    )
    closer_wrong_root = min(
        (
            finding
            for finding in semantic_matches
            if not finding.symbol.startswith("CopyMapViewToVRAM2.")
        ),
        key=lambda finding: abs(finding.line - row.subject.metadata["line"]),
    )
    assert abs(closer_wrong_root.line - row.subject.metadata["line"]) < abs(
        expected.line - row.subject.metadata["line"]
    )

    rebound = source_transition._unique_rebindings(
        (row,),
        (closer_wrong_root, expected),
        subject=source_finding_subject,
        rebound=source_transition._reviewed_source_location,
        kind="source",
    )

    assert rebound[row.subject.sha256] == source_finding_subject(expected).sha256


def test_audit_identity_rebinding_changes_evidence_but_not_subjects(
    tmp_path, monkeypatch
) -> None:
    inventory = tmp_path / "specs/full-colors/inventory"
    inventory.mkdir(parents=True)
    originals = {}
    for relative in audit_evidence_identities.DOCUMENTS:
        source = REPOSITORY_ROOT / relative
        target = tmp_path / relative
        target.write_bytes(source.read_bytes())
        originals[relative] = json.loads(source.read_text(encoding="utf-8"))
    transition = tmp_path / audit_evidence_identities.TRANSITION_PATH
    transition.parent.mkdir(parents=True)
    transition.write_text(
        json.dumps(
            {
                "schema": source_transition.SCHEMA,
                "reviewed_source_sha256": (
                    audit_evidence_identities.REVIEWED_SOURCE_SHA256
                ),
                "audit_source_sha256": "f" * 64,
                "baseline_manifest_sha256": (
                    audit_evidence_identities.BASELINE_MANIFEST_SHA256
                ),
                "audit_only_paths": {},
                "subject_rebindings": {},
                "rom_subject_rebindings": {},
            }
        )
    )
    for relative in audit_evidence_identities.NORMAL_DEBUG_ARTIFACTS.values():
        shutil.copyfile(REPOSITORY_ROOT / relative, tmp_path / relative)
    monkeypatch.setattr(
        audit_evidence_identities,
        "discover_baseline_sources",
        lambda root: SimpleNamespace(source_sha256="f" * 64),
    )
    monkeypatch.setattr(
        source_transition,
        "generate",
        lambda root, *, authority_path=None: json.loads(
            authority_path.read_text(encoding="utf-8")
        ),
    )
    audit_evidence_identities.update(tmp_path)
    normal_hashes = audit_evidence_identities._normal_debug_hashes(
        tmp_path, "f" * 64
    )
    for relative, before in originals.items():
        after = json.loads((tmp_path / relative).read_text(encoding="utf-8"))
        before_subjects = [row.get("subject") for row in before["rows"]]
        after_subjects = [row.get("subject") for row in after["rows"]]
        assert after_subjects == before_subjects
        for row in after["rows"]:
            evidence = row.get("evidence", {})
            product = row.get("product", NORMAL_DEBUG_PRODUCT)
            if relative.name == "assignments.json" and product == NORMAL_DEBUG_PRODUCT:
                assert evidence == {
                    "source_sha256": "f" * 64,
                    **{
                        name: (
                            load_map(tmp_path / path).artifact_sha256
                            if name == "map_sha256"
                            else hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()
                        )
                        for name, path in audit_evidence_identities.NORMAL_DEBUG_ARTIFACTS.items()
                    },
                    "reviewer": row["evidence"]["reviewer"],
                    "reviewed": True,
                }
            if row.get("id") in audit_evidence_identities.NORMAL_DEBUG_INVENTORY_IDS.get(
                relative.name, frozenset()
            ):
                assert evidence == {
                    **normal_hashes,
                    "reviewer": row["evidence"]["reviewer"],
                    "reviewed": True,
                }
            if evidence.get("rom_sha256") == audit_evidence_identities.AUDIT_ROM_SHA256:
                assert evidence["source_sha256"] == "f" * 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("schema", "source-transition authority is malformed"),
        (
            "digest",
            "source-transition audit identity does not match current baseline discovery",
        ),
    ),
)
def test_audit_identity_rebinding_rejects_untrusted_transition(
    tmp_path, monkeypatch, mutation: str, message: str
) -> None:
    transition = tmp_path / audit_evidence_identities.TRANSITION_PATH
    transition.parent.mkdir(parents=True)
    authority = {
        "schema": source_transition.SCHEMA,
        "reviewed_source_sha256": audit_evidence_identities.REVIEWED_SOURCE_SHA256,
        "audit_source_sha256": "f" * 64,
        "baseline_manifest_sha256": (
            audit_evidence_identities.BASELINE_MANIFEST_SHA256
        ),
        "audit_only_paths": {},
        "subject_rebindings": {},
        "rom_subject_rebindings": {},
    }
    if mutation == "schema":
        authority["schema"] = "fabricated-source-transition-schema"
    transition.write_text(json.dumps(authority), encoding="utf-8")
    monkeypatch.setattr(
        audit_evidence_identities,
        "discover_baseline_sources",
        lambda root: SimpleNamespace(source_sha256="e" * 64),
    )

    with pytest.raises(
        audit_evidence_identities.AuditEvidenceIdentityError, match=message
    ):
        audit_evidence_identities.update(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    (
        "reviewed_source_sha256",
        "baseline_manifest_sha256",
        "audit_only_paths",
        "subject_rebindings",
        "rom_subject_rebindings",
    ),
)
def test_audit_identity_rebinding_rejects_fabricated_nondigest_authority(
    tmp_path, monkeypatch, mutation: str
) -> None:
    transition = tmp_path / audit_evidence_identities.TRANSITION_PATH
    transition.parent.mkdir(parents=True)
    canonical = {
        "schema": source_transition.SCHEMA,
        "reviewed_source_sha256": audit_evidence_identities.REVIEWED_SOURCE_SHA256,
        "audit_source_sha256": "f" * 64,
        "baseline_manifest_sha256": (
            audit_evidence_identities.BASELINE_MANIFEST_SHA256
        ),
        "audit_only_paths": {},
        "subject_rebindings": {},
        "rom_subject_rebindings": {},
    }
    authority = json.loads(json.dumps(canonical))
    if mutation in {"reviewed_source_sha256", "baseline_manifest_sha256"}:
        authority[mutation] = "0" * 64
    else:
        authority[mutation] = {"fabricated": "authority"}
    transition.write_text(json.dumps(authority), encoding="utf-8")
    monkeypatch.setattr(
        audit_evidence_identities,
        "discover_baseline_sources",
        lambda root: SimpleNamespace(source_sha256="f" * 64),
    )
    monkeypatch.setattr(
        source_transition,
        "generate",
        lambda root, *, authority_path=None: json.loads(json.dumps(canonical)),
    )

    with pytest.raises(
        audit_evidence_identities.AuditEvidenceIdentityError,
        match="does not match canonical recomputation",
    ):
        audit_evidence_identities.update(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("product", "mixed product hash tuple"),
        ("id", "rows must be sorted by stable ID"),
        ("semantics", "duplicate subject fingerprints"),
        ("mixed", "mixed product hash tuple"),
    ),
)
def test_assignment_identity_rebinding_rejects_authority_mutation(
    mutation: str, message: str
) -> None:
    raw = json.loads(
        (REPOSITORY_ROOT / source_transition.ASSIGNMENTS_PATH).read_text(
            encoding="utf-8"
        )
    )
    normal = [
        row
        for row in raw["rows"]
        if row.get("product", NORMAL_DEBUG_PRODUCT) == NORMAL_DEBUG_PRODUCT
    ]
    if mutation == "product":
        normal[0]["product"] = "pokeyellow_phase2_audit"
    elif mutation == "id":
        normal[0]["id"] = "AS-UNEXPECTED"
    elif mutation == "semantics":
        normal[0]["subject"] = normal[1]["subject"]
    else:
        normal[0]["evidence"]["rom_sha256"] = "0" * 64
    with pytest.raises(Exception, match=message):
        authority = DiscoveryAssignmentAuthority.from_dict(raw)
        audit_evidence_identities._updated_assignments(
            authority,
            "f" * 64,
            {
                "source_sha256": "f" * 64,
                "rom_sha256": "1" * 64,
                "map_sha256": "2" * 64,
                "sym_sha256": "3" * 64,
            },
        )


def test_assignment_identity_rebinding_requires_all_debug_artifacts(tmp_path) -> None:
    with pytest.raises(
        audit_evidence_identities.AuditEvidenceIdentityError,
        match="required build artifact is missing",
    ):
        audit_evidence_identities._normal_debug_hashes(tmp_path, "f" * 64)


def test_assignment_identity_rebinding_rejects_scope_and_semantic_drift() -> None:
    authority = DiscoveryAssignmentAuthority.load(
        REPOSITORY_ROOT / source_transition.ASSIGNMENTS_PATH
    )
    normal = authority.for_product(NORMAL_DEBUG_PRODUCT)
    narrowed = DiscoveryAssignmentAuthority(
        tuple(row for row in authority.rows if row.id != normal.rows[0].id)
    )
    with pytest.raises(
        audit_evidence_identities.AuditEvidenceIdentityError,
        match="normal-debug assignment scope changed",
    ):
        audit_evidence_identities._updated_assignments(
            narrowed,
            "f" * 64,
            {
                "source_sha256": "f" * 64,
                "rom_sha256": "1" * 64,
                "map_sha256": "2" * 64,
                "sym_sha256": "3" * 64,
            },
        )

    changed = replace(
        normal.rows[0],
        evidence=replace(normal.rows[0].evidence, reviewer="changed-reviewer"),
    )
    after = DiscoveryAssignmentAuthority(
        (changed,) + authority.rows[1:]
    )
    with pytest.raises(
        audit_evidence_identities.AuditEvidenceIdentityError,
        match="reviewed semantics changed",
    ):
        audit_evidence_identities._assert_assignment_delta(authority, after)


def test_identity_producer_make_target_is_stable_and_build_dependent() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    assert (
        "measure-full-color-audit-evidence-identities: "
        "measure-full-color-source-transition" in makefile
    )
    assert (
        "measure-full-color-source-transition: "
        "yellow yellow_debug yellow_vc yellow_phase2_audit" in makefile
    )
