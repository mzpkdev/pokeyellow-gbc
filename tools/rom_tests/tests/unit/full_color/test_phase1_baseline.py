from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.enums import Owner, Phase
from tools.rom_tests.full_color.phase1_baseline import compare_phase1_baseline
from tools.rom_tests.full_color.snapshots import SemanticSnapshot, SnapshotJob

FIXTURE = Path(
    "tools/rom_tests/fixtures/full_color/renderer-conformance/observations/"
    "RC-OWNERSHIP-REPLACEMENT.snapshot.json"
)


def baseline(*, generation: int = 5, frame: int = 10, checkpoint: str = "before"):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw.update(
        rom="pokeyellow_debug.gbc:deadbeef",
        scenario="phase1-baseline",
        checkpoint=checkpoint,
        frame=frame,
        evidence_kind="YELLOW_BASELINE",
        activation_phase=0,
        owner=Owner.RENDERER_YELLOW.value,
        phase=Phase.YELLOW_ACTIVE.value,
        generation=generation,
        writer_id=None,
        traced_writer_ids=[],
        artifacts={},
    )
    return SemanticSnapshot.from_dict(raw)


@pytest.mark.parametrize(
    "checkpoint",
    ("hard-boot", "soft-reset", "ownership-restore", "forced-entry-bank-vblank"),
)
def test_clean_phase1_paths_allow_only_frame_checkpoint_and_fresh_token(
    checkpoint: str,
) -> None:
    before = baseline()
    after = baseline(generation=6, frame=13, checkpoint=checkpoint)
    assert compare_phase1_baseline(before, after).passed


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (
            lambda value: replace(
                value, bg_tile_ids=b"\x01" + value.bg_tile_ids[1:]
            ),
            "bg_tile_ids[0x0000]",
        ),
        (
            lambda value: replace(
                value,
                dirty=(("attributes", True), ("bg", False), ("obj", False)),
            ),
            "dirty",
        ),
        (
            lambda value: replace(
                value,
                owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
                phase=Phase.HANDOFF_TO_YELLOW,
            ),
            "owner",
        ),
        (lambda value: replace(value, banks=replace(value.banks, wram=2)), "banks"),
        (lambda value: replace(value, generation=5), "generation"),
    ],
)
def test_baseline_mutations_fail_at_localized_field(mutation, path: str) -> None:
    before = baseline()
    after = mutation(baseline(generation=6, frame=13, checkpoint="after"))
    report = compare_phase1_baseline(before, after)
    assert not report.passed
    assert path in {difference.path for difference in report.differences}


def test_stale_job_fails_exact_semantics() -> None:
    before = baseline()
    job = SnapshotJob.from_dict(
        {
            "job_id": "JOB-STALE",
            "request_ids": ["REQ-STALE"],
            "resources": ["ownership_generation"],
            "state": "PREPARED",
            "cancellation_reason": None,
            "commit_unit_id": "MU-STALE",
            "owner": "RENDERER_YELLOW",
            "generation": 5,
        }
    )
    after = replace(baseline(generation=6, checkpoint="after"), job=job)
    report = compare_phase1_baseline(before, after)
    assert not report.passed
    assert "job" in {difference.path for difference in report.differences}


def test_wrong_rom_and_provenance_fail_closed() -> None:
    before = baseline()
    after = replace(
        baseline(generation=6, checkpoint="after"),
        rom="other.gbc:bad",
        evidence_kind="RENDERER_RUNTIME",
        activation_phase=1,
    )
    paths = {item.path for item in compare_phase1_baseline(before, after).differences}
    assert {"rom", "evidence_kind", "activation_phase"} <= paths
