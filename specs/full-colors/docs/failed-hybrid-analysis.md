# Why the hybrid overworld approach failed

The prior full-color-overworld experiment did not replace Yellow's renderer.
It retained Yellow's palette commands and canned attribute maps, then added
per-tile overworld attribute writes around them.

Its own design constraints demonstrate the conflict:

- it intentionally excluded battles and menus;
- it suppressed only selected original palette refreshes;
- it restored attributes after dialogue and menu operations;
- it added separate initial-map and streamed-row/column writers;
- it performed some attribute work by waiting for accessible VRAM outside a
  centralized renderer schedule; and
- later fixes had to address map connections, redraw direction, serialization,
  menu/dialogue restoration, and competing battle/window palettes.

## Root cause

Two active systems believed they owned the same hardware state:

```text
Yellow renderer --------------------+
  canned screen maps                |
  four palette commands             +--> VRAM bank 1 / palette RAM
  direct palette refreshes          |
                                     |
full-color overworld overlay -------+
  per-tile map attributes
  restoration hooks
  streamed edge updates
```

Correctness depended on which system wrote last. Adding another restoration
hook could repair one transition while exposing a different timing or map-edge
failure.

## Lessons carried into this specification

1. VRAM bank 1 must have one owner.
2. Palette RAM must have one owner.
3. Initial draw, scrolling, dialogue, and menus are not separate color
   features; they are consumers of one transfer layer.
4. A palette command must describe the complete target scene.
5. Restoration is legitimate only for restoring a deliberately saved scene,
   not for repairing damage from a competing renderer.
6. Timing waits scattered through gameplay code are not a renderer scheduler.
7. A feature toggle between two live renderers multiplies the transition state
   space and should not be part of the replacement.

## Reusable material

The failed runtime architecture should not be ported. Some artifacts may still
be useful after independent verification:

- per-tileset palette assignments;
- Yellow-specific map and connection tests;
- screenshot tooling;
- map atlas coverage;
- emulator setup; and
- documented edge cases discovered during the experiment.

Reusing a test does not imply reusing the implementation it was written for.
