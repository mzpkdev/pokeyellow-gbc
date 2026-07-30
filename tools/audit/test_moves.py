import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def matching_lines(path: str, pattern: str) -> list[str]:
    regex = re.compile(pattern)
    return [
        line
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines()
        if regex.match(line)
    ]


class MoveTableTests(unittest.TestCase):
    def test_parallel_move_tables_stay_aligned(self) -> None:
        move_rows = matching_lines("data/moves/moves.asm", r"^\s*move\s+")
        expected = len(move_rows)
        tables = {
            "names": matching_lines("data/moves/names.asm", r'^\s*li\s+"'),
            "descriptions": matching_lines(
                "data/moves/descriptions.asm", r"^\s*dw\s+\w+Description$"
            ),
            "movedex entries": matching_lines(
                "data/moves/movedex_entries.asm", r"^\s*dw\s+\w+DexEntry$"
            ),
            "movedex order": matching_lines(
                "data/moves/movedex_order.asm", r"^\s*db\s+[A-Z][A-Z0-9_]*\s*$"
            ),
        }
        for label, rows in tables.items():
            with self.subTest(table=label):
                self.assertEqual(expected, len(rows))

    def test_struggle_remains_the_last_move(self) -> None:
        move_rows = matching_lines("data/moves/moves.asm", r"^\s*move\s+")
        self.assertRegex(move_rows[-1], r"^\s*move\s+STRUGGLE,")

    def test_movedex_order_contains_each_move_once(self) -> None:
        rows = matching_lines(
            "data/moves/movedex_order.asm", r"^\s*db\s+[A-Z][A-Z0-9_]*\s*$"
        )
        moves = [re.search(r"\bdb\s+([A-Z][A-Z0-9_]*)", row).group(1) for row in rows]
        self.assertEqual(len(moves), len(set(moves)))

    def test_replaced_tms_have_curated_compatibility(self) -> None:
        compatibility = (
            ROOT / "data/moves/curated_tm_compatibility.asm"
        ).read_text(encoding="utf-8")
        replaced_tms = {
            "X_SCISSOR",
            "ROOST",
            "WATER_PULSE",
            "DRAGONBREATH",
            "ROCK_TOMB",
            "BULLET_SEED",
            "SHADOW_BALL",
            "DRILL_RUN",
            "SUPERPOWER",
            "DRAIN_PUNCH",
            "BODY_PRESS",
        }
        curated_moves = set(
            re.findall(r"^\s*db\s+([A-Z][A-Z0-9_]*)\s*$", compatibility, re.MULTILINE)
        )
        self.assertTrue(replaced_tms <= curated_moves)

    def test_advanced_move_metadata_is_registered(self) -> None:
        priority = (ROOT / "data/battle/priority_moves.asm").read_text(encoding="utf-8")
        critical = (
            ROOT / "data/battle/critical_hit_moves.asm"
        ).read_text(encoding="utf-8")
        for move in ("MACH_PUNCH", "AQUA_JET", "EXTREMESPEED"):
            with self.subTest(priority_move=move):
                self.assertRegex(priority, rf"\b{move}\b")
        for move in ("DRILL_RUN", "AIR_CUTTER"):
            with self.subTest(high_critical_move=move):
                self.assertRegex(critical, rf"\b{move}\b")

    def test_tactical_move_engine_hooks_are_registered(self) -> None:
        priority = (ROOT / "data/battle/priority_moves.asm").read_text(encoding="utf-8")
        core = (ROOT / "engine/battle/core.asm").read_text(encoding="utf-8")
        wram = (ROOT / "ram/wram.asm").read_text(encoding="utf-8")
        self.assertRegex(priority, r"\bMIRROR_COAT\b")
        self.assertIn("CalculateFlailBasePower:", core)
        self.assertIn("HandleMirrorCoatMove:", core)
        self.assertIn("RecordSpecialDamage:", core)
        self.assertGreaterEqual(core.count("cp BODY_PRESS"), 4)
        self.assertIn("wPlayerLastSpecialDamage:: dw", wram)
        self.assertIn("wEnemyLastSpecialDamage:: dw", wram)
        self.assertIn("wDirectDamageForMirrorCoat:: db", wram)

    def test_extreme_yellow_flail_curve_boundaries(self) -> None:
        def flail_power(current_hp: int, max_hp: int) -> int:
            for divisor, power in (
                (20, 200),
                (10, 150),
                (5, 100),
                (3, 80),
                (2, 40),
                (1, 20),
            ):
                if current_hp < max_hp // divisor:
                    return power
            return 20

        max_hp = 300
        expected = {
            1: 200,
            14: 200,
            15: 150,
            29: 150,
            30: 100,
            59: 100,
            60: 80,
            99: 80,
            100: 40,
            149: 40,
            150: 20,
            300: 20,
        }
        for hp, power in expected.items():
            with self.subTest(hp=hp):
                self.assertEqual(power, flail_power(hp, max_hp))


if __name__ == "__main__":
    unittest.main()
