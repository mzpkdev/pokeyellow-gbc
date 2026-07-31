"""Workflow contract for the blocking lean Gate 0 CI job."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[5]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _gate0_job(workflow: str) -> str:
    match = re.search(
        r"^  gate-0-baseline:\n(?P<body>(?: {4}[^\n]*\n| {6}[^\n]*\n| {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n|\n)*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, "CI is missing the blocking gate-0-baseline job"
    return match.group("body")


def _validate_gate0_contract(workflow: str) -> None:
    job = _gate0_job(workflow)
    assert "FULL_COLOR_RESULTS: test-results/full-color-gate0" in job, (
        "Gate 0 CI must define one common FULL_COLOR_RESULTS root"
    )
    assert "uses: ./.github/actions/setup-build" in job, (
        "Gate 0 CI must install the pinned RGBDS toolchain"
    )
    assert "run: make test-full-color-setup" in job, (
        "Gate 0 CI must install the pinned Python dependencies"
    )
    assert "continue-on-error:" not in job, "Gate 0 CI must remain blocking"

    initialize_step = re.search(
        r"      - name: Initialize Gate 0 evidence root\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert initialize_step is not None, (
        "CI must initialize Gate 0 evidence immediately after checkout"
    )
    initialize_body = initialize_step.group("body")
    assert 'mkdir -p "$FULL_COLOR_RESULTS"' in initialize_body, (
        "Gate 0 CI must initialize the common FULL_COLOR_RESULTS root"
    )
    assert '"$FULL_COLOR_RESULTS/ci-run.txt"' in initialize_body, (
        "Gate 0 CI must seed evidence metadata before fallible setup"
    )
    assert job.index("Initialize Gate 0 evidence root") < job.index("Set up Python"), (
        "Gate 0 evidence must be initialized before fallible setup"
    )

    run_step = re.search(
        r"      - name: Run lean Gate 0\n(?P<body>(?: {8}[^\n]*\n)+)", job
    )
    assert run_step is not None, "CI must retain the lean Gate 0 run step"
    run_body = run_step.group("body")
    assert "run: make test-full-color-gate0" in run_body, (
        "Gate 0 CI must invoke the stable make test-full-color-gate0 command"
    )
    upload_step = re.search(
        r"      - name: Upload Gate 0 evidence\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert upload_step is not None, "CI must retain the Gate 0 evidence upload"
    upload_body = upload_step.group("body")
    assert "if: always()" in upload_body, (
        "Gate 0 evidence must upload on success or failure"
    )
    assert re.search(
        r"^          path: \$\{\{ env\.FULL_COLOR_RESULTS \}\}/$",
        upload_body,
        re.MULTILINE,
    ), (
        "Gate 0 evidence upload must retain the whole FULL_COLOR_RESULTS root"
    )


def test_gate0_ci_contract() -> None:
    _validate_gate0_contract(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda text: text.replace(
                "run: make test-full-color-gate0", "run: python -m pytest"
            ),
            "stable make test-full-color-gate0 command",
        ),
        (
            lambda text: text.replace(
                "    timeout-minutes: 30",
                "    timeout-minutes: 30\n    continue-on-error: true",
            ),
            "must remain blocking",
        ),
        (
            lambda text: text.replace("        if: always()\n", ""),
            "upload on success or failure",
        ),
        (
            lambda text: text.replace(
                "path: ${{ env.FULL_COLOR_RESULTS }}/",
                "path: ${{ env.FULL_COLOR_RESULTS }}/summary.json",
            ),
            "retain the whole FULL_COLOR_RESULTS root",
        ),
    ],
    ids=("stable-command", "blocking", "always-upload", "whole-results-root"),
)
def test_gate0_ci_contract_rejects_targeted_mutations(mutate, failure: str) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    mutated = mutate(workflow)
    assert mutated != workflow, "mutation did not alter the workflow fixture"
    with pytest.raises(AssertionError, match=re.escape(failure)):
        _validate_gate0_contract(mutated)
