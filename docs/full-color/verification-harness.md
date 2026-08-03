# Full-color verification harness

The harness is a stack of different kinds of evidence. No single command proves
that the game is playable, visually correct, and architecturally sound. Treat a
green result as evidence for the claim that layer was designed to test—not as a
general certificate that the renderer works.

The implementation lives under
[`tools/rom_tests`](../../tools/rom_tests/), the executable targets are in the
repository [`Makefile`](../../Makefile), and the formal contracts live under
[`specs/full-colors`](../../specs/full-colors/).

The harness grows by the exit gates in the
[migration plan](../../specs/full-colors/docs/migration-plan.md): Phase 3 adds
palette/effect and paired-transfer proof; Phase 4 OAM; Phase 5 architecture
stress; Phase 6 all 25 tilesets, roofs, overrides, and content; Phase 7 complete
handoffs; Phase 8 obsolete-ownership removal; and Phase 9 timing and release
hardening. A green Phase 2 check grants no acceptance credit to those phases.

## Set up once

Run from the repository root:

```console
make test-full-color-setup
```

This creates the ignored `.venv` and installs the pinned dependencies from
[`tools/rom_tests/requirements.txt`](../../tools/rom_tests/requirements.txt).
The Make targets prefer `.venv/bin/python` locally and fall back to `python3`
in managed environments such as CI.

Build the products needed by the Phase 2 and gameplay checks with:

```console
make yellow_debug yellow_phase2_audit
```

`pokeyellow_phase2_audit.gbc` is an audit-only product. Normal release, debug,
and VC products must not acquire its passive color runtime.

## The four proof layers

### 1. Contracts and pure models

The fast tests under
[`tools/rom_tests/tests/unit/full_color`](../../tools/rom_tests/tests/unit/full_color/)
validate schemas, inventories, ownership transitions, scheduling rules, palette
transformations, evidence readers, and deterministic model sequences.

```console
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q
```

These tests are the quickest place to express an invariant. They prove that the
Python contract or model behaves as specified. By themselves they do not prove
that the linked assembly follows that model or that a player can complete a
scene.

### 2. Built-ROM and callable-ROM checks

The full-color unit tree also contains tests that inspect linked `.gbc`, `.sym`,
and `.map` products or call named assembly routines through the emulator. They
check facts such as ROM placement, audit-code exclusion from normal products,
bank restoration, palette writes, request admission, and handoff/reset
behavior.

Build the required product before a focused run. For example:

```console
make yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color/test_phase2_layout.py -q
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color/test_phase2_palettes_rom.py -q
```

Callable-ROM tests are strong evidence about a routine under controlled state.
They are not a substitute for reaching the same state through normal gameplay.

### 3. Retained deterministic gates

These runners execute defined corpora and retain structured evidence below
`test-results/`. Their result roots can be overridden with the corresponding
`FULL_COLOR_*_RESULTS` Make variable.

```console
make test-full-color-smoke
make verify-full-color-phase2-audit
make test-full-color-renderer-conformance
make test-full-color-renderer-runtime
make test-full-color-gate0
make test-full-color-handoffs
make test-full-color-soak
make test-full-color-all
```

The important boundaries are:

- `test-full-color-smoke` boots the debug ROM and retains snapshots,
  diagnostics, reports, and status without overwriting an earlier attempt.
- `verify-full-color-phase2-audit` binds the audit product to its selected
  Phase 2 representation, source discovery, inventory coverage, provenance,
  and product identities. It does not play the vertical slice or judge whether
  its frames look good.
- `test-full-color-renderer-conformance` is an independent **synthetic checker
  self-test**. It proves that the checker accepts its canonical fixtures and
  rejects its named mutations. Synthetic results must never be relabelled as
  runtime evidence.
- `test-full-color-renderer-runtime` captures the activated Phase 1 real-ROM
  ownership case twice. It proves ownership replacement for that selected
  case; Phase 1 makes no global color, visual-quality, or playability claim.
- `test-full-color-handoffs` and `test-full-color-soak` exercise focused model
  transitions and seeded valid sequences.

`make test-full-color-all` is useful, but its name is broader than its actual
dependency list. It combines Gate 0, conformance, Phase 1 runtime, handoff, and
soak checks. **It does not run `verify-full-color-phase2-audit`, and it does not
run the cold-boot gameplay E2E suite.** Run those separately before declaring a
Phase 2 change green.

### 4. Natural gameplay E2E

The cold-boot suite in
[`test_full_color_cold_boot_journey.py`](../../tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py)
starts from boot and reaches states through player inputs. It compares stock
debug and Phase 2 audit behavior while recording logical state, renderer state,
VRAM, OAM, palettes, attributes, and screenshots.

```console
make yellow_debug yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
```

Its two harness tests protect setup behavior. Its eight gameplay journeys cover:

- bedroom through Pallet Town and Route 1 to Viridian City;
- paired stock/audit northbound parity and color-only differences in the slice;
- the reverse Route 1 ledges and Pallet re-entry;
- the Red house interior fallback and return to the colored map;
- Oak's scripted Pikachu capture, ball animation, and lab transition;
- dialogue, menu, and party boundaries;
- a natural Route 1 wild-battle round trip;
- save, reset, Continue, and restored playability.

Failure evidence is written below `test-results/full-color-cold-boot/`. General
E2E scenarios and reusable input flows live in
[`tools/rom_tests/tests/e2e`](../../tools/rom_tests/tests/e2e/) and
[`tools/rom_tests/scenarios`](../../tools/rom_tests/scenarios/).

**Cold-boot E2E is not currently run by hosted CI.** A green GitHub check suite
therefore does not replace this local command or a human playtest of the ROM.

## Gate 0 contract

Local `make test-full-color-gate0` performs two independent executions. Each
execution stops at the first failed component and covers, in order:

1. the complete fast unit suite;
2. baseline source/ROM discovery;
3. reviewed inventory reconciliation;
4. synthetic bank-boundary torture;
5. debug-ROM runtime observability;
6. specification traceability;
7. the visual artifact pipeline.

Attempts are retained under
`test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`. Diagnostics may
differ, but every stable evidence file must exist in both runs and be
byte-identical. The comparator explicitly checks the semantic snapshot,
traceability report, and versioned visual manifest. Failed attempts retain
their status, JUnit, stdout, stderr, and emulator diagnostics and do not erase
earlier successes.

To place evidence elsewhere, including a path containing spaces:

```console
make test-full-color-gate0 FULL_COLOR_RESULTS="/tmp/pokeyellow gate0"
```

Hosted CI parallelizes the two complete executions as `Gate 0 Baseline Run 1`
and `Gate 0 Baseline Run 2`. Each uploads its evidence. The blocking `Gate 0
Baseline` job downloads both and runs the same byte comparator. Parallelism is
only an optimization; the requirement remains two independent complete runs
plus a successful comparison.

## Recommended fast-to-slow ladder

Use the narrowest meaningful check while editing, then climb the ladder as the
change approaches review:

1. one focused pytest file or `-k` expression;
2. `.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q`;
3. `make test-full-color-smoke`;
4. `make verify-full-color-phase2-audit` for Phase 2 code, inventory, or data;
5. `make test-full-color-renderer-conformance`;
6. `make test-full-color-renderer-runtime`;
7. `make test-full-color-gate0`;
8. a focused cold-boot journey, then the complete cold-boot file;
9. `make test-full-color-all` plus the separately required Phase 2 verification
   and cold-boot E2E commands.

For a renderer change, “green” means the relevant local ladder is green, the
retained artifacts are coherent, the screenshots were actually inspected, and
hosted CI later completes successfully.

## Adding tests safely

Put fast, isolated checks under `tools/rom_tests/tests/unit/`. Put real gameplay
and visual scenarios under `tools/rom_tests/tests/e2e/`; reusable journeys
belong under `tools/rom_tests/scenarios/`.

When adding a test:

- Request the shared `emulator` fixture for ordinary E2E tests. Every test gets
  fresh emulator state and an isolated failure directory.
- Reach states through normal inputs when the claim concerns gameplay. State
  injection is suitable for a callable-ROM unit test, not evidence that a
  player can reach or leave a scene.
- Use bounded waits with a named condition. Timeouts should save a descriptive
  screenshot and fail, never spin forever.
- Read runtime state observationally. A test must not repair the state it is
  trying to verify.
- Keep all mutable state local to the test or fixture. Never depend on test
  order, shared `PyBoy` instances, or mutable module globals.
- Treat ROMs, symbol files, scenarios, and committed snapshots as read-only.
- Give each visual assertion a descriptive artifact or snapshot name. Update a
  committed snapshot only after understanding and approving the visual change.
- Preserve versioned schemas, manifests, typed provenance, and attempt
  directories. Generate derived evidence with its official generator instead
  of editing JSON by hand.
- Add semantic assertions around the picture: map, coordinates, script state,
  battle/menu state, renderer generation, palette data, and attributes as
  appropriate. A screenshot alone is weak evidence.

Pytest can distribute the suite across up to four workers. Tests following
these isolation rules need no hand-maintained CI list.

## False confidence and flakiness traps

- A plausible screenshot can hide corrupt tile IDs, stale attributes, broken
  OAM, or a script that never completed. Assert state as well as pixels.
- One captured frame cannot rule out flicker, late VBlank writes, or animation
  corruption. Exercise movement and boundaries over time.
- Synthetic conformance validates the checker, not the ROM renderer.
- Callable-ROM tests validate controlled entry points, not natural call order.
- PyBoy is practical and deterministic here, but it is not a cycle-accurate
  hardware oracle. Keep timing margins conservative and investigate failures
  on another emulator or hardware when timing is suspect.
- Do not derive expected values from the same VRAM observation being tested.
  Expectations must come from an independent contract, known stock product, or
  reviewed data authority.
- Natural encounters involve RNG. Bound searches, record RNG and step counts,
  and assert eventual semantic outcomes instead of one magic frame number.
- A leftover canonical screenshot or report can make a broken run look green.
  Use attempt-scoped outputs and verify the current attempt status.
- Stock/audit parity is intentionally selective: palette and attribute state
  may differ in the colored slice. Tile data, scripts, OAM, menus, battles, and
  other Yellow-owned behavior must retain the intended parity.

## Gates that must not be weakened

Do not “fix” a failure by reducing the proof. Preserve:

- pinned test dependencies and the pinned RGBDS toolchain;
- bounded timeouts and retained failure screenshots/diagnostics;
- two independent Gate 0 and runtime evidence captures;
- byte-identical stable-evidence comparison;
- the blocking hosted Gate 0 comparator;
- the distinction between synthetic checker evidence and real-ROM evidence;
- Phase 1 runtime ownership evidence;
- Phase 2 audit exclusion from normal release, debug, and VC products;
- exact inventory closure, reviewed source/ROM discovery, typed provenance, and
  mutation sensitivity;
- observational runtime reads and fresh emulator state;
- semantic assertions alongside visual artifacts;
- natural cold-boot journeys for claims about playability.

If a gate is wrong, repair the contract and document why. Don’t loosen it until
the current implementation slips through.

## Where to look when something fails

- Harness usage and fixture basics:
  [`tools/rom_tests/README.md`](../../tools/rom_tests/README.md)
- Gate 0 orchestration:
  [`gate0_runner.py`](../../tools/rom_tests/full_color/gate0_runner.py)
- Synthetic conformance runner:
  [`renderer_conformance_runner.py`](../../tools/rom_tests/full_color/renderer_conformance_runner.py)
- Phase 1 real-ROM runner:
  [`renderer_runtime_runner.py`](../../tools/rom_tests/full_color/renderer_runtime_runner.py)
- Phase 2 representation audit:
  [`phase2_measurements.py`](../../tools/rom_tests/full_color/phase2_measurements.py)
- Formal verification rationale:
  [`verification-plan.md`](../../specs/full-colors/docs/verification-plan.md)
- Known renderer failures and resolved glitches:
  [`../bugs_and_glitches.md`](../bugs_and_glitches.md)
