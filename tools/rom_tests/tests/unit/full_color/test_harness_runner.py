"""Contracts for the explicit full-color harness profiles."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

from tools.rom_tests.full_color.harness_runner import (
    CERTIFY_COMPONENTS,
    CLEANUP_SHA,
    DONOR_ORIGIN,
    DONOR_SHA,
    FAST_COMPONENTS,
    PRE_CLEANUP_SHA,
    Component,
    components,
    main,
    run_profile,
)
from tools.rom_tests.full_color.runner_output import OutputMode, RunnerReporter


ROOT = Path(__file__).parents[5]


def _reporter(profile: str, mode: OutputMode) -> RunnerReporter:
    return RunnerReporter(profile, mode, stdout=io.StringIO(), stderr=io.StringIO())


def test_component_membership_and_order_are_exact_and_immutable(tmp_path: Path) -> None:
    fast = components("fast", ROOT, tmp_path / "fast", python="repo-python")
    certify = components("certify", ROOT, tmp_path / "certify", python="repo-python")
    assert tuple(item.name for item in fast) == FAST_COMPONENTS
    assert tuple(item.name for item in certify) == CERTIFY_COMPONENTS
    assert isinstance(fast, tuple)
    with pytest.raises((AttributeError, TypeError)):
        fast[0].name = "changed"  # type: ignore[misc]


def test_setup_pin_matches_the_exact_donor_comparator() -> None:
    from tools.rom_tests.tests.unit.full_color import test_overworld_color_data_donor

    assert DONOR_ORIGIN == test_overworld_color_data_donor.DONOR_ORIGIN
    assert DONOR_SHA == test_overworld_color_data_donor.DONOR_SHA
    assert CLEANUP_SHA == test_overworld_color_data_donor.CLEANUP_SHA
    assert PRE_CLEANUP_SHA == test_overworld_color_data_donor.PRE_CLEANUP_SHA


def test_certify_has_no_redundant_authority_component(tmp_path: Path) -> None:
    names = tuple(item.name for item in components("certify", ROOT, tmp_path))
    assert names == CERTIFY_COMPONENTS
    assert names[0] == "build-products"
    assert len(names) == len(set(names))
    assert names.count("unit-tests") == 1
    assert names.count("harness-contracts") == 1
    assert names.count("evidence-determinism") == 1
    assert names.count("donor-contract") == 1
    assert names.count("e2e-core") == 1
    assert names.count("e2e-renderer") == 1
    assert names.count("e2e-journey") == 1


def test_build_is_visible_first_and_builds_exactly_four_products(
    tmp_path: Path,
) -> None:
    build = components("fast", ROOT, tmp_path)[0]
    assert build.name == "build-products"
    assert build.command[0] == "make"
    assert build.command[1].startswith("-j")
    assert build.command[2:] == (
        "pokeyellow.gbc",
        "pokeyellow_debug.gbc",
        "pokeyellow_vc.gbc",
        "pokeyellow_phase2_audit.gbc",
    )


def test_profile_allocates_and_reports_attempt_before_resolving_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class RecordingReporter(RunnerReporter):
        def attempt(self, path: Path) -> None:
            events.append(f"attempt:{path.name}")
            super().attempt(path)

    def explode(*args: object, **kwargs: object) -> tuple[Component, ...]:
        events.append("components")
        raise OSError("deliberate setup failure")

    monkeypatch.setattr("tools.rom_tests.full_color.harness_runner.components", explode)
    reporter = RecordingReporter(
        "fast", OutputMode.HUMAN, stdout=io.StringIO(), stderr=io.StringIO()
    )
    summary = run_profile("fast", ROOT, tmp_path, OutputMode.HUMAN, reporter=reporter)
    assert events == ["attempt:attempt-0001", "components"]
    assert summary["status"] == "setup-error"
    assert summary["exit_code"] == 2
    assert (tmp_path / "attempt-0001/diagnostics/setup.stderr.txt").is_file()
    assert (tmp_path / "attempt-0001/summary.json").is_file()


def test_fail_fast_retains_complete_streams_junit_and_links(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def run(
        command: object,
        cwd: Path,
        stdout: Path,
        stderr: Path,
        environment: object,
    ) -> int:
        argv = tuple(command)  # type: ignore[arg-type]
        calls.append(argv)
        stdout.write_text("complete stdout\nsecond line\n", encoding="utf-8")
        stderr.write_text("complete stderr\nsecond line\n", encoding="utf-8")
        return 9 if len(calls) == 2 else 0

    reporter = _reporter("fast", OutputMode.HUMAN)
    summary = run_profile(
        "fast",
        ROOT,
        tmp_path / "results with spaces",
        OutputMode.HUMAN,
        python="repo python",
        run_command=run,
        reporter=reporter,
    )
    attempt = tmp_path / "results with spaces/attempt-0001"
    assert len(calls) == 2
    assert summary["status"] == "failed"
    assert summary["exit_code"] == 1
    assert [row["name"] for row in summary["components"]] == [
        "build-products",
        "production-linkage",
    ]
    failed = summary["components"][1]
    assert failed["returncode"] == 9
    assert Path(ROOT / str(failed["stdout"])).read_text(encoding="utf-8") == (
        "complete stdout\nsecond line\n"
    )
    assert Path(ROOT / str(failed["stderr"])).read_text(encoding="utf-8") == (
        "complete stderr\nsecond line\n"
    )
    assert (attempt / "diagnostics/production-linkage.junit.xml").is_file()
    persisted = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    assert persisted == summary
    assert "command" not in json.dumps(summary)


def test_success_runs_exact_commands_and_json_is_one_document(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def run(
        command: object,
        cwd: Path,
        stdout: Path,
        stderr: Path,
        environment: object,
    ) -> int:
        calls.append(tuple(command))  # type: ignore[arg-type]
        return 0

    reporter = _reporter("fast", OutputMode.JSON)
    summary = run_profile(
        "fast",
        ROOT,
        tmp_path,
        OutputMode.JSON,
        python="repo-python",
        run_command=run,
        reporter=reporter,
    )
    assert [call for call in calls] == [
        component.command
        for component in components(
            "fast", ROOT, tmp_path / "attempt-0001", python="repo-python"
        )
    ]
    rendered = reporter.stdout.getvalue()  # type: ignore[union-attr]
    assert json.loads(rendered) == summary
    assert len(rendered.splitlines()) == 1


def test_invalid_donor_is_setup_error_after_attempt_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tools.rom_tests.full_color.harness_runner._donor_authority",
        lambda root: (_ for _ in ()).throw(
            OSError("missing or identity-invalid donor authority")
        ),
    )
    calls: list[object] = []
    reporter = _reporter("certify", OutputMode.HUMAN)
    summary = run_profile(
        "certify",
        ROOT,
        tmp_path,
        OutputMode.HUMAN,
        run_command=lambda *args: calls.append(args) or 0,
        reporter=reporter,
    )
    assert calls == []
    assert summary["status"] == "setup-error"
    assert summary["exit_code"] == 2
    assert (tmp_path / "attempt-0001/summary.json").is_file()
    detail = tmp_path / "attempt-0001/diagnostics/setup.stderr.txt"
    assert "identity-invalid" in detail.read_text(encoding="utf-8")


def test_runner_components_delegate_to_dedicated_evidence_roots(tmp_path: Path) -> None:
    graph = {item.name: item for item in components("certify", ROOT, tmp_path)}
    for name in ("evidence-determinism", "renderer-contracts", "renderer-runtime"):
        component = graph[name]
        assert "--results" in component.command
        result = Path(component.command[component.command.index("--results") + 1])
        assert result == tmp_path.resolve() / "components" / name
        assert "--output" in component.command
        assert component.command[-1] == "json"
    donor = graph["donor-contract"]
    assert (
        donor.command.count(
            "tools/rom_tests/tests/unit/full_color/test_overworld_color_data_donor.py"
        )
        == 1
    )
    assert "-q" in donor.command


def test_certify_e2e_suites_use_attempt_local_evidence_and_environment(
    tmp_path: Path,
) -> None:
    attempt = tmp_path / "results with spaces" / "attempt-0042"
    graph = {item.name: item for item in components("certify", ROOT, attempt)}
    expected_root = attempt.resolve() / "components"
    for suite in ("core", "renderer", "journey"):
        component = graph[f"e2e-{suite}"]
        expected = expected_root / f"e2e-{suite}"
        assert component.evidence == expected
        assert component.environment == (("ROM_TEST_RESULTS", str(expected)),)
    journey = graph["e2e-journey"]
    assert journey.command == (
        sys.executable,
        "-m",
        "pytest",
        "tools/rom_tests/tests/e2e/journey",
        "-q",
        "--junitxml",
        str(attempt.resolve() / "diagnostics/e2e-journey.junit.xml"),
    )
    assert all(
        component.environment == ()
        for name, component in graph.items()
        if not name.startswith("e2e-")
    )


def test_shared_results_seam_preserves_default_and_accepts_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.rom_tests.tests.conftest import (
        DEFAULT_RESULTS_ROOT,
        configured_results_root,
        result_directory,
    )

    configured = tmp_path / "isolated test evidence"
    assert configured_results_root({}) == DEFAULT_RESULTS_ROOT.resolve()
    monkeypatch.setenv("ROM_TEST_RESULTS", str(configured))
    assert result_directory("suite::test case").parent == configured.resolve()


def test_cold_boot_results_seam_preserves_default_and_accepts_spaces(
    tmp_path: Path,
) -> None:
    from tools.rom_tests.tests.conftest import configured_results_root
    from tools.rom_tests.tests.e2e.journey import test_full_color_cold_boot_journey

    configured = tmp_path / "isolated cold boot evidence"
    assert (
        configured_results_root({}) / "full-color-cold-boot"
        == test_full_color_cold_boot_journey.DEFAULT_RESULTS_ROOT.resolve()
    )
    assert (
        configured_results_root({"ROM_TEST_RESULTS": str(configured)})
        / "full-color-cold-boot"
        == (configured / "full-color-cold-boot").resolve()
    )


def test_house_visual_cleanup_accepts_only_a_direct_configured_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.rom_tests.tests.e2e.renderer.test_full_color_house_palette_visual import (
        _prepare_results,
    )

    configured = tmp_path / "attempt evidence"
    results = configured / "house-round-trip"
    results.mkdir(parents=True)
    stale = results / "stale.png"
    stale.write_bytes(b"stale")
    retained_directory = results / "nested"
    retained_directory.mkdir()
    monkeypatch.setenv("ROM_TEST_RESULTS", str(configured))

    _prepare_results(results)
    assert not stale.exists()
    assert retained_directory.is_dir()

    sibling = tmp_path / "sibling"
    with pytest.raises(AssertionError, match="refusing to clean unexpected result path"):
        _prepare_results(sibling)
    nested_child = configured / "nested" / "scenario"
    with pytest.raises(AssertionError, match="refusing to clean unexpected result path"):
        _prepare_results(nested_child)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_outside = configured / "linked-outside"
    linked_outside.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AssertionError, match="refusing to clean unexpected result path"):
        _prepare_results(linked_outside)


def test_results_environment_is_passed_only_to_e2e_components(tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}

    def run(
        command: object,
        cwd: Path,
        stdout: Path,
        stderr: Path,
        environment: object,
    ) -> int:
        argv = tuple(command)  # type: ignore[arg-type]
        name = stdout.stem.removesuffix(".stdout")
        seen[name] = dict(environment).get("ROM_TEST_RESULTS")  # type: ignore[arg-type]
        return 0

    monkey_root = tmp_path / "workspace" / "tasks" / "task" / "repo"
    monkey_root.mkdir(parents=True)
    # Avoid donor validation while retaining the exact certify graph.
    reporter = _reporter("certify", OutputMode.JSON)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "tools.rom_tests.full_color.harness_runner._donor_authority",
            lambda root: tmp_path / "authority",
        )
        summary = run_profile(
            "certify",
            monkey_root,
            tmp_path / "results with spaces",
            OutputMode.JSON,
            run_command=run,
            reporter=reporter,
        )

    expected_root = (tmp_path / "results with spaces/attempt-0001/components").resolve()
    for suite in ("core", "renderer", "journey"):
        assert seen[f"e2e-{suite}"] == str(expected_root / f"e2e-{suite}")
    assert all(
        value is None for name, value in seen.items() if not name.startswith("e2e-")
    )
    journey = next(row for row in summary["components"] if row["name"] == "e2e-journey")  # type: ignore[union-attr]
    assert Path(monkey_root / str(journey["evidence"])).resolve() == (
        expected_root / "e2e-journey"
    )
    persisted = json.loads(
        (tmp_path / "results with spaces/attempt-0001/summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["components"] == summary["components"]


def test_later_certify_attempt_cannot_relink_or_rewrite_cold_boot_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tools.rom_tests.full_color.harness_runner._donor_authority",
        lambda root: tmp_path / "authority",
    )
    results = tmp_path / "results with spaces"
    run = lambda *args: 0
    first = run_profile(
        "certify",
        ROOT,
        results,
        OutputMode.JSON,
        run_command=run,
        reporter=_reporter("certify", OutputMode.JSON),
    )
    first_path = results / "attempt-0001/summary.json"
    first_bytes = first_path.read_bytes()
    second = run_profile(
        "certify",
        ROOT,
        results,
        OutputMode.JSON,
        run_command=run,
        reporter=_reporter("certify", OutputMode.JSON),
    )

    first_cold_boot = next(
        row
        for row in first["components"]
        if row["name"] == "e2e-journey"  # type: ignore[union-attr]
    )
    second_cold_boot = next(
        row
        for row in second["components"]
        if row["name"] == "e2e-journey"  # type: ignore[union-attr]
    )
    assert first_path.read_bytes() == first_bytes
    assert "attempt-0001/components/e2e-journey" in str(first_cold_boot["evidence"])
    assert "attempt-0002/components/e2e-journey" in str(second_cold_boot["evidence"])


def test_results_file_is_a_bounded_json_setup_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = tmp_path / "not-a-directory"
    results.write_text("occupied\n", encoding="utf-8")
    assert (
        main(["--profile", "fast", "--results", str(results), "--output", "json"]) == 2
    )
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["status"] == "setup-error"
    assert document["exit_code"] == 2
    assert document["attempt"] is None
    assert document["components"] == []
    assert "setup_error" not in document
    assert len(captured.out.splitlines()) == 1
    assert captured.err == ""


def test_initial_summary_write_failure_is_bounded_and_retains_no_false_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(path: Path, value: object) -> None:
        raise OSError("summary storage unavailable")

    monkeypatch.setattr(
        "tools.rom_tests.full_color.harness_runner._write_json", fail_write
    )
    reporter = _reporter("fast", OutputMode.JSON)
    summary = run_profile(
        "fast", tmp_path, tmp_path / "results", OutputMode.JSON, reporter=reporter
    )
    rendered = reporter.stdout.getvalue()  # type: ignore[union-attr]
    assert json.loads(rendered) == summary
    assert len(rendered.splitlines()) == 1
    assert summary["status"] == "setup-error"
    assert summary["exit_code"] == 2
    assert summary["attempt"] == "attempt-0001"
    assert "summary" not in summary
    detail = tmp_path / "results/attempt-0001/diagnostics/setup.stderr.txt"
    assert detail.is_file()
    assert "summary storage unavailable" in detail.read_text(encoding="utf-8")
    assert not (tmp_path / "results/attempt-0001/summary.json").exists()
