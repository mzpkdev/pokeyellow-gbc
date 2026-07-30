# ROM tests

Install the test dependencies and run the suite from the repository root:

```console
python -m pip install -r tools/rom_tests/requirements.txt
python -m pytest
```

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
