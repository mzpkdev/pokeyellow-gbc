"""Pure contract checks for the guarded Phase 2 observability harness."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.rom_tests.full_color.phase2_audit_observability import (
    CARRIER_BYTES,
    Phase2AuditError,
    Phase2AuditHarness,
    Phase2AuditIdentity,
    decode_phase2_audit_snapshot,
)
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT, result_directory


CONSTANTS = {
    "FULL_COLOR_DEBUG_COMMAND_CLEAR": 0x20,
    "FULL_COLOR_DEBUG_COMMAND_ARM": 0x21,
    "FULL_COLOR_DEBUG_COMMAND_SNAPSHOT": 0x22,
    "FULL_COLOR_DEBUG_COMMAND_ACK": 0x23,
    "FULL_COLOR_DEBUG_CHECKPOINT_CLEAR": 0x20,
    "FULL_COLOR_DEBUG_CHECKPOINT_ARMED": 0x21,
    "FULL_COLOR_DEBUG_CHECKPOINT_SNAPSHOT": 0x22,
    "FULL_COLOR_DEBUG_CHECKPOINT_ACKNOWLEDGED": 0x23,
    "FULL_COLOR_FALLBACK_NONE": 0,
    "FULL_COLOR_FALLBACK_MISSING_IDENTITY": 1,
    "FULL_COLOR_FALLBACK_OUT_OF_RANGE": 2,
    "FULL_COLOR_FALLBACK_UNMAPPED": 3,
    "FULL_COLOR_RESOURCE_ALL": 0x3F,
}


def carrier() -> bytearray:
    raw = bytearray(CARRIER_BYTES)
    raw[0] = 2
    raw[2] = CONSTANTS["FULL_COLOR_DEBUG_CHECKPOINT_SNAPSHOT"]
    raw[4:6] = (1).to_bytes(2, "little")
    raw[6:8] = b"\x07\x07"
    raw[8:10] = b"\x1f\x1f"
    raw[10:14] = b"\x70\xc0\x70\xc0"
    return raw


def test_exact_snapshot_layout_decodes_to_json_values() -> None:
    decoded = decode_phase2_audit_snapshot(
        bytes(carrier()),
        constants=CONSTANTS,
        expected_protocol=2,
        expected_checkpoint=0x22,
        expected_sequence=1,
    )
    assert decoded.sequence == 1
    assert decoded.request.count == 0
    assert decoded.fallback.count == 0
    assert decoded.reconstruction.barrier_count == 0
    assert decoded.to_dict()["trace_records"] == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.__setitem__(1, 0x22), "command was not consumed"),
        (lambda raw: raw.__setitem__(20, 9), "scheduler ring"),
        (lambda raw: raw.__setitem__(27, 0x80), "writer mask"),
        (lambda raw: raw.__setitem__(33, 0x7F), "unknown fallback"),
        (lambda raw: raw.__setitem__(36, 2), "more than one barrier"),
        (lambda raw: raw.__setitem__(44, 9), "bounded ring"),
        (lambda raw: raw.__setitem__(294, 1), "reserved tail"),
    ],
)
def test_malformed_snapshot_fails_closed(mutate, message: str) -> None:
    raw = carrier()
    mutate(raw)
    with pytest.raises(Phase2AuditError, match=message):
        decode_phase2_audit_snapshot(bytes(raw), constants=CONSTANTS)


def test_sequence_and_checkpoint_are_exact() -> None:
    raw = bytes(carrier())
    with pytest.raises(Phase2AuditError, match="sequence 1 != expected 2"):
        decode_phase2_audit_snapshot(
            raw, constants=CONSTANTS, expected_sequence=2
        )
    with pytest.raises(Phase2AuditError, match="checkpoint"):
        decode_phase2_audit_snapshot(
            raw, constants=CONSTANTS, expected_checkpoint=0x23
        )


def test_identity_is_exact_and_json_serializable() -> None:
    identity = Phase2AuditIdentity("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    assert identity.to_dict()["rom_name"] == "pokeyellow_phase2_audit.gbc"
    assert replace(identity, rom_sha256="e" * 64) != identity
    with pytest.raises(Phase2AuditError, match="SHA-256"):
        replace(identity, source_sha256="not-a-hash")
    with pytest.raises(Phase2AuditError, match="other than Phase 2 audit"):
        replace(identity, rom_name="pokeyellow_debug.gbc")


def test_real_audit_product_layout_identity_and_protocol(
    request: pytest.FixtureRequest,
) -> None:
    results = result_directory(request.node.nodeid)
    with Phase2AuditHarness(REPOSITORY_ROOT, results) as harness:
        expected = harness.identity
        observation = harness.capture(
            lambda active: active.invoke("SnapshotFullColorMapAuthority")
        )
    assert observation.identity == expected
    assert observation.snapshot.sequence == 1
    assert observation.snapshot.trace_count <= 8
    assert len(observation.calls) == 5
    assert observation.calls[2].routine == "SnapshotFullColorMapAuthority"
    assert [call.entry_banks for call in observation.calls] == [
        call.exit_banks for call in observation.calls
    ]
    assert observation.to_dict()["snapshot"]["checkpoint"] == 0x22
    with pytest.raises(Phase2AuditError, match="identity changed"):
        Phase2AuditHarness(
            REPOSITORY_ROOT,
            results,
            expected_identity=replace(expected, rom_sha256="e" * 64),
        )
