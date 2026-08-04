; Complete 64-byte palette preparation and commit. Base buffers are immutable
; inputs for a request; transformations are derived into distinct buffers.

PrepareFullColorVisibleUnitSelected::
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	jp z, PrepareFullColorAnimationReplacementSelected
	cp FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	jr z, PrepareFullColorBGPaletteSelected
	cp FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
	jr z, PrepareFullColorOBJPaletteSelected
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jp z, PrepareFullColorOAMBatchSelected
	jp PrepareFullColorPairedTransferSelected

PrepareFullColorBGPaletteSelected:
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_SOURCE
	add hl, de
	ld a, [hli]
	ld d, [hl]
	ld e, a
	ld hl, wFullColorBGPaletteBase
	call CopyAndTransformFullColorPaletteSelected
	pop hl
	and a
	ret

PrepareFullColorOBJPaletteSelected:
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_SOURCE
	add hl, de
	ld a, [hli]
	ld d, [hl]
	ld e, a
	ld hl, wFullColorOBJPaletteBase
	call CopyAndTransformFullColorPaletteSelected
	pop hl
	and a
	ret

; DE source, HL 64-byte base. The transformed buffer immediately follows base.
CopyAndTransformFullColorPaletteSelected:
	push hl
	ld b, 64
.base
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .base
	pop de
	ld hl, 64
	add hl, de
	ld b, 32
.color
	ld a, [de]
	and $1f
	ld c, a
	ld a, $1f
	sub c
	ld [hli], a
	inc de
	ld a, [de]
	and $7c
	xor $7c
	ld [hli], a
	inc de
	dec b
	jr nz, .color
	ret

CommitFullColorVisibleUnitSelected::
	ld a, [hl]
	and FULL_COLOR_DESCRIPTOR_CLASS_MASK
	cp FULL_COLOR_REQUEST_ANIMATION_REPLACEMENT
	jp z, CommitFullColorAnimationReplacementSelected
	cp FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	jr z, CommitFullColorBGPaletteSelected
	cp FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
	jr z, CommitFullColorOBJPaletteSelected
	cp FULL_COLOR_REQUEST_OAM_BATCH_AND_DMA
	jp z, CommitFullColorOAMBatchSelected
	jp CommitFullColorPairedTransferSelected

CommitFullColorBGPaletteSelected:
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_FLAGS
	add hl, de
	bit 1, [hl]
	ld hl, wFullColorBGPaletteBase
	jr z, .source
	ld hl, wFullColorBGPaletteTransformed
.source
	ld a, $80
	ldh [rBGPI], a
	ld c, LOW(rBGPD)
	ld b, 64
.copy
	ld a, [hli]
	ldh [c], a
	dec b
	jr nz, .copy
	pop hl
	ret

CommitFullColorOBJPaletteSelected:
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_FLAGS
	add hl, de
	bit 1, [hl]
	ld hl, wFullColorOBJPaletteBase
	jr z, .source
	ld hl, wFullColorOBJPaletteTransformed
.source
	ld a, $80
	ldh [rOBPI], a
	ld c, LOW(rOBPD)
	ld b, 64
.copy
	ld a, [hli]
	ldh [c], a
	dec b
	jr nz, .copy
	pop hl
	ret

IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
PUSHS
SECTION "Full Color Production Palette Producer", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]
; Independently authored production OBJ authority. Palette zero is the stable
; fallback; the remaining slots match the final-picture mappings in oam.asm.
FullColorProductionOBJPalettes::
	RGB 31, 31, 31, 21, 21, 21, 10, 10, 10, 0, 0, 0 ; fallback
	RGB 31, 31, 31, 31, 20, 20, 24, 8, 8, 0, 0, 0   ; Red
	RGB 31, 31, 31, 31, 31, 8, 25, 18, 0, 0, 0, 0   ; Pikachu
	RGB 31, 31, 31, 23, 19, 13, 12, 9, 5, 0, 0, 0   ; Oak
	RGB 31, 31, 31, 31, 20, 27, 20, 9, 18, 0, 0, 0  ; girl
	RGB 31, 31, 31, 18, 25, 31, 5, 12, 23, 0, 0, 0  ; fisher
	RGB 31, 31, 31, 20, 31, 20, 5, 18, 5, 0, 0, 0   ; field object
	RGB 31, 31, 31, 31, 24, 12, 20, 10, 2, 0, 0, 0  ; transient
FullColorProductionOBJPalettesEnd::

ASSERT FullColorProductionOBJPalettesEnd - FullColorProductionOBJPalettes == FULL_COLOR_PALETTE_EXTENT

; Compare the complete mapped payload with palette RAM without assuming that
; the hardware index auto-increments on reads. Carry set means it is due.
FullColorProductionBGPaletteDueSelected:
	ldh a, [rBGPI]
	push af
	ld hl, FullColorOverworldBGPalettes
	ld d, 0
	ld b, FULL_COLOR_PALETTE_EXTENT
.compare
	ld a, d
	ldh [rBGPI], a
	ldh a, [rBGPD]
	cp [hl]
	jr nz, .different
	inc hl
	inc d
	dec b
	jr nz, .compare
	pop af
	ldh [rBGPI], a
	and a
	ret
.different
	pop af
	ldh [rBGPI], a
	scf
	ret

FullColorProductionOBJPaletteDueSelected:
	ldh a, [rOBPI]
	push af
	ld hl, FullColorProductionOBJPalettes
	ld d, 0
	ld b, FULL_COLOR_PALETTE_EXTENT
.compare
	ld a, d
	ldh [rOBPI], a
	ldh a, [rOBPD]
	cp [hl]
	jr nz, .different
	inc hl
	inc d
	dec b
	jr nz, .compare
	pop af
	ldh [rOBPI], a
	and a
	ret
.different
	pop af
	ldh [rOBPI], a
	scf
	ret

; A=request class, DE=stable same-bank 64-byte source. The scheduler-private
; descriptor is prepared immediately, so the following OAM enqueue defers and
; this complete palette payload gets the single commit slot for this VBlank.
EnqueueFullColorProductionPaletteSelected:
	ld [wFullColorProducerClass], a
	ld a, e
	ld [wFullColorProducerSource], a
	ld a, d
	ld [wFullColorProducerSource + 1], a
	ld a, [wFullColorProducerClass]
	cp FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	ld a, LOW(FULL_COLOR_BG_PALETTE_DESTINATION)
	jr z, .destination
	ld a, LOW(FULL_COLOR_OBJ_PALETTE_DESTINATION)
.destination
	ld [wFullColorProducerDestination], a
	ld a, HIGH(FULL_COLOR_BG_PALETTE_DESTINATION)
	ld [wFullColorProducerDestination + 1], a
	call ClearFullColorSemanticDescriptorSelected
	ld hl, wFullColorSchedulerEnqueueDescriptor
	ld a, [wFullColorProducerClass]
	ld [hli], a
	call WriteFullColorSemanticDescriptorHeaderFromProducerSourceSelected
	xor a
	ld [hli], a
	ld [hli], a
	ld a, FULL_COLOR_RESOURCE_PALETTES
	ld [hli], a
	xor a
	ld [hli], a
	ld a, LOW(FULL_COLOR_PALETTE_EXTENT)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_PALETTE_EXTENT)
	ld [hli], a
	ld a, LOW(FULL_COLOR_PALETTE_RESERVATION)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_PALETTE_RESERVATION)
	ld [hli], a
	xor a
	ld [hli], a
	ld [hl], a
	jp AdmitPreparedFullColorSemanticSelected

; Hidden reconstruction barrier for resources that cannot truthfully be
; deferred to the first active VBlank. It materializes both complete palette
; buffers and hardware payloads, then builds the current Color shadow OAM and
; DMA-publishes it before the caller marks reconstruction complete.
CompleteFullColorProductionHiddenVisibleRootsSelected::
	ldh a, [rLCDC]
	bit 7, a
	jr nz, .failed
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .failed
	ld a, [wRendererPhase]
	cp OVERWORLD_RECONSTRUCTING
	jr nz, .failed
	ld a, [wRendererAdmissionOpen]
	and a
	jr nz, .failed
	ld de, FullColorOverworldBGPalettes
	ld hl, wFullColorBGPaletteBase
	call CopyAndTransformFullColorPaletteSelected
	ld de, FullColorProductionOBJPalettes
	ld hl, wFullColorOBJPaletteBase
	call CopyAndTransformFullColorPaletteSelected
	; Sprite construction calls the public OAM mapper, which selects WRAM2 on
	; each mapped identity. Temporarily expose the outer caller's WRAM bank while
	; keeping IE masked, and preserve its original IE snapshot across those
	; nested selections. Return with WRAM2 selected for the reconstruction root.
	ldh a, [hRendererStateSavedIE]
	ld [wFullColorRequestStaging], a
	ldh a, [hRendererStateSavedSVBK]
	ldh [rSVBK], a
	ld a, $80
	ldh [rBGPI], a
	ld hl, FullColorOverworldBGPalettes
	ld b, FULL_COLOR_PALETTE_EXTENT
.bg
	ld a, [hli]
	ldh [rBGPD], a
	dec b
	jr nz, .bg
	ld a, $80
	ldh [rOBPI], a
	ld hl, FullColorProductionOBJPalettes
	ld b, FULL_COLOR_PALETTE_EXTENT
.obj
	ld a, [hli]
	ldh [rOBPD], a
	dec b
	jr nz, .obj
	ld a, 1
	ld [wUpdateSpritesEnabled], a
	ldh [hSpritePriority], a
	farcall PrepareOAMData.build
	call hDMARoutine
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, [wFullColorRequestStaging]
	ldh [hRendererStateSavedIE], a
	and a
	ret
.failed
	scf
	ret

; Production Color VBlank producer root. Exactly one due palette, animation,
; or field-replacement unit is made PREPARED; the lifecycle then builds OAM
; and invokes the scheduler, which commits exactly that one whole unit.
ProduceFullColorProductionVBlankWork::
IF FULL_COLOR_PRODUCTION_ACTIVATED
	select_renderer_state_e
	ld a, [wRendererAdmissionOpen]
	and a
	jr z, .deferred
	ld a, [wRendererOwner]
	cp RENDERER_FULL_COLOR_OVERWORLD
	jr nz, .wrong_owner
	ld a, [wRendererPhase]
	cp OVERWORLD_ACTIVE
	jr nz, .wrong_owner
	ld a, [wFullColorProducerPending]
	and a
	jr nz, .deferred
	call FullColorProductionOBJPaletteDueSelected
	jr nc, .bg
	ld de, FullColorProductionOBJPalettes
	ld a, FULL_COLOR_REQUEST_OBJ_PALETTE_PAYLOAD
	call EnqueueFullColorProductionPaletteSelected
	jr .finish
.bg
	call FullColorProductionBGPaletteDueSelected
	jr nc, .animated
	ld de, FullColorOverworldBGPalettes
	ld a, FULL_COLOR_REQUEST_BG_PALETTE_PAYLOAD
	call EnqueueFullColorProductionPaletteSelected
	jr .finish
.animated
	call ProduceFullColorProductionAnimatedTileSelected
	jr .finish
.wrong_owner
	ld a, REJECTED_WRONG_OWNER
	jr .finish
.deferred
	ld a, DEFERRED
.finish
	ld b, a
	restore_renderer_state_e
	ld a, b
	cp ACCEPTED
	ret z
	cp COALESCED
	ret z
	scf
	ret
ELSE
	ld a, REJECTED_WRONG_OWNER
	scf
	ret
ENDC
ProduceFullColorProductionVBlankWorkEnd:

EXPORT CompleteFullColorProductionHiddenVisibleRootsSelected
EXPORT ProduceFullColorProductionVBlankWork
POPS
ENDC
