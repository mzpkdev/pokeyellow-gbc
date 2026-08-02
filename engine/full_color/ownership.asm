; Phase 1 renderer ownership core.
; Yellow's stack lives in switchable WRAM bank 1. Every ownership entry masks
; IE before selecting bank 2 and remains a leaf until the caller's WRAM bank is
; restored. The exact raw IE value is restored last, so the same primitive is
; safe in mainline code and inside an ISR whose IME is already clear.

MACRO select_renderer_state_e
	ldh a, [rIE]
	ldh [hRendererStateSavedIE], a
	xor a
	ldh [rIE], a
	ldh a, [rSVBK]
	ldh [hRendererStateSavedSVBK], a
	ld a, PHASE1_SELECTED_WRAM_BANK
	ldh [rSVBK], a
ENDM

MACRO restore_renderer_state_e
	ldh a, [hRendererStateSavedSVBK]
	ldh [rSVBK], a
	ldh a, [hRendererStateSavedIE]
	ldh [rIE], a
ENDM

MACRO clear_renderer_job
	ld a, RENDERER_JOB_NONE
	ld [wRendererJobState], a
	ld a, CANCELLATION_NONE
	ld [wRendererJobCancellationReason], a
	xor a
	ld [wRendererJobGeneration], a
	ld [wRendererJobGeneration + 1], a
	ld [wRendererJobGeneration + 2], a
	ld [wRendererJobGeneration + 3], a
ENDM

; Jumps to the supplied exhaustion label on zero or 32-bit wrap.
MACRO advance_renderer_generation
	ld a, [wRendererGeneration]
	ld b, a
	ld a, [wRendererGeneration + 1]
	or b
	ld b, a
	ld a, [wRendererGeneration + 2]
	or b
	ld b, a
	ld a, [wRendererGeneration + 3]
	or b
	jp z, \1
	ld hl, wRendererGeneration
	ld b, 4
.increment\@
	inc [hl]
	jr nz, .advanced\@
	inc hl
	dec b
	jr nz, .increment\@
	jp \1
.advanced\@
ENDM

InitRendererOwnership::
	select_renderer_state_e
	xor a
	ld hl, wRendererStateStart
	ld b, PHASE1_OWNERSHIP_STATE_BYTES
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_ACTIVE
	ld [wRendererPhase], a
	ld a, 1
	ld [wRendererGeneration], a
	ld [wRendererAdmissionOpen], a
	clear_renderer_job
IF DEF(FULL_COLOR_PHASE2_ACTIVE)
	call InitFullColorSchedulerSelected
ENDC
	restore_renderer_state_e
	and a
	ret

SoftResetRendererOwnership::
	call ResetRendererOwnership
	jr c, .commit_in_progress
	ld a, 1
	ldh [hSoftReset], a
	call StopAllSounds
	call GBPalWhiteOut
	ld c, 32
	call DelayFrames
	jp SoftResetInit
.commit_in_progress
	jr .commit_in_progress

ResetRendererOwnership::
	select_renderer_state_e
	ld a, [wRendererJobState]
	cp COMMITTING
	jr z, .commit_in_progress
	xor a
	ld [wRendererAdmissionOpen], a
	ld a, [wRendererJobState]
	cp PENDING
	jr z, .cancel
	cp PREPARED
	jr nz, .advance
.cancel
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, RESET
	ld [wRendererJobCancellationReason], a
.advance
IF DEF(FULL_COLOR_PHASE2_ACTIVE)
	call CancelFullColorSchedulerSelected
ENDC
	advance_renderer_generation .generation_exhausted
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_ACTIVE
	ld [wRendererPhase], a
	clear_renderer_job
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	restore_renderer_state_e
	and a
	ret
.generation_exhausted
	xor a
	ld [wRendererAdmissionOpen], a
	ld b, FULL_COLOR_ASSERT_GENERATION_EXHAUSTED
	jr .assert
.commit_in_progress
	ld b, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
.assert
	restore_renderer_state_e
	ld a, b
	call RecordRendererAssertion
	scf
	ret

; Input: A = HANDOFF_TO_OVERWORLD or HANDOFF_TO_YELLOW.
BeginRendererHandoff::
	ld c, a
	select_renderer_state_e
	ld a, c
	cp HANDOFF_TO_OVERWORLD
	jr z, .to_overworld
	cp HANDOFF_TO_YELLOW
	jp nz, .invalid
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp OVERWORLD_ACTIVE
	jr z, .validated
	cp OVERWORLD_OVERLAY
	jr nz, .invalid
	jr .validated
.to_overworld
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp YELLOW_ACTIVE
	jr nz, .invalid
.validated
	ld a, [wRendererJobState]
	cp COMMITTING
	jr z, .commit_in_progress
	xor a
	ld [wRendererAdmissionOpen], a
	ld a, [wRendererJobState]
	cp PENDING
	jr z, .cancel
	cp PREPARED
	jr nz, .set_phase
.cancel
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, HANDOFF
	ld [wRendererJobCancellationReason], a
.set_phase
IF DEF(FULL_COLOR_PHASE2_ACTIVE)
	push bc
	call CancelFullColorSchedulerSelected
	pop bc
ENDC
	ld a, c
	ld [wRendererPhase], a
	advance_renderer_generation .generation_exhausted
	restore_renderer_state_e
	and a
	ret
.generation_exhausted
	xor a
	ld [wRendererAdmissionOpen], a
	ld b, FULL_COLOR_ASSERT_GENERATION_EXHAUSTED
	jr .assert
.invalid
	ld b, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	jr .assert
.commit_in_progress
	ld b, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
.assert
	restore_renderer_state_e
	ld a, b
	call RecordRendererAssertion
	scf
	ret

; Input: A = arriving owner, C = arriving phase.
CompleteRendererHandoff::
	ld b, a
	select_renderer_state_e
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	ld a, [wRendererGeneration]
	ld d, a
	ld a, [wRendererGeneration + 1]
	or d
	ld d, a
	ld a, [wRendererGeneration + 2]
	or d
	ld d, a
	ld a, [wRendererGeneration + 3]
	or d
	jr z, .invalid
	ld a, b
	cp RENDERER_YELLOW
	jr z, .yellow
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp HANDOFF_TO_OVERWORLD
	jr nz, .invalid
	ld a, c
	cp OVERWORLD_RECONSTRUCTING
	jr nz, .invalid
	jr .selected
.yellow
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp HANDOFF_TO_YELLOW
	jr nz, .invalid
	ld a, c
	cp YELLOW_ACTIVE
	jr nz, .invalid
.selected
	ld a, b
	ld [wRendererOwner], a
	ld a, c
	ld [wRendererPhase], a
	clear_renderer_job
	ld a, c
	cp OVERWORLD_RECONSTRUCTING
	jr z, .closed
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	jr .done
.closed
	xor a
	ld [wRendererAdmissionOpen], a
.done
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	scf
	ret

SelectYellowRenderer::
	ld a, RENDERER_YELLOW
	ld c, YELLOW_ACTIVE
	jp CompleteRendererHandoff

SelectFullColorOwnerForDiagnostic::
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ld c, OVERWORLD_RECONSTRUCTING
	jp CompleteRendererHandoff

ActivateFullColorOwnerForDiagnostic::
	select_renderer_state_e
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp OVERWORLD_RECONSTRUCTING
	jr nz, .invalid
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	ld a, [wRendererGeneration]
	ld c, a
	ld a, [wRendererGeneration + 1]
	or c
	ld c, a
	ld a, [wRendererGeneration + 2]
	or c
	ld c, a
	ld a, [wRendererGeneration + 3]
	or c
	jr z, .invalid
	ld a, OVERWORLD_ACTIVE
	ld [wRendererPhase], a
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	scf
	ret

AdvanceRendererGeneration::
	select_renderer_state_e
	ld a, [wRendererJobState]
	cp COMMITTING
	jr z, .commit_in_progress
	cp PENDING
	jr z, .cancel
	cp PREPARED
	jr nz, .advance
.cancel
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, STALE_GENERATION
	ld [wRendererJobCancellationReason], a
.advance
IF DEF(FULL_COLOR_PHASE2_ACTIVE)
	call CancelFullColorSchedulerSelected
ENDC
	advance_renderer_generation .generation_exhausted
	restore_renderer_state_e
	and a
	ret
.generation_exhausted
	xor a
	ld [wRendererAdmissionOpen], a
	ld b, FULL_COLOR_ASSERT_GENERATION_EXHAUSTED
	jr .assert
.commit_in_progress
	ld b, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
.assert
	restore_renderer_state_e
	ld a, b
	call RecordRendererAssertion
	scf
	ret

AdmitRendererDiagnosticJob::
	select_renderer_state_e
	ld a, [wRendererAdmissionOpen]
	and a
	jr z, .rejected
	ld a, [wRendererJobState]
	cp RENDERER_JOB_NONE
	jr z, .admit
	cp COMPLETE
	jr z, .admit
	cp CANCELLED
	jr nz, .rejected
.admit
	ld a, [wRendererGeneration]
	ld [wRendererJobGeneration], a
	ld a, [wRendererGeneration + 1]
	ld [wRendererJobGeneration + 1], a
	ld a, [wRendererGeneration + 2]
	ld [wRendererJobGeneration + 2], a
	ld a, [wRendererGeneration + 3]
	ld [wRendererJobGeneration + 3], a
	ld a, PENDING
	ld [wRendererJobState], a
	ld a, CANCELLATION_NONE
	ld [wRendererJobCancellationReason], a
	restore_renderer_state_e
	ld a, ACCEPTED
	and a
	ret
.rejected
	restore_renderer_state_e
	ld a, DEFERRED
	scf
	ret

SetRendererJobPrepared::
	ld b, PENDING
	ld c, PREPARED
	jr TransitionRendererJob

SetRendererJobCommitting::
	ld b, PREPARED
	ld c, COMMITTING
	jr TransitionRendererJob

CompleteRendererJob::
	ld b, COMMITTING
	ld c, COMPLETE
	; fallthrough
TransitionRendererJob:
	select_renderer_state_e
	ld a, [wRendererJobGeneration]
	ld d, a
	ld a, [wRendererGeneration]
	cp d
	jr nz, .stale
	ld a, [wRendererJobGeneration + 1]
	ld d, a
	ld a, [wRendererGeneration + 1]
	cp d
	jr nz, .stale
	ld a, [wRendererJobGeneration + 2]
	ld d, a
	ld a, [wRendererGeneration + 2]
	cp d
	jr nz, .stale
	ld a, [wRendererJobGeneration + 3]
	ld d, a
	ld a, [wRendererGeneration + 3]
	cp d
	jr nz, .stale
	ld a, [wRendererJobState]
	cp b
	jr nz, .invalid
	ld a, c
	ld [wRendererJobState], a
	restore_renderer_state_e
	and a
	ret
.stale
	ld a, [wRendererJobState]
	cp PENDING
	jr z, .cancel_stale
	cp PREPARED
	jr nz, .invalid
.cancel_stale
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, STALE_GENERATION
	ld [wRendererJobCancellationReason], a
.invalid
	restore_renderer_state_e
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	scf
	ret

; Input: A = cancellation reason.
CancelRendererJob::
	ld c, a
	select_renderer_state_e
	ld a, [wRendererJobState]
	cp PENDING
	jr z, .cancel
	cp PREPARED
	jr nz, .not_cancelled
.cancel
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, c
	ld [wRendererJobCancellationReason], a
	restore_renderer_state_e
	and a
	ret
.not_cancelled
	restore_renderer_state_e
	scf
	ret

; Input: A = expected owner.
AssertRendererWriteAllowed::
	ld c, a
	select_renderer_state_e
	ld a, [wRendererOwner]
	cp c
	jr nz, .violation
	ld a, [wRendererJobGeneration]
	ld d, a
	ld a, [wRendererGeneration]
	cp d
	jr nz, .violation
	ld a, [wRendererJobGeneration + 1]
	ld d, a
	ld a, [wRendererGeneration + 1]
	cp d
	jr nz, .violation
	ld a, [wRendererJobGeneration + 2]
	ld d, a
	ld a, [wRendererGeneration + 2]
	cp d
	jr nz, .violation
	ld a, [wRendererJobGeneration + 3]
	ld d, a
	ld a, [wRendererGeneration + 3]
	cp d
	jr nz, .violation
	restore_renderer_state_e
	and a
	ret
.violation
	restore_renderer_state_e
	ld a, FULL_COLOR_ASSERT_OWNER_OR_GENERATION
	call RecordRendererAssertion
	scf
	ret

GetRendererOwner::
	select_renderer_state_e
	ld a, [wRendererOwner]
	ld b, a
	restore_renderer_state_e
	ld a, b
	ret

IF DEF(FULL_COLOR_PHASE2_ACTIVE)
; The audit implementations live in the measured Phase 2 ROM window so this
; Phase 1 section keeps its current measured end at or before $452b.
ELSE
RunFullColorOwnershipVBlank::
	ret
ENDC

IF DEF(FULL_COLOR_PHASE2_ACTIVE)
ELSE
RouteRendererOwnershipVBlank::
IF DEF(_DEBUG)
	call PollFullColorDebugCommand
ENDC
	ret
ENDC

IF !DEF(FULL_COLOR_PHASE2_ACTIVE)
ClearVramBanked::
	ld hl, STARTOF(VRAM)
	ld bc, SIZEOF(VRAM)
	xor a
	jp FillMemory
ENDC

IF DEF(_DEBUG)
; Caller has selected SRAM bank 3. This uses the same atomic, stackless WRAM2
; primitive as the production ABI.
CopyRendererStateToDebugCarrier::
	select_renderer_state_e
	ld a, [wRendererOwner]
	ld [wFullColorDebugOwner], a
	ld a, [wRendererPhase]
	ld [wFullColorDebugPhase], a
	ld hl, wRendererGeneration
	ld de, wFullColorDebugGeneration
	ld b, 4
.generation
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .generation
	ld a, [wRendererAdmissionOpen]
	ld [wFullColorDebugAdmissionOpen], a
	ld a, [wRendererJobState]
	ld [wFullColorDebugJobState], a
	ld hl, wRendererJobGeneration
	ld de, wFullColorDebugJobGeneration
	ld b, 4
.job_generation
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .job_generation
	ld a, [wRendererJobCancellationReason]
	ld [wFullColorDebugCancellationReason], a
	restore_renderer_state_e
	ret

RecordRendererAssertion:
	push af
	push bc
	ld c, a
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BANK(wFullColorDebugStateStart)
	ld [rRAMB], a
	ld a, c
	ld [wFullColorDebugAssertionCode], a
	xor a
	ld [wFullColorDebugAssertionCode + 1], a
	ld [rRAMB], a
	ld [rRAMG], a
	pop bc
	pop af
	ret
ELSE
RecordRendererAssertion:
	ret
ENDC
