"""Rebind mechanically changed evidence identities through official serializers."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from . import source_transition
from .baseline_discovery import discover_baseline_sources
from .discovery_assignment import (
    DiscoveryAssignmentAuthority,
    NORMAL_DEBUG_PRODUCT,
    PHASE2_AUDIT_PRODUCT,
)
from .inventory import MutationInventory, SceneInventory, WriterInventory
from .rom_discovery import load_map


AUDIT_ROM_SHA256 = "40b0a702c94ebddeb3fd26202c10a60b6dd00b66a392da7ab9598d61c092dcd6"
REVIEWED_SOURCE_SHA256 = (
    "9b12281f62023dbd80e64ed17d684aaae5754d787166163f213fe21e4ca2ff7f"
)
BASELINE_MANIFEST_SHA256 = (
    "75c058f0d0df07a25918c710dc8ddebf43d3e5b809a06faaf7391cf015a9d774"
)
NORMAL_DEBUG_ARTIFACTS = {
    "rom_sha256": Path("pokeyellow_debug.gbc"),
    "map_sha256": Path("pokeyellow_debug.map"),
    "sym_sha256": Path("pokeyellow_debug.sym"),
}
NORMAL_DEBUG_ASSIGNMENT_IDS = frozenset(
    {
        "AS-MU-YELLOW-MAP-VIEW-INITIAL-ROM",
        "AS-MU-YELLOW-MAP-VIEW-INITIAL-SOURCE",
        "AS-SC-YELLOW-MAP-ENTRY-ROM",
        "AS-SC-YELLOW-MAP-ENTRY-SOURCE",
        "AS-WR-YELLOW-LCDC-DISABLE-ROM",
        "AS-WR-YELLOW-LCDC-DISABLE-SOURCE",
        "AS-WR-YELLOW-MAP-VIEW-TILE-COPY-ROM",
        "AS-WR-YELLOW-MAP-VIEW-TILE-COPY-SOURCE",
    }
)
NORMAL_DEBUG_INVENTORY_IDS = {
    "mutations.json": frozenset({"MU-YELLOW-MAP-VIEW-INITIAL"}),
    "scenes.json": frozenset({"SC-YELLOW-MAP-ENTRY"}),
    "writers.json": frozenset(
        {"WR-YELLOW-LCDC-DISABLE", "WR-YELLOW-MAP-VIEW-TILE-COPY"}
    ),
}
TRANSITION_PATH = Path(
    "specs/full-colors/definitions/phase1-audit-source-transition.json"
)
DOCUMENTS = {
    Path("specs/full-colors/inventory/assignments.json"): DiscoveryAssignmentAuthority,
    Path("specs/full-colors/inventory/mutations.json"): MutationInventory,
    Path("specs/full-colors/inventory/scenes.json"): SceneInventory,
    Path("specs/full-colors/inventory/writers.json"): WriterInventory,
}


class AuditEvidenceIdentityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise AuditEvidenceIdentityError(f"required build artifact is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normal_debug_hashes(root: Path, source_sha256: str) -> dict[str, str]:
    hashes = {
        "source_sha256": source_sha256,
        **{
            name: _sha256(root / relative)
            for name, relative in NORMAL_DEBUG_ARTIFACTS.items()
            if name != "map_sha256"
        },
    }
    map_path = root / NORMAL_DEBUG_ARTIFACTS["map_sha256"]
    if not map_path.is_file():
        raise AuditEvidenceIdentityError(
            f"required build artifact is missing: {map_path}"
        )
    hashes["map_sha256"] = load_map(map_path).artifact_sha256
    return hashes


def _updated_assignments(
    authority: DiscoveryAssignmentAuthority,
    source_sha256: str,
    normal_hashes: dict[str, str],
) -> DiscoveryAssignmentAuthority:
    normal = tuple(row for row in authority.rows if row.product == NORMAL_DEBUG_PRODUCT)
    normal_ids = frozenset(row.id for row in normal)
    if normal_ids != NORMAL_DEBUG_ASSIGNMENT_IDS or len(normal) != len(
        NORMAL_DEBUG_ASSIGNMENT_IDS
    ):
        raise AuditEvidenceIdentityError(
            "normal-debug assignment scope changed: expected the eight reviewed "
            "initial-map-entry assignments"
        )
    audit = tuple(row for row in authority.rows if row.product == PHASE2_AUDIT_PRODUCT)
    if not audit:
        raise AuditEvidenceIdentityError("Phase 2 audit assignment scope is empty")
    if any(row.evidence.rom_sha256 != AUDIT_ROM_SHA256 for row in audit):
        raise AuditEvidenceIdentityError("Phase 2 audit assignment ROM authority changed")

    rows = []
    for row in authority.rows:
        if row.product == NORMAL_DEBUG_PRODUCT:
            evidence = replace(row.evidence, **normal_hashes)
        elif row.product == PHASE2_AUDIT_PRODUCT:
            evidence = replace(row.evidence, source_sha256=source_sha256)
        else:  # The model rejects this too; retain an explicit producer scope guard.
            raise AuditEvidenceIdentityError(
                f"assignment product is outside producer scope: {row.product!r}"
            )
        rows.append(replace(row, evidence=evidence))
    return DiscoveryAssignmentAuthority(tuple(rows))


def _assert_assignment_delta(
    before: DiscoveryAssignmentAuthority, after: DiscoveryAssignmentAuthority
) -> None:
    if len(before.rows) != len(after.rows):
        raise AuditEvidenceIdentityError("assignment row count changed during rebinding")
    for old, new in zip(before.rows, after.rows, strict=True):
        old_dict = old.to_dict()
        new_dict = new.to_dict()
        old_evidence = old_dict.pop("evidence")
        new_evidence = new_dict.pop("evidence")
        if old_dict != new_dict:
            raise AuditEvidenceIdentityError(
                f"assignment semantic or ID drift during rebinding: {old.id}"
            )
        allowed = (
            {"source_sha256", "rom_sha256", "map_sha256", "sym_sha256"}
            if old.product == NORMAL_DEBUG_PRODUCT
            else {"source_sha256"}
        )
        for key in set(old_evidence) | set(new_evidence):
            if key not in allowed and old_evidence.get(key) != new_evidence.get(key):
                raise AuditEvidenceIdentityError(
                    f"assignment reviewed semantics changed during rebinding: {old.id}"
                )


def _updated_document(
    relative: Path,
    raw: dict[str, Any],
    source_sha256: str,
    normal_hashes: dict[str, str],
) -> Any:
    normal_ids = NORMAL_DEBUG_INVENTORY_IDS.get(relative.name, frozenset())
    found_normal_ids = frozenset(
        row.get("id") for row in raw["rows"] if row.get("id") in normal_ids
    )
    if found_normal_ids != normal_ids:
        raise AuditEvidenceIdentityError(
            f"normal-debug inventory scope changed: {relative.name}"
        )
    for row in raw["rows"]:
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            continue
        if row.get("id") in normal_ids:
            evidence.update(normal_hashes)
            continue
        is_audit = (
            row.get("product") == "pokeyellow_phase2_audit"
            if relative.name == "assignments.json"
            else evidence.get("rom_sha256") == AUDIT_ROM_SHA256
        )
        if not is_audit:
            continue
        if evidence.get("rom_sha256") != AUDIT_ROM_SHA256:
            raise AuditEvidenceIdentityError(
                f"audit row has changed ROM authority: {row.get('id')}"
            )
        evidence["source_sha256"] = source_sha256
    return raw


def update(root: Path) -> None:
    transition_path = root / TRANSITION_PATH
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    if set(transition) != {
        "schema",
        "reviewed_source_sha256",
        "audit_source_sha256",
        "baseline_manifest_sha256",
        "audit_only_paths",
        "subject_rebindings",
        "rom_subject_rebindings",
    } or transition["schema"] != source_transition.SCHEMA:
        raise AuditEvidenceIdentityError("source-transition authority is malformed")
    source_sha256 = transition["audit_source_sha256"]
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise AuditEvidenceIdentityError(
            "source-transition audit identity is not a lowercase SHA-256"
        )
    current_source_sha256 = discover_baseline_sources(root).source_sha256
    if source_sha256 != current_source_sha256:
        raise AuditEvidenceIdentityError(
            "source-transition audit identity does not match current baseline discovery"
        )
    try:
        canonical_transition = source_transition.generate(
            root, authority_path=transition_path
        )
    except source_transition.SourceTransitionError as exc:
        raise AuditEvidenceIdentityError(
            "source-transition authority failed canonical recomputation"
        ) from exc
    canonical_transition["reviewed_source_sha256"] = REVIEWED_SOURCE_SHA256
    canonical_transition["baseline_manifest_sha256"] = BASELINE_MANIFEST_SHA256
    if transition != canonical_transition:
        raise AuditEvidenceIdentityError(
            "source-transition authority does not match canonical recomputation"
        )
    normal_hashes = _normal_debug_hashes(root, source_sha256)
    rendered: dict[Path, str] = {}
    for relative, document_type in DOCUMENTS.items():
        path = root / relative
        raw = json.loads(path.read_text(encoding="utf-8"))
        if relative.name == "assignments.json":
            before = DiscoveryAssignmentAuthority.from_dict(raw)
            document = _updated_assignments(before, source_sha256, normal_hashes)
            _assert_assignment_delta(before, document)
        else:
            document = document_type.from_dict(
                _updated_document(relative, raw, source_sha256, normal_hashes)
            )
        rendered[path] = document.to_json()
    for path, content in rendered.items():
        path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        update(args.root)
    except (OSError, ValueError, AuditEvidenceIdentityError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
