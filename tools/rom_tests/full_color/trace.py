"""Bounded writer-trace schema and externally mapped ROM-ring decoder."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import struct
from types import MappingProxyType
from typing import Any, Iterable, Mapping, TypeVar

from ._validation import require_enum, require_int, require_object, require_str
from .enums import CancellationReason, JobState, Owner, Phase
from .errors import TraceDecodeError

TRACE_SCHEMA = "full-color-writer-trace-v1"
TRACE_MAGIC = b"FCTR"
TRACE_LAYOUT_VERSION = 2
_HEADER = struct.Struct("<4sBHHH")
_RECORD = struct.Struct("<IIIIBBBBBHHHHHH")
MAX_TRACE_CAPACITY = 256

E = TypeVar("E")


def _freeze_map(
    raw: Mapping[int, E], *, name: str, maximum: int
) -> Mapping[int, E]:
    copied = dict(raw)
    if any(
        isinstance(key, bool)
        or not isinstance(key, int)
        or not 0 <= key <= maximum
        for key in copied
    ):
        raise TraceDecodeError(
            f"trace symbols.{name}: codes must be integers in 0..{maximum}"
        )
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class TraceSymbols:
    """Numeric debug-ROM encodings; values are not normative contract enums."""

    owners: Mapping[int, Owner]
    phases: Mapping[int, Phase]
    job_states: Mapping[int, JobState]
    cancellations: Mapping[int, CancellationReason | None]
    writer_ids: Mapping[int, str]
    commit_unit_ids: Mapping[int, str | None]
    job_ids: Mapping[int, str]
    request_ids: Mapping[int, str]
    resource_identities: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owners", _freeze_map(self.owners, name="owners", maximum=0xFF)
        )
        object.__setattr__(
            self, "phases", _freeze_map(self.phases, name="phases", maximum=0xFF)
        )
        object.__setattr__(
            self,
            "job_states",
            _freeze_map(self.job_states, name="job_states", maximum=0xFF),
        )
        object.__setattr__(
            self,
            "cancellations",
            _freeze_map(self.cancellations, name="cancellations", maximum=0xFF),
        )
        object.__setattr__(
            self,
            "writer_ids",
            _freeze_map(self.writer_ids, name="writer_ids", maximum=0xFFFF),
        )
        object.__setattr__(
            self,
            "commit_unit_ids",
            _freeze_map(
                self.commit_unit_ids, name="commit_unit_ids", maximum=0xFFFF
            ),
        )
        object.__setattr__(
            self,
            "job_ids",
            _freeze_map(self.job_ids, name="job_ids", maximum=0xFFFF),
        )
        object.__setattr__(
            self,
            "request_ids",
            _freeze_map(self.request_ids, name="request_ids", maximum=0xFFFF),
        )
        object.__setattr__(
            self,
            "resource_identities",
            _freeze_map(
                self.resource_identities,
                name="resource_identities",
                maximum=0xFFFF,
            ),
        )
        if any(
            not isinstance(name, str) or not name
            for name in self.resource_identities.values()
        ):
            raise TraceDecodeError(
                "trace symbols.resource_identities: expected stable non-empty canonical names"
            )
        if len(set(self.resource_identities.values())) != len(
            self.resource_identities
        ):
            raise TraceDecodeError(
                "trace symbols.resource_identities: canonical names must be unique"
            )


@dataclass(frozen=True, slots=True)
class WriterTraceEntry:
    sequence: int
    frame: int
    generation: int
    job_generation: int
    owner: Owner
    phase: Phase
    job_owner: Owner
    job_state: JobState
    cancellation_reason: CancellationReason | None
    writer_id: str
    commit_unit_id: str | None
    job_id: str
    request_id: str
    resource_id: int
    wrote: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("writer_id", self.writer_id),
            ("job_id", self.job_id),
            ("request_id", self.request_id),
        ):
            if not isinstance(value, str) or not value:
                raise TraceDecodeError(
                    f"trace entry {self.sequence}: {name} must be a stable non-empty ID"
                )
        if self.job_state is JobState.CANCELLED and self.cancellation_reason is None:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: CANCELLED requires exactly one reason"
            )
        if self.job_state is not JobState.CANCELLED and self.cancellation_reason is not None:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: only CANCELLED may carry a cancellation reason"
            )
        if self.job_state is JobState.CANCELLED and self.wrote:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: cancelled work reports a later write"
            )
        if self.wrote and self.job_state in {JobState.PENDING, JobState.PREPARED}:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: {self.job_state.value} work reports a visible write"
            )
        if self.wrote and self.job_state is not JobState.COMMITTING:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: visible write requires COMMITTING"
            )
        if self.wrote and not self.commit_unit_id:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: visible write requires a concrete "
                "commit_unit_id"
            )
        if self.wrote and self.owner is not self.job_owner:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: wrong owner write "
                f"{self.owner.value} for job owned by {self.job_owner.value}"
            )
        if self.wrote and self.generation != self.job_generation:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: stale job generation "
                f"{self.job_generation}; active generation is {self.generation}"
            )
        allowed = {
            Phase.YELLOW_ACTIVE: {Owner.RENDERER_YELLOW},
            Phase.HANDOFF_TO_OVERWORLD: set(Owner),
            Phase.OVERWORLD_RECONSTRUCTING: {
                Owner.RENDERER_FULL_COLOR_OVERWORLD
            },
            Phase.OVERWORLD_ACTIVE: {Owner.RENDERER_FULL_COLOR_OVERWORLD},
            Phase.OVERWORLD_OVERLAY: {Owner.RENDERER_FULL_COLOR_OVERWORLD},
            Phase.HANDOFF_TO_YELLOW: set(Owner),
        }
        if self.owner not in allowed[self.phase]:
            raise TraceDecodeError(
                f"trace entry {self.sequence}: invalid owner/phase pair "
                f"{self.owner.value}/{self.phase.value}"
            )

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> WriterTraceEntry:
        obj = require_object(
            raw,
            path=path,
            required={
                "sequence", "frame", "generation", "job_generation", "owner",
                "phase", "job_owner", "job_state",
                "cancellation_reason", "writer_id", "commit_unit_id", "resource_id",
                "job_id", "request_id", "wrote",
            },
            error=TraceDecodeError,
        )
        reason_raw = obj["cancellation_reason"]
        reason = (
            None
            if reason_raw is None
            else require_enum(
                CancellationReason,
                reason_raw,
                path=f"{path}.cancellation_reason",
                error=TraceDecodeError,
            )
        )
        commit_raw = obj["commit_unit_id"]
        commit = (
            None
            if commit_raw is None
            else require_str(commit_raw, path=f"{path}.commit_unit_id", error=TraceDecodeError)
        )
        wrote = obj["wrote"]
        if not isinstance(wrote, bool):
            raise TraceDecodeError(f"{path}.wrote: expected a boolean")
        return cls(
            sequence=require_int(obj["sequence"], path=f"{path}.sequence", error=TraceDecodeError),
            frame=require_int(obj["frame"], path=f"{path}.frame", error=TraceDecodeError),
            generation=require_int(
                obj["generation"], path=f"{path}.generation", error=TraceDecodeError
            ),
            job_generation=require_int(
                obj["job_generation"],
                path=f"{path}.job_generation",
                error=TraceDecodeError,
            ),
            owner=require_enum(Owner, obj["owner"], path=f"{path}.owner", error=TraceDecodeError),
            phase=require_enum(Phase, obj["phase"], path=f"{path}.phase", error=TraceDecodeError),
            job_owner=require_enum(
                Owner, obj["job_owner"], path=f"{path}.job_owner", error=TraceDecodeError
            ),
            job_state=require_enum(
                JobState, obj["job_state"], path=f"{path}.job_state", error=TraceDecodeError
            ),
            cancellation_reason=reason,
            writer_id=require_str(
                obj["writer_id"], path=f"{path}.writer_id", error=TraceDecodeError
            ),
            commit_unit_id=commit,
            job_id=require_str(obj["job_id"], path=f"{path}.job_id", error=TraceDecodeError),
            request_id=require_str(
                obj["request_id"], path=f"{path}.request_id", error=TraceDecodeError
            ),
            resource_id=require_int(
                obj["resource_id"], path=f"{path}.resource_id", maximum=0xFFFF,
                error=TraceDecodeError,
            ),
            wrote=wrote,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "frame": self.frame,
            "generation": self.generation,
            "job_generation": self.job_generation,
            "owner": self.owner.value,
            "phase": self.phase.value,
            "job_owner": self.job_owner.value,
            "job_state": self.job_state.value,
            "cancellation_reason": (
                None if self.cancellation_reason is None else self.cancellation_reason.value
            ),
            "writer_id": self.writer_id,
            "commit_unit_id": self.commit_unit_id,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "wrote": self.wrote,
        }


@dataclass(frozen=True, slots=True)
class WriterTrace:
    capacity: int
    entries: tuple[WriterTraceEntry, ...]
    permitted_writer_ids: tuple[str, ...]
    resource_identities: Mapping[int, str] = field(default_factory=dict)
    schema: str = TRACE_SCHEMA

    def __post_init__(self) -> None:
        if not 1 <= self.capacity <= MAX_TRACE_CAPACITY:
            raise TraceDecodeError(
                f"trace.capacity: expected 1..{MAX_TRACE_CAPACITY}, got {self.capacity}"
            )
        if len(self.entries) > self.capacity:
            raise TraceDecodeError(
                f"trace.entries: {len(self.entries)} entries exceed capacity {self.capacity}"
            )
        sequences = [entry.sequence for entry in self.entries]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise TraceDecodeError("trace.entries: sequence numbers must be unique and increasing")
        if not self.permitted_writer_ids:
            raise TraceDecodeError("trace.permitted_writer_ids: expected at least one writer ID")
        if any(
            not isinstance(writer_id, str) or not writer_id
            for writer_id in self.permitted_writer_ids
        ):
            raise TraceDecodeError(
                "trace.permitted_writer_ids: expected stable non-empty writer IDs"
            )
        object.__setattr__(
            self,
            "resource_identities",
            _freeze_map(
                self.resource_identities,
                name="resource_identities",
                maximum=0xFFFF,
            ),
        )
        if any(
            not isinstance(name, str) or not name
            for name in self.resource_identities.values()
        ):
            raise TraceDecodeError(
                "trace.resource_identities: expected stable non-empty canonical names"
            )
        if len(set(self.resource_identities.values())) != len(
            self.resource_identities
        ):
            raise TraceDecodeError(
                "trace.resource_identities: canonical names must be unique"
            )
        if len(set(self.permitted_writer_ids)) != len(self.permitted_writer_ids):
            raise TraceDecodeError("trace.permitted_writer_ids: duplicate writer ID")
        permitted = set(self.permitted_writer_ids)
        jobs: dict[str, WriterTraceEntry] = {}
        prior_states: dict[str, JobState] = {}
        for entry in self.entries:
            if entry.wrote and entry.writer_id not in permitted:
                raise TraceDecodeError(
                    f"trace entry {entry.sequence}: unexpected hardware writer "
                    f"{entry.writer_id}"
                )
            admitted = jobs.setdefault(entry.job_id, entry)
            if entry.job_owner is not admitted.job_owner:
                raise TraceDecodeError(
                    f"trace entry {entry.sequence}: job {entry.job_id} changed owner"
                )
            if entry.job_generation != admitted.job_generation:
                raise TraceDecodeError(
                    f"trace entry {entry.sequence}: job {entry.job_id} changed generation"
                )
            prior = prior_states.get(entry.job_id)
            if prior is not None and entry.job_state is not prior:
                if prior is JobState.CANCELLED and entry.wrote:
                    raise TraceDecodeError(
                        f"trace entry {entry.sequence}: job {entry.job_id} "
                        "reports a write after cancellation"
                    )
                allowed = {
                    JobState.PENDING: {JobState.PREPARED, JobState.CANCELLED},
                    JobState.PREPARED: {JobState.COMMITTING, JobState.CANCELLED},
                    JobState.COMMITTING: {JobState.COMPLETE},
                    JobState.COMPLETE: set(),
                    JobState.CANCELLED: set(),
                }
                if entry.job_state not in allowed[prior]:
                    raise TraceDecodeError(
                        f"trace entry {entry.sequence}: illegal transition for "
                        f"{entry.job_id}: {prior.value} -> {entry.job_state.value}"
                    )
            prior_states[entry.job_id] = entry.job_state

    @classmethod
    def from_dict(cls, raw: object) -> WriterTrace:
        obj = require_object(
            raw,
            path="trace",
            required={"schema", "capacity", "permitted_writer_ids", "entries"},
            optional={"resource_identities"},
            error=TraceDecodeError,
        )
        if obj["schema"] != TRACE_SCHEMA:
            raise TraceDecodeError(
                f"trace.schema: unsupported schema {obj['schema']!r}; expected {TRACE_SCHEMA!r}"
            )
        capacity = require_int(
            obj["capacity"],
            path="trace.capacity",
            minimum=1,
            maximum=MAX_TRACE_CAPACITY,
            error=TraceDecodeError,
        )
        entries_raw = obj["entries"]
        if not isinstance(entries_raw, list):
            raise TraceDecodeError("trace.entries: expected an array")
        if len(entries_raw) > capacity:
            raise TraceDecodeError(
                f"trace.entries: {len(entries_raw)} entries exceed capacity {capacity}"
            )
        permitted_raw = obj["permitted_writer_ids"]
        if not isinstance(permitted_raw, list):
            raise TraceDecodeError("trace.permitted_writer_ids: expected an array")
        identities_raw = obj.get("resource_identities", {})
        if not isinstance(identities_raw, dict):
            raise TraceDecodeError("trace.resource_identities: expected an object")
        resource_identities: dict[int, str] = {}
        for raw_id, raw_name in identities_raw.items():
            try:
                resource_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise TraceDecodeError(
                    "trace.resource_identities: keys must be integer strings"
                ) from exc
            if str(resource_id) != raw_id:
                raise TraceDecodeError(
                    "trace.resource_identities: keys must use canonical decimal form"
                )
            resource_identities[resource_id] = require_str(
                raw_name,
                path=f"trace.resource_identities.{raw_id}",
                error=TraceDecodeError,
            )
        return cls(
            capacity=capacity,
            permitted_writer_ids=tuple(
                require_str(
                    value,
                    path=f"trace.permitted_writer_ids[{index}]",
                    error=TraceDecodeError,
                )
                for index, value in enumerate(permitted_raw)
            ),
            entries=tuple(
                WriterTraceEntry.from_dict(entry, path=f"trace.entries[{index}]")
                for index, entry in enumerate(entries_raw)
            ),
            resource_identities=resource_identities,
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> WriterTrace:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TraceDecodeError(f"trace: invalid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capacity": self.capacity,
            "permitted_writer_ids": list(self.permitted_writer_ids),
            "resource_identities": {
                str(resource_id): name
                for resource_id, name in sorted(self.resource_identities.items())
            },
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def decode_writer_ring(
    raw: bytes,
    symbols: TraceSymbols,
    *,
    permitted_writer_ids: Iterable[str],
) -> WriterTrace:
    """Decode a synthetic/debug ROM ring without assigning stable numeric enums.

    The expected writer allowlist is supplied independently; the ROM symbol
    table cannot authorize an unexpected writer merely by naming it.

    Layout v2 is ``header(magic, version, capacity, count, next_write)`` followed
    by all physical ring slots. Count and next-write index are bounded by
    capacity, allowing chronological decoding after wraparound. A record is
    ``sequence, frame, active-generation, job-generation, owner, phase,
    job-owner, state, cancellation, writer, commit-unit, resource, job-id,
    request-id, flags``. Bit 0 of flags is the write marker.
    """
    if len(raw) < _HEADER.size:
        raise TraceDecodeError("trace ring: truncated header")
    magic, version, capacity, count, next_write = _HEADER.unpack_from(raw)
    if magic != TRACE_MAGIC:
        raise TraceDecodeError(f"trace ring: bad magic {magic!r}")
    if version != TRACE_LAYOUT_VERSION:
        raise TraceDecodeError(f"trace ring: unsupported layout version {version}")
    if not 1 <= capacity <= MAX_TRACE_CAPACITY:
        raise TraceDecodeError(
            f"trace ring: capacity {capacity} outside 1..{MAX_TRACE_CAPACITY}"
        )
    if count > capacity:
        raise TraceDecodeError(f"trace ring: count {count} exceeds capacity {capacity}")
    if next_write >= capacity:
        raise TraceDecodeError(
            f"trace ring: next-write index {next_write} exceeds capacity {capacity}"
        )
    expected_size = _HEADER.size + capacity * _RECORD.size
    if len(raw) != expected_size:
        raise TraceDecodeError(
            f"trace ring: expected exactly {expected_size} bytes, got {len(raw)}"
        )
    decoded: list[WriterTraceEntry] = []
    first = (next_write - count) % capacity
    active_slots = tuple((first + index) % capacity for index in range(count))
    for slot in range(capacity):
        values = _RECORD.unpack_from(raw, _HEADER.size + slot * _RECORD.size)
        if slot not in active_slots:
            if any(values):
                raise TraceDecodeError(f"trace ring: unused slot {slot} is not zero-filled")
    for slot in active_slots:
        values = _RECORD.unpack_from(raw, _HEADER.size + slot * _RECORD.size)
        (
            sequence, frame, generation, job_generation, owner, phase,
            job_owner, job, cancel, writer, commit, resource, job_code,
            request_code, flags,
        ) = values
        if flags & ~1:
            raise TraceDecodeError(f"trace ring slot {slot}: unknown flags 0x{flags:04x}")
        decoded.append(
            WriterTraceEntry(
                sequence=sequence,
                frame=frame,
                generation=generation,
                job_generation=job_generation,
                owner=_lookup(symbols.owners, owner, slot, "owner"),
                phase=_lookup(symbols.phases, phase, slot, "phase"),
                job_owner=_lookup(symbols.owners, job_owner, slot, "job owner"),
                job_state=_lookup(symbols.job_states, job, slot, "job state"),
                cancellation_reason=_lookup(
                    symbols.cancellations, cancel, slot, "cancellation"
                ),
                writer_id=_lookup(symbols.writer_ids, writer, slot, "writer"),
                commit_unit_id=_lookup(
                    symbols.commit_unit_ids, commit, slot, "commit unit"
                ),
                job_id=_lookup(symbols.job_ids, job_code, slot, "job"),
                request_id=_lookup(symbols.request_ids, request_code, slot, "request"),
                resource_id=resource,
                wrote=bool(flags & 1),
            )
        )
    return WriterTrace(
        capacity=capacity,
        entries=tuple(decoded),
        permitted_writer_ids=tuple(permitted_writer_ids),
        resource_identities=symbols.resource_identities,
    )


def _lookup(table: Mapping[int, E], code: int, slot: int, field: str) -> E:
    try:
        return table[code]
    except KeyError as exc:
        raise TraceDecodeError(
            f"trace ring slot {slot}: unknown {field} code {code}"
        ) from exc


def encode_synthetic_ring(
    *,
    capacity: int,
    records: tuple[tuple[int, ...], ...],
) -> bytes:
    """Test-fixture helper encoding raw numeric records under layout v2."""
    if not 1 <= capacity <= MAX_TRACE_CAPACITY:
        raise TraceDecodeError(f"synthetic trace: invalid capacity {capacity}")
    if len(records) > capacity:
        raise TraceDecodeError("synthetic trace: records exceed capacity")
    slots = list(records) + [(0,) * 15] * (capacity - len(records))
    next_write = len(records) % capacity
    try:
        return _HEADER.pack(
            TRACE_MAGIC, TRACE_LAYOUT_VERSION, capacity, len(records), next_write
        ) + b"".join(_RECORD.pack(*record) for record in slots)
    except struct.error as exc:
        raise TraceDecodeError(f"synthetic trace: malformed record: {exc}") from exc
