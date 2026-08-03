; Yellow has already completed LoadGBPal. If a fade or menu restoration
; replaced donor color zero on an active slice map, defer republication to
; the existing bounded VBlank path. Ordinary frames perform no writes.
;
; This audit-only writer lives beyond the frozen Phase 2 pipeline range so
; adding it cannot move the reviewed source-to-ROM subjects in that range.

PassiveFullColorRefreshAfterLoadGBPal:
	call PassiveFullColorIsSliceMap
	ret nz
	ldh a, [rBGPI]
	push af
	xor a
	ldh [rBGPI], a
	ldh a, [rBGPD]
	cp $fb ; low byte of donor RGB 27, 31, 27
	jr nz, .schedule
	ld a, 1
	ldh [rBGPI], a
	ldh a, [rBGPD]
	cp $03 ; high byte of donor RGB 27, 31, 27
	jr nz, .schedule
	pop af
	ldh [rBGPI], a
	ret
.schedule
	pop af
	ldh [rBGPI], a
	jp PassiveFullColorHandleConnection

EXPORT PassiveFullColorRefreshAfterLoadGBPal
