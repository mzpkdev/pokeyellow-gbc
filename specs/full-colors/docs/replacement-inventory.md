# Overworld replacement inventory

## Donor modules in scope

| RGB source | Use |
|---|---|
| `color/init.asm` | CGB double speed and renderer WRAM initialization |
| `color/wram.asm` | model for bank-2 state; convert to named WRAMX |
| `color/loadpalettes.asm` | tileset palette sets, assignments, roofs, overrides |
| `color/refreshmaps.asm` | paired map/window tile and attribute transfers |
| `color/vblank.asm` | overworld palette transformation and scheduling concepts |
| `color/super_palettes.asm` | loading eight-byte RGB555 palettes |
| overworld portion of `color/color.asm` | `SetPal_Overworld` scene initialization |
| overworld portion of `color/sprites.asm` | NPC/player/object palettes |
| `color/boulder.asm` | overworld moving-object behavior where applicable |
| `color/ssanne.asm` | Vermilion Dock/ship overworld exception |
| `color/data/map_*` | palette sets and tile assignments |
| `color/data/roofpalettes.asm` | town-specific roof colors |
| `color/tilesets/*.asm` | candidate tile assignment data |

Every donor routine must be adapted to Yellow's MBC5 banks, labels, interrupt
model, and `BEACH_HOUSE` tileset.

## Donor modules excluded

Do not port runtime behavior from:

- battle palette commands in `color/color.asm`;
- non-overworld portions of `color/sprites.asm`;
- `color/animations.asm`;
- HP/EXP bar color modules;
- trade, cable club, slots, status, and Oak intro color modules;
- ghost Marowak and HUD Poké Ball modules; or
- RGB's DMG fallback bank binary.

Palette values may be referenced artistically, but these systems stay on
Yellow's renderer.

## Yellow integration points

| Yellow source | Required overworld change |
|---|---|
| `home/start.asm` | CGB-only startup and initialization |
| `home/vcopy.asm` | paired map/window tile and attribute transfers |
| `home/vblank.asm` | owner-routed palette/attribute scheduling and bank safety |
| `home/lcdc.asm` | compose renderer preparation with scanline overrides |
| `home/overworld.asm` | ownership entry/exit and map reconstruction |
| `home/reload_tiles.asm` | reload through paired transfer path |
| `home/text_script.asm` | map-backed dialogue attributes |
| `home/palettes.asm` | owner-dispatched fade/palette requests |
| `home/cgb_palettes.asm` | wrappers dispatch to active renderer |
| `engine/overworld/update_map.asm` | select tileset palettes before map commit |
| `engine/gfx/sprite_oam.asm` | insert overworld palette bits after tile selection |
| `engine/gfx/palettes.asm:SetPal_Overworld` | replace only overworld command behavior |
| `ram/wram.asm` | named WRAMX bank-2 state |
| `ram/hram.asm` | owner/bank scratch if justified |
| `layout.link` | renderer bank `$3b` and WRAMX layout |
| `Makefile` | CGB-only header flag |

The existing Yellow implementations for excluded scenes remain.

## Ownership-boundary call-site audit

Calls to these APIs must be classified by scene:

```text
RunPaletteCommand
UpdateCGBPal_BGP
UpdateCGBPal_OBP0
UpdateCGBPal_OBP1
LoadBGMapAttributes
```

Classification:

1. **Overworld or map-backed overlay:** route to the new renderer or replace.
2. **Standalone scene:** hand off first, then retain Yellow behavior.
3. **Return to map:** invoke complete full-color reconstruction.

Direct hardware writer searches:

```sh
rg -n "\[r(BGPI|BGPD|OBPI|OBPD)\]" --glob '*.asm'
rg -n "\[rVBK\]" --glob '*.asm'
rg -n "\[rSVBK\]" --glob '*.asm'
```

The goal is not to eliminate Yellow's non-overworld writers. The goal is to
prove they cannot execute while the full-color overworld owner is active.

## Tile transfer audit

Review every path that can alter the visible map:

- `RedrawRowOrColumn`;
- `AutoBgMapTransfer`;
- `TransferBgRows`;
- `VBlankCopyBgMap`;
- map load with LCD disabled;
- connected-map streaming;
- tile reload;
- dialogue and text windows;
- start-menu/list/yes-no overlays;
- moving background tiles;
- field effects that replace tiles; and
- alternate BG map destination changes.

Each must use an authoritative paired transfer or explicitly hand off to
Yellow before drawing a standalone scene.

## Tilesets

RGB and Yellow share IDs 0-23:

`OVERWORLD`, `REDS_HOUSE_1`, `MART`, `FOREST`, `REDS_HOUSE_2`, `DOJO`,
`POKECENTER`, `GYM`, `HOUSE`, `FOREST_GATE`, `MUSEUM`, `UNDERGROUND`, `GATE`,
`SHIP`, `SHIP_PORT`, `CEMETERY`, `INTERIOR`, `CAVERN`, `LOBBY`, `MANSION`,
`LAB`, `CLUB`, `FACILITY`, and `PLATEAU`.

ID 24 differs:

- RGB: `SAFARI`
- Yellow: `BEACH_HOUSE`

Matching names do not guarantee identical tile graphics. Verify generated tile
IDs before adopting RGB assignments.

## Overworld object audit

Assign or deliberately preserve palettes for:

- player;
- follower Pikachu;
- NPC picture IDs;
- item balls;
- boulders;
- cut trees;
- dust/smoke;
- healing machine;
- fishing rod;
- ledge shadow;
- emotion bubbles;
- map-specific animated objects; and
- transient overworld effects.

Exclude party icons, battle sprites, title/intro objects, trade objects, slots,
and Surfing Pikachu.

## Bank conflicts

- RGB bank `$2c` conflicts with Yellow Text 7.
- RGB bank `$31` conflicts with Yellow Pikachu cries.
- RGB uses MBC1 assumptions; Yellow uses MBC5.
- Yellow bank `$3b` is empty.
- Yellow VBlank preserves `rVBK` but not currently `rSVBK`.
- Yellow LCD interrupt is already active.

These constraints must be solved before visual content is ported.
