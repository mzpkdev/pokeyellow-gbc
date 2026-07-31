"""Versioned manifest for retained renderer-conformance evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ._validation import require_bool, require_int, require_object, require_str
from .bank_torture import BankTortureCase, BankTortureResult, BoundarySnapshot
from .errors import ContractError, RendererConformanceError
from .renderer_conformance import (
    CONFORMANCE_REPORT_SCHEMA,
    EvidenceMode,
    check_case,
)
from .renderer_oracle import (
    CONFORMANCE_CORPUS_SCHEMA,
    REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES,
    ConformanceCase,
    OracleExpectation,
    derive_expectation,
)
from .snapshots import SemanticSnapshot
from .trace import WriterTrace

CONFORMANCE_MANIFEST_SCHEMA = "full-color-renderer-conformance-manifest-v1"
CANONICAL_CORPUS_SHA256 = (
    "d17331c4872be75b7331d78c188cd1e9f45a9eb1a2cd50f2af799dab037bf373"
)
CANONICAL_CORPUS_CASE_IDS = (
    "RC-OVERLAY-OPAQUE-EXPLICIT",
    "RC-OVERLAY-OPAQUE-DEFAULT",
    "RC-OVERLAY-REVEALED-LOOKUP",
    "RC-OVERLAY-REVEALED-OVERRIDE",
    "RC-OVERLAY-FULLY-CLIPPED",
    "RC-OVERLAY-PARTIAL-CLIP",
    "RC-OVERLAY-PARTIAL-RIGHT",
    "RC-OVERLAY-PARTIAL-TOP",
    "RC-OVERLAY-PARTIAL-BOTTOM",
    "RC-OVERLAY-MAP-EDGE",
    "RC-OVERLAY-CONNECTION",
    "RC-OVERLAY-WINDOW",
    "RC-OVERLAY-ALTERNATE-BG",
    "RC-OVERLAY-ALTERNATE-MAP",
    "RC-TRANSFER-ROW",
    "RC-TRANSFER-COLUMN",
    "RC-TRANSFER-CONNECTION",
    "RC-PALETTE-BG",
    "RC-PALETTE-OBJ",
    "RC-OAM-MISSING_IDENTITY",
    "RC-OAM-OUT_OF_RANGE_IDENTITY",
    "RC-OAM-UNMAPPED_IDENTITY",
    "RC-RECONSTRUCTION",
    "RC-OWNERSHIP-REPLACEMENT",
    "RC-MACHINE-FAR-CALL",
)
REQUIRED_ROLES = frozenset(
    {
        "case-input",
        "expected-patches",
        "actual-semantic-snapshot",
        "actual-writer-trace",
        "structured-diff",
        "compact-summary",
    }
)
OPTIONAL_ROLES = frozenset({"actual-boundary"})
ROLE_FILENAMES = {
    "case-input": "case-input.json",
    "expected-patches": "expected-patches.json",
    "actual-semantic-snapshot": "actual-semantic-snapshot.json",
    "actual-writer-trace": "actual-writer-trace.json",
    "structured-diff": "structured-diff.json",
    "compact-summary": "compact-summary.txt",
    "actual-boundary": "actual-boundary.json",
}


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(item) for item in value)
    return value


def canonical_case_input(case: ConformanceCase) -> dict[str, object]:
    return {
        "schema": case.schema,
        "case_id": case.case_id,
        "requirements": list(case.requirements),
        "checks": list(case.checks),
        "operation": case.operation.value,
        "inputs": _thaw(case.inputs),
        "observation_snapshot": case.observation_snapshot,
        "observation_trace": case.observation_trace,
        "observation_boundary": case.observation_boundary,
    }


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return _thaw(value)


def canonical_expected(expectation: OracleExpectation) -> dict[str, object]:
    return {
        "case_id": expectation.case_id,
        "checks": list(expectation.checks),
        "patches": [
            {
                "resource": patch.resource,
                "offset": patch.offset,
                "expected": patch.expected.hex(),
            }
            for patch in expectation.patches
        ],
        "fields": [
            {"path": path, "expected": _json_value(value)}
            for path, value in expectation.fields
        ],
        "trace": {
            "permitted_writer_ids": list(expectation.trace.permitted_writer_ids),
            "jobs": [
                {
                    "job_id": job.job_id,
                    "owner": job.owner.value,
                    "generation": job.generation,
                    "required_states": [state.value for state in job.required_states],
                    "cancellation_reason": (
                        None
                        if job.cancellation_reason is None
                        else job.cancellation_reason.value
                    ),
                    "forbid_later_writes": job.forbid_later_writes,
                }
                for job in expectation.trace.jobs
            ],
            "commit_unit_id": expectation.trace.commit_unit_id,
            "require_complete_commit": expectation.trace.require_complete_commit,
            "require_no_writes": expectation.trace.require_no_writes,
            "required_phase": expectation.trace.required_phase.value,
            "required_written_resources": list(
                expectation.trace.required_written_resources
            ),
            "allow_unbound_observations": (
                expectation.trace.allow_unbound_observations
            ),
        },
        "machine": None
        if expectation.machine is None
        else {
            name: getattr(expectation.machine, name)
            for name in expectation.machine.__dataclass_fields__
        },
    }


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


@dataclass(frozen=True, slots=True)
class ConformanceArtifact:
    role: str
    path: str
    size_bytes: int
    sha256: str

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> ConformanceArtifact:
        obj = require_object(
            raw,
            path=path,
            required={"role", "path", "size_bytes", "sha256"},
            error=RendererConformanceError,
        )
        role = require_str(
            obj["role"], path=f"{path}.role", error=RendererConformanceError
        )
        if role not in REQUIRED_ROLES | OPTIONAL_ROLES:
            raise RendererConformanceError(
                f"{path}.role: unknown artifact role {role!r}"
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
class ConformanceCaseArtifacts:
    case_id: str
    checks: tuple[str, ...]
    mode: EvidenceMode
    passed: bool
    artifacts: tuple[ConformanceArtifact, ...]

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> ConformanceCaseArtifacts:
        obj = require_object(
            raw,
            path=path,
            required={"case_id", "checks", "mode", "passed", "artifacts"},
            error=RendererConformanceError,
        )
        checks_raw = obj["checks"]
        if not isinstance(checks_raw, list) or not checks_raw:
            raise RendererConformanceError(f"{path}.checks: expected a non-empty array")
        checks = tuple(
            require_str(
                item,
                path=f"{path}.checks[{index}]",
                error=RendererConformanceError,
            )
            for index, item in enumerate(checks_raw)
        )
        if len(checks) != len(set(checks)):
            raise RendererConformanceError(f"{path}.checks: duplicate check ID")
        mode_raw = require_str(
            obj["mode"], path=f"{path}.mode", error=RendererConformanceError
        )
        try:
            mode = EvidenceMode(mode_raw)
        except ValueError as exc:
            raise RendererConformanceError(
                f"{path}.mode: unknown evidence mode {mode_raw!r}"
            ) from exc
        artifacts_raw = obj["artifacts"]
        if not isinstance(artifacts_raw, list):
            raise RendererConformanceError(f"{path}.artifacts: expected an array")
        artifacts = tuple(
            ConformanceArtifact.from_dict(item, path=f"{path}.artifacts[{index}]")
            for index, item in enumerate(artifacts_raw)
        )
        roles = [item.role for item in artifacts]
        paths = [item.path for item in artifacts]
        missing = REQUIRED_ROLES - set(roles)
        if missing:
            raise RendererConformanceError(
                f"{path}.artifacts: missing required roles: "
                f"{', '.join(sorted(missing))}"
            )
        if len(roles) != len(set(roles)):
            raise RendererConformanceError(f"{path}.artifacts: duplicate artifact role")
        if len(paths) != len(set(paths)):
            raise RendererConformanceError(f"{path}.artifacts: duplicate artifact path")
        return cls(
            case_id=require_str(
                obj["case_id"],
                path=f"{path}.case_id",
                error=RendererConformanceError,
            ),
            checks=checks,
            mode=mode,
            passed=require_bool(
                obj["passed"], path=f"{path}.passed", error=RendererConformanceError
            ),
            artifacts=artifacts,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "checks": list(self.checks),
            "mode": self.mode.value,
            "passed": self.passed,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class ConformanceManifest:
    cases: tuple[ConformanceCaseArtifacts, ...]
    corpus_sha256: str = CANONICAL_CORPUS_SHA256
    corpus_case_ids: tuple[str, ...] = CANONICAL_CORPUS_CASE_IDS
    schema: str = CONFORMANCE_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if not self.cases:
            raise RendererConformanceError("manifest.cases: expected at least one case")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise RendererConformanceError("manifest.cases: duplicate case ID")
        if self.corpus_sha256 != CANONICAL_CORPUS_SHA256:
            raise RendererConformanceError(
                "manifest.corpus_sha256: does not identify the authoritative corpus"
            )
        if self.corpus_case_ids != CANONICAL_CORPUS_CASE_IDS:
            raise RendererConformanceError(
                "manifest.corpus_case_ids: do not identify the authoritative corpus"
            )
        if tuple(ids) != self.corpus_case_ids:
            raise RendererConformanceError(
                "manifest.cases: rows must exactly match authoritative corpus order"
            )
        paths = [artifact.path for case in self.cases for artifact in case.artifacts]
        if len(paths) != len(set(paths)):
            raise RendererConformanceError(
                "manifest.cases: artifact paths must be globally unique"
            )

    @classmethod
    def from_dict(cls, raw: object) -> ConformanceManifest:
        obj = require_object(
            raw,
            path="manifest",
            required={"schema", "corpus_sha256", "corpus_case_ids", "cases"},
            error=RendererConformanceError,
        )
        if obj["schema"] != CONFORMANCE_MANIFEST_SCHEMA:
            raise RendererConformanceError("manifest.schema: unsupported version")
        cases_raw = obj["cases"]
        if not isinstance(cases_raw, list) or not cases_raw:
            raise RendererConformanceError("manifest.cases: expected a non-empty array")
        corpus_case_ids_raw = obj["corpus_case_ids"]
        if not isinstance(corpus_case_ids_raw, list):
            raise RendererConformanceError(
                "manifest.corpus_case_ids: expected an array"
            )
        return cls(
            cases=tuple(
                ConformanceCaseArtifacts.from_dict(
                    item, path=f"manifest.cases[{index}]"
                )
                for index, item in enumerate(cases_raw)
            ),
            corpus_sha256=_sha256(
                obj["corpus_sha256"], path="manifest.corpus_sha256"
            ),
            corpus_case_ids=tuple(
                require_str(
                    item,
                    path=f"manifest.corpus_case_ids[{index}]",
                    error=RendererConformanceError,
                )
                for index, item in enumerate(corpus_case_ids_raw)
            ),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> ConformanceManifest:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RendererConformanceError(f"manifest: invalid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "corpus_sha256": self.corpus_sha256,
            "corpus_case_ids": list(self.corpus_case_ids),
            "cases": [case.to_dict() for case in self.cases],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def artifact_for_path(role: str, path: Path, *, root: Path) -> ConformanceArtifact:
    payload = path.read_bytes()
    return ConformanceArtifact(
        role=role,
        path=path.relative_to(root).as_posix(),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _validate_report(
    raw: object, *, case: ConformanceCaseArtifacts
) -> tuple[dict[str, object], list[dict[str, object]]]:
    report = require_object(
        raw,
        path="structured-diff",
        required={"schema", "case_id", "checks", "mode", "passed", "differences"},
        error=RendererConformanceError,
    )
    differences_raw = report["differences"]
    if not isinstance(differences_raw, list):
        raise RendererConformanceError("structured-diff.differences: expected an array")
    differences: list[dict[str, object]] = []
    for index, raw_difference in enumerate(differences_raw):
        difference = require_object(
            raw_difference,
            path=f"structured-diff.differences[{index}]",
            required={"path", "expected", "actual", "trace_sequence"},
            error=RendererConformanceError,
        )
        require_str(
            difference["path"],
            path=f"structured-diff.differences[{index}].path",
            error=RendererConformanceError,
        )
        if difference["trace_sequence"] is not None:
            require_int(
                difference["trace_sequence"],
                path=f"structured-diff.differences[{index}].trace_sequence",
                error=RendererConformanceError,
            )
        differences.append(difference)
    checks = report["checks"]
    if not isinstance(checks, list) or checks != list(case.checks):
        raise RendererConformanceError("structured-diff.checks: linkage mismatch")
    if (
        report["schema"] != CONFORMANCE_REPORT_SCHEMA
        or report["case_id"] != case.case_id
        or report["mode"] != case.mode.value
        or report["passed"] is not case.passed
        or report["passed"] is not (not differences)
    ):
        raise RendererConformanceError(
            f"manifest.cases.{case.case_id}: structured-diff linkage mismatch"
        )
    return report, differences


def _canonical_summary(
    case: ConformanceCaseArtifacts, differences: list[dict[str, object]]
) -> str:
    lines = [
        f"case: {case.case_id}",
        f"mode: {case.mode.value}",
        f"status: {'passed' if case.passed else 'failed'}",
        f"checks: {', '.join(case.checks)}",
        f"differences: {len(differences)}",
    ]
    for difference in differences:
        lines.append(
            f"- {difference['path']}: expected={difference['expected']!r} "
            f"actual={difference['actual']!r}"
        )
    return "\n".join(lines) + "\n"


def _parse_boundary_carrier(raw: object) -> BankTortureResult:
    """Parse boundary evidence without asserting that the observed run passed."""
    obj = require_object(
        raw,
        path="boundary",
        required={
            "case",
            "before",
            "during",
            "after",
            "interrupt_observed",
            "machine_state_restored",
        },
        error=RendererConformanceError,
    )
    return BankTortureResult(
        case=BankTortureCase.from_dict(obj["case"], path="boundary.case"),
        before=BoundarySnapshot.from_dict(obj["before"], path="boundary.before"),
        during=BoundarySnapshot.from_dict(obj["during"], path="boundary.during"),
        after=BoundarySnapshot.from_dict(obj["after"], path="boundary.after"),
        interrupt_observed=require_bool(
            obj["interrupt_observed"],
            path="boundary.interrupt_observed",
            error=RendererConformanceError,
        ),
        machine_state_restored=require_bool(
            obj["machine_state_restored"],
            path="boundary.machine_state_restored",
            error=RendererConformanceError,
        ),
    )


@dataclass(frozen=True, slots=True)
class _RetainedObservationProvider:
    semantic_snapshot: SemanticSnapshot
    writer_trace: WriterTrace
    boundary_result: BankTortureResult | None

    def snapshot(self, case: ConformanceCase) -> SemanticSnapshot:
        return self.semantic_snapshot

    def trace(self, case: ConformanceCase) -> WriterTrace:
        return self.writer_trace

    def boundary(self, case: ConformanceCase) -> BankTortureResult | None:
        return self.boundary_result


def validate_conformance_artifacts(root: Path, manifest: ConformanceManifest) -> None:
    """Verify linkage, bytes, and evidence-mode separation for every artifact."""
    resolved_root = root.resolve()
    expected_root_files = {"manifest.json", "run-summary.json"}
    expected_root_directories = {"cases"}
    actual_root_files: set[str] = set()
    actual_root_directories: set[str] = set()
    for path in sorted(resolved_root.iterdir()):
        if path.is_symlink():
            raise RendererConformanceError(
                f"manifest run root contains a symlink: {path.name}"
            )
        if path.is_dir():
            actual_root_directories.add(path.name)
        elif path.is_file():
            actual_root_files.add(path.name)
        else:
            raise RendererConformanceError(
                f"manifest run root contains a non-file entry: {path.name}"
            )
    if (
        actual_root_files != expected_root_files
        or actual_root_directories != expected_root_directories
    ):
        raise RendererConformanceError(
            "manifest run root is not closed: expected files "
            f"{', '.join(sorted(expected_root_files))} and directories "
            f"{', '.join(sorted(expected_root_directories))}; got files "
            f"{', '.join(sorted(actual_root_files)) or '<none>'} and directories "
            f"{', '.join(sorted(actual_root_directories)) or '<none>'}"
        )
    cases_root = resolved_root / "cases"
    if cases_root.is_symlink() or not cases_root.is_dir():
        raise RendererConformanceError(
            "manifest evidence root must contain a real cases directory"
        )
    expected_files = {
        artifact.path for case in manifest.cases for artifact in case.artifacts
    }
    expected_directories = {
        PurePosixPath("cases", case.case_id).as_posix() for case in manifest.cases
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in sorted(cases_root.rglob("*")):
        relative = path.relative_to(resolved_root).as_posix()
        if path.is_symlink():
            raise RendererConformanceError(
                f"manifest evidence tree contains a symlink: {relative}"
            )
        if path.is_dir():
            actual_directories.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise RendererConformanceError(
                f"manifest evidence tree contains a non-file entry: {relative}"
            )
    missing_files = sorted(expected_files - actual_files)
    extra_files = sorted(actual_files - expected_files)
    missing_directories = sorted(expected_directories - actual_directories)
    extra_directories = sorted(actual_directories - expected_directories)
    if missing_files or extra_files or missing_directories or extra_directories:
        details = []
        for label, values in (
            ("missing files", missing_files),
            ("extra files", extra_files),
            ("missing directories", missing_directories),
            ("extra directories", extra_directories),
        ):
            if values:
                details.append(f"{label}: {', '.join(values)}")
        raise RendererConformanceError(
            "manifest evidence tree is not closed: " + "; ".join(details)
        )
    canonical_case_inputs: list[dict[str, object]] = []
    for case in manifest.cases:
        if case.mode is not EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}.mode: v1 retains synthetic "
                "checker evidence only"
            )
        by_role = {artifact.role: artifact for artifact in case.artifacts}
        for artifact in case.artifacts:
            expected_path = PurePosixPath(
                "cases", case.case_id, ROLE_FILENAMES[artifact.role]
            ).as_posix()
            if artifact.path != expected_path:
                raise RendererConformanceError(
                    f"manifest.cases.{case.case_id}.artifacts.{artifact.role}: "
                    f"canonical artifact path mismatch: expected {expected_path!r}, "
                    f"got {artifact.path!r}"
                )
            path = (resolved_root / artifact.path).resolve()
            if resolved_root != path.parent and resolved_root not in path.parents:
                raise RendererConformanceError(
                    f"manifest artifact escapes evidence root: {artifact.path}"
                )
            if not path.is_file():
                raise RendererConformanceError(
                    f"manifest artifact is missing: {artifact.path}"
                )
            payload = path.read_bytes()
            if len(payload) != artifact.size_bytes:
                raise RendererConformanceError(
                    f"manifest artifact size mismatch: {artifact.path}"
                )
            if hashlib.sha256(payload).hexdigest() != artifact.sha256:
                raise RendererConformanceError(
                    f"manifest artifact sha256 mismatch: {artifact.path}"
                )
        snapshot_path = resolved_root / by_role["actual-semantic-snapshot"].path
        case_input_path = resolved_root / by_role["case-input"].path
        expected_path = resolved_root / by_role["expected-patches"].path
        report_path = resolved_root / by_role["structured-diff"].path
        trace_path = resolved_root / by_role["actual-writer-trace"].path
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            case_input = json.loads(case_input_path.read_text(encoding="utf-8"))
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            trace_raw = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RendererConformanceError(
                f"manifest linked JSON is invalid for {case.case_id}: {exc}"
            ) from exc
        try:
            parsed_case = ConformanceCase.from_dict(
                case_input,
                mapped_picture_identities=(
                    REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES
                ),
            )
            parsed_snapshot = SemanticSnapshot.from_dict(snapshot)
        except ContractError as exc:
            raise RendererConformanceError(
                f"manifest linked carrier is invalid for {case.case_id}: {exc}"
            ) from exc
        if canonical_case_input(parsed_case) != case_input:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: case-input is not canonical"
            )
        canonical_case_inputs.append(canonical_case_input(parsed_case))
        if parsed_snapshot.to_dict() != snapshot:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: actual-semantic-snapshot is not canonical"
            )
        boundary_declared = (
            isinstance(case_input, dict)
            and case_input.get("observation_boundary") is not None
        )
        if parsed_case.case_id != case.case_id:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: case-input linkage mismatch"
            )
        if list(parsed_case.checks) != list(case.checks):
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: case-input checks mismatch"
            )
        canonical_expectation = canonical_expected(derive_expectation(parsed_case))
        if expected != canonical_expectation:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: expected-patches linkage mismatch"
            )
        retained_report, _ = _validate_report(report, case=case)
        summary_path = resolved_root / by_role["compact-summary"].path
        try:
            summary_lines = summary_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise RendererConformanceError(
                f"manifest compact summary is invalid for {case.case_id}: {exc}"
            ) from exc
        try:
            trace = WriterTrace.from_dict(trace_raw)
        except ContractError as exc:
            raise RendererConformanceError(
                f"manifest actual-writer-trace is invalid for {case.case_id}: {exc}"
            ) from exc
        expected_trace = expected.get("trace")
        expected_writers = (
            expected_trace.get("permitted_writer_ids")
            if isinstance(expected_trace, dict)
            else None
        )
        if list(trace.permitted_writer_ids) != expected_writers:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: actual-writer-trace linkage mismatch"
            )
        boundary_linked = "actual-boundary" in by_role
        if boundary_declared != boundary_linked:
            expected = "required" if boundary_declared else "forbidden"
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}.artifacts: "
                f"actual-boundary is {expected}"
            )
        boundary: BankTortureResult | None = None
        if boundary_linked:
            boundary_path = resolved_root / by_role["actual-boundary"].path
            try:
                boundary_raw = json.loads(boundary_path.read_text(encoding="utf-8"))
                boundary = _parse_boundary_carrier(boundary_raw)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ContractError) as exc:
                raise RendererConformanceError(
                    f"manifest actual-boundary is invalid for {case.case_id}: {exc}"
                ) from exc
            if boundary.case.case_id != case.case_id:
                raise RendererConformanceError(
                    f"manifest.cases.{case.case_id}: actual-boundary linkage mismatch"
                )
        kind = snapshot.get("evidence_kind") if isinstance(snapshot, dict) else None
        phase = snapshot.get("activation_phase") if isinstance(snapshot, dict) else None
        if case.mode is EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST:
            if kind != "SCHEMA_FIXTURE" or phase != 0:
                raise RendererConformanceError(
                    f"manifest.cases.{case.case_id}: synthetic row cannot carry "
                    "runtime evidence"
                )
        elif kind != "RENDERER_RUNTIME" or phase == 0:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: runtime row requires activated "
                "runtime evidence"
            )
        regenerated_report = check_case(
            parsed_case,
            _RetainedObservationProvider(parsed_snapshot, trace, boundary),
            mode=case.mode,
        )
        if regenerated_report.to_dict() != retained_report:
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: structured-diff does not match "
                "retained evidence"
            )
        regenerated_differences = [
            difference.to_dict() for difference in regenerated_report.differences
        ]
        if "\n".join(summary_lines) + "\n" != _canonical_summary(
            case, regenerated_differences
        ):
            raise RendererConformanceError(
                f"manifest.cases.{case.case_id}: compact-summary linkage mismatch"
            )
    reconstructed_corpus = {
        "schema": CONFORMANCE_CORPUS_SCHEMA,
        "authoritative_mapped_picture_identities": sorted(
            REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES
        ),
        "cases": canonical_case_inputs,
    }
    canonical_payload = json.dumps(
        reconstructed_corpus, sort_keys=True, separators=(",", ":")
    ).encode()
    if hashlib.sha256(canonical_payload).hexdigest() != manifest.corpus_sha256:
        raise RendererConformanceError(
            "manifest corpus binding does not match authoritative case inputs"
        )
