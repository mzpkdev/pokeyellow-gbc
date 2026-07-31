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

- renderer owner and generation;
- job and dirty state;
- last writer and assertion failure;
- writer trace;
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
- captures screenshots;
- repeats soak loops; and
- detects hangs through explicit timeouts.

PyBoy is the behavioral harness, not the final authority for cycle-accurate
CGB timing.

### Python

Python:

- coordinates scenarios;
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

## Semantic artifact

Use stable JSON with explicit versioning:

```json
{
  "schema": 1,
  "checkpoint": "return_from_party",
  "frame": 1234,
  "owner": "FULL_COLOR_OVERWORLD",
  "generation": 12,
  "banks": {"rom": 3, "wram": 1, "vram": 0},
  "dirty": {"bg": false, "obj": false, "attributes": false},
  "jobs": [],
  "bg_attributes": "...",
  "bg_palettes": "...",
  "obj_palettes": "...",
  "shadow_oam": "..."
}
```

Large byte arrays may use deterministic hex strings or separate binary files.
Failure output must still identify differing offsets.

## Failure report

The primary output is concise and textual:

```text
FAIL east_connection_after_scroll
owner: FULL_COLOR_OVERWORLD
generation: expected 14, actual 14
rSVBK: expected 1, actual 2
BG attribute $99a4: expected $03, actual $07
last writer: FC_WRITER_STREAM_COLUMN
artifact: test-results/.../actual-state.json
```

Also save:

- actual semantic state;
- expected-versus-actual structured diff;
- screenshot;
- screenshot diff when applicable; and
- decoded writer trace.

## Iteration tiers

### Fast: every change

- build/debug symbols as needed;
- unit tests for snapshots, traces, and writer audit;
- Gate 0 bank/ownership smoke;
- one vertical-slice checkpoint.

### Focused: transfer or handoff change

- complete vertical slice;
- affected connection/overlay/handoff cases;
- semantic and visual comparisons.

### Full: stage completion

- all tilesets and connections;
- handoff matrix;
- soak loops;
- timing instrumentation;
- excluded-scene regressions.

## Determinism rules

- Pin dependency versions.
- Start every test from a known fresh fixture or committed state.
- Do not depend on test order or mutable module globals.
- Bound every loop by frames or input count.
- Seed or mask legitimate randomness explicitly.
- Never update golden files automatically in CI.
- Require review when semantic expectations change.

## Timing limitation

Use PyBoy to detect behavioral regressions, missed frames, and obvious
overruns. Use assembly scanline/cycle instrumentation and, when available, a
timing-focused emulator or physical CGB for final timing gates.
