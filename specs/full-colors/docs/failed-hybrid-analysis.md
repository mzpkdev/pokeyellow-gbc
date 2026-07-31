# Why the previous hybrid failed

The previous experiment kept Yellow's overworld palette renderer active and
added per-tile attributes around it.

Both systems touched the same map scene:

```text
Yellow overworld renderer ---------+
  whole-screen palettes            |
  canned/window attributes         +--> active map hardware state
  direct palette refreshes         |
                                    |
full-color overlay ----------------+
  per-tile map attributes
  scrolling attributes
  restoration hooks
```

Correctness depended on which system wrote last. This produced restoration
hooks after dialogue, menus, reloads, and transitions, followed by fixes for
streamed direction, serialization, connections, and stale window attributes.

## Corrected model

The revised architecture contains two renderers but only one active owner:

```text
map and map-backed overlays       standalone screens
FULL_COLOR_OVERWORLD       <----> YELLOW
```

This is not a hybrid because:

- Yellow cannot write palette or attribute hardware while the map owner is
  active;
- the full-color renderer cannot write while Yellow owns a standalone screen;
- handoff occurs before screen initialization;
- pending work from the prior owner is drained or cancelled; and
- returning to the map performs a complete rebuild.

## Lessons

1. Scope may be overworld-only while ownership remains complete within that
   scope.
2. Dialogue and transient menus belong to the map renderer if they reveal the
   existing map on close.
3. Standalone screens require a handoff, not a restoration patch.
4. Tile and attribute streaming are one operation.
5. Palette wrappers must dispatch by owner.
6. A feature toggle that allows both overworld renderers is forbidden.
7. Failed implementation code is not the foundation.

## Reusable artifacts

After independent review, it may be useful to reuse:

- verified tileset assignments;
- map and connection test scenarios;
- screenshot tooling;
- atlas coverage; and
- documented edge cases.

The runtime overlay and restoration architecture must not be reused.
