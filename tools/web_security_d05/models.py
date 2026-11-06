from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    priority: str
    owner: str
    title: str
    location: str
    detail: str
    reproduction: str
    suggested_regression: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Check:
    check_id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)
