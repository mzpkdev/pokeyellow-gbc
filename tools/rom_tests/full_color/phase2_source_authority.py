"""Rebind the reviewed Phase 2 source closure after source-only activation.

The Phase 2 audit ROM remains a frozen authority.  This producer is deliberately
limited to the source findings and source diagnostics discovered beneath the
already-reviewed Phase 2 roots.  Row disposition and enrichment come from the
existing reviewed assignment for that row; ROM subjects and all other planned
authority are immutable inputs.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Sequence

from .discovery_assignment import (
    AssignmentRow,
    DiscoveryAssignmentAuthority,
    PHASE2_AUDIT_PRODUCT,
)
from .discovery_review import SubjectKind, source_error_subject, source_finding_subject
from .baseline_inventory import _phase2_transition_state
from .inventory import MutationInventory, SceneInventory, WriterInventory
from .phase2_measurements import (
    PHASE2_PLANNED_ROW_IDS,
    PLANNED_SUBJECTS_PATH,
    _planned_row_for,
    _source_finding_root,
    _normalize_closed_scene_directions,
    discover_phase2_sources,
)


ASSIGNMENTS_PATH = Path("specs/full-colors/inventory/assignments.json")
INVENTORY_DOCUMENTS = {
    Path("specs/full-colors/inventory/mutations.json"): MutationInventory,
    Path("specs/full-colors/inventory/scenes.json"): SceneInventory,
    Path("specs/full-colors/inventory/writers.json"): WriterInventory,
}


class Phase2SourceAuthorityError(RuntimeError):
    """The reviewed source authority cannot be rebound without changing policy."""


def _canonical_planned(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _assignment_id(row_id: str, digest: str) -> str:
    return f"AS-P2-{row_id.split('-', 1)[1]}-SRC-{digest[:16].upper()}"


def _template_signature(row: AssignmentRow) -> tuple[object, ...]:
    return (
        row.category,
        row.row_id,
        row.scene,
        row.mutation,
        row.evidence.rom_sha256,
        row.evidence.sym_sha256,
        row.evidence.map_sha256,
        row.evidence.reviewer,
        row.evidence.reviewed,
    )


def _templates(authority: DiscoveryAssignmentAuthority) -> dict[str, AssignmentRow]:
    grouped: dict[str, list[AssignmentRow]] = {}
    for row in authority.rows:
        if (
            row.product == PHASE2_AUDIT_PRODUCT
            and row.subject.kind is SubjectKind.SOURCE_FINDING
        ):
            grouped.setdefault(row.row_id, []).append(row)
    if set(grouped) != PHASE2_PLANNED_ROW_IDS:
        raise Phase2SourceAuthorityError(
            "reviewed Phase 2 source templates do not cover the exact planned row set"
        )
    result: dict[str, AssignmentRow] = {}
    for row_id, rows in grouped.items():
        signatures = {_template_signature(row) for row in rows}
        if len(signatures) != 1:
            raise Phase2SourceAuthorityError(
                f"{row_id}: reviewed source assignments disagree on row disposition"
            )
        result[row_id] = rows[0]
    return result


def _rebind_site(
    site: dict[str, Any], configured_roots: dict[str, list[object]]
) -> None:
    candidates = configured_roots.get(site["symbol"], [])
    if not candidates:
        return
    exact = [
        finding
        for finding in candidates
        if finding.path == site["path"] and finding.line == site["line"]
    ]
    if exact:
        return
    distances = sorted(
        (abs(finding.line - site["line"]), finding.path, finding.line, finding)
        for finding in candidates
    )
    if len(distances) > 1 and distances[0][:3] == distances[1][:3]:
        raise Phase2SourceAuthorityError(
            f"{site['symbol']}: source location rebind is ambiguous"
        )
    finding = distances[0][3]
    site["path"] = finding.path
    site["line"] = finding.line


def _updated_inventories(
    root: Path, report: object
) -> dict[Path, str]:
    configured_roots: dict[str, list[object]] = {}
    for finding in report.findings:
        if finding.mechanism == "configured-root":
            configured_roots.setdefault(finding.symbol, []).append(finding)
    rendered: dict[Path, str] = {}
    for relative, document_type in INVENTORY_DOCUMENTS.items():
        raw = json.loads((root / relative).read_text(encoding="utf-8"))
        for row in raw["rows"]:
            for site in row.get("source_sites", []):
                _rebind_site(site, configured_roots)
            if "source" in row:
                _rebind_site(row["source"], configured_roots)
                if row.get("destination") is not None:
                    _rebind_site(row["destination"], configured_roots)
        rendered[relative] = document_type.from_dict(raw).to_json()
    return rendered


def generate(
    root: Path,
) -> tuple[dict[str, Any], DiscoveryAssignmentAuthority, dict[Path, str]]:
    root = root.resolve()
    planned_path = root / PLANNED_SUBJECTS_PATH
    assignments_path = root / ASSIGNMENTS_PATH
    planned = json.loads(planned_path.read_text(encoding="utf-8"))
    authority = DiscoveryAssignmentAuthority.load(assignments_path)
    templates = _templates(authority)
    report = discover_phase2_sources(root)
    inventories = {
        relative.name: document_type.load(root / relative)
        for relative, document_type in INVENTORY_DOCUMENTS.items()
    }
    if _phase2_transition_state(
        writers=inventories["writers.json"],
        scenes=inventories["scenes.json"],
        mutations=inventories["mutations.json"],
        assignments=authority,
    ) == "audit-closed":
        report = _normalize_closed_scene_directions(report)

    subjects: dict[str, list[str]] = {
        row_id: [] for row_id in sorted(PHASE2_PLANNED_ROW_IDS)
    }
    new_source_rows: list[AssignmentRow] = []
    for finding in report.findings:
        finding_root = _source_finding_root(finding)
        if finding_root is None:
            continue
        row_id = _planned_row_for(
            finding_root, finding.category, resource=finding.resource
        )
        subject = source_finding_subject(finding)
        subjects[row_id].append(subject.sha256)
        template = templates[row_id]
        new_source_rows.append(
            replace(
                template,
                id=_assignment_id(row_id, subject.sha256),
                subject=subject,
                evidence=replace(
                    template.evidence, source_sha256=report.source_sha256
                ),
            )
        )

    canonical_subjects = {
        row_id: sorted(values) for row_id, values in subjects.items()
    }
    flattened = [digest for values in canonical_subjects.values() for digest in values]
    if len(flattened) != len(set(flattened)):
        raise Phase2SourceAuthorityError(
            "one discovered source subject mapped to more than one planned row"
        )

    updated_planned = deepcopy(planned)
    updated_planned["source_subjects"] = canonical_subjects
    updated_planned["source_error_subjects"] = sorted(
        source_error_subject(message).sha256 for message in report.errors
    )
    counts = updated_planned["authority_counts"]
    counts["source_subjects"] = {
        "by_row": {
            row_id: len(values) for row_id, values in canonical_subjects.items()
        },
        "total": len(flattened),
    }
    counts["source_error_subjects"] = {
        "total": len(updated_planned["source_error_subjects"])
    }

    retained = [
        row
        for row in authority.rows
        if not (
            row.product == PHASE2_AUDIT_PRODUCT
            and row.subject.kind is SubjectKind.SOURCE_FINDING
        )
    ]
    updated_assignments = DiscoveryAssignmentAuthority(
        tuple(sorted((*retained, *new_source_rows), key=lambda row: row.id))
    )
    # Round-trip through the strict models before any file is written.
    DiscoveryAssignmentAuthority.from_json(updated_assignments.to_json())
    return updated_planned, updated_assignments, _updated_inventories(root, report)


def update(root: Path) -> None:
    planned, assignments, inventories = generate(root)
    (root / PLANNED_SUBJECTS_PATH).write_text(
        _canonical_planned(planned), encoding="utf-8"
    )
    (root / ASSIGNMENTS_PATH).write_text(assignments.to_json(), encoding="utf-8")
    for relative, content in inventories.items():
        (root / relative).write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        update(args.root)
    except (OSError, ValueError, Phase2SourceAuthorityError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
