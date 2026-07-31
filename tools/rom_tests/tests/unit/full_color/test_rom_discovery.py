"""Bank-aware SM83 discovery against small mutation ROMs."""

import pytest

from tools.rom_tests.full_color.rom_discovery import (
    BankAddress,
    CopiedRegion,
    MapSection,
    RomDiscoveryError,
    SM83Decoder,
    bank_address_from_offset,
    discover_rom,
    discover_rom_batched,
    normalize_rom_offset,
    parse_map,
    parse_sym,
)


def synthetic_rom() -> bytes:
    rom = bytearray(0xC000)
    # VBK=1, pointer write to $9800, MBC5 bank=2, call $4000,
    # LDH [C] rDMA, return.
    # Establish both MBC5 bank components; ROM0 roots deliberately begin with
    # an unknown selected bank.
    program = bytes.fromhex("3e01e04f21009877afea00303e02ea0020cd00400e46e2c9")
    rom[0x100 : 0x100 + len(program)] = program
    # Unknown pointer destination.
    rom[0x120:0x122] = bytes.fromhex("77c9")
    # farcall/predef/jump-table roots
    rom[0x130:0x139] = bytes.fromhex("0602210040cd0002c9")
    rom[0x140:0x146] = bytes.fromhex("3e03cd1002c9")
    rom[0x150:0x153] = bytes.fromhex("e9c9c9")
    # Explicit VBK0 pointer destination.
    rom[0x160:0x168] = bytes.fromhex("afe04f21009c77c9")
    rom[0x200] = 0xC9
    rom[0x210] = 0xC9
    # Bank 2 direct tilemap and hardware-OAM pointer writers.
    rom[0x8000:0x8008] = bytes.fromhex("ea00982100fe77c9")
    # Copied-HRAM GDMA launch candidate.
    rom[0x8010:0x8015] = bytes.fromhex("3e80e055c9")
    return bytes(rom)


def symbols():
    return parse_sym(
        """
00:0100 ResetRoot
00:0120 UnknownPointer
00:0130 FarRoot
00:0140 PredefRoot
00:0150 JumpRoot
00:0160 VbkZero
00:0200 Bankswitch
00:0210 Predef
02:4000 BankTwo
02:4010 GdmaCopied
"""
    )


def sections():
    return (
        MapSection(0, 0x0100, 0x0210, "home", "ROM0"),
        MapSection(2, 0x4000, 0x4014, "bank2", "ROMX"),
    )


def test_direct_ldhc_pointer_vbk_mbc5_and_copied_hram() -> None:
    decoder = SM83Decoder(
        synthetic_rom(),
        symbols(),
        sections=sections(),
        copied_regions=(CopiedRegion(2, 0x4000, 0xFF80, 0x15, "hDMARoutine"),),
    )

    report = decoder.decode(["ResetRoot"])

    sites = {(item.bank, item.address): item for item in report.findings}
    assert sites[(0, 0x102)].resource == "VRAM_BANK"
    assert (sites[(0, 0x107)].destination_low, sites[(0, 0x107)].vbk_low) == (
        0x9800,
        1,
    )
    assert sites[(0, 0x116)].destination_low == 0xFF46
    assert sites[(2, 0x4000)].destination_low == 0x9800
    assert sites[(2, 0x4000)].runtime_copy == (0xFF80, 0x15, "hDMARoutine")
    assert sites[(2, 0x4006)].destination_low == 0xFE00
    assert not report.unresolved_destinations
    candidate = next(
        item
        for item in report.candidate_findings
        if (item.bank, item.address) == (2, 0x4000)
    )
    assert candidate.runtime_copy == (0xFF80, 0x15, "hDMARoutine")

    vbk_zero = decoder.decode(["VbkZero"])
    pointer = next(item for item in vbk_zero.findings if item.address == 0x166)
    assert (pointer.destination_low, pointer.vbk_low, pointer.vbk_high) == (
        0x9C00,
        0,
        0,
    )

    gdma = decoder.decode(["GdmaCopied"])
    launch = next(item for item in gdma.findings if item.address == 0x4012)
    assert launch.resource == "HDMA_GDMA"
    assert launch.runtime_copy == (0xFF92, 0x15, "hDMARoutine")


def test_unknown_destination_is_an_explicit_finding() -> None:
    report = SM83Decoder(synthetic_rom(), symbols(), sections=sections()).decode(
        ["UnknownPointer"]
    )

    assert len(report.findings) == 1
    assert not report.findings[0].resolved
    assert report.findings[0].resource == "UNKNOWN_DESTINATION"
    assert "unresolved pointer destination" in report.unresolved_destinations[0]


def test_ld_hl_immediate_tracks_hl_vbk_and_never_disappears_from_candidates() -> None:
    exact = decode_home(bytes.fromhex("2100983600c9"))
    write = next(item for item in exact.findings if item.address == 0x103)
    assert write.mechanism == "pointer-immediate"
    assert (write.destination_low, write.destination_high) == (0x9800, 0x9800)
    candidate = next(item for item in exact.candidate_findings if item.address == 0x103)
    assert candidate.resolved
    assert (candidate.destination_low, candidate.destination_high) == (0x9800, 0x9800)

    unknown = decode_home(bytes.fromhex("3600c9"))
    unresolved = next(item for item in unknown.findings if item.address == 0x100)
    assert not unresolved.resolved
    assert unresolved.resource == "UNKNOWN_DESTINATION"
    assert any(item.address == 0x100 for item in unknown.candidate_findings)

    non_audited = decode_home(bytes.fromhex("2100c03600c9"))
    candidate = next(
        item for item in non_audited.candidate_findings if item.address == 0x103
    )
    assert candidate.resolved
    assert candidate.resource == "NON_AUDITED_DESTINATION"

    for vbk, program in (
        (0, "afe04f2100983600c9"),
        (1, "3e01e04f2100983600c9"),
        (1, "214fff36012100983600c9"),
    ):
        report = decode_home(bytes.fromhex(program))
        write = next(
            item
            for item in report.findings
            if item.mechanism == "pointer-immediate" and item.destination_low == 0x9800
        )
        assert (write.vbk_low, write.vbk_high) == (vbk, vbk)


def test_farcall_predef_and_reviewed_jump_table_reachability() -> None:
    decoder = SM83Decoder(
        synthetic_rom(),
        symbols(),
        sections=sections(),
        predef_targets={3: BankAddress(2, 0x4000)},
        jump_tables={(0, 0x150): (BankAddress(2, 0x4000),)},
    )

    for root in ("FarRoot", "PredefRoot", "JumpRoot"):
        report = decoder.decode([root])
        assert (2, 0x4000) in report.visited


def test_call_expansion_can_be_disabled_without_hiding_call_site_evidence() -> None:
    report = SM83Decoder(
        synthetic_rom(),
        symbols(),
        sections=sections(),
        scene_roots={"ResetRoot"},
        follow_calls=False,
    ).decode(["ResetRoot"])

    assert (2, 0x4000) not in report.visited
    assert any(
        item.category == "scene"
        and item.control_flow_kind == "call"
        and item.address == 0x111
        for item in report.findings
    )
    assert any(item.address == 0x116 for item in report.findings)


def test_dma_control_names_do_not_match_incidental_wait_or_map_substrings() -> None:
    rom = bytearray(0x4000)
    rom[0x100:0x10D] = bytes.fromhex(
        "cd0002"  # LoadMapData
        "cd1002"  # WaitForSound
        "cd2002"  # WriteOAMBlock
        "cd3002"  # ConfiguredWait
        "c9"
    )
    for address in (0x200, 0x210, 0x220, 0x230):
        rom[address] = 0xC9
    table = parse_sym(
        "00:0100 Root\n"
        "00:0200 LoadMapData\n"
        "00:0210 WaitForSound\n"
        "00:0220 WriteOAMBlock\n"
        "00:0230 ConfiguredWait\n"
    )
    report = SM83Decoder(
        bytes(rom),
        table,
        sections=(
            MapSection(0, 0x100, 0x10C, "root", "ROM0"),
            MapSection(0, 0x200, 0x230, "helpers", "ROM0"),
        ),
        dma_control_labels={"ConfiguredWait"},
        follow_calls=False,
    ).decode(["Root"])

    controls = {
        (item.address, item.mechanism)
        for item in report.findings
        if item.resource == "OAM_DMA_CONTROL"
    }
    assert controls == {(0x106, "dma-wrapper"), (0x109, "dma-wait")}


def test_candidate_scan_and_linker_parsers_preserve_bank() -> None:
    decoder = SM83Decoder(synthetic_rom(), symbols(), sections=sections())
    candidates = decoder.scan_executable_candidates()
    assert any(item.bank == 2 and item.address == 0x4000 for item in candidates)

    parsed = parse_map(
        "ROM0 bank #0:\n"
        '\tSECTION: $0100-$0101 ($0002 bytes) ["home"]\n'
        "ROMX bank #2:\n"
        '\tSECTION: $4000-$4007 ($0008 bytes) ["bank2"]\n'
    )
    assert [(item.bank, item.start, item.end) for item in parsed] == [
        (0, 0x100, 0x101),
        (2, 0x4000, 0x4007),
    ]
    assert normalize_rom_offset(2, 0x4000) == 0x8000
    assert bank_address_from_offset(0x8000) == BankAddress(2, 0x4000)
    alias_symbols = parse_sym("02:4000 Primary\n02:4000 Alias\n01 VALUE_ONLY\n")
    assert alias_symbols.aliases(2, 0x4000) == ("Alias", "Primary")
    with pytest.raises(RomDiscoveryError, match="does not match declared size"):
        parse_map('ROM0 bank #0:\n\tSECTION: $0100-$0101 ($0003 bytes) ["bad-size"]\n')
    with pytest.raises(RomDiscoveryError, match="aliases fixed ROM bank"):
        normalize_rom_offset(2, 0x100)


def test_discover_rom_fails_closed_without_complete_linker_sections() -> None:
    rom = bytearray(0x8002)
    rom[0x100:0x106] = bytes.fromhex("2100983600c9")
    rom[0x8000:0x8002] = bytes.fromhex("36c9")
    table = parse_sym("00:0100 Root\n")
    home = (MapSection(0, 0x100, 0x105, "home", "ROM0"),)

    with pytest.raises(RomDiscoveryError, match="requires non-empty"):
        discover_rom(bytes(rom), table, ["Root"])
    with pytest.raises(RomDiscoveryError, match="omit candidate opcode.*02:4000"):
        discover_rom(bytes(rom), table, ["Root"], sections=home)

    complete = home + (MapSection(2, 0x4000, 0x4001, "bank2", "ROMX"),)
    report = discover_rom(bytes(rom), table, ["Root"], sections=complete)
    bank_two = next(
        item
        for item in report.candidate_findings
        if (item.bank, item.address) == (2, 0x4000)
    )
    assert not bank_two.resolved


def test_batched_discovery_matches_combined_roots_and_scans_candidates_once(
    monkeypatch,
) -> None:
    decoder = SM83Decoder(synthetic_rom(), symbols(), sections=sections())
    scans = 0
    validations = 0
    original = SM83Decoder.scan_executable_candidates
    original_validate = SM83Decoder._validate_candidate_coverage

    def counted_scan(self):
        nonlocal scans
        scans += 1
        return original(self)

    def counted_validate(self):
        nonlocal validations
        validations += 1
        return original_validate(self)

    monkeypatch.setattr(SM83Decoder, "scan_executable_candidates", counted_scan)
    monkeypatch.setattr(SM83Decoder, "_validate_candidate_coverage", counted_validate)
    combined = decoder.decode(["VbkZero", "ResetRoot"])
    scans = 0
    validations = 0
    batched = discover_rom_batched(
        synthetic_rom(),
        symbols(),
        ["ResetRoot", "VbkZero", "ResetRoot"],
        batch_size=1,
        sections=sections(),
    )

    assert scans == 1
    assert validations == 1
    assert batched.findings == combined.findings
    assert batched.unresolved_destinations == combined.unresolved_destinations
    assert batched.unresolved_control_flow == combined.unresolved_control_flow
    assert batched.visited == combined.visited
    assert batched.candidate_findings == combined.candidate_findings
    assert batched.candidate_sections == combined.candidate_sections


@pytest.mark.parametrize("batch_size", (0, -1, True, 1.5))
def test_batched_discovery_rejects_invalid_batch_size(batch_size) -> None:
    with pytest.raises(RomDiscoveryError, match="positive integer"):
        discover_rom_batched(
            synthetic_rom(),
            symbols(),
            ["ResetRoot"],
            batch_size=batch_size,
            sections=sections(),
        )


def decode_home(program: bytes, *, extra: bytes = b"", **kwargs):
    rom = bytearray(0x4000)
    rom[0x100 : 0x100 + len(program)] = program
    rom[0x200 : 0x200 + len(extra)] = extra
    table = parse_sym("00:0100 Root\n00:0200 Callee\n")
    return SM83Decoder(
        bytes(rom),
        table,
        sections=(
            MapSection(0, 0x100, 0x100 + len(program) - 1, "root", "ROM0"),
            MapSection(0, 0x200, max(0x200, 0x200 + len(extra) - 1), "callee", "ROM0"),
        ),
        **kwargs,
    ).decode(["Root"])


def test_memory_load_call_pop_and_pair_changes_do_not_reuse_stale_state() -> None:
    # LD A,[a16] -> LD C,A -> LDH [C],A.
    memory_load = decode_home(bytes.fromhex("fa00c04fe2c9"))
    assert not memory_load.findings[0].resolved

    # A call may clobber C, VBK and every tracked pointer register.
    call = decode_home(
        bytes.fromhex("0e463e01e04fcd0002e2c9"), extra=bytes.fromhex("c9")
    )
    sink = next(item for item in call.findings if item.mechanism == "ldh-c")
    assert not sink.resolved
    assert sink.vbk_low is None

    pop = decode_home(bytes.fromhex("0e46c1e2c9"))
    assert not next(item for item in pop.findings if item.mechanism == "ldh-c").resolved

    add_hl = decode_home(bytes.fromhex("2100980101000977c9"))
    assert not next(
        item for item in add_hl.findings if item.mechanism == "pointer"
    ).resolved


@pytest.mark.parametrize(
    "program",
    (
        bytes.fromhex("21ff972377c9"),  # INC HL: 97ff -> 9800
        bytes.fromhex("2101982b77c9"),  # DEC HL: 9801 -> 9800
    ),
)
def test_inc_dec_hl_update_pointer_write_destination(program) -> None:
    report = decode_home(program)
    pointer = next(item for item in report.findings if item.mechanism == "pointer")
    assert (pointer.destination_low, pointer.destination_high) == (0x9800, 0x9800)


def test_unknown_mbc5_write_clears_selection_and_blocks_romx_call() -> None:
    rom = bytearray(0xC000)
    # Establish bank 2, then replace A from unknown memory before rewriting the
    # low bank component and attempting a ROMX call.
    rom[0x100:0x113] = bytes.fromhex("afea00303e02ea0020fa00c0ea0020cd0040c9")
    rom[0x8000] = 0xC9
    report = SM83Decoder(
        bytes(rom),
        parse_sym("00:0100 Root\n02:4000 BankTwo\n"),
        sections=(
            MapSection(0, 0x100, 0x112, "root", "ROM0"),
            MapSection(2, 0x4000, 0x4000, "bank2", "ROMX"),
        ),
    ).decode(["Root"])

    assert (2, 0x4000) not in report.visited
    assert any(
        "unresolved call bank" in item for item in report.unresolved_control_flow
    )


def test_configured_shadow_oam_dma_and_scene_control_flow_evidence() -> None:
    shadow = decode_home(
        bytes.fromhex("2100c0773e80e046c9"),
        shadow_oam_ranges=((0xC000, 0xC09F),),
    )
    pointer = next(item for item in shadow.findings if item.address == 0x103)
    launch = next(item for item in shadow.findings if item.address == 0x106)
    assert pointer.resource == "SHADOW_OAM"
    assert launch.mechanism == "dma-launch"
    assert (launch.dma_source_low, launch.dma_source_high) == (0x8000, 0x8000)

    scene = decode_home(
        bytes.fromhex("cd0002c9"),
        extra=bytes.fromhex("c9"),
        scene_roots={"Root"},
    )
    edge = next(item for item in scene.findings if item.category == "scene")
    assert edge.control_flow_kind == "call"
    assert edge.destination_low == 0x200


@pytest.mark.parametrize(
    ("bank", "address"),
    ((0, 0x4000), (1, 0x3FFF), (1, 0x8000), (2, 0xFFFF)),
)
def test_invalid_rom_mappings_are_rejected(bank, address) -> None:
    with pytest.raises(RomDiscoveryError):
        normalize_rom_offset(bank, address)
