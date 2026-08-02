"""Deterministic double-run coordinator for Phase 2 runtime evidence."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path

from .errors import RendererConformanceError
from .phase2_conformance_runtime import ACTIVATED_PHASE2_CASE_IDS
from .phase2_runtime_artifacts import (
    CASE_FILENAMES, GLOBAL_PATHS, IDENTITY_PATHS, RUN_SUMMARY_SCHEMA, Artifact,
    Phase2RuntimeManifest, artifact_for_path, file_sha256,
    validate_phase2_runtime_artifacts,
)
from .phase2_runtime_observability import require_committed_guarded_audit


Capture = Callable[[Path, Path, Path], None]


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
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
    raise RendererConformanceError("Phase 2 results contain too many attempts")


def _default_capture(root: Path, run_dir: Path, timing_report: Path) -> None:
    # The observability layer currently exposes carrier records, not the
    # independent SemanticSnapshot/WriterTrace/visual bundle required here.
    # Refuse to manufacture authority until the visual capture adapter lands.
    raise RendererConformanceError(
        "Phase 2 capture adapter is incomplete: runtime must provide all case, "
        "pressure, boundary, reconstruction, timing, and visual artifacts"
    )


def _manifest(root: Path, run_dir: Path) -> Phase2RuntimeManifest:
    guarded = require_committed_guarded_audit(root)
    identities = {name: file_sha256(root / relative) for name, relative in IDENTITY_PATHS.items()}
    identities["sameboy-report"] = file_sha256(run_dir / GLOBAL_PATHS["timing"])
    try:
        timing = json.loads((run_dir / GLOBAL_PATHS["timing"]).read_text(encoding="utf-8"))
        identities["sameboy-tool"] = timing["bridge_sha256"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RendererConformanceError(f"Phase 2 timing report lacks tool identity: {exc}") from exc
    cases = tuple(
        (case_id, tuple(
            artifact_for_path(role, run_dir / "cases" / case_id / filename, run_dir)
            for role, filename in sorted(CASE_FILENAMES.items())
        )) for case_id in ACTIVATED_PHASE2_CASE_IDS
    )
    artifacts = tuple(
        artifact_for_path(role, run_dir / path, run_dir)
        for role, path in sorted(GLOBAL_PATHS.items())
    )
    return Phase2RuntimeManifest(identities, guarded, cases, artifacts)


def run_once(root: Path, run_dir: Path, timing_report: Path, capture: Capture) -> Phase2RuntimeManifest:
    run_dir.mkdir()
    require_committed_guarded_audit(root)  # closure must precede debug capture
    capture(root, run_dir, timing_report)
    manifest = _manifest(root, run_dir)
    _atomic_text(run_dir / "manifest.json", manifest.to_json())
    _atomic_json(run_dir / "run-summary.json", {
        "schema": RUN_SUMMARY_SCHEMA, "status": "passed",
        "activation_phase": 2, "case_count": len(ACTIVATED_PHASE2_CASE_IDS),
    })
    validate_phase2_runtime_artifacts(run_dir, manifest, root)
    return manifest


def compare_stable_phase2_evidence(first: Path, second: Path) -> dict[str, object]:
    def hashes(base: Path) -> dict[str, str]:
        return {path.relative_to(base).as_posix(): file_sha256(path)
                for path in base.rglob("*") if path.is_file()
                and path.name != "run-summary.json"}
    left, right = hashes(first), hashes(second)
    common = sorted(left.keys() & right.keys())
    changed = [path for path in common if left[path] != right[path]]
    return {
        "byte_identical": not changed and left.keys() == right.keys(),
        "file_count": len(common), "changed": changed,
        "missing_from_run_1": sorted(right.keys() - left.keys()),
        "missing_from_run_2": sorted(left.keys() - right.keys()),
        "sha256": {path: {"run-1": left[path], "run-2": right[path]} for path in common},
    }


def run_phase2_runtime(root: Path, results: Path, timing_report: Path, *,
                       capture: Capture = _default_capture) -> dict[str, object]:
    root, timing_report = root.resolve(), timing_report.resolve()
    attempt = new_attempt(results)
    statuses: dict[str, dict[str, str]] = {}
    for name in ("run-1", "run-2"):
        run_dir = attempt / name
        staging = attempt / f"{name}.incomplete"
        try:
            run_once(root, staging, timing_report, capture)
            staging.replace(run_dir)
            statuses[name] = {"status": "passed"}
        except Exception as exc:
            staging.mkdir(exist_ok=True)
            _atomic_json(staging / "run-error.json", {
                "schema": RUN_SUMMARY_SCHEMA, "status": "failed",
                "error_type": type(exc).__name__, "error": str(exc),
            })
            staging.replace(run_dir)
            statuses[name] = {"status": "failed", "error": str(exc)}
    comparison = compare_stable_phase2_evidence(attempt / "run-1", attempt / "run-2")
    summary = {"schema": "full-color-phase2-runtime-runner-v1", "runs": statuses,
               "comparison": comparison,
               "status": "passed" if all(row["status"] == "passed" for row in statuses.values()) and comparison["byte_identical"] else "failed"}
    _atomic_json(attempt / "summary.json", summary)
    if summary["status"] != "passed":
        raise RendererConformanceError("Phase 2 double-run evidence failed; retained under " + str(attempt))
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture Phase 2 hostile runtime evidence twice")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--timing-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_phase2_runtime(args.root, args.results, args.timing_report)
    except Exception as exc:
        print(f"Phase 2 runtime failed: {exc}")
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
