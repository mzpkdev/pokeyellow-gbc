"""Artifact-manifest linkage and malformed-input tests."""

from copy import deepcopy

import pytest

from tools.rom_tests.full_color.artifacts import (
    Artifact,
    ArtifactManifest,
    MANIFEST_SCHEMA,
    ManifestValidationError,
)

HASH = "0" * 64


def artifact(artifact_type: str, path: str, frames: object = None) -> dict[str, object]:
    return {
        "type": artifact_type,
        "path": path,
        "frame_numbers": frames,
        "size_bytes": 1,
        "sha256": HASH,
    }


def manifest_dict() -> dict[str, object]:
    return {
        "schema": "full-color-artifact-manifest-v1",
        "semantic_schema": "full-color-contract-v1",
        "trace_schema": "full-color-writer-trace-v1",
        "rom": "pokeyellow_debug.gbc:abc123",
        "scenario": "baseline",
        "seed": 7,
        "checkpoints": [
            {
                "checkpoint": "map_entry",
                "frame": 100,
                "artifacts": [
                    artifact("screenshot", "map-entry/screenshot.png"),
                    artifact(
                        "frame_strip",
                        "map-entry/frames.png",
                        [98, 99, 100, 101, 102],
                    ),
                    artifact("contact_sheet", "map-entry/contact.png"),
                    artifact("localized_image_diff", "map-entry/diff.png"),
                    artifact("semantic_snapshot", "map-entry/semantic.json"),
                    artifact("writer_trace", "map-entry/trace.json"),
                    artifact("compact_summary", "map-entry/summary.txt"),
                ],
                "timing_row_keys": [],
            }
        ],
    }


def test_manifest_round_trip_is_canonical() -> None:
    manifest = ArtifactManifest.from_dict(manifest_dict())

    assert ArtifactManifest.from_json(manifest.to_json()) == manifest


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda raw: raw["checkpoints"][0]["artifacts"].pop(),
            "checkpoint requires compact_summary",
        ),
        (
            lambda raw: raw["checkpoints"][0]["artifacts"][0].update(
                {"path": "../escape.png"}
            ),
            "normalized and relative",
        ),
        (
            lambda raw: raw["checkpoints"][0]["artifacts"].append(
                artifact("screenshot", "other.png")
            ),
            "duplicate artifact type",
        ),
        (
            lambda raw: raw["checkpoints"][0].update(
                {"timing_row_keys": ["TIME-ROW"]}
            ),
            "timing keys require a timing artifact",
        ),
        (
            lambda raw: raw.update({"unknown": True}),
            "unknown fields: unknown",
        ),
        (
            lambda raw: raw["checkpoints"][0]["artifacts"][0].update(
                {"sha256": "BAD"}
            ),
            "64 lowercase hexadecimal digits",
        ),
    ],
)
def test_malformed_manifest_fails_specifically(mutate: object, message: str) -> None:
    raw = deepcopy(manifest_dict())
    mutate(raw)

    with pytest.raises(ManifestValidationError, match=message):
        ArtifactManifest.from_dict(raw)


@pytest.mark.parametrize(
    ("frame_numbers", "message"),
    [
        ([98, 100, 99], "unique increasing"),
        ([98, 99, 101], "include checkpoint frame"),
        (list(range(32)), "requires 1..31"),
    ],
)
def test_frame_strip_numbers_are_bounded_ordered_and_linked_to_checkpoint(
    frame_numbers: list[int], message: str
) -> None:
    raw = manifest_dict()
    raw["checkpoints"][0]["artifacts"][1]["frame_numbers"] = frame_numbers

    with pytest.raises(ManifestValidationError, match=message):
        ArtifactManifest.from_dict(raw)


def test_visual_manifest_contract_stays_separate_from_renderer_conformance() -> None:
    assert MANIFEST_SCHEMA == "full-color-artifact-manifest-v1"
    with pytest.raises(ManifestValidationError, match="unknown artifact type"):
        Artifact.from_dict(
            {
                "type": "expected_snapshot",
                "path": "expected.json",
                "frame_numbers": None,
                "size_bytes": 1,
                "sha256": "0" * 64,
            },
            path="artifact",
        )
