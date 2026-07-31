from __future__ import annotations

import inspect
import json
from copy import deepcopy
from dataclasses import replace
from functools import reduce
from pathlib import Path

import pytest

from tools.rom_tests.full_color.bank_torture import BankTortureCase
from tools.rom_tests.full_color.enums import (
    CancellationReason,
    JobState,
    OAMFallbackKind,
    Owner,
    Phase,
)
from tools.rom_tests.full_color.errors import RendererConformanceError
from tools.rom_tests.full_color.renderer_oracle import (
    CONFORMANCE_CASE_SCHEMA,
    MachineStatePredicate,
    OperationKind,
    ConformanceCase,
    derive_expectation,
    load_corpus,
)
from tools.rom_tests.full_color.snapshots import (
    OAMFallbackState,
    OverlayRequestState,
    ReconstructionState,
)
from tools.rom_tests.full_color.trace import WriterTrace, WriterTraceEntry


CORPUS_PATH = (
    Path(__file__).parents[3] / "fixtures/full_color/renderer-conformance/cases.json"
)


def corpus_dict() -> dict[str, object]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def corpus() -> tuple[ConformanceCase, ...]:
    return load_corpus(corpus_dict())


def case_dict(case_id: str) -> dict[str, object]:
    for raw in corpus_dict()["cases"]:  # type: ignore[index,union-attr]
        if raw["case_id"] == case_id:
            return raw
    raise AssertionError(f"missing fixture case {case_id}")


def case(case_id: str) -> ConformanceCase:
    for parsed in corpus():
        if parsed.case_id == case_id:
            return parsed
    raise AssertionError(f"missing fixture case {case_id}")


def test_oracle_public_seam_accepts_only_authoritative_case() -> None:
    assert tuple(inspect.signature(derive_expectation).parameters) == ("case",)
    module = inspect.getmodule(derive_expectation)
    assert module is not None
    source = inspect.getsource(module)
    for forbidden in (
        "runtime_observability",
        "Emulator",
        "SemanticSnapshot",
        "WriterTrace",
    ):
        assert forbidden not in source


def test_case_schema_is_closed_versioned_and_deeply_immutable() -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    parsed = ConformanceCase.from_dict(raw)
    assert parsed.schema == CONFORMANCE_CASE_SCHEMA
    with pytest.raises(TypeError):
        parsed.inputs["tile_ids"] = "00"  # type: ignore[index]
    with pytest.raises(TypeError):
        parsed.inputs["rectangle"]["x"] = 0  # type: ignore[index]

    raw["extra"] = True
    with pytest.raises(RendererConformanceError, match=r"case: unknown fields: extra"):
        ConformanceCase.from_dict(raw)
    raw = case_dict("RC-TRANSFER-ROW")
    raw["schema"] = "future-version"
    with pytest.raises(RendererConformanceError, match=r"case.schema: unsupported"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("requirements", ["R99.1"], "unknown R IDs"),
        ("checks", ["CHK-NOT-REAL"], "unknown CHK- IDs"),
        ("requirements", ["R7.1", "R7.1"], "duplicate IDs"),
        ("checks", ["CHK-COMMIT-01", "CHK-COMMIT-01"], "duplicate IDs"),
    ],
)
def test_case_rejects_unknown_and_duplicate_contract_ids(
    field: str, value: object, match: str
) -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    raw[field] = value
    with pytest.raises(RendererConformanceError, match=match):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "path",
    ["/absolute.snapshot.json", "../parent.snapshot.json", "a/../b.snapshot.json", "."],
)
def test_case_rejects_non_relative_observation_paths(path: str) -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    raw["observation_snapshot"] = path
    with pytest.raises(RendererConformanceError, match="normalized relative path"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    ("field", "value", "suffix"),
    [
        ("observation_snapshot", "observations/case.trace.json", ".snapshot.json"),
        ("observation_trace", "observations/case.snapshot.json", ".trace.json"),
        ("observation_boundary", "observations/case.trace.json", ".boundary.json"),
    ],
)
def test_case_requires_the_declared_observation_carrier_suffix(
    field: str, value: str, suffix: str
) -> None:
    raw = case_dict("RC-MACHINE-FAR-CALL")
    raw[field] = value
    with pytest.raises(RendererConformanceError, match=rf"expected {suffix}"):
        ConformanceCase.from_dict(raw)


def test_case_rejects_a_normalized_directory_like_observation_path() -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    raw["observation_snapshot"] = "observations"
    with pytest.raises(RendererConformanceError, match="carrier suffix"):
        ConformanceCase.from_dict(raw)


def test_case_rejects_empty_and_reused_observation_paths() -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    raw["observation_snapshot"] = ""
    with pytest.raises(RendererConformanceError, match="non-empty string"):
        ConformanceCase.from_dict(raw)

    raw = case_dict("RC-TRANSFER-ROW")
    raw["observation_snapshot"] = raw["observation_trace"]
    with pytest.raises(RendererConformanceError, match="snapshot.json carrier suffix"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize("carrier", ["snapshot", "trace"])
def test_corpus_rejects_cross_case_observation_aliases(carrier: str) -> None:
    raw = corpus_dict()
    cases = raw["cases"]  # type: ignore[index]
    cases[1][f"observation_{carrier}"] = cases[0][f"observation_{carrier}"]
    with pytest.raises(RendererConformanceError, match="globally unique"):
        load_corpus(raw)


def test_corpus_rejects_cross_case_boundary_alias() -> None:
    raw = corpus_dict()
    cases = raw["cases"]  # type: ignore[index]
    original = next(
        item for item in cases if item["case_id"] == "RC-MACHINE-FAR-CALL"
    )
    alias = deepcopy(original)
    alias["case_id"] = "RC-MACHINE-FAR-CALL-ALIAS"
    alias["observation_snapshot"] = (
        "observations/RC-MACHINE-FAR-CALL-ALIAS.snapshot.json"
    )
    alias["observation_trace"] = "observations/RC-MACHINE-FAR-CALL-ALIAS.trace.json"
    cases.append(alias)
    with pytest.raises(RendererConformanceError, match="globally unique"):
        load_corpus(raw)


def test_corpus_requires_canonical_case_owned_observation_paths() -> None:
    raw = corpus_dict()
    raw["cases"][0]["observation_snapshot"] = (  # type: ignore[index]
        "observations/not-this-case.snapshot.json"
    )
    with pytest.raises(RendererConformanceError, match="canonical case-owned path"):
        load_corpus(raw)


def test_corpus_rejects_case_ids_that_differ_only_by_case() -> None:
    raw = corpus_dict()
    original = raw["cases"][0]  # type: ignore[index]
    alias = deepcopy(original)
    alias["case_id"] = original["case_id"].lower()
    alias["observation_snapshot"] = original["observation_snapshot"].lower()
    alias["observation_trace"] = original["observation_trace"].lower()
    raw["cases"].append(alias)  # type: ignore[index,union-attr]
    with pytest.raises(RendererConformanceError, match="duplicate case IDs"):
        load_corpus(raw)


@pytest.mark.parametrize("carrier", ["snapshot", "trace", "boundary"])
def test_corpus_rejects_observation_paths_that_differ_only_by_case(
    carrier: str,
) -> None:
    raw = corpus_dict()
    cases = raw["cases"]  # type: ignore[index]
    suffix = f".{carrier}.json"
    if carrier == "boundary":
        original = next(
            item for item in cases if item["case_id"] == "RC-MACHINE-FAR-CALL"
        )
        alias = deepcopy(original)
        alias["case_id"] = "RC-MACHINE-FAR-CALL-CASE-ALIAS"
        alias["observation_snapshot"] = (
            "observations/RC-MACHINE-FAR-CALL-CASE-ALIAS.snapshot.json"
        )
        alias["observation_trace"] = (
            "observations/RC-MACHINE-FAR-CALL-CASE-ALIAS.trace.json"
        )
        original_path = original["observation_boundary"]
        alias["observation_boundary"] = (
            original_path.removesuffix(suffix).swapcase() + suffix
        )
        cases.append(alias)
    else:
        original_path = cases[0][f"observation_{carrier}"]
        cases[1][f"observation_{carrier}"] = (
            original_path.removesuffix(suffix).swapcase() + suffix
        )
    with pytest.raises(RendererConformanceError, match="globally unique"):
        load_corpus(raw)


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("expected_bg_attributes", "07", "expected-output"),
        ("actual_bytes", "07", "observed"),
        ("oracle_sources", ["REQUEST_DATA", "VRAM"], "forbidden oracle authority"),
        ("ambient", "AMBIENT_MAP", "forbidden oracle authority"),
    ],
)
def test_oracle_rejects_expected_output_and_ambient_sources(
    key: str, value: object, match: str
) -> None:
    raw = case_dict("RC-OVERLAY-PARTIAL-CLIP")
    raw["inputs"][key] = value  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match=match):
        ConformanceCase.from_dict(raw)


def test_overlay_clips_before_classification_and_preserves_both_mappings() -> None:
    result = derive_expectation(case("RC-OVERLAY-PARTIAL-CLIP"))
    assert [(p.resource, p.offset, p.expected.hex()) for p in result.patches] == [
        ("bg_tile_ids", 0x07C0, "11"),
        ("bg_attributes", 0x07C0, "07"),
        ("bg_tile_ids", 0x07E0, "13"),
        ("bg_attributes", 0x07E0, "03"),
    ]
    fields = dict(result.fields)
    assert fields["overlay_request.oracle_sources"] == ["REQUEST_DATA"]
    assert fields["overlay_request.clipped_mappings"] == [
        {
            "source_index": 1,
            "destination_x": 0,
            "destination_y": 30,
            "world_x": 101,
            "world_y": 200,
        },
        {
            "source_index": 3,
            "destination_x": 0,
            "destination_y": 31,
            "world_x": 101,
            "world_y": 201,
        },
    ]


def test_overlay_precedence_and_bit_four_canonicalization() -> None:
    explicit = derive_expectation(case("RC-OVERLAY-OPAQUE-EXPLICIT"))
    default = derive_expectation(case("RC-OVERLAY-OPAQUE-DEFAULT"))
    lookup = derive_expectation(case("RC-OVERLAY-REVEALED-LOOKUP"))
    override = derive_expectation(case("RC-OVERLAY-REVEALED-OVERRIDE"))
    assert explicit.patches[1].expected == b"\xef"
    assert default.patches[1].expected == b"\x02"
    assert lookup.patches[1].expected == b"\x07"
    assert override.patches[1].expected == b"\x87"
    assert all(
        byte & 0x10 == 0
        for result in (explicit, default, lookup, override)
        for byte in result.patches[1].expected
    )


@pytest.mark.parametrize(
    ("case_id", "offsets", "attributes"),
    [
        ("RC-OVERLAY-PARTIAL-RIGHT", [127, 159], ["ef", "02"]),
        ("RC-OVERLAY-PARTIAL-TOP", [3], ["0203"]),
        ("RC-OVERLAY-PARTIAL-BOTTOM", [995], ["ef07"]),
        ("RC-OVERLAY-MAP-EDGE", [990, 1022], ["ef02", "0287"]),
        ("RC-OVERLAY-CONNECTION", [0, 32], ["ef02", "0287"]),
        ("RC-OVERLAY-WINDOW", [1057, 1089], ["ef02", "0287"]),
        ("RC-OVERLAY-ALTERNATE-BG", [1057, 1089], ["ef02", "0287"]),
        ("RC-OVERLAY-ALTERNATE-MAP", [33, 65], ["ef02", "0287"]),
    ],
)
def test_overlay_matrix_arithmetic_and_outputs_are_independent(
    case_id: str, offsets: list[int], attributes: list[str]
) -> None:
    result = derive_expectation(case(case_id))
    assert [
        patch.offset for patch in result.patches if patch.resource == "bg_tile_ids"
    ] == offsets
    assert [
        patch.expected.hex()
        for patch in result.patches
        if patch.resource == "bg_attributes"
    ] == attributes
    assert any(byte & 0xE7 for patch in result.patches[1::2] for byte in patch.expected)


def test_overlay_rejects_singular_transform_and_mislabeled_matrix_case() -> None:
    raw = case_dict("RC-OVERLAY-CONNECTION")
    raw["inputs"]["world_transform"] = [1, 2, 2, 4, 0, 0]  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="singular transform"):
        ConformanceCase.from_dict(raw)


def test_ordinary_overlay_must_be_unclipped_and_have_a_writer_and_commit() -> None:
    raw = case_dict("RC-OVERLAY-OPAQUE-EXPLICIT")
    raw["inputs"]["rectangle"]["x"] = -1  # type: ignore[index]
    raw["inputs"]["writer_ids"] = []  # type: ignore[index]
    raw["inputs"]["commit_unit_id"] = None  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="one unclipped"):
        ConformanceCase.from_dict(raw)

    raw = case_dict("RC-OVERLAY-OPAQUE-EXPLICIT")
    raw["inputs"]["writer_ids"] = []  # type: ignore[index]
    raw["inputs"]["commit_unit_id"] = None  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="writer and commit"):
        ConformanceCase.from_dict(raw)


def test_connection_overlay_requires_declared_connection_geometry() -> None:
    raw = case_dict("RC-OVERLAY-CONNECTION")
    raw["inputs"]["rectangle"]["x"] = 1  # type: ignore[index]
    raw["inputs"]["rectangle"]["y"] = 1  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="connection case is mislabeled"):
        ConformanceCase.from_dict(raw)

    raw = case_dict("RC-OVERLAY-CONNECTION")
    raw["inputs"]["matrix_key"] = "OVERLAY-ALTERNATE-BG"  # type: ignore[index]
    with pytest.raises(
        RendererConformanceError, match="alternate-BG case is mislabeled"
    ):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    ("case_id", "canonical_destination"),
    [
        ("RC-OVERLAY-WINDOW", "WINDOW_MAP_9C00"),
        ("RC-OVERLAY-ALTERNATE-BG", "BG_MAP_9C00"),
        ("RC-OVERLAY-ALTERNATE-MAP", "BG_MAP_9800"),
    ],
)
def test_named_destination_overlay_pins_canonical_identity_and_destination(
    case_id: str, canonical_destination: str
) -> None:
    raw = case_dict(case_id)
    raw["inputs"]["map_id"] = "CERULEAN_CITY"  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="case is mislabeled"):
        ConformanceCase.from_dict(raw)

    raw = case_dict(case_id)
    raw["inputs"]["destination_selector"] = (
        "BG_MAP_9800" if canonical_destination != "BG_MAP_9800" else "BG_MAP_9C00"
    )  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="case is mislabeled"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "case_id",
    [
        "RC-OVERLAY-WINDOW",
        "RC-OVERLAY-ALTERNATE-BG",
        "RC-OVERLAY-ALTERNATE-MAP",
    ],
)
@pytest.mark.parametrize(("x", "width"), [(-1, 2), (-2, 2)])
def test_named_destination_overlay_cannot_be_partially_or_fully_clipped(
    case_id: str, x: int, width: int
) -> None:
    raw = case_dict(case_id)
    raw["inputs"]["rectangle"]["x"] = x  # type: ignore[index]
    raw["inputs"]["rectangle"]["width"] = width  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="case is mislabeled"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "case_id",
    [
        "RC-OVERLAY-WINDOW",
        "RC-OVERLAY-ALTERNATE-BG",
        "RC-OVERLAY-ALTERNATE-MAP",
    ],
)
@pytest.mark.parametrize(
    ("field", "value"),
    [("writer_ids", []), ("commit_unit_id", None)],
)
def test_named_destination_overlay_requires_writer_and_commit(
    case_id: str, field: str, value: object
) -> None:
    raw = case_dict(case_id)
    raw["inputs"][field] = value  # type: ignore[index]
    with pytest.raises(
        RendererConformanceError,
        match="overlay with surviving cells requires a writer and commit unit",
    ):
        ConformanceCase.from_dict(raw)


def test_fully_clipped_overlay_has_no_patch_writer_job_or_commit() -> None:
    result = derive_expectation(case("RC-OVERLAY-FULLY-CLIPPED"))
    assert result.patches == ()
    assert result.trace.permitted_writer_ids == ("WR-NONE",)
    assert result.trace.jobs == ()
    assert result.trace.commit_unit_id is None
    assert result.trace.require_complete_commit is False
    assert result.trace.require_no_writes is True

    trace = WriterTrace(
        capacity=1,
        entries=(),
        permitted_writer_ids=result.trace.permitted_writer_ids,
    )
    assert WriterTrace.from_json(trace.to_json()) == trace
    assert result.trace.accepts_observed_writes(
        entry.wrote for entry in trace.entries
    )


@pytest.mark.parametrize("writer_id", ["WR-NONE", "WR-OTHER"])
def test_fully_clipped_overlay_rejects_any_canonical_trace_write(
    writer_id: str,
) -> None:
    predicate = derive_expectation(case("RC-OVERLAY-FULLY-CLIPPED")).trace
    trace = WriterTrace(
        capacity=1,
        entries=(
            WriterTraceEntry(
                sequence=0,
                frame=0,
                generation=1,
                job_generation=1,
                owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
                phase=Phase.OVERWORLD_OVERLAY,
                job_owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
                job_state=JobState.COMMITTING,
                cancellation_reason=None,
                writer_id=writer_id,
                commit_unit_id="MU-ADVERSARIAL-WRITE",
                job_id="JOB-ADVERSARIAL-WRITE",
                request_id="REQ-ADVERSARIAL-WRITE",
                resource_id=1,
                wrote=True,
            ),
        ),
        permitted_writer_ids=(writer_id,),
    )
    canonical = WriterTrace.from_json(trace.to_json())
    assert not predicate.accepts_observed_writes(
        entry.wrote for entry in canonical.entries
    )


def test_no_write_trace_predicate_rejects_conflicting_commit_semantics() -> None:
    no_write = derive_expectation(case("RC-OVERLAY-FULLY-CLIPPED")).trace
    writing = derive_expectation(case("RC-TRANSFER-ROW")).trace

    with pytest.raises(RendererConformanceError, match="cannot declare jobs"):
        replace(writing, require_no_writes=True)
    with pytest.raises(RendererConformanceError, match="complete commit"):
        replace(
            no_write,
            require_complete_commit=True,
            commit_unit_id="MU-CONFLICT",
        )
    with pytest.raises(RendererConformanceError, match="cannot name a commit unit"):
        replace(no_write, commit_unit_id="MU-CONFLICT")


@pytest.mark.parametrize("case_id", ["RC-OAM-MISSING_IDENTITY", "RC-MACHINE-FAR-CALL"])
def test_empty_job_predicates_that_may_have_trace_evidence_allow_writes(
    case_id: str,
) -> None:
    predicate = derive_expectation(case(case_id)).trace
    assert predicate.jobs == ()
    assert predicate.require_complete_commit is False
    assert predicate.require_no_writes is False
    assert predicate.accepts_observed_writes((True,))


@pytest.mark.parametrize("writer_ids", [[], ["WR-OTHER"]])
def test_fully_clipped_overlay_requires_canonical_nonwriting_allowlist(
    writer_ids: list[str],
) -> None:
    raw = case_dict("RC-OVERLAY-FULLY-CLIPPED")
    raw["inputs"]["writer_ids"] = writer_ids  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match=r"allowlist \[WR-NONE\]"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "case_id",
    [
        "RC-OVERLAY-FULLY-CLIPPED",
        "RC-OVERLAY-PARTIAL-CLIP",
        "RC-OVERLAY-PARTIAL-RIGHT",
        "RC-OVERLAY-PARTIAL-TOP",
        "RC-OVERLAY-PARTIAL-BOTTOM",
    ],
)
@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("map_id", "VIRIDIAN_CITY", "wrong destination, map, or tileset"),
        ("tileset_id", "FOREST", "canonical OVERWORLD"),
        (
            "destination_selector",
            "WINDOW_MAP_9800",
            "wrong destination, map, or tileset",
        ),
        (
            "classifications",
            ["REVEALED_TERRAIN"] * 4,
            "alternating mixed classifications",
        ),
        ("explicit_attributes", {}, "all four attribute-source precedence branches"),
        ("coordinate_overrides", {}, "all four attribute-source precedence branches"),
    ],
)
def test_clipped_overlay_contract_rejects_semantic_and_precedence_mutations(
    case_id: str, field: str, value: object, match: str
) -> None:
    raw = case_dict(case_id)
    raw["inputs"][field] = value  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match=match):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    ("case_id", "x", "y"),
    [
        ("RC-OVERLAY-PARTIAL-CLIP", -1, -1),
        ("RC-OVERLAY-PARTIAL-RIGHT", 31, -1),
        ("RC-OVERLAY-PARTIAL-TOP", -1, -1),
        ("RC-OVERLAY-PARTIAL-BOTTOM", -1, 31),
    ],
)
def test_partial_overlay_must_cross_only_its_declared_edge(
    case_id: str, x: int, y: int
) -> None:
    raw = case_dict(case_id)
    raw["inputs"]["rectangle"]["x"] = x  # type: ignore[index]
    raw["inputs"]["rectangle"]["y"] = y  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="partially clipped edge"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    ("case_id", "patches"),
    [
        (
            "RC-TRANSFER-ROW",
            [("bg_tile_ids", 98, "102030"), ("bg_attributes", 98, "8192a3")],
        ),
        (
            "RC-TRANSFER-COLUMN",
            [
                ("bg_tile_ids", 95, "40"),
                ("bg_attributes", 95, "b4"),
                ("bg_tile_ids", 127, "50"),
                ("bg_attributes", 127, "c5"),
                ("bg_tile_ids", 159, "60"),
                ("bg_attributes", 159, "d6"),
            ],
        ),
    ],
)
def test_paired_transfer_emits_equal_bank_zero_and_bank_one_rows(
    case_id: str, patches: list[tuple[str, int, str]]
) -> None:
    result = derive_expectation(case(case_id))
    assert [(p.resource, p.offset, p.expected.hex()) for p in result.patches] == patches
    assert result.trace.require_complete_commit
    assert result.trace.jobs[0].required_states == (
        JobState.PREPARED,
        JobState.COMMITTING,
        JobState.COMPLETE,
    )


def test_palette_upload_requires_and_emits_complete_payloads() -> None:
    for case_id, resource in (
        ("RC-PALETTE-BG", "bg_palettes"),
        ("RC-PALETTE-OBJ", "obj_palettes"),
    ):
        result = derive_expectation(case(case_id))
        assert result.patches[0].resource == resource
        assert len(result.patches[0].expected) == 64
    raw = case_dict("RC-PALETTE-BG")
    raw["inputs"]["payload"] = "00" * 63  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="exactly 64 bytes"):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "case_id",
    ["RC-TRANSFER-ROW", "RC-PALETTE-BG", "RC-RECONSTRUCTION"],
)
def test_committing_operations_reject_a_null_commit_unit(case_id: str) -> None:
    raw = case_dict(case_id)
    raw["inputs"]["commit_unit_id"] = None  # type: ignore[index]
    with pytest.raises(
        RendererConformanceError,
        match="complete commit requires a concrete commit unit ID",
    ):
        ConformanceCase.from_dict(raw)


def test_replacement_job_rejects_a_null_commit_unit() -> None:
    raw = case_dict("RC-OWNERSHIP-REPLACEMENT")
    raw["inputs"]["commit_unit_id"] = None  # type: ignore[index]
    with pytest.raises(
        RendererConformanceError,
        match="replacement commit requires a unit ID",
    ):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "case_id", ["RC-OAM-MISSING_IDENTITY", "RC-MACHINE-FAR-CALL"]
)
def test_noncommitting_operations_accept_null_commit_and_do_not_require_one(
    case_id: str,
) -> None:
    result = derive_expectation(case(case_id))
    assert result.trace.commit_unit_id is None
    assert result.trace.require_complete_commit is False


@pytest.mark.parametrize(
    ("case_id", "kind"),
    [
        ("RC-OAM-MISSING_IDENTITY", OAMFallbackKind.MISSING_IDENTITY),
        ("RC-OAM-OUT_OF_RANGE_IDENTITY", OAMFallbackKind.OUT_OF_RANGE_IDENTITY),
        ("RC-OAM-UNMAPPED_IDENTITY", OAMFallbackKind.UNMAPPED_IDENTITY),
    ],
)
def test_oam_fallback_preserves_control_bits_and_records_reason(
    case_id: str, kind: OAMFallbackKind
) -> None:
    result = derive_expectation(case(case_id))
    assert result.patches[0].expected == b"\xf8"
    fields = dict(result.fields)
    assert fields["oam_fallback.occurred"] is True
    assert fields["oam_fallback.fallback_kind"] == kind.value
    assert dict(result.fields)["oam_fallback.palette"] == 0
    assert fields["oam_fallback.generation"] == 5
    assert fields["oam_fallback.writer_id"] == f"WR-{case_id}"
    assert fields["oam_fallback.before_attributes"] == 0xFD
    assert fields["oam_fallback.after_attributes"] == 0xF8


def test_oam_unmapped_classification_uses_authoritative_mapped_identity_set() -> None:
    raw = case_dict("RC-OAM-UNMAPPED_IDENTITY")
    raw["inputs"]["final_picture_identity"] = 1  # type: ignore[index]
    with pytest.raises(
        RendererConformanceError, match="mapped identity cannot claim fallback"
    ):
        ConformanceCase.from_dict(raw, mapped_picture_identities=frozenset({1, 2, 3, 7}))


@pytest.mark.parametrize(
    ("authority", "match"),
    [
        ([], "expected complete synthetic authority"),
        ([1], "expected complete synthetic authority"),
        ([1, 1], "duplicate identity"),
        ([1, 2, 3, 7, 300], r"\[4\].*0\.\.255"),
    ],
)
def test_corpus_rejects_incomplete_or_inconsistent_oam_authority(
    authority: list[int], match: str
) -> None:
    raw = corpus_dict()
    raw["authoritative_mapped_picture_identities"] = authority
    with pytest.raises(RendererConformanceError, match=match):
        load_corpus(raw)


def test_oam_case_cannot_supply_a_contradictory_local_mapping() -> None:
    raw = corpus_dict()
    for item in raw["cases"]:  # type: ignore[union-attr]
        if item["case_id"] == "RC-OAM-UNMAPPED_IDENTITY":
            item["inputs"]["mapped_picture_identities"] = [42]
            break
    with pytest.raises(
        RendererConformanceError, match="unknown fields: mapped_picture_identities"
    ):
        load_corpus(raw)


def test_reconstruction_requires_poison_authority_and_one_barrier() -> None:
    result = derive_expectation(case("RC-RECONSTRUCTION"))
    fields = dict(result.fields)
    required_items = fields["reconstruction.required_items"]
    assert isinstance(required_items, list)
    assert len(required_items) == 8
    assert (
        fields["reconstruction.completed_items"]
        == fields["reconstruction.required_items"]
    )
    assert (
        fields["reconstruction.poisoned_items"]
        == fields["reconstruction.required_items"]
    )
    assert fields["reconstruction.presentation_barrier_count"] == 1

    assert (
        fields["reconstruction.item_provenance"]["tilemaps_and_attributes"]
        == "FRESHLY_GENERATED_STATE"
    )


def test_ownership_jobs_separate_cancelled_old_and_legitimate_replacement() -> None:
    result = derive_expectation(case("RC-OWNERSHIP-REPLACEMENT"))
    old, replacement = result.trace.jobs
    assert old.job_id == "JOB-OLD"
    assert old.required_states[-1] is JobState.CANCELLED
    assert old.cancellation_reason is CancellationReason.SUPERSEDED
    assert old.forbid_later_writes
    assert replacement.job_id == "JOB-REPLACEMENT"
    assert replacement.required_states[-1] is JobState.COMPLETE
    assert replacement.cancellation_reason is None
    assert dict(result.fields) == {
        "owner": "RENDERER_FULL_COLOR_OVERWORLD",
        "generation": 8,
    }


def test_machine_restore_requires_full_bank_stack_and_interrupt_predicate() -> None:
    result = derive_expectation(case("RC-MACHINE-FAR-CALL"))
    assert result.machine == MachineStatePredicate(
        require_banks_restored=True,
        require_stack_pointer_restored=True,
        require_stack_window_restored=True,
        require_interrupt_master_enabled_restored=True,
        require_interrupt_enable_restored=True,
        require_interrupt_flags_restored=True,
        require_interrupt_observed=True,
    )
    raw = case_dict("RC-MACHINE-FAR-CALL")
    raw["observation_boundary"] = None
    with pytest.raises(RendererConformanceError, match="requires boundary evidence"):
        ConformanceCase.from_dict(raw)


def test_dotted_fields_round_trip_through_their_canonical_carriers() -> None:
    overlay_fields = {
        path.removeprefix("overlay_request."): value
        for path, value in derive_expectation(case("RC-OVERLAY-PARTIAL-CLIP")).fields
    }
    overlay = OverlayRequestState.from_dict(overlay_fields)
    assert overlay.to_dict() == overlay_fields

    oam_fields = {
        path.removeprefix("oam_fallback."): value
        for path, value in derive_expectation(case("RC-OAM-UNMAPPED_IDENTITY")).fields
    }
    oam = OAMFallbackState.from_dict(oam_fields)
    assert oam.to_dict() == oam_fields

    reconstruction_fields = {
        path.removeprefix("reconstruction."): value
        for path, value in derive_expectation(case("RC-RECONSTRUCTION")).fields
    }
    reconstruction = ReconstructionState.from_dict(reconstruction_fields)
    assert reconstruction.to_dict() == reconstruction_fields

    machine_fields = dict(derive_expectation(case("RC-MACHINE-FAR-CALL")).fields)
    bank_case = BankTortureCase.from_dict(
        {
            "case_id": "RC-MACHINE-FAR-CALL",
            "event": machine_fields["case.event"],
            "entry_banks": machine_fields["case.entry_banks"],
            "pending_work": False,
        },
        path="result.case",
    )
    assert bank_case.event.value == machine_fields["case.event"]


@pytest.mark.parametrize(
    ("case_id", "checks", "match"),
    [
        (
            "RC-TRANSFER-ROW",
            ["CHK-OAM-01"],
            "missing CHK-TRANSFER-01.*unrelated CHK-OAM-01",
        ),
        ("RC-PALETTE-BG", ["CHK-COMMIT-01"], "missing CHK-PALETTE-01"),
    ],
)
def test_operation_rejects_unrelated_or_missing_check_identities(
    case_id: str, checks: list[str], match: str
) -> None:
    raw = case_dict(case_id)
    raw["checks"] = checks
    with pytest.raises(RendererConformanceError, match=match):
        ConformanceCase.from_dict(raw)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "required_items",
        "completed_items",
        "poisoned_items",
        "item_provenance",
        "presentation_barrier_count",
        "required_states",
        "cancellation_reason",
        "forbid_later_writes",
        "visible_states",
        "fallback_kind",
        "diagnostic_record",
        "provenance",
        "poison_result",
        "barrier_result",
        "completed_resources",
    ],
)
def test_oracle_rejects_forbidden_outcome_keys_even_without_expected_prefix(
    forbidden_key: str,
) -> None:
    raw = case_dict("RC-TRANSFER-ROW")
    raw["inputs"][forbidden_key] = True  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="expected-output"):
        ConformanceCase.from_dict(raw)


def test_corpus_covers_each_operation_and_declared_overlay_variant() -> None:
    parsed = corpus()
    assert {item.operation for item in parsed} == set(OperationKind)
    overlays = [item for item in parsed if item.operation is OperationKind.OVERLAY]
    assert {item.inputs["matrix_key"] for item in overlays} == {
        "OVERLAY-ORDINARY-OPAQUE-EXPLICIT",
        "OVERLAY-ORDINARY-OPAQUE-DEFAULT",
        "OVERLAY-ORDINARY-REVEALED-LOOKUP",
        "OVERLAY-ORDINARY-REVEALED-OVERRIDE",
        "OVERLAY-FULLY-CLIPPED",
        "OVERLAY-PARTIALLY-CLIPPED",
        "OVERLAY-MAP-EDGE",
        "OVERLAY-CONNECTION",
        "OVERLAY-WINDOW",
        "OVERLAY-ALTERNATE-BG",
        "OVERLAY-ALTERNATE-MAP",
    }
    assert {
        item.inputs["clip_edge"]
        for item in overlays
        if item.inputs["matrix_key"] == "OVERLAY-PARTIALLY-CLIPPED"
    } == {"left", "right", "top", "bottom"}
    assert {
        item.inputs["transfer_kind"]
        for item in parsed
        if item.operation is OperationKind.PAIRED_TRANSFER
    } == {"ROW", "COLUMN", "CONNECTION"}
    assert {
        item.inputs["palette_kind"]
        for item in parsed
        if item.operation is OperationKind.PALETTE_UPLOAD
    } == {"BG", "OBJ"}
    assert {
        dict(derive_expectation(item).fields)["oam_fallback.fallback_kind"]
        for item in parsed
        if item.operation is OperationKind.OAM_FALLBACK
    } == {item.value for item in OAMFallbackKind}


def test_every_overlay_matrix_key_requires_its_canonical_tileset() -> None:
    seen: set[str] = set()
    for raw in corpus_dict()["cases"]:  # type: ignore[index,union-attr]
        if raw["operation"] != "OVERLAY" or raw["inputs"]["matrix_key"] in seen:
            continue
        seen.add(raw["inputs"]["matrix_key"])
        raw["inputs"]["tileset_id"] = "FOREST"
        with pytest.raises(RendererConformanceError, match="canonical OVERWORLD"):
            ConformanceCase.from_dict(raw)
    assert seen == {
        "OVERLAY-ORDINARY-OPAQUE-EXPLICIT",
        "OVERLAY-ORDINARY-OPAQUE-DEFAULT",
        "OVERLAY-ORDINARY-REVEALED-LOOKUP",
        "OVERLAY-ORDINARY-REVEALED-OVERRIDE",
        "OVERLAY-FULLY-CLIPPED",
        "OVERLAY-PARTIALLY-CLIPPED",
        "OVERLAY-MAP-EDGE",
        "OVERLAY-CONNECTION",
        "OVERLAY-WINDOW",
        "OVERLAY-ALTERNATE-BG",
        "OVERLAY-ALTERNATE-MAP",
    }


@pytest.mark.parametrize("case_id", ["RC-OVERLAY-MAP-EDGE", "RC-OVERLAY-CONNECTION"])
def test_edge_and_connection_reject_tileset_mutation(case_id: str) -> None:
    raw = case_dict(case_id)
    raw["inputs"]["tileset_id"] = "FOREST"  # type: ignore[index]
    with pytest.raises(RendererConformanceError, match="canonical OVERWORLD"):
        ConformanceCase.from_dict(raw)


def test_corpus_attribute_sources_cover_every_meaningful_bit_and_zero_bit_four() -> None:
    attributes = [
        attribute
        for item in corpus()
        if item.operation is OperationKind.OVERLAY
        for attribute in bytes.fromhex(
            dict(derive_expectation(item).fields)["overlay_request.attributes"]
        )
    ]
    assert all(attribute & 0x10 == 0 for attribute in attributes)
    assert 0xEF == reduce(int.__or__, attributes, 0)


def test_corpus_rejects_palette_bit_zero_as_only_meaningful_attribute_bit() -> None:
    raw = corpus_dict()
    for item in raw["cases"]:  # type: ignore[union-attr]
        if item["operation"] != "OVERLAY":
            continue
        inputs = item["inputs"]
        inputs["explicit_attributes"] = {
            key: 1 for key in inputs["explicit_attributes"]
        }
        inputs["text_window_default"] = 1
        inputs["coordinate_overrides"] = {
            key: 1 for key in inputs["coordinate_overrides"]
        }
        inputs["tileset_attributes"] = "01" * 256
    with pytest.raises(RendererConformanceError, match="palette bits 0-2"):
        load_corpus(raw)


def test_corpus_contains_no_expected_output_fields() -> None:
    def keys(value: object) -> list[str]:
        if isinstance(value, dict):
            return list(value) + [
                key for child in value.values() for key in keys(child)
            ]
        if isinstance(value, list):
            return [key for child in value for key in keys(child)]
        return []

    for raw in corpus_dict()["cases"]:  # type: ignore[index,union-attr]
        input_keys = [key.lower().replace("-", "_") for key in keys(raw["inputs"])]
        assert not any(
            key.startswith(("expected", "actual", "observed")) or "output" in key
            for key in input_keys
        )


def test_corpus_rejects_duplicate_case_ids() -> None:
    raw = corpus_dict()
    raw["cases"].append(raw["cases"][0])  # type: ignore[union-attr,index]
    with pytest.raises(RendererConformanceError, match="duplicate case IDs"):
        load_corpus(raw)
