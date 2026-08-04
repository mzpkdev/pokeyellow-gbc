SoftReset::
	farjp SoftResetRendererOwnership

Init::
	; Cold startup establishes its reset intent before inspecting any memory.
	xor a
	IF FULL_COLOR_PRODUCTION_ACTIVATED
	; Admit the complete hard-reset root before it can clear any renderer-owned
	; WRAM, VRAM, tilemap, palette, or OAM state. Cold WRAM is not authority for
	; the test seam, so normalize the seam before the linked check observation.
	di
	ld a, 1
	ldh [rSVBK], a
	ld sp, wStack
	farcall AdmitFullColorHardResetBeforeInit
	jr c, .hardResetBudgetRejected
	xor a
	ENDC
	jr InitWithResetIntent
	IF FULL_COLOR_PRODUCTION_ACTIVATED
.hardResetBudgetRejected
	jr .hardResetBudgetRejected
	ENDC

SoftResetInit::
	; Only the completed SoftResetRendererOwnership path enters here.
	ld a, 1

InitWithResetIntent:
	ldh [hSoftReset], a
;  Program init.
	di

	xor a
	ldh [rIF], a
	ldh [rIE], a
	ldh [rSCX], a
	ldh [rSCY], a
	ldh [rSB], a
	ldh [rSC], a
	ldh [rWX], a
	ldh [rWY], a
	ldh [rTMA], a
	ldh [rTAC], a
	ldh [rBGP], a
	ldh [rOBP0], a
	ldh [rOBP1], a

	ld a, LCDC_ON
	ldh [rLCDC], a
	call DisableLCD

	ld sp, wStack

	ld a, 1
	ldh [rSVBK], a
	ld hl, STARTOF(WRAM0)
	; Preserve Yellow's historical contiguous C000-DFFF clear now that the
	; CGB linker describes D000-DFFF honestly as WRAMX bank 1.
	ld bc, $2000
.loop
	ld [hl], 0
	inc hl
	dec bc
	ld a, b
	or c
	jr nz, .loop

	call ClearVram

	call ClearSprites

	ld a, BANK(WriteDMACodeToHRAM)
	ldh [hLoadedROMBank], a
	ld [rROMB], a
	call WriteDMACodeToHRAM

	xor a
	ldh [hTileAnimations], a
	ldh [rSTAT], a
	ldh [hSCX], a
	ldh [hSCY], a
	ldh [rIF], a
	ld [wUnusedAudioCounter], a
	ld [wUnusedAudioCounter + 1], a
	ld a, IE_VBLANK | IE_TIMER | IE_SERIAL
	ldh [rIE], a

	ld a, 144 ; move the window off-screen
	ldh [hWY], a
	ldh [rWY], a
	ld a, 7
	ldh [rWX], a

	ld a, CONNECTION_NOT_ESTABLISHED
	ldh [hSerialConnectionStatus], a

	ld h, HIGH(vBGMap0)
	call ClearBgMap
	ld h, HIGH(vBGMap1)
	call ClearBgMap

	ld a, LCDC_DEFAULT
	ldh [rLCDC], a
	ld a, 16
	ldh [hSoftReset], a
	call StopAllSounds

	ei

	predef LoadSGB

	ld a, BANK(SFX_Shooting_Star)
	ld [wAudioROMBank], a
	ld [wAudioSavedROMBank], a
	ld a, HIGH(vBGMap1)
	ldh [hAutoBGTransferDest + 1], a
	xor a
	ldh [hAutoBGTransferDest], a
	dec a
	ld [wUpdateSpritesEnabled], a

	predef PlayIntro

	call DisableLCD
	call ClearVram
	call GBPalNormal
	call ClearSprites
	ld a, LCDC_DEFAULT
	ldh [rLCDC], a

	jp PrepareTitleScreen

ClearVram::
	farjp ClearVramBanked


StopAllSounds::
	ld a, BANK("Audio Engine 1")
	ld [wAudioROMBank], a
	ld [wAudioSavedROMBank], a
	xor a
	ld [wAudioFadeOutControl], a
	ld [wNewSoundID], a
	ld [wLastMusicSoundID], a
	jp StopAllMusic
