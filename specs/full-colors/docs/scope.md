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
- entering and returning from standalone screens.

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

## Map-backed versus standalone

An operation is map-backed when closing it should reveal the current map
without a full map entry. It remains under full-color ownership and must use
renderer-owned attributes.

An operation is standalone when it rebuilds the display and has its own screen
lifecycle. Ownership passes to Yellow before the screen initializes.

Returning from a standalone screen performs a complete map reconstruction.
Correctness cannot depend on map palettes or attributes surviving.

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
