"""Bounded writer trace decoding and mutation tests."""

import pytest

from tools.rom_tests.full_color.enums import (
    CancellationReason,
    JobState,
    Owner,
    Phase,
)
from tools.rom_tests.full_color.errors import TraceDecodeError
from tools.rom_tests.full_color.trace import (
    TraceSymbols,
    WriterTrace,
    decode_writer_ring,
    encode_synthetic_ring,
)


@pytest.fixture
def symbols() -> TraceSymbols:
    return TraceSymbols(
        owners={7: Owner.RENDERER_FULL_COLOR_OVERWORLD},
        phases={9: Phase.OVERWORLD_ACTIVE},
        job_states={3: JobState.CANCELLED},
        cancellations={0: None, 4: CancellationReason.HANDOFF},
        writer_ids={11: "WR-TEST-STREAM"},
        commit_unit_ids={0: None, 5: "MU-TEST-PAIR"},
        job_ids={13: "JOB-0041"},
        request_ids={17: "REQ-0900"},
    )


def test_synthetic_ring_decodes_through_external_symbol_tables(
    symbols: TraceSymbols,
) -> None:
    raw = encode_synthetic_ring(
        capacity=3,
        records=((41, 900, 12, 12, 7, 9, 7, 3, 4, 11, 5, 0x77, 13, 17, 0),),
    )

    trace = decode_writer_ring(
        raw, symbols, permitted_writer_ids=("WR-TEST-STREAM",)
    )

    assert trace.capacity == 3
    assert trace.entries[0].writer_id == "WR-TEST-STREAM"
    assert trace.entries[0].cancellation_reason is CancellationReason.HANDOFF
    assert WriterTrace.from_json(trace.to_json()) == trace


def test_unknown_numeric_symbol_fails_at_exact_slot(symbols: TraceSymbols) -> None:
    raw = encode_synthetic_ring(
        capacity=1,
        records=((1, 2, 3, 3, 99, 9, 7, 3, 4, 11, 5, 6, 13, 17, 0),),
    )

    with pytest.raises(TraceDecodeError, match="slot 0: unknown owner code 99"):
        decode_writer_ring(
            raw, symbols, permitted_writer_ids=("WR-TEST-STREAM",)
        )


def test_trace_rejects_count_beyond_bounded_capacity(symbols: TraceSymbols) -> None:
    raw = bytearray(encode_synthetic_ring(capacity=1, records=()))
    raw[7:9] = (2).to_bytes(2, "little")

    with pytest.raises(TraceDecodeError, match="count 2 exceeds capacity 1"):
        decode_writer_ring(
            bytes(raw), symbols, permitted_writer_ids=("WR-TEST-STREAM",)
        )


def test_trace_rejects_nonzero_unused_ring_slot(symbols: TraceSymbols) -> None:
    raw = bytearray(encode_synthetic_ring(capacity=1, records=()))
    raw[-1] = 1

    with pytest.raises(TraceDecodeError, match="unused slot 0 is not zero-filled"):
        decode_writer_ring(
            bytes(raw), symbols, permitted_writer_ids=("WR-TEST-STREAM",)
        )


def test_json_trace_rejects_duplicate_or_reordered_sequences() -> None:
    entry = {
        "sequence": 2,
        "frame": 3,
        "generation": 1,
        "job_generation": 1,
        "owner": "RENDERER_YELLOW",
        "phase": "YELLOW_ACTIVE",
        "job_owner": "RENDERER_YELLOW",
        "job_state": "PENDING",
        "cancellation_reason": None,
        "writer_id": "WR-TEST",
        "commit_unit_id": None,
        "job_id": "JOB-1",
        "request_id": "REQ-1",
        "resource_id": 1,
        "wrote": False,
    }
    raw = {
        "schema": "full-color-writer-trace-v1",
        "capacity": 2,
        "permitted_writer_ids": ["WR-TEST"],
        "entries": [entry, dict(entry)],
    }

    with pytest.raises(TraceDecodeError, match="unique and increasing"):
        WriterTrace.from_dict(raw)


def test_cancelled_trace_entry_cannot_report_a_later_write() -> None:
    raw = {
        "schema": "full-color-writer-trace-v1",
        "capacity": 1,
        "entries": [
            {
                "sequence": 2,
                "frame": 3,
                "generation": 1,
                "job_generation": 1,
                "owner": "RENDERER_YELLOW",
                "phase": "YELLOW_ACTIVE",
                "job_owner": "RENDERER_YELLOW",
                "job_state": "CANCELLED",
                "cancellation_reason": "RESET",
                "writer_id": "WR-TEST",
                "commit_unit_id": None,
                "job_id": "JOB-1",
                "request_id": "REQ-1",
                "resource_id": 1,
                "wrote": False,
            }
        ],
        "permitted_writer_ids": ["WR-TEST"],
    }

    raw["entries"].append(
        {
            **raw["entries"][0],
            "sequence": 3,
            "job_state": "COMMITTING",
            "cancellation_reason": None,
            "commit_unit_id": "MU-PAIR",
            "wrote": True,
        }
    )
    raw["capacity"] = 2
    with pytest.raises(TraceDecodeError, match="write after cancellation"):
        WriterTrace.from_dict(raw)


def trace_entry(**changes: object) -> dict[str, object]:
    raw = {
        "sequence": 1,
        "frame": 3,
        "generation": 7,
        "job_generation": 7,
        "owner": "RENDERER_YELLOW",
        "phase": "YELLOW_ACTIVE",
        "job_owner": "RENDERER_YELLOW",
        "job_state": "COMMITTING",
        "cancellation_reason": None,
        "writer_id": "WR-EXPECTED",
        "commit_unit_id": "MU-PAIR",
        "job_id": "JOB-STABLE",
        "request_id": "REQ-STABLE",
        "resource_id": 1,
        "wrote": True,
    }
    raw.update(changes)
    return raw


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"commit_unit_id": None}, "concrete commit_unit_id"),
        ({"job_owner": "RENDERER_FULL_COLOR_OVERWORLD"}, "wrong owner write"),
        ({"job_generation": 6}, "stale job generation"),
        ({"job_state": "PENDING"}, "PENDING work reports a visible write"),
        ({"job_state": "PREPARED"}, "PREPARED work reports a visible write"),
        ({"writer_id": "WR-UNEXPECTED"}, "unexpected hardware writer"),
    ],
)
def test_cross_entry_write_guards(changes: dict[str, object], message: str) -> None:
    raw = {
        "schema": "full-color-writer-trace-v1",
        "capacity": 1,
        "permitted_writer_ids": ["WR-EXPECTED"],
        "entries": [trace_entry(**changes)],
    }
    with pytest.raises(TraceDecodeError, match=message):
        WriterTrace.from_dict(raw)
