"""Closed, bidirectional validation for concrete R/AC/CHK traceability IDs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

from .errors import TraceabilityError

_REQUIREMENT_ID = re.compile(r"R(?:[1-9]|1[0-2])\.[1-9][0-9]*\Z")
_ACCEPTANCE_ID = re.compile(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{2}\Z")
_CHECK_ID = re.compile(r"CHK-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{2}\Z")


@dataclass(frozen=True, slots=True)
class RequirementMap:
    requirement: str
    acceptances: tuple[str, ...]
    checks: tuple[str, ...]
    evidence: tuple[str, ...]
    tier: str
    mutation: str
    activation_phase: int


@dataclass(frozen=True, slots=True)
class AcceptanceMap:
    acceptance: str
    requirements: tuple[str, ...]
    checks: tuple[str, ...]
    evidence: tuple[str, ...]
    tier: str
    mutation: str
    activation_phase: int


@dataclass(frozen=True, slots=True)
class TraceabilityReport:
    requirements: int
    acceptances: int
    checks: int
    requirement_rows: int
    acceptance_rows: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "schema": "full-color-traceability-report-v1",
            "requirements": self.requirements,
            "acceptances": self.acceptances,
            "checks": self.checks,
            "requirement_rows": self.requirement_rows,
            "acceptance_rows": self.acceptance_rows,
        }


def validate_traceability(
    *,
    requirement_ids: Iterable[str],
    acceptance_requirements: Mapping[str, Iterable[str]],
    check_ids: Iterable[str],
    requirement_rows: Iterable[RequirementMap],
    acceptance_rows: Iterable[AcceptanceMap],
) -> TraceabilityReport:
    """Validate authority IDs, all references, closure, and exact AC requirement sets."""
    requirements = _authority_set(
        requirement_ids, kind="requirement", pattern=_REQUIREMENT_ID
    )
    checks = _authority_set(check_ids, kind="check", pattern=_CHECK_ID)
    acceptances = _authority_set(
        acceptance_requirements, kind="acceptance", pattern=_ACCEPTANCE_ID
    )
    authority_ac_requirements: dict[str, frozenset[str]] = {}
    for acceptance in sorted(acceptances):
        referenced = tuple(acceptance_requirements[acceptance])
        _reject_duplicate_refs(
            referenced, path=f"acceptance definition {acceptance}.requirements"
        )
        unknown = sorted(set(referenced) - requirements)
        if unknown:
            raise TraceabilityError(
                f"acceptance definition {acceptance}: unknown requirement IDs: {', '.join(unknown)}"
            )
        if not referenced:
            raise TraceabilityError(
                f"acceptance definition {acceptance}: uncovered; no requirement IDs"
            )
        authority_ac_requirements[acceptance] = frozenset(referenced)

    r_rows = tuple(requirement_rows)
    ac_rows = tuple(acceptance_rows)
    _validate_primary_ids(
        (row.requirement for row in r_rows),
        authority=requirements,
        kind="requirement",
        pattern=_REQUIREMENT_ID,
    )
    _validate_primary_ids(
        (row.acceptance for row in ac_rows),
        authority=acceptances,
        kind="acceptance",
        pattern=_ACCEPTANCE_ID,
    )

    r_by_id = {row.requirement: row for row in r_rows}
    ac_by_id = {row.acceptance: row for row in ac_rows}
    referenced_checks: set[str] = set()

    for requirement in sorted(r_by_id):
        row = r_by_id[requirement]
        _validate_evidence_metadata(row, path=f"R-MAP {requirement}")
        _validate_refs(
            row.acceptances,
            authority=acceptances,
            path=f"R-MAP {requirement}.acceptances",
            kind="acceptance",
        )
        _validate_refs(
            row.checks,
            authority=checks,
            path=f"R-MAP {requirement}.checks",
            kind="check",
        )
        if not row.acceptances:
            raise TraceabilityError(f"R-MAP {requirement}: orphan; no acceptance IDs")
        if not row.checks:
            raise TraceabilityError(f"R-MAP {requirement}: orphan; no check IDs")
        referenced_checks.update(row.checks)

    for acceptance in sorted(ac_by_id):
        row = ac_by_id[acceptance]
        _validate_evidence_metadata(row, path=f"AC-MAP {acceptance}")
        _validate_refs(
            row.requirements,
            authority=requirements,
            path=f"AC-MAP {acceptance}.requirements",
            kind="requirement",
        )
        _validate_refs(
            row.checks,
            authority=checks,
            path=f"AC-MAP {acceptance}.checks",
            kind="check",
        )
        actual = frozenset(row.requirements)
        expected = authority_ac_requirements[acceptance]
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("extra " + ", ".join(extra))
            raise TraceabilityError(
                f"AC-MAP {acceptance}: requirement set differs from authority definition "
                f"({'; '.join(details)})"
            )
        if not row.checks:
            raise TraceabilityError(f"AC-MAP {acceptance}: orphan; no check IDs")
        referenced_checks.update(row.checks)

    for requirement, r_row in sorted(r_by_id.items()):
        for acceptance in r_row.acceptances:
            if requirement not in ac_by_id[acceptance].requirements:
                raise TraceabilityError(
                    f"bidirectional mapping mismatch: R-MAP {requirement} names {acceptance}, "
                    f"but AC-MAP {acceptance} does not name {requirement}"
                )
    for acceptance, ac_row in sorted(ac_by_id.items()):
        for requirement in ac_row.requirements:
            if acceptance not in r_by_id[requirement].acceptances:
                raise TraceabilityError(
                    f"bidirectional mapping mismatch: AC-MAP {acceptance} names {requirement}, "
                    f"but R-MAP {requirement} does not name {acceptance}"
                )

    orphan_checks = sorted(checks - referenced_checks)
    if orphan_checks:
        raise TraceabilityError(
            f"orphan check IDs are defined but never mapped: {', '.join(orphan_checks)}"
        )
    return TraceabilityReport(
        requirements=len(requirements),
        acceptances=len(acceptances),
        checks=len(checks),
        requirement_rows=len(r_rows),
        acceptance_rows=len(ac_rows),
    )


def _authority_set(
    values: Iterable[str],
    *,
    kind: str,
    pattern: re.Pattern[str],
) -> frozenset[str]:
    sequence = tuple(values)
    _reject_duplicate_refs(sequence, path=f"{kind} authority")
    for value in sequence:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise TraceabilityError(f"{kind} authority: malformed concrete ID {value!r}")
    return frozenset(sequence)


def _validate_primary_ids(
    values: Iterable[str],
    *,
    authority: frozenset[str],
    kind: str,
    pattern: re.Pattern[str],
) -> None:
    sequence = tuple(values)
    for value in sequence:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise TraceabilityError(f"{kind} mapping: malformed concrete ID {value!r}")
    duplicates = sorted({value for value in sequence if sequence.count(value) > 1})
    if duplicates:
        raise TraceabilityError(
            f"duplicate primary {kind} mapping IDs: {', '.join(duplicates)}"
        )
    unknown = sorted(set(sequence) - authority)
    if unknown:
        raise TraceabilityError(
            f"unknown primary {kind} mapping IDs: {', '.join(unknown)}"
        )
    uncovered = sorted(authority - set(sequence))
    if uncovered:
        raise TraceabilityError(
            f"uncovered {kind} authority IDs: {', '.join(uncovered)}"
        )


def _validate_refs(
    values: tuple[str, ...],
    *,
    authority: frozenset[str],
    path: str,
    kind: str,
) -> None:
    _reject_duplicate_refs(values, path=path)
    unknown = sorted(set(values) - authority)
    if unknown:
        raise TraceabilityError(f"{path}: unknown {kind} IDs: {', '.join(unknown)}")


def _reject_duplicate_refs(values: tuple[str, ...], *, path: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise TraceabilityError(f"{path}: duplicate IDs: {', '.join(duplicates)}")


def _validate_evidence_metadata(
    row: RequirementMap | AcceptanceMap, *, path: str
) -> None:
    if not isinstance(row.evidence, tuple) or not row.evidence:
        raise TraceabilityError(f"{path}: missing evidence references")
    if any(not isinstance(item, str) or not item for item in row.evidence):
        raise TraceabilityError(f"{path}: evidence references must be non-empty strings")
    _reject_duplicate_refs(row.evidence, path=f"{path}.evidence")
    if (
        not isinstance(row.tier, str)
        or not row.tier
        or any(part not in {"fast", "focused", "full"} for part in row.tier.split("/"))
    ):
        raise TraceabilityError(
            f"{path}: tier must contain fast, focused, or full evidence tiers"
        )
    if not isinstance(row.mutation, str) or not row.mutation:
        raise TraceabilityError(f"{path}: missing mutation evidence metadata")
    if (
        isinstance(row.activation_phase, bool)
        or not isinstance(row.activation_phase, int)
        or not 0 <= row.activation_phase <= 9
    ):
        raise TraceabilityError(f"{path}: activation phase must be an integer in 0..9")
