"""Specific failures emitted by Gate 0 contract validators."""


class ContractError(ValueError):
    """Base class for invalid contract data."""


class SnapshotValidationError(ContractError):
    """A semantic snapshot does not satisfy its versioned schema."""


class TraceDecodeError(ContractError):
    """A bounded writer trace cannot be decoded safely."""


class ModelViolation(ContractError):
    """An ownership-model action violates the normative state machine."""


class ManifestValidationError(ContractError):
    """An artifact manifest is malformed or has broken linkage."""


class TraceabilityError(ContractError):
    """A requirement/acceptance/check mapping is not closed."""


class BankTortureError(ContractError):
    """A synthetic bank-boundary fixture is malformed or leaks machine state."""
