"""Frozen real-ROM provider for Phase 2 renderer conformance.

The synthetic corpus remains the expectation authority.  This module only
selects the cases realized by the hostile slice and validates the real-ROM
carrier presented to the independent checker.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from .bank_torture import BankTortureResult
from .enums import Owner
from .errors import RendererConformanceError
from .renderer_conformance import ConformanceReport, EvidenceMode, check_case
from .renderer_conformance_artifacts import (
    CANONICAL_CORPUS_CASE_IDS,
    CANONICAL_CORPUS_SHA256,
    canonical_case_input,
)
from .renderer_oracle import (
    CONFORMANCE_CORPUS_SCHEMA,
    REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES,
    ConformanceCase,
    load_corpus,
)
from .snapshots import SemanticSnapshot
from .trace import WriterTrace


CORPUS_RELATIVE = Path(
    "tools/rom_tests/fixtures/full_color/renderer-conformance/cases.json"
)

# The debug scenario realizes every non-overlay operation in the corpus.  The
# overlay checkpoint deliberately runs the complete diagnostic OVERWORLD
# matrix, so omitting a matrix edge here would turn runtime evidence into a
# hand-picked happy path.  Keep this tuple literal and ordered: it is a sibling
# authority, never an alias that can drift with the synthetic manifest.
ACTIVATED_PHASE2_CASE_IDS = (
    "RC-OVERLAY-OPAQUE-EXPLICIT",
    "RC-OVERLAY-OPAQUE-DEFAULT",
    "RC-OVERLAY-REVEALED-LOOKUP",
    "RC-OVERLAY-REVEALED-OVERRIDE",
    "RC-OVERLAY-FULLY-CLIPPED",
    "RC-OVERLAY-PARTIAL-CLIP",
    "RC-OVERLAY-PARTIAL-RIGHT",
    "RC-OVERLAY-PARTIAL-TOP",
    "RC-OVERLAY-PARTIAL-BOTTOM",
    "RC-OVERLAY-MAP-EDGE",
    "RC-OVERLAY-CONNECTION",
    "RC-OVERLAY-WINDOW",
    "RC-OVERLAY-ALTERNATE-BG",
    "RC-OVERLAY-ALTERNATE-MAP",
    "RC-TRANSFER-ROW",
    "RC-TRANSFER-COLUMN",
    "RC-TRANSFER-CONNECTION",
    "RC-PALETTE-BG",
    "RC-PALETTE-OBJ",
    "RC-OAM-MISSING_IDENTITY",
    "RC-OAM-OUT_OF_RANGE_IDENTITY",
    "RC-OAM-UNMAPPED_IDENTITY",
    "RC-RECONSTRUCTION",
    "RC-OWNERSHIP-REPLACEMENT",
    "RC-MACHINE-FAR-CALL",
)

_OVERLAY_CASE_IDS = ACTIVATED_PHASE2_CASE_IDS[:14]
_CASE_CHECKPOINTS = MappingProxyType({
    **{case_id: "diagnostic-overlay-matrix" for case_id in _OVERLAY_CASE_IDS},
    "RC-TRANSFER-ROW": "horizontal",
    "RC-TRANSFER-COLUMN": "vertical",
    "RC-TRANSFER-CONNECTION": "north-route1-connection",
    "RC-PALETTE-BG": "map-entry",
    "RC-PALETTE-OBJ": "follower-npc-oam",
    "RC-OAM-MISSING_IDENTITY": "release-oam-fallback-probe",
    "RC-OAM-OUT_OF_RANGE_IDENTITY": "release-oam-fallback-probe",
    "RC-OAM-UNMAPPED_IDENTITY": "release-oam-fallback-probe",
    "RC-RECONSTRUCTION": "party-return",
    "RC-OWNERSHIP-REPLACEMENT": "map-entry-party-handoff",
    "RC-MACHINE-FAR-CALL": "non-default-banks-interrupt-pressure",
})

# Each approved hostile mutation is pinned to at least one activated case whose
# retained diff must expose it.  Runners may fan a mutation over more cases,
# but cannot rename it or claim sensitivity outside this closed table.
PHASE2_MUTATION_SENSITIVITY = MappingProxyType({
    "MUT-P2-WRONG-OWNER": ("RC-OWNERSHIP-REPLACEMENT",),
    "MUT-P2-INVALID-OWNERSHIP-TRANSITION": ("RC-OWNERSHIP-REPLACEMENT",),
    "MUT-P2-STALE-ADMISSION": ("RC-OWNERSHIP-REPLACEMENT",),
    "MUT-P2-STALE-JOB": ("RC-OWNERSHIP-REPLACEMENT",),
    "MUT-P2-CAPACITY-PLUS-ONE": ("RC-TRANSFER-ROW",),
    "MUT-P2-LOST-ADMITTED-WORK": ("RC-TRANSFER-ROW",),
    "MUT-P2-MISSING-ATTRIBUTE": ("RC-TRANSFER-ROW",),
    "MUT-P2-INSUFFICIENT-PREVISIBLE-BUDGET": ("RC-MACHINE-FAR-CALL",),
    "MUT-P2-MISSING-RESERVATION": ("RC-MACHINE-FAR-CALL",),
    "MUT-P2-VISIBLE-MID-COMMIT-INTERRUPTION": ("RC-TRANSFER-CONNECTION",),
    "MUT-P2-VRAM-OVERLAY-ORACLE": ("RC-OVERLAY-OPAQUE-EXPLICIT",),
    "MUT-P2-AMBIENT-MAP-OVERLAY-ORACLE": ("RC-OVERLAY-REVEALED-LOOKUP",),
    "MUT-P2-OVERLAY-MAPPING-LOSS": ("RC-OVERLAY-PARTIAL-CLIP",),
    "MUT-P2-INCOMPLETE-RECONSTRUCTION": ("RC-RECONSTRUCTION",),
    "MUT-P2-OAM-FALLBACK": (
        "RC-OAM-MISSING_IDENTITY",
        "RC-OAM-OUT_OF_RANGE_IDENTITY",
        "RC-OAM-UNMAPPED_IDENTITY",
    ),
    "MUT-P2-THRESHOLD-PLUS-ONE": ("RC-MACHINE-FAR-CALL",),
    "MUT-P2-WRAM-BANK-LEAK": ("RC-MACHINE-FAR-CALL",),
    "MUT-P2-UNEXPECTED-WRITER": ("RC-OWNERSHIP-REPLACEMENT",),
    "MUT-P2-SNAPSHOT-CORRUPTION": ("RC-TRANSFER-ROW",),
})


def canonical_phase2_cases(root: Path) -> tuple[ConformanceCase, ...]:
    """Load the exact 25-case authority and return the fixed Phase 2 slice."""

    path = root.resolve() / CORPUS_RELATIVE
    try:
        cases = load_corpus(json.loads(path.read_bytes()))
    except Exception as exc:
        raise RendererConformanceError(
            f"authoritative renderer corpus is invalid: {exc}"
        ) from exc
    case_ids = tuple(case.case_id for case in cases)
    if case_ids != CANONICAL_CORPUS_CASE_IDS:
        raise RendererConformanceError(
            "Phase 2 runtime case source changed the exact synthetic 25-case authority"
        )
    canonical_payload = json.dumps(
        {
            "schema": CONFORMANCE_CORPUS_SCHEMA,
            "authoritative_mapped_picture_identities": sorted(
                REQUIRED_SYNTHETIC_MAPPED_PICTURE_IDENTITIES
            ),
            "cases": [canonical_case_input(case) for case in cases],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if hashlib.sha256(canonical_payload).hexdigest() != CANONICAL_CORPUS_SHA256:
        raise RendererConformanceError(
            "Phase 2 runtime case source does not match the authoritative synthetic corpus"
        )
    if case_ids != ACTIVATED_PHASE2_CASE_IDS:
        raise RendererConformanceError(
            "Phase 2 activated cases do not cover the exact hostile diagnostic matrix"
        )
    return cases


def phase2_case_checkpoints() -> Mapping[str, str]:
    """Expose the immutable runtime-case rationale to artifact manifests."""

    return _CASE_CHECKPOINTS


@dataclass(frozen=True, slots=True)
class Phase2Observation:
    """One atomic semantic, trace, and optional machine-boundary observation."""

    case_id: str
    rom_identity: str
    snapshot: SemanticSnapshot
    trace: WriterTrace
    boundary: BankTortureResult | None


def _validate_observation(
    case: ConformanceCase, observation: Phase2Observation
) -> Phase2Observation:
    snapshot = observation.snapshot
    if observation.case_id != case.case_id or snapshot.scenario != case.case_id:
        raise RendererConformanceError("Phase 2 observation has wrong case identity")
    if snapshot.rom != observation.rom_identity:
        raise RendererConformanceError("Phase 2 observation has wrong ROM identity")
    if re.fullmatch(r"pokeyellow_debug\.gbc:[0-9a-f]{64}", snapshot.rom) is None:
        raise RendererConformanceError(
            "Phase 2 observation is not bound to an exact debug ROM SHA-256"
        )
    if snapshot.evidence_kind != "RENDERER_RUNTIME":
        raise RendererConformanceError("Phase 2 observation has wrong provenance")
    if snapshot.activation_phase != 2:
        raise RendererConformanceError("Phase 2 observation has wrong activation phase")
    if snapshot.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD:
        raise RendererConformanceError("Phase 2 observation has wrong owner")
    if snapshot.generation != case.inputs["generation"]:
        raise RendererConformanceError("Phase 2 observation has wrong generation")
    boundary_required = case.observation_boundary is not None
    if boundary_required != (observation.boundary is not None):
        raise RendererConformanceError(
            "Phase 2 observation has missing or unexpected boundary evidence"
        )
    if observation.boundary is not None:
        if observation.boundary.case.case_id != case.case_id:
            raise RendererConformanceError(
                "Phase 2 observation has wrong boundary case identity"
            )
        if observation.boundary.before.generation != case.inputs["generation"]:
            raise RendererConformanceError(
                "Phase 2 observation has wrong boundary generation"
            )
    return observation


@dataclass(frozen=True, slots=True)
class FrozenPhase2Provider:
    """Freeze case observations so checker access cannot recapture ROM state."""

    observations: tuple[Phase2Observation, ...]

    def __post_init__(self) -> None:
        ids = tuple(item.case_id for item in self.observations)
        if ids != ACTIVATED_PHASE2_CASE_IDS:
            raise RendererConformanceError(
                "Phase 2 observations do not match activated case order"
            )
        identities = {item.rom_identity for item in self.observations}
        if len(identities) != 1:
            raise RendererConformanceError(
                "Phase 2 observations do not bind one debug ROM identity"
            )

    def _observation(self, case: ConformanceCase) -> Phase2Observation:
        if case.case_id not in ACTIVATED_PHASE2_CASE_IDS:
            raise RendererConformanceError(
                f"Phase 2 runtime case is not activated: {case.case_id}"
            )
        observation = self.observations[
            ACTIVATED_PHASE2_CASE_IDS.index(case.case_id)
        ]
        return _validate_observation(case, observation)

    def snapshot(self, case: ConformanceCase) -> SemanticSnapshot:
        return self._observation(case).snapshot

    def trace(self, case: ConformanceCase) -> WriterTrace:
        return self._observation(case).trace

    def boundary(self, case: ConformanceCase) -> BankTortureResult | None:
        return self._observation(case).boundary


def check_phase2_observation(
    case: ConformanceCase, observation: Phase2Observation
) -> ConformanceReport:
    """Check one observation while retaining the full-provider invariants."""

    if case.case_id not in ACTIVATED_PHASE2_CASE_IDS:
        raise RendererConformanceError(
            f"Phase 2 runtime case is not activated: {case.case_id}"
        )
    class _SingleCaseProvider:
        def snapshot(self, requested: ConformanceCase) -> SemanticSnapshot:
            return _require_single(requested).snapshot

        def trace(self, requested: ConformanceCase) -> WriterTrace:
            return _require_single(requested).trace

        def boundary(self, requested: ConformanceCase) -> BankTortureResult | None:
            return _require_single(requested).boundary

    def _require_single(requested: ConformanceCase) -> Phase2Observation:
        if requested.case_id != case.case_id:
            raise RendererConformanceError("Phase 2 single-case provider changed case")
        return _validate_observation(requested, observation)

    return check_case(case, _SingleCaseProvider(), mode=EvidenceMode.ROM_RUNTIME)


def check_phase2_observations(
    cases: tuple[ConformanceCase, ...],
    observations: tuple[Phase2Observation, ...],
) -> tuple[ConformanceReport, ...]:
    """Check one complete ordered Phase 2 runtime corpus."""

    if tuple(case.case_id for case in cases) != ACTIVATED_PHASE2_CASE_IDS:
        raise RendererConformanceError("Phase 2 cases do not match activated case order")
    provider = FrozenPhase2Provider(observations)
    return tuple(
        check_case(case, provider, mode=EvidenceMode.ROM_RUNTIME) for case in cases
    )
