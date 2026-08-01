SECTION "Sprite Buffers", SRAM

sSpriteBuffer0:: ds SPRITEBUFFERSIZE
sSpriteBuffer1:: ds SPRITEBUFFERSIZE
sSpriteBuffer2:: ds SPRITEBUFFERSIZE

	ds $100

sHallOfFame:: ds HOF_TEAM * HOF_TEAM_CAPACITY


SECTION "Save Data", SRAM

	ds $598

sGameData::
sPlayerName::  ds NAME_LENGTH
sMainData::    ds wMainDataEnd - wMainDataStart
sSpriteData::  ds wSpriteDataEnd - wSpriteDataStart
sPartyData::   ds wPartyDataEnd - wPartyDataStart
sCurBoxData::  ds wBoxDataEnd - wBoxDataStart
sTileAnimations:: db
sGameDataEnd::
sMainDataCheckSum:: db


; The PC boxes will not fit into one SRAM bank,
; so they use multiple SECTIONs
DEF box_n = 0
MACRO boxes
	REPT \1
		DEF box_n += 1
	sBox{d:box_n}:: ds wBoxDataEnd - wBoxDataStart
	ENDR
ENDM

SECTION "Saved Boxes 1", SRAM

; sBox1 - sBox6
	boxes 6
sBank2AllBoxesChecksum:: db
sBank2IndividualBoxChecksums:: ds 6

SECTION "Saved Boxes 2", SRAM

; sBox7 - sBox12
	boxes 6
sBank3AllBoxesChecksum:: db
sBank3IndividualBoxChecksums:: ds 6

; All 12 boxes fit within 2 SRAM banks
	ASSERT box_n == NUM_BOXES, \
		"boxes: Expected {d:NUM_BOXES} total boxes, got {d:box_n}"

ENDSECTION


SECTION "Full Color Gate 0 Debug State", SRAM, BANK[3]

IF DEF(_DEBUG)
DEF FULL_COLOR_DEBUG_LAYOUT_VERSION EQU 2
DEF FULL_COLOR_DEBUG_ACTIVATION_PHASE EQU 1
DEF FULL_COLOR_DEBUG_WRITER_OWNERSHIP EQU 1
DEF FULL_COLOR_DEBUG_COMMIT_OWNERSHIP_REPLACEMENT EQU 1
DEF FULL_COLOR_DEBUG_TRACE_LAYOUT_VERSION EQU 2
DEF FULL_COLOR_DEBUG_TRACE_CAPACITY EQU 32
DEF FULL_COLOR_DEBUG_TRACE_RECORD_SIZE EQU 33

EXPORT FULL_COLOR_DEBUG_LAYOUT_VERSION
EXPORT FULL_COLOR_DEBUG_ACTIVATION_PHASE
EXPORT FULL_COLOR_DEBUG_WRITER_OWNERSHIP
EXPORT FULL_COLOR_DEBUG_COMMIT_OWNERSHIP_REPLACEMENT
EXPORT FULL_COLOR_DEBUG_TRACE_LAYOUT_VERSION
EXPORT FULL_COLOR_DEBUG_TRACE_CAPACITY

wFullColorDebugStateStart::
wFullColorDebugMagic:: ds 4
wFullColorDebugLayoutVersion:: db
wFullColorDebugActivationPhase:: db
wFullColorDebugCommand:: db
wFullColorDebugCheckpoint:: db
wFullColorDebugOwner:: db
wFullColorDebugPhase:: db
wFullColorDebugGeneration:: ds 4
wFullColorDebugLastRequestResult:: db
wFullColorDebugAdmissionOpen:: db
wFullColorDebugJobState:: db
wFullColorDebugCancellationReason:: db
wFullColorDebugDirtyFlags:: db
wFullColorDebugCommitUnitID:: dw
wFullColorDebugWriterID:: dw
wFullColorDebugCurrentROMBank:: db
wFullColorDebugCurrentWRAMBank:: db
wFullColorDebugCurrentVRAMBank:: db
wFullColorDebugLastWriterID:: dw
wFullColorDebugLastResourceID:: dw
wFullColorDebugReconstructionItems:: dw
wFullColorDebugPresentationBarrierStatus:: db
wFullColorDebugOAMFallbackKind:: db
wFullColorDebugOAMFallbackObjectID:: dw
wFullColorDebugOAMFallbackTileID:: db
wFullColorDebugTimingRowKey:: dw
wFullColorDebugAssertionCode:: dw

; Binary layout consumed by tools/rom_tests/full_color/trace.py:
; magic, layout version, capacity, count, next write, then physical slots.
wFullColorDebugTraceStart::
wFullColorDebugTraceMagic:: ds 4
wFullColorDebugTraceLayoutVersion:: db
wFullColorDebugTraceCapacity:: dw
wFullColorDebugTraceCount:: dw
wFullColorDebugTraceNextWrite:: dw
wFullColorDebugTraceRecords::
	ds FULL_COLOR_DEBUG_TRACE_CAPACITY * FULL_COLOR_DEBUG_TRACE_RECORD_SIZE
wFullColorDebugTraceEnd::
wFullColorDebugStateEnd::
ASSERT wFullColorDebugStateEnd <= $c000, \
	"Gate 0 debug state must fit after saved boxes in SRAM bank 3"
ENDC
