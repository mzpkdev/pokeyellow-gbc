# Full-color renderer

This manual describes the renderer that actually runs today and the approved
migration beyond it. It supplements the ROM-wide [ARCHITECTURE.md](ARCHITECTURE.md).
Procedures live in [ADDING_CONTENT.md](ADDING_CONTENT.md), and proof boundaries
live in [TESTING.md](TESTING.md).

## Current scope

The visible Phase 2 slice is an audit-only passive CGB color layer for Pallet
Town and Route 1. It is not a release feature and it is not the retained
full-color scheduler taking ownership of the game.

| Target | Product | Active passive slice |
| --- | --- | --- |
| `make yellow` | `pokeyellow.gbc` | No |
| `make yellow_debug` | `pokeyellow_debug.gbc` | No |
| `make yellow_vc` | VC ROM/patch | No |
| `make yellow_phase2_audit` | `pokeyellow_phase2_audit.gbc` | Yes |

The audit target defines both `_DEBUG` and `PHASE2_AUDIT`. Guarded code and data
are linked by [main.asm](../main.asm). Ordinary products must not acquire a
reachable passive renderer by accident.

## Ownership contract

Yellow remains authoritative for every bank-0 background tile and tile pattern;
sprite graphics, OAM, movement, and mechanics; map construction, scrolling,
menus, dialogue, battle, and cutscenes; and animations, overlays, fades, and
scheduling.

The passive slice may publish only:

- a complete set of eight CGB background palettes; and
- corresponding per-tile attributes in VRAM bank 1.

It translates the tile picture Yellow already finished. It never suppresses,
replaces, or races Yellow's bank-0 write. Object palettes are present in the
audit data ABI, but the passive path does not publish them; sprites stay under
Yellow control.

Earlier incomplete ownership attempts produced mismatched tilemaps and broken
cutscenes. Do not widen this boundary as a shortcut for another colored map.

## Active path and retained scaffolding

[engine/full_color/passive_overworld.asm](../engine/full_color/passive_overworld.asm)
is the live presentation path. Hooks in Yellow's normal map, redraw, menu,
palette, and VBlank flows call its `PassiveFullColor*` routines. The hard-coded
map gate accepts only `PALLET_TOWN` and `ROUTE_1`.

[engine/full_color/passive_palette_refresh.asm](../engine/full_color/passive_palette_refresh.asm)
detects a legitimate Yellow palette replacement after a fade or restoration
and queues passive republication for a bounded VBlank.

The following modules preserve measured contracts, debug observability, and
future migration seams but do not drive the current Pallet/Route 1 display:

- `ownership.asm` and `scheduler.asm`;
- `palettes.asm`, `transfers.asm`, and `oam.asm`; and
- most of `lifecycle.asm`.

The active audit VBlank calls `PassiveFullColorVBlank`; it does not route the
frame through `RouteRendererOwnershipVBlank`. The passive path reuses reviewed
WRAM2 storage and the renderer generation, but it does not acquire
`RENDERER_FULL_COLOR_OVERWORLD` ownership or enqueue ordinary scheduler jobs.
Compiled or callable scaffolding is not evidence of active presentation.

## Data authority

[data/tilesets/full_color_overworld.asm](../data/tilesets/full_color_overworld.asm)
contains every live slice color decision:

- `FullColorOverworldBGPalettes`: 64 bytes, eight complete four-color CGB BG
  palettes;
- `FullColorOverworldTileAttributes`: 256 bytes mapping each tile ID directly
  to an attribute;
- tile IDs `$00`–`$5f`: donor-derived `OVERWORLD` assignments;
- tile IDs `$60`–`$ff`: text palette 7;
- bank 0 and no authored priority for all current attributes; and
- palette 6: the Pallet roof colors used by both current maps.

The table records pinned donor provenance and has size assertions. Runtime uses
a direct lookup; there is no `tile_id & 7` or other legal-looking fallback.

Pallet Town and Route 1 can share this authority because both use Yellow's
`OVERWORLD` tileset and the accepted slice gives them the same roof identity.
That does not make the palette correct for every `OVERWORLD` map. Viridian City
is the canonical trap: adding it to an allowlist is a diagnostic canary, not
finished Viridian color.

## Map load and publication

`LoadMapData` in [home/overworld.asm](../home/overworld.asm) disables the LCD and
lets Yellow complete normal map setup, tilemap copy, and `SET_PAL_OVERWORLD`.
It then calls `PassiveFullColorApplyMap`.

For an allowed map, the passive routine:

1. clears pending passive state;
2. records active state for the current renderer generation;
3. commits all eight BG palettes; and
4. mirrors the complete 32×32 bank-0 BG map into bank 1, translating every tile
   through the authored attribute table.

The LCD-off publication is atomic to the player. The routine restores `rVBK`
to bank 0 before Yellow resumes.

For every other map, it clears passive state and the active bit, then clears
the complete bank-1 BG map. Yellow continues normally.

## Scrolling and VBlank

Yellow produces the next bank-0 row or column. Immediately before arming a
redraw, `PassiveFullColorPrepareRedrawAttributes` or
`PassiveFullColorPrepareColumnAttributes` translates those completed tile IDs
outside VBlank into fixed records in `wFullColorAttributeRectangle`.

During VBlank, Yellow's `RedrawRowOrColumn` executes first. The consumed redraw
mode is preserved, then `PassiveFullColorVBlank` commits the matching bank-1
row or column. Column records carry destination addresses so the critical
section does not reconstruct them per row.

The invariant is strict: prepare outside VBlank, Yellow tile write first,
matching passive attribute write second.

After `LoadGBPal`, `PassiveFullColorRefreshAfterLoadGBPal` checks the active
map's palette zero. If the donor palette is absent, it queues republication
instead of writing palette RAM during visible time.

At most one passive visible operation runs per frame:

1. a Yellow row/column redraw wins;
2. otherwise a pending palette commit may run;
3. otherwise one exit-cleanup chunk may run.

A palette request remains pending when a redraw wins. Combining them violates
the measured timing contract.

## Leaving the slice

Integrated doors, warps, and connected-map routes reach
`PassiveFullColorApplyMap` while the LCD is off, so all 1024 bank-1 attributes
are cleared immediately.

The module also exposes `PassiveFullColorHandleConnection` for a bounded LCD-on
barrier. `PassiveFullColorHomogenizeBGPalettes` first copies palette 0 across
palettes 1–7, making uncleared attributes visually equivalent to Yellow palette
0. It then clears the 1024-byte bank-1 map in thirty-two 32-byte VBlank chunks.
The entry side supports deferred palette republication; the complete handler is
also an audit-callable seam. Never assume a new natural transition reaches the
right branch without verifying its Yellow call site.

## Menus, interiors, dialogue, and battles

The passive renderer is an overworld layer, not global display ownership.

- Interiors are outside the map gate and use Yellow palettes with cleared
  bank-1 attributes.
- Menus and dialogue can overwrite the visible attribute window. On close,
  Yellow rebuilds `wTileMap`, then `PassiveFullColorRestoreAfterMenu` translates
  the final 20×18 window and restores it LCD-off.
- Battles and transitions remain Yellow behavior. Normal map restoration
  reapplies the passive attributes when returning to an allowed map.
- Sprites, battle effects, moving tiles, and cutscene objects are never inferred
  from background tile IDs.

Donor attributes appearing in an overlay, interior, or battle are an ownership
leak, not evidence of broader renderer support.

## State and fail-closed behavior

Passive state is declared in [ram/wram.asm](../ram/wram.asm) and lives in WRAM2:

- `wPassiveFullColorActive` prevents power-on map ID zero from impersonating a
  loaded Pallet Town;
- `wPassiveFullColorPalettePending` records deferred palette work;
- `wPassiveFullColorClearChunks` records bounded cleanup; and
- `wPassiveFullColorGeneration` binds state to `wRendererGeneration`.

Every active-state read validates the generation. A mismatch clears active and
pending work. VBlank repeats the map allowlist check before publishing. Cleanup
rejects unauthored chunk counts before deriving a VRAM address. Stale, reset,
pre-activation, or aliased state therefore produces no color write.

Helpers use the ownership core's `select_renderer_state_e` /
`restore_renderer_state_e` protocol outside VBlank. The interrupt path switches
WRAM stacklessly, restores WRAM bank 1 before popping, restores the interrupted
raw `SVBK`, and leaves `rVBK` as Yellow expects.

## Load-bearing invariants

1. Only a `PHASE2_AUDIT` build reaches the passive slice.
2. Only Pallet Town and Route 1 are active until the extension procedure proves
   another map.
3. Yellow owns bank-0 tiles, sprites, mechanics, timing, fades, and overlays.
4. Passive code writes only complete BG palettes and bank-1 BG attributes.
5. Every attribute comes from the authored 256-byte table.
6. Initial publication is LCD-off; visible work is one bounded passive VBlank
   operation.
7. Yellow's bank-0 redraw precedes the corresponding bank-1 attribute commit.
8. Every exit removes or neutralizes stale attributes.
9. Map identity, active state, and renderer generation agree before a visible
   write.
10. `rVBK`, `rSVBK`, interrupt state, stack state, and Yellow postconditions are
    restored exactly.

A prettier screenshot does not justify breaking one of these contracts.

## Evidence boundary

The active-runtime claim must be supported by the audit ROM, not merely by
source inspection or synthetic machinery. Verification spans model tests,
built-ROM probes, retained deterministic gates, and natural gameplay journeys.
Each catches different failures; none makes the others redundant.

The synthetic renderer conformance checker proves its own modeled contract. It
does not prove that gameplay routes through the passive path. Phase 1 runtime
evidence proves ownership supersession mechanics, not global coloring. A single
screenshot can show palette quality but cannot prove scrolling, timing,
handoffs, flicker, or cutscene correctness. The exact commands and limitations
are in [TESTING.md](TESTING.md).

## Code map

- [Makefile](../Makefile): products and audit flags.
- [main.asm](../main.asm): guarded ROM placement.
- [constants/full_color_constants.asm](../constants/full_color_constants.asm):
  ROM/WRAM banks, windows, and renderer constants.
- [ram/wram.asm](../ram/wram.asm): ownership, scheduler, passive, and staging
  state.
- [engine/full_color/passive_overworld.asm](../engine/full_color/passive_overworld.asm):
  live activation, translation, redraw, VBlank, and cleanup.
- [engine/full_color/passive_palette_refresh.asm](../engine/full_color/passive_palette_refresh.asm):
  post-Yellow refresh detection.
- [data/tilesets/full_color_overworld.asm](../data/tilesets/full_color_overworld.asm):
  current palette and attribute authority.
- [home/overworld.asm](../home/overworld.asm) and
  [home/vblank.asm](../home/vblank.asm): map and interrupt integration.
- `home/text_script.asm` and `home/start_menu.asm`: overlay restoration seams.

## Roadmap: Phases 3–9

The authoritative
[migration plan](../specs/full-colors/docs/migration-plan.md) separates the
remaining work and exit gates:

- **Phase 3 — palette and transfers:** map-aware palette selection; effects,
  reloads, connections, overlays, animations, replacements, and paired
  transfer destinations.
- **Phase 4 — overworld OAM:** authored picture-ID OBJ palettes after Yellow's
  final tile calculation, preserving follower offsets and DMA behavior.
- **Phase 5 — architecture stress:** combined pressure, poisoned handoff
  reconstruction, interrupted connections, timing margins, and deferral.
- **Phase 6 — tileset content:** independently authored and accepted data for
  all 25 Yellow tilesets, roofs, overrides, Beach House, and animations.
- **Phase 7 — handoffs:** every concrete map-to-Yellow and Yellow-to-overworld
  edge, including resets, nesting, errors, and soak paths.
- **Phase 8 — ownership deletion:** remove superseded Yellow overworld tint,
  attribute, adapter, and restoration paths while preserving excluded scenes.
- **Phase 9 — release hardening:** numeric budgets, multi-frame behavior, soak
  coverage, and release/debug/VC reproducibility.

Until the relevant phases are proved, a new map belongs in the passive slice
only if it truthfully uses the exact current `OVERWORLD` palette and attribute
authority. Phase 3 can introduce map-aware selection; Phase 6 still has to
author and accept correct map-specific content. Follow
[ADDING_CONTENT.md](ADDING_CONTENT.md) instead of editing the allowlist in
isolation.
