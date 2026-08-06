DisplayStartMenu::
	ld a, BANK(StartMenu_Pokedex) ; also bank for other functions
	call BankswitchCommon
	; Home has no room for the integration. The selected bank is already bank 4,
	; so keep a constant-size Home trampoline and emit the production body
	; beside the start-menu implementation it calls.
	jp FullColorDisplayStartMenu
PUSHS
SECTION "Full Color start menu overlay integration", ROMX, BANK[4]
FullColorDisplayStartMenu:
	ld a, [wWalkBikeSurfState] ; walking/biking/surfing
	ld [wWalkBikeSurfStateCopy], a
	ld a, SFX_START_MENU
	call PlaySound

RedisplayStartMenu::
	call FullColorResumeStartMenuOverlay
	farcall DrawStartMenu
	jr RedisplayStartMenu_PrepareOverlay
RedisplayStartMenu_DoNotDrawStartMenu::
	; Trainer Info returns through this direct entry after a forced-Yellow
	; packet, so it shares the normal entry's hidden palette reconciliation.
	call FullColorResumeStartMenuOverlay
RedisplayStartMenu_PrepareOverlay:
	; Both paths install a fresh Start-menu structure. Invalidate the completed
	; Color attribute plane before the first cursor placement prepares it again.
	farcall PassiveFullColorInvalidateOverlayAttributes
	call FullColorStartMenuReveal
	call UpdateSprites
.loop
	call FullColorHandleStartMenuInput
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
	call FullColorPlaceUnfilledStartMenuCursor
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
	call LoadTextBoxTilePatterns
	jp CloseTextDisplay

; DisplayStartMenu pins bank 4 before entering this Home loop. Keep its Home
; call sites constant-sized and put the guarded integration beside the other
; start-menu implementation instead of consuming the last Home bytes.
FullColorStartMenuReveal:
	farcall PrintSafariZoneSteps
	ret

; A forced-Yellow submenu may have suspended passive overlay projection and
; invalidated the authored palettes. Start is explicitly paired: resume once,
; hide only after Color admission succeeds, then restore the complete current-
; BGP palette unit before either Start redisplay path prepares its structure.
FullColorResumeStartMenuOverlay:
	farcall PassiveFullColorResumeOverlays
	farcall PassiveFullColorShouldColorOverlay
	ret nc
	ld a, SCREEN_HEIGHT_PX
	ldh [hWY], a
	farcall PassiveFullColorRestoreInvalidatedPalettes
	ret

; Mirror HandleMenuInput through its first visible cursor placement, enqueue
; that finished authority, then resume the original wait loop and mechanics.
FullColorHandleStartMenuInput:
	farcall PassiveFullColorShouldColorOverlay
	jp nc, HandleMenuInput
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
	farcall PassiveFullColorPrepareMenuOverlay
	call Delay3
	xor a
	ldh [hWY], a
	jp HandleMenuInput_.loop2

FullColorPlaceUnfilledStartMenuCursor:
	jp PlaceUnfilledArrowMenuCursor

IF DEF(PHASE2_AUDIT)
EnqueueFullColorStartMenuOverlay:
	farcall IsFullColorOverworldOwnerFar
	ret c
.retry
	farcall EnqueueFullColorWindowTileMapOverlayFar
	jr c, .retry
	ret
ENDC

POPS
