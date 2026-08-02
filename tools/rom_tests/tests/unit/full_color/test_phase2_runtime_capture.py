"""Closed-emission tests for the Phase 2 observation bundle adapter."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from tools.rom_tests.full_color.bank_torture import BankTortureResult
from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.phase2_conformance_runtime import (
    Phase2Observation,
    canonical_phase2_cases,
)
from tools.rom_tests.full_color.phase2_runtime_artifacts import expected_artifact_paths
from tools.rom_tests.full_color.phase2_runtime_capture import (
    Capture,
    InputReplayEvent,
    Phase2ObservationBundle,
    _production_source,
)
from tools.rom_tests.full_color.phase2_runtime_observability import (
    OVERWORLD_ACTIVE,
    RENDERER_FULL_COLOR_OVERWORLD,
    Phase2Carrier,
    Phase2CarrierRecord,
    ReleaseOAMFallbackObservation,
)
from tools.rom_tests.full_color.snapshots import SemanticSnapshot
from tools.rom_tests.full_color.trace import WriterTrace
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


FIXTURES = REPOSITORY_ROOT / "tools/rom_tests/fixtures/full_color/renderer-conformance"


def _rom_identity() -> str:
    payload = (REPOSITORY_ROOT / "pokeyellow_debug.gbc").read_bytes()
    return "pokeyellow_debug.gbc:" + hashlib.sha256(payload).hexdigest()


def _observations() -> tuple[Phase2Observation, ...]:
    identity = _rom_identity()
    rows = []
    for case in canonical_phase2_cases(REPOSITORY_ROOT):
        snapshot = SemanticSnapshot.from_json(
            (FIXTURES / case.observation_snapshot).read_text(encoding="utf-8")
        )
        snapshot = replace(
            snapshot,
            rom=identity,
            evidence_kind="RENDERER_RUNTIME",
            activation_phase=2,
        )
        trace = WriterTrace.from_json(
            (FIXTURES / case.observation_trace).read_text(encoding="utf-8")
        )
        boundary = None
        if case.observation_boundary is not None:
            boundary = BankTortureResult.from_dict(
                json.loads((FIXTURES / case.observation_boundary).read_text()),
                path="boundary",
            )
        rows.append(Phase2Observation(case.case_id, identity, snapshot, trace, boundary))
    return tuple(rows)


def _record(checkpoint: int) -> Phase2CarrierRecord:
    return Phase2CarrierRecord(
        kind="checkpoint", checkpoint=checkpoint,
        owner=RENDERER_FULL_COLOR_OVERWORLD, phase=OVERWORLD_ACTIVE,
        generation=2, rom_bank=0x2D, wram_bank=7, vram_bank=1,
        ie=0x15, interrupt_flags=0x1A, request_result=1, request_count=1,
        commit_or_request_class=1, reconstruction_barrier_count=1,
        fallback_kind=0, fallback_identity=0, fallback_object_index=0,
        before_attributes=0xD8, after_attributes=0xD8,
        payload=bytes(19), timing=None,
    )


def _bundle() -> Phase2ObservationBundle:
    observations = _observations()
    carriers = tuple(
        Phase2Carrier(
            sequence=index, scenario=1, flags=1, command=0x31,
            checkpoint=0x31, write_index=1, records=(_record(index),),
        )
        for index in range(1, 6)
    )
    fallbacks = tuple(
        ReleaseOAMFallbackObservation(
            case=case, identity=identity, object_index=index,
            before_attributes=0xD8 | index,
            shadow_attributes=(0xD8 | index) & 0xF8,
            hardware_attributes=(0xD8 | index) & 0xF8,
            carry=True, entry_rom_bank=0x2D, exit_rom_bank=0x2D,
            entry_wram_bank=7, exit_wram_bank=7,
            entry_vram_bank=1, exit_vram_bank=1,
            entry_ie=0x15, exit_ie=0x15, entry_if=0x1A, exit_if=0x1A,
        )
        for index, (case, identity) in enumerate((
            ("missing", 0xFF), ("out-of-range", 0x08), ("unmapped", 0x00)
        ))
    )
    return Phase2ObservationBundle(
        observations=observations,
        carriers=carriers,
        release_fallbacks=fallbacks,
        frames=(Image.new("RGB", (8, 8), "black"), Image.new("RGB", (8, 8), "red")),
        frame_numbers=(100, 101), checkpoint_index=1,
        visual_case_id="RC-TRANSFER-ROW",
        input_replay=(InputReplayEvent(0, 0), InputReplayEvent(100, 1)),
    )


def test_capture_emits_every_closed_role_from_one_bundle(tmp_path: Path) -> None:
    timing = tmp_path / "sameboy-timing.json"
    timing.write_text('{"blocking":true}\n', encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    Capture(REPOSITORY_ROOT, run, timing, source=lambda root, results: _bundle())
    actual = {path.relative_to(run).as_posix() for path in run.rglob("*") if path.is_file()}
    assert actual == expected_artifact_paths()
    pressure = json.loads((run / "pressure.json").read_text())
    assert pressure["input_replay"]["timebase"] == "absolute-cold-boot-frame"
    assert pressure["input_replay"]["events"][-1] == {"frame": 100, "key_mask": 1}
    assert json.loads((run / "cases/RC-TRANSFER-ROW/structured-diff.json").read_text())["passed"]


def test_production_source_fails_closed_without_complete_observation_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.rom_tests.full_color import phase2_runtime_observability

    monkeypatch.delattr(
        phase2_runtime_observability, "capture_phase2_observation_bundle", raising=False
    )
    with pytest.raises(RendererConformanceError, match="closes Emulator after carrier-only"):
        _production_source(REPOSITORY_ROOT, tmp_path)

