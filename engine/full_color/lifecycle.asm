; Guarded hostile-slice lifecycle ABI. These routines are deliberately banked;
; Home integration reaches them with farcall and pays no permanent Home cost.

FullColorLifecycleROMStart::

; Audit products use an owned WRAM2 protocol. They never open or poll the
; Phase 1 SRAM mailbox, whose write-only MBC state cannot be restored safely.
IF DEF(PHASE2_AUDIT)
PollFullColorPhase2DebugCommand::
	select_renderer_state_e
	ldh a, [hRendererStateSavedSVBK]
	ld [wFullColorDebugEntrySVBK], a
	ldh a, [hRendererStateSavedIE]
	ld [wFullColorDebugEntryIE], a
	ld hl, sp+0
	ld a, l
	ld [wFullColorDebugEntrySP], a
	ld a, h
	ld [wFullColorDebugEntrySP + 1], a
	ld a, [wFullColorDebugCommandPhase2]
	and a
	jp z, .finish
	ld b, a
	xor a
	ld [wFullColorDebugCommandPhase2], a
	ld a, b
	cp FULL_COLOR_DEBUG_COMMAND_CLEAR
	jr z, .clear
	cp FULL_COLOR_DEBUG_COMMAND_ARM
	jr z, .arm
	cp FULL_COLOR_DEBUG_COMMAND_SNAPSHOT
	jr z, .snapshot
	cp FULL_COLOR_DEBUG_COMMAND_ACK
	jr z, .ack
	ld a, FULL_COLOR_ASSERT_DEBUG_COMMAND
	ld [wFullColorDebugWriterState], a
	jr .finish
.clear
	ld hl, wFullColorDebugCarrierStart
	ld bc, FULL_COLOR_DEBUG_CARRIER_BYTES
	xor a
	call FillMemory
	ldh a, [hRendererStateSavedSVBK]
	ld [wFullColorDebugEntrySVBK], a
	ldh a, [hRendererStateSavedIE]
	ld [wFullColorDebugEntryIE], a
	ld hl, sp+0
	ld a, l
	ld [wFullColorDebugEntrySP], a
	ld a, h
	ld [wFullColorDebugEntrySP + 1], a
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_CLEAR
	ld [wFullColorDebugCheckpointPhase2], a
	jr .finish
.arm
	ld a, [wFullColorDebugProtocolState]
	and a
	jr z, .arm_valid
	cp FULL_COLOR_DEBUG_PROTOCOL_ACKNOWLEDGED
	jr nz, .protocol_error
.arm_valid
	ld a, FULL_COLOR_DEBUG_PROTOCOL_ARMED
	ld [wFullColorDebugProtocolState], a
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_ARMED
	ld [wFullColorDebugCheckpointPhase2], a
	jr .finish
.snapshot
	ld a, [wFullColorDebugProtocolState]
	cp FULL_COLOR_DEBUG_PROTOCOL_ARMED
	jr nz, .protocol_error
	call SnapshotFullColorPhase2DebugSelected
	ld a, FULL_COLOR_DEBUG_PROTOCOL_SNAPSHOTTED
	ld [wFullColorDebugProtocolState], a
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_SNAPSHOT
	ld [wFullColorDebugCheckpointPhase2], a
	jr .finish
.ack
	ld a, [wFullColorDebugProtocolState]
	cp FULL_COLOR_DEBUG_PROTOCOL_SNAPSHOTTED
	jr nz, .protocol_error
	ld a, FULL_COLOR_DEBUG_PROTOCOL_ACKNOWLEDGED
	ld [wFullColorDebugProtocolState], a
	ld a, FULL_COLOR_DEBUG_CHECKPOINT_ACKNOWLEDGED
	ld [wFullColorDebugCheckpointPhase2], a
	jr .finish
.protocol_error
	ld a, FULL_COLOR_ASSERT_DEBUG_COMMAND
	ld [wFullColorDebugWriterState], a
.finish
	ld hl, sp+0
	ld a, l
	ld [wFullColorDebugExitSP], a
	ld a, h
	ld [wFullColorDebugExitSP + 1], a
	ldh a, [hRendererStateSavedSVBK]
	ld [wFullColorDebugExitSVBK], a
	ldh a, [hRendererStateSavedIE]
	ld [wFullColorDebugExitIE], a
	restore_renderer_state_e
	ret

SnapshotFullColorPhase2DebugSelected::
	ld hl, wFullColorDebugSequence
	inc [hl]
	jr nz, .sequence_ready
	inc hl
	inc [hl]
.sequence_ready
	ld a, [wRendererOwner]
	ld [wFullColorDebugOwnerPhase], a
	ld a, [wRendererPhase]
	ld [wFullColorDebugOwnerPhase + 1], a
	ld hl, wRendererGeneration
	ld de, wFullColorDebugGenerationPhase2
	ld b, 4
.generation
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .generation
	ld a, [wFullColorRequestCount]
	ld [wFullColorDebugRequestState], a
	ld a, [wFullColorRequestCursor]
	ld [wFullColorDebugRequestState + 1], a
	ld a, [wFullColorLastAdmissionResult]
	ld [wFullColorDebugRequestState + 2], a
	ld a, [wFullColorTransitionCount]
	ld [wFullColorDebugRequestState + 3], a
	ld [wFullColorDebugWriterState + 1], a
	ld a, [wFullColorTransitionLog]
	ld [wFullColorDebugWriterState + 2], a
	ldh a, [hAutoBGTransferEnabled]
	ld [wFullColorDebugCommonState], a
	ldh a, [hVBlankCopyBGNumRows]
	ld [wFullColorDebugCommonState + 1], a
	ldh a, [hVBlankCopySize]
	ld [wFullColorDebugCommonState + 2], a
	ldh a, [hRedrawRowOrColumnMode]
	ld [wFullColorDebugCommonState + 3], a
	ld hl, wFullColorReconstructionItems
	ld de, wFullColorDebugFallbackState
	ld b, 4
.fallback
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .fallback
	ld a, [wFullColorAuthorityMap]
	ld [wFullColorDebugReconstructionState + 1], a
	ld a, [wFullColorAuthorityTileset]
	ld [wFullColorDebugReconstructionState + 2], a
	ld a, [wFullColorAuthorityY]
	ld [wFullColorDebugReconstructionState + 3], a
	ld a, [wFullColorAuthorityX]
	ld [wFullColorDebugReconstructionState + 4], a
	ret
ENDC

; Called with WRAM bank 2 selected during ownership initialization.
IF DEF(PHASE2_AUDIT)
InitFullColorPhase2LifecycleSelected::
	ld hl, wFullColorPhase2LifecycleStateStart
	ld bc, wFullColorPhase2LifecycleStateEnd - wFullColorPhase2LifecycleStateStart
	xor a
	jp FillMemory
ELSE
InitFullColorProductionLifecycleSelected::
	ld hl, wFullColorProductionLifecycleStateStart
	ld bc, wFullColorProductionLifecycleStateEnd - wFullColorProductionLifecycleStateStart
	xor a
	call FillMemory
	IF FULL_COLOR_PRODUCTION_ACTIVATED
	; InitRendererOwnership has already selected Yellow reconstruction closed.
	; Publish the matching hard-boot transition only after the lifecycle state
	; clear, so the title-screen reconstruction can record and complete it.
	ld a, TRANSITION_REQUIRED
	ld [wFullColorProductionTransitionStatus], a
	ld a, TRANSITION_ROUTE_RESET_YELLOW
	ld [wFullColorProductionTransitionRoute], a
	ld a, RENDERER_CONTEXT_BOOT_RESET
	ld [wFullColorProductionReturnContext], a
	ENDC
	ret
ENDC

; Copy the evolving 20x18 fixed-WRAM tile authority into producer-owned WRAM2
; and derive a separate attribute plane from independent tile-class authority.
; Bank 2 must be selected. Clobbers AF, BC, DE, HL.
SnapshotFullColorVisibleMapSelected::
	ld de, wTileMap
	ld hl, wFullColorProducerTiles
	ld bc, SCREEN_AREA
.tiles
	ld a, [de]
	ld [hli], a
	inc de
	dec bc
	ld a, b
	or c
	jr nz, .tiles
	ld de, wFullColorProducerTiles
	ld hl, wFullColorProducerAttributes
	ld bc, SCREEN_AREA
.attributes
	push bc
	push hl
	ld a, [de]
	ld c, a
	ld b, 0
	ld hl, FullColorOverworldTileAttributes
	add hl, bc
	ld a, [hl]
	pop hl
	ld [hli], a
	pop bc
	inc de
	dec bc
	ld a, b
	or c
	jr nz, .attributes
	ret

; Copy one byte from WRAM bank 1 into the guarded WRAM bank 2 snapshot. IE must
; already be masked. The value crosses banks in C, never through an aliased
; pointer, so bank-1 authority is never dereferenced while bank 2 is selected.
MACRO snapshot_wram1_byte
	ld a, 1
	ldh [rSVBK], a
	ld a, [\1]
	ld c, a
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, c
	ld [\2], a
ENDM

; No inputs. Returns carry clear. Clobbers AF, BC, HL. Preserves the caller's
; raw IE and SVBK. The snapshot is a closed 16-byte authority record.
SnapshotFullColorMapAuthority::
	select_renderer_state_e
	snapshot_wram1_byte wCurMap, wFullColorAuthorityMap
	snapshot_wram1_byte wCurMapTileset, wFullColorAuthorityTileset
	snapshot_wram1_byte wYCoord, wFullColorAuthorityY
	snapshot_wram1_byte wXCoord, wFullColorAuthorityX
	snapshot_wram1_byte wCurrentTileBlockMapViewPointer, wFullColorAuthorityBlockView
	snapshot_wram1_byte wCurrentTileBlockMapViewPointer + 1, wFullColorAuthorityBlockView + 1
	snapshot_wram1_byte wMapViewVRAMPointer, wFullColorAuthorityVRAMView
	snapshot_wram1_byte wMapViewVRAMPointer + 1, wFullColorAuthorityVRAMView + 1
	snapshot_wram1_byte wCurMapHeight, wFullColorAuthorityMapHeight
	snapshot_wram1_byte wCurMapWidth, wFullColorAuthorityMapWidth
	snapshot_wram1_byte wNumSprites, wFullColorAuthoritySpriteCount
	; Sprite authority lives in fixed WRAM0 and is safe with bank 2 selected.
	ld a, [wSpritePlayerStateData1]
	ld [wFullColorAuthorityPlayerPicture], a
	ld a, [wSpritePikachuStateData1]
	ld [wFullColorAuthorityPikachuPicture], a
	xor a
	ld [wFullColorAuthorityReserved], a
	ld [wFullColorAuthorityReserved + 1], a
	ld [wFullColorAuthorityReserved + 2], a
	restore_renderer_state_e
	and a
	ret

; No inputs. Clobbers AF. Clears every legacy pending visible-video enable.
; Call at both sides of a Yellow/full-color ownership boundary.
PoisonLegacyVideoRequests::
	xor a
	ldh [hAutoBGTransferEnabled], a
	ldh [hVBlankCopyBGSource], a
	ldh [hVBlankCopyBGSource + 1], a
	ldh [hVBlankCopyBGNumRows], a
	ldh [hVBlankCopySize], a
	ldh [hVBlankCopyDoubleSize], a
	ldh [hRedrawRowOrColumnMode], a
	ld [wUpdateSpritesEnabled], a
	ret

; No inputs. Returns carry set on an ownership transition failure. Clobbers
; AF, BC, HL. Snapshots WRAM1 authority before ownership selects bank 2.
BeginFullColorMapEntry::
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr z, .same_owner
	select_renderer_state_e
	xor a
	ld [wFullColorProductionTransitionStatus], a
	ld [wFullColorProductionTransitionRoute], a
	ld [wFullColorProductionReconstructionLedger], a
	ld [wFullColorProductionReconstructionLedger + 1], a
	restore_renderer_state_e
	call SnapshotFullColorMapAuthority
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	ret c
	call SelectFullColorOwnerForDiagnostic
	ret c
	select_renderer_state_e
	ld a, TRANSITION_REQUIRED
	ld [wFullColorProductionTransitionStatus], a
	ld a, TRANSITION_ROUTE_FULL_COLOR
	ld [wFullColorProductionTransitionRoute], a
	restore_renderer_state_e
.same_owner
	and a
	ret
	ELSE
	call SnapshotFullColorMapAuthority
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	ret c
	jp SelectFullColorOwnerForDiagnostic
	ENDC

IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
SelectYellowRendererForReconstruction::
	select_renderer_state_e
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp HANDOFF_TO_YELLOW
	jr nz, .invalid
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_RECONSTRUCTING
	ld [wRendererPhase], a
	clear_renderer_job
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	scf
	ret

ActivateYellowRenderer::
	select_renderer_state_e
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp YELLOW_RECONSTRUCTING
	jr nz, .invalid
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .invalid
	ld a, YELLOW_ACTIVE
	ld [wRendererPhase], a
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	scf
	ret

; Production reset seam used by reset/soft-reset roots once activation wiring is
; enabled.  It never publishes the intermediate Yellow owner as active.
ResetRendererOwnershipForReconstruction::
	select_renderer_state_e
	ld a, [wRendererJobState]
	cp COMMITTING
	jr nz, .commit_complete
	call CompleteDepartingRendererCommitSelected
	jp c, .generation_exhausted
.commit_complete
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
	call CancelFullColorSchedulerSelected
	advance_renderer_generation .generation_exhausted
	ld a, RENDERER_YELLOW
	ld [wRendererOwner], a
	ld a, YELLOW_RECONSTRUCTING
	ld [wRendererPhase], a
	clear_renderer_job
	xor a
	ld [wRendererAdmissionOpen], a
	ld [wFullColorProductionReconstructionLedger], a
	ld [wFullColorProductionReconstructionLedger + 1], a
	ld a, TRANSITION_REQUIRED
	ld [wFullColorProductionTransitionStatus], a
	ld a, TRANSITION_ROUTE_RESET_YELLOW
	ld [wFullColorProductionTransitionRoute], a
	ld a, RENDERER_CONTEXT_BOOT_RESET
	ld [wFullColorProductionReturnContext], a
	restore_renderer_state_e
	and a
	ret
.generation_exhausted
	xor a
	ld [wRendererAdmissionOpen], a
	restore_renderer_state_e
	scf
	ret

; Force a Yellow-owned destination only when ownership really changes.  The
; destination remains closed until CompleteYellowPresentation records its
; complete logical reconstruction and presentation barrier.
BeginForcedYellowPresentation::
	call GetRendererOwner
	cp RENDERER_YELLOW
	jr z, .same_owner
	select_renderer_state_e
	xor a
	ld [wFullColorProductionTransitionStatus], a
	ld [wFullColorProductionTransitionRoute], a
	ld [wFullColorProductionReconstructionLedger], a
	ld [wFullColorProductionReconstructionLedger + 1], a
	restore_renderer_state_e
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_YELLOW
	call BeginRendererHandoff
	ret c
	call SelectYellowRendererForReconstruction
	ret c
	select_renderer_state_e
	ld a, TRANSITION_REQUIRED
	ld [wFullColorProductionTransitionStatus], a
	ld a, TRANSITION_ROUTE_YELLOW
	ld [wFullColorProductionTransitionRoute], a
	restore_renderer_state_e
.same_owner
	and a
	ret

; A=renderer context recorded for the runtime-root return adapter.
SetFullColorProductionReturnContext::
	ld c, a
	select_renderer_state_e
	ld a, c
	ld [wFullColorProductionReturnContext], a
	restore_renderer_state_e
	and a
	ret

ResolveOrdinaryMapPresentation::
	call ResolveCurrentOrdinaryMapOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jp z, BeginFullColorMapEntry
	jp BeginForcedYellowPresentation

; Called at the last genuine hidden Yellow destination-reconstruction point.
; This records evidence only; activation and the presentation barrier remain
; exclusively owned by CompleteYellowPresentation.
RecordYellowReconstructionComplete::
	select_renderer_state_e
	ld a, [wFullColorProductionTransitionStatus]
	and a
	jr z, .same_owner
	cp TRANSITION_REQUIRED
	jr nz, .failed
	ld a, [wFullColorProductionTransitionRoute]
	cp TRANSITION_ROUTE_YELLOW
	jr z, .route_valid
	cp TRANSITION_ROUTE_RESET_YELLOW
	jr nz, .failed
.route_valid
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jr nz, .failed
	ld a, [wRendererPhase]
	cp YELLOW_RECONSTRUCTING
	jr nz, .failed
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .failed
	; Record each independently required destination item. This root is reached
	; only after the caller's genuine hidden reconstruction has completed; no
	; complete ledger value is ever fabricated by one store.
	ld hl, wFullColorProductionReconstructionLedger
	set 0, [hl] ; map/tileset overrides
	set 1, [hl] ; viewport destination
	set 2, [hl] ; tiles/replacements
	; The tilemap item is recorded only by a context-specific hidden VRAM
	; commit. In particular, a finished wTileMap is not presentation evidence.
	set 4, [hl] ; palettes
	set 5, [hl] ; OAM
	set 6, [hl] ; scheduler
	set 7, [hl] ; machine state
	restore_renderer_state_e
.same_owner
	and a
	ret
.failed
	restore_renderer_state_e
	scf
	ret

CompleteYellowPresentation::
	select_renderer_state_e
	ld a, [wFullColorProductionTransitionStatus]
	and a
	jr z, .same_owner
	cp TRANSITION_REQUIRED
	jr nz, .restore_failed
	ld a, [wFullColorProductionTransitionRoute]
	cp TRANSITION_ROUTE_YELLOW
	jr z, .route_valid
	cp TRANSITION_ROUTE_RESET_YELLOW
	jr nz, .restore_failed
.route_valid
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jr nz, .restore_failed
	ld a, [wRendererPhase]
	cp YELLOW_RECONSTRUCTING
	jr nz, .restore_failed
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .restore_failed
	ld a, [wFullColorProductionReconstructionLedger]
	cp LOW(FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE)
	jr nz, .restore_failed
	ld a, [wFullColorProductionReconstructionLedger + 1]
	cp HIGH(FULL_COLOR_RECONSTRUCTION_LEDGER_COMPLETE)
	jr nz, .restore_failed
	ld hl, wFullColorProductionYellowReconstructionBarrier
	inc [hl]
	restore_renderer_state_e
	call ActivateYellowRenderer
	ret c
	select_renderer_state_e
	xor a
	ld [wFullColorProductionTransitionStatus], a
	ld [wFullColorProductionTransitionRoute], a
	restore_renderer_state_e
.same_owner
	and a
	ret
.restore_failed
	restore_renderer_state_e
	scf
	ret
ENDC

; No inputs. Returns carry clear only after reconstruction crosses the single
; presentation barrier and admissions reopen. Clobbers AF, BC, HL.
CompleteFullColorMapReconstruction::
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	select_renderer_state_e
	ld a, [wFullColorProductionTransitionStatus]
	cp TRANSITION_REQUIRED
	jr nz, .same_owner
	ld a, [wFullColorProductionTransitionRoute]
	cp TRANSITION_ROUTE_FULL_COLOR
	jr nz, .failed
	restore_renderer_state_e
	jp ReconstructFullColorMapEntry
.same_owner
	restore_renderer_state_e
	and a
	ret
.failed
	restore_renderer_state_e
	scf
	ret
	ELSE
	jp ReconstructFullColorMapEntry
	ENDC

; Expand the complete 1bpp font authority into VRAM bank 0 while presentation
; is hidden. FarCopyDataDouble uses one byte of Yellow WRAM1 as its private ROM
; bank save, so select that bank explicitly without reopening interrupts, then
; return to the Phase 2 state bank. The caller's raw VRAM bank is preserved.
; Bank 2 must be selected. Clobbers AF, BC, DE, HL.
LoadFullColorFontGraphicsSelected:
	ldh a, [rVBK]
	push af
	xor a
	ldh [rVBK], a
	ld a, 1
	ldh [rSVBK], a
	ld hl, FontGraphics
	ld de, vFont
	ld bc, FontGraphicsEnd - FontGraphics
	ld a, BANK(FontGraphics)
	call FarCopyDataDouble
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	pop af
	ldh [rVBK], a
	ret

; No inputs. The caller must have begun map entry and kept LCD presentation
; hidden. Returns carry clear only after one complete BG palette plus the
; complete font graphics and 20x18 tile/attribute map have committed and
; admissions have reopened.
; Clobbers AF, BC, DE, HL.
ReconstructFullColorMapEntry::
	ldh a, [rLCDC]
	bit 7, a
	jp nz, .failed
	select_renderer_state_e
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jp nz, .restore_failed
	ld a, [wRendererPhase]
	cp OVERWORLD_RECONSTRUCTING
	jp nz, .restore_failed
	call LoadFullColorFontGraphicsSelected
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	ld hl, wFullColorProductionReconstructionLedger
	set 2, [hl] ; complete tile/replacement graphics now exist in VRAM
	ENDC
	call SnapshotFullColorVisibleMapSelected
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	ld hl, wFullColorProductionReconstructionLedger
	set 0, [hl] ; map/tileset authority was snapshotted
	set 1, [hl] ; exact viewport destination was snapshotted
	ENDC
	; Commit the independent 64-byte palette authority while presentation is
	; hidden. This is one complete payload, never a transition-only success.
	ld a, $80
	ldh [rBGPI], a
	ld hl, FullColorOverworldBGPalettes
	ld c, LOW(rBGPD)
	ld b, FULL_COLOR_PALETTE_EXTENT
.palette
	ld a, [hli]
	ldh [c], a
	dec b
	jr nz, .palette
	; Build the exact reconstruction descriptor and use the ordinary paired
	; preparation/commit machinery. Its source has already been snapshotted.
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld bc, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	xor a
	call FillMemory
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld a, FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED
	ld [hli], a
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ld [hli], a
	ld de, wRendererGeneration
	REPT 4
		ld a, [de]
		ld [hli], a
		inc de
	ENDR
	ld a, [wFullColorAuthorityVRAMView]
	ld [hli], a
	ld a, [wFullColorAuthorityVRAMView + 1]
	ld [hli], a
	ld a, LOW(wFullColorProducerTiles)
	ld [hli], a
	ld a, HIGH(wFullColorProducerTiles)
	ld [hli], a
	ld a, FULL_COLOR_RECONSTRUCTION_WIDTH
	ld [hli], a
	ld a, FULL_COLOR_RECONSTRUCTION_HEIGHT
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_BG_MAP | FULL_COLOR_RESOURCE_ATTRIBUTES
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(SCREEN_AREA)
	ld [hli], a
	ld a, HIGH(SCREEN_AREA)
	ld [hli], a
	ld a, LOW(SCREEN_AREA * 2)
	ld [hli], a
	ld a, HIGH(SCREEN_AREA * 2)
	ld [hli], a
	xor a
	ld [hli], a
	ld [hl], a
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld d, h
	ld e, l
	call ValidateFullColorRequestResourcesSelected
	jr c, .restore_failed
	ld hl, wFullColorSchedulerEnqueueDescriptor
	call PrepareFullColorPairedTransferSelected
	jr c, .restore_failed
	call CommitFullColorPairedTransferSelected
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	ld hl, wFullColorProductionReconstructionLedger
	set 3, [hl] ; paired tilemap/attribute destination committed
	set 6, [hl] ; scheduler preparation/commit barrier completed
	; The independent OBJ palette and finished OAM batch are synchronous hidden
	; reconstruction roots. They must exist before their ledger evidence and
	; before admissions reopen; first-active-VBlank work is too late.
	call CompleteFullColorProductionHiddenVisibleRootsSelected
	jr c, .restore_failed
	ld hl, wFullColorProductionReconstructionLedger
	set 4, [hl] ; complete BG and OBJ palettes committed
	set 5, [hl] ; shadow and hardware OAM committed
	set 7, [hl] ; hidden renderer machine state is complete
	ENDC
	; Exactly one reconstruction barrier is observable before activation.
IF DEF(PHASE2_AUDIT)
	ld hl, wFullColorDebugReconstructionState
ELSE
	ld hl, wFullColorProductionColorReconstructionBarrier
ENDC
	inc [hl]
	restore_renderer_state_e
	call ActivateFullColorOwnerForDiagnostic
	ret c
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
	select_renderer_state_e
	xor a
	ld [wFullColorProductionTransitionStatus], a
	ld [wFullColorProductionTransitionRoute], a
	restore_renderer_state_e
ENDC
	; BeginFullColorMapEntry poisoned sprite production before reconstruction.
	; Reopen it only after the hidden authoritative commit and successful owner
	; activation. The caller still owns the LCD-off boundary, so no active frame
	; can observe the old hidden batch between these two lifecycle points.
	ld a, 1
	ld [wUpdateSpritesEnabled], a
	and a
	ret
.restore_failed
	restore_renderer_state_e
.failed
	scf
	ret

; No inputs. Returns carry clear when Yellow owns before PartyMenuInit.
; Clobbers AF, BC, HL.
BeginFullColorPartyHandoff::
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_YELLOW
	call BeginRendererHandoff
	ret c
	call SelectYellowRenderer
	ret c
	select_renderer_state_e
	ld a, TRUE
	ld [wFullColorPartyReturnPending], a
	restore_renderer_state_e
	and a
	ret

; Farcall-safe party entry. Already-Yellow callers succeed idempotently without
; setting the Phase 2 return marker or advancing ownership generation.
EnsureFullColorPartyHandoff::
	call GetRendererOwner
	cp RENDERER_YELLOW
	jr z, .yellow
	jp BeginFullColorPartyHandoff
.yellow
	and a
	ret

; No inputs. Returns carry clear in OVERWORLD_RECONSTRUCTING. This poisons all
; prior presentation state and takes a fresh authority snapshot; it never
; restores captured VRAM. Clobbers AF, BC, HL.
ReturnFullColorFromParty::
	select_renderer_state_e
	ld a, [wFullColorPartyReturnPending]
	and a
	jr z, .not_party
	xor a
	ld [wFullColorPartyReturnPending], a
	restore_renderer_state_e
	call PoisonLegacyVideoRequests
	call SnapshotFullColorMapAuthority
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	ret c
	jp SelectFullColorOwnerForDiagnostic
.not_party
	restore_renderer_state_e
	scf
	ret

; Returns A=1 and carry clear only for a Yellow owner reached through the
; successful Phase 2 party handoff. A=0/carry set is ordinary Yellow flow.
IsFullColorPartyReturnPending::
	select_renderer_state_e
	ld a, [wFullColorPartyReturnPending]
	ld b, a
	restore_renderer_state_e
	ld a, b
	and a
	ret nz
	scf
	ret

; Generic bounded-slice exit. Idempotent when Yellow already owns. This never
; sets the party-return marker.
LeaveFullColorOverworldSlice::
	call GetRendererOwner
	cp RENDERER_YELLOW
	jr z, .done
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_YELLOW
	call BeginRendererHandoff
	ret c
	jp SelectYellowRenderer
.done
	and a
	ret

; Conventional farcall-safe ownership predicate. Carry clear means the current
; owner is the full-color overworld; carry set means every other owner. A is
; deliberately unspecified because Bankswitch restores the caller ROM bank
; through A after this routine returns.
IsFullColorOverworldOwnerFar::
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	ret z
	scf
	ret

; Overlay boundaries change only the exact ownership phase. They snapshot the
; evolving fixed-WRAM tile authority before returning, so later producers do
; not reconstruct from stale entry data.
EnterFullColorOverlay::
	ld c, OVERWORLD_ACTIVE
	ld b, OVERWORLD_OVERLAY
	jr ChangeFullColorOverlayPhase
ExitFullColorOverlay::
	ld c, OVERWORLD_OVERLAY
	ld b, OVERWORLD_ACTIVE
ChangeFullColorOverlayPhase:
	select_renderer_state_e
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .invalid
	ld a, [wRendererPhase]
	cp c
	jr nz, .invalid
	ld a, b
	ld [wRendererPhase], a
	call SnapshotFullColorVisibleMapSelected
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	scf
	ret

; Full-color close restores gameplay authority in WRAM, never from the legacy
; saved VRAM image. Presentation remains owned until the immutable replacement
; is queued; ExitFullColorOverlay then returns the lifecycle to ACTIVE.
PrepareCloseFullColorTextDisplay::
	xor a
	ldh [hAutoBGTransferEnabled], a
	ld hl, wSprite01StateData2OrigFacingDirection
	ld c, NUM_SPRITESTATEDATA_STRUCTS - 1
	ld de, SPRITESTATEDATA1_LENGTH
.restoreSpriteFacingDirectionLoop
	ld a, [hl]
	dec h
	ld [hl], a
	inc h
	add hl, de
	dec c
	jr nz, .restoreSpriteFacingDirectionLoop
	ld hl, wFontLoaded
	res BIT_FONT_LOADED, [hl]
	call LoadCurrentMapView
	call ExitFullColorOverlay
	jr c, .failed
.enqueueRestoredMap
	call EnqueueFullColorCurrentTileMapOverlayFar
	jr c, .enqueueRestoredMap
	ld a, $90
	ldh [hWY], a
	ret
.failed
	jr .failed

; HL points to a fixed-WRAM 20-byte descriptor. These class-exact wrappers
; return the scheduler result in A; carry is clear only for ACCEPTED/COALESCED.
MACRO exact_paired_submit
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp \1
	jr z, .valid\@
	ld a, DEFERRED
	scf
	ret
.valid\@
	jp AdmitFullColorRequest
ENDM

SubmitFullColorMapRow::
	exact_paired_submit FULL_COLOR_REQUEST_MAP_ROW_PAIRED
SubmitFullColorMapColumn::
	exact_paired_submit FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
SubmitFullColorMapConnection::
	exact_paired_submit FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED
SubmitFullColorMapOverlay::
	exact_paired_submit FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED
SubmitFullColorMapRectangle::
	exact_paired_submit FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED
SubmitFullColorAnimationReplacement::
	exact_paired_submit FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT

; No-input adapter for Home producers. Conventional farcall consumes A, B and
; HL, so rebuild the complete semantic overlay ABI after entering this bank.
; The destination comes from the closed map-authority snapshot in WRAM2.
EnqueueFullColorCurrentTileMapOverlayFar::
	select_renderer_state_e
	ld a, [wFullColorAuthorityVRAMView]
	ld e, a
	ld a, [wFullColorAuthorityVRAMView + 1]
	ld d, a
	restore_renderer_state_e
	ld hl, wTileMap
	ld b, SCREEN_WIDTH
	ld c, SCREEN_HEIGHT
	jp EnqueueFullColorMapOverlay

; No-input adapter for window-backed dialogue and start-menu producers. Window
; presentation is always the BG1 map at $9c00; it must not inherit the BG0
; destination captured by overworld map authority.
EnqueueFullColorWindowTileMapOverlayFar::
	ld de, vBGMap1
	ld hl, wTileMap
	ld b, SCREEN_WIDTH
	ld c, SCREEN_HEIGHT
	jp EnqueueFullColorMapOverlay

; Farcall-safe adapters for bank-1 producers. These contracts avoid relying on
; the conventional farcall register scratch used by the internal APIs.
; Map: C=identity, DE=attribute pointer within wShadowOAM. The farcall itself
; consumes A, B and HL, so derive the reverse object cursor from the surviving
; pointer only after entering this bank.
MapFullColorOAMAttributeFar::
	ld h, d
	ld l, e
	ld a, e
	sub LOW(wShadowOAM + 3)
	srl a
	srl a
	ld b, a
	ld a, OAM_COUNT
	sub b
	ld b, a
	ld a, c
	jp MapFullColorOAMAttribute

; Enqueue: DE=fixed-WRAM finished 160-byte OAM batch. Returns the ordinary
; EnqueueFullColorOAMBatch A/carry result.
EnqueueFullColorOAMBatchFar::
	ld h, d
	ld l, e
	jp EnqueueFullColorOAMBatch

; Carry clear means the owner consumed the VBlank. Yellow-visible writers must
; be skipped. Carry set means Yellow remains the VBlank owner.
FullColorVBlankOwnerConsumed::
IF DEF(PHASE2_AUDIT)
	call PollFullColorPhase2DebugCommand
	call RetryFullColorProducer
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .yellow
	; Ownership has been decided once. The producer assumes it and only builds
	; and enqueues; the scheduler below remains the sole shadow/DMA committer.
	farcall PrepareFullColorOAMDataForOwnedVBlank
	call RunFullColorOwnershipVBlank
	; Presentation follows the scheduler commit barrier in this same VBlank.
	; Yellow's route publishes these registers in Home and never reaches here.
	ldh a, [hSCX]
	ldh [rSCX], a
	ldh a, [hSCY]
	ldh [rSCY], a
.publishWindowY
	ldh a, [hWY]
	ldh [rWY], a
	and a
	ret
.yellow
	scf
	ret
ELSE
	; This audit integration route is deliberately inert in production Phase 1.
	scf
	ret
ENDC

IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
FullColorProductionTransitionFailed:
	call DisableLCD
.closed
	jr .closed

; Thin-root adapters keep the fixed Home bank bounded. They return only after
; the requested ownership boundary has succeeded; failures remain closed.
; Input C=renderer context. Conventional farcall clobbers A while selecting
; this bank, so Home roots must never try to pass policy context in A.
BeginForcedYellowPresentationRoot::
	; Keep LCD timing alive while legacy reconstruction runs: dialogue and battle
	; both use DelayFrame/Delay3 before reaching the final hidden commit. A real
	; Color departure blanks BG, window and OBJ visibility without clearing bit 7,
	; so palette/tile churn cannot leak through those closed timing frames.
	ld a, c
	call SetFullColorProductionReturnContext
	call ConcealForcedYellowPresentation
	call BeginForcedYellowPresentation
	jp c, FullColorProductionTransitionFailed
	ret

ConcealForcedYellowPresentation::
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	ret nz
	ldh a, [rLCDC]
	ld b, a
	select_renderer_state_e
	ld a, b
	ld [wFullColorProductionSavedLCDC], a
	restore_renderer_state_e
	ld a, b
	and ~(LCDC_WINDOW | LCDC_OBJS | LCDC_BG)
	ldh [rLCDC], a
	ret

RecordAndCompleteYellowPresentationRoot::
	select_renderer_state_e
	ld a, [wFullColorProductionTransitionStatus]
	ld b, a
	restore_renderer_state_e
	ld a, b
	and a
	ret z
	cp TRANSITION_REQUIRED
	jp nz, FullColorProductionTransitionFailed
	; All legacy DelayFrame work is now finished. Hide only at this final commit
	; boundary; calling DisableLCD earlier would deadlock its LY wait.
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	call nz, DisableLCD
	; Legacy VBlank is deliberately closed during reconstruction. Commit the
	; context's real BG/window destination synchronously before claiming its
	; ledger item; menu, dialogue and battle all use BG1, while map/title roots
	; have already performed their specialized hidden commits.
	call CommitYellowPresentationTileMapForContext
	jp c, FullColorProductionTransitionFailed
	; Every Yellow root reaches this adapter only after its final shadow-OAM
	; producer. Publish that completed batch while the destination is still
	; hidden, so the OAM ledger item describes hardware rather than future work.
	call hDMARoutine
	call RecordYellowReconstructionComplete
	jp c, FullColorProductionTransitionFailed
	call CompleteYellowPresentation
	jr c, FullColorProductionTransitionFailed
	; Only forced visible contexts own a saved concealment state. Map and title
	; roots arrived LCD-off and retain their caller-owned reveal points.
	select_renderer_state_e
	ld a, [wFullColorProductionSavedLCDC]
	ld b, a
	xor a
	ld [wFullColorProductionSavedLCDC], a
	restore_renderer_state_e
	ld a, b
	and a
	ret z
	ldh [rLCDC], a
	ret

; Returns carry clear after one complete Yellow palette/attribute destination
; and 20x18 bank-0 tilemap commit have been made (window contexts), or after
; verifying a context whose specialized caller already made its authoritative
; commit. The ledger bit is never set first.
CommitYellowPresentationTileMapForContext::
	select_renderer_state_e
	ld a, [wFullColorProductionTransitionStatus]
	and a
	jp z, .sameOwner
	cp TRANSITION_REQUIRED
	jp nz, .invalid
	ld a, [wFullColorProductionTransitionRoute]
	cp TRANSITION_ROUTE_YELLOW
	jr z, .routeValid
	cp TRANSITION_ROUTE_RESET_YELLOW
	jp nz, .invalid
.routeValid
	ld a, [wRendererOwner]
	cp RENDERER_YELLOW
	jp nz, .invalid
	ld a, [wRendererPhase]
	cp YELLOW_RECONSTRUCTING
	jp nz, .invalid
	ld a, [wRendererAdmissionOpen]
	and a
	jp nz, .invalid
	ld a, [wFullColorProductionReturnContext]
	ld b, a
	restore_renderer_state_e
	ld a, b
	cp RENDERER_CONTEXT_DIALOGUE
	jr z, .commitWindow
	cp RENDERER_CONTEXT_MENU
	jr z, .commitWindow
	cp RENDERER_CONTEXT_BATTLE
	jr z, .commitWindow
	cp RENDERER_CONTEXT_ORDINARY_MAP
	jr z, .recordCommit
	cp RENDERER_CONTEXT_STANDALONE
	jr z, .recordCommit
	cp RENDERER_CONTEXT_BOOT_RESET
	jr z, .recordCommit
	scf
	ret
.commitWindow
	; Preserve the caller's VRAM bank across both Yellow commits. The palette
	; command's attribute translator deliberately finishes in bank 0.
	ldh a, [rVBK]
	push af
	; Rebuild Yellow's context-owned CGB presentation from Yellow's logical
	; authority at the final hidden boundary.  Color's bank-1 attributes and
	; BG/OBJ palettes may still be resident here; a bank-0 tilemap copy alone
	; cannot make this destination complete.  RunPaletteCommand installs both
	; Yellow palette classes and translates the matching block packet into the
	; authoritative bank-1 attributes while the LCD is off.
	; Every forced context inherits the authoritative Yellow default selected by
	; its genuine destination root. Battle has advanced this from transition
	; black to SET_PAL_BATTLE before completion; menu and dialogue normally retain
	; SET_PAL_OVERWORLD from map setup.
	ld b, SET_PAL_DEFAULT
	call RunPaletteCommand
	; The LCD is off for a real Color departure. Select bank 0 explicitly after
	; the attribute translator before publishing the matching tile plane.
	xor a
	ldh [rVBK], a
	ld hl, wTileMap
	ld de, vBGMap1
	ld b, SCREEN_HEIGHT
.row
	push bc
	ld c, SCREEN_WIDTH
.tile
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .tile
	ld a, TILEMAP_WIDTH - SCREEN_WIDTH
	add e
	ld e, a
	jr nc, .noCarry
	inc d
.noCarry
	pop bc
	dec b
	jr nz, .row
	pop af
	ldh [rVBK], a
.recordCommit
	select_renderer_state_e
	ld hl, wFullColorProductionReconstructionLedger
	set 3, [hl] ; complete palette/attribute and tilemap destination committed
	restore_renderer_state_e
	and a
	ret
.sameOwner
	restore_renderer_state_e
	and a
	ret
.invalid
	restore_renderer_state_e
	scf
	ret

; Resolve current ordinary-map policy while hidden. Carry set returns Yellow;
; carry clear returns Color. Bankswitch preserves the route flag to Home.
BeginOrdinaryMapPresentationRoot::
	call DisableLCD
	ld a, RENDERER_CONTEXT_ORDINARY_MAP
	call SetFullColorProductionReturnContext
	call ResolveOrdinaryMapPresentation
	jp c, FullColorProductionTransitionFailed
	jp IsFullColorOverworldOwnerFar

CompleteOrdinaryMapPresentationRoot::
	call IsFullColorOverworldOwnerFar
	jp c, .yellow
	select_renderer_state_e
	ld a, [wRendererPhase]
	ld b, a
	restore_renderer_state_e
	ld a, b
	cp OVERWORLD_RECONSTRUCTING
	jr z, .reconstruct
	cp OVERWORLD_ACTIVE
	jp nz, FullColorProductionTransitionFailed
	; Same-owner destination replacement preserves generation but still submits
	; one authoritative complete rectangle; never reuse the stale connection
	; strip geometry left by the departing map.
	select_renderer_state_e
	call CancelFullColorSchedulerSelected
	restore_renderer_state_e
	call SnapshotFullColorMapAuthority
	select_renderer_state_e
	ld a, [wFullColorAuthorityVRAMView]
	ld e, a
	ld a, [wFullColorAuthorityVRAMView + 1]
	ld d, a
	restore_renderer_state_e
	ld hl, wTileMap
	ld b, SCREEN_WIDTH
	ld c, SCREEN_HEIGHT
	call EnqueueFullColorMapRectangle
	jp c, FullColorProductionTransitionFailed
	call CommitFullColorHiddenDestinationRoot
	jp c, FullColorProductionTransitionFailed
	ret
.reconstruct
	call SnapshotFullColorMapAuthority
	call CompleteFullColorMapReconstruction
	jp c, FullColorProductionTransitionFailed
	ret
.yellow
	jp RecordAndCompleteYellowPresentationRoot

; Seamless connections use one authoritative MAP_CONNECTION_PAIRED unit when
; Color ownership is preserved. A real owner transition already performs its
; one complete reconstruction and must not enqueue a duplicate connection.
CompleteConnectedMapPresentationRoot::
	call IsFullColorOverworldOwnerFar
	jp c, .yellow
	select_renderer_state_e
	ld a, [wRendererPhase]
	ld b, a
	restore_renderer_state_e
	ld a, b
	cp OVERWORLD_RECONSTRUCTING
	jp z, .reconstruct
	cp OVERWORLD_ACTIVE
	jp nz, FullColorProductionTransitionFailed
	select_renderer_state_e
	call CancelFullColorSchedulerSelected
	restore_renderer_state_e
	call SnapshotFullColorMapAuthority
	select_renderer_state_e
	ld a, [wFullColorAuthorityVRAMView]
	ld e, a
	ld a, [wFullColorAuthorityVRAMView + 1]
	ld d, a
	restore_renderer_state_e
	ld hl, wTileMap
	ld b, SCREEN_WIDTH
	ld c, 2
	; A low destination Y denotes a southbound connection: publish the bottom
	; two rows, not the stale top strip. Northbound entry keeps the top unit.
	select_renderer_state_e
	ld a, [wFullColorAuthorityY]
	push af
	restore_renderer_state_e
	pop af
	cp 2
	jr nc, .enqueue
	ld hl, wTileMap + SCREEN_WIDTH * (SCREEN_HEIGHT - 2)
	ld a, e
	add LOW(TILEMAP_WIDTH * (SCREEN_HEIGHT - 2))
	ld e, a
	ld a, d
	adc HIGH(TILEMAP_WIDTH * (SCREEN_HEIGHT - 2))
	and HIGH(TILEMAP_AREA - 1)
	or HIGH(vBGMap0)
	ld d, a
.enqueue
	call EnqueueFullColorMapConnection
	jp c, FullColorProductionTransitionFailed
	call CommitFullColorHiddenDestinationRoot
	jp c, FullColorProductionTransitionFailed
	ret
.reconstruct
	call SnapshotFullColorMapAuthority
	call CompleteFullColorMapReconstruction
	jp c, FullColorProductionTransitionFailed
	ret
.yellow
	jp RecordAndCompleteYellowPresentationRoot

; Same-owner hidden replacements must cross their scheduler commit barrier
; before Home can re-enable LCD. The queue was cancelled before admission, so
; exactly this one complete destination unit must drain synchronously.
CommitFullColorHiddenDestinationRoot:
	call RunFullColorOwnershipVBlank
	select_renderer_state_e
	ld a, [wFullColorRequestCount]
	ld b, a
	restore_renderer_state_e
	ld a, b
	and a
	ret z
	scf
	ret

; Farcall-safe movement producers. Each adapter reconstitutes the complete
; legacy strip ABI after the bank switch, admits one paired Color unit, and
; consumes Yellow's pending redraw only after the scheduler accepts it.
FullColorProductionLoadRedrawStrip:
	ldh a, [hRedrawRowOrColumnDest]
	ld e, a
	ldh a, [hRedrawRowOrColumnDest + 1]
	ld d, a
	ld hl, wRedrawRowOrColumnSrcTiles
	ret

FullColorProductionConsumeAcceptedRedraw:
	ret c
	xor a
	ldh [hRedrawRowOrColumnMode], a
	ret

SubmitFullColorProductionNorthRowFar::
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	call FullColorProductionLoadRedrawStrip
	call EnqueueFullColorMovementRowStrip
	jp FullColorProductionConsumeAcceptedRedraw
.wrong_owner
	scf
	ret

SubmitFullColorProductionSouthRowFar::
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	call FullColorProductionLoadRedrawStrip
	call EnqueueFullColorMovementRowStrip
	jp FullColorProductionConsumeAcceptedRedraw
.wrong_owner
	scf
	ret

SubmitFullColorProductionEastColumnFar::
	jr SubmitFullColorProductionMovementColumn

SubmitFullColorProductionWestColumnFar::
SubmitFullColorProductionMovementColumn:
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	call FullColorProductionLoadRedrawStrip
	call EnqueueFullColorMovementColumnStrip
	jp FullColorProductionConsumeAcceptedRedraw
.wrong_owner
	scf
	ret

; Production-only bank adapter. Build the finished legacy OAM authority without
; publishing it, then hand the immutable batch to the Color scheduler. The
; scheduler remains the sole shadow/hardware OAM commit owner.
PrepareFullColorProductionOAMForOwnedVBlank::
	ld a, 1
	ldh [hSpritePriority], a
	farcall PrepareOAMData.build
	ld de, wShadowOAM
	call EnqueueFullColorOAMBatchFar
	ret

; Called only after RouteRendererOwnershipVBlank has selected the active Color
; route.  Do not resolve ownership again: this is the one visible Color route.
RunFullColorProductionVBlank::
	call RetryFullColorProducer
	call ProduceFullColorProductionVBlankWork
	call PrepareFullColorProductionOAMForOwnedVBlank
	call RunFullColorOwnershipVBlank
	ldh a, [hSCX]
	ldh [rSCX], a
	ldh a, [hSCY]
	ldh [rSCY], a
	ldh a, [hWY]
	ldh [rWY], a
	ret

ENDC

EXPORT SnapshotFullColorMapAuthority, PoisonLegacyVideoRequests
EXPORT BeginFullColorMapEntry, CompleteFullColorMapReconstruction
EXPORT ReconstructFullColorMapEntry
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE)
EXPORT SelectYellowRendererForReconstruction, ActivateYellowRenderer
EXPORT ResetRendererOwnershipForReconstruction
EXPORT BeginForcedYellowPresentation, RecordYellowReconstructionComplete
EXPORT CompleteYellowPresentation
	EXPORT ResolveOrdinaryMapPresentation, SetFullColorProductionReturnContext
	EXPORT BeginForcedYellowPresentationRoot
	EXPORT ConcealForcedYellowPresentation
	EXPORT RecordAndCompleteYellowPresentationRoot
	EXPORT CommitYellowPresentationTileMapForContext
	EXPORT BeginOrdinaryMapPresentationRoot
	EXPORT CompleteOrdinaryMapPresentationRoot
	EXPORT CompleteConnectedMapPresentationRoot
	EXPORT SubmitFullColorProductionNorthRowFar
	EXPORT SubmitFullColorProductionSouthRowFar
	EXPORT SubmitFullColorProductionEastColumnFar
	EXPORT SubmitFullColorProductionWestColumnFar
	EXPORT PrepareFullColorProductionOAMForOwnedVBlank
	EXPORT RunFullColorProductionVBlank
ENDC
EXPORT BeginFullColorPartyHandoff, ReturnFullColorFromParty
EXPORT EnsureFullColorPartyHandoff
EXPORT IsFullColorPartyReturnPending, LeaveFullColorOverworldSlice
EXPORT IsFullColorOverworldOwnerFar
EXPORT EnterFullColorOverlay, ExitFullColorOverlay
EXPORT SubmitFullColorMapRow, SubmitFullColorMapColumn
EXPORT SubmitFullColorMapConnection, SubmitFullColorMapOverlay
EXPORT SubmitFullColorMapRectangle, SubmitFullColorAnimationReplacement
EXPORT EnqueueFullColorCurrentTileMapOverlayFar
EXPORT EnqueueFullColorWindowTileMapOverlayFar
EXPORT MapFullColorOAMAttributeFar, EnqueueFullColorOAMBatchFar
EXPORT FullColorVBlankOwnerConsumed
IF DEF(PHASE2_AUDIT)
EXPORT InitFullColorPhase2LifecycleSelected
ELSE
EXPORT InitFullColorProductionLifecycleSelected
ENDC
