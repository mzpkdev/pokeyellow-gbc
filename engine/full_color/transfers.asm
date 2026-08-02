; Class-specific complete visible units. Map requests encode width/height in
; desired-state and commit with the hardware 32-byte BG-map stride. The source
; owns both planes: extent tile bytes followed by extent attribute bytes.

PrepareFullColorPairedTransferSelected::
	ld a, l
	ld [wFullColorActiveDescriptor], a
	ld a, h
	ld [wFullColorActiveDescriptor + 1], a
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_EXTENT
	add hl, de
	ld a, [hli]
	ld c, a
	ld b, [hl]
	pop hl
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_SOURCE
	add hl, de
	ld a, [hli]
	ld d, [hl]
	ld e, a
	pop hl
	; Freeze the complete tile plane in the 360-byte rectangle buffer.
	push hl
	push bc
	ld hl, wFullColorAttributeRectangle
.tile
	ld a, b
	or c
	jr z, .tile_done
	ld a, [de]
	ld [hli], a
	inc de
	dec bc
	jr .tile
.tile_done
	pop bc
	pop hl
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp FULL_COLOR_REQUEST_MAP_OVERLAY_PAIRED
	jr nz, .normal
	ld a, 1
	jr .mode
.normal
	xor a
.mode
	ld [wFullColorRequestStaging], a
	ld a, [wFullColorRequestStaging]
	and a
	jr z, .attributes_ready
	ld de, wFullColorAttributeRectangle
.attributes_ready
	; The second frozen plane uses the four palette buffers followed by the
	; first 104 bytes of the OAM buffer. Singleton preparation makes that union
	; safe and keeps the measured scratch allocation unchanged.
	ld hl, wFullColorBGPaletteBase
.attribute
	ld a, b
	or c
	jr z, .done
	ld a, h
	cp HIGH(wFullColorAttributeRectangle)
	jr nz, .attribute_source
	ld a, l
	cp LOW(wFullColorAttributeRectangle)
	jr nz, .attribute_source
	ld hl, wFullColorShadowOAMBatch
.attribute_source
	ld a, [wFullColorRequestStaging]
	and a
	jr z, .owned_attribute
	ld a, [de]
	and 7
	jr .store
.owned_attribute
	ld a, [de]
	and $ef
.store
	ld [hli], a
	inc de
	dec bc
	jr .attribute
.done
	ld a, [wFullColorActiveDescriptor]
	ld l, a
	ld a, [wFullColorActiveDescriptor + 1]
	ld h, a
	and a
	ret

PrepareFullColorAnimationReplacementSelected::
	ld a, l
	ld [wFullColorActiveDescriptor], a
	ld a, h
	ld [wFullColorActiveDescriptor + 1], a
	ld de, FULL_COLOR_DESCRIPTOR_SOURCE
	add hl, de
	ld a, [hli]
	ld d, [hl]
	ld e, a
	ld hl, FULL_COLOR_ANIMATION_TILE_BYTES
	add hl, de
	ld a, [hl]
	and $ef
	ld [wFullColorAttributeRectangle], a
	; Freeze all tile bytes too; COMMITTING must never reread caller storage.
	ld hl, wFullColorBGPaletteBase
	ld b, FULL_COLOR_ANIMATION_TILE_BYTES
.tile
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .tile
	ld a, [wFullColorActiveDescriptor]
	ld l, a
	ld a, [wFullColorActiveDescriptor + 1]
	ld h, a
	and a
	ret

CommitFullColorPairedTransferSelected::
	ld a, l
	ld [wFullColorActiveDescriptor], a
	ld a, h
	ld [wFullColorActiveDescriptor + 1], a
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_DESIRED_STATE
	add hl, de
	ld a, [hli]
	ld [wFullColorRequestStaging], a ; width
	ld a, [hl]
	ld [wFullColorRequestStaging + 1], a ; height
	pop hl
	ld de, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	ld h, [hl]
	ld l, a
	ld de, wFullColorAttributeRectangle
	xor a
	ld [wFullColorRequestStaging + 2], a
	ld a, h
	and $fc
	ld [wFullColorTimingState], a ; selected map base high
	ldh a, [rVBK]
	ld [wFullColorTimingState + 1], a
	xor a
	ldh [rVBK], a
	call CommitFullColorMapPlaneSelected
	ld a, 1
	ldh [rVBK], a
	ld de, wFullColorBGPaletteBase
	ld [wFullColorRequestStaging + 2], a
	call LoadFullColorActiveMapDestinationSelected
	call CommitFullColorMapPlaneSelected
	ld a, [wFullColorTimingState + 1]
	ldh [rVBK], a
	call LoadFullColorActiveDescriptorSelected
	ret

; DE packed source, HL first destination. Width/height are in staging.
CommitFullColorMapPlaneSelected:
	ld a, l
	ld [wFullColorRequestStaging + 3], a
	ld a, h
	ld [wFullColorRequestStaging + 4], a
	ld a, [wFullColorRequestStaging + 1]
	ld c, a
.row
	ld a, [wFullColorRequestStaging + 3]
	ld l, a
	ld a, [wFullColorRequestStaging + 4]
	ld h, a
	ld a, [wFullColorRequestStaging]
	ld b, a
.cell
	ld a, [wFullColorRequestStaging + 2]
	and a
	jr z, .load
	ld a, d
	cp HIGH(wFullColorAttributeRectangle)
	jr nz, .load
	ld a, e
	cp LOW(wFullColorAttributeRectangle)
	jr nz, .load
	ld de, wFullColorShadowOAMBatch
.load
	ld a, [de]
	ld [hl], a
	inc de
	call AdvanceFullColorMapCellSelected
	dec b
	jr nz, .cell
	ld a, [wFullColorRequestStaging + 3]
	ld l, a
	ld a, [wFullColorRequestStaging + 4]
	ld h, a
	call AdvanceFullColorMapRowSelected
	ld a, l
	ld [wFullColorRequestStaging + 3], a
	ld a, h
	ld [wFullColorRequestStaging + 4], a
	dec c
	jr nz, .row
	ret

AdvanceFullColorMapCellSelected:
	inc hl
	ld a, [wFullColorTimingState]
	add 4
	cp h
	ret nz
	ld a, [wFullColorTimingState]
	ld h, a
	ret

AdvanceFullColorMapRowSelected:
	ld a, l
	add 32
	ld l, a
	jr nc, .range
	inc h
.range
	ld a, [wFullColorTimingState]
	add 4
	cp h
	ret nz
	ld a, [wFullColorTimingState]
	ld h, a
	ret

LoadFullColorActiveDescriptorSelected:
	ld a, [wFullColorActiveDescriptor]
	ld l, a
	ld a, [wFullColorActiveDescriptor + 1]
	ld h, a
	ret

LoadFullColorActiveMapDestinationSelected:
	call LoadFullColorActiveDescriptorSelected
	ld bc, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, bc
	ld a, [hli]
	ld h, [hl]
	ld l, a
	ret

CommitFullColorAnimationReplacementSelected::
	ld a, l
	ld [wFullColorActiveDescriptor], a
	ld a, h
	ld [wFullColorActiveDescriptor + 1], a
	ld de, FULL_COLOR_DESCRIPTOR_DESTINATION
	add hl, de
	ld a, [hli]
	ld h, [hl]
	ld l, a
	ld de, wFullColorBGPaletteBase
	ldh a, [rVBK]
	ld [wFullColorTimingState + 1], a
	xor a
	ldh [rVBK], a
	ld b, FULL_COLOR_ANIMATION_TILE_BYTES
.tile
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .tile
	ld a, 1
	ldh [rVBK], a
	call LoadFullColorActiveDescriptorSelected
	ld bc, FULL_COLOR_DESCRIPTOR_DESIRED_STATE
	add hl, bc
	ld a, [hli]
	ld h, [hl]
	ld l, a
	ld a, [wFullColorAttributeRectangle]
	ld [hl], a
	ld a, [wFullColorTimingState + 1]
	ldh [rVBK], a
	call LoadFullColorActiveDescriptorSelected
	ret

ASSERT wFullColorBGPaletteBase + 256 == wFullColorAttributeRectangle
ASSERT wFullColorAttributeRectangle + SCREEN_AREA == wFullColorShadowOAMBatch
ASSERT 256 + 104 == SCREEN_AREA
