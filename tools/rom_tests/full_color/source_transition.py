"""Generate the reviewed-to-audit source transition without changing authority."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import baseline_discovery as baseline
from .discovery_assignment import DiscoveryAssignmentAuthority, NORMAL_DEBUG_PRODUCT
from .discovery_review import rom_finding_subject, source_finding_subject
from .rom_discovery import discover_rom_batched, load_map, load_sym


SCHEMA = "full-color-phase1-audit-source-transition-v2"
TRANSITION_PATH = Path(
    "specs/full-colors/definitions/phase1-audit-source-transition.json"
)
ASSIGNMENTS_PATH = Path("specs/full-colors/inventory/assignments.json")


class SourceTransitionError(RuntimeError):
    """The immutable reviewed authority cannot map uniquely to current evidence."""


def _manifest_sha256(manifest: dict[str, str]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _unique_rebindings(
    rows: Iterable[Any],
    findings: Iterable[Any],
    *,
    subject: Callable[[Any], Any],
    rebound: Callable[[Any, Any], Any],
    kind: str,
) -> dict[str, str]:
    current = tuple(findings)
    result: dict[str, str] = {}
    claimed: set[str] = set()
    for row in rows:
        matches = [
            finding
            for finding in current
            if subject(rebound(finding, row)).sha256 == row.subject.sha256
        ]
        if len(matches) != 1:
            raise SourceTransitionError(
                f"reviewed {kind} subject {row.subject.sha256} has "
                f"{len(matches)} semantic matches; expected exactly one"
            )
        current_sha = subject(matches[0]).sha256
        if current_sha in claimed:
            raise SourceTransitionError(
                f"reviewed {kind} subjects do not map uniquely to current findings"
            )
        claimed.add(current_sha)
        result[row.subject.sha256] = current_sha
    return dict(sorted(result.items()))


def _raw_baseline_rom(root: Path, source_report: Any) -> Any:
    symbols = load_sym(root / "pokeyellow_debug.sym")
    source_writers = set(baseline.writer_roots(source_report))
    linked_writer_roots = source_writers & symbols.by_name.keys()
    scene_roots = tuple(
        sorted(set(baseline.LIFECYCLE_ROOTS) | set(baseline.SCENE_ROOTS))
    )
    roots = tuple(
        sorted(
            linked_writer_roots
            | set(scene_roots)
            | set(baseline.MUTATION_ROOTS)
        )
    )
    return discover_rom_batched(
        (root / "pokeyellow_debug.gbc").read_bytes(),
        symbols,
        roots,
        batch_size=16,
        sections=load_map(root / "pokeyellow_debug.map"),
        farcall_labels=baseline.FARCALL_LABELS,
        predef_targets=baseline.load_predef_targets(root, symbols),
        copied_regions=baseline.COPIED_REGIONS,
        shadow_oam_ranges=baseline.SHADOW_OAM_RANGES,
        scene_roots=scene_roots,
        mutation_roots=baseline.MUTATION_ROOTS,
        dma_control_labels=baseline.DMA_CONTROL_LABELS,
        follow_calls=False,
    )


def generate(root: Path, *, authority_path: Path | None = None) -> dict[str, object]:
    authority_file = authority_path or root / TRANSITION_PATH
    try:
        authority = json.loads(authority_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceTransitionError("source-transition authority is unreadable") from exc
    if set(authority) != {
        "schema",
        "reviewed_source_sha256",
        "audit_source_sha256",
        "baseline_manifest_sha256",
        "audit_only_paths",
        "subject_rebindings",
        "rom_subject_rebindings",
    } or authority["schema"] != SCHEMA:
        raise SourceTransitionError("source-transition authority is malformed")

    source_report = baseline.discover_baseline_sources(root)
    include_paths = {path for path, _ in source_report.include_graph}
    current_manifest = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in sorted(include_paths)
    }
    audit_only_paths: dict[str, dict[str, str | None]] = {}
    baseline_manifest = dict(current_manifest)
    for relative, binding in authority["audit_only_paths"].items():
        if relative not in current_manifest:
            raise SourceTransitionError(f"audit path is no longer linked: {relative}")
        reviewed = binding["reviewed_sha256"]
        audit_only_paths[relative] = {
            "reviewed_sha256": reviewed,
            "audit_sha256": current_manifest[relative],
        }
        if reviewed is None:
            baseline_manifest.pop(relative)
        else:
            baseline_manifest[relative] = reviewed
    if _manifest_sha256(baseline_manifest) != authority["baseline_manifest_sha256"]:
        raise SourceTransitionError(
            "current source changed outside the immutable audit-only path partition"
        )

    assignments = DiscoveryAssignmentAuthority.load(root / ASSIGNMENTS_PATH).for_product(
        NORMAL_DEBUG_PRODUCT
    )
    source_rows = [
        row for row in assignments.rows if row.subject.kind.value == "SOURCE_FINDING"
    ]
    rom_rows = [
        row for row in assignments.rows if row.subject.kind.value == "ROM_FINDING"
    ]
    subject_rebindings = _unique_rebindings(
        source_rows,
        source_report.findings,
        subject=source_finding_subject,
        rebound=lambda finding, row: replace(
            finding, symbol=row.subject.metadata["symbol"]
        ),
        kind="source",
    )
    rom_report = _raw_baseline_rom(root, source_report)
    rom_subject_rebindings = _unique_rebindings(
        rom_rows,
        rom_report.findings,
        subject=rom_finding_subject,
        rebound=lambda finding, row: replace(
            finding,
            root=row.subject.metadata["root"],
            call_path=tuple(row.subject.metadata["call_path"]),
        ),
        kind="ROM",
    )
    return {
        "schema": SCHEMA,
        "reviewed_source_sha256": authority["reviewed_source_sha256"],
        "audit_source_sha256": source_report.source_sha256,
        "baseline_manifest_sha256": authority["baseline_manifest_sha256"],
        "audit_only_paths": dict(sorted(audit_only_paths.items())),
        "subject_rebindings": subject_rebindings,
        "rom_subject_rebindings": rom_subject_rebindings,
    }


def generate_json(root: Path, *, authority_path: Path | None = None) -> str:
    return _canonical(generate(root, authority_path=authority_path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rendered = generate_json(args.root, authority_path=args.authority)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except (OSError, SourceTransitionError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
