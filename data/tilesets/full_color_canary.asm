; Independently authored diagnostic assignments. Symbol names and payloads are
; absent from release/VC products, while equal padding keeps the ROM window
; identical across products.
IF DEF(PHASE2_AUDIT)
FullColorCanaryBGPalettes::
	REPT 8
		RGB 31, 31, 31
		RGB 31, 0, 31
		RGB 0, 31, 31
		RGB 0, 0, 0
	ENDR
FullColorCanaryBGPalettesEnd::
FullColorCanaryOBJPalettes::
	REPT 8
		RGB 31, 31, 31
		RGB 31, 31, 0
		RGB 0, 0, 31
		RGB 0, 0, 0
	ENDR
FullColorCanaryOBJPalettesEnd::
FullColorCanaryOverworldTileClasses::
	FOR n, 0, 256
		db n & 7
	ENDR
FullColorCanaryOverworldTileClassesEnd::
ASSERT FullColorCanaryBGPalettesEnd - FullColorCanaryBGPalettes == 64
ASSERT FullColorCanaryOBJPalettesEnd - FullColorCanaryOBJPalettes == 64
ASSERT FullColorCanaryOverworldTileClassesEnd - FullColorCanaryOverworldTileClasses == 256
ELSE
	ds 64 + 64 + 256
ENDC
