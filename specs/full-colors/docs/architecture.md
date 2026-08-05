# Overworld renderer architecture

This document is a conforming realization of the behavior and vocabulary in
[requirements.md](requirements.md). It does not select a binary ABI, queue
shape, capacity, descriptor layout, or WRAM address.

## Conformance and mechanism reference

The mechanism reference is `git@github.com:dannye/pokered-gbc.git` commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93`, consulted at
`color/{wram,vblank,super_palettes,loadpalettes,refreshmaps,sprites}.asm` and
the relevant `color/data/` and `color/tilesets/` files. Only palette
transforms, attribute lookup and transfer, scheduling, and OAM mechanisms are
candidates. Outside the accepted OVERWORLD palette and corrected attribute
slice, donor palettes, mappings, roofs, OAM assignments, content, and data
organization are non-authoritative candidate evidence; every Yellow-specific
value is independently authored and validated. The five payload authorities
(`color/data/map_palettes.asm`, `color/data/map_palette_sets.asm`,
`color/data/roofpalettes.asm`, `color/data/map_palette_constants.asm`, and
`color/tilesets/overworld.asm`) remain distinct from the ten mechanism paths
listed in the replacement inventory. pokered-gbc scene ownership,
static-screen restoration, MBC1 layout, banks, WRAM representation, and
non-overworld coloring are not part of this realization, as required by
[R4.1, R4.2, R4.3, R4.4, and R4.5](requirements.md#r4-rom-placement),
[R6.12](requirements.md#r6-attribute-and-overlay-model), and
[R12.1, R12.3, R12.4, R12.5, and R12.7](requirements.md#r12-isolation-and-removal).

## Ownership policy and phases

The saved preference is policy input, never write authority. The sole
authoritative decision is:

```text
effective_owner(preference, lifecycle, map) = RENDERER_FULL_COLOR_OVERWORLD
    iff preference == COLOR
    and lifecycle == ordinary map presentation
    and map is a city or route using the OVERWORLD tileset;
otherwise RENDERER_YELLOW.
```

The selected owner and phase are explicit state, not inferred from a routine
name. The legal owner/phase combinations are the table in
[requirements.md](requirements.md#stable-vocabulary), governed by
[R1.1, R1.2, R1.3, R1.4, R1.5, and R1.6](requirements.md#r1-renderer-ownership).
“Yellow” and “full-color”
below mean `RENDERER_YELLOW` and `RENDERER_FULL_COLOR_OVERWORLD`,
respectively.

```text
HARD BOOT / RESET / SOFT RESET
    |
    | Yellow selected; Yellow destination initialized
    v
YELLOW_ACTIVE <----> YELLOW-OWNED NESTED / ERROR LIFECYCLES
    |
    | effective owner changes for ordinary supported OVERWORLD maps only
    v
HANDOFF_TO_OVERWORLD
    |
    | full-color owner selected with a fresh generation
    v
OVERWORLD_RECONSTRUCTING
    |
    | one complete presentation barrier
    v
OVERWORLD_ACTIVE (ordinary supported OVERWORLD maps only)
    |
    | overlay/dialogue/menu/battle/standalone/unsupported map,
    | Yellow preference, reset, or soft reset
    v
HANDOFF_TO_YELLOW
    |
    | Yellow selected with fresh generation; destination resources unknown
    v
YELLOW_RECONSTRUCTING
    |
    | complete Yellow ledger; exactly one presentation barrier
    v
YELLOW_ACTIVE
```

There is no state in which both owners may write an owner-gated resource.
`OVERWORLD_OVERLAY` is reserved and unreachable in production. Overlays,
dialogue, menus, battles, standalone scenes, unsupported maps, boot/reset, and
the Yellow preference are forced Yellow. Same-owner decisions retain owner and
generation and perform no synthetic handoff. Scene classification remains
authoritative in [scope.md](scope.md), subject to this bounded policy.

## Transition and request algorithm

The resolver is recomputed before the destination's first owner-gated write.
An unchanged result retains owner and generation. A changed result executes
exactly one transition using this ordering to realize
[R2.1, R2.2, R2.3, R2.4, R2.6, R2.7, R2.8, and R2.9](requirements.md#r2-generation-handoff-reset-and-reconstruction):

1. Enter the applicable handoff phase and close admission for the departing
   owner.
2. Complete a commit unit that has become visible; otherwise cancel its job
   before visibility. Cancel remaining `PENDING` or `PREPARED` departing work
   with the applicable stable reason.
3. Establish a fresh, non-aliasing generation and invalidate all older work.
   No older job may write after this point.
4. Select the destination owner and reconstruct every destination authority
   from fresh logical state. Each direction treats bank-0 tiles/tilemaps,
   bank-1 attributes, palette sources/transforms/hardware, OAM, scroll/window,
   buffers, flags, animations, jobs, banks, stack, and interrupt state as
   unknown. Yellow is selected before forced-Yellow initialization; Color is
   selected before eligible-map reconstruction.
5. Cross exactly one presentation barrier, then reopen admission. Selecting
   either owner without complete reconstruction and its barrier is insufficient.

Reset and soft reset are real Color-to-Yellow boundaries, and soft reset still
re-enters normal boot after restoring machine state. They either keep the
display provably hidden and admission closed through cancellation, generation,
complete fresh Yellow reconstruction, and the barrier, or complete the
ordinary handoff before any reset-owned video write.

A request follows this exact realization of
[R1.8, R1.9, R1.10, R1.11, R1.12, R1.13, R1.14, R1.15, R1.16, R1.17, R1.18, R1.19, R1.20, R1.21, R1.22, R1.23, R1.24, R1.25, R1.27, and R1.28](requirements.md#r1-renderer-ownership):

1. Admission records desired state, declared owner and generation, all
   resources, the destination, and the visible commit unit. Owner is checked
   first and returns `REJECTED_WRONG_OWNER` on mismatch; generation is then
   checked and returns `REJECTED_STALE_GENERATION` on mismatch. Neither result
   creates or attaches work.
2. Equivalent tracked work returns `COALESCED`. Otherwise available capacity
   returns `ACCEPTED`; at capacity, non-equivalent work returns exactly the
   measured policy selected when its request class is implemented. Required
   visible-state work returns `DEFERRED` and its caller retries. `REJECTED_CAPACITY` is available
   only to an optional or supersedable class with a documented caller fallback.
3. Accepted work is prepared using scratch or an inactive destination only.
   `PENDING` and `PREPARED` jobs do not alter a presented resource.
4. At every pre-visible preparation or revalidation boundary, revalidate owner,
   generation, destination, and the operation's numeric time budget. A state
   validation failure cancels before visibility. A budget failure leaves the
   entire job `PREPARED` for a later attempt.
5. Before entering `COMMITTING` for a visible destination, reserve the measured
   worst-case completion budget. Once `COMMITTING` begins, finish the whole
   declared visible unit without arbitrary interruption and record `COMPLETE`
   only after every declared resource equals the desired state. Arbitrary
   interruption remains permissible only for an inactive destination or while
   the LCD is off.

Coalescing uses equality of final state and visible boundary, not descriptor
identity. Accepted or coalesced work remains accounted for until completion or
an explicit, traced cancellation; capacity pressure never silently drops it.
Runtime conformance exercises exactly the selected policy for each request
class. The schema and reference model additionally exercise unselected enum
branches so their contracts do not rot.

## Visible commit realization

Commit units are exactly those required by
[R2.11, R2.12, R5.8, R6.4, R7.1, R7.3, R9.2, and R9.8](requirements.md#visible-commit-units).
At the next presentation boundary, the viewer observes the complete old unit
or the complete new unit:

- map rectangles pair every bank-0 tile ID with its bank-1 full attribute;
- overlay changes pair every tile and attribute in the clipped changed
  rectangle;
- animation and field replacement include the declared tile-data dependency;
- a palette commit is one complete requested 64-byte BG or OBJ payload;
- overworld OAM completes its declared shadow batch before one DMA; and
- load, reload, and return remain hidden until complete reconstruction.

Preparation may occur with the LCD off or in an inactive destination. No job
may expose an internal prefix of a commit unit. A visible-destination job
defers before `COMMITTING` unless it has reserved its measured worst-case
completion budget; once it begins, it completes without arbitrary
interruption. Only an inactive-destination or LCD-off commit may be interrupted
mid-operation
([R7.1, R7.3, and R7.4](requirements.md#r7-paired-transfers-and-visible-commit-units)).

## Bounded Color overworld pipeline

```text
authoritative ordinary supported OVERWORLD map, tileset, override, viewport, and object state
        |
        +--> base BG/OBJ palettes --> transformed BG/OBJ payloads
        +--> desired tile IDs -----> 256-entry attribute lookup/overrides
        `--> final object identity -> shadow-OAM palette mapping
                                      |
                         current-generation jobs
                                      |
                     revalidate owner/destination/budget
                                      |
             whole-unit VRAM/palette/OAM presentation
```

Gameplay requests desired state; it does not directly schedule hardware writes.
Wrapper functions dispatch through the selected owner and generation
([R5.6, R5.7, and R5.8](requirements.md#r5-palette-model)).
Animated tiles and field replacements declare their tile-data dependency and
atomically commit the bank-0 tile result with its bank-1 attribute result.
Yellow's moving-BG writer is unreachable while Color owns.

## Semantic state lifetimes

Architecture fixes these semantic lifetimes. Storage and representation are
selected when the corresponding renderer state is first implemented:

| State | Lifetime and invalidation |
|---|---|
| base BG and OBJ palettes | current authoritative palette state; initialized on reconstruction |
| transformed BG and OBJ payloads | derived from base palettes and current shade remap; invalid when either changes |
| active tileset lookup and coordinate overrides | current map/tileset identity; replaced on map identity change |
| overlay preparation | one admitted request/current generation; discarded on cancellation |
| request and job bookkeeping | from admission through completion/cancellation; never executable across generation invalidation |
| owner, phase, and generation | ownership epoch; reset and handoff establish new state |
| reconstruction state | one overworld arrival; complete only at its presentation barrier |
| OAM mapping and prepared shadow batch | current object state/current generation; invalid on handoff, reset, or object-state change |

Phase 1 records measured byte cost, placement, and interrupt-access needs before
allocating the ownership foundation. Later phases record capacity, descriptor,
and scratch measurements when their request classes are implemented. Renderer
calls and interrupts preserve ROM bank, `rSVBK`, `rVBK`, stack, and interrupt
state at their boundaries under
[R3.3, R3.4, R3.5, and R3.6](requirements.md#r3-cgb-and-bank-foundation).

## Representation decision record

| Decision | Required measured evidence |
|---|---|
| capacity, pressure policy, and coalescing | measurements from the implemented request class plus generated high-water marks, required-work retry evidence, optional/supersedable fallback evidence where final rejection is selected, and schema/reference-model coverage of every result branch |
| descriptor semantics | every distinct resource and commit-unit shape, including cancellation and reconstruction |
| WRAM location and size | link-map ranges, byte and bank cost, interrupt access, and stack margin |
| preparation buffers | largest overlay, paired transfer, palette, OAM, and reconstruction preparation unit plus worst-case visible-commit reservation |

Each phase records numeric evidence before selecting the value it introduces.
The record distinguishes logical limits from encoded field widths. Gate 0 does
not preselect a ring, list, slot count, descriptor size, index width, scratch
layout, or WRAM bank. This is the required realization of
[R1.26](requirements.md#r1-renderer-ownership) and
[R3.3](requirements.md#r3-cgb-and-bank-foundation).

## ROM placement and bank composition

The donor locations conflict with Yellow: bank `$2c` contains Text 7, bank
`$31` contains Pikachu cries, and the `$1c` extension is not assumed free.
Yellow's empty bank `$3b` is only the measured starting candidate. All donor
MBC1 behavior is converted to Yellow's MBC5 `rROMB` and far-call conventions
([R4.1, R4.2, R4.3, R4.4, and R4.5](requirements.md#r4-rom-placement)).

Yellow already uses the LCD interrupt for per-scanline `wLYOverrides`.
Renderer preparation composes with that handler. Measured timing determines
the exact safe start and ordering; VBlank selects the current effective owner
once before its first visible writer, runs exactly one route, revalidates the
job at every pre-visible boundary, and enters
`COMMITTING` only after reserving the worst-case completion budget. Every exit
restores temporary bank state
([R10.1, R10.2, R10.3, R10.4, R10.5, R10.6, R10.7, R10.8, R10.9, R10.10, and R10.11](requirements.md#r10-scheduling-and-timing-evidence)).

## Tile and attribute transfers

A paired-transfer job semantically carries:

- tile and authoritative attribute sources;
- destination, dimensions, stride, and clipping;
- declared resources and visible commit unit; and
- owner and generation.

It produces one matching full-byte attribute for every committed tile. The
same realization serves initial load/reload, both scrolling axes, four
connections, third-screen, row and rectangle transfers, tile reload,
alternate BG destinations, animation and field replacements, dialogue/text,
and transient overlays. Each phase supplies closed mutation rows for the paths
it touches; later rows are added atomically and reclosed before reachability under
[replacement-inventory.md](replacement-inventory.md).

## Overlay oracle quarantine

The overlay oracle below remains diagnostic/audit conformance machinery only.
Production overlays, dialogue, and menus are Yellow-owned, never enter this
pipeline, and cannot make `OVERWORLD_OVERLAY` reachable.

An overlay request supplies the authoritative destination BG/window selector,
destination map identity, tileset identity, destination rectangle,
world-coordinate origin or transform, complete coordinate-override set,
`OPAQUE_OVERLAY` or `REVEALED_TERRAIN` classification for every source cell,
desired tile IDs, and optional explicit full-byte overlay attributes. The
implementation:

1. Clips the selected destination to its presentable bounds while retaining
   both the source-to-destination tilemap mapping and derived world coordinate
   for every survivor.
2. Reads classification only from that request data.
3. For an opaque cell, selects its explicit full-byte assignment or the
   defined text/window default.
4. For a revealed cell, selects the request-supplied override for its derived
   world coordinate or the request-supplied tileset identity's 256-entry
   lookup for the requested desired tile ID.
5. Emits palette bits 0–2, tile-bank bit 3, flip bits 5–6, and priority bit 7,
   with bit 4 canonicalized to zero, paired with the desired tile.

Neither VRAM bank nor ambient active-map identity is read as an oracle. The
same steps cover ordinary, fully clipped, partially clipped, window,
alternate-BG, alternate-map-identity, edge, and connection destinations; a
fully clipped result commits no cell. This realizes
[R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, and R6.12](requirements.md#r6-attribute-and-overlay-model) without importing
the donor's static palette-map lifecycle.

## Reconstruction realization

An arriving owner treats old tilemaps, attributes, palettes, OAM, buffers,
flags, and jobs as unknown. Under one fresh full-color generation it derives
from authoritative state and completes:

- map, tileset, and coordinate-override identity;
- viewport, scroll, window, and destination state;
- required tiles plus animation and field replacements;
- every presentable bank-0 tilemap and freshly generated bank-1 attribute;
- base, transformed, and hardware BG/OBJ palettes;
- player, follower, and object shadow OAM;
- current-generation request/scheduler state; and
- restored ROM/WRAM/VRAM banks, stack, and interrupt state.

Only after every item is complete does one presentation barrier expose the
result and advance to `OVERWORLD_ACTIVE`. A preparation failure remains hidden
in `OVERWORLD_RECONSTRUCTING`; captured VRAM, palette RAM, OAM, or screen
buffers are never inputs or completion evidence. This realizes
[R2.10, R2.11, R2.12, and R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction).
Color-to-Yellow is normatively symmetric: `YELLOW_RECONSTRUCTING` treats the
same complete resource set as unknown, rebuilds the same complete ledger from
fresh Yellow logical authority, and crosses exactly one barrier before
admission reopens or presentation begins. Captured renderer bytes satisfy
neither direction.

## Palette realization

Eight four-color RGB555 BG palettes and eight four-color RGB555 OBJ palettes
remain authoritative base data. `BGP`, `OBP0`, and `OBP1` changes derive
separate complete transformed payloads, preserving the base data and Yellow's
fade vocabulary. A current-generation job uploads a complete requested
payload only after commit revalidation
([R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, and R5.8](requirements.md#r5-palette-model)).

## OAM realization

Authoritative overworld OAM construction first completes Yellow's tile
selection, including `hPikachuSpriteVRAMOffset`, and resolves the final picture
identity. It then looks up the OBJ palette and replaces attribute bits 0–2
only, preserving bits 3–7. Missing, out-of-range, or unmapped identity selects
palette 0; diagnostic builds record the required fallback evidence.

The complete declared shadow-OAM batch is prepared under the effective owner
and generation before one declared shadow-to-hardware OAM DMA. A Yellow-named
allocation, clear, sort/copy, DMA-launch, or wait routine is a mechanism and
does not change effective ownership. Reset and handoff invalidate both
prepared shadow state and any permission to launch its DMA. These steps realize
[R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, and R9.9](requirements.md#r9-overworld-oam); concrete shadow-OAM,
hardware-OAM, and `rDMA` writers are closed by the inventory.
