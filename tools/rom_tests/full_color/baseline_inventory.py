"""Deterministic progress report for the reviewed baseline inventory tranche."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Sequence

from .baseline_discovery import discover_baseline_rom, discover_baseline_sources
from .discovery_assignment import DiscoveryAssignmentAuthority
from .discovery_review import rom_finding_subject, source_finding_subject
from .inventory import (
    InventoryReconciliationError,
    MutationInventory,
    SceneInventory,
    WriterInventory,
    reconcile,
)

PROGRESS_SCHEMA = "full-color-inventory-progress-v1"


def _validate_assignment_targets(
    assignments: DiscoveryAssignmentAuthority,
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
) -> None:
    targets = {
        row["id"]: row
        for rows in (writers.rows, scenes.rows, mutations.rows)
        for row in rows
    }
    errors: list[str] = []
    for assignment in assignments.rows:
        target = targets.get(assignment.row_id)
        if target is None:
            errors.append(f"{assignment.id}: target row does not exist")
            continue
        metadata = assignment.subject.metadata
        if assignment.subject.kind.value == "SOURCE_FINDING":
            source_sites = (
                (target["source"],)
                if assignment.category.value == "scene"
                else target["source_sites"]
            )
            source_key = (
                metadata["path"],
                metadata["line"],
                metadata["symbol"],
            )
            if not any(
                source_key == (site["path"], site["line"], site["symbol"])
                for site in source_sites
            ):
                errors.append(
                    f"{assignment.id}: source subject does not belong to "
                    f"{assignment.row_id}"
                )
                continue
            if assignment.category.value == "mutation":
                destination = (
                    metadata["destination"]
                    if assignment.mutation is None
                    else assignment.mutation.destination
                )
                if destination != target["destination"]:
                    errors.append(
                        f"{assignment.id}: mutation destination does not match "
                        f"{assignment.row_id}"
                    )
            if assignment.category.value == "scene":
                enrichment = assignment.scene
                destination = target["destination"]
                expected_shape = (
                    target["row_kind"],
                    target["direction"],
                    None if destination is None else destination["path"],
                    None if destination is None else destination["line"],
                    None if destination is None else destination["symbol"],
                )
                actual_shape = (
                    enrichment.row_kind,
                    enrichment.direction,
                    enrichment.destination_path,
                    enrichment.destination_line,
                    enrichment.destination_symbol,
                )
                if actual_shape != expected_shape:
                    errors.append(
                        f"{assignment.id}: scene shape does not match "
                        f"{assignment.row_id}"
                    )
        else:
            machine_key = (
                metadata["bank"],
                metadata["address"],
                metadata["bytes"],
            )
            if not any(
                machine_key == (site["bank"], site["address"], site["bytes"])
                for site in target["machine_sites"]
            ):
                errors.append(
                    f"{assignment.id}: ROM subject does not belong to "
                    f"{assignment.row_id}"
                )
    if errors:
        raise InventoryReconciliationError("\n".join(errors))


def _project_assignments(
    assignments: DiscoveryAssignmentAuthority, source_report: Any, rom_report: Any
) -> tuple[Any, Any, tuple[str, ...], tuple[str, ...]]:
    hashes = {
        "source_sha256": source_report.source_sha256,
        "rom_sha256": rom_report.rom_sha256,
        "sym_sha256": rom_report.sym_sha256,
        "map_sha256": rom_report.map_sha256,
    }
    matcher = assignments.matcher(**hashes)
    subjects = {row.subject.sha256: row for row in assignments.rows}
    source_rows: list[str] = []
    rom_rows: list[str] = []
    source_findings = []
    for finding in source_report.findings:
        row = subjects.get(source_finding_subject(finding).sha256)
        if row is None:
            source_findings.append(finding)
        else:
            source_findings.append(matcher.project_source_finding(finding))
            source_rows.append(row.row_id)
    rom_findings = []
    for finding in rom_report.findings:
        row = subjects.get(rom_finding_subject(finding).sha256)
        if row is None:
            rom_findings.append(finding)
        else:
            rom_findings.append(matcher.project_rom_finding(finding))
            rom_rows.append(row.row_id)
    candidate_findings = []
    for finding in rom_report.candidate_findings:
        row = subjects.get(rom_finding_subject(finding).sha256)
        if row is None:
            candidate_findings.append(finding)
        else:
            candidate_findings.append(matcher.project_rom_finding(finding))
            rom_rows.append(row.row_id)
    matcher.assert_all_consumed()
    return (
        replace(source_report, findings=tuple(source_findings)),
        replace(
            rom_report,
            findings=tuple(rom_findings),
            candidate_findings=tuple(candidate_findings),
        ),
        tuple(sorted(source_rows)),
        tuple(sorted(rom_rows)),
    )


def build_progress(
    *,
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
    assignments: DiscoveryAssignmentAuthority,
    source_report: Any,
    rom_report: Any,
    rom: bytes,
) -> dict[str, Any]:
    """Project reviewed assignments once and report honest remaining work."""
    _validate_assignment_targets(assignments, writers, scenes, mutations)
    projected_source, projected_rom, source_rows, rom_rows = _project_assignments(
        assignments, source_report, rom_report
    )
    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=projected_source,
        rom_report=projected_rom,
        rom=rom,
        raise_on_error=False,
    )
    rows = tuple(writers.rows) + tuple(scenes.rows) + tuple(mutations.rows)
    row_ids = tuple(sorted(row["id"] for row in rows))
    if set(source_rows) != set(row_ids):
        raise InventoryReconciliationError(
            "every reviewed row requires an exact source assignment"
        )
    if set(rom_rows) != set(row_ids):
        raise InventoryReconciliationError(
            "every reviewed row requires an exact ROM assignment"
        )
    checked_errors = tuple(
        error for error in report.errors if any(row_id in error for row_id in row_ids)
    )
    expected_source = (
        sum(len(row["source_sites"]) for row in writers.rows)
        + len(scenes.rows)
        + sum(len(row["source_sites"]) for row in mutations.rows)
    )
    expected_machine = sum(len(row.get("machine_sites", ())) for row in rows)
    if checked_errors:
        raise InventoryReconciliationError("\n".join(checked_errors))
    if len(report.matched_source_sites) != expected_source:
        raise InventoryReconciliationError("reviewed source rows did not all match")
    if len(report.matched_machine_sites) != expected_machine:
        raise InventoryReconciliationError("reviewed machine rows did not all match")

    pending = {
        "diagnostics": len(projected_source.errors),
        "errors": len(report.errors),
        "rom_candidates": len(projected_rom.candidate_findings),
        "rom_findings": len(projected_rom.findings) - len(rom_rows),
        "source_findings": len(projected_source.findings) - len(source_rows),
        "unresolved": len(projected_rom.unresolved_destinations)
        + len(projected_rom.unresolved_control_flow),
    }
    return {
        "assigned": {
            "rom_count": len(rom_rows),
            "rom_row_ids": list(rom_rows),
            "source_count": len(source_rows),
            "source_row_ids": list(source_rows),
        },
        "closed": report.closed and not any(pending.values()),
        "hashes": {
            "assignments_sha256": assignments.sha256,
            "map_sha256": projected_rom.map_sha256,
            "mutations_sha256": mutations.sha256,
            "rom_sha256": projected_rom.rom_sha256,
            "scenes_sha256": scenes.sha256,
            "source_sha256": projected_source.source_sha256,
            "sym_sha256": projected_rom.sym_sha256,
            "writers_sha256": writers.sha256,
        },
        "matched": {
            "machine_count": len(report.matched_machine_sites),
            "machine_row_ids": list(row_ids),
            "source_count": len(report.matched_source_sites),
            "source_row_ids": list(row_ids),
        },
        "pending": pending,
        "reviewed_rows": {
            "mutation_count": len(mutations.rows),
            "row_ids": list(row_ids),
            "scene_count": len(scenes.rows),
            "total_count": len(rows),
            "writer_count": len(writers.rows),
        },
        "schema": PROGRESS_SCHEMA,
    }


def baseline_inventory_progress(repository: str | Path = ".") -> dict[str, Any]:
    root = Path(repository)
    authority = root / "specs/full-colors/inventory"
    writers = WriterInventory.load(authority / "writers.json")
    scenes = SceneInventory.load(authority / "scenes.json")
    mutations = MutationInventory.load(authority / "mutations.json")
    assignments = DiscoveryAssignmentAuthority.load(authority / "assignments.json")
    source_report = discover_baseline_sources(root)
    rom_report = discover_baseline_rom(root, source_report=source_report)
    return build_progress(
        writers=writers,
        scenes=scenes,
        mutations=mutations,
        assignments=assignments,
        source_report=source_report,
        rom_report=rom_report,
        rom=(root / "pokeyellow_debug.gbc").read_bytes(),
    )


def progress_json(repository: str | Path = ".") -> str:
    return (
        json.dumps(
            baseline_inventory_progress(repository),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report Gate 0 inventory progress.")
    parser.add_argument("--repository", default=".")
    args = parser.parse_args(argv)
    print(progress_json(args.repository), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
