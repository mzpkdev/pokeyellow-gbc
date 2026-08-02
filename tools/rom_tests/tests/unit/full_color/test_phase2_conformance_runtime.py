"""Phase 2 binding of real hostile-slice observations to the frozen oracle."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from tools.rom_tests.full_color.bank_torture import BankTortureResult
from tools.rom_tests.full_color.enums import Owner
from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.phase2_conformance_runtime import (
    ACTIVATED_PHASE2_CASE_IDS,
    PHASE2_MUTATION_SENSITIVITY,
    FrozenPhase2Provider,
    Phase2Observation,
    canonical_phase2_cases,
    check_phase2_observation,
    check_phase2_observations,
    phase2_case_checkpoints,
)
from tools.rom_tests.full_color.renderer_conformance_artifacts import (
    CANONICAL_CORPUS_CASE_IDS,
)
from tools.rom_tests.full_color.renderer_oracle import derive_expectation
from tools.rom_tests.full_color.snapshots import SemanticSnapshot
from tools.rom_tests.full_color.trace import WriterTrace


ROOT = Path.cwd()
FIXTURES = ROOT / "tools/rom_tests/fixtures/full_color/renderer-conformance"
ROM_IDENTITY = "pokeyellow_debug.gbc:" + "1a" * 32


def _observation(case) -> Phase2Observation:
    snapshot = SemanticSnapshot.from_json(
        (FIXTURES / case.observation_snapshot).read_text(encoding="utf-8")
    )
    snapshot = replace(
        snapshot,
        rom=ROM_IDENTITY,
        evidence_kind="RENDERER_RUNTIME",
        activation_phase=2,
    )
    trace = WriterTrace.from_json(
        (FIXTURES / case.observation_trace).read_text(encoding="utf-8")
    )
    boundary = None
    if case.observation_boundary is not None:
        boundary = BankTortureResult.from_dict(
            json.loads((FIXTURES / case.observation_boundary).read_text(encoding="utf-8")),
            path="boundary",
        )
    return Phase2Observation(case.case_id, ROM_IDENTITY, snapshot, trace, boundary)


def _observations(cases) -> tuple[Phase2Observation, ...]:
    return tuple(_observation(case) for case in cases)


def test_activated_tuple_is_fixed_exact_corpus_with_complete_overlay_matrix() -> None:
    cases = canonical_phase2_cases(ROOT)
    assert ACTIVATED_PHASE2_CASE_IDS == CANONICAL_CORPUS_CASE_IDS
    assert tuple(case.case_id for case in cases) == ACTIVATED_PHASE2_CASE_IDS
    checkpoints = phase2_case_checkpoints()
    assert tuple(checkpoints) == ACTIVATED_PHASE2_CASE_IDS
    assert sum(value == "diagnostic-overlay-matrix" for value in checkpoints.values()) == 14
    assert set(checkpoints.values()) >= {
        "horizontal",
        "vertical",
        "north-route1-connection",
        "map-entry",
        "follower-npc-oam",
        "release-oam-fallback-probe",
        "party-return",
        "map-entry-party-handoff",
        "non-default-banks-interrupt-pressure",
    }


def test_clean_complete_real_rom_provider_passes_independent_checker() -> None:
    cases = canonical_phase2_cases(ROOT)
    reports = check_phase2_observations(cases, _observations(cases))
    assert len(reports) == 25
    assert all(report.passed for report in reports)
    assert {report.mode.value for report in reports} == {"rom_runtime"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("evidence_kind", "SCHEMA_FIXTURE", "wrong provenance"),
        ("activation_phase", 1, "wrong activation phase"),
        ("owner", Owner.RENDERER_YELLOW, "wrong owner"),
        ("generation", 99, "wrong generation"),
        ("scenario", "RC-TRANSFER-COLUMN", "wrong case identity"),
        ("rom", "pokeyellow_debug.gbc:" + "2b" * 32, "wrong ROM identity"),
    ),
)
def test_single_observation_rejects_wrong_provenance_identity_and_owner(
    field: str, value: object, message: str,
) -> None:
    case = canonical_phase2_cases(ROOT)[14]
    clean = _observation(case)
    changed = replace(clean, snapshot=replace(clean.snapshot, **{field: value}))
    with pytest.raises(RendererConformanceError, match=message):
        check_phase2_observation(case, changed)


def test_rom_identity_must_be_exact_debug_product_sha256() -> None:
    case = canonical_phase2_cases(ROOT)[14]
    clean = _observation(case)
    short = replace(
        clean,
        rom_identity="pokeyellow_debug.gbc:abc",
        snapshot=replace(clean.snapshot, rom="pokeyellow_debug.gbc:abc"),
    )
    with pytest.raises(RendererConformanceError, match="exact debug ROM SHA-256"):
        check_phase2_observation(case, short)


def test_provider_requires_one_complete_ordered_atomic_capture() -> None:
    cases = canonical_phase2_cases(ROOT)
    observations = _observations(cases)
    with pytest.raises(RendererConformanceError, match="activated case order"):
        FrozenPhase2Provider(observations[:-1])
    with pytest.raises(RendererConformanceError, match="activated case order"):
        FrozenPhase2Provider((observations[1], observations[0], *observations[2:]))
    mixed = replace(
        observations[-1],
        rom_identity="pokeyellow_debug.gbc:" + "2b" * 32,
        snapshot=replace(
            observations[-1].snapshot,
            rom="pokeyellow_debug.gbc:" + "2b" * 32,
        ),
    )
    with pytest.raises(RendererConformanceError, match="one debug ROM identity"):
        FrozenPhase2Provider((*observations[:-1], mixed))


def test_boundary_presence_case_identity_and_generation_fail_closed() -> None:
    cases = canonical_phase2_cases(ROOT)
    ordinary = cases[14]
    machine = cases[-1]
    machine_observation = _observation(machine)
    with pytest.raises(RendererConformanceError, match="missing or unexpected boundary"):
        check_phase2_observation(machine, replace(machine_observation, boundary=None))
    with pytest.raises(RendererConformanceError, match="missing or unexpected boundary"):
        check_phase2_observation(
            ordinary,
            replace(_observation(ordinary), boundary=machine_observation.boundary),
        )
    assert machine_observation.boundary is not None
    wrong_case = replace(
        machine_observation.boundary,
        case=replace(machine_observation.boundary.case, case_id="BANK-FORGED"),
    )
    with pytest.raises(RendererConformanceError, match="boundary case identity"):
        check_phase2_observation(machine, replace(machine_observation, boundary=wrong_case))
    wrong_generation = replace(
        machine_observation.boundary,
        before=replace(machine_observation.boundary.before, generation=10),
    )
    with pytest.raises(RendererConformanceError, match="boundary generation"):
        check_phase2_observation(
            machine, replace(machine_observation, boundary=wrong_generation)
        )


def test_nonactivated_case_is_rejected_before_checker_dispatch() -> None:
    case = canonical_phase2_cases(ROOT)[0]
    forged_case = replace(case, case_id="RC-PHASE3-NOT-ACTIVATED")
    with pytest.raises(RendererConformanceError, match="not activated"):
        check_phase2_observation(forged_case, _observation(case))


def test_exact_corpus_digest_rejects_any_case_input_drift(tmp_path: Path) -> None:
    destination = tmp_path / "tools/rom_tests/fixtures/full_color/renderer-conformance"
    destination.mkdir(parents=True)
    shutil.copy(FIXTURES / "cases.json", destination / "cases.json")
    payload = json.loads((destination / "cases.json").read_text(encoding="utf-8"))
    payload["cases"][0]["inputs"]["generation"] += 1
    (destination / "cases.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RendererConformanceError, match="authoritative synthetic corpus"):
        canonical_phase2_cases(tmp_path)


def test_named_mutation_sensitivity_is_closed_and_targets_activated_cases() -> None:
    assert tuple(PHASE2_MUTATION_SENSITIVITY) == (
        "MUT-P2-WRONG-OWNER",
        "MUT-P2-INVALID-OWNERSHIP-TRANSITION",
        "MUT-P2-STALE-ADMISSION",
        "MUT-P2-STALE-JOB",
        "MUT-P2-CAPACITY-PLUS-ONE",
        "MUT-P2-LOST-ADMITTED-WORK",
        "MUT-P2-MISSING-ATTRIBUTE",
        "MUT-P2-INSUFFICIENT-PREVISIBLE-BUDGET",
        "MUT-P2-MISSING-RESERVATION",
        "MUT-P2-VISIBLE-MID-COMMIT-INTERRUPTION",
        "MUT-P2-VRAM-OVERLAY-ORACLE",
        "MUT-P2-AMBIENT-MAP-OVERLAY-ORACLE",
        "MUT-P2-OVERLAY-MAPPING-LOSS",
        "MUT-P2-INCOMPLETE-RECONSTRUCTION",
        "MUT-P2-OAM-FALLBACK",
        "MUT-P2-THRESHOLD-PLUS-ONE",
        "MUT-P2-WRAM-BANK-LEAK",
        "MUT-P2-UNEXPECTED-WRITER",
        "MUT-P2-SNAPSHOT-CORRUPTION",
    )
    assert all(case_ids for case_ids in PHASE2_MUTATION_SENSITIVITY.values())
    assert all(
        case_id in ACTIVATED_PHASE2_CASE_IDS
        for case_ids in PHASE2_MUTATION_SENSITIVITY.values()
        for case_id in case_ids
    )


def test_named_snapshot_mutation_produces_useful_checker_diff() -> None:
    case = next(
        item
        for item in canonical_phase2_cases(ROOT)
        if item.case_id == PHASE2_MUTATION_SENSITIVITY["MUT-P2-SNAPSHOT-CORRUPTION"][0]
    )
    clean = _observation(case)
    patch = derive_expectation(case).patches[0]
    changed = bytearray(getattr(clean.snapshot, patch.resource))
    changed[patch.offset] ^= 0xFF
    report = check_phase2_observation(
        case,
        replace(
            clean,
            snapshot=replace(clean.snapshot, **{patch.resource: bytes(changed)}),
        ),
    )
    assert not report.passed
    assert report.differences
    assert report.differences[0].path.startswith(f"{patch.resource}[")
