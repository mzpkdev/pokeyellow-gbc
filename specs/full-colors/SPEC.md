# Full-color renderer replacement

Status: proposed

Target: `pokeyellow`

Donor architecture: `pokemon-rgb`
Scope: complete replacement of Yellow's CGB palette and attribute renderer

## 1. Purpose

Replace Pokémon Yellow's existing four-palette, SGB-packet-derived CGB renderer
with one authoritative renderer based on the `pokemon-rgb` architecture.

The replacement must provide:

- eight simultaneous background palettes and eight object palettes;
- per-tile overworld palette selection;
- coordinate-based palette maps for battles, menus, and special screens;
- per-character overworld object palettes;
- per-tile and per-move battle-animation object palettes;
- species- and trainer-specific picture palettes;
- buffered, synchronized palette updates;
- preservation of the original `BGP`, `OBP0`, and `OBP1` fade semantics; and
- complete coverage of Yellow-exclusive screens and Pikachu systems.

This is an engine transplant. It is not an optional overworld overlay and must
not depend on restoring attributes after Yellow's renderer overwrites them.

## 2. Background

Yellow already has a CGB compatibility renderer:

- `NUM_ACTIVE_PALS` is four;
- SGB palette packets select four base palettes;
- those base palettes are converted through the current DMG shade registers;
- canned attribute maps are copied into VRAM bank 1 for special screens; and
- most palette changes synchronously wait for accessible VRAM and write
  directly to CGB palette registers.

That design is coherent for Yellow's original whole-screen tinting but cannot
be the co-owner of a full-color attribute map. A previous hybrid experiment
kept the existing renderer and added per-tile overworld writes around it. That
created two owners for VRAM bank 1 and required restoration hooks after map
loads, scrolling, dialogue, menus, and palette commands. The replacement
specified here eliminates that ownership conflict.

See:

- [Architecture](docs/architecture.md)
- [Replacement inventory](docs/replacement-inventory.md)
- [Failure analysis](docs/failed-hybrid-analysis.md)
- [Migration plan](docs/migration-plan.md)
- [Verification plan](docs/verification-plan.md)

## 3. Architectural decision

### 3.1 Single renderer

The new renderer is the sole authority for:

1. base BG and OBJ RGB555 palette data;
2. transformed palettes after applying DMG shade registers;
3. VRAM bank 1 BG/window attributes;
4. palette bits in all OAM entries; and
5. dirty state and timing of palette transfers.

No legacy routine may independently copy a canned attribute map or write
`rBGPI`, `rBGPD`, `rOBPI`, or `rOBPD` after the replacement is complete.
Exceptional direct writes must be documented, timing-safe, and owned by the
new renderer.

### 3.2 CGB-only target

The completed renderer is CGB-only, matching `pokemon-rgb`:

- change the cartridge flag from CGB-compatible (`rgbfix -c`) to CGB-only
  (`rgbfix -C`);
- reject non-CGB startup with a deterministic error path;
- enter CGB double-speed mode during initialization; and
- use CGB WRAM banking and VRAM attributes unconditionally after startup.

DMG and SGB compatibility are not part of this replacement. Retaining the old
renderer as a fallback would preserve the dual-renderer ownership problem and
would no longer constitute a complete swap. A future compatibility project may
add a separately designed fallback after the new renderer is stable.

### 3.3 No backward-compatibility requirement

The replacement does not need to preserve:

- DMG or SGB execution;
- the old renderer as a runtime fallback;
- old palette implementation APIs or calling conventions;
- old CGB visual output;
- ROM binary layout or matching ROM hashes;
- renderer-specific RAM layout;
- save compatibility when implementation work requires a save-format change;
  or
- compatibility with the failed full-color-overworld implementation.

Gameplay behavior unrelated to rendering remains in scope for regression
protection, but backward compatibility must not constrain renderer ownership or
architecture.

### 3.4 Transitional adapters

Existing call sites may continue to invoke these public APIs while migration is
in progress:

- `RunPaletteCommand`
- `UpdateCGBPal_BGP`
- `UpdateCGBPal_OBP0`
- `UpdateCGBPal_OBP1`

Their implementations may temporarily become adapters to the new renderer.
Adapters exist only to split implementation into reviewable stages; preserving
their signatures is not a final requirement. Every transitional adapter must
have a removal stage and must be deleted when its callers migrate.

## 4. Required behavior

### R1. Startup and memory

- Detect CGB hardware before any banked-WRAM access.
- Enter double-speed mode exactly once per hard boot.
- Reserve a named WRAMX section in bank 2 for all renderer state.
- Clear renderer-owned WRAM on hard boot and soft reset.
- Preserve and restore `rSVBK` across every interrupt and every renderer entry
  point that can be called with an unknown WRAM bank.
- Preserve and restore `rVBK` across interrupts and public renderer calls.
- Keep the stack in the default WRAM bank; do not place renderer state close to
  a banked stack alias.

The proposed state layout is defined in
[architecture.md](docs/architecture.md#memory-model).

### R2. ROM banking

- Do not use RGB's bank `$2c`; Yellow stores Text 7 there.
- Do not import RGB's bank `$31` binary; Yellow stores Pikachu cries there.
- Do not assume RGB's bank `$1c` extension has compatible free space.
- Place the initial renderer in Yellow's empty bank `$3b`.
- Spill into explicitly measured free space or expand the ROM only after the
  map file proves bank `$3b` insufficient.
- Convert MBC1-specific donor code to Yellow's MBC5 banking API (`rROMB`,
  `hLoadedROMBank`, and `Bankswitch`/far-call conventions).
- Interrupt-time far calls must restore the interrupted ROM bank even if the
  interrupt occurs inside another far-call wrapper.

### R3. Palette model

- Store eight four-color RGB555 base BG palettes.
- Store eight four-color RGB555 base OBJ palettes.
- Maintain separate transformed 64-byte BG and OBJ buffers.
- Treat `BGP`, `OBP0`, and `OBP1` as four-entry shade-remapping tables.
- Rebuild transformed buffers when a base palette changes, a DMG shade register
  changes, or a force-update flag is set.
- Preserve the RGB convention that OBJ palettes 0-3 use `OBP0` semantics and,
  when requested by the active scene, OBJ palettes 4-7 use `OBP1` semantics.
- Support forced all-white and all-black states without losing base palettes.
- Palette commands must alter base state and dirty flags, never race direct
  hardware writes against VBlank.

### R4. Background and window attributes

Support two explicit attribute modes:

1. **Tile lookup mode:** each tile ID indexes a 256-byte attribute table.
2. **Static screen mode:** each visible coordinate reads a 20×18 attribute
   grid.

The active mode must be set by the palette command that owns the screen.

Every path that writes tile IDs to a BG or window tilemap must also write the
matching attribute bytes:

- initial map load while LCD is disabled;
- streamed horizontal and vertical map redraws;
- connected-map edge redraws;
- automatic one-third window/tilemap transfers;
- explicit `TransferBgRows` operations;
- text and dialogue windows;
- menu open, close, and restoration;
- full tile reloads;
- battle tilemap setup and transitions;
- title/intro tilemaps;
- trade, slots, printer, and minigame tilemaps; and
- alternate BG map destinations (`$9800` and `$9c00`).

Tile attribute values must preserve:

- palette index in bits 0-2;
- VRAM tile bank in bit 3 when deliberately used;
- horizontal/vertical flip bits when deliberately used; and
- BG priority in bit 7.

The implementation must not add scattered post-hoc restoration calls. Tile and
attribute writes belong in the same transfer primitive or in a paired,
serialized transfer owned by the renderer.

### R5. Overworld palette data

- Define eight-palette sets for all 25 Yellow tilesets.
- Port RGB assignments for the 24 structurally matching tilesets only after
  confirming Yellow's tile graphics and IDs.
- Create a native assignment for Yellow's `BEACH_HOUSE`; RGB's slot 24 is
  `SAFARI` and is not compatible.
- Assign tiles `$00-$5f` explicitly and default `$60-$ff` to the text palette
  unless a screen declares otherwise.
- Handle town-specific roof colors without duplicating the overworld tileset.
- Document and test every map-specific tile override.
- Treat animation tile replacement as a palette invariant: replacement frames
  must keep compatible pixel indices or update their attributes/palettes.

### R6. Static screens and palette commands

Implement a Yellow-native command for every existing command ID:

| ID | Command | Required treatment |
|---:|---|---|
| `$00` | battle black | both palette banks black; attributes remain valid |
| `$01` | battle | player/enemy pictures, HP bars, EXP bar, textbox |
| `$02` | town map | map regions, cursor/object palettes |
| `$03` | status | species picture, HP bar, EXP bar, text |
| `$04` | Pokédex | species picture and data/text regions |
| `$05` | slots | static BG grid and object tile assignments |
| `$06` | title | Yellow title layout and animated objects |
| `$07` | Nidorino intro | Yellow intro object/BG ownership |
| `$08` | generic | text-safe neutral screen |
| `$09` | overworld | tile lookup mode and overworld OBJ palettes |
| `$0a` | party | per-row HP bars and party icon palettes |
| `$0b` | whole-screen Pokémon | evolution, trade, Hall of Fame |
| `$0c` | Game Freak intro | logo and sparkle palettes |
| `$0d` | trainer card | portrait, badge, border, and text regions |
| `$0e` | Surfing Pikachu title | Yellow-native static map and OBJ palettes |
| `$0f` | Surfing Pikachu minigame | Yellow-native dynamic ownership |
| `$fc` | party HP update | update one row without resetting the screen |
| `$ff` | default | dispatch to the recorded scene command |

Additional internal commands may be introduced for naming, Oak speech,
post-black battle restoration, and other scenes where RGB separates states.
Existing numeric IDs must not silently change without updating every caller.

### R7. Pokémon and trainer pictures

- Resolve internal species IDs through Pokédex order before palette lookup.
- Preserve Yellow's special Pikachu palettes and front-picture animation.
- Provide correct player, rival, trainer-class, Old Man, ghost, fossil, and
  substitute palettes.
- Retain the active player's palette across Transform.
- Define whether front and back pictures share a palette or use separate lookup
  functions.
- Ensure palette selection remains correct in link battles where local trainer
  state is unreliable.

### R8. Overworld objects

- Insert the palette index into each OAM attribute during OAM construction,
  preserving priority, flip, tile-bank, and end-of-data flags.
- Assign palettes by overworld picture ID with documented deterministic
  fallback behavior.
- Preserve Yellow's `hPikachuSpriteVRAMOffset` calculation and follower
  animation layout.
- Give the player, follower Pikachu, NPCs, item balls, boulders, cut trees,
  healing machine, dust, fishing rod, ledge shadow, and emotion bubbles
  deliberate assignments.
- Reload the eight OBJ base palettes when the active environment changes.
- OAM construction must remain within its frame budget and must not introduce
  visible sprite wobble.

### R9. Non-overworld objects and animations

- Maintain a 256-byte tile-ID-to-OBJ-palette assignment table.
- Support fixed palette IDs, type-derived attack colors, "preserve current
  palette", and explicitly documented special selectors.
- Port or regenerate palette maps for both battle-animation tilesets.
- Handle Poké Ball types, status effects, Leech Seed, trade cable, ghost
  Marowak, HUD Poké Balls, party icons, intro sparkles, slots, and healing
  animations.
- Audit every Yellow routine that currently calls `UpdateCGBPal_OBP0` or
  `UpdateCGBPal_OBP1`; classify it as base-palette mutation, fade remap, scene
  transition, or obsolete direct refresh.

### R10. Yellow-exclusive systems

The following require native implementations rather than RGB copies:

- Yellow splash and title sequences;
- the full `intro_yellow` animation;
- Oak speech Pikachu animation;
- Pikachu front-picture and emotion animations;
- follower Pikachu OAM, including temporary disappearance and respawn;
- Pikachu's Beach title;
- Surfing Pikachu gameplay, HUD, result screens, and transitions;
- Beach House tileset;
- Yellow credits palette changes;
- Yellow-specific healing, cut, dust, and companion emotion objects;
- printer behavior; and
- link/trade presentation.

Each system must declare who owns BG attributes, OBJ attributes, base palettes,
and fade state for every phase of its animation.

### R11. Interrupt and transfer scheduling

- Compose palette preparation with Yellow's existing LCD interrupt; do not
  replace the scanline-override behavior in `home/lcdc.asm`.
- A dedicated LYC event may prepare palette buffers before VBlank only if it
  coexists with active per-scanline effects.
- If the LCD handler cannot safely host both responsibilities, preparation may
  run in the main loop, but the resulting transfer protocol must retain one
  owner and deterministic deadlines.
- VBlank must serialize, in a documented order:
  1. tilemap/attribute streaming;
  2. OAM DMA preparation;
  3. BG palette transfer;
  4. OBJ palette transfer; and
  5. restoration of ROM, WRAM, and VRAM banks.
- Palette uploads must check that sufficient VBlank time remains.
- An attribute row/column redraw and full palette upload must not overrun the
  frame or expose a one-frame white/incorrect palette.
- The renderer must tolerate a missed deadline by leaving dirty state pending
  for the next safe frame.

### R12. Removal of the old renderer

After all acceptance gates pass:

- remove `NUM_ACTIVE_PALS = 4` assumptions;
- remove `wCGBBasePalPointers`, `wCGBPal`, and the old four-palette buffer;
- remove `InitCGBPalettes`, `DMGPalToCGBPal`, and direct transfer routines that
  have been superseded;
- remove `TranslatePalPacketToBGMapAttributes`;
- remove canned CGB BG attribute data and its loader when no longer referenced;
- remove `hOnCGB` and branches made unreachable by the CGB-only header;
- remove SGB packet dispatch and rendering data after any still-useful palette
  IDs or RGB555 values have been migrated into native renderer tables; and
- add link-time assertions or CI searches preventing unauthorized palette
  register and VRAM-bank-1 writers.

## 5. Ownership invariants

The implementation is not complete unless all of these are true:

1. Exactly one subsystem owns CGB palette hardware.
2. Exactly one subsystem owns BG/window attribute generation.
3. Tile IDs and their attributes cannot be committed from unrelated paths.
4. Every interrupt restores the ROM, WRAM, and VRAM bank it interrupted.
5. Palette command completion leaves a fully described scene state.
6. Fades transform palette output without destroying base palette data.
7. No routine repairs color damage caused by another active renderer.
8. A missed VBlank deadline delays work; it does not perform an unsafe write.

## 6. Delivery stages

The implementation should be delivered as independently reviewable stages.
Detailed gates are in [migration-plan.md](docs/migration-plan.md).

1. Instrumentation and ownership assertions.
2. CGB-only startup and bank-safe memory foundation.
3. Eight-palette buffered core.
4. Unified tile/attribute transfer primitives.
5. Overworld and connected-map rendering.
6. Static screens and palette-command replacement.
7. Pokémon, trainer, and overworld object colors.
8. Battle animations and dynamic effects.
9. Yellow-exclusive systems.
10. Legacy renderer removal and hardening.

Do not merge a stage that introduces a second production renderer. Transitional
adapters are allowed; transitional co-ownership is not.

## 7. Acceptance criteria

### Functional

- All 25 tilesets render correct per-tile attributes.
- Every palette command has a Yellow-native implementation.
- All eight BG and OBJ palette slots can be used without corruption.
- Horizontal and vertical scrolling, connected maps, menus, and dialogue never
  lose or smear attributes.
- Battles retain correct species, trainer, HP, EXP, text, transition, and
  animation colors.
- Pikachu-following and all Yellow-exclusive sequences remain functional.
- Fades, flashes, blackouts, whiteouts, poison, and transition effects preserve
  their intended timing.
- Link, trade, printer, save/load, and soft reset do not corrupt bank state.

### Technical

- Release and debug ROMs build with RGBDS warnings treated as errors.
- The ROM header is CGB-only and the non-CGB startup path is deterministic.
- No unauthorized direct palette-register writes remain.
- No unauthorized VRAM-bank-1 attribute writers remain.
- Interrupt bank-restoration tests pass under forced non-default ROM, WRAM, and
  VRAM bank conditions.
- VBlank work remains within measured budgets on real-speed CGB timing.
- Automated screenshots are stable over multiple frames, not merely correct on
  one captured frame.

### Regression

- Gameplay state, collision, movement, scripts, audio, serial communication,
  and battle calculations are unchanged except where renderer timing previously
  exposed an actual bug. Save compatibility is not required, although unrelated
  save-data changes should not be introduced without cause.
- The failed hybrid implementation is not imported as runtime architecture.
  Its tests and verified tile assignments may be reused only after review.

## 8. Definition of done

The swap is done only when the old Yellow CGB renderer can be deleted without
changing behavior, all renderer ownership invariants are enforced, the complete
verification matrix passes, and no screen depends on a legacy attribute packet
or direct synchronous palette update.
