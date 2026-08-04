; Pure production renderer policy. Preference changes are policy input only;
; this module never mutates ownership, lifecycle, jobs, or visible resources.

; Input: A = COLOR_MODE_*, B = RENDERER_CONTEXT_*, C = map id.
; Output: A = exactly one RENDERER_* owner.
ResolveEffectiveRendererOwner::
	cp COLOR_MODE_COLOR
	jr nz, .yellow
	ld a, b
	cp RENDERER_CONTEXT_ORDINARY_MAP
	jr nz, .yellow
	ld a, c
	cp PALLET_TOWN
	jr z, .color
	cp ROUTE_1
	jr nz, .yellow
.color
	ld a, RENDERER_FULL_COLOR_OVERWORLD
	ret
.yellow
	ld a, RENDERER_YELLOW
	ret

; Resolve the saved preference for ordinary presentation on the current map.
; This adapter remains observational: only a transition boundary may apply the
; returned owner to runtime ownership state.
ResolveCurrentOrdinaryMapOwner::
	ld a, [wUnusedObtainedBadges]
	and 1 << BIT_COLOR_MODE_YELLOW
	ld d, COLOR_MODE_COLOR
	jr z, .preference_ready
	inc d
.preference_ready
	ld a, [wCurMap]
	ld c, a
	ld b, RENDERER_CONTEXT_ORDINARY_MAP
	ld a, d
	jp ResolveEffectiveRendererOwner
