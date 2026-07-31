"""Strict Gate 0b inventory contracts and exact reconciliation.

The checked-in authorities are intentionally data, not Python.  This module
defines their v1 wire format, rejects extensions by default, and emits
canonical JSON so reports are byte stable across machines.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, ClassVar

from .enums import Owner, Phase
from .errors import ContractError

WRITER_SCHEMA = "full-color-writer-inventory-v1"
SCENE_SCHEMA = "full-color-scene-inventory-v1"
MUTATION_SCHEMA = "full-color-mutation-inventory-v1"

_ID = {
    "writer": re.compile(r"WR-[A-Z0-9][A-Z0-9-]*\Z"),
    "scene": re.compile(r"SC-[A-Z0-9][A-Z0-9-]*\Z"),
    "mutation": re.compile(r"MU-[A-Z0-9][A-Z0-9-]*\Z"),
}
_REQ = re.compile(r"R(?:[1-9][0-9]*)(?:\.[1-9][0-9]*)?\Z")
_CHK = re.compile(r"CHK-[A-Z0-9][A-Z0-9-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class InventoryValidationError(ContractError):
    """A v1 inventory document is malformed or internally inconsistent."""


class InventoryReconciliationError(ContractError):
    """Discovery and the reviewed authorities do not reconcile exactly."""


class WriterKind(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    WRAPPER = "WRAPPER"
    DMA = "DMA"
    INTERRUPT = "INTERRUPT"


class WriterDisposition(StrEnum):
    KEEP = "KEEP"
    REPLACE = "REPLACE"
    ROUTE = "ROUTE"
    REMOVE = "REMOVE"
    PLANNED = "PLANNED"


class SceneRowKind(StrEnum):
    LIFECYCLE = "LIFECYCLE"
    DIRECTED_EDGE = "DIRECTED_EDGE"


class SceneClassification(StrEnum):
    MAP_BACKED = "MAP_BACKED"
    STANDALONE = "STANDALONE"
    SCENE_BOUNDARY = "SCENE_BOUNDARY"


class Reconstruction(StrEnum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"


class MutationBehavior(StrEnum):
    INITIAL_LOAD = "INITIAL_LOAD"
    RELOAD = "RELOAD"
    RECONSTRUCTION = "RECONSTRUCTION"
    SCROLL_HORIZONTAL = "SCROLL_HORIZONTAL"
    SCROLL_VERTICAL = "SCROLL_VERTICAL"
    CONNECTION_NORTH = "CONNECTION_NORTH"
    CONNECTION_SOUTH = "CONNECTION_SOUTH"
    CONNECTION_EAST = "CONNECTION_EAST"
    CONNECTION_WEST = "CONNECTION_WEST"
    ROW = "ROW"
    COLUMN = "COLUMN"
    RECTANGLE = "RECTANGLE"
    OVERLAY = "OVERLAY"
    ANIMATION = "ANIMATION"
    FIELD_REPLACEMENT = "FIELD_REPLACEMENT"
    MOVING_TILES = "MOVING_TILES"
    PALETTE = "PALETTE"
    OAM_BATCH = "OAM_BATCH"
    OAM_DMA = "OAM_DMA"


class MutationResource(StrEnum):
    BG_TILE_IDS = "BG_TILE_IDS"
    BG_ATTRIBUTES = "BG_ATTRIBUTES"
    WINDOW_TILE_IDS = "WINDOW_TILE_IDS"
    WINDOW_ATTRIBUTES = "WINDOW_ATTRIBUTES"
    TILE_DATA = "TILE_DATA"
    BG_PALETTES = "BG_PALETTES"
    OBJ_PALETTES = "OBJ_PALETTES"
    SHADOW_OAM = "SHADOW_OAM"
    HARDWARE_OAM = "HARDWARE_OAM"


class CommitUnit(StrEnum):
    BYTE = "BYTE"
    TILE_ATTRIBUTE_PAIR = "TILE_ATTRIBUTE_PAIR"
    ROW = "ROW"
    COLUMN = "COLUMN"
    RECTANGLE = "RECTANGLE"
    FULL_MAP = "FULL_MAP"
    PALETTE = "PALETTE"
    OAM_ENTRY = "OAM_ENTRY"
    OAM_FRAME = "OAM_FRAME"


def _object(
    raw: object, path: str, required: set[str], optional: set[str] = frozenset()
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or any(not isinstance(k, str) for k in raw):
        raise InventoryValidationError(f"{path}: expected object with string keys")
    missing = sorted(required - set(raw))
    unknown = sorted(set(raw) - required - optional)
    if missing:
        raise InventoryValidationError(f"{path}: missing fields: {', '.join(missing)}")
    if unknown:
        raise InventoryValidationError(f"{path}: unknown fields: {', '.join(unknown)}")
    return raw


def _str(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise InventoryValidationError(f"{path}: expected non-empty string")
    return raw


def _bool(raw: object, path: str) -> bool:
    if not isinstance(raw, bool):
        raise InventoryValidationError(f"{path}: expected boolean")
    return raw


def _int(raw: object, path: str, maximum: int | None = None) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise InventoryValidationError(f"{path}: expected non-negative integer")
    if maximum is not None and raw > maximum:
        raise InventoryValidationError(f"{path}: expected value <= {maximum}")
    return raw


def _enum(cls: type[StrEnum], raw: object, path: str) -> str:
    text = _str(raw, path)
    try:
        cls(text)
    except ValueError as exc:
        raise InventoryValidationError(
            f"{path}: unknown value {text!r}; expected "
            + ", ".join(item.value for item in cls)
        ) from exc
    return text


def _list(raw: object, path: str, *, nonempty: bool = False) -> list[object]:
    if not isinstance(raw, list) or (nonempty and not raw):
        qualifier = "non-empty " if nonempty else ""
        raise InventoryValidationError(f"{path}: expected {qualifier}array")
    return raw


def _strings(
    raw: object,
    path: str,
    *,
    nonempty: bool = False,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    values = tuple(
        _str(v, f"{path}[{i}]")
        for i, v in enumerate(_list(raw, path, nonempty=nonempty))
    )
    if len(set(values)) != len(values):
        raise InventoryValidationError(f"{path}: duplicate values")
    if tuple(sorted(values)) != values:
        raise InventoryValidationError(f"{path}: values must be sorted")
    if pattern:
        for value in values:
            if not pattern.fullmatch(value):
                raise InventoryValidationError(f"{path}: invalid value {value!r}")
    return values


def _relpath(raw: object, path: str) -> str:
    value = _str(raw, path)
    posix = PurePosixPath(value)
    if (
        posix.is_absolute()
        or value != str(posix)
        or "\\" in value
        or ".." in posix.parts
    ):
        raise InventoryValidationError(
            f"{path}: expected normalized repository-relative POSIX path"
        )
    return value


def _id(raw: object, path: str, kind: str) -> str:
    value = _str(raw, path)
    if not _ID[kind].fullmatch(value):
        raise InventoryValidationError(
            f"{path}: expected stable {_ID[kind].pattern[:-2]} ID"
        )
    return value


def _site(raw: object, path: str, *, machine: bool) -> dict[str, Any]:
    if machine:
        obj = _object(
            raw,
            path,
            {"bank", "address", "rom_offset", "bytes", "runtime_copy"},
        )
        bank = _int(obj["bank"], f"{path}.bank", 0x1FF)
        address = _int(obj["address"], f"{path}.address", 0xFFFF)
        offset = _int(obj["rom_offset"], f"{path}.rom_offset")
        byte_text = _str(obj["bytes"], f"{path}.bytes")
        if not re.fullmatch(r"(?:[0-9a-f]{2})+", byte_text):
            raise InventoryValidationError(
                f"{path}.bytes: expected canonical lowercase hex bytes"
            )
        runtime = obj["runtime_copy"]
        if runtime is not None:
            runtime_obj = _object(
                runtime, f"{path}.runtime_copy", {"address", "length", "launcher"}
            )
            runtime = {
                "address": _int(
                    runtime_obj["address"], f"{path}.runtime_copy.address", 0xFFFF
                ),
                "length": _int(
                    runtime_obj["length"], f"{path}.runtime_copy.length", 0x10000
                ),
                "launcher": _str(
                    runtime_obj["launcher"], f"{path}.runtime_copy.launcher"
                ),
            }
        if address < 0x4000:
            if bank != 0:
                raise InventoryValidationError(
                    f"{path}: bank {bank:#x} cannot map fixed-ROM address {address:04x}"
                )
            expected = address
        elif address <= 0x7FFF and 1 <= bank <= 0x1FF:
            expected = bank * 0x4000 + address - 0x4000
        else:
            raise InventoryValidationError(
                f"{path}: invalid ROM address {bank:#x}:{address:04x}"
            )
        if offset != expected:
            raise InventoryValidationError(
                f"{path}.rom_offset: {offset:#x} does not normalize bank {bank:#x}:{address:04x}"
            )
        return {
            "bank": bank,
            "address": address,
            "rom_offset": offset,
            "bytes": byte_text,
            "runtime_copy": runtime,
        }
    obj = _object(raw, path, {"path", "line", "symbol", "aliases", "object"})
    return {
        "path": _relpath(obj["path"], f"{path}.path"),
        "line": _int(obj["line"], f"{path}.line"),
        "symbol": _str(obj["symbol"], f"{path}.symbol"),
        "aliases": list(_strings(obj["aliases"], f"{path}.aliases")),
        "object": None
        if obj["object"] is None
        else _relpath(obj["object"], f"{path}.object"),
    }


def _evidence(raw: object, path: str) -> dict[str, Any]:
    obj = _object(
        raw,
        path,
        {
            "source_sha256",
            "rom_sha256",
            "sym_sha256",
            "map_sha256",
            "reviewer",
            "reviewed",
        },
    )
    hashes = {
        name: _str(obj[name], f"{path}.{name}")
        for name in ("source_sha256", "rom_sha256", "sym_sha256", "map_sha256")
    }
    if any(not _SHA256.fullmatch(value) for value in hashes.values()):
        raise InventoryValidationError(f"{path}: hashes must be lowercase SHA-256")
    return {
        **hashes,
        "reviewer": _str(obj["reviewer"], f"{path}.reviewer"),
        "reviewed": _bool(obj["reviewed"], f"{path}.reviewed"),
    }


def _references(obj: Mapping[str, Any], path: str) -> tuple[list[str], list[str]]:
    requirements = list(
        _strings(
            obj["requirements"], f"{path}.requirements", nonempty=True, pattern=_REQ
        )
    )
    checks = list(
        _strings(obj["checks"], f"{path}.checks", nonempty=True, pattern=_CHK)
    )
    return requirements, checks


def _endpoint(raw: object, path: str) -> dict[str, Any]:
    obj = _object(raw, path, {"path", "line", "symbol", "aliases"})
    return {
        "path": _relpath(obj["path"], f"{path}.path"),
        "line": _int(obj["line"], f"{path}.line"),
        "symbol": _str(obj["symbol"], f"{path}.symbol"),
        "aliases": list(_strings(obj["aliases"], f"{path}.aliases")),
    }


def _reachability(raw: object, path: str) -> dict[str, Any]:
    obj = _object(raw, path, {"roots", "call_paths", "scenes", "phases", "interrupt"})
    roots = list(_strings(obj["roots"], f"{path}.roots", nonempty=True))
    paths = _list(obj["call_paths"], f"{path}.call_paths", nonempty=True)
    call_paths: list[list[str]] = []
    for index, item in enumerate(paths):
        raw_path = _list(item, f"{path}.call_paths[{index}]", nonempty=True)
        call_path = [
            _str(value, f"{path}.call_paths[{index}][{part}]")
            for part, value in enumerate(raw_path)
        ]
        call_paths.append(call_path)
    if call_paths != sorted(call_paths):
        raise InventoryValidationError(f"{path}.call_paths: paths must be sorted")
    scenes = list(_strings(obj["scenes"], f"{path}.scenes", pattern=_ID["scene"]))
    phases = list(_strings(obj["phases"], f"{path}.phases", nonempty=True))
    for index, phase in enumerate(phases):
        _enum(Phase, phase, f"{path}.phases[{index}]")
    return {
        "roots": roots,
        "call_paths": call_paths,
        "scenes": scenes,
        "phases": phases,
        "interrupt": _bool(obj["interrupt"], f"{path}.interrupt"),
    }


def _resource_range(raw: object, path: str) -> dict[str, Any]:
    obj = _object(raw, path, {"resource", "start", "end", "vram_bank", "aliases"})
    start = _int(obj["start"], f"{path}.start", 0xFFFF)
    end = _int(obj["end"], f"{path}.end", 0xFFFF)
    if end < start:
        raise InventoryValidationError(f"{path}: end precedes start")
    vbk = obj["vram_bank"]
    if vbk is not None and vbk not in (0, 1):
        raise InventoryValidationError(f"{path}.vram_bank: expected null, 0, or 1")
    return {
        "resource": _str(obj["resource"], f"{path}.resource"),
        "start": start,
        "end": end,
        "vram_bank": vbk,
        "aliases": list(_strings(obj["aliases"], f"{path}.aliases")),
    }


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


@dataclass(frozen=True, slots=True)
class InventoryDocument:
    rows: tuple[dict[str, Any], ...]
    schema: ClassVar[str]
    kind: ClassVar[str]

    @classmethod
    def from_dict(cls, raw: object) -> "InventoryDocument":
        obj = _object(raw, cls.kind, {"schema", "rows"})
        if obj["schema"] != cls.schema:
            raise InventoryValidationError(
                f"{cls.kind}.schema: expected {cls.schema!r}, got {obj['schema']!r}"
            )
        rows = tuple(
            cls._validate_row(row, f"{cls.kind}.rows[{index}]")
            for index, row in enumerate(_list(obj["rows"], f"{cls.kind}.rows"))
        )
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise InventoryValidationError(f"{cls.kind}.rows: duplicate IDs")
        if ids != sorted(ids):
            raise InventoryValidationError(
                f"{cls.kind}.rows: rows must be sorted by ID"
            )
        cls._validate_relations(rows)
        return cls(rows)

    @classmethod
    def from_json(cls, text: str | bytes) -> "InventoryDocument":
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InventoryValidationError(f"{cls.kind}: invalid JSON") from exc
        return cls.from_dict(raw)

    @classmethod
    def load(cls, path: str | Path) -> "InventoryDocument":
        return cls.from_json(Path(path).read_bytes())

    @classmethod
    def _validate_row(cls, raw: object, path: str) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def _validate_relations(cls, rows: Sequence[dict[str, Any]]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "rows": [dict(row) for row in self.rows]}

    def to_json(self) -> str:
        return _canonical(self.to_dict()).decode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class WriterInventory(InventoryDocument):
    schema: ClassVar[str] = WRITER_SCHEMA
    kind: ClassVar[str] = "writers"

    @classmethod
    def _validate_row(cls, raw: object, path: str) -> dict[str, Any]:
        obj = _object(
            raw,
            path,
            {
                "id",
                "resources",
                "source_sites",
                "machine_sites",
                "kind",
                "wrappers",
                "downstream",
                "reachability",
                "owner",
                "generation_checked",
                "bank_restore_permission",
                "commit_unit",
                "disposition",
                "requirements",
                "checks",
                "evidence",
                "planned",
            },
        )
        source = [
            _site(v, f"{path}.source_sites[{i}]", machine=False)
            for i, v in enumerate(
                _list(obj["source_sites"], f"{path}.source_sites", nonempty=True)
            )
        ]
        machine = [
            _site(v, f"{path}.machine_sites[{i}]", machine=True)
            for i, v in enumerate(_list(obj["machine_sites"], f"{path}.machine_sites"))
        ]
        if source != sorted(source, key=lambda s: (s["path"], s["line"], s["symbol"])):
            raise InventoryValidationError(f"{path}.source_sites: sites must be sorted")
        if machine != sorted(machine, key=lambda s: (s["bank"], s["address"])):
            raise InventoryValidationError(
                f"{path}.machine_sites: sites must be sorted"
            )
        requirements, checks = _references(obj, path)
        return {
            "id": _id(obj["id"], f"{path}.id", "writer"),
            "resources": [
                _resource_range(v, f"{path}.resources[{i}]")
                for i, v in enumerate(
                    _list(obj["resources"], f"{path}.resources", nonempty=True)
                )
            ],
            "source_sites": source,
            "machine_sites": machine,
            "kind": _enum(WriterKind, obj["kind"], f"{path}.kind"),
            "wrappers": list(
                _strings(obj["wrappers"], f"{path}.wrappers", pattern=_ID["writer"])
            ),
            "downstream": list(
                _strings(obj["downstream"], f"{path}.downstream", pattern=_ID["writer"])
            ),
            "reachability": _reachability(obj["reachability"], f"{path}.reachability"),
            "owner": _enum(Owner, obj["owner"], f"{path}.owner"),
            "generation_checked": _bool(
                obj["generation_checked"], f"{path}.generation_checked"
            ),
            "bank_restore_permission": _bool(
                obj["bank_restore_permission"], f"{path}.bank_restore_permission"
            ),
            "commit_unit": _str(obj["commit_unit"], f"{path}.commit_unit"),
            "disposition": _enum(
                WriterDisposition, obj["disposition"], f"{path}.disposition"
            ),
            "requirements": requirements,
            "checks": checks,
            "evidence": _evidence(obj["evidence"], f"{path}.evidence"),
            "planned": _bool(obj["planned"], f"{path}.planned"),
        }

    @classmethod
    def _validate_relations(cls, rows: Sequence[dict[str, Any]]) -> None:
        ids = {row["id"] for row in rows}
        source_keys: list[tuple[str, int, str]] = []
        machine_keys: list[tuple[int, int]] = []
        for row in rows:
            links = set(row["wrappers"]) | set(row["downstream"])
            missing = sorted(links - ids)
            if missing:
                raise InventoryValidationError(
                    f"{row['id']}: unknown writer links {missing}"
                )
            if (
                row["kind"] in {WriterKind.WRAPPER, WriterKind.DMA}
                and not row["downstream"]
            ):
                raise InventoryValidationError(
                    f"{row['id']}: wrapper/DMA requires downstream writer"
                )
            if row["id"] in links:
                raise InventoryValidationError(
                    f"{row['id']}: writer relationship cannot be self-referential"
                )
            source_keys.extend(
                (s["path"], s["line"], s["symbol"]) for s in row["source_sites"]
            )
            machine_keys.extend((s["bank"], s["address"]) for s in row["machine_sites"])
        if any(count > 1 for count in Counter(source_keys).values()):
            raise InventoryValidationError("writers: duplicate source site across rows")
        if any(count > 1 for count in Counter(machine_keys).values()):
            raise InventoryValidationError(
                "writers: duplicate machine site across rows"
            )


@dataclass(frozen=True, slots=True)
class SceneInventory(InventoryDocument):
    schema: ClassVar[str] = SCENE_SCHEMA
    kind: ClassVar[str] = "scenes"

    @classmethod
    def _validate_row(cls, raw: object, path: str) -> dict[str, Any]:
        obj = _object(
            raw,
            path,
            {
                "id",
                "row_kind",
                "source",
                "destination",
                "classification",
                "direction",
                "owner_before_destination_initialization",
                "first_display_writers",
                "reconstruction",
                "edges",
                "machine_sites",
                "requirements",
                "checks",
                "evidence",
                "planned",
            },
        )
        row_kind = _enum(SceneRowKind, obj["row_kind"], f"{path}.row_kind")
        destination = (
            None
            if obj["destination"] is None
            else _endpoint(obj["destination"], f"{path}.destination")
        )
        direction = obj["direction"]
        if row_kind == SceneRowKind.DIRECTED_EDGE:
            if destination is None or direction not in {
                "YELLOW_TO_MAP",
                "MAP_TO_YELLOW",
                "YELLOW_TO_YELLOW",
                "MAP_TO_MAP",
            }:
                raise InventoryValidationError(
                    f"{path}: directed edge requires destination and direction"
                )
        elif destination is not None or direction is not None:
            raise InventoryValidationError(
                f"{path}: lifecycle has no destination or direction"
            )
        classification = _enum(
            SceneClassification, obj["classification"], f"{path}.classification"
        )
        reconstruction = _enum(
            Reconstruction, obj["reconstruction"], f"{path}.reconstruction"
        )
        if reconstruction == Reconstruction.REQUIRED and direction != "YELLOW_TO_MAP":
            raise InventoryValidationError(
                f"{path}: reconstruction is required only on YELLOW_TO_MAP edges"
            )
        edges_obj = _object(
            obj["edges"], f"{path}.edges", {"normal", "reset", "nested", "error"}
        )
        edges = {
            name: [
                _endpoint(v, f"{path}.edges.{name}[{i}]")
                for i, v in enumerate(_list(edges_obj[name], f"{path}.edges.{name}"))
            ]
            for name in ("normal", "reset", "nested", "error")
        }
        machine = [
            _site(value, f"{path}.machine_sites[{index}]", machine=True)
            for index, value in enumerate(
                _list(obj["machine_sites"], f"{path}.machine_sites", nonempty=True)
            )
        ]
        if machine != sorted(machine, key=lambda site: (site["bank"], site["address"])):
            raise InventoryValidationError(
                f"{path}.machine_sites: sites must be sorted"
            )
        requirements, checks = _references(obj, path)
        return {
            "id": _id(obj["id"], f"{path}.id", "scene"),
            "row_kind": row_kind,
            "source": _endpoint(obj["source"], f"{path}.source"),
            "destination": destination,
            "classification": classification,
            "direction": direction,
            "owner_before_destination_initialization": _enum(
                Owner,
                obj["owner_before_destination_initialization"],
                f"{path}.owner_before_destination_initialization",
            ),
            "first_display_writers": list(
                _strings(
                    obj["first_display_writers"],
                    f"{path}.first_display_writers",
                    nonempty=True,
                    pattern=_ID["writer"],
                )
            ),
            "reconstruction": reconstruction,
            "edges": edges,
            "machine_sites": machine,
            "requirements": requirements,
            "checks": checks,
            "evidence": _evidence(obj["evidence"], f"{path}.evidence"),
            "planned": _bool(obj["planned"], f"{path}.planned"),
        }

    @classmethod
    def _validate_relations(cls, rows: Sequence[dict[str, Any]]) -> None:
        edge_keys: list[tuple[object, ...]] = []
        machine_keys: list[tuple[int, int]] = []
        for row in rows:
            destination = row["destination"]
            edge_keys.append(
                (
                    row["row_kind"],
                    row["direction"],
                    row["source"]["path"],
                    row["source"]["line"],
                    row["source"]["symbol"],
                    None if destination is None else destination["path"],
                    None if destination is None else destination["line"],
                    None if destination is None else destination["symbol"],
                )
            )
            machine_keys.extend(
                (site["bank"], site["address"]) for site in row["machine_sites"]
            )
        if any(count > 1 for count in Counter(edge_keys).values()):
            raise InventoryValidationError(
                "scenes: duplicate lifecycle/directed edge across rows"
            )
        if any(count > 1 for count in Counter(machine_keys).values()):
            raise InventoryValidationError(
                "scenes: duplicate machine control-flow site across rows"
            )


@dataclass(frozen=True, slots=True)
class MutationInventory(InventoryDocument):
    schema: ClassVar[str] = MUTATION_SCHEMA
    kind: ClassVar[str] = "mutations"

    @classmethod
    def _validate_row(cls, raw: object, path: str) -> dict[str, Any]:
        obj = _object(
            raw,
            path,
            {
                "id",
                "behavior",
                "resources",
                "commit_unit",
                "source_sites",
                "machine_sites",
                "reachability",
                "trigger",
                "destination",
                "coordinate_handling",
                "clipping",
                "wrapping",
                "tile_source",
                "attribute_source",
                "dependencies",
                "baseline_commits",
                "required_commits",
                "owner",
                "phases",
                "generation_checked",
                "writer_ids",
                "disposition",
                "requirements",
                "checks",
                "evidence",
                "planned",
            },
        )
        source = [
            _site(v, f"{path}.source_sites[{i}]", machine=False)
            for i, v in enumerate(
                _list(obj["source_sites"], f"{path}.source_sites", nonempty=True)
            )
        ]
        machine = [
            _site(v, f"{path}.machine_sites[{i}]", machine=True)
            for i, v in enumerate(_list(obj["machine_sites"], f"{path}.machine_sites"))
        ]
        resources = list(_strings(obj["resources"], f"{path}.resources", nonempty=True))
        for index, resource in enumerate(resources):
            _enum(MutationResource, resource, f"{path}.resources[{index}]")
        phases = list(_strings(obj["phases"], f"{path}.phases", nonempty=True))
        for index, phase in enumerate(phases):
            _enum(Phase, phase, f"{path}.phases[{index}]")
        dependencies = list(
            _strings(obj["dependencies"], f"{path}.dependencies", nonempty=True)
        )
        baseline = list(_strings(obj["baseline_commits"], f"{path}.baseline_commits"))
        required = list(
            _strings(obj["required_commits"], f"{path}.required_commits", nonempty=True)
        )
        if not set(baseline) <= set(required):
            raise InventoryValidationError(
                f"{path}: baseline_commits must be a subset of required_commits"
            )
        requirements, checks = _references(obj, path)
        return {
            "id": _id(obj["id"], f"{path}.id", "mutation"),
            "behavior": _enum(MutationBehavior, obj["behavior"], f"{path}.behavior"),
            "resources": resources,
            "commit_unit": _enum(CommitUnit, obj["commit_unit"], f"{path}.commit_unit"),
            "source_sites": source,
            "machine_sites": machine,
            "reachability": _reachability(obj["reachability"], f"{path}.reachability"),
            "trigger": _str(obj["trigger"], f"{path}.trigger"),
            "destination": _str(obj["destination"], f"{path}.destination"),
            "coordinate_handling": _str(
                obj["coordinate_handling"], f"{path}.coordinate_handling"
            ),
            "clipping": _str(obj["clipping"], f"{path}.clipping"),
            "wrapping": _str(obj["wrapping"], f"{path}.wrapping"),
            "tile_source": _str(obj["tile_source"], f"{path}.tile_source"),
            "attribute_source": _str(
                obj["attribute_source"], f"{path}.attribute_source"
            ),
            "dependencies": dependencies,
            "baseline_commits": baseline,
            "required_commits": required,
            "owner": _enum(Owner, obj["owner"], f"{path}.owner"),
            "phases": phases,
            "generation_checked": _bool(
                obj["generation_checked"], f"{path}.generation_checked"
            ),
            "writer_ids": list(
                _strings(
                    obj["writer_ids"],
                    f"{path}.writer_ids",
                    nonempty=True,
                    pattern=_ID["writer"],
                )
            ),
            "disposition": _enum(
                WriterDisposition, obj["disposition"], f"{path}.disposition"
            ),
            "requirements": requirements,
            "checks": checks,
            "evidence": _evidence(obj["evidence"], f"{path}.evidence"),
            "planned": _bool(obj["planned"], f"{path}.planned"),
        }

    @classmethod
    def _validate_relations(cls, rows: Sequence[dict[str, Any]]) -> None:
        source_keys: list[tuple[object, ...]] = []
        machine_keys: list[tuple[int, int]] = []
        behavior_keys: list[tuple[object, ...]] = []
        for row in rows:
            source_keys.extend(
                (site["path"], site["line"], site["symbol"], row["destination"])
                for site in row["source_sites"]
            )
            machine_keys.extend(
                (site["bank"], site["address"]) for site in row["machine_sites"]
            )
            behavior_keys.append(
                (
                    row["behavior"],
                    row["destination"],
                    row["commit_unit"],
                    tuple(row["resources"]),
                    tuple(
                        (site["path"], site["line"], site["symbol"])
                        for site in row["source_sites"]
                    ),
                )
            )
        if any(count > 1 for count in Counter(source_keys).values()):
            raise InventoryValidationError(
                "mutations: duplicate source/destination site across rows"
            )
        if any(count > 1 for count in Counter(machine_keys).values()):
            raise InventoryValidationError(
                "mutations: duplicate machine site across rows"
            )
        if any(count > 1 for count in Counter(behavior_keys).values()):
            raise InventoryValidationError("mutations: duplicate behavior row")


def validate_cross_references(
    writers: WriterInventory, scenes: SceneInventory, mutations: MutationInventory
) -> None:
    writer_ids = {row["id"] for row in writers.rows}
    scene_ids = {row["id"] for row in scenes.rows}
    errors: list[str] = []
    writer_machine_sites = {
        (site["bank"], site["address"])
        for row in writers.rows
        for site in row["machine_sites"]
    }
    for row in writers.rows:
        errors.extend(
            f"{row['id']}: unknown scene {value}"
            for value in row["reachability"]["scenes"]
            if value not in scene_ids
        )
    for row in scenes.rows:
        errors.extend(
            f"{row['id']}: unknown first display writer {value}"
            for value in row["first_display_writers"]
            if value not in writer_ids
        )
    for row in mutations.rows:
        errors.extend(
            f"{row['id']}: unknown writer {value}"
            for value in row["writer_ids"]
            if value not in writer_ids
        )
        for site in row["machine_sites"]:
            if (site["bank"], site["address"]) in writer_machine_sites:
                errors.append(
                    f"{row['id']}: duplicates writer machine site "
                    f"{site['bank']:02x}:{site['address']:04x}; "
                    "reference it through writer_ids"
                )
        errors.extend(
            f"{row['id']}: unknown scene {value}"
            for value in row["reachability"]["scenes"]
            if value not in scene_ids
        )
    if errors:
        raise InventoryValidationError("\n".join(sorted(errors)))


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    matched_source_sites: tuple[str, ...]
    matched_machine_sites: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def closed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "full-color-inventory-reconciliation-v1",
            "closed": self.closed,
            "matched_source_sites": list(self.matched_source_sites),
            "matched_machine_sites": list(self.matched_machine_sites),
            "errors": list(self.errors),
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict()).decode()


def _finding_attr(finding: object, name: str, default: object = None) -> object:
    return (
        finding.get(name, default)
        if isinstance(finding, Mapping)
        else getattr(finding, name, default)
    )


def reconcile(
    writers: WriterInventory,
    scenes: SceneInventory,
    mutations: MutationInventory,
    *,
    source_report: object,
    rom_report: object,
    rom: bytes,
    raise_on_error: bool = True,
) -> ReconciliationReport:
    """Reconcile complete discovery reports to all three reviewed authorities."""
    validate_cross_references(writers, scenes, mutations)
    errors: list[str] = []
    authorities = {
        "writer": writers.rows,
        "scene": scenes.rows,
        "mutation": mutations.rows,
    }
    for name, authority_rows in authorities.items():
        if not authority_rows:
            errors.append(f"{name} authority is empty")
    if not isinstance(rom, bytes) or not rom:
        errors.append("non-empty immutable ROM bytes are required")
        rom = bytes(rom) if isinstance(rom, (bytes, bytearray)) else b""

    required_source_fields = ("roots", "findings", "errors", "source_sha256")
    required_rom_fields = (
        "findings",
        "unresolved_destinations",
        "unresolved_control_flow",
        "visited",
        "rom_sha256",
        "sym_sha256",
        "map_sha256",
        "candidate_findings",
        "candidate_sections",
    )
    if any(not hasattr(source_report, name) for name in required_source_fields):
        errors.append("complete SourceDiscoveryReport is required")
        source_findings: tuple[object, ...] = ()
        source_errors: tuple[str, ...] = ()
        source_roots: tuple[str, ...] = ()
        source_hash = ""
    else:
        source_findings = tuple(getattr(source_report, "findings"))
        source_errors = tuple(getattr(source_report, "errors"))
        source_roots = tuple(getattr(source_report, "roots"))
        source_hash = str(getattr(source_report, "source_sha256"))
    if any(not hasattr(rom_report, name) for name in required_rom_fields):
        errors.append("complete RomDiscoveryReport is required")
        rom_findings: tuple[object, ...] = ()
        candidates: tuple[object, ...] = ()
        candidate_sections: tuple[object, ...] = ()
        rom_unresolved: tuple[str, ...] = ()
        control_unresolved: tuple[str, ...] = ()
        visited: tuple[object, ...] = ()
        report_hashes = {"rom_sha256": "", "sym_sha256": "", "map_sha256": ""}
    else:
        rom_findings = tuple(getattr(rom_report, "findings"))
        candidates = tuple(getattr(rom_report, "candidate_findings"))
        candidate_sections = tuple(getattr(rom_report, "candidate_sections"))
        rom_unresolved = tuple(getattr(rom_report, "unresolved_destinations"))
        control_unresolved = tuple(getattr(rom_report, "unresolved_control_flow"))
        visited = tuple(getattr(rom_report, "visited"))
        report_hashes = {
            name: str(getattr(rom_report, name))
            for name in ("rom_sha256", "sym_sha256", "map_sha256")
        }

    if not source_roots:
        errors.append("source discovery has no roots")
    if not source_findings:
        errors.append("source discovery has no findings")
    errors.extend(f"source discovery error: {item}" for item in source_errors)
    if not rom_findings:
        errors.append("ROM discovery has no findings")
    if not visited:
        errors.append("ROM discovery visited no instructions")
    if not candidate_sections:
        errors.append("ROM candidate scan has no linker sections")
    errors.extend(f"ROM unresolved destination: {item}" for item in rom_unresolved)
    errors.extend(f"ROM unresolved control flow: {item}" for item in control_unresolved)

    all_hashes = {"source_sha256": source_hash, **report_hashes}
    for name, value in all_hashes.items():
        if not _SHA256.fullmatch(value):
            errors.append(f"{name} is missing or not a lowercase SHA-256")
    actual_rom_hash = hashlib.sha256(rom).hexdigest() if rom else ""
    if report_hashes["rom_sha256"] != actual_rom_hash:
        errors.append(
            f"ROM report hash {report_hashes['rom_sha256']} "
            f"does not match bytes {actual_rom_hash}"
        )

    section_ranges: list[tuple[int, int, int]] = []
    for index, section in enumerate(candidate_sections):
        try:
            bank = int(_finding_attr(section, "bank", -1))
            start = int(_finding_attr(section, "start", -1))
            end = int(_finding_attr(section, "end", -1))
            region = str(_finding_attr(section, "region", ""))
            name = str(_finding_attr(section, "name", ""))
            if region == "ROM0":
                valid = bank == 0 and 0 <= start <= end < 0x4000
            elif region == "ROMX":
                valid = bank > 0 and 0x4000 <= start <= end <= 0x7FFF
            else:
                valid = False
            end_offset = end if bank == 0 else bank * 0x4000 + end - 0x4000
            if not name or not valid or end_offset >= len(rom):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"ROM candidate section {index} is invalid")
            continue
        section_ranges.append((bank, start, end))

    for left, right in zip(sorted(section_ranges), sorted(section_ranges)[1:]):
        if left[0] == right[0] and right[1] <= left[2]:
            errors.append("ROM candidate linker sections overlap")

    candidate_opcodes = {
        0xE0,
        0xE2,
        0xEA,
        0x08,
        0x02,
        0x12,
        0x22,
        0x32,
        0x36,
        *range(0x70, 0x76),
        0x77,
    }
    for offset, opcode in enumerate(rom):
        if opcode not in candidate_opcodes:
            continue
        bank = 0 if offset < 0x4000 else offset // 0x4000
        address = offset if bank == 0 else 0x4000 + offset % 0x4000
        if not any(
            item_bank == bank and start <= address <= end
            for item_bank, start, end in section_ranges
        ):
            errors.append(f"ROM candidate scan coverage omits {bank:02x}:{address:04x}")

    candidate_sites = {
        (
            int(_finding_attr(finding, "bank", -1)),
            int(_finding_attr(finding, "address", -1)),
        )
        for finding in candidates
    }
    for bank, address in candidate_sites:
        if not any(
            item_bank == bank and start <= address <= end
            for item_bank, start, end in section_ranges
        ):
            errors.append(
                "ROM candidate finding lies outside linker sections at "
                f"{bank:02x}:{address:04x}"
            )
    for bank, start, end in section_ranges:
        for address in range(start, end + 1):
            offset = address if bank == 0 else bank * 0x4000 + address - 0x4000
            if rom[offset] == 0x36 and (bank, address) not in candidate_sites:
                errors.append(
                    "ROM candidate findings omit LD [HL],n8 at "
                    f"{bank:02x}:{address:04x}"
                )

    rows = list(writers.rows) + list(scenes.rows) + list(mutations.rows)
    for row in rows:
        if not row["evidence"]["reviewed"]:
            errors.append(f"{row['id']}: unreviewed row")
        for hash_name, expected in all_hashes.items():
            if row["evidence"][hash_name] != expected:
                errors.append(
                    f"{row['id']}: stale {hash_name.removesuffix('_sha256')} hash"
                )
        for site in row.get("machine_sites", ()):
            expected_bytes = bytes.fromhex(site["bytes"])
            start = site["rom_offset"]
            if rom[start : start + len(expected_bytes)] != expected_bytes:
                errors.append(
                    f"{row['id']}: machine bytes do not match "
                    f"{site['bank']:02x}:{site['address']:04x}"
                )

    source_index: dict[tuple[object, ...], list[str]] = defaultdict(list)
    machine_index: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for category, authority_rows in (
        ("writer", writers.rows),
        ("mutation", mutations.rows),
    ):
        for row in authority_rows:
            for site in row["source_sites"]:
                key: tuple[object, ...]
                if category == "mutation":
                    key = (
                        category,
                        site["path"],
                        site["line"],
                        site["symbol"],
                        row["destination"],
                    )
                else:
                    key = (category, site["path"], site["line"], site["symbol"])
                source_index[key].append(row["id"])
            for site in row["machine_sites"]:
                machine_index[(category, site["bank"], site["address"])].append(
                    row["id"]
                )
    for row in scenes.rows:
        destination = row["destination"]
        key = (
            "scene",
            row["row_kind"],
            row["direction"],
            row["source"]["path"],
            row["source"]["line"],
            row["source"]["symbol"],
            None if destination is None else destination["path"],
            None if destination is None else destination["line"],
            None if destination is None else destination["symbol"],
        )
        source_index[key].append(row["id"])
        for site in row["machine_sites"]:
            machine_index[("scene", site["bank"], site["address"])].append(row["id"])

    for key, row_ids in source_index.items():
        if len(row_ids) != 1:
            errors.append(f"source authority key overwrites multiple rows: {key!r}")
    for key, row_ids in machine_index.items():
        if len(row_ids) != 1:
            errors.append(f"machine authority key overwrites multiple rows: {key!r}")

    seen_source: list[tuple[object, ...]] = []
    matched_rows: set[str] = set()
    for finding in source_findings:
        category = str(_finding_attr(finding, "category", "")).lower()
        if category in {"scene_edge", "lifecycle"}:
            category = "scene"
        path = str(_finding_attr(finding, "path", ""))
        line = int(_finding_attr(finding, "line", 0))
        symbol = str(_finding_attr(finding, "symbol", ""))
        if category == "scene":
            row_kind = _finding_attr(finding, "row_kind")
            lifecycle = str(row_kind).upper() == "LIFECYCLE"
            key = (
                category,
                row_kind,
                _finding_attr(finding, "direction"),
                path,
                line,
                symbol,
                None if lifecycle else _finding_attr(finding, "destination_path", path),
                None if lifecycle else _finding_attr(finding, "destination_line", 0),
                None if lifecycle else _finding_attr(finding, "destination"),
            )
        elif category == "mutation":
            key = (
                category,
                path,
                line,
                symbol,
                _finding_attr(finding, "destination"),
            )
        else:
            key = (category, path, line, symbol)
        seen_source.append(key)
        if category not in authorities:
            errors.append(f"source finding has missing/unknown category {category!r}")
        if _finding_attr(finding, "resolved", False) is not True:
            errors.append(f"source unresolved finding {path}:{line}:{symbol}")
        row_ids = source_index.get(key, ())
        if len(row_ids) != 1:
            errors.append(
                f"source orphan finding or ambiguous key {path}:{line}:{symbol}"
            )
        else:
            matched_rows.add(row_ids[0])
    for key, row_ids in source_index.items():
        if key not in seen_source:
            errors.append(f"{row_ids[0]}: stale source site/authority key {key!r}")
    if any(count > 1 for count in Counter(seen_source).values()):
        errors.append("duplicate source findings")

    seen_machine: list[tuple[str, int, int]] = []
    resolved_report_sites = {
        (
            str(_finding_attr(finding, "category", "writer")).lower(),
            int(_finding_attr(finding, "bank", -1)),
            int(_finding_attr(finding, "address", -1)),
        )
        for finding in rom_findings
        if _finding_attr(finding, "resolved", False) is True
    }
    unresolved_candidates = tuple(
        finding
        for finding in candidates
        if (
            str(_finding_attr(finding, "category", "writer")).lower(),
            int(_finding_attr(finding, "bank", -1)),
            int(_finding_attr(finding, "address", -1)),
        )
        not in resolved_report_sites
    )
    all_rom_findings = rom_findings + unresolved_candidates
    unique_rom_findings: dict[tuple[object, ...], object] = {}
    for finding in all_rom_findings:
        identity = (
            _finding_attr(finding, "category", "writer"),
            _finding_attr(finding, "bank", -1),
            _finding_attr(finding, "address", -1),
            _finding_attr(finding, "destination_low"),
            _finding_attr(finding, "destination_high"),
            _finding_attr(finding, "control_flow_kind"),
        )
        unique_rom_findings.setdefault(identity, finding)
    for finding in unique_rom_findings.values():
        category = str(_finding_attr(finding, "category", "writer")).lower()
        bank = int(_finding_attr(finding, "bank", -1))
        address = int(_finding_attr(finding, "address", -1))
        key = (category, bank, address)
        seen_machine.append(key)
        if _finding_attr(finding, "resolved", False) is not True:
            errors.append(f"ROM/candidate unresolved finding {bank:02x}:{address:04x}")
        row_ids = machine_index.get(key, ())
        if len(row_ids) != 1:
            errors.append(f"ROM orphan/ambiguous finding {bank:02x}:{address:04x}")
        else:
            matched_rows.add(row_ids[0])
    for key, row_ids in machine_index.items():
        if key not in seen_machine:
            errors.append(f"{row_ids[0]}: stale machine site {key[1]:02x}:{key[2]:04x}")
    if any(count > 1 for count in Counter(seen_machine).values()):
        errors.append("multiple ROM findings cover one directed/site authority key")

    source_categories = {
        (
            "scene"
            if str(_finding_attr(item, "category", "")).lower()
            in {"scene", "scene_edge", "lifecycle"}
            else str(_finding_attr(item, "category", "")).lower()
        )
        for item in source_findings
    }
    for category in authorities:
        if category not in source_categories:
            errors.append(f"source discovery has no applicable {category} finding")

    for row in rows:
        if row["planned"] and row["id"] in matched_rows:
            errors.append(f"{row['id']}: planned row is reachable before review")

    report = ReconciliationReport(
        tuple(sorted(repr(key) for key in set(seen_source) & set(source_index))),
        tuple(
            sorted(
                f"{category}:{bank:02x}:{address:04x}"
                for category, bank, address in set(seen_machine) & set(machine_index)
            )
        ),
        tuple(sorted(set(errors))),
    )
    if report.errors and raise_on_error:
        raise InventoryReconciliationError("\n".join(report.errors))
    return report
