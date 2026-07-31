# Migration plan

## Phase 0: mandatory iteration foundation

Implement [Gate 0](prerequisite-gates.md) using the existing
[PyBoy/Python harness](ai-iteration-harness.md).

Allowed work:

- tests and fixtures;
- debug-only observability;
- hardware-writer inventory;
- semantic snapshot and diff support;
- bank-torture controls;
- deterministic baseline scenarios; and
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

Exit gate: ownership, bank-torture, mutation, and baseline semantic tests pass.

## Phase 2: diagnostic vertical slice

- Add eight diagnostic BG and OBJ palettes.
- Add transformed buffers and shade remapping.
- Pair initial, horizontal, vertical, connection, and overlay attributes for
  one diagnostic tileset.
- Route wrappers by owner.
- Implement one real standalone-screen handoff and return.

Exit gate: the complete diagnostic scenario passes semantic checkpoints without
restoration hooks.

Do not expand to real palette content until this gate is green.

## Phase 3: complete transfer architecture

- Generalize the tile attribute lookup.
- Cover every map load/reload path.
- Cover all connections and transfer destinations.
- Cover dialogue and transient overlays.
- Cover animated and replaced tiles.

Exit gate: transfer matrix, bank tests, ownership trace, and focused soak pass.

## Phase 4: tileset content

- Add all 25 palette sets and `$60` assignment tables.
- Add native Beach House data.
- Add roofs and reviewed map overrides.
- Verify animated tile compatibility.

Exit gate: tileset atlas and semantic attribute snapshots pass.

## Phase 5: overworld OAM

- Add picture-ID palette assignments.
- Insert palette bits after Yellow's final tile calculation.
- Preserve follower Pikachu VRAM offsets.
- Cover field objects and transient effects.

Exit gate: maximum-NPC, player, follower Pikachu, priority, and field-object
tests pass without wobble or bank leakage.

## Phase 6: complete handoff coverage

- Handoff before every standalone screen.
- Reconstruct the map on every return path.
- Stress rapid, repeated, interrupted, and nested transitions.
- Reject stale-generation jobs.

Exit gate: full handoff matrix and 100-cycle soak tests pass.

## Phase 7: delete old overworld ownership

- Remove Yellow's old overworld tint and attribute path.
- Remove transitional overworld adapters.
- Remove restoration behavior.
- Enforce owner-gated hardware writers in CI.
- Retain Yellow code required by excluded scenes.

Exit gate: old overworld ownership is unreachable and excluded-scene
regressions remain green.

## Phase 8: timing and release hardening

- Measure LCD, VBlank, map streaming, palette upload, and OAM budgets.
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
