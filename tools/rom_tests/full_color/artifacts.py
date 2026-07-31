"""Contract-versioned manifest for linked visual and semantic evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import PurePosixPath
from typing import Any

from ._validation import require_int, require_object, require_str
from .errors import ManifestValidationError
from .snapshots import SNAPSHOT_SCHEMA
from .trace import TRACE_SCHEMA

MANIFEST_SCHEMA = "full-color-artifact-manifest-v1"
MAX_FRAME_STRIP_FRAMES = 31


class ArtifactType(StrEnum):
    SCREENSHOT = "screenshot"
    FRAME_STRIP = "frame_strip"
    CONTACT_SHEET = "contact_sheet"
    SEMANTIC_SNAPSHOT = "semantic_snapshot"
    WRITER_TRACE = "writer_trace"
    STRUCTURED_DIFF = "structured_diff"
    TIMING = "timing"
    COMPACT_SUMMARY = "compact_summary"


def _relative_path(value: object, *, path: str) -> str:
    text = require_str(value, path=path, error=ManifestValidationError)
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
        raise ManifestValidationError(
            f"{path}: artifact path must be normalized and relative, got {text!r}"
        )
    if "\\" in text or text != str(parsed):
        raise ManifestValidationError(
            f"{path}: artifact path must use normalized POSIX separators, got {text!r}"
        )
    return text


@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType
    path: str
    frame_numbers: tuple[int, ...] | None

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> Artifact:
        obj = require_object(
            raw,
            path=path,
            required={"type", "path", "frame_numbers"},
            error=ManifestValidationError,
        )
        type_raw = require_str(obj["type"], path=f"{path}.type", error=ManifestValidationError)
        try:
            artifact_type = ArtifactType(type_raw)
        except ValueError as exc:
            raise ManifestValidationError(
                f"{path}.type: unknown artifact type {type_raw!r}"
            ) from exc
        frames_raw = obj["frame_numbers"]
        if artifact_type is ArtifactType.FRAME_STRIP:
            if (
                not isinstance(frames_raw, list)
                or not 1 <= len(frames_raw) <= MAX_FRAME_STRIP_FRAMES
            ):
                raise ManifestValidationError(
                    f"{path}.frame_numbers: frame strip requires 1.."
                    f"{MAX_FRAME_STRIP_FRAMES} frames"
                )
            frames = tuple(
                require_int(
                    value,
                    path=f"{path}.frame_numbers[{index}]",
                    error=ManifestValidationError,
                )
                for index, value in enumerate(frames_raw)
            )
            if list(frames) != sorted(frames) or len(frames) != len(set(frames)):
                raise ManifestValidationError(
                    f"{path}.frame_numbers: expected unique increasing frame numbers"
                )
        else:
            if frames_raw is not None:
                raise ManifestValidationError(
                    f"{path}.frame_numbers: only frame_strip artifacts carry frames"
                )
            frames = None
        artifact_path = _relative_path(obj["path"], path=f"{path}.path")
        if (
            artifact_type is ArtifactType.COMPACT_SUMMARY
            and PurePosixPath(artifact_path).suffix not in {".txt", ".md"}
        ):
            raise ManifestValidationError(
                f"{path}.path: compact_summary must be a .txt or .md text artifact"
            )
        return cls(
            type=artifact_type,
            path=artifact_path,
            frame_numbers=frames,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "path": self.path,
            "frame_numbers": (
                None if self.frame_numbers is None else list(self.frame_numbers)
            ),
        }


@dataclass(frozen=True, slots=True)
class ArtifactCheckpoint:
    checkpoint: str
    frame: int
    artifacts: tuple[Artifact, ...]
    timing_row_keys: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> ArtifactCheckpoint:
        obj = require_object(
            raw,
            path=path,
            required={"checkpoint", "frame", "artifacts", "timing_row_keys"},
            error=ManifestValidationError,
        )
        artifacts_raw = obj["artifacts"]
        if not isinstance(artifacts_raw, list) or not artifacts_raw:
            raise ManifestValidationError(f"{path}.artifacts: expected a non-empty array")
        artifacts = tuple(
            Artifact.from_dict(item, path=f"{path}.artifacts[{index}]")
            for index, item in enumerate(artifacts_raw)
        )
        types = [artifact.type for artifact in artifacts]
        paths = [artifact.path for artifact in artifacts]
        if len(types) != len(set(types)):
            raise ManifestValidationError(
                f"{path}.artifacts: duplicate artifact type within checkpoint"
            )
        if len(paths) != len(set(paths)):
            raise ManifestValidationError(f"{path}.artifacts: duplicate artifact path")
        required_checkpoint_artifacts = {
            ArtifactType.SCREENSHOT,
            ArtifactType.FRAME_STRIP,
            ArtifactType.CONTACT_SHEET,
            ArtifactType.SEMANTIC_SNAPSHOT,
            ArtifactType.WRITER_TRACE,
            ArtifactType.COMPACT_SUMMARY,
        }
        missing = required_checkpoint_artifacts - set(types)
        if missing:
            labels = ", ".join(sorted(item.value for item in missing))
            raise ManifestValidationError(
                f"{path}.artifacts: checkpoint requires {labels}"
            )
        frame_strip = next(
            artifact
            for artifact in artifacts
            if artifact.type is ArtifactType.FRAME_STRIP
        )
        checkpoint_frame = require_int(
            obj["frame"], path=f"{path}.frame", error=ManifestValidationError
        )
        frame_numbers = frame_strip.frame_numbers
        if frame_numbers is None or checkpoint_frame not in frame_numbers:
            raise ManifestValidationError(
                f"{path}.artifacts: frame_strip frame_numbers must include "
                "checkpoint frame"
            )

        timing_raw = obj["timing_row_keys"]
        if not isinstance(timing_raw, list):
            raise ManifestValidationError(f"{path}.timing_row_keys: expected an array")
        timing = tuple(
            require_str(
                value,
                path=f"{path}.timing_row_keys[{index}]",
                error=ManifestValidationError,
            )
            for index, value in enumerate(timing_raw)
        )
        if len(timing) != len(set(timing)):
            raise ManifestValidationError(f"{path}.timing_row_keys: duplicate key")
        if timing and ArtifactType.TIMING not in types:
            raise ManifestValidationError(
                f"{path}.timing_row_keys: timing keys require a timing artifact"
            )
        return cls(
            checkpoint=require_str(
                obj["checkpoint"], path=f"{path}.checkpoint", error=ManifestValidationError
            ),
            frame=checkpoint_frame,
            artifacts=artifacts,
            timing_row_keys=timing,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint,
            "frame": self.frame,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "timing_row_keys": list(self.timing_row_keys),
        }


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    rom: str
    scenario: str
    seed: int
    checkpoints: tuple[ArtifactCheckpoint, ...]
    semantic_schema: str = SNAPSHOT_SCHEMA
    trace_schema: str = TRACE_SCHEMA
    schema: str = MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if not self.checkpoints:
            raise ManifestValidationError("manifest.checkpoints: expected at least one checkpoint")
        labels = [item.checkpoint for item in self.checkpoints]
        if len(labels) != len(set(labels)):
            raise ManifestValidationError("manifest.checkpoints: duplicate checkpoint name")
        all_paths = [
            artifact.path
            for checkpoint in self.checkpoints
            for artifact in checkpoint.artifacts
        ]
        if len(all_paths) != len(set(all_paths)):
            raise ManifestValidationError("manifest.checkpoints: artifact paths must be globally unique")

    @classmethod
    def from_dict(cls, raw: object) -> ArtifactManifest:
        obj = require_object(
            raw,
            path="manifest",
            required={
                "schema", "semantic_schema", "trace_schema", "rom", "scenario",
                "seed", "checkpoints",
            },
            error=ManifestValidationError,
        )
        expected_versions = {
            "schema": MANIFEST_SCHEMA,
            "semantic_schema": SNAPSHOT_SCHEMA,
            "trace_schema": TRACE_SCHEMA,
        }
        for field, expected in expected_versions.items():
            if obj[field] != expected:
                raise ManifestValidationError(
                    f"manifest.{field}: unsupported version {obj[field]!r}; expected {expected!r}"
                )
        checkpoints_raw = obj["checkpoints"]
        if not isinstance(checkpoints_raw, list) or not checkpoints_raw:
            raise ManifestValidationError("manifest.checkpoints: expected a non-empty array")
        return cls(
            rom=require_str(obj["rom"], path="manifest.rom", error=ManifestValidationError),
            scenario=require_str(
                obj["scenario"], path="manifest.scenario", error=ManifestValidationError
            ),
            seed=require_int(obj["seed"], path="manifest.seed", error=ManifestValidationError),
            checkpoints=tuple(
                ArtifactCheckpoint.from_dict(item, path=f"manifest.checkpoints[{index}]")
                for index, item in enumerate(checkpoints_raw)
            ),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> ArtifactManifest:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ManifestValidationError(f"manifest: invalid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "semantic_schema": self.semantic_schema,
            "trace_schema": self.trace_schema,
            "rom": self.rom,
            "scenario": self.scenario,
            "seed": self.seed,
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
