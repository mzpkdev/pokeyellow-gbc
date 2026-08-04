# Full-color renderer

This manual describes the renderer that actually runs today and the approved
migration beyond it. It supplements the ROM-wide [ARCHITECTURE.md](ARCHITECTURE.md).
Procedures live in [ADDING_CONTENT.md](ADDING_CONTENT.md), and proof boundaries
live in [TESTING.md](TESTING.md).

## Current scope

Normal, debug, and VC builds expose `COLOR MODE: COLOR/YELLOW` in Options.
`COLOR` selects the production full-color owner only for ordinary presentation
of Pallet Town and Route 1. `YELLOW` keeps Yellow ownership everywhere.

Dialogue, menus, battles, interiors, standalone scenes, unsupported maps,
boot, hard reset, and soft reset are always Yellow-owned. Preference is policy
input only: changing the saved bit never writes presentation state. The next
real presentation boundary performs any required ownership handoff.

| Target | Product | Playable policy |
| --- | --- | --- |
| `make yellow` | `pokeyellow.gbc` | COLOR/YELLOW |
| `make yellow_debug` | `pokeyellow_debug.gbc` | COLOR/YELLOW |
| `make yellow_vc` | VC ROM/patch | COLOR/YELLOW |
| `make yellow_phase2_audit` | `pokeyellow_phase2_audit.gbc` | Independent passive audit |

The Phase 2 audit product remains byte-pinned and independently verified. Its
debug carriers and passive hooks are not linked into production products.

## Ownership contract

Exactly one renderer owns every owner-gated resource. Under Color ownership the
production scheduler exclusively publishes the ordinary Pallet/Route 1 map,
scroll/window state, authored palettes and attributes, paired movement and
connection transfers, supported animated/field tiles, and OAM. Yellow's
owner-gated VBlank writers are skipped.

Under Yellow ownership no Color producer or commit may write. Yellow owns all
forced contexts and all maps when the player selects `YELLOW`. Owner-neutral
input, time, audio, serial, and interrupt cleanup still run once per frame.

Every real handoff cancels or completes departing work, advances exactly one
fresh generation, reconstructs the complete destination from logical
authority while admission is closed, crosses one presentation barrier, then
reopens admission. Same-owner boundaries retain the generation and use the
current owner's ordinary destination path.

Earlier incomplete ownership attempts produced mismatched tilemaps and broken
cutscenes. Do not widen this boundary as a shortcut for another colored map.

## Production path and retained audit

[engine/full_color/policy.asm](../engine/full_color/policy.asm) resolves the
saved preference, context, and map without side effects. Lifecycle boundaries
in `lifecycle.asm` apply that policy; `ownership.asm` owns generations and
admission; `scheduler.asm` owns Color commits. `home/vblank.asm` selects one
visible route before its first writer.

[engine/full_color/passive_palette_refresh.asm](../engine/full_color/passive_palette_refresh.asm)
detects a legitimate Yellow palette replacement after a fade or restoration
and queues passive republication for a bounded VBlank.

The separate audit ROM still calls `PassiveFullColorVBlank` and preserves the
prior passive slice as an evidence authority. Compiled or callable audit
machinery is not production reachability.

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

The production Color renderer is an ordinary two-map owner, not global display
ownership.

- Interiors are outside the map gate and use Yellow palettes with cleared
  bank-1 attributes.
- Menus and dialogue force a complete Color-to-Yellow handoff before their
  first writer. Their close path resolves policy and reconstructs the ordinary
  map owner.
- Battles, interiors, standalone scenes, boot, and reset use the same forced
  Yellow contract. Returning to eligible ordinary maps reconstructs Color only
  when `COLOR` remains selected.
- Unsupported maps resolve Yellow without changing the saved preference.

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

1. Production Color is reachable only through policy plus a lifecycle handoff.
2. Only Pallet Town and Route 1 are Color-owned until the extension procedure proves
   another map.
3. Yellow owns overlays, dialogue, menus, battles, standalone scenes,
   unsupported maps, reset, and every map under `YELLOW` preference.
4. Color and Yellow owner-gated writers never run under the other owner.
5. Every attribute comes from the authored 256-byte table.
6. Initial Color reconstruction is LCD-off; later visible work is one bounded,
   owner-exclusive Color VBlank operation.
7. Color publishes its coordinated attributes, palettes, and OAM only on the
   Color route; Yellow redraw and palette writers run only on the Yellow route.
8. Every exit removes or neutralizes stale attributes.
9. Map identity, active state, and renderer generation agree before a visible
   write.
10. `rVBK`, `rSVBK`, interrupt state, stack state, and Yellow postconditions are
    restored exactly.

A prettier screenshot does not justify breaking one of these contracts.

## Evidence boundary

The active-runtime claim must be supported by production ROMs, while the audit
ROM remains an independent retained authority. Verification spans model tests,
built-ROM probes, deterministic gates, and natural gameplay journeys.
Each catches different failures; none makes the others redundant.

Run `make test-full-color-fast` while iterating and
`make test-full-color-certify` before integration. Certification retains both
independent Gate 0 runs and their comparator, Phase 1 runtime evidence,
mutation-sensitive conformance, source-transition authority, numeric exact-fit
and threshold-plus-one timing evidence, the pinned donor comparator, and Phase
2 audit verification. A screenshot proves none of those contracts.

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
