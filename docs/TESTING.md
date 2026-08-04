# Testing the ROM hack

This project tests a running Game Boy ROM, not just assembly source. A useful
test must say which claim it proves: a pure rule, a linked-ROM property, a
callable routine, a naturally reached gameplay state, or a visual result. No
single green command proves the game is playable and visually correct.

The harness lives under [`tools/rom_tests`](../tools/rom_tests/), its executable
targets are in the repository [`Makefile`](../Makefile), and hosted automation
is defined in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for runtime ownership and
[`ADDING_CONTENT.md`](ADDING_CONTENT.md) for adding maps and content.

## Test layout

The ROM-hack-wide harness is split by purpose:

```text
tools/rom_tests/
├── emulator.py          # PyBoy wrapper and runtime inspection helpers
├── scenarios/           # Reusable player-input journeys
├── snapshots/           # Reviewed visual expectations
├── tests/
│   ├── unit/            # Fast contracts, models, and isolated checks
│   └── e2e/             # Gameplay and visual checks against a running ROM
├── fixtures/            # Read-only inputs for specialized checkers
└── full_color/           # Full-color evidence runners and contracts
```

Keep navigation in `scenarios/` and assertions in `tests/e2e/`. Existing
scenario modules compose a natural new-game path through Oak's lab, Viridian
City, and parcel delivery. Extend those reusable journeys instead of copying
long input sequences into every test.

Generated diagnostics belong under `test-results/`, which is ignored. Reviewed
snapshots live in `tools/rom_tests/snapshots/` and are committed deliberately.
ROMs, symbol files, scenarios, fixtures, and committed snapshots are read-only
test inputs.

## Set up and run the general suite

From the repository root, create the ignored virtual environment and install
the pinned dependencies:

```console
make test-full-color-setup
```

The target has a historical full-color name, but it sets up the shared ROM test
harness. Make targets prefer `.venv/bin/python` locally and fall back to
`python3` in managed environments.

Build the normal products and run the general unit suite:

```console
make -j"$(nproc)" yellow yellow_debug yellow_vc
make yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/unit -q
```

Run all current gameplay journeys locally with:

```console
make yellow_debug
.venv/bin/python -m pytest tools/rom_tests/tests/e2e -q
```

The E2E suite expects `pokeyellow_debug.gbc` and `pokeyellow_debug.sym` unless a
test or environment selects another product. Full-color journeys select Color
or Yellow inside that same shipped binary; they do not use the audit product as
a behavioral variant. Use a focused file or `-k` expression while iterating.

## Writing a gameplay test

Every gameplay test should follow the same contract:

- For an ordinary single-product test, request the shared `emulator` fixture.
  Despite its name, the instance is not shared between tests: the fixture
  creates one fresh PyBoy instance and one isolated result directory for each
  test, then guarantees cleanup.
- A paired or multi-product comparison must explicitly create one fresh
  `Emulator` per product. Give every instance its own isolated result
  directory, close every instance in a `finally` block, and never reuse mutable
  emulator state between the products.
- Reach the state through normal player inputs when the claim is about
  playability. Direct memory setup belongs in an isolated callable-ROM test,
  not in evidence that a player can enter or leave a scene.
- Wait for named semantic conditions with a hard bound. A timeout must retain a
  descriptive screenshot or diagnostic; it must never spin forever.
- Observe runtime state without repairing it. A test cannot write the value it
  then claims the game produced.
- Keep mutable state inside the test or fixture. Never depend on test order, an
  emulator instance from another test or product, or mutable module globals.
- Assert meaning as well as pixels: map and coordinates, script phase,
  battle/menu state, tile or OAM state, and relevant renderer state.
- Give every visual assertion a descriptive snapshot or artifact name. Update
  a committed snapshot only after inspecting and approving the change.

A screenshot is supporting evidence, not the entire verdict. Plausible pixels
can conceal corrupt tile IDs, stale attributes, broken OAM, or a script that
never completed. Likewise, one frame cannot rule out flicker or late VBlank
writes; exercise movement, animation, and transitions over time.

PyBoy is deterministic and practical, but it is not a cycle-accurate hardware
oracle. Keep timing margins conservative. Recheck suspicious timing failures in
another emulator or on hardware before changing a runtime contract.

## Fast feedback and certification

| Intent | Command | Claim |
|---|---|---|
| inner loop | `make test-full-color-fast` | focused production-foundation feedback, with a warm target of at most 60 seconds |
| pre-handoff | `make test-full-color-certify` | every retained local authority passed |
| diagnosis | existing narrow `test-full-color-*` targets | only the named subsystem |
| compatibility | `make test-full-color-all` | legacy aggregate, not certification |

Fast is explicitly not certification. It runs these exact ordered components:
`build-products`, `production-linkage`, `phase2-audit`, `smoke`,
`renderer-conformance`, and `renderer-runtime`. Production linkage runs both
the production color-mode linkage and Phase 1 runtime-ROM ownership tests. The
first component visibly builds exactly the release, debug, VC, and Phase 2
audit products.

Certify is the only local ready-to-handoff claim. It runs these exact ordered
components: `build-products`, `donor-provenance`, `gate0`, `phase2-audit`,
`renderer-conformance`, `renderer-runtime`, `cold-boot-journeys`, `handoffs`,
and `soak`. Donor provenance resolves the workspace authority at
`.references/pokered-gbc`, verifies its exact pinned origin, HEAD, and cleanup
parent, then invokes the exact donor comparator without a skip. Gate 0 retains
both complete independent runs and its Exact comparator. The other authorities
remain the Phase 2 verifier, mutation-sensitive synthetic conformance checker,
two-fresh-emulator Phase 1 ownership runner, natural cold-boot journey file,
focused handoff/reset model tests, and seeded soak sequences. There is no third
full-unit invocation outside Gate 0 and no duplicate donor or cold-boot
component.

Both profiles retain complete component stdout and stderr plus JUnit for pytest
components below an attempt-scoped aggregate root. Each retained runner gets a
dedicated evidence root. `summary.json` only links those outputs; it never
copies, relabels, or promotes evidence from one authority into another. Human
mode prints bounded progress. Use
`FULL_COLOR_OUTPUT=json make test-full-color-fast` (or certify) for exactly one
canonical JSON summary.

## Fast-to-slow development loop

For any ROM-hack change, climb only as far as the claim and blast radius demand:

1. Run the focused pytest file or `-k` expression.
2. Run `.venv/bin/python -m pytest tools/rom_tests/tests/unit -q`.
3. Build every affected ROM product.
4. Run the focused natural gameplay journey.
5. Run `.venv/bin/python -m pytest tools/rom_tests/tests/e2e -q` when shared
   scenarios, menus, scripts, rendering, or transitions changed.
6. Inspect new or changed screenshots and retained diagnostics manually.
7. Run `make test-full-color-fast` for focused production-foundation feedback.
8. Run initiative-specific narrow gates when their contracts are affected.
9. Run `make test-full-color-certify` before handing off full-color work.
10. Push and wait for every hosted check to complete.

Do not translate “CI is green” into “the ROM was playtested.” Hosted CI runs the
complete unit directory and the specialized full-color jobs described below,
but it does **not** run `tools/rom_tests/tests/e2e`. Natural gameplay E2E and a
human playtest remain local release evidence.

## What hosted CI covers

Full `CI` runs only for commit-bearing events: opening a pull request and
synchronizing a new commit. Pushes to `main` retain release certification. A
new PR commit cancels obsolete in-flight full CI for that pull request, while
title/body edits, reopening, and draft-state changes run only the lightweight
`PR Metadata` workflow and cannot cancel certification. Reopening fails closed
unless the exact current head SHA already has a successful `Test` check. It
emits a durable `PR Reopen Certification` context; every other metadata event
emits `PR Title`. Per-PR, per-action concurrency prevents a later edit or
draft-state change from cancelling or replacing the reopen result, while an
obsolete repeated run of the same action may still be cancelled.

The hosted workflows provide these signals:

- `PR Title` checks the Conventional Commit title without checkout, dependency
  installation, ROM build, emulator use, or evidence production.
- `PR Reopen Certification` runs the same title check on reopen and also proves
  that the exact reopened head already has a successful `Test` check.
- `Lint` checks the workflows.
- `Build` produces release, debug, and VC ROMs and rejects build-generated
  changes to tracked files.
- two `Gate 0 Baseline Run` jobs each install pinned RGBDS, build the Phase 2
  audit ROM, and execute the complete seven-component Gate 0 independently;
  the blocking `Gate 0 Baseline` job compares their byte-exact stable evidence;
- `Renderer Conformance Checker` exercises the synthetic checker corpus;
- `Phase 1 Runtime Ownership` captures real-ROM ownership evidence;
- `Test` is the fail-closed final aggregator over donor provenance, lint, build,
  the Gate 0 comparator, conformance, and runtime ownership. It runs no third
  copy of the full unit tree.

Because `main` currently has no branch protection rule or ruleset, reviewers
must check `Test`, the latest `PR Title`, and `PR Reopen Certification` after a
reopen. The reopen context exists only for reopened events and therefore must
not be made a universally required branch-protection context.

Hosted targets are a first useful log within 1 second, focused warm feedback
within 60 seconds, and no duplicate full CI run for one PR head SHA. Gate 0
component durations should be recorded when evaluating orchestration changes.
A scheduling or cache follow-up must compare pytest `--dist=load` with
`--dist=loadscope` across three clean repetitions and demonstrate at least 15%
wall-time improvement with identical collected test counts, failures, and
retained mutation outcomes. Until that evidence exists, persistent discovery
caches, unit sharding, and pytest scheduling changes remain deferred. Gate 0
runs never share evidence or mutable emulator state.

Hosted CI does not invoke `tools/rom_tests/tests/e2e`, and it does not invoke
`make verify-full-color-phase2-audit` as a standalone gate. Run the relevant
natural journey, formal Phase 2 verification, and human visual review locally.

## Full-color evidence stack

Full-color work adds four complementary proof layers. The formal contracts live
under [`specs/full-colors`](../specs/full-colors/), and their planned growth is
defined by the
[`migration-plan.md`](../specs/full-colors/docs/migration-plan.md). A Phase 2
green result grants no acceptance credit to later phases. Phase 3 adds
palette/effect and paired-transfer proof; Phase 4 adds OAM; Phase 5 adds
architecture stress; Phase 6 closes bounded Pallet Town/Route 1 content and
animation/field-replacement obligations; Phase 7 closes handoffs; Phase 8
proves obsolete ownership is gone; and Phase 9 hardens timing and release
behavior. All-25-tileset and all-map color remain later non-gating work.

Build the shipped debug product before specialized gameplay checks:

```console
make yellow_debug
```

Normal release, debug, and VC products all include the bounded passive runtime
and saved toggle. `pokeyellow_phase2_audit.gbc` adds diagnostic and
certification surfaces only; `PHASE2_AUDIT` MUST NOT change renderer behavior.

### Contracts, models, and linked-ROM checks

Fast full-color contracts and models cover schemas, inventories, ownership,
scheduling, palette transforms, evidence readers, and deterministic sequences:

```console
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q
```

That tree also inspects linked `.gbc`, `.sym`, and `.map` products and calls
named assembly routines through the emulator. Focused examples are:

```console
make yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color/test_phase2_layout.py -q
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color/test_phase2_palettes_rom.py -q
```

A callable-ROM test proves a routine under controlled state. It does not prove
that normal gameplay reaches the routine in the correct order.

### Retained deterministic gates

These commands retain structured evidence under `test-results/`:

```console
make test-full-color-smoke
make verify-full-color-phase2-audit
make test-full-color-renderer-conformance
make test-full-color-renderer-runtime
make test-full-color-gate0
make test-full-color-handoffs
make test-full-color-soak
make test-full-color-all
make test-full-color-fast
make test-full-color-certify
```

Their claims are deliberately narrow:

- `test-full-color-smoke` boots the debug ROM and retains attempt-scoped
  snapshots, diagnostics, reports, and status.
- `verify-full-color-phase2-audit` binds the audit product to the selected
  Phase 2 representation, discovery, inventory, provenance, and product
  identities. It neither plays the slice nor judges its appearance.
- `test-full-color-renderer-conformance` is a **synthetic checker self-test**.
  It proves acceptance of canonical fixtures and rejection of named mutations,
  not that the ROM renderer works.
- `test-full-color-renderer-runtime` captures the selected Phase 1 real-ROM
  ownership case twice. It proves ownership replacement for that case, not
  global color correctness or playability.
- `test-full-color-handoffs` and `test-full-color-soak` exercise focused model
  transitions and seeded valid sequences.

Despite its name, `test-full-color-all` remains the unchanged compatibility-only
legacy aggregate of Gate 0, conformance, Phase 1 runtime, handoff, and soak
checks. It is not certification. It does **not** run Phase 2 verification,
donor provenance, or cold-boot E2E; use `test-full-color-certify` for the local
handoff claim.

The retained roots are:

- Gate 0: `test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`;
- smoke: `test-results/full-color-gate0/smoke/attempt-NNNN`;
- conformance:
  `test-results/full-color-renderer-conformance/attempt-NNNN`;
- Phase 1 runtime: `test-results/full-color-renderer-runtime/attempt-NNNN`;
- direct cold-boot E2E: `test-results/full-color-cold-boot/`;
- certify cold-boot E2E:
  `test-results/full-color-harness/attempt-NNNN/components/cold-boot-journeys/`;
- reviewed Phase 1 and Phase 2 evidence: `specs/full-colors/evidence/`.
- fast/certify aggregate: `test-results/full-color-harness/attempt-NNNN`.

The deterministic runners accept their corresponding `FULL_COLOR_*_RESULTS`
Make variables when evidence must be routed outside the default tree. Never
edit generated JSON by hand; use its official generator and review the diff.

The `measure-full-color-*` targets are discovery commands, not acceptance
commands. They write explicitly unreviewed, disposable proposals beneath
`test-results/full-color-proposals/` (override with `FULL_COLOR_PROPOSALS`) and
MUST NOT rewrite the checked-in source transition, four reviewed inventories,
or Phase 1/Phase 2 evidence. `measure-full-color-phase2-audit` runs the complete
proposal chain and leaves:

- `phase1-source-transition.proposal.json`;
- `audit-evidence-identities.proposal.json`, whose hash-only changes name all
  four inventory authority paths and contain no reviewer metadata;
- `phase2-subjects.proposal.json`, whose top-level `reviewed` value is false.

There is deliberately no Make target that promotes those files. A human must
review the subject and semantic deltas, deliberately edit the corresponding
checked-in authorities, and supply reviewer metadata based on that review.
Only after that boundary may the official Phase 1/Phase 2 evidence producer be
run against the accepted authorities. Phase 2 requires the explicit
`--authority-reviewed` acknowledgement before it will write accepted evidence;
the flag does not add reviewer metadata or accept any discovery subjects.
`verify-full-color-phase2-audit` is strictly read-only: it recomputes current
evidence, byte-compares the checked-in record, and fails closed on any mismatch.

### Natural full-color gameplay

The cold-boot file starts at boot and reaches states through player inputs. Its
player-facing journeys select Yellow and Color in the shipped normal binary;
two scenarios use the debug product where a debug control is part of setup.
Every journey records logical state, renderer state, VRAM, OAM, palettes,
attributes, and screenshots:

```console
make yellow yellow_debug
.venv/bin/python -m pytest tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
```

Its two harness tests protect setup behavior. Its eight gameplay journeys cover
bedroom-to-Viridian progression, paired northbound parity, reverse Route 1
ledges, Red's house fallback, Oak's capture cutscene, dialogue/menu/party
boundaries, a natural wild-battle round trip, and save/reset/Continue.

Direct failures are retained under `test-results/full-color-cold-boot/`.
Certify overrides that narrow default with its current attempt's dedicated
`components/cold-boot-journeys/` root, so later or concurrent attempts cannot
clean or relink earlier evidence. This file is part of the locally run E2E
suite and is not currently run by hosted CI.

## Gate 0 contract

`make test-full-color-gate0` performs two independent executions. Each stops at
the first failure and covers, in order:

1. the complete unit tree apart from the separately invoked donor comparator;
2. baseline source/ROM discovery;
3. reviewed inventory reconciliation;
4. synthetic bank-boundary torture;
5. debug-ROM runtime observability;
6. specification traceability;
7. the visual artifact pipeline.

Attempts live under
`test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`. Every stable
evidence file must exist in both runs and be byte-identical; the comparator
explicitly checks the semantic snapshot, traceability report, and versioned
visual manifest. Failures retain status, JUnit, stdout, stderr, and emulator
diagnostics without overwriting earlier attempts.

Override the evidence root, including with spaces, using:

```console
make test-full-color-gate0 FULL_COLOR_RESULTS="/tmp/pokeyellow gate0"
```

Hosted CI runs `Gate 0 Baseline Run 1` and `Run 2` in parallel, uploads both
products, then blocks on `Gate 0 Baseline`, which applies the same byte
comparison. Parallel execution is an optimization; two complete independent
runs and a successful comparison remain the contract.

## Full-color completion ladder

Use this ordering for renderer work:

1. one focused pytest file or `-k` expression;
2. `make test-full-color-fast`;
3. a stable narrow command for any failed or specially affected authority;
4. the focused natural gameplay journey and manual frame review when relevant;
5. `make test-full-color-certify` before handoff.

For renderer work, “green” means relevant local checks passed, retained
artifacts agree with their claim, screenshots were inspected, and hosted CI
completed successfully.

## False-confidence traps

- Never derive an expected value from the same VRAM observation being tested.
  Use an independent contract, known stock product, or reviewed data authority.
- Synthetic conformance validates the checker, not the running renderer.
- State-injected callable tests validate entry points, not natural call order.
- Natural encounters involve RNG. Bound searches, retain RNG and step counts,
  and assert eventual semantic outcomes instead of a magic frame number.
- Stale canonical screenshots or reports can make a broken run look green. Use
  attempt-scoped outputs and check the current attempt status.
- Yellow/Color parity within one shipped binary is selective: palettes and
  attributes may differ in the colored slice. Tile data, scripts, OAM, menus,
  battles, and other Yellow-owned behavior must retain intended parity.

## Gates that must not be weakened

Preserve these constraints when repairing or extending the harness:

- pinned test dependencies and pinned RGBDS;
- bounded timeouts with retained failure screenshots and diagnostics;
- fresh emulator state and observational runtime reads;
- semantic assertions alongside visual artifacts;
- natural cold-boot journeys for playability claims;
- two independent Gate 0 and Phase 1 runtime captures;
- byte-identical stable-evidence comparison and the blocking hosted comparator;
- the separation between synthetic checker and real-ROM evidence;
- Phase 1 runtime ownership evidence;
- inclusion of the same toggle and bounded passive runtime in release, debug,
  and VC products, with Phase 2 diagnostics still excluded from them;
- inventory closure, reviewed discovery, typed provenance, and mutation
  sensitivity.

If a gate is wrong, repair its contract and document why. Do not reduce its
proof until the current implementation happens to pass.

## Failure map

- Shared fixtures and emulator usage:
  [`tools/rom_tests/README.md`](../tools/rom_tests/README.md)
- Gate 0 orchestration:
  [`gate0_runner.py`](../tools/rom_tests/full_color/gate0_runner.py)
- Synthetic conformance:
  [`renderer_conformance_runner.py`](../tools/rom_tests/full_color/renderer_conformance_runner.py)
- Phase 1 real-ROM evidence:
  [`renderer_runtime_runner.py`](../tools/rom_tests/full_color/renderer_runtime_runner.py)
- Phase 2 representation audit:
  [`phase2_measurements.py`](../tools/rom_tests/full_color/phase2_measurements.py)
- Formal full-color rationale:
  [`verification-plan.md`](../specs/full-colors/docs/verification-plan.md)
- Historical Pokémon Yellow bugs and their known status:
  [`BUGS_AND_GLITCHES.md`](BUGS_AND_GLITCHES.md)
