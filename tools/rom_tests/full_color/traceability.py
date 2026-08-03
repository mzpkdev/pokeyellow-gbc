"""Closed, bidirectional validation for the full-color specification."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from .errors import TraceabilityError

_REQUIREMENT_ID = re.compile(r"R(?:[1-9]|1[0-2])\.[1-9][0-9]*\Z")
_ACCEPTANCE_ID = re.compile(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{2}\Z")
_CHECK_ID = re.compile(r"CHK-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{2}\Z")
_CONCRETE_ID = {
    "requirement": _REQUIREMENT_ID,
    "acceptance": _ACCEPTANCE_ID,
    "check": _CHECK_ID,
}

SPECIFICATION_DOCUMENTS = (
    "SPEC.md",
    "docs/acceptance-criteria.md",
    "docs/ai-iteration-harness.md",
    "docs/architecture.md",
    "docs/failed-hybrid-analysis.md",
    "docs/migration-plan.md",
    "docs/prerequisite-gates.md",
    "docs/replacement-inventory.md",
    "docs/requirements.md",
    "docs/scope.md",
    "docs/verification-plan.md",
)

_ID_SEARCH = {
    "requirement": re.compile(r"(?<![A-Za-z0-9])R\d+\.\d+(?![A-Za-z0-9.*])"),
    "acceptance": re.compile(
        r"(?<![A-Za-z0-9])AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+(?![A-Za-z0-9*-])"
    ),
    "check": re.compile(
        r"(?<![A-Za-z0-9])CHK-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+(?![A-Za-z0-9*-])"
    ),
}
_DEFINITION = {
    "requirement": re.compile(r"(?m)^\s*-\s+\*\*(R\d+\.\d+):\*\*\s+(\S.*)$"),
    "acceptance": re.compile(
        r"(?m)^\s*-\s+\*\*(AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+):\*\*\s+(\S.*)$"
    ),
    "check": re.compile(
        r"(?m)^\s*-\s+\*\*(CHK-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+):\*\*\s+(\S.*)$"
    ),
}
_WILDCARD_ID = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"R\d+\.\*|"
    r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\*|"
    r"CHK-[A-Z0-9]+(?:-[A-Z0-9]+)*-\*"
    r")(?![A-Za-z0-9*-])"
)
_LINK = re.compile(
    r'''(?x)(?<!!)\[[^\]]+\]\(\s*(<[^>]+>|[^)\s]+)'''
    r'''(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)'''
)


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
    documents: tuple[str, ...] = ()
    relative_links: int = 0
    requirement_mappings: tuple[RequirementMap, ...] = ()
    acceptance_mappings: tuple[AcceptanceMap, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": "full-color-traceability-report-v1",
            "requirements": self.requirements,
            "acceptances": self.acceptances,
            "checks": self.checks,
            "requirement_rows": self.requirement_rows,
            "acceptance_rows": self.acceptance_rows,
        }
        if self.documents:
            result["documents"] = list(self.documents)
            result["relative_links"] = self.relative_links
        if self.documents and self.requirement_mappings:
            result["requirement_mappings"] = [
                _mapping_dict(row) for row in self.requirement_mappings
            ]
        if self.documents and self.acceptance_mappings:
            result["acceptance_mappings"] = [
                _mapping_dict(row) for row in self.acceptance_mappings
            ]
        return result


def validate_traceability(
    *,
    requirement_ids: Iterable[str],
    acceptance_requirements: Mapping[str, Iterable[str]],
    check_ids: Iterable[str],
    requirement_rows: Iterable[RequirementMap],
    acceptance_rows: Iterable[AcceptanceMap],
    enforce_bidirectional: bool = True,
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

    if enforce_bidirectional:
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
        requirement_mappings=tuple(sorted(r_rows, key=lambda row: row.requirement)),
        acceptance_mappings=tuple(sorted(ac_rows, key=lambda row: row.acceptance)),
    )


def validate_specification(spec_root: Path | str) -> TraceabilityReport:
    """Parse and validate the exact full-color Markdown specification scope."""
    root = Path(spec_root).resolve()
    expected = tuple(root / relative for relative in SPECIFICATION_DOCUMENTS)
    actual = tuple(sorted(root.rglob("*.md"))) if root.is_dir() else ()
    if actual != tuple(sorted(expected)):
        actual_relative = [
            str(path.relative_to(root)) for path in actual if path.is_relative_to(root)
        ]
        raise TraceabilityError(
            "scoped Markdown set differs; expected: "
            + ", ".join(SPECIFICATION_DOCUMENTS)
            + "; actual: "
            + ", ".join(actual_relative)
        )

    texts = {path: path.read_text(encoding="utf-8") for path in expected}
    authority_paths = {
        "requirement": root / "docs/requirements.md",
        "acceptance": root / "docs/acceptance-criteria.md",
        "check": root / "docs/verification-plan.md",
    }
    definitions: dict[str, dict[str, str]] = {}
    for kind, pattern in _DEFINITION.items():
        occurrences = [
            (match.group(1), match.group(2), path)
            for path, text in texts.items()
            for match in pattern.finditer(text)
        ]
        counts = Counter(identifier for identifier, _, _ in occurrences)
        duplicates = sorted(
            identifier for identifier, count in counts.items() if count != 1
        )
        if duplicates:
            identifier = duplicates[0]
            raise TraceabilityError(
                f"{identifier}: {counts[identifier]} definitions (expected 1)"
            )
        misplaced = next(
            (
                (identifier, path)
                for identifier, _, path in occurrences
                if path != authority_paths[kind]
            ),
            None,
        )
        if misplaced:
            identifier, path = misplaced
            raise TraceabilityError(
                f"{identifier}: definition outside "
                f"{authority_paths[kind].relative_to(root)} "
                f"(found in {path.relative_to(root)})"
            )
        if not occurrences:
            raise TraceabilityError(f"no {kind} definitions found")
        definitions[kind] = {
            identifier: definition for identifier, definition, _ in occurrences
        }

    for path, text in texts.items():
        relative = path.relative_to(root)
        wildcard = _WILDCARD_ID.search(text)
        if wildcard:
            raise TraceabilityError(f"{relative}: wildcard ID {wildcard.group(0)}")
        for kind, pattern in _ID_SEARCH.items():
            for identifier in pattern.findall(text):
                if identifier not in definitions[kind]:
                    raise TraceabilityError(f"{relative}: unknown {identifier}")

    acceptance_requirements = {
        identifier: _acceptance_direct_requirements(identifier, definition)
        for identifier, definition in definitions["acceptance"].items()
    }
    requirement_rows, acceptance_rows = _parse_mapping_rows(
        texts[authority_paths["check"]]
    )
    link_count = _validate_links(root, expected, texts)
    report = validate_traceability(
        requirement_ids=definitions["requirement"],
        acceptance_requirements=acceptance_requirements,
        check_ids=definitions["check"],
        requirement_rows=requirement_rows,
        acceptance_rows=acceptance_rows,
        enforce_bidirectional=True,
    )
    return TraceabilityReport(
        requirements=report.requirements,
        acceptances=report.acceptances,
        checks=report.checks,
        requirement_rows=report.requirement_rows,
        acceptance_rows=report.acceptance_rows,
        documents=SPECIFICATION_DOCUMENTS,
        relative_links=link_count,
        requirement_mappings=report.requirement_mappings,
        acceptance_mappings=report.acceptance_mappings,
    )


def _acceptance_direct_requirements(
    identifier: str, definition: str
) -> tuple[str, ...]:
    marker = "Direct requirements:"
    if marker not in definition:
        raise TraceabilityError(
            f"acceptance definition {identifier}: missing 'Direct requirements:'"
        )
    requirement_text = definition.split(marker, 1)[1].strip().removesuffix(".")
    return _concrete_list(
        requirement_text,
        "requirement",
        f"acceptance definition {identifier}: expected only comma-separated "
        "direct requirement IDs",
    )


def _parse_mapping_rows(
    verification: str,
) -> tuple[tuple[RequirementMap, ...], tuple[AcceptanceMap, ...]]:
    requirement_rows: list[RequirementMap] = []
    acceptance_rows: list[AcceptanceMap] = []
    for line_number, line in enumerate(verification.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = tuple(
            cell.strip().strip("`")
            for cell in line.strip().strip("|").split("|")
        )
        if not cells or cells[0] not in {"R-MAP", "AC-MAP"}:
            continue
        where = f"docs/verification-plan.md:{line_number}"
        if len(cells) != 7:
            raise TraceabilityError(
                f"{where}: {cells[0]} row has {len(cells)} cells (expected 7)"
            )
        if cells[0] == "R-MAP":
            primary = _concrete_cell(cells[1], "requirement", where)
            if len(primary) != 1:
                raise TraceabilityError(
                    f"{where}: R-MAP needs exactly one primary requirement"
                )
            requirement_rows.append(
                RequirementMap(
                    primary[0],
                    _concrete_cell(cells[2], "acceptance", where),
                    _concrete_cell(cells[3], "check", where),
                    (cells[6],) if cells[6] else (),
                    cells[4],
                    cells[5],
                    0,
                )
            )
        else:
            primary = _concrete_cell(cells[1], "acceptance", where)
            if len(primary) != 1:
                raise TraceabilityError(
                    f"{where}: AC-MAP needs exactly one primary acceptance"
                )
            acceptance_rows.append(
                AcceptanceMap(
                    primary[0],
                    _concrete_cell(cells[2], "requirement", where),
                    _concrete_cell(cells[3], "check", where),
                    (cells[6],) if cells[6] else (),
                    cells[4],
                    cells[5],
                    0,
                )
            )
    return tuple(requirement_rows), tuple(acceptance_rows)


def _concrete_cell(cell: str, kind: str, where: str) -> tuple[str, ...]:
    return _concrete_list(
        cell,
        kind,
        f"{where}: expected comma-separated concrete {kind} IDs",
    )


def _concrete_list(value: str, kind: str, diagnostic: str) -> tuple[str, ...]:
    tokens = tuple(token.strip() for token in value.split(","))
    if not tokens or any(
        not token or _CONCRETE_ID[kind].fullmatch(token) is None for token in tokens
    ):
        raise TraceabilityError(f"{diagnostic}: {value!r}")
    return tokens


def _heading_anchors(text: str) -> frozenset[str]:
    anchors = set(re.findall(r'<a\s+(?:name|id)=["\']([^"\']+)["\']', text, re.I))
    seen: Counter[str] = Counter()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"<[^>]+>", "", match.group(1))
        title = re.sub(r"[`*_~]", "", title).strip().lower()
        base = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE).replace(" ", "-")
        suffix = seen[base]
        seen[base] += 1
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
    return frozenset(anchors)


def _validate_links(
    root: Path, expected: tuple[Path, ...], texts: Mapping[Path, str]
) -> int:
    anchors = {path: _heading_anchors(text) for path, text in texts.items()}
    count = 0
    for path, text in texts.items():
        relative = path.relative_to(root)
        if re.search(r"(?<!!)\[[^\]]+\]\[[^\]]*\]", text):
            raise TraceabilityError(
                f"{relative}: reference-style links are forbidden; "
                "use inline relative Markdown targets"
            )
        for raw in _LINK.findall(text):
            target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
            parts = urlsplit(target)
            if parts.scheme in {"http", "https", "mailto"}:
                continue
            count += 1
            if parts.scheme or parts.netloc or parts.path.startswith("/"):
                raise TraceabilityError(f"{relative}: non-relative local link {raw}")
            target_path = (
                path
                if not parts.path
                else (path.parent / unquote(parts.path)).resolve()
            )
            if target_path not in expected:
                raise TraceabilityError(
                    f"{relative}: local target is not a scoped Markdown file: {raw}"
                )
            fragment = unquote(parts.fragment)
            if fragment and fragment not in anchors[target_path]:
                raise TraceabilityError(
                    f"{relative}: missing anchor {fragment!r} in "
                    f"{target_path.relative_to(root)}"
                )
    return count


def _mapping_dict(row: RequirementMap | AcceptanceMap) -> dict[str, Any]:
    primary_key = "requirement" if isinstance(row, RequirementMap) else "acceptance"
    result: dict[str, Any] = {
        primary_key: getattr(row, primary_key),
        "checks": list(row.checks),
        "evidence": list(row.evidence),
        "tier": row.tier,
        "mutation": row.mutation,
    }
    if isinstance(row, RequirementMap):
        result["acceptances"] = list(row.acceptances)
    else:
        result["requirements"] = list(row.requirements)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    """Run the real-document validator and emit its canonical JSON report."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate the exact full-color Markdown specification and "
            "traceability maps."
        )
    )
    parser.add_argument(
        "--spec-root",
        type=Path,
        default=Path("specs/full-colors"),
        help="full-color specification root (default: specs/full-colors)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the canonical report to this path instead of stdout",
    )
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    try:
        report = validate_specification(args.spec_root)
        payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output is None:
            sys.stdout.write(payload)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError, TraceabilityError) as exc:
        print(f"full-color specification validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
