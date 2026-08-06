"""Strict reviewed rejections for conservative baseline discovery subjects.

Nothing in this module infers that a discovery result is safe to ignore.  A
caller must load an explicit reviewed authority, bind it to the exact baseline
hashes, and consume an exact subject fingerprint.  Unused rows are stale and a
row cannot be consumed twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, ClassVar

from .errors import ContractError
from .rom_discovery import RomFinding, normalize_rom_offset
from .source_discovery import SourceFinding

REJECTION_SCHEMA = "full-color-discovery-rejections-v1"

_ID = re.compile(r"RV-[A-Z0-9][A-Z0-9-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOWER_HEX_BYTES = re.compile(r"(?:[0-9a-f]{2})+\Z")


class DiscoveryReviewValidationError(ContractError):
    """A rejection authority is malformed, ambiguous, or self-stale."""


class StaleDiscoveryReviewError(ContractError):
    """A reviewed rejection does not belong to the current baseline."""


class DuplicateDiscoveryConsumptionError(ContractError):
    """One reviewed rejection was used for more than one discovered subject."""


class SubjectKind(StrEnum):
    SOURCE_FINDING = "SOURCE_FINDING"
    ROM_FINDING = "ROM_FINDING"
    SOURCE_ERROR = "SOURCE_ERROR"
    ROM_UNRESOLVED_DESTINATION = "ROM_UNRESOLVED_DESTINATION"
    ROM_UNRESOLVED_CONTROL_FLOW = "ROM_UNRESOLVED_CONTROL_FLOW"


class RejectionReason(StrEnum):
    NOT_A_WRITE = "NOT_A_WRITE"
    OUTSIDE_OWNER_GATED_SCOPE = "OUTSIDE_OWNER_GATED_SCOPE"
    UNREACHABLE_CODE_OR_DATA = "UNREACHABLE_CODE_OR_DATA"
    DUPLICATE_ALIAS_EVIDENCE = "DUPLICATE_ALIAS_EVIDENCE"
    CONTROL_FLOW_PROVED_BY_REVIEW = "CONTROL_FLOW_PROVED_BY_REVIEW"
    DIAGNOSTIC_PROVED_BENIGN = "DIAGNOSTIC_PROVED_BENIGN"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _object(
    value: object,
    path: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DiscoveryReviewValidationError(
            f"{path}: expected object with string keys"
        )
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise DiscoveryReviewValidationError(
            f"{path}: missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise DiscoveryReviewValidationError(
            f"{path}: unknown fields: {', '.join(unknown)}"
        )
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise DiscoveryReviewValidationError(f"{path}: expected non-empty string")
    return value


def _canonical_line(value: object, path: str) -> str:
    text = _string(value, path)
    if text != text.strip() or "\n" in text or "\r" in text:
        raise DiscoveryReviewValidationError(
            f"{path}: expected one canonical trimmed line"
        )
    return text


def _nullable_string(value: object, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _integer(
    value: object, path: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        bound = f"..{maximum}" if maximum is not None else " or greater"
        raise DiscoveryReviewValidationError(
            f"{path}: expected integer {minimum}{bound}"
        )
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise DiscoveryReviewValidationError(f"{path}: expected boolean")
    return value


def _relative_path(value: object, path: str) -> str:
    text = _string(value, path)
    posix = PurePosixPath(text)
    if posix.is_absolute() or text != str(posix) or "\\" in text or ".." in posix.parts:
        raise DiscoveryReviewValidationError(
            f"{path}: expected normalized repository-relative POSIX path"
        )
    return text


def _sorted_strings(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise DiscoveryReviewValidationError(f"{path}: expected array")
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if result != sorted(set(result)):
        raise DiscoveryReviewValidationError(
            f"{path}: values must be unique and sorted"
        )
    return result


def _nullable_pair(
    low: object,
    high: object,
    path: str,
    *,
    maximum: int,
) -> tuple[int | None, int | None]:
    if low is None and high is None:
        return None, None
    if low is None or high is None:
        raise DiscoveryReviewValidationError(
            f"{path}: low and high must both be null or integers"
        )
    low_value = _integer(low, f"{path}_low", maximum=maximum)
    high_value = _integer(high, f"{path}_high", maximum=maximum)
    if high_value < low_value:
        raise DiscoveryReviewValidationError(f"{path}: high precedes low")
    return low_value, high_value


_SOURCE_FIELDS = {
    "category",
    "path",
    "line",
    "symbol",
    "mechanism",
    "destination",
    "resource",
    "aliases",
    "object",
    "owner_gate",
    "resolved",
    "evidence_sha256",
    "row_kind",
    "direction",
    "destination_path",
    "destination_line",
    "condition",
}


def _source_metadata(value: object, path: str) -> dict[str, Any]:
    obj = _object(value, path, _SOURCE_FIELDS)
    aliases = _sorted_strings(obj["aliases"], f"{path}.aliases")
    evidence_hash = _string(obj["evidence_sha256"], f"{path}.evidence_sha256")
    if not _SHA256.fullmatch(evidence_hash):
        raise DiscoveryReviewValidationError(
            f"{path}.evidence_sha256: expected lowercase SHA-256"
        )
    destination_path = obj["destination_path"]
    destination_line = obj["destination_line"]
    if (destination_path is None) != (destination_line is None):
        raise DiscoveryReviewValidationError(
            f"{path}: destination_path and destination_line must both be null or set"
        )
    return {
        "category": _string(obj["category"], f"{path}.category"),
        "path": _relative_path(obj["path"], f"{path}.path"),
        "line": _integer(obj["line"], f"{path}.line", minimum=1),
        "symbol": _string(obj["symbol"], f"{path}.symbol"),
        "mechanism": _string(obj["mechanism"], f"{path}.mechanism"),
        "destination": _string(obj["destination"], f"{path}.destination"),
        "resource": _string(obj["resource"], f"{path}.resource"),
        "aliases": aliases,
        "object": (
            None
            if obj["object"] is None
            else _relative_path(obj["object"], f"{path}.object")
        ),
        "owner_gate": _nullable_string(obj["owner_gate"], f"{path}.owner_gate"),
        "resolved": _boolean(obj["resolved"], f"{path}.resolved"),
        "evidence_sha256": evidence_hash,
        "row_kind": _nullable_string(obj["row_kind"], f"{path}.row_kind"),
        "direction": _nullable_string(obj["direction"], f"{path}.direction"),
        "destination_path": (
            None
            if destination_path is None
            else _relative_path(destination_path, f"{path}.destination_path")
        ),
        "destination_line": (
            None
            if destination_line is None
            else _integer(destination_line, f"{path}.destination_line", minimum=1)
        ),
        "condition": _nullable_string(obj["condition"], f"{path}.condition"),
    }


_ROM_FIELDS = {
    "bank",
    "address",
    "rom_offset",
    "bytes",
    "mechanism",
    "destination_low",
    "destination_high",
    "resource",
    "vbk_low",
    "vbk_high",
    "root",
    "call_path",
    "runtime_copy",
    "resolved",
    "category",
    "control_flow_kind",
    "dma_source_low",
    "dma_source_high",
}


def _rom_metadata(value: object, path: str) -> dict[str, Any]:
    obj = _object(value, path, _ROM_FIELDS)
    bank = _integer(obj["bank"], f"{path}.bank", maximum=0x1FF)
    address = _integer(obj["address"], f"{path}.address", maximum=0xFFFF)
    try:
        expected_offset = normalize_rom_offset(bank, address)
    except ValueError as exc:
        raise DiscoveryReviewValidationError(
            f"{path}: invalid ROM bank/address"
        ) from exc
    rom_offset = _integer(obj["rom_offset"], f"{path}.rom_offset")
    if rom_offset != expected_offset:
        raise DiscoveryReviewValidationError(
            f"{path}.rom_offset: does not match bank/address"
        )
    byte_text = _string(obj["bytes"], f"{path}.bytes")
    if not _LOWER_HEX_BYTES.fullmatch(byte_text):
        raise DiscoveryReviewValidationError(
            f"{path}.bytes: expected canonical lowercase hex bytes"
        )
    destination_low, destination_high = _nullable_pair(
        obj["destination_low"],
        obj["destination_high"],
        f"{path}.destination",
        maximum=0xFFFF,
    )
    vbk_low, vbk_high = _nullable_pair(
        obj["vbk_low"], obj["vbk_high"], f"{path}.vbk", maximum=1
    )
    dma_low, dma_high = _nullable_pair(
        obj["dma_source_low"],
        obj["dma_source_high"],
        f"{path}.dma_source",
        maximum=0xFFFF,
    )
    call_path = _sorted_or_ordered_path(obj["call_path"], f"{path}.call_path")
    runtime = obj["runtime_copy"]
    runtime_value: dict[str, Any] | None = None
    if runtime is not None:
        runtime_obj = _object(
            runtime, f"{path}.runtime_copy", {"address", "length", "launcher"}
        )
        runtime_value = {
            "address": _integer(
                runtime_obj["address"],
                f"{path}.runtime_copy.address",
                maximum=0xFFFF,
            ),
            "length": _integer(
                runtime_obj["length"],
                f"{path}.runtime_copy.length",
                minimum=1,
                maximum=0x10000,
            ),
            "launcher": _string(
                runtime_obj["launcher"], f"{path}.runtime_copy.launcher"
            ),
        }
    return {
        "bank": bank,
        "address": address,
        "rom_offset": rom_offset,
        "bytes": byte_text,
        "mechanism": _string(obj["mechanism"], f"{path}.mechanism"),
        "destination_low": destination_low,
        "destination_high": destination_high,
        "resource": _string(obj["resource"], f"{path}.resource"),
        "vbk_low": vbk_low,
        "vbk_high": vbk_high,
        "root": _string(obj["root"], f"{path}.root"),
        "call_path": call_path,
        "runtime_copy": runtime_value,
        "resolved": _boolean(obj["resolved"], f"{path}.resolved"),
        "category": _string(obj["category"], f"{path}.category"),
        "control_flow_kind": _nullable_string(
            obj["control_flow_kind"], f"{path}.control_flow_kind"
        ),
        "dma_source_low": dma_low,
        "dma_source_high": dma_high,
    }


def _sorted_or_ordered_path(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DiscoveryReviewValidationError(f"{path}: expected non-empty array")
    return [_string(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _message_metadata(value: object, path: str) -> dict[str, str]:
    obj = _object(value, path, {"message"})
    message = _canonical_line(obj["message"], f"{path}.message")
    return {"message": message}


def _metadata(kind: SubjectKind, value: object, path: str) -> dict[str, Any]:
    if kind is SubjectKind.SOURCE_FINDING:
        return _source_metadata(value, path)
    if kind is SubjectKind.ROM_FINDING:
        return _rom_metadata(value, path)
    return _message_metadata(value, path)


@dataclass(frozen=True, slots=True)
class RejectionSubject:
    kind: SubjectKind
    sha256: str
    _metadata: dict[str, Any]

    @property
    def metadata(self) -> dict[str, Any]:
        return deepcopy(self._metadata)

    @classmethod
    def from_dict(cls, value: object, path: str = "subject") -> "RejectionSubject":
        obj = _object(value, path, {"kind", "sha256", "metadata"})
        kind_text = _string(obj["kind"], f"{path}.kind")
        try:
            kind = SubjectKind(kind_text)
        except ValueError as exc:
            raise DiscoveryReviewValidationError(
                f"{path}.kind: unknown subject kind {kind_text!r}"
            ) from exc
        metadata = _metadata(kind, obj["metadata"], f"{path}.metadata")
        digest = _string(obj["sha256"], f"{path}.sha256")
        expected = _subject_digest(kind, metadata)
        if not _SHA256.fullmatch(digest) or digest != expected:
            raise DiscoveryReviewValidationError(
                f"{path}.sha256: stale or invalid subject fingerprint"
            )
        return cls(kind, digest, metadata)

    @classmethod
    def create(cls, kind: SubjectKind, metadata: object) -> "RejectionSubject":
        checked = _metadata(kind, metadata, "subject.metadata")
        return cls(kind, _subject_digest(kind, checked), checked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sha256": self.sha256,
            "metadata": deepcopy(self._metadata),
        }


def _subject_digest(kind: SubjectKind, metadata: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({"kind": kind.value, "metadata": metadata})
    ).hexdigest()


def source_finding_subject(finding: SourceFinding) -> RejectionSubject:
    if not isinstance(finding, SourceFinding):
        raise TypeError("expected SourceFinding")
    return RejectionSubject.create(SubjectKind.SOURCE_FINDING, finding.to_dict())


def rom_finding_subject(finding: RomFinding) -> RejectionSubject:
    if not isinstance(finding, RomFinding):
        raise TypeError("expected RomFinding")
    return RejectionSubject.create(SubjectKind.ROM_FINDING, finding.to_dict())


def unresolved_message_subject(kind: SubjectKind, message: str) -> RejectionSubject:
    if kind not in {
        SubjectKind.SOURCE_ERROR,
        SubjectKind.ROM_UNRESOLVED_DESTINATION,
        SubjectKind.ROM_UNRESOLVED_CONTROL_FLOW,
    }:
        raise ValueError("message subjects require an unresolved-message kind")
    return RejectionSubject.create(kind, {"message": message})


def source_error_subject(message: str) -> RejectionSubject:
    return unresolved_message_subject(SubjectKind.SOURCE_ERROR, message)


def rom_unresolved_destination_subject(message: str) -> RejectionSubject:
    return unresolved_message_subject(SubjectKind.ROM_UNRESOLVED_DESTINATION, message)


def rom_unresolved_control_flow_subject(message: str) -> RejectionSubject:
    return unresolved_message_subject(SubjectKind.ROM_UNRESOLVED_CONTROL_FLOW, message)


def fingerprint_source_finding(finding: SourceFinding) -> str:
    return source_finding_subject(finding).sha256


def fingerprint_rom_finding(finding: RomFinding) -> str:
    return rom_finding_subject(finding).sha256


def fingerprint_unresolved_message(kind: SubjectKind, message: str) -> str:
    return unresolved_message_subject(kind, message).sha256


@dataclass(frozen=True, slots=True)
class BaselineEvidence:
    source_sha256: str
    rom_sha256: str
    sym_sha256: str
    map_sha256: str
    reviewer: str
    reviewed: bool

    _FIELDS: ClassVar[set[str]] = {
        "source_sha256",
        "rom_sha256",
        "sym_sha256",
        "map_sha256",
        "reviewer",
        "reviewed",
    }

    @classmethod
    def from_dict(cls, value: object, path: str = "evidence") -> "BaselineEvidence":
        obj = _object(value, path, cls._FIELDS)
        hashes: list[str] = []
        for name in (
            "source_sha256",
            "rom_sha256",
            "sym_sha256",
            "map_sha256",
        ):
            digest = obj[name]
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise DiscoveryReviewValidationError(
                    f"{path}.{name}: expected lowercase SHA-256"
                )
            hashes.append(digest)
        reviewer = _canonical_line(obj["reviewer"], f"{path}.reviewer")
        reviewed = _boolean(obj["reviewed"], f"{path}.reviewed")
        if not reviewed:
            raise DiscoveryReviewValidationError(
                f"{path}.reviewed: rejection dispositions must be reviewed"
            )
        return cls(*hashes, reviewer, reviewed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "rom_sha256": self.rom_sha256,
            "sym_sha256": self.sym_sha256,
            "map_sha256": self.map_sha256,
            "reviewer": self.reviewer,
            "reviewed": self.reviewed,
        }

    @property
    def hashes(self) -> tuple[str, str, str, str]:
        return (
            self.source_sha256,
            self.rom_sha256,
            self.sym_sha256,
            self.map_sha256,
        )


@dataclass(frozen=True, slots=True)
class RejectionRow:
    id: str
    subject: RejectionSubject
    reason: RejectionReason
    detail: str
    evidence: BaselineEvidence

    @classmethod
    def from_dict(cls, value: object, path: str) -> "RejectionRow":
        obj = _object(value, path, {"id", "subject", "reason", "detail", "evidence"})
        row_id = _string(obj["id"], f"{path}.id")
        if not _ID.fullmatch(row_id):
            raise DiscoveryReviewValidationError(f"{path}.id: expected stable RV-* ID")
        reason_text = _string(obj["reason"], f"{path}.reason")
        try:
            reason = RejectionReason(reason_text)
        except ValueError as exc:
            raise DiscoveryReviewValidationError(
                f"{path}.reason: unknown closed reason {reason_text!r}"
            ) from exc
        subject = RejectionSubject.from_dict(obj["subject"], f"{path}.subject")
        _validate_reason(reason, subject.kind, f"{path}.reason")
        return cls(
            row_id,
            subject,
            reason,
            _canonical_line(obj["detail"], f"{path}.detail"),
            BaselineEvidence.from_dict(obj["evidence"], f"{path}.evidence"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject.to_dict(),
            "reason": self.reason.value,
            "detail": self.detail,
            "evidence": self.evidence.to_dict(),
        }


_FINDING_REASONS = {
    RejectionReason.NOT_A_WRITE,
    RejectionReason.OUTSIDE_OWNER_GATED_SCOPE,
    RejectionReason.UNREACHABLE_CODE_OR_DATA,
    RejectionReason.DUPLICATE_ALIAS_EVIDENCE,
    RejectionReason.CONTROL_FLOW_PROVED_BY_REVIEW,
}
_MESSAGE_REASONS = {
    RejectionReason.CONTROL_FLOW_PROVED_BY_REVIEW,
    RejectionReason.DIAGNOSTIC_PROVED_BENIGN,
}


def _validate_reason(reason: RejectionReason, kind: SubjectKind, path: str) -> None:
    allowed = (
        _FINDING_REASONS
        if kind in {SubjectKind.SOURCE_FINDING, SubjectKind.ROM_FINDING}
        else _MESSAGE_REASONS
    )
    if reason not in allowed:
        raise DiscoveryReviewValidationError(
            f"{path}: {reason.value} is incompatible with {kind.value}"
        )


@dataclass(frozen=True, slots=True)
class DiscoveryRejectionAuthority:
    rows: tuple[RejectionRow, ...]

    @classmethod
    def from_dict(cls, value: object) -> "DiscoveryRejectionAuthority":
        obj = _object(value, "rejections", {"schema", "rows"})
        if obj["schema"] != REJECTION_SCHEMA:
            raise DiscoveryReviewValidationError(
                f"rejections.schema: expected {REJECTION_SCHEMA!r}"
            )
        raw_rows = obj["rows"]
        if not isinstance(raw_rows, list):
            raise DiscoveryReviewValidationError("rejections.rows: expected array")
        rows = tuple(
            RejectionRow.from_dict(row, f"rejections.rows[{index}]")
            for index, row in enumerate(raw_rows)
        )
        ids = [row.id for row in rows]
        if ids != sorted(ids):
            raise DiscoveryReviewValidationError(
                "rejections.rows: rows must be sorted by stable ID"
            )
        if len(ids) != len(set(ids)):
            raise DiscoveryReviewValidationError("rejections.rows: duplicate IDs")
        fingerprints = [row.subject.sha256 for row in rows]
        if len(fingerprints) != len(set(fingerprints)):
            raise DiscoveryReviewValidationError(
                "rejections.rows: duplicate subject fingerprints"
            )
        return cls(rows)

    @classmethod
    def from_json(cls, value: str | bytes) -> "DiscoveryRejectionAuthority":
        try:
            raw = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DiscoveryReviewValidationError("rejections: invalid JSON") from exc
        return cls.from_dict(raw)

    @classmethod
    def load(cls, path: str | Path) -> "DiscoveryRejectionAuthority":
        return cls.from_json(Path(path).read_bytes())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REJECTION_SCHEMA,
            "rows": [row.to_dict() for row in self.rows],
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict()).decode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def matcher(
        self,
        *,
        source_sha256: str,
        rom_sha256: str,
        sym_sha256: str,
        map_sha256: str,
    ) -> "RejectionMatcher":
        return RejectionMatcher(
            self,
            (source_sha256, rom_sha256, sym_sha256, map_sha256),
        )


class RejectionMatcher:
    """Stateful exact matcher; callers must finish by checking stale rows."""

    def __init__(
        self,
        authority: DiscoveryRejectionAuthority,
        baseline_hashes: tuple[str, str, str, str],
    ) -> None:
        if any(not _SHA256.fullmatch(value) for value in baseline_hashes):
            raise StaleDiscoveryReviewError(
                "current baseline requires four lowercase SHA-256 hashes"
            )
        stale = tuple(
            row.id for row in authority.rows if row.evidence.hashes != baseline_hashes
        )
        if stale:
            raise StaleDiscoveryReviewError(
                "rejection rows have stale baseline evidence: " + ", ".join(stale)
            )
        self._rows = {row.subject.sha256: row for row in authority.rows}
        self._consumed: set[str] = set()

    def consume(self, subject: RejectionSubject) -> str | None:
        if not isinstance(subject, RejectionSubject):
            raise TypeError("expected RejectionSubject")
        row = self._rows.get(subject.sha256)
        if row is None or row.subject != subject:
            return None
        if row.id in self._consumed:
            raise DuplicateDiscoveryConsumptionError(
                f"{row.id}: rejection row consumed more than once"
            )
        self._consumed.add(row.id)
        return row.id

    def consume_source_finding(self, finding: SourceFinding) -> str | None:
        return self.consume(source_finding_subject(finding))

    def consume_rom_finding(self, finding: RomFinding) -> str | None:
        return self.consume(rom_finding_subject(finding))

    def consume_source_error(self, message: str) -> str | None:
        return self.consume(source_error_subject(message))

    def consume_rom_unresolved_destination(self, message: str) -> str | None:
        return self.consume(rom_unresolved_destination_subject(message))

    def consume_rom_unresolved_control_flow(self, message: str) -> str | None:
        return self.consume(rom_unresolved_control_flow_subject(message))

    @property
    def consumed_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._consumed))

    @property
    def stale_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                row.id for row in self._rows.values() if row.id not in self._consumed
            )
        )

    def assert_all_consumed(self) -> None:
        if self.stale_ids:
            raise StaleDiscoveryReviewError(
                "reviewed rejection rows were not rediscovered: "
                + ", ".join(self.stale_ids)
            )

    def consume_exactly(self, subjects: Iterable[RejectionSubject]) -> tuple[str, ...]:
        matched: list[str] = []
        for subject in subjects:
            row_id = self.consume(subject)
            if row_id is None:
                raise StaleDiscoveryReviewError(
                    f"unreviewed discovery subject {subject.kind.value}:{subject.sha256}"
                )
            matched.append(row_id)
        self.assert_all_consumed()
        return tuple(matched)
