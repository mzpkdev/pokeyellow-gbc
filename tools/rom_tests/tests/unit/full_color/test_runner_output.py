from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.rom_tests.full_color import runner_output
from tools.rom_tests.full_color.runner_output import OutputMode, RunnerReporter


ROOT = Path(__file__).resolve().parents[5]
CLI_MODULES = (
    "tools.rom_tests.full_color.evidence_runner",
    "tools.rom_tests.full_color.renderer_conformance_runner",
    "tools.rom_tests.full_color.renderer_runtime_runner",
    "tools.rom_tests.full_color.runtime_observability",
)


def _reporter(mode: OutputMode | None) -> tuple[RunnerReporter, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    return RunnerReporter("profile", mode, stdout, stderr), stdout, stderr


def test_human_progress_is_bounded_relative_and_presentation_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_output.time, "monotonic", iter((10.0, 10.25)).__next__)
    reporter, stdout, stderr = _reporter(OutputMode.HUMAN)
    attempt = tmp_path / "results with spaces" / "attempt-0001"

    reporter.attempt(attempt)
    started = reporter.running("component")
    reporter.passed("component", started)
    reporter.finish({"status": "passed"}, attempt / "summary.json")

    lines = stdout.getvalue().splitlines()
    assert lines[0] == "RUN profile evidence='results with spaces/attempt-0001'"
    assert lines[1:] == [
        "RUN component",
        "PASS component 0.25s",
        "PASS profile summary='results with spaces/attempt-0001/summary.json'",
    ]
    assert stderr.getvalue() == ""


def test_json_mode_emits_exactly_one_canonical_document() -> None:
    reporter, stdout, stderr = _reporter(OutputMode.JSON)
    reporter.attempt(Path("attempt"))
    started = reporter.running("component")
    reporter.passed("component", started)
    reporter.finish({"z": 1, "status": "passed", "a": [2]}, None)

    assert stdout.getvalue() == '{"a":[2],"status":"passed","z":1}\n'
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert stderr.getvalue() == ""


def test_human_failure_is_bounded_and_preserves_retained_detail(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    detail = tmp_path / "attempt with spaces" / "diagnostics" / "failure.txt"
    detail.parent.mkdir(parents=True)
    detail.write_text("full\ntraceback\nwith\nall\nlines\n", encoding="utf-8")
    reporter, _, stderr = _reporter(OutputMode.HUMAN)

    reporter.failed("unit-tests", RuntimeError("actionable\nnoise\nmore"), detail)
    reporter.failed("unit-tests", RuntimeError("duplicate"), detail)

    lines = stderr.getvalue().splitlines()
    assert len(lines) <= 5
    assert lines == [
        "FAIL unit-tests: actionable",
        "EVIDENCE 'attempt with spaces/diagnostics/failure.txt'",
    ]
    assert "full\ntraceback" in detail.read_text(encoding="utf-8")


def test_path_outside_repository_falls_back_to_absolute_path(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.chdir(repository)
    detail = tmp_path / "external evidence" / "failure.txt"
    reporter, _, stderr = _reporter(OutputMode.HUMAN)

    reporter.failed("component", RuntimeError("failure"), detail)

    assert detail.resolve().as_posix() in stderr.getvalue()


def test_null_mode_is_a_noop() -> None:
    reporter, stdout, stderr = _reporter(None)
    reporter.attempt(Path("attempt"))
    started = reporter.running("component")
    reporter.passed("component", started)
    reporter.failed("component", RuntimeError("failure"), Path("detail"))
    reporter.finish({"status": "passed"}, None)
    assert stdout.getvalue() == stderr.getvalue() == ""


@pytest.mark.parametrize("module", CLI_MODULES)
def test_invalid_output_environment_is_argparse_error_without_traceback(
    module: str,
) -> None:
    environment = os.environ.copy()
    environment["FULL_COLOR_OUTPUT"] = "invalid"
    arguments = ["--results", "unused"] if module != CLI_MODULES[-1] else []
    completed = subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert len(completed.stderr.splitlines()) <= 8
    assert "invalid OutputMode value" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    "module",
    (
        "tools.rom_tests.full_color.renderer_runtime_runner",
        "tools.rom_tests.full_color.runtime_observability",
    ),
)
def test_fresh_process_help_has_clean_stderr_in_json_mode(module: str) -> None:
    environment = os.environ.copy()
    environment["FULL_COLOR_OUTPUT"] = "json"
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
