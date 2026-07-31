# Overworld verification plan

This file is the sole requirement-to-check index. It defines future checks and
the evidence that implementation and Gate 0 execution must produce; it does
not claim that inventories, measurements, ROMs, or test artifacts already
exist. The [prerequisite suite](prerequisite-gates.md) must be operational
before renderer work starts, and the
[AI harness](ai-iteration-harness.md) runs the checks in the tiers below.

## Check definitions

- **CHK-OWN-01:** Method: seeded owner/phase/generation model sequences plus owner-gated writer traces; tier: fast/full; evidence: semantic snapshots, decoded trace, mutation result, seed, and reduced action sequence.
- **CHK-REQUEST-01:** Method: runtime pressure for exactly the selected policy of each request class plus schema/reference-model coverage of unselected enum branches; tier: fast/full; evidence: selected capacity/policy table, required-work defer/retry trace, optional-or-supersedable final-rejection fallback where selected, work accounting, and reduced seed.
- **CHK-JOB-01:** Method: handoff, reset, supersession, stale-generation, and adversarial cancellation sequences; tier: fast/full; evidence: job-state and cancellation trace proving no post-cancellation write.
- **CHK-COMMIT-01:** Method: force insufficient budget at every pre-visible preparation/revalidation boundary, verify deferral before `COMMITTING`, and verify uninterrupted completion after worst-case budget reservation; tier: focused/full; evidence: old/new semantic snapshots, frame strip, commit-unit/writer IDs, boundary defer traces, reservation record, and inactive-or-LCD-off interruption cases.
- **CHK-RETURN-01:** Method: for every concrete Yellow-to-full-color overworld boundary, record its actual Yellow-owned source lifecycle, poison every prior screen resource, and reconstruct; tier: focused/full; evidence: concrete directed scene IDs, a preceding map-to-Yellow edge and last map generation only when source/ROM proves that predecessor, poison record, reconstruction-item ledger, presentation barrier, and five active-frame snapshots.
- **CHK-OVERLAY-01:** Method: independent request-data oracle across authoritative BG/window destination, map/tileset identity, world transform, override set, clipping mappings, classification, and full-byte precedence; tier: fast/focused/full; evidence: complete request fixture, clipped source/destination/world coordinate map, expected/actual tile and attribute bytes, and trace proving no VRAM or ambient-map oracle read.
- **CHK-OAM-01:** Method: missing, out-of-range, and unmapped final-picture identities under diagnostic and release builds; tier: fast/focused; evidence: final identity, before/after attributes, palette-0 result, diagnostic fallback record, and release-symbol audit.
- **CHK-TIME-01:** Method: numeric cycle instrumentation for every operation plus an exact defer-threshold-plus-one case; tier: focused/full; evidence: completed timing row, equation result, whole-unit defer trace, and timing artifact key.
- **CHK-INV-01:** Method: reconcile source search with symbol-guided built-ROM disassembly for the Phase 0 baseline and after every atomically added concrete planned row; tier: fast/full; evidence: reviewed `WR-…`, `SC-…`, and `MU-…` rows, before-reachability review, renewed closure report, and unlisted-writer/scene/mutation fixtures.
- **CHK-TRACE-01:** Method: validate authority definitions, references, and bidirectional primary mappings; tier: fast; evidence: machine-readable mapping report and zero unknown, uncovered, duplicate, or orphan IDs.
- **CHK-G0-01:** Method: run only Gate 0 harness/schema/self-mutation, baseline-inventory, representation-selection, and baseline timing-instrument-readiness tests twice against the baseline debug ROM; tier: fast/full; evidence: identical outputs, mutation failures, artifact manifests, suite logs, and no renderer acceptance claim.
- **CHK-BUILD-01:** Method: reproducibly build release, debug, and VC variants with warnings fatal; tier: fast/full; evidence: commands, tool versions, ROM content IDs, headers, symbols, link maps, and warning logs.
- **CHK-CGB-01:** Method: exercise CGB hard boot, DMG/SGB rejection, soft reset, and double-speed initialization; tier: fast/full; evidence: header bytes, startup traces, reset snapshots, and rejection-path checkpoints.
- **CHK-BANK-01:** Method: invoke renderer paths from non-default ROM/VRAM banks, every selected renderer WRAM bank, every other valid WRAM entry bank, and interrupt boundaries; tier: fast/focused/full; evidence: before/after bank, stack, interrupt, owner, generation, and dirty-state snapshots.
- **CHK-ROM-01:** Method: inspect source, link maps, and donor adaptations for prohibited banks and MBC1 assumptions; tier: fast/full; evidence: placement decision record, link-map ranges, far-call audit, and negative source/disassembly findings.
- **CHK-PALETTE-01:** Method: compare base, transformed, and hardware BG/OBJ palettes through every remap/effect and owner-dispatched wrapper; tier: focused/full; evidence: palette snapshots, wrapper trace, complete-payload commit record, and visual checkpoints.
- **CHK-TRANSFER-01:** Method: exercise every concrete paired-transfer mutation and destination from the closed baseline and atomically extended inventories; tier: focused/full; evidence: concrete mutation/writer IDs, renewed source/ROM closure, tile/attribute byte pairs, serialization trace, and five-frame boundary captures.
- **CHK-TILESET-01:** Method: audit and exercise all 25 tilesets, table assertions, graphics, roofs, overrides, animations, and native Beach House data; tier: full; evidence: table lengths, assignment audit, semantic atlas, animation captures, and reviewed visual atlas.
- **CHK-HANDOFF-01:** Method: execute the concrete directed scene graph, including boot/reset, initial new-game/continue and other actual Yellow-owned source lifecycles, Yellow-to-Yellow nested/error edges, and only source/ROM-proven map ownership boundaries; tier: focused/full; evidence: concrete scene/writer IDs, Yellow-before-destination-initialization trace only for proven map-to-Yellow boundaries, generation transitions, reconstruction only on Yellow-to-overworld edges, and regression result.
- **CHK-OAM-02:** Method: exercise player, follower, every mapped object class, maximum population, shadow construction, sort/copy, invalidation, and one hardware DMA; tier: focused/full; evidence: concrete writer/mutation IDs, final-picture mapping, shadow/hardware OAM snapshots, DMA trace, and frame strip.
- **CHK-VISUAL-01:** Method: inspect named screenshots, bounded frame strips, and contact sheets beside semantic state; tier: focused/full; evidence: versioned manifest, reviewer result, image diffs, snapshots, and linked traces.
- **CHK-STRESS-01:** Method: repeat simultaneous scrolling, animation, palette, maximum representative OAM, and interrupt pressure; tier: focused/full; evidence: request accounting, semantic snapshots, writer trace, bank snapshots, numeric timing rows, and reviewed frame strips.
- **CHK-STRESS-02:** Method: enter a standalone lifecycle immediately after map activity, poison old resources, and return; tier: focused/full; evidence: concrete scene IDs, poison/reconstruction ledger, barrier, five active frames, model trace, and timing rows.
- **CHK-STRESS-03:** Method: force insufficient budget at every pre-visible connection-transfer boundary and interrupt mid-operation only for inactive or LCD-off destinations; tier: focused/full; evidence: concrete mutation/writer IDs, old/new snapshots, pre-commit defer traces, reserved-budget completion, bank state, timing row, and frame strip.
- **CHK-REMOVE-01:** Method: source plus built-ROM reachability audit for obsolete ownership, restoration, and transitional paths; tier: full; evidence: deleted/unreachable concrete inventory rows, negative disassembly findings, and adapter disposition report.
- **CHK-REGRESS-01:** Method: run baseline-equivalence scenarios for every retained Yellow-owned lifecycle and excluded resource path; tier: focused/full; evidence: concrete scene IDs, semantic and visual comparisons, build variants, and regression logs.
- **CHK-CANARY-01:** Method: exercise all eight diagnostic canary palette slots and selected tile classes and audit release exclusion; tier: fast/focused; evidence: semantic palette/tile snapshots, screenshots, debug trace, and release source/symbol findings.

## Requirement-to-evidence traceability

Each row has one primary requirement. Cross-reference cells contain only
defined concrete IDs.

| Map kind | Requirement | Acceptance | Check | Tier | Mutation | Evidence |
|---|---|---|---|---|---|---|
| R-MAP | R1.1 | AC-OWN-01 | CHK-OWN-01 | fast/full | zero or dual active owner | owner snapshot and writer trace |
| R-MAP | R1.2 | AC-OWN-01, AC-TECH-06 | CHK-OWN-01 | fast/full | invalid owner/phase pair | model and ROM transition trace |
| R-MAP | R1.3 | AC-OWN-01, AC-TECH-04 | CHK-OWN-01 | fast/full | Yellow write during full-color ownership | assertion and writer trace |
| R-MAP | R1.4 | AC-OWN-01, AC-TECH-04 | CHK-OWN-01 | fast/full | full-color write during Yellow ownership | assertion and writer trace |
| R-MAP | R1.5 | AC-OWN-01, AC-TECH-06 | CHK-OWN-01 | fast/full | absent owner or generation | job snapshot and trace |
| R-MAP | R1.6 | AC-JOB-01, AC-HO-04 | CHK-JOB-01 | fast/full | departing-generation execution | cancellation and no-later-write trace |
| R-MAP | R1.7 | AC-INV-01, AC-TECH-03 | CHK-INV-01 | fast/full | reachable unlisted writer | source/ROM closure report |
| R-MAP | R1.8 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | missing admission declaration | request record and assertion |
| R-MAP | R1.9 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | wrong owner | result and no-work trace |
| R-MAP | R1.10 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | stale generation | result and no-work trace |
| R-MAP | R1.11 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | accepted request untracked | request/job accounting |
| R-MAP | R1.12 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | equivalent request at capacity | coalescing attachment trace |
| R-MAP | R1.13 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | retryable pressure | deferred no-work and retry trace |
| R-MAP | R1.14 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | final pressure rejection | rejected no-work/finality trace |
| R-MAP | R1.15 | AC-REQUEST-01, AC-STRESS-01 | CHK-REQUEST-01, CHK-STRESS-01 | fast/full | capacity plus one | selected-policy result record |
| R-MAP | R1.16 | AC-REQUEST-01, AC-STRESS-01 | CHK-REQUEST-01, CHK-STRESS-01 | fast/full | admitted-work pressure | eventual-completion accounting |
| R-MAP | R1.17 | AC-COMMIT-01 | CHK-COMMIT-01 | focused/full | pending/prepared presented write | resource snapshots |
| R-MAP | R1.18 | AC-REQUEST-01 | CHK-REQUEST-01 | fast/full | non-equivalent coalescing | ordered final-state comparison |
| R-MAP | R1.19 | AC-JOB-01, AC-TECH-06 | CHK-JOB-01 | fast/full | illegal job transition | state trace and model diff |
| R-MAP | R1.20 | AC-JOB-01, AC-TECH-06 | CHK-JOB-01 | fast/full | absent/invalid cancellation reason | cancellation trace |
| R-MAP | R1.21 | AC-COMMIT-01, AC-TIME-01 | CHK-COMMIT-01, CHK-TIME-01 | focused/full | state/budget change before commit | revalidation trace and timing row |
| R-MAP | R1.22 | AC-COMMIT-01, AC-TIME-01 | CHK-COMMIT-01, CHK-TIME-01 | focused/full | insufficient time | whole-unit defer evidence |
| R-MAP | R1.23 | AC-COMMIT-01 | CHK-COMMIT-01 | focused/full | early completion record | declared-resource diff |
| R-MAP | R1.24 | AC-JOB-01 | CHK-JOB-01 | fast/full | write after cancellation | bounded trace |
| R-MAP | R1.25 | AC-COMMIT-01, AC-HO-04 | CHK-COMMIT-01, CHK-JOB-01 | focused/full | missing reservation or illegal visible mid-commit interruption | reservation, presentation, and ownership trace |
| R-MAP | R1.26 | AC-G0-01, AC-STRESS-01 | CHK-G0-01, CHK-STRESS-01 | fast/full | preselected representation | numeric decision record |
| R-MAP | R1.27 | AC-JOB-01, AC-COMMIT-01 | CHK-JOB-01, CHK-COMMIT-01 | fast/full | failed commit revalidation | cancellation/no-write trace |
| R-MAP | R1.28 | AC-REQUEST-01, AC-COMMIT-01 | CHK-REQUEST-01, CHK-COMMIT-01 | focused/full | numeric budget failure | prepared-job retry trace |
| R-MAP | R2.1 | AC-JOB-01, AC-HO-04 | CHK-JOB-01, CHK-HANDOFF-01 | focused/full | admission during handoff | admission and transition trace |
| R-MAP | R2.2 | AC-JOB-01, AC-COMMIT-01 | CHK-JOB-01, CHK-COMMIT-01 | focused/full | handoff at commit step | old/new unit and cancellation trace |
| R-MAP | R2.3 | AC-JOB-01, AC-HO-04 | CHK-JOB-01, CHK-HANDOFF-01 | focused/full | aliasing generation | generation and writer trace |
| R-MAP | R2.4 | AC-HO-01, AC-HO-04 | CHK-HANDOFF-01 | focused/full | early admission reopening | owner/init/admission trace |
| R-MAP | R2.5 | AC-RETURN-01, AC-OW-02 | CHK-RETURN-01, CHK-TRANSFER-01 | focused/full | present before reconstruction | reconstruction ledger |
| R-MAP | R2.6 | AC-HO-01 | CHK-HANDOFF-01 | focused/full | Yellow display before selection | first-writer trace |
| R-MAP | R2.7 | AC-HO-03, AC-RETURN-01 | CHK-HANDOFF-01, CHK-RETURN-01 | focused/full | actual Yellow-to-overworld boundary shortcut or invented return | directed boundary and reconstruction evidence |
| R-MAP | R2.8 | AC-JOB-01, AC-HO-04 | CHK-JOB-01, CHK-CGB-01 | fast/full | soft reset with work | reset and cancellation snapshots |
| R-MAP | R2.9 | AC-JOB-01, AC-TECH-06 | CHK-JOB-01, CHK-OWN-01 | fast/full | live-generation reuse | generation trace |
| R-MAP | R2.10 | AC-RETURN-01, AC-STRESS-02 | CHK-RETURN-01, CHK-STRESS-02 | focused/full | poisoned prior resources | unknown-state and rebuild ledger |
| R-MAP | R2.11 | AC-RETURN-01, AC-STRESS-02 | CHK-RETURN-01, CHK-STRESS-02 | focused/full | omitted reconstruction item | per-item ledger and snapshot |
| R-MAP | R2.12 | AC-RETURN-01, AC-STRESS-02 | CHK-RETURN-01, CHK-STRESS-02 | focused/full | missing/early barrier | barrier and five-frame trace |
| R-MAP | R2.13 | AC-RETURN-01, AC-REMOVE-02 | CHK-RETURN-01, CHK-REMOVE-01 | focused/full | saved-byte restoration | poison result and reachability audit |
| R-MAP | R3.1 | AC-TECH-02 | CHK-CGB-01 | fast/full | DMG/SGB startup | header and rejection checkpoints |
| R-MAP | R3.2 | AC-TECH-02 | CHK-CGB-01 | fast/full | repeated/missing speed switch | hard-boot trace |
| R-MAP | R3.3 | AC-G0-01, AC-TECH-07 | CHK-G0-01, CHK-BANK-01 | fast/full | unmeasured WRAM placement | decision record and link map |
| R-MAP | R3.4 | AC-TECH-02, AC-JOB-01 | CHK-CGB-01, CHK-JOB-01 | fast/full | observable uncleared state | boot/reset snapshots |
| R-MAP | R3.5 | AC-TECH-07 | CHK-BANK-01 | fast/full | leaked bank/stack/interrupt | boundary snapshots |
| R-MAP | R3.6 | AC-TECH-07 | CHK-BANK-01 | fast/full | accidental return bank | Yellow-return snapshots |
| R-MAP | R4.1 | AC-TECH-01, AC-TECH-07 | CHK-ROM-01, CHK-BUILD-01 | fast/full | use donor bank 2c | link-map and source audit |
| R-MAP | R4.2 | AC-TECH-01, AC-TECH-07 | CHK-ROM-01, CHK-BUILD-01 | fast/full | import donor bank 31 | link-map and source audit |
| R-MAP | R4.3 | AC-TECH-01, AC-TECH-07 | CHK-ROM-01, CHK-BUILD-01 | fast/full | assume extension bank 1c | link-map and source audit |
| R-MAP | R4.4 | AC-G0-01, AC-TECH-01 | CHK-ROM-01, CHK-G0-01 | fast/full | fixed unmeasured bank 3b | placement evidence |
| R-MAP | R4.5 | AC-TECH-07 | CHK-ROM-01, CHK-BANK-01 | fast/full | retained MBC1 assumption | far-call and bank audit |
| R-MAP | R5.1 | AC-OW-01, AC-TECH-05 | CHK-PALETTE-01 | focused/full | incomplete BG base palettes | palette snapshot |
| R-MAP | R5.2 | AC-OW-05, AC-TECH-05 | CHK-PALETTE-01 | focused/full | incomplete OBJ base palettes | palette snapshot |
| R-MAP | R5.3 | AC-OW-06, AC-TECH-05 | CHK-PALETTE-01 | focused/full | aliased base/transformed data | before/after buffers |
| R-MAP | R5.4 | AC-OW-06, AC-TECH-05 | CHK-PALETTE-01 | focused/full | destructive shade remap | base/transformed diff |
| R-MAP | R5.5 | AC-OW-06 | CHK-PALETTE-01, CHK-VISUAL-01 | focused/full | overworld visual effect | semantic palettes and frame strips |
| R-MAP | R5.6 | AC-OWN-01, AC-TECH-04 | CHK-PALETTE-01, CHK-OWN-01 | focused/full | gameplay hardware palette write | wrapper/writer trace |
| R-MAP | R5.7 | AC-OWN-01, AC-TECH-06 | CHK-PALETTE-01, CHK-OWN-01 | focused/full | wrong-owner wrapper dispatch | dispatch trace |
| R-MAP | R5.8 | AC-COMMIT-01, AC-TECH-08 | CHK-PALETTE-01, CHK-COMMIT-01 | focused/full | partial palette payload | payload snapshot and boundary frames |
| R-MAP | R6.1 | AC-OW-01 | CHK-TILESET-01 | full | lookup length/coverage | semantic atlas |
| R-MAP | R6.2 | AC-OW-01 | CHK-TILESET-01 | full | missing deliberate base assignment | assignment audit |
| R-MAP | R6.3 | AC-OW-01, AC-OW-03 | CHK-TILESET-01, CHK-OVERLAY-01 | focused/full | missing text/window default | expected attribute bytes |
| R-MAP | R6.4 | AC-OVERLAY-01, AC-OW-03 | CHK-OVERLAY-01 | fast/focused/full | incomplete request data | fixture schema and assertion |
| R-MAP | R6.5 | AC-OVERLAY-01 | CHK-OVERLAY-01 | fast/focused/full | classify before clipping | clipped coordinate map |
| R-MAP | R6.6 | AC-OVERLAY-01 | CHK-OVERLAY-01 | fast/focused/full | non-request classification | independent oracle diff |
| R-MAP | R6.7 | AC-OVERLAY-01, AC-OW-01 | CHK-OVERLAY-01 | fast/focused/full | meaningful attribute bits | full-byte expected/actual |
| R-MAP | R6.8 | AC-OVERLAY-01, AC-OW-03 | CHK-OVERLAY-01 | fast/focused/full | opaque precedence | explicit/default byte diff |
| R-MAP | R6.9 | AC-OVERLAY-01, AC-OW-04 | CHK-OVERLAY-01 | fast/focused/full | revealed precedence | override/lookup byte diff |
| R-MAP | R6.10 | AC-OVERLAY-01 | CHK-OVERLAY-01 | fast/focused/full | VRAM-derived oracle | observational-access trace |
| R-MAP | R6.11 | AC-OVERLAY-01, AC-OW-03 | CHK-OVERLAY-01 | focused/full | destination/clipping variant | destination matrix |
| R-MAP | R6.12 | AC-REMOVE-02, AC-OVERLAY-01 | CHK-REMOVE-01, CHK-OVERLAY-01 | fast/full | imported static palette-map mode | source/ROM negative evidence |
| R-MAP | R7.1 | AC-OW-02, AC-COMMIT-01 | CHK-TRANSFER-01, CHK-COMMIT-01 | focused/full | unpaired tile write | paired byte and writer trace |
| R-MAP | R7.2 | AC-REMOVE-02, AC-OW-03 | CHK-REMOVE-01 | fast/full | gameplay repair hook | reachability audit |
| R-MAP | R7.3 | AC-COMMIT-01, AC-OW-06 | CHK-COMMIT-01 | focused/full | visible mixed unit | old/new frames and snapshots |
| R-MAP | R7.4 | AC-COMMIT-01, AC-TIME-01 | CHK-COMMIT-01, CHK-TIME-01 | focused/full | over-budget indivisible unit | whole-unit defer trace |
| R-MAP | R8.1 | AC-OW-01 | CHK-TILESET-01 | full | absent tileset content | 25-tileset atlas |
| R-MAP | R8.2 | AC-OW-01 | CHK-TILESET-01 | full | donor content treated as authoritative | independent Yellow authorship and validation audit |
| R-MAP | R8.3 | AC-OW-01 | CHK-TILESET-01 | full | reused Safari data | Beach House evidence |
| R-MAP | R8.4 | AC-OW-01, AC-TECH-01 | CHK-TILESET-01, CHK-BUILD-01 | fast/full | wrong table length | build assertion |
| R-MAP | R8.5 | AC-OW-04 | CHK-TILESET-01 | full | roof/override mismatch | documented semantic cases |
| R-MAP | R8.6 | AC-OW-04 | CHK-TILESET-01, CHK-VISUAL-01 | full | incompatible animation indices | animation snapshots/frame strips |
| R-MAP | R9.1 | AC-OAM-01, AC-OW-05 | CHK-OAM-01, CHK-OAM-02 | fast/focused | map before final identity | final-identity trace |
| R-MAP | R9.2 | AC-OAM-01, AC-OW-05 | CHK-OAM-01, CHK-OAM-02 | fast/focused | control-bit clobber | before/after attributes |
| R-MAP | R9.3 | AC-OAM-01 | CHK-OAM-01 | fast/focused | unknown identity | palette-0 result |
| R-MAP | R9.4 | AC-OAM-01, AC-TECH-10 | CHK-OAM-01 | fast/focused | missing diagnostic fallback record | debug artifact |
| R-MAP | R9.5 | AC-OW-05 | CHK-OAM-02 | focused/full | Pikachu offset loss | final tile/OAM snapshot |
| R-MAP | R9.6 | AC-OW-05 | CHK-OAM-02 | focused/full | omitted object class | object coverage report |
| R-MAP | R9.7 | AC-TIME-01, AC-OW-06 | CHK-TIME-01, CHK-OAM-02 | focused/full | maximum OAM budget/wobble | timing row and frame strip |
| R-MAP | R9.8 | AC-COMMIT-01, AC-OW-05 | CHK-OAM-02, CHK-COMMIT-01 | focused/full | partial shadow/DMA image | shadow/hardware snapshots and DMA trace |
| R-MAP | R9.9 | AC-OW-05 | CHK-OAM-02 | focused/full | non-final palette identity | mapping trace |
| R-MAP | R10.1 | AC-TECH-07, AC-TIME-01 | CHK-BANK-01, CHK-TIME-01 | focused/full | override-handler interference | interrupt trace and timing row |
| R-MAP | R10.2 | AC-OWN-01, AC-TECH-06 | CHK-OWN-01 | fast/full | wrong-owner VBlank route | owner/generation writer trace |
| R-MAP | R10.3 | AC-TIME-01, AC-G0-01 | CHK-TIME-01, CHK-G0-01 | focused/full | late instrumentation | diagnostic-slice timing artifacts |
| R-MAP | R10.4 | AC-TIME-01, AC-COMMIT-01 | CHK-TIME-01, CHK-COMMIT-01 | focused/full | unchecked upload threshold | timing and defer trace |
| R-MAP | R10.5 | AC-TIME-01, AC-OW-02 | CHK-TIME-01, CHK-TRANSFER-01 | focused/full | transfer/palette overlap | serialization trace and timing rows |
| R-MAP | R10.6 | AC-TECH-07 | CHK-BANK-01 | fast/full | scheduled-work bank leak | boundary snapshots |
| R-MAP | R10.7 | AC-TIME-01 | CHK-TIME-01 | focused/full | accepted donor constant | Yellow measurement record |
| R-MAP | R10.8 | AC-TIME-01, AC-TECH-08 | CHK-TIME-01 | focused/full | incomplete timing row | complete numeric row |
| R-MAP | R10.9 | AC-TIME-01, AC-TECH-08 | CHK-TIME-01 | focused/full | nonpositive timing margin | equation result |
| R-MAP | R10.10 | AC-TIME-01, AC-COMMIT-01 | CHK-TIME-01, CHK-COMMIT-01 | focused/full | threshold plus one | whole-unit defer evidence |
| R-MAP | R11.1 | AC-TECH-10 | CHK-CANARY-01 | fast/focused | indistinct canary assignments | semantic and visual artifacts |
| R-MAP | R11.2 | AC-TECH-01 | CHK-CANARY-01, CHK-BUILD-01 | fast/full | canary in release | source/symbol audit |
| R-MAP | R11.3 | AC-TECH-10 | CHK-VISUAL-01 | focused/full | missing named visual | manifest and image artifacts |
| R-MAP | R11.4 | AC-TECH-10 | CHK-VISUAL-01 | focused/full | unpaired visual | linked snapshot and trace |
| R-MAP | R11.5 | AC-TECH-10 | CHK-VISUAL-01 | focused/full | visual-only verdict | machine assertion and review |
| R-MAP | R11.6 | AC-G0-01 | CHK-G0-01 | fast/full | renderer starts before Gate 0 | phase/build audit |
| R-MAP | R12.1 | AC-HO-02, AC-REMOVE-04 | CHK-REGRESS-01 | focused/full | changed Yellow lifecycle | baseline comparisons |
| R-MAP | R12.2 | AC-HO-01 | CHK-HANDOFF-01 | focused/full | standalone display before Yellow | first-writer trace |
| R-MAP | R12.3 | AC-REMOVE-02, AC-REMOVE-04 | CHK-REMOVE-01, CHK-REGRESS-01 | fast/full | imported excluded runtime | source/ROM audit |
| R-MAP | R12.4 | AC-REMOVE-01 | CHK-REMOVE-01 | full | reachable old overworld owner | reachability report |
| R-MAP | R12.5 | AC-REMOVE-04, AC-HO-02 | CHK-REGRESS-01 | focused/full | removed required Yellow code | excluded-scene regressions |
| R-MAP | R12.6 | AC-INV-01, AC-TECH-03 | CHK-INV-01 | fast/full | unreviewed writer in CI | audit log and mutation |
| R-MAP | R12.7 | AC-REMOVE-01 | CHK-REMOVE-01 | full | dual selectable overworld modes | source/ROM negative evidence |
| R-MAP | R12.8 | AC-INV-01 | CHK-INV-01, CHK-HANDOFF-01 | fast/full | scene touched without row | closed scene inventory |

## Acceptance-to-evidence traceability

Each row has one primary acceptance outcome. Representative fast-tier samples
never satisfy a full-tier completion row.

| Map kind | Acceptance | Requirement | Check | Tier | Mutation | Evidence |
|---|---|---|---|---|---|---|
| AC-MAP | AC-OWN-01 | R1.1, R1.2, R1.3, R1.4, R1.5, R10.2 | CHK-OWN-01 | fast/full | hostile owner/phase/generation writer | snapshots, trace, reduced seed |
| AC-MAP | AC-REQUEST-01 | R1.8, R1.9, R1.10, R1.11, R1.12, R1.13, R1.14, R1.15, R1.16, R1.18, R1.26, R1.28 | CHK-REQUEST-01 | fast/full | selected per-class pressure plus model-only unselected branches | result/work-accounting and fallback trace |
| AC-MAP | AC-JOB-01 | R1.6, R1.19, R1.20, R1.24, R1.27, R2.1, R2.2, R2.3, R2.8, R2.9 | CHK-JOB-01 | fast/full | handoff/reset/adversarial cancellation | cancellation/no-later-write trace |
| AC-MAP | AC-COMMIT-01 | R1.17, R1.21, R1.22, R1.23, R1.25, R1.28, R7.3, R7.4, R10.4, R10.10 | CHK-COMMIT-01 | focused/full | every pre-visible budget boundary and reserved commit | old/new frames, defer traces, and reservation record |
| AC-MAP | AC-RETURN-01 | R2.7, R2.10, R2.11, R2.12, R2.13 | CHK-RETURN-01 | focused/full | poisoned actual Yellow-to-overworld edge | inventory IDs, ledger, barrier, five frames |
| AC-MAP | AC-OVERLAY-01 | R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11 | CHK-OVERLAY-01 | fast/focused/full | clipping and precedence matrix | independent oracle byte diffs |
| AC-MAP | AC-OAM-01 | R9.1, R9.2, R9.3, R9.4 | CHK-OAM-01 | fast/focused | invalid picture identities | palette-0/debug/control-bit evidence |
| AC-MAP | AC-TIME-01 | R9.7, R10.3, R10.4, R10.7, R10.8, R10.9, R10.10 | CHK-TIME-01 | focused/full | numeric margin and threshold plus one | completed rows and defer trace |
| AC-MAP | AC-INV-01 | R1.7, R12.6, R12.8 | CHK-INV-01 | fast/full | unlisted reachable item | source/ROM reconciliation |
| AC-MAP | AC-TRACE-01 | R11.4, R12.6 | CHK-TRACE-01 | fast | unknown/uncovered/duplicate ID | validator and mapping report |
| AC-MAP | AC-G0-01 | R1.26, R3.3, R10.3, R11.6 | CHK-G0-01 | fast/full | named gate mutations | repeat logs and manifests |
| AC-MAP | AC-OW-01 | R5.1, R6.1, R6.2, R6.3, R8.1, R8.2, R8.3, R8.4 | CHK-TILESET-01, CHK-PALETTE-01 | full | all tileset content | semantic/visual atlas and audits |
| AC-MAP | AC-OW-02 | R2.5, R7.1, R7.3, R10.5 | CHK-TRANSFER-01, CHK-COMMIT-01 | focused/full | load/scroll/connection paths | paired bytes, traces, frame strips |
| AC-MAP | AC-OW-03 | R6.3, R6.4, R6.8, R6.11, R7.1 | CHK-OVERLAY-01, CHK-TRANSFER-01 | focused/full | dialogue and transient overlays | oracle and paired-transfer evidence |
| AC-MAP | AC-OW-04 | R6.9, R7.1, R8.5, R8.6 | CHK-TILESET-01, CHK-TRANSFER-01 | full | overrides/animation/replacement | semantic atlas and frame strips |
| AC-MAP | AC-OW-05 | R5.2, R9.1, R9.2, R9.5, R9.6, R9.8, R9.9 | CHK-OAM-02 | focused/full | every object class and DMA | OAM snapshots and mapping/DMA trace |
| AC-MAP | AC-OW-06 | R5.3, R5.4, R5.5, R7.3, R9.7 | CHK-VISUAL-01, CHK-COMMIT-01, CHK-TIME-01 | focused/full | stale/mixed/flickering frame | frame strips, snapshots, timing rows |
| AC-MAP | AC-HO-01 | R2.4, R2.6, R12.2 | CHK-HANDOFF-01 | focused/full | destination initialization before Yellow | owner/initialization-entry trace |
| AC-MAP | AC-HO-02 | R12.1, R12.5 | CHK-REGRESS-01 | focused/full | excluded lifecycle regression | baseline comparisons |
| AC-MAP | AC-HO-03 | R2.7, R2.10, R2.11, R2.12, R2.13 | CHK-HANDOFF-01, CHK-RETURN-01 | focused/full | each actual Yellow-to-overworld edge | concrete directed boundaries and reconstruction evidence |
| AC-MAP | AC-HO-04 | R1.6, R1.25, R2.1, R2.2, R2.3, R2.8, R2.9 | CHK-HANDOFF-01, CHK-JOB-01 | focused/full | repeated/nested/reset/interrupted | transition and cancellation traces |
| AC-MAP | AC-TECH-01 | R4.1, R4.2, R4.3, R4.4, R8.4, R11.2 | CHK-BUILD-01, CHK-ROM-01 | fast/full | variant build and warning failure | ROM IDs, headers, maps, logs |
| AC-MAP | AC-TECH-02 | R3.1, R3.2, R3.4 | CHK-CGB-01 | fast/full | platform/startup/reset | header and startup checkpoints |
| AC-MAP | AC-TECH-03 | R1.7, R12.6 | CHK-INV-01 | fast/full | reachable unreviewed writer | inventory closure report |
| AC-MAP | AC-TECH-04 | R1.3, R1.4, R5.6, R12.6 | CHK-OWN-01, CHK-INV-01 | fast/full | targeted writer mutations | assertion and audit results |
| AC-MAP | AC-TECH-05 | R1.23, R2.11, R5.1, R5.2, R5.3, R5.4 | CHK-COMMIT-01, CHK-PALETTE-01 | fast/full | semantic checkpoint mutation | exact state diff |
| AC-MAP | AC-TECH-06 | R1.2, R1.5, R1.19, R1.20, R2.9, R10.2 | CHK-OWN-01, CHK-JOB-01, CHK-REQUEST-01 | fast/full | seeded ownership actions | model/ROM state comparison |
| AC-MAP | AC-TECH-07 | R3.3, R3.5, R3.6, R4.5, R10.1, R10.6 | CHK-BANK-01, CHK-ROM-01 | fast/focused/full | bank and interrupt torture | boundary snapshots |
| AC-MAP | AC-TECH-08 | R5.8, R9.7, R10.4, R10.5, R10.8, R10.9, R10.10 | CHK-TIME-01 | focused/full | all timed operations | numeric rows and defer evidence |
| AC-MAP | AC-TECH-09 | R11.6, R12.6 | CHK-G0-01 | fast/full | each critical gate mutation | targeted failure artifacts |
| AC-MAP | AC-TECH-10 | R9.4, R11.1, R11.3, R11.4, R11.5 | CHK-VISUAL-01, CHK-CANARY-01, CHK-OAM-01 | focused/full | checkpoint artifact omissions | complete versioned manifests |
| AC-MAP | AC-STRESS-01 | R1.15, R1.16, R1.21, R1.22, R1.26, R7.3, R9.7, R10.8, R10.9, R10.10 | CHK-STRESS-01 | focused/full | combined renderer pressure | accounting, traces, timing, visuals |
| AC-MAP | AC-STRESS-02 | R2.7, R2.10, R2.11, R2.12, R2.13 | CHK-STRESS-02 | focused/full | handoff after map activity | poison/rebuild/barrier/five-frame evidence |
| AC-MAP | AC-STRESS-03 | R2.2, R7.1, R7.3, R7.4, R10.4, R10.10 | CHK-STRESS-03 | focused/full | interrupted connection | atomic snapshots, defer, timing |
| AC-MAP | AC-REMOVE-01 | R12.4, R12.7 | CHK-REMOVE-01 | full | old/selectable overworld ownership | negative source/ROM reachability |
| AC-MAP | AC-REMOVE-02 | R2.13, R6.12, R7.2, R12.3 | CHK-REMOVE-01 | full | captured-screen/restoration path | negative source/ROM reachability |
| AC-MAP | AC-REMOVE-03 | R12.4, R12.5 | CHK-REMOVE-01, CHK-REGRESS-01 | full | unjustified transitional adapter | disposition and regression report |
| AC-MAP | AC-REMOVE-04 | R12.1, R12.3, R12.5 | CHK-REGRESS-01 | focused/full | removed required Yellow path | excluded-scene regressions |
| AC-MAP | AC-DONE-01 | R1.1, R2.7, R7.1, R11.6, R12.1, R12.4, R12.6 | CHK-TRACE-01, CHK-G0-01, CHK-HANDOFF-01, CHK-TRANSFER-01, CHK-REMOVE-01, CHK-REGRESS-01 | full | incomplete aggregate completion | all mapped reports and artifacts green |

## Numeric timing operation matrix

Future execution creates one complete numeric row for every row below. Each
records operation, mode, ROM, tool/device, samples, worst cycles,
instrumentation cycles, start, deadline, guard, margin cycles, margin percent,
exact defer threshold, equation result, insufficient-budget injection at every
pre-visible preparation/revalidation boundary, and the threshold-plus-one
whole-unit defer artifact. For a visible destination it also records
worst-case reservation and uninterrupted completion after `COMMITTING`.
Arbitrary mid-operation interruption appears only for inactive destinations or
LCD-off cases. Repeated measurements retain phase and ROM identity.

| Timing row key | Operation and mode | Contract | Check | Required boundary evidence |
|---|---|---|---|---|
| TIME-LCD-OVERRIDE-OFF | LCD interrupt, scanline overrides disabled | R10.1, R10.8, R10.9, R10.10 | CHK-TIME-01 | numeric row and threshold-plus-one defer |
| TIME-LCD-OVERRIDE-ON | LCD interrupt, scanline overrides enabled | R10.1, R10.8, R10.9, R10.10 | CHK-TIME-01 | numeric row and threshold-plus-one defer |
| TIME-VBLANK-YELLOW | VBlank under `RENDERER_YELLOW` | R10.2, R10.8, R10.9, R10.10 | CHK-TIME-01 | route trace, numeric row, and threshold-plus-one defer |
| TIME-VBLANK-OVERWORLD | VBlank under `RENDERER_FULL_COLOR_OVERWORLD` | R10.2, R10.8, R10.9, R10.10 | CHK-TIME-01 | route trace, numeric row, and threshold-plus-one defer |
| TIME-PALETTE-BG | complete BG palette upload | R5.8, R10.4, R10.8, R10.9, R10.10 | CHK-TIME-01 | 64-byte old/new payload and whole-unit defer |
| TIME-PALETTE-OBJ | complete OBJ palette upload | R5.8, R10.4, R10.8, R10.9, R10.10 | CHK-TIME-01 | 64-byte old/new payload and whole-unit defer |
| TIME-PALETTE-COMBINED | serialized BG and OBJ palette uploads | R5.8, R10.4, R10.5, R10.8, R10.9, R10.10 | CHK-TIME-01 | payload ordering and whole-unit defer |
| TIME-STREAM-HORIZONTAL | paired horizontal row/column transfer | R7.1, R7.3, R7.4, R10.4, R10.5, R10.8, R10.9, R10.10 | CHK-TIME-01 | concrete mutation ID, old/new pairs, defer |
| TIME-STREAM-VERTICAL | paired vertical row/column transfer | R7.1, R7.3, R7.4, R10.4, R10.5, R10.8, R10.9, R10.10 | CHK-TIME-01 | concrete mutation ID, old/new pairs, defer |
| TIME-STREAM-CONNECTION | paired connected-map transfer in each direction | R7.1, R7.3, R7.4, R10.4, R10.5, R10.8, R10.9, R10.10 | CHK-TIME-01, CHK-STRESS-03 | concrete mutation IDs, direction, old/new pairs, defer |
| TIME-TRANSFER-THIRD-SCREEN | paired third-screen transfer | R7.1, R7.3, R7.4, R10.4, R10.8, R10.9, R10.10 | CHK-TIME-01 | concrete mutation ID, old/new pairs, defer |
| TIME-RECONSTRUCTION | full map reconstruction and presentation barrier | R2.11, R2.12, R10.8, R10.9, R10.10 | CHK-TIME-01, CHK-RETURN-01 | item ledger, barrier, numeric row, defer |
| TIME-OAM-MAXIMUM | maximum visible-object shadow build and hardware DMA | R9.7, R9.8, R10.8, R10.9, R10.10 | CHK-TIME-01, CHK-OAM-02 | concrete writer/mutation IDs, DMA image, defer |

## Directed scene and reconstruction matrix

Phase 0 expands this matrix to one evidence row for every concrete baseline
`STANDALONE` lifecycle and directed transition. Later phases add concrete rows
atomically with new edges and rerun source plus built-ROM closure before
reachability. A lifecycle row is never expanded into assumed map entry and
return edges. Grouping aliases is forbidden unless the reviewed inventory
proves identical control flow and names every alias. A representative
fast-tier sample cannot close a full-tier row.

| Directed coverage | Required concrete inventory join | Destination evidence | Reconstruction evidence | Check |
|---|---|---|---|---|
| hard boot, reset, new-game, and continue into Yellow lifecycles | one `STANDALONE` row plus each concrete Yellow-owned edge | Yellow selected before destination initialization | none unless a later concrete Yellow-to-overworld edge is traversed | CHK-HANDOFF-01, CHK-REGRESS-01 |
| battle, menus, status, Pokédex, town map, trainer card, naming, PC, evolution, Hall of Fame, trade, slots, printer, link, Pikachu pictures, Beach, and Surfing Pikachu lifecycles | one `STANDALONE` row per reachable lifecycle | Yellow remains selected through initialization and display | no implied map entry or return | CHK-HANDOFF-01, CHK-REGRESS-01 |
| Yellow-to-Yellow nesting, return, failure, disconnect, and error recovery | one concrete directed Yellow-owned `SC-…` row per edge | Yellow remains selected; no generation handoff | none | CHK-HANDOFF-01, CHK-REGRESS-01 |
| each source-and-ROM-proven map-to-Yellow edge | one concrete directional `SCENE_BOUNDARY` row | Yellow selected before destination initialization entry | poison may be installed for a later return fixture, but no reconstruction occurs on departure | CHK-HANDOFF-01 |
| each source-and-ROM-proven Yellow-to-full-color overworld edge | one concrete directional `SCENE_BOUNDARY` row joined to its actual source lifecycle | full-color selected before reconstruction | poison, every reconstruction item, barrier, five active frames | CHK-HANDOFF-01, CHK-RETURN-01 |
| every additional lifecycle or directed edge added after Phase 0 | one atomically added, reviewed concrete row plus renewed source/ROM closure | evidence follows the actual owner transition | reconstruction only for an actual Yellow-to-overworld edge | CHK-INV-01, CHK-HANDOFF-01, CHK-RETURN-01 |

Every actual Yellow-to-overworld row records its actual Yellow-owned source
lifecycle and poisons prior bank-0 tilemaps, bank-1 attributes, BG and OBJ
palette RAM, shadow and hardware OAM, buffers, flags, and jobs while Yellow
owns that lifecycle. Evidence records a preceding map-to-Yellow edge and its
last map generation only when source plus built-ROM evidence proves that
predecessor; initial new-game, continue, reset, and other Yellow-owned entry
lifecycles never invent a departure. Evidence then records
map/tileset/override identity; viewport, scroll, window, and destination;
required tiles, animation, and replacements; every presentable bank-0 tilemap
and freshly generated bank-1 attribute; base, transformed, and hardware
palettes; player, follower, and object shadow OAM; current-generation
scheduler state; restored banks, stack, and interrupts; the single
presentation barrier; and five consecutive `OVERWORLD_ACTIVE` frames.

## Overlay precedence matrix

Expected values are derived only from the request's authoritative destination
BG/window selector, map identity, tileset identity, rectangle,
world-coordinate origin/transform, complete override set, classification,
desired tile ID, and explicit attribute or text/window default. The harness
clips the selected destination while retaining source-to-destination tilemap
and source-to-world mappings. Revealed terrain uses the supplied
world-coordinate override or supplied tileset lookup. Reading either VRAM bank
or ambient active-map state to derive classification, coordinate, tile
identity, or an expected attribute fails `CHK-OVERLAY-01`.

| Case key | Destination/clipping | Classification and source | Meaningful byte coverage | Required evidence |
|---|---|---|---|---|
| OVERLAY-ORDINARY-OPAQUE-EXPLICIT | ordinary/unclipped | `OPAQUE_OVERLAY`, explicit full byte | palette 0–2, bank 3, flips 5–6, priority 7, bit 4 forced zero | request, coordinate map, expected/actual bytes |
| OVERLAY-ORDINARY-OPAQUE-DEFAULT | ordinary/unclipped | `OPAQUE_OVERLAY`, text/window default | default full byte and bit 4 forced zero | request, default key, expected/actual bytes |
| OVERLAY-ORDINARY-REVEALED-LOOKUP | ordinary/unclipped | `REVEALED_TERRAIN`, desired tile lookup | palette 0–2, bank 3, flips 5–6, priority 7, bit 4 forced zero | tile ID, lookup entry, expected/actual bytes |
| OVERLAY-ORDINARY-REVEALED-OVERRIDE | ordinary/unclipped | `REVEALED_TERRAIN`, coordinate override | override precedence and bit 4 forced zero | source/destination coordinate, override, bytes |
| OVERLAY-FULLY-CLIPPED | empty after clipping | mixed request classifications | no surviving commit cell | clipped coordinate map and zero-writer trace |
| OVERLAY-PARTIALLY-CLIPPED | clipped on each destination edge | alternating opaque/revealed source cells | preserved source/destination/world mappings and every meaningful bit | pre/post clip tilemap/world map and byte diffs |
| OVERLAY-MAP-EDGE | map edge | mixed explicit/default/lookup/override cells | every meaningful bit and canonical bit 4 | concrete mutation/writer IDs and byte diffs |
| OVERLAY-CONNECTION | connection destination | mixed explicit/default/lookup/override cells | every meaningful bit and canonical bit 4 | concrete mutation/writer IDs and byte diffs |
| OVERLAY-WINDOW | window destination | opaque and revealed cells | text/window default and terrain precedence | concrete mutation/writer IDs and byte diffs |
| OVERLAY-ALTERNATE-BG | alternate BG destination | opaque and revealed cells | destination pairing and every meaningful bit | concrete mutation/writer IDs and byte diffs |
| OVERLAY-ALTERNATE-MAP | request-supplied alternate map identity | opaque and revealed cells | supplied destination selector, map/tileset identity, world transform, overrides, and lookup independent of ambient map | complete request, concrete mutation/writer IDs, coordinate maps, and byte diffs |

## OAM fallback and lifecycle matrix

Palette mapping runs after final tile and Pikachu-offset selection and may
replace bits 0–2 only. Every case preserves bits 3–7. Diagnostic fallback
evidence is mandatory for invalid identities; release builds exclude
debug-only recording without changing the deterministic palette-0 result.

| Case key | Final picture identity | Expected palette | Required diagnostic evidence | Check |
|---|---|---|---|---|
| OAM-FALLBACK-MISSING | absent identity | OBJ palette 0 | fallback kind, object, final tile, generation, writer ID | CHK-OAM-01 |
| OAM-FALLBACK-RANGE | out-of-range identity | OBJ palette 0 | fallback kind, numeric identity, object, generation, writer ID | CHK-OAM-01 |
| OAM-FALLBACK-UNMAPPED | in-range unmapped identity | OBJ palette 0 | fallback kind, numeric identity, object, generation, writer ID | CHK-OAM-01 |
| OAM-MAPPED-OBJECTS | every mapped final identity | deliberate mapped OBJ palette | mapping key and concrete shadow/hardware writer IDs | CHK-OAM-02 |
| OAM-DMA-COMPLETE | maximum declared shadow batch | mapped and fallback results retained | shadow batch ID, DMA source/launch/wait IDs, complete hardware image | CHK-OAM-02, CHK-COMMIT-01 |

## Inventory-keyed implementation matrices

Phase 0 supplies concrete baseline rows before renderer expansion. Each later
phase may add a concrete row atomically with its new symbol or edge and must
rerun source plus built-ROM closure before reachability. Each full-tier matrix
is generated by joining the baseline and atomically extended inventories,
never by substituting a representative category:

- every concrete `MU-…` row for load, reload, return, reconstruction,
  horizontal and vertical scrolling, four connection directions,
  third-screen, row, column, rectangle, overlay, alternate destination,
  animation, field replacement, moving BG, LCD-off load, palette dependency,
  and OAM participation is exercised by `CHK-TRANSFER-01`,
  `CHK-COMMIT-01`, or `CHK-OAM-02` as its declared resources require;
- every concrete `WR-…` row reached by those mutations is asserted against its
  owner, phase, generation, destination, commit unit, and bank permissions by
  `CHK-OWN-01`, `CHK-BANK-01`, and `CHK-INV-01`; and
- every concrete `SC-…` lifecycle and directed transition row is exercised on
  boot, normal, abnormal, Yellow-to-Yellow nested/error, reset, and failure
  exits by `CHK-HANDOFF-01` and `CHK-REGRESS-01`; `CHK-RETURN-01` joins only
  actual Yellow-to-full-color overworld boundary rows.

The full content matrix covers first entry, each actual Yellow-to-overworld return, both scroll
axes, same-tileset and different-tileset warps, dialogue, start-menu overlay,
tile reload, and animation for each of the 25 tilesets. It additionally covers
every Fly destination; four connection directions; town roofs and the Route
6/Saffron boundary; Celadon Mart overrides; Vermilion Dock/SS Anne; caves and
dungeon warps; Pokémon Center healing; cut and boulder; fishing and ledge
shadow; Beach House; and follower Pikachu hide, show, move, and respawn.

The full OAM matrix covers player walking, running, biking, surfing, fishing,
and ledge states; follower Pikachu in every direction and animation state;
maximum visible NPC population; static NPCs and item balls; cut tree and
boulder movement; dust/smoke; healing machine; emotion bubbles; and objects
under grass/priority tiles. Evidence includes shadow OAM, hardware OAM, OBJ
palettes, and multi-frame images.

## Completion report

The final implementation PR reports all concrete mapped IDs and includes:

- reproducible release, debug, and VC builds plus CGB-only header evidence;
- closed hardware-writer, scene, and mutation inventories;
- bank-stress and ownership-model results;
- complete numeric timing rows and threshold-plus-one results;
- architecture stress results;
- all tileset/map, overlay, handoff, and OAM coverage;
- LLM-reviewed screenshots, frame strips, and contact sheets linked to
  semantic snapshots and traces;
- emulator and hardware/tool versions; and
- physical CGB tests not performed.
