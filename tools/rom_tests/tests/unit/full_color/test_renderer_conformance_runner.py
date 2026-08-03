from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tools.rom_tests.full_color import renderer_conformance_runner
from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.renderer_conformance import EvidenceMode
from tools.rom_tests.full_color.renderer_conformance_artifacts import (
    CONFORMANCE_MANIFEST_SCHEMA,
    REQUIRED_ROLES,
    ConformanceManifest,
    validate_conformance_artifacts,
)
from tools.rom_tests.full_color.renderer_conformance_runner import (
    compare_stable_files,
    main,
    run_renderer_conformance,
)

ROOT = Path(__file__).resolve().parents[5]


def _attempt(results: Path) -> Path:
    return next(results.glob("attempt-*"))


def test_json_failure_uses_current_attempt_not_malformed_stale_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = tmp_path / "attempt-9999"
    stale.mkdir()
    (stale / "summary.json").write_text("{malformed", encoding="utf-8")

    def fail_current(root: Path, results: Path, *, reporter, **kwargs):
        del root, kwargs
        attempt = renderer_conformance_runner.new_attempt(results.resolve())
        reporter.attempt(attempt)
        summary = {"attempt": attempt.name, "status": "failed", "error": "current"}
        renderer_conformance_runner.write_json(attempt / "summary.json", summary)
        raise RendererConformanceError("current")

    monkeypatch.setattr(
        renderer_conformance_runner, "run_renderer_conformance", fail_current
    )
    assert main(["--results", str(tmp_path), "--output", "json"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["attempt"] == "attempt-0001"
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def _manifest_dict(results: Path) -> tuple[Path, dict[str, object]]:
    run = _attempt(results) / "run-1"
    return run, json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def _rewrite_artifact(
    run: Path,
    case: dict[str, object],
    role: str,
    payload: bytes,
) -> None:
    row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == role
    )
    path = run / row["path"]
    path.write_bytes(payload)
    row["size_bytes"] = len(payload)
    row["sha256"] = hashlib.sha256(payload).hexdigest()


def test_runner_executes_twice_and_compares_every_stable_artifact(
    tmp_path: Path,
) -> None:
    summary = run_renderer_conformance(ROOT, tmp_path)

    assert summary["status"] == "passed"
    assert summary["runs"] == ["run-1", "run-2"]
    comparison = summary["comparison"]
    assert isinstance(comparison, dict)
    assert comparison["byte_identical"] is True
    assert comparison["manifest_byte_identical"] is True
    assert comparison["file_count"] > 100
    assert (_attempt(tmp_path) / "run-1/manifest.json").read_bytes() == (
        _attempt(tmp_path) / "run-2/manifest.json"
    ).read_bytes()


def test_each_invocation_retains_a_fresh_attempt(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    first = (_attempt(tmp_path) / "summary.json").read_bytes()
    run_renderer_conformance(ROOT, tmp_path)

    assert sorted(path.name for path in tmp_path.glob("attempt-*")) == [
        "attempt-0001",
        "attempt-0002",
    ]
    assert (tmp_path / "attempt-0001/summary.json").read_bytes() == first


def test_run_two_mutation_retains_localized_failure(tmp_path: Path) -> None:
    with pytest.raises(RendererConformanceError, match="different evidence"):
        run_renderer_conformance(
            ROOT,
            tmp_path,
            mutation_by_run={"run-2": "wrong-attribute-byte"},
        )

    attempt = _attempt(tmp_path)
    summary = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["comparison"]["changed"] == [
        "cases/RC-OVERLAY-PARTIAL-CLIP/actual-semantic-snapshot.json",
        "cases/RC-OVERLAY-PARTIAL-CLIP/compact-summary.txt",
        "cases/RC-OVERLAY-PARTIAL-CLIP/structured-diff.json",
        "manifest.json",
    ]
    case_dir = attempt / "run-2/cases/RC-OVERLAY-PARTIAL-CLIP"
    for name in (
        "case-input.json",
        "expected-patches.json",
        "actual-semantic-snapshot.json",
        "actual-writer-trace.json",
        "structured-diff.json",
        "compact-summary.txt",
    ):
        assert (case_dir / name).is_file()


def test_red_cases_complete_both_runs_before_failure(tmp_path: Path) -> None:
    with pytest.raises(
        RendererConformanceError, match="checker cases failed in run-1, run-2"
    ):
        run_renderer_conformance(
            ROOT,
            tmp_path,
            mutation_by_run={
                "run-1": "wrong-attribute-byte",
                "run-2": "wrong-attribute-byte",
            },
        )

    attempt = _attempt(tmp_path)
    assert (attempt / "run-1/run-summary.json").is_file()
    assert (attempt / "run-2/run-summary.json").is_file()
    assert json.loads((attempt / "summary.json").read_text())["comparison"][
        "byte_identical"
    ] is True


@pytest.mark.parametrize(
    "mutation",
    ["bank-leak", "stack-pointer-leak", "interrupt-enable-leak"],
)
def test_red_boundary_evidence_completes_and_validates_both_runs(
    tmp_path: Path, mutation: str
) -> None:
    with pytest.raises(
        RendererConformanceError, match="checker cases failed in run-1, run-2"
    ):
        run_renderer_conformance(
            ROOT,
            tmp_path,
            mutation_by_run={"run-1": mutation, "run-2": mutation},
        )

    attempt = _attempt(tmp_path)
    for run_name in ("run-1", "run-2"):
        run = attempt / run_name
        assert json.loads((run / "run-summary.json").read_text(encoding="utf-8"))[
            "status"
        ] == "failed"
        manifest = ConformanceManifest.from_json(
            (run / "manifest.json").read_text(encoding="utf-8")
        )
        validate_conformance_artifacts(run, manifest)
        failed = [case for case in manifest.cases if not case.passed]
        assert [case.case_id for case in failed] == ["RC-MACHINE-FAR-CALL"]

    summary = json.loads((attempt / "summary.json").read_text(encoding="utf-8"))
    assert summary["comparison"]["byte_identical"] is True
    assert summary["status"] == "failed"


def test_conformance_manifest_round_trip_and_mode_are_exact(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    manifest = ConformanceManifest.from_dict(raw)

    assert manifest.schema == CONFORMANCE_MANIFEST_SCHEMA
    assert ConformanceManifest.from_json(manifest.to_json()) == manifest
    assert {case.mode for case in manifest.cases} == {
        EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST
    }
    validate_conformance_artifacts(run, manifest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda raw: raw["cases"][0]["artifacts"].pop(0),
            "missing required roles",
        ),
        (
            lambda raw: raw["cases"][0]["artifacts"][0].update({"role": "screenshot"}),
            "unknown artifact role",
        ),
        (
            lambda raw: raw["cases"][0]["artifacts"][0].update(
                {"path": "../escape.json"}
            ),
            "normalized and relative",
        ),
        (
            lambda raw: raw["cases"][0]["artifacts"][1].update(
                {"path": raw["cases"][0]["artifacts"][0]["path"]}
            ),
            "duplicate artifact path",
        ),
        (
            lambda raw: raw["cases"][0].update({"mode": "runtime-ish"}),
            "unknown evidence mode",
        ),
        (
            lambda raw: raw["cases"][0]["artifacts"][0].update({"sha256": "bad"}),
            "64 lowercase hexadecimal digits",
        ),
    ],
)
def test_manifest_rejects_targeted_contract_mutations(
    tmp_path: Path, mutate: object, message: str
) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    _, raw = _manifest_dict(tmp_path)
    broken = deepcopy(raw)
    mutate(broken)

    with pytest.raises(RendererConformanceError, match=message):
        ConformanceManifest.from_dict(broken)


def test_manifest_detects_missing_and_corrupt_linked_files(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    manifest = ConformanceManifest.from_dict(raw)
    artifact = manifest.cases[0].artifacts[0]
    path = run / artifact.path
    original = path.read_bytes()
    path.write_bytes(original + b"x")
    with pytest.raises(RendererConformanceError, match="size mismatch"):
        validate_conformance_artifacts(run, manifest)
    path.write_bytes(original)
    path.unlink()
    with pytest.raises(RendererConformanceError, match="missing files"):
        validate_conformance_artifacts(run, manifest)


def test_manifest_rejects_dropped_case_with_leftover_evidence(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    raw["cases"].pop()

    with pytest.raises(RendererConformanceError, match="authoritative corpus order"):
        ConformanceManifest.from_dict(raw)


def test_manifest_rejects_coherent_whole_case_deletion(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    removed = raw["cases"].pop()
    shutil.rmtree(run / "cases" / removed["case_id"])

    with pytest.raises(RendererConformanceError, match="authoritative corpus order"):
        ConformanceManifest.from_dict(raw)


def test_manifest_rejects_tampered_corpus_binding(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    _, raw = _manifest_dict(tmp_path)
    raw["corpus_sha256"] = "0" * 64

    with pytest.raises(RendererConformanceError, match="authoritative corpus"):
        ConformanceManifest.from_dict(raw)


def test_manifest_rejects_unlisted_file(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    (run / "cases/RC-TRANSFER-ROW/unlisted.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(RendererConformanceError, match="extra files"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_unlisted_case_directory(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    (run / "cases/RC-UNLISTED").mkdir()

    with pytest.raises(RendererConformanceError, match="extra directories"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_unlisted_run_root_file(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    (run / "junk.txt").write_text("junk\n", encoding="utf-8")

    with pytest.raises(RendererConformanceError, match="run root is not closed"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_unlisted_run_root_directory(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    (run / "extra").mkdir()

    with pytest.raises(RendererConformanceError, match="run root is not closed"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_run_root_symlink(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    (run / "manifest-link.json").symlink_to("manifest.json")

    with pytest.raises(RendererConformanceError, match="run root contains a symlink"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_cross_case_artifact_swaps(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)

    for role in sorted(REQUIRED_ROLES):
        broken = deepcopy(raw)
        first, second = broken["cases"][:2]
        first_artifact = next(
            artifact for artifact in first["artifacts"] if artifact["role"] == role
        )
        second_artifact = next(
            artifact for artifact in second["artifacts"] if artifact["role"] == role
        )
        first_index = first["artifacts"].index(first_artifact)
        second_index = second["artifacts"].index(second_artifact)
        first["artifacts"][first_index], second["artifacts"][second_index] = (
            second_artifact,
            first_artifact,
        )

        with pytest.raises(
            RendererConformanceError, match="canonical artifact path mismatch"
        ):
            validate_conformance_artifacts(
                run, ConformanceManifest.from_dict(broken)
            )


def test_manifest_rejects_passed_status_contradicting_structured_diff(
    tmp_path: Path,
) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    broken = deepcopy(raw)
    broken["cases"][0]["passed"] = not broken["cases"][0]["passed"]

    with pytest.raises(RendererConformanceError, match="structured-diff linkage"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(broken))


def test_manifest_rejects_malformed_actual_writer_trace(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    row = next(
        artifact
        for artifact in raw["cases"][0]["artifacts"]
        if artifact["role"] == "actual-writer-trace"
    )
    path = run / row["path"]
    path.write_text("not json\n", encoding="utf-8")
    row["size_bytes"] = len(path.read_bytes())
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(RendererConformanceError, match="linked JSON is invalid"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_malformed_actual_boundary(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    case = next(
        case
        for case in raw["cases"]
        if any(
            artifact["role"] == "actual-boundary"
            for artifact in case["artifacts"]
        )
    )
    row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "actual-boundary"
    )
    path = run / row["path"]
    path.write_text("not json\n", encoding="utf-8")
    row["size_bytes"] = len(path.read_bytes())
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(RendererConformanceError, match="actual-boundary is invalid"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_minimal_case_input(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    _rewrite_artifact(run, raw["cases"][0], "case-input", b"{}\n")

    with pytest.raises(RendererConformanceError, match="linked carrier is invalid"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_minimal_expected_patches(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    _rewrite_artifact(run, raw["cases"][0], "expected-patches", b"{}\n")

    with pytest.raises(RendererConformanceError, match="expected-patches linkage"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_minimal_semantic_snapshot(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    _rewrite_artifact(
        run, raw["cases"][0], "actual-semantic-snapshot", b"{}\n"
    )

    with pytest.raises(RendererConformanceError, match="linked carrier is invalid"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_minimal_structured_diff(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    _rewrite_artifact(run, raw["cases"][0], "structured-diff", b"{}\n")

    with pytest.raises(RendererConformanceError, match="structured-diff"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_minimal_compact_summary(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    _rewrite_artifact(run, raw["cases"][0], "compact-summary", b"junk\n")

    with pytest.raises(RendererConformanceError, match="compact-summary linkage"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_coherent_runtime_relabelling(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    case = raw["cases"][0]
    case["mode"] = EvidenceMode.ROM_RUNTIME.value

    snapshot_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "actual-semantic-snapshot"
    )
    snapshot = json.loads((run / snapshot_row["path"]).read_text(encoding="utf-8"))
    snapshot["evidence_kind"] = "RENDERER_RUNTIME"
    snapshot["activation_phase"] = 1
    _rewrite_artifact(
        run,
        case,
        "actual-semantic-snapshot",
        (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    report_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "structured-diff"
    )
    report = json.loads((run / report_row["path"]).read_text(encoding="utf-8"))
    report["mode"] = EvidenceMode.ROM_RUNTIME.value
    _rewrite_artifact(
        run,
        case,
        "structured-diff",
        (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    summary_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "compact-summary"
    )
    summary = (run / summary_row["path"]).read_text(encoding="utf-8").replace(
        EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST.value,
        EvidenceMode.ROM_RUNTIME.value,
    )
    _rewrite_artifact(run, case, "compact-summary", summary.encode())

    with pytest.raises(RendererConformanceError, match="synthetic checker evidence only"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_snapshot_semantic_mutation(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    case = next(case for case in raw["cases"] if case["case_id"] == "RC-TRANSFER-ROW")
    expected_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "expected-patches"
    )
    expected = json.loads((run / expected_row["path"]).read_text(encoding="utf-8"))
    patch = expected["patches"][0]
    snapshot_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "actual-semantic-snapshot"
    )
    snapshot = json.loads((run / snapshot_row["path"]).read_text(encoding="utf-8"))
    payload = bytearray.fromhex(snapshot[patch["resource"]])
    payload[patch["offset"]] ^= 1
    snapshot[patch["resource"]] = payload.hex()
    _rewrite_artifact(
        run,
        case,
        "actual-semantic-snapshot",
        (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    with pytest.raises(RendererConformanceError, match="does not match retained evidence"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_trace_wrong_phase(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    case = next(case for case in raw["cases"] if case["case_id"] == "RC-TRANSFER-ROW")
    trace_row = next(
        artifact
        for artifact in case["artifacts"]
        if artifact["role"] == "actual-writer-trace"
    )
    trace = json.loads((run / trace_row["path"]).read_text(encoding="utf-8"))
    trace["entries"][0]["phase"] = "OVERWORLD_OVERLAY"
    _rewrite_artifact(
        run,
        case,
        "actual-writer-trace",
        (json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    with pytest.raises(RendererConformanceError, match="does not match retained evidence"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_rehashed_cross_case_snapshot_content_swap(
    tmp_path: Path,
) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    first, second = raw["cases"][:2]
    second_snapshot = next(
        artifact
        for artifact in second["artifacts"]
        if artifact["role"] == "actual-semantic-snapshot"
    )
    _rewrite_artifact(
        run,
        first,
        "actual-semantic-snapshot",
        (run / second_snapshot["path"]).read_bytes(),
    )

    with pytest.raises(RendererConformanceError, match="does not match retained evidence"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(raw))


def test_manifest_rejects_synthetic_row_relabelled_with_runtime_snapshot(
    tmp_path: Path,
) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    run, raw = _manifest_dict(tmp_path)
    manifest = ConformanceManifest.from_dict(raw)
    case = manifest.cases[0]
    snapshot = next(
        artifact
        for artifact in case.artifacts
        if artifact.role == "actual-semantic-snapshot"
    )
    path = run / snapshot.path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence_kind"] = "RENDERER_RUNTIME"
    payload["activation_phase"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    altered = deepcopy(raw)
    row = next(
        artifact
        for artifact in altered["cases"][0]["artifacts"]
        if artifact["role"] == "actual-semantic-snapshot"
    )
    row["size_bytes"] = len(path.read_bytes())
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RendererConformanceError, match="cannot carry runtime evidence"):
        validate_conformance_artifacts(run, ConformanceManifest.from_dict(altered))


def test_stable_comparison_reports_missing_files(tmp_path: Path) -> None:
    run_renderer_conformance(ROOT, tmp_path)
    attempt = _attempt(tmp_path)
    target = attempt / "run-2/cases/RC-TRANSFER-ROW/compact-summary.txt"
    target.unlink()

    comparison = compare_stable_files(attempt / "run-1", attempt / "run-2")
    assert comparison["byte_identical"] is False
    assert comparison["missing_from_run_2"] == [
        "cases/RC-TRANSFER-ROW/compact-summary.txt"
    ]


def test_cli_json_mode_is_one_document_and_keeps_two_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(
        ["--root", str(ROOT), "--results", str(tmp_path), "--output", "json"]
    ) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["status"] == "passed"
    assert summary["runs"] == ["run-1", "run-2"]
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_cli_mutation_keeps_diff_while_failure_output_is_bounded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(
        [
            "--root",
            str(ROOT),
            "--results",
            str(tmp_path),
            "--mutation-run-2",
            "wrong-owner-writer",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert len(captured.err.splitlines()) <= 5
    assert "EVIDENCE" in captured.err
    attempt = _attempt(tmp_path)
    assert next(attempt.glob("run-2/cases/*/structured-diff.json")).is_file()
