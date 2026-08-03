; Audit-only passive CGB coloring for Pallet Town and Route 1.
;
; Yellow remains authoritative for tiles, OAM, timing, overlays, fades, and
; mechanics. This code writes only BG palette RAM and VRAM bank 1 attributes.

PassiveFullColorIsSliceMap:
	ld a, [wCurMap]
	cp PALLET_TOWN
	ret z
	cp ROUTE_1
	ret

; Called with the LCD disabled after Yellow's complete ordinary map setup.
PassiveFullColorApplyMap:
	call PassiveFullColorIsSliceMap
	jr z, .apply
	call PassiveFullColorClearState
	xor a
	call PassiveFullColorWriteActive
	call PassiveFullColorClearBGMapAttributes
	ret
.apply
	call PassiveFullColorClearState
	ld a, 1
	call PassiveFullColorWriteActive
	call PassiveFullColorCommitPalettes
	jp PassiveFullColorCommitVisibleAttributes

; Seamless connections happen with the LCD active. Palette installation and
; any bank-1 cleanup are therefore deferred to bounded VBlank work.
PassiveFullColorHandleConnection:
	call PassiveFullColorIsSliceMap
	jr z, .enter
	ld bc, $320 ; homogenize first, then clear thirty-two 32-byte chunks
	call PassiveFullColorWriteState
	xor a
	call PassiveFullColorWriteActive
	ret
.enter
	ld bc, $100
	call PassiveFullColorWriteState
	ld a, 1
	call PassiveFullColorWriteActive
	ret

PUSHS
SECTION "Passive Full Color Bounded Helpers", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

; Yellow's tile source remains authoritative; translation happens outside
; VBlank. The fixed extent is loaded here because farcall consumes B.
PassiveFullColorPrepareRedrawAttributes:
	call PassiveFullColorIsSliceMap
	ret nz
	call PassiveFullColorReadActive
	cp 1
	ret nz
	select_renderer_state_e
	ld hl, wRedrawRowOrColumnSrcTiles
	ld de, wFullColorAttributeRectangle
	ldh a, [hRedrawRowOrColumnDest]
	ld c, a
	ldh a, [hRedrawRowOrColumnDest + 1]
	ld b, a
	push bc
	call .prepare_row
	pop bc
	ld a, TILEMAP_WIDTH
	add c
	ld c, a
	call .prepare_row
	restore_renderer_state_e
	ret
.prepare_row
	ld a, SCREEN_WIDTH / 2
.pair
	push af
	ld a, c
	ld [de], a
	inc de
	ld a, b
	ld [de], a
	inc de
	ld a, [hli]
	call PassiveFullColorAttributeForTile
	ld [de], a
	inc de
	ld a, [hli]
	call PassiveFullColorAttributeForTile
	ld [de], a
	inc de
	ld a, c
	add 2
	and %11111
	push af
	ld a, c
	and %11100000
	ld c, a
	pop af
	or c
	ld c, a
	pop af
	dec a
	jr nz, .pair
	ret

; Column geometry is frozen outside VBlank as 18 records containing destination
; low/high followed by two translated attributes. The bounded consumer then has
; no per-row address arithmetic in the visible critical section.
PassiveFullColorPrepareColumnAttributes:
	call PassiveFullColorIsSliceMap
	ret nz
	call PassiveFullColorReadActive
	cp 1
	ret nz
	select_renderer_state_e
	ld hl, wRedrawRowOrColumnSrcTiles
	ld de, wFullColorAttributeRectangle
	ldh a, [hRedrawRowOrColumnDest]
	ld c, a
	ldh a, [hRedrawRowOrColumnDest + 1]
	ld b, a
	ld a, SCREEN_HEIGHT
.row
	push af
	ld a, c
	ld [de], a
	inc de
	ld a, b
	ld [de], a
	inc de
	ld a, [hli]
	call PassiveFullColorAttributeForTile
	ld [de], a
	inc de
	ld a, [hli]
	call PassiveFullColorAttributeForTile
	ld [de], a
	inc de
	ld a, TILEMAP_WIDTH
	add c
	ld c, a
	jr nc, .normalize
	inc b
.normalize
	ld a, b
	and HIGH(TILEMAP_AREA - 1)
	or HIGH(vBGMap0)
	ld b, a
	pop af
	dec a
	jr nz, .row
	restore_renderer_state_e
	ret

; Party entry hook. Mark only an active slice; the close path performs the
; atomic LCD-off restore after Yellow has rebuilt wTileMap.
PassiveFullColorScheduleAttributeRestore:
	call PassiveFullColorIsSliceMap
	ret nz
	call PassiveFullColorReadActive
	cp 1
	ret nz
	ld bc, $200
	jp PassiveFullColorWriteState

; Party close hook, called after Yellow's LoadCurrentMapView. Translate the
; exact 20x18 window, disable the LCD, restore bank-1 attributes atomically at
; Yellow's current VRAM origin, then return presentation ownership to Yellow.
PassiveFullColorRestoreAfterMenu:
	call PassiveFullColorIsSliceMap
	ret nz
	call PassiveFullColorReadActive
	cp 1
	ret nz
	; CloseTextDisplay reaches this hook only after Yellow has rebuilt the
	; complete map view. Restore after ordinary dialogue as well as party and
	; start-menu overlays; every one of them rewrites bank-1 attributes.
	select_renderer_state_e
	ld hl, wTileMap
	ld de, wFullColorAttributeRectangle
	ld bc, SCREEN_AREA
.translate
	ld a, [hli]
	call PassiveFullColorAttributeForTile
	ld [de], a
	inc de
	dec bc
	ld a, b
	or c
	jr nz, .translate
	restore_renderer_state_e
	call DisableLCD
	ld a, [wMapViewVRAMPointer]
	ld e, a
	ld a, [wMapViewVRAMPointer + 1]
	ld d, a
	select_renderer_state_e
	ld a, 1
	ldh [rVBK], a
	ld hl, wFullColorAttributeRectangle
	ld b, SCREEN_HEIGHT
.row
	push de
	ld c, SCREEN_WIDTH
.copy
	ld a, [hli]
	ld [de], a
	ld a, e
	inc a
	and %11111
	push af
	ld a, e
	and %11100000
	ld e, a
	pop af
	or e
	ld e, a
	dec c
	jr nz, .copy
	pop de
	ld a, TILEMAP_WIDTH
	add e
	ld e, a
	jr nc, .wrap
	inc d
.wrap
	ld a, d
	and HIGH(TILEMAP_AREA - 1)
	or HIGH(vBGMap0)
	ld d, a
	dec b
	jr nz, .row
	restore_renderer_state_e
	xor a
	ldh [rVBK], a
	call PassiveFullColorClearState
	jp EnableLCD

POPS

; A=active. An explicit bit prevents the power-on wCurMap value (Pallet's ID
; is zero) from coloring the intro before a real Yellow map load completes.
PassiveFullColorWriteActive:
	ld b, a
	select_renderer_state_e
	ld a, b
	ld [wPassiveFullColorActive], a
	ld a, [wRendererGeneration]
	ld [wPassiveFullColorGeneration], a
	restore_renderer_state_e
	ret

PassiveFullColorReadActive:
	select_renderer_state_e
	ld a, [wPassiveFullColorActive]
	ld b, a
	ld a, [wPassiveFullColorGeneration]
	ld c, a
	ld a, [wRendererGeneration]
	cp c
	jr z, .generation_ok
	xor a
	ld b, a
	ld [wPassiveFullColorActive], a
	ld [wPassiveFullColorPalettePending], a
	ld [wPassiveFullColorClearChunks], a
.generation_ok
	ld a, [wPassiveFullColorPalettePending]
	ld c, a
	ld a, [wPassiveFullColorClearChunks]
	ld e, a
	restore_renderer_state_e
	ld a, b
	ret

; B=pending palette commit, C=remaining cleanup chunks. State lives in the
; dormant scheduler timing scratch in WRAM2; raw SVBK is always restored.
PassiveFullColorWriteState:
	select_renderer_state_e
	ld a, b
	ld [wPassiveFullColorPalettePending], a
	ld a, c
	ld [wPassiveFullColorClearChunks], a
	restore_renderer_state_e
	ret

PassiveFullColorClearState:
	xor a
	ld b, a
	ld c, a
	jr PassiveFullColorWriteState

; Runs after Yellow's RedrawRowOrColumn. It never replaces or suppresses the
; bank-0 write, and consumes only the mode frozen immediately before it.
PassiveFullColorVBlank:
	push de ; D is Yellow's consumed redraw mode
	; VBlank has IME clear and its prologue selected Yellow's WRAM1 stack.
	; Read WRAM2 stacklessly, then restore bank 1 before any pop or return.
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, [wPassiveFullColorActive]
	ld b, a
	ld a, [wPassiveFullColorGeneration]
	ld c, a
	ld a, [wRendererGeneration]
	cp c
	jr z, .generation_ok
	xor a
	ld b, a
	ld [wPassiveFullColorActive], a
	ld [wPassiveFullColorPalettePending], a
	ld [wPassiveFullColorClearChunks], a
.generation_ok
	ld a, [wPassiveFullColorPalettePending]
	ld c, a
	ld a, [wPassiveFullColorClearChunks]
	ld e, a
	ld a, 1
	ldh [rSVBK], a
	ld a, b
	cp 1
	jr nz, .inactive
	ld a, [wCurMap]
	cp PALLET_TOWN
	jr z, .slice
	cp ROUTE_1
	jr nz, .inactive
.slice
	pop de
	ld a, d
	cp REDRAW_ROW
	jp z, PassiveFullColorCommitRedrawRow
	cp REDRAW_COL
	jp z, PassiveFullColorCommitRedrawColumn
	; A redraw owns this frame. A pending palette remains queued for the next
	; redraw-free VBlank instead of combining two bounded operations.
	ld a, c
	cp 2
	ret z
	and a
	ret z
	ld b, 0
	ld c, 0
	call PassiveFullColorWriteState
	jp PassiveFullColorCommitPalettes

.inactive
	ld a, c
	cp 3
	jr nz, .clear
	ld c, e
	pop de
	ld b, 0
	call PassiveFullColorWriteState
	jp PassiveFullColorHomogenizeBGPalettes
.clear
	ld a, e
	ld c, a
	pop de
	ld a, c
	and a
	ret z
	cp 33
	jr c, .bounded_clear
	; Timing scratch is aliased but may contain pre-activation scheduler bytes.
	; Reject anything outside the only authored exit range before SP targets VRAM.
	call PassiveFullColorClearState
	ret
.bounded_clear
	jp PassiveFullColorClearBGMapChunk

; LCD must be off or the caller must be in VBlank.
PassiveFullColorCommitPalettes:
	ld a, $80
	ldh [rBGPI], a
	ld hl, FullColorOverworldBGPalettes
	ld b, 8 * 4 * 2
.loop
	ld a, [hli]
	ldh [rBGPD], a
	dec b
	jr nz, .loop
	ret

; Translate tile A through the donor-authored 256-byte authority table.
; Preserves DE, returns the attribute in A.
PassiveFullColorAttributeForTile:
	push hl
	push de
	ld e, a
	ld d, 0
	ld hl, FullColorOverworldTileAttributes
	add hl, de
	ld a, [hl]
	pop de
	pop hl
	ret

; LCD-off map path: mirror the complete bank-0 tilemap address-for-address.
; This covers both ordinary entries and scrolled seamless connections without
; guessing where wTileMap's visible window currently lands in VRAM.
PassiveFullColorCommitVisibleAttributes:
	ld hl, vBGMap0
	ld bc, TILEMAP_AREA
.loop
	xor a
	ldh [rVBK], a
	ld a, [hl]
	call PassiveFullColorAttributeForTile
	ld d, a
	ld a, 1
	ldh [rVBK], a
	ld [hl], d
	inc hl
	dec bc
	ld a, b
	or c
	jr nz, .loop
	; LoadMapData immediately streams player graphics after this hook. Its
	; established postcondition is VRAM bank 0, regardless of whatever a
	; palette command happened to leave selected on entry.
	xor a
	ldh [rVBK], a
	ret

PUSHS
SECTION "Passive Full Color Redraw Commits", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

PassiveFullColorCommitRedrawColumn:
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, 1
	ldh [rVBK], a
	ld hl, wFullColorAttributeRectangle
	REPT SCREEN_HEIGHT
		ld a, [hli]
		ld e, a
		ld a, [hli]
		ld d, a
		ld a, [hli]
		ld [de], a
		inc e
		ld a, [hli]
		ld [de], a
	ENDR
	ld a, 1
	ldh [rSVBK], a
	xor a
	ldh [rVBK], a
	ret

PassiveFullColorCommitRedrawRow:
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, 1
	ldh [rVBK], a
	ld hl, wFullColorAttributeRectangle
	REPT SCREEN_WIDTH
		ld a, [hli]
		ld e, a
		ld a, [hli]
		ld d, a
		ld a, [hli]
		ld [de], a
		inc e
		ld a, [hli]
		ld [de], a
	ENDR
	ld a, 1
	ldh [rSVBK], a
	xor a
	ldh [rVBK], a
	ret

POPS

PUSHS
SECTION "Passive Full Color Exit Barrier", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

; VBlank-only exit barrier. Read each color from palette 0 and duplicate it
; across palettes 1-7, so any uncleared attribute selects identical colors.
PassiveFullColorHomogenizeBGPalettes:
	ldh a, [rBGPI]
	push af
	ld b, 0 ; palette-0 byte index, advanced two bytes per color
.color
	ld a, b
	ldh [rBGPI], a
	ldh a, [rBGPD]
	ld d, a
	ld a, b
	inc a
	ldh [rBGPI], a
	ldh a, [rBGPD]
	ld e, a
	ld c, 1
.palette
	ld a, c
	add a
	add a
	add a
	add b
	or $80
	ldh [rBGPI], a
	ld a, d
	ldh [rBGPD], a
	ld a, e
	ldh [rBGPD], a
	inc c
	bit 3, c
	jr z, .palette
	inc b
	inc b
	ld a, b
	cp 8
	jr nz, .color
	pop af
	ldh [rBGPI], a
	ret

POPS

; LCD-off cleanup for door/warp exits. Clear the complete BG map bank so no
; stale attribute survives into an unrelated Yellow scene.
PassiveFullColorClearBGMapAttributes:
	ld a, 1
	ldh [rVBK], a
	ld hl, vBGMap0
	ld bc, TILEMAP_AREA
	xor a
	call FillMemory
	xor a
	ldh [rVBK], a
	ret

; Seamless exits amortize the same complete clear over 32 VBlanks. The plain
; bounded loop is deliberately stack-independent: pre-activation scratch can
; never redirect SP or turn malformed state into a control-flow failure.
PassiveFullColorClearBGMapChunk:
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, [wPassiveFullColorClearChunks]
	dec a
	ld [wPassiveFullColorClearChunks], a
	ld c, a
	ld a, 31
	sub c ; completed-chunk index, 0 through 31
	ld b, a
	and 7
	swap a
	add a
	ld l, a
	ld a, b
	srl a
	srl a
	srl a
	add HIGH(vBGMap0)
	ld h, a
	ld a, 1
	ldh [rVBK], a
	ld b, 32
	xor a
.loop
	ld [hli], a
	dec b
	jr nz, .loop
	ld a, 1
	ldh [rSVBK], a
	xor a
	ldh [rVBK], a
	ret

EXPORT PassiveFullColorApplyMap, PassiveFullColorHandleConnection
EXPORT PassiveFullColorPrepareRedrawAttributes
EXPORT PassiveFullColorPrepareColumnAttributes
EXPORT PassiveFullColorScheduleAttributeRestore, PassiveFullColorRestoreAfterMenu
EXPORT PassiveFullColorVBlank
