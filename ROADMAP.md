# Roadmap: Pokémon Yellow, Fully Colorized or Original

## North star

Deliver a complete Pokémon Yellow disassembly with one persistent player setting: **COLOR** presents a deliberately authored full-color treatment in every visible scene class, while **YELLOW** presents the original Yellow palette treatment. Gameplay logic, progression, timing-sensitive behavior, and save semantics must remain identical in both modes except for the saved presentation preference itself.

“Full-color” means the whole visible game, not an overworld-only demonstration. Until a scene has authored Color content and passes its gate, a Color preference must fail safely to the Yellow presentation without being erased.

The current tracked baseline and constraints are described by the [documentation index](docs/INDEX.md), [renderer architecture](docs/FULL_COLOR_RENDERER.md), [full-color specification](specs/full-colors/SPEC.md), and [technical debt register](TECH_DEBT.md). Update those authorities with each milestone; this roadmap recommends sequence but does not overrule their gates.

## Non-negotiable engineering policy

- Treat a pinned `pokered-gbc` revision as mechanism reference and candidate palette/data organization only. It is never drop-in Yellow authority: every palette, mapping, roof, override, lifecycle, bank placement, and timing decision must be reviewed against Yellow and recorded in the [replacement inventory](specs/full-colors/docs/replacement-inventory.md).
- Preserve the Gate 0 two-run comparator, Phase 1 real-ROM runtime evidence, the mutation-sensitive synthetic checker, Phase 2 audit and provenance, natural cold-boot journeys, manual frame review, and hosted CI. Their distinct claims and limitations remain defined in [testing](docs/TESTING.md) and the [verification plan](specs/full-colors/docs/verification-plan.md).
- Close the exact writer, scene, boundary, and mutation rows touched by a milestone before making its behavior reachable. No later milestone receives credit from an earlier phase, and no red gate may be bypassed as “follow-up” work.
- Keep gameplay and presentation ownership separate. A visual-mode change must not branch game rules, RNG, progression, scripting, or save data beyond the preference representation.

## Milestone 1 — Production COLOR/YELLOW toggle and Pallet/Route 1 canary

- **Outcome:** Ordinary production ROMs expose a persistent `COLOR MODE: COLOR/YELLOW` option. Pallet Town and Route 1 are the deliberately bounded Color canary; unsupported scenes present Yellow while retaining a saved Color preference.
- **Scope:** First rebaseline all donor provenance to a pinned `pokered-gbc` revision and update the tracked evidence contract. Separate saved **preference**, resolved **effective mode**, and atomically published **presented mode**. Options changes preference only; after the overlay closes, an LCD-off reconstruction cancels stale work, advances generation only for a real effective-mode change, and publishes one complete backend. Keep Phase 2 diagnostics isolated from production and open a draft PR after the first reviewed green preflight checkpoint.
- **Exit gate:** Both directions switch without a mixed-owner frame; no-op changes do no work; save/reset/Continue preserves preference; unsupported maps resolve to Yellow and later resume Color on a supported map; normal, debug, VC, and audit products have the intended symbol/reachability partition. Gate 0, Phase 1 runtime evidence, synthetic checker mutation tests, Phase 2 audit/provenance, cold-boot journeys, manual frame strips, and hosted CI are green.
- **Debt/constraint consequence:** The permanent toggle directly conflicts with current replacement-only wording, especially `AC-REMOVE-01` in the [acceptance criteria](specs/full-colors/docs/acceptance-criteria.md) and the dual-renderer prohibition in [scope](specs/full-colors/docs/scope.md). M1 cannot be ready until tracked requirements and acceptance criteria are reconciled to retain an explicit Yellow presentation backend while still eliminating uncontrolled competing writers. Do not claim that this toggle exists on the current baseline.

## Milestone 2 — Map-aware renderer and paired-transfer foundation

- **Outcome:** One effective-mode/map authority selects reviewed palettes, tileset attributes, roofs, and overrides; every visible map mutation transfers tiles and full-byte attributes as one declared unit.
- **Scope:** Build on the centralized admitted-map predicate, tileset palette/attribute dispatch, and map-aware roof table with explicit override and destination identities. Cover initial load, reload, scrolling, all connections, overlays, animation, field replacement, alternate BG/window destinations, clipping, VBlank routing, and reconstruction, following the [migration plan](specs/full-colors/docs/migration-plan.md).
- **Exit gate:** Source and linked-ROM inventory agree on one authority; supported and unsupported decisions match at load and VBlank; forced insufficient budgets defer before presentation; every admitted commit is atomic; natural traversal and frame review show no tile/attribute mismatch.
- **Debt/constraint consequence:** The playable outdoor and conventional-interior map set is broader than its retained harness authority. The successful ROM builds and donor table checks do not claim PyBoy coverage or visual acceptance for the expanded interiors.

## Milestone 3 — Full overworld OBJ ownership

- **Outcome:** Player, follower Pikachu, NPCs, items, boulders, cut trees, shadows, effects, and other overworld objects receive authored palettes based on final picture identity.
- **Scope:** Complete shadow-OAM construction through hardware-OAM DMA, preserve attribute bits 3–7, use deterministic palette-0 fallback for unknown identities, and keep standalone-scene objects Yellow-owned. Follow the object contract in the [requirements](specs/full-colors/docs/requirements.md).
- **Exit gate:** All reachable overworld picture identities are inventoried and reviewed; missing and hostile identities fail safely; bank/interrupt tests and natural moving-object journeys show stable BG/OBJ composition in both modes.
- **Debt/constraint consequence:** Existing OAM code is scaffolding, not acceptance evidence. Activating it before final-picture and DMA ownership close would create a second uncontrolled writer.

## Milestone 4 — Architecture stress and timing expansion gate

- **Outcome:** The combined map, palette, transfer, OAM, overlay, handoff, and generation system has measured capacity and timing headroom before content scales.
- **Scope:** Exercise poisoned handoffs, rapid map connections, animation plus dialogue plus moving objects, generation churn, bank torture, threshold-plus-one deferral, and reserved commit completion. Record numeric timing rows and selected pressure policy for each request class.
- **Exit gate:** All architecture-expansion criteria in the [acceptance criteria](specs/full-colors/docs/acceptance-criteria.md) pass under real-ROM pressure; manual frame strips remain clean; the mutation-sensitive checker rejects each targeted ownership, timing, and inventory corruption.
- **Debt/constraint consequence:** This is a hard stop. If the design cannot survive combined pressure, repair or simplify it here; do not compensate with map-specific exceptions in later content work.

## Milestone 5 — Complete Yellow-specific map background content

- **Outcome:** Every Yellow map background and all 25 Yellow tilesets, including interiors, special maps, and Yellow-only content, have independently authored and reviewed Color palettes, attributes, roofs, overrides, animated tiles, and replacements.
- **Scope:** Land remaining content in bounded geographic or tileset PRs, each backed by source/ROM inventory, integrity checks, natural routes, and manual frame review. The conventional-interior donor slice is playable but still needs that visual acceptance; use pinned `pokered-gbc` data only as a candidate starting point and validate every retained value against Yellow graphics and behavior.
- **Exit gate:** Every map-background content row is complete, including every interior and special map; no map falls back because content is merely missing, all directions and mutations are covered, and representative day-to-day plus hostile journeys pass in both modes.
- **Debt/constraint consequence:** Similar names or graphics do not prove equivalence. Unknown artistic cases should remain explicit Yellow fallback until reviewed, never be filled by bulk donor import.

## Milestone 6 — Overworld handoff closure

- **Outcome:** Every concrete transition between the full-color map lifecycle and a Yellow-owned standalone lifecycle transfers ownership before the destination writes and reconstructs exactly once on a real return.
- **Scope:** Close normal, nested, reset, interrupted, blackout, warp, error, link-failure, and abnormal edges using the scene model in [scope](specs/full-colors/docs/scope.md). Poison prior resources in tests so accidental screen preservation cannot pass.
- **Exit gate:** Every reachable directed edge has source and ROM evidence; Color→Yellow and Yellow→Color transitions are atomic; Yellow→Yellow edges invent no map work; natural journeys and manual frame strips show no flash or stale resource.
- **Debt/constraint consequence:** This closes the overworld boundary, not the whole Color product. The following milestones deliberately expand tracked scope beyond the current standalone-scene exclusions and therefore require requirements, inventories, and acceptance criteria to be extended before implementation.

## Milestone 7 — Map-backed UI, menus, and text

- **Outcome:** Every map-backed or general UI surface—dialogue, text boxes, Start and list menus, PC, prompts, field-move overlays, and related UI overlays—has an authored Color presentation while Yellow remains exact.
- **Scope:** Inventory UI lifecycles and shared font/window/palette writers, define explicit composition and reconstruction ownership, then migrate bounded UI families rather than adding overlay-specific restoration hooks. Map backgrounds, including interiors and special maps, remain owned by Milestone 5; naming and Town Map lifecycles remain owned by Milestone 9.
- **Exit gate:** Text remains readable, windows and cursors retain semantics, nested menus and cancellations are clean, and natural input journeys cover every migrated family in both modes with frame review.
- **Debt/constraint consequence:** Shared UI routines cross many scenes. Do not infer ownership from a routine name or recolor all callers until their distinct destinations and lifecycle rows are closed.

## Milestone 8 — Battles, HUD, Pokémon/trainers, and effects

- **Outcome:** Wild and trainer battles, battle HUD, Pokémon and trainer pictures, transitions, status effects, and battle animations are fully authored in Color and unchanged in Yellow.
- **Scope:** Establish battle-local BG/OBJ palette authority, species/trainer/effect assignments, animation lifetimes, fades, and entry/return barriers without altering battle mechanics or RNG.
- **Exit gate:** Representative and hostile battles cover all effect families, substitutions, captures, fainting, switching, status, and return paths; semantic gameplay traces match Yellow mode and visual artifacts contain no mixed-owner frame.
- **Debt/constraint consequence:** The current specification explicitly excludes this work. Expand the tracked contract first, and do not reuse overworld inference for battle pictures or effects.

## Milestone 9 — Introductory, identity, and player-record scenes

- **Outcome:** Boot/splash, title, Yellow intro, Oak speech, Pokédex, party/status, trainer card, naming, town map, and related record screens have reviewed Color art and exact Yellow presentation.
- **Scope:** Migrate lifecycle families with shared palette, tile, and OAM writers, including the complete naming and Town Map lifecycles; include hard boot, soft reset, New Game, Continue, nested entry, and return paths.
- **Exit gate:** Cold-boot journeys cover New Game and Continue through every family, and dedicated journeys close naming and Town Map entry, interaction, cancellation, completion, nested-entry, and return paths; record data and save behavior are mode-invariant; screenshots and frame strips pass human review in both modes.
- **Debt/constraint consequence:** Startup and save-adjacent scenes are high blast radius. Presentation preference may persist, but initialization ordering and player data must not acquire mode-dependent behavior.

## Milestone 10 — Cutscenes, Pikachu, trade, evolution, and Hall of Fame

- **Outcome:** Scripted cutscenes, Pikachu emotion/front-picture scenes, evolution, trade, Hall of Fame, and other cinematic lifecycles are fully authored in Color.
- **Scope:** Inventory each scripted entry, nested scene, interruption, and return; author scene-specific BG/OBJ palettes and effects while preserving dialogue, animation cadence, cry/audio synchronization, and progression.
- **Exit gate:** Natural journeys reach every lifecycle and abnormal exit; gameplay/save semantic traces match between modes; frame review shows stable transitions and correct character identity.
- **Debt/constraint consequence:** These are heterogeneous lifecycles, not one “cutscene renderer.” Keep PRs bounded by shared ownership and evidence, not by a cosmetic global palette pass.

## Milestone 11 — Minigames, link, printer, and ending

- **Outcome:** Slots, Pikachu’s Beach/Surfing Pikachu, link rooms and transfers, printer flows, credits, ending, and every remaining visible special mode are fully authored in Color.
- **Scope:** Treat each subsystem’s timing, error, disconnect, peripheral, and return behavior as its own inventory slice. Preserve protocol and peripheral behavior exactly.
- **Exit gate:** Normal and failure journeys cover all reachable paths in both modes; link/printer behavior has hardware-appropriate or justified emulator evidence; credits and ending pass complete manual review.
- **Debt/constraint consequence:** Hardware-dependent proof may remain uncertain until representative hardware is available. Record that uncertainty explicitly; emulator-only success must not be described as hardware qualification.

## Milestone 12 — Ownership cleanup without deleting the Yellow backend

- **Outcome:** Transitional adapters, dormant experiments, failed restoration paths, duplicate writers, and obsolete ownership are removed; the selected Yellow presentation backend remains intentional, reachable only through the mode authority, and fully tested.
- **Scope:** Audit source and linked ROMs for dead or bypassable writers, collapse temporary routing, retire unused diagnostics only when no accepted evidence consumes them, and update the [architecture](docs/ARCHITECTURE.md) and [technical debt register](TECH_DEBT.md).
- **Exit gate:** Every visible resource has one authorized writer per effective mode; no uncontrolled competing path or stale generation is reachable; retained Yellow code has an explicit continuing justification; removed paths are absent from source and symbols.
- **Debt/constraint consequence:** “Remove old ownership” must mean remove uncontrolled and superseded ownership, not delete the product’s promised Yellow presentation. Any unresolved conflict in tracked removal criteria blocks this milestone.

## Milestone 13 — Full-game release qualification

- **Outcome:** A release candidate can be played start-to-finish in either persistent mode, switching at supported boundaries, with identical gameplay and save outcomes and complete authored Color coverage.
- **Scope:** Run full-game and targeted natural cold-boot journeys, save/reset/Continue and cross-mode save tests, long soaks, numeric timing and bank stress, reproducible builds, release/debug/VC partition checks, complete visual-class review, and hosted CI. Follow the [development workflow](docs/DEVELOPMENT_WORKFLOW.md).
- **Exit gate:** No visible scene class is unaccounted for; Color has no unintended Yellow fallback; Yellow matches its approved baseline; gameplay and save semantic comparisons agree; all inventory, provenance, timing, mutation, audit, visual, build, and hosted-CI gates are green.
- **Debt/constraint consequence:** Release is blocked by unknown scene coverage, unreviewed art, unexplained emulator/hardware gaps, or waived evidence. Documented uncertainty is acceptable during development; silent uncertainty is not a release gate.

## Delivery policy

- Use bounded draft PRs aligned to one milestone or a coherent slice within it. Do not mix later-phase cleanup or content into an earlier gate.
- Commit at reviewed, independently green checkpoints. Push each checkpoint and leave a short PR status comment stating what now works, verification run, known risks or decisions, and the next checkpoint.
- Keep questions and reversible decisions in PR comments so work can proceed asynchronously; stop only for a genuinely high-impact fork, destructive ambiguity, or external blocker.
- Mark a draft ready for review only when its declared milestone/slice exit gate and hosted CI are green. Do not use a green PR from one phase to justify phase drift into the next.
