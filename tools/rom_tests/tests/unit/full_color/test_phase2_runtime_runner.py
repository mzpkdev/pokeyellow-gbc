from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.phase2_runtime_runner import (
    compare_stable_phase2_evidence, new_attempt, run_phase2_runtime,
)
from tools.rom_tests.full_color.phase2_runtime_observability import GuardedAuditIdentity


def test_numbered_attempts_never_reuse_a_directory(tmp_path: Path) -> None:
    assert new_attempt(tmp_path).name == "attempt-0001"
    assert new_attempt(tmp_path).name == "attempt-0002"


def test_stable_comparison_includes_timing_and_png_but_excludes_run_summary(tmp_path: Path) -> None:
    for name in ("run-1", "run-2"):
        run = tmp_path / name
        (run / "visuals").mkdir(parents=True)
        (run / "timing.json").write_text("timing\n", encoding="utf-8")
        (run / "visuals/screenshot.png").write_bytes(b"png")
        (run / "run-summary.json").write_text(name, encoding="utf-8")
    comparison = compare_stable_phase2_evidence(tmp_path / "run-1", tmp_path / "run-2")
    assert comparison["byte_identical"] is True
    assert set(comparison["sha256"]) == {"timing.json", "visuals/screenshot.png"}


def test_first_capture_failure_does_not_stop_second_and_retains_errors(tmp_path: Path, monkeypatch) -> None:
    identity = GuardedAuditIdentity(*( "0" * 64 for _ in range(4)))
    monkeypatch.setattr("tools.rom_tests.full_color.phase2_runtime_runner.require_committed_guarded_audit", lambda root: identity)
    calls = []
    def capture(root: Path, run: Path, timing: Path) -> None:
        calls.append(run.name)
        raise RuntimeError("capture flatlined")
    timing = tmp_path / "timing-source.json"
    timing.write_text("{}", encoding="utf-8")
    with pytest.raises(RendererConformanceError, match="retained under"):
        run_phase2_runtime(tmp_path, tmp_path / "results", timing, capture=capture)
    assert calls == ["run-1.incomplete", "run-2.incomplete"]
    attempt = tmp_path / "results/attempt-0001"
    for name in ("run-1", "run-2"):
        error = json.loads((attempt / name / "run-error.json").read_text())
        assert error["status"] == "failed"
        assert error["error"] == "capture flatlined"
    assert json.loads((attempt / "summary.json").read_text())["status"] == "failed"
