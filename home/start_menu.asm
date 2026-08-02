DisplayStartMenu::
	ld a, BANK(StartMenu_Pokedex) ; also bank for other functions
	call BankswitchCommon
IF DEF(PHASE2_AUDIT)
	; Home has no room for the guarded integration. The selected bank is already
	; bank 4, so keep a constant-size Home trampoline and emit the audit body
	; beside the start-menu implementation it calls.
	jp FullColorDisplayStartMenu
PUSHS
SECTION "Phase 2 start menu overlay integration", ROMX, BANK[4]
FullColorDisplayStartMenu:
ENDC
	ld a, [wWalkBikeSurfState] ; walking/biking/surfing
	ld [wWalkBikeSurfStateCopy], a
	ld a, SFX_START_MENU
	call PlaySound

RedisplayStartMenu::
	farcall DrawStartMenu
RedisplayStartMenu_DoNotDrawStartMenu::
	IF DEF(PHASE2_AUDIT)
	call FullColorStartMenuReveal
	ELSE
	farcall PrintSafariZoneSteps ; print Safari Zone info, if in Safari Zone
	ENDC
	call UpdateSprites
.loop
	IF DEF(PHASE2_AUDIT)
	call FullColorHandleStartMenuInput
	ELSE
	call HandleMenuInput
	ENDC
	ld b, a
; check if Up pressed
	bit B_PAD_UP, a
	jr z, .checkIfDownPressed
	ld a, [wCurrentMenuItem] ; menu selection
	and a
	jr nz, .loop
	ld a, [wLastMenuItem]
	and a
	jr nz, .loop
; if the player pressed tried to go past the top item, wrap around to the bottom
	CheckEvent EVENT_GOT_POKEDEX
	ld a, 6 ; there are 7 menu items with the pokedex, so the max index is 6
	jr nz, .wrapMenuItemId
	dec a ; there are only 6 menu items without the pokedex
.wrapMenuItemId
	ld [wCurrentMenuItem], a
	call EraseMenuCursor
	jr .loop
.checkIfDownPressed
	bit B_PAD_DOWN, a
	jr z, .buttonPressed
; if the player pressed tried to go past the bottom item, wrap around to the top
	CheckEvent EVENT_GOT_POKEDEX
	ld a, [wCurrentMenuItem]
	ld c, 7 ; there are 7 menu items with the pokedex
	jr nz, .checkIfPastBottom
	dec c ; there are only 6 menu items without the pokedex
.checkIfPastBottom
	cp c
	jr nz, .loop
; the player went past the bottom, so wrap to the top
	xor a
	ld [wCurrentMenuItem], a
	call EraseMenuCursor
	jr .loop
.buttonPressed ; A, B, or Start button pressed
	IF DEF(PHASE2_AUDIT)
	call FullColorPlaceUnfilledStartMenuCursor
	ELSE
	call PlaceUnfilledArrowMenuCursor
	ENDC
	ld a, [wCurrentMenuItem]
	ld [wBattleAndStartSavedMenuItem], a ; save current menu selection
	ld a, b
	and PAD_B | PAD_START ; was the Start button or B button pressed?
	jp nz, CloseStartMenu
	call SaveScreenTilesToBuffer2 ; copy background from wTileMap to wTileMapBackup2
	CheckEvent EVENT_GOT_POKEDEX
	ld a, [wCurrentMenuItem]
	jr nz, .displayMenuItem
	inc a ; adjust position to account for missing pokedex menu item
.displayMenuItem
	cp 0
	jp z, StartMenu_Pokedex
	cp 1
	jp z, StartMenu_Pokemon
	cp 2
	jp z, StartMenu_Item
	cp 3
	jp z, StartMenu_TrainerInfo
	cp 4
	jp z, StartMenu_SaveReset
	cp 5
	jp z, StartMenu_Option

; EXIT falls through to here
CloseStartMenu::
	call Joypad
	ldh a, [hJoyPressed]
	bit B_PAD_A, a
	jr nz, CloseStartMenu
	IF DEF(PHASE2_AUDIT)
	farcall IsFullColorOverworldOwnerFar
	jp nc, CloseTextDisplay
	ENDC
	call LoadTextBoxTilePatterns
	jp CloseTextDisplay

IF DEF(PHASE2_AUDIT)
; DisplayStartMenu pins bank 4 before entering this Home loop. Keep its Home
; call sites constant-sized and put the guarded integration beside the other
; start-menu implementation instead of consuming the last Home bytes.
FullColorStartMenuReveal:
	farcall PrintSafariZoneSteps
	call EnqueueFullColorStartMenuOverlay
	ret

; Mirror HandleMenuInput through its first visible cursor placement, enqueue
; that finished authority, then resume the original wait loop and mechanics.
FullColorHandleStartMenuInput:
	xor a
	ld [wPartyMenuAnimMonEnabled], a
	ldh a, [hDownArrowBlinkCount1]
	push af
	ldh a, [hDownArrowBlinkCount2]
	push af
	xor a
	ldh [hDownArrowBlinkCount1], a
	ld a, 6
	ldh [hDownArrowBlinkCount2], a
	xor a
	ld [wAnimCounter], a
	call PlaceMenuCursor
	call EnqueueFullColorStartMenuOverlay
	call Delay3
	jp HandleMenuInput_.loop2

FullColorPlaceUnfilledStartMenuCursor:
	call PlaceUnfilledArrowMenuCursor
	push af
	call EnqueueFullColorStartMenuOverlay
	pop af
	ret

EnqueueFullColorStartMenuOverlay:
	farcall IsFullColorOverworldOwnerFar
	ret c
.retry
	farcall EnqueueFullColorWindowTileMapOverlayFar
	jr c, .retry
	ret

POPS
ENDC
