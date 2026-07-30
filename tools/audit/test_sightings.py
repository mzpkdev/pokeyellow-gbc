"""Static contracts for the data-driven wild sighting framework."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class WildSightingFrameworkTests(unittest.TestCase):
    def test_every_map_has_an_ordered_zone_and_profile_record(self) -> None:
        map_constants = _source("constants/map_constants.asm")
        sighting_maps = _source("data/wild/sighting_maps.asm")

        maps = re.findall(r"^\s*map_const\s+([A-Z0-9_]+),", map_constants, re.MULTILINE)
        records = re.findall(
            r"^\s*sighting_map\s+([A-Z0-9_]+),\s+([A-Z0-9_]+)\s*;\s*([A-Z0-9_]+)",
            sighting_maps,
            re.MULTILINE,
        )

        self.assertEqual(len(records), len(maps))
        self.assertEqual([record[2] for record in records], maps)
        self.assertIn("assert_table_length NUM_MAPS", sighting_maps)

    def test_every_declared_sighting_zone_is_used(self) -> None:
        declared_zones = set(
            re.findall(
                r"^\s*const\s+(SIGHTING_ZONE_[A-Z0-9_]+)",
                _source("constants/sighting_constants.asm"),
                re.MULTILINE,
            )
        )
        used_zones = set(
            re.findall(
                r"^\s*sighting_map\s+(SIGHTING_ZONE_[A-Z0-9_]+),",
                _source("data/wild/sighting_maps.asm"),
                re.MULTILINE,
            )
        )

        self.assertEqual(
            declared_zones - {"SIGHTING_ZONE_NONE"},
            used_zones - {"SIGHTING_ZONE_NONE"},
        )

    def test_sighting_profiles_match_wild_data_and_explicit_exclusions(self) -> None:
        wild_pointers = _source("data/wild/grass_water.asm")
        sighting_maps = _source("data/wild/sighting_maps.asm")

        wild_rows = re.findall(
            r"^\s*dw\s+([A-Za-z0-9_]+)",
            wild_pointers,
            re.MULTILINE,
        )
        sighting_rows = re.findall(
            r"^\s*sighting_map\s+([A-Z0-9_]+),\s+([A-Z0-9_]+)\s*;\s*([A-Z0-9_]+)",
            sighting_maps,
            re.MULTILINE,
        )

        excluded_maps = {
            "CERULEAN_CAVE_1F",
            "CERULEAN_CAVE_2F",
            "CERULEAN_CAVE_B1F",
            "SAFARI_ZONE_CENTER",
            "SAFARI_ZONE_EAST",
            "SAFARI_ZONE_NORTH",
            "SAFARI_ZONE_WEST",
        }
        wild_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "data/wild/maps").glob("*.asm")
        )

        self.assertEqual(len(wild_rows), len(sighting_rows))
        for wild_data, (zone, profile, map_name) in zip(
            wild_rows, sighting_rows, strict=True
        ):
            if wild_data == "NothingWildMons" or map_name in excluded_maps:
                self.assertEqual(zone, "SIGHTING_ZONE_NONE")
                self.assertEqual(profile, "SIGHTING_PROFILE_NONE")
            else:
                wild_table = re.search(
                    rf"(?ms)^{re.escape(wild_data)}:\r?\n"
                    rf"(.*?)(?=^[A-Za-z]\w*:\r?$|\Z)",
                    wild_sources,
                )
                self.assertIsNotNone(wild_table, wild_data)
                encounter_rates = [
                    int(rate)
                    for rate in re.findall(
                        r"^\s*def_(?:grass|water)_wildmons\s+(\d+)",
                        wild_table.group(1),
                        re.MULTILINE,
                    )
                ]
                has_encounters = any(encounter_rates)
                self.assertEqual(
                    profile != "SIGHTING_PROFILE_NONE",
                    has_encounters,
                    map_name,
                )
                if has_encounters:
                    self.assertNotEqual(zone, "SIGHTING_ZONE_NONE")

    def test_species_tables_are_weighted_and_end_at_full_probability(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        table_names = {
            table_name
            for profile in re.findall(
                r"^\s*sighting_profile\s+(.+)$",
                sightings,
                re.MULTILINE,
            )
            for table_name in re.findall(r"([A-Za-z0-9_]+)", profile)[-2:]
        }
        table_names.remove("NoWildSightings")

        self.assertGreater(len(table_names), 1)
        for table_name in table_names:
            table = re.search(
                rf"(?ms)^{re.escape(table_name)}:\r?\n(.*?)(?=^[A-Za-z]\w*:\r?$|\Z)",
                sightings,
            )
            self.assertIsNotNone(table, table_name)
            entries = re.findall(
                r"^\s*sighting_mon\s+\$([0-9a-f]{2}),\s+([A-Z0-9_]+)",
                table.group(1),
                re.MULTILINE,
            )
            thresholds = [int(threshold, 16) for threshold, _ in entries]
            bucket_sizes = [
                current - previous
                for previous, current in zip(
                    [-1, *thresholds[:-1]],
                    thresholds,
                )
            ]
            self.assertGreater(len(entries), 1, table_name)
            self.assertEqual(thresholds[-1], 0xFF, table_name)
            self.assertEqual(thresholds, sorted(set(thresholds)), table_name)
            # Every listed species must receive at least 5 percent of the
            # 256-byte random range. Thirteen outcomes is the smallest bucket
            # that clears that floor.
            self.assertGreaterEqual(min(bucket_sizes), 13, table_name)
            self.assertRegex(table.group(1), r"(?m)^\s*db 0\s*$")

    def test_profile_method_flags_match_populated_table_pointers(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        profiles = re.findall(
            r"^\s*sighting_profile\s+(.+?),\s*([A-Za-z0-9_]+),\s*([A-Za-z0-9_]+)",
            sightings,
            re.MULTILINE,
        )

        for flags, land_table, water_table in profiles:
            with self.subTest(flags=flags):
                self.assertEqual(
                    land_table != "NoWildSightings",
                    "SIGHTING_METHOD_LAND" in flags,
                )
                self.assertEqual(
                    water_table != "NoWildSightings",
                    "SIGHTING_METHOD_WATER" in flags,
                )

    def test_sighting_species_do_not_overlap_their_zones_normal_species(
        self,
    ) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        sighting_maps = _source("data/wild/sighting_maps.asm")
        wild_pointers = _source("data/wild/grass_water.asm")

        profiles = re.findall(
            r"^\s*sighting_profile\s+[^,]+,\s*([A-Za-z0-9_]+),\s*([A-Za-z0-9_]+)",
            sightings,
            re.MULTILINE,
        )
        profile_names = re.findall(
            r"^\s*const\s+(SIGHTING_PROFILE_[A-Z0-9_]+)",
            _source("constants/sighting_constants.asm"),
            re.MULTILINE,
        )
        profile_tables = dict(zip(profile_names, profiles, strict=True))
        map_records = re.findall(
            r"^\s*sighting_map\s+([A-Z0-9_]+),\s+([A-Z0-9_]+)",
            sighting_maps,
            re.MULTILINE,
        )
        map_wild_data = re.findall(
            r"^\s*dw\s+([A-Za-z0-9_]+)",
            wild_pointers[: wild_pointers.index("assert_table_length NUM_MAPS")],
            re.MULTILINE,
        )

        wild_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "data/wild/maps").glob("*.asm")
        )
        normal_species: dict[str, set[str]] = {}
        profile_zones: dict[str, set[str]] = {
            profile: set() for profile in profile_tables
        }
        for (zone, profile), wild_label in zip(
            map_records,
            map_wild_data,
            strict=True,
        ):
            if profile == "SIGHTING_PROFILE_NONE":
                continue
            profile_zones[profile].add(zone)
            wild_table = re.search(
                rf"(?ms)^{re.escape(wild_label)}:\r?\n(.*?)(?=^[A-Za-z]\w*:\r?$|\Z)",
                wild_sources,
            )
            self.assertIsNotNone(wild_table, wild_label)
            normal_species.setdefault(zone, set()).update(
                re.findall(
                    r"^\s*db\s+\d+,\s*([A-Z0-9_]+)",
                    wild_table.group(1),
                    re.MULTILINE,
                )
            )

        overlaps = []
        for profile, tables in profile_tables.items():
            for table_name in set(tables) - {"NoWildSightings"}:
                table = re.search(
                    rf"(?ms)^{re.escape(table_name)}:\r?\n(.*?)(?=^[A-Za-z]\w*:\r?$|\Z)",
                    sightings,
                )
                self.assertIsNotNone(table, table_name)
                species = set(
                    re.findall(
                        r"^\s*sighting_mon\s+\$[0-9a-f]{2},\s+([A-Z0-9_]+)",
                        table.group(1),
                        re.MULTILINE,
                    )
                )
                for zone in profile_zones[profile]:
                    shared_species = species & normal_species[zone]
                    if shared_species:
                        overlaps.append(
                            f"{table_name} in {zone}: "
                            f"{sorted(shared_species)}"
                        )
        self.assertFalse(
            overlaps,
            "Sighting tables overlap normal encounters: " + "; ".join(overlaps),
        )

    def test_sightings_exclude_starters_fossils_and_legendaries(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        species = set(
            re.findall(
                r"^\s*sighting_mon\s+\$[0-9a-f]{2},\s+([A-Z0-9_]+)",
                sightings,
                re.MULTILINE,
            )
        )
        excluded = {
            "PIKACHU", "RAICHU",
            "EEVEE", "VAPOREON", "JOLTEON", "FLAREON",
            "BULBASAUR", "IVYSAUR", "VENUSAUR",
            "CHARMANDER", "CHARMELEON", "CHARIZARD",
            "SQUIRTLE", "WARTORTLE", "BLASTOISE",
            "OMANYTE", "OMASTAR", "KABUTO", "KABUTOPS", "AERODACTYL",
            "ARTICUNO", "ZAPDOS", "MOLTRES", "MEWTWO", "MEW",
        }
        self.assertFalse(species & excluded)

    def test_land_and_water_tables_use_disjoint_species(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        profiles = re.findall(
            r"^\s*sighting_profile\s+[^,]+,\s*([A-Za-z0-9_]+),\s*([A-Za-z0-9_]+)",
            sightings,
            re.MULTILINE,
        )

        def table_species(table_name: str) -> set[str]:
            table = re.search(
                rf"(?ms)^{re.escape(table_name)}:\r?\n(.*?)(?=^[A-Za-z]\w*:\r?$|\Z)",
                sightings,
            )
            self.assertIsNotNone(table, table_name)
            return set(
                re.findall(
                    r"^\s*sighting_mon\s+\$[0-9a-f]{2},\s+([A-Z0-9_]+)",
                    table.group(1),
                    re.MULTILINE,
                )
            )

        for land_table, water_table in profiles:
            if "NoWildSightings" in (land_table, water_table):
                continue
            shared_species = (
                table_species(land_table) & table_species(water_table)
            )
            self.assertFalse(
                shared_species,
                f"{land_table} and {water_table} share "
                f"{sorted(shared_species)}",
            )

    def test_encounter_hook_runs_after_repel_and_preserves_level(self) -> None:
        encounters = _source("engine/battle/wild_encounters.asm")
        sightings = _source("engine/events/wild_sightings.asm")

        repel_check = encounters.index("cp b\n\tjr c, .CantEncounter2")
        hook = encounters.index("callfar TryReplaceWithWildSighting")
        self.assertGreater(hook, repel_check)

        selector_start = sightings.index("TryReplaceWithWildSighting::")
        selector_end = sightings.index("\nClearWildSighting::", selector_start)
        selector = sightings[selector_start:selector_end]
        self.assertNotIn("wCurEnemyLevel", selector)
        self.assertNotIn("wd49c", selector)
        self.assertIn("ld [wCurPartySpecies], a", selector)
        self.assertIn("ld [wEnemyMonSpecies2], a", selector)
        self.assertLess(selector.index("call ClearWildSighting"), selector.index("ret", selector.index(".gotSpecies")))

    def test_encounter_method_selects_a_dedicated_species_table(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        constants = _source("constants/sighting_constants.asm")
        selector_start = sightings.index("TryReplaceWithWildSighting::")
        selector_end = sightings.index("\nClearWildSighting::", selector_start)
        selector = sightings[selector_start:selector_end]
        table_selector_start = sightings.index("GetWildSightingTable:")
        table_selector_end = sightings.index(
            '\nINCLUDE "data/wild/sighting_maps.asm"',
            table_selector_start,
        )
        table_selector = sightings[table_selector_start:table_selector_end]

        self.assertIn("call GetWildSightingTable", selector)
        self.assertIn("cp SIGHTING_METHOD_WATER", table_selector)
        self.assertIn("inc hl\n\tinc hl", table_selector)
        self.assertIn("dw \\3", constants)
        self.assertIn("table_width 5, WildSightingProfiles", sightings)

    def test_sighting_capture_penalty_uses_the_effective_rate(self) -> None:
        item_effects = _source("engine/items/item_effects.asm")
        ball_start = item_effects.index("ItemUseBall:")
        ball_end = item_effects.index("\nItemUseBallText00:", ball_start)
        ball = item_effects[ball_start:ball_end]
        helper_start = ball.index("GetEffectiveEnemyCatchRate:")
        helper = ball[helper_start:]

        self.assertEqual(ball.count("call GetEffectiveEnemyCatchRate"), 2)
        self.assertIn("bit SIGHTING_BATTLE_F, a", helper)
        self.assertIn("ld a, [wEnemyMonActualCatchRate]", helper)
        self.assertIn("push bc", helper)
        self.assertIn("srl a\n\tsrl a", helper)
        self.assertIn("sub c", helper)
        self.assertIn("pop bc", helper)
        master_ball = ball.index("cp MASTER_BALL")
        first_penalty = ball.index("call GetEffectiveEnemyCatchRate")
        self.assertLess(master_ball, first_penalty)

    def test_world_step_update_is_independent_from_companion_update(self) -> None:
        overworld = _source("home/overworld.asm")
        sighting_call = overworld.index("farcall UpdateWildSightingOnStep")
        companion_call = overworld.index("farcall UpdatePikachuCompanionOnStep")
        self.assertLess(sighting_call, companion_call)

    def test_pikachu_sighting_hint_uses_exclamation_bubble(self) -> None:
        happiness = _source("engine/events/pikachu_happiness.asm")
        portrait_start = happiness.index(".portraitReady")
        portrait_end = happiness.index("\n.queuePendingPortraitAlert", portrait_start)
        portrait = happiness[portrait_start:portrait_end]

        sighting_branch = (
            "cp PIKACHU_PENDING_SIGHTING\n"
            "\tjr z, .portraitSighting"
        )
        sighting_handler = (
            ".portraitSighting\n"
            "\tld b, EXCLAMATION_BUBBLE\n"
            "\tjr .facePlayer"
        )
        self.assertIn(sighting_branch, portrait)
        self.assertIn(sighting_handler, portrait)

    def test_pikachu_sighting_interaction_uses_emotion_27(self) -> None:
        emotions = _source("engine/pikachu/pikachu_emotions.asm")
        table_start = emotions.index(".Emotions:")
        table_end = emotions.index("\n\nIsPlayerPikachuAsleepInParty:", table_start)
        pending_emotions = [
            line.strip()
            for line in emotions[table_start:table_end].splitlines()[1:]
            if line.strip()
        ]

        self.assertEqual(len(pending_emotions), 6)
        self.assertEqual(
            pending_emotions[-1],
            "dpikaemotion PikachuEmotion27",
        )

    def test_travel_charges_before_activation_eligibility_checks(self) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        update_start = sightings.index("UpdateWildSightingOnStep::")
        update_end = sightings.index(
            "\nGetCurrentWildSightingStepMethod:",
            update_start,
        )
        update = sightings[update_start:update_end]

        cooldown = update.index("ld hl, wSightingCooldown")
        pokeballs = update.index("CheckEvent EVENT_GOT_POKEBALLS_FROM_OAK")
        profile = update.index("call GetCurrentWildSightingZoneAndProfile")
        terrain = update.index("call GetCurrentWildSightingStepMethod")
        random_roll = update.index("call Random")

        self.assertLess(cooldown, pokeballs)
        self.assertLess(pokeballs, profile)
        self.assertLess(profile, terrain)
        self.assertLess(terrain, random_roll)
        self.assertIn(
            "ld hl, wSightingCooldown\n"
            "\tld a, [hl]\n"
            "\tand a\n"
            "\tjr z, .charged\n"
            "\tdec [hl]\n"
            "\tret",
            update,
        )
        self.assertIn(
            "CheckEvent EVENT_GOT_POKEBALLS_FROM_OAK\n\tret z",
            update,
        )
        self.assertNotIn("wRepelRemainingSteps", update)

    def test_charged_activation_roll_is_persistent_and_low_probability(
        self,
    ) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        constants = _source("constants/sighting_constants.asm")
        update_start = sightings.index("UpdateWildSightingOnStep::")
        update_end = sightings.index(
            "\nGetCurrentWildSightingStepMethod:",
            update_start,
        )
        update = sightings[update_start:update_end]
        random_block = re.search(
            r"(?ms)^\s*IF !DEF\(_DEBUG\)\s*$"
            r"(.*?)"
            r"^\s*ENDC\s*$",
            update,
        )

        self.assertIsNotNone(random_block)
        self.assertIn(
            "call Random\n"
            "\t\tcp SIGHTING_TRIGGER_CHANCE\n"
            "\t\tpop bc\n"
            "\t\tret nc",
            random_block.group(1),
        )
        # A failed roll returns directly while cooldown remains zero. The
        # compatibility byte from the old interval system must not participate.
        self.assertNotIn("wSightingCooldown", random_block.group(1))
        self.assertNotIn("wSightingStepCounter", update)
        self.assertNotIn("SIGHTING_STEP_INTERVAL", update)
        self.assertNotIn("SIGHTING_STEP_INTERVAL", constants)
        self.assertRegex(
            constants,
            r"(?m)^DEF SIGHTING_TRIGGER_CHANCE\s+EQU \$04(?:\s|;|$)",
        )
        self.assertRegex(
            constants,
            r"(?m)^DEF SIGHTING_COOLDOWN_STEPS\s+EQU \$ff(?:\s|;|$)",
        )

    def test_activation_retains_encounter_terrain_and_profile_method_checks(
        self,
    ) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        update_start = sightings.index("UpdateWildSightingOnStep::")
        update_end = sightings.index(
            "\nGetCurrentWildSightingStepMethod:",
            update_start,
        )
        update = sightings[update_start:update_end]
        terrain_start = sightings.index("GetCurrentWildSightingStepMethod:")
        terrain_end = sightings.index("\nValidateWildSightingZone::", terrain_start)
        terrain_source = sightings[terrain_start:terrain_end]

        self.assertIn("call GetCurrentWildSightingZoneAndProfile", update)
        self.assertIn("call GetCurrentWildSightingStepMethod", update)
        self.assertIn("call GetWildSightingProfile", update)
        self.assertIn("call GetWildSightingTable", update)
        self.assertIn("callfar IsPlayerStandingOnDoorTileOrWarpTile", terrain_source)
        self.assertIn("callfar IsPlayerJustOutsideMap", terrain_source)
        self.assertIn("ld a, SIGHTING_METHOD_LAND\n\tret z", terrain_source)
        self.assertIn("cp $14\n\tld a, SIGHTING_METHOD_WATER", terrain_source)
        self.assertIn("cp FIRST_INDOOR_MAP", terrain_source)
        self.assertIn("cp FOREST\n\tjr z, .ineligible", terrain_source)

    def test_clearing_or_abandoning_an_active_sighting_starts_full_cooldown(
        self,
    ) -> None:
        sightings = _source("engine/events/wild_sightings.asm")
        validate_start = sightings.index("ValidateWildSightingZone::")
        validate_end = sightings.index(
            "\nTryReplaceWithWildSighting::",
            validate_start,
        )
        clear_start = sightings.index("ClearWildSighting::")
        clear_end = sightings.index(
            "\nQueueWildSightingPikachuHint:",
            clear_start,
        )
        validate = sightings[validate_start:validate_end]
        clear = sightings[clear_start:clear_end]

        self.assertIn("jr nz, ClearWildSighting", validate)
        self.assertIn(
            "ld a, SIGHTING_COOLDOWN_STEPS\n"
            "\tld [wSightingCooldown], a",
            clear,
        )

    def test_warp_and_connected_map_entries_validate_the_active_zone(self) -> None:
        overworld = _source("home/overworld.asm")
        clear_variables = _source("engine/overworld/clear_variables.asm")
        self.assertIn("callfar ValidateWildSightingZone", clear_variables)
        self.assertIn(
            "call LoadMapHeader\n\tfarcall ValidateWildSightingZone",
            overworld,
        )


if __name__ == "__main__":
    unittest.main()
