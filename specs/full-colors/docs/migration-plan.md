# Migration plan

## Execution evidence rule

This documentation revision defines future execution records; it does not
claim that Gate 0 artifacts, measurements, concrete inventory rows, or checks
already exist. Every phase retains the evidence block below in its execution
record:

- **Requirements:** concrete `R…` sub-IDs changed or established by the phase.
- **Inventory:** concrete `WR-…`, `SC-…`, and `MU-…` rows touched by the phase.
  Phase 0 fills baseline rows from completed discovery before exit. Phases 1–9
  cite those closed IDs and may add a concrete planned row atomically with a
  new symbol or directed edge; the row is reviewed and source plus built-ROM
  closure reruns before the path becomes reachable or the phase proceeds.
  `none`, category names, wildcards, and placeholder IDs are not permitted
  where a row is touched.
- **Acceptance:** concrete `AC-…` IDs the phase must close.
- **Evidence:** named future checks and artifacts, including concrete
  `CHK-…` IDs and timing-row keys when the phase changes timed work.
- **Exit gate:** an observable evidence condition. Later phases may not begin
  while it is red.

Each implementation PR names its affected requirement and inventory IDs,
commit units, owner transitions, timing-row keys, and concrete `CHK-…` checks.

## Phase 0: mandatory iteration foundation

Implement [Gate 0](prerequisite-gates.md) using the existing
[PyBoy/Python harness](ai-iteration-harness.md).

Allowed work:

- tests and fixtures;
- debug-only observability;
- source and built-ROM writer, scene, and mutation discovery;
- assignment of concrete `WR-…`, `SC-…`, and `MU-…` IDs;
- complete population and review of every inventory field;
- semantic snapshot and diff support;
- model-based ownership sequences;
- bank-torture controls;
- deterministic hostile baseline scenario;
- screenshot, frame-strip, and contact-sheet artifacts;
- timing instrumentation and Yellow baselines; and
- mutation tests for the gates.

Production renderer code is not allowed in this phase.

Phase 0 runs source search and built-ROM symbol/disassembly reachability until
no reachable baseline writer, lifecycle, directed transition, or visible-map
mutation is unclassified. It then produces only harness, schema,
self-mutation, baseline-inventory, representation-selection, and baseline
timing-instrument-readiness artifacts and validates them twice with identical
semantic, trace, mapping, and visual-manifest outputs. It does not accept
renderer request, commit, return, overlay, OAM, or operation-timing behavior.

**Requirements:** The execution record cites `R1.7`, `R1.26`, `R3.3`,
`R10.3`, `R10.8`, `R11.3`, `R11.4`, `R11.5`, `R11.6`, `R12.6`, and
`R12.8`.

**Inventory:** Before Phase 0 exits, this execution record contains every baseline
concrete `WR-…`, `SC-…`, and `MU-…` ID assigned by completed source and
built-ROM discovery; every required field is populated and every row is
reviewed.

**Acceptance:** The execution record closes `AC-G0-01`, `AC-INV-01`,
`AC-TRACE-01`, `AC-TECH-03`, and `AC-TECH-09`.

**Evidence:** Named baseline-inventory-closure, representation-selection,
contract-schema, baseline timing-instrument-readiness, self-mutation,
semantic-snapshot, visual-manifest, and traceability checks; renderer oracles
are model/schema self-tests only, and the executed record supplies their
concrete `CHK-…` IDs.

**Exit gate:** All three baseline inventories are populated, reviewed, closed
by source and built-ROM evidence, and contain no unclassified reachable item;
the harness/schema/self-mutation and baseline timing-instrument-readiness
artifacts pass twice with identical output, without production renderer code
or renderer acceptance claims.

## Phase 1: ownership foundation

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Make the ROM CGB-only.
- Add renderer WRAM at the placement selected by Gate 0 evidence.
- Add both renderer owners and ownership generation.
- Preserve banks in renderer-capable interrupts.
- Add job cancellation behavior.
- Keep visuals unchanged.

**Requirements:** The execution record cites `R1.1`, `R1.2`, `R1.3`, `R1.4`,
`R1.5`, `R1.6`, `R1.19`, `R1.20`, `R1.24`, `R1.25`, `R2.1`, `R2.2`, `R2.3`,
`R2.4`, `R2.8`, `R2.9`, `R3.1`, `R3.2`, `R3.3`, `R3.4`, `R3.5`, `R3.6`,
`R4.1`, `R4.2`, `R4.3`, `R4.4`, and `R4.5`.

**Inventory:** When executed, list every concrete closed-inventory writer,
scene-boundary, reset, handoff, bank, startup, and job-lifecycle `WR-…`,
`SC-…`, and `MU-…` row touched by the foundation.

**Acceptance:** The execution record closes `AC-OWN-01`, `AC-JOB-01`,
`AC-TECH-02`, `AC-TECH-04`, `AC-TECH-06`, and `AC-TECH-07`.

**Evidence:** Named ownership-model, hostile-writer, handoff/reset,
bank-torture, cancellation, baseline-semantic, and mutation checks; execution
records their concrete `CHK-…` IDs. The cited handoff/reset cases are progress
toward `AC-HO-01` and `AC-HO-04`, not closure of their universally quantified
directed-edge coverage.

**Exit gate:** Ownership-model sequences agree with debug-ROM traces, and
bank-torture, cancellation, mutation, handoff, and baseline semantic evidence
is green for every cited closed-inventory row.

## Phase 2: diagnostic vertical slice

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Add the unmistakable eight-palette canary mode.
- Add transformed buffers and shade remapping.
- Pair initial, horizontal, vertical, connection, and overlay attributes for
  one diagnostic tileset.
- Route wrappers by owner.
- Exercise follower Pikachu, several NPCs, and animated terrain.
- Implement one real standalone-screen handoff and return.
- Run runtime pressure tests for exactly the Gate 0-selected policy of each
  request class; required visible-state work defers and retries, and any final
  capacity rejection proves its optional/supersedable caller fallback.
- Run with non-default banks and representative interrupt pressure.
- Capture semantic checkpoints, screenshots, and bounded frame strips.
- Measure LCD, VBlank, transfer, palette, and OAM work.
- Exercise missing, out-of-range, and unmapped overworld picture identities;
  prove OBJ palette 0, preserved attribute bits 3–7, and required diagnostic
  fallback evidence.

**Requirements:** The execution record cites `R1.8`, `R1.9`, `R1.10`,
`R1.11`, `R1.12`, `R1.13`, `R1.14`, `R1.15`, `R1.16`, `R1.17`, `R1.18`,
`R1.21`, `R1.22`, `R1.23`, `R1.27`, `R1.28`, `R2.5`, `R2.6`, `R2.7`,
`R2.10`, `R2.11`, `R2.12`, `R2.13`, `R5.1`, `R5.2`, `R5.3`, `R5.4`,
`R5.6`, `R5.7`, `R5.8`, `R6.4`, `R6.5`, `R6.6`, `R6.7`, `R6.8`, `R6.9`,
`R6.10`, `R6.11`, `R9.1`, `R9.2`, `R9.3`, `R9.4`, `R10.3`, `R10.4`,
`R11.1`, and `R11.2`.

**Inventory:** When executed, list every concrete baseline or atomically added
`WR-…`, `SC-…`, and `MU-…` row exercised by the hostile diagnostic slice,
including its one proven map-to-Yellow edge, proven Yellow-to-map edge, and
OAM fallback writers/mutations; rerun source plus built-ROM closure before
either new path becomes reachable.

**Acceptance:** The execution record closes `AC-REQUEST-01`,
`AC-COMMIT-01`, `AC-OVERLAY-01`, `AC-OAM-01`, `AC-TECH-05`,
`AC-TECH-06`, `AC-TECH-08`, and `AC-TECH-10`. This is the first phase that
closes `AC-TECH-05`, using actual completed-resource and reconstruction
states after renderer activation.

**Evidence:** Named hostile-slice request-pressure, canary, overlay-oracle,
reconstruction-poison, presentation-barrier, five-active-frame, OAM-fallback,
semantic, visual, owner, bank, and numeric timing checks; execution records
their concrete `CHK-…` IDs and timing-row keys. Its one proven pair of
directed boundaries is slice evidence toward `AC-HO-01`, `AC-HO-03`,
`AC-HO-04`, `AC-RETURN-01`, and `AC-STRESS-02`; it does not close any of
those global criteria.

**Exit gate:** The hostile scenario passes exact request, semantic, model,
visual, bank, ownership, reconstruction, atomicity, OAM fallback, and numeric
timing evidence without restoration hooks.

Do not expand the architecture until this gate is green.

## Phase 3: complete palette and transfer architecture

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Generalize the tile attribute lookup.
- Complete the overworld palette/shade pipeline for fades, flashes, white,
  black, and poison effects.
- Cover every map load/reload path.
- Cover all connections and transfer destinations.
- Cover dialogue and transient overlays.
- Cover animated and replaced tiles.
- Make every overlay request authoritative for destination BG/window selector,
  map identity, tileset identity, world-coordinate transform, override set,
  and preserved source/destination/world mapping.

**Requirements:** The execution record cites `R5.5`, `R6.1`, `R6.3`, `R6.4`,
`R6.5`, `R6.6`, `R6.7`, `R6.8`, `R6.9`, `R6.10`, `R6.11`, `R6.12`,
`R7.1`, `R7.2`, `R7.3`, `R7.4`, `R10.4`, `R10.5`, and `R10.6`.

**Inventory:** When executed, list and close every concrete paired-transfer
and palette-effect `MU-…` row and each `WR-…` row it reaches for fades,
flashes, white, black, poison, load/reload, both scroll axes, four connections,
row/column/rectangle/third-screen transfers, overlays, alternate destinations,
animation, and field replacement.

**Acceptance:** The execution record closes `AC-COMMIT-01`,
`AC-OVERLAY-01`, `AC-OW-02`, `AC-OW-03`, `AC-OW-06`, `AC-STRESS-03`,
`AC-TECH-05`, and `AC-TECH-08`.

**Evidence:** Named fade/flash/white/black/poison semantic palette snapshots
and frame strips, paired-transfer matrix, overlay-oracle, forced-boundary,
bank, ownership-trace, focused-soak, and numeric worst-case timing checks;
execution records their concrete `CHK-…` IDs and timing-row keys. Transfer
and override-precedence coverage in this phase is evidence toward
`AC-OW-04`, but that criterion does not close until Phase 6 supplies its
roof, override, animation, and replacement content. Transfer coverage in this
phase does not close any globally quantified handoff or return criterion.

**Exit gate:** Every cited paired-transfer and palette-effect `MU-…` and
reached `WR-…` row is closed, and the effect semantics and frame strips plus
transfer matrix, atomicity, bank, ownership, soak, and numeric timing evidence
pass.

## Phase 4: overworld OAM

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Add picture-ID palette assignments.
- Insert palette bits after Yellow's final tile calculation.
- Preserve follower Pikachu VRAM offsets.
- Cover field objects and transient effects.

**Requirements:** The execution record cites `R9.1`, `R9.2`, `R9.3`, `R9.4`,
`R9.5`, `R9.6`, `R9.7`, `R9.8`, `R9.9`, `R10.2`, `R10.4`, and `R10.6`.

**Inventory:** When executed, list and close every concrete shadow-OAM
lifecycle, hardware-OAM, `rDMA` source/launch/wait `WR-…` row and every
overworld OAM build, palette-map, sort/copy, invalidate, DMA, and
LCD-off/reset/handoff `MU-…` row touched.

**Acceptance:** The execution record closes `AC-OAM-01`, `AC-OW-05`,
`AC-OW-06`, `AC-TECH-04`, `AC-TECH-05`, `AC-TECH-07`, and `AC-TECH-08`.

**Evidence:** Named maximum-NPC, player, follower, final-picture, priority,
field-object, shadow-to-hardware DMA, fallback, bank, wobble, and numeric
timing checks; execution records their concrete `CHK-…` IDs and timing-row
keys.

**Exit gate:** Every cited shadow-OAM, hardware-OAM, and `rDMA` `WR-…`/`MU-…`
row is closed, and OAM identity, fallback, complete-DMA, bank, visual-stability,
and numeric timing evidence passes.

## Phase 5: architecture stress gate

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

Prove these cases before scaling real color content:

1. **Combined pressure:** simultaneous scrolling, animated terrain, palette
   work, maximum representative overworld OAM, and interrupt pressure.
2. **Handoff reconstruction:** a standalone screen entered immediately after
   map activity, followed by a complete map return with no stale generation or
   restoration hook.
3. **Interrupted connection:** force insufficient budget at every pre-visible
   preparation and revalidation boundary; the transfer defers before
   `COMMITTING`, while a visible commit that reserved its measured worst-case
   budget completes without arbitrary interruption. Interrupt a mid-operation
   write only when its destination is inactive or the LCD is off.

For each case, require semantic state, ownership-model agreement, writer trace,
bank restoration, timing measurements, and LLM-reviewed screenshots/frame
strips.

Each case records complete numeric timing rows, proves `defer threshold + 1`
whole-unit deferral at every pre-visible boundary, and proves reserved-budget
completion after visible `COMMITTING` begins.

**Requirements:** The execution record cites `R1.15`, `R1.16`, `R1.21`,
`R1.22`, `R1.23`, `R1.24`, `R1.25`, `R1.27`, `R1.28`, `R2.10`, `R2.11`,
`R2.12`, `R2.13`, `R7.1`, `R7.3`, `R7.4`, `R10.4`, `R10.5`, `R10.8`,
`R10.9`, and `R10.10`.

**Inventory:** When executed, list every concrete closed-inventory `WR-…`,
`SC-…`, and `MU-…` row reached by combined pressure, standalone handoff
reconstruction, and interrupted connection transfer.

**Acceptance:** The execution record closes `AC-STRESS-01`, `AC-STRESS-03`,
`AC-REQUEST-01`, `AC-JOB-01`, `AC-COMMIT-01`, and `AC-TIME-01`.

**Evidence:** Named combined-pressure, poisoned-return reconstruction,
interrupted-connection, request-accounting, owner-model, writer-trace, bank,
atomicity, semantic, visual, and complete numeric timing checks; execution
records their concrete `CHK-…` IDs and timing-row keys. The named
poisoned-return case is stress progress toward `AC-STRESS-02` and
`AC-RETURN-01`, not exhaustive closure.

**Exit gate:** All three named architecture stress cases pass repeatedly with
deterministic artifacts, positive numeric margins, and threshold-plus-one
whole-unit deferral for every timed path.

Do not begin tileset content expansion until this gate is green.

## Phase 6: tileset content

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Independently author and validate all 25 Yellow palette sets and `$60`
  assignment tables; donor content is candidate organizational or artistic
  evidence only.
- Add native Beach House data.
- Add roofs and reviewed map overrides.
- Verify animated tile compatibility.
- Revalidate fades, flashes, white, black, and poison effects across all 25
  completed Yellow palette sets.

**Requirements:** The execution record cites `R5.5`, `R6.1`, `R6.2`, `R6.3`,
`R6.7`, `R6.9`, `R8.1`, `R8.2`, `R8.3`, `R8.4`, `R8.5`, and `R8.6`.

**Inventory:** When executed, list and close every concrete closed-inventory
tileset/content and palette-effect `MU-…` row and every `WR-…` row used to
load or transform its palette or to apply its lookup, roof, override,
animation, or native Beach House data.

**Acceptance:** The execution record closes `AC-OW-01`, `AC-OW-04`,
`AC-OW-06`, `AC-TECH-05`, and `AC-TECH-10`. `AC-OW-04` closes here, after
the Phase 3 transfer and precedence work is exercised with the completed roof,
override, animation, and replacement content required by `R8.5` and `R8.6`.

**Evidence:** Named 25-tileset atlas, exact table-length, Yellow-graphics
audit, Beach House, roof/override, animation, semantic full-byte attribute,
fade/flash/white/black/poison frame-strip, and visual-review checks; execution
records their concrete `CHK-…` IDs.

**Exit gate:** Every cited tileset/content row is closed, and all 25 tilesets'
atlas, table, semantic attribute, animation, palette-effect, and visual-review
evidence passes.

## Phase 7: complete handoff coverage

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Handoff before destination initialization on every concrete map-to-Yellow
  edge.
- Reconstruct the map on every concrete Yellow-to-full-color overworld edge,
  and do not invent map returns for standalone lifecycles without that edge.
- Stress rapid, repeated, interrupted, boot/reset, Yellow-to-Yellow nested and
  error, and actual ownership-boundary transitions.
- Reject stale-generation jobs.

**Requirements:** The execution record cites `R1.6`, `R1.9`, `R1.10`,
`R1.19`, `R1.20`, `R1.24`, `R2.1`, `R2.2`, `R2.3`, `R2.4`, `R2.5`, `R2.6`,
`R2.7`, `R2.8`, `R2.9`, `R2.10`, `R2.11`, `R2.12`, `R2.13`, `R12.1`,
`R12.2`, `R12.5`, and `R12.8`.

**Inventory:** When executed, list and close every concrete `MAP_BACKED`,
`STANDALONE`, and directed `SCENE_BOUNDARY` `SC-…` row from the baseline and
atomically extended inventories, including hard boot and Yellow-to-Yellow
nested/error edges, plus every reached handoff/reconstruction `WR-…` and
`MU-…` row. These scene labels classify scene rows only and do not classify
resources or responsibilities.

**Acceptance:** The execution record closes `AC-JOB-01`, `AC-RETURN-01`,
`AC-HO-01`, `AC-HO-02`, `AC-HO-03`, `AC-HO-04`, `AC-STRESS-02`, and
`AC-TECH-06`. `AC-RETURN-01`, `AC-HO-01`, `AC-HO-03`, and `AC-HO-04`
close here, and not in an earlier representative slice, only after every
concrete directed inventory edge has exhaustive evidence.

**Evidence:** Named directed scene-graph and boundary handoff matrix,
Yellow-before-destination-initialization, poison, complete-reconstruction only
on actual Yellow-to-overworld edges, barrier, five-active-frame,
stale-generation, boot/reset/nested/error-exit, and 100-cycle soak checks;
execution records their concrete `CHK-…` IDs, including the `R2.6` and
`R12.2` first-writer and initialization-entry evidence required by
`AC-HO-01`.

**Exit gate:** Every cited lifecycle and boundary `SC-…` row is closed, and
the full handoff matrix plus rapid, repeated, interrupted, nested, reset,
return-reconstruction, and 100-cycle soak evidence passes.

## Phase 8: delete old overworld ownership

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Remove Yellow's old overworld tint and attribute path.
- Remove transitional overworld adapters.
- Remove restoration behavior.
- Enforce owner-gated hardware writers in CI.
- Retain Yellow code required by excluded scenes.

**Requirements:** The execution record cites `R1.3`, `R1.4`, `R1.7`, `R7.2`,
`R12.3`, `R12.4`, `R12.5`, `R12.6`, and `R12.7`.

**Inventory:** When executed, list every concrete closed-inventory `WR-…`,
`SC-…`, and `MU-…` row removed, retained, or proven unreachable; this includes
obsolete overworld ownership and every captured-screen/restoration path.

**Acceptance:** The execution record closes `AC-INV-01`, `AC-REMOVE-01`,
`AC-REMOVE-02`, `AC-REMOVE-03`, `AC-REMOVE-04`, `AC-TECH-03`, and
`AC-HO-02`.

**Evidence:** Named source plus built-ROM reachability, restoration-hook
absence, owner-gated writer, adapter justification/removal, and excluded-scene
regression checks; execution records their concrete `CHK-…` IDs.

**Exit gate:** Source and built-ROM evidence proves obsolete Yellow overworld
ownership, tint/attribute, and captured-screen restoration paths unreachable
and removed, while every retained excluded-scene row remains green.

## Phase 9: timing and release hardening

Phase 0 baseline inventory closure is green. Closed baseline IDs and concrete
planned IDs added atomically under the execution evidence rule are permitted.

- Reconfirm LCD, VBlank, map streaming, palette upload, and OAM budgets.
- Verify safe missed-deadline behavior.
- Run the complete multi-frame suite.
- Verify release, debug, and VC builds.

**Requirements:** The execution record cites `R3.1`, `R3.4`, `R3.5`, `R3.6`,
`R5.5`, `R9.7`, `R10.1`, `R10.2`, `R10.3`, `R10.4`, `R10.5`, `R10.6`,
`R10.7`, `R10.8`, `R10.9`, `R10.10`, `R11.3`, `R11.4`, `R11.5`, `R12.1`,
`R12.5`, and `R12.6`.

**Inventory:** When executed, list every remaining concrete closed-inventory
`WR-…`, `SC-…`, and `MU-…` row reached by timing comparison, soak, release
builds, and excluded-scene regressions.

**Acceptance:** The execution record closes every acceptance criterion still
open after Phases 0–8, including `AC-TIME-01`, `AC-TRACE-01`, `AC-TECH-01`,
`AC-TECH-08`, `AC-TECH-10`, `AC-HO-02`, `AC-REMOVE-04`, and `AC-DONE-01`.

**Evidence:** Named timing-budget and baseline-comparison tables, exact
threshold-plus-one deferrals, complete traceability report,
fade/flash/white/black/poison multi-frame regressions, multi-frame and soak
suites, reproducible release/debug/VC builds, and excluded-scene regression
checks; execution records their concrete `CHK-…` IDs and every timing-row key.

**Exit gate:** All remaining acceptance, traceability, numeric timing
comparison, threshold deferral, soak, build, and excluded-scene regression
evidence passes, so all [acceptance criteria](acceptance-criteria.md) are green.

## Iteration rule

Run the fastest relevant gate after each change. A red prerequisite,
ownership, bank, or semantic-state gate stops renderer expansion until fixed.

Each implementation PR must:

- address one phase or bounded transfer path;
- name concrete affected `R…`, `AC-…`, `CHK-…`, `WR-…`, `SC-…`, and `MU-…`
  IDs from the closed authorities and inventory;
- state owner transitions and visible commit units;
- name applicable timing-row keys;
- include a machine-checkable test;
- avoid unrelated non-overworld work; and
- remain bootable and diagnosable.
