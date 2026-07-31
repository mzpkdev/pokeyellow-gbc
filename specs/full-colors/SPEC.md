# Full-color overworld renderer

Status: proposed

Target: `pokeyellow`

Donor: the overworld architecture from `pokemon-rgb`

## Goal

Replace Yellow's overworld renderer with an authoritative RGB-style renderer.
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
Standalone screens receive ownership before initialization. Returning from one
rebuilds the overworld from authoritative map data; it never restores stale
VRAM.

This makes the overworld a complete architecture swap, not a hybrid overlay.

## Mandatory prerequisite

No production renderer port begins until the AI-iteration Gate 0 suite exists,
validates itself, and passes against the baseline debug ROM.

Gate 0 includes:

- pinned PyBoy/Python test dependencies;
- deterministic scenario and timeout handling;
- semantic state snapshots;
- model-generated ownership sequences;
- renderer-owner and writer tracing;
- hardware-writer inventory checks;
- bank-torture tests;
- an LLM-viewable screenshot and frame-strip artifact pipeline;
- mutation tests proving the gates fail when invariants are violated; and
- a hostile diagnostic vertical slice ready to receive the new renderer.

The first renderer slice must then activate an unmistakable canary palette,
pass early timing checks, and clear the three architecture stress cases before
content expansion.

Details:

- [Prerequisite gates](docs/prerequisite-gates.md)
- [AI iteration harness](docs/ai-iteration-harness.md)

## Success

The project is done when:

1. RGB architecture exclusively renders every overworld frame.
2. Yellow exclusively renders every excluded scene.
3. Map tiles and attributes use paired, serialized transfer paths.
4. Overlays and scene handoffs pass deterministic semantic tests.
5. All bank, ownership, timing, and writer gates pass.
6. The three architecture stress cases pass before content expansion.
7. Yellow's old overworld ownership path can be deleted.

See [Acceptance criteria](docs/acceptance-criteria.md).

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

If documents conflict, `scope.md` defines the product boundary,
`requirements.md` defines mandatory behavior, and `acceptance-criteria.md`
defines completion.
