from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.renderer_conformance_artifacts import (
    CONFORMANCE_MANIFEST_SCHEMA,
    REQUIRED_ROLES,
)
from tools.rom_tests.full_color.renderer_runtime_artifacts import (
    RUNTIME_CASE_ROLES,
    RUNTIME_MANIFEST_SCHEMA,
    RuntimeManifest,
    validate_runtime_artifacts,
)
from tools.rom_tests.full_color.renderer_runtime_runner import (
    compare_stable_runtime_evidence,
    main,
    run_renderer_runtime,
)

ROOT = Path(__file__).resolve().parents[5]


def _attempt(results: Path, number: int = 1) -> Path:
    return results / f"attempt-{number:04d}"


def _run(results: Path) -> tuple[Path, Path, dict[str, object]]:
    summary = run_renderer_runtime(ROOT, results)
    attempt = _attempt(results)
    return attempt, attempt / "run-1", summary


def _raw_manifest(run: Path) -> dict[str, object]:
    return json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(run: Path, raw: dict[str, object]) -> RuntimeManifest:
    manifest = RuntimeManifest.from_dict(raw)
    (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def _artifact_row(raw: dict[str, object], role: str) -> dict[str, object]:
    if role.startswith("baseline-"):
        key = role.replace("-", "_", 1)
        return raw[key]
    case = raw["cases"][0]
    return next(item for item in case["artifacts"] if item["role"] == role)


def _rewrite_artifact(
    run: Path,
    raw: dict[str, object],
    role: str,
    mutate,
) -> None:
    row = _artifact_row(raw, role)
    path = run / row["path"]
    payload = path.read_bytes()
    changed = mutate(payload)
    path.write_bytes(changed)
    row["size_bytes"] = len(changed)
    row["sha256"] = hashlib.sha256(changed).hexdigest()


def _rewrite_json(
    run: Path,
    raw: dict[str, object],
    role: str,
    mutate,
) -> None:
    def transform(payload: bytes) -> bytes:
        value = json.loads(payload)
        mutate(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"

    _rewrite_artifact(run, raw, role, transform)


def test_real_runtime_runner_is_closed_deterministic_and_typed(
    tmp_path: Path,
) -> None:
    attempt, run, summary = _run(tmp_path)

    assert summary["status"] == "passed"
    comparison = summary["comparison"]
    assert comparison["byte_identical"] is True
    assert comparison["manifest_byte_identical"] is True
    assert comparison["file_count"] == 10
    assert set(comparison["sha256"]["manifest.json"]) == {"run-1", "run-2"}
    manifest = RuntimeManifest.from_json((run / "manifest.json").read_bytes())
    assert RuntimeManifest.from_json(manifest.to_json()) == manifest
    assert manifest.schema == RUNTIME_MANIFEST_SCHEMA
    validate_runtime_artifacts(run, manifest, repository_root=ROOT)
    assert (attempt / "run-1/manifest.json").read_bytes() == (
        attempt / "run-2/manifest.json"
    ).read_bytes()


def test_each_invocation_retains_a_fresh_attempt(tmp_path: Path) -> None:
    run_renderer_runtime(ROOT, tmp_path)
    first = (_attempt(tmp_path) / "summary.json").read_bytes()
    run_renderer_runtime(ROOT, tmp_path)

    assert [path.name for path in sorted(tmp_path.glob("attempt-*"))] == [
        "attempt-0001",
        "attempt-0002",
    ]
    assert (_attempt(tmp_path) / "summary.json").read_bytes() == first


def test_run1_red_still_completes_run2_and_retains_both_manifests(
    tmp_path: Path,
) -> None:
    with pytest.raises(RendererConformanceError, match="different evidence"):
        run_renderer_runtime(
            ROOT, tmp_path, mutation_by_run={"run-1": "baseline-byte"}
        )

    attempt = _attempt(tmp_path)
    summary = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    assert summary["runs"]["run-1"]["status"] == "failed"
    assert summary["runs"]["run-2"]["status"] == "passed"
    assert (attempt / "run-1/manifest.json").is_file()
    assert (attempt / "run-2/manifest.json").is_file()
    assert "baseline-after.json" in summary["comparison"]["changed"]


def test_identical_red_runs_validate_before_reporting_failure(tmp_path: Path) -> None:
    with pytest.raises(
        RendererConformanceError, match="runtime checks failed in run-1, run-2"
    ):
        run_renderer_runtime(
            ROOT,
            tmp_path,
            mutation_by_run={
                "run-1": "missing-superseded",
                "run-2": "missing-superseded",
            },
        )

    attempt = _attempt(tmp_path)
    summary = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    assert summary["comparison"]["byte_identical"] is True
    for name in ("run-1", "run-2"):
        run = attempt / name
        manifest = RuntimeManifest.from_json((run / "manifest.json").read_bytes())
        assert not manifest.cases[0].passed
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_run2_divergence_reports_exact_changed_hashes(tmp_path: Path) -> None:
    with pytest.raises(RendererConformanceError, match="different evidence"):
        run_renderer_runtime(
            ROOT, tmp_path, mutation_by_run={"run-2": "diverge-frame"}
        )

    comparison = json.loads(
        (_attempt(tmp_path) / "summary.json").read_text(encoding="utf-8")
    )["comparison"]
    assert comparison["changed"] == ["baseline-after.json", "manifest.json"]
    assert comparison["missing_from_run_1"] == []
    assert comparison["missing_from_run_2"] == []
    assert comparison["sha256"]["baseline-after.json"]["run-1"] != comparison[
        "sha256"
    ]["baseline-after.json"]["run-2"]


def test_capture_error_in_run1_does_not_prevent_complete_run2(tmp_path: Path) -> None:
    with pytest.raises(RendererConformanceError, match="run-1"):
        run_renderer_runtime(ROOT, tmp_path, mutation_by_run={"run-1": "error"})

    attempt = _attempt(tmp_path)
    assert (attempt / "run-1/run-error.json").is_file()
    assert (attempt / "run-2/manifest.json").is_file()
    assert (attempt / "run-2/run-summary.json").is_file()


def test_comparison_reports_missing_files_without_hiding_common_hashes(
    tmp_path: Path,
) -> None:
    attempt, _, _ = _run(tmp_path)
    missing = attempt / "run-2/baseline-after.json"
    missing.unlink()

    comparison = compare_stable_runtime_evidence(
        attempt / "run-1", attempt / "run-2"
    )
    assert not comparison["byte_identical"]
    assert comparison["missing_from_run_2"] == ["baseline-after.json"]
    assert "manifest.json" in comparison["sha256"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(schema="bad"), "unsupported version"),
        (
            lambda raw: raw.update(corpus_sha256="0" * 64),
            "authoritative corpus",
        ),
        (
            lambda raw: raw.update(activated_case_ids=["RC-TRANSFER-ROW"]),
            "case-set mismatch",
        ),
        (lambda raw: raw.update(activation_phase=2), "activation phase 1"),
        (lambda raw: raw.update(rom_sha256="bad"), "64 lowercase"),
        (lambda raw: raw["cases"].clear(), "activated case order"),
        (
            lambda raw: raw["cases"][0]["artifacts"].pop(),
            "role closure mismatch",
        ),
        (
            lambda raw: raw["cases"][0]["artifacts"][0].update(
                path="../escape.json"
            ),
            "normalized and relative",
        ),
    ],
)
def test_manifest_parser_rejects_authority_and_shape_mutations(
    tmp_path: Path, mutate, message: str
) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    mutate(raw)
    with pytest.raises(RendererConformanceError, match=message):
        RuntimeManifest.from_dict(raw)


def test_validator_rejects_case_relabel_and_artifact_role_swap(tmp_path: Path) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    relabelled = deepcopy(raw)
    relabelled["cases"][0]["case_id"] = "RC-TRANSFER-ROW"
    with pytest.raises(RendererConformanceError, match="activated case order"):
        RuntimeManifest.from_dict(relabelled)

    swapped = deepcopy(raw)
    swapped["baseline_before"], swapped["baseline_after"] = (
        swapped["baseline_after"],
        swapped["baseline_before"],
    )
    with pytest.raises(RendererConformanceError, match="baseline role closure"):
        RuntimeManifest.from_dict(swapped)

    swapped = deepcopy(raw)
    artifacts = swapped["cases"][0]["artifacts"]
    first, second = artifacts[:2]
    for field in ("path", "size_bytes", "sha256"):
        first[field], second[field] = second[field], first[field]
    manifest = _write_manifest(run, swapped)
    with pytest.raises(RendererConformanceError, match="canonical artifact path"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_validator_rejects_missing_extra_symlink_and_special_entries(
    tmp_path: Path,
) -> None:
    _, run, _ = _run(tmp_path)
    manifest = RuntimeManifest.from_json((run / "manifest.json").read_bytes())
    target = run / manifest.baseline_before.path
    original = target.read_bytes()
    target.unlink()
    with pytest.raises(RendererConformanceError, match="missing files"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)
    target.write_bytes(original)

    extra = run / "extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RendererConformanceError, match="extra files"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)
    extra.unlink()

    target.unlink()
    target.symlink_to("baseline-after.json")
    with pytest.raises(RendererConformanceError, match="symlink"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)
    target.unlink()
    target.write_bytes(original)

    fifo = run / "unexpected.fifo"
    os.mkfifo(fifo)
    with pytest.raises(RendererConformanceError, match="non-file entry"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_validator_rejects_symlinked_green_run_root(tmp_path: Path) -> None:
    _, run, _ = _run(tmp_path / "results")
    manifest = RuntimeManifest.from_json((run / "manifest.json").read_bytes())
    linked_root = tmp_path / "linked-green-run"
    linked_root.symlink_to(run, target_is_directory=True)

    with pytest.raises(RendererConformanceError, match="root must not be a symlink"):
        validate_runtime_artifacts(
            linked_root, manifest, repository_root=ROOT
        )


def test_validator_rejects_size_hash_and_canonical_path_mutations(
    tmp_path: Path,
) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    broken = deepcopy(raw)
    broken["baseline_before"]["size_bytes"] += 1
    manifest = _write_manifest(run, broken)
    with pytest.raises(RendererConformanceError, match="size mismatch"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)

    (run / "manifest.json").write_text(
        RuntimeManifest.from_dict(raw).to_json(), encoding="utf-8"
    )
    broken = deepcopy(raw)
    broken["baseline_before"]["sha256"] = "0" * 64
    manifest = _write_manifest(run, broken)
    with pytest.raises(RendererConformanceError, match="sha256 mismatch"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)

    (run / "manifest.json").write_text(
        RuntimeManifest.from_dict(raw).to_json(), encoding="utf-8"
    )
    broken = deepcopy(raw)
    broken["baseline_before"]["path"] = "renamed.json"
    manifest = _write_manifest(run, broken)
    with pytest.raises(RendererConformanceError, match="not closed|canonical"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_validator_rejects_coherent_rom_rebinding(tmp_path: Path) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    raw["rom_sha256"] = "0" * 64
    manifest = _write_manifest(run, raw)

    with pytest.raises(RendererConformanceError, match="authoritative debug ROM"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


@pytest.mark.parametrize(
    ("role", "mutate", "message"),
    [
        (
            "case-input",
            lambda raw: raw.update(checks=["CHK-OWN-01"]),
            "case carrier is invalid|authority mismatch|checks mismatch",
        ),
        (
            "expected-patches",
            lambda raw: raw.update(checks=[]),
            "expected-patches linkage",
        ),
        (
            "actual-semantic-snapshot",
            lambda raw: raw.update(evidence_kind="SCHEMA_FIXTURE", activation_phase=0),
            "runtime carrier is invalid|wrong evidence provenance|runtime snapshot",
        ),
        (
            "actual-semantic-snapshot",
            lambda raw: raw.update(rom="pokeyellow_debug.gbc:" + "0" * 64),
            "ROM identity mismatch",
        ),
        (
            "structured-diff",
            lambda raw: raw.update(passed=False, differences=[]),
            "linkage mismatch",
        ),
        (
            "baseline-after",
            lambda raw: raw["dirty"].update(bg=not raw["dirty"]["bg"]),
            "baseline report does not match",
        ),
        (
            "baseline-after",
            lambda raw: raw.update(checkpoint="forged-checkpoint"),
            "after checkpoint linkage mismatch",
        ),
    ],
)
def test_coherently_rehashed_semantic_mutations_still_fail_regeneration(
    tmp_path: Path, role: str, mutate, message: str
) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    _rewrite_json(run, raw, role, mutate)
    manifest = _write_manifest(run, raw)
    with pytest.raises(RendererConformanceError, match=message):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_rehashed_compact_summary_cannot_forge_comparator_output(
    tmp_path: Path,
) -> None:
    _, run, _ = _run(tmp_path)
    raw = _raw_manifest(run)
    _rewrite_artifact(run, raw, "compact-summary", lambda payload: payload + b"forged\n")
    manifest = _write_manifest(run, raw)
    with pytest.raises(RendererConformanceError, match="compact-summary linkage"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_run_summary_is_exactly_regenerated(tmp_path: Path) -> None:
    _, run, _ = _run(tmp_path)
    manifest = RuntimeManifest.from_json((run / "manifest.json").read_bytes())
    summary_path = run / "run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "failed"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RendererConformanceError, match="run-summary linkage"):
        validate_runtime_artifacts(run, manifest, repository_root=ROOT)


def test_runtime_contract_does_not_weaken_synthetic_manifest() -> None:
    assert RUNTIME_MANIFEST_SCHEMA != CONFORMANCE_MANIFEST_SCHEMA
    assert RUNTIME_CASE_ROLES == REQUIRED_ROLES


def test_real_cli_returns_success_and_writes_two_runs(tmp_path: Path) -> None:
    assert main(["--root", str(ROOT), "--results", str(tmp_path)]) == 0
    attempt = _attempt(tmp_path)
    assert (attempt / "run-1/manifest.json").is_file()
    assert (attempt / "run-2/manifest.json").is_file()
