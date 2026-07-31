"""Synthetic bank-boundary coverage and self-mutation tests."""

from copy import deepcopy

import pytest

from tools.rom_tests.full_color.bank_torture import (
    BANK_TORTURE_SCHEMA,
    BankTortureError,
    BankTortureEvent,
    BankTortureMutation,
    BankTortureResult,
    VALID_WRAM_ENTRY_BANKS,
    bank_torture_report,
    canonical_cases,
    report_json,
    run_case,
)

SYNTHETIC_ROM = bytes(64 * 0x4000)


def test_canonical_report_is_deterministic_and_explicitly_synthetic() -> None:
    first = report_json(SYNTHETIC_ROM)
    second = report_json(SYNTHETIC_ROM)
    assert first == second
    report = bank_torture_report(SYNTHETIC_ROM)
    assert report["schema"] == BANK_TORTURE_SCHEMA
    assert report["fixture_kind"] == "SYNTHETIC_GATE0"
    assert report["coverage"]["wram_entry_banks"] == list(VALID_WRAM_ENTRY_BANKS)
    assert report["coverage"]["vram_entry_banks"] == [1]
    assert len(report["coverage"]["non_default_rom_banks"]) >= 8
    assert report["checks"] == ["CHK-BANK-01"]
    assert report["rom"]["bank_count"] == 64


def test_entry_rom_banks_must_exist_in_the_baseline_artifact() -> None:
    with pytest.raises(BankTortureError, match="exceed the baseline ROM"):
        bank_torture_report(bytes(47 * 0x4000))


def test_far_call_interrupt_covers_every_valid_wram_entry_bank() -> None:
    cases = [
        case
        for case in canonical_cases()
        if case.event is BankTortureEvent.FAR_CALL_INTERRUPT
    ]
    assert tuple(case.entry_banks.wram for case in cases) == VALID_WRAM_ENTRY_BANKS
    for case in cases:
        result = run_case(case)
        assert result.interrupt_observed
        assert result.before.banks == result.after.banks
        assert result.before.stack_pointer == result.after.stack_pointer
        assert result.before.stack_window == result.after.stack_window
        assert (
            result.before.interrupt_master_enabled
            == result.after.interrupt_master_enabled
        )
        assert result.during.banks != result.before.banks
        assert result.during.stack_pointer < result.before.stack_pointer


@pytest.mark.parametrize(
    ("event", "reason", "owner", "dirty"),
    [
        (
            BankTortureEvent.SOFT_RESET_PENDING,
            "RESET",
            "RENDERER_YELLOW",
            False,
        ),
        (
            BankTortureEvent.OWNERSHIP_SWITCH_PENDING,
            "HANDOFF",
            "RENDERER_FULL_COLOR_OVERWORLD",
            True,
        ),
    ],
)
def test_pending_work_is_cancelled_with_decodable_semantics(
    event: BankTortureEvent,
    reason: str,
    owner: str,
    dirty: bool,
) -> None:
    case = next(item for item in canonical_cases() if item.event is event)
    result = run_case(case)
    decoded = BankTortureResult.from_dict(result.to_dict(), path="result")
    assert decoded == result
    assert decoded.after.job_state.value == "CANCELLED"
    assert decoded.after.cancellation_reason.value == reason
    assert decoded.after.owner.value == owner
    assert decoded.after.generation == decoded.before.generation + 1
    assert decoded.after.dirty_bg is dirty
    assert decoded.after.dirty_obj is dirty
    assert decoded.after.dirty_attributes is dirty


@pytest.mark.parametrize(
    "mutation",
    [
        BankTortureMutation.LEAK_ROM_BANK,
        BankTortureMutation.LEAK_WRAM_BANK,
        BankTortureMutation.LEAK_VRAM_BANK,
        BankTortureMutation.LEAK_STACK_POINTER,
        BankTortureMutation.CORRUPT_STACK,
        BankTortureMutation.LEAK_INTERRUPT_MASTER_ENABLE,
        BankTortureMutation.LEAK_INTERRUPT_ENABLE,
        BankTortureMutation.LEAK_INTERRUPT_FLAGS,
    ],
)
def test_every_machine_state_leak_mutation_fails_specifically(
    mutation: BankTortureMutation,
) -> None:
    case = canonical_cases()[0]
    with pytest.raises(
        BankTortureError, match="bank, stack, or interrupt state leaked"
    ):
        run_case(case, mutation=mutation)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (BankTortureMutation.CHANGE_DURING_OWNER, "changed semantic state"),
        (BankTortureMutation.WRONG_AFTER_OWNER, "owner/generation/job outcome"),
        (BankTortureMutation.WRONG_AFTER_GENERATION, "owner/generation/job outcome"),
        (BankTortureMutation.WRONG_AFTER_JOB_STATE, "owner/generation/job outcome"),
        (BankTortureMutation.WRONG_AFTER_DIRTY_STATE, "dirty-state outcome"),
        (BankTortureMutation.LOSE_INTERRUPT_OBSERVATION, "did not observe"),
    ],
)
def test_semantic_outcome_mutations_fail_specifically(
    mutation: BankTortureMutation,
    message: str,
) -> None:
    with pytest.raises(BankTortureError, match=message):
        run_case(canonical_cases()[0], mutation=mutation)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (BankTortureMutation.DROP_PENDING_CANCELLATION, "was not cancelled"),
        (
            BankTortureMutation.CLAIM_INTERRUPT_IN_NONINTERRUPT,
            "claimed interrupt evidence",
        ),
    ],
)
def test_pending_case_semantic_mutations_fail_specifically(
    mutation: BankTortureMutation,
    message: str,
) -> None:
    case = next(
        item
        for item in canonical_cases()
        if item.event is BankTortureEvent.SOFT_RESET_PENDING
    )
    with pytest.raises(BankTortureError, match=message):
        run_case(case, mutation=mutation)


def test_malformed_result_schema_fails_closed() -> None:
    raw = deepcopy(run_case(canonical_cases()[0]).to_dict())
    raw["after"]["banks"]["wram"] = 8
    with pytest.raises(BankTortureError, match="banks.wram"):
        BankTortureResult.from_dict(raw, path="result")

    raw = deepcopy(run_case(canonical_cases()[0]).to_dict())
    raw["after"]["unknown"] = True
    with pytest.raises(BankTortureError, match="unknown fields"):
        BankTortureResult.from_dict(raw, path="result")

    raw = deepcopy(run_case(canonical_cases()[0]).to_dict())
    raw["during"]["owner"] = "RENDERER_FULL_COLOR_OVERWORLD"
    with pytest.raises(BankTortureError, match="changed semantic state"):
        BankTortureResult.from_dict(raw, path="result")

    raw = deepcopy(run_case(canonical_cases()[0]).to_dict())
    raw["during"]["banks"]["rom"] = raw["before"]["banks"]["rom"]
    with pytest.raises(BankTortureError, match="boundary was not exercised"):
        BankTortureResult.from_dict(raw, path="result")

    pending = next(
        item
        for item in canonical_cases()
        if item.event is BankTortureEvent.SOFT_RESET_PENDING
    )
    raw = deepcopy(run_case(pending).to_dict())
    raw["during"] = deepcopy(raw["before"])
    with pytest.raises(BankTortureError, match="boundary was not exercised"):
        BankTortureResult.from_dict(raw, path="result")
