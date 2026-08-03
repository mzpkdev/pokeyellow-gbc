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

- hardware writes are owner-gated by
  [R1.1, R1.3, R1.4, R1.5, R1.6, and R1.7](requirements.md#r1-renderer-ownership);
- handoff ordering and job invalidation follow
  [R2.1, R2.2, R2.3, R2.4, R2.6, R2.7, R2.8, and R2.9](requirements.md#r2-generation-handoff-reset-and-reconstruction);
  and
- return reconstruction follows
  [R2.10, R2.11, R2.12, and R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction).

## Non-hybrid rule

At an actual Yellow-to-full-color overworld boundary, reconstruction may not
use bytes captured from the old map presentation: no 20×18 snapshot, partial
attribute backup, palette restoration, or gameplay repair hook. Off-screen
preparation is allowed only inside the current full-color generation when its
source is authoritative map state. `git@github.com:dannye/pokered-gbc.git` commit
`c1a3b6c5a7591472241036d0cf09c3817f841f93` supplies mechanism evidence plus
the separately frozen OVERWORLD palette and corrected attribute payload. Its
other palettes, mappings, roofs, OAM assignments, and content are
non-authoritative candidates that must be independently authored and validated
for Yellow, and its static palette-map mode is excluded.

The rejected restoration paths and permitted preparation boundary are governed
by [R1.5 and R1.17](requirements.md#r1-renderer-ownership),
[R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction),
[R6.12](requirements.md#r6-attribute-and-overlay-model),
[R7.2](requirements.md#r7-paired-transfers-and-visible-commit-units), and
[R12.3](requirements.md#r12-isolation-and-removal).

## Lessons

| Observed lesson | Contract |
|---|---|
| Overworld-only scope still needs exclusive ownership of every map resource. | [R1.1, R1.3, R1.4, R1.5, R1.6, and R1.7](requirements.md#r1-renderer-ownership) |
| Dialogue and transient overlays share the map lifecycle. | [R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, and R6.12](requirements.md#r6-attribute-and-overlay-model) |
| Actual map/Yellow ownership edges need generation-safe handoff, while only Yellow-to-full-color overworld edges reconstruct. | [R2.1, R2.2, R2.3, R2.4, R2.6, R2.7, R2.9, R2.10, R2.11, R2.12, and R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction) |
| Tile and attribute streaming share a visible commit boundary. | [R7.1, R7.2, R7.3, and R7.4](requirements.md#r7-paired-transfers-and-visible-commit-units) |
| Palette wrappers follow effective ownership. | [R5.6, R5.7, and R5.8](requirements.md#r5-palette-model) |
| Dual selectable overworld ownership recreates the race. | [R12.4, R12.5, R12.6, and R12.7](requirements.md#r12-isolation-and-removal) |
| Failed runtime code is evidence, not a foundation. | [R12.3](requirements.md#r12-isolation-and-removal) |

## Reusable artifacts

After independent review, it may be useful to reuse as non-authoritative
evidence:

- palette and tileset organization as artistic candidates, with Yellow values
  independently authored and validated;
- map and connection test scenarios;
- screenshot tooling;
- atlas coverage; and
- documented edge cases.

The runtime overlay and restoration architecture is excluded by
[R2.13](requirements.md#r2-generation-handoff-reset-and-reconstruction),
[R6.10](requirements.md#r6-attribute-and-overlay-model), and
[R7.2](requirements.md#r7-paired-transfers-and-visible-commit-units).
