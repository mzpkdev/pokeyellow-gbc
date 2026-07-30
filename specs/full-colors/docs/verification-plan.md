# Verification plan

Renderer validation must check stable behavior over time and across transitions.
A single screenshot can miss one-frame corruption, stale attributes, or a bank
restoration failure.

## Build checks

- Release ROM.
- Debug ROM.
- VC ROM.
- RGBDS warnings as errors.
- Link-map bank-capacity assertions.
- CGB-only header validation.
- Deterministic ROM hashes for repeated identical builds.

There are no DMG/SGB execution, old-renderer parity, binary matching, or
old-save migration gates.

## Static ownership checks

CI must maintain reviewed allowlists for:

```text
rBGPI / rBGPD writers
rOBPI / rOBPD writers
rVBK writers
rSVBK writers
HDMA/GDMA attribute transfers
```

The palette-register allowlist should converge on the renderer transfer
routine. `rVBK` and `rSVBK` necessarily have more users, but every result must
preserve its incoming bank or have a documented whole-program precondition.

## Bank-safety tests

Invoke renderer entry points while:

- a non-default ROM bank is active;
- WRAM bank 2 is active;
- another valid WRAM bank is active;
- VRAM bank 1 is active;
- an interrupt occurs during a far call; and
- a palette request is pending across soft reset.

Assert restoration of:

- `hLoadedROMBank` and `rROMB`;
- `rSVBK`;
- `rVBK`;
- stack pointer;
- interrupt-enable state; and
- renderer dirty flags.

## Timing tests

Instrument cycle or scanline usage for:

- LCD preparation with scanline overrides disabled;
- LCD preparation with overrides enabled;
- VBlank with no renderer work;
- BG-only palette upload;
- OBJ-only palette upload;
- both palette uploads;
- horizontal attribute redraw;
- vertical attribute redraw;
- automatic third-screen transfer; and
- OAM construction with the maximum visible objects.

Force insufficient time and verify work is deferred without a partial update.

## Overworld matrix

For every tileset:

- initial entry;
- return from a menu;
- close dialogue;
- horizontal walking;
- vertical walking;
- bicycle or movement-mode transition where supported;
- warp within the same tileset;
- warp to a different tileset;
- animated tiles; and
- text/font tile fallback.

Additional cases:

- every Fly destination;
- all four connected-map directions;
- Route 6/Saffron roof boundary;
- town-specific roof colors;
- Celadon Mart overrides;
- Vermilion Dock/SS Anne transition;
- caves and escape/warp transitions;
- Pokémon Center healing;
- cut tree and boulder;
- fishing and ledge shadow;
- Beach House; and
- follower Pikachu entering, leaving, hiding, and respawning.

## Palette command matrix

For each command:

1. enter from the overworld;
2. enter after a different static command;
3. fade out and in;
4. force black and white;
5. update only BGP;
6. update only OBP0;
7. update only OBP1;
8. return to the default command; and
9. observe at least five frames before and after transition.

Validate all command IDs listed in `SPEC.md`, including `$fc` and `$ff`.

## Battle matrix

- Wild and trainer battles.
- Player and enemy species with visibly distinct palettes.
- Player and enemy HP: green, yellow, and red.
- EXP gain and level-up.
- Player and enemy switching.
- Transform in both directions.
- Substitute.
- Status effects.
- Capture with Poké, Great, Ultra, Master, and Safari Balls.
- Ghost Marowak.
- Old Man tutorial.
- Link battle and link trade.
- Every battle transition.
- Both animation tilesets.
- At least one move of every type.
- Multi-turn and persistent effects such as Leech Seed.
- Healing items and trainer AI healing.
- Run, blackout, victory, loss, and Hall of Fame exits.

## Yellow-exclusive matrix

- Splash sequence.
- Title sequence and every animated object phase.
- Full Yellow intro.
- Oak speech.
- Pikachu front-picture animation.
- Pikachu emotion viewer and all emotion classes.
- Follower Pikachu movement in all directions and animation states.
- Pikachu entrance battle animation.
- Pikachu's Beach title.
- Surfing Pikachu gameplay, pause, results, retry, and exit.
- Yellow credits.
- Printer success, failure, and cancel paths.

## Persistence and external systems

- New game and continue.
- Save/load in multiple tilesets.
- Soft reset on overworld and static screens.
- Serial link initialization and teardown.
- Trade Center and Colosseum.
- Printer serial behavior.
- Audio continuity during long attribute/palette transfers.
- Poison and low-HP effects during transitions.

## Visual assertions

Automated captures should include:

- raw BG map 0 and BG map 1 tile IDs;
- corresponding VRAM bank 1 attributes;
- all BG and OBJ palette RAM;
- shadow OAM and hardware OAM;
- active renderer mode and dirty flags; and
- five-frame image sequences around transitions.

Compare semantic state as well as pixels. Pixel equality alone cannot identify
whether a correct-looking frame was produced by stale attributes.

## Completion report

The final implementation PR must include:

- build results;
- hardware-writer audit results;
- bank and timing measurements;
- command coverage;
- overworld, battle, and Yellow-exclusive matrix results;
- known visual-content differences from RGB;
- emulator versions; and
- any tests not run on physical CGB hardware.
