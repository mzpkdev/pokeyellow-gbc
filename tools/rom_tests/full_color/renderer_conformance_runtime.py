"""Phase 1 real-ROM provider for the independent conformance checker."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from tools.rom_tests.emulator import Emulator

from .enums import Owner, Phase
from .errors import RendererConformanceError
from .renderer_conformance import (
    ConformanceReport,
    EvidenceMode,
    check_case,
)
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
from .runtime_observability import (
    RuntimeObservation,
    capture_phase1_runtime_observation,
)

ACTIVATED_PHASE1_CASE_IDS = ("RC-OWNERSHIP-REPLACEMENT",)
CORPUS_RELATIVE = Path(
    "tools/rom_tests/fixtures/full_color/renderer-conformance/cases.json"
)


def canonical_phase1_case(root: Path) -> ConformanceCase:
    """Select the one runtime case without weakening the 25-case authority."""

    path = root / CORPUS_RELATIVE
    payload = path.read_bytes()
    try:
        cases = load_corpus(json.loads(payload))
    except Exception as exc:
        raise RendererConformanceError(
            f"authoritative renderer corpus is invalid: {exc}"
        ) from exc
    case_ids = tuple(case.case_id for case in cases)
    if case_ids != CANONICAL_CORPUS_CASE_IDS:
        raise RendererConformanceError(
            "runtime case source changed the exact synthetic 25-case authority"
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
            "runtime case source does not match the authoritative synthetic corpus"
        )
    return cases[case_ids.index(ACTIVATED_PHASE1_CASE_IDS[0])]


@dataclass(frozen=True, slots=True)
class FrozenRuntimeProvider:
    """Cache one atomic observation for all checker carrier requests."""

    observation: RuntimeObservation

    def _require_case(self, case: ConformanceCase) -> None:
        if case.case_id not in ACTIVATED_PHASE1_CASE_IDS:
            raise RendererConformanceError(
                f"Phase 1 runtime case is not activated: {case.case_id}"
            )
        if case.case_id != self.observation.case_id:
            raise RendererConformanceError(
                "runtime observation case identity does not match requested case"
            )
        snapshot = self.observation.snapshot
        if snapshot.rom != self.observation.rom_identity:
            raise RendererConformanceError("runtime observation has wrong ROM identity")
        if snapshot.scenario != case.case_id:
            raise RendererConformanceError("runtime observation has wrong case identity")
        if snapshot.evidence_kind != "RENDERER_RUNTIME":
            raise RendererConformanceError("runtime observation has wrong provenance")
        if snapshot.activation_phase != 1:
            raise RendererConformanceError(
                "runtime observation has wrong activation phase"
            )
        if snapshot.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD:
            raise RendererConformanceError("runtime observation has wrong owner")
        if snapshot.phase is not Phase.OVERWORLD_ACTIVE:
            raise RendererConformanceError("runtime observation has wrong phase")
        if snapshot.generation != case.inputs["generation"]:
            raise RendererConformanceError("runtime observation has wrong generation")

    def snapshot(self, case: ConformanceCase):
        self._require_case(case)
        return self.observation.snapshot

    def trace(self, case: ConformanceCase):
        self._require_case(case)
        return self.observation.trace

    def boundary(self, case: ConformanceCase):
        self._require_case(case)
        return None


def check_runtime_observation(
    case: ConformanceCase, observation: RuntimeObservation
) -> ConformanceReport:
    if case.case_id not in ACTIVATED_PHASE1_CASE_IDS:
        raise RendererConformanceError(
            f"Phase 1 runtime case is not activated: {case.case_id}"
        )
    return check_case(
        case,
        FrozenRuntimeProvider(observation),
        mode=EvidenceMode.ROM_RUNTIME,
    )


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def check_phase1_runtime(root: Path, output: Path) -> ConformanceReport:
    """Boot, capture, compare, and retain the activated Phase 1 observation."""

    root = root.resolve()
    case = canonical_phase1_case(root)
    emulator = Emulator(
        rom=root / "pokeyellow_phase1_debug.gbc",
        symbols=root / "pokeyellow_phase1_debug.sym",
        results=output / "diagnostics",
        cgb=True,
    )
    try:
        observation = capture_phase1_runtime_observation(emulator, case)
    finally:
        emulator.close()
    report = check_runtime_observation(case, observation)
    _write_atomic(
        output / "actual-semantic-snapshot.json", observation.snapshot.to_json()
    )
    _write_atomic(output / "actual-writer-trace.json", observation.trace.to_json())
    _write_atomic(output / "structured-diff.json", report.to_json())
    return report
