#!/usr/bin/env python3
"""Validate trainer parties and their special-move overrides.

This intentionally parses only the small, regular subset of RGBDS syntax used by
data/trainers/{parties,special_moves}.asm.  It does not need a built ROM or RGBDS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


DB_RE = re.compile(r"^\s*db\s+(.+?)\s*$", re.IGNORECASE)
LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$")
POINTER_RE = re.compile(r"^\s*dw\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
TRAINER_CONST_RE = re.compile(r"^\s*trainer_const\s+([A-Za-z_][A-Za-z0-9_]*)")
OBJECT_REF_RE = re.compile(r"\bOPP_([A-Za-z0-9_]+)\s*,\s*(\d+)\s*$")
LOAD_OPP_RE = re.compile(r"^\s*ld\s+a,\s*OPP_([A-Za-z0-9_]+)\s*$", re.IGNORECASE)
LOAD_NUMBER_RE = re.compile(
    r"^\s*ld\s+a,\s*(\$[0-9a-f]+|\d+)\s*$", re.IGNORECASE
)
LOAD_RIVAL_STARTER_RE = re.compile(
    r"^\s*ld\s+a,\s*\[wRivalStarter\]\s*$", re.IGNORECASE
)
ADD_NUMBER_RE = re.compile(
    r"^\s*add\s+(\$[0-9a-f]+|\d+)\s*$", re.IGNORECASE
)
STORE_CUR_OPPONENT_RE = re.compile(
    r"^\s*ld\s+\[wCurOpponent\],\s*a\s*$", re.IGNORECASE
)
STORE_TRAINER_NUMBER_RE = re.compile(
    r"^\s*ld\s+\[wTrainerNo\],\s*a\s*$", re.IGNORECASE
)

# Dynamic selectors cannot be proven by merely looking for literal `ld a, N`
# instructions. These contracts document the intended result of their arithmetic
# and make party-count drift fail the audit.
DYNAMIC_SELECTOR_CONTRACTS = [
    ("scripts/PokemonTower2F.asm", "RIVAL2", range(2, 5), 1),
    ("scripts/SilphCo7F.asm", "RIVAL2", range(5, 8), 4),
    ("scripts/Route22.asm", "RIVAL2", range(8, 11), 7),
    ("scripts/ChampionsRoom.asm", "RIVAL3", range(1, 4), 0),
]


def clean(line: str) -> str:
    return line.split(";", 1)[0].strip()


def fields(line: str) -> list[str] | None:
    match = DB_RE.match(clean(line))
    if not match:
        return None
    return [part.strip() for part in match.group(1).split(",")]


def key(name: str) -> str:
    name = re.sub(r"Data$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def parse_asm_int(value: str) -> int:
    """Parse the decimal and RGBDS-style hexadecimal literals used by selectors."""
    if value.startswith("$"):
        return int(value[1:], 16)
    return int(value, 10)


def has_dynamic_rival_selector(text: str, class_name: str, offset: int) -> bool:
    """Verify the implemented wRivalStarter selector for a trainer class."""
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    for index, line in enumerate(lines):
        opponent = LOAD_OPP_RE.match(line)
        if not opponent or key(opponent.group(1)) != key(class_name):
            continue
        window = lines[index + 1:index + 8]
        for store_index, candidate in enumerate(window):
            if not STORE_CUR_OPPONENT_RE.match(candidate):
                continue
            selector = window[store_index + 1:]
            if len(selector) < 3 or not LOAD_RIVAL_STARTER_RE.match(selector[0]):
                continue
            addition = ADD_NUMBER_RE.match(selector[1])
            if (
                addition
                and parse_asm_int(addition.group(1)) == offset
                and STORE_TRAINER_NUMBER_RE.match(selector[2])
            ):
                return True
    return False


def parse_trainer_constants(path: Path) -> list[str]:
    constants = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = TRAINER_CONST_RE.match(clean(line))
        if match and match.group(1) != "NOBODY":
            constants.append(match.group(1))
    return constants


def parse_parties(
    path: Path, constants: list[str]
) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    pointers: list[str] = []
    in_pointers = False
    for line in lines:
        stripped = clean(line)
        if stripped == "TrainerDataPointers:":
            in_pointers = True
            continue
        if in_pointers and stripped.startswith("assert_table_length"):
            break
        if in_pointers:
            match = POINTER_RE.match(stripped)
            if match:
                pointers.append(match.group(1))

    if len(pointers) != len(constants):
        errors.append(
            f"{path}: TrainerDataPointers has {len(pointers)} entries; "
            f"trainer_constants.asm defines {len(constants)} trainer classes"
        )
    for index, (pointer, constant) in enumerate(zip(pointers, constants), 1):
        expected_key = key(constant)
        if expected_key == "PSYCHICTR":
            expected_key = "PSYCHIC"
        if key(pointer) != expected_key:
            errors.append(
                f"{path}: TrainerDataPointers entry {index} ({pointer}) "
                f"does not match trainer class {constant}"
            )

    pointer_keys = [key(label) for label in pointers]
    if len(pointer_keys) != len(set(pointer_keys)):
        errors.append(f"{path}: duplicate TrainerDataPointers target")
    classes: dict[str, list[dict]] = {key(name): [] for name in constants}
    pointer_to_class = {
        key(pointer): key(constant) for pointer, constant in zip(pointers, constants)
    }
    current: str | None = None
    for lineno, line in enumerate(lines, 1):
        stripped = clean(line)
        match = LABEL_RE.match(stripped)
        if match:
            candidate = key(match.group(1))
            if candidate in pointer_to_class:
                current = pointer_to_class[candidate]
            else:
                current = None
            continue
        values = fields(line)
        if current is None or values is None:
            continue
        if values == ["-1"]:
            current = None
            continue
        if not values or values[-1] != "0":
            errors.append(f"{path}:{lineno}: trainer party is not 0-terminated")
            continue
        body = values[:-1]
        mons: list[dict] = []
        if body and body[0].upper() == "$FF":
            pairs = body[1:]
            if len(pairs) % 2:
                errors.append(f"{path}:{lineno}: $FF party has an incomplete level/species pair")
                continue
            for pos in range(0, len(pairs), 2):
                level_text, species = pairs[pos : pos + 2]
                try:
                    level = int(level_text, 0)
                except ValueError:
                    errors.append(f"{path}:{lineno}: invalid level {level_text!r}")
                    level = -1
                mons.append({"level": level, "species": species})
        elif body:
            try:
                level = int(body[0], 0)
            except ValueError:
                errors.append(f"{path}:{lineno}: invalid shared level {body[0]!r}")
                level = -1
            mons = [{"level": level, "species": species} for species in body[1:]]
        else:
            errors.append(f"{path}:{lineno}: empty trainer party")

        if not 1 <= len(mons) <= 6:
            errors.append(f"{path}:{lineno}: party size {len(mons)} is outside 1..6")
        for mon in mons:
            if not 1 <= mon["level"] <= 100:
                errors.append(
                    f"{path}:{lineno}: {mon['species']} level {mon['level']} is outside 1..100"
                )
        classes[current].append(
            {"id": len(classes[current]) + 1, "line": lineno, "pokemon": mons}
        )

    class_manifest = [
        {
            "class": constant,
            "data_label": pointer,
            "constant_key": key(constant),
            "party_count": len(classes[key(constant)]),
        }
        for constant, pointer in zip(constants, pointers)
    ]
    return class_manifest, classes, errors


def parse_special_moves(
    path: Path, classes: dict[str, list[dict]]
) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    records: list[dict] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    active: dict | None = None
    started = False
    ended = False

    for lineno, line in enumerate(lines, 1):
        if clean(line) == "SpecialTrainerMoves:":
            started = True
            continue
        if not started:
            continue
        values = fields(line)
        if values is None:
            continue
        if values == ["-1"]:
            if active is not None:
                errors.append(f"{path}:{lineno}: missing record terminator before end marker")
            ended = True
            break
        if active is None:
            if len(values) != 2:
                errors.append(f"{path}:{lineno}: expected trainer class and party id")
                continue
            class_name, party_text = values
            try:
                party_id = int(party_text, 0)
            except ValueError:
                errors.append(f"{path}:{lineno}: invalid party id {party_text!r}")
                party_id = -1
            active = {
                "class": class_name,
                "party_id": party_id,
                "line": lineno,
                "moves": [],
            }
            continue
        if values == ["0"]:
            records.append(active)
            active = None
            continue
        if len(values) != 3:
            errors.append(f"{path}:{lineno}: expected party slot, move slot, and move")
            continue
        mon_text, slot_text, move = values
        try:
            mon_slot, move_slot = int(mon_text, 0), int(slot_text, 0)
        except ValueError:
            errors.append(f"{path}:{lineno}: invalid numeric slot")
            continue
        active["moves"].append(
            {"party_slot": mon_slot, "move_slot": move_slot, "move": move, "line": lineno}
        )

    if active is not None:
        errors.append(f"{path}:{active['line']}: unterminated special-move record")
    if not ended:
        errors.append(f"{path}: SpecialTrainerMoves is missing its final db -1 marker")

    seen_records: set[tuple[str, int]] = set()
    for record in records:
        class_key = key(record["class"])
        record_key = (class_key, record["party_id"])
        if record_key in seen_records:
            errors.append(
                f"{path}:{record['line']}: duplicate special-move record for "
                f"{record['class']} party {record['party_id']}"
            )
        seen_records.add(record_key)
        parties = classes.get(class_key)
        if parties is None:
            errors.append(f"{path}:{record['line']}: unknown trainer class {record['class']}")
            continue
        if not 1 <= record["party_id"] <= len(parties):
            errors.append(
                f"{path}:{record['line']}: {record['class']} party {record['party_id']} "
                f"is outside 1..{len(parties)}"
            )
            continue
        party_size = len(parties[record["party_id"] - 1]["pokemon"])
        seen_slots: set[tuple[int, int]] = set()
        for move in record["moves"]:
            slot = (move["party_slot"], move["move_slot"])
            if not 1 <= move["party_slot"] <= party_size:
                errors.append(
                    f"{path}:{move['line']}: party slot {move['party_slot']} "
                    f"is outside 1..{party_size}"
                )
            if not 1 <= move["move_slot"] <= 4:
                errors.append(
                    f"{path}:{move['line']}: move slot {move['move_slot']} is outside 1..4"
                )
            if slot in seen_slots:
                errors.append(f"{path}:{move['line']}: duplicate override for slots {slot}")
            seen_slots.add(slot)
    return records, errors


def validate_class_tables(root: Path, expected: int) -> list[str]:
    errors = []
    tables = {
        "data/trainers/names.asm": re.compile(r"^\s*li\s+"),
        "data/trainers/pic_pointers_money.asm": re.compile(r"^\s*pic_money\s+"),
        "data/trainers/ai_pointers.asm": re.compile(r"^\s*dbw\s+"),
        "data/trainers/move_choices.asm": re.compile(r"^\s*move_choices(?:\s|$)"),
    }
    for relative, pattern in tables.items():
        path = root / relative
        count = sum(
            bool(pattern.match(clean(line)))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if count != expected:
            errors.append(f"{path}: has {count} class entries; expected {expected}")
    return errors


def collect_references(
    root: Path, classes: dict[str, list[dict]]
) -> tuple[list[dict], list[str]]:
    references: list[dict] = []
    errors: list[str] = []

    for path in sorted((root / "data/maps/objects").glob("*.asm")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = OBJECT_REF_RE.search(clean(line))
            if match:
                references.append({
                    "kind": "map_object",
                    "path": path.relative_to(root).as_posix(),
                    "line": lineno,
                    "class": match.group(1),
                    "party_ids": [int(match.group(2))],
                    "selector": "literal",
                })

    for path in sorted((root / "scripts").glob("*.asm")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            opponent = LOAD_OPP_RE.match(clean(line))
            if not opponent:
                continue
            # Literal script selectors use the usual load/store pair, followed
            # shortly by a literal trainer number.
            window = lines[index + 1:index + 12]
            if not any("[wCurOpponent]" in clean(item) for item in window[:3]):
                continue
            for offset, candidate in enumerate(window, 1):
                number = LOAD_NUMBER_RE.match(clean(candidate))
                if number and any(
                    "[wTrainerNo]" in clean(item)
                    for item in window[offset:offset + 3]
                ):
                    references.append({
                        "kind": "script",
                        "path": path.relative_to(root).as_posix(),
                        "line": index + 1,
                        "class": opponent.group(1),
                        "party_ids": [parse_asm_int(number.group(1))],
                        "selector": "literal",
                    })
                    break

    for relative, class_name, party_range, offset in DYNAMIC_SELECTOR_CONTRACTS:
        path = root / relative
        if not path.exists():
            errors.append(f"{path}: dynamic selector contract source is missing")
            continue
        expected_party_ids = list(range(offset + 1, offset + 4))
        if list(party_range) != expected_party_ids:
            errors.append(
                f"{path}: dynamic selector contract IDs {list(party_range)} "
                f"do not match wRivalStarter + {offset} ({expected_party_ids})"
            )
        if not has_dynamic_rival_selector(
            path.read_text(encoding="utf-8"), class_name, offset
        ):
            errors.append(
                f"{path}: expected OPP_{class_name} selector "
                f"wRivalStarter + {offset} stored in wTrainerNo"
            )
        references.append({
            "kind": "script",
            "path": relative,
            "line": None,
            "class": class_name,
            "party_ids": expected_party_ids,
            "selector": f"wRivalStarter + {offset}",
        })

    errors.extend(validate_references(references, classes, root))
    return references, errors


def validate_references(
    references: list[dict], classes: dict[str, list[dict]], root: Path
) -> list[str]:
    errors: list[str] = []
    for ref in references:
        class_key = key(ref["class"])
        parties = classes.get(class_key)
        location = f"{root / ref['path']}"
        if ref["line"]:
            location += f":{ref['line']}"
        if parties is None:
            errors.append(f"{location}: unknown trainer class OPP_{ref['class']}")
            continue
        for party_id in ref["party_ids"]:
            if not 1 <= party_id <= len(parties):
                errors.append(
                    f"{location}: OPP_{ref['class']} party {party_id} "
                    f"is outside 1..{len(parties)}"
                )
    return errors


def compare_topology(manifest: dict, baseline_path: Path) -> list[str]:
    errors = []
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    def topology(items: list[dict]) -> list[tuple[str, int]]:
        return [
            (
                key(item.get("data_label", item.get("class", item["constant_key"]))),
                item["party_count"],
            )
            for item in items
        ]

    current = topology(manifest["classes"])
    expected = topology(baseline["classes"])
    if current != expected:
        errors.append(
            f"{baseline_path}: trainer class order or per-class party counts "
            "differ from the topology baseline"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the script's repository)",
    )
    parser.add_argument("--manifest", type=Path, help="write parsed data as JSON")
    parser.add_argument(
        "--baseline", type=Path,
        help="manifest whose class order and per-class party counts must be preserved",
    )
    args = parser.parse_args()
    parties_path = args.root / "data/trainers/parties.asm"
    moves_path = args.root / "data/trainers/special_moves.asm"

    constants = parse_trainer_constants(args.root / "constants/trainer_constants.asm")
    class_manifest, classes, errors = parse_parties(parties_path, constants)
    records, move_errors = parse_special_moves(moves_path, classes)
    errors.extend(move_errors)
    errors.extend(validate_class_tables(args.root, len(constants)))
    references, reference_errors = collect_references(args.root, classes)
    errors.extend(reference_errors)
    manifest = {
        "summary": {
            "trainer_classes": len(class_manifest),
            "parties": sum(item["party_count"] for item in class_manifest),
            "special_move_records": len(records),
            "special_move_overrides": sum(len(item["moves"]) for item in records),
        },
        "classes": class_manifest,
        "parties": classes,
        "special_moves": records,
        "references": references,
    }
    if args.baseline:
        errors.extend(compare_topology(manifest, args.baseline))
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    summary = manifest["summary"]
    print(
        f"Audited {summary['trainer_classes']} classes, {summary['parties']} parties, "
        f"{summary['special_move_records']} special-move records "
        f"({summary['special_move_overrides']} overrides)."
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Trainer audit failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Trainer audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
