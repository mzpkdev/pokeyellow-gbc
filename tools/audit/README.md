# Trainer data audit

Run the structural trainer-data checks from the repository root:

```sh
python tools/audit/trainers.py
```

To also emit a machine-readable manifest for reviews or balance reports:

```sh
python tools/audit/trainers.py --manifest trainer-manifest.json
```

The audit checks party sizes and levels, trainer class/party references in
`special_moves.asm`, party-slot and move-slot bounds, duplicate records, and
duplicate slot overrides. It also checks the authoritative trainer-class order,
class-indexed table lengths, direct map-object and script references, and the
known dynamic rival selector ranges. Literal script selectors may use decimal
or RGBDS hexadecimal notation (for example, Jessie and James use `$2a` through
`$2f`). It does not modify trainer data.

To reject inserted, deleted, or reordered trainer records, compare class order
and per-class party counts with a previously reviewed manifest:

```sh
python tools/audit/trainers.py --baseline trainer-manifest-baseline.json
```

The topology check deliberately allows party composition and levels to change.
Dynamic script selectors are listed as explicit contracts in `trainers.py`;
the audit verifies their implemented `wRivalStarter` load, offset, opponent
class, and `wTrainerNo` store. Update those contracts when selector arithmetic
changes.
