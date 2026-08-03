"""Strict reviewed ACCEPT assignments for Gate 0 discovery findings.

Assignments are exact review decisions, not classification heuristics.  Each
row binds one complete discovery fingerprint to a concrete inventory row and
the baseline on which it was reviewed.  Matchers are single-use and require
callers to account for every authority row.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, ClassVar

from .discovery_review import (
    DiscoveryReviewValidationError,
    RejectionSubject,
    SubjectKind,
    rom_finding_subject,
    source_finding_subject,
)
from .errors import ContractError
from .inventory import SceneRowKind
from .rom_discovery import RomFinding
from .source_discovery import SourceFinding

ASSIGNMENT_SCHEMA = "full-color-discovery-assignments-v1"
NORMAL_DEBUG_PRODUCT = "pokeyellow_debug"
PHASE2_AUDIT_PRODUCT = "pokeyellow_phase2_audit"
ASSIGNMENT_PRODUCTS = frozenset({NORMAL_DEBUG_PRODUCT, PHASE2_AUDIT_PRODUCT})

_ASSIGNMENT_ID = re.compile(r"AS-[A-Z0-9][A-Z0-9-]*\Z")
_ROW_ID = {
    "writer": re.compile(r"WR-[A-Z0-9][A-Z0-9-]*\Z"),
    "scene": re.compile(r"SC-[A-Z0-9][A-Z0-9-]*\Z"),
    "mutation": re.compile(r"MU-[A-Z0-9][A-Z0-9-]*\Z"),
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCENE_DIRECTIONS = {
    "YELLOW_TO_MAP",
    "MAP_TO_YELLOW",
    "YELLOW_TO_YELLOW",
    "MAP_TO_MAP",
}


class DiscoveryAssignmentValidationError(ContractError):
    """An assignment authority is malformed, ambiguous, or self-stale."""


class StaleDiscoveryAssignmentError(ContractError):
    """An assignment does not belong to, or was not found in, this baseline."""


class DuplicateDiscoveryAssignmentConsumptionError(ContractError):
    """One assignment row was used for more than one discovered finding."""


class AssignmentCategory(StrEnum):
    WRITER = "writer"
    SCENE = "scene"
    MUTATION = "mutation"


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
        raise DiscoveryAssignmentValidationError(
            f"{path}: expected object with string keys"
        )
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise DiscoveryAssignmentValidationError(
            f"{path}: missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise DiscoveryAssignmentValidationError(
            f"{path}: unknown fields: {', '.join(unknown)}"
        )
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise DiscoveryAssignmentValidationError(f"{path}: expected non-empty string")
    return value


def _canonical_line(value: object, path: str) -> str:
    text = _string(value, path)
    if text != text.strip() or "\n" in text or "\r" in text:
        raise DiscoveryAssignmentValidationError(
            f"{path}: expected one canonical trimmed line"
        )
    return text


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DiscoveryAssignmentValidationError(
            f"{path}: expected integer {minimum} or greater"
        )
    return value


def _relative_path(value: object, path: str) -> str:
    text = _string(value, path)
    posix = PurePosixPath(text)
    if posix.is_absolute() or text != str(posix) or "\\" in text or ".." in posix.parts:
        raise DiscoveryAssignmentValidationError(
            f"{path}: expected normalized repository-relative POSIX path"
        )
    return text


@dataclass(frozen=True, slots=True)
class AssignmentEvidence:
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
    def from_dict(cls, value: object, path: str) -> AssignmentEvidence:
        obj = _object(value, path, cls._FIELDS)
        hashes: list[str] = []
        for name in ("source_sha256", "rom_sha256", "sym_sha256", "map_sha256"):
            digest = obj[name]
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise DiscoveryAssignmentValidationError(
                    f"{path}.{name}: expected lowercase SHA-256"
                )
            hashes.append(digest)
        reviewer = _canonical_line(obj["reviewer"], f"{path}.reviewer")
        reviewed = obj["reviewed"]
        if not isinstance(reviewed, bool):
            raise DiscoveryAssignmentValidationError(
                f"{path}.reviewed: expected boolean"
            )
        if not reviewed:
            raise DiscoveryAssignmentValidationError(
                f"{path}.reviewed: assignment rows must be reviewed"
            )
        return cls(*hashes, reviewer, reviewed)

    @property
    def hashes(self) -> tuple[str, str, str, str]:
        return (
            self.source_sha256,
            self.rom_sha256,
            self.sym_sha256,
            self.map_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "rom_sha256": self.rom_sha256,
            "sym_sha256": self.sym_sha256,
            "map_sha256": self.map_sha256,
            "reviewer": self.reviewer,
            "reviewed": self.reviewed,
        }


@dataclass(frozen=True, slots=True)
class SceneEnrichment:
    row_kind: SceneRowKind
    direction: str | None
    destination_path: str | None
    destination_line: int | None
    destination_symbol: str | None

    _FIELDS: ClassVar[set[str]] = {
        "row_kind",
        "direction",
        "destination_path",
        "destination_line",
        "destination_symbol",
    }

    @classmethod
    def from_dict(cls, value: object, path: str) -> SceneEnrichment:
        obj = _object(value, path, cls._FIELDS)
        row_kind_text = _string(obj["row_kind"], f"{path}.row_kind")
        try:
            row_kind = SceneRowKind(row_kind_text)
        except ValueError as exc:
            raise DiscoveryAssignmentValidationError(
                f"{path}.row_kind: unknown scene row kind {row_kind_text!r}"
            ) from exc
        direction = obj["direction"]
        destination_path = obj["destination_path"]
        destination_line = obj["destination_line"]
        destination_symbol = obj["destination_symbol"]
        if row_kind is SceneRowKind.LIFECYCLE:
            if any(
                item is not None
                for item in (
                    direction,
                    destination_path,
                    destination_line,
                    destination_symbol,
                )
            ):
                raise DiscoveryAssignmentValidationError(
                    f"{path}: lifecycle enrichment has no direction or destination"
                )
            return cls(row_kind, None, None, None, None)
        if direction not in _SCENE_DIRECTIONS:
            raise DiscoveryAssignmentValidationError(
                f"{path}.direction: directed edge requires a canonical direction"
            )
        if (
            destination_path is None
            or destination_line is None
            or destination_symbol is None
        ):
            raise DiscoveryAssignmentValidationError(
                f"{path}: directed edge requires a complete destination"
            )
        return cls(
            row_kind,
            direction,
            _relative_path(destination_path, f"{path}.destination_path"),
            _integer(destination_line, f"{path}.destination_line", minimum=1),
            _canonical_line(destination_symbol, f"{path}.destination_symbol"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "row_kind": self.row_kind.value,
            "direction": self.direction,
            "destination_path": self.destination_path,
            "destination_line": self.destination_line,
            "destination_symbol": self.destination_symbol,
        }


@dataclass(frozen=True, slots=True)
class MutationEnrichment:
    destination: str

    @classmethod
    def from_dict(cls, value: object, path: str) -> MutationEnrichment:
        obj = _object(value, path, {"destination"})
        return cls(_canonical_line(obj["destination"], f"{path}.destination"))

    def to_dict(self) -> dict[str, str]:
        return {"destination": self.destination}


@dataclass(frozen=True, slots=True)
class AssignmentRow:
    id: str
    category: AssignmentCategory
    row_id: str
    subject: RejectionSubject
    scene: SceneEnrichment | None
    mutation: MutationEnrichment | None
    evidence: AssignmentEvidence
    product: str = NORMAL_DEBUG_PRODUCT
    product_explicit: bool = False

    _FIELDS: ClassVar[set[str]] = {
        "id",
        "category",
        "row_id",
        "subject",
        "scene",
        "mutation",
        "evidence",
    }

    @classmethod
    def from_dict(cls, value: object, path: str) -> AssignmentRow:
        obj = _object(value, path, cls._FIELDS, {"product"})
        product_explicit = "product" in obj
        product = obj.get("product", NORMAL_DEBUG_PRODUCT)
        if product not in ASSIGNMENT_PRODUCTS:
            raise DiscoveryAssignmentValidationError(
                f"{path}.product: unknown link product {product!r}"
            )
        assignment_id = _string(obj["id"], f"{path}.id")
        if not _ASSIGNMENT_ID.fullmatch(assignment_id):
            raise DiscoveryAssignmentValidationError(
                f"{path}.id: expected stable AS-* ID"
            )
        category_text = _string(obj["category"], f"{path}.category")
        try:
            category = AssignmentCategory(category_text)
        except ValueError as exc:
            raise DiscoveryAssignmentValidationError(
                f"{path}.category: unknown assignment category {category_text!r}"
            ) from exc
        row_id = _string(obj["row_id"], f"{path}.row_id")
        if not _ROW_ID[category.value].fullmatch(row_id):
            raise DiscoveryAssignmentValidationError(
                f"{path}.row_id: category {category.value!r} requires "
                f"{_ROW_ID[category.value].pattern[:-2]} ID"
            )
        try:
            subject = RejectionSubject.from_dict(obj["subject"], f"{path}.subject")
        except DiscoveryReviewValidationError as exc:
            raise DiscoveryAssignmentValidationError(str(exc)) from exc
        if subject.kind not in {SubjectKind.SOURCE_FINDING, SubjectKind.ROM_FINDING}:
            raise DiscoveryAssignmentValidationError(
                f"{path}.subject.kind: assignments require a source or ROM finding"
            )
        scene = (
            None
            if obj["scene"] is None
            else SceneEnrichment.from_dict(obj["scene"], f"{path}.scene")
        )
        mutation = (
            None
            if obj["mutation"] is None
            else MutationEnrichment.from_dict(obj["mutation"], f"{path}.mutation")
        )
        if scene is not None and category is not AssignmentCategory.SCENE:
            raise DiscoveryAssignmentValidationError(
                f"{path}.scene: enrichment requires scene category"
            )
        if mutation is not None and category is not AssignmentCategory.MUTATION:
            raise DiscoveryAssignmentValidationError(
                f"{path}.mutation: enrichment requires mutation category"
            )
        if category is AssignmentCategory.SCENE and mutation is not None:
            raise DiscoveryAssignmentValidationError(
                f"{path}.mutation: scene assignment cannot enrich a mutation"
            )
        if category is AssignmentCategory.MUTATION and scene is not None:
            raise DiscoveryAssignmentValidationError(
                f"{path}.scene: mutation assignment cannot enrich a scene"
            )
        if (
            category is AssignmentCategory.SCENE
            and subject.kind is SubjectKind.SOURCE_FINDING
            and scene is None
        ):
            raise DiscoveryAssignmentValidationError(
                f"{path}.scene: source scene assignments require explicit enrichment"
            )
        if subject.kind is SubjectKind.ROM_FINDING and (
            scene is not None or mutation is not None
        ):
            raise DiscoveryAssignmentValidationError(
                f"{path}: ROM findings do not carry source enrichment"
            )
        return cls(
            assignment_id,
            category,
            row_id,
            subject,
            scene,
            mutation,
            AssignmentEvidence.from_dict(obj["evidence"], f"{path}.evidence"),
            product,
            product_explicit,
        )

    def to_dict(self) -> dict[str, object]:
        result = {
            "id": self.id,
            "category": self.category.value,
            "row_id": self.row_id,
            "subject": self.subject.to_dict(),
            "scene": None if self.scene is None else self.scene.to_dict(),
            "mutation": None if self.mutation is None else self.mutation.to_dict(),
            "evidence": self.evidence.to_dict(),
        }
        if self.product_explicit:
            result["product"] = self.product
        return result


@dataclass(frozen=True, slots=True)
class DiscoveryAssignmentAuthority:
    rows: tuple[AssignmentRow, ...]

    @classmethod
    def from_dict(cls, value: object) -> DiscoveryAssignmentAuthority:
        obj = _object(value, "assignments", {"schema", "rows"})
        if obj["schema"] != ASSIGNMENT_SCHEMA:
            raise DiscoveryAssignmentValidationError(
                f"assignments.schema: expected {ASSIGNMENT_SCHEMA!r}"
            )
        raw_rows = obj["rows"]
        if not isinstance(raw_rows, list):
            raise DiscoveryAssignmentValidationError("assignments.rows: expected array")
        rows = tuple(
            AssignmentRow.from_dict(row, f"assignments.rows[{index}]")
            for index, row in enumerate(raw_rows)
        )
        ids = [row.id for row in rows]
        if ids != sorted(ids):
            raise DiscoveryAssignmentValidationError(
                "assignments.rows: rows must be sorted by stable ID"
            )
        if len(ids) != len(set(ids)):
            raise DiscoveryAssignmentValidationError(
                "assignments.rows: duplicate assignment IDs"
            )
        fingerprints = [(row.product, row.subject.sha256) for row in rows]
        if len(fingerprints) != len(set(fingerprints)):
            raise DiscoveryAssignmentValidationError(
                "assignments.rows: duplicate subject fingerprints within one product"
            )
        for product in ASSIGNMENT_PRODUCTS:
            hashes = {row.evidence.hashes for row in rows if row.product == product}
            if len(hashes) > 1:
                raise DiscoveryAssignmentValidationError(
                    f"assignments.rows: mixed product hash tuple for {product}"
                )
        return cls(rows)

    @classmethod
    def from_json(cls, value: str | bytes) -> DiscoveryAssignmentAuthority:
        try:
            raw = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DiscoveryAssignmentValidationError(
                "assignments: invalid JSON"
            ) from exc
        return cls.from_dict(raw)

    @classmethod
    def load(cls, path: str | Path) -> DiscoveryAssignmentAuthority:
        return cls.from_json(Path(path).read_bytes())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ASSIGNMENT_SCHEMA,
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
        product: str = NORMAL_DEBUG_PRODUCT,
    ) -> AssignmentMatcher:
        if product not in ASSIGNMENT_PRODUCTS:
            raise StaleDiscoveryAssignmentError(f"unknown assignment product {product!r}")
        return AssignmentMatcher(
            self,
            (source_sha256, rom_sha256, sym_sha256, map_sha256),
            product=product,
        )

    def for_product(self, product: str = NORMAL_DEBUG_PRODUCT) -> DiscoveryAssignmentAuthority:
        """Return one fail-closed link-product partition of the authority."""
        if product not in ASSIGNMENT_PRODUCTS:
            raise DiscoveryAssignmentValidationError(
                f"assignments.product: unknown link product {product!r}"
            )
        return type(self)(tuple(row for row in self.rows if row.product == product))


class AssignmentMatcher:
    """Single-use exact matcher that projects only explicit review decisions."""

    def __init__(
        self,
        authority: DiscoveryAssignmentAuthority,
        baseline_hashes: tuple[str, str, str, str],
        *,
        product: str = NORMAL_DEBUG_PRODUCT,
    ) -> None:
        if any(not _SHA256.fullmatch(value) for value in baseline_hashes):
            raise StaleDiscoveryAssignmentError(
                "current baseline requires four lowercase SHA-256 hashes"
            )
        if product not in ASSIGNMENT_PRODUCTS:
            raise StaleDiscoveryAssignmentError(f"unknown assignment product {product!r}")
        selected = tuple(row for row in authority.rows if row.product == product)
        stale = tuple(row.id for row in selected if row.evidence.hashes != baseline_hashes)
        if stale:
            raise StaleDiscoveryAssignmentError(
                "assignment rows have stale baseline evidence: " + ", ".join(stale)
            )
        self._rows = {row.subject.sha256: row for row in selected}
        self._consumed: set[str] = set()

    def _consume(self, subject: RejectionSubject) -> AssignmentRow:
        row = self._rows.get(subject.sha256)
        if row is None or row.subject != subject:
            raise StaleDiscoveryAssignmentError(
                f"unreviewed discovery subject {subject.kind.value}:{subject.sha256}"
            )
        if row.id in self._consumed:
            raise DuplicateDiscoveryAssignmentConsumptionError(
                f"{row.id}: assignment row consumed more than once"
            )
        self._consumed.add(row.id)
        return row

    def project_source_finding(self, finding: SourceFinding) -> SourceFinding:
        if not isinstance(finding, SourceFinding):
            raise TypeError("expected SourceFinding")
        row = self._consume(source_finding_subject(finding))
        changes: dict[str, object] = {
            "category": row.category.value,
            "resolved": True,
        }
        if row.scene is not None:
            changes.update(
                row_kind=row.scene.row_kind.value,
                direction=row.scene.direction,
                destination_path=row.scene.destination_path,
                destination_line=row.scene.destination_line,
            )
            if row.scene.destination_symbol is not None:
                changes["destination"] = row.scene.destination_symbol
        if row.mutation is not None:
            changes["destination"] = row.mutation.destination
        return replace(finding, **changes)

    def project_rom_finding(self, finding: RomFinding) -> RomFinding:
        if not isinstance(finding, RomFinding):
            raise TypeError("expected RomFinding")
        row = self._consume(rom_finding_subject(finding))
        return replace(finding, category=row.category.value)

    @property
    def consumed_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._consumed))

    @property
    def consumed_row_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                row.row_id for row in self._rows.values() if row.id in self._consumed
            )
        )

    @property
    def stale_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                row.id for row in self._rows.values() if row.id not in self._consumed
            )
        )

    def assert_all_consumed(self) -> None:
        if self.stale_ids:
            raise StaleDiscoveryAssignmentError(
                "reviewed assignment rows were not rediscovered: "
                + ", ".join(self.stale_ids)
            )
