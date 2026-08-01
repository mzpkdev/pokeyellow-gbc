"""Phase 1 measured-placement selection and evidence tests."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tools.rom_tests.full_color.phase1_measurements import (
    FORBIDDEN_ROM_BANKS,
    MAP_IDENTITY,
    MINIMUM_STACK_MARGIN,
    PHASE1_STATE_BYTES,
    LinkMeasurement,
    PlacementError,
    RomCandidate,
    WramCandidate,
    generate,
    select_placement,
    verify_evidence,
)


def candidate(
    bank: int,
    *,
    interrupt_switches: int = 2,
    runtime_switches: int = 2,
    margin: int = MINIMUM_STACK_MARGIN,
    start: int = 0xD000,
    end: int = 0xDFFF,
    overlaps: tuple[str, ...] = (),
    allocated: bool = False,
) -> WramCandidate:
    return WramCandidate(
        section="Full Color Ownership State",
        bank=bank,
        start=start,
        end=end,
        interrupt_bank_switches=interrupt_switches,
        runtime_bank_switches=runtime_switches,
        stack_margin_bytes=margin,
        overlaps=overlaps,
        allocated=allocated,
    )


def measurement(
    *,
    wram: tuple[WramCandidate, ...] | None = None,
    rom: tuple[RomCandidate, ...] | None = None,
    margin: int = MINIMUM_STACK_MARGIN,
) -> LinkMeasurement:
    return LinkMeasurement(
        rom_sha256="1" * 64,
        map_sha256="2" * 64,
        sym_sha256="3" * 64,
        state_bytes=PHASE1_STATE_BYTES,
        wram=wram or (candidate(2, margin=margin),),
        rom=rom or (RomCandidate(0x3B, 0x4000, 0x7FFF),),
        stack_margin_bytes=margin,
    )


def write_measurement_inputs(root: Path, map_text: str) -> None:
    root.mkdir()
    (root / "pokeyellow_debug.gbc").write_bytes(b"rom")
    (root / "pokeyellow_debug.map").write_text(map_text, encoding="utf-8")
    (root / "pokeyellow_debug.sym").write_text(
        "00:dfff wStack\n", encoding="utf-8"
    )


def placement_map(symbols: tuple[str, str], *, rom_end: int = 0x4001) -> str:
    size = rom_end - 0x4000 + 1
    return (
        "ROMX bank #59:\n"
        f'\tSECTION: $4000-${rom_end:04x} (${size:04x} bytes) '
        '["Full Color Ownership Core"]\n'
        f"\t         $4000 = {symbols[0]}\n"
        f"\t         $4000 = {symbols[1]}\n\n"
        "WRAM0 bank #0:\n"
        '\tSECTION: $df15-$dfff ($00eb bytes) ["Stack"]\n'
    )


def test_selection_prefers_measured_interrupt_safe_candidate() -> None:
    slower = candidate(1, interrupt_switches=2, runtime_switches=0, margin=512)
    interrupt_safe = candidate(
        6, interrupt_switches=0, runtime_switches=2, margin=MINIMUM_STACK_MARGIN
    )
    decision = select_placement(measurement(wram=(slower, interrupt_safe)))
    assert decision.selected_wram_bank == 6
    assert decision.state_bytes == PHASE1_STATE_BYTES
    assert decision.stack_margin_bytes >= MINIMUM_STACK_MARGIN


@pytest.mark.parametrize("bank", sorted(FORBIDDEN_ROM_BANKS))
def test_forbidden_rom_bank_never_selects(bank: int) -> None:
    with pytest.raises(PlacementError, match="forbidden ROM bank"):
        select_placement(measurement(rom=(RomCandidate(bank, 0x4000, 0x7FFF),)))


def test_bank_3b_is_selected_only_by_measurement_not_fixed_preference() -> None:
    decision = select_placement(
        measurement(
            rom=(
                RomCandidate(0x3B, 0x6000, 0x7FFF),
                RomCandidate(0x20, 0x4000, 0x7FFF),
            )
        )
    )
    assert decision.selected_rom_bank == 0x20


def test_linked_ownership_core_remains_the_selected_rom_placement() -> None:
    linked = RomCandidate(0x3B, 0x4000, 0x431C, allocated=True)
    larger_free = RomCandidate(0x30, 0x4000, 0x7FFF)
    decision = select_placement(measurement(rom=(larger_free, linked)))
    assert decision.selected_rom_bank == 0x3B
    assert decision.selected_rom_start == 0x4000
    assert decision.rom_allocation_status == "linked"


def test_overlap_is_rejected_and_never_selected() -> None:
    overlapping = candidate(1, interrupt_switches=0, overlaps=("Existing State",))
    valid = candidate(2, interrupt_switches=2)
    decision = select_placement(measurement(wram=(overlapping, valid)))
    assert decision.selected_wram_bank == 2
    rejected = [item for item in decision.rejected_candidates if item.kind == "WRAM"]
    assert len(rejected) == 1
    assert "overlaps measured section" in rejected[0].reason


def test_overlap_fails_closed_when_no_nonoverlapping_candidate_exists() -> None:
    with pytest.raises(PlacementError, match="no WRAM candidate fits"):
        select_placement(
            measurement(wram=(candidate(1, overlaps=("Existing State",)),))
        )


def test_wram_bank_1_legacy_alias_is_rejected_by_real_measurement() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    from tools.rom_tests.full_color.phase1_measurements import measure

    measured = measure(repo_root)
    bank_1 = [item for item in measured.wram if item.bank == 1]
    assert bank_1
    assert all(item.overlaps for item in bank_1)
    assert select_placement(measured).selected_wram_bank == 2


def test_linked_ownership_section_remains_the_selected_placement() -> None:
    linked = candidate(2, start=0xD000, end=0xD00C, allocated=True)
    later_free_range = candidate(2, start=0xD00D, end=0xDFFF)
    decision = select_placement(measurement(wram=(later_free_range, linked)))
    assert decision.selected_wram_start == 0xD000
    assert decision.selected_wram_end == 0xD00C
    assert decision.allocation_status == "linked"


def test_insufficient_stack_margin_fails_closed() -> None:
    margin = MINIMUM_STACK_MARGIN - 1
    with pytest.raises(PlacementError, match="insufficient stack margin"):
        select_placement(measurement(margin=margin))


def test_candidate_order_does_not_change_decision_or_json() -> None:
    candidates = (
        candidate(6, interrupt_switches=1, runtime_switches=4, margin=200),
        candidate(2, interrupt_switches=1, runtime_switches=2, margin=200),
        candidate(4, interrupt_switches=1, runtime_switches=2, margin=200),
    )
    rom = (
        RomCandidate(0x3A, 0x6000, 0x7FFF),
        RomCandidate(0x3B, 0x4000, 0x7FFF),
        RomCandidate(0x10, 0x7000, 0x7FFF),
    )
    first = select_placement(measurement(wram=candidates, rom=rom))
    second = select_placement(
        measurement(wram=tuple(reversed(candidates)), rom=tuple(reversed(rom)))
    )
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.selected_wram_bank == 2
    assert first.selected_rom_bank == 0x3B


def test_wrong_ownership_byte_cost_is_rejected() -> None:
    with pytest.raises(PlacementError, match="ownership state byte cost"):
        select_placement(replace(measurement(), state_bytes=PHASE1_STATE_BYTES + 1))


def test_same_address_map_symbol_reordering_has_stable_identity(tmp_path) -> None:
    root = tmp_path / "repo"
    map_path = root / "pokeyellow_debug.map"
    write_measurement_inputs(root, placement_map(("First", "Second")))
    first_raw = map_path.read_bytes()
    first = generate(root)
    evidence = tmp_path / "placement.json"
    evidence.write_text(first.to_json(), encoding="utf-8")

    map_path.write_text(placement_map(("Second", "First")), encoding="utf-8")
    second = generate(root)

    assert first_raw != map_path.read_bytes()
    assert first.map_sha256 == second.map_sha256
    assert first.to_json() == second.to_json()
    assert first.to_dict()["inputs"]["map"]["sha256_kind"] == MAP_IDENTITY
    verify_evidence(root, evidence)


def test_placement_relevant_map_change_invalidates_evidence(tmp_path) -> None:
    root = tmp_path / "repo"
    map_path = root / "pokeyellow_debug.map"
    write_measurement_inputs(root, placement_map(("First", "Second")))
    original = generate(root)
    evidence = tmp_path / "placement.json"
    evidence.write_text(original.to_json(), encoding="utf-8")

    map_path.write_text(
        placement_map(("First", "Second"), rom_end=0x4002), encoding="utf-8"
    )
    changed = generate(root)

    assert changed.map_sha256 != original.map_sha256
    assert changed.selected_rom_end != original.selected_rom_end
    with pytest.raises(PlacementError, match="stale or edited"):
        verify_evidence(root, evidence)


def test_stale_hash_or_hand_edited_evidence_is_rejected(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pokeyellow_debug.gbc").write_bytes(b"rom")
    (root / "pokeyellow_debug.map").write_text(
        "ROMX bank #59:\n\tEMPTY\n\n"
        "WRAM0 bank #0:\n"
        '\tSECTION: $df15-$dfff ($00eb bytes) ["Stack"]\n',
        encoding="utf-8",
    )
    (root / "pokeyellow_debug.sym").write_text(
        "00:dfff wStack\n", encoding="utf-8"
    )

    evidence = tmp_path / "placement.json"
    evidence.write_text(generate(root).to_json(), encoding="utf-8")
    verify_evidence(root, evidence)

    raw = json.loads(evidence.read_text(encoding="utf-8"))
    raw["inputs"]["rom"]["sha256"] = "0" * 64
    evidence.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(PlacementError, match="stale or edited"):
        verify_evidence(root, evidence)


def test_committed_evidence_is_canonical_for_current_debug_build() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    evidence = repo_root / "specs/full-colors/evidence/phase1-ownership-placement.json"
    decision = verify_evidence(repo_root, evidence)
    assert decision.selected_wram_bank == 2
    assert decision.selected_rom_bank == 0x3B
    assert decision.selected_wram_end - decision.selected_wram_start + 1 == 13
