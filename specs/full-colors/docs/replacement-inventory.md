# Replacement inventory

This inventory maps the donor architecture to Yellow integration points. It is
an implementation checklist, not permission to copy files without adaptation.

## Core donor modules

| RGB source | Responsibility | Yellow action |
|---|---|---|
| `color/init.asm` | double speed and WRAM clearing | rewrite for Yellow startup and soft reset |
| `color/wram.asm` | bank-2 state | convert absolute addresses to named WRAMX bank-2 sections |
| `color/super_palettes.asm` | eight-byte palette loading | port behind Yellow palette IDs |
| `color/vblank.asm` | transforms and buffered transfer | compose with Yellow LCD/VBlank handlers |
| `color/refreshmaps.asm` | paired tile/attribute transfers | port to Yellow's transfer primitives |
| `color/loadpalettes.asm` | tileset sets and assignments | add `BEACH_HOUSE`; audit tile IDs |
| `color/color.asm` | scene palette commands | rewrite for Yellow layouts and commands |
| `color/sprites.asm` | overworld/non-overworld OAM colors | adapt to Yellow OAM and Pikachu |
| `color/animations.asm` | animation-palette loading | integrate with Yellow animation loader |
| `color/update_hp_bar.asm` | dynamic HP palette regions | adapt to Yellow battle/status layouts |
| `color/exp_bar.asm` | dynamic EXP colors | verify Yellow HUD geometry |
| `color/trade.asm` | trade attributes/OBJ colors | adapt to Yellow trade flow |
| `color/cable_club.asm` | link-room screen colors | adapt to MBC5 and Yellow link code |
| `color/ssanne.asm` | map-specific water/ship fix | verify Yellow Vermilion Dock sequence |
| `color/boulder.asm` | moving boulder object colors | merge with Yellow boulder/cut OAM |
| `color/ghost_marowak_anim.asm` | BG picture to OBJ palette | adapt Yellow ghost routine |
| `color/oak_intro.asm` | intro picture colors | replace with Yellow-native sequence |
| `color/dmg.asm` | non-CGB error | reuse concept, not ROM-bank binary |

## Yellow renderer components to replace

| Yellow source | Current responsibility | Final state |
|---|---|---|
| `engine/gfx/palettes.asm` | command dispatch, four CGB palettes, SGB translation, hardware writes | retain command-facing entry points; replace internals |
| `engine/gfx/bg_map_attributes.asm` | canned attribute DMA | remove after static-map replacement |
| `data/cgb/bg_map_attributes.asm` | canned screen attributes | remove after all commands migrate |
| `home/cgb_palettes.asm` | CGB update wrappers | convert to renderer requests, then simplify |
| `home/palettes.asm` | fades and command wrapper | preserve public behavior; route through buffers |
| `home/fade.asm` | DMG register fade sequences | preserve; new core observes register changes |
| `ram/wram.asm` CGB section | four-palette pointers/scratch | remove after bank-2 state is live |
| `ram/hram.asm:hOnCGB` | runtime compatibility branch | remove or make constant after CGB-only conversion |

## Tile and attribute transfer integration

| Yellow source | Required change |
|---|---|
| `home/vcopy.asm` | pair attributes with row, column, thirds, and explicit row transfers |
| `home/vblank.asm` | serialize attribute and palette transfers; preserve all banks |
| `home/overworld.asm` | select palettes before initial tile/attribute commit |
| `home/reload_tiles.asm` | reload attributes through the same transfer primitive |
| `home/text_script.asm` | use static/tile-mode window attributes without restoration hacks |
| `engine/overworld/update_map.asm` | load tileset palette set before exposing a map |
| map connection/streaming code | prove correct wrapping at all four edges |
| `engine/movie/intro_yellow.asm` | replace direct `rVBK` writes with scene-owned attributes |

All searches for direct `rVBK` writes must be reviewed. A direct write is not
automatically wrong, but its ownership and bank restoration must be explicit.

## Palette command coverage

Yellow has 16 ordinary command slots plus `$fc` and `$ff`. RGB lacks Yellow's
Surfing Pikachu commands and adds commands Yellow does not currently expose.

| Yellow scene | Donor reuse | Yellow work |
|---|---|---|
| battle | high | verify Yellow HUD and transition geometry |
| town map | medium | preserve Yellow cursor and map data |
| status | medium | Yellow status layout and Pikachu |
| Pokédex | medium | Yellow layout and animated Pikachu cases |
| slots | medium | preserve Yellow wheel/OBJ effects |
| title | low | Yellow-specific title animation |
| Nidorino/intro | low | Yellow uses an extended unique intro |
| generic | high | define text-safe baseline |
| overworld | high | add Beach House and Yellow map exceptions |
| party | medium | Yellow party icons and HP rows |
| whole-screen Pokémon | high | evolution/trade/Hall of Fame |
| Game Freak | medium | verify Yellow sparkle OAM |
| trainer card | medium | Yellow portrait/badge layout |
| Surfing Pikachu title | none | implement natively |
| Surfing Pikachu game | none | implement natively |

## Existing call-site audit

At specification time, Yellow contains palette calls across these categories:

- 28 assembly files call `RunPaletteCommand`;
- 18 files call `UpdateCGBPal_BGP`;
- 13 files call `UpdateCGBPal_OBP0`;
- 17 files call `UpdateCGBPal_OBP1`;
- three files call `LoadBGMapAttributes`; and
- direct palette hardware writes are concentrated in
  `engine/gfx/palettes.asm`.

Before removing an adapter, regenerate these searches:

```sh
rg -n "RunPaletteCommand|UpdateCGBPal_BGP|UpdateCGBPal_OBP0|UpdateCGBPal_OBP1" \
  --glob '*.asm'
rg -n "\[r(BGPI|BGPD|OBPI|OBPD)\]" --glob '*.asm'
rg -n "\[rVBK\]" --glob '*.asm'
```

Each result must be assigned to an owner in the implementation PR.

## Overworld tilesets

RGB and Yellow share IDs 0-23:

`OVERWORLD`, `REDS_HOUSE_1`, `MART`, `FOREST`, `REDS_HOUSE_2`, `DOJO`,
`POKECENTER`, `GYM`, `HOUSE`, `FOREST_GATE`, `MUSEUM`, `UNDERGROUND`, `GATE`,
`SHIP`, `SHIP_PORT`, `CEMETERY`, `INTERIOR`, `CAVERN`, `LOBBY`, `MANSION`,
`LAB`, `CLUB`, `FACILITY`, and `PLATEAU`.

ID 24 differs:

- RGB: `SAFARI`
- Yellow: `BEACH_HOUSE`

Even for IDs 0-23, matching names do not prove matching tile graphics. Compare
the generated `.2bpp` tiles and in-game semantics before accepting donor
assignments. Add an assertion that every table has `NUM_TILESETS` entries and
every assignment has exactly `$60` bytes.

## Yellow-exclusive object and animation audit

The following must receive explicit palette ownership:

- follower Pikachu base and emotion sprites;
- Pikachu front-picture animation;
- Pikachu entrance animation;
- splash Pikachu;
- Yellow intro Pikachu and character layers;
- Surfing Pikachu sprite animation;
- Beach House NPCs and objects;
- healing machine;
- cut tree and boulder dust;
- emotion bubbles;
- fishing rod and ledge shadow;
- trade machine and cable;
- printer presentation; and
- credits objects.

## Bank and hardware conflicts

- Yellow is MBC5; donor MBC1 register names and assumptions must not survive.
- Yellow bank `$3b` is empty and preferred for the first implementation.
- Yellow LCD interrupt already runs `LCDC` scanline overrides.
- Yellow VBlank saves/restores `rVBK` but not `rSVBK`.
- Yellow does not currently enter double-speed mode.
- Yellow currently builds a CGB-compatible, not CGB-only, header.

These are foundation tasks, not cleanup tasks.
