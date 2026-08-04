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
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
	ld hl, wFullColorPairedScratchTail
	ELSE
	ld hl, wFullColorShadowOAMBatch
	ENDC
.attribute_source
	ld a, [de]
	and $ef
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
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
.firstPlane
ENDC
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
	call CommitFullColorProductionMapPlaneSelected
ELSE
	call CommitFullColorMapPlaneSelected
ENDC
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
.firstPlaneComplete
ENDC
	ld a, 1
	ldh [rVBK], a
	ld de, wFullColorBGPaletteBase
	ld [wFullColorRequestStaging + 2], a
	call LoadFullColorActiveMapDestinationSelected
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
.secondPlane
ENDC
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
	call CommitFullColorProductionMapPlaneSelected
ELSE
	call CommitFullColorMapPlaneSelected
ENDC
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
.secondPlaneComplete
ENDC
	ld a, [wFullColorTimingState + 1]
	ldh [rVBK], a
	call LoadFullColorActiveDescriptorSelected
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
.complete
ENDC
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
	IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
	ld de, wFullColorPairedScratchTail
	ELSE
	ld de, wFullColorShadowOAMBatch
	ENDC
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
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
ASSERT wFullColorAttributeRectangle + SCREEN_AREA == wFullColorPairedScratchTail
ELSE
ASSERT wFullColorAttributeRectangle + SCREEN_AREA == wFullColorShadowOAMBatch
ENDC
ASSERT 256 + 104 == SCREEN_AREA

IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
PUSHS
SECTION "Full Color Production Animation Producer", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]
; Returns BC at the first visible occurrence of the tile identity in A. The
; destination walks the same 32x32 hardware map geometry as paired commits.
FindFullColorProductionAnimatedTileSelected:
	ld [wFullColorProducerWidth], a
	ld a, [wFullColorAuthorityVRAMView]
	ld c, a
	ld a, [wFullColorAuthorityVRAMView + 1]
	ld b, a
	and $fc
	ld [wFullColorTimingState], a
	ld hl, wTileMap
	ld d, SCREEN_HEIGHT
.row
	ld e, SCREEN_WIDTH
.cell
	ld a, [wFullColorProducerWidth]
	cp [hl]
	jr z, .found
	inc hl
	call AdvanceFullColorProductionAttributeDestinationSelected
	dec e
	jr nz, .cell
	ld e, TILEMAP_WIDTH - SCREEN_WIDTH
.row_stride
	call AdvanceFullColorProductionAttributeDestinationSelected
	dec e
	jr nz, .row_stride
	dec d
	jr nz, .row
	scf
	ret
.found
	and a
	ret

AdvanceFullColorProductionAttributeDestinationSelected:
	inc bc
	ld a, [wFullColorTimingState]
	add 4
	cp b
	ret nz
	ld b, a
	sub 4
	ld b, a
	ret

; Queue the native overworld water animation or flower field replacement as a
; paired tile-data/attribute unit. Yellow's UpdateMovingBgTiles is not reached
; on the Color route, so this root owns both its counters and visible writes.
ProduceFullColorProductionAnimatedTileSelected:
	call FullColorProducerStorageAvailableSelected
	jp c, .deferred
	ldh a, [hTileAnimations]
	and a
	jp z, .none
	ldh a, [hMovingBGTilesCounter1]
	inc a
	ldh [hMovingBGTilesCounter1], a
	cp 20
	jp c, .none
	cp 21
	jr z, .flower

; Water: derive the next immutable 16-byte tile from current bank-0 graphics.
	ld a, [wMovingBGTilesCounter2]
	inc a
	and 7
	ld [wMovingBGTilesCounter2], a
	and 4
	ld [wFullColorProducerFlags], a
	ld a, $14
	call FindFullColorProductionAnimatedTileSelected
	jr c, .water_counter
	ld a, c
	ld [wFullColorProducerWidth], a
	ld a, b
	ld [wFullColorProducerHeight], a
	ldh a, [rVBK]
	push af
	xor a
	ldh [rVBK], a
	ld hl, vTileset tile $14
	ld de, wFullColorProducerTiles
	ld b, FULL_COLOR_ANIMATION_TILE_BYTES
.water_byte
	ld a, [hl]
	push bc
	ld b, a
	ld a, [wFullColorProducerFlags]
	and a
	ld a, b
	pop bc
	jr nz, .water_left
	rrca
	jr .water_store
.water_left
	rlca
.water_store
	ld [de], a
	inc hl
	inc de
	dec b
	jr nz, .water_byte
	pop af
	ldh [rVBK], a
	ldh a, [hTileAnimations]
	rrca
	jr nc, .water_counter_ready
	xor a
	ldh [hMovingBGTilesCounter1], a
.water_counter_ready
	ld de, vTileset tile $14
	ld a, $14
	jr .enqueue
.water_counter
	ldh a, [hTileAnimations]
	rrca
	jr nc, .none
	xor a
	ldh [hMovingBGTilesCounter1], a
	jr .none

.flower
	xor a
	ldh [hMovingBGTilesCounter1], a
	ld a, $03
	call FindFullColorProductionAnimatedTileSelected
	jr c, .none
	ld a, c
	ld [wFullColorProducerWidth], a
	ld a, b
	ld [wFullColorProducerHeight], a
	ld a, [wMovingBGTilesCounter2]
	and 3
	cp 2
	ld hl, FullColorProductionFlowerTile1
	jr c, .flower_source
	ld hl, FullColorProductionFlowerTile2
	jr z, .flower_source
	ld hl, FullColorProductionFlowerTile3
.flower_source
	ld de, wFullColorProducerTiles
	ld b, FULL_COLOR_ANIMATION_TILE_BYTES
.flower_byte
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .flower_byte
	ld de, vTileset tile $03
	ld a, $03
.enqueue
	push de
	ld c, a
	ld b, 0
	ld hl, FullColorOverworldTileAttributes
	add hl, bc
	ld a, [hl]
	and $ef
	ld [wFullColorProducerTiles + FULL_COLOR_ANIMATION_TILE_BYTES], a
	pop de
	ld a, e
	ld [wFullColorProducerDestination], a
	ld a, d
	ld [wFullColorProducerDestination + 1], a
	ld a, FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	ld [wFullColorProducerClass], a
	xor a
	ld [wFullColorProducerFlags], a
	call BuildAndPrepareFullColorAnimationDescriptorSelected
	cp ACCEPTED
	ret z
	scf
	ret
.deferred
	ld a, DEFERRED
	scf
	ret
.none
	ld a, COALESCED
	and a
	ret

EXPORT ProduceFullColorProductionAnimatedTileSelected

; Keep field-replacement authority in this production-owned bank instead of
; reaching the unexported Yellow Home labels.
FullColorProductionFlowerTile1: INCBIN "gfx/tilesets/flower/flower1.2bpp"
FullColorProductionFlowerTile2: INCBIN "gfx/tilesets/flower/flower2.2bpp"
FullColorProductionFlowerTile3: INCBIN "gfx/tilesets/flower/flower3.2bpp"
POPS
ENDC
