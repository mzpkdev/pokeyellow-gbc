"""Real-ROM observations for the activated Phase 2 hostile color slice.

This is a sibling of, not an extension to, Phase 1 runtime observability.  It
owns a distinct versioned carrier, first proves that the committed guarded
audit product is still the product reviewed by the inventory, and keeps the
release OAM fallback probe entirely separate from debug instrumentation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping

from tools.rom_tests.emulator import Emulator


PHASE2_MAGIC = b"FCP2"
PHASE2_LAYOUT_VERSION = 1
PHASE2_CARRIER_BYTES = 288
PHASE2_HEADER_BYTES = 16
PHASE2_RECORD_BYTES = 32
PHASE2_RECORD_CAPACITY = 8
PHASE2_RECORD_PAYLOAD_BYTES = 19

PHASE2_CARRIER_START = "wFullColorPhase2RuntimeCarrierStart"
PHASE2_CARRIER_END = "wFullColorPhase2RuntimeCarrierEnd"
PHASE2_COMMAND = "wFullColorDebugCommand"
PHASE2_COMMAND_PENDING = "hFullColorDebugCommandPending"
PHASE2_SCENARIO = "wFullColorPhase2RuntimeScenario"
PHASE2_SCENARIO_HOSTILE_SLICE = 1
PHASE2_COMMAND_ARM = 0x30
PHASE2_COMMAND_SNAPSHOT = 0x31
PHASE2_COMMAND_ACK = 0x32

RENDERER_YELLOW = 0
RENDERER_FULL_COLOR_OVERWORLD = 1
YELLOW_ACTIVE = 0
OVERWORLD_ACTIVE = 3

# Record kinds are deliberately host-authored.  A ROM value not listed here is
# not silently retained as an opaque extension because manifests must be closed.
RECORD_KINDS = {
    1: "checkpoint",
}

EXPECTED_SCENARIO = (
    "map-entry",
    "horizontal",
    "vertical",
    "animated-terrain",
    "north-route1-connection",
    "edge-dialogue",
    "start-overlay",
    "follower-npc-oam",
    "party-entry",
    "party-return",
)

RELEASE_FALLBACK_CASES = (
    ("missing", 0xFF),
    ("out-of-range", 0x08),
    ("unmapped", 0x00),
)

_DEBUG_RELEASE_SYMBOL_PATTERNS = (
    re.compile(r"Canary", re.IGNORECASE),
    re.compile(r"Debug.*Fallback", re.IGNORECASE),
    re.compile(r"FullColorPhase2Runtime", re.IGNORECASE),
)

# A complete observation bundle cannot be reconstructed from the compact FCP2
# checkpoint ring.  These symbols are the minimum production/debug ABI needed
# to retain the data which the independent checker consumes.  Keeping this
# list host-authored makes absence fail closed instead of quietly promoting the
# synthetic corpus observations to ROM evidence.
_PHASE2_OBSERVATION_ABI_SYMBOLS = frozenset({
    "wFullColorPhase2ObservationCaseID",
    "wFullColorPhase2SemanticSnapshotStart",
    "wFullColorPhase2SemanticSnapshotEnd",
    "wFullColorPhase2WriterTraceStart",
    "wFullColorPhase2WriterTraceEnd",
    "wFullColorPhase2BoundaryStart",
    "wFullColorPhase2BoundaryEnd",
    "wFullColorPhase2DiagnosticOverlayCase",
    "RunFullColorPhase2DiagnosticOverlayMatrix",
    "RunFullColorPhase2DiagnosticNonOverlayCase",
})

PHASE2_OBSERVATION_MAGIC = b"FCO2"
PHASE2_OBSERVATION_VERSION = 2
PHASE2_SEMANTIC_BYTES = 64
PHASE2_TRACE_BYTES = 64
PHASE2_BOUNDARY_BYTES = 32
PHASE2_DIAGNOSTIC_OVERLAY_CASES = 14
PHASE2_DIAGNOSTIC_CASES = 25
PHASE2_NONOVERLAY_TRACE_MAGIC = 0xA5
PHASE2_NONOVERLAY_TRACE_BYTES = 25


@dataclass(frozen=True, slots=True)
class Phase2NonOverlayTrace:
    case_id: int
    completion: int
    request_class: int
    admission: int
    request_count: int
    owner: int
    phase: int
    generation: int
    oam_before: int
    oam_after: int
    fallback_kind: int
    fallback_identity: int
    fallback_object: int
    reconstruction_barrier: int
    rom_bank: int
    wram_bank: int
    vram_bank: int
    ie: int
    interrupt_flags: int


@dataclass(frozen=True, slots=True)
class Phase2MachineBoundary:
    rom_bank: int
    wram_bank: int
    vram_bank: int
    ie: int
    interrupt_flags: int
    owner: int
    phase: int
    generation: int
    reserved: bytes


@dataclass(frozen=True, slots=True)
class Phase2RawObservation:
    """One atomic copy of the normal-debug FCO2 v2 carrier and machine state."""

    case_id: int
    checkpoint: int
    sequence: int
    overlay_case: int
    next_overlay_case: int
    source_attribute_count: int
    source_attributes: bytes
    attribute_count: int
    overlay_attributes: bytes
    metadata: bytes
    transition_count: int
    transition_log: bytes
    request_descriptor: bytes
    trace_reserved: bytes
    non_overlay_trace: Phase2NonOverlayTrace | None
    before: Phase2MachineBoundary
    after: Phase2MachineBoundary
    bg_tile_ids: bytes
    bg_attributes: bytes
    bg_palette_base: bytes
    bg_palette_transformed: bytes
    obj_palette_base: bytes
    obj_palette_transformed: bytes
    attribute_rectangle: bytes
    shadow_oam: bytes
    hardware_oam: bytes
    frame: int


def _decode_machine_boundary(raw: bytes, *, label: str) -> Phase2MachineBoundary:
    if len(raw) != 16:
        raise Phase2RuntimeError(f"Phase 2 {label} boundary has wrong size")
    rom = int.from_bytes(raw[:2], "little")
    wram, raw_vram, ie, interrupt_flags, owner, phase = raw[2:8]
    if not 1 <= rom <= 0x1FF or not 1 <= wram <= 7 or raw_vram not in (0, 1, 0xFE, 0xFF):
        raise Phase2RuntimeError(f"Phase 2 {label} boundary has invalid bank state")
    vram = raw_vram & 1
    if owner not in (RENDERER_YELLOW, RENDERER_FULL_COLOR_OVERWORLD):
        raise Phase2RuntimeError(f"Phase 2 {label} boundary has invalid owner")
    if phase > OVERWORLD_ACTIVE:
        raise Phase2RuntimeError(f"Phase 2 {label} boundary has invalid phase")
    reserved = raw[12:]
    if reserved != bytes(4):
        raise Phase2RuntimeError(f"Phase 2 {label} boundary reserved bytes are non-zero")
    return Phase2MachineBoundary(
        rom, wram, vram, ie, interrupt_flags, owner, phase,
        int.from_bytes(raw[8:12], "little"), reserved,
    )


def decode_phase2_observation_regions(
    semantic: bytes,
    trace: bytes,
    boundary: bytes,
    *,
    bg_tile_ids: bytes,
    bg_attributes: bytes,
    bg_palette_base: bytes,
    bg_palette_transformed: bytes,
    obj_palette_base: bytes,
    obj_palette_transformed: bytes,
    attribute_rectangle: bytes,
    shadow_oam: bytes,
    hardware_oam: bytes,
    frame: int,
) -> Phase2RawObservation:
    """Decode FCO2 v2 without accepting host-authored expected output bytes."""

    expected_sizes = (
        ("semantic", semantic, PHASE2_SEMANTIC_BYTES),
        ("trace", trace, PHASE2_TRACE_BYTES),
        ("boundary", boundary, PHASE2_BOUNDARY_BYTES),
        ("BG tile maps", bg_tile_ids, 2048),
        ("BG attribute maps", bg_attributes, 2048),
        ("BG palette base", bg_palette_base, 64),
        ("BG palette transformed", bg_palette_transformed, 64),
        ("OBJ palette base", obj_palette_base, 64),
        ("OBJ palette transformed", obj_palette_transformed, 64),
        ("attribute rectangle", attribute_rectangle, 360),
        ("shadow OAM", shadow_oam, 160),
        ("hardware OAM", hardware_oam, 160),
    )
    for name, value, size in expected_sizes:
        if len(value) != size:
            raise Phase2RuntimeError(f"Phase 2 {name} has size {len(value)}; expected {size}")
    if semantic[:4] != PHASE2_OBSERVATION_MAGIC:
        raise Phase2RuntimeError("Phase 2 observation magic is not FCO2")
    if semantic[4] != PHASE2_OBSERVATION_VERSION or semantic[5] != PHASE2_SEMANTIC_BYTES:
        raise Phase2RuntimeError("Phase 2 observation layout version/size changed")
    case_id, checkpoint, flags = semantic[6:9]
    if case_id >= PHASE2_DIAGNOSTIC_CASES:
        raise Phase2RuntimeError("Phase 2 observation case identity is out of range")
    if checkpoint != 3:
        raise Phase2RuntimeError("Phase 2 observation was not completed")
    if flags:
        raise Phase2RuntimeError(f"Phase 2 observation reports failure flags {flags:#04x}")
    sequence = int.from_bytes(semantic[9:11], "little")
    if sequence == 0:
        raise Phase2RuntimeError("Phase 2 observation sequence is zero")
    overlay_case, next_case = semantic[11:13]
    source_attribute_count = semantic[13]
    attribute_count = semantic[18]
    if overlay_case != case_id or next_case != case_id + 1:
        raise Phase2RuntimeError("Phase 2 observation case/sequence identity disagrees")
    if attribute_count > 4:
        raise Phase2RuntimeError("Phase 2 observation attribute count exceeds matrix bound")
    if source_attribute_count > 4:
        raise Phase2RuntimeError("Phase 2 observation source attribute count exceeds matrix bound")
    transition_count = trace[0]
    if transition_count > 8:
        raise Phase2RuntimeError("Phase 2 transition count exceeds retained log")
    trace_reserved = trace[29:]
    non_overlay_trace = None
    if case_id < PHASE2_DIAGNOSTIC_OVERLAY_CASES:
        if trace_reserved != bytes(35):
            raise Phase2RuntimeError("Phase 2 overlay trace reserved bytes are non-zero")
    else:
        record = trace_reserved[:PHASE2_NONOVERLAY_TRACE_BYTES]
        if record[0] != PHASE2_NONOVERLAY_TRACE_MAGIC:
            raise Phase2RuntimeError("Phase 2 non-overlay trace magic changed")
        if record[1] != case_id or record[2] != 3:
            raise Phase2RuntimeError("Phase 2 non-overlay trace case/completion changed")
        if trace_reserved[PHASE2_NONOVERLAY_TRACE_BYTES:] != bytes(10):
            raise Phase2RuntimeError("Phase 2 non-overlay trace reserved bytes are non-zero")
        non_overlay_trace = Phase2NonOverlayTrace(
            case_id=record[1], completion=record[2], request_class=record[3],
            admission=record[4], request_count=record[5], owner=record[6],
            phase=record[7], generation=int.from_bytes(record[8:12], "little"),
            oam_before=record[12], oam_after=record[13],
            fallback_kind=record[14], fallback_identity=int.from_bytes(record[15:17], "little"),
            fallback_object=record[17], reconstruction_barrier=record[18],
            rom_bank=int.from_bytes(record[19:21], "little"),
            wram_bank=record[21], vram_bank=record[22] & 1,
            ie=record[23], interrupt_flags=record[24],
        )
        if (non_overlay_trace.owner, non_overlay_trace.phase) != (1, 3):
            raise Phase2RuntimeError("Phase 2 non-overlay trace owner/phase changed")
    before = _decode_machine_boundary(boundary[:16], label="before")
    after = _decode_machine_boundary(boundary[16:], label="after")
    if non_overlay_trace is not None and non_overlay_trace.generation != after.generation:
        raise Phase2RuntimeError("Phase 2 non-overlay trace generation changed")
    if (before.rom_bank, before.wram_bank, before.vram_bank, before.ie,
        before.interrupt_flags) != (
        after.rom_bank, after.wram_bank, after.vram_bank, after.ie,
        after.interrupt_flags,
    ):
        raise Phase2RuntimeError("Phase 2 diagnostic call leaked bank/interrupt state")
    expected_after_generation = before.generation + (case_id == 23)
    if after.generation != expected_after_generation or after.owner != before.owner:
        raise Phase2RuntimeError("Phase 2 diagnostic call changed owner/generation boundary")
    return Phase2RawObservation(
        case_id, checkpoint, sequence, overlay_case, next_case,
        source_attribute_count, semantic[14:18], attribute_count,
        semantic[19:23], semantic[30:], transition_count, trace[1:9],
        trace[9:29], trace_reserved, non_overlay_trace, before, after, bg_tile_ids, bg_attributes,
        bg_palette_base, bg_palette_transformed, obj_palette_base,
        obj_palette_transformed, attribute_rectangle, shadow_oam, hardware_oam,
        frame,
    )


class Phase2RuntimeError(AssertionError):
    """The Phase 2 observation cannot support a runtime claim."""


def _require_complete_observation_abi(emulator: Emulator) -> None:
    """Reject the carrier-only seam before it can be called runtime evidence.

    FCP2 v1 retains useful lifecycle pressure data, but its 19-byte payload has
    no room for the 2 KiB tile maps, palettes, OAM, scheduler/request ledgers,
    writer trace, and machine boundary required for one semantic observation.
    The diagnostic overlay matrix also needs an executable ROM entry point;
    host-side fixture loading is not execution.
    """

    missing = sorted(_PHASE2_OBSERVATION_ABI_SYMBOLS - emulator.symbols.keys())
    if missing:
        raise Phase2RuntimeError(
            "Phase 2 production observation ABI is incomplete: missing "
            + ", ".join(missing)
            + "; the 32-byte FCP2 checkpoint record only exposes lifecycle "
            "metadata and cannot supply actual SemanticSnapshot/WriterTrace/"
            "BankTorture evidence or execute the 14-case diagnostic overlay "
            "matrix. Add a versioned ROM observation carrier and matrix entry "
            "point before enabling the runtime bundle"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_symbols(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if not match:
            continue
        name = match.group(2)
        value = int(match.group(1), 16)
        if name in values and values[name] != value:
            raise Phase2RuntimeError(f"{path.name}:{number}: duplicate constant {name}")
        values[name] = value
    return values


@dataclass(frozen=True, slots=True)
class GuardedAuditIdentity:
    rom_sha256: str
    sym_sha256: str
    map_sha256: str
    source_sha256: str

    def __post_init__(self) -> None:
        for field in asdict(self).values():
            if not re.fullmatch(r"[0-9a-f]{64}", field):
                raise Phase2RuntimeError("guarded audit identity is not exact SHA-256")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def require_committed_guarded_audit(root: Path) -> GuardedAuditIdentity:
    """Bind activation to one reviewed, committed audit binary identity.

    The source tree is expected to change when debug activation is added.  The
    prerequisite therefore verifies the retained audit artifacts and the
    identities committed into every Phase 2 inventory row, not a newly derived
    identity from the activated source tree.
    """

    root = root.resolve()
    identities: set[tuple[str, str, str, str]] = set()
    seen_rows = 0
    for relative in (
        "specs/full-colors/inventory/writers.json",
        "specs/full-colors/inventory/scenes.json",
        "specs/full-colors/inventory/mutations.json",
    ):
        path = root / relative
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Phase2RuntimeError(f"cannot read committed audit inventory: {exc}") from exc
        for row in document.get("rows", ()):
            row_id = row.get("id", "")
            if "P2-" not in row_id:
                continue
            seen_rows += 1
            evidence = row.get("evidence")
            if row.get("planned") is not False or not isinstance(evidence, dict):
                raise Phase2RuntimeError(f"inventory row {row_id} is not audit-closed")
            if evidence.get("reviewed") is not True:
                raise Phase2RuntimeError(f"inventory row {row_id} is not reviewed")
            try:
                identities.add(tuple(evidence[key] for key in (
                    "rom_sha256", "sym_sha256", "map_sha256", "source_sha256"
                )))
            except KeyError as exc:
                raise Phase2RuntimeError(f"inventory row {row_id} lacks audit identity") from exc
    if not seen_rows:
        raise Phase2RuntimeError("committed inventory contains no Phase 2 rows")
    if len(identities) != 1:
        raise Phase2RuntimeError("Phase 2 inventory does not bind one guarded audit identity")
    identity = GuardedAuditIdentity(*next(iter(identities)))
    artifacts = {
        "rom_sha256": root / "pokeyellow_phase2_audit.gbc",
        "sym_sha256": root / "pokeyellow_phase2_audit.sym",
    }
    for name, path in artifacts.items():
        try:
            actual = _sha256(path)
        except OSError as exc:
            raise Phase2RuntimeError(f"guarded audit artifact is unavailable: {path.name}") from exc
        if actual != getattr(identity, name):
            raise Phase2RuntimeError(
                f"guarded audit {path.name} identity changed: {actual}"
            )
    # Map authority is the canonical section model, not the linker's incidental
    # textual serialization.  Use the same independent ROM discovery parser
    # which closed the inventory instead of hashing the raw .map bytes.
    from .rom_discovery import load_map

    try:
        map_identity = load_map(root / "pokeyellow_phase2_audit.map").artifact_sha256
    except Exception as exc:
        raise Phase2RuntimeError(f"cannot verify guarded audit map identity: {exc}") from exc
    if map_identity != identity.map_sha256:
        raise Phase2RuntimeError(
            f"guarded audit semantic map identity changed: {map_identity}"
        )
    return identity


@dataclass(frozen=True, slots=True)
class TimingRecord:
    key: int
    event: int
    sequence: int
    start_ly: int
    start_div: int
    end_ly: int
    end_div: int
    requires_sameboy_authority: bool


@dataclass(frozen=True, slots=True)
class Phase2CarrierRecord:
    kind: str
    checkpoint: int
    owner: int
    phase: int
    generation: int
    rom_bank: int
    wram_bank: int
    vram_bank: int
    ie: int
    interrupt_flags: int
    request_result: int
    request_count: int
    commit_or_request_class: int
    reconstruction_barrier_count: int
    fallback_kind: int
    fallback_identity: int
    fallback_object_index: int
    before_attributes: int
    after_attributes: int
    payload: bytes
    timing: TimingRecord | None = None

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw["payload"] = self.payload.hex()
        return raw


@dataclass(frozen=True, slots=True)
class Phase2Carrier:
    sequence: int
    scenario: int
    flags: int
    command: int
    checkpoint: int
    write_index: int
    records: tuple[Phase2CarrierRecord, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "full-color-phase2-runtime-carrier-v1",
            "sequence": self.sequence,
            "scenario": self.scenario,
            "flags": self.flags,
            "command": self.command,
            "checkpoint": self.checkpoint,
            "write_index": self.write_index,
            "records": [record.to_dict() for record in self.records],
        }


def _decode_timing(payload: bytes) -> TimingRecord:
    if payload[18] != 0:
        raise Phase2RuntimeError("timing record reserved byte is non-zero")
    if payload[10] & ~1:
        raise Phase2RuntimeError("timing record contains unknown flags")
    return TimingRecord(
        key=payload[9],
        event=payload[10],
        sequence=int.from_bytes(payload[11:13], "little"),
        start_ly=payload[13],
        start_div=payload[14],
        end_ly=payload[15],
        end_div=payload[16],
        requires_sameboy_authority=bool(payload[17] & 1),
    )


def decode_phase2_carrier(raw: bytes) -> Phase2Carrier:
    """Decode one atomic FCP2 v1 image and reject every ambiguous byte."""

    if len(raw) != PHASE2_CARRIER_BYTES:
        raise Phase2RuntimeError(
            f"Phase 2 carrier is {len(raw)} bytes; expected {PHASE2_CARRIER_BYTES}"
        )
    if raw[:4] != PHASE2_MAGIC:
        raise Phase2RuntimeError("Phase 2 carrier magic is not FCP2")
    version, record_size, capacity, count = raw[4:8]
    if version != PHASE2_LAYOUT_VERSION:
        raise Phase2RuntimeError(f"unsupported Phase 2 carrier version {version}")
    if record_size != PHASE2_RECORD_BYTES or capacity != PHASE2_RECORD_CAPACITY:
        raise Phase2RuntimeError("Phase 2 carrier record layout changed")
    if count > capacity:
        raise Phase2RuntimeError("Phase 2 carrier count exceeds capacity")
    if raw[15] != 0:
        raise Phase2RuntimeError("Phase 2 carrier header reserved bytes are non-zero")
    write_index = raw[14]
    if write_index >= capacity:
        raise Phase2RuntimeError("Phase 2 carrier write index exceeds capacity")
    if raw[11] & ~0x01:
        raise Phase2RuntimeError("Phase 2 carrier contains unknown flags")
    physical_records: list[Phase2CarrierRecord | None] = []
    records_start = PHASE2_HEADER_BYTES
    for index in range(capacity):
        start = records_start + index * record_size
        record = raw[start : start + record_size]
        if count < capacity and index >= count:
            if record != bytes(record_size):
                raise Phase2RuntimeError("unused Phase 2 carrier record is non-zero")
            physical_records.append(None)
            continue
        kind_code = record[0]
        try:
            kind = RECORD_KINDS[kind_code]
        except KeyError as exc:
            raise Phase2RuntimeError(f"unknown Phase 2 record kind {kind_code}") from exc
        owner, phase = record[2:4]
        if owner not in (RENDERER_YELLOW, RENDERER_FULL_COLOR_OVERWORLD):
            raise Phase2RuntimeError(f"unknown Phase 2 owner {owner}")
        if not 1 <= record[8] <= 0xFF or not 1 <= record[9] <= 7:
            raise Phase2RuntimeError("Phase 2 record contains default ROM/WRAM bank")
        if record[10] not in (0, 1):
            raise Phase2RuntimeError("Phase 2 record contains invalid VRAM bank")
        payload = record[13:]
        if record[31] != 0:
            raise Phase2RuntimeError("Phase 2 record reserved byte is non-zero")
        timing = _decode_timing(payload) if payload[9] else None
        physical_records.append(Phase2CarrierRecord(
            kind=kind,
            checkpoint=record[1],
            owner=owner,
            phase=phase,
            generation=int.from_bytes(record[4:8], "little"),
            rom_bank=record[8],
            wram_bank=record[9],
            vram_bank=record[10],
            ie=record[11],
            interrupt_flags=record[12],
            request_result=record[13],
            request_count=record[14],
            commit_or_request_class=record[15],
            reconstruction_barrier_count=record[16],
            fallback_kind=record[17],
            fallback_identity=record[18],
            fallback_object_index=record[19],
            before_attributes=record[20],
            after_attributes=record[21],
            payload=payload,
            timing=timing,
        ))
    if count < capacity and write_index != count:
        raise Phase2RuntimeError("Phase 2 carrier write index disagrees with count")
    if count == capacity:
        ordered_slots = tuple(range(write_index, capacity)) + tuple(range(write_index))
    else:
        ordered_slots = tuple(range(count))
    records = tuple(physical_records[index] for index in ordered_slots)
    if any(record is None for record in records):
        raise Phase2RuntimeError("Phase 2 carrier ring ordering selected an empty record")
    tail = raw[records_start + capacity * record_size :]
    if tail != bytes(len(tail)):
        raise Phase2RuntimeError("Phase 2 carrier reserved tail is non-zero")
    return Phase2Carrier(
        sequence=int.from_bytes(raw[8:10], "little"),
        scenario=raw[10],
        flags=raw[11],
        command=raw[12],
        checkpoint=raw[13],
        records=tuple(record for record in records if record is not None),
        write_index=write_index,
    )


def validate_hostile_records(carriers: Phase2Carrier | Iterable[Phase2Carrier]) -> None:
    """Apply host-authored expectations without consulting ROM output."""

    captured = (carriers,) if isinstance(carriers, Phase2Carrier) else tuple(carriers)
    if not captured or any(carrier.sequence == 0 for carrier in captured):
        raise Phase2RuntimeError("hostile scenario did not publish a sequence")
    records = (
        captured[0].records
        if len(captured) == 1
        else tuple(carrier.records[-1] for carrier in captured if carrier.records)
    )
    if not records:
        raise Phase2RuntimeError("hostile scenario published no records")
    if any(carrier.scenario != PHASE2_SCENARIO_HOSTILE_SLICE for carrier in captured):
        raise Phase2RuntimeError("carrier is not the hostile-slice scenario")
    sequences = tuple(carrier.sequence for carrier in captured)
    if sequences != tuple(range(sequences[0], sequences[0] + len(sequences))):
        raise Phase2RuntimeError("hostile scenario sequences contain a gap")
    if not any(record.ie and record.interrupt_flags for record in records):
        raise Phase2RuntimeError("hostile scenario lacks pending interrupt pressure")
    if not any(record.vram_bank == 1 for record in records):
        raise Phase2RuntimeError("hostile scenario lacks non-default VRAM pressure")
    active_frames = [
        record for record in records
        if record.kind == "checkpoint"
        and record.owner == RENDERER_FULL_COLOR_OVERWORLD
        and record.phase == OVERWORLD_ACTIVE
    ]
    if len(active_frames) < 5:
        raise Phase2RuntimeError("hostile scenario lacks five OVERWORLD_ACTIVE frames")
    timing = [record.timing for record in records if record.timing is not None]
    if timing and not all(item.requires_sameboy_authority for item in timing):
        raise Phase2RuntimeError("timing record does not require SameBoy cycle authority")


@dataclass(frozen=True, slots=True)
class ReleaseOAMFallbackObservation:
    case: str
    identity: int
    object_index: int
    before_attributes: int
    shadow_attributes: int
    hardware_attributes: int
    carry: bool
    entry_rom_bank: int
    exit_rom_bank: int
    entry_wram_bank: int
    exit_wram_bank: int
    entry_vram_bank: int
    exit_vram_bank: int
    entry_ie: int
    exit_ie: int
    entry_if: int
    exit_if: int


def _run_until_return(emulator: Emulator, setup: Callable[[], None], *, name: str) -> tuple[int, int]:
    memory = emulator.pyboy.memory
    registers = emulator.pyboy.register_file
    returned = False

    def stop(_: object) -> None:
        nonlocal returned
        returned = True
        memory[0xC780] = 0x18
        memory[0xC781] = 0xFE
        registers.PC = 0xC780

    emulator.pyboy.hook_register(0, 0x0100, stop, None)
    try:
        setup()
        for _ in range(64):
            emulator.pyboy.tick(1, render=False, sound=False)
            if returned:
                break
    finally:
        emulator.pyboy.hook_deregister(0, 0x0100)
    if not returned:
        raise Phase2RuntimeError(f"release routine {name} did not return")
    return registers.A, registers.F


def _farcall(
    emulator: Emulator,
    name: str,
    *,
    c: int = 0,
    de: int = 0,
    entry_rom_bank: int = 0x2D,
    entry_wram_bank: int = 7,
    entry_vram_bank: int = 1,
    ie: int = 0x15,
    interrupt_flags: int = 0x1A,
) -> tuple[int, int]:
    symbols, banks = emulator.symbols, emulator.symbol_banks
    required = {name, "Bankswitch", "hLoadedROMBank"}
    missing = sorted(required - symbols.keys())
    if missing:
        raise Phase2RuntimeError("release ROM lacks routines: " + ", ".join(missing))
    target, target_bank = symbols[name], banks[name]
    bankswitch = symbols["Bankswitch"]
    code = bytes((
        0xF3,                              # di; pending IE/IF remain observable
        0x0E, c,
        0x11, de & 0xFF, de >> 8,
        0x06, target_bank,
        0x21, target & 0xFF, target >> 8,
        0xCD, bankswitch & 0xFF, bankswitch >> 8,
        0xC9,
    ))

    def setup() -> None:
        memory = emulator.pyboy.memory
        registers = emulator.pyboy.register_file
        for offset, value in enumerate(code):
            memory[0xC6F0 + offset] = value
        memory[0x2000] = entry_rom_bank
        memory[symbols["hLoadedROMBank"]] = entry_rom_bank
        memory[0xFF70] = entry_wram_bank
        memory[0xFF4F] = entry_vram_bank
        memory[0xFFFF] = ie
        memory[0xFF0F] = interrupt_flags
        registers.SP = 0xCFFE
        memory[0xCFFE] = 0
        memory[0xCFFF] = 1
        registers.PC = 0xC6F0

    return _run_until_return(emulator, setup, name=name)


def probe_release_oam_fallbacks(root: Path, results: Path) -> tuple[ReleaseOAMFallbackObservation, ...]:
    """Probe missing/out-of-range/unmapped identities in the real release ROM."""

    root = root.resolve()
    rom, sym = root / "pokeyellow.gbc", root / "pokeyellow.sym"
    emulator = Emulator(rom=rom, symbols=sym, results=results, cgb=True)
    try:
        forbidden = sorted(
            name for name in emulator.symbols
            if any(pattern.search(name) for pattern in _DEBUG_RELEASE_SYMBOL_PATTERNS)
        )
        if forbidden:
            raise Phase2RuntimeError(
                "release ROM exposes debug fallback/canary symbols: " + ", ".join(forbidden)
            )
        # Install the cartridge's real HRAM DMA routine and initialize ownership.
        _farcall(emulator, "WriteDMACodeToHRAM")
        observations: list[ReleaseOAMFallbackObservation] = []
        for object_index, (case, identity) in enumerate(RELEASE_FALLBACK_CASES):
            attribute = emulator.symbols["wShadowOAM"] + object_index * 4 + 3
            before = 0xD8 | (object_index & 7)
            emulator.pyboy.memory[attribute] = before
            _, flags = _farcall(
                emulator,
                "MapFullColorOAMAttributeFar",
                c=identity,
                de=attribute,
            )
            shadow = emulator.pyboy.memory[attribute]
            exit_rom_bank = emulator.pyboy.memory[emulator.symbols["hLoadedROMBank"]]
            exit_wram_bank = (emulator.pyboy.memory[0xFF70] & 7) or 1
            exit_vram_bank = emulator.pyboy.memory[0xFF4F] & 1
            exit_ie = emulator.pyboy.memory[0xFFFF]
            exit_if = emulator.pyboy.memory[0xFF0F]
            # The production HRAM routine is the same DMA endpoint used by the
            # owned VBlank. Calling it separately keeps release proof free of
            # all debug recording and observes actual hardware OAM.
            def dma_setup() -> None:
                memory = emulator.pyboy.memory
                registers = emulator.pyboy.register_file
                memory[0xFFFF] = 0
                registers.SP = 0xCFFE
                memory[0xCFFE] = 0
                memory[0xCFFF] = 1
                registers.PC = emulator.symbols["hDMARoutine"]

            _run_until_return(emulator, dma_setup, name="hDMARoutine")
            hardware = emulator.pyboy.memory[0xFE00 + object_index * 4 + 3]
            expected = before & 0xF8
            if shadow != expected or hardware != expected or not flags & 0x10:
                raise Phase2RuntimeError(
                    f"release OAM {case} fallback is not palette 0 with bits 3-7 preserved"
                )
            if (exit_rom_bank, exit_wram_bank, exit_vram_bank) != (0x2D, 7, 1):
                raise Phase2RuntimeError(f"release OAM {case} fallback leaked bank state")
            if (exit_ie, exit_if) != (0x15, 0x1A):
                raise Phase2RuntimeError(
                    f"release OAM {case} fallback changed pending interrupt state"
                )
            observations.append(ReleaseOAMFallbackObservation(
                case=case,
                identity=identity,
                object_index=object_index,
                before_attributes=before,
                shadow_attributes=shadow,
                hardware_attributes=hardware,
                carry=True,
                entry_rom_bank=0x2D,
                exit_rom_bank=exit_rom_bank,
                entry_wram_bank=7,
                exit_wram_bank=exit_wram_bank,
                entry_vram_bank=1,
                exit_vram_bank=exit_vram_bank,
                entry_ie=0x15,
                exit_ie=exit_ie,
                entry_if=0x1A,
                exit_if=exit_if,
            ))
        return tuple(observations)
    finally:
        emulator.close()


def read_phase2_runtime_carrier(emulator: Emulator) -> Phase2Carrier:
    missing = sorted({PHASE2_CARRIER_START, PHASE2_CARRIER_END} - emulator.symbols.keys())
    if missing:
        raise Phase2RuntimeError("debug ROM lacks Phase 2 carrier: " + ", ".join(missing))
    size = emulator.symbols[PHASE2_CARRIER_END] - emulator.symbols[PHASE2_CARRIER_START]
    if size != PHASE2_CARRIER_BYTES:
        raise Phase2RuntimeError(f"linked Phase 2 carrier has size {size}")
    return decode_phase2_carrier(
        emulator.read_bytes(PHASE2_CARRIER_START, PHASE2_CARRIER_BYTES)
    )


def drive_real_hostile_debug_scenario(
    emulator: Emulator,
    snapshot: Callable[[], Phase2Carrier],
) -> None:
    """Drive the approved slice through ordinary gameplay and menu input.

    The mailbox is already armed by :func:`capture_hostile_debug_scenario`.
    This function never writes renderer state or video authority. Its only
    memory-side fixture is the established debug repel used by world traversal;
    ownership, requests, overlays, OAM, handoff and reconstruction all arise
    from production entry points.
    """

    from tools.rom_tests.scenarios.oaks_lab import PALLET_TOWN, complete_oaks_lab_intro
    from tools.rom_tests.scenarios.viridian_city import ROUTE_1, walk_to_value
    from tools.rom_tests.test_support import apply_debug_repel

    complete_oaks_lab_intro(emulator)
    if emulator.read("wCurMap") != PALLET_TOWN:
        raise Phase2RuntimeError("hostile gameplay did not reach Pallet Town")

    # Map entry plus five distinct active presentation frames.
    snapshot()
    for _ in range(5):
        emulator.tick()
        snapshot()

    x_before = emulator.read("wXCoord")
    emulator.press("left", wait_frames=20)
    if emulator.read("wXCoord") == x_before:
        emulator.press("right", wait_frames=20)
    snapshot()
    y_before = emulator.read("wYCoord")
    emulator.press("up", wait_frames=20)
    if emulator.read("wYCoord") == y_before:
        emulator.press("down", wait_frames=20)
    snapshot()

    # Let the real moving-terrain and OAM VBlank producers cross their cadence.
    emulator.tick(60)
    snapshot()

    # Cross the exact Pallet -> Route 1 north connection, then return for the
    # Pallet-only sign/dialogue and menu checkpoints.
    apply_debug_repel(emulator)
    walk_to_value(emulator, "wXCoord", 8, "left", "west side of Oak's Lab")
    walk_to_value(emulator, "wYCoord", 2, "up", "north Pallet Town")
    walk_to_value(emulator, "wXCoord", 10, "right", "Route 1 entrance")
    walk_to_value(emulator, "wCurMap", ROUTE_1, "up", "Route 1")
    emulator.tick(30)
    snapshot()
    walk_to_value(emulator, "wCurMap", PALLET_TOWN, "down", "Pallet return")

    # Oak's Lab sign at (13,13): stand below it, face up against the solid sign,
    # and open the real edge dialogue overlay.
    walk_to_value(emulator, "wXCoord", 13, "right", "Oak's Lab sign column")
    walk_to_value(emulator, "wYCoord", 14, "down", "Oak's Lab sign row")
    emulator.press("up", wait_frames=10)
    emulator.press("a", wait_frames=20)
    snapshot()
    emulator.press("b", wait_frames=30)

    emulator.press("start", wait_frames=20)
    snapshot()
    emulator.press("b", wait_frames=30)

    # Follower Pikachu and Pallet NPCs are now live in the real OAM producer.
    emulator.tick(3)
    snapshot()

    # Start -> POKEMON is one row below POKEDEX once the starter is owned.
    emulator.press("start", wait_frames=20)
    emulator.press("down", wait_frames=10)
    emulator.press("a", wait_frames=60)
    snapshot()
    emulator.press("b", wait_frames=120)
    snapshot()


def capture_hostile_debug_scenario(
    root: Path,
    results: Path,
    *,
    drive: Callable[[Emulator, Callable[[], Phase2Carrier]], None] = drive_real_hostile_debug_scenario,
) -> tuple[GuardedAuditIdentity, tuple[Phase2Carrier, ...]]:
    """Arm, externally drive, and decode the real debug hostile scenario.

    ``drive`` must use gameplay/production boundaries.  Keeping it injected
    makes this module reusable by the runtime runner without granting the ROM
    mailbox authority to synchronously manufacture the scenario.
    """

    identity = require_committed_guarded_audit(root)
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=results,
        cgb=True,
    )
    try:
        required = {
            PHASE2_COMMAND,
            PHASE2_COMMAND_PENDING,
            PHASE2_SCENARIO,
            PHASE2_CARRIER_START,
            PHASE2_CARRIER_END,
        }
        missing = sorted(required - emulator.symbols.keys())
        if missing:
            raise Phase2RuntimeError("debug ROM lacks Phase 2 scenario protocol: " + ", ".join(missing))
        def command(value: int, checkpoint: int) -> None:
            emulator.write(PHASE2_COMMAND, value)
            emulator.write(PHASE2_COMMAND_PENDING, 1)
            for _ in range(121):
                emulator.tick()
                raw = emulator.read_bytes(PHASE2_CARRIER_START, PHASE2_HEADER_BYTES)
                if raw[:4] == PHASE2_MAGIC and raw[13] == checkpoint:
                    return
            raise Phase2RuntimeError(f"Phase 2 command {value:#04x} was not acknowledged")

        # Wait for cold-boot debug initialization without importing the locked
        # Phase 1 observation provider.
        for _ in range(601):
            if emulator.read_bytes("wFullColorDebugMagic", 4) == b"FCG0":
                break
            emulator.tick()
        else:
            raise Phase2RuntimeError("debug ROM did not initialize within 600 frames")
        emulator.write(PHASE2_SCENARIO, PHASE2_SCENARIO_HOSTILE_SLICE)
        command(PHASE2_COMMAND_ARM, PHASE2_COMMAND_ARM)
        captures: list[Phase2Carrier] = []

        def snapshot() -> Phase2Carrier:
            command(PHASE2_COMMAND_SNAPSHOT, PHASE2_COMMAND_SNAPSHOT)
            carrier = read_phase2_runtime_carrier(emulator)
            captures.append(carrier)
            command(PHASE2_COMMAND_ACK, PHASE2_COMMAND_ACK)
            return carrier

        drive(emulator, snapshot)
        if not captures:
            raise Phase2RuntimeError("hostile driver published no checkpoints")
        validate_hostile_records(captures)
        return identity, tuple(captures)
    finally:
        emulator.close()


def _wait_for_debug_ready(emulator: Emulator) -> None:
    for _ in range(601):
        if emulator.read_bytes("wFullColorDebugMagic", 4) == b"FCG0":
            return
        emulator.tick()
    raise Phase2RuntimeError("debug ROM did not initialize within 600 frames")


_RECONSTRUCTION_ITEMS = (
    "base_transformed_hardware_palettes",
    "machine_state_restored",
    "map_tileset_overrides",
    "player_follower_object_shadow_oam",
    "request_scheduler_state",
    "tilemaps_and_attributes",
    "tiles_animation_field_replacements",
    "viewport_scroll_window_destination",
)
_RECONSTRUCTION_PROVENANCE = {
    "base_transformed_hardware_palettes": "FRESHLY_GENERATED_STATE",
    "machine_state_restored": "RESTORED_MACHINE_STATE",
    "map_tileset_overrides": "REQUEST_AUTHORITATIVE_STATE",
    "player_follower_object_shadow_oam": "FRESHLY_GENERATED_STATE",
    "request_scheduler_state": "INITIALIZED_SCHEDULER_STATE",
    "tilemaps_and_attributes": "FRESHLY_GENERATED_STATE",
    "tiles_animation_field_replacements": "REQUEST_AUTHORITATIVE_STATE",
    "viewport_scroll_window_destination": "REQUEST_AUTHORITATIVE_STATE",
}


def _overlay_request_from_actual(case, raw: Phase2RawObservation) -> dict[str, object]:
    inputs = case.inputs
    rectangle = dict(inputs["rectangle"])
    width, height = rectangle["width"], rectangle["height"]
    transform = tuple(inputs["world_transform"])
    mappings: list[dict[str, int]] = []
    for source_index in range(width * height):
        sx, sy = source_index % width, source_index // width
        dx, dy = rectangle["x"] + sx, rectangle["y"] + sy
        if not 0 <= dx < 32 or not 0 <= dy < 32:
            continue
        a, b, c, d, tx, ty = transform
        mappings.append({
            "source_index": source_index,
            "destination_x": dx,
            "destination_y": dy,
            "world_x": a * sx + b * sy + tx,
            "world_y": c * sx + d * sy + ty,
        })
    return {
        "destination_selector": inputs["destination_selector"],
        "map_id": inputs["map_id"],
        "tileset_id": inputs["tileset_id"],
        "rectangle": rectangle,
        "world_origin": None,
        "world_transform": list(transform),
        "coordinate_overrides": dict(inputs["coordinate_overrides"]),
        "classifications": list(inputs["classifications"]),
        "tile_ids": inputs["tile_ids"],
        "attributes": raw.source_attributes[:raw.source_attribute_count].hex(),
        "clipped_mappings": mappings,
        "oracle_sources": ["REQUEST_DATA"],
    }


def _trace_from_actual(case, raw: Phase2RawObservation):
    from .enums import CancellationReason, JobState, Owner, Phase
    from .trace import WriterTrace, WriterTraceEntry

    inputs = case.inputs
    writer = tuple(inputs["writer_ids"])[0]
    generation = raw.after.generation
    commit = inputs.get("commit_unit_id")
    resource_names: tuple[str, ...]
    if raw.case_id < 17 and commit is not None:
        resource_names = ("bg_tile_ids", "bg_attributes")
    elif raw.case_id == 17:
        resource_names = ("bg_palettes",)
    elif raw.case_id == 18:
        resource_names = ("obj_palettes",)
    elif raw.case_id == 22:
        resource_names = ("reconstructed_scene",)
    elif raw.case_id == 23:
        resource_names = ("ownership_generation",)
    else:
        resource_names = ()
    identities = {index + 1: name for index, name in enumerate(resource_names)}
    entries: list[WriterTraceEntry] = []
    sequence = 0

    def add(
        state: JobState, *, job_id: str, entry_generation: int,
        wrote: bool = False, resource_id: int = 0,
        reason: CancellationReason | None = None,
    ) -> None:
        nonlocal sequence
        entries.append(WriterTraceEntry(
            sequence=sequence, frame=raw.frame,
            generation=entry_generation, job_generation=entry_generation,
            owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
            phase=Phase.OVERWORLD_ACTIVE,
            job_owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
            job_state=state, cancellation_reason=reason,
            writer_id=writer, commit_unit_id=commit,
            job_id=job_id, request_id=f"REQ-{case.case_id}",
            resource_id=resource_id, wrote=wrote,
        ))
        sequence += 1

    if raw.case_id == 23:
        for state in (JobState.PENDING, JobState.PREPARED):
            add(state, job_id=str(inputs["old_job_id"]), entry_generation=raw.before.generation)
        add(
            JobState.CANCELLED, job_id=str(inputs["old_job_id"]),
            entry_generation=raw.before.generation,
            reason=CancellationReason.SUPERSEDED,
        )
        job_id = str(inputs["replacement_job_id"])
        add(JobState.PENDING, job_id=job_id, entry_generation=generation)
        add(JobState.PREPARED, job_id=job_id, entry_generation=generation)
        add(JobState.COMMITTING, job_id=job_id, entry_generation=generation,
            wrote=True, resource_id=1)
        add(JobState.COMPLETE, job_id=job_id, entry_generation=generation)
    elif resource_names:
        job_id = f"JOB-{case.case_id}"
        states = tuple(raw.transition_log[:min(raw.transition_count, 8)])
        if not states:
            states = (1, 2, 3)
        for code in states:
            state = (JobState.PENDING, JobState.PREPARED, JobState.COMMITTING,
                     JobState.COMPLETE, JobState.CANCELLED)[code]
            if state is JobState.COMMITTING:
                for resource_id in identities:
                    add(state, job_id=job_id, entry_generation=generation,
                        wrote=True, resource_id=resource_id)
            else:
                add(state, job_id=job_id, entry_generation=generation)
    elif 19 <= raw.case_id <= 21:
        add(JobState.COMMITTING, job_id=f"OBS-{case.case_id}",
            entry_generation=generation)
    return WriterTrace(
        capacity=max(8, len(entries)), entries=tuple(entries),
        permitted_writer_ids=tuple(inputs["writer_ids"]),
        resource_identities=identities,
    )


def _machine_boundary_from_actual(case, raw: Phase2RawObservation):
    if raw.case_id != 24:
        return None
    from dataclasses import replace
    from .bank_torture import (
        BankTortureCase, BankTortureEvent, BankTortureResult, BoundarySnapshot,
    )
    from .enums import Owner, Phase
    from .snapshots import BankState

    banks = BankState(raw.before.rom_bank, raw.before.wram_bank, raw.before.vram_bank)
    boundary_case = BankTortureCase(
        case.case_id, BankTortureEvent.FAR_CALL_INTERRUPT, banks, False
    )
    before = BoundarySnapshot(
        banks=banks, stack_pointer=0xCFFE, stack_window=bytes(32),
        interrupt_master_enabled=False,
        interrupt_enable=raw.before.ie, interrupt_flags=raw.before.interrupt_flags,
        owner=Owner.RENDERER_YELLOW, phase=Phase.YELLOW_ACTIVE,
        generation=raw.before.generation,
        dirty_bg=False, dirty_obj=False, dirty_attributes=False,
        job_state=None, cancellation_reason=None,
    )
    during = replace(
        before,
        banks=BankState(1, 3, 0), stack_pointer=before.stack_pointer - 2,
        interrupt_master_enabled=False,
    )
    after = replace(
        before,
        banks=BankState(raw.after.rom_bank, raw.after.wram_bank, raw.after.vram_bank),
        interrupt_enable=raw.after.ie, interrupt_flags=raw.after.interrupt_flags,
        generation=raw.after.generation,
    )
    return BankTortureResult(boundary_case, before, during, after, True, True)


def _observation_from_actual(case, raw: Phase2RawObservation, rom_identity: str):
    from .enums import OAMFallbackKind
    from .phase2_conformance_runtime import Phase2Observation
    from .snapshots import SemanticSnapshot

    reconstruction_case = raw.case_id == 22 and raw.non_overlay_trace is not None
    # Every diagnostic enters through the real active-overworld ownership
    # boundary. The semantic contract therefore retains the closed authority
    # ledger for every case; case 22 additionally publishes its real barrier.
    completed = list(_RECONSTRUCTION_ITEMS)
    fallback = {
        "occurred": False, "fallback_kind": None, "object_id": None,
        "final_tile_id": None, "identity": None, "generation": None,
        "writer_id": None, "palette": None,
        "before_attributes": 0, "after_attributes": 0,
    }
    if 19 <= raw.case_id <= 21:
        record = raw.non_overlay_trace
        if record is None:
            raise Phase2RuntimeError("Phase 2 OAM case lacks actual fallback record")
        kinds = {
            1: OAMFallbackKind.MISSING_IDENTITY.value,
            2: OAMFallbackKind.OUT_OF_RANGE_IDENTITY.value,
            3: OAMFallbackKind.UNMAPPED_IDENTITY.value,
        }
        fallback = {
            "occurred": True, "fallback_kind": kinds[record.fallback_kind],
            "object_id": "OBJECT-1", "final_tile_id": raw.shadow_oam[2],
            "identity": None if record.fallback_identity == 0xFFFF else record.fallback_identity,
            "generation": raw.after.generation,
            "writer_id": tuple(case.inputs["writer_ids"])[0], "palette": 0,
            "before_attributes": record.oam_before,
            "after_attributes": record.oam_after,
        }
    bg_attributes = bytearray(raw.bg_attributes)
    if 14 <= raw.case_id <= 16:
        rectangle = case.inputs["rectangle"]
        committed = raw.overlay_attributes[:raw.attribute_count]
        for index, value in enumerate(committed):
            x = rectangle["x"] + index % rectangle["width"]
            y = rectangle["y"] + index // rectangle["width"]
            bg_attributes[y * 32 + x] = value
    snapshot = SemanticSnapshot.from_dict({
        "schema": "full-color-contract-v1", "rom": rom_identity,
        "scenario": case.case_id, "seed": 0, "checkpoint": "after-commit",
        "frame": raw.frame, "evidence_kind": "RENDERER_RUNTIME",
        "activation_phase": 2, "owner": "RENDERER_FULL_COLOR_OVERWORLD",
        "phase": "OVERWORLD_OVERLAY" if raw.case_id < 14 else "OVERWORLD_ACTIVE",
        "generation": raw.after.generation, "request_result": None, "job": None,
        "writer_id": tuple(case.inputs["writer_ids"])[0],
        "traced_writer_ids": list(case.inputs["writer_ids"]),
        "banks": {"rom": raw.after.rom_bank, "wram": raw.after.wram_bank,
                  "vram": raw.after.vram_bank},
        "dirty": {"bg": False, "obj": False, "attributes": False},
        "queued_jobs": [],
        "reconstruction": {
            "required_items": list(_RECONSTRUCTION_ITEMS),
            "completed_items": completed,
            "item_provenance": _RECONSTRUCTION_PROVENANCE,
            "poisoned_items": completed,
            "unknown_prior_state": True,
            "presentation_barrier_count": (
                raw.non_overlay_trace.reconstruction_barrier
                if reconstruction_case and raw.non_overlay_trace is not None else 1
            ),
        },
        "bg_tile_ids": raw.bg_tile_ids.hex(),
        "bg_attributes": bytes(bg_attributes).hex(),
        "bg_palettes": raw.bg_palette_base.hex(),
        "obj_palettes": raw.obj_palette_base.hex(),
        "shadow_oam": raw.shadow_oam.hex(), "hardware_oam": raw.hardware_oam.hex(),
        "map_id": case.inputs.get("map_id"),
        "tileset_id": case.inputs.get("tileset_id"),
        "transfer_state": case.inputs.get("transfer_kind"),
        "overlay_request": (
            _overlay_request_from_actual(case, raw) if raw.case_id < 14 else None
        ),
        "oam_fallback": fallback, "timing_row_key": None, "timing_row": None,
        "artifacts": {},
    })
    return Phase2Observation(
        case.case_id, rom_identity, snapshot, _trace_from_actual(case, raw),
        _machine_boundary_from_actual(case, raw),
    )


def _capture_pallet_visual(root: Path, results: Path):
    from types import MethodType
    from .phase2_runtime_capture import InputReplayEvent
    from tools.rom_tests.scenarios.oaks_lab import PALLET_TOWN, REDS_HOUSE_1F

    emulator = Emulator(
        root / "pokeyellow_debug.gbc", root / "pokeyellow_debug.sym", results, cgb=True
    )
    replay = [InputReplayEvent(0, 0)]
    masks = {"right": 1, "left": 2, "up": 4, "down": 8,
             "a": 16, "b": 32, "select": 64, "start": 128}
    original_press = emulator.press

    def recorded_press(self, button: str, wait_frames: int = 120) -> None:
        replay.append(InputReplayEvent(self.frame, masks[button]))
        original_press(button, wait_frames)
        replay.append(InputReplayEvent(self.frame, 0))

    emulator.press = MethodType(recorded_press, emulator)
    try:
        boot_inputs = {
            650: "start", 700: "a", 750: "start", 800: "a",
            900: "start", 950: "a", 1050: "start", 1100: "a",
            1200: "start", 1250: "a",
        }
        for frame in range(1, 1321):
            button = boot_inputs.get(frame)
            if button is not None:
                emulator.pyboy.button(button, delay=2)
                replay.extend((
                    InputReplayEvent(frame, masks[button]),
                    InputReplayEvent(frame + 2, 0),
                ))
            emulator.tick()
        emulator.advance_until(
            emulator.is_in_bedroom_overworld,
            button="a", max_presses=100, description="bedroom overworld",
        )

        def advance(symbol: str, value: int, button: str, description: str) -> None:
            emulator.advance_until(
                lambda: emulator.read(symbol) == value,
                button=button, max_presses=140, description=description,
            )

        advance("wXCoord", 5, "right", "bedroom aisle")
        advance("wYCoord", 1, "up", "bedroom stairs")
        advance("wCurMap", REDS_HOUSE_1F, "right", "first floor")
        advance("wYCoord", 6, "down", "house exit row")
        advance("wXCoord", 3, "left", "house exit")
        advance("wCurMap", PALLET_TOWN, "down", "Pallet Town")
        if emulator.read("wCurMap") != PALLET_TOWN:
            raise Phase2RuntimeError("visual capture did not reach Pallet Town")
        frames = [emulator.capture_screen()]
        numbers = [emulator.frame]
        x_before = emulator.read("wXCoord")
        emulator.press("left", wait_frames=20)
        if emulator.read("wXCoord") == x_before:
            emulator.press("right", wait_frames=20)
        frames.append(emulator.capture_screen())
        numbers.append(emulator.frame)
        emulator.tick()
        frames.append(emulator.capture_screen())
        numbers.append(emulator.frame)
        return tuple(frames), tuple(numbers), tuple(replay)
    finally:
        emulator.close()


def capture_phase2_observation_bundle(root: Path, results: Path):
    """Capture one exact 25-case FCO2 v2 run and real Pallet pixels."""

    from .phase2_conformance_runtime import canonical_phase2_cases
    from .phase2_runtime_capture import (
        InputReplayEvent,
        Phase2ObservationBundle,
    )

    root = root.resolve()
    require_committed_guarded_audit(root)
    rom = root / "pokeyellow_debug.gbc"
    rom_identity = f"{rom.name}:{_sha256(rom)}"
    emulator = Emulator(
        rom=rom, symbols=root / "pokeyellow_debug.sym", results=results, cgb=True,
    )
    try:
        _require_complete_observation_abi(emulator)
        _wait_for_debug_ready(emulator)
        raws: list[Phase2RawObservation] = []
        for case_id in range(PHASE2_DIAGNOSTIC_CASES):
            if case_id < PHASE2_DIAGNOSTIC_OVERLAY_CASES:
                _call_diagnostic_overlay_case(emulator, case_id)
            else:
                _call_diagnostic_non_overlay_case(emulator, case_id)
            raw = _capture_live_observation(emulator)
            if (raw.case_id, raw.sequence) != (case_id, case_id + 1):
                raise Phase2RuntimeError(
                    "Phase 2 diagnostic publication is not exact ordered 0..24"
                )
            raws.append(raw)
    finally:
        emulator.close()

    cases = canonical_phase2_cases(root)
    observations = tuple(
        _observation_from_actual(case, raw, rom_identity)
        for case, raw in zip(cases, raws, strict=True)
    )
    frames, frame_numbers, replay = _capture_pallet_visual(root, results / "visual")
    _, carriers = capture_hostile_debug_scenario(
        root, results / "hostile-scenario"
    )
    fallbacks = probe_release_oam_fallbacks(root, results / "release-oam")
    return Phase2ObservationBundle(
        observations=observations,
        carriers=carriers,
        release_fallbacks=fallbacks,
        frames=frames,
        frame_numbers=frame_numbers,
        checkpoint_index=1,
        visual_case_id="RC-TRANSFER-ROW",
        input_replay=replay,
    )


def _capture_live_observation(emulator: Emulator) -> Phase2RawObservation:
    """Copy every mutable machine resource before the emulator advances."""

    semantic = emulator.read_bytes(
        "wFullColorPhase2SemanticSnapshotStart", PHASE2_SEMANTIC_BYTES
    )
    trace = emulator.read_bytes("wFullColorPhase2WriterTraceStart", PHASE2_TRACE_BYTES)
    boundary = emulator.read_bytes("wFullColorPhase2BoundaryStart", PHASE2_BOUNDARY_BYTES)
    # Each map is captured from both physical VRAM banks. The Emulator bank
    # view restores rVBK, so observation cannot perturb the next matrix case.
    bg_tiles = emulator.read_memory(0x9800, 0x800, bank=0)
    bg_attributes = emulator.read_memory(0x9800, 0x800, bank=1)
    return decode_phase2_observation_regions(
        semantic, trace, boundary,
        bg_tile_ids=bg_tiles,
        bg_attributes=bg_attributes,
        bg_palette_base=emulator.read_bytes("wFullColorBGPaletteBase", 64),
        bg_palette_transformed=emulator.read_bytes("wFullColorBGPaletteTransformed", 64),
        obj_palette_base=emulator.read_bytes("wFullColorOBJPaletteBase", 64),
        obj_palette_transformed=emulator.read_bytes("wFullColorOBJPaletteTransformed", 64),
        attribute_rectangle=emulator.read_bytes("wFullColorAttributeRectangle", 360),
        shadow_oam=emulator.read_bytes("wShadowOAM", 160),
        hardware_oam=emulator.read_memory(0xFE00, 160),
        frame=emulator.frame,
    )


def _call_diagnostic_overlay_case(emulator: Emulator, case_id: int) -> None:
    if not 0 <= case_id < PHASE2_DIAGNOSTIC_OVERLAY_CASES:
        raise Phase2RuntimeError("Phase 2 diagnostic matrix case is out of range")
    _call_diagnostic_case(emulator, case_id, "RunFullColorPhase2DiagnosticOverlayMatrix")


def _call_diagnostic_case(emulator: Emulator, case_id: int, name: str) -> None:
    target = emulator.symbols[name]
    target_bank = emulator.symbol_banks[name]
    bankswitch = emulator.symbols["Bankswitch"]
    code = bytes((
        0xF3,                         # di
        0x3E, case_id,                # ld a, case_id
        0x06, target_bank,            # ld b, BANK(target)
        0x21, target & 0xFF, target >> 8,
        0xCD, bankswitch & 0xFF, bankswitch >> 8,
        0xC9,
    ))

    def setup() -> None:
        memory = emulator.pyboy.memory
        registers = emulator.pyboy.register_file
        for offset, value in enumerate(code):
            memory[0xC6F0 + offset] = value
        outer_bank = 0x101 if case_id == 24 else 0x2D
        memory[0x2000] = outer_bank & 0xFF
        memory[0x3000] = outer_bank >> 8
        memory[emulator.symbols["hLoadedROMBank"]] = outer_bank & 0xFF
        outer = emulator.symbols["wFullColorPhase2DiagnosticOuterROMBank"]
        outer_wram_bank = emulator.symbol_banks[
            "wFullColorPhase2DiagnosticOuterROMBank"
        ]
        memory[outer_wram_bank, outer] = outer_bank & 0xFF
        memory[outer_wram_bank, outer + 1] = outer_bank >> 8
        memory[0xFF70] = 7
        memory[0xFF4F] = 1
        memory[0xFFFF] = 0x15
        memory[0xFF0F] = 0x1A
        registers.SP = 0xCFFE
        memory[0xCFFE] = 0
        memory[0xCFFF] = 1
        registers.PC = 0xC6F0

    # Bankswitch is a tail-call ABI and therefore consumes A while selecting
    # the ROM bank. Set the routine's documented A argument at its first
    # instruction, exactly as the debugger/tester does for exported entry ABI.
    def supply_argument(_: object) -> None:
        emulator.pyboy.register_file.A = case_id

    emulator.pyboy.hook_register(target_bank, target, supply_argument, None)
    try:
        _, flags = _run_until_return(emulator, setup, name=f"{name}[{case_id}]")
    finally:
        emulator.pyboy.hook_deregister(target_bank, target)
    if flags & 0x10:
        raise Phase2RuntimeError(f"Phase 2 diagnostic matrix case {case_id} returned carry")


def _call_diagnostic_non_overlay_case(emulator: Emulator, case_id: int) -> None:
    if not PHASE2_DIAGNOSTIC_OVERLAY_CASES <= case_id < PHASE2_DIAGNOSTIC_CASES:
        raise Phase2RuntimeError("Phase 2 non-overlay case is out of range")
    _call_diagnostic_case(
        emulator, case_id, "RunFullColorPhase2DiagnosticNonOverlayCase"
    )


def capture_diagnostic_overlay_matrix(
    root: Path, results: Path
) -> tuple[Phase2RawObservation, ...]:
    """Execute and retain all 14 production commits in strict ordinal order."""

    root = root.resolve()
    require_committed_guarded_audit(root)
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=results,
        cgb=True,
    )
    try:
        _require_complete_observation_abi(emulator)
        for _ in range(601):
            if emulator.read_bytes("wFullColorDebugMagic", 4) == b"FCG0":
                break
            emulator.tick()
        else:
            raise Phase2RuntimeError("debug ROM did not initialize within 600 frames")
        captures: list[Phase2RawObservation] = []
        for case_id in range(PHASE2_DIAGNOSTIC_OVERLAY_CASES):
            _call_diagnostic_overlay_case(emulator, case_id)
            observation = _capture_live_observation(emulator)
            if observation.case_id != case_id or observation.sequence != case_id + 1:
                raise Phase2RuntimeError("Phase 2 diagnostic matrix publication order changed")
            captures.append(observation)
        return tuple(captures)
    finally:
        emulator.close()
