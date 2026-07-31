# Overworld verification plan

## Build and ownership checks

- Release, debug, and VC builds.
- CGB-only header validation.
- RGBDS warnings as errors.
- Link-map capacity assertions.
- Reviewed allowlists for `rBGPI`, `rBGPD`, `rOBPI`, `rOBPD`, `rVBK`, and
  `rSVBK`.
- Runtime assertion that exactly one renderer owner is active.
- Runtime assertion that queued jobs match the current ownership generation.

There are no DMG/SGB, binary matching, or old-save migration gates.

## Bank-safety matrix

Trigger map rendering and handoffs while:

- a non-default ROM bank is active;
- WRAM bank 2 is active;
- another valid WRAM bank is active;
- VRAM bank 1 is active;
- an interrupt occurs during a far call;
- a map transfer is pending; and
- a palette upload is pending.

Assert restoration of ROM, WRAM, VRAM, stack, interrupt state, owner, and dirty
flags.

## Timing matrix

Measure:

- LCD interrupt with scanline overrides off and on;
- VBlank with each owner;
- BG-only, OBJ-only, and combined overworld uploads;
- horizontal and vertical attribute streaming;
- connected-map streaming;
- third-screen overlay transfer;
- full map reconstruction; and
- OAM construction with maximum visible overworld objects.

Force insufficient time and confirm whole jobs defer safely.

## Tileset and map matrix

For every tileset:

- first entry;
- return from a standalone screen;
- horizontal and vertical movement;
- same-tileset and different-tileset warps;
- dialogue;
- start-menu overlay;
- tile reload; and
- animated tile behavior.

Special coverage:

- every Fly destination;
- all four connected-map directions;
- town roofs and Route 6/Saffron boundary;
- Celadon Mart overrides;
- Vermilion Dock/SS Anne transition;
- caves and dungeon warps;
- Pokémon Center healing;
- cut and boulder;
- fishing and ledge shadow;
- Beach House; and
- follower Pikachu hide, show, move, and respawn.

## Overlay matrix

Under full-color overworld ownership:

- NPC dialogue;
- signs;
- yes/no prompts;
- list menus;
- start menu open/close;
- field-move prompts;
- item messages; and
- text boxes near map edges and connection boundaries.

Validate terrain and overlay attributes for at least five frames before,
during, and after each operation.

## Handoff matrix

Enter each representative Yellow-owned scene from the overworld, assert the
owner changes before screen initialization, then return and assert a complete
map rebuild:

- wild and trainer battle;
- party and status;
- Pokédex;
- town map;
- naming and PC;
- title/intro paths reachable through reset or new game;
- slots;
- trade/link room;
- printer;
- evolution/Hall of Fame;
- Pikachu picture/emotion screen; and
- Surfing Pikachu.

The goal is not to recolor these scenes. The goal is to prove isolation and
correct return.

Stress:

- rapid repeated menu open/close;
- battle immediately after a map transition;
- soft reset under each owner;
- blackout and warp return;
- serial/link initialization;
- save/load in multiple tilesets; and
- queued map work cancelled by a handoff.

## Overworld OAM matrix

- Player walking, running, biking, surfing, fishing, and ledge states.
- Follower Pikachu in all directions and animation states.
- Maximum visible NPC population.
- Static NPCs and item balls.
- Cut tree and boulder movement.
- Dust/smoke.
- Healing machine.
- Emotion bubbles.
- Objects under grass/priority tiles.

Capture shadow OAM, hardware OAM, OBJ palettes, and multi-frame images.

## Visual and semantic captures

Automated captures should record:

- BG map tile IDs;
- VRAM-bank-1 attributes;
- BG and OBJ palette RAM;
- shadow and hardware OAM;
- owner and ownership generation;
- dirty and queued transfer state; and
- image sequences around overlays and handoffs.

A correct-looking single frame is insufficient because it can contain stale
attributes from the previous owner.

## Completion report

The final implementation PR must report:

- builds and header validation;
- hardware-writer audit;
- bank-stress results;
- timing measurements;
- all tileset/map coverage;
- overlay coverage;
- handoff coverage;
- overworld OAM coverage;
- emulator versions; and
- physical CGB tests not performed.
