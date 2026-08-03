; Compile-time-only provenance for the Phase 2 hostile-slice inventory audit.
; This section contains data references, never an executable entry point.
IF DEF(PHASE2_AUDIT)
SECTION "Phase 2 Audit Provenance", ROMX

Phase2AuditProvenance::
	db $50, $32, $41, $55, $44, $49, $54, $31 ; ASCII "P2AUDIT1"
Phase2AuditRoots::
	; Stable lexical order; the verifier decodes and binds every entry.
	dw AutoBgMapTransfer
	dw DMARoutine
	dw DisplayPartyMenu
	dw DisplayStartMenu
	dw DisplayTextID
	dw EnterMap
	dw LoadGBPal
	dw LoadMapData
	dw LoadNorthSouthConnectionsTileMap
	dw PalletTown_h
	dw PartyMenuInit
	dw PassiveFullColorApplyMap
	dw PassiveFullColorClearBGMapAttributes
	dw PassiveFullColorClearBGMapChunk
	dw PassiveFullColorCommitPalettes
	dw PassiveFullColorCommitRedrawColumn
	dw PassiveFullColorCommitRedrawRow
	dw PassiveFullColorCommitVisibleAttributes
	dw PassiveFullColorHandleConnection
	dw PassiveFullColorHomogenizeBGPalettes
	dw PassiveFullColorVBlank
	dw PrepareOAMData
	dw RedrawRowOrColumn
	dw RestoreScreenTilesAndReloadTilePatterns
	dw Route1_h
	dw ScheduleEastColumnRedraw
	dw ScheduleNorthRowRedraw
	dw ScheduleSouthRowRedraw
	dw ScheduleWestColumnRedraw
	dw StartMenu_Pokemon.exitMenu
	dw TransferBGPPals
	dw UpdateMovingBgTiles
Phase2AuditRootsEnd::

ASSERT Phase2AuditRootsEnd - Phase2AuditRoots == 32 * 2
ENDC
