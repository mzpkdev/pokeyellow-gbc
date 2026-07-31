"""Committed observation provider and observed-side checker mutations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, replace
import json
from pathlib import Path, PurePosixPath
from typing import Callable

from .bank_torture import BankTortureResult, BoundarySnapshot
from .errors import RendererConformanceError
from .renderer_oracle import ConformanceCase
from .enums import ReconstructionProvenance
from .snapshots import SemanticSnapshot
from .trace import WriterTrace, WriterTraceEntry

Mutation = Callable[[dict[str, object], dict[str, object]], None]

MUTATION_CASES = {
    "wrong-attribute-byte": "RC-OVERLAY-PARTIAL-CLIP",
    "lost-clipped-coordinate": "RC-OVERLAY-PARTIAL-CLIP",
    "partial-paired-commit": "RC-TRANSFER-ROW",
    "saved-byte-reconstruction": "RC-RECONSTRUCTION",
    "missing-oam-fallback": "RC-OAM-MISSING_IDENTITY",
    "oam-control-bit-loss": "RC-OAM-MISSING_IDENTITY",
    "wrong-owner-writer": "RC-OWNERSHIP-REPLACEMENT",
    "stale-generation-writer": "RC-OWNERSHIP-REPLACEMENT",
    "write-after-cancellation": "RC-OWNERSHIP-REPLACEMENT",
    "bank-leak": "RC-MACHINE-FAR-CALL",
    "stack-pointer-leak": "RC-MACHINE-FAR-CALL",
    "stack-window-leak": "RC-MACHINE-FAR-CALL",
    "ime-leak": "RC-MACHINE-FAR-CALL",
    "interrupt-enable-leak": "RC-MACHINE-FAR-CALL",
    "interrupt-flags-leak": "RC-MACHINE-FAR-CALL",
}


def _xor_hex_byte(
    raw: dict[str, object], name: str, offset: int, mask: int = 1
) -> None:
    payload = bytearray.fromhex(str(raw[name]))
    payload[offset] ^= mask
    raw[name] = payload.hex()


def mutate_wrong_attribute_byte(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    _xor_hex_byte(snapshot, "bg_attributes", 0x07C0)


def mutate_lost_clipped_coordinate(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    overlay = snapshot["overlay_request"]
    assert isinstance(overlay, dict)
    mappings = overlay["clipped_mappings"]
    assert isinstance(mappings, list)
    mappings.pop(0)


def mutate_partial_paired_commit(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    _xor_hex_byte(snapshot, "bg_attributes", 0x0062)


def mutate_saved_byte_reconstruction(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    reconstruction = snapshot["reconstruction"]
    assert isinstance(reconstruction, dict)
    provenance = reconstruction["item_provenance"]
    assert isinstance(provenance, dict)
    provenance["tilemaps_and_attributes"] = "SAVED_VRAM"


def mutate_missing_oam_fallback(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    fallback = snapshot["oam_fallback"]
    assert isinstance(fallback, dict)
    fallback["occurred"] = False


def mutate_oam_control_bit_loss(
    snapshot: dict[str, object], _: dict[str, object]
) -> None:
    fallback = snapshot["oam_fallback"]
    assert isinstance(fallback, dict)
    fallback["after_attributes"] = int(fallback["after_attributes"]) ^ 0x80


def mutate_wrong_owner_writer(_: dict[str, object], trace: dict[str, object]) -> None:
    entries = trace["entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0]["owner"] = "RENDERER_YELLOW"
    entries[0]["phase"] = "YELLOW_ACTIVE"


def mutate_stale_generation_writer(
    _: dict[str, object], trace: dict[str, object]
) -> None:
    entries = trace["entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0]["generation"] = 6


def mutate_write_after_cancellation(
    _: dict[str, object], trace: dict[str, object]
) -> None:
    entries = trace["entries"]
    assert isinstance(entries, list) and isinstance(entries[2], dict)
    entries[2]["wrote"] = True


def _boundary_only(_: dict[str, object], __: dict[str, object]) -> None:
    """Boundary mutations are applied to their third, machine-state carrier."""


MUTATIONS: dict[str, Mutation] = {
    "wrong-attribute-byte": mutate_wrong_attribute_byte,
    "lost-clipped-coordinate": mutate_lost_clipped_coordinate,
    "partial-paired-commit": mutate_partial_paired_commit,
    "saved-byte-reconstruction": mutate_saved_byte_reconstruction,
    "missing-oam-fallback": mutate_missing_oam_fallback,
    "oam-control-bit-loss": mutate_oam_control_bit_loss,
    "wrong-owner-writer": mutate_wrong_owner_writer,
    "stale-generation-writer": mutate_stale_generation_writer,
    "write-after-cancellation": mutate_write_after_cancellation,
    "bank-leak": _boundary_only,
    "stack-pointer-leak": _boundary_only,
    "stack-window-leak": _boundary_only,
    "ime-leak": _boundary_only,
    "interrupt-enable-leak": _boundary_only,
    "interrupt-flags-leak": _boundary_only,
}

_BOUNDARY_MUTATIONS = {
    "bank-leak": ("banks", "wram"),
    "stack-pointer-leak": ("stack_pointer", None),
    "stack-window-leak": ("stack_window", None),
    "ime-leak": ("interrupt_master_enabled", None),
    "interrupt-enable-leak": ("interrupt_enable", None),
    "interrupt-flags-leak": ("interrupt_flags", None),
}


@dataclass(frozen=True, slots=True)
class FilesystemObservationProvider:
    root: Path
    mutation: str | None = None

    def __post_init__(self) -> None:
        if self.mutation is not None and self.mutation not in MUTATION_CASES:
            raise RendererConformanceError(
                f"unknown renderer mutation {self.mutation!r}"
            )

    def snapshot(self, case: ConformanceCase) -> SemanticSnapshot:
        snapshot, trace = self._raw(case)
        self._mutate(case, snapshot, trace)
        if self._targets(case) and self.mutation == "missing-oam-fallback":
            clean = SemanticSnapshot.from_dict(self.raw_snapshot(case, mutate=False))
            return _unsafe_snapshot_mutation(clean, self.mutation)
        try:
            return SemanticSnapshot.from_dict(snapshot)
        except Exception as exc:
            if self.mutation in {
                "lost-clipped-coordinate",
                "saved-byte-reconstruction",
                "oam-control-bit-loss",
            }:
                clean = SemanticSnapshot.from_dict(
                    self.raw_snapshot(case, mutate=False)
                )
                return _unsafe_snapshot_mutation(clean, self.mutation)
            raise RendererConformanceError(
                f"{case.case_id}: malformed semantic snapshot: {exc}"
            ) from exc

    def trace(self, case: ConformanceCase) -> WriterTrace:
        snapshot, trace = self._raw(case)
        self._mutate(case, snapshot, trace)
        if self._targets(case) and self.mutation == "write-after-cancellation":
            clean = WriterTrace.from_dict(self.raw_trace(case, mutate=False))
            entries = list(clean.entries)
            original = entries[2]
            altered = WriterTraceEntry.__new__(WriterTraceEntry)
            for field in fields(WriterTraceEntry):
                object.__setattr__(
                    altered,
                    field.name,
                    True if field.name == "wrote" else getattr(original, field.name),
                )
            entries[2] = altered
            result = WriterTrace.__new__(WriterTrace)
            object.__setattr__(result, "capacity", clean.capacity)
            object.__setattr__(result, "entries", tuple(entries))
            object.__setattr__(
                result, "permitted_writer_ids", clean.permitted_writer_ids
            )
            object.__setattr__(
                result, "resource_identities", clean.resource_identities
            )
            object.__setattr__(result, "schema", clean.schema)
            return result
        try:
            return WriterTrace.from_dict(trace)
        except Exception as exc:
            raise RendererConformanceError(
                f"{case.case_id}: malformed writer trace: {exc}"
            ) from exc

    def boundary(self, case: ConformanceCase) -> BankTortureResult | None:
        raw = self.raw_boundary(case, mutate=False)
        if raw is None:
            return None
        try:
            result = BankTortureResult.from_dict(raw, path="boundary")
        except Exception as exc:
            raise RendererConformanceError(
                f"{case.case_id}: malformed boundary result: {exc}"
            ) from exc
        if self._targets(case) and self.mutation in _BOUNDARY_MUTATIONS:
            return _mutate_boundary_result(result, self.mutation)
        return result

    def raw_snapshot(
        self, case: ConformanceCase, *, mutate: bool = True
    ) -> dict[str, object]:
        snapshot, trace = self._raw(case)
        if mutate:
            self._mutate(case, snapshot, trace)
        return snapshot

    def raw_trace(
        self, case: ConformanceCase, *, mutate: bool = True
    ) -> dict[str, object]:
        snapshot, trace = self._raw(case)
        if mutate:
            self._mutate(case, snapshot, trace)
        return trace

    def raw_boundary(
        self, case: ConformanceCase, *, mutate: bool = True
    ) -> dict[str, object] | None:
        if case.observation_boundary is None:
            return None
        raw = self._read(case.observation_boundary)
        if mutate and self._targets(case) and self.mutation in _BOUNDARY_MUTATIONS:
            after = raw["after"]
            assert isinstance(after, dict)
            name, child = _BOUNDARY_MUTATIONS[self.mutation]
            if child is not None:
                nested = after[name]
                assert isinstance(nested, dict)
                nested[child] = (int(nested[child]) + 1) % 8
            elif name == "stack_window":
                payload = bytearray.fromhex(str(after[name]))
                payload[0] ^= 1
                after[name] = payload.hex()
            elif name == "interrupt_master_enabled":
                after[name] = not bool(after[name])
            else:
                after[name] = int(after[name]) ^ 1
            raw["machine_state_restored"] = False
        return raw

    def _raw(
        self, case: ConformanceCase
    ) -> tuple[dict[str, object], dict[str, object]]:
        return self._read(case.observation_snapshot), self._read(case.observation_trace)

    def _read(self, relative: str) -> dict[str, object]:
        parsed = PurePosixPath(relative)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or parsed.as_posix() != relative
        ):
            raise RendererConformanceError(
                f"observation path escapes fixture root: {relative}"
            )
        base = self.root.resolve()
        path = (base / Path(*parsed.parts)).resolve()
        if path.parent != base and base not in path.parents:
            raise RendererConformanceError(
                f"observation path escapes fixture root: {relative}"
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RendererConformanceError(
                f"{relative}: invalid observation JSON: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise RendererConformanceError(f"{relative}: expected a JSON object")
        return deepcopy(raw)

    def _targets(self, case: ConformanceCase) -> bool:
        return (
            self.mutation is not None and MUTATION_CASES[self.mutation] == case.case_id
        )

    def _mutate(
        self,
        case: ConformanceCase,
        snapshot: dict[str, object],
        trace: dict[str, object],
    ) -> None:
        if self._targets(case) and self.mutation in MUTATIONS:
            MUTATIONS[self.mutation](snapshot, trace)


def _unsafe_snapshot_mutation(
    snapshot: SemanticSnapshot, mutation: str | None
) -> SemanticSnapshot:
    if mutation == "lost-clipped-coordinate":
        assert snapshot.overlay_request is not None
        return replace(
            snapshot,
            overlay_request=replace(
                snapshot.overlay_request,
                clipped_mappings=snapshot.overlay_request.clipped_mappings[1:],
            ),
        )
    if mutation == "saved-byte-reconstruction":
        provenance = dict(snapshot.reconstruction.item_provenance)
        provenance["tilemaps_and_attributes"] = ReconstructionProvenance.SAVED_VRAM
        return replace(
            snapshot,
            reconstruction=replace(
                snapshot.reconstruction,
                item_provenance=tuple(sorted(provenance.items())),
            ),
        )
    if mutation == "oam-control-bit-loss":
        return replace(
            snapshot,
            oam_fallback=replace(
                snapshot.oam_fallback,
                after_attributes=snapshot.oam_fallback.after_attributes ^ 0x80,
            ),
        )
    if mutation == "missing-oam-fallback":
        return replace(
            snapshot,
            oam_fallback=replace(snapshot.oam_fallback, occurred=False),
        )
    raise AssertionError(mutation)


def _mutate_boundary_result(
    result: BankTortureResult, mutation: str | None
) -> BankTortureResult:
    after: BoundarySnapshot
    if mutation == "bank-leak":
        after = replace(
            result.after,
            banks=replace(result.after.banks, wram=(result.after.banks.wram + 1) % 8),
        )
    elif mutation == "stack-pointer-leak":
        after = replace(result.after, stack_pointer=result.after.stack_pointer ^ 1)
    elif mutation == "stack-window-leak":
        payload = bytearray(result.after.stack_window)
        payload[0] ^= 1
        after = replace(result.after, stack_window=bytes(payload))
    elif mutation == "ime-leak":
        after = replace(
            result.after,
            interrupt_master_enabled=not result.after.interrupt_master_enabled,
        )
    elif mutation == "interrupt-enable-leak":
        after = replace(
            result.after, interrupt_enable=result.after.interrupt_enable ^ 1
        )
    elif mutation == "interrupt-flags-leak":
        after = replace(result.after, interrupt_flags=result.after.interrupt_flags ^ 1)
    else:
        raise AssertionError(mutation)
    return replace(result, after=after, machine_state_restored=False)
