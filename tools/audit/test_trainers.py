import json
import re
import unittest
from pathlib import Path
from unittest.mock import Mock

import trainers


class TrainerAuditTests(unittest.TestCase):
    def test_topology_detects_party_count_drift(self):
        manifest = {"classes": [{"constant_key": "BROCK", "party_count": 2}]}
        baseline = {"classes": [{"constant_key": "BROCK", "party_count": 1}]}
        path = Mock()
        path.read_text.return_value = json.dumps(baseline)
        self.assertTrue(trainers.compare_topology(manifest, path))

    def test_missing_special_moves_end_marker_fails(self):
        path = Mock()
        path.read_text.return_value = (
            "SpecialTrainerMoves:\n"
            "\tdb BROCK, 1\n"
            "\tdb 1, 1, TACKLE\n"
            "\tdb 0\n"
        )
        _, errors = trainers.parse_special_moves(
            path, {"BROCK": [{"pokemon": [{"species": "ONIX", "level": 12}]}]}
        )
        self.assertTrue(any("final db -1" in error for error in errors))

    def test_bad_reference_fails(self):
        refs = [{
            "path": "data/maps/objects/Gym.asm",
            "line": 1,
            "class": "BROCK",
            "party_ids": [2],
        }]
        errors = trainers.validate_references(
            refs, {"BROCK": [{"pokemon": []}]}, Path(".")
        )
        self.assertTrue(any("outside 1..1" in error for error in errors))

    def test_hex_script_selectors_are_collected_and_validated(self):
        root = Path(__file__).resolve().parents[2]
        constants = trainers.parse_trainer_constants(
            root / "constants/trainer_constants.asm"
        )
        _, classes, party_errors = trainers.parse_parties(
            root / "data/trainers/parties.asm", constants
        )
        references, reference_errors = trainers.collect_references(root, classes)
        rocket_parties = sorted(
            reference["party_ids"][0]
            for reference in references
            if trainers.key(reference["class"]) == "ROCKET"
            and 0x2A <= reference["party_ids"][0] <= 0x2F
        )

        self.assertFalse(party_errors)
        self.assertFalse(reference_errors)
        self.assertEqual(rocket_parties, list(range(0x2A, 0x30)))

    def test_dynamic_rival_contracts_match_script_implementations(self):
        root = Path(__file__).resolve().parents[2]
        for relative, class_name, _, offset in trainers.DYNAMIC_SELECTOR_CONTRACTS:
            with self.subTest(path=relative):
                text = (root / relative).read_text(encoding="utf-8")
                self.assertTrue(
                    trainers.has_dynamic_rival_selector(text, class_name, offset)
                )

    def test_dynamic_rival_contracts_reject_changed_offsets(self):
        root = Path(__file__).resolve().parents[2]
        for relative, class_name, _, offset in trainers.DYNAMIC_SELECTOR_CONTRACTS:
            with self.subTest(path=relative):
                text = (root / relative).read_text(encoding="utf-8")
                changed = re.sub(
                    r"(?im)(ld\s+a,\s*\[wRivalStarter\]\s*\r?\n"
                    r"\s*add\s+)(?:\$[0-9a-f]+|\d+)",
                    r"\g<1>99",
                    text,
                    count=1,
                )
                self.assertNotEqual(text, changed)
                self.assertFalse(
                    trainers.has_dynamic_rival_selector(
                        changed, class_name, offset
                    )
                )

    def test_dynamic_rival_contracts_reject_changed_starter_branch(self):
        root = Path(__file__).resolve().parents[2]
        for relative, class_name, _, offset in trainers.DYNAMIC_SELECTOR_CONTRACTS:
            with self.subTest(path=relative):
                text = (root / relative).read_text(encoding="utf-8")
                changed = text.replace(
                    "ld a, [wRivalStarter]", "ld a, [wGameStage]", 1
                )
                self.assertNotEqual(text, changed)
                self.assertFalse(
                    trainers.has_dynamic_rival_selector(
                        changed, class_name, offset
                    )
                )


if __name__ == "__main__":
    unittest.main()
