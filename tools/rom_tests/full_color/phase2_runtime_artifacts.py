"""Closed artifact authority for the Phase 2 hostile runtime slice."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from .errors import RendererConformanceError
from .phase2_conformance_runtime import ACTIVATED_PHASE2_CASE_IDS
from .phase2_runtime_observability import GuardedAuditIdentity


MANIFEST_SCHEMA = "full-color-phase2-runtime-manifest-v1"
RUN_SUMMARY_SCHEMA = "full-color-phase2-runtime-run-summary-v1"
ACTIVATION_PHASE = 2

CASE_FILENAMES = {
    "case-input": "case-input.json",
    "expected-patches": "expected-patches.json",
    "actual-semantic-snapshot": "actual-semantic-snapshot.json",
    "actual-writer-trace": "actual-writer-trace.json",
    "structured-diff": "structured-diff.json",
}
GLOBAL_PATHS = {
    "pressure": "pressure.json",
    "boundary": "boundary.json",
    "reconstruction": "reconstruction.json",
    "release-oam-fallback": "release-oam-fallback.json",
    "timing": "timing.json",
    "screenshot": "visuals/screenshot.png",
    "frame-strip": "visuals/frame-strip.png",
    "contact-sheet": "visuals/contact-sheet.png",
    "localized-diff": "visuals/localized-diff.png",
    "localized-diff-metadata": "visuals/localized-diff.json",
    "semantic": "visuals/semantic-snapshot.json",
    "trace": "visuals/writer-trace.json",
}
IDENTITY_PATHS = {
    "debug-rom": "pokeyellow_debug.gbc",
    "debug-map": "pokeyellow_debug.map",
    "debug-sym": "pokeyellow_debug.sym",
    "release-rom": "pokeyellow.gbc",
    "release-map": "pokeyellow.map",
    "release-sym": "pokeyellow.sym",
    "sameboy-lock": "tools/rom_tests/vendor/sameboy.lock",
    "sameboy-bridge-source": "tools/rom_tests/full_color/sameboy_timing_bridge_v1.c",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RendererConformanceError(f"{label}: expected exact SHA-256")
    return value


def _relative(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RendererConformanceError(f"{label}: expected relative path")
    parsed = PurePosixPath(value)
    if (parsed.is_absolute() or "." in parsed.parts or ".." in parsed.parts
            or "\\" in value or parsed.as_posix() != value):
        raise RendererConformanceError(f"{label}: path is not normalized and relative")
    return value


@dataclass(frozen=True, slots=True)
class Artifact:
    role: str
    path: str
    size_bytes: int
    sha256: str

    @classmethod
    def from_dict(cls, raw: object, label: str) -> "Artifact":
        if not isinstance(raw, dict) or set(raw) != {"role", "path", "size_bytes", "sha256"}:
            raise RendererConformanceError(f"{label}: open or incomplete artifact row")
        if not isinstance(raw["role"], str):
            raise RendererConformanceError(f"{label}.role: expected string")
        if type(raw["size_bytes"]) is not int or raw["size_bytes"] < 1:
            raise RendererConformanceError(f"{label}.size_bytes: expected positive integer")
        return cls(raw["role"], _relative(raw["path"], f"{label}.path"), raw["size_bytes"],
                   _require_sha256(raw["sha256"], f"{label}.sha256"))

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role, "path": self.path, "size_bytes": self.size_bytes,
                "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class Phase2RuntimeManifest:
    identities: Mapping[str, str]
    guarded_audit: GuardedAuditIdentity
    cases: tuple[tuple[str, tuple[Artifact, ...]], ...]
    artifacts: tuple[Artifact, ...]
    activation_phase: int = ACTIVATION_PHASE
    schema: str = MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MANIFEST_SCHEMA or self.activation_phase != ACTIVATION_PHASE:
            raise RendererConformanceError("Phase 2 manifest has wrong schema or activation phase")
        if set(self.identities) != set(IDENTITY_PATHS) | {"sameboy-tool", "sameboy-report"}:
            raise RendererConformanceError("Phase 2 manifest identity closure mismatch")
        for name, value in self.identities.items():
            _require_sha256(value, f"manifest.identities.{name}")
        if tuple(case_id for case_id, _ in self.cases) != ACTIVATED_PHASE2_CASE_IDS:
            raise RendererConformanceError("Phase 2 manifest case order mismatch")
        paths: list[str] = []
        for case_id, rows in self.cases:
            if {row.role for row in rows} != set(CASE_FILENAMES) or len(rows) != len(CASE_FILENAMES):
                raise RendererConformanceError(f"{case_id}: case role closure mismatch")
            for row in rows:
                expected = PurePosixPath("cases", case_id, CASE_FILENAMES[row.role]).as_posix()
                if row.path != expected:
                    raise RendererConformanceError(f"{case_id}: non-canonical artifact path")
                paths.append(row.path)
        if {row.role for row in self.artifacts} != set(GLOBAL_PATHS) or len(self.artifacts) != len(GLOBAL_PATHS):
            raise RendererConformanceError("Phase 2 global role closure mismatch")
        for row in self.artifacts:
            if row.path != GLOBAL_PATHS[row.role]:
                raise RendererConformanceError(f"{row.role}: non-canonical artifact path")
            paths.append(row.path)
        if len(paths) != len(set(paths)):
            raise RendererConformanceError("Phase 2 manifest repeats artifact paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "activation_phase": self.activation_phase,
            "identities": dict(sorted(self.identities.items())),
            "guarded_audit": self.guarded_audit.to_dict(),
            "cases": [{"case_id": case_id, "artifacts": [row.to_dict() for row in rows]}
                      for case_id, rows in self.cases],
            "artifacts": [row.to_dict() for row in self.artifacts],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, payload: str | bytes) -> "Phase2RuntimeManifest":
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RendererConformanceError(f"Phase 2 manifest is invalid JSON: {exc}") from exc
        required = {"schema", "activation_phase", "identities", "guarded_audit", "cases", "artifacts"}
        if not isinstance(raw, dict) or set(raw) != required:
            raise RendererConformanceError("Phase 2 manifest has an open or incomplete schema")
        identities = raw["identities"]
        guarded = raw["guarded_audit"]
        cases = raw["cases"]
        artifacts = raw["artifacts"]
        if not isinstance(identities, dict) or not isinstance(guarded, dict):
            raise RendererConformanceError("Phase 2 manifest identities are malformed")
        if set(guarded) != {"rom_sha256", "sym_sha256", "map_sha256", "source_sha256"}:
            raise RendererConformanceError("Phase 2 guarded identity schema mismatch")
        if not isinstance(cases, list) or not isinstance(artifacts, list):
            raise RendererConformanceError("Phase 2 manifest artifact collections are malformed")
        parsed_cases = []
        for index, case in enumerate(cases):
            if not isinstance(case, dict) or set(case) != {"case_id", "artifacts"} or not isinstance(case["case_id"], str) or not isinstance(case["artifacts"], list):
                raise RendererConformanceError(f"manifest.cases[{index}] is malformed")
            parsed_cases.append((case["case_id"], tuple(Artifact.from_dict(row, f"manifest.cases[{index}].artifacts") for row in case["artifacts"])))
        return cls(
            identities={str(key): _require_sha256(value, f"manifest.identities.{key}") for key, value in identities.items()},
            guarded_audit=GuardedAuditIdentity(**guarded),
            cases=tuple(parsed_cases),
            artifacts=tuple(Artifact.from_dict(row, "manifest.artifacts") for row in artifacts),
            activation_phase=raw["activation_phase"], schema=raw["schema"],
        )


def artifact_for_path(role: str, path: Path, root: Path) -> Artifact:
    payload = path.read_bytes()
    return Artifact(role, path.relative_to(root).as_posix(), len(payload), _sha256_bytes(payload))


def expected_artifact_paths() -> set[str]:
    paths = set(GLOBAL_PATHS.values())
    for case_id in ACTIVATED_PHASE2_CASE_IDS:
        paths.update(PurePosixPath("cases", case_id, filename).as_posix()
                     for filename in CASE_FILENAMES.values())
    return paths


def validate_phase2_runtime_artifacts(root: Path, manifest: Phase2RuntimeManifest,
                                      repository_root: Path) -> None:
    """Reject any unlisted path, altered byte, or rebound binary/tool identity."""
    if root.is_symlink() or not root.is_dir():
        raise RendererConformanceError("Phase 2 evidence root must be a real directory")
    root = root.resolve()
    repository_root = repository_root.resolve()
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RendererConformanceError(f"Phase 2 evidence contains symlink: {relative}")
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise RendererConformanceError(f"Phase 2 evidence contains special path: {relative}")
    expected = expected_artifact_paths() | {"manifest.json", "run-summary.json"}
    if actual_files != expected:
        raise RendererConformanceError(
            f"Phase 2 evidence tree is not closed: missing={sorted(expected-actual_files)}, extra={sorted(actual_files-expected)}"
        )
    expected_directories = {"cases", "visuals"} | {
        PurePosixPath("cases", case_id).as_posix()
        for case_id in ACTIVATED_PHASE2_CASE_IDS
    }
    if actual_directories != expected_directories:
        raise RendererConformanceError(
            "Phase 2 evidence directory tree is not closed: "
            f"missing={sorted(expected_directories-actual_directories)}, "
            f"extra={sorted(actual_directories-expected_directories)}"
        )
    if (root / "manifest.json").read_text(encoding="utf-8") != manifest.to_json():
        raise RendererConformanceError("Phase 2 manifest is not canonical")
    rows = [row for _, case_rows in manifest.cases for row in case_rows] + list(manifest.artifacts)
    for row in rows:
        path = root / row.path
        payload = path.read_bytes()
        if len(payload) != row.size_bytes or _sha256_bytes(payload) != row.sha256:
            raise RendererConformanceError(f"Phase 2 artifact identity changed: {row.path}")
    for name, relative in IDENTITY_PATHS.items():
        path = repository_root / relative
        if path.is_symlink() or not path.is_file() or file_sha256(path) != manifest.identities[name]:
            raise RendererConformanceError(f"Phase 2 {name} identity changed")
    timing = root / GLOBAL_PATHS["timing"]
    if file_sha256(timing) != manifest.identities["sameboy-report"]:
        raise RendererConformanceError("Phase 2 SameBoy report identity changed")
    try:
        timing_raw = json.loads(timing.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RendererConformanceError(f"Phase 2 timing report is invalid: {exc}") from exc
    from .phase2_timing_sameboy import validate_report
    validate_report(
        timing_raw,
        rom_sha256=manifest.identities["debug-rom"],
        bridge_sha256=manifest.identities["sameboy-tool"],
    )
