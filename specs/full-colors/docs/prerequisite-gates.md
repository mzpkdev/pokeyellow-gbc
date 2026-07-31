# Mandatory prerequisite gates

Gate 0 is a hard prerequisite. Work may add tests, debug instrumentation, and
test-only control surfaces, but may not begin the production renderer port
until every Gate 0 item passes against the baseline debug ROM.

Some sections also state a later activation condition. Only their baseline
condition belongs to Gate 0; the later condition becomes a blocking phase exit
after renderer code exists.

## Gate 0 required artifact contract

The following are required outputs of future Gate 0 implementation and
execution. This documentation revision defines their schemas and pass
conditions; it does not claim that an inventory has been populated, a
measurement has been taken, or an artifact has been produced or validated.

| Gate 0 artifact | Required baseline content |
|---|---|
| baseline writer/scene/mutation inventories | concrete existing-code `WR-…`/`SC-…`/`MU-…` IDs, populated rows, reachability, permissions, and source plus built-ROM closure |
| representation decision | numeric baseline and synthetic/model high-water and size evidence selecting capacity, descriptor semantics, one policy per request class, and WRAM placement |
| timing-instrument readiness | deterministic numeric instrumentation cost, complete Yellow baseline rows, and detection of synthetic over-budget fixtures |
| semantic schema | decodable owner, phase, generation, request result, job state/cancellation, commit unit, reconstruction items, overlay request fields, OAM fallback, and timing-row fields |
| traceability report | every concrete `R…` and `AC-…` mapped to named `CHK-…` checks and evidence, with activation phase recorded for renderer checks |

Future Gate 0 execution cannot pass until the three baseline inventories are
populated and reviewed and both source and built-ROM discovery are closed.
Later phases may add concrete planned rows atomically with new symbols or
directed edges, but must review them and rerun source plus built-ROM closure
before the path becomes reachable or the phase proceeds.

Gate 0 synthetic/schema and reference-model evidence selects exactly one
pressure policy per request class. It exercises the selected result and every
unselected enum branch without claiming baseline runtime renderer behavior.
Required visible-state classes select `DEFERRED` plus caller retry when they
cannot coalesce. `REJECTED_CAPACITY` may be selected only for an optional or
supersedable class with a documented caller fallback. Runtime conformance to
the selected class policies activates with the request implementation in
Phase 2.

Renderer acceptance is deliberately not a Gate 0 exit condition. Request,
commit, actual Yellow-to-overworld reconstruction, overlay, overworld OAM, and
renderer-operation timing checks exist as schemas, reference-model cases, and
self-mutations in Gate 0, then become runtime acceptance in their migration
activation phases. Production renderer code remains prohibited during Gate 0.

The overlay schema carries destination BG/window selector, map identity,
tileset identity, rectangle, world-coordinate origin/transform, override set,
per-cell classification, tile IDs, and attributes. Its independent model
preserves source-to-destination tilemap and world-coordinate mappings through
clipping and never reads VRAM or ambient map state. Runtime ordinary, clipped,
edge, connection, alternate-BG, and alternate-map coverage activates in
Phases 2–3. Runtime OAM fallback coverage activates in Phases 2 and 4.

| Operation | Mode | ROM | Tool/device | Samples | Worst cycles | Instrumentation | Start | Deadline | Guard | Margin cycles | Margin % | Defer threshold | Result |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|

Every numeric cell is required when a renderer timing row activates. A row
passes only when `worst + instrumentation <= deadline - start - guard`.
Activation checks force insufficient budget at every pre-visible preparation
or revalidation boundary. A visible-destination operation must defer before
`COMMITTING`; after reserving its worst-case budget it must complete. Arbitrary
mid-operation interruption is tested only for an inactive destination or with
the LCD off.

## G0.1 Reproducible test environment

- Extend the existing `tools/rom_tests` pytest/PyBoy framework.
- Keep PyBoy and related packages pinned in
  `tools/rom_tests/requirements.txt`.
- Build and consume `pokeyellow_debug.gbc` and `pokeyellow_debug.sym`.
- Give every test a deterministic initial state, bounded frame count, and
  explicit timeout.
- Preserve per-test failure artifacts under `test-results`.

Pass condition: a clean checkout runs the smoke command twice with identical
semantic outputs.

## G0.2 Inventory discovery and closure

Build the concrete writer, scene, and visible-map-mutation inventories defined
by [replacement-inventory.md](replacement-inventory.md). Discovery must cover
source search and built-ROM symbol/disassembly reachability. Grep only seeds
rows and cannot prove closure.

The writer audit covers direct, indirect-high-memory, wrapper, DMA, and
interrupt writes to every owner-gated resource, including LCD/STAT/LYC,
scroll/window/palette registers, `rVBK`, `rSVBK`, HDMA/GDMA, shadow OAM,
hardware OAM, and every `rDMA` source, launch, and wait path. Scene discovery
covers every lifecycle and boundary in the scope contract plus reachable
reset, failure, nested-exit, load, and return paths. Mutation discovery covers
every visible-map load, transfer, overlay, animation, replacement, alternate
destination, and reconstruction path.

Every discovered baseline item receives a concrete `WR-…`, `SC-…`, or `MU-…`
ID and a fully populated reviewed row. Later concrete rows are added and
reviewed atomically with new symbols or directed edges, followed by source and
built-ROM closure before reachability. Unexpected additions or any reachable
unclassified item fail CI.

Pass condition: all three baseline inventories are populated, reviewed, and
closed in both source and built-ROM evidence; independent source and ROM
fixtures containing an unlisted reachable item make the audit fail, and a
fixture proves a planned row cannot become reachable before atomic row review
and renewed closure.

## G0.3 Debug observability

The debug ROM exposes symbols for:

- active owner;
- active phase;
- ownership generation;
- last request result;
- job state, cancellation reason, and dirty flags;
- current commit-unit and writer IDs;
- current ROM/WRAM/VRAM banks;
- last writer ID and resource;
- reconstruction-item and presentation-barrier status;
- OAM fallback evidence;
- current timing-row key;
- assertion failure code; and
- a bounded writer trace ring.

Release builds need not include the trace.

Pass condition: PyBoy can resolve every symbol and decode a synthetic trace.

## G0.4 Semantic snapshots

Extend the Python emulator helper to capture JSON containing:

- schema/contract version, ROM identity, scenario, seed, checkpoint, and frame;
- owner, phase, and generation;
- exact request result, job state, cancellation reason, and commit-unit IDs;
- current and traced writer IDs;
- ROM/WRAM/VRAM banks;
- BG tile IDs and attributes;
- BG and OBJ palette RAM;
- shadow and hardware OAM;
- dirty and queued job state; and
- current map/tileset, transfer state, reconstruction-item status, OAM
  fallback, and timing-row key.

Diffs identify exact offsets and expected/actual values. Screenshots are
secondary artifacts. Cancelled work remains in a bounded trace long enough to
prove that it performs no later write.

Pass condition: identical checkpoints compare cleanly and an intentional
one-byte mutation reports the resource and offset.

## G0.5 Ownership assertions

Debug assertions fail when:

- a writer runs under the wrong owner;
- two owners appear active;
- a stale-generation job executes;
- ownership changes during a partially committed job; or
- a renderer returns with unexpected bank state.

Gate 0 schema/reference-model fixtures submit wrong-owner, stale-generation,
equivalent-at-capacity, and each request class's selected pressure result; they
also exercise unselected enum branches only in the schema/model. Atomicity
self-mutations model insufficient time at every pre-visible preparation and
revalidation boundary, failure to reserve worst-case completion budget, and
illegal interruption after visible `COMMITTING`.

Gate 0 pass condition: mutation fixtures trigger every harness assertion,
schema/reference-model request and atomicity oracles match exactly, and normal
Yellow baseline scenarios trigger no assertion. Runtime request accounting and
visible atomicity become Phase 2 acceptance.

## G0.6 Bank-torture harness

Provide debug entry points, synthetic fixtures, or controlled baseline
scenarios that exercise bank capture and restoration with:

- non-default ROM bank;
- every bank in the Gate 0-selected renderer WRAM range and every other valid
  WRAM entry bank;
- VRAM bank 1;
- an interrupt during a far call; and
- pending work during soft reset or ownership switch.

Gate 0 pass condition: every baseline or synthetic fixture restores banks,
stack, and interrupts and proves the future owner/generation/dirty-state schema
is decodable. Renderer-path conformance activates in Phases 1–2.

## G0.7 Model-based ownership testing

Implement a small Python reference model using the stable owner, phase,
request-result, job-state, and cancellation symbols from the requirements
contract. Its observable phases are:

```text
YELLOW_ACTIVE
HANDOFF_TO_OVERWORLD
OVERWORLD_RECONSTRUCTING
OVERWORLD_ACTIVE
OVERWORLD_OVERLAY
HANDOFF_TO_YELLOW
```

Generate seeded valid and adversarial action sequences covering movement,
overlays, connections, handoffs, returns, reset, pending work, and interrupt
boundaries. After every action, compare the ROM trace and semantic snapshot to
the model's expected owner, phase, generation, exact request result, job
state/cancellation, permitted writer and commit-unit IDs, queued work, and bank
state.

Failures preserve the seed and reduce to the shortest reproducible action
sequence where practical.

Gate 0 pass condition: model unit tests and seeded synthetic traces are
deterministic, valid sequences satisfy the model, and deliberately corrupted
transitions fail at the first divergent action.

Activation condition after Phase 1: generated sequences agree with debug-ROM
traces at every action.

## G0.8 Hostile diagnostic vertical slice

Script one bounded PyBoy scenario:

```text
map entry
-> horizontal and vertical movement
-> animated terrain
-> map connection near a tilemap boundary
-> dialogue near a map edge
-> start-menu overlay
-> follower Pikachu and several NPCs
-> standalone screen
-> map return
```

Run it with forced non-default ROM/WRAM/VRAM entry state and representative
interrupt pressure.

Before renderer work, the scenario records stable Yellow baseline checkpoints.
It also defines the future full-color expectations.

Pass condition before implementation: scenario and baseline are deterministic.

Pass condition before expanding beyond the first slice: all semantic,
multi-frame visual, ownership, bank, and initial timing checkpoints pass without
restoration hooks. An actual Yellow-to-overworld return records the last map
generation, Yellow ownership before destination initialization entry, poison
installation, every reconstruction item, the presentation barrier, and at
least five active overworld frames. Overlay checkpoints apply the
authoritative destination/map/tileset/world-transform request oracle from the
artifact contract.

## G0.9 LLM visual artifact pipeline

At named checkpoints, emit lossless screenshots, bounded frame strips,
annotated contact sheets, and metadata linking each image to its semantic
snapshot and writer trace. The filenames and checkpoint labels are stable
enough for an LLM-driven test play to locate and view them directly. A small
contract-versioned artifact manifest lists relative paths, checkpoint names,
frame numbers, scenario, seed, ROM identity, semantic schema version, and
linked trace and timing-row keys.

Gate 0 pass condition: a deterministic baseline fixture produces viewable
artifacts, and an intentional visual mutation produces a localized image diff.

Activation condition after Phase 2: the hostile slice's canary assignments
produce the expected semantic and visual artifacts.

## G0.10 Gate mutation suite

Tests deliberately introduce or emulate:

- wrong-owner write;
- invalid ownership-model transition;
- stale job generation;
- wrong-owner and stale-generation request admission;
- selected per-class capacity-plus-one pressure plus model-only unselected
  enum branches;
- silent loss of accepted or coalesced work;
- missing streamed attribute;
- insufficient time at each pre-visible boundary, missing worst-case
  reservation, or visible mid-commit interruption;
- VRAM-derived, ambient-map-derived, or mapping-losing overlay classification;
- incomplete or saved-byte reconstruction after poisoned prior state;
- missing OAM fallback diagnostic or changed bits 3–7;
- a defer-threshold-plus-one boundary that enters `COMMITTING`;
- leaked WRAM bank;
- unexpected hardware writer; and
- snapshot corruption.

Pass condition: each mutation makes the intended gate fail with a specific
message and useful artifacts. This suite validates the tests, not the renderer.

## G0.11 Early timing instrumentation

Before renderer code exists, add debug counters and checkpoints that report
scanline or cycle consumption for LCD, VBlank, transfer, palette, and OAM work.
Record stable Yellow baselines. Future renderer execution must populate one
numeric table row from the artifact contract for every timed operation and
derive, rather than assume, its explicit budget and exact safe-defer threshold.

PyBoy may drive and record these checks, but a timing-focused emulator or
physical CGB remains the final authority.

Gate 0 pass condition: instrumentation is deterministic, its cost is numeric,
the Yellow baseline rows are complete, and synthetic over-budget and illegal
mid-commit-interruption fixtures are detected. No renderer-operation timing row
is accepted in Gate 0.

Activation condition before architecture expansion: the hostile slice has
complete numeric results for every timed operation, every row passes the
required equation, insufficient budget at every pre-visible boundary safely
defers the whole job, and a visible `COMMITTING` unit always completes from its
reserved worst-case budget.

## G0.12 CI enforcement

- Add a job that builds the debug ROM and symbols.
- Run Gate 0 unit and bounded PyBoy tests on pull requests.
- Archive semantic diffs, traces, screenshots, and frame strips on failure.
- Keep long atlas/soak suites separate from the fast required job.
- Emit a machine-readable traceability report mapping every concrete `R…` and
  `AC-…` to named `CHK-…` checks and artifacts, and fail on unknown or
  uncovered IDs.
- Treat a Gate 0 failure as blocking.

Pass condition: the required job passes normally, fails under a gate mutation,
and publishes enough artifacts to diagnose the mutation without reproducing it
locally.

## Required commands

Expose stable commands or documented pytest selections equivalent to:

```text
test-full-color-gate0
test-full-color-smoke
test-full-color-handoffs
test-full-color-soak
test-full-color-all
```

`gate0` must be fast enough to run after every small change. `smoke` becomes the
default AI loop after the first renderer slice.

## Stop rule

If Gate 0 becomes red, production renderer iteration stops. Fix the harness or
violated invariant before changing color content or adding another transfer
path.
