"""Provenance and exact data-contract checks for OVERWORLD color authority."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from tools.rom_tests.tests.conftest import REPOSITORY_ROOT


DONOR_SHA = "bf823bc15d75ba8335ce2c9418d2eb65897bb878"
DONOR_PRE_CLEANUP_SHA = "a8b62fb990a13da6add30c92f8440b296dddce49"
# Frozen from the permitted donor revisions above. These run in CI without a
# donor checkout; the optional local test below regenerates them with git show.
EXPECTED_PALETTE_CHANNELS_SHA256 = (
    "d94e306dcd04f503eaa528df9e57eea329130fd66f588d38a4173d525d1bd968"
)
EXPECTED_TILE_ATTRIBUTES_00_5F_SHA256 = (
    "5ecabfc009bbea792623e4ae6078bfd79ac00112d030fad9a7a128184dd11e49"
)
DONOR_ROOT = Path(os.environ.get(
    "POKEMON_GBC_CELEBRATIONS_ROOT", "/tmp/Pokemon_GBC_Celebrations",
))
YELLOW_DATA = REPOSITORY_ROOT / "data/tilesets/full_color_overworld.asm"


def _non_snow(source: str) -> str:
    """Select the donor's normal (non-SNOW) conditional branches."""
    output: list[str] = []
    in_snow = False
    keep = True
    for line in source.splitlines():
        directive = line.strip()
        if directive == "IF SNOW":
            assert not in_snow
            in_snow, keep = True, False
        elif directive == "ELSE" and in_snow:
            keep = True
        elif directive == "ENDC" and in_snow:
            in_snow, keep = False, True
        elif keep:
            output.append(line)
    assert not in_snow
    return "\n".join(output)


def _rgb_rows(source: str) -> list[tuple[int, int, int]]:
    return [
        tuple(map(int, match.groups()))
        for match in re.finditer(r"^\s*RGB\s+(\d+),\s*(\d+),\s*(\d+)", source, re.M)
    ]


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def _yellow_attributes() -> list[int]:
    source = YELLOW_DATA.read_text(encoding="utf-8")
    constants = {
        name: int(value, 0)
        for name, value in re.findall(
            r"^DEF\s+(FULL_COLOR_OVERWORLD_\w+)\s+EQU\s+([^\s;]+)", source, re.M,
        )
    }
    table = _between(
        source, "FullColorOverworldTileAttributes::", "FullColorOverworldTileAttributesEnd::",
    )
    values: list[int] = []
    for line in table.splitlines():
        statement = line.split(";", 1)[0].strip()
        if statement.startswith("db "):
            values.extend(constants[token.strip()] for token in statement[3:].split(","))
        elif statement.startswith("ds "):
            count, value = (token.strip() for token in statement[3:].split(",", 1))
            assert count == "$100 - $60"
            values.extend([constants[value]] * (0x100 - 0x60))
    return values


def _git_show(path: str, *, revision: str = DONOR_SHA) -> str:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=DONOR_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _digest(values: list[int]) -> str:
    return hashlib.sha256(bytes(values)).hexdigest()


def _donor_attributes(source: str, constants_source: str) -> list[int]:
    names = re.findall(
        r"^\s*const PAL_BG_(GRAY|RED|GREEN|WATER|YELLOW|BROWN|ROOF|TEXT)\s*(?:;.*)?$",
        constants_source,
        re.M,
    )
    palette = {name: index for index, name in enumerate(names)}
    assert palette == {
        "GRAY": 0, "RED": 1, "GREEN": 2, "WATER": 3,
        "YELLOW": 4, "BROWN": 5, "ROOF": 6, "TEXT": 7,
    }
    result: list[int] = []
    for bank, assignments in re.findall(r"^\s*tilepal\s+(\d+),\s*(.+)$", source, re.M):
        result.extend((int(bank) << 3) | palette[name.strip()] for name in assignments.split(","))
    # Correct the pinned HEAD's truncated table using its last two explicitly
    # authored entries immediately before cleanup commit cb6bb66d.
    assert len(result) == 94
    result.extend([palette["GRAY"], palette["GRAY"]])
    assert len(result) == 96
    return result


def _donor_overworld_palettes(
    palette_source: str, set_source: str, roof_source: str,
) -> list[tuple[int, int, int]]:
    source = _non_snow(palette_source)
    palettes: dict[str, list[tuple[int, int, int]]] = {}
    for match in re.finditer(r"^; 0x[0-9a-f]+: (\w+)\n((?:\s*RGB[^\n]+\n){4})", source, re.M):
        palettes[match.group(1)] = _rgb_rows(match.group(2))

    sets = _non_snow(set_source)
    names = re.findall(
        r"^\s*db\s+(\w+)", _between(sets, "OverworldPalSet:", "RedsHouse1PalSet:"), re.M,
    )
    assert names == [
        "OUTDOOR_GRAY", "OUTDOOR_RED", "OUTDOOR_GREEN", "OUTDOOR_BLUE",
        "OUTDOOR_YELLOW", "OUTDOOR_BROWN", "OUTDOOR_ROOF", "CRYS_TEXTBOX",
    ]
    result = [color for name in names for color in palettes[name]]
    pallet_roof = _rgb_rows(_between(
        roof_source, "PalletRoof:", "ViridianRoof:",
    ))
    result[6 * 4 + 1:6 * 4 + 3] = pallet_roof
    return result


def test_yellow_payload_is_eight_complete_rgb555_palettes() -> None:
    source = YELLOW_DATA.read_text(encoding="utf-8")
    colors = _rgb_rows(_between(
        source, "FullColorOverworldBGPalettes::", "FullColorOverworldBGPalettesEnd::",
    ))
    assert len(colors) == 8 * 4
    assert all(all(0 <= channel <= 31 for channel in color) for color in colors)
    payload = b"".join(
        bytes(((red | green << 5 | blue << 10) & 0xff, (red | green << 5 | blue << 10) >> 8))
        for red, green, blue in colors
    )
    assert len(payload) == 64


def test_yellow_authority_matches_frozen_permitted_donor_digests() -> None:
    yellow = YELLOW_DATA.read_text(encoding="utf-8")
    colors = _rgb_rows(_between(
        yellow, "FullColorOverworldBGPalettes::", "FullColorOverworldBGPalettesEnd::",
    ))
    assert _digest([channel for color in colors for channel in color]) == (
        EXPECTED_PALETTE_CHANNELS_SHA256
    )
    assert _digest(_yellow_attributes()[:0x60]) == (
        EXPECTED_TILE_ATTRIBUTES_00_5F_SHA256
    )


@pytest.mark.skipif(not (DONOR_ROOT / ".git").exists(), reason="donor checkout not supplied")
def test_yellow_exactly_adapts_permitted_donor_palette_and_tile_tables() -> None:
    palette_source = _git_show("color/data/map_palettes.asm")
    set_source = _git_show("color/data/map_palette_sets.asm")
    roof_source = _git_show("color/data/roofpalettes.asm")
    overworld_source = _git_show("color/tilesets/overworld.asm")
    constants_source = _git_show("color/data/map_palette_constants.asm")
    yellow = YELLOW_DATA.read_text(encoding="utf-8")
    yellow_colors = _rgb_rows(_between(
        yellow, "FullColorOverworldBGPalettes::", "FullColorOverworldBGPalettesEnd::",
    ))
    donor_colors = _donor_overworld_palettes(palette_source, set_source, roof_source)
    donor_attributes = _donor_attributes(overworld_source, constants_source)
    assert yellow_colors == donor_colors
    assert _yellow_attributes()[:0x60] == donor_attributes
    assert _digest([channel for color in donor_colors for channel in color]) == (
        EXPECTED_PALETTE_CHANNELS_SHA256
    )
    assert _digest(donor_attributes) == EXPECTED_TILE_ATTRIBUTES_00_5F_SHA256

    # Record the pinned-HEAD defect and prove this adaptation neither inherits
    # its effective WATER,GRAY spill nor invents the intended correction.
    assert sum(
        len(row.split(",")) - 1
        for row in re.findall(r"^\s*tilepal\s+.+$", overworld_source, re.M)
    ) == 94
    reds_house = _git_show("color/tilesets/reds_house.asm")
    first_next_row = re.search(r"^\s*tilepal\s+\d+,\s*(.+)$", reds_house, re.M).group(1)
    assert [name.strip() for name in first_next_row.split(",")[:2]] == ["WATER", "GRAY"]
    previous = _git_show(
        "color/tilesets/overworld.asm", revision=DONOR_PRE_CLEANUP_SHA,
    )
    assert previous.rstrip().endswith("ROOF, ROOF, GRAY, GRAY")
    assert _yellow_attributes()[0x5E:0x60] == [0, 0]


def test_tile_table_has_256_legal_authoritative_assignments_and_semantics() -> None:
    attributes = _yellow_attributes()
    assert len(attributes) == 256
    assert all(attribute & 0x10 == 0 for attribute in attributes)  # CGB bit 4 is unused.
    assert all(attribute & 0x78 == 0 for attribute in attributes[:0x60])
    assert attributes[0x60:] == [7] * 0xA0
    assert attributes[0x03] == 1  # flower: RED
    assert attributes[0x14] == 3  # water: WATER
    assert attributes[0x2C] == 2  # vegetation: GREEN
    assert [attributes[index] for index in (0x2A, 0x2B, 0x3A, 0x3B)] == [0] * 4


def test_pallet_and_route_1_share_overworld_blockset_and_pallet_roof() -> None:
    for name in ("PalletTown", "Route1"):
        header = (REPOSITORY_ROOT / f"data/maps/headers/{name}.asm").read_text(encoding="utf-8")
        assert re.search(rf"map_header\s+{name},\s*\w+,\s*OVERWORLD,", header)
        blocks = (REPOSITORY_ROOT / f"maps/{name}.blk").read_bytes()
        blockset = (REPOSITORY_ROOT / "gfx/blocksets/overworld.bst").read_bytes()
        assert len(blockset) % 16 == 0
        assert max(blocks) < len(blockset) // 16
        assert all(len(blockset[block * 16:block * 16 + 16]) == 16 for block in blocks)

    if (DONOR_ROOT / ".git").exists():
        roof_source = _between(
            _git_show("color/data/roofpalettes.asm"),
            "RoofPalettes:", "PalletRoof:",
        )
        roofs = re.findall(r"^\s*dw\s+(\w+)", roof_source, re.M)
        assert roofs[0] == roofs[12] == "PalletRoof"  # PALLET_TOWN and ROUTE_1


def test_authority_is_provenanced_and_not_derived_from_tile_id_low_bits() -> None:
    source = YELLOW_DATA.read_text(encoding="utf-8")
    assert "https://github.com/CreamElDudJafar/Pokemon_GBC_Celebrations" in source
    assert DONOR_SHA in source
    assert "adapted with permission" in source.lower()
    consumers = "\n".join(
        (REPOSITORY_ROOT / path).read_text(encoding="utf-8")
        for path in ("engine/full_color/lifecycle.asm", "engine/full_color/scheduler.asm")
    )
    assert "FullColorOverworldTileAttributes" in consumers
    assert not re.search(r"\band\s+(?:7|\$0?7)\b", consumers, re.I)
    assert not re.search(r"\b(?:tile_id|n)\s*&\s*(?:7|0x0?7)\b", source, re.I)
