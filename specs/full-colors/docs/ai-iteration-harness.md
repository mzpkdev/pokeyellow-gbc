# AI iteration harness

## Existing foundation

Use the repository's current framework instead of creating another test stack:

- `tools/rom_tests/emulator.py` already wraps PyBoy;
- `tools/rom_tests/tests/conftest.py` provides isolated emulator fixtures;
- `pokeyellow_debug.sym` already resolves WRAM symbols;
- pytest already runs tests in parallel; and
- `test-results` already stores per-test artifacts.

Pinned dependencies currently include PyBoy, Pillow, pytest, and pytest-xdist.

## Responsibilities

### Assembly debug instrumentation

Expose only state Python cannot infer reliably:

- renderer owner, phase, and generation;
- exact request result, job state, cancellation reason, and dirty state;
- commit-unit, writer, and timing-row IDs;
- last writer and assertion failure;
- writer trace;
- reconstruction-item and presentation-barrier status;
- shadow/hardware OAM and fallback evidence;
- debug checkpoints; and
- controlled bank-torture entry points.

Keep debug-only instrumentation behind existing build conventions.

### PyBoy

PyBoy drives deterministic gameplay:

- boots the debug ROM;
- advances bounded frames;
- presses inputs;
- reads symbols and memory;
- enters map, overlay, and handoff scenarios;
- captures named checkpoint screenshots and bounded frame strips;
- repeats soak loops; and
- detects hangs through explicit timeouts.

PyBoy is the behavioral harness, not the final authority for cycle-accurate
CGB timing.

### Python

Python:

- coordinates scenarios;
- runs the reference ownership model with the stable owner, phase,
  request-result, job-state, and cancellation symbols;
- resolves `.sym` addresses;
- reads WRAM, HRAM, VRAM, OAM, and palette state;
- writes semantic JSON;
- diffs expected and actual state;
- audits hardware writers;
- manages timeouts and artifacts; and
- returns a nonzero CI exit code.

State readers must be observational: when reading banked VRAM or CGB palette
RAM, they save and restore index registers and bank state so the test harness
does not alter the behavior it is measuring.

## Suggested test layout

```text
tools/rom_tests/
├── emulator.py
├── full_color/
│   ├── snapshots.py
│   ├── trace.py
│   ├── writer_audit.py
│   └── scenarios.py
└── tests/
    ├── unit/
    │   ├── test_full_color_snapshots.py
    │   ├── test_full_color_trace.py
    │   └── test_full_color_writer_audit.py
    └── e2e/
        └── full_color/
            ├── test_gate0.py
            ├── test_vertical_slice.py
            ├── test_handoffs.py
            └── test_soak.py
```

Exact names may change, but unit and emulator-driven responsibilities must stay
separate.

## LLM-visible play evidence

An LLM-driven test play must be able to inspect the actual rendered output, not
only receive a pass/fail result. At named checkpoints, save:

- a lossless screenshot;
- a short, bounded frame strip before and after the checkpoint;
- a contact sheet with frame numbers and checkpoint labels;
- the matching semantic snapshot and decoded writer trace; and
- a compact text summary linking visual and semantic artifacts.

Write a contract-versioned artifact manifest containing relative file paths,
checkpoint names, frame numbers, scenario seed, artifact types, and explicit
links to the matching semantic snapshots and decoded writer traces. Prefer
directly viewable PNG files for screenshots and contact sheets.

Use screenshots to inspect palette selection, seams, missing attributes,
incorrect priority, follower/NPC OAM, overlay damage, stale return frames, and
visible flicker. Prefer a frame strip or contact sheet when correctness depends
on ordering; a single final frame cannot prove that no transient corruption
occurred.

Visual review is a first-class diagnostic and acceptance input, but it does not
replace semantic assertions. A plausible screenshot can still contain stale
state, and visual differences may be ambiguous until paired with attributes,
palettes, owner, generation, banks, and last-writer data.

## Contract-versioned artifacts

Gate 0 implements and self-mutates this schema against deterministic Yellow
baseline fixtures; it does not claim runtime renderer behavior. Request,
commit, Yellow-to-overworld reconstruction, overlay, overworld OAM, and
renderer-operation timing fields become runtime acceptance only in their
migration activation phases.

When the harness is implemented and run, every checkpoint records the contract
schema version, ROM identity, scenario, seed, checkpoint, and frame; owner,
phase, and generation; the exact stable request result, including wrong-owner,
stale-generation, and every capacity-pressure result; job state and
cancellation reason; commit-unit and writer IDs; ROM/WRAM/VRAM banks;
reconstruction-item and presentation-barrier status; tile IDs and full
attributes; BG and OBJ palettes; shadow and hardware OAM; OAM fallback
evidence; a timing-row key; and linked visual and trace artifacts. Cancelled
work remains in a bounded trace long enough to prove that it performs no later
write.

Every future collected check declares its concrete `R…` and `AC-…` IDs.
Collection emits a machine-readable mapping to named `CHK-…` checks and fails
on unknown or uncovered IDs.

Use stable JSON with explicit contract versioning:

```json
{
  "schema": "full-color-contract-v1",
  "rom": "pokeyellow_debug.gbc:<content-id>",
  "scenario": "standalone_return",
  "seed": 83421,
  "checkpoint": "return_from_party",
  "frame": 1234,
  "owner": "RENDERER_FULL_COLOR_OVERWORLD",
  "phase": "OVERWORLD_RECONSTRUCTING",
  "generation": 12,
  "request_result": "ACCEPTED",
  "job": {
    "state": "COMMITTING",
    "cancellation_reason": null,
    "commit_unit_id": "<inventory-populated-ID>"
  },
  "writer_id": "<inventory-populated-WR-ID>",
  "banks": {"rom": 3, "wram": 1, "vram": 0},
  "dirty": {"bg": false, "obj": false, "attributes": false},
  "reconstruction": {"items": {}, "presentation_barrier": false},
  "bg_tile_ids": "...",
  "bg_attributes": "...",
  "bg_palettes": "...",
  "obj_palettes": "...",
  "shadow_oam": "...",
  "hardware_oam": "...",
  "oam_fallback": null,
  "timing_row_key": "<future-numeric-row-key>",
  "artifacts": {"trace": "...", "screenshot": "...", "frame_strip": "..."}
}
```

Large byte arrays may use deterministic hex strings or separate binary files.
Failure output must still identify differing offsets.

For each concrete Yellow-to-full-color overworld boundary,
return-reconstruction evidence must identify the actual Yellow-owned source
lifecycle. Only when source plus built-ROM evidence proves that the boundary
has a preceding concrete map-to-Yellow edge does it also identify the last map
generation and prove that Yellow was selected before entry to that
destination's initialization; the harness must not synthesize that departure.
Initial new-game, continue, reset, and other Yellow-owned entry lifecycles
record their actual source lifecycle without inventing a map-to-Yellow
predecessor. Every concrete Yellow-to-overworld boundary still records poison
installation for prior tilemaps, attributes, palettes, OAM, buffers, flags,
and jobs, every reconstruction item completed from authoritative state, the
presentation barrier, and at least five `OVERWORLD_ACTIVE` frames after it.
Standalone and Yellow-to-Yellow edges that do not cross a concrete
Yellow-to-overworld boundary require no reconstruction fixture.

Request-pressure runtime evidence records the selected capacity and the
selected policy for each request class, then submits wrong-owner,
stale-generation, equivalent-at-capacity, and non-equivalent capacity+1 cases.
Required visible-state classes must return `DEFERRED` and retry when they
cannot coalesce. A class returning `REJECTED_CAPACITY` must be optional or
supersedable and prove its documented caller fallback. Runtime tests exercise
exactly the selected policies; schema and reference-model tests also exercise
unselected enum branches. Evidence records whether work was created or
attached and eventual completion of all accepted or coalesced work.

The overlay expected-value generator is independent of emulator VRAM and
ambient map state. It consumes the request's authoritative destination
BG/window selector, map identity, tileset identity, destination rectangle,
world-coordinate origin/transform, complete override set, per-cell
`OPAQUE_OVERLAY`/`REVEALED_TERRAIN` classification, desired tile identity, and
explicit/default overlay attribute. It clips the selected destination while
preserving source-to-destination tilemap and source-to-world mappings, then
uses the supplied world-coordinate override or supplied tileset lookup.
Ordinary, fully clipped, partially clipped, edge, connection, alternate-BG,
and alternate-map destinations compare every full-byte attribute bit,
including canonical bit 4. Reading either VRAM bank or ambient map identity to
derive classification, tile identity, coordinate, or expected attribute is a
harness failure.

Atomicity evidence forces insufficient budget at every pre-visible preparation
and revalidation boundary. Visible-destination work must remain `PREPARED`
unless it can reserve its measured worst-case completion budget; after it
enters `COMMITTING`, the harness expects uninterrupted completion. Arbitrary
mid-operation interruption is generated only for an inactive destination or
while the LCD is off.

## Failure report

The primary output is concise and textual:

```text
FAIL east_connection_after_scroll
owner: RENDERER_FULL_COLOR_OVERWORLD
phase: OVERWORLD_ACTIVE
generation: expected 14, actual 14
request result: ACCEPTED
job: PREPARED; cancellation: none
commit unit: <inventory-populated-ID>
writer: <inventory-populated-WR-ID>
timing row: <future-numeric-row-key>
rSVBK: expected 1, actual 2
BG attribute $99a4: expected $03, actual $07
artifact: test-results/.../actual-state.json
```

Also save:

- actual semantic state;
- expected-versus-actual structured diff;
- named screenshot and annotated contact sheet;
- bounded frame strip for temporal failures;
- screenshot diff when applicable; and
- decoded writer trace including phase, job/cancellation, commit-unit, writer,
  and timing-row context.

## Iteration tiers

### Fast: every change

- build/debug symbols as needed;
- unit tests for snapshots, traces, and writer audit;
- Gate 0 bank/ownership smoke;
- deterministic baseline screenshot, frame-strip, annotated-contact-sheet,
  localized-image-diff, and versioned-manifest checks.

### Focused: transfer or handoff change

- complete hostile vertical slice after Phase 2 activates it;
- affected connection/overlay/handoff cases;
- semantic comparisons and LLM visual review; and
- current timing measurements.

### Full: stage completion

- all tilesets and connections;
- handoff matrix;
- soak loops;
- timing measurements;
- excluded-scene regressions.

## Determinism rules

- Pin dependency versions.
- Start every test from a known fresh fixture or committed state.
- Do not depend on test order or mutable module globals.
- Bound every loop by frames or input count.
- Seed or mask legitimate randomness explicitly.
- Never update golden files automatically in CI.
- Require review when semantic expectations change.
- Record the seed and action list for generated ownership scenarios.
- Give every screenshot and frame strip a stable checkpoint name.

## Timing limitation

Use PyBoy to detect behavioral regressions, missed frames, and obvious
overruns. Use assembly scanline/cycle instrumentation and, when available, a
timing-focused emulator or physical CGB for final timing gates.
