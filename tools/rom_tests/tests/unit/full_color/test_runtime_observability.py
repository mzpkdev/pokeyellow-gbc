from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pytest

from tools.rom_tests.full_color import runtime_observability
from tools.rom_tests.full_color.runtime_observability import (
    DEBUG_LAYOUT_VERSION,
    DEBUG_TRACE_CAPACITY,
    DEBUG_TRACE_RECORD_SIZE,
    REQUIRED_DEBUG_SYMBOLS,
    PHASE1_COMMAND_SYMBOLS,
    PHASE1_CASE_ID,
    capture_phase1_runtime_observation,
    capture_yellow_baseline_snapshot,
    require_debug_symbols,
    run_retained_smoke,
    run_smoke,
)
from tools.rom_tests.full_color.renderer_oracle import load_corpus
from tools.rom_tests.full_color.snapshots import SemanticSnapshot


class FakeEmulator:
    def __init__(self) -> None:
        self.symbols = {
            symbol: 0xA000 + index
            for index, symbol in enumerate(REQUIRED_DEBUG_SYMBOLS)
        }
        self.symbol_banks = {symbol: 3 for symbol in REQUIRED_DEBUG_SYMBOLS}


def test_required_debug_symbol_contract_is_complete_and_bounded() -> None:
    required = set(REQUIRED_DEBUG_SYMBOLS)
    assert len(required) == len(REQUIRED_DEBUG_SYMBOLS)
    assert {
        "wFullColorDebugOwner",
        "wFullColorDebugPhase",
        "wFullColorDebugGeneration",
        "wFullColorDebugLastRequestResult",
        "wFullColorDebugJobState",
        "wFullColorDebugCancellationReason",
        "wFullColorDebugDirtyFlags",
        "wFullColorDebugCommitUnitID",
        "wFullColorDebugWriterID",
        "wFullColorDebugCurrentROMBank",
        "wFullColorDebugCurrentWRAMBank",
        "wFullColorDebugCurrentVRAMBank",
        "wFullColorDebugLastWriterID",
        "wFullColorDebugLastResourceID",
        "wFullColorDebugReconstructionItems",
        "wFullColorDebugPresentationBarrierStatus",
        "wFullColorDebugOAMFallbackKind",
        "wFullColorDebugTimingRowKey",
        "wFullColorDebugAssertionCode",
        "wFullColorDebugTraceStart",
        "wFullColorDebugTraceEnd",
    } <= required
    assert DEBUG_TRACE_CAPACITY == 32
    assert DEBUG_TRACE_RECORD_SIZE == 33


def test_debug_symbols_must_all_resolve_in_reserved_bank() -> None:
    emulator = FakeEmulator()
    require_debug_symbols(emulator)  # type: ignore[arg-type]

    del emulator.symbols["wFullColorDebugOwner"]
    with pytest.raises(AssertionError, match="missing symbols"):
        require_debug_symbols(emulator)  # type: ignore[arg-type]

    emulator = FakeEmulator()
    emulator.symbol_banks["wFullColorDebugOwner"] = 2
    with pytest.raises(AssertionError, match="outside reserved SRAM bank 3"):
        require_debug_symbols(emulator)  # type: ignore[arg-type]


class SnapshotEmulator:
    def __init__(self, rom: Path) -> None:
        self.rom = rom
        self.frame = 77
        self.symbols = {
            symbol: 0xA000 + index
            for index, symbol in enumerate(REQUIRED_DEBUG_SYMBOLS)
        }
        trace_start = 0xA200
        trace_size = 11 + DEBUG_TRACE_CAPACITY * DEBUG_TRACE_RECORD_SIZE
        self.symbols["wFullColorDebugTraceStart"] = trace_start
        self.symbols["wFullColorDebugTraceEnd"] = trace_start + trace_size
        self.symbols.update(
            {
                "hLoadedROMBank": 0xFFB8,
                "wCurMap": 0xD35E,
                "wCurMapTileset": 0xD367,
                "wShadowOAM": 0xC300,
            }
        )
        self.symbol_banks = {symbol: 3 for symbol in REQUIRED_DEBUG_SYMBOLS}
        self.symbol_banks.update(
            {
                "hLoadedROMBank": 0,
                "wCurMap": 1,
                "wCurMapTileset": 1,
                "wShadowOAM": 0,
            }
        )
        self.data = {symbol: bytes(4) for symbol in REQUIRED_DEBUG_SYMBOLS}
        self.data.update(
            {
                "wFullColorDebugMagic": b"FCG0",
                "wFullColorDebugLayoutVersion": bytes([DEBUG_LAYOUT_VERSION]),
                "wFullColorDebugGeneration": (9).to_bytes(4, "little"),
                "wFullColorDebugJobState": b"\xff",
                "wFullColorDebugCancellationReason": b"\xff",
                "wFullColorDebugDirtyFlags": b"\x05",
                "wFullColorDebugAssertionCode": b"\x00\x00",
                "wFullColorDebugTraceStart": struct.pack(
                    "<4sBHHH", b"FCTR", 2, DEBUG_TRACE_CAPACITY, 0, 0
                )
                + bytes(DEBUG_TRACE_CAPACITY * DEBUG_TRACE_RECORD_SIZE),
                "hLoadedROMBank": b"\x23",
                "wCurMap": b"\x26",
                "wCurMapTileset": b"\x07",
                "wShadowOAM": bytes(range(160)),
            }
        )
        self.io_registers = {
            0xFF70: 0xFD,
            0xFF4F: 0xFF,
            0xFF68: 0xA5,
            0xFF6A: 0xC3,
        }
        self.mutate_palette_guard = False
        self.closed = False

    def read(self, symbol: str) -> int:
        return self.read_bytes(symbol, 1)[0]

    def read_bytes(self, symbol: str, size: int) -> bytes:
        return self.data[symbol][:size]

    def read_memory(self, address: int, size: int, *, bank: int | None = None) -> bytes:
        assert bank is None
        if address in self.io_registers:
            assert size == 1
            return bytes([self.io_registers[address]])
        if address == 0xFE00:
            return bytes((255 - offset) & 0xFF for offset in range(size))
        raise AssertionError(f"unexpected memory read {address:#x} + {size}")

    def read_vram_bank(self, bank: int, address: int, size: int) -> bytes:
        assert address == 0x9800
        return bytes((bank * 17 + offset) & 0xFF for offset in range(size))

    def read_palette_ram(self, *, object_palettes: bool = False) -> bytes:
        if self.mutate_palette_guard and not object_palettes:
            self.io_registers[0xFF68] ^= 0x01
        start = 64 if object_palettes else 0
        return bytes((start + offset) & 0xFF for offset in range(64))

    def tick(self) -> None:
        raise AssertionError("initialized debug state should not need a tick")

    def close(self) -> None:
        self.closed = True


def _phase1_case():
    path = Path("tools/rom_tests/fixtures/full_color/renderer-conformance/cases.json")
    return next(
        case
        for case in load_corpus(json.loads(path.read_text(encoding="utf-8")))
        if case.case_id == PHASE1_CASE_ID
    )


class Phase1Emulator(SnapshotEmulator):
    def __init__(self, rom: Path) -> None:
        super().__init__(rom)
        for index, symbol in enumerate(PHASE1_COMMAND_SYMBOLS):
            self.symbols[symbol] = 0xA700 + index
            self.symbol_banks[symbol] = 3
            self.data[symbol] = b"\x00"
        self.data.update(
            {
                "wFullColorDebugActivationPhase": b"\x01",
                "wFullColorDebugOwner": b"\x01",
                "wFullColorDebugPhase": b"\x03",
                "wFullColorDebugGeneration": (8).to_bytes(4, "little"),
                "wFullColorDebugCheckpoint": b"\x01",
                "wFullColorDebugAdmissionOpen": b"\x01",
                "wFullColorDebugJobState": b"\x03",
                "wFullColorDebugJobGeneration": (8).to_bytes(4, "little"),
                "wFullColorDebugCancellationReason": b"\xff",
                "wFullColorDebugCommitUnitID": b"\x01\x00",
                "wFullColorDebugWriterID": b"\x01\x00",
                "wFullColorDebugLastWriterID": b"\x01\x00",
                "wFullColorDebugLastResourceID": b"\x01\x00",
            }
        )
        records = [
            (0, 1, 7, 7, 1, 3, 1, 0, 0xFF, 1, 1, 1, 1, 1, 0),
            (1, 1, 7, 7, 1, 3, 1, 1, 0xFF, 1, 1, 1, 1, 1, 0),
            (2, 1, 7, 7, 1, 3, 1, 4, 2, 1, 1, 1, 1, 1, 0),
            (3, 1, 8, 8, 1, 3, 1, 0, 0xFF, 1, 1, 1, 2, 1, 0),
            (4, 1, 8, 8, 1, 3, 1, 1, 0xFF, 1, 1, 1, 2, 1, 0),
            (5, 1, 8, 8, 1, 3, 1, 2, 0xFF, 1, 1, 1, 2, 1, 1),
            (6, 1, 8, 8, 1, 3, 1, 3, 0xFF, 1, 1, 1, 2, 1, 0),
        ]
        record_struct = struct.Struct("<IIIIBBBBBHHHHHH")
        body = b"".join(record_struct.pack(*record) for record in records)
        body += bytes((DEBUG_TRACE_CAPACITY - len(records)) * DEBUG_TRACE_RECORD_SIZE)
        self.data["wFullColorDebugTraceStart"] = (
            struct.pack("<4sBHHH", b"FCTR", 2, DEBUG_TRACE_CAPACITY, len(records), len(records))
            + body
        )


def test_phase1_capture_uses_real_rom_identity_and_canonical_trace(tmp_path: Path) -> None:
    rom = tmp_path / "pokeyellow_debug.gbc"
    rom.write_bytes(b"phase1 ROM")
    emulator = Phase1Emulator(rom)

    observation = capture_phase1_runtime_observation(
        emulator,  # type: ignore[arg-type]
        _phase1_case(),
        execute_command=False,
    )

    assert observation.snapshot.evidence_kind == "RENDERER_RUNTIME"
    assert observation.snapshot.activation_phase == 1
    assert observation.snapshot.scenario == PHASE1_CASE_ID
    assert observation.snapshot.rom == (
        "pokeyellow_debug.gbc:" + hashlib.sha256(b"phase1 ROM").hexdigest()
    )
    assert [entry.job_id for entry in observation.trace.entries] == [
        "JOB-OLD",
        "JOB-OLD",
        "JOB-OLD",
        "JOB-REPLACEMENT",
        "JOB-REPLACEMENT",
        "JOB-REPLACEMENT",
        "JOB-REPLACEMENT",
    ]


@pytest.mark.parametrize(
    ("symbol", "value", "failure"),
    [
        ("wFullColorDebugActivationPhase", 0, "wrong activation phase"),
        ("wFullColorDebugOwner", 0, "wrong owner code"),
        ("wFullColorDebugPhase", 0, "wrong phase code"),
        ("wFullColorDebugGeneration", 7, "wrong generation"),
    ],
)
def test_phase1_capture_rejects_wrong_carrier_identity(
    tmp_path: Path, symbol: str, value: int, failure: str
) -> None:
    rom = tmp_path / "pokeyellow_debug.gbc"
    rom.write_bytes(b"phase1 ROM")
    emulator = Phase1Emulator(rom)
    size = 4 if symbol == "wFullColorDebugGeneration" else 1
    emulator.data[symbol] = value.to_bytes(size, "little")
    with pytest.raises(AssertionError, match=failure):
        capture_phase1_runtime_observation(
            emulator,  # type: ignore[arg-type]
            _phase1_case(),
            execute_command=False,
        )


def test_capture_constructs_valid_deterministic_yellow_baseline(
    tmp_path: Path,
) -> None:
    rom = tmp_path / "pokeyellow_debug.gbc"
    rom.write_bytes(b"deterministic ROM")
    emulator = SnapshotEmulator(rom)

    snapshot = capture_yellow_baseline_snapshot(
        emulator,  # type: ignore[arg-type]
        scenario="new_game",
        seed=123,
        checkpoint="bedroom",
    )

    assert SemanticSnapshot.from_json(snapshot.to_json()) == snapshot
    assert snapshot.rom == (
        "pokeyellow_debug.gbc:" + hashlib.sha256(b"deterministic ROM").hexdigest()
    )
    assert snapshot.frame == 77
    assert snapshot.generation == 9
    assert snapshot.banks.to_dict() == {"rom": 0x23, "wram": 5, "vram": 1}
    assert dict(snapshot.dirty) == {
        "attributes": True,
        "bg": True,
        "obj": False,
    }
    assert snapshot.bg_tile_ids[:3] == b"\x00\x01\x02"
    assert snapshot.bg_attributes[:3] == b"\x11\x12\x13"
    assert snapshot.bg_palettes == bytes(range(64))
    assert snapshot.obj_palettes == bytes(range(64, 128))
    assert snapshot.shadow_oam == bytes(range(160))
    assert snapshot.hardware_oam[:3] == b"\xff\xfe\xfd"
    assert snapshot.map_id == "$26"
    assert snapshot.tileset_id == "$07"
    assert snapshot.job is None
    assert snapshot.queued_jobs == ()
    assert snapshot.traced_writer_ids == ()
    assert snapshot.timing_row is None


def test_capture_rejects_unknown_dirty_bits(tmp_path: Path) -> None:
    rom = tmp_path / "debug.gbc"
    rom.write_bytes(b"ROM")
    emulator = SnapshotEmulator(rom)
    emulator.data["wFullColorDebugDirtyFlags"] = b"\x80"

    with pytest.raises(AssertionError, match="unknown debug dirty bits: 0x80"):
        capture_yellow_baseline_snapshot(
            emulator,  # type: ignore[arg-type]
            scenario="test",
            seed=0,
            checkpoint="dirty",
        )


def test_capture_rejects_unsupported_nonzero_scalar(tmp_path: Path) -> None:
    rom = tmp_path / "debug.gbc"
    rom.write_bytes(b"ROM")
    emulator = SnapshotEmulator(rom)
    emulator.data["wFullColorDebugLastRequestResult"] = b"\x01"

    with pytest.raises(
        AssertionError,
        match="wFullColorDebugLastRequestResult=1",
    ):
        capture_yellow_baseline_snapshot(
            emulator,  # type: ignore[arg-type]
            scenario="test",
            seed=0,
            checkpoint="request",
        )


def test_capture_rejects_changed_bank_or_palette_guard(tmp_path: Path) -> None:
    rom = tmp_path / "debug.gbc"
    rom.write_bytes(b"ROM")
    emulator = SnapshotEmulator(rom)
    emulator.mutate_palette_guard = True

    with pytest.raises(
        AssertionError,
        match=r"semantic snapshot capture changed guard state: FF68=0xa5->0xa4",
    ):
        capture_yellow_baseline_snapshot(
            emulator,  # type: ignore[arg-type]
            scenario="test",
            seed=0,
            checkpoint="guard",
        )


def test_smoke_writes_deterministic_debug_ready_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rom = tmp_path / "pokeyellow_debug.gbc"
    rom.write_bytes(b"deterministic ROM")
    emulator = SnapshotEmulator(rom)
    emulator.data.update(
        {
            "wFullColorDebugGeneration": (1).to_bytes(4, "little"),
            "wFullColorDebugCurrentROMBank": b"\x01",
            "wFullColorDebugCurrentWRAMBank": b"\x01",
            "wFullColorDebugCurrentVRAMBank": b"\x00",
        }
    )
    monkeypatch.setattr(runtime_observability, "Emulator", lambda **_kwargs: emulator)
    output = tmp_path / "evidence" / "semantic-snapshot.json"

    summary = run_smoke(tmp_path, snapshot_output=output)

    payload = output.read_text(encoding="utf-8")
    snapshot = SemanticSnapshot.from_json(payload)
    encoded = payload.encode("utf-8")
    assert snapshot.scenario == "gate-0-baseline"
    assert snapshot.checkpoint == "debug-ready"
    assert summary["snapshot_bytes"] == len(encoded)
    assert summary["snapshot_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert emulator.closed


def test_smoke_routes_diagnostics_to_external_results_without_repo_local_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    rom = root / "pokeyellow_debug.gbc"
    rom.write_bytes(b"deterministic ROM")
    emulator = SnapshotEmulator(rom)
    emulator.data.update(
        {
            "wFullColorDebugGeneration": (1).to_bytes(4, "little"),
            "wFullColorDebugCurrentROMBank": b"\x01",
            "wFullColorDebugCurrentWRAMBank": b"\x01",
            "wFullColorDebugCurrentVRAMBank": b"\x00",
        }
    )
    constructor_args: dict[str, object] = {}

    def emulator_factory(**kwargs: object) -> SnapshotEmulator:
        constructor_args.update(kwargs)
        return emulator

    monkeypatch.setattr(runtime_observability, "Emulator", emulator_factory)
    external = tmp_path / "external results with spaces"

    run_smoke(
        root,
        snapshot_output=external / "semantic-snapshot.json",
        diagnostics_output=external / "diagnostics",
    )

    assert constructor_args["results"] == external / "diagnostics"
    assert not (root / "test-results").exists()


def test_retained_smoke_failure_does_not_stale_or_destroy_prior_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def smoke(
        root: Path,
        *,
        snapshot_output: Path | None = None,
        diagnostics_output: Path | None = None,
    ) -> dict[str, object]:
        nonlocal calls
        del root
        calls += 1
        assert snapshot_output is not None
        assert diagnostics_output is not None
        diagnostics_output.mkdir(parents=True)
        (diagnostics_output / "emulator.log").write_text(
            f"attempt {calls}", encoding="utf-8"
        )
        if calls == 2:
            raise AssertionError("mutated smoke failure")
        snapshot_output.write_text("stable snapshot", encoding="utf-8")
        return {"schema": "smoke-report-v1"}

    monkeypatch.setattr(runtime_observability, "run_smoke", smoke)
    results = tmp_path / "smoke results"
    first = run_retained_smoke(tmp_path, results)
    first_summary = (results / "attempt-0001/summary.json").read_bytes()

    with pytest.raises(AssertionError, match="mutated smoke failure"):
        run_retained_smoke(tmp_path, results)

    assert first["status"] == "passed"
    assert (results / "attempt-0001/summary.json").read_bytes() == first_summary
    assert (results / "attempt-0001/semantic-snapshot.json").read_text() == (
        "stable snapshot"
    )
    failed = results / "attempt-0002"
    assert json.loads((failed / "summary.json").read_text())["status"] == "failed"
    assert (failed / "diagnostics/emulator.log").read_text() == "attempt 2"
    assert not (failed / "semantic-snapshot.json").exists()
    assert not (failed / "observability.json").exists()


def test_cli_retained_json_mode_emits_one_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def smoke(
        root: Path,
        *,
        snapshot_output: Path | None = None,
        diagnostics_output: Path | None = None,
    ) -> dict[str, object]:
        del root
        assert snapshot_output is not None
        assert diagnostics_output is not None
        snapshot_output.write_text("snapshot", encoding="utf-8")
        diagnostics_output.mkdir(parents=True)
        return {"schema": "smoke-report-v1"}

    monkeypatch.setattr(runtime_observability, "run_smoke", smoke)
    results = tmp_path / "results with spaces"
    assert runtime_observability.main(
        ["--root", str(tmp_path), "--results", str(results), "--output", "json"]
    ) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["status"] == "passed"
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_json_failure_uses_current_attempt_not_malformed_stale_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results"
    stale = results / "attempt-9999"
    stale.mkdir(parents=True)
    (stale / "summary.json").write_text("{malformed", encoding="utf-8")

    def smoke(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("current")

    monkeypatch.setattr(runtime_observability, "run_smoke", smoke)
    assert runtime_observability.main(
        ["--results", str(results), "--output", "json"]
    ) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["attempt"] == "attempt-0001"
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_cli_retained_failure_is_bounded_and_keeps_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def smoke(
        root: Path,
        *,
        snapshot_output: Path | None = None,
        diagnostics_output: Path | None = None,
    ) -> dict[str, object]:
        del root, snapshot_output
        assert diagnostics_output is not None
        diagnostics_output.mkdir(parents=True)
        (diagnostics_output / "emulator.log").write_text(
            "complete diagnostic detail", encoding="utf-8"
        )
        raise AssertionError("first actionable line\nextra\nnoise")

    monkeypatch.setattr(runtime_observability, "run_smoke", smoke)
    results = tmp_path / "results"
    assert runtime_observability.main(
        ["--root", str(tmp_path), "--results", str(results)]
    ) == 1
    captured = capsys.readouterr()
    assert len(captured.err.splitlines()) <= 5
    assert "EVIDENCE" in captured.err
    assert (results / "attempt-0001/diagnostics/emulator.log").read_text() == (
        "complete diagnostic detail"
    )


def test_cli_preserves_explicit_gate0_outputs_and_rejects_mixed_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def smoke(
        root: Path,
        *,
        snapshot_output: Path | None = None,
        diagnostics_output: Path | None = None,
    ) -> dict[str, object]:
        del root
        assert snapshot_output is not None
        assert diagnostics_output is not None
        snapshot_output.parent.mkdir(parents=True, exist_ok=True)
        snapshot_output.write_text("snapshot", encoding="utf-8")
        diagnostics_output.mkdir(parents=True)
        return {"schema": "smoke-report-v1"}

    monkeypatch.setattr(runtime_observability, "run_smoke", smoke)
    snapshot = tmp_path / "semantic snapshot.json"
    diagnostics = tmp_path / "diagnostics with spaces"
    assert runtime_observability.main(
        [
            "--root",
            str(tmp_path),
            "--snapshot-output",
            str(snapshot),
            "--diagnostics-output",
            str(diagnostics),
        ]
    ) == 0
    assert snapshot.is_file()
    assert diagnostics.is_dir()
    capsys.readouterr()

    with pytest.raises(SystemExit) as error:
        runtime_observability.main(
            [
                "--root",
                str(tmp_path),
                "--results",
                str(tmp_path / "retained"),
                "--snapshot-output",
                str(snapshot),
            ]
        )
    assert error.value.code == 2
