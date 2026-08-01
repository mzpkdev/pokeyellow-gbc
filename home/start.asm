_Start::
	cp BOOTUP_A_CGB
	jp z, StartCGB
	jp RejectNonCGBStartup

PUSHS
SECTION "CGB-only Startup", ROMX, BANK[1]

RejectNonCGBStartup::
	di
.loop
	halt
	jr .loop

StartCGB::
	ld a, TRUE
	ldh [hOnCGB], a
	ldh a, [rSPD]
	bit B_SPD_DOUBLE, a
	jr nz, .speed_ready
	ld a, SPD_PREPARE
	ldh [rSPD], a
	stop
.speed_ready
	jp Init

POPS
