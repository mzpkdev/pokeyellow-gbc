"""Closed, authoritative manifest for Phase 1 real-ROM runtime evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ._validation import require_bool, require_int, require_object, require_str
from .errors import ContractError, RendererConformanceError
from .phase1_baseline import (
    BASELINE_REPORT_SCHEMA,
    BaselineSemanticReport,
    compare_phase1_baseline,
)
from .renderer_conformance import (
    CONFORMANCE_REPORT_SCHEMA,
    ConformanceDifference,
    EvidenceMode,
)
from .renderer_conformance_artifacts import (
    CANONICAL_CORPUS_SHA256,
    canonical_case_input,
    canonical_expected,
)
from .renderer_conformance_runtime import (
    ACTIVATED_PHASE1_CASE_IDS,
    canonical_phase1_case,
    check_runtime_observation,
)
from .renderer_oracle import (
    REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES,
    ConformanceCase,
    derive_expectation,
)
from .runtime_observability import RuntimeObservation
from .snapshots import SemanticSnapshot
from .trace import WriterTrace

RUNTIME_MANIFEST_SCHEMA = "full-color-renderer-runtime-manifest-v1"
RUNTIME_RUN_SUMMARY_SCHEMA = "full-color-renderer-runtime-run-summary-v1"
RUNTIME_ACTIVATION_PHASE = 1
RUNTIME_CASE_ROLES = frozenset(
    {
        "case-input",
        "expected-patches",
        "actual-semantic-snapshot",
        "actual-writer-trace",
        "structured-diff",
        "compact-summary",
    }
)
RUNTIME_CASE_FILENAMES = {
    "case-input": "case-input.json",
    "expected-patches": "expected-patches.json",
    "actual-semantic-snapshot": "actual-semantic-snapshot.json",
    "actual-writer-trace": "actual-writer-trace.json",
    "structured-diff": "structured-diff.json",
    "compact-summary": "compact-summary.txt",
}
BASELINE_ROLES = frozenset(
    {"baseline-before", "baseline-after", "baseline-report"}
)
BASELINE_FILENAMES = {
    "baseline-before": "baseline-before.json",
    "baseline-after": "baseline-after.json",
    "baseline-report": "baseline-semantic-report.json",
}
ALL_RUNTIME_ROLES = RUNTIME_CASE_ROLES | BASELINE_ROLES
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _relative_path(value: object, *, path: str) -> str:
    text = require_str(value, path=path, error=RendererConformanceError)
    parsed = PurePosixPath(text)
    if (
        parsed.is_absolute()
        or "." in parsed.parts
        or ".." in parsed.parts
        or "\\" in text
        or parsed.as_posix() != text
    ):
        raise RendererConformanceError(
            f"{path}: artifact path must be normalized and relative, got {text!r}"
        )
    return text


def _sha256(value: object, *, path: str) -> str:
    text = require_str(value, path=path, error=RendererConformanceError)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise RendererConformanceError(
            f"{path}: expected 64 lowercase hexadecimal digits"
        )
    return text


def _string_array(value: object, *, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RendererConformanceError(f"{path}: expected an array")
    result = tuple(
        require_str(item, path=f"{path}[{index}]", error=RendererConformanceError)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise RendererConformanceError(f"{path}: duplicate value")
    return result


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    role: str
    path: str
    size_bytes: int
    sha256: str

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> RuntimeArtifact:
        obj = require_object(
            raw,
            path=path,
            required={"role", "path", "size_bytes", "sha256"},
            error=RendererConformanceError,
        )
        role = require_str(
            obj["role"], path=f"{path}.role", error=RendererConformanceError
        )
        if role not in ALL_RUNTIME_ROLES:
            raise RendererConformanceError(
                f"{path}.role: unknown runtime artifact role {role!r}"
            )
        return cls(
            role=role,
            path=_relative_path(obj["path"], path=f"{path}.path"),
            size_bytes=require_int(
                obj["size_bytes"],
                path=f"{path}.size_bytes",
                minimum=1,
                error=RendererConformanceError,
            ),
            sha256=_sha256(obj["sha256"], path=f"{path}.sha256"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class RuntimeCaseArtifacts:
    case_id: str
    checks: tuple[str, ...]
    mode: EvidenceMode
    passed: bool
    artifacts: tuple[RuntimeArtifact, ...]

    def __post_init__(self) -> None:
        if not self.checks or len(self.checks) != len(set(self.checks)):
            raise RendererConformanceError(
                f"manifest.cases.{self.case_id}.checks: expected unique check IDs"
            )
        roles = tuple(item.role for item in self.artifacts)
        paths = tuple(item.path for item in self.artifacts)
        if set(roles) != RUNTIME_CASE_ROLES or len(roles) != len(set(roles)):
            raise RendererConformanceError(
                f"manifest.cases.{self.case_id}.artifacts: runtime case role closure mismatch"
            )
        if len(paths) != len(set(paths)):
            raise RendererConformanceError(
                f"manifest.cases.{self.case_id}.artifacts: duplicate artifact path"
            )

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> RuntimeCaseArtifacts:
        obj = require_object(
            raw,
            path=path,
            required={"case_id", "checks", "mode", "passed", "artifacts"},
            error=RendererConformanceError,
        )
        mode_text = require_str(
            obj["mode"], path=f"{path}.mode", error=RendererConformanceError
        )
        try:
            mode = EvidenceMode(mode_text)
        except ValueError as exc:
            raise RendererConformanceError(
                f"{path}.mode: unknown evidence mode {mode_text!r}"
            ) from exc
        artifacts_raw = obj["artifacts"]
        if not isinstance(artifacts_raw, list):
            raise RendererConformanceError(f"{path}.artifacts: expected an array")
        return cls(
            case_id=require_str(
                obj["case_id"], path=f"{path}.case_id", error=RendererConformanceError
            ),
            checks=_string_array(obj["checks"], path=f"{path}.checks"),
            mode=mode,
            passed=require_bool(
                obj["passed"], path=f"{path}.passed", error=RendererConformanceError
            ),
            artifacts=tuple(
                RuntimeArtifact.from_dict(item, path=f"{path}.artifacts[{index}]")
                for index, item in enumerate(artifacts_raw)
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "checks": list(self.checks),
            "mode": self.mode.value,
            "passed": self.passed,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    rom_sha256: str
    cases: tuple[RuntimeCaseArtifacts, ...]
    baseline_before: RuntimeArtifact
    baseline_after: RuntimeArtifact
    baseline_report: RuntimeArtifact
    corpus_sha256: str = CANONICAL_CORPUS_SHA256
    activated_case_ids: tuple[str, ...] = ACTIVATED_PHASE1_CASE_IDS
    activation_phase: int = RUNTIME_ACTIVATION_PHASE
    schema: str = RUNTIME_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        self.validate_authority()
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != self.activated_case_ids:
            raise RendererConformanceError(
                "manifest.cases: rows must exactly match activated case order"
            )
        baseline = (self.baseline_before, self.baseline_after, self.baseline_report)
        if tuple(item.role for item in baseline) != (
            "baseline-before",
            "baseline-after",
            "baseline-report",
        ):
            raise RendererConformanceError("manifest baseline role closure mismatch")
        paths = [item.path for case in self.cases for item in case.artifacts]
        paths.extend(item.path for item in baseline)
        if len(paths) != len(set(paths)):
            raise RendererConformanceError("manifest artifact paths must be globally unique")

    def validate_authority(self) -> None:
        if self.schema != RUNTIME_MANIFEST_SCHEMA:
            raise RendererConformanceError("manifest.schema: unsupported version")
        if self.corpus_sha256 != CANONICAL_CORPUS_SHA256:
            raise RendererConformanceError(
                "manifest.corpus_sha256: does not identify the authoritative corpus"
            )
        if self.activated_case_ids != ACTIVATED_PHASE1_CASE_IDS:
            raise RendererConformanceError("runtime manifest case-set mismatch")
        if self.activation_phase != RUNTIME_ACTIVATION_PHASE:
            raise RendererConformanceError(
                "Phase 1 runtime manifest requires activation phase 1"
            )
        _sha256(self.rom_sha256, path="manifest.rom_sha256")

    @classmethod
    def from_dict(cls, raw: object) -> RuntimeManifest:
        obj = require_object(
            raw,
            path="manifest",
            required={
                "schema",
                "corpus_sha256",
                "activated_case_ids",
                "rom_sha256",
                "activation_phase",
                "cases",
                "baseline_before",
                "baseline_after",
                "baseline_report",
            },
            error=RendererConformanceError,
        )
        cases_raw = obj["cases"]
        if not isinstance(cases_raw, list):
            raise RendererConformanceError("manifest.cases: expected an array")
        return cls(
            schema=require_str(
                obj["schema"], path="manifest.schema", error=RendererConformanceError
            ),
            corpus_sha256=_sha256(
                obj["corpus_sha256"], path="manifest.corpus_sha256"
            ),
            activated_case_ids=_string_array(
                obj["activated_case_ids"], path="manifest.activated_case_ids"
            ),
            rom_sha256=_sha256(obj["rom_sha256"], path="manifest.rom_sha256"),
            activation_phase=require_int(
                obj["activation_phase"],
                path="manifest.activation_phase",
                error=RendererConformanceError,
            ),
            cases=tuple(
                RuntimeCaseArtifacts.from_dict(
                    item, path=f"manifest.cases[{index}]"
                )
                for index, item in enumerate(cases_raw)
            ),
            baseline_before=RuntimeArtifact.from_dict(
                obj["baseline_before"], path="manifest.baseline_before"
            ),
            baseline_after=RuntimeArtifact.from_dict(
                obj["baseline_after"], path="manifest.baseline_after"
            ),
            baseline_report=RuntimeArtifact.from_dict(
                obj["baseline_report"], path="manifest.baseline_report"
            ),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> RuntimeManifest:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RendererConformanceError(f"manifest: invalid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "corpus_sha256": self.corpus_sha256,
            "activated_case_ids": list(self.activated_case_ids),
            "rom_sha256": self.rom_sha256,
            "activation_phase": self.activation_phase,
            "cases": [case.to_dict() for case in self.cases],
            "baseline_before": self.baseline_before.to_dict(),
            "baseline_after": self.baseline_after.to_dict(),
            "baseline_report": self.baseline_report.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def artifact_for_path(role: str, path: Path, *, root: Path) -> RuntimeArtifact:
    payload = path.read_bytes()
    return RuntimeArtifact(
        role=role,
        path=path.relative_to(root).as_posix(),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _read_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RendererConformanceError(f"{label}: invalid JSON: {exc}") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_report(raw: object, case: RuntimeCaseArtifacts) -> dict[str, object]:
    obj = require_object(
        raw,
        path="structured-diff",
        required={"schema", "case_id", "checks", "mode", "passed", "differences"},
        error=RendererConformanceError,
    )
    differences = obj["differences"]
    if not isinstance(differences, list):
        raise RendererConformanceError("structured-diff.differences: expected an array")
    for index, value in enumerate(differences):
        item = require_object(
            value,
            path=f"structured-diff.differences[{index}]",
            required={"path", "expected", "actual", "trace_sequence"},
            error=RendererConformanceError,
        )
        require_str(
            item["path"],
            path=f"structured-diff.differences[{index}].path",
            error=RendererConformanceError,
        )
        if item["trace_sequence"] is not None:
            require_int(
                item["trace_sequence"],
                path=f"structured-diff.differences[{index}].trace_sequence",
                error=RendererConformanceError,
            )
    if (
        obj["schema"] != CONFORMANCE_REPORT_SCHEMA
        or obj["case_id"] != case.case_id
        or obj["checks"] != list(case.checks)
        or obj["mode"] != EvidenceMode.ROM_RUNTIME.value
        or obj["passed"] is not case.passed
        or obj["passed"] is not (not differences)
    ):
        raise RendererConformanceError("runtime structured-diff linkage mismatch")
    return obj


def _compact_summary(case: RuntimeCaseArtifacts, report: dict[str, object]) -> str:
    differences = report["differences"]
    assert isinstance(differences, list)
    lines = [
        f"case: {case.case_id}",
        f"mode: {case.mode.value}",
        f"status: {'passed' if case.passed else 'failed'}",
        f"checks: {', '.join(case.checks)}",
        f"differences: {len(differences)}",
    ]
    for item in differences:
        assert isinstance(item, dict)
        lines.append(
            f"- {item['path']}: expected={item['expected']!r} actual={item['actual']!r}"
        )
    return "\n".join(lines) + "\n"


def _parse_baseline_report(raw: object) -> BaselineSemanticReport:
    obj = require_object(
        raw,
        path="baseline-report",
        required={"schema", "passed", "differences"},
        error=RendererConformanceError,
    )
    if obj["schema"] != BASELINE_REPORT_SCHEMA:
        raise RendererConformanceError("baseline-report.schema: unsupported version")
    values = obj["differences"]
    if not isinstance(values, list):
        raise RendererConformanceError("baseline-report.differences: expected an array")
    differences: list[ConformanceDifference] = []
    for index, value in enumerate(values):
        item = require_object(
            value,
            path=f"baseline-report.differences[{index}]",
            required={"path", "expected", "actual", "trace_sequence"},
            error=RendererConformanceError,
        )
        differences.append(
            ConformanceDifference(
                path=require_str(
                    item["path"],
                    path=f"baseline-report.differences[{index}].path",
                    error=RendererConformanceError,
                ),
                expected=item["expected"],
                actual=item["actual"],
                trace_sequence=(
                    None
                    if item["trace_sequence"] is None
                    else require_int(
                        item["trace_sequence"],
                        path=f"baseline-report.differences[{index}].trace_sequence",
                        error=RendererConformanceError,
                    )
                ),
            )
        )
    passed = require_bool(
        obj["passed"], path="baseline-report.passed", error=RendererConformanceError
    )
    if passed is not (not differences):
        raise RendererConformanceError("baseline-report passed/differences mismatch")
    return BaselineSemanticReport(passed, tuple(differences))


def _validate_tree(root: Path, manifest: RuntimeManifest) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RendererConformanceError("runtime evidence root must be a real directory")
    expected_files = {"manifest.json", "run-summary.json"}
    expected_directories = {"cases"}
    expected_files.update(
        {
            manifest.baseline_before.path,
            manifest.baseline_after.path,
            manifest.baseline_report.path,
        }
    )
    expected_files.update(
        item.path for case in manifest.cases for item in case.artifacts
    )
    expected_directories.update(
        PurePosixPath("cases", case.case_id).as_posix() for case in manifest.cases
    )
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RendererConformanceError(
                f"runtime evidence tree contains a symlink: {relative}"
            )
        if path.is_dir():
            actual_directories.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise RendererConformanceError(
                f"runtime evidence tree contains a non-file entry: {relative}"
            )
    missing_files = sorted(expected_files - actual_files)
    extra_files = sorted(actual_files - expected_files)
    missing_directories = sorted(expected_directories - actual_directories)
    extra_directories = sorted(actual_directories - expected_directories)
    if missing_files or extra_files or missing_directories or extra_directories:
        raise RendererConformanceError(
            "runtime evidence tree is not closed: "
            f"missing files={missing_files}, extra files={extra_files}, "
            f"missing directories={missing_directories}, extra directories={extra_directories}"
        )


def validate_runtime_artifacts(
    root: Path,
    manifest: RuntimeManifest,
    *,
    repository_root: Path = _REPOSITORY_ROOT,
) -> None:
    """Reparse and regenerate every retained Phase 1 runtime claim."""
    if root.is_symlink():
        raise RendererConformanceError(
            "runtime evidence root must not be a symlink"
        )
    root = root.resolve()
    repository_root = repository_root.resolve()
    manifest.validate_authority()
    rom_path = repository_root / "pokeyellow_debug.gbc"
    if rom_path.is_symlink() or not rom_path.is_file():
        raise RendererConformanceError(
            "runtime manifest requires the authoritative debug ROM"
        )
    if _file_sha256(rom_path) != manifest.rom_sha256:
        raise RendererConformanceError(
            "runtime manifest ROM identity does not match the authoritative debug ROM"
        )
    _validate_tree(root, manifest)
    manifest_path = root / "manifest.json"
    if manifest_path.read_text(encoding="utf-8") != manifest.to_json():
        raise RendererConformanceError("runtime manifest is not canonical")

    all_artifacts = [
        *(item for case in manifest.cases for item in case.artifacts),
        manifest.baseline_before,
        manifest.baseline_after,
        manifest.baseline_report,
    ]
    for item in all_artifacts:
        path = root / item.path
        resolved = path.resolve()
        if root not in resolved.parents:
            raise RendererConformanceError(
                f"runtime artifact escapes evidence root: {item.path}"
            )
        if path.is_symlink() or not path.is_file():
            raise RendererConformanceError(
                f"runtime artifact is not a regular file: {item.path}"
            )
        payload = path.read_bytes()
        if len(payload) != item.size_bytes:
            raise RendererConformanceError(
                f"runtime artifact size mismatch: {item.path}"
            )
        if hashlib.sha256(payload).hexdigest() != item.sha256:
            raise RendererConformanceError(
                f"runtime artifact sha256 mismatch: {item.path}"
            )

    authoritative_case = canonical_phase1_case(repository_root)
    for case in manifest.cases:
        if case.mode is not EvidenceMode.ROM_RUNTIME:
            raise RendererConformanceError("runtime case requires rom_runtime mode")
        if case.case_id != authoritative_case.case_id:
            raise RendererConformanceError("runtime case identity mismatch")
        if case.checks != authoritative_case.checks:
            raise RendererConformanceError("runtime case checks mismatch")
        by_role = {item.role: item for item in case.artifacts}
        for role, item in by_role.items():
            expected_path = PurePosixPath(
                "cases", case.case_id, RUNTIME_CASE_FILENAMES[role]
            ).as_posix()
            if item.path != expected_path:
                raise RendererConformanceError(
                    f"runtime case canonical artifact path mismatch for {role}"
                )
        case_raw = _read_json(root / by_role["case-input"].path, label="case-input")
        try:
            parsed_case = ConformanceCase.from_dict(
                case_raw,
                mapped_picture_identities=REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES,
            )
        except ContractError as exc:
            raise RendererConformanceError(f"runtime case carrier is invalid: {exc}") from exc
        if canonical_case_input(parsed_case) != case_raw:
            raise RendererConformanceError("runtime case-input is not canonical")
        if canonical_case_input(parsed_case) != canonical_case_input(authoritative_case):
            raise RendererConformanceError("runtime case-input authority mismatch")
        expected_raw = _read_json(
            root / by_role["expected-patches"].path, label="expected-patches"
        )
        if expected_raw != canonical_expected(derive_expectation(authoritative_case)):
            raise RendererConformanceError("runtime expected-patches linkage mismatch")
        try:
            snapshot = SemanticSnapshot.from_json(
                (root / by_role["actual-semantic-snapshot"].path).read_bytes()
            )
            trace = WriterTrace.from_json(
                (root / by_role["actual-writer-trace"].path).read_bytes()
            )
        except ContractError as exc:
            raise RendererConformanceError(f"runtime carrier is invalid: {exc}") from exc
        expected_identity = f"pokeyellow_debug.gbc:{manifest.rom_sha256}"
        if snapshot.to_json() != (root / by_role["actual-semantic-snapshot"].path).read_text(encoding="utf-8"):
            raise RendererConformanceError("runtime snapshot is not canonical")
        if trace.to_json() != (root / by_role["actual-writer-trace"].path).read_text(encoding="utf-8"):
            raise RendererConformanceError("runtime trace is not canonical")
        if snapshot.rom != expected_identity:
            raise RendererConformanceError("runtime snapshot ROM identity mismatch")
        observation = RuntimeObservation(case.case_id, expected_identity, snapshot, trace)
        regenerated = check_runtime_observation(authoritative_case, observation)
        retained = _parse_report(
            _read_json(root / by_role["structured-diff"].path, label="structured-diff"),
            case,
        )
        if regenerated.to_dict() != retained:
            raise RendererConformanceError(
                "runtime structured-diff does not match retained evidence"
            )
        summary = (root / by_role["compact-summary"].path).read_text(encoding="utf-8")
        if summary != _compact_summary(case, retained):
            raise RendererConformanceError("runtime compact-summary linkage mismatch")

    baseline_by_role = {
        item.role: item
        for item in (
            manifest.baseline_before,
            manifest.baseline_after,
            manifest.baseline_report,
        )
    }
    for role, item in baseline_by_role.items():
        if item.path != BASELINE_FILENAMES[role]:
            raise RendererConformanceError(
                f"runtime baseline canonical artifact path mismatch for {role}"
            )
    try:
        before = SemanticSnapshot.from_json(
            (root / manifest.baseline_before.path).read_bytes()
        )
        after = SemanticSnapshot.from_json(
            (root / manifest.baseline_after.path).read_bytes()
        )
    except ContractError as exc:
        raise RendererConformanceError(f"runtime baseline carrier is invalid: {exc}") from exc
    expected_identity = f"pokeyellow_debug.gbc:{manifest.rom_sha256}"
    for label, snapshot in (("before", before), ("after", after)):
        if snapshot.rom != expected_identity:
            raise RendererConformanceError(f"runtime baseline {label} ROM identity mismatch")
        if snapshot.evidence_kind != "YELLOW_BASELINE" or snapshot.activation_phase != 0:
            raise RendererConformanceError(
                f"runtime baseline {label} has wrong provenance"
            )
        path = root / baseline_by_role[f"baseline-{label}"].path
        if snapshot.to_json() != path.read_text(encoding="utf-8"):
            raise RendererConformanceError(f"runtime baseline {label} is not canonical")
    if (
        before.scenario != "phase1-baseline"
        or before.seed != 0
        or before.checkpoint != "before-phase1-runtime"
    ):
        raise RendererConformanceError(
            "runtime baseline before checkpoint linkage mismatch"
        )
    if (
        after.scenario != "phase1-baseline"
        or after.seed != 0
        or after.checkpoint != "after-phase1-restore"
    ):
        raise RendererConformanceError(
            "runtime baseline after checkpoint linkage mismatch"
        )
    retained_baseline = _parse_baseline_report(
        _read_json(root / manifest.baseline_report.path, label="baseline-report")
    )
    regenerated_baseline = compare_phase1_baseline(before, after)
    if retained_baseline.to_dict() != regenerated_baseline.to_dict():
        raise RendererConformanceError(
            "runtime baseline report does not match retained evidence"
        )

    passed = all(case.passed for case in manifest.cases) and retained_baseline.passed
    expected_summary = {
        "schema": RUNTIME_RUN_SUMMARY_SCHEMA,
        "status": "passed" if passed else "failed",
        "rom_sha256": manifest.rom_sha256,
        "activation_phase": manifest.activation_phase,
        "case_ids": list(manifest.activated_case_ids),
        "failed_cases": [case.case_id for case in manifest.cases if not case.passed],
        "baseline_passed": retained_baseline.passed,
    }
    if _read_json(root / "run-summary.json", label="run-summary") != expected_summary:
        raise RendererConformanceError("runtime run-summary linkage mismatch")
