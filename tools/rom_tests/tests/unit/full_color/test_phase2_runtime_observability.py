"""Contract and real-product checks for Phase 2 runtime observations."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.rom_tests.full_color.phase2_runtime_observability import (
    OVERWORLD_ACTIVE,
    PHASE2_CARRIER_BYTES,
    PHASE2_HEADER_BYTES,
    PHASE2_RECORD_BYTES,
    PHASE2_RECORD_CAPACITY,
    PHASE2_NONOVERLAY_TRACE_MAGIC,
    RENDERER_FULL_COLOR_OVERWORLD,
    Phase2RuntimeError,
    _require_complete_observation_abi,
    decode_phase2_observation_regions,
    decode_phase2_carrier,
    probe_release_oam_fallbacks,
    require_committed_guarded_audit,
    validate_hostile_records,
)
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


def _record(
    kind: int,
    *,
    checkpoint: int = 1,
    owner: int = RENDERER_FULL_COLOR_OVERWORLD,
    phase: int = OVERWORLD_ACTIVE,
    generation: int = 2,
    rom: int = 0x2D,
    wram: int = 7,
    vram: int = 1,
    ie: int = 0x15,
    interrupt_flags: int = 0x1A,
    payload: bytes = bytes(19),
) -> bytes:
    assert len(payload) == 19
    return b"".join((
        bytes((kind, checkpoint, owner, phase)),
        generation.to_bytes(4, "little"),
        bytes((rom, wram, vram, ie, interrupt_flags)),
        payload,
    ))


def _carrier(records: tuple[bytes, ...], *, version: int = 1) -> bytearray:
    assert len(records) <= PHASE2_RECORD_CAPACITY
    raw = bytearray(PHASE2_CARRIER_BYTES)
    raw[:16] = b"".join((
        b"FCP2",
        bytes((version, PHASE2_RECORD_BYTES, PHASE2_RECORD_CAPACITY, len(records))),
        (1).to_bytes(2, "little"),
        bytes((1, 0)),
        bytes((0, 0, len(records) % PHASE2_RECORD_CAPACITY, 0)),
    ))
    for index, record in enumerate(records):
        start = PHASE2_HEADER_BYTES + index * PHASE2_RECORD_BYTES
        raw[start : start + PHASE2_RECORD_BYTES] = record
    return raw


def _timing_payload(
    *, event: int = 1, sequence: int = 7, timing_flags: int = 1,
) -> bytes:
    payload = bytearray(19)
    payload[9] = 1
    payload[10] = event
    payload[11:13] = sequence.to_bytes(2, "little")
    payload[13:17] = bytes((20, 30, 21, 40))
    payload[17] = timing_flags
    return bytes(payload)


def test_fcp2_v1_decodes_strict_records_and_independent_timing() -> None:
    records = tuple(_record(1, checkpoint=index + 1) for index in range(5)) + (
        _record(1, checkpoint=6, payload=_timing_payload()),
    )
    decoded = decode_phase2_carrier(bytes(_carrier(records)))
    assert decoded.sequence == 1
    assert [record.kind for record in decoded.records] == ["checkpoint"] * 6
    timing = decoded.records[-1].timing
    assert timing is not None
    assert timing.sequence == 7
    assert timing.requires_sameboy_authority
    validate_hostile_records(decoded)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda raw: raw.__setitem__(0, 0), "magic"),
        (lambda raw: raw.__setitem__(4, 2), "version"),
        (lambda raw: raw.__setitem__(5, 31), "record layout"),
        (lambda raw: raw.__setitem__(7, 9), "exceeds capacity"),
        (lambda raw: raw.__setitem__(15, 1), "header reserved"),
        (lambda raw: raw.__setitem__(PHASE2_HEADER_BYTES, 0xFF), "unknown.*kind"),
        (lambda raw: raw.__setitem__(PHASE2_HEADER_BYTES + 2, 9), "unknown.*owner"),
        (lambda raw: raw.__setitem__(PHASE2_HEADER_BYTES + 8, 0), "default ROM/WRAM"),
        (
            lambda raw: raw.__setitem__(PHASE2_HEADER_BYTES + PHASE2_RECORD_BYTES, 1),
            "unused.*non-zero",
        ),
        (lambda raw: raw.__setitem__(-1, 1), "reserved tail"),
    ),
)
def test_malformed_fcp2_carrier_fails_closed(mutate, message: str) -> None:
    raw = _carrier((_record(1),))
    mutate(raw)
    with pytest.raises(Phase2RuntimeError, match=message):
        decode_phase2_carrier(bytes(raw))


def test_timing_reserved_bytes_and_equation_fail_independently() -> None:
    payload = bytearray(_timing_payload())
    payload[-1] = 1
    with pytest.raises(Phase2RuntimeError, match="record reserved"):
        decode_phase2_carrier(bytes(_carrier((_record(1, payload=bytes(payload)),))))

    records = tuple(_record(1, checkpoint=index + 1) for index in range(5)) + (
        _record(1, payload=_timing_payload(timing_flags=0)),
    )
    decoded = decode_phase2_carrier(bytes(_carrier(records)))
    with pytest.raises(Phase2RuntimeError, match="SameBoy cycle authority"):
        validate_hostile_records(decoded)


def test_pressure_and_five_active_frames_are_required() -> None:
    records = tuple(_record(1, checkpoint=index + 1) for index in range(5))
    no_interrupts = replace(
        decode_phase2_carrier(bytes(_carrier(records))),
        records=tuple(replace(record, ie=0, interrupt_flags=0) for record in decode_phase2_carrier(bytes(_carrier(records))).records),
    )
    with pytest.raises(Phase2RuntimeError, match="interrupt pressure"):
        validate_hostile_records(no_interrupts)
    with pytest.raises(Phase2RuntimeError, match="five OVERWORLD_ACTIVE"):
        validate_hostile_records(decode_phase2_carrier(bytes(_carrier(records[:4]))))


def test_full_ring_decodes_oldest_to_newest_and_capture_gaps_fail() -> None:
    records = tuple(_record(1, checkpoint=index) for index in range(8))
    raw = _carrier(records)
    raw[14] = 3  # next write slot, therefore slot 3 is the oldest retained row
    decoded = decode_phase2_carrier(bytes(raw))
    assert [item.checkpoint for item in decoded.records] == [3, 4, 5, 6, 7, 0, 1, 2]

    first = replace(decoded, sequence=1, records=(decoded.records[-1],))
    third = replace(decoded, sequence=3, records=(decoded.records[-2],))
    with pytest.raises(Phase2RuntimeError, match="sequence.*gap"):
        validate_hostile_records((first, third))


def test_carrier_only_debug_product_fails_closed_with_exact_bundle_blocker() -> None:
    class CarrierOnlyEmulator:
        symbols = {
            "wFullColorPhase2RuntimeCarrierStart": 0xA000,
            "wFullColorPhase2RuntimeCarrierEnd": 0xA120,
        }

    with pytest.raises(Phase2RuntimeError, match=(
        "production observation ABI is incomplete.*"
        "SemanticSnapshot/WriterTrace/BankTorture.*"
        "14-case diagnostic overlay matrix"
    )):
        _require_complete_observation_abi(CarrierOnlyEmulator())


def _observation_regions(*, case_id: int = 0, flags: int = 0):
    semantic = bytearray(64)
    semantic[:23] = b"".join((
        b"FCO2", bytes((2, 64, case_id, 3, flags)),
        (case_id + 1).to_bytes(2, "little"),
        bytes((case_id, case_id + 1, 1, 0xEF, 0, 0, 0, 1, 0xEF, 0, 0, 0)),
    ))
    semantic[35:41] = bytes((1, 3, 2, 0, 0, 0))
    trace = bytearray(64)
    trace[0] = 2
    trace[1:3] = bytes((1, 2))
    boundary = bytearray(32)
    row = (0x2D).to_bytes(2, "little") + bytes((7, 1, 0x15, 0x1A, 1, 3)) + (2).to_bytes(4, "little") + bytes(4)
    boundary[:16] = row
    boundary[16:] = row
    common = dict(
        bg_tile_ids=bytes(2048), bg_attributes=bytes(2048),
        bg_palette_base=bytes(64), bg_palette_transformed=bytes(64),
        obj_palette_base=bytes(64), obj_palette_transformed=bytes(64),
        attribute_rectangle=bytes(360), shadow_oam=bytes(160),
        hardware_oam=bytes(160), frame=42,
    )
    return semantic, trace, boundary, common


def _non_overlay_regions(*, case_id: int = 14):
    semantic, trace, boundary, common = _observation_regions(case_id=case_id)
    semantic[18] = 0
    generation = 3 if case_id < 17 else 4
    if case_id >= 19:
        generation = 5 if case_id < 22 else case_id - 16
    row = (0x2D).to_bytes(2, "little") + bytes((7, 1, 0x15, 0x1A, 1, 3)) + generation.to_bytes(4, "little") + bytes(4)
    boundary[:16] = row
    boundary[16:] = row
    record = bytes((
        PHASE2_NONOVERLAY_TRACE_MAGIC, case_id, 3, 6, 0, 0, 1, 3,
    )) + generation.to_bytes(4, "little") + bytes((0xFD, 0, 0, 0, 0, 0, 0, 0x2D, 0, 7, 1, 0x15, 0x1A))
    assert len(record) == 25
    trace[29:54] = record
    return semantic, trace, boundary, common


def test_fco2_v2_regions_decode_exact_machine_state() -> None:
    semantic, trace, boundary, common = _observation_regions(case_id=3)
    actual = decode_phase2_observation_regions(
        bytes(semantic), bytes(trace), bytes(boundary), **common
    )
    assert (actual.case_id, actual.sequence, actual.frame) == (3, 4, 42)
    assert actual.overlay_attributes == bytes((0xEF, 0, 0, 0))
    assert (actual.before.rom_bank, actual.after.wram_bank) == (0x2D, 7)


def test_fco2_v2_keeps_source_and_committed_attribute_planes_distinct() -> None:
    semantic, trace, boundary, common = _observation_regions(case_id=5)
    semantic[13:23] = bytes((4, 0x0F, 0x07, 0x02, 0x03, 2, 0x07, 0x03, 0, 0))
    actual = decode_phase2_observation_regions(
        bytes(semantic), bytes(trace), bytes(boundary), **common
    )
    assert actual.source_attribute_count == 4
    assert actual.source_attributes == bytes((0x0F, 0x07, 0x02, 0x03))
    assert actual.attribute_count == 2
    assert actual.overlay_attributes == bytes((0x07, 0x03, 0, 0))


def test_fco2_v2_decodes_strict_non_overlay_trace() -> None:
    semantic, trace, boundary, common = _non_overlay_regions()
    actual = decode_phase2_observation_regions(
        bytes(semantic), bytes(trace), bytes(boundary), **common
    )
    assert actual.non_overlay_trace is not None
    assert actual.non_overlay_trace.case_id == 14
    assert actual.non_overlay_trace.generation == 3


def test_fco2_v2_decodes_u16_oam_identity_and_outer_rom_bank() -> None:
    semantic, trace, boundary, common = _non_overlay_regions(case_id=20)
    trace[44:46] = (300).to_bytes(2, "little")
    trace[48:50] = (0x101).to_bytes(2, "little")
    boundary[:2] = boundary[16:18] = (0x101).to_bytes(2, "little")
    actual = decode_phase2_observation_regions(
        bytes(semantic), bytes(trace), bytes(boundary), **common
    )
    assert actual.non_overlay_trace is not None
    assert actual.non_overlay_trace.fallback_identity == 300
    assert actual.non_overlay_trace.rom_bank == 0x101
    assert (actual.before.rom_bank, actual.after.rom_bank) == (0x101, 0x101)


def test_fco2_v2_allows_only_the_case23_generation_replacement() -> None:
    semantic, trace, boundary, common = _non_overlay_regions(case_id=23)
    before = (0x2D).to_bytes(2, "little") + bytes((7, 1, 0x15, 0x1A, 1, 3)) + (7).to_bytes(4, "little") + bytes(4)
    after = (0x2D).to_bytes(2, "little") + bytes((7, 1, 0x15, 0x1A, 1, 3)) + (8).to_bytes(4, "little") + bytes(4)
    boundary[:] = before + after
    trace[37:41] = (8).to_bytes(4, "little")
    actual = decode_phase2_observation_regions(
        bytes(semantic), bytes(trace), bytes(boundary), **common
    )
    assert (actual.before.generation, actual.after.generation) == (7, 8)

    semantic[6] = 22
    semantic[11:13] = bytes((22, 23))
    trace[30] = 22
    with pytest.raises(Phase2RuntimeError, match="changed owner/generation"):
        decode_phase2_observation_regions(
            bytes(semantic), bytes(trace), bytes(boundary), **common
        )


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    (
        (29, 0, "magic"),
        (30, 15, "case/completion"),
        (31, 2, "case/completion"),
        (54, 1, "reserved"),
    ),
)
def test_fco2_v2_non_overlay_trace_fails_closed(
    offset: int, value: int, message: str,
) -> None:
    semantic, trace, boundary, common = _non_overlay_regions()
    trace[offset] = value
    with pytest.raises(Phase2RuntimeError, match=message):
        decode_phase2_observation_regions(
            bytes(semantic), bytes(trace), bytes(boundary), **common
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda s, t, b: s.__setitem__(0, 0), "magic"),
        (lambda s, t, b: s.__setitem__(4, 1), "version/size"),
        (lambda s, t, b: s.__setitem__(8, 1), "failure flags"),
        (lambda s, t, b: s.__setitem__(12, 0), "case/sequence"),
        (lambda s, t, b: t.__setitem__(0, 9), "transition count"),
        (lambda s, t, b: t.__setitem__(-1, 1), "trace reserved"),
        (lambda s, t, b: b.__setitem__(16, 0x2E), "leaked bank"),
    ),
)
def test_fco2_v2_regions_fail_closed(mutation, message: str) -> None:
    semantic, trace, boundary, common = _observation_regions()
    mutation(semantic, trace, boundary)
    with pytest.raises(Phase2RuntimeError, match=message):
        decode_phase2_observation_regions(
            bytes(semantic), bytes(trace), bytes(boundary), **common
        )


def test_committed_guarded_audit_identity_precedes_activation() -> None:
    identity = require_committed_guarded_audit(REPOSITORY_ROOT)
    assert identity.rom_sha256 == "536c747d855e6b381850d96d0dc45d3679d6a18034026e0add0ba4bb4eaa26ad"
    assert identity.sym_sha256 == "ce8111cd4f86fd6185181bdccbd63e515360c47e90f88168951a73417afe8e02"
    assert identity.map_sha256 == "a46f1b5efc8847d5319047bddca639cdfcbd211d4f504a59fbfb0c46c6247c90"
    assert identity.source_sha256 == "c4d94b9ac6433681be894192f6e71f2f7216e7f670412d5eeb673cbec111f50e"


def test_real_release_oam_fallback_has_no_debug_authority(
    request: pytest.FixtureRequest,
) -> None:
    observations = probe_release_oam_fallbacks(
        REPOSITORY_ROOT, result_directory(request.node.nodeid)
    )
    assert [item.case for item in observations] == [
        "missing", "out-of-range", "unmapped"
    ]
    for item in observations:
        assert item.carry
        assert item.shadow_attributes == item.before_attributes & 0xF8
        assert item.hardware_attributes == item.before_attributes & 0xF8
        assert item.entry_rom_bank == item.exit_rom_bank != 0
        assert (item.entry_wram_bank, item.exit_wram_bank) == (7, 7)
        assert (item.entry_vram_bank, item.exit_vram_bank) == (1, 1)
        assert (item.entry_ie, item.exit_ie) == (0x15, 0x15)
        assert (item.entry_if, item.exit_if) == (0x1A, 0x1A)
