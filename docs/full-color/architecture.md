# Full-color runtime architecture

This document describes the renderer that actually runs today. The important
constraint is simple: the visible Phase 2 slice is an audit-only, passive CGB
color layer for Pallet Town and Route 1. It is not the retained full-color
scheduler taking ownership of the game.

For procedures and verification, use the sibling extension and harness guides.
This page is the source of truth for runtime boundaries and data flow.

## What ships in each build

The build flag is the cleanest way to understand the current product boundary.

| Target | Product | Active passive color slice |
| --- | --- | --- |
| `make yellow` | `pokeyellow.gbc` | No |
| `make yellow_debug` | `pokeyellow_debug.gbc` | No |
| `make yellow_vc` | `pokeyellow.patch` / VC ROM | No |
| `make yellow_phase2_audit` | `pokeyellow_phase2_audit.gbc` | Yes |

The audit target adds both `_DEBUG` and `PHASE2_AUDIT`; see the target-specific
flags in the [Makefile](../../Makefile). The guarded Phase 2 code and data are
linked from [main.asm](../../main.asm). Release, ordinary debug, and VC products
must not gain a reachable passive renderer by accident.

## Current ownership contract

Yellow remains authoritative for:

- every bank-0 background tile and tile pattern;
- sprite graphics, OAM, movement, and mechanics;
- map construction, scrolling, menus, dialogue, battle, and cutscenes;
- animation timing, overlays, fades, and scheduling.

The passive slice may publish only:

- all eight CGB background palettes through BG palette RAM; and
- the corresponding per-tile attributes in VRAM bank 1.

It translates the tile picture Yellow has already finished. It never replaces,
suppresses, or races Yellow's bank-0 tile write. Object palettes exist in the
audit data ABI, but the passive runtime does not publish or own them; sprite
presentation remains Yellow's responsibility.

This narrow boundary is why the current ROM is playable. Earlier attempts to
make an incomplete second renderer own tiles, sprites, and cutscene timing
produced mismatched tilemaps and broken sequences. Do not widen this contract as
a shortcut for adding another colored map.

## Active path versus retained scaffolding

Two architectures coexist in `engine/full_color`, and their presence in the
same audit ROM can be misleading.

### Active Phase 2 path

[passive_overworld.asm](../../engine/full_color/passive_overworld.asm) is the
live presentation path. Hooks in Yellow's ordinary map, redraw, menu, palette,
and VBlank flows call its `PassiveFullColor*` routines. The allowed map set is
hard-coded by `PassiveFullColorIsSliceMap` to `PALLET_TOWN` and `ROUTE_1`.

[passive_palette_refresh.asm](../../engine/full_color/passive_palette_refresh.asm)
notices when Yellow has legitimately republished a different palette after a
fade or restoration and schedules the passive palette for a later bounded
VBlank.

### Retained future and test seams

[ownership.asm](../../engine/full_color/ownership.asm),
[scheduler.asm](../../engine/full_color/scheduler.asm),
[palettes.asm](../../engine/full_color/palettes.asm),
[transfers.asm](../../engine/full_color/transfers.asm),
[oam.asm](../../engine/full_color/oam.asm), and most of
[lifecycle.asm](../../engine/full_color/lifecycle.asm) preserve measured Phase
1/Phase 2 contracts, debug observability, and seams for later roadmap phases.
The [migration plan](../../specs/full-colors/docs/migration-plan.md) assigns
palette/transfers to Phase 3, OAM to Phase 4, stress to Phase 5, content to
Phase 6, handoffs to Phase 7, ownership deletion to Phase 8, and release
hardening to Phase 9. These modules are
compiled into the audit layout, but they do not drive the passive Pallet/Route
1 presentation.

In particular, the audit VBlank path calls `PassiveFullColorVBlank`; it does not
hand the frame to `RouteRendererOwnershipVBlank`. The passive state reuses
reviewed WRAM2 storage and the renderer generation, but it does not acquire
`RENDERER_FULL_COLOR_OVERWORLD` ownership or enqueue normal scheduler jobs.
Treating the scheduler, transfer, palette, or OAM machinery as active behavior
will lead to false conclusions during debugging.

## Data authority

All live slice color decisions are centralized in
[full_color_overworld.asm](../../data/tilesets/full_color_overworld.asm):

- `FullColorOverworldBGPalettes` is a complete 64-byte set of eight CGB BG
  palettes, each containing four 15-bit colors.
- `FullColorOverworldTileAttributes` is a complete 256-byte tile-ID-to-attribute
  lookup table.
- tile IDs `$00` through `$5f` use the donor-derived `OVERWORLD` assignments;
  `$60` through `$ff` deliberately select text palette 7.
- the attributes select VRAM bank 0 and do not author priority.
- palette 6 carries the Pallet roof colors used by both maps in this slice.

The data records its donor source and pinned revisions inline. Its size
assertions are part of the ABI. A tile attribute is looked up directly by tile
ID in `PassiveFullColorAttributeForTile`; there is no arithmetic fallback such
as `tile_id & 7`.

Pallet Town and Route 1 can share this authority because both use Yellow's
`OVERWORLD` tileset and the approved slice gives them the same roof identity.
That does not imply that every `OVERWORLD` map can safely share Pallet's
palette. Phase 3 must introduce map-aware palette/transfer selection; Phase 6
authors and accepts the complete map-specific roof/content set.

## Map lifecycle and publication

### Full map load or warp

`LoadMapData` in [home/overworld.asm](../../home/overworld.asm) disables the LCD
and lets Yellow complete its normal map setup, tilemap copy, and
`SET_PAL_OVERWORLD` command first. It then calls `PassiveFullColorApplyMap`.

For an allowed map, the passive routine:

1. clears pending passive state;
2. marks the slice active for the current renderer generation;
3. commits all eight BG palettes; and
4. mirrors the complete 32 x 32 bank-0 BG map into bank 1, translating every
   tile through `FullColorOverworldTileAttributes`.

Because the LCD is off, that initial publication is atomic from the player's
point of view. The routine restores `rVBK` to bank 0 before Yellow resumes.

For any other map, it clears the passive state and active bit, then clears the
complete bank-1 BG map. The scene continues under ordinary Yellow rendering.

### Scrolling inside an active map

Yellow remains responsible for producing the next row or column of bank-0 tile
IDs. Immediately before the redraw is armed, `PassiveFullColorPrepareRedrawAttributes`
or `PassiveFullColorPrepareColumnAttributes` translates those finished tile
IDs outside VBlank into fixed records in `wFullColorAttributeRectangle`.

During VBlank, Yellow's `RedrawRowOrColumn` runs first. The consumed redraw mode
is preserved, then `PassiveFullColorVBlank` commits only the matching bank-1
row or column. Column records include their destination addresses so the
critical section does no per-row address reconstruction.

This ordering is invariant: source work happens before VBlank, Yellow's tile
write happens first, and the passive attribute write follows the same geometry.

### Palette refreshes and bounded VBlank work

Yellow is allowed to run fades and restore its palette. After `LoadGBPal`,
`PassiveFullColorRefreshAfterLoadGBPal` probes the active map's palette zero. If
the donor palette is no longer present, it queues republication rather than
writing palette RAM in ordinary visible time.

`PassiveFullColorVBlank` performs at most one passive visible operation per
frame:

- a Yellow row/column redraw wins the frame;
- otherwise one pending palette commit may run;
- otherwise one exit-cleanup chunk may run.

A palette request remains pending when a redraw wins. Combining both operations
in one frame is forbidden by the timing contract.

### Leaving the slice

The currently integrated door, warp, and connected-map routes reach
`PassiveFullColorApplyMap` with the LCD off, so they clear all 1024 bank-1
attributes immediately.

The passive module also provides a bounded LCD-on connection barrier through
`PassiveFullColorHandleConnection`. First,
`PassiveFullColorHomogenizeBGPalettes` copies palette 0's four colors across
palettes 1 through 7. That makes any not-yet-cleared attribute visually
equivalent to Yellow palette 0. The renderer then clears the 1024-byte bank-1
map in thirty-two 32-byte VBlank chunks. The entry side is used when an active
slice palette needs deferred republication; the full handler is also exposed
as an audit callable seam. Do not assume its exit branch protects a new natural
transition without verifying and testing the actual Yellow call site.

## Menus, dialogue, interiors, and battles

The passive renderer is an overworld layer, not a global display owner.

- Interiors are outside the map allowlist and use Yellow's normal palette and
  zeroed bank-1 attributes.
- Menus and dialogue may overwrite the visible attribute window while open.
  On close, Yellow rebuilds `wTileMap`; `PassiveFullColorRestoreAfterMenu`
  translates that final 20 x 18 window and restores it atomically with the LCD
  off.
- Battles and their transitions stay exact Yellow behavior. Returning to an
  allowed overworld map passes through normal map/view restoration, after which
  the passive attributes are reapplied.
- Sprites, battle effects, moving tiles, and cutscene objects are never inferred
  from background tile IDs.

If an overlay, battle, or interior starts showing donor tile attributes, that is
not broader renderer success. It is an ownership leak.

## State and fail-closed behavior

The passive state lives in WRAM bank 2 and is declared in
[ram/wram.asm](../../ram/wram.asm):

- `wPassiveFullColorActive` prevents map ID zero at power-on from being mistaken
  for a real loaded Pallet Town;
- `wPassiveFullColorPalettePending` records deferred palette publication;
- `wPassiveFullColorClearChunks` records bounded exit cleanup; and
- `wPassiveFullColorGeneration` binds that state to `wRendererGeneration`.

Every active-state read checks the saved generation. A mismatch clears the
active bit and all pending work. VBlank also repeats the map allowlist check
before publishing. Cleanup rejects chunk counts outside its only authored
range before deriving a VRAM address. These checks deliberately fail closed:
stale, pre-activation, reset, or aliased scratch data must result in no color
write, not a guessed recovery.

Bank preservation is equally load-bearing. Helpers use the ownership core's
`select_renderer_state_e` / `restore_renderer_state_e` protocol outside VBlank.
The interrupt path switches WRAM stacklessly, restores WRAM bank 1 before
popping, restores the interrupted raw `SVBK`, and leaves `rVBK` in the state
Yellow expects.

## Runtime invariants

Changes to the active renderer must preserve all of these:

1. Only a `PHASE2_AUDIT` build can reach the passive slice.
2. Only Pallet Town and Route 1 are active, until the full extension procedure
   proves another map.
3. Yellow owns all bank-0 tiles, sprites, mechanics, timing, fades, and overlays.
4. Passive code writes only complete BG palettes and bank-1 BG attributes.
5. Every attribute comes from the authored 256-byte table.
6. Initial map publication is LCD-off; visible updates are bounded to one
   passive VBlank operation.
7. A redraw commits Yellow's bank-0 tiles before matching bank-1 attributes.
8. Every exit removes or visually neutralizes all stale attributes.
9. Map identity, active state, and renderer generation must agree before a
   visible write.
10. `rVBK`, `rSVBK`, interrupt state, stack state, and Yellow's postconditions
    are restored exactly.

These are architectural boundaries, not test implementation details. A change
that makes a screenshot prettier by violating one of them is still wrong.

## Key code map

- [Makefile](../../Makefile): product targets and audit-only flags.
- [main.asm](../../main.asm): ROM layout and guarded module inclusion.
- [constants/full_color_constants.asm](../../constants/full_color_constants.asm):
  fixed ROM/WRAM banks, measured windows, and renderer constants.
- [ram/wram.asm](../../ram/wram.asm): ownership, scheduler, passive, and staging
  state.
- [engine/full_color/passive_overworld.asm](../../engine/full_color/passive_overworld.asm):
  live map gate, translation, publication, redraw, VBlank, and cleanup.
- [engine/full_color/passive_palette_refresh.asm](../../engine/full_color/passive_palette_refresh.asm):
  post-Yellow palette refresh detection.
- [data/tilesets/full_color_overworld.asm](../../data/tilesets/full_color_overworld.asm):
  live palette and tile-attribute authority.
- [home/overworld.asm](../../home/overworld.asm): map-load, connection, and
  scrolling integration.
- [home/vblank.asm](../../home/vblank.asm): bounded post-Yellow VBlank hook.
- [home/text_script.asm](../../home/text_script.asm) and
  [home/start_menu.asm](../../home/start_menu.asm): overlay restoration seams.
- [engine/full_color/ownership.asm](../../engine/full_color/ownership.asm),
  [scheduler.asm](../../engine/full_color/scheduler.asm), and related Phase 2
  modules: retained ownership architecture and proof surfaces, not the current
  passive presentation route.

## Roadmap boundary: Phases 3–9

The current slice does not collapse the remaining migration into “Phase 3.”
The authoritative [migration plan](../../specs/full-colors/docs/migration-plan.md)
separates the work and its exit gates:

- **Phase 3 — palette and transfers:** generalize lookup and map-aware palette
  selection; cover effects, load/reload paths, connections, overlays,
  animations, replacements, and paired transfer destinations.
- **Phase 4 — overworld OAM:** author picture-ID OBJ palettes after Yellow's
  final tile calculation while preserving follower offsets and DMA behavior.
- **Phase 5 — architecture stress:** prove combined pressure, poisoned handoff
  reconstruction, interrupted connections, timing margins, and deferral.
- **Phase 6 — tileset content:** independently author and accept all 25 Yellow
  tilesets, roofs, overrides, Beach House data, and animation compatibility.
- **Phase 7 — handoffs:** close every concrete map-to-Yellow and
  Yellow-to-overworld edge, including reset, nested, error, and soak paths.
- **Phase 8 — ownership deletion:** remove old Yellow overworld tint,
  attribute, adapter, and restoration paths while preserving excluded scenes.
- **Phase 9 — release hardening:** reconfirm numeric budgets, multi-frame
  behavior, soak coverage, and release/debug/VC reproducibility.

Until the relevant phases are proved, a new map belongs in the current slice
only when it can truthfully use the exact same global `OVERWORLD` attribute
table and palette set. Viridian City is the canonical warning: Phase 3 can
provide the map-aware palette/transfer mechanism, but Phase 6 must still supply
and accept correct Viridian roof/content data. An allowlist edit is only a
diagnostic canary, not finished color support.
