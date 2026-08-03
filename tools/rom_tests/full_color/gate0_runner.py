"""Retained, deterministic orchestration for the lean full-color Gate 0."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


RUNNER_SCHEMA = "full-color-gate0-runner-v1"
COMPONENTS = (
    "unit-tests",
    "baseline-discovery",
    "inventory-progress",
    "bank-torture",
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
            "pytest",
            "tools/rom_tests/tests/unit",
            "--ignore=tools/rom_tests/tests/unit/full_color/test_overworld_color_data_donor.py",
            "--junitxml",
            str(run_dir / "diagnostics" / "unit-tests.junit.xml"),
        ),
        (
            python,
            "-m",
            "tools.rom_tests.full_color.baseline_discovery",
            "--repository",
            str(root),
        ),
        (
            python,
            "-m",
            "tools.rom_tests.full_color.baseline_inventory",
            "--repository",
            str(root),
        ),
        (
            python,
            "-m",
            "tools.rom_tests.full_color.bank_torture",
            "--rom",
            str(root / "pokeyellow_debug.gbc"),
        ),
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
    raise RuntimeError("Gate 0 results root contains too many attempts")


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
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "run-summary.json").exists():
        raise RuntimeError(f"Gate 0 run directory already contains a run: {run_dir}")
    results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "components": results,
    }
    _write_json(run_dir / "run-summary.json", summary)
    for name, command in zip(COMPONENTS, _commands(python, root, run_dir), strict=True):
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
            raise RuntimeError(f"{name} failed with exit status {returncode}")
        _write_json(run_dir / "run-summary.json", summary)
    summary["status"] = "passed"
    _write_json(run_dir / "run-summary.json", summary)
    return summary


def run_gate0_once(
    root: Path,
    run_dir: Path,
    *,
    python: str = sys.executable,
    run_command: RunCommand = _default_run_command,
) -> dict[str, Any]:
    """Execute one complete Gate 0 run for later independent comparison."""
    return _run_once(
        root.resolve(),
        run_dir.resolve(),
        python=python,
        run_command=run_command,
    )


def compare_gate0_runs(first: Path, second: Path, output: Path) -> dict[str, Any]:
    """Validate and compare two complete, independently produced Gate 0 runs."""
    first = first.resolve()
    second = second.resolve()
    output = output.resolve()
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
                raise RuntimeError(f"Gate 0 run is missing its summary: {run}")
            run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            if run_summary.get("status") != "passed":
                raise RuntimeError(f"Gate 0 run did not pass: {run}")
        comparison = compare_runs(first, second)
        summary["comparison"] = comparison
        if not comparison["byte_identical"]:
            raise RuntimeError("independent Gate 0 executions produced different evidence")
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        _write_json(output, summary)
        raise
    summary["status"] = "passed"
    _write_json(output, summary)
    return summary


def run_gate0(
    root: Path,
    results_root: Path,
    *,
    python: str = sys.executable,
    run_command: RunCommand = _default_run_command,
) -> dict[str, Any]:
    root = root.resolve()
    results_root = results_root.resolve()
    attempt = _new_attempt(results_root)
    summary: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": "running",
        "attempt": attempt.name,
        "runs": ["run-1", "run-2"],
    }
    _write_json(attempt / "summary.json", summary)
    try:
        for name in summary["runs"]:
            _run_once(root, attempt / name, python=python, run_command=run_command)
        comparison = compare_runs(attempt / "run-1", attempt / "run-2")
        summary["comparison"] = comparison
        if not comparison["byte_identical"]:
            raise RuntimeError("independent Gate 0 executions produced different evidence")
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        _write_json(attempt / "summary.json", summary)
        raise
    summary["status"] = "passed"
    _write_json(attempt / "summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and compare lean Gate 0 twice")
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
    args = parser.parse_args(argv)
    try:
        if args.one_run:
            summary = run_gate0_once(args.root, args.results / args.one_run)
        elif args.compare_runs:
            first, second = args.compare_runs
            summary = compare_gate0_runs(
                args.results / first,
                args.results / second,
                args.results / "summary.json",
            )
        else:
            summary = run_gate0(args.root, args.results)
    except Exception as exc:
        print(f"Gate 0 failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
