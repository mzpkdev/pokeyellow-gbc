"""Run and retain two independent Phase 1 runtime evidence captures."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from tools.rom_tests.emulator import Emulator

from .errors import RendererConformanceError
from .phase1_baseline import BaselineSemanticReport, compare_phase1_baseline
from .renderer_conformance import ConformanceReport, EvidenceMode
from .renderer_conformance_artifacts import canonical_case_input, canonical_expected
from .renderer_conformance_runtime import (
    canonical_phase1_case,
    check_runtime_observation,
)
from .renderer_oracle import ConformanceCase, derive_expectation
from .renderer_runtime_artifacts import (
    RUNTIME_RUN_SUMMARY_SCHEMA,
    RuntimeCaseArtifacts,
    RuntimeManifest,
    artifact_for_path,
    validate_runtime_artifacts,
)
from .runtime_observability import (
    RuntimeObservation,
    capture_phase1_runtime_observation,
    capture_yellow_baseline_snapshot,
    restore_phase1_to_yellow,
    wait_until_phase1_capture_ready,
)
from .snapshots import SemanticSnapshot
from .trace import WriterTrace

RUNTIME_RUNNER_SCHEMA = "full-color-renderer-runtime-runner-v1"
TEST_MUTATIONS = frozenset(
    {"baseline-byte", "diverge-frame", "missing-superseded", "stale-generation", "error"}
)


def write_json(path: Path, value: object) -> None:
    _write_text(
        path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def new_attempt(results_root: Path) -> Path:
    results_root.mkdir(parents=True, exist_ok=True)
    for number in range(1, 1_000_000):
        candidate = results_root / f"attempt-{number:04d}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RendererConformanceError("runtime results contain too many attempts")


@dataclass(frozen=True, slots=True)
class RuntimeRunData:
    case: ConformanceCase
    baseline_before: SemanticSnapshot
    observation: RuntimeObservation
    baseline_after: SemanticSnapshot


RuntimeMutation = Callable[[RuntimeRunData], RuntimeRunData]


def _named_mutation(name: str) -> RuntimeMutation:
    if name not in TEST_MUTATIONS:
        raise RendererConformanceError(f"unknown runtime test mutation: {name}")

    def mutate(data: RuntimeRunData) -> RuntimeRunData:
        if name == "error":
            raise RendererConformanceError("injected runtime capture error")
        if name == "baseline-byte":
            changed = bytes([data.baseline_after.bg_tile_ids[0] ^ 1]) + (
                data.baseline_after.bg_tile_ids[1:]
            )
            return replace(
                data,
                baseline_after=replace(data.baseline_after, bg_tile_ids=changed),
            )
        if name == "diverge-frame":
            return replace(
                data,
                baseline_after=replace(
                    data.baseline_after, frame=data.baseline_after.frame + 1
                ),
            )
        entries = list(data.observation.trace.entries)
        cancelled_index = next(
            index
            for index, entry in enumerate(entries)
            if entry.cancellation_reason is not None
        )
        entry = entries[cancelled_index]
        if name == "missing-superseded":
            from .enums import CancellationReason

            entries[cancelled_index] = replace(
                entry, cancellation_reason=CancellationReason.HANDOFF
            )
        elif name == "stale-generation":
            entries[cancelled_index] = replace(
                entry, generation=entry.generation + 1
            )
        trace = WriterTrace(
            capacity=data.observation.trace.capacity,
            entries=tuple(entries),
            permitted_writer_ids=data.observation.trace.permitted_writer_ids,
            resource_identities=data.observation.trace.resource_identities,
        )
        observation = RuntimeObservation(
            data.observation.case_id,
            data.observation.rom_identity,
            data.observation.snapshot,
            trace,
        )
        return replace(data, observation=observation)

    return mutate


def _apply_mutation(
    data: RuntimeRunData, mutation: str | RuntimeMutation | None
) -> RuntimeRunData:
    if mutation is None:
        return data
    function = _named_mutation(mutation) if isinstance(mutation, str) else mutation
    mutated = function(data)
    if not isinstance(mutated, RuntimeRunData):
        raise RendererConformanceError(
            "runtime mutation seam must return RuntimeRunData"
        )
    return mutated


def _compact_summary(
    case: ConformanceCase, report: ConformanceReport
) -> str:
    lines = [
        f"case: {case.case_id}",
        f"mode: {report.mode.value}",
        f"status: {'passed' if report.passed else 'failed'}",
        f"checks: {', '.join(case.checks)}",
        f"differences: {len(report.differences)}",
    ]
    for difference in report.differences:
        lines.append(
            f"- {difference.path}: expected={difference.expected!r} "
            f"actual={difference.actual!r}"
        )
    return "\n".join(lines) + "\n"


def _rom_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_phase1_runtime(
    root: Path,
    run_dir: Path,
    *,
    mutation: str | RuntimeMutation | None = None,
) -> bool:
    """Capture one fresh ROM run, retain it, and independently validate it."""
    root = root.resolve()
    run_dir.mkdir()
    case = canonical_phase1_case(root)
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=run_dir,
        cgb=True,
    )
    try:
        wait_until_phase1_capture_ready(emulator)
        before = capture_yellow_baseline_snapshot(
            emulator,
            scenario="phase1-baseline",
            seed=0,
            checkpoint="before-phase1-runtime",
        )
        observation = capture_phase1_runtime_observation(
            emulator, case, settle_debug_ready=False
        )
        after = restore_phase1_to_yellow(emulator)
    finally:
        emulator.close()

    data = _apply_mutation(RuntimeRunData(case, before, observation, after), mutation)
    report = check_runtime_observation(case, data.observation)
    baseline_report = compare_phase1_baseline(
        data.baseline_before, data.baseline_after
    )
    case_dir = run_dir / "cases" / case.case_id
    paths = {
        "case-input": case_dir / "case-input.json",
        "expected-patches": case_dir / "expected-patches.json",
        "actual-semantic-snapshot": case_dir / "actual-semantic-snapshot.json",
        "actual-writer-trace": case_dir / "actual-writer-trace.json",
        "structured-diff": case_dir / "structured-diff.json",
        "compact-summary": case_dir / "compact-summary.txt",
    }
    write_json(paths["case-input"], canonical_case_input(case))
    write_json(paths["expected-patches"], canonical_expected(derive_expectation(case)))
    _write_text(paths["actual-semantic-snapshot"], data.observation.snapshot.to_json())
    _write_text(paths["actual-writer-trace"], data.observation.trace.to_json())
    _write_text(paths["structured-diff"], report.to_json())
    _write_text(paths["compact-summary"], _compact_summary(case, report))
    case_row = RuntimeCaseArtifacts(
        case_id=case.case_id,
        checks=case.checks,
        mode=EvidenceMode.ROM_RUNTIME,
        passed=report.passed,
        artifacts=tuple(
            artifact_for_path(role, path, root=run_dir)
            for role, path in sorted(paths.items())
        ),
    )

    baseline_paths = {
        "baseline-before": run_dir / "baseline-before.json",
        "baseline-after": run_dir / "baseline-after.json",
        "baseline-report": run_dir / "baseline-semantic-report.json",
    }
    _write_text(baseline_paths["baseline-before"], data.baseline_before.to_json())
    _write_text(baseline_paths["baseline-after"], data.baseline_after.to_json())
    _write_text(baseline_paths["baseline-report"], baseline_report.to_json())
    rom_sha256 = _rom_sha256(root / "pokeyellow_debug.gbc")
    manifest = RuntimeManifest(
        rom_sha256=rom_sha256,
        cases=(case_row,),
        baseline_before=artifact_for_path(
            "baseline-before", baseline_paths["baseline-before"], root=run_dir
        ),
        baseline_after=artifact_for_path(
            "baseline-after", baseline_paths["baseline-after"], root=run_dir
        ),
        baseline_report=artifact_for_path(
            "baseline-report", baseline_paths["baseline-report"], root=run_dir
        ),
    )
    _write_text(run_dir / "manifest.json", manifest.to_json())
    passed = report.passed and baseline_report.passed
    write_json(
        run_dir / "run-summary.json",
        {
            "schema": RUNTIME_RUN_SUMMARY_SCHEMA,
            "status": "passed" if passed else "failed",
            "rom_sha256": rom_sha256,
            "activation_phase": manifest.activation_phase,
            "case_ids": list(manifest.activated_case_ids),
            "failed_cases": [] if report.passed else [case.case_id],
            "baseline_passed": baseline_report.passed,
        },
    )
    validate_runtime_artifacts(run_dir, manifest, repository_root=root)
    return passed


def _stable_files(run_dir: Path) -> dict[str, Path]:
    if not run_dir.is_dir():
        return {}
    return {
        path.relative_to(run_dir).as_posix(): path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "run-summary.json"
    }


def compare_stable_runtime_evidence(first: Path, second: Path) -> dict[str, Any]:
    first_files = _stable_files(first)
    second_files = _stable_files(second)
    first_names = set(first_files)
    second_names = set(second_files)
    missing_from_run_1 = sorted(second_names - first_names)
    missing_from_run_2 = sorted(first_names - second_names)
    common = sorted(first_names & second_names)
    hashes = {
        relative: {
            "run-1": hashlib.sha256(first_files[relative].read_bytes()).hexdigest(),
            "run-2": hashlib.sha256(second_files[relative].read_bytes()).hexdigest(),
        }
        for relative in common
    }
    changed = [
        relative
        for relative in common
        if hashes[relative]["run-1"] != hashes[relative]["run-2"]
    ]
    manifest_identical = "manifest.json" in common and "manifest.json" not in changed
    return {
        "byte_identical": not (
            missing_from_run_1 or missing_from_run_2 or changed
        )
        and manifest_identical,
        "manifest_byte_identical": manifest_identical,
        "changed": changed,
        "missing_from_run_1": missing_from_run_1,
        "missing_from_run_2": missing_from_run_2,
        "file_count": len(common),
        "sha256": hashes,
    }


def run_renderer_runtime(
    root: Path,
    results_root: Path,
    *,
    mutation_by_run: Mapping[str, str | RuntimeMutation] | None = None,
) -> dict[str, object]:
    """Complete both fresh runs, then fail for red or nondeterministic evidence."""
    root = root.resolve()
    attempt = new_attempt(results_root.resolve())
    runs = ("run-1", "run-2")
    summary: dict[str, object] = {
        "schema": RUNTIME_RUNNER_SCHEMA,
        "status": "running",
        "attempt": attempt.name,
        "runs": {},
    }
    write_json(attempt / "summary.json", summary)
    statuses: dict[str, bool] = {}
    errors: dict[str, str] = {}
    for name in runs:
        try:
            statuses[name] = run_phase1_runtime(
                root,
                attempt / name,
                mutation=(mutation_by_run or {}).get(name),
            )
        except Exception as exc:
            statuses[name] = False
            errors[name] = str(exc)
            run = attempt / name
            run.mkdir(exist_ok=True)
            write_json(
                run / "run-error.json",
                {"schema": RUNTIME_RUNNER_SCHEMA, "run": name, "error": str(exc)},
            )
    comparison = compare_stable_runtime_evidence(
        attempt / "run-1", attempt / "run-2"
    )
    summary["runs"] = {
        name: {
            "status": "passed" if statuses[name] else "failed",
            "error": errors.get(name),
        }
        for name in runs
    }
    summary["comparison"] = comparison
    passed = all(statuses.values()) and bool(comparison["byte_identical"])
    summary["status"] = "passed" if passed else "failed"
    if errors:
        summary["errors"] = errors
    write_json(attempt / "summary.json", summary)
    if errors:
        raise RendererConformanceError(
            "runtime capture failed in " + ", ".join(sorted(errors))
        )
    if not comparison["byte_identical"]:
        raise RendererConformanceError(
            "independent runtime executions produced different evidence"
        )
    failed = [name for name, status in statuses.items() if not status]
    if failed:
        raise RendererConformanceError(
            "runtime checks failed in " + ", ".join(failed)
        )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 1 ROM evidence twice")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--mutation-run-2", choices=sorted(TEST_MUTATIONS))
    args = parser.parse_args(argv)
    if args.mutation_run_2 is not None and "CI" in os.environ:
        print("runtime evidence mutation is forbidden in CI", file=sys.stderr)
        return 2
    try:
        summary = run_renderer_runtime(
            args.root,
            args.results,
            mutation_by_run=(
                None
                if args.mutation_run_2 is None
                else {"run-2": args.mutation_run_2}
            ),
        )
    except Exception as exc:
        print(f"renderer runtime failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
