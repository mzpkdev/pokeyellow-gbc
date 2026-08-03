VBlank::

	push af
	push bc
	push de
	push hl

	ldh a, [rSVBK]
IF DEF(PHASE2_AUDIT)
	; The outer register frame is already on the interrupted WRAM bank. Save
	; SVBK in HRAM so restoring it never tries to read through another bank.
	ldh [hPassiveFullColorVBlankSavedSVBK], a
ELSE
	push af
ENDC
	ld a, 1
	ldh [rSVBK], a

	ldh a, [rVBK] ; vram bank
	push af
	xor a
	ldh [rVBK], a ; reset vram bank to 0

	ldh a, [hLoadedROMBank]
	ld [wVBlankSavedROMBank], a

IF FULL_COLOR_PRODUCTION_ACTIVATED
	; Resolve visible ownership before the first hardware writer. Color performs
	; its complete visible route in the banked dispatcher; closed states perform
	; neither route and join only the owner-neutral tail below.
	farcall RouteRendererOwnershipVBlank
	push de
	ld a, e
	cp VBLANK_ROUTE_YELLOW
	jr nz, .visibleRouteComplete
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

IF DEF(PHASE2_AUDIT)
	; RedrawRowOrColumn consumes its mode. Freeze that one byte so the passive
	; bank-1 mirror can follow the completed Yellow bank-0 write geometrically.
	ldh a, [hRedrawRowOrColumnMode]
	push af
ENDC
	call RedrawRowOrColumn
IF DEF(PHASE2_AUDIT)
	; D carries the consumed mode through Bankswitch; E is the discarded flags.
	pop de
	farcall PassiveFullColorVBlank
ENDC
	call VBlankCopy
	call VBlankCopyDouble
	call UpdateMovingBgTiles
	call hDMARoutine
	ld a, BANK(PrepareOAMData)
	call BankswitchCommon
	call PrepareOAMData

IF FULL_COLOR_PRODUCTION_ACTIVATED
.visibleRouteComplete
	pop de
ENDC
IF DEF(FULL_COLOR_PRODUCTION_LINKAGE) && !DEF(PHASE2_AUDIT)
FullColorProductionVBlankVisibleRouteComplete::
ENDC
	IF FULL_COLOR_PRODUCTION_ACTIVATED
	; Build and freeze the next Color OAM unit only after the hardware-visible
	; route has crossed its deadline. This mirrors Yellow's next-frame OAM build:
	; producer work may extend into the visible period, hardware writes may not.
	ld a, e
	cp VBLANK_ROUTE_COLOR
	jr nz, .visiblePreparationComplete
	farcall PrepareFullColorProductionOAMForOwnedVBlank
.visiblePreparationComplete
	ENDC
:
	; VBlank-sensitive operations end.
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

IF DEF(PHASE2_AUDIT)
	ldh a, [hPassiveFullColorVBlankSavedSVBK]
	ldh [rSVBK], a
ELSE
	pop af
	ldh [rSVBK], a
ENDC

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
