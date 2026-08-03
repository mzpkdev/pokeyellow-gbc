# Full-color overworld renderer

Status: proposed

Target: `pokeyellow`

Mechanism reference: `git@github.com:dannye/pokered-gbc.git` commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`

## Goal

Replace Yellow's overworld renderer with an authoritative full-color renderer.
It owns map palettes, BG/window attributes, map transfers, map-backed overlays,
and overworld OAM—including follower Pikachu.

Yellow keeps its existing renderer for battles and standalone screens. The two
renderers exchange ownership at explicit scene boundaries and never write the
same active scene concurrently.

## Product boundary

Included:

- all 25 overworld tilesets;
- map entry, reload, scrolling, connections, and animated tiles;
- dialogue and transient overlays that reveal the map when closed;
- player, follower Pikachu, NPCs, and overworld objects; and
- deterministic handoff to and from Yellow-owned screens.

Excluded:

- battle rendering and animations;
- title, intro, credits, and Pokémon picture screens;
- party, status, Pokédex, trade, slots, printer, and link presentation; and
- Pikachu's Beach and Surfing Pikachu.

See [Scope and ownership boundary](docs/scope.md).

## Core decision

The active renderer is exactly one of:

```text
RENDERER_FULL_COLOR_OVERWORLD
RENDERER_YELLOW
```

Map-backed dialogue and transient menus remain part of the full-color scene.
Standalone screens reached from the map receive Yellow ownership before entry
to destination initialization. Only an actual Yellow-to-full-color overworld
boundary rebuilds the overworld from authoritative map data; it never restores
stale VRAM. Yellow-to-Yellow nested, boot, reset, and error transitions do not
invent a map return.

This makes the overworld a complete architecture swap, not a hybrid overlay.
The normative owner and return behavior is defined by
[R1.1](docs/requirements.md#r1-renderer-ownership) and
[R2.7, R2.10, R2.11, R2.12, and R2.13](docs/requirements.md#r2-generation-handoff-reset-and-reconstruction).

## Reference implementation

The mechanism reference is `git@github.com:dannye/pokered-gbc.git` at commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`. Its palette buffers,
shade transforms, VBK0/VBK1 transfers, tile attribute lookup, VBlank
scheduling, and overworld OAM mapping are mechanism evidence. Donor palette,
mapping, roof, OAM, and content values outside the accepted OVERWORLD slice are
non-authoritative candidate organization or artistic evidence and are
independently authored and validated for Yellow. Its static-screen restoration,
MBC1 layout, banks, WRAM
representation, and non-overworld coloring are not inherited.

The ten mechanism paths are `color/init.asm`, `color/wram.asm`,
`color/loadpalettes.asm`, `color/refreshmaps.asm`, `color/vblank.asm`,
`color/super_palettes.asm`, `color/color.asm`, `color/sprites.asm`,
`color/boulder.asm`, and `color/ssanne.asm`. They are distinct from the five
payload authorities: `color/data/map_palettes.asm`,
`color/data/map_palette_sets.asm`, `color/data/roofpalettes.asm`,
`color/data/map_palette_constants.asm`, and `color/tilesets/overworld.asm`.
Only those five paths authorize the frozen OVERWORLD palette and attribute
bytes; the broader mechanism inventory does not.

## Mandatory prerequisite

No production renderer port begins until the AI-iteration Gate 0 suite exists,
validates itself, and passes against the baseline debug ROM.
This is the [R11.6](docs/requirements.md#r11-diagnostic-mode) requirement and
[AC-G0-01](docs/acceptance-criteria.md#gate-0-prerequisite) completion outcome.

Gate 0 includes:

- pinned PyBoy/Python test dependencies;
- deterministic scenario and timeout handling;
- semantic state snapshots;
- model-generated ownership sequences;
- renderer-owner and writer tracing;
- source and built-ROM inventory tooling proven on the initial map-entry slice;
- bank-torture tests;
- a complete LLM-viewable pipeline for lossless screenshots, bounded frame
  strips, annotated contact sheets, localized image diffs, and a versioned
  manifest linked to semantic snapshots and writer traces;
- mutation tests proving the implemented gates fail when invariants are violated;
- stable local commands and blocking CI execution.

Gate 0 does not exhaustively inventory untouched Yellow paths, select a future
queue ABI or WRAM layout, produce renderer timing rows, or execute the hostile
renderer slice. Each renderer phase closes the inventory rows it touches before
the path becomes reachable and records representation and timing evidence when
the corresponding implementation exists. The first renderer slice activates
the unmistakable canary palette and hostile scenario, then applies canary
visual acceptance and evidence through the visual pipeline completed by Gate 0
before content expansion.

Details:

- [Prerequisite gates](docs/prerequisite-gates.md)
- [AI iteration harness](docs/ai-iteration-harness.md)

## Success

The project is done when:

1. The full-color architecture exclusively renders every overworld frame.
2. Yellow exclusively renders every excluded scene.
3. Map tiles and attributes use paired, serialized transfer paths.
4. Overlays and scene handoffs pass deterministic semantic tests.
5. All bank, ownership, timing, and writer gates pass.
6. The three architecture stress cases pass before content expansion.
7. Yellow's old overworld ownership path can be deleted.

See [Acceptance criteria](docs/acceptance-criteria.md).
The authoritative aggregate outcome is
[AC-DONE-01](docs/acceptance-criteria.md#definition-of-done).

## Document authority

| Question | Authority |
|---|---|
| included scenes | `docs/scope.md` |
| mandatory behavior and vocabulary | `docs/requirements.md` |
| completion outcomes | `docs/acceptance-criteria.md` |
| conforming realization | `docs/architecture.md` |
| audited writers/scenes | `docs/replacement-inventory.md` |
| requirement-to-evidence mapping | `docs/verification-plan.md` |

Dependent documents cite the authority; they do not redefine it.

## Document map

### Contract

- [Scope and ownership boundary](docs/scope.md)
- [Normative requirements](docs/requirements.md)
- [Acceptance criteria](docs/acceptance-criteria.md)

### Design

- [Architecture](docs/architecture.md)
- [Replacement inventory](docs/replacement-inventory.md)
- [Why the previous hybrid failed](docs/failed-hybrid-analysis.md)

### Execution

- [Prerequisite gates](docs/prerequisite-gates.md)
- [AI iteration harness](docs/ai-iteration-harness.md)
- [Migration plan](docs/migration-plan.md)
- [Verification plan](docs/verification-plan.md)
