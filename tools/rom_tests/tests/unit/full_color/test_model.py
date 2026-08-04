"""Mutation-oriented coverage for request, job, and ownership contracts."""

from dataclasses import replace

import pytest

from tools.rom_tests.full_color.enums import (
    CancellationReason,
    JobState,
    Owner,
    Phase,
    ReconstructionProvenance,
    RequestResult,
)
from tools.rom_tests.full_color.errors import ModelViolation
from tools.rom_tests.full_color.model import (
    ActionKind,
    OPTIONAL_SUPERSEDABLE,
    PHASE1_MAX_GENERATION,
    ModelAction,
    OwnershipModel,
    Phase1ActionKind,
    Phase1OwnershipModel,
    PreVisibleBoundary,
    Request,
    RECONSTRUCTION_ITEMS,
    RECONSTRUCTION_ITEM_PROVENANCE,
    execute_valid_actions,
    generated_phase1_actions,
    generate_actions,
    replay_phase1_actions,
)


def request(
    model: OwnershipModel,
    request_id: str,
    *,
    desired: bytes = b"state",
) -> Request:
    return Request(
        request_id=request_id,
        owner=model.owner,
        generation=model.generation,
        resources=("BG_TILE_IDS", "BG_ATTRIBUTES"),
        commit_unit_id="MU-TEST-PAIR",
        desired_state=desired,
    )


def test_all_request_result_branches_have_exact_work_accounting() -> None:
    model = OwnershipModel(capacity=1)
    accepted = model.admit(request(model, "REQ-ACCEPT"))
    coalesced = model.admit(request(model, "REQ-COALESCE"))
    deferred = model.admit(request(model, "REQ-DEFER", desired=b"required"))
    optional = replace(
        request(model, "REQ-REJECT", desired=b"optional"),
        request_class=OPTIONAL_SUPERSEDABLE,
    )
    rejected = model.admit(optional)
    wrong = model.admit(
        replace(
            request(model, "REQ-WRONG"),
            owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
        )
    )
    stale = model.admit(
        replace(request(model, "REQ-STALE"), generation=model.generation + 1)
    )

    assert [item.result for item in (accepted, coalesced, deferred, rejected, wrong, stale)] == [
        RequestResult.ACCEPTED,
        RequestResult.COALESCED,
        RequestResult.DEFERRED,
        RequestResult.REJECTED_CAPACITY,
        RequestResult.REJECTED_WRONG_OWNER,
        RequestResult.REJECTED_STALE_GENERATION,
    ]
    assert len(model.jobs) == 1
    assert model.jobs[accepted.job_id].request_ids == ["REQ-ACCEPT", "REQ-COALESCE"]
    assert not deferred.created and not deferred.attached and deferred.job_id is None
    assert not rejected.created and not rejected.attached and rejected.job_id is None
    assert not wrong.created and not stale.attached


@pytest.mark.parametrize("reason", list(CancellationReason))
def test_every_stable_cancellation_reason_is_recorded_once(
    reason: CancellationReason,
) -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, f"REQ-{reason.value}"))
    model.cancel_job(admission.job_id, reason)

    job = model.jobs[admission.job_id]
    assert job.state is JobState.CANCELLED
    assert job.cancellation_reason is reason

    with pytest.raises(ModelViolation, match="cannot cancel from CANCELLED"):
        model.cancel_job(job.job_id, reason)


def test_wrong_owner_and_stale_generation_writes_fail_specifically() -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, "REQ-WRITE"))
    model.advance(admission.job_id, JobState.PREPARED)
    assert model.begin_commit(
        admission.job_id, available_cycles=10, worst_case_cycles=10
    )

    with pytest.raises(ModelViolation, match="wrong owner write"):
        model.record_write(
            admission.job_id,
            owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
            generation=model.generation,
        )
    with pytest.raises(ModelViolation, match="stale generation write"):
        model.record_write(
            admission.job_id,
            owner=model.owner,
            generation=model.generation + 1,
        )


def test_cancelled_job_can_never_write() -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, "REQ-CANCEL"))
    model.cancel_job(admission.job_id, CancellationReason.SUPERSEDED)

    with pytest.raises(ModelViolation, match="cancelled work performed a later write"):
        model.jobs[admission.job_id].writes += 1
        model.assert_invariants()


def test_complete_requires_reserved_real_write_and_every_declared_resource() -> None:
    model = OwnershipModel()
    admission = model.admit(
        replace(
            request(model, "REQ-ATOMIC"),
            desired_state={
                "BG_TILE_IDS": b"tiles",
                "BG_ATTRIBUTES": b"attributes",
            },
        )
    )
    job_id = admission.job_id
    model.prepare(job_id, available_cycles=5, required_cycles=5)

    with pytest.raises(ModelViolation, match="worst-case budget reservation"):
        model.advance(job_id, JobState.COMMITTING)

    assert model.begin_commit(job_id, available_cycles=8, worst_case_cycles=8)
    model.record_write(
        job_id,
        owner=model.owner,
        generation=model.generation,
        resource="BG_TILE_IDS",
        value=b"tiles",
    )
    with pytest.raises(ModelViolation, match="BG_ATTRIBUTES"):
        model.advance(job_id, JobState.COMPLETE)

    model.record_write(
        job_id,
        owner=model.owner,
        generation=model.generation,
        resource="BG_ATTRIBUTES",
        value=b"attributes",
    )
    model.advance(job_id, JobState.COMPLETE)
    assert model.jobs[job_id].writes == 2


@pytest.mark.parametrize("boundary", list(PreVisibleBoundary))
def test_every_pre_visible_budget_boundary_leaves_work_prepared(
    boundary: PreVisibleBoundary,
) -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, f"REQ-BUDGET-{boundary.value}"))

    assert not model.prepare(
        admission.job_id,
        available_cycles=9,
        required_cycles=10,
        boundary=boundary,
    )
    assert model.jobs[admission.job_id].state is JobState.PREPARED
    assert not model.begin_commit(
        admission.job_id,
        available_cycles=9,
        worst_case_cycles=10,
    )
    assert model.jobs[admission.job_id].state is JobState.PREPARED
    assert model.jobs[admission.job_id].budget_attempts == [boundary]


def test_visible_committing_unit_cannot_be_interrupted_by_reset_or_handoff() -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, "REQ-NO-INTERRUPT"))
    model.prepare(admission.job_id, available_cycles=10, required_cycles=10)
    model.begin_commit(admission.job_id, available_cycles=10, worst_case_cycles=10)

    with pytest.raises(ModelViolation, match="visible COMMITTING"):
        model.reset()
    with pytest.raises(ModelViolation, match="visible COMMITTING"):
        model.begin_handoff_to_overworld()


def test_poisoned_reconstruction_cannot_activate_until_ledger_and_barrier_complete() -> None:
    model = OwnershipModel()
    model.begin_handoff_to_overworld()
    model.select_overworld_owner()

    assert set(model.reconstruction_poisoned) == set(RECONSTRUCTION_ITEMS)
    with pytest.raises(ModelViolation, match="missing authoritative items"):
        model.finish_reconstruction()
    for item in RECONSTRUCTION_ITEMS:
        model.complete_reconstruction_item(
            item, RECONSTRUCTION_ITEM_PROVENANCE[item]
        )
    with pytest.raises(ModelViolation, match="exactly one complete presentation barrier"):
        model.finish_reconstruction()
    model.present_reconstruction()
    model.finish_reconstruction()
    assert model.phase.value == "OVERWORLD_ACTIVE"


@pytest.mark.parametrize(
    "provenance",
    [
        ReconstructionProvenance.CAPTURED_VRAM,
        ReconstructionProvenance.SAVED_PALETTE_RAM,
        ReconstructionProvenance.CAPTURED_OAM,
        ReconstructionProvenance.SAVED_SCREEN_BUFFER,
    ],
)
def test_reconstruction_completion_rejects_saved_or_captured_provenance(
    provenance: ReconstructionProvenance,
) -> None:
    model = OwnershipModel()
    model.begin_handoff_to_overworld()
    model.select_overworld_owner()

    with pytest.raises(ModelViolation, match="captured/saved display state"):
        model.complete_reconstruction_item("tilemaps_and_attributes", provenance)


def test_yellow_handoff_uses_the_same_closed_reconstruction_contract() -> None:
    model = OwnershipModel()
    model.begin_handoff_to_overworld()
    model.select_overworld_owner()
    for item in RECONSTRUCTION_ITEMS:
        model.complete_reconstruction_item(item, RECONSTRUCTION_ITEM_PROVENANCE[item])
    model.present_reconstruction()
    model.finish_reconstruction()
    generation = model.generation

    model.begin_handoff_to_yellow()
    model.select_yellow_owner()
    assert model.owner is Owner.RENDERER_YELLOW
    assert model.phase is Phase.YELLOW_RECONSTRUCTING
    assert model.generation == generation + 1
    assert not model.admission_open
    for item in RECONSTRUCTION_ITEMS:
        model.complete_reconstruction_item(item, RECONSTRUCTION_ITEM_PROVENANCE[item])
    model.present_reconstruction()
    model.finish_reconstruction()
    assert model.phase is Phase.YELLOW_ACTIVE
    assert model.admission_open


def test_accepted_and_coalesced_work_remains_until_eventual_completion() -> None:
    model = OwnershipModel(capacity=1)
    accepted = model.admit(request(model, "REQ-FIRST"))
    coalesced = model.admit(request(model, "REQ-SECOND"))
    assert coalesced.job_id == accepted.job_id
    job = model.jobs[accepted.job_id]
    assert job.request_ids == ["REQ-FIRST", "REQ-SECOND"]

    model.prepare(job.job_id, available_cycles=1, required_cycles=1)
    model.begin_commit(job.job_id, available_cycles=1, worst_case_cycles=1)
    model.record_write(job.job_id, owner=model.owner, generation=model.generation)
    model.advance(job.job_id, JobState.COMPLETE)
    assert job.state is JobState.COMPLETE


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (JobState.PENDING, JobState.COMMITTING),
        (JobState.PREPARED, JobState.COMPLETE),
        (JobState.COMPLETE, JobState.PENDING),
    ],
)
def test_illegal_job_transitions_fail_at_first_edge(
    start: JobState, target: JobState
) -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, f"REQ-{start.value}"))
    job = model.jobs[admission.job_id]
    job.state = start

    with pytest.raises(
        ModelViolation, match=f"illegal transition {start.value} -> {target.value}"
    ):
        model.advance(job.job_id, target)


def test_handoff_cancels_departing_generation_and_uses_fresh_generation() -> None:
    model = OwnershipModel()
    admission = model.admit(request(model, "REQ-HANDOFF"))
    old_generation = model.generation

    model.begin_handoff_to_overworld()
    model.select_overworld_owner()

    job = model.jobs[admission.job_id]
    assert (job.state, job.cancellation_reason) == (
        JobState.CANCELLED,
        CancellationReason.HANDOFF,
    )
    assert model.generation > old_generation
    assert model.owner is Owner.RENDERER_FULL_COLOR_OVERWORLD


def test_seeded_valid_sequences_are_deterministic_and_cover_vocabulary() -> None:
    actions_a = generate_actions(83421, 500)
    actions_b = generate_actions(83421, 500)

    assert actions_a == actions_b
    expected_actions = {
        ActionKind.MOVEMENT,
        ActionKind.OVERLAY,
        ActionKind.CONNECTION,
        ActionKind.HANDOFF_TO_OVERWORLD,
        ActionKind.FINISH_RECONSTRUCTION,
        ActionKind.HANDOFF_TO_YELLOW,
        ActionKind.RESET,
        ActionKind.PREPARE_PENDING,
        ActionKind.INTERRUPT_BOUNDARY,
    }
    assert {action.kind for action in actions_a} == expected_actions
    assert execute_valid_actions(actions_a) == execute_valid_actions(actions_b)
    executed = execute_valid_actions(actions_a)
    assert {action.kind for action in executed.executed_actions} == expected_actions
    assert len(executed.executed_actions) <= len(actions_a)
    assert Phase.HANDOFF_TO_OVERWORLD in executed.phase_history
    assert Phase.OVERWORLD_RECONSTRUCTING in executed.phase_history


def test_executor_tracks_ordered_handoff_steps_and_excludes_context_noops() -> None:
    actions = (
        ModelAction(ActionKind.FINISH_RECONSTRUCTION, 0),
        ModelAction(ActionKind.HANDOFF_TO_OVERWORLD, 1),
        ModelAction(ActionKind.FINISH_RECONSTRUCTION, 2),
        ModelAction(ActionKind.HANDOFF_TO_YELLOW, 3),
    )

    executed = execute_valid_actions(actions)

    assert executed.executed_actions == list(actions[1:])
    assert executed.executed_steps == [
        "HANDOFF_TO_OVERWORLD:CLOSE_ADMISSION_AND_SETTLE",
        "HANDOFF_TO_OVERWORLD:CANCEL_DEPARTING_WORK",
        "HANDOFF_TO_OVERWORLD:FRESH_GENERATION",
        "HANDOFF_TO_OVERWORLD:SELECT_AND_INITIALIZE_OWNER",
        "HANDOFF_TO_YELLOW:CLOSE_ADMISSION_AND_SETTLE",
        "HANDOFF_TO_YELLOW:CANCEL_DEPARTING_WORK",
        "HANDOFF_TO_YELLOW:FRESH_GENERATION",
        "HANDOFF_TO_YELLOW:SELECT_AND_INITIALIZE_OWNER",
        "HANDOFF_TO_YELLOW:COMPLETE_RECONSTRUCTION_LEDGER",
        "HANDOFF_TO_YELLOW:PRESENTATION_BARRIER",
        "HANDOFF_TO_YELLOW:ACTIVATE_AND_REOPEN_ADMISSION",
    ]


def test_adversarial_sequence_fails_at_first_corrupted_transition() -> None:
    actions = (
        ModelAction(ActionKind.MOVEMENT, 1),
        ModelAction(ActionKind.ILLEGAL_TRANSITION, 2),
        ModelAction(ActionKind.RESET, 3),
    )

    with pytest.raises(ModelViolation, match="action 1: adversarial action ILLEGAL_TRANSITION"):
        execute_valid_actions(actions)


def test_phase1_hard_boot_owns_yellow_generation_one_with_empty_slot() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()

    assert model.snapshot() == replace(
        model.snapshot(),
        owner=Owner.RENDERER_YELLOW,
        phase=Phase.YELLOW_ACTIVE,
        generation=1,
        admission_open=True,
        job_state=None,
        job_generation=None,
        cancellation_reason=None,
        generation_exhausted=False,
    )


def test_phase1_single_diagnostic_slot_has_explicit_admission_results() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()

    assert model.admit_job(owner=Owner.RENDERER_FULL_COLOR_OVERWORLD) is RequestResult.REJECTED_WRONG_OWNER
    assert model.admit_job(generation=0) is RequestResult.REJECTED_STALE_GENERATION
    assert model.admit_job() is RequestResult.ACCEPTED
    assert model.admit_job() is RequestResult.REJECTED_CAPACITY
    assert model.job_state is JobState.PENDING
    assert model.job_generation == model.generation


def test_phase1_reset_invalidates_work_before_reopening_yellow() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    model.admit_job()
    model.prepare_job()
    previous_generation = model.generation

    model.reset()

    assert model.owner is Owner.RENDERER_YELLOW
    assert model.phase is Phase.YELLOW_ACTIVE
    assert model.generation == previous_generation + 1
    assert model.admission_open
    assert model.job_state is None
    assert model.job_generation is None


def test_phase1_handoff_cancels_old_slot_and_never_reuses_generation() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    model.admit_job()
    model.prepare_job()
    old_generation = model.job_generation

    model.handoff_to_overworld()

    assert model.owner is Owner.RENDERER_FULL_COLOR_OVERWORLD
    assert model.phase is Phase.OVERWORLD_RECONSTRUCTING
    assert model.generation == old_generation + 1
    assert not model.admission_open
    assert model.job_state is None
    model.activate_overworld()
    assert model.admission_open


def test_phase1_reconstruction_stays_closed_and_cannot_handoff_to_yellow() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    model.handoff_to_overworld()
    before = model.snapshot()

    assert model.phase is Phase.OVERWORLD_RECONSTRUCTING
    assert not model.admission_open
    assert model.admit_job() is RequestResult.DEFERRED
    assert model.snapshot() == before
    with pytest.raises(ModelViolation, match="active full-color ownership"):
        model.handoff_to_yellow()
    assert model.snapshot() == before

    model.activate_overworld()
    assert model.phase is Phase.OVERWORLD_ACTIVE
    assert model.admission_open

    with pytest.raises(ModelViolation, match="reconstruction must keep admission closed"):
        Phase1OwnershipModel(
            owner=Owner.RENDERER_FULL_COLOR_OVERWORLD,
            phase=Phase.OVERWORLD_RECONSTRUCTING,
            generation=2,
            admission_open=True,
        )


def test_phase1_superseded_slot_records_reason_and_replacement_generation() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    model.admit_job()
    model.prepare_job()

    assert model.cancel_superseded()
    assert model.job_state is JobState.CANCELLED
    assert model.cancellation_reason is CancellationReason.SUPERSEDED
    assert model.advance_generation()
    assert model.admit_job() is RequestResult.ACCEPTED
    assert model.job_state is JobState.PENDING
    assert model.job_generation == model.generation
    assert model.cancellation_reason is None


def test_phase1_committing_job_cannot_be_cancelled_reset_or_handed_off() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    model.admit_job()
    model.prepare_job()
    model.begin_commit()
    before = model.snapshot()

    with pytest.raises(ModelViolation, match="COMMITTING is not cancellable"):
        model.cancel_superseded()
    with pytest.raises(ModelViolation, match="COMMITTING is not cancellable"):
        model.reset()
    with pytest.raises(ModelViolation, match="COMMITTING is not cancellable"):
        model.handoff_to_overworld()
    assert model.snapshot() == before


def test_phase1_generation_carry_and_exhaustion_are_fail_closed() -> None:
    carrying = Phase1OwnershipModel(generation=0xFF, admission_open=True)
    assert carrying.advance_generation()
    assert carrying.generation == 0x100
    assert carrying.admission_open

    exhausted = Phase1OwnershipModel(
        generation=PHASE1_MAX_GENERATION,
        admission_open=True,
    )
    assert not exhausted.advance_generation()
    assert exhausted.generation == 0
    assert exhausted.generation_exhausted
    assert not exhausted.admission_open
    assert exhausted.admit_job() is RequestResult.DEFERRED
    assert not exhausted.advance_generation()


def test_phase1_exhausted_handoff_completion_cannot_reopen_admission() -> None:
    model = Phase1OwnershipModel(
        generation=PHASE1_MAX_GENERATION,
        admission_open=True,
    )

    assert not model.begin_handoff_to_overworld()
    before = model.snapshot()
    with pytest.raises(ModelViolation, match="generation space is exhausted"):
        model.complete_handoff(
            Owner.RENDERER_FULL_COLOR_OVERWORLD,
            Phase.OVERWORLD_RECONSTRUCTING,
        )

    assert model.snapshot() == before
    assert not model.admission_open


def test_phase1_wrong_direction_completion_fails_without_state_corruption() -> None:
    model = Phase1OwnershipModel()
    model.hard_boot()
    assert model.begin_handoff_to_overworld()
    before = model.snapshot()

    with pytest.raises(ModelViolation, match="completion direction is invalid"):
        model.complete_handoff(Owner.RENDERER_YELLOW, Phase.YELLOW_ACTIVE)

    assert model.snapshot() == before

    model.complete_handoff(
        Owner.RENDERER_FULL_COLOR_OVERWORLD,
        Phase.OVERWORLD_RECONSTRUCTING,
    )
    model.activate_overworld()
    assert model.begin_handoff_to_yellow()
    before = model.snapshot()

    with pytest.raises(ModelViolation, match="completion direction is invalid"):
        model.complete_handoff(
            Owner.RENDERER_FULL_COLOR_OVERWORLD,
            Phase.OVERWORLD_ACTIVE,
        )

    assert model.snapshot() == before


@pytest.mark.parametrize("seed", range(32))
def test_seeded_phase1_action_scaffolding_is_legal_and_deterministic(seed: int) -> None:
    first = generated_phase1_actions(seed, 64)
    second = generated_phase1_actions(seed, 64)
    assert first == second
    assert replay_phase1_actions(first) == replay_phase1_actions(second)
    assert first[0].kind is Phase1ActionKind.HARD_BOOT

    model = Phase1OwnershipModel()
    for action in first:
        model.apply(action)
        model.assert_invariants()
