"""Deterministic progress report for the reviewed baseline inventory tranche."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any, Sequence

from .baseline_discovery import discover_baseline_rom, discover_baseline_sources
from .discovery_assignment import (
    DiscoveryAssignmentAuthority,
    NORMAL_DEBUG_PRODUCT,
    PHASE2_AUDIT_PRODUCT,
    StaleDiscoveryAssignmentError,
)
from .discovery_review import rom_finding_subject, source_error_subject, source_finding_subject
from .inventory import (
    InventoryReconciliationError,
    MutationInventory,
    SceneInventory,
    WriterInventory,
    reconcile,
)

PROGRESS_SCHEMA = "full-color-inventory-progress-v2"
REVIEWED_SLICE = "initial-map-entry-v1"

_OWNER_GATED_ROM_RESOURCES = frozenset(
    {
        "BG_WINDOW_MAP",
        "CGB_PALETTE",
        "DISPLAY_REGISTER",
        "HARDWARE_OAM",
        "HDMA_GDMA",
        "OAM_DMA_CONTROL",
        "SHADOW_OAM",
        "VRAM_BANK",
        "WRAM_BANK",
    }
)

SOURCE_TRANSITION_PATH = Path(
    "specs/full-colors/definitions/phase1-audit-source-transition.json"
)
ACTIVATION_TRANSITION_PATH = Path(
    "specs/full-colors/definitions/phase2-activation-source-transition.json"
)

PHASE2_PLANNED_ROW_IDS = frozenset(
    {
        "MU-P2-ANIMATED-TERRAIN",
        "MU-P2-DIALOGUE-OVERLAY",
        "MU-P2-MAP-CONNECTION-NORTH",
        "MU-P2-MAP-RECONSTRUCTION",
        "MU-P2-MOVEMENT-HORIZONTAL",
        "MU-P2-MOVEMENT-VERTICAL",
        "MU-P2-OAM-FOLLOWER-NPC",
        "MU-P2-PALETTE-PAYLOADS",
        "MU-P2-START-MENU-OVERLAY",
        "SC-P2-PALLET-ROUTE1-NORTH",
        "SC-P2-PARTY-ENTRY",
        "SC-P2-PARTY-RETURN",
        "WR-P2-YELLOW-ANIMATION-TILES",
        "WR-P2-YELLOW-BG-PALETTE",
        "WR-P2-YELLOW-MAP-STREAM",
        "WR-P2-YELLOW-OAM-BUILD",
        "WR-P2-YELLOW-OAM-DMA",
        "WR-P2-YELLOW-OVERLAY-TRANSFER",
    }
)

_PLANNED_ONLY_ROW_CONTRACTS = {
    "WR-P2-YELLOW-BG-PALETTE": {
        "commit_unit": "PALETTE",
        "machine_sites": (
            {
                "bank": 0,
                "address": 0x3E14,
                "rom_offset": 0x3E14,
                "bytes": "fa1acf",
                "runtime_copy": None,
            },
        ),
        "resources": (
            {
                "aliases": [],
                "end": 0xFF69,
                "resource": "CGB_PALETTE",
                "start": 0xFF68,
                "vram_bank": None,
            },
        ),
        "root": "RunPaletteCommand",
        "source_sites": (
            {
                "aliases": [],
                "line": 47,
                "object": None,
                "path": "home/palettes.asm",
                "symbol": "RunPaletteCommand",
            },
        ),
    },
}


def _source_path_manifest(repository: Path, paths: Sequence[str]) -> dict[str, str]:
    return {
        relative: hashlib.sha256((repository / relative).read_bytes()).hexdigest()
        for relative in sorted(paths)
    }


def _manifest_sha256(manifest: dict[str, str]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _transition_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise InventoryReconciliationError("malformed audit-only transition path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != str(path) or "\\" in value or ".." in path.parts:
        raise InventoryReconciliationError(
            f"audit-only transition path is not normalized repository-relative: {value!r}"
        )
    return value


def _sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _symbol_names(path: Path) -> frozenset[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InventoryReconciliationError(
            f"activation product authority is unavailable: {path.name}"
        ) from exc
    return frozenset(
        fields[1]
        for line in lines
        if len(fields := line.split(maxsplit=1)) == 2 and ":" in fields[0]
    )


def _validate_activation_transition(
    repository: Path,
    source_report: Any,
    guarded_source_sha256: str,
    current_manifest: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Project one reviewed debug-only activation back to guarded closure."""
    path = repository / ACTIVATION_TRANSITION_PATH
    try:
        transition = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_json_object
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise InventoryReconciliationError(
            "guarded audit closure changed without a valid activation transition"
        ) from exc
    expected_keys = {
        "schema", "baseline_commit", "guarded_commit", "guarded_source_sha256",
        "activated_source_sha256", "audit_rom_sha256", "audit_sym_sha256",
        "activation_paths", "guarded_debug_identity", "activated_debug_identity",
        "guarded_path_manifest_sha256", "guarded_product_input_sha256",
        "activated_product_input_sha256",
        "debug_rom_subject_rebindings", "debug_source_subject_rebindings",
        "audit_source_subject_rebindings", "audit_source_error_rebindings",
        "activated_placement_sections", "product_guard",
    }
    if set(transition) != expected_keys or transition["schema"] != (
        "full-color-phase2-activation-source-transition-v1"
    ):
        raise InventoryReconciliationError("malformed Phase 2 activation transition")
    if transition["guarded_source_sha256"] != guarded_source_sha256:
        raise InventoryReconciliationError(
            "activation transition does not bind guarded source identity"
        )
    if transition["activated_source_sha256"] != source_report.source_sha256:
        raise InventoryReconciliationError(
            "activation transition does not bind current source identity"
        )
    baseline_commit = transition["baseline_commit"]
    commit = transition["guarded_commit"]
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
        for value in (baseline_commit, commit)
    ):
        raise InventoryReconciliationError("malformed guarded checkpoint identity")
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", baseline_commit, commit],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryReconciliationError(
            "activation transition has wrong baseline or guarded parent"
        ) from exc

    bindings = transition["activation_paths"]
    if not isinstance(bindings, dict) or not bindings:
        raise InventoryReconciliationError("activation transition has no reviewed path delta")
    guarded_manifest = dict(current_manifest)
    for relative, binding in bindings.items():
        relative = _transition_path(relative)
        if set(binding) != {"guarded_sha256", "activated_sha256"}:
            raise InventoryReconciliationError(
                f"malformed activation path binding: {relative}"
            )
        guarded = binding["guarded_sha256"]
        activated = binding["activated_sha256"]
        if not _sha256_text(guarded) or not _sha256_text(activated):
            raise InventoryReconciliationError(
                f"malformed activation path hash: {relative}"
            )
        if guarded == activated:
            raise InventoryReconciliationError(
                f"activation path has no actual delta: {relative}"
            )
        if current_manifest.get(relative) != activated:
            raise InventoryReconciliationError(f"activation path changed: {relative}")
        try:
            guarded_bytes = subprocess.run(
                ["git", "show", f"{commit}:{relative}"],
                cwd=repository,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise InventoryReconciliationError(
                f"activation transition has stale guarded checkpoint: {commit}"
            ) from exc
        if hashlib.sha256(guarded_bytes).hexdigest() != guarded:
            raise InventoryReconciliationError(
                f"activation path does not bind guarded checkpoint: {relative}"
            )
        guarded_manifest[relative] = guarded

    guarded_manifest_sha256 = transition["guarded_path_manifest_sha256"]
    if (
        not _sha256_text(guarded_manifest_sha256)
        or _manifest_sha256(guarded_manifest) != guarded_manifest_sha256
    ):
        raise InventoryReconciliationError(
            "activation source drift exists outside the exact reviewed path delta"
        )

    for key, artifact in (
        ("audit_rom_sha256", "pokeyellow_phase2_audit.gbc"),
        ("audit_sym_sha256", "pokeyellow_phase2_audit.sym"),
    ):
        expected = transition[key]
        if not _sha256_text(expected):
            raise InventoryReconciliationError("malformed guarded audit artifact identity")
        try:
            actual = hashlib.sha256((repository / artifact).read_bytes()).hexdigest()
        except OSError as exc:
            raise InventoryReconciliationError(
                f"guarded audit artifact is unavailable: {artifact}"
            ) from exc
        if actual != expected:
            raise InventoryReconciliationError(
                f"guarded audit artifact identity changed: {artifact}"
            )

    rom_bindings = transition["debug_rom_subject_rebindings"]
    if (
        not isinstance(rom_bindings, dict)
        or not rom_bindings
        or any(
            not _sha256_text(guarded)
            or not _sha256_text(activated)
            or guarded == activated
            for guarded, activated in rom_bindings.items()
        )
        or len(set(rom_bindings.values())) != len(rom_bindings)
    ):
        raise InventoryReconciliationError(
            "malformed activation debug ROM subject bindings"
        )
    source_bindings = transition["audit_source_subject_rebindings"]
    activated_source_subjects = tuple(
        activated
        for value in source_bindings.values()
        for activated in (value if isinstance(value, list) else (value,))
    ) if isinstance(source_bindings, dict) else ()
    if (
        not isinstance(source_bindings, dict)
        or not source_bindings
        or any(not _sha256_text(guarded) for guarded in source_bindings)
        or any(
            not isinstance(value, (str, list))
            or isinstance(value, list) and not value
            for value in source_bindings.values()
        )
        or any(not _sha256_text(activated) for activated in activated_source_subjects)
    ):
        raise InventoryReconciliationError(
            "malformed activation audit source subject bindings"
        )
    debug_source_bindings = transition["debug_source_subject_rebindings"]
    try:
        guarded_transition = json.loads(
            (repository / SOURCE_TRANSITION_PATH).read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise InventoryReconciliationError(
            "activation debug source bindings lack guarded authority"
        ) from exc
    current_subjects = {
        source_finding_subject(finding).sha256 for finding in source_report.findings
    }
    guarded_targets = set(guarded_transition.get("subject_rebindings", {}).values())
    missing_guarded_targets = guarded_targets - current_subjects
    if (
        not isinstance(debug_source_bindings, dict)
        or set(debug_source_bindings) != missing_guarded_targets
        or any(
            not _sha256_text(guarded)
            or not _sha256_text(activated)
            or guarded == activated
            or activated not in current_subjects
            for guarded, activated in debug_source_bindings.items()
        )
        or len(set(debug_source_bindings.values())) != len(debug_source_bindings)
    ):
        raise InventoryReconciliationError(
            "malformed activation debug source subject bindings"
        )
    error_bindings = transition["audit_source_error_rebindings"]
    current_errors = {
        source_error_subject(message).sha256: message
        for message in source_report.errors
    }
    if (
        not isinstance(error_bindings, dict)
        or not error_bindings
        or any(
            not _sha256_text(guarded)
            or not isinstance(binding, dict)
            or set(binding) != {"activated_sha256", "guarded_message"}
            or not _sha256_text(binding.get("activated_sha256"))
            or not isinstance(binding.get("guarded_message"), str)
            or source_error_subject(binding.get("guarded_message", "")).sha256
            != guarded
            or binding.get("activated_sha256") not in current_errors
            or guarded in current_errors
            for guarded, binding in error_bindings.items()
        )
        or len({
            binding["activated_sha256"] for binding in error_bindings.values()
            if isinstance(binding, dict) and "activated_sha256" in binding
        }) != len(error_bindings)
    ):
        raise InventoryReconciliationError(
            "malformed activation audit source diagnostic bindings"
        )
    for name in ("guarded_debug_identity", "activated_debug_identity"):
        identity = transition[name]
        if (
            not isinstance(identity, dict)
            or set(identity) != {"rom_sha256", "sym_sha256", "map_sha256"}
            or any(not _sha256_text(value) for value in identity.values())
        ):
            raise InventoryReconciliationError(
                f"malformed activation {name.replace('_', ' ')}"
            )
    product_names = {
        f"pokeyellow{suffix}.{extension}"
        for suffix in ("", "_debug", "_vc")
        for extension in ("gbc", "map", "sym")
    }
    guarded_inputs = transition["guarded_product_input_sha256"]
    activated_inputs = transition["activated_product_input_sha256"]
    if (
        not isinstance(guarded_inputs, dict)
        or not isinstance(activated_inputs, dict)
        or set(guarded_inputs) != product_names
        or set(activated_inputs) != product_names
        or any(not _sha256_text(value) for value in guarded_inputs.values())
        or any(not _sha256_text(value) for value in activated_inputs.values())
        or any(guarded_inputs[name] == activated_inputs[name] for name in product_names)
    ):
        raise InventoryReconciliationError("malformed frozen product input projection")
    for name in product_names:
        try:
            actual = hashlib.sha256((repository / name).read_bytes()).hexdigest()
        except OSError as exc:
            raise InventoryReconciliationError(
                f"activation product input is unavailable: {name}"
            ) from exc
        if actual != activated_inputs[name]:
            raise InventoryReconciliationError(
                f"activation product input changed: {name}"
            )
    placements = transition["activated_placement_sections"]
    expected_placements = [
        {
            "kind": "ROMX", "bank": 59, "start": 0x452B, "end": 0x552A,
            "name": "Full Color Phase 2 Pipelines",
            "products": ["release", "debug", "vc"],
        },
        {
            "kind": "WRAMX", "bank": 2, "start": 0xD00D, "end": 0xD3D4,
            "name": "Full Color Phase 2 State",
            "products": ["debug"],
        },
        {
            "kind": "SRAM", "bank": 3, "start": 0xBEAF, "end": 0xBFCE,
            "name": "Full Color Phase 2 Runtime Carrier", "products": ["debug"],
        },
    ]
    if placements != expected_placements:
        raise InventoryReconciliationError("malformed activated placement authority")

    guard = transition["product_guard"]
    if not isinstance(guard, dict) or set(guard) != {"active", "inactive"}:
        raise InventoryReconciliationError("malformed activation product guard")
    active = guard["active"]
    inactive = guard["inactive"]
    if set(active) != {"pokeyellow_debug.sym", "pokeyellow_phase2_audit.sym"} or set(
        inactive
    ) != {"pokeyellow.sym", "pokeyellow_vc.sym"}:
        raise InventoryReconciliationError("activation product guard has widened products")
    required = set(active["pokeyellow_debug.sym"])
    if not required or required != set(active["pokeyellow_phase2_audit.sym"]):
        raise InventoryReconciliationError("activation product guard is not one exact surface")
    if any(not isinstance(symbol, str) or not symbol for symbol in required):
        raise InventoryReconciliationError("activation product guard has malformed symbols")
    for product in active:
        if not required <= _symbol_names(repository / product):
            raise InventoryReconciliationError(
                f"activation product lacks reviewed guarded surface: {product}"
            )
    for product, forbidden in inactive.items():
        if set(forbidden) != required:
            raise InventoryReconciliationError(
                "inactive product guard does not forbid the exact activation surface"
            )
        if required & _symbol_names(repository / product):
            raise InventoryReconciliationError(
                f"activation surface widened into inactive product: {product}"
            )
    return guarded_manifest, transition


def _reviewed_source_view(
    assignments: DiscoveryAssignmentAuthority,
    source_report: Any,
    repository: Path,
) -> tuple[Any, dict[str, Any] | None]:
    """Verify and apply the explicit audit-only source-hash transition."""
    assignments = assignments.for_product(NORMAL_DEBUG_PRODUCT)
    reviewed_hashes = {row.evidence.source_sha256 for row in assignments.rows}
    if len(reviewed_hashes) != 1:
        raise StaleDiscoveryAssignmentError(
            "assignment rows have stale baseline evidence: mixed source hashes"
        )
    reviewed_hash = next(iter(reviewed_hashes))
    if source_report.source_sha256 == reviewed_hash:
        return source_report, None
    path = repository / SOURCE_TRANSITION_PATH
    try:
        transition = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_json_object
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise InventoryReconciliationError(
            "reviewed source hash changed without a valid audit-only transition"
        ) from exc
    expected_keys = {
        "schema", "reviewed_source_sha256", "audit_source_sha256",
        "baseline_manifest_sha256", "audit_only_paths", "subject_rebindings",
        "rom_subject_rebindings",
    }
    if set(transition) != expected_keys or transition["schema"] != (
        "full-color-phase1-audit-source-transition-v2"
    ):
        raise InventoryReconciliationError("malformed audit-only source transition")
    if transition["reviewed_source_sha256"] != reviewed_hash:
        raise InventoryReconciliationError("audit transition does not bind reviewed source hash")
    current_manifest = _source_path_manifest(
        repository, (path for path, _ in source_report.include_graph)
    )
    effective_source_sha256 = source_report.source_sha256
    activation_transition = None
    if transition["audit_source_sha256"] != effective_source_sha256:
        current_manifest, activation_transition = _validate_activation_transition(
            repository,
            source_report,
            transition["audit_source_sha256"],
            current_manifest,
        )
        effective_source_sha256 = transition["audit_source_sha256"]
    if transition["audit_source_sha256"] != effective_source_sha256:
        raise InventoryReconciliationError("audit transition does not bind current source hash")
    baseline_manifest = dict(current_manifest)
    for relative, binding in transition["audit_only_paths"].items():
        relative = _transition_path(relative)
        if set(binding) != {"reviewed_sha256", "audit_sha256"}:
            raise InventoryReconciliationError(
                f"malformed audit-only transition path binding: {relative}"
            )
        actual = current_manifest.get(relative)
        audit = binding["audit_sha256"]
        if not _sha256_text(audit):
            raise InventoryReconciliationError(
                f"malformed audit path hash: {relative}"
            )
        if actual != audit:
            raise InventoryReconciliationError(
                f"audit-only transition path changed: {relative}"
            )
        reviewed = binding["reviewed_sha256"]
        if reviewed is None:
            if not (repository / relative).is_file():
                raise InventoryReconciliationError(
                    f"audit-only transition contains phantom added path: {relative}"
                )
            baseline_manifest.pop(relative, None)
        elif _sha256_text(reviewed):
            if reviewed == audit:
                raise InventoryReconciliationError(
                    f"audit-only transition path has no actual delta: {relative}"
                )
            baseline_manifest[relative] = reviewed
        else:
            raise InventoryReconciliationError(
                f"malformed reviewed path hash: {relative}"
            )
    if _manifest_sha256(baseline_manifest) != transition["baseline_manifest_sha256"]:
        raise InventoryReconciliationError(
            "current source changed outside the hash-bound audit-only change set"
        )
    source_rows = {
        row.subject.sha256: row
        for row in assignments.rows
        if row.subject.kind.value == "SOURCE_FINDING"
    }
    current_by_subject = {
        source_finding_subject(finding).sha256: finding
        for finding in source_report.findings
    }
    activation_source_bindings = (
        activation_transition["debug_source_subject_rebindings"]
        if activation_transition is not None else {}
    )
    if set(transition["subject_rebindings"]) != set(source_rows):
        raise InventoryReconciliationError(
            "audit-only transition does not enumerate reviewed semantic subjects"
        )
    translated: dict[str, Any] = {}
    for old_sha, new_sha in transition["subject_rebindings"].items():
        activated_sha = activation_source_bindings.get(new_sha, new_sha)
        finding = current_by_subject.get(activated_sha)
        row = source_rows[old_sha]
        if finding is None:
            raise InventoryReconciliationError(
                f"audit-only transition target subject is absent: {activated_sha}"
            )
        rebound = (
            type(finding)(**row.subject.metadata)
            if activated_sha != new_sha
            else replace(finding, symbol=row.subject.metadata["symbol"])
        )
        if source_finding_subject(rebound) != row.subject:
            raise InventoryReconciliationError(
                f"audit-only transition changes reviewed subject semantics: {old_sha}"
            )
        translated[activated_sha] = rebound
    findings = tuple(
        translated.get(source_finding_subject(finding).sha256, finding)
        for finding in source_report.findings
    )
    if activation_transition is not None:
        transition = dict(transition)
        transition["_activation_transition"] = activation_transition
    return replace(source_report, findings=findings, source_sha256=reviewed_hash), transition


def _reviewed_rom_view(
    assignments: DiscoveryAssignmentAuthority,
    rom_report: Any,
    transition: dict[str, Any] | None,
) -> Any:
    assignments = assignments.for_product(NORMAL_DEBUG_PRODUCT)
    if transition is None:
        return rom_report
    rows = {
        row.subject.sha256: row
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
    }
    current = {
        rom_finding_subject(finding).sha256: finding for finding in rom_report.findings
    }
    activation = transition.get("_activation_transition")
    activation_bindings = (
        None if activation is None else activation["debug_rom_subject_rebindings"]
    )
    activation_translated: dict[str, Any] = {}
    if activation_bindings is not None:
        guarded_subjects = set(transition["rom_subject_rebindings"].values())
        if not activation_bindings or not set(activation_bindings) <= guarded_subjects:
            raise InventoryReconciliationError(
                "activation transition names an unknown guarded debug ROM subject"
            )
        rebound_current: dict[str, Any] = {}
        for guarded_sha, activated_sha in activation_bindings.items():
            if guarded_sha == activated_sha:
                raise InventoryReconciliationError(
                    "activation debug ROM subject binding has no actual delta"
                )
            finding = current.get(activated_sha)
            if finding is None:
                raise InventoryReconciliationError(
                    f"activation debug ROM target subject is absent: {activated_sha}"
                )
            old_sha = next(
                old
                for old, guarded in transition["rom_subject_rebindings"].items()
                if guarded == guarded_sha
            )
            row = rows[old_sha]
            rebound = type(finding)(**row.subject.metadata)
            if rom_finding_subject(rebound) != row.subject:
                raise InventoryReconciliationError(
                    f"activation changes reviewed debug ROM semantics: {guarded_sha}"
                )
            rebound_current[guarded_sha] = rebound
            activation_translated[activated_sha] = rebound
        current.update(rebound_current)
    bindings = transition["rom_subject_rebindings"]
    if set(bindings) != set(rows):
        raise InventoryReconciliationError(
            "audit-only transition does not enumerate reviewed ROM subjects"
        )
    translated: dict[str, Any] = {}
    for old_sha, new_sha in bindings.items():
        finding = current.get(new_sha)
        row = rows[old_sha]
        if finding is None:
            raise InventoryReconciliationError(
                f"audit-only transition ROM target subject is absent: {new_sha}"
            )
        rebound = replace(
            finding,
            root=row.subject.metadata["root"],
            call_path=tuple(row.subject.metadata["call_path"]),
        )
        if rom_finding_subject(rebound) != row.subject:
            raise InventoryReconciliationError(
                f"audit-only transition changes reviewed ROM semantics: {old_sha}"
            )
        translated[new_sha] = rebound
    def project(findings: Sequence[Any]) -> tuple[Any, ...]:
        result = []
        for finding in findings:
            finding = activation_translated.get(
                rom_finding_subject(finding).sha256, finding
            )
            finding = translated.get(rom_finding_subject(finding).sha256, finding)
            result.append(finding)
        return tuple(result)

    projected = replace(
        rom_report,
        findings=project(rom_report.findings),
        candidate_findings=project(rom_report.candidate_findings),
    )
    if activation is not None:
        actual_identity = {
            "rom_sha256": rom_report.rom_sha256,
            "sym_sha256": rom_report.sym_sha256,
            "map_sha256": rom_report.map_sha256,
        }
        if actual_identity != activation["activated_debug_identity"]:
            raise InventoryReconciliationError(
                "activation transition does not bind current debug product identity"
            )
        projected = replace(projected, **activation["guarded_debug_identity"])
    return projected


def _reviewed_rom_bytes(
    assignments: DiscoveryAssignmentAuthority,
    rom_report: Any,
    transition: dict[str, Any] | None,
    rom: bytes,
) -> bytes:
    """Project only reviewed activation-shifted machine bytes to guarded sites."""
    if transition is None or "_activation_transition" not in transition:
        return rom
    activation = transition["_activation_transition"]
    current = {
        rom_finding_subject(finding).sha256: finding
        for finding in rom_report.findings
    }
    rows = {
        row.subject.sha256: row
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
    }
    projected = bytearray(rom)
    guarded_bindings = transition["rom_subject_rebindings"]
    for guarded_sha, activated_sha in activation[
        "debug_rom_subject_rebindings"
    ].items():
        finding = current.get(activated_sha)
        if finding is None:
            raise InventoryReconciliationError(
                f"activation debug ROM byte source is absent: {activated_sha}"
            )
        old_sha = next(
            old for old, guarded in guarded_bindings.items() if guarded == guarded_sha
        )
        metadata = rows[old_sha].subject.metadata
        expected = bytes.fromhex(metadata["bytes"])
        actual = rom[finding.rom_offset : finding.rom_offset + len(expected)]
        if actual != expected:
            raise InventoryReconciliationError(
                f"activation debug ROM subject bytes changed: {activated_sha}"
            )
        target = metadata["rom_offset"]
        projected[target : target + len(expected)] = actual
    return bytes(projected)


def _partition_authority(document: Any) -> tuple[Any, tuple[dict[str, Any], ...]]:
    """Return a revalidated frozen tranche plus declared planned rows."""
    reviewed = tuple(row for row in document.rows if not row["planned"])
    planned = tuple(row for row in document.rows if row["planned"])
    reviewed_document = type(document).from_dict(
        {"schema": document.schema, "rows": list(reviewed)}
    )
    return reviewed_document, planned


def _select_inventory_rows(document: Any, row_ids: set[str]) -> Any:
    """Select only rows owned by one link-product assignment partition."""
    return type(document).from_dict(
        {
            "schema": document.schema,
            "rows": [row for row in document.rows if row["id"] in row_ids],
        }
    )


def _phase2_transition_state(
    *,
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
    assignments: DiscoveryAssignmentAuthority,
) -> str:
    """Require the hostile tranche to be wholly planned or wholly audit-closed."""
    rows = {
        row["id"]: row
        for document in (writers, scenes, mutations)
        for row in document.rows
        if row["id"] in PHASE2_PLANNED_ROW_IDS
    }
    if set(rows) != PHASE2_PLANNED_ROW_IDS:
        raise InventoryReconciliationError(
            "planned Phase 2 row IDs must be the exact closed set; "
            f"missing={sorted(PHASE2_PLANNED_ROW_IDS - set(rows))}"
        )
    audit = assignments.for_product(PHASE2_AUDIT_PRODUCT)
    audit_targets = {row.row_id for row in audit.rows}
    planned = {row_id for row_id, row in rows.items() if row["planned"]}
    reviewed = {
        row_id for row_id, row in rows.items() if row["evidence"]["reviewed"]
    }
    if planned == PHASE2_PLANNED_ROW_IDS and not reviewed and not audit.rows:
        return "planned"
    if planned == PHASE2_PLANNED_ROW_IDS and reviewed:
        raise InventoryReconciliationError(
            "planned row cannot claim reviewed evidence"
        )
    if planned == PHASE2_PLANNED_ROW_IDS and audit.rows:
        raise InventoryReconciliationError(
            "planned hostile rows consume closure assignments"
        )
    if (
        not planned
        and reviewed == PHASE2_PLANNED_ROW_IDS
        and audit_targets == PHASE2_PLANNED_ROW_IDS
    ):
        return "audit-closed"
    raise InventoryReconciliationError(
        "Phase 2 closure must transition all 18 rows atomically from "
        "planned/unreviewed/unassigned to reviewed audit assignments"
    )


def _validate_planned_rows(
    *,
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
    assignments: DiscoveryAssignmentAuthority,
    source_report: Any,
    rom_report: Any,
    rom: bytes,
    repository: Path,
) -> tuple[dict[str, Any], ...]:
    """Validate declarations without promoting them into Gate 0 closure."""
    all_rows = tuple(writers.rows) + tuple(scenes.rows) + tuple(mutations.rows)
    planned = tuple(row for row in all_rows if row["planned"])
    reviewed = tuple(row for row in all_rows if not row["planned"])
    errors: list[str] = []
    assigned_ids = {row.row_id for row in assignments.rows}
    writer_ids = {row["id"] for row in writers.rows}
    current_hashes = {
        "source_sha256": source_report.source_sha256,
        "rom_sha256": rom_report.rom_sha256,
        "sym_sha256": rom_report.sym_sha256,
        "map_sha256": rom_report.map_sha256,
    }
    planned_ids = {row["id"] for row in planned}
    if planned_ids != PHASE2_PLANNED_ROW_IDS:
        errors.append(
            "planned Phase 2 row IDs must be the exact closed set; "
            f"missing={sorted(PHASE2_PLANNED_ROW_IDS - planned_ids)}, "
            f"unexpected={sorted(planned_ids - PHASE2_PLANNED_ROW_IDS)}"
        )
    for row in reviewed:
        if not row["evidence"]["reviewed"]:
            errors.append(f"{row['id']}: frozen reviewed row became unreviewed")
    for row in planned:
        if row["evidence"]["reviewed"]:
            errors.append(f"{row['id']}: planned row cannot claim reviewed evidence")
        if row["id"] in assigned_ids:
            errors.append(f"{row['id']}: planned row cannot consume a closure assignment")
        for name, expected in current_hashes.items():
            if row["evidence"][name] != expected:
                errors.append(f"{row['id']}: stale planned {name.removesuffix('_sha256')} hash")
        declared_sources = (
            (row["source"],)
            if row["id"].startswith("SC-")
            else tuple(row.get("source_sites", ()))
        )
        if not declared_sources:
            errors.append(f"{row['id']}: planned row lacks required source evidence")
        if not row.get("machine_sites"):
            errors.append(f"{row['id']}: planned row lacks required machine evidence")
        for site in row.get("machine_sites", ()):
            expected = bytes.fromhex(site["bytes"])
            start = site["rom_offset"]
            if rom[start : start + len(expected)] != expected:
                errors.append(
                    f"{row['id']}: planned machine bytes do not match "
                    f"{site['bank']:02x}:{site['address']:04x}"
                )
        contract = _PLANNED_ONLY_ROW_CONTRACTS.get(row["id"])
        if contract is not None:
            if tuple(row.get("machine_sites", ())) != contract["machine_sites"]:
                errors.append(f"{row['id']}: planned-only machine-site contract changed")
            if tuple(row.get("source_sites", ())) != contract["source_sites"]:
                errors.append(f"{row['id']}: planned-only source-site contract changed")
            if tuple(row.get("resources", ())) != contract["resources"]:
                errors.append(f"{row['id']}: planned-only resource contract changed")
            if row.get("commit_unit") != contract["commit_unit"]:
                errors.append(f"{row['id']}: planned-only commit contract changed")
            reachability = row.get("reachability", {})
            if (
                reachability.get("roots") != [contract["root"]]
                or reachability.get("call_paths") != [[contract["root"]]]
            ):
                errors.append(f"{row['id']}: planned-only root contract changed")
    for row in scenes.rows:
        missing = sorted(set(row["first_display_writers"]) - writer_ids)
        if missing:
            errors.append(f"{row['id']}: unknown first-display writers {missing}")
    for row in mutations.rows:
        missing = sorted(set(row["writer_ids"]) - writer_ids)
        if missing:
            errors.append(f"{row['id']}: unknown mutation writers {missing}")
    if errors:
        raise InventoryReconciliationError("\n".join(sorted(errors)))
    return planned


def _assert_no_unlisted_slice_findings(
    assignments: DiscoveryAssignmentAuthority,
    source_report: Any,
    rom_report: Any,
) -> None:
    """Fail closed for new subjects within the reviewed map-entry slice."""
    source_subjects = {
        row.subject.sha256
        for row in assignments.rows
        if row.subject.kind.value == "SOURCE_FINDING"
    }
    rom_subjects = {
        row.subject.sha256
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
    }
    reviewed_rom_sites = {
        (row.subject.metadata["bank"], row.subject.metadata["address"])
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
    }
    source_roots = {
        (row.subject.metadata["category"], row.subject.metadata["symbol"])
        for row in assignments.rows
        if row.subject.kind.value == "SOURCE_FINDING"
    }
    source_shapes = {
        (
            row.subject.metadata["category"],
            row.subject.metadata["symbol"],
            row.subject.metadata["mechanism"],
        )
        for row in assignments.rows
        if row.subject.kind.value == "SOURCE_FINDING"
        and row.subject.metadata["category"] != "writer"
    }
    rom_roots = {
        (row.subject.metadata["category"], row.subject.metadata["root"])
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
    }
    rom_shapes = {
        (
            row.subject.metadata["category"],
            row.subject.metadata["root"],
            row.subject.metadata["control_flow_kind"],
        )
        for row in assignments.rows
        if row.subject.kind.value == "ROM_FINDING"
        and row.subject.metadata["category"] != "writer"
    }

    def belongs_to_root(name: str, root: str) -> bool:
        return name == root or name.startswith(root + ".")

    unexpected_source = []
    for finding in source_report.findings:
        if source_finding_subject(finding).sha256 in source_subjects:
            continue
        shape = (finding.category, finding.symbol, finding.mechanism)
        in_slice = shape in source_shapes or any(
            finding.category == category
            and (
                (category == "writer" and belongs_to_root(finding.symbol, root))
                or finding.symbol.startswith(root + ".")
            )
            for category, root in source_roots
        )
        if in_slice:
            unexpected_source.append(
                f"{finding.category}:{finding.path}:{finding.line}:{finding.symbol}"
            )

    unexpected_rom = []
    seen_rom_sites: set[tuple[int, int]] = set()
    for finding in (*rom_report.findings, *rom_report.candidate_findings):
        if rom_finding_subject(finding).sha256 in rom_subjects:
            continue
        shape = (finding.category, finding.root, finding.control_flow_kind)
        in_slice = shape in rom_shapes or any(
            finding.category == category
            and (
                (category == "writer" and belongs_to_root(finding.root, root))
                or finding.root.startswith(root + ".")
            )
            and (
                category != "writer"
                or finding.resource in _OWNER_GATED_ROM_RESOURCES
            )
            for category, root in rom_roots
        )
        site = (finding.bank, finding.address)
        if (
            in_slice
            and site not in reviewed_rom_sites
            and site not in seen_rom_sites
        ):
            seen_rom_sites.add(site)
            unexpected_rom.append(
                f"{finding.category}:{finding.root}:{finding.bank:02x}:"
                f"{finding.address:04x}:{finding.resource}"
            )

    errors = []
    if unexpected_source:
        errors.append(
            "unexpected unlisted source item(s) in reviewed slice: "
            + ", ".join(sorted(unexpected_source))
        )
    if unexpected_rom:
        errors.append(
            "unexpected unlisted ROM item(s) in reviewed slice: "
            + ", ".join(sorted(unexpected_rom))
        )
    if errors:
        raise InventoryReconciliationError("\n".join(errors))


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
    assignments: DiscoveryAssignmentAuthority,
    source_report: Any,
    rom_report: Any,
    *,
    matcher: Any | None = None,
) -> tuple[Any, Any, tuple[str, ...], tuple[str, ...]]:
    hashes = {
        "source_sha256": source_report.source_sha256,
        "rom_sha256": rom_report.rom_sha256,
        "sym_sha256": rom_report.sym_sha256,
        "map_sha256": rom_report.map_sha256,
    }
    matcher = matcher or assignments.matcher(**hashes)
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
    repository: str | Path = ".",
) -> dict[str, Any]:
    """Project reviewed assignments once and report honest remaining work."""
    all_writers, all_scenes, all_mutations = writers, scenes, mutations
    repository_path = Path(repository).resolve()
    phase2_state = _phase2_transition_state(
        writers=writers, scenes=scenes, mutations=mutations, assignments=assignments
    )
    normal_assignments = assignments.for_product(NORMAL_DEBUG_PRODUCT)
    _validate_assignment_targets(normal_assignments, writers, scenes, mutations)
    reviewed_source, source_transition = _reviewed_source_view(
        normal_assignments, source_report, repository_path
    )
    reviewed_rom = _reviewed_rom_view(normal_assignments, rom_report, source_transition)
    reviewed_rom_data = _reviewed_rom_bytes(
        normal_assignments, rom_report, source_transition, rom
    )
    _assert_no_unlisted_slice_findings(normal_assignments, reviewed_source, reviewed_rom)
    matcher = normal_assignments.matcher(
        source_sha256=reviewed_source.source_sha256,
        rom_sha256=reviewed_rom.rom_sha256,
        sym_sha256=reviewed_rom.sym_sha256,
        map_sha256=reviewed_rom.map_sha256,
        product=NORMAL_DEBUG_PRODUCT,
    )
    projected_source, projected_rom, source_rows, rom_rows = _project_assignments(
        normal_assignments, reviewed_source, reviewed_rom, matcher=matcher
    )
    if phase2_state == "planned":
        planned = _validate_planned_rows(
            writers=writers,
            scenes=scenes,
            mutations=mutations,
            assignments=normal_assignments,
            source_report=source_report,
            rom_report=rom_report,
            rom=rom,
            repository=repository_path,
        )
    else:
        planned = ()
    normal_row_ids = {row.row_id for row in normal_assignments.rows}
    writers = _select_inventory_rows(writers, normal_row_ids)
    scenes = _select_inventory_rows(scenes, normal_row_ids)
    mutations = _select_inventory_rows(mutations, normal_row_ids)
    report = reconcile(
        writers,
        scenes,
        mutations,
        source_report=projected_source,
        rom_report=projected_rom,
        rom=reviewed_rom_data,
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

    backlog = {
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
        "backlog": backlog,
        "closed": True,
        "hashes": {
            "assignments_sha256": assignments.sha256,
            "map_sha256": projected_rom.map_sha256,
            "mutations_sha256": all_mutations.sha256,
            "rom_sha256": projected_rom.rom_sha256,
            "scenes_sha256": all_scenes.sha256,
            "source_sha256": projected_source.source_sha256,
            "sym_sha256": projected_rom.sym_sha256,
            "writers_sha256": all_writers.sha256,
        },
        "matched": {
            "machine_count": len(report.matched_machine_sites),
            "machine_row_ids": list(row_ids),
            "source_count": len(report.matched_source_sites),
            "source_row_ids": list(row_ids),
        },
        "reviewed_slice": {
            "closed": True,
            "name": REVIEWED_SLICE,
            "rom_unlisted_count": 0,
            "source_unlisted_count": 0,
        },
        "reviewed_rows": {
            "mutation_count": len(mutations.rows),
            "row_ids": list(row_ids),
            "scene_count": len(scenes.rows),
            "total_count": len(rows),
            "writer_count": len(writers.rows),
        },
        "planned_rows": {
            "row_ids": sorted(row["id"] for row in planned),
            "total_count": len(planned),
        },
        "source_transition": source_transition,
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
        repository=root,
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
