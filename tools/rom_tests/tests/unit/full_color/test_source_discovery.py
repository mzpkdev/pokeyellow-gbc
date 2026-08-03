"""Synthetic RGBDS include/macro discovery coverage."""

from tools.rom_tests.full_color.source_discovery import discover_sources


def test_include_alias_macro_and_computed_sink_discovery(tmp_path) -> None:
    (tmp_path / "main.asm").write_text(
        'INCLUDE "macros.inc"\nINCLUDE "child.asm"\n', encoding="utf-8"
    )
    (tmp_path / "macros.inc").write_text(
        "MACRO putreg\n\tldh [\\1], a\nENDM\n", encoding="utf-8"
    )
    (tmp_path / "child.asm").write_text(
        """
Alias EQU Direct
Sink EQU $ff55
Direct::
    ldh [rVBK], a
    ldh [Sink], a
    putreg rDMA
    ldh [c], a
    ld [hl], a
.edge:
    ; @full-color scene-edge destination=BattleInit resource=SCENE_BOUNDARY row_kind=DIRECTED_EDGE direction=YELLOW_TO_MAP
.mutation:
    ; @full-color mutation destination=BG_MAP_9800 resource=BG_TILE_IDS
""".lstrip(),
        encoding="utf-8",
    )

    report = discover_sources(
        tmp_path,
        ["main.asm"],
        owner_gates={"Direct": "RENDERER_YELLOW"},
        object_paths={"child.asm": "build/child.o"},
    )

    assert not report.errors
    assert dict(report.include_graph)["main.asm"] == ("child.asm", "macros.inc")
    direct = [item for item in report.findings if item.symbol == "Direct"]
    assert {item.mechanism for item in direct} == {
        "direct",
        "macro:putreg",
        "ldh-c",
        "pointer",
    }
    assert {item.resolved for item in direct} == {False, True}
    assert all(item.aliases == ("Alias",) for item in direct)
    assert all(item.object == "build/child.o" for item in direct)
    assert all(item.owner_gate == "RENDERER_YELLOW" for item in direct)
    assert any(
        item.destination == "ff55" and item.resource == "HDMA_GDMA" for item in direct
    )
    assert {item.category for item in report.findings} >= {"scene_edge", "mutation"}
    assert report.to_json() == report.to_json()


def test_missing_include_remains_a_deterministic_error(tmp_path) -> None:
    (tmp_path / "main.asm").write_text('INCLUDE "missing.asm"\n', encoding="utf-8")

    report = discover_sources(tmp_path, ["main.asm"])

    assert report.errors == ("missing.asm: included source does not exist",)


def test_identical_macro_expansion_findings_are_deduplicated(tmp_path) -> None:
    (tmp_path / "main.asm").write_text(
        """
MACRO twice
    ld [hl], a
    ld [hl], a
ENDM
Root::
    twice
""".lstrip(),
        encoding="utf-8",
    )

    report = discover_sources(tmp_path, ["main.asm"])

    writers = [item for item in report.findings if item.category == "writer"]
    assert len(writers) == 1
    assert writers[0].symbol == "Root"


def test_inline_labels_expressions_and_unannotated_control_flow(tmp_path) -> None:
    (tmp_path / "main.asm").write_text(
        """
StatWriter:: ldh [rSTAT + 0], a
VbkWriter:: ld [$ff4f+0], a
SceneEntry:: call SceneTarget
    call nz, SceneTarget
    jp c, SceneTarget
    jr z, SceneTarget
    farcall SceneTarget
    farjp SceneTarget
    predef SceneTarget
    dw SceneTarget
Computed:: jp hl
SceneTarget:: ret
""".lstrip(),
        encoding="utf-8",
    )

    report = discover_sources(
        tmp_path,
        ["main.asm"],
        scene_roots={"SceneEntry", "Computed"},
        scene_sinks={"SceneTarget"},
    )

    writers = {
        (finding.symbol, finding.destination)
        for finding in report.findings
        if finding.category == "writer"
    }
    assert ("StatWriter", "ff41") in writers
    assert ("VbkWriter", "ff4f") in writers
    scene_mechanisms = {
        finding.mechanism
        for finding in report.findings
        if finding.symbol == "SceneEntry" and finding.category == "scene_edge"
    }
    assert scene_mechanisms == {
        "call",
        "jp",
        "jr",
        "farcall",
        "farjp",
        "predef",
        "table",
    }
    conditional = [
        finding
        for finding in report.findings
        if finding.symbol == "SceneEntry" and finding.condition is not None
    ]
    assert {
        (finding.mechanism, finding.destination, finding.condition)
        for finding in conditional
    } == {
        ("call", "SceneTarget", "nz"),
        ("jp", "SceneTarget", "c"),
        ("jr", "SceneTarget", "z"),
    }
    assert all(finding.evidence_sha256 for finding in conditional)
    computed = next(
        finding
        for finding in report.findings
        if finding.symbol == "Computed" and finding.mechanism == "jp"
    )
    assert not computed.resolved
    assert computed.resource == "COMPUTED_CONTROL_FLOW"
    assert any("unresolved jp destination hl" in error for error in report.errors)


def test_missing_configured_lifecycle_symbol_is_an_error(tmp_path) -> None:
    (tmp_path / "main.asm").write_text("Present:: ret\n", encoding="utf-8")

    report = discover_sources(tmp_path, ["main.asm"], lifecycle_roots={"Missing"})

    assert report.errors == (
        "configured lifecycle/scene/mutation symbol 'Missing' was not discovered",
    )


def test_unconfigured_local_label_always_terminates_parent_scope(tmp_path) -> None:
    (tmp_path / "main.asm").write_text(
        "Root::\n    ldh [rVBK], a\n.local:\n    ldh [rDMA], a\n",
        encoding="utf-8",
    )
    report = discover_sources(tmp_path, ["main.asm"], lifecycle_roots={"Root"})
    writers = [finding for finding in report.findings if finding.category == "writer"]
    assert [(finding.symbol, finding.destination) for finding in writers] == [
        ("Root", "ff4f"),
        ("Root.local", "ff46"),
    ]
    assert [
        finding.symbol
        for finding in report.findings
        if finding.mechanism == "configured-root"
    ] == ["Root"]
