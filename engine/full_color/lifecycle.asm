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
	call LoadFullColorFontGraphicsSelected
	call SnapshotFullColorVisibleMapSelected
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
	; Exactly one reconstruction barrier is observable before activation.
	ld hl, wFullColorDebugReconstructionState
	inc [hl]
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
