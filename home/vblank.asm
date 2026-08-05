VBlank::

	push af
	push bc
	push de
	push hl

	ldh a, [rSVBK]
	; The outer register frame is already on the interrupted WRAM bank. Save
	; SVBK in HRAM so restoring it never tries to read through another bank.
	ldh [hPassiveFullColorVBlankSavedSVBK], a
	ld a, 1
	ldh [rSVBK], a

	ldh a, [rVBK] ; vram bank
	push af
	xor a
	ldh [rVBK], a ; reset vram bank to 0

	ldh a, [hLoadedROMBank]
	ld [wVBlankSavedROMBank], a
	ldh a, [hSCX]
	ldh [rSCX], a
	ldh a, [hSCY]
	ldh [rSCY], a

	ld a, [wDisableVBlankWYUpdate]
	and a
	jr nz, .ok
	ldh a, [hWY]
	ldh [rWY], a
.ok

	; A fresh Color overlay publishes two hidden bank-1 attribute rows per
	; VBlank. Once complete, Yellow's stock transfer owns bank-0 tile updates;
	; never execute both transfers in one interrupt.
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	jr z, .ordinaryAutoBgMapTransfer
	farcall PassiveFullColorAutoBgMapTransfer
	call VBlankCopyBgMap
	; The bounded overlay transfer owns this frame. Leave any Yellow redraw
	; armed so it runs, then receives its passive mirror, after the overlay.
	jr .passiveFullColorVBlankDone
.ordinaryAutoBgMapTransfer
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	jr nz, .completedOverlayTransfer
	call AutoBgMapTransfer
	call VBlankCopyBgMap
	jr .ordinaryVisibleOperations
.completedOverlayTransfer
	farcall PassiveFullColorCompletedOverlayVBlank
	jr nc, .vblankSensitiveOperationsDone

.ordinaryVisibleOperations
	; RedrawRowOrColumn consumes its mode. Freeze that one byte so the passive
	; bank-1 mirror can follow the completed Yellow bank-0 write geometrically.
	ldh a, [hRedrawRowOrColumnMode]
	push af
	call RedrawRowOrColumn
	; D carries the consumed mode through Bankswitch; E is the discarded flags.
	pop de
	farcall PassiveFullColorVBlank
.passiveFullColorVBlankDone
	call VBlankCopy
	call VBlankCopyDouble
	call UpdateMovingBgTiles
	call hDMARoutine
	ld a, BANK(PrepareOAMData)
	call BankswitchCommon
	call PrepareOAMData

:
	; VBlank-sensitive operations end.
.vblankSensitiveOperationsDone
	call TrackPlayTime ; keep track of time played

	call Random
	call ReadJoypad

	; The postcondition was always zero; write it directly and leave more of
	; the fixed Home section for the bank-preserving interrupt prologue.
	xor a
	ldh [hVBlankOccurred], a

	ldh a, [hFrameCounter]
	and a
	jr z, .skipDec
	dec a
	ldh [hFrameCounter], a

.skipDec
	call FadeOutAudio

	ld a, BANK(Music_DoLowHealthAlarm)
	call BankswitchCommon
	call Music_DoLowHealthAlarm
	ld a, BANK(Audio1_UpdateMusic)
	call BankswitchCommon
	call Audio1_UpdateMusic

	call SerialFunction

	ld a, [wVBlankSavedROMBank]
	call BankswitchCommon

	pop af
	ldh [rVBK], a

	ldh a, [hPassiveFullColorVBlankSavedSVBK]
	ldh [rSVBK], a

	pop hl
	pop de
	pop bc
	pop af
	reti


DelayFrame::
; Wait for the next vblank interrupt.
; As a bonus, this saves battery.

DEF NOT_VBLANKED EQU 1

	ld a, NOT_VBLANKED
	ldh [hVBlankOccurred], a
.halt
	halt
	ldh a, [hVBlankOccurred]
	and a
	jr nz, .halt
	ret
