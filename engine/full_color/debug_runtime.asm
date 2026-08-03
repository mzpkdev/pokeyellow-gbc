IF DEF(_DEBUG)

IF DEF(PHASE2_AUDIT)
; The Phase 2 audit protocol lives with the added-only lifecycle roots. This
; file retains only the pre-existing debug product's Phase 1 SRAM protocol.
ELSE

; Poll one debug-only SRAM mailbox from the production VBlank route. Commands
; are accepted once, cleared before execution, and finish at a stable checkpoint.
PollFullColorDebugCommand::
	ldh a, [hFullColorDebugCommandPending]
	and a
	ret z
	xor a
	ldh [hFullColorDebugCommandPending], a
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BANK(wFullColorDebugStateStart)
	ld [rRAMB], a
	ld a, [wFullColorDebugCommand]
	ld b, a
	xor a
	ld [wFullColorDebugCommand], a
	ld [rRAMB], a
	ld [rRAMG], a
	ld a, b
	and a
	ret z
	cp FULL_COLOR_DEBUG_COMMAND_OWNERSHIP_REPLACEMENT
	jp z, RunPhase1OwnershipReplacementScenario
	cp FULL_COLOR_DEBUG_COMMAND_RESTORE_YELLOW
	jp z, RestoreYellowAfterPhase1Diagnostic
	ld a, FULL_COLOR_ASSERT_DEBUG_COMMAND
	call RecordRendererAssertion
	ret

RunPhase1OwnershipReplacementScenario::
; Enter through the same ordered ownership handoff used by production callers.
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	ret c
	call SelectFullColorOwnerForDiagnostic
	ret c
	call ActivateFullColorOwnerForDiagnostic
	ret c

; The canonical runtime case uses old generation 7 and replacement generation
; 8. Boot begins at 1 and the handoff established generation 2.
	ld d, 5
.advance_to_old_generation
	call AdvanceRendererGeneration
	ret c
	dec d
	jr nz, .advance_to_old_generation

	call OpenFullColorDebugCarrier
	call AdmitRendererDiagnosticJob
	ld [wFullColorDebugLastRequestResult], a
	jp c, .failed
	ld a, PENDING
	ld b, FULL_COLOR_DEBUG_JOB_OLD
	ld c, CANCELLATION_NONE
	ld d, 0
	call AppendFullColorOwnershipTrace

	call SetRendererJobPrepared
	jp c, .failed
	ld a, PREPARED
	ld b, FULL_COLOR_DEBUG_JOB_OLD
	ld c, CANCELLATION_NONE
	ld d, 0
	call AppendFullColorOwnershipTrace

	ld a, SUPERSEDED
	call CancelRendererJob
	jp c, .failed
	ld a, CANCELLED
	ld b, FULL_COLOR_DEBUG_JOB_OLD
	ld c, SUPERSEDED
	ld d, 0
	ld a, [FullColorDebugMutationCancellation]
	and a
	jr z, .old_cancel_ready
	ld c, CANCELLATION_NONE
.old_cancel_ready
	ld a, [FullColorDebugMutationWrite]
	and a
	jr z, .old_cancel_ready_to_append
	ld d, 1
.old_cancel_ready_to_append
	ld a, CANCELLED
	call AppendFullColorOwnershipTrace

	call AdvanceRendererGeneration
	jp c, .failed
	call AdmitRendererDiagnosticJob
	ld [wFullColorDebugLastRequestResult], a
	jp c, .failed
	ld a, PENDING
	ld b, FULL_COLOR_DEBUG_JOB_REPLACEMENT
	ld c, CANCELLATION_NONE
	ld d, 0
	call AppendFullColorOwnershipTrace

	call SetRendererJobPrepared
	jp c, .failed
	ld a, PREPARED
	ld b, FULL_COLOR_DEBUG_JOB_REPLACEMENT
	ld c, CANCELLATION_NONE
	ld d, 0
	call AppendFullColorOwnershipTrace

	call SetRendererJobCommitting
	jp c, .failed
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	call AssertRendererWriteAllowed
	jp c, .failed
	ld a, COMMITTING
	ld b, FULL_COLOR_DEBUG_JOB_REPLACEMENT
	ld c, CANCELLATION_NONE
	ld d, 1 ; ownership_generation commit, not a visible-resource write
	call AppendFullColorOwnershipTrace

	call CompleteRendererJob
	jp c, .failed
	ld a, COMPLETE
	ld e, a
	ld a, [FullColorDebugMutationCompletion]
	and a
	ld a, e
	jr z, .completion_ready
	ld a, COMMITTING
.completion_ready
	ld b, FULL_COLOR_DEBUG_JOB_REPLACEMENT
	ld c, CANCELLATION_NONE
	ld d, 0
	call AppendFullColorOwnershipTrace

	call CopyRendererStateToDebugCarrier
	ld a, [FullColorDebugMutationOwner]
	and a
	jr z, .final_owner_ready
	xor a
	ld [wFullColorDebugOwner], a
.final_owner_ready
	ld a, [FullColorDebugMutationPhase]
	and a
	jr z, .final_phase_ready
	xor a
	ld [wFullColorDebugPhase], a
.final_phase_ready
	ld a, [FullColorDebugMutationGeneration]
	and a
	jr z, .generation_ready
	ld hl, wFullColorDebugGeneration
	dec [hl]
.generation_ready
	ld a, [FullColorDebugMutationVideo]
	and a
	jr z, .video_ready
	ld hl, wShadowOAM
	inc [hl]
.video_ready
	ld a, FULL_COLOR_DEBUG_WRITER_OWNERSHIP
	ld [wFullColorDebugWriterID], a
	ld [wFullColorDebugLastWriterID], a
	ld a, FULL_COLOR_DEBUG_COMMIT_OWNERSHIP_REPLACEMENT
	ld [wFullColorDebugCommitUnitID], a
	ld a, FULL_COLOR_DEBUG_RESOURCE_OWNERSHIP_GENERATION
	ld [wFullColorDebugLastResourceID], a
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_OWNERSHIP_REPLACEMENT
	ld [wFullColorDebugCheckpoint], a
	jp CloseFullColorDebugCarrier
.failed
	ld a, FULL_COLOR_ASSERT_DEBUG_COMMAND
	call RecordRendererAssertion
	jp CloseFullColorDebugCarrier

RestoreYellowAfterPhase1Diagnostic::
	ld a, HANDOFF_TO_YELLOW
	call BeginRendererHandoff
	ret c
	call SelectYellowRenderer
	ret c
	call OpenFullColorDebugCarrier
	call CopyRendererStateToDebugCarrier
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_RESTORED_YELLOW
	ld [wFullColorDebugCheckpoint], a
	jp CloseFullColorDebugCarrier

OpenFullColorDebugCarrier:
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BANK(wFullColorDebugStateStart)
	ld [rRAMB], a
	ret

CloseFullColorDebugCarrier:
	xor a
	ld [rRAMB], a
	ld [rRAMG], a
	ret

; Input: A=job state, B=job ID, C=cancellation, D=flags.
; Appends one 33-byte layout-v2 record. The mailbox is single-use and produces
; seven records, but the count/index checks keep the physical ring bounded.
AppendFullColorOwnershipTrace:
	ld [wFullColorDebugTraceScratchState], a
	ld a, b
	ld [wFullColorDebugTraceScratchJobID], a
	ld a, c
	ld [wFullColorDebugTraceScratchCancellation], a
	ld a, d
	ld [wFullColorDebugTraceScratchFlags], a
	call CopyRendererStateToDebugCarrier
	ld a, [FullColorDebugMutationOwner]
	and a
	jr z, .trace_owner_ready
	xor a
	ld [wFullColorDebugOwner], a
.trace_owner_ready
	ld a, [FullColorDebugMutationPhase]
	and a
	jr z, .trace_phase_ready
	xor a
	ld [wFullColorDebugPhase], a
.trace_phase_ready
	ld a, [FullColorDebugMutationGeneration]
	and a
	jr z, .trace_generation_ready
	ld hl, wFullColorDebugGeneration
	dec [hl]
.trace_generation_ready

	ld a, [wFullColorDebugTraceNextWrite + 1]
	and a
	ret nz
	ld a, [wFullColorDebugTraceNextWrite]
	cp FULL_COLOR_DEBUG_TRACE_CAPACITY
	ret nc
	ld e, a
	ld d, 0
	ld hl, wFullColorDebugTraceRecords
	ld bc, FULL_COLOR_DEBUG_TRACE_RECORD_SIZE
.seek
	ld a, e
	and a
	jr z, .record
	add hl, bc
	dec e
	jr .seek
.record
	; sequence (u32)
	ld a, [wFullColorDebugTraceNextWrite]
	ld [hli], a
	xor a
	ld [hli], a
	ld [hli], a
	ld [hli], a
	; frame (u32), one bounded VBlank command
	ld [hli], a
	ld [hli], a
	ld [hli], a
	ld [hli], a
	; active generation and job generation
	ld de, wFullColorDebugGeneration
	call CopyFourDebugBytes
	ld de, wFullColorDebugJobGeneration
	call CopyFourDebugBytes
	; owner, phase, job owner, state, cancellation
	ld a, [wFullColorDebugOwner]
	ld [hli], a
	ld a, [wFullColorDebugPhase]
	ld [hli], a
	ld a, [wFullColorDebugOwner]
	ld [hli], a
	ld a, [wFullColorDebugTraceScratchState]
	ld [hli], a
	ld a, [wFullColorDebugTraceScratchCancellation]
	ld [hli], a
	; writer, commit, resource, job, request, flags (six u16 values)
	ld a, FULL_COLOR_DEBUG_WRITER_OWNERSHIP
	call WriteDebugWordA
	ld a, FULL_COLOR_DEBUG_COMMIT_OWNERSHIP_REPLACEMENT
	call WriteDebugWordA
	ld a, FULL_COLOR_DEBUG_RESOURCE_OWNERSHIP_GENERATION
	call WriteDebugWordA
	ld a, [wFullColorDebugTraceScratchJobID]
	call WriteDebugWordA
	ld a, FULL_COLOR_DEBUG_REQUEST_OWNERSHIP_REPLACEMENT
	call WriteDebugWordA
	ld a, [wFullColorDebugTraceScratchFlags]
	call WriteDebugWordA

	ld hl, wFullColorDebugTraceCount
	inc [hl]
	ld hl, wFullColorDebugTraceNextWrite
	inc [hl]
	ret

CopyFourDebugBytes:
	ld b, 4
.loop
	ld a, [de]
	inc de
	ld [hli], a
	dec b
	jr nz, .loop
	ret

WriteDebugWordA:
	ld [hli], a
	xor a
	ld [hli], a
	ret

; Patchable debug-ROM mutation controls. Every clean-ROM byte is zero; changing
; exactly one byte to a nonzero value enables its named negative-test fault.
; These are data, never self-modifying code, and exist only in debug builds.
FullColorDebugMutationOwner:: db 0
FullColorDebugMutationPhase:: db 0
FullColorDebugMutationGeneration:: db 0
FullColorDebugMutationCancellation:: db 0
FullColorDebugMutationWrite:: db 0
FullColorDebugMutationCompletion:: db 0
FullColorDebugMutationVideo:: db 0

EXPORT FullColorDebugMutationOwner
EXPORT FullColorDebugMutationPhase
EXPORT FullColorDebugMutationGeneration
EXPORT FullColorDebugMutationCancellation
EXPORT FullColorDebugMutationWrite
EXPORT FullColorDebugMutationCompletion
EXPORT FullColorDebugMutationVideo

ENDC
ENDC
