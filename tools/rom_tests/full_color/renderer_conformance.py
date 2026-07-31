"""Independent comparison of renderer expectations with observed carriers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Protocol

from .bank_torture import BankTortureResult
from .errors import RendererConformanceError
from .renderer_oracle import ConformanceCase, OracleExpectation, derive_expectation
from .snapshots import SemanticSnapshot
from .trace import WriterTrace, WriterTraceEntry

CONFORMANCE_REPORT_SCHEMA = "full-color-renderer-conformance-report-v1"
_RESOURCES = frozenset(
    {
        "bg_tile_ids",
        "bg_attributes",
        "bg_palettes",
        "obj_palettes",
        "shadow_oam",
        "hardware_oam",
    }
)
class EvidenceMode(StrEnum):
    SYNTHETIC_CHECKER_SELF_TEST = "synthetic_checker_self_test"
    ROM_RUNTIME = "rom_runtime"


class ObservationProvider(Protocol):
    def snapshot(self, case: ConformanceCase) -> SemanticSnapshot: ...

    def trace(self, case: ConformanceCase) -> WriterTrace: ...

    def boundary(self, case: ConformanceCase) -> BankTortureResult | None: ...


@dataclass(frozen=True, slots=True)
class ConformanceDifference:
    path: str
    expected: object
    actual: object
    trace_sequence: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
            "trace_sequence": self.trace_sequence,
        }


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    case_id: str
    checks: tuple[str, ...]
    mode: EvidenceMode
    passed: bool
    differences: tuple[ConformanceDifference, ...]
    schema: str = CONFORMANCE_REPORT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "checks": list(self.checks),
            "mode": self.mode.value,
            "passed": self.passed,
            "differences": [difference.to_dict() for difference in self.differences],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def check_case(
    case: ConformanceCase,
    provider: ObservationProvider,
    *,
    mode: EvidenceMode,
) -> ConformanceReport:
    try:
        snapshot = provider.snapshot(case)
        trace = provider.trace(case)
        boundary = provider.boundary(case)
    except RendererConformanceError:
        raise
    except Exception as exc:
        raise RendererConformanceError(
            f"{case.case_id}: malformed observation carrier: {exc}"
        ) from exc
    if mode is EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST:
        if snapshot.evidence_kind != "SCHEMA_FIXTURE" or snapshot.activation_phase != 0:
            raise RendererConformanceError(
                "synthetic evidence must remain a phase-0 SCHEMA_FIXTURE"
            )
    elif snapshot.evidence_kind != "RENDERER_RUNTIME" or snapshot.activation_phase == 0:
        raise RendererConformanceError(
            "runtime evidence requires RENDERER_RUNTIME and a nonzero activation phase"
        )
    expectation = derive_expectation(case)
    differences = compare_expectation(expectation, snapshot, trace, boundary)
    return ConformanceReport(
        case.case_id, case.checks, mode, not differences, differences
    )


def compare_expectation(
    expectation: OracleExpectation,
    snapshot: SemanticSnapshot,
    trace: WriterTrace,
    boundary: BankTortureResult | None,
) -> tuple[ConformanceDifference, ...]:
    differences: list[ConformanceDifference] = []
    for patch in expectation.patches:
        if patch.resource not in _RESOURCES:
            raise RendererConformanceError(
                f"oracle patch resource: unknown canonical resource {patch.resource!r}"
            )
        observed = getattr(snapshot, patch.resource)
        end = patch.offset + len(patch.expected)
        if patch.offset < 0 or end > len(observed):
            raise RendererConformanceError(
                f"oracle patch {patch.resource}[0x{patch.offset:04x}]: outside resource"
            )
        for index, expected_byte in enumerate(patch.expected):
            offset = patch.offset + index
            actual_byte = observed[offset]
            if actual_byte != expected_byte:
                differences.append(
                    ConformanceDifference(
                        f"{patch.resource}[0x{offset:04x}]",
                        expected_byte,
                        actual_byte,
                    )
                )

    snapshot_dict = snapshot.to_dict()
    boundary_dict = None if boundary is None else boundary.to_dict()
    for path, expected in expectation.fields:
        source = boundary_dict if path.startswith("case.") else snapshot_dict
        if source is None:
            differences.append(ConformanceDifference(path, expected, None))
            continue
        found, actual = _resolve_dotted(source, path)
        if not found or actual != expected:
            differences.append(
                ConformanceDifference(path, expected, actual if found else None)
            )

    _compare_trace(expectation, trace, differences)
    _compare_machine(expectation, boundary, differences)
    return tuple(sorted(differences, key=_difference_sort_key))


def _resolve_dotted(raw: object, path: str) -> tuple[bool, object]:
    current = raw
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return False, None
        current = current[component]
    return True, current


def _compare_trace(
    expectation: OracleExpectation,
    trace: WriterTrace,
    differences: list[ConformanceDifference],
) -> None:
    predicate = expectation.trace
    if trace.permitted_writer_ids != predicate.permitted_writer_ids:
        differences.append(
            ConformanceDifference(
                "trace.permitted_writer_ids",
                list(predicate.permitted_writer_ids),
                list(trace.permitted_writer_ids),
            )
        )
    if predicate.require_no_writes:
        for entry in trace.entries:
            if entry.wrote:
                differences.append(
                    ConformanceDifference(
                        f"trace[{entry.sequence}].wrote", False, True, entry.sequence
                    )
                )
    jobs = {job.job_id: job for job in predicate.jobs}
    entries_by_job: dict[str, list[WriterTraceEntry]] = {job_id: [] for job_id in jobs}
    for entry in trace.entries:
        declared = entry.job_id in entries_by_job
        if declared:
            entries_by_job[entry.job_id].append(entry)
        elif not predicate.allow_unbound_observations:
            differences.append(
                ConformanceDifference(
                    f"trace[{entry.sequence}].job_id",
                    sorted(jobs),
                    entry.job_id,
                    entry.sequence,
                )
            )
        elif entry.wrote:
            differences.append(
                ConformanceDifference(
                    f"trace[{entry.sequence}].wrote",
                    "non-writing observational evidence",
                    True,
                    entry.sequence,
                )
            )
        _entry_value(
            differences,
            entry,
            "phase",
            predicate.required_phase.value,
            entry.phase.value,
        )
        if entry.wrote and entry.writer_id not in predicate.permitted_writer_ids:
            differences.append(
                ConformanceDifference(
                    f"trace[{entry.sequence}].writer_id",
                    list(predicate.permitted_writer_ids),
                    entry.writer_id,
                    entry.sequence,
                )
            )
    for job_id, job in jobs.items():
        entries = entries_by_job[job_id]
        states = [entry.job_state for entry in entries]
        cursor = 0
        for required_state in job.required_states:
            while cursor < len(states) and states[cursor] is not required_state:
                cursor += 1
            if cursor == len(states):
                differences.append(
                    ConformanceDifference(
                        f"trace.jobs.{job_id}.required_states",
                        [state.value for state in job.required_states],
                        [state.value for state in states],
                    )
                )
                break
            cursor += 1
        cancellation_sequence: int | None = None
        for entry in entries:
            _entry_value(
                differences, entry, "owner", job.owner.value, entry.owner.value
            )
            _entry_value(
                differences,
                entry,
                "job_owner",
                job.owner.value,
                entry.job_owner.value,
            )
            _entry_value(
                differences, entry, "generation", job.generation, entry.generation
            )
            _entry_value(
                differences,
                entry,
                "job_generation",
                job.generation,
                entry.job_generation,
            )
            if entry.job_state.value == "CANCELLED":
                cancellation_sequence = entry.sequence
                actual_reason = (
                    None
                    if entry.cancellation_reason is None
                    else entry.cancellation_reason.value
                )
                expected_reason = (
                    None
                    if job.cancellation_reason is None
                    else job.cancellation_reason.value
                )
                _entry_value(
                    differences,
                    entry,
                    "cancellation_reason",
                    expected_reason,
                    actual_reason,
                )
        if job.cancellation_reason is not None and cancellation_sequence is None:
            differences.append(
                ConformanceDifference(
                    f"trace.jobs.{job_id}.cancellation_reason",
                    job.cancellation_reason.value,
                    None,
                )
            )
        if job.forbid_later_writes and cancellation_sequence is not None:
            for entry in entries:
                if entry.sequence >= cancellation_sequence and entry.wrote:
                    differences.append(
                        ConformanceDifference(
                            f"trace[{entry.sequence}].writer_id",
                            "no write after cancellation",
                            entry.writer_id,
                            entry.sequence,
                        )
                    )
    if predicate.require_complete_commit:
        relevant = [entry for entry in trace.entries if entry.job_id in jobs]
        wrote = [
            entry
            for entry in relevant
            if entry.wrote and jobs[entry.job_id].cancellation_reason is None
        ]
        commit_boundaries = [
            entry
            for entry in relevant
            if jobs[entry.job_id].cancellation_reason is None
            and entry.job_state.value in {"COMMITTING", "COMPLETE"}
        ]
        written_resources = tuple(
            sorted(
                trace.resource_identities.get(
                    entry.resource_id, f"<unmapped:{entry.resource_id}>"
                )
                for entry in wrote
            )
        )
        expected_resources = tuple(sorted(predicate.required_written_resources))
        complete_jobs = {
            entry.job_id for entry in relevant if entry.job_state.value == "COMPLETE"
        }
        if (
            not wrote
            or written_resources != expected_resources
            or any(entry.commit_unit_id != predicate.commit_unit_id for entry in wrote)
            or any(
                entry.commit_unit_id != predicate.commit_unit_id
                for entry in commit_boundaries
            )
            or any(
                job_id not in complete_jobs
                for job_id, job in jobs.items()
                if job.cancellation_reason is None
            )
        ):
            differences.append(
                ConformanceDifference(
                    "trace.complete_commit",
                    {
                        "commit_unit_id": predicate.commit_unit_id,
                        "written_resources": list(expected_resources),
                        "complete": True,
                    },
                    {
                        "commit_unit_ids": sorted(
                            {entry.commit_unit_id for entry in commit_boundaries},
                            key=lambda value: "" if value is None else value,
                        ),
                        "written_resources": list(written_resources),
                        "complete_jobs": sorted(complete_jobs),
                    },
                )
            )


def _entry_value(
    differences: list[ConformanceDifference],
    entry: WriterTraceEntry,
    name: str,
    expected: object,
    actual: object,
) -> None:
    if expected != actual:
        differences.append(
            ConformanceDifference(
                f"trace[{entry.sequence}].{name}",
                expected,
                actual,
                entry.sequence,
            )
        )


def _compare_machine(
    expectation: OracleExpectation,
    boundary: BankTortureResult | None,
    differences: list[ConformanceDifference],
) -> None:
    predicate = expectation.machine
    if predicate is None:
        if boundary is not None:
            raise RendererConformanceError("unexpected boundary observation")
        return
    if boundary is None:
        differences.append(ConformanceDifference("boundary", "required", None))
        return
    pairs: list[tuple[bool, str, object, object]] = [
        (
            predicate.require_banks_restored,
            "banks.rom",
            boundary.before.banks.rom,
            boundary.after.banks.rom,
        ),
        (
            predicate.require_banks_restored,
            "banks.wram",
            boundary.before.banks.wram,
            boundary.after.banks.wram,
        ),
        (
            predicate.require_banks_restored,
            "banks.vram",
            boundary.before.banks.vram,
            boundary.after.banks.vram,
        ),
        (
            predicate.require_stack_pointer_restored,
            "stack_pointer",
            boundary.before.stack_pointer,
            boundary.after.stack_pointer,
        ),
        (
            predicate.require_interrupt_master_enabled_restored,
            "interrupt_master_enabled",
            boundary.before.interrupt_master_enabled,
            boundary.after.interrupt_master_enabled,
        ),
        (
            predicate.require_interrupt_enable_restored,
            "interrupt_enable",
            boundary.before.interrupt_enable,
            boundary.after.interrupt_enable,
        ),
        (
            predicate.require_interrupt_flags_restored,
            "interrupt_flags",
            boundary.before.interrupt_flags,
            boundary.after.interrupt_flags,
        ),
    ]
    for required, name, expected, actual in pairs:
        if required and expected != actual:
            differences.append(
                ConformanceDifference(f"boundary.after.{name}", expected, actual)
            )
    if predicate.require_stack_window_restored:
        for offset, (expected, actual) in enumerate(
            zip(boundary.before.stack_window, boundary.after.stack_window, strict=True)
        ):
            if expected != actual:
                differences.append(
                    ConformanceDifference(
                        f"boundary.after.stack_window[0x{offset:02x}]",
                        expected,
                        actual,
                    )
                )
    if (
        predicate.require_interrupt_observed is not None
        and boundary.interrupt_observed != predicate.require_interrupt_observed
    ):
        differences.append(
            ConformanceDifference(
                "boundary.interrupt_observed",
                predicate.require_interrupt_observed,
                boundary.interrupt_observed,
            )
        )
    restored = not any(d.path.startswith("boundary.after.") for d in differences)
    if boundary.machine_state_restored != restored:
        differences.append(
            ConformanceDifference(
                "boundary.machine_state_restored",
                restored,
                boundary.machine_state_restored,
            )
        )


def _difference_sort_key(difference: ConformanceDifference) -> tuple[object, ...]:
    def stable(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    return (
        difference.path,
        -1 if difference.trace_sequence is None else difference.trace_sequence,
        stable(difference.expected),
        stable(difference.actual),
    )
