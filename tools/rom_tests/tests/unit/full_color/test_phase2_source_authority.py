from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color import phase2_source_authority
from tools.rom_tests.full_color.discovery_assignment import (
    DiscoveryAssignmentAuthority,
    PHASE2_AUDIT_PRODUCT,
)
from tools.rom_tests.full_color.discovery_review import SubjectKind


ROOT = Path(__file__).resolve().parents[5]


def test_generate_is_deterministic_and_preserves_non_source_authority() -> None:
    planned, assignments, inventories = phase2_source_authority.generate(ROOT)
    planned_again, assignments_again, inventories_again = (
        phase2_source_authority.generate(ROOT)
    )
    assert planned == planned_again
    assert assignments.to_json() == assignments_again.to_json()
    assert inventories == inventories_again

    current_planned = json.loads(
        (ROOT / phase2_source_authority.PLANNED_SUBJECTS_PATH).read_text()
    )
    for key in (
        "rom_subjects",
        "rom_candidate_subjects",
        "rom_unresolved_dispositions",
        "planned_only_dispositions",
        "source_error_disposition",
    ):
        assert planned[key] == current_planned[key]

    current = DiscoveryAssignmentAuthority.load(
        ROOT / phase2_source_authority.ASSIGNMENTS_PATH
    )
    retained = lambda authority: tuple(
        row.to_dict()
        for row in authority.rows
        if not (
            row.product == PHASE2_AUDIT_PRODUCT
            and row.subject.kind is SubjectKind.SOURCE_FINDING
        )
    )
    assert retained(assignments) == retained(current)


def test_generate_rejects_ambiguous_reviewed_row_policy(monkeypatch) -> None:
    authority = DiscoveryAssignmentAuthority.load(
        ROOT / phase2_source_authority.ASSIGNMENTS_PATH
    )
    source_rows = [
        row
        for row in authority.rows
        if row.product == PHASE2_AUDIT_PRODUCT
        and row.subject.kind is SubjectKind.SOURCE_FINDING
    ]
    target = source_rows[0]
    changed = replace(target, category=next(
        row.category for row in source_rows if row.category != target.category
    ))
    monkeypatch.setattr(
        phase2_source_authority.DiscoveryAssignmentAuthority,
        "load",
        classmethod(lambda cls, path: replace(authority, rows=tuple(
            changed if row.id == target.id else row for row in authority.rows
        ))),
    )
    with pytest.raises(
        phase2_source_authority.Phase2SourceAuthorityError,
        match="disagree on row disposition",
    ):
        phase2_source_authority.generate(ROOT)
