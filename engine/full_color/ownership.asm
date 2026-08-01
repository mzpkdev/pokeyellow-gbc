; Phase 1 renderer ownership core.
; This module is the sole bank-selection ABI for wRenderer* production state.
; It intentionally performs no palette, tilemap, attribute, OAM, or other
; visible-resource write.

MACRO open_renderer_state
	ldh a, [rSVBK]
	push af
	ld a, PHASE1_SELECTED_WRAM_BANK
	ldh [rSVBK], a
ENDM

MACRO close_renderer_state
	pop af
	ldh [rSVBK], a
ENDM

InitRendererOwnership::
	open_renderer_state
	xor a
	ld hl, wRendererStateStart
	ld bc, PHASE1_OWNERSHIP_STATE_BYTES
	call FillMemory
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_ACTIVE
	ld [wRendererPhase], a
	ld a, 1
	ld [wRendererGeneration], a
	ld [wRendererAdmissionOpen], a
	ld a, RENDERER_JOB_NONE
	ld [wRendererJobState], a
	ld a, CANCELLATION_NONE
	ld [wRendererJobCancellationReason], a
	close_renderer_state
	and a
	ret

SoftResetRendererOwnership::
	call ResetRendererOwnership
	jr c, .commit_in_progress
	; Init preserves this one HRAM byte until WriteDMACodeToHRAM. That hook
	; therefore keeps the fresh reset generation instead of reinitializing it.
	ld a, 1
	ldh [hSoftReset], a
	call StopAllSounds
	call GBPalWhiteOut
	ld c, 32
	call DelayFrames
	jp SoftResetInit
.commit_in_progress
	jr .commit_in_progress

; Reset is atomic with respect to visible commits: a COMMITTING job makes the
; reset fail with carry before any ownership state is changed.
ResetRendererOwnership::
	open_renderer_state
	ld a, [wRendererJobState]
	cp COMMITTING
	jr z, .commit_in_progress
	xor a
	ld [wRendererAdmissionOpen], a
	ld a, RESET
	call CancelRendererJobInOpenState
	call AdvanceRendererGenerationInOpenState
	jr c, .generation_exhausted
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_ACTIVE
	ld [wRendererPhase], a
	call ClearRendererJobInOpenState
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
.done
	close_renderer_state
	and a
	ret
.generation_exhausted
	close_renderer_state
	scf
	ret
.commit_in_progress
	ld a, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

; Input: A = HANDOFF_TO_OVERWORLD or HANDOFF_TO_YELLOW.
; Closes admission, cancels cancellable work, then establishes a fresh token.
BeginRendererHandoff::
	ld c, a
	open_renderer_state
	ld a, c
	cp HANDOFF_TO_OVERWORLD
	jr z, .validate_overworld
	cp HANDOFF_TO_YELLOW
	jr nz, .invalid
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp OVERWORLD_ACTIVE
	jr z, .validated
	cp OVERWORLD_OVERLAY
	jr nz, .invalid
	jr .validated
.validate_overworld
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
	push bc
	ld a, HANDOFF
	call CancelRendererJobInOpenState
	pop bc
	ld a, c
	ld [wRendererPhase], a
	call AdvanceRendererGenerationInOpenState
	jr c, .generation_exhausted
	close_renderer_state
	and a
	ret
.generation_exhausted
	close_renderer_state
	scf
	ret
.invalid
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret
.commit_in_progress
	ld a, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

; Input: A = arriving owner, C = arriving phase.
; The generation has already been invalidated by BeginRendererHandoff.
CompleteRendererHandoff::
	ld b, a
	open_renderer_state
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	; Generation zero is permanently exhausted. A delayed selector must never
	; reopen admission after BeginRendererHandoff wrapped the token space.
	ld hl, wRendererGeneration
	ld a, [hli]
	ld d, a
	ld a, [hli]
	or d
	ld d, a
	ld a, [hli]
	or d
	ld d, a
	ld a, [hl]
	or d
	jr z, .invalid
	ld a, b
	cp RENDERER_YELLOW
	jr z, .validate_yellow
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
	jr .validated
.validate_yellow
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp HANDOFF_TO_YELLOW
	jr nz, .invalid
	ld a, c
	cp YELLOW_ACTIVE
	jr nz, .invalid
.validated
	ld a, b
	ld [wRendererOwner], a
	ld a, c
	ld [wRendererPhase], a
	push bc
	call ClearRendererJobInOpenState
	pop bc
	ld a, c
	cp OVERWORLD_RECONSTRUCTING
	jr z, .keep_admission_closed
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	close_renderer_state
	and a
	ret
.keep_admission_closed
	xor a
	ld [wRendererAdmissionOpen], a
	close_renderer_state
	and a
	ret
.invalid
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	close_renderer_state
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

; Phase 1 has no reconstruction writer. This diagnostic boundary represents
; the later renderer's completed initialization and is the only path that
; opens admission after an overworld arrival.
ActivateFullColorOwnerForDiagnostic::
	open_renderer_state
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp OVERWORLD_RECONSTRUCTING
	jr nz, .invalid
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	ld hl, wRendererGeneration
	ld a, [hli]
	ld c, a
	ld a, [hli]
	or c
	ld c, a
	ld a, [hli]
	or c
	ld c, a
	ld a, [hl]
	or c
	jr z, .invalid
	ld a, OVERWORLD_ACTIVE
	ld [wRendererPhase], a
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	close_renderer_state
	and a
	ret
.invalid
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

AdvanceRendererGeneration::
	open_renderer_state
	ld a, [wRendererJobState]
	cp COMMITTING
	jr z, .commit_in_progress
	ld a, STALE_GENERATION
	call CancelRendererJobInOpenState
	call AdvanceRendererGenerationInOpenState
	jr c, .generation_exhausted
	close_renderer_state
	and a
	ret
.generation_exhausted
	close_renderer_state
	scf
	ret
.commit_in_progress
	ld a, FULL_COLOR_ASSERT_COMMIT_IN_PROGRESS
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

AdvanceRendererGenerationInOpenState:
; Generation zero is the permanent exhaustion sentinel.
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
	jr z, .exhausted

	ld hl, wRendererGeneration
	ld b, 4
.increment
	inc [hl]
	jr nz, .advanced
	inc hl
	dec b
	jr nz, .increment
.exhausted
	xor a
	ld [wRendererAdmissionOpen], a
	ld a, FULL_COLOR_ASSERT_GENERATION_EXHAUSTED
	call RecordRendererAssertion
	scf
	ret
.advanced
	and a
	ret

; Creates the single Phase 1 diagnostic job under the active generation.
; Returns carry when admission is closed or nonterminal work already exists.
AdmitRendererDiagnosticJob::
	open_renderer_state
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
	ld hl, wRendererGeneration
	ld de, wRendererJobGeneration
	ld b, 4
.copy_generation
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_generation
	ld a, PENDING
	ld [wRendererJobState], a
	ld a, CANCELLATION_NONE
	ld [wRendererJobCancellationReason], a
	close_renderer_state
	ld a, ACCEPTED
	and a
	ret
.rejected
	close_renderer_state
	ld a, DEFERRED
	scf
	ret

SetRendererJobPrepared::
	ld a, PENDING
	ld c, PREPARED
	jp TransitionRendererJob

SetRendererJobCommitting::
	ld a, PREPARED
	ld c, COMMITTING
	jp TransitionRendererJob

CompleteRendererJob::
	ld a, COMMITTING
	ld c, COMPLETE
	jp TransitionRendererJob

; Input: A = required current state, C = next state.
TransitionRendererJob:
	ld b, a
	open_renderer_state
	push bc
	call CompareRendererJobGenerationInOpenState
	pop bc
	jr nz, .stale
	ld a, [wRendererJobState]
	cp b
	jr nz, .invalid
	ld a, c
	ld [wRendererJobState], a
	close_renderer_state
	and a
	ret
.stale
	ld a, STALE_GENERATION
	call CancelRendererJobInOpenState
	jr .invalid
.invalid
	ld a, FULL_COLOR_ASSERT_ILLEGAL_JOB_TRANSITION
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

; Input: A = cancellation reason. Only PENDING/PREPARED may cancel.
CancelRendererJob::
	ld c, a
	open_renderer_state
	ld a, c
	call CancelRendererJobInOpenState
	jr c, .not_cancelled
	close_renderer_state
	and a
	ret
.not_cancelled
	close_renderer_state
	scf
	ret

CancelRendererJobInOpenState:
	ld c, a
	ld a, [wRendererJobState]
	cp PENDING
	jr z, .cancel
	cp PREPARED
	jr z, .cancel
	scf
	ret
.cancel
	ld a, CANCELLED
	ld [wRendererJobState], a
	ld a, c
	ld [wRendererJobCancellationReason], a
	and a
	ret

ClearRendererJobInOpenState:
	ld a, RENDERER_JOB_NONE
	ld [wRendererJobState], a
	ld a, CANCELLATION_NONE
	ld [wRendererJobCancellationReason], a
	xor a
	ld hl, wRendererJobGeneration
	ld bc, 4
	jp FillMemory

CompareRendererJobGenerationInOpenState:
	ld hl, wRendererGeneration
	ld de, wRendererJobGeneration
	ld b, 4
.compare
	ld a, [de]
	cp [hl]
	ret nz
	inc de
	inc hl
	dec b
	jr nz, .compare
	ret

; Input: A = expected owner. Checks owner before all four generation bytes.
AssertRendererWriteAllowed::
	ld c, a
	open_renderer_state
	ld a, [wRendererOwner]
	cp c
	jr nz, .violation
	call CompareRendererJobGenerationInOpenState
	jr nz, .violation
	close_renderer_state
	and a
	ret
.violation
	ld a, FULL_COLOR_ASSERT_OWNER_OR_GENERATION
	call RecordRendererAssertion
	close_renderer_state
	scf
	ret

GetRendererOwner::
	open_renderer_state
	ld a, [wRendererOwner]
	ld b, a
	close_renderer_state
	ld a, b
	ret

; Phase 1 deliberately has no renderer work to perform during VBlank.
RunFullColorOwnershipVBlank::
	ret

RouteRendererOwnershipVBlank::
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	ret nz
	jp RunFullColorOwnershipVBlank

; Banked copy of the original Home helper, moved only to keep the fixed bank
; within its pre-existing bound after the ownership hooks were added.
ClearVramBanked::
	ld hl, STARTOF(VRAM)
	ld bc, SIZEOF(VRAM)
	xor a
	jp FillMemory

IF DEF(_DEBUG)
; Caller has enabled and selected the debug SRAM carrier bank. This routine
; mirrors production ownership state; it never synthesizes observed values.
CopyRendererStateToDebugCarrier::
	open_renderer_state
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
	ld a, [wRendererJobCancellationReason]
	ld [wFullColorDebugCancellationReason], a
	close_renderer_state
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
