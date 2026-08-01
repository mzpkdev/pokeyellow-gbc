from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.enums import Owner, Phase
from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.renderer_conformance_runtime import (
    ACTIVATED_PHASE1_CASE_IDS,
    FrozenRuntimeProvider,
    canonical_phase1_case,
    check_runtime_observation,
)
from tools.rom_tests.full_color.renderer_oracle import load_corpus
from tools.rom_tests.full_color.runtime_observability import RuntimeObservation
from tools.rom_tests.full_color.snapshots import SemanticSnapshot
from tools.rom_tests.full_color.trace import WriterTrace

ROOT = Path.cwd()
FIXTURES = ROOT / "tools/rom_tests/fixtures/full_color/renderer-conformance"


def canonical_cases():
    return load_corpus(json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8")))


def observation() -> RuntimeObservation:
    case = canonical_phase1_case(ROOT)
    snapshot = SemanticSnapshot.from_json(
        (FIXTURES / case.observation_snapshot).read_text(encoding="utf-8")
    )
    snapshot = replace(
        snapshot,
        rom="pokeyellow_debug.gbc:0123456789abcdef",
        evidence_kind="RENDERER_RUNTIME",
        activation_phase=1,
        checkpoint="phase1-ownership-replacement",
        artifacts=(),
        reconstruction=replace(
            snapshot.reconstruction,
            completed_items=(),
            item_provenance=(),
            poisoned_items=(),
            unknown_prior_state=False,
            presentation_barrier_count=0,
        ),
    )
    trace = WriterTrace.from_json(
        (FIXTURES / case.observation_trace).read_text(encoding="utf-8")
    )
    return RuntimeObservation(case.case_id, snapshot.rom, snapshot, trace)


def test_only_canonical_ownership_replacement_is_activated() -> None:
    assert ACTIVATED_PHASE1_CASE_IDS == ("RC-OWNERSHIP-REPLACEMENT",)
    assert len(canonical_cases()) == 25
    assert canonical_phase1_case(ROOT).case_id == ACTIVATED_PHASE1_CASE_IDS[0]


def test_clean_runtime_observation_passes_existing_checker_seam() -> None:
    case = canonical_phase1_case(ROOT)
    clean = observation()
    assert SemanticSnapshot.from_json(clean.snapshot.to_json()) == clean.snapshot
    report = check_runtime_observation(case, clean)
    assert report.passed
    assert report.mode.value == "rom_runtime"


@pytest.mark.parametrize(
    ("changes", "failure"),
    [
        (
            {"evidence_kind": "SCHEMA_FIXTURE", "activation_phase": 0},
            "wrong evidence provenance",
        ),
        ({"activation_phase": 2}, "requires activation phase 1"),
    ],
)
def test_runtime_observation_rejects_wrong_provenance(changes, failure: str) -> None:
    clean = observation()
    with pytest.raises(AssertionError, match=failure):
        replace(clean, snapshot=replace(clean.snapshot, **changes))


def test_provider_rejects_wrong_phase_case_and_rom_identity() -> None:
    case = canonical_phase1_case(ROOT)
    clean = observation()
    bad_phase = replace(
        clean, snapshot=replace(clean.snapshot, phase=Phase.HANDOFF_TO_YELLOW)
    )
    with pytest.raises(RendererConformanceError, match="wrong phase"):
        FrozenRuntimeProvider(bad_phase).snapshot(case)

    wrong_case = next(item for item in canonical_cases() if item.case_id != case.case_id)
    with pytest.raises(RendererConformanceError, match="not activated"):
        FrozenRuntimeProvider(clean).snapshot(wrong_case)

    forged = RuntimeObservation.__new__(RuntimeObservation)
    object.__setattr__(forged, "case_id", clean.case_id)
    object.__setattr__(forged, "rom_identity", "other.gbc:bad")
    object.__setattr__(forged, "snapshot", clean.snapshot)
    object.__setattr__(forged, "trace", clean.trace)
    with pytest.raises(RendererConformanceError, match="wrong ROM identity"):
        FrozenRuntimeProvider(forged).snapshot(case)
