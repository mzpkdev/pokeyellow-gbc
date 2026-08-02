"""Closed Phase 2 runtime evidence emitter.

The production observation backend must return real pixels and complete
per-case semantic observations before its Emulator closes.  This module never
falls back to schema fixtures or derives an observation from the oracle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import tempfile
from typing import Callable

from PIL import Image

from .errors import RendererConformanceError
from .phase2_conformance_runtime import (
    ACTIVATED_PHASE2_CASE_IDS,
    Phase2Observation,
    canonical_phase2_cases,
    check_phase2_observations,
)
from .phase2_runtime_artifacts import CASE_FILENAMES, GLOBAL_PATHS
from .phase2_runtime_observability import (
    EXPECTED_SCENARIO,
    RELEASE_FALLBACK_CASES,
    Phase2Carrier,
    ReleaseOAMFallbackObservation,
    validate_hostile_records,
)
from .renderer_conformance_artifacts import canonical_case_input, canonical_expected
from .renderer_oracle import derive_expectation
from .visual_pipeline import VisualCheckpointContract, write_runtime_visual_evidence


CAPTURE_SCHEMA = "full-color-phase2-observation-bundle-v1"
INPUT_REPLAY_SCHEMA = "full-color-phase2-input-replay-v1"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class InputReplayEvent:
    """One absolute-frame joypad mask for deterministic cold-boot replay."""

    frame: int
    key_mask: int

    def __post_init__(self) -> None:
        if type(self.frame) is not int or self.frame < 0:
            raise RendererConformanceError("Phase 2 input replay frame is invalid")
        if type(self.key_mask) is not int or not 0 <= self.key_mask <= 0xFF:
            raise RendererConformanceError("Phase 2 input replay key mask is invalid")

    def to_dict(self) -> dict[str, int]:
        return {"frame": self.frame, "key_mask": self.key_mask}


@dataclass(frozen=True, slots=True)
class Phase2ObservationBundle:
    """All actual observations captured before the emulator is closed."""

    observations: tuple[Phase2Observation, ...]
    carriers: tuple[Phase2Carrier, ...]
    release_fallbacks: tuple[ReleaseOAMFallbackObservation, ...]
    frames: tuple[Image.Image, ...]
    frame_numbers: tuple[int, ...]
    checkpoint_index: int
    visual_case_id: str
    input_replay: tuple[InputReplayEvent, ...]
    schema: str = CAPTURE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAPTURE_SCHEMA:
            raise RendererConformanceError("Phase 2 observation bundle schema changed")
        if tuple(item.case_id for item in self.observations) != ACTIVATED_PHASE2_CASE_IDS:
            raise RendererConformanceError(
                "Phase 2 observation bundle lacks the exact ordered 25-case actuals"
            )
        if self.visual_case_id not in ACTIVATED_PHASE2_CASE_IDS:
            raise RendererConformanceError("Phase 2 visual checkpoint has unknown case identity")
        if not 2 <= len(self.frames) <= 31 or len(self.frames) != len(self.frame_numbers):
            raise RendererConformanceError("Phase 2 visual bundle requires 2..31 linked frames")
        if tuple(sorted(set(self.frame_numbers))) != self.frame_numbers:
            raise RendererConformanceError("Phase 2 visual frame numbers are ambiguous")
        if not 0 <= self.checkpoint_index < len(self.frames):
            raise RendererConformanceError("Phase 2 visual checkpoint is outside its strip")
        if not self.input_replay:
            raise RendererConformanceError("Phase 2 capture lacks cold-boot input replay")
        replay_frames = tuple(item.frame for item in self.input_replay)
        if tuple(sorted(replay_frames)) != replay_frames:
            raise RendererConformanceError("Phase 2 input replay is not frame ordered")
        fallback_cases = tuple(item.case for item in self.release_fallbacks)
        if fallback_cases != tuple(case for case, _ in RELEASE_FALLBACK_CASES):
            raise RendererConformanceError("Phase 2 bundle lacks exact release fallback cases")
        validate_hostile_records(self.carriers)


ObservationSource = Callable[[Path, Path], Phase2ObservationBundle]


def _production_source(root: Path, results: Path) -> Phase2ObservationBundle:
    """Load the production backend, failing closed until its complete seam exists."""
    from . import phase2_runtime_observability as observability

    backend = getattr(observability, "capture_phase2_observation_bundle", None)
    if backend is None:
        raise RendererConformanceError(
            "Phase 2 observability closes Emulator after carrier-only capture; "
            "it must expose capture_phase2_observation_bundle with 25 actual "
            "SemanticSnapshot/WriterTrace/boundary observations, captured frame "
            "pixels, and the cold-boot key-mask replay"
        )
    bundle = backend(root, results)
    if not isinstance(bundle, Phase2ObservationBundle):
        raise RendererConformanceError(
            "Phase 2 observability returned an unversioned observation bundle"
        )
    return bundle


def _emit_cases(root: Path, run_dir: Path, bundle: Phase2ObservationBundle) -> None:
    cases = canonical_phase2_cases(root)
    reports = check_phase2_observations(cases, bundle.observations)
    failed = tuple(report.case_id for report in reports if not report.passed)
    if failed:
        raise RendererConformanceError(
            "Phase 2 actual observations failed independent checker: " + ", ".join(failed)
        )
    for case, observation, report in zip(cases, bundle.observations, reports, strict=True):
        case_dir = run_dir / "cases" / case.case_id
        paths = {role: case_dir / filename for role, filename in CASE_FILENAMES.items()}
        _write_json(paths["case-input"], canonical_case_input(case))
        _write_json(paths["expected-patches"], canonical_expected(derive_expectation(case)))
        paths["actual-semantic-snapshot"].write_text(
            observation.snapshot.to_json(), encoding="utf-8"
        )
        paths["actual-writer-trace"].write_text(
            observation.trace.to_json(), encoding="utf-8"
        )
        paths["structured-diff"].write_text(report.to_json(), encoding="utf-8")


def _emit_globals(
    run_dir: Path,
    timing_report: Path,
    bundle: Phase2ObservationBundle,
) -> None:
    _write_json(run_dir / GLOBAL_PATHS["pressure"], {
        "schema": "full-color-phase2-pressure-evidence-v1",
        "scenario": list(EXPECTED_SCENARIO),
        "input_replay": {
            "schema": INPUT_REPLAY_SCHEMA,
            "timebase": "absolute-cold-boot-frame",
            "encoding": "sameboy-joypad-active-high-mask-v1",
            "events": [item.to_dict() for item in bundle.input_replay],
        },
        "actual_carriers": [item.to_dict() for item in bundle.carriers],
    })
    boundaries = [
        {"case_id": item.case_id, "actual": item.boundary.to_dict()}
        for item in bundle.observations if item.boundary is not None
    ]
    _write_json(run_dir / GLOBAL_PATHS["boundary"], {
        "schema": "full-color-phase2-boundary-evidence-v1",
        "actuals": boundaries,
    })
    _write_json(run_dir / GLOBAL_PATHS["reconstruction"], {
        "schema": "full-color-phase2-reconstruction-evidence-v1",
        "actuals": [
            {
                "case_id": item.case_id,
                "checkpoint": item.snapshot.checkpoint,
                "reconstruction": item.snapshot.reconstruction.to_dict(),
            }
            for item in bundle.observations
        ],
    })
    _write_json(run_dir / GLOBAL_PATHS["release-oam-fallback"], {
        "schema": "full-color-phase2-release-oam-fallback-v1",
        "actuals": [asdict(item) for item in bundle.release_fallbacks],
    })
    shutil.copyfile(timing_report, run_dir / GLOBAL_PATHS["timing"])

    visual = next(
        item for item in bundle.observations if item.case_id == bundle.visual_case_id
    )
    write_runtime_visual_evidence(
        run_dir / "visuals",
        contract=VisualCheckpointContract(
            scenario=visual.snapshot.scenario,
            checkpoint=visual.snapshot.checkpoint,
            minimum_frames=2,
            maximum_frames=31,
        ),
        frames=bundle.frames,
        frame_numbers=bundle.frame_numbers,
        checkpoint_index=bundle.checkpoint_index,
        snapshot=visual.snapshot,
        trace=visual.trace,
    )


def Capture(
    root: Path,
    run_dir: Path,
    timing_report: Path,
    *,
    source: ObservationSource = _production_source,
) -> None:
    """Emit every closed runtime role from one real observation bundle."""
    root, run_dir, timing_report = root.resolve(), run_dir.resolve(), timing_report.resolve()
    if not timing_report.is_file():
        raise RendererConformanceError("Phase 2 blocking timing report is unavailable")
    if any(run_dir.iterdir()):
        raise RendererConformanceError("Phase 2 capture directory is not empty")
    with tempfile.TemporaryDirectory(prefix="pokeyellow-phase2-capture-") as temporary:
        bundle = source(root, Path(temporary))
    _emit_cases(root, run_dir, bundle)
    _emit_globals(run_dir, timing_report, bundle)


capture = Capture
