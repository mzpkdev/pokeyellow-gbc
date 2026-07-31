"""Pure expected-state oracle for renderer-conformance contract cases.

This module deliberately knows nothing about emulator observations.  It turns
only authoritative request inputs into sparse resource patches and semantic,
trace, and machine-state predicates for a later comparator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Callable

from ._validation import (
    require_bool,
    require_enum,
    require_hex,
    require_int,
    require_object,
    require_str,
)
from .enums import (
    CancellationReason,
    JobState,
    OAMFallbackKind,
    OverlayCell,
    OverlayDestination,
    Owner,
    Phase,
    ReconstructionProvenance,
)
from .errors import RendererConformanceError

CONFORMANCE_CASE_SCHEMA = "full-color-renderer-conformance-case-v1"
CONFORMANCE_CORPUS_SCHEMA = "full-color-renderer-conformance-corpus-v1"

# These are the closed identifiers defined by requirements.md and the check
# definitions in verification-plan.md.  Keeping them here makes fixture
# parsing deterministic and independent of the checkout or current directory.
KNOWN_REQUIREMENT_IDS = frozenset(
    f"R{section}.{item}"
    for section, last in {
        1: 28,
        2: 13,
        3: 6,
        4: 5,
        5: 8,
        6: 12,
        7: 4,
        8: 6,
        9: 9,
        10: 10,
        11: 6,
        12: 8,
    }.items()
    for item in range(1, last + 1)
)
KNOWN_CHECK_IDS = frozenset(
    {
        "CHK-OWN-01",
        "CHK-REQUEST-01",
        "CHK-JOB-01",
        "CHK-COMMIT-01",
        "CHK-RETURN-01",
        "CHK-OVERLAY-01",
        "CHK-OAM-01",
        "CHK-TIME-01",
        "CHK-INV-01",
        "CHK-TRACE-01",
        "CHK-G0-01",
        "CHK-BUILD-01",
        "CHK-CGB-01",
        "CHK-BANK-01",
        "CHK-ROM-01",
        "CHK-PALETTE-01",
        "CHK-TRANSFER-01",
        "CHK-TILESET-01",
        "CHK-HANDOFF-01",
        "CHK-OAM-02",
        "CHK-VISUAL-01",
        "CHK-STRESS-01",
        "CHK-STRESS-02",
        "CHK-STRESS-03",
        "CHK-REMOVE-01",
        "CHK-REGRESS-01",
        "CHK-CANARY-01",
    }
)

REQUIRED_RECONSTRUCTION_ITEMS = frozenset(
    {
        "map_tileset_overrides",
        "viewport_scroll_window_destination",
        "tiles_animation_field_replacements",
        "tilemaps_and_attributes",
        "base_transformed_hardware_palettes",
        "player_follower_object_shadow_oam",
        "request_scheduler_state",
        "machine_state_restored",
    }
)
RECONSTRUCTION_ITEM_PROVENANCE = MappingProxyType(
    {
        "map_tileset_overrides": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
        "viewport_scroll_window_destination": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
        "tiles_animation_field_replacements": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
        "tilemaps_and_attributes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
        "base_transformed_hardware_palettes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
        "player_follower_object_shadow_oam": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
        "request_scheduler_state": ReconstructionProvenance.INITIALIZED_SCHEDULER_STATE,
        "machine_state_restored": ReconstructionProvenance.RESTORED_MACHINE_STATE,
    }
)
OVERLAY_MATRIX_KEYS = frozenset(
    {
        "OVERLAY-ORDINARY-OPAQUE-EXPLICIT",
        "OVERLAY-ORDINARY-OPAQUE-DEFAULT",
        "OVERLAY-ORDINARY-REVEALED-LOOKUP",
        "OVERLAY-ORDINARY-REVEALED-OVERRIDE",
        "OVERLAY-FULLY-CLIPPED",
        "OVERLAY-PARTIALLY-CLIPPED",
        "OVERLAY-MAP-EDGE",
        "OVERLAY-CONNECTION",
        "OVERLAY-WINDOW",
        "OVERLAY-ALTERNATE-BG",
        "OVERLAY-ALTERNATE-MAP",
    }
)
REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES = frozenset({1, 2, 3, 7})
_OVERLAY_MEANINGFUL_ATTRIBUTE_MASK = 0xEF
_ORDINARY_OVERLAY_MATRIX_KEYS = frozenset(
    {
        "OVERLAY-ORDINARY-OPAQUE-EXPLICIT",
        "OVERLAY-ORDINARY-OPAQUE-DEFAULT",
        "OVERLAY-ORDINARY-REVEALED-LOOKUP",
        "OVERLAY-ORDINARY-REVEALED-OVERRIDE",
    }
)

OPERATION_CHECK_IDS = MappingProxyType(
    {
        "PAIRED_TRANSFER": (
            frozenset({"CHK-TRANSFER-01"}),
            frozenset({"CHK-TRANSFER-01", "CHK-COMMIT-01"}),
        ),
        "OVERLAY": (frozenset({"CHK-OVERLAY-01"}), frozenset({"CHK-OVERLAY-01"})),
        "PALETTE_UPLOAD": (
            frozenset({"CHK-PALETTE-01"}),
            frozenset({"CHK-PALETTE-01", "CHK-COMMIT-01"}),
        ),
        "OAM_FALLBACK": (frozenset({"CHK-OAM-01"}), frozenset({"CHK-OAM-01"})),
        "RECONSTRUCTION": (
            frozenset({"CHK-RETURN-01"}),
            frozenset({"CHK-RETURN-01", "CHK-STRESS-02"}),
        ),
        "OWNERSHIP_JOB": (
            frozenset({"CHK-OWN-01", "CHK-JOB-01"}),
            frozenset({"CHK-OWN-01", "CHK-JOB-01", "CHK-COMMIT-01"}),
        ),
        "MACHINE_RESTORE": (frozenset({"CHK-BANK-01"}), frozenset({"CHK-BANK-01"})),
    }
)

_FORBIDDEN_OUTCOME_KEYS = frozenset(
    {
        "required_items",
        "required_states",
        "completed_items",
        "completion",
        "poisoned_items",
        "item_provenance",
        "presentation_barrier_count",
        "cancellation_reason",
        "forbid_later_writes",
        "visible_states",
        "fallback_kind",
        "diagnostic_record",
        "occurred",
        "after_attributes",
        "machine_state_restored",
    }
)
_FORBIDDEN_OUTCOME_KEY_FRAGMENTS = (
    "provenance",
    "completed",
    "completion",
    "poison",
    "barrier",
    "required_state",
    "cancellation_reason",
    "later_write",
    "visible_state",
    "fallback_kind",
    "diagnostic_record",
)


class OperationKind(StrEnum):
    PAIRED_TRANSFER = "PAIRED_TRANSFER"
    OVERLAY = "OVERLAY"
    PALETTE_UPLOAD = "PALETTE_UPLOAD"
    OAM_FALLBACK = "OAM_FALLBACK"
    RECONSTRUCTION = "RECONSTRUCTION"
    OWNERSHIP_JOB = "OWNERSHIP_JOB"
    MACHINE_RESTORE = "MACHINE_RESTORE"


@dataclass(frozen=True, slots=True)
class ResourcePatch:
    resource: str
    offset: int
    expected: bytes


@dataclass(frozen=True, slots=True)
class TraceJobPredicate:
    job_id: str
    owner: Owner
    generation: int
    required_states: tuple[JobState, ...]
    cancellation_reason: CancellationReason | None
    forbid_later_writes: bool


@dataclass(frozen=True, slots=True)
class TracePredicate:
    permitted_writer_ids: tuple[str, ...]
    jobs: tuple[TraceJobPredicate, ...]
    commit_unit_id: str | None
    require_complete_commit: bool
    require_no_writes: bool
    required_phase: Phase
    required_written_resources: tuple[str, ...]
    allow_unbound_observations: bool

    def __post_init__(self) -> None:
        if not self.permitted_writer_ids:
            raise RendererConformanceError(
                "trace predicate: expected at least one permitted writer ID"
            )
        if self.require_complete_commit and self.commit_unit_id is None:
            raise RendererConformanceError(
                "trace predicate: complete commit requires a concrete commit unit ID"
            )
        if self.require_no_writes and self.jobs:
            raise RendererConformanceError(
                "trace predicate: no-write requirement cannot declare jobs"
            )
        if self.require_no_writes and self.require_complete_commit:
            raise RendererConformanceError(
                "trace predicate: no-write requirement cannot require a complete commit"
            )
        if self.require_no_writes and self.commit_unit_id is not None:
            raise RendererConformanceError(
                "trace predicate: no-write requirement cannot name a commit unit"
            )
        if self.require_complete_commit and not self.required_written_resources:
            raise RendererConformanceError(
                "trace predicate: complete commit requires canonical written resources"
            )
        if self.require_no_writes and self.required_written_resources:
            raise RendererConformanceError(
                "trace predicate: no-write requirement cannot name written resources"
            )
        if len(set(self.required_written_resources)) != len(
            self.required_written_resources
        ):
            raise RendererConformanceError(
                "trace predicate: canonical written resources must be unique"
            )

    def accepts_observed_writes(self, wrote_flags: Iterable[bool]) -> bool:
        """Apply the predicate's write-presence rule to decoded trace entries."""
        return not self.require_no_writes or not any(wrote_flags)


@dataclass(frozen=True, slots=True)
class MachineStatePredicate:
    require_banks_restored: bool
    require_stack_pointer_restored: bool
    require_stack_window_restored: bool
    require_interrupt_master_enabled_restored: bool
    require_interrupt_enable_restored: bool
    require_interrupt_flags_restored: bool
    require_interrupt_observed: bool | None


@dataclass(frozen=True, slots=True)
class OracleExpectation:
    case_id: str
    checks: tuple[str, ...]
    patches: tuple[ResourcePatch, ...]
    fields: tuple[tuple[str, object], ...]
    trace: TracePredicate
    machine: MachineStatePredicate | None


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    case_id: str
    requirements: tuple[str, ...]
    checks: tuple[str, ...]
    operation: OperationKind
    inputs: Mapping[str, object]
    observation_snapshot: str
    observation_trace: str
    observation_boundary: str | None
    mapped_picture_identities: frozenset[int] = frozenset()
    schema: str = CONFORMANCE_CASE_SCHEMA

    @classmethod
    def from_dict(
        cls,
        raw: object,
        *,
        mapped_picture_identities: frozenset[int] = frozenset(),
    ) -> "ConformanceCase":
        obj = require_object(
            raw,
            path="case",
            required={
                "schema",
                "case_id",
                "requirements",
                "checks",
                "operation",
                "inputs",
                "observation_snapshot",
                "observation_trace",
                "observation_boundary",
            },
            error=RendererConformanceError,
        )
        if obj["schema"] != CONFORMANCE_CASE_SCHEMA:
            raise RendererConformanceError("case.schema: unsupported version")
        operation = require_enum(
            OperationKind,
            obj["operation"],
            path="case.operation",
            error=RendererConformanceError,
        )
        case = cls(
            case_id=require_str(
                obj["case_id"], path="case.case_id", error=RendererConformanceError
            ),
            requirements=_require_id_array(
                obj["requirements"],
                KNOWN_REQUIREMENT_IDS,
                path="case.requirements",
                prefix="R",
            ),
            checks=_require_id_array(
                obj["checks"],
                KNOWN_CHECK_IDS,
                path="case.checks",
                prefix="CHK-",
            ),
            operation=operation,
            inputs=_freeze_inputs(obj["inputs"]),
            observation_snapshot=_observation_path(
                obj["observation_snapshot"],
                path="case.observation_snapshot",
                suffix=".snapshot.json",
            ),
            observation_trace=_observation_path(
                obj["observation_trace"],
                path="case.observation_trace",
                suffix=".trace.json",
            ),
            observation_boundary=(
                None
                if obj["observation_boundary"] is None
                else _observation_path(
                    obj["observation_boundary"],
                    path="case.observation_boundary",
                    suffix=".boundary.json",
                )
            ),
            mapped_picture_identities=mapped_picture_identities,
        )
        observation_paths = {
            path.casefold()
            for path in (
                case.observation_snapshot,
                case.observation_trace,
                case.observation_boundary,
            )
            if path is not None
        }
        expected_path_count = 2 + (case.observation_boundary is not None)
        if len(observation_paths) != expected_path_count:
            raise RendererConformanceError(
                "case.observation_*: snapshot, trace, and boundary paths must be distinct"
            )
        _validate_case_inputs(case)
        required_checks, allowed_checks = OPERATION_CHECK_IDS[operation.value]
        supplied_checks = frozenset(case.checks)
        missing = sorted(required_checks - supplied_checks)
        unrelated = sorted(supplied_checks - allowed_checks)
        if missing or unrelated:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unrelated:
                details.append("unrelated " + ", ".join(unrelated))
            raise RendererConformanceError(
                f"case.checks: invalid for {operation.value}: " + "; ".join(details)
            )
        return case


def load_corpus(raw: object) -> tuple[ConformanceCase, ...]:
    """Parse a complete corpus and reject ambiguous case/evidence ownership."""
    obj = require_object(
        raw,
        path="corpus",
        required={"schema", "authoritative_mapped_picture_identities", "cases"},
        error=RendererConformanceError,
    )
    if obj["schema"] != CONFORMANCE_CORPUS_SCHEMA:
        raise RendererConformanceError("corpus.schema: unsupported version")
    cases_raw = _sequence(obj["cases"], path="corpus.cases")
    if not cases_raw:
        raise RendererConformanceError("corpus.cases: expected at least one case")
    mapped_raw = _sequence(
        obj["authoritative_mapped_picture_identities"],
        path="corpus.authoritative_mapped_picture_identities",
    )
    mapped = tuple(
        _int(
            value,
            path=f"corpus.authoritative_mapped_picture_identities[{index}]",
            maximum=255,
        )
        for index, value in enumerate(mapped_raw)
    )
    if len(set(mapped)) != len(mapped):
        raise RendererConformanceError(
            "corpus.authoritative_mapped_picture_identities: duplicate identity"
        )
    authority = frozenset(mapped)
    if authority != REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES:
        raise RendererConformanceError(
            "corpus.authoritative_mapped_picture_identities: expected complete "
            "synthetic authority [1, 2, 3, 7]"
        )
    cases = tuple(
        ConformanceCase.from_dict(item, mapped_picture_identities=authority)
        for item in cases_raw
    )
    duplicate = _case_insensitive_duplicates(case.case_id for case in cases)
    if duplicate:
        raise RendererConformanceError(
            "corpus.cases: duplicate case IDs: " + ", ".join(duplicate)
        )
    observation_paths = [
        path
        for case in cases
        for path in (
            case.observation_snapshot,
            case.observation_trace,
            case.observation_boundary,
        )
        if path is not None
    ]
    duplicate_paths = _case_insensitive_duplicates(observation_paths)
    if duplicate_paths:
        raise RendererConformanceError(
            "corpus.cases: observation paths must be globally unique: "
            + ", ".join(duplicate_paths)
        )
    for case in cases:
        expected_paths = {
            "snapshot": f"observations/{case.case_id}.snapshot.json",
            "trace": f"observations/{case.case_id}.trace.json",
            "boundary": f"observations/{case.case_id}.boundary.json",
        }
        actual_paths = {
            "snapshot": case.observation_snapshot,
            "trace": case.observation_trace,
            "boundary": case.observation_boundary,
        }
        for carrier, actual in actual_paths.items():
            if actual is not None and actual != expected_paths[carrier]:
                raise RendererConformanceError(
                    f"case.observation_{carrier}: expected canonical case-owned path "
                    f"{expected_paths[carrier]}"
                )
    oam_kinds = {
        dict(derive_expectation(case).fields)["oam_fallback.fallback_kind"]
        for case in cases
        if case.operation is OperationKind.OAM_FALLBACK
    }
    expected_oam_kinds = {kind.value for kind in OAMFallbackKind}
    if oam_kinds != expected_oam_kinds:
        missing = ", ".join(sorted(expected_oam_kinds - oam_kinds))
        raise RendererConformanceError(
            "corpus.cases: incomplete OAM fallback classifications"
            + (f": missing {missing}" if missing else "")
        )
    overlays = [case for case in cases if case.operation is OperationKind.OVERLAY]
    matrix_keys = {case.inputs["matrix_key"] for case in overlays}
    if matrix_keys != OVERLAY_MATRIX_KEYS:
        missing = ", ".join(sorted(OVERLAY_MATRIX_KEYS - matrix_keys))
        raise RendererConformanceError(
            "corpus.cases: incomplete overlay matrix"
            + (f": missing {missing}" if missing else "")
        )
    partial_edges = {
        case.inputs["clip_edge"]
        for case in overlays
        if case.inputs["matrix_key"] == "OVERLAY-PARTIALLY-CLIPPED"
    }
    if partial_edges != {"left", "right", "top", "bottom"}:
        raise RendererConformanceError(
            "corpus.cases: partial overlay matrix requires left, right, top, and bottom edges"
        )
    overlay_attributes = {
        case.inputs["matrix_key"]: bytes.fromhex(
            dict(derive_expectation(case).fields)["overlay_request.attributes"]
        )
        for case in overlays
    }
    aggregate_attributes = 0
    for attributes in overlay_attributes.values():
        for attribute in attributes:
            if attribute & 0x10:
                raise RendererConformanceError(
                    "corpus.cases: overlay attribute bit 4 must be canonical zero"
                )
    for matrix_key in _ORDINARY_OVERLAY_MATRIX_KEYS:
        for attribute in overlay_attributes[matrix_key]:
            aggregate_attributes |= attribute
    if aggregate_attributes & _OVERLAY_MEANINGFUL_ATTRIBUTE_MASK != _OVERLAY_MEANINGFUL_ATTRIBUTE_MASK:
        raise RendererConformanceError(
            "corpus.cases: overlay explicit/lookup/default/override sources must collectively exercise "
            "palette bits 0-2, bank bit 3, flip bits 5-6, and priority bit 7"
        )
    return cases


def derive_expectation(case: ConformanceCase) -> OracleExpectation:
    """Derive expected state without accepting any observation argument."""
    dispatch: dict[OperationKind, Callable[[ConformanceCase], OracleExpectation]] = {
        OperationKind.PAIRED_TRANSFER: _paired_transfer,
        OperationKind.OVERLAY: _overlay,
        OperationKind.PALETTE_UPLOAD: _palette_upload,
        OperationKind.OAM_FALLBACK: _oam_fallback,
        OperationKind.RECONSTRUCTION: _reconstruction,
        OperationKind.OWNERSHIP_JOB: _ownership_job,
        OperationKind.MACHINE_RESTORE: _machine_restore,
    }
    return dispatch[case.operation](case)


def _require_id_array(
    value: object, known: frozenset[str], *, path: str, prefix: str
) -> tuple[str, ...]:
    values = _sequence(value, path=path)
    result = tuple(
        require_str(item, path=f"{path}[{index}]", error=RendererConformanceError)
        for index, item in enumerate(values)
    )
    if not result:
        raise RendererConformanceError(f"{path}: expected at least one {prefix} ID")
    duplicate = _duplicates(result)
    if duplicate:
        raise RendererConformanceError(f"{path}: duplicate IDs: {', '.join(duplicate)}")
    unknown = sorted(set(result) - known)
    if unknown:
        raise RendererConformanceError(
            f"{path}: unknown {prefix} IDs: {', '.join(unknown)}"
        )
    return result


def _duplicates(values: Any) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        (duplicate if value in seen else seen).add(value)
    return sorted(duplicate)


def _case_insensitive_duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        folded = value.casefold()
        if folded in seen:
            duplicate.add(value)
        else:
            seen.add(folded)
    return sorted(duplicate, key=str.casefold)


def _sequence(value: object, *, path: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise RendererConformanceError(f"{path}: expected an array")
    return value


def _observation_path(value: object, *, path: str, suffix: str) -> str:
    text = require_str(value, path=path, error=RendererConformanceError)
    parsed = PurePosixPath(text)
    if (
        parsed.is_absolute()
        or parsed == PurePosixPath(".")
        or ".." in parsed.parts
        or "\\" in text
        or text != parsed.as_posix()
    ):
        raise RendererConformanceError(f"{path}: expected a normalized relative path")
    if not text.endswith(suffix):
        raise RendererConformanceError(f"{path}: expected {suffix} carrier suffix")
    return text


def _freeze_inputs(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise RendererConformanceError(
            "case.inputs: expected an object with string keys"
        )

    def freeze(item: object, path: str) -> object:
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise RendererConformanceError(f"{path}: expected string keys")
                normalized = key.lower().replace("-", "_")
                if (
                    normalized.startswith(("expected", "actual", "observed"))
                    or "output" in normalized
                    or normalized in _FORBIDDEN_OUTCOME_KEYS
                    or any(
                        fragment in normalized
                        for fragment in _FORBIDDEN_OUTCOME_KEY_FRAGMENTS
                    )
                ):
                    raise RendererConformanceError(
                        f"{path}.{key}: expected-output or observed fields are forbidden in inputs"
                    )
                result[key] = freeze(child, f"{path}.{key}")
            return MappingProxyType(result)
        if isinstance(item, list):
            return tuple(
                freeze(child, f"{path}[{index}]") for index, child in enumerate(item)
            )
        if isinstance(item, (str, int, bool)) or item is None:
            if isinstance(item, str) and item.upper() in {
                "VRAM",
                "AMBIENT_MAP",
                "OBSERVED_SNAPSHOT",
                "WRITER_TRACE",
            }:
                raise RendererConformanceError(
                    f"{path}: forbidden oracle authority {item!r}"
                )
            return item
        raise RendererConformanceError(f"{path}: unsupported JSON value")

    return freeze(value, "case.inputs")  # type: ignore[return-value]


def _obj(value: object, *, path: str, required: set[str]) -> Mapping[str, Any]:
    return require_object(
        value, path=path, required=required, error=RendererConformanceError
    )


def _str(value: object, *, path: str) -> str:
    return require_str(value, path=path, error=RendererConformanceError)


def _int(
    value: object, *, path: str, minimum: int = 0, maximum: int | None = None
) -> int:
    return require_int(
        value,
        path=path,
        minimum=minimum,
        maximum=maximum,
        error=RendererConformanceError,
    )


def _bool(value: object, *, path: str) -> bool:
    return require_bool(value, path=path, error=RendererConformanceError)


def _enum(enum_type: Any, value: object, *, path: str) -> Any:
    return require_enum(enum_type, value, path=path, error=RendererConformanceError)


def _strings(value: object, *, path: str, nonempty: bool = True) -> tuple[str, ...]:
    raw = _sequence(value, path=path)
    result = tuple(
        _str(item, path=f"{path}[{index}]") for index, item in enumerate(raw)
    )
    if nonempty and not result:
        raise RendererConformanceError(f"{path}: expected at least one item")
    if _duplicates(result):
        raise RendererConformanceError(f"{path}: duplicate values")
    return result


_COMMON = {"writer_ids", "owner", "generation", "commit_unit_id"}


def _common(
    inputs: Mapping[str, object],
) -> tuple[tuple[str, ...], Owner, int, str | None]:
    writers = _strings(
        inputs["writer_ids"], path="case.inputs.writer_ids", nonempty=False
    )
    owner = _enum(Owner, inputs["owner"], path="case.inputs.owner")
    generation = _int(inputs["generation"], path="case.inputs.generation")
    raw_commit = inputs["commit_unit_id"]
    commit = (
        None
        if raw_commit is None
        else _str(raw_commit, path="case.inputs.commit_unit_id")
    )
    return writers, owner, generation, commit


def _trace(
    inputs: Mapping[str, object],
    *,
    jobs: tuple[TraceJobPredicate, ...] = (),
    complete: bool = True,
    no_writes: bool,
    resources: tuple[str, ...] = (),
    allow_unbound_observations: bool = False,
) -> TracePredicate:
    writers, _, _, commit = _common(inputs)
    return TracePredicate(
        writers,
        jobs,
        commit,
        complete,
        no_writes,
        Phase.OVERWORLD_ACTIVE,
        resources,
        allow_unbound_observations,
    )


def _require_writer(inputs: Mapping[str, object]) -> None:
    if not _common(inputs)[0]:
        raise RendererConformanceError(
            "case.inputs.writer_ids: expected at least one permitted writer"
        )


def _rectangle(
    value: object, *, path: str, signed_origin: bool
) -> tuple[int, int, int, int]:
    obj = _obj(value, path=path, required={"x", "y", "width", "height"})
    minimum = -4096 if signed_origin else 0
    x = _int(obj["x"], path=f"{path}.x", minimum=minimum, maximum=4096)
    y = _int(obj["y"], path=f"{path}.y", minimum=minimum, maximum=4096)
    width = _int(obj["width"], path=f"{path}.width", minimum=1, maximum=32)
    height = _int(obj["height"], path=f"{path}.height", minimum=1, maximum=32)
    return x, y, width, height


def _destination(
    inputs: Mapping[str, object],
) -> tuple[OverlayDestination, int, int, int]:
    destination = _enum(
        OverlayDestination,
        inputs["destination_selector"],
        path="case.inputs.destination_selector",
    )
    width = _int(
        inputs["destination_width"],
        path="case.inputs.destination_width",
        minimum=1,
        maximum=32,
    )
    height = _int(
        inputs["destination_height"],
        path="case.inputs.destination_height",
        minimum=1,
        maximum=32,
    )
    if (width, height) != (32, 32):
        raise RendererConformanceError(
            "case.inputs.destination_width/height: selected tilemap must be 32x32"
        )
    base = (
        0x400
        if destination
        in {OverlayDestination.BG_MAP_9C00, OverlayDestination.WINDOW_MAP_9C00}
        else 0
    )
    return destination, width, height, base


def _hex(value: object, *, path: str, length: int | None = None) -> bytes:
    return require_hex(value, path=path, length=length, error=RendererConformanceError)


def _validate_case_inputs(case: ConformanceCase) -> None:
    validators: dict[OperationKind, Callable[[ConformanceCase], OracleExpectation]] = {
        OperationKind.PAIRED_TRANSFER: _paired_transfer,
        OperationKind.OVERLAY: _overlay,
        OperationKind.PALETTE_UPLOAD: _palette_upload,
        OperationKind.OAM_FALLBACK: _oam_fallback,
        OperationKind.RECONSTRUCTION: _reconstruction,
        OperationKind.OWNERSHIP_JOB: _ownership_job,
        OperationKind.MACHINE_RESTORE: _machine_restore,
    }
    validators[case.operation](case)
    if case.operation is OperationKind.MACHINE_RESTORE:
        if case.observation_boundary is None:
            raise RendererConformanceError(
                "case.observation_boundary: machine restoration requires boundary evidence"
            )
    elif case.observation_boundary is not None:
        raise RendererConformanceError(
            "case.observation_boundary: only machine restoration accepts boundary evidence"
        )


def _paired_transfer(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON
        | {
            "transfer_kind",
            "destination_selector",
            "destination_width",
            "destination_height",
            "rectangle",
            "tile_ids",
            "attributes",
        },
    )
    kind = _str(inputs["transfer_kind"], path="case.inputs.transfer_kind")
    _require_writer(inputs)
    if kind not in {"ROW", "COLUMN", "CONNECTION"}:
        raise RendererConformanceError(
            "case.inputs.transfer_kind: unknown transfer kind"
        )
    _, width, height, base = _destination(inputs)
    x, y, rect_width, rect_height = _rectangle(
        inputs["rectangle"], path="case.inputs.rectangle", signed_origin=False
    )
    if x + rect_width > width or y + rect_height > height:
        raise RendererConformanceError(
            "case.inputs.rectangle: exceeds selected destination"
        )
    size = rect_width * rect_height
    tiles = _hex(inputs["tile_ids"], path="case.inputs.tile_ids", length=size)
    attributes = _hex(inputs["attributes"], path="case.inputs.attributes", length=size)
    patches: list[ResourcePatch] = []
    for row in range(rect_height):
        source = row * rect_width
        offset = base + (y + row) * 32 + x
        patches.append(
            ResourcePatch("bg_tile_ids", offset, tiles[source : source + rect_width])
        )
        patches.append(
            ResourcePatch(
                "bg_attributes", offset, attributes[source : source + rect_width]
            )
        )
    writers, owner, generation, _ = _common(inputs)
    job = TraceJobPredicate(
        f"JOB-{case.case_id}",
        owner,
        generation,
        (JobState.PREPARED, JobState.COMMITTING, JobState.COMPLETE),
        None,
        False,
    )
    return OracleExpectation(
        case.case_id,
        case.checks,
        tuple(patches),
        (("transfer_state", kind),),
        _trace(
            inputs,
            jobs=(job,),
            no_writes=False,
            resources=("bg_tile_ids", "bg_attributes"),
        ),
        None,
    )


def _overlay(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON
        | {
            "matrix_key",
            "clip_edge",
            "destination_selector",
            "destination_width",
            "destination_height",
            "rectangle",
            "world_transform",
            "map_id",
            "tileset_id",
            "classifications",
            "tile_ids",
            "explicit_attributes",
            "text_window_default",
            "coordinate_overrides",
            "tileset_attributes",
        },
    )
    matrix_key = _str(inputs["matrix_key"], path="case.inputs.matrix_key")
    if matrix_key not in OVERLAY_MATRIX_KEYS:
        raise RendererConformanceError(
            "case.inputs.matrix_key: unknown overlay matrix key"
        )
    clip_raw = inputs["clip_edge"]
    clip_edge = (
        None if clip_raw is None else _str(clip_raw, path="case.inputs.clip_edge")
    )
    if clip_edge not in {None, "left", "right", "top", "bottom"}:
        raise RendererConformanceError("case.inputs.clip_edge: unknown clipping edge")
    if (matrix_key == "OVERLAY-PARTIALLY-CLIPPED") is not (clip_edge is not None):
        raise RendererConformanceError(
            "case.inputs.clip_edge: required only for partially clipped matrix cases"
        )
    _, width, height, base = _destination(inputs)
    x, y, rect_width, rect_height = _rectangle(
        inputs["rectangle"], path="case.inputs.rectangle", signed_origin=True
    )
    size = rect_width * rect_height
    raw_classes = _sequence(
        inputs["classifications"], path="case.inputs.classifications"
    )
    if len(raw_classes) != size:
        raise RendererConformanceError(
            f"case.inputs.classifications: expected exactly {size} cells"
        )
    classes = tuple(
        _enum(OverlayCell, value, path=f"case.inputs.classifications[{index}]")
        for index, value in enumerate(raw_classes)
    )
    tiles = _hex(inputs["tile_ids"], path="case.inputs.tile_ids", length=size)
    transform_raw = _sequence(
        inputs["world_transform"], path="case.inputs.world_transform"
    )
    if len(transform_raw) != 6:
        raise RendererConformanceError(
            "case.inputs.world_transform: expected six integers"
        )
    transform = tuple(
        _int(
            value,
            path=f"case.inputs.world_transform[{index}]",
            minimum=-65536,
            maximum=65536,
        )
        for index, value in enumerate(transform_raw)
    )
    a, b, c, d, tx, ty = transform
    if a * d - b * c == 0:
        raise RendererConformanceError(
            "case.inputs.world_transform: singular transform loses source-to-world mapping"
        )
    map_id = _str(inputs["map_id"], path="case.inputs.map_id")
    tileset_id = _str(inputs["tileset_id"], path="case.inputs.tileset_id")
    default = (
        _int(
            inputs["text_window_default"],
            path="case.inputs.text_window_default",
            maximum=255,
        )
        & 0xEF
    )
    lookup = _hex(
        inputs["tileset_attributes"], path="case.inputs.tileset_attributes", length=256
    )
    explicit_obj = _obj(
        inputs["explicit_attributes"],
        path="case.inputs.explicit_attributes",
        required=set(inputs["explicit_attributes"]),
    )
    explicit: dict[int, int] = {}
    for key, value in explicit_obj.items():
        try:
            index = int(key)
        except ValueError as exc:
            raise RendererConformanceError(
                f"case.inputs.explicit_attributes.{key}: expected cell index"
            ) from exc
        if str(index) != key or not 0 <= index < size:
            raise RendererConformanceError(
                f"case.inputs.explicit_attributes.{key}: invalid cell index"
            )
        explicit[index] = (
            _int(value, path=f"case.inputs.explicit_attributes.{key}", maximum=255)
            & 0xEF
        )
    override_obj = _obj(
        inputs["coordinate_overrides"],
        path="case.inputs.coordinate_overrides",
        required=set(inputs["coordinate_overrides"]),
    )
    overrides: dict[tuple[int, int], int] = {}
    for key, value in override_obj.items():
        parts = key.split(",")
        try:
            coordinate = (int(parts[0]), int(parts[1])) if len(parts) == 2 else None
        except ValueError:
            coordinate = None
        if coordinate is None or f"{coordinate[0]},{coordinate[1]}" != key:
            raise RendererConformanceError(
                f"case.inputs.coordinate_overrides.{key}: expected canonical x,y"
            )
        overrides[coordinate] = (
            _int(value, path=f"case.inputs.coordinate_overrides.{key}", maximum=255)
            & 0xEF
        )

    rows: dict[int, list[tuple[int, int, int, int, int]]] = {}
    mappings: list[dict[str, int]] = []
    all_attributes: list[int] = []
    for source_y in range(rect_height):
        for source_x in range(rect_width):
            destination_x, destination_y = x + source_x, y + source_y
            index = source_y * rect_width + source_x
            world_x = a * source_x + b * source_y + tx
            world_y = c * source_x + d * source_y + ty
            if classes[index] is OverlayCell.OPAQUE_OVERLAY:
                attribute = explicit.get(index, default)
            else:
                attribute = (
                    overrides.get((world_x, world_y), lookup[tiles[index]]) & 0xEF
                )
            all_attributes.append(attribute)
            if not (0 <= destination_x < width and 0 <= destination_y < height):
                continue
            rows.setdefault(destination_y, []).append(
                (destination_x, tiles[index], attribute, source_x, source_y)
            )
            mappings.append(
                {
                    "source_index": index,
                    "destination_x": destination_x,
                    "destination_y": destination_y,
                    "world_x": world_x,
                    "world_y": world_y,
                }
            )

    _validate_overlay_matrix(
        matrix_key=matrix_key,
        clip_edge=clip_edge,
        destination=inputs["destination_selector"],
        rectangle=(x, y, rect_width, rect_height),
        map_id=map_id,
        tileset_id=tileset_id,
        classes=classes,
        explicit=explicit,
        overrides=overrides,
        transform=transform,
        mappings=mappings,
    )

    patches: list[ResourcePatch] = []
    for destination_y in sorted(rows):
        cells = sorted(rows[destination_y])
        # Rectangular clipping leaves a contiguous interval on each row.
        first_x = cells[0][0]
        offset = base + destination_y * 32 + first_x
        patches.append(
            ResourcePatch("bg_tile_ids", offset, bytes(cell[1] for cell in cells))
        )
        patches.append(
            ResourcePatch("bg_attributes", offset, bytes(cell[2] for cell in cells))
        )
    writers, owner, generation, commit = _common(inputs)
    if mappings and (not writers or commit is None):
        raise RendererConformanceError(
            "case.inputs: overlay with surviving cells requires a writer and commit unit"
        )
    jobs: tuple[TraceJobPredicate, ...]
    if mappings:
        jobs = (
            TraceJobPredicate(
                f"JOB-{case.case_id}",
                owner,
                generation,
                (JobState.PREPARED, JobState.COMMITTING, JobState.COMPLETE),
                None,
                False,
            ),
        )
    else:
        jobs = ()
        if writers != ("WR-NONE",):
            raise RendererConformanceError(
                "case.inputs.writer_ids: fully clipped overlay requires the canonical "
                "non-writing allowlist [WR-NONE]"
            )
        if commit is not None:
            raise RendererConformanceError(
                "case.inputs.commit_unit_id: fully clipped overlay cannot have a commit"
            )
    return OracleExpectation(
        case.case_id,
        case.checks,
        tuple(patches),
        (
            ("overlay_request.destination_selector", inputs["destination_selector"]),
            ("overlay_request.map_id", map_id),
            ("overlay_request.tileset_id", tileset_id),
            (
                "overlay_request.rectangle",
                {"x": x, "y": y, "width": rect_width, "height": rect_height},
            ),
            ("overlay_request.world_origin", None),
            ("overlay_request.world_transform", list(transform)),
            (
                "overlay_request.coordinate_overrides",
                dict(sorted(override_obj.items())),
            ),
            ("overlay_request.classifications", [item.value for item in classes]),
            ("overlay_request.tile_ids", tiles.hex()),
            ("overlay_request.attributes", bytes(all_attributes).hex()),
            ("overlay_request.clipped_mappings", mappings),
            ("overlay_request.oracle_sources", ["REQUEST_DATA"]),
        ),
        _trace(
            inputs,
            jobs=jobs,
            complete=bool(mappings),
            no_writes=not mappings,
            resources=("bg_tile_ids", "bg_attributes") if mappings else (),
        ),
        None,
    )


def _validate_overlay_matrix(
    *,
    matrix_key: str,
    clip_edge: str | None,
    destination: object,
    rectangle: tuple[int, int, int, int],
    map_id: str,
    tileset_id: str,
    classes: tuple[OverlayCell, ...],
    explicit: Mapping[int, int],
    overrides: Mapping[tuple[int, int], int],
    transform: tuple[int, ...],
    mappings: Sequence[Mapping[str, int]],
) -> None:
    """Make every matrix label a consequence of its causal request shape."""
    x, y, width, height = rectangle
    area = width * height
    if tileset_id != "OVERWORLD":
        raise RendererConformanceError(
            "case.inputs.tileset_id: matrix case requires canonical OVERWORLD tileset"
        )

    if matrix_key in _ORDINARY_OVERLAY_MATRIX_KEYS:
        if (
            destination != OverlayDestination.BG_MAP_9800.value
            or map_id != "PALLET_TOWN"
            or area != 1
            or len(mappings) != 1
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: ordinary case requires one unclipped Pallet Town BG 9800 cell"
            )
        opaque = classes == (OverlayCell.OPAQUE_OVERLAY,)
        revealed = classes == (OverlayCell.REVEALED_TERRAIN,)
        if matrix_key == "OVERLAY-ORDINARY-OPAQUE-EXPLICIT" and not (
            opaque and 0 in explicit
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: explicit opaque case is mislabeled"
            )
        if matrix_key == "OVERLAY-ORDINARY-OPAQUE-DEFAULT" and not (
            opaque and not explicit
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: default opaque case is mislabeled"
            )
        if matrix_key == "OVERLAY-ORDINARY-REVEALED-LOOKUP" and not (
            revealed and not overrides
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: revealed lookup case is mislabeled"
            )
        if matrix_key == "OVERLAY-ORDINARY-REVEALED-OVERRIDE":
            world = (transform[4], transform[5])
            if not (revealed and world in overrides):
                raise RendererConformanceError(
                    "case.inputs.matrix_key: revealed override case is mislabeled"
                )
        return

    clipped_destinations = {
        "OVERLAY-FULLY-CLIPPED": OverlayDestination.BG_MAP_9800.value,
        "left": OverlayDestination.WINDOW_MAP_9C00.value,
        "right": OverlayDestination.BG_MAP_9800.value,
        "top": OverlayDestination.BG_MAP_9800.value,
        "bottom": OverlayDestination.BG_MAP_9800.value,
    }
    if matrix_key == "OVERLAY-FULLY-CLIPPED":
        if mappings or not (x + width <= 0 or y + height <= 0 or x >= 32 or y >= 32):
            raise RendererConformanceError(
                "case.inputs.matrix_key: fully clipped case is mislabeled"
            )
    elif matrix_key == "OVERLAY-PARTIALLY-CLIPPED":
        edge_matches = {
            "left": x < 0 < x + width,
            "right": x < 32 < x + width,
            "top": y < 0 < y + height,
            "bottom": y < 32 < y + height,
        }
        crossed_edges = {edge for edge, crossed in edge_matches.items() if crossed}
        if crossed_edges != {clip_edge} or not 0 < len(mappings) < area:
            raise RendererConformanceError(
                "case.inputs.matrix_key: partially clipped edge is mislabeled"
            )
    if matrix_key in {"OVERLAY-FULLY-CLIPPED", "OVERLAY-PARTIALLY-CLIPPED"}:
        declared_destination = clipped_destinations[
            matrix_key if matrix_key == "OVERLAY-FULLY-CLIPPED" else clip_edge or ""
        ]
        if (
            destination != declared_destination
            or map_id != "PALLET_TOWN"
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: clipped case has wrong destination, map, or tileset identity"
            )
        if area < 4 or classes != tuple(
            OverlayCell.OPAQUE_OVERLAY
            if index % 2 == 0
            else OverlayCell.REVEALED_TERRAIN
            for index in range(area)
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: clipped case requires alternating mixed classifications"
            )
        _validate_mixed_overlay_sources(
            width=width,
            area=area,
            classes=classes,
            explicit=explicit,
            overrides=overrides,
            transform=transform,
        )
        return
    if matrix_key == "OVERLAY-MAP-EDGE":
        if (
            destination != OverlayDestination.BG_MAP_9800.value
            or map_id != "PALLET_TOWN"
            or x + width != 32
            or y + height != 32
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: map-edge case is mislabeled"
            )
    elif matrix_key == "OVERLAY-CONNECTION":
        if (
            destination != OverlayDestination.BG_MAP_9800.value
            or map_id != "ROUTE_1"
            or (x, y, width, height) != (0, 0, 2, 2)
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: connection case is mislabeled"
            )
    elif matrix_key == "OVERLAY-WINDOW":
        if (
            destination != OverlayDestination.WINDOW_MAP_9C00.value
            or map_id != "PALLET_TOWN"
            or not mappings
            or len(mappings) != area
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: window case is mislabeled"
            )
    elif matrix_key == "OVERLAY-ALTERNATE-BG":
        if (
            destination != OverlayDestination.BG_MAP_9C00.value
            or map_id != "PALLET_TOWN"
            or not mappings
            or len(mappings) != area
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: alternate-BG case is mislabeled"
            )
    elif matrix_key == "OVERLAY-ALTERNATE-MAP":
        if (
            destination != OverlayDestination.BG_MAP_9800.value
            or map_id != "VIRIDIAN_CITY"
            or not mappings
            or len(mappings) != area
        ):
            raise RendererConformanceError(
                "case.inputs.matrix_key: alternate-map case is mislabeled"
            )

    if area < 4 or set(classes) != set(OverlayCell):
        raise RendererConformanceError(
            "case.inputs.matrix_key: edge/connection/destination/map cases require mixed classification arithmetic"
        )
    _validate_mixed_overlay_sources(
        width=width,
        area=area,
        classes=classes,
        explicit=explicit,
        overrides=overrides,
        transform=transform,
    )


def _validate_mixed_overlay_sources(
    *,
    width: int,
    area: int,
    classes: tuple[OverlayCell, ...],
    explicit: Mapping[int, int],
    overrides: Mapping[tuple[int, int], int],
    transform: tuple[int, ...],
) -> None:
    """Require independent coverage of every overlay attribute-source branch."""
    world_by_index = {
        index: (
            transform[0] * (index % width)
            + transform[1] * (index // width)
            + transform[4],
            transform[2] * (index % width)
            + transform[3] * (index // width)
            + transform[5],
        )
        for index in range(area)
    }
    if not (
        any(
            classes[index] is OverlayCell.OPAQUE_OVERLAY and index in explicit
            for index in range(area)
        )
        and any(
            classes[index] is OverlayCell.OPAQUE_OVERLAY and index not in explicit
            for index in range(area)
        )
        and any(
            classes[index] is OverlayCell.REVEALED_TERRAIN
            and world_by_index[index] in overrides
            for index in range(area)
        )
        and any(
            classes[index] is OverlayCell.REVEALED_TERRAIN
            and world_by_index[index] not in overrides
            for index in range(area)
        )
    ):
        raise RendererConformanceError(
            "case.inputs.matrix_key: mixed case must independently exercise all four attribute-source precedence branches"
        )


def _palette_upload(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON | {"palette_kind", "payload"},
    )
    kind = _str(inputs["palette_kind"], path="case.inputs.palette_kind")
    _require_writer(inputs)
    if kind not in {"BG", "OBJ"}:
        raise RendererConformanceError("case.inputs.palette_kind: expected BG or OBJ")
    payload = _hex(inputs["payload"], path="case.inputs.payload", length=64)
    _, owner, generation, _ = _common(inputs)
    job = TraceJobPredicate(
        f"JOB-{case.case_id}",
        owner,
        generation,
        (JobState.PREPARED, JobState.COMMITTING, JobState.COMPLETE),
        None,
        False,
    )
    return OracleExpectation(
        case.case_id,
        case.checks,
        (ResourcePatch("bg_palettes" if kind == "BG" else "obj_palettes", 0, payload),),
        (),
        _trace(
            inputs,
            jobs=(job,),
            no_writes=False,
            resources=("bg_palettes" if kind == "BG" else "obj_palettes",),
        ),
        None,
    )


def _oam_fallback(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON
        | {
            "final_picture_identity",
            "final_tile_id",
            "object_id",
            "attribute_offset",
            "attribute_before",
        },
    )
    _require_writer(inputs)
    mapped = case.mapped_picture_identities
    if not mapped:
        raise RendererConformanceError(
            "case: OAM fallback requires corpus authoritative mapped-picture identities"
        )
    identity = inputs["final_picture_identity"]
    if identity is None:
        kind = OAMFallbackKind.MISSING_IDENTITY
    elif isinstance(identity, bool) or not isinstance(identity, int) or identity < 0:
        raise RendererConformanceError(
            "case.inputs.final_picture_identity: expected a non-negative integer"
        )
    elif identity > 255:
        kind = OAMFallbackKind.OUT_OF_RANGE_IDENTITY
    elif identity not in mapped:
        kind = OAMFallbackKind.UNMAPPED_IDENTITY
    else:
        raise RendererConformanceError(
            "case.inputs.final_picture_identity: mapped identity cannot claim fallback"
        )
    tile = _int(inputs["final_tile_id"], path="case.inputs.final_tile_id", maximum=255)
    object_id = _str(inputs["object_id"], path="case.inputs.object_id")
    offset = _int(
        inputs["attribute_offset"], path="case.inputs.attribute_offset", maximum=159
    )
    if offset % 4 != 3:
        raise RendererConformanceError(
            "case.inputs.attribute_offset: expected an OAM attribute-byte offset"
        )
    before = _int(
        inputs["attribute_before"], path="case.inputs.attribute_before", maximum=255
    )
    writers, _, generation, _ = _common(inputs)
    after = before & 0xF8
    return OracleExpectation(
        case.case_id,
        case.checks,
        (ResourcePatch("shadow_oam", offset, bytes((before & 0xF8,))),),
        (
            ("oam_fallback.occurred", True),
            ("oam_fallback.fallback_kind", kind.value),
            ("oam_fallback.identity", identity),
            ("oam_fallback.final_tile_id", tile),
            ("oam_fallback.object_id", object_id),
            ("oam_fallback.generation", generation),
            ("oam_fallback.writer_id", writers[0]),
            ("oam_fallback.palette", 0),
            ("oam_fallback.before_attributes", before),
            ("oam_fallback.after_attributes", after),
        ),
        _trace(
            inputs,
            complete=False,
            no_writes=False,
            allow_unbound_observations=True,
        ),
        None,
    )


def _reconstruction(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON | {"prior_resource_state", "action"},
    )
    _require_writer(inputs)
    prior = _str(
        inputs["prior_resource_state"], path="case.inputs.prior_resource_state"
    )
    action = _str(inputs["action"], path="case.inputs.action")
    if prior != "POISONED_UNKNOWN" or action != "RECONSTRUCT_AND_PRESENT":
        raise RendererConformanceError(
            "case.inputs: reconstruction requires poisoned unknown initial resources and reconstruct-and-present action"
        )
    required = tuple(sorted(REQUIRED_RECONSTRUCTION_ITEMS))
    provenance = {item: RECONSTRUCTION_ITEM_PROVENANCE[item].value for item in required}
    _, owner, generation, _ = _common(inputs)
    job = TraceJobPredicate(
        f"JOB-{case.case_id}",
        owner,
        generation,
        (JobState.PREPARED, JobState.COMMITTING, JobState.COMPLETE),
        None,
        False,
    )
    return OracleExpectation(
        case.case_id,
        case.checks,
        (),
        (
            ("reconstruction.required_items", list(required)),
            ("reconstruction.completed_items", list(required)),
            ("reconstruction.poisoned_items", list(required)),
            ("reconstruction.item_provenance", provenance),
            ("reconstruction.unknown_prior_state", True),
            ("reconstruction.presentation_barrier_count", 1),
        ),
        _trace(
            inputs,
            jobs=(job,),
            no_writes=False,
            resources=("reconstructed_scene",),
        ),
        None,
    )


def _ownership_job(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON
        | {
            "old_job_id",
            "replacement_job_id",
            "previous_generation",
            "action",
        },
    )
    _require_writer(inputs)
    _, current_owner, current_generation, commit = _common(inputs)
    previous_generation = _int(
        inputs["previous_generation"], path="case.inputs.previous_generation"
    )
    if previous_generation >= current_generation:
        raise RendererConformanceError(
            "case.inputs.previous_generation: expected an older generation"
        )
    if (
        _str(inputs["action"], path="case.inputs.action")
        != "SUPERSEDE_WITH_REPLACEMENT"
    ):
        raise RendererConformanceError(
            "case.inputs.action: expected SUPERSEDE_WITH_REPLACEMENT"
        )
    old_id = _str(inputs["old_job_id"], path="case.inputs.old_job_id")
    replacement_id = _str(
        inputs["replacement_job_id"], path="case.inputs.replacement_job_id"
    )
    if old_id == replacement_id:
        raise RendererConformanceError(
            "case.inputs: old and replacement job IDs must differ"
        )
    if commit is None:
        raise RendererConformanceError(
            "case.inputs.commit_unit_id: replacement commit requires a unit ID"
        )
    jobs = (
        TraceJobPredicate(
            old_id,
            current_owner,
            previous_generation,
            (JobState.PENDING, JobState.PREPARED, JobState.CANCELLED),
            CancellationReason.SUPERSEDED,
            True,
        ),
        TraceJobPredicate(
            replacement_id,
            current_owner,
            current_generation,
            (
                JobState.PENDING,
                JobState.PREPARED,
                JobState.COMMITTING,
                JobState.COMPLETE,
            ),
            None,
            False,
        ),
    )
    return OracleExpectation(
        case.case_id,
        case.checks,
        (),
        (("owner", current_owner.value), ("generation", current_generation)),
        _trace(
            inputs,
            jobs=jobs,
            no_writes=False,
            resources=("ownership_generation",),
        ),
        None,
    )


def _machine_restore(case: ConformanceCase) -> OracleExpectation:
    inputs = _obj(
        case.inputs,
        path="case.inputs",
        required=_COMMON | {"event", "entry_banks"},
    )
    _require_writer(inputs)
    event = _str(inputs["event"], path="case.inputs.event")
    if event not in {
        "FAR_CALL_INTERRUPT",
        "SOFT_RESET_PENDING",
        "OWNERSHIP_SWITCH_PENDING",
    }:
        raise RendererConformanceError("case.inputs.event: unknown bank-torture event")
    banks = _obj(
        inputs["entry_banks"],
        path="case.inputs.entry_banks",
        required={"rom", "wram", "vram"},
    )
    entry = (
        _int(banks["rom"], path="case.inputs.entry_banks.rom", maximum=0x1FF),
        _int(banks["wram"], path="case.inputs.entry_banks.wram", maximum=7),
        _int(banks["vram"], path="case.inputs.entry_banks.vram", maximum=1),
    )
    interrupt = event == "FAR_CALL_INTERRUPT"
    predicate = MachineStatePredicate(True, True, True, True, True, True, interrupt)
    return OracleExpectation(
        case.case_id,
        case.checks,
        (),
        (
            ("case.event", event),
            ("case.entry_banks", {"rom": entry[0], "wram": entry[1], "vram": entry[2]}),
        ),
        _trace(
            inputs,
            complete=False,
            no_writes=False,
            allow_unbound_observations=True,
        ),
        predicate,
    )
