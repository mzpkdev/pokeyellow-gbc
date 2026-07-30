# Target architecture

## Renderer pipeline

```text
scene/palette command
        |
        +--> base BG palettes (8 × 4 RGB555)
        +--> base OBJ palettes (8 × 4 RGB555)
        +--> attribute mode and source
        |      +--> tile ID lookup (maps)
        |      `--> 20×18 static grid (screens)
        `--> dirty flags

BGP / OBP0 / OBP1 -------------------------+
                                             |
pre-VBlank preparation                      v
        +--> transformed BG buffer (64 bytes)
        +--> transformed OBJ buffer (64 bytes)
        `--> prepared window attributes

safe transfer phase
        +--> VRAM bank 1 attributes
        +--> BGPI/BGPD
        `--> OBPI/OBPD
```

Base palettes are never destructively faded. The DMG shade registers select
which of the four RGB555 base colors appears for each 2bpp pixel value.

## Ownership boundaries

| Resource | Owner | Consumers |
|---|---|---|
| Base BG palettes | palette command layer | transform stage |
| Base OBJ palettes | palette command/object layer | transform stage |
| Transformed palette buffers | pre-VBlank stage | palette transfer |
| Tile attribute lookup | active tileset | map and window transfer |
| Static attribute grid | active special screen | window transfer |
| BG VRAM bank 1 | transfer layer | PPU |
| OAM palette bits | OAM construction/object colorizer | PPU |
| Dirty/deadline state | scheduler | preparation and VBlank |

No consumer may mutate its producer's state.

## Memory model

Use a named `WRAMX`, bank 2 section instead of anonymous absolute `EQU`
addresses. Preserve RGB's page-alignment properties where indexed addressing
depends on the high byte remaining constant.

Proposed layout:

| Data | Size | Alignment/reason |
|---|---:|---|
| base BG palettes | `$40` | eight palettes |
| base OBJ palettes | `$40` | eight palettes |
| last BGP/OBP values | 3 | change detection |
| tile/static attribute storage | at least `$180` | 256-byte tile lookup or 360-byte screen grid |
| OBJ tile lookup | `$100` | low-byte tile indexing |
| prepared window attributes | `$c0` | six 32-byte rows, DMA-friendly |
| transformed BG palettes | `$40` | one complete hardware bank |
| transformed OBJ palettes | `$40` | one complete hardware bank |
| flags and scene state | implementation-defined | dirty, mode, deadlines |

The original RGB layout overlaps no Yellow data only because it switches
`rSVBK` to bank 2. Yellow's normal `$d000-$dfff` labels remain in WRAM bank 1.

Required rules:

- renderer calls save the incoming `rSVBK`;
- interrupts save `rSVBK` before touching renderer state;
- code reading Yellow WRAM at `$d000-$dfff` explicitly returns to bank 1;
- bank 2 must never remain selected on return to legacy code; and
- soft reset clears renderer state without clearing Yellow's bank-1 game state.

## ROM placement

The donor's placement cannot be retained:

| Donor location | Yellow conflict |
|---|---|
| bank `$2c` | Text 7 |
| bank `$31` | Pikachu cries 6 |
| bank `$1c` extension | must be measured; not assumed free |

Yellow bank `$3b` is empty in `layout.link` and is the preferred first renderer
bank. The implementation must use normal sections and link assertions rather
than hard-coded bank register writes copied from RGB.

## Attribute modes

### Tile lookup mode

The attribute byte is selected by tile ID:

```text
attribute = active_tile_attributes[tile_id]
```

This mode is used for maps. The full 8-bit attribute is retained so priority,
tile bank, and flips are not accidentally masked away.

### Static screen mode

The attribute is selected by screen coordinate:

```text
attribute = active_screen_attributes[y * 20 + x]
```

This mode is used when identical tile IDs need different colors in different
screen regions, including battles, status, Pokédex, title, and minigames.

### Window transfer

Yellow updates the window/tilemap in thirds. Attribute preparation must use the
same portion and destination as the tile transfer. Changing between `$9800` and
`$9c00` invalidates any prepared static map portion.

## Timing model

RGB prepares palette data with an LCD interrupt before VBlank and transfers it
during VBlank. Yellow's LCD interrupt is already used for `wLYOverrides`.
Therefore the port must implement a composed scheduler:

1. Preserve the existing scanline register override behavior.
2. Detect the renderer's preparation scanline without suppressing overrides.
3. Prepare only when the previous portion has been consumed.
4. During VBlank, perform only operations whose deadline budget fits.
5. Leave dirty flags set when work is deferred.

The implementation must measure cycles after Yellow's audio, serial, OAM, and
map-transfer ordering is finalized. RGB's scanline constants are starting
points, not automatically valid Yellow constants.

## Transitional API behavior

During migration:

- `RunPaletteCommand` selects complete scene state.
- `UpdateCGBPal_BGP` marks/rebuilds BG output after `rBGP` changes.
- `UpdateCGBPal_OBP0` marks/rebuilds OBJ output affected by `rOBP0`.
- `UpdateCGBPal_OBP1` marks/rebuilds OBJ output affected by `rOBP1`.

These wrappers must not synchronously transfer palette colors one pair at a
time. They request renderer work and, only where a caller contract truly
requires synchronous presentation, wait for completion through a renderer-owned
barrier. Their signatures are not compatibility contracts and the wrappers
must be removed when direct scene/renderer requests replace their callers.

## OAM model

Overworld OAM is colored by picture identity during construction. Non-overworld
OAM is colored by tile ID or scene-specific assignment.

Palette insertion must preserve:

- bit 7: BG/OBJ priority;
- bit 6: Y flip;
- bit 5: X flip;
- bit 3: OBJ tile VRAM bank;
- bits 0-2: CGB OBJ palette.

Yellow's current `OAM_HIGH_PALS` conversion is insufficient because it maps only
the old OBP0/OBP1 distinction. The replacement selects all three palette bits.

Follower Pikachu is a first-class exception: tile calculation using
`hPikachuSpriteVRAMOffset` happens before palette insertion and must remain
unchanged.

## Failure recovery

If a deadline is missed:

- do not write palette RAM during an unsafe LCD mode;
- do not partially switch an attribute map;
- retain dirty state;
- retry on the next safe frame; and
- keep the previous complete palette/attribute state visible.

Atomic visual consistency is preferred over updating every requested change in
the same frame.
