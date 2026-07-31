# Acceptance criteria

This file is the sole authority for observable completion outcomes; mandatory
behavior and vocabulary remain defined in [requirements.md](requirements.md).

## Cross-cutting contract outcomes

- **AC-OWN-01:** Hostile writer traces contain no owner, phase, generation, or routed-VBlank violation. Direct requirements: R1.1, R1.2, R1.3, R1.4, R1.5, R10.2.
- **AC-REQUEST-01:** Runtime pressure tests exercise exactly the Gate 0-selected policy for each request class; required visible-state work that cannot coalesce defers and retries, final capacity rejection occurs only for optional or supersedable work with a proven fallback, and schema/reference-model tests cover unselected enum branches without losing admitted work. Direct requirements: R1.8, R1.9, R1.10, R1.11, R1.12, R1.13, R1.14, R1.15, R1.16, R1.18, R1.26, R1.28.
- **AC-JOB-01:** Handoff, reset, supersession, stale-generation, and adversarial sequences prove that older jobs cancel with the required reason and never write. Direct requirements: R1.6, R1.19, R1.20, R1.24, R1.27, R2.1, R2.2, R2.3, R2.8, R2.9.
- **AC-COMMIT-01:** Forced insufficient budget at every pre-visible preparation and revalidation boundary defers before `COMMITTING`; after a visible-destination job reserves its measured worst-case completion budget and enters `COMMITTING`, it completes without arbitrary interruption, and every presented boundary exposes only the complete old or new unit. Direct requirements: R1.17, R1.21, R1.22, R1.23, R1.25, R1.28, R7.3, R7.4, R10.4, R10.10.
- **AC-RETURN-01:** Every concrete Yellow-to-full-color overworld boundary poisons prior screen resources, rebuilds every reconstruction item from authoritative state, crosses one presentation barrier, and only then presents the map; standalone or Yellow-to-Yellow edges without that concrete boundary require no reconstruction. Direct requirements: R2.7, R2.10, R2.11, R2.12, R2.13.
- **AC-OVERLAY-01:** Requests carrying authoritative BG/window destination, map and tileset identity, world transform, override set, classifications, tile IDs, and attributes preserve source-to-destination and source-to-world mapping through clipping; ordinary, fully clipped, partially clipped, edge, connection, alternate-BG, and alternate-map cases match the full-byte oracle without VRAM or ambient-map input. Direct requirements: R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11.
- **AC-OAM-01:** Missing, out-of-range, and unmapped picture identities select OBJ palette 0, diagnostic builds record debug evidence, and OAM bits 3–7 remain unchanged. Direct requirements: R9.1, R9.2, R9.3, R9.4.
- **AC-TIME-01:** Every activated renderer timing row is numeric and passes its equation; every pre-visible boundary proves threshold-plus-one deferral before `COMMITTING`, and reserved visible commits finish. Direct requirements: R9.7, R10.3, R10.4, R10.7, R10.8, R10.9, R10.10.
- **AC-INV-01:** Phase 0 source plus built-ROM discovery closes every baseline row, and each later new symbol or directed edge adds and reviews its concrete row atomically and reruns both closure passes before reachability. Direct requirements: R1.7, R12.6, R12.8.
- **AC-TRACE-01:** Every requirement maps to at least one named check, every named check maps to at least one requirement, and the definition-derived acceptance requirement sets equal their AC-MAP cells. Direct requirements: R11.4, R12.6.

## Gate 0 prerequisite

- **AC-G0-01:** The [prerequisite gates](prerequisite-gates.md) pass only harness, schema, self-mutation, baseline-inventory, representation-selection, and baseline timing-instrument-readiness outcomes twice against the baseline debug ROM before production renderer work begins; no renderer request, commit, return, overlay, OAM, or operation-timing acceptance is claimed. Direct requirements: R1.26, R3.3, R10.3, R11.6.

## Overworld

- **AC-OW-01:** All 25 tilesets use independently authored and Yellow-validated palette/attribute content with expected full-byte assignments and build-time table integrity. Direct requirements: R5.1, R6.1, R6.2, R6.3, R8.1, R8.2, R8.3, R8.4.
- **AC-OW-02:** Initial entry, reload, horizontal and vertical scrolling, and all four connections preserve paired color state at every visible boundary. Direct requirements: R2.5, R7.1, R7.3, R10.5.
- **AC-OW-03:** Dialogue, text boxes, and transient map overlays preserve paired attributes and the authoritative overlay request contract without erasure, smearing, or competing ownership. Direct requirements: R6.3, R6.4, R6.8, R6.11, R7.1.
- **AC-OW-04:** Roofs, world-coordinate overrides, animated tiles, and field replacements produce their declared tiles, attributes, and tile-data dependencies. Direct requirements: R6.9, R7.1, R8.5, R8.6.
- **AC-OW-05:** Player, follower Pikachu, NPCs, and every mapped object use deliberate final-picture-identity OBJ palette mapping through a complete shadow-to-hardware OAM operation. Direct requirements: R5.2, R9.1, R9.2, R9.5, R9.6, R9.8, R9.9.
- **AC-OW-06:** No tested overworld sequence presents a stale, white, black, partially committed, tile/attribute-mismatched, or visibly wobbling frame. Direct requirements: R5.3, R5.4, R5.5, R7.3, R9.7.

## Handoffs

- **AC-HO-01:** Every concrete map-to-Yellow boundary selects Yellow before entry to destination initialization and therefore before its first display write. Direct requirements: R2.4, R2.6, R12.2.
- **AC-HO-02:** Every excluded lifecycle remains functionally equivalent to the baseline apart from the explicit CGB-only product boundary. Direct requirements: R12.1, R12.5.
- **AC-HO-03:** Every concrete Yellow-to-full-color overworld boundary reconstructs from authoritative state, while standalone and Yellow-to-Yellow edges with no such boundary do not invent map entry or return work. Direct requirements: R2.7, R2.10, R2.11, R2.12, R2.13.
- **AC-HO-04:** Repeated, nested, reset, interrupted, boot, and Yellow-to-Yellow error transitions follow the directed scene graph without leaking ownership or executable work. Direct requirements: R1.6, R1.25, R2.1, R2.2, R2.3, R2.8, R2.9.

## Technical

- **AC-TECH-01:** Release, debug, and VC ROM variants build reproducibly with warnings fatal, valid placement, complete tables, and no debug-only canary leakage. Direct requirements: R4.1, R4.2, R4.3, R4.4, R8.4, R11.2.
- **AC-TECH-02:** Header validation identifies the cartridge as CGB-only, hard boot initializes exactly once, soft reset clears renderer state, and non-CGB startup reaches the rejection path. Direct requirements: R3.1, R3.2, R3.4.
- **AC-TECH-03:** Baseline and atomically extended hardware-writer inventories close with no reachable unreviewed writer. Direct requirements: R1.7, R12.6.
- **AC-TECH-04:** Runtime owner and writer assertions remain silent for valid sequences and fire for each targeted ownership or direct-write mutation. Direct requirements: R1.3, R1.4, R5.6, R12.6.
- **AC-TECH-05:** Semantic snapshots match expected completed-resource and reconstruction state at every required checkpoint. Direct requirements: R1.23, R2.11, R5.1, R5.2, R5.3, R5.4.
- **AC-TECH-06:** Seeded ownership-model sequences match request, job, cancellation, generation, phase, owner, and routed-VBlank state. Direct requirements: R1.2, R1.5, R1.19, R1.20, R2.9, R10.2.
- **AC-TECH-07:** Forced entry-bank and interrupt tests preserve selected WRAM placement, bank/stack state, MBC5 call behavior, LCD composition, and scheduled-work bank restoration. Direct requirements: R3.3, R3.5, R3.6, R4.5, R10.1, R10.6.
- **AC-TECH-08:** Every activated LCD, VBlank, palette, transfer, and OAM operation has complete numeric evidence, selected scheduling, pre-visible deferral, and reserved-budget completion. Direct requirements: R5.8, R9.7, R10.4, R10.5, R10.8, R10.9, R10.10.
- **AC-TECH-09:** Each critical gate's mutation test proves that the prerequisite suite and CI detect its named target failure before renderer expansion. Direct requirements: R11.6, R12.6.
- **AC-TECH-10:** Every diagnostic checkpoint produces complete fallback, canary, screenshot, bounded frame-strip, semantic, trace, and LLM-visible evidence. Direct requirements: R9.4, R11.1, R11.3, R11.4, R11.5.

## Architecture expansion gate

- **AC-STRESS-01:** Combined renderer pressure preserves selected per-class request accounting, owner gating, pre-visible deferral, reserved complete commit units, and numeric timing margins. Direct requirements: R1.15, R1.16, R1.21, R1.22, R1.26, R7.3, R9.7, R10.8, R10.9, R10.10.
- **AC-STRESS-02:** Each proven Yellow-to-full-color overworld handoff reconstructs after every prior screen resource is poisoned and presents only after the barrier. Direct requirements: R2.7, R2.10, R2.11, R2.12, R2.13.
- **AC-STRESS-03:** A connection transfer defers at every insufficient pre-visible boundary and, once visibly committing with reserved budget, completes without a mixed tile/attribute frame; arbitrary interruption is limited to inactive or LCD-off work. Direct requirements: R2.2, R7.1, R7.3, R7.4, R10.4, R10.10.

## Removal

- **AC-REMOVE-01:** Yellow's old overworld tint and attribute ownership paths are unreachable and deleted, with no selectable dual-renderer mode. Direct requirements: R12.4, R12.7.
- **AC-REMOVE-02:** No failed-hybrid restoration hook, captured-screen restoration path, or donor standalone runtime remains reachable. Direct requirements: R2.13, R6.12, R7.2, R12.3.
- **AC-REMOVE-03:** Every transitional adapter has a reviewed continuing justification tied to retained Yellow behavior or is removed with obsolete overworld ownership. Direct requirements: R12.4, R12.5.
- **AC-REMOVE-04:** Yellow code required by excluded lifecycles remains present, donor excluded runtime stays absent, and regression checks pass. Direct requirements: R12.1, R12.3, R12.5.

## Definition of done

- **AC-DONE-01:** Completion requires exclusive full-color overworld ownership, reconstruction only on actual Yellow-to-overworld boundaries, paired transfers, a prerequisite suite that preceded production work, retained Yellow lifecycles, removed old ownership, and enforced inventory/trace closure. Direct requirements: R1.1, R2.7, R7.1, R11.6, R12.1, R12.4, R12.6.
