; Phase 2 measured request scheduler.
;
; Admission ABI: HL points at a 20-byte candidate descriptor in fixed WRAM.
; The low nibble of byte 0 is the request class; state bits are ignored.
; A returns ACCEPTED/COALESCED/DEFERRED or a stable rejection code. Carry is
; set for every result other than ACCEPTED/COALESCED. Required work is never
; dropped: DEFERRED increments the observable retry token.

RouteRendererOwnershipVBlank::
IF DEF(_DEBUG)
	call PollFullColorDebugCommand
ENDC
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
	jp z, .defer
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	ld a, [de]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp NUM_FULL_COLOR_REQUEST_CLASSES
	jr nc, .defer
	inc de
	ld a, [de]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	inc de
	ld hl, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	cp [hl]
	jr nz, .stale
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
	jr c, .defer
	call FindEquivalentFullColorRequestSelected
	jr nc, .coalesced
	ld a, [wFullColorRequestCount]
	cp FULL_COLOR_REQUEST_CAPACITY
	jr nc, .defer
	call FindFreeFullColorDescriptorSelected
	jr c, .defer
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
.wrong_owner
	ld a, REJECTED_WRONG_OWNER
	jr .reject
.stale
	ld a, REJECTED_STALE_GENERATION
	jr .reject
.defer
	ld hl, wFullColorRetryCounter
	ld a, [hl]
	cp $ff
	jr z, .retry_saturated
	inc [hl]
.retry_saturated
	ld a, DEFERRED
.reject
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
	jp nz, .invalid
.not_row
	ld a, b
	cp FULL_COLOR_REQUEST_MAP_COLUMN_PAIRED
	jr nz, .geometry_product
	ld a, c
	cp 1
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
	jr nz, CancelFullColorDescriptorStaleSelected
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_OWNER
	add hl, de
	ld a, [hli]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .cancel_pop
	ld de, wRendererGeneration
	ld b, 4
.generation
	ld a, [de]
	cp [hl]
	jr nz, .cancel_pop
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
	jr c, CancelFullColorDescriptorStaleSelected
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
.cancel_pop
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
