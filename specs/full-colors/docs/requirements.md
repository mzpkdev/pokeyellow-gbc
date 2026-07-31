# Normative requirements

## R1. Renderer ownership

- Define `RENDERER_YELLOW` and `RENDERER_FULL_COLOR_OVERWORLD`.
- Exactly one owner is active.
- Yellow performs no palette or BG-attribute writes under full-color ownership.
- The new renderer performs no writes under Yellow ownership.
- Queued work is tagged with an ownership generation and cannot survive a
  handoff.

## R2. Handoffs

Entering the overworld must:

1. stop or drain Yellow renderer work;
2. select full-color ownership;
3. load the tileset palette and attribute data;
4. reconstruct tile IDs and attributes;
5. load all overworld BG/OBJ palettes; and
6. present one complete scene safely.

Leaving the overworld must:

1. block new map jobs;
2. drain or cancel pending jobs;
3. select Yellow ownership; and
4. initialize the destination through Yellow's existing renderer.

Returning always runs the complete entering protocol.

## R3. CGB and bank foundation

- Build a CGB-only cartridge and reject non-CGB startup.
- Enter double-speed mode once per hard boot.
- Use a named WRAMX bank-2 section for renderer state.
- Clear renderer state on hard boot and soft reset.
- Preserve ROM, `rSVBK`, `rVBK`, stack, and interrupt state across renderer
  calls and interrupts.
- Never return to Yellow code with an accidental bank selection.

## R4. ROM placement

- Do not use RGB bank `$2c`; Yellow stores Text 7 there.
- Do not import RGB bank `$31`; Yellow stores Pikachu cries there.
- Do not assume RGB's `$1c` extension is free.
- Start in Yellow's empty bank `$3b`.
- Convert donor MBC1 assumptions to Yellow's MBC5 far-call conventions.

## R5. Palette model

- Store eight four-color RGB555 BG palettes.
- Store eight four-color RGB555 OBJ palettes.
- Maintain complete transformed BG and OBJ buffers.
- Apply `BGP`, `OBP0`, and `OBP1` remapping without destroying base data.
- Support overworld fades, flashes, white, black, and poison effects.
- Schedule hardware writes through the active owner; gameplay code sets state
  or dirty flags.
- Palette wrappers dispatch by owner.

## R6. Attribute model

- Use a 256-byte tile-ID-to-CGB-attribute lookup for maps.
- Define `$00-$5f` per tileset.
- Give `$60-$ff` a deliberate text/window default unless explicitly assigned.
- Preserve palette, tile-bank, flip, and priority bits.
- Generate map-backed overlay attributes within the full-color renderer.
- Do not import RGB's standalone-screen 20×18 mode unless an overworld overlay
  has a demonstrated coordinate-specific need.

## R7. Paired transfers

Every overworld tile-writing path commits matching attributes through the same
job or a serialized paired job:

- initial load and full reload;
- horizontal and vertical streaming;
- four-direction connections;
- one-third window/tilemap transfer;
- explicit row transfer;
- dialogue and transient overlays;
- alternate BG map destinations;
- animated tiles; and
- field effects that replace BG tiles.

Gameplay-level color-restoration hooks are forbidden.

## R8. Tileset data

- Provide palette sets and exactly `$60` assignments for all 25 Yellow
  tilesets.
- Audit RGB assignments against Yellow tile graphics.
- Create native `BEACH_HOUSE` data; RGB ID 24 is `SAFARI`.
- Assert all table lengths.
- Document roofs and every map-specific override.
- Verify animated frames retain compatible 2bpp indices.

## R9. Overworld OAM

- Insert palette bits during authoritative overworld OAM construction.
- Preserve priority, flips, tile bank, and control flags.
- Assign palettes by picture identity with deterministic fallback.
- Preserve `hPikachuSpriteVRAMOffset`.
- Cover player, follower Pikachu, NPCs, item balls, cut trees, boulders, dust,
  healing machine, fishing rod, ledge shadow, and emotion bubbles.
- Keep OAM work within measured timing and avoid wobble.

## R10. Scheduling

- Compose preparation with Yellow's existing LCD `wLYOverrides` handler.
- Route VBlank work by active owner.
- Instrument timing from the first diagnostic renderer slice onward.
- Check safe time before starting uploads.
- Defer complete jobs when a deadline is missed.
- Serialize row/column attributes against palette uploads.
- Restore every bank on every exit.

RGB scanline constants are references, not accepted Yellow values.

## R11. Diagnostic mode

- Provide a debug-only canary mode with unmistakable assignments for all eight
  palette slots and selected tile classes.
- Keep canary output deterministic and unavailable in release builds.
- Capture named screenshots and bounded frame strips at diagnostic checkpoints.
- Pair visual evidence with semantic state and writer traces.
- Treat LLM screenshot inspection as a supported test-play workflow, not as a
  replacement for machine assertions.

## R12. Isolation and removal

- Battles and standalone screens retain Yellow rendering behavior.
- Handoff occurs before their initialization.
- Returning rebuilds the map from authoritative data.
- Do not import RGB battle, picture, animation, or minigame runtime modules.
- Remove Yellow's old overworld tint and attribute ownership after replacement.
- Keep Yellow code still required by excluded scenes.
- Enforce owner-gated hardware writers in CI.

## Invariants

1. One active scene owner.
2. No stale-generation job executes.
3. Map tiles and attributes use paired transfer paths.
4. Map-backed overlays never invoke competing attribute ownership.
5. Standalone screens hand off before drawing.
6. Every return reconstructs the map.
7. Interrupts restore ROM/WRAM/VRAM bank state.
8. Missed deadlines defer rather than partially write.
9. No hook exists solely to repair another renderer's overwrite.
