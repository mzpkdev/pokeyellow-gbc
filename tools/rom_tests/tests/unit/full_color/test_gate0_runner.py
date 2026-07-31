"""Lean Gate 0 orchestration and retained failure artifacts."""

import json
from pathlib import Path
from typing import Sequence

import pytest

from tools.rom_tests.full_color.gate0_runner import COMPONENTS, run_gate0


def _fake_runner(*, fail: str | None = None):
    calls: list[tuple[str, ...]] = []

    def run(
        command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
    ) -> int:
        del cwd
        command = tuple(command)
        calls.append(command)
        module = command[command.index("-m") + 1]
        component = (
            "unit-tests"
            if module == "pytest"
            else module.rsplit(".", 1)[-1].replace("_", "-")
        )
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text('{"stable":true}\n', encoding="utf-8")
        stderr_path.write_text(
            "intentional failure\n" if component == fail else "", encoding="utf-8"
        )
        if module == "pytest":
            junit = Path(command[command.index("--junitxml") + 1])
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.write_text("<testsuites/>", encoding="utf-8")
        if module.endswith("runtime_observability"):
            output = Path(command[command.index("--snapshot-output") + 1])
            output.write_bytes(b'{"schema":"semantic-v1"}\n')
            diagnostics = Path(command[command.index("--diagnostics-output") + 1])
            diagnostics.mkdir(parents=True, exist_ok=True)
            (diagnostics / "emulator.log").write_text("diagnostic", encoding="utf-8")
        if module.endswith("traceability"):
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b'{"schema":"traceability-v1"}\n')
        if module.endswith("visual_pipeline"):
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True)
            (output / "manifest.json").write_bytes(b'{"schema":"manifest-v1"}\n')
            (output / "linked.png").write_bytes(b"stable image")
        return 7 if component == fail else 0

    return calls, run


def test_runner_executes_every_real_component_twice_and_compares_bytes(
    tmp_path: Path,
) -> None:
    calls, fake = _fake_runner()
    root = tmp_path / "repo"
    root.mkdir()

    summary = run_gate0(root, tmp_path / "results", python="repo-python", run_command=fake)

    assert summary["status"] == "passed"
    assert len(calls) == 2 * len(COMPONENTS)
    assert [
        command[command.index("-m") + 1] for command in calls[: len(COMPONENTS)]
    ] == [
        "pytest",
        "tools.rom_tests.full_color.baseline_discovery",
        "tools.rom_tests.full_color.baseline_inventory",
        "tools.rom_tests.full_color.bank_torture",
        "tools.rom_tests.full_color.runtime_observability",
        "tools.rom_tests.full_color.traceability",
        "tools.rom_tests.full_color.visual_pipeline",
    ]
    assert summary["comparison"]["byte_identical"] is True
    assert summary["comparison"]["semantic_snapshot_byte_identical"] is True
    assert summary["comparison"]["traceability_report_byte_identical"] is True
    assert summary["comparison"]["versioned_manifest_byte_identical"] is True
    attempt = tmp_path / "results" / summary["attempt"]
    assert (attempt / "run-1/visual/linked.png").is_file()
    assert (attempt / "run-2/visual/linked.png").is_file()


def test_failure_retains_logs_summary_and_previous_attempt(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _, passing = _fake_runner()
    first = run_gate0(root, tmp_path / "results", run_command=passing)
    first_summary = tmp_path / "results" / first["attempt"] / "summary.json"
    original = first_summary.read_bytes()
    _, failing = _fake_runner(fail="bank-torture")

    with pytest.raises(RuntimeError, match="bank-torture failed"):
        run_gate0(root, tmp_path / "results", run_command=failing)

    assert first_summary.read_bytes() == original
    failed = tmp_path / "results/attempt-0002"
    summary = json.loads((failed / "summary.json").read_text())
    run_summary = json.loads((failed / "run-1/run-summary.json").read_text())
    assert summary["status"] == "failed"
    assert run_summary["failed_component"] == "bank-torture"
    assert (failed / "run-1/diagnostics/bank-torture.stderr.txt").read_text() == (
        "intentional failure\n"
    )
    assert not (failed / "run-2").exists()


def test_failing_pytest_retains_junit_and_stops_first_run(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls, failing = _fake_runner(fail="unit-tests")

    with pytest.raises(RuntimeError, match="unit-tests failed"):
        run_gate0(root, tmp_path / "results", run_command=failing)

    run = tmp_path / "results/attempt-0001/run-1"
    assert len(calls) == 1
    assert (run / "diagnostics/unit-tests.junit.xml").is_file()
    assert (run / "diagnostics/unit-tests.stdout.txt").is_file()
    assert (run / "diagnostics/unit-tests.stderr.txt").read_text() == (
        "intentional failure\n"
    )
    assert json.loads((run / "run-summary.json").read_text())["failed_component"] == (
        "unit-tests"
    )


def test_semantic_difference_fails_with_exact_changed_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls, stable = _fake_runner()

    def divergent(
        command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
    ) -> int:
        returncode = stable(command, cwd, stdout_path, stderr_path)
        if "runtime_observability" in command[command.index("-m") + 1]:
            output = Path(command[command.index("--snapshot-output") + 1])
            if output.parent.name == "run-2":
                output.write_bytes(b'{"schema":"mutated-semantic-v1"}\n')
        return returncode

    with pytest.raises(RuntimeError, match="produced different evidence"):
        run_gate0(root, tmp_path / "results", run_command=divergent)

    assert len(calls) == 2 * len(COMPONENTS)
    summary = json.loads(
        (tmp_path / "results/attempt-0001/summary.json").read_text()
    )
    assert summary["comparison"]["semantic_snapshot_byte_identical"] is False
    assert "semantic-snapshot.json" in summary["comparison"]["changed"]


def test_second_run_traceability_mutation_fails_with_exact_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls, stable = _fake_runner()

    def divergent(
        command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
    ) -> int:
        returncode = stable(command, cwd, stdout_path, stderr_path)
        if command[command.index("-m") + 1].endswith("traceability"):
            output = Path(command[command.index("--output") + 1])
            if output.parent.name == "run-2":
                output.write_bytes(b'{"schema":"mutated-traceability-v1"}\n')
        return returncode

    with pytest.raises(RuntimeError, match="produced different evidence"):
        run_gate0(root, tmp_path / "results", run_command=divergent)

    assert len(calls) == 2 * len(COMPONENTS)
    summary = json.loads(
        (tmp_path / "results/attempt-0001/summary.json").read_text()
    )
    assert "traceability-report.json" in summary["comparison"]["changed"]
