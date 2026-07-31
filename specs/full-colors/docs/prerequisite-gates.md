# Mandatory prerequisite gates

Gate 0 is a hard prerequisite. Work may add tests, debug instrumentation, and
test-only control surfaces, but may not begin the production renderer port
until every Gate 0 item passes against the baseline debug ROM.

Some sections also state a later activation condition. Only their baseline
condition belongs to Gate 0; the later condition becomes a blocking phase exit
after renderer code exists.

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

## G0.2 Hardware-writer inventory

Add a Python audit for writes to:

- `rBGPI` and `rBGPD`;
- `rOBPI` and `rOBPD`;
- `rVBK` and `rSVBK`; and
- HDMA/GDMA registers used for attributes.

Every writer has an ID, owner classification, source location, and reason.
The audit covers direct register operands and indirect high-memory writes such
as `ld [$ff00+c], a`; a plain text search is only one input to the reviewed
inventory. Unexpected additions fail CI.

Pass condition: the baseline allowlist is complete and a fixture containing an
unlisted writer makes the audit fail.

## G0.3 Debug observability

The debug ROM exposes symbols for:

- active owner;
- ownership generation;
- pending job and dirty flags;
- current ROM/WRAM/VRAM banks;
- last writer ID and resource;
- assertion failure code; and
- a bounded writer trace ring.

Release builds need not include the trace.

Pass condition: PyBoy can resolve every symbol and decode a synthetic trace.

## G0.4 Semantic snapshots

Extend the Python emulator helper to capture JSON containing:

- owner and generation;
- ROM/WRAM/VRAM banks;
- BG tile IDs and attributes;
- BG and OBJ palette RAM;
- shadow OAM;
- dirty and queued job state; and
- current map/tileset and relevant transfer state.

Diffs identify exact offsets and expected/actual values. Screenshots are
secondary artifacts.

Pass condition: identical checkpoints compare cleanly and an intentional
one-byte mutation reports the resource and offset.

## G0.5 Ownership assertions

Debug assertions fail when:

- a writer runs under the wrong owner;
- two owners appear active;
- a stale-generation job executes;
- ownership changes during a partially committed job; or
- a renderer returns with unexpected bank state.

Pass condition: mutation fixtures trigger every assertion and normal baseline
scenarios trigger none.

## G0.6 Bank-torture harness

Provide debug entry points or controlled scenarios that call renderer-facing
wrappers with:

- non-default ROM bank;
- WRAM bank 2 and another valid bank;
- VRAM bank 1;
- an interrupt during a far call; and
- pending work during soft reset or ownership switch.

Pass condition: every test restores banks, stack, interrupts, owner, generation,
and dirty state exactly as specified.

## G0.7 Model-based ownership testing

Implement a small Python reference model with these observable states:

```text
OVERWORLD
OVERWORLD_OVERLAY
HANDOFF_TO_YELLOW
YELLOW_SCREEN
RETURN_TO_OVERWORLD
```

Generate seeded valid and adversarial action sequences covering movement,
overlays, connections, handoffs, returns, reset, pending work, and interrupt
boundaries. After every action, compare the ROM trace and semantic snapshot to
the model's expected owner, generation, permitted writers, queued work, and
bank state.

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
restoration hooks.

## G0.9 LLM visual artifact pipeline

At named checkpoints, emit lossless screenshots, bounded frame strips,
annotated contact sheets, and metadata linking each image to its semantic
snapshot and writer trace. The filenames and checkpoint labels are stable
enough for an LLM-driven test play to locate and view them directly. A small
artifact manifest lists relative paths, checkpoint names, and frame numbers.

Gate 0 pass condition: a deterministic baseline fixture produces viewable
artifacts, and an intentional visual mutation produces a localized image diff.

Activation condition after Phase 2: the hostile slice's canary assignments
produce the expected semantic and visual artifacts.

## G0.10 Gate mutation suite

Tests deliberately introduce or emulate:

- wrong-owner write;
- invalid ownership-model transition;
- stale job generation;
- missing streamed attribute;
- leaked WRAM bank;
- unexpected hardware writer; and
- snapshot corruption.

Pass condition: each mutation makes the intended gate fail with a specific
message and useful artifacts. This suite validates the tests, not the renderer.

## G0.11 Early timing instrumentation

Before renderer code exists, add debug counters and checkpoints that report
scanline or cycle consumption for LCD, VBlank, transfer, palette, and OAM work.
Record stable Yellow baselines and define explicit budgets or safe-defer
behavior for the first renderer slice.

PyBoy may drive and record these checks, but a timing-focused emulator or
physical CGB remains the final authority.

Gate 0 pass condition: instrumentation is deterministic and a synthetic
over-budget fixture is detected.

Activation condition before architecture expansion: the hostile slice has
measured results for worst-case representative work and safely defers any job
that cannot complete.

## G0.12 CI enforcement

- Add a job that builds the debug ROM and symbols.
- Run Gate 0 unit and bounded PyBoy tests on pull requests.
- Archive semantic diffs, traces, screenshots, and frame strips on failure.
- Keep long atlas/soak suites separate from the fast required job.
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
