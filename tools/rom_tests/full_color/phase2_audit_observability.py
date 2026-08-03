"""Fail-closed host access to the guarded Phase 2 WRAM audit carrier.

This module is deliberately product-specific.  It will not operate on a normal
ROM, guess a link layout, or use the cartridge SRAM controller.  Runtime suites
may use it to call the guarded seams and turn one atomic WRAM2 snapshot into
JSON-serializable evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Callable, Mapping

from tools.rom_tests.emulator import Emulator

from .phase2_measurements import (
    AUDIT_MARKER,
    Phase2MeasurementError,
    _verify_audit_product,
    discover_phase2_sources,
)


AUDIT_PRODUCT = "pokeyellow_phase2_audit"
WRAM_BANK = 2
CARRIER_BYTES = 295
TRACE_RECORD_BYTES = 24
TRACE_CAPACITY = 8
RETURN_TRAP = 0x0100
HRAM_TRAMPOLINE = 0xFF90
STACK_POINTER = 0xC080
STACK_GUARD_START = 0xC000
STACK_GUARD = bytes(range(0x40, 0x60))

COMMAND_NAMES = {
    "clear": "FULL_COLOR_DEBUG_COMMAND_CLEAR",
    "arm": "FULL_COLOR_DEBUG_COMMAND_ARM",
    "snapshot": "FULL_COLOR_DEBUG_COMMAND_SNAPSHOT",
    "ack": "FULL_COLOR_DEBUG_COMMAND_ACK",
}
CHECKPOINT_NAMES = {
    "clear": "FULL_COLOR_DEBUG_CHECKPOINT_CLEAR",
    "arm": "FULL_COLOR_DEBUG_CHECKPOINT_ARMED",
    "snapshot": "FULL_COLOR_DEBUG_CHECKPOINT_SNAPSHOT",
    "ack": "FULL_COLOR_DEBUG_CHECKPOINT_ACKNOWLEDGED",
}
PROTOCOL = {"clear": 0, "arm": 1, "snapshot": 2, "ack": 3}

REQUIRED_CONSTANTS = frozenset(COMMAND_NAMES.values()) | frozenset(
    CHECKPOINT_NAMES.values()
) | {
    "FULL_COLOR_FALLBACK_NONE",
    "FULL_COLOR_FALLBACK_MISSING_IDENTITY",
    "FULL_COLOR_FALLBACK_OUT_OF_RANGE",
    "FULL_COLOR_FALLBACK_UNMAPPED",
    "FULL_COLOR_RESOURCE_ALL",
}

REQUIRED_SYMBOL_LAYOUT = {
    "wFullColorDebugCarrierStart": (WRAM_BANK, 0),
    "wFullColorDebugProtocolState": (WRAM_BANK, 0),
    "wFullColorDebugCommandPhase2": (WRAM_BANK, 1),
    "wFullColorDebugCheckpointPhase2": (WRAM_BANK, 2),
    "wFullColorDebugScenario": (WRAM_BANK, 3),
    "wFullColorDebugSequence": (WRAM_BANK, 4),
    "wFullColorDebugEntrySVBK": (WRAM_BANK, 6),
    "wFullColorDebugExitSVBK": (WRAM_BANK, 7),
    "wFullColorDebugEntryIE": (WRAM_BANK, 8),
    "wFullColorDebugExitIE": (WRAM_BANK, 9),
    "wFullColorDebugEntrySP": (WRAM_BANK, 10),
    "wFullColorDebugExitSP": (WRAM_BANK, 12),
    "wFullColorDebugOwnerPhase": (WRAM_BANK, 14),
    "wFullColorDebugGenerationPhase2": (WRAM_BANK, 16),
    "wFullColorDebugRequestState": (WRAM_BANK, 20),
    "wFullColorDebugWriterState": (WRAM_BANK, 24),
    "wFullColorDebugCommonState": (WRAM_BANK, 28),
    "wFullColorDebugFallbackState": (WRAM_BANK, 32),
    "wFullColorDebugReconstructionState": (WRAM_BANK, 36),
    "wFullColorDebugTraceCountPhase2": (WRAM_BANK, 44),
    "wFullColorDebugTraceWritePhase2": (WRAM_BANK, 45),
    "wFullColorDebugTracePhase2": (WRAM_BANK, 46),
    "wFullColorDebugCarrierReserved": (WRAM_BANK, 238),
    "wFullColorDebugCarrierEnd": (WRAM_BANK, CARRIER_BYTES),
}

REQUIRED_ROUTINES = (
    "Bankswitch",
    "PollFullColorPhase2DebugCommand",
    "InitRendererOwnership",
    "InitFullColorScheduler",
    "InitFullColorPhase2LifecycleSelected",
    "SnapshotFullColorMapAuthority",
    "BeginFullColorMapEntry",
    "CompleteFullColorMapReconstruction",
    "EnsureFullColorPartyHandoff",
    "ReturnFullColorFromParty",
    "IsFullColorPartyReturnPending",
    "LeaveFullColorOverworldSlice",
    "EnterFullColorOverlay",
    "ExitFullColorOverlay",
)
SELECTED_WRAM2_ROUTINES = frozenset({"InitFullColorPhase2LifecycleSelected"})


class Phase2AuditError(AssertionError):
    """The requested observation is not trustworthy."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_symbols(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if len(fields) != 2 or ":" in fields[0]:
            continue
        try:
            value = int(fields[0], 16)
        except ValueError as exc:
            raise Phase2AuditError(f"{path.name}:{number}: malformed constant") from exc
        name = fields[1]
        if name in values and values[name] != value:
            raise Phase2AuditError(f"{path.name}:{number}: duplicate constant {name}")
        values[name] = value
    return values


@dataclass(frozen=True, slots=True)
class Phase2AuditIdentity:
    rom_sha256: str
    sym_sha256: str
    map_sha256: str
    source_sha256: str
    rom_name: str = f"{AUDIT_PRODUCT}.gbc"
    sym_name: str = f"{AUDIT_PRODUCT}.sym"
    map_name: str = f"{AUDIT_PRODUCT}.map"

    def __post_init__(self) -> None:
        for name in ("rom_sha256", "sym_sha256", "map_sha256", "source_sha256"):
            value = getattr(self, name)
            if len(value) != 64:
                raise Phase2AuditError(f"{name} is not an exact SHA-256 identity")
            try:
                int(value, 16)
            except ValueError as exc:
                raise Phase2AuditError(f"{name} is not an exact SHA-256 identity") from exc
        expected_names = (
            f"{AUDIT_PRODUCT}.gbc",
            f"{AUDIT_PRODUCT}.sym",
            f"{AUDIT_PRODUCT}.map",
        )
        if (self.rom_name, self.sym_name, self.map_name) != expected_names:
            raise Phase2AuditError("identity names a product other than Phase 2 audit")

    @classmethod
    def from_root(cls, root: Path) -> "Phase2AuditIdentity":
        root = root.resolve()
        artifact_paths = tuple(
            root / f"{AUDIT_PRODUCT}{suffix}" for suffix in (".gbc", ".sym", ".map")
        )
        try:
            before = tuple(_sha256(path) for path in artifact_paths)
            _verify_audit_product(root)
            source_sha = discover_phase2_sources(root).source_sha256
            after = tuple(_sha256(path) for path in artifact_paths)
        except (OSError, Phase2MeasurementError, ValueError) as exc:
            raise Phase2AuditError(f"invalid Phase 2 audit product: {exc}") from exc
        if before != after:
            raise Phase2AuditError("Phase 2 audit artifacts changed during identity capture")
        return cls(
            rom_sha256=after[0],
            sym_sha256=after[1],
            map_sha256=after[2],
            source_sha256=source_sha,
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AuditBanks:
    rom: int
    wram: int
    vram: int

    def __post_init__(self) -> None:
        if not 1 <= self.rom <= 0xFF:
            raise Phase2AuditError("ROM bank must be in 1..255")
        if not 1 <= self.wram <= 7:
            raise Phase2AuditError("WRAM bank must be in 1..7")
        if self.vram not in (0, 1):
            raise Phase2AuditError("VRAM bank must be zero or one")


@dataclass(frozen=True, slots=True)
class AuditCallObservation:
    routine: str
    entry_banks: AuditBanks
    exit_banks: AuditBanks
    entry_ie: int
    exit_ie: int
    entry_if: int
    exit_if: int
    entry_sp: int
    exit_sp: int
    a: int
    flags: int

    @property
    def carry(self) -> bool:
        return bool(self.flags & 0x10)

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw["carry"] = self.carry
        return raw


@dataclass(frozen=True, slots=True)
class AuditRequestState:
    count: int
    cursor: int
    last_admission_result: int
    transition_count: int


@dataclass(frozen=True, slots=True)
class AuditWriterState:
    assertion_code: int
    transition_count: int
    first_transition: int
    writer_mask: int


@dataclass(frozen=True, slots=True)
class AuditCommonState:
    auto_bg_transfer: int
    bg_rows: int
    copy_size: int
    redraw_mode: int


@dataclass(frozen=True, slots=True)
class AuditFallbackState:
    count: int
    overflowed: bool
    kind: int
    rejected_identity: int
    object_index: int


@dataclass(frozen=True, slots=True)
class AuditReconstructionState:
    barrier_count: int
    map_id: int
    tileset_id: int
    y: int
    x: int
    reserved: bytes


@dataclass(frozen=True, slots=True)
class Phase2AuditSnapshot:
    protocol: int
    command: int
    checkpoint: int
    scenario: int
    sequence: int
    entry_svbk: int
    exit_svbk: int
    entry_ie: int
    exit_ie: int
    entry_sp: int
    exit_sp: int
    owner: int
    phase: int
    generation: int
    request: AuditRequestState
    writer: AuditWriterState
    common: AuditCommonState
    fallback: AuditFallbackState
    reconstruction: AuditReconstructionState
    trace_count: int
    trace_write: int
    trace_records: tuple[bytes, ...]

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw["reconstruction"]["reserved"] = self.reconstruction.reserved.hex()
        raw["trace_records"] = [record.hex() for record in self.trace_records]
        return raw


@dataclass(frozen=True, slots=True)
class Phase2ProtocolObservation:
    identity: Phase2AuditIdentity
    snapshot: Phase2AuditSnapshot
    party_return_pending: bool
    calls: tuple[AuditCallObservation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.to_dict(),
            "snapshot": self.snapshot.to_dict(),
            "party_return_pending": self.party_return_pending,
            "calls": [call.to_dict() for call in self.calls],
        }


def decode_phase2_audit_snapshot(
    raw: bytes,
    *,
    constants: Mapping[str, int],
    expected_protocol: int | None = None,
    expected_checkpoint: int | None = None,
    expected_sequence: int | None = None,
) -> Phase2AuditSnapshot:
    """Decode one exact carrier image and reject ambiguous or corrupt state."""

    if len(raw) != CARRIER_BYTES:
        raise Phase2AuditError(
            f"audit carrier is {len(raw)} bytes; expected exactly {CARRIER_BYTES}"
        )
    missing = sorted(REQUIRED_CONSTANTS - constants.keys())
    if missing:
        raise Phase2AuditError("missing audit constants: " + ", ".join(missing))
    protocol, command, checkpoint, scenario = raw[:4]
    sequence = int.from_bytes(raw[4:6], "little")
    if expected_protocol is not None and protocol != expected_protocol:
        raise Phase2AuditError(
            f"protocol state {protocol:#04x} != expected {expected_protocol:#04x}"
        )
    if expected_checkpoint is not None and checkpoint != expected_checkpoint:
        raise Phase2AuditError(
            f"checkpoint {checkpoint:#04x} != expected {expected_checkpoint:#04x}"
        )
    if expected_sequence is not None and sequence != expected_sequence:
        raise Phase2AuditError(
            f"snapshot sequence {sequence} != expected {expected_sequence}"
        )
    if command:
        raise Phase2AuditError("audit command was not consumed before observation")

    request = AuditRequestState(*raw[20:24])
    if request.count > TRACE_CAPACITY or request.cursor >= TRACE_CAPACITY:
        raise Phase2AuditError("request state exceeds the eight-slot scheduler ring")
    writer = AuditWriterState(*raw[24:28])
    if writer.transition_count != request.transition_count:
        raise Phase2AuditError("writer/request transition counts disagree")
    if writer.writer_mask & ~constants["FULL_COLOR_RESOURCE_ALL"]:
        raise Phase2AuditError("writer mask names an unknown visible resource")
    common = AuditCommonState(*raw[28:32])
    fallback_count = raw[32]
    fallback = AuditFallbackState(
        count=fallback_count & 0x7F,
        overflowed=bool(fallback_count & 0x80),
        kind=raw[33],
        rejected_identity=raw[34],
        object_index=raw[35],
    )
    fallback_kinds = {
        constants["FULL_COLOR_FALLBACK_NONE"],
        constants["FULL_COLOR_FALLBACK_MISSING_IDENTITY"],
        constants["FULL_COLOR_FALLBACK_OUT_OF_RANGE"],
        constants["FULL_COLOR_FALLBACK_UNMAPPED"],
    }
    if fallback.kind not in fallback_kinds:
        raise Phase2AuditError(f"unknown fallback kind {fallback.kind:#04x}")
    if fallback.count == 0 and (
        fallback.overflowed
        or fallback.kind != constants["FULL_COLOR_FALLBACK_NONE"]
        or fallback.rejected_identity
        or fallback.object_index
    ):
        raise Phase2AuditError("empty fallback ledger contains a phantom event")
    reconstruction = AuditReconstructionState(
        barrier_count=raw[36],
        map_id=raw[37],
        tileset_id=raw[38],
        y=raw[39],
        x=raw[40],
        reserved=raw[41:44],
    )
    if reconstruction.barrier_count > 1:
        raise Phase2AuditError("reconstruction crossed more than one barrier")
    if reconstruction.reserved != b"\0\0\0":
        raise Phase2AuditError("reconstruction reserved bytes are non-zero")
    trace_count, trace_write = raw[44:46]
    if trace_count > TRACE_CAPACITY or trace_write >= TRACE_CAPACITY:
        raise Phase2AuditError("audit trace exceeds its bounded ring")
    trace = raw[46 : 46 + TRACE_CAPACITY * TRACE_RECORD_BYTES]
    if raw[46 + TRACE_CAPACITY * TRACE_RECORD_BYTES :] != bytes(
        CARRIER_BYTES - 46 - TRACE_CAPACITY * TRACE_RECORD_BYTES
    ):
        raise Phase2AuditError("audit carrier reserved tail is non-zero")
    records = tuple(
        trace[index * TRACE_RECORD_BYTES : (index + 1) * TRACE_RECORD_BYTES]
        for index in range(trace_count)
    )
    return Phase2AuditSnapshot(
        protocol=protocol,
        command=command,
        checkpoint=checkpoint,
        scenario=scenario,
        sequence=sequence,
        entry_svbk=raw[6],
        exit_svbk=raw[7],
        entry_ie=raw[8],
        exit_ie=raw[9],
        entry_sp=int.from_bytes(raw[10:12], "little"),
        exit_sp=int.from_bytes(raw[12:14], "little"),
        owner=raw[14],
        phase=raw[15],
        generation=int.from_bytes(raw[16:20], "little"),
        request=request,
        writer=writer,
        common=common,
        fallback=fallback,
        reconstruction=reconstruction,
        trace_count=trace_count,
        trace_write=trace_write,
        trace_records=records,
    )


class Phase2AuditHarness:
    """Own an isolated CGB emulator and the guarded audit command protocol."""

    def __init__(
        self,
        root: Path,
        results: Path,
        *,
        expected_identity: Phase2AuditIdentity | None = None,
    ) -> None:
        self.root = root.resolve()
        self.identity = Phase2AuditIdentity.from_root(self.root)
        if expected_identity is not None and self.identity != expected_identity:
            raise Phase2AuditError("Phase 2 audit product identity changed")
        rom = self.root / self.identity.rom_name
        sym = self.root / self.identity.sym_name
        self.constants = _numeric_symbols(sym)
        missing = sorted(REQUIRED_CONSTANTS - self.constants.keys())
        if missing:
            raise Phase2AuditError("audit symbol file lacks constants: " + ", ".join(missing))
        self.emulator = Emulator(rom=rom, symbols=sym, results=results, cgb=True)
        self._calls: list[AuditCallObservation] = []
        try:
            actual_artifacts = (
                _sha256(rom),
                _sha256(sym),
                _sha256(self.root / self.identity.map_name),
            )
            expected_artifacts = (
                self.identity.rom_sha256,
                self.identity.sym_sha256,
                self.identity.map_sha256,
            )
            if actual_artifacts != expected_artifacts:
                raise Phase2AuditError("Phase 2 artifacts changed while opening emulator")
            self._validate_link_layout()
        except Exception:
            self.emulator.close()
            raise

    def close(self) -> None:
        self.emulator.close()

    def __enter__(self) -> "Phase2AuditHarness":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _validate_link_layout(self) -> None:
        symbols = self.emulator.symbols
        banks = self.emulator.symbol_banks
        missing = sorted(
            (set(REQUIRED_SYMBOL_LAYOUT) | set(REQUIRED_ROUTINES)) - symbols.keys()
        )
        if missing:
            raise Phase2AuditError("audit product lacks symbols: " + ", ".join(missing))
        start = symbols["wFullColorDebugCarrierStart"]
        for name, (bank, offset) in REQUIRED_SYMBOL_LAYOUT.items():
            actual = (banks[name], symbols[name] - start)
            if actual != (bank, offset):
                raise Phase2AuditError(
                    f"audit carrier layout mismatch for {name}: {actual!r}"
                )
        if banks["PollFullColorPhase2DebugCommand"] == 0:
            raise Phase2AuditError("audit command poll unexpectedly linked in Home")
        marker = self.root.joinpath(self.identity.rom_name).read_bytes()
        if AUDIT_MARKER not in marker:
            raise Phase2AuditError("audit provenance marker disappeared")

    def invoke(
        self,
        routine: str,
        *,
        entry_banks: AuditBanks = AuditBanks(rom=0x2D, wram=7, vram=1),
        ie: int = 0x1F,
        interrupt_flags: int = 0x1F,
        stack_pointer: int = STACK_POINTER,
        a: int = 0,
        c: int = 0,
        hl: int = 0,
        preserve_banks: bool = True,
        preserve_interrupts: bool = True,
    ) -> AuditCallObservation:
        """Invoke a guarded seam through the real bank-switch return path."""

        if routine not in REQUIRED_ROUTINES:
            raise Phase2AuditError(f"routine is not an approved guarded seam: {routine}")
        if routine in SELECTED_WRAM2_ROUTINES and entry_banks.wram != WRAM_BANK:
            raise Phase2AuditError(f"{routine} requires WRAM bank 2 selected on entry")
        if not 0 <= ie <= 0xFF or not 0 <= interrupt_flags <= 0xFF:
            raise Phase2AuditError("IE and IF must be bytes")
        if not 0xC060 <= stack_pointer <= 0xCFFE:
            raise Phase2AuditError("stack pointer is outside the fixed-WRAM pressure window")
        emu = self.emulator
        memory = emu.pyboy.memory
        registers = emu.pyboy.register_file
        for offset, value in enumerate(STACK_GUARD):
            memory[STACK_GUARD_START + offset] = value
        memory[stack_pointer] = RETURN_TRAP & 0xFF
        memory[stack_pointer + 1] = RETURN_TRAP >> 8
        memory[0x2000] = entry_banks.rom
        memory[emu.symbols["hLoadedROMBank"]] = entry_banks.rom
        memory[0xFF70] = entry_banks.wram
        memory[0xFF4F] = entry_banks.vram
        memory[0xFFFF] = ie
        memory[0xFF0F] = interrupt_flags
        registers.A = a
        registers.B = emu.symbol_banks[routine]
        registers.C = c
        registers.HL = emu.symbols[routine] if hl == 0 else hl
        registers.SP = stack_pointer
        # DI; JP Bankswitch. Bankswitch supplies the exact far-call save/restore
        # behavior while pending IE/IF remain raw evidence instead of firing.
        memory[HRAM_TRAMPOLINE] = 0xF3
        memory[HRAM_TRAMPOLINE + 1] = 0xC3
        memory[HRAM_TRAMPOLINE + 2] = emu.symbols["Bankswitch"] & 0xFF
        memory[HRAM_TRAMPOLINE + 3] = emu.symbols["Bankswitch"] >> 8
        registers.PC = HRAM_TRAMPOLINE
        returned = False
        observation: AuditCallObservation | None = None

        def at_return(_: object) -> None:
            nonlocal returned, observation
            returned = True
            observation = AuditCallObservation(
                routine=routine,
                entry_banks=entry_banks,
                exit_banks=AuditBanks(
                    rom=memory[emu.symbols["hLoadedROMBank"]],
                    wram=(memory[0xFF70] & 7) or 1,
                    vram=memory[0xFF4F] & 1,
                ),
                entry_ie=ie,
                exit_ie=memory[0xFFFF],
                entry_if=interrupt_flags,
                exit_if=memory[0xFF0F],
                entry_sp=stack_pointer,
                exit_sp=registers.SP,
                a=registers.A,
                flags=registers.F,
            )
            memory[0xFFFF] = 0
            memory[HRAM_TRAMPOLINE + 4] = 0x76
            registers.PC = HRAM_TRAMPOLINE + 4

        emu.pyboy.hook_register(0, RETURN_TRAP, at_return, None)
        try:
            emu.pyboy.tick(1, render=False, sound=False)
        finally:
            emu.pyboy.hook_deregister(0, RETURN_TRAP)
        if not returned or observation is None:
            raise Phase2AuditError(f"{routine} did not return within one frame")
        if observation.exit_sp != stack_pointer + 2:
            raise Phase2AuditError(f"{routine} leaked stack space")
        guard = bytes(memory[STACK_GUARD_START + offset] for offset in range(len(STACK_GUARD)))
        if guard != STACK_GUARD:
            raise Phase2AuditError(f"{routine} exceeded the bounded stack pressure margin")
        if preserve_banks and observation.exit_banks != entry_banks:
            raise Phase2AuditError(f"{routine} leaked ROM/WRAM/VRAM bank state")
        if preserve_interrupts and (
            observation.exit_ie != ie or observation.exit_if != interrupt_flags
        ):
            raise Phase2AuditError(f"{routine} changed raw IE/IF state")
        self._calls.append(observation)
        return observation

    def _read_snapshot(
        self,
        *,
        protocol: int,
        checkpoint: int,
        sequence: int | None = None,
    ) -> Phase2AuditSnapshot:
        raw = self.emulator.read_bytes("wFullColorDebugCarrierStart", CARRIER_BYTES)
        return decode_phase2_audit_snapshot(
            raw,
            constants=self.constants,
            expected_protocol=protocol,
            expected_checkpoint=checkpoint,
            expected_sequence=sequence,
        )

    def command(
        self,
        name: str,
        *,
        entry_banks: AuditBanks = AuditBanks(rom=0x2D, wram=7, vram=1),
    ) -> tuple[AuditCallObservation, Phase2AuditSnapshot]:
        if name not in COMMAND_NAMES:
            raise Phase2AuditError(f"unknown audit command {name!r}")
        self.emulator.write(
            "wFullColorDebugCommandPhase2", self.constants[COMMAND_NAMES[name]]
        )
        call = self.invoke(
            "PollFullColorPhase2DebugCommand", entry_banks=entry_banks
        )
        snapshot = self._read_snapshot(
            protocol=PROTOCOL[name],
            checkpoint=self.constants[CHECKPOINT_NAMES[name]],
        )
        if (snapshot.entry_svbk & 7 or 1) != entry_banks.wram:
            raise Phase2AuditError("carrier recorded the wrong entry WRAM bank")
        if (snapshot.exit_svbk & 7 or 1) != entry_banks.wram:
            raise Phase2AuditError("carrier recorded the wrong exit WRAM bank")
        if snapshot.entry_ie != call.entry_ie or snapshot.exit_ie != call.exit_ie:
            raise Phase2AuditError("carrier/call interrupt evidence disagrees")
        if snapshot.entry_sp != snapshot.exit_sp:
            raise Phase2AuditError("audit command leaked stack within its selected seam")
        return call, snapshot

    def capture(
        self,
        action: Callable[["Phase2AuditHarness"], None] | None = None,
        *,
        entry_banks: AuditBanks = AuditBanks(rom=0x2D, wram=7, vram=1),
    ) -> Phase2ProtocolObservation:
        """Run CLEAR/ARM/action/SNAPSHOT/ACK and retain the atomic snapshot."""

        first_call = len(self._calls)
        _, clear = self.command("clear", entry_banks=entry_banks)
        if clear.sequence != 0:
            raise Phase2AuditError("CLEAR did not reset the sequence")
        _, armed = self.command("arm", entry_banks=entry_banks)
        if armed.sequence != 0:
            raise Phase2AuditError("ARM changed the snapshot sequence")
        if action is not None:
            action(self)
        _, snapshot = self.command("snapshot", entry_banks=entry_banks)
        if snapshot.sequence != 1:
            raise Phase2AuditError("first SNAPSHOT did not publish sequence one")
        party_pending = bool(self.emulator.read("wFullColorPartyReturnPending"))
        _, acknowledged = self.command("ack", entry_banks=entry_banks)
        if acknowledged.sequence != snapshot.sequence:
            raise Phase2AuditError("ACK changed the captured sequence")
        return Phase2ProtocolObservation(
            identity=self.identity,
            snapshot=snapshot,
            party_return_pending=party_pending,
            calls=tuple(self._calls[first_call:]),
        )
