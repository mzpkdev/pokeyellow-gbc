; Scope the steady overworld LoadGBPal call. An active authored presentation
; keeps BG palette hardware ownership while Yellow updates its BGP cache and
; object palettes. Other contexts retain Yellow's ordinary palette publication.
;
; This audit-only writer lives beyond the frozen Phase 2 pipeline range so
; adding it cannot move the reviewed source-to-ROM subjects in that range.

PassiveFullColorLoadGBPal:
	call PassiveFullColorIsSliceMap
	jr nz, .yellow
	call PassiveFullColorReadActive
	cp 1
	jr nz, .yellow
	select_renderer_state_e
	ld a, 1
	ld [wPassiveFullColorBGPaletteProtected], a
	restore_renderer_state_e
	call LoadGBPal
	select_renderer_state_e
	xor a
	ld [wPassiveFullColorBGPaletteProtected], a
	ld a, [wPassiveFullColorPaletteInvalidated]
	ld b, a
	restore_renderer_state_e
	ld a, b
	and a
	ret z
	jp PassiveFullColorHandleConnection
.yellow
	call LoadGBPal
	ret

EXPORT PassiveFullColorLoadGBPal
