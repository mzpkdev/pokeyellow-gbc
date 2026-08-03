"""Workflow contract for provisioning the Phase 2 audit product."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[5]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
AUDIT_BUILD_COMMAND = 'make -j"$(nproc)" yellow_phase2_audit'
SETUP_BUILD_ACTION = "uses: ./.github/actions/setup-build"


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n"
        r"(?P<body>(?: {4}[^\n]*\n| {6}[^\n]*\n| {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n|\n)*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, f"CI is missing the {name} job"
    return match.group("body")


def _validate_phase2_audit_provisioning(workflow: str) -> None:
    test_job = _job(workflow, "test")
    gate0_job = _job(workflow, "gate-0-baseline-runs")
    gate0_aggregator = _job(workflow, "gate-0-baseline")
    gate0_command = (
        "run: make test-full-color-gate0-ci-run "
        "FULL_COLOR_GATE0_RUN=${{ matrix.run }}"
    )

    assert re.findall(r"^    timeout-minutes: (.+)$", test_job, re.MULTILINE) == [
        "5"
    ], "Test aggregator timeout must be exactly 5 minutes"
    assert "name: Test" in test_job
    assert re.search(r"^    if: always\(\)$", test_job, re.MULTILINE), (
        "Test aggregator must run after failed or skipped dependencies"
    )
    assert "Require every certification gate" in test_job
    assert "pytest tools/rom_tests/tests/unit" not in test_job, (
        "Test aggregator must not execute the full unit suite a third time"
    )
    assert SETUP_BUILD_ACTION not in test_job
    assert AUDIT_BUILD_COMMAND not in test_job

    assert SETUP_BUILD_ACTION in gate0_job, (
        "Gate 0 CI must install the pinned RGBDS toolchain"
    )
    assert "run: make test-full-color-setup" in gate0_job, (
        "Gate 0 CI must install the pinned test dependencies"
    )
    assert f"run: {AUDIT_BUILD_COMMAND}" in gate0_job, (
        "Gate 0 CI must build the genuine root-level Phase 2 audit product"
    )
    run_commands = re.findall(r"^        run: (.+)$", gate0_job, re.MULTILINE)
    assert run_commands.count(
        "make test-full-color-gate0-ci-run FULL_COLOR_GATE0_RUN=${{ matrix.run }}"
    ) == 1, (
        "each Gate 0 CI matrix leg must retain the exact complete-run command"
    )
    assert gate0_job.index(SETUP_BUILD_ACTION) < gate0_job.index(
        AUDIT_BUILD_COMMAND
    ), (
        "Gate 0 CI must install the pinned RGBDS toolchain before the Phase 2 audit build"
    )
    assert gate0_job.index("run: make test-full-color-setup") < gate0_job.index(
        AUDIT_BUILD_COMMAND
    ) < gate0_job.index(gate0_command), (
        "Gate 0 CI must provision the Phase 2 audit product after setup and before execution"
    )
    assert "needs: gate-0-baseline-runs" in gate0_aggregator, (
        "Gate 0 aggregator must wait for every complete matrix run"
    )
    assert "run: make test-full-color-gate0-ci-compare" in gate0_aggregator, (
        "Gate 0 aggregator must compare the independently produced evidence"
    )


def test_phase2_audit_and_units_remain_in_both_gate0_legs() -> None:
    _validate_phase2_audit_provisioning(WORKFLOW.read_text(encoding="utf-8"))


def _move_gate0_rgbds_setup_after_audit(workflow: str) -> str:
    setup = (
        "      - name: Set up pinned RGBDS\n"
        "        uses: ./.github/actions/setup-build\n\n"
    )
    dependencies = (
        "      - name: Install pinned ROM test dependencies\n"
        "        run: make test-full-color-setup\n\n"
    )
    audit = (
        "      - name: Build Phase 2 audit ROM\n"
        f"        run: {AUDIT_BUILD_COMMAND}\n"
    )
    execution = "      - name: Run one complete lean Gate 0 execution\n"
    return workflow.replace(
        setup + dependencies + audit + "\n" + execution,
        dependencies + audit + "\n" + setup + execution,
        1,
    )


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda text: text.replace(
                "    if: always()\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 5\n\n"
                "    steps:\n"
                "      - name: Require every certification gate",
                "    if: always()\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 10\n\n"
                "    steps:\n"
                "      - name: Require every certification gate",
                1,
            ),
            "Test aggregator timeout must be exactly 5 minutes",
        ),
        (
            lambda text: text.replace(
                "    if: always()\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 5\n\n"
                "    steps:\n"
                "      - name: Require every certification gate",
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 5\n\n"
                "    steps:\n"
                "      - name: Require every certification gate",
                1,
            ),
            "Test aggregator must run after failed or skipped dependencies",
        ),
        (
            lambda text: text.replace(
                "      - name: Require every certification gate",
                "      - name: Run unit tests\n"
                "        run: python -m pytest tools/rom_tests/tests/unit\n\n"
                "      - name: Require every certification gate",
                1,
            ),
            "must not execute the full unit suite a third time",
        ),
        (
            lambda text: text.replace(
                "      - name: Build Phase 2 audit ROM\n"
                f"        run: {AUDIT_BUILD_COMMAND}\n\n"
                "      - name: Run one complete lean Gate 0 execution\n",
                "      - name: Run one complete lean Gate 0 execution\n",
            ),
            "Gate 0 CI must build the genuine root-level Phase 2 audit product",
        ),
        (
            _move_gate0_rgbds_setup_after_audit,
            "Gate 0 CI must install the pinned RGBDS toolchain before the Phase 2 audit build",
        ),
        (
            lambda text: text.replace(
                "run: make test-full-color-gate0-ci-run", "run: python -m pytest"
            ),
            "exact complete-run command",
        ),
    ],
    ids=(
        "aggregator-timeout",
        "aggregator-always",
        "third-unit-run",
        "gate0-audit-build",
        "gate0-rgbds-after-audit",
        "gate0-command",
    ),
)
def test_phase2_audit_ci_contract_rejects_targeted_mutations(
    mutate, failure: str
) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    mutated = mutate(workflow)
    assert mutated != workflow, "mutation did not alter the workflow fixture"
    with pytest.raises(AssertionError, match=re.escape(failure)):
        _validate_phase2_audit_provisioning(mutated)
