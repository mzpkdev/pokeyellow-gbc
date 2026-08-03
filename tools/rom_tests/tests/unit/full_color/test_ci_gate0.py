"""Workflow contract for parallel Gate 0 execution and blocking comparison."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[5]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n"
        r"(?P<body>(?: {4}[^\n]*\n| {6}[^\n]*\n| {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n|\n)*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, f"CI is missing the {name} job"
    return match.group("body")


def _validate_gate0_contract(workflow: str) -> None:
    runs = _job(workflow, "gate-0-baseline-runs")
    comparison = _job(workflow, "gate-0-baseline")

    assert "fail-fast: false" in runs, "Gate 0 matrix must run both legs"
    assert "run: [1, 2]" in runs, "Gate 0 matrix must contain exactly two runs"
    assert "needs: build" in runs, "Gate 0 runs must wait for the build"
    assert "FULL_COLOR_RESULTS: test-results/full-color-gate0" in runs
    assert "uses: ./.github/actions/setup-build" in runs
    assert "run: make test-full-color-setup" in runs
    assert 'run: make -j"$(nproc)" yellow_phase2_audit' in runs
    assert (
        "run: make test-full-color-gate0-ci-run "
        "FULL_COLOR_GATE0_RUN=${{ matrix.run }}"
    ) in runs, "each matrix leg must execute one complete Gate 0 run"
    assert "continue-on-error:" not in runs, "Gate 0 runs must remain blocking"
    assert runs.count("if: always()") == 1, (
        "each Gate 0 run must always upload evidence"
    )
    assert "path: ${{ env.FULL_COLOR_RESULTS }}/run-${{ matrix.run }}/" in runs

    assert "name: Gate 0 Baseline" in comparison
    assert "needs: gate-0-baseline-runs" in comparison
    assert re.search(r"^    if: always\(\)$", comparison, re.MULTILINE), (
        "the blocking comparison must run even when a matrix leg fails"
    )
    assert "continue-on-error:" not in comparison, (
        "the Gate 0 comparison must remain blocking"
    )
    assert comparison.count("uses: actions/download-artifact@v7") == 2
    assert "path: ${{ env.FULL_COLOR_RESULTS }}/run-1" in comparison
    assert "path: ${{ env.FULL_COLOR_RESULTS }}/run-2" in comparison
    assert "run: make test-full-color-gate0-ci-compare" in comparison
    assert comparison.count("if: always()") == 2, (
        "the aggregator must always run and always upload compared evidence"
    )
    assert "uses: actions/upload-artifact@v7" in comparison
    assert "path: ${{ env.FULL_COLOR_RESULTS }}/" in comparison


def test_gate0_ci_contract() -> None:
    _validate_gate0_contract(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda text: text.replace("fail-fast: false", "fail-fast: true"),
            "matrix must run both legs",
        ),
        (
            lambda text: text.replace("run: [1, 2]", "run: [1]"),
            "exactly two runs",
        ),
        (
            lambda text: text.replace(
                "make test-full-color-gate0-ci-run", "python -m pytest"
            ),
            "one complete Gate 0 run",
        ),
        (
            lambda text: text.replace(
                "    needs: gate-0-baseline-runs\n"
                "    if: always()\n"
                "    runs-on: ubuntu-latest\n",
                "    needs: gate-0-baseline-runs\n"
                "    runs-on: ubuntu-latest\n",
                1,
            ),
            "comparison must run even when a matrix leg fails",
        ),
        (
            lambda text: text.replace(
                "run: make test-full-color-gate0-ci-compare",
                "run: true",
            ),
            "test-full-color-gate0-ci-compare",
        ),
    ],
    ids=("fail-fast", "two-runs", "complete-run", "always-compare", "compare"),
)
def test_gate0_ci_contract_rejects_targeted_mutations(mutate, failure: str) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    mutated = mutate(workflow)
    assert mutated != workflow, "mutation did not alter the workflow fixture"
    with pytest.raises(AssertionError, match=re.escape(failure)):
        _validate_gate0_contract(mutated)
