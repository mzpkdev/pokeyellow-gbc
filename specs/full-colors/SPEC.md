# Full-color overworld renderer replacement

Status: proposed

Target: `pokeyellow`

Donor architecture: the overworld portion of `pokemon-rgb`

Scope: complete replacement of Yellow's overworld renderer only

## 1. Purpose

Replace Pokémon Yellow's overworld rendering pipeline with an authoritative
renderer based on `pokemon-rgb`.

The replacement owns the complete overworld scene:

- eight CGB background palettes;
- per-tile BG and window attributes;
- map loading, scrolling, connections, and tile reloads;
- dialogue and transient menu overlays that return directly to the map;
- eight CGB object palettes; and
- player, follower Pikachu, NPC, and map-object OAM palette selection.

Yellow's existing renderer continues to own battles and standalone screens.
This is not the failed hybrid design: the two renderers may exist in the ROM,
but they never own the same active scene at the same time.

Supporting analysis:

- [Architecture and ownership](docs/architecture.md)
- [Replacement inventory](docs/replacement-inventory.md)
- [Failed hybrid analysis](docs/failed-hybrid-analysis.md)
- [Migration plan](docs/migration-plan.md)
- [Verification plan](docs/verification-plan.md)

## 2. Scope

### 2.1 Included

- CGB-only startup; backward compatibility is not required.
- A named renderer ownership state.
- RGB-style bank-2 WRAM state needed by the overworld renderer.
- RGB-style eight-palette BG and OBJ storage and buffered updates while the
  overworld renderer owns the scene.
- Tile-ID-to-attribute tables for all 25 Yellow tilesets.
- Town roof and reviewed map-specific palette overrides.
- Initial map draw, map reload, streamed rows and columns, connected maps,
  animated tiles, text, dialogue, and map-backed menus.
- Overworld OAM palettes, including follower Pikachu.
- Clean handoff to Yellow before any non-overworld scene.
- Complete reconstruction of RGB overworld state after returning to a map.

### 2.2 Excluded

The following remain on Yellow's existing renderer:

- battle backgrounds, HUD, Pokémon, trainers, transitions, and animations;
- title, splash, Oak speech, Yellow intro, and credits;
- party, status, Pokédex, town map, trainer card, naming, and PC screens;
- evolution, Hall of Fame, and trade presentation;
- slots, printer screens, and link-room presentation;
- Pikachu front-picture and emotion-picture screens;
- Pikachu's Beach title and Surfing Pikachu gameplay; and
- all other standalone screens that replace the map scene.

Follower Pikachu is included because it is part of overworld OAM.

### 2.3 No backward-compatibility requirement

The project does not need to preserve:

- DMG or SGB execution;
- the failed full-color-overworld implementation;
- ROM binary layout or matching hashes;
- old renderer-specific RAM layout;
- visual parity for the overwritten overworld renderer;
- old save compatibility if a save-format change is genuinely useful; or
- old internal overworld-renderer APIs.

Non-overworld gameplay and presentation must remain functionally intact because
they are deliberately outside this replacement, not because of compatibility
with the old overworld renderer.

## 3. Architectural decision

### 3.1 Scene-bounded ownership

The active owner is always exactly one of:

```text
RENDERER_YELLOW
RENDERER_FULL_COLOR_OVERWORLD
```

When `RENDERER_FULL_COLOR_OVERWORLD` is active, the new renderer exclusively
owns:

1. all eight BG palette slots;
2. all eight OBJ palette slots used by the map scene;
3. BG/window VRAM-bank-1 attributes;
4. OAM palette bits for overworld objects;
5. palette dirty state and overworld palette transfers; and
6. all tile/attribute transfers that can alter the visible map scene.

Yellow's renderer must not copy canned attributes or directly refresh palette
hardware during that ownership interval.

When `RENDERER_YELLOW` is active, the new renderer performs no palette or
attribute writes. Yellow continues to render non-overworld scenes unchanged.

### 3.2 What counts as the overworld scene

An operation remains under full-color overworld ownership when it temporarily
draws over the map and expects to reveal that same map without a complete scene
load:

- dialogue and text boxes;
- the map-backed start menu;
- yes/no and list overlays;
- sign and NPC interactions;
- field-move prompts; and
- any transient window using the map as its backing scene.

These overlays must use renderer-owned attribute generation. They must not ask
Yellow to paint attributes and then restore map color afterward.

A standalone screen triggers a handoff to Yellow when it rebuilds the screen
and has its own palette command, tilemap, or presentation lifecycle. Returning
from that screen must reconstruct the overworld palette and attribute state
from authoritative map data, not copy back stale VRAM.

### 3.3 Handoff protocol

#### Entering or rebuilding the overworld

1. Stop or drain pending Yellow palette/attribute transfers.
2. Set the active owner to `RENDERER_FULL_COLOR_OVERWORLD`.
3. Select the tileset palette set and tile attribute table.
4. Load all eight overworld BG and OBJ base palettes.
5. Build tile IDs and attributes through the paired transfer path.
6. Mark palette buffers dirty.
7. Present the complete map scene on a safe frame.

#### Leaving the overworld

1. Prevent new overworld transfer requests.
2. Drain or cancel pending overworld work at a defined safe point.
3. Set the active owner to `RENDERER_YELLOW`.
4. Invoke the destination's ordinary Yellow palette command and screen setup.

#### Returning to the overworld

Run the complete entering protocol. No correctness may depend on attributes or
palettes surviving the non-overworld scene.

## 4. Requirements

### R1. CGB-only foundation

- Change the cartridge from CGB-compatible to CGB-only.
- Reject non-CGB startup deterministically.
- Enter double-speed mode once during hard boot.
- Remove runtime DMG/SGB selection where it affects the overworld path.
- Do not retain an old-overworld fallback or feature toggle.

Yellow's non-overworld CGB renderer may retain now-constant CGB checks until
cleanup; removing every such branch is not required by this project.

### R2. WRAM and bank safety

- Reserve a named WRAMX bank-2 section for overworld renderer state.
- Clear that state on hard boot and soft reset.
- Preserve and restore `rSVBK` across interrupts and public renderer calls.
- Preserve and restore `rVBK` across interrupts and renderer calls.
- Never return to Yellow code with bank 2 selected accidentally.
- Never place renderer state where it aliases the active stack.

### R3. ROM banking

- Do not use RGB bank `$2c`; Yellow stores Text 7 there.
- Do not import RGB's bank `$31` binary; Yellow stores Pikachu cries there.
- Do not assume RGB's `$1c` extension has compatible free space.
- Use Yellow's empty bank `$3b` as the first renderer bank.
- Convert donor MBC1 assumptions to Yellow's MBC5 far-call conventions.
- Preserve interrupted ROM-bank state during renderer work.

### R4. Overworld palette model

- Store eight four-color RGB555 BG palettes.
- Store eight four-color RGB555 OBJ palettes.
- Maintain transformed 64-byte BG and OBJ output buffers.
- Apply `BGP`, `OBP0`, and `OBP1` shade remapping without destroying base data.
- Support all-white, all-black, fades, flashes, and poison/transition effects
  that occur while the overworld is visible.
- Palette requests must update base state or dirty flags, not race unscheduled
  direct hardware writes.
- Yellow palette-update wrappers must dispatch by active owner: new renderer
  while in the overworld, Yellow renderer otherwise.

### R5. Tile attribute model

- Use a 256-byte tile-ID-to-CGB-attribute lookup while rendering maps.
- Define tiles `$00-$5f` per tileset.
- Default `$60-$ff` to a deliberate text/window attribute unless explicitly
  assigned.
- Preserve the full attribute byte: palette, tile bank, flips, and priority.
- Generate dialogue and transient-menu attributes from explicit overlay rules,
  not by allowing Yellow's canned screen attributes to overwrite the map.

The new renderer does not need RGB's general 20×18 static-screen mode because
standalone static screens remain owned by Yellow. A small renderer-owned
overlay grid or prepared window buffer may be used where map-backed windows
need coordinate-specific attributes.

### R6. Paired transfer coverage

Every tile-writing path active during overworld ownership must commit matching
attributes through the same primitive or a serialized paired primitive:

- initial map load with LCD disabled;
- full map and tileset reload;
- horizontal and vertical streamed redraw;
- all four connected-map edges;
- automatic one-third tilemap/window transfers;
- explicit `TransferBgRows`;
- text and dialogue;
- start-menu and map-backed window open/close;
- animated water, flowers, and replacement tiles;
- map transitions that use `$9800` or `$9c00`; and
- field effects that alter BG tiles.

No gameplay-level "restore full-color attributes" hooks are permitted.

### R7. Tileset data

- Define eight-palette sets for all 25 Yellow tilesets.
- Audit RGB assignments against Yellow tile graphics before reuse.
- Create a native `BEACH_HOUSE` assignment; RGB slot 24 is `SAFARI`.
- Assert `NUM_TILESETS` table lengths.
- Assert exactly `$60` assignments per tileset.
- Document town roofs and every map-specific override.
- Verify animated replacement frames retain compatible 2bpp color indices.

### R8. Overworld OAM

- Insert palette bits during authoritative OAM construction.
- Preserve priority, flips, tile VRAM bank, and control flags.
- Assign palettes by overworld picture identity with deterministic fallback.
- Preserve Yellow's `hPikachuSpriteVRAMOffset` tile calculation.
- Cover the player, follower Pikachu, NPCs, item balls, cut trees, boulders,
  dust, healing machine, fishing rod, ledge shadow, and emotion bubbles that
  appear over the map.
- Keep OAM work within measured frame budget and avoid sprite wobble.

Non-overworld OAM, party icons, battle animations, and picture sprites remain
unchanged.

### R9. Interrupt and transfer scheduling

- Compose renderer preparation with Yellow's existing LCD scanline handler;
  do not replace `wLYOverrides` behavior.
- Route VBlank palette work according to the active owner.
- Do not run overworld palette or attribute transfers under Yellow ownership.
- Check that sufficient safe time remains before starting an upload.
- Leave dirty work pending when a deadline is missed.
- Serialize map row/column attributes against palette uploads.
- Restore ROM, WRAM, and VRAM banks on every exit path.

RGB's exact scanline constants are reference values, not automatically correct
for Yellow.

### R10. Non-overworld isolation

- Battles and standalone screens must continue using Yellow's current palette
  and canned/static attribute behavior.
- Entering those scenes must perform the explicit ownership handoff first.
- No new RGB battle, menu, animation, Pokémon-picture, or minigame palette data
  is imported.
- Smoke tests must prove the ownership switch did not leave bank state, dirty
  flags, interrupts, or palette wrappers in an invalid state.
- Returning to a map always rebuilds full-color state.

### R11. Removal of the old overworld path

After the replacement passes:

- remove Yellow's whole-screen overworld tint selection from
  `SetPal_Overworld`;
- remove old overworld attribute/palette writes;
- remove the failed feature toggle and restoration hooks if present in the
  implementation base;
- remove transitional overworld adapters after callers migrate; and
- add CI searches preventing unauthorized VRAM-bank-1 or palette writers while
  `RENDERER_FULL_COLOR_OVERWORLD` is active.

Do not delete Yellow rendering code still used by excluded scenes.

## 5. Invariants

1. Exactly one renderer owns the active scene.
2. Yellow performs no palette or BG-attribute writes during full-color
   overworld ownership.
3. The new renderer performs no writes during Yellow ownership.
4. Tile IDs and overworld attributes travel through paired transfer paths.
5. Map-backed overlays are part of the overworld renderer.
6. Standalone screens use an explicit handoff and map reconstruction on return.
7. Every interrupt restores ROM, WRAM, and VRAM bank state.
8. A missed deadline defers work instead of performing an unsafe partial write.
9. No repair hook exists solely because another renderer overwrote the map.

## 6. Delivery stages

1. Baseline, writer inventory, and scene-boundary classification.
2. CGB-only startup, bank-2 WRAM, and ownership state.
3. Overworld eight-palette core with owner-dispatched wrappers.
4. Paired initial, streamed, connected-map, and window transfers.
5. All tileset palette/attribute data and map exceptions.
6. Overworld OAM, including follower Pikachu and field objects.
7. Scene handoffs, non-overworld isolation, and legacy-overworld deletion.
8. Timing hardening and complete verification.

Detailed gates are in [migration-plan.md](docs/migration-plan.md).

## 7. Acceptance criteria

### Overworld

- All 25 tilesets use correct per-tile attributes.
- Initial entry, reload, scrolling, and all map connections remain colored.
- Dialogue and map-backed menus never erase or smear map attributes.
- Town roofs, map overrides, animated tiles, and field effects remain correct.
- Player, follower Pikachu, NPCs, and map objects use deliberate OBJ palettes.
- No visible one-frame stale, white, black, or mismatched palette appears.

### Handoffs

- Every standalone screen is entered under Yellow ownership.
- Battles, title/intro, menus, pictures, trade, slots, printer, and Surfing
  Pikachu remain functionally unchanged.
- Returning from every tested screen reconstructs the overworld correctly.
- Repeated rapid transitions do not leak ownership or pending work.

### Technical

- Release, debug, and VC ROMs build with warnings as errors.
- Header validation confirms CGB-only.
- Hardware-writer audits pass.
- Forced bank-state interrupt tests pass.
- Measured LCD/VBlank/OAM work fits CGB timing or safely defers.
- Multi-frame automated captures pass for transfers and handoffs.

## 8. Definition of done

The work is complete when RGB's architecture exclusively renders every
overworld frame, Yellow exclusively renders every excluded scene, transitions
between them are explicit and deterministic, and the old Yellow overworld path
can be deleted without changing either side's behavior.
