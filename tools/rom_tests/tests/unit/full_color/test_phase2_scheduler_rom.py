"""Direct real-ROM tests for the guarded Phase 2 scheduler seams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re

import pytest

from tools.rom_tests.emulator import Emulator
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


def numeric_symbols(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\S+)", line)
        if match:
            result[match.group(2)] = int(match.group(1), 16)
    return result


@dataclass
class Phase2Rom:
    emulator: Emulator
    constants: dict[str, int]

    def call(self, name: str, *, a: int = 0, c: int = 0, hl: int = 0) -> tuple[int, int]:
        emu = self.emulator
        regs = emu.pyboy.register_file
        address = emu.symbols[name]
        bank = emu.symbol_banks[name]
        stack = 0xCFFE
        regs.A, regs.C, regs.HL, regs.SP = a, c, hl, stack
        emu.pyboy.memory[stack] = 0
        emu.pyboy.memory[stack + 1] = 1
        emu.pyboy.memory[0xFFFF] = 0
        if bank:
            emu.pyboy.memory[0x2000] = bank
        regs.PC = address
        returned = False

        def stop(_: object) -> None:
            nonlocal returned
            returned = True
            # Never use $ff80: that is the production OAM DMA routine.
            emu.pyboy.memory[0xC6F0] = 0x18
            emu.pyboy.memory[0xC6F1] = 0xFE
            regs.PC = 0xC6F0

        emu.pyboy.hook_register(0, 0x0100, stop, None)
        try:
            # A maximum 360-cell paired PREPARE/COMMIT is intentionally larger
            # than one emulated frame. Keep stepping until the return hook has
            # fired, with a small hard ceiling so a real ROM loop still fails.
            for _ in range(4):
                emu.pyboy.tick(1, render=False, sound=False)
                if returned:
                    break
        finally:
            emu.pyboy.hook_deregister(0, 0x0100)
        assert returned, f"{name} did not return (PC={regs.PC:#06x}, SP={regs.SP:#06x})"
        return regs.A, regs.F

    def write_fixed(self, address: int, data: bytes) -> None:
        for offset, value in enumerate(data):
            self.emulator.pyboy.memory[address + offset] = value

    def write_wram2(self, symbol: str, data: bytes | int) -> None:
        blob = bytes([data]) if isinstance(data, int) else data
        old = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            address = self.emulator.symbols[symbol]
            for offset, value in enumerate(blob):
                self.emulator.pyboy.memory[address + offset] = value
        finally:
            self.emulator.pyboy.memory[0xFF70] = old

    def read_wram2(self, symbol: str, size: int = 1) -> bytes:
        old = self.emulator.pyboy.memory[0xFF70]
        self.emulator.pyboy.memory[0xFF70] = 2
        try:
            address = self.emulator.symbols[symbol]
            return bytes(self.emulator.pyboy.memory[address + i] for i in range(size))
        finally:
            self.emulator.pyboy.memory[0xFF70] = old

    @property
    def generation(self) -> int:
        return int.from_bytes(self.read_wram2("wRendererGeneration", 4), "little")

    def activate(self) -> None:
        self.call("InitRendererOwnership")
        # Direct-call ROM tests bypass the game's boot copier. Install the exact
        # production DMA stub in its HRAM execution address before OAM tests.
        dma_stub = bytes((0x3E, 0xC3, 0xE0, 0x46, 0x3E, 0x28, 0x3D, 0x20, 0xFD, 0xC9))
        for offset, value in enumerate(dma_stub):
            self.emulator.pyboy.memory[0xFF80 + offset] = value
        self.write_wram2("wRendererOwner", self.constants["RENDERER_FULL_COLOR_OVERWORLD"])
        self.write_wram2("wRendererPhase", self.constants["OVERWORLD_ACTIVE"])
        self.write_wram2("wRendererAdmissionOpen", 1)
        self.call("InitFullColorScheduler")

    def descriptor(
        self,
        request_class: str,
        *,
        destination: int | None = None,
        source: int = 0xC900,
        desired: int | None = None,
        resources: int | None = None,
        extent: int | None = None,
        reservation: int | None = None,
        flags: int = 0,
        owner: str = "RENDERER_FULL_COLOR_OVERWORLD",
        generation: int | None = None,
    ) -> bytes:
        cls = self.constants[request_class]
        if request_class == "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD":
            defaults = (self.constants["FULL_COLOR_BG_PALETTE_DESTINATION"], 0, 1, 64, 64)
        elif request_class == "FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD":
            defaults = (self.constants["FULL_COLOR_OBJ_PALETTE_DESTINATION"], 0, 1, 64, 64)
        elif request_class == "FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA":
            defaults = (self.constants["FULL_COLOR_OAM_DESTINATION"], 0, 24, 160, 200)
        elif request_class == "FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT":
            defaults = (0x8000, 0x9800, 36, 17, 17)
        else:
            defaults = (0x9800, 0x0101, 6, 1, 2)
        destination, desired, resources, extent, reservation = (
            default if value is None else value
            for value, default in zip(
                (destination, desired, resources, extent, reservation), defaults, strict=True
            )
        )
        return b"".join((
            bytes([cls, self.constants[owner]]),
            (self.generation if generation is None else generation).to_bytes(4, "little"),
            destination.to_bytes(2, "little"), source.to_bytes(2, "little"),
            desired.to_bytes(2, "little"), resources.to_bytes(2, "little"),
            extent.to_bytes(2, "little"), reservation.to_bytes(2, "little"),
            bytes([flags, 0]),
        ))

    def admit(self, descriptor: bytes) -> tuple[int, int]:
        assert len(descriptor) == 20
        self.write_fixed(0xC700, descriptor)
        return self.call("AdmitFullColorRequest", hl=0xC700)


@pytest.fixture
def phase2_rom(request: pytest.FixtureRequest):
    rom = Path(os.environ.get("ROM_TEST_ROM", REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"))
    sym = Path(os.environ.get("ROM_TEST_SYMBOLS", REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"))
    emulator = Emulator(rom=rom, symbols=sym, results=result_directory(request.node.nodeid), cgb=True)
    instance = Phase2Rom(emulator, numeric_symbols(sym))
    try:
        instance.activate()
        yield instance
    finally:
        emulator.close()


def test_admission_coalescing_and_oam_noncoalescing(phase2_rom: Phase2Rom) -> None:
    bg = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD")
    assert phase2_rom.admit(bg)[0] == phase2_rom.constants["ACCEPTED"]
    assert phase2_rom.admit(bg)[0] == phase2_rom.constants["COALESCED"]
    oam = phase2_rom.descriptor("FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", desired=2)
    assert phase2_rom.admit(oam)[0] == phase2_rom.constants["ACCEPTED"]
    assert phase2_rom.admit(oam)[0] == phase2_rom.constants["ACCEPTED"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x03"


@pytest.mark.parametrize("mutated_offset", (13, 17))
def test_invalid_resident_cannot_absorb_and_strand_valid_retry(
    phase2_rom: Phase2Rom, mutated_offset: int
) -> None:
    payload = bytes((index * 3) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC900, payload)
    request = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD")
    assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]

    resident = bytearray(phase2_rom.read_wram2("wFullColorRequestDescriptors", 20))
    resident[mutated_offset] = 1  # high resource byte or reservation high byte
    phase2_rom.write_wram2("wFullColorRequestDescriptors", resident)

    assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x01"
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == payload
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_capacity_plus_one_defers_and_retry_is_observable(phase2_rom: Phase2Rom) -> None:
    for index in range(8):
        request = phase2_rom.descriptor(
            "FULL_COLOR_REQUEST_MAP_ROW_PAIRED", destination=0x9800 + index,
            desired=0x0101,
        )
        assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]
    ninth = phase2_rom.descriptor("FULL_COLOR_REQUEST_MAP_ROW_PAIRED", destination=0x9900)
    assert phase2_rom.admit(ninth)[0] == phase2_rom.constants["DEFERRED"]
    assert phase2_rom.read_wram2("wFullColorRetryCounter") == b"\x01"
    assert phase2_rom.read_wram2("wFullColorTimingState", 4) == bytes((
        8, 1, phase2_rom.constants["DEFERRED"], 8,
    ))
    phase2_rom.write_fixed(0xC900, b"\x55\x06")
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.admit(ninth)[0] == phase2_rom.constants["ACCEPTED"]


def test_retry_and_transition_counters_saturate_in_real_rom(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_wram2("wFullColorRetryCounter", 0xFF)
    phase2_rom.write_wram2("wRendererAdmissionOpen", 0)
    request = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD")
    assert phase2_rom.admit(request)[0] == phase2_rom.constants["DEFERRED"]
    assert phase2_rom.read_wram2("wFullColorRetryCounter") == b"\xff"
    assert phase2_rom.read_wram2("wFullColorTimingState", 2)[1] == 0xFF

    phase2_rom.write_wram2("wRendererAdmissionOpen", 1)
    phase2_rom.write_wram2("wFullColorTransitionCount", 0xFF)
    phase2_rom.write_wram2("wFullColorTransitionLog", b"sentinel")
    assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]
    assert phase2_rom.read_wram2("wFullColorTransitionCount") == b"\xff"
    assert phase2_rom.read_wram2("wFullColorTransitionLog", 8) == b"sentinel"


def test_ring_reuse_preserves_fifo_after_wrap(phase2_rom: Phase2Rom) -> None:
    for index in range(8):
        phase2_rom.write_fixed(0xC900 + index * 2, bytes((0x40 + index, index)))
        assert phase2_rom.admit(phase2_rom.descriptor(
            "FULL_COLOR_REQUEST_MAP_ROW_PAIRED", destination=0x9800 + index,
            source=0xC900 + index * 2, desired=0x100 + index + 1,
            extent=index + 1, reservation=(index + 1) * 2,
        ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    phase2_rom.write_fixed(0xC920, b"\x99\x07")
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_ROW_PAIRED", destination=0x9900, source=0xC920,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9801, 1) == b"\x41"
    assert phase2_rom.emulator.read_vram_bank(0, 0x9900, 1) != b"\x99"


def test_wrong_owner_and_stale_generation_reject_without_residency(phase2_rom: Phase2Rom) -> None:
    wrong = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", owner="RENDERER_YELLOW")
    assert phase2_rom.admit(wrong)[0] == phase2_rom.constants["REJECTED_WRONG_OWNER"]
    stale = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", generation=phase2_rom.generation + 1)
    assert phase2_rom.admit(stale)[0] == phase2_rom.constants["REJECTED_STALE_GENERATION"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_transition_order_and_generation_cancellation(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_fixed(0xC900, bytes(range(64)))
    request = phase2_rom.descriptor("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", resources=1, extent=64)
    assert phase2_rom.admit(request)[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.read_wram2("wFullColorTransitionLog", 4) == bytes(
        phase2_rom.constants[name] for name in ("PENDING", "PREPARED", "COMMITTING", "COMPLETE")
    )
    second = phase2_rom.descriptor("FULL_COLOR_REQUEST_MAP_ROW_PAIRED")
    assert phase2_rom.admit(second)[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("AdvanceRendererGeneration")
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\x00"


def test_resource_and_budget_revalidation_defer_before_committing(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_fixed(0xC900, bytes(range(64)))
    request = phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD",
    )
    phase2_rom.admit(request)
    phase2_rom.call("PrepareNextFullColorRequest")
    phase2_rom.write_wram2("wFullColorAvailableResources", b"\x00\x00")
    phase2_rom.write_wram2("wFullColorCommitBudget", b"\xff\xff")
    before = phase2_rom.emulator.read_palette_ram()
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == before
    assert phase2_rom.read_wram2("wFullColorTransitionLog", 2) == bytes(
        [phase2_rom.constants["PENDING"], phase2_rom.constants["PREPARED"]]
    )


def test_complete_bg_and_obj_palette_payloads_commit(phase2_rom: Phase2Rom) -> None:
    bg = bytes((index * 3) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC900, bg)
    phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC900,
    ))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == bg

    obj = bytes((index * 5) & 0x7F for index in range(64))
    phase2_rom.write_fixed(0xC940, obj)
    phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD", source=0xC940, desired=2,
        resources=1,
    ))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram(object_palettes=True) == obj


def test_paired_transfer_commits_whole_tiles_and_attributes(phase2_rom: Phase2Rom) -> None:
    tiles = bytes([0x11, 0x22, 0x33, 0x44])
    attributes = bytes([0x1F, 0x92, 0xE7, 0x10])
    phase2_rom.write_fixed(0xC900, tiles + attributes)
    phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_ROW_PAIRED", source=0xC900, desired=0x0104, extent=4, reservation=8,
    ))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9800, 4) == tiles
    assert phase2_rom.emulator.read_vram_bank(1, 0x9800, 4) == bytes(value & 0xEF for value in attributes)


def test_overlay_is_independent_of_vram_or_ambient_map_oracle(phase2_rom: Phase2Rom) -> None:
    tiles = bytes([0x08, 0x19, 0x2A, 0x3B])
    phase2_rom.write_fixed(0xC900, tiles + b"ambient-not-consumed")
    for bank, fill in ((0, 0xA5), (1, 0x5A)):
        old = phase2_rom.emulator.pyboy.memory[0xFF4F]
        phase2_rom.emulator.pyboy.memory[0xFF4F] = bank
        for offset in range(4):
            phase2_rom.emulator.pyboy.memory[0x9800 + offset] = fill
        phase2_rom.emulator.pyboy.memory[0xFF4F] = old
    phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED", source=0xC900, desired=0x0104, extent=4, reservation=8,
    ))
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_vram_bank(0, 0x9800, 4) == tiles
    assert phase2_rom.emulator.read_vram_bank(1, 0x9800, 4) == bytes(value & 7 for value in tiles)


def test_oam_preparation_maps_final_identity_with_palette_zero_fallback(phase2_rom: Phase2Rom) -> None:
    batch = bytearray(160)
    for index in range(40):
        batch[index * 4 + 3] = 0xF8 | (index & 7)
    identities = bytes([3, 0xFF, 9, 0x80] + [0] * 36)
    phase2_rom.write_fixed(0xC900, bytes(batch) + identities)
    phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", source=0xC900,
    ))
    phase2_rom.call("PrepareNextFullColorRequest")
    mapped = phase2_rom.read_wram2("wFullColorShadowOAMBatch", 16)
    assert mapped[3] == 0xFB
    assert mapped[7] == 0xF8
    assert mapped[11] == 0xF8
    assert mapped[15] == 0xF8


def test_prepared_scratch_cannot_be_overwritten_by_a_second_request(phase2_rom: Phase2Rom) -> None:
    first, second = bytes(range(64)), bytes(reversed(range(64)))
    phase2_rom.write_fixed(0xC900, first)
    phase2_rom.write_fixed(0xC940, second)
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC900, desired=1,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    assert phase2_rom.admit(phase2_rom.descriptor(
        "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", source=0xC940, desired=2,
    ))[0] == phase2_rom.constants["ACCEPTED"]
    before = phase2_rom.read_wram2("wFullColorBGPaletteBase", 64)
    phase2_rom.call("PrepareNextFullColorRequest")
    assert phase2_rom.read_wram2("wFullColorBGPaletteBase", 64) == before == first
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == first
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.emulator.read_palette_ram() == second


@pytest.mark.parametrize(
    ("request_class", "changes"),
    (
        ("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", {"extent": 1}),
        ("FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD", {"reservation": 1}),
        ("FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", {"extent": 1}),
        ("FULL_COLOR_REQUEST_MAP_ROW_PAIRED", {"reservation": 1}),
        ("FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED", {"desired": 0x0201, "extent": 1}),
        ("FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED", {"desired": 0x0202, "extent": 1}),
        ("FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED", {"reservation": 1}),
        ("FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED", {"extent": 2}),
        ("FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT", {"reservation": 1}),
    ),
)
def test_each_class_rejects_false_extent_or_reservation(
    phase2_rom: Phase2Rom, request_class: str, changes: dict[str, int]
) -> None:
    result, _ = phase2_rom.admit(phase2_rom.descriptor(request_class, **changes))
    assert result == phase2_rom.constants["DEFERRED"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\0"


@pytest.mark.parametrize(
    ("request_class", "resources", "reservation"),
    (
        ("FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", 1, 64),
        ("FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD", 1, 64),
        ("FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA", 24, 200),
        ("FULL_COLOR_REQUEST_MAP_ROW_PAIRED", 6, 2),
        ("FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED", 6, 2),
        ("FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED", 6, 2),
        ("FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED", 6, 2),
        ("FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED", 6, 2),
        ("FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT", 36, 17),
    ),
)
def test_every_class_rejects_high_resource_bits_and_reservation_plus_one(
    phase2_rom: Phase2Rom, request_class: str, resources: int, reservation: int
) -> None:
    high_mask = phase2_rom.descriptor(request_class, resources=resources | 0x100)
    assert phase2_rom.admit(high_mask)[0] == phase2_rom.constants["DEFERRED"]
    plus_one = phase2_rom.descriptor(request_class, reservation=reservation + 1)
    assert phase2_rom.admit(plus_one)[0] == phase2_rom.constants["DEFERRED"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\0"


def test_destination_is_validated_at_admission_and_again_before_commit(phase2_rom: Phase2Rom) -> None:
    phase2_rom.write_fixed(0xC900, b"\x41\x06")
    bad = phase2_rom.descriptor("FULL_COLOR_REQUEST_MAP_ROW_PAIRED", destination=0xD000)
    assert phase2_rom.admit(bad)[0] == phase2_rom.constants["DEFERRED"]
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\0"

    good = phase2_rom.descriptor("FULL_COLOR_REQUEST_MAP_ROW_PAIRED")
    assert phase2_rom.admit(good)[0] == phase2_rom.constants["ACCEPTED"]
    phase2_rom.call("PrepareNextFullColorRequest")
    descriptors = bytearray(phase2_rom.read_wram2("wFullColorRequestDescriptors", 20))
    descriptors[6:8] = (0xD000).to_bytes(2, "little")
    phase2_rom.write_wram2("wFullColorRequestDescriptors", descriptors)
    sentinel = phase2_rom.read_wram2("wRendererOwner")
    phase2_rom.call("RunFullColorOwnershipVBlank")
    assert phase2_rom.read_wram2("wRendererOwner") == sentinel
    assert phase2_rom.read_wram2("wFullColorRequestCount") == b"\0"


def test_rom_byte_mutation_of_validator_trips_a_useful_contract(tmp_path: Path) -> None:
    source_rom = REPOSITORY_ROOT / "pokeyellow_phase2_audit.gbc"
    source_sym = REPOSITORY_ROOT / "pokeyellow_phase2_audit.sym"
    symbols = numeric_symbols(source_sym)
    probe = Emulator(rom=source_rom, symbols=source_sym, results=tmp_path / "probe", cgb=True)
    try:
        address = probe.symbols["ValidateFullColorRequestResourcesSelected"]
        bank = probe.symbol_banks["ValidateFullColorRequestResourcesSelected"]
    finally:
        probe.close()
    blob = bytearray(source_rom.read_bytes())
    offset = bank * 0x4000 + address - 0x4000
    blob[offset:offset + 2] = b"\xa7\xc9"  # and a; ret -- bypass validation
    mutant_rom = tmp_path / "mutant.gbc"
    mutant_rom.write_bytes(blob)
    emulator = Emulator(rom=mutant_rom, symbols=source_sym, results=tmp_path / "mutant", cgb=True)
    mutant = Phase2Rom(emulator, symbols)
    try:
        mutant.activate()
        with pytest.raises(AssertionError, match="exact palette extent"):
            result = mutant.admit(mutant.descriptor(
                "FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD", extent=1,
            ))[0]
            assert result != mutant.constants["ACCEPTED"], "exact palette extent mutation escaped"
    finally:
        emulator.close()
