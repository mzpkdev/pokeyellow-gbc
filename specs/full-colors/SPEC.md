# Full-color overworld renderer

Status: proposed

Target: `pokeyellow`

Mechanism reference: `Pokemon_GBC_Celebrations` commit
`bf823bc15d75ba8335ce2c9418d2eb65897bb878`

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

The mechanism reference is `Pokemon_GBC_Celebrations` at commit
`bf823bc15d75ba8335ce2c9418d2eb65897bb878`. Its palette buffers,
shade transforms, VBK0/VBK1 transfers, tile attribute lookup, VBlank
scheduling, and overworld OAM mapping are mechanism evidence. Donor palette,
mapping, roof, OAM, and content values are non-authoritative candidate
organization or artistic evidence and are independently authored and
validated for Yellow. Its static-screen restoration, MBC1 layout, banks, WRAM
representation, and non-overworld coloring are not inherited.

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
