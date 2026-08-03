# Full-color renderer guide

## Current truth

The only playable color implementation is the audit product
`pokeyellow_phase2_audit.gbc`. It adds a passive CGB background-palette and
bank-1 tile-attribute layer to **Pallet Town and Route 1 only**.

Pokemon Yellow still owns gameplay, bank-0 tiles, graphics, sprites and OAM,
animations, cutscenes, menus, battles, fades, overlays, and scheduling. The
ordinary release, debug, and VC products remain unchanged. Retained ownership
and scheduler modules are future/test seams, not the active presentation path.

That boundary is the reason the slice is playable. Do not widen it casually.

## Read by task

- Start with [Runtime architecture](architecture.md) to understand ownership,
  data flow, map lifecycle, VBlank limits, and what is active versus retained.
- Read [Verification harness](verification-harness.md) before interpreting a
  green check or adding a test. It explains the four proof layers and what each
  one cannot prove.
- Use [Extending the slice](extending.md) when adding a compatible map,
  changing palette/attribute data, or adding a natural gameplay journey.
- Use [Development workflow](development-workflow.md) to resume after a context
  switch, triage failures, review the ROM manually, and hand work to the next
  session.
- Consult [Bugs and glitches](../bugs_and_glitches.md) for historical failure
  modes and their fixes.

## Build and play

Run commands from the repository root:

```console
make test-full-color-setup
make yellow_debug yellow_phase2_audit
```

Play `pokeyellow_phase2_audit.gbc` to review the colored slice. Use
`pokeyellow_debug.gbc`, built from the same revision, as the stock comparison.
Start from cold boot rather than an old save state when diagnosing rendering or
progression.

## Minimum useful checks

While iterating, run the focused test first, then the full-color unit suite:

```console
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q
```

Before calling a Phase 2 renderer or data change green, run at least:

```console
make yellow_debug yellow_phase2_audit
make verify-full-color-phase2-audit
.venv/bin/python -m pytest \
  tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
make test-full-color-gate0
make test-full-color-all
```

Then play the audit ROM through movement, boundaries, menus, an interior, a
battle, and return to the slice. Hosted CI does not currently run the cold-boot
journey, and `test-full-color-all` includes neither that journey nor
`verify-full-color-phase2-audit`. See the
[recommended verification ladder](verification-harness.md#recommended-fast-to-slow-ladder)
for the complete progression and evidence semantics.

## Common tasks

- **Understand what code actually runs:** read
  [active versus retained scaffolding](architecture.md#active-path-versus-retained-scaffolding)
  and the [key code map](architecture.md#key-code-map).
- **Add color to another map:** make the
  [bounded-slice or roadmap decision](extending.md#first-decide-bounded-slice-or-roadmap-work),
  then follow the [compatible-map checklist](extending.md#add-a-map-compatible-with-the-passive-slice).
  Adding Viridian to an allowlist is only a diagnostic canary; it is not correct
  Viridian coloring.
- **Change colors or tile assignments:** follow
  [Change palette or tile-attribute authority](extending.md#change-palette-or-tile-attribute-authority).
- **Add playable content coverage:** follow
  [Add natural gameplay coverage](extending.md#add-natural-gameplay-coverage).
- **Investigate corruption, flicker, or a white screen:** use
  [Failure triage](development-workflow.md#failure-triage) and compare the same
  scene against `pokeyellow_debug.gbc`.
- **Resume tomorrow:** follow [Start of a session](development-workflow.md#start-of-a-session),
  then read the [direction and decision ledger](development-workflow.md#direction-and-decision-ledger).
- **Prepare a handoff or PR update:** follow
  [Handoff and commit discipline](development-workflow.md#handoff-and-commit-discipline).

## Non-negotiable boundaries

1. Only the `_DEBUG` + `PHASE2_AUDIT` product may reach the passive renderer.
2. Pallet Town and Route 1 are the only currently claimed colored maps.
3. Yellow remains authoritative for tile bytes, sprites, gameplay presentation,
   effects, overlays, and timing; the passive layer writes only complete BG
   palettes and bank-1 BG attributes.
4. A map is not supported merely because its ID is allowlisted. Tileset,
   palettes, roofs, transitions, scrolling, fallback, and cleanup all require
   evidence.
5. Gate 0, Phase 1 runtime evidence, Phase 2 provenance/product checks, the
   synthetic checker, natural gameplay E2E, and manual playtesting prove
   different things. None replaces another, and none may be weakened to make a
   change pass.
6. Do not collapse future work into “Phase 3.” Phase 3 covers palette/effect
   and paired-transfer architecture; Phase 4 OAM; Phase 5 stress; Phase 6 all
   25 tilesets, roofs, overrides, and content; Phase 7 handoffs; Phase 8 old
   overworld-ownership deletion; and Phase 9 release hardening. Follow the
   [migration plan](../../specs/full-colors/docs/migration-plan.md).

Viridian shows why the split matters: Phase 3 can provide map-aware palette and
transfer selection, but correct Viridian roof/content acceptance belongs to
Phase 6. An allowlist edit completes neither.

The complete architectural list is in
[Runtime invariants](architecture.md#runtime-invariants), and the verification
list is in [Gates that must not be weakened](verification-harness.md#gates-that-must-not-be-weakened).

## Authoritative entry points

Runtime and data:

- [`engine/full_color/passive_overworld.asm`](../../engine/full_color/passive_overworld.asm):
  active map gate, translation, redraw, palette publication, and cleanup.
- [`data/tilesets/full_color_overworld.asm`](../../data/tilesets/full_color_overworld.asm):
  the live eight-palette payload and complete 256-entry attribute authority.
- [`home/overworld.asm`](../../home/overworld.asm) and
  [`home/vblank.asm`](../../home/vblank.asm): Yellow lifecycle integration and
  bounded VBlank hook.
- [`Makefile`](../../Makefile) and [`main.asm`](../../main.asm): product flags,
  checks, and audit-only module inclusion.

Contracts and evidence:

- [`specs/full-colors`](../../specs/full-colors/): reviewed definitions,
  inventories, verification rationale, and retained evidence.
- [`tools/rom_tests/full_color`](../../tools/rom_tests/full_color/): gate runners,
  source/ROM discovery, measurements, and evidence readers.
- [`tools/rom_tests/tests/unit/full_color`](../../tools/rom_tests/tests/unit/full_color/):
  contract, model, linked-ROM, and callable-ROM tests.
- [`tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py`](../../tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py):
  paired stock/audit journeys reached from natural gameplay.
- [`test-results`](../../test-results/): attempt-scoped local diagnostics; check
  each attempt's status and manifest rather than trusting a leftover image.
