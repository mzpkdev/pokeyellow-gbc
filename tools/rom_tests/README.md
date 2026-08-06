# ROM tests

Create the ignored repo-local virtualenv and install the pinned test
dependencies from the repository root:

```console
make test-full-color-setup
make test-full-color-fast
```

The full-color Make targets prefer `.venv/bin/python` when it exists and fall
back to `python3` in managed environments such as CI. For a focused local loop,
run `.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q`.

Use `make test-full-color-fast` while iterating and
`make test-full-color-certify` before handoff. Fast is focused
production-foundation feedback; it is not certification. Its warm supported-
workstation target is at most 60 seconds. Certify requires the pinned
`.references/pokered-gbc` donor checkout and is the only local command that
claims every retained authority passed. Set `FULL_COLOR_OUTPUT=json` for one
canonical machine-readable summary instead of human `RUN`/`PASS` lines.

Both profiles announce an attempt under
`test-results/full-color-harness/attempt-NNNN` before resolving or running
components. Fast runs, in order: all four product builds, production-linkage
and Phase 1 runtime-ROM tests, Phase 2 audit verification, retained smoke,
renderer conformance, and renderer runtime ownership. Certify runs, in order:
all four product builds, exact donor provenance, Gate 0, Phase 2 audit
verification, renderer conformance, renderer runtime ownership, cold-boot
journeys, handoffs, and soak. The aggregate summary links to each authority's
dedicated evidence root and complete stdout, stderr, and pytest JUnit; it does
not copy, rename, or substitute that authority's evidence. Certify routes the
cold-boot file to the current attempt's `components/cold-boot-journeys/` root;
running that file directly preserves its narrow
`test-results/full-color-cold-boot/` default.

The normal, debug, and VC products all include the saved Color/Yellow toggle
and passive renderer for the supported `OVERWORLD` and conventional-interior
map slice. Production-linkage proves the previously retained shared runtime
surface while excluding Phase 2-only diagnostics; it does not by itself prove
the expanded interior content. Natural
runtime tests select Color and Yellow inside one shipped binary; the
`PHASE2_AUDIT` product is an additional diagnostic/certification surface, not a
behavioral variant.

`test-full-color-gate0` builds the debug ROM, then performs two independent
executions of the complete unit tree (apart from the separately invoked donor
comparator), baseline discovery, the reviewed
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

The narrower commands remain intentionally stable for diagnosis:
`verify-full-color-phase2-audit`, `test-full-color-smoke`,
`test-full-color-renderer-conformance`, `test-full-color-renderer-runtime`,
`test-full-color-gate0`, `test-full-color-handoffs`, and
`test-full-color-soak`. `test-full-color-smoke`
boots the debug ROM and retains each snapshot, report, diagnostics, and status
under `$(FULL_COLOR_RESULTS)/smoke/attempt-NNNN`, so a failed rerun cannot leave
stale canonical output or destroy the prior success. `test-full-color-handoffs`
runs focused ownership-model handoff/reset tests, `test-full-color-soak` runs
seeded model sequences. `test-full-color-all` remains the unchanged legacy
compatibility aggregate; it is not certification.

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
