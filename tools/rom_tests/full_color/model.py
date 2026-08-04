"""Deterministic reference ownership, request, and job model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import random
from collections.abc import Mapping
from typing import Iterable

from .enums import (
    CancellationReason,
    JobState,
    Owner,
    Phase,
    ReconstructionProvenance,
    RequestResult,
)
from .errors import ModelViolation


class ActionKind(StrEnum):
    MOVEMENT = "MOVEMENT"
    OVERLAY = "OVERLAY"
    CONNECTION = "CONNECTION"
    HANDOFF_TO_OVERWORLD = "HANDOFF_TO_OVERWORLD"
    FINISH_RECONSTRUCTION = "FINISH_RECONSTRUCTION"
    HANDOFF_TO_YELLOW = "HANDOFF_TO_YELLOW"
    RESET = "RESET"
    PREPARE_PENDING = "PREPARE_PENDING"
    INTERRUPT_BOUNDARY = "INTERRUPT_BOUNDARY"
    WRONG_OWNER_REQUEST = "WRONG_OWNER_REQUEST"
    STALE_GENERATION_REQUEST = "STALE_GENERATION_REQUEST"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"


class PreVisibleBoundary(StrEnum):
    PREPARATION = "PREPARATION"
    OWNER_REVALIDATION = "OWNER_REVALIDATION"
    GENERATION_REVALIDATION = "GENERATION_REVALIDATION"
    DESTINATION_REVALIDATION = "DESTINATION_REVALIDATION"
    BUDGET_REVALIDATION = "BUDGET_REVALIDATION"


class Phase1ActionKind(StrEnum):
    """Actions implemented by the bounded Phase 1 ownership core.

    These are deliberately separate from :class:`ActionKind`: Phase 1 has one
    diagnostic slot and no visible renderer work, overlays, or reconstruction
    ledger.  Keeping the vocabulary small also gives the ROM comparison tests
    a stable action ABI while the later renderer model can continue to grow.
    """

    HARD_BOOT = "HARD_BOOT"
    RESET = "RESET"
    HANDOFF_TO_OVERWORLD = "HANDOFF_TO_OVERWORLD"
    ACTIVATE_OVERWORLD = "ACTIVATE_OVERWORLD"
    HANDOFF_TO_YELLOW = "HANDOFF_TO_YELLOW"
    ADMIT_JOB = "ADMIT_JOB"
    PREPARE_JOB = "PREPARE_JOB"
    BEGIN_COMMIT = "BEGIN_COMMIT"
    COMPLETE_JOB = "COMPLETE_JOB"
    CANCEL_SUPERSEDED = "CANCEL_SUPERSEDED"
    ADVANCE_GENERATION = "ADVANCE_GENERATION"


@dataclass(frozen=True, slots=True)
class Phase1Action:
    kind: Phase1ActionKind


@dataclass(frozen=True, slots=True)
class Phase1State:
    """The complete host/ROM comparison surface for Phase 1."""

    owner: Owner
    phase: Phase
    generation: int
    admission_open: bool
    job_state: JobState | None
    job_generation: int | None
    cancellation_reason: CancellationReason | None
    generation_exhausted: bool


PHASE1_MAX_GENERATION = 0xFFFFFFFF


@dataclass(slots=True)
class Phase1OwnershipModel:
    """Reference model for the production Phase 1 single-slot runtime.

    No method models a tile, palette, OAM, VRAM, or other visible write.  The
    slot exists only to prove admission, cancellation, and generation safety.
    Generation zero is reserved for an empty/uninitialised job token.
    """

    owner: Owner = Owner.RENDERER_YELLOW
    phase: Phase = Phase.YELLOW_ACTIVE
    generation: int = 0
    admission_open: bool = False
    job_state: JobState | None = None
    job_generation: int | None = None
    cancellation_reason: CancellationReason | None = None
    generation_exhausted: bool = False
    last_request_result: RequestResult | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.generation <= PHASE1_MAX_GENERATION:
            raise ModelViolation("Phase 1 generation must fit an unsigned 32-bit token")
        self.assert_invariants()

    def snapshot(self) -> Phase1State:
        return Phase1State(
            owner=self.owner,
            phase=self.phase,
            generation=self.generation,
            admission_open=self.admission_open,
            job_state=self.job_state,
            job_generation=self.job_generation,
            cancellation_reason=self.cancellation_reason,
            generation_exhausted=self.generation_exhausted,
        )

    def hard_boot(self) -> None:
        self.owner = Owner.RENDERER_YELLOW
        self.phase = Phase.YELLOW_ACTIVE
        self.generation = 0
        self.generation_exhausted = False
        self._clear_job()
        if self._advance_generation():
            self.admission_open = True
        self.assert_invariants()

    def reset(self) -> None:
        self._cancel_if_cancellable(CancellationReason.RESET)
        self.admission_open = False
        advanced = self._advance_generation()
        self.owner = Owner.RENDERER_YELLOW
        self.phase = Phase.YELLOW_ACTIVE
        self._clear_job()
        self.admission_open = advanced
        self.assert_invariants()

    def handoff_to_overworld(self) -> None:
        if not self.begin_handoff_to_overworld():
            return
        self.complete_handoff(
            Owner.RENDERER_FULL_COLOR_OVERWORLD,
            Phase.OVERWORLD_RECONSTRUCTING,
        )

    def begin_handoff_to_overworld(self) -> bool:
        if self.owner is not Owner.RENDERER_YELLOW or self.phase is not Phase.YELLOW_ACTIVE:
            raise ModelViolation("Phase 1 overworld handoff requires Yellow active")
        if self.job_state is JobState.COMMITTING:
            raise ModelViolation("Phase 1 job: COMMITTING is not cancellable")
        self.admission_open = False
        self.phase = Phase.HANDOFF_TO_OVERWORLD
        self._cancel_if_cancellable(CancellationReason.HANDOFF)
        if not self._advance_generation():
            self.assert_invariants()
            return False
        self.assert_invariants()
        return True

    def activate_overworld(self) -> None:
        if (
            self.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD
            or self.phase is not Phase.OVERWORLD_RECONSTRUCTING
        ):
            raise ModelViolation("Phase 1 activation requires overworld reconstruction")
        if self.generation_exhausted:
            raise ModelViolation("Phase 1 generation space is exhausted")
        self.phase = Phase.OVERWORLD_ACTIVE
        self.admission_open = True
        self.assert_invariants()

    def handoff_to_yellow(self) -> None:
        if not self.begin_handoff_to_yellow():
            return
        self.complete_handoff(Owner.RENDERER_YELLOW, Phase.YELLOW_ACTIVE)

    def begin_handoff_to_yellow(self) -> bool:
        if self.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD or self.phase not in {
            Phase.OVERWORLD_ACTIVE,
            Phase.OVERWORLD_OVERLAY,
        }:
            raise ModelViolation("Phase 1 Yellow handoff requires active full-color ownership")
        if self.job_state is JobState.COMMITTING:
            raise ModelViolation("Phase 1 job: COMMITTING is not cancellable")
        self.admission_open = False
        self.phase = Phase.HANDOFF_TO_YELLOW
        self._cancel_if_cancellable(CancellationReason.HANDOFF)
        if not self._advance_generation():
            self.assert_invariants()
            return False
        self.assert_invariants()
        return True

    def complete_handoff(self, arriving_owner: Owner, arriving_phase: Phase) -> None:
        if self.admission_open:
            raise ModelViolation("Phase 1 handoff completion requires closed admission")
        if self.generation_exhausted or self.generation == 0:
            raise ModelViolation("Phase 1 generation space is exhausted")
        if arriving_owner is Owner.RENDERER_FULL_COLOR_OVERWORLD:
            if (
                self.owner is not Owner.RENDERER_YELLOW
                or self.phase is not Phase.HANDOFF_TO_OVERWORLD
                or arriving_phase is not Phase.OVERWORLD_RECONSTRUCTING
            ):
                raise ModelViolation("Phase 1 handoff completion direction is invalid")
        elif arriving_owner is Owner.RENDERER_YELLOW:
            if (
                self.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD
                or self.phase is not Phase.HANDOFF_TO_YELLOW
                or arriving_phase is not Phase.YELLOW_ACTIVE
            ):
                raise ModelViolation("Phase 1 handoff completion direction is invalid")
        else:
            raise ModelViolation("Phase 1 handoff completion owner is invalid")
        self.owner = arriving_owner
        self.phase = arriving_phase
        self._clear_job()
        self.admission_open = arriving_phase is not Phase.OVERWORLD_RECONSTRUCTING
        self.assert_invariants()

    def admit_job(self, *, owner: Owner | None = None, generation: int | None = None) -> RequestResult:
        requested_owner = self.owner if owner is None else owner
        requested_generation = self.generation if generation is None else generation
        if requested_owner is not self.owner:
            result = RequestResult.REJECTED_WRONG_OWNER
        elif requested_generation != self.generation:
            result = RequestResult.REJECTED_STALE_GENERATION
        elif not self.admission_open:
            result = RequestResult.DEFERRED
        elif self.job_state not in {None, JobState.COMPLETE, JobState.CANCELLED}:
            result = RequestResult.REJECTED_CAPACITY
        else:
            self.job_state = JobState.PENDING
            self.job_generation = self.generation
            self.cancellation_reason = None
            result = RequestResult.ACCEPTED
        self.last_request_result = result
        self.assert_invariants()
        return result

    def prepare_job(self) -> None:
        self._transition_job(JobState.PENDING, JobState.PREPARED)

    def begin_commit(self) -> None:
        self._transition_job(JobState.PREPARED, JobState.COMMITTING)

    def complete_job(self) -> None:
        self._transition_job(JobState.COMMITTING, JobState.COMPLETE)

    def cancel_superseded(self) -> bool:
        cancelled = self._cancel_if_cancellable(CancellationReason.SUPERSEDED)
        self.assert_invariants()
        return cancelled

    def advance_generation(self) -> bool:
        advanced = self._advance_generation()
        self.assert_invariants()
        return advanced

    def apply(self, action: Phase1Action) -> RequestResult | bool | None:
        if action.kind is Phase1ActionKind.HARD_BOOT:
            self.hard_boot()
        elif action.kind is Phase1ActionKind.RESET:
            self.reset()
        elif action.kind is Phase1ActionKind.HANDOFF_TO_OVERWORLD:
            self.handoff_to_overworld()
        elif action.kind is Phase1ActionKind.ACTIVATE_OVERWORLD:
            self.activate_overworld()
        elif action.kind is Phase1ActionKind.HANDOFF_TO_YELLOW:
            self.handoff_to_yellow()
        elif action.kind is Phase1ActionKind.ADMIT_JOB:
            return self.admit_job()
        elif action.kind is Phase1ActionKind.PREPARE_JOB:
            self.prepare_job()
        elif action.kind is Phase1ActionKind.BEGIN_COMMIT:
            self.begin_commit()
        elif action.kind is Phase1ActionKind.COMPLETE_JOB:
            self.complete_job()
        elif action.kind is Phase1ActionKind.CANCEL_SUPERSEDED:
            return self.cancel_superseded()
        elif action.kind is Phase1ActionKind.ADVANCE_GENERATION:
            return self.advance_generation()
        else:  # pragma: no cover - StrEnum makes this defensive only
            raise ModelViolation(f"unknown Phase 1 action {action.kind!r}")
        return None

    def _transition_job(self, source: JobState, target: JobState) -> None:
        if self.job_state is not source:
            actual = "EMPTY" if self.job_state is None else self.job_state.value
            raise ModelViolation(
                f"Phase 1 job: illegal transition {actual} -> {target.value}"
            )
        if self.job_generation != self.generation:
            raise ModelViolation("Phase 1 job: stale generation execution")
        self.job_state = target
        self.assert_invariants()

    def _cancel_if_cancellable(self, reason: CancellationReason) -> bool:
        if self.job_state in {JobState.PENDING, JobState.PREPARED}:
            self.job_state = JobState.CANCELLED
            self.cancellation_reason = reason
            return True
        if self.job_state is JobState.COMMITTING:
            raise ModelViolation("Phase 1 job: COMMITTING is not cancellable")
        return False

    def _advance_generation(self) -> bool:
        if self.generation_exhausted:
            self.admission_open = False
            return False
        if self.generation == PHASE1_MAX_GENERATION:
            self.generation = 0
            self.admission_open = False
            self.generation_exhausted = True
            return False
        self.generation += 1
        return True

    def _clear_job(self) -> None:
        self.job_state = None
        self.job_generation = None
        self.cancellation_reason = None

    def assert_invariants(self) -> None:
        if not 0 <= self.generation <= PHASE1_MAX_GENERATION:
            raise ModelViolation("Phase 1 generation escaped unsigned 32-bit range")
        if self.generation_exhausted and self.admission_open:
            raise ModelViolation("Phase 1 admission reopened after generation exhaustion")
        if self.phase is Phase.OVERWORLD_RECONSTRUCTING and self.admission_open:
            raise ModelViolation("Phase 1 reconstruction must keep admission closed")
        allowed = _ALLOWED_PHASE_OWNERS[self.phase]
        if self.owner not in allowed:
            raise ModelViolation(
                f"invalid owner/phase pair: {self.owner.value}/{self.phase.value}"
            )
        if self.job_state is None:
            if self.job_generation is not None or self.cancellation_reason is not None:
                raise ModelViolation("Phase 1 empty slot retained job metadata")
            return
        if self.job_generation is None or self.job_generation == 0:
            raise ModelViolation("Phase 1 occupied slot requires a nonzero generation")
        if self.job_state is JobState.CANCELLED:
            if self.cancellation_reason is None:
                raise ModelViolation("Phase 1 cancelled job requires one stable reason")
        elif self.cancellation_reason is not None:
            raise ModelViolation("Phase 1 live job carries a cancellation reason")


def generated_phase1_actions(seed: int, count: int) -> tuple[Phase1Action, ...]:
    """Generate a deterministic *legal* action stream for model/ROM comparison."""
    if count < 0:
        raise ModelViolation("Phase 1 action count must be non-negative")
    rng = random.Random(seed)
    model = Phase1OwnershipModel()
    actions: list[Phase1Action] = [Phase1Action(Phase1ActionKind.HARD_BOOT)]
    model.apply(actions[0])
    while len(actions) < count:
        choices: list[Phase1ActionKind] = []
        if model.job_state is not JobState.COMMITTING:
            choices.append(Phase1ActionKind.RESET)
            if model.phase is Phase.YELLOW_ACTIVE:
                choices.append(Phase1ActionKind.HANDOFF_TO_OVERWORLD)
            elif model.phase is Phase.OVERWORLD_RECONSTRUCTING:
                choices.append(Phase1ActionKind.ACTIVATE_OVERWORLD)
            elif model.phase is Phase.OVERWORLD_ACTIVE:
                choices.append(Phase1ActionKind.HANDOFF_TO_YELLOW)
        if model.job_state in {None, JobState.COMPLETE, JobState.CANCELLED}:
            choices.append(Phase1ActionKind.ADVANCE_GENERATION)
        if model.admission_open:
            if model.job_state in {None, JobState.COMPLETE, JobState.CANCELLED}:
                choices.append(Phase1ActionKind.ADMIT_JOB)
            elif model.job_state is JobState.PENDING:
                choices.extend(
                    (Phase1ActionKind.PREPARE_JOB, Phase1ActionKind.CANCEL_SUPERSEDED)
                )
            elif model.job_state is JobState.PREPARED:
                choices.extend(
                    (Phase1ActionKind.BEGIN_COMMIT, Phase1ActionKind.CANCEL_SUPERSEDED)
                )
            elif model.job_state is JobState.COMMITTING:
                choices.append(Phase1ActionKind.COMPLETE_JOB)
        action = Phase1Action(rng.choice(choices))
        model.apply(action)
        actions.append(action)
    return tuple(actions[:count])


def replay_phase1_actions(actions: Iterable[Phase1Action]) -> tuple[Phase1State, ...]:
    """Return the expected state after each action for a ROM-side replay."""
    model = Phase1OwnershipModel()
    states: list[Phase1State] = []
    for action in actions:
        model.apply(action)
        states.append(model.snapshot())
    return tuple(states)


@dataclass(frozen=True, slots=True)
class ModelAction:
    kind: ActionKind
    nonce: int = 0


@dataclass(frozen=True, slots=True)
class RequestClass:
    name: str
    required_visible_state: bool
    supersedable: bool
    pressure_result: RequestResult
    final_rejection_fallback: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ModelViolation("request class: name must not be empty")
        if self.pressure_result not in {
            RequestResult.DEFERRED,
            RequestResult.REJECTED_CAPACITY,
        }:
            raise ModelViolation(
                f"request class {self.name}: pressure result must be DEFERRED or REJECTED_CAPACITY"
            )
        if self.required_visible_state and self.pressure_result is not RequestResult.DEFERRED:
            raise ModelViolation(
                f"request class {self.name}: required visible-state work must select DEFERRED"
            )
        if self.pressure_result is RequestResult.REJECTED_CAPACITY:
            if not self.supersedable and self.required_visible_state:
                raise ModelViolation(
                    f"request class {self.name}: capacity rejection requires optional or supersedable work"
                )
            if not self.final_rejection_fallback:
                raise ModelViolation(
                    f"request class {self.name}: capacity rejection requires a documented fallback"
                )


REQUIRED_VISIBLE = RequestClass(
    name="required-visible",
    required_visible_state=True,
    supersedable=False,
    pressure_result=RequestResult.DEFERRED,
)
OPTIONAL_SUPERSEDABLE = RequestClass(
    name="optional-supersedable",
    required_visible_state=False,
    supersedable=True,
    pressure_result=RequestResult.REJECTED_CAPACITY,
    final_rejection_fallback="retain the previously presented optional state",
)


@dataclass(frozen=True, slots=True)
class Request:
    request_id: str
    owner: Owner
    generation: int
    resources: tuple[str, ...]
    commit_unit_id: str
    desired_state: bytes | Mapping[str, bytes]
    request_class: RequestClass = REQUIRED_VISIBLE

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ModelViolation("request: request_id must not be empty")
        if self.generation < 0:
            raise ModelViolation("request: generation must be non-negative")
        if not self.resources or any(not resource for resource in self.resources):
            raise ModelViolation("request: resources must be a non-empty tuple of names")
        if len(set(self.resources)) != len(self.resources):
            raise ModelViolation("request: resources must not contain duplicates")
        if not self.commit_unit_id:
            raise ModelViolation("request: commit_unit_id must not be empty")
        if isinstance(self.desired_state, Mapping):
            if set(self.desired_state) != set(self.resources):
                raise ModelViolation(
                    "request: per-resource desired state must exactly match declared resources"
                )
            if any(not isinstance(value, bytes) for value in self.desired_state.values()):
                raise ModelViolation("request: every desired resource state must be bytes")
            object.__setattr__(self, "desired_state", dict(self.desired_state))
        elif not isinstance(self.desired_state, bytes):
            raise ModelViolation("request: desired_state must be bytes or a resource mapping")

    @property
    def desired_states(self) -> dict[str, bytes]:
        if isinstance(self.desired_state, bytes):
            return {resource: self.desired_state for resource in self.resources}
        return dict(self.desired_state)

    @property
    def equivalence_key(self) -> tuple[object, ...]:
        return (
            self.owner,
            self.generation,
            self.resources,
            self.commit_unit_id,
            tuple((resource, self.desired_states[resource]) for resource in self.resources),
        )


@dataclass(frozen=True, slots=True)
class Admission:
    result: RequestResult
    request_id: str
    job_id: str | None
    created: bool
    attached: bool

    def __post_init__(self) -> None:
        if self.result is RequestResult.ACCEPTED:
            if not self.created or self.attached or self.job_id is None:
                raise ModelViolation("admission: ACCEPTED must create exactly one job")
        elif self.result is RequestResult.COALESCED:
            if self.created or not self.attached or self.job_id is None:
                raise ModelViolation("admission: COALESCED must attach without creating a job")
        elif self.created or self.attached or self.job_id is not None:
            raise ModelViolation(f"admission: {self.result.value} must create and attach no work")


@dataclass(slots=True)
class Job:
    job_id: str
    owner: Owner
    generation: int
    resources: tuple[str, ...]
    commit_unit_id: str
    desired_state: dict[str, bytes]
    request_ids: list[str]
    state: JobState = JobState.PENDING
    cancellation_reason: CancellationReason | None = None
    writes: int = 0
    resource_state: dict[str, bytes | None] = field(default_factory=dict)
    worst_case_cycles: int | None = None
    reserved_cycles: int = 0
    budget_attempts: list[PreVisibleBoundary] = field(default_factory=list)

    @property
    def equivalence_key(self) -> tuple[object, ...]:
        return (
            self.owner,
            self.generation,
            self.resources,
            self.commit_unit_id,
            tuple((resource, self.desired_state[resource]) for resource in self.resources),
        )


_ALLOWED_PHASE_OWNERS: dict[Phase, frozenset[Owner]] = {
    Phase.YELLOW_ACTIVE: frozenset({Owner.RENDERER_YELLOW}),
    Phase.HANDOFF_TO_OVERWORLD: frozenset(Owner),
    Phase.OVERWORLD_RECONSTRUCTING: frozenset(
        {Owner.RENDERER_FULL_COLOR_OVERWORLD}
    ),
    Phase.OVERWORLD_ACTIVE: frozenset({Owner.RENDERER_FULL_COLOR_OVERWORLD}),
    Phase.OVERWORLD_OVERLAY: frozenset({Owner.RENDERER_FULL_COLOR_OVERWORLD}),
    Phase.HANDOFF_TO_YELLOW: frozenset(Owner),
}


@dataclass(slots=True)
class OwnershipModel:
    capacity: int = 2
    owner: Owner = Owner.RENDERER_YELLOW
    phase: Phase = Phase.YELLOW_ACTIVE
    generation: int = 1
    admission_open: bool = True
    jobs: dict[str, Job] = field(default_factory=dict)
    last_request_result: RequestResult | None = None
    _seen_requests: set[str] = field(default_factory=set, repr=False)
    _retired_generations: set[int] = field(default_factory=set, repr=False)
    _next_job: int = field(default=1, repr=False)
    reconstruction_required: tuple[str, ...] = ()
    reconstruction_completed: set[str] = field(default_factory=set)
    reconstruction_provenance: dict[str, ReconstructionProvenance] = field(
        default_factory=dict
    )
    reconstruction_poisoned: set[str] = field(default_factory=set)
    reconstruction_unknown_prior_state: bool = False
    presentation_barriers: int = 0
    executed_actions: list[ModelAction] = field(default_factory=list)
    executed_steps: list[str] = field(default_factory=list)
    phase_history: list[Phase] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ModelViolation("model.capacity: expected at least one job")
        if not self.phase_history:
            self.phase_history.append(self.phase)
        self.assert_invariants()

    @property
    def active_jobs(self) -> tuple[Job, ...]:
        return tuple(
            job
            for job in self.jobs.values()
            if job.state not in {JobState.COMPLETE, JobState.CANCELLED}
        )

    def admit(self, request: Request) -> Admission:
        if request.request_id in self._seen_requests:
            raise ModelViolation(f"request {request.request_id}: duplicate request ID")
        self._seen_requests.add(request.request_id)
        if request.owner is not self.owner:
            return self._admission(RequestResult.REJECTED_WRONG_OWNER, request)
        if request.generation != self.generation:
            return self._admission(RequestResult.REJECTED_STALE_GENERATION, request)
        if not self.admission_open:
            return self._admission(RequestResult.DEFERRED, request)

        equivalent = next(
            (job for job in self.active_jobs if job.equivalence_key == request.equivalence_key),
            None,
        )
        if equivalent is not None:
            equivalent.request_ids.append(request.request_id)
            return self._admission(
                RequestResult.COALESCED, request, job=equivalent, attached=True
            )
        if len(self.active_jobs) >= self.capacity:
            return self._admission(request.request_class.pressure_result, request)

        job = Job(
            job_id=f"JOB-{self._next_job:04d}",
            owner=request.owner,
            generation=request.generation,
            resources=request.resources,
            commit_unit_id=request.commit_unit_id,
            desired_state=request.desired_states,
            request_ids=[request.request_id],
            resource_state={resource: None for resource in request.resources},
        )
        self._next_job += 1
        self.jobs[job.job_id] = job
        return self._admission(RequestResult.ACCEPTED, request, job=job, created=True)

    def _admission(
        self,
        result: RequestResult,
        request: Request,
        *,
        job: Job | None = None,
        created: bool = False,
        attached: bool = False,
    ) -> Admission:
        self.last_request_result = result
        return Admission(
            result=result,
            request_id=request.request_id,
            job_id=None if job is None else job.job_id,
            created=created,
            attached=attached,
        )

    def advance(self, job_id: str, target: JobState) -> None:
        job = self._job(job_id)
        allowed = {
            JobState.PENDING: {JobState.PREPARED},
            JobState.PREPARED: {JobState.COMMITTING},
            JobState.COMMITTING: {JobState.COMPLETE},
            JobState.COMPLETE: set(),
            JobState.CANCELLED: set(),
        }
        if target not in allowed[job.state]:
            raise ModelViolation(
                f"job {job_id}: illegal transition {job.state.value} -> {target.value}"
            )
        if job.owner is not self.owner:
            raise ModelViolation(
                f"job {job_id}: wrong owner {job.owner.value}; active owner is {self.owner.value}"
            )
        if job.generation != self.generation:
            self.cancel_job(job_id, CancellationReason.STALE_GENERATION)
            raise ModelViolation(
                f"job {job_id}: stale generation {job.generation}; active generation is {self.generation}"
            )
        if target is JobState.COMMITTING:
            if job.worst_case_cycles is None or job.reserved_cycles < job.worst_case_cycles:
                raise ModelViolation(
                    f"job {job_id}: COMMITTING requires worst-case budget reservation"
                )
        if target is JobState.COMPLETE:
            missing = [
                resource
                for resource, state in job.resource_state.items()
                if state != job.desired_state[resource]
            ]
            if not job.writes:
                raise ModelViolation(
                    f"job {job_id}: COMPLETE requires a real visible write/commit"
                )
            if missing:
                raise ModelViolation(
                    f"job {job_id}: COMPLETE before desired state for resources: "
                    + ", ".join(missing)
                )
        job.state = target

    def prepare(
        self,
        job_id: str,
        *,
        available_cycles: int,
        required_cycles: int,
        boundary: PreVisibleBoundary = PreVisibleBoundary.PREPARATION,
    ) -> bool:
        """Prepare a job and leave it PREPARED when a pre-visible budget fails."""
        if available_cycles < 0 or required_cycles < 0:
            raise ModelViolation("pre-visible budget values must be non-negative")
        job = self._job(job_id)
        if job.state is JobState.PENDING:
            self.advance(job_id, JobState.PREPARED)
        elif job.state is not JobState.PREPARED:
            raise ModelViolation(
                f"job {job_id}: preparation requires PENDING/PREPARED, got {job.state.value}"
            )
        job.budget_attempts.append(boundary)
        return available_cycles >= required_cycles

    def reserve_commit_budget(
        self,
        job_id: str,
        *,
        available_cycles: int,
        worst_case_cycles: int,
    ) -> bool:
        """Reserve the full visible unit or defer while remaining PREPARED."""
        if available_cycles < 0 or worst_case_cycles <= 0:
            raise ModelViolation(
                "commit budget requires non-negative availability and positive worst case"
            )
        job = self._job(job_id)
        if job.state is not JobState.PREPARED:
            raise ModelViolation(
                f"job {job_id}: reservation requires PREPARED, got {job.state.value}"
            )
        job.worst_case_cycles = worst_case_cycles
        if available_cycles < worst_case_cycles:
            job.reserved_cycles = 0
            return False
        job.reserved_cycles = worst_case_cycles
        return True

    def begin_commit(
        self,
        job_id: str,
        *,
        available_cycles: int,
        worst_case_cycles: int,
    ) -> bool:
        if not self.reserve_commit_budget(
            job_id,
            available_cycles=available_cycles,
            worst_case_cycles=worst_case_cycles,
        ):
            return False
        self.advance(job_id, JobState.COMMITTING)
        return True

    def cancel_job(self, job_id: str, reason: CancellationReason) -> None:
        job = self._job(job_id)
        if job.state not in {JobState.PENDING, JobState.PREPARED}:
            raise ModelViolation(
                f"job {job_id}: cannot cancel from {job.state.value}; only PENDING/PREPARED"
            )
        job.state = JobState.CANCELLED
        job.cancellation_reason = reason

    def record_write(
        self,
        job_id: str,
        *,
        owner: Owner,
        generation: int,
        resource: str | None = None,
        value: bytes | None = None,
    ) -> None:
        job = self._job(job_id)
        if owner is not self.owner or job.owner is not self.owner:
            raise ModelViolation(
                f"job {job_id}: wrong owner write under {owner.value}; active {self.owner.value}"
            )
        if generation != self.generation or job.generation != self.generation:
            raise ModelViolation(
                f"job {job_id}: stale generation write {generation}; active {self.generation}"
            )
        if job.state is JobState.CANCELLED:
            raise ModelViolation(f"job {job_id}: cancelled work performed a later write")
        if job.state is not JobState.COMMITTING:
            raise ModelViolation(
                f"job {job_id}: visible write requires COMMITTING, got {job.state.value}"
            )
        if resource is None:
            targets = job.resources
        else:
            if resource not in job.resource_state:
                raise ModelViolation(
                    f"job {job_id}: write names undeclared resource {resource}"
                )
            targets = (resource,)
        for target in targets:
            state = job.desired_state[target] if value is None else value
            if not isinstance(state, bytes):
                raise ModelViolation(f"job {job_id}: written resource state must be bytes")
            job.resource_state[target] = state
        job.writes += 1

    def enter_overlay(self) -> None:
        self._require_state(Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_ACTIVE)
        self.phase = Phase.OVERWORLD_OVERLAY
        self.phase_history.append(self.phase)

    def leave_overlay(self) -> None:
        self._require_state(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_OVERLAY
        )
        self.phase = Phase.OVERWORLD_ACTIVE
        self.phase_history.append(self.phase)

    def begin_handoff_to_overworld(self) -> None:
        self._require_state(Owner.RENDERER_YELLOW, Phase.YELLOW_ACTIVE)
        self._begin_handoff(Phase.HANDOFF_TO_OVERWORLD)

    def select_overworld_owner(self) -> None:
        self._require_state(Owner.RENDERER_YELLOW, Phase.HANDOFF_TO_OVERWORLD)
        self._select_arriving_owner(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_RECONSTRUCTING
        )

    def finish_reconstruction(self) -> None:
        self._require_state(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_RECONSTRUCTING
        )
        missing = sorted(set(self.reconstruction_required) - self.reconstruction_completed)
        if missing:
            raise ModelViolation(
                "reconstruction incomplete; missing authoritative items: "
                + ", ".join(missing)
            )
        if set(self.reconstruction_provenance) != set(self.reconstruction_required):
            raise ModelViolation(
                "reconstruction incomplete; authoritative provenance missing"
            )
        for item, provenance in self.reconstruction_provenance.items():
            if provenance in FORBIDDEN_RECONSTRUCTION_PROVENANCE:
                raise ModelViolation(
                    f"reconstruction {item}: captured/saved display state is not authoritative"
                )
            if provenance is not RECONSTRUCTION_ITEM_PROVENANCE[item]:
                raise ModelViolation(
                    f"reconstruction {item}: non-authoritative provenance "
                    f"{provenance.value}"
                )
        if not self.reconstruction_unknown_prior_state:
            raise ModelViolation(
                "reconstruction must treat prior presented state as poisoned/unknown"
            )
        if self.reconstruction_poisoned != set(self.reconstruction_required):
            raise ModelViolation(
                "reconstruction requires a complete poisoned-prior-state record"
            )
        if self.presentation_barriers != 1:
            raise ModelViolation(
                "reconstruction requires exactly one complete presentation barrier"
            )
        self.phase = Phase.OVERWORLD_ACTIVE
        self.phase_history.append(self.phase)
        self.admission_open = True

    def complete_reconstruction_item(
        self, item: str, provenance: ReconstructionProvenance
    ) -> None:
        self._require_state(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_RECONSTRUCTING
        )
        if item not in self.reconstruction_required:
            raise ModelViolation(f"reconstruction: unknown authoritative item {item}")
        if not isinstance(provenance, ReconstructionProvenance):
            raise ModelViolation(
                f"reconstruction {item}: provenance must be a closed symbolic value"
            )
        if provenance in FORBIDDEN_RECONSTRUCTION_PROVENANCE:
            raise ModelViolation(
                f"reconstruction {item}: captured/saved display state is not authoritative"
            )
        expected = RECONSTRUCTION_ITEM_PROVENANCE[item]
        if provenance is not expected:
            raise ModelViolation(
                f"reconstruction {item}: expected {expected.value}, got {provenance.value}"
            )
        self.reconstruction_completed.add(item)
        self.reconstruction_provenance[item] = provenance

    def present_reconstruction(self) -> None:
        self._require_state(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.OVERWORLD_RECONSTRUCTING
        )
        missing = sorted(set(self.reconstruction_required) - self.reconstruction_completed)
        if missing:
            raise ModelViolation(
                "reconstruction barrier before all authoritative items completed: "
                + ", ".join(missing)
            )
        if self.presentation_barriers:
            raise ModelViolation("reconstruction permits exactly one presentation barrier")
        self.presentation_barriers = 1

    def begin_handoff_to_yellow(self) -> None:
        if self.owner is not Owner.RENDERER_FULL_COLOR_OVERWORLD or self.phase not in {
            Phase.OVERWORLD_ACTIVE,
            Phase.OVERWORLD_OVERLAY,
        }:
            raise ModelViolation(
                "handoff to Yellow requires full-color OVERWORLD_ACTIVE/OVERWORLD_OVERLAY"
            )
        self._begin_handoff(Phase.HANDOFF_TO_YELLOW)

    def select_yellow_owner(self) -> None:
        self._require_state(
            Owner.RENDERER_FULL_COLOR_OVERWORLD, Phase.HANDOFF_TO_YELLOW
        )
        self._select_arriving_owner(Owner.RENDERER_YELLOW, Phase.YELLOW_ACTIVE)
        self.admission_open = True

    def _begin_handoff(self, phase: Phase) -> None:
        committing = [job.job_id for job in self.active_jobs if job.state is JobState.COMMITTING]
        if committing:
            raise ModelViolation(
                "handoff: visible COMMITTING jobs must finish before ownership changes: "
                + ", ".join(committing)
            )
        self.admission_open = False
        for job in self.active_jobs:
            self.cancel_job(job.job_id, CancellationReason.HANDOFF)
        self.phase = phase
        self.phase_history.append(self.phase)

    def _select_arriving_owner(self, owner: Owner, phase: Phase) -> None:
        self._retired_generations.add(self.generation)
        candidate = self.generation + 1
        while candidate in self._retired_generations:
            candidate += 1
        self.generation = candidate
        self.owner = owner
        self.phase = phase
        self.phase_history.append(self.phase)
        if phase is Phase.OVERWORLD_RECONSTRUCTING:
            self.reconstruction_required = RECONSTRUCTION_ITEMS
            self.reconstruction_completed.clear()
            self.reconstruction_provenance.clear()
            self.reconstruction_poisoned = set(RECONSTRUCTION_ITEMS)
            self.reconstruction_unknown_prior_state = True
            self.presentation_barriers = 0

    def reset(self) -> None:
        for job in self.active_jobs:
            if job.state is JobState.COMMITTING:
                raise ModelViolation(
                    f"reset: visible COMMITTING job {job.job_id} must finish before reset"
                )
            self.cancel_job(job.job_id, CancellationReason.RESET)
        self._retired_generations.add(self.generation)
        self.generation = max(self._retired_generations) + 1
        self.owner = Owner.RENDERER_YELLOW
        self.phase = Phase.YELLOW_ACTIVE
        self.phase_history.append(self.phase)
        self.admission_open = True
        self.last_request_result = None

    def revalidate(self, job_id: str, *, owner: Owner, generation: int) -> bool:
        job = self._job(job_id)
        if owner is not self.owner or job.owner is not self.owner:
            self.cancel_job(job_id, CancellationReason.HANDOFF)
            return False
        if generation != self.generation or job.generation != self.generation:
            self.cancel_job(job_id, CancellationReason.STALE_GENERATION)
            return False
        return True

    def supersede(self, job_id: str) -> None:
        self.cancel_job(job_id, CancellationReason.SUPERSEDED)

    def assert_invariants(self) -> None:
        if self.owner not in _ALLOWED_PHASE_OWNERS[self.phase]:
            raise ModelViolation(
                f"invalid owner/phase pair: {self.owner.value}/{self.phase.value}"
            )
        for job in self.jobs.values():
            if job.state is JobState.CANCELLED and job.cancellation_reason is None:
                raise ModelViolation(f"job {job.job_id}: cancellation reason missing")
            if job.state is not JobState.CANCELLED and job.cancellation_reason is not None:
                raise ModelViolation(
                    f"job {job.job_id}: non-cancelled job has cancellation reason"
                )
            if job.state is JobState.CANCELLED and job.writes:
                raise ModelViolation(
                    f"job {job.job_id}: cancelled work performed a later write "
                    f"({job.writes} writes recorded)"
                )
            if job.state in {JobState.PENDING, JobState.PREPARED} and (
                job.writes or any(state is not None for state in job.resource_state.values())
            ):
                raise ModelViolation(
                    f"job {job.job_id}: {job.state.value} work altered presented resources"
                )
            if job.state is JobState.COMMITTING and (
                job.worst_case_cycles is None
                or job.reserved_cycles < job.worst_case_cycles
            ):
                raise ModelViolation(
                    f"job {job.job_id}: COMMITTING without worst-case budget reservation"
                )
            if job.state is JobState.COMPLETE:
                if not job.writes:
                    raise ModelViolation(
                        f"job {job.job_id}: COMPLETE without a real visible write/commit"
                    )
                incomplete = [
                    resource
                    for resource, state in job.resource_state.items()
                    if state != job.desired_state[resource]
                ]
                if incomplete:
                    raise ModelViolation(
                        f"job {job.job_id}: COMPLETE with incomplete resources: "
                        + ", ".join(incomplete)
                    )

    def _job(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise ModelViolation(f"unknown job {job_id}") from exc

    def _require_state(self, owner: Owner, phase: Phase) -> None:
        if self.owner is not owner or self.phase is not phase:
            raise ModelViolation(
                f"expected {owner.value}/{phase.value}, got {self.owner.value}/{self.phase.value}"
            )


def generate_actions(
    seed: int,
    count: int,
    *,
    adversarial: bool = False,
) -> tuple[ModelAction, ...]:
    """Generate a deterministic, bounded action vocabulary for model tests."""
    if count < 0:
        raise ModelViolation("action count must be non-negative")
    rng = random.Random(seed)
    ordinary = (
        ActionKind.MOVEMENT,
        ActionKind.OVERLAY,
        ActionKind.CONNECTION,
        ActionKind.HANDOFF_TO_OVERWORLD,
        ActionKind.FINISH_RECONSTRUCTION,
        ActionKind.HANDOFF_TO_YELLOW,
        ActionKind.RESET,
        ActionKind.PREPARE_PENDING,
        ActionKind.INTERRUPT_BOUNDARY,
    )
    hostile = (
        ActionKind.WRONG_OWNER_REQUEST,
        ActionKind.STALE_GENERATION_REQUEST,
        ActionKind.ILLEGAL_TRANSITION,
    )
    choices = ordinary + hostile if adversarial else ordinary
    return tuple(ModelAction(rng.choice(choices), rng.getrandbits(32)) for _ in range(count))


def execute_valid_actions(actions: Iterable[ModelAction], *, capacity: int = 2) -> OwnershipModel:
    """Interpret generated actions while preserving a legal lifecycle.

    Context-inapplicable actions are deterministic no-ops, but only actions
    actually executed are appended to ``model.executed_actions``. Generated
    vocabulary therefore cannot be mistaken for behavioral coverage.
    """
    model = OwnershipModel(capacity=capacity)
    for index, action in enumerate(actions):
        executed = False
        if action.kind is ActionKind.RESET:
            _settle_committing(model)
            model.reset()
            executed = True
        elif action.kind is ActionKind.HANDOFF_TO_OVERWORLD:
            if model.phase is Phase.YELLOW_ACTIVE:
                _settle_committing(model)
                model.begin_handoff_to_overworld()
                model.executed_steps.extend(
                    (
                        "HANDOFF_TO_OVERWORLD:CLOSE_ADMISSION_AND_SETTLE",
                        "HANDOFF_TO_OVERWORLD:CANCEL_DEPARTING_WORK",
                    )
                )
                model.select_overworld_owner()
                model.executed_steps.extend(
                    (
                        "HANDOFF_TO_OVERWORLD:FRESH_GENERATION",
                        "HANDOFF_TO_OVERWORLD:SELECT_AND_INITIALIZE_OWNER",
                    )
                )
                executed = True
        elif action.kind is ActionKind.FINISH_RECONSTRUCTION:
            if model.phase is Phase.OVERWORLD_RECONSTRUCTING:
                for item in model.reconstruction_required:
                    model.complete_reconstruction_item(
                        item, RECONSTRUCTION_ITEM_PROVENANCE[item]
                    )
                model.present_reconstruction()
                model.finish_reconstruction()
                executed = True
        elif action.kind is ActionKind.HANDOFF_TO_YELLOW:
            if model.phase in {Phase.OVERWORLD_ACTIVE, Phase.OVERWORLD_OVERLAY}:
                _settle_committing(model)
                model.begin_handoff_to_yellow()
                model.executed_steps.extend(
                    (
                        "HANDOFF_TO_YELLOW:CLOSE_ADMISSION_AND_SETTLE",
                        "HANDOFF_TO_YELLOW:CANCEL_DEPARTING_WORK",
                    )
                )
                model.select_yellow_owner()
                model.executed_steps.extend(
                    (
                        "HANDOFF_TO_YELLOW:FRESH_GENERATION",
                        "HANDOFF_TO_YELLOW:SELECT_AND_INITIALIZE_OWNER",
                        "HANDOFF_TO_YELLOW:REOPEN_ADMISSION",
                    )
                )
                executed = True
        elif action.kind is ActionKind.OVERLAY:
            if model.phase is Phase.OVERWORLD_ACTIVE:
                model.enter_overlay()
                _submit_and_complete(model, index, action)
                model.leave_overlay()
                executed = True
        elif action.kind in {ActionKind.MOVEMENT, ActionKind.CONNECTION}:
            if model.phase in {Phase.YELLOW_ACTIVE, Phase.OVERWORLD_ACTIVE}:
                _submit_and_complete(model, index, action)
                executed = True
        elif action.kind is ActionKind.PREPARE_PENDING:
            if model.admission_open:
                admission = model.admit(_request_for(model, index, action))
                if admission.result is RequestResult.ACCEPTED:
                    model.advance(admission.job_id or "", JobState.PREPARED)
                    executed = True
        elif action.kind is ActionKind.INTERRUPT_BOUNDARY:
            model.assert_invariants()
            executed = True
        elif action.kind in {
            ActionKind.WRONG_OWNER_REQUEST,
            ActionKind.STALE_GENERATION_REQUEST,
            ActionKind.ILLEGAL_TRANSITION,
        }:
            raise ModelViolation(
                f"action {index}: adversarial action {action.kind.value} in valid sequence"
            )
        if executed:
            model.executed_actions.append(action)
        model.assert_invariants()
    return model


def _request_for(model: OwnershipModel, index: int, action: ModelAction) -> Request:
    return Request(
        request_id=f"REQ-{index:04d}-{action.nonce:08x}",
        owner=model.owner,
        generation=model.generation,
        resources=("BG_TILE_IDS", "BG_ATTRIBUTES"),
        commit_unit_id=f"CU-{action.kind.value}",
        desired_state=action.nonce.to_bytes(4, "little"),
    )


def _submit_and_complete(model: OwnershipModel, index: int, action: ModelAction) -> None:
    admission = model.admit(_request_for(model, index, action))
    if admission.result is RequestResult.ACCEPTED:
        job_id = admission.job_id or ""
        model.advance(job_id, JobState.PREPARED)
        model.begin_commit(job_id, available_cycles=1, worst_case_cycles=1)
        model.record_write(job_id, owner=model.owner, generation=model.generation)
        model.advance(job_id, JobState.COMPLETE)


def _settle_committing(model: OwnershipModel) -> None:
    for job in model.active_jobs:
        if job.state is JobState.COMMITTING:
            if not job.writes:
                model.record_write(
                    job.job_id, owner=model.owner, generation=model.generation
                )
            model.advance(job.job_id, JobState.COMPLETE)


RECONSTRUCTION_ITEMS = (
    "map_tileset_overrides",
    "viewport_scroll_window_destination",
    "tiles_animation_field_replacements",
    "tilemaps_and_attributes",
    "base_transformed_hardware_palettes",
    "player_follower_object_shadow_oam",
    "request_scheduler_state",
    "machine_state_restored",
)

RECONSTRUCTION_ITEM_PROVENANCE = {
    "map_tileset_overrides": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "viewport_scroll_window_destination": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "tiles_animation_field_replacements": ReconstructionProvenance.REQUEST_AUTHORITATIVE_STATE,
    "tilemaps_and_attributes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "base_transformed_hardware_palettes": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "player_follower_object_shadow_oam": ReconstructionProvenance.FRESHLY_GENERATED_STATE,
    "request_scheduler_state": ReconstructionProvenance.INITIALIZED_SCHEDULER_STATE,
    "machine_state_restored": ReconstructionProvenance.RESTORED_MACHINE_STATE,
}

FORBIDDEN_RECONSTRUCTION_PROVENANCE = frozenset(
    {
        ReconstructionProvenance.CAPTURED_VRAM,
        ReconstructionProvenance.SAVED_VRAM,
        ReconstructionProvenance.CAPTURED_PALETTE_RAM,
        ReconstructionProvenance.SAVED_PALETTE_RAM,
        ReconstructionProvenance.CAPTURED_OAM,
        ReconstructionProvenance.SAVED_OAM,
        ReconstructionProvenance.CAPTURED_SCREEN_BUFFER,
        ReconstructionProvenance.SAVED_SCREEN_BUFFER,
    }
)
