# Acceptance criteria

## Gate 0 prerequisite

All prerequisite gates in [prerequisite-gates.md](prerequisite-gates.md) exist,
validate themselves, and pass before production renderer code begins.

## Overworld

- All 25 tilesets use correct per-tile attributes.
- Initial entry, reload, scrolling, and connections remain colored.
- Dialogue and map-backed menus do not erase or smear attributes.
- Roofs, overrides, animated tiles, and field effects remain correct.
- Player, follower Pikachu, NPCs, and objects use deliberate OBJ palettes.
- No one-frame stale, white, black, or mismatched state is visible.

## Handoffs

- Every standalone screen is entered under Yellow ownership.
- Excluded scenes remain functionally unchanged.
- Returning reconstructs the overworld correctly.
- Repeated and interrupted transitions do not leak ownership or jobs.

## Technical

- Release, debug, and VC ROMs build with warnings as errors.
- Header validation confirms CGB-only.
- Static hardware-writer inventory passes.
- Runtime owner/writer assertions pass.
- Semantic snapshots match at all required checkpoints.
- Seeded ownership-model sequences match the reference state machine.
- Forced bank-state and interrupt tests pass.
- Measured LCD, VBlank, and OAM work fits timing or safely defers.
- Mutation tests prove critical gates detect their target failures.
- Named screenshots and frame strips are available for LLM visual inspection.

## Architecture expansion gate

Before scaling to all tilesets and real color content, the implementation passes
the three stress cases defined by the migration plan: combined renderer
pressure, handoff reconstruction, and interrupted connection transfer.

## Removal

- Yellow's old overworld tint and attribute path is unreachable and deleted.
- No failed-hybrid restoration hook remains.
- Transitional adapters have explicit justification or are removed.
- Yellow code required by excluded scenes remains intact.

## Definition of done

RGB architecture exclusively renders every overworld frame, Yellow exclusively
renders excluded scenes, handoffs are deterministic, and all prerequisite,
stage, soak, timing, and regression gates pass.
