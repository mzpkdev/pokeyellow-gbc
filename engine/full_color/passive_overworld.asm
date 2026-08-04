; Shipped passive CGB coloring for Pallet Town and Route 1.
;
; Yellow remains authoritative for tiles, OAM, timing, overlays, fades, and
; mechanics. This code writes only BG palette RAM and VRAM bank 1 attributes.

; Called during ownership boot with WRAM2 already selected. Explicitly clear
; every persistent passive field so random power-on WRAM cannot impersonate a
; loaded Pallet Town before Yellow has completed a real map publication.
InitPassiveFullColorStateSelected:
	xor a
	ld hl, wPassiveFullColorStateStart
	ld b, wPassiveFullColorAttributeRectangle - wPassiveFullColorStateStart
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ld [wPassiveFullColorDeferredRedrawState], a
	ret

PassiveFullColorIsSliceMap:
	ld a, [wUnusedObtainedBadges]
	bit BIT_FULL_COLOR_YELLOW_MODE, a
	ret nz

; Presentation stays latched while a Start/Options overlay is open. The saved
; preference is reconciled only when the outer overlay closes or a map loads.
PassiveFullColorIsPresentedSliceMap:
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
	call PassiveFullColorWaitForRedrawSlot
	select_renderer_state_e
	ld hl, wRedrawRowOrColumnSrcTiles
	ld de, wPassiveFullColorRedrawStaging
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
	ld a, $80 | REDRAW_ROW
	ld [wPassiveFullColorDeferredRedrawState], a
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
	call PassiveFullColorWaitForRedrawSlot
	select_renderer_state_e
	ld hl, wRedrawRowOrColumnSrcTiles
	ld de, wPassiveFullColorRedrawStaging
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
	ld a, $80 | REDRAW_COL
	ld [wPassiveFullColorDeferredRedrawState], a
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

; Color-to-Yellow menu close must retire donor attributes before LoadGBPal can
; install Yellow palettes. Yellow's whole-screen GDMA packet clears both bank-1
; maps during safe video periods, matching the established battle handoff.
PassiveFullColorPrepareMenuHandoff:
	call PassiveFullColorIsSliceMap
	ret z
	call PassiveFullColorShouldColorOverlay
	ret nc
	call PassiveFullColorClearState
	xor a
	call PassiveFullColorWriteActive
	ld c, 12 ; BGMapAttributes_WholeScreen
	jpfar LoadBGMapAttributes

; Menu/dialogue close hook, called after Yellow's LoadCurrentMapView and
; LoadGBPal. Never blank the live LCD. An already-active Color presentation
; needs only a palette refresh. Activating Color from Yellow first translates
; Yellow's finalized wTileMap outside VBlank, then holds this close path until
; a bounded live-LCD transaction has published all 20x18 attributes.
PassiveFullColorRestoreAfterMenu:
	call PassiveFullColorIsSliceMap
	jr nz, .yellow
	ld a, [wIsInBattle]
	and a
	jr nz, .battle_owned
	call PassiveFullColorReadActive
	cp 1
	jr nz, .activate_color
	; Party presentation overwrites bank 1 without the paired overlay path.
	; Its held restore marker keeps Color latched through the returned Start
	; menu, then forces the same bounded visible-plane activation used by a
	; Yellow-to-Color mode change when the outer menu finally closes.
	ld a, c
	cp 2
	jr z, .activate_color
	call PassiveFullColorClearState
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	jr nz, .schedule_color
	call PassiveFullColorCommitPalettes
	jp PassiveFullColorCommitVisibleAttributes
.schedule_color
	ld bc, $100
	jp PassiveFullColorWriteState
.activate_color
	call PassiveFullColorClearState
	xor a
	call PassiveFullColorWriteActive
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	jr nz, .prepare_activation
	call PassiveFullColorCommitPalettes
	call PassiveFullColorCommitVisibleAttributes
	ld a, 1
	jp PassiveFullColorWriteActive
.prepare_activation
	call PassiveFullColorTranslateTileMap
	ld bc, $412 ; neutralize, then publish eighteen rows
	call PassiveFullColorWriteState
	ld b, 12 ; one bounded spare frame beyond the eleven-step transaction
.wait
	push bc
	call DelayFrame
	call PassiveFullColorReadActive
	cp 1
	pop bc
	ret z
	dec b
	jr nz, .wait
	ret
.battle_owned
	call PassiveFullColorClearState
	xor a
	jp PassiveFullColorWriteActive
.yellow
	ld b, SET_PAL_OVERWORLD
	call RunPaletteCommand
	call PassiveFullColorClearState
	xor a
	call PassiveFullColorWriteActive
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	jp z, PassiveFullColorClearBGMapAttributes
	ld bc, $320
	jp PassiveFullColorWriteState

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
; passive renderer's private WRAM2 allocation; raw SVBK is always restored.
PassiveFullColorWriteState:
	select_renderer_state_e
	ld a, b
	ld [wPassiveFullColorPalettePending], a
	ld a, c
	ld [wPassiveFullColorClearChunks], a
	restore_renderer_state_e
	ret

PUSHS
SECTION "Passive Full Color Redraw Admission", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

; One bounded redraw record set owns this slot from preparation through its
; bank-1 commit. The hold normally lasts two VBlanks: Yellow publishes bank 0
; first, then the passive mirror consumes the following redraw-free frame.
; Admission backpressure prevents a second scroll producer from replacing the
; frozen records in between.
PassiveFullColorWaitForRedrawSlot:
.wait
	select_renderer_state_e
	ld a, [wPassiveFullColorDeferredRedrawState]
	ld b, a
	restore_renderer_state_e
	ld a, b
	and a
	ret z
	call DelayFrame
	jr .wait

POPS

PUSHS
SECTION "Passive Full Color State Reset", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

PassiveFullColorClearState:
	xor a
	ld b, a
	ld c, a
	call PassiveFullColorWriteState
	select_renderer_state_e
	xor a
	ld [wPassiveFullColorDeferredRedrawState], a
	restore_renderer_state_e
	ldh a, [hAutoBGTransferEnabled]
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	ldh [hAutoBGTransferEnabled], a
	xor a
	ldh [hAutoBGTransferPortion], a
	ret

POPS

; Battles remain wholly Yellow-owned. Relinquish the passive overlay before
; the stock palette command waits for safe video access and replaces both
; bank-1 BG maps, so no transition frame can combine the two authorities.
PassiveFullColorPrepareBattleHandoff:
	call PassiveFullColorShouldColorOverlay
	ret nc
	call PassiveFullColorClearState
	xor a
	call PassiveFullColorWriteActive
	; RunPaletteCommand installs palettes before its attribute packet. Clear the
	; two maps first while the complete donor palette is still coherent, so its
	; LCD-safe waits cannot expose stock colors through stale donor attributes.
	ld c, 12 ; BGMapAttributes_WholeScreen
	farcall LoadBGMapAttributes
	ld b, SET_PAL_OVERWORLD
	jp RunPaletteCommand

PUSHS
SECTION "Passive Full Color Window Transfer", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

; hAutoBGTransferEnabled bit 7 owns the bounded overlay lifecycle. Bit 6 is
; private phase state during initial publication: one means publish the pending
; bank-1 pair of rows, zero means publish the matching Yellow bank-0 rows. Bit 5
; marks the completed coherent plane while the overlay stays open.
DEF BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE EQU 6
DEF BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE EQU 5
DEF PASSIVE_FULL_COLOR_OVERLAY_ROWS_PER_PHASE EQU 2
DEF PASSIVE_FULL_COLOR_OVERLAY_WAIT_FRAMES EQU \
	2 * SCREEN_HEIGHT / PASSIVE_FULL_COLOR_OVERLAY_ROWS_PER_PHASE - 3

; Carry means the active Pallet/Route 1 Color slice owns bank-1 attributes for
; this overlay. Yellow mode and every other scene remain on the stock path.
PassiveFullColorShouldColorOverlay:
	call PassiveFullColorIsPresentedSliceMap
	jr nz, .inactive
	call PassiveFullColorReadActive
	cp 1
	jr nz, .inactive
	scf
	ret
.inactive
	and a
	ret

; Translate Yellow's finalized 20x18 window tilemap outside VBlank. The window
; remains hidden while eighteen VBlanks alternate two bank-1 rows and the
; matching Yellow bank-0 rows. Callers retain their established Delay3 before
; reveal; this wait supplies the preceding fifteen bounded phases.
PassiveFullColorPrepareMenuOverlay:
	call PassiveFullColorShouldColorOverlay
	jr nc, .inactive
	call PassiveFullColorTranslateTileMap
	xor a
	ldh [hAutoBGTransferPortion], a
	ldh a, [hAutoBGTransferEnabled]
	set BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	set BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	ldh [hAutoBGTransferEnabled], a
	ld c, PASSIVE_FULL_COLOR_OVERLAY_WAIT_FRAMES
	call DelayFrames
	scf
	ret
.inactive
	ldh a, [hAutoBGTransferEnabled]
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	ldh [hAutoBGTransferEnabled], a
	xor a
	ldh [hAutoBGTransferPortion], a
	ret

PassiveFullColorTranslateTileMap:
	select_renderer_state_e
	ld hl, wTileMap
	ld de, wPassiveFullColorAttributeRectangle
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
	ret
; VBlank entry for the paired overlay. Exactly one 40-byte pair of rows is
; published. During initial publication an attribute pair leaves the row cursor
; unchanged, then the next frame's matching tile pair advances it. Once the
; hidden plane is coherent, continuous Yellow updates use the same bounded
; two-row cursor. No phase consumes the OAM/input/audio portion of VBlank.
PassiveFullColorAutoBgMapTransfer:
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	ret z
	ld [hSPTemp], sp

	; Build the source address as base + row * SCREEN_WIDTH. The cursor is an
	; even visible row from 0 through 16 while this private lifecycle owns it.
	ldh a, [hAutoBGTransferPortion]
	ld l, a
	ld h, 0
	add hl, hl ; row * 2
	add hl, hl ; row * 4
	ld e, l
	ld d, h
	add hl, hl ; row * 8
	add hl, hl ; row * 16
	add hl, de ; row * 20
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	jr z, .tiles
.attributes
	ld de, wPassiveFullColorAttributeRectangle
	add hl, de
	ld sp, hl
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, 1
	ldh [rVBK], a
	jr .destination
.tiles
	ld de, wTileMap
	add hl, de
	ld sp, hl
	xor a
	ldh [rVBK], a

.destination
	; Build the destination as the configured map base + row * TILEMAP_WIDTH.
	ldh a, [hAutoBGTransferPortion]
	ld l, a
	ld h, 0
	REPT 5
		add hl, hl
	ENDR
	ldh a, [hAutoBGTransferDest]
	ld e, a
	ldh a, [hAutoBGTransferDest + 1]
	ld d, a
	add hl, de
.copy
	ld b, PASSIVE_FULL_COLOR_OVERLAY_ROWS_PER_PHASE
.row
	REPT SCREEN_WIDTH / 2 - 1
		pop de
		ld [hl], e
		inc l
		ld [hl], d
		inc l
	ENDR
	pop de
	ld [hl], e
	inc l
	ld [hl], d
	ld a, TILEMAP_WIDTH - (SCREEN_WIDTH - 1)
	add l
	ld l, a
	jr nc, .no_carry
	inc h
.no_carry
	dec b
	jr nz, .row
.restore
	ld a, 1
	ldh [rSVBK], a
	xor a
	ldh [rVBK], a
	ldh a, [hSPTemp]
	ld l, a
	ldh a, [hSPTemp + 1]
	ld h, a
	ld sp, hl
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	jr z, .advance_tiles
	; The next VBlank publishes this exact pair from Yellow's bank-0 tilemap.
	res BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	ldh [hAutoBGTransferEnabled], a
	scf
	ret

.advance_tiles
	ldh a, [hAutoBGTransferPortion]
	add PASSIVE_FULL_COLOR_OVERLAY_ROWS_PER_PHASE
	cp SCREEN_HEIGHT
	jr c, .store_row
	xor a
.store_row
	ldh [hAutoBGTransferPortion], a
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	jr nz, .done
	ldh a, [hAutoBGTransferPortion]
	and a
	jr z, .initial_complete
	ldh a, [hAutoBGTransferEnabled]
	set BIT_PASSIVE_FULL_COLOR_OVERLAY_ATTRIBUTE_PHASE, a
	ldh [hAutoBGTransferEnabled], a
	jr .done
.initial_complete
	ldh a, [hAutoBGTransferEnabled]
	set BIT_PASSIVE_FULL_COLOR_OVERLAY_COMPLETE, a
	ldh [hAutoBGTransferEnabled], a
.done
	scf
	ret

POPS

; Runs after Yellow's RedrawRowOrColumn. It never replaces or suppresses the
; bank-0 write. A consumed redraw becomes a bank-1 commit for the next idle
; VBlank so each frame retains the complete Yellow interrupt tail.
PassiveFullColorVBlank:
	; The paired overlay already consumed this frame's one visible operation.
	; The lifecycle remains marked complete until the overlay closes, so ordinary
	; passive palette/redraw work cannot combine with its bounded bank-0 updates.
	ldh a, [hAutoBGTransferEnabled]
	bit BIT_PASSIVE_FULL_COLOR_OVERLAY_TRANSFER, a
	ret nz
	ld h, d ; freeze Yellow's consumed redraw mode without touching the stack
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
	ld [wPassiveFullColorDeferredRedrawState], a
.generation_ok
	ld a, [wPassiveFullColorPalettePending]
	ld c, a
	ld a, [wPassiveFullColorClearChunks]
	ld e, a
	ld a, [wPassiveFullColorDeferredRedrawState]
	ld l, a
	ld a, 1
	ldh [rSVBK], a
	ld a, b
	dec a
	jr nz, .inactive
	ld a, [wCurMap]
	cp PALLET_TOWN
	jr z, .slice
	cp ROUTE_1
	jr nz, .inactive
.slice
	ld d, h
	ld a, d
	cp REDRAW_ROW
	jp z, PassiveFullColorScheduleRedrawMirror
	cp REDRAW_COL
	jp z, PassiveFullColorScheduleRedrawMirror
	ld a, l
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
	cp 4
	jp nc, PassiveFullColorActivationVBlank
	cp 3
	jr nz, .clear
	ld c, e
	ld b, 0
	call PassiveFullColorWriteState
	jp PassiveFullColorHomogenizeBGPalettes
.clear
	ld a, e
	ld c, a
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

; The producer marks a prepared record with bit 7. Yellow's bank-0 redraw
; consumes this frame; convert that marker to a low-valued bank-1 pending mode
; for the next VBlank. A redraw without a matching passive record remains
; wholly Yellow-owned.
PassiveFullColorScheduleRedrawMirror:
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, [wPassiveFullColorDeferredRedrawState]
	ld b, a
	and $7f
	cp d
	jr nz, .restore
	bit 7, b
	jr z, .restore
	ld a, d
	ld [wPassiveFullColorDeferredRedrawState], a
.restore
	ld a, 1
	ldh [rSVBK], a
	ret

PassiveFullColorCommitRedrawColumn:
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	xor a
	ld [wPassiveFullColorDeferredRedrawState], a
	ld a, 1
	ldh [rVBK], a
	ld hl, wPassiveFullColorRedrawStaging
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
	xor a
	ld [wPassiveFullColorDeferredRedrawState], a
	ld a, 1
	ldh [rVBK], a
	ld hl, wPassiveFullColorRedrawStaging
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
SECTION "Passive Full Color Activation Barrier", ROMX, BANK[FULL_COLOR_PHASE2_ROM_BANK]

PassiveFullColorActivationVBlank:
	cp 4
	jr z, .neutralize
	cp 5
	jr z, .rows
	cp 6
	jr nz, .abort
	call PassiveFullColorValidateActivation
	jr nc, .abort
	jp PassiveFullColorCommitActivation
.neutralize
	call PassiveFullColorValidateActivation
	jr nc, .abort
	ld b, 5
	ld c, e
	call PassiveFullColorWriteState
	jp PassiveFullColorHomogenizeBGPalettes
.rows
	call PassiveFullColorValidateActivation
	jr nc, .abort
	jp PassiveFullColorCommitActivationRows
.abort
	call PassiveFullColorClearState
	ret

; Carry means an inactive live-LCD activation may continue. The saved option
; cannot change while RestoreAfterMenu is blocking, so admission is bound to
; generation-validated transaction state, map identity, and battle ownership.
PassiveFullColorValidateActivation:
	ld a, [wIsInBattle]
	and a
	jr nz, .invalid
	call PassiveFullColorIsPresentedSliceMap
	jr nz, .invalid
	scf
	ret
.invalid
	and a
	ret

; Publish two translated visible rows per VBlank. wPassiveFullColorClearChunks
; carries the remaining row count (18, 16, ... 2) during this transaction.
PassiveFullColorCommitActivationRows:
	ld a, SCREEN_HEIGHT
	sub e
	push af
	call PassiveFullColorCommitActivationRow
	pop af
	inc a
	call PassiveFullColorCommitActivationRow

	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, [wPassiveFullColorClearChunks]
	sub 2
	ld [wPassiveFullColorClearChunks], a
	jr nz, .restore
	ld a, 6
	ld [wPassiveFullColorPalettePending], a
.restore
	ld a, 1
	ldh [rSVBK], a
	ret

; A=row (0..17). Resolve both axes independently on Yellow's 32x32 torus:
; vertical addition wraps at $9bff and horizontal increments wrap within the
; same row instead of spilling into the next one.
PassiveFullColorCommitActivationRow:
	push af
	ld a, [wMapViewVRAMPointer]
	ld e, a
	ld a, [wMapViewVRAMPointer + 1]
	ld d, a
	pop af
	push af
	ld c, a
.advance_row
	ld a, c
	and a
	jr z, .destination_ready
	ld a, TILEMAP_WIDTH
	add e
	ld e, a
	jr nc, .no_carry
	inc d
.no_carry
	dec c
	jr .advance_row
.destination_ready
	ld a, d
	and HIGH(TILEMAP_AREA - 1)
	or HIGH(vBGMap0)
	ld d, a

	; Convert the row to a packed 20-byte scratch offset: row * (16 + 4).
	pop af
	ld l, a
	ld h, 0
	add hl, hl
	add hl, hl
	ld b, h
	ld c, l
	add hl, hl
	add hl, hl
	add hl, bc
	ld bc, wPassiveFullColorAttributeRectangle
	add hl, bc
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, 1
	ldh [rVBK], a
	ld a, e
	and %11111
	ld c, a
	add SCREEN_WIDTH
	cp TILEMAP_WIDTH + 1
	jr nc, .split_copy
	ld b, SCREEN_WIDTH
.copy_one_segment
	ld a, [hli]
	ld [de], a
	inc e
	dec b
	jr nz, .copy_one_segment
	jr .copy_done
.split_copy
	ld a, TILEMAP_WIDTH
	sub c
	ld b, a
.copy_before_wrap
	ld a, [hli]
	ld [de], a
	inc e
	dec b
	jr nz, .copy_before_wrap
	ld a, e
	sub TILEMAP_WIDTH
	ld e, a
	ld a, c
	sub TILEMAP_WIDTH - SCREEN_WIDTH
	ld b, a
.copy_after_wrap
	ld a, [hli]
	ld [de], a
	inc e
	dec b
	jr nz, .copy_after_wrap
.copy_done
	ld a, 1
	ldh [rSVBK], a
	xor a
	ldh [rVBK], a
	ret

; Palettes are committed only after every visible attribute row is complete.
; Set active in the same later bounded VBlank so no mixed presentation exists.
PassiveFullColorCommitActivation:
	call PassiveFullColorCommitPalettes
	ld a, FULL_COLOR_PHASE2_WRAM_BANK
	ldh [rSVBK], a
	ld a, 1
	ld [wPassiveFullColorActive], a
	xor a
	ld [wPassiveFullColorPalettePending], a
	ld [wPassiveFullColorClearChunks], a
	ld a, 1
	ldh [rSVBK], a
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
EXPORT PassiveFullColorPrepareMenuHandoff
EXPORT PassiveFullColorShouldColorOverlay, PassiveFullColorPrepareMenuOverlay
EXPORT PassiveFullColorPrepareBattleHandoff
EXPORT PassiveFullColorAutoBgMapTransfer
EXPORT PassiveFullColorVBlank
