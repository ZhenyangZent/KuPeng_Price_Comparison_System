from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProvenanceContractError(ValueError):
    pass


@dataclass(frozen=True)
class ProvenanceResult:
    allowed: bool
    verifier_id: str
    decision: str
    reasons: tuple[str, ...]


class ProvenanceVerifier(Protocol):
    def verify(self, record: dict[str, object], *, input_sha256: str, record_sha256: str) -> ProvenanceResult: ...


class DefaultDenyVerifier:
    """Fail-closed verifier used whenever no exact C09 decision artifact is supplied."""

    def verify(self, record: dict[str, object], *, input_sha256: str, record_sha256: str) -> ProvenanceResult:
        del record, input_sha256, record_sha256
        return ProvenanceResult(False, "B12-DEFAULT-DENY", "DENY", ("C09_VERIFIER_UNAVAILABLE",))


