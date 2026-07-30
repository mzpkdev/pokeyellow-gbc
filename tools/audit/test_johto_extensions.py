import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

NEW_SPECIES = (
    "SMOOCHUM",
    "ELEKID",
    "MAGBY",
    "POLITOED",
    "SLOWKING",
    "STEELIX",
    "KINGDRA",
    "SCIZOR",
    "PORYGON2",
)

NEW_BOND_SPECIES = (
    "PICHU",
    "CLEFFA",
    "IGGLYBUFF",
    "CROBAT",
    "BLISSEY",
)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def evolution_rows(species: str) -> list[str]:
    data = read("data/pokemon/evos_moves.asm")
    match = re.search(
        rf"(?m)^{species.title().replace('_', '')}EvosMoves:\s*$"
        rf"(?P<body>.*?)(?=^[ \t]*db[ \t]+0(?:[ \t]*;[^\r\n]*)?$)",
        data,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"missing evolution data for {species}")
    return re.findall(r"(?m)^\s*db\s+([^;\r\n]+)", match.group("body"))


def learnset_rows(species: str) -> list[str]:
    data = read("data/pokemon/evos_moves.asm")
    match = re.search(
        rf"(?ms)^{species.title().replace('_', '')}EvosMoves:\s*$"
        rf".*?^[ \t]*db[ \t]+0(?:[ \t]*;[^\r\n]*)?$"
        rf"(?P<body>.*?)(?=^[ \t]*db[ \t]+0(?:[ \t]*;[^\r\n]*)?$)",
        data,
    )
    if match is None:
        raise AssertionError(f"missing learnset data for {species}")
    return re.findall(r"(?m)^\s*db\s+([^;\r\n]+)", match.group("body"))


class JohtoExtensionTests(unittest.TestCase):
    def test_new_dex_entries_are_appended_in_order(self) -> None:
        constants = re.findall(
            r"(?m)^\s*const\s+(DEX_[A-Z0-9_]+)\b",
            read("constants/pokedex_constants.asm"),
        )
        self.assertEqual(165, len(constants))
        self.assertEqual(
            [
                "DEX_MEW",
                *(f"DEX_{species}" for species in NEW_SPECIES),
                *(f"DEX_{species}" for species in NEW_BOND_SPECIES),
            ],
            constants[150:],
        )

    def test_babies_use_their_gen2_level_evolutions(self) -> None:
        expected = {
            "SMOOCHUM": "EVOLVE_LEVEL, 30, JYNX",
            "ELEKID": "EVOLVE_LEVEL, 30, ELECTABUZZ",
            "MAGBY": "EVOLVE_LEVEL, 30, MAGMAR",
        }
        for species, row in expected.items():
            with self.subTest(species=species):
                self.assertEqual([row], evolution_rows(species))

    def test_trade_evolutions_are_first_and_branches_are_preserved(self) -> None:
        expected = {
            "POLIWHIRL": [
                "EVOLVE_TRADE, 1, POLITOED",
                "EVOLVE_ITEM, WATER_STONE, 1, POLIWRATH",
            ],
            "SLOWPOKE": [
                "EVOLVE_TRADE, 1, SLOWKING",
                "EVOLVE_LEVEL, 37, SLOWBRO",
            ],
            "ONIX": ["EVOLVE_TRADE, 1, STEELIX"],
            "SEADRA": ["EVOLVE_TRADE, 1, KINGDRA"],
            "SCYTHER": ["EVOLVE_TRADE, 1, SCIZOR"],
            "PORYGON": ["EVOLVE_TRADE, 1, PORYGON2"],
        }
        for species, rows in expected.items():
            with self.subTest(species=species):
                self.assertEqual(rows, evolution_rows(species))

    def test_bond_evolutions_use_the_shared_pikachu_thresholds(self) -> None:
        expected = {
            "PICHU": "EVOLVE_BOND, 160, PIKACHU",
            "CLEFFA": "EVOLVE_BOND, 160, CLEFAIRY",
            "IGGLYBUFF": "EVOLVE_BOND, 160, JIGGLYPUFF",
            "GOLBAT": "EVOLVE_BOND, 200, CROBAT",
            "CHANSEY": "EVOLVE_BOND, 200, BLISSEY",
        }
        for species, row in expected.items():
            with self.subTest(species=species):
                self.assertEqual([row], evolution_rows(species))

    def test_bond_babies_use_curated_family_learnsets(self) -> None:
        expected = {
            "PICHU": [
                "5, LEER",
                "10, QUICK_ATTACK",
                "15, DOUBLE_KICK",
                "18, THUNDER_WAVE",
                "23, DOUBLE_TEAM",
                "28, SING",
                "34, THUNDERPUNCH",
                "40, AGILITY",
                "45, THUNDERBOLT",
                "50, LIGHT_SCREEN",
            ],
            "CLEFFA": [
                "4, SING",
                "8, DEFENSE_CURL",
                "12, DOUBLESLAP",
                "16, MINIMIZE",
                "20, METRONOME",
                "24, SWIFT",
                "30, LIGHT_SCREEN",
            ],
            "IGGLYBUFF": [
                "8, CHARM",
                "12, DISABLE",
                "16, DOUBLESLAP",
                "20, REST",
                "24, BODY_SLAM",
                "30, MIMIC",
                "36, DOUBLE_EDGE",
            ],
        }
        for species, rows in expected.items():
            with self.subTest(species=species):
                self.assertEqual(rows, learnset_rows(species))

    def test_other_extensions_use_curated_family_learnsets(self) -> None:
        expected = {
            "POLITOED": [
                "6, MIST",
                "10, DOUBLESLAP",
                "12, MUD_SHOT",
                "13, WATER_GUN",
                "17, HYPNOSIS",
                "22, WATER_PULSE",
                "30, BODY_SLAM",
                "40, AMNESIA",
                "48, HYDRO_PUMP",
            ],
            "SLOWKING": [
                "6, GROWL",
                "10, WATER_GUN",
                "15, CONFUSION",
                "18, WATER_PULSE",
                "20, DISABLE",
                "25, HEADBUTT",
                "30, PSYBEAM",
                "36, LIGHT_SCREEN",
                "40, AMNESIA",
                "45, PSYCHIC_M",
            ],
            "STEELIX": [
                "12, ROCK_THROW",
                "15, DRAGONBREATH",
                "19, DIG",
                "23, BIND",
                "25, ROCK_TOMB",
                "29, HARDEN",
                "31, SLAM",
                "34, BODY_PRESS",
                "37, ROCK_SLIDE",
                "43, EARTHQUAKE",
            ],
            "KINGDRA": [
                "10, WATER_GUN",
                "14, SMOKESCREEN",
                "18, LEER",
                "20, DRAGONBREATH",
                "22, WATER_PULSE",
                "26, DRAGON_RAGE",
                "30, AURORA_BEAM",
                "33, WATERFALL",
                "37, AGILITY",
                "41, SLAM",
                "45, HYDRO_PUMP",
            ],
            "SCIZOR": [
                "6, FOCUS_ENERGY",
                "12, QUICK_ATTACK",
                "16, CUT",
                "24, AGILITY",
                "30, AIR_CUTTER",
                "36, SLASH",
                "42, X_SCISSOR",
                "48, DOUBLE_TEAM",
                "50, ROOST",
                "53, SUPERPOWER",
                "54, SWORDS_DANCE",
            ],
            "PORYGON2": [
                "12, PSYBEAM",
                "20, RECOVER",
                "24, SHARPEN",
                "28, TRI_ATTACK",
                "32, AGILITY",
                "40, BARRIER",
                "50, HYPER_BEAM",
                "56, MIRROR_COAT",
            ],
            "CROBAT": [
                "5, SUPERSONIC",
                "13, ABSORB",
                "17, LEECH_LIFE",
                "19, WING_ATTACK",
                "21, CONFUSE_RAY",
                "24, SWIFT",
                "29, AIR_CUTTER",
                "33, MEGA_DRAIN",
                "38, AGILITY",
                "41, HAZE",
                "42, X_SCISSOR",
                "55, ROOST",
            ],
            "BLISSEY": [
                "12, DOUBLESLAP",
                "24, SING",
                "30, GROWL",
                "35, CHARM",
                "38, MINIMIZE",
                "42, WATER_PULSE",
                "44, DEFENSE_CURL",
                "48, LIGHT_SCREEN",
                "50, MEGA_PUNCH",
                "54, DOUBLE_EDGE",
            ],
        }
        for species, rows in expected.items():
            with self.subTest(species=species):
                self.assertEqual(rows, learnset_rows(species))

    def test_new_sprites_are_48_pixels_square(self) -> None:
        paths = [
            ROOT / "gfx/pokemon" / facing / f"{species.lower()}{suffix}.png"
            for species in (*NEW_SPECIES, *NEW_BOND_SPECIES)
            for facing, suffix in (("front", ""), ("back", "b"))
        ]
        self.assertEqual(28, len(paths))
        for path in paths:
            with self.subTest(sprite=path.relative_to(ROOT).as_posix()):
                header = path.read_bytes()[:24]
                self.assertEqual(b"\x89PNG\r\n\x1a\n", header[:8])
                self.assertEqual(b"IHDR", header[12:16])
                self.assertEqual((48, 48), struct.unpack(">II", header[16:24]))

    def test_expanded_dex_flags_use_the_reserved_save_space(self) -> None:
        wram = read("ram/wram.asm")
        self.assertRegex(
            wram,
            r"(?s)wPokedexOwned::\s+flag_array\s+NUM_POKEMON\s+"
            r"wPokedexOwnedEnd::\s+"
            r"wPokedexSeen::\s+flag_array\s+NUM_POKEMON\s+"
            r"wPokedexSeenEnd::.*?\n\s*ds\s+16\b",
        )

    def test_babies_are_not_placed_in_the_world(self) -> None:
        source_roots = (
            "data/wild",
            "data/events",
            "data/trainers",
            "maps",
        )
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for source_root in source_roots
            for path in (ROOT / source_root).rglob("*.asm")
        )
        for species in (
            "SMOOCHUM",
            "ELEKID",
            "MAGBY",
            "PICHU",
            "CLEFFA",
            "IGGLYBUFF",
        ):
            with self.subTest(species=species):
                self.assertNotRegex(sources, rf"\b{species}\b")


if __name__ == "__main__":
    unittest.main()
