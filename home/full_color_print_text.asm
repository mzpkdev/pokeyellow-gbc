; Keep this helper at the tail of Home: PrintText retains its address and exact
; extent, while the linked predicate keeps Yellow and unsupported scenes inert.
FullColorPrintTextDelay:
	farcall PassiveFullColorPrepareTextOverlay
	jp Delay3
