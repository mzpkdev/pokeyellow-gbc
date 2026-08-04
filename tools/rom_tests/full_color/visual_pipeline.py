"""Deterministic, LLM-viewable Gate 0 baseline evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw

from tools.rom_tests.emulator import Emulator

from .artifacts import (
    ArtifactCheckpoint,
    ArtifactManifest,
    ArtifactType,
    artifact_for_path,
    validate_artifact_files,
)
from .runtime_observability import (
    capture_yellow_baseline_snapshot,
    read_writer_trace,
    wait_until_debug_ready,
)
from .snapshots import SemanticSnapshot
from .trace import WriterTrace

VISUAL_PIPELINE_SCHEMA = "full-color-visual-pipeline-v1"
BASELINE_SCENARIO = "gate-0-baseline"
BASELINE_CHECKPOINT = "debug-ready"
BASELINE_SEED = 0
BASELINE_FRAME_COUNT = 5
CHECKPOINT_FRAME_INDEX = 2


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _frame_strip(frames: Sequence[Image.Image]) -> Image.Image:
    width, height = frames[0].size
    strip = Image.new("RGB", (width * len(frames), height))
    for index, frame in enumerate(frames):
        strip.paste(frame, (index * width, 0))
    return strip


def _contact_sheet(
    frames: Sequence[Image.Image],
    frame_numbers: Sequence[int],
    *,
    checkpoint_index: int,
) -> Image.Image:
    columns = 3
    label_height = 18
    width, height = frames[0].size
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * (height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (frame, frame_number) in enumerate(zip(frames, frame_numbers, strict=True)):
        x = index % columns * width
        y = index // columns * (height + label_height)
        label = f"frame {frame_number}"
        if index == checkpoint_index:
            label += " | CHECKPOINT"
        draw.rectangle((x, y, x + width - 1, y + label_height - 1), fill="white")
        draw.text((x + 3, y + 3), label, fill="black")
        sheet.paste(frame, (x, y + label_height))
    return sheet


def _localized_diff(reference: Image.Image) -> tuple[Image.Image, dict[str, object]]:
    mutated = reference.copy()
    x, y = reference.width // 2, reference.height // 2
    before = reference.getpixel((x, y))
    after = tuple(255 - channel for channel in before)
    mutated.putpixel((x, y), after)
    difference = ImageChops.difference(reference, mutated)
    bbox = difference.getbbox()
    if bbox is None:
        raise AssertionError("intentional visual mutation produced no image difference")
    left = max(0, bbox[0] - 4)
    top = max(0, bbox[1] - 4)
    right = min(reference.width, bbox[2] + 4)
    bottom = min(reference.height, bbox[3] + 4)
    localized = difference.crop((left, top, right, bottom)).resize(
        ((right - left) * 8, (bottom - top) * 8),
        resample=Image.Resampling.NEAREST,
    )
    return localized, {
        "schema": "full-color-localized-image-diff-v1",
        "bbox": list(bbox),
        "crop": [left, top, right, bottom],
        "changed_pixels": 1,
        "mutation": {
            "kind": "INVERT_ONE_PIXEL",
            "x": x,
            "y": y,
            "expected_rgb": list(before),
            "actual_rgb": list(after),
        },
    }


def write_visual_evidence(
    output: Path,
    *,
    frames: Sequence[Image.Image],
    frame_numbers: Sequence[int],
    checkpoint_index: int,
    snapshot: SemanticSnapshot,
    trace: WriterTrace,
) -> ArtifactManifest:
    """Write one complete linked checkpoint and validate every emitted byte."""
    if not 1 <= len(frames) <= 31:
        raise ValueError("visual evidence requires 1..31 frames")
    if len(frames) != len(frame_numbers):
        raise ValueError("frames and frame numbers must have equal length")
    if not 0 <= checkpoint_index < len(frames):
        raise ValueError("checkpoint index is outside the frame strip")
    if list(frame_numbers) != sorted(set(frame_numbers)):
        raise ValueError("frame numbers must be unique and increasing")
    sizes = {frame.size for frame in frames}
    if len(sizes) != 1:
        raise ValueError("every frame must have the same dimensions")

    checkpoint_dir = output / BASELINE_CHECKPOINT
    screenshot_path = checkpoint_dir / "screenshot.png"
    strip_path = checkpoint_dir / "frame-strip.png"
    contact_path = checkpoint_dir / "contact-sheet.png"
    localized_diff_path = checkpoint_dir / "localized-image-diff.png"
    diff_metadata_path = checkpoint_dir / "localized-image-diff.json"
    semantic_path = checkpoint_dir / "semantic-snapshot.json"
    trace_path = checkpoint_dir / "writer-trace.json"
    summary_path = checkpoint_dir / "summary.txt"

    normalized_frames = tuple(frame.convert("RGB") for frame in frames)
    checkpoint_frame = normalized_frames[checkpoint_index]
    localized_diff, diff_metadata = _localized_diff(checkpoint_frame)
    _save_png(checkpoint_frame, screenshot_path)
    _save_png(_frame_strip(normalized_frames), strip_path)
    _save_png(
        _contact_sheet(
            normalized_frames,
            frame_numbers,
            checkpoint_index=checkpoint_index,
        ),
        contact_path,
    )
    _save_png(localized_diff, localized_diff_path)
    diff_metadata_path.write_text(
        json.dumps(diff_metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    trace_path.write_text(trace.to_json(), encoding="utf-8")

    linked_snapshot = snapshot.to_dict()
    linked_snapshot["artifacts"] = {
        "contact_sheet": contact_path.relative_to(output).as_posix(),
        "frame_strip": strip_path.relative_to(output).as_posix(),
        "localized_image_diff": localized_diff_path.relative_to(output).as_posix(),
        "localized_image_diff_metadata": diff_metadata_path.relative_to(output).as_posix(),
        "screenshot": screenshot_path.relative_to(output).as_posix(),
        "writer_trace": trace_path.relative_to(output).as_posix(),
    }
    linked_snapshot_obj = SemanticSnapshot.from_dict(linked_snapshot)
    semantic_path.write_text(linked_snapshot_obj.to_json(), encoding="utf-8")
    summary_path.write_text(
        "\n".join(
            (
                f"scenario: {snapshot.scenario}",
                f"checkpoint: {snapshot.checkpoint}",
                f"frame: {snapshot.frame}",
                f"owner: {snapshot.owner.value}",
                f"phase: {snapshot.phase.value}",
                f"generation: {snapshot.generation}",
                f"writer trace entries: {len(trace.entries)}",
                "intentional visual mutation: one inverted center pixel",
                "",
            )
        ),
        encoding="utf-8",
    )

    artifacts = (
        artifact_for_path(ArtifactType.SCREENSHOT, screenshot_path, root=output),
        artifact_for_path(
            ArtifactType.FRAME_STRIP,
            strip_path,
            root=output,
            frame_numbers=tuple(frame_numbers),
        ),
        artifact_for_path(ArtifactType.CONTACT_SHEET, contact_path, root=output),
        artifact_for_path(
            ArtifactType.LOCALIZED_IMAGE_DIFF,
            localized_diff_path,
            root=output,
        ),
        artifact_for_path(
            ArtifactType.STRUCTURED_DIFF,
            diff_metadata_path,
            root=output,
        ),
        artifact_for_path(
            ArtifactType.SEMANTIC_SNAPSHOT,
            semantic_path,
            root=output,
        ),
        artifact_for_path(ArtifactType.WRITER_TRACE, trace_path, root=output),
        artifact_for_path(ArtifactType.COMPACT_SUMMARY, summary_path, root=output),
    )
    manifest = ArtifactManifest(
        rom=snapshot.rom,
        scenario=snapshot.scenario,
        seed=snapshot.seed,
        checkpoints=(
            ArtifactCheckpoint(
                checkpoint=snapshot.checkpoint,
                frame=snapshot.frame,
                artifacts=artifacts,
            ),
        ),
    )
    manifest_path = output / "manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    validate_artifact_files(output, ArtifactManifest.from_json(manifest_path.read_text()))
    if SemanticSnapshot.from_json(semantic_path.read_text()) != linked_snapshot_obj:
        raise AssertionError("emitted semantic snapshot did not round-trip")
    if WriterTrace.from_json(trace_path.read_text()) != trace:
        raise AssertionError("emitted writer trace did not round-trip")
    return manifest


def run_baseline_visual_pipeline(root: Path, output: Path) -> dict[str, object]:
    emulator = Emulator(
        rom=root / "pokeyellow_debug.gbc",
        symbols=root / "pokeyellow_debug.sym",
        results=output / "diagnostics",
        cgb=True,
    )
    try:
        wait_until_debug_ready(emulator)
        frames: list[Image.Image] = []
        frame_numbers: list[int] = []
        snapshot = None
        trace = None
        for index in range(BASELINE_FRAME_COUNT):
            frames.append(emulator.capture_screen())
            frame_numbers.append(emulator.frame)
            if index == CHECKPOINT_FRAME_INDEX:
                snapshot = capture_yellow_baseline_snapshot(
                    emulator,
                    scenario=BASELINE_SCENARIO,
                    seed=BASELINE_SEED,
                    checkpoint=BASELINE_CHECKPOINT,
                )
                trace = read_writer_trace(emulator)
            if index + 1 < BASELINE_FRAME_COUNT:
                emulator.tick()
    finally:
        emulator.close()
    if snapshot is None or trace is None:
        raise AssertionError("baseline visual checkpoint was not captured")
    manifest = write_visual_evidence(
        output,
        frames=frames,
        frame_numbers=frame_numbers,
        checkpoint_index=CHECKPOINT_FRAME_INDEX,
        snapshot=snapshot,
        trace=trace,
    )
    manifest_bytes = manifest.to_json().encode("utf-8")
    semantic_bytes = (output / BASELINE_CHECKPOINT / "semantic-snapshot.json").read_bytes()
    return {
        "schema": VISUAL_PIPELINE_SCHEMA,
        "checkpoint": BASELINE_CHECKPOINT,
        "frame_count": BASELINE_FRAME_COUNT,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "semantic_sha256": hashlib.sha256(semantic_bytes).hexdigest(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit lean Gate 0 visual evidence")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run_baseline_visual_pipeline(args.root, args.output),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
