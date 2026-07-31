# Scope and ownership boundary

## Included

The replacement owns the complete map scene:

- eight CGB BG palettes;
- eight CGB OBJ palettes used by overworld objects;
- tile-ID-to-attribute data for every Yellow tileset;
- initial map load and full reload;
- horizontal and vertical scrolling;
- all four connected-map directions;
- animated and replaced map tiles;
- dialogue and text boxes over the map;
- transient start, list, yes/no, and field-move overlays;
- player, follower Pikachu, NPC, and map-object OAM palette bits; and
- actual ownership boundaries between the map and Yellow-owned screens.

## Excluded

Yellow's existing renderer continues to own:

- battle backgrounds, HUD, Pokémon, trainers, transitions, and animations;
- title, splash, Oak speech, Yellow intro, and credits;
- party, status, Pokédex, town map, trainer card, naming, and PC screens;
- evolution, Hall of Fame, and trade presentation;
- slots, printer, and link-room presentation;
- Pikachu front-picture and emotion-picture screens;
- Pikachu's Beach and Surfing Pikachu; and
- any other standalone screen that replaces the map.

Follower Pikachu is included because it is an overworld object.

## Classification rule

These labels apply only to rows in the scene-lifecycle table.
`MAP_BACKED` means dismissal resumes the same map simulation and viewport
without map entry; it remains full-color-owned even when opaque.
`STANDALONE` means an independent display lifecycle owned by Yellow.
`SCENE_BOUNDARY` means a concrete directed transition that transfers ownership
between a map lifecycle and a Yellow-owned lifecycle. Boot and reset entry,
Yellow-to-Yellow nesting, failure recovery, and other Yellow-to-Yellow edges
remain Yellow-owned and are not map boundaries. Yellow is selected before
entry to destination initialization on a full-color-to-Yellow boundary. No
scene may be “temporarily Yellow-owned while preserving the map.” A standalone
lifecycle does not imply a map entry or return edge; only source and built-ROM
reachability may establish those concrete directed edges. Every unlisted
lifecycle or directed transition must receive a reviewed `SC-…` row in
`replacement-inventory.md` before later implementation phases touch it, as
required by
[R12.8](requirements.md#r12-isolation-and-removal).

Owner behavior is defined by
[R1.1, R1.3, R1.4, R1.5, R1.6, and R1.7](requirements.md#r1-renderer-ownership).
Transition and reconstruction behavior is defined by
[R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.9, R2.10, R2.11, R2.12, and R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction).

## Scene-lifecycle table

| Lifecycle or directed edge | Classification | Owner or transfer |
|---|---|---|
| map entry, reload, scrolling, connections, animations, and field replacements | `MAP_BACKED` | full-color owner |
| dialogue and text boxes over the map | `MAP_BACKED` | full-color owner |
| transient start, list, yes/no, and field-move overlays | `MAP_BACKED` | full-color owner |
| battle presentation and animation lifecycle | `STANDALONE` | Yellow |
| title, splash, Oak speech, Yellow intro, and credits lifecycle | `STANDALONE` | Yellow |
| party, status, Pokédex, town map, trainer card, naming, and PC lifecycle | `STANDALONE` | Yellow |
| evolution, Hall of Fame, and trade presentation lifecycle | `STANDALONE` | Yellow |
| slots, printer, and link-room presentation lifecycle | `STANDALONE` | Yellow |
| Pikachu front-picture and emotion-picture lifecycle | `STANDALONE` | Yellow |
| Pikachu's Beach and Surfing Pikachu lifecycle | `STANDALONE` | Yellow |
| any other lifecycle that replaces the map | `STANDALONE` | Yellow |
| hard boot, soft reset, new-game, and continue entry into a Yellow lifecycle | `STANDALONE` | Yellow to Yellow; no map reconstruction |
| nested standalone entry/return and Yellow error or disconnect recovery | `STANDALONE` | Yellow to Yellow; no map reconstruction |
| each source-and-ROM-proven map-to-standalone edge | `SCENE_BOUNDARY` | full-color to Yellow before destination initialization |
| each source-and-ROM-proven standalone-to-map edge | `SCENE_BOUNDARY` | Yellow to full-color reconstruction |

## Compatibility

Backward compatibility is not a goal. The project may:

- become CGB-only;
- reject DMG/SGB execution;
- change ROM and renderer RAM layout;
- remove old overworld APIs;
- discard the failed full-color-overworld runtime implementation; and
- change save format if implementation has a concrete reason.

Non-overworld behavior remains protected because it is outside the replacement,
not because the old overworld renderer must remain compatible.

## Forbidden scope growth

Implementation work must not expand into:

- recoloring battles or battle animations;
- species/trainer picture palettes;
- standalone menu redesign;
- title/intro/minigame renderer replacement; or
- keeping two selectable overworld renderers.

Non-overworld tests are handoff and regression tests only.
