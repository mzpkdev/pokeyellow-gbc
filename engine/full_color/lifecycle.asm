; Guarded hostile-slice lifecycle ABI. These routines are deliberately banked;
; Home integration reaches them with farcall and pays no permanent Home cost.

FullColorLifecycleROMStart::

; Audit products use an owned WRAM2 protocol. They never open or poll the
; Phase 1 SRAM mailbox, whose write-only MBC state cannot be restored safely.
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

; Called with WRAM bank 2 selected during ownership initialization.
InitFullColorPhase2LifecycleSelected::
	ld hl, wFullColorPhase2LifecycleStateStart
	ld bc, wFullColorPhase2LifecycleStateEnd - wFullColorPhase2LifecycleStateStart
	xor a
	jp FillMemory

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
	ld hl, FullColorCanaryOverworldTileClasses
	add hl, bc
	ld a, [hl]
	and 7
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
IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	call InitFullColorPhase2LifecycleSelected
	restore_renderer_state_e
ENDC
	call SnapshotFullColorMapAuthority
	call PoisonLegacyVideoRequests
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	ret c
	jp SelectFullColorOwnerForDiagnostic

; No inputs. Returns carry clear only after reconstruction crosses the single
; presentation barrier and admissions reopen. Clobbers AF, BC, HL.
CompleteFullColorMapReconstruction::
	jp ReconstructFullColorMapEntry

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
IF !DEF(PHASE2_AUDIT)
	call MeasureFullColorCanaryPaletteRowsSelected
	ld a, FULL_COLOR_TIMING_ROW_RECONSTRUCTION
	call BeginFullColorRuntimeTimingSampleSelected
	push af
ENDC
	call LoadFullColorFontGraphicsSelected
	call SnapshotFullColorVisibleMapSelected
	; Commit the independent 64-byte palette authority while presentation is
	; hidden. This is one complete payload, never a transition-only success.
	IF DEF(PHASE2_AUDIT)
	ld a, $80
	ldh [rBGPI], a
	ld hl, FullColorCanaryBGPalettes
	ld c, LOW(rBGPD)
	ld b, FULL_COLOR_PALETTE_EXTENT
.palette
	ld a, [hli]
	ldh [c], a
	dec b
	jr nz, .palette
	ELSE
	call CommitFullColorCanaryCombinedPalettesSelected
	ENDC
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
IF !DEF(PHASE2_AUDIT)
	jr c, .timed_restore_failed
ELSE
	jr c, .restore_failed
ENDC
	ld hl, wFullColorSchedulerEnqueueDescriptor
	call PrepareFullColorPairedTransferSelected
IF !DEF(PHASE2_AUDIT)
	jr c, .timed_restore_failed
ELSE
	jr c, .restore_failed
ENDC
	call CommitFullColorPairedTransferSelected
	; Exactly one reconstruction barrier is observable before activation.
	ld hl, wFullColorDebugReconstructionState
	inc [hl]
IF !DEF(PHASE2_AUDIT)
	pop af
	jr c, .timing_done
	call EndFullColorRuntimeTimingSampleSelected
.timing_done
ENDC
	restore_renderer_state_e
	call ActivateFullColorOwnerForDiagnostic
	ret c
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
IF !DEF(PHASE2_AUDIT)
.timed_restore_failed
	pop af
	xor a
	ld [wFullColorRuntimeTimingActive], a
	jr .restore_failed
ENDC

IF !DEF(PHASE2_AUDIT)
; Capture the three palette rows independently before the complete hidden
; reconstruction sample. Repeating the writes is harmless while LCD is off
; and keeps every canonical row bound to its exact hardware operation.
MeasureFullColorCanaryPaletteRowsSelected:
	ld a, FULL_COLOR_TIMING_ROW_PALETTE_BG
	call BeginFullColorRuntimeTimingSampleSelected
	push af
	call CommitFullColorCanaryBGPaletteSelected
	pop af
	call nc, EndFullColorRuntimeTimingSampleSelected
	ld a, FULL_COLOR_TIMING_ROW_PALETTE_OBJ
	call BeginFullColorRuntimeTimingSampleSelected
	push af
	call CommitFullColorCanaryOBJPaletteSelected
	pop af
	call nc, EndFullColorRuntimeTimingSampleSelected
	ld a, FULL_COLOR_TIMING_ROW_PALETTE_COMBINED
	call BeginFullColorRuntimeTimingSampleSelected
	push af
	call CommitFullColorCanaryCombinedPalettesSelected
	pop af
	call nc, EndFullColorRuntimeTimingSampleSelected
	ret

CommitFullColorCanaryCombinedPalettesSelected:
	call CommitFullColorCanaryBGPaletteSelected
	; fallthrough
CommitFullColorCanaryOBJPaletteSelected:
	ld a, $80
	ldh [rOBPI], a
	ld hl, FullColorCanaryOBJPalettes
	ld c, LOW(rOBPD)
	jr CommitFullColorCanaryPaletteSelected

CommitFullColorCanaryBGPaletteSelected:
	ld a, $80
	ldh [rBGPI], a
	ld hl, FullColorCanaryBGPalettes
	ld c, LOW(rBGPD)
CommitFullColorCanaryPaletteSelected:
	ld b, FULL_COLOR_PALETTE_EXTENT
.copy
	ld a, [hli]
	ldh [c], a
	dec b
	jr nz, .copy
	ret
ENDC

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

IF !DEF(PHASE2_AUDIT)
; Interrupt-safe bank adapters for the normal-debug SameBoy marker ABI.
; Begin returns carry set when this row was already sampled or another exact
; operation currently owns the singleton marker record.
BeginFullColorRuntimeTimingSampleFar::
	select_renderer_state_e
	call BeginFullColorRuntimeTimingSampleSelected
	push af
	restore_renderer_state_e
	pop af
	ret

EndFullColorRuntimeTimingSampleFar::
	select_renderer_state_e
	call EndFullColorRuntimeTimingSampleSelected
	restore_renderer_state_e
	ret
ENDC

; Carry clear means the owner consumed the VBlank. Yellow-visible writers must
; be skipped. Carry set means Yellow remains the VBlank owner.
FullColorVBlankOwnerConsumed::
	IF DEF(PHASE2_AUDIT)
	call PollFullColorPhase2DebugCommand
	ELSE
	call PollFullColorDebugCommand
	ENDC
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

IF !DEF(PHASE2_AUDIT)
; Normal debug uses the Phase 1 SRAM mailbox as the transport but stores Phase
; 2 observations in a separate FCP2 carrier. ARM only initializes metadata;
; gameplay and presentation continue through ordinary production boundaries.
OpenFullColorPhase2RuntimeCarrier:
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BANK(wFullColorPhase2RuntimeCarrierStart)
	ld [rRAMB], a
	ret

CloseFullColorPhase2RuntimeCarrier:
	xor a
	ld [rRAMB], a
	ld [rRAMG], a
	ret

RunFullColorPhase2RuntimeArm::
	call OpenFullColorPhase2RuntimeCarrier
	ld a, [wFullColorPhase2RuntimeScenario]
	cp FULL_COLOR_PHASE2_RUNTIME_SCENARIO_HOSTILE_SLICE
	jr z, .scenario_valid
	call CloseFullColorPhase2RuntimeCarrier
	ld a, FULL_COLOR_ASSERT_DEBUG_COMMAND
	jp RecordRendererAssertion
.scenario_valid
	ld d, a
	ld hl, wFullColorPhase2RuntimeCarrierStart
	ld bc, FULL_COLOR_RUNTIME_CARRIER_BYTES
	xor a
	call FillMemory
	ld hl, wFullColorPhase2RuntimeMagic
	; Host protocol magic is ASCII, not the game's active text charmap.
	ld a, $46
	ld [hli], a
	ld a, $43
	ld [hli], a
	ld a, $50
	ld [hli], a
	ld a, $32
	ld [hl], a
	ld a, FULL_COLOR_RUNTIME_CARRIER_LAYOUT_VERSION
	ld [wFullColorPhase2RuntimeLayoutVersion], a
	ld a, FULL_COLOR_RUNTIME_RECORD_BYTES
	ld [wFullColorPhase2RuntimeRecordSize], a
	ld a, FULL_COLOR_RUNTIME_RECORD_CAPACITY
	ld [wFullColorPhase2RuntimeRecordCapacity], a
	ld a, d
	ld [wFullColorPhase2RuntimeScenario], a
	ld a, 1
	ld [wFullColorPhase2RuntimeFlags], a
	ld a, FULL_COLOR_RUNTIME_COMMAND_ARM
	ld [wFullColorPhase2RuntimeCommand], a
	ld a, FULL_COLOR_RUNTIME_CHECKPOINT_ARMED
	ld [wFullColorPhase2RuntimeCheckpoint], a
	jp CloseFullColorPhase2RuntimeCarrier

RunFullColorPhase2RuntimeSnapshot::
	select_renderer_state_e
	call OpenFullColorPhase2RuntimeCarrier
	ld a, [wFullColorPhase2RuntimeWriteIndex]
	ld e, a
	ld d, 0
	REPT 5
		sla e
		rl d
	ENDR
	ld hl, wFullColorPhase2RuntimeRecords
	add hl, de
	ld a, FULL_COLOR_PHASE2_RUNTIME_RECORD_CHECKPOINT
	ld [hli], a
	ld a, FULL_COLOR_RUNTIME_CHECKPOINT_SNAPSHOT
	ld [hli], a
	ld a, [wRendererOwner]
	ld [hli], a
	ld a, [wRendererPhase]
	ld [hli], a
	ld de, wRendererGeneration
	REPT 4
		ld a, [de]
		ld [hli], a
		inc de
	ENDR
	ldh a, [hLoadedROMBank]
	ld [hli], a
	ldh a, [hRendererStateSavedSVBK]
	ld [hli], a
	ldh a, [rVBK]
	ld [hli], a
	ldh a, [hRendererStateSavedIE]
	ld [hli], a
	ldh a, [rIF]
	ld [hli], a
	ld a, [wFullColorLastAdmissionResult]
	ld [hli], a
	ld a, [wFullColorRequestCount]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingRow]
	ld [hli], a ; final committed/request class
	ld a, [wFullColorDebugReconstructionState]
	ld [hli], a
	ld a, [wFullColorReconstructionItems + 1]
	ld [hli], a
	ld a, [wFullColorReconstructionItems + 2]
	ld [hli], a
	ld a, [wFullColorReconstructionItems + 3]
	ld [hli], a
	xor a
	ld [hli], a ; before attribute, populated by targeted OAM probes
	ld [hli], a ; after attribute, populated by targeted OAM probes
	ld a, [wFullColorRuntimeTimingRow]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingEvent]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingSequence]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingSequence + 1]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingProbeResult]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingProbeCycles]
	ld [hli], a
	ld a, [wFullColorRuntimeTimingProbeCycles + 1]
	ld [hli], a
	ld a, 1 ; exact SameBoy core cycles required for authority
	ld [hli], a
	xor a
	ld [hl], a
	ld hl, wFullColorPhase2RuntimeRecordCount
	ld a, [hl]
	cp FULL_COLOR_RUNTIME_RECORD_CAPACITY
	jr nc, .count_ready
	inc [hl]
.count_ready
	ld hl, wFullColorPhase2RuntimeWriteIndex
	ld a, [hl]
	inc a
	and FULL_COLOR_RUNTIME_RECORD_CAPACITY - 1
	ld [hl], a
	ld hl, wFullColorPhase2RuntimeSequence
	inc [hl]
	jr nz, .metadata
	inc hl
	inc [hl]
.metadata
	ld a, FULL_COLOR_RUNTIME_COMMAND_SNAPSHOT
	ld [wFullColorPhase2RuntimeCommand], a
	ld a, FULL_COLOR_RUNTIME_CHECKPOINT_SNAPSHOT
	ld [wFullColorPhase2RuntimeCheckpoint], a
	call CloseFullColorPhase2RuntimeCarrier
	restore_renderer_state_e
	ret

RunFullColorPhase2RuntimeAck::
	call OpenFullColorPhase2RuntimeCarrier
	ld a, FULL_COLOR_RUNTIME_COMMAND_ACK
	ld [wFullColorPhase2RuntimeCommand], a
	ld a, FULL_COLOR_RUNTIME_CHECKPOINT_ACKNOWLEDGED
	ld [wFullColorPhase2RuntimeCheckpoint], a
	call CloseFullColorPhase2RuntimeCarrier
	ret

; A = the exact ordinal in the host-authored 14-case overlay corpus. Case zero
; starts a new sequence; later cases must be presented in strict order. Each
; bounded invocation executes one request through the production overlay
; preparation, scheduler state machine, reservation, and paired VRAM commit.
RunFullColorPhase2DiagnosticOverlayMatrix::
	ld c, a
	cp FULL_COLOR_PHASE2_DIAGNOSTIC_OVERLAY_CASES
	jp nc, .overflow
	and a
	jr nz, .validate_sequence
	call InitRendererOwnership
	ld a, HANDOFF_TO_OVERWORLD
	call BeginRendererHandoff
	jp c, .request_failed
	call SelectFullColorOwnerForDiagnostic
	jp c, .request_failed
	call ActivateFullColorOwnerForDiagnostic
	jp c, .request_failed
	select_renderer_state_e
	ld hl, wFullColorPhase2SemanticSnapshotStart
	ld bc, wFullColorPhase2BoundaryEnd - wFullColorPhase2SemanticSnapshotStart
	xor a
	call FillMemory
	xor a
	ld [wFullColorPhase2DiagnosticOverlayNextCase], a
	restore_renderer_state_e
.validate_sequence
	select_renderer_state_e
	ld a, [wFullColorPhase2DiagnosticOverlayNextCase]
	cp c
	jp nz, .sequence_error_selected
	ld a, c
	ld [wFullColorPhase2ObservationCaseID], a
	ld [wFullColorPhase2DiagnosticOverlayCase], a
	ld hl, wFullColorPhase2WriterTraceStart
	ld bc, wFullColorPhase2WriterTraceEnd - wFullColorPhase2WriterTraceStart
	xor a
	call FillMemory
	ld a, FULL_COLOR_PHASE2_OBSERVATION_CHECKPOINT_PREPARED
	ld [wFullColorPhase2ObservationCheckpoint], a
	call CaptureFullColorPhase2BoundaryBeforeSelected
	call InitFullColorSchedulerSelected

	; Clear both physical BG maps while the LCD is hidden. This makes every
	; case an independent full-state observation, not a delta over its sibling.
	ldh a, [rLCDC]
	ld [wFullColorPhase2ObservationMetadata], a
	res 7, a
	ldh [rLCDC], a
	ldh a, [rVBK]
	ld [wFullColorPhase2ObservationMetadata + 1], a
	xor a
	ldh [rVBK], a
	call ClearVramBanked
	ld a, 1
	ldh [rVBK], a
	call ClearVramBanked

	; Locate the fixed record: destination, clipped width/height, independent
	; source/committed counts, selector, map, four clipped tiles, then the full
	; authored source plane and the separately clipped committed plane.
	ld hl, FullColorPhase2DiagnosticOverlayCases
	ld a, [wFullColorPhase2DiagnosticOverlayCase]
	and a
	jr z, .case_record_ready
	ld de, 20
.seek_case_record
	add hl, de
	dec a
	jr nz, .seek_case_record
.case_record_ready
	ld a, [hli]
	ld e, a
	ld a, [hli]
	ld d, a
	ld a, [hli]
	ld b, a
	ld a, [hli]
	ld c, a
	ld a, [hli]
	ld [wFullColorPhase2DiagnosticOverlaySourceAttributeCount], a
	ld a, [hli]
	ld [wFullColorPhase2DiagnosticOverlayCommittedAttributeCount], a
	ld [wFullColorPhase2DiagnosticOverlayWorkingAttributeCount], a
	ld [wFullColorPhase2ObservationMetadata + 2], a
	ld a, [hli]
	ld [wFullColorPhase2ObservationMetadata + 3], a ; destination selector
	ld a, [hli]
	ld [wFullColorPhase2ObservationMetadata + 4], a ; map identity
	push de
	push bc
	ld de, wTileMap
	ld b, 4
.copy_tiles
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_tiles
	ld de, wFullColorPhase2DiagnosticOverlaySourceAttributes
	ld b, 4
.copy_source_attributes
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_source_attributes
	ld de, wFullColorPhase2DiagnosticOverlayCommittedAttributes
	ld b, 4
.copy_committed_attributes
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_committed_attributes
	ld hl, wFullColorPhase2DiagnosticOverlayCommittedAttributes
	ld de, wFullColorPhase2DiagnosticOverlayWorkingAttributes
	ld b, 4
.copy_working_attributes
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_working_attributes
	pop bc
	pop de
	ld a, [wFullColorPhase2DiagnosticOverlayCommittedAttributeCount]
	and a
	jr z, .no_visible_request
	restore_renderer_state_e
	ld hl, wTileMap
	call EnqueueFullColorMapOverlay
	jp c, .request_failed_restore_lcd
	select_renderer_state_e
	ld hl, wFullColorRequestDescriptors
	ld de, wFullColorPhase2ObservationDescriptor
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
.copy_descriptor
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy_descriptor
	restore_renderer_state_e
	call RunFullColorOwnershipVBlank
	select_renderer_state_e
.no_visible_request
	call PublishFullColorPhase2ObservationSelected
	ld a, [wFullColorPhase2DiagnosticOverlayCase]
	inc a
	ld [wFullColorPhase2DiagnosticOverlayNextCase], a
	ld a, FULL_COLOR_PHASE2_OBSERVATION_CHECKPOINT_COMPLETE
	ld [wFullColorPhase2ObservationCheckpoint], a
	call CaptureFullColorPhase2BoundaryAfterSelected
	ld a, [wFullColorPhase2ObservationMetadata + 1]
	ldh [rVBK], a
	ld a, [wFullColorPhase2ObservationMetadata]
	ldh [rLCDC], a
	restore_renderer_state_e
	and a
	ret
.sequence_error_selected
	ld hl, wFullColorPhase2ObservationFlags
	set 1, [hl]
	restore_renderer_state_e
	scf
	ret
.overflow
	select_renderer_state_e
	ld [wFullColorPhase2ObservationCaseID], a
	ld hl, wFullColorPhase2ObservationFlags
	set 0, [hl]
	restore_renderer_state_e
	scf
	ret
.request_failed_restore_lcd
	select_renderer_state_e
	ld a, [wFullColorPhase2ObservationMetadata + 1]
	ldh [rVBK], a
	ld a, [wFullColorPhase2ObservationMetadata]
	ldh [rLCDC], a
	restore_renderer_state_e
.request_failed
	select_renderer_state_e
	ld hl, wFullColorPhase2ObservationFlags
	set 2, [hl]
	restore_renderer_state_e
	scf
	ret

CaptureFullColorPhase2BoundaryBeforeSelected:
	ld hl, wFullColorPhase2BoundaryBefore
	jr CaptureFullColorPhase2BoundarySelected
CaptureFullColorPhase2BoundaryAfterSelected:
	ld hl, wFullColorPhase2BoundaryAfter
CaptureFullColorPhase2BoundarySelected:
	ld a, [wFullColorPhase2DiagnosticOuterROMBank]
	ld [hli], a
	ld a, [wFullColorPhase2DiagnosticOuterROMBank + 1]
	ld [hli], a
	ldh a, [hRendererStateSavedSVBK]
	ld [hli], a
	ldh a, [rVBK]
	ld [hli], a
	ldh a, [hRendererStateSavedIE]
	ld [hli], a
	ldh a, [rIF]
	ld [hli], a
	ld a, [wRendererOwner]
	ld [hli], a
	ld a, [wRendererPhase]
	ld [hli], a
	ld de, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .generation
	xor a
	ld [hli], a
	ld [hli], a
	ld [hli], a
	ld [hl], a
	ret

PublishFullColorPhase2ObservationSelected:
	ld hl, wFullColorPhase2ObservationMagic
	ld a, $46 ; FCO2
	ld [hli], a
	ld a, $43
	ld [hli], a
	ld a, $4f
	ld [hli], a
	ld a, $32
	ld [hli], a
	ld a, FULL_COLOR_PHASE2_OBSERVATION_LAYOUT_VERSION
	ld [wFullColorPhase2ObservationVersion], a
	ld a, FULL_COLOR_PHASE2_OBSERVATION_SNAPSHOT_BYTES
	ld [wFullColorPhase2ObservationSize], a
	ld hl, wFullColorPhase2ObservationSequence
	inc [hl]
	jr nz, .sequence_ready
	inc hl
	inc [hl]
	jr nz, .sequence_ready
	ld hl, wFullColorPhase2ObservationFlags
	set 0, [hl]
.sequence_ready
	ld hl, wFullColorPhase2ObservationMetadata + 5
	ld a, [wRendererOwner]
	ld [hli], a
	ld a, [wRendererPhase]
	ld [hli], a
	ld de, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .generation
	ld a, [wFullColorLastAdmissionResult]
	ld [hli], a
	ld a, [wFullColorRequestCount]
	ld [hli], a
	ld a, [wFullColorRequestCursor]
	ld [hli], a
	ld de, wFullColorReconstructionItems
	ld b, 4
.reconstruction
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .reconstruction
	ld a, [wFullColorTransitionCount]
	ld [wFullColorPhase2ObservationTransitionCount], a
	ld de, wFullColorTransitionLog
	ld hl, wFullColorPhase2ObservationTransitionLog
	ld b, 8
.transitions
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .transitions
	ret

; destination, clipped width/height, source/committed attribute counts,
; destination selector, map identity, four clipped tile bytes, four complete
; request-authored attributes, and four independently clipped commit bytes.
FullColorPhase2DiagnosticOverlayCases:
	dw $9884
	db 1, 1, 1, 1, 0, 0, $10, 0, 0, 0, $ef, 0, 0, 0, $ef, 0, 0, 0
	dw $9885
	db 1, 1, 1, 1, 0, 0, $10, 0, 0, 0, $02, 0, 0, 0, $02, 0, 0, 0
	dw $9886
	db 1, 1, 1, 1, 0, 0, $17, 0, 0, 0, $07, 0, 0, 0, $07, 0, 0, 0
	dw $9887
	db 1, 1, 1, 1, 0, 0, $10, 0, 0, 0, $87, 0, 0, 0, $87, 0, 0, 0
	dw $9800
	db 0, 0, 4, 0, 0, 0, 0, 0, 0, 0, $ef, $07, $02, $03, 0, 0, 0, 0
	dw $9fc0
	db 1, 2, 4, 2, 1, 0, $11, $13, 0, 0, $0f, $07, $02, $03, $07, $03, 0, 0
	dw $987f
	db 1, 2, 4, 2, 0, 0, $10, $12, 0, 0, $ef, $07, $02, $03, $ef, $02, 0, 0
	dw $9803
	db 2, 1, 4, 2, 0, 0, $12, $13, 0, 0, $ef, $07, $02, $03, $02, $03, 0, 0
	dw $9be3
	db 2, 1, 4, 2, 0, 0, $10, $11, 0, 0, $ef, $07, $02, $03, $ef, $07, 0, 0
	dw $9bde
	db 2, 2, 4, 4, 0, 0, $10, $11, $12, $13, $ef, $02, $02, $87, $ef, $02, $02, $87
	dw $9800
	db 2, 2, 4, 4, 0, 1, $10, $11, $12, $13, $ef, $02, $02, $87, $ef, $02, $02, $87
	dw $9c21
	db 2, 2, 4, 4, 1, 0, $10, $11, $12, $13, $ef, $02, $02, $87, $ef, $02, $02, $87
	dw $9c21
	db 2, 2, 4, 4, 2, 0, $10, $11, $12, $13, $ef, $02, $02, $87, $ef, $02, $02, $87
	dw $9821
	db 2, 2, 4, 4, 0, 2, $10, $11, $12, $13, $ef, $02, $02, $87, $ef, $02, $02, $87
FullColorPhase2DiagnosticOverlayCasesEnd:
ASSERT FullColorPhase2DiagnosticOverlayCasesEnd - FullColorPhase2DiagnosticOverlayCases == FULL_COLOR_PHASE2_DIAGNOSTIC_OVERLAY_CASES * 20

; A = exact ordinal 14..24 in the fixed hostile corpus. The caller must first
; execute the unchanged 0..13 overlay matrix in the same emulator. Every case
; crosses its production commit/barrier before FCO2 is published; the strict
; next-case byte makes omission, reordering, repetition, and overflow fail
; closed instead of silently rebinding an actual to a checker case.
RunFullColorPhase2DiagnosticNonOverlayCase::
	cp FULL_COLOR_PHASE2_DIAGNOSTIC_NONOVERLAY_FIRST
	jp c, .overflow
	cp FULL_COLOR_PHASE2_DIAGNOSTIC_CASES
	jp nc, .overflow
	ld c, a
	ld [wTileMap + SCREEN_AREA - 1], a
	select_renderer_state_e
	ld a, [wFullColorPhase2DiagnosticOverlayNextCase]
	cp c
	jp nz, .sequence_error_selected
	ld a, c
	ld [wFullColorPhase2ObservationCaseID], a
	ld [wFullColorPhase2DiagnosticOverlayCase], a
	xor a
	ld [wFullColorPhase2ObservationFlags], a
	ld hl, wFullColorPhase2DiagnosticOverlaySourceAttributeCount
	ld bc, 15
	call FillMemory
	ld hl, wFullColorPhase2WriterTraceStart
	ld bc, wFullColorPhase2WriterTraceEnd - wFullColorPhase2WriterTraceStart
	call FillMemory
	ld a, FULL_COLOR_PHASE2_OBSERVATION_CHECKPOINT_PREPARED
	ld [wFullColorPhase2ObservationCheckpoint], a
	call InitFullColorSchedulerSelected
	call SetFullColorPhase2DiagnosticGenerationSelected
	call CaptureFullColorPhase2BoundaryBeforeSelected
	restore_renderer_state_e

	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 17
	jr c, .transfer
	cp 19
	jr c, .palette
	cp 22
	jr c, .oam
	jr z, .reconstruction
	cp 23
	jr z, .ownership
	call RunFullColorPhase2MachineDiagnostic
	jr .operation_complete
.transfer
	call RunFullColorPhase2TransferDiagnostic
	jr .operation_complete
.palette
	call RunFullColorPhase2PaletteDiagnostic
	jr .operation_complete
.oam
	call RunFullColorPhase2OAMDiagnostic
	jr .operation_complete
.reconstruction
	call RunFullColorPhase2ReconstructionDiagnostic
	jr .operation_complete
.ownership
	call RunFullColorPhase2OwnershipDiagnostic
.operation_complete
	jp c, .request_failed
	select_renderer_state_e
	ld a, [wTileMap + SCREEN_AREA - 1]
	inc a
	ld [wFullColorPhase2DiagnosticOverlayNextCase], a
	ld a, FULL_COLOR_PHASE2_OBSERVATION_CHECKPOINT_COMPLETE
	ld [wFullColorPhase2ObservationCheckpoint], a
	call CaptureFullColorPhase2BoundaryAfterSelected
	call PublishFullColorPhase2NonOverlayTraceSelected
	call PublishFullColorPhase2ObservationSelected
	restore_renderer_state_e
	and a
	ret
.sequence_error_selected
	ld hl, wFullColorPhase2ObservationFlags
	set 1, [hl]
	restore_renderer_state_e
	scf
	ret
.overflow
	select_renderer_state_e
	ld [wFullColorPhase2ObservationCaseID], a
	ld hl, wFullColorPhase2ObservationFlags
	set 0, [hl]
	restore_renderer_state_e
	scf
	ret
.request_failed
	select_renderer_state_e
	ld hl, wFullColorPhase2ObservationFlags
	set 2, [hl]
	restore_renderer_state_e
	scf
	ret

; The corpus generations are independently fixed inputs. Setting the entry
; fixture does not claim a transition; ownership replacement below advances
; seven to eight through the real generation primitive.
SetFullColorPhase2DiagnosticGenerationSelected:
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 17
	ld a, 3
	jr c, .store
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 19
	ld a, 4
	jr c, .store
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 22
	ld a, 5
	jr c, .store
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 23
	ld a, 6
	jr c, .store
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 24
	ld a, 7
	jr c, .store
	ld a, 9
.store
	ld [wRendererGeneration], a
	xor a
	ld [wRendererGeneration + 1], a
	ld [wRendererGeneration + 2], a
	ld [wRendererGeneration + 3], a
	ret

RunFullColorPhase2TransferDiagnostic:
	; Copy independently authored tiles and attributes into fixed WRAM. The
	; ordinary semantic producer freezes them, and the scheduler performs the
	; real paired VRAM commit.
	ld a, [wTileMap + SCREEN_AREA - 1]
	sub 14
	ld c, a
	ld hl, FullColorPhase2DiagnosticTransferCases
	and a
	jr z, .record
	ld de, 12
.seek
	add hl, de
	dec a
	jr nz, .seek
.record
	ld a, [hli]
	ld e, a
	ld a, [hli]
	ld d, a
	ld a, [hli]
	ld b, a
	ld a, [hli]
	ld c, a
	push de
	push bc
	ld de, wTileMap
	ld b, 4
.tiles
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .tiles
	select_renderer_state_e
	ld de, wFullColorPhase2DiagnosticOverlayCommittedAttributes
	ld b, 4
.attributes
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .attributes
	pop bc
	push bc
	ld a, b
	ld d, a
	ld a, c
	and a
	jr z, .count_ready
	ld a, d
.count_loop
	dec c
	jr z, .count_ready
	add d
	jr .count_loop
.count_ready
	ld [wFullColorPhase2DiagnosticOverlayCommittedAttributeCount], a
	restore_renderer_state_e
	pop bc
	pop de
	ld hl, wTileMap
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 14
	jr z, .row
	cp 15
	jr z, .column
	call EnqueueFullColorMapConnection
	jr .admitted
.row
	call EnqueueFullColorMapRow
	jr .admitted
.column
	call EnqueueFullColorMapColumn
.admitted
	ret c
	call CopyFullColorPhase2DiagnosticDescriptor
	call RunFullColorOwnershipVBlank
	and a
	ret

; destination, width, height, four tile bytes, four attribute bytes.
FullColorPhase2DiagnosticTransferCases:
	dw $9862
	db 3, 1, $10, $20, $30, 0, $81, $92, $a3, 0
	dw $985f
	db 1, 3, $40, $50, $60, 0, $b4, $c5, $d6, 0
	dw $9800
	db 2, 2, $70, $80, $90, $a0, $e7, $f8, $09, $1a
ASSERT @ - FullColorPhase2DiagnosticTransferCases == 3 * 12

RunFullColorPhase2PaletteDiagnostic:
	; Source bytes are copied to fixed WRAM, then admitted through the complete
	; 64-byte production palette request. Case 18 leaves both BG and OBJ actual
	; buffers/hardware populated, proving the combined state without inventing
	; a third checker case.
	ld hl, wTileMap + FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	ld b, FULL_COLOR_PALETTE_EXTENT
	xor a
.payload
	ld [hli], a
	inc a
	dec b
	jr nz, .payload
	ld hl, wTileMap
	ld bc, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	xor a
	call FillMemory
	ld hl, wTileMap
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 17
	ld a, FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	jr z, .class_ready
	ld a, FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
.class_ready
	ld [hli], a
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ld [hli], a
	select_renderer_state_e
	ld de, wRendererGeneration
	REPT 4
		ld a, [de]
		ld [hli], a
		inc de
	ENDR
	restore_renderer_state_e
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 17
	ld de, FULL_COLOR_BG_PALETTE_DESTINATION
	jr z, .destination_ready
	ld de, FULL_COLOR_OBJ_PALETTE_DESTINATION
.destination_ready
	ld a, e
	ld [hli], a
	ld a, d
	ld [hli], a
	ld de, wTileMap + FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	ld a, e
	ld [hli], a
	ld a, d
	ld [hli], a
	xor a
	ld [hli], a
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_PALETTES
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(FULL_COLOR_PALETTE_EXTENT)
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(FULL_COLOR_PALETTE_RESERVATION)
	ld [hli], a
	xor a
	ld [hli], a
	ld [hli], a
	ld [hl], a
	ld hl, wTileMap
	call AdmitFullColorRequest
	ret c
	call CopyFullColorPhase2DiagnosticDescriptor
	call RunFullColorOwnershipVBlank
	and a
	ret

RunFullColorPhase2OAMDiagnostic:
	ld hl, wShadowOAM
	ld bc, FULL_COLOR_OAM_EXTENT
	xor a
	call FillMemory
	ld a, 37
	ld [wShadowOAM + 2], a
	ld a, $fd
	ld [wShadowOAM + 3], a
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 19
	ld de, $ffff
	jr z, .identity_ready
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 20
	ld de, 300
	jr z, .identity_ready
	ld de, 42
.identity_ready
	select_renderer_state_e
	ld a, e
	ld [wFullColorPhase2DiagnosticOAMSourceIdentity], a
	ld a, d
	ld [wFullColorPhase2DiagnosticOAMSourceIdentity + 1], a
	restore_renderer_state_e
	ld hl, wShadowOAM + 3
	ld b, OAM_COUNT
	ld a, [wTileMap + SCREEN_AREA - 1]
	cp 20
	jr z, .out_of_range
	cp 19
	ld a, $ff
	jr z, .map_byte
	select_renderer_state_e
	ld a, 42
	call MapFullColorOAMUnmappedAttributeSelected
	restore_renderer_state_e
	jr .mapped
.map_byte
	call MapFullColorOAMAttribute
	jr .mapped
.out_of_range
	select_renderer_state_e
	ld de, 300
	call MapFullColorOAMAttribute16Selected
	restore_renderer_state_e
.mapped
	; Carry is the expected fallback result. The mapped byte is authoritative;
	; publish it through the same hardware DMA used after a complete OAM batch.
	call hDMARoutine
	and a
	ret

RunFullColorPhase2ReconstructionDiagnostic:
	ldh a, [rLCDC]
	push af
	res 7, a
	ldh [rLCDC], a
	select_renderer_state_e
	ld a, OVERWORLD_RECONSTRUCTING
	ld [wRendererPhase], a
	xor a
	ld [wRendererAdmissionOpen], a
	ld a, LOW($9800)
	ld [wFullColorAuthorityVRAMView], a
	ld a, HIGH($9800)
	ld [wFullColorAuthorityVRAMView + 1], a
	restore_renderer_state_e
	call ReconstructFullColorMapEntry
	pop bc
	ld a, b
	ldh [rLCDC], a
	ret

RunFullColorPhase2OwnershipDiagnostic:
	; Exercise replacement through the real cancellation and generation APIs.
	call AdvanceRendererGeneration
	ret c
	select_renderer_state_e
	ld a, OVERWORLD_ACTIVE
	ld [wRendererPhase], a
	ld a, TRUE
	ld [wRendererAdmissionOpen], a
	restore_renderer_state_e
	and a
	ret

RunFullColorPhase2MachineDiagnostic:
	; The host enters with non-default ROM/WRAM/VRAM/IE/IF. This production far
	; wrapper must preserve that machine boundary while mapping a real object.
	ld a, $fd
	ld [wShadowOAM + 3], a
	ld de, wShadowOAM + 3
	ld c, SPRITE_RED
	call MapFullColorOAMAttributeFar
	and a
	ret

CopyFullColorPhase2DiagnosticDescriptor:
	select_renderer_state_e
	ld hl, wFullColorRequestDescriptors
	ld de, wFullColorPhase2ObservationDescriptor
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
.copy
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy
	restore_renderer_state_e
	ret

; FCO2 trace-reserved bytes remain zero for overlay cases. Non-overlay cases
; publish this bounded actual-state record after the real operation completes:
; magic, case, COMPLETE, request class, admission, pending count, owner, phase,
; generation[4], OAM before/after, fallback kind, u16 source identity, object,
; reconstruction barrier, u16 outer ROM bank, WRAM/VRAM banks, IE, IF. The host
; rejects any other version, length, or order.
PublishFullColorPhase2NonOverlayTraceSelected:
	ld hl, wFullColorPhase2ObservationTraceReserved
	ld a, FULL_COLOR_PHASE2_NONOVERLAY_TRACE_MAGIC
	ld [hli], a
	ld a, [wTileMap + SCREEN_AREA - 1]
	ld [hli], a
	ld a, COMPLETE
	ld [hli], a
	ld a, [wFullColorPhase2ObservationDescriptor]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld [hli], a
	ld a, [wFullColorLastAdmissionResult]
	ld [hli], a
	ld a, [wFullColorRequestCount]
	ld [hli], a
	ld a, [wRendererOwner]
	ld [hli], a
	ld a, [wRendererPhase]
	ld [hli], a
	ld de, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .generation
	ld a, $fd
	ld [hli], a
	ld a, [wShadowOAM + 3]
	ld [hli], a
	ld a, [wFullColorReconstructionItems + 1]
	ld [hli], a
	ld a, [wFullColorPhase2DiagnosticOAMSourceIdentity]
	ld [hli], a
	ld a, [wFullColorPhase2DiagnosticOAMSourceIdentity + 1]
	ld [hli], a
	ld a, [wFullColorReconstructionItems + 3]
	ld [hli], a
	ld a, [wFullColorDebugReconstructionState]
	ld [hli], a
	ld a, [wFullColorPhase2DiagnosticOuterROMBank]
	ld [hli], a
	ld a, [wFullColorPhase2DiagnosticOuterROMBank + 1]
	ld [hli], a
	ldh a, [hRendererStateSavedSVBK]
	ld [hli], a
	ldh a, [rVBK]
	ld [hli], a
	ldh a, [hRendererStateSavedIE]
	ld [hli], a
	ldh a, [rIF]
	ld [hli], a
	ret
ENDC

EXPORT SnapshotFullColorMapAuthority, PoisonLegacyVideoRequests
EXPORT BeginFullColorMapEntry, CompleteFullColorMapReconstruction
EXPORT ReconstructFullColorMapEntry
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
EXPORT InitFullColorPhase2LifecycleSelected
IF !DEF(PHASE2_AUDIT)
EXPORT RunFullColorPhase2RuntimeArm, RunFullColorPhase2RuntimeSnapshot
EXPORT RunFullColorPhase2RuntimeAck
EXPORT RunFullColorPhase2DiagnosticOverlayMatrix
EXPORT RunFullColorPhase2DiagnosticNonOverlayCase
EXPORT BeginFullColorRuntimeTimingSampleFar
EXPORT EndFullColorRuntimeTimingSampleFar
ENDC
