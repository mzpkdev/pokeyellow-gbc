# Overworld migration plan

## Stage 0: baseline and classification

- Build release, debug, and VC ROMs.
- Record bank capacity and interrupt timing.
- Inventory all palette and VRAM-bank-1 writers.
- Classify every palette command call as map-backed, standalone, or return.
- Capture stable map, connection, dialogue, and handoff states.

Exit gate: every relevant writer and scene boundary has an owner.

## Stage 1: ownership and bank-safe foundation

- Make the ROM CGB-only.
- Add bank-2 renderer WRAM.
- Add `RENDERER_YELLOW` and `RENDERER_FULL_COLOR_OVERWORLD`.
- Preserve ROM, WRAM, and VRAM banks in renderer-capable interrupts.
- Add job cancellation/generation behavior for handoffs.
- Initially keep visuals unchanged.

Exit gate: repeated synthetic ownership switches preserve banks and game state.

## Stage 2: overworld palette core

- Add eight BG and OBJ base palettes.
- Add transformed buffers and DMG shade remapping.
- Route palette wrappers by active owner.
- Activate the new core only under overworld ownership.
- Prove Yellow standalone screens still use their existing renderer.

Exit gate: diagnostic eight-palette output survives fades and repeated handoffs.

## Stage 3: paired attribute transfers

- Add the 256-byte tile attribute lookup.
- Pair initial map tile and attribute loads.
- Pair horizontal and vertical streaming.
- Pair all four connected-map directions.
- Pair third-screen and explicit row transfers.
- Add authoritative map-backed overlay attributes.

Exit gate: a diagnostic attribute table survives map entry, movement,
connections, dialogue, start-menu overlays, and reloads without restoration
hooks.

## Stage 4: overworld content

- Add palette sets and `$60` assignments for all 25 tilesets.
- Add native Beach House data.
- Add roofs and reviewed map-specific overrides.
- Verify animated tile compatibility.

Exit gate: every tileset and representative map exception passes atlas tests.

## Stage 5: overworld OAM

- Add picture-ID palette assignments.
- Insert palette bits after Yellow's final tile calculation.
- Preserve follower Pikachu VRAM offsets and animation.
- Cover field objects and transient overworld effects.

Exit gate: maximum visible NPCs, player movement, follower Pikachu, cut,
boulder, healing, fishing, ledges, and emotions render without wobble.

## Stage 6: real scene handoffs

- Handoff before battles and every standalone screen.
- Rebuild the map on every return path.
- Stress rapid open/close and nested transitions.
- Remove any implementation path that restores stale map VRAM.

Exit gate: all handoff smoke tests pass and owner logs never overlap.

## Stage 7: delete old overworld ownership

- Remove Yellow's old `SetPal_Overworld` tint path.
- Remove old map attribute writes.
- Delete transitional overworld adapters.
- Add CI enforcement for owner-gated hardware writers.
- Keep Yellow code required by standalone scenes.

Exit gate: old overworld code can no longer be selected, and excluded scenes
remain unchanged.

## Stage 8: timing and release hardening

- Measure LCD, VBlank, map streaming, palette upload, and OAM budgets.
- Test missed deadlines.
- Run the complete multi-frame verification matrix.
- Verify release/debug/VC builds.

Exit gate: no unsafe partial updates, bank leaks, or one-frame color corruption.

## Commit discipline

Each implementation PR should:

- change one stage or bounded transfer path;
- state the active owner before and after the change;
- include a transition or transfer test;
- avoid unrelated non-overworld color work; and
- remain bootable and diagnosable.
