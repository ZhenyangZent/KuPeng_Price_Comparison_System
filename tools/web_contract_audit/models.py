from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    owner: str
    location: str
    detail: str
    reproduction: str
    needs_a06: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Assessment:
    findings: tuple[Finding, ...]
    checks: int

    @classmethod
    def from_iterable(cls, findings: Iterable[Finding], *, checks: int) -> "Assessment":
        return cls(tuple(findings), checks)

    @property
    def critical_or_high(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity in {"CRITICAL", "HIGH"})

    @property
    def passed(self) -> bool:
        return not self.critical_or_high

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "finding_count": len(self.findings),
            "findings": [item.to_dict() for item in self.findings],
        }
