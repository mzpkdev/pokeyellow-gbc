"""Structural, mutation-sensitive contracts for CI workflow orchestration."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

from tools.rom_tests.full_color.gate0_runner import COMPONENTS


ROOT = Path(__file__).parents[5]
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
METADATA_WORKFLOW = ROOT / ".github/workflows/pr-metadata.yml"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
REQUIRED_CERTIFICATION_JOBS = [
    "donor-provenance",
    "lint",
    "build",
    "gate-0-baseline",
    "renderer-conformance-checker",
    "phase1-runtime-ownership",
]
EXPECTED_TEST_ENV = {
    "DONOR": "${{ needs.donor-provenance.result }}",
    "LINT": "${{ needs.lint.result }}",
    "BUILD": "${{ needs.build.result }}",
    "GATE0": "${{ needs.gate-0-baseline.result }}",
    "CONFORMANCE": "${{ needs.renderer-conformance-checker.result }}",
    "RUNTIME": "${{ needs.phase1-runtime-ownership.result }}",
}
EXPECTED_TEST_SCRIPT = """\
for result in "$DONOR" "$LINT" "$BUILD" "$GATE0" "$CONFORMANCE" "$RUNTIME"; do
  if [ "$result" != success ]; then
    echo "::error::certification dependency finished as $result"
    exit 1
  fi
done
"""
EXPECTED_TITLE_SCRIPT = """\
pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\\([a-z0-9._/-]+\\))?(!)?: .+'
if [[ ! "$PR_TITLE" =~ $pattern ]]; then
  echo "::error::PR title must follow Conventional Commits"
  exit 1
fi
"""
EXPECTED_REOPEN_SCRIPT = """\
if ! check_run_pages="$(gh api --paginate --slurp \\
  "repos/$REPOSITORY/commits/$HEAD_SHA/check-runs?filter=all&per_page=100" \\
  2>/dev/null)"; then
  echo "::error::could not enumerate Test check runs for reopened head SHA"
  exit 1
fi

if ! successful_test_count="$(jq -er \\
  '[.[] | .check_runs[] | select(.name == "Test" and .conclusion == "success")] | length' \\
  <<<"$check_run_pages" 2>/dev/null)"; then
  echo "::error::could not parse Test check runs for reopened head SHA"
  exit 1
fi

if [ "$successful_test_count" -lt 1 ]; then
  echo "::error::reopened head SHA has no successful Test check run"
  exit 1
fi
"""
EXPECTED_GATE0_COMPONENTS = (
    "unit-tests",
    "baseline-discovery",
    "inventory-progress",
    "bank-torture",
    "observability",
    "traceability",
    "visual-pipeline",
)
EXPECTED_METADATA_JOB_NAME = (
    "${{ github.event.action == 'reopened' && "
    "'PR Reopen Certification' || 'PR Title' }}"
)
EXPECTED_METADATA_CONCURRENCY = (
    "${{ github.workflow }}-${{ github.event.pull_request.number }}-"
    "${{ github.event.action }}"
)
METADATA_ACTIONS = (
    "opened",
    "edited",
    "reopened",
    "synchronize",
    "ready_for_review",
    "converted_to_draft",
)


def _load_workflow(text: str) -> dict:
    """Load keys as strings, avoiding YAML 1.1's conversion of ``on`` to true."""
    loaded = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict), "workflow must be a YAML mapping"
    return loaded


def _assert_bash_syntax(script: str) -> None:
    result = subprocess.run(
        ["bash", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _reopen_script(metadata_text: str | None = None) -> str:
    metadata = _load_workflow(
        metadata_text
        if metadata_text is not None
        else METADATA_WORKFLOW.read_text(encoding="utf-8")
    )
    return metadata["jobs"]["title"]["steps"][1]["run"]


def _run_reopen_script(
    tmp_path: Path,
    *,
    pages: list[dict] | None = None,
    raw_output: str | None = None,
    gh_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    assert shutil.which("jq"), "semantic reopen test requires the runner's real jq"
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
  echo 'simulated unbounded API diagnostic' >&2
  exit 1
fi
printf '%s\\n' "${FAKE_GH_OUTPUT:?}"
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


def _validate_ci(ci_text: str) -> None:
    ci = _load_workflow(ci_text)
    assert ci["name"] == "CI"
    assert ci["on"] == {
        "pull_request": {
            "branches": ["main"],
            "types": ["opened", "synchronize"],
        },
        "push": {"branches": ["main"]},
    }
    assert ci["permissions"] == {"contents": "read"}
    assert ci["concurrency"] == {
        "group": "${{ github.workflow }}-pr-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": "true",
    }

    test = ci["jobs"]["test"]
    assert test["name"] == "Test", "the required check context must remain stable"
    assert test["needs"] == REQUIRED_CERTIFICATION_JOBS
    assert test["if"] == "always()"
    assert test["runs-on"] == "ubuntu-latest"
    assert test["timeout-minutes"] == "5"
    assert test["steps"] == [
        {
            "name": "Require every certification gate",
            "env": EXPECTED_TEST_ENV,
            "run": EXPECTED_TEST_SCRIPT,
        }
    ]
    _assert_bash_syntax(test["steps"][0]["run"])

    all_steps = [
        step
        for job in ci["jobs"].values()
        for step in job.get("steps", [])
    ]
    full_unit_command = re.compile(
        r"(?:^|\n)\s*python -m pytest tools/rom_tests/tests/unit(?:\s|$)"
    )
    assert all(not full_unit_command.search(step.get("run", "")) for step in all_steps), (
        "the complete unit tree may run only inside the two Gate 0 legs"
    )
    assert COMPONENTS == EXPECTED_GATE0_COMPONENTS


def _validate_metadata(metadata_text: str) -> None:
    metadata = _load_workflow(metadata_text)
    assert metadata["name"] == "PR Metadata"
    assert metadata["on"] == {
        "pull_request": {
            "branches": ["main"],
            "types": list(METADATA_ACTIONS),
        }
    }
    assert metadata["permissions"] == {"contents": "read", "checks": "read"}
    assert metadata["concurrency"] == {
        "group": EXPECTED_METADATA_CONCURRENCY,
        "cancel-in-progress": "true",
    }
    assert set(metadata["jobs"]) == {"title"}

    title = metadata["jobs"]["title"]
    assert title["name"] == EXPECTED_METADATA_JOB_NAME
    assert title["runs-on"] == "ubuntu-latest"
    assert title["timeout-minutes"] == "2"
    assert title["steps"] == [
        {
            "name": "Lint pull request title",
            "env": {"PR_TITLE": "${{ github.event.pull_request.title }}"},
            "run": EXPECTED_TITLE_SCRIPT,
        },
        {
            "name": "Require prior certification when reopening",
            "if": "github.event.action == 'reopened'",
            "env": {
                "GH_TOKEN": "${{ github.token }}",
                "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
                "REPOSITORY": "${{ github.repository }}",
            },
            "run": EXPECTED_REOPEN_SCRIPT,
        },
    ]
    for step in title["steps"]:
        _assert_bash_syntax(step["run"])

    serialized_steps = repr(title["steps"])
    for forbidden in (
        "actions/checkout",
        "setup-python",
        "setup-build",
        "pip install",
        "make ",
        "pytest",
        "emulator",
        "upload-artifact",
        "test-results",
    ):
        assert forbidden not in serialized_steps


def _validate_workflows(ci_text: str, metadata_text: str) -> None:
    """Validate workflow text structurally; YAML comments cannot satisfy contracts."""
    _validate_ci(ci_text)
    _validate_metadata(metadata_text)


def test_code_and_metadata_workflow_contracts() -> None:
    _validate_workflows(
        CI_WORKFLOW.read_text(encoding="utf-8"),
        METADATA_WORKFLOW.read_text(encoding="utf-8"),
    )


def _metadata_run_identity(action: str, pull_request_number: int = 9) -> tuple[str, str]:
    """Model the exact job-name and concurrency expressions asserted above."""
    context = "PR Reopen Certification" if action == "reopened" else "PR Title"
    group = f"PR Metadata-{pull_request_number}-{action}"
    return context, group


def test_reopen_context_survives_later_metadata_event_sequence() -> None:
    reopen_context, reopen_group = _metadata_run_identity("reopened")
    assert reopen_context == "PR Reopen Certification"

    later_actions = (
        "edited",
        "ready_for_review",
        "converted_to_draft",
        "opened",
        "synchronize",
    )
    for action in later_actions:
        context, group = _metadata_run_identity(action)
        assert context == "PR Title"
        assert group != reopen_group

    repeated_context, repeated_group = _metadata_run_identity("reopened")
    assert repeated_context == reopen_context
    assert repeated_group == reopen_group


def test_push_to_main_still_drives_release_certification() -> None:
    release = _load_workflow(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert release["on"] == {
        "workflow_run": {"workflows": ["CI"], "types": ["completed"]}
    }
    release_job = release["jobs"]["release"]
    assert release_job["if"] == (
        "github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.event == 'push'"
    )


@pytest.mark.parametrize(
    "pages",
    [
        [{"check_runs": [{"name": "Test", "conclusion": "success"}]}],
        [
            {
                "check_runs": [
                    {"name": "Test", "conclusion": "cancelled"},
                    {"name": "Test", "conclusion": "success"},
                    {"name": "Test", "conclusion": "failure"},
                    {"name": "Test", "conclusion": "success"},
                ]
            }
        ],
        [
            {"check_runs": [{"name": "Lint", "conclusion": "success"}]},
            {"check_runs": [{"name": "Test", "conclusion": "success"}]},
        ],
    ],
    ids=("one-success", "historical-reruns", "success-on-later-page"),
)
def test_reopen_accepts_any_successful_test_run(
    tmp_path: Path, pages: list[dict]
) -> None:
    result = _run_reopen_script(tmp_path, pages=pages)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "pages",
    [
        [{"check_runs": []}],
        [{"check_runs": [{"name": "Lint", "conclusion": "success"}]}],
        [{"check_runs": [{"name": "Test", "conclusion": None}]}],
    ],
    ids=("zero-check-runs", "missing-test", "test-in-progress"),
)
def test_reopen_rejects_heads_without_a_successful_test(
    tmp_path: Path, pages: list[dict]
) -> None:
    result = _run_reopen_script(tmp_path, pages=pages)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::reopened head SHA has no successful Test check run\n"
    )
    assert result.stderr == ""


def test_reopen_fails_closed_when_gh_api_fails(tmp_path: Path) -> None:
    result = _run_reopen_script(tmp_path, gh_failure=True)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::could not enumerate Test check runs for reopened head SHA\n"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    "raw_output",
    ("not json", '[{"check_runs":', "[{}]"),
    ids=("not-json", "truncated-json", "missing-check-runs-array"),
)
def test_reopen_fails_closed_when_paginated_json_is_malformed(
    tmp_path: Path, raw_output: str
) -> None:
    result = _run_reopen_script(tmp_path, raw_output=raw_output)
    assert result.returncode != 0
    assert result.stdout == (
        "::error::could not parse Test check runs for reopened head SHA\n"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("mutate", "description"),
    [
        (
            lambda ci, metadata: (
                ci.replace("on:\n", "on:\n  workflow_dispatch:\n", 1),
                metadata,
            ),
            "workflow_dispatch bypass",
        ),
        (
            lambda ci, metadata: (
                ci,
                metadata.replace(
                    "github.event.action == 'reopened'",
                    "github.event.action == 'opened'",
                    1,
                ),
            ),
            "reopen guard moved to opened",
        ),
        (
            lambda ci, metadata: (
                ci,
                metadata.replace(
                    '[ "$successful_test_count" -lt 1 ]',
                    '[ "$successful_test_count" -lt 0 ]',
                    1,
                ),
            ),
            "reopen accepts zero successful Test runs",
        ),
        (
            lambda ci, metadata: (
                ci,
                metadata.replace(
                    "name: ${{ github.event.action == 'reopened' && "
                    "'PR Reopen Certification' || 'PR Title' }}",
                    "name: PR Title",
                    1,
                ),
            ),
            "reopen result can be replaced by a later PR Title check",
        ),
        (
            lambda ci, metadata: (
                ci,
                metadata.replace(
                    "group: ${{ github.workflow }}-"
                    "${{ github.event.pull_request.number }}-"
                    "${{ github.event.action }}",
                    "group: ${{ github.workflow }}-"
                    "${{ github.event.pull_request.number }}",
                    1,
                ),
            ),
            "later metadata event can cancel an in-flight reopen check",
        ),
        (
            lambda ci, metadata: (
                ci.replace(
                    "DONOR: ${{ needs.donor-provenance.result }}",
                    "DONOR: success # ${{ needs.donor-provenance.result }}",
                    1,
                ),
                metadata,
            ),
            "hard-coded result with expression in comment",
        ),
    ],
    ids=(
        "workflow-dispatch",
        "opened-guard",
        "accept-zero",
        "constant-title-context",
        "pr-only-concurrency",
        "comment-decoy",
    ),
)
def test_workflow_contract_rejects_critic_mutations(mutate, description) -> None:
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    metadata = METADATA_WORKFLOW.read_text(encoding="utf-8")
    mutated_ci, mutated_metadata = mutate(ci, metadata)
    assert (mutated_ci, mutated_metadata) != (ci, metadata), description
    with pytest.raises(AssertionError):
        _validate_workflows(mutated_ci, mutated_metadata)
