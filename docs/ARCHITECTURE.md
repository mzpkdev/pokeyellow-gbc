# ROM architecture

This is the architectural map for the whole ROM hack. It describes the
structure that exists in the repository, the compatibility contracts that make
changes dangerous, and the direction new systems should follow. Renderer-specific
details live in [FULL_COLOR_RENDERER.md](FULL_COLOR_RENDERER.md); start from
[INDEX.md](INDEX.md) when onboarding.

## Build and link architecture

The ROM is assembled by RGBDS from several translation-unit roots listed in
the [Makefile](../Makefile): `audio.asm`, `home.asm`, `main.asm`, `maps.asm`,
`ram.asm`, `text.asm`, and the `gfx/*.asm` roots. Each root expands an ordered
tree of `INCLUDE` and `INCBIN` directives into one object. This repository does
not compile every `.asm` file independently.

Every object is assembled with `-P includes.asm`. That preinclude is a shared
source ABI: [includes.asm](../includes.asm) loads macros first, then constants,
then the optional VC constants. A macro or constant changed there can affect
every object even when no caller has an explicit include. Avoid circular
dependencies and do not depend on labels defined later in an unrelated object.

[layout.link](../layout.link) fixes named sections into ROM0 and ROMX banks.
Section names and placement are therefore compatibility surfaces, not
decoration. The linker combines the objects according to this layout and emits
the ROM plus `.map` and `.sym` files; `rgbfix` then writes cartridge metadata.
Bank placement must be proved from the generated map/symbol output rather than
inferred from a source file's directory.

The primary roots have distinct jobs:

- [home.asm](../home.asm) places the always-addressable ROM0 routines, interrupt
  paths, and shared entry points.
- [main.asm](../main.asm) places most banked engine and data sections.
- [maps.asm](../maps.asm) co-locates map headers, objects, scripts, and block
  binaries into explicit map banks.
- [ram.asm](../ram.asm) declares VRAM, WRAM, SRAM, and HRAM through the files in
  `ram/`.
- `audio.asm`, `text.asm`, and the `gfx/*.asm` roots assemble their respective
  content families.

An `INCLUDE` is textual composition, not a call boundary. Labels, local state,
macro definitions, section placement, and assertions all become part of the
including object.

## Repository boundaries

The directory names describe responsibility, though old engine code sometimes
mixes code and tables inside one bank:

- `home/`: ROM0 routines and integration points used across banks.
- `engine/`: executable game systems grouped by behavior.
- `data/`: authored tables and records consumed by engine code.
- `maps/`: binary block layouts; `data/maps/headers`, `data/maps/objects`, and
  `scripts/` hold the other pieces of a map.
- `text/`: map and system text sources.
- `gfx/` and `audio/`: source assets and their assembly roots.
- `constants/` and `macros/`: repository-wide compile-time ABI.
- `ram/`: memory declarations. These allocate storage; they are not ordinary
  data files.
- `tools/rom_tests/`: host-side models, ROM probes, emulation tests, and
  gameplay journeys. See [TESTING.md](TESTING.md).
- `specs/`: approved design authority, evidence, inventories, and migration
  plans. A spec is not proof that its proposed runtime is active.

When adding content, keep authored values in `data/`, map behavior in
`scripts/`, executable mechanisms in `engine/`, and only genuinely universal
or interrupt-sensitive entry points in `home/`. Preserve existing layout when
the original ROM's address or byte identity is part of a product contract.

## Banks and memory ownership

The CPU directly addresses ROM0 and one switchable ROMX bank. Calls across
banks must use the project's bank-switch/far-call conventions and must restore
the caller's bank. A label being visible to the assembler does not make a
direct `call` safe across banks.

The same rule applies to CGB memory:

- `rSVBK` selects switchable WRAM banks.
- `rVBK` selects tile/attribute VRAM banks.
- interrupt code cannot assume the interrupted routine used the default bank.
- bank-changing helpers must preserve the caller-visible register, stack,
  interrupt, and banking postconditions their call sites require.

Memory declarations in `ram/wram.asm`, `ram/vram.asm`, `ram/sram.asm`, and
`ram/hram.asm` are positional allocations. Aliasing scratch storage is only
safe when lifetimes cannot overlap and tests cover the hostile overlap case.
Never claim unused bytes from a map file or an emulator snapshot alone; confirm
the declaration, linker symbols, and all owners.

The full-color work adds fixed ROM and WRAM reservations in
[constants/full_color_constants.asm](../constants/full_color_constants.asm).
Those reservations and their bank-switch protocol are explained in
[FULL_COLOR_RENDERER.md](FULL_COLOR_RENDERER.md). They are useful examples of
ROM-wide bank discipline, not authority to route unrelated systems through the
renderer.

## Map identity is a positional ABI

[constants/map_constants.asm](../constants/map_constants.asm) defines map IDs
and dimensions in canonical order. The numeric ID indexes several parallel
tables, including:

- `MapHeaderBanks` in `data/maps/map_header_banks.asm`;
- `MapHeaderPointers` in `data/maps/map_header_pointers.asm`;
- map songs, sprite sets, town-map entries, toggleable-object pointers, and
  wild-data pointers; and
- associated content assembled by `maps.asm`.

Changing the order of map constants without changing every indexed authority
silently gives one map another map's data. Duplicate and unused IDs are also
intentional ABI entries. Extend tables in lockstep, preserve their length
assertions, and verify the actual ROM. The same positional warning applies to
other ID-indexed tables such as species, moves, items, tilesets, and sprites.

For the practical map/content procedure, use
[ADDING_CONTENT.md](ADDING_CONTENT.md).

## Product variants and experimental isolation

The Makefile builds separate products from the same roots with compile-time
flags:

| Target | Defining flags | Purpose |
| --- | --- | --- |
| `make yellow` | none | normal ROM |
| `make yellow_debug` | `_DEBUG` | debug ROM |
| `make yellow_vc` | `_YELLOW_VC` | Virtual Console patch product |
| `make yellow_phase2_audit` | `_DEBUG`, `PHASE2_AUDIT` | experimental renderer audit ROM |

Conditional source changes layout and reachability independently for each
product. Experimental runtime belongs behind an explicit product flag until
its release migration is approved. Normal, debug, and VC builds must not gain
an experimental path merely because its module is present in source.

Product isolation is broader than color. Future experiments should follow the
same pattern: a named build, an explicit inclusion guard, fail-closed runtime
activation, and checks proving ordinary products remain unaffected. The
release ROM's reproducibility check remains load-bearing whenever the project
still claims fidelity to the base disassembly.

## Runtime integration boundaries

The original Yellow engine remains the behavioral authority unless a migration
explicitly supersedes one of its resources. Hooks in ROM0, VBlank, map loading,
menus, or battle transitions have a large blast radius because they are shared
by otherwise unrelated content.

### Pre-edit architecture conflict gate

Before changing runtime code, compare the task or pull-request plan with this
manual and the current subsystem manual. Plans govern execution scope; they
MUST NOT override current approved architecture or product truth. If the plan
requires a contradictory owner, data flow, activation path, product claim, or
lifecycle, implementation MUST stop until the operator explicitly decides the
architecture change.

Do not implement the contradiction first and rewrite documentation afterward
to legitimize it. Architecture manuals may be revised only as part of a
separately approved architecture decision, before dependent implementation is
treated as authorized.

Before adding such a hook, establish:

1. the old owner and its exact postconditions;
2. the new owner's resources and activation predicate;
3. entry, exit, reset, interruption, and failure behavior;
4. a bounded timing and memory budget; and
5. evidence from the built ROM and a natural gameplay path.

This ownership-first pattern was made explicit by the full-color initiative,
but it applies to any future replacement engine: audio, scripting, battle
presentation, save migration, or new hardware effects.

## Intended architecture for future work

This section is direction, not a claim about every existing module.

- **Keep one authority per visible or mutable resource.** Adapters may observe
  or translate an existing result; two engines must not concurrently guess at
  the same tiles, sprites, save bytes, or timing.
- **Separate mechanism from content.** Schedulers, transfers, lookup, and
  lifecycle code belong in `engine/`; palettes, mappings, encounters, and map
  records belong in `data/` or the corresponding content directory.
- **Make identity explicit.** Dispatch by authored map, tileset, sprite, or
  effect identity. Arithmetic fallbacks that merely produce legal values hide
  missing content.
- **Bound interrupt work.** Prepare outside VBlank, commit a measured unit
  inside VBlank, defer excess work, and expose the deferral to tests.
- **Fail closed across lifecycle changes.** Generation or ownership tokens
  should invalidate stale work after reset, handoff, cancellation, or reuse.
- **Treat transitions as first-class behavior.** Entry and steady state are not
  enough; menus, connections, battles, saves, resets, and error paths must
  reconstruct or relinquish ownership explicitly.
- **Prove the product, not only the model.** Source assertions and host models
  are useful, but built-ROM probes and natural input-driven journeys decide
  whether the shipped machine behaves.
- **Preserve provenance.** Imported code or content needs a pinned source,
  transformation record, license compatibility, and a testable authority.

The [full-color migration plan](../specs/full-colors/docs/migration-plan.md) is
the most developed application of these principles. Its scheduler and
ownership machinery is retained experimental architecture, not automatically
the foundation of every future feature.

## Change checklist

Before calling an architectural change complete:

1. identify every assembly root and product variant it reaches;
2. identify the ROM/RAM banks and caller-visible machine state it touches;
3. update all positional tables and assertions together;
4. preserve or intentionally migrate the previous owner;
5. test activation, normal operation, exit, reset, and hostile interruption;
6. run the appropriate gates from
   [TESTING.md](TESTING.md); and
7. record what is active now versus merely retained or intended.

Use [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) for the next-day handoff
and review loop.
