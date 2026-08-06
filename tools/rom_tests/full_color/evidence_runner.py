"""Deterministic capture and comparison of full-color evidence."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from .runner_output import (
    NULL_REPORTER,
    OutputMode,
    RunnerReporter,
    add_output_argument,
)


RUNNER_SCHEMA = "full-color-evidence-runner-v1"
COMPONENTS = (
    "observability",
    "traceability",
    "visual-pipeline",
)
RunCommand = Callable[[Sequence[str], Path, Path, Path], int]


def _write_json(path: Path, value: object) -> None:
    """Atomically publish a status file without losing the previous contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _default_run_command(
    command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(
            tuple(command), cwd=cwd, stdout=stdout, stderr=stderr, check=False
        )
    return completed.returncode


def _commands(python: str, root: Path, run_dir: Path) -> tuple[tuple[str, ...], ...]:
    return (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.runtime_observability",
            "--root",
            str(root),
            "--snapshot-output",
            str(run_dir / "semantic-snapshot.json"),
            "--diagnostics-output",
            str(run_dir / "diagnostics" / "runtime-observability"),
        ),
        (
            python,
            "-m",
            "tools.rom_tests.full_color.traceability",
            "--spec-root",
            str(root / "specs" / "full-colors"),
            "--output",
            str(run_dir / "traceability-report.json"),
        ),
        (
            python,
            "-m",
            "tools.rom_tests.full_color.visual_pipeline",
            "--root",
            str(root),
            "--output",
            str(run_dir / "visual"),
        ),
    )


def _new_attempt(results_root: Path) -> Path:
    results_root.mkdir(parents=True, exist_ok=True)
    for number in range(1, 1_000_000):
        candidate = results_root / f"attempt-{number:04d}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("evidence results root contains too many attempts")


def _stable_files(run_dir: Path) -> dict[str, Path]:
    return {
        path.relative_to(run_dir).as_posix(): path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
        and path.name != "run-summary.json"
        and "/diagnostics/" not in f"/{path.relative_to(run_dir).as_posix()}"
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_runs(first: Path, second: Path) -> dict[str, Any]:
    first_files = _stable_files(first)
    second_files = _stable_files(second)
    missing_from_run_1 = sorted(set(second_files) - set(first_files))
    missing_from_run_2 = sorted(set(first_files) - set(second_files))
    changed = sorted(
        relative
        for relative in set(first_files) & set(second_files)
        if first_files[relative].read_bytes() != second_files[relative].read_bytes()
    )
    semantic_path = "semantic-snapshot.json"
    traceability_path = "traceability-report.json"
    manifest_path = "visual/manifest.json"
    explicit = {
        "semantic_snapshot_byte_identical": semantic_path in first_files
        and semantic_path in second_files
        and semantic_path not in changed,
        "traceability_report_byte_identical": traceability_path in first_files
        and traceability_path in second_files
        and traceability_path not in changed,
        "versioned_manifest_byte_identical": manifest_path in first_files
        and manifest_path in second_files
        and manifest_path not in changed,
    }
    return {
        "byte_identical": not (missing_from_run_1 or missing_from_run_2 or changed)
        and all(explicit.values()),
        "changed": changed,
        "file_count": len(set(first_files) & set(second_files)),
        "missing_from_run_1": missing_from_run_1,
        "missing_from_run_2": missing_from_run_2,
        **explicit,
        "sha256": {
            relative: _sha256(first_files[relative])
            for relative in sorted(set(first_files) & set(second_files))
        },
    }


def _run_once(
    root: Path,
    run_dir: Path,
    *,
    python: str,
    run_command: RunCommand,
    reporter: RunnerReporter = NULL_REPORTER,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "run-summary.json").exists():
        raise RuntimeError(f"evidence run directory already contains a run: {run_dir}")
    results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "components": results,
    }
    _write_json(run_dir / "run-summary.json", summary)
    for name, command in zip(COMPONENTS, _commands(python, root, run_dir), strict=True):
        label = f"{run_dir.name}/{name}"
        started = reporter.running(label)
        diagnostics = run_dir / "diagnostics"
        stdout_path = diagnostics / f"{name}.stdout.txt"
        stderr_path = diagnostics / f"{name}.stderr.txt"
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            returncode = run_command(command, root, stdout_path, stderr_path)
        except Exception as exc:
            stderr_path.write_text(f"runner exception: {exc}\n", encoding="utf-8")
            returncode = -1
        result = {
            "command": list(command),
            "name": name,
            "returncode": returncode,
            "stderr": stderr_path.relative_to(run_dir).as_posix(),
            "stdout": stdout_path.relative_to(run_dir).as_posix(),
        }
        results.append(result)
        if returncode:
            summary["status"] = "failed"
            summary["failed_component"] = name
            _write_json(run_dir / "run-summary.json", summary)
            error = RuntimeError(f"{name} failed with exit status {returncode}")
            reporter.failed(label, error, stderr_path)
            raise error
        reporter.passed(label, started)
        _write_json(run_dir / "run-summary.json", summary)
    summary["status"] = "passed"
    _write_json(run_dir / "run-summary.json", summary)
    return summary


def capture_evidence_once(
    root: Path,
    run_dir: Path,
    *,
    python: str = sys.executable,
    run_command: RunCommand = _default_run_command,
    reporter: RunnerReporter = NULL_REPORTER,
) -> dict[str, Any]:
    """Capture one complete evidence run for later independent comparison."""
    reporter.attempt(run_dir.resolve())
    return _run_once(
        root.resolve(),
        run_dir.resolve(),
        python=python,
        run_command=run_command,
        reporter=reporter,
    )


def _validate_complete_run(run: Path, run_summary: object) -> None:
    if not isinstance(run_summary, dict):
        raise RuntimeError(f"evidence run has an invalid summary: {run}")
    if run_summary.get("schema") != RUNNER_SCHEMA:
        raise RuntimeError(f"evidence run has an incompatible schema: {run}")
    if run_summary.get("status") != "passed":
        raise RuntimeError(f"evidence run did not pass: {run}")
    components = run_summary.get("components")
    if not isinstance(components, list) or any(
        not isinstance(component, dict) for component in components
    ):
        raise RuntimeError(f"evidence run has an invalid component graph: {run}")
    component_names = tuple(component.get("name") for component in components)
    if component_names != COMPONENTS:
        raise RuntimeError(f"evidence run has an unexpected component graph: {run}")


def _compare_complete_runs(
    first: Path, second: Path, output: Path
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "runs": [first.name, second.name],
    }
    _write_json(output, summary)
    try:
        for run in (first, second):
            run_summary_path = run / "run-summary.json"
            if not run_summary_path.is_file():
                raise RuntimeError(f"evidence run is missing its summary: {run}")
            run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            _validate_complete_run(run, run_summary)
        comparison = compare_runs(first, second)
        summary["comparison"] = comparison
        if not comparison["byte_identical"]:
            raise RuntimeError("independent evidence captures produced different evidence")
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        _write_json(output, summary)
        raise
    summary["status"] = "passed"
    _write_json(output, summary)
    return summary


def compare_evidence_runs(first: Path, second: Path, output: Path) -> dict[str, Any]:
    """Validate and compare two complete, independently produced evidence runs."""
    return _compare_complete_runs(first.resolve(), second.resolve(), output.resolve())


def run_evidence_determinism(
    root: Path,
    results_root: Path,
    *,
    python: str = sys.executable,
    run_command: RunCommand = _default_run_command,
    reporter: RunnerReporter = NULL_REPORTER,
) -> dict[str, Any]:
    root = root.resolve()
    results_root = results_root.resolve()
    attempt = _new_attempt(results_root)
    reporter.attempt(attempt)
    summary: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "attempt": attempt.name,
        "runs": ["run-1", "run-2"],
    }
    _write_json(attempt / "summary.json", summary)
    try:
        for name in summary["runs"]:
            _run_once(
                root,
                attempt / name,
                python=python,
                run_command=run_command,
                reporter=reporter,
            )
        comparison = compare_runs(attempt / "run-1", attempt / "run-2")
        summary["comparison"] = comparison
        if not comparison["byte_identical"]:
            raise RuntimeError("independent evidence captures produced different evidence")
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        _write_json(attempt / "summary.json", summary)
        reporter.failed("evidence", exc, attempt / "summary.json")
        raise
    summary["status"] = "passed"
    _write_json(attempt / "summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture and compare deterministic full-color evidence"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--results", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--one-run",
        metavar="NAME",
        help="execute one complete run under the results root",
    )
    mode.add_argument(
        "--compare-runs",
        nargs=2,
        metavar=("FIRST", "SECOND"),
        help="compare two complete run directories under the results root",
    )
    add_output_argument(parser)
    args = parser.parse_args(argv)
    reporter = RunnerReporter("evidence", args.output)
    summary_path: Path | None = None
    try:
        if args.one_run:
            run_path = args.results.resolve() / args.one_run
            summary = capture_evidence_once(args.root, run_path, reporter=reporter)
            summary_path = run_path / "run-summary.json"
        elif args.compare_runs:
            first, second = args.compare_runs
            summary_path = args.results.resolve() / "summary.json"
            summary = compare_evidence_runs(
                args.results / first,
                args.results / second,
                summary_path,
            )
        else:
            summary = run_evidence_determinism(
                args.root, args.results, reporter=reporter
            )
            summary_path = (
                args.results.resolve() / str(summary["attempt"]) / "summary.json"
            )
    except Exception as exc:
        reporter.failed("evidence", exc, summary_path or args.results)
        if reporter.mode is OutputMode.JSON:
            if summary_path is None and reporter.attempt_path is not None:
                summary_path = reporter.attempt_path / "summary.json"
            failed_summary: dict[str, Any] = {
                "status": "failed",
                "error": str(exc),
            }
            if summary_path is not None and summary_path.is_file():
                try:
                    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        failed_summary = loaded
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    pass
            reporter.finish(failed_summary, summary_path)
        return 1
    reporter.finish(summary, summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
