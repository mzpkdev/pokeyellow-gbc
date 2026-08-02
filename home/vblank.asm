VBlank::

	push af
	push bc
	push de
	push hl

	; An interrupt can arrive while renderer state has WRAM bank 2 selected.
	; Save the raw entry register on the stack before touching any banked WRAM,
	; then run Yellow's legacy VBlank work against its established bank 1.
	ldh a, [rSVBK]
	push af
	ld a, 1
	ldh [rSVBK], a

	ldh a, [rVBK] ; vram bank
	push af
	xor a
	ldh [rVBK], a ; reset vram bank to 0

	ldh a, [hLoadedROMBank]
	ld [wVBlankSavedROMBank], a

IF DEF(PHASE2_AUDIT)
	; Decide visible ownership once. Carry clear means the full-color owner has
	; consumed this VBlank, so no Yellow-visible writer may run afterward.
	farcall FullColorVBlankOwnerConsumed
	jr nc, :+
ELSE
	; Phase 1 dispatch is banked to keep the already-full Home section bounded.
	; Its full-color route is a no-op; Yellow's mechanics continue unchanged.
	farcall RouteRendererOwnershipVBlank
ENDC
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
	call AutoBgMapTransfer
	call VBlankCopyBgMap
	call RedrawRowOrColumn
	call VBlankCopy
	call VBlankCopyDouble
	call UpdateMovingBgTiles
	call hDMARoutine
	ld a, BANK(PrepareOAMData)
	call BankswitchCommon
	call PrepareOAMData

IF DEF(PHASE2_AUDIT)
:
ENDC
IF !DEF(PHASE2_AUDIT)
.mailbox_command_consumed
ENDC
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

	pop af
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
