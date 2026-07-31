from pathlib import Path

import pytest

from tools.rom_tests.full_color.baseline_discovery import (
    COPIED_REGIONS,
    DMA_CONTROL_LABELS,
    FARCALL_LABELS,
    SHADOW_OAM_RANGES,
    SOURCE_ROOTS,
    baseline_summary,
    load_predef_targets,
    main,
    summary_json,
    writer_roots,
)
from tools.rom_tests.full_color.rom_discovery import RomDiscoveryError, parse_sym
from tools.rom_tests.full_color.source_discovery import (
    SourceDiscoveryReport,
    SourceFinding,
)


def test_reviewed_baseline_configuration_is_stable() -> None:
    assert SOURCE_ROOTS == tuple(sorted(SOURCE_ROOTS))
    assert SHADOW_OAM_RANGES == ((0xC300, 0xC39F), (0xC508, 0xC5A7))
    assert COPIED_REGIONS[0].runtime_address == 0xFF80
    assert COPIED_REGIONS[0].length == 0x0A
    assert FARCALL_LABELS == ("Bankswitch", "JumpToAddress")
    assert DMA_CONTROL_LABELS == (
        "DMARoutine",
        "WriteDMACodeToHRAM",
        "hDMARoutine",
    )


def test_writer_roots_are_unique_sorted_source_backed_labels() -> None:
    report = SourceDiscoveryReport(
        (),
        (),
        (
            SourceFinding(
                "writer", "b.asm", 2, "WriterB", "direct", "ff40", "DISPLAY_REGISTER"
            ),
            SourceFinding(
                "scene", "a.asm", 1, "Scene", "call", "Dest", "SCENE_BOUNDARY"
            ),
            SourceFinding(
                "writer", "a.asm", 3, "WriterA", "pointer", "hl", "UNKNOWN_DESTINATION"
            ),
            SourceFinding(
                "writer", "b.asm", 4, "WriterB", "direct", "ff41", "DISPLAY_REGISTER"
            ),
        ),
        (),
    )

    assert writer_roots(report) == ("WriterA", "WriterB")


def test_predef_targets_preserve_order_and_explicit_bank_overrides(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    rows = [
        "add_predef TargetZero",
        "add_predef TargetOverride, $03 ; deliberate override",
    ]
    rows.extend(f"add_predef Target{index}" for index in range(2, 99))
    (data / "predef_pointers.asm").write_text("\n".join(rows) + "\n", encoding="utf-8")
    sym_lines = ["02:4000 TargetZero", "04:4001 TargetOverride"]
    sym_lines.extend(f"{index + 5:02x}:4000 Target{index}" for index in range(2, 99))

    targets = load_predef_targets(tmp_path, parse_sym("\n".join(sym_lines) + "\n"))

    assert tuple(targets) == tuple(range(99))
    assert (targets[0].bank, targets[0].address) == (2, 0x4000)
    assert (targets[1].bank, targets[1].address) == (3, 0x4001)


def test_predef_targets_fail_closed_on_unknown_or_incomplete_authority(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    path = data / "predef_pointers.asm"
    path.write_text("add_predef Missing\n", encoding="utf-8")
    with pytest.raises(RomDiscoveryError, match="unknown predef symbol"):
        load_predef_targets(tmp_path, parse_sym("00:0100 Other\n"))

    path.write_text("add_predef Only\n", encoding="utf-8")
    with pytest.raises(RomDiscoveryError, match="exactly 99"):
        load_predef_targets(tmp_path, parse_sym("00:0100 Only\n"))


def test_summary_json_and_cli_are_byte_stable(monkeypatch, capsys) -> None:
    summary = {
        "schema": "full-color-baseline-discovery-summary-v1",
        "source": {"files": 2},
        "rom": {"findings": 3},
    }
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_discovery.baseline_summary",
        lambda repository: summary,
    )

    assert summary_json(".") == (
        '{"rom":{"findings":3},"schema":'
        '"full-color-baseline-discovery-summary-v1","source":{"files":2}}\n'
    )
    assert main(["--repository", "repo"]) == 0
    assert capsys.readouterr().out == summary_json(".")


def test_real_summary_shape_uses_one_source_report_for_rom(monkeypatch) -> None:
    rom = type(
        "Rom",
        (),
        {
            "rom_sha256": "0" * 64,
            "sym_sha256": "1" * 64,
            "map_sha256": "2" * 64,
            "findings": (),
            "visited": (),
            "unresolved_destinations": (),
            "unresolved_control_flow": (),
            "candidate_findings": (),
            "candidate_sections": (),
        },
    )()
    source_report = type(
        "Source",
        (),
        {
            "source_sha256": "3" * 64,
            "roots": ("main.asm",),
            "include_graph": (("main.asm", ()),),
            "findings": (),
            "errors": (),
        },
    )()
    seen = []
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_discovery.discover_baseline_sources",
        lambda repository: source_report,
    )
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_discovery.discover_baseline_rom",
        lambda repository, *, source_report: seen.append(source_report) or rom,
    )
    monkeypatch.setattr(
        "tools.rom_tests.full_color.baseline_discovery.writer_roots",
        lambda report: (),
    )

    result = baseline_summary("repo")

    assert seen == [source_report]
    assert result["source"]["files"] == 1
    assert result["rom"]["candidate_sections"] == 0
