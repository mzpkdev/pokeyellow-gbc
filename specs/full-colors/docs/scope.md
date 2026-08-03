# Scope and ownership boundary

This document defines the included production scenes. Mandatory owner,
handoff, reconstruction, and write behavior remains defined in
[requirements.md](requirements.md).

## Bounded production inclusion

Color production scope is only ordinary base-map presentation in Pallet Town
and Route 1 while the saved preference is `COLOR`. Within those intervals the
full-color owner includes:

- the two maps' CGB BG palettes and tile-ID-to-attribute data;
- initial map entry and reload, horizontal and vertical scrolling, and the
  Pallet Town/Route 1 connection;
- animated tiles and field replacements, with paired tile/attribute commits;
- player, follower Pikachu, NPC, and map-object OAM palette bits; and
- complete ownership handoffs to and from Yellow-owned contexts.

The saved preference is policy input only. It never grants write authority.
The effective owner is Color if and only if the preference is `COLOR`, the
lifecycle is ordinary map presentation, and the map is Pallet Town or Route 1.
Every other cell is Yellow-owned. Exactly one effective owner is selected at
every instant.

## Yellow-owned production scope

Yellow's existing renderer continues to own:

- every map, including Pallet Town and Route 1, under `YELLOW` preference;
- every unsupported map under either preference;
- boot, reset, soft reset, new-game, and continue presentation;
- dialogue, text boxes, and transient start, list, yes/no, field-move, and
  other menu or overlay presentation;
- battle backgrounds, HUD, Pokémon, trainers, transitions, and animations;
- title, splash, Oak speech, Yellow intro, and credits;
- party, status, Pokédex, town map, trainer card, naming, and PC screens;
- evolution, Hall of Fame, and trade presentation;
- slots, printer, and link-room presentation;
- Pikachu front-picture and emotion-picture screens;
- Pikachu's Beach and Surfing Pikachu; and
- any other standalone or unlisted lifecycle.

Follower Pikachu is included in Color only as an overworld object during an
eligible ordinary base-map interval. Its dialogue, emotion-picture, menu,
battle, and standalone presentation remains Yellow-owned.

## Classification and ownership rule

`ORDINARY_BASE_MAP` means the ordinary Pallet Town or Route 1 simulation and
viewport without dialogue, text, a menu, or any other overlay active.
`FORCED_YELLOW` means any overlay, dialogue, menu, battle, standalone,
boot/reset, unsupported-map, or `YELLOW`-preference lifecycle.
`SCENE_BOUNDARY` means a concrete directed edge on which the effective owner
changes. A real owner change completes the ordered handoff and destination
reconstruction contract before the arriving owner's first display write.

`OVERWORLD_OVERLAY` is reserved and unreachable in this bounded production
product. An overlay never preserves Color ownership and never enters the Color
pipeline: it causes a complete Color-to-Yellow handoff when departing an
eligible Color interval. A later return to eligible ordinary presentation may
cause a complete Yellow-to-Color handoff. Same-owner edges preserve generation
and do not invent a handoff, reconstruction, or map return.

Every unlisted lifecycle or directed transition must receive a reviewed
`SC-...` row in [replacement-inventory.md](replacement-inventory.md) before an
implementation phase makes it reachable, as required by
[R12.8](requirements.md#r12-isolation-and-removal).

Owner selection is defined by
[R1.1 and R1.29-R1.33](requirements.md#r1-renderer-ownership).
Transition and reconstruction behavior is defined by
[R2.1-R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction).

## Scene-lifecycle table

| Lifecycle or directed edge | Classification | Effective owner or transfer |
|---|---|---|
| ordinary Pallet Town or Route 1 presentation with `COLOR` preference | `ORDINARY_BASE_MAP` | Color |
| ordinary Pallet Town or Route 1 presentation with `YELLOW` preference | `FORCED_YELLOW` | Yellow |
| any unsupported map under either preference | `FORCED_YELLOW` | Yellow |
| dialogue, text, menu, or transient overlay on any map | `FORCED_YELLOW` | Yellow; `OVERWORLD_OVERLAY` is unreachable |
| battle or standalone presentation | `FORCED_YELLOW` | Yellow |
| boot, reset, soft reset, new-game, or continue presentation | `FORCED_YELLOW` | Yellow |
| Color-eligible base presentation to any forced-Yellow context | `SCENE_BOUNDARY` | complete Color-to-Yellow handoff |
| Yellow-owned context to eligible ordinary base presentation with `COLOR` preference | `SCENE_BOUNDARY` | complete Yellow-to-Color handoff |
| Pallet Town to Route 1 or Route 1 to Pallet Town while Color remains effective | `ORDINARY_BASE_MAP` | Color to Color; no handoff |
| any edge whose effective owner remains Yellow | `FORCED_YELLOW` | Yellow to Yellow; no handoff |

## Quarantined diagnostic and future material

The all-25-tileset palette/attribute corpus, overlay request oracle, precedence
and clipping matrices, and diagnostic `OVERWORLD_OVERLAY` model may remain as
authoring, synthetic-conformance, or audit evidence only. They are explicitly
non-production and non-gating for this bounded release. They cannot expand the
two-map allowlist, make a production Color overlay reachable, select an owner,
or authorize any production write.

Production completion does not require Color authoring for maps beyond Pallet
Town and Route 1 or Color rendering of dialogue, text, menus, or overlays.
Those are future product work and require a separately reviewed scope change.

## Compatibility

Backward compatibility is not a goal. The project may:

- become CGB-only;
- reject DMG/SGB execution;
- change ROM and renderer RAM layout;
- remove only obsolete competing overworld ownership or repair APIs;
- discard the failed full-color-overworld runtime implementation; and
- change save format if a later implementation has a concrete reviewed reason.

Required Yellow paths remain because `YELLOW` preference and every
forced-Yellow context depend on them. Non-Color behavior is protected by
baseline and handoff regression gates.

## Forbidden scope growth

Implementation work must not expand into:

- Color ownership of dialogue, text, menus, or overlays;
- recoloring battles or battle animations;
- species/trainer picture palettes;
- standalone menu redesign;
- title/intro/minigame renderer replacement;
- Color ownership outside ordinary Pallet Town and Route 1 presentation;
- treating the preference as write authority; or
- concurrent or overlapping ownership by the two renderers.

Yellow-owned tests are baseline, policy, handoff, return, and regression tests
only. Diagnostic and future authoring evidence cannot satisfy or enlarge the
bounded production acceptance gate.
