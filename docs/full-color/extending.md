# Extending the full-color slice

This is the implementation checklist for adding color or gameplay coverage. Read
[architecture.md](architecture.md) before changing ownership or timing, and use
[verification-harness.md](verification-harness.md) to interpret the gates.

The current playable renderer is deliberately narrow: only the `_DEBUG` +
`PHASE2_AUDIT` product colors Pallet Town and Route 1. Yellow still owns tile
graphics, sprites, animation, menus, battles, mechanics, and scheduling. The
passive layer may install BG palettes and VRAM-bank-1 tile attributes only.

## First decide: bounded slice or roadmap work?

Keep a change in Phase 2 only when all of these are true:

- the map uses the same tileset and the same complete 256-entry tile-to-attribute
  authority as the existing slice;
- one global eight-palette BG payload, including its roof colors, is correct for
  every added map;
- Yellow can remain authoritative for every bank-0 tile, sprite, animation,
  overlay, fade, transfer, and gameplay event;
- entry, scrolling, connections, menus, battles, exit cleanup, save/reset, and
  return paths fit the existing passive lifecycle without a new owner or writer;
- the audit-only product boundary remains intact.

If any answer is no, the work belongs in a later roadmap phase. Do not smuggle
map-aware palette selection, new tileset content, animation or overlay
precedence, sprite coloring, or production integration into an allowlist edit.
Phase 3 builds the palette and paired-transfer architecture; Phase 4 owns
overworld OAM; Phase 5 stress-tests the architecture; Phase 6 completes and
accepts all 25 tilesets, roofs, overrides, and content; Phase 7 closes every
handoff; Phase 8 removes old overworld ownership; and Phase 9 hardens release
timing and products. The authoritative sequencing and exit gates live in the
[migration plan](../../specs/full-colors/docs/migration-plan.md).

## Add a map compatible with the passive slice

### Prerequisites

Before touching the allowlist, prove from the map header and block data that the
candidate uses `OVERWORLD`, that every reachable tile has an authored entry in
the current table, and that the existing palette payload (including palette 6's
Pallet roof colors) is visually correct. Test door/warp exits and every seamless
connection in both directions. A shared tileset is necessary, not sufficient.

### Implementation order

Keep the new map unreachable while closing its discovery, inventory, and audit
authority. The migration rule is strict: reviewed source and built-ROM closure
comes before the changed runtime path becomes reachable.

1. Add the map's source scene root to `PHASE2_HOSTILE_SCENE_ROOTS` in
   [source_discovery.py](../../tools/rom_tests/full_color/source_discovery.py).
2. Update every concrete-slice authority in
   [phase2_measurements.py](../../tools/rom_tests/full_color/phase2_measurements.py),
   not only `PHASE2_ROOT_ROWS`:

   - add the root-to-row assignment in `PHASE2_ROOT_ROWS` and any new closed row
     ID in `PHASE2_PLANNED_ROW_IDS`;
   - update `PHASE2_SCENE_EDGE_CLASSIFICATIONS`, `_CLOSED_SCENE_DIRECTIONS`,
     `_PASSIVE_REQUIRED_EDGES`, and `_PASSIVE_REQUIRED_WRITERS` when the new
     boundary or writer surface changes them;
   - update the reviewed `_PASSIVE_ROM_POINTER_WRITES` sites, root/path
     ancestry, and its pinned audit-ROM SHA-256 comment if the linked code moves;
   - extend the hard-coded header reads and `concrete_slice_ok` predicates near
     the inventory-audit output; and
   - update the returned `inventory_audit["concrete_slice"]` identity. The
     derived `guarded_root_count` must then reflect the expanded root set.
3. Add the new root pointer to the stable lexical sequence in
   [phase2_audit.asm](../../engine/full_color/phase2_audit.asm), and update its
   exact `ASSERT Phase2AuditRootsEnd - Phase2AuditRoots == N * 2` count.
   `_verify_audit_product` decodes this table and requires its length and order
   to match `_phase2_roots()` exactly; changing Python discovery without this
   compiled provenance pointer makes verification fail closed.
4. Reconcile every new source and ROM finding with
   [phase2-planned-subjects.json](../../specs/full-colors/definitions/phase2-planned-subjects.json)
   and the four authorities under
   [specs/full-colors/inventory](../../specs/full-colors/inventory). Do not reuse
   a row merely because its name sounds close: each discovered fingerprint must
   have the correct scene, mutation, writer, product identity, and reviewed
   assignment.
5. Update the concrete slice/transition definition in
   [phase2-hostile-slice-representation.json](../../specs/full-colors/definitions/phase2-hostile-slice-representation.json)
   if the newly supported boundary changes the modeled pressure sequence.
6. With both runtime allowlists still unchanged, build all four products,
   regenerate the derived evidence with the official generator, review the
   new subjects, and require `make verify-full-color-phase2-audit` to pass.
   Never hand-edit the generated evidence file.
7. Only after that closure is reviewed, add the map constant to
   `PassiveFullColorIsSliceMap` in
   [passive_overworld.asm](../../engine/full_color/passive_overworld.asm), then
   add the same map to the inline guard in `PassiveFullColorVBlank`. This
   duplicate is intentional: the VBlank path reads WRAM2 stacklessly. If only
   the first allowlist changes, entry appears to work but scrolling color
   updates remain inactive.
8. Extend the linked-ROM cases in
   [test_passive_overworld_rom.py](../../tools/rom_tests/tests/unit/full_color/test_passive_overworld_rom.py)
   and the timing/connection cases in
   [test_passive_overworld_timing.py](../../tools/rom_tests/tests/unit/full_color/test_passive_overworld_timing.py).
   Cover LCD-off entry, all 1,024 attributes, row and column redraws, palette
   deferral, seamless entry/exit, complete cleanup, generation mismatch, and
   bank/register restoration.
9. Rebuild and regenerate the evidence again after activation, because the
   audit ROM and source identities have changed. Re-run the verifier before
   claiming the path.

```sh
make yellow_debug yellow_phase2_audit pokeyellow.gbc pokeyellow_vc.gbc
.venv/bin/python -m tools.rom_tests.full_color.phase2_measurements \
  --root . \
  --output specs/full-colors/evidence/phase2-hostile-slice-representation.json
make verify-full-color-phase2-audit
```

10. Add a natural cold-boot checkpoint when the map is reachable in the current
   journey. Assert gameplay state and renderer state as well as pixels; a pretty
   screenshot alone does not prove that tiles, attributes, or event flow match.
11. Review screenshots from entry, movement near every edge, overlays, battle
   round trips, interiors, and both exits. One still frame cannot reveal flicker,
   a stale redraw column, or cleanup spread across VBlanks.

### Viridian City example

Viridian uses `OVERWORLD`, so adding `VIRIDIAN_CITY` to both guards is useful as
a **diagnostic canary**: it can prove that the passive path activates, scrolls,
and survives the Route 1 connection. It is not honest Viridian coloring.

The current global payload hardcodes Pallet roof colors in palette 6. Phase 3
must provide map-aware palette selection and paired-transfer architecture, but
that architecture alone does not finish Viridian. Phase 6 supplies and accepts
the reviewed Viridian roof/content authority against the completed tileset set.
Until both milestones are evidenced, Viridian must remain outside the claimed
slice; do not describe an allowlisted build as finished or authoritative.

## Change palette or tile-attribute authority

The current authority is
[data/tilesets/full_color_overworld.asm](../../data/tilesets/full_color_overworld.asm):

- `FullColorOverworldBGPalettes` is exactly 64 bytes: eight complete CGB BG
  palettes, four RGB555 colors each;
- `FullColorOverworldTileAttributes` is exactly 256 bytes, indexed by the full
  bank-0 tile ID;
- tiles `$00`-`$5f` adapt the pinned, permitted donor table; tiles `$60`-`$ff`
  explicitly use text palette 7;
- every attribute must use legal CGB bits. The present table selects bank 0 and
  authors no priority.

Never derive a palette as `tile_id & 7` (or `n & 7`). Tile IDs are identities,
not palette classes; low-bit derivation produced plausible-looking corruption
and destroys donor provenance. Author all 256 entries explicitly, even when a
range intentionally repeats one value.

For a data change:

1. Record the source, permission, pinned revision, and any deliberate correction
   beside the table. Do not silently “clean up” donor data.
2. Change the complete palette/table authority and keep the size assertions.
3. Update the frozen permitted digests and semantic spot checks in
   [test_overworld_color_data.py](../../tools/rom_tests/tests/unit/full_color/test_overworld_color_data.py)
   only after independently comparing the new authority with its source. If a
   donor checkout is available at `/tmp/Pokemon_GBC_Celebrations` (or through
   `POKEMON_GBC_CELEBRATIONS_ROOT`), run the exact-adaptation test too.
4. Extend linked-ROM tests so they read the bytes from the built audit ROM, not
   from a second Python copy of the expected table.
5. Regenerate Phase 2 evidence because the audit ROM/source identities change,
   then run the gates below and manually inspect natural gameplay captures.

## Add natural gameplay coverage

Reusable input journeys live under
[tools/rom_tests/scenarios](../../tools/rom_tests/scenarios). Keep them layered:
`new_game.py` reaches the bedroom, `oaks_lab.py` builds on it,
`viridian_city.py` continues north, and `parcel_delivery.py` continues the quest.
Tests live under
[tools/rom_tests/tests/e2e](../../tools/rom_tests/tests/e2e).

When adding a checkpoint or content path:

1. Start a fresh `Emulator`; never depend on state left by another test.
2. Reach the state with controller input and natural game transitions. Memory
   reads may observe progress, but must not teleport the player, force scripts,
   or manufacture expected VRAM.
3. Bound every wait and movement loop. Put the intended map, coordinate, script,
   or battle condition in its failure message.
4. Assert logical state first: map, coordinates, script/event flags, party,
   battle state, or inventory. Then assert renderer active/inactive state,
   bank-0 tiles, bank-1 attributes, palettes, and screen where relevant.
5. Capture named failure images. For flicker-prone paths, observe multiple frames
   around the transition instead of blessing one convenient frame.
6. Put reusable navigation in the scenario module and assertions in the test.
   Extend
   [test_full_color_cold_boot_journey.py](../../tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py)
   for paired stock/audit behavior across the playable color slice.

The older visual E2E tests use committed PNGs under
[tools/rom_tests/snapshots](../../tools/rom_tests/snapshots). Update only the
specific test's snapshot, using the intended ROM explicitly:

```sh
ROM_TEST_ROM=pokeyellow_debug.gbc \
ROM_TEST_SYMBOLS=pokeyellow_debug.sym \
UPDATE_ROM_SNAPSHOTS=1 \
.venv/bin/python -m pytest tools/rom_tests/tests/e2e/test_new_game.py -q
```

Then rerun without `UPDATE_ROM_SNAPSHOTS`, inspect the new PNG and `git diff`,
and have another reviewer confirm the change. Never bulk-bless snapshots, and
never update one merely because a regression test failed. The cold-boot
full-color journey writes diagnostic captures under `test-results/`; those are
run artifacts, not golden snapshots to commit.

## Verification ladder

Run focused checks while iterating, then the complete gate. A reasonable order
for a map or palette extension is:

```sh
make yellow_phase2_audit
.venv/bin/python -m pytest \
  tools/rom_tests/tests/unit/full_color/test_overworld_color_data.py \
  tools/rom_tests/tests/unit/full_color/test_passive_overworld_rom.py \
  tools/rom_tests/tests/unit/full_color/test_passive_overworld_timing.py -q
make test-full-color-smoke
make verify-full-color-phase2-audit
make test-full-color-renderer-conformance
make test-full-color-renderer-runtime
make test-full-color-gate0
make yellow_debug yellow_phase2_audit
.venv/bin/python -m pytest \
  tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
make test-full-color-all
```

`test-full-color-all` does not include Phase 2 evidence verification or the
cold-boot E2E journey, so those explicit commands are mandatory. Preserve Gate
0's two independent runs, the Phase 1 runtime evidence, the synthetic checker,
mutation sensitivity, time bounds, audit exclusion from normal products, and
byte-identical stable artifacts. A new green screenshot is additional evidence;
it is never permission to weaken one of those gates.

## Common failure signatures

- **Entry is colored, scrolling is not:** the VBlank guard was not updated, or
  row/column preparation did not run.
- **Map is recognizable but roofs are wrong:** the global palette is being used
  beyond its authority. Phase 3 supplies map-aware dispatch; Phase 6 supplies
  and accepts the complete roof/content data.
- **Tiles look mismatched or striped:** tile identity was derived or bank-0 was
  overwritten. Re-establish Yellow's bank-0 authority and the explicit 256-byte
  lookup.
- **Leaving the slice contaminates an interior/town:** verify palette
  homogenization, all 32 attribute-clear chunks, and both connection directions.
- **The intro colors before a real map load:** the explicit active/generation
  guard was bypassed; map ID zero is Pallet at power-on and is not proof of entry.
- **Evidence regeneration explodes into new findings:** stop and reconcile the
  inventory. Do not widen discovery exclusions or relabel unknown writers to
  make the file stable.
