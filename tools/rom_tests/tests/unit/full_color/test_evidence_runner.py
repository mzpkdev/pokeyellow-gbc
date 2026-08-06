"""Deterministic evidence orchestration and retained failure artifacts."""

import json
from pathlib import Path
from typing import Sequence

import pytest

from tools.rom_tests.full_color import evidence_runner

from tools.rom_tests.full_color.evidence_runner import (
    COMPONENTS,
    capture_evidence_once,
    compare_evidence_runs,
    run_evidence_determinism,
)


def _fake_runner(*, fail: str | None = None):
    calls: list[tuple[str, ...]] = []

    def run(
        command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
    ) -> int:
        del cwd
        command = tuple(command)
        calls.append(command)
        module = command[command.index("-m") + 1]
        component = {
            "runtime_observability": "observability",
            "traceability": "traceability",
            "visual_pipeline": "visual-pipeline",
        }[module.rsplit(".", 1)[-1]]
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text('{"stable":true}\n', encoding="utf-8")
        stderr_path.write_text(
            "intentional failure\n" if component == fail else "", encoding="utf-8"
        )
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


def test_json_failure_uses_current_attempt_not_malformed_stale_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results"
    stale = results / "attempt-9999"
    stale.mkdir(parents=True)
    (stale / "summary.json").write_text("{malformed", encoding="utf-8")

    def fail_current(root: Path, results_root: Path, *, reporter, **kwargs):
        del root, kwargs
        attempt = evidence_runner._new_attempt(results_root.resolve())
        reporter.attempt(attempt)
        summary = {"attempt": attempt.name, "status": "failed", "error": "current"}
        evidence_runner._write_json(attempt / "summary.json", summary)
        raise RuntimeError("current")

    monkeypatch.setattr(evidence_runner, "run_evidence_determinism", fail_current)
    assert evidence_runner.main(
        ["--results", str(results), "--output", "json"]
    ) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["attempt"] == "attempt-0001"
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_runner_executes_every_real_component_twice_and_compares_bytes(
    tmp_path: Path,
) -> None:
    calls, fake = _fake_runner()
    root = tmp_path / "repo"
    root.mkdir()

    summary = run_evidence_determinism(
        root, tmp_path / "results", python="repo-python", run_command=fake
    )

    assert summary["status"] == "passed"
    assert summary["schema"] == "full-color-evidence-runner-v1"
    assert len(calls) == 2 * len(COMPONENTS)
    assert [
        command[command.index("-m") + 1] for command in calls[: len(COMPONENTS)]
    ] == [
        "tools.rom_tests.full_color.runtime_observability",
        "tools.rom_tests.full_color.traceability",
        "tools.rom_tests.full_color.visual_pipeline",
    ]
    assert calls[0] == (
        "repo-python",
        "-m",
        "tools.rom_tests.full_color.runtime_observability",
        "--root",
        str(root),
        "--snapshot-output",
        str(
            tmp_path
            / "results/attempt-0001/run-1/semantic-snapshot.json"
        ),
        "--diagnostics-output",
        str(
            tmp_path
            / "results/attempt-0001/run-1/diagnostics/runtime-observability"
        ),
    )
    assert summary["comparison"]["byte_identical"] is True
    assert summary["comparison"]["semantic_snapshot_byte_identical"] is True
    assert summary["comparison"]["traceability_report_byte_identical"] is True
    assert summary["comparison"]["versioned_manifest_byte_identical"] is True
    attempt = tmp_path / "results" / summary["attempt"]
    assert (attempt / "run-1/visual/linked.png").is_file()
    assert (attempt / "run-2/visual/linked.png").is_file()


def test_cli_json_mode_emits_one_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(root: Path, results: Path, *, reporter):
        del root
        attempt = results / "attempt-0001"
        attempt.mkdir(parents=True)
        reporter.attempt(attempt)
        return {"status": "passed", "attempt": attempt.name}

    monkeypatch.setattr(evidence_runner, "run_evidence_determinism", run)
    assert evidence_runner.main(
        ["--results", str(tmp_path), "--output", "json"]
    ) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "attempt": "attempt-0001",
        "status": "passed",
    }
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_independent_runs_execute_every_component_once_and_compare(tmp_path: Path) -> None:
    calls, fake = _fake_runner()
    root = tmp_path / "repo"
    root.mkdir()
    results = tmp_path / "results"

    first = capture_evidence_once(root, results / "run-1", run_command=fake)
    second = capture_evidence_once(root, results / "run-2", run_command=fake)
    summary = compare_evidence_runs(
        results / "run-1", results / "run-2", results / "summary.json"
    )

    assert first["status"] == second["status"] == "passed"
    assert first["schema"] == second["schema"] == "full-color-evidence-runner-v1"
    assert len(calls) == 2 * len(COMPONENTS)
    assert summary["status"] == "passed"
    assert summary["schema"] == "full-color-evidence-runner-v1"
    assert summary["comparison"]["byte_identical"] is True
    assert json.loads((results / "summary.json").read_text())["status"] == "passed"


def test_independent_compare_rejects_failed_or_incomplete_run(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    results = tmp_path / "results"
    _, passing = _fake_runner()
    _, failing = _fake_runner(fail="observability")
    capture_evidence_once(root, results / "run-1", run_command=passing)
    with pytest.raises(RuntimeError, match="observability failed"):
        capture_evidence_once(root, results / "run-2", run_command=failing)

    with pytest.raises(RuntimeError, match="did not pass"):
        compare_evidence_runs(
            results / "run-1", results / "run-2", results / "summary.json"
        )

    summary = json.loads((results / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert "run-2" in summary["error"]


def test_independent_compare_rejects_retired_runner_schema(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    results = tmp_path / "results"
    _, passing = _fake_runner()
    capture_evidence_once(root, results / "run-1", run_command=passing)
    capture_evidence_once(root, results / "run-2", run_command=passing)
    run_summary_path = results / "run-2/run-summary.json"
    run_summary = json.loads(run_summary_path.read_text())
    retired_stage = "".join(("ga", "te", chr(ord("1") - 1)))
    run_summary["schema"] = f"full-color-{retired_stage}-runner-v1"
    assert run_summary["schema"].endswith("0-runner-v1")
    run_summary_path.write_text(json.dumps(run_summary), encoding="utf-8")

    with pytest.raises(RuntimeError, match="incompatible schema"):
        compare_evidence_runs(
            results / "run-1", results / "run-2", results / "summary.json"
        )

    summary = json.loads((results / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert "incompatible schema" in summary["error"]


@pytest.mark.parametrize(
    "component_names",
    (
        ("observability", "traceability"),
        ("observability", "traceability", "visual-pipeline", "unit-tests"),
        ("observability", "traceability", "renderer-pipeline"),
    ),
    ids=("missing", "extra", "renamed"),
)
def test_independent_compare_rejects_noncanonical_component_graph(
    tmp_path: Path,
    component_names: tuple[str, ...],
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    results = tmp_path / "results"
    _, passing = _fake_runner()
    capture_evidence_once(root, results / "run-1", run_command=passing)
    capture_evidence_once(root, results / "run-2", run_command=passing)
    run_summary_path = results / "run-2/run-summary.json"
    run_summary = json.loads(run_summary_path.read_text())
    run_summary["components"] = [
        {"name": component_name} for component_name in component_names
    ]
    run_summary_path.write_text(json.dumps(run_summary), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected component graph"):
        compare_evidence_runs(
            results / "run-1", results / "run-2", results / "summary.json"
        )

    summary = json.loads((results / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert "unexpected component graph" in summary["error"]


def test_independent_compare_rejects_missing_or_nonidentical_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    results = tmp_path / "results"
    _, passing = _fake_runner()
    capture_evidence_once(root, results / "run-1", run_command=passing)

    with pytest.raises(RuntimeError, match="missing its summary"):
        compare_evidence_runs(
            results / "run-1", results / "run-2", results / "summary.json"
        )

    capture_evidence_once(root, results / "run-2", run_command=passing)
    (results / "run-2/semantic-snapshot.json").write_bytes(b"different\n")
    with pytest.raises(RuntimeError, match="produced different evidence"):
        compare_evidence_runs(
            results / "run-1", results / "run-2", results / "summary.json"
        )

    summary = json.loads((results / "summary.json").read_text())
    assert summary["comparison"]["semantic_snapshot_byte_identical"] is False


def test_failure_retains_logs_summary_and_previous_attempt(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _, passing = _fake_runner()
    first = run_evidence_determinism(
        root, tmp_path / "results", run_command=passing
    )
    first_summary = tmp_path / "results" / first["attempt"] / "summary.json"
    original = first_summary.read_bytes()
    _, failing = _fake_runner(fail="observability")

    with pytest.raises(RuntimeError, match="observability failed"):
        run_evidence_determinism(root, tmp_path / "results", run_command=failing)

    assert first_summary.read_bytes() == original
    failed = tmp_path / "results/attempt-0002"
    summary = json.loads((failed / "summary.json").read_text())
    run_summary = json.loads((failed / "run-1/run-summary.json").read_text())
    assert summary["status"] == "failed"
    assert run_summary["failed_component"] == "observability"
    assert (failed / "run-1/diagnostics/observability.stderr.txt").read_text() == (
        "intentional failure\n"
    )
    assert not (failed / "run-2").exists()


def test_failing_component_retains_diagnostics_and_stops_first_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls, failing = _fake_runner(fail="observability")

    with pytest.raises(RuntimeError, match="observability failed"):
        run_evidence_determinism(root, tmp_path / "results", run_command=failing)

    run = tmp_path / "results/attempt-0001/run-1"
    assert len(calls) == 1
    assert (run / "diagnostics/observability.stdout.txt").is_file()
    assert (run / "diagnostics/observability.stderr.txt").read_text() == (
        "intentional failure\n"
    )
    assert json.loads((run / "run-summary.json").read_text())["failed_component"] == (
        "observability"
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
        run_evidence_determinism(root, tmp_path / "results", run_command=divergent)

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
        run_evidence_determinism(root, tmp_path / "results", run_command=divergent)

    assert len(calls) == 2 * len(COMPONENTS)
    summary = json.loads(
        (tmp_path / "results/attempt-0001/summary.json").read_text()
    )
    assert "traceability-report.json" in summary["comparison"]["changed"]


def test_second_run_manifest_mutation_fails_with_exact_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls, stable = _fake_runner()

    def divergent(
        command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path
    ) -> int:
        returncode = stable(command, cwd, stdout_path, stderr_path)
        if command[command.index("-m") + 1].endswith("visual_pipeline"):
            output = Path(command[command.index("--output") + 1])
            if output.parent.name == "run-2":
                (output / "manifest.json").write_bytes(
                    b'{"schema":"mutated-manifest-v1"}\n'
                )
        return returncode

    with pytest.raises(RuntimeError, match="produced different evidence"):
        run_evidence_determinism(root, tmp_path / "results", run_command=divergent)

    assert len(calls) == 2 * len(COMPONENTS)
    summary = json.loads(
        (tmp_path / "results/attempt-0001/summary.json").read_text()
    )
    assert summary["comparison"]["versioned_manifest_byte_identical"] is False
    assert summary["comparison"]["changed"] == ["visual/manifest.json"]
