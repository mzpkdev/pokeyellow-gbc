# Migration plan

The sequence is designed to avoid a second production renderer and to make
failures attributable to one stage.

## Stage 0: baseline and instrumentation

- Build release, debug, and VC targets.
- Record ROM size, bank free space, and symbols.
- Capture stable screenshots and emulator states for every verification scene.
- Add CI searches for palette-register and VRAM-bank-1 writers.
- Record cycle budgets for the current VBlank and LCD handlers.

Exit gate: reproducible baseline with no worktree changes during capture.

## Stage 1: CGB-only and bank-safe foundation

- Change the header to CGB-only.
- Add non-CGB error behavior.
- Delete runtime DMG/SGB renderer selection; no fallback is retained.
- Enter double-speed mode.
- Add named WRAMX bank-2 renderer sections.
- Preserve `rSVBK` and `rVBK` in VBlank, LCD, timer, and serial paths.
- Make soft reset clear renderer state.
- Add far-call tests under non-default ROM and WRAM banks.

Exit gate: game behavior remains visually unchanged using the old palettes, and
bank-stress tests pass.

## Stage 2: eight-palette core

- Port base BG/OBJ palette storage.
- Port shade-register transformation.
- Add dirty flags and transformed buffers.
- Redirect the four public palette-update functions to the new core.
- Upload all eight palettes safely.
- Keep existing attribute maps temporarily, but do not allow the old palette
  hardware writer to remain active.

Exit gate: existing Yellow screens look equivalent while using only the new
palette hardware owner.

## Stage 3: unified attribute transfers

- Introduce tile lookup and static screen modes.
- Pair attributes with initial map, row, column, third-screen, and explicit row
  transfers.
- Handle both BG map destinations.
- Remove gameplay-level full-color restoration hooks.
- Add missed-deadline behavior.

Exit gate: a diagnostic attribute pattern survives all transfer paths,
including four-direction connected-map scrolling.

## Stage 4: overworld

- Add eight-palette sets and `$60`-byte assignments for all Yellow tilesets.
- Implement roofs and reviewed map-specific overrides.
- Handle animated map tiles.
- Load environment OBJ palettes.

Exit gate: atlas and movement tests pass for every tileset and representative
connections.

## Stage 5: static screens and commands

- Implement every ordinary Yellow command as a complete scene.
- Convert battles, status, party, Pokédex, slots, town map, title, generic,
  whole-screen Pokémon, Game Freak intro, and trainer card.
- Implement `$fc` as a localized party HP update.
- Make `$ff` dispatch the recorded complete scene.
- Remove converted canned attribute packets.

Exit gate: all command-contract tests pass and no converted command invokes the
old attribute loader.

## Stage 6: picture and object palettes

- Add species/trainer lookup.
- Add Transform preservation.
- Add overworld picture-ID assignments.
- Integrate palette insertion into Yellow OAM construction after Pikachu tile
  calculation.
- Add party icons and special overworld objects.

Exit gate: all player/NPC/Pikachu movements and picture scenes pass multi-frame
tests without OAM jitter.

## Stage 7: battle animations and dynamic effects

- Port tile-ID animation maps.
- Add move-type palettes.
- Add Poké Ball, status, seed, ghost, trade, HUD, and HP/EXP dynamic behavior.
- Classify and replace every old OBP update call.

Exit gate: animation matrix passes for both animation tilesets and every
palette-changing effect category.

## Stage 8: Yellow-exclusive systems

- Yellow splash/title.
- Full Yellow intro.
- Oak speech/Pikachu picture animation.
- Pikachu emotion and follower transitions.
- Pikachu's Beach title and Surfing Pikachu game.
- Credits, printer, and Yellow-specific link/trade flows.

Exit gate: each system declares and tests complete scene ownership.

## Stage 9: deletion and hardening

- Delete old palette buffers and converter.
- Delete obsolete canned attribute data and translation.
- Remove unreachable DMG/CGB branches.
- Delete every transitional palette adapter and migrate its remaining callers.
- Enforce authorized hardware-writer lists in CI.
- Run the complete verification matrix on release/debug/VC builds.

Exit gate: reverting any deleted legacy component is unnecessary for behavior,
and repository searches show one palette and attribute owner.

## Commit discipline

Each implementation PR should:

- address one stage or a bounded subset;
- state which owner changes;
- include tests for the transfer or scene contract it changes;
- avoid unrelated palette-content tuning; and
- leave the ROM bootable and testable.

Palette art review and renderer correctness should be separate commits where
possible. A technically correct renderer can display provisional colors; a
beautiful palette cannot compensate for uncertain ownership.
