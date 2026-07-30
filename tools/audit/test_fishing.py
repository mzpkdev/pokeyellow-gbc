"""Regression coverage for the curated fishing encounter balance."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


def parse_fishing_data(path: str) -> dict[str, tuple[tuple[int, str], ...]]:
    source = (ROOT / path).read_text(encoding="utf-8")
    index_source = source.split("db -1", 1)[0]
    index = re.findall(
        r"^\s*dbw\s+([A-Z0-9_]+),\s*(\.Group\d+)",
        index_source,
        re.MULTILINE,
    )
    groups = {}
    for match in re.finditer(
        r"(?ms)^(\.Group\d+):\r?\n(.*?)(?=^\.Group\d+:|\Z)",
        source,
    ):
        label, body = match.groups()
        count_match = re.search(r"^\s*db\s+(\d+)", body, re.MULTILINE)
        if count_match is None:
            raise AssertionError(f"{path}: {label} has no encounter count")
        rows = tuple(
            (int(level), species)
            for level, species in re.findall(
                r"^\s*db\s+(\d+),\s*([A-Z0-9_]+)",
                body,
                re.MULTILINE,
            )
        )
        count = int(count_match.group(1))
        if count != len(rows):
            raise AssertionError(
                f"{path}: {label} declares {count} encounters but has {len(rows)}"
            )
        groups[label] = rows

    maps = [map_name for map_name, _ in index]
    if len(maps) != len(set(maps)):
        raise AssertionError(f"{path}: duplicate map entries")
    missing = {label for _, label in index} - groups.keys()
    if missing:
        raise AssertionError(f"{path}: missing groups {sorted(missing)}")
    return {map_name: groups[label] for map_name, label in index}


class FishingBalanceTests(unittest.TestCase):
    def test_good_rod_keeps_curated_global_pool(self) -> None:
        encounters = parse_fishing_data("data/wild/good_rod.asm")
        self.assertGreater(len(encounters), 0)
        self.assertEqual(
            set(encounters.values()),
            {((20, "HORSEA"), (20, "KRABBY"))},
        )

    def test_super_rod_keeps_authored_completion_rows(self) -> None:
        encounters = parse_fishing_data("data/wild/super_rod.asm")
        self.assertEqual(len(encounters), 31)
        expected = {
            "ROUTE_23": (
                (45, "POLIWHIRL"),
                (45, "POLIWRATH"),
                (45, "OMANYTE"),
                (45, "KABUTO"),
            ),
            "SAFARI_ZONE_CENTER": (
                (20, "MAGIKARP"),
                (20, "MAGIKARP"),
                (20, "DRATINI"),
                (25, "DRAGONAIR"),
            ),
            "SEAFOAM_ISLANDS_B4F": (
                (40, "KRABBY"),
                (40, "STARYU"),
                (40, "KINGLER"),
                (40, "STARYU"),
            ),
            "CERULEAN_CAVE_B1F": (
                (60, "SEAKING"),
                (60, "STARMIE"),
                (60, "KABUTOPS"),
                (60, "OMASTAR"),
            ),
        }
        for map_name, rows in expected.items():
            with self.subTest(map=map_name):
                self.assertEqual(encounters[map_name], rows)

    def test_four_slot_groups_keep_original_weight_thresholds(self) -> None:
        source = (ROOT / "engine/items/item_effects.asm").read_text(
            encoding="utf-8"
        )
        weighted_selector = re.search(
            r"cp 4.*?call Random.*?cp \$66.*?cp \$b2.*?cp \$e5",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(weighted_selector)


if __name__ == "__main__":
    unittest.main()
