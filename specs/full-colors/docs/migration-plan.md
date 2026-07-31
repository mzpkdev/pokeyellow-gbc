# Migration plan

## Phase 0: mandatory iteration foundation

Implement [Gate 0](prerequisite-gates.md) using the existing
[PyBoy/Python harness](ai-iteration-harness.md).

Allowed work:

- tests and fixtures;
- debug-only observability;
- hardware-writer inventory;
- semantic snapshot and diff support;
- model-based ownership sequences;
- bank-torture controls;
- deterministic hostile baseline scenario;
- screenshot, frame-strip, and contact-sheet artifacts;
- timing instrumentation and Yellow baselines; and
- mutation tests for the gates.

Production renderer code is not allowed in this phase.

Exit gate: every Gate 0 item validates itself and passes twice with identical
semantic output.

## Phase 1: ownership foundation

- Make the ROM CGB-only.
- Add bank-2 renderer WRAM.
- Add both renderer owners and ownership generation.
- Preserve banks in renderer-capable interrupts.
- Add job cancellation behavior.
- Keep visuals unchanged.

Exit gate: ownership-model sequences agree with debug-ROM traces, and
bank-torture, mutation, and baseline semantic tests pass.

## Phase 2: diagnostic vertical slice

- Add the unmistakable eight-palette canary mode.
- Add transformed buffers and shade remapping.
- Pair initial, horizontal, vertical, connection, and overlay attributes for
  one diagnostic tileset.
- Route wrappers by owner.
- Exercise follower Pikachu, several NPCs, and animated terrain.
- Implement one real standalone-screen handoff and return.
- Run with non-default banks and representative interrupt pressure.
- Capture semantic checkpoints, screenshots, and bounded frame strips.
- Measure LCD, VBlank, transfer, palette, and OAM work.

Exit gate: the hostile scenario passes semantic, model, visual, bank, ownership,
and initial timing checks without restoration hooks.

Do not expand the architecture until this gate is green.

## Phase 3: complete transfer architecture

- Generalize the tile attribute lookup.
- Cover every map load/reload path.
- Cover all connections and transfer destinations.
- Cover dialogue and transient overlays.
- Cover animated and replaced tiles.

Exit gate: transfer matrix, bank tests, ownership trace, focused soak, and
updated worst-case timing measurements pass.

## Phase 4: overworld OAM

- Add picture-ID palette assignments.
- Insert palette bits after Yellow's final tile calculation.
- Preserve follower Pikachu VRAM offsets.
- Cover field objects and transient effects.

Exit gate: maximum-NPC, player, follower Pikachu, priority, and field-object
tests pass without wobble, bank leakage, or timing regression.

## Phase 5: architecture stress gate

Prove these cases before scaling real color content:

1. **Combined pressure:** simultaneous scrolling, animated terrain, palette
   work, maximum representative overworld OAM, and interrupt pressure.
2. **Handoff reconstruction:** a standalone screen entered immediately after
   map activity, followed by a complete map return with no stale generation or
   restoration hook.
3. **Interrupted connection:** a connection transfer reaches an allowed
   interrupt or insufficient-time boundary and either commits atomically or
   defers as a whole.

For each case, require semantic state, ownership-model agreement, writer trace,
bank restoration, timing measurements, and LLM-reviewed screenshots/frame
strips.

Exit gate: all three cases pass repeatedly with deterministic artifacts.

Do not begin tileset content expansion until this gate is green.

## Phase 6: tileset content

- Add all 25 palette sets and `$60` assignment tables.
- Add native Beach House data.
- Add roofs and reviewed map overrides.
- Verify animated tile compatibility.

Exit gate: tileset atlas, semantic attribute snapshots, and visual review pass.

## Phase 7: complete handoff coverage

- Handoff before every standalone screen.
- Reconstruct the map on every return path.
- Stress rapid, repeated, interrupted, and nested transitions.
- Reject stale-generation jobs.

Exit gate: full handoff matrix and 100-cycle soak tests pass.

## Phase 8: delete old overworld ownership

- Remove Yellow's old overworld tint and attribute path.
- Remove transitional overworld adapters.
- Remove restoration behavior.
- Enforce owner-gated hardware writers in CI.
- Retain Yellow code required by excluded scenes.

Exit gate: old overworld ownership is unreachable and excluded-scene
regressions remain green.

## Phase 9: timing and release hardening

- Reconfirm LCD, VBlank, map streaming, palette upload, and OAM budgets.
- Verify safe missed-deadline behavior.
- Run the complete multi-frame suite.
- Verify release, debug, and VC builds.

Exit gate: all [acceptance criteria](acceptance-criteria.md) pass.

## Iteration rule

Run the fastest relevant gate after each change. A red prerequisite,
ownership, bank, or semantic-state gate stops renderer expansion until fixed.

Each implementation PR must:

- address one phase or bounded transfer path;
- state owner transitions;
- include a machine-checkable test;
- avoid unrelated non-overworld work; and
- remain bootable and diagnosable.
