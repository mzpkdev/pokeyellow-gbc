# Full-color renderer

This manual is the normative contract for the renderer that actually runs
today and describes the proposed migration beyond it. It supplements the
ROM-wide [ARCHITECTURE.md](ARCHITECTURE.md).
Procedures live in [ADDING_CONTENT.md](ADDING_CONTENT.md), and proof boundaries
live in [TESTING.md](TESTING.md).

## Current scope

The shipped renderer is a bounded passive CGB color layer for the 34 city and
route maps that use `OVERWORLD` and the conventional interior maps using
tileset IDs `REDS_HOUSE_1` through `FACILITY`, excluding `FOREST`, `SHIP_PORT`,
and `CAVERN`. Those 19 tilesets cover 162 maps. `PLATEAU` and `BEACH_HOUSE`
also remain Yellow. The normal, debug, and VC products
expose a saved `COLOR MODE`
preference between `COLOR` and `YELLOW`; fresh saves default to Color, Continue
retains the saved choice, and New Game may reset it to Color. It is a release
feature, but it is not the retained full-color scheduler taking ownership of
the game.

`passive_overworld` is the only active color presentation path. No plan,
compiled module, callable symbol, retained test, or migration proposal changes
that fact without a separately approved architecture change.

| Target | Product | Active passive slice |
| --- | --- | --- |
| `make yellow` | `pokeyellow.gbc` | Yes |
| `make yellow_debug` | `pokeyellow_debug.gbc` | Yes |
| `make yellow_vc` | VC ROM/patch | Yes |
| `make yellow_phase2_audit` | `pokeyellow_phase2_audit.gbc` | Yes |

The audit target defines both `_DEBUG` and `PHASE2_AUDIT`, but that flag adds
only extra diagnostics and certification surfaces. The toggle, passive code,
data, state, and hooks are unconditional product functionality; runtime mode
selection, never `PHASE2_AUDIT`, decides whether Color is presented.

## Ownership contract

Yellow MUST retain authority for every bank-0 background tile and tile pattern;
sprite graphics, OAM, movement, and gameplay; map construction, scrolling,
menus, dialogue, battle, and cutscenes; and animations, overlays, fades,
scheduling, and lifecycle behavior.

The passive Color path MAY publish only:

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
palette, and VBlank flows call its `PassiveFullColor*` routines in every
shipped product. The activation gate requires the saved Color preference and
accepts either a city/route map whose loaded tileset is `OVERWORLD` or an
authored conventional-interior tileset from the bounded range above.
While Start or Options is open, the active presentation remains
latched; the saved preference is reconciled only when the outer menu closes.

[engine/full_color/passive_palette_refresh.asm](../engine/full_color/passive_palette_refresh.asm)
detects a legitimate Yellow palette replacement after a fade or restoration
and queues passive republication for a bounded VBlank.

The following modules preserve measured contracts, debug observability, and
future migration seams but do not drive the current passive display:

- `ownership.asm` and `scheduler.asm`;
- `palettes.asm`, `transfers.asm`, and `oam.asm`; and
- most of `lifecycle.asm`.

The active production VBlank calls `PassiveFullColorVBlank`; it does not route
the frame through `RouteRendererOwnershipVBlank`. The passive path reuses
reviewed WRAM2 storage and the renderer generation, but it does not acquire
`RENDERER_FULL_COLOR_OVERWORLD` ownership or enqueue ordinary scheduler jobs.
Compiled or callable scaffolding is not evidence of active presentation.
Retained ownership, scheduler, and lifecycle machinery MUST NOT be activated,
used as current presentation authority, or treated as the foundation of a
broader renderer without a separately approved architecture change.

## Data authority

[data/tilesets/full_color_overworld.asm](../data/tilesets/full_color_overworld.asm)
contains the live outdoor decisions, while
[data/tilesets/full_color_interiors.asm](../data/tilesets/full_color_interiors.asm)
contains the interior palette/attribute pointer tables and donor payloads:

- `FullColorOverworldBGPalettes`: 64 bytes, eight complete four-color CGB BG
  palettes;
- `FullColorOverworldTileAttributes`: 256 bytes mapping each tile ID directly
  to an attribute;
- tile IDs `$00`–`$5f`: donor-derived `OVERWORLD` assignments;
- tile IDs `$60`–`$ff`: text palette 7;
- bank 0 and no authored priority for all current attributes; and
- `FullColorOverworldRoofAssignments`: one donor roof identity for each city
  and route map ID;
- `FullColorOverworldRoofPalettes`: the eleven donor roof color pairs; and
- palette 6: common outdoor edge colors with map-aware roof middle colors;
- every admitted tileset selects a complete 64-byte BG palette payload and a
  complete 256-byte tile attribute lookup;
- identical donor palette sets and assignment maps are shared by pointer;
- all interior tile IDs `$60`–`$ff` explicitly use palette 7; and
- two donor map overrides apply after tileset lookup: `CELADON_MART_ROOF`
  tiles `$4b`–`$4f` use palette 3, and `CELADON_MART_1F` tiles `$07`, `$08`,
  `$17`, and `$18` use palette 4.

The tables record pinned donor provenance and have size assertions. Runtime uses
a direct lookup; there is no `tile_id & 7` or other legal-looking fallback.

Each admitted map keeps the Yellow graphics selected by its own map header.
Runtime selects the corresponding donor-authored tileset palette payload and
tile-to-attribute table. Outdoor maps additionally select donor roof colors;
Route 6 uses Saffron roof colors in its top rows and Vermilion colors elsewhere.

## Map load and publication

`LoadMapData` in [home/overworld.asm](../home/overworld.asm) disables the LCD and
lets Yellow complete normal map setup, tilemap copy, and `SET_PAL_OVERWORLD`.
It then calls `PassiveFullColorApplyMap`.

For an allowed map while Color is selected, the passive routine:

1. clears pending passive state;
2. records active state for the current renderer generation;
3. commits all eight BG palettes; and
4. mirrors the complete 32×32 bank-0 BG map into bank 1, translating every tile
   through the authored attribute table.

The LCD-off publication is atomic to the player. The routine restores `rVBK`
to bank 0 before Yellow resumes.

For Yellow mode or every other map, it clears passive state and the active bit,
then clears the complete bank-1 BG map. Yellow continues normally.

## Scrolling and VBlank

Yellow produces the next bank-0 row or column. Immediately before arming a
redraw, `PassiveFullColorPrepareRedrawAttributes` or
`PassiveFullColorPrepareColumnAttributes` translates those completed tile IDs
outside VBlank into fixed records in `wPassiveFullColorRedrawStaging`.

During an ordinary scrolling VBlank, Yellow's `RedrawRowOrColumn` executes
first and publishes the offscreen bank-0 strip. The consumed mode changes the
frozen redraw record from prepared to mirror-pending. The next redraw-free
VBlank commits the matching bank-1 row or column, before another producer may
reuse the single slot. Column records carry destination addresses so the
critical section does not reconstruct them per row.

The hidden overlay activation barrier is the exception. A fresh menu translates
the finalized 20x18 tilemap once, then publishes two attribute rows in each of
the first nine VBlanks. A tenth no-copy VBlank observes the terminal row cursor,
completes the private transfer lifecycle, and arms Yellow's stock six-row
`AutoBgMapTransfer`; the caller's existing `Delay3` therefore completes the
bank-0 sweep before reveal. Fresh presentation takes ten passive frames plus
those three caller frames. Later cursor movement rearms only that finite
three-frame sweep because the completed attribute plane returns immediately.
The sweep then disables stock publication so ordinary OAM and queued video work
resume on the next VBlank. A submenu that clears `hAutoBGTransferEnabled` also
clears the completion latch, so returning to the menu correctly performs a
fresh attribute publication.

Initial attribute publication owns one bounded 40-byte transfer per frame, and
any pending Yellow redraw remains armed until the barrier finishes. While the
completed plane is latched, ordinary passive palette and redraw work stays
excluded. Each stock six-row bank-0 publication owns that frame's visible-write
budget and resumes at the common non-video interrupt tail. Dialogue retains
continuous Yellow tile publication while letters print, but inserts one full
visible-work recovery VBlank after every three stock chunks; menus use one
finite sweep and then remain on ordinary VBlanks until another update.

The scrolling invariant is strict: prepare outside VBlank, Yellow tile write
first, matching passive attribute write second, and apply producer backpressure
until both halves finish. The hidden overlay instead completes its translated
attribute plane before Yellow's three-frame bank-0 sweep. Overlay attributes and
redraw records use separate WRAM2 storage, so either may be staged first without
corrupting the other.

After `LoadGBPal`, `PassiveFullColorRefreshAfterLoadGBPal` checks the active
map's palette zero. If the donor palette is absent, it queues republication
instead of writing palette RAM during visible time.

At most one passive visible operation runs per frame:

1. an armed overlay-transfer step wins and defers any Yellow redraw;
2. otherwise a Yellow row/column redraw wins and arms its passive mirror;
3. otherwise a pending passive redraw mirror wins;
4. otherwise one remaining activation-barrier step may run;
5. otherwise a pending palette commit may run;
6. otherwise one exit-cleanup chunk may run.

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
also a diagnostic-callable seam. Never assume a new natural transition reaches the
right branch without verifying its Yellow call site.

## Menus, maps, dialogue, and battles

The passive renderer is a bounded map layer, not global display ownership.

- Conventional interiors in the admitted tileset range use their selected
  donor payload. `FOREST`, `SHIP_PORT`, `CAVERN`, `PLATEAU`, `BEACH_HOUSE`, and any other
  unsupported map use Yellow palettes with cleared bank-1 attributes.
- Menus and dialogue can overwrite the visible attribute window. On close,
  a Color-to-Yellow handoff clears donor attributes before Yellow can replace
  the palettes. Yellow then rebuilds `wTileMap`, and
  `PassiveFullColorRestoreAfterMenu` reconciles the selected presentation. An
  already-active Color presentation refreshes its palettes. Yellow-to-Color
  activation keeps Color inactive and donor palettes unpublished while two
  wrapped visible rows are published per VBlank, then commits all donor
  palettes and activates Color in one later VBlank. Yellow mode reruns Yellow's
  authoritative overworld palette command and leaves passive state inactive.
- Battles and transitions remain Yellow behavior. Normal map restoration
  reapplies the passive attributes when returning to an allowed map.
- Sprites, battle effects, moving tiles, and cutscene objects are never inferred
  from background tile IDs.

Donor attributes appearing in an overlay, unsupported map, or battle are an
ownership leak, not evidence of broader renderer support.

## State and fail-closed behavior

Passive state is declared in [ram/wram.asm](../ram/wram.asm) and lives in WRAM2:

- `wPassiveFullColorActive` prevents power-on map ID zero from impersonating a
  loaded Pallet Town;
- `wPassiveFullColorPalettePending` records deferred palette work;
- `wPassiveFullColorClearChunks` records bounded cleanup;
- `wPassiveFullColorGeneration` binds state to `wRendererGeneration`; and
- `wPassiveFullColorDeferredRedrawState` owns one prepared or mirror-pending
  redraw transaction; `wPassiveFullColorRedrawStaging` holds its immutable
  destination and attribute records outside the overlay translation plane.

`InitRendererOwnership` clears the complete private passive allocation before
any map can be treated as active. The allocation is unconditional and does not
alias the audit scheduler or its timing scratch.

Every active-state read validates the generation. A mismatch clears active and
pending work. VBlank repeats the map allowlist check before publishing. Cleanup
rejects unauthored chunk counts before deriving a VRAM address. Stale, reset,
pre-activation, or aliased state therefore produces no color write.

Helpers use the ownership core's `select_renderer_state_e` /
`restore_renderer_state_e` protocol outside VBlank. The interrupt path switches
WRAM stacklessly, restores WRAM bank 1 before popping, restores the interrupted
raw `SVBK`, and leaves `rVBK` as Yellow expects.

## Load-bearing invariants

1. Every normal, debug, and VC build exposes the same bounded passive slice;
   `PHASE2_AUDIT` may add diagnostics but MUST NOT gate its behavior.
2. Only the saved Color preference on admitted `OVERWORLD` or conventional
   interior maps is active.
3. Yellow owns bank-0 tiles, sprites, mechanics, timing, fades, and overlays.
4. Passive code writes only complete BG palettes and bank-1 BG attributes.
5. Every attribute comes from the selected authored 256-byte table or one of
   the two authored Celadon Mart map overrides.
6. Initial publication is LCD-off; every live transition is a bounded sequence
   of one-operation passive VBlanks with palettes committed only after the
   corresponding visible attribute plane is coherent.
7. Yellow's bank-0 redraw precedes the corresponding bank-1 attribute commit.
8. Every exit removes or neutralizes stale attributes.
9. Map identity, active state, and renderer generation agree before a visible
   write.
10. `rVBK`, `rSVBK`, interrupt state, stack state, and Yellow postconditions are
    restored exactly.

A prettier screenshot does not justify breaking one of these contracts.

## Evidence boundary

The active-runtime claim must be supported in each shipped product, not merely
by source inspection, the audit ROM, or synthetic machinery. Runtime journeys
select Color and Yellow within the same production binary. Verification spans
model tests, built-ROM probes, retained deterministic gates, and natural
gameplay journeys. Each catches different failures; none makes the others
redundant.

The synthetic renderer conformance checker proves its own modeled contract. It
does not prove that gameplay routes through the passive path. Phase 1 runtime
evidence proves ownership supersession mechanics, not global coloring. A single
screenshot can show palette quality but cannot prove scrolling, timing,
handoffs, flicker, or cutscene correctness. The exact commands and limitations
are in [TESTING.md](TESTING.md).

## Code map

- [Makefile](../Makefile): products and audit flags.
- [main.asm](../main.asm): production placement and audit-only diagnostic
  placement.
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
- **Phase 6 — bounded content:** independently authored and accepted data,
  overrides, and animation/field-replacement behavior reached by Pallet Town
  and Route 1.
- **Phase 7 — handoffs:** every concrete map-to-Yellow and Yellow-to-overworld
  edge, including resets, nesting, errors, and soak paths.
- **Phase 8 — ownership deletion:** remove superseded Yellow overworld tint,
  attribute, adapter, and restoration paths while preserving excluded scenes.
- **Phase 9 — release hardening:** numeric budgets, multi-frame behavior, soak
  coverage, and release/debug/VC reproducibility.

All-25-tileset and all-map color authoring remains future non-gating work after
the bounded release. It is not implied by the shipped toggle.

Until the relevant phases are proved, maps outside the current city/route
`OVERWORLD` set remain Yellow-owned. Phase 3 can introduce wider tileset-aware
selection; Phase 6 still has to author and accept other map-specific content.
Follow
[ADDING_CONTENT.md](ADDING_CONTENT.md) instead of editing the allowlist in
isolation.
