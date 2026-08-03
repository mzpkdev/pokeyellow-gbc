# Technical debt register

## Purpose and rules

This register explains intentional compromises that a cold operator could
otherwise mistake for finished architecture, dead code, or permission to widen
the renderer. It covers the current full-color initiative and the ROMhack-wide
contracts exposed by that work.

Three categories must stay distinct:

- **Intentional constraint:** a boundary that protects current correctness. It
  is not debt until an approved change needs behavior outside the boundary.
- **Technical debt:** a retained compromise whose trigger has been reached or
  whose risk must be paid down before a named capability can ship.
- **Planned work:** an accepted future capability with its own phase and gate.
  Planned work is not evidence that the implementation exists today.

An entry records a decision; it does not authorize its own scope. Work still
needs an approved plan or task, fresh source and ROM evidence, review, and the
gates required by [AGENTS.md](AGENTS.md) and the
[development workflow](docs/DEVELOPMENT_WORKFLOW.md). Update an entry's status,
links, and proof when the underlying code changes. Do not close an entry from a
source diff, build, screenshot, or synthetic test alone when its acceptance
proof requires linked-ROM or natural-gameplay evidence.

Current product truth: the only playable color path is the `PHASE2_AUDIT`
product, and it colors only Pallet Town and Route 1. A production
`COLOR/YELLOW` option has been approved and planned, but it is not implemented
on merged `main`. The optional local operator plan is
`.preemdeck/plan/introduce-production-color-mode-toggle.md`; this tracked
register does not depend on that untracked file. The authoritative tracked
direction remains the [migration plan](specs/full-colors/docs/migration-plan.md).

## Status and priority

Statuses:

- **CONSTRAINT:** safe boundary; revisit only when its trigger is reached.
- **TRIGGERED:** an approved change now depends on resolving the entry.
- **PLANNED:** assigned to a future migration phase, not yet active.
- **ACTIVE:** debt exists in a live product and should be reduced now.
- **BLOCKED:** trigger is reached, but a named dependency is not complete.
- **CLOSED:** retirement or activation proof is linked in the entry.

Priorities:

- **P0:** blocks safe production promotion or can corrupt visible/game state.
- **P1:** blocks a promised capability or can create false release confidence.
- **P2:** raises maintenance cost but does not presently threaten correctness.

## Index

| ID | Status | Priority | Subject |
| --- | --- | --- | --- |
| [FC-001](#fc-001-audit-only-passive-runtime) | TRIGGERED | P0 | Audit-only passive runtime |
| [FC-002](#fc-002-hard-coded-map-gate) | PLANNED | P1 | Hard-coded map gate |
| [FC-003](#fc-003-yellow-owned-scene-fallbacks) | PLANNED | P1 | Yellow-owned scene fallbacks |
| [FC-004](#fc-004-palette-ownership-flashes) | TRIGGERED | P0 | Palette ownership flashes |
| [FC-005](#fc-005-mode-handoff-is-not-a-product-contract) | TRIGGERED | P0 | Atomic mode handoff |
| [FC-006](#fc-006-passive-state-aliases-dormant-scheduler-storage) | CONSTRAINT | P1 | WRAM alias with dormant scheduler |
| [FC-007](#fc-007-dormant-renderer-architecture) | PLANNED | P1 | Dormant scheduler and lifecycle |
| [FC-008](#fc-008-phase-2-audit-mailboxes-and-observability-carriers) | TRIGGERED | P0 | Phase 2 audit mailboxes and carriers |
| [FC-009](#fc-009-product-link-and-reachability-partition) | TRIGGERED | P0 | Product link partition |
| [FC-010](#fc-010-object-color-path-is-only-scaffolding) | PLANNED | P1 | OAM color scaffolding |
| [FC-011](#fc-011-evidence-contract-assumes-audit-only-color) | TRIGGERED | P0 | Stale product/evidence assumption |
| [FC-012](#fc-012-generated-inventory-transition-cost) | ACTIVE | P1 | Generated inventory transitions |
| [FC-013](#fc-013-natural-gameplay-is-not-hosted) | ACTIVE | P1 | Natural gameplay not hosted |
| [FC-014](#fc-014-donor-content-is-incomplete-for-yellow) | BLOCKED | P1 | Incomplete Yellow color content |
| [WF-001](#wf-001-branch-and-release-evidence-hygiene) | TRIGGERED | P1 | Branch and release evidence hygiene |

## Production quarantine

The rule is to remove unproved machinery from **production reachability**, not
from the repository. Delete retained code only after its replacement or
obsolescence is proved.

| Surface | Production disposition | Audit/repository disposition | Activation or removal trigger |
| --- | --- | --- | --- |
| Passive palettes, tile attributes, redraw preparation, bounded VBlank commit, cleanup | Candidate for deliberate production promotion | Keep audit path independently buildable | Production toggle has closed linkage, atomicity, fallback, timing, save, and natural-play gates |
| Phase 2 provenance, audit-only SRAM/WRAM mailboxes and trace carriers, callable audit roots | Unreachable and absent from release/debug/VC symbol maps | Keep under `PHASE2_AUDIT` for diagnostics and proof; preserve the separate Phase 1 `_DEBUG` SRAM protocol | Remove only when no accepted Phase 2 audit claim consumes them; never activate in production |
| Ownership scheduler, lifecycle planes, palette scheduler, paired transfers, OAM mapper | Unreachable in production until its owning migration phase | Keep buildable and tested as dormant seams | Activate one bounded subsystem only after its phase inventory and exit gate close; remove if the chosen production design supersedes it |

A blanket guard removal is forbidden. It could ship Phase 2 audit command
channels, dormant jobs, or provenance markers while making the evidence report
a product that no longer exists. This quarantine does not remove or weaken the
Phase 1 `_DEBUG` mailbox, Gate 0, or Phase 1 runtime evidence.

## Debt entries

### FC-001: Audit-only passive runtime

- **Status / priority:** TRIGGERED / P0.
- **What exists:** `pokeyellow_phase2_audit.gbc` links the passive Pallet
  Town/Route 1 renderer behind `_DEBUG` plus `PHASE2_AUDIT`; ordinary release,
  debug, and VC products do not expose it.
- **Why retained:** isolation let the slice prove geometry, timing, fallback,
  and gameplay without changing stock product identities.
- **Current risk:** promoting color with the audit flag would also promote
  unproved diagnostics and dormant architecture.
- **Dependencies:** [FC-004](#fc-004-palette-ownership-flashes),
  [FC-005](#fc-005-mode-handoff-is-not-a-product-contract),
  [FC-008](#fc-008-phase-2-audit-mailboxes-and-observability-carriers),
  [FC-009](#fc-009-product-link-and-reachability-partition), and
  [FC-011](#fc-011-evidence-contract-assumes-audit-only-color).
- **Right-time trigger:** reached when the production `COLOR/YELLOW` option was
  approved.
- **Recommendation:** extract only the minimal passive substrate into ordinary
  products behind a separate staged production predicate. Never define
  `PHASE2_AUDIT` for production.
- **Acceptance proof:** all four products link; production can select Color or
  Yellow at an LCD-off reconstruction boundary; audit-only symbols are absent
  from production `.sym` files; audit verification remains green; natural
  play proves both modes and unsupported-map fallback.
- **Sources:** [Makefile](Makefile), [main.asm](main.asm),
  [passive_overworld.asm](engine/full_color/passive_overworld.asm), and the
  [renderer product matrix](docs/FULL_COLOR_RENDERER.md#current-scope).

### FC-002: Hard-coded map gate

- **Status / priority:** PLANNED / P1.
- **What exists:** two duplicated runtime checks admit only `PALLET_TOWN` and
  `ROUTE_1`; both maps share one `OVERWORLD` tile table and one Pallet roof
  palette payload.
- **Why retained:** the narrow gate prevents a legal-looking attribute table
  from falsely coloring maps whose roofs, overrides, or tilesets differ.
- **Current risk:** duplicated predicates can drift, and widening either one
  can produce wrong color or asymmetric VBlank behavior.
- **Dependencies:** Phase 3 map/tileset-aware palette dispatch and Phase 6
  accepted Yellow content.
- **Right-time trigger:** a proposed map cannot truthfully use the exact current
  256-entry lookup and all eight current palettes.
- **Recommendation:** replace both checks with one effective-mode/map authority
  keyed by explicit map, tileset, roof, and override identities.
- **Acceptance proof:** source and built-ROM inventory show one authority;
  supported and unsupported maps agree at load and VBlank; each admitted map
  has reviewed content and natural transition coverage.
- **Sources:** [passive_overworld.asm](engine/full_color/passive_overworld.asm),
  [full_color_overworld.asm](data/tilesets/full_color_overworld.asm), and the
  [extension recipe](docs/ADDING_CONTENT.md#full-color-extension-recipes).

### FC-003: Yellow-owned scene fallbacks

- **Status / priority:** PLANNED / P1.
- **What exists:** interiors, menus, dialogue, battles, cutscenes, sprites,
  effects, and animations remain Yellow-owned; the passive layer restores a
  colored overworld after some overlays.
- **Why retained:** Yellow remains the only proved owner for those scenes, and
  coloring them by inferring from background tile IDs previously corrupted
  geometry and progression.
- **Current risk:** fallback edges can expose stale attributes or one-frame
  palette changes; future contributors may mistake stock-looking scenes for a
  completed full-color product.
- **Dependencies:** Phase 3 effects/transfers, Phase 4 OAM, Phase 7 handoffs,
  and Phase 8 ownership deletion.
- **Right-time trigger:** reached separately for each scene class when product
  scope promises color there or a transition cannot be made visually atomic.
- **Recommendation:** inventory concrete handoff edges and migrate one resource
  owner at a time; do not add scene-shaped exceptions to the passive map layer.
- **Acceptance proof:** each migrated scene has an exclusive writer, explicit
  entry/exit reconstruction, frame-strip review, built-ROM probes, and natural
  gameplay in both player modes.
- **Sources:** [renderer scene boundaries](docs/FULL_COLOR_RENDERER.md#menus-interiors-dialogue-and-battles),
  [migration phases](specs/full-colors/docs/migration-plan.md), and
  [acceptance criteria](specs/full-colors/docs/acceptance-criteria.md).

### FC-004: Palette ownership flashes

- **Status / priority:** TRIGGERED / P0.
- **What exists:** Yellow's `LoadGBPal`, fades, menus, dialogue, and battle
  transitions may replace global CGB BG palettes; the passive layer detects
  replacement and queues republication in a later VBlank.
- **Why retained:** deferred publication respects visible-time and VBlank
  budgets better than an immediate palette write.
- **Current risk:** Yellow and passive writers can expose old, gray, or donor
  palettes on adjacent visible frames during dialogue, menus, and battle entry.
- **Dependencies:** a formal preference/effective/presented-mode state machine
  and [FC-005](#fc-005-mode-handoff-is-not-a-product-contract).
- **Right-time trigger:** reached because a production mode toggle must promise
  stable presentation, and manual play already observes palette flashes.
- **Recommendation:** suspend passive republication while Yellow owns an
  overlay, fade, or battle transition; reconcile once at the next hidden
  reconstruction boundary.
- **Acceptance proof:** frame strips and natural input tests show no mixed-owner
  frame across Start, Options, dialogue, party, battle, return, save, reset, and
  Continue; timing evidence still permits only bounded VBlank work.
- **Sources:** [passive_palette_refresh.asm](engine/full_color/passive_palette_refresh.asm),
  [palette publication contract](docs/FULL_COLOR_RENDERER.md#scrolling-and-vblank),
  and [testing limitations](docs/TESTING.md#false-confidence-traps).

### FC-005: Mode handoff is not a product contract

- **Status / priority:** TRIGGERED / P0.
- **What exists:** the audit path activates on map load and restores attributes
  after selected overlays, but there is no saved player preference or general
  Color-to-Yellow/Yellow-to-Color reconstruction contract.
- **Why retained:** Phase 2 needed one safe canary, not a second product mode.
- **Current risk:** flipping a live flag would mix palette RAM, bank-1
  attributes, pending work, and generations from two owners.
- **Dependencies:** a save-compatible preference bit, effective-mode resolver,
  pending reconciliation state, and FC-001/FC-004 closure.
- **Right-time trigger:** reached when the player-facing production toggle was
  approved.
- **Recommendation:** Options changes preference only. After the overlay
  closes, cancel stale work, advance generation once for a real effective-mode
  change, and publish the complete 32x32 attributes plus palettes while LCD is
  off. Unsupported maps resolve to Yellow without erasing Color preference.
- **Acceptance proof:** repeated/no-op changes, supported/unsupported maps,
  maps in both directions, save/reset/Continue, and every overlay edge prove
  exactly one hidden reconstruction and no stale write.
- **Sources:** [passive lifecycle](docs/FULL_COLOR_RENDERER.md#map-load-and-publication),
  [save declarations](ram/wram.asm), [Options engine](engine/menus/options.asm),
  and [handoff requirements](specs/full-colors/docs/requirements.md).

### FC-006: Passive state aliases dormant scheduler storage

- **Status / priority:** CONSTRAINT / P1.
- **What exists:** two passive state bytes alias dormant scheduler timing
  scratch in WRAM2 because their lifetimes cannot overlap in the audit path.
- **Why retained:** the alias preserved the measured WRAM layout without
  growing an experimental reservation.
- **Current risk:** production promotion or scheduler activation could make the
  lifetimes overlap and silently corrupt pending palette/cleanup state.
- **Dependencies:** final production passive-state allocation and the Phase 3
  scheduler decision.
- **Right-time trigger:** any build can reach both passive state and scheduler
  timing state, or either lifetime expands beyond its proved boundary.
- **Recommendation:** allocate standalone passive production state before
  promotion; keep any audit alias only where a test proves mutual exclusion.
- **Acceptance proof:** linker symbols and hostile overlap tests prove unique,
  bounded storage in every product that can reach both owners.
- **Sources:** [WRAM declarations](ram/wram.asm),
  [scheduler.asm](engine/full_color/scheduler.asm), and
  [bank and memory ownership](docs/ARCHITECTURE.md#banks-and-memory-ownership).

### FC-007: Dormant renderer architecture

- **Status / priority:** PLANNED / P1.
- **What exists:** ownership, scheduler, lifecycle, palette, transfer, and OAM
  modules preserve measured contracts and synthetic/callable test seams, but
  they do not drive the playable slice.
- **Why retained:** later phases need explicit ownership, generation,
  reconstruction, transfer, and identity concepts; deleting them now discards
  reviewed experiments.
- **Current risk:** compiled or callable code can be mistaken for an active
  renderer, and its design may diverge from the minimal passive production
  path before activation.
- **Dependencies:** each module's owning migration phase and a fresh inventory
  of actual Yellow writers.
- **Right-time trigger:** activate a module only when a bounded production
  capability needs it and its phase prerequisites, inventory, and gates close;
  retire it when the selected production design proves it redundant.
- **Recommendation:** keep it quarantined, buildable, and testable. Activate or
  delete one subsystem per reviewed change, never the directory as a unit.
- **Acceptance proof:** activation requires natural reachability and exclusive
  writer evidence; retirement requires symbol/source absence plus preserved
  acceptance coverage for the behavior it modeled.
- **Sources:** [active path and scaffolding](docs/FULL_COLOR_RENDERER.md#active-path-and-retained-scaffolding),
  [engine/full_color](engine/full_color), and the
  [migration plan](specs/full-colors/docs/migration-plan.md).

### FC-008: Phase 2 audit mailboxes and observability carriers

- **Status / priority:** TRIGGERED / P0.
- **What exists:** the Phase 2 audit product adds its own SRAM/WRAM mailboxes,
  trace records, audit commands, provenance, and callable roots used by ROM
  probes. Separately, the ordinary `_DEBUG` product retains the legitimate
  Phase 1 SRAM mailbox and trace protocol used by Gate 0 and Phase 1 runtime
  evidence.
- **Why retained:** they make bank, ownership, rejection, and provenance claims
  observable without inferring them from screenshots.
- **Current risk:** a blanket `PHASE2_AUDIT` guard removal can expose the Phase 2
  command surface in production, collide with production interrupt scratch,
  change save/WRAM layout, or let tests manipulate a path unavailable to
  players.
- **Dependencies:** FC-009 product partition and dedicated production scratch
  allocation.
- **Right-time trigger:** reached because the passive runtime is approved for
  ordinary products while audit diagnostics are not.
- **Recommendation:** keep Phase 2 audit commands, provenance, callable roots,
  and carriers under `PHASE2_AUDIT`; give production passive interrupt state
  separately named, non-aliased storage; test those Phase 2 symbols absent in
  release/debug/VC. Preserve the Phase 1 `_DEBUG` mailbox and protocol until
  Gate 0 and Phase 1 evidence have an explicitly approved replacement.
- **Acceptance proof:** product `.sym`/`.map` scans and direct-ROM probes show
  zero Phase 2 audit roots, commands, provenance carriers, or aliases in all
  production variants while Phase 2 audit observability, Gate 0, and Phase 1
  runtime evidence still pass. The ordinary debug product still exposes its
  expected Phase 1 mailbox and trace protocol.
- **Sources:** [debug_runtime.asm](engine/full_color/debug_runtime.asm),
  [phase2_audit.asm](engine/full_color/phase2_audit.asm),
  [HRAM declarations](ram/hram.asm), and
  [audit observability](tools/rom_tests/full_color/phase2_audit_observability.py).

### FC-009: Product link and reachability partition

- **Status / priority:** TRIGGERED / P0.
- **What exists:** one outer `PHASE2_AUDIT` partition currently groups the live
  passive slice, diagnostic payloads, and dormant future modules.
- **Why retained:** a single experimental product boundary was correct while
  none of the grouped machinery belonged in production.
- **Current risk:** promoting the group ships too much; leaving it grouped
  prevents promoting the narrow passive substrate at all. Source inclusion and
  runtime reachability can also disagree across release, debug, VC, and audit.
- **Dependencies:** exact source/ROM inventory closure and FC-001/FC-008.
- **Right-time trigger:** reached by approved production promotion.
- **Recommendation:** create a narrow production section for passive code,
  data, state, and hooks, initially staged off. Preserve a separate audit-only
  section for diagnostics and dormant modules, then activate only after
  inventories close.
- **Acceptance proof:** a four-product matrix proves expected symbols,
  callability, no-op staged behavior, forbidden-symbol absence, bank/layout
  bounds, and unchanged audit identity semantics.
- **Sources:** [main.asm](main.asm), [layout.link](layout.link),
  [product variants](docs/ARCHITECTURE.md#product-variants-and-experimental-isolation),
  and [ROM discovery](tools/rom_tests/full_color/rom_discovery.py).

### FC-010: Object color path is only scaffolding

- **Status / priority:** PLANNED / P1.
- **What exists:** OBJ palette payloads, OAM mapping, fallback records, and
  scheduler requests exist in audit scaffolding; the passive slice does not
  publish object palettes or alter Yellow's OAM.
- **Why retained:** the code records the intended final-picture-identity rule
  and deterministic palette-0 fallback for Phase 4.
- **Current risk:** activating it before Yellow's final tile calculation can
  recolor the wrong sprite, break follower Pikachu offsets, or race DMA.
- **Dependencies:** Phase 4 writer inventory, complete picture-ID assignments,
  and shadow-to-hardware OAM timing proof.
- **Right-time trigger:** player scope promises colored overworld objects, or
  background-only color is no longer an accepted slice boundary.
- **Recommendation:** map palette bits from final authored picture identity
  after Yellow completes tile calculation; preserve bits 3-7; commit one
  complete shadow-OAM batch through the existing DMA contract.
- **Acceptance proof:** player, Pikachu, NPC, fallback, mutation, bank, timing,
  and complete-DMA tests plus natural movement/cutscene frame review close
  Phase 4.
- **Sources:** [oam.asm](engine/full_color/oam.asm),
  [Phase 4 plan](specs/full-colors/docs/migration-plan.md#phase-4-overworld-oam),
  and [AC-OW-05](specs/full-colors/docs/acceptance-criteria.md).

### FC-011: Evidence contract assumes audit-only color

- **Status / priority:** TRIGGERED / P0.
- **What exists:** Phase 2 verification proves that color belongs to an exact
  audit product and that ordinary products exclude its runtime; product hashes,
  compile-time provenance, and inventory rows encode that claim.
- **Why retained:** it prevents a source-only or stale-ROM claim from passing
  as the measured Phase 2 slice.
- **Current risk:** production promotion makes part of the old negative claim
  false. Weakening or deleting the verifier would also discard the independent
  audit claim and permit stale evidence.
- **Dependencies:** FC-009 partition and a versioned production-toggle evidence
  contract.
- **Right-time trigger:** reached when production Color was approved.
- **Recommendation:** preserve Phase 2 audit provenance, then add a new typed
  evidence version proving production Color reachability, Yellow fallback,
  audit-diagnostic exclusion, and exact product identities. Do not overwrite
  an old schema with new semantics.
- **Acceptance proof:** old audit evidence still validates its historical
  claim; new generated evidence rejects wrong ROMs, stale hashes, forbidden
  symbols, false mode reachability, and hand-edited payloads.
- **Sources:** [phase2_measurements.py](tools/rom_tests/full_color/phase2_measurements.py),
  [phase2_audit_observability.py](tools/rom_tests/full_color/phase2_audit_observability.py),
  [Phase 2 definition](specs/full-colors/definitions/phase2-hostile-slice-representation.json),
  and [evidence rules](docs/TESTING.md#full-color-evidence-stack).

### FC-012: Generated inventory transition cost

- **Status / priority:** ACTIVE / P1.
- **What exists:** reviewed source discovery, ROM discovery, assignments,
  rejections, inventories, and evidence bind exact hashes and semantic subjects.
- **Why retained:** the friction is deliberate: it makes a new hook, writer,
  root, or product identity visible instead of silently escaping the audit.
- **Current risk:** duplicated roots and hand-maintained transition metadata can
  become stale; operators may bypass the producer or edit JSON until it passes.
- **Dependencies:** official generators in `tools/rom_tests/full_color` and
  reviewed authority under `specs/full-colors`.
- **Right-time trigger:** any source, linked-ROM root, writer set, product
  identity, or accepted scene changes.
- **Recommendation:** keep closure before activation. Improve generators and
  error messages when the transition is hard, but never relax exact hashes,
  typed provenance, stale-row rejection, or mutation sensitivity.
- **Acceptance proof:** the official generator produces a reviewed semantic
  diff; stale, phantom, omitted, and hand-mutated rows fail; two independent
  Gate 0 runs remain byte-identical.
- **Sources:** [baseline_inventory.py](tools/rom_tests/full_color/baseline_inventory.py),
  [source_discovery.py](tools/rom_tests/full_color/source_discovery.py),
  [phase2_measurements.py](tools/rom_tests/full_color/phase2_measurements.py),
  and [Gate 0](docs/TESTING.md#gate-0-contract).

### FC-013: Natural gameplay is not hosted

- **Status / priority:** ACTIVE / P1.
- **What exists:** local cold-boot journeys use natural inputs across new game,
  Pallet/Route 1, Oak's capture, menus/dialogue, battles, fallback, and
  save/reset/Continue. Hosted CI runs unit and retained deterministic gates but
  not `tools/rom_tests/tests/e2e`.
- **Why retained:** PyBoy journeys are slower and less deterministic than
  source/model checks; manual visual review still catches flicker and aesthetic
  failures that one checkpoint cannot.
- **Current risk:** a green PR can ship a ROM that builds and satisfies
  synthetic/callable contracts but is visibly broken through natural play.
- **Dependencies:** CI runtime budget, stable ROM prerequisites, bounded journey
  timeouts, attempt-scoped artifacts, and flake data.
- **Right-time trigger:** any production player-visible renderer or mode change;
  the production toggle has reached this trigger even though CI migration may
  remain a separate task.
- **Recommendation:** require local E2E plus human frame review for the toggle;
  move a stable smoke subset to hosted CI when repeated local/hosted trials show
  bounded runtime and useful failures. Keep the longer suite local if needed.
- **Acceptance proof:** the hosted subset starts from cold boot, uses inputs
  rather than injected states, retains named failure screenshots/diagnostics,
  and demonstrates an acceptable flake/runtime record. Manual review remains a
  release fact, not an inferred CI result.
- **Sources:** [cold-boot journeys](tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py),
  [scenario helpers](tools/rom_tests/scenarios), and
  [hosted coverage](docs/TESTING.md#what-hosted-ci-covers).

### FC-014: Donor content is incomplete for Yellow

- **Status / priority:** BLOCKED / P1.
- **What exists:** one donor-derived `OVERWORLD` tile-to-attribute table and
  eight BG palettes color Pallet Town and Route 1. The donor offers useful Gen
  1 organization and artistic evidence, not a drop-in Yellow renderer.
- **Why retained:** the accepted data is a strong canary and avoids inventing
  colors already authored for a related engine.
- **Current risk:** treating donor mappings as authoritative can miscolor
  Yellow-exclusive graphics, roofs, maps, follower Pikachu, animations, and
  tilesets while all attribute bytes remain technically legal.
- **Dependencies:** Phase 3 map-aware palette/roof dispatch and Phase 6
  independent authoring/validation for all 25 Yellow tilesets and overrides.
- **Right-time trigger:** adding any map whose exact tileset, roof, override,
  or animation identity differs from the accepted slice.
- **Recommendation:** import donor material only as pinned candidate provenance;
  validate every retained value against Yellow graphics and behavior. Keep
  mechanisms separate from authored data.
- **Acceptance proof:** every Yellow tileset, roof, override, animation, and
  special case has inventory closure, atlas/table review, semantic full-byte
  attribute tests, and natural visual acceptance.
- **Sources:** [full_color_overworld.asm](data/tilesets/full_color_overworld.asm),
  [Phase 6 plan](specs/full-colors/docs/migration-plan.md#phase-6-tileset-content),
  [R8.2](specs/full-colors/docs/requirements.md), and
  [Viridian warning](docs/ADDING_CONTENT.md#viridian-is-a-canary-not-completed-content).

### WF-001: Branch and release evidence hygiene

- **Status / priority:** TRIGGERED / P1.
- **What exists:** merged work can leave local `main`, product hashes,
  retained artifacts, and operator plans behind the remote truth. The workflow
  requires exact-path staging, reviewed commits, feature branches, early draft
  PRs, and hosted checks, but those are human discipline rather than a single
  machine-enforced transaction.
- **Why retained:** operator state and generated evidence cannot safely be
  swept into every commit; direct local iteration needs flexibility.
- **Current risk:** branching from stale local `main`, pushing unrelated
  `.preemdeck/` or `test-results/`, hand-editing evidence, or updating product
  hashes before final verified ROMs can make review and reproduction false.
- **Dependencies:** repository instructions, protected remote branch policy,
  official evidence producers, and product identity gates.
- **Right-time trigger:** reached for the production toggle because it changes
  release/debug/VC identities and must begin from merged `origin/main`.
- **Recommendation:** fetch `origin main`, branch from `origin/main`, open
  a draft PR after the first reviewed green commit, stage exact owned paths,
  regenerate evidence only through its producer, and update release hashes only
  from final verified products. Never commit `.preemdeck/` plans.
- **Acceptance proof:** PR history shows the correct base and scoped commits;
  worktree inspection shows no unrelated files; product `.gbc`/`.map`/`.sym`
  identities agree with evidence; required local checks, manual play, and
  hosted CI are recorded before merge.
- **Sources:** [AGENTS.md](AGENTS.md),
  [development workflow](docs/DEVELOPMENT_WORKFLOW.md#handoff-commit-and-pull-request-discipline),
  [Makefile](Makefile), and [roms.sha1](roms.sha1).

## Intentional constraints and non-goals

These are not shortcuts to remove. A constraint becomes debt only when its
trigger is reached and the replacement has a proved boundary.

### IC-001: Color is audit-only

**Status:** becoming debt now. Audit isolation remains the current truth, but
approval of a production toggle has reached its replacement trigger. Resolve
through FC-001, FC-008, FC-009, and FC-011 rather than deleting the outer guard.

### IC-002: Pallet Town and Route 1 only

The slice stays limited until map-aware palette/roof dispatch and independently
accepted Yellow content exist. A broader allowlist is not broader support.

### IC-003: Yellow owns bank-0 tiles and gameplay

Passive color may translate only completed Yellow background tiles into BG
palettes and bank-1 attributes. It must not change scripts, mechanics, tile
geometry, movement, or cutscene progression.

### IC-004: Yellow owns excluded scenes

Menus, dialogue, battles, interiors, effects, sprites, and cutscenes stay Yellow
until their concrete migration phases close. A player mode toggle does not
color those scenes by itself.

### IC-005: One bounded passive VBlank operation

Yellow row/column redraw wins; palette publication defers; cleanup is chunked.
Performance pressure must improve preparation or measured budgets, not combine
unbounded work in one interrupt.

### IC-006: Complete authored attributes and palettes

Every tile uses the reviewed 256-byte table, and palette publication writes a
complete set. Arithmetic fallbacks such as `tile_id & 7`, partial palettes, or
sampling VRAM as an oracle are non-goals.

### IC-007: Phase 2 audit diagnostics stay out of production

Phase 2 audit mailboxes, provenance carriers, synthetic roots, and dormant
subsystems remain audit-only even when the minimal passive runtime ships. The
separate Phase 1 `_DEBUG` mailbox and trace protocol remain available to Gate 0
and Phase 1 runtime evidence until deliberately replaced with equivalent proof.

### IC-008: Synthetic and callable evidence stays narrow

The conformance checker proves its modeled contract; callable ROM tests prove
controlled entry points. Neither may claim natural reachability, playability,
visual stability, or artistic quality.

### IC-009: Donor content is candidate evidence

Pokemon Celebrations can supply pinned organization and artistic candidates.
Yellow-specific values still require independent authoring and validation; no
donor import can waive Yellow's inventories or acceptance gates.

## ROMhack-wide recommendations

- Treat map, tileset, species, move, item, sprite, WRAM, HRAM, and SRAM order as
  positional ABI. Update parallel tables and assertions together, then prove
  the linked addresses and sizes.
- Treat ROM banks and `layout.link` placement as evidence-bearing contracts.
  Verify `.map` and `.sym` output, far-call boundaries, and restored ROM/WRAM/
  VRAM bank state for every new shared hook.
- Reserve “natural gameplay” for cold-boot input-driven scenarios. State
  injection, direct routine calls, screenshots, and save states are different
  evidence classes and must be named honestly.
- Never hand-edit generated evidence. Run the official producer, preserve
  schema versions and provenance, review the semantic diff, and keep failed
  attempts separate from accepted artifacts.
- Branch from fetched `origin/main`, keep operator state untracked, stage
  exact paths, use a draft PR for visible review, and bind release claims to the
  pushed revision whose hosted checks completed.

## Maintenance workflow

Create a new debt entry only when all of these are known:

1. a concrete retained compromise or live risk exists in source, products, or
   evidence;
2. keeping it has a defensible reason;
3. a specific event defines when it must change; and
4. executable or inspectable proof can define closure.

Use the next stable ID in the owning family. Link source and tracked authority,
name dependencies, and separate player impact from maintenance discomfort. Do
not add vague wishes, duplicate the migration roadmap, or use this file to
authorize a feature.

To close an entry:

1. land the replacement, activation, or deletion through a reviewed PR;
2. run the entry's acceptance proof and the gates required by its blast radius;
3. link the PR, committed evidence, or stable test authority in the entry;
4. set status to CLOSED and record what remains intentionally constrained; and
5. update or remove dependent entries whose triggers or recommendations changed.

Evidence JSON and retained generated reports must be regenerated by their
official tools, never edited by hand. Local `.preemdeck` plans can help the
operator resume work, but they remain optional context: tracked docs, specs,
source, linked products, and verified evidence must stand without them.
