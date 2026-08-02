; Phase 2 measured request scheduler.
;
; Admission ABI: HL points at a 20-byte candidate descriptor in fixed WRAM.
; The low nibble of byte 0 is the request class; state bits are ignored.
; A returns ACCEPTED/COALESCED/DEFERRED or a stable rejection code. Carry is
; set for every result other than ACCEPTED/COALESCED. Required work is never
; dropped: DEFERRED increments the observable retry token.

RouteRendererOwnershipVBlank::
IF DEF(PHASE2_AUDIT)
	call PollFullColorPhase2DebugCommand
ELIF DEF(_DEBUG)
	call PollFullColorDebugCommand
ENDC
	call RetryFullColorProducer
	call GetRendererOwner
	cp RENDERER_FULL_COLOR_OVERWORLD
	ret nz
	; fallthrough
RunFullColorOwnershipVBlank::
	select_renderer_state_e
	call RunFullColorSchedulerSelected
	restore_renderer_state_e
	ret

ClearVramBanked::
	ld hl, STARTOF(VRAM)
	ld bc, SIZEOF(VRAM)
	xor a
	jp FillMemory

InitFullColorSchedulerSelected::
	ld hl, wFullColorRequestDescriptors
	ld b, FULL_COLOR_REQUEST_CAPACITY
.clear_descriptor
	ld a, FULL_COLOR_DESCRIPTOR_FREE
	ld [hl], a
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	dec b
	jr nz, .clear_descriptor
	xor a
	ld [wFullColorRequestCount], a
	ld [wFullColorRequestCursor], a
	ld [wFullColorRetryCounter], a
	ld [wFullColorTransitionCount], a
	ld [wFullColorActiveDescriptor], a
	ld [wFullColorActiveDescriptor + 1], a
	ld hl, wFullColorTimingState
	ld b, 8
.clear_observability
	ld [hli], a
	dec b
	jr nz, .clear_observability
	ld a, FULL_COLOR_RESOURCE_ALL
	ld [wFullColorAvailableResources], a
	xor a
	ld [wFullColorAvailableResources + 1], a
	cpl
	ld [wFullColorCommitBudget], a
	ld [wFullColorCommitBudget + 1], a
	ret

InitFullColorScheduler::
	select_renderer_state_e
	call InitFullColorSchedulerSelected
	restore_renderer_state_e
	ret

; HL is the candidate before bank selection. Keep the fixed-WRAM pointer in DE.
AdmitFullColorRequest::
	ld d, h
	ld e, l
	select_renderer_state_e
	ld a, [wRendererAdmissionOpen]
	and a
	jp z, AdmitFullColorRequest_defer
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jp nz, AdmitFullColorRequest_wrong_owner
	ld a, [de]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp NUM_FULL_COLOR_REQUEST_CLASSES
	jp nc, AdmitFullColorRequest_defer
	inc de
	ld a, [de]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jp nz, AdmitFullColorRequest_wrong_owner
	inc de
	ld hl, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	cp [hl]
	jp nz, AdmitFullColorRequest_stale
	inc de
	inc hl
	dec b
	jr nz, .generation
	; Restore candidate start, then coalesce before testing capacity.
	ld hl, -6
	add hl, de
	ld d, h
	ld e, l
	call ValidateFullColorRequestResourcesSelected
	jp c, AdmitFullColorRequest_defer
	call FindEquivalentFullColorRequestSelected
	jr nc, .coalesced
	ld a, [wFullColorRequestCount]
	cp FULL_COLOR_REQUEST_CAPACITY
	jp nc, AdmitFullColorRequest_defer
	call FindFreeFullColorDescriptorSelected
	jp c, AdmitFullColorRequest_defer
	; HL = destination descriptor, DE = candidate.
	push hl
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
.copy
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .copy
	pop hl
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, PENDING << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld de, FULL_COLOR_DESCRIPTOR_RETRY_TOKEN
	add hl, de
	ld a, [wFullColorRetryCounter]
	ld [hl], a
	ld hl, wFullColorRequestCount
	inc [hl]
	ld a, PENDING
	call RecordFullColorTransitionSelected
	ld a, ACCEPTED
	jr .accepted_result
.coalesced
	ld a, COALESCED
.accepted_result
	ld [wFullColorLastAdmissionResult], a
	ld b, a
	call PublishFullColorSchedulerDebugSelected
	restore_renderer_state_e
	ld a, b
	and a
	ret

; Semantic paired-producer ABI. HL=fixed-WRAM tile source, DE=BG-map
; destination, B=width, C=height. A is supplied by the class-exact wrappers.
; The helper derives attributes from independent tile-class authority, creates
; the exact descriptor, and freezes it into scheduler scratch before return.
; A returns ACCEPTED or DEFERRED; carry is clear only for ACCEPTED.
EnqueueFullColorMapRow::
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jp EnqueueFullColorPairedSemantic
EnqueueFullColorMapColumn::
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jp EnqueueFullColorPairedSemantic
EnqueueFullColorMapConnection::
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED
	jp EnqueueFullColorPairedSemantic
EnqueueFullColorMapRectangle::
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, FULL_COLOR_REQUEST_MAP_RECTANGLE_PAIRED
	jp EnqueueFullColorPairedSemantic
EnqueueFullColorMapOverlay::
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED
	; fallthrough
EnqueueFullColorPairedSemantic:
	IF DEF(PHASE2_AUDIT)
	push af
	select_renderer_state_e
	pop af
	ELSE
	; The class is loaded only after selecting WRAM2. Pushing it before the bank
	; switch and popping afterward would read the same stack address from the
	; wrong physical WRAM bank.
	; A retained producer is immutable retry authority. Check the singleton
	; before writing even its class: a later row/column request must not mutate
	; the deferred unit while OAM owns preparation scratch.
	push af
	call FullColorProducerStorageAvailableSelected
	jr nc, .storage_available
	pop af
	jp EnqueueFullColorSemantic_defer
.storage_available
	pop af
	ENDC
	ld [wFullColorProducerClass], a
	bit 7, a
	ld a, 0
	jr z, .flags_ready
	ld a, FULL_COLOR_FLAG_MOVEMENT_STRIP
.flags_ready
	ld [wFullColorProducerFlags], a
	ld a, [wFullColorProducerClass]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld [wFullColorProducerClass], a
	ld a, h
	cp $c0
	jp c, EnqueueFullColorSemantic_defer
	cp $d0
	jp nc, EnqueueFullColorSemantic_defer
	ld a, l
	ld [wFullColorProducerSource], a
	ld a, h
	ld [wFullColorProducerSource + 1], a
	ld a, e
	ld [wFullColorProducerDestination], a
	ld a, d
	ld [wFullColorProducerDestination + 1], a
	ld a, b
	and a
	jp z, EnqueueFullColorSemantic_defer
	cp SCREEN_WIDTH + 1
	jp nc, EnqueueFullColorSemantic_defer
	ld [wFullColorProducerWidth], a
	ld a, c
	and a
	jp z, EnqueueFullColorSemantic_defer
	cp SCREEN_HEIGHT + 1
	jp nc, EnqueueFullColorSemantic_defer
	ld [wFullColorProducerHeight], a
	ld a, [wFullColorProducerClass]
	cp FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jr nz, .not_row
	ld a, c
	ld d, 1
	ld a, [wFullColorProducerFlags]
	and FULL_COLOR_FLAG_MOVEMENT_STRIP
	jr z, .row_height_ready
	inc d
.row_height_ready
	ld a, c
	cp d
	jp nz, EnqueueFullColorSemantic_defer
.not_row
	ld a, [wFullColorProducerClass]
	cp FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jr nz, .geometry_ok
	ld a, b
	ld d, 1
	ld a, [wFullColorProducerFlags]
	and FULL_COLOR_FLAG_MOVEMENT_STRIP
	jr z, .column_width_ready
	inc d
.column_width_ready
	ld a, b
	cp d
	jp nz, EnqueueFullColorSemantic_defer
.geometry_ok
	IF DEF(PHASE2_AUDIT)
	call FullColorProducerStorageAvailableSelected
	jp c, EnqueueFullColorSemantic_defer
	ENDC
	; BC = width * height.
	ld a, [wFullColorProducerWidth]
	ld e, a
	ld a, [wFullColorProducerHeight]
	ld d, a
	ld bc, 0
.multiply_exact
	ld a, c
	add e
	ld c, a
	jr nc, .multiply_exact_no_carry
	inc b
.multiply_exact_no_carry
	dec d
	jr nz, .multiply_exact
	ld a, c
	ld [wFullColorRequestStaging], a
	ld a, b
	ld [wFullColorRequestStaging + 1], a
	; The complete caller source must remain inside fixed WRAM0.
	ld a, [wFullColorProducerSource]
	ld l, a
	ld a, [wFullColorProducerSource + 1]
	ld h, a
	add hl, bc
	ld a, h
	cp $d0
	jp c, .source_extent_ok
	jp nz, EnqueueFullColorSemantic_defer
	ld a, l
	and a
	jp nz, EnqueueFullColorSemantic_defer
.source_extent_ok
	; Snapshot immutable tiles.
	ld a, [wFullColorProducerSource]
	ld e, a
	ld a, [wFullColorProducerSource + 1]
	ld d, a
	ld hl, wFullColorProducerTiles
	push bc
.copy_tiles
	ld a, b
	or c
	jr z, .tiles_done
	ld a, [de]
	ld [hli], a
	inc de
	dec bc
	jr .copy_tiles
.tiles_done
	pop bc
	; Normal-debug diagnostic overlays carry an independently-authored second
	; plane. The scheduler below remains the production freezer and committer.
IF DEF(_DEBUG)
IF !DEF(PHASE2_AUDIT)
	ld a, [wFullColorProducerClass]
	cp FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED
	jr z, .diagnostic_class
	cp FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jr z, .diagnostic_class
	cp FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jr z, .diagnostic_class
	cp FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED
	jr nz, .derive_attributes
.diagnostic_class
	ld a, [wFullColorRequestStaging + 1]
	and a
	jr nz, .derive_attributes
	ld a, [wFullColorPhase2DiagnosticOverlayAttributeCount]
	cp c
	jr nz, .derive_attributes
	ld de, wFullColorPhase2DiagnosticOverlayAttributes
	ld hl, wFullColorProducerTiles
	add hl, bc
	push bc
.copy_diagnostic_attributes
	ld a, b
	or c
	jr z, .diagnostic_attributes_done
	ld a, [de]
	ld [hli], a
	inc de
	dec bc
	jr .copy_diagnostic_attributes
.diagnostic_attributes_done
	pop bc
	xor a
	ld [wFullColorPhase2DiagnosticOverlayAttributeCount], a
	jr .derived
.derive_attributes
ENDC
ENDC
	; Derive a distinct attribute plane from the frozen tile plane.
	ld de, wFullColorProducerTiles
	ld hl, wFullColorProducerTiles
	add hl, bc
.derive
	ld a, b
	or c
	jr z, .derived
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
	jr .derive
.derived
	call BuildAndPrepareFullColorPairedDescriptorSelected
	jp FinishFullColorSemanticSelected

; Atomic legacy movement strips. They remain row/column requests, but carry an
; explicit measured flag binding the complete 20x2 or 2x18 visible unit.
; Row: HL=40 tile bytes, DE=BG destination. Column: HL=36 bytes, DE=BG dest.
EnqueueFullColorMovementRowStrip::
	ld b, SCREEN_WIDTH
	ld c, 2
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, $80 | FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jp EnqueueFullColorPairedSemantic
EnqueueFullColorMovementColumnStrip::
	ld b, 2
	ld c, SCREEN_HEIGHT
	IF !DEF(PHASE2_AUDIT)
	select_renderer_state_e
	ENDC
	ld a, $80 | FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jp EnqueueFullColorPairedSemantic

; Animation ABI: HL=fixed-WRAM 16-byte tile source, DE=tile-data destination,
; BC=attribute-map destination. Attribute identity is derived from tile 0.
EnqueueFullColorAnimation::
	select_renderer_state_e
	IF !DEF(PHASE2_AUDIT)
	call FullColorProducerStorageAvailableSelected
	jp c, EnqueueFullColorSemantic_defer
	ENDC
	xor a
	ld [wFullColorProducerFlags], a
	ld a, h
	cp $c0
	jp c, EnqueueFullColorSemantic_defer
	cp $d0
	jp nc, EnqueueFullColorSemantic_defer
	ld a, l
	ld [wFullColorProducerSource], a
	ld a, h
	ld [wFullColorProducerSource + 1], a
	ld a, e
	ld [wFullColorProducerDestination], a
	ld a, d
	ld [wFullColorProducerDestination + 1], a
	ld a, c
	ld [wFullColorProducerWidth], a
	ld a, b
	ld [wFullColorProducerHeight], a
	ld a, FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	ld [wFullColorProducerClass], a
	IF DEF(PHASE2_AUDIT)
	call FullColorProducerStorageAvailableSelected
	jp c, EnqueueFullColorSemantic_defer
	ENDC
	ld a, [wFullColorProducerSource]
	ld e, a
	ld a, [wFullColorProducerSource + 1]
	ld d, a
	ld a, e
	add FULL_COLOR_ANIMATION_TILE_BYTES
	ld l, a
	ld a, d
	adc 0
	cp $d0
	jp nc, EnqueueFullColorSemantic_defer
	ld hl, wFullColorProducerTiles
	ld b, FULL_COLOR_ANIMATION_TILE_BYTES
.tile
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .tile
	ld a, [wFullColorProducerTiles]
	ld c, a
	ld b, 0
	ld hl, FullColorCanaryOverworldTileClasses
	add hl, bc
	ld a, [hl]
	and 7
	ld [wFullColorProducerTiles + FULL_COLOR_ANIMATION_TILE_BYTES], a
	call BuildAndPrepareFullColorAnimationDescriptorSelected
	jp FinishFullColorSemanticSelected

; Carry set if singleton preparation scratch or producer source may still be
; resident. This check happens before producer storage is overwritten.
FullColorProducerStorageAvailableSelected:
	ld a, [wFullColorProducerPending]
	and a
	jr nz, .busy
	ld a, [wRendererAdmissionOpen]
	and a
	jr z, .busy
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .busy
	and a
	ret
.busy
	scf
	ret

BuildAndPrepareFullColorPairedDescriptorSelected:
	call ClearFullColorSemanticDescriptorSelected
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld a, [wFullColorProducerClass]
	ld [hli], a
	call WriteFullColorSemanticDescriptorHeaderSelected
	ld a, [wFullColorProducerWidth]
	ld [hli], a
	ld a, [wFullColorProducerHeight]
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_BG_MAP | FULL_COLOR_RESOURCE_ATTRIBUTES
	ld [hli], a
	xor a
	ld [hli], a
	ld a, [wFullColorRequestStaging]
	ld [hli], a
	ld a, [wFullColorRequestStaging + 1]
	ld [hli], a
	ld a, [wFullColorRequestStaging]
	add a
	ld [hli], a
	ld a, [wFullColorRequestStaging + 1]
	rla
	ld [hli], a
	ld a, [wFullColorProducerFlags]
	ld b, a
	ld a, [wFullColorProducerClass]
	cp FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED
	ld a, b
	jr nz, .flags
	or FULL_COLOR_FLAG_OVERLAY
.flags
	ld [hli], a
	xor a
	ld [hl], a
	jr AdmitPreparedFullColorSemanticSelected

BuildAndPrepareFullColorAnimationDescriptorSelected:
	call ClearFullColorSemanticDescriptorSelected
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld a, FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	ld [hli], a
	call WriteFullColorSemanticDescriptorHeaderSelected
	ld a, [wFullColorProducerWidth]
	ld [hli], a
	ld a, [wFullColorProducerHeight]
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_TILE_DATA | FULL_COLOR_RESOURCE_ATTRIBUTES
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(FULL_COLOR_ANIMATION_EXTENT)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_ANIMATION_EXTENT)
	ld [hli], a
	ld a, LOW(FULL_COLOR_ANIMATION_RESERVATION)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_ANIMATION_RESERVATION)
	ld [hli], a
	xor a
	ld [hli], a
	ld [hl], a
	jr AdmitPreparedFullColorSemanticSelected

; HL points just after class. Writes owner/generation/destination/source.
WriteFullColorSemanticDescriptorHeaderSelected:
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ld [hli], a
	ld de, wRendererGeneration
	REPT 4
		ld a, [de]
		ld [hli], a
		inc de
	ENDR
	ld a, [wFullColorProducerDestination]
	ld [hli], a
	ld a, [wFullColorProducerDestination + 1]
	ld [hli], a
	ld a, LOW(wFullColorProducerTiles)
	ld [hli], a
	ld a, HIGH(wFullColorProducerTiles)
	ld [hli], a
	ret

ClearFullColorSemanticDescriptorSelected:
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	xor a
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ret

AdmitPreparedFullColorSemanticSelected:
	ld de, wFullColorSchedulerEnqueueDescriptor
	call ValidateFullColorRequestResourcesSelected
	jr c, RetainFullColorSemanticSelected
	; Singleton preparation scratch may belong to an earlier visible unit. The
	; new immutable producer descriptor remains queued privately until VBlank.
	ld hl, wFullColorRequestDescriptors
	ld b, FULL_COLOR_REQUEST_CAPACITY
.prepared_scan
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, RetainFullColorSemanticSelected
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	dec b
	jr nz, .prepared_scan
	ld de, wFullColorSchedulerEnqueueDescriptor
	call FindFreeFullColorDescriptorSelected
	jr c, RetainFullColorSemanticSelected
	push hl
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
.copy
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .copy
	pop hl
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, PENDING << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	push hl
	call PrepareFullColorVisibleUnitSelected
	pop hl
	jr c, RetainFullColorSemanticSelected
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld hl, wFullColorRequestCount
	inc [hl]
	ld a, PREPARED
	call RecordFullColorTransitionSelected
	ld a, ACCEPTED
	ret

RetainFullColorSemanticSelected:
	ld hl, wFullColorRetryCounter
	ld a, [hl]
	cp $ff
	jr z, .retry_saturated
	inc [hl]
.retry_saturated
	ld a, TRUE
	ld [wFullColorProducerPending], a
	ld a, DEFERRED
	ret

; Retry the single immutable producer slot. This is called before the owner
; decision on every routed VBlank, so a one-shot movement request cannot be
; lost under preparation pressure. It admits at most one complete unit.
RetryFullColorProducer::
	select_renderer_state_e
	ld a, [wFullColorProducerPending]
	and a
	jr z, .done
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .done
	ld a, [wRendererAdmissionOpen]
	and a
	jr z, .done
	call AdmitPreparedFullColorSemanticSelected
	cp ACCEPTED
	jr nz, .publish
	xor a
	ld [wFullColorProducerPending], a
.publish
	ld [wFullColorLastAdmissionResult], a
	call PublishFullColorSchedulerDebugSelected
.done
	restore_renderer_state_e
	ret

EnqueueFullColorSemantic_defer:
	ld hl, wFullColorRetryCounter
	ld a, [hl]
	cp $ff
	jr z, .saturated
	inc [hl]
.saturated
	ld a, DEFERRED
	; fallthrough
FinishFullColorSemanticSelected:
	ld [wFullColorLastAdmissionResult], a
	ld b, a
	call PublishFullColorSchedulerDebugSelected
	restore_renderer_state_e
	ld a, b
	cp ACCEPTED
	ret z
	scf
	ret

EXPORT EnqueueFullColorMapRow, EnqueueFullColorMapColumn
EXPORT EnqueueFullColorMapConnection, EnqueueFullColorMapRectangle
EXPORT EnqueueFullColorMapOverlay, EnqueueFullColorAnimation
EXPORT EnqueueFullColorMovementRowStrip
EXPORT EnqueueFullColorMovementColumnStrip, RetryFullColorProducer

; Scheduler-owned exact OAM enqueue. HL points to a finished 160-byte batch in
; fixed WRAM. Producers never fabricate descriptors or borrow preparation
; scratch. A returns ACCEPTED/DEFERRED/rejection; carry is clear only on
; ACCEPTED. The reservation remains 200 for batch construction's 40 identity
; lookups even though the visible extent and snapshotted source are 160 bytes.
EnqueueFullColorOAMBatch::
	ld c, l
	ld b, h
	select_renderer_state_e
	ld a, c
	ld [wFullColorActiveDescriptor], a
	ld a, b
	ld [wFullColorActiveDescriptor + 1], a
	ld a, [wRendererAdmissionOpen]
	and a
	jp z, .defer
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jp nz, .wrong_owner
	ld a, [wFullColorRequestCount]
	cp FULL_COLOR_REQUEST_CAPACITY
	jp nc, .defer
	ld a, [wFullColorProducerPending]
	and a
	jp nz, .defer
	; Reject a duplicate OAM resident. A non-OAM PREPARED descriptor owns the
	; shared scratch tail, so defer before snapshotting over it.
	ld hl, wFullColorRequestDescriptors
	ld d, FULL_COLOR_REQUEST_CAPACITY
.resident
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	ld c, a
	cp FULL_COLOR_DESCRIPTOR_FREE
	jr z, .next
	cp COMPLETE << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .next
	cp CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .next
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jp z, .defer
	ld a, c
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jp z, .defer
.next
	ld a, l
	add FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	ld l, a
	jr nc, .next_ready
	inc h
.next_ready
	dec d
	jr nz, .resident
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld d, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	xor a
.clear
	ld [hli], a
	dec d
	jr nz, .clear
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld a, FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	ld [hli], a
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ld [hli], a
	ld de, wRendererGeneration
	ld a, [de]
	ld [hli], a
	inc de
	ld a, [de]
	ld [hli], a
	inc de
	ld a, [de]
	ld [hli], a
	inc de
	ld a, [de]
	ld [hli], a
	ld a, LOW(FULL_COLOR_OAM_DESTINATION)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_OAM_DESTINATION)
	ld [hli], a
	ld a, [wFullColorActiveDescriptor]
	ld [hli], a
	ld a, [wFullColorActiveDescriptor + 1]
	ld [hli], a
	xor a
	ld [hli], a
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_SHADOW_OAM | FULL_COLOR_RESOURCE_HARDWARE_OAM
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(FULL_COLOR_OAM_EXTENT)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_OAM_EXTENT)
	ld [hli], a
	ld a, LOW(FULL_COLOR_OAM_RESERVATION)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_OAM_RESERVATION)
	ld [hli], a
	ld a, FULL_COLOR_FLAG_OAM_FINISHED
	ld [hli], a
	ld a, [wFullColorRetryCounter]
	ld [hl], a
	ld de, wFullColorSchedulerEnqueueDescriptor
	call ValidateFullColorRequestResourcesSelected
	jr c, .defer
	call FindFreeFullColorDescriptorSelected
	jr c, .defer
	push hl
	ld b, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
.copy
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .copy
	pop hl
	ld a, PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT | FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	ld [hl], a
	; Snapshot before return so later sprite authority mutations are irrelevant.
	call PrepareFullColorOAMBatchSelected
	ld hl, wFullColorRequestCount
	inc [hl]
	ld a, PREPARED
	call RecordFullColorTransitionSelected
	ld a, ACCEPTED
	ld [wFullColorLastAdmissionResult], a
	ld b, a
	call PublishFullColorSchedulerDebugSelected
	restore_renderer_state_e
	ld a, b
	and a
	ret
.wrong_owner
	ld a, REJECTED_WRONG_OWNER
	jr .reject
.defer
	ld hl, wFullColorRetryCounter
	ld a, [hl]
	cp $ff
	jr z, .retry_ready
	inc [hl]
.retry_ready
	ld a, DEFERRED
.reject
	ld [wFullColorLastAdmissionResult], a
	ld b, a
	call PublishFullColorSchedulerDebugSelected
	restore_renderer_state_e
	ld a, b
	scf
	ret

EXPORT EnqueueFullColorOAMBatch
AdmitFullColorRequest_wrong_owner:
	ld a, REJECTED_WRONG_OWNER
	jr AdmitFullColorRequest_reject
AdmitFullColorRequest_stale:
	ld a, REJECTED_STALE_GENERATION
	jr AdmitFullColorRequest_reject
AdmitFullColorRequest_defer:
	ld hl, wFullColorRetryCounter
	ld a, [hl]
	cp $ff
	jr z, .retry_saturated
	inc [hl]
.retry_saturated
	ld a, DEFERRED
AdmitFullColorRequest_reject:
	ld [wFullColorLastAdmissionResult], a
	ld b, a
	call PublishFullColorSchedulerDebugSelected
	restore_renderer_state_e
	ld a, b
	scf
	ret

; DE candidate. Validate the exact class contract. This routine is also called
; immediately before COMMITTING, so mutation of any asserted field cannot turn
; into a visible write.
ValidateFullColorRequestResourcesSelected:
	push de
	ld a, [de]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld hl, FULL_COLOR_DESCRIPTOR_RESOURCE_MASK
	add hl, de
	ld a, b
	cp FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	jp z, .bg_palette
	cp FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
	jp z, .obj_palette
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jp z, .oam
	cp FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	jp z, .animation
	; Every map class is a paired tile/attribute unit.
	ld a, [hli]
	cp FULL_COLOR_RESOURCE_BG_MAP | FULL_COLOR_RESOURCE_ATTRIBUTES
	jp nz, .invalid
	ld a, [hl]
	and a
	jp nz, .invalid
	; Destination must be one of the two 32x32 BG maps.
	push de
	ld hl, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	ld e, a
	ld d, [hl]
	ld a, d
	cp HIGH(FULL_COLOR_BG_MAP_FIRST)
	jp c, .map_destination_invalid
	cp HIGH(FULL_COLOR_BG_MAP_LAST + 1)
	jp nc, .map_destination_invalid
	pop de
	; Geometry is width/height in desired state, each 1..32.
	ld hl, FULL_COLOR_DESCRIPTOR_DESIRED_STATE
	add hl, de
	ld a, [hli]
	and a
	jp z, .invalid
	cp 33
	jp nc, .invalid
	ld c, a ; width
	ld a, [hl]
	and a
	jp z, .invalid
	cp 33
	jp nc, .invalid
	ld h, a ; height
	ld a, b
	cp FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jr nz, .not_row
	ld a, h
	cp 1
	jr z, .not_row
	cp 2
	jp nz, .invalid
	push hl
	ld hl, FULL_COLOR_DESCRIPTOR_FLAGS
	add hl, de
	bit 3, [hl]
	pop hl
	jp z, .invalid
	ld a, c
	cp SCREEN_WIDTH
	jp nz, .invalid
.not_row
	ld a, b
	cp FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jr nz, .geometry_product
	ld a, c
	cp 1
	jr z, .geometry_product
	cp 2
	jp nz, .invalid
	push hl
	ld hl, FULL_COLOR_DESCRIPTOR_FLAGS
	add hl, de
	bit 3, [hl]
	pop hl
	jp z, .invalid
	ld a, h
	cp SCREEN_HEIGHT
	jp nz, .invalid
.geometry_product
	; BC = width * height (at most 1024).
	ld b, 0
	ld d, 0
	ld e, c
.multiply
	ld a, h
	and a
	jr z, .product_ready
	ld a, c
	add b
	ld b, a
	jr nc, .multiply_no_carry
	inc d
.multiply_no_carry
	dec h
	jr .multiply
.product_ready
	ld c, b
	ld b, d
	ld a, b
	cp HIGH(SCREEN_AREA)
	jp c, .product_in_scratch
	jp nz, .invalid
	ld a, c
	cp LOW(SCREEN_AREA + 1)
	jp nc, .invalid
.product_in_scratch
	; Extent must equal the computed cell count.
	; DE was consumed by multiplication; restore descriptor first.
	pop de
	push de
	ld hl, FULL_COLOR_DESCRIPTOR_EXTENT
	add hl, de
	ld a, [hli]
	cp c
	jp nz, .invalid
	ld a, [hl]
	cp b
	jp nz, .invalid
	; Minimum reservation is two writes per cell.
	sla c
	rl b
	jp c, .invalid
	inc hl
	ld a, [hli]
	ld e, a
	ld d, [hl]
	ld a, d
	cp b
	jp nz, .invalid
	ld a, e
	cp c
	jp nz, .invalid
	jp .valid
.map_destination_invalid
	pop de
	jp .invalid
.bg_palette
	ld c, LOW(FULL_COLOR_BG_PALETTE_DESTINATION)
	ld b, HIGH(FULL_COLOR_BG_PALETTE_DESTINATION)
	jr .palette
.obj_palette
	ld c, LOW(FULL_COLOR_OBJ_PALETTE_DESTINATION)
	ld b, HIGH(FULL_COLOR_OBJ_PALETTE_DESTINATION)
.palette
	ld a, [hli]
	cp FULL_COLOR_RESOURCE_PALETTES
	jp nz, .invalid
	ld a, [hl]
	and a
	jp nz, .invalid
	ld hl, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	cp c
	jp nz, .invalid
	ld a, [hl]
	cp b
	jp nz, .invalid
	ld bc, FULL_COLOR_PALETTE_EXTENT
	ld hl, FULL_COLOR_DESCRIPTOR_EXTENT
	add hl, de
	call ValidateFullColorExactExtentAndMinimumSelected
	jr c, .invalid
	jp .valid
.oam
	ld a, [hli]
	cp FULL_COLOR_RESOURCE_SHADOW_OAM | FULL_COLOR_RESOURCE_HARDWARE_OAM
	jr nz, .invalid
	ld a, [hl]
	and a
	jr nz, .invalid
	ld hl, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	cp LOW(FULL_COLOR_OAM_DESTINATION)
	jr nz, .invalid
	ld a, [hl]
	cp HIGH(FULL_COLOR_OAM_DESTINATION)
	jr nz, .invalid
	ld hl, FULL_COLOR_DESCRIPTOR_EXTENT
	add hl, de
	ld a, [hli]
	cp LOW(FULL_COLOR_OAM_EXTENT)
	jr nz, .invalid
	ld a, [hli]
	cp HIGH(FULL_COLOR_OAM_EXTENT)
	jr nz, .invalid
	; OAM includes forty identity lookups in its measured reservation.
	ld a, [hli]
	cp LOW(FULL_COLOR_OAM_RESERVATION)
	jr nz, .invalid
	ld a, [hl]
	cp HIGH(FULL_COLOR_OAM_RESERVATION)
	jr nz, .invalid
	jr .valid
.animation
	ld a, [hli]
	cp FULL_COLOR_RESOURCE_TILE_DATA | FULL_COLOR_RESOURCE_ATTRIBUTES
	jr nz, .invalid
	ld a, [hl]
	and a
	jr nz, .invalid
	; Sixteen tile bytes may start only where the whole tile remains in VRAM.
	ld hl, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	ld c, a
	ld a, [hl]
	cp HIGH(FULL_COLOR_TILE_DATA_FIRST)
	jr c, .invalid
	cp $98
	jr nc, .invalid
	cp HIGH(FULL_COLOR_TILE_DATA_LAST_START)
	jr nz, .animation_attr
	ld a, c
	cp LOW(FULL_COLOR_TILE_DATA_LAST_START + 1)
	jr nc, .invalid
.animation_attr
	ld hl, FULL_COLOR_DESCRIPTOR_DESIRED_STATE
	add hl, de
	ld a, [hli]
	ld c, a
	ld a, [hl]
	cp HIGH(FULL_COLOR_BG_MAP_FIRST)
	jr c, .invalid
	cp HIGH(FULL_COLOR_BG_MAP_LAST + 1)
	jr nc, .invalid
	ld bc, FULL_COLOR_ANIMATION_EXTENT
	ld hl, FULL_COLOR_DESCRIPTOR_EXTENT
	add hl, de
	call ValidateFullColorExactExtentAndMinimumSelected
	jr c, .invalid
.valid
	pop de
	and a
	ret
.invalid
	pop de
	scf
	ret

; HL extent, BC exact extent and reservation. Returns HL on extent high.
ValidateFullColorExactExtentAndMinimumSelected:
	ld a, [hli]
	cp c
	jr nz, .bad
	ld a, [hl]
	cp b
	jr nz, .bad
	inc hl
	ld a, [hli]
	cp c
	jr nz, .bad
	ld a, [hl]
	cp b
	jr nz, .bad
.ok
	and a
	ret
.bad
	scf
	ret

; Input DE candidate. Output carry clear if equivalent resident request exists.
FindEquivalentFullColorRequestSelected:
	ld hl, wFullColorRequestDescriptors
	ld c, FULL_COLOR_REQUEST_CAPACITY
.next
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp COMPLETE << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .skip
	cp CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .skip
	cp FULL_COLOR_DESCRIPTOR_FREE
	jr z, .skip
	ld a, [de]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jr z, .not_equivalent
	; A resident may have changed after admission. Never let an invalid resident
	; absorb a valid retry. Cancel malformed work before comparing identity so
	; its slot and request count are immediately reusable by this admission.
	push bc
	push hl
	push de
	ld d, h
	ld e, l
	call ValidateFullColorRequestResourcesSelected
	pop de
	pop hl
	pop bc
	jr nc, .resident_valid
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld a, [wFullColorRequestCount]
	and a
	jr z, .record_invalid_resident
	dec a
	ld [wFullColorRequestCount], a
.record_invalid_resident
	push bc
	push de
	push hl
	ld a, CANCELLED
	call RecordFullColorTransitionSelected
	pop hl
	pop de
	pop bc
	jr .skip
.resident_valid
	ld a, [de]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp b
	jr nz, .skip
	; Final-state identity: owner/generation, destination, desired state,
	; visible extent, and flags. Source bytes are deliberately not an oracle.
	push hl
	push de
	inc hl
	inc de
	ld b, 7
	call CompareFullColorBytesSelected
	jr nz, .different
	inc hl ; skip source pointer
	inc hl
	inc de
	inc de
	ld b, 2
	call CompareFullColorBytesSelected ; desired state
	jr nz, .different
	inc hl ; skip resources
	inc hl
	inc de
	inc de
	ld b, 2
	call CompareFullColorBytesSelected ; extent/boundary
	jr nz, .different
	inc hl ; skip reservation
	inc hl
	inc de
	inc de
	ld b, 1
	call CompareFullColorBytesSelected ; flags
	jr nz, .different
	pop de
	pop hl
	and a
	ret
.different
	pop de
	pop hl
.skip
	push de
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	pop de
	dec c
	jp nz, .next
.not_equivalent
	scf
	ret

CompareFullColorBytesSelected:
.byte
	ld a, [de]
	cp [hl]
	ret nz
	inc de
	inc hl
	dec b
	jr nz, .byte
	ret

; Input DE remains candidate. Output HL free descriptor.
FindFreeFullColorDescriptorSelected:
	push de
	call LoadFullColorCursorDescriptorSelected
	pop de
	ld b, FULL_COLOR_REQUEST_CAPACITY
.next
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp FULL_COLOR_DESCRIPTOR_FREE
	jr z, .found
	cp COMPLETE << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .found
	cp CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .found
	push de
	call AdvanceFullColorDescriptorPointerSelected
	pop de
	dec b
	jr nz, .next
	scf
	ret
.found
	and a
	ret

PrepareNextFullColorRequest::
	select_renderer_state_e
	call PrepareNextFullColorRequestSelected
	restore_renderer_state_e
	ret

PrepareNextFullColorRequestSelected:
	call LoadFullColorCursorDescriptorSelected
	ld b, FULL_COLOR_REQUEST_CAPACITY
.prepared_scan
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .busy
	call AdvanceFullColorDescriptorPointerSelected
	dec b
	jr nz, .prepared_scan
	call LoadFullColorCursorDescriptorSelected
	ld b, FULL_COLOR_REQUEST_CAPACITY
.next
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PENDING << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .prepare
	call AdvanceFullColorDescriptorPointerSelected
	dec b
	jr nz, .next
	scf
	ret
.prepare
	push hl
	call PrepareFullColorVisibleUnitSelected
	pop hl
	jr c, .failed
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld a, PREPARED
	call RecordFullColorTransitionSelected
	and a
	ret
.failed
	scf
	ret
.busy
	scf
	ret

RunFullColorSchedulerSelected::
	; The preparation scratch is a singleton. Commit/revalidate its current
	; owner before preparing another descriptor, then process at most one unit.
	call LoadFullColorCursorDescriptorSelected
	ld b, FULL_COLOR_REQUEST_CAPACITY
.prepared_scan
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .revalidate
	call AdvanceFullColorDescriptorPointerSelected
	dec b
	jr nz, .prepared_scan
	call PrepareNextFullColorRequestSelected
	ret c
	call LoadFullColorCursorDescriptorSelected
	ld b, FULL_COLOR_REQUEST_CAPACITY
.scan_new
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .revalidate
	call AdvanceFullColorDescriptorPointerSelected
	dec b
	jr nz, .scan_new
	ret
.revalidate
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
IF DEF(PHASE2_AUDIT)
	jr nz, CancelFullColorDescriptorStaleSelected
ELSE
	jp nz, CancelFullColorDescriptorStaleSelected
ENDC
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_OWNER
	add hl, de
	ld a, [hli]
	cp RENDERER_FULL_COLOR_OVERWORLD
IF DEF(PHASE2_AUDIT)
	jr nz, .cancel_pop
ELSE
	jp nz, FullColorCancelPop
ENDC
	ld de, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	cp [hl]
IF DEF(PHASE2_AUDIT)
	jr nz, .cancel_pop
ELSE
	jp nz, FullColorCancelPop
ENDC
	inc de
	inc hl
	dec b
	jr nz, .generation
	pop hl
	; Revalidate class extent, reservation, resources, geometry and destination
	; from the resident descriptor immediately before the visible boundary.
	push hl
	ld d, h
	ld e, l
	call ValidateFullColorRequestResourcesSelected
	pop hl
IF DEF(PHASE2_AUDIT)
	jr c, CancelFullColorDescriptorStaleSelected
ELSE
	jp c, CancelFullColorDescriptorStaleSelected
ENDC
	; Required resources must be a subset of the currently available set.
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_RESOURCE_MASK
	add hl, de
	ld a, [hli]
	ld c, a
	ld a, [wFullColorAvailableResources]
	and c
	cp c
	jr nz, .defer_pop
	ld a, [hl]
	ld c, a
	ld a, [wFullColorAvailableResources + 1]
	and c
	cp c
	jr nz, .defer_pop
	inc hl
	inc hl
	inc hl ; reservation low byte
	ld c, [hl]
	inc hl
	ld a, [wFullColorCommitBudget + 1]
	cp [hl] ; compare high byte first
	jr c, .defer_pop
	jr nz, .budget_ok
	ld a, [wFullColorCommitBudget]
	cp c
	jr c, .defer_pop
.budget_ok
	pop hl
	; The normal-debug core-cycle authority brackets the exact commit and then
	; exercises a second, synthetic admission at threshold + 1. SameBoy writes
	; the host-derived probe only after calibration; a nonzero probe must defer
	; before this second attempt can enter COMMITTING.
IF !DEF(PHASE2_AUDIT)
	push hl
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	call SelectFullColorRuntimeTimingRowSelected
	call BeginFullColorRuntimeTimingSampleSelected
	pop hl
	push af
ENDC
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, COMMITTING << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld a, COMMITTING
	push hl
	call RecordFullColorTransitionSelected
	pop hl
	call CommitFullColorVisibleUnitSelected
IF !DEF(PHASE2_AUDIT)
	pop af
	jr c, .timing_done
	push hl
	call EndFullColorRuntimeTimingSampleSelected
	pop hl
.timing_done
ENDC
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, COMPLETE << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld a, COMPLETE
	call RecordFullColorTransitionSelected
	ld hl, wFullColorRequestCount
	dec [hl]
	call AdvanceFullColorRequestCursorSelected
	call PublishFullColorSchedulerDebugSelected
	ret
.defer_pop
	pop hl
	ret

IF !DEF(PHASE2_AUDIT)
; Input A=request class. Output A=canonical timing row or zero when the work is
; deliberately measured inside its containing transfer/VBlank unit.
SelectFullColorRuntimeTimingRowSelected:
	cp FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	jr z, .bg
	cp FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
	jr z, .obj
	cp FULL_COLOR_REQUEST_MAP_ROW_PAIRED
	jr z, .horizontal
	cp FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jr z, .vertical
	cp FULL_COLOR_REQUEST_MAP_CONNECTION_PAIRED
	jr z, .connection
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jr z, .oam
	xor a
	ret
.bg
	ld a, FULL_COLOR_TIMING_ROW_PALETTE_BG
	ret
.obj
	ld a, FULL_COLOR_TIMING_ROW_PALETTE_OBJ
	ret
.horizontal
	ld a, FULL_COLOR_TIMING_ROW_STREAM_HORIZONTAL
	ret
.vertical
	ld a, FULL_COLOR_TIMING_ROW_STREAM_VERTICAL
	ret
.connection
	ld a, FULL_COLOR_TIMING_ROW_STREAM_CONNECTION
	ret
.oam
	ld a, FULL_COLOR_TIMING_ROW_OAM_MAXIMUM
	ret

; Input A=row. The calibration and sample use the same two marker writes; the
; only difference between them is the exact operation between sample markers.
BeginFullColorRuntimeTimingSampleSelected::
	and a
	jr z, .skip
	ld c, a
	ld a, [wFullColorRuntimeTimingInitialized]
	cp $a7
	jr z, .initialized
	push bc
	ld hl, wFullColorRuntimeTimingEvent
	ld bc, wFullColorRuntimeTimingInitialized + 1 - wFullColorRuntimeTimingEvent
	xor a
	call FillMemory
	ld a, $a7
	ld [wFullColorRuntimeTimingInitialized], a
	pop bc
.initialized
	ld a, [wFullColorRuntimeTimingActive]
	and a
	jr nz, .skip
	ld b, 0
	ld hl, wFullColorRuntimeTimingSeenRows
	add hl, bc
	ld a, [hl]
	and a
	jr nz, .skip
	inc [hl]
	ld a, 1
	ld [wFullColorRuntimeTimingActive], a
	ld a, c
	ld [wFullColorRuntimeTimingRow], a
	ld hl, wFullColorRuntimeTimingSequence
	inc [hl]
	jr nz, :+
	inc hl
	inc [hl]
:
	xor a
	ld [wFullColorRuntimeTimingProbeResult], a
	ld [wFullColorRuntimeTimingProbeCycles], a
	ld [wFullColorRuntimeTimingProbeCycles + 1], a
	ld [wFullColorRuntimeTimingProbeCycles + 2], a
	ld [wFullColorRuntimeTimingProbeCycles + 3], a
	ld a, FULL_COLOR_TIMING_EVENT_CALIBRATION_START
	ld [wFullColorRuntimeTimingEvent], a
	ld a, FULL_COLOR_TIMING_EVENT_CALIBRATION_END
	ld [wFullColorRuntimeTimingEvent], a
	ld a, FULL_COLOR_TIMING_EVENT_SAMPLE_START
	ld [wFullColorRuntimeTimingEvent], a
	and a
	ret
.skip
	scf
	ret

EndFullColorRuntimeTimingSampleSelected::
	ld a, [wFullColorRuntimeTimingRow]
	and a
	ret z
	ld a, FULL_COLOR_TIMING_EVENT_SAMPLE_END
	ld [wFullColorRuntimeTimingEvent], a
	ld a, FULL_COLOR_TIMING_EVENT_THRESHOLD_START
	ld [wFullColorRuntimeTimingEvent], a
	ld a, [wFullColorRuntimeTimingProbeResult]
	cp FULL_COLOR_TIMING_PROBE_ENTERED_COMMITTING
	jr z, .entered_committing
	ld hl, wFullColorRuntimeTimingProbeCycles
	ld a, [hli]
	or [hl]
	inc hl
	or [hl]
	inc hl
	or [hl]
	jr z, .no_host_probe
	ld a, FULL_COLOR_TIMING_PROBE_DEFERRED
	ld [wFullColorRuntimeTimingProbeResult], a
	ld a, FULL_COLOR_TIMING_EVENT_THRESHOLD_DEFER
	ld [wFullColorRuntimeTimingEvent], a
	jr .done
.entered_committing
	ld a, FULL_COLOR_TIMING_EVENT_THRESHOLD_COMMITTING
	ld [wFullColorRuntimeTimingEvent], a
	jr .done
.no_host_probe
	; Ordinary emulators do not inject a threshold probe. Leave the observation
	; neutral rather than turning debug gameplay into a timing-test dependency.
	xor a
	ld [wFullColorRuntimeTimingEvent], a
.done
	xor a
	ld [wFullColorRuntimeTimingActive], a
	ret
ENDC
IF DEF(PHASE2_AUDIT)
.cancel_pop
ELSE
FullColorCancelPop:
ENDC
	pop hl
	; fallthrough
CancelFullColorDescriptorStaleSelected:
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld b, a
	ld a, CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or b
	ld [hl], a
	ld a, CANCELLED
	call RecordFullColorTransitionSelected
	ld hl, wFullColorRequestCount
	dec [hl]
	call AdvanceFullColorRequestCursorSelected
	ret

CancelFullColorSchedulerSelected::
	ld hl, wFullColorRequestDescriptors
	ld b, FULL_COLOR_REQUEST_CAPACITY
.next
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_STATE_MASK
	cp PENDING << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr z, .cancel
	cp PREPARED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	jr nz, .skip
.cancel
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	ld c, a
	ld a, CANCELLED << FULL_COLOR_DESCRIPTOR_STATE_SHIFT
	or c
	ld [hl], a
	ld a, CANCELLED
	push hl
	call RecordFullColorTransitionSelected
	pop hl
.skip
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	dec b
	jr nz, .next
	xor a
	ld [wFullColorRequestCount], a
	ld [wFullColorRequestCursor], a
IF !DEF(PHASE2_AUDIT)
	; Cancellation invalidates the retained singleton as well as resident
	; descriptors. Otherwise a pre-handoff row or column can be retried after a
	; later generation takes ownership. Party-return authority is separate and
	; deliberately remains intact.
	ld [wFullColorProducerPending], a
	ld [wFullColorProducerClass], a
	ld [wFullColorProducerFlags], a
	ld [wFullColorProducerWidth], a
	ld [wFullColorProducerHeight], a
	ld [wFullColorProducerSource], a
	ld [wFullColorProducerSource + 1], a
	ld [wFullColorProducerDestination], a
	ld [wFullColorProducerDestination + 1], a
ENDC
	ret

LoadFullColorCursorDescriptorSelected:
	ld hl, wFullColorRequestDescriptors
	ld a, [wFullColorRequestCursor]
	and a
	ret z
	ld c, a
.offset
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	dec c
	jr nz, .offset
	ret

AdvanceFullColorDescriptorPointerSelected:
	ld de, FULL_COLOR_REQUEST_DESCRIPTOR_BYTES
	add hl, de
	ld a, h
	cp HIGH(wFullColorRequestDescriptorsEnd)
	ret nz
	ld a, l
	cp LOW(wFullColorRequestDescriptorsEnd)
	ret nz
	ld hl, wFullColorRequestDescriptors
	ret

AdvanceFullColorRequestCursorSelected:
	ld hl, wFullColorRequestCursor
	inc [hl]
	ld a, [hl]
	cp FULL_COLOR_REQUEST_CAPACITY
	ret c
	xor a
	ld [hl], a
	ret

RecordFullColorTransitionSelected:
	ld c, a
	ld a, [wFullColorTransitionCount]
	cp 8
	jr nc, .count_only
	ld e, a
	ld d, 0
	ld hl, wFullColorTransitionLog
	add hl, de
	ld [hl], c
.count_only
	ld hl, wFullColorTransitionCount
	ld a, [hl]
	cp $ff
	ret z
	inc [hl]
	ret

PublishFullColorSchedulerDebugSelected:
	; rRAMG/rRAMB are write-only on the cartridge. Until the repository has a
	; global tracked SRAM-state ABI, Phase 2 observability remains in owned WRAM
	; and must not guess that SRAM was disabled/bank zero on entry.
	ld a, [wFullColorRequestCount]
	ld [wFullColorTimingState], a
	ld a, [wFullColorRetryCounter]
	ld [wFullColorTimingState + 1], a
	ld a, [wFullColorLastAdmissionResult]
	ld [wFullColorTimingState + 2], a
	ld a, [wFullColorTransitionCount]
	ld [wFullColorTimingState + 3], a
	ret
