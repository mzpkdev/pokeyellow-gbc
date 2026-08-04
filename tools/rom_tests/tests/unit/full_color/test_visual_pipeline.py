"""Complete visual evidence generation and integrity mutations."""

import json
from pathlib import Path

from PIL import Image
import pytest

from tools.rom_tests.full_color.artifacts import (
    ArtifactManifest,
    ManifestValidationError,
    validate_artifact_files,
)
from tools.rom_tests.full_color.snapshots import SemanticSnapshot
from tools.rom_tests.full_color.trace import WriterTrace
from tools.rom_tests.full_color import visual_pipeline
from tools.rom_tests.full_color.visual_pipeline import write_visual_evidence

from .test_snapshots import snapshot_dict


def _snapshot() -> SemanticSnapshot:
    raw = snapshot_dict()
    raw.update(
        {
            "scenario": "gate-0-baseline",
            "checkpoint": "debug-ready",
            "frame": 12,
            "artifacts": {},
        }
    )
    return SemanticSnapshot.from_dict(raw)


def _trace() -> WriterTrace:
    return WriterTrace(capacity=4, entries=(), permitted_writer_ids=("WR-NONE",))


def test_baseline_visual_pipeline_uses_the_frozen_phase1_product() -> None:
    source = Path(visual_pipeline.__file__).read_text(encoding="utf-8")
    function = source.split("def run_baseline_visual_pipeline", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert 'rom=root / "pokeyellow_phase1_debug.gbc"' in function
    assert 'symbols=root / "pokeyellow_phase1_debug.sym"' in function
    assert 'root / "pokeyellow_debug.gbc"' not in function


def test_visual_pipeline_writes_linked_viewable_deterministic_evidence(
    tmp_path: Path,
) -> None:
    frames = tuple(
        Image.new("RGB", (16, 12), (index * 20, 40, 80)) for index in range(5)
    )

    first = write_visual_evidence(
        tmp_path / "run-1",
        frames=frames,
        frame_numbers=(10, 11, 12, 13, 14),
        checkpoint_index=2,
        snapshot=_snapshot(),
        trace=_trace(),
    )
    second = write_visual_evidence(
        tmp_path / "run-2",
        frames=frames,
        frame_numbers=(10, 11, 12, 13, 14),
        checkpoint_index=2,
        snapshot=_snapshot(),
        trace=_trace(),
    )

    assert first.to_json() == second.to_json()
    checkpoint = first.checkpoints[0]
    assert checkpoint.frame == 12
    assert {artifact.type.value for artifact in checkpoint.artifacts} == {
        "screenshot",
        "frame_strip",
        "contact_sheet",
        "localized_image_diff",
        "structured_diff",
        "semantic_snapshot",
        "writer_trace",
        "compact_summary",
    }
    semantic = SemanticSnapshot.from_json(
        (tmp_path / "run-1/debug-ready/semantic-snapshot.json").read_text()
    )
    assert dict(semantic.artifacts)["writer_trace"] == (
        "debug-ready/writer-trace.json"
    )
    metadata = json.loads(
        (tmp_path / "run-1/debug-ready/localized-image-diff.json").read_text()
    )
    assert metadata["bbox"] == [8, 6, 9, 7]
    assert metadata["changed_pixels"] == 1


def test_visual_integrity_mutation_fails_with_the_artifact_path(tmp_path: Path) -> None:
    frames = tuple(Image.new("RGB", (8, 8), "black") for _ in range(3))
    manifest = write_visual_evidence(
        tmp_path,
        frames=frames,
        frame_numbers=(11, 12, 13),
        checkpoint_index=1,
        snapshot=_snapshot(),
        trace=_trace(),
    )
    screenshot = tmp_path / "debug-ready/screenshot.png"
    screenshot.write_bytes(screenshot.read_bytes() + b"corruption")

    with pytest.raises(
        ManifestValidationError,
        match="artifact size mismatch: debug-ready/screenshot.png",
    ):
        validate_artifact_files(tmp_path, ArtifactManifest.from_json(manifest.to_json()))


@pytest.mark.parametrize(
    ("frame_numbers", "message"),
    [
        ((10, 10, 11), "unique and increasing"),
        (tuple(range(32)), "1..31"),
    ],
)
def test_visual_pipeline_rejects_unbounded_or_ambiguous_frames(
    tmp_path: Path,
    frame_numbers: tuple[int, ...],
    message: str,
) -> None:
    frames = tuple(Image.new("RGB", (8, 8), "black") for _ in frame_numbers)
    with pytest.raises(ValueError, match=message):
        write_visual_evidence(
            tmp_path,
            frames=frames,
            frame_numbers=frame_numbers,
            checkpoint_index=0,
            snapshot=_snapshot(),
            trace=_trace(),
        )
