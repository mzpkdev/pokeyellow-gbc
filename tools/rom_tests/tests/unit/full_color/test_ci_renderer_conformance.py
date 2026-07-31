"""Workflow contract for the blocking renderer-conformance checker CI job."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[5]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _renderer_checker_job(workflow: str) -> str:
    match = re.search(
        r"^  renderer-conformance-checker:\n"
        r"(?P<body>(?: {4}[^\n]*\n| {6}[^\n]*\n| {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n|\n)*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, (
        "CI is missing the blocking renderer-conformance-checker job"
    )
    return match.group("body")


def validate_renderer_checker_job(workflow: str) -> None:
    job = _renderer_checker_job(workflow)
    assert (
        "FULL_COLOR_CONFORMANCE_RESULTS: test-results/full-color-renderer-conformance"
        in job
    ), "renderer checker CI must define its dedicated evidence root"
    assert "continue-on-error:" not in job, "renderer checker CI must remain blocking"

    initialize_step = re.search(
        r"      - name: Initialize renderer checker evidence root\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert initialize_step is not None, (
        "CI must initialize renderer evidence immediately after checkout"
    )
    initialize_body = initialize_step.group("body")
    assert 'mkdir -p "$FULL_COLOR_CONFORMANCE_RESULTS"' in initialize_body
    assert '"$FULL_COLOR_CONFORMANCE_RESULTS/ci-run.txt"' in initialize_body
    assert job.index("Initialize renderer checker evidence root") < job.index(
        "Set up Python"
    ), "renderer evidence must be initialized before fallible setup"

    run_step = re.search(
        r"      - name: Run renderer conformance checker\n"
        r"(?P<body>(?: {8}[^\n]*\n)+)",
        job,
    )
    assert run_step is not None
    assert "run: make test-full-color-renderer-conformance" in run_step.group("body"), (
        "renderer checker CI must invoke the stable Make command"
    )

    upload_step = re.search(
        r"      - name: Upload renderer checker evidence\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert upload_step is not None
    upload_body = upload_step.group("body")
    assert "if: always()" in upload_body, (
        "renderer evidence must upload on success or failure"
    )
    assert re.search(
        r"^          path: \$\{\{ env\.FULL_COLOR_CONFORMANCE_RESULTS \}\}/$",
        upload_body,
        re.MULTILINE,
    ), "renderer evidence upload must retain the whole evidence root"


def test_renderer_checker_ci_contract() -> None:
    validate_renderer_checker_job(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda job: job.replace(
                "run: make test-full-color-renderer-conformance", "run: true"
            ),
            "stable Make command",
        ),
        (
            lambda job: job.replace(
                "    timeout-minutes: 15",
                "    timeout-minutes: 15\n    continue-on-error: true",
            ),
            "must remain blocking",
        ),
        (
            lambda job: job.replace("        if: always()\n", ""),
            "upload on success or failure",
        ),
        (
            lambda job: job.replace(
                "path: ${{ env.FULL_COLOR_CONFORMANCE_RESULTS }}/",
                "path: ${{ env.FULL_COLOR_CONFORMANCE_RESULTS }}/summary.json",
            ),
            "whole evidence root",
        ),
    ],
    ids=("stable-command", "blocking", "always-upload", "whole-results-root"),
)
def test_checker_ci_rejects_targeted_mutations(mutate, failure: str) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = _renderer_checker_job(workflow)
    mutated_job = mutate(job)
    assert mutated_job != job, "mutation did not alter the renderer checker job"
    mutated = workflow.replace(job, mutated_job, 1)
    with pytest.raises(AssertionError, match=re.escape(failure)):
        validate_renderer_checker_job(mutated)
