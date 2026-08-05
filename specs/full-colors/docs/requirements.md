# Normative requirements

This file is the sole authority for mandatory renderer behavior and symbolic
vocabulary; numeric enum values, binary layouts, and storage addresses are not
part of the contract.

## Stable vocabulary

| Kind | Symbolic values |
|---|---|
| owner | `RENDERER_YELLOW`, `RENDERER_FULL_COLOR_OVERWORLD` |
| preference | `COLOR`, `YELLOW` |
| lifecycle | ordinary map presentation, overlay, dialogue, menu, battle, standalone, boot/reset |
| phase | `YELLOW_ACTIVE`, `HANDOFF_TO_OVERWORLD`, `OVERWORLD_RECONSTRUCTING`, `OVERWORLD_ACTIVE`, `OVERWORLD_OVERLAY`, `HANDOFF_TO_YELLOW`, `YELLOW_RECONSTRUCTING` |
| request result | `ACCEPTED`, `COALESCED`, `DEFERRED`, `REJECTED_WRONG_OWNER`, `REJECTED_STALE_GENERATION`, `REJECTED_CAPACITY` |
| job state | `PENDING`, `PREPARED`, `COMMITTING`, `COMPLETE`, `CANCELLED` |
| cancellation reason | `HANDOFF`, `RESET`, `SUPERSEDED`, `STALE_GENERATION` |
| overlay cell | `OPAQUE_OVERLAY`, `REVEALED_TERRAIN` |

A request is desired visible state. A job is schedulable work realizing one or
more requests. A generation is an opaque equality token for one ownership
epoch. The saved preference is policy input only and never grants write
authority. Numeric enum values are not part of this contract.

| Phase | Permitted owner state | Requirement |
|---|---|---|
| `YELLOW_ACTIVE` | Yellow selected | R1.2 |
| `HANDOFF_TO_OVERWORLD` | Yellow selected until the ordered selection step, then full-color selected | R1.2 |
| `OVERWORLD_RECONSTRUCTING` | full-color selected | R1.2 |
| `OVERWORLD_ACTIVE` | full-color selected | R1.2 |
| `OVERWORLD_OVERLAY` | reserved and unreachable in the bounded production product | R1.2, R6.13 |
| `HANDOFF_TO_YELLOW` | full-color selected until the ordered selection step, then Yellow selected | R1.2 |
| `YELLOW_RECONSTRUCTING` | Yellow selected; admission closed until complete reconstruction and the barrier | R1.2, R2.6, R2.8 |

## R1 Renderer ownership

- **R1.1:** Exactly one active owner shall be selected from `RENDERER_YELLOW` and `RENDERER_FULL_COLOR_OVERWORLD`.
- **R1.2:** The active owner and lifecycle shall use only the phases defined in the stable vocabulary.
- **R1.3:** Yellow shall perform no owner-gated hardware or shadow-state write during full-color ownership.
- **R1.4:** The full-color renderer shall perform no owner-gated hardware or shadow-state write during Yellow ownership.
- **R1.5:** Every request and job shall carry the owner and generation under which it may execute.
- **R1.6:** Work from a departing ownership generation shall not execute after handoff.
- **R1.7:** Phase 0 shall prove source and built-ROM discovery on a reviewed initial map-entry slice, and each implementation phase shall close stable reviewed rows for every direct, indirect-high-memory, DMA, wrapper, and interrupt writer it touches before the changed path becomes reachable.

### Request and job contract

- **R1.8:** Admission shall declare the requested owner, generation, resources, visible commit unit, and desired result.
- **R1.9:** An owner mismatch shall return `REJECTED_WRONG_OWNER`, create no job, and attach to no job.
- **R1.10:** A generation mismatch shall return `REJECTED_STALE_GENERATION`, create no job, and attach to no job.
- **R1.11:** `ACCEPTED` shall create tracked work that realizes the admitted request.
- **R1.12:** `COALESCED` shall attach the request to equivalent tracked work without creating a distinct job.
- **R1.13:** `DEFERRED` shall create no work, attach to no work, and require the caller to retry while the visible state is still required.
- **R1.14:** `REJECTED_CAPACITY` shall create no work, attach to no work, and shall be used only for an optional or supersedable request class whose caller has a documented final-rejection fallback.
- **R1.15:** At capacity, an equivalent request shall return exactly `COALESCED`, while each non-equivalent request class shall return exactly the measured policy selected when that class is implemented: required visible-state work returns `DEFERRED` and is retried, whereas only an optional or supersedable class meeting R1.14 may return `REJECTED_CAPACITY`.
- **R1.16:** Capacity pressure shall never silently discard a request that returned `ACCEPTED` or `COALESCED`.
- **R1.17:** Jobs in `PENDING` or `PREPARED` may change scratch state only and shall not change a presented resource.
- **R1.18:** Coalescing shall be permitted only when ordered execution would produce the same final state at the same visible boundary.
- **R1.19:** A job shall advance only through `PENDING` to `PREPARED` to `COMMITTING` to `COMPLETE`, except that `PENDING` or `PREPARED` may advance to `CANCELLED`.
- **R1.20:** Every cancellation shall record exactly one reason from `HANDOFF`, `RESET`, `SUPERSEDED`, or `STALE_GENERATION`.
- **R1.21:** A job shall revalidate owner, generation, destination, and the applicable numeric time budget at every pre-visible preparation or revalidation boundary.
- **R1.22:** Insufficient time at any pre-visible boundary shall leave the entire visible commit unit unpresented and prepared for a later attempt.
- **R1.23:** Completion shall be recorded only after every declared resource equals the request's desired state.
- **R1.24:** Cancelled work shall perform no later write.
- **R1.25:** Entry to `COMMITTING` shall reserve the measured worst-case budget needed to complete the visible unit without interruption, except that arbitrary interruption is permitted while writing only an inactive destination or while the LCD is off.
- **R1.26:** The phase that first implements each request class or storage allocation shall select its capacity, descriptor semantics, indices, scratch layout, WRAM placement, and pressure policy from measurements taken against that implementation; runtime tests shall exercise the selected policy while schema and reference-model tests cover every result branch.
- **R1.27:** Owner, generation, or destination revalidation failure before visibility shall cancel the job with the applicable stable reason and perform no visible write.
- **R1.28:** Numeric-budget failure before visibility shall leave the complete job prepared for a later commit attempt rather than returning an admission result.
- **R1.29:** The saved `COLOR` or `YELLOW` preference shall be policy input only and shall never directly authorize an owner-gated hardware or shadow-state write.
- **R1.30:** `effective_owner(preference, lifecycle, map)` shall return `RENDERER_FULL_COLOR_OVERWORLD` if and only if preference is `COLOR`, lifecycle is ordinary map presentation, and the map is a city or route whose header selects the `OVERWORLD` tileset; every other input shall return `RENDERER_YELLOW`.
- **R1.31:** The complete preference × lifecycle × map matrix shall select exactly one effective owner in every cell, and owner-gated dispatch shall use that effective owner rather than the saved preference.
- **R1.32:** The effective owner shall be recomputed before the destination's first owner-gated write; an unchanged decision shall preserve owner and generation, while a changed decision shall execute exactly one complete handoff and advance generation exactly once.
- **R1.33:** VBlank shall select the effective owner once before its first visible writer and shall run exactly one owner route for that frame.

## R2 Generation, handoff, reset, and reconstruction

- **R2.1:** A handoff shall close admission for the departing owner before draining or cancelling its work.
- **R2.2:** A handoff shall finish an already-visible complete unit or cancel its job before visibility.
- **R2.3:** A handoff shall establish a fresh non-aliasing generation and invalidate all older work before the arriving owner can write.
- **R2.4:** A handoff shall select and initialize the arriving owner, reconstruct every destination authority from fresh logical state, cross exactly one presentation barrier, and only then reopen admission.
- **R2.5:** Entry to Color-owned ordinary presentation of a supported `OVERWORLD` map shall load tileset palette and attribute data and complete full reconstruction before presentation.
- **R2.6:** Every Color-to-Yellow boundary, including overlay, dialogue, menu, battle, standalone, unsupported-map, preference, reset, and soft-reset boundaries, shall enter `YELLOW_RECONSTRUCTING`, treat the complete R2.10 resource set as unknown, rebuild the complete R2.11 ledger from fresh logical authority, cross exactly one R2.12 barrier, and only then reopen admission or permit the destination's first owner-gated display write.
- **R2.7:** Every concrete Yellow-to-Color boundary for eligible ordinary presentation of a supported `OVERWORLD` map shall run the complete overworld-entry protocol; a same-owner decision shall preserve generation and perform no synthetic handoff or reconstruction.
- **R2.8:** Soft reset shall cancel all work, invalidate all generations, restore machine state, select Yellow, and re-enter normal boot. Reset and soft reset from Color ownership shall additionally complete the R2.6 Color-to-Yellow contract before presentation: if the display stays provably hidden, admission shall remain closed through fresh Yellow reconstruction and its one barrier; otherwise the ordinary complete handoff shall finish before any reset-owned video write.
- **R2.9:** A generation value shall not be reused while any work carrying that value can execute.

### Complete destination reconstruction

- **R2.10:** `OVERWORLD_RECONSTRUCTING` and `YELLOW_RECONSTRUCTING` shall treat prior tiles and tilemaps, attributes, palette sources, transformed palettes and palette hardware, shadow and hardware OAM, viewport, scroll, window and destination state, buffers, flags, animations and field replacements, jobs, banks, stack, and interrupt state as unknown.
- **R2.11:** Before presentation, reconstruction shall complete map, tileset, and override identity; viewport, scroll, window, and destination state; required tiles and animation or field replacements; all presentable bank-0 tilemaps and freshly generated bank-1 attributes; base, transformed, and hardware palettes; player, follower, and object shadow OAM; current-generation scheduler state; and restored banks, stack, and interrupt state.
- **R2.12:** Exactly one presentation barrier shall expose the reconstructed result before the phase changes from `OVERWORLD_RECONSTRUCTING` to `OVERWORLD_ACTIVE` or from `YELLOW_RECONSTRUCTING` to `YELLOW_ACTIVE`; admission shall reopen only after that barrier.
- **R2.13:** Captured VRAM, palette RAM, OAM, or screen-buffer bytes shall satisfy no reconstruction item.

## R3 CGB and bank foundation

- **R3.1:** The cartridge shall be CGB-only and shall reject DMG and SGB startup.
- **R3.2:** Hard boot shall enter double-speed mode exactly once.
- **R3.3:** Renderer state shall occupy the WRAM placement selected during Phase 1 from current link-map, byte-cost, bank-cost, interrupt-access, and stack-margin evidence.
- **R3.4:** Hard boot and soft reset shall clear and initialize renderer state before it can be observed.
- **R3.5:** Renderer calls and interrupts shall preserve ROM bank, `rSVBK`, `rVBK`, stack, and interrupt state across their call or interrupt boundary.
- **R3.6:** Control shall never return to Yellow code with an accidental ROM, WRAM, or VRAM bank selection.

## R4 ROM placement

- **R4.1:** Renderer placement shall not use RGB bank `$2c` because Yellow stores Text 7 there.
- **R4.2:** The port shall not import RGB bank `$31` because Yellow stores Pikachu cries there.
- **R4.3:** The port shall not assume RGB's `$1c` extension is free in Yellow.
- **R4.4:** Yellow's empty ROM bank `$3b` shall remain the measured starting candidate rather than an unmeasured fixed allocation.
- **R4.5:** Every donor MBC1 assumption shall be converted to Yellow's MBC5 far-call conventions.

## R5 Palette model

- **R5.1:** The renderer shall store eight four-color RGB555 BG palettes.
- **R5.2:** The renderer shall store eight four-color RGB555 OBJ palettes.
- **R5.3:** The renderer shall maintain complete transformed BG and OBJ buffers separate from base palette data.
- **R5.4:** `BGP`, `OBP0`, and `OBP1` remapping shall not destroy base palette data.
- **R5.5:** The renderer shall support overworld fades, flashes, white, black, and poison effects.
- **R5.6:** Gameplay code shall request palette state or set dirty state, and only the active owner shall schedule hardware palette writes.
- **R5.7:** Palette wrappers shall dispatch according to the active owner and generation.
- **R5.8:** A BG or OBJ palette change shall commit the complete requested 64-byte payload as one visible unit.

## R6 Attribute and overlay model

- **R6.1:** Map attributes shall use a 256-entry tile-ID-to-CGB-attribute lookup for the active tileset.
- **R6.2:** Every tileset shall define deliberate assignments for tile IDs `$00` through `$5f`.
- **R6.3:** Tile IDs `$60` through `$ff` shall use a deliberate text or window default unless explicitly assigned.

### Full-byte attribute precedence

- **R6.4:** Every overlay request shall carry the authoritative destination BG/window selector, destination map identity, tileset identity, destination rectangle, world-coordinate origin or transform, complete coordinate-override set, per-source-cell classification as `OPAQUE_OVERLAY` or `REVEALED_TERRAIN`, desired tile IDs, and any explicit full-byte overlay attributes.
- **R6.5:** Overlay processing shall clip the destination rectangle to the selected presentable destination before classification while preserving the request's source-to-destination tilemap mapping and source-to-world-coordinate transform.
- **R6.6:** Every surviving overlay cell shall be classified from the request's authoritative per-cell data.
- **R6.7:** Every generated CGB attribute shall assign palette bits 0–2, tile-bank bit 3, flip bits 5–6, and priority bit 7 while canonicalizing bit 4 to zero.
- **R6.8:** An `OPAQUE_OVERLAY` cell shall use its explicit full-byte assignment or the defined text or window default.
- **R6.9:** A `REVEALED_TERRAIN` cell shall use the supplied override for its derived world coordinate or the supplied tileset identity's 256-entry lookup for the request's desired tile ID.
- **R6.10:** Overlay classification, tile identity, and attribute generation shall never sample either VRAM bank as oracle input.
- **R6.11:** The same overlay oracle shall govern unclipped, partially clipped, edge, connection, alternate-BG, alternate-map-identity, and empty-after-clipping requests without consulting ambient active-map state.
- **R6.12:** RGB's standalone-screen 20×18 palette-map mode shall not be imported for an overworld overlay.
- **R6.13:** Production overlays, dialogue, text, and transient menus shall be Yellow-owned and shall not enter the Color pipeline; `OVERWORLD_OVERLAY` remains reserved and unreachable in this bounded product.

## R7 Paired transfers and visible commit units

- **R7.1:** Every listed overworld tile-writing path shall commit bank-0 tile IDs and matching bank-1 attributes through the same job or a serialized paired job.
- **R7.2:** No gameplay-level hook shall exist solely to repair color state overwritten by another renderer.
- **R7.3:** The first frame at a visible boundary shall contain the complete old commit unit or the complete new commit unit.
- **R7.4:** Work may be interrupted while preparing under LCD-off or in an inactive destination, but visible-destination work that cannot reserve its measured worst-case completion budget shall defer before `COMMITTING`.

### Visible commit units

| Operation | Atomic visible unit | Requirement |
|---|---|---|
| load, reload, or actual Yellow-to-Color eligible-map boundary | complete reconstruction before presentation | R2.11, R2.12 |
| actual Color-to-Yellow boundary, including reset or soft reset from Color | complete fresh Yellow reconstruction and exactly one barrier before admission or presentation | R2.6, R2.10, R2.11, R2.12 |
| horizontal or vertical streaming, all four connection directions, one-third window/tilemap transfer, explicit row, or rectangle transfer | all bank-0 IDs and matching bank-1 attributes | R7.1, R7.3 |
| dialogue, text, transient-menu, or field-move overlay | Yellow-owned declared baseline unit; Color pipeline unreachable | R6.13, R7.3 |
| alternate BG map destination | every declared tile/attribute pair | R7.1, R7.3 |
| animation or field replacement | tile ID, attribute, and declared tile-data dependency | R7.1, R7.3 |
| palette change | complete requested 64-byte BG or OBJ payload | R5.8 |
| overworld OAM | complete shadow entries before DMA | R9.2, R9.8 |

## R8 Tileset data

- **R8.1:** Palette sets and exactly `$60` deliberate assignments shall exist for all 25 Yellow overworld tilesets.
- **R8.2:** Donor palette, mapping, roof, OAM, and content data shall be treated only as candidate organization or artistic evidence and every retained Yellow value shall be independently authored and validated against Yellow graphics and behavior.
- **R8.3:** `BEACH_HOUSE` shall have native data because RGB tileset ID 24 is `SAFARI`.
- **R8.4:** Build-time assertions shall enforce every tileset table length.
- **R8.5:** Roof assignments and every map-specific coordinate override shall be documented and tested.
- **R8.6:** Animated frames shall retain compatible 2bpp color indices.

## Stable OAM fallback and timing evidence

R9.1, R9.2, R9.3, and R9.4 define the stable fallback. R9.7, R10.3, R10.4,
R10.5, R10.6, R10.7, R10.8, R10.9, and R10.10 define its evidence and numeric
timing boundary.

## R9 Overworld OAM

R9 applies only while Color effectively owns ordinary presentation of a supported `OVERWORLD` map;
all forced-Yellow contexts retain Yellow OAM ownership.

- **R9.1:** Authoritative overworld OAM construction shall assign OBJ palette bits after final tile and Pikachu offset selection.
- **R9.2:** OAM palette assignment shall replace bits 0–2 while preserving priority, flips, tile bank, and all control bits 3–7.
- **R9.3:** Missing, out-of-range, or unmapped overworld picture identity shall select OBJ palette 0 deterministically.
- **R9.4:** Diagnostic builds shall record required debug evidence whenever the OBJ palette 0 fallback is selected.
- **R9.5:** OAM construction shall preserve `hPikachuSpriteVRAMOffset`.
- **R9.6:** Deliberate palette mapping shall cover player, follower Pikachu, NPCs, item balls, cut trees, boulders, dust, healing machine, fishing rod, ledge shadow, and emotion bubbles.
- **R9.7:** OAM work shall remain within its measured numeric budget without visible wobble.
- **R9.8:** A complete declared shadow-OAM batch shall be built before one declared shadow-to-hardware OAM DMA commits the complete hardware-OAM image.
- **R9.9:** Every mapped overworld object shall select its OBJ palette by final picture identity.

## R10 Scheduling and timing evidence

- **R10.1:** Renderer preparation shall compose with Yellow's existing LCD `wLYOverrides` handler.
- **R10.2:** VBlank work shall route according to the active owner and generation.
- **R10.3:** Timing instrumentation shall begin with the first diagnostic renderer slice.
- **R10.4:** Every timed operation shall check its exact safe-time threshold at each pre-visible preparation or revalidation boundary and reserve its measured worst-case completion budget before `COMMITTING`.
- **R10.5:** Row and column attribute transfers shall serialize against palette uploads.
- **R10.6:** Every exit from scheduled or interrupt work shall restore each temporary bank selection.
- **R10.7:** RGB scanline constants shall be treated only as reference evidence and not as accepted Yellow timing values.
- **R10.8:** Every timing budget row shall record operation, mode, ROM, tool or device, samples, worst cycles, instrumentation cycles, start, deadline, guard, margin cycles, margin percent, and exact defer threshold.
- **R10.9:** A timing budget shall pass only when `worst + instrumentation <= deadline - start - guard`.
- **R10.10:** A forced workload of exact defer threshold plus one at every pre-visible preparation or revalidation boundary shall defer the whole visible unit before `COMMITTING`.
- **R10.11:** Every timed operation made reachable by the production selector or either handoff direction shall have a named numeric cycle equation, natural budget or deadline, exact-fit commit evidence, and threshold-plus-one whole-unit defer evidence before activation; `$ffff` is not a production budget.

## R11 Diagnostic mode

- **R11.1:** A debug-only canary mode shall use unmistakable deterministic assignments for all eight palette slots and selected tile classes.
- **R11.2:** Canary output shall be unavailable in release builds.
- **R11.3:** Diagnostic checkpoints shall capture named screenshots and bounded frame strips.
- **R11.4:** Every visual artifact shall be paired with semantic state and owner, generation, job, and writer traces.
- **R11.5:** LLM screenshot inspection shall be a supported test-play workflow but shall not replace machine assertions.
- **R11.6:** Production renderer work shall not begin until the lean Gate 0 harness passes twice against the baseline debug ROM with identical semantic outputs and identical contract-versioned artifact-manifest outputs, and later renderer paths shall not expand while their activated inventory, visual, mutation, or timing gates are red.

## R12 Isolation and removal

- **R12.1:** Boot/reset, overlays, dialogue, menus, battles, standalone screens, unsupported maps, and every supported map under `YELLOW` preference shall retain Yellow rendering behavior.
- **R12.2:** Ownership shall transfer to Yellow before entry to destination initialization for a standalone lifecycle and therefore before its first display write.
- **R12.3:** RGB battle, picture, animation, minigame, and static palette-map runtime modules shall not be imported.
- **R12.4:** Yellow paths required by the `YELLOW` preference and forced-Yellow contexts shall remain reachable; only obsolete competing ownership or repair paths may be removed.
- **R12.5:** Yellow code still required by excluded scenes shall remain intact.
- **R12.6:** Owner-gated hardware-writer checks shall run in CI.
- **R12.7:** The selectable preference shall choose policy only; it shall never permit simultaneous renderer ownership, and exactly one effective owner shall control every visible resource at every instant.
- **R12.8:** Phase 0 shall prove lifecycle discovery on a reviewed initial map-entry slice, and each implementation phase shall close stable reviewed `SC-…` rows for every lifecycle and directed transition it touches before the changed path becomes reachable.

## Owner-gated resources

The permissions and visible units below are governed by R1.1, R1.2, R1.3,
R1.4, R1.5, R1.6, R1.7, R1.21, R1.22, R1.23, R1.24, R1.25, R1.26, R1.27,
R1.28, R7.1, R7.2, R7.3, and R7.4.

| Resource | Full-color permission | Yellow permission | Visible commit unit |
|---|---|---|---|
| BG palette RAM (`rBGPI/rBGPD`) | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | complete requested BG payload |
| OBJ palette RAM (`rOBPI/rOBPD`) | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | complete requested OBJ payload |
| bank-0 BG/window tile IDs | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | declared rectangle paired with attributes |
| bank-1 BG/window attributes | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | same rectangle as tile IDs |
| LCDC/STAT/scroll/window presentation registers (`rLCDC` `$ff40`, `rSTAT` `$ff41`, `rSCY` `$ff42`, `rSCX` `$ff43`, `rLYC` `$ff45`, `rBGP` `$ff47`, `rOBP0` `$ff48`, `rOBP1` `$ff49`, `rWY` `$ff4a`, `rWX` `$ff4b`) | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | declared presentation barrier |
| shadow OAM entries and lifecycle (allocate, clear, build, palette-map, sort/copy, invalidate) | supported `OVERWORLD` map while effective Color; Yellow routines may be called as mechanics | all forced-Yellow contexts | complete declared shadow-OAM batch |
| hardware OAM bytes and lifecycle (DMA destination, LCD-off initialization/clear, reset/handoff invalidation) | supported `OVERWORLD` map while effective Color | all forced-Yellow contexts | complete hardware-OAM image |
| OAM DMA source/control (`rDMA` `$ff46`) and DMA launch/wait wrappers | supported `OVERWORLD` map effective Color owner/generation; Yellow routines may be called as mechanics | all forced-Yellow contexts | one declared shadow-to-hardware OAM DMA |
| shade-remap and renderer dirty/job state | current full-color generation | independent Yellow state | generation boundary |
| `rVBK`, `rSVBK`, ROM bank, stack, interrupts | temporary and restored | temporary and restored | call/interrupt boundary |
| HDMA/GDMA for listed resources | current owner/generation | current owner/generation | declared DMA operation |
