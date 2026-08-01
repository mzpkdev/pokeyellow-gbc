WriteDMACodeToHRAM::
; Since no other memory is available during OAM DMA,
; DMARoutine is copied to HRAM and executed there.
	; Init and SoftResetInit overwrite this intent before joining their common
	; initialization path, so no power-on HRAM value is ever trusted.
	ldh a, [hSoftReset]
	cp 1
	jr nz, .cold_boot
	jr .ownership_ready
.cold_boot
	farcall InitRendererOwnership
.ownership_ready
	; Match the legacy initialization boundary: clear all HRAM except hOnCGB,
	; then reinstall the DMA stub below.
	xor a
	ld hl, STARTOF(HRAM)
	ld bc, SIZEOF(HRAM) - 1
	call FillMemory
	ld a, BANK(WriteDMACodeToHRAM)
	ldh [hLoadedROMBank], a
	ld [rROMB], a

	ld c, LOW(hDMARoutine)
	ld b, DMARoutine.End - DMARoutine
	ld hl, DMARoutine
.copy
	ld a, [hli]
	ldh [c], a
	inc c
	dec b
	jr nz, .copy
IF DEF(_DEBUG)
	jp InitFullColorDebugState
ELSE
	ret
ENDC

IF DEF(_DEBUG)
InitFullColorDebugState::
; Keep Gate 0 instrumentation isolated from the release ROM and from
; gameplay WRAM. The caller has already selected this routine's ROM bank.
	ldh a, [hOnCGB]
	and a
	ret z
	xor a
	ldh [hFullColorDebugCommandPending], a

	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BANK(wFullColorDebugStateStart)
	ld [rRAMB], a

	xor a
	ld hl, wFullColorDebugStateStart
	ld bc, wFullColorDebugStateEnd - wFullColorDebugStateStart
	call FillMemory

	ld hl, wFullColorDebugMagic
	ld a, $46 ; ASCII "F", intentionally bypassing the game text charmap
	ld [hli], a
	ld a, $43 ; ASCII "C"
	ld [hli], a
	ld a, $47 ; ASCII "G"
	ld [hli], a
	ld a, $30 ; ASCII "0"
	ld [hli], a
	ld a, FULL_COLOR_DEBUG_LAYOUT_VERSION
	ld [hli], a
	ld a, FULL_COLOR_DEBUG_ACTIVATION_PHASE
	ld [wFullColorDebugActivationPhase], a
	xor a
	ld [wFullColorDebugCommand], a
	ld [wFullColorDebugCheckpoint], a
	farcall CopyRendererStateToDebugCarrier

	ldh a, [hLoadedROMBank]
	ld [wFullColorDebugCurrentROMBank], a
	ldh a, [rVBK]
	and 1
	ld [wFullColorDebugCurrentVRAMBank], a

	ld hl, wFullColorDebugTraceMagic
	ld a, $46 ; ASCII "F"
	ld [hli], a
	ld a, $43 ; ASCII "C"
	ld [hli], a
	ld a, $54 ; ASCII "T"
	ld [hli], a
	ld a, $52 ; ASCII "R"
	ld [hli], a
	ld a, FULL_COLOR_DEBUG_TRACE_LAYOUT_VERSION
	ld [hli], a
	ld a, LOW(FULL_COLOR_DEBUG_TRACE_CAPACITY)
	ld [hli], a
	ld a, HIGH(FULL_COLOR_DEBUG_TRACE_CAPACITY)
	ld [hl], a

	ldh a, [rSVBK]
	and 7
	ld [wFullColorDebugCurrentWRAMBank], a
	xor a
	ld [rRAMB], a
	ld [rRAMG], a
	ret
ENDC

DMARoutine:
LOAD "OAM DMA", HRAM
hDMARoutine::
	; initiate DMA
	ld a, HIGH(wShadowOAM)
	ldh [rDMA], a
	; wait for DMA to finish
	ld a, $28
.wait
	dec a
	jr nz, .wait
	ret
ENDL
.End:
