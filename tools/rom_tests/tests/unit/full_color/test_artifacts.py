"""Artifact-manifest linkage and malformed-input tests."""

from copy import deepcopy

import pytest

from tools.rom_tests.full_color.artifacts import (
    ArtifactManifest,
    ManifestValidationError,
)


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
                    {
                        "type": "screenshot",
                        "path": "map-entry/screenshot.png",
                        "frame_numbers": None,
                    },
                    {
                        "type": "frame_strip",
                        "path": "map-entry/frames.png",
                        "frame_numbers": [98, 99, 100, 101, 102],
                    },
                    {
                        "type": "contact_sheet",
                        "path": "map-entry/contact.png",
                        "frame_numbers": None,
                    },
                    {
                        "type": "semantic_snapshot",
                        "path": "map-entry/semantic.json",
                        "frame_numbers": None,
                    },
                    {
                        "type": "writer_trace",
                        "path": "map-entry/trace.json",
                        "frame_numbers": None,
                    },
                    {
                        "type": "compact_summary",
                        "path": "map-entry/summary.txt",
                        "frame_numbers": None,
                    },
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
                {
                    "type": "screenshot",
                    "path": "other.png",
                    "frame_numbers": None,
                }
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
