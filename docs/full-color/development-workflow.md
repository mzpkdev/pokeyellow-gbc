# Full-color development workflow

This is the operating guide for resuming the full-color work after a context
switch. Read [Architecture](architecture.md) before changing runtime code,
[Verification harness](verification-harness.md) before interpreting a green
test, and [Extending the slice](extending.md) before adding a map or palette.
Known historical failure modes are recorded in
[Bugs and glitches](../bugs_and_glitches.md).

## Current truth

The playable color implementation is the **Phase 2 audit product**,
`pokeyellow_phase2_audit.gbc`. It passively colors Pallet Town and Route 1.
Interiors, menus, battles, cutscenes, sprites, animation, and every map outside
that slice remain under Pokemon Yellow's existing visual behavior.

The normal products (`pokeyellow.gbc`, `pokeyellow_debug.gbc`, and the VC
patch) deliberately do not link or expose the Phase 2 passive runtime. The
audit ROM is evidence and a playable canary, not yet a release ROM. Never
describe the normal ROM as colored, and never make the audit runtime reachable
there merely to simplify a test.

The contract is simple and load-bearing: Yellow owns tile bytes, sprites,
animations, cutscenes, menus, battle presentation, fades, overlays, and the
schedule. The passive slice may add CGB background palettes and bank-1 map
attributes without changing those owners. If a color change needs to replace
Yellow's tile or sprite production, it is outside this slice.

## Start of a session

Begin at the repository root and establish what actually exists before making
assumptions from yesterday's notes:

```console
git status --short --branch
git log -5 --oneline --decorate
git diff --stat
git diff
```

Preserve unrelated or untracked work. In particular, do not add, remove, or
rewrite `.preemdeck/` as part of renderer work. Check the active pull request
and hosted checks if the branch already has one; local files alone do not tell
you whether the last push is green.

Set up the pinned Python environment once per checkout, then build both the
stock debug reference and the playable audit ROM:

```console
make test-full-color-setup
make yellow_debug yellow_phase2_audit
```

`pokeyellow_phase2_audit.gbc` is the ROM to play when reviewing current color
work. `pokeyellow_debug.gbc` is the paired Yellow reference. Keep both built
from the same source revision. If their `.gbc`, `.sym`, or `.map` files came
from different revisions, rebuild before diagnosing anything.

## Development loop: fast to slow

Use the cheapest check that can disprove the current change, then widen the
circle. A practical loop is:

1. Run the focused unit or ROM-backed test for the code being changed.
2. Run the full full-color unit directory:

   ```console
   .venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q
   ```

3. Build the audit product and verify its Phase 2 evidence:

   ```console
   make yellow_phase2_audit
   make verify-full-color-phase2-audit
   ```

4. Run the narrow smoke and renderer checks:

   ```console
   make test-full-color-smoke
   make test-full-color-renderer-conformance
   make test-full-color-renderer-runtime
   ```

5. Run the natural cold-boot journeys against paired, freshly built ROMs:

   ```console
   make yellow_debug yellow_phase2_audit
   .venv/bin/python -m pytest tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
   ```

6. Play `pokeyellow_phase2_audit.gbc` and inspect motion and transitions, not
   just stationary screenshots.
7. Before handoff, run the retained gates:

   ```console
   make test-full-color-gate0
   make test-full-color-all
   ```

`test-full-color-all` does **not** include
`verify-full-color-phase2-audit` or the cold-boot E2E file. Run those explicitly.
The conformance checker is a synthetic checker; passing it does not prove that
the ROM is playable or visually correct. Gate 0 protects the retained baseline
and evidence system; it does not replace the natural journey or a human review.

## Manual visual review

Start from a cold boot. Do not load an emulator save state made by another ROM
revision. At minimum, play through the Game Freak logo, Oak's introduction,
the bedroom, Pallet Town, Oak's interception and Pikachu capture, Route 1,
Viridian entry, and the return trip. Exercise a house transition, dialogue,
Start and party menus, a Route 1 wild battle, save/reset/Continue, scrolling in
both directions, and the Route 1 ledges.

Look for behavior over several frames:

- the boot and non-slice scenes remain legible and Yellow-like;
- Pallet Town and Route 1 gain stable background color;
- tile shapes and positions match the stock debug ROM;
- NPCs, Pikachu, the Poké Ball animation, windows, and text remain intact;
- menus, battles, interiors, and Viridian fall back cleanly;
- returning to the slice restores color without stale rows or columns;
- scrolling produces no seams, flashes, delayed strips, or one-frame palette
  swaps.

Compare suspicious scenes with `pokeyellow_debug.gbc` at the same gameplay
point. A single attractive screenshot proves almost nothing: it misses flicker,
timing faults, transitions, input deadlocks, and corruption that appears only
after several redraws.

## Failure triage

### White screen or progression stops

Treat this as a runtime/control-flow failure, not a palette-design problem.
Reproduce from cold boot, note the last working scene and input, and compare the
stock debug ROM. Check whether the audit ROM, symbols, and map file were rebuilt
together. Preserve any failure screenshot and emulator diagnostics before
rerunning. If the stock debug ROM also fails, first suspect the scenario,
toolchain, or unrelated Yellow change; if only the audit ROM fails, narrow the
first audit-only entry reached before the stall.

### Corrupt or mismatched tiles

Wrong shapes, repeated fragments, checkerboards, or a cutscene drawn over an
overworld are not "ugly palettes." They indicate tile bytes, tile indices,
attribute coordinates, VRAM bank selection, map wrap, or transition cleanup
are wrong. Compare the same frame with stock debug. The bank-0 tilemap and
Yellow-owned graphics should agree; only CGB palette state and bank-1
attributes are expected to differ in the slice. Stop palette tuning until that
structural mismatch is fixed.

### Correct geometry, wrong colors

If shapes and positions match stock but a roof, ground, or object has the wrong
color, inspect the palette payload and tile-to-attribute authority described in
[Extending the slice](extending.md). Do not hide a map-specific palette problem
with a broader allowlist. For example, merely allowing Viridian to reuse the
Pallet/Route 1 table is not correct Viridian support.

### Flicker, seams, or intermittent corruption

Assume scheduling or timing until disproved. Record direction, map boundary,
and whether dialogue, animation, or a redraw happened in the same frame. Check
row and column scrolling repeatedly and review frame strips/diagnostics rather
than only the final screenshot. Yellow's redraw and animation work retains
priority; passive palette or attribute work must defer or clear in bounded
chunks without pushing Yellow's writers outside their safe window.

### Stale or contradictory evidence

Every retained runner writes a new `attempt-NNNN`; do not copy an old green
summary over a new failure or judge the current source by the newest-looking
PNG. Match the attempt's manifest/status, ROM identity, and revision. Rebuild
paired products and rerun the failing command into a fresh attempt. Evidence
files under `specs/full-colors/evidence/` are reviewed inputs/outputs, not a
license to regenerate until a check turns green.

### Audit-only code appears in a normal product

This is a release-boundary regression. Stop feature work and run
`make verify-full-color-phase2-audit`. The normal release, debug, and VC
products must not expose the Phase 2 audit entries. Do not weaken the identity,
reachability, or provenance checks to accept leakage.

## Where evidence lands

- Gate 0: `test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`
- Smoke: `test-results/full-color-gate0/smoke/attempt-NNNN`
- Renderer conformance:
  `test-results/full-color-renderer-conformance/attempt-NNNN`
- Renderer runtime: `test-results/full-color-renderer-runtime/attempt-NNNN`
- Natural gameplay screenshots and diagnostics:
  `test-results/full-color-cold-boot/`
- Per-test emulator failure directories: `test-results/<test-derived-name>/`
- Reviewed Phase 1 and Phase 2 evidence: `specs/full-colors/evidence/`
- Built products and identities: repository-root `.gbc`, `.sym`, and `.map`
  files

These result directories are diagnostic output. Review the status/manifest and
the files it names as one set. Keep successful and failed attempts distinct.

## Handoff and commit discipline

Before handing work to another session or pushing it:

1. Review `git status`, the complete diff, and every new file.
2. Verify unexpected changes belong to the task; preserve concurrent work.
3. Run the relevant focused check, Phase 2 verification, cold-boot journey,
   manual playthrough, Gate 0, and the aggregate gate as appropriate.
4. Record exact commands and outcomes. Say which checks were not run.
5. Record which ROM was manually played, the route taken, and any retained
   artifact directories worth reviewing.
6. Stage exact paths. Do not use a blanket add in a dirty worktree.
7. Commit only the reviewed paths, push the feature branch, update the pull
   request with verified facts, and watch hosted CI to completion.

Do not let implementation workers commit or push. A fresh read-only review
should inspect each green phase; verify each finding against source and runtime
evidence before changing code. Green tests do not make an unverified finding
true, and a critic's suspicion does not make it a bug.

## Direction and decision ledger

### What exists now

- A playable, audit-only passive color slice for Pallet Town and Route 1.
- One complete overworld palette payload and tile-to-attribute table for that
  deliberately narrow slice.
- Paired stock/audit natural journeys covering boot, movement, boundaries,
  menus, battles, Oak's capture, fallback, return, and save/Continue.
- Retained architecture and harness seams for broader renderer work, without
  pretending those seams are the active player-facing runtime.

### Decisions that remain in force

- Yellow owns gameplay presentation; Phase 2 adds palette color only.
- Normal products stay stock until a later phase is explicitly approved for
  release integration.
- Pallet Town and Route 1 are the only claimed colored maps.
- Gate 0, Phase 1 runtime evidence, Phase 2 identity/provenance checks, the
  synthetic checker, paired journeys, and manual review remain complementary;
  none may be weakened to make another pass.
- A map is not supported merely because it was added to an allowlist. Its
  tileset, palette, roofs, transitions, scrolling, overlays, and fallback must
  be correct and evidenced.

### Phases 3–9 direction

Use the authoritative
[migration plan](../../specs/full-colors/docs/migration-plan.md), not a vague
“future Phase 3” bucket. Phase 3 completes palette/effect and paired-transfer
architecture. Phase 4 adds overworld OAM color. Phase 5 stress-proves the
architecture. Phase 6 authors and accepts all 25 tilesets, roofs, overrides,
and other content. Phase 7 closes every handoff. Phase 8 deletes obsolete
Yellow overworld ownership. Phase 9 hardens timing and release/debug/VC builds.

Each phase must close its inventory before making changed paths reachable and
must pass its own exit gate. For Viridian specifically, Phase 3 supplies the
map-aware palette/transfer mechanism; Phase 6 supplies and accepts correct
roof/content data. Neither milestone can be replaced by widening an allowlist.

### What must never be claimed

- that the release ROM is colored while color remains audit-only;
- that screenshots prove playability or temporal correctness;
- that synthetic conformance proves the real ROM renderer;
- that an allowlisted map has correct content without map-specific evidence;
- that retained future architecture is already active at runtime;
- that a green aggregate target includes Phase 2 verification or E2E when its
  Makefile dependencies do not.

That boundary is what keeps the roadmap honest. Preserve it until the relevant
phase has enough evidence to replace it.
