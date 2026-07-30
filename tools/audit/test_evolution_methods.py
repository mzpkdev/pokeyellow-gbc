import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class EvolutionMethodTests(unittest.TestCase):
    def test_bond_record_is_a_three_byte_evolution_method(self) -> None:
        constants = read("constants/pokemon_data_constants.asm")
        data = read("data/pokemon/evos_moves.asm")

        self.assertRegex(
            constants,
            r"(?m)^\s*const EVOLVE_TRADE\s*; 3\s*$"
            r"\n\s*const EVOLVE_BOND\s*; 4\s*$",
        )
        self.assertIn(
            "* db EVOLVE_BOND, Pikachu happiness threshold, species",
            data,
        )

    def test_bond_dispatch_checks_happiness_and_restores_level(self) -> None:
        engine = read("engine/pokemon/evos_moves.asm")
        bond_handler = re.search(
            r"(?ms)^\.checkBondEvo\n(?P<body>.*?)(?=^\.doEvolution\n)",
            engine,
        )
        self.assertIsNotNone(bond_handler)
        body = bond_handler.group("body")
        self.assertIn("ld a, [wPikachuHappiness]", body)
        self.assertIn("jp c, .nextEvoEntry2", body)
        self.assertIn("ld a, [wLoadedMonLevel]", body)

    def test_unknown_three_byte_methods_are_skipped_safely(self) -> None:
        engine = read("engine/pokemon/evos_moves.asm")
        self.assertRegex(
            engine,
            r"(?m)^\s*cp EVOLVE_BOND\s*$"
            r"\n\s*jr z, \.checkBondEvo\s*$"
            r"\n\s*jp \.nextEvoEntry1 ; safely skip unknown 3-byte evolution methods$",
        )

    def test_pokedex_labels_bond_without_exposing_threshold(self) -> None:
        pokedex = read("engine/menus/pokedex.asm")
        handler = re.search(
            r"(?ms)^\.printBondText\n(?P<body>.*?)(?=^\.itemIdByte\n)",
            pokedex,
        )
        self.assertIsNotNone(handler)
        body = handler.group("body")
        self.assertIn("ld de, EvolveBondText", body)
        self.assertIn("inc de ; happiness threshold", body)
        self.assertIn("jr .targetByte", body)
        self.assertIn('EvolveBondText:\n\tdb "*BOND@"', pokedex)


if __name__ == "__main__":
    unittest.main()
