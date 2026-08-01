"""Workflow contract for the blocking Phase 1 runtime ownership job."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[5]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _phase1_runtime_job(workflow: str) -> str:
    match = re.search(
        r"^  phase1-runtime-ownership:\n"
        r"(?P<body>(?: {4}[^\n]*\n| {6}[^\n]*\n| {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n|\n)*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, "CI is missing the blocking phase1-runtime-ownership job"
    return match.group("body")


def validate_phase1_runtime_job(workflow: str) -> None:
    job = _phase1_runtime_job(workflow)
    assert "name: Phase 1 Runtime Ownership" in job
    assert re.search(r"^    needs: build$", job, re.MULTILINE), (
        "Phase 1 runtime CI requires the debug ROM build dependency"
    )
    assert re.search(r"^    timeout-minutes: 15$", job, re.MULTILINE), (
        "Phase 1 runtime CI must retain its bounded timeout"
    )
    assert "continue-on-error:" not in job, "Phase 1 runtime CI must remain blocking"
    assert (
        "FULL_COLOR_RUNTIME_RESULTS: test-results/full-color-renderer-runtime" in job
    ), "Phase 1 runtime CI must define its dedicated evidence root"

    initialize = re.search(
        r"      - name: Initialize Phase 1 runtime evidence root\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert initialize is not None, (
        "Phase 1 runtime evidence must be initialized immediately after checkout"
    )
    initialize_body = initialize.group("body")
    assert 'mkdir -p "$FULL_COLOR_RUNTIME_RESULTS"' in initialize_body, (
        "Phase 1 runtime CI must initialize the dedicated evidence root"
    )
    assert '"$FULL_COLOR_RUNTIME_RESULTS/ci-run.txt"' in initialize_body, (
        "Phase 1 runtime CI must seed evidence metadata before setup"
    )
    assert job.index("Initialize Phase 1 runtime evidence root") < job.index(
        "Set up Python"
    ), "Phase 1 runtime evidence must initialize before fallible setup"

    assert "uses: ./.github/actions/setup-build" in job, (
        "Phase 1 runtime CI must install pinned RGBDS for its build dependency"
    )
    assert "run: make test-full-color-setup" in job, (
        "Phase 1 runtime CI must install pinned Python dependencies"
    )

    download = re.search(
        r"      - name: Download debug ROM evidence\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert download is not None, "Phase 1 runtime CI must download debug ROM evidence"
    download_body = download.group("body")
    assert "uses: actions/download-artifact@v7" in download_body
    assert re.search(r"^          name: pokeyellow-build$", download_body, re.MULTILINE), (
        "Phase 1 runtime CI must download the exact build artifact"
    )
    assert re.search(r"^          path: release$", download_body, re.MULTILINE)

    prepare = re.search(
        r"      - name: Prepare debug ROM evidence\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert prepare is not None
    actual_copies = {
        line.strip()
        for line in prepare.group("body").splitlines()
        if line.strip().startswith("cp ")
    }
    assert actual_copies == {
        "cp release/pokeyellow-debug.gbc pokeyellow_debug.gbc",
        "cp release/pokeyellow-debug.map pokeyellow_debug.map",
        "cp release/pokeyellow-debug.sym pokeyellow_debug.sym",
    }, "Phase 1 runtime CI must prepare exactly the debug ROM/map/sym"

    assert "run: make test-full-color-renderer-runtime" in job, (
        "Phase 1 runtime CI must invoke the stable Make command"
    )
    upload = re.search(
        r"      - name: Upload Phase 1 runtime evidence\n"
        r"(?P<body>(?: {8}[^\n]*\n| {10}[^\n]*\n| {12}[^\n]*\n)+)",
        job,
    )
    assert upload is not None
    upload_body = upload.group("body")
    assert "if: always()" in upload_body, (
        "Phase 1 runtime evidence must upload on success or failure"
    )
    assert re.search(
        r"^          path: \$\{\{ env\.FULL_COLOR_RUNTIME_RESULTS \}\}/$",
        upload_body,
        re.MULTILINE,
    ), "Phase 1 runtime upload must retain the whole evidence root"
    assert "if-no-files-found: error" in upload_body


def test_phase1_runtime_ci_contract() -> None:
    validate_phase1_runtime_job(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (lambda job: job.replace("    needs: build", "    needs: []"), "build dependency"),
        (
            lambda job: job.replace("    timeout-minutes: 15", "    timeout-minutes: 30"),
            "bounded timeout",
        ),
        (
            lambda job: job.replace(
                "    timeout-minutes: 15",
                "    timeout-minutes: 15\n    continue-on-error: true",
            ),
            "must remain blocking",
        ),
        (
            lambda job: job.replace(
                "run: make test-full-color-renderer-runtime", "run: true"
            ),
            "stable Make command",
        ),
        (
            lambda job: job.replace(
                'mkdir -p "$FULL_COLOR_RUNTIME_RESULTS"',
                'mkdir -p test-results/elsewhere',
            ),
            "initialize the dedicated evidence root",
        ),
        (
            lambda job: job.replace("          name: pokeyellow-build", "          name: roms"),
            "exact build artifact",
        ),
        (
            lambda job: job.replace(
                "cp release/pokeyellow-debug.sym pokeyellow_debug.sym\n", ""
            ),
            "exactly the debug ROM/map/sym",
        ),
        (
            lambda job: job.replace("        if: always()\n", ""),
            "upload on success or failure",
        ),
        (
            lambda job: job.replace(
                "path: ${{ env.FULL_COLOR_RUNTIME_RESULTS }}/",
                "path: ${{ env.FULL_COLOR_RUNTIME_RESULTS }}/summary.json",
            ),
            "whole evidence root",
        ),
    ],
    ids=(
        "build-dependency",
        "timeout",
        "blocking",
        "stable-command",
        "early-initialization",
        "artifact-name",
        "exact-debug-files",
        "always-upload",
        "whole-root",
    ),
)
def test_phase1_runtime_ci_rejects_targeted_mutations(mutate, failure: str) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = _phase1_runtime_job(workflow)
    mutated_job = mutate(job)
    assert mutated_job != job, "mutation did not alter the Phase 1 runtime job"
    with pytest.raises(AssertionError, match=re.escape(failure)):
        validate_phase1_runtime_job(workflow.replace(job, mutated_job, 1))
