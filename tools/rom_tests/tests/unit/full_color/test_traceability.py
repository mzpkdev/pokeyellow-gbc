"""Concrete traceability closure and mutation tests."""

from dataclasses import replace

import pytest

from tools.rom_tests.full_color.errors import TraceabilityError
from tools.rom_tests.full_color.traceability import (
    AcceptanceMap,
    RequirementMap,
    validate_traceability,
)


def valid_input() -> dict[str, object]:
    def requirement(requirement_id: str) -> RequirementMap:
        return RequirementMap(
            requirement_id,
            ("AC-OWN-01",),
            ("CHK-OWN-01",),
            ("artifacts/owner-trace.json",),
            "fast/full",
            "wrong-owner write",
            0,
        )

    return {
        "requirement_ids": ("R1.1", "R1.2"),
        "acceptance_requirements": {
            "AC-OWN-01": ("R1.1", "R1.2"),
        },
        "check_ids": ("CHK-OWN-01",),
        "requirement_rows": (
            requirement("R1.1"),
            requirement("R1.2"),
        ),
        "acceptance_rows": (
            AcceptanceMap(
                "AC-OWN-01",
                ("R1.1", "R1.2"),
                ("CHK-OWN-01",),
                ("artifacts/owner-trace.json",),
                "fast/full",
                "wrong-owner write",
                0,
            ),
        ),
    }


def test_closed_traceability_returns_machine_readable_counts() -> None:
    report = validate_traceability(**valid_input())

    assert report.to_dict() == {
        "schema": "full-color-traceability-report-v1",
        "requirements": 2,
        "acceptances": 1,
        "checks": 1,
        "requirement_rows": 2,
        "acceptance_rows": 1,
    }


def test_unknown_reference_fails_specifically() -> None:
    raw = valid_input()
    rows = list(raw["requirement_rows"])
    rows[0] = replace(rows[0], checks=("CHK-NOT-DEFINED-99",))
    raw["requirement_rows"] = tuple(rows)

    with pytest.raises(TraceabilityError, match="unknown check IDs: CHK-NOT-DEFINED-99"):
        validate_traceability(**raw)


def test_uncovered_authority_id_fails_specifically() -> None:
    raw = valid_input()
    raw["requirement_rows"] = raw["requirement_rows"][:1]

    with pytest.raises(TraceabilityError, match="uncovered requirement authority IDs: R1.2"):
        validate_traceability(**raw)


def test_duplicate_primary_id_fails_specifically() -> None:
    raw = valid_input()
    raw["requirement_rows"] = (
        raw["requirement_rows"][0],
        raw["requirement_rows"][0],
    )

    with pytest.raises(TraceabilityError, match="duplicate primary requirement mapping IDs"):
        validate_traceability(**raw)


def test_duplicate_reference_id_fails_specifically() -> None:
    raw = valid_input()
    rows = list(raw["requirement_rows"])
    rows[0] = replace(rows[0], checks=("CHK-OWN-01", "CHK-OWN-01"))
    raw["requirement_rows"] = tuple(rows)

    with pytest.raises(TraceabilityError, match="duplicate IDs: CHK-OWN-01"):
        validate_traceability(**raw)


def test_acceptance_requirement_set_must_equal_authority_definition() -> None:
    raw = valid_input()
    raw["acceptance_rows"] = (
        replace(raw["acceptance_rows"][0], requirements=("R1.1",)),
    )

    with pytest.raises(TraceabilityError, match="missing R1.2"):
        validate_traceability(**raw)


def test_orphan_check_definition_fails_specifically() -> None:
    raw = valid_input()
    raw["check_ids"] = ("CHK-OWN-01", "CHK-JOB-01")

    with pytest.raises(TraceabilityError, match="orphan check IDs.*CHK-JOB-01"):
        validate_traceability(**raw)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"evidence": ()}, "missing evidence references"),
        ({"tier": ""}, "tier must contain"),
        ({"mutation": ""}, "missing mutation evidence metadata"),
        ({"activation_phase": -1}, "activation phase"),
    ],
)
def test_rows_reject_missing_evidence_metadata(
    changes: dict[str, object], message: str
) -> None:
    raw = valid_input()
    rows = list(raw["requirement_rows"])
    rows[0] = replace(rows[0], **changes)
    raw["requirement_rows"] = tuple(rows)

    with pytest.raises(TraceabilityError, match=message):
        validate_traceability(**raw)
