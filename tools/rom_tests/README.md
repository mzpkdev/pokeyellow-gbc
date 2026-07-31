# ROM tests

Create the ignored repo-local virtualenv and install the pinned test
dependencies from the repository root:

```console
make test-full-color-setup
make test-full-color-gate0
```

The full-color Make targets prefer `.venv/bin/python` when it exists and fall
back to `python3` in managed environments such as CI. For a focused local loop,
run `.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q`.

`test-full-color-gate0` builds the debug ROM, then performs two independent
executions of the complete fast unit suite, baseline discovery, the reviewed
initial map-entry inventory slice, synthetic bank torture, debug-ROM runtime
observability, specification traceability, and the visual artifact pipeline.
The runner byte-compares all stable evidence, explicitly including the semantic
snapshot, traceability report, and versioned visual manifest. Each invocation is retained under
`test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`. A failed attempt
keeps its structured status plus unit-test JUnit, component stdout, stderr, and
any emulator diagnostics; it never starts later components or overwrites an
earlier successful attempt. Override the common evidence root, including with a
path containing spaces, using `FULL_COLOR_RESULTS=/path/to/results`. Runtime
diagnostics are routed below that root rather than written to a repo-local
fallback.

The narrower commands remain intentionally stable: `test-full-color-smoke`
boots the debug ROM and retains each snapshot, report, diagnostics, and status
under `$(FULL_COLOR_RESULTS)/smoke/attempt-NNNN`, so a failed rerun cannot leave
stale canonical output or destroy the prior success. `test-full-color-handoffs`
runs focused ownership-model handoff/reset tests, `test-full-color-soak` runs
seeded model sequences, and `test-full-color-all` combines Gate 0 with both
model-focused commands.

Pytest distributes the complete suite across up to four worker processes. New
tests are included automatically; no CI job or test list needs to be updated.

Tests are grouped by intent:

```text
tests/
├── unit/  # Fast tests that do not need a built ROM
└── e2e/   # Gameplay and visual scenarios that run the ROM in PyBoy
```

Place new tests in the appropriate directory. CI discovers every test in that
directory automatically.

## Writing parallel-safe tests

- Request the shared `emulator` fixture instead of constructing or sharing a
  `PyBoy` instance. Each test receives fresh emulator state and its own failure
  output directory.
- Treat the built ROM, symbol file, scenarios, and snapshots as read-only.
- Give every visual assertion its own committed snapshot and descriptive
  `name`.
- Keep state needed by a test inside that test or its fixtures. Do not depend on
  test order or mutable module-level state.

Tests that follow these rules can run locally, in CI, and alongside future tests
without special parallelization configuration.
