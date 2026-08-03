# ROMhack documentation index

This is the contributor entry point for the Pokémon Yellow ROMhack. Start here
when onboarding, resuming work after a context switch, or deciding which
contract owns a change. The manuals describe both the ROM as it exists today
and the direction future systems should follow; they are not limited to the
current color work.

`FULL_COLOR_RENDERER.md` documents the current concrete initiative. The
architecture, testing, content, and workflow manuals apply across the whole
ROMhack, including future features unrelated to color.

## Current product truth

- `pokeyellow.gbc` is the ordinary ROM. `pokeyellow_debug.gbc` is its debug
  product, and the VC target remains a separate compatibility product.
- The only playable new color runtime is the experimental
  `pokeyellow_phase2_audit.gbc` product built with `_DEBUG` and
  `PHASE2_AUDIT`.
- That audit ROM passively colors Pallet Town and Route 1 backgrounds. Yellow
  still owns gameplay, bank-0 tile graphics, sprites, animations, overlays,
  menus, battles, cutscenes, fades, and scheduling.
- Normal release, debug, and VC products do not expose the passive renderer.
  Retained full-color scheduler and ownership modules are migration seams and
  test surfaces, not proof that they drive the visible game.
- The broader architectural direction is ownership-first: one authority per
  mutable resource, explicit identities, bounded interrupt work, fail-closed
  lifecycle transitions, authored content separated from mechanism, and proof
  from the built ROM plus natural gameplay.

Do not turn a roadmap statement into a claim about current runtime behavior.
The code path, product guard, linked ROM, test evidence, and natural playthrough
must agree.

## Manuals

- [ARCHITECTURE.md](ARCHITECTURE.md) — ROM-wide build/link layout, directory
  responsibilities, banking and memory contracts, positional IDs, product
  variants, runtime ownership boundaries, and principles for future systems.
  Read it before changing shared engine code, VBlank, ROM/RAM layout, map IDs,
  product flags, or another subsystem's owner.
- [TESTING.md](TESTING.md) — ROM-wide test layout, local and hosted coverage,
  natural gameplay tests, evidence semantics, fast-to-slow verification, and
  gates that must not be weakened. Read it before writing tests or interpreting
  a green result.
- [ADDING_CONTENT.md](ADDING_CONTENT.md) — practical recipes for maps, scripts,
  text, encounters, graphics, E2E journeys, and full-color data or slice
  extensions. Read it before adding player-visible content or changing an
  ID-indexed table.
- [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) — next-day startup,
  build/playtest loop, failure triage, artifact discipline, handoff, commits,
  pull requests, and CI. Read it when starting or parking a work session.
- [FULL_COLOR_RENDERER.md](FULL_COLOR_RENDERER.md) — the active Phase 2 passive
  renderer, its exact ownership and data flow, lifecycle, VBlank budget,
  invariants, code map, and Phases 3–9. Read it for the current concrete
  initiative; do not treat its experimental machinery as a general ROMhack
  dependency.
- [BUGS_AND_GLITCHES.md](BUGS_AND_GLITCHES.md) — historical defects inherited
  from Pokémon Yellow and their known status. Use it as a ledger, not as the
  active issue tracker or the renderer failure log.

## Authority hierarchy

When two descriptions appear to disagree, resolve them in this order:

1. `AGENTS.md` and the current approved task or pull-request plan define how
   work must be performed and what the change is allowed to claim.
2. Approved material under `specs/` defines initiative contracts, inventories,
   provenance, phase boundaries, and exit gates. For color work, begin with the
   [full-color migration plan](../specs/full-colors/docs/migration-plan.md).
3. Assembly source, data, build flags, and generated `.map`/`.sym` products
   define what is linked and reachable.
4. Built-ROM probes, retained evidence, natural input-driven E2E, and manual
   playtesting establish what the machine actually does.
5. These manuals explain those authorities and the intended contributor
   workflow. Update them when the underlying contract changes.
6. Chat history, screenshots without provenance, and leftover `test-results/`
   artifacts are context only. They are never authority by themselves.

Generated evidence must come from its official producer. A spec is not proof
that proposed code is active, a successful build is not proof of playability,
and a plausible screenshot is not proof of correct ownership or timing.

## Quick start

Run commands from the repository root:

```console
cat AGENTS.md
git status --short --branch
git log -5 --oneline --decorate
make test-full-color-setup
make -j"$(nproc)" yellow yellow_debug yellow_vc yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/unit -q
```

The setup target has a historical full-color name, but it prepares the shared
ROM test harness. Choose further checks by blast radius using the
[verification ladder](TESTING.md#fast-to-slow-development-loop). For the
current playable color slice, build paired products and compare them from cold
boot:

```console
make yellow_debug yellow_phase2_audit
.venv/bin/python -m pytest \
  tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
```

Play `pokeyellow_phase2_audit.gbc` for the colored slice and
`pokeyellow_debug.gbc` from the same revision as its Yellow reference. Hosted
CI does not currently run the natural gameplay E2E suite; see
[TESTING.md](TESTING.md) before reporting a feature green.

## Common tasks

- **Understand the ROM or design a shared subsystem:** read
  [ROM architecture](ARCHITECTURE.md), especially
  [runtime integration boundaries](ARCHITECTURE.md#runtime-integration-boundaries)
  and [future direction](ARCHITECTURE.md#intended-architecture-for-future-work).
- **Add a map, event, text, encounter, or graphics:** follow
  [Adding content](ADDING_CONTENT.md#a-map-is-a-multi-file-feature) and preserve
  the [map-ID ABI](ADDING_CONTENT.md#the-map-id-is-a-positional-abi).
- **Add gameplay coverage:** use
  [the E2E recipe](ADDING_CONTENT.md#add-gameplay-and-e2e-coverage) and
  [the gameplay-test contract](TESTING.md#writing-a-gameplay-test).
- **Work on the current color renderer:** read its
  [active path](FULL_COLOR_RENDERER.md#active-path-and-retained-scaffolding),
  [load-bearing invariants](FULL_COLOR_RENDERER.md#load-bearing-invariants),
  and [evidence boundary](FULL_COLOR_RENDERER.md#evidence-boundary).
- **Add color to another map or change palette data:** use the
  [full-color extension recipes](ADDING_CONTENT.md#full-color-extension-recipes).
  An allowlist entry alone is not correctly authored map color.
- **Investigate a white screen, corrupt geometry, flicker, or stale evidence:**
  start with [failure triage](DEVELOPMENT_WORKFLOW.md#failure-triage), then use
  the [full-color-specific triage](DEVELOPMENT_WORKFLOW.md#full-color-specific-triage)
  only when the audit path is implicated.
- **Resume tomorrow or hand work over:** follow
  [start every session from facts](DEVELOPMENT_WORKFLOW.md#start-every-session-from-facts)
  and write the
  [next-day handoff note](DEVELOPMENT_WORKFLOW.md#a-useful-next-day-handoff-note).
- **Decide what a green check proves:** use
  [the full-color evidence stack](TESTING.md#full-color-evidence-stack) and
  [hosted CI coverage](TESTING.md#what-hosted-ci-covers).

Keep this index stable as the entry point. Add a focused SCREAMING_CASE manual
when a new subsystem genuinely needs one; link it here and state whether its
contract is ROM-wide, initiative-specific, current, or intended.
