"""Retained, deterministic execution of the renderer-conformance corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from .errors import RendererConformanceError
from .renderer_conformance import EvidenceMode, check_case
from .renderer_conformance_artifacts import (
    ConformanceCaseArtifacts,
    ConformanceManifest,
    artifact_for_path,
    canonical_case_input,
    canonical_expected,
    validate_conformance_artifacts,
)
from .renderer_conformance_fixtures import FilesystemObservationProvider
from .renderer_conformance_fixtures import MUTATIONS
from .renderer_oracle import (
    derive_expectation,
    load_corpus,
)

RUNNER_SCHEMA = "full-color-renderer-conformance-runner-v1"
FIXTURE_RELATIVE = Path("tools/rom_tests/fixtures/full_color/renderer-conformance")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
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
    raise RendererConformanceError(
        "renderer conformance results contain too many attempts"
    )


def _summary_text(
    case: ConformanceCase, passed: bool, differences: tuple[object, ...]
) -> str:
    lines = [
        f"case: {case.case_id}",
        f"mode: {EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST.value}",
        f"status: {'passed' if passed else 'failed'}",
        f"checks: {', '.join(case.checks)}",
        f"differences: {len(differences)}",
    ]
    for difference in differences:
        lines.append(
            f"- {difference.path}: expected={difference.expected!r} "
            f"actual={difference.actual!r}"
        )
    return "\n".join(lines) + "\n"


def run_corpus(root: Path, run_dir: Path, *, mutation: str | None = None) -> bool:
    fixture_root = root / FIXTURE_RELATIVE
    try:
        raw = json.loads((fixture_root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RendererConformanceError(f"renderer corpus is invalid: {exc}") from exc
    cases = load_corpus(raw)
    run_dir.mkdir()
    rows: list[ConformanceCaseArtifacts] = []
    all_passed = True
    for case in cases:
        case_dir = run_dir / "cases" / case.case_id
        case_dir.mkdir(parents=True)
        provider = FilesystemObservationProvider(fixture_root, mutation)
        report = check_case(
            case, provider, mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST
        )
        expectation = derive_expectation(case)
        snapshot = provider.raw_snapshot(case)
        trace = provider.raw_trace(case)
        boundary = provider.raw_boundary(case)
        paths = {
            "case-input": case_dir / "case-input.json",
            "expected-patches": case_dir / "expected-patches.json",
            "actual-semantic-snapshot": case_dir / "actual-semantic-snapshot.json",
            "actual-writer-trace": case_dir / "actual-writer-trace.json",
            "structured-diff": case_dir / "structured-diff.json",
            "compact-summary": case_dir / "compact-summary.txt",
        }
        write_json(paths["case-input"], canonical_case_input(case))
        write_json(paths["expected-patches"], canonical_expected(expectation))
        write_json(paths["actual-semantic-snapshot"], snapshot)
        write_json(paths["actual-writer-trace"], trace)
        write_json(paths["structured-diff"], report.to_dict())
        paths["compact-summary"].write_text(
            _summary_text(case, report.passed, report.differences), encoding="utf-8"
        )
        if boundary is not None:
            paths["actual-boundary"] = case_dir / "actual-boundary.json"
            write_json(paths["actual-boundary"], boundary)
        rows.append(
            ConformanceCaseArtifacts(
                case_id=case.case_id,
                checks=case.checks,
                mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
                passed=report.passed,
                artifacts=tuple(
                    artifact_for_path(role, path, root=run_dir)
                    for role, path in sorted(paths.items())
                ),
            )
        )
        all_passed = all_passed and report.passed
    manifest = ConformanceManifest(tuple(rows))
    (run_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    write_json(
        run_dir / "run-summary.json",
        {
            "schema": RUNNER_SCHEMA,
            "status": "passed" if all_passed else "failed",
            "case_count": len(cases),
            "failed_cases": [row.case_id for row in rows if not row.passed],
        },
    )
    validate_conformance_artifacts(run_dir, manifest)
    return all_passed


def _stable_files(run_dir: Path) -> dict[str, Path]:
    return {
        path.relative_to(run_dir).as_posix(): path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "run-summary.json"
    }


def compare_stable_files(first: Path, second: Path) -> dict[str, Any]:
    first_files = _stable_files(first)
    second_files = _stable_files(second)
    missing_from_run_1 = sorted(set(second_files) - set(first_files))
    missing_from_run_2 = sorted(set(first_files) - set(second_files))
    changed = sorted(
        relative
        for relative in set(first_files) & set(second_files)
        if first_files[relative].read_bytes() != second_files[relative].read_bytes()
    )
    common = sorted(set(first_files) & set(second_files))
    manifest = "manifest.json"
    manifest_identical = manifest in common and manifest not in changed
    return {
        "byte_identical": not (missing_from_run_1 or missing_from_run_2 or changed)
        and manifest_identical,
        "manifest_byte_identical": manifest_identical,
        "changed": changed,
        "file_count": len(common),
        "missing_from_run_1": missing_from_run_1,
        "missing_from_run_2": missing_from_run_2,
        "sha256": {
            relative: hashlib.sha256(first_files[relative].read_bytes()).hexdigest()
            for relative in common
        },
    }


def run_renderer_conformance(
    root: Path,
    results_root: Path,
    *,
    mutation_by_run: Mapping[str, str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    attempt = new_attempt(results_root.resolve())
    runs = ("run-1", "run-2")
    summary: dict[str, object] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "attempt": attempt.name,
        "runs": list(runs),
    }
    write_json(attempt / "summary.json", summary)
    try:
        statuses: dict[str, bool] = {}
        for name in runs:
            statuses[name] = run_corpus(
                root, attempt / name, mutation=(mutation_by_run or {}).get(name)
            )
        comparison = compare_stable_files(attempt / "run-1", attempt / "run-2")
        summary["comparison"] = comparison
        if not comparison["byte_identical"]:
            raise RendererConformanceError(
                "independent checker executions produced different evidence"
            )
        failed = [name for name, passed in statuses.items() if not passed]
        if failed:
            raise RendererConformanceError(
                "checker cases failed in " + ", ".join(failed)
            )
    except Exception as exc:
        summary.update(status="failed", error=str(exc))
        write_json(attempt / "summary.json", summary)
        raise
    summary["status"] = "passed"
    write_json(attempt / "summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run renderer conformance twice")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--mutation-run-2", choices=sorted(MUTATIONS))
    args = parser.parse_args(argv)
    if args.mutation_run_2 is not None and "CI" in os.environ:
        print(
            "renderer conformance failed: test-only mutation is forbidden in CI",
            file=sys.stderr,
        )
        return 2
    try:
        summary = run_renderer_conformance(
            args.root,
            args.results,
            mutation_by_run=(
                None
                if args.mutation_run_2 is None
                else {"run-2": args.mutation_run_2}
            ),
        )
    except Exception as exc:
        print(f"renderer conformance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
