"""Exact semantic regression comparison around Phase 1 ownership diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json

from .enums import Owner, Phase
from .renderer_conformance import ConformanceDifference
from .snapshots import SemanticSnapshot

BASELINE_REPORT_SCHEMA = "full-color-phase1-baseline-report-v1"
BASELINE_RESOURCE_FIELDS = (
    "bg_tile_ids",
    "bg_attributes",
    "bg_palettes",
    "obj_palettes",
    "shadow_oam",
    "hardware_oam",
    "map_id",
    "tileset_id",
    "dirty",
    "banks",
)
_ALLOWED_TO_CHANGE = frozenset(
    {"checkpoint", "frame", "generation", "traced_writer_ids"}
)

class GenerationContract(StrEnum):
    FRESH = "fresh"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class BaselineSemanticReport:
    passed: bool
    differences: tuple[ConformanceDifference, ...]
    schema: str = BASELINE_REPORT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "passed": self.passed,
            "differences": [difference.to_dict() for difference in self.differences],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def _resource_differences(
    name: str, before: object, after: object
) -> list[ConformanceDifference]:
    if before == after:
        return []
    if isinstance(before, bytes) and isinstance(after, bytes):
        differences = []
        for offset, (expected, actual) in enumerate(zip(before, after, strict=False)):
            if expected != actual:
                differences.append(
                    ConformanceDifference(f"{name}[0x{offset:04x}]", expected, actual)
                )
        if len(before) != len(after):
            differences.append(
                ConformanceDifference(f"{name}.length", len(before), len(after))
            )
        return differences
    expected = (
        before.to_dict()
        if hasattr(before, "to_dict")
        else dict(before)
        if isinstance(before, tuple)
        else before
    )
    actual = (
        after.to_dict()
        if hasattr(after, "to_dict")
        else dict(after)
        if isinstance(after, tuple)
        else after
    )
    return [ConformanceDifference(name, expected, actual)]


def compare_phase1_baseline(
    before: SemanticSnapshot,
    after: SemanticSnapshot,
    *,
    generation_contract: GenerationContract = GenerationContract.FRESH,
) -> BaselineSemanticReport:
    """Require a no-visual-change Yellow restore with a fresh generation."""

    differences: list[ConformanceDifference] = []
    for field in BASELINE_RESOURCE_FIELDS:
        differences.extend(
            _resource_differences(field, getattr(before, field), getattr(after, field))
        )

    before_dict = before.to_dict()
    after_dict = after.to_dict()
    already_compared = set(BASELINE_RESOURCE_FIELDS) | _ALLOWED_TO_CHANGE
    for field in sorted(set(before_dict) - already_compared):
        if before_dict[field] != after_dict[field]:
            differences.append(
                ConformanceDifference(field, before_dict[field], after_dict[field])
            )

    if after.owner is not Owner.RENDERER_YELLOW:
        differences.append(
            ConformanceDifference(
                "owner", Owner.RENDERER_YELLOW.value, after.owner.value
            )
        )
    if after.phase is not Phase.YELLOW_ACTIVE:
        differences.append(
            ConformanceDifference(
                "phase", Phase.YELLOW_ACTIVE.value, after.phase.value
            )
        )
    if after.job is not None:
        differences.append(ConformanceDifference("job", None, after.job.to_dict()))
    if after.queued_jobs:
        differences.append(
            ConformanceDifference(
                "queued_jobs", [], [job.to_dict() for job in after.queued_jobs]
            )
        )
    if generation_contract is GenerationContract.FRESH and after.generation == before.generation:
        differences.append(
            ConformanceDifference("generation", "fresh token", after.generation)
        )
    if generation_contract is GenerationContract.UNCHANGED and after.generation != before.generation:
        differences.append(
            ConformanceDifference("generation", before.generation, after.generation)
        )
    if after.frame < before.frame:
        differences.append(
            ConformanceDifference("frame", f">={before.frame}", after.frame)
        )

    # Avoid duplicate owner/job paths already found by the exact-field loop.
    unique: dict[tuple[str, str, str], ConformanceDifference] = {}
    for difference in differences:
        key = (
            difference.path,
            repr(difference.expected),
            repr(difference.actual),
        )
        unique.setdefault(key, difference)
    ordered = tuple(
        sorted(unique.values(), key=lambda difference: difference.path)
    )
    return BaselineSemanticReport(not ordered, ordered)
