# Full-color overworld renderer

Status: proposed

Target: `pokeyellow`

Mechanism reference: `git@github.com:dannye/pokered-gbc.git` commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`

## Goal

Add a persistent `COLOR MODE: COLOR/YELLOW` preference. Color may become the
authoritative renderer for ordinary presentation of the supported map slice:
the 34 city/route maps whose header selects `OVERWORLD` and conventional
interiors using `REDS_HOUSE_1` through `FACILITY`, except `FOREST`, `SHIP_PORT`,
and `CAVERN` (19 tilesets and 162 maps),
including their map palettes, paired tiles/attributes, animated tiles, field
replacements, and overworld OAM—including follower Pikachu.

Yellow keeps its existing renderer for boot/reset, overlays, dialogue, menus,
battles, standalone screens, unsupported maps, and all maps under Yellow
preference. The preference is policy input only. The two renderers exchange
exclusive ownership at explicit boundaries and never write concurrently.

## Product boundary

Included:

- ordinary base-map presentation for the supported outdoor and conventional-
  interior map slice;
- map entry, reload, scrolling, their connection, animated tiles, and field replacements;
- complete Color-to-Yellow and Yellow-to-Color handoffs around forced-Yellow contexts;
- player, follower Pikachu, NPCs, and overworld objects; and
- deterministic handoff to and from Yellow-owned screens.

Excluded:

- battle rendering and animations;
- title, intro, credits, and Pokémon picture screens;
- party, status, Pokédex, trade, slots, printer, and link presentation; and
- Pikachu's Beach and Surfing Pikachu.

Color authoring for the remaining tilesets and production Color overlays remain future work,
not release gates for this bounded product.

See [Scope and ownership boundary](docs/scope.md).

## Core decision

The active renderer is exactly one of:

```text
RENDERER_FULL_COLOR_OVERWORLD
RENDERER_YELLOW
```

Production ownership is defined by the pure decision
`effective_owner(preference, lifecycle, map)`: it returns Color if and only if
preference is Color, lifecycle is ordinary map presentation, and the map is in
the supported outdoor/conventional-interior slice; otherwise it returns Yellow. `OVERWORLD_OVERLAY` is reserved
and unreachable. Every real owner change closes admission, resolves departing
work, advances generation once, selects the destination, reconstructs every
destination authority from fresh logical state, crosses one barrier, and then
reopens admission. Same-owner decisions preserve generation. Reset and soft
reset from Color complete the same Color-to-Yellow safety contract.

This makes each eligible base-map interval a complete exclusive-owner route,
not a hybrid overlay or a second writer layered onto Yellow.
The normative owner and return behavior is defined by
[R1.1](docs/requirements.md#r1-renderer-ownership) and
[R2.7, R2.10, R2.11, R2.12, and R2.13](docs/requirements.md#r2-generation-handoff-reset-and-reconstruction).

## Reference implementation

The mechanism reference is `git@github.com:dannye/pokered-gbc.git` at commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`. Its palette buffers,
shade transforms, VBK0/VBK1 transfers, tile attribute lookup, VBlank
scheduling, and overworld OAM mapping are mechanism evidence. Donor palette,
mapping, roof, OAM, and content values outside the accepted map slice are
non-authoritative candidate organization or artistic evidence and are
independently authored and validated for Yellow. Its static-screen restoration,
MBC1 layout, banks, WRAM
representation, and non-overworld coloring are not inherited.

The ten mechanism paths are `color/init.asm`, `color/wram.asm`,
`color/loadpalettes.asm`, `color/refreshmaps.asm`, `color/vblank.asm`,
`color/super_palettes.asm`, `color/color.asm`, `color/sprites.asm`,
`color/boulder.asm`, and `color/ssanne.asm`. They are distinct from the payload
authorities: `color/data/map_palettes.asm`,
`color/data/map_palette_sets.asm`, `color/data/map_palette_assignments.asm`,
`color/data/roofpalettes.asm`, `color/data/map_palette_constants.asm`,
`color/tilesets/overworld.asm`, and the admitted interior
`color/tilesets/*.asm` tables.
Only the pinned payload paths listed in the replacement inventory authorize
the accepted outdoor/conventional-interior palette and attribute bytes; the
broader mechanism inventory does not. The donor loader supplies the two
map-specific override locations for `CELADON_MART_ROOF` and
`CELADON_MART_1F`; their palette identities remain grounded in
`map_palette_constants.asm`.

## Mandatory evidence prerequisite

Full-color evidence capture remains deterministic across two independent
executions. Renderer scope does not expand while an activated inventory,
visual, mutation, timing, or gameplay contract is red. This is the
[R11.6](docs/requirements.md#r11-diagnostic-mode) requirement and
[AC-EVIDENCE-01](docs/acceptance-criteria.md#evidence-prerequisite) completion
outcome.

The baseline verification contracts include:

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
- mutation tests proving the implemented contracts fail when invariants are violated;
- stable local commands and blocking CI execution.

The baseline verification contracts do not exhaustively inventory untouched
Yellow paths, select a future queue ABI or WRAM layout, produce renderer timing
rows, or execute the hostile renderer slice. Each renderer phase closes the
inventory rows it touches before the path becomes reachable and records
representation and timing evidence when the corresponding implementation
exists. The first renderer slice activates the unmistakable canary palette and
hostile scenario, then applies canary visual acceptance and evidence through
the established visual pipeline before content expansion.

Details:

- [Prerequisite contracts](docs/prerequisite-gates.md)
- [AI iteration harness](docs/ai-iteration-harness.md)

## Success

The project is done when:

1. The exhaustive preference × lifecycle × map matrix selects exactly one owner per cell.
2. Color exclusively renders ordinary presentation of the supported outdoor and conventional-interior maps only when preference is Color; Yellow exclusively renders every other cell.
3. Map tiles and attributes use paired, serialized transfer paths.
4. Forced-Yellow overlays and complete bidirectional/reset handoffs pass deterministic semantic tests.
5. All bank, ownership, timing, and writer gates pass.
6. The three architecture stress cases pass before content expansion.
7. Required Yellow paths remain, while only obsolete competing ownership is deleted.

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
