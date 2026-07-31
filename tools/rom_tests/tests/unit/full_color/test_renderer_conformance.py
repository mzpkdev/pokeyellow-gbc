from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.enums import JobState, Phase
from tools.rom_tests.full_color.renderer_conformance import (
    CONFORMANCE_REPORT_SCHEMA,
    EvidenceMode,
    check_case,
)
from tools.rom_tests.full_color.renderer_conformance_fixtures import (
    FilesystemObservationProvider,
    MUTATIONS,
    MUTATION_CASES,
)
from tools.rom_tests.full_color.renderer_oracle import (
    ConformanceCase,
    derive_expectation,
    load_corpus,
)
from tools.rom_tests.full_color.trace import WriterTrace, WriterTraceEntry

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "tools/rom_tests/fixtures/full_color/renderer-conformance"


def _cases() -> tuple[ConformanceCase, ...]:
    return load_corpus(
        json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    )


CASES = _cases()
CASE_BY_ID = {case.case_id: case for case in CASES}


def _check_with_trace(case_id: str, trace: WriterTrace):
    case = CASE_BY_ID[case_id]
    base = FilesystemObservationProvider(FIXTURES)

    class TraceProvider:
        def snapshot(self, selected: ConformanceCase):
            return base.snapshot(selected)

        def trace(self, selected: ConformanceCase):
            return trace

        def boundary(self, selected: ConformanceCase):
            return base.boundary(selected)

    return check_case(
        case,
        TraceProvider(),
        mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
    )


def _renumbered_trace(
    trace: WriterTrace, entries: list[WriterTraceEntry]
) -> WriterTrace:
    numbered = tuple(
        replace(entry, sequence=index) for index, entry in enumerate(entries)
    )
    return replace(trace, capacity=max(trace.capacity, len(numbered)), entries=numbered)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_hand_authored_observations_conform(case: ConformanceCase) -> None:
    report = check_case(
        case,
        FilesystemObservationProvider(FIXTURES),
        mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
    )
    assert report.passed
    assert report.differences == ()
    assert report.schema == CONFORMANCE_REPORT_SCHEMA
    assert json.loads(report.to_json()) == report.to_dict()


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        ("wrong-attribute-byte", "bg_attributes[0x07c0]"),
        ("lost-clipped-coordinate", "overlay_request.clipped_mappings"),
        ("partial-paired-commit", "bg_attributes[0x0062]"),
        ("saved-byte-reconstruction", "reconstruction.item_provenance"),
        ("missing-oam-fallback", "oam_fallback.occurred"),
        ("oam-control-bit-loss", "oam_fallback.after_attributes"),
        ("wrong-owner-writer", "trace[0].owner"),
        ("stale-generation-writer", "trace[0].generation"),
        ("write-after-cancellation", "trace[2].writer_id"),
        ("bank-leak", "boundary.after.banks.wram"),
        ("stack-pointer-leak", "boundary.after.stack_pointer"),
        ("stack-window-leak", "boundary.after.stack_window[0x00]"),
        ("ime-leak", "boundary.after.interrupt_master_enabled"),
        ("interrupt-enable-leak", "boundary.after.interrupt_enable"),
        ("interrupt-flags-leak", "boundary.after.interrupt_flags"),
    ],
)
def test_named_mutation_fails_at_exact_path(mutation: str, path: str) -> None:
    case = CASE_BY_ID[MUTATION_CASES[mutation]]
    report = check_case(
        case,
        FilesystemObservationProvider(FIXTURES, mutation),
        mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
    )
    assert not report.passed
    assert report.differences[0].path == path


def test_mutations_change_only_their_declared_case_observation() -> None:
    assert set(MUTATIONS) == set(MUTATION_CASES)
    for mutation, target in MUTATION_CASES.items():
        provider = FilesystemObservationProvider(FIXTURES, mutation)
        for case in CASES:
            changed = (
                provider.raw_snapshot(case) != provider.raw_snapshot(case, mutate=False)
                or provider.raw_trace(case) != provider.raw_trace(case, mutate=False)
                or provider.raw_boundary(case)
                != provider.raw_boundary(case, mutate=False)
            )
            assert changed is (case.case_id == target)


def test_synthetic_evidence_cannot_be_promoted_to_runtime() -> None:
    case = CASES[0]
    with pytest.raises(
        RendererConformanceError,
        match="runtime evidence requires RENDERER_RUNTIME and a nonzero activation phase",
    ):
        check_case(
            case,
            FilesystemObservationProvider(FIXTURES),
            mode=EvidenceMode.ROM_RUNTIME,
        )


def test_runtime_mode_requires_nonzero_renderer_runtime_evidence() -> None:
    case = CASES[0]
    base = FilesystemObservationProvider(FIXTURES)

    class RuntimeProvider:
        def snapshot(self, selected: ConformanceCase):
            return replace(
                base.snapshot(selected),
                evidence_kind="RENDERER_RUNTIME",
                activation_phase=2,
            )

        def trace(self, selected: ConformanceCase):
            return base.trace(selected)

        def boundary(self, selected: ConformanceCase):
            return base.boundary(selected)

    assert check_case(case, RuntimeProvider(), mode=EvidenceMode.ROM_RUNTIME).passed
    with pytest.raises(
        RendererConformanceError,
        match="synthetic evidence must remain a phase-0 SCHEMA_FIXTURE",
    ):
        check_case(
            case,
            RuntimeProvider(),
            mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
        )


def test_malformed_carrier_is_normalized_with_case_and_carrier_name(
    tmp_path: Path,
) -> None:
    shutil.copytree(FIXTURES, tmp_path / "fixtures")
    case = CASES[0]
    path = tmp_path / "fixtures" / case.observation_snapshot
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["bg_tile_ids"] = "00"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(
        RendererConformanceError,
        match=rf"{case.case_id}: malformed semantic snapshot: snapshot.bg_tile_ids",
    ):
        check_case(
            case,
            FilesystemObservationProvider(tmp_path / "fixtures"),
            mode=EvidenceMode.SYNTHETIC_CHECKER_SELF_TEST,
        )


def test_provider_rejects_path_escape_before_reading() -> None:
    case = replace(CASES[0], observation_snapshot="../outside.snapshot.json")
    with pytest.raises(RendererConformanceError, match="escapes fixture root"):
        FilesystemObservationProvider(FIXTURES).snapshot(case)


def test_all_observation_carriers_exist_at_canonical_unique_paths() -> None:
    paths = [
        path
        for case in CASES
        for path in (
            case.observation_snapshot,
            case.observation_trace,
            case.observation_boundary,
        )
        if path is not None
    ]
    assert len(paths) == len(set(paths))
    assert all((FIXTURES / path).is_file() for path in paths)


@pytest.mark.parametrize("position", ["before", "after"])
def test_undeclared_job_is_rejected_on_either_side_of_commit(position: str) -> None:
    case = CASE_BY_ID["RC-TRANSFER-ROW"]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    extra = replace(
        trace.entries[0],
        job_id="JOB-UNDECLARED",
        job_state=JobState.PREPARED,
        wrote=False,
    )
    entries = list(trace.entries)
    entries.insert(0 if position == "before" else len(entries), extra)

    report = _check_with_trace(case.case_id, _renumbered_trace(trace, entries))

    assert not report.passed
    assert any(
        difference.path.endswith(".job_id") and difference.actual == "JOB-UNDECLARED"
        for difference in report.differences
    )


def test_permitted_writer_cannot_write_for_an_undeclared_job() -> None:
    case = CASE_BY_ID["RC-TRANSFER-ROW"]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    extra = replace(
        trace.entries[1],
        job_id="JOB-UNDECLARED",
        resource_id=1,
        job_state=JobState.COMMITTING,
        wrote=True,
    )
    entries = [*trace.entries[:-1], extra, trace.entries[-1]]

    report = _check_with_trace(case.case_id, _renumbered_trace(trace, entries))

    assert not report.passed
    assert any(
        difference.path.endswith(".job_id") and difference.actual == "JOB-UNDECLARED"
        for difference in report.differences
    )


def test_oam_unbound_trace_permission_is_observational_only() -> None:
    case = CASE_BY_ID["RC-OAM-MISSING_IDENTITY"]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    assert _check_with_trace(case.case_id, trace).passed
    writing_entry = replace(trace.entries[0], commit_unit_id="MU-EXTRA", wrote=True)

    report = _check_with_trace(case.case_id, replace(trace, entries=(writing_entry,)))

    assert not report.passed
    assert any(
        difference.path == "trace[0].wrote"
        and difference.expected == "non-writing observational evidence"
        for difference in report.differences
    )


def test_complete_commit_rejects_arbitrary_replacement_resource_ids() -> None:
    case = CASE_BY_ID["RC-TRANSFER-ROW"]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    entries = [
        replace(entry, resource_id=99)
        if entry.wrote and entry.resource_id == 2
        else entry
        for entry in trace.entries
    ]

    report = _check_with_trace(case.case_id, replace(trace, entries=tuple(entries)))

    assert not report.passed
    assert any(
        difference.path == "trace.complete_commit"
        and difference.actual["written_resources"]
        == ["<unmapped:99>", "bg_tile_ids"]
        for difference in report.differences
    )


def test_complete_commit_rejects_an_extra_resource_write() -> None:
    case = CASE_BY_ID["RC-TRANSFER-ROW"]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    extra = replace(trace.entries[1], resource_id=3)
    entries = [*trace.entries[:-1], extra, trace.entries[-1]]

    report = _check_with_trace(case.case_id, _renumbered_trace(trace, entries))

    assert not report.passed
    assert any(
        difference.path == "trace.complete_commit"
        and difference.actual["written_resources"]
        == ["<unmapped:3>", "bg_attributes", "bg_tile_ids"]
        for difference in report.differences
    )


def test_trace_phase_must_match_the_oracle_predicate() -> None:
    case = CASE_BY_ID["RC-TRANSFER-ROW"]
    expectation = derive_expectation(case)
    assert expectation.trace.required_phase is Phase.OVERWORLD_ACTIVE
    trace = FilesystemObservationProvider(FIXTURES).trace(case)
    entries = (
        replace(trace.entries[0], phase=Phase.OVERWORLD_OVERLAY),
        *trace.entries[1:],
    )

    report = _check_with_trace(case.case_id, replace(trace, entries=entries))

    assert not report.passed
    assert any(
        difference.path == "trace[0].phase"
        and difference.expected == "OVERWORLD_ACTIVE"
        and difference.actual == "OVERWORLD_OVERLAY"
        for difference in report.differences
    )


def test_bg_palette_commit_rejects_obj_palette_resource_substitution() -> None:
    case = CASE_BY_ID["RC-PALETTE-BG"]
    expectation = derive_expectation(case)
    assert expectation.trace.required_written_resources == ("bg_palettes",)
    trace = FilesystemObservationProvider(FIXTURES).trace(case)

    report = _check_with_trace(
        case.case_id,
        replace(trace, resource_identities={1: "obj_palettes"}),
    )

    assert not report.passed
    assert any(
        difference.path == "trace.complete_commit"
        and difference.expected["written_resources"] == ["bg_palettes"]
        and difference.actual["written_resources"] == ["obj_palettes"]
        for difference in report.differences
    )


@pytest.mark.parametrize(
    ("case_id", "resources"),
    [
        ("RC-TRANSFER-ROW", ["bg_attributes", "bg_tile_ids"]),
        ("RC-PALETTE-BG", ["bg_palettes"]),
        ("RC-PALETTE-OBJ", ["obj_palettes"]),
        ("RC-RECONSTRUCTION", ["reconstructed_scene"]),
        ("RC-OWNERSHIP-REPLACEMENT", ["ownership_generation"]),
    ],
)
def test_exact_intended_positive_trace_resources(
    case_id: str, resources: list[str]
) -> None:
    case = CASE_BY_ID[case_id]
    trace = FilesystemObservationProvider(FIXTURES).trace(case)

    assert (
        sorted(
            trace.resource_identities[entry.resource_id]
            for entry in trace.entries
            if entry.wrote
        )
        == resources
    )
    assert _check_with_trace(case_id, trace).passed
