"""Explicit fast-feedback and local-certification full-color profiles."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

from .runner_output import OutputMode, RunnerReporter, add_output_argument


RUNNER_SCHEMA = "full-color-harness-runner-v1"
DONOR_ORIGIN = "git@github.com:dannye/pokered-gbc.git"
DONOR_SHA = "c1a3b6c5a7591472241036d0cf09c3817f841f93"
CLEANUP_SHA = "cb6bb66dc91a7a162f442f3bd81ea2887558ada4"
PRE_CLEANUP_SHA = "a8b62fb990a13da6add30c92f8440b296dddce49"
FAST_COMPONENTS = (
    "build-products",
    "production-linkage",
    "phase2-audit",
    "smoke",
    "renderer-conformance",
    "renderer-runtime",
)
CERTIFY_COMPONENTS = (
    "build-products",
    "donor-provenance",
    "gate0",
    "phase2-audit",
    "renderer-conformance",
    "renderer-runtime",
    "cold-boot-journeys",
    "handoffs",
    "soak",
)


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    command: tuple[str, ...]
    evidence: Path | None
    stdout: Path
    stderr: Path
    junit: Path | None
    environment: tuple[tuple[str, str], ...] = ()


RunCommand = Callable[[Sequence[str], Path, Path, Path, Mapping[str, str]], int]


class SetupError(RuntimeError):
    """The requested profile cannot start with the available authorities."""


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _new_attempt(results_root: Path) -> Path:
    results_root.mkdir(parents=True, exist_ok=True)
    for number in range(1, 1_000_000):
        candidate = results_root / f"attempt-{number:04d}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise SetupError("full-color harness results contain too many attempts")


def _pytest(
    python: str, attempt: Path, name: str, *arguments: str
) -> tuple[tuple[str, ...], Path]:
    junit = attempt / "diagnostics" / f"{name}.junit.xml"
    return (python, "-m", "pytest", *arguments, "--junitxml", str(junit)), junit


def components(
    profile: str, root: Path, results: Path, *, python: str = sys.executable
) -> tuple[Component, ...]:
    """Return the exact immutable command graph for the selected profile."""
    if profile not in {"fast", "certify"}:
        raise SetupError(f"unknown full-color harness profile: {profile}")
    root = root.resolve()
    attempt = results.resolve()
    diagnostics = attempt / "diagnostics"
    evidence = attempt / "components"
    cpu_count = max(1, os.cpu_count() or 1)

    commands: dict[str, tuple[tuple[str, ...], Path | None, Path | None]] = {}
    commands["build-products"] = (
        (
            "make",
            f"-j{cpu_count}",
            "pokeyellow.gbc",
            "pokeyellow_debug.gbc",
            "pokeyellow_vc.gbc",
            "pokeyellow_phase2_audit.gbc",
        ),
        None,
        None,
    )
    production, production_junit = _pytest(
        python,
        attempt,
        "production-linkage",
        "tools/rom_tests/tests/unit/full_color/test_production_color_mode_linkage_rom.py",
        "tools/rom_tests/tests/unit/full_color/test_phase1_runtime_rom.py",
    )
    commands["production-linkage"] = (
        production,
        None,
        production_junit,
    )
    commands["phase2-audit"] = (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.phase2_measurements",
            "--root",
            str(root),
            "--output",
            str(root / "specs/full-colors/evidence/phase2-hostile-slice-representation.json"),
            "--verify",
        ),
        root / "specs/full-colors/evidence/phase2-hostile-slice-representation.json",
        None,
    )
    commands["smoke"] = (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.runtime_observability",
            "--root",
            str(root),
            "--results",
            str(evidence / "smoke"),
            "--output",
            OutputMode.JSON.value,
        ),
        evidence / "smoke",
        None,
    )
    commands["renderer-conformance"] = (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.renderer_conformance_runner",
            "--root",
            str(root),
            "--results",
            str(evidence / "renderer-conformance"),
            "--output",
            OutputMode.JSON.value,
        ),
        evidence / "renderer-conformance",
        None,
    )
    commands["renderer-runtime"] = (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.renderer_runtime_runner",
            "--root",
            str(root),
            "--results",
            str(evidence / "renderer-runtime"),
            "--output",
            OutputMode.JSON.value,
        ),
        evidence / "renderer-runtime",
        None,
    )
    donor, donor_junit = _pytest(
        python,
        attempt,
        "donor-provenance",
        "tools/rom_tests/tests/unit/full_color/test_overworld_color_data_donor.py::test_exact_pokered_gbc_donor_contract",
    )
    commands["donor-provenance"] = (
        donor,
        None,
        donor_junit,
    )
    commands["gate0"] = (
        (
            python,
            "-m",
            "tools.rom_tests.full_color.gate0_runner",
            "--root",
            str(root),
            "--results",
            str(evidence / "gate0"),
            "--output",
            OutputMode.JSON.value,
        ),
        evidence / "gate0",
        None,
    )
    cold_boot, cold_boot_junit = _pytest(
        python,
        attempt,
        "cold-boot-journeys",
        "tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py",
    )
    cold_boot_evidence = evidence / "cold-boot-journeys"
    commands["cold-boot-journeys"] = (
        cold_boot,
        cold_boot_evidence,
        cold_boot_junit,
    )
    handoffs, handoffs_junit = _pytest(
        python,
        attempt,
        "handoffs",
        "tools/rom_tests/tests/unit/full_color/test_model.py",
        "-k",
        "handoff or reconstruction or reset",
    )
    commands["handoffs"] = (
        handoffs,
        None,
        handoffs_junit,
    )
    soak, soak_junit = _pytest(
        python,
        attempt,
        "soak",
        "tools/rom_tests/tests/unit/full_color/test_model.py",
        "-k",
        "seeded_valid_sequences",
    )
    commands["soak"] = (soak, None, soak_junit)

    names = FAST_COMPONENTS if profile == "fast" else CERTIFY_COMPONENTS
    return tuple(
        Component(
            name=name,
            command=commands[name][0],
            evidence=commands[name][1],
            stdout=diagnostics / f"{name}.stdout.txt",
            stderr=diagnostics / f"{name}.stderr.txt",
            junit=commands[name][2],
            environment=(
                (("FULL_COLOR_COLD_BOOT_RESULTS", str(cold_boot_evidence)),)
                if name == "cold-boot-journeys"
                else ()
            ),
        )
        for name in names
    )


def _default_run_command(
    command: Sequence[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    environment: Mapping[str, str],
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(
            tuple(command),
            cwd=cwd,
            env=dict(environment),
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    return completed.returncode


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise SetupError(completed.stderr.strip() or "donor git command failed")
    return completed.stdout.strip()


def _donor_authority(root: Path) -> Path:
    try:
        workspace = root.resolve().parents[2]
    except IndexError as exc:
        raise SetupError("repository is not inside the expected uberepo task layout") from exc
    authority = (workspace / ".references" / "pokered-gbc").resolve()
    configured = os.environ.get("POKERED_GBC_ROOT")
    if configured is not None and Path(configured).resolve() != authority:
        raise SetupError(
            f"POKERED_GBC_ROOT must resolve to the pinned uberepo authority: {authority}"
        )
    if not authority.is_dir():
        raise SetupError(f"pinned pokered-gbc authority is missing: {authority}")
    if _git(authority, "rev-parse", "--is-inside-work-tree") != "true":
        raise SetupError(f"pinned pokered-gbc authority is not a git worktree: {authority}")
    origin = _git(authority, "remote", "get-url", "origin")
    head = _git(authority, "rev-parse", "HEAD")
    parent = _git(authority, "rev-parse", f"{CLEANUP_SHA}^")
    if origin != DONOR_ORIGIN:
        raise SetupError(f"wrong donor origin: {origin}")
    if head != DONOR_SHA:
        raise SetupError(f"wrong donor HEAD: {head}")
    if parent != PRE_CLEANUP_SHA:
        raise SetupError(f"wrong cleanup parent: {parent}")
    return authority


def _link(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def run_profile(
    profile: str,
    root: Path,
    results: Path,
    output: OutputMode,
    *,
    python: str = sys.executable,
    run_command: RunCommand = _default_run_command,
    reporter: RunnerReporter | None = None,
) -> dict[str, object]:
    """Run fail-fast and retain an aggregate summary linking component evidence."""
    root = root.resolve()
    reporter = reporter or RunnerReporter(profile, output)
    base_summary: dict[str, object] = {
        "schema": RUNNER_SCHEMA,
        "profile": profile,
        "attempt": None,
        "status": "setup-error",
        "exit_code": 2,
        "components": [],
    }
    try:
        attempt = _new_attempt(results.resolve())
    except (OSError, SetupError) as exc:
        base_summary["error"] = f"{type(exc).__name__}: {exc}"
        if output is OutputMode.HUMAN:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            print(f"FAIL setup: {message}", file=reporter.stderr)
        reporter.finish(base_summary, None)
        return base_summary
    reporter.attempt(attempt)
    reporter.stdout.flush()
    summary_path = attempt / "summary.json"
    rows: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "schema": RUNNER_SCHEMA,
        "profile": profile,
        "attempt": attempt.name,
        "status": "running",
        "exit_code": 0,
        "components": rows,
    }
    try:
        _write_json(summary_path, summary)
    except OSError as exc:
        detail = attempt / "diagnostics" / "setup.stderr.txt"
        try:
            detail.parent.mkdir(parents=True, exist_ok=True)
            detail.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        except OSError:
            detail = attempt
        summary.update(
            status="setup-error",
            exit_code=2,
            setup_error=_link(root, detail),
            error=f"{type(exc).__name__}: {exc}",
        )
        try:
            _write_json(summary_path, summary)
        except OSError:
            summary_path = None
        reporter.failed("setup", exc, detail)
        reporter.finish(summary, summary_path)
        return summary

    environment = dict(os.environ)
    try:
        graph = components(profile, root, attempt, python=python)
        if profile == "certify":
            environment["POKERED_GBC_ROOT"] = str(_donor_authority(root))
    except (OSError, SetupError) as exc:
        detail = attempt / "diagnostics" / "setup.stderr.txt"
        detail.parent.mkdir(parents=True, exist_ok=True)
        detail.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        summary.update(status="setup-error", exit_code=2, setup_error=_link(root, detail))
        _write_json(summary_path, summary)
        reporter.failed("setup", exc, detail)
        reporter.finish(summary, summary_path)
        return summary

    for component in graph:
        component.stdout.parent.mkdir(parents=True, exist_ok=True)
        component.stdout.touch()
        component.stderr.touch()
        if component.evidence is not None and component.evidence.suffix == "":
            component.evidence.mkdir(parents=True, exist_ok=True)
        if component.junit is not None:
            component.junit.parent.mkdir(parents=True, exist_ok=True)
            component.junit.touch()
        row: dict[str, object] = {
            "name": component.name,
            "status": "running",
            "stdout": _link(root, component.stdout),
            "stderr": _link(root, component.stderr),
            "evidence": _link(root, component.evidence),
            "junit": _link(root, component.junit),
        }
        rows.append(row)
        _write_json(summary_path, summary)
        started = reporter.running(component.name)
        reporter.stdout.flush()
        try:
            returncode = run_command(
                component.command,
                root,
                component.stdout,
                component.stderr,
                environment | dict(component.environment),
            )
        except Exception as exc:  # retain an executor failure like a failed check
            with component.stderr.open("a", encoding="utf-8") as stream:
                stream.write(f"runner exception: {exc}\n")
            returncode = -1
        row.update(
            status="passed" if returncode == 0 else "failed",
            returncode=returncode,
        )
        if returncode:
            error = RuntimeError(f"component exited {returncode}")
            summary.update(status="failed", exit_code=1)
            _write_json(summary_path, summary)
            reporter.failed(component.name, error, component.stderr)
            reporter.finish(summary, summary_path)
            return summary
        reporter.passed(component.name, started)
        _write_json(summary_path, summary)

    summary.update(status="passed", exit_code=0)
    _write_json(summary_path, summary)
    reporter.finish(summary, summary_path)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("fast", "certify"), required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--results", type=Path, required=True)
    add_output_argument(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = run_profile(args.profile, args.root, args.results, args.output)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
