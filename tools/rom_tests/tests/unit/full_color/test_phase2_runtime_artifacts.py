from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.phase2_conformance_runtime import ACTIVATED_PHASE2_CASE_IDS
from tools.rom_tests.full_color.phase2_runtime_artifacts import (
    CASE_FILENAMES, GLOBAL_PATHS, IDENTITY_PATHS, Artifact, Phase2RuntimeManifest,
    artifact_for_path, validate_phase2_runtime_artifacts,
)
from tools.rom_tests.full_color.phase2_runtime_observability import GuardedAuditIdentity


SHA = "0" * 64


def _tree(run: Path) -> tuple[tuple[tuple[str, tuple[Artifact, ...]], ...], tuple[Artifact, ...]]:
    cases = []
    for case_id in ACTIVATED_PHASE2_CASE_IDS:
        rows = []
        for role, filename in sorted(CASE_FILENAMES.items()):
            path = run / "cases" / case_id / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{case_id}:{role}\n", encoding="utf-8")
            rows.append(artifact_for_path(role, path, run))
        cases.append((case_id, tuple(rows)))
    globals_ = []
    for role, relative in sorted(GLOBAL_PATHS.items()):
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}\n" if role == "timing" else (role + "\n").encode())
        globals_.append(artifact_for_path(role, path, run))
    return tuple(cases), tuple(globals_)


def _manifest(run: Path) -> Phase2RuntimeManifest:
    cases, globals_ = _tree(run)
    return Phase2RuntimeManifest(
        identities={name: SHA for name in set(IDENTITY_PATHS) | {"sameboy-tool", "sameboy-report"}},
        guarded_audit=GuardedAuditIdentity(SHA, SHA, SHA, SHA),
        cases=cases, artifacts=globals_,
    )


def test_manifest_round_trips_and_closes_every_required_role(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    assert Phase2RuntimeManifest.from_json(manifest.to_json()) == manifest
    assert tuple(case_id for case_id, _ in manifest.cases) == ACTIVATED_PHASE2_CASE_IDS
    assert {row.role for row in manifest.artifacts} == set(GLOBAL_PATHS)


def test_manifest_rejects_case_role_and_identity_drift(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    case_id, rows = manifest.cases[0]
    with pytest.raises(RendererConformanceError, match="case role closure"):
        replace(manifest, cases=((case_id, rows[:-1]),) + manifest.cases[1:])
    identities = dict(manifest.identities)
    identities.pop("sameboy-tool")
    with pytest.raises(RendererConformanceError, match="identity closure"):
        replace(manifest, identities=identities)


def test_validator_rejects_unlisted_path_and_changed_hash(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "repo"
    run = tmp_path / "run"
    repository.mkdir()
    run.mkdir()
    for relative in IDENTITY_PATHS.values():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("identity\n", encoding="utf-8")
    manifest = _manifest(run)
    identities = {name: __import__("hashlib").sha256((repository / relative).read_bytes()).hexdigest()
                  for name, relative in IDENTITY_PATHS.items()}
    identities.update({"sameboy-tool": SHA, "sameboy-report": manifest.artifacts[[r.role for r in manifest.artifacts].index("timing")].sha256})
    manifest = replace(manifest, identities=identities)
    (run / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    (run / "run-summary.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("tools.rom_tests.full_color.phase2_timing_sameboy.validate_report", lambda *args, **kwargs: None)
    validate_phase2_runtime_artifacts(run, manifest, repository)
    (run / "extra").write_text("bad", encoding="utf-8")
    with pytest.raises(RendererConformanceError, match="not closed"):
        validate_phase2_runtime_artifacts(run, manifest, repository)
    (run / "extra").unlink()
    target = run / manifest.artifacts[0].path
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(RendererConformanceError, match="identity changed"):
        validate_phase2_runtime_artifacts(run, manifest, repository)
