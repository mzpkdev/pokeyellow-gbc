"""Fail-closed contracts for the Phase 2 SameBoy timing authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from tools.rom_tests.full_color.phase2_timing_sameboy import (
    AUTHORITY,
    BRIDGE_VERSION,
    EVENT_CALIBRATION_END,
    EVENT_CALIBRATION_START,
    EVENT_SAMPLE_END,
    EVENT_SAMPLE_START,
    EVENT_THRESHOLD_COMMITTING,
    EVENT_THRESHOLD_DEFER,
    EVENT_THRESHOLD_START,
    REPORT_SCHEMA,
    ROW_DEFINITIONS,
    Observation,
    SameBoyTimingError,
    SourceLock,
    _load_input_manifest,
    _write_generated_input_replay,
    parse_bridge_output,
    rows_from_observations,
    validate_report,
)
from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


ROM_SHA = "a" * 64
BRIDGE_SHA = "b" * 64


def _observations(*, omit: str | None = None, commit: str | None = None) -> tuple[Observation, ...]:
    result: list[Observation] = []
    clock = 1000
    for definition in ROW_DEFINITIONS:
        if definition.key == omit:
            continue
        threshold = definition.deadline_cycle - definition.guard_cycles - 20
        events = (
            (EVENT_CALIBRATION_START, clock, 0, 0),
            (EVENT_CALIBRATION_END, clock + 20, 0, 0),
            (EVENT_SAMPLE_START, clock + 40, 0, 0),
            (EVENT_SAMPLE_END, clock + 160, 0, 0),
            (EVENT_THRESHOLD_START, clock + 180, 0, threshold + 1),
            (
                EVENT_THRESHOLD_COMMITTING if definition.key == commit else EVENT_THRESHOLD_DEFER,
                clock + 200,
                2 if definition.key == commit else 1,
                threshold + 1,
            ),
        )
        result.extend(
            Observation(definition.row_id, event, definition.row_id, cycles, 144, probe, probe_cycles)
            for event, cycles, probe, probe_cycles in events
        )
        clock += 1000
    return tuple(result)


def _report() -> dict[str, object]:
    lock = SourceLock.load(
        REPOSITORY_ROOT / "tools/rom_tests/vendor/sameboy.lock"
    )
    return {
        "schema": REPORT_SCHEMA,
        "authority": AUTHORITY,
        "sameboy": asdict(lock),
        "bridge_sha256": BRIDGE_SHA,
        "rom": {"name": "pokeyellow_debug.gbc", "sha256": ROM_SHA},
        "rows": list(rows_from_observations(_observations(), "pokeyellow_debug.gbc")),
    }


def test_pinned_lock_and_all_12_core_cycle_rows_pass() -> None:
    report = _report()
    validate_report(report, rom_sha256=ROM_SHA, bridge_sha256=BRIDGE_SHA)
    assert [row["key"] for row in report["rows"]] == [row.key for row in ROW_DEFINITIONS]
    assert all(row["tool_device"] == BRIDGE_VERSION for row in report["rows"])
    assert all(row["evidence_kind"] == "RENDERER_RUNTIME" for row in report["rows"])


def test_lock_rejects_wrong_version_and_archive_hash(tmp_path: Path) -> None:
    original = (REPOSITORY_ROOT / "tools/rom_tests/vendor/sameboy.lock").read_text()
    for old, new, message in (
        ('"v1.0.3"', '"v1.0.2"', "version"),
        ("7da338458e19396cb43dfe1a4df4555882ebea92540565dc993c1c706c981dc3", "0" * 64, "archive_sha256"),
    ):
        path = tmp_path / f"{message}.lock"
        path.write_text(original.replace(old, new), encoding="utf-8")
        with pytest.raises(SameBoyTimingError, match=message):
            SourceLock.load(path)


def test_missing_row_and_absent_samples_fail_closed() -> None:
    with pytest.raises(SameBoyTimingError, match="missing canonical timing row"):
        rows_from_observations(_observations(omit="TIME-OAM-MAXIMUM"), "pokeyellow_debug.gbc")
    report = _report()
    report["rows"][0]["sample_core_cycles"] = []
    with pytest.raises(SameBoyTimingError, match="lacks core-cycle samples"):
        validate_report(report, rom_sha256=ROM_SHA, bridge_sha256=BRIDGE_SHA)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda report: report.__setitem__("authority", "PYBOY_CYCLES"), "PyBoy"),
        (lambda report: report.__setitem__("bridge_sha256", "0" * 64), "tool identity"),
        (lambda report: report["rom"].__setitem__("sha256", "0" * 64), "ROM identity"),
        (lambda report: report["sameboy"].__setitem__("version", "v1.0.2"), "SameBoy identity"),
        (lambda report: report["rows"][0].__setitem__("margin_cycles", 1), "budget equation"),
        (lambda report: report["rows"][0].__setitem__("deadline_cycle", 64), "relabels"),
    ),
)
def test_report_rejects_wrong_authority_identity_and_arithmetic(mutation, message) -> None:
    report = deepcopy(_report())
    mutation(report)
    with pytest.raises((SameBoyTimingError, AssertionError), match=message):
        validate_report(report, rom_sha256=ROM_SHA, bridge_sha256=BRIDGE_SHA)


def test_threshold_plus_one_commit_is_an_immediate_failure() -> None:
    with pytest.raises(SameBoyTimingError, match="entered COMMITTING"):
        rows_from_observations(
            _observations(commit="TIME-PALETTE-BG"), "pokeyellow_debug.gbc"
        )


def test_threshold_probe_cannot_relabel_byte_budget_as_cycles() -> None:
    observations = list(_observations())
    index = next(
        index for index, item in enumerate(observations)
        if item.row == 5 and item.event == EVENT_THRESHOLD_DEFER
    )
    item = observations[index]
    observations[index] = Observation(
        item.row, item.event, item.sequence, item.core_cycles, item.ly, item.probe, 64
    )
    with pytest.raises(SameBoyTimingError, match="exact cycle threshold"):
        rows_from_observations(observations, "pokeyellow_debug.gbc")


def test_bridge_tsv_is_strict_and_retains_scanline_support(tmp_path: Path) -> None:
    path = tmp_path / "capture.tsv"
    path.write_text(
        "row\tevent\tsequence\tcore_cycles\tly\tprobe\tprobe_cycles\n"
        "1\t1\t7\t100\t144\t0\t0\n",
        encoding="ascii",
    )
    assert parse_bridge_output(path) == (
        Observation(1, EVENT_SAMPLE_START, 7, 100, 144, 0, 0),
    )
    path.write_text("row\tevent\tsequence\tcore_cycles\tly\tprobe\n", encoding="ascii")
    with pytest.raises(SameBoyTimingError, match="wrong header"):
        parse_bridge_output(path)


def test_input_replay_manifest_is_closed_and_hash_bound(tmp_path: Path) -> None:
    trace = tmp_path / "input.tsv"
    trace.write_text("frame\tkey_mask\n0\t0\n10\t16\n12\t0\n", encoding="ascii")
    import hashlib
    digest = hashlib.sha256(trace.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"schema":"full-color-phase2-sameboy-input-v1",'
        f'"input_trace":"input.tsv","input_sha256":"{digest}","max_cycles":1000}}',
        encoding="utf-8",
    )
    loaded = _load_input_manifest(manifest, tmp_path)
    assert loaded["input_trace"] == trace
    trace.write_text("frame\tkey_mask\n0\t1\n", encoding="ascii")
    with pytest.raises(SameBoyTimingError, match="wrong identity"):
        _load_input_manifest(manifest, tmp_path)


def test_generated_default_replay_is_strict_closed_and_hash_bound(tmp_path: Path) -> None:
    manifest = _write_generated_input_replay(
        tmp_path,
        ((0, 0), (10, 16), (12, 0)),
        max_cycles=1000,
    )
    loaded = _load_input_manifest(manifest, tmp_path)
    assert loaded["max_cycles"] == 1000
    assert loaded["input_trace"].read_text(encoding="ascii").splitlines() == [
        "frame\tkey_mask", "0\t0", "10\t16", "12\t0",
    ]
    with pytest.raises(SameBoyTimingError, match="strictly ordered"):
        _write_generated_input_replay(
            tmp_path / "bad", ((0, 0), (10, 16), (10, 0)), max_cycles=1000,
        )


def test_bridge_initializes_pinned_headless_rgb_path_before_running() -> None:
    source = (
        REPOSITORY_ROOT / "tools/rom_tests/full_color/sameboy_timing_bridge_v1.c"
    ).read_text(encoding="utf-8")
    pixels = source.index("GB_set_pixels_output(&gb, pixels);")
    encode = source.index("GB_set_rgb_encode_callback(&gb, rgb_encode);")
    run = source.index("GB_run(&gb)")
    assert pixels < run
    assert encode < run
