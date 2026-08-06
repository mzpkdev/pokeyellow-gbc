"""Semantic contracts for hosted verification workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest
import yaml

from tools.rom_tests.full_color.evidence_runner import COMPONENTS


ROOT = Path(__file__).parents[5]
WORKFLOWS = {
    "caller": ROOT / ".github/workflows/ci.yml",
    "build": ROOT / ".github/workflows/ci-build.yml",
    "full_color": ROOT / ".github/workflows/ci-full-color.yml",
    "gameplay": ROOT / ".github/workflows/ci-gameplay.yml",
    "metadata": ROOT / ".github/workflows/metadata.yml",
    "labels": ROOT / ".github/workflows/pr-labels.yml",
    "release": ROOT / ".github/workflows/release.yml",
}
TEST_PRODUCTS = {
    "pokeyellow.gbc",
    "pokeyellow.map",
    "pokeyellow.sym",
    "pokeyellow_debug.gbc",
    "pokeyellow_debug.map",
    "pokeyellow_debug.sym",
    "pokeyellow_vc.gbc",
    "pokeyellow_vc.map",
    "pokeyellow_vc.sym",
    "pokeyellow_phase2_audit.gbc",
    "pokeyellow_phase2_audit.map",
    "pokeyellow_phase2_audit.sym",
}
RELEASE_COPIES = {
    "cp pokeyellow.gbc release/pokeyellow.gbc",
    "cp pokeyellow.map release/pokeyellow.map",
    "cp pokeyellow.sym release/pokeyellow.sym",
    "cp pokeyellow_debug.gbc release/pokeyellow-debug.gbc",
    "cp pokeyellow_debug.map release/pokeyellow-debug.map",
    "cp pokeyellow_debug.sym release/pokeyellow-debug.sym",
    "cp pokeyellow_vc.gbc release/pokeyellow-vc.gbc",
    "cp pokeyellow_vc.map release/pokeyellow-vc.map",
    "cp pokeyellow_vc.sym release/pokeyellow-vc.sym",
}
FULL_COLOR_JOB_NAMES = {
    "donor-contract": "Donor Contract",
    "unit-tests": "Unit Tests",
    "harness-contracts": "Harness Contracts",
    "evidence-capture": "Full-color Evidence Capture ${{ matrix.run }}",
    "evidence-determinism": "Full-color Evidence Determinism",
    "renderer-contracts": "Renderer Contract Fixtures",
    "renderer-runtime": "Renderer Runtime Ownership",
    "audit-evidence": "Full-color Audit Evidence",
}
GAMEPLAY_MATRIX = [
    {
        "name": "Core",
        "suite": "core",
        "target": "test-full-color-e2e-core",
    },
    {
        "name": "Renderer",
        "suite": "renderer",
        "target": "test-full-color-e2e-renderer",
    },
    {
        "name": "Journey",
        "suite": "journey",
        "target": "test-full-color-e2e-journey",
    },
]


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict), f"{path} must contain a YAML mapping"
    return loaded


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matching = [step for step in job["steps"] if step.get("name") == name]
    assert len(matching) == 1, f"expected one {name!r} step"
    return matching[0]


def _artifact_steps(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [step for step in job["steps"] if step.get("uses") == action]


def _script_lines(script: str) -> set[str]:
    return {line.strip() for line in script.splitlines() if line.strip()}


def _all_workflow_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]


def _reopen_script() -> str:
    metadata = _load(WORKFLOWS["metadata"])
    return _step(metadata["jobs"]["title"], "Require prior certification when reopening")[
        "run"
    ]


def _run_certification_script(
    *,
    build: str = "success",
    full_color: str = "success",
    gameplay: str = "success",
) -> subprocess.CompletedProcess[str]:
    caller = _load(WORKFLOWS["caller"])
    script = _step(
        caller["jobs"]["certification"], "Require every verification group"
    )["run"]
    env = os.environ.copy()
    env.update(
        {
            "BUILD": build,
            "FULL_COLOR": full_color,
            "GAMEPLAY": gameplay,
        }
    )
    return subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _run_reopen_script(
    tmp_path: Path,
    *,
    pages: list[dict[str, Any]] | None = None,
    raw_output: str | None = None,
    gh_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    assert shutil.which("jq"), "semantic reopen test requires jq"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -u
expected_url='repos/acme/project/commits/abc123/check-runs?filter=all&per_page=100'
if [ "$#" -ne 4 ] || [ "$1" != api ] || [ "$2" != --paginate ] || \
   [ "$3" != --slurp ] || [ "$4" != "$expected_url" ]; then
  echo 'unexpected gh argv' >&2
  exit 64
fi
if [ "${FAKE_GH_FAILURE:-0}" = 1 ]; then
  echo 'simulated API failure' >&2
  exit 1
fi
printf '%s\n' "${FAKE_GH_OUTPUT:?}"
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "REPOSITORY": "acme/project",
            "HEAD_SHA": "abc123",
            "FAKE_GH_FAILURE": "1" if gh_failure else "0",
            "FAKE_GH_OUTPUT": (
                raw_output if raw_output is not None else json.dumps(pages)
            ),
        }
    )
    return subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", _reopen_script()],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_ci_caller_is_the_only_release_gate() -> None:
    caller = _load(WORKFLOWS["caller"])
    release = _load(WORKFLOWS["release"])

    assert caller["name"] == "CI"
    assert caller["on"] == {
        "pull_request": {
            "branches": ["main"],
            "types": ["opened", "synchronize"],
        },
        "push": {"branches": ["main"]},
    }
    assert caller["permissions"] == {"contents": "read"}
    assert set(caller["jobs"]) == {
        "build",
        "full-color",
        "gameplay",
        "certification",
    }
    assert caller["jobs"]["build"] == {
        "name": "Build ROMs",
        "uses": "./.github/workflows/ci-build.yml",
    }
    assert caller["jobs"]["full-color"] == {
        "name": "Full-color Verification",
        "needs": "build",
        "uses": "./.github/workflows/ci-full-color.yml",
    }
    assert caller["jobs"]["gameplay"] == {
        "name": "Gameplay Verification",
        "needs": "build",
        "uses": "./.github/workflows/ci-gameplay.yml",
    }

    certification = caller["jobs"]["certification"]
    assert certification["name"] == "Certification"
    assert set(certification["needs"]) == {"build", "full-color", "gameplay"}
    assert certification["if"] == "always()"
    certification_step = _step(certification, "Require every verification group")
    assert certification_step["env"] == {
        "BUILD": "${{ needs.build.result }}",
        "FULL_COLOR": "${{ needs.full-color.result }}",
        "GAMEPLAY": "${{ needs.gameplay.result }}",
    }
    syntax = subprocess.run(
        ["bash", "-n"],
        input=certification_step["run"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    assert release["on"] == {
        "workflow_run": {"workflows": ["CI"], "types": ["completed"]}
    }
    release_job = release["jobs"]["release"]
    assert release_job["if"] == (
        "github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.event == 'push'"
    )
    download = _step(release_job, "Download build artifacts")
    assert download["with"]["name"] == "pokeyellow-build"


def test_certification_accepts_only_all_successful_groups() -> None:
    result = _run_certification_script()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("dependency", ("build", "full_color", "gameplay"))
@pytest.mark.parametrize("result", ("failure", "cancelled", "skipped"))
def test_certification_rejects_any_unsuccessful_group(
    dependency: str, result: str
) -> None:
    dependency_results = {
        "build": "success",
        "full_color": "success",
        "gameplay": "success",
    }
    dependency_results[dependency] = result
    completed = _run_certification_script(**dependency_results)
    assert completed.returncode != 0
    assert completed.stdout == f"::error::verification group finished as {result}\n"
    assert completed.stderr == ""


def test_build_workflow_produces_all_products_once() -> None:
    build = _load(WORKFLOWS["build"])
    assert build["name"] == "CI Build"
    assert build["on"] == {"workflow_call": ""}
    assert build["permissions"] == {"contents": "read"}
    assert set(build["jobs"]) == {"build"}

    job = build["jobs"]["build"]
    assert job["name"] == "Build ROMs"
    build_step = _step(job, "Build ROM products")
    assert build_step["run"] == (
        'make -j"$(nproc)" yellow yellow_debug yellow_vc yellow_phase2_audit'
    )
    assert len(
        [step for step in job["steps"] if step.get("uses") == "./.github/actions/setup-build"]
    ) == 1

    clean_step = _step(job, "Check for modified tracked files")
    assert "git diff-index --quiet HEAD --" in clean_step["run"]

    release_upload = _step(job, "Upload release products")
    assert release_upload["with"] == {
        "name": "pokeyellow-build",
        "path": "release/",
        "if-no-files-found": "error",
        "retention-days": "3",
    }
    stage = _step(job, "Stage release files")
    assert {
        line for line in _script_lines(stage["run"]) if line.startswith("cp ")
    } == RELEASE_COPIES

    test_upload = _step(job, "Upload test products")
    assert test_upload["with"]["name"] == "pokeyellow-test-products"
    test_product_paths = test_upload["with"]["path"].splitlines()
    assert len(test_product_paths) == 12
    assert set(test_product_paths) == TEST_PRODUCTS
    assert test_upload["with"]["if-no-files-found"] == "error"


def test_full_color_workflow_splits_one_run_contracts_from_evidence() -> None:
    workflow = _load(WORKFLOWS["full_color"])
    assert workflow["name"] == "CI Full-color"
    assert workflow["on"] == {"workflow_call": ""}
    assert workflow["permissions"] == {"contents": "read"}
    assert {
        job_id: job["name"] for job_id, job in workflow["jobs"].items()
    } == FULL_COLOR_JOB_NAMES
    assert "continue-on-error" not in WORKFLOWS["full_color"].read_text(
        encoding="utf-8"
    )

    jobs = workflow["jobs"]
    donor = jobs["donor-contract"]
    donor_checkout = _step(donor, "Checkout pinned pokered-gbc donor")
    assert donor_checkout["with"]["repository"] == "dannye/pokered-gbc"
    assert donor_checkout["with"]["ref"] == (
        "c1a3b6c5a7591472241036d0cf09c3817f841f93"
    )
    assert _step(donor, "Run exact donor contract")["run"] == (
        "make test-full-color-donor-contract"
    )

    unit = jobs["unit-tests"]
    assert _step(unit, "Run complete unit contracts once")["run"] == (
        "make test-unit ROM_TEST_PREBUILT_PRODUCTS=1"
    )
    harness = jobs["harness-contracts"]
    assert "make test-full-color-harness-contracts ROM_TEST_PREBUILT_PRODUCTS=1" in (
        _step(harness, "Run repository and bank contracts")["run"]
    )
    assert _step(harness, "Upload harness contract evidence")["if"] == "always()"

    capture = jobs["evidence-capture"]
    assert capture["strategy"] == {
        "fail-fast": "false",
        "matrix": {"run": ["1", "2"]},
    }
    assert COMPONENTS == ("observability", "traceability", "visual-pipeline")
    capture_command = _step(capture, "Capture deterministic evidence")["run"]
    assert "tools.rom_tests.full_color.evidence_runner" in capture_command
    assert "--one-run run-${{ matrix.run }}" in capture_command
    capture_upload = _step(capture, "Upload evidence capture")
    assert capture_upload["if"] == "always()"
    assert capture_upload["with"]["name"] == (
        "full-color-evidence-run-${{ matrix.run }}-${{ github.run_id }}-${{ github.run_attempt }}"
    )

    comparison = jobs["evidence-determinism"]
    assert comparison["needs"] == "evidence-capture"
    assert comparison["if"] == "always()"
    downloads = _artifact_steps(comparison, "actions/download-artifact@v7")
    assert {(step["with"]["name"], step["with"]["path"]) for step in downloads} == {
        (
            "full-color-evidence-run-1-${{ github.run_id }}-${{ github.run_attempt }}",
            "${{ env.FULL_COLOR_EVIDENCE_RESULTS }}/run-1",
        ),
        (
            "full-color-evidence-run-2-${{ github.run_id }}-${{ github.run_attempt }}",
            "${{ env.FULL_COLOR_EVIDENCE_RESULTS }}/run-2",
        ),
    }
    compare_command = _step(comparison, "Compare independent evidence")["run"]
    assert "--compare-runs run-1 run-2" in compare_command
    assert _step(comparison, "Upload compared evidence")["if"] == "always()"

    verification_workflows = [
        _load(WORKFLOWS[name]) for name in ("build", "full_color", "gameplay")
    ]
    one_run_commands = [
        step.get("run", "")
        for verification_workflow in verification_workflows
        for step in _all_workflow_steps(verification_workflow)
        if "make test-unit" in step.get("run", "")
    ]
    assert one_run_commands == ["make test-unit ROM_TEST_PREBUILT_PRODUCTS=1"]


def test_full_color_product_consumers_use_same_revision_artifact() -> None:
    jobs = _load(WORKFLOWS["full_color"])["jobs"]
    consumer_ids = {
        "unit-tests",
        "harness-contracts",
        "evidence-capture",
        "renderer-runtime",
        "audit-evidence",
    }
    for job_id in consumer_ids:
        downloads = _artifact_steps(jobs[job_id], "actions/download-artifact@v7")
        assert len(downloads) == 1, job_id
        assert downloads[0]["with"] == {
            "name": "pokeyellow-test-products",
            "path": ".",
        }

    assert _step(jobs["renderer-contracts"], "Run renderer contract fixtures")[
        "run"
    ] == "make test-full-color-renderer-contracts"
    assert _step(jobs["renderer-runtime"], "Run renderer runtime ownership")[
        "run"
    ] == "make test-full-color-renderer-runtime ROM_TEST_PREBUILT_PRODUCTS=1"
    assert "make test-full-color-audit ROM_TEST_PREBUILT_PRODUCTS=1" in _step(
        jobs["audit-evidence"], "Verify audit evidence"
    )["run"]

    for job_id in (
        "renderer-contracts",
        "renderer-runtime",
        "audit-evidence",
    ):
        upload = [
            step
            for step in jobs[job_id]["steps"]
            if step.get("uses") == "actions/upload-artifact@v7"
        ]
        assert len(upload) == 1, job_id
        assert upload[0]["if"] == "always()"
        assert upload[0]["with"]["if-no-files-found"] == "error"


def test_gameplay_workflow_runs_three_independent_suites() -> None:
    workflow = _load(WORKFLOWS["gameplay"])
    assert workflow["name"] == "CI Gameplay"
    assert workflow["on"] == {"workflow_call": ""}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"e2e"}

    e2e = workflow["jobs"]["e2e"]
    assert e2e["name"] == "E2E (${{ matrix.name }})"
    assert e2e["strategy"] == {
        "fail-fast": "false",
        "matrix": {"include": GAMEPLAY_MATRIX},
    }
    download = _step(e2e, "Download same-revision test products")
    assert download["with"] == {"name": "pokeyellow-test-products", "path": "."}
    assert _step(e2e, "Run gameplay suite")["run"] == (
        "make ROM_TEST_PREBUILT_PRODUCTS=1 ${{ matrix.target }}"
    )
    failure_upload = _step(e2e, "Upload failure evidence")
    assert failure_upload["if"] == "failure()"
    assert failure_upload["with"] == {
        "name": "e2e-${{ matrix.suite }}-failure-evidence",
        "path": "test-results/",
        "if-no-files-found": "warn",
        "retention-days": "14",
    }


def test_metadata_and_trusted_label_workflows_keep_distinct_boundaries() -> None:
    metadata = _load(WORKFLOWS["metadata"])
    labels = _load(WORKFLOWS["labels"])

    assert metadata["name"] == "Metadata"
    assert metadata["on"] == {
        "pull_request": {
            "branches": ["main"],
            "types": [
                "opened",
                "edited",
                "reopened",
                "synchronize",
                "ready_for_review",
                "converted_to_draft",
            ],
        },
        "push": {"branches": ["main"]},
    }
    assert metadata["permissions"] == {"contents": "read", "checks": "read"}
    assert metadata["concurrency"] == {
        "group": (
            "${{ github.workflow }}-${{ github.event_name == 'pull_request' && "
            "github.event.pull_request.number || github.ref }}-${{ github.event_name "
            "== 'pull_request' && github.event.action || 'code' }}"
        ),
        "cancel-in-progress": "true",
    }
    assert set(metadata["jobs"]) == {"lint", "title"}
    lint = metadata["jobs"]["lint"]
    assert lint["name"] == "Workflow Lint"
    assert lint["if"] == (
        "github.event_name == 'push' || github.event.action != 'edited'"
    )
    assert _step(lint, "Run actionlint")["uses"] == "docker://rhysd/actionlint:1.7.12"

    title = metadata["jobs"]["title"]
    assert title["name"] == (
        "${{ github.event.action == 'reopened' && "
        "'PR Reopen Certification' || 'PR Title' }}"
    )
    assert title["if"] == "github.event_name == 'pull_request'"
    reopen = _step(title, "Require prior certification when reopening")
    assert reopen["if"] == "github.event.action == 'reopened'"
    assert 'select(.name == "Certification" and .conclusion == "success")' in reopen[
        "run"
    ]

    assert labels["on"] == {
        "pull_request_target": {
            "types": ["opened", "edited", "synchronize", "reopened"]
        }
    }
    assert labels["permissions"] == {
        "issues": "write",
        "pull-requests": "write",
    }
    assert "actions/checkout" not in WORKFLOWS["labels"].read_text(encoding="utf-8")
    assert "pull_request_target" not in WORKFLOWS["metadata"].read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "pages",
    [
        [{"check_runs": [{"name": "Certification", "conclusion": "success"}]}],
        [
            {"check_runs": [{"name": "Certification", "conclusion": "failure"}]},
            {"check_runs": [{"name": "Certification", "conclusion": "success"}]},
        ],
    ],
    ids=("one-success", "success-on-later-page"),
)
def test_reopen_accepts_prior_successful_certification(
    tmp_path: Path, pages: list[dict[str, Any]]
) -> None:
    result = _run_reopen_script(tmp_path, pages=pages)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "pages",
    [
        [{"check_runs": []}],
        [{"check_runs": [{"name": "Certification", "conclusion": None}]}],
        [{"check_runs": [{"name": "Test", "conclusion": "success"}]}],
    ],
    ids=("zero-check-runs", "in-progress", "old-check-name"),
)
def test_reopen_rejects_heads_without_successful_certification(
    tmp_path: Path, pages: list[dict[str, Any]]
) -> None:
    result = _run_reopen_script(tmp_path, pages=pages)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::reopened head SHA has no successful Certification check run\n"
    )
    assert result.stderr == ""


def test_reopen_fails_closed_when_api_fails(tmp_path: Path) -> None:
    result = _run_reopen_script(tmp_path, gh_failure=True)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::could not enumerate Certification check runs for reopened head SHA\n"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    "raw_output",
    ("not json", '[{"check_runs":', "[{}]"),
    ids=("not-json", "truncated-json", "missing-check-runs"),
)
def test_reopen_fails_closed_when_paginated_json_is_malformed(
    tmp_path: Path, raw_output: str
) -> None:
    result = _run_reopen_script(tmp_path, raw_output=raw_output)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::could not parse Certification check runs for reopened head SHA\n"
    )
    assert result.stderr == ""


def test_verification_workflows_have_no_manual_bypass_or_soft_failures() -> None:
    for name in ("caller", "build", "full_color", "gameplay"):
        workflow = _load(WORKFLOWS[name])
        assert "workflow_dispatch" not in workflow["on"], name
        assert "continue-on-error" not in WORKFLOWS[name].read_text(
            encoding="utf-8"
        ), name
