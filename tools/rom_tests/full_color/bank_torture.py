"""Deterministic synthetic bank-boundary fixtures for Gate 0.

These cases validate the future bank/owner/generation evidence contract. They
do not claim that renderer runtime paths exist before their activation phase.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from ._validation import (
    require_bool,
    require_enum,
    require_hex,
    require_int,
    require_object,
    require_str,
)
from .enums import CancellationReason, JobState, Owner, Phase
from .errors import BankTortureError
from .snapshots import BankState

BANK_TORTURE_SCHEMA = "full-color-bank-torture-v1"
FIXTURE_KIND = "SYNTHETIC_GATE0"
CHECK_ID = "CHK-BANK-01"
STACK_WINDOW_BYTES = 32
VALID_WRAM_ENTRY_BANKS = tuple(range(8))
_STACK_WINDOW = bytes(range(0x40, 0x40 + STACK_WINDOW_BYTES))
_ROM_BANK_BYTES = 0x4000


class BankTortureEvent(StrEnum):
    FAR_CALL_INTERRUPT = "FAR_CALL_INTERRUPT"
    SOFT_RESET_PENDING = "SOFT_RESET_PENDING"
    OWNERSHIP_SWITCH_PENDING = "OWNERSHIP_SWITCH_PENDING"


class BankTortureMutation(StrEnum):
    LEAK_ROM_BANK = "LEAK_ROM_BANK"
    LEAK_WRAM_BANK = "LEAK_WRAM_BANK"
    LEAK_VRAM_BANK = "LEAK_VRAM_BANK"
    LEAK_STACK_POINTER = "LEAK_STACK_POINTER"
    CORRUPT_STACK = "CORRUPT_STACK"
    LEAK_INTERRUPT_MASTER_ENABLE = "LEAK_INTERRUPT_MASTER_ENABLE"
    LEAK_INTERRUPT_ENABLE = "LEAK_INTERRUPT_ENABLE"
    LEAK_INTERRUPT_FLAGS = "LEAK_INTERRUPT_FLAGS"
    CHANGE_DURING_OWNER = "CHANGE_DURING_OWNER"
    WRONG_AFTER_OWNER = "WRONG_AFTER_OWNER"
    WRONG_AFTER_GENERATION = "WRONG_AFTER_GENERATION"
    WRONG_AFTER_JOB_STATE = "WRONG_AFTER_JOB_STATE"
    WRONG_AFTER_DIRTY_STATE = "WRONG_AFTER_DIRTY_STATE"
    LOSE_INTERRUPT_OBSERVATION = "LOSE_INTERRUPT_OBSERVATION"
    DROP_PENDING_CANCELLATION = "DROP_PENDING_CANCELLATION"
    CLAIM_INTERRUPT_IN_NONINTERRUPT = "CLAIM_INTERRUPT_IN_NONINTERRUPT"


def _bank_state_from_dict(raw: object, *, path: str) -> BankState:
    obj = require_object(
        raw,
        path=path,
        required={"rom", "wram", "vram"},
        error=BankTortureError,
    )
    return BankState(
        rom=require_int(
            obj["rom"], path=f"{path}.rom", maximum=0x1FF, error=BankTortureError
        ),
        wram=require_int(
            obj["wram"], path=f"{path}.wram", maximum=7, error=BankTortureError
        ),
        vram=require_int(
            obj["vram"], path=f"{path}.vram", maximum=1, error=BankTortureError
        ),
    )


@dataclass(frozen=True, slots=True)
class BoundarySnapshot:
    banks: BankState
    stack_pointer: int
    stack_window: bytes
    interrupt_master_enabled: bool
    interrupt_enable: int
    interrupt_flags: int
    owner: Owner
    phase: Phase
    generation: int
    dirty_bg: bool
    dirty_obj: bool
    dirty_attributes: bool
    job_state: JobState | None
    cancellation_reason: CancellationReason | None

    def __post_init__(self) -> None:
        if not 0 <= self.stack_pointer <= 0xFFFF:
            raise BankTortureError("boundary.stack_pointer: expected integer 0..65535")
        if len(self.stack_window) != STACK_WINDOW_BYTES:
            raise BankTortureError(
                f"boundary.stack_window: expected exactly {STACK_WINDOW_BYTES} bytes"
            )
        if not 0 <= self.interrupt_enable <= 0xFF:
            raise BankTortureError("boundary.interrupt_enable: expected integer 0..255")
        if not 0 <= self.interrupt_flags <= 0xFF:
            raise BankTortureError("boundary.interrupt_flags: expected integer 0..255")
        if self.generation < 0:
            raise BankTortureError(
                "boundary.generation: expected a non-negative integer"
            )
        if self.job_state is JobState.CANCELLED:
            if self.cancellation_reason is None:
                raise BankTortureError(
                    "boundary.cancellation_reason: cancelled job requires a reason"
                )
        elif self.cancellation_reason is not None:
            raise BankTortureError(
                "boundary.cancellation_reason: only cancelled jobs carry a reason"
            )

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> BoundarySnapshot:
        obj = require_object(
            raw,
            path=path,
            required={
                "banks",
                "stack_pointer",
                "stack_window",
                "interrupt_master_enabled",
                "interrupt_enable",
                "interrupt_flags",
                "owner",
                "phase",
                "generation",
                "dirty",
                "job_state",
                "cancellation_reason",
            },
            error=BankTortureError,
        )
        dirty = require_object(
            obj["dirty"],
            path=f"{path}.dirty",
            required={"bg", "obj", "attributes"},
            error=BankTortureError,
        )
        job_raw = obj["job_state"]
        reason_raw = obj["cancellation_reason"]
        return cls(
            banks=_bank_state_from_dict(obj["banks"], path=f"{path}.banks"),
            stack_pointer=require_int(
                obj["stack_pointer"],
                path=f"{path}.stack_pointer",
                maximum=0xFFFF,
                error=BankTortureError,
            ),
            stack_window=require_hex(
                obj["stack_window"],
                path=f"{path}.stack_window",
                length=STACK_WINDOW_BYTES,
                error=BankTortureError,
            ),
            interrupt_master_enabled=require_bool(
                obj["interrupt_master_enabled"],
                path=f"{path}.interrupt_master_enabled",
                error=BankTortureError,
            ),
            interrupt_enable=require_int(
                obj["interrupt_enable"],
                path=f"{path}.interrupt_enable",
                maximum=0xFF,
                error=BankTortureError,
            ),
            interrupt_flags=require_int(
                obj["interrupt_flags"],
                path=f"{path}.interrupt_flags",
                maximum=0xFF,
                error=BankTortureError,
            ),
            owner=require_enum(
                Owner, obj["owner"], path=f"{path}.owner", error=BankTortureError
            ),
            phase=require_enum(
                Phase, obj["phase"], path=f"{path}.phase", error=BankTortureError
            ),
            generation=require_int(
                obj["generation"],
                path=f"{path}.generation",
                error=BankTortureError,
            ),
            dirty_bg=require_bool(
                dirty["bg"], path=f"{path}.dirty.bg", error=BankTortureError
            ),
            dirty_obj=require_bool(
                dirty["obj"], path=f"{path}.dirty.obj", error=BankTortureError
            ),
            dirty_attributes=require_bool(
                dirty["attributes"],
                path=f"{path}.dirty.attributes",
                error=BankTortureError,
            ),
            job_state=(
                None
                if job_raw is None
                else require_enum(
                    JobState,
                    job_raw,
                    path=f"{path}.job_state",
                    error=BankTortureError,
                )
            ),
            cancellation_reason=(
                None
                if reason_raw is None
                else require_enum(
                    CancellationReason,
                    reason_raw,
                    path=f"{path}.cancellation_reason",
                    error=BankTortureError,
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "banks": self.banks.to_dict(),
            "stack_pointer": self.stack_pointer,
            "stack_window": self.stack_window.hex(),
            "interrupt_master_enabled": self.interrupt_master_enabled,
            "interrupt_enable": self.interrupt_enable,
            "interrupt_flags": self.interrupt_flags,
            "owner": self.owner.value,
            "phase": self.phase.value,
            "generation": self.generation,
            "dirty": {
                "bg": self.dirty_bg,
                "obj": self.dirty_obj,
                "attributes": self.dirty_attributes,
            },
            "job_state": None if self.job_state is None else self.job_state.value,
            "cancellation_reason": (
                None
                if self.cancellation_reason is None
                else self.cancellation_reason.value
            ),
        }


@dataclass(frozen=True, slots=True)
class BankTortureCase:
    case_id: str
    event: BankTortureEvent
    entry_banks: BankState
    pending_work: bool

    def __post_init__(self) -> None:
        if not self.case_id:
            raise BankTortureError("case.case_id: expected a non-empty string")
        if not 0 <= self.entry_banks.rom <= 0x1FF:
            raise BankTortureError("case.entry_banks.rom: expected integer 0..511")
        if not 0 <= self.entry_banks.wram <= 7:
            raise BankTortureError("case.entry_banks.wram: expected integer 0..7")
        if not 0 <= self.entry_banks.vram <= 1:
            raise BankTortureError("case.entry_banks.vram: expected integer 0..1")
        expects_pending = self.event in {
            BankTortureEvent.SOFT_RESET_PENDING,
            BankTortureEvent.OWNERSHIP_SWITCH_PENDING,
        }
        if self.pending_work is not expects_pending:
            raise BankTortureError(
                f"{self.case_id}: pending_work does not match {self.event.value}"
            )

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> BankTortureCase:
        obj = require_object(
            raw,
            path=path,
            required={"case_id", "event", "entry_banks", "pending_work"},
            error=BankTortureError,
        )
        return cls(
            case_id=require_str(
                obj["case_id"], path=f"{path}.case_id", error=BankTortureError
            ),
            event=require_enum(
                BankTortureEvent,
                obj["event"],
                path=f"{path}.event",
                error=BankTortureError,
            ),
            entry_banks=_bank_state_from_dict(
                obj["entry_banks"], path=f"{path}.entry_banks"
            ),
            pending_work=require_bool(
                obj["pending_work"],
                path=f"{path}.pending_work",
                error=BankTortureError,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "event": self.event.value,
            "entry_banks": self.entry_banks.to_dict(),
            "pending_work": self.pending_work,
        }


@dataclass(frozen=True, slots=True)
class BankTortureResult:
    case: BankTortureCase
    before: BoundarySnapshot
    during: BoundarySnapshot
    after: BoundarySnapshot
    interrupt_observed: bool
    machine_state_restored: bool

    @classmethod
    def from_dict(cls, raw: object, *, path: str) -> BankTortureResult:
        obj = require_object(
            raw,
            path=path,
            required={
                "case",
                "before",
                "during",
                "after",
                "interrupt_observed",
                "machine_state_restored",
            },
            error=BankTortureError,
        )
        result = cls(
            case=BankTortureCase.from_dict(obj["case"], path=f"{path}.case"),
            before=BoundarySnapshot.from_dict(obj["before"], path=f"{path}.before"),
            during=BoundarySnapshot.from_dict(obj["during"], path=f"{path}.during"),
            after=BoundarySnapshot.from_dict(obj["after"], path=f"{path}.after"),
            interrupt_observed=require_bool(
                obj["interrupt_observed"],
                path=f"{path}.interrupt_observed",
                error=BankTortureError,
            ),
            machine_state_restored=require_bool(
                obj["machine_state_restored"],
                path=f"{path}.machine_state_restored",
                error=BankTortureError,
            ),
        )
        _assert_result(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "before": self.before.to_dict(),
            "during": self.during.to_dict(),
            "after": self.after.to_dict(),
            "interrupt_observed": self.interrupt_observed,
            "machine_state_restored": self.machine_state_restored,
        }


def canonical_cases() -> tuple[BankTortureCase, ...]:
    cases = [
        BankTortureCase(
            case_id=f"BANK-FAR-INT-WRAM-{wram}",
            event=BankTortureEvent.FAR_CALL_INTERRUPT,
            entry_banks=BankState(rom=0x21 + wram, wram=wram, vram=1),
            pending_work=False,
        )
        for wram in VALID_WRAM_ENTRY_BANKS
    ]
    cases.extend(
        (
            BankTortureCase(
                case_id="BANK-SOFT-RESET-PENDING",
                event=BankTortureEvent.SOFT_RESET_PENDING,
                entry_banks=BankState(rom=0x2D, wram=3, vram=1),
                pending_work=True,
            ),
            BankTortureCase(
                case_id="BANK-OWNER-SWITCH-PENDING",
                event=BankTortureEvent.OWNERSHIP_SWITCH_PENDING,
                entry_banks=BankState(rom=0x2E, wram=7, vram=1),
                pending_work=True,
            ),
        )
    )
    return tuple(cases)


def _before(case: BankTortureCase) -> BoundarySnapshot:
    return BoundarySnapshot(
        banks=case.entry_banks,
        stack_pointer=0xDFF0,
        stack_window=_STACK_WINDOW,
        interrupt_master_enabled=True,
        interrupt_enable=0x05,
        interrupt_flags=0x01,
        owner=Owner.RENDERER_YELLOW,
        phase=Phase.YELLOW_ACTIVE,
        generation=17,
        dirty_bg=False,
        dirty_obj=False,
        dirty_attributes=False,
        job_state=JobState.PENDING if case.pending_work else None,
        cancellation_reason=None,
    )


def _execute(case: BankTortureCase) -> BankTortureResult:
    before = _before(case)
    during = replace(
        before,
        banks=BankState(
            rom=case.entry_banks.rom + 0x10,
            wram=(case.entry_banks.wram + 3) & 0x07,
            vram=0,
        ),
        stack_pointer=before.stack_pointer - 2,
        interrupt_master_enabled=False,
        interrupt_flags=before.interrupt_flags | 0x04,
    )
    after = before
    interrupt_observed = case.event is BankTortureEvent.FAR_CALL_INTERRUPT
    if case.event is BankTortureEvent.SOFT_RESET_PENDING:
        after = replace(
            before,
            generation=before.generation + 1,
            job_state=JobState.CANCELLED,
            cancellation_reason=CancellationReason.RESET,
        )
    elif case.event is BankTortureEvent.OWNERSHIP_SWITCH_PENDING:
        after = replace(
            before,
            owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
            phase=Phase.OVERWORLD_RECONSTRUCTING,
            generation=before.generation + 1,
            dirty_bg=True,
            dirty_obj=True,
            dirty_attributes=True,
            job_state=JobState.CANCELLED,
            cancellation_reason=CancellationReason.HANDOFF,
        )
    result = BankTortureResult(
        case=case,
        before=before,
        during=during,
        after=after,
        interrupt_observed=interrupt_observed,
        machine_state_restored=True,
    )
    _assert_result(result)
    return result


def _machine_boundary(snapshot: BoundarySnapshot) -> tuple[object, ...]:
    return (
        snapshot.banks,
        snapshot.stack_pointer,
        snapshot.stack_window,
        snapshot.interrupt_master_enabled,
        snapshot.interrupt_enable,
        snapshot.interrupt_flags,
    )


def _assert_result(result: BankTortureResult) -> None:
    case = result.case
    if result.before.banks != case.entry_banks:
        raise BankTortureError(f"{case.case_id}: before banks differ from case entry")
    expected_before_job = JobState.PENDING if case.pending_work else None
    if (
        result.before.owner is not Owner.RENDERER_YELLOW
        or result.before.phase is not Phase.YELLOW_ACTIVE
        or result.before.job_state is not expected_before_job
        or result.before.cancellation_reason is not None
        or result.before.dirty_bg
        or result.before.dirty_obj
        or result.before.dirty_attributes
    ):
        raise BankTortureError(f"{case.case_id}: invalid initial semantic state")
    before_semantics = (
        result.before.owner,
        result.before.phase,
        result.before.generation,
        result.before.dirty_bg,
        result.before.dirty_obj,
        result.before.dirty_attributes,
        result.before.job_state,
        result.before.cancellation_reason,
    )
    during_semantics = (
        result.during.owner,
        result.during.phase,
        result.during.generation,
        result.during.dirty_bg,
        result.during.dirty_obj,
        result.during.dirty_attributes,
        result.during.job_state,
        result.during.cancellation_reason,
    )
    if during_semantics != before_semantics:
        raise BankTortureError(
            f"{case.case_id}: machine boundary changed semantic state"
        )
    if (
        result.during.banks.rom == result.before.banks.rom
        or result.during.banks.wram == result.before.banks.wram
        or result.during.banks.vram == result.before.banks.vram
        or result.during.stack_pointer != result.before.stack_pointer - 2
        or result.during.interrupt_master_enabled
    ):
        raise BankTortureError(
            f"{case.case_id}: synthetic bank boundary was not exercised"
        )
    restored = _machine_boundary(result.before) == _machine_boundary(result.after)
    if not result.machine_state_restored or not restored:
        raise BankTortureError(
            f"{case.case_id}: bank, stack, or interrupt state leaked across boundary"
        )
    if (
        case.event is BankTortureEvent.FAR_CALL_INTERRUPT
        and not result.interrupt_observed
    ):
        raise BankTortureError(f"{case.case_id}: far call did not observe an interrupt")
    if (
        case.event is not BankTortureEvent.FAR_CALL_INTERRUPT
        and result.interrupt_observed
    ):
        raise BankTortureError(
            f"{case.case_id}: non-interrupt case claimed interrupt evidence"
        )
    expected = {
        BankTortureEvent.FAR_CALL_INTERRUPT: (
            result.before.owner,
            result.before.phase,
            result.before.generation,
            result.before.job_state,
            None,
        ),
        BankTortureEvent.SOFT_RESET_PENDING: (
            Owner.RENDERER_YELLOW,
            Phase.YELLOW_ACTIVE,
            result.before.generation + 1,
            JobState.CANCELLED,
            CancellationReason.RESET,
        ),
        BankTortureEvent.OWNERSHIP_SWITCH_PENDING: (
            Owner.RENDERER_FULL_COLOR_OVERWORLD,
            Phase.OVERWORLD_RECONSTRUCTING,
            result.before.generation + 1,
            JobState.CANCELLED,
            CancellationReason.HANDOFF,
        ),
    }[case.event]
    if case.pending_work and result.after.job_state is not JobState.CANCELLED:
        raise BankTortureError(f"{case.case_id}: pending work was not cancelled")
    actual = (
        result.after.owner,
        result.after.phase,
        result.after.generation,
        result.after.job_state,
        result.after.cancellation_reason,
    )
    if actual != expected:
        raise BankTortureError(f"{case.case_id}: owner/generation/job outcome mismatch")
    expected_dirty = case.event is BankTortureEvent.OWNERSHIP_SWITCH_PENDING
    actual_dirty = (
        result.after.dirty_bg,
        result.after.dirty_obj,
        result.after.dirty_attributes,
    )
    if actual_dirty != (expected_dirty, expected_dirty, expected_dirty):
        raise BankTortureError(f"{case.case_id}: dirty-state outcome mismatch")


def run_case(
    case: BankTortureCase,
    *,
    mutation: BankTortureMutation | None = None,
) -> BankTortureResult:
    result = _execute(case)
    if mutation is None:
        return result
    after = result.after
    if mutation is BankTortureMutation.LEAK_ROM_BANK:
        after = replace(after, banks=replace(after.banks, rom=0x1FE))
    elif mutation is BankTortureMutation.LEAK_WRAM_BANK:
        after = replace(
            after, banks=replace(after.banks, wram=(after.banks.wram + 1) & 7)
        )
    elif mutation is BankTortureMutation.LEAK_VRAM_BANK:
        after = replace(after, banks=replace(after.banks, vram=0))
    elif mutation is BankTortureMutation.LEAK_STACK_POINTER:
        after = replace(after, stack_pointer=after.stack_pointer - 2)
    elif mutation is BankTortureMutation.CORRUPT_STACK:
        after = replace(
            after,
            stack_window=bytes([after.stack_window[0] ^ 0xFF]) + after.stack_window[1:],
        )
    elif mutation is BankTortureMutation.LEAK_INTERRUPT_MASTER_ENABLE:
        after = replace(after, interrupt_master_enabled=False)
    elif mutation is BankTortureMutation.LEAK_INTERRUPT_ENABLE:
        after = replace(after, interrupt_enable=after.interrupt_enable ^ 0x01)
    elif mutation is BankTortureMutation.LEAK_INTERRUPT_FLAGS:
        after = replace(after, interrupt_flags=after.interrupt_flags ^ 0x01)
    elif mutation is BankTortureMutation.CHANGE_DURING_OWNER:
        mutated = replace(
            result,
            during=replace(result.during, owner=Owner.RENDERER_FULL_COLOR_OVERWORLD),
        )
        _assert_result(mutated)
        return mutated
    elif mutation is BankTortureMutation.WRONG_AFTER_OWNER:
        after = replace(after, owner=Owner.RENDERER_FULL_COLOR_OVERWORLD)
    elif mutation is BankTortureMutation.WRONG_AFTER_GENERATION:
        after = replace(after, generation=after.generation + 1)
    elif mutation is BankTortureMutation.WRONG_AFTER_JOB_STATE:
        after = replace(after, job_state=JobState.COMPLETE)
    elif mutation is BankTortureMutation.WRONG_AFTER_DIRTY_STATE:
        after = replace(after, dirty_bg=not after.dirty_bg)
    elif mutation is BankTortureMutation.LOSE_INTERRUPT_OBSERVATION:
        mutated = replace(result, interrupt_observed=False)
        _assert_result(mutated)
        return mutated
    elif mutation is BankTortureMutation.DROP_PENDING_CANCELLATION:
        after = replace(
            after,
            job_state=JobState.PENDING,
            cancellation_reason=None,
        )
    elif mutation is BankTortureMutation.CLAIM_INTERRUPT_IN_NONINTERRUPT:
        mutated = replace(result, interrupt_observed=True)
        _assert_result(mutated)
        return mutated
    mutated = replace(result, after=after)
    _assert_result(mutated)
    return mutated


def bank_torture_report(rom: bytes) -> dict[str, Any]:
    if not rom or len(rom) % _ROM_BANK_BYTES:
        raise BankTortureError("bank torture ROM must contain complete 16 KiB banks")
    rom_bank_count = len(rom) // _ROM_BANK_BYTES
    results = tuple(run_case(case) for case in canonical_cases())
    round_tripped = tuple(
        BankTortureResult.from_dict(result.to_dict(), path=f"results[{index}]")
        for index, result in enumerate(results)
    )
    if round_tripped != results:
        raise BankTortureError("bank torture result schema did not round-trip")
    wram_banks = tuple(sorted({item.case.entry_banks.wram for item in results}))
    events = tuple(sorted({item.case.event.value for item in results}))
    if wram_banks != VALID_WRAM_ENTRY_BANKS:
        raise BankTortureError("bank torture did not cover every WRAM entry bank")
    exercised_rom_banks = {
        bank
        for item in results
        for bank in (
            item.case.entry_banks.rom,
            item.before.banks.rom,
            item.during.banks.rom,
            item.after.banks.rom,
        )
    }
    invalid_rom_banks = sorted(
        bank for bank in exercised_rom_banks if bank >= rom_bank_count
    )
    if invalid_rom_banks:
        raise BankTortureError(
            "bank torture exercised banks exceed the baseline ROM: "
            + ", ".join(str(bank) for bank in invalid_rom_banks)
        )
    return {
        "schema": BANK_TORTURE_SCHEMA,
        "fixture_kind": FIXTURE_KIND,
        "activation": "renderer runtime conformance activates in phases 1-2",
        "checks": [CHECK_ID],
        "rom": {
            "bank_count": rom_bank_count,
            "sha256": hashlib.sha256(rom).hexdigest(),
        },
        "coverage": {
            "case_count": len(results),
            "events": list(events),
            "non_default_rom_banks": sorted(
                {item.case.entry_banks.rom for item in results}
            ),
            "vram_entry_banks": sorted(
                {item.case.entry_banks.vram for item in results}
            ),
            "wram_entry_banks": list(wram_banks),
        },
        "results": [result.to_dict() for result in results],
    }


def report_json(rom: bytes) -> str:
    return (
        json.dumps(
            bank_torture_report(rom),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit deterministic synthetic Gate 0 bank-torture evidence."
    )
    parser.add_argument("--rom", default="pokeyellow_debug.gbc")
    args = parser.parse_args(argv)
    print(report_json(Path(args.rom).read_bytes()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
