"""Concrete traceability closure and mutation tests."""

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from tools.rom_tests.full_color.errors import TraceabilityError
from tools.rom_tests.full_color.traceability import (
    AcceptanceMap,
    RequirementMap,
    SPECIFICATION_DOCUMENTS,
    main,
    validate_specification,
    validate_traceability,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
REAL_SPEC_ROOT = REPOSITORY_ROOT / "specs/full-colors"


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


def test_real_specification_emits_complete_canonical_mapping_report() -> None:
    report = validate_specification(REAL_SPEC_ROOT)
    payload = report.to_dict()

    assert payload["schema"] == "full-color-traceability-report-v1"
    assert payload["documents"] == list(SPECIFICATION_DOCUMENTS)
    assert payload["requirements"] == payload["requirement_rows"] == 122
    assert payload["acceptances"] == payload["acceptance_rows"] == 42
    assert payload["checks"] == 30
    assert payload["relative_links"] == 76
    assert len(payload["requirement_mappings"]) == 122
    assert len(payload["acceptance_mappings"]) == 42
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        validate_specification(REAL_SPEC_ROOT).to_dict(), sort_keys=True
    )


def test_cli_writes_identical_report_on_double_execution(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert main(("--spec-root", str(REAL_SPEC_ROOT), "--output", str(first))) == 0
    assert main(("--spec-root", str(REAL_SPEC_ROOT), "--output", str(second))) == 0
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["checks"] == 30


def test_cli_reports_output_parent_failure_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("occupied", encoding="utf-8")

    assert main(
        (
            "--spec-root",
            str(REAL_SPEC_ROOT),
            "--output",
            str(invalid_parent / "report.json"),
        )
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("full-color specification validation failed: ")
    assert "Traceback" not in captured.err


def _copy_specification(tmp_path: Path) -> Path:
    target = tmp_path / "full-colors"
    shutil.copytree(REAL_SPEC_ROOT, target)
    return target


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("extra-document", "scoped Markdown set differs"),
        ("unknown-reference", "unknown R99.99"),
        ("duplicate-definition", "R1.1: 2 definitions"),
        ("missing-primary", "uncovered requirement authority IDs: R1.1"),
        ("orphan-check", "orphan check IDs.*CHK-GHOST-99"),
        ("broken-anchor", "missing anchor 'not-a-real-anchor'"),
        ("ac-multisegment-wildcard", "wildcard ID AC-EVIDENCE-BASELINE-\\*"),
        ("check-multisegment-wildcard", "wildcard ID CHK-EVIDENCE-BASELINE-\\*"),
    ],
)
def test_real_specification_mutations_fail_specifically(
    tmp_path: Path, mutation: str, message: str
) -> None:
    root = _copy_specification(tmp_path)
    requirements = root / "docs/requirements.md"
    verification = root / "docs/verification-plan.md"
    spec = root / "SPEC.md"

    if mutation == "extra-document":
        (root / "unexpected.md").write_text("# Unexpected\n", encoding="utf-8")
    elif mutation == "unknown-reference":
        requirements.write_text(
            requirements.read_text(encoding="utf-8") + "\nUnknown R99.99 reference.\n",
            encoding="utf-8",
        )
    elif mutation == "duplicate-definition":
        requirements.write_text(
            requirements.read_text(encoding="utf-8") + "\n- **R1.1:** Duplicate.\n",
            encoding="utf-8",
        )
    elif mutation == "missing-primary":
        verification.write_text(
            verification.read_text(encoding="utf-8").replace(
                "| R-MAP | R1.1 |", "| NOT-A-MAP | R1.1 |", 1
            ),
            encoding="utf-8",
        )
    elif mutation == "orphan-check":
        verification.write_text(
            verification.read_text(encoding="utf-8")
            + "\n- **CHK-GHOST-99:** Method: fixture; tier: fast; evidence: fixture.\n",
            encoding="utf-8",
        )
    elif mutation == "broken-anchor":
        spec.write_text(
            spec.read_text(encoding="utf-8").replace(
                "(docs/scope.md)", "(docs/scope.md#not-a-real-anchor)", 1
            ),
            encoding="utf-8",
        )
    elif mutation == "ac-multisegment-wildcard":
        requirements.write_text(
            requirements.read_text(encoding="utf-8")
            + "\nForbidden AC-EVIDENCE-BASELINE-* placeholder.\n",
            encoding="utf-8",
        )
    elif mutation == "check-multisegment-wildcard":
        requirements.write_text(
            requirements.read_text(encoding="utf-8")
            + "\nForbidden CHK-EVIDENCE-BASELINE-* placeholder.\n",
            encoding="utf-8",
        )

    with pytest.raises(TraceabilityError, match=message):
        validate_specification(root)


@pytest.mark.parametrize(
    "acceptances", [", AC-OWN-01", "AC-OWN-01,", "AC-OWN-01,, AC-TECH-06"]
)
def test_mapping_cells_reject_empty_comma_entries(
    tmp_path: Path, acceptances: str
) -> None:
    root = _copy_specification(tmp_path)
    verification = root / "docs/verification-plan.md"
    verification.write_text(
        verification.read_text(encoding="utf-8").replace(
            "| R-MAP | R1.1 | AC-DONE-01, AC-OWN-01 |",
            f"| R-MAP | R1.1 | {acceptances} |",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TraceabilityError, match="comma-separated concrete acceptance"):
        validate_specification(root)


def test_real_specification_rejects_requirement_to_acceptance_asymmetry(
    tmp_path: Path,
) -> None:
    root = _copy_specification(tmp_path)
    verification = root / "docs/verification-plan.md"
    verification.write_text(
        verification.read_text(encoding="utf-8").replace(
            "| R-MAP | R1.1 | AC-DONE-01, AC-OWN-01 |",
            "| R-MAP | R1.1 | AC-DONE-01, AC-OAM-01, AC-OWN-01 |",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        TraceabilityError,
        match=r"R-MAP R1\.1 names AC-OAM-01, but AC-MAP AC-OAM-01 does not name R1\.1",
    ):
        validate_specification(root)


def test_real_specification_rejects_acceptance_to_requirement_asymmetry(
    tmp_path: Path,
) -> None:
    root = _copy_specification(tmp_path)
    acceptance = root / "docs/acceptance-criteria.md"
    verification = root / "docs/verification-plan.md"
    acceptance.write_text(
        acceptance.read_text(encoding="utf-8").replace(
            "Direct requirements: R9.1, R9.2, R9.3, R9.4.",
            "Direct requirements: R1.1, R9.1, R9.2, R9.3, R9.4.",
            1,
        ),
        encoding="utf-8",
    )
    verification.write_text(
        verification.read_text(encoding="utf-8").replace(
            "| AC-MAP | AC-OAM-01 | R9.1, R9.2, R9.3, R9.4 |",
            "| AC-MAP | AC-OAM-01 | R1.1, R9.1, R9.2, R9.3, R9.4 |",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        TraceabilityError,
        match=r"AC-MAP AC-OAM-01 names R1\.1, but R-MAP R1\.1 does not name AC-OAM-01",
    ):
        validate_specification(root)


@pytest.mark.parametrize("requirements", [", R1.1", "R1.1,", "R1.1,, R1.2"])
def test_direct_requirements_reject_empty_comma_entries(
    tmp_path: Path, requirements: str
) -> None:
    root = _copy_specification(tmp_path)
    acceptance = root / "docs/acceptance-criteria.md"
    acceptance.write_text(
        acceptance.read_text(encoding="utf-8").replace(
            "Direct requirements: R1.1, R1.2, R1.3, R1.4, R1.5, R1.33, R5.7, R10.2.",
            f"Direct requirements: {requirements}.",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TraceabilityError, match="comma-separated direct requirement IDs"):
        validate_specification(root)
