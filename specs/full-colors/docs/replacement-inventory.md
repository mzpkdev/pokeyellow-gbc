# Overworld replacement inventory

This document defines the evidence schemas that migration Phase 0 must
populate. It contains no claim that source or built-ROM discovery is complete.

## Donor evidence policy

Every donor reference below is pinned to `git@github.com:dannye/pokered-gbc.git`
commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`. The ten mechanism paths are
mechanism-only evidence. The separately listed five payload paths authorize
only the already accepted OVERWORLD palette and corrected 96-byte attribute
slice. All other donor values, mappings, roofs, OAM assignments, content, and
data organization remain candidate artistic or organizational evidence. The
donor supplies no Yellow scene lifecycle, ownership decision, ABI, bank, or
WRAM placement, and every retained candidate is independently authored,
reviewed, and validated against Yellow.

The disposition vocabulary is:

- `MECHANISM`: inspect the algorithm or data organization as evidence;
- `ADAPT`: independently review the candidate against Yellow and the normative
  requirements before using it; and
- `EXCLUDE`: do not import its runtime behavior.

## Donor mechanism inventory

| Pinned RGB source | Disposition | Evidence or required adaptation |
|---|---|---|
| `color/init.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | CGB double-speed sequencing only; initialization follows Yellow owner/reset requirements |
| `color/wram.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `MECHANISM` | semantic state categories only; no bank, address, size, or representation is inherited |
| `color/loadpalettes.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | candidate palette-loading organization only; Yellow assignments, roofs, and overrides are independently authored and validated |
| `color/refreshmaps.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `MECHANISM` | paired map/window tile and attribute transfer mechanics |
| `color/vblank.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `MECHANISM` | transformation and scheduling mechanics; Yellow timing must be measured |
| `color/super_palettes.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `MECHANISM` | loading four-color RGB555 palettes |
| overworld portion of `color/color.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | candidate palette-selection organization only; Yellow values are independently authored and ownership follows Yellow's explicit state |
| overworld portion of `color/sprites.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | candidate final-picture OAM organization only; Yellow mappings are independently authored and validated |
| `color/boulder.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | moving-overworld-object evidence where Yellow behavior matches |
| `color/ssanne.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `ADAPT` | Vermilion Dock/ship exception audited against Yellow maps and tiles |

## Donor payload authorities

The frozen OVERWORLD payload is derived only from these five authorities; they
are not part of the broader ten-path mechanism inventory.

| Pinned RGB source | Payload authority |
|---|---|
| `color/data/map_palettes.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | palette RGB rows |
| `color/data/map_palette_sets.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `OverworldPalSet` selection |
| `color/data/roofpalettes.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `PalletRoof` middle colors |
| `color/data/map_palette_constants.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | palette attribute values |
| `color/tilesets/overworld.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | 94 authored tile entries, corrected at `$5e/$5f` to explicit `GRAY, GRAY` using the historic `a8b62fb990a13da6add30c92f8440b296dddce49` parent of cleanup `cb6bb66dc91a7a162f442f3bd81ea2887558ada4` |

Every retained candidate must use Yellow's MBC5 banks, labels, interrupt
model, measured timing, explicit ownership, and current-generation jobs.

## Donor modules excluded

| Pinned RGB source or subsystem | Disposition | Reason |
|---|---|---|
| battle palette commands in `color/color.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | battle rendering remains Yellow-owned |
| non-overworld portions of `color/sprites.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | standalone object rendering remains Yellow-owned |
| `color/animations.asm@c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | non-overworld animation ownership is excluded |
| HP/EXP bar color modules at `c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | battle HUD remains Yellow-owned |
| trade, cable club, slots, status, and Oak intro color modules at `c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | standalone presentation remains Yellow-owned |
| ghost Marowak and HUD Poké Ball modules at `c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | picture and battle HUD behavior is excluded |
| RGB DMG fallback bank binary at `c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | the product is CGB-only |
| static 20×18 palette-map and restoration behavior at `c1a3b6c5a7591472241036d0cf09c3817f841f93` | `EXCLUDE` | return reconstruction follows R2.10, R2.11, R2.12, and R2.13 |

Palette values from excluded systems may be candidate artistic reference only.
Outside the five frozen OVERWORLD payload authorities above, no donor content
is authoritative, and no excluded runtime lifecycle is imported.

## Inventory closure

Source search and built-ROM symbol/disassembly review must agree within the
declared slice. A source allowlist without reachable-scene review is incomplete.
Migration Phase 0 proves discovery, assignment, review, and closure on the
initial map-entry slice. Each later phase declares the paths it touches and
closes their concrete rows before the changed path becomes reachable. This
documentation defines the schemas and closure rule; it does not require an
exhaustive audit of untouched Yellow code before Phase 1.

Slice closure requires a one-to-one reviewed row for every in-slice discovered:

- reachable owner-gated writer, including aliases and wrapper-mediated writes;
- scene lifecycle and each entry/return ownership boundary; and
- visible-map mutation path and distinct destination/commit-unit behavior.

Aliases that resolve to one machine writer may share one writer row only when
the evidence names every alias and reachability path. A wrapper receives its
own writer row when it can authorize, redirect, suppress, schedule, launch, or
order a write. One source symbol receives multiple rows when it has materially
different resources, permissions, destinations, or commit units. Generated and
hand-written code are held to the same rule.

Phase 0 is green when source and built-ROM results reconcile for the initial
map-entry slice, every in-slice finding has one reviewed disposition, and the
audit fails under synthetic unlisted writer, lifecycle, boundary, and mutation
fixtures. A later phase must declare its implementation slice, add or update
fully populated `WR-…`, `SC-…`, and `MU-…` rows, review them, and rerun source
plus built-ROM reconciliation before the changed path becomes reachable. An
unexpected in-slice discovery reopens that phase gate; out-of-slice findings
remain backlog evidence rather than blocking unrelated work. This supplies the inventory evidence required by
[R1.7](requirements.md#r1-renderer-ownership),
[R12.8](requirements.md#r12-isolation-and-removal), and
[AC-INV-01](acceptance-criteria.md#cross-cutting-contract-outcomes).

## Writer inventory schema

A concrete writer ID uses `WR-` followed by a unique stable reviewed identifier.
Renaming or moving a symbol does not silently reassign its ID; splits and
merges retain explicit history in the evidence artifact.

| Writer ID (`WR-…`) | Resource/address | `path:symbol` | direct/indirect/wrapper/DMA/interrupt | reachable phases | owner/generation permission | disposition | requirement | evidence |
|---|---|---|---|---|---|---|---|---|

Every row names all affected byte ranges/registers, call and interrupt
reachability, the effective owner and generation check, keep/replace/route/
remove disposition, concrete requirement IDs, and source plus ROM evidence.

## Scene inventory schema

A concrete scene ID uses `SC-` followed by a unique stable reviewed identifier.
Each lifecycle and each directional ownership boundary receives its own row;
grouped scope prose is not a substitute for concrete reachable entries/exits.

| Scene ID (`SC-…`) | source `path:symbol` | destination `path:symbol` | `MAP_BACKED`/`STANDALONE`/`SCENE_BOUNDARY` | owner before destination initialization | reconstruction trigger | reset/nested/error edges | requirement | evidence |
|---|---|---|---|---|---|---|---|---|

Every row records all aliases, concrete directed control-flow edges, nesting,
reset and error behavior, destination-initialization entry, first reachable
display writer, transfer direction where applicable, concrete requirement
IDs, and source plus ROM reachability evidence. A standalone lifecycle row
does not imply either direction of a map boundary. Each actual map-to-Yellow
and Yellow-to-map ownership transfer receives a separate `SCENE_BOUNDARY` row;
boot and Yellow-to-Yellow nested, return, failure, and error edges remain
Yellow-owned rows and do not trigger reconstruction. These scene labels
classify scene rows only; they do not classify resources, routines,
mechanisms, or responsibilities.

## Mutation inventory schema

A concrete mutation ID uses `MU-` followed by a unique stable reviewed
identifier. One row represents one observable mutation behavior; a symbol
with multiple destinations or commit-unit shapes receives separately reviewed
rows or explicit exhaustive variants in its evidence.

| Mutation ID (`MU-…`) | `path:symbol` | trigger/destination | tile source | attribute source | commit unit | owner/phase | requirement | evidence |
|---|---|---|---|---|---|---|---|---|

Every row records source/destination coordinate handling, clipping, tile and
attribute authority, declared resource dependencies, visible boundary,
effective owner/phase/generation, concrete requirement IDs, and source plus ROM
evidence.

## Writer discovery coverage

Discovery reviews definitions, aliases, macro expansion, generated assembly,
callers, wrappers, interrupt vectors, DMA launch/wait code, and built-ROM
instructions. It distinguishes reads from writes but does not discard a
finding until the disassembly proves its operation and reachability.

The source search must include symbolic and raw writes to:

- every address from `$ff40` through `$ff4b`, including `rLCDC`, `rSTAT`,
  `rSCY`, `rSCX`, `rLYC`, `rDMA` at `$ff46`, `rBGP`, `rOBP0`, `rOBP1`,
  `rWY`, and `rWX`;
- `rVBK` at `$ff4f`, HDMA/GDMA registers `$ff51`–`$ff55`, CGB palette
  registers `$ff68`–`$ff6b`, and `rSVBK` at `$ff70`;
- indirect high-memory forms through `$ff00+c`, computed pointers, register
  aliases, macros, and copied/executed HRAM DMA code;
- bank-0 and bank-1 BG/window tilemap destinations, including `$9800`–`$9fff`,
  alternate destinations, rectangles, and LCD-off paths;
- the complete shadow-OAM lifecycle: allocate, initialize, clear, build,
  palette-map, sort/copy, invalidate, reset, and handoff;
- hardware OAM `$fe00`–`$fe9f`, including direct writes, LCD-off initialization
  and clear, DMA destinations, reset, and handoff invalidation;
- every shadow-OAM source page, `rDMA` launch and wait wrapper, interrupt
  ordering path, and hardware-OAM completion path; and
- OAM attribute writers, including player, follower, NPC, object, animation,
  field-effect, and fallback mapping paths.

Yellow-named routines called during full-color operation are inventoried under
the effective owner's phase and generation, not classified by their name. This
applies to shadow OAM, hardware OAM, and OAM DMA allocation, construction,
copy/sort, launch, and wait mechanisms.

Initial source-search seeds include:

```sh
rg -n '\[r(BGPI|BGPD|OBPI|OBPD|LCDC|STAT|SCY|SCX|LYC|DMA|BGP|OBP0|OBP1|WY|WX|VBK|SVBK)\]' --glob '*.asm'
rg -n '\$(ff4[0-9a-bf]|ff5[1-5]|ff6[8-9a-b]|ff70|fe[0-9a-f]{2}|9(?:8|9)[0-9a-f]{2})' --glob '*.{asm,inc}'
rg -n 'ldh?[[:space:]]+\[(c|hli|hld)\]|High|DMA|HDMA|GDMA|OAM' --glob '*.{asm,inc}'
```

These searches seed rows; grep cannot prove closure. Phase 0 must also inspect
the linked symbol/map files and disassemble the built ROM for immediate,
high-memory indirect, pointer-mediated, DMA, wrapper, and interrupt writers,
then reconcile those findings to the source inventory.

## Scene discovery coverage

Scene discovery starts with every row of the
[scope scene-lifecycle table](scope.md#scene-lifecycle-table) and follows every
reachable directed entry, return, abnormal exit, interrupt/reset path, and
nested lifecycle. It additionally searches hard boot, battle entry/return,
blackout and warp, save/load and continue, reset/new game/title, link
failure/disconnect, and error recovery. Each lifecycle and each concrete
directed edge receives a reviewed scene row. Only a proven transition between
full-color map ownership and Yellow ownership is `SCENE_BOUNDARY`; a
Yellow-to-Yellow transition is not.

For each row, source callers and built-ROM control flow must identify the owner
before destination-initialization entry and before the first display write,
all display-writer IDs reached, generation invalidation, whether a concrete
Yellow-to-full-color boundary triggers reconstruction, normal return, reset
behavior, nested exit, and failure exit.

## Visible-map mutation discovery coverage

Mutation discovery follows every path that can alter a presentable map or its
declared dependency:

- initial load, reload, actual Yellow-to-full-color overworld boundary, and reconstruction;
- horizontal and vertical scrolling;
- north, south, east, and west connections;
- third-screen, explicit-row, row/column, and rectangle transfers;
- dialogue, text, transient start/list/yes-no, and field-move overlays;
- ordinary, fully clipped, partially clipped, edge, connection, window,
  alternate-BG, and alternate-map destinations;
- animation, field replacement, moving BG tiles, and map-specific effects;
- LCD-off tilemap/attribute loads and presentation barriers;
- palette changes and tile-data dependencies coupled to visible map changes;
  and
- shadow-OAM batch construction and its hardware-OAM DMA commit when objects
  participate in the visible result.

Every mutation row names the authoritative tile and full-byte attribute source,
destination and clipping behavior, paired resources, visible commit unit,
owner/phase/generation, and linked writer IDs. Discovery follows both source
call graphs and built-ROM control flow; a checklist of routine names is not
closure evidence.

## Yellow integration seeds

These are discovery seeds, not pre-populated inventory rows:

| Yellow source | Review focus |
|---|---|
| `home/start.asm` | CGB-only startup and initialization |
| `home/vcopy.asm` | paired map/window tile and attribute transfers |
| `home/vblank.asm` | owner-routed palette/attribute scheduling and bank safety |
| `home/lcdc.asm` | composition with scanline overrides |
| `home/overworld.asm` | ownership entry/exit and authoritative reconstruction |
| `home/reload_tiles.asm` | reload through paired transfer path |
| `home/text_script.asm` | map-backed dialogue mutations |
| `home/palettes.asm` | owner-dispatched fade/palette requests |
| `home/cgb_palettes.asm` | wrappers dispatched to the active owner |
| `engine/overworld/update_map.asm` | tileset selection before map commit |
| `engine/gfx/sprite_oam.asm` | overworld palette bits after final tile selection |
| `engine/gfx/palettes.asm:SetPal_Overworld` | overworld command replacement boundary |
| `ram/wram.asm` | candidate state ranges subject to the implementing phase's evidence |
| `ram/hram.asm` | owner/bank scratch only if the implementing phase justifies it |
| `layout.link` | measured ROM and WRAM placement |
| `Makefile` | CGB-only header flag |

Calls to `RunPaletteCommand`, `UpdateCGBPal_BGP`, `UpdateCGBPal_OBP0`,
`UpdateCGBPal_OBP1`, and `LoadBGMapAttributes` are seed APIs whose complete
call graphs must be classified by effective scene ownership.

## Tileset and object content seeds

RGB and Yellow share tileset IDs 0–23 by name: `OVERWORLD`, `REDS_HOUSE_1`,
`MART`, `FOREST`, `REDS_HOUSE_2`, `DOJO`, `POKECENTER`, `GYM`, `HOUSE`,
`FOREST_GATE`, `MUSEUM`, `UNDERGROUND`, `GATE`, `SHIP`, `SHIP_PORT`,
`CEMETERY`, `INTERIOR`, `CAVERN`, `LOBBY`, `MANSION`, `LAB`, `CLUB`,
`FACILITY`, and `PLATEAU`. Matching names do not prove matching tile graphics.
ID 24 differs: RGB has `SAFARI`; Yellow has `BEACH_HOUSE`, which requires
native data.

Object discovery includes player, follower Pikachu, NPC picture IDs, item
balls, boulders, cut trees, dust/smoke, healing machine, fishing rod, ledge
shadow, emotion bubbles, map-specific animated objects, and transient
overworld effects. Party icons, battle sprites, title/intro objects, trade
objects, slots, and Surfing Pikachu remain Yellow-owned and are reviewed as
scene-boundary reachability, not imported overworld content.

## Known bank and interrupt constraints

- RGB bank `$2c` conflicts with Yellow Text 7.
- RGB bank `$31` conflicts with Yellow Pikachu cries.
- RGB uses MBC1 assumptions; Yellow uses MBC5.
- Yellow bank `$3b` is a measured starting candidate, not a selected location.
- Yellow VBlank preserves `rVBK` but does not currently preserve `rSVBK`.
- Yellow's LCD interrupt already owns `wLYOverrides` behavior.

These constraints are inputs to phase-local decision evidence and must be
resolved before the affected renderer path becomes reachable.
