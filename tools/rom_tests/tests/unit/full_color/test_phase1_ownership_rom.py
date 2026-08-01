"""Real-ROM checks for the Phase 1 ownership core.

The adapter in this module is intentionally the only place that knows the
temporary callable-ROM test mechanism.  Milestone 3's mailbox must not be
pulled forward merely to test Milestone 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.full_color.enums import CancellationReason, JobState, Owner, Phase
from tools.rom_tests.full_color.model import (
    PHASE1_MAX_GENERATION,
    Phase1Action,
    Phase1ActionKind,
    Phase1OwnershipModel,
    Phase1State,
    generated_phase1_actions,
)
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


STATE_SYMBOLS = (
    "wRendererOwner",
    "wRendererPhase",
    "wRendererGeneration",
    "wRendererAdmissionOpen",
    "wRendererJobState",
    "wRendererJobGeneration",
    "wRendererJobCancellationReason",
)
PUBLIC_ROUTINES = (
    "InitRendererOwnership",
    "ResetRendererOwnership",
    "BeginRendererHandoff",
    "CompleteRendererHandoff",
    "SelectYellowRenderer",
    "SelectFullColorOwnerForDiagnostic",
    "ActivateFullColorOwnerForDiagnostic",
    "AdvanceRendererGeneration",
    "AdmitRendererDiagnosticJob",
    "SetRendererJobPrepared",
    "SetRendererJobCommitting",
    "CompleteRendererJob",
    "CancelRendererJob",
    "AssertRendererWriteAllowed",
    "GetRendererOwner",
    "RunFullColorOwnershipVBlank",
    "RouteRendererOwnershipVBlank",
)


def _numeric_symbols(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            values[match.group(2)] = int(match.group(1), 16)
    return values


@dataclass(frozen=True, slots=True)
class Phase1CallObservation:
    """Machine state observed at the real production RET boundary."""

    a: int
    flags: int
    program_counter: int
    stack_pointer: int
    rsvbk: int
    rvbk: int
    interrupt_enable: int
    interrupt_flags: int
    ownership_state: bytes
    visible_resources: tuple[bytes, ...] | None


@dataclass(slots=True)
class Phase1Rom:
    emulator: Emulator
    constants: dict[str, int]

    @classmethod
    def require(cls, emulator: Emulator, symbols_path: Path) -> "Phase1Rom":
        missing = sorted(set(STATE_SYMBOLS + PUBLIC_ROUTINES) - emulator.symbols.keys())
        assert not missing, "debug ROM is missing Phase 1 ownership ABI: " + ", ".join(
            missing
        )
        wrong_banks = [
            name for name in STATE_SYMBOLS if emulator.symbol_banks[name] != 2
        ]
        assert not wrong_banks, f"Phase 1 state must be in WRAMX bank 2: {wrong_banks}"
        start = emulator.symbols["wRendererOwner"]
        expected_offsets = {
            "wRendererOwner": 0,
            "wRendererPhase": 1,
            "wRendererGeneration": 2,
            "wRendererAdmissionOpen": 6,
            "wRendererJobState": 7,
            "wRendererJobGeneration": 8,
            "wRendererJobCancellationReason": 12,
        }
        actual_offsets = {
            name: emulator.symbols[name] - start for name in STATE_SYMBOLS
        }
        assert actual_offsets == expected_offsets, (
            "Phase 1 ownership state must be the measured contiguous 13-byte ABI"
        )
        constants = _numeric_symbols(symbols_path)
        required_constants = {
            member.value
            for enum_type in (Owner, Phase, JobState, CancellationReason)
            for member in enum_type
        }
        missing_constants = sorted(required_constants - constants.keys())
        assert not missing_constants, (
            "debug symbol file must export symbolic Phase 1 encodings: "
            + ", ".join(missing_constants)
        )
        return cls(emulator, constants)

    def wait_for_hard_boot(self, max_frames: int = 180) -> None:
        for _ in range(max_frames):
            self.emulator.tick()
            if self.generation == 1 and self.owner is Owner.RENDERER_YELLOW:
                return
        raise AssertionError("hard boot did not initialize Phase 1 ownership")

    @property
    def owner(self) -> Owner:
        return self._decode(Owner, self.emulator.read("wRendererOwner"))

    @property
    def phase(self) -> Phase:
        return self._decode(Phase, self.emulator.read("wRendererPhase"))

    @property
    def generation(self) -> int:
        return int.from_bytes(
            self.emulator.read_bytes("wRendererGeneration", 4), "little"
        )

    @property
    def job_generation(self) -> int:
        return int.from_bytes(
            self.emulator.read_bytes("wRendererJobGeneration", 4), "little"
        )

    @property
    def admission_open(self) -> bool:
        return bool(self.emulator.read("wRendererAdmissionOpen"))

    @property
    def job_state(self) -> JobState | None:
        value = self.emulator.read("wRendererJobState")
        if value == self.constants["RENDERER_JOB_NONE"]:
            return None
        return self._decode(JobState, value)

    @property
    def cancellation_reason(self) -> CancellationReason | None:
        value = self.emulator.read("wRendererJobCancellationReason")
        if value == self.constants["CANCELLATION_NONE"]:
            return None
        return self._decode(CancellationReason, value)

    def snapshot(self) -> Phase1State:
        job_state = self.job_state
        return Phase1State(
            owner=self.owner,
            phase=self.phase,
            generation=self.generation,
            admission_open=self.admission_open,
            job_state=job_state,
            job_generation=None if job_state is None else self.job_generation,
            cancellation_reason=self.cancellation_reason,
            generation_exhausted=self.generation == 0,
        )

    def _decode(self, enum_type: type[Owner] | type[Phase] | type[JobState] | type[CancellationReason], value: int):
        for member in enum_type:
            if self.constants[member.value] == value:
                return member
        raise AssertionError(f"unknown {enum_type.__name__} encoding {value:#04x}")

    def call(
        self,
        routine: str,
        *,
        a: int = 0,
        c: int = 0,
        capture_visible: bool = False,
    ) -> Phase1CallObservation:
        """Call a production routine without a debug mailbox.

        Inputs use A/C because the far-call convention owns B.  A fixed-bank
        return trap aborts the emulator tick immediately after RET.
        """
        emulator = self.emulator
        checkpoint = BytesIO()
        emulator.pyboy.save_state(checkpoint)
        bank = emulator.symbol_banks[routine]
        address = emulator.symbols[routine]
        return_address = 0x0100
        register_file = emulator.pyboy.register_file
        register_file.A = a
        register_file.C = c
        register_file.SP = 0xFFFC
        emulator.pyboy.memory[0xFFFC] = return_address & 0xFF
        emulator.pyboy.memory[0xFFFD] = return_address >> 8
        if bank:
            emulator.pyboy.memory[0x2000] = bank & 0xFF
            emulator.pyboy.memory[0x3000] = bank >> 8
        register_file.PC = address
        returned_to_host = False
        observation: Phase1CallObservation | None = None

        def returned(_: object) -> None:
            nonlocal observation, returned_to_host
            returned_to_host = True
            observation = Phase1CallObservation(
                a=register_file.A,
                flags=register_file.F,
                program_counter=register_file.PC,
                stack_pointer=register_file.SP,
                rsvbk=emulator.pyboy.memory[0xFF70],
                rvbk=emulator.pyboy.memory[0xFF4F],
                interrupt_enable=emulator.pyboy.memory[0xFFFF],
                interrupt_flags=emulator.pyboy.memory[0xFF0F],
                ownership_state=self.ownership_state(),
                visible_resources=(
                    self.visible_resources() if capture_visible else None
                ),
            )
            emulator.pyboy.memory[0xFFFF] = 0
            emulator.pyboy.memory[0xFF80] = 0x76
            register_file.PC = 0xFF80

        emulator.pyboy.hook_register(0, return_address, returned, None)
        try:
            emulator.pyboy.tick(1, render=False, sound=False)
        finally:
            emulator.pyboy.hook_deregister(0, return_address)
        assert returned_to_host, f"{routine} did not return within one frame"
        assert observation is not None
        assert observation.program_counter == return_address
        assert observation.stack_pointer == 0xFFFE
        checkpoint.seek(0)
        emulator.pyboy.load_state(checkpoint)
        self.write_ownership_state(observation.ownership_state)
        return observation

    def write_state(self, symbol: str, value: int, size: int = 1) -> None:
        blob = value.to_bytes(size, "little")
        address = self.emulator.symbols[symbol]
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            for offset, byte in enumerate(blob):
                self.emulator.pyboy.memory[address + offset] = byte
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def write_ownership_state(self, state: bytes) -> None:
        assert len(state) == 13
        address = self.emulator.symbols["wRendererOwner"]
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            for offset, byte in enumerate(state):
                self.emulator.pyboy.memory[address + offset] = byte
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior

    def apply(self, action: Phase1Action) -> None:
        if action.kind is Phase1ActionKind.HARD_BOOT:
            return
        calls: tuple[tuple[str, int], ...]
        if action.kind is Phase1ActionKind.RESET:
            calls = (("ResetRendererOwnership", 0),)
        elif action.kind is Phase1ActionKind.HANDOFF_TO_OVERWORLD:
            calls = (
                ("BeginRendererHandoff", self.constants["HANDOFF_TO_OVERWORLD"]),
                ("SelectFullColorOwnerForDiagnostic", 0),
            )
        elif action.kind is Phase1ActionKind.ACTIVATE_OVERWORLD:
            calls = (("ActivateFullColorOwnerForDiagnostic", 0),)
        elif action.kind is Phase1ActionKind.HANDOFF_TO_YELLOW:
            calls = (
                ("BeginRendererHandoff", self.constants["HANDOFF_TO_YELLOW"]),
                ("SelectYellowRenderer", 0),
            )
        elif action.kind is Phase1ActionKind.ADMIT_JOB:
            calls = (("AdmitRendererDiagnosticJob", 0),)
        elif action.kind is Phase1ActionKind.PREPARE_JOB:
            calls = (("SetRendererJobPrepared", 0),)
        elif action.kind is Phase1ActionKind.BEGIN_COMMIT:
            calls = (("SetRendererJobCommitting", 0),)
        elif action.kind is Phase1ActionKind.COMPLETE_JOB:
            calls = (("CompleteRendererJob", 0),)
        elif action.kind is Phase1ActionKind.CANCEL_SUPERSEDED:
            calls = (("CancelRendererJob", self.constants["SUPERSEDED"]),)
        elif action.kind is Phase1ActionKind.ADVANCE_GENERATION:
            calls = (("AdvanceRendererGeneration", 0),)
        else:  # pragma: no cover - exhaustive Phase1ActionKind mapping
            raise AssertionError(f"unsupported Phase 1 ROM action: {action.kind}")
        for routine, a in calls:
            observation = self.call(routine, a=a)
            assert not observation.flags & 0x10, (
                f"{routine} rejected legal action {action.kind.value}"
            )

    def visible_resources(self) -> tuple[bytes, ...]:
        emulator = self.emulator
        shadow_oam = (
            emulator.read_bytes("wShadowOAM", 160)
            if "wShadowOAM" in emulator.symbols
            else b""
        )
        return (
            emulator.read_vram_bank(0, 0x8000, 0x2000),
            emulator.read_vram_bank(1, 0x8000, 0x2000),
            emulator.read_palette_ram(),
            emulator.read_palette_ram(object_palettes=True),
            emulator.read_memory(0xFE00, 160),
            shadow_oam,
        )

    def ownership_state(self) -> bytes:
        address = self.emulator.symbols["wRendererOwner"]
        prior = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            return bytes(
                self.emulator.pyboy.memory[address + offset] for offset in range(13)
            )
        finally:
            self.emulator.pyboy.memory[0xFF70] = prior


@pytest.fixture
def phase1_rom(request: pytest.FixtureRequest) -> Phase1Rom:
    rom_path = Path(os.environ.get("ROM_TEST_ROM", REPOSITORY_ROOT / "pokeyellow_debug.gbc"))
    symbols_path = Path(
        os.environ.get("ROM_TEST_SYMBOLS", REPOSITORY_ROOT / "pokeyellow_debug.sym")
    )
    emulator = Emulator(
        rom=rom_path,
        symbols=symbols_path,
        results=result_directory(request.node.nodeid),
        cgb=True,
    )
    try:
        yield Phase1Rom.require(emulator, symbols_path)
    finally:
        emulator.close()


def test_hard_boot_matches_reference_model(phase1_rom: Phase1Rom) -> None:
    phase1_rom.wait_for_hard_boot()
    model = Phase1OwnershipModel()
    model.hard_boot()

    assert phase1_rom.owner is model.owner
    assert phase1_rom.phase is model.phase
    assert phase1_rom.generation == model.generation
    assert phase1_rom.emulator.read("wRendererAdmissionOpen") == model.admission_open
    assert phase1_rom.job_generation == 0


def test_reset_uses_fresh_generation_and_clears_diagnostic_slot(
    phase1_rom: Phase1Rom,
) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state("wRendererJobState", phase1_rom.constants["PREPARED"])
    phase1_rom.write_state("wRendererJobGeneration", phase1_rom.generation, 4)
    visible_before = phase1_rom.visible_resources()

    observation = phase1_rom.call(
        "ResetRendererOwnership", capture_visible=True
    )

    assert phase1_rom.owner is Owner.RENDERER_YELLOW
    assert phase1_rom.phase is Phase.YELLOW_ACTIVE
    assert phase1_rom.generation == 2
    assert phase1_rom.emulator.read("wRendererAdmissionOpen") == 1
    assert phase1_rom.job_generation == 0
    assert observation.visible_resources == visible_before


def test_cancellation_records_one_reason_and_generation(
    phase1_rom: Phase1Rom,
) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state("wRendererJobState", phase1_rom.constants["PREPARED"])
    phase1_rom.write_state("wRendererJobGeneration", phase1_rom.generation, 4)
    visible_before = phase1_rom.visible_resources()

    observation = phase1_rom.call(
        "CancelRendererJob",
        a=phase1_rom.constants[CancellationReason.SUPERSEDED.value],
        capture_visible=True,
    )

    assert phase1_rom.emulator.read("wRendererJobState") == phase1_rom.constants[
        "CANCELLED"
    ]
    assert phase1_rom.emulator.read(
        "wRendererJobCancellationReason"
    ) == phase1_rom.constants["SUPERSEDED"]
    assert phase1_rom.job_generation == phase1_rom.generation
    assert observation.visible_resources == visible_before


def test_generation_carry_is_little_endian(phase1_rom: Phase1Rom) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state("wRendererGeneration", 0xFF, 4)
    phase1_rom.call("AdvanceRendererGeneration")
    assert phase1_rom.generation == 0x100


def test_generation_exhaustion_fails_closed(phase1_rom: Phase1Rom) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state("wRendererGeneration", PHASE1_MAX_GENERATION, 4)
    phase1_rom.write_state("wRendererAdmissionOpen", 1)
    observation = phase1_rom.call("AdvanceRendererGeneration")
    assert observation.flags & 0x10  # SM83 carry flag
    assert phase1_rom.generation == 0
    assert phase1_rom.emulator.read("wRendererAdmissionOpen") == 0


def test_exhausted_handoff_completion_stays_closed(phase1_rom: Phase1Rom) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state(
        "wRendererPhase", phase1_rom.constants["HANDOFF_TO_OVERWORLD"]
    )
    phase1_rom.write_state("wRendererGeneration", 0, 4)
    phase1_rom.write_state("wRendererAdmissionOpen", 0)
    before = phase1_rom.ownership_state()

    observation = phase1_rom.call("SelectFullColorOwnerForDiagnostic")

    assert observation.flags & 0x10
    assert phase1_rom.ownership_state() == before
    assert phase1_rom.emulator.read("wRendererAdmissionOpen") == 0


def test_overworld_arrival_stays_closed_until_explicit_activation(
    phase1_rom: Phase1Rom,
) -> None:
    phase1_rom.wait_for_hard_boot()
    visible_before = phase1_rom.visible_resources()

    phase1_rom.call(
        "BeginRendererHandoff", a=phase1_rom.constants["HANDOFF_TO_OVERWORLD"]
    )
    phase1_rom.call("SelectFullColorOwnerForDiagnostic")

    assert phase1_rom.owner is Owner.RENDERER_FULL_COLOR_OVERWORLD
    assert phase1_rom.phase is Phase.OVERWORLD_RECONSTRUCTING
    assert not phase1_rom.admission_open
    before_rejection = phase1_rom.ownership_state()
    observation = phase1_rom.call("AdmitRendererDiagnosticJob")
    assert observation.flags & 0x10
    assert phase1_rom.ownership_state() == before_rejection

    observation = phase1_rom.call(
        "BeginRendererHandoff", a=phase1_rom.constants["HANDOFF_TO_YELLOW"]
    )
    assert observation.flags & 0x10
    assert phase1_rom.ownership_state() == before_rejection

    activation = phase1_rom.call(
        "ActivateFullColorOwnerForDiagnostic", capture_visible=True
    )
    assert phase1_rom.phase is Phase.OVERWORLD_ACTIVE
    assert phase1_rom.admission_open
    assert activation.visible_resources == visible_before


@pytest.mark.parametrize("seed", range(32))
def test_seeded_phase1_model_matches_real_debug_rom_after_every_action(
    phase1_rom: Phase1Rom, seed: int
) -> None:
    phase1_rom.wait_for_hard_boot()
    model = Phase1OwnershipModel()

    for index, action in enumerate(generated_phase1_actions(seed, 64)):
        model.apply(action)
        phase1_rom.apply(action)
        assert phase1_rom.snapshot() == model.snapshot(), (
            f"seed {seed} diverged at action {index}: {action.kind.value}"
        )


@pytest.mark.parametrize(
    ("owner", "handoff_phase", "routine"),
    [
        (
            Owner.RENDERER_YELLOW,
            Phase.HANDOFF_TO_OVERWORLD,
            "SelectYellowRenderer",
        ),
        (
            Owner.RENDERER_FULL_COLOR_OVERWORLD,
            Phase.HANDOFF_TO_YELLOW,
            "SelectFullColorOwnerForDiagnostic",
        ),
    ],
)
def test_wrong_direction_completion_fails_without_state_corruption(
    phase1_rom: Phase1Rom,
    owner: Owner,
    handoff_phase: Phase,
    routine: str,
) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.write_state("wRendererOwner", phase1_rom.constants[owner.value])
    phase1_rom.write_state("wRendererPhase", phase1_rom.constants[handoff_phase.value])
    phase1_rom.write_state("wRendererAdmissionOpen", 0)
    before = phase1_rom.ownership_state()

    observation = phase1_rom.call(routine)

    assert observation.flags & 0x10
    assert phase1_rom.ownership_state() == before


@pytest.mark.parametrize("entry_bank", range(1, 8))
@pytest.mark.parametrize("routine", PUBLIC_ROUTINES)
def test_every_ownership_entry_restores_wram_bank(
    phase1_rom: Phase1Rom, entry_bank: int, routine: str
) -> None:
    phase1_rom.wait_for_hard_boot()
    phase1_rom.emulator.pyboy.memory[0xFF70] = entry_bank
    raw_entry_bank = phase1_rom.emulator.pyboy.memory[0xFF70]
    entry_vram_bank = phase1_rom.emulator.pyboy.memory[0xFF4F]
    entry_ie = phase1_rom.emulator.pyboy.memory[0xFFFF]
    entry_if = phase1_rom.emulator.pyboy.memory[0xFF0F]

    observation = phase1_rom.call(routine)

    assert observation.rsvbk == raw_entry_bank
    assert observation.rvbk == entry_vram_bank
    assert observation.interrupt_enable == entry_ie
    assert observation.interrupt_flags == entry_if


@pytest.mark.parametrize("routine", PUBLIC_ROUTINES)
def test_phase1_core_never_changes_visible_resources(
    phase1_rom: Phase1Rom, routine: str
) -> None:
    phase1_rom.wait_for_hard_boot()
    before = phase1_rom.visible_resources()

    observation = phase1_rom.call(routine, capture_visible=True)

    assert observation.visible_resources == before
