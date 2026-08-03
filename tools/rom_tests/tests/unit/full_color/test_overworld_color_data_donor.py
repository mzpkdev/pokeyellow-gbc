"""Exact, explicitly invoked comparator for the pinned pokered-gbc donor."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from tools.rom_tests.tests.unit.full_color.test_overworld_color_data import (
    EXPECTED_PALETTE_CHANNELS_SHA256,
    EXPECTED_TILE_ATTRIBUTES_00_5F_SHA256,
    YELLOW_DATA,
    _between,
    _digest,
    _donor_attributes,
    _donor_overworld_palettes,
    _rgb_rows,
    _yellow_attributes,
)


DONOR_ORIGIN = "git@github.com:dannye/pokered-gbc.git"
DONOR_SHA = "c1a3b6c5a7591472241036d0cf09c3817f841f93"
CLEANUP_SHA = "cb6bb66dc91a7a162f442f3bd81ea2887558ada4"
PRE_CLEANUP_SHA = "a8b62fb990a13da6add30c92f8440b296dddce49"
PAYLOAD_PATHS = (
    "color/data/map_palettes.asm",
    "color/data/map_palette_sets.asm",
    "color/data/roofpalettes.asm",
    "color/data/map_palette_constants.asm",
    "color/tilesets/overworld.asm",
)
MECHANISM_PATHS = (
    "color/init.asm",
    "color/wram.asm",
    "color/loadpalettes.asm",
    "color/refreshmaps.asm",
    "color/vblank.asm",
    "color/super_palettes.asm",
    "color/color.asm",
    "color/sprites.asm",
    "color/boulder.asm",
    "color/ssanne.asm",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr.strip() or "git command failed"
    return result.stdout.strip()


def _require_root(value: str | None, is_worktree: Callable[[Path], bool]) -> Path:
    assert value, "POKERED_GBC_ROOT is required for the exact donor comparator"
    root = Path(value)
    assert root.is_dir(), f"POKERED_GBC_ROOT is not a directory: {root}"
    assert is_worktree(root), f"POKERED_GBC_ROOT is not a git worktree: {root}"
    return root


def _validate_identity(origin: str, head: str) -> None:
    assert origin == DONOR_ORIGIN, f"wrong donor origin: {origin}"
    assert head == DONOR_SHA, f"wrong donor HEAD: {head}"


def _validate_paths(exists: Callable[[str], bool]) -> None:
    assert len(PAYLOAD_PATHS) == 5
    assert len(MECHANISM_PATHS) == 10
    for path in (*PAYLOAD_PATHS, *MECHANISM_PATHS):
        assert exists(path), f"missing donor path at pin: {path}"


def _validate_history(parent: str, historic_overworld: str) -> None:
    assert parent == PRE_CLEANUP_SHA, f"wrong cleanup parent: {parent}"
    assert historic_overworld.rstrip().endswith("ROOF, ROOF, GRAY, GRAY"), (
        "pre-cleanup OVERWORLD table does not end with explicit GRAY, GRAY"
    )


def _validate_payload(
    sources: dict[str, str],
    historic_overworld: str,
    correction_5e_5f: tuple[str, str] = ("GRAY", "GRAY"),
) -> None:
    assert set(sources) == set(PAYLOAD_PATHS), (
        "payload derivation must use exactly the five payload authorities"
    )
    overworld = sources["color/tilesets/overworld.asm"]
    authored_count = sum(
        len(row.split(",")) - 1
        for row in re.findall(r"^\s*tilepal\s+.+$", overworld, re.M)
    )
    assert authored_count == 94, f"expected 94 authored entries, got {authored_count}"
    _validate_history(PRE_CLEANUP_SHA, historic_overworld)

    attributes = _donor_attributes(
        overworld,
        sources["color/data/map_palette_constants.asm"],
        correction_5e_5f,
    )
    assert attributes[0x5E:0x60] == [0, 0], "correction must be explicit GRAY, GRAY"
    colors = _donor_overworld_palettes(
        sources["color/data/map_palettes.asm"],
        sources["color/data/map_palette_sets.asm"],
        sources["color/data/roofpalettes.asm"],
    )
    assert _digest([channel for color in colors for channel in color]) == (
        EXPECTED_PALETTE_CHANNELS_SHA256
    ), "donor palette digest changed"
    assert _digest(attributes) == EXPECTED_TILE_ATTRIBUTES_00_5F_SHA256, (
        "donor attribute digest changed"
    )

    yellow = YELLOW_DATA.read_text(encoding="utf-8")
    yellow_colors = _rgb_rows(_between(
        yellow, "FullColorOverworldBGPalettes::", "FullColorOverworldBGPalettesEnd::",
    ))
    assert yellow_colors == colors, "frozen palette bytes differ from donor payload"
    assert _yellow_attributes()[:0x60] == attributes, (
        "frozen attribute bytes differ from corrected donor payload"
    )


@pytest.fixture(scope="module")
def donor_root() -> Path:
    return _require_root(
        os.environ.get("POKERED_GBC_ROOT"),
        lambda root: _git(root, "rev-parse", "--is-inside-work-tree") == "true",
    )


def test_exact_pokered_gbc_donor_contract(donor_root: Path) -> None:
    _validate_identity(
        _git(donor_root, "remote", "get-url", "origin"),
        _git(donor_root, "rev-parse", "HEAD"),
    )
    _validate_paths(lambda path: subprocess.run(
        ["git", "-C", str(donor_root), "cat-file", "-e", f"{DONOR_SHA}:{path}"],
        capture_output=True,
    ).returncode == 0)
    parent = _git(donor_root, "rev-parse", f"{CLEANUP_SHA}^")
    historic = _git(donor_root, "show", f"{PRE_CLEANUP_SHA}:color/tilesets/overworld.asm")
    _validate_history(parent, historic)
    sources = {path: _git(donor_root, "show", f"{DONOR_SHA}:{path}") for path in PAYLOAD_PATHS}
    _validate_payload(sources, historic)


def test_root_validation_rejects_missing_and_non_worktree(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="required"):
        _require_root(None, lambda _: True)
    with pytest.raises(AssertionError, match="not a directory"):
        _require_root(str(tmp_path / "missing"), lambda _: True)
    with pytest.raises(AssertionError, match="not a git worktree"):
        _require_root(str(tmp_path), lambda _: False)


@pytest.mark.parametrize("field", ["origin", "head"])
def test_identity_validation_is_mutation_sensitive(field: str) -> None:
    origin = DONOR_ORIGIN if field != "origin" else DONOR_ORIGIN + ".wrong"
    head = DONOR_SHA if field != "head" else "0" * 40
    with pytest.raises(AssertionError, match=f"wrong donor {'HEAD' if field == 'head' else 'origin'}"):
        _validate_identity(origin, head)


@pytest.mark.parametrize("missing", (*PAYLOAD_PATHS, *MECHANISM_PATHS))
def test_path_validation_is_mutation_sensitive(missing: str) -> None:
    with pytest.raises(AssertionError, match=missing):
        _validate_paths(lambda path: path != missing)


def test_history_validation_is_mutation_sensitive() -> None:
    with pytest.raises(AssertionError, match="wrong cleanup parent"):
        _validate_history("0" * 40, "tilepal 0, ROOF, ROOF, GRAY, GRAY")
    with pytest.raises(AssertionError, match="explicit GRAY, GRAY"):
        _validate_history(PRE_CLEANUP_SHA, "tilepal 0, ROOF, ROOF, WATER, GRAY")


def test_payload_count_and_correction_are_mutation_sensitive(donor_root: Path) -> None:
    historic = _git(donor_root, "show", f"{PRE_CLEANUP_SHA}:color/tilesets/overworld.asm")
    sources = {path: _git(donor_root, "show", f"{DONOR_SHA}:{path}") for path in PAYLOAD_PATHS}
    sources["color/tilesets/overworld.asm"] += "\n\ttilepal 0, GRAY"
    with pytest.raises(AssertionError, match="94 authored entries"):
        _validate_payload(sources, historic)
    sources["color/tilesets/overworld.asm"] = _git(
        donor_root, "show", f"{DONOR_SHA}:color/tilesets/overworld.asm",
    )
    with pytest.raises(
        AssertionError, match=r"\$5e/\$5f correction must be explicit GRAY, GRAY",
    ):
        _validate_payload(sources, historic, ("WATER", "GRAY"))


@pytest.mark.parametrize("kind", ["palette", "attribute"])
def test_payload_digests_are_mutation_sensitive(
    donor_root: Path, kind: str,
) -> None:
    historic = _git(donor_root, "show", f"{PRE_CLEANUP_SHA}:color/tilesets/overworld.asm")
    sources = {path: _git(donor_root, "show", f"{DONOR_SHA}:{path}") for path in PAYLOAD_PATHS}
    if kind == "palette":
        sources["color/data/map_palettes.asm"] = sources["color/data/map_palettes.asm"].replace(
            "RGB 27,31,27", "RGB 26,31,27", 1,
        )
        message = "palette digest changed"
    else:
        sources["color/tilesets/overworld.asm"] = sources["color/tilesets/overworld.asm"].replace(
            "GRAY, BROWN", "RED, BROWN", 1,
        )
        message = "attribute digest changed"
    with pytest.raises(AssertionError, match=message):
        _validate_payload(sources, historic)
