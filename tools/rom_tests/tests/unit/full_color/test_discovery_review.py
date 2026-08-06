"""Strict exact-match contracts for reviewed discovery rejections."""

from copy import deepcopy
from dataclasses import replace

import pytest

from tools.rom_tests.full_color.discovery_review import (
    DiscoveryRejectionAuthority,
    DiscoveryReviewValidationError,
    DuplicateDiscoveryConsumptionError,
    REJECTION_SCHEMA,
    StaleDiscoveryReviewError,
    SubjectKind,
    fingerprint_rom_finding,
    fingerprint_source_finding,
    fingerprint_unresolved_message,
    rom_finding_subject,
    source_finding_subject,
    unresolved_message_subject,
)
from tools.rom_tests.full_color.rom_discovery import RomFinding
from tools.rom_tests.full_color.source_discovery import SourceFinding

HASHES = {
    "source_sha256": "0" * 64,
    "rom_sha256": "1" * 64,
    "sym_sha256": "2" * 64,
    "map_sha256": "3" * 64,
}


def source_finding() -> SourceFinding:
    return SourceFinding(
        "writer",
        "engine/test.asm",
        12,
        "WriteVbk",
        "direct",
        "ff4f",
        "VRAM_BANK",
        ("WriteVbkAlias",),
        "build/engine/test.o",
        "RENDERER_YELLOW",
        True,
        "4" * 64,
        None,
        None,
        None,
        None,
        "z",
    )


def rom_finding() -> RomFinding:
    return RomFinding(
        2,
        0x4000,
        0x8000,
        "e04f",
        "ldh-direct",
        0xFF4F,
        0xFF4F,
        "VRAM_BANK",
        1,
        1,
        "Reset",
        ("Reset", "02:4000"),
        (0xFF80, 8, "hCopy"),
        True,
        "writer",
        None,
        None,
        None,
    )


def evidence(*, reviewed: bool = True) -> dict[str, object]:
    return {
        **HASHES,
        "reviewer": "baseline-reviewer",
        "reviewed": reviewed,
    }


def row(row_id: str, subject, *, reason: str = "NOT_A_WRITE") -> dict[str, object]:
    return {
        "id": row_id,
        "subject": subject.to_dict(),
        "reason": reason,
        "detail": "Linked bytes prove this conservative candidate is not a write.",
        "evidence": evidence(),
    }


def authority_dict(*rows: dict[str, object]) -> dict[str, object]:
    return {"schema": REJECTION_SCHEMA, "rows": list(rows)}


def matcher(authority: DiscoveryRejectionAuthority):
    return authority.matcher(**HASHES)


def test_all_subject_kinds_fingerprint_exact_metadata_and_round_trip() -> None:
    source = source_finding_subject(source_finding())
    rom = rom_finding_subject(rom_finding())
    source_error = unresolved_message_subject(
        SubjectKind.SOURCE_ERROR, "missing generated include"
    )
    destination = unresolved_message_subject(
        SubjectKind.ROM_UNRESOLVED_DESTINATION, "Reset: unknown pointer"
    )
    control = unresolved_message_subject(
        SubjectKind.ROM_UNRESOLVED_CONTROL_FLOW, "Reset: computed jp hl"
    )
    document = DiscoveryRejectionAuthority.from_dict(
        authority_dict(
            row("RV-CONTROL", control, reason="CONTROL_FLOW_PROVED_BY_REVIEW"),
            row("RV-DESTINATION", destination, reason="DIAGNOSTIC_PROVED_BENIGN"),
            row("RV-ROM", rom, reason="UNREACHABLE_CODE_OR_DATA"),
            row("RV-SOURCE", source),
            row("RV-SOURCE-ERROR", source_error, reason="DIAGNOSTIC_PROVED_BENIGN"),
        )
    )

    assert DiscoveryRejectionAuthority.from_json(document.to_json()) == document
    assert document.to_json() == document.to_json()
    assert len(document.sha256) == 64
    review = matcher(document)
    assert (
        review.consume_rom_unresolved_control_flow("Reset: computed jp hl")
        == "RV-CONTROL"
    )
    assert (
        review.consume_rom_unresolved_destination("Reset: unknown pointer")
        == "RV-DESTINATION"
    )
    assert review.consume_rom_finding(rom_finding()) == "RV-ROM"
    assert review.consume_source_finding(source_finding()) == "RV-SOURCE"
    assert review.consume_source_error("missing generated include") == "RV-SOURCE-ERROR"
    review.assert_all_consumed()


def test_every_source_and_rom_field_changes_the_fingerprint() -> None:
    source = source_finding()
    source_changed = replace(source, condition="nz")
    rom = rom_finding()
    rom_changed = RomFinding(
        rom.bank,
        rom.address,
        rom.rom_offset,
        rom.bytes,
        rom.mechanism,
        rom.destination_low,
        rom.destination_high,
        rom.resource,
        rom.vbk_low,
        rom.vbk_high,
        rom.root,
        ("Reset", "DifferentPath"),
        rom.runtime_copy,
        rom.resolved,
        rom.category,
        rom.control_flow_kind,
        rom.dma_source_low,
        rom.dma_source_high,
    )

    assert fingerprint_source_finding(source) != fingerprint_source_finding(
        source_changed
    )
    assert fingerprint_rom_finding(rom) != fingerprint_rom_finding(rom_changed)
    assert fingerprint_unresolved_message(
        SubjectKind.SOURCE_ERROR, "message one"
    ) != fingerprint_unresolved_message(SubjectKind.SOURCE_ERROR, "message two")
    assert fingerprint_unresolved_message(
        SubjectKind.ROM_UNRESOLVED_DESTINATION, "same message"
    ) != fingerprint_unresolved_message(
        SubjectKind.ROM_UNRESOLVED_CONTROL_FLOW, "same message"
    )


def test_stale_subject_hash_duplicate_subject_and_invalid_metadata_are_rejected() -> (
    None
):
    subject = source_finding_subject(source_finding())
    stale_hash = row("RV-STALE", subject)
    stale_hash["subject"]["sha256"] = "f" * 64
    with pytest.raises(DiscoveryReviewValidationError, match="stale or invalid"):
        DiscoveryRejectionAuthority.from_dict(authority_dict(stale_hash))

    with pytest.raises(DiscoveryReviewValidationError, match="duplicate subject"):
        DiscoveryRejectionAuthority.from_dict(
            authority_dict(row("RV-A", subject), row("RV-B", subject))
        )

    invalid = row("RV-INVALID", subject)
    invalid["subject"]["metadata"]["line"] = 0
    with pytest.raises(DiscoveryReviewValidationError, match="expected integer"):
        DiscoveryRejectionAuthority.from_dict(authority_dict(invalid))


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda value: value.update({"schema": "future"}), "schema"),
        (lambda value: value["rows"][0].update({"extra": True}), "unknown fields"),
        (lambda value: value["rows"][0].update({"id": "BAD"}), "RV-"),
        (
            lambda value: value["rows"][0].update({"reason": "BECAUSE"}),
            "unknown closed reason",
        ),
        (
            lambda value: value["rows"][0]["evidence"].update({"reviewed": False}),
            "must be reviewed",
        ),
        (
            lambda value: value["rows"][0]["evidence"].update({"map_sha256": ""}),
            "SHA-256",
        ),
    ),
)
def test_authority_json_is_closed_and_requires_full_review_evidence(
    mutate, message
) -> None:
    raw = authority_dict(row("RV-SOURCE", source_finding_subject(source_finding())))
    mutate(raw)
    with pytest.raises(DiscoveryReviewValidationError, match=message):
        DiscoveryRejectionAuthority.from_dict(raw)


def test_exact_consume_or_stale_semantics_never_infer_a_rejection() -> None:
    subject = source_finding_subject(source_finding())
    document = DiscoveryRejectionAuthority.from_dict(
        authority_dict(row("RV-SOURCE", subject))
    )
    review = matcher(document)
    changed = SourceFinding(
        source_finding().category,
        source_finding().path,
        13,
        source_finding().symbol,
        source_finding().mechanism,
        source_finding().destination,
        source_finding().resource,
        source_finding().aliases,
        source_finding().object,
        source_finding().owner_gate,
        source_finding().resolved,
        source_finding().evidence_sha256,
        condition=source_finding().condition,
    )

    assert review.consume_source_finding(changed) is None
    with pytest.raises(StaleDiscoveryReviewError, match="not rediscovered"):
        review.assert_all_consumed()
    assert review.consume_source_finding(source_finding()) == "RV-SOURCE"
    with pytest.raises(DuplicateDiscoveryConsumptionError, match="more than once"):
        review.consume_source_finding(source_finding())


def test_baseline_hash_change_invalidates_every_row_before_matching() -> None:
    document = DiscoveryRejectionAuthority.from_dict(
        authority_dict(
            row("RV-ROM", rom_finding_subject(rom_finding())),
            row("RV-SOURCE", source_finding_subject(source_finding())),
        )
    )
    stale = {**HASHES, "rom_sha256": "f" * 64}

    with pytest.raises(StaleDiscoveryReviewError, match="RV-ROM, RV-SOURCE"):
        document.matcher(**stale)


def test_consume_exactly_rejects_unreviewed_and_unused_subjects() -> None:
    source = source_finding_subject(source_finding())
    destination = unresolved_message_subject(
        SubjectKind.ROM_UNRESOLVED_DESTINATION, "unknown pointer"
    )
    document = DiscoveryRejectionAuthority.from_dict(
        authority_dict(
            row("RV-DESTINATION", destination, reason="DIAGNOSTIC_PROVED_BENIGN"),
            row("RV-SOURCE", source),
        )
    )

    with pytest.raises(StaleDiscoveryReviewError, match="not rediscovered"):
        matcher(document).consume_exactly((source,))

    unreviewed = unresolved_message_subject(
        SubjectKind.SOURCE_ERROR, "new source diagnostic"
    )
    with pytest.raises(StaleDiscoveryReviewError, match="unreviewed discovery"):
        matcher(document).consume_exactly((unreviewed,))


def test_rows_must_be_sorted_and_message_metadata_is_canonical() -> None:
    source = source_finding_subject(source_finding())
    rom = rom_finding_subject(rom_finding())
    with pytest.raises(DiscoveryReviewValidationError, match="sorted"):
        DiscoveryRejectionAuthority.from_dict(
            authority_dict(row("RV-Z", source), row("RV-A", rom))
        )
    with pytest.raises(DiscoveryReviewValidationError, match="canonical trimmed"):
        unresolved_message_subject(SubjectKind.SOURCE_ERROR, " padded ")


def test_subject_metadata_is_owned_and_not_affected_by_input_mutation() -> None:
    raw_subject = source_finding_subject(source_finding()).to_dict()
    raw = authority_dict(row("RV-SOURCE", source_finding_subject(source_finding())))
    raw["rows"][0]["subject"] = deepcopy(raw_subject)
    document = DiscoveryRejectionAuthority.from_dict(raw)
    raw["rows"][0]["subject"]["metadata"]["symbol"] = "Mutated"

    assert document.rows[0].subject.metadata["symbol"] == "WriteVbk"
