# Overworld renderer architecture

## Ownership state machine

```text
                         standalone screen request
 FULL_COLOR_OVERWORLD  ------------------------------>  YELLOW
          ^                                                 |
          |                                                 |
          +---------- complete map reconstruction ----------+
```

There is no state in which both renderers may write palette RAM or BG/window
attributes.

`FULL_COLOR_OVERWORLD` includes map-backed dialogue and transient overlays.
`YELLOW` includes every standalone screen that replaces the map.

## Full-color overworld pipeline

```text
map/tileset selection
        |
        +--> 8 base BG palettes
        +--> 8 base OBJ palettes
        +--> 256-byte tile attribute lookup
        `--> dirty state

BGP / OBP0 / OBP1 -------------------------+
                                             |
safe preparation                            v
        +--> transformed BG buffer
        +--> transformed OBJ buffer
        `--> prepared overlay attributes

paired transfer
        +--> tile IDs in VRAM bank 0
        +--> attributes in VRAM bank 1
        +--> BG palette RAM
        `--> OBJ palette RAM
```

Yellow's renderer is not changed into an RGB renderer. It is paused while this
pipeline owns the scene and resumed only after a handoff.

## Resource ownership

| Resource | Full-color overworld owner | Yellow owner |
|---|---|---|
| BG palette RAM | all slots while map active | all slots in standalone scenes |
| OBJ palette RAM | all slots while map active | all slots in standalone scenes |
| BG/window attributes | map and map-backed overlays | standalone screens |
| Overworld OAM palette bits | RGB-style picture assignment | never |
| Non-overworld OAM palette bits | never | existing Yellow logic |
| Palette dirty/deadline state | overworld scheduler | existing Yellow calls |

Wrapper functions that can be called in either scene must inspect the owner and
dispatch to only that owner.

## Map-backed overlays versus standalone screens

The key test is restoration behavior.

If closing a window should reveal the existing map without a complete map
entry, it remains a full-color overworld operation. The renderer generates
attributes for both the terrain and the overlay.

If a screen has an independent lifecycle and rebuilds the display, ownership
passes to Yellow. The old map is considered discarded. Returning reconstructs
the map from map state and the active tileset table.

This prevents a "save VRAM, let Yellow overwrite it, patch it back" design.

## Memory model

Use a named WRAMX bank-2 section. Suggested state:

| Data | Size | Reason |
|---|---:|---|
| base BG palettes | `$40` | eight four-color palettes |
| base OBJ palettes | `$40` | eight four-color palettes |
| transformed BG buffer | `$40` | complete hardware payload |
| transformed OBJ buffer | `$40` | complete hardware payload |
| tile attributes | `$100` | direct low-byte tile indexing |
| overlay attribute buffer | implementation-defined | map-backed windows |
| last BGP/OBP values | 3 | change detection |
| owner/mode/dirty state | implementation-defined | scheduling and handoff |

Requirements:

- callers save incoming `rSVBK`;
- interrupts save `rSVBK`;
- Yellow WRAM at `$d000-$dfff` is accessed only with bank 1 selected;
- renderer calls restore the incoming bank; and
- soft reset clears pending work and selects a safe owner before reboot.

## ROM placement

The donor's locations conflict with Yellow:

| RGB location | Yellow use |
|---|---|
| bank `$2c` | Text 7 |
| bank `$31` | Pikachu cries 6 |
| bank `$1c` extension | not assumed free |

Start in Yellow's empty bank `$3b`. Use Yellow's MBC5 `rROMB` and far-call
conventions; do not carry over MBC1 register writes.

## Tile and attribute transfers

The canonical primitive takes:

- tile source;
- attribute source or tile lookup;
- VRAM destination;
- dimensions/stride; and
- ownership generation or token.

It commits a matching attribute for every tile. If tile and attribute writes
cannot occur in the same LCD interval, they are serialized as one renderer job
that cannot be interleaved with another owner.

Required consumers:

- initial map load;
- row and column streaming;
- map connections;
- third-screen window transfer;
- explicit row transfer;
- tile reload;
- dialogue/text;
- transient menus; and
- animated/replaced tiles.

## Palette transformations

Base RGB555 palettes are retained. The current `BGP`, `OBP0`, and `OBP1`
registers select which base color appears for each 2bpp index, preserving
Yellow's existing fade vocabulary.

During overworld ownership:

- BGP changes dirty the BG transformed buffer;
- OBP changes dirty the OBJ transformed buffer;
- palette wrappers route to the new scheduler; and
- safe VBlank work uploads complete requested payloads.

During Yellow ownership, the new dirty state is ignored or cleared and wrappers
use Yellow's existing behavior.

## LCD and VBlank composition

Yellow already uses the LCD interrupt for per-scanline `wLYOverrides`.
The renderer must compose with it, not replace it.

Possible implementation:

1. Existing scanline override behavior executes first.
2. A renderer LYC condition runs preparation only under overworld ownership.
3. VBlank performs paired attribute work and dirty palette uploads only for the
   active owner.
4. Work that cannot finish safely remains pending.

Exact ordering and scanline values require cycle measurements in Yellow.

## Overworld OAM

Palette bits are inserted after Yellow calculates the final tile ID, including
`hPikachuSpriteVRAMOffset`.

The colorizer must preserve:

- priority;
- X/Y flips;
- tile VRAM bank;
- control/end flags; and
- all tile selection behavior.

Only overworld OAM uses this path. Yellow's non-overworld OAM generation remains
untouched.

## Handoff safety

Every ownership transition has a generation counter or equivalent barrier.
Jobs created by the previous owner must not execute after the switch.

On leaving the map:

- block new map jobs;
- finish or cancel queued work;
- clear new-renderer dirty flags;
- switch owner; and
- let Yellow initialize the destination from scratch.

On return, treat VRAM attributes and palette RAM as unknown and rebuild all
overworld state.
