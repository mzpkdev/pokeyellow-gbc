; Final-picture OAM palette mapping. A request source contains a complete
; 160-byte shadow batch followed by forty final-picture identity bytes.

PrepareFullColorOAMBatchSelected::
	push hl
	ld de, FULL_COLOR_DESCRIPTOR_SOURCE
	add hl, de
	ld a, [hli]
	ld d, [hl]
	ld e, a
	ld hl, wFullColorShadowOAMBatch
	ld b, 160
.copy
	ld a, [de]
	ld [hli], a
	inc de
	dec b
	jr nz, .copy
	; DE now addresses request-owned final picture identities.
	ld hl, wFullColorShadowOAMBatch + 3
	ld b, 40
.map
	ld a, [de]
	inc de
	cp $ff
	jr z, .missing
	cp 8
	jr c, .mapped
	bit 7, a
	jr nz, .unmapped
	ld c, FULL_COLOR_FALLBACK_OUT_OF_RANGE
	jr .fallback
.missing
	ld c, FULL_COLOR_FALLBACK_MISSING_IDENTITY
	jr .fallback
.unmapped
	ld c, FULL_COLOR_FALLBACK_UNMAPPED
.fallback
	push de
	ld d, a
	xor a
	call RecordFullColorOAMFallbackSelected
	pop de
.mapped
	ld c, a
	ld a, [hl]
	and $f8
	or c
	ld [hl], a
	inc hl
	inc hl
	inc hl
	inc hl
	dec b
	jr nz, .map
	pop hl
	and a
	ret

; A palette (zero for fallback), B reverse object cursor, C fallback kind,
; D rejected identity. The fixed four-byte bounded record is a seven-bit
; saturating count with an explicit high-bit overflow marker, then last kind,
; rejected identity, and object index. Together the total and final event
; distinguish an expected late fallback from hidden earlier fallbacks without
; touching write-only SRAM controls.
RecordFullColorOAMFallbackSelected:
	push hl
	ld hl, wFullColorReconstructionItems
	ld a, [hl]
	bit 7, a
	jr nz, .record
	cp $7f
	jr z, .overflow
	inc [hl]
	jr .record
.overflow
	ld a, $ff
	ld [hl], a
.record
	ld a, c
	ld [wFullColorReconstructionItems + 1], a
	ld a, d
	ld [wFullColorReconstructionItems + 2], a
	ld a, 40
	sub b
	ld [wFullColorReconstructionItems + 3], a
	pop hl
	xor a
	ret

CommitFullColorOAMBatchSelected:
	push hl
	ld hl, wFullColorShadowOAMBatch
	ld de, wShadowOAM
	ld b, 160
.copy
	ld a, [hli]
	ld [de], a
	inc de
	dec b
	jr nz, .copy
	call hDMARoutine
	pop hl
	ret
