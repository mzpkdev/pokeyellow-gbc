"""Small strict-schema helpers shared by full-color verification contracts."""

from collections.abc import Mapping
from enum import Enum
from typing import Any, TypeVar

from .errors import ContractError

E = TypeVar("E", bound=Enum)


def require_object(
    value: object,
    *,
    path: str,
    required: set[str],
    optional: set[str] = frozenset(),
    error: type[ContractError] = ContractError,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise error(f"{path}: expected an object with string keys")
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing:
        raise error(f"{path}: missing required fields: {', '.join(missing)}")
    if unknown:
        raise error(f"{path}: unknown fields: {', '.join(unknown)}")
    return value


def require_str(
    value: object,
    *,
    path: str,
    allow_empty: bool = False,
    error: type[ContractError] = ContractError,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise error(f"{path}: expected a{' non-empty' if not allow_empty else ''} string")
    return value


def require_int(
    value: object,
    *,
    path: str,
    minimum: int = 0,
    maximum: int | None = None,
    error: type[ContractError] = ContractError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error(f"{path}: expected an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise error(f"{path}: expected integer {bound}, got {value}")
    return value


def require_bool(
    value: object,
    *,
    path: str,
    error: type[ContractError] = ContractError,
) -> bool:
    if not isinstance(value, bool):
        raise error(f"{path}: expected a boolean")
    return value


def require_enum(
    enum_type: type[E],
    value: object,
    *,
    path: str,
    error: type[ContractError] = ContractError,
) -> E:
    if not isinstance(value, str):
        raise error(f"{path}: expected a symbolic string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise error(f"{path}: unknown symbol {value!r}; expected one of {allowed}") from exc


def require_hex(
    value: object,
    *,
    path: str,
    length: int | None = None,
    error: type[ContractError] = ContractError,
) -> bytes:
    text = require_str(value, path=path, allow_empty=True, error=error)
    if len(text) % 2:
        raise error(f"{path}: hex data must contain complete bytes")
    try:
        decoded = bytes.fromhex(text)
    except ValueError as exc:
        raise error(f"{path}: invalid hexadecimal byte data") from exc
    if length is not None and len(decoded) != length:
        raise error(f"{path}: expected exactly {length} bytes, got {len(decoded)}")
    if text != decoded.hex():
        raise error(f"{path}: hex data must be canonical lowercase without separators")
    return decoded
